"""Fixtures compartidas — doc 06 §4.3: MySQL efímero (testcontainers), verificador de
Firebase falso (uids controlados, sin red real), KEK de prueba por corrida."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator, AsyncIterator

# Variables de entorno ANTES de importar cualquier módulo de app.* (Settings se lee al importar).
_kek_tmp = tempfile.NamedTemporaryFile(delete=False)
_kek_tmp.write(os.urandom(32))
_kek_tmp.close()
_storage_tmp = tempfile.mkdtemp(prefix="hub_cfdi_storage_")

os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost:0/placeholder")
os.environ.setdefault("REDIS_URL", "redis://localhost:0/0")
os.environ.setdefault("KEK_PATH", _kek_tmp.name)
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "/dev/null")
os.environ.setdefault("FIREBASE_PROJECT_ID", "test-project")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("STORAGE_ROOT", _storage_tmp)
os.environ.setdefault("SIGNING_SECRET", "test-signing-secret-not-for-production-use")
os.environ.setdefault("PUBLIC_BASE_URL", "http://test")

import pytest
import pytest_asyncio
from fastapi import HTTPException, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.mysql import MySqlContainer

import app.models  # noqa: F401 — registra todas las tablas en Base.metadata
from app.api import deps
from app.db.base import Base
from app.services.boveda import cargar_kek

cargar_kek.cache_clear()  # asegura que lea el KEK_PATH de prueba, no uno cacheado antes


@pytest.fixture(scope="session")
def mysql_container() -> AsyncIterator[MySqlContainer]:  # type: ignore[misc]
    with MySqlContainer(
        "mysql:8", username="hub_cfdi_test", password="hub_cfdi_test", root_password="hub_cfdi_test_root", dbname="hub_cfdi_test"
    ) as mysql:
        yield mysql


@pytest.fixture(scope="session")
def mysql_url(mysql_container: MySqlContainer) -> str:
    host = mysql_container.get_container_host_ip()
    port = mysql_container.get_exposed_port(3306)
    return f"mysql+asyncmy://hub_cfdi_test:hub_cfdi_test@{host}:{port}/hub_cfdi_test"


@pytest.fixture(scope="session")
def mysql_root_url(mysql_container: MySqlContainer) -> str:
    """Solo para pruebas que necesitan crear/otorgar privilegios (RF-BIT-01) —
    el usuario de la app nunca tiene estos permisos en ningún entorno real."""
    host = mysql_container.get_container_host_ip()
    port = mysql_container.get_exposed_port(3306)
    return f"mysql+asyncmy://root:hub_cfdi_test_root@{host}:{port}/hub_cfdi_test"


@pytest_asyncio.fixture(scope="session")
async def engine(mysql_url: str) -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(mysql_url)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture()
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Tablas frescas por test — el volumen de datos de prueba es mínimo, no vale la
    pena la complejidad de una transacción con rollback anidado por caso."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def _sin_notificaciones_reales(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ningún test dispara un envío real por Celery/SMTP (doc 07 Sprint 4, "límite de
    seguridad") — los tests que sí quieren verificar el encolado lo sobreescriben ellos
    mismos dentro del propio test (monkeypatch por test gana sobre este autouse)."""
    import app.services.notificaciones as notificaciones_service

    monkeypatch.setattr(notificaciones_service, "encolar_si_nuevo", lambda evento: None)


def _fake_verificar_id_token(authorization: str | None) -> str:
    """Firebase falso: el propio valor del Bearer ES el `firebase_uid` (sin red real)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Falta el encabezado Authorization: Bearer <uid>.")
    uid = authorization.removeprefix("Bearer ").strip()
    if uid == "invalido":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado.")
    return uid


@pytest_asyncio.fixture()
async def client(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    from app.main import app

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app.dependency_overrides[deps.get_db] = override_get_db
    monkeypatch.setattr(deps, "verificar_id_token", _fake_verificar_id_token)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
