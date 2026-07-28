"""API de configuración SMTP (RF-NOT-01, Configuración → Correo) — admin-only, la
contraseña nunca se regresa, y guardar sin contraseña conserva la ya guardada."""

from __future__ import annotations

import smtplib

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RolGlobal
from tests.factories import crear_usuario


class _FakeSmtp:
    instancias: list["_FakeSmtp"] = []
    fallar_login: bool = False

    def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
        self.host, self.port = host, port
        self.mensajes: list[object] = []
        _FakeSmtp.instancias.append(self)

    def __enter__(self) -> "_FakeSmtp":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def starttls(self) -> None:
        pass

    def login(self, usuario: str, password: str) -> None:
        if _FakeSmtp.fallar_login:
            raise smtplib.SMTPAuthenticationError(535, b"credenciales invalidas")

    def send_message(self, mensaje: object) -> None:
        self.mensajes.append(mensaje)


@pytest.fixture(autouse=True)
def _smtp_fake(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSmtp]:
    _FakeSmtp.instancias = []
    _FakeSmtp.fallar_login = False
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtp)
    return _FakeSmtp


_BODY = {"host": "smtp.test.local", "port": 587, "usuario": "no-reply@test.local", "password": "secreto", "remitente": "Hub CFDI", "tls": True}


async def test_get_sin_configurar(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-admin", correo="admin@demo.test", rol_global=RolGlobal.ADMIN)
    r = await client.get("/v1/config/smtp", headers={"Authorization": "Bearer uid-admin"})
    assert r.status_code == 200
    assert r.json() == {"configurado": False, "host": None, "port": None, "usuario": None, "remitente": None, "tls": None}


async def test_put_y_get_no_regresa_password(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-admin2", correo="admin2@demo.test", rol_global=RolGlobal.ADMIN)

    r_put = await client.put("/v1/config/smtp", json=_BODY, headers={"Authorization": "Bearer uid-admin2"})
    assert r_put.status_code == 204

    r_get = await client.get("/v1/config/smtp", headers={"Authorization": "Bearer uid-admin2"})
    body = r_get.json()
    assert body["configurado"] is True
    assert body["host"] == "smtp.test.local"
    assert "password" not in body


async def test_put_sin_password_conserva_la_anterior(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-admin3", correo="admin3@demo.test", rol_global=RolGlobal.ADMIN)
    await client.put("/v1/config/smtp", json=_BODY, headers={"Authorization": "Bearer uid-admin3"})

    body_sin_password = {**_BODY, "host": "smtp.nuevo.local", "password": None}
    r_put2 = await client.put("/v1/config/smtp", json=body_sin_password, headers={"Authorization": "Bearer uid-admin3"})
    assert r_put2.status_code == 204

    r_get = await client.get("/v1/config/smtp", headers={"Authorization": "Bearer uid-admin3"})
    assert r_get.json()["host"] == "smtp.nuevo.local"

    r_probar = await client.post(
        "/v1/config/smtp/probar", json={**body_sin_password, "correo_destino": "yo@example.com"}, headers={"Authorization": "Bearer uid-admin3"}
    )
    assert r_probar.status_code == 200  # usó la contraseña ya guardada, no la que venía en None


async def test_put_sin_password_ni_previa_422(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-admin4", correo="admin4@demo.test", rol_global=RolGlobal.ADMIN)
    body = {**_BODY, "password": None}
    r = await client.put("/v1/config/smtp", json=body, headers={"Authorization": "Bearer uid-admin4"})
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "SMTP_SIN_CONTRASENA"


async def test_no_admin_403(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-operador", correo="operador@demo.test", rol_global=RolGlobal.OPERADOR)
    r_get = await client.get("/v1/config/smtp", headers={"Authorization": "Bearer uid-operador"})
    r_put = await client.put("/v1/config/smtp", json=_BODY, headers={"Authorization": "Bearer uid-operador"})
    assert r_get.status_code == 403
    assert r_put.status_code == 403


async def test_probar_envia_correo_de_verdad_al_doble_de_smtp(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-admin5", correo="admin5@demo.test", rol_global=RolGlobal.ADMIN)
    r = await client.post("/v1/config/smtp/probar", json={**_BODY, "correo_destino": "yo@example.com"}, headers={"Authorization": "Bearer uid-admin5"})
    assert r.status_code == 200
    assert r.json() == {"enviado": True}
    assert len(_FakeSmtp.instancias) == 1
    assert _FakeSmtp.instancias[0].mensajes[0]["To"] == "yo@example.com"


async def test_probar_smtp_error_502(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-admin6", correo="admin6@demo.test", rol_global=RolGlobal.ADMIN)
    _FakeSmtp.fallar_login = True
    r = await client.post("/v1/config/smtp/probar", json={**_BODY, "correo_destino": "yo@example.com"}, headers={"Authorization": "Bearer uid-admin6"})
    assert r.status_code == 502
    assert r.json()["error"]["codigo"] == "SMTP_ERROR"
