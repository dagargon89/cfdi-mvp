"""B-10 · Validación de datos del receptor (§B-10 del documento fuente).

**El propósito, y por qué este informe importa aunque no lleve un solo importe.** Audita la
calidad de los datos del trabajador timbrados en el complemento de nómina: RFC, CURP, NSS,
cuenta bancaria, fechas de relación laboral, SBC y SDI. Los errores que detecta generan
requerimientos del SAT y problemas de acreditación ante el IMSS, y son **invisibles en los
informes de importes**: los otros cinco informes del grupo B (B-01, B-02, B-04, B-05, B-07)
pueden cuadrar perfectamente con un NSS mal capturado o una CURP que no corresponde al RFC,
porque ninguno de ellos mira esos campos, solo los importes.

**Grano: una fila por hallazgo, `(rfc_receptor, clave_validación)`.** Es el formato
accionable: cada fila es algo que corregir. Se descartó a propósito el formato pivotado (una
columna por validación, una fila por empleado) que también ofrece la ficha B-10: expondría
un parámetro sin efecto (`severidad_minima` no tendría nada que filtrar de forma limpia en un
pivote) y está fuera del alcance declarado de esta tarea.

**Las 23 validaciones en alcance, en cinco grupos con dificultad propia:**

1. **Estructura** (`app.informes.validadores`, puro, sin BD): RFC, CURP, NSS y cuenta
   bancaria por expresión regular y dígito verificador.
2. **De conjunto** (`CURP_DUPLICADA`, `RFC_DUPLICADO`, `NSS_DUPLICADO`): no se ven mirando un
   CFDI aislado, hay que cruzar **todos** los comprobantes del rango, no solo el más reciente
   de cada empleado.
3. **Entre periodos** (`DATOS_CAMBIANTES`): un mismo RFC con distinto NSS o distinta fecha de
   inicio de relación laboral en quincenas distintas — error de captura que solo aparece
   comparando periodos. **La CURP quedó fuera de esta validación** en la revisión final: ese
   caso exacto ("un RFC con más de una CURP") ya lo reporta `RFC_DUPLICADO` con la misma
   severidad alta, y en un informe cuyo grano es "una fila = algo que corregir" dos claves para
   un mismo defecto producen dos filas para una sola corrección. Ver
   `_hallazgos_de_conjunto`/`_hallazgos_entre_periodos`.
4. **Derivadas de importes** (`SDI_MENOR_SD_IMPLICITO`): el SDI declarado contra el sueldo
   diario que se deduce del propio CFDI (`Σ percepción '001' / días pagados`).
5. **Dependientes de la configuración fiscal** (`SBC_SOBRE_TOPE`, `SBC_BAJO_MINIMO`): las dos
   que la fase 2 dejó fuera de alcance por falta de `param_fiscal`. Ver el bloque siguiente.

Las dos validaciones de SBC y el conteo variable
--------------------------------------------------
- **`SBC_SOBRE_TOPE`** (media): `salario_base_cot_apor > 25 × UMA_DIARIA` **vigente a la fecha
  de pago**. El límite superior de cotización del artículo 28 de la Ley del Seguro Social. Es
  media y no alta porque un SBC sobre el tope no daña al trabajador: sobrestima la cuota, y el
  IMSS la recorta al tope de todos modos.
- **`SBC_BAJO_MINIMO`** (alta): `salario_base_cot_apor < salario_minimo_de_empresa(...)`. Un SBC
  por debajo del mínimo es incumplimiento directo y deja al trabajador con prestaciones
  subvaluadas.

**El SBC solo se compara si es positivo.** Con `sbc <= 0` ninguna de las dos corre: un SBC en
cero no está "por debajo del mínimo", es una base ausente, y `SBC_CERO` ya nombra ese defecto
donde sí lo es (`tipo_regimen='02'`). Sin esta regla, cada asimilado a salarios —que legítimamente
no cotiza— saldría con un hallazgo de severidad alta por cada corrida.

**Nada de heurísticas para la zona salarial.** El CFDI no dice en qué zona está el trabajador y
**no se infiere del código postal ni del domicilio**: sale de `configuracion_empresa.zona_salarial`,
que nace nula a propósito, y `salario_minimo_de_empresa` devuelve `None` **sin mirar los valores**
cuando no está configurada. El mínimo de la Zona Libre de la Frontera Norte y el general se llevan
casi un 40%, así que suponer el general produciría **falsos negativos** en una validación de
cumplimiento: empleados por debajo del mínimo que nadie detecta. Cuando falta el dato, la
validación **no se evalúa** y se emite una bandera que dice cuál falta, distinguiendo los tres
estados igual que B-03 —confirmado calcula; propuesto sin confirmar lleva su procedencia
(`UMA_SIN_CONFIRMAR`); ausente dice qué capturar (`FALTA_UMA`, `FALTA_ZONA_SALARIAL`,
`FALTA_SALARIO_MINIMO`)—. **Una bandera por causa, con el número de empleados afectados, nunca
una por empleado.**

**Y el conteo `VALIDACIONES_EJECUTADAS` lo refleja: una validación que no corre no se cuenta.**
Por eso el número **es variable** desde la fase 3, y no un invariante del módulo: con la
configuración fiscal ausente —que es el estado de la instalación real hoy, 5 parámetros y 44
marcas sin confirmar— un empleado con todos sus campos ejecuta 15 validaciones, y con la UMA y la
zona configuradas ejecuta 17. Un conteo que dijera "ejecuté 21" habiendo ejecutado 19 sería peor
que no tenerlo: convertiría la bandera que existe para hacer auditable al informe en una
afirmación falsa. Ver `VALIDACIONES_POR_EMPLEADO_COMPLETO` y `VALIDACIONES_QUE_EXIGEN_CONFIGURACION`.

**B-10.R1 — SBC y SDI son conceptos distintos, y hay que respetarlo.** El SBC es la base de
cotización ante el IMSS (topada a 25 UMA); el SDI es el salario diario integrado de los
artículos 84 y 89 de la LFT, base de indemnizaciones. Un SDI **inferior** al SBC es
teóricamente posible aunque infrecuente (los conceptos usan bases distintas), así que
`SDI_MENOR_SBC` es severidad **media**, no un error absoluto como `SBC_CERO` o `SDI_CERO`.

**Reglas de aplicabilidad — cuándo una validación se omite (no cuándo se relaja).** Las 23
validaciones son en principio independientes entre sí, pero varias necesitan un dato que
puede faltar, y comparar contra `None` no está definido. Se omiten (no se marcan, ni en un
sentido ni en el otro) en estos casos, todos documentados aquí para que ninguno sea un olvido:

- **Comparaciones numéricas** (`SBC_CERO`, `SDI_CERO`, `SDI_MENOR_SBC`,
  `SDI_MENOR_SD_IMPLICITO`): se omiten si falta el operando (`sbc`/`sdi`/`num_dias_pagados`
  en `None`, o días pagados `<= 0` para el implícito, que dividiría por cero). Un campo
  ausente no satisface ninguna comparación numérica definida; no se interpreta "ausente"
  como "cero" porque la ficha no lo pide y esa interpretación no distinguiría un dato que
  falta de un dato que de verdad es cero.
- **`FECHA_INICIO_POSTERIOR` y `ANTIGUEDAD_INCONSISTENTE`**: se omiten si falta cualquiera de
  las dos fechas que comparan (o, para la segunda, si falta `@Antigüedad`).
- **`CURP_ENTIDAD`** se omite si la CURP ya falló `CURP_ESTRUCTURA`: sin la forma general
  correcta, las posiciones 12-13 no son fiables y marcar el mismo defecto dos veces con dos
  claves distintas no añade información, solo ruido.
- **`NSS_DIGITO_VERIFICADOR`** se omite si el NSS no tiene longitud 11: el cálculo de Luhn
  sobre una cadena de longitud incorrecta no es significativo, y `NSS_LONGITUD` ya señala ese
  defecto.
- **`NSS_LONGITUD`, `NSS_DIGITO_VERIFICADOR` y `CUENTA_INVALIDA`** se omiten cuando el campo
  está **vacío** (no solo mal formado). Es una decisión de diseño explícita, no forzada por
  ninguna prueba de la tarea: la ficha declara `NSS_FALTANTE` condicionado a
  `tipo_regimen='02'` (no incondicional), lo que implica que un NSS vacío bajo otro régimen
  (asimilados a salarios, por ejemplo) es un estado legítimo, no un defecto — y evaluar
  longitud o dígito verificador sobre un campo que se espera vacío sería puro ruido en el
  caso más común. `BANCO_SIN_CUENTA` cumple el mismo papel para la cuenta bancaria: un
  empleado sin banco registrado y sin cuenta (pagado en efectivo) no tiene nada que corregir;
  `CUENTA_INVALIDA` solo tiene sentido sobre una cuenta que sí se capturó. **Esta decisión se
  reporta explícitamente como duda** al cierre de la tarea, por si el criterio real de la
  empresa fuera distinto.
- **`RFC_CURP_INCONSISTENTE`** se omite si la CURP es `None` (la ausencia ya la cubre
  `CURP_ESTRUCTURA`, que sí se evalúa siempre porque la CURP es obligatoria en el complemento
  de nómina y el RFC nunca es `NULL` en el esquema).
- **`SBC_SOBRE_TOPE` y `SBC_BAJO_MINIMO`** se omiten con `sbc` ausente o no positivo (arriba) y,
  cada una por separado, cuando falta el valor de configuración que necesita: la UMA diaria
  vigente a la fecha de pago para la primera, la zona salarial de la empresa o el mínimo
  confirmado de esa zona para la segunda. La omisión **siempre** deja bandera.
- **`CURP_DUPLICADA`, `RFC_DUPLICADO`, `NSS_DUPLICADO` y `DATOS_CAMBIANTES`** ignoran los
  valores vacíos: un CURP o NSS vacío compartido por varios RFC no es una duplicidad real de
  identidad, es ausencia de dato en varios lados a la vez, y ya la señalan otras reglas.

**Identidad del empleado: `comprobante_detalle.nombre_receptor`.** B-01/B-02 usaban
`comprobante.razon_social_emisor` para la columna "Nombre empleado" a falta de otra fuente en su
momento; B-04 señaló que ese dato es la razón social del **emisor** (el patrón), no del empleado,
y B-05/B-07/B-10 usaron desde el principio el campo correcto. La revisión final de la fase 2
corrigió también B-01 y B-02, así que los seis informes del grupo B usan hoy el mismo campo.

**Validaciones por empleado (grupos 1 y 4): la ÚLTIMA fotografía, no todas.** El brief lo
pide explícito ("trae el último `nomina_receptor` por `rfc_receptor`"): para RFC, CURP, NSS,
SBC, SDI, fechas y el SDI implícito se usa el comprobante con `fecha_pago` más reciente de
cada empleado en el rango — mismo criterio de "última fotografía" que B-04/B-05/B-07 (el
universo viene ordenado ascendente por `fecha_pago`, así que sobrescribir en el orden de
iteración deja la más reciente). Las validaciones de **conjunto** y **entre periodos**
(grupos 2 y 3) sí recorren todos los comprobantes del rango, porque su propósito es
precisamente comparar entre ellos.

**Banderas del informe: las del universo compartido y el conteo de validaciones.** Este informe
no emite banderas del propio hallazgo (los hallazgos SON las filas: cada uno ya lleva su
severidad y su descripción), pero sí emite `VALIDACIONES_EJECUTADAS` (baja, ámbito `informe`):
**cuántas validaciones se corrieron de verdad** en la corrida. Es el equivalente del `cotejos`
de `identidades_b00.verificar` que exige el §13 del diseño, y existe por la misma razón: una
validación que no corre no puede fallar, así que una hoja `Datos` vacía no distingue "los datos
están bien" de "no se validó nada" — y una prueba que asevera `filas == []` pasa **más fácil**
cuando alguien borra una comprobación. Con el conteo a la vista, borrarla rompe la suite. Ver
`VALIDACIONES_IMPLEMENTADAS` y las tres constantes que la acompañan. También hereda
`SIN_NORMALIZAR`/`COMPLEMENTO_AUSENTE`
(`universo_nomina.banderas_de_no_normalizables`), porque un CFDI que el ETL no pudo
normalizar tampoco puede auditarse. No se incluyen `ESTATUS_NO_VERIFICADO`/
`COMPROBANTE_CANCELADO`/`DATOS_DE_CORRIDA_ANTERIOR` (`universo_nomina.banderas_de_estatus`):
esas describen el estatus del CFDI ante el SAT, un eje distinto de la calidad de los datos
del receptor que este informe audita, y ya las cubre B-02 para quien necesite esa dimensión.

**Cero N+1 (regla 11).** El universo se trae con una sola consulta
(`universo_nomina.universo`, con `tipo_nomina` fijo en `AMBOS`: la calidad de los datos del
receptor no depende de si la nómina es ordinaria o extraordinaria, y filtrar produciría
"últimas fotografías" incompletas). Las percepciones `'001'` para `SDI_MENOR_SD_IMPLICITO` se
suman con una segunda consulta agregada, sobre los comprobantes de la última fotografía de
cada empleado únicamente (no sobre todo el universo). La configuración fiscal se resuelve **por
fecha de pago distinta**, no por empleado (mismo patrón que `b03_gravado_exento._configuracion`):
los empleados de una empresa comparten calendario de nómina, así que el número de consultas queda
acotado por las quincenas del rango y no por la plantilla. Ninguna consulta se hace por empleado.

**Este informe es el que más datos personales expone del catálogo** (CURP, NSS y cuenta
bancaria son literalmente el objeto de las validaciones), así que `CURP` y `NSS` se declaran
`sensible=True` (spec §8); el motor de informes (`app.informes.excel.escribir_libro`) es
quien enmascara, esta consulta solo declara.

**Y ningún mensaje de hallazgo repite el dato personal** (corrección de la revisión final, el
defecto más grave que encontró). La columna "Descripción del hallazgo" **no** es sensible y no
puede serlo —enmascararla dejaría el mensaje ilegible—, así que interpolar la CURP o el NSS en
el texto los sacaba en claro en el Excel aunque las columnas `CURP`/`NSS` salieran enmascaradas:
6 de 7 filas filtraban con el default `enmascarar_datos_personales=True`. Los mensajes describen
el defecto y, cuando ayuda a accionarlo, nombran los **RFC** implicados (el RFC no es un dato
enmascarado en este informe: sale completo en su propia columna). `app.informes.validadores.dato_personal_en_texto`
audita esta regla desde fuera, y la usan tanto `tests/test_informe_b10.py` como
`scripts/verificar_informes.py`.

**`Decimal` de punta a punta; sin `round()` ni `quantize()`** (el redondeo lo hace
`app.informes.excel` al escribir la celda)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import universo_nomina, validadores as v
from app.informes.base import Bandera, Columna, ResultadoInforme, Severidad
from app.models.empresa import Empresa
from app.models.nomina import NominaPercepcion
from app.services import configuracion_fiscal as cfg

CLAVE = "B-10"
NOMBRE = "Validación de datos del receptor"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por hallazgo (empleado, validación). Audita la calidad de los datos del "
    "trabajador timbrados en el complemento de nómina — RFC, CURP, NSS, cuenta bancaria, "
    "fechas y SBC/SDI —, errores que generan requerimientos del SAT y problemas de "
    "acreditación ante el IMSS y que los informes de importes no pueden ver."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Ver la constante homónima de `app.informes.b02_conceptos_patron`: mismo razonamiento
(todo el grupo B declara `("N",)`) y mismo consumidor (el pre-vuelo del ETL en
`app.worker.tasks._generar_informe_async`)."""

