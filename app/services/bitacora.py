"""Bitácora transaccional (RF-BIT-01). No hace commit — se inserta dentro de la misma
transacción que la operación sensible; si algo falla después, todo se revierte junto."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bitacora import Bitacora


async def registrar(db: AsyncSession, *, actor: str, accion: str, entidad: str, detalle: dict[str, Any] | None = None) -> None:
    db.add(Bitacora(actor=actor, accion=accion, entidad=entidad, detalle=detalle))
    await db.flush()
