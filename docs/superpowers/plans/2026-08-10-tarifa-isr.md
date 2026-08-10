# Tarifa del ISR y subsidio al empleo — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que la tarifa del ISR y el subsidio al empleo se puedan cargar desde el documento oficial del
SAT, corregir a mano, comprobar contra un recibo real y confirmar, sin que nada calcule antes de que una
persona lo confirme.

**Architecture:** un extractor puro del PDF del Anexo 8 (`app/services/anexo8.py`) que no toca la BD; un
módulo puro con las reglas de la tarifa —validación, huella y fórmula del ISR— (`app/services/tarifa_isr.py`);
un repositorio que persiste y confirma (`app/repositories/tarifa_isr.py`); endpoints de administrador en el
router de configuración que ya existe; y un panel nuevo en la pantalla de configuración fiscal. El subsidio
reutiliza sin cambios el mecanismo de `param_fiscal`.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2 async, MySQL 8, Alembic, `pypdfium2` (extracción de
texto del PDF), `weasyprint` (PDF de revisión), pytest + testcontainers, React 19 + TS + Tailwind 4 +
TanStack Query 5.

**Documento de diseño:** `docs/superpowers/specs/2026-08-10-tarifa-isr-design.md`. Ante cualquier duda de
"por qué así", la respuesta está ahí; este plan no repite las justificaciones.

## Global Constraints

Estas reglas aplican a **todas** las tareas. No se repiten en cada una.

- **Se trabaja directo en `main`**, con commits frecuentes. Sin ramas de feature ni worktrees.
- **Ningún importe fiscal literal en `app/`** (§2.12 del documento fuente). Un `Decimal("117.31")` en
  `app/` es un defecto Critical. En YAML de semillas y en pruebas sí: son datos, no código.
- **Todo dato fiscal entra sin confirmar.** Importar, sembrar y corregir **proponen**; solo una persona
  confirma. Ninguna función de escritura toca `confirmado_por` / `confirmado_en`.
- **Bitácora en la misma transacción** que la operación (regla no negociable 8). Si la bitácora falla, la
  operación se revierte.
- **Los endpoints de configuración fiscal son de administrador**: `Depends(require_admin)`. La
  configuración fiscal es política federal y aplica a todas las empresas.
- **Cero N+1** (regla 11): joins o dos consultas explícitas, nunca lazy loading por fila.
- **`.venv/bin/mypy --strict app` limpio antes de cada commit.** No se commitea con mypy en rojo.
- **El contrato `ApiClient` (doc 05 §9) se actualiza en la misma sesión** que el endpoint que lo cambia
  (regla 10).
- **Los mensajes que ve una persona van en español llano y dicen qué hacer.** El nombre de la excepción
  (`CorreccionManualProtegida`) es para el log, nunca para la pantalla. Ver §10 del diseño para el texto
  exacto de cada caso.
- **Ninguna etiqueta visible es un nombre de enum ni una clave en mayúsculas.** `DIAS_15` se muestra como
  "Quincenal (15 días)"; `SUBSIDIO_FACTOR_UMA` como "Subsidio al empleo — porcentaje de la UMA mensual".
- **Los enums persisten su `.value`**: se declaran con `enum_column(...)` de `app/models/enums.py`.
- **En las pruebas de mutación hay que exigir que la prueba FALLE y mirar el conteo de selección de `-k`.**
  Un `-k` que no selecciona nada sale con código 5 y se ve igual que una prueba muerta. Las cuatro trampas
  están documentadas en el docstring de `tests/test_cli_configuracion.py`.
- **Datos de prueba:** el RFC y la razón social de la propia empresa sí; datos de terceros no; CURP, NSS y
  cuentas bancarias **siempre inventados** (regla 12).

## Estructura de archivos

**Backend**

| Archivo | Responsabilidad |
|---|---|
| `app/models/enums.py` (modificar) | `PeriodicidadTarifa`, `OrigenTarifa` |
| `app/models/configuracion_fiscal.py` (modificar) | `TarifaIsr`, `TarifaIsrRenglon` |
| `alembic/versions/<hash>_add_tarifa_isr.py` (crear) | Las dos tablas nuevas |
| `app/services/tarifa_isr.py` (crear) | **Puro.** `Renglon`, `Tarifa`, `validar`, `huella`, `renglon_para`, `isr_de`, mapa periodicidad CFDI → tarifa |
| `app/services/anexo8.py` (crear) | **Puro.** Extrae tarifas del PDF del Anexo 8 |
| `app/repositories/tarifa_isr.py` (crear) | Persistencia: guardar, leer, confirmar, borrar |
| `app/services/comprobacion_tarifa.py` (crear) | Elige un recibo real y compara el ISR calculado con el timbrado |
| `app/services/revision_tarifa.py` (crear) | HTML + PDF de la hoja de revisión para el contador |
| `app/services/configuracion_fiscal.py` (modificar) | Dos claves nuevas en `CLAVES_PARAM_FISCAL` |
| `app/services/sincronizacion_fiscal.py` (modificar) | Alerta sintética `TARIFA_ISR` |
| `app/api/v1/schemas.py` (modificar) | Esquemas de entrada y salida |
| `app/api/v1/configuracion.py` (modificar) | Los cinco endpoints y el de la hoja de revisión |
| `config/fiscal/param_fiscal.yaml` (modificar) | Subsidio 2026 y UMA de 2025 |

**Frontend**

| Archivo | Responsabilidad |
|---|---|
| `apps/web/src/lib/api.ts` (modificar) | Tipos y métodos del contrato |
| `apps/web/src/lib/api.http.ts` (modificar) | Implementación HTTP |
| `apps/web/src/lib/api.mock.ts` (modificar) | Doble para desarrollo |
| `apps/web/src/features/admin/TarifaIsrPanel.tsx` (crear) | El panel completo de tarifas |
| `apps/web/src/features/admin/ConfiguracionFiscalPage.tsx` (modificar) | Monta el panel |

`TarifaIsrPanel.tsx` es un archivo nuevo y no una sección más en `ConfiguracionFiscalPage.tsx`, que ya
tiene 672 líneas. Meterlo ahí la dejaría inmanejable.

**Pruebas**

| Archivo | Cubre |
|---|---|
| `tests/fixtures/anexo8-2026.pdf` (crear) | El documento oficial real |
| `tests/test_tarifa_isr.py` (crear) | Validación, huella, fórmula, mapa de periodicidades |
| `tests/test_anexo8.py` (crear) | El extractor contra el PDF real |
| `tests/test_api_tarifa_isr.py` (crear) | Los endpoints, la bitácora y los límites |
| `tests/test_comprobacion_tarifa.py` (crear) | La comprobación con recibo real |
| `scripts/verificar_tarifa_isr.py` (crear) | Verificación en vivo (§12 del diseño) |

---

### Task 1: Esquema y migración

**Files:**
- Modify: `app/models/enums.py`
- Modify: `app/models/configuracion_fiscal.py`
- Create: `alembic/versions/<hash>_add_tarifa_isr.py`
- Modify: `Hub_CFDI_docs/03-datos/03_modelo_de_datos.md` (DDL)

**Interfaces:**
- Produces: `PeriodicidadTarifa` (`DIARIA`, `DIAS_7`, `DIAS_10`, `DIAS_15`, `MENSUAL`, `EJERCICIO`);
  `OrigenTarifa` (`IMPORTADA`, `MANUAL`); modelos `TarifaIsr` (PK `ejercicio`, `periodicidad`) y
  `TarifaIsrRenglon` (PK `ejercicio`, `periodicidad`, `renglon`).

- [ ] **Step 1: Escribir los enums**

En `app/models/enums.py`, después de `OrigenValor`:

```python
class PeriodicidadTarifa(str, Enum):
    """Periodicidades **como las publica el Anexo 8**, no como las nombra el CFDI.

    El catálogo `c_PeriodicidadPago` del SAT tiene periodicidades para las que el Anexo no
    publica tarifa (`03` catorcenal, `06` bimestral), así que admitirlas aquí sugeriría que
    existen. La traducción de una cosa a la otra vive en `app.services.tarifa_isr.PARA_CFDI`.
    """

    DIARIA = "DIARIA"
    DIAS_7 = "DIAS_7"
    DIAS_10 = "DIAS_10"
    DIAS_15 = "DIAS_15"
    MENSUAL = "MENSUAL"
    EJERCICIO = "EJERCICIO"


class OrigenTarifa(str, Enum):
    """De dónde salió una tarifa. `IMPORTADA` no es `SEMILLA`: no viene del repositorio, viene
    del documento oficial que alguien subió, y su huella queda en `documento_sha256`."""

    IMPORTADA = "IMPORTADA"
    MANUAL = "MANUAL"
```

- [ ] **Step 2: Escribir los modelos**

En `app/models/configuracion_fiscal.py`, al final. Los imports que hay que añadir a los que ya existen:
`OrigenTarifa`, `PeriodicidadTarifa` desde `app.models.enums`.

```python
class TarifaIsr(Base):
    """Una tarifa del ISR (`ejercicio` + `periodicidad`) con su procedencia y su confirmación.

    **La cabecera va aparte de los renglones a propósito**, divergiendo del §12 del documento
    fuente, que describe `tarifa_isr` como una tabla plana. La procedencia y la confirmación son
    propiedades de *la tarifa*: con una tabla plana existiría el estado "renglón 3 confirmado,
    renglón 4 no", que no significa nada, que ningún cálculo puede usar y que habría que excluir
    a mano en cada consulta. Aquí ese estado es inexpresable.

    `documento_sha256` es nulo cuando la tarifa se capturó a mano sin documento. `encabezado`
    guarda **citado literal** el texto del que salieron los renglones: es lo que se le muestra a
    quien confirma para que vea de qué tabla del documento vinieron, y sin él el ancla del
    extractor sería una decisión invisible.
    """

    __tablename__ = "tarifa_isr"
    __table_args__ = (_TABLA_ARGS,)

    ejercicio: Mapped[int] = mapped_column(Integer, primary_key=True)
    periodicidad: Mapped[PeriodicidadTarifa] = mapped_column(enum_column(PeriodicidadTarifa), primary_key=True)
    origen: Mapped[OrigenTarifa] = mapped_column(enum_column(OrigenTarifa), nullable=False)
    fuente: Mapped[str] = mapped_column(String(500), nullable=False)
    documento_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    encabezado: Mapped[str] = mapped_column(String(1000), nullable=False)
    importado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    confirmado_por: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TarifaIsrRenglon(Base):
    """Un renglón de una tarifa. `limite_superior` nulo es el último renglón ("En adelante").

    `tasa_excedente` se guarda como **fracción decimal** (`0.213600`), nunca como el porcentaje
    que publica el SAT (`21.36`). La conversión ocurre en un único lugar
    (`app.services.anexo8`) y `tarifa_isr.validar` la vigila: una tasa en la escala equivocada
    produce un ISR cien veces mayor o menor, y el segundo caso pasa desapercibido porque el
    resultado sigue siendo un número pequeño y plausible (B-09.R2).
    """

    __tablename__ = "tarifa_isr_renglon"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ejercicio", "periodicidad"],
            ["tarifa_isr.ejercicio", "tarifa_isr.periodicidad"],
            ondelete="CASCADE",
        ),
        _TABLA_ARGS,
    )

    ejercicio: Mapped[int] = mapped_column(Integer, primary_key=True)
    periodicidad: Mapped[PeriodicidadTarifa] = mapped_column(enum_column(PeriodicidadTarifa), primary_key=True)
    renglon: Mapped[int] = mapped_column(Integer, primary_key=True)
    limite_inferior: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    limite_superior: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cuota_fija: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tasa_excedente: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
```

Añadir `ForeignKeyConstraint` a los imports de `sqlalchemy` del módulo.

- [ ] **Step 3: Escribir la migración a mano**

`--autogenerate` emite `op.drop_index` para índices compuestos que respaldan llaves foráneas y MySQL lo
rechaza con el error 1553 (está documentado en `f92d4a1c7b06`). Se escribe a mano.

Crear `alembic/versions/<hash>_add_tarifa_isr.py` con `down_revision = "a1d93f27e5b8"` (la cabeza actual;
verificar con `alembic heads` antes de escribirla) y un docstring que explique por qué la cabecera va
aparte de los renglones. El `upgrade`:

```python
def upgrade() -> None:
    op.create_table(
        "tarifa_isr",
        sa.Column("ejercicio", sa.Integer(), nullable=False),
        sa.Column(
            "periodicidad",
            sa.Enum("DIARIA", "DIAS_7", "DIAS_10", "DIAS_15", "MENSUAL", "EJERCICIO", name="periodicidadtarifa"),
            nullable=False,
        ),
        sa.Column("origen", sa.Enum("IMPORTADA", "MANUAL", name="origentarifa"), nullable=False),
        sa.Column("fuente", sa.String(length=500), nullable=False),
        sa.Column("documento_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("encabezado", sa.String(length=1000), nullable=False),
        sa.Column("importado_en", sa.DateTime(), nullable=False),
        sa.Column("confirmado_por", sa.String(length=128), nullable=True),
        sa.Column("confirmado_en", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("ejercicio", "periodicidad"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_table(
        "tarifa_isr_renglon",
        sa.Column("ejercicio", sa.Integer(), nullable=False),
        sa.Column(
            "periodicidad",
            sa.Enum("DIARIA", "DIAS_7", "DIAS_10", "DIAS_15", "MENSUAL", "EJERCICIO", name="periodicidadtarifa"),
            nullable=False,
        ),
        sa.Column("renglon", sa.Integer(), nullable=False),
        sa.Column("limite_inferior", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("limite_superior", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("cuota_fija", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tasa_excedente", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["ejercicio", "periodicidad"],
            ["tarifa_isr.ejercicio", "tarifa_isr.periodicidad"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ejercicio", "periodicidad", "renglon"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    op.drop_table("tarifa_isr_renglon")
    op.drop_table("tarifa_isr")
```

- [ ] **Step 4: Correr el ciclo de migración de verdad**

