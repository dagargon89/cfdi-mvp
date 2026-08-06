"""Registro de informes disponibles (spec §7.1).

Agregar un informe = importar su módulo y añadirlo a `_MODULOS`. El endpoint del catálogo
y el de generación no cambian.
"""

from __future__ import annotations

from typing import Any

from app.informes import (
    b01_catalogo_sat,
    b02_conceptos_patron,
    b04_matriz_empleado_periodo,
    b05_acumulado_anual,
    b07_prestamos,
    b10_validacion_receptor,
)
from app.informes.base import DefinicionInforme

_MODULOS: tuple[Any, ...] = (
    b01_catalogo_sat,
    b02_conceptos_patron,
    b04_matriz_empleado_periodo,
    b05_acumulado_anual,
    b07_prestamos,
    b10_validacion_receptor,
)

REGISTRO: dict[str, DefinicionInforme] = {modulo.CLAVE: modulo for modulo in _MODULOS}


class InformeDesconocidoError(KeyError):
    """Clave que no está en el registro."""


def obtener(clave: str) -> DefinicionInforme:
    try:
        return REGISTRO[clave]
    except KeyError as exc:
        raise InformeDesconocidoError(clave) from exc


def catalogo() -> list[dict[str, Any]]:
    """Catálogo para el frontend: incluye el JSON Schema de los parámetros, con lo que la
    pantalla genera su formulario sola (spec §7.2)."""
    return [
        {
            "clave": definicion.CLAVE,
            "nombre": definicion.NOMBRE,
            "grupo": definicion.GRUPO,
            "descripcion": definicion.DESCRIPCION,
            "parametros": definicion.Parametros.model_json_schema(),
        }
        for definicion in sorted(REGISTRO.values(), key=lambda d: d.CLAVE)
    ]
