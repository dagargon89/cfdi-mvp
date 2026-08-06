"""Verificación en vivo de la fase 1 contra los datos reales (spec §13, §14).

Comprueba las 9 identidades de B-00 (fuente: `Hub_CFDI_docs/00-fuentes/especificacion-
informes-cfdi.md`, sección "B-00 · Definiciones comunes al grupo") sobre los CFDI de
nómina ya normalizados, y que B-02 produce filas y columnas dinámicas consistentes con
esos mismos datos.

Las identidades **no se implementan aquí**: viven en `app/informes/identidades_b00.py` y
`tests/test_identidades_b00.py` las corre en cada pasada de la suite sobre XML sintéticos.
Este script es el otro llamador de esa misma implementación, el que la ejerce contra los
CFDI reales. Antes las identidades vivían solo en este archivo, fuera de `testpaths`, así
que nada las mantenía verdes.

Deliberadamente **no hardcodea** cuántas nóminas, filas o columnas dinámicas esperar: eso
quedaría obsoleto en cuanto se descargue más historia del SAT. Lo que sí es fijo son las
identidades contables — un XML timbrado por el SAT las cumple por construcción, así que
si alguna falla aquí es un bug de nuestro ETL, nunca un dato malo.

No imprime CURP, NSS ni cuenta bancaria: son datos personales de personas reales y esto
se corre en una terminal cuyo historial queda guardado.

Uso: `python scripts/verificar_fase1.py` (dentro del contenedor `api`, o con el `.venv`
del host apuntando a la misma base). Sale con código 1 si alguna comprobación falla.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.informes import b02_conceptos_patron as b02
from app.informes import identidades_b00

EMPRESA_ID = 11


async def _verificar_identidades_b00(db: AsyncSession) -> tuple[int, list[str]]:
    """Corre las identidades del módulo compartido y las reporta por consola."""
    v = await identidades_b00.verificar(db, EMPRESA_ID)

    print(f"CFDI de nómina normalizados: {v.comprobantes}")
    if not v.comprobantes:
        print("FALLA: no hay nóminas normalizadas; ¿corrió el reproceso (normalizacion_lote.normalizar_lote)?")
        return 0, ["no hay CFDI de nómina normalizados"]

    # `cotejos` es lo que hace auditable a la propia verificación: sin él, "cero fallas" no
    # distingue entre "todo cuadra" y "no se comprobó nada". Se imprime el número real, no el
    # teórico: un atributo ausente en el XML no se compara y por tanto no cuenta.
    print(f"Cotejos ejecutados: {v.cotejos} (máximo {identidades_b00.COTEJOS_POR_COMPROBANTE_COMPLETO} por CFDI)")
    if v.cotejos < v.comprobantes * identidades_b00.IDENTIDADES_POR_COMPROBANTE:
        print(
            f"AVISO: se esperaban al menos {v.comprobantes * identidades_b00.IDENTIDADES_POR_COMPROBANTE} cotejos. "
            "Algún atributo del complemento no vino en el XML; revisa qué CFDI y por qué."
        )

    return v.comprobantes, v.fallas


async def _verificar_b02(db: AsyncSession, comprobantes_normalizados: int) -> list[str]:
    fallas: list[str] = []

    resultado = await b02.consultar(
        db,
        EMPRESA_ID,
        b02.Parametros(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 12, 31)),
    )
    dinamicas = [c.titulo for c in resultado.columnas if b02.SEPARADOR_ETIQUETA in c.titulo]
    print(f"\nB-02: {len(resultado.filas)} filas, {len(resultado.columnas)} columnas totales, {len(dinamicas)} columnas dinámicas, {len(resultado.banderas)} banderas")
    print("Conceptos detectados (naturaleza¦tipo¦clave¦concepto):")
    for titulo in dinamicas:
        print("  ", titulo)

    if len(resultado.filas) != comprobantes_normalizados:
        fallas.append(
            f"B-02 devolvió {len(resultado.filas)} filas para {comprobantes_normalizados} CFDI de nómina normalizados en el rango 2026-01-01/2026-12-31"
        )
    if not dinamicas:
        fallas.append("B-02 no produjo ninguna columna dinámica; ¿hay datos en nomina_percepcion/deduccion/otro_pago?")
    if not resultado.diccionario:
        fallas.append("B-02 no produjo entradas de Diccionario para las columnas dinámicas detectadas")

    # Caso real de colisión que B-02.R3 debe resolver: `099` como clave de deducción y de
    # otro pago a la vez ("Ajuste al neto" en ambas naturalezas). Si aparece, confirma que
    # el prefijo de naturaleza en la etiqueta evita que se confundan; si no aparece en este
    # rango de datos no es una falla — es informativo.
    claves_por_tipo: dict[str, set[str]] = {"P": set(), "O": set(), "D": set()}
    for titulo in dinamicas:
        partes = titulo.split(b02.SEPARADOR_ETIQUETA)
        if len(partes) >= 3:
            claves_por_tipo.setdefault(partes[0], set()).add(partes[2])
    colisiones = claves_por_tipo["D"] & claves_por_tipo["O"]
    if colisiones:
        print(f"Claves compartidas entre deducción y otro pago (naturaleza distinta, R3 en acción): {sorted(colisiones)}")

    if resultado.banderas:
        print("\nBanderas de B-02:")
        for bandera in resultado.banderas:
            print(f"  [{bandera.severidad}] {bandera.clave} · {bandera.ambito} · {bandera.mensaje}")
        if any(bandera.clave == "TOTALES_DESCUADRADOS" for bandera in resultado.banderas):
            fallas.append(
                "B-02 emitió TOTALES_DESCUADRADOS sobre CFDI reales timbrados por el SAT: es un bug del ETL, no un hallazgo del informe"
            )
    else:
        print("\nB-02 no emitió banderas.")

    return fallas


async def main() -> int:
    async with SessionLocal() as db:
        comprobantes_normalizados, fallas_b00 = await _verificar_identidades_b00(db)
        print(f"Identidades de B-00 por CFDI: {identidades_b00.IDENTIDADES_POR_COMPROBANTE}")

        fallas_b02 = await _verificar_b02(db, comprobantes_normalizados)

    fallas = fallas_b00 + fallas_b02
    if fallas:
        print("\nFALLAS:")
        for falla in fallas:
            print("  -", falla)
        return 1
    print("\nTodas las comprobaciones pasaron.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
