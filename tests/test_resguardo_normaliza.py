"""Disparador 1 (spec §6.3): lo que entra por descarga queda normalizado.

La regla que no se negocia: un XML que el ETL no puede leer **no** impide que el
comprobante se indexe. El índice es lo que la UI necesita; la normalización es un extra.
"""

from __future__ import annotations

import os
import zipfile
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoJob
from app.models.job import Job
from app.models.nomina import Nomina
from app.services import resguardo
from tests import factories, fixtures_cfdi


async def _job_con_paquete(db: AsyncSession, empresa_id: int, xmls: dict[str, bytes]) -> Job:
    job = Job(
        empresa_id=empresa_id,
        tipo=TipoJob.EMITIDO,
        solicitud=SolicitudTipo.CFDI,
        origen=OrigenJob.MANUAL,
        fecha_inicial=date(2026, 6, 1),
        fecha_final=date(2026, 7, 31),
        estado=EstadoJob.DESCARGADO,
    )
    db.add(job)
    await db.flush()
    await db.commit()

    # Misma convención de ruta que `resguardo._ruta_paquetes`: sin subcarpeta "paquetes".
    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), str(job.job_id))
    os.makedirs(carpeta, exist_ok=True)
    with zipfile.ZipFile(os.path.join(carpeta, "paquete_01.zip"), "w") as zf:
        for nombre, contenido in xmls.items():
            zf.writestr(nombre, contenido)
    return job


async def test_indexar_job_normaliza_la_nomina(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    job = await _job_con_paquete(db, empresa.empresa_id, {"nomina.xml": fixtures_cfdi.cfdi_nomina()})

    nuevos = await resguardo.indexar_job(db, job, empresa)
    assert nuevos == 1

    comprobante = await db.scalar(select(Comprobante).where(Comprobante.empresa_id == empresa.empresa_id))
    assert comprobante is not None
    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante.comprobante_id))
    assert detalle is not None
    assert detalle.error_normalizacion is None
    nomina = await db.scalar(select(Nomina).where(Nomina.comprobante_id == comprobante.comprobante_id))
    assert nomina is not None
    assert nomina.tipo_nomina == "O"


async def test_xml_ilegible_para_el_etl_no_impide_indexar(db: AsyncSession, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Si `normalizar` truena, el comprobante se indexa igual y el fallo queda registrado."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    job = await _job_con_paquete(db, empresa.empresa_id, {"ingreso.xml": fixtures_cfdi.cfdi_ingreso()})

    def _explota(_xml: bytes) -> None:
        raise ValueError("nodo inesperado")

    monkeypatch.setattr(resguardo.normalizacion, "normalizar", _explota)

    nuevos = await resguardo.indexar_job(db, job, empresa)
    assert nuevos == 1

    comprobante = await db.scalar(select(Comprobante).where(Comprobante.empresa_id == empresa.empresa_id))
    assert comprobante is not None
    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante.comprobante_id))
    assert detalle is not None
    assert detalle.error_normalizacion is not None
    assert "nodo inesperado" in detalle.error_normalizacion
