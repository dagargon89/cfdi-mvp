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
    **completa**. B-08 necesita saber cuánto aguinaldo se pagó ya; con una sola **percepción**
    sin clasificar, "aguinaldo pagado = 0" es indistinguible de "sí se pagó y no sé en cuál
    concepto viene", y el informe no puede generarse. Cuando todas las percepciones tienen
    categoría —incluidas las que explícitamente no son ninguna de las tres— ese cero pasa a
    ser un hecho conocido. Sin esta opción, marcar "esta percepción no aplica" sería
    indistinguible de no haberla revisado.

    **"Todas" quiere decir todas las percepciones, no todos los conceptos**, y la precisión
    importa porque la primera versión de este docstring decía lo segundo. Una deducción no
    puede ser aguinaldo —el aguinaldo no se le descuenta a nadie— y `c_TipoOtroPago` son
    subsidios, viáticos y reintegros: pedir `NO_APLICA` en las siete deducciones de una empresa
    es trabajo sin sentido para bajar un contador que nunca debió contarlas. El criterio vive
    en `configuracion_fiscal.percepciones_sin_clasificar`, que es donde está el argumento
    completo; léelo antes de volver a ensancharlo aquí.
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


class PeriodicidadTarifa(str, Enum):
    """Periodicidades **como las publica el Anexo 8**, no como las nombra el CFDI.

    El catálogo `c_PeriodicidadPago` del SAT tiene periodicidades para las que el Anexo no
    publica tarifa (`03` catorcenal, `06` bimestral), así que admitirlas aquí sugeriría que
    existen. La traducción de una cosa a la otra vive en `app.services.tarifa_isr.PARA_CFDI`.
    """

    DIARIA = "DIARIA"
    DIAS_7 = "DIAS_7"
    DIAS_10 = "DIAS_10"
    DIAS_15 = "DIAS_15"
    MENSUAL = "MENSUAL"
    EJERCICIO = "EJERCICIO"


class OrigenTarifa(str, Enum):
    """De dónde salió una tarifa. `IMPORTADA` no es `SEMILLA`: no viene del repositorio, viene
    del documento oficial que alguien subió, y su huella queda en `documento_sha256`."""

    IMPORTADA = "IMPORTADA"
    MANUAL = "MANUAL"
