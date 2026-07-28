"""API de comprobantes (doc 05 §6) — listados con filtros, validar/export (202 + tarea_id),
RBAC y anti-enumeración (IDOR). El worker real se espía — el procesamiento real de
`validar_lote`/`exportar_excel` se cubre en `tests/test_worker_comprobantes.py`.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import comprobantes as comprobantes_router
from app.models.enums import EstatusCfdi, RolEmpresa, RolGlobal
from tests.factories import asignar_permiso, crear_comprobante, crear_empresa, crear_usuario

pytestmark = pytest.mark.asyncio


class _TareaFalsa:
    id = "tarea-falsa-1234"

    def delay(self, *args: object, **kwargs: object) -> "_TareaFalsa":
        return self


@pytest.fixture(autouse=True)
def _sin_worker_real(monkeypatch: pytest.MonkeyPatch) -> None:
    tarea = _TareaFalsa()
    monkeypatch.setattr(comprobantes_router, "validar_lote", tarea)
    monkeypatch.setattr(comprobantes_router, "exportar_excel", tarea)


async def test_listar_comprobantes_con_filtros(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-con", correo="con@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111", estatus=EstatusCfdi.VIGENTE)
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="22222222-2222-2222-2222-222222222222", estatus=EstatusCfdi.CANCELADO)

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/comprobantes", headers={"Authorization": "Bearer uid-con"})
    assert r.status_code == 200
    assert r.json()["total"] == 2

    r_filtrado = await client.get(
        f"/v1/empresas/{empresa.empresa_id}/comprobantes", params={"estatus": "cancelado"}, headers={"Authorization": "Bearer uid-con"}
    )
    body = r_filtrado.json()
    assert body["total"] == 1
    assert body["data"][0]["uuid"] == "22222222-2222-2222-2222-222222222222"


async def test_listar_comprobantes_busqueda_por_texto(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-con2", correo="con2@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111", razon_social_emisor="ACME SA DE CV")
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="22222222-2222-2222-2222-222222222222", razon_social_emisor="OTRA EMPRESA")

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/comprobantes", params={"q": "acme"}, headers={"Authorization": "Bearer uid-con2"})
    body = r.json()
    assert body["total"] == 1
    assert body["data"][0]["razon_social_emisor"] == "ACME SA DE CV"


async def test_listar_comprobantes_empresa_ajena_404_idor(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-ajeno", correo="ajeno@demo.test", rol_global=RolGlobal.CONSULTA)
    otra_empresa = await crear_empresa(db, rfc="XAXX010101000")  # sin permiso para uid-ajeno

    r = await client.get(f"/v1/empresas/{otra_empresa.empresa_id}/comprobantes", headers={"Authorization": "Bearer uid-ajeno"})
    assert r.status_code == 404


async def test_validar_lote_202(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111")

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/comprobantes/validar", headers={"Authorization": "Bearer uid-op"}, json={"alcance": "no_verificados"}
    )
    assert r.status_code == 202
    assert r.json()["tarea_id"] == "tarea-falsa-1234"


async def test_validar_lote_consulta_no_puede_403(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-con3", correo="con3@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/comprobantes/validar", headers={"Authorization": "Bearer uid-con3"}, json={"alcance": "todos"}
    )
    assert r.status_code == 403


async def test_validar_lote_con_uuids_explicitos(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op2", correo="op2@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/comprobantes/validar",
        headers={"Authorization": "Bearer uid-op2"},
        json={"alcance": {"uuids": ["11111111-1111-1111-1111-111111111111"]}},
    )
    assert r.status_code == 202


async def test_exportar_excel_202(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-con4", correo="con4@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/comprobantes/export", headers={"Authorization": "Bearer uid-con4"})
    assert r.status_code == 202
    assert r.json()["tarea_id"] == "tarea-falsa-1234"
