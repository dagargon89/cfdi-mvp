"""Repositorio de `comprobantes` (RF-LIST-01) — filtros sobre los índices del DDL (doc 03
§2.2: `idx_comp_emp_fecha`, `idx_comp_emp_estatus`, `idx_comp_emisor`), sin N+1 (doc 06 §3)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comprobante import Comprobante
from app.models.enums import EstatusCfdi


async def listar(
    db: AsyncSession,
    empresa_id: int,
    *,
    desde: date | None = None,
    hasta: date | None = None,
    tipo_comprobante: str | None = None,
    estatus: EstatusCfdi | None = None,
    rfc_contraparte: str | None = None,
    direccion: str | None = None,
    rfc_empresa: str | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[Comprobante], int]:
    filtros = [Comprobante.empresa_id == empresa_id]
    if desde is not None:
        filtros.append(Comprobante.fecha_emision >= desde)
    if hasta is not None:
        filtros.append(Comprobante.fecha_emision <= hasta)
    if tipo_comprobante is not None:
        filtros.append(Comprobante.tipo_comprobante == tipo_comprobante)
    if estatus is not None:
        filtros.append(Comprobante.estatus == estatus)
    if rfc_contraparte is not None:
        filtros.append(or_(Comprobante.rfc_emisor == rfc_contraparte, Comprobante.rfc_receptor == rfc_contraparte))
    # "emitido"/"recibido" es relativo al RFC de la propia empresa (no de la contraparte) —
    # requiere `rfc_empresa` (el llamador lo resuelve, este repo no conoce `empresas`).
    if direccion == "emitido" and rfc_empresa:
        filtros.append(Comprobante.rfc_emisor == rfc_empresa)
    elif direccion == "recibido" and rfc_empresa:
        filtros.append(Comprobante.rfc_receptor == rfc_empresa)
    if q:
        patron = f"%{q}%"
        filtros.append(
            or_(
                Comprobante.uuid.ilike(patron),
                Comprobante.rfc_emisor.ilike(patron),
                Comprobante.razon_social_emisor.ilike(patron),
                Comprobante.folio.ilike(patron),
            )
        )

    total = await db.scalar(select(func.count()).select_from(Comprobante).where(*filtros)) or 0
    result = await db.scalars(
        select(Comprobante)
        .where(*filtros)
        .order_by(Comprobante.fecha_emision.desc(), Comprobante.comprobante_id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(result.all()), total


async def por_id(db: AsyncSession, empresa_id: int, comprobante_id: int) -> Comprobante | None:
    row: Comprobante | None = await db.scalar(
        select(Comprobante).where(Comprobante.empresa_id == empresa_id, Comprobante.comprobante_id == comprobante_id)
    )
    return row


async def por_ids(db: AsyncSession, empresa_id: int, comprobante_ids: Sequence[int]) -> list[Comprobante]:
    if not comprobante_ids:
        return []
    result = await db.scalars(
        select(Comprobante).where(Comprobante.empresa_id == empresa_id, Comprobante.comprobante_id.in_(comprobante_ids))
    )
    return list(result.all())


async def ids_no_verificados(db: AsyncSession, empresa_id: int) -> list[int]:
    result = await db.scalars(
        select(Comprobante.comprobante_id).where(Comprobante.empresa_id == empresa_id, Comprobante.estatus == EstatusCfdi.NO_VERIFICADO)
    )
    return list(result.all())


async def ids_todos(db: AsyncSession, empresa_id: int) -> list[int]:
    result = await db.scalars(select(Comprobante.comprobante_id).where(Comprobante.empresa_id == empresa_id))
    return list(result.all())


async def ids_por_uuids(db: AsyncSession, empresa_id: int, uuids: Sequence[str]) -> list[int]:
    if not uuids:
        return []
    result = await db.scalars(
        select(Comprobante.comprobante_id).where(Comprobante.empresa_id == empresa_id, Comprobante.uuid.in_(uuids))
    )
    return list(result.all())
