"""Resolución de la configuración fiscal que necesita el recálculo del ISR (B-09 y las
columnas anuales de B-05): qué está **confirmado** para una fecha, y qué falta.

Módulo delgado a propósito: **no calcula ISR ni subsidio, solo resuelve y reporta.** La
aritmética vive en `app.services.tarifa_isr` (Task 1); este módulo únicamente junta, por
`(ejercicio, en_fecha)`, la tarifa que aplica a cada periodicidad, la UMA mensual y los dos
parámetros del subsidio al empleo, y las marcas de percepción — y dice, en español llano,
qué le falta a quien administra el Hub para que el informe se pueda generar.

Existe un solo módulo, y no uno por informe, porque **B-09 y B-05 tienen que decir
exactamente lo mismo cuando algo falta**: los textos de `AVISO_SIN_TARIFA`,
`AVISO_SIN_MARCAS` y `BANDERA_SIN_SUBSIDIO` viven aquí, una sola vez, y los dos informes los
citan tal cual en vez de redactar su propia versión.

El invariante heredado, sin excepción: un valor sin confirmar no calcula
------------------------------------------------------------------------
`app.repositories.tarifa_isr.vigente`, `app.services.configuracion_fiscal.valor_vigente` y
`marcas_de_percepcion` devuelven **solo lo confirmado** — sembrar, importar y capturar
proponen; solo una persona activa. Este módulo hereda esa garantía sin reimplementarla: nunca
lee `tarifa_isr`, `param_fiscal` ni `catalogo_percepcion_marca` por su cuenta saltándose el
filtro de confirmación, aunque para las tarifas sí ejecuta su propia consulta (ver más abajo
el porqué) — esa consulta repite el mismo filtro `confirmado_en IS NOT NULL`, nunca lo omite.

Por qué las tarifas no se resuelven llamando a `vigente` una vez por periodicidad (regla 11)
----------------------------------------------------------------------------------------------
`repo.vigente` es la función correcta para *una* tarifa, pero hace dos consultas (cabecera y
renglones) y este módulo necesita resolver hasta cinco periodicidades a la vez (una por cada
valor no nulo de `PARA_CFDI`). Llamarla en un bucle sería un N+1 clásico: el número de
consultas escalaría con la cantidad de periodicidades pedidas, no con el número de tablas.
En vez de eso, `_tarifas_confirmadas` hace **una consulta a `tarifa_isr`** (con
`periodicidad IN (...)`) para saber qué periodicidades están confirmadas, y **una consulta a
`tarifa_isr_renglon`** para traer sus renglones — dos consultas fijas, sin importar si se
piden una periodicidad o las cinco. La UMA mensual y los dos parámetros del subsidio sí se
resuelven con `valor_vigente` (una consulta por clave, tres en total): no dependen de la
periodicidad, así que no hay ningún bucle que colapsar. Las marcas son una sola consulta con
`marcas_de_percepcion`, ya agregada para todo el catálogo.

Las marcas se exigen solo de los tipos que la empresa usó de verdad
----------------------------------------------------------------------
El catálogo `catalogo_percepcion_marca` tiene 44 renglones (uno por `c_TipoPercepcion`), pero
una empresa real timbra dos o tres. Exigir que las 44 estén confirmadas dejaría a esa empresa
sin informe para siempre por tipos que nunca va a pagar. `hay_marcas` y el aviso de marcas
faltantes se acotan siempre a `tipos_presentes`: los tipos que de verdad aparecen en los datos
que se van a procesar, no el catálogo completo.

La degradación es por partes, no todo o nada
--------------------------------------------
Sin tarifa confirmada para alguna periodicidad que aparece en los datos, o sin alguna marca de
los tipos presentes, **el informe no se genera**: un informe con columnas vacías a medias no
sirve, y una base gravada inventada sería peor que ninguna. Sin subsidio (UMA mensual, factor
o tope) el informe **sí se genera**: el ISR determinado se puede calcular sin el subsidio, así
que solo las columnas del subsidio quedan vacías con su bandera. Este módulo no decide cuál de
las dos cosas hacer — eso es del informe —, solo expone `hay_tarifa`, `hay_marcas` y
`hay_subsidio` para que cada uno lo decida por sí mismo, y una lista de `faltantes` ya
redactada para cuando la decisión sea no generar nada.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion_fiscal import CatalogoPercepcionMarca, TarifaIsr, TarifaIsrRenglon
from app.models.enums import PeriodicidadTarifa
from app.services import configuracion_fiscal as cfg
from app.services.tarifa_isr import ETIQUETAS_TARIFA, Renglon

# Claves de `param_fiscal` que necesita el subsidio al empleo (modelo de monto fijo, vigente
# desde la reforma de 2024). `UMA_MENSUAL` también alimenta la mensualización de
# `subsidio_del_periodo`, no solo el subsidio en sí, pero vive aquí porque las tres se
# resuelven juntas por la misma fecha.
_CLAVE_UMA_MENSUAL: Final = "UMA_MENSUAL"
_CLAVE_FACTOR_SUBSIDIO: Final = "SUBSIDIO_FACTOR_UMA"
_CLAVE_TOPE_SUBSIDIO: Final = "SUBSIDIO_TOPE_INGRESO"

# Orden estable para listar periodicidades en un mensaje: el de declaración del enum
# (Diaria, 7, 10, 15, Mensual, Ejercicio), no el alfabético de `.value` — que dejaría
# "DIAS_10" antes que "DIAS_7" y produciría una lista rara de leer.
_ORDEN_PERIODICIDAD: Final[Mapping[PeriodicidadTarifa, int]] = {p: i for i, p in enumerate(PeriodicidadTarifa)}

AVISO_SIN_TARIFA: Final = (
    "No se puede recalcular el ISR porque no hay una tarifa confirmada para {etiquetas} de {ejercicio}. "
    "Descarga el Anexo 8 de la Resolución Miscelánea Fiscal del portal del SAT y súbelo en "
    "Configuración → Fiscal; después confírmala."
)

AVISO_SIN_MARCAS: Final = (
    "No se puede recalcular el ISR porque faltan marcas de percepción confirmadas para el/los tipo(s) "
    "{tipos}, que sí aparecen en los recibos. Revísalas y confírmalas en Configuración → Fiscal → Marcas "
    "de percepción; si alguna no está capturada, cárgala primero con la semilla "
    "`config/fiscal/catalogo_percepcion.yaml`."
)

BANDERA_SIN_SUBSIDIO: Final = (
    "No hay UMA mensual, factor de subsidio al empleo o tope de ingreso confirmados para esta fecha, así "
    "que el informe se generó pero las columnas del subsidio quedaron vacías (el ISR determinado sí se "
    "calculó). Captura y confirma los tres valores en Configuración → Fiscal para completarlas."
)


@dataclass(frozen=True)
class ConfiguracionIsr:
    """Lo que se pudo resolver de la configuración fiscal para un `(ejercicio, en_fecha)`, y
    qué falta. Ningún campo es un importe fiscal codificado en el programa (§2.12): todos
    salen de `tarifa_isr`, `param_fiscal` o `catalogo_percepcion_marca`, resueltos por fecha.

    `tarifas` solo trae las periodicidades **confirmadas**: una periodicidad sin tarifa
    confirmada simplemente no tiene entrada, no una entrada vacía.
    """

    tarifas: Mapping[PeriodicidadTarifa, tuple[Renglon, ...]]
    uma_mensual: Decimal | None
    factor_subsidio: Decimal | None
    tope_subsidio: Decimal | None
    marcas: Mapping[str, CatalogoPercepcionMarca]
    faltantes: tuple[str, ...]

    def hay_tarifa(self, periodicidad: PeriodicidadTarifa) -> bool:
        """Si hay una tarifa **confirmada** con al menos un renglón para esa periodicidad.
        Con la tarifa guardada pero sin confirmar, `resolver` nunca la incluye en `tarifas`,
        así que esto es falso — es el invariante central de todo el subsistema."""
        return bool(self.tarifas.get(periodicidad))

    @property
    def hay_subsidio(self) -> bool:
        """Si los tres valores que exige `subsidio_del_periodo` están confirmados. Los tres o
        ninguno: con solo dos, la fórmula no se puede evaluar igual, así que el informe trata
        la falta de cualquiera de ellos como "sin subsidio", no como un cálculo parcial."""
        return self.uma_mensual is not None and self.factor_subsidio is not None and self.tope_subsidio is not None

    def hay_marcas(self, tipos: Collection[str]) -> bool:
        """Si **todos** los `tipos` pedidos tienen marca confirmada. Se evalúa solo contra los
        tipos que se le pasan — normalmente los que de verdad aparecen en los recibos —, nunca
        contra las 44 claves del catálogo completo del SAT."""
        return all(tipo in self.marcas for tipo in tipos)


async def _tarifas_confirmadas(
    db: AsyncSession, *, ejercicio: int, periodicidades: Sequence[PeriodicidadTarifa]
) -> dict[PeriodicidadTarifa, tuple[Renglon, ...]]:
    """Las tarifas **confirmadas** de `ejercicio` para las `periodicidades` pedidas, con sus
    renglones. Dos consultas fijas —cabeceras y renglones—, nunca una por periodicidad (regla
    11): ver el docstring del módulo para el argumento completo.
    """
    if not periodicidades:
        return {}

    cabeceras = (
        await db.scalars(
            select(TarifaIsr).where(
                TarifaIsr.ejercicio == ejercicio,
                TarifaIsr.periodicidad.in_(periodicidades),
                TarifaIsr.confirmado_en.is_not(None),
            )
        )
    ).all()
    confirmadas = {c.periodicidad for c in cabeceras}
    if not confirmadas:
        return {}

    filas = (
        await db.scalars(
            select(TarifaIsrRenglon)
            .where(
                TarifaIsrRenglon.ejercicio == ejercicio,
                TarifaIsrRenglon.periodicidad.in_(confirmadas),
            )
            .order_by(TarifaIsrRenglon.periodicidad, TarifaIsrRenglon.renglon)
        )
    ).all()

    por_periodicidad: dict[PeriodicidadTarifa, list[Renglon]] = {p: [] for p in confirmadas}
    for f in filas:
        por_periodicidad[f.periodicidad].append(
            Renglon(
                renglon=f.renglon,
                limite_inferior=f.limite_inferior,
                limite_superior=f.limite_superior,
                cuota_fija=f.cuota_fija,
                tasa_excedente=f.tasa_excedente,
            )
        )
    return {p: tuple(renglones) for p, renglones in por_periodicidad.items()}


def _faltantes(
    *,
    ejercicio: int,
    periodicidades: Sequence[PeriodicidadTarifa],
    tarifas: Mapping[PeriodicidadTarifa, tuple[Renglon, ...]],
    tipos_presentes: Collection[str],
    marcas: Mapping[str, CatalogoPercepcionMarca],
    uma_mensual: Decimal | None,
    factor_subsidio: Decimal | None,
    tope_subsidio: Decimal | None,
) -> tuple[str, ...]:
    """Las frases ya redactadas que le faltan al informe, **una por causa** (tarifa, marcas,
    subsidio), nunca una por periodicidad o por tipo: quien lo lee necesita saber qué hacer,
    no una lista de 5 avisos idénticos con distinto nombre de periodicidad."""
    faltantes: list[str] = []

    sin_tarifa = sorted(
        (p for p in dict.fromkeys(periodicidades) if p not in tarifas),
        key=lambda p: _ORDEN_PERIODICIDAD[p],
    )
    if sin_tarifa:
        etiquetas = ", ".join(ETIQUETAS_TARIFA[p] for p in sin_tarifa)
        faltantes.append(AVISO_SIN_TARIFA.format(etiquetas=etiquetas, ejercicio=ejercicio))

    sin_marca = sorted(tipo for tipo in dict.fromkeys(tipos_presentes) if tipo not in marcas)
    if sin_marca:
        faltantes.append(AVISO_SIN_MARCAS.format(tipos=", ".join(sin_marca)))

    hay_subsidio = uma_mensual is not None and factor_subsidio is not None and tope_subsidio is not None
    if not hay_subsidio:
        faltantes.append(BANDERA_SIN_SUBSIDIO)

    return tuple(faltantes)


async def resolver(
    db: AsyncSession,
    *,
    ejercicio: int,
    en_fecha: date,
    periodicidades: Sequence[PeriodicidadTarifa],
    tipos_presentes: Collection[str],
) -> ConfiguracionIsr:
    """Resuelve, para `(ejercicio, en_fecha)`, qué configuración fiscal está confirmada y qué
    falta. No decide si el informe se genera o no — eso es de B-09 y B-05—, solo lo reporta.

    `periodicidades` son las que el informe necesita cubrir (normalmente, las que de verdad
    aparecen en los recibos del rango, traducidas de `c_PeriodicidadPago` con `PARA_CFDI`).
    `tipos_presentes` son los `c_TipoPercepcion` que de verdad aparecen: acotar las marcas
    exigidas a ellos, y no a las 44 del catálogo, es lo que hace posible generar el informe
    para una empresa que solo usa dos o tres tipos.

    Seis consultas en total, fijas sin importar cuántas periodicidades o tipos se pidan (regla
    11): dos para las tarifas (`_tarifas_confirmadas`), tres para los parámetros del subsidio
    (`UMA_MENSUAL`, `SUBSIDIO_FACTOR_UMA`, `SUBSIDIO_TOPE_INGRESO`, una por clave) y una para
    las marcas de percepción.
    """
    tarifas = await _tarifas_confirmadas(db, ejercicio=ejercicio, periodicidades=periodicidades)

    uma_mensual = await cfg.valor_vigente(db, _CLAVE_UMA_MENSUAL, en_fecha)
    factor_subsidio = await cfg.valor_vigente(db, _CLAVE_FACTOR_SUBSIDIO, en_fecha)
    tope_subsidio = await cfg.valor_vigente(db, _CLAVE_TOPE_SUBSIDIO, en_fecha)

    marcas = await cfg.marcas_de_percepcion(db)

    faltantes = _faltantes(
        ejercicio=ejercicio,
        periodicidades=periodicidades,
        tarifas=tarifas,
        tipos_presentes=tipos_presentes,
        marcas=marcas,
        uma_mensual=uma_mensual,
        factor_subsidio=factor_subsidio,
        tope_subsidio=tope_subsidio,
    )

    return ConfiguracionIsr(
        tarifas=tarifas,
        uma_mensual=uma_mensual,
        factor_subsidio=factor_subsidio,
        tope_subsidio=tope_subsidio,
        marcas=marcas,
        faltantes=faltantes,
    )
