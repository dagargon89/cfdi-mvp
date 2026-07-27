from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.mysql import SET, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_EVENTOS = ("cancelacion_tardia", "efos", "efirma_por_vencer", "error_descarga", "resumen_sync")


class NotificacionDestino(Base):
    __tablename__ = "notificacion_destinos"
    __table_args__ = (
        UniqueConstraint("empresa_id", "correo", name="uq_emp_correo"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    destino_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="CASCADE"), nullable=False)
    correo: Mapped[str] = mapped_column(String(190), nullable=False)
    eventos_suscritos: Mapped[str] = mapped_column(SET(*_EVENTOS), nullable=False)
    activo: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, default=1)
