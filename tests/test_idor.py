"""doc 06 §2.2 — IDOR/aislamiento. Empresa inexistente y empresa ajena responden
idéntico (404) — anti-enumeración (doc 05 §1.3)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RolEmpresa, RolGlobal
from tests.factories import asignar_permiso, crear_empresa, crear_usuario

pytestmark = pytest.mark.asyncio


async def test_empresa_inexistente_404(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)

    r = await client.get("/v1/empresas/999999/efirma", headers={"Authorization": "Bearer uid-op"})
    assert r.status_code == 404


async def test_empresa_ajena_404_identico(client: AsyncClient, db: AsyncSession) -> None:
    """Usuario con permiso sobre la empresa 7 (aquí, la primera creada) pide un recurso
    de la empresa 8 (la segunda, sin permiso) → mismo 404 que si no existiera."""
    usuario = await crear_usuario(db, uid="uid-op2", correo="op2@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa_propia = await crear_empresa(db, nombre="Propia", rfc="EKU9003173C9")
    empresa_ajena = await crear_empresa(db, nombre="Ajena", rfc="XAXX010101000")
    await asignar_permiso(db, usuario, empresa_propia, RolEmpresa.OPERADOR)

    r_propia = await client.get(f"/v1/empresas/{empresa_propia.empresa_id}/efirma", headers={"Authorization": "Bearer uid-op2"})
    r_ajena = await client.get(f"/v1/empresas/{empresa_ajena.empresa_id}/efirma", headers={"Authorization": "Bearer uid-op2"})
    r_inexistente = await client.get("/v1/empresas/424242/efirma", headers={"Authorization": "Bearer uid-op2"})

    assert r_propia.status_code == 200
    assert r_ajena.status_code == 404
    assert r_inexistente.status_code == 404
    # Mismo cuerpo salvo `trace_id` (deliberadamente único por request, para correlar logs).
    assert r_ajena.json()["error"]["codigo"] == r_inexistente.json()["error"]["codigo"]
    assert r_ajena.json()["error"]["mensaje"] == r_inexistente.json()["error"]["mensaje"]


async def test_admin_ve_todas_las_empresas_sin_asignacion_explicita(client: AsyncClient, db: AsyncSession) -> None:
    admin = await crear_usuario(db, uid="uid-admin", correo="admin@demo.test", rol_global=RolGlobal.ADMIN)
    empresa = await crear_empresa(db)

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/efirma", headers={"Authorization": f"Bearer {admin.firebase_uid}"})
    assert r.status_code == 200

    r_listado = await client.get("/v1/empresas", headers={"Authorization": "Bearer uid-admin"})
    assert r_listado.status_code == 200
    assert len(r_listado.json()) == 1
