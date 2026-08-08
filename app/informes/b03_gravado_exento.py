"""B-03 · Desglose gravado / exento por percepción (§B-03 del documento fuente).

Grano: **una fila por nodo de percepción** (formato largo, no pivotado, al revés que B-02).
Verifica la aplicación de las exenciones del **artículo 93 de la LISR** concepto por
concepto: es lo que la autoridad reconstruye para determinar diferencias de ISR de nómina.

Es el primer informe que consume la configuración fiscal de la fase 3 (`param_fiscal` y
`catalogo_percepcion_marca`), y casi todo lo delicado de este módulo está en **cómo degrada
cuando esa configuración todavía no está confirmada**, que hoy es el caso normal: la
instalación real tiene 5 parámetros y 44 marcas, todos propuestos y ninguno confirmado.

El invariante heredado: **un valor sin confirmar no calcula**
--------------------------------------------------------------
`valor_vigente` y `marcas_de_percepcion` devuelven solo lo confirmado. Este informe traduce
esa ausencia en **columnas vacías, nunca en ceros** — un cero en un tope de exención produce
exenciones falsas, que es el error más caro que puede cometer— y en una bandera que dice qué
hacer, distinguiendo los tres estados:

- **Confirmado** → calcula.
- **Propuesto sin confirmar** → columna vacía y bandera con la **fuente** de la propuesta:
  el arreglo es un clic (`UMA_SIN_CONFIRMAR`, `MARCA_SIN_CONFIRMAR`).
- **Ausente** → columna vacía y bandera que dice qué capturar (`FALTA_UMA`, `FALTA_MARCA`,
  `FALTA_ZONA_SALARIAL`).

**El invariante gobierna los cálculos, no las advertencias**, y confundir las dos cosas costó
tres defectos seguidos en este módulo, los tres del mismo tipo: apagar en silencio una
comprobación por faltar un dato **que esa comprobación no usa**. La regla general, escrita
aquí para que no haya una cuarta: antes de condicionar algo a que un valor esté confirmado,
pregúntate si ese algo *usa* el valor. Sumar importes exentos contra `UMA_ANUAL` no usa
`factor_exencion`; decidir si hay que avisar no usa nada. Ver
`tipos_que_podrian_estar_sujetos_al_tope_conjunto`.

**Una bandera por causa, con el conteo de filas afectadas; nunca una por fila.** Es la
lección del colapso de banderas de la fase 2 (`universo_nomina._banderas_de_no_verificado`):
si faltan la UMA y 300 filas la necesitan, una hoja `Banderas` con 300 avisos idénticos
sepulta los hallazgos de auditoría —`EXENCION_INDEBIDA`, `EXENCION_EXCEDIDA`— que son lo
accionable. Aquí el ámbito de cada bandera de configuración es el informe o el tipo de
percepción, no el UUID.

Los tres límites del modelo de marcas, y qué hace cada uno
-------------------------------------------------------------
Salieron de la tarea 3, al derivar las 44 marcas contra el texto oficial de la LISR.
Ignorarlos hace que el informe **exente de más**.

1. **El tope conjunto de previsión social** (penúltimo párrafo del art. 93): la *suma* de
   esas exenciones se limita a 1 UMA anual por trabajador y por año. No es un factor por
   tipo —los seis afectados llevan `PORCENTAJE 100`, la exención en bruto—, así que se
   aplica **aparte**, sobre el acumulado anual (`_banderas_de_tope_conjunto`). Cuáles son
   esos seis **lo dice el dato**: la columna `catalogo_percepcion_marca.sujeto_a_tope_conjunto`
   existe justo para eso. Llevar la lista escrita aquí sería una lista fiscal codificada en
   el programa, que es lo que prohíbe el §2.12 — y además dejaría de valer en cuanto una
   reforma moviera un tipo de lado.

2. **Factores cuyo multiplicador no viene en el CFDI.** Nueve tipos capturan el número de la
   ley pero no el multiplicador: "90 UMA **por año de servicio**" (022, 023, 025, 039, 053),
   "15 UMA **diarias**" (044, 051, 052) y "1 UMA **por domingo laborado**" (020). Calcular
   `factor × UMA` ahí supone un multiplicador de 1 y produce un tope muy por debajo del
   legal, que el informe presentaría como un exceso del patrón que no existe.

   **Cómo se resuelve hoy, y su límite.** Los nueve declaran esa advertencia en
   `catalogo_percepcion_marca.nota_revision`, que sí es un campo de la base y cuyo
   significado documentado es exactamente "el valor podría estar mal" (ver el modelo). Así
   que la regla de este informe es **una marca con duda declarada abierta no calcula su tope
   por tipo**: columna vacía y `MARCA_CON_DUDA_DECLARADA`, la misma forma de degradar que con
   la UMA, y **citando la nota** en vez de suponer cuál es la duda (39 de las 44 la traen y
   solo nueve por este motivo). Es deliberadamente conservadora, pero nunca publica un tope
   calculado con un multiplicador supuesto y no codifica ninguna lista fiscal. Los cinco tipos
   sin duda (`001`, `002`, `003`, `021`, `028`) son justamente los de la nómina cotidiana, así
   que el informe sí calcula donde se usa a diario.

   **Lo que la duda NO puede apagar, y costó dos defectos:** solo bloquea lo que depende del
   factor. No bloquea el tope de un `NINGUNA` —que no tiene factor: su cero es un hecho—, ni
   el tope conjunto del punto 1 —que suma `importe_exento` contra `UMA_ANUAL` sin tocar el
   factor—. Alimentar el tope conjunto de las filas cuyo tope por tipo se había podido
   calcular dejaba **inerte** esa comprobación para los seis tipos afectados, porque los seis
   traen nota en la semilla real: el 100% del catálogo de producción, y sin bandera que lo
   dijera. Ver `_banderas_de_tope_conjunto` y el orden de comprobaciones de `_tope_de_fila`.

   **Su residuo, declarado:** si alguien resuelve la duda de un tipo del grupo C y le borra
   la nota sin corregir el modelo, el tope por tipo volvería a calcularse con el multiplicador
   supuesto. El arreglo preciso es una columna propia —`multiplicador_no_derivable`, el
   mismo remedio que ya se aplicó dos veces en esta fase con `sujeto_a_tope_conjunto` y
   `nota_revision`—, que exige migración, semilla y pantalla de confirmación, y por eso no
   cabe en esta tarea: es la tarea 7b.

3. **Las vacaciones no tienen tipo propio** en `c_TipoPercepcion`: se pagan dentro del `001`.
   Ninguna marca de este catálogo las identifica, así que B-03 **no intenta distinguirlas**;
   lo que dependa de ello sale de `map_concepto_provision`, por organización (B-06/B-08).

Las tres reglas de la ficha
------------------------------
- **B-03.R1** — el tope se resuelve por tipo según `base_exencion` y `factor_exencion`, con
  la UMA vigente **a la fecha de pago** (`_tope_de_fila`). Con `PORCENTAJE`, `factor_exencion`
  está en **escala 0-100**, no como fracción: tratarlo como fracción exenta cien veces de
  menos. Con `SM_DIAS` se usa `salario_minimo_de_empresa`, que devuelve `None` sin mirar los
  valores cuando la zona no está configurada — el mínimo de la Zona Libre de la Frontera
  Norte y el general se llevan casi un 40%, y no hay valor por omisión.
- **B-03.R2** — el tope se evalúa contra el **acumulado del ejercicio** del mismo empleado y
  tipo, no contra el importe del periodo (`_acumulado_anual`, una sola consulta agregada).
  Es la regla que hace útil el informe: periodo por periodo casi nunca se excede.
- **B-03.R3** — `base_exencion = NINGUNA` con `importe_exento > 0` es `EXENCION_INDEBIDA`.

**Sustituciones: la misma regla que B-05.R1, y por la misma razón.** Un CFDI de nómina
corregido por sustitución deja dos comprobantes con **el mismo pago**. Como B-03.R2 acumula por
`(rfc, tipo, ejercicio)`, contarlos los dos duplicaba el exento anual y el informe emitía una
`EXENCION_EXCEDIDA` —severidad **alta**, un hallazgo de auditoría— **acusando al patrón de un
exceso que no existe**; y la hoja `Datos` imprimía dos filas para un solo pago, así que sumar
su columna de exento daba el doble. El daño es solo en esa dirección (nunca deja pasar un
exceso real: con base `PORCENTAJE` el tope anual se duplica igual y la razón se conserva, así
que se concentra en `UMA_DIAS`/`SM_DIAS`, donde está el aguinaldo). Se resuelve con
`universo_nomina.uuids_sustituidos`, **siempre** y sobre el **ejercicio completo**, en las dos
superficies —filas y acumulado— y con bandera `CFDI_SUSTITUIDO` para que la exclusión no sea
silenciosa. El filtro por `estatus` no sustituye a esto: la verificación contra el SAT es
asíncrona, así que el sustituido normalmente está `no_verificado`, no `cancelado`.

**Ningún importe fiscal vive en este archivo** (§2.12): la UMA, el salario mínimo y los
factores salen de `param_fiscal` y de `catalogo_percepcion_marca`, resueltos por fecha.
**Ningún redondeo, tampoco** (R-T4): `Decimal` de punta a punta y el único `ROUND_HALF_UP`
del sistema está en `app.informes.excel`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Select, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import catalogos, universo_nomina
from app.informes.base import Bandera, Columna, ResultadoInforme
from app.models.comprobante import Comprobante
from app.models.configuracion_fiscal import CatalogoPercepcionMarca
from app.models.empresa import Empresa
from app.models.enums import BaseExencion, EstatusCfdi
from app.models.nomina import Nomina, NominaPercepcion
from app.services import configuracion_fiscal as cfg

CLAVE = "B-03"
NOMBRE = "Desglose gravado / exento por percepción"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por nodo de percepción, con el tope de exención del artículo 93 de la LISR que "
    "corresponde a cada tipo y el exceso sobre ese tope. Es el papel de trabajo con el que se "
    "revisa concepto por concepto si las exenciones están bien aplicadas."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Tipos de comprobante que este informe necesita normalizados (todo el grupo B: solo `N`).
Lo consume el pre-vuelo del ETL (`app.worker.tasks._generar_informe_async`); ver la constante
homónima de `b02_conceptos_patron` para el argumento completo."""

