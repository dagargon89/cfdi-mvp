"""GET /v1/empresas/{id}/comprobantes[, /validar, /export, /descargar-zip, /{id}/pdf|detalle|paquete]
— doc 05 §6 (RF-LIST, RF-VAL, RF-RES-03/D2)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_empresa
from app.api.v1.composers import comprobante_a_out
from app.api.v1.schemas import AlcanceUuids, ComprobanteIdsIn, ComprobantePageOut, TareaCrearOut, ValidarLoteIn
from app.core.config import get_settings
from app.models.comprobante import Comprobante
from app.models.enums import EstatusCfdi, RolEmpresa
from app.repositories import comprobantes as comprobantes_repo
from app.repositories import empresas as empresas_repo
from app.services import bitacora as bitacora_service
from app.services import representaciones
from app.worker.tasks import descargar_zip_lote, exportar_excel, validar_lote

router = APIRouter(prefix="/empresas/{empresa_id}/comprobantes", tags=["comprobantes"])


def _leer_xml(comprobante: Comprobante) -> bytes:
    xml_bytes = representaciones.leer_xml_de_disco(get_settings().storage_root, comprobante)
    if xml_bytes is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    return xml_bytes


async def _comprobante_o_404(db: AsyncSession, empresa_id: int, comprobante_id: int) -> Comprobante:
    comprobante = await comprobantes_repo.por_id(db, empresa_id, comprobante_id)
    if comprobante is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    return comprobante


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
    per_page: int = 50,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> ComprobantePageOut:
    # `per_page` acotado a [1, 100000]: el frontend manda un valor grande para "Todos" (una sola página).
    per_page = max(1, min(per_page, 100_000))
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
        per_page=per_page,
    )
    return ComprobantePageOut(data=[comprobante_a_out(c) for c in filas], page=page, per_page=per_page, total=total)


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


@router.get("/{comprobante_id}/pdf")
async def descargar_pdf_endpoint(
    empresa_id: int,
    comprobante_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    comprobante = await _comprobante_o_404(db, empresa_id, comprobante_id)
    xml_bytes = _leer_xml(comprobante)
    pdf = representaciones.generar_pdf(xml_bytes)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{comprobante.uuid}.pdf"'})


@router.get("/{comprobante_id}/detalle")
async def descargar_detalle_endpoint(
    empresa_id: int,
    comprobante_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    comprobante = await _comprobante_o_404(db, empresa_id, comprobante_id)
    xml_bytes = _leer_xml(comprobante)
    detalle = representaciones.generar_detalle(xml_bytes, comprobante.estatus)
    return Response(detalle, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{comprobante.uuid}_detalle.pdf"'})


@router.get("/{comprobante_id}/paquete")
async def descargar_paquete_endpoint(
    empresa_id: int,
    comprobante_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    comprobante = await _comprobante_o_404(db, empresa_id, comprobante_id)
    xml_bytes = _leer_xml(comprobante)
    paquete = representaciones.generar_paquete_zip(comprobante, xml_bytes)
    return Response(paquete, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{comprobante.uuid}.zip"'})


@router.post("/descargar-zip", status_code=status.HTTP_202_ACCEPTED, response_model=TareaCrearOut)
async def descargar_zip_lote_endpoint(
    empresa_id: int,
    body: ComprobanteIdsIn,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> TareaCrearOut:
    # La tarea re-consulta con `comprobantes_repo.por_ids(db, empresa_id, ...)` — acotado a la
    # empresa igual que `validar_lote`; un id de otra empresa en el body simplemente se ignora.
    await bitacora_service.registrar(
        db, actor=ctx.usuario.correo, accion="descargar_zip_lote", entidad=f"empresa:{empresa_id}", detalle={"cantidad": len(body.comprobante_ids)}
    )
    await db.commit()

    tarea = descargar_zip_lote.delay(empresa_id, body.comprobante_ids)
    return TareaCrearOut(tarea_id=tarea.id)
