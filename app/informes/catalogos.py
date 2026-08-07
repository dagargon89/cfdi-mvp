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

**Descubrimiento (tarea 3, fase 2):** para B-01 hace falta enumerar la tabla completa, no
solo resolver una clave. El brief proponía leer `catalogs.db` con `sqlite3` asumiendo
columnas `id` y `texto`. Esa suposición es incorrecta: `PRAGMA table_info` sobre
`C75b_c_TipoPercepcion` muestra dos columnas `BLOB` llamadas `key` y `value` — el propio
`satcfdi.catalogs` guarda cada catálogo como un pickle de `(clave, descripción)` por fila
(`select`/`select_all` en ese módulo hacen `pickle.loads` sobre ambas columnas). Leerlas con
`sqlite3` puro sin despicklear daría bytes ilegibles, no texto.

En vez de reimplementar ese unpickling a mano, se reutiliza `satcfdi.catalogs.select_all`,
la misma función pública que ya usa la librería para volcar un catálogo completo — así este
módulo sigue el mismo patrón que ya tenía para `catalog_code`: apoyarse en la API de
`satcfdi`, no en el archivo `.db` directamente. Confirmado contando filas: 44 tipos de
percepción, 107 de deducción, 10 de otro pago, todas con clave de 3 caracteres.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Callable, cast

logger = logging.getLogger(__name__)

# Naturaleza (P/D/O) → tabla del catálogo embebido de `satcfdi` (ver docstring del módulo).
#
# `"R"` (c_TipoRegimen, 13 claves) no es una naturaleza de concepto como las otras tres: no
# describe percepciones ni deducciones sino el régimen de contratación del **trabajador**. Se
# cuelga del mismo mapa a propósito, en vez de duplicar la caché y la garantía de "un fallo de
# lectura no se memoiza" en una función aparte; el parámetro de `tipos_de` es en realidad "de
# qué catálogo", y `tipos_de_regimen()` existe para que quien lo consulte no tenga que conocer
# esta convención.
_TABLAS = {
    "P": "C75b_c_TipoPercepcion",
    "D": "C75b_c_TipoDeduccion",
    "O": "C75b_c_TipoOtroPago",
    "R": "C75b_c_TipoRegimen",
}


@lru_cache(maxsize=1)
def _catalog_code() -> Callable[[str, str], Any]:
    """Carga perezosa: importar `satcfdi.catalogs` es costoso y no todo informe lo necesita."""
    from satcfdi.catalogs import catalog_code

    return cast("Callable[[str, str], Any]", catalog_code)


@lru_cache(maxsize=1)
def _select_all() -> Callable[[str], dict[Any, Any]]:
    """Carga perezosa de `satcfdi.catalogs.select_all`, la función que vuelca un catálogo
    completo ya despicklado (ver docstring del módulo: `key`/`value` son BLOBs pickled)."""
    from satcfdi.catalogs import select_all

    return cast("Callable[[str], dict[Any, Any]]", select_all)


class CatalogoIlegible(RuntimeError):
    """No se pudo **leer** la tabla del catálogo embebido de `satcfdi`.

    Existe para separar dos cosas que antes eran la misma tupla vacía: "el catálogo dice que
    no hay tipos" y "no pude abrir el catálogo". Mientras enumerar el catálogo solo servía
    para poner descripciones en un informe, confundirlas era inocuo; desde que decide si una
    escritura se acepta (`exige_tipo_percepcion_conocido`), la diferencia es la que separa
    "rechaza este renglón" de "no puedo opinar, no escribas".
    """


