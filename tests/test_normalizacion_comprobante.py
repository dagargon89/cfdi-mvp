"""ETL puro del encabezado y el cuerpo del comprobante (spec §6.1).

`normalizar` no toca la BD: recibe bytes y devuelve dataclasses. Eso es lo que la hace
probable a fondo sin contenedores.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.services import normalizacion
from tests import fixtures_cfdi


def test_normaliza_encabezado_de_ingreso() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_ingreso())

    enc = datos.encabezado
    assert enc.version == "4.0"
    assert enc.serie == "A"
    assert enc.fecha_timbrado == datetime(2026, 7, 1, 10, 5, 0)
    assert enc.moneda == "MXN"
    assert enc.tipo_cambio == Decimal("1")
    assert enc.subtotal == Decimal("7000.00")
    # `Descuento` ausente en el XML se normaliza a cero (§2.1 del fuente).
    assert enc.descuento == Decimal("0")
    assert enc.metodo_pago == "PUE"
    assert enc.forma_pago == "03"
    assert enc.regimen_emisor == "601"
    assert enc.regimen_receptor == "616"
    assert enc.uso_cfdi == "G03"
    assert enc.lugar_expedicion == "31000"
    assert enc.no_certificado_sat == "00001000000504465028"


def test_normaliza_concepto_con_impuesto_por_linea() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_ingreso())

    assert len(datos.conceptos) == 1
    concepto = datos.conceptos[0]
    assert concepto.num_linea == 1
    assert concepto.clave_prod_serv == "84111506"
    assert concepto.importe == Decimal("7000.00")
    assert concepto.descuento == Decimal("0")
    assert concepto.objeto_imp == "02"

    assert len(concepto.impuestos) == 1
    impuesto = concepto.impuestos[0]
    assert impuesto.naturaleza == "T"
    # Clave de catálogo como texto: '002', no 2.
    assert impuesto.impuesto == "002"
    assert impuesto.tipo_factor == "Tasa"
    assert impuesto.tasa_o_cuota == Decimal("0.080000")
    assert impuesto.base == Decimal("7000.00")
    assert impuesto.importe == Decimal("560.00")


def test_normaliza_varios_relacionados_con_distinto_tipo() -> None:
    """En CFDI 4.0 puede haber varios nodos `CfdiRelacionados` con distinto `TipoRelacion`
    en el mismo comprobante (§2.4 del fuente)."""
    xml = fixtures_cfdi.cfdi_ingreso(
        relacionados_xml=(
            fixtures_cfdi.relacionados("01", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
            + fixtures_cfdi.relacionados("04", "cccccccc-cccc-cccc-cccc-cccccccccccc")
        )
    )
    datos = normalizacion.normalizar(xml)

    pares = sorted((r.tipo_relacion, r.uuid_relacionado) for r in datos.relacionados)
    assert pares == [
        ("01", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"),
        ("01", "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"),
        ("04", "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"),
    ]


def test_sin_complemento_de_nomina_ni_pagos() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_ingreso())
    assert datos.nomina is None
    assert datos.pagos == []
    assert datos.pago_totales is None


def test_hash_es_estable_y_sensible_al_contenido() -> None:
    a = fixtures_cfdi.cfdi_ingreso()
    b = fixtures_cfdi.cfdi_ingreso(total="7561.00")
    assert normalizacion.hash_xml(a) == normalizacion.hash_xml(a)
    assert normalizacion.hash_xml(a) != normalizacion.hash_xml(b)
    assert len(normalizacion.hash_xml(a)) == 64
