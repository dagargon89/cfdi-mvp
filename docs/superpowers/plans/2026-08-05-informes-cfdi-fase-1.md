# Informes CFDI — Fase 1: capa normalizada + motor de informes + B-02

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persistir el contenido completo de los XML ya resguardados en 15 tablas normalizadas y entregar el informe B-02 ("Nómina agrupada por conceptos del patrón") como libro de Excel descargable.

**Architecture:** Un servicio de parseo **puro** (`bytes` → dataclasses, sin BD) alimenta un escritor idempotente por `comprobante_id`. Sobre las tablas resultantes, un registro de informes expone cada informe como un módulo con parámetros pydantic, una consulta y un escritor de Excel. La entrega reusa la tubería existente: tarea Celery → `{"ruta": ...}` → `GET /v1/tareas/{id}` → enlace firmado HMAC.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async, `asyncmy`), Alembic, Celery + Redis, MySQL 8, `satcfdi==26.7.4`, `openpyxl` (modo `write_only`), pytest + testcontainers, React + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-08-05-informes-cfdi-nomina-design.md`
**Documento fuente:** `Hub_CFDI_docs/00-fuentes/especificacion-informes-cfdi.md` (§2 modelo de datos, §4 reglas transversales, B-00 y B-02)

## Global Constraints

- **Claves de catálogo como texto.** Todas (`001`, `04`, `P001`) se almacenan y comparan como `VARCHAR`. Nunca como entero: destruye los ceros a la izquierda (regla dura del §1.3).
- **`Decimal` de punta a punta. Jamás `float`.** Importes en `DECIMAL(18,6)`, tasas en `DECIMAL(9,6)`. `satcfdi` ya devuelve `Decimal`; no convertir. El redondeo a 2 decimales ocurre **una sola vez**, al escribir la celda de Excel (R-T4).
- **Las tablas nuevas cuelgan de `comprobante_id`**, nunca de `uuid`. `comprobantes` declara `UNIQUE(empresa_id, uuid)` porque el mismo CFDI puede existir en dos empresas.
- **No se toca `comprobantes`.** Ni una columna nueva.
- **Nada rompe el lote.** Un XML corrupto se registra y se sigue.
- **Los XML reales no entran a git.** Contienen CURP, NSS y cuentas bancarias de personas reales. Todos los fixtures son sintéticos.
- **`mysql_charset="utf8mb4"`, `mysql_collate="utf8mb4_unicode_ci"`** en toda tabla nueva, como el resto del esquema.
- **Verde obligatorio antes de cada commit:** `.venv/bin/pytest -q` y `.venv/bin/mypy --strict app`.
- Comentarios y docstrings en español, como el resto del código.

---

### Task 1: Modelos y migración — encabezado extendido, conceptos, impuestos y relacionados

**Files:**
- Create: `app/models/cfdi_detalle.py`
- Modify: `app/models/__init__.py`
- Create: `alembic/versions/<rev>_add_cfdi_detalle.py` (autogenerada)
- Test: `tests/test_modelos_cfdi_detalle.py`

**Interfaces:**
- Produces: `ComprobanteDetalle`, `CfdiConcepto`, `CfdiConceptoImpuesto`, `CfdiRelacionado` (clases SQLAlchemy). Constantes de módulo: ninguna.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_modelos_cfdi_detalle.py
"""Las tablas de detalle del comprobante cuelgan de `comprobante_id` (spec §4.1) y
aceptan importes con 6 decimales sin perder precisión (spec §5, regla de Decimal)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cfdi_detalle import CfdiConcepto, CfdiConceptoImpuesto, CfdiRelacionado, ComprobanteDetalle
from tests import factories


async def test_detalle_guarda_encabezado_con_seis_decimales(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111")

    db.add(
        ComprobanteDetalle(
            comprobante_id=comprobante.comprobante_id,
            version="4.0",
            serie="A",
            fecha_timbrado=datetime(2026, 7, 1, 10, 0, 0),
            moneda="MXN",
            tipo_cambio=Decimal("1.000000"),
            subtotal=Decimal("8759.700000"),
            descuento=Decimal("0.000000"),
            xml_hash="a" * 64,
            etl_version=1,
        )
    )
    await db.commit()

    guardado = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante.comprobante_id))
    assert guardado is not None
    assert guardado.subtotal == Decimal("8759.700000")
    assert guardado.error_normalizacion is None


async def test_concepto_impuesto_conserva_tasa_y_clave_como_texto(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="22222222-2222-2222-2222-222222222222")

    concepto = CfdiConcepto(
        comprobante_id=comprobante.comprobante_id,
        num_linea=1,
        clave_prod_serv="84111506",
        cantidad=Decimal("1.000000"),
        clave_unidad="E48",
        descripcion="Servicios de facturación",
        valor_unitario=Decimal("7000.000000"),
        importe=Decimal("7000.000000"),
        descuento=Decimal("0.000000"),
        objeto_imp="02",
    )
    db.add(concepto)
    await db.flush()

    db.add(
        CfdiConceptoImpuesto(
            concepto_id=concepto.id,
            comprobante_id=comprobante.comprobante_id,
            naturaleza="T",
            impuesto="002",
            tipo_factor="Tasa",
            tasa_o_cuota=Decimal("0.080000"),
            base=Decimal("7000.000000"),
            importe=Decimal("560.000000"),
        )
    )
    db.add(
        CfdiRelacionado(
            comprobante_id=comprobante.comprobante_id,
            tipo_relacion="01",
            uuid_relacionado="33333333-3333-3333-3333-333333333333",
        )
    )
    await db.commit()

    impuesto = await db.scalar(select(CfdiConceptoImpuesto).where(CfdiConceptoImpuesto.concepto_id == concepto.id))
    assert impuesto is not None
    # La clave se conserva como texto: '002' no puede volverse 2.
    assert impuesto.impuesto == "002"
    assert impuesto.tasa_o_cuota == Decimal("0.080000")

    relacionado = await db.scalar(select(CfdiRelacionado).where(CfdiRelacionado.comprobante_id == comprobante.comprobante_id))
    assert relacionado is not None
    assert relacionado.tipo_relacion == "01"


async def test_borrar_comprobante_arrastra_el_detalle(db: AsyncSession) -> None:
    """`ON DELETE CASCADE`: el detalle nunca queda huérfano."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="44444444-4444-4444-4444-444444444444")
    db.add(ComprobanteDetalle(comprobante_id=comprobante.comprobante_id, version="4.0", xml_hash="b" * 64, etl_version=1))
    await db.commit()

    await db.delete(comprobante)
    await db.commit()

    assert await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante.comprobante_id)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_modelos_cfdi_detalle.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.models.cfdi_detalle'`

- [ ] **Step 3: Write the models**

```python
# app/models/cfdi_detalle.py
"""Encabezado extendido y cuerpo del comprobante (spec §5.1).

`comprobantes` es la tabla caliente del listado de la UI y no se toca: el encabezado
extendido vive aquí, en una tabla 1:1, para que un fallo del ETL no pueda dañar el
índice del que depende la aplicación (spec §4.2).

Todas las claves de catálogo son texto y todos los importes `Numeric(18, 6)` — ver las
reglas duras del spec §5.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_TABLA_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


class ComprobanteDetalle(Base):
    """1:1 con `comprobantes`. `xml_hash` + `etl_version` son la base de la idempotencia
    del ETL (spec §6.2); `error_normalizacion` guarda el fallo para que el pre-vuelo no
    reintente el mismo XML corrupto en cada corrida."""

    __tablename__ = "comprobante_detalle"
    __table_args__ = (_TABLA_ARGS,)

    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[str | None] = mapped_column(String(5), nullable=True)
    serie: Mapped[str | None] = mapped_column(String(25), nullable=True)
    fecha_timbrado: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    forma_pago: Mapped[str | None] = mapped_column(String(2), nullable=True)
    metodo_pago: Mapped[str | None] = mapped_column(String(3), nullable=True)
    moneda: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    tipo_cambio: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    descuento: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    lugar_expedicion: Mapped[str | None] = mapped_column(String(5), nullable=True)
    exportacion: Mapped[str | None] = mapped_column(String(2), nullable=True)
    regimen_emisor: Mapped[str | None] = mapped_column(String(3), nullable=True)
    nombre_receptor: Mapped[str | None] = mapped_column(String(300), nullable=True)
    domicilio_receptor: Mapped[str | None] = mapped_column(String(5), nullable=True)
    regimen_receptor: Mapped[str | None] = mapped_column(String(3), nullable=True)
    uso_cfdi: Mapped[str | None] = mapped_column(String(4), nullable=True)
    no_certificado: Mapped[str | None] = mapped_column(String(20), nullable=True)
    no_certificado_sat: Mapped[str | None] = mapped_column(String(20), nullable=True)
    xml_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    etl_version: Mapped[int] = mapped_column(Integer, nullable=False)
    normalizado_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_normalizacion: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CfdiConcepto(Base):
    __tablename__ = "cfdi_concepto"
    __table_args__ = (
        UniqueConstraint("comprobante_id", "num_linea", name="uq_concepto_linea"),
        _TABLA_ARGS,
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    num_linea: Mapped[int] = mapped_column(Integer, nullable=False)
    clave_prod_serv: Mapped[str | None] = mapped_column(String(8), nullable=True)
    no_identificacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cantidad: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    clave_unidad: Mapped[str | None] = mapped_column(String(3), nullable=True)
    unidad: Mapped[str | None] = mapped_column(String(20), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    valor_unitario: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    descuento: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    objeto_imp: Mapped[str | None] = mapped_column(String(2), nullable=True)


class CfdiConceptoImpuesto(Base):
    """Impuestos a nivel concepto. `comprobante_id` está desnormalizado a propósito: los
    informes de impuestos por tasa agregan sin pasar por `cfdi_concepto` (§2.3 del fuente)."""

    __tablename__ = "cfdi_concepto_impuesto"
    __table_args__ = (
        Index("idx_cci_comp_impuesto", "comprobante_id", "naturaleza", "impuesto", "tasa_o_cuota"),
        _TABLA_ARGS,
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    concepto_id: Mapped[int] = mapped_column(ForeignKey("cfdi_concepto.id", ondelete="CASCADE"), nullable=False)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    naturaleza: Mapped[str] = mapped_column(CHAR(1), nullable=False)
    impuesto: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    tipo_factor: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tasa_o_cuota: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class CfdiRelacionado(Base):
    __tablename__ = "cfdi_relacionado"
    __table_args__ = (
        UniqueConstraint("comprobante_id", "tipo_relacion", "uuid_relacionado", name="uq_relacionado"),
        _TABLA_ARGS,
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    tipo_relacion: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    uuid_relacionado: Mapped[str] = mapped_column(CHAR(36), nullable=False)
```

- [ ] **Step 4: Register the models**

En `app/models/__init__.py`, agregar el import y las cuatro entradas de `__all__`:

```python
from app.models.cfdi_detalle import CfdiConcepto, CfdiConceptoImpuesto, CfdiRelacionado, ComprobanteDetalle
```

Agregar a `__all__`: `"ComprobanteDetalle"`, `"CfdiConcepto"`, `"CfdiConceptoImpuesto"`, `"CfdiRelacionado"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_modelos_cfdi_detalle.py -q`
Expected: PASS (3 tests). Las tablas se crean con `Base.metadata.create_all` del fixture `db`.

- [ ] **Step 6: Generate the migration**

Los servicios deben estar arriba (`docker compose up -d`). La migración se autogenera contra la BD real:

Run: `docker compose exec api alembic revision --autogenerate -m "add cfdi detalle conceptos impuestos relacionados"`

Revisar el archivo generado en `alembic/versions/`: debe crear exactamente cuatro tablas y **ninguna alteración a `comprobantes`**. Si Alembic propone tocar `comprobantes`, es un error — quitarlo a mano.

- [ ] **Step 7: Apply and verify the migration**

Run: `docker compose exec api alembic upgrade head`
Run: `docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "show tables;" hub_cfdi'`
Expected: aparecen `comprobante_detalle`, `cfdi_concepto`, `cfdi_concepto_impuesto`, `cfdi_relacionado`.

Verificar que el downgrade también funciona antes de confiar en la migración:
Run: `docker compose exec api alembic downgrade -1 && docker compose exec api alembic upgrade head`
Expected: ambos comandos terminan sin error.

- [ ] **Step 8: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/models/cfdi_detalle.py app/models/__init__.py alembic/versions/ tests/test_modelos_cfdi_detalle.py
git commit -m "feat(informes): agregar tablas de detalle del comprobante (encabezado, conceptos, impuestos, relacionados)"
```

---

### Task 2: Modelos y migración — complemento de Pagos 2.0

**Files:**
- Create: `app/models/pago.py`
- Modify: `app/models/__init__.py`
- Create: `alembic/versions/<rev>_add_pagos.py` (autogenerada)
- Test: `tests/test_modelos_pago.py`

**Interfaces:**
- Consumes: nada de tareas anteriores (las FK apuntan a `comprobantes`, que ya existe).
- Produces: `Pago`, `PagoDocto`, `PagoDoctoImpuesto`, `PagoTotales`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_modelos_pago.py
"""Complemento de Pagos 2.0 (spec §5.2). Un REP con 1 pago que cubre 1 documento
produce una fila en `pago`, una en `pago_docto` y una en `pago_totales`."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pago import Pago, PagoDocto, PagoDoctoImpuesto, PagoTotales
from tests import factories


async def test_pago_con_documento_relacionado_e_impuestos(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="55555555-5555-5555-5555-555555555555", tipo_comprobante="P"
    )

    pago = Pago(
        comprobante_id=comprobante.comprobante_id,
        num_pago=1,
        fecha_pago=datetime(2026, 7, 22, 12, 0, 0),
        forma_de_pago_p="03",
        moneda_p="MXN",
        tipo_cambio_p=Decimal("1.000000"),
        monto=Decimal("10800.000000"),
        num_operacion="123456",
    )
    db.add(pago)
    await db.flush()

    docto = PagoDocto(
        pago_id=pago.id,
        comprobante_id=comprobante.comprobante_id,
        id_documento="66666666-6666-6666-6666-666666666666",
        serie="A",
        folio="1001",
        moneda_dr="MXN",
        equivalencia_dr=Decimal("1.0000000000"),
        num_parcialidad=1,
        imp_saldo_ant=Decimal("10800.000000"),
        imp_pagado=Decimal("10800.000000"),
        imp_saldo_insoluto=Decimal("0.000000"),
        objeto_imp_dr="02",
    )
    db.add(docto)
    await db.flush()

    db.add(
        PagoDoctoImpuesto(
            pago_docto_id=docto.id,
            comprobante_id=comprobante.comprobante_id,
            naturaleza="T",
            impuesto="002",
            tipo_factor="Tasa",
            tasa_o_cuota=Decimal("0.080000"),
            base=Decimal("10000.000000"),
            importe=Decimal("800.000000"),
        )
    )
    db.add(
        PagoTotales(
            comprobante_id=comprobante.comprobante_id,
            total_traslados_base_iva8=Decimal("10000.000000"),
            total_traslados_impuesto_iva8=Decimal("800.000000"),
            monto_total_pagos=Decimal("10800.000000"),
        )
    )
    await db.commit()

    guardado = await db.scalar(select(PagoDocto).where(PagoDocto.pago_id == pago.id))
    assert guardado is not None
    assert guardado.imp_pagado == Decimal("10800.000000")
    # `equivalencia_dr` necesita 10 decimales, no 6 (§2.5 del documento fuente).
    assert guardado.equivalencia_dr == Decimal("1.0000000000")

    totales = await db.scalar(select(PagoTotales).where(PagoTotales.comprobante_id == comprobante.comprobante_id))
    assert totales is not None
    assert totales.monto_total_pagos == Decimal("10800.000000")
    assert totales.total_traslados_base_iva16 is None  # no informado en este REP
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_modelos_pago.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.models.pago'`

- [ ] **Step 3: Write the models**

```python
# app/models/pago.py
"""Complemento de Pagos 2.0 (spec §5.2, §2.5 del documento fuente).

`equivalencia_dr` es `Numeric(18, 10)`, no 6: es un factor de conversión entre monedas y
el estándar admite 10 decimales.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_TABLA_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


class Pago(Base):
    __tablename__ = "pago"
    __table_args__ = (Index("idx_pago_comp", "comprobante_id"), Index("idx_pago_fecha", "fecha_pago"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    num_pago: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_pago: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    forma_de_pago_p: Mapped[str | None] = mapped_column(String(2), nullable=True)
    moneda_p: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    tipo_cambio_p: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    monto: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    num_operacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rfc_emisor_cta_ord: Mapped[str | None] = mapped_column(String(13), nullable=True)
    cta_ordenante: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rfc_emisor_cta_ben: Mapped[str | None] = mapped_column(String(13), nullable=True)
    cta_beneficiario: Mapped[str | None] = mapped_column(String(50), nullable=True)


class PagoDocto(Base):
    __tablename__ = "pago_docto"
    __table_args__ = (Index("idx_docto_documento", "id_documento"), Index("idx_docto_comp", "comprobante_id"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pago_id: Mapped[int] = mapped_column(ForeignKey("pago.id", ondelete="CASCADE"), nullable=False)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    id_documento: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    serie: Mapped[str | None] = mapped_column(String(25), nullable=True)
    folio: Mapped[str | None] = mapped_column(String(40), nullable=True)
    moneda_dr: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    equivalencia_dr: Mapped[Decimal | None] = mapped_column(Numeric(18, 10), nullable=True)
    num_parcialidad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imp_saldo_ant: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    imp_pagado: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    imp_saldo_insoluto: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    objeto_imp_dr: Mapped[str | None] = mapped_column(String(2), nullable=True)


class PagoDoctoImpuesto(Base):
    __tablename__ = "pago_docto_impuesto"
    __table_args__ = (Index("idx_pdi_comp", "comprobante_id", "naturaleza", "impuesto"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pago_docto_id: Mapped[int] = mapped_column(ForeignKey("pago_docto.id", ondelete="CASCADE"), nullable=False)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    naturaleza: Mapped[str] = mapped_column(CHAR(1), nullable=False)
    impuesto: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    tipo_factor: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tasa_o_cuota: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class PagoTotales(Base):
    """1:1 con el comprobante — nodo `pago20:Totales` (§2.5 del fuente). Los campos no
    informados quedan en `NULL`, no en cero: "no vino" y "vino en cero" son distintos aquí."""

    __tablename__ = "pago_totales"
    __table_args__ = (_TABLA_ARGS,)

    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), primary_key=True)
    total_traslados_base_iva16: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_impuesto_iva16: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_base_iva8: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_impuesto_iva8: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_base_iva0: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_impuesto_iva0: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_base_iva_exento: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_retenciones_iva: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_retenciones_isr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_retenciones_ieps: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    monto_total_pagos: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
```

- [ ] **Step 4: Register the models**

En `app/models/__init__.py`:

```python
from app.models.pago import Pago, PagoDocto, PagoDoctoImpuesto, PagoTotales
```

Agregar a `__all__`: `"Pago"`, `"PagoDocto"`, `"PagoDoctoImpuesto"`, `"PagoTotales"`.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_modelos_pago.py -q`
Expected: PASS (1 test)

- [ ] **Step 6: Generate, apply and verify the migration**

Run: `docker compose exec api alembic revision --autogenerate -m "add complemento pagos"`
Run: `docker compose exec api alembic upgrade head`
Run: `docker compose exec api alembic downgrade -1 && docker compose exec api alembic upgrade head`
Expected: crea `pago`, `pago_docto`, `pago_docto_impuesto`, `pago_totales`; sin tocar tablas existentes; downgrade limpio.

- [ ] **Step 7: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/models/pago.py app/models/__init__.py alembic/versions/ tests/test_modelos_pago.py
git commit -m "feat(informes): agregar tablas del complemento de pagos 2.0"
```

---

### Task 3: Modelos y migración — complemento de Nómina 1.2

**Files:**
- Create: `app/models/nomina.py`
- Modify: `app/models/__init__.py`
- Create: `alembic/versions/<rev>_add_nomina.py` (autogenerada)
- Test: `tests/test_modelos_nomina.py`

**Interfaces:**
- Produces: `Nomina`, `NominaReceptor`, `NominaPercepcion`, `NominaDeduccion`, `NominaOtroPago`, `NominaIncapacidad`, `NominaTotales`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_modelos_nomina.py
"""Complemento de Nómina 1.2 (spec §5.3).

Dos cosas que estas pruebas fijan a propósito, porque son los errores que el documento
fuente advierte: `antiguedad` se guarda como texto (viene como duración ISO 8601, p. ej.
'P663W') y el mismo `(tipo, clave)` puede repetirse en un solo CFDI, así que la tabla
NO lleva restricción de unicidad sobre esa combinación (B-02.R1).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nomina import (
    Nomina,
    NominaDeduccion,
    NominaIncapacidad,
    NominaOtroPago,
    NominaPercepcion,
    NominaReceptor,
    NominaTotales,
)
from tests import factories


async def test_nomina_completa_con_receptor_y_conceptos(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="77777777-7777-7777-7777-777777777777", tipo_comprobante="N"
    )
    cid = comprobante.comprobante_id

    db.add(
        Nomina(
            comprobante_id=cid,
            version_nomina="1.2",
            tipo_nomina="O",
            fecha_pago=date(2026, 6, 30),
            fecha_inicial_pago=date(2026, 6, 16),
            fecha_final_pago=date(2026, 6, 30),
            num_dias_pagados=Decimal("15.000"),
            total_percepciones=Decimal("9259.700000"),
            total_deducciones=Decimal("1091.100000"),
            total_otros_pagos=Decimal("0.000000"),
            registro_patronal="B5510768108",
        )
    )
    db.add(
        NominaReceptor(
            comprobante_id=cid,
            curp="MAOM800101HCHNRN01",
            nss="12345678901",
            fecha_inicio_rel_laboral=date(2013, 9, 1),
            antiguedad="P663W",
            tipo_contrato="01",
            sindicalizado="No",
            tipo_jornada="01",
            tipo_regimen="02",
            num_empleado="039",
            departamento="Dirección",
            puesto="Director",
            riesgo_puesto="1",
            periodicidad_pago="04",
            salario_base_cot_apor=Decimal("583.980000"),
            salario_diario_integrado=Decimal("607.340000"),
            clave_ent_fed="CHH",
        )
    )
    db.add(NominaTotales(comprobante_id=cid, total_sueldos=Decimal("8759.700000"), total_gravado=Decimal("8759.700000"), total_exento=Decimal("500.000000")))
    await db.commit()

    nomina = await db.scalar(select(Nomina).where(Nomina.comprobante_id == cid))
    assert nomina is not None
    assert nomina.num_dias_pagados == Decimal("15.000")

    receptor = await db.scalar(select(NominaReceptor).where(NominaReceptor.comprobante_id == cid))
    assert receptor is not None
    # Texto, nunca número: 'P663W' no es una cantidad de semanas parseable como int.
    assert receptor.antiguedad == "P663W"
    # Clave interna del patrón: '039' no puede volverse 39.
    assert receptor.num_empleado == "039"


async def test_mismo_tipo_y_clave_se_repite_en_un_comprobante(db: AsyncSession) -> None:
    """B-02.R1: el esquema Nómina 1.2 permite dos nodos con el mismo (tipo, clave) en un
    mismo CFDI. Si la tabla los rechazara, el ETL perdería importes en silencio."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="88888888-8888-8888-8888-888888888888", tipo_comprobante="N"
    )
    cid = comprobante.comprobante_id

    for importe in (Decimal("300.000000"), Decimal("450.000000")):
        db.add(
            NominaPercepcion(
                comprobante_id=cid,
                tipo_percepcion="019",
                clave="019",
                concepto="Horas extra",
                importe_gravado=importe,
                importe_exento=Decimal("0.000000"),
            )
        )
    await db.commit()

    total = await db.scalar(
        select(func.sum(NominaPercepcion.importe_gravado)).where(NominaPercepcion.comprobante_id == cid, NominaPercepcion.tipo_percepcion == "019")
    )
    assert total == Decimal("750.000000")


async def test_deduccion_otro_pago_e_incapacidad(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="99999999-9999-9999-9999-999999999999", tipo_comprobante="N"
    )
    cid = comprobante.comprobante_id

    db.add(NominaDeduccion(comprobante_id=cid, tipo_deduccion="002", clave="045", concepto="I.S.R. mes", importe=Decimal("591.100000")))
    db.add(
        NominaOtroPago(
            comprobante_id=cid,
            tipo_otro_pago="002",
            clave="035",
            concepto="Subs al Empleo mes",
            importe=Decimal("0.000000"),
            subsidio_causado=Decimal("0.000000"),
        )
    )
    db.add(NominaIncapacidad(comprobante_id=cid, dias_incapacidad=3, tipo_incapacidad="02", importe_monetario=Decimal("1200.000000")))
    await db.commit()

    deduccion = await db.scalar(select(NominaDeduccion).where(NominaDeduccion.comprobante_id == cid))
    assert deduccion is not None
    assert deduccion.tipo_deduccion == "002"
    incapacidad = await db.scalar(select(NominaIncapacidad).where(NominaIncapacidad.comprobante_id == cid))
    assert incapacidad is not None
    assert incapacidad.dias_incapacidad == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_modelos_nomina.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.models.nomina'`

- [ ] **Step 3: Write the models**

