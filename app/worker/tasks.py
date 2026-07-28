"""Tarea Celery `ejecutar_job` — un paso de la máquina de estados por invocación
(doc 01 §1.6, doc 07 Sprint 2).

La lógica de negocio vive en `paso_job` (async, sin Celery, sin sleeps reales) para que
las pruebas la ejerciten en un bucle síncrono y deterministic. `ejecutar_job` es el
adaptador que Celery invoca de verdad: abre su propia sesión de BD, corre `paso_job` con
`asyncio.run` y traduce "seguir sondeando" en `self.retry(countdown=...)`.

Dos mecanismos de reintento independientes, a propósito:
- `autoretry_for=(SatReintentableError,)` (con `max_retries` normal) — intermitencia de
  red/SAT al llamar `solicitar`/`verificar` (doc 06 §2.5 "intermitencia transitoria").
- `self.retry(..., max_retries=_SIN_LIMITE_CELERY)` explícito — "sigue en proceso, vuelve
  a sondear"; el tope real de esto es `configuracion.max_reintentos` (T8), NUNCA el
  `max_retries` de Celery (que solo debe acotar errores, no el sondeo normal).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.enums import EstadoJob, EstatusCfdi
from app.models.job import Job
from app.repositories import comprobantes as comprobantes_repo
from app.repositories import configuracion as config_repo
from app.repositories import jobs as jobs_repo
from app.sat_hub.domain import Job as DominioJob
from app.sat_hub.domain import Solicitud as DominioSolicitud
from app.sat_hub.domain import Tipo as DominioTipo
from app.sat_hub.errors import FielVencidaError, SatRechazoError, SatReintentableError
from app.sat_hub.sat_facade import ESTADOS_EN_PROCESO, ESTADOS_RECHAZO, ESTADOS_TERMINADA, SatFacade, consultar_estatus_xml
from app.services import resguardo
from app.services.descargas import EfirmaAusenteError, signer_para_empresa
from app.worker.celery_app import celery_app

logger = logging.getLogger("app.worker")

_SIN_LIMITE_CELERY = 1_000_000

# `asyncio.run()` (abajo) crea y cierra un event loop nuevo en CADA invocación del task —
# un engine con pool normal (como el de `app.db.session`, pensado para el proceso de la API
# con un solo loop de por vida) retiene conexiones asyncmy atadas al loop en que se
# crearon; al reusarlas desde el loop siguiente revienta con "Future attached to a
# different loop" (visto en producción, en el segundo sondeo de un job real). `NullPool`
# abre y cierra una conexión nueva por sesión — nunca hay una conexión que sobreviva al
# loop que la creó.
_engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
SessionLocal = async_sessionmaker(_engine, expire_on_commit=False)


@dataclass(slots=True)
class ResultadoPaso:
    siguiente: str  # "hecho" | "reintentar"
    countdown: int = 0


def _a_dominio(job: Job) -> DominioJob:
    return DominioJob(
        job_id=job.job_id,
        client_id=job.empresa_id,
        tipo=DominioTipo(job.tipo.value),
        solicitud=DominioSolicitud(job.solicitud.value),
        fecha_inicial=job.fecha_inicial,
        fecha_final=job.fecha_final,
    )


def _ruta_paquete(empresa_id: int, job_id: int, indice: int) -> str:
    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), str(job_id))
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, f"paquete_{indice}.zip")


def _escribir_paquete(empresa_id: int, job_id: int, indice: int, paquete_b64: str) -> None:
    with open(_ruta_paquete(empresa_id, job_id, indice), "wb") as f:
        f.write(base64.b64decode(paquete_b64))


async def _cargar_job(db: AsyncSession, job_id: int) -> Job | None:
    result: Job | None = await db.scalar(select(Job).options(selectinload(Job.empresa)).where(Job.job_id == job_id))
    return result


async def _paso_nuevo(db: AsyncSession, job: Job) -> ResultadoPaso:
    try:
        signer = await signer_para_empresa(db, job.empresa)
    except (EfirmaAusenteError, FielVencidaError) as exc:
        await jobs_repo.transicion(db, job, EstadoJob.ERROR, mensaje=str(exc))  # T2
        await db.commit()
        return ResultadoPaso("hecho")

    facade = SatFacade(signer, job.empresa.rfc)
    try:
        id_solicitud = facade.solicitar(_a_dominio(job))
    except SatRechazoError as exc:
        await jobs_repo.transicion(db, job, EstadoJob.ERROR, mensaje=str(exc))
        await db.commit()
        return ResultadoPaso("hecho")
    # SatReintentableError se deja propagar sin tocar el job (sigue en NUEVO); el
    # adaptador Celery decide el backoff vía `autoretry_for`.

    espera = await config_repo.valor(db, "polling_espera_seg", 60)
    await jobs_repo.transicion(db, job, EstadoJob.SOLICITADO, id_solicitud=id_solicitud)  # T1
    await db.commit()
    return ResultadoPaso("reintentar", countdown=espera)


async def _descargar_paquetes(db: AsyncSession, job: Job, facade: SatFacade, ids_paquetes: list[str]) -> None:
    escritos = 0
    try:
        for idx, id_paquete in enumerate(ids_paquetes, start=1):
            _, paquete_b64 = facade.descargar(id_paquete)
            _escribir_paquete(job.empresa_id, job.job_id, idx, paquete_b64)
            escritos += 1
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de escritura/descarga es terminal (T10)
        await jobs_repo.transicion(db, job, EstadoJob.ERROR, mensaje=f"Fallo al descargar paquetes ({escritos}/{job.paquetes} escritos): {exc}")
        await db.commit()
        return
    if escritos != job.paquetes:
        # doc 06 §2.7 A08: paquetes reportados ≠ archivos escritos → nunca pasa a DESCARGADO.
        await jobs_repo.transicion(db, job, EstadoJob.ERROR, mensaje=f"Se esperaban {job.paquetes} paquetes; se escribieron {escritos}.")
        await db.commit()
        return
    await jobs_repo.transicion(db, job, EstadoJob.DESCARGADO)  # T9
    await db.commit()

    # Resguardo encadenado (RF-RES-01…03, doc 06 §2.5) — en la misma ejecución, nunca una
    # tarea Celery aparte. Un fallo aquí no revierte el job: los paquetes crudos ya están a
    # salvo (contrato de T9 ya cumplido); indexar_job es idempotente y puede reintentarse.
    try:
        nuevos = await resguardo.indexar_job(db, job, job.empresa)
        logger.info("resguardo: %s comprobantes nuevos indexados (job %s).", nuevos, job.job_id)
    except Exception:  # noqa: BLE001 — el job ya es DESCARGADO; esto no debe corromper su estado
        logger.exception("resguardo: fallo indexando el job %s.", job.job_id)


async def _paso_polling(db: AsyncSession, job: Job) -> ResultadoPaso:
    assert job.id_solicitud is not None  # garantizado por T1: NUEVO→SOLICITADO siempre lo asigna
    signer = await signer_para_empresa(db, job.empresa)
    facade = SatFacade(signer, job.empresa.rfc)
    resultado = facade.verificar(job.id_solicitud)  # SatReintentableError se propaga (backoff de Celery)

    if resultado.estado_solicitud in ESTADOS_RECHAZO:
        await jobs_repo.transicion(db, job, EstadoJob.ERROR, mensaje=resultado.mensaje or "Rechazo definitivo del SAT.")  # T5/T8
        await db.commit()
        return ResultadoPaso("hecho")

    if resultado.estado_solicitud in ESTADOS_TERMINADA:
        await jobs_repo.transicion(db, job, EstadoJob.TERMINADA, paquetes=len(resultado.ids_paquetes))  # T4/T7
        await db.commit()
        await _descargar_paquetes(db, job, facade, resultado.ids_paquetes)
        return ResultadoPaso("hecho")

    # Cualquier otro código (los documentados de "en proceso" 1-2, o uno no catalogado por
    # satcfdi — visto en producción: el SAT respondió un EstadoSolicitud fuera de 1-6
    # mientras aún procesaba) se trata igual: sigue en proceso. Nunca asumir TERMINADA ni
    # ERROR ante un código desconocido — el tope real es `configuracion.max_reintentos` (T8).
    if resultado.estado_solicitud not in ESTADOS_EN_PROCESO:
        logger.warning("ejecutar_job: EstadoSolicitud %s no catalogado para job %s; se trata como 'en proceso'.", resultado.estado_solicitud, job.job_id)

    max_reintentos = await config_repo.valor(db, "max_reintentos", 60)
    intentos = job.intentos + 1
    if intentos >= max_reintentos:
        await jobs_repo.transicion(db, job, EstadoJob.ERROR, mensaje=f"Se agotaron los reintentos de sondeo sin que el SAT terminara la solicitud (último EstadoSolicitud={resultado.estado_solicitud}).", intentos=intentos)  # T8
        await db.commit()
        return ResultadoPaso("hecho")
    await jobs_repo.transicion(db, job, EstadoJob.EN_PROCESO, intentos=intentos)  # T3/T6
    await db.commit()
    espera = await config_repo.valor(db, "polling_espera_seg", 60)
    return ResultadoPaso("reintentar", countdown=espera)


async def paso_job(db: AsyncSession, job_id: int) -> ResultadoPaso:
    """Ejecuta exactamente un paso de la máquina de estados para `job_id`.

    Re-entrante y sin estado en memoria: relee todo de la BD, así que si un worker
    muere a medias, la siguiente invocación retoma desde el estado persistido sin
    duplicar `id_solicitud` (RF-DESC-04, doc 06 §2.5 "reanudación").
    """
    job = await _cargar_job(db, job_id)
    if job is None:
        logger.warning("ejecutar_job: el job %s ya no existe.", job_id)
        return ResultadoPaso("hecho")

    if job.estado is EstadoJob.NUEVO:
        return await _paso_nuevo(db, job)
    if job.estado in (EstadoJob.SOLICITADO, EstadoJob.EN_PROCESO):
        return await _paso_polling(db, job)

    logger.info("ejecutar_job: job %s en estado terminal %s, nada que hacer.", job_id, job.estado.value)
    return ResultadoPaso("hecho")


async def _paso_con_sesion_propia(job_id: int) -> ResultadoPaso:
    async with SessionLocal() as db:
        return await paso_job(db, job_id)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="app.worker.tasks.ejecutar_job",
    autoretry_for=(SatReintentableError,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=8,
)
def ejecutar_job(self, job_id: int) -> None:  # type: ignore[no-untyped-def]
    resultado = asyncio.run(_paso_con_sesion_propia(job_id))
    if resultado.siguiente == "reintentar":
        raise self.retry(countdown=resultado.countdown, max_retries=_SIN_LIMITE_CELERY)


# --------------------------------------------------------------------------- #
# Validación en lote (RF-VAL-01/02/03, doc 05 §6) — tareas de un solo disparo,
# sin máquina de estados propia (no son `jobs`). `consultar_estatus_xml` no usa
# `Signer` (endpoint público del SAT, doc 05 §5): esta tarea nunca toca la bóveda.
# --------------------------------------------------------------------------- #


async def _validar_lote_async(empresa_id: int, comprobante_ids: list[int]) -> dict[str, int]:
    exitosos = 0
    fallidos = 0
    storage_root = get_settings().storage_root
    async with SessionLocal() as db:
        for c in await comprobantes_repo.por_ids(db, empresa_id, comprobante_ids):
            if not c.xml_path:
                fallidos += 1
                continue
            try:
                with open(os.path.join(storage_root, c.xml_path), "rb") as f:
                    xml_bytes = f.read()
                estado = consultar_estatus_xml(xml_bytes)
                c.estatus = EstatusCfdi.VIGENTE if estado.strip().lower() == "vigente" else EstatusCfdi.CANCELADO
                c.estatus_verificado_at = datetime.now(timezone.utc).replace(tzinfo=None)
                exitosos += 1
            except Exception as exc:  # noqa: BLE001 — RF-VAL-02: un CFDI no consultable no aborta el lote
                logger.warning("validar_lote: no se pudo validar el comprobante %s: %s", c.comprobante_id, exc)
                fallidos += 1
        await db.commit()
    return {"total": len(comprobante_ids), "exitosos": exitosos, "fallidos": fallidos}


@celery_app.task(name="app.worker.tasks.validar_lote")  # type: ignore[untyped-decorator]
def validar_lote(empresa_id: int, comprobante_ids: list[int]) -> dict[str, int]:
    return asyncio.run(_validar_lote_async(empresa_id, comprobante_ids))


# --------------------------------------------------------------------------- #
# Export a Excel (RF-LIST-02, doc 05 §6) — streaming (openpyxl `write_only`) y
# paginado por lotes, para no cargar 100k filas en memoria de una vez (doc 06 §3).
# --------------------------------------------------------------------------- #

_COLUMNAS_EXPORT = ("UUID", "Folio", "RFC emisor", "RFC receptor", "Razón social emisor", "Total", "Fecha emisión", "Tipo", "Estatus", "Verificado")
_TAMANO_LOTE_EXPORT = 5000


async def _exportar_excel_async(empresa_id: int, filtros: dict[str, Any]) -> dict[str, Any]:
    from openpyxl import Workbook

    desde = date.fromisoformat(filtros["desde"]) if filtros.get("desde") else None
    hasta = date.fromisoformat(filtros["hasta"]) if filtros.get("hasta") else None
    estatus = EstatusCfdi(filtros["estatus"]) if filtros.get("estatus") else None

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Comprobantes")
    ws.append(_COLUMNAS_EXPORT)

    total_filas = 0
    async with SessionLocal() as db:
        pagina = 1
        while True:
            filas, _ = await comprobantes_repo.listar(
                db,
                empresa_id,
                desde=desde,
                hasta=hasta,
                tipo_comprobante=filtros.get("tipo_comprobante"),
                estatus=estatus,
                rfc_contraparte=filtros.get("rfc_contraparte"),
                q=filtros.get("q"),
                page=pagina,
                per_page=_TAMANO_LOTE_EXPORT,
            )
            for c in filas:
                ws.append(
                    (
                        c.uuid,
                        c.folio,
                        c.rfc_emisor,
                        c.rfc_receptor,
                        c.razon_social_emisor,
                        float(c.total) if c.total is not None else None,
                        c.fecha_emision.isoformat() if c.fecha_emision else None,
                        c.tipo_comprobante,
                        c.estatus.value,
                        c.estatus_verificado_at.isoformat() if c.estatus_verificado_at else None,
                    )
                )
            total_filas += len(filas)
            if len(filas) < _TAMANO_LOTE_EXPORT:
                break
            pagina += 1

    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), "exports")
    os.makedirs(carpeta, exist_ok=True)
    nombre = f"comprobantes_{uuid.uuid4().hex[:12]}.xlsx"
    wb.save(os.path.join(carpeta, nombre))
    ruta_relativa = os.path.join(str(empresa_id), "exports", nombre)
    return {"ruta": ruta_relativa, "filas": total_filas}


@celery_app.task(name="app.worker.tasks.exportar_excel")  # type: ignore[untyped-decorator]
def exportar_excel(empresa_id: int, filtros: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_exportar_excel_async(empresa_id, filtros))
