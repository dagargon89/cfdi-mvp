# Informes CFDI — Fase 2: B-01, B-04, B-05, B-07 y B-10

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar cinco informes de nómina sobre la capa normalizada y el motor que la fase 1 dejó funcionando, sin necesitar tablas de configuración fiscal.

**Architecture:** Cada informe es un módulo en `app/informes/` que declara `CLAVE`, `NOMBRE`, `GRUPO`, `DESCRIPCION`, `TIPOS_COMPROBANTE`, una clase `Parametros` de pydantic y una corrutina `consultar`, y se registra en `app/informes/registro.py`. El endpoint, la tarea de Celery, el libro de Excel de cuatro hojas, el enmascaramiento y la pantalla web **ya existen y no se tocan**: agregar un informe es un archivo y una línea en el registro. La única pieza compartida nueva es el eje teórico de periodos, que B-04 y B-07 necesitan.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async, `asyncmy`), Celery + Redis, MySQL 8, `satcfdi==26.7.4`, `openpyxl`, pytest + testcontainers, React + TypeScript + Vite.

**Referencias:**
- Diseño aprobado: `docs/superpowers/specs/2026-08-05-informes-cfdi-nomina-design.md`
- Documento fuente, fichas B-01 / B-04 / B-05 / B-07 / B-10: `Hub_CFDI_docs/00-fuentes/especificacion-informes-cfdi.md`
- **Implementación de referencia: `app/informes/b02_conceptos_patron.py`.** Es el informe que la fase 1 dejó terminado y revisado; su estructura, su manejo de banderas y su estilo de consulta son el patrón a seguir. Ábrelo antes de escribir cualquier informe nuevo.
- Plan de la fase 1, con el detalle de lo ya construido: `docs/superpowers/plans/2026-08-05-informes-cfdi-fase-1.md`

## Global Constraints

- **Claves de catálogo del SAT como texto** (`VARCHAR`/`str`), nunca entero: `001` ≠ `1`. Vale también para `num_empleado` y `clave` del patrón.
- **`Decimal` de punta a punta. Jamás `float`.** El redondeo ocurre **una sola vez**, en `app/informes/excel.py`, con `ROUND_HALF_UP`. **Ningún informe lleva `round()` ni `quantize()`.**
- **El motor enmascara, el informe declara.** Una columna sensible se marca `Columna(..., sensible=True)` y el motor la enmascara según el parámetro. **Ningún informe llama a `excel.enmascarar()`** — sería doble enmascaramiento.
- **Cero, no vacío** (R-T7): una celda de importe sin dato es `Decimal("0")`, nunca `None`.
- **Datos de terceros nunca en fixtures.** El dueño del repo autorizó usar el RFC y la razón social **de su propia empresa** (`CHL960913IX9` / CENTRO HUMANO DE LIDERAZGO) — es su dato y el RFC de una persona moral es público. Lo que **no** entra a ningún archivo versionado es dato de un tercero: nombres de proveedores o clientes, sus folios y sus importes reales, y **nunca** datos personales de empleados (CURP, NSS, cuentas bancarias), que son inventados siempre. Ver la tarea 1.
- **Cero N+1** — regla no negociable 11: los informes usan agregaciones y joins explícitos, no un `SELECT` por fila.
- Docstrings y comentarios en español. Sin imports sin usar. Sin línea de comentario con la ruta del archivo antes del docstring.
- **Verde obligatorio antes de cada commit:** `.venv/bin/pytest <archivos tocados> -q` y `.venv/bin/mypy --strict app`. **La suite completa la corre el controlador** (tarda ~10 min).
- **No lanzar nada en segundo plano.** Todo en primer plano; el timeout por comando admite hasta 600000 ms.
- **Cada informe nuevo se registra en `app/informes/registro.py`.** Sin eso no aparece en el catálogo y la pantalla web no lo ofrece.

## Alcance: lo que estos informes NO cubren, y por qué

Declararlo aquí evita parámetros que no hacen nada — el defecto que costó una ronda en la fase 1.

| Informe | Fuera de alcance | Razón |
|---|---|---|
| B-05 | Columna 11 "Gravado ordinario" | Requiere la marca `es_ingreso_ordinario` de `catalogo_percepcion_marca` (§3.1), tabla de la **fase 3**. El diseño §11 decía "columnas 1–23"; es un error del diseño detectado al planear la fase 2 |
| B-05 | Columnas 24–26 (ISR anual teórico y diferencia) | Requieren `tarifa_isr` por ejercicio y periodicidad |
| B-07 | Columnas 10–13 (monto original, saldo, liquidación) | El CFDI no contiene el monto original del préstamo; B-07.R2 dice explícitamente que **no** se estima. El informe conserva su valor como control de continuidad |
| B-10 | `SBC_SOBRE_TOPE` y `SBC_BAJO_MINIMO` | Requieren UMA diaria y salario mínimo de `param_fiscal` (**fase 3**). Quedan 21 de las 23 validaciones |
| B-10 | El formato pivotado (una fila por empleado, una columna por validación) | El parámetro `formato` de la ficha ofrece dos formas; se implementa solo el formato largo (una fila por hallazgo), que es el accionable. **No se declara el parámetro** para no exponer una opción sin efecto |
| B-04 | `fecha_baja` en el conteo de periodos esperados (B-04.R1) | Requiere `plantilla_rh`, que no existe. Se cuenta hasta `fecha_hasta` |

---

### Task 1: Reconciliar la regla 12 con la política real de datos

**Files:**
- Modify: `Hub_CFDI_docs/CLAUDE.md` (regla no negociable 12)

**Interfaces:**
- Consumes: nada.
- Produces: ningún símbolo. Solo la regla escrita, para que futuras sesiones no la reinterpreten.

**El problema que esta tarea resuelve.** La regla 12 de `Hub_CFDI_docs/CLAUDE.md` dice hoy:

> *"Nada sensible real en docs ni fixtures. RFC de prueba del SAT (`EKU9003173C9`, `XAXX010101000`), UUID ficticios, dominios `@demo.test`."*

Los fixtures de la fase 1 usan el RFC y la razón social **reales de la propia empresa del dueño del repo**, y él autorizó explícitamente que se queden así: es su dato y el RFC de una persona moral es información pública en México. Pero mientras la regla diga lo contrario, **cualquier sesión futura va a volver a "corregir" los fixtures** y a gastar una tarea en deshacer una decisión ya tomada — de hecho esta fase empezó así.

Lo que **sí** se mantiene prohibido, y hay que decirlo con precisión porque es la parte que importa:

- **Datos de terceros.** En la fase 1 apareció el nombre real de un proveedor (`AKBAL CONSULTORES`) con su folio e importes exactos en un fixture y en el documento del plan. Eso **no** es del dueño del repo autorizarlo, y ya se corrigió. No vuelve.
- **Datos personales, siempre.** CURP, NSS y cuentas bancarias de empleados reales son inventados sin excepción, en fixtures y en cualquier documento. Esto no admite matices: son datos personales de terceros bajo la LFPDPPP, no información de la empresa.
- **Salida de los informes.** El enmascaramiento por defecto no cambia; la regla 12 no lo gobierna, lo gobierna el §8 del diseño.

- [ ] **Step 1: Reescribir la regla 12**

En `Hub_CFDI_docs/CLAUDE.md`, sustituye la regla 12 por una que distinga los tres casos. Conserva el formato de las otras reglas (enunciado, luego *"Por qué:"*). El contenido debe decir, con estas palabras o equivalentes:

- Los datos de la **propia empresa** (RFC, razón social) **sí** pueden aparecer en fixtures y documentación: son suyos y el RFC de una moral es público.
- Los datos de **terceros** (nombres de clientes o proveedores, sus folios, sus importes) **no** entran a ningún archivo versionado, aunque aparezcan en los CFDI reales que el sistema procesa.
- Los **datos personales** (CURP, NSS, cuenta bancaria) son **siempre** inventados, sin excepción.
- Los UUID siguen siendo ficticios y los dominios de correo `@demo.test`.

Y el *"Por qué"*: la empresa es dueña de sus propios identificadores fiscales, pero no de los de sus contrapartes; y los datos personales de los empleados están protegidos por la LFPDPPP independientemente de quién sea el patrón.

- [ ] **Step 2: Verificar que la práctica actual cumple la regla nueva**

```bash
git grep -n "AKBAL\|17393\|16105\|1288\.40" -- tests/ app/ apps/ docs/ scripts/
```
Expected: sin resultados (más allá de hashes de Alembic que contengan esas cifras como subcadena; compruébalo caso por caso si aparece alguno).

```bash
git grep -rn "Curp=\|NumSeguridadSocial=\|CuentaBancaria=" -- tests/
```
Expected: solo valores inventados del tipo `XXXX800101HCHXXX01`, `12345678901`, `1234567890`. Si alguno parece una CURP real (estructura verosímil con nombre y fecha plausibles), sustitúyelo.

- [ ] **Step 3: Commit**

```bash
git add Hub_CFDI_docs/CLAUDE.md
git commit -m "docs: precisar la regla 12 — datos propios sí, de terceros no, personales nunca"
```

---

### Task 2: Eje teórico de periodos — pieza compartida de B-04 y B-07

**Files:**
- Create: `app/informes/periodos.py`
- Test: `tests/test_informes_periodos.py`

**Interfaces:**
- Consumes: nada del proyecto (módulo puro, sin BD).
- Produces:
  - `PERIODICIDADES_SOPORTADAS: frozenset[str]` = `{"02", "03", "04", "05", "06"}`
  - `@dataclass(frozen=True, slots=True) Corte` con `etiqueta: str`, `inicio: date`, `fin: date`
  - `def periodicidad_dominante(periodicidades: Sequence[str | None]) -> str | None` — la moda; `None` si no hay ninguna reconocida. Desempata por la clave menor como texto, para que sea determinista.
  - `def construir_eje(periodicidad: str, desde: date, hasta: date, *, primer_corte_observado: date | None = None) -> list[Corte]`
  - `def asignar_a_corte(eje: Sequence[Corte], fecha_final_pago: date) -> tuple[int, bool]` — devuelve `(índice del corte, es_irregular)`. `es_irregular` es `True` cuando la fecha no cae dentro de ningún corte y se asignó al más cercano.

**Por qué un módulo aparte.** B-04 lo necesita para su eje de columnas y B-07 para su control de continuidad (B-07.R1 compara la serie de descuentos contra "la secuencia teórica de B-04"). Escribirlo dos veces garantiza que divergan. Además es lógica de calendario pura, así que se prueba sin BD y sin contenedores.

- [ ] **Step 1: Write the failing test**

