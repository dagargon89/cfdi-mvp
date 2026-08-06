"""Eje teórico de periodos de pago (ficha B-04, fase 1 del algoritmo).

Módulo puro: no toca BD. Lo consumen B-04 (eje de columnas) y B-07 (continuidad de
descuentos), así que su comportamiento es contrato entre los dos.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.informes import periodos


def test_periodicidad_dominante_es_la_moda() -> None:
    assert periodos.periodicidad_dominante(["04", "04", "05"]) == "04"


def test_periodicidad_dominante_ignora_nulos_y_desconocidas() -> None:
    assert periodos.periodicidad_dominante([None, "99", "04", "04"]) == "04"
    assert periodos.periodicidad_dominante([None, "99"]) is None
    assert periodos.periodicidad_dominante([]) is None


def test_periodicidad_dominante_desempata_de_forma_determinista() -> None:
    """Un empate no puede depender del orden de la lista: dos corridas del mismo informe
    deben producir el mismo eje de columnas."""
    assert periodos.periodicidad_dominante(["05", "04"]) == periodos.periodicidad_dominante(["04", "05"]) == "04"


def test_eje_quincenal_parte_el_mes_en_dos() -> None:
    eje = periodos.construir_eje("04", date(2026, 6, 1), date(2026, 7, 31))
    assert [c.etiqueta for c in eje] == ["2026-06 Q1", "2026-06 Q2", "2026-07 Q1", "2026-07 Q2"]
    assert (eje[0].inicio, eje[0].fin) == (date(2026, 6, 1), date(2026, 6, 15))
    assert (eje[1].inicio, eje[1].fin) == (date(2026, 6, 16), date(2026, 6, 30))
    # Julio tiene 31 días: el segundo corte llega al último día del mes, no al 30.
    assert eje[3].fin == date(2026, 7, 31)


def test_eje_mensual_usa_el_ultimo_dia_de_cada_mes() -> None:
    eje = periodos.construir_eje("05", date(2026, 1, 1), date(2026, 3, 31))
    assert [c.etiqueta for c in eje] == ["2026-01", "2026-02", "2026-03"]
    # Febrero de 2026 no es bisiesto.
    assert eje[1].fin == date(2026, 2, 28)


def test_eje_decenal_parte_el_mes_en_tres() -> None:
    eje = periodos.construir_eje("06", date(2026, 6, 1), date(2026, 6, 30))
    assert [(c.inicio.day, c.fin.day) for c in eje] == [(1, 10), (11, 20), (21, 30)]


def test_eje_semanal_arranca_en_el_primer_corte_observado() -> None:
    """`02` semanal y `03` catorcenal no tienen día fijo del mes: la ficha dice que la
    secuencia arranca en el primer corte observado en los datos."""
    eje = periodos.construir_eje("02", date(2026, 6, 1), date(2026, 6, 28), primer_corte_observado=date(2026, 6, 7))
    assert [c.fin for c in eje][:3] == [date(2026, 6, 7), date(2026, 6, 14), date(2026, 6, 21)]


def test_eje_catorcenal() -> None:
    eje = periodos.construir_eje("03", date(2026, 6, 1), date(2026, 7, 15), primer_corte_observado=date(2026, 6, 14))
    assert [c.fin for c in eje][:3] == [date(2026, 6, 14), date(2026, 6, 28), date(2026, 7, 12)]


def test_eje_semanal_sin_corte_observado_arranca_en_desde() -> None:
    eje = periodos.construir_eje("02", date(2026, 6, 1), date(2026, 6, 21))
    assert eje[0].fin == date(2026, 6, 7)


def test_periodicidad_no_soportada_lanza() -> None:
    with pytest.raises(ValueError):
        periodos.construir_eje("99", date(2026, 6, 1), date(2026, 6, 30))


def test_asignar_a_corte_exacto() -> None:
    eje = periodos.construir_eje("04", date(2026, 6, 1), date(2026, 6, 30))
    assert periodos.asignar_a_corte(eje, date(2026, 6, 30)) == (1, False)
    assert periodos.asignar_a_corte(eje, date(2026, 6, 15)) == (0, False)


def test_asignar_a_corte_irregular_va_al_mas_cercano() -> None:
    """La ficha B-04, fase 2: si `fecha_final_pago` no cae en un corte teórico, se asigna
    al más cercano y se marca `CORTE_IRREGULAR`."""
    eje = periodos.construir_eje("04", date(2026, 6, 1), date(2026, 6, 30))
    indice, irregular = periodos.asignar_a_corte(eje, date(2026, 5, 20))
    assert (indice, irregular) == (0, True)
    indice, irregular = periodos.asignar_a_corte(eje, date(2026, 7, 20))
    assert (indice, irregular) == (1, True)


def test_asignar_a_corte_con_eje_vacio() -> None:
    assert periodos.asignar_a_corte([], date(2026, 6, 30)) == (-1, True)


# Ronda de correcciones 1: el ancla de `_cortes_de_paso_fijo` solo retrocedía. Si el
# ancla ya era anterior a `desde`, la condición de retroceso nunca disparaba y el ancla
# se quedaba fuera del rango, generando un eje corrido (o, con anclas muy antiguas,
# decenas de cortes de sobra empezando años atrás).


def test_eje_semanal_con_ancla_anterior_al_rango_avanza_conservando_fase() -> None:
    """Ancla unos días antes de `desde`: el primer corte debe caer dentro del rango y
    conservar la fase del ancla (la diferencia sigue siendo múltiplo del paso)."""
    eje = periodos.construir_eje("02", date(2026, 6, 1), date(2026, 6, 28), primer_corte_observado=date(2026, 5, 25))
    assert eje[0].fin == date(2026, 6, 1)
    assert (eje[0].fin - date(2026, 5, 25)).days % 7 == 0
    assert [c.fin for c in eje] == [date(2026, 6, 1), date(2026, 6, 8), date(2026, 6, 15), date(2026, 6, 22)]


def test_eje_semanal_con_ancla_muy_anterior_no_genera_cortes_de_sobra() -> None:
    """Ancla de más de un año antes del rango: el número de cortes debe ser el del
    rango pedido, no decenas arrancando en el pasado lejano."""
    eje = periodos.construir_eje("02", date(2026, 6, 1), date(2026, 6, 28), primer_corte_observado=date(2025, 1, 3))
    assert len(eje) == 4
    assert eje[0].fin == date(2026, 6, 5)
    assert (eje[0].fin - date(2025, 1, 3)).days % 7 == 0


def test_eje_semanal_con_ancla_posterior_a_hasta_queda_vacio() -> None:
    """Si el ancla observado cae después de `hasta`, no hay ningún corte teórico dentro
    del rango pedido: el eje queda vacío a propósito, no por un error silencioso."""
    eje = periodos.construir_eje("02", date(2026, 6, 1), date(2026, 6, 3), primer_corte_observado=date(2026, 6, 7))
    assert eje == []
