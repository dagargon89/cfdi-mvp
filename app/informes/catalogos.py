"""Descripciones de los catálogos del SAT para las hojas de los informes (§3 del fuente).

No se cargan tablas de catálogo: `satcfdi` ya las trae. Este módulo solo resuelve
`tipo → descripción` y devuelve `None` cuando la clave no está en el catálogo de la versión
instalada — el SAT agrega claves, y un catálogo desactualizado no debe abortar un informe.

**Descubrimiento (tarea 12):** el brief asumía `satcfdi.catalogs.TipoPercepcion` y compañía
como enumeraciones consultables por clave. No existen: `dir(satcfdi.catalogs)` no expone
ningún nombre con "ercepcion", "educcion" ni "troPago". Lo que sí expone es
`catalog_code(tabla, clave) -> Code(code, description)`, que consulta un sqlite embebido
(`satcfdi/catalogs/catalogs.db`) — la misma función que usa el propio parser de `satcfdi`
para resolver estos catálogos al leer un XML de nómina (`satcfdi/transform/objectify.py`,
p. ej. `catalog_code('C75b_c_TipoPercepcion', node.attrib['TipoPercepcion'])`). Con una
clave ausente del catálogo, `catalog_code` no lanza: devuelve `Code(clave, None)` — ya
resuelve por sí solo el requisito de no abortar el informe.

Los nombres de tabla (`C75b_c_TipoPercepcion`, `C75b_c_TipoDeduccion`,
`C75b_c_TipoOtroPago`) se tomaron de ese mismo módulo de `satcfdi`, no están documentados
en la API pública.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, cast

# Naturaleza (P/D/O) → tabla del catálogo embebido de `satcfdi` (ver docstring del módulo).
_TABLAS = {
    "P": "C75b_c_TipoPercepcion",
    "D": "C75b_c_TipoDeduccion",
    "O": "C75b_c_TipoOtroPago",
}


@lru_cache(maxsize=1)
def _catalog_code() -> Callable[[str, str], Any]:
    """Carga perezosa: importar `satcfdi.catalogs` es costoso y no todo informe lo necesita."""
    from satcfdi.catalogs import catalog_code

    return cast("Callable[[str, str], Any]", catalog_code)


def _buscar(naturaleza: str, tipo: str) -> str | None:
    tabla = _TABLAS.get(naturaleza)
    if tabla is None:
        return None
    try:
        codigo = _catalog_code()(tabla, tipo)
    except Exception:
        # El catálogo del SAT es un archivo externo a la librería; ante cualquier fallo de
        # lectura, el informe no debe abortar por una clave que no se pudo resolver.
        return None
    descripcion = codigo.description
    return str(descripcion) if descripcion else None


def descripcion_percepcion(tipo: str) -> str | None:
    return _buscar("P", tipo)


def descripcion_deduccion(tipo: str) -> str | None:
    return _buscar("D", tipo)


def descripcion_otro_pago(tipo: str) -> str | None:
    return _buscar("O", tipo)


def descripcion(naturaleza: str, tipo: str) -> str | None:
    """Despacho por naturaleza (`P`, `D`, `O`). Cualquier otra devuelve `None`."""
    if naturaleza not in _TABLAS:
        return None
    return _buscar(naturaleza, tipo)
