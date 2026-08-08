"""B-06 · Costo de nómina por centro de costo (§B-06 del documento fuente).

Grano: **una fila por `(ejercicio, periodo, centro de costo)`**, o por
`(ejercicio, periodo, centro de costo, empleado)` con `detalle_empleado`.

Para quién es
-------------
Esta organización **ejecuta recursos etiquetados**, así que B-06 no es un informe de
curiosidad: es el insumo con el que comprueba ante el financiador **a dónde se fue el
dinero**. Todo lo que sigue —la cascada de resolución, el reporte de calidad del
agrupamiento, la negativa a retropropagar el departamento— existe porque una cifra por
centro de costo que nadie puede auditar no sirve para comprobar nada.

B-06.R1 — la cascada tiene **dos** niveles, no tres
----------------------------------------------------
La ficha del documento fuente describe tres niveles y el primero lee una tabla
`plantilla_rh` (la plantilla de recursos humanos con el centro de costo asignado a cada
puesto). **Esa tabla no existe en este sistema** y no está planeada: no hay migración,
modelo ni pantalla que la produzca, y ningún CFDI la puede alimentar. Queda escrito aquí
para que nadie la busque, la dé por perdida ni "arregle" la cascada agregándole un nivel
muerto. Los dos niveles que sí existen son:

1. **`map_departamento` de la empresa** (`cfg.centro_de_costo`), por el texto del
   departamento tal como viene en el CFDI.
2. **El texto crudo de `nomina_receptor.departamento`**, cuando no hay mapeo para él.

Y un tercer caso que no es un nivel de la cascada sino la ausencia del dato de entrada: un
CFDI **sin departamento**. No se puede mapear —`departamento_texto` va en la PK de
`map_departamento`, y por eso `cfg.observados_de_empresa` ni siquiera lo enumera— así que
se agrupa aparte, bajo `SIN_DEPARTAMENTO`, con bandera propia.

**El texto no se normaliza al buscarlo en el mapa.** Ni `strip()` ni mayúsculas ni acentos:
la clave de búsqueda es el texto exacto que trae el CFDI, que es el mismo que enumera la
pantalla de configuración (`cfg.observados_de_empresa`). Normalizar aquí produciría el peor
de los mundos —el informe uniría "EDIFICIOS" y " Edificios " pero la pantalla seguiría
pidiendo mapear los dos por separado, y un mapeo capturado sobre el texto con espacios no
casaría nunca—. Además, **unificar variantes ortográficas es exactamente para lo que existe
`map_departamento`**: hacerlo a medias por debajo escondería el problema que el mapeo
resuelve. La consecuencia visible —dos variantes del mismo departamento sin mapeo caen en
grupos distintos— es deliberada y está fijada en las pruebas.

**Residuo declarado de esa decisión.** Hay una variante que hoy **no se puede arreglar desde
la configuración**: la que difiere solo en mayúsculas o en espacios finales. `map_departamento`
vive en una tabla `utf8mb4_unicode_ci` y su PK incluye `departamento_texto`, así que MySQL
considera "EDIFICIOS" y "Edificios " la **misma** clave y rechaza el segundo renglón; pero la
búsqueda de este módulo es un `dict` de Python, que sí las distingue. Resultado: se puede
mapear una de las dos y la otra seguirá cayendo al texto crudo, sin forma de capturarla. El
arreglo correcto es de esquema —colación binaria en esa columna, o una columna normalizada
con su índice— y exige migración, así que no cabe en esta tarea; queda escrito para que no se
descubra en vivo. Mientras tanto, `DEPARTAMENTO_SIN_MAPEO` sigue nombrando el texto exacto que
falta, que es lo que permite ver el caso.

Dos niveles distintos **sí** se funden en un mismo grupo cuando resuelven al mismo centro:
si "EDIF" está mapeado a "EDIFICIOS" y otro CFDI trae el texto crudo "EDIFICIOS", los dos
son el mismo centro de costo y suman en la misma fila. El nivel de resolución no forma
parte de la llave de agrupamiento, a propósito. Lo único que **sí** entra en la llave, además
del centro, es si el CFDI venía sin departamento: un centro de costo o un texto crudo que se
llamara literalmente igual que `SIN_DEPARTAMENTO` se fundiría con el grupo de los ausentes
mientras se contaría en otro nivel del censo, y el rótulo dejaría de significar lo que dice.
Es un caso rebuscado y la guarda cuesta un elemento de la tupla.

El otro lado del agrupamiento: el **valor** configurado del centro de costo
----------------------------------------------------------------------------
La cascada instrumenta a fondo el lado del *texto del departamento*, pero el agrupamiento
tiene un segundo lado que puede salir mal igual de callado: **el valor de
`map_departamento.centro_costo` es texto libre sin catálogo** (la pantalla es un `<input>` y
el esquema solo exige `min_length=1`). Si alguien mapea `EDIF → "EDIFICIOS"` y
`EDIFICIO → "Edificios"`, salen **dos** centros de costo, los dos contados como nivel 1, y sin
esta comprobación el censo diría "2 se resolvieron con el mapeo" sin una sola alerta: el
informe se vería impecable con el gasto partido en dos.

Se detecta **desde el mapa**, no desde las filas impresas, y se **reporta sin normalizar**
(`CENTRO_DE_COSTO_AMBIGUO`, más `CENTRO_DE_COSTO_EN_BLANCO` para su variante degenerada, que
`min_length=1` deja pasar). Reportar y no unificar es la misma doctrina que con el texto del
departamento, y aquí es más importante todavía: unificar dos centros por su parecido
tipográfico sería el sistema decidiendo un hecho contable —que esos dos son el mismo centro—
sobre un dato que nadie revisó. Se detecta desde el mapa y no desde lo impreso porque una
configuración ambigua es un defecto de configuración aunque en este rango no haya cobrado
nadie de esos departamentos: el arreglo se hace una vez y sirve para todos los rangos.

Cómo se reporta la calidad del agrupamiento, y por qué no cuelga de una fila
-----------------------------------------------------------------------------
La ficha pide dos cosas distintas y este módulo las emite con **dos claves distintas**:

- `DEPARTAMENTO_SIN_MAPEO` es la **alerta**: solo aparece cuando de verdad hubo CFDI que
  cayeron al texto crudo. Va **agregada** —una bandera con el conteo de CFDI afectados y la
  lista de textos sin mapear, nunca una por fila—, que es la lección del colapso de banderas
  de la fase 2 (`universo_nomina._banderas_de_no_verificado`) y la regla que B-03 dejó
  escrita: una hoja `Banderas` con cien avisos idénticos sepulta los hallazgos accionables.
- `RESOLUCION_DE_CENTRO_DE_COSTO` es el **reporte**: cuántos CFDI resolvió cada nivel. La
  ficha lo pide explícitamente y es lo que hace auditable el agrupamiento — sin él, un total
  por centro de costo no se puede defender ante un financiador, porque nadie sabe qué parte
  del agrupamiento salió de una configuración revisada y qué parte de un texto libre.
  **Se emite siempre**, incluso cuando todo resolvió por el mapeo, y eso no contradice la
  regla de que "una bandera que dispara siempre es peor que no tenerla": esa regla es sobre
  *alertas*, y esta es un **censo**. Por eso lleva severidad `baja` y clave propia, para que
  quien filtre la hoja por severidad no la confunda con un hallazgo. **No es una excepción
  inventada aquí:** `b10_validacion_receptor` emite `VALIDACIONES_EJECUTADAS` con la misma
  severidad, el mismo ámbito y el mismo argumento —"sin este número, una hoja `Datos` vacía no
  distingue *los datos están bien* de *no se validó nada*"—, y ahí también existe porque las
  pruebas que aseveran ausencia pasan **más fácil** cuando se borra la comprobación.

**Ninguna de las dos depende de que se imprima una fila** (la regla general del docstring de
`b03_gravado_exento`): se calculan sobre el universo de CFDI, no sobre las filas agregadas.
Un centro con importe cero, o un grupo que el lector no mire, no puede apagar el aviso.

B-06.R3 — cada CFDI al departamento que él declara
---------------------------------------------------
Un empleado que cambia de área a mitad del ejercicio se asigna, en cada periodo, al
departamento **declarado en ese CFDI**. El departamento actual **no se retropropaga** hacia
los periodos anteriores. Reescribir la historia del gasto es justo lo que un financiador no
puede aceptar: el recurso etiquetado se ejecutó donde se ejecutó, y moverlo a posteriori
—aunque el CFDI no cambie— convertiría la comprobación en una reconstrucción. Como
consecuencia, el mismo empleado puede aparecer en dos centros de costo del mismo ejercicio,
y "Núm. de empleados" cuenta RFC distintos **dentro de cada grupo**: sumar esa columna entre
centros de un mismo periodo puede dar más que la plantilla real, y es correcto que así sea.

La columna 15 (costo patronal estimado) queda fuera de alcance
----------------------------------------------------------------
No se declara ni la columna ni un parámetro para ella. El costo patronal **no es derivable
del CFDI**: el complemento de nómina solo trae la parte **obrera** de la seguridad social
(lo que se le retiene al trabajador). Publicarlo exigiría las cuotas patronales del IMSS,
la aportación al INFONAVIT y el impuesto sobre nóminas estatal, ninguna de las cuales está
en el timbre; sería una **estimación** que habría que rotular como tal, con sus tasas
capturadas y confirmadas como cualquier otro valor fiscal (§2.12). Una cifra estimada
presentada junto a cifras timbradas, en el informe con el que se comprueba un recurso
etiquetado, es exactamente el tipo de error caro que este proyecto evita.

**Qué sí es "Costo bruto", y el subsidio dentro de él.** Es total de percepciones + otros
pagos, tal como lo define la ficha, y **no se redefine**: esa columna tiene que atar con
`nomina.total_percepciones + total_otros_pagos` y con lo que B-01 y B-02 reportan del mismo
periodo. Publicar aquí un "costo bruto neto de subsidio" sería una columna que se llama igual
que en los otros informes y significa otra cosa, que es exactamente el defecto que
`universo_nomina.banderas_de_gravado_y_exento_descuadrados` existe para no repetir ("Total
gravado" significaba dos cosas según el informe y nadie lo advertía); con un financiador de
por medio, la cifra que no ata con la de al lado es la que dispara la observación.

Pero el problema contable es real: entre los "otros pagos" viaja el **subsidio para el empleo
entregado en efectivo** (`c_TipoOtroPago` `002`), que el patrón desembolsa y **recupera contra
el ISR**, así que no es costo propio. La salida es **aditiva**: se publica en su propia columna,
«Subsidio para el empleo entregado», al lado de «Otros pagos». "Costo bruto" sigue significando
lo de la ficha y atando con todo, quien lea resta él mismo, y nada queda escondido. Va además
en `notas`, porque quien recibe el Excel no lee este docstring.

Reglas transversales que este módulo respeta
----------------------------------------------
- **`Decimal` de punta a punta.** Ni un `float`, ni un `round()`, ni un `quantize()`: el
  único redondeo del sistema es el `ROUND_HALF_UP` de `app.informes.excel` al escribir la
  celda (R-T4). Ojo con su consecuencia en el porcentaje: ver `_porcentaje`.
- **Cero, no vacío** (R-T7) en toda celda de importe. Aquí no hay ninguna celda que dependa
  de configuración fiscal por capturar, así que no hay ningún hueco legítimo: la ausencia de
  `map_departamento` degrada el **agrupamiento**, nunca los importes.
- **Cero N+1** (regla 11): cuatro consultas agregadas para todo el informe, más el universo
  y las banderas compartidas. Ninguna por empleado ni por comprobante. Y las tres tablas del
  `outerjoin` de `universo()` (`nomina_receptor`, `nomina_totales`, `comprobante_detalle`)
  tienen `comprobante_id` como PK, así que no multiplican filas: los importes que se suman
  recorriendo el universo no se pueden inflar por un `join` en abanico.
- **Claves del catálogo del SAT como texto** (`'001'`, nunca `1`).
- **Ningún importe fiscal codificado** (§2.12): este informe suma lo timbrado y no aplica
  ningún factor, tope ni tasa, así que no lee `param_fiscal` en absoluto.
- **El motor enmascara, el informe declara**: ver la nota de
  `Parametros.enmascarar_datos_personales`. Este informe **no selecciona** CURP ni NSS de la
  base, así que tampoco puede filtrarlos por una bandera (la fuga real de B-10).
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import universo_nomina
from app.informes.base import Bandera, Columna, ResultadoInforme
from app.informes.identidades_b00 import CLAVE_TIPO_DEDUCCION_ISR
from app.models.empresa import Empresa
from app.models.nomina import NominaDeduccion, NominaOtroPago, NominaPercepcion
from app.services import configuracion_fiscal as cfg

CLAVE = "B-06"
NOMBRE = "Costo de nómina por centro de costo"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por periodo y centro de costo, con el desglose del costo de nómina (sueldos, prestaciones, "
    "asimilados, otros pagos) y su peso sobre el total del periodo. Es el informe con el que se comprueba "
    "ante un financiador a dónde se fue el gasto de personal."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Tipos de comprobante que este informe necesita normalizados (todo el grupo B: solo `N`).
Lo consume el pre-vuelo del ETL (`app.worker.tasks._generar_informe_async`); ver la constante
homónima de `b02_conceptos_patron` para el argumento completo."""

