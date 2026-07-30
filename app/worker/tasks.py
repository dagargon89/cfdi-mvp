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
import io
import logging
import os
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.enums import EstadoJob, EstatusCfdi, OrigenJob, ResultadoNotificacion, SolicitudTipo, TipoEvento, TipoJob
from app.models.evento import Evento
from app.models.job import Job
from app.repositories import comprobantes as comprobantes_repo
from app.repositories import configuracion as config_repo
from app.repositories import empresas as empresas_repo
from app.repositories import eventos as eventos_repo
from app.repositories import jobs as jobs_repo
from app.repositories import lista_69b as lista_69b_repo
from app.repositories import notificaciones as notificaciones_repo
from app.sat_hub.domain import Job as DominioJob
from app.sat_hub.domain import Solicitud as DominioSolicitud
from app.sat_hub.domain import Tipo as DominioTipo
from app.sat_hub.errors import FielVencidaError, SatRechazoError, SatReintentableError
from app.sat_hub.sat_facade import (
    COD_ESTATUS_SIN_RESULTADOS,
    ESTADOS_EN_PROCESO,
    ESTADOS_RECHAZO,
    ESTADOS_TERMINADA,
    ResultadoVerificacion,
    SatFacade,
    consultar_estatus_xml,
    descargar_lista_69b,
)
from app.services import notificaciones as notificaciones_service
from app.services import representaciones
from app.services import resguardo
from app.services import riesgo as riesgo_service
from app.services.descargas import EfirmaAusenteError, EmpresaInactivaError, RangoInvalidoError, crear_descarga, signer_para_empresa
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


_REINTENTOS_INMEDIATOS_PARPADEO = 2
_ESPERA_PARPADEO_SEG = 3


def _es_resultado_definitivo(resultado: ResultadoVerificacion) -> bool:
    """True si no hace falta el margen de gracia de "parpadeo" — ya es un resultado que
    sabemos clasificar con certeza (incluye `COD_ESTATUS_SIN_RESULTADOS`, que llega con
    `EstadoSolicitud=0` pero es un éxito documentado, no un código ambiguo)."""
    return (
        resultado.estado_solicitud in ESTADOS_EN_PROCESO | ESTADOS_TERMINADA | ESTADOS_RECHAZO
        or resultado.cod_estatus == COD_ESTATUS_SIN_RESULTADOS
    )


