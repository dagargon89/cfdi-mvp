"""Tipos de dominio y enumeraciones del núcleo (doc 05 §1.3 y §2).

Espejo del modelo de datos (doc 03). Estos tipos son la frontera del contrato:
la carcasa (CLI/Flet) solo habla con el núcleo mediante estas dataclasses y los
métodos de ``Engine``/``Store``/``Fiel``. No importan ``satcfdi`` ni conocen SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

# --------------------------------------------------------------------------- #
# Enumeraciones de dominio (doc 05 §1.3)
# --------------------------------------------------------------------------- #


class Estado(str, Enum):
    """Estados del ciclo asíncrono de un job de descarga (SRS §4)."""

    NUEVO = "NUEVO"
    SOLICITADO = "SOLICITADO"
    EN_PROCESO = "EN_PROCESO"
    TERMINADA = "TERMINADA"
    DESCARGADO = "DESCARGADO"
    ERROR = "ERROR"


class Tipo(str, Enum):
    """Dirección del comprobante respecto al contribuyente (R5)."""

    EMITIDO = "emitido"
    RECIBIDO = "recibido"


class Solicitud(str, Enum):
    """Modalidad de descarga masiva (R3)."""

    CFDI = "CFDI"
    METADATA = "METADATA"


class Estatus(str, Enum):
    """Estatus de vigencia de un CFDI (RF-VAL-01, H-07)."""

    VIGENTE = "vigente"
    CANCELADO = "cancelado"
    NO_VERIFICADO = "no_verificado"


# --------------------------------------------------------------------------- #
# Entidades de dominio (doc 05 §2 · espejo de doc 03)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Client:
    """Contribuyente gestionado en la instalación (tabla ``clients``).

    La contraseña de la FIEL NUNCA vive en esta estructura (RF-FIEL-03).
    """

    client_id: int | None
    nombre: str
    rfc: str
    cer_path: str
    key_path: str
    dest_dir: str
    activo: bool = True


@dataclass(slots=True)
class Job:
    """Una solicitud de descarga masiva por ventana de fechas (tabla ``jobs``)."""

    job_id: int | None
    client_id: int
    tipo: Tipo
    solicitud: Solicitud
    fecha_inicial: date
    fecha_final: date
    id_solicitud: str | None = None
    estado: Estado = Estado.NUEVO
    intentos: int = 0
    paquetes: int = 0
    mensaje: str | None = None


@dataclass(slots=True)
class Comprobante:
    """CFDI individual indexado (tabla ``comprobantes``, Fase 2)."""

    comprobante_id: int | None
    client_id: int
    job_id: int | None
    uuid: str
    folio: str | None
    rfc_emisor: str
    rfc_receptor: str
    razon_social_emisor: str | None
    total: float | None
    fecha_emision: datetime | None
    tipo_comprobante: str | None
    estatus: Estatus = Estatus.NO_VERIFICADO
    estatus_verificado_at: datetime | None = None
    xml_path: str | None = None
    comprobante_path: str | None = None


@dataclass(slots=True)
class ResultadoValidacion:
    """Resultado de validar un CFDI (XML) suelto de forma manual (RF-VAL-01).

    Lo produce ``Engine.validar_xmls`` para archivos que el operador ya tiene en
    disco, fuera del ciclo de descarga. No requiere FIEL (la consulta de estatus
    del SAT es un endpoint público). ``error`` explica por qué un archivo no pudo
    parsearse o consultarse; ``guardado`` indica si además se indexó en la base.
    """

    origen: str
    uuid: str | None = None
    rfc_emisor: str | None = None
    rfc_receptor: str | None = None
    total: float | None = None
    fecha_emision: datetime | None = None
    tipo_comprobante: str | None = None
    estatus: Estatus = Estatus.NO_VERIFICADO
    error: str | None = None
    guardado: bool = False


@dataclass(slots=True)
class Progreso:
    """Evento de avance que el núcleo emite hacia la carcasa (callback)."""

    job_id: int
    estado: Estado
    intento: int
    mensaje: str | None = None
