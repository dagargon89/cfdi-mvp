"""Sincronización diaria (RF-SYNC-01, RNF-05) — `ultima_ventana_sincronizada`,
`sync_diaria_empresa` (e.firma vigente/vencida/ausente) y `disparar_sync_diaria` (no
duplica corridas del mismo día)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.configuracion import Configuracion
from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoEvento, TipoJob
from app.repositories import efirmas as efirmas_repo
from app.repositories import eventos as eventos_repo
from app.repositories import jobs as jobs_repo
from app.services import boveda
from app.worker import tasks as worker_tasks
from tests._certs import generar_fiel_prueba
from tests.factories import crear_empresa
from tests.test_worker import _efirma_cifrada_sin_validar_vigencia

pytestmark = pytest.mark.asyncio


class _FakeTarea:
    def __init__(self) -> None:
        self.llamadas: list[int] = []

    def delay(self, id_: int) -> None:
        self.llamadas.append(id_)


@pytest.fixture(autouse=True)
def _sesion_de_prueba_en_worker(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_tasks, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))


async def _dar_efirma_vigente(db: AsyncSession, empresa_id: int, rfc: str) -> None:
    cer, key, password = generar_fiel_prueba(rfc=rfc)
    cifrada = boveda.preparar_efirma(cer, key, password, rfc)
    await efirmas_repo.upsert(db, empresa_id, cifrada)
    # `_sync_diaria_empresa_async` abre su PROPIA sesión (`SessionLocal`, otra conexión al
    # mismo testcontainer) — sin este commit no vería la e.firma, todavía pendiente en la
    # transacción de la sesión `db` de la prueba.
    await db.commit()


async def _set_config(db: AsyncSession, clave: str, valor: object) -> None:
    db.add(Configuracion(clave=clave, ejercicio_fiscal="vigente", valor=valor))
    await db.flush()
    await db.commit()


async def _crear_lote_sync_descargado(
    db: AsyncSession, *, empresa_id: int, tipo: TipoJob, solicitud: SolicitudTipo, ventanas: list[tuple[date, date]]
) -> None:
    """`ultima_ventana_sincronizada` solo cuenta jobs `DESCARGADO` — `crear_lote` los deja en
    `NUEVO` por default, así que las pruebas que simulan "esto ya se sincronizó" deben
    marcarlos como terminados a mano."""
    jobs = await jobs_repo.crear_lote(db, empresa_id=empresa_id, tipo=tipo, solicitud=solicitud, ventanas=ventanas, origen=OrigenJob.SYNC)
    for j in jobs:
        j.estado = EstadoJob.DESCARGADO
    await db.commit()


async def test_ultima_ventana_sincronizada_primera_vez_es_none(db: AsyncSession) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    resultado = await jobs_repo.ultima_ventana_sincronizada(db, empresa.empresa_id, TipoJob.RECIBIDO, SolicitudTipo.CFDI)
    assert resultado is None


async def test_ultima_ventana_sincronizada_incremental(db: AsyncSession) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await _crear_lote_sync_descargado(
        db, empresa_id=empresa.empresa_id, tipo=TipoJob.RECIBIDO, solicitud=SolicitudTipo.CFDI, ventanas=[(date(2026, 1, 1), date(2026, 1, 31))]
    )

    resultado = await jobs_repo.ultima_ventana_sincronizada(db, empresa.empresa_id, TipoJob.RECIBIDO, SolicitudTipo.CFDI)
    assert resultado == date(2026, 1, 31)

    # Un job MANUAL con una ventana más reciente no cuenta — solo `origen=SYNC` es la
    # marca de agua de la sincronización automática.
    await jobs_repo.crear_lote(
        db,
        empresa_id=empresa.empresa_id,
        tipo=TipoJob.RECIBIDO,
        solicitud=SolicitudTipo.CFDI,
        ventanas=[(date(2026, 6, 1), date(2026, 6, 30))],
        origen=OrigenJob.MANUAL,
    )
    await db.commit()
    resultado2 = await jobs_repo.ultima_ventana_sincronizada(db, empresa.empresa_id, TipoJob.RECIBIDO, SolicitudTipo.CFDI)
    assert resultado2 == date(2026, 1, 31)


async def test_ultima_ventana_sincronizada_ignora_jobs_en_error(db: AsyncSession) -> None:
    """Un job de sync en ERROR nunca llegó a bajar nada — no puede darse esa fecha por
    sincronizada (de lo contrario ese día quedaría saltado para siempre)."""
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    jobs = await jobs_repo.crear_lote(
        db,
        empresa_id=empresa.empresa_id,
        tipo=TipoJob.RECIBIDO,
        solicitud=SolicitudTipo.CFDI,
        ventanas=[(date(2026, 1, 1), date(2026, 1, 31))],
        origen=OrigenJob.SYNC,
    )
    jobs[0].estado = EstadoJob.ERROR
    await db.commit()

    resultado = await jobs_repo.ultima_ventana_sincronizada(db, empresa.empresa_id, TipoJob.RECIBIDO, SolicitudTipo.CFDI)
    assert resultado is None


async def test_sync_diaria_empresa_efirma_vigente_crea_un_job_por_combinacion(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await _dar_efirma_vigente(db, empresa.empresa_id, "EKU9003173C9")
    tarea_fake = _FakeTarea()
    monkeypatch.setattr(worker_tasks, "ejecutar_job", tarea_fake)

    resultado = await worker_tasks._sync_diaria_empresa_async(empresa.empresa_id)

    assert resultado["jobs_creados"] == 4  # emitido/recibido × CFDI/Metadata, primera vez cada una
    assert resultado["evento"] is None
    assert len(tarea_fake.llamadas) == 4
    _, total = await jobs_repo.listar(db, empresa.empresa_id, origen=OrigenJob.SYNC)
    assert total == 4


async def test_sync_diaria_empresa_no_repite_ventana_ya_sincronizada(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await _dar_efirma_vigente(db, empresa.empresa_id, "EKU9003173C9")
    monkeypatch.setattr(worker_tasks, "ejecutar_job", _FakeTarea())

    await worker_tasks._sync_diaria_empresa_async(empresa.empresa_id)
    resultado2 = await worker_tasks._sync_diaria_empresa_async(empresa.empresa_id)

    assert resultado2["jobs_creados"] == 0  # ya sincronizado hasta ayer en las 4 combinaciones


async def test_sync_diaria_empresa_regimen_estable_nunca_pide_un_solo_dia(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirmado en producción (2026-07-28): el SAT rechaza (CodEstatus=301) una solicitud
    cuya fecha inicial y final caen en el mismo día calendario — con una sync que avanza un
    día por corrida, `ultima_ventana_sincronizada + 1 día` == "ayer" TODOS los días en régimen
    estable, no solo la primera vez. `desde` debe traslapar el último día ya cubierto en vez de
    empezar al día siguiente, para que el rango enviado al SAT siempre abarque ≥ 2 días."""
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await _dar_efirma_vigente(db, empresa.empresa_id, "EKU9003173C9")
    ayer = date.today() - timedelta(days=1)
    anteayer = ayer - timedelta(days=1)
    # Simula que esta combinación ya se sincronizó hasta "anteayer" (como si la corrida de
    # ayer hubiera terminado con éxito) — la corrida de HOY solo tendría "ayer" como día nuevo.
    await _crear_lote_sync_descargado(
        db, empresa_id=empresa.empresa_id, tipo=TipoJob.RECIBIDO, solicitud=SolicitudTipo.CFDI, ventanas=[(anteayer, anteayer)]
    )
    tarea_fake = _FakeTarea()
    monkeypatch.setattr(worker_tasks, "ejecutar_job", tarea_fake)

    resultado = await worker_tasks._sync_diaria_empresa_async(empresa.empresa_id)

    assert resultado["evento"] is None  # nunca debió toparse con un RangoInvalidoError
    assert resultado["jobs_creados"] == 4
    jobs, _ = await jobs_repo.listar(db, empresa.empresa_id, origen=OrigenJob.SYNC)
    nuevo = next(j for j in jobs if j.tipo is TipoJob.RECIBIDO and j.solicitud is SolicitudTipo.CFDI and j.fecha_inicial == anteayer)
    assert nuevo.fecha_final == ayer  # traslapa "anteayer" (ya cubierto) en vez de pedir solo "ayer"


