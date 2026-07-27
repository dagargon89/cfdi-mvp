"""doc 06 §2.3 — Bóveda de e.firmas (envelope encryption, A02)."""

from __future__ import annotations

import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.efirma import Efirma
from app.models.enums import RolGlobal
from tests._certs import generar_fiel_prueba
from tests.factories import crear_empresa, crear_usuario

pytestmark = pytest.mark.asyncio

RFC_EMPRESA = "EKU9003173C9"


async def _empresa_operador(db: AsyncSession) -> tuple[str, int]:
    from app.models.enums import RolEmpresa

    usuario = await crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc=RFC_EMPRESA)
    from tests.factories import asignar_permiso

    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)
    return "uid-op", empresa.empresa_id


async def test_alta_exitosa_cifra_en_reposo(client: AsyncClient, db: AsyncSession) -> None:
    uid, empresa_id = await _empresa_operador(db)
    cer, key, password = generar_fiel_prueba(rfc=RFC_EMPRESA)

    r = await client.post(
        f"/v1/empresas/{empresa_id}/efirma",
        headers={"Authorization": f"Bearer {uid}"},
        files={"cer": ("test.cer", cer, "application/octet-stream"), "key": ("test.key", key, "application/octet-stream")},
        data={"password": password},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "num_serie" in body and body["dias_para_vencer"] > 0

    row = await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa_id))
    assert row is not None
    assert password.encode() not in row.key_cifrada
    assert password.encode() not in row.password_cifrada
    assert b"BEGIN" not in row.key_cifrada  # la llave privada no queda en claro (PKCS8 DER tampoco tendría este header, pero confirma que no es el PEM sin cifrar)


async def test_contrasena_incorrecta_422_efirma_no_abre(client: AsyncClient, db: AsyncSession) -> None:
    uid, empresa_id = await _empresa_operador(db)
    cer, key, _ = generar_fiel_prueba(rfc=RFC_EMPRESA)

    r = await client.post(
        f"/v1/empresas/{empresa_id}/efirma",
        headers={"Authorization": f"Bearer {uid}"},
        files={"cer": ("test.cer", cer, "application/octet-stream"), "key": ("test.key", key, "application/octet-stream")},
        data={"password": "esta-no-es-la-password"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "EFIRMA_NO_ABRE"

    assert await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa_id)) is None


async def test_rfc_no_coincide_422(client: AsyncClient, db: AsyncSession) -> None:
    uid, empresa_id = await _empresa_operador(db)
    cer, key, password = generar_fiel_prueba(rfc="XAXX010101000")

    r = await client.post(
        f"/v1/empresas/{empresa_id}/efirma",
        headers={"Authorization": f"Bearer {uid}"},
        files={"cer": ("test.cer", cer, "application/octet-stream"), "key": ("test.key", key, "application/octet-stream")},
        data={"password": password},
    )
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "RFC_NO_COINCIDE"


async def test_efirma_vencida_422(client: AsyncClient, db: AsyncSession) -> None:
    uid, empresa_id = await _empresa_operador(db)
    cer, key, password = generar_fiel_prueba(
        rfc=RFC_EMPRESA,
        not_before=datetime.datetime(2015, 1, 1),
        not_after=datetime.datetime(2016, 1, 1),
    )

    r = await client.post(
        f"/v1/empresas/{empresa_id}/efirma",
        headers={"Authorization": f"Bearer {uid}"},
        files={"cer": ("test.cer", cer, "application/octet-stream"), "key": ("test.key", key, "application/octet-stream")},
        data={"password": password},
    )
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "EFIRMA_VENCIDA"


async def test_eliminar_efirma(client: AsyncClient, db: AsyncSession) -> None:
    uid, empresa_id = await _empresa_operador(db)
    cer, key, password = generar_fiel_prueba(rfc=RFC_EMPRESA)
    await client.post(
        f"/v1/empresas/{empresa_id}/efirma",
        headers={"Authorization": f"Bearer {uid}"},
        files={"cer": ("test.cer", cer, "application/octet-stream"), "key": ("test.key", key, "application/octet-stream")},
        data={"password": password},
    )

    r = await client.delete(f"/v1/empresas/{empresa_id}/efirma", headers={"Authorization": f"Bearer {uid}"})
    assert r.status_code == 204
    assert await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa_id)) is None
