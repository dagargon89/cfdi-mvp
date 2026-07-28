from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, func, text
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConfiguracionSmtp(Base):
    """Correo saliente para notificaciones (RF-NOT-01) — una sola fila global, gestionada
    desde Configuración → Correo (nunca por variable de entorno). `password_cifrada`/
    `dek_envuelta` usan el mismo sobre AES-256-GCM que protege la e.firma en la bóveda
    (`app/services/boveda.py`) — nunca se guarda la contraseña de aplicación en claro."""

    __tablename__ = "configuracion_smtp"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    config_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(190), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    usuario: Mapped[str] = mapped_column(String(190), nullable=False)
    password_cifrada: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_envuelta: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    remitente: Mapped[str] = mapped_column(String(190), nullable=False)
    tls: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
    )