_TOLERANCIA_SDI_SBC = Decimal("0.8")
"""`SDI_MENOR_SBC` (B-10.R1, media): el SDI se considera anómalamente bajo frente al SBC solo
por debajo del 80% de este — un SDI algo menor que el SBC es teóricamente normal (bases
distintas, ver docstring del módulo); muy por debajo ya es sospechoso de captura."""

_TOLERANCIA_ANTIGUEDAD_DIAS = 14
"""Dos semanas: absorbe la aproximación de `validadores.antiguedad_iso_a_dias` (años de 365
días, meses de 30) frente al cálculo exacto por fecha."""

_ORDEN_SEVERIDAD: dict[Severidad, int] = {"alta": 0, "media": 1, "baja": 2}
"""Orden de clasificación de filas (alta, media, baja) y de filtrado por `severidad_minima`:
a menor número, más severa."""

_FACTOR_TOPE_SBC = Decimal(25)
"""`SBC_SOBRE_TOPE`: el límite superior de cotización del artículo 28 de la Ley del Seguro
Social, "veinticinco veces" la UMA diaria.

**No es un importe fiscal codificado** (§2.12): es el multiplicador que fija el texto del
artículo, no una cifra en pesos. El importe —la UMA— sale de `param_fiscal` resuelto por
vigencia, que es lo que el §2.12 protege; poner el 25 en la tabla no ganaría nada y obligaría a
que una validación de cumplimiento dependiera de un renglón más por capturar. Mismo criterio que
el `_CIEN` de la escala 0-100 en `b03_gravado_exento`."""

