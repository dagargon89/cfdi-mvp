"""GET/POST/PATCH /v1/empresas — doc 05 §3."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin, usuario_actual
from app.api.v1.composers import empresa_resumen
from app.api.v1.schemas import EmpresaCrearIn, EmpresaPatchIn, EmpresaResumenOut
from app.models.usuario import Usuario
from app.repositories import empresas as empresas_repo
from app.services import bitacora

router = APIRouter(prefix="/empresas", tags=["empresas"])


@router.get("", response_model=list[EmpresaResumenOut])
async def listar_empresas(usuario: Usuario = Depends(usuario_actual), db: AsyncSession = Depends(get_db)) -> list[EmpresaResumenOut]:
    empresas = await empresas_repo.listar_para_usuario(db, usuario)
    return [await empresa_resumen(db, usuario, e) for e in empresas]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EmpresaResumenOut)
async def crear_empresa(
    body: EmpresaCrearIn, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> EmpresaResumenOut:
    rfc = body.rfc.strip().upper()
    if not (12 <= len(rfc) <= 13):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"codigo": "RFC_MALFORMADO", "mensaje": "El RFC debe tener 12 o 13 caracteres."})
    if await empresas_repo.por_rfc(db, rfc):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "RFC_DUPLICADO", "mensaje": "Ya existe una empresa con ese RFC."})
    empresa = await empresas_repo.crear(db, nombre=body.nombre, rfc=rfc)
    await bitacora.registrar(db, actor=admin.correo, accion="alta_empresa", entidad=f"empresa:{empresa.empresa_id}", detalle={"rfc": rfc})
    await db.commit()
    return await empresa_resumen(db, admin, empresa)


@router.patch("/{empresa_id}", response_model=EmpresaResumenOut)
async def actualizar_empresa(
    empresa_id: int, body: EmpresaPatchIn, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> EmpresaResumenOut:
    empresa = await empresas_repo.por_id(db, empresa_id)
    if empresa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    if body.activo is not None:
        await empresas_repo.actualizar_activo(db, empresa, body.activo)
        await bitacora.registrar(db, actor=admin.correo, accion="editar_empresa", entidad=f"empresa:{empresa_id}", detalle={"activo": body.activo})
    await db.commit()
    return await empresa_resumen(db, admin, empresa)
