from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.mysql import INTEGER as MYSQL_INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoJob, enum_column

if TYPE_CHECKING:
    from app.models.empresa import Empresa


class Job(Base):
    """Job de descarga masiva por ventana de fechas (doc 03 §2.2; máquina de estados doc 01 §1.6)."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("fecha_final >= fecha_inicial", name="chk_rango"),
        Index("idx_jobs_empresa_estado", "empresa_id", "estado"),
        Index("idx_jobs_estado", "estado"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    job_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="RESTRICT"), nullable=False)
    tipo: Mapped[TipoJob] = mapped_column(enum_column(TipoJob), nullable=False)
    solicitud: Mapped[SolicitudTipo] = mapped_column(enum_column(SolicitudTipo), nullable=False, default=SolicitudTipo.CFDI)
    origen: Mapped[OrigenJob] = mapped_column(enum_column(OrigenJob), nullable=False, default=OrigenJob.MANUAL)
    fecha_inicial: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_final: Mapped[date] = mapped_column(Date, nullable=False)
    id_solicitud: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estado: Mapped[EstadoJob] = mapped_column(enum_column(EstadoJob), nullable=False, default=EstadoJob.NUEVO)
    intentos: Mapped[int] = mapped_column(MYSQL_INTEGER(unsigned=True), nullable=False, default=0)
    paquetes: Mapped[int] = mapped_column(MYSQL_INTEGER(unsigned=True), nullable=False, default=0)
    mensaje: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    # server_default combinado (no `onupdate=`) es la única forma en SQLAlchemy de emitir el DDL
    # `ON UPDATE CURRENT_TIMESTAMP` real de MySQL en vez de solo simularlo a nivel ORM.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
    )

    empresa: Mapped["Empresa"] = relationship()