VALIDACIONES_IMPLEMENTADAS = 23
"""Las 23 validaciones en alcance (ver el docstring del módulo): 19 por empleado, 3 de
conjunto y 1 entre periodos."""

VALIDACIONES_POR_EMPLEADO_COMPLETO = 15
"""Cuántas validaciones por empleado se ejecutan sobre una fotografía con **todos** sus campos
presentes y **sin** configuración fiscal disponible — el estado de la instalación real hoy.

Son 15 y no 19 por dos motivos distintos, que conviene no mezclar:

- Dos pares son mutuamente excluyentes **por construcción**: `NSS_FALTANTE` solo se evalúa
  cuando el NSS está vacío (y entonces no se evalúan `NSS_LONGITUD` ni `NSS_DIGITO_VERIFICADOR`,
  que sí cuentan aquí), y `BANCO_SIN_CUENTA` solo cuando la cuenta está vacía (y entonces no se
  evalúa `CUENTA_INVALIDA`, que sí cuenta aquí). Eso descuenta dos de las 19.
- Las otras dos son las de SBC, que dependen de la configuración fiscal y se cuentan aparte en
  `VALIDACIONES_QUE_EXIGEN_CONFIGURACION`.

**Esta constante no es el total: es el piso.** El conteo real de una corrida es variable por
diseño (ver el docstring del módulo)."""

VALIDACIONES_QUE_EXIGEN_CONFIGURACION = 2
"""`SBC_SOBRE_TOPE` (UMA diaria vigente a la fecha de pago) y `SBC_BAJO_MINIMO` (zona salarial
de la empresa más el mínimo confirmado de esa zona). Se suman a
`VALIDACIONES_POR_EMPLEADO_COMPLETO` **solo** cuando el dato existe y está confirmado; si no,
no corren, no se cuentan, y dejan bandera."""

VALIDACIONES_DE_CONJUNTO = 3
"""`CURP_DUPLICADA`, `RFC_DUPLICADO` y `NSS_DUPLICADO`: se evalúan una vez por corrida sobre
todo el rango, no una vez por empleado."""

VALIDACIONES_ENTRE_PERIODOS_POR_RFC = 1
"""`DATOS_CAMBIANTES`: una evaluación por RFC del rango."""

# Claves y descripciones de "puesto/departamento vacío" (§ficha B-10): además de None y
# cadena vacía, los valores centinela que el patrón usa para decir "no aplica" sin dejar el
# campo realmente vacío.
_VALORES_VACIOS_TEXTO = frozenset({"", "ninguno", "n/a", "na"})


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango, sobre `nomina.fecha_pago`.")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    severidad_minima: Literal["alta", "media", "baja"] = Field(
        "baja", description="Solo se listan hallazgos de esta severidad o más alta (alta > media > baja)."
    )
    incluir_cancelados: bool = Field(False, description="Por defecto solo vigentes (R-T1).")
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
    """Adaptador local a `universo_nomina.ParametrosUniverso`. B-10 no expone `tipo_nomina`:
    la calidad de los datos del receptor no depende de si la nómina es ordinaria o
    extraordinaria, y filtrar por tipo dejaría "últimas fotografías" incompletas para
    empleados cuyo CFDI más reciente del rango fuera del tipo excluido (mismo razonamiento
    que `b04_matriz_empleado_periodo._ParametrosUniverso` y `b07_prestamos._ParametrosUniverso`)."""

    fecha_desde: date
    fecha_hasta: date
    incluir_cancelados: bool
    tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"


