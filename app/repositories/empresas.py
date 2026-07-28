from __future__ import annotations

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comprobante import Comprobante
from app.models.efirma import Efirma
from app.models.empresa import Empresa
from app.models.enums import RolGlobal
from app.models.job import Job
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


async def tiene_historial(db: AsyncSession, empresa_id: int) -> bool:
    """True si la empresa ya tiene e.firma, jobs o comprobantes (RF-EMP-02, doc 04 §4.4) —
    en ese caso el borrado real se rechaza; solo queda la baja lógica (`actualizar_activo`)."""
    query = select(
        or_(
            exists(select(Efirma.efirma_id).where(Efirma.empresa_id == empresa_id)),
            exists(select(Job.job_id).where(Job.empresa_id == empresa_id)),
            exists(select(Comprobante.comprobante_id).where(Comprobante.empresa_id == empresa_id)),
        )
    )
    result: bool | None = await db.scalar(query)
    return bool(result)


async def eliminar(db: AsyncSession, empresa: Empresa) -> None:
    """Solo llamar tras confirmar `not tiene_historial(...)` — usuario_empresa/eventos/
    notificacion_destinos caen en cascada (FK ON DELETE CASCADE, doc 03 §2.2)."""
    await db.delete(empresa)
    await db.flush()
