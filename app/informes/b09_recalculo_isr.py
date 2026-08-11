"""B-09 · Recálculo de ISR y subsidio al empleo por recibo (§B-09 del documento fuente).

**Lo que este informe afirma, y lo que no.** Compara el ISR que cada recibo debería tener según
la tarifa que el SAT publica en el Anexo 8 de la RMF contra el que el patrón timbró en el CFDI.
**No dictamina** que una diferencia sea un error: dice que, con la tarifa cargada y confirmada en
este Hub, el número no coincide. Una diferencia real puede venir de varias fuentes legítimas que
este informe no reproduce — el subsidio al empleo (si no está confirmado, este informe ni
siquiera lo calcula: ver la degradación abajo), un periodo irregular (menos o más días que los
nominales de su periodicidad, prorrateado por el art. 175 del Reglamento), o el procedimiento
opcional del art. 174 (ingreso mensual estimado con ajuste posterior), que este informe no
implementa y solo detecta por indicio (Task 4). Lo que este informe **sí** puede afirmar con
certeza es que compara contra la tarifa vigente, y que si el número del patrón no coincide, hay
algo que revisar — no necesariamente un error del proveedor de nómina.

Grano: **una fila por recibo (UUID)**, igual que el resto del universo del grupo B que reporta
CFDI de nómina uno a uno.

Esta tarea (3 del plan) entrega **filas y columnas correctas**: el universo, la base gravable, el
recálculo y las **24 columnas** de datos del documento fuente. El documento numera 21 renglones,
pero sus dos primeros agrupan varios campos cada uno ("UUID / Fecha pago / Periodo",
"RFC / Nombre / Núm. empleado"); expandidos uno a uno —como ya hace B-03 con el mismo tipo de
grupo— son 24 columnas físicas, no 21 (una ronda de revisión de esta misma tarea corrigió el
conteo). La fila 21 del documento ("Bandera") **no** es una columna de esta hoja: en este
proyecto los hallazgos van a la hoja `Banderas` (`ResultadoInforme.banderas`), nunca a una celda
de texto por fila.

Las banderas de comparación (`COINCIDE`, `DIFERENCIA_MENOR`, `DIFERENCIA_MAYOR`,
`ISR_CERO_CON_BASE`, `PERIODO_IRREGULAR`, `PERCEPCIONES_EXTRAORDINARIAS`, `PROCEDIMIENTO_ART174`,
`DIFERENCIA_SISTEMATICA`) son la tarea 4 (§6 del diseño): el juicio que separa un hallazgo de un
recibo que no necesita revisión — ver la sección dedicada más abajo. Esta tarea (3) emite dos
banderas propias, las dos sobre **si** se pudo calcular, no sobre si el número coincide:

- `RECIBO_NO_CALCULABLE` (alta): el recibo no se pudo recalcular — cero días pagados, falta el
  nodo del receptor o su periodicidad de pago, o ni siquiera la tarifa de repuesto (ver B-09.R1
  abajo) está confirmada. Impide que un solo recibo raro tumbe la corrida completa.
- `TARIFA_PROPORCIONADA` (media, B-09.R1): el Anexo 8 no publica tarifa para la periodicidad de
  este recibo, así que se usó la mensual prorrateada — ver la sección de abajo.

La base gravable son **solo las percepciones ordinarias**
-----------------------------------------------------------
`Σ importe_gravado` de las percepciones cuyo tipo está marcado `es_ingreso_ordinario = true` en
`catalogo_percepcion_marca` **confirmada** — nunca el gravado total del recibo. Un aguinaldo, una
PTU o una prima vacacional no se gravan con la tarifa del periodo (tienen su propio tratamiento),
así que meterlos en la base infla el ISR teórico y produce una acusación falsa contra el patrón.
Ver `_gravado_por_tipo` y `_base_ordinaria`.

La degradación es por partes (§5 del diseño), heredada de `app.informes.configuracion_isr`
--------------------------------------------------------------------------------------------
- **Sin tarifa confirmada** para alguna periodicidad presente en los recibos del rango, o **sin
  alguna marca de percepción confirmada** de los tipos que de verdad aparecen: **no se generan
  filas**, y el `aviso` es literalmente el texto de `configuracion_isr` (nunca reescrito aquí).
  Una base gravable inventada con el gravado total sería peor que ningún informe.
- **Sin el subsidio al empleo** (UMA mensual, factor o tope sin confirmar): el informe **sí se
  genera** — el ISR determinado no depende del subsidio — y solo las tres columnas del subsidio
  (`Subsidio al empleo teórico`, `ISR a retener teórico`, `Subsidio a entregar teórico`, y lo que
  de ellas depende: `Diferencia de subsidio`) quedan vacías.

El recibo con cero días pagados, o sin receptor, o sin periodicidad (hueco explícito de esta tarea)
------------------------------------------------------------------------------------------------------
`tarifa_isr.isr_del_periodo` y `subsidio_del_periodo` lanzan `TarifaInvalida` cuando
`num_dias_pagados <= 0` (una baja el día 1 es un dato real, no un caso imaginario). Esta tarea
**captura** esa excepción por recibo, deja sus columnas de cálculo vacías (`None`, nunca cero: un
cero ahí se leería como "no le tocó ISR", que es un hallazgo distinto de "no se pudo calcular") y
emite `RECIBO_NO_CALCULABLE` con el mensaje de la excepción — la corrida completa sigue, no se
rompe por un recibo atípico.

El mismo tratamiento aplica a los recibos sin nodo de receptor (`nomina_receptor`, que llega por
`LEFT JOIN` en `universo_nomina.universo` y puede faltar), sin `num_dias_pagados`, o sin
`periodicidad_pago`: son datos del propio CFDI, no de configuración, y su ausencia deja el recibo
igual de no calculable que un cero en los días. Ninguno de estos casos tumba la corrida.

B-09.R1 — la periodicidad sin tarifa publicada usa la mensual prorrateada
------------------------------------------------------------------------------
`tarifa_isr.PARA_CFDI` traduce `c_PeriodicidadPago` a `PeriodicidadTarifa`, y mapea a `None` las
periodicidades que el Anexo 8 **no** publica: `03` (catorcenal), `06` (bimestral), `07` (por
unidad de obra), `08` (comisión), `09` (precio alzado) y `99` (otra). Un recibo con cualquiera de
ellas no puede quedar mudo —una fila con todas las columnas vacías y sin ninguna bandera es peor
que una con aviso, porque nadie nota que no se calculó—, así que este informe implementa la regla
que la especificación exige (B-09.R1): se recalcula con la **tarifa mensual**, prorrateada a los
días pagados del propio recibo (`isr_del_periodo` con `DIAS_NOMINALES[MENSUAL]`, el mismo
prorrateo del art. 175 que ya usa B-09.R3 para un periodo incompleto), y se marca con
`TARIFA_PROPORCIONADA` (severidad media): la comparación sigue siendo útil, pero es orientativa,
no exacta. Si la tarifa mensual tampoco está confirmada, el recibo cae en `RECIBO_NO_CALCULABLE`
como cualquier otro que no se puede calcular.

**Esta necesidad de la mensual nunca bloquea el informe completo.** Solo las periodicidades que
los recibos usan **directamente** (las que sí traducen a una `PeriodicidadTarifa`) entran en la
verificación de bloqueo de `configuracion_isr`; la mensual de repuesto se resuelve aparte
(`configs_mensual`, más abajo) precisamente para que su ausencia degrade recibo por recibo — con
`RECIBO_NO_CALCULABLE` — y no le quite el informe entero a una empresa que nunca paga catorcenal.

Tarea 4 — las ocho banderas que separan un hallazgo del ruido
--------------------------------------------------------------
El dueño del Hub **no es contador**: estas banderas tienen que decirle qué significa el hallazgo,
no nombrar una condición. Ocho claves, siete por recibo y una de toda la corrida (§6 del diseño):

- `COINCIDE` / `DIFERENCIA_MENOR` / `DIFERENCIA_MAYOR` (B-09.R4): clasifican `Diferencia de ISR`
  contra tres umbrales — hasta 0.02 pesos es redondeo entre dos cálculos hechos por separado
  (`_UMBRAL_COINCIDE`); hasta 1.00 peso sigue siendo redondeo acumulado, no un error
  (`_UMBRAL_DIFERENCIA_MENOR`); por encima ya merece revisarse con el proveedor de nómina. Ninguno
  de los tres nombres es una cifra fiscal: son la clasificación que este informe define.
- `ISR_CERO_CON_BASE` (alta): el patrón retuvo 0.00 de ISR en un recibo cuya base gravable ya
  rebasó el tramo exento de la tarifa (su renglón calculado es el 2 o mayor). Es el hallazgo más
  grave del informe: apunta a una retención que debió calcularse y no se hizo.
- `PERIODO_IRREGULAR` (baja): el recibo pagó más o menos días que los nominales de su
  periodicidad. No es un error en sí — es contexto: cualquier diferencia de ISR de ese recibo
  puede venir del prorrateo, no del cálculo del proveedor.
- `PERCEPCIONES_EXTRAORDINARIAS` (media): el recibo trae al menos una percepción marcada
  `es_ingreso_ordinario = false` en el catálogo **confirmado** — nunca una lista de tipos escrita
  en el código. Esas percepciones (aguinaldo, PTU, prima vacacional…) no se gravan con la tarifa
  del periodo, así que la comparación de ISR de ese recibo no es concluyente.
- `PROCEDIMIENTO_ART174` (baja): alguna deducción del recibo menciona, en su texto normalizado
  (minúsculas, sin acentos), el `174` del Reglamento. Es una detección **deliberadamente laxa**:
  un falso positivo solo rotula un recibo como no concluyente (el lado barato del error); un falso
  negativo —un proveedor que no nombra el artículo— queda cubierto por `DIFERENCIA_SISTEMATICA`,
  que no depende del texto. Que una deducción diga solo "ISR" no la dispara: hace falta el `174`.
- `DIFERENCIA_SISTEMATICA` (alta): la única bandera de la **corrida completa**, no de una fila.
  Exige al menos tres empleados distintos con `Diferencia de ISR` comparable, y que **todos**
  difieran en más de un peso y del mismo signo. Con uno o dos empleados "todos difieren igual" es
  trivialmente cierto y la bandera sería ruido; con tres o más, una diferencia pareja deja de
  parecer una coincidencia y empieza a apuntar a otro procedimiento (el propio art. 174, por
  ejemplo) o a una tarifa mal cargada, no a errores sueltos de cada recibo.

**Ningún importe fiscal literal vive en este archivo** (§2.12): la tarifa, la UMA mensual y los
parámetros del subsidio salen de `app.informes.configuracion_isr`, resueltos por fecha y
confirmados. **Todo redondeo a dos decimales con `ROUND_HALF_UP`**, igual que
`app.services.tarifa_isr`.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import configuracion_isr, universo_nomina
from app.informes.base import Bandera, Columna, ResultadoInforme, Severidad
from app.informes.configuracion_isr import ConfiguracionIsr
from app.informes.identidades_b00 import CLAVE_TIPO_DEDUCCION_ISR
from app.models.empresa import Empresa
from app.models.enums import PeriodicidadTarifa
from app.models.nomina import NominaDeduccion, NominaOtroPago, NominaPercepcion
from app.services import tarifa_isr

CLAVE = "B-09"
NOMBRE = "Recálculo de ISR y subsidio al empleo"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por recibo, con el ISR recalculado contra la tarifa que el SAT publica en el "
    "Anexo 8 y puesto al lado del que el patrón timbró. Compara contra la tarifa publicada; no "
    "dictamina — una diferencia puede venir del subsidio, de un periodo irregular o de otro "
    "procedimiento legal (art. 174 del Reglamento)."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Todo el grupo B declara `("N",)`: ver el docstring homónimo de `b02_conceptos_patron`."""