_CERO = Decimal("0")
_CIEN = Decimal("100")

_CLAVE_PERCEPCION_SUELDOS = "001"
"""`c_TipoPercepcion` 001, "Sueldos, Salarios Rayas y Jornales": la columna «Sueldos»."""

_CLAVE_PERCEPCION_ASIMILADOS = "046"
"""`c_TipoPercepcion` 046, "Ingresos asimilados a salarios". Va en columna propia y **no**
en «Prestaciones» porque no es una prestación laboral: es otro régimen de contratación, y
mezclarlo con las prestaciones del personal de planta daría un costo de prestaciones falso
justo en el informe con el que se comprueba el gasto."""

_CLAVE_DEDUCCION_ISR = CLAVE_TIPO_DEDUCCION_ISR
"""`"002"` (catálogo `c_TipoDeduccion`), reexportado de `identidades_b00` para no declarar
dos veces la misma clave."""

_CLAVE_DEDUCCION_IMSS = "001"
"""Clave del catálogo `c_TipoDeduccion` de "Seguridad social": la parte **obrera** de la
cuota, la única que trae el CFDI. Mismo valor que `b05_acumulado_anual._CLAVE_DEDUCCION_IMSS`,
declarado aparte a propósito: es una clave de catálogo, no lógica compartida entre módulos."""