```python
# app/models/nomina.py
"""Complemento de Nómina 1.2 (spec §5.3, §2.6–§2.11 del documento fuente).

Dos decisiones deliberadas:

- `nomina_totales` fusiona `nomina_percepciones_tot` y `nomina_deducciones_tot` del
  documento fuente: ambos son 1:1 con el comprobante y separarlos solo agrega un JOIN.
- Ni `nomina_percepcion` ni `nomina_deduccion` ni `nomina_otro_pago` llevan restricción
  de unicidad sobre `(comprobante_id, tipo, clave)`: el esquema del SAT permite nodos
  repetidos y el valor correcto es la SUMA, no el último (B-02.R1). Una restricción aquí
  haría fallar el ETL en CFDI perfectamente válidos.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_TABLA_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


class Nomina(Base):
    __tablename__ = "nomina"
    __table_args__ = (Index("idx_nomina_fecha_pago", "fecha_pago"), Index("idx_nomina_final_pago", "fecha_final_pago"), _TABLA_ARGS)

    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), primary_key=True)
    version_nomina: Mapped[str | None] = mapped_column(String(5), nullable=True)
    tipo_nomina: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    fecha_pago: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_inicial_pago: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_final_pago: Mapped[date | None] = mapped_column(Date, nullable=True)
    num_dias_pagados: Mapped[Decimal | None] = mapped_column(Numeric(9, 3), nullable=True)
    total_percepciones: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_deducciones: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_otros_pagos: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    registro_patronal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rfc_patron_origen: Mapped[str | None] = mapped_column(String(13), nullable=True)
    origen_recurso: Mapped[str | None] = mapped_column(String(2), nullable=True)
    monto_recurso_propio: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class NominaReceptor(Base):
    """Datos del trabajador. `curp`, `nss` y `cuenta_bancaria` son **datos personales**:
    todo informe que los emita respeta el enmascaramiento del spec §8."""

    __tablename__ = "nomina_receptor"
    __table_args__ = (Index("idx_nom_receptor_curp", "curp"), Index("idx_nom_receptor_nss", "nss"), _TABLA_ARGS)

    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), primary_key=True)
    curp: Mapped[str | None] = mapped_column(CHAR(18), nullable=True)
    nss: Mapped[str | None] = mapped_column(String(15), nullable=True)
    fecha_inicio_rel_laboral: Mapped[date | None] = mapped_column(Date, nullable=True)
    antiguedad: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tipo_contrato: Mapped[str | None] = mapped_column(String(2), nullable=True)
    sindicalizado: Mapped[str | None] = mapped_column(String(2), nullable=True)
    tipo_jornada: Mapped[str | None] = mapped_column(String(2), nullable=True)
    tipo_regimen: Mapped[str | None] = mapped_column(String(2), nullable=True)
    num_empleado: Mapped[str | None] = mapped_column(String(15), nullable=True)
    departamento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    puesto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    riesgo_puesto: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    periodicidad_pago: Mapped[str | None] = mapped_column(String(2), nullable=True)
    banco: Mapped[str | None] = mapped_column(String(3), nullable=True)
    cuenta_bancaria: Mapped[str | None] = mapped_column(String(18), nullable=True)
    salario_base_cot_apor: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    salario_diario_integrado: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    clave_ent_fed: Mapped[str | None] = mapped_column(String(3), nullable=True)


class NominaPercepcion(Base):
    __tablename__ = "nomina_percepcion"
    __table_args__ = (Index("idx_percepcion_concepto", "comprobante_id", "tipo_percepcion", "clave"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    tipo_percepcion: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    clave: Mapped[str | None] = mapped_column(String(15), nullable=True)
    concepto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    importe_gravado: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    importe_exento: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))


class NominaDeduccion(Base):
    __tablename__ = "nomina_deduccion"
    __table_args__ = (Index("idx_deduccion_concepto", "comprobante_id", "tipo_deduccion", "clave"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    tipo_deduccion: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    clave: Mapped[str | None] = mapped_column(String(15), nullable=True)
    concepto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    importe: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))


class NominaOtroPago(Base):
    __tablename__ = "nomina_otro_pago"
    __table_args__ = (Index("idx_otro_pago_concepto", "comprobante_id", "tipo_otro_pago", "clave"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    tipo_otro_pago: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    clave: Mapped[str | None] = mapped_column(String(15), nullable=True)
    concepto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    importe: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    subsidio_causado: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    saldo_a_favor: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    anio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remanente_sal_fav: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class NominaIncapacidad(Base):
    __tablename__ = "nomina_incapacidad"
    __table_args__ = (Index("idx_incapacidad_comp", "comprobante_id"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    dias_incapacidad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tipo_incapacidad: Mapped[str | None] = mapped_column(String(2), nullable=True)
    importe_monetario: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class NominaTotales(Base):
    """Fusión de `nomina_percepciones_tot` y `nomina_deducciones_tot` del documento fuente."""

    __tablename__ = "nomina_totales"
    __table_args__ = (_TABLA_ARGS,)

    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), primary_key=True)
    total_sueldos: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_separacion_indemnizacion: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_jubilacion_pension_retiro: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_gravado: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_exento: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_otras_deducciones: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_impuestos_retenidos: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
```

- [ ] **Step 4: Register the models**

En `app/models/__init__.py`:

```python
from app.models.nomina import (
    Nomina,
    NominaDeduccion,
    NominaIncapacidad,
    NominaOtroPago,
    NominaPercepcion,
    NominaReceptor,
    NominaTotales,
)
```

Agregar las siete a `__all__`.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_modelos_nomina.py -q`
Expected: PASS (3 tests)

- [ ] **Step 6: Generate, apply and verify the migration**

Run: `docker compose exec api alembic revision --autogenerate -m "add complemento nomina"`
Run: `docker compose exec api alembic upgrade head`
Run: `docker compose exec api alembic downgrade -1 && docker compose exec api alembic upgrade head`
Expected: crea las siete tablas de nómina; downgrade limpio.

- [ ] **Step 7: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/models/nomina.py app/models/__init__.py alembic/versions/ tests/test_modelos_nomina.py
git commit -m "feat(informes): agregar tablas del complemento de nomina 1.2"
```

---

### Task 4: ETL puro — encabezado, conceptos, impuestos y relacionados

**Files:**
- Create: `app/services/normalizacion.py`
- Create: `tests/fixtures_cfdi.py`
- Test: `tests/test_normalizacion_comprobante.py`

**Interfaces:**
- Produces:
  - `ETL_VERSION: int = 1`
  - `@dataclass DatosEncabezado` con los campos de `ComprobanteDetalle` (sin `comprobante_id`, `xml_hash`, `etl_version`, `normalizado_at`, `error_normalizacion`).
  - `@dataclass DatosConcepto` (campos de `CfdiConcepto` sin `id`/`comprobante_id`, más `impuestos: list[DatosImpuesto]`).
  - `@dataclass DatosImpuesto` (`naturaleza`, `impuesto`, `tipo_factor`, `tasa_o_cuota`, `base`, `importe`).
  - `@dataclass DatosRelacionado` (`tipo_relacion`, `uuid_relacionado`).
  - `@dataclass DatosComprobante` con `encabezado`, `conceptos`, `relacionados`, `nomina: DatosNomina | None = None`, `pagos: list[DatosPago] = []`, `pago_totales: DatosPagoTotales | None = None`.
  - `def normalizar(xml_bytes: bytes) -> DatosComprobante`
  - `def hash_xml(xml_bytes: bytes) -> str` (SHA-256 hexadecimal, minúsculas)
  - Helpers internos reutilizados por las tareas 5 y 6: `_clave(valor) -> str | None`, `_lista(nodo, clave) -> list`

- [ ] **Step 1: Write the synthetic fixture builder**

```python
# tests/fixtures_cfdi.py
"""Constructores de XML de CFDI sintéticos para las pruebas del ETL.

**Ningún XML real entra a git**: los de la empresa 11 contienen CURP, NSS y cuentas
bancarias de personas reales (spec §13). Todo lo de aquí es inventado.

Los XML no llevan sello ni certificado válidos: `satcfdi.CFDI.from_string` parsea sin
validar la firma, que es exactamente lo que el ETL necesita.
"""

from __future__ import annotations

_TIMBRE = (
    '<complemento><tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" '
    'Version="1.1" UUID="{uuid}" FechaTimbrado="{timbrado}" RfcProvCertif="AAA010101AAA" '
    'SelloCFD="c2VsbG8=" NoCertificadoSAT="00001000000504465028" SelloSAT="c2VsbG8=" /></complemento>'
)


def cfdi_ingreso(
    *,
    uuid: str = "11111111-1111-1111-1111-111111111111",
    fecha: str = "2026-07-01T10:00:00",
    timbrado: str = "2026-07-01T10:05:00",
    serie: str = "A",
    folio: str = "1582",
    moneda: str = "MXN",
    tipo_cambio: str = "1",
    subtotal: str = "7000.00",
    descuento: str | None = None,
    total: str = "7560.00",
    conceptos_xml: str | None = None,
    relacionados_xml: str = "",
) -> bytes:
    """CFDI 4.0 de ingreso con un concepto y un traslado de IVA al 8 %."""
    concepto_default = (
        '<cfdi:Concepto ClaveProdServ="84111506" Cantidad="1" ClaveUnidad="E48" '
        'Descripcion="Servicios de facturacion" ValorUnitario="7000.00" Importe="7000.00" ObjetoImp="02">'
        "<cfdi:Impuestos><cfdi:Traslados>"
        '<cfdi:Traslado Base="7000.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.080000" Importe="560.00" />'
        "</cfdi:Traslados></cfdi:Impuestos></cfdi:Concepto>"
    )
    atributo_descuento = f' Descuento="{descuento}"' if descuento is not None else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0" '
        f'Serie="{serie}" Folio="{folio}" Fecha="{fecha}" FormaPago="03" MetodoPago="PUE" '
        f'Moneda="{moneda}" TipoCambio="{tipo_cambio}" SubTotal="{subtotal}"{atributo_descuento} Total="{total}" '
        'TipoDeComprobante="I" Exportacion="01" LugarExpedicion="31000" '
        'NoCertificado="00001000000504465028" Certificado="Y2VydA==" Sello="c2VsbG8=">'
        f"{relacionados_xml}"
        '<cfdi:Emisor Rfc="CHL960913IX9" Nombre="CENTRO HUMANO DE LIDERAZGO" RegimenFiscal="601" />'
        '<cfdi:Receptor Rfc="XAXX010101000" Nombre="PUBLICO EN GENERAL" '
        'DomicilioFiscalReceptor="31000" RegimenFiscalReceptor="616" UsoCFDI="G03" />'
        f"<cfdi:Conceptos>{conceptos_xml or concepto_default}</cfdi:Conceptos>"
        + _TIMBRE.format(uuid=uuid, timbrado=timbrado).replace("complemento", "cfdi:Complemento")
        + "</cfdi:Comprobante>"
    ).encode()


def relacionados(tipo_relacion: str, *uuids: str) -> str:
    """Bloque `CfdiRelacionados`. En 4.0 puede haber varios con distinto `TipoRelacion`."""
    hijos = "".join(f'<cfdi:CfdiRelacionado UUID="{u}" />' for u in uuids)
    return f'<cfdi:CfdiRelacionados TipoRelacion="{tipo_relacion}">{hijos}</cfdi:CfdiRelacionados>'
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_normalizacion_comprobante.py
"""ETL puro del encabezado y el cuerpo del comprobante (spec §6.1).

`normalizar` no toca la BD: recibe bytes y devuelve dataclasses. Eso es lo que la hace
probable a fondo sin contenedores.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.services import normalizacion
from tests import fixtures_cfdi


def test_normaliza_encabezado_de_ingreso() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_ingreso())

    enc = datos.encabezado
    assert enc.version == "4.0"
    assert enc.serie == "A"
    assert enc.fecha_timbrado == datetime(2026, 7, 1, 10, 5, 0)
    assert enc.moneda == "MXN"
    assert enc.tipo_cambio == Decimal("1")
    assert enc.subtotal == Decimal("7000.00")
    # `Descuento` ausente en el XML se normaliza a cero (§2.1 del fuente).
    assert enc.descuento == Decimal("0")
    assert enc.metodo_pago == "PUE"
    assert enc.forma_pago == "03"
    assert enc.regimen_emisor == "601"
    assert enc.regimen_receptor == "616"
    assert enc.uso_cfdi == "G03"
    assert enc.lugar_expedicion == "31000"
    assert enc.no_certificado_sat == "00001000000504465028"


def test_normaliza_concepto_con_impuesto_por_linea() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_ingreso())

    assert len(datos.conceptos) == 1
    concepto = datos.conceptos[0]
    assert concepto.num_linea == 1
    assert concepto.clave_prod_serv == "84111506"
    assert concepto.importe == Decimal("7000.00")
    assert concepto.descuento == Decimal("0")
    assert concepto.objeto_imp == "02"

    assert len(concepto.impuestos) == 1
    impuesto = concepto.impuestos[0]
    assert impuesto.naturaleza == "T"
    # Clave de catálogo como texto: '002', no 2.
    assert impuesto.impuesto == "002"
    assert impuesto.tipo_factor == "Tasa"
    assert impuesto.tasa_o_cuota == Decimal("0.080000")
    assert impuesto.base == Decimal("7000.00")
    assert impuesto.importe == Decimal("560.00")


def test_normaliza_varios_relacionados_con_distinto_tipo() -> None:
    """En CFDI 4.0 puede haber varios nodos `CfdiRelacionados` con distinto `TipoRelacion`
    en el mismo comprobante (§2.4 del fuente)."""
    xml = fixtures_cfdi.cfdi_ingreso(
        relacionados_xml=(
            fixtures_cfdi.relacionados("01", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
            + fixtures_cfdi.relacionados("04", "cccccccc-cccc-cccc-cccc-cccccccccccc")
        )
    )
    datos = normalizacion.normalizar(xml)

    pares = sorted((r.tipo_relacion, r.uuid_relacionado) for r in datos.relacionados)
    assert pares == [
        ("01", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"),
        ("01", "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"),
        ("04", "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"),
    ]


def test_sin_complemento_de_nomina_ni_pagos() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_ingreso())
    assert datos.nomina is None
    assert datos.pagos == []
    assert datos.pago_totales is None


def test_hash_es_estable_y_sensible_al_contenido() -> None:
    a = fixtures_cfdi.cfdi_ingreso()
    b = fixtures_cfdi.cfdi_ingreso(total="7561.00")
    assert normalizacion.hash_xml(a) == normalizacion.hash_xml(a)
    assert normalizacion.hash_xml(a) != normalizacion.hash_xml(b)
    assert len(normalizacion.hash_xml(a)) == 64
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_normalizacion_comprobante.py -q`
Expected: FAIL con `AttributeError: module 'app.services.normalizacion' has no attribute 'normalizar'` (o `ModuleNotFoundError`)

- [ ] **Step 4: Write the pure ETL**

```python
# app/services/normalizacion.py
"""ETL: XML de CFDI → dataclasses (spec §6.1).

Servicio **puro**: sin BD, sin sesión, sin I/O de disco. Recibe los bytes del XML y
devuelve el árbol de datos que el escritor (`app/repositories/normalizacion.py`)
persiste. Es el único módulo que conoce `satcfdi`.

Tres detalles que `satcfdi` resuelve y de los que este módulo depende:

- Los importes ya vienen como `Decimal`. **No se convierten a float** (regla R-T4).
- Las claves de catálogo vienen como objetos `Code` con `.code` y `.description`; se
  guarda la clave textual (`_clave`).
- Los nodos con cardinalidad variable llegan a veces como lista y a veces como mapa con
  un hijo nombrado (`Percepciones.Percepcion` es mapa+lista, `OtrosPagos` es lista
  directa). `_lista` normaliza ambas formas.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

ETL_VERSION = 1
"""Subir este número fuerza el reproceso de todo el histórico (spec §6.2)."""

_CERO = Decimal("0")


# --------------------------------------------------------------------------- #
# Dataclasses de salida
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class DatosImpuesto:
    naturaleza: str  # 'T' traslado | 'R' retención
    impuesto: str
    tipo_factor: str | None
    tasa_o_cuota: Decimal | None
    base: Decimal | None
    importe: Decimal | None


@dataclass(slots=True)
class DatosConcepto:
    num_linea: int
    clave_prod_serv: str | None
    no_identificacion: str | None
    cantidad: Decimal | None
    clave_unidad: str | None
    unidad: str | None
    descripcion: str | None
    valor_unitario: Decimal | None
    importe: Decimal | None
    descuento: Decimal
    objeto_imp: str | None
    impuestos: list[DatosImpuesto] = field(default_factory=list)


@dataclass(slots=True)
class DatosRelacionado:
    tipo_relacion: str
    uuid_relacionado: str


@dataclass(slots=True)
class DatosEncabezado:
    version: str | None
    serie: str | None
    fecha_timbrado: datetime | None
    forma_pago: str | None
    metodo_pago: str | None
    moneda: str | None
    tipo_cambio: Decimal | None
    subtotal: Decimal | None
    descuento: Decimal
    lugar_expedicion: str | None
    exportacion: str | None
    regimen_emisor: str | None
    nombre_receptor: str | None
    domicilio_receptor: str | None
    regimen_receptor: str | None
    uso_cfdi: str | None
    no_certificado: str | None
    no_certificado_sat: str | None


@dataclass(slots=True)
class DatosComprobante:
    encabezado: DatosEncabezado
    conceptos: list[DatosConcepto] = field(default_factory=list)
    relacionados: list[DatosRelacionado] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def hash_xml(xml_bytes: bytes) -> str:
    """SHA-256 hexadecimal del XML original — base de la idempotencia (spec §6.2)."""
    return hashlib.sha256(xml_bytes).hexdigest()


def _clave(valor: Any) -> str | None:
    """Clave textual de un catálogo. `satcfdi` devuelve `Code('002', 'IVA')`; interesa
    `'002'`. Nunca se convierte a entero: destruiría los ceros a la izquierda."""
    if valor is None:
        return None
    codigo = getattr(valor, "code", None)
    return str(codigo) if codigo is not None else str(valor)


def _lista(nodo: Any, clave_hijo: str) -> list[Any]:
    """Normaliza las dos formas en que `satcfdi` entrega colecciones: lista directa
    (`OtrosPagos`) o mapa con un hijo nombrado (`Percepciones` → `Percepcion`)."""
    if nodo is None:
        return []
    if isinstance(nodo, list):
        return nodo
    hijo = nodo.get(clave_hijo)
    if hijo is None:
        return []
    return hijo if isinstance(hijo, list) else [hijo]


def _decimal(valor: Any) -> Decimal | None:
    if valor is None:
        return None
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def _decimal_o_cero(valor: Any) -> Decimal:
    """Campos que el estándar declara opcionales pero que valen cero cuando faltan
    (`Descuento` a nivel comprobante y a nivel concepto, §2.1 y §2.2 del fuente)."""
    convertido = _decimal(valor)
    return _CERO if convertido is None else convertido


def _fecha_hora(valor: Any) -> datetime | None:
    return valor if isinstance(valor, datetime) else None


def _fecha(valor: Any) -> date | None:
    """`FechaPago` de nómina llega como `date`; un `datetime` se recorta a su fecha."""
    if isinstance(valor, datetime):
        return valor.date()
    return valor if isinstance(valor, date) else None


# --------------------------------------------------------------------------- #
# Parseo
# --------------------------------------------------------------------------- #


def _impuestos_de_concepto(concepto: Any) -> list[DatosImpuesto]:
    impuestos_nodo = concepto.get("Impuestos") or {}
    resultado: list[DatosImpuesto] = []
    for naturaleza, llave in (("T", "Traslados"), ("R", "Retenciones")):
        agrupados = impuestos_nodo.get(llave) or {}
        # `Traslados`/`Retenciones` es un mapa con llave compuesta '002|Tasa|0.160000'.
        valores = agrupados.values() if hasattr(agrupados, "values") else agrupados
        for nodo in valores:
            resultado.append(
                DatosImpuesto(
                    naturaleza=naturaleza,
                    impuesto=_clave(nodo.get("Impuesto")) or "",
                    tipo_factor=_clave(nodo.get("TipoFactor")),
                    tasa_o_cuota=_decimal(nodo.get("TasaOCuota")),
                    base=_decimal(nodo.get("Base")),
                    importe=_decimal(nodo.get("Importe")),
                )
            )
    return resultado


def _encabezado(c: Any) -> DatosEncabezado:
    tfd = (c.get("Complemento") or {}).get("TimbreFiscalDigital") or {}
    emisor = c.get("Emisor") or {}
    receptor = c.get("Receptor") or {}
    return DatosEncabezado(
        version=_clave(c.get("Version")),
        serie=c.get("Serie"),
        fecha_timbrado=_fecha_hora(tfd.get("FechaTimbrado")),
        forma_pago=_clave(c.get("FormaPago")),
        metodo_pago=_clave(c.get("MetodoPago")),
        moneda=_clave(c.get("Moneda")),
        tipo_cambio=_decimal(c.get("TipoCambio")),
        subtotal=_decimal(c.get("SubTotal")),
        descuento=_decimal_o_cero(c.get("Descuento")),
        lugar_expedicion=_clave(c.get("LugarExpedicion")),
        exportacion=_clave(c.get("Exportacion")),
        regimen_emisor=_clave(emisor.get("RegimenFiscal")),
        nombre_receptor=receptor.get("Nombre"),
        domicilio_receptor=_clave(receptor.get("DomicilioFiscalReceptor")),
        regimen_receptor=_clave(receptor.get("RegimenFiscalReceptor")),
        uso_cfdi=_clave(receptor.get("UsoCFDI")),
        no_certificado=c.get("NoCertificado"),
        no_certificado_sat=tfd.get("NoCertificadoSAT"),
    )


def _conceptos(c: Any) -> list[DatosConcepto]:
    resultado: list[DatosConcepto] = []
    for indice, concepto in enumerate(c.get("Conceptos") or [], start=1):
        resultado.append(
            DatosConcepto(
                num_linea=indice,
                clave_prod_serv=_clave(concepto.get("ClaveProdServ")),
                no_identificacion=concepto.get("NoIdentificacion"),
                cantidad=_decimal(concepto.get("Cantidad")),
                clave_unidad=_clave(concepto.get("ClaveUnidad")),
                unidad=concepto.get("Unidad"),
                descripcion=concepto.get("Descripcion"),
                valor_unitario=_decimal(concepto.get("ValorUnitario")),
                importe=_decimal(concepto.get("Importe")),
                descuento=_decimal_o_cero(concepto.get("Descuento")),
                objeto_imp=_clave(concepto.get("ObjetoImp")),
                impuestos=_impuestos_de_concepto(concepto),
            )
        )
    return resultado


def _relacionados(c: Any) -> list[DatosRelacionado]:
    """`CfdiRelacionados` puede venir como un nodo o como lista de nodos, cada uno con su
    propio `TipoRelacion` (§2.4 del fuente)."""
    nodo = c.get("CfdiRelacionados")
    if nodo is None:
        return []
    grupos = nodo if isinstance(nodo, list) else [nodo]
    resultado: list[DatosRelacionado] = []
    for grupo in grupos:
        tipo = _clave(grupo.get("TipoRelacion")) or ""
        for relacionado in _lista(grupo.get("CfdiRelacionado"), "CfdiRelacionado"):
            uuid_rel = relacionado.get("UUID") if hasattr(relacionado, "get") else relacionado
            if uuid_rel:
                resultado.append(DatosRelacionado(tipo_relacion=tipo, uuid_relacionado=str(uuid_rel).upper()))
    return resultado


def normalizar(xml_bytes: bytes) -> DatosComprobante:
    """Parsea el XML completo. Lanza si el XML no es un CFDI legible; el caller decide
    qué hacer con el fallo (spec §6.2: se persiste en `error_normalizacion`)."""
    from satcfdi.cfdi import CFDI

    c = CFDI.from_string(xml_bytes)
    return DatosComprobante(encabezado=_encabezado(c), conceptos=_conceptos(c), relacionados=_relacionados(c))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_normalizacion_comprobante.py -q`
Expected: PASS (5 tests)

Si `test_normaliza_varios_relacionados_con_distinto_tipo` falla porque `satcfdi` entrega
`CfdiRelacionado` con otra forma, imprimir la estructura para ajustar `_relacionados`:

```bash
.venv/bin/python -c "
from satcfdi.cfdi import CFDI
import sys; sys.path.insert(0, 'tests')
import fixtures_cfdi
c = CFDI.from_string(fixtures_cfdi.cfdi_ingreso(relacionados_xml=fixtures_cfdi.relacionados('01','AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA')))
print(type(c['CfdiRelacionados']), c['CfdiRelacionados'])
"
```