```python
"""Eje teórico de periodos de pago (ficha B-04, fase 1 del algoritmo).

Módulo puro: no toca BD. Lo consumen B-04 (eje de columnas) y B-07 (continuidad de
descuentos), así que su comportamiento es contrato entre los dos.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.informes import periodos


def test_periodicidad_dominante_es_la_moda() -> None:
    assert periodos.periodicidad_dominante(["04", "04", "05"]) == "04"


def test_periodicidad_dominante_ignora_nulos_y_desconocidas() -> None:
    assert periodos.periodicidad_dominante([None, "99", "04", "04"]) == "04"
    assert periodos.periodicidad_dominante([None, "99"]) is None
    assert periodos.periodicidad_dominante([]) is None


def test_periodicidad_dominante_desempata_de_forma_determinista() -> None:
    """Un empate no puede depender del orden de la lista: dos corridas del mismo informe
    deben producir el mismo eje de columnas."""
    assert periodos.periodicidad_dominante(["05", "04"]) == periodos.periodicidad_dominante(["04", "05"]) == "04"


def test_eje_quincenal_parte_el_mes_en_dos() -> None:
    eje = periodos.construir_eje("04", date(2026, 6, 1), date(2026, 7, 31))
    assert [c.etiqueta for c in eje] == ["2026-06 Q1", "2026-06 Q2", "2026-07 Q1", "2026-07 Q2"]
    assert (eje[0].inicio, eje[0].fin) == (date(2026, 6, 1), date(2026, 6, 15))
    assert (eje[1].inicio, eje[1].fin) == (date(2026, 6, 16), date(2026, 6, 30))
    # Julio tiene 31 días: el segundo corte llega al último día del mes, no al 30.
    assert eje[3].fin == date(2026, 7, 31)


def test_eje_mensual_usa_el_ultimo_dia_de_cada_mes() -> None:
    eje = periodos.construir_eje("05", date(2026, 1, 1), date(2026, 3, 31))
    assert [c.etiqueta for c in eje] == ["2026-01", "2026-02", "2026-03"]
    # Febrero de 2026 no es bisiesto.
    assert eje[1].fin == date(2026, 2, 28)


def test_eje_decenal_parte_el_mes_en_tres() -> None:
    eje = periodos.construir_eje("06", date(2026, 6, 1), date(2026, 6, 30))
    assert [(c.inicio.day, c.fin.day) for c in eje] == [(1, 10), (11, 20), (21, 30)]


def test_eje_semanal_arranca_en_el_primer_corte_observado() -> None:
    """`02` semanal y `03` catorcenal no tienen día fijo del mes: la ficha dice que la
    secuencia arranca en el primer corte observado en los datos."""
    eje = periodos.construir_eje("02", date(2026, 6, 1), date(2026, 6, 28), primer_corte_observado=date(2026, 6, 7))
    assert [c.fin for c in eje][:3] == [date(2026, 6, 7), date(2026, 6, 14), date(2026, 6, 21)]


def test_eje_catorcenal() -> None:
    eje = periodos.construir_eje("03", date(2026, 6, 1), date(2026, 7, 15), primer_corte_observado=date(2026, 6, 14))
    assert [c.fin for c in eje][:3] == [date(2026, 6, 14), date(2026, 6, 28), date(2026, 7, 12)]


def test_eje_semanal_sin_corte_observado_arranca_en_desde() -> None:
    eje = periodos.construir_eje("02", date(2026, 6, 1), date(2026, 6, 21))
    assert eje[0].fin == date(2026, 6, 7)


def test_periodicidad_no_soportada_lanza() -> None:
    with pytest.raises(ValueError):
        periodos.construir_eje("99", date(2026, 6, 1), date(2026, 6, 30))


def test_asignar_a_corte_exacto() -> None:
    eje = periodos.construir_eje("04", date(2026, 6, 1), date(2026, 6, 30))
    assert periodos.asignar_a_corte(eje, date(2026, 6, 30)) == (1, False)
    assert periodos.asignar_a_corte(eje, date(2026, 6, 15)) == (0, False)


def test_asignar_a_corte_irregular_va_al_mas_cercano() -> None:
    """La ficha B-04, fase 2: si `fecha_final_pago` no cae en un corte teórico, se asigna
    al más cercano y se marca `CORTE_IRREGULAR`."""
    eje = periodos.construir_eje("04", date(2026, 6, 1), date(2026, 6, 30))
    indice, irregular = periodos.asignar_a_corte(eje, date(2026, 5, 20))
    assert (indice, irregular) == (0, True)
    indice, irregular = periodos.asignar_a_corte(eje, date(2026, 7, 20))
    assert (indice, irregular) == (1, True)


def test_asignar_a_corte_con_eje_vacio() -> None:
    assert periodos.asignar_a_corte([], date(2026, 6, 30)) == (-1, True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_informes_periodos.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.informes.periodos'`

- [ ] **Step 3: Implementar el módulo**

```python
"""Eje teórico de periodos de pago (ficha B-04, fase 1 del algoritmo).

Módulo **puro**: calendario, sin BD y sin dependencias del proyecto. Lo consumen B-04
(eje de columnas de la matriz) y B-07 (control de continuidad de los descuentos), que la
ficha B-07.R1 define explícitamente contra "la secuencia teórica de B-04" — de ahí que
viva aquí y no dentro de un informe.

Las periodicidades con día fijo del mes (`04` quincenal, `05` mensual, `06` decenal) se
derivan del calendario. Las que no lo tienen (`02` semanal, `03` catorcenal) necesitan un
ancla: el primer corte observado en los datos.
"""

from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

PERIODICIDADES_SOPORTADAS = frozenset({"02", "03", "04", "05", "06"})

_DIAS_POR_PERIODICIDAD = {"02": 7, "03": 14}


@dataclass(frozen=True, slots=True)
class Corte:
    """Un periodo del eje. `fin` es el día de corte; `inicio` el día siguiente al corte
    anterior (o el primer día del periodo natural)."""

    etiqueta: str
    inicio: date
    fin: date


def periodicidad_dominante(periodicidades: Sequence[str | None]) -> str | None:
    """Moda de las periodicidades reconocidas. `None` si no hay ninguna.

    El desempate es por la clave menor como texto y no por orden de aparición: dos
    corridas del mismo informe tienen que producir el mismo eje de columnas.
    """
    frecuencias = Counter(p for p in periodicidades if p in PERIODICIDADES_SOPORTADAS)
    if not frecuencias:
        return None
    return min(frecuencias.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def _ultimo_dia(anio: int, mes: int) -> int:
    return calendar.monthrange(anio, mes)[1]


def _cortes_de_dia_fijo(periodicidad: str, desde: date, hasta: date) -> list[Corte]:
    """`04` quincenal (15 y último), `05` mensual (último), `06` decenal (10, 20, último)."""
    dias_de_corte = {"04": (15,), "05": (), "06": (10, 20)}[periodicidad]
    cortes: list[Corte] = []
    anio, mes = desde.year, desde.month
    while (anio, mes) <= (hasta.year, hasta.month):
        ultimo = _ultimo_dia(anio, mes)
        finales = [*dias_de_corte, ultimo]
        inicio_dia = 1
        for indice, dia_fin in enumerate(finales, start=1):
            inicio = date(anio, mes, inicio_dia)
            fin = date(anio, mes, dia_fin)
            if periodicidad == "05":
                etiqueta = f"{anio:04d}-{mes:02d}"
            else:
                etiqueta = f"{anio:04d}-{mes:02d} Q{indice}"
            cortes.append(Corte(etiqueta=etiqueta, inicio=inicio, fin=fin))
            inicio_dia = dia_fin + 1
        mes += 1
        if mes == 13:
            anio, mes = anio + 1, 1
    return cortes


def _cortes_de_paso_fijo(periodicidad: str, desde: date, hasta: date, ancla: date | None) -> list[Corte]:
    """`02` semanal y `03` catorcenal: no tienen día fijo del mes, así que la secuencia se
    ancla en el primer corte observado en los datos (ficha B-04, fase 1). Sin ancla se usa
    `desde` más un paso, que es lo mejor que se puede hacer sin datos."""
    paso = _DIAS_POR_PERIODICIDAD[periodicidad]
    primer_fin = ancla if ancla is not None else desde + timedelta(days=paso - 1)
    # Retrocede hasta el primer corte que caiga en el rango o justo antes de `desde`.
    while primer_fin - timedelta(days=paso) >= desde:
        primer_fin -= timedelta(days=paso)

    cortes: list[Corte] = []
    fin = primer_fin
    indice = 1
    while fin <= hasta:
        inicio = fin - timedelta(days=paso - 1)
        cortes.append(Corte(etiqueta=f"{fin.year:04d}-S{indice:02d}", inicio=inicio, fin=fin))
        fin += timedelta(days=paso)
        indice += 1
    return cortes


def construir_eje(
    periodicidad: str,
    desde: date,
    hasta: date,
    *,
    primer_corte_observado: date | None = None,
) -> list[Corte]:
    """Secuencia teórica de cortes en `[desde, hasta]`. Lanza `ValueError` si la
    periodicidad no está soportada: un eje silenciosamente vacío produciría una matriz sin
    columnas y nadie sabría por qué."""
    if periodicidad not in PERIODICIDADES_SOPORTADAS:
        raise ValueError(f"Periodicidad no soportada para el eje de periodos: {periodicidad!r}.")
    if periodicidad in _DIAS_POR_PERIODICIDAD:
        return _cortes_de_paso_fijo(periodicidad, desde, hasta, primer_corte_observado)
    return _cortes_de_dia_fijo(periodicidad, desde, hasta)


def asignar_a_corte(eje: Sequence[Corte], fecha_final_pago: date) -> tuple[int, bool]:
    """`(índice del corte, es_irregular)`. La asignación es por `fecha_final_pago` y no por
    `fecha_pago`, porque el pago puede adelantarse o retrasarse sin que cambie el periodo
    devengado (ficha B-04, fase 2).

    `es_irregular` es `True` cuando la fecha no cae dentro de ningún corte; entonces se
    asigna al más cercano y el informe emite `CORTE_IRREGULAR`.
    """
    if not eje:
        return -1, True
    for indice, corte in enumerate(eje):
        if corte.inicio <= fecha_final_pago <= corte.fin:
            return indice, False

    def distancia(par: tuple[int, Corte]) -> int:
        corte = par[1]
        if fecha_final_pago < corte.inicio:
            return (corte.inicio - fecha_final_pago).days
        return (fecha_final_pago - corte.fin).days

    indice, _ = min(enumerate(eje), key=distancia)
    return indice, True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_informes_periodos.py -q`
Expected: PASS (12 tests)

Si `test_eje_semanal_arranca_en_el_primer_corte_observado` falla, revisa el retroceso del ancla en `_cortes_de_paso_fijo`: debe dejar el primer corte dentro del rango, no antes.

- [ ] **Step 5: Type-check and commit**

```bash
.venv/bin/mypy --strict app
git add app/informes/periodos.py tests/test_informes_periodos.py
git commit -m "feat(informes): agregar eje teorico de periodos compartido por B-04 y B-07"
```

---

### Task 3: B-01 · Nómina agrupada por catálogo SAT

**Files:**
- Create: `app/informes/b01_catalogo_sat.py`
- Modify: `app/informes/catalogos.py` (enumeración de un catálogo completo)
- Modify: `app/informes/registro.py`
- Test: `tests/test_informe_b01.py`
- Test: `tests/test_informes_catalogos.py` (pruebas de la enumeración)

**Interfaces:**
- Consumes: `app/informes/base.py` (`Columna`, `Bandera`, `ResultadoInforme`), `app/informes/catalogos.py`, los modelos de `app/models/nomina.py` y `app/models/cfdi_detalle.py`.
- Produces:
  - En `catalogos.py`: `def tipos_de(naturaleza: str) -> list[tuple[str, str]]` — todas las claves de un catálogo con su descripción, ordenadas por clave como texto.
  - `CLAVE = "B-01"`, `NOMBRE`, `GRUPO = "B"`, `DESCRIPCION`, `TIPOS_COMPROBANTE = ("N",)`
  - `class Parametros(BaseModel)`: `fecha_desde: date`, `fecha_hasta: date`, `tipo_nomina: Literal["O","E","AMBOS"] = "AMBOS"`, `incluir_cancelados: bool = False`, `solo_tipos_con_movimiento: bool = False`, `enmascarar_datos_personales: bool = True`
  - `async def consultar(db, empresa_id, p) -> ResultadoInforme`

**La diferencia esencial con B-02, y es el propósito del informe.** B-02 genera una columna por cada concepto **observado en los datos**, con las claves internas del patrón. B-01 genera una columna por cada tipo **del catálogo del SAT**, esté o no en los datos, con cero cuando no hay movimiento (B-01.R1). Eso lo hace comparable entre periodos y entre organizaciones, que es lo que se necesita para alimentar pólizas contables: el conjunto de columnas no cambia de un mes a otro.

**El costo de eso:** 46 tipos de percepción + 107 de deducción + los de otros pagos ≈ **más de 150 columnas**. Por eso existe `solo_tipos_con_movimiento` (B-01.R2), que restringe al conjunto observado. Cuando se activa, **el informe deja de ser comparable y hay que rotularlo**: emite una bandera informativa que lo diga, para que quien reciba el Excel no lo compare contra otro mes creyendo que las columnas coinciden.

- [ ] **Step 1: Descubrir cómo enumerar un catálogo completo de satcfdi**

La fase 1 dejó `catalogos.py` resolviendo **una** clave con `satcfdi.catalogs.catalog_code(tabla, clave)` contra el SQLite embebido del paquete. Para B-01 hace falta **enumerar** la tabla entera, y eso no está confirmado. Averígualo:

```bash
.venv/bin/python -c "
import satcfdi.catalogs as cat
print('publico:', [n for n in dir(cat) if not n.startswith('_')])
import inspect
print(inspect.getsource(cat.catalog_code))
"
```