@lru_cache(maxsize=8)
def _tipos_de_cache(naturaleza: str) -> tuple[tuple[str, str], ...]:
    """Cuerpo cacheable de `tipos_de` (ver esa función para la firma pública).

    `lru_cache` exige un valor inmutable, así que esta capa interna devuelve una tupla; la
    función pública la convierte a `list` porque así la declara la interfaz de la tarea y
    porque las pruebas comparan el resultado con `==` contra listas y listas vacías
    (`tipos_de("X") == []`, que con una tupla sería `() == []` → `False`).

    **Un fallo de lectura se propaga como `CatalogoIlegible` y NO se memoiza.** `lru_cache`
    solo guarda los retornos, nunca las excepciones, así que la siguiente llamada vuelve a
    intentar. Antes esta función atrapaba el error y devolvía `()`, y ese `()` sí quedaba
    cacheado para siempre: un fallo de un instante —un sqlite a medio montar, un `satcfdi`
    reinstalándose— dejaba el proceso entero opinando que el catálogo está vacío hasta que
    alguien reiniciara el API. Inocuo mientras solo faltaba una descripción; una denegación
    de servicio permanente desde que `PUT /percepciones/{tipo}` depende de esta lista. Un
    fallo transitorio tiene que producir un rechazo transitorio.
    """
    tabla = _TABLAS.get(naturaleza)
    if tabla is None:
        # Naturaleza desconocida no es un fallo, es una respuesta: no existe esa tabla y no
        # va a existir. Cachearla está bien.
        return ()
    try:
        mapa = _select_all()(tabla)
    except Exception as exc:
        raise CatalogoIlegible(f"no se pudo enumerar la tabla {tabla} del catálogo de satcfdi: {exc}") from exc
    return tuple(sorted(((str(clave), str(texto)) for clave, texto in mapa.items()), key=lambda par: par[0]))


def tipos_de(naturaleza: str) -> list[tuple[str, str]]:
    """Todas las claves de un catálogo con su descripción, ordenadas por clave **como
    texto**. B-01 genera una columna por cada una (B-01.R1), esté o no en los datos.

    `naturaleza` es `"P"` (percepción), `"D"` (deducción), `"O"` (otro pago) o `"R"`
    (`c_TipoRegimen`, ver el comentario de `_TABLAS`); cualquier otro valor devuelve `[]`.
    Internamente se apoya en `_tipos_de_cache`, cacheada con
    `lru_cache`: enumerar el catálogo completo cuesta más que resolver una sola clave
    (`descripcion`), y B-01 la llama una vez por naturaleza en cada corrida.

    **Falla abierto**: si el catálogo no se puede leer devuelve `[]` y lo registra, porque un
    catálogo ilegible no debe abortar un informe. Quien necesite distinguir ese caso —porque
    de él depende aceptar o no una escritura— usa `tipos_de_estricto`.
    """
    try:
        return list(_tipos_de_cache(naturaleza))
    except CatalogoIlegible as exc:
        logger.warning("catalogos: %s", exc)
        return []


def tipos_de_estricto(naturaleza: str) -> list[tuple[str, str]]:
    """Igual que `tipos_de`, pero **propaga** `CatalogoIlegible` en vez de devolver `[]`.

    Para quien valida una escritura contra el catálogo: ahí "no pude leerlo" no puede
    confundirse con "no está en la lista", porque el primero debe negarse a escribir y el
    segundo debe rechazar el dato. Y como el fallo no se memoiza, el rechazo dura lo que dure
    la avería.
    """
    return list(_tipos_de_cache(naturaleza))


def tipos_de_regimen() -> frozenset[str]:
    """Las claves de `c_TipoRegimen` (13 en la versión pinada de `satcfdi`), para validar el
    `tipo_regimen` que trae el complemento de nómina.

    **Falla abierto igual que `tipos_de`**: si el catálogo no se puede leer devuelve un
    conjunto vacío, y quien lo consulte tiene que interpretarlo como "no puedo opinar" y
    omitir la comprobación —nunca como "ninguna clave es válida", que marcaría a toda la
    plantilla—. Es la regla del módulo: un catálogo ilegible no aborta ni contamina un
    informe. Para una **escritura**, donde esa distinción decide si se guarda un dato, se usa
    `tipos_de_estricto` (ver `configuracion_fiscal.exige_tipo_percepcion_conocido`).
    """
    return frozenset(clave for clave, _descripcion in tipos_de("R"))


def _buscar(naturaleza: str, tipo: str) -> str | None:
    tabla = _TABLAS.get(naturaleza)
    if tabla is None:
        return None
    try:
        codigo = _catalog_code()(tabla, tipo)
    except Exception as exc:  # noqa: BLE001 — el informe no aborta por una descripción
        # El catálogo del SAT es un archivo externo a la librería; ante cualquier fallo de
        # lectura, el informe no debe abortar por una clave que no se pudo resolver. Pero se
        # registra: sin este log, un sqlite corrupto o un `satcfdi` a medio instalar produce
        # exactamente el mismo `None` que una clave nueva del SAT todavía no catalogada, y la
        # primera causa se arregla mientras la segunda solo se anota.
        logger.warning("catalogos: no se pudo resolver %s/%s en la tabla %s: %s", naturaleza, tipo, tabla, exc)
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
