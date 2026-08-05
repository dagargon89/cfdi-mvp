"""Tipos compartidos por todos los informes (spec §7.1, §10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

SEPARADOR_ETIQUETA = "¦"
"""Barra vertical partida (U+00A6) para las etiquetas de columnas dinámicas (R-T8).

**No se usa `/`**: los `@Concepto` del catálogo del SAT contienen diagonales, lo que hace
ambiguo cualquier `split('/')` del lado del consumidor.
"""

TipoColumna = Literal["texto", "monto", "entero", "decimal", "fecha", "fecha_hora"]
Severidad = Literal["alta", "media", "baja"]


@dataclass(slots=True)
class Columna:
    titulo: str
    tipo: TipoColumna = "texto"


@dataclass(slots=True)
class Bandera:
    """Un hallazgo. Va en su propia hoja en vez de colorear celdas: así es filtrable y no
    se pierde al copiar (spec §10)."""

    clave: str
    severidad: Severidad
    ambito: str
    mensaje: str


@dataclass(slots=True)
class EntradaDiccionario:
    """Fila de la hoja `Diccionario`: permite al consumidor resolver una columna dinámica
    sin parsear su nombre (spec §10)."""

    etiqueta: str
    naturaleza: str
    tipo: str
    descripcion_sat: str | None
    clave_patron: str | None
    concepto_canonico: str | None
    descripciones_alternas: list[str] = field(default_factory=list)
    num_comprobantes: int = 0
    importe_total: Decimal = Decimal("0")


@dataclass(slots=True)
class ResultadoInforme:
    columnas: list[Columna]
    filas: list[list[Any]] = field(default_factory=list)
    banderas: list[Bandera] = field(default_factory=list)
    diccionario: list[EntradaDiccionario] = field(default_factory=list)
    aviso: str | None = None


@dataclass(slots=True)
class ContextoInforme:
    """Lo que va a la hoja `Parámetros` para que la corrida sea reproducible."""

    clave: str
    nombre: str
    usuario: str
    generado_en: datetime
    parametros: dict[str, Any]
    etl_version: int


class DefinicionInforme(Protocol):
    """Contrato que cumple cada módulo de informe."""

    CLAVE: str
    NOMBRE: str
    GRUPO: str
    DESCRIPCION: str

    Parametros: type[Any]

    async def consultar(self, db: Any, empresa_id: int, parametros: Any) -> ResultadoInforme: ...
