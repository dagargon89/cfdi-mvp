"""POST/GET/DELETE /v1/empresas/{empresa_id}/efirma — doc 05 §4, doc 04 §3.3 (bóveda)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_empresa
from app.api.v1.schemas import EfirmaAltaOut, EfirmaMetaOut
from app.models.enums import RolEmpresa
from app.repositories import efirmas as efirmas_repo
from app.repositories import empresas as empresas_repo
from app.sat_hub.errors import FielPasswordError, FielVencidaError
from app.services import boveda
from app.services import bitacora as bitacora_service
from app.services.fiel import RfcNoCoincideError

router = APIRouter(prefix="/empresas/{empresa_id}/efirma", tags=["boveda"])


def _dias_restantes(not_after: datetime) -> int:
    return (not_after - datetime.now(timezone.utc)).days


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EfirmaAltaOut)
async def subir_efirma(
    empresa_id: int,
    cer: UploadFile = File(...),
    key: UploadFile = File(...),
    password: str = Form(...),
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> EfirmaAltaOut:
    empresa = await empresas_repo.por_id(db, empresa_id)
    if empresa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")

    cer_bytes = await cer.read()
    key_bytes = await key.read()
    try:
        cifrada = boveda.preparar_efirma(cer_bytes, key_bytes, password, empresa.rfc)
    except FielPasswordError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "EFIRMA_NO_ABRE", "mensaje": str(exc)}) from exc
    except RfcNoCoincideError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "RFC_NO_COINCIDE", "mensaje": str(exc)}) from exc
    except FielVencidaError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "EFIRMA_VENCIDA", "mensaje": str(exc)}) from exc

    efirma = await efirmas_repo.upsert(db, empresa_id, cifrada)
    await bitacora_service.registrar(
        db, actor=ctx.usuario.correo, accion="alta_efirma", entidad=f"empresa:{empresa_id}", detalle={"num_serie": cifrada.num_serie}
    )
    await db.commit()

    return EfirmaAltaOut(
        num_serie=efirma.num_serie,
        not_before=efirma.not_before.isoformat(),
        not_after=efirma.not_after.isoformat(),
        dias_para_vencer=_dias_restantes(cifrada.not_after),
    )


@router.get("", response_model=EfirmaMetaOut | None)
async def obtener_efirma(
    empresa_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> EfirmaMetaOut | None:
    efirma = await efirmas_repo.por_empresa(db, empresa_id)
    if efirma is None:
        return None
    return EfirmaMetaOut(num_serie=efirma.num_serie, not_before=efirma.not_before.isoformat(), not_after=efirma.not_after.isoformat())


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_efirma(
    empresa_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> None:
    empresa = await empresas_repo.por_id(db, empresa_id)
    await efirmas_repo.eliminar(db, empresa_id)
    await bitacora_service.registrar(
        db, actor=ctx.usuario.correo, accion="baja_efirma", entidad=f"empresa:{empresa_id}", detalle={"rfc": empresa.rfc if empresa else None}
    )
    await db.commit()
