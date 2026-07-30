"""Lectura de `configuracion` (RF-CFG-01) — claves versionadas por ejercicio fiscal.

Sprint 2 solo lee el ejercicio "vigente" (sembrado por la migración de datos
`alembic/versions/..._seed_configuracion.py`); versionar por ejercicio fiscal real
queda para cuando exista una UI de administración de config (doc 07, sprint futuro).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion import Configuracion

EJERCICIO_VIGENTE = "vigente"


async def valor(db: AsyncSession, clave: str, default: Any) -> Any:
    fila = await db.scalar(
        select(Configuracion).where(Configuracion.clave == clave, Configuracion.ejercicio_fiscal == EJERCICIO_VIGENTE)
    )
    return fila.valor if fila is not None else default


async def establecer(db: AsyncSession, clave: str, valor_nuevo: Any) -> None:
    """Upsert de una clave de configuración del ejercicio vigente (RF-CFG-01)."""
    fila = await db.scalar(
        select(Configuracion).where(Configuracion.clave == clave, Configuracion.ejercicio_fiscal == EJERCICIO_VIGENTE)
    )
    if fila is None:
        db.add(Configuracion(clave=clave, ejercicio_fiscal=EJERCICIO_VIGENTE, valor=valor_nuevo))
    else:
        fila.valor = valor_nuevo
    await db.flush()