_CLAVE_OTRO_PAGO_SUBSIDIO = "002"
"""Clave del catálogo `c_TipoOtroPago` de "Subsidio para el empleo (efectivamente entregado al
trabajador)": la columna «Subsidio para el empleo entregado». Mismo valor que
`b05_acumulado_anual._CLAVE_OTRO_PAGO_SUBSIDIO`, declarado aparte por el mismo motivo que el
del IMSS: es una clave de catálogo, no lógica compartida entre módulos."""

SIN_DEPARTAMENTO = "(sin departamento)"
"""Etiqueta del grupo de los CFDI que no traen departamento. Es un rótulo de presentación,
no un centro de costo: por eso va entre paréntesis y en minúsculas, para que se distinga a
simple vista de los centros reales, que la organización escribe en mayúsculas.

**No es una llave de agrupamiento por sí sola.** La llave lleva además la marca de "venía sin
departamento", para que un centro de costo o un texto crudo llamado literalmente igual que
esta cadena no se funda con el grupo de los ausentes."""

_NOTAS: tuple[str, ...] = (
    "«Núm. de empleados» cuenta trabajadores distintos dentro de cada centro de costo. Un empleado que "
    "cobró en dos centros del mismo periodo cuenta en los dos (B-06.R3: cada CFDI se atribuye al "
    "departamento que él declara), así que la suma de esta columna entre centros puede exceder la "
    "plantilla real; no la sumes.",
    "«Periodo» es el MES de la fecha de pago. Un mes con dos fechas de pago agrega las dos quincenas en "
    "una sola fila: con nómina quincenal, una fila puede ser una quincena o dos según cómo caiga el "
    "calendario de pago de ese mes. Si necesitas el corte por quincena, el dato está en el CFDI "
    "(`fecha_inicial_pago`/`fecha_final_pago`) pero este informe no lo usa como eje.",
    "«% del total del periodo» se mide contra el costo bruto de los CFDI que caen DENTRO del rango "
    "consultado. Un rango que parte un mes por la mitad produce porcentajes sobre un mes truncado, "
    "indistinguibles de los de un mes completo: para comparar periodos entre sí, consulta meses enteros.",
    "«Costo bruto» es total de percepciones + otros pagos, como lo define la ficha, y entre los otros "
    "pagos viaja el subsidio para el empleo entregado en efectivo, que el patrón desembolsa pero "
    "recupera contra el ISR: no es costo propio. Se publica en su propia columna para que puedas "
    "restarlo, y NO se descuenta del costo bruto, que así sigue atando con el complemento de nómina y "
    "con lo que reportan B-01 y B-02 del mismo periodo.",
)
"""Lo que `app.informes.excel` rotula en la hoja `Parámetros` del libro.

Son advertencias **permanentes** sobre cómo leer estas cifras, no avisos de la corrida, así que
van en `ResultadoInforme.notas` y no en `aviso` ni en una `Bandera` (ver el docstring del campo
en `app.informes.base`). Y van en el libro y no solo en este docstring porque quien recibe el
Excel —el financiador, o quien arma la comprobación— no lee el código.

Las dos primeras se rompen solas con el uso: la segunda porque la nómina real es quincenal y
hoy sus dos fechas de pago caen en meses distintos, así que "mes" y "quincena" coinciden **por
accidente** y dejarán de coincidir en cuanto un mes reciba dos pagos."""


def _plegar(texto: str) -> str:
    """Forma comparable de un centro de costo: sin acentos, sin diferencias de caja y con los
    espacios colapsados.

    **Solo se usa para DETECTAR ambigüedad, nunca para agrupar.** Es la línea que separa
    "hazlo visible" de "arréglalo por tu cuenta": agrupar por esta forma haría que el sistema
    decidiera que "EDIFICIOS" y "Edificios" son el mismo centro de costo —un hecho contable—
    a partir de un parecido tipográfico que nadie revisó.
    """
    sin_acentos = "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c))
    return " ".join(sin_acentos.split()).upper()

MAX_TEXTOS_EN_BANDERA = 20
"""Cuántos textos de departamento sin mapear se citan en `DEPARTAMENTO_SIN_MAPEO`. No son
cero —quien la lee necesita saber qué capturar— y no son todos: el mensaje dice cuántos hay
en total. Mismo criterio que `universo_nomina.MUESTRA_UUID_COLAPSO`."""