_DOS_DECIMALES = Decimal("0.01")

_CLAVE_OTRO_PAGO_SUBSIDIO = "002"
"""Clave de `c_TipoOtroPago` del "Subsidio para el empleo". Mismo valor y mismo criterio que
`b05_acumulado_anual._CLAVE_OTRO_PAGO_SUBSIDIO`: se declara localmente porque, a diferencia del
ISR (una identidad de B-00 con una sola clave inequívoca), esta constante no tiene todavía un
hogar compartido — no vale la pena crear uno para una constante que dos módulos ya repiten igual."""

# --------------------------------------------------------------------------------------
# Los umbrales de las banderas (tarea 4, B-09.R4 y §6 del diseño). Ninguno es un importe
# fiscal (§2.12): no sale de una tarifa ni de la ley, es la tolerancia de comparación que este
# informe define para separar el redondeo de un hallazgo real.
# --------------------------------------------------------------------------------------

_UMBRAL_COINCIDE = Decimal("0.02")
"""Hasta 2 centavos de diferencia se explica por el redondeo entre dos cálculos hechos por
separado (el nuestro y el del proveedor de nómina): `COINCIDE`."""

_UMBRAL_DIFERENCIA_MENOR = Decimal("1.00")
"""Hasta un peso completo sigue leyéndose como redondeo acumulado de varias operaciones
encadenadas, no como un error del proveedor: `DIFERENCIA_MENOR`. Por encima de este umbral,
`DIFERENCIA_MAYOR` — y es el mismo umbral que usa `DIFERENCIA_SISTEMATICA` para decidir si un
empleado "difiere" de la tarifa."""

