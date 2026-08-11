"""Las reglas puras de una tarifa del ISR: qué la hace válida, cómo se identifica y cómo calcula.

Las seis pruebas de carga del Anexo I.1 del documento fuente viven en `validar`, y se corren tanto
al importar un PDF como al corregir un renglón a mano: es la única forma de que la corrección
manual no reintroduzca el error que el importador evita.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import PeriodicidadTarifa
from app.services import tarifa_isr as t


def _r(n: int, inf: str, sup: str | None, cuota: str, tasa: str) -> t.Renglon:
    return t.Renglon(
        renglon=n,
        limite_inferior=Decimal(inf),
        limite_superior=Decimal(sup) if sup is not None else None,
        cuota_fija=Decimal(cuota),
        tasa_excedente=Decimal(tasa),
    )


def _quincenal() -> list[t.Renglon]:
    """Tarifa de 15 días del Anexo 8 de 2026, con las tasas ya en fracción."""
    return [
        _r(1, "0.01", "416.70", "0.00", "0.0192"),
        _r(2, "416.71", "3537.15", "7.95", "0.0640"),
        _r(3, "3537.16", "6216.15", "207.75", "0.1088"),
        _r(4, "6216.16", "7225.95", "499.20", "0.1600"),
        _r(5, "7225.96", None, "660.75", "0.3500"),
    ]


def test_una_tarifa_real_es_valida() -> None:
    t.validar(_quincenal())


def test_el_primer_renglon_tiene_que_arrancar_en_un_centavo() -> None:
    malos = _quincenal()
    malos[0] = _r(1, "0.00", "416.70", "0.00", "0.0192")
    with pytest.raises(t.TarifaInvalida, match="0.01"):
        t.validar(malos)


def test_un_solape_entre_renglones_se_rechaza_con_el_valor_esperado() -> None:
    """El renglón 4 arranca en 6216.00, dentro del rango del renglón 3 (hasta 6216.15): es un
    solape, no un hueco — el nombre de una prueba es su especificación."""
    malos = _quincenal()
    malos[3] = _r(4, "6216.00", "7225.95", "499.20", "0.1600")
    with pytest.raises(t.TarifaInvalida) as exc:
        t.validar(malos)
    # El mensaje tiene que decir el valor correcto, no solo que algo está mal.
    assert "6216.16" in str(exc.value) and "renglón 4" in str(exc.value)


def test_la_cuota_fija_del_primer_renglon_tiene_que_ser_cero() -> None:
    malos = _quincenal()
    malos[0] = _r(1, "0.01", "416.70", "1.00", "0.0192")
    with pytest.raises(t.TarifaInvalida, match="cuota fija"):
        t.validar(malos)


def test_las_tasas_tienen_que_crecer() -> None:
    malos = _quincenal()
    malos[2] = _r(3, "3537.16", "6216.15", "207.75", "0.0640")
    with pytest.raises(t.TarifaInvalida, match="crecer"):
        t.validar(malos)


def test_una_tasa_en_porcentaje_se_rechaza_diciendo_que_parece_porcentaje() -> None:
    """La prueba 6 del Anexo I.1: el error de escala es el que produce ISR cien veces mayor."""
    malos = [
        _r(1, "0.01", "416.70", "0.00", "1.92"),
        _r(2, "416.71", None, "7.95", "35.00"),
    ]
    with pytest.raises(t.TarifaInvalida, match="porcentaje"):
        t.validar(malos)


def test_la_ultima_tasa_tiene_que_caer_en_el_rango_publicado() -> None:
    malos = _quincenal()
    malos[-1] = _r(5, "7225.96", None, "660.75", "0.2500")
    with pytest.raises(t.TarifaInvalida, match="0.30"):
        t.validar(malos)


def test_solo_el_ultimo_renglon_puede_no_tener_limite_superior() -> None:
    malos = _quincenal()
    malos[2] = _r(3, "3537.16", None, "207.75", "0.1088")
    with pytest.raises(t.TarifaInvalida, match="En adelante"):
        t.validar(malos)


def test_una_tarifa_de_un_solo_renglon_es_una_extraccion_a_medias() -> None:
    with pytest.raises(t.TarifaInvalida, match="incompleta"):
        t.validar([_r(1, "0.01", None, "0.00", "0.3500")])


def test_la_huella_no_depende_de_la_escala_con_la_que_venga_el_decimal() -> None:
    """`Decimal("0.35")` y `Decimal("0.350000")` son el mismo valor: la huella tiene que coincidir,
    porque si no, quien confirma vería un 409 imposible de explicar."""
    a = _quincenal()
    b = _quincenal()
    b[-1] = _r(5, "7225.96", None, "660.7500", "0.35")
    assert t.huella(a) == t.huella(b)


def test_la_huella_cambia_si_cambia_una_cifra() -> None:
    a = _quincenal()
    b = _quincenal()
    b[1] = _r(2, "416.71", "3537.15", "8.95", "0.0640")
    assert t.huella(a) != t.huella(b)


def test_el_renglon_se_localiza_por_la_base() -> None:
    tarifa = _quincenal()
    assert t.renglon_para(tarifa, Decimal("0.01")).renglon == 1
    assert t.renglon_para(tarifa, Decimal("416.70")).renglon == 1
    assert t.renglon_para(tarifa, Decimal("416.71")).renglon == 2
    # El último renglón no tiene techo.
    assert t.renglon_para(tarifa, Decimal("999999.99")).renglon == 5


def test_una_base_por_debajo_del_primer_limite_es_un_error_de_configuracion_no_un_cero() -> None:
    """Anexo I.1: 'Si no hay renglón → error de configuración, NO cero'."""
    with pytest.raises(t.TarifaInvalida):
        t.renglon_para(_quincenal(), Decimal("0.00"))


def test_el_isr_es_cuota_fija_mas_el_excedente_por_la_tasa_redondeado_a_dos() -> None:
    # Renglón 3: cuota 207.75 + (5000.00 - 3537.16) * 0.1088 = 207.75 + 159.1569... = 366.91
    assert t.isr_de(_quincenal(), Decimal("5000.00")) == Decimal("366.91")


def test_el_mapa_de_periodicidades_del_cfdi_respeta_el_catalogo_del_sat() -> None:
    """`10` es Decenal y `06` es Bimestral en `c_PeriodicidadPago`, no al revés. El Anexo 8 no
    publica tarifa catorcenal ni bimestral, y decirlo con `None` es lo que permite avisar."""
    assert t.PARA_CFDI["04"] is PeriodicidadTarifa.DIAS_15
    assert t.PARA_CFDI["10"] is PeriodicidadTarifa.DIAS_10
    assert t.PARA_CFDI["02"] is PeriodicidadTarifa.DIAS_7
    assert t.PARA_CFDI["01"] is PeriodicidadTarifa.DIARIA
    assert t.PARA_CFDI["05"] is PeriodicidadTarifa.MENSUAL
    assert t.PARA_CFDI["03"] is None
    assert t.PARA_CFDI["06"] is None


def _quincenal_real() -> list[t.Renglon]:
    """Los cinco primeros renglones de la tarifa de 15 días del Anexo 8 de 2026, con el
    quinto abierto para que `validar` la acepte."""
    return [
        _r(1, "0.01", "416.70", "0.00", "0.0192"),
        _r(2, "416.71", "3537.15", "7.95", "0.0640"),
        _r(3, "3537.16", "6216.15", "207.75", "0.1088"),
        _r(4, "6216.16", "7225.95", "499.20", "0.1600"),
        _r(5, "7225.96", None, "660.75", "0.3500"),
    ]


def test_el_isr_del_periodo_completo_es_el_calculo_directo() -> None:
    """15 días de 15: no hay prorrateo. Renglón 3:
    207.75 + (5000.00 − 3537.16) × 0.1088 = 207.75 + 159.156992 → 366.91"""
    assert t.isr_del_periodo(_quincenal_real(), Decimal("5000.00"), Decimal("15"), Decimal("15")) == Decimal("366.91")


def test_un_centavo_de_base_cruza_de_renglon_y_mueve_el_isr() -> None:
    """La frontera exacta entre el renglón 2 y el 3, que es donde un error de agregación se
    delata. 3537.15 → 7.95 + (3537.15 − 416.71) × 0.0640 = 7.95 + 199.70816 → 207.66.
    3537.16 → 207.75 + 0 = 207.75. Nueve centavos de diferencia por un centavo de base."""
    tarifa = _quincenal_real()
    assert t.isr_del_periodo(tarifa, Decimal("3537.15"), Decimal("15"), Decimal("15")) == Decimal("207.66")
    assert t.isr_del_periodo(tarifa, Decimal("3537.16"), Decimal("15"), Decimal("15")) == Decimal("207.75")


def test_un_periodo_parcial_se_eleva_se_aplica_y_se_baja() -> None:
    """9 días de una quincena, art. 175 del Reglamento (decisión 2 del diseño):
    base elevada 3000.00 × 15/9 = 5000.00 → ISR del periodo completo 366.91
    → prorrateado 366.91 × 9/15 = 220.146 → 220.15.

    Sin elevar, 3000.00 caería en el renglón 2 y daría 7.95 + (3000.00 − 416.71) × 0.0640
    = 173.28: el error que este procedimiento existe para evitar."""
    assert t.isr_del_periodo(_quincenal_real(), Decimal("3000.00"), Decimal("9"), Decimal("15")) == Decimal("220.15")


def test_el_subsidio_se_mensualiza_para_compararlo_con_el_tope_y_se_prorratea_de_vuelta() -> None:
    """UMA mensual 3566.22, factor 0.1502, tope 11492.66 (los valores de 2026).
    Gravado quincenal 5000.00 → mensualizado 5000 × 30/15 = 10000.00 ≤ tope.
    Subsidio mensual: 0.1502 × 3566.22 = 535.6462… → 535.65.
    Del periodo: 535.65 × 15/30 = 267.825 → 267.83."""
    assert t.subsidio_del_periodo(
        Decimal("5000.00"), Decimal("15"), Decimal("3566.22"), Decimal("0.1502"), Decimal("11492.66")
    ) == Decimal("267.83")


def test_por_encima_del_tope_no_hay_subsidio() -> None:
    """Gravado 6000.00 → mensualizado 12000.00 > 11492.66 → cero. Es cero de verdad, no
    ausencia: quien gana de más no tiene subsidio, y eso es un hecho, no un dato que falte."""
    assert t.subsidio_del_periodo(
        Decimal("6000.00"), Decimal("15"), Decimal("3566.22"), Decimal("0.1502"), Decimal("11492.66")
    ) == Decimal("0.00")


def test_el_tope_se_compara_por_igualdad_inclusiva() -> None:
    """Justo en el tope todavía hay subsidio: el decreto dice «no exceda». Gravado quincenal
    5746.33 → mensualizado 11492.66 = tope exacto. El subsidio no depende del gravado una vez
    que la comparación con el tope ya pasó — solo depende de la UMA, el factor y los días —,
    así que el valor exacto es el mismo 267.83 del caso de 5000.00: 0.1502 × 3566.22 = 535.6462…
    → 535.65 mensual → 535.65 × 15/30 = 267.825 → 267.83."""
    assert t.subsidio_del_periodo(
        Decimal("5746.33"), Decimal("15"), Decimal("3566.22"), Decimal("0.1502"), Decimal("11492.66")
    ) == Decimal("267.83")


def test_el_isr_a_retener_y_el_subsidio_a_entregar_nunca_son_negativos() -> None:
    """366.91 − 267.83 = 99.08 a retener, nada que entregar. Y al revés cuando el subsidio
    supera al impuesto: se entrega la diferencia y no se retiene nada."""
    assert t.isr_a_retener(Decimal("366.91"), Decimal("267.83")) == Decimal("99.08")
    assert t.subsidio_a_entregar(Decimal("366.91"), Decimal("267.83")) == Decimal("0.00")
    assert t.isr_a_retener(Decimal("100.00"), Decimal("267.83")) == Decimal("0.00")
    assert t.subsidio_a_entregar(Decimal("100.00"), Decimal("267.83")) == Decimal("167.83")


def test_cero_dias_pagados_no_divide_entre_cero() -> None:
    """Un recibo con 0 días pagados existe (una baja el día 1). Debe lanzar `TarifaInvalida`
    con un mensaje que diga qué pasa, no reventar con ZeroDivisionError."""
    with pytest.raises(t.TarifaInvalida, match="días"):
        t.isr_del_periodo(_quincenal_real(), Decimal("1000.00"), Decimal("0"), Decimal("15"))


def test_cero_dias_pagados_en_el_subsidio_tampoco_divide_entre_cero() -> None:
    """El mismo recibo sin días pagados también rompería `subsidio_del_periodo`, que mensualiza
    dividiendo entre `dias_pagados`. Sin este guard, la librería lanzaría
    `decimal.DivisionByZero` — una excepción interna, no un mensaje de dominio — en un módulo
    cuyo contrato es fallar con algo que una persona pueda leer."""
    with pytest.raises(t.TarifaInvalida, match="días"):
        t.subsidio_del_periodo(
            Decimal("1000.00"), Decimal("0"), Decimal("3566.22"), Decimal("0.1502"), Decimal("11492.66")
        )


def test_la_base_elevada_se_redondea_antes_de_aplicar_la_tarifa() -> None:
    """7 días de una quincena con un gravado que no eleva limpio, para que el redondeo
    intermedio de la base elevada sí importe (a diferencia de 3000.00 × 15/9, que da exacto).

    Elevada: 1500.00 × 15/7 = 3214.2857142857… → redondeada a 3214.29 (renglón 2).
    Completo: 7.95 + (3214.29 − 416.71) × 0.0640 = 7.95 + 179.04512 → 7.95 + 179.05 = 187.00.
    Prorrateado: 187.00 × 7/15 = 87.2666… → 87.27.

    Sin redondear la base elevada, el marginal sale 7.95 + 179.0448457… → 7.95 + 179.04 = 186.99,
    y el prorrateo da 186.99 × 7/15 = 87.262 → 87.26: un centavo menos, exactamente la magnitud
    que B-09 reporta como diferencia."""
    assert t.isr_del_periodo(_quincenal_real(), Decimal("1500.00"), Decimal("7"), Decimal("15")) == Decimal("87.27")
