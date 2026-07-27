"""Composición repos → esquemas de salida, compartida entre /me y /empresas."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import EfirmaResumenOut, EmpresaResumenOut
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.repositories import efirmas as efirmas_repo
from app.repositories import empresas as empresas_repo


async def empresa_resumen(db: AsyncSession, usuario: Usuario, empresa: Empresa) -> EmpresaResumenOut:
    rol = await empresas_repo.rol_de_usuario(db, usuario, empresa.empresa_id)
    efirma = await efirmas_repo.por_empresa(db, empresa.empresa_id)
    return EmpresaResumenOut(
        empresa_id=empresa.empresa_id,
        nombre=empresa.nombre,
        rfc=empresa.rfc,
        rol=rol or "",
        activo=empresa.activo,
        efirma=EfirmaResumenOut(presente=True, not_after=efirma.not_after.isoformat()) if efirma else EfirmaResumenOut(presente=False, not_after=None),
    )
