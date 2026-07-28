"""Orquestación de descargas masivas (doc 05 §5, doc 07 Sprint 2).

Dos responsabilidades separadas:
- `crear_descarga`: valida la empresa/e.firma y trocea el rango en jobs `NUEVO`
  (llamado por la API, sin tocar el SAT ni la bóveda más que para leer metadatos).
- `signer_para_empresa`: descifra la e.firma y construye el `Signer` de `satcfdi`
  (llamado por el worker en el paso NUEVO→SOLICITADO — nunca por la API).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.efirma import Efirma
from app.models.empresa import Empresa
from app.models.enums import OrigenJob, SolicitudTipo, TipoJob
from app.models.job import Job
from app.repositories import configuracion as config_repo
from app.repositories import efirmas as efirmas_repo
from app.repositories import jobs as jobs_repo
from app.sat_hub.daterange import trocear
from app.sat_hub.errors import FielVencidaError, HubError
from app.services import bitacora as bitacora_service
from app.services import boveda
from app.services.fiel import cargar_signer, validar_vigencia


class EfirmaAusenteError(HubError):
    """La empresa no tiene ninguna e.firma registrada en la bóveda (doc 05 §5)."""


class EmpresaInactivaError(HubError):
    """La empresa está desactivada (RF-EMP-02); no se le pueden crear descargas."""


class RangoInvalidoError(HubError):
    """El rango de fechas es inválido o queda fuera del tope de antigüedad (RF-DESC-01)."""


def _efirma_vencida(efirma: Efirma) -> bool:
    """`not_after` se persiste como UTC-naive (MySQL DATETIME); se compara contra la hora
    actual en UTC pero sin tzinfo, con la misma convención — nunca contra un valor tz-aware."""
    return efirma.not_after <= datetime.now(timezone.utc).replace(tzinfo=None)


async def crear_descarga(
    db: AsyncSession,
    empresa: Empresa,
    *,
    tipo: TipoJob,
    solicitud: SolicitudTipo,
    desde: date,
    hasta: date,
    hoy: date | None = None,
    origen: OrigenJob = OrigenJob.MANUAL,
) -> list[Job]:
    if not empresa.activo:
        raise EmpresaInactivaError("La empresa está desactivada; no se pueden crear descargas.")

    efirma = await efirmas_repo.por_empresa(db, empresa.empresa_id)
    if efirma is None:
        raise EfirmaAusenteError("Esta empresa no tiene e.firma registrada en la bóveda.")
    if _efirma_vencida(efirma):
        raise FielVencidaError("La e.firma de esta empresa está vencida; el SAT rechazará la solicitud.")

    if desde == hasta:
        # Confirmado en producción (2026-07-28, sync diaria de la empresa 11): el SAT rechaza
        # (CodEstatus=301) un rango de un solo día calendario — `FechaInicial`/`FechaFinal` se
        # serializan como fecha sin hora (`app/sat_hub/sat_facade.py`, vía `satcfdi`), así que
        # ambas quedan iguales y el WS las trata como "fecha inicial >= fecha final". `trocear`
        # ya rechaza `hasta < desde`; esto cubre el caso que se le escapa (`hasta == desde`).
        raise RangoInvalidoError("El rango debe cubrir al menos 2 días distintos — el SAT no acepta una sola fecha para inicio y fin.")

    ventana_meses = await config_repo.valor(db, "max_meses_ventana", 12)
    antiguedad_anios = await config_repo.valor(db, "max_anios_antiguedad", 5)
    try:
        ventanas = trocear(desde, hasta, hoy=hoy or date.today(), ventana_meses=ventana_meses, antiguedad_anios=antiguedad_anios)
    except ValueError as exc:
        raise RangoInvalidoError(str(exc)) from exc

    return await jobs_repo.crear_lote(db, empresa_id=empresa.empresa_id, tipo=tipo, solicitud=solicitud, ventanas=ventanas, origen=origen)


async def signer_para_empresa(db: AsyncSession, empresa: Empresa, *, actor: str = "sistema:worker") -> Any:
    """Descifra la e.firma de la empresa y devuelve el `Signer` listo para `SatFacade`.

    Lanza `EfirmaAusenteError` o `FielVencidaError` (T2: NUEVO→ERROR sin encolar). El
    material descifrado (llave privada + contraseña) vive solo en variables locales de
    esta función — nunca se retorna ni se loguea, solo el `Signer` ya construido.
    """
    efirma = await efirmas_repo.por_empresa(db, empresa.empresa_id)
    if efirma is None:
        raise EfirmaAusenteError("Esta empresa no tiene e.firma registrada en la bóveda.")

    kek = boveda.cargar_kek()
    dek = boveda.desenvolver_dek(kek, efirma.dek_envuelta)
    key_bytes = boveda.descifrar(dek, efirma.key_cifrada)
    password = boveda.descifrar(dek, efirma.password_cifrada).decode()
    signer = cargar_signer(efirma.cer_pem, key_bytes, password)
    validar_vigencia(signer)  # relee la vigencia directamente del certificado (RF-BOV-02)

    await bitacora_service.registrar(
        db, actor=actor, accion="uso_boveda", entidad=f"empresa:{empresa.empresa_id}", detalle={"num_serie": efirma.num_serie}
    )
    return signer
