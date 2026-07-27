"""doc 06 §2.3/§2.7 — Bitácora (RF-BIT-01): se registra junto con la operación sensible,
y el usuario de MySQL de la app no tiene UPDATE/DELETE sobre `bitacora` (A05, A09)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.models.bitacora import Bitacora
from app.models.enums import RolEmpresa, RolGlobal
from tests._certs import generar_fiel_prueba
from tests.factories import asignar_permiso, crear_empresa, crear_usuario

pytestmark = pytest.mark.asyncio


async def test_alta_efirma_registra_bitacora(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)
    cer, key, password = generar_fiel_prueba(rfc="EKU9003173C9")

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op"},
        files={"cer": ("test.cer", cer, "application/octet-stream"), "key": ("test.key", key, "application/octet-stream")},
        data={"password": password},
    )
    assert r.status_code == 201

    fila = await db.scalar(select(Bitacora).where(Bitacora.accion == "alta_efirma", Bitacora.entidad == f"empresa:{empresa.empresa_id}"))
    assert fila is not None
    assert fila.actor == "op@demo.test"
    assert fila.detalle is not None and "num_serie" in fila.detalle


async def test_password_nunca_aparece_en_bitacora(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op2", correo="op2@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)
    cer, key, password = generar_fiel_prueba(rfc="EKU9003173C9", password="una-password-muy-secreta")

    await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op2"},
        files={"cer": ("test.cer", cer, "application/octet-stream"), "key": ("test.key", key, "application/octet-stream")},
        data={"password": password},
    )

    filas = (await db.scalars(select(Bitacora))).all()
    for fila in filas:
        assert password not in str(fila.detalle)


@pytest.fixture()
async def engine_restringido(mysql_root_url: str, mysql_url: str) -> AsyncEngine:  # type: ignore[misc]
    """Crea un usuario MySQL con solo INSERT+SELECT sobre `bitacora` (RF-BIT-01) y
    devuelve un engine conectado con ese usuario — la app real correría con estos grants.
    Requiere la conexión root: ni el usuario de la app ni el de las demás pruebas
    (`hub_cfdi_test`) tienen (ni deberían tener) privilegio CREATE USER."""
    root_engine = create_async_engine(mysql_root_url)
    async with root_engine.begin() as conn:
        await conn.execute(text("DROP USER IF EXISTS 'bitacora_ro'@'%'"))
        await conn.execute(text("CREATE USER 'bitacora_ro'@'%' IDENTIFIED BY 'bitacora_ro_pw'"))
        await conn.execute(text("GRANT SELECT, INSERT ON hub_cfdi_test.bitacora TO 'bitacora_ro'@'%'"))
        await conn.execute(text("FLUSH PRIVILEGES"))
    await root_engine.dispose()

    restringido_url = mysql_url.replace("hub_cfdi_test:hub_cfdi_test@", "bitacora_ro:bitacora_ro_pw@")
    restringido = create_async_engine(restringido_url)
    yield restringido
    await restringido.dispose()


async def test_bitacora_es_insert_only_a_nivel_de_grants(engine_restringido: AsyncEngine, db: AsyncSession) -> None:
    db.add(Bitacora(actor="worker", accion="prueba", entidad="test:1", detalle=None))
    await db.commit()

    async with engine_restringido.connect() as conn:
        # INSERT+SELECT sí funcionan con estos grants.
        await conn.execute(text("INSERT INTO bitacora (actor, accion, entidad) VALUES ('worker', 'prueba2', 'test:2')"))
        await conn.commit()
        rows = (await conn.execute(text("SELECT COUNT(*) FROM bitacora"))).scalar()
        assert rows and rows >= 2

        # UPDATE/DELETE deben fallar por privilegios insuficientes.
        with pytest.raises(DBAPIError):
            await conn.execute(text("UPDATE bitacora SET actor = 'otro' WHERE entidad = 'test:1'"))
            await conn.commit()
