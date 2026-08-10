"""Alarma de vigencia de los valores fiscales y sincronización del tipo de cambio.

Por qué esto es una alarma de calendario y no un raspador
---------------------------------------------------------
Alguien va a proponer raspar el DOF o la página de la CONASAMI. Se investigó y se descartó, y
conviene que la razón esté aquí antes de que se vuelva a proponer. De las cuatro fuentes que
alimentan `param_fiscal`, **solo una tiene API de verdad**:

| Valor | Cómo se publica | Qué se puede hacer |
|---|---|---|
| Tipo de cambio | API SIE de Banxico (REST/JSON, token gratuito, serie `SF43718`) | Sincronizar. Es lo que hace este módulo. |
| UMA | Boletín **PDF** del INEGI | Nada fiable. La API del INEGI sirve el INPC, del que la UMA *se deriva*; recalcularla sería reimplementar la fórmula de la ley en código, justo lo que §2.12 prohíbe. |
| Salario mínimo | Resolución de la CONASAMI en el **DOF**. No hay API | Nada fiable. |
| Tarifa del ISR | Anexo 8 en PDF | Fuera de alcance. |

Raspar HTML no es una alternativa más débil: es una alternativa **peor que no hacer nada**.
Cuando el sitio cambia de estructura el raspador no falla, devuelve otra cosa o nada, y el
resultado es un valor fiscal viejo con cara de vigente — el modo de falla exacto que este
subsistema existe para impedir.

**Lo que de verdad mantiene los valores al día es el calendario.** Las fechas de actualización
son conocidas y fijas: la UMA cambia el **1 de febrero** (art. 26-B de la Constitución: el INEGI
la publica en enero para entrar en vigor el 1 de febrero) y el salario mínimo el **1 de enero**.
Si esa fecha del año en curso ya pasó y no hay un valor **confirmado** cuya vigencia arranque en
o después de ella, el valor está caducado y hay que gritarlo. Esto **no se rompe nunca**, porque
no depende de que ninguna página web conserve su estructura ni de que exista conexión.

El invariante heredado: proponer no es confirmar
------------------------------------------------
`sincronizar_tipo_cambio` escribe con `origen: SINCRONIZADO` y **sin** confirmación, igual que
el cargador de semillas y la captura manual. Ni la API más confiable activa un valor por su
cuenta: `valor_vigente` sigue devolviendo `None` hasta que una persona lo confirme.

Y **falla ruidosamente**: si falta el token o la API no responde, se lanza
`ErrorDeSincronizacion`, la tarea del beat lo registra en `configuracion`
(`sync_banxico_estado`) y `alertas_de_vigencia` lo devuelve como una alerta más. Nunca se
devuelve "0 valores propuestos" como si todo estuviera en orden.

Por qué `TIPO_CAMBIO_USD` no está en `FECHAS_DE_ACTUALIZACION`
---------------------------------------------------------------
No cambia por decreto en una fecha fija: cambia cada día hábil. Meterlo en la alarma de
calendario lo dejaría permanentemente en rojo —nadie confirma a mano un tipo de cambio diario—
y una alarma siempre encendida es una alarma que se aprende a ignorar, que es como se gasta la
misma puerta que el invariante de confirmación vino a proteger. Su ausencia total sigue siendo
visible por otra vía: `claves_sin_valor` en `GET /v1/configuracion/fiscal`.

Tres cosas más que caducan y que no son valores
------------------------------------------------
La alarma también vigila la maquinaria, porque su avería se manifiesta con síntomas que nadie
relacionaría con la causa:

1. **La versión de `satcfdi`.** Capturar una marca de percepción exige que el tipo exista en
   `C75b_c_TipoPercepcion`. Es la protección correcta contra un dedazo (`150` por `015`), pero
   si el SAT publica claves nuevas se rechazarán hasta que se actualice la librería. El síntoma
   sin aviso sería "no puedo capturar un tipo que el SAT ya publicó".
2. **El catálogo del SAT ilegible.** Ante esa avería B-01 genera sin columnas de catálogo (falla
   abierto: leer degradado) mientras la captura de percepciones responde 503 (falla cerrado:
   escribir a ciegas es peor). **El reparto es correcto y no se cambia aquí** — pero la alarma
   es donde tiene que hacerse visible que el catálogo no se puede leer.
3. **La sincronización de Banxico.** Ver arriba.

Los seis motivos de alerta, y por qué no son tres
--------------------------------------------------
Los tres del enunciado —`AUSENTE`, `SIN_CONFIRMAR`, `CADUCADO`— describen el estado de un
**valor** y piden acciones distintas (capturar / un clic / actualizar el ejercicio). Los otros
tres —`CATALOGO_ILEGIBLE`, `LIBRERIA_DESACTUALIZADA`, `SINCRONIZACION_FALLIDA`— describen la
**maquinaria**, y meterlos a la fuerza en los primeros haría que la alerta mintiera: un catálogo
que no se puede abrir no es un valor "ausente" ni pide ir a capturar nada.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version_instalada
from typing import Any, Final, Literal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.configuracion_fiscal import ParamFiscal
from app.models.enums import OrigenValor, PeriodicidadTarifa
from app.repositories import configuracion as config_repo
from app.repositories import tarifa_isr as repo_tarifa
from app.services import configuracion_fiscal as cfg
from app.services import tarifa_isr as reglas_tarifa

logger = logging.getLogger(__name__)

MotivoAlerta = Literal[
    "AUSENTE",
    "SIN_CONFIRMAR",
    "CADUCADO",
    "CATALOGO_ILEGIBLE",
    "LIBRERIA_DESACTUALIZADA",
    "SINCRONIZACION_FALLIDA",
]

# Mes y día en que cada clave se actualiza **cada año**. Es el corazón de la alarma: no hay que
# leer ninguna página para saber que el 6 de agosto de 2026 la UMA tuvo que haber cambiado el 1
# de febrero. Solo entran valores que cambian por decreto en fecha fija (ver el docstring: el
# tipo de cambio queda fuera a propósito).
#
# El subsidio al empleo entra con (1, 1): el decreto se publica en el DOF a fines de diciembre
# y aplica desde el 1 de enero del año siguiente, igual que el salario mínimo.
FECHAS_DE_ACTUALIZACION: Final[dict[str, tuple[int, int]]] = {
    "UMA_DIARIA": (2, 1),
    "UMA_MENSUAL": (2, 1),
    "UMA_ANUAL": (2, 1),
    "SALARIO_MINIMO_GENERAL": (1, 1),
    "SALARIO_MINIMO_ZLFN": (1, 1),
    "SUBSIDIO_FACTOR_UMA": (1, 1),
    "SUBSIDIO_TOPE_INGRESO": (1, 1),
}

# Claves sintéticas de las alertas de maquinaria: no son claves de `param_fiscal` y no colisionan
# con ellas (`CLAVES_PARAM_FISCAL` es una lista blanca cerrada).
CLAVE_CATALOGO_SAT: Final = "CATALOGO_SAT_PERCEPCIONES"
CLAVE_VERSION_SATCFDI: Final = "VERSION_SATCFDI"
CLAVE_BANXICO: Final = "SINCRONIZACION_BANXICO"

# Otra clave sintética de la misma familia: la tarifa del ISR tampoco vive en `param_fiscal`
# (vive en `tarifa_isr`/`tarifa_isr_renglon`, con su propio repositorio), y su alarma no cabe en
# `FECHAS_DE_ACTUALIZACION` porque no es "una fecha fija en la que un solo valor cambia" — son
# hasta cinco tarifas (una por periodicidad que la nómina timbre) y la fecha que importa es
# cuándo empieza el ejercicio, no un día puntual dentro de él.
#
# **A lo sumo una alerta con esta clave**, igual que con cualquier otra clave del módulo (una
# UMA caducada es una alerta, no una por cada mes que lleva caducada). La primera versión de
# esta tarea emitía una alerta por periodicidad faltante, todas con `clave="TARIFA_ISR"`, y una
# revisión lo marcó como un hallazgo real: nada en el tipo dice que "a lo sumo una por clave"
# es un invariante, así que romperlo pasaba en silencio, y un consumidor que tratara `alertas`
# como un mapa por clave (razonable, dado que todas las demás lo cumplen) se quedaría solo con
# la última. Se corrigió consolidando en `_alertas_de_tarifa`: si faltan varias periodicidades,
# es **una** alerta cuyo `detalle` las enumera todas. No se agregó un campo `periodicidad` a
# `AlertaVigenciaOut` (doc 05) para poder decirlo de otra forma: el único caso real hoy es una
# empresa que timbra una sola periodicidad, y ampliar el contrato de la API para un escenario
# hipotético es la misma sobreconstrucción que el proyecto evita en todas partes. Si el día de
# mañana varias empresas con periodicidades distintas necesitan ver el desglose estructurado en
# pantalla y no solo en prosa, ese es el momento de tocar el contrato — no antes.
CLAVE_TARIFA_ISR: Final = "TARIFA_ISR"

# Etiqueta breve para meter la periodicidad dentro de una frase ("la tarifa del ISR {etiqueta}
# de 2026"). No es la misma lista que `ETIQUETAS_TARIFA` de `app.services.tarifa_isr`: esa es
# para una columna de pantalla y lleva una aclaración entre paréntesis ("Quincenal (15 días)");
# aquí basta con el adjetivo. Solo cubre las periodicidades que `PARA_CFDI` puede producir —
# `EJERCICIO` nunca sale de traducir una clave de CFDI, así que no hace falta aquí.
_ETIQUETAS_PERIODICIDAD_TARIFA: Final[dict[PeriodicidadTarifa, str]] = {
    PeriodicidadTarifa.DIARIA: "diaria",
    PeriodicidadTarifa.DIAS_7: "semanal (7 días)",
    PeriodicidadTarifa.DIAS_10: "decenal (10 días)",
    PeriodicidadTarifa.DIAS_15: "quincenal (15 días)",
    PeriodicidadTarifa.MENSUAL: "mensual",
}

# Orden fijo en el que se enumeran las periodicidades dentro del `detalle`, para que el mensaje
# no cambie de redacción según el orden en que la consulta agregada devuelva las filas (un
# `GROUP BY` sin `ORDER BY` no promete ningún orden). No es el alfabético de `.value`: ese
# dejaría "DIAS_10" antes que "DIAS_15" y que "DIAS_7" (comparando texto, no número), un orden
# que no se parece a como el Anexo 8 presenta sus tablas. Este es el orden natural: de la
# periodicidad más corta a la más larga.
_ORDEN_PERIODICIDAD_TARIFA: Final[tuple[PeriodicidadTarifa, ...]] = (
    PeriodicidadTarifa.DIARIA,
    PeriodicidadTarifa.DIAS_7,
    PeriodicidadTarifa.DIAS_10,
    PeriodicidadTarifa.DIAS_15,
    PeriodicidadTarifa.MENSUAL,
)

# Clave de `configuracion` donde la tarea del beat deja el resultado del último intento de
# sincronización. Vive en la base y no en memoria porque quien tiene que ver el fallo es el
# administrador desde `GET /v1/configuracion/fiscal`, en otro proceso que el worker.
CLAVE_ESTADO_SINCRONIZACION: Final = "sync_banxico_estado"

# Interruptor de la automatización, misma convención que las otras cuatro de /admin/config.
CLAVE_AUTOMATIZACION: Final = "auto_vigencia_fiscal"

SERIE_TIPO_CAMBIO_USD: Final = "SF43718"  # FIX, pesos por dólar, publicado en el DOF
_URL_SERIE: Final = "https://www.banxico.org.mx/SieAPIRest/service/v1/series/{serie}/datos/oportuno"

# Tiempo de espera **explícito**, nunca sin límite: esta llamada corre dentro de una tarea del
# beat, y una conexión colgada dejaría un worker ocupado indefinidamente. 5 s para conectar
# (si Banxico no acepta la conexión en 5 s, no va a contestar) y 15 s en total.
_ESPERA: Final = httpx.Timeout(15.0, connect=5.0)

# Margen de la guarda de plausibilidad: 50% de desviación relativa contra el valor anterior.
#
# Por qué 50 y no otro número. El margen tiene que dejar pasar los movimientos reales y atrapar
# el dedazo y el parseo de la columna equivocada, que son de otro orden:
#   - Movimientos reales que DEBE tolerar: el salario mínimo general subió 13% en 2026 y 22% en
#     2019 (el mayor incremento anual del régimen general en el periodo reciente); la UMA se
#     mueve alrededor de la inflación (3-8%); el tipo de cambio no varía ni 5% entre dos días
#     hábiles consecutivos.
#   - Errores que DEBE atrapar: 117.31 tecleado como 11731 (x100), un punto decimal corrido
#     (x10 o /10), y una columna equivocada del PDF/JSON, que casi siempre cambia el orden de
#     magnitud.
# 50% deja ~2.3x de holgura sobre el mayor movimiento real conocido del régimen general y sigue
# a un orden de magnitud de distancia del error más pequeño que hay que atrapar. El único caso
# real que marca es la duplicación del mínimo de la ZLFN por decreto en 2019 (88.36 -> 176.72), y
# marcarlo es correcto: duplicar un salario mínimo es un hecho que merece que una persona lo mire
# antes de que entre a un cálculo, no que un script lo dé por bueno.
#
# No es un importe fiscal (§2.12): es un umbral de validación, como `_VALOR_MAXIMO` en
# `configuracion_fiscal`. No cambia por decreto.
_MARGEN_PLAUSIBILIDAD: Final[Decimal] = Decimal("0.50")

# A partir de cuántos meses se considera vieja la versión instalada de `satcfdi`. Un año: es el
# ciclo con el que el SAT publica cambios de catálogo, y un umbral más corto convertiría el aviso
# en ruido de fondo (que es como se desactivan los avisos).
_MESES_MAX_SATCFDI: Final = 12


class ErrorDeSincronizacion(RuntimeError):
    """La sincronización no se pudo hacer. **Nunca** se traduce en "no había nada que traer".

    Quien la atrape tiene que dejar rastro visible (log + `CLAVE_ESTADO_SINCRONIZACION`), no
    seguir como si la corrida hubiera ido bien: un valor viejo con cara de vigente es peor que
    un valor ausente.
    """


class SincronizacionNoConfigurada(ErrorDeSincronizacion):
    """Falta el token de Banxico. Se distingue del fallo de red porque la acción es otra: aquí
    hay que ir a `BANXICO_TOKEN`, no a esperar a que el servicio vuelva."""


class SincronizacionFallida(ErrorDeSincronizacion):
    """La API respondió mal, no respondió, o respondió algo con otra forma de la esperada."""


@dataclass(frozen=True)
class AlertaVigencia:
    """Un valor (o una pieza de maquinaria) que necesita atención, con lo que hace falta para
    saber **qué hacer**.

    `vigencia_desde` es la del renglón del que habla la alerta: el confirmado que caducó
    (`CADUCADO`), la propuesta que espera un clic (`SIN_CONFIRMAR`), o `None` cuando no hay
    ningún renglón (`AUSENTE` y las alertas de maquinaria).

    `fecha_esperada` es la fecha de actualización del calendario que ya pasó y que el valor
    debería cubrir. `None` en las alertas de maquinaria, que no tienen una.

    `detalle` es la frase que la pantalla enseña. Existe porque `motivo` es una etiqueta de
    máquina y las alertas de maquinaria no se explican solas: "el catálogo de `satcfdi` no se
    puede leer" no se deduce de `CATALOGO_ILEGIBLE`.
    """

    clave: str
    motivo: MotivoAlerta
    vigencia_desde: date | None
    fecha_esperada: date | None
    detalle: str = ""


def _ahora() -> datetime:
    """`datetime` sin zona, como todas las columnas `DateTime` del proyecto (naive en UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------------------
# Guarda de plausibilidad
# --------------------------------------------------------------------------------------


def desviacion_relativa(anterior: Decimal, nuevo: Decimal) -> Decimal:
    """|nuevo - anterior| / anterior, en `Decimal` de punta a punta. `anterior` debe ser > 0."""
    return abs(nuevo - anterior) / anterior


def es_implausible(anterior: Decimal, nuevo: Decimal) -> bool:
    """Si `nuevo` se desvía de `anterior` más allá del margen (ver `_MARGEN_PLAUSIBILIDAD`).

    **No rechaza nada**: quien la llama propone el valor igual, pero marcado, con la desviación
    calculada a la vista de quien va a confirmarlo. Descartarlo en silencio sería el mismo
    pecado al revés — dejar el valor viejo puesto sin decir que llegó uno nuevo.

    Con `anterior <= 0` devuelve `True`: no hay contra qué comparar, y que exista un valor no
    positivo en `param_fiscal` (que `guardar_param_fiscal` rechaza) ya es motivo de revisión.
    """
    if anterior <= 0:
        return True
    return desviacion_relativa(anterior, nuevo) > _MARGEN_PLAUSIBILIDAD


# --------------------------------------------------------------------------------------
# La alarma de calendario
# --------------------------------------------------------------------------------------


def fecha_de_actualizacion_aplicable(clave: str, hoy: date) -> date | None:
    """La última fecha de actualización de `clave` que **ya pasó** (incluyendo hoy).

    En enero de 2026 la de la UMA es el 1 de febrero de **2025**, no el de 2026: el valor de
    febrero de 2025 sigue siendo el vigente y no hay nada que reclamar. Ese matiz es lo que
    separa "estás desactualizado" de "todavía no toca".
    """
    calendario = FECHAS_DE_ACTUALIZACION.get(clave)
    if calendario is None:
        return None
    mes, dia = calendario
    del_anio = date(hoy.year, mes, dia)
    return del_anio if del_anio <= hoy else date(hoy.year - 1, mes, dia)


def _alerta_de_clave(clave: str, tramos: list[ParamFiscal], hoy: date) -> AlertaVigencia | None:
    esperada = fecha_de_actualizacion_aplicable(clave, hoy)
    if esperada is None:  # pragma: no cover — solo se llama con claves del calendario
        return None
    if not tramos:
        return AlertaVigencia(
            clave=clave,
            motivo="AUSENTE",
            vigencia_desde=None,
            fecha_esperada=esperada,
            detalle=(
                f"No hay ningún valor capturado para `{clave}`, y su fecha de actualización "
                f"({esperada.isoformat()}) ya pasó. Captúralo desde Configuración → Fiscal con su fuente "
                "oficial; mientras tanto los informes que dependen de él salen degradados."
            ),
        )

    confirmados = [t for t in tramos if t.confirmado_en is not None]
    propuestos = [t for t in tramos if t.confirmado_en is None]
    confirmado = max(confirmados, key=lambda t: t.vigencia_desde) if confirmados else None
    propuesto = max(propuestos, key=lambda t: t.vigencia_desde) if propuestos else None

    # "Al día" son **dos** cosas, y confundirlas era el defecto: que el tramo confirmado más
    # reciente sea del periodo que toca, y que **haya un tramo confirmado que cubra hoy**. Sin la
    # segunda, un tramo confirmado y luego cerrado antes de hoy (`vigencia_hasta` en el pasado y
    # sin sucesor) salía "al día" mientras `valor_vigente(hoy)` devolvía `None` y B-03 y B-10
    # emitían `FALTA_UMA` / `FALTA_SALARIO_MINIMO`: la alarma decía "todo en orden" justo cuando
    # los informes decían que no. Y no es un caso de laboratorio: cerrar el tramo anterior a mano
    # es el procedimiento **obligatorio** del módulo (`guardar_param_fiscal` no lo cierra solo, a
    # propósito), así que teclear mal ese `vigencia_hasta` es el dedazo natural del proceso.
    #
    # La comprobación es sobre **todos** los confirmados y no sobre el más reciente, porque
    # `max()` puede ser un tramo futuro confirmado por adelantado (la UMA de febrero, confirmada
    # en enero) mientras el que cubre hoy es el anterior: exigirle a ese máximo que cubra hoy
    # habría encendido una alarma falsa en el caso legítimo.
    cubre_hoy = any(t.vigencia_desde <= hoy and (t.vigencia_hasta is None or t.vigencia_hasta >= hoy) for t in confirmados)
    al_dia = confirmado is not None and confirmado.vigencia_desde >= esperada and cubre_hoy
    if not al_dia:
        # Hay una propuesta que **sí** cubre el periodo: confirmarla resuelve el problema, y eso
        # es un clic. Distinguirlo de "ve a capturar" es lo que hace la alarma accionable.
        if propuesto is not None and propuesto.vigencia_desde >= esperada:
            return AlertaVigencia(
                clave=clave,
                motivo="SIN_CONFIRMAR",
                vigencia_desde=propuesto.vigencia_desde,
                fecha_esperada=esperada,
                detalle=(
                    f"`{clave}` tiene un valor propuesto ({propuesto.valor}, vigente desde "
                    f"{propuesto.vigencia_desde.isoformat()}, fuente: {propuesto.fuente}) esperando "
                    "confirmación. Hasta que alguien lo revise y lo confirme no entra a ningún cálculo."
                ),
            )
        # El hueco: lo confirmado es del periodo que toca, pero **ninguno cubre hoy**. Se
        # informa aparte porque la acción es otra —revisar el `vigencia_hasta` que alguien
        # tecleó al cerrar, o capturar el sucesor— y el mensaje genérico de abajo diría algo
        # falso ("arranca antes de la fecha de actualización", cuando arranca después).
        if confirmado is not None and confirmado.vigencia_desde >= esperada and not cubre_hoy:
            cerrado = confirmado.vigencia_hasta
            return AlertaVigencia(
                clave=clave,
                motivo="CADUCADO",
                vigencia_desde=confirmado.vigencia_desde,
                fecha_esperada=esperada,
                detalle=(
                    f"`{clave}` tiene un tramo confirmado ({confirmado.valor}, desde "
                    f"{confirmado.vigencia_desde.isoformat()}) que "
                    + (
                        f"se cerró el {cerrado.isoformat()}"
                        if cerrado is not None
                        else f"todavía no arranca (empieza el {confirmado.vigencia_desde.isoformat()})"
                    )
                    + ", así que hoy no hay ningún valor vigente y los informes lo reportan como "
                    "faltante aunque la tabla parezca completa. Revisa si el `vigencia_hasta` se "
                    "tecleó mal al cerrar el tramo, o captura el tramo que cubre hoy."
                ),
            )

        # Lo único que hay es de antes de la fecha de actualización. Aunque esté sin confirmar,
        # el motivo es la caducidad: confirmar una propuesta de 2025 no arregla que falte la de
        # 2026, y la acción que toca es capturar el valor del ejercicio.
        actual = confirmado if confirmado is not None else propuesto
        assert actual is not None  # `tramos` no está vacío y todo tramo es confirmado o propuesto
        estado = "confirmado" if confirmado is not None else "propuesto y sin confirmar"
        return AlertaVigencia(
            clave=clave,
            motivo="CADUCADO",
            vigencia_desde=actual.vigencia_desde,
            fecha_esperada=esperada,
            detalle=(
                f"El valor más reciente de `{clave}` ({actual.valor}, {estado}) arranca el "
                f"{actual.vigencia_desde.isoformat()}, antes de la fecha de actualización "
                f"{esperada.isoformat()}, que ya pasó. Busca el valor del ejercicio en curso en su "
                "publicación oficial y captúralo cerrando el tramo anterior."
            ),
        )

    # Está al día, pero encima hay una propuesta más nueva que nadie ha mirado (una fe de
    # erratas, otra semilla, una corrección). Sin este aviso quedaría invisible para siempre.
    if propuesto is not None and confirmado is not None and propuesto.vigencia_desde > confirmado.vigencia_desde:
        return AlertaVigencia(
            clave=clave,
            motivo="SIN_CONFIRMAR",
            vigencia_desde=propuesto.vigencia_desde,
            fecha_esperada=esperada,
            detalle=(
                f"`{clave}` está al día, pero hay un tramo más reciente propuesto ({propuesto.valor}, "
                f"desde {propuesto.vigencia_desde.isoformat()}, fuente: {propuesto.fuente}) esperando "
                "confirmación. Mientras no se confirme, los cálculos siguen usando el anterior."
            ),
        )
    return None


def _tipos_percepcion() -> list[tuple[str, str]]:
    """Indirección de un renglón sobre `catalogos.tipos_de_estricto('P')`, para que la alarma
    pueda comprobar la legibilidad del catálogo sin importar `app.informes` en el encabezado
    (import perezoso: abre un sqlite y despickla 44 renglones) y para poder ejercitarla."""
    from app.informes.catalogos import tipos_de_estricto

    return tipos_de_estricto("P")


def _version_de_satcfdi() -> str | None:
    try:
        return _version_instalada("satcfdi")
    except PackageNotFoundError:  # pragma: no cover — satcfdi es dependencia dura
        return None


def _alerta_del_catalogo() -> AlertaVigencia | None:
    """El catálogo `c_TipoPercepcion` de `satcfdi`, que decide si una marca se puede capturar."""
    from app.informes.catalogos import CatalogoIlegible

    try:
        tipos = _tipos_percepcion()
    except CatalogoIlegible as exc:
        motivo_tecnico = str(exc)
    else:
        if tipos:
            return None
        motivo_tecnico = "el catálogo se leyó pero no trae ningún tipo"
    return AlertaVigencia(
        clave=CLAVE_CATALOGO_SAT,
        motivo="CATALOGO_ILEGIBLE",
        vigencia_desde=None,
        fecha_esperada=None,
        detalle=(
            f"No se puede leer el catálogo `c_TipoPercepcion` de `satcfdi` ({motivo_tecnico}). "
            "Mientras dure: capturar o confirmar marcas de percepción responde 503 (no se escribe sin "
            "poder validar) y el informe B-01 se genera sin las columnas de catálogo. Revisa la "
            "instalación de `satcfdi` en el contenedor de la API."
        ),
    )


def _alerta_de_la_libreria(hoy: date) -> AlertaVigencia | None:
    """`satcfdi` versiona por fecha (`AA.M.micro`: 26.7.4 = julio de 2026), así que su edad se
    calcula sin consultar PyPI — la alarma tampoco depende de internet aquí.

    Si el esquema de versiones cambiara y no se pudiera interpretar, **se avisa igual** en vez
    de desactivar la comprobación en silencio: una comprobación que se apaga sola es el mismo
    fallo silencioso que este módulo entero existe para evitar.
    """
    version = _version_de_satcfdi()
    if version is None:  # pragma: no cover — satcfdi es dependencia dura
        return None
    partes = version.split(".")
    anio = mes = None
    if len(partes) >= 2 and partes[0].isdigit() and partes[1].isdigit():
        posible_anio, posible_mes = int(partes[0]), int(partes[1])
        # CalVer plausible: año de dos dígitos de este siglo y un mes real.
        if 20 <= posible_anio <= 99 and 1 <= posible_mes <= 12:
            anio, mes = 2000 + posible_anio, posible_mes
    if anio is None or mes is None:
        return AlertaVigencia(
            clave=CLAVE_VERSION_SATCFDI,
            motivo="LIBRERIA_DESACTUALIZADA",
            vigencia_desde=None,
            fecha_esperada=None,
            detalle=(
                f"La versión instalada de `satcfdi` ({version}) no se puede leer como fecha (`AA.M.micro`), "
                "así que esta comprobación no puede decir si está al día. Revísalo a mano: si el SAT publicó "
                "claves nuevas de `c_TipoPercepcion`, se rechazarán al capturarlas hasta que se actualice."
            ),
        )
    meses = (hoy.year - anio) * 12 + (hoy.month - mes)
    if meses < _MESES_MAX_SATCFDI:
        return None
    return AlertaVigencia(
        clave=CLAVE_VERSION_SATCFDI,
        motivo="LIBRERIA_DESACTUALIZADA",
        vigencia_desde=None,
        fecha_esperada=None,
        detalle=(
            f"La versión instalada de `satcfdi` ({version}) es de {mes:02d}/{anio} — {meses} meses. De ahí "
            "sale el catálogo `c_TipoPercepcion` contra el que se validan las marcas de percepción: si el "
            "SAT publicó claves nuevas, capturarlas devuelve 422 hasta que se actualice la librería, y el "
            "síntoma parece un error de captura. Actualiza `satcfdi` en `pyproject.toml`/`requirements.txt`."
        ),
    )


async def _alerta_de_sincronizacion(db: AsyncSession) -> AlertaVigencia | None:
    """El resultado del último intento de la tarea del beat, tal como lo dejó en `configuracion`."""
    estado = await config_repo.valor(db, CLAVE_ESTADO_SINCRONIZACION, None)
    if not isinstance(estado, dict):
        return None
    fallo = estado.get("fallo")
    if not fallo:
        return None
    cuando = estado.get("cuando")
    return AlertaVigencia(
        clave=CLAVE_BANXICO,
        motivo="SINCRONIZACION_FALLIDA",
        vigencia_desde=None,
        fecha_esperada=None,
        detalle=(
            f"El último intento de sincronizar el tipo de cambio con Banxico falló{f' ({cuando})' if cuando else ''}: "
            f"{fallo}. Mientras no se resuelva, `TIPO_CAMBIO_USD` deja de recibir valores nuevos; captúralo a "
            "mano desde Configuración → Fiscal si algún informe lo necesita."
        ),
    )


def _enumera(textos: Sequence[str]) -> str:
    """Une textos al estilo español: `"a"`, `"a y b"`, `"a, b y c"`. Sin esto, un `", ".join`
    simple dejaría "a, b, y c" (con una coma de más antes del "y") o "a, b, c" (sin "y" y con
    ambigüedad de si la lista sigue). Los nombres de periodicidad no llevan comas propias, así
    que no hay que escapar nada."""
    lista = list(textos)
    if len(lista) <= 1:
        return "".join(lista)
    return f"{', '.join(lista[:-1])} y {lista[-1]}"


async def _alertas_de_tarifa(db: AsyncSession, hoy: date) -> list[AlertaVigencia]:
    """Falta la tarifa del ejercicio en curso para alguna periodicidad **que la nómina
    realmente timbra**. Devuelve **como mucho una** alerta (ver el comentario de
    `CLAVE_TARIFA_ISR`): si faltan varias periodicidades, se enumeran todas dentro del mismo
    `detalle` en vez de repetir la alerta una vez por cada una.

    Solo las periodicidades observadas, no las cinco que `PARA_CFDI` sabe traducir. Exigir la
    tarifa de 10 días que ninguna empresa usa dejaría la alarma permanentemente encendida, que
    es el argumento que este módulo ya tiene escrito para dejar el tipo de cambio fuera de
    `FECHAS_DE_ACTUALIZACION`: *"una alarma siempre encendida es una alarma que se aprende a
    ignorar"*.

    Si no hay nómina normalizada no hay nada que recalcular, y por eso el conjunto vacío no
    alerta: la ausencia de datos no es una configuración pendiente. Lo mismo si toda la nómina
    observada cae en periodicidades que el Anexo no publica (catorcenal, bimestral, etc.): no
    hay ninguna tarifa que exigir.

    A diferencia de `_alerta_de_clave`, no hay motivo `CADUCADO`: la tarifa del ISR no tiene
    tramos de vigencia dentro del año (es una tabla por `(ejercicio, periodicidad)`, no un
    valor con `vigencia_desde`/`vigencia_hasta`), así que "vieja" y "ausente" son la misma
    cosa aquí — o existe la del ejercicio en curso, o no existe.

    Usa `repo_tarifa.obtener` (confirmada o propuesta) y no `repo_tarifa.vigente` (solo
    confirmada): la alarma necesita distinguir `AUSENTE` de `SIN_CONFIRMAR`, y `vigente`
    colapsa las dos en `None`.

    Cuando hay periodicidades de los dos grupos a la vez, el `motivo` de la única alerta es
    `AUSENTE`: es el caso más grave (ni siquiera hay un documento cargado) y el que exige la
    acción más urgente. El `detalle` no colapsa la distinción —dice separado qué falta *cargar*
    y qué falta *confirmar*—, porque son dos acciones distintas y quien lee la alerta necesita
    saber cuál le toca a cada periodicidad, no solo que "algo" falta.
    """
    observadas = await cfg.periodicidades_pago_observadas(db)
    periodicidades_observadas = {
        p for clave, _n in observadas if (p := reglas_tarifa.PARA_CFDI.get(clave)) is not None
    }
    if not periodicidades_observadas:
        return []

    ausentes: list[str] = []
    sin_confirmar: list[str] = []
    for periodicidad in _ORDEN_PERIODICIDAD_TARIFA:
        if periodicidad not in periodicidades_observadas:
            continue
        # Acotado a como mucho cinco periodicidades (regla 11): nunca una consulta por CFDI ni
        # por empresa, la misma proporción que ya acepta `_tarifa_a_salida` en la API.
        tarifa = await repo_tarifa.obtener(db, ejercicio=hoy.year, periodicidad=periodicidad)
        etiqueta = _ETIQUETAS_PERIODICIDAD_TARIFA[periodicidad]
        if tarifa is None:
            ausentes.append(etiqueta)
        elif not tarifa.confirmada:
            sin_confirmar.append(etiqueta)

    if not ausentes and not sin_confirmar:
        return []

    partes: list[str] = []
    if ausentes:
        partes.append(
            f"Falta cargar la tarifa del ISR de {hoy.year} para: {_enumera(ausentes)}. Descarga el "
            "Anexo 8 de la Resolución Miscelánea Fiscal del portal del SAT (sat.gob.mx → "
            "Normatividad → RMF → Anexos) y súbelo en Configuración → Fiscal."
        )
    if sin_confirmar:
        partes.append(
            f"Está cargada pero sin confirmar la tarifa del ISR de {hoy.year} para: "
            f"{_enumera(sin_confirmar)}. Revísala en Configuración → Fiscal y confírmala; mientras "
            "tanto no entra a ningún cálculo."
        )

    return [
        AlertaVigencia(
            clave=CLAVE_TARIFA_ISR,
            motivo="AUSENTE" if ausentes else "SIN_CONFIRMAR",
            vigencia_desde=None,
            fecha_esperada=date(hoy.year, 1, 1),
            detalle=" ".join(partes),
        )
    ]


async def alertas_de_vigencia(db: AsyncSession, hoy: date) -> list[AlertaVigencia]:
    """Todo lo que necesita atención hoy: valores caducados, propuestas esperando un clic,
    claves sin capturar, tarifas del ISR que faltan, y la maquinaria averiada.

    Una sola consulta para los valores del calendario (regla 11), una más (acotada) para la
    tarifa del ISR, y ninguna llamada de red: la alarma tiene que funcionar exactamente igual
    con el cable desconectado.
    """
    filas = list(
        (await db.scalars(select(ParamFiscal).where(ParamFiscal.clave.in_(FECHAS_DE_ACTUALIZACION)))).all()
    )
    por_clave: dict[str, list[ParamFiscal]] = {}
    for fila in filas:
        por_clave.setdefault(fila.clave, []).append(fila)

    alertas = [
        alerta
        for clave in sorted(FECHAS_DE_ACTUALIZACION)
        if (alerta := _alerta_de_clave(clave, por_clave.get(clave, []), hoy)) is not None
    ]
    alertas.extend(await _alertas_de_tarifa(db, hoy))
    for alerta_maquinaria in (_alerta_del_catalogo(), _alerta_de_la_libreria(hoy), await _alerta_de_sincronizacion(db)):
        if alerta_maquinaria is not None:
            alertas.append(alerta_maquinaria)
    return alertas


# --------------------------------------------------------------------------------------
# Sincronización del tipo de cambio con la API SIE de Banxico
# --------------------------------------------------------------------------------------


def _token_banxico() -> str | None:
    """El token del SIE, desde `app/core/config.py`. **Jamás incrustado**: es una credencial,
    aunque sea gratuita y de datos públicos. Vacío = sincronización deshabilitada (fail-closed:
    la alarma lo dice, no se finge que no hace falta)."""
    token = get_settings().banxico_token.strip()
    return token or None


def _leer_datos(cuerpo: object, serie: str) -> list[tuple[date, Decimal]]:
    """Traduce la respuesta del SIE a `(fecha, valor)`, con `Decimal` **desde cadena**.

    Banxico manda `{"bmx": {"series": [{"idSerie": ..., "datos": [{"fecha": "05/08/2026",
    "dato": "18.4321"}]}]}}`. Dos detalles que importan:

    - **`dato` llega como cadena y se convierte desde cadena.** `Decimal(float("18.4321"))` da
      18.432099999999998... : el error de representación entra antes de que nadie pueda revisar
      el número, y la fila guardada ya no es la que publicó Banxico.
    - **`"N/E"` (no existe) se descarta, no se vuelve cero.** Un cero en un tipo de cambio es
      una mentira, no una ausencia (misma regla que `valor_vigente`).

    Cualquier otra forma es un `SincronizacionFallida`: si Banxico cambia el JSON, el síntoma
    tiene que ser un error, no una corrida silenciosa que no propuso nada.
    """
    if not isinstance(cuerpo, dict):
        raise SincronizacionFallida(f"la respuesta del SIE para la serie {serie} no es un objeto JSON.")
    bmx = cuerpo.get("bmx")
    series = bmx.get("series") if isinstance(bmx, dict) else None
    if not isinstance(series, list) or not series:
        raise SincronizacionFallida(
            f"la respuesta del SIE para la serie {serie} no trae `bmx.series` con al menos una serie "
            f"(llegó: {str(cuerpo)[:200]}). Revisa si cambió el formato de la API."
        )
    primera = series[0]
    datos = primera.get("datos") if isinstance(primera, dict) else None
    if datos is None:
        # El SIE responde 200 con la serie y sin `datos` cuando no hay observaciones en el rango.
        return []
    if not isinstance(datos, list):
        raise SincronizacionFallida(f"`bmx.series[0].datos` de la serie {serie} no es una lista.")

    observaciones: list[tuple[date, Decimal]] = []
    for cruda in datos:
        if not isinstance(cruda, dict):
            raise SincronizacionFallida(f"una observación de la serie {serie} no es un objeto: {cruda!r}.")
        texto_fecha, texto_valor = cruda.get("fecha"), cruda.get("dato")
        if not isinstance(texto_fecha, str) or not isinstance(texto_valor, str):
            raise SincronizacionFallida(
                f"una observación de la serie {serie} no trae `fecha` y `dato` como cadenas: {cruda!r}."
            )
        if texto_valor.strip().upper() in {"N/E", "N/A", ""}:
            continue  # no hay dato ese día (día inhábil); no es un cero
        try:
            dia, mes, anio = (int(parte) for parte in texto_fecha.strip().split("/"))
            fecha = date(anio, mes, dia)
        except ValueError as exc:
            raise SincronizacionFallida(
                f"la fecha {texto_fecha!r} de la serie {serie} no tiene el formato dd/mm/aaaa del SIE."
            ) from exc
        try:
            valor = Decimal(texto_valor.strip().replace(",", ""))
        except InvalidOperation as exc:
            raise SincronizacionFallida(
                f"el dato {texto_valor!r} de la serie {serie} no es un número decimal."
            ) from exc
        observaciones.append((fecha, valor))
    return observaciones


async def _consultar_serie(serie: str, token: str) -> list[tuple[date, Decimal]]:
    """Pide el dato oportuno (el más reciente disponible) de una serie del SIE.

    El token viaja en el encabezado `Bmx-Token`, nunca en la URL: una URL acaba en los logs de
    acceso de cualquier proxy que haya en medio.
    """
    url = _URL_SERIE.format(serie=serie)
    try:
        async with httpx.AsyncClient(timeout=_ESPERA) as cliente:
            respuesta = await cliente.get(url, headers={"Bmx-Token": token, "Accept": "application/json"})
            respuesta.raise_for_status()
            cuerpo: object = respuesta.json()
    except httpx.HTTPStatusError as exc:
        detalle = "token rechazado" if exc.response.status_code in (401, 403) else exc.response.text[:200]
        raise SincronizacionFallida(
            f"el SIE de Banxico respondió {exc.response.status_code} para la serie {serie}: {detalle}"
        ) from exc
    except httpx.HTTPError as exc:
        raise SincronizacionFallida(f"no se pudo consultar la serie {serie} en el SIE de Banxico: {exc}") from exc
    except ValueError as exc:
        raise SincronizacionFallida(f"el SIE devolvió algo que no es JSON para la serie {serie}: {exc}") from exc
    return _leer_datos(cuerpo, serie)


async def _valor_anterior(db: AsyncSession, clave: str, antes_de: date) -> Decimal | None:
    """El valor del tramo más reciente de `clave` anterior a `antes_de`, confirmado o no.

    Sin filtrar por confirmación **a propósito**: esto alimenta la guarda de plausibilidad, y lo
    que hay que comparar es contra el último dato conocido de la serie. Exigir que estuviera
    confirmado dejaría la guarda ciega justo donde más sirve —una serie diaria que nadie
    confirma— y no proteger nada es peor que comparar contra una propuesta.
    """
    stmt = (
        select(ParamFiscal.valor)
        .where(ParamFiscal.clave == clave, ParamFiscal.vigencia_desde < antes_de)
        .order_by(ParamFiscal.vigencia_desde.desc())
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


def _fuente_banxico(fecha: date, anterior: Decimal | None, nuevo: Decimal) -> str:
    """La procedencia que verá quien confirme, con la marca de sospecha si la hay.

    La marca va en `fuente` y no en un campo aparte porque `fuente` es lo que la pantalla enseña
    al lado del botón de confirmar; una bandera que no llega a esos ojos no defiende de nada.
    """
    base = (
        f"Banxico, API SIE serie {SERIE_TIPO_CAMBIO_USD} (tipo de cambio FIX, pesos por dólar), "
        f"observación del {fecha.isoformat()}"
    )
    if anterior is None or not es_implausible(anterior, nuevo):
        return base
    porcentaje = (desviacion_relativa(anterior, nuevo) * 100).quantize(Decimal("0.1"))
    return (
        f"{base} — SOSPECHOSO: se desvía {porcentaje}% del valor anterior ({anterior}). Una desviación así "
        "suele ser un dedazo o un parseo de la columna equivocada; verifícalo contra el DOF antes de confirmar."
    )


async def sincronizar_tipo_cambio(db: AsyncSession, *, hoy: date) -> int:
    """Trae el tipo de cambio FIX de Banxico y lo **propone**. Devuelve cuántos valores escribió.

    No confirma nada (`origen: SINCRONIZADO`, `confirmado_en` nulo) y no hace `commit`: la
    transacción es de quien llama, para que la bitácora de la regla 8 entre con las escrituras.

    Cada observación se guarda como un tramo **cerrado de un día** (`vigencia_desde ==
    vigencia_hasta == la fecha del dato`). No es un detalle: si se guardaran abiertos,
    `guardar_param_fiscal` rechazaría el segundo por solapamiento, y con razón — un tipo de
    cambio no está "vigente hasta nuevo aviso", vale para el día que Banxico lo publicó.

    Es idempotente: una observación que ya está en la base con el mismo valor no se reescribe (la
    tarea es diaria y `oportuno` repite el último dato durante un puente; reescribirla tocaría la
    `fuente` de una fila que quizá alguien ya confirmó).
    """
    token = _token_banxico()
    if token is None:
        raise SincronizacionNoConfigurada(
            "falta `BANXICO_TOKEN` en la configuración, así que no se puede consultar el SIE. Consíguelo gratis "
            "en https://www.banxico.org.mx/SieAPIRest/service/v1/token y ponlo en el entorno del worker. "
            "Mientras tanto `TIPO_CAMBIO_USD` solo se puede capturar a mano."
        )
    observaciones = await _consultar_serie(SERIE_TIPO_CAMBIO_USD, token)
    if not observaciones:
        raise SincronizacionFallida(
            f"la serie {SERIE_TIPO_CAMBIO_USD} del SIE no devolvió ninguna observación utilizable. No es "
            "'todo en orden': es la API diciendo algo que este código no supo leer."
        )

    existentes = {
        fila.vigencia_desde: fila
        for fila in (await db.scalars(select(ParamFiscal).where(ParamFiscal.clave == "TIPO_CAMBIO_USD"))).all()
    }
    propuestos = 0
    for fecha, valor in sorted(observaciones):
        if fecha > hoy:
            # Solo puede venir de un parseo mal hecho (dd/mm leído como mm/dd). Escribirla crearía
            # un tramo que empieza en el futuro y que además bloquearía el del día correcto.
            logger.error(
                "sincronizacion fiscal: el SIE devolvió la observación %s, posterior a hoy (%s); se ignora.",
                fecha,
                hoy,
            )
            continue
        previa = existentes.get(fecha)
        if previa is not None and previa.valor == valor:
            continue
        anterior = await _valor_anterior(db, "TIPO_CAMBIO_USD", fecha)
        try:
            fila = await cfg.guardar_param_fiscal(
                db,
                clave="TIPO_CAMBIO_USD",
                valor=valor,
                vigencia_desde=fecha,
                vigencia_hasta=fecha,
                origen=OrigenValor.SINCRONIZADO,
                fuente=_fuente_banxico(fecha, anterior, valor),
                contexto="sincronización Banxico",
            )
        except cfg.ErrorDeConfiguracion as exc:
            # Un tramo capturado a mano y abierto ("hasta nuevo aviso") choca con el del día. No
            # se pisa la captura manual ni se calla: queda en el log y la corrida no lo cuenta.
            logger.error("sincronizacion fiscal: no se pudo proponer el tipo de cambio del %s: %s", fecha, exc)
            continue
        fila.sincronizado_en = _ahora()
        propuestos += 1
    await db.flush()
    return propuestos


def alerta_a_detalle(alerta: AlertaVigencia) -> dict[str, Any]:
    """La alerta en tipos que el `JSON` de `bitacora` sabe guardar."""
    return {
        "clave": alerta.clave,
        "motivo": alerta.motivo,
        "vigencia_desde": alerta.vigencia_desde.isoformat() if alerta.vigencia_desde else None,
        "fecha_esperada": alerta.fecha_esperada.isoformat() if alerta.fecha_esperada else None,
    }