class NivelDeResolucion(str, Enum):
    """Con qué se resolvió el centro de costo de un CFDI. Alimenta el reporte de calidad del
    agrupamiento (`RESOLUCION_DE_CENTRO_DE_COSTO`), que es lo que la ficha pide para que el
    agrupamiento sea auditable."""

    MAPEO = "mapeo"
    """Nivel 1: `map_departamento` de la empresa."""

    TEXTO_CRUDO = "texto_crudo"
    """Nivel 2: el texto de `nomina_receptor.departamento`, sin mapeo que lo traduzca."""

    AUSENTE = "ausente"
    """No es un nivel de la cascada: el CFDI no trae departamento y no hay nada que resolver."""


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango, sobre `nomina.fecha_pago` (R-T6).")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    detalle_empleado: bool = Field(
        False,
        description=(
            "Cambia el grano de `(periodo, centro de costo)` a `(periodo, centro de costo, empleado)` y "
            "agrega las columnas de identidad del trabajador. El porcentaje sigue midiéndose contra el "
            "total del periodo, así que sigue sumando 100 por periodo."
        ),
    )
    incluir_cancelados: bool = Field(False, description="Por defecto solo vigentes (R-T1).")
    enmascarar_datos_personales: bool = Field(
        True,
        description=(
            "Enmascara los datos personales (spec §8). Lo aplica el motor de informes "
            "(`app.informes.excel.escribir_libro`) sobre las columnas que esta consulta marca como "
            "`sensible=True`, no esta consulta directamente. **Hoy B-06 no declara ninguna**: un informe "
            "de costo por centro de costo no necesita CURP ni NSS, así que ni siquiera se leen de la base "
            "—no publicar un dato es más fuerte que enmascararlo—. El parámetro se declara igual que en el "
            "resto del grupo B para que la superficie de los informes sea uniforme y para que el "
            "enmascaramiento ya esté pedido el día que se agregue una columna sensible."
        ),
    )
    """Queda declarado aunque hoy no tenga efecto, y la decisión es deliberada: quitarlo haría de
    B-06 el único informe del grupo B sin este parámetro, y el día que alguien agregue una columna
    sensible habría que volver a declararlo, pasarlo por el formulario y probarlo, con la ventana
    de que se olvide justo en el informe que ya circula por correo.

    Lo que sí es un defecto —y está **fuera** de este módulo— es que la pantalla muestre el
    control por el hecho de que el parámetro exista: debería derivar su visibilidad de si el
    informe declara alguna `Columna(sensible=True)`, que es el dato real y que arregla el mismo
    síntoma en cualquier informe futuro sin tocar ninguno."""


@dataclass(slots=True)
class _ParametrosUniverso:
    """Adaptador local a `universo_nomina.ParametrosUniverso`. B-06 no expone `tipo_nomina`,
    igual que B-03 y B-05 y por el mismo motivo aplicado a este informe: el aguinaldo y el
    finiquito se pagan en nóminas **extraordinarias** y son costo del centro igual que la
    quincena ordinaria. Filtrar por tipo dejaría fuera del comprobante ante el financiador
    justo los pagos más grandes del ejercicio."""

    fecha_desde: date
    fecha_hasta: date
    incluir_cancelados: bool
    tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"


_COLUMNAS_CABECERA: tuple[tuple[str, str], ...] = (
    ("Ejercicio", "entero"),
    ("Periodo", "entero"),
    ("Centro de costo", "texto"),
)

_COLUMNAS_EMPLEADO: tuple[tuple[str, str], ...] = (
    ("RFC empleado", "texto"),
    ("Nombre empleado", "texto"),
    ("Núm. empleado", "texto"),
)
"""Solo con `detalle_empleado`. Sin ellas el grano por empleado sería ilegible —tantas filas
por centro como trabajadores, y ninguna forma de saber cuál es cuál—, así que son parte del
parámetro, no una columna extra de la ficha. Ni CURP ni NSS: ver
`Parametros.enmascarar_datos_personales`."""

_COLUMNAS_CIFRAS: tuple[tuple[str, str], ...] = (
    ("Núm. de empleados", "entero"),
    ("Núm. de CFDI", "entero"),
    ("Días pagados", "decimal"),
    ("Sueldos", "monto"),
    ("Prestaciones", "monto"),
    ("Asimilados", "monto"),
    ("Total percepciones", "monto"),
    ("Otros pagos", "monto"),
    # Va **dentro** de «Otros pagos» y por tanto dentro de «Costo bruto»: es un desglose, no un
    # sumando más. Existe para que el lector pueda restar dinero federal recuperable contra el
    # ISR sin que el informe redefina «Costo bruto» (ver el docstring del módulo).
    ("Subsidio para el empleo entregado", "monto"),
    ("Costo bruto", "monto"),
    ("ISR retenido", "monto"),
    ("IMSS obrero retenido", "monto"),
    ("Neto pagado", "monto"),
    ("Costo promedio por empleado", "monto"),
    ("% del total del periodo", "decimal"),
)


def _columnas(detalle_empleado: bool) -> list[Columna]:
    definiciones = _COLUMNAS_CABECERA + (_COLUMNAS_EMPLEADO if detalle_empleado else ()) + _COLUMNAS_CIFRAS
    return [Columna(titulo=titulo, tipo=tipo) for titulo, tipo in definiciones]  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# B-06.R1: la cascada de dos niveles
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CentroResuelto:
    """El centro de costo de un CFDI y con qué se resolvió.

    El `nivel` **no** entra en la llave de agrupamiento (ver el docstring del módulo): dos
    CFDI que resuelven al mismo centro por caminos distintos son el mismo centro de costo.
    Se conserva solo para el reporte de calidad del agrupamiento.
    """

    centro: str
    nivel: NivelDeResolucion


def resolver_centro_de_costo(departamento: str | None, mapa: Mapping[str, str]) -> _CentroResuelto:
    """B-06.R1, los dos niveles que existen (el `plantilla_rh` de la ficha **no** existe en
    este sistema: ver el docstring del módulo).

    El texto se busca en el mapa **tal cual viene**, sin normalizar. Lo único que se recorta
    es el caso de un departamento en blanco, que no es un departamento con un nombre raro
    sino la ausencia del dato: `None` y `"   "` son lo mismo y no se pueden mapear.
    """
    if departamento is None or not departamento.strip():
        return _CentroResuelto(SIN_DEPARTAMENTO, NivelDeResolucion.AUSENTE)
    centro = mapa.get(departamento)
    if centro is not None:
        return _CentroResuelto(centro, NivelDeResolucion.MAPEO)
    return _CentroResuelto(departamento, NivelDeResolucion.TEXTO_CRUDO)


# --------------------------------------------------------------------------------------
# Los agregados: una consulta por tabla hija, ninguna por comprobante (regla 11)
# --------------------------------------------------------------------------------------


def _dec(valor: object) -> Decimal:
    """`func.sum` devuelve `Decimal`, `float` o `None` según el dialecto y el atributo
    mapeado; nunca se opera en binario (mismo patrón que `universo_nomina._dec`)."""
    if valor is None:
        return _CERO
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


