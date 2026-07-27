from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Bitacora(Base):
    """Append-only (RF-BIT-01). El usuario MySQL de la app tiene solo INSERT+SELECT sobre
    esta tabla — el grant restrictivo vive en el script de inicialización de MySQL, no aquí."""

    __tablename__ = "bitacora"
    __table_args__ = (
        Index("idx_bit_entidad", "entidad"),
        Index("idx_bit_fecha", "created_at"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    bitacora_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(190), nullable=False)
    accion: Mapped[str] = mapped_column(String(60), nullable=False)
    entidad: Mapped[str] = mapped_column(String(120), nullable=False)
    detalle: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
