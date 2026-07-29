"""Esquemas Pydantic — espejo de las formas JSON de doc 05 (contrato `ApiClient` congelado)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import RolEmpresa, RolGlobal, SolicitudTipo, TipoEvento, TipoJob


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


class BootstrapStatusOut(BaseModel):
    needs_bootstrap: bool


class BootstrapAdminIn(BaseModel):
    correo: EmailStr
    nombre: str
    password: str = Field(min_length=8)
    token: str


class RegistroIn(BaseModel):
    nombre: str


class RegistroOut(BaseModel):
    estado: str


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
    aprobado: bool


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
    aprobado: bool | None = None


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


class MetadataPreviewOut(BaseModel):
    headers: list[str]
    filas: list[list[str]]
    total: int
    page: int
    per_page: int


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


class ComprobanteIdsIn(BaseModel):
    comprobante_ids: list[int]


class TareaCrearOut(BaseModel):
    tarea_id: str


class TareaEstadoOut(BaseModel):
    estado: Literal["pendiente", "completada", "fallida"]
    descarga_url: str | None = None


class EventoOut(BaseModel):
    evento_id: int
    tipo: str
    detalle: dict[str, object]
    created_at: str


class EventoPageOut(BaseModel):
    data: list[EventoOut]
    page: int
    per_page: int
    total: int


class Efos69bEstadoOut(BaseModel):
    version_lista: str | None
    registros: int


class NotificacionDestinoIn(BaseModel):
    correo: EmailStr
    eventos: list[TipoEvento]


class NotificacionesGuardarIn(BaseModel):
    destinos: list[NotificacionDestinoIn]


class NotificacionDestinoOut(BaseModel):
    correo: str
    eventos: list[str]


class NotificacionesOut(BaseModel):
    destinos: list[NotificacionDestinoOut]


class ConfigSmtpOut(BaseModel):
    configurado: bool
    host: str | None
    port: int | None
    usuario: str | None
    remitente: str | None
    tls: bool | None


class ConfigSmtpIn(BaseModel):
    host: str
    port: int = 587
    usuario: str
    # `None`/vacío conserva la contraseña ya guardada (editar host/remitente sin reteclearla).
    password: str | None = None
    remitente: str
    tls: bool = True


class ConfigSmtpProbarIn(ConfigSmtpIn):
    correo_destino: EmailStr


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
