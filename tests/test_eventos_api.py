"""API de eventos / EFOS 69-B / notificaciones (RF-RIES-01/02, RF-NOT-01) — filtros,
IDOR y RBAC (doc 05 §1.3, doc 06 §2.2)."""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RolEmpresa, RolGlobal, TipoEvento
from app.repositories import eventos as eventos_repo
from app.repositories import lista_69b as lista_69b_repo
from tests.factories import asignar_permiso, crear_empresa, crear_usuario

pytestmark = pytest.mark.asyncio


async def test_listar_eventos_con_filtro_tipo(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-con", correo="con@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)
    await eventos_repo.crear(db, empresa.empresa_id, TipoEvento.EFOS, {"rfc": "AAA010101AAA"})
    await eventos_repo.crear(db, empresa.empresa_id, TipoEvento.CANCELACION_TARDIA, {"uuid": "x"})
    await db.commit()

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/eventos", headers={"Authorization": "Bearer uid-con"})
    assert r.status_code == 200
    assert r.json()["total"] == 2

    r_filtrado = await client.get(
        f"/v1/empresas/{empresa.empresa_id}/eventos", params={"tipo": "efos"}, headers={"Authorization": "Bearer uid-con"}
    )
    body = r_filtrado.json()
    assert body["total"] == 1
    assert body["data"][0]["tipo"] == "efos"


async def test_eventos_empresa_ajena_404(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa_propia = await crear_empresa(db, nombre="Propia", rfc="EKU9003173C9")
    empresa_ajena = await crear_empresa(db, nombre="Ajena", rfc="XAXX010101000")
    await asignar_permiso(db, usuario, empresa_propia, RolEmpresa.OPERADOR)

    r = await client.get(f"/v1/empresas/{empresa_ajena.empresa_id}/eventos", headers={"Authorization": "Bearer uid-op"})
    assert r.status_code == 404


async def test_eventos_empresa_inexistente_404(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op2", correo="op2@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)

    r = await client.get("/v1/empresas/999999/eventos", headers={"Authorization": "Bearer uid-op2"})
    assert r.status_code == 404


async def test_efos_estado_sin_version_previa(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-cualquiera", correo="c@demo.test", rol_global=RolGlobal.CONSULTA)
    r = await client.get("/v1/efos/estado", headers={"Authorization": "Bearer uid-cualquiera"})
    assert r.status_code == 200
    assert r.json() == {"version_lista": None, "registros": 0}


async def test_efos_estado_devuelve_la_version_mas_reciente(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-cualquiera2", correo="c2@demo.test", rol_global=RolGlobal.CONSULTA)
    await lista_69b_repo.crear_version(db, date(2026, 7, 1), [("AAA010101AAA", "presunto")])
    await lista_69b_repo.crear_version(db, date(2026, 7, 28), [("BBB020202BBB", "definitivo"), ("CCC030303CCC", "desvirtuado")])
    await db.commit()

    r = await client.get("/v1/efos/estado", headers={"Authorization": "Bearer uid-cualquiera2"})
    assert r.status_code == 200
    body = r.json()
    assert body["version_lista"] == "2026-07-28"
    assert body["registros"] == 2


async def test_notificaciones_guardar_y_obtener(client: AsyncClient, db: AsyncSession) -> None:
    operador = await crear_usuario(db, uid="uid-op-notif", correo="opn@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)

    r_put = await client.put(
        f"/v1/empresas/{empresa.empresa_id}/notificaciones",
        json={"destinos": [{"correo": "contador@example.com", "eventos": ["efos", "cancelacion_tardia"]}]},
        headers={"Authorization": "Bearer uid-op-notif"},
    )
    assert r_put.status_code == 204

    r_get = await client.get(f"/v1/empresas/{empresa.empresa_id}/notificaciones", headers={"Authorization": "Bearer uid-op-notif"})
    assert r_get.status_code == 200
    destinos = r_get.json()["destinos"]
    assert len(destinos) == 1
    assert destinos[0]["correo"] == "contador@example.com"
    assert sorted(destinos[0]["eventos"]) == ["cancelacion_tardia", "efos"]


async def test_notificaciones_put_reemplaza_todo(client: AsyncClient, db: AsyncSession) -> None:
    operador = await crear_usuario(db, uid="uid-op-notif2", correo="opn2@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)

    await client.put(
        f"/v1/empresas/{empresa.empresa_id}/notificaciones",
        json={"destinos": [{"correo": "viejo@example.com", "eventos": ["efos"]}]},
        headers={"Authorization": "Bearer uid-op-notif2"},
    )
    r_put2 = await client.put(
        f"/v1/empresas/{empresa.empresa_id}/notificaciones",
        json={"destinos": [{"correo": "nuevo@example.com", "eventos": ["resumen_sync"]}]},
        headers={"Authorization": "Bearer uid-op-notif2"},
    )
    assert r_put2.status_code == 204

    r_get = await client.get(f"/v1/empresas/{empresa.empresa_id}/notificaciones", headers={"Authorization": "Bearer uid-op-notif2"})
    destinos = r_get.json()["destinos"]
    assert len(destinos) == 1
    assert destinos[0]["correo"] == "nuevo@example.com"


async def test_notificaciones_put_requiere_rol_operador(client: AsyncClient, db: AsyncSession) -> None:
    consulta = await crear_usuario(db, uid="uid-consulta-notif", correo="cn@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, consulta, empresa, RolEmpresa.CONSULTA)

    r = await client.put(
        f"/v1/empresas/{empresa.empresa_id}/notificaciones",
        json={"destinos": []},
        headers={"Authorization": "Bearer uid-consulta-notif"},
    )
    assert r.status_code == 403
