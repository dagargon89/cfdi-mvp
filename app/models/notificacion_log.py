from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ResultadoNotificacion, enum_column


class NotificacionLog(Base):
    __tablename__ = "notificacion_log"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    envio_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evento_id: Mapped[int] = mapped_column(ForeignKey("eventos.evento_id", ondelete="CASCADE"), nullable=False)
    correo: Mapped[str] = mapped_column(String(190), nullable=False)
    resultado: Mapped[ResultadoNotificacion] = mapped_column(enum_column(ResultadoNotificacion), nullable=False)
    mensaje: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
