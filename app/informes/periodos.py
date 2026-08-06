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
    # Normaliza el ancla en las dos direcciones sin alterar su fase (el resto módulo
    # `paso` respecto al ancla se conserva; solo cambia el punto de arranque).
    # Avanza si el ancla es anterior al rango (p. ej. un ancla de hace más de un año).
    while primer_fin < desde:
        primer_fin += timedelta(days=paso)
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