y localiza el archivo de la base:

```bash
.venv/bin/python -c "
import satcfdi.catalogs as cat, os
print(os.path.dirname(cat.__file__))
print(os.listdir(os.path.dirname(cat.__file__)))
"
```

Con la ruta del `.db`, enumera con `sqlite3` de la biblioteca estándar:

```bash
.venv/bin/python -c "
import sqlite3, satcfdi.catalogs as cat, os
ruta = os.path.join(os.path.dirname(cat.__file__), 'catalogs.db')
con = sqlite3.connect(f'file:{ruta}?mode=ro', uri=True)
print(con.execute(\"select count(*) from C75b_c_TipoPercepcion\").fetchone())
print(con.execute(\"select * from C75b_c_TipoPercepcion limit 3\").fetchall())
print([r[0] for r in con.execute(\"select name from sqlite_master where type='table' and name like '%TipoDeduccion%'\")])
"
```

**Documenta en el informe la forma real que encontraste.** Si el nombre de la tabla o de las columnas difiere, ajusta el código del paso 3 a lo real; **no relajes las aserciones de las pruebas**, que exigen los conteos y descripciones verdaderos del catálogo.

- [ ] **Step 2: Write the failing tests for the enumeration**

Agrega a `tests/test_informes_catalogos.py`:

```python
def test_tipos_de_percepcion_trae_el_catalogo_completo() -> None:
    """B-01.R1 genera una columna por tipo del catálogo, no por tipo observado, así que
    necesita la lista completa."""
    tipos = catalogos.tipos_de("P")
    claves = [clave for clave, _ in tipos]
    # El catálogo del SAT llega al menos hasta el 046; el conteo exacto puede cambiar con
    # la versión de satcfdi, así que se asevera el piso y las claves conocidas.
    assert len(claves) >= 40
    assert "001" in claves and "046" in claves
    # Claves como texto, con sus ceros a la izquierda intactos.
    assert all(isinstance(c, str) for c in claves)
    assert dict(tipos)["001"] == "Sueldos, Salarios Rayas y Jornales"


def test_tipos_de_deduccion_y_otro_pago() -> None:
    deducciones = dict(catalogos.tipos_de("D"))
    assert len(deducciones) >= 100
    assert "002" in deducciones and "ISR" in deducciones["002"]
    otros = dict(catalogos.tipos_de("O"))
    assert "002" in otros


def test_tipos_de_esta_ordenado_por_clave_como_texto() -> None:
    """El orden de las columnas del informe depende de esto y debe ser estable."""
    claves = [c for c, _ in catalogos.tipos_de("P")]
    assert claves == sorted(claves)


def test_tipos_de_naturaleza_desconocida_devuelve_vacio() -> None:
    assert catalogos.tipos_de("X") == []
```

- [ ] **Step 3: Implementar la enumeración**

En `app/informes/catalogos.py`, junto a lo que ya existe:

```python
_TABLA_POR_NATURALEZA = {"P": "C75b_c_TipoPercepcion", "D": "C75b_c_TipoDeduccion", "O": "C75b_c_TipoOtroPago"}


@lru_cache(maxsize=8)
def tipos_de(naturaleza: str) -> tuple[tuple[str, str], ...]:
    """Todas las claves de un catálogo con su descripción, ordenadas por clave **como
    texto**. B-01 genera una columna por cada una (B-01.R1), esté o no en los datos.

    Se consulta el SQLite embebido de `satcfdi` en modo solo lectura. Devuelve una tupla
    (no una lista) porque `lru_cache` exige un valor inmutable; los llamadores la tratan
    como secuencia.
    """
    tabla = _TABLA_POR_NATURALEZA.get(naturaleza)
    if tabla is None:
        return ()
    import os
    import sqlite3

    import satcfdi.catalogs as catalogs_pkg

    ruta = os.path.join(os.path.dirname(catalogs_pkg.__file__), "catalogs.db")
    try:
        con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        try:
            filas = con.execute(f"SELECT id, texto FROM {tabla}").fetchall()  # noqa: S608 — tabla de un mapa fijo
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 — un catálogo ilegible no debe abortar el informe
        logger.warning("No se pudo enumerar el catálogo %s: %s", tabla, exc)
        return ()
    return tuple(sorted(((str(clave), str(texto)) for clave, texto in filas), key=lambda par: par[0]))
```

**Nota:** los nombres de columna `id` y `texto` son una suposición. El paso 1 te dice los reales; ajústalos y deja el nombre correcto en el código y en el informe. Devuelve una tupla por `lru_cache`, pero las pruebas la comparan con `==` contra listas — usa `list(...)` en la firma pública si eso resulta más limpio, y ajusta las pruebas en consecuencia declarándolo en el informe.

- [ ] **Step 4: Run the enumeration tests**

Run: `.venv/bin/pytest tests/test_informes_catalogos.py -q`
Expected: PASS (las 3 previas más las 4 nuevas)

- [ ] **Step 5: Write the failing tests for B-01**

```python
"""B-01 · Nómina agrupada por catálogo SAT.

La diferencia esencial con B-02 (B-01.R1): las columnas de tipo se generan desde el
**catálogo**, no desde los datos, con cero cuando no hay movimiento. Eso hace el informe
comparable entre periodos, que es lo que exige una póliza contable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b01_catalogo_sat as b01
from tests import factories
from tests.helpers_nomina import insertar_nomina  # helper compartido; ver nota del paso 6


def _p(**kw: object) -> b01.Parametros:
    base = {"fecha_desde": date(2026, 6, 1), "fecha_hasta": date(2026, 7, 31)}
    base.update(kw)
    return b01.Parametros(**base)  # type: ignore[arg-type]


def _titulos(resultado: object) -> list[str]:
    return [c.titulo for c in resultado.columnas]  # type: ignore[attr-defined]


async def test_columnas_vienen_del_catalogo_no_de_los_datos(db: AsyncSession) -> None:
    """El corazón de B-01.R1: un tipo que NO está en los datos igual tiene su columna."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111",
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")])

    resultado = await b01.consultar(db, empresa.empresa_id, _p())
    titulos = _titulos(resultado)

    # El tipo 002 (aguinaldo) no aparece en los datos y sí debe tener columna.
    assert any(t.startswith("P 002") for t in titulos), titulos
    # Y muchas columnas: el catálogo completo, no las dos del comprobante.
    dinamicas = [t for t in titulos if t.startswith(("P ", "D ", "O "))]
    assert len(dinamicas) > 100, len(dinamicas)


async def test_celda_sin_movimiento_es_cero_no_vacio(db: AsyncSession) -> None:
    """R-T7. Un nulo en columna de importe rompe cualquier suma en hoja de cálculo."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="22222222-2222-2222-2222-222222222222",
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")])

    resultado = await b01.consultar(db, empresa.empresa_id, _p())
    titulos = _titulos(resultado)
    indice_002 = next(i for i, t in enumerate(titulos) if t.startswith("P 002"))
    assert resultado.filas[0][indice_002] == Decimal("0")


async def test_agrupa_por_tipo_no_por_clave_del_patron(db: AsyncSession) -> None:
    """Dos claves internas distintas del mismo tipo del catálogo caen en la misma columna.
    Es exactamente lo contrario de B-02, y el motivo de que este informe exista."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="33333333-3333-3333-3333-333333333333",
                          percepciones=[("001", "001", "Sueldo", "5000.00", "0.00"),
                                        ("001", "077", "Sueldo eventual", "3000.00", "0.00")])

    resultado = await b01.consultar(db, empresa.empresa_id, _p())
    titulos = _titulos(resultado)
    indice_001 = next(i for i, t in enumerate(titulos) if t.startswith("P 001"))
    assert resultado.filas[0][indice_001] == Decimal("8000.00")


async def test_solo_tipos_con_movimiento_reduce_y_avisa(db: AsyncSession) -> None:
    """B-01.R2: al activarlo el informe deja de ser comparable entre periodos, así que
    tiene que decirlo — si no, alguien compara dos meses con columnas distintas."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="44444444-4444-4444-4444-444444444444",
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                          deducciones=[("002", "045", "ISR", "500.00")])

    completo = await b01.consultar(db, empresa.empresa_id, _p())
    reducido = await b01.consultar(db, empresa.empresa_id, _p(solo_tipos_con_movimiento=True))

    dinamicas_completo = [t for t in _titulos(completo) if t.startswith(("P ", "D ", "O "))]
    dinamicas_reducido = [t for t in _titulos(reducido) if t.startswith(("P ", "D ", "O "))]
    assert len(dinamicas_reducido) < len(dinamicas_completo)
    assert len(dinamicas_reducido) == 2, dinamicas_reducido
    assert any(b.clave == "CONJUNTO_REDUCIDO" for b in reducido.banderas)
    assert not any(b.clave == "CONJUNTO_REDUCIDO" for b in completo.banderas)


async def test_curp_y_nss_se_declaran_sensibles(db: AsyncSession) -> None:
    """El motor enmascara según la marca; el informe solo la declara."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="55555555-5555-5555-5555-555555555555")

    resultado = await b01.consultar(db, empresa.empresa_id, _p())
    por_titulo = {c.titulo: c for c in resultado.columnas}
    assert por_titulo["CURP"].sensible is True
    assert por_titulo["NSS"].sensible is True
    assert por_titulo["RFC empleado"].sensible is False


async def test_subsidio_causado_y_aplicado(db: AsyncSession) -> None:
    """Definiciones de B-00: `subsidio` sale de `subsidio_causado` del otro pago 002, y
    `subsidio_aplicado` de su `importe`."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="66666666-6666-6666-6666-666666666666",
                          otros_pagos=[("002", "035", "Subsidio", "120.00", "200.00")])

    resultado = await b01.consultar(db, empresa.empresa_id, _p())
    titulos = _titulos(resultado)
    fila = resultado.filas[0]
    assert fila[titulos.index("Subsidio causado")] == Decimal("200.00")
    assert fila[titulos.index("Subsidio aplicado")] == Decimal("120.00")


async def test_sin_comprobantes_devuelve_aviso(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    resultado = await b01.consultar(db, empresa.empresa_id, _p(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31)))
    assert resultado.filas == []
    assert resultado.aviso is not None


async def test_orden_de_columnas_es_determinista(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="77777777-7777-7777-7777-777777777777")
    primera = await b01.consultar(db, empresa.empresa_id, _p())
    segunda = await b01.consultar(db, empresa.empresa_id, _p())
    assert _titulos(primera) == _titulos(segunda)
```

- [ ] **Step 6: Extraer el helper de inserción de nóminas a un módulo compartido**

`tests/test_informe_b02.py` tiene un helper `_nomina(...)` que inserta un CFDI de nómina normalizado. Los cinco informes de esta fase lo necesitan. **Extráelo** a `tests/helpers_nomina.py` como `insertar_nomina(...)`, con la misma semántica, y haz que `test_informe_b02.py` lo importe en lugar de su copia local.

Requisitos del helper:
- Firma con `keyword-only`: `empresa_id`, `uuid`, y opcionales `num_empleado`, `rfc_receptor`, `rfc_emisor`, `curp`, `nss`, `fecha_pago`, `fecha_inicial_pago`, `fecha_final_pago`, `periodicidad`, `tipo_nomina`, `dias`, `percepciones`, `deducciones`, `otros_pagos`, `total_percepciones`, `total_deducciones`, `total_otros_pagos`, `total_separacion`, `total_jubilacion`, `total`, `estatus`, `tipo_regimen`, `sbc`, `sdi`, `departamento`, `puesto`, `fecha_inicio_rel_laboral`, `banco`, `cuenta_bancaria`, `antiguedad`. **Declara los 31 desde el principio**, aunque las pruebas de B-01 solo usen unos pocos: los informes de las tareas 4 a 7 usan el resto, y agregarlos a mitad del plan deja pruebas escritas contra una firma que aún no existe.
- `rfc_emisor` por defecto es el de la empresa (`CHL960913IX9`), porque B-01, B-02, B-04, B-05 y B-07 filtran el universo por emisor: un default distinto vaciaría todos los informes y las pruebas fallarían con un mensaje confuso. B-05 lo sobrescribe a propósito para probar `MULTI_PATRON`.
- `total_separacion` y `total_jubilacion` alimentan `NominaTotales.total_separacion_indemnizacion` y `total_jubilacion_pension_retiro`, que son columnas de B-01 y de B-05 y hoy no tienen ninguna prueba con valor no nulo en todo el proyecto (deuda que la revisión final de la fase 1 dejó anotada).
- **`None` significa "usa el default", no "vacío"** — usa `if x is None:`, nunca `x or default`: una lista vacía es *falsy* en Python y ese fue un defecto real del plan de la fase 1.
- Las tuplas de `otros_pagos` llevan 5 elementos: `(tipo, clave, concepto, importe, subsidio_causado)`.
- Devuelve el `comprobante_id`.
- **Datos de la propia empresa sí, de terceros y personales no** (ver tarea 1): RFC `CHL960913IX9` para la empresa emisora, receptor genérico `XAXX010101000`, y **CURP y NSS siempre inventados**.

