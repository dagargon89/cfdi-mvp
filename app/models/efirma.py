from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.empresa import Empresa


class Efirma(Base):
    """Bóveda — una e.firma vigente por empresa (doc 03 §2.2, doc 04 §3.3).

    `cer_pem` es público (sin cifrar); `key_cifrada`/`password_cifrada` son
    AES-256-GCM(DEK) con nonce+tag incluidos en el blob; `dek_envuelta` es la DEK
    envuelta por la KEK (que vive fuera de la BD). Nunca hay columnas en claro.
    """

    __tablename__ = "efirmas"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    efirma_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="RESTRICT"), unique=True, nullable=False)
    num_serie: Mapped[str] = mapped_column(String(40), nullable=False)
    not_before: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    not_after: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cer_pem: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_cifrada: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    password_cifrada: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_envuelta: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    empresa: Mapped["Empresa"] = relationship(back_populates="efirma")
