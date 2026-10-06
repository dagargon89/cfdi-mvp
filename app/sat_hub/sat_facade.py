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

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .domain import Job, Tipo
from .errors import SatRechazoError, SatReintentableError

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
_COD_EXITO = "5000"


def _codigo_de_estatus(st: dict[str, Any]) -> str | None:
    """El código que de verdad describe la solicitud en una respuesta de verificación.

    La respuesta trae dos: `CodEstatus` (encabezado: ¿se atendió la *consulta*?) y
    `CodigoEstadoSolicitud` (¿cómo terminó la *solicitud*?). Visto en producción el
    2026-10-06: `EstadoSolicitud=5`, `CodigoEstadoSolicitud=5004`, `CodEstatus=5000`
    ("Solicitud Aceptada") para un rango sin CFDI — leer solo el encabezado mandaba a ERROR
    una solicitud válida sin resultados. También se ha visto el 5004 (o el 404 de "Error no
    controlado") solo en el encabezado, con `EstadoSolicitud=0`; por eso, si el código de la
    solicitud es un éxito o no viene, se conserva el del encabezado.
    """
    cod_solicitud = st.get("CodigoEstadoSolicitud")
    if cod_solicitud and str(cod_solicitud) != _COD_EXITO:
        return str(cod_solicitud)
    cod = st.get("CodEstatus")
    return str(cod) if cod is not None else None


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


@contextmanager
def _traduce_fallos_de_red(operacion: str) -> Iterator[None]:
    """Convierte cualquier fallo de transporte hacia el SAT en `SatReintentableError`.

    Sin esta traducción, un hipo de red sale del facade como la excepción cruda de
    ``requests`` (`ConnectionError`, `Timeout`, `SSLError`…), que **no** coincide con el
    ``autoretry_for=(SatReintentableError,)`` de `app.worker.tasks.ejecutar_job`: la tarea muere
    con una excepción no controlada y el job se queda **congelado en su estado, sin mensaje y
    sin nadie que lo retome** — el mismo huérfano que hay que limpiar a mano después.

    Visto en producción el 2026-08-20: el `worker` perdió la resolución de DNS y
    `requests.exceptions.ConnectionError` ("Temporary failure in name resolution") escapó por
    los sondeos de estatus. El backoff de Celery estaba escrito desde el principio, pero
    ninguna ruta real levantaba la excepción que lo dispara: `SatReintentableError` solo
    existía en los dobles de las pruebas.

    Es deliberadamente ancho — se captura `RequestException`, la raíz de la jerarquía de
    ``requests``. Un fallo de transporte nunca es información sobre la solicitud: no dice que
    el SAT la rechazara ni que los datos estén mal, solo que no se pudo preguntar. Reintentar
    es la única respuesta correcta, y el tope de tiempo de sondeo del job (`max_horas_sondeo`) es lo
    que evita que un corte permanente sondee para siempre.
    """
    import requests  # import perezoso, igual que ``satcfdi``

    try:
        yield
    except requests.RequestException as exc:
        raise SatReintentableError(f"No se pudo {operacion}: la red hacia el SAT falló ({exc.__class__.__name__}).") from exc