async def _paso_polling(db: AsyncSession, job: Job) -> ResultadoPaso:
    assert job.id_solicitud is not None  # garantizado por T1: NUEVO→SOLICITADO siempre lo asigna
    signer = await signer_para_empresa(db, job.empresa)
    facade = SatFacade(signer, job.empresa.rfc)
    resultado = facade.verificar(job.id_solicitud)  # SatReintentableError se propaga (backoff de Celery)

    # Un código no catalogado por satcfdi (fuera de 1-6) CON un mensaje del SAT no es "sigue en
    # proceso" silencioso — es el WS respondiendo un error explícito. Visto en producción con una
    # solicitud de METADATA: el WS "parpadeó" (error/éxito/error de nuevo en menos de un minuto)
    # — unos segundos de gracia in-proceso antes de rendirse evita fallar un job que se hubiera
    # recuperado solo en el siguiente intento, sin gastar un sondeo completo (countdown de
    # `polling_espera_seg`, minutos) por cada parpadeo.
    intentos_parpadeo = 0
    while not _es_resultado_definitivo(resultado) and resultado.mensaje and intentos_parpadeo < _REINTENTOS_INMEDIATOS_PARPADEO:
        intentos_parpadeo += 1
        logger.warning(
            "ejecutar_job: EstadoSolicitud %s con mensaje %r para job %s — reintento inmediato %s/%s.",
            resultado.estado_solicitud,
            resultado.mensaje,
            job.job_id,
            intentos_parpadeo,
            _REINTENTOS_INMEDIATOS_PARPADEO,
        )
        await asyncio.sleep(_ESPERA_PARPADEO_SEG)
        resultado = facade.verificar(job.id_solicitud)

    if resultado.cod_estatus == COD_ESTATUS_SIN_RESULTADOS:
        # "5004: No se encontró la información" — la solicitud es válida, simplemente no hay
        # CFDI que coincidan con el rango/tipo pedido. Éxito con cero paquetes, no un error
        # (visto en producción: una solicitud de METADATA sin comprobantes ese mes).
        await jobs_repo.transicion(db, job, EstadoJob.TERMINADA, paquetes=0)  # T4/T7
        await db.commit()
        await _descargar_paquetes(db, job, facade, [])
        return ResultadoPaso("hecho")

    if resultado.estado_solicitud in ESTADOS_RECHAZO:
        await jobs_repo.transicion(db, job, EstadoJob.ERROR, mensaje=resultado.mensaje or "Rechazo definitivo del SAT.")  # T5/T8
        await db.commit()
        return ResultadoPaso("hecho")

    if resultado.estado_solicitud in ESTADOS_TERMINADA:
        await jobs_repo.transicion(db, job, EstadoJob.TERMINADA, paquetes=len(resultado.ids_paquetes))  # T4/T7
        await db.commit()
        await _descargar_paquetes(db, job, facade, resultado.ids_paquetes)
        return ResultadoPaso("hecho")

    if resultado.estado_solicitud not in ESTADOS_EN_PROCESO:
        if resultado.mensaje:
            # Ya se le dio su margen de gracia (parpadeo) arriba y sigue fallando — esto sí es
            # un error real, no vale la pena agotar 60 reintentos (~1h) para mostrar lo mismo.
            await jobs_repo.transicion(
                db, job, EstadoJob.ERROR, mensaje=f"El SAT respondió un error (EstadoSolicitud={resultado.estado_solicitud}): {resultado.mensaje}"
            )
            await db.commit()
            return ResultadoPaso("hecho")
        # Código desconocido SIN mensaje (silencio, no un error explícito) — sí es transitorio.
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
                estatus_anterior = c.estatus
                c.estatus = EstatusCfdi.VIGENTE if estado.strip().lower() == "vigente" else EstatusCfdi.CANCELADO
                c.estatus_verificado_at = datetime.now(timezone.utc).replace(tzinfo=None)
                if estatus_anterior is EstatusCfdi.VIGENTE and c.estatus is EstatusCfdi.CANCELADO:
                    # RF-RIES-01: solo nos interesa la cancelación de un CFDI que YA se había
                    # dado por vigente antes — no la primera verificación de uno recién bajado.
                    await riesgo_service.registrar_cancelacion_tardia(db, c)
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
        direccion = filtros.get("direccion")
        rfc_empresa = None
        if direccion:
            empresa = await empresas_repo.por_id(db, empresa_id)
            rfc_empresa = empresa.rfc if empresa else None

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
                direccion=direccion,
                rfc_empresa=rfc_empresa,
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


# --------------------------------------------------------------------------- #
# Descarga por lote (XML+PDF+Detalle de varios comprobantes en un solo .zip) —
# selección por casillas en la tabla de Comprobantes (RF-RES-03/D2).
# --------------------------------------------------------------------------- #


_TIPO_TEXTO = {"I": "Ingreso", "E": "Egreso", "N": "Nómina", "P": "Pago", "T": "Traslado"}


async def _descargar_zip_lote_async(empresa_id: int, comprobante_ids: list[int]) -> dict[str, Any]:
    storage_root = get_settings().storage_root
    incluidos = 0
    buffer = io.BytesIO()
    async with SessionLocal() as db:
        empresa = await empresas_repo.por_id(db, empresa_id)
        rfc_empresa = empresa.rfc if empresa else None
        comprobantes = await comprobantes_repo.por_ids(db, empresa_id, comprobante_ids)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for c in comprobantes:
                xml_bytes = representaciones.leer_xml_de_disco(storage_root, c)
                if xml_bytes is None:
                    logger.warning("descargar_zip_lote: comprobante %s sin XML en disco, se omite.", c.comprobante_id)
                    continue
                # Organización del zip: Emitidos|Recibidos / año-mes / tipo (mejora de UX 2026-07-30).
                direccion = "Emitidos" if rfc_empresa and c.rfc_emisor == rfc_empresa else "Recibidos"
                periodo = c.fecha_emision.strftime("%Y-%m") if c.fecha_emision else "sin-fecha"
                tipo = _TIPO_TEXTO.get(c.tipo_comprobante or "", "Otro")
                carpeta = f"{direccion}/{periodo}/{tipo}"
                zf.writestr(f"{carpeta}/{c.uuid}.xml", xml_bytes)
                zf.writestr(f"{carpeta}/{c.uuid}.pdf", representaciones.generar_pdf(xml_bytes))
                zf.writestr(f"{carpeta}/{c.uuid}_detalle.pdf", representaciones.generar_detalle(xml_bytes, c.estatus))
                incluidos += 1

    carpeta = os.path.join(storage_root, str(empresa_id), "exports")
    os.makedirs(carpeta, exist_ok=True)
    nombre = f"comprobantes_{uuid.uuid4().hex[:12]}.zip"
    with open(os.path.join(carpeta, nombre), "wb") as f:
        f.write(buffer.getvalue())
    ruta_relativa = os.path.join(str(empresa_id), "exports", nombre)
    return {"ruta": ruta_relativa, "incluidos": incluidos, "solicitados": len(comprobante_ids)}


