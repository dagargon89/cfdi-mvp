from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.efirma import Efirma
    from app.models.usuario_empresa import UsuarioEmpresa


class Empresa(Base):
    __tablename__ = "empresas"
    __table_args__ = (
        CheckConstraint("CHAR_LENGTH(rfc) BETWEEN 12 AND 13", name="chk_rfc"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    empresa_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(190), nullable=False)
    rfc: Mapped[str] = mapped_column(String(13), unique=True, nullable=False)
    plantilla_nomenclatura: Mapped[str] = mapped_column(String(190), nullable=False, default="{razon_social}_{folio}_V")
    genera_pdf_comprobante: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, default=0)
    activo: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    permisos: Mapped[list["UsuarioEmpresa"]] = relationship(back_populates="empresa", cascade="all, delete-orphan")
    # ON DELETE RESTRICT en efirmas.empresa_id (doc 03) — sin cascade de borrado a nivel ORM.
    efirma: Mapped["Efirma | None"] = relationship(back_populates="empresa", uselist=False)
