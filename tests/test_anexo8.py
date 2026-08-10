"""El extractor de tarifas del Anexo 8, contra el documento oficial real.

Las pruebas se escriben contra el **PDF completo**, no contra un fragmento recortado con solo las
tablas buenas: "semilla limpia donde el mundo real tiene datos sucios" fue la clase de defecto que
más se repitió en la fase 3 de informes. Este documento trae, de verdad, las tres trampas que el
extractor tiene que sortear: encabezados duplicados en el índice, un pie de página a media tabla y
tarifas que no son de nómina con exactamente la misma forma.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.models.enums import PeriodicidadTarifa
from app.services import anexo8
from app.services import tarifa_isr as t

ANEXO_2026 = Path(__file__).parent / "fixtures" / "anexo8-2026.pdf"


@pytest.fixture(scope="module")
def extraidas() -> list[anexo8.TarifaExtraida]:
    return anexo8.extraer(ANEXO_2026.read_bytes())


def test_del_anexo_real_salen_las_siete_tarifas_de_sueldos(extraidas: list[anexo8.TarifaExtraida]) -> None:
    """Cinco periodicidades del ejercicio 2026, más la anual de 2026 y la de 2025."""
    claves = {(x.ejercicio, x.periodicidad) for x in extraidas}
    assert claves == {
        (2026, PeriodicidadTarifa.DIARIA),
        (2026, PeriodicidadTarifa.DIAS_7),
        (2026, PeriodicidadTarifa.DIAS_10),
        (2026, PeriodicidadTarifa.DIAS_15),
        (2026, PeriodicidadTarifa.MENSUAL),
        (2026, PeriodicidadTarifa.EJERCICIO),
        (2025, PeriodicidadTarifa.EJERCICIO),
    }


def test_el_ejercicio_sale_del_encabezado_de_cada_tabla_no_del_documento(
    extraidas: list[anexo8.TarifaExtraida],
) -> None:
    """El Anexo 8 de 2026 trae la tarifa anual del ejercicio **2025** en su rubro C.I. Tomar el año
    del archivo la guardaría como de 2026, y las seis pruebas no lo detectarían: las dos tablas son
    internamente coherentes. Es el error más peligroso de todo el importador."""
    anuales = {x.ejercicio for x in extraidas if x.periodicidad is PeriodicidadTarifa.EJERCICIO}
    assert anuales == {2025, 2026}


def test_la_tarifa_quincenal_coincide_renglon_por_renglon_con_el_documento(
    extraidas: list[anexo8.TarifaExtraida],
) -> None:
    q = next(x for x in extraidas if x.periodicidad is PeriodicidadTarifa.DIAS_15 and x.ejercicio == 2026)
    assert len(q.renglones) == 11
    assert q.renglones[0] == t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192"))
    assert q.renglones[1] == t.Renglon(
        2, Decimal("416.71"), Decimal("3537.15"), Decimal("7.95"), Decimal("0.0640")
    )
    # El renglón 6 va justo después del pie de página del DOF que el PDF intercala a media tabla.
    assert q.renglones[5] == t.Renglon(
        6, Decimal("8651.41"), Decimal("17448.75"), Decimal("916.20"), Decimal("0.2136")
    )
    assert q.renglones[-1] == t.Renglon(
        11, Decimal("210020.71"), None, Decimal("65866.05"), Decimal("0.3500")
    )


def test_el_pie_de_pagina_del_dof_no_corta_la_tabla(extraidas: list[anexo8.TarifaExtraida]) -> None:
    """'Domingo 28 de diciembre de 2025 DIARIO OFICIAL' aparece entre el renglón 5 y el 6 de la
    tarifa quincenal. Si el extractor se detuviera ahí, la tarifa saldría con 5 renglones, fallaría
    la prueba de continuidad y quien la sube vería un error falso sobre un PDF correcto."""
    q = next(x for x in extraidas if x.periodicidad is PeriodicidadTarifa.DIAS_15 and x.ejercicio == 2026)
    t.validar(list(q.renglones))


def test_ninguna_tarifa_extraida_es_de_las_que_no_son_de_nomina(
    extraidas: list[anexo8.TarifaExtraida],
) -> None:
    """El rubro A.I (enajenación de inmuebles) y las de los arts. 106 y 116 tienen la misma forma de
    cuatro columnas. El ancla exige el fundamento citado, así que ninguna entra."""
    for x in extraidas:
        assert "126" not in x.encabezado
        assert "106 de la Ley del ISR" not in x.encabezado
        assert "116" not in x.encabezado


def test_el_encabezado_del_indice_no_produce_una_tarifa_vacia(
    extraidas: list[anexo8.TarifaExtraida],
) -> None:
    """Cada encabezado aparece dos veces en el documento: en el 'Contenido' de la página 1 y sobre
    su tabla. La ocurrencia del índice no tiene renglones detrás, y si contara, habría 14 tarifas
    (siete de ellas vacías) en vez de 7."""
    assert len(extraidas) == 7
    assert all(len(x.renglones) >= 2 for x in extraidas)


def test_todas_las_tarifas_extraidas_pasan_la_validacion(extraidas: list[anexo8.TarifaExtraida]) -> None:
    for x in extraidas:
        t.validar(list(x.renglones))


def test_las_tasas_quedan_en_fraccion_no_en_porcentaje(extraidas: list[anexo8.TarifaExtraida]) -> None:
    """El Anexo publica 21.36 y la columna guarda 0.2136. La división entre 100 ocurre en un solo
    lugar de todo el sistema y esta prueba es la que lo vigila (B-09.R2)."""
    for x in extraidas:
        assert all(r.tasa_excedente < Decimal(1) for r in x.renglones)
        assert Decimal("0.30") <= x.renglones[-1].tasa_excedente <= Decimal("0.40")


def test_un_pdf_sin_texto_se_rechaza_diciendo_que_parece_escaneo() -> None:
    # PDF mínimo válido de una página, sin objetos de texto.
    vacio = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    with pytest.raises(anexo8.DocumentoInvalido, match="escaneo"):
        anexo8.extraer(vacio)


def test_un_pdf_que_no_es_el_anexo_8_no_importa_nada_y_dice_que_esperaba() -> None:
    """Se le pasa un PDF real del propio repositorio que no es el Anexo 8."""
    otro = Path(__file__).parent.parent / "docs" / "superpowers" / "specs" / "2026-08-10-tarifa-isr-design.md"
    with pytest.raises(anexo8.DocumentoInvalido, match="Anexo 8"):
        anexo8.extraer(otro.read_bytes())


def test_un_archivo_mas_grande_que_el_limite_se_rechaza_antes_de_abrirlo() -> None:
    with pytest.raises(anexo8.DocumentoInvalido, match="grande"):
        anexo8.extraer(b"x" * (anexo8.MAXIMO_BYTES + 1))
