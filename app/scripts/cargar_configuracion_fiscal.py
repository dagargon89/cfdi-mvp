"""Carga un archivo de configuración fiscal (`config/fiscal/*.yaml`) a la base.

Lo que se carga queda **pendiente de confirmación**: un valor de `param_fiscal` sin
confirmar no calcula nada, por diseño (ver `app/services/configuracion_fiscal.py`). Este
script propone; confirmar es un acto humano y se hace desde la pantalla de configuración.

Es idempotente: volver a correrlo actualiza los renglones, no los duplica. Si al recargar
cambia el contenido de un renglón, su confirmación previa se limpia — un valor distinto es
un valor nuevo y necesita que alguien lo mire otra vez. Y no pisa una corrección hecha a
mano: la reporta y la deja como está, salvo que se pase `--forzar`.

Uso:
    python -m app.scripts.cargar_configuracion_fiscal config/fiscal/param_fiscal.yaml
    python -m app.scripts.cargar_configuracion_fiscal config/fiscal/empresa.yaml --empresa-id 1

Sale con código 1 si la validación falla, sin escribir nada: la carga entera va en una
sola transacción.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.db.session import SessionLocal
from app.services.configuracion_fiscal import ResultadoCarga, cargar_desde_yaml_detallado

# Las tablas cuyos renglones exigen confirmación humana antes de usarse en un cálculo.
# `tabla_vacaciones` no está: es el art. 76 de la LFT, dos columnas de enteros que se
# verifican de un vistazo contra la ley y no cambian desde la reforma de 2023.
_EXIGEN_CONFIRMACION = ("param_fiscal", "catalogo_percepcion_marca")


async def _cargar(ruta: Path, empresa_id: int | None, forzar: bool) -> ResultadoCarga:
    async with SessionLocal() as db:
        return await cargar_desde_yaml_detallado(db, ruta, empresa_id=empresa_id, forzar=forzar)


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga una semilla de configuración fiscal (queda sin confirmar).")
    parser.add_argument("ruta", help="Ruta del YAML, p. ej. config/fiscal/param_fiscal.yaml")
    parser.add_argument(
        "--empresa-id",
        type=int,
        default=None,
        help="Obligatorio para las secciones por empresa (map_departamento, map_concepto_provision, configuracion_empresa).",
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Pisa los renglones que fueron corregidos a mano (origen MANUAL). Sin esta bandera se omiten y se reportan.",
    )
    args = parser.parse_args()
    ruta = Path(args.ruta)
    empresa_id: int | None = args.empresa_id
    forzar: bool = args.forzar

    try:
        resultado = asyncio.run(_cargar(ruta, empresa_id, forzar))
    except ValueError as exc:
        print(f"No se cargó nada — la validación falló:\n  {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    resumen = resultado.filas
    if not resumen:
        print(f"{ruta}: el archivo no trae ninguna sección con datos. No se cargó nada.")
        return

    print(f"Cargado {ruta}:")
    for tabla in sorted(resumen):
        print(f"  {tabla}: {resumen[tabla]} renglón(es)")
    if resultado.omitidos:
        print(f"\n{len(resultado.omitidos)} renglón(es) NO se cargaron para no pisar una corrección manual:")
        for aviso in resultado.omitidos:
            print(f"  - {aviso}")
    if any(resumen.get(tabla) for tabla in _EXIGEN_CONFIRMACION):
        print(
            "\nPENDIENTE DE CONFIRMACIÓN: lo cargado NO se usa en ningún cálculo hasta que una\n"
            "persona lo confirme desde la pantalla de configuración. Hasta entonces los informes\n"
            "lo reportan como faltante, con su propuesta y su fuente."
        )


if __name__ == "__main__":
    main()
