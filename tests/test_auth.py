"""doc 06 §2.1 — Autenticación."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RolEmpresa, RolGlobal
from tests.factories import asignar_permiso, crear_empresa, crear_usuario

pytestmark = pytest.mark.asyncio


async def test_sin_token_401(client: AsyncClient) -> None:
    r = await client.get("/v1/me")
    assert r.status_code == 401
    assert r.json()["error"]["codigo"]


async def test_token_invalido_401(client: AsyncClient) -> None:
    r = await client.get("/v1/me", headers={"Authorization": "Bearer invalido"})
    assert r.status_code == 401


async def test_uid_sin_usuario_local_403(client: AsyncClient) -> None:
    r = await client.get("/v1/me", headers={"Authorization": "Bearer uid-no-registrado"})
    assert r.status_code == 403


async def test_usuario_inactivo_403(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-inactivo", correo="inactivo@demo.test", activo=False)
    r = await client.get("/v1/me", headers={"Authorization": "Bearer uid-inactivo"})
    assert r.status_code == 403


async def test_me_devuelve_usuario_y_empresas(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-ana", correo="ana@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db)
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)

    r = await client.get("/v1/me", headers={"Authorization": "Bearer uid-ana"})
    assert r.status_code == 200
    body = r.json()
    assert body["correo"] == "ana@demo.test"
    assert len(body["empresas"]) == 1
    assert body["empresas"][0]["rol"] == "operador"
    assert body["empresas"][0]["efirma"] == {"presente": False, "not_after": None}


async def test_rol_consulta_en_endpoint_mutante_403(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-beto", correo="beto@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db)
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    r = await client.delete(f"/v1/empresas/{empresa.empresa_id}/efirma", headers={"Authorization": "Bearer uid-beto"})
    assert r.status_code == 403
