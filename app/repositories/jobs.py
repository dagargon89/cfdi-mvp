"""Repositorio de `jobs` + máquina de estados (doc 01 §1.6, doc 06 §2.4 — T1-T11/I1-I8).

`transicion()` es el único punto por el que un job cambia de estado — tanto la API
(reintento manual, T11) como el worker (T1/T3-T10) pasan por aquí, así la legalidad
de la transición se valida en un solo lugar (heredado de `sat_hub/store.py` v1.0,
ver `app/sat_hub/errors.TransicionIlegalError`).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoJob
from app.models.job import Job
from app.sat_hub.errors import TransicionIlegalError

# Pares (origen, destino) permitidos — exactamente T1-T11 de doc 06 §2.4. Cualquier otro
# par (incluyendo I1-I7) queda rechazado por omisión. T6 (EN_PROCESO→EN_PROCESO) es la
# única auto-transición: el polling reintenta sin cambiar de estado.
_TRANSICIONES: frozenset[tuple[EstadoJob, EstadoJob]] = frozenset(
    {
        (EstadoJob.NUEVO, EstadoJob.SOLICITADO),  # T1
        (EstadoJob.NUEVO, EstadoJob.ERROR),  # T2
        (EstadoJob.SOLICITADO, EstadoJob.EN_PROCESO),  # T3
        (EstadoJob.SOLICITADO, EstadoJob.TERMINADA),  # T4
        (EstadoJob.SOLICITADO, EstadoJob.ERROR),  # T5
        (EstadoJob.EN_PROCESO, EstadoJob.EN_PROCESO),  # T6
        (EstadoJob.EN_PROCESO, EstadoJob.TERMINADA),  # T7
        (EstadoJob.EN_PROCESO, EstadoJob.ERROR),  # T8
        (EstadoJob.TERMINADA, EstadoJob.DESCARGADO),  # T9
        (EstadoJob.TERMINADA, EstadoJob.ERROR),  # T10
        (EstadoJob.ERROR, EstadoJob.NUEVO),  # T11
    }
)


async def transicion(db: AsyncSession, job: Job, nuevo_estado: EstadoJob, **campos: Any) -> Job:
    """Aplica una transición de estado si es legal; si no, lanza `TransicionIlegalError`.

    `**campos` son atributos adicionales de `Job` a actualizar en la misma operación
    (p. ej. `id_solicitud=...`, `mensaje=...`, `intentos=job.intentos + 1`). No hace
    commit — el caller decide cuándo cerrar la transacción.
    """
    if (job.estado, nuevo_estado) not in _TRANSICIONES:
        raise TransicionIlegalError(f"Transición ilegal: {job.estado.value} → {nuevo_estado.value} (job {job.job_id}).")
    job.estado = nuevo_estado
    for campo, valor in campos.items():
        setattr(job, campo, valor)
    await db.flush()
    return job


async def crear_lote(
    db: AsyncSession,
    *,
    empresa_id: int,
    tipo: TipoJob,
    solicitud: SolicitudTipo,
    ventanas: list[tuple[date, date]],
    origen: OrigenJob = OrigenJob.MANUAL,
) -> list[Job]:
    """Crea un job NUEVO por cada ventana ya troceada (RF-DESC-01)."""
    jobs = [
        Job(empresa_id=empresa_id, tipo=tipo, solicitud=solicitud, origen=origen, fecha_inicial=inicio, fecha_final=fin)
        for inicio, fin in ventanas
    ]
    db.add_all(jobs)
    await db.flush()
    return jobs


async def por_id_de_empresa(db: AsyncSession, empresa_id: int, job_id: int) -> Job | None:
    result: Job | None = await db.scalar(select(Job).where(Job.job_id == job_id, Job.empresa_id == empresa_id))
    return result


async def listar(
    db: AsyncSession,
    empresa_id: int,
    *,
    estado: EstadoJob | None = None,
    origen: OrigenJob | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[Job], int]:
    filtros = [Job.empresa_id == empresa_id]
    if estado is not None:
        filtros.append(Job.estado == estado)
    if origen is not None:
        filtros.append(Job.origen == origen)

    total = await db.scalar(select(func.count()).select_from(Job).where(*filtros)) or 0
    result = await db.scalars(
        select(Job).where(*filtros).order_by(Job.job_id.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    return list(result.all()), total
