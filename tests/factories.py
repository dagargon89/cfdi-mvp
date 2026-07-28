"""Helpers de datos de prueba — inserción directa, sin pasar por la API."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comprobante import Comprobante
from app.models.empresa import Empresa
from app.models.enums import EstatusCfdi, RolEmpresa, RolGlobal
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


async def crear_comprobante(
    db: AsyncSession,
    *,
    empresa_id: int,
    uuid: str,
    rfc_emisor: str = "EKU9003173C9",
    rfc_receptor: str = "XAXX010101000",
    razon_social_emisor: str = "EMISOR DE PRUEBA SA DE CV",
    folio: str | None = "1",
    total: float | None = 1160.0,
    fecha_emision: datetime | None = None,
    tipo_comprobante: str | None = "I",
    estatus: EstatusCfdi = EstatusCfdi.NO_VERIFICADO,
    xml_path: str | None = None,
) -> Comprobante:
    comprobante = Comprobante(
        empresa_id=empresa_id,
        uuid=uuid,
        folio=folio,
        rfc_emisor=rfc_emisor,
        rfc_receptor=rfc_receptor,
        razon_social_emisor=razon_social_emisor,
        total=total,
        fecha_emision=fecha_emision or datetime(2026, 1, 15, 12, 0),
        tipo_comprobante=tipo_comprobante,
        estatus=estatus,
        xml_path=xml_path,
    )
    db.add(comprobante)
    await db.flush()
    await db.commit()
    return comprobante
