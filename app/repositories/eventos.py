"""Repositorio de `eventos` (RF-RIES-01/02, RF-SYNC-01, RF-NOT-01) — `crear` es idempotente
de verdad vía la `UNIQUE(empresa_id, tipo, hash_detalle)` del DDL: dos llamadas con el mismo
`detalle` para la misma empresa/tipo nunca duplican el evento, sin necesidad de una
verificación previa (que dejaría una condición de carrera entre dos workers concurrentes)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TipoEvento
from app.models.evento import Evento


def _hash_detalle(detalle: dict[str, Any]) -> str:
    crudo = json.dumps(detalle, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(crudo).hexdigest()


async def crear(db: AsyncSession, empresa_id: int, tipo: TipoEvento, detalle: dict[str, Any]) -> Evento | None:
    """Crea el evento y hace `flush` (no `commit` — el caller decide la transacción).

    Devuelve `None` si un evento idéntico (misma empresa/tipo/detalle) ya existía — el
    caller lo usa para no encolar una notificación duplicada (doc 06 §2.6). El intento se
    hace en un SAVEPOINT (`begin_nested`), no un `rollback()` de la sesión completa: esto
    puede llamarse en medio de una unidad de trabajo más grande (p. ej. `cruzar_efos`
    creando varios eventos, o `sync_diaria_empresa` creando jobs + un evento) y un rollback
    de sesión completa se llevaría entre las patas cualquier cambio previo aún sin commit.
    """
    evento = Evento(empresa_id=empresa_id, tipo=tipo, detalle=detalle, hash_detalle=_hash_detalle(detalle))
    try:
        async with db.begin_nested():
            db.add(evento)
            await db.flush()
    except IntegrityError:
        return None
    return evento


async def listar(
    db: AsyncSession,
    empresa_id: int,
    *,
    tipo: TipoEvento | None = None,
    desde: date | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[Evento], int]:
    filtros = [Evento.empresa_id == empresa_id]
    if tipo is not None:
        filtros.append(Evento.tipo == tipo)
    if desde is not None:
        filtros.append(Evento.created_at >= datetime.combine(desde, datetime.min.time()))

    total = await db.scalar(select(func.count()).select_from(Evento).where(*filtros)) or 0
    result = await db.scalars(
        select(Evento).where(*filtros).order_by(Evento.evento_id.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    return list(result.all()), total


async def existe_tipo_hoy_global(db: AsyncSession, tipo: TipoEvento, hoy: date) -> bool:
    """Sin filtro de empresa — usado por `disparar_sync_diaria` (RNF-05) para saber si el
    `resumen_sync` de hoy ya se generó (el evento vive bajo una sola empresa "ancla", pero la
    pregunta de "¿ya corrió el disparador hoy?" es de todo el sistema, no de una empresa en
    particular). Se puede preguntar cuantas veces haga falta en el día — misma respuesta —
    así un `beat` que se cayó a media hora y vuelve más tarde no dispara dos veces (RNF-05)."""
    fila = await db.scalar(
        select(Evento.evento_id).where(Evento.tipo == tipo, Evento.created_at >= datetime.combine(hoy, datetime.min.time()))
    )
    return fila is not None