# Token de autenticación del WS de descarga masiva, por (RFC, número de certificado).
# Cada tarea del worker construye un `SatFacade` nuevo (nunca se cachea el `Signer`, para que
# no quede material descifrado vivo entre invocaciones), y sin esto cada sondeo hacía una
# llamada extra de `Autentica` al SAT. El token dura unos minutos y no es material de llave;
# vive solo en la memoria del proceso del worker.
_TOKENS: dict[tuple[str, str], dict[str, Any]] = {}


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
        self._clave_token = (rfc, str(signer.certificate_number))
        # `SAT` revisa la vigencia del token antes de usarlo y se re-autentica solo si ya
        # expiró (o expira en <30 s), así que sembrarlo con uno cacheado es seguro.
        self._sat.token_comprobante = _TOKENS.get(self._clave_token)

    def _recordar_token(self) -> None:
        clave = getattr(self, "_clave_token", None)
        token = getattr(self._sat, "token_comprobante", None)
        if clave is not None and token is not None:
            _TOKENS[clave] = token

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
        with _traduce_fallos_de_red("enviar la solicitud de descarga"):
            if job.tipo is Tipo.RECIBIDO:
                resp = self._sat.recover_comprobante_received_request(rfc_receptor=self._rfc, **comun)
            else:
                resp = self._sat.recover_comprobante_emitted_request(rfc_emisor=self._rfc, **comun)
        self._recordar_token()

        id_solicitud = resp.get("IdSolicitud")
        if not id_solicitud:
            cod = resp.get("CodEstatus", "SIN_CODIGO")
            mensaje = resp.get("Mensaje", "El SAT rechazó la solicitud sin indicar un motivo.")
            raise SatRechazoError(f"El SAT rechazó la solicitud (CodEstatus={cod}): {mensaje}")
        return str(id_solicitud)

    # ---- Verificación (polling) ----------------------------------------- #

    def verificar(self, id_solicitud: str) -> ResultadoVerificacion:
        """Consulta el estatus de la solicitud (polling)."""
        with _traduce_fallos_de_red("consultar el estatus de la solicitud"):
            st = self._sat.recover_comprobante_status(id_solicitud)
        self._recordar_token()
        return ResultadoVerificacion(
            estado_solicitud=int(st["EstadoSolicitud"]),
            ids_paquetes=list(st.get("IdsPaquetes", []) or []),
            num_cfdis=int(st.get("NumeroCFDIs", 0) or 0),
            mensaje=st.get("Mensaje"),
            cod_estatus=_codigo_de_estatus(st),
        )

    # ---- Descarga -------------------------------------------------------- #

    def descargar(self, id_paquete: str) -> tuple[dict[str, Any], str | None]:
        """Descarga un paquete; devuelve ``(meta, paquete_base64)``.

        ``satcfdi`` entrega el paquete como cadena base64; el ``Engine`` la
        decodifica a bytes antes de escribir el ``.zip`` (RF-DESC-06). El base64
        puede venir ``None`` cuando el SAT responde con el ``<Paquete>`` vacío
        (el motivo llega en ``meta`` como ``CodEstatus``/``Mensaje``); quien
        consume decide qué hacer con ese caso.
        """
        with _traduce_fallos_de_red("descargar el paquete"):
            meta, paquete_b64 = self._sat.recover_comprobante_download(id_paquete)
        self._recordar_token()
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


# Situación tal cual la publica el CSV del SAT (mismos literales que `satcfdi.pacs.TaxpayerStatus`,
# que solo consulta un RFC a la vez contra su propio caché privado en archivo — no sirve para
# bulk-download) → valor de `app.models.enums.SituacionEfos` (RF-RIES-02).
_SITUACION_A_ENUM = {
    "Presunto": "presunto",
    "Definitivo": "definitivo",
    "Desvirtuado": "desvirtuado",
    "Sentencia Favorable": "sentencia_favorable",
}

LISTA_69B_URL = "http://omawww.sat.gob.mx/cifras_sat/Documents/Listado_Completo_69-B.csv"


def descargar_lista_69b() -> list[tuple[str, str]]:
    """Descarga y parsea el CSV público del padrón 69-B completo (RF-RIES-02).

    Endpoint público del SAT, sin firma/e.firma — mismo espíritu que `consultar_estatus_xml`.
    No se usa `satcfdi.pacs.sat.SAT.list_69b()` porque solo consulta un RFC a la vez contra una
    función privada con caché en un archivo local que este proyecto no controla; el CSV es
    público y su parseo es sencillo, así que se hace aquí directamente (único punto de
    contacto con el SAT para este flujo).

    Devuelve una lista de ``(rfc, situacion)`` — ``situacion`` ya normalizada al valor de
    `SituacionEfos` (p. ej. "definitivo"), no al literal en español del CSV. Un mismo RFC
    puede aparecer varias veces en el archivo real del SAT (una fila por cada cambio de
    situación en su historial — p. ej. "presunto" y luego, más abajo, "definitivo"; o
    "definitivo" y luego "sentencia_favorable" si el contribuyente ganó su caso). Solo
    interesa el estado VIGENTE, así que se deduplica quedándose con la última fila del
    archivo para cada RFC (el orden del CSV es cronológico: la entrada más reciente de un
    RFC siempre queda más abajo que las anteriores) — confirmado con el archivo real
    (82 RFC repetidos en la descarga de producción del 2026-07-28).
    """
    import csv
    from itertools import islice

    import requests

    respuesta = requests.get(LISTA_69B_URL, headers={"User-Agent": "hub-cfdi/1.0"}, timeout=30)
    respuesta.raise_for_status()
    lineas = str(respuesta.content, "windows-1250").splitlines(keepends=True)
    lector = csv.reader(islice(lineas, 3, None), delimiter=",", quotechar='"')

    por_rfc: dict[str, str] = {}
    for fila in lector:
        if len(fila) < 4:
            continue
        rfc, situacion_cruda = fila[1].strip(), fila[3].strip()
        situacion = _SITUACION_A_ENUM.get(situacion_cruda)
        if situacion is None:
            continue  # fila con una situación que no reconocemos — se ignora, no se rompe el cruce
        por_rfc[rfc] = situacion  # una fila posterior del mismo RFC sobreescribe a la anterior
    return list(por_rfc.items())
