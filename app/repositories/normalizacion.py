"""Persistencia del árbol que devuelve `app/services/normalizacion.py` (spec §6.2).

Idempotencia por borrar-e-insertar acotado a `comprobante_id`: reprocesar un comprobante
nunca duplica hijos y nunca toca los de otro comprobante. Todo ocurre en la transacción
del caller — este módulo no hace `commit`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cfdi_detalle import CfdiConcepto, CfdiConceptoImpuesto, CfdiRelacionado, ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.nomina import (
    Nomina,
    NominaDeduccion,
    NominaIncapacidad,
    NominaOtroPago,
    NominaPercepcion,
    NominaReceptor,
    NominaTotales,
)
from app.models.pago import Pago, PagoDocto, PagoDoctoImpuesto, PagoTotales
from app.services.normalizacion import ETL_VERSION, DatosComprobante

# Hijos que se borran antes de reinsertar. `cfdi_concepto_impuesto` y `pago_docto*` caen
# por cascada de sus padres, pero se listan explícitamente: depender de la cascada de
# MySQL para la idempotencia sería frágil si alguien cambia una FK.
_TABLAS_HIJAS = (
    CfdiConceptoImpuesto,
    CfdiConcepto,
    CfdiRelacionado,
    PagoDoctoImpuesto,
    PagoDocto,
    Pago,
    PagoTotales,
    NominaPercepcion,
    NominaDeduccion,
    NominaOtroPago,
    NominaIncapacidad,
    NominaTotales,
    NominaReceptor,
    Nomina,
)


async def necesita_normalizar(db: AsyncSession, comprobante_id: int, xml_hash: str) -> bool:
    """`False` solo si este XML exacto ya se procesó con la versión vigente del ETL —
    incluidos los que fallaron (su error ya quedó registrado, no se reintenta en bucle)."""
    fila = (
        await db.execute(
            select(ComprobanteDetalle.xml_hash, ComprobanteDetalle.etl_version).where(ComprobanteDetalle.comprobante_id == comprobante_id)
        )
    ).first()
    if fila is None:
        return True
    return not (fila.xml_hash == xml_hash and fila.etl_version == ETL_VERSION)


async def _limpiar_hijos(db: AsyncSession, comprobante_id: int) -> None:
    for tabla in _TABLAS_HIJAS:
        await db.execute(delete(tabla).where(tabla.comprobante_id == comprobante_id))


async def _upsert_detalle(db: AsyncSession, comprobante_id: int, valores: dict[str, Any]) -> None:
    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante_id))
    if detalle is None:
        db.add(ComprobanteDetalle(comprobante_id=comprobante_id, **valores))
        return
    for campo, valor in valores.items():
        setattr(detalle, campo, valor)


async def escribir(db: AsyncSession, comprobante_id: int, datos: DatosComprobante, xml_hash: str) -> None:
    """Persiste el árbol completo. Limpia los hijos anteriores y borra cualquier
    `error_normalizacion` previo: si llegamos aquí, el XML se leyó bien."""
    await _limpiar_hijos(db, comprobante_id)

    enc = datos.encabezado
    await _upsert_detalle(
        db,
        comprobante_id,
        {
            "version": enc.version,
            "serie": enc.serie,
            "fecha_timbrado": enc.fecha_timbrado,
            "forma_pago": enc.forma_pago,
            "metodo_pago": enc.metodo_pago,
            "moneda": enc.moneda,
            "tipo_cambio": enc.tipo_cambio,
            "subtotal": enc.subtotal,
            "descuento": enc.descuento,
            "lugar_expedicion": enc.lugar_expedicion,
            "exportacion": enc.exportacion,
            "regimen_emisor": enc.regimen_emisor,
            "nombre_receptor": enc.nombre_receptor,
            "domicilio_receptor": enc.domicilio_receptor,
            "regimen_receptor": enc.regimen_receptor,
            "uso_cfdi": enc.uso_cfdi,
            "no_certificado": enc.no_certificado,
            "no_certificado_sat": enc.no_certificado_sat,
            "xml_hash": xml_hash,
            "etl_version": ETL_VERSION,
            "normalizado_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "error_normalizacion": None,
        },
    )

    for concepto in datos.conceptos:
        fila = CfdiConcepto(
            comprobante_id=comprobante_id,
            num_linea=concepto.num_linea,
            clave_prod_serv=concepto.clave_prod_serv,
            no_identificacion=concepto.no_identificacion,
            cantidad=concepto.cantidad,
            clave_unidad=concepto.clave_unidad,
            unidad=concepto.unidad,
            descripcion=concepto.descripcion,
            valor_unitario=concepto.valor_unitario,
            importe=concepto.importe,
            descuento=concepto.descuento,
            objeto_imp=concepto.objeto_imp,
        )
        db.add(fila)
        await db.flush()  # necesitamos `fila.id` para los impuestos de la línea
        for impuesto in concepto.impuestos:
            db.add(
                CfdiConceptoImpuesto(
                    concepto_id=fila.id,
                    comprobante_id=comprobante_id,
                    naturaleza=impuesto.naturaleza,
                    impuesto=impuesto.impuesto,
                    tipo_factor=impuesto.tipo_factor,
                    tasa_o_cuota=impuesto.tasa_o_cuota,
                    base=impuesto.base,
                    importe=impuesto.importe,
                )
            )

    for relacionado in datos.relacionados:
        db.add(
            CfdiRelacionado(
                comprobante_id=comprobante_id,
                tipo_relacion=relacionado.tipo_relacion,
                uuid_relacionado=relacionado.uuid_relacionado,
            )
        )

    for pago in datos.pagos:
        fila_pago = Pago(
            comprobante_id=comprobante_id,
            num_pago=pago.num_pago,
            fecha_pago=pago.fecha_pago,
            forma_de_pago_p=pago.forma_de_pago_p,
            moneda_p=pago.moneda_p,
            tipo_cambio_p=pago.tipo_cambio_p,
            monto=pago.monto,
            num_operacion=pago.num_operacion,
            rfc_emisor_cta_ord=pago.rfc_emisor_cta_ord,
            cta_ordenante=pago.cta_ordenante,
            rfc_emisor_cta_ben=pago.rfc_emisor_cta_ben,
            cta_beneficiario=pago.cta_beneficiario,
        )
        db.add(fila_pago)
        await db.flush()
        for docto in pago.doctos:
            fila_docto = PagoDocto(
                pago_id=fila_pago.id,
                comprobante_id=comprobante_id,
                id_documento=docto.id_documento,
                serie=docto.serie,
                folio=docto.folio,
                moneda_dr=docto.moneda_dr,
                equivalencia_dr=docto.equivalencia_dr,
                num_parcialidad=docto.num_parcialidad,
                imp_saldo_ant=docto.imp_saldo_ant,
                imp_pagado=docto.imp_pagado,
                imp_saldo_insoluto=docto.imp_saldo_insoluto,
                objeto_imp_dr=docto.objeto_imp_dr,
            )
            db.add(fila_docto)
            await db.flush()
            for impuesto in docto.impuestos:
                db.add(
                    PagoDoctoImpuesto(
                        pago_docto_id=fila_docto.id,
                        comprobante_id=comprobante_id,
                        naturaleza=impuesto.naturaleza,
                        impuesto=impuesto.impuesto,
                        tipo_factor=impuesto.tipo_factor,
                        tasa_o_cuota=impuesto.tasa_o_cuota,
                        base=impuesto.base,
                        importe=impuesto.importe,
                    )
                )

    if datos.pago_totales is not None:
        t = datos.pago_totales
        db.add(
            PagoTotales(
                comprobante_id=comprobante_id,
                total_traslados_base_iva16=t.total_traslados_base_iva16,
                total_traslados_impuesto_iva16=t.total_traslados_impuesto_iva16,
                total_traslados_base_iva8=t.total_traslados_base_iva8,
                total_traslados_impuesto_iva8=t.total_traslados_impuesto_iva8,
                total_traslados_base_iva0=t.total_traslados_base_iva0,
                total_traslados_impuesto_iva0=t.total_traslados_impuesto_iva0,
                total_traslados_base_iva_exento=t.total_traslados_base_iva_exento,
                total_retenciones_iva=t.total_retenciones_iva,
                total_retenciones_isr=t.total_retenciones_isr,
                total_retenciones_ieps=t.total_retenciones_ieps,
                monto_total_pagos=t.monto_total_pagos,
            )
        )

    if datos.nomina is not None:
        nom = datos.nomina
        cab = nom.cabecera
        db.add(
            Nomina(
                comprobante_id=comprobante_id,
                version_nomina=cab.version_nomina,
                tipo_nomina=cab.tipo_nomina,
                fecha_pago=cab.fecha_pago,
                fecha_inicial_pago=cab.fecha_inicial_pago,
                fecha_final_pago=cab.fecha_final_pago,
                num_dias_pagados=cab.num_dias_pagados,
                total_percepciones=cab.total_percepciones,
                total_deducciones=cab.total_deducciones,
                total_otros_pagos=cab.total_otros_pagos,
                registro_patronal=cab.registro_patronal,
                rfc_patron_origen=cab.rfc_patron_origen,
                origen_recurso=cab.origen_recurso,
                monto_recurso_propio=cab.monto_recurso_propio,
            )
        )
        r = nom.receptor
        db.add(
            NominaReceptor(
                comprobante_id=comprobante_id,
                curp=r.curp,
                nss=r.nss,
                fecha_inicio_rel_laboral=r.fecha_inicio_rel_laboral,
                antiguedad=r.antiguedad,
                tipo_contrato=r.tipo_contrato,
                sindicalizado=r.sindicalizado,
                tipo_jornada=r.tipo_jornada,
                tipo_regimen=r.tipo_regimen,
                num_empleado=r.num_empleado,
                departamento=r.departamento,
                puesto=r.puesto,
                riesgo_puesto=r.riesgo_puesto,
                periodicidad_pago=r.periodicidad_pago,
                banco=r.banco,
                cuenta_bancaria=r.cuenta_bancaria,
                salario_base_cot_apor=r.salario_base_cot_apor,
                salario_diario_integrado=r.salario_diario_integrado,
                clave_ent_fed=r.clave_ent_fed,
            )
        )
        tot = nom.totales
        db.add(
            NominaTotales(
                comprobante_id=comprobante_id,
                total_sueldos=tot.total_sueldos,
                total_separacion_indemnizacion=tot.total_separacion_indemnizacion,
                total_jubilacion_pension_retiro=tot.total_jubilacion_pension_retiro,
                total_gravado=tot.total_gravado,
                total_exento=tot.total_exento,
                total_otras_deducciones=tot.total_otras_deducciones,
                total_impuestos_retenidos=tot.total_impuestos_retenidos,
            )
        )
        for percepcion in nom.percepciones:
            db.add(
                NominaPercepcion(
                    comprobante_id=comprobante_id,
                    tipo_percepcion=percepcion.tipo_percepcion,
                    clave=percepcion.clave,
                    concepto=percepcion.concepto,
                    importe_gravado=percepcion.importe_gravado,
                    importe_exento=percepcion.importe_exento,
                )
            )
        for deduccion in nom.deducciones:
            db.add(
                NominaDeduccion(
                    comprobante_id=comprobante_id,
                    tipo_deduccion=deduccion.tipo_deduccion,
                    clave=deduccion.clave,
                    concepto=deduccion.concepto,
                    importe=deduccion.importe,
                )
            )
        for otro in nom.otros_pagos:
            db.add(
                NominaOtroPago(
                    comprobante_id=comprobante_id,
                    tipo_otro_pago=otro.tipo_otro_pago,
                    clave=otro.clave,
                    concepto=otro.concepto,
                    importe=otro.importe,
                    subsidio_causado=otro.subsidio_causado,
                    saldo_a_favor=otro.saldo_a_favor,
                    anio=otro.anio,
                    remanente_sal_fav=otro.remanente_sal_fav,
                )
            )
        for incapacidad in nom.incapacidades:
            db.add(
                NominaIncapacidad(
                    comprobante_id=comprobante_id,
                    dias_incapacidad=incapacidad.dias_incapacidad,
                    tipo_incapacidad=incapacidad.tipo_incapacidad,
                    importe_monetario=incapacidad.importe_monetario,
                )
            )

    await db.flush()


async def registrar_error(db: AsyncSession, comprobante_id: int, xml_hash: str, mensaje: str) -> None:
    """Deja constancia del fallo con el hash del XML que lo produjo, para que el
    pre-vuelo no lo reintente en cada corrida (spec §6.2).

    A propósito **no** llama a `_limpiar_hijos`: si este comprobante ya se había
    normalizado con éxito antes (y ahora, por ejemplo, cambió el XML en disco o subió
    `ETL_VERSION`, se reintentó y el parseo falló), sus hijos de la corrida anterior
    — conceptos, nómina, pagos — siguen siendo el último estado bueno conocido y no
    hay ninguna razón para destruirlos. Ante un fallo se conserva ese estado y se marca
    el error; perder el detalle de un comprobante por un fallo transitorio es peor que
    conservar datos de una corrida anterior explícitamente marcados como sospechosos.
    Cualquier consumidor debe comprobar `error_normalizacion IS NULL` antes de confiar
    en la fila — eso ya era cierto para los campos de encabezado, que tampoco se
    limpiaban aquí."""
    await _upsert_detalle(
        db,
        comprobante_id,
        {
            "xml_hash": xml_hash,
            "etl_version": ETL_VERSION,
            "normalizado_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "error_normalizacion": mensaje[:500],
        },
    )
    await db.flush()


async def ids_pendientes(
    db: AsyncSession,
    empresa_id: int,
    *,
    solo_tipo: str | None = None,
    desde: date | None = None,
    hasta: date | None = None,
) -> list[int]:
    """Comprobantes de la empresa sin detalle, o con detalle de una versión vieja del ETL.
    No filtra por hash (eso requiere leer el XML); es el caller quien decide al leerlo."""
    consulta = (
        select(Comprobante.comprobante_id)
        .outerjoin(ComprobanteDetalle, ComprobanteDetalle.comprobante_id == Comprobante.comprobante_id)
        .where(
            Comprobante.empresa_id == empresa_id,
            Comprobante.xml_path.is_not(None),
            (ComprobanteDetalle.comprobante_id.is_(None)) | (ComprobanteDetalle.etl_version != ETL_VERSION),
        )
        .order_by(Comprobante.comprobante_id)
    )
    if solo_tipo is not None:
        consulta = consulta.where(Comprobante.tipo_comprobante == solo_tipo)
    if desde is not None:
        consulta = consulta.where(Comprobante.fecha_emision >= datetime.combine(desde, datetime.min.time()))
    if hasta is not None:
        consulta = consulta.where(Comprobante.fecha_emision <= datetime.combine(hasta, datetime.max.time()))
    return list((await db.execute(consulta)).scalars().all())