_COLUMNAS: tuple[tuple[str, str, bool], ...] = (
    ("RFC empleado", "texto", False),
    ("Nombre", "texto", False),
    ("Núm. empleado", "texto", False),
    ("Validación", "texto", False),
    ("Severidad", "texto", False),
    ("Descripción del hallazgo", "texto", False),
    ("CURP", "texto", True),
    ("NSS", "texto", True),
    ("SBC", "monto", False),
    ("SDI", "monto", False),
    ("Fecha inicio relación laboral", "fecha", False),
    ("Fecha final de pago", "fecha", False),
)


def _columnas() -> list[Columna]:
    return [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS]  # type: ignore[arg-type]


@dataclass(slots=True)
class _Identidad:
    """Última fotografía de `nomina_receptor` de un empleado en el rango, más lo que hace
    falta de `Comprobante`/`ComprobanteDetalle`/`Nomina` para evaluar y desplegar sus
    hallazgos."""

    comprobante_id: int
    rfc: str
    nombre: str | None
    num_empleado: str | None
    curp: str | None
    nss: str | None
    tipo_regimen: str | None
    sbc: Decimal | None
    sdi: Decimal | None
    fecha_inicio_rel_laboral: date | None
    fecha_final_pago: date | None
    # `fecha_pago` (no `fecha_final_pago`): es la fecha con la que se resuelven por vigencia la
    # UMA y el salario mínimo de las dos validaciones de SBC. Son fechas distintas —el periodo
    # puede cerrar en un tramo de vigencia y pagarse en el siguiente— y el criterio fiscal es la
    # del pago.
    fecha_pago: date | None
    num_dias_pagados: Decimal | None
    antiguedad: str | None
    banco: str | None
    cuenta_bancaria: str | None
    puesto: str | None
    departamento: str | None


@dataclass(slots=True)
class _Hallazgo:
    rfc: str
    clave: str
    severidad: Severidad
    mensaje: str


@dataclass(frozen=True, slots=True)
class _ConfiguracionSbc:
    """Los insumos de `param_fiscal` y `configuracion_empresa` que necesitan las dos
    validaciones de SBC, resueltos **por fecha de pago distinta** (regla 11).

    `zona_configurada` se guarda aparte porque distingue las dos causas de que el salario
    mínimo salga `None`: "la empresa no dice en qué zona está" (que se arregla en Configuración
    › Empresa) y "la zona está configurada pero no hay mínimo confirmado para esa fecha" (que se
    arregla en Configuración › Fiscal). Mandar a la pantalla equivocada es lo que hace inútil un
    aviso de configuración.
    """

    uma: dict[date, Decimal | None]
    uma_propuesta: dict[date, cfg.ValorFiscal | None]
    salario_minimo: dict[date, Decimal | None]
    zona_configurada: bool


@dataclass(frozen=True, slots=True)
class _PorEmpleado:
    """Lo que produce evaluar la última fotografía de un empleado.

    `omitidas` son las **claves de bandera** de las validaciones que no se pudieron evaluar por
    falta de configuración fiscal. Viaja junto a `ejecutadas` a propósito: el conteo y el motivo
    de lo no contado se deciden en el mismo sitio, y así no hay dos copias de la condición
    "¿corrió esta validación?" que puedan divergir.
    """

    hallazgos: list[_Hallazgo]
    ejecutadas: int
    omitidas: tuple[str, ...]


async def _configuracion_sbc(db: AsyncSession, empresa_id: int, fechas: set[date]) -> _ConfiguracionSbc:
    """La UMA diaria y el salario mínimo de la empresa, resueltos a cada fecha de pago distinta
    de las últimas fotografías del rango.

    `valor_propuesto` solo se consulta cuando no hay valor confirmado: es lo que convierte
    "falta la UMA, ve a buscarla" en "la UMA 2026 está propuesta con su fuente, confírmala".
    """
    config_empresa = await cfg.configuracion_de_empresa(db, empresa_id)
    uma: dict[date, Decimal | None] = {}
    uma_propuesta: dict[date, cfg.ValorFiscal | None] = {}
    salario_minimo: dict[date, Decimal | None] = {}
    for fecha in sorted(fechas):
        uma[fecha] = await cfg.valor_vigente(db, "UMA_DIARIA", fecha)
        uma_propuesta[fecha] = None if uma[fecha] is not None else await cfg.valor_propuesto(db, "UMA_DIARIA", fecha)
        salario_minimo[fecha] = await cfg.salario_minimo_de_empresa(db, empresa_id, fecha)
    return _ConfiguracionSbc(
        uma=uma,
        uma_propuesta=uma_propuesta,
        salario_minimo=salario_minimo,
        zona_configurada=config_empresa is not None and config_empresa.zona_salarial is not None,
    )


def _a_decimal(valor: Decimal | float | None) -> Decimal | None:
    """`Numeric` puede llegar como `Decimal` o como `float` según el atributo mapeado; nunca
    se opera en binario (mismo patrón que `identidades_b00._dec`), y `None` se conserva como
    `None` (no como cero: las comparaciones numéricas de este informe se omiten sobre datos
    ausentes, ver docstring del módulo)."""
    if valor is None:
        return None
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def _vacio_texto(valor: str | None) -> bool:
    """`PUESTO_VACIO`/`DEPARTAMENTO_VACIO`: `None`, cadena vacía, o los centinelas de "no
    aplica" que el patrón captura sin dejar el campo realmente vacío (`Ninguno`, `N/A`),
    comparados sin distinguir mayúsculas ni espacios sobrantes."""
    if valor is None:
        return True
    return valor.strip().lower() in _VALORES_VACIOS_TEXTO


def _vacio(valor: str | None) -> bool:
    """Vacío para NSS/cuenta bancaria: `None` o cadena vacía tras quitar espacios."""
    return valor is None or valor.strip() == ""


async def _percepciones_001_por_comprobante(db: AsyncSession, ids: list[int]) -> dict[int, Decimal]:
    """`SUM(importe_gravado + importe_exento)` de las percepciones `tipo_percepcion='001'`
    (Sueldo), por comprobante — una sola consulta agregada (regla 11: cero N+1), acotada a
    los comprobantes de la última fotografía de cada empleado, no a todo el universo."""
    if not ids:
        return {}
    filas = await db.execute(
        select(NominaPercepcion.comprobante_id, func.sum(NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento))
        .where(NominaPercepcion.comprobante_id.in_(ids), NominaPercepcion.tipo_percepcion == "001")
        .group_by(NominaPercepcion.comprobante_id)
    )
    resultado: dict[int, Decimal] = {}
    for comprobante_id, suma in filas:
        decimal_suma = _a_decimal(suma)
        if decimal_suma is not None:
            resultado[int(comprobante_id)] = decimal_suma
    return resultado


