"""Helpers de datos de prueba — inserción directa, sin pasar por la API."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.empresa import Empresa
from app.models.enums import RolEmpresa, RolGlobal
from app.models.usuario import Usuario
from app.models.usuario_empresa import UsuarioEmpresa


async def crear_usuario(db: AsyncSession, *, uid: str, correo: str, rol_global: RolGlobal = RolGlobal.CONSULTA, activo: bool = True) -> Usuario:
    usuario = Usuario(firebase_uid=uid, correo=correo, nombre=correo.split("@")[0], rol_global=rol_global, activo=activo)
    db.add(usuario)
    await db.flush()
    await db.commit()
    return usuario


async def crear_empresa(db: AsyncSession, *, nombre: str = "Empresa Demo", rfc: str = "EKU9003173C9") -> Empresa:
    empresa = Empresa(nombre=nombre, rfc=rfc)
    db.add(empresa)
    await db.flush()
    await db.commit()
    return empresa


async def asignar_permiso(db: AsyncSession, usuario: Usuario, empresa: Empresa, rol: RolEmpresa) -> None:
    db.add(UsuarioEmpresa(usuario_id=usuario.usuario_id, empresa_id=empresa.empresa_id, rol=rol))
    await db.flush()
    await db.commit()