- [ ] **Step 6: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/services/normalizacion.py tests/fixtures_cfdi.py tests/test_normalizacion_comprobante.py
git commit -m "feat(informes): agregar ETL puro del encabezado, conceptos, impuestos y relacionados"
```

---

### Task 5: ETL puro — complemento de Nómina 1.2

**Files:**
- Modify: `app/services/normalizacion.py`
- Modify: `tests/fixtures_cfdi.py`
- Test: `tests/test_normalizacion_nomina.py`

**Interfaces:**
- Consumes de la tarea 4: `_clave`, `_lista`, `_decimal`, `_decimal_o_cero`, `_fecha`, `DatosComprobante`, `normalizar`.
- Produces:
  - `@dataclass DatosNominaReceptor`, `DatosPercepcion`, `DatosDeduccion`, `DatosOtroPago`, `DatosIncapacidad`, `DatosNominaTotales`
  - `@dataclass DatosNomina` con `cabecera` (campos de `Nomina`), `receptor`, `percepciones`, `deducciones`, `otros_pagos`, `incapacidades`, `totales`
  - `DatosComprobante.nomina: DatosNomina | None`

- [ ] **Step 1: Add the payroll fixture**

Agregar a `tests/fixtures_cfdi.py`:

```python
def cfdi_nomina(
    *,
    uuid: str = "77777777-7777-7777-7777-777777777777",
    fecha: str = "2026-07-01T09:30:00",
    fecha_pago: str = "2026-06-30",
    fecha_inicial: str = "2026-06-16",
    fecha_final: str = "2026-06-30",
    dias_pagados: str = "15.000",
    tipo_nomina: str = "O",
    total_percepciones: str = "9259.70",
    total_deducciones: str = "1091.10",
    total_otros_pagos: str = "0.00",
    subtotal: str = "9259.70",
    descuento: str = "1091.10",
    total: str = "8168.60",
    percepciones_xml: str | None = None,
    deducciones_xml: str | None = None,
    otros_pagos_xml: str | None = None,
    incapacidades_xml: str = "",
    total_gravado: str = "8759.70",
    total_exento: str = "500.00",
) -> bytes:
    """CFDI 4.0 tipo N con complemento de Nómina 1.2. Todos los datos personales son
    inventados: la CURP y el NSS no corresponden a ninguna persona real."""
    percepciones_default = (
        '<nomina12:Percepcion TipoPercepcion="001" Clave="001" Concepto="Sueldo" '
        'ImporteGravado="8759.70" ImporteExento="0.00" />'
        '<nomina12:Percepcion TipoPercepcion="005" Clave="031" Concepto="Fondo ahorro empresa" '
        'ImporteGravado="0.00" ImporteExento="500.00" />'
    )
    deducciones_default = (
        '<nomina12:Deduccion TipoDeduccion="001" Clave="052" Concepto="I.M.S.S." Importe="200.00" />'
        '<nomina12:Deduccion TipoDeduccion="002" Clave="045" Concepto="I.S.R. mes" Importe="391.10" />'
        '<nomina12:Deduccion TipoDeduccion="004" Clave="067" Concepto="Fondo de ahorro Empresa" Importe="500.00" />'
    )
    otros_default = (
        '<nomina12:OtroPago TipoOtroPago="002" Clave="035" Concepto="Subs al Empleo mes" Importe="0.00">'
        '<nomina12:SubsidioAlEmpleo SubsidioCausado="0.00" /></nomina12:OtroPago>'
    )
    percepciones_nodo = (
        f'<nomina12:Percepciones TotalSueldos="{total_gravado}" TotalGravado="{total_gravado}" '
        f'TotalExento="{total_exento}">{percepciones_xml or percepciones_default}</nomina12:Percepciones>'
    )
    deducciones_nodo = (
        '<nomina12:Deducciones TotalOtrasDeducciones="700.00" TotalImpuestosRetenidos="391.10">'
        f"{deducciones_xml or deducciones_default}</nomina12:Deducciones>"
    )
    otros_nodo = f"<nomina12:OtrosPagos>{otros_pagos_xml or otros_default}</nomina12:OtrosPagos>"
    complemento_nomina = (
        '<nomina12:Nomina xmlns:nomina12="http://www.sat.gob.mx/nomina12" Version="1.2" '
        f'TipoNomina="{tipo_nomina}" FechaPago="{fecha_pago}" FechaInicialPago="{fecha_inicial}" '
        f'FechaFinalPago="{fecha_final}" NumDiasPagados="{dias_pagados}" '
        f'TotalPercepciones="{total_percepciones}" TotalDeducciones="{total_deducciones}" '
        f'TotalOtrosPagos="{total_otros_pagos}">'
        '<nomina12:Emisor RegistroPatronal="B5510768108" />'
        '<nomina12:Receptor Curp="XXXX800101HCHXXX01" NumSeguridadSocial="12345678901" '
        'FechaInicioRelLaboral="2013-09-01" Antig&#252;edad="P663W" TipoContrato="01" '
        'Sindicalizado="No" TipoJornada="01" TipoRegimen="02" NumEmpleado="039" '
        'Departamento="Direccion" Puesto="Director" RiesgoPuesto="1" PeriodicidadPago="04" '
        'Banco="002" CuentaBancaria="1234567890" SalarioBaseCotApor="583.98" '
        'SalarioDiarioIntegrado="607.34" ClaveEntFed="CHH" />'
        f"{percepciones_nodo}{deducciones_nodo}{otros_nodo}{incapacidades_xml}"
        "</nomina12:Nomina>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0" '
        f'Serie="N" Folio="12" Fecha="{fecha}" MetodoPago="PUE" Moneda="MXN" '
        f'SubTotal="{subtotal}" Descuento="{descuento}" Total="{total}" '
        'TipoDeComprobante="N" Exportacion="01" LugarExpedicion="31000" '
        'NoCertificado="00001000000504465028" Certificado="Y2VydA==" Sello="c2VsbG8=">'
        '<cfdi:Emisor Rfc="CHL960913IX9" Nombre="CENTRO HUMANO DE LIDERAZGO" RegimenFiscal="601" />'
        '<cfdi:Receptor Rfc="XAXX010101000" Nombre="EMPLEADO DE PRUEBA" '
        'DomicilioFiscalReceptor="31000" RegimenFiscalReceptor="605" UsoCFDI="CN01" />'
        "<cfdi:Conceptos>"
        '<cfdi:Concepto ClaveProdServ="84111505" Cantidad="1" ClaveUnidad="ACT" '
        f'Descripcion="Pago de nomina" ValorUnitario="{subtotal}" Importe="{subtotal}" '
        f'Descuento="{descuento}" ObjetoImp="01" />'
        "</cfdi:Conceptos>"
        '<cfdi:Complemento>'
        f"{complemento_nomina}"
        '<tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" '
        f'Version="1.1" UUID="{uuid}" FechaTimbrado="{fecha}" RfcProvCertif="AAA010101AAA" '
        'SelloCFD="c2VsbG8=" NoCertificadoSAT="00001000000504465028" SelloSAT="c2VsbG8=" />'
        "</cfdi:Complemento>"
        "</cfdi:Comprobante>"
    ).encode()
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_normalizacion_nomina.py
"""ETL del complemento de Nómina 1.2.

Estas pruebas fijan los tres errores que el documento fuente advierte como los más
frecuentes: `@Antigüedad` lleva diéresis en el nombre del atributo, el mismo
`(tipo, clave)` puede repetirse y debe sumarse (B-02.R1), y el caso espejo del fondo de
ahorro NO se consolida (R-T10).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services import normalizacion
from tests import fixtures_cfdi


def test_normaliza_cabecera_de_nomina() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina())

    assert datos.nomina is not None
    cab = datos.nomina.cabecera
    assert cab.version_nomina == "1.2"
    assert cab.tipo_nomina == "O"
    assert cab.fecha_pago == date(2026, 6, 30)
    assert cab.fecha_inicial_pago == date(2026, 6, 16)
    assert cab.fecha_final_pago == date(2026, 6, 30)
    assert cab.num_dias_pagados == Decimal("15.000")
    assert cab.total_percepciones == Decimal("9259.70")
    assert cab.registro_patronal == "B5510768108"


def test_normaliza_receptor_con_antiguedad_con_dieresis() -> None:
    """`@Antigüedad` lleva diéresis en el nombre del atributo — fuente frecuente de
    fallos de parseo (§2.7 del fuente). Se guarda como texto, nunca como número."""
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina())

    assert datos.nomina is not None
    r = datos.nomina.receptor
    assert r.antiguedad == "P663W"
    assert r.curp == "XXXX800101HCHXXX01"
    assert r.nss == "12345678901"
    assert r.fecha_inicio_rel_laboral == date(2013, 9, 1)
    assert r.periodicidad_pago == "04"
    assert r.tipo_contrato == "01"
    assert r.num_empleado == "039"
    assert r.riesgo_puesto == "1"
    assert r.salario_base_cot_apor == Decimal("583.98")
    assert r.salario_diario_integrado == Decimal("607.34")
    assert r.clave_ent_fed == "CHH"


def test_normaliza_percepciones_deducciones_y_otros_pagos() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina())
    assert datos.nomina is not None
    nom = datos.nomina

    assert [(p.tipo_percepcion, p.clave, p.importe_gravado, p.importe_exento) for p in nom.percepciones] == [
        ("001", "001", Decimal("8759.70"), Decimal("0.00")),
        ("005", "031", Decimal("0.00"), Decimal("500.00")),
    ]
    assert [(d.tipo_deduccion, d.clave, d.importe) for d in nom.deducciones] == [
        ("001", "052", Decimal("200.00")),
        ("002", "045", Decimal("391.10")),
        ("004", "067", Decimal("500.00")),
    ]
    assert len(nom.otros_pagos) == 1
    otro = nom.otros_pagos[0]
    assert (otro.tipo_otro_pago, otro.clave, otro.importe) == ("002", "035", Decimal("0.00"))
    assert otro.subsidio_causado == Decimal("0.00")

    assert nom.totales.total_gravado == Decimal("8759.70")
    assert nom.totales.total_exento == Decimal("500.00")
    assert nom.totales.total_impuestos_retenidos == Decimal("391.10")
    assert nom.totales.total_otras_deducciones == Decimal("700.00")


def test_concepto_repetido_se_conserva_como_dos_filas() -> None:
    """B-02.R1: el ETL NO consolida. Devuelve los dos nodos tal cual y es el informe el
    que los suma. Colapsarlos aquí perdería la trazabilidad contra el XML."""
    percepciones = (
        '<nomina12:Percepcion TipoPercepcion="019" Clave="019" Concepto="Horas extra" '
        'ImporteGravado="300.00" ImporteExento="0.00" />'
        '<nomina12:Percepcion TipoPercepcion="019" Clave="019" Concepto="Horas extra" '
        'ImporteGravado="450.00" ImporteExento="0.00" />'
    )
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina(percepciones_xml=percepciones))

    assert datos.nomina is not None
    repetidas = [p for p in datos.nomina.percepciones if p.tipo_percepcion == "019"]
    assert len(repetidas) == 2
    assert sum(p.importe_gravado for p in repetidas) == Decimal("750.00")


def test_espejo_del_fondo_de_ahorro_se_conserva_en_las_tres_naturalezas() -> None:
    """R-T10: el mismo flujo aparece como percepción exenta, deducción y otro pago. El
    ETL refleja el XML; consolidar aquí falsearía el informe."""
    datos = normalizacion.normalizar(
        fixtures_cfdi.cfdi_nomina(
            otros_pagos_xml='<nomina12:OtroPago TipoOtroPago="999" Clave="099" Concepto="Fondo ahorro" Importe="500.00" />'
        )
    )
    assert datos.nomina is not None
    nom = datos.nomina
    assert any(p.tipo_percepcion == "005" and p.importe_exento == Decimal("500.00") for p in nom.percepciones)
    assert any(d.tipo_deduccion == "004" and d.importe == Decimal("500.00") for d in nom.deducciones)
    assert any(o.importe == Decimal("500.00") for o in nom.otros_pagos)


def test_incapacidad_cuando_el_nodo_existe() -> None:
    incapacidades = (
        "<nomina12:Incapacidades>"
        '<nomina12:Incapacidad DiasIncapacidad="3" TipoIncapacidad="02" ImporteMonetario="1200.00" />'
        "</nomina12:Incapacidades>"
    )
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina(incapacidades_xml=incapacidades))

    assert datos.nomina is not None
    assert len(datos.nomina.incapacidades) == 1
    inc = datos.nomina.incapacidades[0]
    assert (inc.dias_incapacidad, inc.tipo_incapacidad, inc.importe_monetario) == (3, "02", Decimal("1200.00"))


def test_sin_nodos_opcionales_no_truena() -> None:
    """Los 8 CFDI reales de la empresa 11 no traen `Incapacidades`. Ausente ≠ error."""
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina())
    assert datos.nomina is not None
    assert datos.nomina.incapacidades == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_normalizacion_nomina.py -q`
Expected: FAIL — `datos.nomina` es `None` porque `normalizar` todavía no parsea el complemento (`AssertionError` en el primer test).

- [ ] **Step 4: Extend the ETL with the payroll complement**

Agregar a `app/services/normalizacion.py`, antes de `normalizar`:

```python
@dataclass(slots=True)
class DatosNominaCabecera:
    version_nomina: str | None
    tipo_nomina: str | None
    fecha_pago: date | None
    fecha_inicial_pago: date | None
    fecha_final_pago: date | None
    num_dias_pagados: Decimal | None
    total_percepciones: Decimal | None
    total_deducciones: Decimal | None
    total_otros_pagos: Decimal | None
    registro_patronal: str | None
    rfc_patron_origen: str | None
    origen_recurso: str | None
    monto_recurso_propio: Decimal | None


@dataclass(slots=True)
class DatosNominaReceptor:
    curp: str | None
    nss: str | None
    fecha_inicio_rel_laboral: date | None
    antiguedad: str | None
    tipo_contrato: str | None
    sindicalizado: str | None
    tipo_jornada: str | None
    tipo_regimen: str | None
    num_empleado: str | None
    departamento: str | None
    puesto: str | None
    riesgo_puesto: str | None
    periodicidad_pago: str | None
    banco: str | None
    cuenta_bancaria: str | None
    salario_base_cot_apor: Decimal | None
    salario_diario_integrado: Decimal | None
    clave_ent_fed: str | None


@dataclass(slots=True)
class DatosPercepcion:
    tipo_percepcion: str
    clave: str | None
    concepto: str | None
    importe_gravado: Decimal
    importe_exento: Decimal


@dataclass(slots=True)
class DatosDeduccion:
    tipo_deduccion: str
    clave: str | None
    concepto: str | None
    importe: Decimal


@dataclass(slots=True)
class DatosOtroPago:
    tipo_otro_pago: str
    clave: str | None
    concepto: str | None
    importe: Decimal
    subsidio_causado: Decimal | None
    saldo_a_favor: Decimal | None
    anio: int | None
    remanente_sal_fav: Decimal | None


@dataclass(slots=True)
class DatosIncapacidad:
    dias_incapacidad: int | None
    tipo_incapacidad: str | None
    importe_monetario: Decimal | None


@dataclass(slots=True)
class DatosNominaTotales:
    total_sueldos: Decimal | None
    total_separacion_indemnizacion: Decimal | None
    total_jubilacion_pension_retiro: Decimal | None
    total_gravado: Decimal | None
    total_exento: Decimal | None
    total_otras_deducciones: Decimal | None
    total_impuestos_retenidos: Decimal | None


@dataclass(slots=True)
class DatosNomina:
    cabecera: DatosNominaCabecera
    receptor: DatosNominaReceptor
    totales: DatosNominaTotales
    percepciones: list[DatosPercepcion] = field(default_factory=list)
    deducciones: list[DatosDeduccion] = field(default_factory=list)
    otros_pagos: list[DatosOtroPago] = field(default_factory=list)
    incapacidades: list[DatosIncapacidad] = field(default_factory=list)


def _nomina(nodo: Any) -> DatosNomina:
    emisor = nodo.get("Emisor") or {}
    entidad = nodo.get("EntidadSNCF") or {}
    receptor_nodo = nodo.get("Receptor") or {}
    percepciones_nodo = nodo.get("Percepciones") or {}
    deducciones_nodo = nodo.get("Deducciones") or {}

    cabecera = DatosNominaCabecera(
        version_nomina=_clave(nodo.get("Version")),
        tipo_nomina=_clave(nodo.get("TipoNomina")),
        fecha_pago=_fecha(nodo.get("FechaPago")),
        fecha_inicial_pago=_fecha(nodo.get("FechaInicialPago")),
        fecha_final_pago=_fecha(nodo.get("FechaFinalPago")),
        num_dias_pagados=_decimal(nodo.get("NumDiasPagados")),
        total_percepciones=_decimal(nodo.get("TotalPercepciones")),
        total_deducciones=_decimal(nodo.get("TotalDeducciones")),
        total_otros_pagos=_decimal(nodo.get("TotalOtrosPagos")),
        registro_patronal=emisor.get("RegistroPatronal"),
        rfc_patron_origen=emisor.get("RfcPatronOrigen"),
        origen_recurso=_clave(entidad.get("OrigenRecurso")),
        monto_recurso_propio=_decimal(entidad.get("MontoRecursoPropio")),
    )

    receptor = DatosNominaReceptor(
        curp=receptor_nodo.get("Curp"),
        nss=receptor_nodo.get("NumSeguridadSocial"),
        fecha_inicio_rel_laboral=_fecha(receptor_nodo.get("FechaInicioRelLaboral")),
        # El nombre del atributo lleva diéresis — no es un error de tipeo (§2.7 del fuente).
        antiguedad=receptor_nodo.get("Antigüedad"),
        tipo_contrato=_clave(receptor_nodo.get("TipoContrato")),
        sindicalizado=_clave(receptor_nodo.get("Sindicalizado")),
        tipo_jornada=_clave(receptor_nodo.get("TipoJornada")),
        tipo_regimen=_clave(receptor_nodo.get("TipoRegimen")),
        num_empleado=receptor_nodo.get("NumEmpleado"),
        departamento=receptor_nodo.get("Departamento"),
        puesto=receptor_nodo.get("Puesto"),
        riesgo_puesto=_clave(receptor_nodo.get("RiesgoPuesto")),
        periodicidad_pago=_clave(receptor_nodo.get("PeriodicidadPago")),
        banco=_clave(receptor_nodo.get("Banco")),
        cuenta_bancaria=receptor_nodo.get("CuentaBancaria"),
        salario_base_cot_apor=_decimal(receptor_nodo.get("SalarioBaseCotApor")),
        salario_diario_integrado=_decimal(receptor_nodo.get("SalarioDiarioIntegrado")),
        clave_ent_fed=_clave(receptor_nodo.get("ClaveEntFed")),
    )

    percepciones = [
        DatosPercepcion(
            tipo_percepcion=_clave(p.get("TipoPercepcion")) or "",
            clave=p.get("Clave"),
            concepto=p.get("Concepto"),
            importe_gravado=_decimal_o_cero(p.get("ImporteGravado")),
            importe_exento=_decimal_o_cero(p.get("ImporteExento")),
        )
        for p in _lista(percepciones_nodo, "Percepcion")
    ]

    deducciones = [
        DatosDeduccion(
            tipo_deduccion=_clave(d.get("TipoDeduccion")) or "",
            clave=d.get("Clave"),
            concepto=d.get("Concepto"),
            importe=_decimal_o_cero(d.get("Importe")),
        )
        for d in _lista(deducciones_nodo, "Deduccion")
    ]

    otros_pagos: list[DatosOtroPago] = []
    for o in _lista(nodo.get("OtrosPagos"), "OtroPago"):
        subsidio = o.get("SubsidioAlEmpleo") or {}
        compensacion = o.get("CompensacionSaldosAFavor") or {}
        otros_pagos.append(
            DatosOtroPago(
                tipo_otro_pago=_clave(o.get("TipoOtroPago")) or "",
                clave=o.get("Clave"),
                concepto=o.get("Concepto"),
                importe=_decimal_o_cero(o.get("Importe")),
                subsidio_causado=_decimal(subsidio.get("SubsidioCausado")),
                saldo_a_favor=_decimal(compensacion.get("SaldoAFavor")),
                anio=int(compensacion["Año"]) if compensacion.get("Año") is not None else None,
                remanente_sal_fav=_decimal(compensacion.get("RemanenteSalFav")),
            )
        )

    incapacidades = [
        DatosIncapacidad(
            dias_incapacidad=int(i["DiasIncapacidad"]) if i.get("DiasIncapacidad") is not None else None,
            tipo_incapacidad=_clave(i.get("TipoIncapacidad")),
            importe_monetario=_decimal(i.get("ImporteMonetario")),
        )
        for i in _lista(nodo.get("Incapacidades"), "Incapacidad")
    ]

    totales = DatosNominaTotales(
        total_sueldos=_decimal(percepciones_nodo.get("TotalSueldos")),
        total_separacion_indemnizacion=_decimal(percepciones_nodo.get("TotalSeparacionIndemnizacion")),
        total_jubilacion_pension_retiro=_decimal(percepciones_nodo.get("TotalJubilacionPensionRetiro")),
        total_gravado=_decimal(percepciones_nodo.get("TotalGravado")),
        total_exento=_decimal(percepciones_nodo.get("TotalExento")),
        total_otras_deducciones=_decimal(deducciones_nodo.get("TotalOtrasDeducciones")),
        total_impuestos_retenidos=_decimal(deducciones_nodo.get("TotalImpuestosRetenidos")),
    )

    return DatosNomina(
        cabecera=cabecera,
        receptor=receptor,
        totales=totales,
        percepciones=percepciones,
        deducciones=deducciones,
        otros_pagos=otros_pagos,
        incapacidades=incapacidades,
    )
```

Agregar el campo a `DatosComprobante`:

```python
    nomina: DatosNomina | None = None
```

Y en `normalizar`, después de construir `c`:

```python
    complemento = c.get("Complemento") or {}
    nomina_nodo = complemento.get("Nomina")
    return DatosComprobante(
        encabezado=_encabezado(c),
        conceptos=_conceptos(c),
        relacionados=_relacionados(c),
        nomina=_nomina(nomina_nodo) if nomina_nodo is not None else None,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_normalizacion_nomina.py -q`
Expected: PASS (7 tests)

- [ ] **Step 6: Verify against the real XML (no fixture committed)**

Esta comprobación usa los XML reales en disco y **no escribe nada a git**. Es la que
detecta si el fixture sintético divergió del XML real del SAT:

```bash
.venv/bin/python -c "
from decimal import Decimal
from app.services.normalizacion import normalizar
ruta = 'storage/11/comprobantes/CENTRO HUMANO DE LIDERAZGO_12_V_2.xml'
d = normalizar(open(ruta, 'rb').read())
n = d.nomina
assert n is not None, 'no se detectó el complemento de nómina'
print('dias:', n.cabecera.num_dias_pagados, '| periodicidad:', n.receptor.periodicidad_pago)
print('antiguedad:', n.receptor.antiguedad)
print('percepciones:', [(p.tipo_percepcion, p.clave) for p in n.percepciones])
print('deducciones:', [(x.tipo_deduccion, x.clave) for x in n.deducciones])
print('otros pagos:', [(o.tipo_otro_pago, o.clave) for o in n.otros_pagos])
suma = sum(p.importe_gravado + p.importe_exento for p in n.percepciones)
assert abs(suma - n.cabecera.total_percepciones) <= Decimal('0.01'), (suma, n.cabecera.total_percepciones)
print('identidad total_percepciones OK')
"
```

Expected: imprime la antigüedad como `P663W`, las 3 percepciones / 5 deducciones / 2 otros pagos del CFDI real, y `identidad total_percepciones OK`.

- [ ] **Step 7: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/services/normalizacion.py tests/fixtures_cfdi.py tests/test_normalizacion_nomina.py
git commit -m "feat(informes): agregar ETL del complemento de nomina 1.2"
```

---

### Task 6: ETL puro — complemento de Pagos 2.0

**Files:**
- Modify: `app/services/normalizacion.py`
- Modify: `tests/fixtures_cfdi.py`
- Test: `tests/test_normalizacion_pagos.py`

**Interfaces:**
- Consumes de las tareas 4–5: los helpers y `DatosImpuesto`.
- Produces: `@dataclass DatosPagoDocto`, `DatosPago`, `DatosPagoTotales`; campos `DatosComprobante.pagos: list[DatosPago]` y `DatosComprobante.pago_totales: DatosPagoTotales | None`.

- [ ] **Step 1: Add the REP fixture**

Agregar a `tests/fixtures_cfdi.py`:

```python
def cfdi_pago(
    *,
    uuid: str = "55555555-5555-5555-5555-555555555555",
    fecha: str = "2026-07-22T14:11:39",
    fecha_pago: str = "2026-07-22T12:00:00",
    monto: str = "10800.00",
    id_documento: str = "66666666-6666-6666-6666-6666666666ab",
    imp_pagado: str = "10800.00",
    doctos_extra: str = "",
    retenciones_dr_xml: str = "",
    pagos_extra: str = "",
) -> bytes:
    """CFDI 4.0 tipo P con complemento de Pagos 2.0: un pago que cubre un documento con
    IVA al 8 % y el nodo `Totales`. Emisor, folio e importes son inventados; los
    importes son aritméticamente coherentes (base 10000.00 × 8 % = 800.00, monto total
    10000.00 + 800.00 = 10800.00). `id_documento` lleva letras en minúsculas a propósito
    para que las pruebas puedan verificar la normalización a mayúsculas."""
    retenciones_bloque = (
        f"<pago20:RetencionesDR>{retenciones_dr_xml}</pago20:RetencionesDR>" if retenciones_dr_xml else ""
    )
    docto = (
        f'<pago20:DoctoRelacionado IdDocumento="{id_documento}" Serie="A" Folio="1001" '
        f'MonedaDR="MXN" EquivalenciaDR="1" NumParcialidad="1" ImpSaldoAnt="{monto}" '
        f'ImpPagado="{imp_pagado}" ImpSaldoInsoluto="0.00" ObjetoImpDR="02">'
        "<pago20:ImpuestosDR><pago20:TrasladosDR>"
        '<pago20:TrasladoDR BaseDR="10000.00" ImpuestoDR="002" TipoFactorDR="Tasa" '
        'TasaOCuotaDR="0.080000" ImporteDR="800.00" />'
        f"</pago20:TrasladosDR>{retenciones_bloque}</pago20:ImpuestosDR>"
        "</pago20:DoctoRelacionado>"
    )
    complemento_pagos = (
        '<pago20:Pagos xmlns:pago20="http://www.sat.gob.mx/Pagos20" Version="2.0">'
        '<pago20:Totales TotalTrasladosBaseIVA8="10000.00" TotalTrasladosImpuestoIVA8="800.00" '
        f'MontoTotalPagos="{monto}" />'
        f'<pago20:Pago FechaPago="{fecha_pago}" FormaDePagoP="03" MonedaP="MXN" TipoCambioP="1" '
        f'Monto="{monto}" NumOperacion="123456">{docto}{doctos_extra}</pago20:Pago>'
        f"{pagos_extra}"
        "</pago20:Pagos>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0" '
        f'Serie="P" Folio="1001" Fecha="{fecha}" Moneda="XXX" SubTotal="0" Total="0" '
        'TipoDeComprobante="P" Exportacion="01" LugarExpedicion="31000" '
        'NoCertificado="00001000000504465028" Certificado="Y2VydA==" Sello="c2VsbG8=">'
        '<cfdi:Emisor Rfc="DEM120101AAA" Nombre="PROVEEDOR DEMO SA DE CV" RegimenFiscal="601" />'
        '<cfdi:Receptor Rfc="CHL960913IX9" Nombre="CENTRO HUMANO DE LIDERAZGO" '
        'DomicilioFiscalReceptor="31000" RegimenFiscalReceptor="601" UsoCFDI="CP01" />'
        "<cfdi:Conceptos>"
        '<cfdi:Concepto ClaveProdServ="84111506" Cantidad="1" ClaveUnidad="ACT" '
        'Descripcion="Pago" ValorUnitario="0" Importe="0" ObjetoImp="01" />'
        "</cfdi:Conceptos>"
        "<cfdi:Complemento>"
        f"{complemento_pagos}"
        '<tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" '
        f'Version="1.1" UUID="{uuid}" FechaTimbrado="{fecha}" RfcProvCertif="AAA010101AAA" '
        'SelloCFD="c2VsbG8=" NoCertificadoSAT="00001000000504465028" SelloSAT="c2VsbG8=" />'
        "</cfdi:Complemento>"
        "</cfdi:Comprobante>"
    ).encode()


def pago_adicional(
    *,
    fecha_pago: str = "2026-07-23T09:00:00",
    monto: str = "500.00",
    num_operacion: str = "654321",
) -> str:
    """Bloque `<pago20:Pago>` mínimo, sin documento relacionado, para probar con
    `pagos_extra` de `cfdi_pago` que `num_pago` es la posición del nodo y no un valor
    fijo cuando el REP trae más de un pago."""
    return (
        f'<pago20:Pago FechaPago="{fecha_pago}" FormaDePagoP="03" MonedaP="MXN" '
        f'TipoCambioP="1" Monto="{monto}" NumOperacion="{num_operacion}" />'
    )


def retencion_dr(
    *,
    base: str = "10000.00",
    impuesto: str = "001",
    tasa_o_cuota: str = "0.100000",
    importe: str = "1000.00",
) -> str:
    """Bloque `<pago20:RetencionDR>` para probar, vía `retenciones_dr_xml` de
    `cfdi_pago`, la rama de retenciones de `_impuestos_de_docto` (naturaleza `'R'`)."""
    return (
        f'<pago20:RetencionDR BaseDR="{base}" ImpuestoDR="{impuesto}" TipoFactorDR="Tasa" '
        f'TasaOCuotaDR="{tasa_o_cuota}" ImporteDR="{importe}" />'
    )
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_normalizacion_pagos.py
"""ETL del complemento de Pagos 2.0. El grano de A-05 es una fila por documento pagado
en cada pago, así que el ETL debe conservar la jerarquía pago → documento → impuestos."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.services import normalizacion
from tests import fixtures_cfdi


