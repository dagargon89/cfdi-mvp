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


def test_tipos_de_percepcion_trae_el_catalogo_completo() -> None:
    """B-01.R1 genera una columna por tipo del catálogo, no por tipo observado, así que
    necesita la lista completa."""
    tipos = catalogos.tipos_de("P")
    claves = [clave for clave, _ in tipos]
    # El catálogo del SAT llega al menos hasta el 046; el conteo exacto puede cambiar con
    # la versión de satcfdi, así que se asevera el piso y las claves conocidas.
    assert len(claves) >= 40
    assert "001" in claves and "046" in claves
    # Claves como texto, con sus ceros a la izquierda intactos.
    assert all(isinstance(c, str) for c in claves)
    assert dict(tipos)["001"] == "Sueldos, Salarios Rayas y Jornales"


def test_tipos_de_deduccion_y_otro_pago() -> None:
    deducciones = dict(catalogos.tipos_de("D"))
    assert len(deducciones) >= 100
    assert "002" in deducciones and "ISR" in deducciones["002"]
    otros = dict(catalogos.tipos_de("O"))
    assert "002" in otros


def test_tipos_de_esta_ordenado_por_clave_como_texto() -> None:
    """El orden de las columnas del informe depende de esto y debe ser estable."""
    claves = [c for c, _ in catalogos.tipos_de("P")]
    assert claves == sorted(claves)


def test_tipos_de_naturaleza_desconocida_devuelve_vacio() -> None:
    assert catalogos.tipos_de("X") == []
