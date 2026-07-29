"""Signup de arranque del primer admin (bootstrap) — spec 2026-07-29. Firebase Admin SDK mockeado
(sin red real); el fixture `db` recrea tablas por test, así que cada caso arranca con `usuarios` vacía."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import RolGlobal
from app.repositories import usuarios as usuarios_repo
from tests.factories import crear_usuario

# email-validator rechaza el TLD reservado ".test" (IANA special-use); se usa "example.com",
# convención ya usada en el resto de la suite para correos validados vía Pydantic EmailStr.
_BODY = {"correo": "admin@example.com", "nombre": "Admin", "password": "contrasena8", "token": "tok-test"}


class _CuentaFake:
    def __init__(self, uid: str) -> None:
        self.uid = uid


@pytest.fixture()
def firebase_fake(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Mockea el Admin SDK en el módulo del router: create_user devuelve un uid, delete_user se registra."""
    import app.api.v1.auth_bootstrap as mod

    estado: dict = {"creadas": [], "borradas": [], "fallar_create": None}

    def fake_create_user(**kwargs):
        if estado["fallar_create"] is not None:
            raise estado["fallar_create"]
        estado["creadas"].append(kwargs)
        return _CuentaFake("uid-fake-1")

    def fake_delete_user(uid, **kwargs):
        estado["borradas"].append(uid)

    monkeypatch.setattr(mod, "firebase_app", lambda: None)
    monkeypatch.setattr(mod.firebase_auth, "create_user", fake_create_user)
    monkeypatch.setattr(mod.firebase_auth, "delete_user", fake_delete_user)
    return estado


@pytest.fixture()
def con_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "bootstrap_admin_token", "tok-test")


async def test_status_bd_vacia(client: AsyncClient) -> None:
    res = await client.get("/v1/auth/bootstrap-status")
    assert res.status_code == 200
    assert res.json()["needs_bootstrap"] is True


async def test_status_con_usuario(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="u1", correo="ya@demo.test")
    await db.commit()
    res = await client.get("/v1/auth/bootstrap-status")
    assert res.json()["needs_bootstrap"] is False


async def test_bootstrap_ok(client: AsyncClient, db: AsyncSession, firebase_fake: dict, con_token: None) -> None:
    res = await client.post("/v1/auth/bootstrap", json=_BODY)
    assert res.status_code == 201, res.text
    usuario = await usuarios_repo.por_correo(db, "admin@example.com")
    assert usuario is not None
    assert usuario.rol_global == RolGlobal.ADMIN
    assert usuario.firebase_uid == "uid-fake-1"
    # se creó en Firebase CON contraseña
    assert firebase_fake["creadas"][0]["password"] == "contrasena8"


async def test_bootstrap_token_deshabilitado_503(client: AsyncClient, firebase_fake: dict, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "bootstrap_admin_token", "")
    res = await client.post("/v1/auth/bootstrap", json=_BODY)
    assert res.status_code == 503
    assert res.json()["error"]["codigo"] == "BOOTSTRAP_DESHABILITADO"


async def test_bootstrap_token_invalido_403(client: AsyncClient, firebase_fake: dict, con_token: None) -> None:
    res = await client.post("/v1/auth/bootstrap", json={**_BODY, "token": "otro"})
    assert res.status_code == 403
    assert res.json()["error"]["codigo"] == "TOKEN_INVALIDO"


async def test_bootstrap_ya_realizado_409(client: AsyncClient, db: AsyncSession, firebase_fake: dict, con_token: None) -> None:
    await crear_usuario(db, uid="u1", correo="ya@demo.test")
    await db.commit()
    res = await client.post("/v1/auth/bootstrap", json=_BODY)
    assert res.status_code == 409
    assert res.json()["error"]["codigo"] == "BOOTSTRAP_YA_REALIZADO"


async def test_bootstrap_correo_ya_en_firebase_409(client: AsyncClient, firebase_fake: dict, con_token: None) -> None:
    from firebase_admin import auth as firebase_auth

    # Firma exacta varía por versión de firebase-admin; construimos con los args mínimos que
    # la instalada acepta (message, cause, http_response) — el objetivo del test se mantiene:
    # que el `except firebase_auth.EmailAlreadyExistsError` del router la capture.
    firebase_fake["fallar_create"] = firebase_auth.EmailAlreadyExistsError("existe", None, None)
    res = await client.post("/v1/auth/bootstrap", json=_BODY)
    assert res.status_code == 409
    assert res.json()["error"]["codigo"] == "CORREO_DUPLICADO"


async def test_bootstrap_limpia_huerfano_si_falla_local(client: AsyncClient, firebase_fake: dict, con_token: None, monkeypatch) -> None:
    # Forzar fallo del registro local DESPUÉS de crear la cuenta en Firebase.
    import app.api.v1.auth_bootstrap as mod

    async def crear_explota(*a, **k):
        raise RuntimeError("fallo BD simulado")

    monkeypatch.setattr(mod.usuarios_repo, "crear", crear_explota)
    res = await client.post("/v1/auth/bootstrap", json=_BODY)
    assert res.status_code == 500
    assert firebase_fake["borradas"] == ["uid-fake-1"]  # se limpió el huérfano