@celery_app.task(name="app.worker.tasks.descargar_zip_lote")  # type: ignore[untyped-decorator]
def descargar_zip_lote(empresa_id: int, comprobante_ids: list[int]) -> dict[str, Any]:
    return asyncio.run(_descargar_zip_lote_async(empresa_id, comprobante_ids))


# --------------------------------------------------------------------------- #
# Sincronización diaria (RF-SYNC-01, RNF-05) — `disparar_sync_diaria` corre cada hora
# (beat) y decide si ya es momento de encolar `sync_diaria_empresa` por empresa activa;
# nunca un cron a una hora exacta, así una caída de `beat` se autorecupera solo (basta con
# que vuelva a correr en CUALQUIER hora >= la configurada, el mismo día).
# --------------------------------------------------------------------------- #

# emitido/recibido × CFDI/Metadata (doc 01 §1.3) — las 4 combinaciones que cubre RF-DESC-01.
_COMBINACIONES_SYNC: tuple[tuple[TipoJob, SolicitudTipo], ...] = (
    (TipoJob.EMITIDO, SolicitudTipo.CFDI),
    (TipoJob.EMITIDO, SolicitudTipo.METADATA),
    (TipoJob.RECIBIDO, SolicitudTipo.CFDI),
    (TipoJob.RECIBIDO, SolicitudTipo.METADATA),
)


async def _sync_diaria_empresa_async(empresa_id: int) -> dict[str, Any]:
    ayer = date.today() - timedelta(days=1)
    job_ids: list[int] = []
    evento_generado: str | None = None
    async with SessionLocal() as db:
        empresa = await empresas_repo.por_id(db, empresa_id)
        if empresa is None or not empresa.activo:
            return {"jobs_creados": 0, "evento": None}

        for tipo, solicitud in _COMBINACIONES_SYNC:
            ultima = await jobs_repo.ultima_ventana_sincronizada(db, empresa_id, tipo, solicitud)
            # `desde = ultima` (NO `ultima + 1 día`): confirmado en producción (2026-07-28) que
            # el SAT rechaza (CodEstatus=301, "fecha inicial >= fecha final") cualquier solicitud
            # cuya `fecha_inicial`/`fecha_final` caigan en el MISMO día calendario — y con una
            # sync que avanza exactamente un día por corrida, `ultima + 1 día` == `ayer` TODOS
            # los días en régimen estable, no solo la primera vez. Se vuelve a incluir el último
            # día ya sincronizado (1 día de traslape) para garantizar siempre ≥ 2 días distintos;
            # `resguardo.indexar_job` ya es idempotente por `UNIQUE(empresa_id, uuid)`, así que
            # reprocesar ese día no duplica nada, solo re-consulta un poco de más al SAT.
            # Primera vez (`ultima is None`): arranca 2 días atrás de "ayer" — sigue sin disparar
            # un backfill histórico automático, eso ya existe como acción manual consciente en la UI.
            desde = ultima if ultima is not None else ayer - timedelta(days=1)
            if desde >= ayer:
                continue  # ya sincronizado hasta ayer (o más) en esta combinación; nada que hacer
            try:
                jobs = await crear_descarga(db, empresa, tipo=tipo, solicitud=solicitud, desde=desde, hasta=ayer, origen=OrigenJob.SYNC)
                job_ids.extend(j.job_id for j in jobs)
            except (EfirmaAusenteError, FielVencidaError) as exc:
                # Empresarial, no por combinación: no tiene caso seguir probando las otras 3.
                evento = await eventos_repo.crear(db, empresa_id, TipoEvento.EFIRMA_POR_VENCER, {"mensaje": str(exc)})
                notificaciones_service.encolar_si_nuevo(evento)
                evento_generado = "efirma_por_vencer" if evento is not None else None
                break
            except (EmpresaInactivaError, RangoInvalidoError) as exc:
                logger.warning("sync_diaria_empresa: %s (empresa %s, %s/%s).", exc, empresa_id, tipo.value, solicitud.value)
                continue
        await db.commit()

    for job_id in job_ids:
        ejecutar_job.delay(job_id)
    return {"jobs_creados": len(job_ids), "evento": evento_generado}