def _hallazgos_estructurales_y_derivados(
    identidad: _Identidad,
    percepciones_001: Decimal | None,
    uma: Decimal | None,
    hay_propuesta_de_uma: bool,
    salario_minimo: Decimal | None,
    zona_configurada: bool,
) -> _PorEmpleado:
    """Grupos 1 (estructura), 4 (derivadas de importes) y 5 (dependientes de la configuración
    fiscal) más las validaciones de fecha y de campos de texto vacíos: todo lo que se evalúa
    sobre la ÚLTIMA fotografía de un solo empleado, sin cruzar con otros CFDI del rango.

    Devuelve un `_PorEmpleado` con los hallazgos, cuántas validaciones se ejecutaron y qué
    causas de configuración impidieron evaluar alguna. El conteo es lo que hace auditable a la
    propia validación, con el mismo razonamiento del §13 del diseño para
    `identidades_b00.verificar`: **una validación que no corre no puede fallar**, así que
    `filas == []` es indistinguible de "no se comprobó nada" y borrar media docena de
    comprobaciones dejaría la suite verde. Cada comprobación que de verdad se evalúa suma uno;
    las que se omiten por falta de operando (ver el docstring del módulo) no suman, igual que
    `identidades_b00._checar` no cuenta un atributo ausente.

    Los valores de configuración llegan **ya resueltos a la fecha de pago de este empleado**:
    esta función es pura y no toca la base (ver `_configuracion_sbc`).

    **Ningún mensaje interpola la CURP, el NSS ni la cuenta bancaria.** El valor ya viaja en su
    propia columna, enmascarada o no según `enmascarar_datos_personales`; repetirlo en la
    descripción —que es una columna **no** sensible, y no puede marcarse como tal sin volver el
    mensaje ilegible— lo dejaba en claro en el Excel incluso con el enmascaramiento activado.
    Era el defecto más grave de la revisión final: 6 de 7 filas del informe que el propio
    docstring del módulo describe como "el que más datos personales expone" filtraban el dato
    que el parámetro decía estar protegiendo. Los mensajes describen el defecto y, cuando
    ayuda a accionarlo, nombran los **RFC** implicados: el RFC no es un dato enmascarado en
    este informe (sale completo en su propia columna) y es la llave con la que el capturista
    localiza al empleado."""
    hallazgos: list[_Hallazgo] = []
    rfc = identidad.rfc
    ejecutadas = 0
    omitidas: list[str] = []

    def _marca(clave: str, severidad: Severidad, mensaje: str) -> None:
        hallazgos.append(_Hallazgo(rfc=rfc, clave=clave, severidad=severidad, mensaje=mensaje))

    # --- Estructura ---
    ejecutadas += 1
    if not v.rfc_persona_fisica_valido(rfc):
        _marca("RFC_ESTRUCTURA", "alta", f"El RFC {rfc!r} no cumple la estructura de persona física (4 letras, 6 dígitos de fecha, 3 de homoclave).")

    ejecutadas += 1
    curp_estructura_valida = v.curp_valida(identidad.curp)
    if not curp_estructura_valida:
        _marca("CURP_ESTRUCTURA", "alta", "La CURP capturada no cumple la estructura esperada (ver la columna CURP de esta fila).")
    else:
        # `CURP_ENTIDAD` solo se evalúa si la estructura general ya es válida (ver docstring
        # del módulo): sin eso, las posiciones 12-13 no son fiables y ya se marcó
        # `CURP_ESTRUCTURA`. Por eso el `+= 1` va aquí y no fuera del `else`.
        ejecutadas += 1
        if not v.curp_entidad_valida(identidad.curp):
            _marca("CURP_ENTIDAD", "media", "La CURP no trae una clave de entidad federativa reconocida en las posiciones 12-13.")

    if identidad.curp is not None and not _vacio(identidad.curp) and not _vacio(rfc):
        ejecutadas += 1
        if rfc[:10] != identidad.curp[:10]:
            _marca(
                "RFC_CURP_INCONSISTENTE",
                "alta",
                "Las primeras 10 posiciones del RFC y de la CURP deben coincidir (mismos apellidos, nombre y fecha de "
                f"nacimiento) y no coinciden. RFC del empleado: {rfc!r}.",
            )

    if not _vacio(identidad.nss):
        nss = identidad.nss
        assert nss is not None  # para mypy: `_vacio` ya descartó `None`
        ejecutadas += 1
        if len(nss) != 11:
            _marca("NSS_LONGITUD", "media", f"El NSS capturado tiene {len(nss)} caracteres; se esperan 11.")
        else:
            # Luhn solo se evalúa con longitud correcta (ver docstring): sobre una longitud
            # equivocada no es significativo y ya se marcó `NSS_LONGITUD`.
            ejecutadas += 1
            if not v.nss_digito_verificador_valido(nss):
                _marca("NSS_DIGITO_VERIFICADOR", "media", "El NSS capturado no cumple el dígito verificador (algoritmo de Luhn sobre las 10 primeras posiciones).")
    elif identidad.tipo_regimen == "02":
        ejecutadas += 1
        _marca("NSS_FALTANTE", "alta", "El NSS está vacío con `tipo_regimen='02'` (régimen obligatorio de cotización IMSS).")

    # --- SBC / SDI (B-10.R1) ---
    sbc, sdi = identidad.sbc, identidad.sdi
    if identidad.tipo_regimen == "02" and sbc is not None:
        ejecutadas += 1
        if sbc <= 0:
            _marca("SBC_CERO", "alta", f"El SBC declarado es {sbc} con `tipo_regimen='02'`.")
    if sdi is not None:
        ejecutadas += 1
        if sdi <= 0:
            _marca("SDI_CERO", "alta", f"El SDI declarado es {sdi}.")
    if sbc is not None and sdi is not None:
        ejecutadas += 1
        if sdi < sbc * _TOLERANCIA_SDI_SBC:
            # Media, no alta (B-10.R1): un SDI inferior al SBC es teóricamente posible.
            _marca("SDI_MENOR_SBC", "media", f"El SDI ({sdi}) es menor al 80% del SBC ({sbc}); son conceptos distintos, pero conviene revisar.")

    # Las dos validaciones del grupo 5. `sbc > 0` y no `sbc is not None`: un SBC en cero no está
    # "por debajo del mínimo", es una base ausente, y `SBC_CERO` ya nombra ese defecto donde lo
    # es. Sin esta condición cada asimilado a salarios —que legítimamente no cotiza— saldría con
    # un hallazgo alta por corrida. `fecha_pago is not None` es inalcanzable a través de
    # `universo()` (filtra por ese campo): se comprueba para no atribuirle a la configuración un
    # hueco que sería del CFDI.
    if sbc is not None and sbc > 0 and identidad.fecha_pago is not None:
        if uma is None:
            omitidas.append("UMA_SIN_CONFIRMAR" if hay_propuesta_de_uma else "FALTA_UMA")
        else:
            ejecutadas += 1
            tope = _FACTOR_TOPE_SBC * uma
            if sbc > tope:
                _marca(
                    "SBC_SOBRE_TOPE",
                    "media",
                    f"El SBC declarado ({sbc}) excede el límite superior de cotización del artículo 28 de la "
                    f"LSS: {_FACTOR_TOPE_SBC} UMA diarias vigentes a la fecha de pago = {tope} "
                    f"({_FACTOR_TOPE_SBC} × {uma}).",
                )
        if salario_minimo is None:
            omitidas.append("FALTA_SALARIO_MINIMO" if zona_configurada else "FALTA_ZONA_SALARIAL")
        else:
            ejecutadas += 1
            if sbc < salario_minimo:
                _marca(
                    "SBC_BAJO_MINIMO",
                    "alta",
                    f"El SBC declarado ({sbc}) es menor al salario mínimo vigente a la fecha de pago para la "
                    f"zona salarial configurada en la empresa ({salario_minimo}). Ningún salario base de "
                    "cotización puede quedar por debajo del mínimo.",
                )

    if sdi is not None and percepciones_001 is not None and identidad.num_dias_pagados is not None and identidad.num_dias_pagados > 0:
        ejecutadas += 1
        sd_implicito = percepciones_001 / identidad.num_dias_pagados
        if sdi < sd_implicito:
            _marca(
                "SDI_MENOR_SD_IMPLICITO",
                "alta",
                f"El SDI declarado ({sdi}) es menor al sueldo diario implícito en el CFDI "
                f"(Σ percepción '001' / días pagados = {percepciones_001} / {identidad.num_dias_pagados} = {sd_implicito}).",
            )

    # --- Fechas ---
    if identidad.fecha_inicio_rel_laboral is not None and identidad.fecha_final_pago is not None:
        ejecutadas += 1
        if identidad.fecha_inicio_rel_laboral > identidad.fecha_final_pago:
            _marca(
                "FECHA_INICIO_POSTERIOR",
                "alta",
                f"`fecha_inicio_rel_laboral` ({identidad.fecha_inicio_rel_laboral}) es posterior a `fecha_final_pago` ({identidad.fecha_final_pago}).",
            )
        dias_declarados = v.antiguedad_iso_a_dias(identidad.antiguedad)
        if dias_declarados is not None:
            ejecutadas += 1
            dias_calculados = (identidad.fecha_final_pago - identidad.fecha_inicio_rel_laboral).days
            if abs(dias_declarados - dias_calculados) > _TOLERANCIA_ANTIGUEDAD_DIAS:
                _marca(
                    "ANTIGUEDAD_INCONSISTENTE",
                    "baja",
                    f"`@Antigüedad` ({identidad.antiguedad!r} = {dias_declarados} días) difiere en más de "
                    f"{_TOLERANCIA_ANTIGUEDAD_DIAS} días del cálculo desde `fecha_inicio_rel_laboral` ({dias_calculados} días).",
                )

    # --- Puesto / departamento ---
    ejecutadas += 1
    if _vacio_texto(identidad.puesto):
        _marca("PUESTO_VACIO", "baja", "El puesto está vacío, nulo o es un valor centinela (`Ninguno`/`N/A`).")
    ejecutadas += 1
    if _vacio_texto(identidad.departamento):
        _marca("DEPARTAMENTO_VACIO", "baja", "El departamento está vacío, nulo o es un valor centinela (`Ninguno`/`N/A`).")

    # --- Cuenta bancaria ---
    banco_presente = not _vacio(identidad.banco)
    cuenta_presente = not _vacio(identidad.cuenta_bancaria)
    if cuenta_presente:
        cuenta = identidad.cuenta_bancaria
        assert cuenta is not None
        ejecutadas += 1
        if not v.cuenta_bancaria_longitud_valida(cuenta):
            _marca("CUENTA_INVALIDA", "baja", f"La cuenta bancaria capturada tiene {len(cuenta)} caracteres; se esperan 10, 11, 16 o 18.")
    elif banco_presente:
        ejecutadas += 1
        _marca("BANCO_SIN_CUENTA", "baja", f"El banco ({identidad.banco!r}) está capturado pero la cuenta bancaria está vacía.")

    return _PorEmpleado(hallazgos=hallazgos, ejecutadas=ejecutadas, omitidas=tuple(omitidas))