_CERO = Decimal("0")
_CIEN = Decimal("100")
_TOLERANCIA = universo_nomina.TOLERANCIA

MUESTRA_UUID = 3
"""Cuántos UUID se citan en el mensaje de una bandera colapsada por tipo. No es cero —quien
la lee necesita por dónde empezar— y no son todos: el mensaje dice cuántos hay en total.
Mismo criterio que `universo_nomina.MUESTRA_UUID_COLAPSO`."""

_MAX_NOTA_EN_BANDERA = 240
"""Cuánto de `nota_revision` se cita en `MARCA_CON_DUDA_DECLARADA`. Las notas de la semilla
llegan a pasar de 780 caracteres y son párrafos con subpuntos: entero, el mensaje deja de ser
legible en una celda. Se cita la **primera línea** recortada a esto, que es donde la semilla
pone el enunciado de la duda, y el texto completo sigue estando en la pantalla de marcas."""


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango, sobre `nomina.fecha_pago` (R-T6).")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    tipo_percepcion: str | None = Field(
        None,
        description=(
            "Clave de `c_TipoPercepcion` a la que acotar las filas (p. ej. '002' para revisar solo "
            "el aguinaldo). Va como texto: los ceros a la izquierda son significativos. Vacío = todas."
        ),
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
    """Adaptador local a `universo_nomina.ParametrosUniverso`. B-03 no expone `tipo_nomina`,
    y no es un olvido: el aguinaldo —el caso de exención anual por excelencia— se suele pagar
    en una nómina **extraordinaria**, así que filtrar por tipo escondería justo las filas que
    este informe existe para revisar. Mismo patrón que
    `b10_validacion_receptor._ParametrosUniverso`."""

    fecha_desde: date
    fecha_hasta: date
    incluir_cancelados: bool
    tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"


_COLUMNAS: tuple[tuple[str, str, bool], ...] = (
    ("UUID", "texto", False),
    ("Fecha pago", "fecha", False),
    ("Ejercicio", "entero", False),
    ("Periodo", "entero", False),
    ("RFC empleado", "texto", False),
    ("Nombre empleado", "texto", False),
    ("CURP", "texto", True),
    ("NSS", "texto", True),
    ("Núm. empleado", "texto", False),
    ("Departamento", "texto", False),
    ("Puesto", "texto", False),
    ("Días pagados", "decimal", False),
    ("Tipo percepción", "texto", False),
    ("Descripción SAT", "texto", False),
    ("Clave patrón", "texto", False),
    ("Concepto patrón", "texto", False),
    ("Importe gravado", "monto", False),
    ("Importe exento", "monto", False),
    ("Importe total", "monto", False),
    ("% exento", "decimal", False),
    # Las cuatro dependientes de configuración. Salen vacías —nunca cero— cuando el valor del
    # que dependen no está disponible, y cada causa deja **una** bandera con su conteo.
    ("Base de exención", "texto", False),
    ("Tope de exención", "monto", False),
    ("Exceso sobre el tope", "monto", False),
    ("UMA aplicable", "monto", False),
)


def _columnas() -> list[Columna]:
    return [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS]  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Configuración fiscal, resuelta una sola vez para todas las fechas que hacen falta
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Configuracion:
    """Los insumos de `param_fiscal` y `catalogo_percepcion_marca` ya resueltos.

    Se resuelven **por fecha de pago distinta**, no por fila: una quincena tiene una sola
    fecha de pago y un ejercicio completo tiene ~26, así que el número de consultas queda
    acotado por el calendario y no por el volumen de nómina (regla 11). Las marcas son dos
    consultas en total, pase lo que pase.
    """

    marcas: dict[str, CatalogoPercepcionMarca]
    marcas_propuestas: dict[str, CatalogoPercepcionMarca]
    uma: dict[date, Decimal | None]
    uma_propuesta: dict[date, cfg.ValorFiscal | None]
    salario_minimo: dict[date, Decimal | None]
    salario_minimo_propuesto: dict[date, cfg.ValorFiscal | None]
    zona_configurada: bool
    uma_anual: dict[int, Decimal | None]
    uma_anual_propuesta: dict[int, cfg.ValorFiscal | None]


async def _configuracion(db: AsyncSession, empresa_id: int, fechas: set[date], ejercicios: set[int]) -> _Configuracion:
    """Trae todo lo que el informe necesita de la configuración fiscal.

    Las fechas de cierre de ejercicio (`31-dic`) entran en el mismo conjunto que las fechas
    de pago: los topes **anuales** de B-03.R2 se resuelven con el valor vigente al cierre del
    ejercicio, que es el que corresponde a una cifra anual, mientras que el tope que se
    imprime en cada fila usa el valor vigente a su fecha de pago (B-03.R1). Cuando el
    ejercicio tiene un solo tramo de UMA —el caso normal— los dos coinciden.

    **El salario mínimo se resuelve con la zona en la mano, no con `salario_minimo_de_empresa`
    por fecha**, y eso hace dos cosas a la vez:

    1. Distingue los tres estados. `salario_minimo_de_empresa` devuelve `Decimal | None` y
       colapsa "no hay valor" con "hay uno esperando confirmación", así que con ella el informe
       no podía decir "es un clic" — que es la premisa de toda la interfaz de confirmación de
       esta fase. Con `clave_de_salario_minimo` se resuelven `valor_vigente` y `valor_propuesto`
       igual que con la UMA.
    2. Ahorra una consulta por fecha: esa función vuelve a leer `configuracion_empresa` en cada
       llamada, y aquí ya está leída una vez arriba.

    Lo que **no** se duplica es la decisión de negocio que encapsula esa función: *sin zona
    configurada no hay valor y no se mira ningún renglón*. Aquí se respeta por construcción —si
    `zona is None` no se consulta ninguna clave— y la causa que sale es `FALTA_ZONA_SALARIAL`,
    que es una acción distinta (configurar la empresa, no capturar un valor).
    """
    config_empresa = await cfg.configuracion_de_empresa(db, empresa_id)
    zona = config_empresa.zona_salarial if config_empresa is not None else None
    clave_minimo = cfg.clave_de_salario_minimo(zona) if zona is not None else None

    uma: dict[date, Decimal | None] = {}
    uma_propuesta: dict[date, cfg.ValorFiscal | None] = {}
    salario_minimo: dict[date, Decimal | None] = {}
    salario_minimo_propuesto: dict[date, cfg.ValorFiscal | None] = {}
    for fecha in sorted(fechas):
        uma[fecha] = await cfg.valor_vigente(db, "UMA_DIARIA", fecha)
        uma_propuesta[fecha] = None if uma[fecha] is not None else await cfg.valor_propuesto(db, "UMA_DIARIA", fecha)
        if clave_minimo is None:
            salario_minimo[fecha] = None
            salario_minimo_propuesto[fecha] = None
            continue
        salario_minimo[fecha] = await cfg.valor_vigente(db, clave_minimo, fecha)
        salario_minimo_propuesto[fecha] = (
            None if salario_minimo[fecha] is not None else await cfg.valor_propuesto(db, clave_minimo, fecha)
        )

    uma_anual: dict[int, Decimal | None] = {}
    uma_anual_propuesta: dict[int, cfg.ValorFiscal | None] = {}
    for ejercicio in sorted(ejercicios):
        cierre = date(ejercicio, 12, 31)
        uma_anual[ejercicio] = await cfg.valor_vigente(db, "UMA_ANUAL", cierre)
        uma_anual_propuesta[ejercicio] = (
            None if uma_anual[ejercicio] is not None else await cfg.valor_propuesto(db, "UMA_ANUAL", cierre)
        )

    return _Configuracion(
        marcas=await cfg.marcas_de_percepcion(db),
        marcas_propuestas=await cfg.marcas_propuestas(db),
        uma=uma,
        uma_propuesta=uma_propuesta,
        salario_minimo=salario_minimo,
        salario_minimo_propuesto=salario_minimo_propuesto,
        zona_configurada=zona is not None,
        uma_anual=uma_anual,
        uma_anual_propuesta=uma_anual_propuesta,
    )