_MIN_EMPLEADOS_DIFERENCIA_SISTEMATICA = 3
"""§6 del diseño: con uno o dos empleados, "todos difieren igual" es trivialmente cierto y
`DIFERENCIA_SISTEMATICA` sería ruido. Tres es la muestra mínima donde la coincidencia empieza a
significar algo."""

_NOTA_SIN_SUBSIDIO = (
    "Este informe se generó, pero no se pudo comparar lo que retuvo el patrón contra lo que en "
    "realidad correspondía: falta confirmar en el sistema los datos del apoyo que la ley da a los "
    "sueldos más bajos (el subsidio al empleo), y sin ellos no se puede saber cuánto debió "
    "retenerse. Por eso las columnas de comparación de este informe (Subsidio, ISR a retener "
    "teórico, Diferencia de ISR) quedaron vacías. Que este informe no traiga banderas de "
    "diferencia NO significa que las retenciones estén correctas: significa que todavía no se "
    "pudieron comparar. Confirma la UMA mensual, el factor y el tope del subsidio en "
    "Configuración → Fiscal para que la comparación empiece a funcionar."
)
"""Ronda de corrección de la tarea 4: `BANDERA_SIN_SUBSIDIO` (`configuracion_isr`) se descarta de
la lista de bloqueo (§5 del diseño: sin subsidio el informe sí se genera) pero antes no se
reintroducía en ningún lado — ni bandera, ni aviso, ni nota. Eso deja al usuario con un informe
de cero banderas de comparación (todas dependen de `isr_a_retener_teorico`, y esa columna
depende del subsidio) sin ninguna explicación, que se lee como "todo está bien" cuando la verdad
es que no se comparó nada. Va a `ResultadoInforme.notas`, no a `aviso` (que desaparece cuando la
corrida sale bien: aquí sale bien) ni a una `Bandera` (no es un hallazgo que se filtre por
recibo, es un calificador permanente de la corrida completa mientras falte confirmar)."""


def _redondear(valor: Decimal) -> Decimal:
    return valor.quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)


def _dec(valor: object) -> Decimal:
    """`func.sum` puede devolver `Decimal`, `float` o `None` según el dialecto; nunca se compara
    en binario (mismo patrón que `universo_nomina._dec`)."""
    if valor is None:
        return Decimal("0")
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango, sobre `nomina.fecha_pago` (R-T6).")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    incluir_cancelados: bool = Field(False, description="Por defecto solo vigentes (R-T1).")


@dataclass(slots=True)
class _ParametrosUniverso:
    """Adaptador local a `universo_nomina.ParametrosUniverso`. B-09 no expone `tipo_nomina`: el
    ISR se retiene también en nómina extraordinaria (aguinaldo, PTU), así que filtrar por tipo
    escondería justo los recibos que más vale comparar. Mismo patrón que
    `b03_gravado_exento._ParametrosUniverso`."""

    fecha_desde: date
    fecha_hasta: date
    incluir_cancelados: bool
    tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"


# --------------------------------------------------------------------------------------
# Las 24 columnas: los 21 renglones del documento fuente, con sus dos primeros grupos
# ("UUID / Fecha pago / Periodo", "RFC / Nombre / Núm. empleado") expandidos uno a uno —
# igual que ya hace B-03 con el mismo tipo de grupo (`b03_gravado_exento._COLUMNAS`).
# --------------------------------------------------------------------------------------

_COLUMNAS: tuple[tuple[str, str], ...] = (
    ("UUID", "texto"),
    ("Fecha pago", "fecha"),
    ("Periodo", "entero"),
    ("RFC empleado", "texto"),
    ("Nombre empleado", "texto"),
    ("Núm. empleado", "texto"),
    ("Periodicidad", "texto"),
    ("Días pagados", "decimal"),
    ("Base gravable", "monto"),
    ("Tarifa aplicada", "texto"),
    ("Renglón de la tarifa", "entero"),
    ("Límite inferior", "monto"),
    ("Excedente", "monto"),
    ("Tasa sobre excedente (%)", "decimal"),
    ("Impuesto marginal", "monto"),
    ("Cuota fija", "monto"),
    ("ISR determinado", "monto"),
    ("Subsidio al empleo teórico", "monto"),
    ("ISR a retener teórico", "monto"),
    ("Subsidio a entregar teórico", "monto"),
    ("ISR retenido en el CFDI", "monto"),
    ("Subsidio en el CFDI", "monto"),
    ("Diferencia de ISR", "monto"),
    ("Diferencia de subsidio", "monto"),
)

