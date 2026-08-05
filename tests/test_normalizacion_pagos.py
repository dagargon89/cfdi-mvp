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
    assert pago.monto == Decimal("10800.00")
    assert pago.num_operacion == "123456"

    assert len(pago.doctos) == 1
    docto = pago.doctos[0]
    # El fixture usa letras en minúsculas en `id_documento`: verifica que el ETL las
    # normaliza a mayúsculas (regla de dominio, no solo un valor que ya viniera así).
    assert docto.id_documento == "66666666-6666-6666-6666-6666666666AB"
    assert docto.num_parcialidad == 1
    assert docto.imp_pagado == Decimal("10800.00")
    assert docto.imp_saldo_insoluto == Decimal("0.00")
    assert docto.equivalencia_dr == Decimal("1")

    assert len(docto.impuestos) == 1
    impuesto = docto.impuestos[0]
    assert impuesto.naturaleza == "T"
    assert impuesto.impuesto == "002"
    assert impuesto.tasa_o_cuota == Decimal("0.080000")
    assert impuesto.base == Decimal("10000.00")
    assert impuesto.importe == Decimal("800.00")


def test_normaliza_totales_del_rep() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_pago())

    assert datos.pago_totales is not None
    totales = datos.pago_totales
    assert totales.total_traslados_base_iva8 == Decimal("10000.00")
    assert totales.total_traslados_impuesto_iva8 == Decimal("800.00")
    assert totales.monto_total_pagos == Decimal("10800.00")
    # No informado ≠ cero: el REP real de la empresa 11 solo trae los campos del 8 %.
    assert totales.total_traslados_base_iva16 is None


def test_numera_los_pagos_en_orden() -> None:
    """`num_pago` es derivado: la posición del nodo (§2.5 del fuente). Con un solo
    `Pago` la prueba pasaría aunque el código hardcodeara `num_pago=1`, así que el
    fixture trae un segundo `Pago` para forzar que la numeración sea posicional."""
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_pago(pagos_extra=fixtures_cfdi.pago_adicional()))
    assert [p.num_pago for p in datos.pagos] == [1, 2]
    assert datos.pagos[1].monto == Decimal("500.00")
    assert datos.pagos[1].num_operacion == "654321"


def test_impuestos_de_docto_incluye_retenciones() -> None:
    """`RetencionesDR` usa la misma forma de mapa con llave compuesta que `TrasladosDR`
    (verificado contra un REP real); esta prueba cubre esa rama de `_impuestos_de_docto`
    que el traslado por sí solo no ejercita."""
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_pago(retenciones_dr_xml=fixtures_cfdi.retencion_dr()))

    docto = datos.pagos[0].doctos[0]
    assert len(docto.impuestos) == 2
    retencion = next(i for i in docto.impuestos if i.naturaleza == "R")
    assert retencion.impuesto == "001"
    assert retencion.tasa_o_cuota == Decimal("0.100000")
    assert retencion.base == Decimal("10000.00")
    assert retencion.importe == Decimal("1000.00")
