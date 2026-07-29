"""POST /v1/empresas/{empresa_id}/descargas, GET .../jobs[/{job_id}],
POST .../jobs/{job_id}/reintentar — doc 05 §5, máquina de estados doc 01 §1.6."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_empresa
from app.api.v1.composers import job_a_out
from app.api.v1.schemas import DescargaCrearIn, DescargaCrearOut, JobOut, JobPageOut, MetadataPreviewOut
from app.core.config import get_settings
from app.models.enums import EstadoJob, OrigenJob, RolEmpresa
from app.repositories import empresas as empresas_repo
from app.repositories import jobs as jobs_repo
from app.sat_hub.errors import FielVencidaError, TransicionIlegalError
from app.services import bitacora as bitacora_service
from app.services import metadata_export
from app.services.descargas import EfirmaAusenteError, EmpresaInactivaError, RangoInvalidoError, crear_descarga
from app.services.metadata_export import MetadataNoAplicableError, MetadataNoDisponibleError
from app.worker.tasks import ejecutar_job

router = APIRouter(prefix="/empresas/{empresa_id}", tags=["descargas"])


@router.post("/descargas", status_code=status.HTTP_202_ACCEPTED, response_model=DescargaCrearOut)
async def crear_descarga_endpoint(
    empresa_id: int,
    body: DescargaCrearIn,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> DescargaCrearOut:
    empresa = await empresas_repo.por_id(db, empresa_id)
    if empresa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")

    try:
        jobs = await crear_descarga(db, empresa, tipo=body.tipo, solicitud=body.solicitud, desde=body.desde, hasta=body.hasta)
    except EfirmaAusenteError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "EFIRMA_AUSENTE", "mensaje": str(exc)}) from exc
    except FielVencidaError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "EFIRMA_VENCIDA", "mensaje": str(exc)}) from exc
    except EmpresaInactivaError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "EMPRESA_INACTIVA", "mensaje": str(exc)}) from exc
    except RangoInvalidoError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "RANGO_INVALIDO", "mensaje": str(exc)}) from exc

    job_ids = [j.job_id for j in jobs]
    await bitacora_service.registrar(
        db,
        actor=ctx.usuario.correo,
        accion="crear_descarga",
        entidad=f"empresa:{empresa_id}",
        detalle={"job_ids": job_ids, "tipo": body.tipo.value, "solicitud": body.solicitud.value},
    )
    await db.commit()

    # Encolar DESPUÉS del commit: el worker debe ver el job ya persistido cuando lo recoja.
    for job_id in job_ids:
        ejecutar_job.delay(job_id)

    return DescargaCrearOut(job_ids=job_ids, ventanas=len(job_ids))


@router.get("/jobs", response_model=JobPageOut)
async def listar_jobs_endpoint(
    empresa_id: int,
    estado: EstadoJob | None = None,
    origen: OrigenJob | None = None,
    page: int = 1,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> JobPageOut:
    jobs, total = await jobs_repo.listar(db, empresa_id, estado=estado, origen=origen, page=page)
    return JobPageOut(data=[job_a_out(j) for j in jobs], page=page, per_page=50, total=total)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def obtener_job_endpoint(
    empresa_id: int,
    job_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    job = await jobs_repo.por_id_de_empresa(db, empresa_id, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    return job_a_out(job)


@router.post("/jobs/{job_id}/reintentar", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def reintentar_job_endpoint(
    empresa_id: int,
    job_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> None:
    job = await jobs_repo.por_id_de_empresa(db, empresa_id, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    try:
        # `intentos` también se reinicia: una solicitud nueva (id_solicitud=None → se asigna
        # una nueva en el siguiente NUEVO→SOLICITADO) merece un presupuesto de sondeo fresco,
        # no seguir contando hacia el mismo `max_reintentos` de un intento anterior ya agotado.
        await jobs_repo.transicion(db, job, EstadoJob.NUEVO, id_solicitud=None, mensaje=None, intentos=0)  # T11
    except TransicionIlegalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "TRANSICION_ILEGAL", "mensaje": str(exc)}) from exc

    await bitacora_service.registrar(db, actor=ctx.usuario.correo, accion="reintento_job", entidad=f"job:{job_id}", detalle={"empresa_id": empresa_id})
    await db.commit()
    ejecutar_job.delay(job_id)


_METADATA_PER_PAGE = 100


def _job_o_404(job: object | None) -> None:
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")


def _mapear_error_metadata(exc: Exception) -> HTTPException:
    if isinstance(exc, MetadataNoAplicableError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "METADATA_NO_APLICABLE", "mensaje": str(exc)})
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "METADATA_NO_DISPONIBLE", "mensaje": str(exc)})


@router.get("/jobs/{job_id}/metadata", response_model=MetadataPreviewOut)
async def preview_metadata_endpoint(
    empresa_id: int,
    job_id: int,
    page: int = 1,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> MetadataPreviewOut:
    job = await jobs_repo.por_id_de_empresa(db, empresa_id, job_id)
    _job_o_404(job)
    try:
        headers, filas = metadata_export.parsear_metadata(get_settings().storage_root, job)
    except (MetadataNoAplicableError, MetadataNoDisponibleError) as exc:
        raise _mapear_error_metadata(exc) from exc

    inicio = max(page - 1, 0) * _METADATA_PER_PAGE
    return MetadataPreviewOut(
        headers=headers,
        filas=filas[inicio : inicio + _METADATA_PER_PAGE],
        total=len(filas),
        page=page,
        per_page=_METADATA_PER_PAGE,
    )


@router.get("/jobs/{job_id}/metadata.csv")
async def descargar_metadata_csv_endpoint(
    empresa_id: int,
    job_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    job = await jobs_repo.por_id_de_empresa(db, empresa_id, job_id)
    _job_o_404(job)
    try:
        csv_bytes = metadata_export.generar_csv_metadata(get_settings().storage_root, job)
    except (MetadataNoAplicableError, MetadataNoDisponibleError) as exc:
        raise _mapear_error_metadata(exc) from exc
    return Response(
        csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="metadata_job{job_id}.csv"'},
    )
