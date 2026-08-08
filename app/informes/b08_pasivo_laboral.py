"""B-08 · Provisión de pasivo laboral (§B-08 del documento fuente).

Grano: **una fila por empleado**. Cuantifica el pasivo **devengado y no pagado** por
aguinaldo, vacaciones y prima vacacional a una fecha de corte. Es la cifra que el auditor
externo pide al cierre, y la que puede acabar reconocida en los estados financieros de la
organización: un número inventado aquí no es un informe feo, es un pasivo mal reconocido.

**B-08.R3 — Qué es y qué NO es este número, y por qué se rotula en el libro.** Es una
**estimación con base en los CFDI de nómina**, no un cálculo actuarial. No cubre la prima de
antigüedad (art. 162 LFT) ni ninguno de los beneficios al retiro que la NIF D-3 exige valuar
(pensiones, indemnizaciones por terminación, remuneraciones al término de la relación
laboral). El rótulo va en la hoja `Parámetros` del libro —`ResultadoInforme.notas`, ver
`_NOTAS`—, no solo en este docstring: quien recibe el Excel puede ser el contador que lo va a
usar para armar el asiento, y un docstring no viaja por correo.

Cuándo se genera y cuándo no
------------------------------
Dos puertas, y las dos se evalúan en la misma corrida para que quien configure lo arregle
todo de una pasada en vez de descubrir el segundo hueco después de tapar el primero.

**1. La clasificación de percepciones tiene que estar completa.** Lo que B-08 necesita del
mapeo `map_concepto_provision` es una sola cosa: **cuánto aguinaldo, vacaciones y prima se
pagaron ya**, para restarlo de lo devengado. Lo devengado sale del salario y de los días
trabajados, y no necesita el mapeo para nada. Por eso la condición no es "que existan filas
en `map_concepto_provision`" sino que **no quede ninguna percepción sin clasificar**: con una
sola percepción sin categoría es imposible distinguir *"no se pagó aguinaldo"* de *"sí se
pagó y no sé en cuál concepto viene"*, y las dos hipótesis dan provisiones distintas. El
aviso dice **cuáles** conceptos faltan, no un mensaje genérico.

**Si todas están clasificadas —incluidas las marcadas `NO_APLICA`— el informe se genera**,
porque entonces "aguinaldo pagado = 0" pasa a ser un **hecho conocido**. Una organización
cuyo ejercicio no incluye diciembre tiene legítimamente cero aguinaldo pagado y una provisión
igual al devengado completo.

**La completitud se mide SOLO sobre percepciones** (`cfg.percepciones_sin_clasificar`, que es
donde vive el argumento entero). Aguinaldo, vacaciones y prima vacacional **son percepciones**;
una deducción no puede ser aguinaldo, porque el aguinaldo no se le descuenta a nadie, y los
departamentos son de los centros de costo de B-06. Contar deducciones u otros pagos volvería
la clasificación imposible de completar y B-08 no se generaría **nunca**, por una razón sin
sentido: en la empresa real son tres percepciones frente a siete deducciones y dos
departamentos.

**No se infiere la categoría por el texto del concepto** (B-08.R2 lo prohíbe). En los datos
reales conviven "Fondo ahorro empresa" y "Fondo de Ahorro Empleado": dos conceptos distintos
con textos casi idénticos, y adivinar por cadena de caracteres los confundiría.

**2. Los dos parámetros de política laboral tienen que existir.** `dias_aguinaldo` y
`factor_prima_vacacional` llegan `None` en los parámetros y se resuelven de
`configuracion_empresa`. Si el parámetro viene nulo **y** la configuración también, el informe
**no se genera** y dice qué falta configurar. **No hay 15 días por omisión**: el mínimo legal
del art. 87 LFT son 15, pero muchas organizaciones dan más, y suponer el mínimo
**subestima la provisión** — el error que un auditor no perdona. El parámetro explícito, cuando
viene, gana sobre la configuración: es la corrida puntual con otro supuesto ("¿cuánto sería la
provisión si diéramos 30 días?").

B-08.R1 — El salario diario base, y por qué el orden importa
---------------------------------------------------------------
1. **Preferida:** `Σ (gravado + exento de tipo_percepcion='001') / Σ num_dias_pagados` de los
   **últimos 3 periodos ordinarios** anteriores al corte. Es derivable del CFDI y verificable.
2. **Último recurso:** `nomina_receptor.salario_diario_integrado`. El SDI **ya incluye** la
   parte proporcional de aguinaldo y de prima vacacional (art. 84 LSS), así que usarlo para
   provisionar aguinaldo y prima **integra dos veces** esos conceptos y **sobreestima** la
   provisión.

**Cada fila declara con qué fuente se calculó** (columna «Fuente del salario diario base»).
No es un adorno: sin ese dato nadie que reciba el Excel puede saber si la cifra está inflada
por la vía 2, y las dos vías conviven en la misma hoja.

**Y el numerador y el denominador se arman del MISMO conjunto de comprobantes.** Fue un defecto
Critical de la primera versión (la fórmula literal de la ficha se puede leer como dos conjuntos
distintos, y así se implementó): un periodo que aportaba días sin importe `001` subestimaba el
salario un 33% y uno con `num_dias_pagados` nulo lo inflaba un 50%, en los dos casos **con la
etiqueta de la vía confiable y sin una sola bandera**. Ahora un periodo entra en los dos lados o
en ninguno, y quedarse fuera deja bandera. Ver `_salarios_diarios`, que lleva las dos cifras
medidas.

Cómo se calcula cada columna
-------------------------------
Sea `dias_ejercicio` el largo real del año (365, o 366 si es bisiesto — así un año completo
devenga exactamente el derecho anual y nunca el 100.27% de él), y `dias_trabajados` los días
naturales entre `max(fecha_inicio_rel_laboral, 1-ene)` y la fecha de corte, ambos inclusive:

- **Aguinaldo devengado** = `salario_diario × dias_aguinaldo × dias_trabajados / dias_ejercicio`
  (art. 87 LFT: proporcional al tiempo trabajado en el año).
- **Días de vacaciones del año** salen de `tabla_vacaciones` según la antigüedad cumplida al
  corte (art. 76 LFT). Con menos de un año cumplido el resolutor devuelve `None` a propósito
  —el art. 77 da un derecho **proporcional** que no sale de esa tabla—, así que se toma el
  renglón del primer año como base del prorrateo, que es lo que ese artículo prorratea.
- **Días de vacaciones pendientes** = `dias_del_año × proporción − vacaciones_pagadas /
  salario_diario`, con piso en cero. **Es una estimación y la columna lo dice en su título**:
  el saldo real de vacaciones lo lleva recursos humanos y este sistema no lo tiene; lo único
  observable en el CFDI es lo que se pagó.
- **Prima vacacional devengada** = `dias_del_año × proporción × salario_diario × factor`
  (art. 80 LFT).
- **Cada provisión es `max(0, devengado − pagado)` y nunca es negativa.** Un pagado mayor que
  el devengado es un anticipo o un supuesto de días equivocado, no un activo: reportarlo en
  negativo restaría de la provisión de los demás empleados al sumar la columna.
- **Provisión total** = la suma de las tres provisiones, que son tres columnas visibles de la
  misma fila. La hoja tiene que cuadrar por suma: un total que incluya un sumando que no
  aparece en ninguna columna no es auditable.

Lo que este informe NO puede saber, declarado
------------------------------------------------
Los cinco huecos van rotulados en la hoja `Parámetros` (`_NOTAS`) y no solo aquí, y los tres que
se pueden acotar con el dato que ya está en el universo llevan además bandera o columna: un
residuo declarado en un docstring no llega al contador que recibe el Excel.

- **Una baja no es observable en el CFDI.** No existe fecha de terminación en el complemento
  de nómina, así que el devengo de todos los empleados corre hasta la fecha de corte y la
  provisión de quien dejó la organización a media año sale **de más**. Declararlo era el piso y
  no bastaba: la columna **«Último CFDI del ejercicio»** dice por dónde empezar a conciliar, y
  `POSIBLE_BAJA_EN_EL_EJERCICIO` marca a quien dejó de recibir recibos mucho antes que el resto
  de la plantilla. Ninguna de las dos cosas adivina nada — es el `max(fecha_pago)` que ya viene
  en el universo — y convierten "concilia 300 personas" en "revisa estas tres".
- **La cobertura de los datos puede quedarse muy por detrás del corte.** El devengo legal corre
  hasta el corte con independencia de lo que se haya descargado, así que un informe con corte al
  31 de diciembre sobre un histórico que llega a julio da una cifra anual **correcta como devengo
  y equívoca como observación**. Se emite `COBERTURA_INCOMPLETA_AL_CORTE` con los días sin datos:
  la cifra no cambia, pero quien la firma tiene que saber sobre qué se proyectó.
- **Lo pagado se identifica por su fecha de pago, no por el ejercicio que liquida.** El
  complemento no declara a qué ejercicio corresponde la prestación pagada, así que un aguinaldo
  de 2025 pagado en enero de 2026 se resta del devengado de 2026 (en una prueba, la provisión
  pasa de 7 500 a 500). Es lo que pide la ficha —"lo pagado en el ejercicio"— y va rotulado.
- **Las vacaciones no arrastran ejercicios anteriores.** El art. 78 LFT permite acumular hasta
  18 meses; este cálculo solo devenga el derecho del ejercicio, así que un empleado con saldo
  de 2025 aparece con un año de derecho y su provisión **subestima**. Cerrarlo exige el saldo de
  recursos humanos, que este sistema no tiene.
- **Sin `fecha_inicio_rel_laboral` no hay antigüedad ni proporción devengada**, y por eso las
  columnas calculadas de ese empleado salen **vacías, nunca en cero**, con
  `FALTA_FECHA_INICIO_RELACION_LABORAL`. No se supone "trabajó todo el año": para alguien
  contratado en julio eso duplicaría su provisión, y el dato no está en la configuración sino
  en lo que el sistema de nómina timbra.
- **Una percepción sin `clave` no se puede clasificar** (`map_concepto_provision` la lleva en
  la PK), así que su importe no se puede reconocer como aguinaldo o vacaciones pagados y la
  provisión sale **de más**. Se reporta con `CLAVE_VACIA`, la misma clave que ya usa B-02 para
  el mismo hueco, en vez de bloquear el informe: no hay nada que el usuario pueda configurar
  para bajarla a cero.

Restricciones que este módulo cumple
---------------------------------------
- **`Decimal` de punta a punta, jamás `float`.** Ni un `round()` ni un `quantize()`: el único
  redondeo del sistema está en `app.informes.excel` al escribir la celda (R-T4).
- **El motor enmascara, el informe declara.** CURP y NSS van como `Columna(sensible=True)` y
  este módulo nunca llama a `enmascarar()`. **Ningún mensaje de bandera interpola CURP ni
  NSS** —fue una fuga real en B-10—; el ámbito de las banderas por empleado lleva el RFC.
- **Cero N+1** (regla 11) y **ningún bucle con entrada/salida**: los últimos 3 periodos
  ordinarios de todos los empleados salen de **una** consulta con
  `ROW_NUMBER() OVER (PARTITION BY rfc_receptor)`, no de una por empleado; `tabla_vacaciones`
  se trae entera de **una** consulta (14 renglones de dos enteros) y se resuelve en memoria; y
  las categorías de provisión se leen **una** vez, de `observados_de_empresa`, que ya las trae
  resueltas por concepto.
- **Ningún importe fiscal codificado** (§2.12): los días de aguinaldo, el factor de prima y
  los días de vacaciones salen de `configuracion_empresa` y de `tabla_vacaciones`. Las claves
  de catálogo del SAT van como texto.
- **Una celda vacía suma cero al totalizar en Excel**, así que cuando alguna fila no puede
  calcular su provisión total el libro lo dice con un renglón propio en la hoja `Parámetros`.
  Dejar la celda vacía es lo correcto —un cero afirmaría que a esa persona no se le debe nada—,
  pero sin el conteo la decisión correcta produce un total corto con apariencia de completo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import catalogos, universo_nomina
from app.informes.base import Bandera, Columna, ResultadoInforme
from app.models.comprobante import Comprobante
from app.models.configuracion_fiscal import TablaVacaciones
from app.models.empresa import Empresa
from app.models.enums import CategoriaProvision, EstatusCfdi
from app.models.nomina import Nomina, NominaPercepcion
from app.services import configuracion_fiscal as cfg

CLAVE = "B-08"
NOMBRE = "Provisión de pasivo laboral"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por empleado con el pasivo devengado y no pagado por aguinaldo, vacaciones y "
    "prima vacacional a una fecha de corte. Es una estimación con base en los CFDI de nómina, "
    "no un cálculo actuarial: no cubre prima de antigüedad ni beneficios al retiro (NIF D-3). "
    "No se genera mientras queden percepciones sin clasificar o falte la política laboral de "
    "la empresa (días de aguinaldo y factor de prima vacacional)."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Ver la constante homónima de `app.informes.b02_conceptos_patron`: mismo razonamiento (todo
el grupo B declara `("N",)`) y mismo consumidor (el pre-vuelo del ETL en
`app.worker.tasks._generar_informe_async`)."""