(
    _COL_UUID,
    _COL_FECHA_PAGO,
    _COL_PERIODO,
    _COL_RFC_EMPLEADO,
    _COL_NOMBRE_EMPLEADO,
    _COL_NUM_EMPLEADO,
    _COL_PERIODICIDAD,
    _COL_DIAS_PAGADOS,
    _COL_BASE,
    _COL_TARIFA_APLICADA,
    _COL_RENGLON,
    _COL_LIMITE_INFERIOR,
    _COL_EXCEDENTE,
    _COL_TASA,
    _COL_IMPUESTO_MARGINAL,
    _COL_CUOTA_FIJA,
    _COL_ISR_DETERMINADO,
    _COL_SUBSIDIO_TEORICO,
    _COL_ISR_A_RETENER_TEORICO,
    _COL_SUBSIDIO_A_ENTREGAR_TEORICO,
    _COL_ISR_RETENIDO_CFDI,
    _COL_SUBSIDIO_CFDI,
    _COL_DIFERENCIA_ISR,
    _COL_DIFERENCIA_SUBSIDIO,
) = range(len(_COLUMNAS))


def _columnas() -> list[Columna]:
    return [Columna(titulo=titulo, tipo=tipo) for titulo, tipo in _COLUMNAS]  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Datos de la base de datos: universo + agregados, sin N+1 (regla 11)
# --------------------------------------------------------------------------------------


async def _gravado_por_tipo(db: AsyncSession, ids: list[int]) -> dict[int, dict[str, Decimal]]:
    """Gravado por `(comprobante_id, tipo_percepcion)`, una sola consulta agregada para todo el
    universo. Mismo patrón que `b05_acumulado_anual._sumas_por_comprobante`: separar por tipo es
    lo único que permite quedarse después solo con las percepciones ordinarias — B-09 nunca usa
    el gravado total del recibo (ver el docstring del módulo)."""
    if not ids:
        return {}
    resultado: dict[int, dict[str, Decimal]] = {}
    filas = await db.execute(
        select(
            NominaPercepcion.comprobante_id,
            NominaPercepcion.tipo_percepcion,
            func.sum(NominaPercepcion.importe_gravado).label("gravado"),
        )
        .where(NominaPercepcion.comprobante_id.in_(ids))
        .group_by(NominaPercepcion.comprobante_id, NominaPercepcion.tipo_percepcion)
    )
    for comprobante_id, tipo_percepcion, gravado in filas:
        por_tipo = resultado.setdefault(int(comprobante_id), {})
        por_tipo[str(tipo_percepcion)] = _dec(gravado)
    return resultado


async def _isr_y_subsidio_cfdi(db: AsyncSession, ids: list[int]) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    """Lo que el patrón timbró: ISR retenido (`nomina_deduccion` tipo `002`) y subsidio causado
    (`nomina_otro_pago` tipo `002`, campo `subsidio_causado`), una consulta agregada por tabla
    para todo el universo (regla 11)."""
    isr: dict[int, Decimal] = {}
    subsidio: dict[int, Decimal] = {}
    if not ids:
        return isr, subsidio

    filas_isr = await db.execute(
        select(NominaDeduccion.comprobante_id, func.sum(NominaDeduccion.importe))
        .where(NominaDeduccion.comprobante_id.in_(ids), NominaDeduccion.tipo_deduccion == CLAVE_TIPO_DEDUCCION_ISR)
        .group_by(NominaDeduccion.comprobante_id)
    )
    for comprobante_id, importe in filas_isr:
        isr[int(comprobante_id)] = _redondear(_dec(importe))

    filas_subsidio = await db.execute(
        select(NominaOtroPago.comprobante_id, func.sum(NominaOtroPago.subsidio_causado))
        .where(
            NominaOtroPago.comprobante_id.in_(ids),
            NominaOtroPago.tipo_otro_pago == _CLAVE_OTRO_PAGO_SUBSIDIO,
        )
        .group_by(NominaOtroPago.comprobante_id)
    )
    for comprobante_id, importe in filas_subsidio:
        subsidio[int(comprobante_id)] = _redondear(_dec(importe))

    return isr, subsidio


async def _conceptos_deduccion(db: AsyncSession, ids: list[int]) -> dict[int, list[str]]:
    """El texto de `concepto` de cada deducción del recibo, **sin agregar**: aquí importa lo que
    dice el texto, no la suma. Una sola consulta para todo el universo (regla 11). Es la única
    consulta de este informe cuyo resultado se lee como texto libre, no como un importe — la
    necesita `PROCEDIMIENTO_ART174` (tarea 4), que busca la mención del artículo en lo que el
    proveedor de nómina escribió, no en un catálogo."""
    resultado: dict[int, list[str]] = {}
    if not ids:
        return resultado
    filas = await db.execute(
        select(NominaDeduccion.comprobante_id, NominaDeduccion.concepto).where(NominaDeduccion.comprobante_id.in_(ids))
    )
    for comprobante_id, concepto in filas:
        if concepto:
            resultado.setdefault(int(comprobante_id), []).append(concepto)
    return resultado


def _es_ordinaria(config: ConfiguracionIsr, tipo: str) -> bool:
    marca = config.marcas.get(tipo)
    return marca is not None and marca.es_ingreso_ordinario


def _base_ordinaria(config: ConfiguracionIsr, por_tipo: dict[str, Decimal]) -> Decimal:
    """B-09: `Σ importe_gravado` de los tipos ordinarios de este recibo. Nunca el gravado total
    (ver el docstring del módulo)."""
    return _redondear(sum((importe for tipo, importe in por_tipo.items() if _es_ordinaria(config, tipo)), Decimal("0")))