def _hallazgos_de_conjunto(todas: list[_Identidad]) -> tuple[list[_Hallazgo], int]:
    """Grupo 2: `CURP_DUPLICADA`, `RFC_DUPLICADO`, `NSS_DUPLICADO`. Cruza **todos** los
    comprobantes del rango (no solo la última fotografía de cada empleado): una duplicidad de
    identidad no se ve mirando un solo CFDI.

    Devuelve `(hallazgos, validaciones_ejecutadas)`; las tres se evalúan una vez por corrida
    sobre todo el rango, no una vez por empleado, así que el conteo es
    `VALIDACIONES_DE_CONJUNTO` siempre que haya universo (ver `_hallazgos_estructurales_y_derivados`
    para el porqué del conteo).

    **`RFC_DUPLICADO` es la única clave que reporta "un RFC con más de una CURP"** (decisión de
    la revisión final). `DATOS_CAMBIANTES` disparaba también con ese mismo hecho y con la misma
    severidad alta, así que un solo defecto producía **dos** filas en un informe cuyo grano es
    "una fila = algo que corregir". Se conservó `RFC_DUPLICADO` —es una de las tres validaciones
    de duplicidad que pide la ficha, simétrica de `CURP_DUPLICADA`/`NSS_DUPLICADO`— y se acotó
    `DATOS_CAMBIANTES` a los campos que ninguna otra clave cubre (ver esa función)."""
    curp_a_rfcs: dict[str, set[str]] = {}
    rfc_a_curps: dict[str, set[str]] = {}
    nss_a_rfcs: dict[str, set[str]] = {}

    for identidad in todas:
        if not _vacio(identidad.curp):
            curp = identidad.curp
            assert curp is not None
            curp_a_rfcs.setdefault(curp, set()).add(identidad.rfc)
            rfc_a_curps.setdefault(identidad.rfc, set()).add(curp)
        if not _vacio(identidad.nss):
            nss = identidad.nss
            assert nss is not None
            nss_a_rfcs.setdefault(nss, set()).add(identidad.rfc)

    hallazgos: list[_Hallazgo] = []
    for curp, rfcs in curp_a_rfcs.items():
        if len(rfcs) > 1:
            for rfc in rfcs:
                otros = sorted(rfcs - {rfc})
                hallazgos.append(
                    _Hallazgo(
                        rfc=rfc,
                        clave="CURP_DUPLICADA",
                        severidad="alta",
                        mensaje=f"La CURP de este empleado también aparece con otro(s) RFC en el rango: {otros}.",
                    )
                )
    for rfc, curps in rfc_a_curps.items():
        if len(curps) > 1:
            hallazgos.append(
                _Hallazgo(
                    rfc=rfc,
                    clave="RFC_DUPLICADO",
                    severidad="alta",
                    mensaje=(
                        f"El RFC {rfc!r} aparece con {len(curps)} CURP distintas en el rango: una sola persona no puede "
                        "tener más de una. Revisa la captura de la CURP en los CFDI de este empleado."
                    ),
                )
            )
    for nss, rfcs in nss_a_rfcs.items():
        if len(rfcs) > 1:
            for rfc in rfcs:
                otros = sorted(rfcs - {rfc})
                hallazgos.append(
                    _Hallazgo(
                        rfc=rfc,
                        clave="NSS_DUPLICADO",
                        severidad="alta",
                        mensaje=f"El NSS de este empleado también aparece con otro(s) RFC en el rango: {otros}.",
                    )
                )
    return hallazgos, VALIDACIONES_DE_CONJUNTO