@dataclass(frozen=True, slots=True)
class _Percepciones:
    """El desglose de percepciones de un CFDI, ya repartido en las tres columnas de la ficha.

    `total` es la **suma de los nodos**, no `nomina.total_percepciones`: así las tres
    columnas suman exactamente la cuarta, que es lo que un financiador va a comprobar con
    una calculadora. Si el encabezado del complemento dice otra cosa, eso es un descuadre y
    se reporta como tal (`TOTALES_DESCUADRADOS`), no se disimula repartiendo la diferencia.
    """

    sueldos: Decimal = _CERO
    prestaciones: Decimal = _CERO
    asimilados: Decimal = _CERO

    @property
    def total(self) -> Decimal:
        return self.sueldos + self.prestaciones + self.asimilados


async def _percepciones_por_comprobante(db: AsyncSession, ids: list[int]) -> dict[int, _Percepciones]:
    """Sueldos (`001`), asimilados (`046`) y prestaciones (todo lo demás) por comprobante.

    Una sola consulta agregada por `(comprobante_id, tipo_percepcion)`; el reparto en las
    tres columnas se hace en Python porque es donde vive la regla —"prestaciones es lo que no
    es `001` ni `046`"— y escribirla como un `CASE` en SQL la escondería del lector.
    """
    if not ids:
        return {}
    filas = await db.execute(
        select(
            NominaPercepcion.comprobante_id,
            NominaPercepcion.tipo_percepcion,
            func.sum(NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento).label("importe"),
        )
        .where(NominaPercepcion.comprobante_id.in_(ids))
        .group_by(NominaPercepcion.comprobante_id, NominaPercepcion.tipo_percepcion)
    )
    por_comprobante: dict[int, _Percepciones] = {}
    for comprobante_id, tipo_percepcion, importe in filas.all():
        cid = int(comprobante_id)
        tipo = str(tipo_percepcion)
        monto = _dec(importe)
        actual = por_comprobante.get(cid, _Percepciones())
        if tipo == _CLAVE_PERCEPCION_SUELDOS:
            actual = _Percepciones(actual.sueldos + monto, actual.prestaciones, actual.asimilados)
        elif tipo == _CLAVE_PERCEPCION_ASIMILADOS:
            actual = _Percepciones(actual.sueldos, actual.prestaciones, actual.asimilados + monto)
        else:
            actual = _Percepciones(actual.sueldos, actual.prestaciones + monto, actual.asimilados)
        por_comprobante[cid] = actual
    return por_comprobante


@dataclass(frozen=True, slots=True)
class _Deducciones:
    """ISR y seguridad social obrera de un CFDI, más el total de todas sus deducciones (que
    solo se usa para cotejar el encabezado)."""

    isr: Decimal = _CERO
    imss: Decimal = _CERO
    total: Decimal = _CERO


async def _deducciones_por_comprobante(db: AsyncSession, ids: list[int]) -> dict[int, _Deducciones]:
    """ISR (`002`), seguridad social obrera (`001`) y total de deducciones por comprobante,
    en una sola consulta agregada."""
    if not ids:
        return {}
    filas = await db.execute(
        select(
            NominaDeduccion.comprobante_id,
            NominaDeduccion.tipo_deduccion,
            func.sum(NominaDeduccion.importe).label("importe"),
        )
        .where(NominaDeduccion.comprobante_id.in_(ids))
        .group_by(NominaDeduccion.comprobante_id, NominaDeduccion.tipo_deduccion)
    )
    por_comprobante: dict[int, _Deducciones] = {}
    for comprobante_id, tipo_deduccion, importe in filas.all():
        cid = int(comprobante_id)
        tipo = str(tipo_deduccion)
        monto = _dec(importe)
        actual = por_comprobante.get(cid, _Deducciones())
        por_comprobante[cid] = _Deducciones(
            isr=actual.isr + (monto if tipo == _CLAVE_DEDUCCION_ISR else _CERO),
            imss=actual.imss + (monto if tipo == _CLAVE_DEDUCCION_IMSS else _CERO),
            total=actual.total + monto,
        )
    return por_comprobante


@dataclass(frozen=True, slots=True)
class _OtrosPagos:
    """Los otros pagos de un CFDI: el total y, dentro de él, el subsidio para el empleo.

    `subsidio` **no** es un sumando aparte de `total`, es una parte suya. Tenerlos en el mismo
    objeto es lo que impide sumar dos veces el mismo peso al armar «Costo bruto».
    """

    total: Decimal = _CERO
    subsidio: Decimal = _CERO


async def _otros_pagos_por_comprobante(db: AsyncSession, ids: list[int]) -> dict[int, _OtrosPagos]:
    """Otros pagos por comprobante, en una sola consulta agregada por `(comprobante_id, tipo)`.

    El total incluye **todos** los tipos, no solo el subsidio: la ficha define «Otros pagos»
    como el nodo completo (viáticos, reintegros, ajustes). El desglose por tipo sale del mismo
    `GROUP BY` —no de una segunda consulta— y solo se usa para publicar el subsidio en su
    columna. Ver el docstring del módulo sobre por qué es aditivo y no una redefinición de
    «Costo bruto».
    """
    if not ids:
        return {}
    filas = await db.execute(
        select(
            NominaOtroPago.comprobante_id,
            NominaOtroPago.tipo_otro_pago,
            func.sum(NominaOtroPago.importe).label("importe"),
        )
        .where(NominaOtroPago.comprobante_id.in_(ids))
        .group_by(NominaOtroPago.comprobante_id, NominaOtroPago.tipo_otro_pago)
    )
    por_comprobante: dict[int, _OtrosPagos] = {}
    for comprobante_id, tipo_otro_pago, importe in filas.all():
        cid = int(comprobante_id)
        monto = _dec(importe)
        actual = por_comprobante.get(cid, _OtrosPagos())
        por_comprobante[cid] = _OtrosPagos(
            total=actual.total + monto,
            subsidio=actual.subsidio + (monto if str(tipo_otro_pago) == _CLAVE_OTRO_PAGO_SUBSIDIO else _CERO),
        )
    return por_comprobante