_CERO = Decimal("0")

_CLAVE_PERCEPCION_SUELDO = "001"
"""Clave de `c_TipoPercepcion` de "Sueldos, Salarios Rayas y Jornales": el numerador de la
fuente preferida del salario diario base (B-08.R1). Va como texto — los ceros a la izquierda
son significativos— y es una clave de catálogo del SAT, no un importe fiscal."""

_TIPO_NOMINA_ORDINARIA = "O"
"""`c_TipoNomina`. B-08.R1 promedia **periodos ordinarios**: una nómina extraordinaria (el
aguinaldo, un finiquito) no representa el salario corriente y metería en el promedio justo lo
que este informe está tratando de provisionar."""

ULTIMOS_PERIODOS = 3
"""Cuántos periodos ordinarios entran en el promedio de B-08.R1. Se declara con nombre porque
es el número que la ficha fija y el que hay que cambiar en un solo sitio si se revisa."""

MUESTRA_RFC = 3
"""Cuántos RFC se citan en una bandera colapsada. No cero —quien la lee necesita por dónde
empezar— y no todos: el mensaje dice cuántos hay en total. Mismo criterio que
`universo_nomina.MUESTRA_UUID_COLAPSO`. **Solo RFC**: la CURP y el NSS jamás entran en el
mensaje ni en el ámbito de una bandera (la hoja `Banderas` no se enmascara)."""

MARGEN_COBERTURA_DIAS = 31
"""Cuántos días puede la fecha de corte adelantarse al último CFDI observado antes de que el
informe emita `COBERTURA_INCOMPLETA_AL_CORTE`.

31 días —un mes natural— por el mismo criterio de `universo_nomina.MARGEN_TIMBRADO_DIAS`: una
bandera de más se lee y se descarta, una de menos no se ve nunca. El corte de un cierre normal
cae el mismo día o pocos días después del último pago del ejercicio, así que en la operación
sana esta bandera no aparece.

**Por qué hacía falta.** El devengo del art. 87 LFT corre hasta el corte con independencia de
lo que se haya descargado, así que el informe daba una cifra anual completa sobre un histórico
que llegaba a julio y **el libro no lo decía en ninguna parte**: en la corrida real eran 117 182.62
con cero banderas, una proyección de 12 meses sobre 6.5 observados, presentada como devengo
observado. La cifra no cambia —es la correcta— pero quien la firma tiene que saber sobre qué se
proyectó."""

MAX_CONCEPTOS_EN_AVISO = 15
"""Cuántos conceptos sin clasificar se enumeran en el aviso que bloquea el informe. La empresa
real tiene tres, así que en la práctica se enumeran todos; el tope existe para que una empresa
con un catálogo grande no produzca un aviso ilegible, y el mensaje dice cuántos quedaron
fuera."""

FUENTE_CFDI = f"CFDI · últimos {ULTIMOS_PERIODOS} periodos ordinarios (percepciones tipo {_CLAVE_PERCEPCION_SUELDO})"
FUENTE_SDI = "SDI declarado · último recurso: ya integra aguinaldo y prima, sobreestima la provisión"
FUENTE_AUSENTE = "Sin fuente: no hay percepciones tipo 001 en periodos ordinarios ni SDI declarado"

