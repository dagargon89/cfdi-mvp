"""Repositorio de `configuracion_smtp` (RF-NOT-01) — una sola fila global. Solo CRUD; el
cifrado/descifrado de la contraseña de aplicación vive en `app/services/notificaciones.py`,
no aquí (mismo reparto de responsabilidades que `efirmas_repo`/`app/services/boveda.py`)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion_smtp import ConfiguracionSmtp


async def obtener(db: AsyncSession) -> ConfiguracionSmtp | None:
    result: ConfiguracionSmtp | None = await db.scalar(select(ConfiguracionSmtp).limit(1))
    return result


async def guardar(
    db: AsyncSession,
    *,
    host: str,
    port: int,
    usuario: str,
    remitente: str,
    tls: bool,
    password_cifrada: bytes,
    dek_envuelta: bytes,
) -> ConfiguracionSmtp:
    """Reemplaza la fila única (si existía) — misma semántica que `efirmas_repo.upsert`."""
    existente = await obtener(db)
    if existente is not None:
        await db.delete(existente)
        await db.flush()
    nueva = ConfiguracionSmtp(
        host=host, port=port, usuario=usuario, remitente=remitente, tls=tls, password_cifrada=password_cifrada, dek_envuelta=dek_envuelta
    )
    db.add(nueva)
    await db.flush()
    return nueva