def test_normaliza_pago_con_documento_e_impuestos() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_pago())

    assert len(datos.pagos) == 1
    pago = datos.pagos[0]
    assert pago.num_pago == 1
    assert pago.fecha_pago == datetime(2026, 7, 22, 12, 0, 0)
    assert pago.forma_de_pago_p == "03"
    assert pago.moneda_p == "MXN"
    assert pago.monto == Decimal("10800.00")
    assert pago.num_operacion == "123456"

    assert len(pago.doctos) == 1
    docto = pago.doctos[0]
    # El fixture usa letras en minúsculas en `id_documento`: verifica que el ETL las
    # normaliza a mayúsculas (regla de dominio, no solo un valor que ya viniera así).
    assert docto.id_documento == "66666666-6666-6666-6666-6666666666AB"
    assert docto.num_parcialidad == 1
    assert docto.imp_pagado == Decimal("10800.00")
    assert docto.imp_saldo_insoluto == Decimal("0.00")
    assert docto.equivalencia_dr == Decimal("1")

    assert len(docto.impuestos) == 1
    impuesto = docto.impuestos[0]
    assert impuesto.naturaleza == "T"
    assert impuesto.impuesto == "002"
    assert impuesto.tasa_o_cuota == Decimal("0.080000")
    assert impuesto.base == Decimal("10000.00")
    assert impuesto.importe == Decimal("800.00")


def test_normaliza_totales_del_rep() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_pago())

    assert datos.pago_totales is not None
    totales = datos.pago_totales
    assert totales.total_traslados_base_iva8 == Decimal("10000.00")
    assert totales.total_traslados_impuesto_iva8 == Decimal("800.00")
    assert totales.monto_total_pagos == Decimal("10800.00")
    # No informado ≠ cero: el REP real de la empresa 11 solo trae los campos del 8 %.
    assert totales.total_traslados_base_iva16 is None


def test_numera_los_pagos_en_orden() -> None:
    """`num_pago` es derivado: la posición del nodo (§2.5 del fuente). Con un solo
    `Pago` la prueba pasaría aunque el código hardcodeara `num_pago=1`, así que el
    fixture trae un segundo `Pago` para forzar que la numeración sea posicional."""
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_pago(pagos_extra=fixtures_cfdi.pago_adicional()))
    assert [p.num_pago for p in datos.pagos] == [1, 2]
    assert datos.pagos[1].monto == Decimal("500.00")
    assert datos.pagos[1].num_operacion == "654321"


def test_impuestos_de_docto_incluye_retenciones() -> None:
    """`RetencionesDR` usa la misma forma de mapa con llave compuesta que `TrasladosDR`
    (verificado contra un REP real); esta prueba cubre esa rama de `_impuestos_de_docto`
    que el traslado por sí solo no ejercita."""
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_pago(retenciones_dr_xml=fixtures_cfdi.retencion_dr()))

    docto = datos.pagos[0].doctos[0]
    assert len(docto.impuestos) == 2
    retencion = next(i for i in docto.impuestos if i.naturaleza == "R")
    assert retencion.impuesto == "001"
    assert retencion.tasa_o_cuota == Decimal("0.100000")
    assert retencion.base == Decimal("10000.00")
    assert retencion.importe == Decimal("1000.00")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_normalizacion_pagos.py -q`
Expected: FAIL — `datos.pagos` está vacío (`AssertionError: assert 0 == 1`).

- [ ] **Step 4: Extend the ETL with the payments complement**

Agregar a `app/services/normalizacion.py`:

```python
@dataclass(slots=True)
class DatosPagoDocto:
    id_documento: str
    serie: str | None
    folio: str | None
    moneda_dr: str | None
    equivalencia_dr: Decimal | None
    num_parcialidad: int | None
    imp_saldo_ant: Decimal | None
    imp_pagado: Decimal | None
    imp_saldo_insoluto: Decimal | None
    objeto_imp_dr: str | None
    impuestos: list[DatosImpuesto] = field(default_factory=list)


@dataclass(slots=True)
class DatosPago:
    num_pago: int
    fecha_pago: datetime | None
    forma_de_pago_p: str | None
    moneda_p: str | None
    tipo_cambio_p: Decimal | None
    monto: Decimal | None
    num_operacion: str | None
    rfc_emisor_cta_ord: str | None
    rfc_emisor_cta_ben: str | None
    cta_ordenante: str | None
    cta_beneficiario: str | None
    doctos: list[DatosPagoDocto] = field(default_factory=list)


@dataclass(slots=True)
class DatosPagoTotales:
    total_traslados_base_iva16: Decimal | None
    total_traslados_impuesto_iva16: Decimal | None
    total_traslados_base_iva8: Decimal | None
    total_traslados_impuesto_iva8: Decimal | None
    total_traslados_base_iva0: Decimal | None
    total_traslados_impuesto_iva0: Decimal | None
    total_traslados_base_iva_exento: Decimal | None
    total_retenciones_iva: Decimal | None
    total_retenciones_isr: Decimal | None
    total_retenciones_ieps: Decimal | None
    monto_total_pagos: Decimal | None


def _impuestos_de_docto(docto: Any) -> list[DatosImpuesto]:
    """Los atributos del complemento de pagos llevan sufijo `DR`: `BaseDR`, `ImpuestoDR`,
    `TasaOCuotaDR`, `ImporteDR` — no son los mismos nombres que a nivel concepto."""
    impuestos_nodo = docto.get("ImpuestosDR") or {}
    resultado: list[DatosImpuesto] = []
    for naturaleza, llave in (("T", "TrasladosDR"), ("R", "RetencionesDR")):
        agrupados = impuestos_nodo.get(llave) or {}
        valores = agrupados.values() if hasattr(agrupados, "values") else agrupados
        for nodo in valores:
            resultado.append(
                DatosImpuesto(
                    naturaleza=naturaleza,
                    impuesto=_clave(nodo.get("ImpuestoDR")) or "",
                    tipo_factor=_clave(nodo.get("TipoFactorDR")),
                    tasa_o_cuota=_decimal(nodo.get("TasaOCuotaDR")),
                    base=_decimal(nodo.get("BaseDR")),
                    importe=_decimal(nodo.get("ImporteDR")),
                )
            )
    return resultado


def _pagos(nodo: Any) -> tuple[list[DatosPago], DatosPagoTotales | None]:
    pagos: list[DatosPago] = []
    for indice, pago_nodo in enumerate(_lista(nodo.get("Pago"), "Pago"), start=1):
        doctos = [
            DatosPagoDocto(
                id_documento=str(d.get("IdDocumento") or "").upper(),
                serie=d.get("Serie"),
                folio=d.get("Folio"),
                moneda_dr=_clave(d.get("MonedaDR")),
                equivalencia_dr=_decimal(d.get("EquivalenciaDR")),
                num_parcialidad=int(d["NumParcialidad"]) if d.get("NumParcialidad") is not None else None,
                imp_saldo_ant=_decimal(d.get("ImpSaldoAnt")),
                imp_pagado=_decimal(d.get("ImpPagado")),
                imp_saldo_insoluto=_decimal(d.get("ImpSaldoInsoluto")),
                objeto_imp_dr=_clave(d.get("ObjetoImpDR")),
                impuestos=_impuestos_de_docto(d),
            )
            for d in _lista(pago_nodo.get("DoctoRelacionado"), "DoctoRelacionado")
        ]
        pagos.append(
            DatosPago(
                num_pago=indice,
                fecha_pago=_fecha_hora(pago_nodo.get("FechaPago")),
                forma_de_pago_p=_clave(pago_nodo.get("FormaDePagoP")),
                moneda_p=_clave(pago_nodo.get("MonedaP")),
                tipo_cambio_p=_decimal(pago_nodo.get("TipoCambioP")),
                monto=_decimal(pago_nodo.get("Monto")),
                num_operacion=pago_nodo.get("NumOperacion"),
                rfc_emisor_cta_ord=pago_nodo.get("RfcEmisorCtaOrd"),
                rfc_emisor_cta_ben=pago_nodo.get("RfcEmisorCtaBen"),
                cta_ordenante=pago_nodo.get("CtaOrdenante"),
                cta_beneficiario=pago_nodo.get("CtaBeneficiario"),
                doctos=doctos,
            )
        )

    totales_nodo = nodo.get("Totales")
    totales = None
    if totales_nodo is not None:
        totales = DatosPagoTotales(
            total_traslados_base_iva16=_decimal(totales_nodo.get("TotalTrasladosBaseIVA16")),
            total_traslados_impuesto_iva16=_decimal(totales_nodo.get("TotalTrasladosImpuestoIVA16")),
            total_traslados_base_iva8=_decimal(totales_nodo.get("TotalTrasladosBaseIVA8")),
            total_traslados_impuesto_iva8=_decimal(totales_nodo.get("TotalTrasladosImpuestoIVA8")),
            total_traslados_base_iva0=_decimal(totales_nodo.get("TotalTrasladosBaseIVA0")),
            total_traslados_impuesto_iva0=_decimal(totales_nodo.get("TotalTrasladosImpuestoIVA0")),
            total_traslados_base_iva_exento=_decimal(totales_nodo.get("TotalTrasladosBaseIVAExento")),
            total_retenciones_iva=_decimal(totales_nodo.get("TotalRetencionesIVA")),
            total_retenciones_isr=_decimal(totales_nodo.get("TotalRetencionesISR")),
            total_retenciones_ieps=_decimal(totales_nodo.get("TotalRetencionesIEPS")),
            monto_total_pagos=_decimal(totales_nodo.get("MontoTotalPagos")),
        )
    return pagos, totales
```

Agregar los campos a `DatosComprobante`:

```python
    pagos: list[DatosPago] = field(default_factory=list)
    pago_totales: DatosPagoTotales | None = None
```

Y en `normalizar`:

```python
    pagos_nodo = complemento.get("Pagos")
    pagos, pago_totales = _pagos(pagos_nodo) if pagos_nodo is not None else ([], None)
    return DatosComprobante(
        encabezado=_encabezado(c),
        conceptos=_conceptos(c),
        relacionados=_relacionados(c),
        nomina=_nomina(nomina_nodo) if nomina_nodo is not None else None,
        pagos=pagos,
        pago_totales=pago_totales,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_normalizacion_pagos.py -q`
Expected: PASS (4 tests)

- [ ] **Step 6: Verify against the real REPs**

No se nombra ningún archivo real (los nombres de archivo de la empresa 11 llevan el
nombre del proveedor): se descubren por su tipo de comprobante en vez de hardcodear una
ruta. **Ojo:** no asumas que hay un único REP en el directorio — verifícalo. La empresa
11 tiene decenas de REPs (comprobantes con `TipoDeComprobante="P"`), no uno solo, así que
la verificación barre todos y comprueba coherencia interna en cada uno, en vez de fijar
cifras de un archivo específico.

```bash
.venv/bin/python -c "
import glob
from decimal import Decimal
from app.services.normalizacion import normalizar

rutas = [r for r in glob.glob('storage/11/comprobantes/*.xml') if b'TipoDeComprobante=\"P\"' in open(r, 'rb').read()]
assert rutas, 'no se encontró ningún REP en storage/11/comprobantes'

con_pagos = 0
con_impuestos = 0
for ruta in rutas:
    d = normalizar(open(ruta, 'rb').read())
    if not d.pagos:
        continue
    con_pagos += 1
    for pago in d.pagos:
        for docto in pago.doctos:
            for impuesto in docto.impuestos:
                con_impuestos += 1
                if impuesto.base is not None and impuesto.tasa_o_cuota is not None and impuesto.importe is not None:
                    esperado = impuesto.base * impuesto.tasa_o_cuota
                    assert abs(esperado - impuesto.importe) < Decimal('1'), (ruta, impuesto)

print(f'REPs encontrados: {len(rutas)} | con al menos un pago: {con_pagos} | impuestos verificados: {con_impuestos}')
"
```

Expected: al menos un REP encontrado, todos con al menos un pago, y ningún `AssertionError`
de coherencia — cada traslado/retención cumple `base × tasa ≈ importe`. Ninguna cifra real
queda fija en esta instrucción; lo que se fija es la propiedad aritmética que debe cumplir
cualquier REP real, sea cual sea.

- [ ] **Step 7: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/services/normalizacion.py tests/fixtures_cfdi.py tests/test_normalizacion_pagos.py
git commit -m "feat(informes): agregar ETL del complemento de pagos 2.0"
```

---

### Task 7: Escritor idempotente

**Files:**
- Create: `app/repositories/normalizacion.py`
- Test: `tests/test_normalizacion_escritor.py`

**Interfaces:**
- Consumes de las tareas 1–6: los 15 modelos y `normalizacion.normalizar`, `normalizacion.hash_xml`, `normalizacion.ETL_VERSION`.
- Produces:
  - `async def escribir(db: AsyncSession, comprobante_id: int, datos: DatosComprobante, xml_hash: str) -> None`
  - `async def registrar_error(db: AsyncSession, comprobante_id: int, xml_hash: str, mensaje: str) -> None`
  - `async def necesita_normalizar(db: AsyncSession, comprobante_id: int, xml_hash: str) -> bool`
  - `async def ids_pendientes(db: AsyncSession, empresa_id: int, *, solo_tipo: str | None = None, desde: date | None = None, hasta: date | None = None) -> list[int]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_normalizacion_escritor.py
"""Escritor idempotente (spec §6.2).

Lo que estas pruebas fijan: reprocesar el mismo XML no duplica hijos, un XML corrupto
deja rastro para que el pre-vuelo no lo reintente en cada corrida, y subir `ETL_VERSION`
sí fuerza el reproceso.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cfdi_detalle import CfdiConcepto, CfdiConceptoImpuesto, ComprobanteDetalle
from app.models.nomina import NominaDeduccion, NominaPercepcion, NominaReceptor
from app.repositories import normalizacion as repo
from app.services import normalizacion
from tests import factories, fixtures_cfdi


async def _comprobante(db: AsyncSession, uuid: str, tipo: str = "I") -> int:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    c = await factories.crear_comprobante(db, empresa_id=empresa.empresa_id, uuid=uuid, tipo_comprobante=tipo)
    return c.comprobante_id


async def test_escribe_encabezado_conceptos_e_impuestos(db: AsyncSession) -> None:
    cid = await _comprobante(db, "11111111-1111-1111-1111-111111111111")
    xml = fixtures_cfdi.cfdi_ingreso()

    await repo.escribir(db, cid, normalizacion.normalizar(xml), normalizacion.hash_xml(xml))
    await db.commit()

    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == cid))
    assert detalle is not None
    assert detalle.version == "4.0"
    assert detalle.etl_version == normalizacion.ETL_VERSION
    assert detalle.normalizado_at is not None
    assert detalle.error_normalizacion is None
    assert await db.scalar(select(func.count()).select_from(CfdiConcepto).where(CfdiConcepto.comprobante_id == cid)) == 1
    assert await db.scalar(select(func.count()).select_from(CfdiConceptoImpuesto).where(CfdiConceptoImpuesto.comprobante_id == cid)) == 1


async def test_reprocesar_no_duplica_hijos(db: AsyncSession) -> None:
    """Borrar-e-insertar por `comprobante_id`, no `INSERT` a ciegas."""
    cid = await _comprobante(db, "22222222-2222-2222-2222-222222222222", tipo="N")
    xml = fixtures_cfdi.cfdi_nomina()
    datos = normalizacion.normalizar(xml)
    h = normalizacion.hash_xml(xml)

    await repo.escribir(db, cid, datos, h)
    await db.commit()
    await repo.escribir(db, cid, datos, h)
    await db.commit()

    assert await db.scalar(select(func.count()).select_from(NominaPercepcion).where(NominaPercepcion.comprobante_id == cid)) == 2
    assert await db.scalar(select(func.count()).select_from(NominaDeduccion).where(NominaDeduccion.comprobante_id == cid)) == 3
    assert await db.scalar(select(func.count()).select_from(NominaReceptor).where(NominaReceptor.comprobante_id == cid)) == 1


async def test_necesita_normalizar_respeta_hash_y_version(db: AsyncSession) -> None:
    cid = await _comprobante(db, "33333333-3333-3333-3333-333333333333")
    xml = fixtures_cfdi.cfdi_ingreso()
    h = normalizacion.hash_xml(xml)

    assert await repo.necesita_normalizar(db, cid, h) is True

    await repo.escribir(db, cid, normalizacion.normalizar(xml), h)
    await db.commit()

    # Mismo hash y misma versión → no hay nada que hacer.
    assert await repo.necesita_normalizar(db, cid, h) is False
    # XML distinto → sí.
    assert await repo.necesita_normalizar(db, cid, "f" * 64) is True

    # Subir la versión del ETL fuerza el reproceso de todo el histórico.
    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == cid))
    assert detalle is not None
    detalle.etl_version = normalizacion.ETL_VERSION - 1
    await db.commit()
    assert await repo.necesita_normalizar(db, cid, h) is True


async def test_registrar_error_deja_rastro_y_evita_reintento(db: AsyncSession) -> None:
    """Un XML corrupto se registra con su hash: sin esto, el pre-vuelo del informe lo
    reintentaría en cada corrida para siempre (spec §6.2)."""
    cid = await _comprobante(db, "44444444-4444-4444-4444-444444444444")

    await repo.registrar_error(db, cid, "a" * 64, "XML mal formado")
    await db.commit()

    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == cid))
    assert detalle is not None
    assert detalle.error_normalizacion == "XML mal formado"
    assert await repo.necesita_normalizar(db, cid, "a" * 64) is False


async def test_error_previo_se_limpia_al_reprocesar_bien(db: AsyncSession) -> None:
    cid = await _comprobante(db, "55555555-5555-5555-5555-555555555555")
    xml = fixtures_cfdi.cfdi_ingreso()
    h = normalizacion.hash_xml(xml)

    await repo.registrar_error(db, cid, h, "fallo transitorio")
    await db.commit()
    await repo.escribir(db, cid, normalizacion.normalizar(xml), h)
    await db.commit()

    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == cid))
    assert detalle is not None
    assert detalle.error_normalizacion is None


async def test_ids_pendientes_filtra_por_tipo(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    nomina = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="66666666-6666-6666-6666-666666666666", tipo_comprobante="N"
    )
    await factories.crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="77777777-7777-7777-7777-777777777777", tipo_comprobante="I")

    pendientes = await repo.ids_pendientes(db, empresa.empresa_id, solo_tipo="N")
    assert pendientes == [nomina.comprobante_id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_normalizacion_escritor.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.repositories.normalizacion'`

- [ ] **Step 3: Write the writer**

```python
# app/repositories/normalizacion.py
"""Persistencia del árbol que devuelve `app/services/normalizacion.py` (spec §6.2).

Idempotencia por borrar-e-insertar acotado a `comprobante_id`: reprocesar un comprobante
nunca duplica hijos y nunca toca los de otro comprobante. Todo ocurre en la transacción
del caller — este módulo no hace `commit`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cfdi_detalle import CfdiConcepto, CfdiConceptoImpuesto, CfdiRelacionado, ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.nomina import (
    Nomina,
    NominaDeduccion,
    NominaIncapacidad,
    NominaOtroPago,
    NominaPercepcion,
    NominaReceptor,
    NominaTotales,
)
from app.models.pago import Pago, PagoDocto, PagoDoctoImpuesto, PagoTotales
from app.services.normalizacion import ETL_VERSION, DatosComprobante

# Hijos que se borran antes de reinsertar. `cfdi_concepto_impuesto` y `pago_docto*` caen
# por cascada de sus padres, pero se listan explícitamente: depender de la cascada de
# MySQL para la idempotencia sería frágil si alguien cambia una FK.
_TABLAS_HIJAS = (
    CfdiConceptoImpuesto,
    CfdiConcepto,
    CfdiRelacionado,
    PagoDoctoImpuesto,
    PagoDocto,
    Pago,
    PagoTotales,
    NominaPercepcion,
    NominaDeduccion,
    NominaOtroPago,
    NominaIncapacidad,
    NominaTotales,
    NominaReceptor,
    Nomina,
)


async def necesita_normalizar(db: AsyncSession, comprobante_id: int, xml_hash: str) -> bool:
    """`False` solo si este XML exacto ya se procesó con la versión vigente del ETL —
    incluidos los que fallaron (su error ya quedó registrado, no se reintenta en bucle)."""
    fila = (
        await db.execute(
            select(ComprobanteDetalle.xml_hash, ComprobanteDetalle.etl_version).where(ComprobanteDetalle.comprobante_id == comprobante_id)
        )
    ).first()
    if fila is None:
        return True
    return not (fila.xml_hash == xml_hash and fila.etl_version == ETL_VERSION)


async def _limpiar_hijos(db: AsyncSession, comprobante_id: int) -> None:
    for tabla in _TABLAS_HIJAS:
        await db.execute(delete(tabla).where(tabla.comprobante_id == comprobante_id))  # type: ignore[attr-defined]


async def _upsert_detalle(db: AsyncSession, comprobante_id: int, valores: dict[str, Any]) -> None:
    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante_id))
    if detalle is None:
        db.add(ComprobanteDetalle(comprobante_id=comprobante_id, **valores))
        return
    for campo, valor in valores.items():
        setattr(detalle, campo, valor)


async def escribir(db: AsyncSession, comprobante_id: int, datos: DatosComprobante, xml_hash: str) -> None:
    """Persiste el árbol completo. Limpia los hijos anteriores y borra cualquier
    `error_normalizacion` previo: si llegamos aquí, el XML se leyó bien."""
    await _limpiar_hijos(db, comprobante_id)

    enc = datos.encabezado
    await _upsert_detalle(
        db,
        comprobante_id,
        {
            "version": enc.version,
            "serie": enc.serie,
            "fecha_timbrado": enc.fecha_timbrado,
            "forma_pago": enc.forma_pago,
            "metodo_pago": enc.metodo_pago,
            "moneda": enc.moneda,
            "tipo_cambio": enc.tipo_cambio,
            "subtotal": enc.subtotal,
            "descuento": enc.descuento,
            "lugar_expedicion": enc.lugar_expedicion,
            "exportacion": enc.exportacion,
            "regimen_emisor": enc.regimen_emisor,
            "nombre_receptor": enc.nombre_receptor,
            "domicilio_receptor": enc.domicilio_receptor,
            "regimen_receptor": enc.regimen_receptor,
            "uso_cfdi": enc.uso_cfdi,
            "no_certificado": enc.no_certificado,
            "no_certificado_sat": enc.no_certificado_sat,
            "xml_hash": xml_hash,
            "etl_version": ETL_VERSION,
            "normalizado_at": datetime.now(),
            "error_normalizacion": None,
        },
    )

    for concepto in datos.conceptos:
        fila = CfdiConcepto(
            comprobante_id=comprobante_id,
            num_linea=concepto.num_linea,
            clave_prod_serv=concepto.clave_prod_serv,
            no_identificacion=concepto.no_identificacion,
            cantidad=concepto.cantidad,
            clave_unidad=concepto.clave_unidad,
            unidad=concepto.unidad,
            descripcion=concepto.descripcion,
            valor_unitario=concepto.valor_unitario,
            importe=concepto.importe,
            descuento=concepto.descuento,
            objeto_imp=concepto.objeto_imp,
        )
        db.add(fila)
        await db.flush()  # necesitamos `fila.id` para los impuestos de la línea
        for impuesto in concepto.impuestos:
            db.add(
                CfdiConceptoImpuesto(
                    concepto_id=fila.id,
                    comprobante_id=comprobante_id,
                    naturaleza=impuesto.naturaleza,
                    impuesto=impuesto.impuesto,
                    tipo_factor=impuesto.tipo_factor,
                    tasa_o_cuota=impuesto.tasa_o_cuota,
                    base=impuesto.base,
                    importe=impuesto.importe,
                )
            )

    for relacionado in datos.relacionados:
        db.add(
            CfdiRelacionado(
                comprobante_id=comprobante_id,
                tipo_relacion=relacionado.tipo_relacion,
                uuid_relacionado=relacionado.uuid_relacionado,
            )
        )

    for pago in datos.pagos:
        fila_pago = Pago(
            comprobante_id=comprobante_id,
            num_pago=pago.num_pago,
            fecha_pago=pago.fecha_pago,
            forma_de_pago_p=pago.forma_de_pago_p,
            moneda_p=pago.moneda_p,
            tipo_cambio_p=pago.tipo_cambio_p,
            monto=pago.monto,
            num_operacion=pago.num_operacion,
            rfc_emisor_cta_ord=pago.rfc_emisor_cta_ord,
            cta_ordenante=pago.cta_ordenante,
            rfc_emisor_cta_ben=pago.rfc_emisor_cta_ben,
            cta_beneficiario=pago.cta_beneficiario,
        )
        db.add(fila_pago)
        await db.flush()
        for docto in pago.doctos:
            fila_docto = PagoDocto(
                pago_id=fila_pago.id,
                comprobante_id=comprobante_id,
                id_documento=docto.id_documento,
                serie=docto.serie,
                folio=docto.folio,
                moneda_dr=docto.moneda_dr,
                equivalencia_dr=docto.equivalencia_dr,
                num_parcialidad=docto.num_parcialidad,
                imp_saldo_ant=docto.imp_saldo_ant,
                imp_pagado=docto.imp_pagado,
                imp_saldo_insoluto=docto.imp_saldo_insoluto,
                objeto_imp_dr=docto.objeto_imp_dr,
            )
            db.add(fila_docto)
            await db.flush()
            for impuesto in docto.impuestos:
                db.add(
                    PagoDoctoImpuesto(
                        pago_docto_id=fila_docto.id,
                        comprobante_id=comprobante_id,
                        naturaleza=impuesto.naturaleza,
                        impuesto=impuesto.impuesto,
                        tipo_factor=impuesto.tipo_factor,
                        tasa_o_cuota=impuesto.tasa_o_cuota,
                        base=impuesto.base,
                        importe=impuesto.importe,
                    )
                )

    if datos.pago_totales is not None:
        t = datos.pago_totales
        db.add(
            PagoTotales(
                comprobante_id=comprobante_id,
                total_traslados_base_iva16=t.total_traslados_base_iva16,
                total_traslados_impuesto_iva16=t.total_traslados_impuesto_iva16,
                total_traslados_base_iva8=t.total_traslados_base_iva8,
                total_traslados_impuesto_iva8=t.total_traslados_impuesto_iva8,
                total_traslados_base_iva0=t.total_traslados_base_iva0,
                total_traslados_impuesto_iva0=t.total_traslados_impuesto_iva0,
                total_traslados_base_iva_exento=t.total_traslados_base_iva_exento,
                total_retenciones_iva=t.total_retenciones_iva,
                total_retenciones_isr=t.total_retenciones_isr,
                total_retenciones_ieps=t.total_retenciones_ieps,
                monto_total_pagos=t.monto_total_pagos,
            )
        )

    if datos.nomina is not None:
        nom = datos.nomina
        cab = nom.cabecera
        db.add(
            Nomina(
                comprobante_id=comprobante_id,
                version_nomina=cab.version_nomina,
                tipo_nomina=cab.tipo_nomina,
                fecha_pago=cab.fecha_pago,
                fecha_inicial_pago=cab.fecha_inicial_pago,
                fecha_final_pago=cab.fecha_final_pago,
                num_dias_pagados=cab.num_dias_pagados,
                total_percepciones=cab.total_percepciones,
                total_deducciones=cab.total_deducciones,
                total_otros_pagos=cab.total_otros_pagos,
                registro_patronal=cab.registro_patronal,
                rfc_patron_origen=cab.rfc_patron_origen,
                origen_recurso=cab.origen_recurso,
                monto_recurso_propio=cab.monto_recurso_propio,
            )
        )
        r = nom.receptor
        db.add(
            NominaReceptor(
                comprobante_id=comprobante_id,
                curp=r.curp,
                nss=r.nss,
                fecha_inicio_rel_laboral=r.fecha_inicio_rel_laboral,
                antiguedad=r.antiguedad,
                tipo_contrato=r.tipo_contrato,
                sindicalizado=r.sindicalizado,
                tipo_jornada=r.tipo_jornada,
                tipo_regimen=r.tipo_regimen,
                num_empleado=r.num_empleado,
                departamento=r.departamento,
                puesto=r.puesto,
                riesgo_puesto=r.riesgo_puesto,
                periodicidad_pago=r.periodicidad_pago,
                banco=r.banco,
                cuenta_bancaria=r.cuenta_bancaria,
                salario_base_cot_apor=r.salario_base_cot_apor,
                salario_diario_integrado=r.salario_diario_integrado,
                clave_ent_fed=r.clave_ent_fed,
            )
        )
        t = nom.totales
        db.add(
            NominaTotales(
                comprobante_id=comprobante_id,
                total_sueldos=t.total_sueldos,
                total_separacion_indemnizacion=t.total_separacion_indemnizacion,
                total_jubilacion_pension_retiro=t.total_jubilacion_pension_retiro,
                total_gravado=t.total_gravado,
                total_exento=t.total_exento,
                total_otras_deducciones=t.total_otras_deducciones,
                total_impuestos_retenidos=t.total_impuestos_retenidos,
            )
        )
        for percepcion in nom.percepciones:
            db.add(
                NominaPercepcion(
                    comprobante_id=comprobante_id,
                    tipo_percepcion=percepcion.tipo_percepcion,
                    clave=percepcion.clave,
                    concepto=percepcion.concepto,
                    importe_gravado=percepcion.importe_gravado,
                    importe_exento=percepcion.importe_exento,
                )
            )
        for deduccion in nom.deducciones:
            db.add(
                NominaDeduccion(
                    comprobante_id=comprobante_id,
                    tipo_deduccion=deduccion.tipo_deduccion,
                    clave=deduccion.clave,
                    concepto=deduccion.concepto,
                    importe=deduccion.importe,
                )
            )
        for otro in nom.otros_pagos:
            db.add(
                NominaOtroPago(
                    comprobante_id=comprobante_id,
                    tipo_otro_pago=otro.tipo_otro_pago,
                    clave=otro.clave,
                    concepto=otro.concepto,
                    importe=otro.importe,
                    subsidio_causado=otro.subsidio_causado,
                    saldo_a_favor=otro.saldo_a_favor,
                    anio=otro.anio,
                    remanente_sal_fav=otro.remanente_sal_fav,
                )
            )
        for incapacidad in nom.incapacidades:
            db.add(
                NominaIncapacidad(
                    comprobante_id=comprobante_id,
                    dias_incapacidad=incapacidad.dias_incapacidad,
                    tipo_incapacidad=incapacidad.tipo_incapacidad,
                    importe_monetario=incapacidad.importe_monetario,
                )
            )

    await db.flush()


async def registrar_error(db: AsyncSession, comprobante_id: int, xml_hash: str, mensaje: str) -> None:
    """Deja constancia del fallo con el hash del XML que lo produjo, para que el
    pre-vuelo no lo reintente en cada corrida (spec §6.2)."""
    await _limpiar_hijos(db, comprobante_id)
    await _upsert_detalle(
        db,
        comprobante_id,
        {
            "xml_hash": xml_hash,
            "etl_version": ETL_VERSION,
            "normalizado_at": datetime.now(),
            "error_normalizacion": mensaje[:500],
        },
    )
    await db.flush()


async def ids_pendientes(
    db: AsyncSession,
    empresa_id: int,
    *,
    solo_tipo: str | None = None,
    desde: date | None = None,
    hasta: date | None = None,
) -> list[int]:
    """Comprobantes de la empresa sin detalle, o con detalle de una versión vieja del ETL.
    No filtra por hash (eso requiere leer el XML); es el caller quien decide al leerlo."""
    consulta = (
        select(Comprobante.comprobante_id)
        .outerjoin(ComprobanteDetalle, ComprobanteDetalle.comprobante_id == Comprobante.comprobante_id)
        .where(
            Comprobante.empresa_id == empresa_id,
            Comprobante.xml_path.is_not(None),
            (ComprobanteDetalle.comprobante_id.is_(None)) | (ComprobanteDetalle.etl_version != ETL_VERSION),
        )
        .order_by(Comprobante.comprobante_id)
    )
    if solo_tipo is not None:
        consulta = consulta.where(Comprobante.tipo_comprobante == solo_tipo)
    if desde is not None:
        consulta = consulta.where(Comprobante.fecha_emision >= datetime.combine(desde, datetime.min.time()))
    if hasta is not None:
        consulta = consulta.where(Comprobante.fecha_emision <= datetime.combine(hasta, datetime.max.time()))
    return list((await db.execute(consulta)).scalars().all())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_normalizacion_escritor.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/repositories/normalizacion.py tests/test_normalizacion_escritor.py
git commit -m "feat(informes): agregar escritor idempotente de la capa normalizada"
```

---

### Task 8: Disparador 1 — normalizar al resguardar

**Files:**
- Modify: `app/services/resguardo.py:77-111` (función `_indexar_xml`)
- Test: `tests/test_resguardo_normaliza.py`

**Interfaces:**
- Consumes: `repo_normalizacion.escribir`, `repo_normalizacion.registrar_error`, `normalizacion.normalizar`, `normalizacion.hash_xml`.
- Produces: ningún símbolo nuevo. Efecto: todo CFDI que entra por descarga queda normalizado en la misma transacción.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resguardo_normaliza.py
"""Disparador 1 (spec §6.3): lo que entra por descarga queda normalizado.

La regla que no se negocia: un XML que el ETL no puede leer **no** impide que el
comprobante se indexe. El índice es lo que la UI necesita; la normalización es un extra.
"""

from __future__ import annotations

import os
import zipfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoJob
from app.models.job import Job
from app.models.nomina import Nomina
from app.services import resguardo
from tests import factories, fixtures_cfdi


async def _job_con_paquete(db: AsyncSession, empresa_id: int, xmls: dict[str, bytes]) -> Job:
    job = Job(
        empresa_id=empresa_id,
        tipo=TipoJob.EMITIDO,
        solicitud=SolicitudTipo.CFDI,
        origen=OrigenJob.MANUAL,
        desde="2026-06-01",
        hasta="2026-07-31",
        estado=EstadoJob.DESCARGADO,
    )
    db.add(job)
    await db.flush()
    await db.commit()

    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), "paquetes", str(job.job_id))
    os.makedirs(carpeta, exist_ok=True)
    with zipfile.ZipFile(os.path.join(carpeta, "paquete_01.zip"), "w") as zf:
        for nombre, contenido in xmls.items():
            zf.writestr(nombre, contenido)
    return job


