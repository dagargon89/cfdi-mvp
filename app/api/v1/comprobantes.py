"""GET /v1/empresas/{id}/comprobantes[, /validar, /export] — doc 05 §6 (RF-LIST, RF-VAL)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_empresa
from app.api.v1.composers import comprobante_a_out
from app.api.v1.schemas import AlcanceUuids, ComprobantePageOut, TareaCrearOut, ValidarLoteIn
from app.models.enums import EstatusCfdi, RolEmpresa
from app.repositories import comprobantes as comprobantes_repo
from app.repositories import empresas as empresas_repo
from app.services import bitacora as bitacora_service
from app.worker.tasks import exportar_excel, validar_lote

router = APIRouter(prefix="/empresas/{empresa_id}/comprobantes", tags=["comprobantes"])


@router.get("", response_model=ComprobantePageOut)
async def listar_comprobantes_endpoint(
    empresa_id: int,
    desde: date | None = None,
    hasta: date | None = None,
    tipo_comprobante: str | None = None,
    estatus: EstatusCfdi | None = None,
    rfc_contraparte: str | None = None,
    direccion: Literal["emitido", "recibido"] | None = None,
    q: str | None = None,
    page: int = 1,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> ComprobantePageOut:
    rfc_empresa = None
    if direccion is not None:
        empresa = await empresas_repo.por_id(db, empresa_id)
        rfc_empresa = empresa.rfc if empresa else None

    filas, total = await comprobantes_repo.listar(
        db,
        empresa_id,
        desde=desde,
        hasta=hasta,
        tipo_comprobante=tipo_comprobante,
        estatus=estatus,
        rfc_contraparte=rfc_contraparte,
        direccion=direccion,
        rfc_empresa=rfc_empresa,
        q=q,
        page=page,
    )
    return ComprobantePageOut(data=[comprobante_a_out(c) for c in filas], page=page, per_page=50, total=total)


@router.post("/validar", status_code=status.HTTP_202_ACCEPTED, response_model=TareaCrearOut)
async def validar_lote_endpoint(
    empresa_id: int,
    body: ValidarLoteIn,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> TareaCrearOut:
    if isinstance(body.alcance, AlcanceUuids):
        ids = await comprobantes_repo.ids_por_uuids(db, empresa_id, body.alcance.uuids)
    elif body.alcance == "todos":
        ids = await comprobantes_repo.ids_todos(db, empresa_id)
    else:
        ids = await comprobantes_repo.ids_no_verificados(db, empresa_id)

    await bitacora_service.registrar(db, actor=ctx.usuario.correo, accion="validar_lote", entidad=f"empresa:{empresa_id}", detalle={"cantidad": len(ids)})
    await db.commit()

    tarea = validar_lote.delay(empresa_id, ids)
    return TareaCrearOut(tarea_id=tarea.id)


@router.get("/export", status_code=status.HTTP_202_ACCEPTED, response_model=TareaCrearOut)
async def exportar_excel_endpoint(
    empresa_id: int,
    desde: date | None = None,
    hasta: date | None = None,
    tipo_comprobante: str | None = None,
    estatus: EstatusCfdi | None = None,
    rfc_contraparte: str | None = None,
    direccion: Literal["emitido", "recibido"] | None = None,
    q: str | None = None,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> TareaCrearOut:
    await bitacora_service.registrar(db, actor=ctx.usuario.correo, accion="exportar_excel", entidad=f"empresa:{empresa_id}", detalle=None)
    await db.commit()

    filtros = {
        "desde": desde.isoformat() if desde else None,
        "hasta": hasta.isoformat() if hasta else None,
        "tipo_comprobante": tipo_comprobante,
        "estatus": estatus.value if estatus else None,
        "rfc_contraparte": rfc_contraparte,
        "direccion": direccion,
        "q": q,
    }
    tarea = exportar_excel.delay(empresa_id, filtros)
    return TareaCrearOut(tarea_id=tarea.id)
