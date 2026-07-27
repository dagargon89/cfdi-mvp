from datetime import date

from sqlalchemy import Date, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import SituacionEfos, enum_column


class Lista69b(Base):
    """Versión del padrón EFOS 69-B CFF (doc 03 §2.2, RF-RIES-02)."""

    __tablename__ = "lista_69b"
    __table_args__ = (
        UniqueConstraint("rfc", "version_lista", name="uq_rfc_version"),
        Index("idx_69b_rfc", "rfc"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    registro_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rfc: Mapped[str] = mapped_column(String(13), nullable=False)
    situacion: Mapped[SituacionEfos] = mapped_column(enum_column(SituacionEfos), nullable=False)
    fecha_publicacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    version_lista: Mapped[date] = mapped_column(Date, nullable=False)