def _hallazgos_entre_periodos(todas: list[_Identidad]) -> tuple[list[_Hallazgo], int]:
    """Grupo 3: `DATOS_CAMBIANTES` — un mismo RFC con distinto NSS o distinta fecha de inicio de
    relación laboral entre comprobantes del rango. Solo aparece comparando periodos, nunca
    mirando un CFDI aislado.

    **Ya no incluye la CURP** (decisión de la revisión final, documentada también en
    `_hallazgos_de_conjunto`): "un RFC con más de una CURP" lo reporta `RFC_DUPLICADO`, con la
    misma severidad alta y el mismo grano, así que incluirlo aquí generaba dos filas para un
    solo defecto. Los dos campos que quedan no los cubre ninguna otra clave: `NSS_DUPLICADO`
    mira la dirección contraria (un NSS con varios RFC), y ninguna validación compara fechas de
    inicio entre periodos.

    Devuelve `(hallazgos, validaciones_ejecutadas)` — una evaluación por RFC del rango."""
    por_rfc: dict[str, list[_Identidad]] = {}
    for identidad in todas:
        por_rfc.setdefault(identidad.rfc, []).append(identidad)

    hallazgos: list[_Hallazgo] = []
    for rfc, identidades in por_rfc.items():
        # `i.nss is not None` (además de `not _vacio(i.nss)`) es lo que permite a mypy --strict
        # angostar `str | None` a `str` dentro de la comprehension: `_vacio` es una función
        # cualquiera para el checker, no un type guard.
        nss_vistos = {i.nss for i in identidades if i.nss is not None and not _vacio(i.nss)}
        fechas_inicio = {i.fecha_inicio_rel_laboral for i in identidades if i.fecha_inicio_rel_laboral is not None}

        campos_cambiantes = []
        if len(nss_vistos) > 1:
            # Sin los valores: el NSS es dato personal y esta descripción va en una columna no
            # sensible (ver `_hallazgos_estructurales_y_derivados`).
            campos_cambiantes.append(f"NSS ({len(nss_vistos)} valores distintos)")
        if len(fechas_inicio) > 1:
            campos_cambiantes.append(f"fecha de inicio de relación laboral: {sorted(fechas_inicio)}")

        if campos_cambiantes:
            hallazgos.append(
                _Hallazgo(
                    rfc=rfc,
                    clave="DATOS_CAMBIANTES",
                    severidad="alta",
                    mensaje=f"El RFC {rfc!r} tiene valores distintos entre periodos del rango — {'; '.join(campos_cambiantes)}.",
                )
            )
    return hallazgos, VALIDACIONES_ENTRE_PERIODOS_POR_RFC * len(por_rfc)


_MENSAJES_DE_CONFIGURACION: dict[str, str] = {
    "FALTA_UMA": (
        "No hay una UMA diaria confirmada para la fecha de pago de estos empleados, así que `SBC_SOBRE_TOPE` "
        "—el límite superior de cotización del artículo 28 de la LSS, 25 UMA diarias— no se evaluó. Captúrala "
        "en Configuración › Fiscal con su fuente (la publica el INEGI cada enero y entra en vigor el 1 de "
        "febrero) y vuelve a generar el informe."
    ),
    "FALTA_ZONA_SALARIAL": (
        "La empresa no tiene zona salarial configurada, así que `SBC_BAJO_MINIMO` no se evaluó para estos "
        "empleados. No se asume ninguna a propósito: el CFDI no dice en qué zona está el trabajador y no se "
        "infiere del domicilio ni del código postal; el mínimo de la Zona Libre de la Frontera Norte y el "
        "general se llevan casi un 40%, y suponer el general dejaría sin detectar a los empleados de una "
        "empresa fronteriza que sí están por debajo del mínimo. Configúrala en Configuración › Empresa."
    ),
    "FALTA_SALARIO_MINIMO": (
        "La zona salarial de la empresa está configurada, pero no hay un salario mínimo confirmado para esa "
        "zona en la fecha de pago de estos empleados, así que `SBC_BAJO_MINIMO` no se evaluó. Captúralo o "
        "confírmalo en Configuración › Fiscal."
    ),
}
"""Texto de las causas que no llevan procedencia. `UMA_SIN_CONFIRMAR` no está aquí: su mensaje
cita la **fuente** de la propuesta, que es lo que separa un aviso accionable de uno inútil (ver
`_banderas_de_configuracion`). Las claves son las mismas que usa `b03_gravado_exento` para los
mismos huecos, a propósito: quien filtre la hoja `Banderas` por `FALTA_ZONA_SALARIAL` debe
encontrar los dos informes que la necesitan, no una clave distinta en cada uno."""


