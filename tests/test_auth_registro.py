"""Auto-registro con aprobación (spec 2026-07-29). Firebase Admin SDK y SMTP mockeados; el fixture `db`
recrea tablas por test desde el modelo (incluye la columna `aprobado`)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RolGlobal
from app.models.usuario import Usuario
from app.repositories import usuarios as usuarios_repo
from tests.factories import crear_usuario


async def _usuario(db: AsyncSession, *, uid: str, correo: str, rol=RolGlobal.CONSULTA, activo=True, aprobado=True) -> Usuario:
    u = await usuarios_repo.crear(db, firebase_uid=uid, correo=correo, nombre="N", rol_global=rol, aprobado=aprobado)
    u.activo = activo
    await db.commit()
    return u


async def test_puerta_pendiente_403_codigo(client: AsyncClient, db: AsyncSession) -> None:
    await _usuario(db, uid="uid-pend", correo="pend@example.com", aprobado=False)
    res = await client.get("/v1/me", headers={"Authorization": "Bearer uid-pend"})
    assert res.status_code == 403
    assert res.json()["error"]["codigo"] == "CUENTA_PENDIENTE"


async def test_puerta_inactiva_403_codigo(client: AsyncClient, db: AsyncSession) -> None:
    await _usuario(db, uid="uid-off", correo="off@example.com", aprobado=True, activo=False)
    res = await client.get("/v1/me", headers={"Authorization": "Bearer uid-off"})
    assert res.status_code == 403
    assert res.json()["error"]["codigo"] == "CUENTA_INACTIVA"


async def test_puerta_no_registrado_403_codigo(client: AsyncClient, db: AsyncSession) -> None:
    res = await client.get("/v1/me", headers={"Authorization": "Bearer uid-fantasma"})
    assert res.status_code == 403
    assert res.json()["error"]["codigo"] == "NO_REGISTRADO"


async def test_usuario_aprobado_activo_pasa(client: AsyncClient, db: AsyncSession) -> None:
    await _usuario(db, uid="uid-ok", correo="ok@example.com", aprobado=True, activo=True)
    res = await client.get("/v1/me", headers={"Authorization": "Bearer uid-ok"})
    assert res.status_code == 200


async def test_contar_admins_activos(db: AsyncSession) -> None:
    await _usuario(db, uid="a1", correo="a1@example.com", rol=RolGlobal.ADMIN)
    await _usuario(db, uid="a2", correo="a2@example.com", rol=RolGlobal.ADMIN, activo=False)  # no cuenta
    await _usuario(db, uid="c1", correo="c1@example.com", rol=RolGlobal.CONSULTA)              # no cuenta
    assert await usuarios_repo.contar_admins_activos(db) == 1
