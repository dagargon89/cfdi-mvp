"""GET /v1/me — doc 05 §2. Único endpoint sin `empresa_id`; primera llamada de la SPA tras login."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, usuario_actual
from app.api.v1.composers import empresa_resumen
from app.api.v1.schemas import MeOut
from app.models.usuario import Usuario
from app.repositories import empresas as empresas_repo

router = APIRouter(tags=["sesion"])


@router.get("/me", response_model=MeOut)
async def me(usuario: Usuario = Depends(usuario_actual), db: AsyncSession = Depends(get_db)) -> MeOut:
    empresas = await empresas_repo.listar_para_usuario(db, usuario)
    resumenes = [await empresa_resumen(db, usuario, e) for e in empresas]
    return MeOut(
        usuario_id=usuario.usuario_id,
        correo=usuario.correo,
        nombre=usuario.nombre,
        rol_global=usuario.rol_global.value,
        empresas=resumenes,
    )
