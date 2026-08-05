"""POST /v1/empresas/{id}/informes/normalizar y el catálogo/generación de informes
(spec §7.2). En esta tarea solo el reproceso del ETL; los informes llegan en la tarea 13."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_empresa
from app.api.v1.schemas import NormalizarIn, TareaCrearOut
from app.models.enums import RolEmpresa
from app.services import bitacora as bitacora_service
from app.worker.tasks import normalizar_comprobantes

router = APIRouter(prefix="/empresas/{empresa_id}/informes", tags=["informes"])


@router.post("/normalizar", status_code=status.HTTP_202_ACCEPTED, response_model=TareaCrearOut)
async def normalizar_endpoint(
    empresa_id: int,
    body: NormalizarIn,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> TareaCrearOut:
    """Reprocesa los XML ya resguardados hacia la capa normalizada. Pide OPERADOR: es una
    escritura masiva, aunque idempotente."""
    await bitacora_service.registrar(
        db, actor=ctx.usuario.correo, accion="normalizar_comprobantes", entidad=f"empresa:{empresa_id}", detalle={"alcance": body.alcance}
    )
    await db.commit()

    tarea = normalizar_comprobantes.delay(empresa_id, body.alcance)
    return TareaCrearOut(tarea_id=tarea.id)
