"""Validadores puros de datos del receptor (ficha B-10). Sin BD: reglas de estructura."""

from __future__ import annotations

import pytest

from app.informes import validadores as v


@pytest.mark.parametrize("rfc", ["VECJ880326XXX", "ÑAAA000101AA1", "AAA&000101AA1"])
def test_rfc_persona_fisica_valido(rfc: str) -> None:
    assert v.rfc_persona_fisica_valido(rfc) is True


@pytest.mark.parametrize("rfc", [None, "", "EKU9003173C9", "VECJ880326", "vecj880326xxx", "VECJ8803261XXX"])
def test_rfc_persona_fisica_invalido(rfc: str | None) -> None:
    """`EKU9003173C9` es de persona moral (3 letras iniciales): no cumple el patrón de
    física, que exige 4."""
    assert v.rfc_persona_fisica_valido(rfc) is False


def test_curp_valida() -> None:
    assert v.curp_valida("VECJ880326HDFLNS09") is True
    assert v.curp_valida(None) is False
    assert v.curp_valida("VECJ880326XDFLNS09") is False  # ni H ni M


def test_curp_entidad() -> None:
    assert v.curp_entidad_valida("VECJ880326HDFLNS09") is True  # DF
    assert v.curp_entidad_valida("VECJ880326HCHLNS09") is True  # CH
    assert v.curp_entidad_valida("VECJ880326HZZLNS09") is False
    assert v.curp_entidad_valida(None) is False


def test_nss_digito_verificador() -> None:
    """Luhn sobre las 10 primeras posiciones; la 11ª es el verificador.

    `12345678903` se verificó a mano y con script antes de fijarlo aquí (ver el docstring
    del módulo `validadores`): la suma de Luhn de `1234567890` da 47, y 47 + 3 = 50 es
    múltiplo de 10, así que el dígito verificador correcto para ese cuerpo SÍ es 3. No es un
    valor ajustado para que la prueba pase, es el que el algoritmo real produce.
    """
    assert v.nss_digito_verificador_valido("12345678903") is True
    assert v.nss_digito_verificador_valido("12345678901") is False
    assert v.nss_digito_verificador_valido(None) is False
    assert v.nss_digito_verificador_valido("123") is False


def test_cuenta_bancaria_longitud() -> None:
    for largo in (10, 11, 16, 18):
        assert v.cuenta_bancaria_longitud_valida("1" * largo) is True
    assert v.cuenta_bancaria_longitud_valida("1" * 12) is False
    assert v.cuenta_bancaria_longitud_valida(None) is False


def test_antiguedad_iso_a_dias() -> None:
    """`@Antigüedad` viene como duración ISO 8601 (`P663W`, `P3Y2M`)."""
    assert v.antiguedad_iso_a_dias("P1W") == 7
    assert v.antiguedad_iso_a_dias("P663W") == 663 * 7
    assert v.antiguedad_iso_a_dias("P1Y") == 365
    assert v.antiguedad_iso_a_dias("P1Y2M") == 365 + 60
    assert v.antiguedad_iso_a_dias("P10D") == 10
    assert v.antiguedad_iso_a_dias(None) is None
    assert v.antiguedad_iso_a_dias("663 semanas") is None
