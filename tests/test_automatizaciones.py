"""Interruptores de las tareas automáticas (beat): cada tarea se salta si su bandera está en
`false`; endpoint GET/PUT (solo admin). Sin red del SAT ni de Firebase — dobles."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.enums import RolGlobal
from app.repositories import configuracion as config_repo
from app.worker import tasks as worker_tasks
from tests.factories import crear_usuario

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _sesion_de_prueba_en_worker(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_tasks, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))


async def test_sync_diaria_se_salta_si_desactivada(db: AsyncSession) -> None:
    await config_repo.establecer(db, "auto_sync_diaria", False)
    await db.commit()
    res = await worker_tasks._disparar_sync_diaria_async()
    assert res == {"disparado": False, "razon": "desactivada"}


async def test_lista_69b_se_salta_si_desactivada(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    # Si NO se saltara, intentaría descargar el CSV real; el doble revienta para probar que ni se llama.
    def _no_debe_llamarse() -> list:
        raise AssertionError("descargar_lista_69b no debe llamarse con la automatización apagada")

    monkeypatch.setattr(worker_tasks, "descargar_lista_69b", _no_debe_llamarse)
    await config_repo.establecer(db, "auto_lista_69b", False)
    await db.commit()
    res = await worker_tasks._actualizar_lista_69b_async()
    assert res == {"actualizado": False, "razon": "desactivada"}


async def test_re_verificar_se_salta_si_desactivada(db: AsyncSession) -> None:
    await config_repo.establecer(db, "auto_re_verificar", False)
    await db.commit()
    res = await worker_tasks._re_verificar_vigentes_async()
    assert res == {"revalidados": 0, "razon": "desactivada"}


async def test_get_automatizaciones_default_todas_activas(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="admin1", correo="admin@example.com", rol_global=RolGlobal.ADMIN)
    await db.commit()
    res = await client.get("/v1/config/automatizaciones", headers={"Authorization": "Bearer admin1"})
    assert res.status_code == 200
    assert res.json() == {"sync_diaria": True, "lista_69b": True, "re_verificar": True, "limpieza": True}


async def test_put_automatizaciones_persiste(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="admin1", correo="admin@example.com", rol_global=RolGlobal.ADMIN)
    await db.commit()
    body = {"sync_diaria": False, "lista_69b": True, "re_verificar": False, "limpieza": False}
    res = await client.put("/v1/config/automatizaciones", json=body, headers={"Authorization": "Bearer admin1"})
    assert res.status_code == 200
    assert res.json() == body
    # y quedó persistido
    assert bool(await config_repo.valor(db, "auto_sync_diaria", True)) is False
    assert bool(await config_repo.valor(db, "auto_lista_69b", True)) is True
    assert bool(await config_repo.valor(db, "auto_re_verificar", True)) is False
    assert bool(await config_repo.valor(db, "auto_limpieza", True)) is False


async def test_automatizaciones_solo_admin(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="consulta1", correo="c@example.com", rol_global=RolGlobal.CONSULTA)
    await db.commit()
    res = await client.get("/v1/config/automatizaciones", headers={"Authorization": "Bearer consulta1"})
    assert res.status_code == 403


async def test_limpieza_se_salta_si_desactivada(db: AsyncSession, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_root", str(tmp_path))
    await config_repo.establecer(db, "auto_limpieza", False)
    await db.commit()
    res = await worker_tasks._limpiar_almacenamiento_async()
    assert res == {"limpiado": False, "razon": "desactivada"}


async def test_limpieza_borra_viejos_conserva_recientes(db: AsyncSession, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import os
    import time
    from datetime import date, datetime, timedelta, timezone

    from sqlalchemy import update

    from app.core.config import get_settings
    from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoJob
    from app.models.job import Job
    from tests.factories import crear_empresa

    monkeypatch.setattr(get_settings(), "storage_root", str(tmp_path))
    empresa = await crear_empresa(db, rfc="EKU9003173C9")

    # Nivel 1: exports — uno viejo (borrar), uno reciente (conservar).
    exports = tmp_path / str(empresa.empresa_id) / "exports"
    exports.mkdir(parents=True)
    export_viejo = exports / "comprobantes_viejo.zip"
    export_viejo.write_bytes(b"x")
    export_reciente = exports / "comprobantes_reciente.zip"
    export_reciente.write_bytes(b"y")
    hace_mucho = time.time() - 100 * 3600  # 100 h atrás (> 48 h por defecto)
    os.utime(export_viejo, (hace_mucho, hace_mucho))

    # Nivel 2: un job DESCARGADO viejo (purgar sus paquetes) y uno reciente (conservar).
    def _job() -> Job:
        return Job(
            empresa_id=empresa.empresa_id, tipo=TipoJob.RECIBIDO, solicitud=SolicitudTipo.CFDI, origen=OrigenJob.MANUAL,
            fecha_inicial=date(2026, 1, 1), fecha_final=date(2026, 1, 31), estado=EstadoJob.DESCARGADO, intentos=0, paquetes=1,
        )

    job_viejo, job_reciente = _job(), _job()
    db.add_all([job_viejo, job_reciente])
    await db.flush()
    # forzar el updated_at viejo (una UPDATE explícita gana sobre ON UPDATE CURRENT_TIMESTAMP)
    await db.execute(update(Job).where(Job.job_id == job_viejo.job_id).values(updated_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)))
    await db.commit()

    for job in (job_viejo, job_reciente):
        carpeta = tmp_path / str(empresa.empresa_id) / str(job.job_id)
        carpeta.mkdir(parents=True)
        (carpeta / "paquete_1.zip").write_bytes(b"z")

    res = await worker_tasks._limpiar_almacenamiento_async()

    assert not export_viejo.exists()       # export viejo borrado
    assert export_reciente.exists()        # export reciente conservado
    assert not (tmp_path / str(empresa.empresa_id) / str(job_viejo.job_id) / "paquete_1.zip").exists()  # paquete viejo borrado
    assert (tmp_path / str(empresa.empresa_id) / str(job_reciente.job_id) / "paquete_1.zip").exists()   # reciente conservado
    assert res == {"exports": 1, "paquetes": 1, "kb_liberados": 0}