_NOTAS: tuple[str, ...] = (
    "B-08.R3 — ESTIMACIÓN CON BASE EN CFDI, NO CÁLCULO ACTUARIAL. Las cifras de este informe se "
    "derivan de los CFDI de nómina timbrados y de la política laboral capturada (días de "
    "aguinaldo, factor de prima vacacional, tabla del art. 76 LFT). NO son una valuación "
    "actuarial: no cubren la prima de antigüedad (art. 162 LFT) ni los beneficios al retiro que "
    "la NIF D-3 exige valuar (pensiones, indemnizaciones y remuneraciones al término de la "
    "relación laboral). Para esos conceptos hace falta una valuación independiente.",
    "Los días de vacaciones pendientes son una ESTIMACIÓN por devengo proporcional: el saldo real "
    "de vacaciones lo lleva recursos humanos y este sistema no lo tiene. Lo único observable en el "
    "CFDI es cuánto se pagó por ese concepto.",
    "SOLO SE DEVENGA EL DERECHO DE VACACIONES DE ESTE EJERCICIO: el cálculo no arrastra saldos de "
    "ejercicios anteriores, que el artículo 78 de la LFT permite acumular hasta 18 meses. Un "
    "empleado que no tomó sus vacaciones de 2025 aparece aquí con un solo año de derecho, así que "
    "la provisión de vacaciones y de prima vacacional SUBESTIMA el pasivo en esos casos. El saldo "
    "acumulado hay que pedirlo a recursos humanos.",
    "LO PAGADO SE IDENTIFICA POR SU FECHA DE PAGO, no por el ejercicio que liquida: un aguinaldo "
    "de 2025 pagado en enero de 2026 se resta del devengado de 2026 y deja la provisión corta (en "
    "una prueba, de 7 500 a 500). El complemento de nómina no declara a qué ejercicio corresponde "
    "la prestación que se paga, así que revisa los pagos de aguinaldo y prima de los primeros días "
    "del ejercicio antes de registrar el asiento.",
    "El complemento de nómina no declara la fecha de baja, así que el devengo de todo empleado "
    "corre hasta la fecha de corte: la provisión de quien dejó la organización durante el "
    "ejercicio sale de más. La columna «Último CFDI del ejercicio» dice por dónde empezar a "
    "conciliar contra recursos humanos —quien dejó de recibir recibos antes que el resto—, y los "
    "casos claros llevan bandera `POSIBLE_BAJA_EN_EL_EJERCICIO`.",
)
"""Lo que se rotula en la hoja `Parámetros` del libro (B-08.R3). Va en `ResultadoInforme.notas`
y no solo en este docstring porque quien recibe el Excel es quien tiene que verlo."""


class Parametros(BaseModel):
    ejercicio: int = Field(
        description=(
            "Año fiscal del devengo, sobre `YEAR(nomina.fecha_pago)`. El aguinaldo y las "
            "vacaciones se devengan por ejercicio (arts. 76, 80 y 87 LFT), así que lo pagado "
            "que se resta es lo pagado **en este ejercicio**."
        )
    )
    fecha_corte: date = Field(
        description=(
            "Fecha a la que se mide el pasivo. Los días devengados se cuentan hasta aquí y solo "
            "cuentan como pagados los CFDI con `fecha_pago` menor o igual. Al cierre del "
            "ejercicio es el 31 de diciembre; una fecha posterior se recorta a ese día."
        )
    )
    dias_aguinaldo: int | None = Field(
        None,
        description=(
            "Días de aguinaldo de la organización. Vacío = se toma de `configuracion_empresa`; "
            "si tampoco está ahí, el informe NO se genera. No hay valor por omisión: el mínimo "
            "legal son 15 días (art. 87 LFT) pero muchas organizaciones dan más, y suponer el "
            "mínimo subestima la provisión. Con valor explícito gana sobre la configuración, "
            "para correr el informe con otro supuesto sin tocar la configuración."
        ),
    )
    factor_prima_vacacional: Decimal | None = Field(
        None,
        description=(
            "Factor de prima vacacional en fracción (0.25 = 25%). Vacío = se toma de "
            "`configuracion_empresa`; si tampoco está ahí, el informe NO se genera. El 25% del "
            "art. 80 LFT es un piso, no el valor de todas las organizaciones."
        ),
    )
    incluir_cancelados: bool = Field(
        False,
        description=(
            "Por defecto solo cuentan los CFDI no cancelados (R-T1). Un recibo cancelado no "
            "representa un pago que subsista, así que incluirlo restaría de la provisión un "
            "aguinaldo que nadie cobró."
        ),
    )
    enmascarar_datos_personales: bool = Field(
        True,
        description=(
            "Enmascara CURP y NSS (spec §8). Lo aplica el motor de informes "
            "(`app.informes.excel.escribir_libro`) sobre las columnas que esta consulta marca "
            "como `sensible=True`, no esta consulta directamente."
        ),
    )


@dataclass(slots=True)
class _ParametrosUniverso:
    """Adaptador a `universo_nomina.ParametrosUniverso` desde un informe cuyo grano es el
    **ejercicio con fecha de corte**, no un rango que el usuario elige.

    `tipo_nomina="AMBOS"` y no es una omisión: el aguinaldo se paga casi siempre en una nómina
    **extraordinaria**, y filtrar por ordinaria dejaría fuera justo el pago que este informe
    tiene que restar del devengado — la provisión saldría inflada por el importe completo del
    aguinaldo pagado. El filtro a ordinarias existe, pero solo dentro de B-08.R1, que es donde
    tiene sentido (ver `_salarios_diarios`).
    """

    fecha_desde: date
    fecha_hasta: date
    incluir_cancelados: bool
    tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"


_COLUMNAS: tuple[tuple[str, str, bool], ...] = (
    ("RFC empleado", "texto", False),
    ("CURP", "texto", True),
    ("NSS", "texto", True),
    ("Nombre empleado", "texto", False),
    ("Núm. empleado", "texto", False),
    ("Fecha inicio relación laboral", "fecha", False),
    # La mitigación concreta de la nota sobre las bajas, y no es una heurística: es el dato que
    # ya viene en el universo. Convierte "concilia la plantilla" en "revisa estas tres filas".
    ("Último CFDI del ejercicio", "fecha", False),
    ("Antigüedad al corte (años cumplidos)", "entero", False),
    ("Salario diario base", "monto", False),
    # B-08.R1: sin esta columna nadie puede saber si la cifra viene inflada por el SDI.
    ("Fuente del salario diario base", "texto", False),
    ("Días de aguinaldo", "entero", False),
    ("Aguinaldo devengado", "monto", False),
    ("Aguinaldo pagado en el ejercicio", "monto", False),
    ("Provisión de aguinaldo", "monto", False),
    ("Días de vacaciones del año (art. 76 LFT)", "entero", False),
    ("Vacaciones pagadas en el ejercicio", "monto", False),
    # El título declara la estimación: el saldo real de vacaciones lo lleva recursos humanos.
    ("Días de vacaciones pendientes (estimados)", "decimal", False),
    ("Provisión de vacaciones", "monto", False),
    ("Prima vacacional devengada", "monto", False),
    ("Prima vacacional pagada en el ejercicio", "monto", False),
    ("Provisión de prima vacacional", "monto", False),
    ("Provisión total", "monto", False),
)


def _columnas() -> list[Columna]:
    return [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS]  # type: ignore[arg-type]


def _dec(valor: object) -> Decimal:
    """`Numeric` y `func.sum` devuelven `Decimal`, `float` o `None` según el atributo y el
    dialecto; nunca se opera en binario (mismo patrón que `universo_nomina._dec`)."""
    if valor is None:
        return _CERO
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


@dataclass(frozen=True, slots=True)
class _Vacaciones:
    """Los días del art. 76 LFT que le tocan a cada antigüedad presente en la plantilla, y el
    estado de la tabla para poder explicar un hueco sin mentir sobre su causa."""

    dias_por_antiguedad: dict[int, int | None]
    renglones: int
    """Cuántos renglones tiene `tabla_vacaciones` en total. Distingue "la tabla está vacía" de
    "la tabla existe y no tiene renglón aplicable", que son dos avisos distintos: el primero se
    arregla con la semilla y el segundo con el renglón que falta."""

    minimo_capturado: int | None