Verifica que B-02 siga verde después de la extracción: `.venv/bin/pytest tests/test_informe_b02.py -q`.

- [ ] **Step 7: Run the B-01 tests to verify they fail**

Run: `.venv/bin/pytest tests/test_informe_b01.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.informes.b01_catalogo_sat'`

- [ ] **Step 8: Implementar B-01**

Sigue la estructura de `app/informes/b02_conceptos_patron.py` — ábrelo y cópiala. Puntos concretos:

- `TIPOS_COMPROBANTE = ("N",)` para que el pre-vuelo se acote (lo consume la tarea de Celery).
- El universo es el mismo que B-02 (mismo `_universo`: tipo `N`, emitidos por la empresa, `fecha_pago` en rango, `tipo_nomina`, estatus, `outerjoin` a `ComprobanteDetalle` y a `NominaTotales`). **Reusa el criterio, no lo reinventes**: si difieren, dos informes del mismo periodo darán distintos totales y nadie sabrá cuál creer. Extrae el universo a una función compartida si te resulta más limpio, y dilo en el informe.
- Las columnas dinámicas salen de `catalogos.tipos_de("P" | "O" | "D")`, en ese orden de naturaleza (percepciones, otros pagos, deducciones, como el orden de lectura de un recibo), y dentro de cada una por clave como texto.
- Título de columna: `f"{naturaleza} {tipo} {descripcion}"` con un separador legible. **No uses el separador `¦` de B-02**: aquí no hay clave del patrón ni riesgo de ambigüedad por diagonales, y el título debe leerse bien en una cabecera de Excel. Documenta la decisión en el docstring.
- La agregación es `SUM` en la BD agrupando por `(comprobante_id, tipo)` — **sin** la clave del patrón, que es justo la diferencia con B-02.
- Las columnas fijas (identificación, nómina, patrón, empleado, totales, subsidio, neto) son las de la ficha; `CURP` y `NSS` con `sensible=True`.
- Banderas: `CONJUNTO_REDUCIDO` (informativa, severidad baja) cuando `solo_tipos_con_movimiento`; y reusa las de B-02 que apliquen al mismo universo (`TOTALES_DESCUADRADOS`, `SIN_NORMALIZAR`, `COMPLEMENTO_AUSENTE`, `DATOS_DE_CORRIDA_ANTERIOR`, `ESTATUS_NO_VERIFICADO`, `COMPROBANTE_CANCELADO`). **Si esa lógica ya está en B-02, extráela a un módulo compartido** en vez de duplicarla; la revisión final de la fase 1 señaló la duplicación entre informes como el riesgo principal de esta fase.
- Sin `round()` ni `quantize()`.

- [ ] **Step 9: Registrar el informe**

En `app/informes/registro.py`, agrega el import y la entrada en `_MODULOS`.

- [ ] **Step 10: Run tests and commit**

Run: `.venv/bin/pytest tests/test_informe_b01.py tests/test_informe_b02.py tests/test_informes_catalogos.py -q`
Expected: PASS

```bash
.venv/bin/mypy --strict app
git add app/informes/ tests/ && git commit -m "feat(informes): agregar B-01 (nomina agrupada por catalogo SAT)"
```

---

### Task 4: B-04 · Matriz empleado × periodo

**Files:**
- Create: `app/informes/b04_matriz_empleado_periodo.py`
- Modify: `app/informes/registro.py`
- Test: `tests/test_informe_b04.py`

**Interfaces:**
- Consumes: `app/informes/periodos.py` (tarea 2), `base.py`, los modelos de nómina, `tests/helpers_nomina.insertar_nomina` (tarea 3).
- Produces: `CLAVE = "B-04"`, `TIPOS_COMPROBANTE = ("N",)`, `class Parametros` con `fecha_desde`, `fecha_hasta`, `metrica: Literal["NETO","TOTAL_PERCEPCIONES","GRAVADO","ISR_RETENIDO","DIAS_PAGADOS","NUM_CFDI"] = "NETO"`, `incluir_cancelados: bool = False`, `enmascarar_datos_personales: bool = True`; y `async def consultar(...)`.

**El grano cambia respecto a los informes anteriores:** una fila por **empleado** (no por CFDI) y una columna por **periodo de pago**. Es el informe de control de completitud: sirve para ver de un golpe qué quincenas faltan.

**Reglas que las pruebas fijan:**
- La asignación de un CFDI a un periodo es por **`fecha_final_pago`**, no por `fecha_pago`: el pago puede adelantarse o retrasarse sin que cambie el periodo devengado.
- `PERIODO_FALTANTE` solo cuando la celda está vacía **y** el mismo empleado tiene un CFDI en un periodo **posterior** dentro del rango. Un hueco al final es una baja probable, no un error; un hueco intermedio es una omisión de timbrado. **Esta distinción es la razón de ser del informe: confundirla lo vuelve inútil por exceso de falsos positivos.**
- `VARIACION_ANOMALA` cuando la variación relativa contra el periodo anterior supera 30 % **y** ambos tienen los mismos días pagados. La condición sobre días evita marcar quincenas cortas legítimas.
- `PERIODO_DUPLICADO` cuando una celda tiene más de un CFDI con `tipo_nomina='O'`: dos nóminas ordinarias del mismo periodo para el mismo empleado casi siempre son un timbrado doble.
- `CORTE_IRREGULAR` cuando `fecha_final_pago` no cae en ningún corte teórico.

- [ ] **Step 1: Write the failing tests**

```python
"""B-04 · Matriz empleado × periodo. Informe de control de completitud."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b04_matriz_empleado_periodo as b04
from tests import factories
from tests.helpers_nomina import insertar_nomina


def _p(**kw: object) -> b04.Parametros:
    base = {"fecha_desde": date(2026, 6, 1), "fecha_hasta": date(2026, 7, 31)}
    base.update(kw)
    return b04.Parametros(**base)  # type: ignore[arg-type]


async def _empresa(db: AsyncSession) -> int:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    return empresa.empresa_id


async def test_una_fila_por_empleado_y_una_columna_por_periodo(db: AsyncSession) -> None:
    eid = await _empresa(db)
    for indice, rfc in enumerate(("XAXX010101000", "XEXX010101000")):
        for quincena, (ini, fin) in enumerate(((date(2026, 6, 16), date(2026, 6, 30)),
                                               (date(2026, 7, 1), date(2026, 7, 15)))):
            await insertar_nomina(db, empresa_id=eid, uuid=f"1111111{indice}-1111-1111-1111-11111111111{quincena}",
                                  rfc_receptor=rfc, num_empleado=f"03{indice}",
                                  fecha_pago=fin, fecha_inicial_pago=ini, fecha_final_pago=fin, total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert len(resultado.filas) == 2
    titulos = [c.titulo for c in resultado.columnas]
    assert "2026-06 Q2" in titulos and "2026-07 Q1" in titulos
    # El eje cubre el rango completo, no solo los periodos con datos.
    assert "2026-06 Q1" in titulos and "2026-07 Q2" in titulos


async def test_asigna_por_fecha_final_pago_no_por_fecha_pago(db: AsyncSession) -> None:
    """El pago se adelantó al 28 de junio, pero el periodo devengado termina el 30: la
    celda que se llena es la de la segunda quincena de junio."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="22222222-2222-2222-2222-222222222222",
                          fecha_pago=date(2026, 6, 28), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    titulos = [c.titulo for c in resultado.columnas]
    fila = resultado.filas[0]
    assert fila[titulos.index("2026-06 Q2")] == Decimal("8000.00")
    assert fila[titulos.index("2026-06 Q1")] in (None, Decimal("0"))


async def test_hueco_intermedio_marca_periodo_faltante(db: AsyncSession) -> None:
    """B-04.R2: falta la Q1 de julio y hay CFDI en la Q2 posterior → omisión de timbrado."""
    eid = await _empresa(db)
    for uuid_cfdi, (ini, fin) in (("33333333-3333-3333-3333-333333333331", (date(2026, 6, 16), date(2026, 6, 30))),
                                  ("33333333-3333-3333-3333-333333333332", (date(2026, 7, 16), date(2026, 7, 31)))):
        await insertar_nomina(db, empresa_id=eid, uuid=uuid_cfdi, fecha_pago=fin,
                              fecha_inicial_pago=ini, fecha_final_pago=fin, total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    faltantes = [b for b in resultado.banderas if b.clave == "PERIODO_FALTANTE"]
    assert faltantes, resultado.banderas
    assert any("2026-07 Q1" in b.mensaje for b in faltantes)


async def test_hueco_al_final_no_marca_periodo_faltante(db: AsyncSession) -> None:
    """B-04.R2 al revés: un hueco al final de la serie es una baja probable, no un error.
    Marcarlo llenaría el informe de falsos positivos y lo volvería inútil."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="44444444-4444-4444-4444-444444444444",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert not [b for b in resultado.banderas if b.clave == "PERIODO_FALTANTE"]


async def test_periodo_duplicado(db: AsyncSession) -> None:
    """B-04.R4: dos nóminas ordinarias del mismo empleado y periodo casi siempre son un
    timbrado doble."""
    eid = await _empresa(db)
    for sufijo in ("1", "2"):
        await insertar_nomina(db, empresa_id=eid, uuid=f"5555555{sufijo}-5555-5555-5555-555555555555",
                              fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                              fecha_final_pago=date(2026, 6, 30), tipo_nomina="O", total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert any(b.clave == "PERIODO_DUPLICADO" for b in resultado.banderas)


async def test_variacion_anomala_solo_con_dias_iguales(db: AsyncSession) -> None:
    """B-04.R3: la condición sobre los días pagados evita marcar quincenas cortas
    legítimas (un alta a media quincena baja el neto sin que sea anomalía)."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="66666666-6666-6666-6666-666666666661",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), dias="15.000", total="8000.00")
    await insertar_nomina(db, empresa_id=eid, uuid="66666666-6666-6666-6666-666666666662",
                          fecha_pago=date(2026, 7, 15), fecha_inicial_pago=date(2026, 7, 1),
                          fecha_final_pago=date(2026, 7, 15), dias="15.000", total="2000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert any(b.clave == "VARIACION_ANOMALA" for b in resultado.banderas)


async def test_variacion_con_dias_distintos_no_marca(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="77777777-7777-7777-7777-777777777771",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), dias="15.000", total="8000.00")
    await insertar_nomina(db, empresa_id=eid, uuid="77777777-7777-7777-7777-777777777772",
                          fecha_pago=date(2026, 7, 15), fecha_inicial_pago=date(2026, 7, 1),
                          fecha_final_pago=date(2026, 7, 15), dias="7.000", total="2000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert not [b for b in resultado.banderas if b.clave == "VARIACION_ANOMALA"]


async def test_corte_irregular(db: AsyncSession) -> None:
    """Periodicidad quincenal con un cierre el día 20: no cae en ningún corte teórico."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="88888888-8888-8888-8888-888888888888",
                          periodicidad="04", fecha_pago=date(2026, 6, 20),
                          fecha_inicial_pago=date(2026, 6, 6), fecha_final_pago=date(2026, 6, 20), total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert any(b.clave == "CORTE_IRREGULAR" for b in resultado.banderas)


async def test_metrica_configurable(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="99999999-9999-9999-9999-999999999999",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), dias="15.000", total="8000.00",
                          deducciones=[("002", "045", "ISR", "500.00")])

    titulos_y_fila = {}
    for metrica, esperado in (("NETO", Decimal("8000.00")), ("ISR_RETENIDO", Decimal("500.00")),
                              ("DIAS_PAGADOS", Decimal("15.000")), ("NUM_CFDI", 1)):
        resultado = await b04.consultar(db, eid, _p(metrica=metrica))
        titulos = [c.titulo for c in resultado.columnas]
        titulos_y_fila[metrica] = resultado.filas[0][titulos.index("2026-06 Q2")]
        assert titulos_y_fila[metrica] == esperado, (metrica, titulos_y_fila[metrica])


async def test_columnas_de_resumen(db: AsyncSession) -> None:
    """Las columnas fijas de la ficha: cobertura, total, promedio y dispersión."""
    eid = await _empresa(db)
    for uuid_cfdi, (ini, fin) in (("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1", (date(2026, 6, 16), date(2026, 6, 30))),
                                  ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2", (date(2026, 7, 1), date(2026, 7, 15)))):
        await insertar_nomina(db, empresa_id=eid, uuid=uuid_cfdi, fecha_pago=fin,
                              fecha_inicial_pago=ini, fecha_final_pago=fin, total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    titulos = [c.titulo for c in resultado.columnas]
    fila = resultado.filas[0]
    assert fila[titulos.index("Núm. de periodos con pago")] == 2
    assert fila[titulos.index("Total del rango")] == Decimal("16000.00")
    assert fila[titulos.index("Promedio por periodo")] == Decimal("8000.00")
    # 4 cortes teóricos en el rango, 2 con pago.
    assert fila[titulos.index("Núm. de periodos esperados")] == 4


async def test_curp_sensible_y_sin_comprobantes(db: AsyncSession) -> None:
    eid = await _empresa(db)
    vacio = await b04.consultar(db, eid, _p(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31)))
    assert vacio.filas == [] and vacio.aviso is not None

    await insertar_nomina(db, empresa_id=eid, uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30))
    resultado = await b04.consultar(db, eid, _p())
    por_titulo = {c.titulo: c for c in resultado.columnas}
    assert por_titulo["CURP"].sensible is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_informe_b04.py -q`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Implementar B-04**