No basta con escribirla. Contra el MySQL real:

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic downgrade -1
docker compose exec api alembic upgrade head
docker compose exec mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" hub_cfdi -e "SHOW COLUMNS FROM tarifa_isr; SHOW COLUMNS FROM tarifa_isr_renglon;"'
```

Esperado: los tres comandos sin error y las dos tablas con las columnas del Step 2. Si `downgrade` falla
por el orden de las tablas, se arregla en la migración, no se omite el ciclo.

- [ ] **Step 5: Sincronizar el DDL del doc 03 y commitear**

Agregar las dos tablas a `Hub_CFDI_docs/03-datos/03_modelo_de_datos.md` en la sección de configuración
fiscal, con la nota de por qué la cabecera va aparte.

```bash
.venv/bin/mypy --strict app
git add app/models/ alembic/versions/ Hub_CFDI_docs/03-datos/
git commit -m "feat(fiscal): tablas tarifa_isr y tarifa_isr_renglon"
```

---

### Task 2: Reglas puras de la tarifa

Este módulo no importa nada de SQLAlchemy ni de FastAPI. Lo consumen el extractor, el repositorio, la
comprobación y —más adelante— B-09.

**Files:**
- Create: `app/services/tarifa_isr.py`
- Test: `tests/test_tarifa_isr.py`

**Interfaces:**
- Consumes: `PeriodicidadTarifa` (Task 1).
- Produces:
  - `@dataclass(frozen=True) Renglon(renglon: int, limite_inferior: Decimal, limite_superior: Decimal | None, cuota_fija: Decimal, tasa_excedente: Decimal)`
  - `TarifaInvalida(ValueError)`
  - `validar(renglones: Sequence[Renglon]) -> None`
  - `huella(renglones: Sequence[Renglon]) -> str`
  - `renglon_para(renglones: Sequence[Renglon], base: Decimal) -> Renglon`
  - `isr_de(renglones: Sequence[Renglon], base: Decimal) -> Decimal`
  - `PARA_CFDI: Mapping[str, PeriodicidadTarifa | None]`
  - `DIAS_NOMINALES: Mapping[PeriodicidadTarifa, Decimal]`

- [ ] **Step 1: Write the failing test**

`tests/test_tarifa_isr.py`. Los renglones de las pruebas son los tres primeros y el último de la tarifa de
15 días del Anexo 8 de 2026 — valores reales, ya convertidos a fracción:

```python
"""Las reglas puras de una tarifa del ISR: qué la hace válida, cómo se identifica y cómo calcula.

Las seis pruebas de carga del Anexo I.1 del documento fuente viven en `validar`, y se corren tanto
al importar un PDF como al corregir un renglón a mano: es la única forma de que la corrección
manual no reintroduzca el error que el importador evita.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import PeriodicidadTarifa
from app.services import tarifa_isr as t


def _r(n: int, inf: str, sup: str | None, cuota: str, tasa: str) -> t.Renglon:
    return t.Renglon(
        renglon=n,
        limite_inferior=Decimal(inf),
        limite_superior=Decimal(sup) if sup is not None else None,
        cuota_fija=Decimal(cuota),
        tasa_excedente=Decimal(tasa),
    )


def _quincenal() -> list[t.Renglon]:
    """Tarifa de 15 días del Anexo 8 de 2026, con las tasas ya en fracción."""
    return [
        _r(1, "0.01", "416.70", "0.00", "0.0192"),
        _r(2, "416.71", "3537.15", "7.95", "0.0640"),
        _r(3, "3537.16", "6216.15", "207.75", "0.1088"),
        _r(4, "6216.16", "7225.95", "499.20", "0.1600"),
        _r(5, "7225.96", None, "660.75", "0.3500"),
    ]


def test_una_tarifa_real_es_valida() -> None:
    t.validar(_quincenal())


def test_el_primer_renglon_tiene_que_arrancar_en_un_centavo() -> None:
    malos = _quincenal()
    malos[0] = _r(1, "0.00", "416.70", "0.00", "0.0192")
    with pytest.raises(t.TarifaInvalida, match="0.01"):
        t.validar(malos)


def test_un_hueco_entre_renglones_se_rechaza_con_el_valor_esperado() -> None:
    malos = _quincenal()
    malos[3] = _r(4, "6216.00", "7225.95", "499.20", "0.1600")
    with pytest.raises(t.TarifaInvalida) as exc:
        t.validar(malos)
    # El mensaje tiene que decir el valor correcto, no solo que algo está mal.
    assert "6216.16" in str(exc.value) and "renglón 4" in str(exc.value)


def test_la_cuota_fija_del_primer_renglon_tiene_que_ser_cero() -> None:
    malos = _quincenal()
    malos[0] = _r(1, "0.01", "416.70", "1.00", "0.0192")
    with pytest.raises(t.TarifaInvalida, match="cuota fija"):
        t.validar(malos)


def test_las_tasas_tienen_que_crecer() -> None:
    malos = _quincenal()
    malos[2] = _r(3, "3537.16", "6216.15", "207.75", "0.0640")
    with pytest.raises(t.TarifaInvalida, match="crecer"):
        t.validar(malos)


def test_una_tasa_en_porcentaje_se_rechaza_diciendo_que_parece_porcentaje() -> None:
    """La prueba 6 del Anexo I.1: el error de escala es el que produce ISR cien veces mayor."""
    malos = [
        _r(1, "0.01", "416.70", "0.00", "1.92"),
        _r(2, "416.71", None, "7.95", "35.00"),
    ]
    with pytest.raises(t.TarifaInvalida, match="porcentaje"):
        t.validar(malos)


def test_la_ultima_tasa_tiene_que_caer_en_el_rango_publicado() -> None:
    malos = _quincenal()
    malos[-1] = _r(5, "7225.96", None, "660.75", "0.2500")
    with pytest.raises(t.TarifaInvalida, match="0.30"):
        t.validar(malos)


def test_solo_el_ultimo_renglon_puede_no_tener_limite_superior() -> None:
    malos = _quincenal()
    malos[2] = _r(3, "3537.16", None, "207.75", "0.1088")
    with pytest.raises(t.TarifaInvalida, match="En adelante"):
        t.validar(malos)


def test_una_tarifa_de_un_solo_renglon_es_una_extraccion_a_medias() -> None:
    with pytest.raises(t.TarifaInvalida, match="incompleta"):
        t.validar([_r(1, "0.01", None, "0.00", "0.3500")])


def test_la_huella_no_depende_de_la_escala_con_la_que_venga_el_decimal() -> None:
    """`Decimal("0.35")` y `Decimal("0.350000")` son el mismo valor: la huella tiene que coincidir,
    porque si no, quien confirma vería un 409 imposible de explicar."""
    a = _quincenal()
    b = _quincenal()
    b[-1] = _r(5, "7225.96", None, "660.7500", "0.35")
    assert t.huella(a) == t.huella(b)


def test_la_huella_cambia_si_cambia_una_cifra() -> None:
    a = _quincenal()
    b = _quincenal()
    b[1] = _r(2, "416.71", "3537.15", "8.95", "0.0640")
    assert t.huella(a) != t.huella(b)


def test_el_renglon_se_localiza_por_la_base() -> None:
    tarifa = _quincenal()
    assert t.renglon_para(tarifa, Decimal("0.01")).renglon == 1
    assert t.renglon_para(tarifa, Decimal("416.70")).renglon == 1
    assert t.renglon_para(tarifa, Decimal("416.71")).renglon == 2
    # El último renglón no tiene techo.
    assert t.renglon_para(tarifa, Decimal("999999.99")).renglon == 5


def test_una_base_por_debajo_del_primer_limite_es_un_error_de_configuracion_no_un_cero() -> None:
    """Anexo I.1: 'Si no hay renglón → error de configuración, NO cero'."""
    with pytest.raises(t.TarifaInvalida):
        t.renglon_para(_quincenal(), Decimal("0.00"))


def test_el_isr_es_cuota_fija_mas_el_excedente_por_la_tasa_redondeado_a_dos() -> None:
    # Renglón 3: cuota 207.75 + (5000.00 - 3537.16) * 0.1088 = 207.75 + 159.1569... = 366.91
    assert t.isr_de(_quincenal(), Decimal("5000.00")) == Decimal("366.91")


def test_el_mapa_de_periodicidades_del_cfdi_respeta_el_catalogo_del_sat() -> None:
    """`10` es Decenal y `06` es Bimestral en `c_PeriodicidadPago`, no al revés. El Anexo 8 no
    publica tarifa catorcenal ni bimestral, y decirlo con `None` es lo que permite avisar."""
    assert t.PARA_CFDI["04"] is PeriodicidadTarifa.DIAS_15
    assert t.PARA_CFDI["10"] is PeriodicidadTarifa.DIAS_10
    assert t.PARA_CFDI["02"] is PeriodicidadTarifa.DIAS_7
    assert t.PARA_CFDI["01"] is PeriodicidadTarifa.DIARIA
    assert t.PARA_CFDI["05"] is PeriodicidadTarifa.MENSUAL
    assert t.PARA_CFDI["03"] is None
    assert t.PARA_CFDI["06"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_tarifa_isr.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.tarifa_isr'`

- [ ] **Step 3: Escribir el módulo**

`app/services/tarifa_isr.py`:

```python
"""Reglas de una tarifa del ISR: qué la hace válida, cómo se identifica y cómo calcula.

**Módulo puro.** No importa SQLAlchemy ni FastAPI, así que se prueba sin base de datos y lo
pueden consumir el extractor del PDF, el repositorio, la comprobación con un recibo real y el
futuro informe B-09 sin que ninguno arrastre a los otros.

Las seis pruebas de carga del Anexo I.1 del documento fuente viven en `validar`, y se corren en
las dos puertas de escritura —importar un PDF y corregir un renglón a mano—. Validar solo el
renglón editado dejaría pasar el hueco que ese cambio abre con su vecino, que es la forma más
probable de romper una tarifa a mano.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from app.models.enums import PeriodicidadTarifa

_UN_CENTAVO: Final = Decimal("0.01")
_DOS_DECIMALES: Final = Decimal("0.01")
# Rango de la tasa marginal máxima publicada, prueba 5 del Anexo I.1. No es un margen de
# holgura: es el rango en el que la tasa tope ha vivido durante toda la vigencia de la LISR
# actual, y una tasa fuera de él significa que la tabla no es una tarifa de ISR o que la escala
# está equivocada.
_TASA_TOPE_MINIMA: Final = Decimal("0.30")
_TASA_TOPE_MAXIMA: Final = Decimal("0.40")


class TarifaInvalida(ValueError):
    """Una tarifa que no se puede aceptar. El mensaje dice qué renglón y qué se esperaba: un
    fallo al cargar es barato, un cálculo incorrecto tres meses después no."""


@dataclass(frozen=True)
class Renglon:
    """Un renglón de la tarifa. `limite_superior` nulo es el último ("En adelante").

    `tasa_excedente` es **fracción decimal** (`0.2136`), nunca porcentaje (`21.36`).
    """

    renglon: int
    limite_inferior: Decimal
    limite_superior: Decimal | None
    cuota_fija: Decimal
    tasa_excedente: Decimal


def validar(renglones: Sequence[Renglon]) -> None:
    """Las seis pruebas de carga del Anexo I.1, más tres que la práctica exige. Lanza
    `TarifaInvalida` con el primer problema encontrado, nombrando el renglón."""
    if len(renglones) < 2:
        raise TarifaInvalida(
            f"Esta tarifa salió con {len(renglones)} renglón(es), así que la extracción quedó incompleta. "
            "Una tarifa del ISR tiene varios tramos; con uno solo no se puede calcular nada."
        )

    en_porcentaje = [r for r in renglones if r.tasa_excedente >= Decimal(1)]
    if en_porcentaje:
        raise TarifaInvalida(
            f"La tasa del renglón {en_porcentaje[0].renglon} es {en_porcentaje[0].tasa_excedente}, que "
            "parece estar en porcentaje. Aquí se guarda como fracción: 21.36 % se escribe 0.2136. "
            "Guardarla en porcentaje multiplicaría el ISR por cien."
        )

    if renglones[0].limite_inferior != _UN_CENTAVO:
        raise TarifaInvalida(
            f"El primer renglón debe empezar en 0.01 y empieza en {renglones[0].limite_inferior}. "
            "Así lo publica el SAT; si empieza en otro valor, falta el primer tramo de la tabla."
        )

    if renglones[0].cuota_fija != Decimal(0):
        raise TarifaInvalida(
            f"La cuota fija del primer renglón debe ser 0.00 y es {renglones[0].cuota_fija}. "
            "En el primer tramo no hay impuesto acumulado de tramos anteriores."
        )

    for anterior, actual in zip(renglones, renglones[1:], strict=False):
        if anterior.limite_superior is None:
            raise TarifaInvalida(
                f"El renglón {anterior.renglon} no tiene límite superior, pero no es el último. "
                "Solo el último renglón va sin techo (el que el SAT publica como 'En adelante')."
            )
        esperado = anterior.limite_superior + _UN_CENTAVO
        if actual.limite_inferior != esperado:
            raise TarifaInvalida(
                f"El renglón {actual.renglon} debe empezar exactamente un centavo después de donde "
                f"termina el {anterior.renglon}: {esperado}, y dice {actual.limite_inferior}. "
                "Sin eso quedan ingresos que no caen en ningún tramo."
            )
        if actual.tasa_excedente <= anterior.tasa_excedente:
            raise TarifaInvalida(
                f"La tasa del renglón {actual.renglon} ({actual.tasa_excedente}) no es mayor que la del "
                f"{anterior.renglon} ({anterior.tasa_excedente}). En una tarifa del ISR las tasas siempre "
                "crecen: si no lo hacen, hay un renglón mal capturado o dos tablas mezcladas."
            )

    ultimo = renglones[-1]
    if ultimo.limite_superior is not None:
        raise TarifaInvalida(
            f"El último renglón ({ultimo.renglon}) tiene límite superior {ultimo.limite_superior}, y debe "
            "ir sin techo: es el que el SAT publica como 'En adelante'. Con techo, un sueldo por encima "
            "de él no caería en ningún tramo."
        )
    if not (_TASA_TOPE_MINIMA <= ultimo.tasa_excedente <= _TASA_TOPE_MAXIMA):
        raise TarifaInvalida(
            f"La tasa del último renglón es {ultimo.tasa_excedente} y debería estar entre "
            f"{_TASA_TOPE_MINIMA} y {_TASA_TOPE_MAXIMA}. Fuera de ese rango, esta tabla no es una tarifa "
            "del ISR o las tasas están en otra escala."
        )


def huella(renglones: Sequence[Renglon]) -> str:
    """SHA-256 de la forma canónica de los renglones. Identifica **lo que alguien revisó**, para
    que confirmar rechace una tarifa que cambió mientras se miraba.

    Los decimales se normalizan a la escala de la columna porque `Decimal("0.35")` y
    `Decimal("0.350000")` son el mismo valor pero distinto texto, y quien confirma no tiene que
    adivinar con cuántos ceros se lo devolvió la base — el mismo argumento que ya está escrito en
    `configuracion_fiscal.confirmar_param_fiscal`.
    """
    lineas = [
        "|".join(
            (
                str(r.renglon),
                str(r.limite_inferior.quantize(Decimal("0.01"))),
                "" if r.limite_superior is None else str(r.limite_superior.quantize(Decimal("0.01"))),
                str(r.cuota_fija.quantize(Decimal("0.01"))),
                str(r.tasa_excedente.quantize(Decimal("0.000001"))),
            )
        )
        for r in sorted(renglones, key=lambda r: r.renglon)
    ]
    return hashlib.sha256("\n".join(lineas).encode()).hexdigest()


def renglon_para(renglones: Sequence[Renglon], base: Decimal) -> Renglon:
    """El renglón que le toca a una base gravable (Anexo I.1).

    Si ninguno aplica lanza en vez de devolver el primero: *"Si no hay renglón → error de
    configuración, NO cero"*. Un cero silencioso aquí se convierte en "este empleado no causa
    ISR", que es indistinguible de un cálculo correcto.
    """
    for r in sorted(renglones, key=lambda r: r.renglon):
        if base >= r.limite_inferior and (r.limite_superior is None or base <= r.limite_superior):
            return r
    raise TarifaInvalida(
        f"Ninguno de los {len(renglones)} renglones de esta tarifa aplica a una base de {base}. "
        "Es un problema de la tarifa cargada, no del recibo."
    )


def isr_de(renglones: Sequence[Renglon], base: Decimal) -> Decimal:
    """`cuota_fija + ⌊(base − limite_inferior) × tasa⌉₂` (Anexo I.2). **No resta subsidio**: eso
    es otro paso, con su propia configuración."""
    r = renglon_para(renglones, base)
    marginal = ((base - r.limite_inferior) * r.tasa_excedente).quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)
    return r.cuota_fija + marginal


# Traducción del catálogo `c_PeriodicidadPago` del CFDI a la tarifa que publica el Anexo 8.
# `None` significa "el Anexo no publica tarifa para esta periodicidad", y es información que la
# pantalla usa para avisarlo en vez de dejar un hueco (B-09.R1 la resuelve proporcionando la
# mensual y rotulándolo).
#
# Ojo con `06` y `10`: en `c_PeriodicidadPago` el **06 es Bimestral** y el **10 es Decenal**
# (verificado contra `C75b_c_PeriodicidadPago` de satcfdi). Es fácil intercambiarlos.
PARA_CFDI: Final[Mapping[str, PeriodicidadTarifa | None]] = {
    "01": PeriodicidadTarifa.DIARIA,
    "02": PeriodicidadTarifa.DIAS_7,
    "03": None,  # Catorcenal: el Anexo no la publica.
    "04": PeriodicidadTarifa.DIAS_15,
    "05": PeriodicidadTarifa.MENSUAL,
    "06": None,  # Bimestral: el Anexo no la publica.
    "07": None,  # Unidad de obra
    "08": None,  # Comisión
    "09": None,  # Precio alzado
    "10": PeriodicidadTarifa.DIAS_10,
    "99": None,  # Otra periodicidad
}

