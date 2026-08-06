"""B-04 · Matriz empleado × periodo. Informe de control de completitud."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b04_matriz_empleado_periodo as b04
from app.models.enums import EstatusCfdi
from tests import factories
from tests.helpers_nomina import insertar_nomina


def _p(**kw: object) -> b04.Parametros:
    base = {"fecha_desde": date(2026, 6, 1), "fecha_hasta": date(2026, 7, 31)}
    base.update(kw)
    return b04.Parametros(**base)  # type: ignore[arg-type]


async def _empresa(db: AsyncSession) -> int:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    return empresa.empresa_id


async def test_una_fila_por_empleado_y_una_columna_por_periodo(db: AsyncSession) -> None:
    eid = await _empresa(db)
    for indice, rfc in enumerate(("XAXX010101000", "XEXX010101000")):
        for quincena, (ini, fin) in enumerate(((date(2026, 6, 16), date(2026, 6, 30)),
                                               (date(2026, 7, 1), date(2026, 7, 15)))):
            await insertar_nomina(db, empresa_id=eid, uuid=f"1111111{indice}-1111-1111-1111-11111111111{quincena}",
                                  rfc_receptor=rfc, num_empleado=f"03{indice}",
                                  fecha_pago=fin, fecha_inicial_pago=ini, fecha_final_pago=fin, total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert len(resultado.filas) == 2
    titulos = [c.titulo for c in resultado.columnas]
    assert "2026-06 Q2" in titulos and "2026-07 Q1" in titulos
    # El eje cubre el rango completo, no solo los periodos con datos.
    assert "2026-06 Q1" in titulos and "2026-07 Q2" in titulos


async def test_asigna_por_fecha_final_pago_no_por_fecha_pago(db: AsyncSession) -> None:
    """El pago se adelantó al 28 de junio, pero el periodo devengado termina el 30: la
    celda que se llena es la de la segunda quincena de junio."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="22222222-2222-2222-2222-222222222222",
                          fecha_pago=date(2026, 6, 28), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    titulos = [c.titulo for c in resultado.columnas]
    fila = resultado.filas[0]
    assert fila[titulos.index("2026-06 Q2")] == Decimal("8000.00")
    assert fila[titulos.index("2026-06 Q1")] in (None, Decimal("0"))


