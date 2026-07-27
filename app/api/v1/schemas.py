"""Esquemas Pydantic — espejo de las formas JSON de doc 05 (contrato `ApiClient` congelado)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr

from app.models.enums import RolEmpresa, RolGlobal


class EfirmaResumenOut(BaseModel):
    presente: bool
    not_after: str | None


class EmpresaResumenOut(BaseModel):
    empresa_id: int
    nombre: str
    rfc: str
    rol: str
    activo: bool
    efirma: EfirmaResumenOut | None


class MeOut(BaseModel):
    usuario_id: int
    correo: str
    nombre: str
    rol_global: str
    empresas: list[EmpresaResumenOut]


class EmpresaCrearIn(BaseModel):
    nombre: str
    rfc: str


class EmpresaPatchIn(BaseModel):
    activo: bool | None = None


class EfirmaAltaOut(BaseModel):
    num_serie: str
    not_before: str
    not_after: str
    dias_para_vencer: int


class EfirmaMetaOut(BaseModel):
    num_serie: str
    not_before: str
    not_after: str


class UsuarioCrearIn(BaseModel):
    correo: EmailStr
    nombre: str
    rol_global: RolGlobal


class UsuarioOut(BaseModel):
    usuario_id: int
    correo: str
    nombre: str
    rol_global: str
    activo: bool


class PermisoEmpresaOut(BaseModel):
    empresa_id: int
    empresa_nombre: str
    rol: str


class UsuarioAdminOut(UsuarioOut):
    permisos: list[PermisoEmpresaOut]


class PermisoIn(BaseModel):
    empresa_id: int
    rol: RolEmpresa


class PermisosIn(BaseModel):
    permisos: list[PermisoIn]


class UsuarioPatchIn(BaseModel):
    activo: bool | None = None
    rol_global: RolGlobal | None = None


class BitacoraOut(BaseModel):
    bitacora_id: int
    actor: str
    accion: str
    entidad: str
    detalle: dict[str, object] | None
    created_at: str


class BitacoraPageOut(BaseModel):
    data: list[BitacoraOut]
    page: int
    per_page: int
    total: int
