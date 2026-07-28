"""Envío de notificaciones (RF-NOT-01) — `smtplib.SMTP` se mockea siempre (nunca red
real, doc 07 Sprint 4 "límite de seguridad"). La configuración SMTP vive en la BD
(`configuracion_smtp`), cifrada con la misma bóveda AES-256-GCM que la e.firma — la KEK de
prueba (`KEK_PATH`) ya la provee `tests/conftest.py`, real, no un doble."""

from __future__ import annotations

import smtplib

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.enums import TipoEvento
from app.repositories import eventos as eventos_repo
from app.repositories import notificaciones as notificaciones_repo
from app.services import notificaciones as notificaciones_service
from app.worker import tasks as worker_tasks
from tests.factories import crear_empresa


class _FakeSmtp:
    instancias: list["_FakeSmtp"] = []
    fallar: bool = False

    def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
        self.host = host
        self.port = port
        self.tls = False
        self.logueado: tuple[str, str] | None = None
        self.mensajes: list[object] = []
        _FakeSmtp.instancias.append(self)

    def __enter__(self) -> "_FakeSmtp":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def starttls(self) -> None:
        self.tls = True

    def login(self, usuario: str, password: str) -> None:
        self.logueado = (usuario, password)

    def send_message(self, mensaje: object) -> None:
        if _FakeSmtp.fallar:
            raise smtplib.SMTPException("intermitencia simulada")
        self.mensajes.append(mensaje)


@pytest.fixture(autouse=True)
def _smtp_fake(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSmtp]:
    _FakeSmtp.instancias = []
    _FakeSmtp.fallar = False
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtp)
    return _FakeSmtp


@pytest.fixture(autouse=True)
def _sesion_de_prueba_en_worker(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_tasks, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))


async def _guardar_config_smtp(db: AsyncSession, **overrides: object) -> None:
    valores: dict[str, object] = {
        "host": "smtp.test.local",
        "port": 587,
        "usuario": "no-reply@test.local",
        "remitente": "no-reply@test.local",
        "tls": True,
        "password_plano": "secreto",
    }
    valores.update(overrides)
    await notificaciones_service.guardar_config(db, **valores)  # type: ignore[arg-type]
    await db.commit()


_CREDENCIALES = notificaciones_service.SmtpCredenciales(
    host="smtp.test.local", port=587, usuario="no-reply@test.local", password="secreto", remitente="no-reply@test.local", tls=True
)


class _DestinoFake:
    def __init__(self, correo: str) -> None:
        self.correo = correo


class _EventoFake:
    tipo = TipoEvento.EFOS
    detalle = {"rfc": "EKU9003173C9", "situacion": "definitivo"}


def test_enviar_correo_arma_mensaje_y_usa_smtp() -> None:
    notificaciones_service.enviar_correo(_DestinoFake("contador@example.com"), _EventoFake(), _CREDENCIALES)

    assert len(_FakeSmtp.instancias) == 1
    smtp = _FakeSmtp.instancias[0]
    assert smtp.tls is True
    assert smtp.logueado == ("no-reply@test.local", "secreto")
    assert len(smtp.mensajes) == 1
    assert smtp.mensajes[0]["To"] == "contador@example.com"


async def test_guardar_config_cifra_password_y_resolver_la_descifra(db: AsyncSession) -> None:
    await _guardar_config_smtp(db)

    credenciales = await notificaciones_service.resolver_credenciales(db)
    assert credenciales == _CREDENCIALES


async def test_guardar_config_sin_password_conserva_la_anterior(db: AsyncSession) -> None:
    await _guardar_config_smtp(db)
    await _guardar_config_smtp(db, host="smtp.nuevo.local", password_plano=None)

    credenciales = await notificaciones_service.resolver_credenciales(db)
    assert credenciales.host == "smtp.nuevo.local"
    assert credenciales.password == "secreto"  # se conservó, no se perdió al no reteclearla


async def test_guardar_config_sin_password_ni_previa_levanta_error(db: AsyncSession) -> None:
    with pytest.raises(notificaciones_service.SmtpNoConfiguradoError):
        await _guardar_config_smtp(db, password_plano=None)


