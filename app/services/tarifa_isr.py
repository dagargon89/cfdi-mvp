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

# Etiquetas legibles de cada periodicidad (§7.2 del diseño: ninguna etiqueta visible es un nombre
# de enum, ni siquiera uno tan descriptivo como `DIAS_15`). Vive aquí — módulo puro, sin
# dependencias de la capa API ni de SQLAlchemy— porque tanto `app.api.v1.configuracion` (las
# pantallas y los mensajes de error) como `app.services.revision_tarifa` (la hoja del contador)
# la necesitan, y un módulo de servicios no puede depender de un router sin invertir las capas.
ETIQUETAS_TARIFA: Final[Mapping[PeriodicidadTarifa, str]] = {
    PeriodicidadTarifa.DIARIA: "Diaria (por día trabajado)",
    PeriodicidadTarifa.DIAS_7: "Semanal (7 días)",
    PeriodicidadTarifa.DIAS_10: "Decenal (10 días)",
    PeriodicidadTarifa.DIAS_15: "Quincenal (15 días)",
    PeriodicidadTarifa.MENSUAL: "Mensual",
    PeriodicidadTarifa.EJERCICIO: "Anual (cálculo del ejercicio)",
}

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
                "tienen que crecer: si no lo hacen, hay un renglón mal capturado o dos tablas mezcladas."
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


def a_porcentaje(tasa: Decimal) -> Decimal:
    """La tasa como número que un contador lee (`21.36`), no la fracción cruda que guarda la
    columna (`0.2136`). Es el único número de toda la tarifa donde equivocar la escala cambia el
    resultado por cien, así que es también el único punto del sistema que multiplica por 100:
    tanto `app.api.v1.configuracion` (la tabla de renglones de la pantalla) como
    `app.services.revision_tarifa` (la hoja del contador) importan esta función en vez de repetir
    la conversión."""
    return (tasa * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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