# Días que cubre cada tarifa. Se usa para elegir un recibo "limpio" en la comprobación: un recibo
# cuyos días pagados coincidan con los nominales no arrastra prorrateos que expliquen una
# diferencia y confundan la lectura.
DIAS_NOMINALES: Final[Mapping[PeriodicidadTarifa, Decimal]] = {
    PeriodicidadTarifa.DIARIA: Decimal(1),
    PeriodicidadTarifa.DIAS_7: Decimal(7),
    PeriodicidadTarifa.DIAS_10: Decimal(10),
    PeriodicidadTarifa.DIAS_15: Decimal(15),
    PeriodicidadTarifa.MENSUAL: Decimal(30),
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_tarifa_isr.py -v`
Expected: PASS, 16 pruebas.

- [ ] **Step 5: Verificar por mutación que la prueba de escala protege**

Cambiar en `validar` el umbral `r.tasa_excedente >= Decimal(1)` por `>= Decimal(100)` y correr:

```bash
.venv/bin/pytest tests/test_tarifa_isr.py -k "porcentaje" -v
```

Esperado: **FAIL**, y el encabezado de pytest debe decir que seleccionó 1 prueba (no "0 selected"; un
`-k` que no casa sale con código 5 y se ve igual que una prueba muerta). Revertir la mutación y confirmar
que vuelve a pasar.

- [ ] **Step 6: Commit**

```bash
.venv/bin/mypy --strict app
git add app/services/tarifa_isr.py tests/test_tarifa_isr.py
git commit -m "feat(fiscal): reglas puras de la tarifa del ISR — validacion, huella y formula"
```

---

### Task 3: El extractor del Anexo 8

**Files:**
- Create: `app/services/anexo8.py`
- Create: `tests/fixtures/anexo8-2026.pdf`
- Test: `tests/test_anexo8.py`
- Modify: `pyproject.toml`, `requirements.txt` (`pypdfium2` pasa a dependencia de la aplicación)

**Interfaces:**
- Consumes: `Renglon`, `validar`, `TarifaInvalida` (Task 2); `PeriodicidadTarifa` (Task 1).
- Produces:
  - `@dataclass(frozen=True) TarifaExtraida(ejercicio: int, periodicidad: PeriodicidadTarifa, encabezado: str, renglones: tuple[Renglon, ...])`
  - `DocumentoInvalido(ValueError)`
  - `extraer(pdf: bytes) -> list[TarifaExtraida]`
  - `MAXIMO_BYTES: int = 10 * 1024 * 1024`, `MAXIMO_PAGINAS: int = 100`

- [ ] **Step 1: Bajar el documento oficial como fixture**

```bash
mkdir -p tests/fixtures
curl -sSL -o tests/fixtures/anexo8-2026.pdf \
  "https://www.sat.gob.mx/minisitio/NormatividadRMFyRGCE/documentos2026/rmf/anexos/Anexo-8-RMF-2026_DOF-28122025.pdf"
sha256sum tests/fixtures/anexo8-2026.pdf
```

Esperado: `69ebaf8a78a3bde5d631ad2a994e81ec6d07e2d4e39085c8c948d138f782c1f4`. Si no coincide, **detenerse**:
el archivo cambió o la descarga se corrompió, y las pruebas de este plan están escritas contra ese
contenido exacto. Es un documento público del DOF, sin datos de terceros ni personales, así que se versiona
(regla 12).

- [ ] **Step 2: Write the failing test**

`tests/test_anexo8.py`:

```python
"""El extractor de tarifas del Anexo 8, contra el documento oficial real.

Las pruebas se escriben contra el **PDF completo**, no contra un fragmento recortado con solo las
tablas buenas: "semilla limpia donde el mundo real tiene datos sucios" fue la clase de defecto que
más se repitió en la fase 3 de informes. Este documento trae, de verdad, las tres trampas que el
extractor tiene que sortear: encabezados duplicados en el índice, un pie de página a media tabla y
tarifas que no son de nómina con exactamente la misma forma.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.models.enums import PeriodicidadTarifa
from app.services import anexo8
from app.services import tarifa_isr as t

ANEXO_2026 = Path(__file__).parent / "fixtures" / "anexo8-2026.pdf"


@pytest.fixture(scope="module")
def extraidas() -> list[anexo8.TarifaExtraida]:
    return anexo8.extraer(ANEXO_2026.read_bytes())


def test_del_anexo_real_salen_las_siete_tarifas_de_sueldos(extraidas: list[anexo8.TarifaExtraida]) -> None:
    """Cinco periodicidades del ejercicio 2026, más la anual de 2026 y la de 2025."""
    claves = {(x.ejercicio, x.periodicidad) for x in extraidas}
    assert claves == {
        (2026, PeriodicidadTarifa.DIARIA),
        (2026, PeriodicidadTarifa.DIAS_7),
        (2026, PeriodicidadTarifa.DIAS_10),
        (2026, PeriodicidadTarifa.DIAS_15),
        (2026, PeriodicidadTarifa.MENSUAL),
        (2026, PeriodicidadTarifa.EJERCICIO),
        (2025, PeriodicidadTarifa.EJERCICIO),
    }


def test_el_ejercicio_sale_del_encabezado_de_cada_tabla_no_del_documento(
    extraidas: list[anexo8.TarifaExtraida],
) -> None:
    """El Anexo 8 de 2026 trae la tarifa anual del ejercicio **2025** en su rubro C.I. Tomar el año
    del archivo la guardaría como de 2026, y las seis pruebas no lo detectarían: las dos tablas son
    internamente coherentes. Es el error más peligroso de todo el importador."""
    anuales = {x.ejercicio for x in extraidas if x.periodicidad is PeriodicidadTarifa.EJERCICIO}
    assert anuales == {2025, 2026}


def test_la_tarifa_quincenal_coincide_renglon_por_renglon_con_el_documento(
    extraidas: list[anexo8.TarifaExtraida],
) -> None:
    q = next(x for x in extraidas if x.periodicidad is PeriodicidadTarifa.DIAS_15 and x.ejercicio == 2026)
    assert len(q.renglones) == 11
    assert q.renglones[0] == t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192"))
    assert q.renglones[1] == t.Renglon(
        2, Decimal("416.71"), Decimal("3537.15"), Decimal("7.95"), Decimal("0.0640")
    )
    # El renglón 6 va justo después del pie de página del DOF que el PDF intercala a media tabla.
    assert q.renglones[5] == t.Renglon(
        6, Decimal("8651.41"), Decimal("17448.75"), Decimal("916.20"), Decimal("0.2136")
    )
    assert q.renglones[-1] == t.Renglon(
        11, Decimal("210020.71"), None, Decimal("65866.05"), Decimal("0.3500")
    )


def test_el_pie_de_pagina_del_dof_no_corta_la_tabla(extraidas: list[anexo8.TarifaExtraida]) -> None:
    """'Domingo 28 de diciembre de 2025 DIARIO OFICIAL' aparece entre el renglón 5 y el 6 de la
    tarifa quincenal. Si el extractor se detuviera ahí, la tarifa saldría con 5 renglones, fallaría
    la prueba de continuidad y quien la sube vería un error falso sobre un PDF correcto."""
    q = next(x for x in extraidas if x.periodicidad is PeriodicidadTarifa.DIAS_15 and x.ejercicio == 2026)
    t.validar(list(q.renglones))


def test_ninguna_tarifa_extraida_es_de_las_que_no_son_de_nomina(
    extraidas: list[anexo8.TarifaExtraida],
) -> None:
    """El rubro A.I (enajenación de inmuebles) y las de los arts. 106 y 116 tienen la misma forma de
    cuatro columnas. El ancla exige el fundamento citado, así que ninguna entra."""
    for x in extraidas:
        assert "126" not in x.encabezado
        assert "106 de la Ley del ISR" not in x.encabezado
        assert "116" not in x.encabezado


def test_el_encabezado_del_indice_no_produce_una_tarifa_vacia(
    extraidas: list[anexo8.TarifaExtraida],
) -> None:
    """Cada encabezado aparece dos veces en el documento: en el 'Contenido' de la página 1 y sobre
    su tabla. La ocurrencia del índice no tiene renglones detrás, y si contara, habría 14 tarifas
    (siete de ellas vacías) en vez de 7."""
    assert len(extraidas) == 7
    assert all(len(x.renglones) >= 2 for x in extraidas)


def test_todas_las_tarifas_extraidas_pasan_la_validacion(extraidas: list[anexo8.TarifaExtraida]) -> None:
    for x in extraidas:
        t.validar(list(x.renglones))


def test_las_tasas_quedan_en_fraccion_no_en_porcentaje(extraidas: list[anexo8.TarifaExtraida]) -> None:
    """El Anexo publica 21.36 y la columna guarda 0.2136. La división entre 100 ocurre en un solo
    lugar de todo el sistema y esta prueba es la que lo vigila (B-09.R2)."""
    for x in extraidas:
        assert all(r.tasa_excedente < Decimal(1) for r in x.renglones)
        assert Decimal("0.30") <= x.renglones[-1].tasa_excedente <= Decimal("0.40")


def test_un_pdf_sin_texto_se_rechaza_diciendo_que_parece_escaneo() -> None:
    # PDF mínimo válido de una página, sin objetos de texto.
    vacio = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    with pytest.raises(anexo8.DocumentoInvalido, match="escaneo"):
        anexo8.extraer(vacio)


def test_un_pdf_que_no_es_el_anexo_8_no_importa_nada_y_dice_que_esperaba() -> None:
    """Se le pasa un PDF real del propio repositorio que no es el Anexo 8."""
    otro = Path(__file__).parent.parent / "docs" / "superpowers" / "specs" / "2026-08-10-tarifa-isr-design.md"
    with pytest.raises(anexo8.DocumentoInvalido, match="Anexo 8"):
        anexo8.extraer(otro.read_bytes())


def test_un_archivo_mas_grande_que_el_limite_se_rechaza_antes_de_abrirlo() -> None:
    with pytest.raises(anexo8.DocumentoInvalido, match="grande"):
        anexo8.extraer(b"x" * (anexo8.MAXIMO_BYTES + 1))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_anexo8.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.anexo8'`

- [ ] **Step 4: Escribir el extractor**

`app/services/anexo8.py`:

```python
"""Extrae las tarifas de sueldos del PDF del Anexo 8 de la Resolución Miscelánea Fiscal.

**Módulo puro:** recibe bytes y devuelve tarifas. No toca la base ni la red.

Por qué esto no contradice la doctrina de `sincronizacion_fiscal`
----------------------------------------------------------------
Ese módulo argumenta —y sigue vigente— que no se raspan fuentes oficiales, porque un raspador que
falla devuelve otra cosa y el resultado es un valor fiscal viejo con cara de vigente. Aquí hay dos
diferencias que acotan esa regla en vez de romperla:

1. **La tarifa se auto-verifica.** Las seis pruebas del Anexo I.1 (`tarifa_isr.validar`) la
   contradicen aritméticamente si la extracción se corrompe. Una UMA mal leída es un número
   plausible y no hay redundancia interna que la delate.
2. **El documento lo aporta una persona.** No hay URL que este código visite solo; hay un archivo
   que alguien subió deliberadamente y cuya huella se guarda.

Las tres trampas del documento real, verificadas contra el Anexo 8 de 2026
--------------------------------------------------------------------------
1. **Cada encabezado aparece dos veces**: en el "Contenido" de la primera página y sobre su tabla.
   La ocurrencia del índice no tiene renglones detrás. Por eso una ocurrencia solo cuenta si le
   sigue el bloque de columnas (`$ $ $ %`), y si no, se descarta en silencio: no es un error del
   documento, es su índice.
2. **El pie de página del DOF se intercala a media tabla** ("Domingo 28 de diciembre de 2025 DIARIO
   OFICIAL", entre los renglones 5 y 6 de la tarifa quincenal). Por eso los renglones se buscan por
   patrón y las líneas que no son cuatro números se ignoran, en vez de cortar la tabla ahí. Cortar
   produciría una tarifa incompleta que falla la validación, y el usuario vería un error falso sobre
   un documento correcto.
3. **Las tarifas que no son de nómina tienen la misma forma de cuatro columnas** (enajenación de
   inmuebles del art. 126, y las de los arts. 106 y 116). Por eso el ancla exige el **fundamento
   legal citado**, no la forma: es lo único que las distingue.

Y una cuarta, que es la más peligrosa porque las pruebas de validación no la ven: **un Anexo 8
contiene tarifas de dos ejercicios**. El de 2026 trae la anual del ejercicio 2025 en su rubro C.I.
El ejercicio se lee del encabezado de cada tabla, nunca del nombre del archivo ni del año de la RMF.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

import pypdfium2

from app.models.enums import PeriodicidadTarifa
from app.services import tarifa_isr

MAXIMO_BYTES: Final = 10 * 1024 * 1024
MAXIMO_PAGINAS: Final = 100

# Cuánto texto puede haber entre el encabezado y su bloque de columnas. El más largo del documento
# real deja ~200 caracteres; 600 da holgura sin llegar al encabezado siguiente.
_MARGEN_HASTA_COLUMNAS: Final = 600


class DocumentoInvalido(ValueError):
    """El archivo no sirve como Anexo 8. El mensaje se le muestra a una persona: dice qué se
    esperaba y qué hacer, no qué falló por dentro."""


@dataclass(frozen=True)
class TarifaExtraida:
    ejercicio: int
    periodicidad: PeriodicidadTarifa
    encabezado: str
    renglones: tuple[tarifa_isr.Renglon, ...]


@dataclass(frozen=True)
class _Ancla:
    periodicidad: PeriodicidadTarifa
    patron: re.Pattern[str]


def _sin_acentos(texto: str) -> str:
    """Quita los acentos para que el ancla no se rompa por una tilde perdida en la extracción.
    Los números de artículo se siguen exigiendo literales: son lo que distingue una tarifa de
    sueldos de una de arrendamiento."""
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


# Anclas: periodicidad + fundamento, ambos exigidos. Se escriben sin acentos porque el texto se
# normaliza antes de buscar. `.{0,160}?` absorbe los saltos de línea que el PDF mete a media frase.
_ANCLAS: Final[tuple[_Ancla, ...]] = (
    _Ancla(
        PeriodicidadTarifa.DIARIA,
        re.compile(
            r"cantidad de trabajo realizado.{0,160}?correspondiente a (?P<ejercicio>\d{4}),?"
            r".{0,60}?calculada en dias.{0,160}?96 de la Ley del ISR y 175 de su Reglamento",
            re.S,
        ),
    ),
    _Ancla(
        PeriodicidadTarifa.DIAS_7,
        re.compile(
            r"periodo de 7 dias,?.{0,60}?correspondiente a (?P<ejercicio>\d{4})"
            r".{0,160}?96 de la Ley del ISR y 175 de su Reglamento",
            re.S,
        ),
    ),
    _Ancla(
        PeriodicidadTarifa.DIAS_10,
        re.compile(
            r"periodo de 10 dias,?.{0,60}?correspondiente a (?P<ejercicio>\d{4})"
            r".{0,160}?96 de la Ley del ISR y 175 de su Reglamento",
            re.S,
        ),
    ),
    _Ancla(
        PeriodicidadTarifa.DIAS_15,
        re.compile(
            r"periodo de 15 dias,?.{0,60}?correspondiente a (?P<ejercicio>\d{4})"
            r".{0,160}?96 de la Ley del ISR y 175 de su Reglamento",
            re.S,
        ),
    ),
    _Ancla(
        PeriodicidadTarifa.MENSUAL,
        re.compile(
            r"Tarifa aplicable durante (?P<ejercicio>\d{4}) para el calculo de los pagos provisionales "
            r"mensuales.{0,160}?96 de la Ley del ISR y 175 de su Reglamento",
            re.S,
        ),
    ),
    _Ancla(
        PeriodicidadTarifa.EJERCICIO,
        re.compile(
            r"impuesto correspondiente al ejercicio de (?P<ejercicio>\d{4})"
            r".{0,160}?97 y 152 de la Ley del ISR",
            re.S,
        ),
    ),
)

# Encabezado de columnas de cualquier tabla del Anexo. Marca dónde empiezan los renglones y, sobre
# todo, distingue una tabla de verdad de su mención en el índice.
_COLUMNAS: Final = re.compile(r"\$ \$ \$ %")

# Un renglón: límite inferior, límite superior (o "En adelante"), cuota fija y porcentaje.
_RENGLON: Final = re.compile(
    r"(?P<inferior>\d[\d,]*\.\d{2}) (?P<superior>\d[\d,]*\.\d{2}|En adelante) "
    r"(?P<cuota>\d[\d,]*\.\d{2}) (?P<tasa>\d{1,2}\.\d{2})"
)


def _texto_plano(pdf: bytes) -> str:
    """Todo el PDF como una sola cadena, sin acentos, con espacios colapsados.

    Se aplana a una línea a propósito: el PDF corta las frases del encabezado con saltos, así que
    buscar por línea obligaría a reconstruirlas. Los renglones se recuperan igual porque se buscan
    por patrón, no por posición.
    """
    if len(pdf) > MAXIMO_BYTES:
        raise DocumentoInvalido(
            f"El archivo es más grande de lo que debería ({len(pdf) // 1024 // 1024} MB; el Anexo 8 pesa "
            "menos de 1 MB). ¿Es el archivo correcto?"
        )
    try:
        documento = pypdfium2.PdfDocument(pdf)
    except Exception as exc:  # pypdfium2 lanza tipos propios; cualquiera significa lo mismo aquí
        raise DocumentoInvalido(
            "No pude abrir este archivo como PDF. Descarga el Anexo 8 del portal del SAT y súbelo tal cual."
        ) from exc
    if len(documento) > MAXIMO_PAGINAS:
        raise DocumentoInvalido(
            f"El archivo trae {len(documento)} páginas y el Anexo 8 trae menos de {MAXIMO_PAGINAS}. "
            "¿Es el archivo correcto?"
        )
    crudo = "\n".join(documento[i].get_textpage().get_text_range() for i in range(len(documento)))
    if len(crudo.strip()) < 500:
        raise DocumentoInvalido(
            "Este PDF no tiene texto, parece un escaneo o una foto. Descarga el archivo del portal del "
            "SAT en vez de una copia escaneada."
        )
    return re.sub(r"\s+", " ", _sin_acentos(crudo))


def _renglones_desde(texto: str, inicio: int) -> tuple[tarifa_isr.Renglon, ...]:
    """Los renglones consecutivos a partir de `inicio`, hasta el que dice "En adelante".

    "En adelante" es el delimitador porque el último renglón de toda tarifa del Anexo lo lleva. Sin
    él haría falta adivinar dónde termina la tabla, y el encabezado siguiente no siempre está cerca.
    """
    renglones: list[tarifa_isr.Renglon] = []
    for numero, m in enumerate(_RENGLON.finditer(texto, inicio), start=1):
        superior = None if m.group("superior") == "En adelante" else Decimal(m.group("superior").replace(",", ""))
        renglones.append(
            tarifa_isr.Renglon(
                renglon=numero,
                limite_inferior=Decimal(m.group("inferior").replace(",", "")),
                limite_superior=superior,
                cuota_fija=Decimal(m.group("cuota").replace(",", "")),
                # El único lugar de todo el sistema donde se divide entre 100.
                tasa_excedente=Decimal(m.group("tasa")) / Decimal(100),
            )
        )
        if superior is None:
            break
    return tuple(renglones)


def extraer(pdf: bytes) -> list[TarifaExtraida]:
    """Las tarifas de sueldos del documento. Lanza `DocumentoInvalido` si no hay ninguna.

    Cada tarifa extraída pasa `tarifa_isr.validar` aquí mismo: si una falla, **no se devuelve
    ninguna**. Un Anexo 8 a medio cargar deja un estado que después nadie sabe interpretar, porque
    no se distingue de un documento que legítimamente traía menos tablas.
    """
    texto = _texto_plano(pdf)
    encontradas: list[TarifaExtraida] = []

    for ancla in _ANCLAS:
        for m in ancla.patron.finditer(texto):
            ventana = texto[m.end() : m.end() + _MARGEN_HASTA_COLUMNAS]
            columnas = _COLUMNAS.search(ventana)
            if columnas is None:
                # La mención del índice: no tiene tabla detrás. No es un error del documento.
                continue
            renglones = _renglones_desde(texto, m.end() + columnas.end())
            if not renglones:
                continue
            tarifa_isr.validar(list(renglones))
            encontradas.append(
                TarifaExtraida(
                    ejercicio=int(m.group("ejercicio")),
                    periodicidad=ancla.periodicidad,
                    encabezado=" ".join(m.group(0).split())[:1000],
                    renglones=renglones,
                )
            )

    if not encontradas:
        raise DocumentoInvalido(
            "No encontré ninguna tarifa de sueldos en este archivo. Debe ser el Anexo 8 de la Resolución "
            "Miscelánea Fiscal (busca 'Anexo 8' y el año en el portal del SAT). No se cargó nada."
        )
    return encontradas
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_anexo8.py -v`
Expected: PASS, 11 pruebas. Si `test_del_anexo_real_salen_las_siete_tarifas_de_sueldos` encuentra más de
7, sobra una ocurrencia del índice: revisar que `_COLUMNAS` sea obligatorio. Si encuentra menos, un ancla
no casó: imprimir `texto[:2000]` para ver cómo quedó normalizado antes de tocar los patrones.

- [ ] **Step 6: Mover `pypdfium2` a dependencia de la aplicación**

Hoy está solo en el entorno de desarrollo. Ahora corre en producción dentro del contenedor.

En `pyproject.toml`, en `dependencies`, junto a `openpyxl`: `"pypdfium2>=4,<5"`. Agregar la línea
equivalente a `requirements.txt` con la versión exacta que devuelva
`.venv/bin/pip show pypdfium2 | grep Version`. Y añadir `"pypdfium2.*"` a la lista de módulos sin tipos
del bloque `[[tool.mypy.overrides]]` si mypy se queja.

Reconstruir la imagen para que el contenedor la tenga:

```bash
docker compose build api worker && docker compose up -d
docker compose exec api python -c "import pypdfium2; print(pypdfium2.__version__)"
```

- [ ] **Step 7: Commit**

```bash
.venv/bin/mypy --strict app
git add app/services/anexo8.py tests/test_anexo8.py tests/fixtures/anexo8-2026.pdf pyproject.toml requirements.txt
git commit -m "feat(fiscal): extractor de tarifas del Anexo 8 anclado en el fundamento citado"
```

---

### Task 4: Persistencia — guardar, leer, confirmar, borrar

**Files:**
- Create: `app/repositories/tarifa_isr.py`
- Test: `tests/test_repositorio_tarifa_isr.py`

**Interfaces:**
- Consumes: `TarifaIsr`, `TarifaIsrRenglon`, `PeriodicidadTarifa`, `OrigenTarifa` (Task 1);
  `Renglon`, `validar`, `huella`, `TarifaInvalida` (Task 2); `TarifaExtraida` (Task 3).
- Produces:
  - `@dataclass(frozen=True) TarifaGuardada(ejercicio, periodicidad, origen, fuente, documento_sha256, encabezado, importado_en, confirmado_por, confirmado_en, renglones: tuple[Renglon, ...])`
    con propiedades `huella: str` y `confirmada: bool`
  - `CorreccionManualProtegida(Exception)`, `ValorCambio(Exception)`, `NoEncontrada(Exception)`,
    `YaConfirmada(Exception)`
  - `async guardar_importadas(db, extraidas: Sequence[TarifaExtraida], *, fuente: str, sha256: str) -> list[TarifaGuardada]`
  - `async guardar_manual(db, *, ejercicio: int, periodicidad: PeriodicidadTarifa, renglones: Sequence[Renglon], fuente: str) -> TarifaGuardada`
  - `async listar(db) -> list[TarifaGuardada]`
  - `async obtener(db, *, ejercicio, periodicidad) -> TarifaGuardada | None`
  - `async vigente(db, *, ejercicio, periodicidad) -> TarifaGuardada | None` (solo confirmadas)
  - `async confirmar(db, *, ejercicio, periodicidad, huella_revisada: str, actor: str) -> tuple[TarifaGuardada, bool]`
  - `async borrar(db, *, ejercicio, periodicidad) -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_repositorio_tarifa_isr.py`. La tabla de cinco casos del §5.5 del diseño es el corazón:

```python
"""Persistencia de las tarifas: el invariante de confirmación y los cinco casos de reimportación.

El caso que estas pruebas fijan y que es fácil de romper: **reimportar un documento cuyos renglones
cambiaron limpia la confirmación**, y reimportar sobre una corrección manual no pisa nada.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrigenTarifa, PeriodicidadTarifa
from app.repositories import tarifa_isr as repo
from app.services import anexo8
from app.services import tarifa_isr as t

SHA_A = "a" * 64
SHA_B = "b" * 64


def _renglones(cuota_segundo: str = "7.95") -> list[t.Renglon]:
    return [
        t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
        t.Renglon(2, Decimal("416.71"), Decimal("3537.15"), Decimal(cuota_segundo), Decimal("0.0640")),
        t.Renglon(3, Decimal("3537.16"), None, Decimal("207.75"), Decimal("0.3500")),
    ]


def _extraida(cuota_segundo: str = "7.95") -> anexo8.TarifaExtraida:
    return anexo8.TarifaExtraida(
        ejercicio=2026,
        periodicidad=PeriodicidadTarifa.DIAS_15,
        encabezado="IV. Tarifa aplicable cuando hagan pagos que correspondan a un periodo de 15 dias",
        renglones=tuple(_renglones(cuota_segundo)),
    )


async def test_lo_importado_entra_sin_confirmar(db: AsyncSession) -> None:
    guardadas = await repo.guardar_importadas(db, [_extraida()], fuente="Anexo 8 DOF 28-12-2025", sha256=SHA_A)
    await db.commit()
    assert len(guardadas) == 1
    assert guardadas[0].confirmado_en is None
    assert guardadas[0].origen is OrigenTarifa.IMPORTADA
    assert guardadas[0].documento_sha256 == SHA_A
    assert await repo.vigente(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15) is None


async def test_reimportar_el_mismo_documento_es_idempotente(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    antes = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert antes is not None

    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    despues = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert despues is not None
    assert despues.huella == antes.huella
    assert len(despues.renglones) == 3


async def test_reimportar_con_los_mismos_renglones_conserva_la_confirmacion(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella,
        actor="dgarcia@planjuarez.org",
    )
    await db.commit()

    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_B)
    await db.commit()
    despues = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert despues is not None
    assert despues.confirmado_por == "dgarcia@planjuarez.org"


async def test_reimportar_con_renglones_distintos_limpia_la_confirmacion(db: AsyncSession) -> None:
    """Regla 2 de `guardar_param_fiscal`: un valor distinto es un valor nuevo y necesita que alguien
    lo vuelva a mirar. Si no, una resolución posterior activaría cifras que nadie revisó."""
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="quien",
    )
    await db.commit()

    await repo.guardar_importadas(db, [_extraida(cuota_segundo="8.95")], fuente="f", sha256=SHA_B)
    await db.commit()
    despues = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert despues is not None
    assert despues.confirmado_en is None
    assert despues.confirmado_por is None
    assert despues.renglones[1].cuota_fija == Decimal("8.95")


async def test_reimportar_sobre_una_correccion_manual_no_pisa_nada(db: AsyncSession) -> None:
    await repo.guardar_manual(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=_renglones("8.95"),
        fuente="corregido a mano",
    )
    await db.commit()

    with pytest.raises(repo.CorreccionManualProtegida):
        await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.rollback()

    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    assert fila.renglones[1].cuota_fija == Decimal("8.95")
    assert fila.origen is OrigenTarifa.MANUAL


async def test_corregir_a_mano_limpia_la_confirmacion_y_marca_el_origen(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="quien",
    )
    await db.commit()

    await repo.guardar_manual(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=_renglones("8.95"),
        fuente="corregido a mano",
    )
    await db.commit()
    despues = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert despues is not None
    assert despues.origen is OrigenTarifa.MANUAL
    assert despues.confirmado_en is None


async def test_una_correccion_que_rompe_la_continuidad_se_rechaza(db: AsyncSession) -> None:
    malos = _renglones()
    malos[2] = t.Renglon(3, Decimal("3537.00"), None, Decimal("207.75"), Decimal("0.3500"))
    with pytest.raises(t.TarifaInvalida, match="3537.16"):
        await repo.guardar_manual(
            db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=malos, fuente="x",
        )


async def test_corregir_puede_quitar_y_agregar_renglones(db: AsyncSession) -> None:
    """Un ejercicio futuro puede traer otro número de renglones; sin esto la corrección serviría
    de poco. El `PUT` recibe la lista completa, así que quitar es no mandarlo."""
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()

    dos = [
        t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
        t.Renglon(2, Decimal("416.71"), None, Decimal("7.95"), Decimal("0.3500")),
    ]
    await repo.guardar_manual(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=dos, fuente="x",
    )
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    assert len(fila.renglones) == 2


async def test_confirmar_con_una_huella_que_ya_no_corresponde_se_rechaza(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    with pytest.raises(repo.ValorCambio):
        await repo.confirmar(
            db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15,
            huella_revisada="0" * 64, actor="quien",
        )


async def test_confirmar_dos_veces_es_idempotente_y_no_reescribe_quien_confirmo(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    _, cambio_primero = await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="primera",
    )
    await db.commit()
    segunda, cambio_segundo = await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="segunda",
    )
    await db.commit()
    assert cambio_primero is True
    assert cambio_segundo is False
    assert segunda.confirmado_por == "primera"


async def test_una_tarifa_confirmada_la_devuelve_vigente(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="quien",
    )
    await db.commit()
    viva = await repo.vigente(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert viva is not None
    assert len(viva.renglones) == 3


async def test_borrar_una_tarifa_confirmada_se_rechaza(db: AsyncSession) -> None:
    """Un borrado que hace desaparecer una tarifa confirmada sin sustituto convierte un cálculo que
    funcionaba en un cálculo ausente, sin explicación."""
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="quien",
    )
    await db.commit()
    with pytest.raises(repo.YaConfirmada):
        await repo.borrar(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)


async def test_borrar_una_propuesta_se_lleva_sus_renglones(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    await repo.borrar(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    await db.commit()
    assert await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15) is None


async def test_guardar_importadas_es_todo_o_nada(db: AsyncSession) -> None:
    """Si una de las tarifas del documento no se puede guardar, no se guarda ninguna: un Anexo 8 a
    medio cargar no se distingue de uno que traía menos tablas."""
    buena = _extraida()
    protegida = anexo8.TarifaExtraida(
        ejercicio=2026, periodicidad=PeriodicidadTarifa.MENSUAL, encabezado="V. Tarifa mensual",
        renglones=tuple(_renglones()),
    )
    await repo.guardar_manual(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.MENSUAL, renglones=_renglones("8.95"), fuente="mano",
    )
    await db.commit()

    with pytest.raises(repo.CorreccionManualProtegida):
        await repo.guardar_importadas(db, [buena, protegida], fuente="f", sha256=SHA_A)
    await db.rollback()

    # La buena tampoco quedó.
    assert await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_repositorio_tarifa_isr.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.repositories.tarifa_isr'`

- [ ] **Step 3: Escribir el repositorio**

`app/repositories/tarifa_isr.py`. Puntos que no se pueden omitir:

- `guardar_importadas` **no hace `commit`**: quien llama escribe la bitácora en la misma transacción y
  commitea (regla 8). Lanzar a media iteración deja la transacción sucia y el `rollback` de quien llama
  la limpia — de ahí que el "todo o nada" salga gratis, pero hay que **validar las protecciones de todas
  las tarifas antes de escribir la primera**, para que el mensaje de error nombre la tarifa protegida y no
  la que se estaba escribiendo.
- La lectura de la cabecera usa `with_for_update()`, por el mismo motivo que
  `guardar_param_fiscal`: sin candado, dos importaciones simultáneas del mismo documento no se ven.
- Los renglones se reemplazan con un `DELETE` del rango completo y un `INSERT` de la lista nueva. No se
  intenta un diff renglón por renglón: la lista es corta y un diff parcial puede dejar un renglón viejo
  que rompe la continuidad.
- `listar` y `obtener` hacen **dos consultas** (cabeceras y renglones) y arman los dataclasses en
  memoria. No hay `relationship` con lazy loading: sería un N+1 por tarifa (regla 11).

```python
"""Persistencia de las tarifas del ISR. Todo lo que decide *si* un dato es aceptable vive en
`app.services.tarifa_isr`; aquí solo se escribe y se lee.

**Ninguna función de escritura confirma.** `confirmar` es la única que toca `confirmado_por` y
`confirmado_en`, y exige la huella de lo que se revisó.

Ninguna función hace `commit`: quien llama escribe la bitácora en la misma transacción (regla 8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion_fiscal import TarifaIsr, TarifaIsrRenglon
from app.models.enums import OrigenTarifa, PeriodicidadTarifa
from app.services import anexo8
from app.services import tarifa_isr as reglas

_LARGO_CONFIRMADO_POR = 128


class CorreccionManualProtegida(Exception):
    """Se intentó importar encima de una tarifa corregida a mano. No se pisa nada."""


class ValorCambio(Exception):
    """La tarifa cambió entre que alguien la revisó y le dio confirmar."""


class NoEncontrada(Exception):
    """No hay tarifa para ese ejercicio y periodicidad."""


class YaConfirmada(Exception):
    """La operación (borrar) no se permite sobre una tarifa confirmada."""


@dataclass(frozen=True)
class TarifaGuardada:
    ejercicio: int
    periodicidad: PeriodicidadTarifa
    origen: OrigenTarifa
    fuente: str
    documento_sha256: str | None
    encabezado: str
    importado_en: datetime
    confirmado_por: str | None
    confirmado_en: datetime | None
    renglones: tuple[reglas.Renglon, ...]

    @property
    def huella(self) -> str:
        return reglas.huella(list(self.renglones))

    @property
    def confirmada(self) -> bool:
        return self.confirmado_en is not None
```

La función donde vive lo delicado, completa:

```python
async def _escribir(
    db: AsyncSession,
    *,
    ejercicio: int,
    periodicidad: PeriodicidadTarifa,
    renglones: Sequence[reglas.Renglon],
    origen: OrigenTarifa,
    fuente: str,
    sha256: str | None,
    encabezado: str,
) -> TarifaGuardada:
    """Única puerta de escritura. Valida, decide si la confirmación sobrevive, reemplaza los
    renglones.

    **Se valida la tarifa completa**, no el renglón que cambió: editar un `limite_superior` rompe la
    continuidad con su vecino, y validar solo lo editado dejaría pasar justo el hueco que ese cambio
    abrió.
    """
    reglas.validar(list(renglones))

    cabecera = await db.scalar(
        select(TarifaIsr)
        .where(TarifaIsr.ejercicio == ejercicio, TarifaIsr.periodicidad == periodicidad)
        .with_for_update()
    )
    huella_nueva = reglas.huella(list(renglones))

    if cabecera is None:
        cabecera = TarifaIsr(ejercicio=ejercicio, periodicidad=periodicidad)
        db.add(cabecera)
    else:
        anteriores = await _leer_renglones(db, ejercicio=ejercicio, periodicidad=periodicidad)
        if reglas.huella(anteriores) != huella_nueva:
            # Una cifra distinta es una tarifa nueva y necesita que alguien la vuelva a mirar. Sin
            # esto, una resolución posterior del SAT activaría cifras que nadie revisó.
            cabecera.confirmado_por = None
            cabecera.confirmado_en = None

    cabecera.origen = origen
    cabecera.fuente = fuente
    cabecera.documento_sha256 = sha256
    cabecera.encabezado = encabezado
    cabecera.importado_en = _ahora()

    # Reemplazo completo, no diff renglón por renglón: la lista es corta y un diff parcial puede
    # dejar vivo un renglón viejo que rompe la continuidad sin que nada lo note.
    await db.execute(
        delete(TarifaIsrRenglon).where(
            TarifaIsrRenglon.ejercicio == ejercicio,
            TarifaIsrRenglon.periodicidad == periodicidad,
        )
    )
    await db.flush()
    for r in renglones:
        db.add(
            TarifaIsrRenglon(
                ejercicio=ejercicio,
                periodicidad=periodicidad,
                renglon=r.renglon,
                limite_inferior=r.limite_inferior,
                limite_superior=r.limite_superior,
                cuota_fija=r.cuota_fija,
                tasa_excedente=r.tasa_excedente,
            )
        )
    await db.flush()
    return _a_dataclass(cabecera, list(renglones))
```

El resto del módulo: `_ahora()` (UTC, como `configuracion_fiscal._ahora`), `_a_dataclass(cabecera, filas)`,
`_leer_renglones(db, *, ejercicio, periodicidad) -> list[reglas.Renglon]` ordenado por `renglon`, y las
públicas listadas en **Interfaces**. `listar` hace **dos** consultas —todas las cabeceras y todos los
renglones— y agrupa en memoria: una por tarifa sería un N+1 (regla 11).

`guardar_importadas` en dos pasadas:

```python
async def guardar_importadas(
    db: AsyncSession, extraidas: Sequence[anexo8.TarifaExtraida], *, fuente: str, sha256: str
) -> list[TarifaGuardada]:
    """Guarda todas las tarifas de un documento, o ninguna.

    Primera pasada: comprobar que ninguna choca con una corrección manual. Segunda: escribir. Sin la
    primera pasada, el mensaje de error nombraría la tarifa que se estaba escribiendo en vez de la
    protegida, y quien lo lee no sabría qué renglón corrigió a mano.
    """
    for extraida in extraidas:
        existente = await obtener(db, ejercicio=extraida.ejercicio, periodicidad=extraida.periodicidad)
        if existente is not None and existente.origen is OrigenTarifa.MANUAL:
            if existente.huella != reglas.huella(list(extraida.renglones)):
                raise CorreccionManualProtegida(
                    f"Corregiste a mano la tarifa {extraida.periodicidad.value} de {extraida.ejercicio} y el "
                    "documento dice otra cosa. No la sobreescribí. Si el documento nuevo es el bueno, "
                    "descarta la tarifa y vuelve a importar."
                )

    return [
        await _escribir(
            db,
            ejercicio=e.ejercicio,
            periodicidad=e.periodicidad,
            renglones=e.renglones,
            origen=OrigenTarifa.IMPORTADA,
            fuente=fuente,
            sha256=sha256,
            encabezado=e.encabezado,
        )
        for e in extraidas
    ]
```

`confirmar` sigue literalmente el patrón de `configuracion_fiscal.confirmar_param_fiscal`: `FOR UPDATE`,
compara la huella, es idempotente y **no reescribe** `confirmado_por` al reconfirmar (sería borrar el
rastro de quien sí la revisó).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_repositorio_tarifa_isr.py -v`
Expected: PASS, 14 pruebas.

- [ ] **Step 5: Verificar por mutación que la limpieza de confirmación protege**

En `_escribir`, quitar la línea que pone `confirmado_por = None` / `confirmado_en = None` cuando la huella
cambia, y correr:

```bash
.venv/bin/pytest tests/test_repositorio_tarifa_isr.py -k "renglones_distintos_limpia" -v
```

Esperado: **FAIL**, con 1 prueba seleccionada. Revertir.

- [ ] **Step 6: Commit**

```bash
.venv/bin/mypy --strict app
git add app/repositories/tarifa_isr.py tests/test_repositorio_tarifa_isr.py
git commit -m "feat(fiscal): persistencia de tarifas del ISR con los cinco casos de reimportacion"
```

---

### Task 5: La comprobación con un recibo real

Es lo que permite confirmar con fundamento sin ser contador, y **cierra el único hueco que las 6 pruebas
no cubren**: una tabla coherente pero del ejercicio o la periodicidad equivocada.

**Files:**
- Create: `app/services/comprobacion_tarifa.py`
- Test: `tests/test_comprobacion_tarifa.py`

**Interfaces:**
- Consumes: `Renglon`, `isr_de`, `renglon_para`, `PARA_CFDI`, `DIAS_NOMINALES` (Task 2);
  `TarifaGuardada` (Task 4); modelos `Nomina`, `NominaReceptor`, `NominaTotales`, `NominaDeduccion`,
  `Comprobante`, `ComprobanteDetalle`.
- Produces:
  - `@dataclass(frozen=True) Comprobacion(uuid, fecha_inicial_pago, fecha_final_pago, num_empleado, dias_pagados, gravado, renglon, limite_inferior, tasa_excedente, isr_calculado, isr_timbrado, diferencia, advertencias: tuple[str, ...])`
  - `async comprobar(db, *, tarifa: TarifaGuardada) -> Comprobacion | None`

- [ ] **Step 1: Write the failing test**

`tests/test_comprobacion_tarifa.py`. `tests/helpers_nomina.insertar_nomina` ya inserta un CFDI de nómina
normalizado completo (comprobante + complemento + `comprobante_detalle`); su firma relevante aquí es
`insertar_nomina(db, *, empresa_id, uuid, periodicidad="04", tipo_nomina="O", dias="15.000",
deducciones=[(tipo, clave, concepto, importe)], total_gravado=None, estatus=..., error_normalizacion=None,
fecha_pago=date(2026, 6, 30))`.

```python
"""La comprobación de una tarifa contra un recibo real.

Su propósito no es auditar al patrón: es detectar un **error de carga**. Una tarifa del ejercicio o
de la periodicidad equivocada es aritméticamente coherente —pasa las seis pruebas del Anexo I.1— y
solo se delata al aplicarla a un recibo de verdad. Eso es lo que fija
`test_la_tarifa_anual_aplicada_a_un_recibo_quincenal_da_una_diferencia_enorme`, que es la razón de
existir de este módulo.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EstatusCfdi, OrigenTarifa, PeriodicidadTarifa
from app.repositories.tarifa_isr import TarifaGuardada
from app.services import comprobacion_tarifa
from app.services import tarifa_isr as t
from tests import factories
from tests.helpers_nomina import insertar_nomina

# Tarifa de 15 días del Anexo 8 de 2026 (los cinco primeros renglones bastan para estas pruebas,
# con el quinto abierto para que valide).
QUINCENAL = (
    t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
    t.Renglon(2, Decimal("416.71"), Decimal("3537.15"), Decimal("7.95"), Decimal("0.0640")),
    t.Renglon(3, Decimal("3537.16"), Decimal("6216.15"), Decimal("207.75"), Decimal("0.1088")),
    t.Renglon(4, Decimal("6216.16"), Decimal("7225.95"), Decimal("499.20"), Decimal("0.1600")),
    t.Renglon(5, Decimal("7225.96"), None, Decimal("660.75"), Decimal("0.3500")),
)

# Tarifa del ejercicio (anual): mismos tramos multiplicados por 24, para que sea internamente
# coherente igual que la real. Es la tabla equivocada que las 6 pruebas no pueden detectar.
ANUAL = (
    t.Renglon(1, Decimal("0.01"), Decimal("10000.80"), Decimal("0.00"), Decimal("0.0192")),
    t.Renglon(2, Decimal("10000.81"), Decimal("84891.60"), Decimal("190.80"), Decimal("0.0640")),
    t.Renglon(3, Decimal("84891.61"), None, Decimal("4986.00"), Decimal("0.3500")),
)


def _tarifa(renglones: tuple[t.Renglon, ...], periodicidad: PeriodicidadTarifa) -> TarifaGuardada:
    return TarifaGuardada(
        ejercicio=2026,
        periodicidad=periodicidad,
        origen=OrigenTarifa.IMPORTADA,
        fuente="Anexo 8 DOF 28-12-2025",
        documento_sha256="a" * 64,
        encabezado="IV. Tarifa aplicable cuando hagan pagos que correspondan a un periodo de 15 dias",
        importado_en=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        confirmado_por=None,
        confirmado_en=None,
        renglones=renglones,
    )


async def _empresa(db: AsyncSession) -> int:
    empresa = await factories.crear_empresa(db, nombre="Empresa de prueba", rfc="CHL960913IX9")
    return empresa.empresa_id


async def test_elige_un_recibo_ordinario_no_uno_extraordinario(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="11111111-1111-4111-8111-111111111111", tipo_nomina="E",
        total_gravado="50000.00", deducciones=[("002", "002", "ISR", "9000.00")],
    )
    await insertar_nomina(
        db, empresa_id=eid, uuid="22222222-2222-4222-8222-222222222222", tipo_nomina="O",
        total_gravado="5000.00", deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.uuid == "22222222-2222-4222-8222-222222222222"


async def test_prefiere_el_recibo_con_los_dias_nominales_y_no_advierte(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="33333333-3333-4333-8333-333333333333", dias="9.000",
        total_gravado="3000.00", deducciones=[("002", "002", "ISR", "100.00")],
    )
    await insertar_nomina(
        db, empresa_id=eid, uuid="44444444-4444-4444-8444-444444444444", dias="15.000",
        total_gravado="5000.00", deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.uuid == "44444444-4444-4444-8444-444444444444"
    assert hecha.advertencias == ()


async def test_si_no_hay_recibo_limpio_usa_el_que_haya_y_explica_por_que_difiere(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="55555555-5555-4555-8555-555555555555", dias="9.000",
        total_gravado="3000.00", deducciones=[("002", "002", "ISR", "100.00")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert any("prorrateado" in a for a in hecha.advertencias)


async def test_el_gravado_sale_del_cfdi_y_no_de_las_marcas_de_percepcion(db: AsyncSession) -> None:
    """`catalogo_percepcion_marca` está vacío en esta prueba, como está en la base real: las 44
    marcas siguen sin confirmar. Si la comprobación derivara la base de ellas, saldría vacía justo
    la primera vez que alguien carga una tarifa, que es cuando más se necesita."""
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="66666666-6666-4666-8666-666666666666",
        total_gravado="5000.00", deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.gravado == Decimal("5000.00")


async def test_el_isr_timbrado_sale_de_la_deduccion_002(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="77777777-7777-4777-8777-777777777777", total_gravado="5000.00",
        deducciones=[("004", "004", "Otra deduccion", "500.00"), ("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.isr_timbrado == Decimal("366.91")


async def test_una_tarifa_correcta_da_una_diferencia_de_pesos(db: AsyncSession) -> None:
    """Renglón 3: 207.75 + (5000.00 − 3537.16) × 0.1088 = 366.91, que es lo timbrado."""
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="88888888-8888-4888-8888-888888888888", total_gravado="5000.00",
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.renglon == 3
    assert hecha.isr_calculado == Decimal("366.91")
    assert abs(hecha.diferencia) <= Decimal("1.00")


async def test_la_tarifa_anual_aplicada_a_un_recibo_quincenal_da_una_diferencia_enorme(
    db: AsyncSession,
) -> None:
    """**La prueba que justifica este módulo.** La tarifa anual es internamente coherente y pasa las
    seis pruebas del Anexo I.1; lo único que la delata es aplicarla a un recibo real. Si esta prueba
    pasara con una diferencia pequeña, la comprobación no estaría cerrando ningún hueco."""
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="99999999-9999-4999-8999-999999999999", periodicidad="05",
        dias="30.000", total_gravado="10000.00", deducciones=[("002", "002", "ISR", "1000.00")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(ANUAL, PeriodicidadTarifa.EJERCICIO))
    assert hecha is not None
    assert abs(hecha.diferencia) > hecha.isr_timbrado * 10
    # Y lo dice, para que nadie lea la diferencia como un hallazgo sobre el patrón.
    assert any("anual" in a.lower() for a in hecha.advertencias)


async def test_sin_recibos_de_nomina_devuelve_None(db: AsyncSession) -> None:
    """Una base sin nómina no rompe la pantalla: el panel dirá que no hay recibos con los que
    comprobar, que es distinto de que la tarifa esté mal."""
    await _empresa(db)
    await db.commit()
    assert await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15)) is None


async def test_no_toma_recibos_cancelados_ni_con_error_de_normalizacion(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", estatus=EstatusCfdi.CANCELADO,
        total_gravado="5000.00", deducciones=[("002", "002", "ISR", "366.91")],
    )
    await insertar_nomina(
        db, empresa_id=eid, uuid="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        error_normalizacion="XML ilegible", total_gravado="5000.00",
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    assert await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_comprobacion_tarifa.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Escribir el servicio**

`app/services/comprobacion_tarifa.py`. El docstring del módulo tiene que decir las cuatro reglas del §7.3
del diseño. La consulta, en una sola sentencia con joins explícitos (regla 11):

```python
async def comprobar(db: AsyncSession, *, tarifa: TarifaGuardada) -> Comprobacion | None:
    """Aplica `tarifa` a un recibo real y devuelve los dos números lado a lado.

    **Usa el gravado que el propio CFDI declara** (`nomina_totales.total_gravado`), no una base
    recalculada desde `catalogo_percepcion_marca`: las 44 marcas están sin confirmar, así que una
    base derivada saldría vacía justo cuando más se necesita la comprobación —al cargar la tarifa por
    primera vez—. Es una aproximación consciente: si el recibo trae percepciones extraordinarias, la
    diferencia contra lo timbrado es esperada, y por eso se advierte en vez de callarlo.

    **No decide nada.** Quien confirma mira los dos números; el endpoint de confirmación no exige que
    cuadren, porque el ISR timbrado puede incluir subsidio al empleo, ajustes del periodo o el
    procedimiento del art. 174 del Reglamento, y exigir coincidencia bloquearía tarifas correctas.
    """
```

Selección del recibo, en este orden:

```sql
-- pseudocódigo de la consulta
SELECT n.*, nr.num_empleado, nr.periodicidad_pago, nt.total_gravado,
       (SELECT SUM(importe) FROM nomina_deduccion d
         WHERE d.comprobante_id = n.comprobante_id AND d.tipo_deduccion = '002') AS isr_timbrado
FROM nomina n
JOIN nomina_receptor nr ON nr.comprobante_id = n.comprobante_id
JOIN nomina_totales  nt ON nt.comprobante_id = n.comprobante_id
JOIN comprobantes    c  ON c.comprobante_id = n.comprobante_id
LEFT JOIN comprobante_detalle cd ON cd.comprobante_id = n.comprobante_id
WHERE c.estatus <> 'cancelado'
  AND (cd.error_normalizacion IS NULL)
  AND n.tipo_nomina = 'O'
  AND nr.periodicidad_pago = :periodicidad_cfdi   -- la que mapea a tarifa.periodicidad
  AND nt.total_gravado > 0
ORDER BY (n.num_dias_pagados = :dias_nominales) DESC,  -- primero los "limpios"
         n.fecha_pago DESC
LIMIT 1
```

`periodicidad_cfdi` se obtiene invirtiendo `reglas.PARA_CFDI` (la primera clave cuyo valor sea
`tarifa.periodicidad`). Si `tarifa.periodicidad is PeriodicidadTarifa.EJERCICIO`, la comprobación **no
tiene una periodicidad de recibo propia**: en ese caso se usa el recibo mensual más reciente y la
advertencia dice que la tarifa anual no se aplica a un recibo, así que la diferencia grande es esperada.
Eso es lo que hace que la prueba 7 pase por la razón correcta.

Las advertencias posibles, como constantes con su texto en español:
- `"Los días pagados del recibo ({dias}) no son los {nominales} de la periodicidad, así que el importe está prorrateado y la diferencia es esperada."`
- `"La tarifa anual no se aplica a un recibo individual; esta comparación solo sirve para ver que las cifras están en la escala correcta."`
- `"El recibo trae percepciones que no son sueldo ordinario, así que parte del gravado no debería entrar en este cálculo."` (cuando existe alguna percepción con tipo distinto de `001`)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_comprobacion_tarifa.py -v`
Expected: PASS, 9 pruebas.

- [ ] **Step 5: Commit**

```bash
.venv/bin/mypy --strict app
git add app/services/comprobacion_tarifa.py tests/test_comprobacion_tarifa.py
git commit -m "feat(fiscal): comprobar una tarifa contra un recibo real antes de confirmarla"
```

---

### Task 6: Endpoints

**Files:**
- Modify: `app/api/v1/schemas.py`
- Modify: `app/api/v1/configuracion.py`
- Test: `tests/test_api_tarifa_isr.py`
- Modify: `Hub_CFDI_docs/05-api/05_contrato_api.md` (§8bis)

**Interfaces:**
- Consumes: todo lo de las tareas 3, 4 y 5.
- Produces: los cinco endpoints del §7.1 del diseño y los esquemas `TarifaIsrOut`, `TarifaIsrRenglonIn`,
  `TarifaIsrRenglonOut`, `TarifaIsrCorregirIn`, `TarifaIsrConfirmarIn`, `ComprobacionOut`,
  `ImportacionTarifasOut`.

- [ ] **Step 1: Write the failing test**

`tests/test_api_tarifa_isr.py`, siguiendo el estilo de `tests/test_api_configuracion.py` (leerlo primero
para reutilizar sus fixtures de cliente autenticado como admin). Las pruebas:

1. `test_importar_el_anexo_real_deja_siete_propuestas` — `POST` multipart con
   `tests/fixtures/anexo8-2026.pdf`; 200, `len(tarifas) == 7`, todas con `confirmada: false`.
2. `test_importar_escribe_bitacora_en_la_misma_transaccion` — hay un renglón de `bitacora` por tarifa con
   `entidad = "tarifa_isr:2026/DIAS_15"` y acción `importar_tarifa_isr`.
3. `test_un_operador_no_puede_importar` — con un usuario `rol_global='operador'`, 403. La configuración
   fiscal es de administrador.
4. `test_un_archivo_que_no_es_el_anexo_devuelve_422_con_mensaje_en_espanol` — el `detail.mensaje` contiene
   "Anexo 8" y **no** contiene "DocumentoInvalido".
5. `test_un_archivo_mayor_al_limite_devuelve_413` — 11 MB de basura; el mensaje dice el tamaño esperado.
6. `test_corregir_un_renglon_limpia_la_confirmacion_y_deja_origen_manual` — `PUT` con la lista completa;
   la respuesta trae `origen: "MANUAL"`, `confirmada: false` y `difiere_del_documento: true`.
7. `test_corregir_con_un_hueco_devuelve_422_diciendo_el_valor_esperado` — el mensaje contiene el valor
   correcto.
8. `test_confirmar_con_la_huella_correcta_activa_la_tarifa` — 200 y `confirmada: true`.
9. `test_confirmar_con_una_huella_vieja_devuelve_409` — `codigo: "TARIFA_CAMBIO"`.
10. `test_reimportar_sobre_una_correccion_manual_devuelve_409` — `codigo: "CORRECCION_MANUAL"`, y la
    corrección sigue en pie.
11. `test_borrar_una_propuesta_la_quita_y_borrar_una_confirmada_da_409`.
12. `test_listar_incluye_la_comprobacion_y_la_periodicidad_que_aplica` — el `GET` trae, por tarifa,
    `aplica_a_la_nomina: true` solo en la que corresponde a la periodicidad observada, y la comprobación
    de la Task 5 cuando hay recibos.
13. `test_listar_avisa_cuando_la_nomina_usa_una_periodicidad_sin_tarifa_publicada` — con un recibo
    catorcenal (`03`), la respuesta trae `periodicidades_sin_tarifa: ["03"]`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_api_tarifa_isr.py -v`
Expected: FAIL con 404 en todas las rutas (los endpoints no existen).

- [ ] **Step 3: Escribir los esquemas**

En `app/api/v1/schemas.py`, junto a los de configuración fiscal. Los importes viajan como **cadena**, no
como float, igual que `ParamFiscalOut` (un float pierde precisión y la huella dejaría de coincidir):

```python
class TarifaIsrRenglonOut(BaseModel):
    renglon: int
    limite_inferior: str
    limite_superior: str | None
    cuota_fija: str
    # La fracción que se guarda y calcula.
    tasa_excedente: str
    # El mismo número como lo publica el SAT y como lo lee un contador. Se envía calculado por el
    # servidor para que la pantalla no tenga que multiplicar por 100 y arriesgar un error de
    # presentación en el único número donde la escala importa.
    tasa_porcentaje: str


class TarifaIsrOut(BaseModel):
    ejercicio: int
    periodicidad: PeriodicidadTarifa
    # Etiqueta en el idioma de un recibo de nómina: "Quincenal (15 días)". Nunca el nombre del enum.
    etiqueta: str
    periodicidad_cfdi: str | None
    origen: OrigenTarifa
    fuente: str
    documento_sha256: str | None
    encabezado: str
    importado_en: datetime
    confirmado_por: str | None
    confirmado_en: datetime | None
    confirmada: bool
    difiere_del_documento: bool
    aplica_a_la_nomina: bool
    huella: str
    renglones: list[TarifaIsrRenglonOut]
    comprobacion: ComprobacionOut | None
```

`TarifaIsrRenglonIn` valida `limite_inferior`, `cuota_fija` y `tasa_excedente` como `Decimal` con
`max_digits`/`decimal_places` acordes a las columnas. `TarifaIsrConfirmarIn` lleva `huella: str`.

- [ ] **Step 4: Escribir los endpoints**

En `app/api/v1/configuracion.py`, después de los de `param_fiscal`. La traducción de excepción a HTTP:

| Excepción | HTTP | `codigo` |
|---|---|---|
| `anexo8.DocumentoInvalido` (tamaño o páginas) | 413 | `ARCHIVO_DEMASIADO_GRANDE` |
| `anexo8.DocumentoInvalido` (resto) | 422 | `DOCUMENTO_INVALIDO` |
| `tarifa_isr.TarifaInvalida` | 422 | `TARIFA_INVALIDA` |
| `repo.CorreccionManualProtegida` | 409 | `CORRECCION_MANUAL` |
| `repo.ValorCambio` | 409 | `TARIFA_CAMBIO` |
| `repo.YaConfirmada` | 409 | `TARIFA_CONFIRMADA` |
| `repo.NoEncontrada` | 404 | `TARIFA_NO_ENCONTRADA` |

En todos los casos `detail = {"codigo": ..., "mensaje": str(exc)}`, y `str(exc)` ya es el texto en español
llano que escribieron las tareas 2-4. **El nombre de la clase no aparece nunca en la respuesta.**

El `POST` de importación, completo, porque es donde se juntan las cuatro cosas (subida, extracción,
persistencia y bitácora):

```python
@router.post("/tarifa-isr/importar", response_model=ImportacionTarifasOut)
async def importar_tarifa_isr(
    archivo: UploadFile = File(..., description="PDF del Anexo 8 de la RMF, tal como lo publica el SAT."),
    admin: Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ImportacionTarifasOut:
    """Extrae las tarifas de sueldos del Anexo 8 y las deja **propuestas, sin confirmar**.

    Si cualquier tarifa del documento falla una validación no se guarda ninguna: un Anexo 8 a medio
    cargar no se distingue de uno que traía menos tablas.
    """
    contenido = await archivo.read()
    sha256 = hashlib.sha256(contenido).hexdigest()
    try:
        extraidas = anexo8.extraer(contenido)
    except anexo8.DocumentoInvalido as exc:
        # 413 solo cuando el archivo no cabe; el resto es un archivo que sí se pudo leer y no sirve.
        codigo, http = (
            ("ARCHIVO_DEMASIADO_GRANDE", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            if "grande" in str(exc) or "páginas" in str(exc)
            else ("DOCUMENTO_INVALIDO", status.HTTP_422_UNPROCESSABLE_ENTITY)
        )
        raise HTTPException(http, detail={"codigo": codigo, "mensaje": str(exc)}) from exc
    except reglas.TarifaInvalida as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"codigo": "TARIFA_INVALIDA", "mensaje": str(exc)}
        ) from exc

    fuente = f"{archivo.filename or 'Anexo 8'} (importado el {date.today().isoformat()})"
    try:
        guardadas = await repo.guardar_importadas(db, extraidas, fuente=fuente, sha256=sha256)
    except repo.CorreccionManualProtegida as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"codigo": "CORRECCION_MANUAL", "mensaje": str(exc)}
        ) from exc

    # Un renglón por tarifa: la entidad de la bitácora es la tarifa, que es la unidad que se confirma.
    for tarifa in guardadas:
        await bitacora_service.registrar(
            db,
            actor=admin.correo,
            accion="importar_tarifa_isr",
            entidad=f"tarifa_isr:{tarifa.ejercicio}/{tarifa.periodicidad.value}",
            detalle={
                "huella": tarifa.huella,
                "renglones": len(tarifa.renglones),
                "documento_sha256": sha256,
                "encabezado": tarifa.encabezado,
                "fuente": fuente,
            },
        )
    await db.commit()
    return await _importacion_a_salida(db, guardadas)
```

`_importacion_a_salida` es el helper que comparten el `GET` y el `POST`: arma `TarifaIsrOut` por tarifa
—con la etiqueta legible, `aplica_a_la_nomina` y la comprobación de la Task 5— más
`periodicidades_sin_tarifa`. Existe una sola vez para que la lista y la importación no puedan divergir en
lo que muestran.

La distinción de 413 por el texto del mensaje es frágil por naturaleza; la alternativa —dos excepciones
distintas en `anexo8`— es mejor si al implementar resulta incómoda. Lo importante es que el mensaje que
llega a la pantalla sea el del módulo, no uno reescrito aquí.

`fuente` se arma del nombre del archivo subido más la fecha de la petición: es la procedencia que verá
quien revise, y el nombre oficial (`Anexo-8-RMF-2026_DOF-28122025.pdf`) ya trae la fecha del DOF.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_tarifa_isr.py -v`
Expected: PASS, 13 pruebas.

- [ ] **Step 6: Actualizar el contrato del doc 05 y commitear**

Agregar los cinco endpoints a `Hub_CFDI_docs/05-api/05_contrato_api.md` §8bis, con la nota de que son de
administrador y de que la importación es multipart. Es la regla 10: el contrato se actualiza en la misma
sesión.

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest tests/test_api_tarifa_isr.py tests/test_api_configuracion.py -q
git add app/api/v1/ tests/test_api_tarifa_isr.py Hub_CFDI_docs/05-api/
git commit -m "feat(fiscal): endpoints para importar, corregir, confirmar y descartar tarifas del ISR"
```

---

### Task 7: Subsidio al empleo y UMA de 2025

No hay tablas nuevas ni endpoints nuevos: son cuatro claves más en el mecanismo de `param_fiscal` que ya
funciona. Las **cifras las valida el dueño del repo**; esta tarea solo las propone con su liga.

**Files:**
- Modify: `app/services/configuracion_fiscal.py` (`CLAVES_PARAM_FISCAL`)
- Modify: `app/services/sincronizacion_fiscal.py` (`FECHAS_DE_ACTUALIZACION`)
- Modify: `config/fiscal/param_fiscal.yaml`
- Modify: `config/fiscal/README.md`
- Modify: `apps/web/src/features/admin/ConfiguracionFiscalPage.tsx` (fichas del catálogo)
- Test: `tests/test_configuracion_fiscal.py` (añadir)

**Interfaces:**
- Produces: las claves `SUBSIDIO_FACTOR_UMA` y `SUBSIDIO_TOPE_INGRESO` aceptadas por
  `guardar_param_fiscal`, y tramos sembrados de `UMA_DIARIA`/`UMA_MENSUAL`/`UMA_ANUAL` para 2025.

- [ ] **Step 1: Write the failing test**

En `tests/test_configuracion_fiscal.py`:

```python
async def test_las_claves_del_subsidio_se_pueden_guardar(db: AsyncSession) -> None:
    """Sin estar en `CLAVES_PARAM_FISCAL` se rechazan, y el subsidio no se podría configurar."""
    fila = await cfg.guardar_param_fiscal(
        db, clave="SUBSIDIO_FACTOR_UMA", valor=Decimal("0.1502"), vigencia_desde=date(2026, 2, 1),
        origen=OrigenValor.SEMILLA, fuente="DOF 31-12-2025",
    )
    assert fila.confirmado_en is None


async def test_el_subsidio_de_enero_usa_el_tramo_de_enero(db: AsyncSession) -> None:
    """El factor cambia junto con la UMA, así que enero de 2026 tiene su propio tramo. Es lo que hace
    que un recibo de enero no se calcule con el factor de febrero."""
    db.add(_param("SUBSIDIO_FACTOR_UMA", "0.1559", date(2026, 1, 1), hasta=date(2026, 1, 31), confirmado=True))
    db.add(_param("SUBSIDIO_FACTOR_UMA", "0.1502", date(2026, 2, 1), confirmado=True))
    await db.commit()
    assert await cfg.valor_vigente(db, "SUBSIDIO_FACTOR_UMA", date(2026, 1, 20)) == Decimal("0.155900")
    assert await cfg.valor_vigente(db, "SUBSIDIO_FACTOR_UMA", date(2026, 2, 1)) == Decimal("0.150200")


async def test_la_uma_mensual_de_enero_de_2026_existe_tras_cargar_la_semilla(db: AsyncSession) -> None:
    """Sin la UMA de 2025 el subsidio de enero de 2026 no es calculable: `UMA_MENSUAL` solo arranca el
    1-feb-2026. Declararlo como limitación era una trampa para quien tiene que explicar por qué los
    recibos de enero no salen."""
    await cfg.cargar_desde_yaml(db, Path("config/fiscal/param_fiscal.yaml"))
    await db.commit()
    # Hay un tramo cuya vigencia cubre enero de 2026 (arranca en feb-2025 y cierra en ene-2026).
    tramo = await cfg._tramo(db, "UMA_MENSUAL", date(2026, 1, 15), confirmado=False)
    assert tramo is not None
```

El nombre exacto de la función de carga (`cargar_desde_yaml` arriba) hay que tomarlo de
`app/services/configuracion_fiscal.py`; el módulo ya expone el cargador que usa
`app/scripts/cargar_configuracion_fiscal.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_configuracion_fiscal.py -k "subsidio or uma_mensual_de_enero" -v`
Expected: FAIL — la primera con `ErrorDeConfiguracion: clave ... no es una clave conocida`. Verificar que
el encabezado de pytest diga que seleccionó 3 pruebas.

- [ ] **Step 3: Agregar las claves y sus fechas de actualización**

En `app/services/configuracion_fiscal.py`, en `CLAVES_PARAM_FISCAL`, añadir `"SUBSIDIO_FACTOR_UMA"` y
`"SUBSIDIO_TOPE_INGRESO"`, y en el comentario del docstring del módulo la línea de qué es cada una y de
dónde sale.

En `app/services/sincronizacion_fiscal.py`, en `FECHAS_DE_ACTUALIZACION`, añadir ambas con `(1, 1)`: el
decreto del subsidio se publica a fin de diciembre y aplica desde el 1 de enero.

**Nota para quien implemente:** `MODELO_SUBSIDIO` **no se agrega**, aunque el Anexo I.3 del documento
fuente la pide. `param_fiscal.valor` es `Numeric(18,6)` y una etiqueta `'TABLA'`/`'MONTO_FIJO'` no cabe;
el modelo se deriva de qué configuración existe. Está declarado como divergencia en §8 y §14 del diseño —
no volver a proponerlo.

- [ ] **Step 4: Sembrar los valores en el YAML**

En `config/fiscal/param_fiscal.yaml`, agregar a la lista de claves esperadas del encabezado las dos nuevas
y, en los datos, cuatro tramos. **Valores a proponer, para que David los valide contra la liga** (van
entrecomillados: sin comillas el YAML los lee como float y pierde precisión):

```yaml
  # Subsidio al empleo. Modelo de monto fijo vigente desde la reforma de 2024: el subsidio mensual
  # es un porcentaje de la UMA mensual, y solo lo tiene quien no excede un tope de ingreso.
  # REVISAR: las dos cifras y las dos vigencias las valida un contador contra el decreto. El factor
  # cambia junto con la UMA, así que enero lleva su propio tramo.
  - clave: SUBSIDIO_FACTOR_UMA
    valor: "0.1559"
    vigencia_desde: 2026-01-01
    vigencia_hasta: 2026-01-31
    ejercicio: 2026
    fuente: "DOF 31-12-2025, decreto del subsidio para el empleo — factor aplicable en enero de 2026 (sobre la UMA de 2025). https://www.dof.gob.mx/"
  - clave: SUBSIDIO_FACTOR_UMA
    valor: "0.1502"
    vigencia_desde: 2026-02-01
    ejercicio: 2026
    fuente: "DOF 31-12-2025, decreto del subsidio para el empleo — factor sobre la UMA mensual desde el 1-feb-2026. https://www.dof.gob.mx/"
  - clave: SUBSIDIO_TOPE_INGRESO
    valor: "11492.66"
    vigencia_desde: 2026-01-01
    ejercicio: 2026
    fuente: "DOF 31-12-2025, decreto del subsidio para el empleo — ingreso mensual máximo para tener derecho al subsidio. https://www.dof.gob.mx/"
```

Y los tres tramos de la UMA de 2025, **cerrados el 31 de enero de 2026** para que no se solapen con los de
2026 que ya están cargados (los tramos no se cierran solos, a propósito). Los valores de la UMA 2025 se
toman del boletín del INEGI y se citan en `fuente` con su liga; quien implemente **no los inventa**: los
copia del boletín, y si no puede abrirlo, deja la tarea abierta y lo dice en vez de poner una cifra
aproximada.

- [ ] **Step 5: Cargar la semilla y ver que no confirma nada**

```bash
docker compose exec api python -m app.scripts.cargar_configuracion_fiscal config/fiscal/param_fiscal.yaml
docker compose exec mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" hub_cfdi -e "SELECT clave, valor, vigencia_desde, vigencia_hasta, confirmado_en FROM param_fiscal ORDER BY clave, vigencia_desde;"'
```

Esperado: los tramos nuevos con `confirmado_en` en `NULL`, los cinco valores ya confirmados intactos, y
ningún solapamiento (si el cargador se queja de solapamiento, el tramo de la UMA 2025 no quedó cerrado).

- [ ] **Step 6: Las fichas de la pantalla, en lenguaje llano**

En `ConfiguracionFiscalPage.tsx`, en el objeto `CATALOGO`, agregar las dos claves con etiqueta y ayuda:

```ts
  SUBSIDIO_FACTOR_UMA: {
    grupo: GRUPO_SUBSIDIO,
    etiqueta: 'Subsidio al empleo — porcentaje de la UMA mensual',
    ayuda:
      'El subsidio mensual es este porcentaje de la UMA mensual. Cambia por decreto, normalmente a fin de año, ' +
      'y su valor de enero es distinto porque la UMA cambia el 1 de febrero.',
  },
  SUBSIDIO_TOPE_INGRESO: {
    grupo: GRUPO_SUBSIDIO,
    etiqueta: 'Ingreso mensual máximo para tener derecho al subsidio',
    ayuda:
      'Quien gana más de esta cantidad al mes no tiene subsidio al empleo. Sin este valor confirmado no se ' +
      'puede saber si un subsidio de cero en un recibo es correcto o es un error.',
  },
```

con `const GRUPO_SUBSIDIO = 'Subsidio al empleo';` añadido a `ORDEN_GRUPOS`. Las claves de las fichas
existentes (`grupo`, `etiqueta`, `ayuda`) hay que copiarlas de la definición real de `FichaClave`, que
puede tener otros campos.

- [ ] **Step 7: Run tests and commit**

```bash
.venv/bin/pytest tests/test_configuracion_fiscal.py -v
.venv/bin/mypy --strict app
cd apps/web && npm run typecheck && cd ..
git add app/services/configuracion_fiscal.py app/services/sincronizacion_fiscal.py config/fiscal/ tests/test_configuracion_fiscal.py apps/web/src/features/admin/ConfiguracionFiscalPage.tsx
git commit -m "feat(fiscal): subsidio al empleo y UMA de 2025 como configuracion propuesta"
```

---

### Task 8: La alarma de vigencia de la tarifa

**Files:**
- Modify: `app/services/sincronizacion_fiscal.py`
- Test: `tests/test_automatizaciones.py` (o donde vivan las pruebas de `alertas_de_vigencia`; buscarlas
  con `grep -rn "alertas_de_vigencia" tests/`)

**Interfaces:**
- Consumes: `repo.listar` (Task 4), `PARA_CFDI` (Task 2).
- Produces: `CLAVE_TARIFA_ISR: Final = "TARIFA_ISR"` y las alertas correspondientes desde
  `alertas_de_vigencia`.

- [ ] **Step 1: Write the failing test**

```python
async def test_alerta_cuando_el_ejercicio_en_curso_no_tiene_tarifa_confirmada(db: AsyncSession) -> None:
    """Con nómina quincenal en la BD y sin tarifa de 15 días confirmada, la alarma tiene que sonar."""
    # ... sembrar un CFDI de nómina quincenal (helpers_nomina) ...
    alertas = await sincronizacion.alertas_de_vigencia(db, date(2026, 8, 10))
    tarifa = [a for a in alertas if a.clave == sincronizacion.CLAVE_TARIFA_ISR]
    assert len(tarifa) == 1
    assert tarifa[0].motivo == "AUSENTE"
    # El detalle dice qué hacer, no solo qué falta.
    assert "Anexo 8" in (tarifa[0].detalle or "")


async def test_la_alerta_dice_sin_confirmar_cuando_hay_propuesta(db: AsyncSession) -> None:
    # ... nómina quincenal + tarifa DIAS_15 importada sin confirmar ...
    alertas = await sincronizacion.alertas_de_vigencia(db, date(2026, 8, 10))
    assert [a.motivo for a in alertas if a.clave == sincronizacion.CLAVE_TARIFA_ISR] == ["SIN_CONFIRMAR"]


async def test_no_alerta_por_periodicidades_que_nadie_usa(db: AsyncSession) -> None:
    """Con solo nómina quincenal y la tarifa de 15 días confirmada, no hay alerta — aunque falten las
    otras cinco. Una alarma siempre encendida es una alarma que se aprende a ignorar."""
    # ... nómina quincenal + DIAS_15 confirmada ...
    alertas = await sincronizacion.alertas_de_vigencia(db, date(2026, 8, 10))
    assert not [a for a in alertas if a.clave == sincronizacion.CLAVE_TARIFA_ISR]


async def test_sin_nomina_no_hay_alerta_de_tarifa(db: AsyncSession) -> None:
    """No hay nada que recalcular, así que no hay nada que exigir."""
    alertas = await sincronizacion.alertas_de_vigencia(db, date(2026, 8, 10))
    assert not [a for a in alertas if a.clave == sincronizacion.CLAVE_TARIFA_ISR]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ -k "alerta and tarifa" -v`
Expected: FAIL con `AttributeError: module ... has no attribute 'CLAVE_TARIFA_ISR'`. Verificar que
seleccionó 4 pruebas.

- [ ] **Step 3: Implementar**

En `app/services/sincronizacion_fiscal.py`:

```python
CLAVE_TARIFA_ISR: Final = "TARIFA_ISR"
```

y una función privada que `alertas_de_vigencia` llama:

```python
async def _alertas_de_tarifa(db: AsyncSession, hoy: date) -> list[Alerta]:
    """Falta la tarifa del ejercicio en curso para alguna periodicidad **que la nómina realmente
    timbra**.

    Solo las observadas, no las seis. Exigir la tarifa de 10 días que ninguna empresa usa dejaría la
    alarma permanentemente encendida, que es el argumento que este módulo ya tiene escrito para dejar
    el tipo de cambio fuera de `FECHAS_DE_ACTUALIZACION`.

    Si no hay nómina normalizada no hay nada que recalcular, y por eso el conjunto vacío no alerta:
    la ausencia de datos no es una configuración pendiente.
    """
```

Su cuerpo: consultar las `periodicidad_pago` distintas de `nomina_receptor` (join con `comprobantes` para
excluir cancelados), traducirlas con `reglas.PARA_CFDI` descartando `None`, y para cada periodicidad
traducida comprobar `repo.vigente(db, ejercicio=hoy.year, periodicidad=...)`. Motivo `AUSENTE` si no hay
fila, `SIN_CONFIRMAR` si hay y no está confirmada. `fecha_esperada` = 1 de enero del año en curso.

El `detalle` de la alerta dice qué hacer:

```python
detalle=(
    f"Falta la tarifa del ISR {etiqueta} de {hoy.year}. Descarga el Anexo 8 de la Resolución Miscelánea "
    "Fiscal del portal del SAT (sat.gob.mx → Normatividad → RMF → Anexos) y súbelo en "
    "Configuración → Fiscal."
)
```

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/ -k "alerta" -v
.venv/bin/mypy --strict app
git add app/services/sincronizacion_fiscal.py tests/
git commit -m "feat(fiscal): la alarma de vigencia exige la tarifa de las periodicidades que se timbran"
```

---

### Task 9: Contrato del frontend

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/api.http.ts`
- Modify: `apps/web/src/lib/api.mock.ts`

**Interfaces:**
- Produces: tipos `TarifaIsr`, `TarifaIsrRenglon`, `ComprobacionTarifa`, `ImportacionTarifas`; métodos
  `listarTarifasIsr`, `importarTarifaIsr`, `corregirTarifaIsr`, `confirmarTarifaIsr`, `descartarTarifaIsr`,
  `urlHojaDeRevisionTarifa`.

- [ ] **Step 1: Los tipos y la interfaz**

En `apps/web/src/lib/api.ts`, en la sección de configuración fiscal (§8bis), con el mismo comentario de
"añadido post-freeze" que usan los tipos de la fase 3 y la fecha de hoy. Los importes son `string` porque
el backend los envía como cadena para no perder precisión.

```ts
/** Un renglón de una tarifa del ISR. `limite_superior` nulo es el último ("En adelante"). */
export interface TarifaIsrRenglon {
  renglon: number;
  limite_inferior: string;
  limite_superior: string | null;
  cuota_fija: string;
  /** Fracción decimal, que es como se guarda y como calcula: "0.213600". */
  tasa_excedente: string;
  /** El mismo número como lo publica el SAT y como lo lee un contador: "21.36". Lo calcula el
   *  servidor a propósito: es el único número donde equivocar la escala cambia el resultado por cien. */
  tasa_porcentaje: string;
}

/** Comparación de la tarifa contra un recibo real. **No es un dictamen fiscal**: sirve para detectar
 *  un error de carga (una tabla de otro año o de otra periodicidad pasa las validaciones
 *  estructurales pero aquí da una diferencia enorme). */
export interface ComprobacionTarifa {
  uuid: string;
  fecha_inicial_pago: string;
  fecha_final_pago: string;
  num_empleado: string | null;
  dias_pagados: string;
  gravado: string;
  renglon: number;
  limite_inferior: string;
  tasa_porcentaje: string;
  isr_calculado: string;
  isr_timbrado: string;
  diferencia: string;
  /** Razones por las que la diferencia puede ser esperada, en español y listas para mostrar. */
  advertencias: string[];
}
```

`TarifaIsr` espeja `TarifaIsrOut` de la Task 6, incluida `etiqueta` (ya traducida por el servidor) y
`aplica_a_la_nomina`.

En la interfaz `ApiClient`, en el bloque de configuración fiscal, con el comentario de que son **solo
administrador**:

```ts
  listarTarifasIsr(): Promise<ImportacionTarifas>;
  /** Sube el PDF del Anexo 8. Las tarifas entran **sin confirmar**. */
  importarTarifaIsr(archivo: File): Promise<ImportacionTarifas>;
  /** Corrección manual: la lista **completa** de renglones. Limpia la confirmación. */
  corregirTarifaIsr(ejercicio: number, periodicidad: string, renglones: TarifaIsrRenglonIn[]): Promise<TarifaIsr>;
  confirmarTarifaIsr(ejercicio: number, periodicidad: string, huella: string): Promise<TarifaIsr>;
  /** Solo tarifas sin confirmar. */
  descartarTarifaIsr(ejercicio: number, periodicidad: string): Promise<void>;
  /** URL de la hoja de revisión en PDF, para abrir o descargar. */
  urlHojaDeRevisionTarifa(ejercicio: number, periodicidad: string): string;
```

- [ ] **Step 2: La implementación HTTP**

En `api.http.ts`, siguiendo los métodos que ya existen. `importarTarifaIsr` usa `FormData` y **no** fija
`Content-Type` a mano (el navegador pone el `boundary`); ver cómo lo hace la subida de e.firma si ya existe
ahí, y copiar ese patrón.

- [ ] **Step 3: El doble para desarrollo**

En `api.mock.ts`, una tarifa quincenal de 2026 con tres renglones y una comprobación con diferencia de
pesos, más una tarifa mensual sin confirmar. El mock **no** simula el PDF: `importarTarifaIsr` devuelve la
lista fija. Que sus datos sean coherentes importa, porque es con lo que se desarrolla la pantalla.

- [ ] **Step 4: Typecheck y commit**

```bash
cd apps/web && npm run typecheck && npm run lint && cd ..
git add apps/web/src/lib/
git commit -m "feat(web): contrato de tarifas del ISR en el ApiClient"
```

---

### Task 10: El panel de tarifas

**Files:**
- Create: `apps/web/src/features/admin/TarifaIsrPanel.tsx`
- Modify: `apps/web/src/features/admin/ConfiguracionFiscalPage.tsx`

**Interfaces:**
- Consumes: los tipos y métodos de la Task 9; `ChipEstado` y los helpers de formato que ya viven en
  `ConfiguracionFiscalPage.tsx` (si hace falta, extraerlos a un módulo compartido en vez de duplicarlos).
- Produces: `export function TarifaIsrPanel()`.

- [ ] **Step 1: El panel, en un archivo propio**

`ConfiguracionFiscalPage.tsx` ya tiene 672 líneas; el panel va aparte y la página solo lo monta.

Lo que el panel muestra, en este orden:

1. **Si no hay ninguna tarifa:** una tarjeta vacía que explica qué es esto y de dónde sale el documento —
   *"La tarifa del ISR se publica cada año en el Anexo 8 de la Resolución Miscelánea Fiscal, en el DOF de
   finales de diciembre"*— con la liga al minisitio de normatividad del SAT y el botón de importar.
2. **La tarifa que aplica a la nómina, primero y expandida**, con el rótulo *"es la que aplica a tu
   nómina"* (viene en `aplica_a_la_nomina`). Las demás, colapsadas.
3. **Si la nómina timbra una periodicidad sin tarifa publicada** (`periodicidades_sin_tarifa`), un aviso:
   *"El Anexo 8 no publica tarifa catorcenal; con esa periodicidad el cálculo se hace proporcionando la
   mensual y queda rotulado."*
4. Por tarifa: el chip de estado, la **etiqueta traducida** (`etiqueta`, nunca `periodicidad`), el
   encabezado citado del documento, la procedencia con su huella, la rejilla de renglones con la tasa en
   **porcentaje** como columna principal y la fracción como dato secundario, y la **comprobación** con su
   rótulo de que no es un dictamen.
5. Los renglones **corregidos a mano marcados**, con el aviso de que la tarifa difiere del documento
   (`difiere_del_documento`).
6. Botones: *Importar Anexo 8*, *Corregir*, *Confirmar*, *Descartar* (este último solo si no está
   confirmada).

Reglas de la interfaz que no son negociables:

- **Ninguna etiqueta visible es `DIAS_15` ni `TARIFA_ISR`.** Si aparece un nombre de enum en pantalla, es
  un defecto.
- **Los mensajes de error del servidor se muestran tal cual** (`detail.mensaje`): ya vienen en español
  llano y diciendo qué hacer. No se reescriben en el frontend ni se sustituyen por un genérico.
- **Confirmar manda la `huella`** que trajo el `GET`. Si el servidor responde 409 `TARIFA_CAMBIO`, la
  pantalla recarga y muestra el mensaje del servidor.
- **El color no es el único indicador de estado** (doc 08): chip con texto e ícono.
- La rejilla de corrección valida en el cliente lo evidente (formato de número, un solo renglón sin techo)
  **sin duplicar** las 6 pruebas: la autoridad es el servidor, y dos copias de la regla se separan.

- [ ] **Step 2: Montarlo en la página**

En `ConfiguracionFiscalPage.tsx`, después de la sección de parámetros: `<TarifaIsrPanel />`.

- [ ] **Step 3: Verificar en el navegador**

Con `docker compose up -d` y `cd apps/web && npm run dev`, entrar a `/admin/config` → Fiscal como
administrador y recorrer: importar el PDF real, ver las 7 tarifas, corregir un renglón, ver que la
confirmación se limpia y que aparece el aviso de que difiere del documento, confirmar la quincenal, ver la
comprobación. **Mirar la pantalla**, no solo que no truene la consola.

- [ ] **Step 4: Typecheck, lint y commit**

```bash
cd apps/web && npm run typecheck && npm run lint && cd ..
git add apps/web/src/features/admin/
git commit -m "feat(web): panel de tarifas del ISR en el idioma de un recibo de nomina"
```

---

### Task 11: La hoja de revisión para el contador

El dueño del Hub confirma, pero la revisión fiscal la hace alguien que **no tiene cuenta**. Esta hoja es
lo que se le manda.

**Files:**
- Create: `app/services/revision_tarifa.py`
- Modify: `app/api/v1/configuracion.py` (un `GET` más)
- Test: `tests/test_revision_tarifa.py`

**Interfaces:**
- Consumes: `TarifaGuardada` (Task 4), `Comprobacion` (Task 5).
- Produces: `hoja_html(tarifa, comprobacion) -> str` y `hoja_pdf(tarifa, comprobacion) -> bytes`;
  endpoint `GET /v1/configuracion/tarifa-isr/{ejercicio}/{periodicidad}/revision.pdf`.

- [ ] **Step 1: Write the failing test**

```python
"""La hoja que revisa un contador. Lo que estas pruebas fijan es qué **no** puede faltar en ella."""

def test_la_hoja_trae_las_tasas_en_porcentaje() -> None:
    """Un contador lee 21.36 %, no 0.2136. La fracción también va, como dato secundario."""
    html = revision_tarifa.hoja_html(_tarifa(), None)
    assert "21.36" in html


def test_la_hoja_cita_el_documento_y_su_huella() -> None:
    html = revision_tarifa.hoja_html(_tarifa(), None)
    assert "periodo de 15 dias" in html
    assert ("a" * 64) in html


def test_la_hoja_marca_los_renglones_corregidos_a_mano() -> None:
    html = revision_tarifa.hoja_html(_tarifa_manual(), None)
    assert "corregido a mano" in html.lower()


def test_la_hoja_dice_que_falta_confirmar_y_que_pasa_cuando_se_confirme() -> None:
    html = revision_tarifa.hoja_html(_tarifa(), None)
    assert "falta confirmar" in html.lower()


def test_la_hoja_rotula_la_comprobacion_como_no_dictamen() -> None:
    html = revision_tarifa.hoja_html(_tarifa(), _comprobacion())
    assert "no es un dictamen" in html.lower()


def test_el_pdf_se_genera_y_pesa_algo() -> None:
    pdf = revision_tarifa.hoja_pdf(_tarifa(), _comprobacion())
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_revision_tarifa.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

`app/services/revision_tarifa.py`, siguiendo el patrón de `app/services/representaciones.py`, que ya
genera el PDF del "Detalle del CFDI" con `weasyprint` (leerlo primero: tiene el `@page` y el CSS a copiar).
Hoja **vertical** (letter portrait), a diferencia del detalle del CFDI: es una tabla larga y angosta.

El HTML se arma con `html.escape` en todo lo que venga de datos —incluido `encabezado`, que sale del
documento subido— y contiene, en este orden: título con la etiqueta legible y el ejercicio; la procedencia
(fuente, huella SHA-256, fecha de importación); la tabla de renglones con **el porcentaje como columna
principal**; los renglones corregidos marcados con lo que decía el documento; la comprobación con su
rótulo *"Esto no es un dictamen fiscal: es una comprobación de que la tarifa se cargó bien"* y sus
advertencias; y al pie qué falta (*"Falta confirmar esta tarifa. Mientras no se confirme, ningún cálculo
la usa"*) o quién la confirmó y cuándo.

Se genera **en el servidor y no con la impresión del navegador** porque así el archivo se puede adjuntar a
un correo tal cual, que es lo que se va a hacer con él.

El endpoint devuelve `Response(content=pdf, media_type="application/pdf")` con
`Content-Disposition: inline; filename="tarifa-isr-2026-quincenal.pdf"`, es `require_admin` y **no**
escribe bitácora: es una lectura.

**Divergencia con el §7.4 del diseño, declarada:** el diseño decía "imprimible y exportable a Excel,
reutilizando el motor de informes". Se entrega **solo el PDF**. Un PDF ya es imprimible y adjuntable, y el
motor de informes exige universo, banderas y parámetros que esta hoja no tiene: arrastrarlo aquí lo
convertiría en el sitio equivocado para un documento de una sola tabla. Si el contador pide Excel, es un
añadido de una tarea, no un rediseño.

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/test_revision_tarifa.py -v
.venv/bin/mypy --strict app
git add app/services/revision_tarifa.py app/api/v1/configuracion.py tests/test_revision_tarifa.py
git commit -m "feat(fiscal): hoja de revision en PDF para que un contador valide la tarifa"
```

---

### Task 12: Verificación en vivo y documentación

**Files:**
- Create: `scripts/verificar_tarifa_isr.py`
- Modify: `config/fiscal/README.md`
- Modify: `Hub_CFDI_docs/07-roadmap/07_roadmap_sprints.md`

- [ ] **Step 1: El script de verificación**

`scripts/verificar_tarifa_isr.py`, con el patrón de `scripts/verificar_informes.py`: **sale con código
distinto de cero si algo falla**, e imprime qué comprobó. Corre contra la BD real, no contra dobles.

Comprueba, en orden:

1. Importa `tests/fixtures/anexo8-2026.pdf` por el endpoint y verifica **7 tarifas** con sus ejercicios
   correctos, incluida la anual del rubro C.I como **2025**.
2. La tarifa de 15 días de 2026 tiene 11 renglones, el primero arranca en `0.01` y el último tiene tasa
   `0.35` sin techo.
3. Ninguna tasa almacenada es `>= 1` (nunca quedó en porcentaje).
4. Corrige un renglón por el `PUT`: la confirmación se limpia, `origen` queda `MANUAL` y
   `difiere_del_documento` es verdadero.
5. Reimporta el mismo PDF: responde 409 `CORRECCION_MANUAL` y la corrección sigue en pie.
6. Descarta la tarifa corregida, reimporta y confirma la de 15 días con su huella.
7. Antes de confirmar, la resolución de la tarifa devolvía ausencia; después, la devuelve.
8. La comprobación con un recibo real trae un renglón y una diferencia **de pesos, no de órdenes de
   magnitud**.
9. La alerta `TARIFA_ISR` estaba en `AUSENTE`/`SIN_CONFIRMAR` y queda apagada.
10. La hoja de revisión en PDF se genera y empieza con `%PDF`.
11. **Deja la BD como estaba**: descarta lo que se creó para la prueba y lo dice en la salida. Si algo no
    se puede revertir limpiamente, lo dice en vez de dejarlo a medias.

- [ ] **Step 2: Correrlo contra el sistema real**

```bash
docker compose up -d
.venv/bin/python scripts/verificar_tarifa_isr.py
echo "código de salida: $?"
```

Esperado: código 0 y la lista de las 11 comprobaciones en verde. Si algo se comporta distinto de lo que
promete este plan, **es un defecto: reportarlo, no acomodarlo**.

- [ ] **Step 3: Revisar la pantalla con ojos de quien no es contador**

No es un `grep`: es abrir `/admin/config` → Fiscal y leerla. Que ninguna etiqueta visible sea un nombre de
enum (`DIAS_15`) ni una clave en mayúsculas (`SUBSIDIO_FACTOR_UMA`); que cada error diga qué hacer; que la
tarifa que aplica se distinga de las que no; y que la comprobación esté rotulada como comprobación de
carga. Anotar lo que no se entienda de una lectura y arreglarlo.

- [ ] **Step 4: Actualizar la documentación**

- `config/fiscal/README.md`: la tarifa del ISR pasa de "deuda declarada" a cargada, con qué está
  confirmado y qué falta; y la nota de que **la revisión fiscal la hace un contador**, no el dueño del Hub.
- `Hub_CFDI_docs/07-roadmap/07_roadmap_sprints.md`: dejar constancia de esta entrega. El roadmap **no
  menciona los informes** de las fases 1-3, así que agregar además una línea que apunte al spec de cada
  fase — el roadmap es la fuente de verdad de lo construido y hoy tiene un hueco de tres fases.

- [ ] **Step 5: Commit final**

```bash
.venv/bin/mypy --strict app
.venv/bin/pytest -q
cd apps/web && npm run typecheck && npm run lint && cd ..
git add scripts/verificar_tarifa_isr.py config/fiscal/README.md Hub_CFDI_docs/07-roadmap/
git commit -m "test(fiscal): verificacion en vivo de la carga de la tarifa del ISR"
```

---

## Notas de cierre

**Punto de control natural.** Las tareas 1 a 6 son el subsistema completo por el backend: al terminar la 6
la tarifa se puede importar, corregir, comprobar y confirmar por API, y eso ya es verificable en vivo.
Las 7 a 12 son el subsidio, la alarma, la interfaz y el cierre. Si conviene partir la entrega en dos, es
ahí.

**Lo que este plan NO construye, y no es un olvido:** el informe **B-09**, las columnas 24-26 de **B-05**,
la `tabla_subsidio` del modelo histórico, la descarga automática del PDF y un rol `fiscal` para contadores.
Las cinco decisiones están razonadas en §3 del documento de diseño.

**Tres cosas que quien implemente va a querer cambiar, y no debe sin hablarlo:**

1. **Añadir `MODELO_SUBSIDIO` a `param_fiscal`.** No cabe: la columna es decimal. §8 del diseño.
2. **Hacer que confirmar exija que la comprobación cuadre.** Bloquearía tarifas correctas: el ISR timbrado
   legítimamente difiere por subsidio, ajustes o el art. 174. §7.3 del diseño.
3. **Usar `c_PeriodicidadPago` como enum de la columna `periodicidad`.** El Anexo no publica tarifa para
   catorcenal ni bimestral, y admitirlas sugeriría que existen. §4 del diseño.

**Un defecto preexistente que este plan no toca, pero que conviene tener anotado:**
`app/informes/b02_conceptos_patron.py:95-103` mapea `"06"` como decenal, cuando en `c_PeriodicidadPago` el
**06 es Bimestral** y el decenal es el **10** (verificado contra `C75b_c_PeriodicidadPago` de `satcfdi`).
Hoy no tiene efecto porque ninguna empresa timbra esas periodicidades. El mapa correcto quedó escrito en
`app/services/tarifa_isr.PARA_CFDI` (Task 2); si algún día se arregla B-02, ese es el que vale.

