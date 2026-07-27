from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import RolEmpresa, enum_column

if TYPE_CHECKING:
    from app.models.empresa import Empresa
    from app.models.usuario import Usuario


class UsuarioEmpresa(Base):
    """Permiso explícito usuario↔empresa (doc 03 §2.2) — los admin no aparecen aquí,
    tienen acceso implícito total (regla no negociable 3 de CLAUDE.md)."""

    __tablename__ = "usuario_empresa"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.usuario_id", ondelete="CASCADE"), primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="CASCADE"), primary_key=True)
    rol: Mapped[RolEmpresa] = mapped_column(enum_column(RolEmpresa), nullable=False, default=RolEmpresa.CONSULTA)

    usuario: Mapped["Usuario"] = relationship(back_populates="permisos")
    empresa: Mapped["Empresa"] = relationship(back_populates="permisos")
