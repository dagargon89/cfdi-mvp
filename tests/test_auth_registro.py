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


class _CuentaFake:
    def __init__(self, uid: str, email: str) -> None:
        self.uid = uid
        self.email = email


@pytest.fixture()
def firebase_reg(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    import app.api.v1.auth_bootstrap as mod
    import app.api.v1.usuarios as mod_usuarios

    estado: dict[str, object] = {"emails": {"uid-nuevo": "nuevo@example.com"}, "borradas": []}
    monkeypatch.setattr(mod, "firebase_app", lambda: None)
    monkeypatch.setattr(mod.firebase_auth, "get_user", lambda uid, **k: _CuentaFake(uid, estado["emails"].get(uid, f"{uid}@example.com")))  # type: ignore[attr-defined]
    monkeypatch.setattr(mod.firebase_auth, "delete_user", lambda uid, **k: estado["borradas"].append(uid))  # type: ignore[attr-defined]
    monkeypatch.setattr(mod_usuarios, "firebase_app", lambda: None)
    monkeypatch.setattr(mod_usuarios.firebase_auth, "delete_user", lambda uid, **k: estado["borradas"].append(uid))  # type: ignore[attr-defined]
    return estado


class _CredFake:
    """Doble simple de `SmtpCredenciales` — solo se usa como valor opaco que se pasa a
    `enviar_aviso_registro`, también mockeada; no necesita los campos reales."""


@pytest.fixture()
def smtp_espia(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], str]]:
    import app.api.v1.auth_bootstrap as mod

    envios: list[tuple[list[str], str]] = []

    async def _resolver_credenciales_fake(db: AsyncSession) -> _CredFake:
        return _CredFake()

    monkeypatch.setattr(mod.notificaciones, "resolver_credenciales", _resolver_credenciales_fake)
    monkeypatch.setattr(
        mod.notificaciones,
        "enviar_aviso_registro",
        lambda destinos, correo, nombre, cred: envios.append((destinos, correo)),
    )
    return envios


async def test_registro_crea_pendiente_consulta(
    client: AsyncClient, db: AsyncSession, firebase_reg: dict[str, object], smtp_espia: list[tuple[list[str], str]]
) -> None:
    # un admin aprobado para que haya destinatario del aviso
    await _usuario(db, uid="admin1", correo="admin@example.com", rol=RolGlobal.ADMIN)
    res = await client.post("/v1/auth/registro", json={"nombre": "Nuevo"}, headers={"Authorization": "Bearer uid-nuevo"})
    assert res.status_code == 201, res.text
    u = await usuarios_repo.por_correo(db, "nuevo@example.com")
    assert u is not None and u.rol_global == RolGlobal.CONSULTA and u.aprobado is False
    assert smtp_espia and smtp_espia[0][0] == ["admin@example.com"]  # se avisó al admin


async def test_registro_correo_de_firebase_no_del_body(client: AsyncClient, db: AsyncSession, firebase_reg: dict[str, object]) -> None:
    res = await client.post("/v1/auth/registro", json={"nombre": "X", "correo": "otro@intruso.com"}, headers={"Authorization": "Bearer uid-nuevo"})
    assert res.status_code == 201
    assert await usuarios_repo.por_correo(db, "nuevo@example.com") is not None  # ganó el de Firebase
    assert await usuarios_repo.por_correo(db, "otro@intruso.com") is None


async def test_registro_ya_existe_409(client: AsyncClient, db: AsyncSession, firebase_reg: dict[str, object]) -> None:
    await _usuario(db, uid="uid-nuevo", correo="nuevo@example.com", aprobado=False)
    res = await client.post("/v1/auth/registro", json={"nombre": "X"}, headers={"Authorization": "Bearer uid-nuevo"})
    assert res.status_code == 409
    assert res.json()["error"]["codigo"] == "YA_REGISTRADO"


async def test_registro_sin_smtp_no_falla(client: AsyncClient, db: AsyncSession, firebase_reg: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.auth_bootstrap as mod
    from app.services.notificaciones import SmtpNoConfiguradoError

    await _usuario(db, uid="admin1", correo="admin@example.com", rol=RolGlobal.ADMIN)

    async def _sin_smtp(db: AsyncSession) -> None:
        raise SmtpNoConfiguradoError("no config")

    monkeypatch.setattr(mod.notificaciones, "resolver_credenciales", _sin_smtp)
    res = await client.post("/v1/auth/registro", json={"nombre": "X"}, headers={"Authorization": "Bearer uid-nuevo"})
    assert res.status_code == 201  # el registro se completa aunque no haya SMTP


async def test_patch_aprobar_activa_acceso(client: AsyncClient, db: AsyncSession, firebase_reg: dict[str, object]) -> None:
    await _usuario(db, uid="admin1", correo="admin@example.com", rol=RolGlobal.ADMIN)
    pend = await _usuario(db, uid="uid-p", correo="p@example.com", aprobado=False)
    res = await client.patch(f"/v1/usuarios/{pend.usuario_id}", json={"aprobado": True}, headers={"Authorization": "Bearer admin1"})
    assert res.status_code == 200
    await db.refresh(pend)
    assert pend.aprobado is True


async def test_delete_rechaza_y_borra_firebase(client: AsyncClient, db: AsyncSession, firebase_reg: dict[str, object]) -> None:
    await _usuario(db, uid="admin1", correo="admin@example.com", rol=RolGlobal.ADMIN)
    pend = await _usuario(db, uid="uid-p", correo="p@example.com", aprobado=False)
    res = await client.delete(f"/v1/usuarios/{pend.usuario_id}", headers={"Authorization": "Bearer admin1"})
    assert res.status_code == 204
    assert await usuarios_repo.por_id(db, pend.usuario_id) is None
    assert firebase_reg["borradas"] == ["uid-p"]


async def test_delete_ultimo_admin_409(client: AsyncClient, db: AsyncSession, firebase_reg: dict[str, object]) -> None:
    admin = await _usuario(db, uid="admin1", correo="admin@example.com", rol=RolGlobal.ADMIN)
    res = await client.delete(f"/v1/usuarios/{admin.usuario_id}", headers={"Authorization": "Bearer admin1"})
    assert res.status_code == 409  # no puede eliminarse a sí mismo / último admin