Estructura como B-02 (ábrelo). Puntos concretos:

- **Fase 1 del algoritmo:** la periodicidad dominante sale de `periodos.periodicidad_dominante` sobre los `nomina_receptor.periodicidad_pago` del universo. Si es `None` (ninguna reconocida), no se puede construir el eje: devuelve un `ResultadoInforme` con aviso explicándolo y una bandera, **no** una matriz sin columnas.
- Para `02` y `03`, pasa como `primer_corte_observado` el `MIN(fecha_final_pago)` del universo.
- **Fase 2:** `periodos.asignar_a_corte(eje, fecha_final_pago)` por cada CFDI; si `es_irregular`, bandera `CORTE_IRREGULAR` con el UUID.
- **Fase 3:** la celda es la métrica del parámetro. Para `NUM_CFDI` es un entero; para las demás, `Decimal`. Una celda sin CFDI queda en `None` (no en cero): aquí `None` significa "no hubo nómina en ese periodo", que es información, no un importe. **Es la excepción declarada a R-T7 y hay que documentarla en el docstring**, porque contradice la regla general del proyecto.
- Tipos de columna: los periodos son `monto` salvo con `NUM_CFDI` (`entero`) y `DIAS_PAGADOS` (`decimal`).
- Las columnas de resumen de la ficha, con `% de cobertura` = periodos con pago / periodos esperados, y desviación estándar y coeficiente de variación sobre las celdas con dato. Usa `Decimal` — para la raíz cuadrada, `Decimal.sqrt()`.
- `PERIODO_FALTANTE`: recorre el eje por empleado; marca un hueco solo si existe un CFDI en un índice **mayor**.
- Las banderas del universo (`SIN_NORMALIZAR` y compañía) se comparten con B-02: **usa el módulo compartido**, no las copies.

- [ ] **Step 4: Registrar, correr y commitear**

Registra en `registro.py`.
Run: `.venv/bin/pytest tests/test_informe_b04.py tests/test_informes_periodos.py -q`
Expected: PASS

```bash
.venv/bin/mypy --strict app
git add app/informes/ tests/ && git commit -m "feat(informes): agregar B-04 (matriz empleado x periodo)"
```

---

### Task 5: B-05 · Acumulado anual por empleado

**Files:**
- Create: `app/informes/b05_acumulado_anual.py`
- Modify: `app/informes/registro.py`
- Test: `tests/test_informe_b05.py`

**Interfaces:**
- Produces: `CLAVE = "B-05"`, `TIPOS_COMPROBANTE = ("N",)`, `class Parametros` con `ejercicio: int`, `incluir_cancelados: bool = False`, `enmascarar_datos_personales: bool = True`; `async def consultar(...)`.

**El grano es `(rfc_receptor, ejercicio)`:** una fila por empleado por año. Es el papel de trabajo del cálculo anual del ISR y la base de la constancia de percepciones.

**Alcance, ya declarado arriba:** se implementan las columnas 1–10 y 12–23. La **11 ("Gravado ordinario") y las 24–26 quedan fuera** — la 11 necesita la marca `es_ingreso_ordinario` del §3.1 y las 24–26 la tarifa de ISR, ambas de la fase 3. **No declares parámetros ni columnas para ellas**: una columna vacía en un papel de trabajo fiscal es peor que su ausencia, porque quien lo revise no sabe si el dato es cero o falta.

**Reglas que las pruebas fijan:**
- **B-05.R1:** un CFDI cancelado y sustituido cuenta **una** vez — se toma el sustituto. La cadena se resuelve por `cfdi_relacionado` con `tipo_relacion='04'`. Sin esto, un timbrado corregido duplica los ingresos anuales del empleado, que es un error grave en una constancia.
- **B-05.R3:** si el mismo `rfc_receptor` aparece con dos `rfc_emisor` distintos en el ejercicio → bandera `MULTI_PATRON`. El cálculo anual es incompleto por construcción en ese caso.
- Los datos de identidad del empleado (columna 2) salen del **CFDI más reciente del ejercicio**, no del primero: si cambió de puesto o departamento, interesa el último estado.
- SBC y SDI promedio son **ponderados por días pagados**, no promedios simples.

- [ ] **Step 1: Write the failing tests**

```python
"""B-05 · Acumulado anual por empleado. Papel de trabajo del cálculo anual del ISR."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b05_acumulado_anual as b05
from app.models.cfdi_detalle import CfdiRelacionado
from app.models.enums import EstatusCfdi
from tests import factories
from tests.helpers_nomina import insertar_nomina


async def _empresa(db: AsyncSession) -> int:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    return empresa.empresa_id


def _fila(resultado: object, titulo: str, indice: int = 0) -> object:
    titulos = [c.titulo for c in resultado.columnas]  # type: ignore[attr-defined]
    return resultado.filas[indice][titulos.index(titulo)]  # type: ignore[attr-defined]


async def test_acumula_el_ejercicio_por_empleado(db: AsyncSession) -> None:
    eid = await _empresa(db)
    for sufijo, fin in (("1", date(2026, 6, 30)), ("2", date(2026, 7, 15))):
        await insertar_nomina(db, empresa_id=eid, uuid=f"1111111{sufijo}-1111-1111-1111-111111111111",
                              fecha_pago=fin, fecha_final_pago=fin, dias="15.000",
                              percepciones=[("001", "001", "Sueldo", "8000.00", "500.00")],
                              deducciones=[("002", "045", "ISR", "600.00"), ("001", "052", "IMSS", "200.00")],
                              total_percepciones="8500.00", total_deducciones="800.00", total="7700.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert len(resultado.filas) == 1
    assert _fila(resultado, "Núm. de CFDI") == 2
    assert _fila(resultado, "Días pagados del ejercicio") == Decimal("30.000")
    assert _fila(resultado, "Total percepciones") == Decimal("17000.00")
    assert _fila(resultado, "Total gravado") == Decimal("16000.00")
    assert _fila(resultado, "Total exento") == Decimal("1000.00")
    assert _fila(resultado, "ISR retenido") == Decimal("1200.00")
    assert _fila(resultado, "IMSS retenido") == Decimal("400.00")
    assert _fila(resultado, "Neto pagado") == Decimal("15400.00")


async def test_otro_ejercicio_no_entra(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="22222222-2222-2222-2222-222222222222",
                          fecha_pago=date(2025, 12, 31), fecha_final_pago=date(2025, 12, 31))
    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert resultado.filas == []


async def test_cancelado_sustituido_cuenta_una_vez(db: AsyncSession) -> None:
    """B-05.R1. Sin esto, un timbrado corregido duplica los ingresos anuales del empleado
    — un error grave en una constancia de percepciones."""
    eid = await _empresa(db)
    cid_malo = await insertar_nomina(db, empresa_id=eid, uuid="33333333-3333-3333-3333-333333333331",
                                     fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                                     estatus=EstatusCfdi.CANCELADO,
                                     percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                                     total_percepciones="8000.00", total="8000.00")
    cid_bueno = await insertar_nomina(db, empresa_id=eid, uuid="33333333-3333-3333-3333-333333333332",
                                      fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                                      percepciones=[("001", "001", "Sueldo", "8500.00", "0.00")],
                                      total_percepciones="8500.00", total="8500.00")
    # El sustituto declara la relación 04 hacia el cancelado.
    db.add(CfdiRelacionado(comprobante_id=cid_bueno, tipo_relacion="04",
                           uuid_relacionado="33333333-3333-3333-3333-333333333331"))
    await db.commit()
    assert cid_malo != cid_bueno

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert len(resultado.filas) == 1
    assert _fila(resultado, "Total percepciones") == Decimal("8500.00")
    assert _fila(resultado, "Núm. de CFDI") == 1


async def test_multi_patron(db: AsyncSession) -> None:
    """B-05.R3: el mismo empleado con dos patrones en el ejercicio hace el cálculo anual
    incompleto por construcción."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="44444444-4444-4444-4444-444444444441",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30))
    await insertar_nomina(db, empresa_id=eid, uuid="44444444-4444-4444-4444-444444444442",
                          fecha_pago=date(2026, 7, 15), fecha_final_pago=date(2026, 7, 15),
                          rfc_emisor="XAXX010101000")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert any(b.clave == "MULTI_PATRON" for b in resultado.banderas)


async def test_identidad_del_empleado_sale_del_cfdi_mas_reciente(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="55555555-5555-5555-5555-555555555551",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30), puesto="Auxiliar")
    await insertar_nomina(db, empresa_id=eid, uuid="55555555-5555-5555-5555-555555555552",
                          fecha_pago=date(2026, 7, 15), fecha_final_pago=date(2026, 7, 15), puesto="Coordinador")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Puesto") == "Coordinador"


async def test_sbc_y_sdi_son_promedios_ponderados_por_dias(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="66666666-6666-6666-6666-666666666661",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          dias="15.000", sbc="500.00", sdi="600.00")
    await insertar_nomina(db, empresa_id=eid, uuid="66666666-6666-6666-6666-666666666662",
                          fecha_pago=date(2026, 7, 15), fecha_final_pago=date(2026, 7, 15),
                          dias="5.000", sbc="700.00", sdi="800.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    # (500×15 + 700×5) / 20 = 550
    assert _fila(resultado, "SBC promedio ponderado") == Decimal("550")
    assert _fila(resultado, "SDI promedio ponderado") == Decimal("650")


async def test_desglose_de_deducciones(db: AsyncSession) -> None:
    """Columnas 18 a 20: fondo de ahorro (004), Infonavit (009) y el resto."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="77777777-7777-7777-7777-777777777777",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          deducciones=[("002", "045", "ISR", "600.00"), ("001", "052", "IMSS", "200.00"),
                                       ("004", "067", "Fondo ahorro", "300.00"),
                                       ("009", "014", "Infonavit", "400.00"),
                                       ("006", "090", "Incapacidad", "100.00")],
                          total_deducciones="1600.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Aportaciones a fondo de ahorro") == Decimal("300.00")
    assert _fila(resultado, "Descuentos Infonavit") == Decimal("400.00")
    # Otras = total − ISR − IMSS − 004 − 009 = 1600 − 600 − 200 − 300 − 400
    assert _fila(resultado, "Otras deducciones") == Decimal("100.00")


async def test_separacion_y_jubilacion(db: AsyncSession) -> None:
    """Columnas 12 y 13, de los totales del complemento."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="88888888-8888-8888-8888-888888888888",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          total_separacion="5000.00", total_jubilacion="3000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Ingreso por separación") == Decimal("5000.00")
    assert _fila(resultado, "Ingreso por jubilación") == Decimal("3000.00")


async def test_subsidio_causado_y_entregado(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="99999999-9999-9999-9999-999999999999",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          otros_pagos=[("002", "035", "Subsidio", "120.00", "200.00")])

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Subsidio causado") == Decimal("200.00")
    assert _fila(resultado, "Subsidio entregado en efectivo") == Decimal("120.00")


async def test_no_hay_columnas_de_alcance_diferido(db: AsyncSession) -> None:
    """La columna 11 y las 24-26 se declararon fuera de alcance: una columna vacía en un
    papel de trabajo fiscal es peor que su ausencia."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30))
    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    titulos = [c.titulo for c in resultado.columnas]
    assert not any("ordinario" in t.lower() for t in titulos)
    assert not any("teórico" in t.lower() or "teorico" in t.lower() for t in titulos)


async def test_curp_sensible_y_ejercicio_vacio(db: AsyncSession) -> None:
    eid = await _empresa(db)
    vacio = await b05.consultar(db, eid, b05.Parametros(ejercicio=2020))
    assert vacio.filas == [] and vacio.aviso is not None
```