async def test_indexar_job_normaliza_la_nomina(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    job = await _job_con_paquete(db, empresa.empresa_id, {"nomina.xml": fixtures_cfdi.cfdi_nomina()})

    nuevos = await resguardo.indexar_job(db, job, empresa)
    assert nuevos == 1

    comprobante = await db.scalar(select(Comprobante).where(Comprobante.empresa_id == empresa.empresa_id))
    assert comprobante is not None
    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante.comprobante_id))
    assert detalle is not None
    assert detalle.error_normalizacion is None
    nomina = await db.scalar(select(Nomina).where(Nomina.comprobante_id == comprobante.comprobante_id))
    assert nomina is not None
    assert nomina.tipo_nomina == "O"


async def test_xml_ilegible_para_el_etl_no_impide_indexar(db: AsyncSession, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Si `normalizar` truena, el comprobante se indexa igual y el fallo queda registrado."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    job = await _job_con_paquete(db, empresa.empresa_id, {"ingreso.xml": fixtures_cfdi.cfdi_ingreso()})

    def _explota(_xml: bytes) -> None:
        raise ValueError("nodo inesperado")

    monkeypatch.setattr(resguardo.normalizacion, "normalizar", _explota)

    nuevos = await resguardo.indexar_job(db, job, empresa)
    assert nuevos == 1

    comprobante = await db.scalar(select(Comprobante).where(Comprobante.empresa_id == empresa.empresa_id))
    assert comprobante is not None
    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante.comprobante_id))
    assert detalle is not None
    assert detalle.error_normalizacion is not None
    assert "nodo inesperado" in detalle.error_normalizacion
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_resguardo_normaliza.py -q`
Expected: FAIL — `detalle` es `None` (`assert detalle is not None`), porque `_indexar_xml` todavía no normaliza.

- [ ] **Step 3: Hook the ETL into `_indexar_xml`**

En `app/services/resguardo.py`, agregar a los imports:

```python
from app.repositories import normalizacion as repo_normalizacion
from app.services import normalizacion
```

Y al final de `_indexar_xml`, reemplazar:

```python
    await db.flush()
    return True
```

por:

```python
    await db.flush()

    # Disparador 1 del ETL (spec §6.3): lo que entra por descarga queda normalizado.
    # Un fallo aquí NO impide indexar — el índice es lo que la UI necesita.
    nuevo = await db.scalar(
        select(Comprobante.comprobante_id).where(Comprobante.empresa_id == empresa.empresa_id, Comprobante.uuid == campos.uuid)
    )
    if nuevo is not None:
        xml_hash = normalizacion.hash_xml(xml_bytes)
        try:
            await repo_normalizacion.escribir(db, nuevo, normalizacion.normalizar(xml_bytes), xml_hash)
        except Exception as exc:  # noqa: BLE001 — se registra y se sigue
            logger.warning("indexar: no se pudo normalizar el comprobante %s: %s", nuevo, exc)
            await repo_normalizacion.registrar_error(db, nuevo, xml_hash, str(exc))

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_resguardo_normaliza.py tests/test_resguardo.py -q`
Expected: PASS. `tests/test_resguardo.py` (ya existente) debe seguir verde: el enganche no cambia el conteo de indexados.

- [ ] **Step 5: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/services/resguardo.py tests/test_resguardo_normaliza.py
git commit -m "feat(informes): normalizar los CFDI al resguardarlos en la descarga"
```

---

### Task 9: Disparador 2 — tarea de reproceso y su endpoint

**Files:**
- Modify: `app/worker/tasks.py` (agregar al final)
- Create: `app/api/v1/informes.py`
- Modify: `app/main.py` (registrar el router)
- Modify: `app/api/v1/schemas.py` (agregar `NormalizarIn`)
- Test: `tests/test_normalizacion_tarea.py`

**Interfaces:**
- Consumes: `repo_normalizacion.*`, `normalizacion.*`, `representaciones.leer_xml_de_disco`.
- Produces:
  - Tarea Celery `app.worker.tasks.normalizar_comprobantes(empresa_id: int, alcance: str, comprobante_ids: list[int] | None = None) -> dict[str, Any]` con `alcance ∈ {"pendientes", "todos"}`; devuelve `{"normalizados": int, "con_error": int, "omitidos": int}`.
  - `async def normalizar_lote(db, empresa_id, comprobante_ids) -> dict[str, int]` en `app/services/normalizacion_lote.py` — reusable por el pre-vuelo de la tarea 13.
  - `POST /v1/empresas/{empresa_id}/informes/normalizar` (rol OPERADOR) → `202` + `tarea_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_normalizacion_tarea.py
"""Disparador 2 (spec §6.3): reproceso por lote de los XML que ya están en disco."""

from __future__ import annotations

import os

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.nomina import NominaPercepcion
from app.services import normalizacion_lote
from tests import factories, fixtures_cfdi


async def _comprobante_con_xml(db: AsyncSession, empresa_id: int, uuid: str, xml: bytes, tipo: str) -> int:
    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), "comprobantes")
    os.makedirs(carpeta, exist_ok=True)
    nombre = f"{uuid}.xml"
    with open(os.path.join(carpeta, nombre), "wb") as f:
        f.write(xml)
    ruta_relativa = os.path.join(str(empresa_id), "comprobantes", nombre)
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa_id, uuid=uuid, tipo_comprobante=tipo, xml_path=ruta_relativa
    )
    return comprobante.comprobante_id


async def test_normaliza_lote_y_es_idempotente(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    cid = await _comprobante_con_xml(db, empresa.empresa_id, "77777777-7777-7777-7777-777777777777", fixtures_cfdi.cfdi_nomina(), "N")

    resumen = await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [cid])
    assert resumen == {"normalizados": 1, "con_error": 0, "omitidos": 0}
    assert await db.scalar(select(func.count()).select_from(NominaPercepcion).where(NominaPercepcion.comprobante_id == cid)) == 2

    # Segunda corrida: mismo hash y misma versión del ETL → se omite, no se reprocesa.
    resumen = await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [cid])
    assert resumen == {"normalizados": 0, "con_error": 0, "omitidos": 1}
    assert await db.scalar(select(func.count()).select_from(NominaPercepcion).where(NominaPercepcion.comprobante_id == cid)) == 2


async def test_xml_ausente_en_disco_cuenta_como_error_no_como_excepcion(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="88888888-8888-8888-8888-888888888888", xml_path="11/comprobantes/no-existe.xml"
    )

    resumen = await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [comprobante.comprobante_id])
    assert resumen == {"normalizados": 0, "con_error": 1, "omitidos": 0}

    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante.comprobante_id))
    assert detalle is not None
    assert detalle.error_normalizacion is not None


async def test_un_xml_corrupto_no_aborta_el_lote(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    malo = await _comprobante_con_xml(db, empresa.empresa_id, "99999999-9999-9999-9999-999999999999", b"<esto no es un cfdi>", "I")
    bueno = await _comprobante_con_xml(db, empresa.empresa_id, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", fixtures_cfdi.cfdi_ingreso(), "I")

    resumen = await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [malo, bueno])
    assert resumen == {"normalizados": 1, "con_error": 1, "omitidos": 0}

    detalle_bueno = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == bueno))
    assert detalle_bueno is not None
    assert detalle_bueno.error_normalizacion is None


async def test_endpoint_de_reproceso_encola_y_pide_operador(client, db: AsyncSession, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.models.enums import RolEmpresa, RolGlobal
    from app.worker import tasks

    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    operador = await factories.crear_usuario(db, uid="op", correo="op@test.mx", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)
    consulta = await factories.crear_usuario(db, uid="con", correo="con@test.mx", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, consulta, empresa, RolEmpresa.CONSULTA)

    encoladas: list[tuple[int, str]] = []

    class _Tarea:
        id = "tarea-fake"

    monkeypatch.setattr(
        tasks.normalizar_comprobantes,
        "delay",
        lambda empresa_id, alcance, ids=None: (encoladas.append((empresa_id, alcance)), _Tarea())[1],
    )

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/informes/normalizar",
        json={"alcance": "pendientes"},
        headers={"Authorization": "Bearer op"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["tarea_id"] == "tarea-fake"
    assert encoladas == [(empresa.empresa_id, "pendientes")]

    # Rol de consulta no puede disparar un reproceso.
    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/informes/normalizar",
        json={"alcance": "pendientes"},
        headers={"Authorization": "Bearer con"},
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_normalizacion_tarea.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.normalizacion_lote'`

- [ ] **Step 3: Write the batch service**

```python
# app/services/normalizacion_lote.py
"""Normalización por lote: lee el XML de disco, lo parsea y lo persiste (spec §6.3).

Compartido por el disparador 2 (tarea de reproceso) y el disparador 3 (pre-vuelo del
informe). Ningún XML individual aborta el lote.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.comprobante import Comprobante
from app.repositories import normalizacion as repo_normalizacion
from app.services import normalizacion, representaciones

logger = logging.getLogger(__name__)


async def normalizar_lote(db: AsyncSession, empresa_id: int, comprobante_ids: list[int]) -> dict[str, int]:
    """Devuelve `{"normalizados": n, "con_error": n, "omitidos": n}`.

    `omitidos` son los que ya estaban al día (mismo hash, misma `ETL_VERSION`). Commitea
    por comprobante: un lote largo que se interrumpa deja avanzado lo que ya procesó.
    """
    storage_root = get_settings().storage_root
    resumen = {"normalizados": 0, "con_error": 0, "omitidos": 0}

    for comprobante_id in comprobante_ids:
        comprobante = await db.scalar(
            select(Comprobante).where(Comprobante.comprobante_id == comprobante_id, Comprobante.empresa_id == empresa_id)
        )
        if comprobante is None:
            continue  # id de otra empresa: se ignora, igual que en `validar_lote`

        xml_bytes = representaciones.leer_xml_de_disco(storage_root, comprobante)
        if xml_bytes is None:
            await repo_normalizacion.registrar_error(db, comprobante_id, "0" * 64, "El XML no está en disco.")
            await db.commit()
            resumen["con_error"] += 1
            continue

        xml_hash = normalizacion.hash_xml(xml_bytes)
        if not await repo_normalizacion.necesita_normalizar(db, comprobante_id, xml_hash):
            resumen["omitidos"] += 1
            continue

        try:
            await repo_normalizacion.escribir(db, comprobante_id, normalizacion.normalizar(xml_bytes), xml_hash)
            await db.commit()
            resumen["normalizados"] += 1
        except Exception as exc:  # noqa: BLE001 — un XML corrupto no aborta el lote
            await db.rollback()
            logger.warning("normalizar_lote: comprobante %s no se pudo normalizar: %s", comprobante_id, exc)
            await repo_normalizacion.registrar_error(db, comprobante_id, xml_hash, str(exc))
            await db.commit()
            resumen["con_error"] += 1

    return resumen
```

- [ ] **Step 4: Write the Celery task**

Agregar al final de `app/worker/tasks.py`:

```python
# --------------------------------------------------------------------------- #
# Normalización (ETL) — disparador 2 del spec §6.3: reproceso de los XML que ya
# están en disco. Idempotente: se puede volver a lanzar cuantas veces se quiera.
# --------------------------------------------------------------------------- #


async def _normalizar_comprobantes_async(empresa_id: int, alcance: str, comprobante_ids: list[int] | None) -> dict[str, Any]:
    from app.repositories import normalizacion as repo_normalizacion
    from app.services import normalizacion_lote

    async with SessionLocal() as db:
        if comprobante_ids:
            ids = comprobante_ids
        elif alcance == "todos":
            ids = await comprobantes_repo.ids_todos(db, empresa_id)
        else:
            ids = await repo_normalizacion.ids_pendientes(db, empresa_id)

        resumen = await normalizacion_lote.normalizar_lote(db, empresa_id, ids)

    logger.info("normalizar_comprobantes: empresa %s alcance %s → %s", empresa_id, alcance, resumen)
    return {"solicitados": len(ids), **resumen}


@celery_app.task(name="app.worker.tasks.normalizar_comprobantes")  # type: ignore[untyped-decorator]
def normalizar_comprobantes(empresa_id: int, alcance: str = "pendientes", comprobante_ids: list[int] | None = None) -> dict[str, Any]:
    return asyncio.run(_normalizar_comprobantes_async(empresa_id, alcance, comprobante_ids))
```

- [ ] **Step 5: Add the request schema**

Agregar a `app/api/v1/schemas.py`:

```python
class NormalizarIn(BaseModel):
    """Alcance del reproceso del ETL. `pendientes` es lo normal; `todos` se usa tras subir
    `ETL_VERSION`, cuando hay que releer el histórico completo."""

    alcance: Literal["pendientes", "todos"] = "pendientes"
```

- [ ] **Step 6: Write the endpoint**

```python
# app/api/v1/informes.py
"""POST /v1/empresas/{id}/informes/normalizar y el catálogo/generación de informes
(spec §7.2). En esta tarea solo el reproceso del ETL; los informes llegan en la tarea 13."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_empresa
from app.api.v1.schemas import NormalizarIn, TareaCrearOut
from app.models.enums import RolEmpresa
from app.services import bitacora as bitacora_service
from app.worker.tasks import normalizar_comprobantes

router = APIRouter(prefix="/empresas/{empresa_id}/informes", tags=["informes"])


@router.post("/normalizar", status_code=status.HTTP_202_ACCEPTED, response_model=TareaCrearOut)
async def normalizar_endpoint(
    empresa_id: int,
    body: NormalizarIn,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> TareaCrearOut:
    """Reprocesa los XML ya resguardados hacia la capa normalizada. Pide OPERADOR: es una
    escritura masiva, aunque idempotente."""
    await bitacora_service.registrar(
        db, actor=ctx.usuario.correo, accion="normalizar_comprobantes", entidad=f"empresa:{empresa_id}", detalle={"alcance": body.alcance}
    )
    await db.commit()

    tarea = normalizar_comprobantes.delay(empresa_id, body.alcance)
    return TareaCrearOut(tarea_id=tarea.id)
```

- [ ] **Step 7: Register the router**

En `app/main.py`, junto a los otros `include_router` de `v1`:

```python
from app.api.v1 import informes as informes_router
...
app.include_router(informes_router.router, prefix="/v1")
```

Verificar el prefijo exacto que usan los routers vecinos (`comprobantes`, `tareas`) y seguir el mismo patrón.

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_normalizacion_tarea.py -q`
Expected: PASS (4 tests)

- [ ] **Step 9: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/services/normalizacion_lote.py app/worker/tasks.py app/api/v1/informes.py app/api/v1/schemas.py app/main.py tests/test_normalizacion_tarea.py
git commit -m "feat(informes): agregar tarea y endpoint de reproceso del ETL"
```

---

### Task 10: Motor de informes — contrato, registro y libro de Excel

**Files:**
- Create: `app/informes/__init__.py`
- Create: `app/informes/base.py`
- Create: `app/informes/registro.py`
- Create: `app/informes/excel.py`
- Test: `tests/test_informes_excel.py`

**Interfaces:**
- Produces:
  - `SEPARADOR_ETIQUETA = "¦"` (R-T8)
  - `@dataclass Columna` con `titulo: str`, `tipo: Literal["texto", "monto", "entero", "decimal", "fecha", "fecha_hora"]`
  - `@dataclass Bandera` con `clave: str`, `severidad: Literal["alta", "media", "baja"]`, `ambito: str`, `mensaje: str`
  - `@dataclass EntradaDiccionario` con `etiqueta`, `naturaleza`, `tipo`, `descripcion_sat`, `clave_patron`, `concepto_canonico`, `descripciones_alternas: list[str]`, `num_comprobantes: int`, `importe_total: Decimal`
  - `@dataclass ResultadoInforme` con `columnas: list[Columna]`, `filas: list[list[Any]]`, `banderas: list[Bandera]`, `diccionario: list[EntradaDiccionario]`, `aviso: str | None`
  - `@dataclass ContextoInforme` con `clave`, `nombre`, `usuario`, `generado_en: datetime`, `parametros: dict[str, Any]`, `etl_version: int`
  - `def escribir_libro(resultado: ResultadoInforme, ctx: ContextoInforme) -> bytes`
  - `def enmascarar(valor: str | None) -> str | None`
  - `class DefinicionInforme(Protocol)` y `REGISTRO: dict[str, DefinicionInforme]`, `def obtener(clave: str) -> DefinicionInforme`, `def catalogo() -> list[dict[str, Any]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_informes_excel.py
"""Motor de informes: el libro común de cuatro hojas (spec §10) y el enmascaramiento.

Las aserciones se hacen sobre valores de celda, nunca sobre bytes del archivo (spec §13).
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal

from openpyxl import load_workbook

from app.informes import excel
from app.informes.base import Bandera, Columna, ContextoInforme, EntradaDiccionario, ResultadoInforme


def _resultado_demo() -> ResultadoInforme:
    return ResultadoInforme(
        columnas=[
            Columna(titulo="UUID", tipo="texto"),
            Columna(titulo="Fecha pago", tipo="fecha"),
            Columna(titulo="P¦001¦001¦Sueldo", tipo="monto"),
        ],
        filas=[["11111111-1111-1111-1111-111111111111", datetime(2026, 6, 30).date(), Decimal("8759.700000")]],
        banderas=[Bandera(clave="NETO_NEGATIVO", severidad="alta", ambito="uuid:1111", mensaje="El total es negativo.")],
        diccionario=[
            EntradaDiccionario(
                etiqueta="P¦001¦001¦Sueldo",
                naturaleza="P",
                tipo="001",
                descripcion_sat="Sueldos, Salarios Rayas y Jornales",
                clave_patron="001",
                concepto_canonico="Sueldo",
                descripciones_alternas=["Sueldos"],
                num_comprobantes=8,
                importe_total=Decimal("70077.60"),
            )
        ],
    )


def _contexto() -> ContextoInforme:
    return ContextoInforme(
        clave="B-02",
        nombre="Nómina agrupada por conceptos del patrón",
        usuario="dgarcia@planjuarez.org",
        generado_en=datetime(2026, 8, 5, 11, 30, 0),
        parametros={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31", "enmascarar_datos_personales": True},
        etl_version=1,
    )


def test_libro_tiene_las_cuatro_hojas() -> None:
    wb = load_workbook(io.BytesIO(excel.escribir_libro(_resultado_demo(), _contexto())))
    assert wb.sheetnames == ["Datos", "Parámetros", "Banderas", "Diccionario"]


def test_hoja_datos_lleva_encabezado_y_valores() -> None:
    wb = load_workbook(io.BytesIO(excel.escribir_libro(_resultado_demo(), _contexto())))
    ws = wb["Datos"]

    assert [c.value for c in ws[1]] == ["UUID", "Fecha pago", "P¦001¦001¦Sueldo"]
    fila = [c.value for c in ws[2]]
    assert fila[0] == "11111111-1111-1111-1111-111111111111"
    # Redondeo único al presentar (R-T4): 6 decimales en BD → 2 en la celda.
    assert float(fila[2]) == 8759.70
    # Encabezado congelado para que la tabla sea navegable.
    assert ws.freeze_panes == "A2"


def test_hoja_parametros_permite_reproducir_la_corrida() -> None:
    """Sin esta hoja un Excel circulando por correo no se puede auditar (spec §10)."""
    wb = load_workbook(io.BytesIO(excel.escribir_libro(_resultado_demo(), _contexto())))
    ws = wb["Parámetros"]
    contenido = {ws.cell(row=f, column=1).value: ws.cell(row=f, column=2).value for f in range(1, ws.max_row + 1)}

    assert contenido["Informe"] == "B-02 · Nómina agrupada por conceptos del patrón"
    assert contenido["Generado por"] == "dgarcia@planjuarez.org"
    assert contenido["Versión del ETL"] == 1
    assert contenido["Filas"] == 1
    assert contenido["fecha_desde"] == "2026-06-01"
    assert contenido["enmascarar_datos_personales"] == "True"


def test_hoja_banderas_y_diccionario() -> None:
    wb = load_workbook(io.BytesIO(excel.escribir_libro(_resultado_demo(), _contexto())))

    banderas = wb["Banderas"]
    assert [c.value for c in banderas[1]] == ["Bandera", "Severidad", "Ámbito", "Mensaje"]
    assert [c.value for c in banderas[2]] == ["NETO_NEGATIVO", "alta", "uuid:1111", "El total es negativo."]

    diccionario = wb["Diccionario"]
    fila = [c.value for c in diccionario[2]]
    assert fila[0] == "P¦001¦001¦Sueldo"
    assert fila[1] == "P"
    assert fila[3] == "Sueldos, Salarios Rayas y Jornales"
    assert fila[6] == "Sueldos"  # descripciones alternas, unidas por '; '


def test_informe_vacio_produce_libro_con_aviso_no_una_excepcion() -> None:
    """spec §9: sin filas no es un error."""
    vacio = ResultadoInforme(columnas=[Columna(titulo="UUID", tipo="texto")], filas=[], aviso="Sin comprobantes en el rango solicitado.")
    wb = load_workbook(io.BytesIO(excel.escribir_libro(vacio, _contexto())))

    assert "Datos" in wb.sheetnames
    parametros = wb["Parámetros"]
    contenido = {parametros.cell(row=f, column=1).value: parametros.cell(row=f, column=2).value for f in range(1, parametros.max_row + 1)}
    assert contenido["Filas"] == 0
    assert contenido["Aviso"] == "Sin comprobantes en el rango solicitado."


def test_enmascarar_conserva_los_ultimos_cuatro() -> None:
    assert excel.enmascarar("XXXX800101HCHXXX01") == "****XX01"
    assert excel.enmascarar("12345678901") == "****8901"
    assert excel.enmascarar(None) is None
    assert excel.enmascarar("123") == "****"  # demasiado corto para conservar 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_informes_excel.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.informes'`