# --------------------------------------------------------------------------------------
# La acumulación por grupo
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Grupo:
    """Lo que se va sumando en una fila del informe.

    `empleados` es un conjunto de RFC y no un contador: dos CFDI del mismo trabajador en el
    mismo periodo —una quincena ordinaria y su finiquito, por ejemplo— son **un** empleado y
    **dos** CFDI, y contar recibos como personas inflaría la plantilla del centro de costo
    y hundiría el costo promedio.
    """

    rfc_empleado: str | None = None
    nombre_empleado: str | None = None
    num_empleado: str | None = None
    empleados: set[str] = field(default_factory=set)
    cfdi: int = 0
    dias: Decimal = _CERO
    sueldos: Decimal = _CERO
    prestaciones: Decimal = _CERO
    asimilados: Decimal = _CERO
    otros_pagos: Decimal = _CERO
    subsidio: Decimal = _CERO
    isr: Decimal = _CERO
    imss: Decimal = _CERO
    neto: Decimal = _CERO
    """«Neto pagado» es el único importe de la fila que **no** sale de los nodos: es la suma de
    `comprobantes.total`, el neto que el CFDI declara en su encabezado.

    Es procedencia mixta dentro de la misma fila y conviene saberlo: `TOTALES_DESCUADRADOS`
    coteja el encabezado del complemento contra sus nodos para percepciones, deducciones y otros
    pagos, pero **no** coteja `comprobantes.total` contra
    `percepciones + otros pagos − deducciones` — esa identidad no es de B-00 y este informe no la
    inventa. Se toma del encabezado a propósito, por consistencia con B-05 («Neto pagado» ahí es
    lo mismo) y porque es la cifra que el patrón depositó; si algún día no cuadra con los nodos,
    lo verá quien compare esta columna con las otras cinco, no una bandera."""

    @property
    def total_percepciones(self) -> Decimal:
        return self.sueldos + self.prestaciones + self.asimilados

    @property
    def costo_bruto(self) -> Decimal:
        return self.total_percepciones + self.otros_pagos

    @property
    def costo_promedio(self) -> Decimal:
        """Costo bruto entre el número de empleados del grupo.

        Sin empleados devuelve cero, no vacío (R-T7): un grupo sin RFC no puede existir
        —todo CFDI tiene receptor— pero un `None` ahí rompería cualquier suma de la hoja, y
        `Decimal("0")` aquí no es un valor inventado sino la ausencia de importe.
        """
        if not self.empleados:
            return _CERO
        return self.costo_bruto / Decimal(len(self.empleados))


# --------------------------------------------------------------------------------------
# Las banderas del agrupamiento
# --------------------------------------------------------------------------------------


def _bandera_de_calidad(conteo: Mapping[NivelDeResolucion, int], hay_mapeo: bool) -> Bandera:
    """`RESOLUCION_DE_CENTRO_DE_COSTO`: cuántos CFDI resolvió cada nivel de la cascada.

    Lo pide la ficha explícitamente y es lo que vuelve **auditable** el agrupamiento: sin
    este conteo, un total por centro de costo no dice qué parte salió de una configuración
    revisada y qué parte de un texto libre del sistema de nómina.

    **Se emite siempre, y es un reporte, no una alerta** (ver el docstring del módulo): por
    eso la severidad es `baja` y la clave es distinta de la de la alerta. Cuenta **CFDI**, no
    filas del informe: una fila agrega muchos comprobantes y decir "3 filas" cuando son 96
    recibos daría una idea equivocada del volumen revisado.
    """
    mapeo = conteo.get(NivelDeResolucion.MAPEO, 0)
    crudo = conteo.get(NivelDeResolucion.TEXTO_CRUDO, 0)
    ausente = conteo.get(NivelDeResolucion.AUSENTE, 0)
    total = mapeo + crudo + ausente
    estado_del_mapa = (
        "La empresa tiene `map_departamento` cargado."
        if hay_mapeo
        else "La empresa no tiene ningún renglón en `map_departamento`, así que el nivel 1 no pudo resolver nada."
    )
    return Bandera(
        clave="RESOLUCION_DE_CENTRO_DE_COSTO",
        severidad="baja",
        ambito="informe",
        mensaje=(
            f"Calidad del agrupamiento por centro de costo, sobre {total} CFDI: {mapeo} se resolvieron con el "
            f"mapeo de departamentos de la empresa (nivel 1), {crudo} con el texto crudo del departamento del "
            f"CFDI (nivel 2) y {ausente} no traen departamento. {estado_del_mapa} La cascada de la ficha tiene "
            "dos niveles y no tres: el primero se apoyaba en una plantilla de recursos humanos que este "
            "sistema no tiene."
        ),
    )


def _bandera_de_sin_mapeo(textos: Mapping[str, int], hay_mapeo: bool) -> Bandera:
    """`DEPARTAMENTO_SIN_MAPEO`, **una sola** para todo el informe, con el conteo de CFDI
    afectados y la lista de textos sin mapear.

    Agregada y no una por fila: es la lección del colapso de banderas de la fase 2. El ámbito
    es el informe porque la acción —capturar el mapeo— se hace una vez y cubre todos los
    casos a la vez.

    El mensaje trae los textos exactos porque son lo que hay que capturar; **nunca** un dato
    del trabajador. Un departamento es un dato de la organización, no personal.
    """
    afectados = sum(textos.values())
    ordenados = sorted(textos)
    muestra = ordenados[:MAX_TEXTOS_EN_BANDERA]
    cita = ", ".join(f"{texto!r} ({textos[texto]} CFDI)" for texto in muestra)
    recorte = "" if len(ordenados) == len(muestra) else f" (se citan {len(muestra)} de {len(ordenados)})"
    remedio = (
        "Complétalo en Configuración › Empresa › Departamentos"
        if hay_mapeo
        else "Captúralo en Configuración › Empresa › Departamentos (hoy la empresa no tiene ninguno)"
    )
    return Bandera(
        clave="DEPARTAMENTO_SIN_MAPEO",
        severidad="media",
        ambito="informe",
        mensaje=(
            f"{afectados} CFDI se agruparon por el texto crudo de su departamento porque no hay un centro de "
            f"costo mapeado para él: {len(ordenados)} texto(s) distinto(s){recorte} — {cita}. Mientras falte el "
            "mapeo, dos formas de escribir el mismo departamento salen como dos centros de costo distintos y "
            f"los totales no se pueden comparar entre periodos. {remedio}: la pantalla enumera los textos que "
            "la nómina emitió de verdad, no hay que teclearlos."
        ),
    )


