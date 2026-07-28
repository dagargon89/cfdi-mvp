"""GET /v1/empresas/{empresa_id}/eventos (RF-RIES-01/02, RF-SYNC-01, RF-NOT-01) y
GET /v1/efos/estado (RF-RIES-02, lectura global sin empresa — cualquier usuario autenticado)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_empresa, usuario_actual
from app.api.v1.schemas import Efos69bEstadoOut, EventoOut, EventoPageOut
from app.models.enums import RolEmpresa, TipoEvento
from app.models.evento import Evento
from app.models.usuario import Usuario
from app.repositories import eventos as eventos_repo
from app.repositories import lista_69b as lista_69b_repo

router = APIRouter(tags=["eventos"])


def _evento_a_out(e: Evento) -> EventoOut:
    return EventoOut(evento_id=e.evento_id, tipo=e.tipo.value, detalle=e.detalle, created_at=e.created_at.isoformat())


@router.get("/empresas/{empresa_id}/eventos", response_model=EventoPageOut)
async def listar_eventos_endpoint(
    empresa_id: int,
    tipo: TipoEvento | None = None,
    desde: date | None = None,
    page: int = 1,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> EventoPageOut:
    eventos, total = await eventos_repo.listar(db, empresa_id, tipo=tipo, desde=desde, page=page)
    return EventoPageOut(data=[_evento_a_out(e) for e in eventos], page=page, per_page=50, total=total)


@router.get("/efos/estado", response_model=Efos69bEstadoOut)
async def efos_estado_endpoint(
    usuario: Usuario = Depends(usuario_actual),
    db: AsyncSession = Depends(get_db),
) -> Efos69bEstadoOut:
    version = await lista_69b_repo.version_mas_reciente(db)
    registros = await lista_69b_repo.total_de_version(db, version) if version is not None else 0
    return Efos69bEstadoOut(version_lista=version.isoformat() if version is not None else None, registros=registros)
