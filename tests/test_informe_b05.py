"""B-05 · Acumulado anual por empleado. Papel de trabajo del cálculo anual del ISR."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b05_acumulado_anual as b05
from app.models.cfdi_detalle import CfdiRelacionado
from app.models.enums import EstatusCfdi
from tests import factories
from tests.helpers_nomina import insertar_nomina


async def _empresa(db: AsyncSession) -> int:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    return empresa.empresa_id


def _fila(resultado: object, titulo: str, indice: int = 0) -> object:
    titulos = [c.titulo for c in resultado.columnas]  # type: ignore[attr-defined]
    return resultado.filas[indice][titulos.index(titulo)]  # type: ignore[attr-defined]


async def test_acumula_el_ejercicio_por_empleado(db: AsyncSession) -> None:
    eid = await _empresa(db)
    for sufijo, fin in (("1", date(2026, 6, 30)), ("2", date(2026, 7, 15))):
        await insertar_nomina(db, empresa_id=eid, uuid=f"1111111{sufijo}-1111-1111-1111-111111111111",
                              fecha_pago=fin, fecha_final_pago=fin, dias="15.000",
                              percepciones=[("001", "001", "Sueldo", "8000.00", "500.00")],
                              deducciones=[("002", "045", "ISR", "600.00"), ("001", "052", "IMSS", "200.00")],
                              total_percepciones="8500.00", total_deducciones="800.00", total="7700.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert len(resultado.filas) == 1
    assert _fila(resultado, "Núm. de CFDI") == 2
    assert _fila(resultado, "Días pagados del ejercicio") == Decimal("30.000")
    assert _fila(resultado, "Total percepciones") == Decimal("17000.00")
    assert _fila(resultado, "Total gravado") == Decimal("16000.00")
    assert _fila(resultado, "Total exento") == Decimal("1000.00")
    assert _fila(resultado, "ISR retenido") == Decimal("1200.00")
    assert _fila(resultado, "IMSS retenido") == Decimal("400.00")
    assert _fila(resultado, "Neto pagado") == Decimal("15400.00")


async def test_otro_ejercicio_no_entra(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="22222222-2222-2222-2222-222222222222",
                          fecha_pago=date(2025, 12, 31), fecha_final_pago=date(2025, 12, 31))
    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert resultado.filas == []


async def test_cancelado_sustituido_cuenta_una_vez(db: AsyncSession) -> None:
    """B-05.R1. Sin esto, un timbrado corregido duplica los ingresos anuales del empleado
    — un error grave en una constancia de percepciones."""
    eid = await _empresa(db)
    cid_malo = await insertar_nomina(db, empresa_id=eid, uuid="33333333-3333-3333-3333-333333333331",
                                     fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                                     estatus=EstatusCfdi.CANCELADO,
                                     percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                                     total_percepciones="8000.00", total="8000.00")
    cid_bueno = await insertar_nomina(db, empresa_id=eid, uuid="33333333-3333-3333-3333-333333333332",
                                      fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                                      percepciones=[("001", "001", "Sueldo", "8500.00", "0.00")],
                                      total_percepciones="8500.00", total="8500.00")
    # El sustituto declara la relación 04 hacia el cancelado.
    db.add(CfdiRelacionado(comprobante_id=cid_bueno, tipo_relacion="04",
                           uuid_relacionado="33333333-3333-3333-3333-333333333331"))
    await db.commit()
    assert cid_malo != cid_bueno

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert len(resultado.filas) == 1
    assert _fila(resultado, "Total percepciones") == Decimal("8500.00")
    assert _fila(resultado, "Núm. de CFDI") == 1


async def test_multi_patron(db: AsyncSession) -> None:
    """B-05.R3: el mismo empleado con dos patrones en el ejercicio hace el cálculo anual
    incompleto por construcción."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="44444444-4444-4444-4444-444444444441",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30))
    await insertar_nomina(db, empresa_id=eid, uuid="44444444-4444-4444-4444-444444444442",
                          fecha_pago=date(2026, 7, 15), fecha_final_pago=date(2026, 7, 15),
                          rfc_emisor="XAXX010101000")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert any(b.clave == "MULTI_PATRON" for b in resultado.banderas)


async def test_identidad_del_empleado_sale_del_cfdi_mas_reciente(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="55555555-5555-5555-5555-555555555551",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30), puesto="Auxiliar")
    await insertar_nomina(db, empresa_id=eid, uuid="55555555-5555-5555-5555-555555555552",
                          fecha_pago=date(2026, 7, 15), fecha_final_pago=date(2026, 7, 15), puesto="Coordinador")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Puesto") == "Coordinador"


async def test_sbc_y_sdi_son_promedios_ponderados_por_dias(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="66666666-6666-6666-6666-666666666661",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          dias="15.000", sbc="500.00", sdi="600.00")
    await insertar_nomina(db, empresa_id=eid, uuid="66666666-6666-6666-6666-666666666662",
                          fecha_pago=date(2026, 7, 15), fecha_final_pago=date(2026, 7, 15),
                          dias="5.000", sbc="700.00", sdi="800.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    # (500×15 + 700×5) / 20 = 550
    assert _fila(resultado, "SBC promedio ponderado") == Decimal("550")
    assert _fila(resultado, "SDI promedio ponderado") == Decimal("650")


async def test_desglose_de_deducciones(db: AsyncSession) -> None:
    """Columnas 18 a 20: fondo de ahorro (004), Infonavit (009) y el resto."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="77777777-7777-7777-7777-777777777777",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          deducciones=[("002", "045", "ISR", "600.00"), ("001", "052", "IMSS", "200.00"),
                                       ("004", "067", "Fondo ahorro", "300.00"),
                                       ("009", "014", "Infonavit", "400.00"),
                                       ("006", "090", "Incapacidad", "100.00")],
                          total_deducciones="1600.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Aportaciones a fondo de ahorro") == Decimal("300.00")
    assert _fila(resultado, "Descuentos Infonavit") == Decimal("400.00")
    # Otras = total − ISR − IMSS − 004 − 009 = 1600 − 600 − 200 − 300 − 400
    assert _fila(resultado, "Otras deducciones") == Decimal("100.00")


async def test_separacion_y_jubilacion(db: AsyncSession) -> None:
    """Columnas 12 y 13, de los totales del complemento."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="88888888-8888-8888-8888-888888888888",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          total_separacion="5000.00", total_jubilacion="3000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Ingreso por separación") == Decimal("5000.00")
    assert _fila(resultado, "Ingreso por jubilación") == Decimal("3000.00")


async def test_subsidio_causado_y_entregado(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="99999999-9999-9999-9999-999999999999",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          otros_pagos=[("002", "035", "Subsidio", "120.00", "200.00")])

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Subsidio causado") == Decimal("200.00")
    assert _fila(resultado, "Subsidio entregado en efectivo") == Decimal("120.00")


async def test_no_hay_columnas_de_alcance_diferido(db: AsyncSession) -> None:
    """La columna 11 y las 24-26 se declararon fuera de alcance: una columna vacía en un
    papel de trabajo fiscal es peor que su ausencia."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30))
    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    titulos = [c.titulo for c in resultado.columnas]
    assert not any("ordinario" in t.lower() for t in titulos)
    assert not any("teórico" in t.lower() or "teorico" in t.lower() for t in titulos)


async def test_curp_sensible_y_ejercicio_vacio(db: AsyncSession) -> None:
    eid = await _empresa(db)
    vacio = await b05.consultar(db, eid, b05.Parametros(ejercicio=2020))
    assert vacio.filas == [] and vacio.aviso is not None