- [ ] **Step 2: Comprobar que el helper ya soporta lo que estas pruebas necesitan**

La tarea 3 declaró los 31 parámetros de `insertar_nomina`, incluidos `rfc_emisor`, `total_separacion` y `total_jubilacion` que estas pruebas usan. Verifícalo antes de escribir código; si falta alguno, agrégalo con el criterio `None` = default (**nunca** `x or default`: una lista vacía es *falsy*).

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_informe_b05.py -q`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 4: Implementar B-05**

Estructura como B-02. Puntos concretos:

- El universo es por **ejercicio** (`YEAR(nomina.fecha_pago) == p.ejercicio`), no por rango de fechas.
- **La resolución de sustituciones (B-05.R1) es la parte delicada.** Antes de agregar: obtén los `uuid_relacionado` con `tipo_relacion='04'` de los comprobantes del universo y **excluye** del acumulado los comprobantes cuyo `uuid` esté en ese conjunto. Documenta la decisión: se conserva el **sustituto** y se descarta el sustituido, sin importar el estatus de cada uno. Si el sustituido no está en la base, no hay nada que excluir y el acumulado es correcto igual.
- Agrupa por `rfc_receptor`. La identidad del empleado sale del CFDI con `MAX(fecha_pago)`.
- SBC/SDI ponderados: `Σ(valor × días) / Σ días`, con guarda de división por cero.
- Banderas: `MULTI_PATRON`, más las del universo compartido.
- Sin `round()` ni `quantize()`.

- [ ] **Step 5: Registrar, correr y commitear**

Run: `.venv/bin/pytest tests/test_informe_b05.py -q`
Expected: PASS

```bash
.venv/bin/mypy --strict app
git add app/informes/ tests/ && git commit -m "feat(informes): agregar B-05 (acumulado anual por empleado)"
```

---

### Task 6: B-07 · Cartera de préstamos y descuentos recurrentes

**Files:**
- Create: `app/informes/b07_prestamos.py`
- Modify: `app/informes/registro.py`
- Test: `tests/test_informe_b07.py`

**Interfaces:**
- Consumes: `app/informes/periodos.py`.
- Produces: `CLAVE = "B-07"`, `TIPOS_COMPROBANTE = ("N",)`, `class Parametros` con `fecha_desde`, `fecha_hasta`, `tipos_deduccion: list[str] | None = None` (filtro opcional; `None` = todos), `incluir_cancelados: bool = False`, `enmascarar_datos_personales: bool = True`; `async def consultar(...)`.

**El grano es `(rfc_receptor, tipo_deduccion, clave)`:** una fila por préstamo o descuento recurrente de cada empleado. El propósito es rastrear algo que **el CFDI no contiene**: el saldo. Solo trae el descuento del periodo, así que el valor del informe está en el **control de continuidad** — detectar un préstamo cuyo descuento se detuvo sin liquidarse.

**Alcance, ya declarado:** las columnas 10–13 (monto original, saldo estimado, descuentos restantes, fecha de liquidación) **quedan fuera**. B-07.R2 lo dice explícitamente: sin el monto original no se estiman, y **no se infiere del descuento**. No declares el parámetro de captura del monto original: sería otro control sin efecto.

**Reglas que las pruebas fijan:**
- **Descuento modal** = el valor más frecuente, que identifica la amortización pactada. No el promedio: un solo ajuste desvía el promedio y el modal sigue señalando la cuota real.
- **B-07.R1 Continuidad:** `CONTINUO` sin huecos entre el primer y el último descuento; `INTERRUMPIDO` con huecos intermedios (que se listan); `CONCLUIDO` cuando el último descuento es anterior al último periodo del rango. Se compara contra el eje teórico de la tarea 2.
- `DESCUENTO_INTERRUMPIDO` es el hallazgo relevante del informe: un préstamo cuyo descuento se detuvo sin liquidarse.
- **B-07.R3:** si el descuento modal cambia a mitad de la serie → `AMORTIZACION_MODIFICADA` con las dos fases y sus fechas. Es lo esperado en créditos Infonavit cuando se actualiza el factor.

- [ ] **Step 1: Write the failing tests**

```python
"""B-07 · Cartera de préstamos y descuentos recurrentes.

El CFDI no contiene el saldo del préstamo, solo el descuento del periodo, así que el valor
de este informe está en el control de continuidad (B-07.R1): detectar un descuento que se
detuvo sin liquidarse.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b07_prestamos as b07
from tests import factories
from tests.helpers_nomina import insertar_nomina


def _p(**kw: object) -> b07.Parametros:
    base = {"fecha_desde": date(2026, 1, 1), "fecha_hasta": date(2026, 3, 31)}
    base.update(kw)
    return b07.Parametros(**base)  # type: ignore[arg-type]


async def _empresa(db: AsyncSession) -> int:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    return empresa.empresa_id


async def _quincenas(db: AsyncSession, eid: int, importes: list[str | None], *, clave: str = "016",
                     tipo: str = "009", rfc: str = "XAXX010101000") -> None:
    """Una quincena por importe; `None` significa que ese periodo NO trae el descuento."""
    cortes = [(date(2026, 1, 15)), (date(2026, 1, 31)), (date(2026, 2, 15)), (date(2026, 2, 28)),
              (date(2026, 3, 15)), (date(2026, 3, 31))]
    for indice, importe in enumerate(importes):
        deducciones = [("002", "045", "ISR", "100.00")]
        if importe is not None:
            deducciones.append((tipo, clave, "Prestamo infonavit", importe))
        await insertar_nomina(db, empresa_id=eid, uuid=f"1111111{indice}-1111-1111-1111-111111111111",
                              rfc_receptor=rfc, fecha_pago=cortes[indice], fecha_final_pago=cortes[indice],
                              periodicidad="04", deducciones=deducciones)


def _fila(resultado: object, titulo: str, indice: int = 0) -> object:
    titulos = [c.titulo for c in resultado.columnas]  # type: ignore[attr-defined]
    return resultado.filas[indice][titulos.index(titulo)]  # type: ignore[attr-defined]


async def test_una_fila_por_empleado_tipo_y_clave(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await _quincenas(db, eid, ["500.00", "500.00", "500.00"])

    resultado = await b07.consultar(db, eid, _p())
    # El ISR también es una deducción recurrente y aparece como su propia fila.
    claves = {(f[0], f[1]) for f in [( _fila(resultado, "Tipo deducción", i), _fila(resultado, "Clave", i))
                                     for i in range(len(resultado.filas))]}
    assert len(resultado.filas) == 2, claves


async def test_agregados_de_la_serie(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await _quincenas(db, eid, ["500.00", "500.00", "600.00"])

    resultado = await b07.consultar(db, eid, _p(tipos_deduccion=["009"]))
    assert len(resultado.filas) == 1
    assert _fila(resultado, "Núm. de descuentos") == 3
    assert _fila(resultado, "Total descontado") == Decimal("1600.00")
    assert _fila(resultado, "Primer descuento") == date(2026, 1, 15)
    assert _fila(resultado, "Último descuento") == date(2026, 2, 15)


async def test_descuento_modal_no_es_el_promedio(db: AsyncSession) -> None:
    """El modal identifica la amortización pactada; un solo ajuste desvía el promedio pero
    no el modal."""
    eid = await _empresa(db)
    await _quincenas(db, eid, ["500.00", "500.00", "500.00", "2000.00"])

    resultado = await b07.consultar(db, eid, _p(tipos_deduccion=["009"]))
    assert _fila(resultado, "Descuento modal") == Decimal("500.00")
    assert _fila(resultado, "Descuento promedio") != Decimal("500.00")


async def test_continuidad_continuo(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await _quincenas(db, eid, ["500.00", "500.00", "500.00", "500.00", "500.00", "500.00"])

    resultado = await b07.consultar(db, eid, _p(tipos_deduccion=["009"]))
    assert _fila(resultado, "Continuidad") == "CONTINUO"
    assert not [b for b in resultado.banderas if b.clave == "DESCUENTO_INTERRUMPIDO"]


async def test_continuidad_interrumpido_es_el_hallazgo_del_informe(db: AsyncSession) -> None:
    """B-07.R1: un préstamo cuyo descuento se detuvo a media serie y luego volvió."""
    eid = await _empresa(db)
    await _quincenas(db, eid, ["500.00", None, "500.00", "500.00"])

    resultado = await b07.consultar(db, eid, _p(tipos_deduccion=["009"]))
    assert _fila(resultado, "Continuidad") == "INTERRUMPIDO"
    banderas = [b for b in resultado.banderas if b.clave == "DESCUENTO_INTERRUMPIDO"]
    assert banderas
    # El mensaje lista los huecos, porque es la información accionable.
    assert "2026-01 Q2" in banderas[0].mensaje


async def test_continuidad_concluido(db: AsyncSession) -> None:
    """El descuento terminó antes del final del rango: probablemente se liquidó."""
    eid = await _empresa(db)
    await _quincenas(db, eid, ["500.00", "500.00", None, None, None, None])

    resultado = await b07.consultar(db, eid, _p(tipos_deduccion=["009"]))
    assert _fila(resultado, "Continuidad") == "CONCLUIDO"


async def test_amortizacion_modificada(db: AsyncSession) -> None:
    """B-07.R3: lo esperado en un crédito Infonavit al actualizarse el factor."""
    eid = await _empresa(db)
    await _quincenas(db, eid, ["500.00", "500.00", "500.00", "620.00", "620.00", "620.00"])

    resultado = await b07.consultar(db, eid, _p(tipos_deduccion=["009"]))
    banderas = [b for b in resultado.banderas if b.clave == "AMORTIZACION_MODIFICADA"]
    assert banderas
    assert "500" in banderas[0].mensaje and "620" in banderas[0].mensaje


async def test_no_hay_columnas_de_saldo(db: AsyncSession) -> None:
    """B-07.R2: sin el monto original no se estima el saldo, y no se infiere del descuento."""
    eid = await _empresa(db)
    await _quincenas(db, eid, ["500.00"])
    resultado = await b07.consultar(db, eid, _p())
    titulos = [c.titulo for c in resultado.columnas]
    assert not any("saldo" in t.lower() or "liquidaci" in t.lower() for t in titulos)


async def test_descripcion_sat_del_tipo_de_deduccion(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await _quincenas(db, eid, ["500.00"])
    resultado = await b07.consultar(db, eid, _p(tipos_deduccion=["009"]))
    assert _fila(resultado, "Descripción SAT") is not None


async def test_sin_descuentos_devuelve_aviso(db: AsyncSession) -> None:
    eid = await _empresa(db)
    resultado = await b07.consultar(db, eid, _p())
    assert resultado.filas == [] and resultado.aviso is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_informe_b07.py -q`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Implementar B-07**

Puntos concretos:

- La consulta agrupa `nomina_deduccion` por `(rfc_receptor, tipo_deduccion, clave)` sobre el universo de nómina, trayendo también las `fecha_pago` y los importes individuales para calcular el modal y la continuidad.
- **El modal** es la moda de los importes; desempata por el importe mayor (una amortización pactada suele ser el valor alto, no el ajuste), y documenta el criterio.
- **La continuidad** usa el eje de `periodos.py`: construye el eje del rango con la periodicidad dominante, mapea cada `fecha_pago` con descuento a su corte, y clasifica. Si no se puede construir el eje (periodicidad no reconocida), la columna queda en `None` y se emite una bandera explicándolo — **no** inventes una clasificación sin base.
- `AMORTIZACION_MODIFICADA`: detecta un cambio sostenido del modal partiendo la serie en dos mitades por fecha y comparando su moda. Reporta ambos valores y las fechas de cada fase.
- `CURP`/`NSS` no van en este informe (la ficha solo pide RFC, nombre y número de empleado), así que no hay nada sensible que declarar — **verifícalo** y dilo en el informe.

- [ ] **Step 4: Registrar, correr y commitear**

Run: `.venv/bin/pytest tests/test_informe_b07.py tests/test_informes_periodos.py -q`
Expected: PASS

```bash
.venv/bin/mypy --strict app
git add app/informes/ tests/ && git commit -m "feat(informes): agregar B-07 (cartera de prestamos y descuentos recurrentes)"
```

---

### Task 7: B-10 · Validación de datos del receptor

**Files:**
- Create: `app/informes/b10_validacion_receptor.py`
- Create: `app/informes/validadores.py` (las reglas puras, sin BD)
- Modify: `app/informes/registro.py`
- Test: `tests/test_informes_validadores.py`
- Test: `tests/test_informe_b10.py`

**Interfaces:**
- Produces:
  - En `validadores.py`: `def rfc_persona_fisica_valido(rfc: str | None) -> bool`, `def curp_valida(curp: str | None) -> bool`, `def curp_entidad_valida(curp: str | None) -> bool`, `def nss_digito_verificador_valido(nss: str | None) -> bool`, `def cuenta_bancaria_longitud_valida(cuenta: str | None) -> bool`, `def antiguedad_iso_a_dias(antiguedad: str | None) -> int | None`
  - `CLAVE = "B-10"`, `TIPOS_COMPROBANTE = ("N",)`, `class Parametros` con `fecha_desde`, `fecha_hasta`, `severidad_minima: Literal["alta","media","baja"] = "baja"`, `incluir_cancelados: bool = False`, `enmascarar_datos_personales: bool = True`; `async def consultar(...)`

**El propósito, y por qué este informe importa aunque no lleve importes:** audita la calidad de los datos del trabajador timbrados. Los errores aquí generan requerimientos del SAT y problemas de acreditación ante el IMSS, **y son invisibles en los informes de importes** — todos los demás informes pueden cuadrar perfectamente con un NSS mal capturado.

**Grano:** una fila por hallazgo, es decir `(rfc_receptor, clave_validación)`. Es el formato accionable: cada fila es algo que corregir.

**Las 21 validaciones en alcance.** Las dos que faltan (`SBC_SOBRE_TOPE`, `SBC_BAJO_MINIMO`) necesitan UMA y salario mínimo de la fase 3.

| Clave | Regla | Severidad |
|---|---|---|
| `RFC_ESTRUCTURA` | No cumple `^[A-ZÑ&]{4}[0-9]{6}[A-Z0-9]{3}$` | alta |
| `RFC_CURP_INCONSISTENTE` | Las 10 primeras del RFC ≠ las 10 primeras de la CURP | alta |
| `CURP_ESTRUCTURA` | No cumple `^[A-Z]{4}[0-9]{6}[HM][A-Z]{5}[A-Z0-9][0-9]$` | alta |
| `CURP_ENTIDAD` | Posiciones 12-13 no son clave de entidad válida | media |
| `CURP_DUPLICADA` | Una CURP con más de un RFC en el conjunto | alta |
| `RFC_DUPLICADO` | Un RFC con más de una CURP | alta |
| `NSS_LONGITUD` | Longitud distinta de 11 | media |
| `NSS_DIGITO_VERIFICADOR` | Falla Luhn sobre las 10 primeras posiciones | media |
| `NSS_FALTANTE` | Vacío con `tipo_regimen='02'` | alta |
| `NSS_DUPLICADO` | Un NSS con más de un RFC | alta |
| `SBC_CERO` | `salario_base_cot_apor <= 0` con `tipo_regimen='02'` | alta |
| `SDI_MENOR_SBC` | `sdi < sbc × 0.8` | media |
| `SDI_CERO` | `sdi <= 0` | alta |
| `SDI_MENOR_SD_IMPLICITO` | `sdi < (Σ percepción '001') / días pagados` | alta |
| `FECHA_INICIO_POSTERIOR` | `fecha_inicio_rel_laboral > fecha_final_pago` | alta |
| `ANTIGUEDAD_INCONSISTENTE` | La duración ISO difiere >2 semanas del cálculo desde la fecha de inicio | baja |
| `PUESTO_VACIO` | Nulo, vacío o `Ninguno`/`N/A` | baja |
| `DEPARTAMENTO_VACIO` | Igual para departamento | baja |
| `CUENTA_INVALIDA` | Longitud distinta de 10, 11, 16 o 18 | baja |
| `BANCO_SIN_CUENTA` | Banco presente y cuenta vacía | baja |
| `DATOS_CAMBIANTES` | Un RFC con distinto CURP, NSS o fecha de inicio entre periodos | alta |

**B-10.R1, y hay que respetarla:** SBC y SDI son conceptos distintos (el SBC es la base de cotización ante el IMSS; el SDI es el salario diario integrado de la LFT). Un SDI inferior al SBC es teóricamente posible, así que `SDI_MENOR_SBC` es severidad **media**, no un error absoluto.

- [ ] **Step 1: Write the failing tests for the pure validators**

```python
"""Validadores puros de datos del receptor (ficha B-10). Sin BD: reglas de estructura."""

from __future__ import annotations

import pytest

from app.informes import validadores as v


@pytest.mark.parametrize("rfc", ["VECJ880326XXX", "ÑAAA000101AA1", "AAA&000101AA1"])
def test_rfc_persona_fisica_valido(rfc: str) -> None:
    assert v.rfc_persona_fisica_valido(rfc) is True


@pytest.mark.parametrize("rfc", [None, "", "EKU9003173C9", "VECJ880326", "vecj880326xxx", "VECJ8803261XXX"])
def test_rfc_persona_fisica_invalido(rfc: str | None) -> None:
    """`EKU9003173C9` es de persona moral (3 letras iniciales): no cumple el patrón de
    física, que exige 4."""
    assert v.rfc_persona_fisica_valido(rfc) is False


def test_curp_valida() -> None:
    assert v.curp_valida("VECJ880326HDFLNS09") is True
    assert v.curp_valida(None) is False
    assert v.curp_valida("VECJ880326XDFLNS09") is False  # ni H ni M


def test_curp_entidad() -> None:
    assert v.curp_entidad_valida("VECJ880326HDFLNS09") is True   # DF
    assert v.curp_entidad_valida("VECJ880326HCHLNS09") is True   # CH
    assert v.curp_entidad_valida("VECJ880326HZZLNS09") is False


def test_nss_digito_verificador() -> None:
    """Luhn sobre las 10 primeras posiciones; la 11ª es el verificador."""
    assert v.nss_digito_verificador_valido("12345678903") is True
    assert v.nss_digito_verificador_valido("12345678901") is False
    assert v.nss_digito_verificador_valido(None) is False
    assert v.nss_digito_verificador_valido("123") is False


def test_cuenta_bancaria_longitud() -> None:
    for largo in (10, 11, 16, 18):
        assert v.cuenta_bancaria_longitud_valida("1" * largo) is True
    assert v.cuenta_bancaria_longitud_valida("1" * 12) is False
    assert v.cuenta_bancaria_longitud_valida(None) is False


def test_antiguedad_iso_a_dias() -> None:
    """`@Antigüedad` viene como duración ISO 8601 (`P663W`, `P3Y2M`)."""
    assert v.antiguedad_iso_a_dias("P1W") == 7
    assert v.antiguedad_iso_a_dias("P663W") == 663 * 7
    assert v.antiguedad_iso_a_dias("P1Y") == 365
    assert v.antiguedad_iso_a_dias("P1Y2M") == 365 + 60
    assert v.antiguedad_iso_a_dias("P10D") == 10
    assert v.antiguedad_iso_a_dias(None) is None
    assert v.antiguedad_iso_a_dias("663 semanas") is None
```

**Nota sobre el dígito verificador:** verifica el NSS de la prueba con el algoritmo real antes de darlo por bueno. Si `12345678903` no cumple Luhn, calcula uno que sí y usa ese, documentándolo. **No ajustes el validador para que pase una prueba con un valor equivocado.**

- [ ] **Step 2: Implementar los validadores y correr**

Módulo puro con las expresiones regulares de la tabla, la lista de claves de entidad de la CURP (las 32 más `NE` para nacidos en el extranjero), Luhn sobre 10 dígitos, y el parseo de la duración ISO 8601 (semanas, años, meses, días; meses = 30 días, años = 365, y documenta la aproximación porque la validación tolera ±2 semanas).

Run: `.venv/bin/pytest tests/test_informes_validadores.py -q`
Expected: PASS

- [ ] **Step 3: Write the failing tests for B-10**

```python
"""B-10 · Validación de datos del receptor.

