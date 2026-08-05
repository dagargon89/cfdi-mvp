# tests/test_modelos_cfdi_detalle.py
"""Las tablas de detalle del comprobante cuelgan de `comprobante_id` (spec §4.1) y
aceptan importes con 6 decimales sin perder precisión (spec §5, regla de Decimal)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cfdi_detalle import CfdiConcepto, CfdiConceptoImpuesto, CfdiRelacionado, ComprobanteDetalle
from tests import factories


async def test_detalle_guarda_encabezado_con_seis_decimales(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111")

    db.add(
        ComprobanteDetalle(
            comprobante_id=comprobante.comprobante_id,
            version="4.0",
            serie="A",
            fecha_timbrado=datetime(2026, 7, 1, 10, 0, 0),
            moneda="MXN",
            tipo_cambio=Decimal("1.000000"),
            subtotal=Decimal("8759.700000"),
            descuento=Decimal("0.000000"),
            xml_hash="a" * 64,
            etl_version=1,
        )
    )
    await db.commit()

    guardado = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante.comprobante_id))
    assert guardado is not None
    assert guardado.subtotal == Decimal("8759.700000")
    assert guardado.error_normalizacion is None


async def test_concepto_impuesto_conserva_tasa_y_clave_como_texto(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="22222222-2222-2222-2222-222222222222")

    concepto = CfdiConcepto(
        comprobante_id=comprobante.comprobante_id,
        num_linea=1,
        clave_prod_serv="84111506",
        cantidad=Decimal("1.000000"),
        clave_unidad="E48",
        descripcion="Servicios de facturación",
        valor_unitario=Decimal("7000.000000"),
        importe=Decimal("7000.000000"),
        descuento=Decimal("0.000000"),
        objeto_imp="02",
    )
    db.add(concepto)
    await db.flush()

    db.add(
        CfdiConceptoImpuesto(
            concepto_id=concepto.id,
            comprobante_id=comprobante.comprobante_id,
            naturaleza="T",
            impuesto="002",
            tipo_factor="Tasa",
            tasa_o_cuota=Decimal("0.080000"),
            base=Decimal("7000.000000"),
            importe=Decimal("560.000000"),
        )
    )
    db.add(
        CfdiRelacionado(
            comprobante_id=comprobante.comprobante_id,
            tipo_relacion="01",
            uuid_relacionado="33333333-3333-3333-3333-333333333333",
        )
    )
    await db.commit()

    impuesto = await db.scalar(select(CfdiConceptoImpuesto).where(CfdiConceptoImpuesto.concepto_id == concepto.id))
    assert impuesto is not None
    # La clave se conserva como texto: '002' no puede volverse 2.
    assert impuesto.impuesto == "002"
    assert impuesto.tasa_o_cuota == Decimal("0.080000")

    relacionado = await db.scalar(select(CfdiRelacionado).where(CfdiRelacionado.comprobante_id == comprobante.comprobante_id))
    assert relacionado is not None
    assert relacionado.tipo_relacion == "01"


async def test_borrar_comprobante_arrastra_el_detalle(db: AsyncSession) -> None:
    """`ON DELETE CASCADE`: el detalle nunca queda huérfano."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="44444444-4444-4444-4444-444444444444")
    db.add(ComprobanteDetalle(comprobante_id=comprobante.comprobante_id, version="4.0", xml_hash="b" * 64, etl_version=1))
    await db.commit()

    await db.delete(comprobante)
    await db.commit()

    assert await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante.comprobante_id)) is None
