from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import RolGlobal
from app.models.usuario import Usuario
from app.models.usuario_empresa import UsuarioEmpresa


async def por_firebase_uid(db: AsyncSession, uid: str) -> Usuario | None:
    result: Usuario | None = await db.scalar(select(Usuario).where(Usuario.firebase_uid == uid))
    return result


async def por_correo(db: AsyncSession, correo: str) -> Usuario | None:
    result: Usuario | None = await db.scalar(select(Usuario).where(Usuario.correo == correo))
    return result


async def por_id(db: AsyncSession, usuario_id: int) -> Usuario | None:
    return await db.get(Usuario, usuario_id)


async def crear(db: AsyncSession, *, firebase_uid: str, correo: str, nombre: str, rol_global: RolGlobal, aprobado: bool = False) -> Usuario:
    usuario = Usuario(firebase_uid=firebase_uid, correo=correo, nombre=nombre, rol_global=rol_global, activo=True, aprobado=aprobado)
    db.add(usuario)
    await db.flush()
    return usuario


async def actualizar(db: AsyncSession, usuario: Usuario, *, activo: bool | None = None, rol_global: RolGlobal | None = None, aprobado: bool | None = None) -> Usuario:
    if activo is not None:
        usuario.activo = activo
    if rol_global is not None:
        usuario.rol_global = rol_global
    if aprobado is not None:
        usuario.aprobado = aprobado
    await db.flush()
    return usuario


async def eliminar(db: AsyncSession, usuario: Usuario) -> None:
    await db.delete(usuario)
    await db.flush()


async def contar(db: AsyncSession) -> int:
    total = await db.scalar(select(func.count()).select_from(Usuario))
    return int(total or 0)


async def contar_admins_activos(db: AsyncSession) -> int:
    total = await db.scalar(
        select(func.count()).select_from(Usuario).where(Usuario.rol_global == RolGlobal.ADMIN, Usuario.activo.is_(True), Usuario.aprobado.is_(True))
    )
    return int(total or 0)


async def correos_admins(db: AsyncSession) -> list[str]:
    filas = await db.scalars(
        select(Usuario.correo).where(Usuario.rol_global == RolGlobal.ADMIN, Usuario.activo.is_(True), Usuario.aprobado.is_(True))
    )
    return [c for c in filas.all() if c]


async def listar_con_permisos(db: AsyncSession) -> list[Usuario]:
    result = await db.scalars(
        select(Usuario).options(selectinload(Usuario.permisos).selectinload(UsuarioEmpresa.empresa)).order_by(Usuario.usuario_id)
    )
    return list(result.all())
