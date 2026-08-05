"""Modelos SQLAlchemy 2 — espejo literal del DDL en Hub_CFDI_docs/03-datos/03_modelo_de_datos.md §2.2.

Importar este paquete registra todas las tablas en `Base.metadata` (necesario para
que Alembic autogenere/compare correctamente).
"""

from app.models.bitacora import Bitacora
from app.models.cfdi_detalle import CfdiConcepto, CfdiConceptoImpuesto, CfdiRelacionado, ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.configuracion import Configuracion
from app.models.configuracion_smtp import ConfiguracionSmtp
from app.models.efirma import Efirma
from app.models.empresa import Empresa
from app.models.evento import Evento
from app.models.job import Job
from app.models.lista_69b import Lista69b
from app.models.nomina import (
    Nomina,
    NominaDeduccion,
    NominaIncapacidad,
    NominaOtroPago,
    NominaPercepcion,
    NominaReceptor,
    NominaTotales,
)
from app.models.notificacion_destino import NotificacionDestino
from app.models.notificacion_log import NotificacionLog
from app.models.pago import Pago, PagoDocto, PagoDoctoImpuesto, PagoTotales
from app.models.usuario import Usuario
from app.models.usuario_empresa import UsuarioEmpresa

__all__ = [
    "Usuario",
    "Empresa",
    "UsuarioEmpresa",
    "Efirma",
    "Job",
    "Comprobante",
    "Lista69b",
    "Evento",
    "NotificacionDestino",
    "NotificacionLog",
    "Bitacora",
    "Configuracion",
    "ConfiguracionSmtp",
    "ComprobanteDetalle",
    "CfdiConcepto",
    "CfdiConceptoImpuesto",
    "CfdiRelacionado",
    "Pago",
    "PagoDocto",
    "PagoDoctoImpuesto",
    "PagoTotales",
    "Nomina",
    "NominaReceptor",
    "NominaPercepcion",
    "NominaDeduccion",
    "NominaOtroPago",
    "NominaIncapacidad",
    "NominaTotales",
]
