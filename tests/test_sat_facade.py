"""Pruebas de `SatFacade` — la frontera con `satcfdi`/`requests`.

Aquí se prueba la **traducción de fallos** a las excepciones del dominio. Es el único lugar
donde puede hacerse: `tests/test_worker.py` sustituye el `SatFacade` entero por un doble, así
que ninguna prueba del worker ejercita esta capa.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
import requests

from app.sat_hub.errors import SatReintentableError
from app.sat_hub.sat_facade import COD_ESTATUS_SIN_RESULTADOS, SatFacade


def _facade_con_sat(sat_doble: Any) -> SatFacade:
    """Construye un `SatFacade` alrededor de un doble de `satcfdi.pacs.sat.SAT`.

    Se evita `__init__` a propósito: el constructor real importa `satcfdi` y construye un
    `SAT` con un `Signer`, que esta prueba no necesita — lo que se prueba es cómo el facade
    trata lo que su dependencia le lanza, no cómo la construye.
    """
    facade = SatFacade.__new__(SatFacade)
    facade._sat = sat_doble
    facade._rfc = "CHL960913IX9"
    return facade


class _SatSinRed:
    """Doble de `SAT` que falla como falla la red de verdad.

    El mensaje es el que apareció en producción el 2026-08-20 con el `worker` sin DNS.
    """

    _MENSAJE = (
        "HTTPSConnectionPool(host='cfdidescargamasivasolicitud.clouda.sat.gob.mx', port=443): "
        "Max retries exceeded with url: /Autenticacion/Autenticacion.svc "
        "(Caused by NameResolutionError(\"Failed to resolve ... "
        "[Errno -3] Temporary failure in name resolution\"))"
    )

    def recover_comprobante_status(self, id_solicitud: str) -> dict[str, Any]:
        raise requests.exceptions.ConnectionError(self._MENSAJE)


def test_un_fallo_de_red_al_verificar_es_intermitencia_no_una_excepcion_cruda() -> None:
    """Un fallo de red no es un rechazo del SAT ni un error de programación: es la
    intermitencia que `autoretry_for=(SatReintentableError,)` existe para absorber.

    Sin esta traducción, `requests.exceptions.ConnectionError` escapa del facade, no coincide
    con el `autoretry_for` de `ejecutar_job`, mata la tarea con una excepción no controlada y
    **deja el job congelado en su estado, sin mensaje y sin reintento** — nadie lo retoma.
    Ocurrió en producción el 2026-08-20 con los jobs de sondeo del SAT.
    """
    facade = _facade_con_sat(_SatSinRed())

    with pytest.raises(SatReintentableError):
        facade.verificar("ID-SOLICITUD-CUALQUIERA")


class _SatQueFallaAlSolicitar(_SatSinRed):
    def recover_comprobante_emitted_request(self, **kwargs: Any) -> dict[str, Any]:
        raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=30)")

    def recover_comprobante_received_request(self, **kwargs: Any) -> dict[str, Any]:
        raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=30)")


class _SatQueFallaAlDescargar(_SatSinRed):
    def recover_comprobante_download(self, id_paquete: str) -> tuple[dict[str, Any], str]:
        raise requests.exceptions.SSLError("EOF occurred in violation of protocol")


def test_un_timeout_al_solicitar_es_intermitencia_no_un_rechazo_del_sat() -> None:
    """Un timeout al pedir la descarga no significa que el SAT rechazara la solicitud.

    Importa distinguirlo: un `SatRechazoError` manda el job a ERROR de forma definitiva, y un
    timeout no autoriza esa conclusión — la solicitud pudo incluso haberse creado del otro
    lado. Lo único correcto es reintentar.
    """
    from app.sat_hub.domain import Job as JobDominio
    from app.sat_hub.domain import Solicitud, Tipo

    facade = _facade_con_sat(_SatQueFallaAlSolicitar())
    job = JobDominio(
        job_id=1,
        client_id=11,
        tipo=Tipo.EMITIDO,
        solicitud=Solicitud.CFDI,
        fecha_inicial=date(2026, 8, 1),
        fecha_final=date(2026, 8, 2),
    )

    with pytest.raises(SatReintentableError):
        facade.solicitar(job)


def test_un_fallo_de_tls_al_descargar_es_intermitencia() -> None:
    """Un paquete que no se pudo bajar por la red se vuelve a intentar; el job no se cae."""
    facade = _facade_con_sat(_SatQueFallaAlDescargar())

    with pytest.raises(SatReintentableError):
        facade.descargar("ID-PAQUETE-1")


class _SatConEstatus:
    """Doble de `SAT` que responde a la verificación con un diccionario fijo."""

    def __init__(self, respuesta: dict[str, Any]) -> None:
        self._respuesta = respuesta

    def recover_comprobante_status(self, id_solicitud: str) -> dict[str, Any]:
        return self._respuesta


def test_sin_resultados_se_lee_de_codigo_estado_solicitud_no_del_encabezado() -> None:
    """Respuesta real del 2026-10-06 (sync de un rango sin CFDI emitidos): el encabezado dice
    5000/"Solicitud Aceptada", pero la solicitud terminó con 5004. Antes se leía solo
    `CodEstatus` y el job caía en ERROR con el mensaje "Solicitud Aceptada"."""
    facade = _facade_con_sat(
        _SatConEstatus(
            {"IdsPaquetes": [], "CodEstatus": "5000", "EstadoSolicitud": 5, "CodigoEstadoSolicitud": "5004", "NumeroCFDIs": 0, "Mensaje": "Solicitud Aceptada"}
        )
    )

    assert facade.verificar("ID").cod_estatus == COD_ESTATUS_SIN_RESULTADOS


@pytest.mark.parametrize(
    ("respuesta", "esperado"),
    [
        # En proceso: ambos códigos son éxito.
        ({"CodEstatus": "5000", "EstadoSolicitud": 2, "CodigoEstadoSolicitud": "5000", "Mensaje": "Solicitud Aceptada"}, "5000"),
        # 5004 solo en el encabezado, con EstadoSolicitud=0 (caso previo, test_worker).
        ({"CodEstatus": "5004", "EstadoSolicitud": 0, "Mensaje": "No se encontró la información"}, "5004"),
        # "Error no controlado": el 404 del encabezado no debe perderse.
        ({"CodEstatus": "404", "EstadoSolicitud": 0, "Mensaje": "Error no controlado."}, "404"),
    ],
)
def test_sin_codigo_de_solicitud_relevante_se_conserva_el_del_encabezado(respuesta: dict[str, Any], esperado: str) -> None:
    assert _facade_con_sat(_SatConEstatus(respuesta)).verificar("ID").cod_estatus == esperado
