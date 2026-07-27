from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RolEmpresa
from app.models.usuario_empresa import UsuarioEmpresa


async def get(db: AsyncSession, usuario_id: int, empresa_id: int) -> UsuarioEmpresa | None:
    result: UsuarioEmpresa | None = await db.scalar(
        select(UsuarioEmpresa).where(UsuarioEmpresa.usuario_id == usuario_id, UsuarioEmpresa.empresa_id == empresa_id)
    )
    return result


async def reemplazar(db: AsyncSession, usuario_id: int, permisos: list[tuple[int, RolEmpresa]]) -> None:
    """PUT semántico (doc 05 §2): reemplaza el conjunto completo de permisos del usuario."""
    await db.execute(delete(UsuarioEmpresa).where(UsuarioEmpresa.usuario_id == usuario_id))
    for empresa_id, rol in permisos:
        db.add(UsuarioEmpresa(usuario_id=usuario_id, empresa_id=empresa_id, rol=rol))
    await db.flush()
