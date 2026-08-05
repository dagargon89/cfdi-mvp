"""ETL del complemento de Pagos 2.0. El grano de A-05 es una fila por documento pagado
en cada pago, así que el ETL debe conservar la jerarquía pago → documento → impuestos."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.services import normalizacion
from tests import fixtures_cfdi


def test_normaliza_pago_con_documento_e_impuestos() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_pago())

    assert len(datos.pagos) == 1
    pago = datos.pagos[0]
    assert pago.num_pago == 1
    assert pago.fecha_pago == datetime(2026, 7, 22, 12, 0, 0)
    assert pago.forma_de_pago_p == "03"
    assert pago.moneda_p == "MXN"
    assert pago.monto == Decimal("17393.40")
    assert pago.num_operacion == "123456"

    assert len(pago.doctos) == 1
    docto = pago.doctos[0]
    assert docto.id_documento == "66666666-6666-6666-6666-666666666666"
    assert docto.num_parcialidad == 1
    assert docto.imp_pagado == Decimal("17393.40")
    assert docto.imp_saldo_insoluto == Decimal("0.00")
    assert docto.equivalencia_dr == Decimal("1")

    assert len(docto.impuestos) == 1
    impuesto = docto.impuestos[0]
    assert impuesto.naturaleza == "T"
    assert impuesto.impuesto == "002"
    assert impuesto.tasa_o_cuota == Decimal("0.080000")
    assert impuesto.base == Decimal("16105.00")
    assert impuesto.importe == Decimal("1288.40")


def test_normaliza_totales_del_rep() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_pago())

    assert datos.pago_totales is not None
    totales = datos.pago_totales
    assert totales.total_traslados_base_iva8 == Decimal("16105.00")
    assert totales.total_traslados_impuesto_iva8 == Decimal("1288.40")
    assert totales.monto_total_pagos == Decimal("17393.40")
    # No informado ≠ cero: el REP real de la empresa 11 solo trae los campos del 8 %.
    assert totales.total_traslados_base_iva16 is None


def test_numera_los_pagos_en_orden() -> None:
    """`num_pago` es derivado: la posición del nodo (§2.5 del fuente)."""
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_pago())
    assert [p.num_pago for p in datos.pagos] == [1]
