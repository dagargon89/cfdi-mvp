"""Fachada de ``satcfdi`` — único punto de contacto con la librería (doc 05 §5).

Aísla toda la API de ``satcfdi`` en un solo módulo: mapea ``tipo → método`` de
solicitud (resuelve H-04), y expone verificación, descarga y validación de
estatus. El ``Engine`` traduce las excepciones que surjan aquí a la jerarquía
``SatError`` (doc 05 §4); la carcasa nunca ve ``satcfdi``.

.. note:: Contrato CONGELADO contra ``satcfdi`` 26.7.3 (Sprint 1, resuelve H-04).
   Firmas verificadas por ``inspect`` (ver ``tools/inspect_satcfdi.py``):

   =============  =========  ==========================================  ================================
   Operación      tipo       Método ``satcfdi.SAT``                       Respuesta
   =============  =========  ==========================================  ================================
   Solicitud      recibido   ``recover_comprobante_received_request``     dict con ``IdSolicitud``
   Solicitud      emitido    ``recover_comprobante_emitted_request``      dict con ``IdSolicitud``
   Verificación   —          ``recover_comprobante_status(id)``           ``EstadoSolicitud`` (int 1-6),
                                                                          ``IdsPaquetes``, ``NumeroCFDIs``
   Descarga       —          ``recover_comprobante_download(id_paquete)`` ``(dict, str)`` — paquete base64
   Validación     —          ``status(cfdi)``                            dict con ``Estado`` (Vigente/…)
   =============  =========  ==========================================  ================================

   ``recover_comprobante_request`` quedó **deprecado** en 26.x: no se usa.
   ``TipoDescargaMasivaTerceros``: CFDI='CFDI', METADATA='Metadata' (lookup por nombre).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .domain import Job, Tipo
from .errors import SatRechazoError

# --------------------------------------------------------------------------- #
# EstadoSolicitud (espejo congelado de satcfdi.pacs.sat.EstadoSolicitud).
# Se declaran aquí para que el Engine clasifique el ciclo sin importar satcfdi
# (satcfdi vive SOLO en este módulo, doc 02 §2).
# --------------------------------------------------------------------------- #
ESTADO_ACEPTADA = 1
ESTADO_EN_PROCESO = 2
ESTADO_TERMINADA = 3
ESTADO_ERROR = 4
ESTADO_RECHAZADA = 5
ESTADO_VENCIDA = 6

# Aún trabajando (seguir haciendo polling).
ESTADOS_EN_PROCESO = frozenset({ESTADO_ACEPTADA, ESTADO_EN_PROCESO})
# Paquetes listos para descarga.
ESTADOS_TERMINADA = frozenset({ESTADO_TERMINADA})
# Rechazo definitivo → el job pasa a ERROR.
ESTADOS_RECHAZO = frozenset({ESTADO_ERROR, ESTADO_RECHAZADA, ESTADO_VENCIDA})

# `CodigoEstadoSolicitud` real del SAT (catálogo de `satcfdi.pacs.sat`) — "5004" viene
# acompañado de `EstadoSolicitud=0` (fuera del enum 1-6 de arriba, que solo cubre la
# respuesta "normal") y significa "la solicitud es válida pero no hay CFDI que coincidan":
# NO es un error, es una terminación exitosa con cero paquetes (visto en producción con
# una solicitud de METADATA para un rango de fechas sin comprobantes).
COD_ESTATUS_SIN_RESULTADOS = "5004"


@dataclass(slots=True)
class ResultadoVerificacion:
    """Resultado de una verificación de estatus de solicitud ante el SAT.

    ``cod_estatus`` es el catálogo real del SAT (``CodigoEstadoSolicitud`` en `satcfdi`):
    "5000" éxito, "5002" agotado, "5003" tope máximo, "5004" *sin resultados* (visto en
    producción con `EstadoSolicitud=0` — no es un error, es una solicitud válida sin CFDI
    que coincidan), "5005" duplicada, "404" error genérico no controlado.
    """

    estado_solicitud: int
    ids_paquetes: list[str] = field(default_factory=list)
    num_cfdis: int = 0
    mensaje: str | None = None
    cod_estatus: str | None = None


@dataclass(slots=True)
class CamposCFDI:
    """Campos extraídos de un CFDI al parsear su XML (para indexar en `comprobantes`)."""

    uuid: str
    folio: str | None
    rfc_emisor: str
    rfc_receptor: str
    razon_social_emisor: str | None
    total: float | None
    fecha_emision: datetime | None
    tipo_comprobante: str | None


def parse_cfdi(xml: bytes) -> CamposCFDI:
    """Parsea un CFDI (XML) y extrae los campos del índice (RF-RES-01).

    Único punto de contacto con el parser de ``satcfdi`` (``satcfdi.cfdi.CFDI``);
    no requiere ``Signer`` ni red. Confirmado contra 26.7.3: ``Total`` es
    ``Decimal``, ``Fecha`` es ``datetime`` y ``TipoDeComprobante`` es un ``Code``
    (se toma ``.code``). El UUID vive en el Timbre Fiscal Digital.
    """
    from satcfdi.cfdi import CFDI  # import perezoso

    c = CFDI.from_string(xml)
    tfd = c["Complemento"]["TimbreFiscalDigital"]
    total = c.get("Total")
    fecha = c.get("Fecha")
    tipo = c.get("TipoDeComprobante")
    return CamposCFDI(
        uuid=str(tfd["UUID"]).upper(),
        folio=str(c["Folio"]) if c.get("Folio") is not None else None,
        rfc_emisor=str(c["Emisor"]["Rfc"]),
        rfc_receptor=str(c["Receptor"]["Rfc"]),
        razon_social_emisor=c["Emisor"].get("Nombre"),
        total=float(total) if total is not None else None,
        fecha_emision=fecha if isinstance(fecha, datetime) else None,
        tipo_comprobante=getattr(tipo, "code", None),
    )


class SatFacade:
    """Envoltura delgada sobre ``satcfdi.pacs.sat.SAT``.

    Se construye con el ``Signer`` del cliente (aislamiento por cliente, S4) y su
    RFC. ``satcfdi`` se importa de forma perezosa para no acoplar el resto del
    núcleo a la dependencia.
    """

    def __init__(self, signer: Any, rfc: str) -> None:
        from satcfdi.pacs.sat import SAT  # import perezoso

        self._sat = SAT(signer=signer)
        self._rfc = rfc

    # ---- Solicitud (mapeo tipo → método dedicado · H-04 resuelto) -------- #

    def solicitar(self, job: Job) -> str:
        """Envía la solicitud de descarga masiva y devuelve el ``IdSolicitud``.

        ``satcfdi`` devuelve ``{**res.attrib}`` del XML de respuesta tal cual — cuando el
        SAT rechaza la solicitud de entrada (p. ej. ya existe una solicitud con los mismos
        criterios, RFC no autorizado, límite de solicitudes) el elemento no trae
        ``IdSolicitud``, solo ``CodEstatus``/``Mensaje``. Sin este chequeo, `resp["IdSolicitud"]`
        revienta con ``KeyError`` sin traducirse a `SatRechazoError` (visto en producción:
        el job se queda en NUEVO para siempre, sin mensaje visible para el usuario).
        """
        from satcfdi.pacs.sat import EstadoComprobante, TipoDescargaMasivaTerceros

        comun = dict(
            fecha_inicial=job.fecha_inicial,
            fecha_final=job.fecha_final,
            tipo_solicitud=TipoDescargaMasivaTerceros[job.solicitud.name],
            # El SAT rechaza (CodEstatus=301, "no se permite la descarga de xml que se
            # encuentren cancelados") si se omite este filtro al pedir XML/CFDI. Los
            # cancelados se detectan después vía re-verificación de estatus (RF-VAL,
            # "cancelación tardía"), nunca volviendo a pedirlos en la descarga masiva.
            estado_comprobante=EstadoComprobante.VIGENTE,
        )
        if job.tipo is Tipo.RECIBIDO:
            resp = self._sat.recover_comprobante_received_request(rfc_receptor=self._rfc, **comun)
        else:
            resp = self._sat.recover_comprobante_emitted_request(rfc_emisor=self._rfc, **comun)

        id_solicitud = resp.get("IdSolicitud")
        if not id_solicitud:
            cod = resp.get("CodEstatus", "SIN_CODIGO")
            mensaje = resp.get("Mensaje", "El SAT rechazó la solicitud sin indicar un motivo.")
            raise SatRechazoError(f"El SAT rechazó la solicitud (CodEstatus={cod}): {mensaje}")
        return str(id_solicitud)

    # ---- Verificación (polling) ----------------------------------------- #

    def verificar(self, id_solicitud: str) -> ResultadoVerificacion:
        """Consulta el estatus de la solicitud (polling)."""
        st = self._sat.recover_comprobante_status(id_solicitud)
        return ResultadoVerificacion(
            estado_solicitud=int(st["EstadoSolicitud"]),
            ids_paquetes=list(st.get("IdsPaquetes", []) or []),
            num_cfdis=int(st.get("NumeroCFDIs", 0) or 0),
            mensaje=st.get("Mensaje"),
            cod_estatus=st.get("CodEstatus"),
        )

    # ---- Descarga -------------------------------------------------------- #

    def descargar(self, id_paquete: str) -> tuple[dict[str, Any], str]:
        """Descarga un paquete; devuelve ``(meta, paquete_base64)``.

        ``satcfdi`` entrega el paquete como cadena base64; el ``Engine`` la
        decodifica a bytes antes de escribir el ``.zip`` (RF-DESC-06).
        """
        meta, paquete_b64 = self._sat.recover_comprobante_download(id_paquete)
        return meta, paquete_b64

    # ---- Validación de estatus (sin captcha · Fase 2) ------------------- #

    def status(self, cfdi: Any) -> str:
        """Consulta vigente/cancelado de un CFDI vía ``SAT.status()`` (RF-VAL-01).

        Devuelve el valor del campo ``Estado`` (``Vigente``/``Cancelado``).
        """
        resp = self._sat.status(cfdi)
        return str(resp.get("Estado", "")).strip()

    def status_de_xml(self, xml: bytes) -> str:
        """Parsea el XML a un CFDI y consulta su estatus (RF-VAL-01, Fase 2)."""
        from satcfdi.cfdi import CFDI  # import perezoso

        return self.status(CFDI.from_string(xml))


def consultar_estatus_xml(xml: bytes) -> str:
    """Consulta vigente/cancelado de un CFDI SIN FIEL (validación manual · RF-VAL-01).

    ``SAT.status()`` no usa el ``Signer``: arma una consulta SOAP al endpoint
    público ``ConsultaCFDIService`` a partir de los datos que ya vienen en el XML
    (RFC emisor/receptor, total, UUID). Esto permite validar un XML suelto que el
    operador ya tiene en disco, sin credenciales ni dar de alta un cliente. Único
    punto de contacto con ``satcfdi`` para este flujo (doc 05 §5).
    """
    from satcfdi.cfdi import CFDI  # import perezoso
    from satcfdi.pacs.sat import SAT

    sat = SAT()  # sin signer: status es endpoint público
    resp = sat.status(CFDI.from_string(xml))
    return str(resp.get("Estado", "")).strip()
