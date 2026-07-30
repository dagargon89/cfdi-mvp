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
    assert res.json() == {"sync_diaria": True, "lista_69b": True, "re_verificar": True}


async def test_put_automatizaciones_persiste(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="admin1", correo="admin@example.com", rol_global=RolGlobal.ADMIN)
    await db.commit()
    body = {"sync_diaria": False, "lista_69b": True, "re_verificar": False}
    res = await client.put("/v1/config/automatizaciones", json=body, headers={"Authorization": "Bearer admin1"})
    assert res.status_code == 200
    assert res.json() == body
    # y quedó persistido
    assert bool(await config_repo.valor(db, "auto_sync_diaria", True)) is False
    assert bool(await config_repo.valor(db, "auto_lista_69b", True)) is True
    assert bool(await config_repo.valor(db, "auto_re_verificar", True)) is False


async def test_automatizaciones_solo_admin(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="consulta1", correo="c@example.com", rol_global=RolGlobal.CONSULTA)
    await db.commit()
    res = await client.get("/v1/config/automatizaciones", headers={"Authorization": "Bearer consulta1"})
    assert res.status_code == 403
