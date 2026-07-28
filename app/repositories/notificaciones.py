"""Repositorio de `notificacion_destinos`/`notificacion_log` (RF-NOT-01)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ResultadoNotificacion, TipoEvento
from app.models.notificacion_destino import NotificacionDestino
from app.models.notificacion_log import NotificacionLog


async def listar_destinos(db: AsyncSession, empresa_id: int) -> list[NotificacionDestino]:
    result = await db.scalars(select(NotificacionDestino).where(NotificacionDestino.empresa_id == empresa_id))
    return list(result.all())


async def reemplazar_destinos(db: AsyncSession, empresa_id: int, destinos: list[tuple[str, list[str]]]) -> None:
    """Reemplaza-todo (misma semántica que `api.mock.ts`: `PUT` no hace merge)."""
    await db.execute(delete(NotificacionDestino).where(NotificacionDestino.empresa_id == empresa_id))
    for correo, eventos in destinos:
        db.add(NotificacionDestino(empresa_id=empresa_id, correo=correo, eventos_suscritos=set(eventos), activo=True))
    await db.flush()


async def destinos_suscritos(db: AsyncSession, empresa_id: int, tipo_evento: TipoEvento) -> list[NotificacionDestino]:
    result = await db.scalars(
        select(NotificacionDestino).where(NotificacionDestino.empresa_id == empresa_id, NotificacionDestino.activo.is_(True))
    )
    return [d for d in result.all() if tipo_evento.value in d.eventos_suscritos]


async def registrar_envio(db: AsyncSession, evento_id: int, correo: str, resultado: ResultadoNotificacion, mensaje: str | None = None) -> NotificacionLog:
    log = NotificacionLog(evento_id=evento_id, correo=correo, resultado=resultado, mensaje=mensaje)
    db.add(log)
    await db.flush()
    return log


async def ya_enviado(db: AsyncSession, evento_id: int, correo: str) -> bool:
    """Usado por `enviar_notificacion` antes de reintentar (doc 06 §2.6 "fallo SMTP →
    reintento") — sin esto, un reintento de la tarea completa reenviaría el correo también
    a los destinos que YA lo habían recibido con éxito en el intento anterior."""
    fila = await db.scalar(
        select(NotificacionLog.envio_id).where(
            NotificacionLog.evento_id == evento_id, NotificacionLog.correo == correo, NotificacionLog.resultado == ResultadoNotificacion.ENVIADO
        )
    )
    return fila is not None
