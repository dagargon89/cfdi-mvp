from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.efirma import Efirma
from app.services.boveda import EfirmaCifrada


async def por_empresa(db: AsyncSession, empresa_id: int) -> Efirma | None:
    result: Efirma | None = await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa_id))
    return result


async def upsert(db: AsyncSession, empresa_id: int, cifrada: EfirmaCifrada) -> Efirma:
    """Alta o reemplazo (RF-BOV-01/04) — una e.firma vigente por empresa (UNIQUE empresa_id)."""
    existente = await por_empresa(db, empresa_id)
    if existente is not None:
        await db.delete(existente)
        await db.flush()
    nueva = Efirma(
        empresa_id=empresa_id,
        num_serie=cifrada.num_serie,
        not_before=cifrada.not_before,
        not_after=cifrada.not_after,
        cer_pem=cifrada.cer_pem,
        key_cifrada=cifrada.key_cifrada,
        password_cifrada=cifrada.password_cifrada,
        dek_envuelta=cifrada.dek_envuelta,
    )
    db.add(nueva)
    await db.flush()
    return nueva


async def eliminar(db: AsyncSession, empresa_id: int) -> None:
    await db.execute(delete(Efirma).where(Efirma.empresa_id == empresa_id))