def banderas_de_valores_configurados(mapa: Mapping[str, str]) -> list[Bandera]:
    """El otro lado del agrupamiento: el **valor** de `map_departamento.centro_costo`.

    Es texto libre sin catálogo (la pantalla es un `<input>`, el esquema solo exige
    `min_length=1`), así que dos formas de escribir el mismo centro producen dos centros de
    costo, **los dos contados como nivel 1**, y sin esta comprobación el censo diría "2 se
    resolvieron con el mapeo" sin una sola alerta: el informe se vería impecable con el gasto
    partido en dos. Es la asimetría que el resto del módulo no tenía — el lado del *texto del
    departamento* está instrumentado a fondo y el del *valor configurado* no tenía nada.

    Dos claves:

    - `CENTRO_DE_COSTO_AMBIGUO`: dos o más valores distintos que coinciden al plegarlos
      (`_plegar`). **Se reporta, no se unifica**, por la misma doctrina que el texto del
      departamento y con más motivo: declarar que dos centros son el mismo es un hecho contable
      y no puede salir de un parecido tipográfico que nadie revisó.
    - `CENTRO_DE_COSTO_EN_BLANCO`: la variante degenerada que `min_length=1` deja pasar (un
      espacio). Produce una fila cuya columna «Centro de costo» va en blanco y que se cuenta
      como nivel 1, es decir, como agrupamiento configurado y revisado.

    Los blancos se sacan de la comprobación de ambigüedad para no reportar el mismo renglón dos
    veces con dos diagnósticos: si hay dos centros en blanco, todos plegan a la cadena vacía y
    saldrían además como "ambiguos", cuando lo que hay que decir es que están vacíos.

    Se calcula **sobre el mapa completo**, no sobre las filas impresas: una configuración
    ambigua es un defecto de configuración aunque en este rango no haya cobrado nadie de esos
    departamentos, se arregla una vez y sirve para todos los rangos. Es el mismo criterio que
    `b03_gravado_exento._avisos_de_tope_conjunto_sin_evaluar` aplica a lo que no cuelga de una
    fila.
    """
    banderas: list[Bandera] = []

    en_blanco = sorted(texto for texto, centro in mapa.items() if not centro.strip())
    if en_blanco:
        banderas.append(
            Bandera(
                clave="CENTRO_DE_COSTO_EN_BLANCO",
                severidad="media",
                ambito="informe",
                mensaje=(
                    f"{len(en_blanco)} departamento(s) están mapeados a un centro de costo vacío o en blanco: "
                    f"{', '.join(repr(texto) for texto in en_blanco)}. La captura solo exige un carácter, así que "
                    "un espacio pasa: su costo sale en una fila con la columna «Centro de costo» en blanco y "
                    "contada como agrupamiento configurado. Corrige el mapeo en Configuración › Empresa › "
                    "Departamentos."
                ),
            )
        )

    por_forma: dict[str, set[str]] = defaultdict(set)
    for centro in mapa.values():
        if centro.strip():
            por_forma[_plegar(centro)].add(centro)

    for forma in sorted(por_forma):
        variantes = sorted(por_forma[forma])
        if len(variantes) < 2:
            continue
        departamentos = sorted(texto for texto, centro in mapa.items() if centro in set(variantes))
        banderas.append(
            Bandera(
                clave="CENTRO_DE_COSTO_AMBIGUO",
                severidad="media",
                ambito="informe",
                mensaje=(
                    f"El mapeo de departamentos tiene {len(variantes)} centros de costo que solo se distinguen "
                    f"por mayúsculas, acentos o espacios: {', '.join(repr(v) for v in variantes)} "
                    f"(departamentos afectados: {', '.join(repr(d) for d in departamentos)}). El informe los trata "
                    "como centros **distintos** y los cuenta a los dos como agrupamiento configurado, así que el "
                    "gasto de lo que probablemente es un solo centro sale partido en varias filas sin que nada más "
                    "lo advierta. No se unifican a propósito: decidir que dos centros son el mismo es una decisión "
                    "contable, no tipográfica. Deja un solo texto en Configuración › Empresa › Departamentos."
                ),
            )
        )
    return banderas


def _bandera_de_departamento_ausente(cuantos: int) -> Bandera:
    """`DEPARTAMENTO_AUSENTE`, agregada: CFDI cuyo complemento no trae departamento.

    No es el nivel 2 de la cascada con otro nombre: ahí hay un texto que capturar y aquí no
    hay nada que mapear —`departamento_texto` va en la PK de `map_departamento`, así que
    `cfg.observados_de_empresa` ni siquiera lo enumera—. El arreglo no está en la
    configuración sino en el sistema de nómina que timbra, y decir "captura el mapeo"
    mandaría a una pantalla donde ese renglón no puede existir.
    """
    return Bandera(
        clave="DEPARTAMENTO_AUSENTE",
        severidad="media",
        ambito="informe",
        mensaje=(
            f"{cuantos} CFDI no traen el nodo `Departamento` en el complemento de nómina, así que su costo no "
            f"se puede atribuir a ningún centro: se agrupó aparte, bajo «{SIN_DEPARTAMENTO}». No se arregla con "
            "el mapeo de departamentos —no hay texto que mapear—, sino en el sistema de nómina que timbra: el "
            "nodo es opcional para el SAT y obligatorio para poder comprobar el gasto por centro de costo."
        ),
    )


