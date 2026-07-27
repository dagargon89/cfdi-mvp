from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Configuracion(Base):
    """Reglas del SAT y parámetros operativos versionados por ejercicio fiscal (RF-CFG-01).

    Claves esperadas: max_meses_ventana, max_anios_antiguedad, polling_espera_seg,
    max_reintentos, umbral_vigencia_dias, hora_sync.
    """

    __tablename__ = "configuracion"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    clave: Mapped[str] = mapped_column(String(80), primary_key=True)
    ejercicio_fiscal: Mapped[str] = mapped_column(String(9), primary_key=True, default="vigente")
    valor: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
    )
