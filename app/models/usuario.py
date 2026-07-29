from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import RolGlobal, enum_column

if TYPE_CHECKING:
    from app.models.usuario_empresa import UsuarioEmpresa


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    usuario_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    correo: Mapped[str] = mapped_column(String(190), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    rol_global: Mapped[RolGlobal] = mapped_column(enum_column(RolGlobal), nullable=False, default=RolGlobal.CONSULTA)
    activo: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, default=1)
    # `Boolean` (no `TINYINT(1)` como `activo`): MySQL compila ambos a la misma columna física
    # (`BOOL` es sinónimo de `TINYINT(1)`), pero `Boolean` sí trae result_processor que convierte
    # el 0/1 crudo del DBAPI (asyncmy) a `bool` de Python — necesario para `usuario.aprobado is False/True`.
    aprobado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    permisos: Mapped[list["UsuarioEmpresa"]] = relationship(back_populates="usuario", cascade="all, delete-orphan")
