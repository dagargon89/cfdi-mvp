"""Composición repos → esquemas de salida, compartida entre /me y /empresas."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import ComprobanteOut, EfirmaResumenOut, EmpresaResumenOut, JobOut
from app.models.comprobante import Comprobante
from app.models.empresa import Empresa
from app.models.job import Job
from app.models.usuario import Usuario
from app.repositories import efirmas as efirmas_repo
from app.repositories import empresas as empresas_repo
from app.services import enlaces


async def empresa_resumen(db: AsyncSession, usuario: Usuario, empresa: Empresa) -> EmpresaResumenOut:
    rol = await empresas_repo.rol_de_usuario(db, usuario, empresa.empresa_id)
    efirma = await efirmas_repo.por_empresa(db, empresa.empresa_id)
    return EmpresaResumenOut(
        empresa_id=empresa.empresa_id,
        nombre=empresa.nombre,
        rfc=empresa.rfc,
        rol=rol or "",
        activo=empresa.activo,
        efirma=EfirmaResumenOut(presente=True, not_after=efirma.not_after.isoformat()) if efirma else EfirmaResumenOut(presente=False, not_after=None),
    )


def job_a_out(job: Job) -> JobOut:
    return JobOut(
        job_id=job.job_id,
        tipo=job.tipo.value,
        solicitud=job.solicitud.value,
        origen=job.origen.value,
        desde=job.fecha_inicial.isoformat(),
        hasta=job.fecha_final.isoformat(),
        estado=job.estado.value,
        intentos=job.intentos,
        paquetes=job.paquetes,
        mensaje=job.mensaje,
        updated_at=job.updated_at.isoformat(),
        id_solicitud=job.id_solicitud,
    )


def comprobante_a_out(c: Comprobante) -> ComprobanteOut:
    return ComprobanteOut(
        comprobante_id=c.comprobante_id,
        uuid=c.uuid,
        folio=c.folio,
        rfc_emisor=c.rfc_emisor,
        rfc_receptor=c.rfc_receptor,
        razon_social_emisor=c.razon_social_emisor,
        total=float(c.total) if c.total is not None else None,
        fecha_emision=c.fecha_emision.isoformat() if c.fecha_emision else None,
        tipo_comprobante=c.tipo_comprobante,
        estatus=c.estatus.value,
        estatus_verificado_at=c.estatus_verificado_at.isoformat() if c.estatus_verificado_at else None,
        # xml_path es la ruta interna (relativa a storage_root) — nunca se expone tal cual;
        # se convierte a una URL firmada temporal (doc 05 §9: "el drawer la necesita para el
        # enlace de descarga").
        xml_path=enlaces.url_descarga(c.xml_path) if c.xml_path else None,
    )