# --------------------------------------------------------------------------------------
# La consulta
# --------------------------------------------------------------------------------------


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    columnas = _columnas(p.detalle_empleado)
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=columnas, notas=list(_NOTAS), aviso="La empresa no existe.")

    p_universo = _ParametrosUniverso(p.fecha_desde, p.fecha_hasta, p.incluir_cancelados)
    filas_universo = list((await db.execute(universo_nomina.universo(empresa_id, rfc_empresa, p_universo))).all())
    # Se resuelve ANTES del retorno temprano: si el ETL falló en todos los CFDI del rango,
    # estas banderas son el único rastro de que había nómina que reportar (§9 del diseño).
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, rfc_empresa, p_universo)

    if not filas_universo:
        # Las notas también viajan cuando no hay filas: un libro vacío circula igual, y una nota
        # califica cómo leer la columna, no esta corrida (ver `ResultadoInforme.notas`).
        return ResultadoInforme(
            columnas=columnas,
            banderas=banderas_fuera,
            notas=list(_NOTAS),
            aviso="Sin CFDI de nómina en el rango solicitado.",
        )

    ids = [fila[0].comprobante_id for fila in filas_universo]
    percepciones = await _percepciones_por_comprobante(db, ids)
    deducciones = await _deducciones_por_comprobante(db, ids)
    otros_pagos = await _otros_pagos_por_comprobante(db, ids)
    mapa = await cfg.centro_de_costo(db, empresa_id)

    banderas: list[Bandera] = list(banderas_fuera)
    banderas.extend(universo_nomina.banderas_de_estatus(universo_nomina.comprobantes_y_detalles(filas_universo)))
    # El otro lado del agrupamiento (el **valor** configurado), sobre el mapa completo y antes
    # de recorrer el universo: no depende de qué filas se impriman.
    banderas.extend(banderas_de_valores_configurados(mapa))

    # El `bool` de la llave marca "venía sin departamento" y es la guarda de `SIN_DEPARTAMENTO`
    # (ver su docstring): sin él, un centro de costo llamado igual que ese rótulo se fundiría
    # con el grupo de los ausentes mientras se cuenta en otro nivel del censo.
    grupos: dict[tuple[int, int, str, bool, str], _Grupo] = {}
    # Insumos de las banderas del agrupamiento. Se cuentan sobre el universo de CFDI y no
    # sobre las filas impresas, para que ningún aviso dependa de que se imprima una fila.
    conteo_por_nivel: dict[NivelDeResolucion, int] = defaultdict(int)
    textos_sin_mapeo: dict[str, int] = defaultdict(int)

    for comprobante, nomina, receptor, _totales, detalle in filas_universo:
        fecha_pago = nomina.fecha_pago
        if fecha_pago is None:
            # Inalcanzable a través de `universo()`, que filtra por `nomina.fecha_pago` y por
            # tanto excluye los nulos. Se conserva para que el tipo case sin un `assert`.
            continue

        # B-06.R1 y B-06.R3: el departamento que declara **este** CFDI, nunca el actual del
        # empleado. Ver el docstring del módulo sobre por qué no se retropropaga.
        departamento = receptor.departamento if receptor is not None else None
        resuelto = resolver_centro_de_costo(departamento, mapa)
        conteo_por_nivel[resuelto.nivel] += 1
        if resuelto.nivel is NivelDeResolucion.TEXTO_CRUDO:
            textos_sin_mapeo[resuelto.centro] += 1

        rfc_empleado = comprobante.rfc_receptor
        llave = (
            fecha_pago.year,
            fecha_pago.month,
            resuelto.centro,
            resuelto.nivel is NivelDeResolucion.AUSENTE,
            rfc_empleado if p.detalle_empleado else "",
        )
        grupo = grupos.setdefault(llave, _Grupo())
        if p.detalle_empleado:
            grupo.rfc_empleado = rfc_empleado
            # El primer valor no nulo del orden determinista de `universo()` (fecha de pago,
            # después `comprobante_id`): el nombre y el número de empleado pueden variar entre
            # recibos del mismo trabajador y hay que elegir uno de forma estable.
            if grupo.nombre_empleado is None and detalle is not None:
                grupo.nombre_empleado = detalle.nombre_receptor
            if grupo.num_empleado is None and receptor is not None:
                grupo.num_empleado = receptor.num_empleado

        cid = comprobante.comprobante_id
        del_cfdi = percepciones.get(cid, _Percepciones())
        deduccion = deducciones.get(cid, _Deducciones())
        otro = otros_pagos.get(cid, _OtrosPagos())

        grupo.empleados.add(rfc_empleado)
        grupo.cfdi += 1
        grupo.dias += _dec(nomina.num_dias_pagados)
        grupo.sueldos += del_cfdi.sueldos
        grupo.prestaciones += del_cfdi.prestaciones
        grupo.asimilados += del_cfdi.asimilados
        grupo.otros_pagos += otro.total
        grupo.subsidio += otro.subsidio
        grupo.isr += deduccion.isr
        grupo.imss += deduccion.imss
        grupo.neto += _dec(comprobante.total)

        # Los tres totales del encabezado del complemento contra la suma de sus nodos
        # (identidades #1, #2 y #3 de B-00). Aquí no es un lujo: las columnas de este informe
        # salen de los **nodos**, así que un encabezado que diga otra cosa produciría un costo
        # por centro distinto del que da B-01/B-02 para el mismo periodo, sin una sola señal.
        banderas.extend(
            universo_nomina.banderas_de_totales_descuadrados(
                f"uuid:{comprobante.uuid}",
                (
                    ("total_percepciones", nomina.total_percepciones, del_cfdi.total),
                    ("total_deducciones", nomina.total_deducciones, deduccion.total),
                    ("total_otros_pagos", nomina.total_otros_pagos, otro.total),
                ),
            )
        )

    # El denominador del porcentaje: el costo bruto de **todo** el periodo, sumando los
    # centros de costo. Con `detalle_empleado` el denominador no cambia, así que las filas de
    # un periodo siguen sumando 100.
    total_por_periodo: dict[tuple[int, int], Decimal] = defaultdict(lambda: _CERO)
    for (ejercicio, periodo, _centro, _ausente, _rfc), grupo in grupos.items():
        total_por_periodo[(ejercicio, periodo)] += grupo.costo_bruto

    filas: list[list[Any]] = []
    for llave in sorted(grupos):
        ejercicio, periodo, centro, _ausente, _rfc = llave
        grupo = grupos[llave]
        identidad: list[Any] = [ejercicio, periodo, centro]
        if p.detalle_empleado:
            identidad += [grupo.rfc_empleado, grupo.nombre_empleado, grupo.num_empleado]
        filas.append(
            identidad
            + [
                len(grupo.empleados),
                grupo.cfdi,
                grupo.dias,
                grupo.sueldos,
                grupo.prestaciones,
                grupo.asimilados,
                grupo.total_percepciones,
                grupo.otros_pagos,
                grupo.subsidio,
                grupo.costo_bruto,
                grupo.isr,
                grupo.imss,
                grupo.neto,
                grupo.costo_promedio,
                _porcentaje(grupo.costo_bruto, total_por_periodo[(ejercicio, periodo)]),
            ]
        )

    banderas.append(_bandera_de_calidad(conteo_por_nivel, bool(mapa)))
    if textos_sin_mapeo:
        banderas.append(_bandera_de_sin_mapeo(textos_sin_mapeo, bool(mapa)))
    if conteo_por_nivel.get(NivelDeResolucion.AUSENTE, 0):
        banderas.append(_bandera_de_departamento_ausente(conteo_por_nivel[NivelDeResolucion.AUSENTE]))

    return ResultadoInforme(columnas=columnas, filas=filas, banderas=banderas, notas=list(_NOTAS))


def _porcentaje(parte: Decimal, total: Decimal) -> Decimal:
    """Peso del grupo sobre el costo bruto del periodo, en escala 0-100.

    Con total cero devuelve cero y no vacío (R-T7): un periodo cuyo costo bruto es cero
    —todo el gasto en descuentos, o un periodo con puros CFDI en ceros— no tiene un
    porcentaje "por capturar", tiene un porcentaje que no existe, y un hueco ahí rompería
    la suma de la columna en la hoja de cálculo.

    **Sin `quantize()`**: el único redondeo del sistema es el de `app.informes.excel` (R-T4).
    Y ojo con su consecuencia aquí: `excel._celda` solo cuantiza las columnas de tipo `monto`,
    así que esta celda guarda el cociente con los 28 dígitos significativos del contexto de
    `Decimal` y solo el formato de la hoja (`#,##0.000`) los oculta. Es lo correcto —redondear
    en el informe sería el error que R-T4 prohíbe— pero quien lea el archivo con otra
    herramienta verá el número largo.
    """
    if total == _CERO:
        return _CERO
    return parte * _CIEN / total
