"""Descripciones de los catálogos del SAT (§3 del documento fuente).

`satcfdi` ya trae los catálogos: no se cargan tablas. Lo que sí hace falta es resolver
`tipo → descripción` para la hoja Diccionario, y que un tipo desconocido devuelva `None`
en vez de romper el informe.
"""

from __future__ import annotations

from app.informes import catalogos


def test_descripcion_de_percepcion_deduccion_y_otro_pago() -> None:
    assert catalogos.descripcion_percepcion("001") == "Sueldos, Salarios Rayas y Jornales"
    assert catalogos.descripcion_deduccion("002") is not None
    assert "ISR" in (catalogos.descripcion_deduccion("002") or "")
    assert catalogos.descripcion_otro_pago("002") is not None


def test_tipo_desconocido_no_rompe() -> None:
    """El SAT agrega claves; un catálogo desactualizado no debe abortar un informe."""
    assert catalogos.descripcion_percepcion("999") is None
    assert catalogos.descripcion_deduccion("ZZZ") is None


def test_despacho_por_naturaleza() -> None:
    assert catalogos.descripcion("P", "001") == "Sueldos, Salarios Rayas y Jornales"
    assert catalogos.descripcion("D", "002") == catalogos.descripcion_deduccion("002")
    assert catalogos.descripcion("O", "002") == catalogos.descripcion_otro_pago("002")
    assert catalogos.descripcion("X", "001") is None
