"""Troceo de rangos de fechas en ventanas (RF-DESC-01, reglas R1/R2).

Lógica pura, sin dependencias externas ni reloj oculto: la fecha "hoy" se recibe
como parámetro para que el recorte por antigüedad sea determinista y testeable.

- R1: cada ventana no excede ``ventana_meses`` meses calendario.
- R2: la fecha inicial se recorta al tope de antigüedad (~``antiguedad_anios`` años).
- Ventanas contiguas y sin traslape.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

_UN_DIA = timedelta(days=1)


def _sumar_meses(d: date, meses: int) -> date:
    """Suma ``meses`` a ``d`` recortando el día al último válido del mes destino."""
    total = d.month - 1 + meses
    anio = d.year + total // 12
    mes = total % 12 + 1
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(d.day, ultimo_dia))


def _restar_anios(d: date, anios: int) -> date:
    """Resta ``anios`` a ``d`` (maneja 29-feb → 28-feb en año no bisiesto)."""
    try:
        return d.replace(year=d.year - anios)
    except ValueError:
        return d.replace(year=d.year - anios, day=28)


def recortar_inicio(desde: date, hoy: date, antiguedad_anios: int) -> date:
    """Recorta ``desde`` al tope de antigüedad (R2). Devuelve la fecha efectiva."""
    tope = _restar_anios(hoy, antiguedad_anios)
    return max(desde, tope)


def trocear(
    desde: date,
    hasta: date,
    *,
    hoy: date,
    ventana_meses: int = 12,
    antiguedad_anios: int = 5,
) -> list[tuple[date, date]]:
    """Trocea ``[desde, hasta]`` en ventanas contiguas de ≤ ``ventana_meses`` meses.

    Devuelve una lista de tuplas ``(fecha_inicial, fecha_final)`` ordenadas, sin
    traslape. La fecha inicial se recorta primero al tope de antigüedad (R2).

    Cada ventana cubre ``[inicio, min(inicio + ventana_meses - 1 día, hasta)]``,
    de modo que ninguna excede ``ventana_meses`` meses calendario.

    Raises:
        ValueError: si ``hasta < desde``, o si tras el recorte el rango queda vacío.
    """
    if hasta < desde:
        raise ValueError("fecha_final no puede ser anterior a fecha_inicial.")

    inicio_efectivo = recortar_inicio(desde, hoy, antiguedad_anios)
    if hasta < inicio_efectivo:
        raise ValueError(
            "El rango completo es más antiguo que el tope de "
            f"{antiguedad_anios} años; no hay nada que solicitar."
        )

    ventanas: list[tuple[date, date]] = []
    inicio = inicio_efectivo
    while inicio <= hasta:
        # Fin exclusivo = inicio + ventana_meses; fin de ventana = un día antes.
        fin_exclusivo = _sumar_meses(inicio, ventana_meses)
        fin_ventana = min(fin_exclusivo - _UN_DIA, hasta)
        ventanas.append((inicio, fin_ventana))
        inicio = fin_ventana + _UN_DIA
    return ventanas
