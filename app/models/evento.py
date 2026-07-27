from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import TipoEvento, enum_column


class Evento(Base):
    """Alerta de vigilancia (doc 03 §2.2). `hash_detalle` = SHA-256(canonical(detalle)),
    da idempotencia vía UNIQUE — evita notificar dos veces el mismo hallazgo (RF-RIES-01)."""

    __tablename__ = "eventos"
    __table_args__ = (
        UniqueConstraint("empresa_id", "tipo", "hash_detalle", name="uq_evento"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    evento_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="CASCADE"), nullable=False)
    tipo: Mapped[TipoEvento] = mapped_column(enum_column(TipoEvento), nullable=False)
    detalle: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    hash_detalle: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
