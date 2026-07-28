"""Esquemas Pydantic — espejo de las formas JSON de doc 05 (contrato `ApiClient` congelado)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr

from app.models.enums import RolEmpresa, RolGlobal, SolicitudTipo, TipoJob


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


class DescargaCrearIn(BaseModel):
    tipo: TipoJob
    solicitud: SolicitudTipo
    desde: date
    hasta: date


class DescargaCrearOut(BaseModel):
    job_ids: list[int]
    ventanas: int


class JobOut(BaseModel):
    job_id: int
    tipo: str
    solicitud: str
    origen: str
    desde: str
    hasta: str
    estado: str
    intentos: int
    paquetes: int
    mensaje: str | None
    updated_at: str
    id_solicitud: str | None


class JobPageOut(BaseModel):
    data: list[JobOut]
    page: int
    per_page: int
    total: int


class ComprobanteOut(BaseModel):
    comprobante_id: int
    uuid: str
    folio: str | None
    rfc_emisor: str
    rfc_receptor: str
    razon_social_emisor: str | None
    total: float | None
    fecha_emision: str | None
    tipo_comprobante: str | None
    estatus: str
    estatus_verificado_at: str | None
    xml_path: str | None


class ComprobantePageOut(BaseModel):
    data: list[ComprobanteOut]
    page: int
    per_page: int
    total: int


class AlcanceUuids(BaseModel):
    uuids: list[str]


class ValidarLoteIn(BaseModel):
    alcance: Literal["no_verificados", "todos"] | AlcanceUuids


class TareaCrearOut(BaseModel):
    tarea_id: str


class TareaEstadoOut(BaseModel):
    estado: Literal["pendiente", "completada", "fallida"]
    descarga_url: str | None = None


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
