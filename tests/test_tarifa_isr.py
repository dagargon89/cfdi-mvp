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
