# Informes CFDI — Fase 3: configuración fiscal administrable, B-03, B-06 y B-08

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir la configuración fiscal como algo **administrable desde la aplicación** —con procedencia, vigencia, confirmación humana y alarma de caducidad— y sobre ella los tres informes que faltan (B-03, B-06, B-08) más dos columnas que quedaron bloqueadas en la fase 2.

**Architecture:** Los valores fiscales viven en tablas con vigencia por fecha, **nunca en el código** (§2.12 del documento fuente: cambian por ejercicio y por decreto). Cada valor carga su **procedencia**: de dónde salió, cuándo, y quién lo confirmó. La regla central es que **un valor sin confirmar no calcula**: el sistema puede proponer un valor —sembrado o sincronizado— pero hasta que una persona lo confirma, los informes lo tratan como ausente y lo dicen. La sincronización automática existe solo donde hay una API real; para el resto, lo que mantiene los valores al día no es un raspador frágil sino una **alarma consciente del calendario** que avisa cuando una fecha de actualización conocida ya pasó. Todo cambio se audita en `bitacora`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async, `asyncmy`), Alembic, Celery + Redis + beat, MySQL 8, `openpyxl`, `httpx`, pytest + testcontainers, React 19 + TypeScript + Vite + TanStack Query.

**Referencias:**
- Diseño: `docs/superpowers/specs/2026-08-05-informes-cfdi-nomina-design.md`, §12.
- Documento fuente: `Hub_CFDI_docs/00-fuentes/especificacion-informes-cfdi.md` — §2.12, §3.1, y las fichas **B-03** (941-988), **B-06** (1079-1123), **B-08** (1164-1199).
- **Implementaciones de referencia:** `app/informes/b02_conceptos_patron.py` (estructura de un informe), `app/informes/b05_acumulado_anual.py` (grano por empleado), `app/informes/universo_nomina.py`, `app/informes/periodos.py`, `app/informes/validadores.py`.
- **Piezas existentes que hay que reutilizar, no reinventar:** `app/models/configuracion.py` (tabla `Configuracion` de reglas del SAT), `app/services/bitacora.py` (`registrar(db, *, actor, accion, entidad, detalle)`), `app/api/deps.py:69` (`require_admin`) y `deps.py:75` (`require_empresa(rol_minimo)`), `apps/web/src/features/admin/ConfigBitacoraPage.tsx` (la pantalla `/admin/config` con pestañas).
- Planes anteriores: `2026-08-05-informes-cfdi-fase-1.md`, `2026-08-06-informes-cfdi-fase-2.md`.

## Global Constraints

- **Ningún importe fiscal se codifica en el programa.** Regla textual del §2.12: *"Ningún importe de tarifa, tope de exención, UMA o monto de subsidio se codifica en el programa. Todo vive en `tarifa_isr` y `param_fiscal` con vigencia, y se resuelve por fecha."* Un valor fiscal literal en un `.py` de `app/` es un defecto **Critical**. (Las semillas en YAML y las pruebas sí llevan valores: son datos, no código.)
- **Un valor sin confirmar no calcula.** `valor_vigente()` devuelve **solo** valores confirmados por una persona. Sembrar o sincronizar **propone**; nunca activa. Sin excepciones: es el invariante que evita que un raspador mal parseado o una semilla equivocada produzcan cálculos incorrectos en silencio.
- **Ningún valor fiscal tiene default en el código.** Ni la zona salarial, ni los días de aguinaldo, ni el factor de prima vacacional. Un default plausible es peor que un hueco visible, porque nadie lo revisa. Falta de valor ⇒ el informe lo dice.
- **Todo cambio de configuración escribe `bitacora` en la misma transacción** (regla 8 de `Hub_CFDI_docs/CLAUDE.md`). Si la bitácora falla, el cambio se revierte.
- **Permiso en cada endpoint** (regla 3): la configuración fiscal es política federal ⇒ `require_admin`. La configuración de una empresa ⇒ `require_empresa` con el rol mínimo que corresponda. Nunca se confía en el `empresa_id` del cliente.
- **Claves de catálogo del SAT como texto** (`'001'` nunca `1`).
- **`Decimal` de punta a punta. Jamás `float`.** El redondeo ocurre una sola vez, en `app/informes/excel.py`, con `ROUND_HALF_UP`. **Ningún informe lleva `round()` ni `quantize()`.**
- **El motor enmascara, el informe declara.** Una columna sensible se marca `Columna(..., sensible=True)`; **ningún informe llama a `excel.enmascarar()`**.
- **Cero, no vacío** en celdas de importe, salvo la excepción ya declarada de B-04 y las columnas que dependen de un valor no confirmado (que salen vacías, ver la tabla de degradación).
- **Datos propios sí, de terceros no, personales nunca** (regla 12).
- **Cero N+1** (regla 11): agregaciones y joins, no un `SELECT` por empleado.
- Docstrings y comentarios en español. Sin imports sin usar.
- **Verde obligatorio antes de cada commit:** las pruebas de los archivos tocados y `.venv/bin/mypy --strict app`. En tareas de `apps/web`, además `npm run typecheck` y `npm run lint`. **La suite completa la corre el controlador** (~19 min).
- Los informes nuevos se registran en `app/informes/registro.py` y declaran `TIPOS_COMPROBANTE = ("N",)`.

## Comportamiento degradado — aprobado por el dueño del repo

Hay **tres** estados, no dos, y la diferencia entre los dos últimos es la que hace la configuración usable:

| Estado del valor | Qué hacen los informes |
|---|---|
| **Confirmado** | Calculan normal |
| **Propuesto, sin confirmar** | Tratan el valor como ausente, **y la bandera dice que hay una propuesta esperando confirmación, con su fuente**. Es un aviso accionable de un clic, no un error |
| **Ausente** | Tratan el valor como ausente y la bandera dice qué falta cargar y dónde |

Y el trato es distinto por informe **a propósito**:

| Informe | Sin el valor que necesita | Por qué |
|---|---|---|
| **B-03** | Columnas 1–13 normales; las de topes de exención **vacías con bandera** `FALTA_UMA` (o `UMA_SIN_CONFIRMAR`) | El desglose gravado/exento ya es útil sin los topes; calcularlos con un cero daría exenciones falsas |
| **B-06** | Agrupa por el texto libre del XML y emite `DEPARTAMENTO_SIN_MAPEO` con el conteo de filas afectadas | El agrupamiento aproximado sirve desde el día uno, y la calidad queda auditable |
| **B-08** | **No se genera** mientras algún concepto de percepción esté **sin clasificar**, y el aviso dice cuáles. Con la clasificación completa —aunque todos sean `NO_APLICA`— **sí se genera** | Sin clasificar, no se puede distinguir "no se pagó aguinaldo" de "sí se pagó y no sé cuál es", y una provisión calculada sobre esa duda es un número sin significado que alguien podría llevar a sus estados financieros. Con la clasificación completa, el cero es un hecho conocido |
| **B-10** | Las dos validaciones de SBC **no se evalúan** y el conteo `VALIDACIONES_EJECUTADAS` lo refleja | Una validación de "salario bajo el mínimo" con el mínimo equivocado es peor que no tenerla: da falsos negativos silenciosos |

## Qué se sincroniza automáticamente y qué no — investigado, no supuesto

