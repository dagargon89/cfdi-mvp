"""Verificación en vivo de la fase 1 contra los datos reales (spec §13, §14).

Comprueba las 9 identidades de B-00 (fuente: `Hub_CFDI_docs/00-fuentes/especificacion-
informes-cfdi.md`, sección "B-00 · Definiciones comunes al grupo") sobre los CFDI de
nómina ya normalizados, y que B-02 produce filas y columnas dinámicas consistentes con
esos mismos datos.

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
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.informes import b02_conceptos_patron as b02
from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.nomina import Nomina, NominaDeduccion, NominaOtroPago, NominaPercepcion, NominaTotales

EMPRESA_ID = 11
TOLERANCIA = Decimal("0.01")
CLAVE_TIPO_DEDUCCION_ISR = "002"


def _dec(valor: object) -> Decimal:
    """`func.sum` puede devolver `float`/`None` según el dialecto; siempre se compara
    como `Decimal` para no arrastrar imprecisión binaria a una tolerancia de centavos."""
    if valor is None:
        return Decimal("0")
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


@dataclass(slots=True)
class SumasNodos:
    percepciones: Decimal
    gravado: Decimal
    exento: Decimal
    deducciones: Decimal
    isr_retenido: Decimal
    otros_pagos: Decimal


async def _sumas_nodos(db: AsyncSession, comprobante_id: int) -> SumasNodos:
    """Recalcula, desde los nodos hijos, cada agregado que el complemento de Nómina
    también declara en su encabezado — la base de las identidades de B-00."""
    percepciones = await db.scalar(
        select(func.sum(NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento)).where(
            NominaPercepcion.comprobante_id == comprobante_id
        )
    )
    gravado = await db.scalar(
        select(func.sum(NominaPercepcion.importe_gravado)).where(NominaPercepcion.comprobante_id == comprobante_id)
    )
    exento = await db.scalar(
        select(func.sum(NominaPercepcion.importe_exento)).where(NominaPercepcion.comprobante_id == comprobante_id)
    )
    deducciones = await db.scalar(
        select(func.sum(NominaDeduccion.importe)).where(NominaDeduccion.comprobante_id == comprobante_id)
    )
    isr_retenido = await db.scalar(
        select(func.sum(NominaDeduccion.importe)).where(
            NominaDeduccion.comprobante_id == comprobante_id,
            NominaDeduccion.tipo_deduccion == CLAVE_TIPO_DEDUCCION_ISR,
        )
    )
    otros_pagos = await db.scalar(
        select(func.sum(NominaOtroPago.importe)).where(NominaOtroPago.comprobante_id == comprobante_id)
    )
    return SumasNodos(
        percepciones=_dec(percepciones),
        gravado=_dec(gravado),
        exento=_dec(exento),
        deducciones=_dec(deducciones),
        isr_retenido=_dec(isr_retenido),
        otros_pagos=_dec(otros_pagos),
    )


def _checar(fallas: list[str], uuid_cfdi: str, nombre: str, declarado: Decimal | None, calculado: Decimal) -> None:
    if declarado is None:
        # El campo del complemento no vino en el XML (p. ej. `TotalImpuestosRetenidos`
        # cuando no hubo ISR retenido). No es una falla: no hay nada que comparar.
        return
    if abs(declarado - calculado) > TOLERANCIA:
        fallas.append(f"{uuid_cfdi}: {nombre} declarado {declarado} ≠ calculado {calculado} (diff {abs(declarado - calculado)})")


async def _verificar_identidades_b00(db: AsyncSession) -> tuple[int, list[str]]:
    """Evalúa las 9 identidades del spec B-00 sobre cada CFDI de nómina normalizado.
    Devuelve `(comprobantes_evaluados, fallas)`."""
    fallas: list[str] = []

    filas = (
        await db.execute(
            select(Comprobante, Nomina, NominaTotales, ComprobanteDetalle)
            .join(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
            .outerjoin(NominaTotales, NominaTotales.comprobante_id == Comprobante.comprobante_id)
            .outerjoin(ComprobanteDetalle, ComprobanteDetalle.comprobante_id == Comprobante.comprobante_id)
            .where(Comprobante.empresa_id == EMPRESA_ID)
            .order_by(Comprobante.comprobante_id)
        )
    ).all()

    print(f"CFDI de nómina normalizados: {len(filas)}")
    if not filas:
        print("FALLA: no hay nóminas normalizadas; ¿corrió el reproceso (normalizacion_lote.normalizar_lote)?")
        return 0, ["no hay CFDI de nómina normalizados"]

    for comprobante, nomina, totales, detalle in filas:
        cid = comprobante.comprobante_id
        uuid_cfdi = comprobante.uuid
        sumas = await _sumas_nodos(db, cid)

        # 1-3: los tres totales del encabezado de Nómina contra la suma de sus nodos.
        _checar(fallas, uuid_cfdi, "total_percepciones", nomina.total_percepciones, sumas.percepciones)
        _checar(fallas, uuid_cfdi, "total_deducciones", nomina.total_deducciones, sumas.deducciones)
        _checar(fallas, uuid_cfdi, "total_otros_pagos", nomina.total_otros_pagos, sumas.otros_pagos)

        # 4-5: el desglose gravado/exento de `nomina_totales` (fusión de
        # `nomina_percepciones_tot` del documento fuente) contra la suma por percepción.
        if totales is not None:
            _checar(fallas, uuid_cfdi, "total_gravado", totales.total_gravado, sumas.gravado)
            _checar(fallas, uuid_cfdi, "total_exento", totales.total_exento, sumas.exento)
            # 9: ISR retenido (`nomina_deducciones_tot` del documento fuente).
            _checar(fallas, uuid_cfdi, "total_impuestos_retenidos", totales.total_impuestos_retenidos, sumas.isr_retenido)
        else:
            fallas.append(f"{uuid_cfdi}: no tiene fila en nomina_totales")

        # 6-8: el encabezado extendido (`comprobante_detalle`) y el total del CFDI
        # (`comprobantes.total`, tabla que ya existía y no se toca en este reproceso).
        if detalle is not None:
            _checar(fallas, uuid_cfdi, "subtotal (= percepciones + otros pagos)", detalle.subtotal, sumas.percepciones + sumas.otros_pagos)
            _checar(fallas, uuid_cfdi, "descuento (= deducciones)", detalle.descuento, sumas.deducciones)
            if detalle.subtotal is not None and detalle.descuento is not None and comprobante.total is not None:
                _checar(
                    fallas,
                    uuid_cfdi,
                    "total del CFDI (= subtotal − descuento)",
                    Decimal(str(comprobante.total)),
                    detalle.subtotal - detalle.descuento,
                )
        else:
            fallas.append(f"{uuid_cfdi}: no tiene fila en comprobante_detalle")

        # Identidad compuesta que exige el brief de la tarea 15, además de las 9 de arriba:
        # el total del CFDI contra percepciones + otros pagos − deducciones calculado
        # directamente de los nodos (sin pasar por subtotal/descuento del encabezado).
        if comprobante.total is not None:
            neto = sumas.percepciones + sumas.otros_pagos - sumas.deducciones
            _checar(fallas, uuid_cfdi, "total del CFDI (= percepciones + otros − deducciones, de nodos)", Decimal(str(comprobante.total)), neto)

    return len(filas), fallas


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
        print(f"Identidades de B-00 evaluadas: {comprobantes_normalizados * 9} (9 por CFDI)")

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