- [ ] **Step 3: Write the base contract**

```python
# app/informes/__init__.py
"""Motor de informes derivados de CFDI (spec §7).

Cada informe es un módulo con `CLAVE`, `NOMBRE`, `GRUPO`, `DESCRIPCION`, una clase
`Parametros` de pydantic, una corrutina `consultar` y —opcionalmente— un `escribir`.
El registro (`registro.py`) los expone al API; agregar un informe no toca ni el endpoint
ni el frontend.
"""
```

```python
# app/informes/base.py
"""Tipos compartidos por todos los informes (spec §7.1, §10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

SEPARADOR_ETIQUETA = "¦"
"""Barra vertical partida (U+00A6) para las etiquetas de columnas dinámicas (R-T8).

**No se usa `/`**: los `@Concepto` del catálogo del SAT contienen diagonales, lo que hace
ambiguo cualquier `split('/')` del lado del consumidor.
"""

TipoColumna = Literal["texto", "monto", "entero", "decimal", "fecha", "fecha_hora"]
Severidad = Literal["alta", "media", "baja"]


@dataclass(slots=True)
class Columna:
    titulo: str
    tipo: TipoColumna = "texto"


@dataclass(slots=True)
class Bandera:
    """Un hallazgo. Va en su propia hoja en vez de colorear celdas: así es filtrable y no
    se pierde al copiar (spec §10)."""

    clave: str
    severidad: Severidad
    ambito: str
    mensaje: str


@dataclass(slots=True)
class EntradaDiccionario:
    """Fila de la hoja `Diccionario`: permite al consumidor resolver una columna dinámica
    sin parsear su nombre (spec §10)."""

    etiqueta: str
    naturaleza: str
    tipo: str
    descripcion_sat: str | None
    clave_patron: str | None
    concepto_canonico: str | None
    descripciones_alternas: list[str] = field(default_factory=list)
    num_comprobantes: int = 0
    importe_total: Decimal = Decimal("0")


@dataclass(slots=True)
class ResultadoInforme:
    columnas: list[Columna]
    filas: list[list[Any]] = field(default_factory=list)
    banderas: list[Bandera] = field(default_factory=list)
    diccionario: list[EntradaDiccionario] = field(default_factory=list)
    aviso: str | None = None


@dataclass(slots=True)
class ContextoInforme:
    """Lo que va a la hoja `Parámetros` para que la corrida sea reproducible."""

    clave: str
    nombre: str
    usuario: str
    generado_en: datetime
    parametros: dict[str, Any]
    etl_version: int


class DefinicionInforme(Protocol):
    """Contrato que cumple cada módulo de informe."""

    CLAVE: str
    NOMBRE: str
    GRUPO: str
    DESCRIPCION: str

    Parametros: type[Any]

    async def consultar(self, db: Any, empresa_id: int, parametros: Any) -> ResultadoInforme: ...
```

- [ ] **Step 4: Write the workbook writer**

```python
# app/informes/excel.py
"""Construcción del libro de Excel común a todos los informes (spec §10).

Cuatro hojas siempre: `Datos`, `Parámetros`, `Banderas`, `Diccionario`. `openpyxl` en modo
`write_only` para no cargar el libro completo en memoria — el mismo patrón que
`exportar_excel` en `app/worker/tasks.py`.

`ROUND_HALF_UP` explícito: el redondeo por defecto de Python es `ROUND_HALF_EVEN`, que
para importes fiscales es incorrecto (⌊x⌉₂ del documento fuente es medio arriba).
"""

from __future__ import annotations

import io
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from app.informes.base import Bandera, Columna, ContextoInforme, EntradaDiccionario, ResultadoInforme

_FORMATO = {
    "monto": "#,##0.00",
    "decimal": "#,##0.000",
    "entero": "#,##0",
    "fecha": "yyyy-mm-dd",
    "fecha_hora": "yyyy-mm-dd hh:mm:ss",
    "texto": "@",
}
_NEGRITA = Font(bold=True)
_DOS_DECIMALES = Decimal("0.01")


def enmascarar(valor: str | None) -> str | None:
    """`****` conservando los últimos 4 caracteres (spec §8). Un valor de 4 o menos se
    enmascara por completo: conservar 4 de 4 no enmascararía nada."""
    if valor is None:
        return None
    texto = str(valor)
    return "****" if len(texto) <= 4 else f"****{texto[-4:]}"


def _celda(valor: Any, tipo: str) -> Any:
    """Único punto donde se redondea (R-T4)."""
    if valor is None:
        return None
    if tipo == "monto" and isinstance(valor, Decimal):
        return valor.quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, (datetime, date)):
        return valor
    return valor


def _con_estilo(ws: Any, valor: Any, *, formato: str | None = None, negrita: bool = False) -> Any:
    """En modo `write_only` no existe `ws.cell(...)`: el estilo se aplica al construir la
    celda con `WriteOnlyCell` antes de hacer `append`."""
    celda = WriteOnlyCell(ws, value=valor)
    if formato:
        celda.number_format = formato
    if negrita:
        celda.font = _NEGRITA
    return celda


def _escribir_datos(wb: Workbook, resultado: ResultadoInforme) -> None:
    ws = wb.create_sheet("Datos")
    ws.freeze_panes = "A2"

    ws.append([_con_estilo(ws, columna.titulo, negrita=True) for columna in resultado.columnas])

    for fila in resultado.filas:
        ws.append(
            [
                _con_estilo(ws, _celda(valor, columna.tipo), formato=_FORMATO.get(columna.tipo))
                for valor, columna in zip(fila, resultado.columnas)
            ]
        )


def _escribir_parametros(wb: Workbook, resultado: ResultadoInforme, ctx: ContextoInforme) -> None:
    ws = wb.create_sheet("Parámetros")
    ws.append(["Informe", f"{ctx.clave} · {ctx.nombre}"])
    ws.append(["Generado por", ctx.usuario])
    ws.append(["Generado el", ctx.generado_en])
    ws.append(["Versión del ETL", ctx.etl_version])
    ws.append(["Filas", len(resultado.filas)])
    if resultado.aviso:
        ws.append(["Aviso", resultado.aviso])
    ws.append([])
    ws.append(["Parámetro", "Valor"])
    for clave, valor in ctx.parametros.items():
        ws.append([clave, "" if valor is None else str(valor)])


def _escribir_banderas(wb: Workbook, banderas: list[Bandera]) -> None:
    ws = wb.create_sheet("Banderas")
    ws.append(["Bandera", "Severidad", "Ámbito", "Mensaje"])
    for bandera in banderas:
        ws.append([bandera.clave, bandera.severidad, bandera.ambito, bandera.mensaje])


def _escribir_diccionario(wb: Workbook, entradas: list[EntradaDiccionario]) -> None:
    ws = wb.create_sheet("Diccionario")
    ws.append(
        [
            "Etiqueta",
            "Naturaleza",
            "Tipo SAT",
            "Descripción SAT",
            "Clave del patrón",
            "Concepto canónico",
            "Descripciones alternas",
            "Núm. comprobantes",
            "Importe del periodo",
        ]
    )
    for entrada in entradas:
        ws.append(
            [
                entrada.etiqueta,
                entrada.naturaleza,
                entrada.tipo,
                entrada.descripcion_sat,
                entrada.clave_patron,
                entrada.concepto_canonico,
                "; ".join(entrada.descripciones_alternas),
                entrada.num_comprobantes,
                _celda(entrada.importe_total, "monto"),
            ]
        )


def escribir_libro(resultado: ResultadoInforme, ctx: ContextoInforme) -> bytes:
    """Devuelve los bytes del `.xlsx`. Las cuatro hojas existen siempre, aunque estén
    vacías: un consumidor automático no debería tener que comprobar si la hoja está."""
    wb = Workbook(write_only=True)
    _escribir_datos(wb, resultado)
    _escribir_parametros(wb, resultado, ctx)
    _escribir_banderas(wb, resultado.banderas)
    _escribir_diccionario(wb, resultado.diccionario)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
```

**Trampa de `openpyxl` que este código evita:** en modo `write_only` no existe `ws.cell(...)`
ni se puede aplicar formato después de escribir la fila. Todo el estilo va en la celda antes
del `append`, que es lo que hace `_con_estilo`. Si `load_workbook` en las pruebas devuelve
`None` en `ws.freeze_panes`, fijarlo **antes** del primer `append` (como está aquí).

- [ ] **Step 5: Write the registry**

```python
# app/informes/registro.py
"""Registro de informes disponibles (spec §7.1).

Agregar un informe = importar su módulo y añadirlo a `_MODULOS`. El endpoint del catálogo
y el de generación no cambian.
"""

from __future__ import annotations

from typing import Any

from app.informes import b02_conceptos_patron
from app.informes.base import DefinicionInforme

_MODULOS: tuple[Any, ...] = (b02_conceptos_patron,)

REGISTRO: dict[str, DefinicionInforme] = {modulo.CLAVE: modulo for modulo in _MODULOS}


class InformeDesconocidoError(KeyError):
    """Clave que no está en el registro."""


def obtener(clave: str) -> DefinicionInforme:
    try:
        return REGISTRO[clave]
    except KeyError as exc:
        raise InformeDesconocidoError(clave) from exc


def catalogo() -> list[dict[str, Any]]:
    """Catálogo para el frontend: incluye el JSON Schema de los parámetros, con lo que la
    pantalla genera su formulario sola (spec §7.2)."""
    return [
        {
            "clave": definicion.CLAVE,
            "nombre": definicion.NOMBRE,
            "grupo": definicion.GRUPO,
            "descripcion": definicion.DESCRIPCION,
            "parametros": definicion.Parametros.model_json_schema(),
        }
        for definicion in sorted(REGISTRO.values(), key=lambda d: d.CLAVE)
    ]
```

**Nota:** `registro.py` importa `b02_conceptos_patron`, que se crea en la tarea 11. Escribir
`registro.py` en esta tarea con `_MODULOS: tuple[Any, ...] = ()` y añadir el import en la
tarea 11; así esta tarea queda verde por sí sola.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_informes_excel.py -q`
Expected: PASS (6 tests)

- [ ] **Step 7: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/informes/ tests/test_informes_excel.py
git commit -m "feat(informes): agregar motor de informes y libro de Excel de cuatro hojas"
```

---

### Task 11: B-02 — consulta

**Files:**
- Create: `app/informes/b02_conceptos_patron.py`
- Modify: `app/informes/registro.py` (agregar el módulo a `_MODULOS`)
- Test: `tests/test_informe_b02.py`

**Interfaces:**
- Consumes: los tipos de `app/informes/base.py`, los modelos de nómina, `app/informes/excel.enmascarar`.
- Produces:
  - `CLAVE = "B-02"`, `NOMBRE`, `GRUPO = "B"`, `DESCRIPCION`
  - `class Parametros(BaseModel)`: `fecha_desde: date`, `fecha_hasta: date`, `tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"`, `incluir_cancelados: bool = False`, `desglosar_gravado_exento: bool = False`, `enmascarar_datos_personales: bool = True`
  - `async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme`
  - `def etiqueta(naturaleza: str, tipo: str, clave: str | None, concepto: str | None) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_informe_b02.py
"""B-02 · Nómina agrupada por conceptos del patrón.

Las cuatro reglas que este informe tiene que respetar y que las herramientas comerciales
fallan (según el §B-02 del documento fuente):

- B-02.R1: dos nodos con el mismo (tipo, clave) en un CFDI se SUMAN, no se sobrescriben.
- B-02.R3: la etiqueta lleva prefijo de naturaleza; 'Ajuste al neto' existe como D/004/099
  y como O/999/099 en los datos reales de la empresa 11 y no debe colapsar en una columna.
- B-02.R4 / R-T7: celda sin dato = 0, no vacío.
- B-02.R5: el orden de columnas es determinista entre corridas.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b02_conceptos_patron as b02
from app.models.enums import EstatusCfdi
from app.models.nomina import Nomina, NominaDeduccion, NominaOtroPago, NominaPercepcion, NominaReceptor, NominaTotales
from tests import factories


async def _nomina(
    db: AsyncSession,
    *,
    empresa_id: int,
    uuid: str,
    num_empleado: str = "039",
    rfc_receptor: str = "XAXX010101000",
    fecha_pago: date = date(2026, 6, 30),
    percepciones: list[tuple[str, str, str, str, str]] | None = None,
    deducciones: list[tuple[str, str, str, str]] | None = None,
    otros_pagos: list[tuple[str, str, str, str]] | None = None,
    total_percepciones: str = "8759.70",
    total_deducciones: str = "591.10",
    total_otros_pagos: str = "0.00",
    total: str = "8168.60",
    estatus: EstatusCfdi = EstatusCfdi.VIGENTE,
    dias: str = "15.000",
) -> int:
    """Inserta un CFDI de nómina normalizado. Las tuplas son
    (tipo, clave, concepto, gravado, exento) para percepciones y (tipo, clave, concepto,
    importe) para deducciones y otros pagos."""
    comprobante = await factories.crear_comprobante(
        db,
        empresa_id=empresa_id,
        uuid=uuid,
        rfc_emisor="CHL960913IX9",
        rfc_receptor=rfc_receptor,
        tipo_comprobante="N",
        estatus=estatus,
        total=Decimal(total),
        fecha_emision=None,
    )
    cid = comprobante.comprobante_id
    db.add(
        Nomina(
            comprobante_id=cid,
            version_nomina="1.2",
            tipo_nomina="O",
            fecha_pago=fecha_pago,
            fecha_inicial_pago=date(fecha_pago.year, fecha_pago.month, 16),
            fecha_final_pago=fecha_pago,
            num_dias_pagados=Decimal(dias),
            total_percepciones=Decimal(total_percepciones),
            total_deducciones=Decimal(total_deducciones),
            total_otros_pagos=Decimal(total_otros_pagos),
            registro_patronal="B5510768108",
        )
    )
    db.add(
        NominaReceptor(
            comprobante_id=cid,
            curp="XXXX800101HCHXXX01",
            nss="12345678901",
            num_empleado=num_empleado,
            departamento="Direccion",
            puesto="Director",
            periodicidad_pago="04",
            tipo_regimen="02",
            salario_base_cot_apor=Decimal("583.98"),
            salario_diario_integrado=Decimal("607.34"),
        )
    )
    db.add(NominaTotales(comprobante_id=cid, total_gravado=Decimal(total_percepciones), total_exento=Decimal("0")))
    for tipo, clave, concepto, gravado, exento in percepciones or [("001", "001", "Sueldo", total_percepciones, "0.00")]:
        db.add(
            NominaPercepcion(
                comprobante_id=cid,
                tipo_percepcion=tipo,
                clave=clave,
                concepto=concepto,
                importe_gravado=Decimal(gravado),
                importe_exento=Decimal(exento),
            )
        )
    for tipo, clave, concepto, importe in deducciones or [("002", "045", "I.S.R. mes", total_deducciones)]:
        db.add(NominaDeduccion(comprobante_id=cid, tipo_deduccion=tipo, clave=clave, concepto=concepto, importe=Decimal(importe)))
    for tipo, clave, concepto, importe in otros_pagos or []:
        db.add(NominaOtroPago(comprobante_id=cid, tipo_otro_pago=tipo, clave=clave, concepto=concepto, importe=Decimal(importe)))
    await db.commit()
    return cid


def _columna(resultado, titulo: str) -> int:  # type: ignore[no-untyped-def]
    titulos = [c.titulo for c in resultado.columnas]
    assert titulo in titulos, f"falta la columna {titulo!r}; hay {titulos}"
    return titulos.index(titulo)


async def test_una_fila_por_comprobante_con_columnas_dinamicas(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111")

    p = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31))
    resultado = await b02.consultar(db, empresa.empresa_id, p)

    assert len(resultado.filas) == 1
    indice = _columna(resultado, f"P{b02.SEPARADOR_ETIQUETA}001{b02.SEPARADOR_ETIQUETA}001{b02.SEPARADOR_ETIQUETA}Sueldo")
    assert resultado.filas[0][indice] == Decimal("8759.70")


async def test_concepto_repetido_se_suma(db: AsyncSession) -> None:
    """B-02.R1. Sobrescribir en vez de sumar subvalúa la nómina en silencio."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="22222222-2222-2222-2222-222222222222",
        percepciones=[("019", "019", "Horas extra", "300.00", "0.00"), ("019", "019", "Horas extra", "450.00", "0.00")],
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    indice = _columna(resultado, f"P{b02.SEPARADOR_ETIQUETA}019{b02.SEPARADOR_ETIQUETA}019{b02.SEPARADOR_ETIQUETA}Horas extra")
    assert resultado.filas[0][indice] == Decimal("750.00")


async def test_colision_de_clave_entre_naturalezas_no_colapsa(db: AsyncSession) -> None:
    """B-02.R3, con el caso real de la empresa 11: 'Ajuste al neto' es D/004/099 y O/999/099."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="33333333-3333-3333-3333-333333333333",
        deducciones=[("004", "099", "Ajuste al neto", "0.04")],
        otros_pagos=[("999", "099", "Ajuste al neto", "0.05")],
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    sep = b02.SEPARADOR_ETIQUETA
    indice_deduccion = _columna(resultado, f"D{sep}004{sep}099{sep}Ajuste al neto")
    indice_otro = _columna(resultado, f"O{sep}999{sep}099{sep}Ajuste al neto")
    assert indice_deduccion != indice_otro
    assert resultado.filas[0][indice_deduccion] == Decimal("0.04")
    assert resultado.filas[0][indice_otro] == Decimal("0.05")


async def test_celda_sin_dato_es_cero_no_vacio(db: AsyncSession) -> None:
    """R-T7: un nulo en columna de importe es indistinguible de 'no aplica' y rompe
    cualquier suma en hoja de cálculo."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="44444444-4444-4444-4444-444444444444",
        rfc_receptor="XEXX010101000",
        percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
    )
    await _nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="55555555-5555-5555-5555-555555555555",
        rfc_receptor="XAXX010101000",
        percepciones=[("002", "002", "Aguinaldo", "5000.00", "0.00")],
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    sep = b02.SEPARADOR_ETIQUETA
    indice_aguinaldo = _columna(resultado, f"P{sep}002{sep}002{sep}Aguinaldo")
    valores = {fila[_columna(resultado, "UUID")]: fila[indice_aguinaldo] for fila in resultado.filas}
    assert valores["44444444-4444-4444-4444-444444444444"] == Decimal("0")
    assert valores["55555555-5555-5555-5555-555555555555"] == Decimal("5000.00")


async def test_orden_de_columnas_es_determinista(db: AsyncSession) -> None:
    """B-02.R5: percepciones, luego otros pagos, luego deducciones; dentro de cada
    naturaleza por tipo y clave como texto."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="66666666-6666-6666-6666-666666666666",
        percepciones=[("005", "031", "Fondo ahorro empresa", "0.00", "500.00"), ("001", "001", "Sueldo", "8000.00", "0.00")],
        deducciones=[("002", "045", "I.S.R. mes", "391.10"), ("001", "052", "I.M.S.S.", "200.00")],
        otros_pagos=[("002", "035", "Subs al Empleo mes", "0.00")],
    )

    p = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31))
    primera = await b02.consultar(db, empresa.empresa_id, p)
    segunda = await b02.consultar(db, empresa.empresa_id, p)
    assert [c.titulo for c in primera.columnas] == [c.titulo for c in segunda.columnas]

    dinamicas = [c.titulo for c in primera.columnas if b02.SEPARADOR_ETIQUETA in c.titulo]
    assert [t[0] for t in dinamicas] == ["P", "P", "O", "D", "D"]
    assert dinamicas[0].startswith("P") and "001" in dinamicas[0]
    assert dinamicas[1].startswith("P") and "005" in dinamicas[1]


async def test_concepto_inconsistente_usa_la_descripcion_mas_frecuente(db: AsyncSession) -> None:
    """R-T9: se agrupa por (tipo, clave) y se reporta la descripción más frecuente, con
    bandera. Agrupar por descripción produciría columnas duplicadas del mismo concepto."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    for indice, concepto in enumerate(("Sueldo", "Sueldo", "Sueldos")):
        await _nomina(
            db,
            empresa_id=empresa.empresa_id,
            uuid=f"7777777{indice}-7777-7777-7777-777777777777",
            rfc_receptor=f"XAXX01010100{indice}",
            percepciones=[("001", "001", concepto, "8000.00", "0.00")],
        )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))

    sep = b02.SEPARADOR_ETIQUETA
    dinamicas = [c.titulo for c in resultado.columnas if sep in c.titulo]
    assert dinamicas == [f"P{sep}001{sep}001{sep}Sueldo"]
    assert any(b.clave == "CONCEPTO_INCONSISTENTE" for b in resultado.banderas)
    entrada = next(e for e in resultado.diccionario if e.etiqueta == dinamicas[0])
    assert entrada.concepto_canonico == "Sueldo"
    assert entrada.descripciones_alternas == ["Sueldos"]


async def test_cancelados_se_excluyen_por_defecto(db: AsyncSession) -> None:
    """R-T1."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(db, empresa_id=empresa.empresa_id, uuid="88888888-8888-8888-8888-888888888888", estatus=EstatusCfdi.CANCELADO)

    p = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31))
    assert (await b02.consultar(db, empresa.empresa_id, p)).filas == []

    p_con = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31), incluir_cancelados=True)
    assert len((await b02.consultar(db, empresa.empresa_id, p_con)).filas) == 1


async def test_enmascara_datos_personales_por_defecto(db: AsyncSession) -> None:
    """spec §8: el default protege CURP y NSS incluso en los informes que el documento
    fuente no marca como sensibles."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(db, empresa_id=empresa.empresa_id, uuid="99999999-9999-9999-9999-999999999999")

    p = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31))
    resultado = await b02.consultar(db, empresa.empresa_id, p)
    assert resultado.filas[0][_columna(resultado, "CURP")] == "****XX01"
    assert resultado.filas[0][_columna(resultado, "NSS")] == "****8901"

    p_claro = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31), enmascarar_datos_personales=False)
    resultado = await b02.consultar(db, empresa.empresa_id, p_claro)
    assert resultado.filas[0][_columna(resultado, "CURP")] == "XXXX800101HCHXXX01"


async def test_banderas_de_descuadre_y_neto(db: AsyncSession) -> None:
    """Identidades de B-00 fuera de tolerancia y `NETO_NEGATIVO`."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        total_percepciones="8759.70",  # no coincide con la suma de percepciones
        total="-10.00",
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    claves = {b.clave for b in resultado.banderas}
    assert "TOTALES_DESCUADRADOS" in claves
    assert "NETO_NEGATIVO" in claves


async def test_dias_pagados_atipico_para_quincenal(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(db, empresa_id=empresa.empresa_id, uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", dias="20.000")

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    assert any(b.clave == "DIAS_PAGADOS_ATIPICO" for b in resultado.banderas)


async def test_sin_comprobantes_devuelve_aviso(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31)))
    assert resultado.filas == []
    assert resultado.aviso is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_informe_b02.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.informes.b02_conceptos_patron'`

- [ ] **Step 3: Implement the report query**