async def test_resolver_credenciales_sin_configuracion_levanta_error(db: AsyncSession) -> None:
    with pytest.raises(notificaciones_service.SmtpNoConfiguradoError):
        await notificaciones_service.resolver_credenciales(db)


async def test_enviar_notificacion_solo_a_destinos_suscritos(db: AsyncSession) -> None:
    await _guardar_config_smtp(db)
    empresa = await crear_empresa(db)
    evento = await eventos_repo.crear(db, empresa.empresa_id, TipoEvento.EFOS, {"rfc": "EKU9003173C9"})
    await notificaciones_repo.reemplazar_destinos(
        db, empresa.empresa_id, [("suscrito@x.com", ["efos"]), ("no_suscrito@x.com", ["cancelacion_tardia"])]
    )
    await db.commit()
    assert evento is not None

    resultado = await worker_tasks._enviar_notificacion_async(evento.evento_id)

    assert resultado == {"enviados": 1, "fallo_retryable": False}
    assert len(_FakeSmtp.instancias) == 1
    assert _FakeSmtp.instancias[0].mensajes[0]["To"] == "suscrito@x.com"


async def test_enviar_notificacion_sin_config_smtp_marca_fallido_no_retryable(db: AsyncSession) -> None:
    empresa = await crear_empresa(db)
    evento = await eventos_repo.crear(db, empresa.empresa_id, TipoEvento.EFOS, {"rfc": "EKU9003173C9"})
    await notificaciones_repo.reemplazar_destinos(db, empresa.empresa_id, [("destino@x.com", ["efos"])])
    await db.commit()
    assert evento is not None

    resultado = await worker_tasks._enviar_notificacion_async(evento.evento_id)

    assert resultado == {"enviados": 0, "fallo_retryable": False}  # nadie ha configurado el correo aún — reintentar no lo arregla
    assert _FakeSmtp.instancias == []


async def test_enviar_notificacion_smtp_falla_marca_fallido_y_retryable(db: AsyncSession) -> None:
    await _guardar_config_smtp(db)
    _FakeSmtp.fallar = True
    empresa = await crear_empresa(db)
    evento = await eventos_repo.crear(db, empresa.empresa_id, TipoEvento.EFOS, {"rfc": "EKU9003173C9"})
    await notificaciones_repo.reemplazar_destinos(db, empresa.empresa_id, [("destino@x.com", ["efos"])])
    await db.commit()
    assert evento is not None

    resultado = await worker_tasks._enviar_notificacion_async(evento.evento_id)

    assert resultado == {"enviados": 0, "fallo_retryable": True}
    assert await notificaciones_repo.ya_enviado(db, evento.evento_id, "destino@x.com") is False


async def test_enviar_notificacion_reintento_no_reenvia_a_quien_ya_recibio(db: AsyncSession) -> None:
    await _guardar_config_smtp(db)
    empresa = await crear_empresa(db)
    evento = await eventos_repo.crear(db, empresa.empresa_id, TipoEvento.EFOS, {"rfc": "EKU9003173C9"})
    await notificaciones_repo.reemplazar_destinos(db, empresa.empresa_id, [("destino@x.com", ["efos"])])
    await db.commit()
    assert evento is not None

    primero = await worker_tasks._enviar_notificacion_async(evento.evento_id)
    segundo = await worker_tasks._enviar_notificacion_async(evento.evento_id)

    assert primero["enviados"] == 1
    assert segundo["enviados"] == 0  # ya se le había enviado — no se duplica el correo
    assert len(_FakeSmtp.instancias) == 1


async def test_sin_destinos_suscritos_no_envia_nada(db: AsyncSession) -> None:
    await _guardar_config_smtp(db)
    empresa = await crear_empresa(db)
    evento = await eventos_repo.crear(db, empresa.empresa_id, TipoEvento.EFOS, {"rfc": "EKU9003173C9"})
    await db.commit()
    assert evento is not None

    resultado = await worker_tasks._enviar_notificacion_async(evento.evento_id)
    assert resultado == {"enviados": 0, "fallo_retryable": False}
    assert _FakeSmtp.instancias == []
