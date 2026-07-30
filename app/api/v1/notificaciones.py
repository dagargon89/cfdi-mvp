"""GET/PUT /v1/empresas/{empresa_id}/notificaciones — destinos de correo (RF-NOT-01)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_empresa
from app.api.v1.schemas import NotificacionDestinoOut, NotificacionesGuardarIn, NotificacionesOut
from app.models.enums import RolEmpresa
from app.repositories import notificaciones as notificaciones_repo
from app.services import bitacora as bitacora_service

router = APIRouter(prefix="/empresas/{empresa_id}/notificaciones", tags=["notificaciones"])


@router.get("", response_model=NotificacionesOut)
async def obtener_notificaciones_endpoint(
    empresa_id: int,
    # Gestionar destinos es tarea de operador/admin; el rol de solo consulta no ve esta sección.
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> NotificacionesOut:
    destinos = await notificaciones_repo.listar_destinos(db, empresa_id)
    return NotificacionesOut(destinos=[NotificacionDestinoOut(correo=d.correo, eventos=sorted(d.eventos_suscritos)) for d in destinos])


@router.put("", response_model=None, status_code=204)
async def guardar_notificaciones_endpoint(
    empresa_id: int,
    body: NotificacionesGuardarIn,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> None:
    destinos = [(d.correo, [e.value for e in d.eventos]) for d in body.destinos]
    await notificaciones_repo.reemplazar_destinos(db, empresa_id, destinos)
    await bitacora_service.registrar(
        db, actor=ctx.usuario.correo, accion="guardar_notificaciones", entidad=f"empresa:{empresa_id}", detalle={"destinos": len(destinos)}
    )
    await db.commit()
