"""GET /v1/bitacora — doc 05 §8, solo admin, solo lectura (RF-BIT-01)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.api.v1.schemas import BitacoraOut, BitacoraPageOut
from app.models.bitacora import Bitacora
from app.models.usuario import Usuario

router = APIRouter(prefix="/bitacora", tags=["bitacora"])


@router.get("", response_model=BitacoraPageOut)
async def listar_bitacora(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    admin: Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BitacoraPageOut:
    total = await db.scalar(select(func.count()).select_from(Bitacora)) or 0
    filas = await db.scalars(
        select(Bitacora).order_by(Bitacora.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    data = [
        BitacoraOut(
            bitacora_id=b.bitacora_id, actor=b.actor, accion=b.accion, entidad=b.entidad,
            detalle=b.detalle, created_at=b.created_at.isoformat(),
        )
        for b in filas
    ]
    return BitacoraPageOut(data=data, page=page, per_page=per_page, total=total)