Los errores de este informe generan requerimientos del SAT y problemas ante el IMSS, y son
**invisibles en los informes de importes**: todos los demás pueden cuadrar con un NSS mal
capturado.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b10_validacion_receptor as b10
from tests import factories
from tests.helpers_nomina import insertar_nomina


def _p(**kw: object) -> b10.Parametros:
    base = {"fecha_desde": date(2026, 6, 1), "fecha_hasta": date(2026, 7, 31)}
    base.update(kw)
    return b10.Parametros(**base)  # type: ignore[arg-type]


async def _empresa(db: AsyncSession) -> int:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    return empresa.empresa_id


def _claves(resultado: object) -> set[str]:
    titulos = [c.titulo for c in resultado.columnas]  # type: ignore[attr-defined]
    i = titulos.index("Validación")
    return {f[i] for f in resultado.filas}  # type: ignore[attr-defined]


async def test_una_fila_por_hallazgo(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="11111111-1111-1111-1111-111111111111",
                          rfc_receptor="XAXX010101000", curp="VECJ880326HDFLNS09",
                          nss="", tipo_regimen="02", puesto="", departamento="")

    resultado = await b10.consultar(db, eid, _p())
    claves = _claves(resultado)
    assert "NSS_FALTANTE" in claves
    assert "PUESTO_VACIO" in claves
    assert "DEPARTAMENTO_VACIO" in claves
    # Una fila por hallazgo, no una por empleado.
    assert len(resultado.filas) >= 3


async def test_datos_correctos_no_generan_hallazgos(db: AsyncSession) -> None:
    """Si un empleado bien capturado produjera hallazgos, el informe sería ruido."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="22222222-2222-2222-2222-222222222222",
                          rfc_receptor="VECJ880326XXX", curp="VECJ880326HDFLNS09",
                          nss="12345678903", tipo_regimen="02", puesto="Auxiliar",
                          departamento="Administración", sbc="500.00", sdi="600.00",
                          fecha_inicio_rel_laboral=date(2020, 1, 1), antiguedad="P330W",
                          banco="002", cuenta_bancaria="1234567890",
                          percepciones=[("001", "001", "Sueldo", "7500.00", "0.00")], dias="15.000")

    resultado = await b10.consultar(db, eid, _p())
    assert resultado.filas == [], _claves(resultado)


async def test_rfc_curp_inconsistente(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="33333333-3333-3333-3333-333333333333",
                          rfc_receptor="VECJ880326XXX", curp="AAAA880326HDFLNS09", nss="12345678903")
    assert "RFC_CURP_INCONSISTENTE" in _claves(await b10.consultar(db, eid, _p()))


async def test_curp_duplicada_y_rfc_duplicado(db: AsyncSession) -> None:
    """Validaciones de conjunto: no se ven mirando un CFDI aislado."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="44444444-4444-4444-4444-444444444441",
                          rfc_receptor="VECJ880326XXX", curp="VECJ880326HDFLNS09", nss="12345678903")
    await insertar_nomina(db, empresa_id=eid, uuid="44444444-4444-4444-4444-444444444442",
                          rfc_receptor="AAAA880326XXX", curp="VECJ880326HDFLNS09", nss="12345678903")

    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "CURP_DUPLICADA" in claves
    assert "NSS_DUPLICADO" in claves