# --------------------------------------------------------------------------------------
# B-03.R1: el tope de una fila, o la razón por la que no se pudo calcular
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Tope:
    """El tope resuelto, o `None` con la clave de la bandera que explica el hueco.

    Nunca las dos cosas, y nunca ninguna: un tope sin valor y sin causa sería un hueco mudo,
    que es exactamente lo que este informe no puede producir.
    """

    valor: Decimal | None
    causa: str | None


def _tope_de_fila(
    marca: CatalogoPercepcionMarca | None,
    propuesta: CatalogoPercepcionMarca | None,
    uma: Decimal | None,
    hay_propuesta_de_uma: bool,
    salario_minimo: Decimal | None,
    hay_propuesta_de_salario_minimo: bool,
    zona_configurada: bool,
    hay_fecha_de_pago: bool,
    importe_total: Decimal,
) -> _Tope:
    """B-03.R1. `factor_exencion` con `PORCENTAJE` está en **escala 0-100**, no en fracción
    (ver la columna en `app/models/configuracion_fiscal.py`): dividir entre 100 aquí es lo
    que impide exentar cien veces de menos.

    **El orden de las comprobaciones es parte de la regla.** Cada una solo puede bloquear lo
    que de verdad depende del dato que falta:

    - Sin marca no hay ni base ni factor: no se puede decir nada.
    - `NINGUNA` va **antes** que la duda declarada porque no tiene factor —`factor_exencion`
      es `NULL` y el cargador lo exige así—, luego no hay nada que la duda pueda invalidar.
      Su tope es cero de verdad, no un cero por ausencia, y vaciarlo escondería el hallazgo
      de B-03.R3 tras una celda en blanco.
    - La duda declarada bloquea solo lo que sale del factor (ver el límite 2 del docstring del
      módulo). **No bloquea el tope conjunto**, que no usa el factor: eso se decide fuera de
      esta función, en `_banderas_de_tope_conjunto`.
    - La fecha de pago se comprueba dentro de las dos bases que la necesitan para resolver su
      valor por vigencia. `PORCENTAJE` no la necesita, y decir "falta la UMA" cuando lo que
      falta es la fecha manda a configurar algo que quizá ya está configurado.
    """
    if marca is None:
        return _Tope(None, "MARCA_SIN_CONFIRMAR" if propuesta is not None else "FALTA_MARCA")

    base = marca.base_exencion
    if base is BaseExencion.NINGUNA:
        return _Tope(_CERO, None)

    if marca.nota_revision:
        return _Tope(None, "MARCA_CON_DUDA_DECLARADA")

    factor = marca.factor_exencion
    if factor is None:
        # El cargador y el endpoint lo impiden (`base_exencion` distinta de NINGUNA exige
        # factor), así que esto solo puede llegar de un `UPDATE` a mano sobre la tabla.
        return _Tope(None, "MARCA_SIN_FACTOR")

    if base is BaseExencion.PORCENTAJE:
        return _Tope(factor * importe_total / _CIEN, None)
    if not hay_fecha_de_pago:
        # Inalcanzable a través de `universo()`, que filtra por `nomina.fecha_pago` y por
        # tanto excluye los nulos. Se conserva para que la causa esté bien atribuida si algún
        # día otro universo llama a esta función: sin fecha no hay vigencia que resolver, y
        # eso no es un hueco de configuración.
        return _Tope(None, "SIN_FECHA_DE_PAGO")
    if base is BaseExencion.UMA_DIAS:
        if uma is None:
            return _Tope(None, "UMA_SIN_CONFIRMAR" if hay_propuesta_de_uma else "FALTA_UMA")
        return _Tope(factor * uma, None)
    if salario_minimo is None:
        # Tres estados, tres acciones distintas: configurar la zona de la empresa, capturar el
        # valor, o confirmar el que ya está capturado. Colapsar los dos últimos convertía "es un
        # clic" en "ve a buscar el dato", que es justo la distinción que la interfaz de
        # confirmación de esta fase existe para poder hacer.
        if not zona_configurada:
            return _Tope(None, "FALTA_ZONA_SALARIAL")
        if hay_propuesta_de_salario_minimo:
            return _Tope(None, "SALARIO_MINIMO_SIN_CONFIRMAR")
        return _Tope(None, "FALTA_SALARIO_MINIMO")
    return _Tope(factor * salario_minimo, None)


# --------------------------------------------------------------------------------------
# B-03.R2: el acumulado del ejercicio, en una sola consulta
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Acumulado:
    exento: Decimal
    total: Decimal


