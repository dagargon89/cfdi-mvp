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
    monkeypatch.setattr(comprobantes_router, "descargar_zip_lote", tarea)


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


async def test_listar_comprobantes_filtro_direccion(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-con5", correo="con5@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)
    # emitido por la propia empresa (rfc_emisor == empresa.rfc)
    await crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111", rfc_emisor="EKU9003173C9", rfc_receptor="COS890215XXX"
    )
    # recibido por la propia empresa (rfc_receptor == empresa.rfc)
    await crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="22222222-2222-2222-2222-222222222222", rfc_emisor="COS890215XXX", rfc_receptor="EKU9003173C9"
    )

    r_emitidos = await client.get(
        f"/v1/empresas/{empresa.empresa_id}/comprobantes", params={"direccion": "emitido"}, headers={"Authorization": "Bearer uid-con5"}
    )
    body_e = r_emitidos.json()
    assert body_e["total"] == 1
    assert body_e["data"][0]["uuid"] == "11111111-1111-1111-1111-111111111111"

    r_recibidos = await client.get(
        f"/v1/empresas/{empresa.empresa_id}/comprobantes", params={"direccion": "recibido"}, headers={"Authorization": "Bearer uid-con5"}
    )
    body_r = r_recibidos.json()
    assert body_r["total"] == 1
    assert body_r["data"][0]["uuid"] == "22222222-2222-2222-2222-222222222222"


async def test_listar_comprobantes_direccion_invalida_422(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-con6", correo="con6@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    r = await client.get(
        f"/v1/empresas/{empresa.empresa_id}/comprobantes", params={"direccion": "no_es_valido"}, headers={"Authorization": "Bearer uid-con6"}
    )
    assert r.status_code == 422


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


async def _comprobante_con_xml_real(db: AsyncSession, empresa_id: int, uuid: str) -> None:
    """Escribe un XML sintético real en `storage_root` y crea el `Comprobante` que apunta a
    él — los endpoints de pdf/detalle/paquete leen el archivo de disco de verdad."""
    import os

    from app.core.config import get_settings
    from tests.test_resguardo import _xml

    ruta_relativa = os.path.join(str(empresa_id), "comprobantes", f"{uuid}.xml")
    ruta_absoluta = os.path.join(get_settings().storage_root, ruta_relativa)
    os.makedirs(os.path.dirname(ruta_absoluta), exist_ok=True)
    with open(ruta_absoluta, "wb") as f:
        f.write(_xml(uuid))
    await crear_comprobante(db, empresa_id=empresa_id, uuid=uuid, xml_path=ruta_relativa)


async def test_descargar_pdf_200(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-pdf", correo="pdf@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)
    await _comprobante_con_xml_real(db, empresa.empresa_id, "aaaaaaaa-1111-1111-1111-111111111111")

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/comprobantes/1/pdf", headers={"Authorization": "Bearer uid-pdf"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")


async def test_descargar_detalle_200(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-det", correo="det@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)
    await _comprobante_con_xml_real(db, empresa.empresa_id, "bbbbbbbb-2222-2222-2222-222222222222")

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/comprobantes/1/detalle", headers={"Authorization": "Bearer uid-det"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")


async def test_descargar_paquete_zip_200_con_3_archivos(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-paq", correo="paq@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)
    await _comprobante_con_xml_real(db, empresa.empresa_id, "cccccccc-3333-3333-3333-333333333333")

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/comprobantes/1/paquete", headers={"Authorization": "Bearer uid-paq"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    import zipfile
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(r.content)) as zf:
        assert len(zf.namelist()) == 3


async def test_descargar_pdf_comprobante_de_otra_empresa_404_idor(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-idor", correo="idor@demo.test", rol_global=RolGlobal.CONSULTA)
    otra_empresa = await crear_empresa(db, rfc="XAXX010101000")
    await _comprobante_con_xml_real(db, otra_empresa.empresa_id, "dddddddd-4444-4444-4444-444444444444")

    r = await client.get(f"/v1/empresas/{otra_empresa.empresa_id}/comprobantes/1/pdf", headers={"Authorization": "Bearer uid-idor"})
    assert r.status_code == 404  # sin permiso sobre la empresa — ni siquiera llega a buscar el comprobante


async def test_descargar_zip_lote_202(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-lote", correo="lote@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="eeeeeeee-5555-5555-5555-555555555555")

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/comprobantes/descargar-zip",
        headers={"Authorization": "Bearer uid-lote"},
        json={"comprobante_ids": [1]},
    )
    assert r.status_code == 202
    assert r.json()["tarea_id"] == "tarea-falsa-1234"
