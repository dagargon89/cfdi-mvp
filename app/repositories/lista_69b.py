"""Repositorio de `lista_69b` (RF-RIES-02) — cada corrida de `actualizar_lista_69b` crea
una `version_lista` (la fecha del día en que se descargó) con una fila por RFC listado."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SituacionEfos
from app.models.lista_69b import Lista69b


async def crear_version(db: AsyncSession, fecha: date, filas: list[tuple[str, str]]) -> int:
    """Inserta una versión completa del padrón. No dedupe contra versiones anteriores —
    eso lo decide `cruzar_efos` comparando contra los comprobantes, no contra sí misma."""
    registros = [Lista69b(rfc=rfc, situacion=SituacionEfos(situacion), version_lista=fecha) for rfc, situacion in filas]
    db.add_all(registros)
    await db.flush()
    return len(registros)


async def version_mas_reciente(db: AsyncSession) -> date | None:
    resultado: date | None = await db.scalar(select(Lista69b.version_lista).order_by(Lista69b.version_lista.desc()).limit(1))
    return resultado


async def rfcs_de_version(db: AsyncSession, version_lista: date) -> list[Lista69b]:
    result = await db.scalars(select(Lista69b).where(Lista69b.version_lista == version_lista))
    return list(result.all())


async def total_de_version(db: AsyncSession, version_lista: date) -> int:
    result = await db.scalars(select(Lista69b.registro_id).where(Lista69b.version_lista == version_lista))
    return len(result.all())