async def test_sync_diaria_empresa_efirma_ausente_crea_evento(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    monkeypatch.setattr(worker_tasks, "ejecutar_job", _FakeTarea())

    resultado = await worker_tasks._sync_diaria_empresa_async(empresa.empresa_id)

    assert resultado["jobs_creados"] == 0
    assert resultado["evento"] == "efirma_por_vencer"
    _, total = await eventos_repo.listar(db, empresa.empresa_id, tipo=TipoEvento.EFIRMA_POR_VENCER)
    assert total == 1


async def test_sync_diaria_empresa_efirma_vencida_crea_evento(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    cer, key, password = generar_fiel_prueba(rfc="EKU9003173C9", not_before=datetime(2020, 1, 1), not_after=datetime(2020, 6, 1))
    cifrada = _efirma_cifrada_sin_validar_vigencia(cer, key, password)
    await efirmas_repo.upsert(db, empresa.empresa_id, cifrada)
    await db.commit()  # visible para la sesión propia de `_sync_diaria_empresa_async`
    monkeypatch.setattr(worker_tasks, "ejecutar_job", _FakeTarea())

    resultado = await worker_tasks._sync_diaria_empresa_async(empresa.empresa_id)

    assert resultado["jobs_creados"] == 0
    assert resultado["evento"] == "efirma_por_vencer"


async def test_disparar_sync_diaria_dispara_y_no_duplica_el_mismo_dia(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await _dar_efirma_vigente(db, empresa.empresa_id, "EKU9003173C9")
    # "00:00": siempre <= la hora real de la corrida, sin importar cuándo se ejecuten las pruebas.
    await _set_config(db, "hora_sync", "00:00")
    tarea_fake = _FakeTarea()
    monkeypatch.setattr(worker_tasks, "sync_diaria_empresa", tarea_fake)

    resultado1 = await worker_tasks._disparar_sync_diaria_async()
    assert resultado1 == {"disparado": True, "empresas": 1}
    assert tarea_fake.llamadas == [empresa.empresa_id]

    resultado2 = await worker_tasks._disparar_sync_diaria_async()
    assert resultado2 == {"disparado": False, "razon": "ya_corrio_hoy"}
    assert tarea_fake.llamadas == [empresa.empresa_id]  # no se volvió a encolar


async def test_disparar_sync_diaria_fuera_de_hora_no_hace_nada(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await _dar_efirma_vigente(db, empresa.empresa_id, "EKU9003173C9")
    await _set_config(db, "hora_sync", "23:59")  # nunca es la hora salvo a las 23:59 exactas
    tarea_fake = _FakeTarea()
    monkeypatch.setattr(worker_tasks, "sync_diaria_empresa", tarea_fake)

    if datetime.now().hour == 23:
        pytest.skip("no determinista a las 23:xx horas")

    resultado = await worker_tasks._disparar_sync_diaria_async()
    assert resultado == {"disparado": False, "razon": "fuera_de_hora"}
    assert tarea_fake.llamadas == []