```python
# app/informes/b02_conceptos_patron.py
"""B-02 · Nómina agrupada por conceptos del patrón (§B-02 del documento fuente).

Es el informe que producen OneFacture, ezaudita, MiAdminXML y Audita CFDI, y el peor
especificado de todos. Reproduce la nómina como la concibe el patrón —con sus claves y
descripciones internas— para cotejar el CFDI timbrado contra el recibo del sistema de
nómina, concepto por concepto.

Grano: una fila por comprobante. Cada concepto distinto del patrón es una columna generada
en tiempo de ejecución.

Las cuatro trampas que este módulo evita a propósito:

1. **Sumar, no sobrescribir** (B-02.R1). El esquema Nómina 1.2 permite varios nodos con el
   mismo `(tipo, clave)` en un CFDI. El valor de la celda es `SUM(...)`.
2. **Prefijo de naturaleza en la etiqueta** (B-02.R3). `tipo_percepcion='002'` (aguinaldo)
   y `tipo_deduccion='002'` (ISR) comparten el texto `002`.
3. **Identidad por `(tipo, clave)`, nunca por descripción** (R-T9). El `@Concepto` es texto
   libre del patrón y varía entre periodos por errores de captura.
4. **Cero, no vacío** (R-T7).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes.base import Bandera, Columna, EntradaDiccionario, ResultadoInforme, SEPARADOR_ETIQUETA
from app.informes.excel import enmascarar
from app.models.comprobante import Comprobante
from app.models.enums import EstatusCfdi
from app.models.nomina import Nomina, NominaDeduccion, NominaOtroPago, NominaPercepcion, NominaReceptor, NominaTotales

CLAVE = "B-02"
NOMBRE = "Nómina agrupada por conceptos del patrón"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por CFDI de nómina, con una columna por cada concepto del patrón. "
    "Sirve para cotejar el CFDI timbrado contra el recibo del sistema de nómina, concepto por concepto."
)

_CERO = Decimal("0")
_TOLERANCIA = Decimal("0.01")

# Orden de naturalezas del informe: replica el orden de lectura de un recibo de nómina
# (B-02, fase 3 del algoritmo): percepciones, otros pagos, deducciones.
_ORDEN_NATURALEZA = {"P": 0, "O": 1, "D": 2}

# Días nominales por periodicidad, para la bandera DIAS_PAGADOS_ATIPICO (B-02).
_RANGO_DIAS = {
    "01": (Decimal("1"), Decimal("1")),  # diario
    "02": (Decimal("1"), Decimal("7")),  # semanal
    "03": (Decimal("1"), Decimal("14")),  # catorcenal
    "04": (Decimal("1"), Decimal("16")),  # quincenal
    "05": (Decimal("1"), Decimal("31")),  # mensual
    "06": (Decimal("1"), Decimal("10")),  # decenal
}


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango, sobre `nomina.fecha_pago` (R-T6).")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    tipo_nomina: Literal["O", "E", "AMBOS"] = Field("AMBOS", description="Ordinaria, extraordinaria o ambas.")
    incluir_cancelados: bool = Field(False, description="Por defecto solo vigentes (R-T1).")
    desglosar_gravado_exento: bool = Field(False, description="Emite dos columnas por percepción: (G) y (E).")
    enmascarar_datos_personales: bool = Field(True, description="Enmascara CURP, NSS y cuenta bancaria (spec §8).")


def etiqueta(naturaleza: str, tipo: str, clave: str | None, concepto: str | None) -> str:
    """`naturaleza ¦ tipo ¦ clave ¦ concepto` (R-T8 más el prefijo de B-02.R3)."""
    partes = [naturaleza, tipo, clave or "", concepto or ""]
    return SEPARADOR_ETIQUETA.join(partes)


# Columnas fijas: identificación, nómina, patrón y empleado (bloques de B-01).
_COLUMNAS_FIJAS: tuple[tuple[str, str], ...] = (
    ("Ejercicio", "entero"),
    ("Periodo", "entero"),
    ("UUID", "texto"),
    ("Serie", "texto"),
    ("Folio", "texto"),
    ("Estado SAT", "texto"),
    ("Tipo nómina", "texto"),
    ("Fecha pago", "fecha"),
    ("Fecha inicial", "fecha"),
    ("Fecha final", "fecha"),
    ("Días pagados", "decimal"),
    ("Periodicidad", "texto"),
    ("RFC patrón", "texto"),
    ("Registro patronal", "texto"),
    ("RFC empleado", "texto"),
    ("Nombre empleado", "texto"),
    ("CURP", "texto"),
    ("NSS", "texto"),
    ("Núm. empleado", "texto"),
    ("Departamento", "texto"),
    ("Puesto", "texto"),
    ("Tipo régimen", "texto"),
    ("SBC", "monto"),
    ("SDI", "monto"),
)

_COLUMNAS_TOTALES: tuple[tuple[str, str], ...] = (
    ("Total sueldos", "monto"),
    ("Total separación indemnización", "monto"),
    ("Total jubilación pensión retiro", "monto"),
    ("Total percepciones", "monto"),
    ("Total gravado", "monto"),
    ("Total exento", "monto"),
    ("Total otros pagos", "monto"),
    ("Total deducciones", "monto"),
    ("Total (neto)", "monto"),
)


def _universo(empresa_id: int, p: Parametros) -> Select[Any]:
    """Fase 1 del algoritmo: qué comprobantes entran."""
    consulta = (
        select(Comprobante, Nomina, NominaReceptor, NominaTotales)
        .join(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
        .outerjoin(NominaReceptor, NominaReceptor.comprobante_id == Comprobante.comprobante_id)
        .outerjoin(NominaTotales, NominaTotales.comprobante_id == Comprobante.comprobante_id)
        .where(
            Comprobante.empresa_id == empresa_id,
            Comprobante.tipo_comprobante == "N",
            Nomina.fecha_pago >= p.fecha_desde,
            Nomina.fecha_pago <= p.fecha_hasta,
        )
        .order_by(Nomina.fecha_pago, Comprobante.comprobante_id)
    )
    if not p.incluir_cancelados:
        consulta = consulta.where(Comprobante.estatus != EstatusCfdi.CANCELADO)
    if p.tipo_nomina != "AMBOS":
        consulta = consulta.where(Nomina.tipo_nomina == p.tipo_nomina)
    return consulta


async def _conceptos_por_comprobante(
    db: AsyncSession, ids: list[int]
) -> tuple[dict[tuple[int, tuple[str, str, str]], Decimal], dict[tuple[str, str, str], Counter[str]]]:
    """Suma por `(comprobante_id, (naturaleza, tipo, clave))` y frecuencias de descripción
    por concepto. La suma la hace la BD (`SUM`), que es lo que implementa B-02.R1."""
    importes: dict[tuple[int, tuple[str, str, str]], Decimal] = defaultdict(lambda: _CERO)
    descripciones: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    if not ids:
        return importes, descripciones

    fuentes = (
        ("P", NominaPercepcion, NominaPercepcion.tipo_percepcion, NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento),
        ("O", NominaOtroPago, NominaOtroPago.tipo_otro_pago, NominaOtroPago.importe),
        ("D", NominaDeduccion, NominaDeduccion.tipo_deduccion, NominaDeduccion.importe),
    )
    for naturaleza, modelo, columna_tipo, expresion_importe in fuentes:
        filas = await db.execute(
            select(
                modelo.comprobante_id,
                columna_tipo.label("tipo"),
                func.coalesce(modelo.clave, "").label("clave"),
                func.coalesce(modelo.concepto, "").label("concepto"),
                func.sum(expresion_importe).label("importe"),
            )
            .where(modelo.comprobante_id.in_(ids))
            .group_by(modelo.comprobante_id, columna_tipo, modelo.clave, modelo.concepto)
        )
        for fila in filas:
            concepto_id = (naturaleza, str(fila.tipo), str(fila.clave))
            importe = fila.importe if isinstance(fila.importe, Decimal) else Decimal(str(fila.importe))
            # Se agrupa por (tipo, clave); la descripción NO forma parte de la identidad
            # (R-T9), así que dos descripciones del mismo concepto se acumulan aquí.
            importes[(int(fila.comprobante_id), concepto_id)] += importe
            if fila.concepto:
                descripciones[concepto_id][str(fila.concepto)] += 1
    return importes, descripciones


def _banderas_del_comprobante(
    comprobante: Comprobante,
    nomina: Nomina,
    receptor: NominaReceptor | None,
    totales: NominaTotales | None,
    suma_percepciones: Decimal,
    suma_deducciones: Decimal,
    suma_otros: Decimal,
) -> list[Bandera]:
    """Identidades de B-00 y las validaciones de la ficha B-02.

    No valida `total_impuestos_retenidos` contra el ISR retenido: esa identidad pertenece a
    B-01, que agrupa por tipo del catálogo. Aquí bastan los tres totales del complemento.
    """
    banderas: list[Bandera] = []
    ambito = f"uuid:{comprobante.uuid}"

    identidades = (
        ("total_percepciones", nomina.total_percepciones, suma_percepciones),
        ("total_deducciones", nomina.total_deducciones, suma_deducciones),
        ("total_otros_pagos", nomina.total_otros_pagos, suma_otros),
    )
    for nombre, declarado, calculado in identidades:
        if declarado is not None and abs(declarado - calculado) > _TOLERANCIA:
            banderas.append(
                Bandera(
                    clave="TOTALES_DESCUADRADOS",
                    severidad="alta",
                    ambito=ambito,
                    mensaje=f"{nombre} declarado {declarado} ≠ suma de nodos {calculado}.",
                )
            )
    if comprobante.total is not None and comprobante.total < 0:
        banderas.append(Bandera(clave="NETO_NEGATIVO", severidad="alta", ambito=ambito, mensaje=f"El total del CFDI es {comprobante.total}."))

    if suma_deducciones > suma_percepciones + suma_otros + _TOLERANCIA:
        banderas.append(
            Bandera(
                clave="DEDUCCION_MAYOR_PERCEPCION",
                severidad="alta",
                ambito=ambito,
                mensaje=f"Deducciones {suma_deducciones} > percepciones + otros pagos {suma_percepciones + suma_otros}.",
            )
        )

    periodicidad = receptor.periodicidad_pago if receptor else None
    dias = nomina.num_dias_pagados
    if periodicidad in _RANGO_DIAS and dias is not None:
        minimo, maximo = _RANGO_DIAS[periodicidad]
        if not (minimo <= dias <= maximo):
            banderas.append(
                Bandera(
                    clave="DIAS_PAGADOS_ATIPICO",
                    severidad="media",
                    ambito=ambito,
                    mensaje=f"{dias} días para periodicidad {periodicidad} (esperado {minimo}–{maximo}).",
                )
            )
    return banderas


def _banderas_de_periodos_traslapados(filas_crudas: list[tuple[Comprobante, Nomina]]) -> list[Bandera]:
    """`PERIODO_TRASLAPADO`: dos nóminas ordinarias del mismo empleado con rangos que se
    intersectan. Casi siempre es un timbrado doble."""
    banderas: list[Bandera] = []
    por_empleado: dict[str, list[tuple[Comprobante, Nomina]]] = defaultdict(list)
    for comprobante, nomina in filas_crudas:
        if nomina.tipo_nomina == "O":
            por_empleado[comprobante.rfc_receptor].append((comprobante, nomina))

    for rfc, registros in por_empleado.items():
        ordenados = sorted(registros, key=lambda par: par[1].fecha_inicial_pago or date.min)
        for anterior, siguiente in zip(ordenados, ordenados[1:]):
            fin_anterior = anterior[1].fecha_final_pago
            inicio_siguiente = siguiente[1].fecha_inicial_pago
            if fin_anterior and inicio_siguiente and inicio_siguiente <= fin_anterior:
                banderas.append(
                    Bandera(
                        clave="PERIODO_TRASLAPADO",
                        severidad="alta",
                        ambito=f"rfc:{rfc}",
                        mensaje=f"{anterior[0].uuid} termina el {fin_anterior} y {siguiente[0].uuid} inicia el {inicio_siguiente}.",
                    )
                )
    return banderas


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    filas_universo = list((await db.execute(_universo(empresa_id, p))).all())
    if not filas_universo:
        columnas = [Columna(titulo=titulo, tipo=tipo) for titulo, tipo in _COLUMNAS_FIJAS + _COLUMNAS_TOTALES]  # type: ignore[arg-type]
        return ResultadoInforme(columnas=columnas, aviso="Sin CFDI de nómina en el rango solicitado.")

    ids = [fila[0].comprobante_id for fila in filas_universo]
    importes, descripciones = await _conceptos_por_comprobante(db, ids)

    # Fase 2 y 3: conjunto de columnas dinámicas, con orden determinista (B-02.R5).
    conceptos = sorted(
        {concepto for _, concepto in importes},
        key=lambda c: (_ORDEN_NATURALEZA.get(c[0], 9), c[1], c[2]),
    )

    banderas: list[Bandera] = []
    diccionario: list[EntradaDiccionario] = []
    etiquetas: dict[tuple[str, str, str], str] = {}
    for concepto in conceptos:
        naturaleza, tipo, clave = concepto
        frecuencias = descripciones.get(concepto, Counter())
        canonico = frecuencias.most_common(1)[0][0] if frecuencias else None
        alternas = sorted(d for d in frecuencias if d != canonico)
        etiquetas[concepto] = etiqueta(naturaleza, tipo, clave, canonico)

        if len(frecuencias) > 1:
            banderas.append(
                Bandera(
                    clave="CONCEPTO_INCONSISTENTE",
                    severidad="baja",
                    ambito=f"concepto:{naturaleza}/{tipo}/{clave}",
                    mensaje=f"Descripciones distintas para el mismo concepto: {canonico!r} y {alternas}.",
                )
            )
        if not clave:
            banderas.append(
                Bandera(
                    clave="CLAVE_VACIA",
                    severidad="media",
                    ambito=f"concepto:{naturaleza}/{tipo}",
                    mensaje="El concepto no trae clave del patrón; no se puede identificar de forma estable.",
                )
            )

        comprobantes_con_concepto = sum(1 for (_, c) in importes if c == concepto)
        diccionario.append(
            EntradaDiccionario(
                etiqueta=etiquetas[concepto],
                naturaleza=naturaleza,
                tipo=tipo,
                descripcion_sat=None,  # se resuelve en la tarea 12 con el catálogo de satcfdi
                clave_patron=clave or None,
                concepto_canonico=canonico,
                descripciones_alternas=alternas,
                num_comprobantes=comprobantes_con_concepto,
                importe_total=sum((v for (_, c), v in importes.items() if c == concepto), _CERO),
            )
        )

    columnas = [Columna(titulo=titulo, tipo=tipo) for titulo, tipo in _COLUMNAS_FIJAS]  # type: ignore[arg-type]
    columnas += [Columna(titulo=etiquetas[c], tipo="monto") for c in conceptos]
    columnas += [Columna(titulo=titulo, tipo=tipo) for titulo, tipo in _COLUMNAS_TOTALES]  # type: ignore[arg-type]

    filas: list[list[Any]] = []
    for comprobante, nomina, receptor, totales in filas_universo:
        cid = comprobante.comprobante_id
        suma = {
            naturaleza: sum((v for (c_id, (nat, _, _)), v in importes.items() if c_id == cid and nat == naturaleza), _CERO)
            for naturaleza in ("P", "O", "D")
        }
        banderas.extend(_banderas_del_comprobante(comprobante, nomina, receptor, totales, suma["P"], suma["D"], suma["O"]))

        curp = receptor.curp if receptor else None
        nss = receptor.nss if receptor else None
        if p.enmascarar_datos_personales:
            curp, nss = enmascarar(curp), enmascarar(nss)

        fija: list[Any] = [
            nomina.fecha_pago.year if nomina.fecha_pago else None,
            nomina.fecha_pago.month if nomina.fecha_pago else None,
            comprobante.uuid,
            None,  # Serie: vive en comprobante_detalle; se llena en la tarea 12
            comprobante.folio,
            comprobante.estatus.value,
            nomina.tipo_nomina,
            nomina.fecha_pago,
            nomina.fecha_inicial_pago,
            nomina.fecha_final_pago,
            nomina.num_dias_pagados,
            receptor.periodicidad_pago if receptor else None,
            comprobante.rfc_emisor,
            nomina.registro_patronal,
            comprobante.rfc_receptor,
            comprobante.razon_social_emisor,
            curp,
            nss,
            receptor.num_empleado if receptor else None,
            receptor.departamento if receptor else None,
            receptor.puesto if receptor else None,
            receptor.tipo_regimen if receptor else None,
            receptor.salario_base_cot_apor if receptor else None,
            receptor.salario_diario_integrado if receptor else None,
        ]
        # R-T7: cero, no vacío.
        dinamicas: list[Any] = [importes.get((cid, concepto), _CERO) for concepto in conceptos]
        totales_fila: list[Any] = [
            totales.total_sueldos if totales else None,
            totales.total_separacion_indemnizacion if totales else None,
            totales.total_jubilacion_pension_retiro if totales else None,
            nomina.total_percepciones,
            totales.total_gravado if totales else None,
            totales.total_exento if totales else None,
            nomina.total_otros_pagos,
            nomina.total_deducciones,
            comprobante.total,
        ]
        filas.append(fija + dinamicas + totales_fila)

    banderas.extend(_banderas_de_periodos_traslapados([(fila[0], fila[1]) for fila in filas_universo]))

    return ResultadoInforme(columnas=columnas, filas=filas, banderas=banderas, diccionario=diccionario)
```

- [ ] **Step 4: Register the report**

En `app/informes/registro.py`, cambiar `_MODULOS`:

```python
from app.informes import b02_conceptos_patron

_MODULOS: tuple[Any, ...] = (b02_conceptos_patron,)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_informe_b02.py -q`
Expected: PASS (11 tests)

Si `test_orden_de_columnas_es_determinista` falla, revisar que `_ORDEN_NATURALEZA` ponga
`O` antes de `D` y que el `sorted` compare `tipo` y `clave` **como texto**.

**Nota de alcance:** la ficha B-02 del documento fuente lista también la bandera
`PERIODO_FALTANTE` ("hueco en la secuencia de periodos esperada según `periodicidad_pago`"),
que remite a B-04.R2. **No se implementa aquí:** requiere construir el eje teórico de periodos,
que es el trabajo propio de B-04 (fase 2). Cuando B-04 exista, B-02 reusará ese eje. Las otras
siete banderas de la ficha sí quedan cubiertas.

- [ ] **Step 6: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/informes/b02_conceptos_patron.py app/informes/registro.py tests/test_informe_b02.py
git commit -m "feat(informes): agregar consulta del informe B-02 (conceptos del patron)"
```

---

### Task 12: B-02 — descripciones del catálogo SAT y serie del comprobante

**Files:**
- Create: `app/informes/catalogos.py`
- Modify: `app/informes/b02_conceptos_patron.py`
- Test: `tests/test_informes_catalogos.py`
- Modify: `tests/test_informe_b02.py` (dos aserciones nuevas)

**Interfaces:**
- Consumes: `satcfdi`, `ComprobanteDetalle`.
- Produces:
  - `def descripcion(naturaleza: str, tipo: str) -> str | None` en `app/informes/catalogos.py`
  - `def descripcion_percepcion(tipo: str) -> str | None`, `descripcion_deduccion`, `descripcion_otro_pago`
  - Cambio en B-02: `EntradaDiccionario.descripcion_sat` se llena y la columna `Serie` sale de `comprobante_detalle`.

La tarea 11 dejó dos huecos a propósito: `descripcion_sat=None` en el diccionario y `None` en la columna `Serie`. Esta tarea los cierra.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_informes_catalogos.py
"""Descripciones de los catálogos del SAT (§3 del documento fuente).

`satcfdi` ya trae los catálogos: no se cargan tablas. Lo que sí hace falta es resolver
`tipo → descripción` para la hoja Diccionario, y que un tipo desconocido devuelva `None`
en vez de romper el informe.
"""

from __future__ import annotations

from app.informes import catalogos


def test_descripcion_de_percepcion_deduccion_y_otro_pago() -> None:
    assert catalogos.descripcion_percepcion("001") == "Sueldos, Salarios Rayas y Jornales"
    assert catalogos.descripcion_deduccion("002") is not None
    assert "ISR" in (catalogos.descripcion_deduccion("002") or "")
    assert catalogos.descripcion_otro_pago("002") is not None


def test_tipo_desconocido_no_rompe() -> None:
    """El SAT agrega claves; un catálogo desactualizado no debe abortar un informe."""
    assert catalogos.descripcion_percepcion("999") is None
    assert catalogos.descripcion_deduccion("ZZZ") is None


def test_despacho_por_naturaleza() -> None:
    assert catalogos.descripcion("P", "001") == "Sueldos, Salarios Rayas y Jornales"
    assert catalogos.descripcion("D", "002") == catalogos.descripcion_deduccion("002")
    assert catalogos.descripcion("O", "002") == catalogos.descripcion_otro_pago("002")
    assert catalogos.descripcion("X", "001") is None
```

- [ ] **Step 2: Discover the catalog API of satcfdi**

`satcfdi` expone los catálogos como enumeraciones/diccionarios en `satcfdi.catalogs`. Antes
de escribir el módulo, averiguar el nombre exacto y la forma:

```bash
.venv/bin/python -c "
import satcfdi.catalogs as cat
print([n for n in dir(cat) if 'ercepcion' in n or 'educcion' in n or 'troPago' in n])
"
```

Si los catálogos no están expuestos ahí, obtener la descripción desde el propio `Code` que
`satcfdi` produce al parsear (que ya vimos que trae `.description`), construyendo el `Code`
a mano. La sonda de exploración confirmó que `Code('001', 'Sueldos, Salarios Rayas y Jornales')`
sale del parseo, así que como último recurso:

```bash
.venv/bin/python -c "
from satcfdi.cfdi import CFDI
import sys; sys.path.insert(0, 'tests')
import fixtures_cfdi
c = CFDI.from_string(fixtures_cfdi.cfdi_nomina())
p = c['Complemento']['Nomina']['Percepciones']['Percepcion'][0]
tipo = p['TipoPercepcion']
print(type(tipo).__mro__)
print(tipo.code, '|', tipo.description)
"
```

Ese `type(...).__mro__` dice de qué clase concreta construir las descripciones.

- [ ] **Step 3: Write the catalog module**

```python
# app/informes/catalogos.py
"""Descripciones de los catálogos del SAT para las hojas de los informes (§3 del fuente).

No se cargan tablas de catálogo: `satcfdi` ya las trae. Este módulo solo resuelve
`tipo → descripción` y devuelve `None` cuando la clave no está en el catálogo de la versión
instalada — el SAT agrega claves, y un catálogo desactualizado no debe abortar un informe.

Ajustar los nombres dentro de `_catalogos()` a los que exponga realmente `satcfdi` (ver el
paso 2 de esta tarea).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _catalogos() -> dict[str, Any]:
    """Carga perezosa: importar `satcfdi.catalogs` es costoso y no todo informe lo necesita."""
    from satcfdi import catalogs

    return {
        "P": getattr(catalogs, "TipoPercepcion", None),
        "D": getattr(catalogs, "TipoDeduccion", None),
        "O": getattr(catalogs, "TipoOtroPago", None),
    }


def _buscar(naturaleza: str, tipo: str) -> str | None:
    catalogo = _catalogos().get(naturaleza)
    if catalogo is None:
        return None
    try:
        entrada = catalogo(tipo)
    except (ValueError, KeyError):
        return None
    descripcion = getattr(entrada, "description", None)
    return str(descripcion) if descripcion else None


def descripcion_percepcion(tipo: str) -> str | None:
    return _buscar("P", tipo)


def descripcion_deduccion(tipo: str) -> str | None:
    return _buscar("D", tipo)


def descripcion_otro_pago(tipo: str) -> str | None:
    return _buscar("O", tipo)


def descripcion(naturaleza: str, tipo: str) -> str | None:
    """Despacho por naturaleza (`P`, `D`, `O`). Cualquier otra devuelve `None`."""
    if naturaleza not in {"P", "D", "O"}:
        return None
    return _buscar(naturaleza, tipo)
```

- [ ] **Step 4: Run the catalog test**

Run: `.venv/bin/pytest tests/test_informes_catalogos.py -q`
Expected: PASS (3 tests). Si falla porque `satcfdi.catalogs` tiene otros nombres, corregir `_catalogos()` con lo que devolvió el paso 2 — **no** relajar las aserciones del test.

- [ ] **Step 5: Fill the two gaps in B-02**

En `app/informes/b02_conceptos_patron.py`:

1. Importar el catálogo y el detalle:

```python
from app.informes import catalogos
from app.models.cfdi_detalle import ComprobanteDetalle
```

2. En `_universo`, agregar el `outerjoin` y la columna:

```python
        .outerjoin(ComprobanteDetalle, ComprobanteDetalle.comprobante_id == Comprobante.comprobante_id)
```

y cambiar el `select` a `select(Comprobante, Nomina, NominaReceptor, NominaTotales, ComprobanteDetalle)`.

3. En el bucle de `filas_universo`, desempacar el quinto elemento y usar su `serie`:

```python
    for comprobante, nomina, receptor, totales, detalle in filas_universo:
```

y sustituir el `None  # Serie: ...` por:

```python
            detalle.serie if detalle else None,
```

4. En la construcción del diccionario, sustituir `descripcion_sat=None` por:

```python
                descripcion_sat=catalogos.descripcion(naturaleza, tipo),
```

5. En `_banderas_de_periodos_traslapados` la llamada pasa `[(fila[0], fila[1]) for fila in filas_universo]`, que sigue siendo correcta con cinco elementos por fila.

- [ ] **Step 6: Extend the B-02 test**

Agregar a `tests/test_informe_b02.py`:

```python
async def test_diccionario_trae_la_descripcion_del_catalogo_sat(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(db, empresa_id=empresa.empresa_id, uuid="cccccccc-cccc-cccc-cccc-cccccccccccc")

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    entrada = next(e for e in resultado.diccionario if e.naturaleza == "P" and e.tipo == "001")
    assert entrada.descripcion_sat == "Sueldos, Salarios Rayas y Jornales"


async def test_serie_sale_del_detalle_del_comprobante(db: AsyncSession) -> None:
    from app.models.cfdi_detalle import ComprobanteDetalle

    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    cid = await _nomina(db, empresa_id=empresa.empresa_id, uuid="dddddddd-dddd-dddd-dddd-dddddddddddd")
    db.add(ComprobanteDetalle(comprobante_id=cid, version="4.0", serie="N", xml_hash="e" * 64, etl_version=1))
    await db.commit()

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    assert resultado.filas[0][_columna(resultado, "Serie")] == "N"
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_informe_b02.py tests/test_informes_catalogos.py -q`
Expected: PASS (13 + 3 tests)

- [ ] **Step 8: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/informes/catalogos.py app/informes/b02_conceptos_patron.py tests/test_informes_catalogos.py tests/test_informe_b02.py
git commit -m "feat(informes): resolver descripciones del catalogo SAT y serie en B-02"
```

---

### Task 13: Endpoints del catálogo y de generación, con pre-vuelo del ETL

**Files:**
- Modify: `app/api/v1/informes.py`
- Modify: `app/worker/tasks.py`
- Modify: `app/api/v1/schemas.py`
- Test: `tests/test_informes_api.py`

**Interfaces:**
- Consumes: `registro.catalogo`, `registro.obtener`, `excel.escribir_libro`, `normalizacion_lote.normalizar_lote`, `repo_normalizacion.ids_pendientes`, `enlaces.url_descarga`.
- Produces:
  - `GET /v1/informes` → `list[InformeCatalogoOut]` (rol: cualquier usuario autenticado)
  - `POST /v1/empresas/{empresa_id}/informes/{clave}` → `202` + `tarea_id`
  - Tarea Celery `app.worker.tasks.generar_informe(empresa_id: int, clave: str, parametros: dict, usuario: str) -> dict` → `{"ruta": ..., "filas": n, "banderas": n}`
  - `class InformeCatalogoOut(BaseModel)`: `clave`, `nombre`, `grupo`, `descripcion`, `parametros: dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_informes_api.py
"""Endpoints de informes (spec §7.2) y el pre-vuelo del ETL (disparador 3, spec §6.3)."""

from __future__ import annotations

import io
import os

from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import RolEmpresa, RolGlobal
from tests import factories, fixtures_cfdi