async def test_datos_cambiantes_entre_periodos(db: AsyncSession) -> None:
    """Un mismo RFC con distinta CURP entre quincenas: error de captura que solo se ve
    comparando periodos."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="55555555-5555-5555-5555-555555555551",
                          rfc_receptor="VECJ880326XXX", curp="VECJ880326HDFLNS09",
                          nss="12345678903", fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30))
    await insertar_nomina(db, empresa_id=eid, uuid="55555555-5555-5555-5555-555555555552",
                          rfc_receptor="VECJ880326XXX", curp="VECJ880326HDFLNS08",
                          nss="12345678903", fecha_pago=date(2026, 7, 15), fecha_final_pago=date(2026, 7, 15))

    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "DATOS_CAMBIANTES" in claves


async def test_sdi_menor_al_salario_diario_implicito(db: AsyncSession) -> None:
    """El SDI declarado es menor que el sueldo diario que se deduce del propio CFDI."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="66666666-6666-6666-6666-666666666666",
                          rfc_receptor="VECJ880326XXX", curp="VECJ880326HDFLNS09", nss="12345678903",
                          sbc="500.00", sdi="100.00", dias="15.000",
                          percepciones=[("001", "001", "Sueldo", "7500.00", "0.00")])
    assert "SDI_MENOR_SD_IMPLICITO" in _claves(await b10.consultar(db, eid, _p()))


async def test_fecha_inicio_posterior_al_periodo(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="77777777-7777-7777-7777-777777777777",
                          rfc_receptor="VECJ880326XXX", curp="VECJ880326HDFLNS09", nss="12345678903",
                          fecha_final_pago=date(2026, 6, 30), fecha_inicio_rel_laboral=date(2026, 12, 1))
    assert "FECHA_INICIO_POSTERIOR" in _claves(await b10.consultar(db, eid, _p()))


async def test_banco_sin_cuenta_y_cuenta_invalida(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="88888888-8888-8888-8888-888888888881",
                          rfc_receptor="VECJ880326XXX", curp="VECJ880326HDFLNS09", nss="12345678903",
                          banco="002", cuenta_bancaria="")
    await insertar_nomina(db, empresa_id=eid, uuid="88888888-8888-8888-8888-888888888882",
                          rfc_receptor="AAAA880326XXX", curp="AAAA880326HDFLNS09", nss="12345678903",
                          banco="002", cuenta_bancaria="123456789012")

    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "BANCO_SIN_CUENTA" in claves
    assert "CUENTA_INVALIDA" in claves


async def test_severidad_minima_filtra(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="99999999-9999-9999-9999-999999999999",
                          rfc_receptor="VECJ880326XXX", curp="VECJ880326HDFLNS09", nss="12345678903",
                          puesto="", departamento="")

    todas = await b10.consultar(db, eid, _p())
    solo_altas = await b10.consultar(db, eid, _p(severidad_minima="alta"))
    assert "PUESTO_VACIO" in _claves(todas)
    assert "PUESTO_VACIO" not in _claves(solo_altas)


async def test_las_dos_validaciones_de_sbc_diferidas_no_aparecen(db: AsyncSession) -> None:
    """Necesitan UMA y salario mínimo de la fase 3."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                          rfc_receptor="VECJ880326XXX", curp="VECJ880326HDFLNS09", nss="12345678903",
                          sbc="999999.00")
    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "SBC_SOBRE_TOPE" not in claves
    assert "SBC_BAJO_MINIMO" not in claves


async def test_curp_y_nss_se_declaran_sensibles(db: AsyncSession) -> None:
    """B-10.R2: este informe es el que más datos personales expone, así que el
    enmascaramiento importa más aquí que en ninguno."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                          rfc_receptor="VECJ880326XXX", curp="VECJ880326HDFLNS09", nss="")
    resultado = await b10.consultar(db, eid, _p())
    por_titulo = {c.titulo: c for c in resultado.columnas}
    assert por_titulo["CURP"].sensible is True
    assert por_titulo["NSS"].sensible is True


async def test_sin_comprobantes_devuelve_aviso(db: AsyncSession) -> None:
    eid = await _empresa(db)
    resultado = await b10.consultar(db, eid, _p(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31)))
    assert resultado.filas == [] and resultado.aviso is not None
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_informe_b10.py -q`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 5: Implementar B-10**

Puntos concretos:

- Trae el último `nomina_receptor` por `rfc_receptor` para las validaciones de estructura, y **todos** los del rango para las de conjunto (`CURP_DUPLICADA`, `RFC_DUPLICADO`, `NSS_DUPLICADO`, `DATOS_CAMBIANTES`). Cuida el N+1: una consulta que traiga lo necesario, no una por empleado.
- Columnas: RFC empleado, Nombre, Núm. empleado, `Validación`, `Severidad`, `Descripción del hallazgo`, y los campos implicados (`CURP`, `NSS` con `sensible=True`, SBC, SDI, fechas). Una fila por hallazgo.
- `severidad_minima` filtra; el orden de las filas es determinista: por RFC, luego por severidad (alta, media, baja), luego por clave.
- **Este informe no emite banderas del propio hallazgo** (los hallazgos son las filas), pero sí las del universo compartido (`SIN_NORMALIZAR` y compañía).

- [ ] **Step 6: Registrar, correr y commitear**

Run: `.venv/bin/pytest tests/test_informe_b10.py tests/test_informes_validadores.py -q`
Expected: PASS

```bash
.venv/bin/mypy --strict app
git add app/informes/ tests/ && git commit -m "feat(informes): agregar B-10 (validacion de datos del receptor)"
```

---

### Task 8: Verificación en vivo de los cinco informes

**Files:**
- Modify: `scripts/verificar_fase1.py` → renombrar a `scripts/verificar_informes.py` y extender
- Test: ninguno nuevo (esta tarea verifica, no implementa)

**Interfaces:**
- Consumes: los cinco informes nuevos y el catálogo del registro.

**Qué comprueba.** Que los cinco informes corren contra los datos reales de la empresa y producen un Excel bien formado. Los datos son pocos (4 empleados, 2 quincenas), así que no se trata de validar cifras de negocio sino de que **ningún informe truene, salga vacío por error, o filtre datos personales**.

- [ ] **Step 1: Verificar que el catálogo expone los seis informes**

```bash
docker compose exec -T api python -c "
from app.informes import registro
for e in registro.catalogo():
    print(e['clave'], '|', e['nombre'], '| params:', sorted(e['parametros']['properties']))
"
```
Expected: B-01, B-02, B-04, B-05, B-07, B-10. **Ningún parámetro que no haga nada** — compáralo contra la tabla de alcance del inicio de este plan.

- [ ] **Step 2: Reiniciar el worker**

Los informes nuevos no requieren tareas de Celery nuevas (todos pasan por `generar_informe`, que ya está registrada), pero el worker tiene el código en memoria desde su último arranque y **no recarga**. Si no lo reinicias, `registro.REGISTRO` dentro del worker no conoce los informes nuevos y la generación falla con un 404 desde la tarea.

```bash
docker compose restart worker
sleep 10
docker compose exec -T worker python -c "from app.informes import registro; print(sorted(registro.REGISTRO))"
```
Expected: las seis claves.

- [ ] **Step 3: Generar los cinco informes end to end**

```bash
docker compose exec -T worker python -c "
from app.worker.tasks import generar_informe
casos = [
    ('B-01', {'fecha_desde': '2026-06-01', 'fecha_hasta': '2026-07-31'}),
    ('B-04', {'fecha_desde': '2026-06-01', 'fecha_hasta': '2026-07-31'}),
    ('B-05', {'ejercicio': 2026}),
    ('B-07', {'fecha_desde': '2026-06-01', 'fecha_hasta': '2026-07-31'}),
    ('B-10', {'fecha_desde': '2026-06-01', 'fecha_hasta': '2026-07-31'}),
]
for clave, params in casos:
    r = generar_informe.apply(args=(11, clave, params, 'verificacion@demo.test'))
    print(clave, r.state, r.result if r.state == 'SUCCESS' else r.traceback)
"
```
Expected: los cinco en `SUCCESS`, con su `ruta`, `filas` y `banderas`. **Si alguno sale con 0 filas, investiga por qué antes de darlo por bueno**: con 8 CFDI de nómina en el rango, B-01 debe dar 8 filas, B-04 cuatro (una por empleado), B-05 cuatro, B-07 una por cada `(empleado, tipo, clave)` de deducción, y B-10 las que haya.

- [ ] **Step 4: Inspeccionar cada Excel**

Para cada archivo generado, comprueba con `openpyxl`: las cuatro hojas; que `Datos` tenga encabezado y filas; que **CURP y NSS salgan enmascarados** (`****` más 4 caracteres) donde esas columnas existan; y que la hoja `Parámetros` traiga el usuario, la fecha, la versión del ETL y los filtros. **No transcribas los valores de CURP ni NSS en el informe**, solo confirma la forma.

Comprobaciones específicas por informe:
- **B-01:** más de 100 columnas dinámicas (el catálogo completo), y una columna de un tipo sin movimiento con valor `0`.
- **B-04:** las cuatro columnas de periodo del rango, y las celdas de los periodos sin nómina distinguibles de un cero.
- **B-05:** una fila por empleado con el acumulado de las dos quincenas.
- **B-07:** las filas de las deducciones recurrentes reales de la empresa, con su columna de continuidad.
- **B-10:** revisa los hallazgos que reporte. **Es información real sobre la calidad de los datos del cliente**, así que resúmela en el informe por clave de validación y conteo, sin transcribir datos personales.

- [ ] **Step 5: Extender el script de verificación**

Renombra `scripts/verificar_fase1.py` a `scripts/verificar_informes.py` (con `git mv`) y agrégale una comprobación que corra los seis informes del catálogo con parámetros mínimos y falle si alguno lanza, si alguno devuelve cero filas habiendo nóminas normalizadas en el rango, o si una columna declarada `sensible` sale sin enmascarar. Conserva las identidades de B-00, que son su parte más valiosa.

Actualiza la referencia al script en el plan de la fase 1 y en el diseño si la nombran.

- [ ] **Step 6: Commit**

```bash
.venv/bin/mypy --strict app
git add scripts/ docs/ && git commit -m "test(informes): extender la verificacion en vivo a los cinco informes de la fase 2"
```

---

## Notas de cierre

**Lo que queda listo:** seis informes de nómina en el catálogo (B-01, B-02, B-04, B-05, B-07, B-10), el eje teórico de periodos como pieza compartida, los validadores de datos del receptor, y los fixtures conformes a la regla 12 del proyecto.

**El riesgo principal de esta fase es la duplicación**, y la revisión final de la fase 1 ya lo señaló: cinco informes sobre el mismo universo de nómina van a querer copiar el mismo `_universo`, las mismas banderas y el mismo bloque de columnas del empleado. **Extráelo a un módulo compartido en cuanto aparezca la segunda copia**, no en cuanto aparezca la tercera. Si dos informes calculan el universo distinto, dos informes del mismo periodo darán totales distintos y nadie sabrá cuál creer.

**Lo que sigue (fase 3):** las cinco tablas de configuración del §12 del diseño (`param_fiscal` con UMA y salario mínimo, `catalogo_percepcion_marca` con las marcas del §3.1, `map_departamento`, `map_concepto_provision`, `tabla_vacaciones`), que habilitan B-03 completo, B-06, B-08, la columna 11 de B-05 y las dos validaciones de SBC de B-10. **Las semillas fiscales las valida el dueño del repo antes de cargarse:** son política fiscal, no código.

**Pendiente operativo que sigue limitando el valor de todo esto:** con 2 quincenas y 4 empleados, B-04 es una matriz de 4×4 y B-05 acumula medio ejercicio. Descargar la historia de nómina del SAT es lo que convierte estos informes en algo utilizable — y también lo que hará aparecer los riesgos de volumen que la revisión final de la fase 1 documentó (el informe materializa todo en memoria; entre 5 000 y 15 000 filas habrá que paginarlo).