@celery_app.task(name="app.worker.tasks.sync_diaria_empresa")  # type: ignore[untyped-decorator]
def sync_diaria_empresa(empresa_id: int) -> dict[str, Any]:
    return asyncio.run(_sync_diaria_empresa_async(empresa_id))


async def _disparar_sync_diaria_async() -> dict[str, Any]:
    hoy = date.today()
    async with SessionLocal() as db:
        if not bool(await config_repo.valor(db, "auto_sync_diaria", True)):
            return {"disparado": False, "razon": "desactivada"}
        hora_sync = str(await config_repo.valor(db, "hora_sync", "02:00"))
        try:
            hora_objetivo = int(hora_sync.split(":")[0])
        except ValueError:
            hora_objetivo = 2

        # `< ` (no `!=`): si el beat estuvo caído durante la hora configurada, la siguiente
        # vez que despierte (cualquier hora posterior, mismo día) igual dispara (RNF-05).
        if datetime.now().hour < hora_objetivo:
            return {"disparado": False, "razon": "fuera_de_hora"}
        if await eventos_repo.existe_tipo_hoy_global(db, TipoEvento.RESUMEN_SYNC, hoy):
            return {"disparado": False, "razon": "ya_corrio_hoy"}

        empresas = await empresas_repo.listar_activas(db)
        if not empresas:
            return {"disparado": False, "razon": "sin_empresas_activas"}

        # El evento "resumen_sync" vive bajo la primera empresa activa (el DDL exige un
        # empresa_id en `eventos`, doc 03 §2.2) — es solo el ancla de idempotencia diaria del
        # disparador; el conteo real de jobs por empresa se ve en `jobs.origen=sync`.
        await eventos_repo.crear(db, empresas[0].empresa_id, TipoEvento.RESUMEN_SYNC, {"fecha": hoy.isoformat(), "empresas": len(empresas)})
        await db.commit()

    for empresa in empresas:
        sync_diaria_empresa.delay(empresa.empresa_id)
    return {"disparado": True, "empresas": len(empresas)}


@celery_app.task(name="app.worker.tasks.disparar_sync_diaria")  # type: ignore[untyped-decorator]
def disparar_sync_diaria() -> dict[str, Any]:
    return asyncio.run(_disparar_sync_diaria_async())


# --------------------------------------------------------------------------- #
# EFOS 69-B (RF-RIES-02) — tarea diaria (beat): descarga el CSV público, guarda una
# versión nueva solo si cambió respecto a la última, y siempre re-cruza (aunque la lista
# no haya cambiado puede haber comprobantes nuevos indexados desde el último cruce).
# --------------------------------------------------------------------------- #


async def _actualizar_lista_69b_async() -> dict[str, Any]:
    async with SessionLocal() as db:
        if not bool(await config_repo.valor(db, "auto_lista_69b", True)):
            return {"actualizado": False, "razon": "desactivada"}
    filas = descargar_lista_69b()
    hoy = date.today()
    async with SessionLocal() as db:
        anterior = await lista_69b_repo.version_mas_reciente(db)
        cambio = True
        if anterior is not None:
            filas_anteriores = await lista_69b_repo.rfcs_de_version(db, anterior)
            cambio = {(f.rfc, f.situacion.value) for f in filas_anteriores} != set(filas)

        version_usada = anterior
        if cambio or anterior is None:
            await lista_69b_repo.crear_version(db, hoy, filas)
            version_usada = hoy
        await db.commit()

        creados = await riesgo_service.cruzar_efos(db, version_usada) if version_usada is not None else 0
        await db.commit()
    return {"version": version_usada.isoformat() if version_usada else None, "registros": len(filas), "cambio": cambio, "eventos_creados": creados}