async def test_hueco_intermedio_marca_periodo_faltante(db: AsyncSession) -> None:
    """B-04.R2: falta la Q1 de julio y hay CFDI en la Q2 posterior → omisión de timbrado."""
    eid = await _empresa(db)
    for uuid_cfdi, (ini, fin) in (("33333333-3333-3333-3333-333333333331", (date(2026, 6, 16), date(2026, 6, 30))),
                                  ("33333333-3333-3333-3333-333333333332", (date(2026, 7, 16), date(2026, 7, 31)))):
        await insertar_nomina(db, empresa_id=eid, uuid=uuid_cfdi, fecha_pago=fin,
                              fecha_inicial_pago=ini, fecha_final_pago=fin, total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    faltantes = [b for b in resultado.banderas if b.clave == "PERIODO_FALTANTE"]
    assert faltantes, resultado.banderas
    assert any("2026-07 Q1" in b.mensaje for b in faltantes)


async def test_hueco_al_final_no_marca_periodo_faltante(db: AsyncSession) -> None:
    """B-04.R2 al revés: un hueco al final de la serie es una baja probable, no un error.
    Marcarlo llenaría el informe de falsos positivos y lo volvería inútil."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="44444444-4444-4444-4444-444444444444",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert not [b for b in resultado.banderas if b.clave == "PERIODO_FALTANTE"]


async def test_periodo_duplicado(db: AsyncSession) -> None:
    """B-04.R4: dos nóminas ordinarias del mismo empleado y periodo casi siempre son un
    timbrado doble."""
    eid = await _empresa(db)
    for sufijo in ("1", "2"):
        await insertar_nomina(db, empresa_id=eid, uuid=f"5555555{sufijo}-5555-5555-5555-555555555555",
                              fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                              fecha_final_pago=date(2026, 6, 30), tipo_nomina="O", total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert any(b.clave == "PERIODO_DUPLICADO" for b in resultado.banderas)


async def test_variacion_anomala_solo_con_dias_iguales(db: AsyncSession) -> None:
    """B-04.R3: la condición sobre los días pagados evita marcar quincenas cortas
    legítimas (un alta a media quincena baja el neto sin que sea anomalía)."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="66666666-6666-6666-6666-666666666661",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), dias="15.000", total="8000.00")
    await insertar_nomina(db, empresa_id=eid, uuid="66666666-6666-6666-6666-666666666662",
                          fecha_pago=date(2026, 7, 15), fecha_inicial_pago=date(2026, 7, 1),
                          fecha_final_pago=date(2026, 7, 15), dias="15.000", total="2000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert any(b.clave == "VARIACION_ANOMALA" for b in resultado.banderas)


async def test_variacion_con_dias_distintos_no_marca(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="77777777-7777-7777-7777-777777777771",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), dias="15.000", total="8000.00")
    await insertar_nomina(db, empresa_id=eid, uuid="77777777-7777-7777-7777-777777777772",
                          fecha_pago=date(2026, 7, 15), fecha_inicial_pago=date(2026, 7, 1),
                          fecha_final_pago=date(2026, 7, 15), dias="7.000", total="2000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert not [b for b in resultado.banderas if b.clave == "VARIACION_ANOMALA"]


async def test_corte_irregular(db: AsyncSession) -> None:
    """Periodicidad quincenal con un cierre el día 20: no cae en ningún corte teórico."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="88888888-8888-8888-8888-888888888888",
                          periodicidad="04", fecha_pago=date(2026, 6, 20),
                          fecha_inicial_pago=date(2026, 6, 6), fecha_final_pago=date(2026, 6, 20), total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    assert any(b.clave == "CORTE_IRREGULAR" for b in resultado.banderas)


async def test_metrica_configurable(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="99999999-9999-9999-9999-999999999999",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), dias="15.000", total="8000.00",
                          deducciones=[("002", "045", "ISR", "500.00")])

    titulos_y_fila = {}
    for metrica, esperado in (("NETO", Decimal("8000.00")), ("ISR_RETENIDO", Decimal("500.00")),
                              ("DIAS_PAGADOS", Decimal("15.000")), ("NUM_CFDI", 1)):
        resultado = await b04.consultar(db, eid, _p(metrica=metrica))
        titulos = [c.titulo for c in resultado.columnas]
        titulos_y_fila[metrica] = resultado.filas[0][titulos.index("2026-06 Q2")]
        assert titulos_y_fila[metrica] == esperado, (metrica, titulos_y_fila[metrica])


async def test_columnas_de_resumen(db: AsyncSession) -> None:
    """Las columnas fijas de la ficha: cobertura, total, promedio y dispersión."""
    eid = await _empresa(db)
    for uuid_cfdi, (ini, fin) in (("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1", (date(2026, 6, 16), date(2026, 6, 30))),
                                  ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2", (date(2026, 7, 1), date(2026, 7, 15)))):
        await insertar_nomina(db, empresa_id=eid, uuid=uuid_cfdi, fecha_pago=fin,
                              fecha_inicial_pago=ini, fecha_final_pago=fin, total="8000.00")

    resultado = await b04.consultar(db, eid, _p())
    titulos = [c.titulo for c in resultado.columnas]
    fila = resultado.filas[0]
    assert fila[titulos.index("Núm. de periodos con pago")] == 2
    assert fila[titulos.index("Total del rango")] == Decimal("16000.00")
    assert fila[titulos.index("Promedio por periodo")] == Decimal("8000.00")
    # 4 cortes teóricos en el rango, 2 con pago.
    assert fila[titulos.index("Núm. de periodos esperados")] == 4


async def test_curp_sensible_y_sin_comprobantes(db: AsyncSession) -> None:
    eid = await _empresa(db)
    vacio = await b04.consultar(db, eid, _p(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31)))
    assert vacio.filas == [] and vacio.aviso is not None

    await insertar_nomina(db, empresa_id=eid, uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30))
    resultado = await b04.consultar(db, eid, _p())
    por_titulo = {c.titulo: c for c in resultado.columnas}
    assert por_titulo["CURP"].sensible is True


async def test_celda_llena_por_un_cancelado_lleva_bandera(db: AsyncSession) -> None:
    """**Hallazgo Important de la revisión final.** El §11 del diseño acepta la divergencia de R-T1
    con una condición explícita: "todo comprobante incluido que no sea vigente lleva bandera". Este
    informe no llamaba a `universo_nomina.banderas_de_estatus` y no tiene columna de estatus en
    `Datos` (a diferencia de B-01/B-02, que traen "Estado SAT"), así que una celda de la matriz
    llena por un CFDI cancelado ante el SAT decía "esa quincena está cubierta" sin ninguna marca:
    no había forma de saberlo."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="cccccccc-cccc-cccc-cccc-ccccccccccc1",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), estatus=EstatusCfdi.CANCELADO, total="8000.00")

    resultado = await b04.consultar(db, eid, _p(incluir_cancelados=True))
    titulos = [c.titulo for c in resultado.columnas]
    # La celda SÍ se llena (el parámetro lo pidió); lo que faltaba era el aviso.
    assert resultado.filas[0][titulos.index("2026-06 Q2")] == Decimal("8000.00")
    bandera = next(b for b in resultado.banderas if b.clave == "COMPROBANTE_CANCELADO")
    assert bandera.ambito == "uuid:cccccccc-cccc-cccc-cccc-ccccccccccc1"
    assert bandera.severidad == "alta"


async def test_no_verificado_lleva_bandera_y_el_vigente_no(db: AsyncSession) -> None:
    """La verificación contra el SAT es asíncrona por diseño, así que `no_verificado` es el estado
    **normal** de un rango recién descargado: sin bandera, la matriz no distingue una quincena
    confirmada de una que el SAT todavía no ha respondido."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="cccccccc-cccc-cccc-cccc-ccccccccccc2",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), estatus=EstatusCfdi.NO_VERIFICADO)
    await insertar_nomina(db, empresa_id=eid, uuid="cccccccc-cccc-cccc-cccc-ccccccccccc3",
                          rfc_receptor="XEXX010101000",
                          fecha_pago=date(2026, 6, 30), fecha_inicial_pago=date(2026, 6, 16),
                          fecha_final_pago=date(2026, 6, 30), estatus=EstatusCfdi.VIGENTE)

    resultado = await b04.consultar(db, eid, _p())
    ambitos = {b.ambito for b in resultado.banderas if b.clave == "ESTATUS_NO_VERIFICADO"}
    assert ambitos == {"uuid:cccccccc-cccc-cccc-cccc-ccccccccccc2"}