def _normalizar_texto(texto: str) -> str:
    """Minúsculas y sin acentos (mismo patrón que `app.services.anexo8._sin_acentos` y
    `b06_centro_costo`), para que "ISR Art. 174 ajuste" y "isr art 174 ajuste" casen igual al
    buscar la mención del artículo 174 (`PROCEDIMIENTO_ART174`, tarea 4)."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return sin_acentos.lower()


def _clasificar_diferencia(diferencia: Decimal) -> str:
    """B-09.R4: los tres umbrales de comparación de `Diferencia de ISR`. Ninguno de los tres
    nombres es una cifra fiscal — es la clasificación que este informe define (ver
    `_UMBRAL_COINCIDE` y `_UMBRAL_DIFERENCIA_MENOR`)."""
    absoluta = abs(diferencia)
    if absoluta <= _UMBRAL_COINCIDE:
        return "COINCIDE"
    if absoluta <= _UMBRAL_DIFERENCIA_MENOR:
        return "DIFERENCIA_MENOR"
    return "DIFERENCIA_MAYOR"


def _bandera_diferencia_sistematica(datos: list[tuple[str, Decimal]]) -> Bandera | None:
    """`DIFERENCIA_SISTEMATICA` (§6 del diseño): la única bandera de la **corrida completa**, no
    de una fila — por eso vive fuera del ciclo de recibos, y por eso su `ambito` es `"informe"`
    en vez de un UUID.

    Exige **al menos tres empleados distintos** (`_MIN_EMPLEADOS_DIFERENCIA_SISTEMATICA`) con
    `Diferencia de ISR` comparable, y que **todos** difieran en más de un peso
    (`_UMBRAL_DIFERENCIA_MENOR`, el mismo umbral de `DIFERENCIA_MAYOR`) y del mismo signo. Con uno
    o dos empleados "todos difieren igual" es trivialmente cierto y la bandera sería ruido; con
    tres o más, una diferencia pareja deja de leerse como una coincidencia y empieza a apuntar a
    otro procedimiento (el propio art. 174, por ejemplo) o a una tarifa mal cargada — no a errores
    sueltos de cada recibo."""
    empleados_distintos = {num_empleado for num_empleado, _diferencia in datos}
    if len(empleados_distintos) < _MIN_EMPLEADOS_DIFERENCIA_SISTEMATICA:
        return None
    if not all(abs(diferencia) > _UMBRAL_DIFERENCIA_MENOR for _num_empleado, diferencia in datos):
        return None
    signos = {1 if diferencia > 0 else -1 for _num_empleado, diferencia in datos}
    if len(signos) != 1:
        return None
    sentido = "por encima" if signos == {1} else "por debajo"
    return Bandera(
        clave="DIFERENCIA_SISTEMATICA",
        severidad="alta",
        ambito="informe",
        mensaje=(
            f"Los {len(empleados_distintos)} empleados de esta corrida con ISR comparable "
            f"difieren de la tarifa en el mismo sentido: todos {sentido} de lo que retuvo el "
            "patrón. Esto no se ve como errores sueltos de cada recibo, sino como el proveedor "
            "de nómina usando otro procedimiento (por ejemplo el del art. 174) o una tarifa mal "
            "cargada — vale la pena confirmarlo con el proveedor antes de revisar recibos uno "
            "por uno."
        ),
    )


# --------------------------------------------------------------------------------------
# La consulta
# --------------------------------------------------------------------------------------


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=_columnas(), aviso="La empresa no existe.")

    p_universo = _ParametrosUniverso(p.fecha_desde, p.fecha_hasta, p.incluir_cancelados)
    filas_universo = list((await db.execute(universo_nomina.universo(empresa_id, rfc_empresa, p_universo))).all())
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, rfc_empresa, p_universo)

    if not filas_universo:
        return ResultadoInforme(
            columnas=_columnas(), banderas=banderas_fuera, aviso="Sin CFDI de nómina en el rango solicitado."
        )

    ids = [fila[0].comprobante_id for fila in filas_universo]
    gravado_por_tipo = await _gravado_por_tipo(db, ids)
    isr_cfdi_por_comprobante, subsidio_cfdi_por_comprobante = await _isr_y_subsidio_cfdi(db, ids)
    conceptos_deduccion_por_comprobante = await _conceptos_deduccion(db, ids)

    # Lo que hace falta resolver en `configuracion_isr`: las periodicidades traducidas (la
    # traducción con `PARA_CFDI` es de este informe, porque es quien lee los recibos) y los
    # tipos de percepción que de verdad aparecen — nunca las 44 claves del catálogo completo.
    periodicidades_presentes: set[PeriodicidadTarifa] = set()
    necesita_fallback_mensual = False
    fecha_representativa_por_ejercicio: dict[int, date] = {}
    for _comprobante, nomina, receptor, _totales, _detalle in filas_universo:
        if nomina.fecha_pago is not None:
            ejercicio = nomina.fecha_pago.year
            actual = fecha_representativa_por_ejercicio.get(ejercicio)
            if actual is None or nomina.fecha_pago > actual:
                fecha_representativa_por_ejercicio[ejercicio] = nomina.fecha_pago
        codigo = receptor.periodicidad_pago if receptor is not None else None
        if codigo is not None:
            traducida = tarifa_isr.PARA_CFDI.get(codigo)
            if traducida is not None:
                periodicidades_presentes.add(traducida)
            else:
                # B-09.R1: el Anexo 8 no publica tarifa para esta periodicidad (catorcenal,
                # bimestral, por obra, comisión, precio alzado u "otra"). No entra en el
                # bloqueo global — sería exigir una tarifa que casi ninguna empresa necesita
                # confirmar—; se resuelve aparte (`configs_mensual`) y degrada por recibo.
                necesita_fallback_mensual = True

    tipos_presentes: set[str] = {tipo for por_tipo in gravado_por_tipo.values() for tipo in por_tipo}
    periodicidades_ordenadas = sorted(periodicidades_presentes, key=lambda per: per.value)

    # Se resuelve una vez por ejercicio presente (acotado por el calendario, no por el número de
    # recibos: regla 11), con la fecha de pago más reciente de ese ejercicio como referencia para
    # los parámetros del subsidio vigentes por fecha. La tarifa no depende de la fecha dentro del
    # ejercicio, solo del ejercicio y la periodicidad.
    configs: dict[int, ConfiguracionIsr] = {}
    # La tarifa mensual de repuesto (B-09.R1) se resuelve **aparte**, en una llamada propia, y
    # solo cuando algún recibo la necesita: si se pidiera junto con `periodicidades_ordenadas`
    # en la misma llamada, su ausencia se colaría en `config.faltantes` y bloquearía el informe
    # entero por una periodicidad que la mayoría de las empresas nunca usa (ver el docstring del
    # módulo). Aquí su ausencia solo llega a `configs_mensual`, que el bloqueo de abajo no mira.
    configs_mensual: dict[int, ConfiguracionIsr] = {}
    for ejercicio, fecha in fecha_representativa_por_ejercicio.items():
        configs[ejercicio] = await configuracion_isr.resolver(
            db,
            ejercicio=ejercicio,
            en_fecha=fecha,
            periodicidades=periodicidades_ordenadas,
            tipos_presentes=tipos_presentes,
        )
        if necesita_fallback_mensual:
            configs_mensual[ejercicio] = await configuracion_isr.resolver(
                db,
                ejercicio=ejercicio,
                en_fecha=fecha,
                periodicidades=[PeriodicidadTarifa.MENSUAL],
                tipos_presentes=tipos_presentes,
            )

    # La degradación es por partes (§5 del diseño): sin tarifa o sin marcas, nada se genera y el
    # aviso es literalmente el texto de `configuracion_isr` (nunca reescrito aquí). Sin subsidio
    # sí se genera — su texto (`BANDERA_SIN_SUBSIDIO`) se descarta de la lista de bloqueo, pero
    # no desaparece: se reintroduce abajo como nota (`_NOTA_SIN_SUBSIDIO`), porque sin él ninguna
    # de las banderas de comparación de la tarea 4 puede dispararse y el usuario necesita saber
    # que la ausencia de hallazgos no significa que todo esté correcto.
    bloqueantes: list[str] = []
    vistos: set[str] = set()
    sin_subsidio_confirmado = False
    for config_ejercicio in configs.values():
        if configuracion_isr.BANDERA_SIN_SUBSIDIO in config_ejercicio.faltantes:
            sin_subsidio_confirmado = True
        for falta in config_ejercicio.faltantes:
            if falta != configuracion_isr.BANDERA_SIN_SUBSIDIO and falta not in vistos:
                vistos.add(falta)
                bloqueantes.append(falta)
    if bloqueantes:
        return ResultadoInforme(columnas=_columnas(), banderas=banderas_fuera, aviso=" ".join(bloqueantes))

    notas: list[str] = [_NOTA_SIN_SUBSIDIO] if sin_subsidio_confirmado else []

    banderas: list[Bandera] = list(banderas_fuera)
    banderas.extend(universo_nomina.banderas_de_estatus(universo_nomina.comprobantes_y_detalles(filas_universo)))

    filas: list[list[Any]] = []
    # Insumo de `DIFERENCIA_SISTEMATICA` (§6 del diseño): un par (empleado, diferencia) por cada
    # recibo cuya `Diferencia de ISR` sí se pudo calcular. Se evalúa después del ciclo porque es
    # la única bandera de la corrida completa, no de una fila.
    datos_diferencia_sistematica: list[tuple[str, Decimal]] = []
    for comprobante, nomina, receptor, _totales, detalle in filas_universo:
        cid = comprobante.comprobante_id
        fecha_pago = nomina.fecha_pago
        periodo = fecha_pago.month if fecha_pago is not None else None
        ejercicio = fecha_pago.year if fecha_pago is not None else None
        config = configs.get(ejercicio) if ejercicio is not None else None
        config_mensual = configs_mensual.get(ejercicio) if ejercicio is not None else None
        codigo = receptor.periodicidad_pago if receptor is not None else None
        dias_pagados = nomina.num_dias_pagados

        base = _base_ordinaria(config, gravado_por_tipo.get(cid, {})) if config is not None else Decimal("0.00")

        renglon: int | None = None
        limite_inferior: Decimal | None = None
        excedente: Decimal | None = None
        tasa: Decimal | None = None
        impuesto_marginal: Decimal | None = None
        cuota_fija: Decimal | None = None
        isr_determinado: Decimal | None = None
        subsidio_teorico: Decimal | None = None
        isr_a_retener_teorico: Decimal | None = None
        subsidio_a_entregar_teorico: Decimal | None = None
        tarifa_aplicada: str | None = None

        if receptor is None or dias_pagados is None or codigo is None:
            # Faltan datos del propio CFDI (no de configuración): el nodo del receptor, sus
            # días pagados o su periodicidad de pago. Mismo tratamiento que el resto de los
            # huecos de esta sección — el recibo no desaparece, se marca.
            banderas.append(
                Bandera(
                    clave="RECIBO_NO_CALCULABLE",
                    severidad="alta",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=(
                        "Este recibo no trae uno de los datos que el recálculo necesita del "
                        "propio CFDI (el nodo del receptor, sus días pagados o su periodicidad "
                        "de pago), así que no se pudo calcular su ISR."
                    ),
                )
            )
        else:
            periodicidad_tarifa = tarifa_isr.PARA_CFDI.get(codigo)
            proporcionada = periodicidad_tarifa is None
            periodicidad_efectiva = PeriodicidadTarifa.MENSUAL if periodicidad_tarifa is None else periodicidad_tarifa
            if proporcionada:
                # B-09.R1: el Anexo 8 no publica tarifa para esta periodicidad — se recalcula
                # con la mensual, prorrateada a los días pagados del propio recibo.
                renglones = (
                    config_mensual.tarifas.get(PeriodicidadTarifa.MENSUAL, ())
                    if config_mensual is not None
                    else ()
                )
            else:
                renglones = config.tarifas.get(periodicidad_efectiva, ()) if config is not None else ()
            dias_nominales = tarifa_isr.DIAS_NOMINALES.get(periodicidad_efectiva)

            if dias_nominales is not None and renglones:
                tarifa_aplicada = (
                    f"{ejercicio} · {tarifa_isr.ETIQUETAS_TARIFA[periodicidad_efectiva]} (proporcionada)"
                    if proporcionada
                    else f"{ejercicio} · {tarifa_isr.ETIQUETAS_TARIFA[periodicidad_efectiva]}"
                )
                try:
                    # `isr_del_periodo` se llama primero: si `dias_pagados` es cero o negativo
                    # lanza aquí, antes de que la elevación de la base de abajo pudiera dividir
                    # entre cero por su cuenta.
                    isr_determinado = tarifa_isr.isr_del_periodo(renglones, base, dias_pagados, dias_nominales)
                    base_para_renglon = (
                        base if dias_pagados == dias_nominales else _redondear(base * dias_nominales / dias_pagados)
                    )
                    r = tarifa_isr.renglon_para(renglones, base_para_renglon)
                    excedente = _redondear(base_para_renglon - r.limite_inferior)
                    impuesto_marginal = _redondear(excedente * r.tasa_excedente)
                    renglon = r.renglon
                    limite_inferior = r.limite_inferior
                    # `a_porcentaje`, no la fracción cruda de la columna: es el único número de
                    # la tarifa donde una escala equivocada cambia el resultado, y es exactamente
                    # para esto que Task 1 construyó el helper — las otras dos pantallas que
                    # muestran una tasa (`app.api.v1.configuracion`,
                    # `app.services.revision_tarifa`) ya lo usan; el dueño del Hub no es contador
                    # y no debe leer `0.1088` donde el resto del sistema muestra `10.88`.
                    tasa = tarifa_isr.a_porcentaje(r.tasa_excedente)
                    cuota_fija = r.cuota_fija

                    if dias_pagados != dias_nominales:
                        # El recibo cubrió más o menos días que los nominales de su
                        # periodicidad: hubo prorrateo (art. 175 del Reglamento). No es un
                        # error en sí — es contexto para leer cualquier diferencia de ISR de
                        # este mismo recibo (§6 del diseño).
                        banderas.append(
                            Bandera(
                                clave="PERIODO_IRREGULAR",
                                severidad="baja",
                                ambito=f"uuid:{comprobante.uuid}",
                                mensaje=(
                                    f"Este recibo pagó {dias_pagados} días, distintos de los "
                                    f"{dias_nominales} días normales de su periodicidad: hubo un "
                                    "prorrateo, así que si el ISR retenido difiere del que marca "
                                    "la tarifa, la causa puede ser ese prorrateo y no un error del "
                                    "proveedor de nómina."
                                ),
                            )
                        )

                    if config is not None and config.hay_subsidio:
                        uma_mensual = config.uma_mensual
                        factor_subsidio = config.factor_subsidio
                        tope_subsidio = config.tope_subsidio
                        assert uma_mensual is not None
                        assert factor_subsidio is not None
                        assert tope_subsidio is not None
                        subsidio_teorico = tarifa_isr.subsidio_del_periodo(
                            base, dias_pagados, uma_mensual, factor_subsidio, tope_subsidio
                        )
                        isr_a_retener_teorico = tarifa_isr.isr_a_retener(isr_determinado, subsidio_teorico)
                        subsidio_a_entregar_teorico = tarifa_isr.subsidio_a_entregar(isr_determinado, subsidio_teorico)

                    if proporcionada:
                        banderas.append(
                            Bandera(
                                clave="TARIFA_PROPORCIONADA",
                                severidad="media",
                                ambito=f"uuid:{comprobante.uuid}",
                                mensaje=(
                                    f"El Anexo 8 de la RMF no publica una tarifa para la periodicidad de pago "
                                    f"`{codigo}` de este recibo (catorcenal, bimestral, por unidad de obra, "
                                    "comisión, precio alzado u otra), así que se usó la tarifa mensual "
                                    "repartida entre los días pagados (mismo prorrateo del art. 175 del "
                                    "Reglamento que B-09.R3 usa para un periodo incompleto). La comparación "
                                    "con lo timbrado es orientativa, no exacta."
                                ),
                            )
                        )
                except tarifa_isr.TarifaInvalida as exc:
                    renglon = limite_inferior = excedente = tasa = impuesto_marginal = cuota_fija = None
                    isr_determinado = None
                    subsidio_teorico = isr_a_retener_teorico = subsidio_a_entregar_teorico = None
                    banderas.append(
                        Bandera(
                            clave="RECIBO_NO_CALCULABLE",
                            severidad="alta",
                            ambito=f"uuid:{comprobante.uuid}",
                            mensaje=f"No se pudo recalcular el ISR de este recibo con la tarifa: {exc}",
                        )
                    )
            else:
                # Ni la tarifa propia de esta periodicidad, ni —si aplicaba— la mensual de
                # repuesto de B-09.R1, están confirmadas para este ejercicio.
                banderas.append(
                    Bandera(
                        clave="RECIBO_NO_CALCULABLE",
                        severidad="alta",
                        ambito=f"uuid:{comprobante.uuid}",
                        mensaje=(
                            "No hay tarifa confirmada para calcular el ISR de este recibo"
                            + (
                                " (la tarifa mensual de repuesto de B-09.R1 tampoco está confirmada)."
                                if proporcionada
                                else "."
                            )
                        ),
                    )
                )

        isr_cfdi = isr_cfdi_por_comprobante.get(cid, Decimal("0.00"))
        subsidio_cfdi = subsidio_cfdi_por_comprobante.get(cid, Decimal("0.00"))
        diferencia_isr = None if isr_a_retener_teorico is None else _redondear(isr_cfdi - isr_a_retener_teorico)
        diferencia_subsidio = (
            None if subsidio_a_entregar_teorico is None else _redondear(subsidio_cfdi - subsidio_a_entregar_teorico)
        )

        # -------------------------------------------------------------------------------
        # Tarea 4 — las banderas de comparación. `COINCIDE`/`DIFERENCIA_MENOR`/
        # `DIFERENCIA_MAYOR` e `ISR_CERO_CON_BASE` necesitan que el ISR se haya podido
        # calcular; las dos primeras necesitan además el subsidio confirmado (`diferencia_isr`
        # compara contra lo que de verdad se retiene, no contra el ISR determinado bruto).
        # -------------------------------------------------------------------------------
        if diferencia_isr is not None:
            clave_diferencia = _clasificar_diferencia(diferencia_isr)
            severidad_diferencia: Severidad
            if clave_diferencia == "COINCIDE":
                mensaje_diferencia = (
                    f"El ISR que retuvo el patrón coincide con el que marca la tarifa (diferencia "
                    f"de {diferencia_isr} pesos, dentro de la tolerancia de redondeo): este recibo "
                    "no necesita revisión."
                )
                severidad_diferencia = "baja"
            elif clave_diferencia == "DIFERENCIA_MENOR":
                mensaje_diferencia = (
                    f"El ISR retenido difiere del que marca la tarifa por {diferencia_isr} pesos: "
                    "una diferencia de hasta un peso se explica por el redondeo acumulado entre "
                    "dos cálculos hechos por separado, no por un error del proveedor de nómina."
                )
                severidad_diferencia = "baja"
            else:
                mensaje_diferencia = (
                    f"El ISR retenido difiere del que marca la tarifa por {diferencia_isr} pesos, "
                    "más de lo que explica el redondeo: vale la pena confirmarlo con el proveedor "
                    "de nómina."
                )
                severidad_diferencia = "alta"
            banderas.append(
                Bandera(
                    clave=clave_diferencia,
                    severidad=severidad_diferencia,
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=mensaje_diferencia,
                )
            )
            num_empleado_actual = receptor.num_empleado if receptor is not None else None
            if num_empleado_actual is not None:
                datos_diferencia_sistematica.append((num_empleado_actual, diferencia_isr))

        if renglon is not None and renglon >= 2 and isr_cfdi == Decimal("0.00"):
            # El caso más grave del informe (§6 del diseño): la base ya rebasó el tramo exento
            # de la tarifa (por eso cayó en el renglón 2 o uno mayor), pero el patrón timbró
            # 0.00 de ISR retenido. No es una diferencia de centavos: es una retención que
            # debió calcularse y no se hizo.
            banderas.append(
                Bandera(
                    clave="ISR_CERO_CON_BASE",
                    severidad="alta",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=(
                        "El patrón no retuvo ISR en este recibo (0.00), pero la base gravable ya "
                        "rebasó el tramo exento de la tarifa: es el hallazgo más grave del "
                        "informe, porque apunta a una retención que debió calcularse y no se hizo."
                    ),
                )
            )

        if config is not None and any(
            not _es_ordinaria(config, tipo) for tipo in gravado_por_tipo.get(cid, {})
        ):
            # Sale del dato confirmado (`es_ingreso_ordinario` en el catálogo), nunca de una
            # lista de tipos escrita en el código (§6 del diseño): un aguinaldo, una PTU o una
            # prima vacacional no se gravan con la tarifa del periodo, así que compararlos
            # contra ella no prueba nada.
            banderas.append(
                Bandera(
                    clave="PERCEPCIONES_EXTRAORDINARIAS",
                    severidad="media",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=(
                        "Este recibo incluye una percepción que el catálogo confirmado marca "
                        "como NO ordinaria (por ejemplo aguinaldo, PTU o prima vacacional): esas "
                        "percepciones no se gravan con la tarifa del periodo, así que la "
                        "comparación de ISR de este recibo no es concluyente."
                    ),
                )
            )

        if any("174" in _normalizar_texto(concepto) for concepto in conceptos_deduccion_por_comprobante.get(cid, [])):
            # Detección deliberadamente laxa (§6 del diseño): busca el "174" en el concepto de
            # cualquier deducción, normalizado. Un falso positivo solo rotula el recibo como no
            # concluyente —el lado barato del error—; un falso negativo (un proveedor que no
            # nombra el artículo) queda cubierto por `DIFERENCIA_SISTEMATICA`, que no depende
            # del texto. Que una deducción diga solo "ISR" no la dispara: hace falta el "174".
            banderas.append(
                Bandera(
                    clave="PROCEDIMIENTO_ART174",
                    severidad="baja",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=(
                        "Una deducción de este recibo menciona el artículo 174 del Reglamento de "
                        "la LISR (ingreso mensual estimado con ajuste posterior): es un "
                        "procedimiento legítimo distinto del que este informe reproduce, así que "
                        "la comparación de ISR de este recibo no es concluyente."
                    ),
                )
            )

        filas.append(
            [
                comprobante.uuid,
                fecha_pago,
                periodo,
                comprobante.rfc_receptor,
                detalle.nombre_receptor if detalle is not None else None,
                receptor.num_empleado if receptor is not None else None,
                codigo,
                dias_pagados,
                base,
                tarifa_aplicada,
                renglon,
                limite_inferior,
                excedente,
                tasa,
                impuesto_marginal,
                cuota_fija,
                isr_determinado,
                subsidio_teorico,
                isr_a_retener_teorico,
                subsidio_a_entregar_teorico,
                isr_cfdi,
                subsidio_cfdi,
                diferencia_isr,
                diferencia_subsidio,
            ]
        )

    bandera_sistematica = _bandera_diferencia_sistematica(datos_diferencia_sistematica)
    if bandera_sistematica is not None:
        banderas.append(bandera_sistematica)

    return ResultadoInforme(columnas=_columnas(), filas=filas, banderas=banderas, notas=notas)
