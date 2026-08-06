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
