"""Las 9 identidades contables del grupo B (§B-00 del documento fuente).

Son los totales que el complemento de Nómina 1.2 **declara** en sus encabezados,
recalculados desde la suma de sus propios nodos hijos. Un CFDI timbrado por el SAT las
cumple por construcción: si alguna falla sobre datos reales es un bug de nuestro ETL —un
nodo leído mal, un atributo confundido, un importe que se sobrescribe en vez de sumarse—,
nunca un dato malo del contribuyente.

Es la comprobación más fuerte que existe sobre la capa normalizada, y la única que detecta
que el ETL lee mal un nodo. Vive en `app/` y no en el script de verificación en vivo para
que tenga **dos** llamadores con una sola implementación:

- `tests/test_identidades_b00.py`, sobre XML sintéticos que pasan por el ETL completo. Es lo
  que mantiene estas identidades verdes en cada corrida de la suite; ocho informes más se van
  a construir sobre esta capa.
- `scripts/verificar_fase1.py`, sobre los CFDI reales de la empresa (spec §13, §14).

Las nueve, por comprobante:

1. `nomina.total_percepciones` = Σ (`importe_gravado` + `importe_exento`) de las percepciones.
2. `nomina.total_deducciones` = Σ `importe` de las deducciones.
3. `nomina.total_otros_pagos` = Σ `importe` de otros pagos.
4. `nomina_totales.total_gravado` = Σ `importe_gravado` de las percepciones.
5. `nomina_totales.total_exento` = Σ `importe_exento` de las percepciones.
6. `comprobante_detalle.subtotal` = Σ percepciones + Σ otros pagos.
7. `comprobante_detalle.descuento` = Σ deducciones.
8. `comprobantes.total` = `subtotal` − `descuento`.
9. `nomina_totales.total_impuestos_retenidos` = Σ deducciones de tipo `'002'` (ISR).

Un campo que el XML no trae (p. ej. `TotalImpuestosRetenidos` cuando no hubo ISR retenido)
llega como `None` y no se compara: no hay nada que cotejar y ausencia no es descuadre.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.nomina import Nomina, NominaDeduccion, NominaOtroPago, NominaPercepcion, NominaTotales

TOLERANCIA = Decimal("0.01")
"""Un centavo: el redondeo legítimo del timbrado, nunca un error de captura."""

CLAVE_TIPO_DEDUCCION_ISR = "002"
"""Clave del catálogo `c_TipoDeduccion` del ISR. Texto, nunca entero (regla dura del §5)."""

IDENTIDADES_POR_COMPROBANTE = 9


def _dec(valor: object) -> Decimal:
    """`func.sum` puede devolver `float`/`None` según el dialecto; siempre se compara como
    `Decimal` para no arrastrar imprecisión binaria a una tolerancia de centavos."""
    if valor is None:
        return Decimal("0")
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


@dataclass(slots=True)
class SumasNodos:
    """Los agregados recalculados desde los nodos hijos, no leídos de ningún encabezado."""

    percepciones: Decimal
    gravado: Decimal
    exento: Decimal
    deducciones: Decimal
    isr_retenido: Decimal
    otros_pagos: Decimal


async def sumas_de_nodos(db: AsyncSession, comprobante_id: int) -> SumasNodos:
    """Recalcula, desde los nodos hijos, cada agregado que el complemento de Nómina también
    declara en su encabezado — la base de las identidades."""
    percepciones = await db.scalar(
        select(func.sum(NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento)).where(
            NominaPercepcion.comprobante_id == comprobante_id
        )
    )
    gravado = await db.scalar(select(func.sum(NominaPercepcion.importe_gravado)).where(NominaPercepcion.comprobante_id == comprobante_id))
    exento = await db.scalar(select(func.sum(NominaPercepcion.importe_exento)).where(NominaPercepcion.comprobante_id == comprobante_id))
    deducciones = await db.scalar(select(func.sum(NominaDeduccion.importe)).where(NominaDeduccion.comprobante_id == comprobante_id))
    isr_retenido = await db.scalar(
        select(func.sum(NominaDeduccion.importe)).where(
            NominaDeduccion.comprobante_id == comprobante_id,
            NominaDeduccion.tipo_deduccion == CLAVE_TIPO_DEDUCCION_ISR,
        )
    )
    otros_pagos = await db.scalar(select(func.sum(NominaOtroPago.importe)).where(NominaOtroPago.comprobante_id == comprobante_id))
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
        return  # el atributo no vino en el XML: no hay nada que comparar
    if abs(declarado - calculado) > TOLERANCIA:
        fallas.append(f"{uuid_cfdi}: {nombre} declarado {declarado} ≠ calculado {calculado} (diff {abs(declarado - calculado)})")


async def verificar(db: AsyncSession, empresa_id: int) -> tuple[int, list[str]]:
    """Evalúa las 9 identidades sobre cada CFDI de nómina normalizado de la empresa.

    Devuelve `(comprobantes_evaluados, fallas)`. Una lista de fallas vacía con cero
    comprobantes evaluados **no** es un éxito: significa que no hay nada normalizado, y es el
    llamador quien decide si eso es un fallo de su escenario.
    """
    fallas: list[str] = []

    filas = (
        await db.execute(
            select(Comprobante, Nomina, NominaTotales, ComprobanteDetalle)
            .join(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
            .outerjoin(NominaTotales, NominaTotales.comprobante_id == Comprobante.comprobante_id)
            .outerjoin(ComprobanteDetalle, ComprobanteDetalle.comprobante_id == Comprobante.comprobante_id)
            .where(Comprobante.empresa_id == empresa_id)
            .order_by(Comprobante.comprobante_id)
        )
    ).all()

    for comprobante, nomina, totales, detalle in filas:
        uuid_cfdi = comprobante.uuid
        sumas = await sumas_de_nodos(db, comprobante.comprobante_id)

        # 1-3: los tres totales del encabezado de Nómina contra la suma de sus nodos.
        _checar(fallas, uuid_cfdi, "total_percepciones", nomina.total_percepciones, sumas.percepciones)
        _checar(fallas, uuid_cfdi, "total_deducciones", nomina.total_deducciones, sumas.deducciones)
        _checar(fallas, uuid_cfdi, "total_otros_pagos", nomina.total_otros_pagos, sumas.otros_pagos)

        # 4-5 y 9: el desglose de `nomina_totales` (fusión de `nomina_percepciones_tot` y
        # `nomina_deducciones_tot` del documento fuente) contra la suma por percepción.
        if totales is not None:
            _checar(fallas, uuid_cfdi, "total_gravado", totales.total_gravado, sumas.gravado)
            _checar(fallas, uuid_cfdi, "total_exento", totales.total_exento, sumas.exento)
            _checar(fallas, uuid_cfdi, "total_impuestos_retenidos", totales.total_impuestos_retenidos, sumas.isr_retenido)
        else:
            fallas.append(f"{uuid_cfdi}: no tiene fila en nomina_totales")

        # 6-8: el encabezado extendido (`comprobante_detalle`) y el total del CFDI
        # (`comprobantes.total`, tabla que ya existía y no se toca en el reproceso).
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

        # Identidad compuesta, además de las 9: el total del CFDI contra
        # percepciones + otros pagos − deducciones calculado directamente de los nodos, sin
        # pasar por el subtotal/descuento del encabezado.
        if comprobante.total is not None:
            neto = sumas.percepciones + sumas.otros_pagos - sumas.deducciones
            _checar(fallas, uuid_cfdi, "total del CFDI (= percepciones + otros − deducciones, de nodos)", Decimal(str(comprobante.total)), neto)

    return len(filas), fallas