| Valor | Fuente automática | Decisión |
|---|---|---|
| **Tipo de cambio** | [API SIE de Banxico](https://www.banxico.org.mx/SieAPIRest/service/v1/doc/catalogoSeries): REST, JSON, token gratuito, serie `SF43718` | **Se sincroniza.** Es la única fuente con API documentada y estable |
| **UMA** | El [INEGI](https://www.inegi.org.mx/servicios/api_indicadores.html) la publica como **boletín PDF**; su API sirve el INPC, del que la UMA se deriva | **No se sincroniza.** Recalcularla desde el INPC sería reimplementar la ley en código, justo lo que el §2.12 prohíbe. Propuesta sembrada + alarma de calendario |
| **Salario mínimo** | CONASAMI publica en el DOF; **no hay API** | **No se sincroniza.** Raspar HTML del DOF se rompe en silencio y deja cálculos incorrectos sin avisar. Propuesta sembrada + alarma |
| **Tarifa ISR y subsidio** | Anexo 8 de la RMF, **PDF** | Fuera de alcance en esta fase (ver la tabla siguiente) |

**Lo que de verdad mantiene los valores al día es la alarma de vigencia de la tarea 6**, no el raspado: las fechas de actualización son conocidas y fijas (UMA el 1 de febrero, salario mínimo el 1 de enero), así que el sistema puede saber que está desactualizado sin necesidad de leer el DOF.

## Alcance: lo que esta fase NO cubre

| Qué | Por qué |
|---|---|
| **B-09** (recálculo de ISR y subsidio) y la tabla `tarifa_isr` | Requiere el Anexo 8 de la RMF por ejercicio y periodicidad, en PDF. B-09.R2 advierte de errores de dos órdenes de magnitud por una tasa mal cargada. Fuera desde el diseño |
| **B-11** (contra plantilla de RH) | Requiere `plantilla_rh`, fuente externa que no existe |
| **B-12** (incapacidades y horas extra) | Los XML actuales no traen esos nodos |
| **B-13** (consolidado multi-organización) | Solo hay una empresa dada de alta |
| **La columna 15 de B-06** (costo patronal estimado) | B-06.R2: **no es derivable del CFDI**, el complemento solo trae la parte obrera. Requeriría tasas patronales de IMSS, INFONAVIT e ISN estatal, y sería una estimación que hay que rotular como tal |
| **Raspado del DOF o de CONASAMI** | Ver la tabla anterior: se rompe en silencio. La alarma de calendario cubre la necesidad sin el riesgo |

---

### Task 1: Las tablas de configuración, con procedencia y vigencia

**Files:**
- Create: `app/models/configuracion_fiscal.py`
- Modify: `app/models/__init__.py`
- Create: `alembic/versions/<rev>_add_configuracion_fiscal.py` (autogenerada)
- Test: `tests/test_modelos_configuracion_fiscal.py`

**Interfaces:**
- Produces: `ParamFiscal`, `CatalogoPercepcionMarca`, `MapDepartamento`, `MapConceptoProvision`, `TablaVacaciones`, `ConfiguracionEmpresa`, y los enums `OrigenValor`, `BaseExencion`, `CategoriaProvision`, `ZonaSalarial`.

**Las seis tablas:**

| Tabla | Columnas | Notas |
|---|---|---|
| `param_fiscal` | `ejercicio` INT, `clave` VARCHAR(40), `valor` `Numeric(18,6)`, `vigencia_desde` DATE, `vigencia_hasta` DATE NULL, **`origen`** ENUM(`SEMILLA`,`MANUAL`,`SINCRONIZADO`), **`fuente`** VARCHAR(500), **`sincronizado_en`** DATETIME NULL, **`confirmado_por`** VARCHAR(128) NULL, **`confirmado_en`** DATETIME NULL | Claves: `UMA_DIARIA`, `UMA_MENSUAL`, `UMA_ANUAL`, `SALARIO_MINIMO_GENERAL`, `SALARIO_MINIMO_ZLFN`, `TIPO_CAMBIO_USD`. PK compuesta `(clave, vigencia_desde)` |
| `catalogo_percepcion_marca` | `tipo_percepcion` CHAR(3) **PK**, `es_ingreso_ordinario` BOOL, `base_exencion` ENUM(`UMA_DIAS`,`SM_DIAS`,`PORCENTAJE`,`NINGUNA`), `factor_exencion` `Numeric(9,4)` NULL, `integra_sbc` BOOL, `es_provisionable` BOOL | Las marcas del §3.1 que el catálogo del SAT no trae |
| `map_departamento` | `empresa_id` FK, `departamento_texto` VARCHAR(100), `centro_costo` VARCHAR(100) | PK `(empresa_id, departamento_texto)` |
| `map_concepto_provision` | `empresa_id` FK, `naturaleza` CHAR(1), `tipo` CHAR(3), `clave` VARCHAR(15), `categoria` ENUM(`AGUINALDO`,`VACACIONES`,`PRIMA_VACACIONAL`,`NO_APLICA`) | PK con las cuatro primeras |
| `tabla_vacaciones` | `anios_antiguedad` INT **PK**, `dias` INT | Art. 76 LFT. Global: es ley |
| `configuracion_empresa` | `empresa_id` FK **PK**, `zona_salarial` ENUM(`GENERAL`,`ZLFN`) **NULL**, `dias_aguinaldo` INT **NULL**, `factor_prima_vacacional` `Numeric(5,4)` **NULL** | Política de cada organización. **Los tres nacen nulos a propósito** |

**Por qué `configuracion_empresa` y no columnas en `empresas`.** `empresas` es una tabla caliente del listado; la fase 1 estableció no tocarla y colgar lo nuevo de una tabla aparte. Además estos tres valores son política laboral, no identidad de la empresa.

**Por qué los tres campos de `configuracion_empresa` nacen nulos.** Decisión explícita del dueño del repo. La zona salarial no tiene default porque **el mínimo aplicable cambia el resultado de una validación de cumplimiento**: Ciudad Juárez está en la Zona Libre de la Frontera Norte, donde el mínimo 2026 es 440.87 contra 315.04 del general — usar el general daría falsos negativos en "empleado por debajo del mínimo". Un default plausible aquí es peor que un hueco visible. Lo mismo para los días de aguinaldo (el mínimo legal es 15, pero cada organización puede dar más) y el factor de prima vacacional (mínimo legal 0.25). **Escribe esta justificación en el docstring del módulo**: alguien va a querer "arreglar" los nulos poniendo defaults.

**Por qué `param_fiscal` aparte de la tabla `Configuracion` que ya existe.** `Configuracion` (`app/models/configuracion.py`) versiona por `ejercicio_fiscal` en texto y guarda `valor` como JSON. Sirve para las reglas operativas del SAT, pero **no puede expresar la vigencia de la UMA, que cambia el 1 de febrero, a mitad de ejercicio**, ni lleva procedencia. Son mecanismos distintos para necesidades distintas; los dos se administran desde la misma pantalla en la tarea 5. **Documéntalo**, o alguien intentará fusionarlas.

**Reglas duras de esquema:** claves de catálogo como texto; importes en `Numeric` con decimales suficientes; `mysql_charset="utf8mb4"` y `mysql_collate="utf8mb4_unicode_ci"`; FK a `empresas` con `ON DELETE CASCADE` en las tres tablas por empresa. Para los `ENUM`, usa `enum_column` de `app/models/enums.py:11`, que es el patrón de la casa.

- [ ] **Step 1: Write the failing test**

```python
"""Tablas de configuración fiscal (§12 del diseño, §2.12 y §3.1 del documento fuente).

Lo que estas pruebas fijan a propósito:
- `param_fiscal` admite dos tramos de vigencia en un mismo ejercicio (la UMA cambia el 1 de
  febrero, el salario mínimo el 1 de enero).
- Cada valor carga su procedencia, y `confirmado_en` nulo es un estado legítimo y distinto de
  "no hay valor".
- `configuracion_empresa` nace con los tres campos nulos: no hay default para la zona salarial
  porque el mínimo aplicable cambia el resultado de una validación de cumplimiento.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion_fiscal import (
    CatalogoPercepcionMarca,
    ConfiguracionEmpresa,
    MapConceptoProvision,
    MapDepartamento,
    ParamFiscal,
    TablaVacaciones,
)
from app.models.enums import BaseExencion, CategoriaProvision, OrigenValor, ZonaSalarial
from tests import factories


async def test_param_fiscal_admite_dos_tramos_en_un_ejercicio(db: AsyncSession) -> None:
    """La UMA cambia el 1 de febrero: enero todavía usa la del año anterior."""
    db.add(ParamFiscal(ejercicio=2026, clave="UMA_DIARIA", valor=Decimal("113.140000"),
                       vigencia_desde=date(2025, 2, 1), vigencia_hasta=date(2026, 1, 31),
                       origen=OrigenValor.SEMILLA, fuente="INEGI, boletín UMA 2025"))
    db.add(ParamFiscal(ejercicio=2026, clave="UMA_DIARIA", valor=Decimal("117.310000"),
                       vigencia_desde=date(2026, 2, 1), vigencia_hasta=None,
                       origen=OrigenValor.SEMILLA, fuente="INEGI, boletín UMA 2026"))
    await db.commit()

    filas = list((await db.execute(select(ParamFiscal).order_by(ParamFiscal.vigencia_desde))).scalars().all())
    assert len(filas) == 2
    # `vigencia_hasta` nula significa "vigente hasta nuevo aviso", no "sin vigencia".
    assert filas[1].vigencia_hasta is None
    assert filas[0].valor == Decimal("113.140000")


async def test_un_valor_nace_sin_confirmar(db: AsyncSession) -> None:
    """Sembrar propone, no activa: `confirmado_en` nulo es el estado inicial legítimo."""
    db.add(ParamFiscal(ejercicio=2026, clave="UMA_DIARIA", valor=Decimal("117.310000"),
                       vigencia_desde=date(2026, 2, 1), vigencia_hasta=None,
                       origen=OrigenValor.SEMILLA, fuente="INEGI, boletín UMA 2026"))
    await db.commit()

    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None
    assert fila.confirmado_en is None
    assert fila.confirmado_por is None
    # La procedencia siempre viaja con el valor: sin fuente, nadie puede revisarlo.
    assert fila.fuente != ""
    assert fila.origen is OrigenValor.SEMILLA


async def test_confirmar_registra_quien_y_cuando(db: AsyncSession) -> None:
    db.add(ParamFiscal(ejercicio=2026, clave="UMA_DIARIA", valor=Decimal("117.310000"),
                       vigencia_desde=date(2026, 2, 1), vigencia_hasta=None,
                       origen=OrigenValor.SEMILLA, fuente="INEGI"))
    await db.commit()

    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None
    fila.confirmado_por = "uid-de-prueba"
    fila.confirmado_en = datetime(2026, 8, 6, 12, 0, 0)
    await db.commit()

    recargada = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert recargada is not None
    assert recargada.confirmado_por == "uid-de-prueba"
    assert recargada.confirmado_en is not None


async def test_marca_de_percepcion_conserva_la_clave_como_texto(db: AsyncSession) -> None:
    db.add(CatalogoPercepcionMarca(tipo_percepcion="002", es_ingreso_ordinario=True,
                                   base_exencion=BaseExencion.UMA_DIAS, factor_exencion=Decimal("30.0000"),
                                   integra_sbc=True, es_provisionable=True))
    db.add(CatalogoPercepcionMarca(tipo_percepcion="022", es_ingreso_ordinario=False,
                                   base_exencion=BaseExencion.NINGUNA, factor_exencion=None,
                                   integra_sbc=False, es_provisionable=False))
    await db.commit()

    marca = await db.scalar(select(CatalogoPercepcionMarca).where(CatalogoPercepcionMarca.tipo_percepcion == "002"))
    assert marca is not None
    # '002' no puede volverse 2.
    assert marca.tipo_percepcion == "002"
    assert marca.factor_exencion == Decimal("30.0000")
    sin_exencion = await db.scalar(
        select(CatalogoPercepcionMarca).where(CatalogoPercepcionMarca.tipo_percepcion == "022"))
    assert sin_exencion is not None
    assert sin_exencion.factor_exencion is None


async def test_configuracion_de_empresa_nace_sin_defaults(db: AsyncSession) -> None:
    """Decisión explícita: la zona salarial no tiene default porque el mínimo aplicable
    cambia el resultado de una validación de cumplimiento (Juárez es ZLFN, no general)."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    db.add(ConfiguracionEmpresa(empresa_id=empresa.empresa_id))
    await db.commit()

    cfg = await db.scalar(select(ConfiguracionEmpresa).where(ConfiguracionEmpresa.empresa_id == empresa.empresa_id))
    assert cfg is not None
    assert cfg.zona_salarial is None
    assert cfg.dias_aguinaldo is None
    assert cfg.factor_prima_vacacional is None

    cfg.zona_salarial = ZonaSalarial.ZLFN
    await db.commit()
    recargada = await db.scalar(
        select(ConfiguracionEmpresa).where(ConfiguracionEmpresa.empresa_id == empresa.empresa_id))
    assert recargada is not None
    assert recargada.zona_salarial is ZonaSalarial.ZLFN


async def test_mapeos_de_organizacion_cuelgan_de_la_empresa(db: AsyncSession) -> None:
    """Dos empresas pueden tener el mismo texto de departamento con centros de costo distintos."""
    a = await factories.crear_empresa(db, rfc="CHL960913IX9", nombre="Empresa A")
    b = await factories.crear_empresa(db, rfc="EKU9003173C9", nombre="Empresa B")

    db.add(MapDepartamento(empresa_id=a.empresa_id, departamento_texto="Direccion", centro_costo="ADMIN"))
    db.add(MapDepartamento(empresa_id=b.empresa_id, departamento_texto="Direccion", centro_costo="GERENCIA"))
    db.add(MapConceptoProvision(empresa_id=a.empresa_id, naturaleza="P", tipo="001", clave="019",
                                categoria=CategoriaProvision.VACACIONES))
    await db.commit()

    de_a = await db.scalar(select(MapDepartamento).where(MapDepartamento.empresa_id == a.empresa_id))
    de_b = await db.scalar(select(MapDepartamento).where(MapDepartamento.empresa_id == b.empresa_id))
    assert de_a is not None and de_b is not None
    assert de_a.centro_costo == "ADMIN" and de_b.centro_costo == "GERENCIA"

    provision = await db.scalar(select(MapConceptoProvision).where(MapConceptoProvision.empresa_id == a.empresa_id))
    assert provision is not None
    # La clave interna del patrón, como texto.
    assert (provision.naturaleza, provision.tipo, provision.clave) == ("P", "001", "019")


async def test_borrar_la_empresa_arrastra_su_configuracion(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    db.add(MapDepartamento(empresa_id=empresa.empresa_id, departamento_texto="Direccion", centro_costo="ADMIN"))
    db.add(ConfiguracionEmpresa(empresa_id=empresa.empresa_id, zona_salarial=ZonaSalarial.ZLFN))
    await db.commit()

    await db.delete(empresa)
    await db.commit()
    assert await db.scalar(select(MapDepartamento).where(MapDepartamento.empresa_id == empresa.empresa_id)) is None
    assert await db.scalar(
        select(ConfiguracionEmpresa).where(ConfiguracionEmpresa.empresa_id == empresa.empresa_id)) is None


async def test_tabla_de_vacaciones_es_global(db: AsyncSession) -> None:
    """Art. 76 de la LFT: es ley federal, no una regla de cada patrón."""
    db.add(TablaVacaciones(anios_antiguedad=1, dias=12))
    db.add(TablaVacaciones(anios_antiguedad=2, dias=14))
    await db.commit()

    filas = list((await db.execute(select(TablaVacaciones).order_by(TablaVacaciones.anios_antiguedad))).scalars().all())
    assert [(f.anios_antiguedad, f.dias) for f in filas] == [(1, 12), (2, 14)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_modelos_configuracion_fiscal.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.models.configuracion_fiscal'`

- [ ] **Step 3: Escribir los modelos y los enums**

Sigue el estilo de `app/models/nomina.py` y `app/models/cfdi_detalle.py` — ábrelos. Los cuatro enums nuevos van en `app/models/enums.py`, junto a los que ya existen, y se declaran con `enum_column`.

- [ ] **Step 4: Registrar los modelos**

En `app/models/__init__.py`, el import y las entradas de `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_modelos_configuracion_fiscal.py -q`
Expected: PASS (8 tests)

- [ ] **Step 6: Generar, aplicar y verificar la migración**

Los servicios deben estar arriba. `alembic/` ya está montado en el contenedor.

Run: `docker compose exec -T api alembic revision --autogenerate -m "add configuracion fiscal"`
Run: `docker compose exec -T api alembic upgrade head`
Run: `docker compose exec -T api alembic downgrade -1 && docker compose exec -T api alembic upgrade head`

Expected: crea las seis tablas, ninguna alteración a tablas existentes, downgrade limpio.

**Trampa conocida de las tres fases anteriores:** el `op.drop_index` que Alembic autogenera para un índice compuesto cuya primera columna es la de una FK falla con el **error 1553 de MySQL**, porque InnoDB usa ese índice para satisfacer la FK. Si tus tablas tienen ese caso, quita el `drop_index` y deja que `DROP TABLE` se lleve el índice. **Ejecuta el ciclo, no lo asumas.**

- [ ] **Step 7: Type-check and commit**

```bash
.venv/bin/mypy --strict app
git add app/models/ alembic/versions/ tests/test_modelos_configuracion_fiscal.py
git commit -m "feat(config): agregar las tablas de configuracion fiscal con procedencia y vigencia"
```

---

### Task 2: Resolución por vigencia, el invariante de confirmación, y el cargador

**Files:**
- Create: `app/services/configuracion_fiscal.py`
- Create: `config/fiscal/param_fiscal.yaml`, `config/fiscal/catalogo_percepcion.yaml`, `config/fiscal/tabla_vacaciones.yaml`
- Create: `app/scripts/cargar_configuracion_fiscal.py`
- Test: `tests/test_configuracion_fiscal.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ValorFiscal` — `valor: Decimal`, `vigencia_desde: date`, `origen: OrigenValor`, `fuente: str`, `confirmado: bool`.
  - `async def valor_vigente(db, clave: str, en_fecha: date) -> Decimal | None` — **solo valores confirmados**; `None` cuando no hay. Nunca lanza, nunca devuelve cero por ausencia.
  - `async def valor_propuesto(db, clave: str, en_fecha: date) -> ValorFiscal | None` — el valor **sin confirmar** que está esperando, para que la UI y las banderas puedan decir que existe.
  - `async def marcas_de_percepcion(db) -> dict[str, CatalogoPercepcionMarca]`
  - `async def centro_de_costo(db, empresa_id: int) -> dict[str, str]`
  - `async def categorias_de_provision(db, empresa_id: int) -> dict[tuple[str, str, str], CategoriaProvision]`
  - `async def dias_de_vacaciones(db, anios: int) -> int | None`
  - `async def configuracion_de_empresa(db, empresa_id: int) -> ConfiguracionEmpresa | None`
  - `async def salario_minimo_de_empresa(db, empresa_id: int, en_fecha: date) -> Decimal | None` — resuelve la clave según la zona configurada; `None` si la zona no está configurada **o** si el valor no está confirmado.
  - `async def cargar_desde_yaml(db, ruta: Path, *, empresa_id: int | None = None) -> dict[str, int]` — idempotente.

**El invariante que define esta tarea.** `valor_vigente` devuelve **solo lo confirmado**. Es lo que hace que sembrar y sincronizar sean seguros: pueden equivocarse sin corromper un cálculo. Y `valor_propuesto` existe para que la ausencia sea *accionable* — la diferencia entre "falta la UMA, ve a buscarla" y "la UMA 2026 está propuesta con su liga al boletín del INEGI, confírmala" es la diferencia entre un informe que estorba y uno que ayuda.

**`salario_minimo_de_empresa` es el único resolutor con dos pasos**, y por eso va aquí y no en el informe: primero la zona configurada de la empresa, luego la clave correspondiente (`SALARIO_MINIMO_GENERAL` o `SALARIO_MINIMO_ZLFN`). Si la zona es nula devuelve `None` **sin mirar los valores**: no hay default. B-10 traduce ese `None` en "no evalué esta validación y te digo por qué".

- [ ] **Step 1: Write the failing test**

```python
"""Resolución por vigencia, invariante de confirmación y carga de la configuración fiscal.

La regla central que estas pruebas fijan: **un valor sin confirmar no calcula.** Sembrar o
sincronizar propone; solo una persona activa. Y la ausencia se distingue del cero: `None`
nunca es `Decimal("0")`, porque un cero en un tope de exención produce exenciones falsas.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion_fiscal import ConfiguracionEmpresa, ParamFiscal
from app.models.enums import OrigenValor, ZonaSalarial
from app.services import configuracion_fiscal as cfg
from tests import factories


def _param(clave: str, valor: str, desde: date, *, confirmado: bool, hasta: date | None = None) -> ParamFiscal:
    return ParamFiscal(
        ejercicio=desde.year, clave=clave, valor=Decimal(valor), vigencia_desde=desde, vigencia_hasta=hasta,
        origen=OrigenValor.SEMILLA, fuente="prueba",
        confirmado_por="uid-prueba" if confirmado else None,
        confirmado_en=datetime(2026, 8, 6, 12, 0, 0) if confirmado else None,
    )


async def test_valor_vigente_resuelve_por_fecha(db: AsyncSession) -> None:
    db.add(_param("UMA_DIARIA", "113.140000", date(2025, 2, 1), hasta=date(2026, 1, 31), confirmado=True))
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=True))
    await db.commit()

    # Enero de 2026 todavía usa la UMA publicada en febrero de 2025.
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 1, 15)) == Decimal("113.140000")
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) == Decimal("117.310000")
    # El día exacto del corte cuenta para el tramo nuevo.
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 2, 1)) == Decimal("117.310000")


async def test_un_valor_sin_confirmar_no_calcula(db: AsyncSession) -> None:
    """El invariante central de la fase: sembrar propone, no activa."""
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=False))
    await db.commit()

    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None
    # Pero la propuesta se puede ver, con su procedencia, para que el aviso sea accionable.
    propuesto = await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 30))
    assert propuesto is not None
    assert propuesto.valor == Decimal("117.310000")
    assert propuesto.confirmado is False
    assert propuesto.fuente == "prueba"


async def test_confirmar_activa_el_valor(db: AsyncSession) -> None:
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=False))
    await db.commit()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) is None

    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None
    fila.confirmado_por = "uid-prueba"
    fila.confirmado_en = datetime(2026, 8, 6, 12, 0, 0)
    await db.commit()

    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) == Decimal("117.310000")


async def test_sin_valor_devuelve_none_no_cero(db: AsyncSession) -> None:
    """Un cero en un tope de exención produce exenciones falsas: la ausencia debe ser `None`."""
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None
    assert await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 30)) is None


async def test_fecha_anterior_a_toda_vigencia_devuelve_none(db: AsyncSession) -> None:
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=True))
    await db.commit()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2025, 12, 31)) is None


async def test_salario_minimo_depende_de_la_zona_configurada(db: AsyncSession) -> None:
    """Ciudad Juárez es ZLFN: el mínimo aplicable es 440.87, no 315.04. Sin zona configurada,
    no hay default — devuelve `None` y B-10 no evalúa la validación."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    db.add(ConfiguracionEmpresa(empresa_id=empresa.empresa_id))  # zona nula a propósito
    db.add(_param("SALARIO_MINIMO_GENERAL", "315.040000", date(2026, 1, 1), confirmado=True))
    db.add(_param("SALARIO_MINIMO_ZLFN", "440.870000", date(2026, 1, 1), confirmado=True))
    await db.commit()

    # Sin zona configurada: ningún default, ni el general.
    assert await cfg.salario_minimo_de_empresa(db, empresa.empresa_id, date(2026, 6, 1)) is None

    config = await cfg.configuracion_de_empresa(db, empresa.empresa_id)
    assert config is not None
    config.zona_salarial = ZonaSalarial.ZLFN
    await db.commit()
    assert await cfg.salario_minimo_de_empresa(db, empresa.empresa_id, date(2026, 6, 1)) == Decimal("440.870000")

    config.zona_salarial = ZonaSalarial.GENERAL
    await db.commit()
    assert await cfg.salario_minimo_de_empresa(db, empresa.empresa_id, date(2026, 6, 1)) == Decimal("315.040000")


async def test_salario_minimo_sin_confirmar_no_se_usa_aunque_haya_zona(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    db.add(ConfiguracionEmpresa(empresa_id=empresa.empresa_id, zona_salarial=ZonaSalarial.ZLFN))
    db.add(_param("SALARIO_MINIMO_ZLFN", "440.870000", date(2026, 1, 1), confirmado=False))
    await db.commit()
    assert await cfg.salario_minimo_de_empresa(db, empresa.empresa_id, date(2026, 6, 1)) is None


async def test_cargar_yaml_es_idempotente_y_no_confirma(db: AsyncSession, tmp_path: Path) -> None:
    """Cargar una semilla nunca la confirma: eso es acto humano."""
    ruta = tmp_path / "param.yaml"
    ruta.write_text(
        "param_fiscal:\n"
        "  - ejercicio: 2026\n"
        "    clave: UMA_DIARIA\n"
        "    valor: '117.31'\n"
        "    vigencia_desde: 2026-02-01\n"
        "    vigencia_hasta: null\n"
        "    fuente: 'INEGI, boletin UMA 2026'\n",
        encoding="utf-8",
    )

    primero = await cfg.cargar_desde_yaml(db, ruta)
    segundo = await cfg.cargar_desde_yaml(db, ruta)
    assert primero["param_fiscal"] == 1
    assert segundo["param_fiscal"] == 1  # actualiza, no duplica

    # Cargada pero NO confirmada: no calcula.
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) is None
    propuesto = await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 1))
    assert propuesto is not None
    assert propuesto.valor == Decimal("117.31")


async def test_cargar_yaml_valida_lo_que_no_puede_estar_mal(db: AsyncSession, tmp_path: Path) -> None:
    """Un valor negativo o una vigencia invertida es un error de captura: hay que atraparlo al
    cargar, no al calcular un informe tres meses después."""
    negativo = tmp_path / "negativo.yaml"
    negativo.write_text(
        "param_fiscal:\n  - ejercicio: 2026\n    clave: UMA_DIARIA\n    valor: '-5.00'\n"
        "    vigencia_desde: 2026-02-01\n    vigencia_hasta: null\n    fuente: 'x'\n",
        encoding="utf-8")
    with pytest.raises(ValueError):
        await cfg.cargar_desde_yaml(db, negativo)

    invertida = tmp_path / "invertida.yaml"
    invertida.write_text(
        "param_fiscal:\n  - ejercicio: 2026\n    clave: UMA_DIARIA\n    valor: '117.31'\n"
        "    vigencia_desde: 2026-06-01\n    vigencia_hasta: 2026-02-01\n    fuente: 'x'\n",
        encoding="utf-8")
    with pytest.raises(ValueError):
        await cfg.cargar_desde_yaml(db, invertida)

    sin_fuente = tmp_path / "sin_fuente.yaml"
    sin_fuente.write_text(
        "param_fiscal:\n  - ejercicio: 2026\n    clave: UMA_DIARIA\n    valor: '117.31'\n"
        "    vigencia_desde: 2026-02-01\n    vigencia_hasta: null\n",
        encoding="utf-8")
    # Sin fuente nadie puede revisar el valor: es un error de captura, no un campo opcional.
    with pytest.raises(ValueError):
        await cfg.cargar_desde_yaml(db, sin_fuente)


async def test_los_mapeos_por_empresa_exigen_empresa_id(db: AsyncSession, tmp_path: Path) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    ruta = tmp_path / "mapeo.yaml"
    ruta.write_text(
        "map_departamento:\n  - departamento_texto: Direccion\n    centro_costo: ADMIN\n", encoding="utf-8")
    with pytest.raises(ValueError):
        await cfg.cargar_desde_yaml(db, ruta)

    resumen = await cfg.cargar_desde_yaml(db, ruta, empresa_id=empresa.empresa_id)
    assert resumen["map_departamento"] == 1
    assert (await cfg.centro_de_costo(db, empresa.empresa_id))["Direccion"] == "ADMIN"


async def test_dias_de_vacaciones_por_antiguedad(db: AsyncSession) -> None:
    from app.models.configuracion_fiscal import TablaVacaciones

    db.add(TablaVacaciones(anios_antiguedad=1, dias=12))
    db.add(TablaVacaciones(anios_antiguedad=5, dias=20))
    await db.commit()

    assert await cfg.dias_de_vacaciones(db, 1) == 12
    assert await cfg.dias_de_vacaciones(db, 5) == 20
    # Una antigüedad entre dos renglones toma el mayor que no la excede: el art. 76 crece cada
    # cinco años después del quinto, así que buscar el renglón exacto fallaría con 7 años.
    assert await cfg.dias_de_vacaciones(db, 7) == 20
    assert await cfg.dias_de_vacaciones(db, 0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_configuracion_fiscal.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.configuracion_fiscal'`

- [ ] **Step 3: Implementar el servicio y el cargador**

Puntos concretos:
- `valor_vigente`: filtra `clave`, `vigencia_desde <= en_fecha`, (`vigencia_hasta` nula o `>= en_fecha`) **y `confirmado_en IS NOT NULL`**, ordena por `vigencia_desde` descendente, toma el primero. Sin fila, `None`.
- `valor_propuesto`: lo mismo pero con `confirmado_en IS NULL`.
- `dias_de_vacaciones`: el renglón con el mayor `anios_antiguedad` que no exceda el parámetro.
- El cargador valida **antes** de escribir: valor no negativo, `vigencia_hasta >= vigencia_desde`, `fuente` no vacía, claves de catálogo con la longitud correcta, y `empresa_id` presente para las tablas por empresa. Lanza `ValueError` **diciendo qué fila y qué campo**. Un fallo al cargar es barato; un cálculo incorrecto tres meses después no.
- El cargador **nunca** escribe `confirmado_por` ni `confirmado_en`.
- Idempotencia por la clave natural de cada tabla: actualiza, no duplica. **Si el valor cambia, la confirmación previa se limpia** — un valor distinto es un valor nuevo y necesita confirmación nueva. Escribe una prueba para eso.
- **PyYAML ya está instalado** (`PyYAML==6.0.3` en `requirements.txt`) pero llegó como **dependencia transitiva**: no está en `pyproject.toml`. Como `app/` va a importar `yaml` directamente, **decláralo como dependencia directa en `pyproject.toml`** — una transitiva puede desaparecer cuando cambia el paquete que la arrastraba, y el cargador se rompería sin aviso.

- [ ] **Step 4: Escribir los YAML de estructura**

`config/fiscal/param_fiscal.yaml` **sin valores todavía** (los siembra la tarea 3): solo la estructura y un comentario con las claves esperadas y de dónde sale cada una. Las otras dos se llenan en la tarea 3.

- [ ] **Step 5: El script de carga**

`app/scripts/cargar_configuracion_fiscal.py`, al estilo de `app/scripts/generar_kek_dev.py`. Recibe la ruta y opcionalmente `--empresa-id`. Imprime el resumen por tabla, **dice explícitamente que lo cargado queda pendiente de confirmación**, y sale con código distinto de cero si la validación falla.

- [ ] **Step 6: Run tests and commit**

Run: `.venv/bin/pytest tests/test_configuracion_fiscal.py -q`
Expected: PASS (11 tests + la de la confirmación que se limpia)

```bash
.venv/bin/mypy --strict app
git add app/services/ app/scripts/ config/ tests/ pyproject.toml
git commit -m "feat(config): resolucion por vigencia con invariante de confirmacion"
```

---

### Task 3: Semillas — la ley, y los valores 2026 como propuesta con su fuente

**Files:**
- Modify: `config/fiscal/tabla_vacaciones.yaml`, `config/fiscal/catalogo_percepcion.yaml`, `config/fiscal/param_fiscal.yaml`
- Create: `config/fiscal/empresa.yaml.ejemplo`
- Create: `config/fiscal/README.md`
- Test: `tests/test_semillas_fiscales.py`

**Interfaces:**
- Consumes: el cargador de la tarea 2.
- Produces: ningún símbolo. Datos de semilla y las pruebas que los validan.

**Qué se siembra y con qué estatus.** Todo entra **sin confirmar**. El dueño del repo confirma desde la pantalla de la tarea 5.

**Los valores 2026, ya investigados, con su fuente:**

| Clave | Valor | Vigencia desde | Fuente para el campo `fuente` |
|---|---|---|---|
| `UMA_DIARIA` | 117.31 | 2026-02-01 | INEGI, boletín UMA 2026 — https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2026/uma/uma2026.pdf |
| `UMA_MENSUAL` | 3566.22 | 2026-02-01 | idem |
| `UMA_ANUAL` | 42794.64 | 2026-02-01 | idem |
| `SALARIO_MINIMO_GENERAL` | 315.04 | 2026-01-01 | DOF 09-12-2025 — https://www.dof.gob.mx/nota_detalle.php?codigo=5775534&fecha=09%2F12%2F2025 |
| `SALARIO_MINIMO_ZLFN` | 440.87 | 2026-01-01 | idem |

**`tabla_vacaciones` — art. 76 de la LFT, reforma de 2023.** 12 días el primer año, +2 por año hasta 20 al quinto, y +2 cada cinco años después. **Cita el artículo en un comentario del YAML.**

**`catalogo_percepcion.yaml` — las marcas del §3.1.** Es el trabajo detallado de esta tarea:
- `es_ingreso_ordinario`: **falso para los cinco tipos del régimen del art. 95 de la LISR** — `022` Prima por antigüedad, `023` Pagos por separación, `025` Indemnizaciones, `039` Jubilaciones/pensiones/haberes de retiro y `044` idem en parcialidades; verdadero para el resto. **Los códigos están verificados contra el catálogo real** (`C75b_c_TipoPercepcion` de satcfdi, **44 tipos**), no tomados de memoria: `022` es *Prima por antigüedad*, no separación, y omitir `025` marcaría las indemnizaciones como ingreso ordinario, sobreestimando la base anual del ISR en B-05.
- `base_exencion` y `factor_exencion`: del **artículo 93 de la LISR**. Casos con tope conocido: aguinaldo (30 días de UMA), prima vacacional y PTU (15 días de UMA cada uno), horas extra, previsión social, fondo de ahorro, primas de antigüedad, indemnizaciones. Los que no tienen exención llevan `NINGUNA` y factor nulo.
- `integra_sbc`: artículo 27 de la LSS.
- `es_provisionable`: verdadero para lo que entra en el pasivo laboral (aguinaldo, vacaciones, prima vacacional).

**Requisitos de proceso, no de código:**
1. **Cita la fuente de cada valor en un comentario del YAML, con el artículo.** Sin eso nadie puede revisar la semilla.
2. **Marca con `# REVISAR:` los tipos de los que no estés seguro.** Es mejor una duda declarada que un factor inventado. El dueño del repo va a revisar este archivo y necesita saber dónde mirar.
3. **Ningún valor de estos entra a un `.py` de `app/`.**

- [ ] **Step 1: Escribir las pruebas de coherencia**

Las pruebas **no** validan la corrección fiscal —eso lo revisa una persona— sino la coherencia interna, que es lo que sí se puede automatizar:

```python
"""Coherencia de las semillas fiscales.

Estas pruebas **no** validan los valores contra la ley (eso lo revisa el dueño del repo con el
`README.md` que esta tarea produce): validan que las semillas sean internamente coherentes,
cargables, y que **ninguna llegue confirmada**. Un factor de exención mal capturado no lo atrapa
una prueba; una semilla contradictoria o autoconfirmada sí.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import configuracion_fiscal as cfg

_RAIZ = Path(__file__).resolve().parent.parent / "config" / "fiscal"


def test_tabla_de_vacaciones_es_monotona_y_arranca_en_doce() -> None:
    """Art. 76 LFT tras la reforma de 2023: 12 días el primer año, y nunca decrece."""
    datos = yaml.safe_load((_RAIZ / "tabla_vacaciones.yaml").read_text(encoding="utf-8"))
    filas = sorted(datos["tabla_vacaciones"], key=lambda f: f["anios_antiguedad"])
    assert filas[0]["anios_antiguedad"] == 1
    assert filas[0]["dias"] == 12
    dias = [f["dias"] for f in filas]
    assert dias == sorted(dias), "los días de vacaciones no pueden decrecer con la antigüedad"
    assert 20 in dias, "el art. 76 llega a 20 días al quinto año"


def test_marcas_de_percepcion_son_coherentes() -> None:
    """Un tipo con base de exención distinta de NINGUNA debe traer factor, y al revés."""
    datos = yaml.safe_load((_RAIZ / "catalogo_percepcion.yaml").read_text(encoding="utf-8"))
    for fila in datos["catalogo_percepcion_marca"]:
        tipo = fila["tipo_percepcion"]
        assert isinstance(tipo, str), f"la clave {tipo!r} debe ser texto, no entero"
        assert len(tipo) == 3, f"la clave {tipo!r} debe tener tres posiciones"
        if fila["base_exencion"] == "NINGUNA":
            assert fila.get("factor_exencion") is None, f"{tipo}: sin base de exención no puede haber factor"
        else:
            assert fila.get("factor_exencion") is not None, f"{tipo}: con base de exención hace falta el factor"
            assert float(fila["factor_exencion"]) > 0, f"{tipo}: el factor debe ser positivo"


def test_separacion_y_jubilacion_no_son_ingreso_ordinario() -> None:
    """B-05.R4: tienen régimen fiscal propio (arts. 95 y 96 LISR) y no se acumulan al ordinario.

    Los cinco códigos están verificados contra el catálogo real de satcfdi
    (`C75b_c_TipoPercepcion`, 44 tipos), no de memoria:
      022 Prima por antigüedad · 023 Pagos por separación · 025 Indemnizaciones
      039 Jubilaciones, pensiones o haberes de retiro · 044 idem en parcialidades
    Los tres primeros caen bajo el art. 95 de la LISR, que los agrupa explícitamente
    ("primas de antigüedad, retiro e indemnizaciones u otros pagos por separación").
    Omitir 025 marcaría las indemnizaciones como ingreso ordinario y **sobreestimaría la
    base anual del ISR** en la columna 11 de B-05.
    """
    datos = yaml.safe_load((_RAIZ / "catalogo_percepcion.yaml").read_text(encoding="utf-8"))
    por_tipo = {f["tipo_percepcion"]: f for f in datos["catalogo_percepcion_marca"]}
    for tipo in ("022", "023", "025", "039", "044"):
        assert tipo in por_tipo, f"falta sembrar el tipo {tipo}"
        assert por_tipo[tipo]["es_ingreso_ordinario"] is False, f"{tipo} no es ingreso ordinario"


def test_todo_parametro_fiscal_declara_su_fuente() -> None:
    """Sin fuente, un revisor no puede verificar el valor: es el requisito que hace la semilla
    auditable, y por eso el cargador lo exige."""
    datos = yaml.safe_load((_RAIZ / "param_fiscal.yaml").read_text(encoding="utf-8"))
    for fila in datos["param_fiscal"]:
        fuente = fila.get("fuente", "")
        assert fuente, f"{fila['clave']}: falta la fuente"
        assert "http" in fuente or any(c.isdigit() for c in fuente), (
            f"{fila['clave']}: la fuente debe citar una liga o una fecha de publicación, no ser genérica")


def test_toda_marca_dudosa_esta_senalada() -> None:
    """Un valor no confirmado lleva `REVISAR` con su tipo, para que la revisión sepa dónde mirar."""
    texto = (_RAIZ / "catalogo_percepcion.yaml").read_text(encoding="utf-8")
    for linea in texto.splitlines():
        if "REVISAR" in linea:
            assert any(c.isdigit() for c in linea), f"la duda debe decir de qué tipo es: {linea!r}"


async def test_las_semillas_se_cargan_y_ninguna_queda_confirmada(db: AsyncSession) -> None:
    """El invariante de la fase, aplicado a las semillas: cargar propone, no activa."""
    await cfg.cargar_desde_yaml(db, _RAIZ / "tabla_vacaciones.yaml")
    await cfg.cargar_desde_yaml(db, _RAIZ / "catalogo_percepcion.yaml")
    resumen = await cfg.cargar_desde_yaml(db, _RAIZ / "param_fiscal.yaml")
    assert resumen["param_fiscal"] > 0

    # La ley se aplica sola (no lleva confirmación); los importes, no.
    assert await cfg.dias_de_vacaciones(db, 1) == 12
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) is None
    propuesto = await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 1))
    assert propuesto is not None
    assert "inegi" in propuesto.fuente.lower()


async def test_las_dos_zonas_de_salario_minimo_estan_sembradas(db: AsyncSession) -> None:
    """Las dos, porque la zona aplicable es configuración de cada empresa y no se puede adivinar."""
    await cfg.cargar_desde_yaml(db, _RAIZ / "param_fiscal.yaml")
    for clave in ("SALARIO_MINIMO_GENERAL", "SALARIO_MINIMO_ZLFN"):
        assert await cfg.valor_propuesto(db, clave, date(2026, 6, 1)) is not None, f"falta sembrar {clave}"
```

- [ ] **Step 2: Run tests to verify they fail, escribir las semillas, verlas pasar**

Run: `.venv/bin/pytest tests/test_semillas_fiscales.py -q`
Expected: primero FAIL, luego PASS (7 tests).

- [ ] **Step 3: `config/fiscal/empresa.yaml.ejemplo`**

Plantilla de la configuración por empresa (zona salarial, días de aguinaldo, factor de prima, mapeos), **con valores de ejemplo claramente ficticios** y un comentario diciendo que hay que copiarla sin el sufijo. **No la llenes con datos inventados que alguien pudiera confundir con reales.**

- [ ] **Step 4: `config/fiscal/README.md` — el documento de revisión**

Es el documento que el dueño del repo lee para revisar las semillas. Escríbelo para eso, no como documentación genérica. Debe llevar: qué contiene cada archivo; **de dónde sale cada valor, con su artículo o su liga**; la lista explícita de los tipos marcados `REVISAR`; qué falta por capturar y quién lo captura; y cómo se corre el script.

- [ ] **Step 5: Commit**

```bash
.venv/bin/mypy --strict app
git add config/ tests/test_semillas_fiscales.py
git commit -m "feat(config): sembrar la ley y los valores fiscales 2026 como propuesta con su fuente"
```

---

### Task 4: Endpoints de configuración, con bitácora

**Files:**
- Create: `app/api/v1/configuracion.py`
- Modify: `app/api/v1/router.py`, `app/api/v1/schemas.py`
- Test: `tests/test_api_configuracion.py`

**Interfaces:**
- Consumes: `app/services/configuracion_fiscal.py`, `app/services/bitacora.py`, `app/api/deps.py`.
- Produces:
  - `GET /v1/configuracion/fiscal` → parámetros con procedencia, estado de confirmación y alertas de vigencia.
  - `PUT /v1/configuracion/fiscal/{clave}` → captura o corrección manual (`require_admin`).
  - `POST /v1/configuracion/fiscal/{clave}/confirmar` → confirma un valor propuesto (`require_admin`).
  - `GET /v1/configuracion/percepciones` y `PUT /v1/configuracion/percepciones/{tipo}` → marcas del §3.1 (`require_admin`).
  - `GET /v1/empresas/{empresa_id}/configuracion` y `PUT ...` → zona salarial, días de aguinaldo, factor de prima (`require_empresa(RolEmpresa.OPERADOR)`).
  - `GET /v1/empresas/{empresa_id}/configuracion/mapeos` y `PUT ...` → `map_departamento` y `map_concepto_provision`.
  - **`GET /v1/empresas/{empresa_id}/configuracion/conceptos-observados`** → los conceptos que **realmente aparecen** en los CFDI de la empresa, cada uno con su naturaleza, tipo, clave, descripción, número de comprobantes en que aparece, importe acumulado, y la categoría que tenga asignada (o ninguna). Igual para los departamentos observados.

**Por qué existe `conceptos-observados`, y es la pieza que hace usable toda la configuración por empresa.** Nadie sabe de memoria que su aguinaldo se timbra como `P/002/047`: las claves internas las inventa el sistema de nómina del patrón, no el usuario. Pedirle a alguien que las escriba a ciegas es pedirle un dato que no tiene, y fue un defecto de diseño de las versiones anteriores de este plan. Con este endpoint la pantalla puede **listar lo que la nómina realmente emitió** y dejar que la persona reconozca la descripción —"Aguinaldo", "Prima vacacional"— y elija su categoría de una lista. Nunca teclea una clave.

Sale de las tablas normalizadas que ya existen (`nomina_percepcion`, `nomina_receptor`), con una consulta agregada. **Cero N+1.**

**El registro va en `app/api/v1/router.py`, no en `app/main.py`.** (Se documentó dos veces en las fases anteriores porque el plan lo tenía mal.)

**Permisos, sin margen:** la configuración fiscal es política federal y aplica a todas las empresas ⇒ `require_admin` (`app/api/deps.py:69`). La configuración de una empresa ⇒ `require_empresa(RolEmpresa.OPERADOR)` (`deps.py:75`). Nunca se lee el `empresa_id` del cuerpo para decidir permiso.

**Bitácora en la misma transacción, para todo cambio** (regla 8): `bitacora.registrar(db, actor=..., accion=..., entidad=..., detalle=...)`. El `detalle` lleva el valor anterior y el nuevo — es el rastro que sustituye al diff de git. **Si la bitácora falla, el cambio se revierte.**

**Una regla de negocio que hay que hacer cumplir en el endpoint:** confirmar exige que el cliente mande el valor que está confirmando, y el servidor rechaza si no coincide con el almacenado. Sin eso, una propuesta que cambió entre que se pintó la pantalla y que se hizo clic se confirmaría a ciegas — exactamente el escenario que el invariante de confirmación existe para evitar.

- [ ] **Step 1: Write the failing tests**

Cubre, cada una con su aserción concreta:
1. `GET /v1/configuracion/fiscal` con un usuario **no admin** → 403.
2. `GET` con admin → lista los parámetros, cada uno con `valor`, `vigencia_desde`, `origen`, `fuente` y `confirmado` booleano.
3. `POST .../confirmar` con admin → el valor queda confirmado, y **`valor_vigente` empieza a devolverlo**.
4. `POST .../confirmar` **mandando un valor que no coincide** con el almacenado → 409, y el valor sigue sin confirmar.
5. `PUT` manual con admin → guarda con `origen=MANUAL`, `fuente` la que mande el cliente, y **sin confirmar** (capturar tampoco confirma; son dos actos).
6. `PUT` con un valor negativo → 422, y nada cambia en la BD.
7. Cada cambio (confirmar y capturar) **escribe una fila en `bitacora`** con el valor anterior y el nuevo.
8. `PUT /v1/empresas/{id}/configuracion` con rol `CONSULTA` → 403; con `OPERADOR` → 200.
9. `PUT` de la configuración de una empresa **a la que el usuario no tiene acceso** → 403, sin filtrar si existe.
10. `PUT` de la zona salarial a `ZLFN` → `salario_minimo_de_empresa` devuelve 440.87 (con el valor confirmado sembrado).
11. `GET /v1/empresas/{id}/configuracion` recién creada la empresa → los tres campos nulos, y el cuerpo lo dice explícitamente (no los omite).

Usa el cliente de pruebas y las factorías que ya usan `tests/test_api_informes.py` y `tests/test_api_usuarios.py` — **ábrelos y sigue su patrón** de autenticación y de creación de usuarios con rol.

- [ ] **Step 2 a 4: fallar, implementar, registrar el router, pasar y commitear**

Run: `.venv/bin/pytest tests/test_api_configuracion.py -q`
Expected: PASS

```bash
.venv/bin/mypy --strict app
git add app/api/ tests/ && git commit -m "feat(config): endpoints de configuracion fiscal y por empresa con bitacora"
```

---

### Task 5: La pantalla de Configuración

**Files:**
- Create: `apps/web/src/features/admin/ConfiguracionFiscalPage.tsx`
- Modify: `apps/web/src/features/admin/ConfigBitacoraPage.tsx` (una pestaña más), `apps/web/src/lib/api.ts`, `apps/web/src/lib/http.ts`, `apps/web/src/lib/mock.ts`, y el enrutador
- Test: manual, con el checklist del step 4

**Interfaces:**
- Consumes: los endpoints de la tarea 4.
- Produces: `ParametroFiscal`, `ConfiguracionEmpresa` (tipos), `listarConfiguracionFiscal`, `capturarParametroFiscal`, `confirmarParametroFiscal`, `obtenerConfiguracionEmpresa`, `guardarConfiguracionEmpresa` en el `ApiClient`.

**Dónde vive.** Ya existe `/admin/config` con pestañas (`ConfigBitacoraPage.tsx`, que gestiona las automatizaciones del beat). **Agrega una pestaña "Fiscal"**, siguiendo el patrón de rutas reales que ese archivo documenta en su comentario de cabecera. No inventes una sección nueva de la aplicación.

**Lo que esta pantalla NO debe ser.** En julio se eliminó de esa misma página un volcado crudo de parámetros clave/valor (commit `1845a68`), con razón: a nadie le servía. **No lo recrees.** Esta pantalla se organiza por lo que el usuario quiere lograr, con nombres en español llano ("Unidad de Medida y Actualización (UMA) diaria", no `UMA_DIARIA`), la vigencia en fechas legibles, y **la fuente como liga cuando la hay**.

**Los tres estados tienen que distinguirse a la vista**, y es el punto de toda la pantalla:
- **Confirmado**: valor, vigencia, y quién lo confirmó y cuándo.
- **Propuesto**: valor, su fuente como liga, y un botón **Confirmar**. Es la acción de un clic que convierte una alarma en un dato usable.
- **Ausente**, o **caducado** (la fecha de actualización conocida ya pasó): aviso visible con qué hay que capturar y de dónde sale.

Respeta el sistema de diseño del doc 08: el color comunica estado pero **nunca es el único indicador** — siempre chip con texto e ícono. Identificadores fiscales en monoespaciada. Contraste ≥ 4.5:1.

**La configuración por empresa** (zona salarial, días de aguinaldo, factor de prima) va en la pantalla de la empresa o en su propia sección de esta pestaña, según lo que quede más coherente con la navegación existente — **decídelo leyendo la aplicación y justifícalo en el informe**. Los tres campos nacen vacíos y la pantalla debe decir **qué se degrada mientras estén vacíos** (sin zona salarial, B-10 no evalúa el salario mínimo).

- [ ] **Step 1: Extender el `ApiClient` y el mock**

El contrato del doc 05 está congelado (regla 10): **actualiza el documento en la misma sesión** si agregas métodos. El mock (`mock.ts`) debe reflejar **las reglas reales del backend**, no una versión relajada — en la fase 1 un mock permisivo escondió un 403 real. Incluye en el mock un parámetro en cada uno de los tres estados, para poder ver la pantalla completa sin backend.

- [ ] **Step 2: La pestaña Fiscal**

- [ ] **Step 3: La configuración por empresa**

- [ ] **Step 4: Verificar en el navegador**

Run: `cd apps/web && npm run typecheck && npm run lint`

Y con la aplicación arriba, comprueba: los tres estados se distinguen; **Confirmar** funciona y el valor pasa a confirmado sin recargar; capturar un valor manual lo deja **sin confirmar**; un valor negativo se rechaza con mensaje claro; un usuario no admin no ve la pestaña fiscal (o la ve deshabilitada con explicación, **no un error crudo**); guardar la zona salarial persiste. Reporta lo que viste.

- [ ] **Step 5: Commit**

```bash
cd apps/web && npm run typecheck && npm run lint && cd ..
git add apps/web/ Hub_CFDI_docs/
git commit -m "feat(web): pantalla de configuracion fiscal con procedencia y confirmacion"
```

---

### Task 6: Alarma de vigencia y sincronización desde Banxico

**Files:**
- Create: `app/services/sincronizacion_fiscal.py`
- Modify: `app/worker/tasks.py`, `app/worker/celery_app.py` (calendario del beat), `app/core/config.py` (token de Banxico)
- Test: `tests/test_sincronizacion_fiscal.py`

**Interfaces:**
- Produces:
  - `FECHAS_DE_ACTUALIZACION: dict[str, tuple[int, int]]` — mes y día en que cada clave se actualiza cada año (`UMA_*` → 1 de febrero; `SALARIO_MINIMO_*` → 1 de enero).
  - `@dataclass(frozen=True) class AlertaVigencia` — `clave`, `motivo` (`AUSENTE`, `SIN_CONFIRMAR`, `CADUCADO`), `vigencia_desde` del valor actual, `fecha_esperada`.
  - `async def alertas_de_vigencia(db, hoy: date) -> list[AlertaVigencia]`
  - `async def sincronizar_tipo_cambio(db, *, hoy: date) -> int` — Banxico; devuelve cuántos valores propuso.
  - Tarea Celery `revisar_vigencia_fiscal` (diaria, por beat).

**Una fuente de caducidad más, que no es un valor sino el propio catálogo.** Desde la ronda de la tarea 4, capturar una marca de percepción exige que el tipo exista en `C75b_c_TipoPercepcion` de satcfdi. Es la protección correcta contra un dedazo (`150` por `015`), pero tiene un costo: **si el SAT publica claves nuevas, se rechazarán hasta que se actualice la versión de `satcfdi`**. Inclúyelo en las alertas: si la versión instalada lleva mucho sin actualizarse, dilo, porque el síntoma sin aviso sería "no puedo capturar un tipo que el SAT ya publicó".

**Esto es lo que de verdad mantiene los valores al día.** No hay API para la UMA ni para el salario mínimo, pero **sí se sabe cuándo cambian**: la UMA el 1 de febrero, el salario mínimo el 1 de enero. Si esa fecha del año en curso ya pasó y no hay un valor **confirmado** cuya `vigencia_desde` sea igual o posterior, el valor está caducado y hay que gritarlo. Esto no se rompe nunca, porque no depende de que una página web conserve su estructura.

**La sincronización de Banxico propone, no confirma** — como todo lo demás. Y **falla ruidosamente**: si la API no responde o el token falta, se registra y la alerta lo dice; nunca se traga el error dejando un valor viejo con cara de vigente.

**Guarda de plausibilidad, contra el error de captura y el mal parseo.** Un valor nuevo que se desvíe del anterior más allá de un margen razonable no se propone en silencio: se propone **marcado como sospechoso**, con la desviación calculada. Es la defensa que atrapa tanto un dedazo (117.31 escrito como 11731) como un parseo que leyó la columna equivocada. Elige el margen y **justifícalo en un comentario**: los incrementos reales de la UMA rondan la inflación, y el del salario mínimo 2026 fue del 13%, así que el margen tiene que tolerar un 13% sin chillar pero atrapar un orden de magnitud.

- [ ] **Step 1: Write the failing tests**

```python
"""Alarma de vigencia y sincronización de valores fiscales.

Lo que estas pruebas fijan: la alarma **no depende de internet**. La UMA cambia el 1 de febrero
y el salario mínimo el 1 de enero; esas fechas son conocidas, así que el sistema puede saber que
está desactualizado sin leer el DOF. Es la defensa que no se rompe cuando una página cambia de
estructura.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion_fiscal import ParamFiscal
from app.models.enums import OrigenValor
from app.services import sincronizacion_fiscal as sync


def _param(clave: str, valor: str, desde: date, *, confirmado: bool) -> ParamFiscal:
    return ParamFiscal(
        ejercicio=desde.year, clave=clave, valor=Decimal(valor), vigencia_desde=desde, vigencia_hasta=None,
        origen=OrigenValor.SEMILLA, fuente="prueba",
        confirmado_por="uid" if confirmado else None,
        confirmado_en=datetime(2026, 8, 6) if confirmado else None,
    )


async def test_valor_ausente_genera_alerta(db: AsyncSession) -> None:
    alertas = await sync.alertas_de_vigencia(db, date(2026, 8, 6))
    claves = {a.clave for a in alertas}
    assert "UMA_DIARIA" in claves
    assert next(a for a in alertas if a.clave == "UMA_DIARIA").motivo == "AUSENTE"


async def test_valor_propuesto_pero_sin_confirmar_genera_alerta_distinta(db: AsyncSession) -> None:
    """Distinguirlas es lo que hace la alarma accionable: una pide capturar, la otra un clic."""
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=False))
    await db.commit()

    alertas = await sync.alertas_de_vigencia(db, date(2026, 8, 6))
    de_uma = next(a for a in alertas if a.clave == "UMA_DIARIA")
    assert de_uma.motivo == "SIN_CONFIRMAR"


async def test_valor_del_ejercicio_anterior_esta_caducado(db: AsyncSession) -> None:
    """El 1 de febrero de 2026 ya pasó y el valor vigente es de 2025: caducado."""
    db.add(_param("UMA_DIARIA", "113.140000", date(2025, 2, 1), confirmado=True))
    await db.commit()

    alertas = await sync.alertas_de_vigencia(db, date(2026, 8, 6))
    de_uma = next(a for a in alertas if a.clave == "UMA_DIARIA")
    assert de_uma.motivo == "CADUCADO"
    assert de_uma.fecha_esperada == date(2026, 2, 1)


async def test_antes_de_la_fecha_de_actualizacion_no_hay_alerta(db: AsyncSession) -> None:
    """En enero de 2026, la UMA de febrero de 2025 sigue siendo la vigente: no es caducidad."""
    db.add(_param("UMA_DIARIA", "113.140000", date(2025, 2, 1), confirmado=True))
    await db.commit()

    alertas = await sync.alertas_de_vigencia(db, date(2026, 1, 15))
    assert not [a for a in alertas if a.clave == "UMA_DIARIA"]


async def test_valor_confirmado_y_al_dia_no_genera_alerta(db: AsyncSession) -> None:
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=True))
    await db.commit()
    alertas = await sync.alertas_de_vigencia(db, date(2026, 8, 6))
    assert not [a for a in alertas if a.clave == "UMA_DIARIA"]


async def test_un_valor_implausible_se_marca_sospechoso(db: AsyncSession) -> None:
    """Atrapa el dedazo (117.31 capturado como 11731) y el parseo de la columna equivocada."""
    anterior = Decimal("113.14")
    assert sync.es_implausible(anterior, Decimal("11731.00")) is True
    # El salario mínimo 2026 subió 13%: el margen debe tolerarlo sin chillar.
    assert sync.es_implausible(Decimal("278.80"), Decimal("315.04")) is False


async def test_sincronizar_falla_ruidosamente_sin_token(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nunca se traga el error dejando un valor viejo con cara de vigente."""
    monkeypatch.setattr(sync, "_token_banxico", lambda: None)
    with pytest.raises(sync.SincronizacionNoConfigurada):
        await sync.sincronizar_tipo_cambio(db, hoy=date(2026, 8, 6))


async def test_sincronizar_propone_sin_confirmar(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Como todo lo demás: propone. Ni la API más confiable activa un valor por su cuenta."""
    from app.services import configuracion_fiscal as cfg

    async def _falso_banxico(*_a: object, **_k: object) -> list[tuple[date, Decimal]]:
        return [(date(2026, 8, 5), Decimal("18.4321"))]

    monkeypatch.setattr(sync, "_token_banxico", lambda: "token-de-prueba")
    monkeypatch.setattr(sync, "_consultar_serie", _falso_banxico)

    propuestos = await sync.sincronizar_tipo_cambio(db, hoy=date(2026, 8, 6))
    assert propuestos == 1
    assert await cfg.valor_vigente(db, "TIPO_CAMBIO_USD", date(2026, 8, 5)) is None
    propuesto = await cfg.valor_propuesto(db, "TIPO_CAMBIO_USD", date(2026, 8, 5))
    assert propuesto is not None
    assert propuesto.origen is OrigenValor.SINCRONIZADO
    assert "banxico" in propuesto.fuente.lower()
```

- [ ] **Step 2 a 4: fallar, implementar, pasar**

La llamada a Banxico usa `httpx` con **tiempo de espera explícito** (nunca sin límite) y el token desde `app/core/config.py`, jamás incrustado. La URL de la serie y el formato están en la [documentación del SIE](https://www.banxico.org.mx/SieAPIRest/service/v1/doc/catalogoSeries); la serie del tipo de cambio FIX es `SF43718`. **Ninguna prueba llama a la red**: se inyecta la respuesta, como en las pruebas de arriba.

- [ ] **Step 5: La tarea de Celery y el beat**

`revisar_vigencia_fiscal`, diaria. Registra las alertas y, si hay token, intenta la sincronización de Banxico. **Agrégala al calendario del beat** siguiendo el patrón de las tareas que ya están ahí, y **añádela a las automatizaciones que el admin puede apagar** desde `/admin/config` si ese mecanismo lo admite — mira `ConfigBitacoraPage.tsx` y el endpoint de automatizaciones para ver si encaja; si no encaja limpiamente, dilo en el informe en vez de forzarlo.

**Recuerda:** el worker y el beat **no recargan código**. Tras agregar la tarea, `docker compose restart worker beat`, y verifica con `docker compose exec -T worker celery -A app.worker.celery_app inspect registered` — un `python -c "import ..."` da un falso positivo porque lanza un proceso nuevo.

- [ ] **Step 6: Commit**

```bash
.venv/bin/pytest tests/test_sincronizacion_fiscal.py -q
.venv/bin/mypy --strict app
git add app/ tests/ && git commit -m "feat(config): alarma de vigencia fiscal y sincronizacion de tipo de cambio"
```

---

### Task 7: B-03 · Desglose gravado / exento por percepción

**Files:**
- Create: `app/informes/b03_gravado_exento.py`
- Modify: `app/informes/registro.py`
- Test: `tests/test_informe_b03.py`

**Interfaces:**
- Consumes: `app/informes/universo_nomina.py`, `app/services/configuracion_fiscal.py`, `app/informes/catalogos.py`.
- Produces: `CLAVE = "B-03"`, `TIPOS_COMPROBANTE = ("N",)`, `class Parametros` con `fecha_desde`, `fecha_hasta`, `tipo_percepcion: str | None = None`, `incluir_cancelados: bool = False`, `enmascarar_datos_personales: bool = True`; `async def consultar(...)`.

**Qué es.** Grano: **una fila por nodo de percepción** (formato largo, no pivotado). Verifica la correcta aplicación de las exenciones del **artículo 93 de la LISR** concepto por concepto, y es lo que el SAT reconstruye para determinar diferencias de ISR de nómina.

**Columnas 1 a 13, de los datos:** UUID, fecha de pago, periodo, RFC y nombre del empleado, número de empleado, departamento, puesto, días pagados, tipo de percepción con su descripción del catálogo, clave y concepto del patrón, importe gravado, importe exento, importe total, porcentaje exento.

**Columnas 14 a 17, dependientes de configuración:** base de exención aplicable, tope de exención, exceso sobre el tope, UMA aplicable a la fecha de pago.

**La degradación, que es el punto delicado.** Según lo que devuelvan `valor_vigente` y `valor_propuesto` para `UMA_DIARIA` a la fecha de pago:
- Columnas 14 a 17 **vacías** (`None`), nunca cero.
- **Una sola** bandera de severidad alta —no una por fila, que es la lección del colapso de la fase 2— con el conteo de filas afectadas: `UMA_SIN_CONFIRMAR` si hay propuesta (diciendo su fuente y que basta confirmarla) o `FALTA_UMA` si no hay nada.
- El resto del informe, normal.

**Las tres reglas de la ficha:**
- **B-03.R1 — el tope se resuelve por tipo de percepción** según `base_exencion` y `factor_exencion`, con la UMA vigente a la fecha de pago: `UMA_DIAS` → `factor × UMA_DIARIA`; `SM_DIAS` → `factor × salario mínimo de la empresa`; `PORCENTAJE` → `factor × importe_total`; `NINGUNA` → tope cero.

  **`factor_exencion` con `PORCENTAJE` está en escala 0–100, no como fracción.** Lo definió la tarea 3 porque nada en el proyecto lo fijaba; está documentado en el YAML y en `config/fiscal/README.md`. Usar la fracción daría exenciones cien veces menores.

**Tres límites del modelo de configuración que B-03 tiene que respetar, y que el esquema no puede expresar por sí solo.** Salieron de la tarea 3, al derivar las marcas contra el texto oficial de la LISR. Ignorarlos hace que el informe **exente de más**, que es el error más caro que puede cometer:

1. **El tope conjunto de previsión social.** El penúltimo párrafo del art. 93 limita la **suma** de las exenciones de previsión social a 1 UMA anual por trabajador y por año — no es un factor por tipo. Los seis tipos afectados llevan `PORCENTAJE 100` (la exención en bruto), así que **B-03 debe aplicar el tope conjunto aparte**, sobre el acumulado anual del trabajador, o exentará de más.

  **Cuáles son esos seis no es hoy un dato consultable, y eso hay que resolverlo antes que B-03.** Hay 16 renglones con `base_exencion: PORCENTAJE` y los seis afectados (`015`, `029`, `030`, `034`, `035`, `037`) son **indistinguibles de los otros diez en cualquier campo que llegue a la base**: la marca solo vive en comentarios del YAML, y los comentarios no se cargan. La lista autoritativa mientras tanto es **§5.3.D de `config/fiscal/README.md`**. La salida correcta es una **bandera en el esquema** (`sujeto_a_tope_conjunto`) que la semilla llene, para que B-03 la lea del dato y no de una lista escrita en prosa; hasta que exista, cualquier implementación de B-03 estaría codificando una lista fiscal en el programa, que es justo lo que el §2.12 prohíbe.
2. **Factores cuyo multiplicador no viene en el CFDI:** "90 UMA por año de servicio" (separación), "15 UMA diarias", "1 UMA por domingo". El CFDI no trae los años de servicio ni el número de domingos. Cuando el multiplicador no sea derivable, **la columna del tope sale vacía con su bandera**, igual que cuando falta la UMA — nunca un tope calculado con un multiplicador supuesto.
3. **Las vacaciones no tienen tipo de percepción propio** en `c_TipoPercepcion`: se pagan dentro del `001`. Así que ninguna marca de este catálogo las identifica, y todo lo que dependa de distinguirlas tiene que salir de `map_concepto_provision`, por organización.
- **B-03.R2 — acumulación anual de topes.** Varias exenciones son **anuales, no por periodo** (el aguinaldo es el caso típico). El tope se evalúa contra el **acumulado del ejercicio** del mismo empleado y tipo, no contra el importe del periodo aislado. Bandera `EXENCION_EXCEDIDA` cuando el exento acumulado supera el tope anual. **Esta regla es la que hace el informe útil:** periodo por periodo casi nunca se excede, así que evaluarlo aislado no detectaría nada.
- **B-03.R3 — exención indebida.** Un tipo con `base_exencion = NINGUNA` e `importe_exento > 0` genera `EXENCION_INDEBIDA`. Hallazgo de auditoría directo.

- [ ] **Step 1: Write the failing tests**

Cada una con su aserción concreta:
1. Grano largo: un CFDI con tres percepciones da tres filas.
2. El porcentaje exento, sobre el importe total de la fila.
3. Con UMA **confirmada**, el tope de un tipo `UMA_DIAS` es `factor × UMA` y el exceso `max(0, exento − tope)`.
4. Con UMA confirmada, un tipo `PORCENTAJE` calcula el tope sobre el importe total.
5. **Con UMA propuesta pero sin confirmar:** columnas 14-17 vacías, **exactamente una** bandera `UMA_SIN_CONFIRMAR` que menciona la fuente, y las columnas 1-13 normales.
6. **Sin UMA en absoluto:** igual pero con `FALTA_UMA`.
7. **B-03.R2:** dos quincenas cuyo exento individual está bajo el tope pero cuyo **acumulado anual** lo supera → `EXENCION_EXCEDIDA`. Y su gemela negativa: si el acumulado no lo supera, no hay bandera.
8. **B-03.R3:** tipo con `NINGUNA` y exento > 0 → `EXENCION_INDEBIDA`.
9. Un tipo `SM_DIAS` **sin zona salarial configurada** → tope vacío, con su bandera; con zona `ZLFN` configurada → tope sobre 440.87.
10. `CURP` y `NSS` declaradas `sensible=True`; el informe **no** llama a `enmascarar()`.
11. Sin comprobantes en el rango → aviso, sin filas.
12. Orden de filas determinista entre corridas.

Usa `tests/helpers_nomina.insertar_nomina` y siembra la configuración **con el servicio** de la tarea 2, no con SQL directo: así las pruebas ejercitan el camino real, incluido el invariante de confirmación.

- [ ] **Step 2 a 4: fallar, implementar, registrar, pasar y commitear**

Sigue la estructura de `app/informes/b02_conceptos_patron.py`. Usa `universo_nomina.universo()` y las banderas comunes — **no reescribas el universo**. La acumulación anual de B-03.R2 necesita una consulta agregada por `(rfc_receptor, tipo_percepcion, ejercicio)`: **una consulta, no una por fila** (regla 11).

```bash
.venv/bin/pytest tests/test_informe_b03.py -q
.venv/bin/mypy --strict app
git add app/informes/ tests/ && git commit -m "feat(informes): agregar B-03 (desglose gravado/exento por percepcion)"
```

---

### Task 7b: `multiplicador_no_derivable` como dato

**Files:** `app/models/configuracion_fiscal.py`, una migración nueva, `app/services/configuracion_fiscal.py`, `config/fiscal/catalogo_percepcion.yaml`, `config/fiscal/README.md`, `app/api/v1/configuracion.py`, `app/api/v1/schemas.py`, `apps/web` (la sección de marcas), doc 05 §8bis, y `app/informes/b03_gravado_exento.py`.

**Por qué existe, y es la tercera vez en esta fase.** El cálculo del tope necesita saber qué tipos tienen un factor cuyo multiplicador **no viene en el CFDI** ("90 UMA por año de servicio", "15 UMA diarias", "1 UMA por domingo": el comprobante no trae los años de servicio ni el número de domingos). Son nueve tipos, y **hoy no son distinguibles de ninguna columna**: la información vive en comentarios y en la prosa del README.

Es exactamente el mismo defecto que ya se corrigió dos veces —`sujeto_a_tope_conjunto` y `nota_revision`— y la lección general vale la pena escribirla: **si el cálculo lo necesita, o si quien confirma tiene que verlo, tiene que ser una columna.** Un comentario no se carga y una lista en el programa viola el §2.12.

**Lo que reemplaza.** B-03 usa hoy `nota_revision` como aproximación: una marca con duda abierta no calcula tope. Funciona y falla del lado seguro, pero tiene dos defectos que su autor declaró: es **más conservadora de la cuenta** (39 de 44 marcas traen nota, solo nueve por este motivo, así que tipos perfectamente calculables salen vacíos) y **se desactiva sin querer** si alguien resuelve la nota sin corregir el modelo.

**El alcance completo, y por qué no se puede hacer a medias.** Hacerlo solo en el plano de datos reintroduce el defecto que ya costó una ronda: un campo que afecta el cálculo pero que no viaja en la respuesta del endpoint permite **confirmar sin verlo**. Así que la columna va acompañada de su exposición en los dos endpoints de marcas, de `_difieren`, de la bitácora, y de la pantalla.

- [ ] **Step 1:** columna en el modelo, con su justificación en el docstring, y migración (corre el ciclo `upgrade` → `downgrade -1` → `upgrade` **de verdad**).
- [ ] **Step 2:** el cargador la lee y la escribe, y entra en la detección de cambios que limpia la confirmación.
- [ ] **Step 3:** sembrarla para los nueve tipos, citando en el YAML **qué multiplicador falta** en cada uno.
- [ ] **Step 4:** exponerla en `MarcaPercepcionIn`/`Out`, en `_difieren` y en la bitácora; doc 05 §8bis.
- [ ] **Step 5:** la pantalla la muestra y la deja editar, junto a las otras marcas.
- [ ] **Step 6:** B-03 la usa **en lugar de** `nota_revision`, y su prueba correspondiente pasa a afirmar la columna. Verifica por mutación que un tipo con la bandera puesta deja el tope vacío y uno sin ella lo calcula.
- [ ] **Step 7:** `.venv/bin/mypy --strict app` limpio y commit.

**Recarga de semilla:** esta tarea sí necesita `alembic upgrade head` y recargar `catalogo_percepcion.yaml` sobre la base de desarrollo. **Deja el conteo de confirmadas como lo encuentres** y dilo en el informe.

---

### Task 8: Desbloquear la columna 11 de B-05 y las dos validaciones de SBC de B-10

**Files:**
- Modify: `app/informes/b05_acumulado_anual.py`, `app/informes/b10_validacion_receptor.py`
- Modify: `tests/test_informe_b05.py`, `tests/test_informe_b10.py`
- Modify: `docs/superpowers/specs/2026-08-05-informes-cfdi-nomina-design.md`

**Interfaces:**
- Consumes: `app/services/configuracion_fiscal.py`.
- Produces: ningún símbolo nuevo. Una columna en B-05 y dos validaciones en B-10.

**Por qué es su propia tarea.** Las dos cosas estaban fuera de alcance en la fase 2 **por falta de configuración**, y ahora existe. Son cambios pequeños en informes ya revisados: aislarlos hace que el diff diga exactamente qué se rompió si algo se rompe.

**La columna 11 de B-05, "Gravado ordinario":** `Σ importe_gravado` de las percepciones cuyo tipo tenga `es_ingreso_ordinario = true`. Es la base del cálculo anual del ISR, y **B-05.R4 es explícita**: los ingresos por separación y por jubilación tienen régimen propio (arts. 95 y 96 de la LISR) y **no** se acumulan al gravado ordinario. Sumarlos sobreestima el ISR anual.

**Degradación:** sin `catalogo_percepcion_marca`, la columna sale `None` con **una** bandera `FALTA_CATALOGO_DE_MARCAS`. Un cero ahí parecería "este empleado no tuvo ingreso ordinario".

**Las dos validaciones de B-10:**
- `SBC_SOBRE_TOPE`, severidad media: `salario_base_cot_apor > 25 × UMA_DIARIA` vigente a la fecha de pago.
- `SBC_BAJO_MINIMO`, severidad alta: `salario_base_cot_apor < salario_minimo_de_empresa(...)`.

**Degradación, y aquí está el detalle que importa:** si falta la UMA, o **si la empresa no tiene zona salarial configurada**, esas validaciones **no se evalúan** y se emite una bandera diciendo cuál falta. Y el conteo `VALIDACIONES_EJECUTADAS` que la fase 2 introdujo **debe reflejarlo**: una validación que no corre no se cuenta. Ajusta la prueba del conteo y **documenta por qué el número es variable ahora**.

**Nada de heurísticas para la zona.** El CFDI no dice en qué zona está el trabajador, y **no se infiere del código postal ni del domicilio**: se toma de la configuración de la empresa, que nace nula a propósito. Si es nula, la validación no corre y lo dice. Ciudad Juárez es ZLFN y su mínimo 2026 es 440.87 contra 315.04 del general — adivinar mal produce falsos negativos en una validación de cumplimiento.

- [ ] **Step 1: Write the failing tests**

B-05: la columna existe y suma solo los tipos ordinarios; separación y jubilación **no** entran; sin catálogo de marcas sale `None` con **una** bandera; con marcas sin confirmar aplica la misma degradación (las marcas del §3.1 son configuración, no ley con vigencia — **decide y documenta** si llevan confirmación o no, y sé consistente).

B-10: cada validación dispara con el dato malo y **no** dispara con el bueno (la gemela negativa importa: una validación que dispara siempre es peor que no tenerla); sin UMA no se evalúa `SBC_SOBRE_TOPE`; **sin zona salarial no se evalúa `SBC_BAJO_MINIMO`**, con bandera propia; con zona `ZLFN` un SBC de 400 dispara `SBC_BAJO_MINIMO` (440.87) y con zona `GENERAL` **no** (315.04) — esa pareja es la prueba de que la zona cambia el resultado; el conteo `VALIDACIONES_EJECUTADAS` refleja lo realmente evaluado en los tres casos.

- [ ] **Step 2 a 4: fallar, implementar, pasar, sincronizar el diseño y commitear**

Run: `.venv/bin/pytest tests/test_informe_b05.py tests/test_informe_b10.py -q`
Expected: PASS, y las pruebas anteriores de los dos informes **sin cambios de aserción** salvo la del conteo, que cambia por diseño.

Actualiza el §11 del diseño: la columna 11 de B-05 y las dos validaciones de B-10 ya no están fuera de alcance.

```bash
.venv/bin/mypy --strict app
git add app/informes/ tests/ docs/
git commit -m "feat(informes): desbloquear el gravado ordinario de B-05 y las validaciones de SBC de B-10"
```

---

### Task 9: B-06 · Costo de nómina por centro de costo

**Files:**
- Create: `app/informes/b06_centro_costo.py`
- Modify: `app/informes/registro.py`
- Test: `tests/test_informe_b06.py`

**Interfaces:**
- Produces: `CLAVE = "B-06"`, `TIPOS_COMPROBANTE = ("N",)`, `class Parametros` con `fecha_desde`, `fecha_hasta`, `detalle_empleado: bool = False`, `incluir_cancelados: bool = False`, `enmascarar_datos_personales: bool = True`; `async def consultar(...)`.

**Qué es.** Grano `(periodo, centro_costo)`, o `(periodo, centro_costo, empleado)` con `detalle_empleado`. Para una organización que ejecuta recursos etiquetados —el caso de este cliente— es el insumo de la comprobación ante el financiador.

**Columnas:** ejercicio, periodo, centro de costo, número de empleados, número de CFDI, días pagados, sueldos (tipo `001`), prestaciones (lo que no es `001` ni `046`), asimilados (`046`), total de percepciones, otros pagos, costo bruto, ISR retenido, IMSS obrero retenido, neto pagado, costo promedio por empleado, porcentaje del total del periodo.

**B-06.R1 — resolución del centro de costo, en cascada, reportando el nivel usado:**
1. `map_departamento` de la empresa, por el texto del departamento.
2. El texto crudo de `nomina_receptor.departamento`.

El nivel 1 de la ficha usa `plantilla_rh`, que no existe, así que la cascada tiene **dos** niveles y no tres. **Documéntalo.**

Al caer al texto crudo se emite `DEPARTAMENTO_SIN_MAPEO` **agregada**: una bandera con el conteo de filas afectadas y la lista de textos sin mapear, no una por fila. Y el informe **reporta cuántas filas resolvió en cada nivel**, para que la calidad del agrupamiento sea auditable — lo pide la ficha explícitamente.

**B-06.R3 — un empleado en varios centros:** cada CFDI se asigna al departamento declarado **en ese CFDI**. No se retropropaga el departamento actual.

**La columna 15 (costo patronal estimado) queda fuera de alcance.** **No declares la columna ni un parámetro para ella.**

- [ ] **Step 1: Write the failing tests**

Cubre: el grano por periodo y centro de costo; el desglose de sueldos, prestaciones y asimilados; con mapeo cargado agrupa por centro de costo; **sin mapeo** agrupa por el texto crudo y emite **una** bandera agregada con el conteo; **dos variantes ortográficas del mismo departamento sin mapeo caen en grupos distintos** (el problema que el mapeo resuelve — hay que verlo para saber que el mapeo sirve); `detalle_empleado` cambia el grano; el porcentaje del total del periodo suma 100; un empleado que cambia de departamento entre periodos se asigna al de cada CFDI; sin comprobantes, aviso; orden determinista.

- [ ] **Step 2 a 4: fallar, implementar, registrar, pasar y commitear**

```bash
.venv/bin/pytest tests/test_informe_b06.py -q
.venv/bin/mypy --strict app
git add app/informes/ tests/ && git commit -m "feat(informes): agregar B-06 (costo de nomina por centro de costo)"
```

---

### Task 10: B-08 · Provisión de pasivo laboral

**Files:**
- Create: `app/informes/b08_pasivo_laboral.py`
- Modify: `app/informes/registro.py`
- Test: `tests/test_informe_b08.py`

**Interfaces:**
- Produces: `CLAVE = "B-08"`, `TIPOS_COMPROBANTE = ("N",)`, `class Parametros` con `ejercicio: int`, `fecha_corte: date`, `dias_aguinaldo: int | None = None`, `factor_prima_vacacional: Decimal | None = None`, `incluir_cancelados: bool = False`, `enmascarar_datos_personales: bool = True`; `async def consultar(...)`.

**Qué es y con qué cuidado hay que tratarlo.** Grano: una fila por empleado. Cuantifica el **pasivo devengado no pagado** por aguinaldo, vacaciones y prima vacacional. Es la cifra que el auditor externo pide al cierre y **puede acabar en los estados financieros de la organización**.

**B-08.R3, que hay que respetar en la presentación:** esto es una **estimación con base en CFDI**, no un cálculo actuarial. No cubre prima de antigüedad ni beneficios al retiro (NIF D-3). **Rotúlalo en la hoja `Parámetros` del libro**, no solo en el docstring: quien reciba el Excel tiene que verlo.

**La condición para generarse no es "que existan filas en `map_concepto_provision`", sino que la clasificación esté completa.** Esta es la corrección de una versión anterior del plan, y el matiz decide si el informe sirve o no:

- Lo que B-08 necesita saber es **cuánto aguinaldo se pagó ya**, para restarlo del devengado. El devengado se calcula del salario y los días trabajados, sin necesidad del mapeo.
- Si algún concepto de percepción de la empresa **no tiene categoría asignada**, es imposible distinguir *"no se pagó aguinaldo"* de *"sí se pagó, pero no sé cuál concepto es"*. Ahí el informe **no se genera**, y el aviso dice **cuáles conceptos faltan por clasificar** — no un mensaje genérico.
- Pero si **todos** los conceptos observados están clasificados —incluidos los marcados explícitamente como `NO_APLICA`— entonces "aguinaldo pagado = 0" es un **hecho conocido**, no una laguna, y **el informe se genera con normalidad**. Una organización cuyo periodo no incluye diciembre tiene legítimamente cero aguinaldo pagado y una provisión igual al devengado completo.

Por eso `CategoriaProvision` incluye **`NO_APLICA`**: sin esa opción, marcar "este concepto no es ninguna de las tres" sería indistinguible de no haberlo revisado, y la clasificación nunca podría estar completa.

**No intentes inferir la categoría por el texto del concepto** — la ficha B-08.R2 lo prohíbe, y con razón: "Fondo ahorro empresa" y "Fondo de Ahorro Empleado" son conceptos distintos con el mismo texto casi idéntico.

**Los dos parámetros nacen `None` y se resuelven desde `configuracion_empresa`.** Si el parámetro viene nulo **y** la configuración también, el informe **no se genera** y dice que falta configurar los días de aguinaldo. **No uses 15 como default silencioso**: el mínimo legal es 15, pero muchas organizaciones dan más, y adivinar subestima la provisión. El parámetro explícito, cuando viene, gana sobre la configuración — es la corrida puntual con otro supuesto.

**B-08.R1 — el salario diario base, en orden de preferencia:**
1. `Σ (gravado + exento de tipo_percepcion='001') / Σ num_dias_pagados` de los **últimos 3 periodos ordinarios**. Derivable del CFDI y preferida.
2. `nomina_receptor.salario_diario_integrado` — **último recurso**, porque el SDI ya incluye la parte proporcional de aguinaldo y prima, así que usarlo **sobreestima la provisión** al integrar dos veces esos conceptos.

**Cada fila declara qué fuente usó.** Requisito de la ficha, no un extra.

**Columnas:** identidad del empleado, fecha de inicio de la relación laboral, antigüedad en años, salario diario base **con su fuente**, días de aguinaldo, aguinaldo devengado, aguinaldo pagado en el ejercicio, provisión de aguinaldo, días de vacaciones del año en curso (de `tabla_vacaciones` por antigüedad), vacaciones pagadas en el ejercicio, días de vacaciones pendientes, provisión de vacaciones, prima vacacional devengada, provisión total.

**Los días de vacaciones pendientes** requieren el saldo de RH, que no existe. Estímalo con el devengo proporcional y **declara en la columna que es una estimación**.

- [ ] **Step 1: Write the failing tests**

Cada una con su aserción: **sin `map_concepto_provision` no se genera y el aviso dice qué falta**; **sin días de aguinaldo configurados ni en parámetro, tampoco se genera** (y no asume 15); el parámetro explícito gana sobre la configuración; con todo cargado, el aguinaldo devengado es proporcional a los días trabajados del ejercicio; la provisión es `max(0, devengado − pagado)` y **nunca negativa**; el salario diario base sale de los últimos 3 periodos ordinarios y la fila declara esa fuente; sin percepciones de tipo `001` cae al SDI y **la fila declara la fuente de último recurso**; los días de vacaciones salen de `tabla_vacaciones` según antigüedad; la prima vacacional aplica el factor; la hoja `Parámetros` lleva el **rótulo de estimación**; `CURP`/`NSS` sensibles; orden determinista.

- [ ] **Step 2 a 4: fallar, implementar, registrar, pasar y commitear**

```bash
.venv/bin/pytest tests/test_informe_b08.py -q
.venv/bin/mypy --strict app
git add app/informes/ tests/ && git commit -m "feat(informes): agregar B-08 (provision de pasivo laboral)"
```

---

### Task 11: Verificación en vivo de los nueve informes y de la configuración

**Files:**
- Modify: `scripts/verificar_informes.py`
- Modify: `config/fiscal/README.md`

**Qué comprueba.** Que los **nueve** informes se generan contra los datos reales, que los tres nuevos degradan **como se prometió** en los tres estados de configuración, y que ninguno filtra datos personales.

- [ ] **Step 1: Cargar las semillas y verificar el catálogo**

```bash
.venv/bin/python -m app.scripts.cargar_configuracion_fiscal config/fiscal/tabla_vacaciones.yaml
.venv/bin/python -m app.scripts.cargar_configuracion_fiscal config/fiscal/catalogo_percepcion.yaml
.venv/bin/python -m app.scripts.cargar_configuracion_fiscal config/fiscal/param_fiscal.yaml
docker compose exec -T api python -c "
from app.informes import registro
for e in registro.catalogo():
    print(e['clave'], '|', e['nombre'], '| params:', sorted(e['parametros']['properties']))
"
```
Expected: nueve claves (B-01 a B-08 sin B-09, más B-10). **Ningún parámetro que no haga nada** — compáralo contra la tabla de alcance.

- [ ] **Step 2: Reiniciar worker y beat**

No recargan código ni el registro de informes. Sin esto, los tres informes nuevos y la tarea de vigencia fallan.

```bash
docker compose restart worker beat && sleep 10
docker compose exec -T worker celery -A app.worker.celery_app inspect registered | head -30
```

- [ ] **Step 3: Los tres estados de configuración, comprobados de verdad**

Genera B-03, B-06 y B-08 **en cada estado** y reporta la salida real:

1. **Sin confirmar nada** (recién sembrado): B-03 con columnas 14-17 vacías y **una** bandera `UMA_SIN_CONFIRMAR` que menciona la fuente; B-06 agrupando por texto crudo con **una** `DEPARTAMENTO_SIN_MAPEO`; B-08 **sin filas** y con el aviso de qué falta.
2. **Confirmando la UMA y el salario mínimo** por el endpoint (no por SQL: ejercita el camino real, incluida la bitácora): B-03 llena 14-17, y **verifica que la bitácora registró la confirmación**.
3. **Configurando zona salarial, días de aguinaldo, factor de prima y los dos mapeos** para la empresa real: B-06 agrupa por centro de costo, B-08 genera, y B-10 evalúa las dos validaciones de SBC con el conteo correcto.

**Si algo se comporta distinto de lo prometido, es un defecto: repórtalo, no lo acomodes.**

- [ ] **Step 4: Dejar la BD como estaba**

Quita las confirmaciones y la configuración de prueba que hayas puesto, **y dilo en el informe**: los valores reales los confirma el dueño del repo desde la pantalla. Si algo no se puede revertir limpiamente, dilo en vez de dejarlo a medias.

- [ ] **Step 5: Inspeccionar los nueve Excel**

Las cuatro hojas en cada uno; `CURP` y `NSS` enmascarados donde existan; `Parámetros` con usuario, fecha, versión del ETL y filtros; en B-08 el **rótulo de estimación**. Corre la auditoría anti-fuga de datos personales sobre los nueve, con la red completa (por patrón **y** por valor, en **todas** las hojas).

- [ ] **Step 6: Extender el script y commitear**

Que `scripts/verificar_informes.py` corra los nueve y compruebe además la degradación: con la configuración sin confirmar, que B-03 y B-06 emitan su bandera y que B-08 no genere filas. Actualiza `config/fiscal/README.md` con el estado real de qué está confirmado y qué falta.

```bash
.venv/bin/mypy --strict app
git add scripts/ config/ && git commit -m "test(informes): extender la verificacion en vivo a los nueve informes y a la configuracion"
```

---

## Notas de cierre

**Punto de control natural.** Las tareas 1 a 6 son el subsistema de configuración y las 7 a 11 los informes. Al terminar la 6 hay algo entregable por sí mismo —una pantalla de configuración fiscal con procedencia, confirmación y alarma de caducidad— así que es el lugar para revisar antes de seguir, si conviene partir la fase en dos entregas.

**Lo que queda listo al final:** los **nueve informes viables** del Grupo B (B-01 a B-08 y B-10), la configuración fiscal administrable desde la aplicación con procedencia y bitácora, y la alarma que avisa cuando un valor caducó.

**Lo que el dueño del repo tiene que hacer, y ahora es de un clic por valor:**
1. **Confirmar la UMA 2026** (117.31 diaria, vigente 1-feb-2026) y el **salario mínimo** (315.04 general, 440.87 ZLFN). Vienen sembrados con su liga al boletín del INEGI y al DOF.
2. **Elegir la zona salarial** de la empresa. Nace vacía a propósito; hasta que se elija, B-10 no evalúa el salario mínimo. Ciudad Juárez está en la ZLFN.
3. **Capturar los días de aguinaldo** y el **factor de prima vacacional** de la organización.
4. **Cargar el mapeo de departamentos a centros de costo.** Habilita el agrupamiento real de B-06.
5. **Mapear cuáles de sus claves internas son aguinaldo, vacaciones y prima vacacional.** Sin esto B-08 no se genera. En los datos reales las vacaciones se timbran como `P/001/019 "Vacaciones a tiempo"`, así que no se puede inferir.

**Y una revisión que le toca a una persona, no a una prueba:** las marcas del §3.1 sembradas en la tarea 3 (los factores de exención del art. 93 de la LISR). Las pruebas verifican coherencia interna; **la corrección fiscal la valida alguien**. El `config/fiscal/README.md` lista los tipos marcados `REVISAR` para que sepa dónde mirar.

**Deuda que esta fase deja anotada, no resuelta:**
- **La tarifa de ISR y el subsidio al empleo** (`tarifa_isr`) siguen sin cargarse, y con ellas B-09. Es el Anexo 8 de la RMF, en PDF, y B-09.R2 advierte de errores de dos órdenes de magnitud por una tasa mal capturada. Cuando se aborde, la captura tiene que ser tan revisable como la de esta fase.
- **Volumen.** El motor materializa todas las filas en memoria antes de escribir la primera celda. **B-03 es el informe de grano más fino de los nueve**: una fila por nodo de percepción, así que con 500 empleados, 24 quincenas y 5 percepciones por recibo son **60 000 filas** — mucho antes que los demás. Cuando se llegue a esa escala hay que paginar el motor, y B-03 es el que lo va a exigir primero.
- **`UMA_MENSUAL` y `UMA_ANUAL` se siembran pero ningún informe de esta fase las usa.** Se incluyen porque vienen del mismo boletín y confirmarlas de una vez es gratis; si dentro de dos fases nadie las ha usado, sobran.
