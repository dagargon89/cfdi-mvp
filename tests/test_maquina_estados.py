"""Máquina de estados del job — exhaustiva (doc 06 §2.4, T1-T11 válidas / I1-I8 inválidas)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoJob
from app.models.job import Job
from app.repositories.jobs import transicion
from app.sat_hub.errors import TransicionIlegalError
from tests.factories import crear_empresa

pytestmark = pytest.mark.asyncio

_VALIDAS = [
    ("T1", EstadoJob.NUEVO, EstadoJob.SOLICITADO),
    ("T2", EstadoJob.NUEVO, EstadoJob.ERROR),
    ("T3", EstadoJob.SOLICITADO, EstadoJob.EN_PROCESO),
    ("T4", EstadoJob.SOLICITADO, EstadoJob.TERMINADA),
    ("T5", EstadoJob.SOLICITADO, EstadoJob.ERROR),
    ("T6", EstadoJob.EN_PROCESO, EstadoJob.EN_PROCESO),
    ("T7", EstadoJob.EN_PROCESO, EstadoJob.TERMINADA),
    ("T8", EstadoJob.EN_PROCESO, EstadoJob.ERROR),
    ("T9", EstadoJob.TERMINADA, EstadoJob.DESCARGADO),
    ("T10", EstadoJob.TERMINADA, EstadoJob.ERROR),
    ("T11", EstadoJob.ERROR, EstadoJob.NUEVO),
]

_INVALIDAS = [
    ("I1", EstadoJob.NUEVO, EstadoJob.DESCARGADO),
    ("I2", EstadoJob.NUEVO, EstadoJob.TERMINADA),
    ("I3", EstadoJob.SOLICITADO, EstadoJob.DESCARGADO),
    ("I4a", EstadoJob.DESCARGADO, EstadoJob.NUEVO),
    ("I4b", EstadoJob.DESCARGADO, EstadoJob.SOLICITADO),
    ("I4c", EstadoJob.DESCARGADO, EstadoJob.ERROR),
    ("I5", EstadoJob.EN_PROCESO, EstadoJob.NUEVO),
    ("I6", EstadoJob.SOLICITADO, EstadoJob.NUEVO),
    ("I7", EstadoJob.ERROR, EstadoJob.SOLICITADO),
]


async def _job(db: AsyncSession, estado: EstadoJob) -> Job:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    job = Job(
        empresa_id=empresa.empresa_id,
        tipo=TipoJob.RECIBIDO,
        solicitud=SolicitudTipo.CFDI,
        origen=OrigenJob.MANUAL,
        fecha_inicial=date(2026, 1, 1),
        fecha_final=date(2026, 1, 31),
        estado=estado,
    )
    db.add(job)
    await db.flush()
    return job


@pytest.mark.parametrize("codigo,origen,destino", _VALIDAS, ids=[v[0] for v in _VALIDAS])
async def test_transicion_valida(db: AsyncSession, codigo: str, origen: EstadoJob, destino: EstadoJob) -> None:
    job = await _job(db, origen)
    await transicion(db, job, destino)
    assert job.estado == destino


@pytest.mark.parametrize("codigo,origen,destino", _INVALIDAS, ids=[i[0] for i in _INVALIDAS])
async def test_transicion_invalida(db: AsyncSession, codigo: str, origen: EstadoJob, destino: EstadoJob) -> None:
    job = await _job(db, origen)
    with pytest.raises(TransicionIlegalError):
        await transicion(db, job, destino)
    assert job.estado == origen  # sin cambios tras el rechazo