async def _vacaciones_por_antiguedad(db: AsyncSession, antiguedades: set[int]) -> _Vacaciones:
    """`tabla_vacaciones` en **una** consulta, resuelta en memoria para todas las antigüedades.

    Antes se llamaba a `cfg.dias_de_vacaciones` una vez por antigüedad distinta. No era N+1 por
    fila —el número de consultas lo acotaba la plantilla, no el volumen de nómina— pero era el
    único bucle con entrada/salida del módulo, y la tabla completa son 14 renglones de dos
    enteros: traerla entera cuesta una consulta y cero riesgo.

    **La regla de resolución es la de `cfg.dias_de_vacaciones` y está duplicada a propósito**
    (el renglón con el mayor `anios_antiguedad` que no exceda la antigüedad consultada, porque
    a partir del sexto año la tabla crece de cinco en cinco y no hay renglón por año). La
    duplicación de una regla legal es exactamente lo que este proyecto evita, así que va
    **atada con una prueba**: `test_la_resolucion_local_de_vacaciones_coincide_con_el_servicio`
    compara las dos implementaciones para 0..50 años y falla en cuanto se separen un carácter.
    """
    filas = (
        await db.execute(select(TablaVacaciones.anios_antiguedad, TablaVacaciones.dias).order_by(TablaVacaciones.anios_antiguedad))
    ).all()
    tabla = [(int(anios), int(dias)) for anios, dias in filas]
    dias_por_antiguedad: dict[int, int | None] = {}
    for antiguedad in sorted(antiguedades):
        # Menos de un año cumplido no sale de la tabla del art. 76: el art. 77 LFT da un derecho
        # **proporcional**, y la base de ese prorrateo es el renglón del primer año — que es el
        # que ese artículo prorratea, y que se lee de la tabla, no se escribe aquí (§2.12).
        buscada = max(antiguedad, 1)
        aplicables = [dias for anios, dias in tabla if anios <= buscada]
        dias_por_antiguedad[antiguedad] = aplicables[-1] if aplicables else None
    return _Vacaciones(dias_por_antiguedad, len(tabla), tabla[0][0] if tabla else None)


def _anios_cumplidos(inicio: date, corte: date) -> int:
    """Antigüedad en años **cumplidos** al corte, por calendario y no dividiendo días entre
    365: quien entró un 29 de febrero cumple años igual, y el renglón de `tabla_vacaciones`
    que le toca depende de haber cumplido el año, no de haber acumulado 365 días."""
    return corte.year - inicio.year - ((corte.month, corte.day) < (inicio.month, inicio.day))


# --------------------------------------------------------------------------------------
# B-08.R1: el salario diario base de todos los empleados, en dos consultas
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SalarioDiario:
    """El salario diario base de un empleado y **con qué se calculó**.

    `valor is None` con `fuente = FUENTE_AUSENTE` no es lo mismo que un salario de cero: el
    primero significa "no hay con qué calcular" y deja las columnas dependientes vacías; un
    cero significaría que a esta persona no se le paga nada, que es una afirmación distinta.
    """

    valor: Decimal | None
    fuente: str


@dataclass(frozen=True, slots=True)
class _SalariosBase:
    """El salario diario de cada empleado más **qué se descartó al calcularlo**.

    Los tres diccionarios de descarte no son telemetría: cada uno es una bandera. Un promedio
    armado sobre menos periodos de los previstos sigue siendo una cifra que alguien tiene que
    mirar antes de firmarla, y sin este dato el informe la publicaba con la etiqueta de la vía
    confiable y sin una sola advertencia.
    """

    por_rfc: dict[str, _SalarioDiario]
    periodos_usados: dict[str, int]
    sin_sueldo: dict[str, int]
    sin_dias: dict[str, int]