def _banderas_de_configuracion(omitidas: dict[str, int], config: _ConfiguracionSbc) -> list[Bandera]:
    """**Una bandera por causa**, con el número de empleados a los que dejó sin evaluar — nunca
    una por empleado (la lección del colapso de banderas de la fase 2: 300 avisos idénticos
    sepultan los hallazgos accionables, que aquí son las filas del informe).

    Ámbito `informe` en las cuatro: lo que falta es un valor global de la empresa o del
    ejercicio, y la acción no cambia de un empleado a otro.
    """
    banderas: list[Bandera] = []
    for causa in sorted(omitidas):
        empleados = omitidas[causa]
        if causa == "UMA_SIN_CONFIRMAR":
            fuentes = sorted({valor.fuente for valor in config.uma_propuesta.values() if valor is not None})
            procedencia = f" Fuente de la propuesta: {'; '.join(fuentes)}." if fuentes else ""
            banderas.append(
                Bandera(
                    clave=causa,
                    severidad="alta",
                    ambito="informe",
                    mensaje=(
                        "Hay una UMA diaria capturada para la fecha de pago de estos empleados, pero nadie la ha "
                        "confirmado, y un valor sin confirmar no calcula: `SBC_SOBRE_TOPE` no se evaluó. Basta con "
                        f"revisarla y confirmarla en Configuración › Fiscal.{procedencia} Empleados sin evaluar: "
                        f"{empleados}."
                    ),
                )
            )
            continue
        banderas.append(
            Bandera(
                clave=causa,
                severidad="alta",
                ambito="informe",
                mensaje=f"{_MENSAJES_DE_CONFIGURACION[causa]} Empleados sin evaluar: {empleados}.",
            )
        )
    return banderas


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=_columnas(), aviso="La empresa no existe.")

    p_universo = _ParametrosUniverso(fecha_desde=p.fecha_desde, fecha_hasta=p.fecha_hasta, incluir_cancelados=p.incluir_cancelados)
    filas_universo = list((await db.execute(universo_nomina.universo(empresa_id, rfc_empresa, p_universo))).all())
    # Se resuelve ANTES del retorno temprano (mismo criterio que el resto del grupo B): si el
    # ETL falló en TODOS los CFDI del rango, la hoja Datos sale vacía y esta bandera es el
    # único rastro de que había nómina que auditar.
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, rfc_empresa, p_universo)

    if not filas_universo:
        return ResultadoInforme(
            columnas=_columnas(),
            banderas=banderas_fuera,
            aviso="Sin CFDI de nómina en el rango solicitado.",
        )

    # `todas`: una `_Identidad` por comprobante, para las validaciones de conjunto y entre
    # periodos (grupos 2 y 3), que necesitan ver TODO el rango.
    # `ultima_por_rfc`: se sobrescribe en el orden de iteración; `filas_universo` viene
    # ordenado ascendente por `fecha_pago` (mismo `order_by` de `universo_nomina.universo`),
    # así que al terminar el recorrido queda la más reciente de cada empleado.
    todas: list[_Identidad] = []
    ultima_por_rfc: dict[str, _Identidad] = {}
    for comprobante, nomina, receptor, _totales, detalle in filas_universo:
        identidad = _Identidad(
            comprobante_id=comprobante.comprobante_id,
            rfc=comprobante.rfc_receptor,
            nombre=detalle.nombre_receptor if detalle else None,
            num_empleado=receptor.num_empleado if receptor else None,
            curp=receptor.curp if receptor else None,
            nss=receptor.nss if receptor else None,
            tipo_regimen=receptor.tipo_regimen if receptor else None,
            sbc=_a_decimal(receptor.salario_base_cot_apor if receptor else None),
            sdi=_a_decimal(receptor.salario_diario_integrado if receptor else None),
            fecha_inicio_rel_laboral=receptor.fecha_inicio_rel_laboral if receptor else None,
            fecha_final_pago=nomina.fecha_final_pago,
            fecha_pago=nomina.fecha_pago,
            num_dias_pagados=_a_decimal(nomina.num_dias_pagados),
            antiguedad=receptor.antiguedad if receptor else None,
            banco=receptor.banco if receptor else None,
            cuenta_bancaria=receptor.cuenta_bancaria if receptor else None,
            puesto=receptor.puesto if receptor else None,
            departamento=receptor.departamento if receptor else None,
        )
        todas.append(identidad)
        ultima_por_rfc[identidad.rfc] = identidad

    ids_ultima_fotografia = [identidad.comprobante_id for identidad in ultima_por_rfc.values()]
    percepciones_001 = await _percepciones_001_por_comprobante(db, ids_ultima_fotografia)
    # Solo las fechas de pago de las últimas fotografías, y sin repetir: las dos validaciones de
    # SBC se evalúan sobre esa fotografía, no sobre todo el rango.
    config_sbc = await _configuracion_sbc(
        db, empresa_id, {i.fecha_pago for i in ultima_por_rfc.values() if i.fecha_pago is not None}
    )

    hallazgos: list[_Hallazgo] = []
    validaciones_ejecutadas = 0
    # Causa de configuración -> a cuántos empleados dejó sin evaluar. Es lo que colapsa las
    # banderas de degradación en una por causa.
    omitidas_por_causa: dict[str, int] = {}
    for rfc, identidad in ultima_por_rfc.items():
        del rfc  # la clave no se usa: la identidad ya trae su propio `rfc`
        fecha = identidad.fecha_pago
        resultado_empleado = _hallazgos_estructurales_y_derivados(
            identidad,
            percepciones_001.get(identidad.comprobante_id),
            config_sbc.uma.get(fecha) if fecha is not None else None,
            (config_sbc.uma_propuesta.get(fecha) is not None) if fecha is not None else False,
            config_sbc.salario_minimo.get(fecha) if fecha is not None else None,
            config_sbc.zona_configurada,
        )
        hallazgos.extend(resultado_empleado.hallazgos)
        validaciones_ejecutadas += resultado_empleado.ejecutadas
        for causa in resultado_empleado.omitidas:
            omitidas_por_causa[causa] = omitidas_por_causa.get(causa, 0) + 1
    de_conjunto, ejecutadas_conjunto = _hallazgos_de_conjunto(todas)
    hallazgos.extend(de_conjunto)
    validaciones_ejecutadas += ejecutadas_conjunto
    entre_periodos, ejecutadas_periodos = _hallazgos_entre_periodos(todas)
    hallazgos.extend(entre_periodos)
    validaciones_ejecutadas += ejecutadas_periodos

    # `VALIDACIONES_EJECUTADAS`: la hoja `Banderas` dice cuántas comprobaciones se corrieron de
    # verdad, no solo qué encontraron. Es el equivalente del `cotejos` de
    # `identidades_b00.verificar` (§13 del diseño) y existe por la misma razón: sin este número,
    # una hoja `Datos` vacía no distingue "los datos están bien" de "no se validó nada", y las
    # pruebas que aseveran `filas == []` pasan **más fácil** cuando se borra una validación.
    banderas = list(banderas_fuera)
    banderas.extend(_banderas_de_configuracion(omitidas_por_causa, config_sbc))
    banderas.append(
        Bandera(
            clave="VALIDACIONES_EJECUTADAS",
            severidad="baja",
            ambito="informe",
            mensaje=(
                f"Se ejecutaron {validaciones_ejecutadas} validaciones sobre {len(ultima_por_rfc)} empleado(s) "
                f"y {len(todas)} CFDI del rango, de las {VALIDACIONES_IMPLEMENTADAS} implementadas "
                f"({VALIDACIONES_POR_EMPLEADO_COMPLETO} por empleado con todos sus campos presentes, más "
                f"{VALIDACIONES_QUE_EXIGEN_CONFIGURACION} que además exigen configuración fiscal confirmada, "
                f"{VALIDACIONES_DE_CONJUNTO} de conjunto y {VALIDACIONES_ENTRE_PERIODOS_POR_RFC} entre periodos por RFC). "
                "Una validación que se omite por falta de dato no cuenta, así que este número es variable por "
                "diseño: si falta la UMA o la zona salarial, las dos validaciones de SBC no corren y las "
                "banderas de esta misma hoja dicen cuál falta."
            ),
        )
    )

    umbral = _ORDEN_SEVERIDAD[p.severidad_minima]
    hallazgos_filtrados = [h for h in hallazgos if _ORDEN_SEVERIDAD[h.severidad] <= umbral]
    hallazgos_filtrados.sort(key=lambda h: (h.rfc, _ORDEN_SEVERIDAD[h.severidad], h.clave))

    filas: list[list[Any]] = []
    for h in hallazgos_filtrados:
        identidad = ultima_por_rfc[h.rfc]
        filas.append(
            [
                identidad.rfc,
                identidad.nombre,
                identidad.num_empleado,
                h.clave,
                h.severidad,
                h.mensaje,
                identidad.curp,
                identidad.nss,
                identidad.sbc,
                identidad.sdi,
                identidad.fecha_inicio_rel_laboral,
                identidad.fecha_final_pago,
            ]
        )

    return ResultadoInforme(columnas=_columnas(), filas=filas, banderas=banderas)
