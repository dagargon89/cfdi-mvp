from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import EstatusCfdi, enum_column

if TYPE_CHECKING:
    from app.models.empresa import Empresa


class Comprobante(Base):
    """Índice local de CFDI (doc 03 §2.2). `UNIQUE(empresa_id, uuid)` — no `UNIQUE(uuid)`
    global, porque el mismo CFDI puede aparecer legítimamente en dos empresas (emisora/receptora)."""

    __tablename__ = "comprobantes"
    __table_args__ = (
        UniqueConstraint("empresa_id", "uuid", name="uq_empresa_uuid"),
        Index("idx_comp_emp_fecha", "empresa_id", "fecha_emision"),
        Index("idx_comp_emp_estatus", "empresa_id", "estatus"),
        Index("idx_comp_emisor", "rfc_emisor"),
        Index("idx_comp_emp_verif", "empresa_id", "estatus_verificado_at"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    comprobante_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="RESTRICT"), nullable=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.job_id", ondelete="SET NULL"), nullable=True)
    uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    folio: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rfc_emisor: Mapped[str] = mapped_column(String(13), nullable=False)
    rfc_receptor: Mapped[str] = mapped_column(String(13), nullable=False)
    razon_social_emisor: Mapped[str | None] = mapped_column(String(254), nullable=True)
    total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    fecha_emision: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tipo_comprobante: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    estatus: Mapped[EstatusCfdi] = mapped_column(enum_column(EstatusCfdi), nullable=False, default=EstatusCfdi.NO_VERIFICADO)
    estatus_verificado_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    xml_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    comprobante_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    empresa: Mapped["Empresa"] = relationship()