async def test_catalogo_expone_b02_con_su_json_schema(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/v1/informes", headers={"Authorization": "Bearer op"})
    assert r.status_code == 200, r.text
    claves = {i["clave"]: i for i in r.json()}
    assert "B-02" in claves
    b02 = claves["B-02"]
    assert b02["grupo"] == "B"
    # El frontend arma el formulario desde aquí: los parámetros deben venir descritos.
    propiedades = b02["parametros"]["properties"]
    assert "fecha_desde" in propiedades
    assert propiedades["enmascarar_datos_personales"]["default"] is True


async def test_generar_informe_encola_con_los_parametros(client, db: AsyncSession, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.worker import tasks

    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    usuario = await factories.crear_usuario(db, uid="con", correo="con@test.mx", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    encoladas: list[tuple[int, str, dict, str]] = []

    class _Tarea:
        id = "tarea-informe"

    monkeypatch.setattr(
        tasks.generar_informe,
        "delay",
        lambda empresa_id, clave, parametros, actor: (encoladas.append((empresa_id, clave, parametros, actor)), _Tarea())[1],
    )

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/informes/B-02",
        json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31"},
        headers={"Authorization": "Bearer con"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["tarea_id"] == "tarea-informe"
    assert encoladas[0][1] == "B-02"
    assert encoladas[0][2]["fecha_desde"] == "2026-06-01"
    assert encoladas[0][3] == "con@test.mx"


async def test_clave_desconocida_da_404(client, db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    usuario = await factories.crear_usuario(db, uid="con", correo="con@test.mx", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/informes/Z-99",
        json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31"},
        headers={"Authorization": "Bearer con"},
    )
    assert r.status_code == 404


async def test_parametros_invalidos_dan_422(client, db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    usuario = await factories.crear_usuario(db, uid="con", correo="con@test.mx", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/informes/B-02",
        json={"fecha_desde": "no-es-fecha"},
        headers={"Authorization": "Bearer con"},
    )
    assert r.status_code == 422


async def test_sin_enmascarar_exige_operador_y_deja_bitacora(client, db: AsyncSession, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """spec §8."""
    from sqlalchemy import select

    from app.models.bitacora import Bitacora
    from app.worker import tasks

    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    consulta = await factories.crear_usuario(db, uid="con", correo="con@test.mx", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, consulta, empresa, RolEmpresa.CONSULTA)
    operador = await factories.crear_usuario(db, uid="op", correo="op@test.mx", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)

    class _Tarea:
        id = "t"

    monkeypatch.setattr(tasks.generar_informe, "delay", lambda *a, **k: _Tarea())

    cuerpo = {"fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31", "enmascarar_datos_personales": False}

    r = await client.post(f"/v1/empresas/{empresa.empresa_id}/informes/B-02", json=cuerpo, headers={"Authorization": "Bearer con"})
    assert r.status_code == 403

    r = await client.post(f"/v1/empresas/{empresa.empresa_id}/informes/B-02", json=cuerpo, headers={"Authorization": "Bearer op"})
    assert r.status_code == 202

    registros = list((await db.execute(select(Bitacora).where(Bitacora.accion == "generar_informe"))).scalars().all())
    assert registros, "la generación sin enmascarar debe quedar en bitácora"
    assert registros[-1].detalle["enmascarar_datos_personales"] is False


async def test_tarea_genera_libro_y_normaliza_lo_pendiente(db: AsyncSession) -> None:
    """Pre-vuelo: el comprobante existe en `comprobantes` pero nunca se normalizó. La
    tarea lo normaliza antes de consultar, así que el informe NO sale vacío."""
    from app.worker.tasks import _generar_informe_async

    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    carpeta = os.path.join(get_settings().storage_root, str(empresa.empresa_id), "comprobantes")
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, "nomina.xml"), "wb") as f:
        f.write(fixtures_cfdi.cfdi_nomina())
    await factories.crear_comprobante(
        db,
        empresa_id=empresa.empresa_id,
        uuid="77777777-7777-7777-7777-777777777777",
        tipo_comprobante="N",
        xml_path=os.path.join(str(empresa.empresa_id), "comprobantes", "nomina.xml"),
    )

    resultado = await _generar_informe_async(
        empresa.empresa_id,
        "B-02",
        {"fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31"},
        "op@test.mx",
    )

    assert resultado["filas"] == 1
    ruta = os.path.join(get_settings().storage_root, resultado["ruta"])
    assert os.path.isfile(ruta)

    with open(ruta, "rb") as f:
        wb = load_workbook(io.BytesIO(f.read()))
    assert wb.sheetnames == ["Datos", "Parámetros", "Banderas", "Diccionario"]
    datos = wb["Datos"]
    encabezados = [c.value for c in datos[1]]
    assert "UUID" in encabezados
    assert any("Sueldo" in (t or "") for t in encabezados)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_informes_api.py -q`
Expected: FAIL — `GET /v1/informes` devuelve 404 (el endpoint no existe).

- [ ] **Step 3: Add the response schema**

Agregar a `app/api/v1/schemas.py`:

```python
class InformeCatalogoOut(BaseModel):
    """Entrada del catálogo de informes. `parametros` es el JSON Schema de la clase
    `Parametros` del informe: el frontend genera su formulario desde ahí (spec §7.2)."""

    clave: str
    nombre: str
    grupo: str
    descripcion: str
    parametros: dict[str, Any]
```

Verificar que `Any` esté importado en el módulo (`from typing import Any`).

- [ ] **Step 4: Write the Celery task**

Agregar a `app/worker/tasks.py`:

```python
# --------------------------------------------------------------------------- #
# Generación de informes (spec §7). El pre-vuelo normaliza lo pendiente del rango
# antes de consultar: así un informe nunca sale vacío porque el ETL no corrió
# (disparador 3 del spec §6.3).
# --------------------------------------------------------------------------- #


async def _generar_informe_async(empresa_id: int, clave: str, parametros: dict[str, Any], actor: str) -> dict[str, Any]:
    from datetime import datetime

    from app.informes import excel, registro
    from app.informes.base import ContextoInforme
    from app.repositories import normalizacion as repo_normalizacion
    from app.services import normalizacion, normalizacion_lote

    definicion = registro.obtener(clave)
    p = definicion.Parametros(**parametros)

    async with SessionLocal() as db:
        # Pre-vuelo: normaliza lo que falte. No se acota por fecha porque los informes
        # del grupo B filtran por `nomina.fecha_pago`, que solo se conoce DESPUÉS de
        # normalizar; acotar por `fecha_emision` dejaría fuera nóminas legítimas.
        pendientes = await repo_normalizacion.ids_pendientes(db, empresa_id)
        if pendientes:
            resumen = await normalizacion_lote.normalizar_lote(db, empresa_id, pendientes)
            logger.info("generar_informe: pre-vuelo del ETL para empresa %s → %s", empresa_id, resumen)

        resultado = await definicion.consultar(db, empresa_id, p)

    ctx = ContextoInforme(
        clave=definicion.CLAVE,
        nombre=definicion.NOMBRE,
        usuario=actor,
        generado_en=datetime.now(),
        parametros=parametros,
        etl_version=normalizacion.ETL_VERSION,
    )
    contenido = excel.escribir_libro(resultado, ctx)

    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), "informes")
    os.makedirs(carpeta, exist_ok=True)
    nombre = f"{clave}_{uuid.uuid4().hex[:12]}.xlsx"
    with open(os.path.join(carpeta, nombre), "wb") as f:
        f.write(contenido)

    return {
        "ruta": os.path.join(str(empresa_id), "informes", nombre),
        "filas": len(resultado.filas),
        "banderas": len(resultado.banderas),
    }


@celery_app.task(name="app.worker.tasks.generar_informe")  # type: ignore[untyped-decorator]
def generar_informe(empresa_id: int, clave: str, parametros: dict[str, Any], actor: str) -> dict[str, Any]:
    return asyncio.run(_generar_informe_async(empresa_id, clave, parametros, actor))
```

- [ ] **Step 5: Write the endpoints**

Reemplazar el contenido de `app/api/v1/informes.py` por (conservando `normalizar_endpoint` de la tarea 9):

```python
"""Catálogo, generación de informes y reproceso del ETL (spec §7.2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_empresa, usuario_actual
from app.api.v1.schemas import InformeCatalogoOut, NormalizarIn, TareaCrearOut
from app.informes import registro
from app.models.enums import RolEmpresa
from app.models.usuario import Usuario
from app.services import bitacora as bitacora_service
from app.worker.tasks import generar_informe, normalizar_comprobantes

router_catalogo = APIRouter(tags=["informes"])
router = APIRouter(prefix="/empresas/{empresa_id}/informes", tags=["informes"])


@router_catalogo.get("/informes", response_model=list[InformeCatalogoOut])
async def catalogo_endpoint(usuario: Usuario = Depends(usuario_actual)) -> list[InformeCatalogoOut]:
    """Catálogo de informes disponibles con el JSON Schema de sus parámetros. No depende de
    la empresa: es la misma lista para todas."""
    return [InformeCatalogoOut(**entrada) for entrada in registro.catalogo()]


@router.post("/normalizar", status_code=status.HTTP_202_ACCEPTED, response_model=TareaCrearOut)
async def normalizar_endpoint(
    empresa_id: int,
    body: NormalizarIn,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> TareaCrearOut:
    """Reprocesa los XML ya resguardados hacia la capa normalizada. Pide OPERADOR: es una
    escritura masiva, aunque idempotente."""
    await bitacora_service.registrar(
        db, actor=ctx.usuario.correo, accion="normalizar_comprobantes", entidad=f"empresa:{empresa_id}", detalle={"alcance": body.alcance}
    )
    await db.commit()

    tarea = normalizar_comprobantes.delay(empresa_id, body.alcance)
    return TareaCrearOut(tarea_id=tarea.id)


@router.post("/{clave}", status_code=status.HTTP_202_ACCEPTED, response_model=TareaCrearOut)
async def generar_endpoint(
    empresa_id: int,
    clave: str,
    parametros: dict[str, Any] = Body(default_factory=dict),
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> TareaCrearOut:
    """Encola la generación de un informe. Los parámetros se validan aquí contra la clase
    `Parametros` del informe, no en la tarea: un `422` es mucho más útil que una tarea que
    falla en segundo plano."""
    try:
        definicion = registro.obtener(clave)
    except registro.InformeDesconocidoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Informe no encontrado.") from exc

    try:
        validados = definicion.Parametros(**parametros)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc

    # spec §8: generar sin enmascarar exige OPERADOR y queda en bitácora.
    sin_enmascarar = getattr(validados, "enmascarar_datos_personales", True) is False
    if sin_enmascarar:
        if ctx.rol == RolEmpresa.CONSULTA:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Generar el informe sin enmascarar datos personales requiere rol de operador o superior.",
            )
        await bitacora_service.registrar(
            db,
            actor=ctx.usuario.correo,
            accion="generar_informe",
            entidad=f"empresa:{empresa_id}",
            detalle={"clave": clave, "enmascarar_datos_personales": False, "parametros": parametros},
        )
        await db.commit()

    tarea = generar_informe.delay(empresa_id, clave, validados.model_dump(mode="json"), ctx.usuario.correo)
    return TareaCrearOut(tarea_id=tarea.id)
```

**Dos detalles ya verificados contra `app/api/deps.py`, no hay que adivinarlos:**

- `usuario_actual` existe (`deps.py:62`) y devuelve el `Usuario`.
- `ContextoEmpresa.rol` está declarado como `RolEmpresa | RolGlobal` (`deps.py:40`): a un
  administrador global se le asigna `RolGlobal.ADMIN` (`deps.py:86`), no un `RolEmpresa`. Por
  eso la comprobación se escribe como `ctx.rol == RolEmpresa.CONSULTA` y **no** como
  `ctx.rol != RolEmpresa.OPERADOR`: con la segunda forma, un administrador quedaría bloqueado.

- [ ] **Step 6: Register both routers**

En `app/main.py`, junto al router de informes de la tarea 9:

```python
app.include_router(informes_router.router_catalogo, prefix="/v1")
app.include_router(informes_router.router, prefix="/v1")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_informes_api.py -q`
Expected: PASS (6 tests)

- [ ] **Step 8: Type-check and commit**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
git add app/api/v1/informes.py app/api/v1/schemas.py app/worker/tasks.py app/main.py tests/test_informes_api.py
git commit -m "feat(informes): agregar endpoints de catalogo y generacion con pre-vuelo del ETL"
```

---

### Task 14: Frontend — sección Informes

**Files:**
- Modify: `apps/web/src/lib/api.ts` (tipos y contrato)
- Modify: `apps/web/src/lib/api.http.ts`
- Modify: `apps/web/src/lib/api.mock.ts`
- Create: `apps/web/src/features/informes/InformesPage.tsx`
- Modify: `apps/web/src/App.tsx` (ruta) y el menú de navegación en `apps/web/src/components/layout/`

**Interfaces:**
- Consumes: `GET /v1/informes`, `POST /v1/empresas/{id}/informes/{clave}`, `GET /v1/tareas/{id}` (ya en el contrato como `estadoTarea`).
- Produces en `api.ts`:
  - `export interface InformeCatalogo { clave: string; nombre: string; grupo: string; descripcion: string; parametros: Record<string, unknown>; }`
  - `listarInformes(): Promise<InformeCatalogo[]>`
  - `generarInforme(empresaId: number, clave: string, parametros: Record<string, unknown>): Promise<{ tarea_id: string }>`

- [ ] **Step 1: Extend the API contract**

En `apps/web/src/lib/api.ts`, agregar el tipo y los dos métodos a la interfaz `ApiClient`
(seguir el estilo de los vecinos, p. ej. `exportarExcel`):

```typescript
/** Entrada del catálogo de informes (doc: spec §7.2). `parametros` es un JSON Schema. */
export interface InformeCatalogo {
  clave: string;
  nombre: string;
  grupo: string;
  descripcion: string;
  parametros: Record<string, unknown>;
}
```

Y en la interfaz del cliente:

```typescript
  listarInformes(): Promise<InformeCatalogo[]>;
  generarInforme(empresaId: number, clave: string, parametros: Record<string, unknown>): Promise<{ tarea_id: string }>;
```

- [ ] **Step 2: Implement in the HTTP client**

En `apps/web/src/lib/api.http.ts`, agregar `'listarInformes'` y `'generarInforme'` a la unión
de claves y las implementaciones:

```typescript
  listarInformes: () => request('/v1/informes'),

  generarInforme: (empresaId, clave, parametros) =>
    request(`/v1/empresas/${empresaId}/informes/${clave}`, { method: 'POST', body: JSON.stringify(parametros) }),
```

- [ ] **Step 3: Implement in the mock client**

En `apps/web/src/lib/api.mock.ts`, devolver un catálogo con B-02 y una tarea falsa, siguiendo
el estilo de los mocks vecinos:

```typescript
  listarInformes: async () => [
    {
      clave: 'B-02',
      nombre: 'Nómina agrupada por conceptos del patrón',
      grupo: 'B',
      descripcion: 'Una fila por CFDI de nómina, con una columna por cada concepto del patrón.',
      parametros: {
        properties: {
          fecha_desde: { type: 'string', format: 'date' },
          fecha_hasta: { type: 'string', format: 'date' },
          tipo_nomina: { enum: ['O', 'E', 'AMBOS'], default: 'AMBOS' },
          incluir_cancelados: { type: 'boolean', default: false },
          desglosar_gravado_exento: { type: 'boolean', default: false },
          enmascarar_datos_personales: { type: 'boolean', default: true },
        },
        required: ['fecha_desde', 'fecha_hasta'],
      },
    },
  ],

  generarInforme: async () => ({ tarea_id: 'mock-informe' }),
```

- [ ] **Step 4: Build the page**

`apps/web/src/features/informes/InformesPage.tsx`. Requisitos concretos, sin inventar
componentes nuevos: reusar los de `apps/web/src/components/ui` y el patrón de sondeo de
tarea → descarga que ya usan `DescargasPage` y `ComprobantesPage` (`estadoTarea` +
`descarga_url`).

La pantalla debe tener:

1. Lista de informes del catálogo, agrupada por `grupo`, con `nombre` y `descripcion`.
2. Al elegir uno, un formulario generado desde `parametros.properties`:
   - `type: 'string', format: 'date'` → `<input type="date">`, obligatorio si está en `required`
   - `enum` → `<select>` con el `default` preseleccionado
   - `type: 'boolean'` → casilla con su `default`
3. Botón **Generar** que llama a `generarInforme`, guarda el `tarea_id` y sondea
   `estadoTarea` con el mismo intervalo que las otras pantallas hasta `completada`, y
   entonces dispara la descarga con `descargarBlob`/`descarga_url`.
4. Aviso visible cuando el usuario desmarca `enmascarar_datos_personales`: "Se generará con
   CURP, NSS y cuenta bancaria a la vista. Queda registrado en la bitácora." Y si la API
   responde `403`, mostrar el mensaje del error, no un fallo genérico.
5. Estados de carga y error con los componentes que ya existen.

- [ ] **Step 5: Add the route and the menu entry**

Agregar la ruta en `apps/web/src/App.tsx` siguiendo el patrón de las demás páginas de
empresa, y la entrada "Informes" en el menú lateral de `apps/web/src/components/layout/`.
Visible para cualquier rol (el enmascaramiento es el que protege los datos).

- [ ] **Step 6: Verify the build is clean**

```bash
cd apps/web && npm run build && npx tsc --noEmit && npx eslint src
```

Expected: los tres sin errores. `tsc` fallará si `api.mock.ts` no implementa los dos métodos
nuevos — el contrato obliga a las dos implementaciones, que es justamente para lo que está.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/api.http.ts apps/web/src/lib/api.mock.ts apps/web/src/features/informes/ apps/web/src/App.tsx apps/web/src/components/layout/
git commit -m "feat(web): agregar seccion de Informes con formulario desde el catalogo"
```

---

### Task 15: Verificación en vivo contra los 351 XML reales

Esta tarea no escribe código de producción: comprueba que la fase 1 funciona sobre los datos
reales de la empresa 11. Es el criterio de cierre del spec §14.

**Files:**
- Create: `scripts/verificar_fase1.py` (script de verificación, no se importa desde `app`)

**Interfaces:**
- Consumes: `normalizacion`, `repo_normalizacion`, `normalizacion_lote`, `b02_conceptos_patron`.
- Produces: un script que imprime el resultado y sale con código distinto de cero si alguna comprobación falla.

- [ ] **Step 1: Apply all migrations to the real database**

```bash
docker compose up -d
docker compose exec api alembic upgrade head
docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "show tables;" hub_cfdi' | sort
```

Expected: las 15 tablas nuevas presentes, además de las 13 que ya existían.

- [ ] **Step 2: Reprocess the 351 real XMLs**

```bash
docker compose exec api python -c "
import asyncio
from app.db.session import SessionLocal
from app.repositories import normalizacion as repo
from app.services import normalizacion_lote

async def main():
    async with SessionLocal() as db:
        ids = await repo.ids_pendientes(db, 11)
        print('pendientes:', len(ids))
        print(await normalizacion_lote.normalizar_lote(db, 11, ids))

asyncio.run(main())
"
```

Expected: `pendientes: 351` y un resumen con `normalizados: 351, con_error: 0, omitidos: 0`.
Si aparecen errores, listarlos antes de continuar:

```bash
docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -t -e "select comprobante_id, error_normalizacion from comprobante_detalle where error_normalizacion is not null limit 20;" hub_cfdi'
```

- [ ] **Step 3: Write the verification script**

```python
# scripts/verificar_fase1.py
"""Verificación en vivo de la fase 1 contra los datos reales (spec §13, §14).

Comprueba las 9 identidades de B-00 sobre los CFDI de nómina ya normalizados y que B-02
produce el número de filas y de columnas dinámicas esperado. Sale con código 1 si algo
falla, para poder usarse como comprobación de cierre.

No imprime CURP, NSS ni cuentas bancarias: son datos personales y esto se corre en una
terminal cuyo historial queda guardado.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.informes import b02_conceptos_patron as b02
from app.models.comprobante import Comprobante
from app.models.nomina import Nomina, NominaDeduccion, NominaOtroPago, NominaPercepcion

EMPRESA_ID = 11
TOLERANCIA = Decimal("0.01")


async def main() -> int:
    fallas: list[str] = []

    async with SessionLocal() as db:
        nominas = list(
            (
                await db.execute(
                    select(Comprobante.comprobante_id, Comprobante.uuid, Comprobante.total, Nomina)
                    .join(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
                    .where(Comprobante.empresa_id == EMPRESA_ID)
                )
            ).all()
        )
        print(f"CFDI de nómina normalizados: {len(nominas)}")
        if not nominas:
            print("FALLA: no hay nóminas normalizadas; ¿corrió el reproceso?")
            return 1

        for cid, uuid_cfdi, total, nomina in nominas:
            percepciones = await db.scalar(
                select(func.coalesce(func.sum(NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento), 0)).where(
                    NominaPercepcion.comprobante_id == cid
                )
            )
            deducciones = await db.scalar(
                select(func.coalesce(func.sum(NominaDeduccion.importe), 0)).where(NominaDeduccion.comprobante_id == cid)
            )
            otros = await db.scalar(select(func.coalesce(func.sum(NominaOtroPago.importe), 0)).where(NominaOtroPago.comprobante_id == cid))

            identidades = (
                ("total_percepciones", nomina.total_percepciones, Decimal(str(percepciones))),
                ("total_deducciones", nomina.total_deducciones, Decimal(str(deducciones))),
                ("total_otros_pagos", nomina.total_otros_pagos, Decimal(str(otros))),
            )
            for nombre, declarado, calculado in identidades:
                if declarado is not None and abs(declarado - calculado) > TOLERANCIA:
                    fallas.append(f"{uuid_cfdi}: {nombre} declarado {declarado} ≠ calculado {calculado}")

            # `total = subtotal − descuento` con subtotal = percepciones + otros pagos
            # y descuento = deducciones (identidades de B-00).
            neto = Decimal(str(percepciones)) + Decimal(str(otros)) - Decimal(str(deducciones))
            if total is not None and abs(Decimal(str(total)) - neto) > TOLERANCIA:
                fallas.append(f"{uuid_cfdi}: total del CFDI {total} ≠ percepciones + otros − deducciones {neto}")

        print(f"Identidades de B-00 evaluadas: {len(nominas) * 4}")

        resultado = await b02.consultar(
            db,
            EMPRESA_ID,
            b02.Parametros(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 12, 31)),
        )
        dinamicas = [c.titulo for c in resultado.columnas if b02.SEPARADOR_ETIQUETA in c.titulo]
        print(f"B-02: {len(resultado.filas)} filas, {len(dinamicas)} columnas dinámicas, {len(resultado.banderas)} banderas")
        print("Conceptos detectados:")
        for titulo in dinamicas:
            print("  ", titulo)

        if len(resultado.filas) != len(nominas):
            fallas.append(f"B-02 devolvió {len(resultado.filas)} filas para {len(nominas)} nóminas normalizadas")

        for bandera in resultado.banderas:
            print(f"  [{bandera.severidad}] {bandera.clave} · {bandera.ambito} · {bandera.mensaje}")

    if fallas:
        print("\nFALLAS:")
        for falla in fallas:
            print("  -", falla)
        return 1
    print("\nTodas las comprobaciones pasaron.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 4: Run the verification**

```bash
docker compose exec api python scripts/verificar_fase1.py
```

Expected, con los datos reales verificados durante el diseño:

- 8 CFDI de nómina normalizados.
- Todas las identidades de B-00 dentro de 0.01. **Si alguna falla, es un bug del ETL** —
  el XML del SAT está timbrado y sus totales cuadran por construcción.
- B-02: **8 filas** y **12 columnas dinámicas** (3 percepciones, 7 deducciones, 2 otros
  pagos), que son los conceptos que la exploración encontró en los XML reales.
- Entre las columnas deben aparecer, con prefijo de naturaleza distinto,
  `D¦004¦099¦Ajuste al neto` y `O¦999¦099¦Ajuste al neto`.
- Bandera `POSIBLE_ESPEJO` no aplica (es de B-01); sí puede aparecer
  `CONCEPTO_INCONSISTENTE` si alguna descripción varía entre quincenas.

- [ ] **Step 5: Generate the report end to end from the UI**

Con los servicios arriba y `npm run dev` corriendo:

1. Entrar a la sección **Informes**, elegir B-02, rango 2026-01-01 a 2026-12-31, dejar el
   enmascaramiento activado.
2. Generar, esperar la tarea, descargar el `.xlsx`.
3. Abrirlo y comprobar: 4 hojas; en `Datos` 8 filas de datos más el encabezado; en
   `Parámetros` el usuario, la fecha, la versión del ETL y los filtros; en `Diccionario` las
   12 entradas con su descripción del catálogo del SAT.
4. Comprobar que **CURP y NSS salen enmascarados** (`****` + 4 caracteres).
5. Repetir con el enmascaramiento desactivado desde una cuenta con rol operador, y
   comprobar en Bitácora que quedó el registro `generar_informe`.

- [ ] **Step 6: Commit the verification script**

```bash
git add scripts/verificar_fase1.py
git commit -m "test(informes): agregar script de verificacion en vivo de la fase 1"
```

- [ ] **Step 7: Record what the live run showed**

Anotar en el commit o en el PR: número de nóminas normalizadas, filas y columnas de B-02,
banderas que salieron y cualquier discrepancia. Si aparecieron banderas
`TOTALES_DESCUADRADOS` sobre CFDI reales timbrados, **no cerrar la fase**: es un bug del ETL,
no un hallazgo del informe.

---

## Notas de cierre

**Lo que queda listo al terminar la fase 1:** las 15 tablas, el ETL con sus tres
disparadores, el motor de informes con el libro de cuatro hojas, B-02 completo con su
Diccionario, y la sección Informes en la web.

**Lo que sigue (fases 2 y 3 del spec §14),** cada una con su propio plan:

- **Fase 2:** B-01, B-04, B-05 (columnas 1–23), B-07, B-10 (21 de 23 reglas). Ninguno
  necesita tablas de configuración. B-01 reusa `catalogos.py` para generar el conjunto fijo
  de columnas desde el catálogo completo, no desde los datos observados (B-01.R1).
- **Fase 3:** las cinco tablas de configuración del spec §12 y sus cargadores, que habilitan
  B-03 completo, B-06 y B-08. **Las semillas fiscales las valida David antes de cargarse.**

**Pendiente operativo, no de código:** descargar más historia de nómina del SAT. Con 2
quincenas y 4 empleados, B-02 sale correcto pero pequeño, B-04 sería una matriz de 4×2 y
B-05 no tiene sentido hasta tener un ejercicio completo.

**Deuda anotada durante el diseño**, que ningún informe del grupo B necesita pero los grupos
A y C sí (spec §16): conservar `EsCancelable`/`EstatusCancelacion` del WS de estatus,
persistir la metadata del SAT, y leer las fechas de publicación del CSV 69-B.
