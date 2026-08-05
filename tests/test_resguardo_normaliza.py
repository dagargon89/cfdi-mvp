"""Disparador 1 (spec §6.3): lo que entra por descarga queda normalizado.

La regla que no se negocia: un XML que el ETL no puede leer **no** impide que el
comprobante se indexe. El índice es lo que la UI necesita; la normalización es un extra.
"""

from __future__ import annotations

import os
import zipfile
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.cfdi_detalle import CfdiConcepto, ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoJob
from app.models.job import Job
from app.models.nomina import Nomina
from app.services import resguardo
from app.services.normalizacion import DatosComprobante
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


async def test_xml_ilegible_para_el_etl_no_impide_indexar(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
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


async def test_fallo_de_escribir_a_mitad_de_flush_no_envenena_el_resto_del_lote(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ronda de corrección: un fallo de `normalizar` puro (el caso de arriba) nunca toca la
    BD, así que no prueba nada sobre el aislamiento de la transacción. Este caso es distinto
    y es el que de verdad importa: `escribir()` truena **a mitad de un `flush`** — como
    pasaría con un `DataError` real de MySQL porque un valor del XML no entra en una columna
    acotada (`comprobante_detalle.moneda` es `CHAR(3)`, spec §5). Sin el SAVEPOINT alrededor
    de la normalización, eso deja la sesión en estado "pending rollback" y tumba el resto
    del lote — justo lo que la regla no negociable de esta tarea prohíbe."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    job = await _job_con_paquete(
        db,
        empresa.empresa_id,
        {
            "malo.xml": fixtures_cfdi.cfdi_ingreso(uuid="11111111-1111-1111-1111-111111111111"),
            "bueno.xml": fixtures_cfdi.cfdi_ingreso(uuid="22222222-2222-2222-2222-222222222222"),
        },
    )

    escribir_original = resguardo.repo_normalizacion.escribir
    llamadas: list[int] = []

    async def _escribir_con_fallo_en_el_primero(
        db_: AsyncSession, comprobante_id: int, datos: DatosComprobante, xml_hash: str
    ) -> None:
        llamadas.append(comprobante_id)
        if len(llamadas) == 1:
            # `DataError` real de MySQL a mitad de un `flush`, no un `ValueError` de mentiras:
            # este valor no entra en `comprobante_detalle.moneda` (`CHAR(3)`).
            db_.add(ComprobanteDetalle(comprobante_id=comprobante_id, moneda="DEMASIADO_LARGO", xml_hash=xml_hash, etl_version=1))
            await db_.flush()
            return
        await escribir_original(db_, comprobante_id, datos, xml_hash)

    monkeypatch.setattr(resguardo.repo_normalizacion, "escribir", _escribir_con_fallo_en_el_primero)

    nuevos = await resguardo.indexar_job(db, job, empresa)
    assert nuevos == 2  # el índice sobrevive para los dos — ni el fallo ni el envenenamiento lo tumban

    comprobantes = (await db.scalars(select(Comprobante).where(Comprobante.empresa_id == empresa.empresa_id))).all()
    assert len(comprobantes) == 2

    detalles = [
        await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == c.comprobante_id))
        for c in comprobantes
    ]
    assert all(d is not None for d in detalles)
    con_error = [d for d in detalles if d is not None and d.error_normalizacion is not None]
    sin_error = [d for d in detalles if d is not None and d.error_normalizacion is None]
    assert len(con_error) == 1  # el que tronó queda marcado, no perdido
    assert len(sin_error) == 1  # y el siguiente del lote se normaliza bien — la sesión no quedó envenenada

    conceptos = (await db.scalars(select(CfdiConcepto).where(CfdiConcepto.comprobante_id == sin_error[0].comprobante_id))).all()
    assert len(conceptos) > 0  # normalizado de verdad, con hijos en las tablas
