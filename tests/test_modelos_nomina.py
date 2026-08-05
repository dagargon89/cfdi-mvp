"""Complemento de Nómina 1.2 (spec §5.3).

Dos cosas que estas pruebas fijan a propósito, porque son los errores que el documento
fuente advierte: `antiguedad` se guarda como texto (viene como duración ISO 8601, p. ej.
'P663W') y el mismo `(tipo, clave)` puede repetirse en un solo CFDI, así que la tabla
NO lleva restricción de unicidad sobre esa combinación (B-02.R1).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nomina import (
    Nomina,
    NominaDeduccion,
    NominaIncapacidad,
    NominaOtroPago,
    NominaPercepcion,
    NominaReceptor,
    NominaTotales,
)
from tests import factories


async def test_nomina_completa_con_receptor_y_conceptos(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="77777777-7777-7777-7777-777777777777", tipo_comprobante="N"
    )
    cid = comprobante.comprobante_id

    db.add(
        Nomina(
            comprobante_id=cid,
            version_nomina="1.2",
            tipo_nomina="O",
            fecha_pago=date(2026, 6, 30),
            fecha_inicial_pago=date(2026, 6, 16),
            fecha_final_pago=date(2026, 6, 30),
            num_dias_pagados=Decimal("15.000"),
            total_percepciones=Decimal("9259.700000"),
            total_deducciones=Decimal("1091.100000"),
            total_otros_pagos=Decimal("0.000000"),
            registro_patronal="B5510768108",
        )
    )
    db.add(
        NominaReceptor(
            comprobante_id=cid,
            curp="MAOM800101HCHNRN01",
            nss="12345678901",
            fecha_inicio_rel_laboral=date(2013, 9, 1),
            antiguedad="P663W",
            tipo_contrato="01",
            sindicalizado="No",
            tipo_jornada="01",
            tipo_regimen="02",
            num_empleado="039",
            departamento="Dirección",
            puesto="Director",
            riesgo_puesto="1",
            periodicidad_pago="04",
            salario_base_cot_apor=Decimal("583.980000"),
            salario_diario_integrado=Decimal("607.340000"),
            clave_ent_fed="CHH",
        )
    )
    db.add(NominaTotales(comprobante_id=cid, total_sueldos=Decimal("8759.700000"), total_gravado=Decimal("8759.700000"), total_exento=Decimal("500.000000")))
    await db.commit()

    nomina = await db.scalar(select(Nomina).where(Nomina.comprobante_id == cid))
    assert nomina is not None
    assert nomina.num_dias_pagados == Decimal("15.000")

    receptor = await db.scalar(select(NominaReceptor).where(NominaReceptor.comprobante_id == cid))
    assert receptor is not None
    # Texto, nunca número: 'P663W' no es una cantidad de semanas parseable como int.
    assert receptor.antiguedad == "P663W"
    # Clave interna del patrón: '039' no puede volverse 39.
    assert receptor.num_empleado == "039"


async def test_mismo_tipo_y_clave_se_repite_en_un_comprobante(db: AsyncSession) -> None:
    """B-02.R1: el esquema Nómina 1.2 permite dos nodos con el mismo (tipo, clave) en un
    mismo CFDI. Si la tabla los rechazara, el ETL perdería importes en silencio."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="88888888-8888-8888-8888-888888888888", tipo_comprobante="N"
    )
    cid = comprobante.comprobante_id

    for importe in (Decimal("300.000000"), Decimal("450.000000")):
        db.add(
            NominaPercepcion(
                comprobante_id=cid,
                tipo_percepcion="019",
                clave="019",
                concepto="Horas extra",
                importe_gravado=importe,
                importe_exento=Decimal("0.000000"),
            )
        )
    await db.commit()

    total = await db.scalar(
        select(func.sum(NominaPercepcion.importe_gravado)).where(NominaPercepcion.comprobante_id == cid, NominaPercepcion.tipo_percepcion == "019")
    )
    assert total == Decimal("750.000000")


async def test_deduccion_otro_pago_e_incapacidad(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="99999999-9999-9999-9999-999999999999", tipo_comprobante="N"
    )
    cid = comprobante.comprobante_id

    db.add(NominaDeduccion(comprobante_id=cid, tipo_deduccion="002", clave="045", concepto="I.S.R. mes", importe=Decimal("591.100000")))
    db.add(
        NominaOtroPago(
            comprobante_id=cid,
            tipo_otro_pago="002",
            clave="035",
            concepto="Subs al Empleo mes",
            importe=Decimal("0.000000"),
            subsidio_causado=Decimal("0.000000"),
        )
    )
    db.add(NominaIncapacidad(comprobante_id=cid, dias_incapacidad=3, tipo_incapacidad="02", importe_monetario=Decimal("1200.000000")))
    await db.commit()

    deduccion = await db.scalar(select(NominaDeduccion).where(NominaDeduccion.comprobante_id == cid))
    assert deduccion is not None
    assert deduccion.tipo_deduccion == "002"
    incapacidad = await db.scalar(select(NominaIncapacidad).where(NominaIncapacidad.comprobante_id == cid))
    assert incapacidad is not None
    assert incapacidad.dias_incapacidad == 3