def _nomina_del_ejercicio(empresa_id: int, rfc_empresa: str, ejercicios: set[int]) -> Select[Any]:
    """Los `comprobante_id` de la nómina de la empresa en esos ejercicios, **sin filtro de
    estatus**: es el alcance en el que se buscan los sustitutos.

    Deliberadamente más ancho que el universo del informe, en las dos direcciones. Todo el
    ejercicio, porque el acumulado que hay que proteger es anual (una sustitución de enero
    envenena el tope anual de un informe de junio). Y sin mirar el estatus, porque la relación
    `tipo_relacion='04'` es un hecho del XML del sustituto: sigue siendo cierta que reemplazó a
    otro comprobante aunque el sustituto acabe cancelado a su vez.
    """
    return (
        select(Comprobante.comprobante_id)
        .join(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
        .where(
            Comprobante.empresa_id == empresa_id,
            Comprobante.rfc_emisor == rfc_empresa,
            Comprobante.tipo_comprobante == "N",
            extract("year", Nomina.fecha_pago).in_(sorted(ejercicios)),
        )
    )


async def _acumulado_anual(
    db: AsyncSession,
    empresa_id: int,
    rfc_empresa: str,
    ejercicios: set[int],
    tipos: set[str],
    incluir_cancelados: bool,
    sustituidos: set[str],
) -> dict[tuple[str, str, int], _Acumulado]:
    """Suma anual de exento y de importe total por `(rfc_receptor, tipo_percepcion, ejercicio)`.

    **Una consulta para todo el informe** (regla 11), y **sobre el ejercicio completo, no
    sobre el rango**: el tope del art. 93 es anual, así que un aguinaldo pagado en enero
    cuenta para el informe de junio. Evaluarlo solo contra el rango dejaría pasar
    exactamente el caso que B-03.R2 existe para detectar.

    No se aplica el filtro `tipo_percepcion` de los parámetros: acota qué **filas se
    imprimen**, no contra qué se compara el acumulado, que sigue siendo el del tipo entero.

    **`sustituidos` se excluye siempre, sin mirar `incluir_cancelados`** (ver
    `universo_nomina.uuids_sustituidos`): un CFDI sustituido y su sustituto traen el mismo pago,
    y sumar los dos hacía que el informe emitiera una `EXENCION_EXCEDIDA` —severidad alta,
    hallazgo de auditoría— acusando al patrón de un exceso inexistente. La exclusión va en el
    `WHERE` y no en Python porque las sumas las hace la BD.
    """
    if not ejercicios or not tipos:
        return {}
    ejercicio_expr = extract("year", Nomina.fecha_pago)
    consulta = (
        select(
            Comprobante.rfc_receptor,
            NominaPercepcion.tipo_percepcion,
            ejercicio_expr.label("ejercicio"),
            func.sum(NominaPercepcion.importe_exento).label("exento"),
            func.sum(NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento).label("total"),
        )
        .join(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
        .join(NominaPercepcion, NominaPercepcion.comprobante_id == Comprobante.comprobante_id)
        .where(
            Comprobante.empresa_id == empresa_id,
            Comprobante.rfc_emisor == rfc_empresa,
            Comprobante.tipo_comprobante == "N",
            ejercicio_expr.in_(sorted(ejercicios)),
            NominaPercepcion.tipo_percepcion.in_(sorted(tipos)),
        )
        .group_by(Comprobante.rfc_receptor, NominaPercepcion.tipo_percepcion, ejercicio_expr)
    )
    if not incluir_cancelados:
        consulta = consulta.where(Comprobante.estatus != EstatusCfdi.CANCELADO)
    if sustituidos:
        consulta = consulta.where(Comprobante.uuid.notin_(sorted(sustituidos)))

    acumulados: dict[tuple[str, str, int], _Acumulado] = {}
    for rfc, tipo, ejercicio, exento, total in (await db.execute(consulta)).all():
        acumulados[(str(rfc), str(tipo), int(ejercicio))] = _Acumulado(_dec(exento), _dec(total))
    return acumulados


def _dec(valor: object) -> Decimal:
    """`func.sum` devuelve `Decimal`, `float` o `None` según el dialecto; nunca se compara en
    binario (mismo patrón que `universo_nomina._dec`)."""
    if valor is None:
        return _CERO
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


# --------------------------------------------------------------------------------------
# Acumuladores de banderas: una por causa, con el conteo
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Recuento:
    """Lo que hace falta para colapsar N hallazgos idénticos en una sola bandera."""

    filas: int = 0
    importe: Decimal = _CERO
    uuids: list[str] = field(default_factory=list)

    def sumar(self, uuid_cfdi: str, importe: Decimal = _CERO) -> None:
        self.filas += 1
        self.importe += importe
        if len(self.uuids) < MUESTRA_UUID:
            self.uuids.append(uuid_cfdi)

    @property
    def muestra(self) -> str:
        return ", ".join(self.uuids)


_MENSAJES_DE_CAUSA: dict[str, str] = {
    "FALTA_UMA": (
        "No hay una UMA diaria capturada para la fecha de pago de estas filas, así que no se pudo calcular "
        "ningún tope de exención sobre UMA. Captúrala en Configuración › Fiscal con su fuente (la publica el "
        "INEGI cada enero y entra en vigor el 1 de febrero) y vuelve a generar el informe."
    ),
    "FALTA_SALARIO_MINIMO": (
        "La zona salarial de la empresa está configurada, pero no hay **ningún** salario mínimo capturado para "
        "esa zona en la fecha de pago de estas filas —ni confirmado ni esperando confirmación—, así que no se "
        "pudo calcular su tope de exención. Captúralo en Configuración › Fiscal con su fuente (lo publica el "
        "CONASAMI en el DOF y cambia el 1 de enero)."
    ),
    "FALTA_ZONA_SALARIAL": (
        "Estas filas tienen una exención que se mide en días de salario mínimo y la empresa no tiene zona "
        "salarial configurada. No se asume ninguna a propósito: el mínimo de la Zona Libre de la Frontera "
        "Norte y el general se llevan casi un 40%, y adivinarlo daría topes falsos. Configúrala en "
        "Configuración › Empresa."
    ),
    "MARCA_SIN_FACTOR": (
        "La marca de estas filas declara una base de exención pero no trae `factor_exencion`. El cargador y "
        "la pantalla lo impiden, así que la fila se escribió directamente en la base: revísala."
    ),
    "SIN_FECHA_DE_PAGO": (
        "Estas filas vienen de un complemento de nómina sin fecha de pago, así que no hay con qué resolver la "
        "UMA ni el salario mínimo por vigencia. No es un hueco de configuración: es el CFDI el que no trae "
        "el dato."
    ),
}
"""Texto de las causas que no necesitan datos de la propia marca. Las que sí —las tres de
`_bandera_de_tipo`— se arman con el tipo, su descripción y su procedencia. `UMA_SIN_CONFIRMAR`
tampoco está aquí: su mensaje lleva la fuente de la propuesta (`_bandera_de_uma_propuesta`)."""


def _banderas_de_configuracion(
    por_causa: dict[str, _Recuento],
    por_tipo: dict[tuple[str, str], _Recuento],
    config: _Configuracion,
) -> list[Bandera]:
    """Las banderas de degradación, **una por causa**, con el conteo de filas afectadas.

    Dos ámbitos, según a quién le toca actuar: `informe` cuando falta un valor global (la UMA,
    la zona salarial) y `tipo:0NN` cuando lo que falta es de un tipo de percepción concreto,
    porque ahí la acción —confirmar *esa* marca, capturar *esa* marca— es distinta por tipo y
    colapsarlas en una sola escondería cuál hay que tocar.

    Cada bandera cuenta las **filas cuyo tope quedó vacío por esa causa**, que es el daño
    concreto: no las filas en las que el valor faltante *aparecería*, sino aquellas en las que
    su falta impidió calcular algo.
    """
    banderas: list[Bandera] = []
    for causa in sorted(por_causa):
        recuento = por_causa[causa]
        if causa in _PROPUESTAS_POR_CAUSA:
            banderas.append(_bandera_de_valor_propuesto(causa, recuento, config))
            continue
        banderas.append(
            Bandera(
                clave=causa,
                severidad="alta",
                ambito="informe",
                mensaje=(
                    f"{_MENSAJES_DE_CAUSA[causa]} Filas afectadas: {recuento.filas} "
                    f"(muestra de UUID: {recuento.muestra})."
                ),
            )
        )

    for (causa, tipo), recuento in sorted(por_tipo.items()):
        banderas.append(_bandera_de_tipo(causa, tipo, recuento, config))
    return banderas


def _bandera_de_tipo(causa: str, tipo: str, recuento: _Recuento, config: _Configuracion) -> Bandera:
    """`MARCA_SIN_CONFIRMAR`, `FALTA_MARCA` y `MARCA_CON_DUDA_DECLARADA`: una por tipo de
    percepción, con lo que hace falta para actuar sin abrir la base."""
    descripcion = catalogos.descripcion("P", tipo)
    nombre = f"{tipo} ({descripcion})" if descripcion else tipo
    comun = f" Filas afectadas: {recuento.filas} (muestra de UUID: {recuento.muestra})."

    if causa == "MARCA_SIN_CONFIRMAR":
        propuesta = config.marcas_propuestas.get(tipo)
        detalle = ""
        if propuesta is not None:
            factor = "sin factor" if propuesta.factor_exencion is None else f"factor {propuesta.factor_exencion}"
            detalle = f" La propuesta dice base {propuesta.base_exencion.value} y {factor}."
            if propuesta.sujeto_a_tope_conjunto:
                # Sin la marca confirmada, este tipo tampoco entra en la suma del tope conjunto
                # —`tipos_sujetos_al_tope_conjunto` solo mira lo confirmado—, y eso es más grave
                # que quedarse sin su tope por tipo: con `PORCENTAJE 100` el tope por tipo es
                # inexcedible por construcción y el conjunto es la única protección real.
                detalle += (
                    " Y está sujeta al tope conjunto de previsión social, que tampoco se evalúa mientras la "
                    "marca no se confirme."
                )
        return Bandera(
            clave=causa,
            severidad="alta",
            ambito=f"tipo:{tipo}",
            mensaje=(
                f"La marca de exención del tipo {nombre} está capturada pero nadie la ha confirmado, así que "
                f"no calcula ningún tope.{detalle} Revísala y confírmala en Configuración › Fiscal › Marcas "
                f"de percepción; es un clic.{comun}"
            ),
        )
    if causa == "FALTA_MARCA":
        return Bandera(
            clave=causa,
            severidad="alta",
            ambito=f"tipo:{tipo}",
            mensaje=(
                f"No hay marca de exención capturada para el tipo {nombre}, así que no se pudo determinar ni su "
                f"base ni su tope. Cárgala con la semilla `config/fiscal/catalogo_percepcion.yaml` o captúrala "
                f"en Configuración › Fiscal.{comun}"
            ),
        )
    # `MARCA_CON_DUDA_DECLARADA`. **Se cita la nota, no se supone cuál es la duda.** 39 de las
    # 44 marcas traen nota y solo nueve la traen por el multiplicador que no viene en el CFDI:
    # la del `029` es sobre el SBC y la del `005` sobre los requisitos de deducibilidad.
    # Afirmar "es el factor por año de servicio" mandaría a resolver la duda equivocada.
    marca = config.marcas.get(tipo)
    nota = (marca.nota_revision or "").strip() if marca is not None else ""
    primera_linea = nota.splitlines()[0] if nota else ""
    if len(primera_linea) > _MAX_NOTA_EN_BANDERA:
        primera_linea = primera_linea[:_MAX_NOTA_EN_BANDERA].rstrip() + "…"
    cita = f' La duda dice: "{primera_linea}".' if primera_linea else ""
    return Bandera(
        clave=causa,
        severidad="alta",
        ambito=f"tipo:{tipo}",
        mensaje=(
            f"La marca del tipo {nombre} está confirmada pero conserva una duda declarada, así que no se calcula "
            f"su tope de exención: publicar un número derivado de un factor que la propia semilla marca como "
            f"dudoso sería peor que dejar la celda vacía.{cita} Resuélvela en Configuración › Fiscal › Marcas de "
            f"percepción —y bórrala solo cuando el factor capturado sea el correcto— antes de confiar en el "
            f"tope.{comun}"
        ),
    )


_PROPUESTAS_POR_CAUSA: dict[str, tuple[str, str]] = {
    "UMA_SIN_CONFIRMAR": (
        "uma_propuesta",
        "Hay una UMA diaria capturada para la fecha de pago de estas filas, pero nadie la ha confirmado, y un "
        "valor sin confirmar no calcula: los topes de exención sobre UMA salieron vacíos.",
    ),
    "SALARIO_MINIMO_SIN_CONFIRMAR": (
        "salario_minimo_propuesto",
        "Hay un salario mínimo capturado para la zona de la empresa en la fecha de pago de estas filas, pero "
        "nadie lo ha confirmado, y un valor sin confirmar no calcula: los topes de exención medidos en días de "
        "salario mínimo salieron vacíos.",
    ),
}
"""Las causas que significan "el valor **existe**, solo falta el clic": el campo de
`_Configuracion` del que sale su procedencia, y el texto de qué quedó sin calcular.

Es una tabla y no dos funciones porque las dos banderas dicen lo mismo con distinto sujeto, y
porque `SALARIO_MINIMO_SIN_CONFIRMAR` nació de que B-03 **no** hacía esta distinción para el
salario mínimo mientras sí la hacía para la UMA: dos ramas separadas es exactamente cómo se
vuelve a perder. La clave es la misma que emite B-10 desde su ronda 1, a propósito — quien
filtre la hoja `Banderas` por ella tiene que encontrar los dos informes."""


def _bandera_de_valor_propuesto(causa: str, recuento: _Recuento, config: _Configuracion) -> Bandera:
    """El estado que más importa que quede bien, porque es el que tiene hoy la instalación real:
    el valor está capturado y solo espera que una persona lo revise.

    El mensaje trae la **fuente** de la propuesta, que es lo que separa un aviso accionable de
    uno inútil: "falta la UMA, ve a buscarla" frente a "la UMA 2026 está propuesta con su liga
    al boletín del INEGI, confírmala".
    """
    campo, texto = _PROPUESTAS_POR_CAUSA[causa]
    propuestas: dict[date, cfg.ValorFiscal | None] = getattr(config, campo)
    fuentes = sorted({v.fuente for v in propuestas.values() if v is not None})
    procedencia = f" Fuente de la propuesta: {'; '.join(fuentes)}." if fuentes else ""
    return Bandera(
        clave=causa,
        severidad="alta",
        ambito="informe",
        mensaje=(
            f"{texto} Basta con revisarlo y confirmarlo en Configuración › Fiscal.{procedencia} "
            f"Filas afectadas: {recuento.filas} (muestra de UUID: {recuento.muestra})."
        ),
    )


# --------------------------------------------------------------------------------------
# Las banderas de hallazgo: B-03.R2, B-03.R3 y el tope conjunto
# --------------------------------------------------------------------------------------


def _banderas_de_exencion_indebida(indebidas: dict[str, _Recuento]) -> list[Bandera]:
    """B-03.R3, colapsada por tipo de percepción: un tipo con `base_exencion = NINGUNA` e
    `importe_exento > 0`. Es un hallazgo de auditoría directo — ese importe debía ir gravado."""
    banderas: list[Bandera] = []
    for tipo in sorted(indebidas):
        recuento = indebidas[tipo]
        descripcion = catalogos.descripcion("P", tipo)
        nombre = f"{tipo} ({descripcion})" if descripcion else tipo
        banderas.append(
            Bandera(
                clave="EXENCION_INDEBIDA",
                severidad="alta",
                ambito=f"tipo:{tipo}",
                mensaje=(
                    f"El tipo {nombre} no tiene tramo exento en el artículo 93 de la LISR y aun así se timbró "
                    f"con importe exento en {recuento.filas} percepción(es), por un total de {recuento.importe}. "
                    f"Ese importe debía ir gravado. Muestra de UUID: {recuento.muestra}."
                ),
            )
        )
    return banderas


def _bandera_de_exencion_excedida(
    rfc: str, tipo: str, ejercicio: int, exento: Decimal, tope: Decimal | None, por_periodo: bool
) -> Bandera:
    """B-03.R2, colapsada por `(empleado, tipo, ejercicio)`: una bandera por causa, no una por
    fila, porque la causa es el acumulado del año y no la percepción concreta.

    El `ambito` lleva el RFC y nunca la CURP ni el NSS: la hoja `Banderas` **no** se enmascara.
    Con `tope=None` la comparación anual no se pudo hacer (falta el valor al cierre del
    ejercicio) y lo que dispara la bandera es una fila que ya excede su propio tope; el mensaje
    lo dice, en vez de inventar una cifra anual.
    """
    descripcion = catalogos.descripcion("P", tipo)
    nombre = f"{tipo} ({descripcion})" if descripcion else tipo
    if tope is None:
        cifras = (
            f"Alguna percepción del tipo {nombre} excede por sí sola su tope de exención. El acumulado del "
            f"ejercicio {ejercicio} de este empleado es {exento}, pero no se pudo comparar contra el tope anual "
            "porque falta el valor vigente al cierre del ejercicio."
        )
        return Bandera(
            clave="EXENCION_EXCEDIDA",
            severidad="alta",
            ambito=f"rfc:{rfc}|tipo:{tipo}|ejercicio:{ejercicio}",
            mensaje=cifras,
        )
    detalle = (
        "Además, alguna percepción suelta ya excede su propio tope."
        if por_periodo
        else "Ninguna percepción del año lo excede por sí sola; el exceso solo aparece al acumular el ejercicio."
    )
    return Bandera(
        clave="EXENCION_EXCEDIDA",
        severidad="alta",
        ambito=f"rfc:{rfc}|tipo:{tipo}|ejercicio:{ejercicio}",
        mensaje=(
            f"El importe exento acumulado del tipo {nombre} en {ejercicio} es {exento} y el tope del artículo 93 "
            f"para ese empleado y ejercicio es {tope}: hay {exento - tope} exentos de más. {detalle} El tope del "
            "artículo 93 es anual, no por periodo de pago."
        ),
    )


def tipos_sujetos_al_tope_conjunto(config: _Configuracion) -> set[str]:
    """Los tipos con `sujeto_a_tope_conjunto` entre las marcas **confirmadas**: los que
    **calculan**.

    El alcance sale del dato, no de una lista escrita en el programa (§2.12): es la columna
    que la tarea 3 agregó justo para eso. Los exceptuados por el último párrafo del art. 93
    (jubilaciones, gastos médicos, funeral, fondo de ahorro…) simplemente no traen la marca,
    así que la lista de exceptuados tampoco vive en el código.

    Solo lo confirmado, porque de aquí sale un **cálculo**. Para decidir si hay que **avisar**,
    ver `tipos_que_podrian_estar_sujetos_al_tope_conjunto`.
    """
    return {tipo for tipo, marca in config.marcas.items() if marca.sujeto_a_tope_conjunto}


def tipos_que_podrian_estar_sujetos_al_tope_conjunto(config: _Configuracion) -> set[str]:
    """Los tipos con `sujeto_a_tope_conjunto` entre las marcas confirmadas **y las
    propuestas**: los que hay que **mirar para saber si el aviso hace falta**.

    **Este es el mismo error de razonamiento que ya costó dos defectos en este módulo, cerrado
    en su forma general:** "un valor sin confirmar no calcula" gobierna los *cálculos*, no las
    *advertencias*. Decidir si hay que avisar de que el tope conjunto no se pudo evaluar no
    necesita la marca confirmada — de hecho es imposible saberlo sin mirar lo propuesto, y con
    el catálogo de hoy (44 marcas, ninguna confirmada) mirar solo lo confirmado deja el aviso
    permanentemente apagado.

    Lo añadido por esta función **nunca entra en una suma ni en una comparación**: solo decide
    si se emite `TOPE_CONJUNTO_SIN_EVALUAR`. Es la misma forma que ya tenían `FALTA_UMA_ANUAL`
    y `FALTA_UMA`: la ausencia se reporta, no se rellena.

    Se expone (sin guion bajo) porque `consultar` la necesita **antes** de la consulta
    agregada, para que el acumulado traiga también los importes de estos tipos.
    """
    return {
        tipo
        for tipo, marca in (*config.marcas.items(), *config.marcas_propuestas.items())
        if marca.sujeto_a_tope_conjunto
    }


def _avisos_de_tope_conjunto_sin_evaluar(
    config: _Configuracion, acumulados: dict[tuple[str, str, int], _Acumulado]
) -> list[Bandera]:
    """`TOPE_CONJUNTO_SIN_EVALUAR`: hay importes exentos bajo un tipo que **podría** estar
    sujeto al tope conjunto y cuya marca nadie ha confirmado, así que la suma del art. 93 salió
    incompleta o no salió.

    **No cuelga de ninguna fila impresa**, a propósito: el tipo sin confirmar puede haberse
    pagado fuera del rango o quedar excluido por el filtro `tipo_percepcion`, y en los dos
    casos el informe se quedaba mudo mientras la suma real del ejercicio pasaba de 1 UMA anual.
    Su ámbito es el ejercicio, como el de `FALTA_UMA_ANUAL`.

    **Solo se avisa de lo que de verdad quedó sin sumar:** hace falta que ese tipo tenga
    importe exento en el ejercicio. Una marca sujeta al tope y sin confirmar bajo la que nadie
    cobró un peso no deja nada sin evaluar, y una bandera que sale siempre no la lee nadie.
    """
    sin_confirmar = tipos_que_podrian_estar_sujetos_al_tope_conjunto(config) - tipos_sujetos_al_tope_conjunto(config)
    if not sin_confirmar:
        return []

    por_ejercicio: dict[int, set[str]] = defaultdict(set)
    for (_rfc, tipo, ejercicio), acumulado in acumulados.items():
        if tipo in sin_confirmar and acumulado.exento > _CERO:
            por_ejercicio[ejercicio].add(tipo)

    banderas: list[Bandera] = []
    for ejercicio in sorted(por_ejercicio):
        tipos = sorted(por_ejercicio[ejercicio])
        banderas.append(
            Bandera(
                clave="TOPE_CONJUNTO_SIN_EVALUAR",
                severidad="alta",
                ambito=f"ejercicio:{ejercicio}",
                mensaje=(
                    f"En {ejercicio} se pagaron importes exentos bajo el/los tipo(s) {', '.join(tipos)}, que están "
                    "marcados como sujetos al tope conjunto de previsión social del artículo 93 de la LISR, y esas "
                    "marcas todavía no están confirmadas: la suma del tope conjunto se calculó **sin ellos** o no "
                    "se calculó. Esos tipos llevan la exención en bruto, así que su tope por tipo no puede "
                    "detectar nada y el tope conjunto es la única comprobación que los cubre. Confirma esas marcas "
                    "en Configuración › Fiscal › Marcas de percepción y vuelve a generar el informe."
                ),
            )
        )
    return banderas


def _banderas_de_tope_conjunto(
    config: _Configuracion,
    acumulados: dict[tuple[str, str, int], _Acumulado],
    empleados: set[tuple[str, int]],
) -> list[Bandera]:
    """El tope conjunto de previsión social (penúltimo párrafo del art. 93): la **suma** de
    esas exenciones se limita a 1 UMA anual por trabajador y por año.

    **Dos cosas que este cálculo NO comparte con el tope por tipo, y que costaron dos
    defectos de "exentar de más en silencio":**

    1. **No depende del `factor_exencion`.** Suma `importe_exento` y lo compara contra
       `UMA_ANUAL`; el factor dudoso no interviene. La primera versión alimentaba esta suma
       de las filas cuyo tope por tipo se había podido calcular, así que la duda declarada de
       una marca apagaba también esta comprobación — y como **los seis tipos sujetos al tope
       traen los seis `nota_revision` en la semilla real**, la única protección contra el
       "exentar de más" de esos seis quedaba inerte en el 100% del catálogo de producción, sin
       una sola bandera que lo dijera. Por eso el conjunto se arma aquí, de las marcas
       confirmadas, y no de lo que se pudo calcular.
    2. **No se acota al rango ni al filtro del informe.** Es una suma *entre* tipos: uno
       pagado en enero consume la misma UMA anual que uno pagado en junio. `consultar` incluye
       todos los tipos de `tipos_sujetos_al_tope_conjunto` en la consulta agregada, no solo
       los presentes en las filas impresas — es el mismo arreglo que ya llevaba B-03.R2 para
       los importes, aplicado ahora al conjunto de tipos.

    3. **Ni siquiera *avisar* depende de la marca confirmada.** El alcance del cálculo sí sale
       de lo confirmado —calcular con una marca sin revisar violaría el invariante—, pero
       saber que hay algo sin evaluar no. Como hoy no hay ninguna marca confirmada, mirar solo
       lo confirmado dejaba el aviso apagado **siempre**, y lo único que lo compensaba era una
       frase dentro de `MARCA_SIN_CONFIRMAR`, que se alimenta de las filas impresas: mudo otra
       vez si el tipo se pagó fuera del rango o lo excluyó el filtro. Por eso
       `TOPE_CONJUNTO_SIN_EVALUAR` se decide con
       `tipos_que_podrian_estar_sujetos_al_tope_conjunto` —confirmadas **y** propuestas— y no
       cuelga de ninguna fila.

    **`empleados` y la cuarta vía.** `empleados` son los `(rfc_receptor, ejercicio)` de las
    filas impresas, y de ellos habla el informe: llevan bandera propia. Un empleado cuyos pagos
    de previsión social caen **todos** fuera del rango es un caso distinto —el informe no lo
    cubre, no hay ninguna fila suya que mirar— pero callarlo sería el mismo silencio que costó
    el punto 2, así que **se cuenta en una bandera colapsada por ejercicio** que dice cuántos
    son y que basta ampliar el rango. La suma que los detecta ya está en `acumulados`, que no
    filtra por empleado: cerrar esta vía no cuesta ninguna consulta más.

    **Es una bandera de revisión, no un recálculo de ISR**, y por eso lleva **clave propia** y
    no `EXENCION_EXCEDIDA`: aquel es un exceso comprobable contra un tope de la ley y este es
    explícitamente condicional. El párrafo limita la exención solo cuando los ingresos por
    salarios más la previsión social exceden de 7 UMA anuales, y añade un piso para que la
    limitación no deje al trabajador por debajo de esas 7 UMA; ninguna de las dos se evalúa
    aquí —haría falta la base salarial anual completa del trabajador, incluida la de otros
    patrones—. Emitirla igual es lo correcto: el falso positivo cuesta una lectura y el falso
    negativo en un ingreso alto es el hallazgo caro. Pero quien filtra la hoja `Banderas`
    tiene que poder separarlos por clave, no leyendo la prosa del mensaje.
    """
    banderas: list[Bandera] = list(_avisos_de_tope_conjunto_sin_evaluar(config, acumulados))

    tipos_con_tope = tipos_sujetos_al_tope_conjunto(config)
    if not tipos_con_tope:
        return banderas

    # Sobre TODOS los empleados del acumulado, no solo los del informe: la separación entre
    # "lleva bandera propia" y "se cuenta en el resumen" se hace después, con `empleados`.
    por_empleado: dict[tuple[str, int], Decimal] = defaultdict(lambda: _CERO)
    for (rfc, tipo, ejercicio), acumulado in acumulados.items():
        if tipo in tipos_con_tope and acumulado.exento > _CERO:
            por_empleado[(rfc, ejercicio)] += acumulado.exento

    ejercicios_sin_uma_anual: set[int] = set()
    excedidos_fuera: Counter[int] = Counter()
    for (rfc, ejercicio), exento in sorted(por_empleado.items()):
        tope = config.uma_anual.get(ejercicio)
        if tope is None:
            ejercicios_sin_uma_anual.add(ejercicio)
            continue
        if exento <= tope + _TOLERANCIA:
            continue
        if (rfc, ejercicio) not in empleados:
            excedidos_fuera[ejercicio] += 1
            continue
        banderas.append(
            Bandera(
                clave="TOPE_CONJUNTO_EXCEDIDO",
                severidad="alta",
                ambito=f"rfc:{rfc}|ejercicio:{ejercicio}",
                mensaje=(
                    f"Tope conjunto de previsión social: las exenciones de previsión social de este empleado "
                    f"suman {exento} en {ejercicio} y el penúltimo párrafo del artículo 93 de la LISR las limita "
                    f"a 1 UMA anual ({tope}). Hay {exento - tope} exentos de más. La suma incluye todo el "
                    "ejercicio y todos los tipos sujetos al tope, aunque no aparezcan en estas filas. La "
                    "limitación aplica cuando los ingresos por salarios más la previsión social exceden de 7 UMA "
                    "anuales y tiene un piso propio; este informe no evalúa esas dos condiciones —necesitan la "
                    "base salarial anual completa del trabajador—, así que confirma el caso antes de corregir."
                ),
            )
        )

    for ejercicio, cuantos in sorted(excedidos_fuera.items()):
        banderas.append(
            Bandera(
                clave="TOPE_CONJUNTO_EXCEDIDO_FUERA_DEL_INFORME",
                severidad="media",
                ambito=f"ejercicio:{ejercicio}",
                mensaje=(
                    f"{cuantos} empleado(s) más exceden el tope conjunto de previsión social de {ejercicio}, pero "
                    "todos sus pagos de esos tipos caen fuera del rango de este informe, así que no tienen ninguna "
                    "fila aquí y no llevan bandera propia. Amplía el rango al ejercicio completo para verlos."
                ),
            )
        )

    for ejercicio in sorted(ejercicios_sin_uma_anual):
        propuesta = config.uma_anual_propuesta.get(ejercicio)
        if propuesta is not None:
            banderas.append(
                Bandera(
                    clave="UMA_ANUAL_SIN_CONFIRMAR",
                    severidad="alta",
                    ambito=f"ejercicio:{ejercicio}",
                    mensaje=(
                        f"Hay percepciones sujetas al tope conjunto de previsión social en {ejercicio}, pero la "
                        f"UMA anual de ese ejercicio está capturada sin confirmar, así que el tope no se evaluó. "
                        f"Fuente de la propuesta: {propuesta.fuente}."
                    ),
                )
            )
        else:
            banderas.append(
                Bandera(
                    clave="FALTA_UMA_ANUAL",
                    severidad="alta",
                    ambito=f"ejercicio:{ejercicio}",
                    mensaje=(
                        f"Hay percepciones sujetas al tope conjunto de previsión social en {ejercicio} y no hay "
                        "UMA anual capturada para ese ejercicio, así que el tope no se evaluó: el informe podría "
                        "estar dando por buenas exenciones que exceden 1 UMA anual."
                    ),
                )
            )
    return banderas


# --------------------------------------------------------------------------------------
# La consulta
# --------------------------------------------------------------------------------------


async def _percepciones(db: AsyncSession, ids: list[int], tipo: str | None) -> dict[int, list[NominaPercepcion]]:
    """Los nodos de percepción de los comprobantes del universo, en una sola consulta y con
    orden determinista: por `(tipo, clave, id)` dentro de cada comprobante (B-02.R5 aplicado
    a filas en vez de a columnas)."""
    if not ids:
        return {}
    consulta = (
        select(NominaPercepcion)
        .where(NominaPercepcion.comprobante_id.in_(ids))
        .order_by(
            NominaPercepcion.comprobante_id,
            NominaPercepcion.tipo_percepcion,
            NominaPercepcion.clave,
            NominaPercepcion.id,
        )
    )
    if tipo is not None:
        consulta = consulta.where(NominaPercepcion.tipo_percepcion == tipo)
    por_comprobante: dict[int, list[NominaPercepcion]] = defaultdict(list)
    for nodo in (await db.scalars(consulta)).all():
        por_comprobante[nodo.comprobante_id].append(nodo)
    return por_comprobante


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=_columnas(), aviso="La empresa no existe.")

    p_universo = _ParametrosUniverso(p.fecha_desde, p.fecha_hasta, p.incluir_cancelados)
    filas_universo = list((await db.execute(universo_nomina.universo(empresa_id, rfc_empresa, p_universo))).all())
    # Se resuelve ANTES del retorno temprano: si el ETL falló en todos los CFDI del rango,
    # estas banderas son el único rastro de que había nómina que reportar.
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, rfc_empresa, p_universo)

    if not filas_universo:
        return ResultadoInforme(
            columnas=_columnas(), banderas=banderas_fuera, aviso="Sin CFDI de nómina en el rango solicitado."
        )

    ids = [fila[0].comprobante_id for fila in filas_universo]
    nodos = await _percepciones(db, ids, p.tipo_percepcion)
    if not any(nodos.values()):
        return ResultadoInforme(
            columnas=_columnas(),
            banderas=banderas_fuera,
            aviso="Los CFDI del rango no traen percepciones que coincidan con el filtro.",
        )

    # Fechas y ejercicios que hay que resolver en la configuración: los de las filas que se
    # van a imprimir, no uno por fila.
    fechas: set[date] = set()
    ejercicios: set[int] = set()
    tipos: set[str] = set()
    for comprobante, nomina, _receptor, _totales, _detalle in filas_universo:
        if not nodos.get(comprobante.comprobante_id):
            continue
        if nomina.fecha_pago is not None:
            fechas.add(nomina.fecha_pago)
            ejercicios.add(nomina.fecha_pago.year)
        tipos.update(nodo.tipo_percepcion for nodo in nodos[comprobante.comprobante_id])
    fechas.update(date(ejercicio, 12, 31) for ejercicio in ejercicios)

    # Resolución de sustituciones, **antes** de imprimir o acumular nada, y sobre el ejercicio
    # completo: es el mismo alcance del acumulado que protege (ver `_nomina_del_ejercicio`).
    ids_sustitutos = list((await db.scalars(_nomina_del_ejercicio(empresa_id, rfc_empresa, ejercicios))).all())
    sustituidos = await universo_nomina.uuids_sustituidos(db, ids_sustitutos)

    config = await _configuracion(db, empresa_id, fechas, ejercicios)
    # El acumulado cubre los tipos de las filas impresas **y** todos los que podrían estar
    # sujetos al tope conjunto —confirmados o solo propuestos—, aunque ninguno aparezca en el
    # rango o lo excluya `tipo_percepcion`: el tope conjunto es una suma *entre* tipos y un
    # vale pagado en enero consume la misma UMA anual que uno de junio. Los propuestos entran
    # para poder **avisar** de que la suma quedó incompleta, nunca para sumarse. Sigue siendo
    # una sola consulta.
    acumulados = await _acumulado_anual(
        db,
        empresa_id,
        rfc_empresa,
        ejercicios,
        tipos | tipos_que_podrian_estar_sujetos_al_tope_conjunto(config),
        p.incluir_cancelados,
        sustituidos,
    )

    banderas: list[Bandera] = list(banderas_fuera)
    banderas.extend(universo_nomina.banderas_de_estatus(universo_nomina.comprobantes_y_detalles(filas_universo)))
    banderas.extend(await universo_nomina.banderas_de_gravado_y_exento_descuadrados(db, ids))

    por_causa: dict[str, _Recuento] = defaultdict(_Recuento)
    por_tipo: dict[tuple[str, str], _Recuento] = defaultdict(_Recuento)
    indebidas: dict[str, _Recuento] = defaultdict(_Recuento)
    # `(rfc, tipo, ejercicio)` de las filas cuyo tope **sí** se pudo calcular: son las únicas
    # que se pueden comparar contra un acumulado anual. Y si alguna fila suelta ya excede el
    # suyo, se recuerda aparte: con base `PORCENTAJE` el acumulado puede cuadrar aunque una
    # percepción concreta se pase, porque otra del mismo año se quedó corta.
    combinaciones: set[tuple[str, str, int]] = set()
    excede_alguna_fila: dict[tuple[str, str, int], bool] = defaultdict(bool)
    # `(rfc_receptor, ejercicio)` de las filas impresas: de esos trabajadores habla el informe,
    # y son los que se revisan contra el tope conjunto. **No se deriva de `combinaciones`**:
    # ese conjunto solo tiene las filas cuyo tope por tipo se pudo calcular, y el tope conjunto
    # no depende de ese cálculo (ver `_banderas_de_tope_conjunto`).
    empleados: set[tuple[str, int]] = set()

    filas: list[list[Any]] = []
    # `_totales` (el encabezado de `nomina_totales`) no se usa: este informe reporta los nodos
    # uno a uno, y el cotejo del encabezado contra la suma de sus nodos ya lo hizo
    # `banderas_de_gravado_y_exento_descuadrados` unas líneas arriba.
    for comprobante, nomina, receptor, _totales, detalle in filas_universo:
        percepciones = nodos.get(comprobante.comprobante_id, [])
        if not percepciones:
            continue
        if comprobante.uuid in sustituidos:
            # Ni fila ni acumulado: el sustituto ya trae este pago. Imprimir las dos versiones
            # daría el doble al sumar la columna "Importe exento" de un papel de trabajo que
            # existe justo para revisar concepto por concepto.
            banderas.append(
                Bandera(
                    clave=universo_nomina.CLAVE_CFDI_SUSTITUIDO,
                    severidad="baja",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=(
                        "Excluido del informe: otro CFDI de nómina del ejercicio lo declara sustituido "
                        "(`cfdi_relacionado.tipo_relacion='04'`), así que su sustituto ya trae este pago. "
                        "Se excluye de la hoja Datos —dos filas para un solo pago darían el doble al sumar "
                        "la columna de exento— y del acumulado anual del artículo 93, donde contarlo dos "
                        "veces produciría un exceso de exención que no existe."
                    ),
                )
            )
            continue
        fecha_pago = nomina.fecha_pago
        uma = config.uma.get(fecha_pago) if fecha_pago is not None else None
        propuesta_uma = config.uma_propuesta.get(fecha_pago) if fecha_pago is not None else None
        salario_minimo = config.salario_minimo.get(fecha_pago) if fecha_pago is not None else None
        propuesta_minimo = config.salario_minimo_propuesto.get(fecha_pago) if fecha_pago is not None else None
        ejercicio = fecha_pago.year if fecha_pago is not None else None
        if ejercicio is not None:
            empleados.add((comprobante.rfc_receptor, ejercicio))

        for nodo in percepciones:
            total = nodo.importe_gravado + nodo.importe_exento
            marca = config.marcas.get(nodo.tipo_percepcion)
            tope = _tope_de_fila(
                marca,
                config.marcas_propuestas.get(nodo.tipo_percepcion),
                uma,
                propuesta_uma is not None,
                salario_minimo,
                propuesta_minimo is not None,
                config.zona_configurada,
                fecha_pago is not None,
                total,
            )
            if tope.causa in ("MARCA_SIN_CONFIRMAR", "FALTA_MARCA", "MARCA_CON_DUDA_DECLARADA"):
                por_tipo[(tope.causa, nodo.tipo_percepcion)].sumar(str(comprobante.uuid))
            elif tope.causa is not None:
                por_causa[tope.causa].sumar(str(comprobante.uuid))

            exceso = None if tope.valor is None else max(_CERO, nodo.importe_exento - tope.valor)
            if (
                marca is not None
                and marca.base_exencion is BaseExencion.NINGUNA
                and nodo.importe_exento > _TOLERANCIA
            ):
                indebidas[nodo.tipo_percepcion].sumar(str(comprobante.uuid), nodo.importe_exento)

            # Insumos de B-03.R2. `NINGUNA` queda fuera a propósito: su tope es cero, así que
            # cualquier exento lo "excede" y saldría una `EXENCION_EXCEDIDA` duplicando la
            # `EXENCION_INDEBIDA` que ya describe mejor el mismo hallazgo.
            if (
                ejercicio is not None
                and marca is not None
                and tope.valor is not None
                and marca.base_exencion is not BaseExencion.NINGUNA
            ):
                llave = (comprobante.rfc_receptor, nodo.tipo_percepcion, ejercicio)
                combinaciones.add(llave)
                if exceso is not None and exceso > _TOLERANCIA:
                    excede_alguna_fila[llave] = True

            filas.append(
                [
                    comprobante.uuid,
                    fecha_pago,
                    ejercicio,
                    fecha_pago.month if fecha_pago is not None else None,
                    comprobante.rfc_receptor,
                    detalle.nombre_receptor if detalle else None,
                    # CURP y NSS en claro: `Columna(sensible=True)` ya lo declaró y es el motor
                    # (`app.informes.excel.escribir_libro`) quien enmascara, no esta consulta.
                    receptor.curp if receptor else None,
                    receptor.nss if receptor else None,
                    receptor.num_empleado if receptor else None,
                    receptor.departamento if receptor else None,
                    receptor.puesto if receptor else None,
                    nomina.num_dias_pagados,
                    nodo.tipo_percepcion,
                    catalogos.descripcion("P", nodo.tipo_percepcion),
                    nodo.clave,
                    nodo.concepto,
                    nodo.importe_gravado,
                    nodo.importe_exento,
                    total,
                    _porcentaje_exento(nodo.importe_exento, total),
                    marca.base_exencion.value if marca is not None else None,
                    tope.valor,
                    exceso,
                    uma,
                ]
            )

    banderas.extend(_banderas_de_configuracion(por_causa, por_tipo, config))
    banderas.extend(_banderas_de_exencion_indebida(indebidas))

    for llave in sorted(combinaciones):
        rfc, tipo, ejercicio = llave
        acumulado = acumulados.get(llave)
        marca_anual = config.marcas.get(tipo)
        if acumulado is None or marca_anual is None:
            continue
        tope_anual = _tope_anual(marca_anual, config, ejercicio, acumulado.total)
        excede_acumulado = tope_anual is not None and acumulado.exento > tope_anual + _TOLERANCIA
        if excede_acumulado or excede_alguna_fila[llave]:
            banderas.append(
                _bandera_de_exencion_excedida(
                    rfc, tipo, ejercicio, acumulado.exento, tope_anual, excede_alguna_fila[llave]
                )
            )

    banderas.extend(_banderas_de_tope_conjunto(config, acumulados, empleados))

    return ResultadoInforme(columnas=_columnas(), filas=filas, banderas=banderas)