@celery_app.task(name="app.worker.tasks.actualizar_lista_69b")  # type: ignore[untyped-decorator]
def actualizar_lista_69b() -> dict[str, Any]:
    return asyncio.run(_actualizar_lista_69b_async())


# --------------------------------------------------------------------------- #
# Re-verificación programada de vigencia (RF-VAL-03) — tarea diaria (beat): reutiliza
# `_validar_lote_async` (ya usada por el endpoint manual de Sprint 3), sin duplicar lógica.
# --------------------------------------------------------------------------- #


async def _re_verificar_vigentes_async() -> dict[str, Any]:
    async with SessionLocal() as db:
        if not bool(await config_repo.valor(db, "auto_re_verificar", True)):
            return {"revalidados": 0, "razon": "desactivada"}
        dias = int(await config_repo.valor(db, "dias_re_verificacion", 30))
        empresas = await empresas_repo.listar_activas(db)
    limite = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=dias)

    total_revalidados = 0
    for empresa in empresas:
        async with SessionLocal() as db:
            ids = await comprobantes_repo.ids_vigentes_por_revalidar(db, empresa.empresa_id, limite)
        if not ids:
            continue
        resultado = await _validar_lote_async(empresa.empresa_id, ids)
        total_revalidados += resultado["total"]
    return {"empresas": len(empresas), "comprobantes_revalidados": total_revalidados}


@celery_app.task(name="app.worker.tasks.re_verificar_vigentes")  # type: ignore[untyped-decorator]
def re_verificar_vigentes() -> dict[str, Any]:
    return asyncio.run(_re_verificar_vigentes_async())


# --------------------------------------------------------------------------- #
# Envío de notificaciones (RF-NOT-01) — se encola desde `app.services.notificaciones.
# encolar_si_nuevo` cada vez que `eventos_repo.crear` produce un evento NUEVO (nunca en un
# no-op de idempotencia). Un fallo SMTP reintenta la tarea completa (doc 06 §2.6); antes de
# reenviar a cada destino se comprueba `ya_enviado` para no duplicar un correo que ya había
# salido bien en un intento anterior.
# --------------------------------------------------------------------------- #


async def _enviar_notificacion_async(evento_id: int) -> dict[str, Any]:
    enviados = 0
    fallo_retryable = False
    async with SessionLocal() as db:
        evento = await db.get(Evento, evento_id)
        if evento is None:
            logger.warning("enviar_notificacion: el evento %s ya no existe.", evento_id)
            return {"enviados": 0, "fallo_retryable": False}

        destinos = await notificaciones_repo.destinos_suscritos(db, evento.empresa_id, evento.tipo)
        if not destinos:
            return {"enviados": 0, "fallo_retryable": False}

        # Credenciales resueltas UNA vez por invocación (no una vez por destinatario) —
        # `resolver_credenciales` descifra la contraseña con la bóveda, no vale la pena
        # repetirlo N veces para N destinos del mismo evento.
        try:
            credenciales = await notificaciones_service.resolver_credenciales(db)
        except notificaciones_service.SmtpNoConfiguradoError as exc:
            for destino in destinos:
                if not await notificaciones_repo.ya_enviado(db, evento_id, destino.correo):
                    await notificaciones_repo.registrar_envio(db, evento_id, destino.correo, ResultadoNotificacion.FALLIDO, str(exc))
            await db.commit()
            return {"enviados": 0, "fallo_retryable": False}

        for destino in destinos:
            if await notificaciones_repo.ya_enviado(db, evento_id, destino.correo):
                continue
            try:
                notificaciones_service.enviar_correo(destino, evento, credenciales)
            except Exception as exc:  # noqa: BLE001 — smtplib.SMTPException y similares, sí son transitorios
                await notificaciones_repo.registrar_envio(db, evento_id, destino.correo, ResultadoNotificacion.FALLIDO, str(exc)[:500])
                fallo_retryable = True
                continue
            await notificaciones_repo.registrar_envio(db, evento_id, destino.correo, ResultadoNotificacion.ENVIADO)
            enviados += 1
        await db.commit()
    return {"enviados": enviados, "fallo_retryable": fallo_retryable}


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="app.worker.tasks.enviar_notificacion",
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=600,
)
def enviar_notificacion(self, evento_id: int) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    resultado = asyncio.run(_enviar_notificacion_async(evento_id))
    if resultado["fallo_retryable"]:
        raise self.retry(countdown=60)
    return resultado
