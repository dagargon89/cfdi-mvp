"""Complemento de Pagos 2.0 (spec §5.2). Un REP con 1 pago que cubre 1 documento
produce una fila en `pago`, una en `pago_docto` y una en `pago_totales`."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pago import Pago, PagoDocto, PagoDoctoImpuesto, PagoTotales
from tests import factories


async def test_pago_con_documento_relacionado_e_impuestos(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="55555555-5555-5555-5555-555555555555", tipo_comprobante="P"
    )

    pago = Pago(
        comprobante_id=comprobante.comprobante_id,
        num_pago=1,
        fecha_pago=datetime(2026, 7, 22, 12, 0, 0),
        forma_de_pago_p="03",
        moneda_p="MXN",
        tipo_cambio_p=Decimal("1.000000"),
        monto=Decimal("10800.000000"),
        num_operacion="123456",
    )
    db.add(pago)
    await db.flush()

    docto = PagoDocto(
        pago_id=pago.id,
        comprobante_id=comprobante.comprobante_id,
        id_documento="66666666-6666-6666-6666-666666666666",
        serie="A",
        folio="1001",
        moneda_dr="MXN",
        equivalencia_dr=Decimal("1.0000000000"),
        num_parcialidad=1,
        imp_saldo_ant=Decimal("10800.000000"),
        imp_pagado=Decimal("10800.000000"),
        imp_saldo_insoluto=Decimal("0.000000"),
        objeto_imp_dr="02",
    )
    db.add(docto)
    await db.flush()

    db.add(
        PagoDoctoImpuesto(
            pago_docto_id=docto.id,
            comprobante_id=comprobante.comprobante_id,
            naturaleza="T",
            impuesto="002",
            tipo_factor="Tasa",
            tasa_o_cuota=Decimal("0.080000"),
            base=Decimal("10000.000000"),
            importe=Decimal("800.000000"),
        )
    )
    db.add(
        PagoTotales(
            comprobante_id=comprobante.comprobante_id,
            total_traslados_base_iva8=Decimal("10000.000000"),
            total_traslados_impuesto_iva8=Decimal("800.000000"),
            monto_total_pagos=Decimal("10800.000000"),
        )
    )
    await db.commit()

    guardado = await db.scalar(select(PagoDocto).where(PagoDocto.pago_id == pago.id))
    assert guardado is not None
    assert guardado.imp_pagado == Decimal("10800.000000")
    # `equivalencia_dr` necesita 10 decimales, no 6 (§2.5 del documento fuente).
    assert guardado.equivalencia_dr == Decimal("1.0000000000")

    totales = await db.scalar(select(PagoTotales).where(PagoTotales.comprobante_id == comprobante.comprobante_id))
    assert totales is not None
    assert totales.monto_total_pagos == Decimal("10800.000000")
    assert totales.total_traslados_base_iva16 is None  # no informado en este REP