def _tope_anual(
    marca: CatalogoPercepcionMarca, config: _Configuracion, ejercicio: int, total_anual: Decimal
) -> Decimal | None:
    """El tope del **ejercicio** para B-03.R2, que no es la suma de los topes por periodo.

    - `UMA_DIAS` / `SM_DIAS`: el art. 93 fija un tope anual único (30 días de UMA de aguinaldo
      al año, no 30 por quincena), así que es `factor × valor` **una sola vez**, resuelto con
      el valor vigente al cierre del ejercicio — el que corresponde a una cifra anual.
    - `PORCENTAJE`: el tope es proporcional al importe, así que el anual es `factor%` del
      **importe anual**, que viene del mismo agregado que el exento acumulado. Sumar los topes
      de las filas impresas daría un tope de junio contra un exento de todo el año, y con un
      informe de un mes cualquier tipo con base porcentual saldría marcado como excedido.

    Devuelve `None` —nunca cero— cuando el valor que hace falta no está disponible al cierre
    del ejercicio: un cero aquí convertiría la ausencia de la UMA en un exceso inexistente
    sobre todos los empleados del informe.

    **El matiz de enero, anotado a propósito.** La UMA cambia el 1 de febrero, así que la
    columna "UMA aplicable" de una fila pagada en **enero** trae el valor del tramo anterior
    y este tope anual trae el nuevo: el lector no puede reproducir la cifra multiplicando lo
    que ve en su fila. La diferencia (~4-5% al año) va **hacia la indulgencia** —el tope sale
    algo más alto—, que es lo contrario del criterio conservador del resto del módulo. Se
    mantiene igual porque medir una cifra anual con el valor vigente al cierre es la lectura
    fiscal estándar, y porque del 1 de febrero al 31 de diciembre los dos valores coinciden.
    """
    factor = marca.factor_exencion
    if factor is None:
        return None
    if marca.base_exencion is BaseExencion.PORCENTAJE:
        return factor * total_anual / _CIEN
    cierre = date(ejercicio, 12, 31)
    if marca.base_exencion is BaseExencion.UMA_DIAS:
        valor = config.uma.get(cierre)
    else:
        valor = config.salario_minimo.get(cierre)
    return None if valor is None else factor * valor


def _porcentaje_exento(exento: Decimal, total: Decimal) -> Decimal:
    """Sobre el importe total de la **fila** (gravado + exento), no sobre el del comprobante.

    Con importe total cero devuelve cero y no `None`: no es una celda que dependa de un valor
    de configuración por capturar, es un hecho —no hubo importe, así que no hubo parte
    exenta— y un vacío ahí rompería cualquier suma en la hoja de cálculo (R-T7).
    """
    if total == _CERO:
        return _CERO
    return exento * _CIEN / total
