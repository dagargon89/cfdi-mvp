"""RF-EMP-01/02 — alta, baja lógica y borrado real de empresas (solo admin)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.empresa import Empresa
from app.models.enums import RolGlobal
from tests._certs import generar_fiel_prueba
from tests.factories import crear_empresa, crear_usuario

pytestmark = pytest.mark.asyncio


async def test_no_admin_no_puede_crear_ni_borrar(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")

    r_crear = await client.post("/v1/empresas", headers={"Authorization": "Bearer uid-op"}, json={"nombre": "X", "rfc": "XAXX010101000"})
    r_borrar = await client.delete(f"/v1/empresas/{empresa.empresa_id}", headers={"Authorization": "Bearer uid-op"})
    assert r_crear.status_code == 403
    assert r_borrar.status_code == 403


async def test_admin_borra_empresa_sin_historial(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-admin", correo="admin@demo.test", rol_global=RolGlobal.ADMIN)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")

    r = await client.delete(f"/v1/empresas/{empresa.empresa_id}", headers={"Authorization": "Bearer uid-admin"})
    assert r.status_code == 204
    assert await db.get(Empresa, empresa.empresa_id) is None


async def test_no_se_puede_borrar_empresa_con_efirma(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-admin2", correo="admin2@demo.test", rol_global=RolGlobal.ADMIN)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    cer, key, password = generar_fiel_prueba(rfc="EKU9003173C9")
    r_alta = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-admin2"},
        files={"cer": ("test.cer", cer, "application/octet-stream"), "key": ("test.key", key, "application/octet-stream")},
        data={"password": password},
    )
    assert r_alta.status_code == 201

    r = await client.delete(f"/v1/empresas/{empresa.empresa_id}", headers={"Authorization": "Bearer uid-admin2"})
    assert r.status_code == 409
    assert r.json()["error"]["codigo"] == "EMPRESA_CON_HISTORIAL"
    assert await db.get(Empresa, empresa.empresa_id) is not None
