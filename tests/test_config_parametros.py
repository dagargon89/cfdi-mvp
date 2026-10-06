"""GET /v1/config/parametros — los parámetros operativos que la interfaz necesita leer.

Antes de este endpoint, `listarConfiguracion` del frontend no existía en el cliente real y lo
servía **el doble de pruebas** (`client.ts` mezcla `{ ...apiMock, ...apiHttp }`). Cuatro pantallas
—Tablero, Empresas, e.firma y Descargas— leían valores inventados en producción: la vista previa
del troceo prometía ventanas de 12 meses mientras el backend troceaba en 2.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RolGlobal
from app.repositories import configuracion as config_repo
from tests.factories import crear_usuario

pytestmark = pytest.mark.asyncio


def _por_clave(cuerpo: list[dict[str, str]]) -> dict[str, str]:
    return {item["clave"]: item["valor"] for item in cuerpo}


async def test_devuelve_los_valores_reales_de_la_base(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-lee", correo="lee@x.mx", rol_global=RolGlobal.CONSULTA)
    await config_repo.establecer(db, "max_meses_ventana", 2)
    await config_repo.establecer(db, "umbral_vigencia_dias", 30)
    await db.commit()

    r = await client.get("/v1/config/parametros", headers={"Authorization": "Bearer uid-lee"})

    assert r.status_code == 200
    valores = _por_clave(r.json())
    assert valores["max_meses_ventana"] == "2"
    assert valores["umbral_vigencia_dias"] == "30"


async def test_sin_valor_en_la_base_devuelve_el_mismo_default_que_usa_el_backend(client: AsyncClient, db: AsyncSession) -> None:
    """La vista previa del troceo y el troceo real tienen que coincidir aunque la clave falte:
    `crear_descarga` usa 2 como default de `max_meses_ventana`, y la interfaz asumía 12."""
    await crear_usuario(db, uid="uid-lee-2", correo="lee2@x.mx", rol_global=RolGlobal.CONSULTA)

    r = await client.get("/v1/config/parametros", headers={"Authorization": "Bearer uid-lee-2"})

    assert r.status_code == 200
    assert _por_clave(r.json())["max_meses_ventana"] == "2"


async def test_solo_expone_las_claves_que_la_interfaz_necesita(client: AsyncClient, db: AsyncSession) -> None:
    """Lista blanca: lo que se guarde mañana en `configuracion` no se publica por accidente."""
    await crear_usuario(db, uid="uid-lee-3", correo="lee3@x.mx", rol_global=RolGlobal.CONSULTA)
    await config_repo.establecer(db, "sync_banxico_estado", {"fallo": "detalle interno"})
    await db.commit()

    r = await client.get("/v1/config/parametros", headers={"Authorization": "Bearer uid-lee-3"})

    assert set(_por_clave(r.json())) == {"max_meses_ventana", "umbral_vigencia_dias"}


async def test_exige_sesion(client: AsyncClient) -> None:
    r = await client.get("/v1/config/parametros")
    assert r.status_code == 401
