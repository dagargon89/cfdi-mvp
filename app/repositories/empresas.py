from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.empresa import Empresa
from app.models.enums import RolGlobal
from app.models.usuario import Usuario
from app.models.usuario_empresa import UsuarioEmpresa


async def listar_para_usuario(db: AsyncSession, usuario: Usuario) -> list[Empresa]:
    if usuario.rol_global == RolGlobal.ADMIN:
        result = await db.scalars(select(Empresa).order_by(Empresa.empresa_id))
        return list(result.all())
    result = await db.scalars(
        select(Empresa).join(UsuarioEmpresa, UsuarioEmpresa.empresa_id == Empresa.empresa_id).where(
            UsuarioEmpresa.usuario_id == usuario.usuario_id
        ).order_by(Empresa.empresa_id)
    )
    return list(result.all())


async def rol_de_usuario(db: AsyncSession, usuario: Usuario, empresa_id: int) -> str | None:
    if usuario.rol_global == RolGlobal.ADMIN:
        return RolGlobal.ADMIN.value
    permiso = await db.scalar(
        select(UsuarioEmpresa).where(UsuarioEmpresa.usuario_id == usuario.usuario_id, UsuarioEmpresa.empresa_id == empresa_id)
    )
    return permiso.rol.value if permiso else None


async def por_id(db: AsyncSession, empresa_id: int) -> Empresa | None:
    return await db.get(Empresa, empresa_id)


async def por_rfc(db: AsyncSession, rfc: str) -> Empresa | None:
    result: Empresa | None = await db.scalar(select(Empresa).where(Empresa.rfc == rfc))
    return result


async def crear(db: AsyncSession, *, nombre: str, rfc: str) -> Empresa:
    empresa = Empresa(nombre=nombre, rfc=rfc.strip().upper())
    db.add(empresa)
    await db.flush()
    return empresa


async def actualizar_activo(db: AsyncSession, empresa: Empresa, activo: bool) -> Empresa:
    empresa.activo = activo
    await db.flush()
    return empresa