async def _salarios_diarios(
    db: AsyncSession,
    empresa_id: int,
    rfc_empresa: str,
    rfcs: set[str],
    corte: date,
    incluir_cancelados: bool,
    sdi_por_rfc: dict[str, Decimal | None],
) -> _SalariosBase:
    """B-08.R1 para **todos** los empleados a la vez: dos consultas, pase lo que pase.

    **Cero N+1 (regla 11), y aquí no era trivial.** "Los últimos 3 periodos ordinarios de cada
    empleado" es la forma canónica de un `SELECT` por empleado; se resuelve con
    `ROW_NUMBER() OVER (PARTITION BY rfc_receptor ORDER BY fecha_pago DESC)` en una subconsulta
    y un filtro `rn <= N` afuera, que MySQL 8 evalúa de una pasada. La segunda consulta suma
    las percepciones tipo `001` de los comprobantes que sobrevivieron al filtro.

    **El numerador y el denominador se arman del MISMO conjunto de comprobantes, y esto fue un
    defecto Critical de la primera versión** (ronda de corrección 1). Aquella sumaba al
    denominador los días de **todo** comprobante que pasaba el `rn <= 3` y al numerador solo las
    percepciones `001` de esos comprobantes, que no es el mismo conjunto: cuando uno de los
    periodos elegidos aportaba a uno y no al otro, `importe / dias` **no era el salario diario de
    nadie**, y la fila seguía declarando «CFDI · últimos 3 periodos ordinarios», que es la
    etiqueta que le dice al contador "este número es de la vía confiable". Falla en los dos
    sentidos y los dos se midieron con un salario real de 500.00/día:

    - **Subestimaba** cuando un periodo aportaba días sin importe `001`: 15 días al denominador y
      cero pesos al numerador daban **333.33** (−33%). Ocurre con una incapacidad que cubre el
      periodo completo (pagada por tipo `014`), con un pago timbrado como asimilado (`029`/`046`)
      o con un aguinaldo timbrado por error como nómina ordinaria.
    - **Sobrestimaba** cuando `num_dias_pagados` venía nulo —es `nullable=True` en el modelo, así
      que basta un ETL parcial—: `_dec(None) → 0` en el denominador mientras el importe sí entraba
      al numerador, y salían **750.00** (+50%) con una provisión total de 31 875 contra 21 250.

    Ahora un periodo elegido **entra en los dos lados o en ninguno**, y quedarse fuera **deja
    bandera** (`PERIODO_SIN_SUELDO_EN_EL_PROMEDIO`, `PERIODO_SIN_DIAS_EN_EL_PROMEDIO`): descartar
    en silencio sería honesto en la aritmética y mudo en el libro, y un promedio sobre menos
    periodos de los previstos sigue siendo una cifra que alguien tiene que mirar.

    **El universo de esta regla no es el del informe**, a propósito: se buscan los últimos
    periodos ordinarios anteriores al corte **sin acotar al ejercicio**. Con una fecha de corte
    en enero, los tres últimos periodos ordinarios están en el año anterior, y acotarlos al
    ejercicio dejaría a toda la plantilla cayendo al SDI —la fuente que sobreestima— por un
    accidente del calendario.

    `sdi_por_rfc` trae el SDI del CFDI más reciente de cada empleado dentro del informe, que es
    la vía 2 de la regla; llega resuelto desde `consultar` porque ese dato ya viene en las filas
    del universo y volver a consultarlo sería una tercera consulta para nada.
    """
    salarios: dict[str, _SalarioDiario] = {}
    periodos_usados: dict[str, int] = {}
    sin_sueldo: dict[str, int] = {}
    sin_dias: dict[str, int] = {}
    if not rfcs:
        return _SalariosBase(salarios, periodos_usados, sin_sueldo, sin_dias)

    recientes = (
        select(
            Comprobante.rfc_receptor.label("rfc"),
            Comprobante.comprobante_id.label("cid"),
            Nomina.num_dias_pagados.label("dias"),
            func.row_number()
            .over(
                partition_by=Comprobante.rfc_receptor,
                order_by=(Nomina.fecha_pago.desc(), Comprobante.comprobante_id.desc()),
            )
            .label("rn"),
        )
        .join(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
        .where(
            Comprobante.empresa_id == empresa_id,
            Comprobante.rfc_emisor == rfc_empresa,
            Comprobante.tipo_comprobante == "N",
            Comprobante.rfc_receptor.in_(sorted(rfcs)),
            Nomina.tipo_nomina == _TIPO_NOMINA_ORDINARIA,
            Nomina.fecha_pago <= corte,
        )
    )
    if not incluir_cancelados:
        recientes = recientes.where(Comprobante.estatus != EstatusCfdi.CANCELADO)
    sub = recientes.subquery()

    # Los días **por comprobante**, no ya sumados por empleado: el filtrado que empareja los dos
    # lados del promedio necesita decidir comprobante por comprobante. `dias` puede venir nulo.
    dias_por_cid: dict[int, Decimal | None] = {}
    cid_a_rfc: dict[int, str] = {}
    elegidos = await db.execute(select(sub.c.rfc, sub.c.cid, sub.c.dias).where(sub.c.rn <= ULTIMOS_PERIODOS))
    for rfc_bruto, cid, dias in elegidos.all():
        cid_a_rfc[int(cid)] = str(rfc_bruto)
        dias_por_cid[int(cid)] = None if dias is None else _dec(dias)

    importe_por_cid: dict[int, Decimal] = {}
    if cid_a_rfc:
        sumas = await db.execute(
            select(
                NominaPercepcion.comprobante_id,
                func.sum(NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento),
            )
            .where(
                NominaPercepcion.comprobante_id.in_(sorted(cid_a_rfc)),
                NominaPercepcion.tipo_percepcion == _CLAVE_PERCEPCION_SUELDO,
            )
            .group_by(NominaPercepcion.comprobante_id)
        )
        for cid, importe in sumas.all():
            importe_por_cid[int(cid)] = _dec(importe)

    # Un periodo elegido entra en los DOS lados del promedio o en NINGUNO, y si queda fuera se
    # anota para que salga bandera. Ver el docstring: aquí vivía el defecto Critical.
    numerador: dict[str, Decimal] = {}
    denominador: dict[str, Decimal] = {}
    for cid in sorted(cid_a_rfc):
        rfc_periodo = cid_a_rfc[cid]
        importe = importe_por_cid.get(cid, _CERO)
        dias_cfdi = dias_por_cid.get(cid)
        if importe <= _CERO:
            sin_sueldo[rfc_periodo] = sin_sueldo.get(rfc_periodo, 0) + 1
            continue
        if dias_cfdi is None or dias_cfdi <= _CERO:
            sin_dias[rfc_periodo] = sin_dias.get(rfc_periodo, 0) + 1
            continue
        numerador[rfc_periodo] = numerador.get(rfc_periodo, _CERO) + importe
        denominador[rfc_periodo] = denominador.get(rfc_periodo, _CERO) + dias_cfdi
        periodos_usados[rfc_periodo] = periodos_usados.get(rfc_periodo, 0) + 1

    for rfc in sorted(rfcs):
        if periodos_usados.get(rfc, 0) > 0:
            # Por construcción el denominador es la suma de los días de los MISMOS comprobantes
            # cuyo importe está en el numerador, y los dos son estrictamente positivos.
            salarios[rfc] = _SalarioDiario(numerador[rfc] / denominador[rfc], FUENTE_CFDI)
            continue
        # Vía 2, el último recurso. Se llega aquí cuando el empleado no tiene ningún periodo
        # ordinario antes del corte, o cuando ninguno de los elegidos aportó importe `001` y días
        # a la vez: sin un par (importe, días) coherente no hay promedio que calcular, y un cero
        # ahí no sería "gana cero", sería "no lo sé".
        sdi = sdi_por_rfc.get(rfc)
        if sdi is not None and sdi > _CERO:
            salarios[rfc] = _SalarioDiario(sdi, FUENTE_SDI)
        else:
            salarios[rfc] = _SalarioDiario(None, FUENTE_AUSENTE)
    return _SalariosBase(salarios, periodos_usados, sin_sueldo, sin_dias)


# --------------------------------------------------------------------------------------
# Lo pagado en el ejercicio, por categoría de provisión
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Pagado:
    """Lo que ya se pagó de cada una de las tres prestaciones, por empleado."""

    aguinaldo: Decimal = _CERO
    vacaciones: Decimal = _CERO
    prima_vacacional: Decimal = _CERO


@dataclass(frozen=True, slots=True)
class _PagosClasificados:
    por_rfc: dict[str, _Pagado]
    importe_sin_clave: Decimal
    conceptos_sin_clave: int


async def _pagos_por_categoria(
    db: AsyncSession, ids: list[int], categorias: dict[tuple[str, str, str], CategoriaProvision]
) -> _PagosClasificados:
    """Lo pagado de aguinaldo, vacaciones y prima vacacional en el ejercicio, **una consulta**
    agregada por `(rfc_receptor, tipo_percepcion, clave)` para todo el universo.

    **La categoría sale del mapeo de la organización, nunca del texto del concepto** (B-08.R2):
    en los datos reales conviven "Fondo ahorro empresa" y "Fondo de Ahorro Empleado", y una
    heurística de cadenas los confundiría con consecuencias contables. El importe de una
    percepción es `gravado + exento`: el aguinaldo trae tramo exento (art. 93, fr. XIV LISR) y
    quedarse con el gravado subestimaría lo pagado, que es lo mismo que **sobreestimar** la
    provisión.

    Una percepción **sin `clave`** no se puede clasificar —`map_concepto_provision` la lleva en
    la PK—, así que su importe se cuenta aparte para poder reportarlo (`CLAVE_VACIA`) en vez de
    tragárselo en silencio.
    """
    por_rfc: dict[str, _Pagado] = {}
    if not ids:
        return _PagosClasificados(por_rfc, _CERO, 0)

    filas = await db.execute(
        select(
            Comprobante.rfc_receptor,
            NominaPercepcion.tipo_percepcion,
            NominaPercepcion.clave,
            func.sum(NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento),
        )
        .join(NominaPercepcion, NominaPercepcion.comprobante_id == Comprobante.comprobante_id)
        .where(Comprobante.comprobante_id.in_(ids))
        .group_by(Comprobante.rfc_receptor, NominaPercepcion.tipo_percepcion, NominaPercepcion.clave)
    )

    importe_sin_clave = _CERO
    claves_sin_clave: set[tuple[str, str]] = set()
    for rfc_receptor, tipo, clave, importe in filas.all():
        rfc = str(rfc_receptor)
        monto = _dec(importe)
        if clave is None:
            importe_sin_clave += monto
            claves_sin_clave.add((cfg.NATURALEZA_PERCEPCION, str(tipo)))
            continue
        categoria = categorias.get((cfg.NATURALEZA_PERCEPCION, str(tipo), str(clave)))
        if categoria is None or categoria is CategoriaProvision.NO_APLICA:
            # `None` es inalcanzable con la puerta de completitud cerrada (ver `consultar`);
            # se trata igual que `NO_APLICA` para que este agregador siga siendo correcto si
            # algún día se llama desde otro sitio.
            continue
        acumulado = por_rfc.setdefault(rfc, _Pagado())
        if categoria is CategoriaProvision.AGUINALDO:
            acumulado.aguinaldo += monto
        elif categoria is CategoriaProvision.VACACIONES:
            acumulado.vacaciones += monto
        else:
            acumulado.prima_vacacional += monto

    return _PagosClasificados(por_rfc, importe_sin_clave, len(claves_sin_clave))


# --------------------------------------------------------------------------------------
# Las dos puertas: por qué el informe puede no generarse
# --------------------------------------------------------------------------------------


def _nombre_de_concepto(concepto: cfg.ConceptoObservado) -> str:
    """`P/001/019 (Vacaciones a tiempo)`: la clave con la que se captura el mapeo más la
    descripción con la que la persona lo reconoce. Nadie conoce de memoria `P/001/019`."""
    texto = concepto.concepto or catalogos.descripcion(concepto.naturaleza, concepto.tipo)
    clave = concepto.clave if concepto.clave is not None else "(sin clave)"
    base = f"{concepto.naturaleza}/{concepto.tipo}/{clave}"
    return f"{base} ({texto})" if texto else base


def _lista_de_conceptos(conceptos: list[cfg.ConceptoObservado]) -> str:
    nombres = [_nombre_de_concepto(c) for c in conceptos[:MAX_CONCEPTOS_EN_AVISO]]
    resto = len(conceptos) - len(nombres)
    return "; ".join(nombres) + (f"; y {resto} más" if resto > 0 else "")


def _bandera_de_clasificacion_incompleta(sin_clasificar: list[cfg.ConceptoObservado]) -> Bandera:
    """`CLASIFICACION_INCOMPLETA`: la puerta 1, con **los nombres** de lo que falta.

    Un mensaje genérico ("falta clasificar conceptos") mandaría a abrir una pantalla a buscar
    cuáles; con la lista, el arreglo es ir y elegir categoría en esos renglones. Se enumeran
    **solo percepciones** porque solo ellas cuentan para la completitud (ver el docstring del
    módulo y `cfg.percepciones_sin_clasificar`).
    """
    return Bandera(
        clave="CLASIFICACION_INCOMPLETA",
        severidad="alta",
        ambito="informe",
        mensaje=(
            f"El informe no se generó: quedan {len(sin_clasificar)} percepción(es) sin categoría de "
            "provisión, y sin eso es imposible distinguir «no se pagó aguinaldo» de «sí se pagó y no sé "
            "en cuál concepto viene» — las dos hipótesis dan provisiones distintas. Falta clasificar: "
            f"{_lista_de_conceptos(sin_clasificar)}. Clasifícalas en Configuración › Fiscal › Conceptos "
            "de provisión; las que no sean aguinaldo, vacaciones ni prima vacacional se marcan "
            "«NO_APLICA», que es lo que convierte «pagado = 0» en un hecho conocido. Las deducciones y "
            "los departamentos NO cuentan para esto."
        ),
    )


def _enumerar(partes: list[str]) -> str:
    """`"a"`, `"a y b"`, `"a, b y c"`. Con `", ".join` la frase "falta capturar los días de
    aguinaldo, el factor de prima vacacional" se lee como una lista truncada, y el mensaje que
    más se va a ver en vivo es justamente este."""
    if len(partes) <= 1:
        return "".join(partes)
    return f"{', '.join(partes[:-1])} y {partes[-1]}"


def _bandera_de_falta_configuracion(faltantes: list[str]) -> Bandera:
    """`FALTA_CONFIGURACION_DE_PROVISION`: la puerta 2. **No hay valor por omisión** y el
    mensaje explica por qué, porque "pon 15" es exactamente lo que alguien haría al leerlo."""
    return Bandera(
        clave="FALTA_CONFIGURACION_DE_PROVISION",
        severidad="alta",
        ambito="informe",
        mensaje=(
            f"El informe no se generó: falta capturar {_enumerar(faltantes)} en la configuración de la "
            "empresa (Configuración › Empresa), o pasarlo como parámetro de esta corrida. No se supone "
            "ningún valor por omisión a propósito: el mínimo legal es de 15 días de aguinaldo (art. 87 "
            "LFT) y 25% de prima vacacional (art. 80 LFT), pero son pisos y muchas organizaciones dan "
            "más — suponer el mínimo subestimaría la provisión, que es el error que un auditor no "
            "perdona."
        ),
    )


# --------------------------------------------------------------------------------------
# Banderas de degradación por empleado, colapsadas por causa
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Recuento:
    """Lo que hace falta para colapsar N hallazgos idénticos en una sola bandera con su
    conteo: la lección del colapso de banderas de la fase 2. Guarda **RFC**, nunca CURP ni
    NSS — la hoja `Banderas` no se enmascara."""

    empleados: int = 0
    periodos: int = 0
    """Cuántos periodos de nómina están detrás del conteo, cuando la causa se cuenta por periodo
    y no solo por empleado (los dos descartes del promedio de B-08.R1). Cero significa "esta
    causa no se cuenta por periodo" y entonces no se menciona en el mensaje."""
    rfcs: list[str] = field(default_factory=list)

    def sumar(self, rfc: str, periodos: int = 0) -> None:
        self.empleados += 1
        self.periodos += periodos
        if len(self.rfcs) < MUESTRA_RFC:
            self.rfcs.append(rfc)

    @property
    def muestra(self) -> str:
        return ", ".join(self.rfcs)


_MENSAJES_DE_CAUSA: dict[str, str] = {
    "SALARIO_DE_ULTIMO_RECURSO": (
        "No hay percepciones tipo 001 en sus últimos periodos ordinarios, así que su salario diario base "
        "salió del SDI declarado en el CFDI (B-08.R1, vía 2). El SDI ya integra la parte proporcional de "
        "aguinaldo y de prima vacacional (art. 84 LSS), así que la provisión de esas filas está "
        "SOBREESTIMADA: integra dos veces los mismos conceptos. Cada fila lo declara en la columna "
        "«Fuente del salario diario base»."
    ),
    "SIN_SALARIO_DIARIO_BASE": (
        "No se pudo determinar su salario diario base por ninguna de las dos vías de B-08.R1: no tienen "
        "percepciones tipo 001 en periodos ordinarios anteriores al corte ni SDI declarado en el "
        "complemento. Sus columnas de provisión salen vacías, no en cero: un cero afirmaría que no se les "
        "debe nada."
    ),
    "FALTA_FECHA_INICIO_RELACION_LABORAL": (
        "Su complemento de nómina no trae `FechaInicioRelLaboral`, así que no hay antigüedad con la que "
        "resolver los días de vacaciones del art. 76 LFT ni proporción de año trabajado con la que "
        "devengar el aguinaldo. Sus columnas calculadas salen vacías: no se supone «trabajó todo el año» "
        "porque para alguien contratado a mitad de ejercicio eso duplicaría su provisión. No se arregla "
        "en la configuración sino en el sistema de nómina que timbra."
    ),
    "FECHA_INICIO_POSTERIOR_AL_CORTE": (
        "Declaran una `FechaInicioRelLaboral` posterior a la fecha de corte del informe, lo que no puede "
        "ser cierto de alguien a quien ya se le timbró nómina. Se les devengó cero días, así que su "
        "provisión sale en cero; revisa la captura de esa fecha en el sistema de nómina."
    ),
    "PERIODO_SIN_SUELDO_EN_EL_PROMEDIO": (
        "Alguno de sus últimos periodos ordinarios no trae ninguna percepción tipo 001, así que se "
        "DESCARTÓ del promedio del salario diario base (B-08.R1) en vez de aportar sus días al "
        "denominador con cero pesos al numerador: eso habría subestimado el salario —hasta un −33% en "
        "la prueba que fija esta regla— y con él toda la provisión. Su salario salió del promedio de "
        "los periodos restantes, que son MENOS de los previstos. Ocurre con una incapacidad que cubre "
        "el periodo completo (pagada por tipo 014), con un pago timbrado como asimilado (029/046) o "
        "con un aguinaldo timbrado por error como nómina ordinaria: vale la pena mirar esas filas "
        "antes de usar la cifra."
    ),
    "PERIODO_SIN_DIAS_EN_EL_PROMEDIO": (
        "Alguno de sus últimos periodos ordinarios trae percepciones tipo 001 pero no trae "
        "`num_dias_pagados` (es opcional en el complemento y un ETL parcial lo deja nulo), así que se "
        "DESCARTÓ del promedio del salario diario base (B-08.R1): sumar su importe al numerador sin "
        "sumar sus días al denominador habría inflado el salario —hasta un +50% en la prueba que fija "
        "esta regla— y con él toda la provisión. Su salario salió del promedio de los periodos "
        "restantes; revisa la normalización de esos CFDI."
    ),
    "POSIBLE_BAJA_EN_EL_EJERCICIO": (
        "Dejaron de recibir CFDI de nómina mucho antes que el resto de la plantilla (ver la columna "
        "«Último CFDI del ejercicio»). El complemento de nómina no declara la fecha de baja, así que "
        "el devengo de estas filas corrió hasta la fecha de corte y su provisión puede estar DE MÁS. "
        "No es una conclusión, es la lista corta con la que conciliar contra recursos humanos: "
        "también lo produce una licencia sin goce de sueldo o una descarga incompleta de ese empleado."
    ),
}


def _banderas_por_causa(recuentos: dict[str, _Recuento]) -> list[Bandera]:
    """Una bandera por causa con el conteo de empleados afectados, nunca una por empleado."""
    banderas: list[Bandera] = []
    for causa in sorted(recuentos):
        recuento = recuentos[causa]
        # Las dos causas de descarte del promedio se cuentan también por periodo: "3 empleados"
        # no dice si fue un periodo de cada uno o los tres de uno, y el daño no es el mismo.
        periodos = f" Periodos descartados del promedio: {recuento.periodos}." if recuento.periodos else ""
        banderas.append(
            Bandera(
                clave=causa,
                severidad="alta",
                ambito="informe",
                mensaje=(
                    f"{_MENSAJES_DE_CAUSA[causa]} Empleados afectados: {recuento.empleados} "
                    f"(muestra de RFC: {recuento.muestra}).{periodos}"
                ),
            )
        )
    return banderas


# --------------------------------------------------------------------------------------
# La consulta
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Empleado:
    """La identidad y los insumos por empleado, tomados del CFDI **más reciente** del
    ejercicio: si alguien cambió de puesto o le corrigieron el NSS a media año, interesa su
    último estado (mismo criterio que B-05)."""

    curp: str | None = None
    nss: str | None = None
    nombre: str | None = None
    num_empleado: str | None = None
    fecha_inicio: date | None = None
    ultimo_pago: date | None = None
    sdi: Decimal | None = None


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    columnas = _columnas()
    empresa = await db.get(Empresa, empresa_id)
    if empresa is None:
        return ResultadoInforme(columnas=columnas, aviso="La empresa no existe.", notas=list(_NOTAS))

    inicio_ejercicio = date(p.ejercicio, 1, 1)
    fin_ejercicio = date(p.ejercicio, 12, 31)
    if p.fecha_corte < inicio_ejercicio:
        return ResultadoInforme(
            columnas=columnas,
            aviso=(
                f"La fecha de corte ({p.fecha_corte}) es anterior al ejercicio {p.ejercicio}: no hay "
                "nada devengado que provisionar."
            ),
            notas=list(_NOTAS),
        )
    # Una fecha de corte posterior al cierre se recorta: el devengo del ejercicio no puede
    # pasar del 31 de diciembre, y dejarla correr daría una proporción mayor que 1.
    corte = min(p.fecha_corte, fin_ejercicio)

    p_universo = _ParametrosUniverso(inicio_ejercicio, corte, p.incluir_cancelados)
    # §9 del diseño, resuelto ANTES de cualquier retorno temprano: si el ETL falló en todos los
    # CFDI del ejercicio, estas banderas son el único rastro de que había nómina que provisionar.
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, empresa.rfc, p_universo)

    # --- Las dos puertas, evaluadas juntas -------------------------------------------------
    # Se evalúan las dos aunque la primera ya bloquee: quien configura arregla los dos huecos
    # en una pasada en vez de descubrir el segundo después de tapar el primero.
    motivos: list[str] = []
    banderas_puerta: list[Bandera] = []

    observados = await cfg.observados_de_empresa(db, empresa)
    sin_clasificar = cfg.percepciones_sin_clasificar(observados)
    if sin_clasificar:
        banderas_puerta.append(_bandera_de_clasificacion_incompleta(sin_clasificar))
        motivos.append(
            f"faltan por clasificar {len(sin_clasificar)} percepción(es): {_lista_de_conceptos(sin_clasificar)}"
        )

    config = await cfg.configuracion_de_empresa(db, empresa_id)
    dias_aguinaldo = p.dias_aguinaldo if p.dias_aguinaldo is not None else (config.dias_aguinaldo if config else None)
    factor_prima = (
        p.factor_prima_vacacional
        if p.factor_prima_vacacional is not None
        else (config.factor_prima_vacacional if config else None)
    )
    faltantes = [
        nombre
        for nombre, valor in (("los días de aguinaldo", dias_aguinaldo), ("el factor de prima vacacional", factor_prima))
        if valor is None
    ]
    if faltantes:
        banderas_puerta.append(_bandera_de_falta_configuracion(faltantes))
        motivos.append(f"falta configurar {_enumerar(faltantes)}")

    if motivos:
        return ResultadoInforme(
            columnas=columnas,
            banderas=banderas_fuera + banderas_puerta,
            aviso="El informe no se generó porque " + "; y ".join(motivos) + ".",
            notas=list(_NOTAS),
        )
    # `mypy` no deduce de `faltantes` que los dos son distintos de `None`; el `assert` documenta
    # lo que la puerta ya garantizó y no puede fallar en tiempo de ejecución.
    assert dias_aguinaldo is not None and factor_prima is not None

    filas_universo = list((await db.execute(universo_nomina.universo(empresa_id, empresa.rfc, p_universo))).all())
    if not filas_universo:
        return ResultadoInforme(
            columnas=columnas,
            banderas=banderas_fuera,
            aviso=f"Sin CFDI de nómina del ejercicio {p.ejercicio} hasta el {corte}.",
            notas=list(_NOTAS),
        )

    ids = [fila[0].comprobante_id for fila in filas_universo]
    banderas: list[Bandera] = list(banderas_fuera)
    banderas.extend(universo_nomina.banderas_de_estatus(universo_nomina.comprobantes_y_detalles(filas_universo)))
    banderas.extend(await universo_nomina.banderas_de_gravado_y_exento_descuadrados(db, ids))

    # Identidad e insumos por empleado. `universo()` ordena por `fecha_pago` ascendente, así
    # que sobrescribir en el orden de iteración deja la fotografía más reciente (B-05).
    empleados: dict[str, _Empleado] = {}
    for comprobante, nomina, receptor, _totales, detalle in filas_universo:
        rfc = str(comprobante.rfc_receptor)
        registro = empleados.setdefault(rfc, _Empleado())
        if receptor is not None:
            registro.curp = receptor.curp
            registro.nss = receptor.nss
            registro.num_empleado = receptor.num_empleado
            registro.sdi = receptor.salario_diario_integrado
            if receptor.fecha_inicio_rel_laboral is not None:
                registro.fecha_inicio = receptor.fecha_inicio_rel_laboral
        if detalle is not None:
            registro.nombre = detalle.nombre_receptor
        if nomina.fecha_pago is not None and (registro.ultimo_pago is None or nomina.fecha_pago > registro.ultimo_pago):
            registro.ultimo_pago = nomina.fecha_pago

    # Las categorías salen de `observados`, que ya las trae resueltas por concepto: llamar otra
    # vez a `cfg.categorias_de_provision` leía `map_concepto_provision` **dos veces** por corrida
    # (`observados_de_empresa` la lee por dentro). `observados` no filtra por fecha ni estatus, así
    # que es un superconjunto de los conceptos del universo y la búsqueda nunca se queda corta.
    categorias = {
        (concepto.naturaleza, concepto.tipo, concepto.clave): concepto.categoria
        for concepto in observados.conceptos
        if concepto.clave is not None and concepto.categoria is not None
    }
    pagos = await _pagos_por_categoria(db, ids, categorias)
    salarios = await _salarios_diarios(
        db,
        empresa_id,
        empresa.rfc,
        set(empleados),
        corte,
        p.incluir_cancelados,
        {rfc: registro.sdi for rfc, registro in empleados.items()},
    )

    if pagos.conceptos_sin_clave:
        banderas.append(
            Bandera(
                clave="CLAVE_VACIA",
                severidad="alta",
                ambito="informe",
                mensaje=(
                    f"{pagos.conceptos_sin_clave} tipo(s) de percepción del ejercicio vienen sin clave del "
                    f"patrón, por un total de {pagos.importe_sin_clave}. Sin clave no se pueden clasificar "
                    "—`map_concepto_provision` la lleva en la llave primaria—, así que ese importe no se "
                    "reconoció como aguinaldo, vacaciones ni prima pagados: si alguna de esas percepciones lo "
                    "era, la provisión de este informe sale DE MÁS. No se arregla en la configuración sino en "
                    "el sistema de nómina que timbra (el nodo `Concepto` debe traer su clave)."
                ),
            )
        )

    dias_ejercicio = Decimal((fin_ejercicio - inicio_ejercicio).days + 1)

    # `COBERTURA_INCOMPLETA_AL_CORTE`: el devengo corre hasta el corte con independencia de lo que
    # se haya descargado, así que sin esto el informe publicaba una proyección anual sobre un
    # histórico parcial y el libro no lo decía en ninguna parte (ver `MARGEN_COBERTURA_DIAS`).
    pagos_observados = [r.ultimo_pago for r in empleados.values() if r.ultimo_pago is not None]
    ultimo_observado = max(pagos_observados) if pagos_observados else None
    if ultimo_observado is not None and (corte - ultimo_observado).days > MARGEN_COBERTURA_DIAS:
        dias_sin_datos = (corte - ultimo_observado).days
        banderas.append(
            Bandera(
                clave="COBERTURA_INCOMPLETA_AL_CORTE",
                severidad="alta",
                ambito="informe",
                mensaje=(
                    f"El último CFDI de nómina observado del ejercicio se pagó el {ultimo_observado} y el "
                    f"devengo de este informe corre hasta el {corte}: hay {dias_sin_datos} días sin datos "
                    "observados. Las cifras devengadas de ese tramo son una PROYECCIÓN sobre el salario y la "
                    "antigüedad conocidos, no un devengo observado, y lo pagado de ese tramo no se pudo "
                    "restar porque todavía no está descargado. No es un error de cálculo —el devengo legal "
                    "del art. 87 LFT corre igual—, pero no uses esta cifra para un cierre sin descargar el "
                    "ejercicio completo o sin mover la fecha de corte al último periodo timbrado."
                ),
            )
        )

    antiguedades: set[int] = set()
    for registro in empleados.values():
        if registro.fecha_inicio is not None:
            antiguedades.add(max(_anios_cumplidos(registro.fecha_inicio, corte), 0))
    vacaciones = await _vacaciones_por_antiguedad(db, antiguedades)
    dias_vacaciones = vacaciones.dias_por_antiguedad

    sin_resolver = sorted(a for a, dias in dias_vacaciones.items() if dias is None)
    if sin_resolver:
        # Dos huecos distintos con dos arreglos distintos, y la primera versión afirmaba el
        # primero también cuando era el segundo: decirle a alguien que su tabla está vacía cuando
        # tiene 14 renglones lo manda a revisar donde no está el problema.
        if vacaciones.renglones == 0:
            causa = (
                "No hay ningún renglón en `tabla_vacaciones` (art. 76 LFT). Cárgala con la semilla "
                "`config/fiscal/tabla_vacaciones.yaml`."
            )
        else:
            causa = (
                f"`tabla_vacaciones` tiene {vacaciones.renglones} renglón(es) pero ninguno aplicable a "
                f"{_enumerar([str(a) for a in sin_resolver])} año(s) de antigüedad: el renglón más bajo "
                f"capturado es el de {vacaciones.minimo_capturado} año(s) y el art. 76 LFT arranca en 1. "
                "Falta ese renglón en la tabla, no la tabla entera."
            )
        banderas.append(
            Bandera(
                clave="FALTA_TABLA_VACACIONES",
                severidad="alta",
                ambito="informe",
                mensaje=(
                    f"{causa} Sin días de vacaciones no se pudo calcular a cuánto tiene derecho la "
                    "plantilla afectada: sus columnas de vacaciones y de prima vacacional salieron vacías, "
                    "y la provisión total con ellas."
                ),
            )
        )

    recuentos: dict[str, _Recuento] = {}

    def _anotar(causa: str, rfc: str, periodos: int = 0) -> None:
        recuentos.setdefault(causa, _Recuento()).sumar(rfc, periodos)

    filas: list[list[Any]] = []
    no_calculables = 0
    for rfc in sorted(empleados):
        registro = empleados[rfc]
        salario = salarios.por_rfc.get(rfc, _SalarioDiario(None, FUENTE_AUSENTE))
        pagado = pagos.por_rfc.get(rfc, _Pagado())

        if salario.fuente == FUENTE_SDI:
            _anotar("SALARIO_DE_ULTIMO_RECURSO", rfc)
        elif salario.valor is None:
            _anotar("SIN_SALARIO_DIARIO_BASE", rfc)
        if salarios.sin_sueldo.get(rfc):
            _anotar("PERIODO_SIN_SUELDO_EN_EL_PROMEDIO", rfc, salarios.sin_sueldo[rfc])
        if salarios.sin_dias.get(rfc):
            _anotar("PERIODO_SIN_DIAS_EN_EL_PROMEDIO", rfc, salarios.sin_dias[rfc])
        # La lista corta de la nota sobre bajas: dejó de recibir recibos mucho antes que el resto.
        # Con un solo empleado en el informe nunca dispara, y así debe ser: no hay "el resto" con
        # quien comparar, y el hueco global ya lo cubre `COBERTURA_INCOMPLETA_AL_CORTE`.
        if (
            ultimo_observado is not None
            and registro.ultimo_pago is not None
            and (ultimo_observado - registro.ultimo_pago).days > MARGEN_COBERTURA_DIAS
        ):
            _anotar("POSIBLE_BAJA_EN_EL_EJERCICIO", rfc)

        anios: int | None = None
        proporcion: Decimal | None = None
        if registro.fecha_inicio is None:
            _anotar("FALTA_FECHA_INICIO_RELACION_LABORAL", rfc)
        else:
            anios = max(_anios_cumplidos(registro.fecha_inicio, corte), 0)
            if registro.fecha_inicio > corte:
                _anotar("FECHA_INICIO_POSTERIOR_AL_CORTE", rfc)
            inicio_devengo = max(registro.fecha_inicio, inicio_ejercicio)
            dias_trabajados = max((corte - inicio_devengo).days + 1, 0)
            proporcion = Decimal(dias_trabajados) / dias_ejercicio

        base = salario.valor
        dias_vac = dias_vacaciones.get(anios) if anios is not None else None

        # Aguinaldo (art. 87 LFT). Vacío —nunca cero— cuando falta el salario o la proporción:
        # un cero afirmaría que a esta persona no se le debe aguinaldo.
        agu_devengado = (
            base * Decimal(dias_aguinaldo) * proporcion if base is not None and proporcion is not None else None
        )
        agu_provision = max(_CERO, agu_devengado - pagado.aguinaldo) if agu_devengado is not None else None

        # Vacaciones (arts. 76 y 77 LFT) y prima vacacional (art. 80 LFT).
        dias_vac_pendientes: Decimal | None = None
        vac_provision: Decimal | None = None
        prima_devengada: Decimal | None = None
        prima_provision: Decimal | None = None
        if base is not None and proporcion is not None and dias_vac is not None:
            dias_devengados = Decimal(dias_vac) * proporcion
            dias_vac_pendientes = max(_CERO, dias_devengados - pagado.vacaciones / base)
            vac_provision = dias_vac_pendientes * base
            prima_devengada = dias_devengados * base * factor_prima
            prima_provision = max(_CERO, prima_devengada - pagado.prima_vacacional)

        # La provisión total es la suma de las tres columnas visibles de la fila, y sale vacía
        # si falta cualquiera de ellas: un total parcial se ve exactamente igual que uno
        # completo en la celda, y sería un pasivo corto con apariencia de correcto.
        provision_total: Decimal | None = None
        if agu_provision is not None and vac_provision is not None and prima_provision is not None:
            provision_total = agu_provision + vac_provision + prima_provision
        else:
            no_calculables += 1

        filas.append(
            [
                rfc,
                registro.curp,
                registro.nss,
                registro.nombre,
                registro.num_empleado,
                registro.fecha_inicio,
                registro.ultimo_pago,
                anios,
                base,
                salario.fuente,
                dias_aguinaldo,
                agu_devengado,
                pagado.aguinaldo,
                agu_provision,
                dias_vac,
                pagado.vacaciones,
                dias_vac_pendientes,
                vac_provision,
                prima_devengada,
                pagado.prima_vacacional,
                prima_provision,
                provision_total,
            ]
        )

    banderas.extend(_banderas_por_causa(recuentos))

    notas = list(_NOTAS)
    if no_calculables:
        # **Una celda vacía suma cero al totalizar en Excel**, así que una fila sin provisión se ve
        # igual que una fila en cero para quien arrastra la columna. Dejarlas vacías es lo correcto
        # —un cero afirmaría que no se le debe nada a esa persona— pero entonces el libro tiene que
        # decir cuántas son, o la decisión correcta produce un total corto con apariencia completa.
        notas.append(
            f"ATENCIÓN AL TOTALIZAR: {no_calculables} de las {len(filas)} filas tienen «Provisión total» "
            "vacía porque faltó un insumo (la hoja Banderas dice cuál para cada causa). Una celda vacía "
            "suma CERO en Excel, así que el total de esa columna EXCLUYE a esos empleados y el pasivo real "
            "es mayor que la suma que devuelve la hoja de cálculo."
        )
    return ResultadoInforme(columnas=columnas, filas=filas, banderas=banderas, notas=notas)
