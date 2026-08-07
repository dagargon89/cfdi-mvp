"""Enums espejo del DDL (Hub_CFDI_docs/03-datos/03_modelo_de_datos.md §2.2)."""

from enum import Enum
from typing import TypeVar

from sqlalchemy import Enum as SAEnum

_E = TypeVar("_E", bound=Enum)


def enum_column(enum_cls: type[_E]) -> SAEnum:
    """`Enum` de SQLAlchemy que persiste el *valor* del enum ('admin'), no el nombre
    ('ADMIN') — sin esto, MySQL guarda los nombres en mayúsculas y rompe el contrato
    con `apps/web/src/lib/api.ts` (que espera 'admin'/'operador'/'vigente'/etc.)."""
    return SAEnum(enum_cls, values_callable=lambda cls: [e.value for e in cls])


class RolGlobal(str, Enum):
    ADMIN = "admin"
    OPERADOR = "operador"
    CONSULTA = "consulta"


class RolEmpresa(str, Enum):
    OPERADOR = "operador"
    CONSULTA = "consulta"


class TipoJob(str, Enum):
    EMITIDO = "emitido"
    RECIBIDO = "recibido"


class SolicitudTipo(str, Enum):
    CFDI = "CFDI"
    METADATA = "METADATA"


class OrigenJob(str, Enum):
    MANUAL = "manual"
    SYNC = "sync"


class EstadoJob(str, Enum):
    NUEVO = "NUEVO"
    SOLICITADO = "SOLICITADO"
    EN_PROCESO = "EN_PROCESO"
    TERMINADA = "TERMINADA"
    DESCARGADO = "DESCARGADO"
    ERROR = "ERROR"


class EstatusCfdi(str, Enum):
    VIGENTE = "vigente"
    CANCELADO = "cancelado"
    NO_VERIFICADO = "no_verificado"


class SituacionEfos(str, Enum):
    PRESUNTO = "presunto"
    DEFINITIVO = "definitivo"
    DESVIRTUADO = "desvirtuado"
    SENTENCIA_FAVORABLE = "sentencia_favorable"


class TipoEvento(str, Enum):
    CANCELACION_TARDIA = "cancelacion_tardia"
    EFOS = "efos"
    EFIRMA_POR_VENCER = "efirma_por_vencer"
    ERROR_DESCARGA = "error_descarga"
    RESUMEN_SYNC = "resumen_sync"


class ResultadoNotificacion(str, Enum):
    ENVIADO = "enviado"
    FALLIDO = "fallido"


class OrigenValor(str, Enum):
    """Procedencia de un valor de `param_fiscal`: quién lo puso ahí."""

    SEMILLA = "SEMILLA"
    MANUAL = "MANUAL"
    SINCRONIZADO = "SINCRONIZADO"


class BaseExencion(str, Enum):
    """Sobre qué se calcula el tramo exento de una percepción (§3.1 del documento fuente)."""

    UMA_DIAS = "UMA_DIAS"
    SM_DIAS = "SM_DIAS"
    PORCENTAJE = "PORCENTAJE"
    NINGUNA = "NINGUNA"


class CategoriaProvision(str, Enum):
    """A qué provisión contable corresponde un concepto de nómina de la organización.

    `NO_APLICA` no es un relleno: es lo que hace que la clasificación pueda estar
    **completa**. B-08 necesita saber cuánto aguinaldo se pagó ya; con un solo concepto sin
    clasificar, "aguinaldo pagado = 0" es indistinguible de "sí se pagó y no sé en cuál
    concepto viene", y el informe no puede generarse. Cuando todos los conceptos tienen
    categoría —incluidos los que explícitamente no son ninguna de las tres— ese cero pasa a
    ser un hecho conocido. Sin esta opción, marcar "este concepto no aplica" sería
    indistinguible de no haberlo revisado.
    """

    AGUINALDO = "AGUINALDO"
    VACACIONES = "VACACIONES"
    PRIMA_VACACIONAL = "PRIMA_VACACIONAL"
    NO_APLICA = "NO_APLICA"


class ZonaSalarial(str, Enum):
    """Régimen de salario mínimo aplicable (art. 94 LFT). Sin este dato no se puede saber
    si un salario está por debajo del mínimo — ver `app/models/configuracion_fiscal.py`."""

    GENERAL = "GENERAL"
    ZLFN = "ZLFN"
