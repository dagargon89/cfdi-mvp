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
    """`sensible=True` marca una columna con datos personales (CURP, NSS, cuenta bancaria,
    etc.). Un informe solo declara la marca; el motor (`app.informes.excel`) es quien decide
    si la enmascara, según `ContextoInforme.parametros["enmascarar_datos_personales"]` —
    así ningún informe puede "olvidar" enmascarar una columna sensible."""

    titulo: str
    tipo: TipoColumna = "texto"
    sensible: bool = False


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
    notas: list[str] = field(default_factory=list)
    """Advertencias **permanentes** sobre cómo hay que leer las cifras del informe, que
    `app.informes.excel` rotula en la hoja `Parámetros` del libro.

    No es un `aviso` con otro nombre y la diferencia importa: `aviso` explica **esta** corrida
    (no hay filas, falta configurar algo) y desaparece cuando el informe sale bien; una nota
    vale siempre y sobre todo cuando el informe sale bien, porque califica los números que sí
    se produjeron. Tampoco es una `Bandera`: una bandera es un hallazgo accionable y la hoja
    `Banderas` se filtra buscando qué arreglar, así que una entrada que aparece en todas las
    corridas y que nadie puede quitar solo enseña a ignorar esa hoja.

    Existe para B-08 (`b08_pasivo_laboral._NOTAS`): su cifra puede acabar reconocida en los
    estados financieros y **tiene** que llegar rotulada como estimación con base en CFDI y no
    como cálculo actuarial, en el libro y no solo en el docstring del módulo. Quien recibe el
    Excel por correo no lee el código."""


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

    TIPOS_COMPROBANTE: tuple[str, ...]
    """Tipos de `comprobantes.tipo_comprobante` que el informe necesita normalizados.

    Lo usa el pre-vuelo del ETL (`app.worker.tasks._generar_informe_async`) para acotar
    `ids_pendientes` a lo que el informe de verdad va a leer. Todo el grupo B declara
    `("N",)`. Es obligatorio: un informe que no lo declare hace que su pre-vuelo reprocese
    el histórico completo de la empresa, lo que con volúmenes reales convierte la primera
    generación posterior a un cambio de `ETL_VERSION` en una tarea de horas.
    """

    Parametros: type[Any]

    async def consultar(self, db: Any, empresa_id: int, parametros: Any) -> ResultadoInforme: ...
