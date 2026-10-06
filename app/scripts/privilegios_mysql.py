"""Crea o actualiza el usuario de MySQL con el que corre la aplicación, con privilegios mínimos.

Runbook de producción, ítem A.4: la aplicación no debe conectarse con un usuario que puede hacerlo
todo. Este script deja a `hub_cfdi_app` con lo justo:

- `SELECT, INSERT, UPDATE, DELETE` sobre cada tabla del esquema;
- sobre `bitacora`, **solo `SELECT, INSERT`**: la bitácora es inmutable, y que la base lo imponga
  vale más que una convención del código, porque también resiste a un error o a un atacante que
  ya esté dentro de la aplicación;
- nada sobre `alembic_version`, y ningún privilegio de DDL: las migraciones las corre otro usuario.

Se ejecuta en el servicio `migrate` de `docker-compose.prod.yml`, **después** de
`alembic upgrade head`, con la conexión de administrador. Va después a propósito: los privilegios
se dan tabla por tabla (MySQL no permite quitar `UPDATE` de una sola tabla si se concedió sobre
todo el esquema), así que cada migración que agregue una tabla necesita volver a correrlo. Es
idempotente: revoca todo y vuelve a conceder lo exacto.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

USUARIO_APP = "hub_cfdi_app"
SOLO_LECTURA_E_INSERCION = frozenset({"bitacora"})
SIN_ACCESO = frozenset({"alembic_version"})

# La contraseña se interpola en `CREATE USER`, que MySQL no admite como sentencia preparada.
# En lugar de escapar, se restringe el alfabeto a uno que no necesita escape: lo que genera
# `deploy/generar_secretos.sh` siempre cumple.
_PASSWORD_VALIDA = re.compile(r"^[A-Za-z0-9._~-]{24,128}$")
_IDENTIFICADOR_VALIDO = re.compile(r"^[a-z0-9_]+$")


async def aplicar(password: str) -> list[tuple[str, str]]:
    if not _PASSWORD_VALIDA.fullmatch(password):
        raise SystemExit("MYSQL_APP_PASSWORD debe tener de 24 a 128 caracteres de [A-Za-z0-9._~-].")

    engine = create_async_engine(get_settings().database_url)
    concedidos: list[tuple[str, str]] = []
    try:
        async with engine.begin() as conn:
            esquema = (await conn.execute(text("SELECT DATABASE()"))).scalar_one()
            tablas = (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :esquema AND table_type = 'BASE TABLE' ORDER BY table_name"
                    ),
                    {"esquema": esquema},
                )
            ).scalars().all()

            cuenta = f"'{USUARIO_APP}'@'%'"
            await conn.execute(text(f"CREATE USER IF NOT EXISTS {cuenta} IDENTIFIED BY '{password}'"))
            await conn.execute(text(f"ALTER USER {cuenta} IDENTIFIED BY '{password}'"))
            await conn.execute(text(f"REVOKE ALL PRIVILEGES, GRANT OPTION FROM {cuenta}"))

            for tabla in tablas:
                if tabla in SIN_ACCESO:
                    continue
                if not _IDENTIFICADOR_VALIDO.fullmatch(tabla) or not _IDENTIFICADOR_VALIDO.fullmatch(esquema):
                    raise SystemExit(f"Nombre inesperado en el esquema: {esquema}.{tabla}")
                privilegios = "SELECT, INSERT" if tabla in SOLO_LECTURA_E_INSERCION else "SELECT, INSERT, UPDATE, DELETE"
                await conn.execute(text(f"GRANT {privilegios} ON `{esquema}`.`{tabla}` TO {cuenta}"))
                concedidos.append((tabla, privilegios))
    finally:
        await engine.dispose()
    return concedidos


def main() -> None:
    password = os.environ.get("MYSQL_APP_PASSWORD", "")
    concedidos = asyncio.run(aplicar(password))
    restringidas = [t for t, p in concedidos if t in SOLO_LECTURA_E_INSERCION]
    print(f"{USUARIO_APP}: privilegios aplicados sobre {len(concedidos)} tablas; solo lectura e inserción en: {', '.join(restringidas)}.")
    if not concedidos:
        print("AVISO: no se encontró ninguna tabla. ¿Corrió `alembic upgrade head` antes?", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
