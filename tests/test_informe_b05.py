"""B-05 · Acumulado anual por empleado. Papel de trabajo del cálculo anual del ISR."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b05_acumulado_anual as b05
from app.models.cfdi_detalle import CfdiRelacionado, ComprobanteDetalle
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


async def test_sustituido_no_verificado_cuenta_una_vez(db: AsyncSession) -> None:
    """B-05.R1, aislada de la red de seguridad del filtro de cancelados.

    La verificación de estatus contra el SAT es asíncrona (spec §11, divergencia de R-T1
    documentada en `universo_nomina`): un CFDI recién descargado y luego sustituido por un
    timbrado corregido queda en `no_verificado` durante un tiempo — no es un caso de borde,
    es el caso común, porque la sustitución casi siempre ocurre antes de que la siguiente
    corrida de verificación alcance al sustituido. En ese estatus, el filtro de cancelados
    (`incluir_cancelados`) no protege nada: no ve nada cancelado. La única defensa contra
    duplicar el ingreso anual del empleado es B-05.R1 (la relación `tipo_relacion='04'`).
    Ver también `test_cancelado_sustituido_cuenta_una_vez`, que cubre la otra defensa."""
    eid = await _empresa(db)
    cid_malo = await insertar_nomina(db, empresa_id=eid, uuid="33333333-3333-3333-3333-333333333331",
                                     fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                                     estatus=EstatusCfdi.NO_VERIFICADO,
                                     percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                                     total_percepciones="8000.00", total="8000.00")
    cid_bueno = await insertar_nomina(db, empresa_id=eid, uuid="33333333-3333-3333-3333-333333333332",
                                      fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                                      percepciones=[("001", "001", "Sueldo", "8500.00", "0.00")],
                                      total_percepciones="8500.00", total="8500.00")
    # El sustituto declara la relación 04 hacia el sustituido, todavía no_verificado.
    db.add(CfdiRelacionado(comprobante_id=cid_bueno, tipo_relacion="04",
                           uuid_relacionado="33333333-3333-3333-3333-333333333331"))
    await db.commit()
    assert cid_malo != cid_bueno

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert len(resultado.filas) == 1
    assert _fila(resultado, "Total percepciones") == Decimal("8500.00")
    assert _fila(resultado, "Núm. de CFDI") == 1


async def test_cancelado_sustituido_cuenta_una_vez(db: AsyncSession) -> None:
    """La segunda defensa, para no perder cobertura: un sustituido que sí llegó a marcarse
    `CANCELADO` también debe contar una vez. Aquí ambos filtros del módulo lo excluirían
    por su cuenta (R1 y el filtro de cancelados huérfanos) — es exactamente lo que la
    verificación por mutación de esta tarea confirmó: esta prueba sigue pasando aunque se
    desactive R1, porque la salva el filtro de cancelados. Ver
    `test_sustituido_no_verificado_cuenta_una_vez` para la prueba que sí aísla R1."""
    eid = await _empresa(db)
    cid_malo = await insertar_nomina(db, empresa_id=eid, uuid="33333333-3333-3333-3333-333333333333",
                                     fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                                     estatus=EstatusCfdi.CANCELADO,
                                     percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                                     total_percepciones="8000.00", total="8000.00")
    cid_bueno = await insertar_nomina(db, empresa_id=eid, uuid="33333333-3333-3333-3333-333333333334",
                                      fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                                      percepciones=[("001", "001", "Sueldo", "8500.00", "0.00")],
                                      total_percepciones="8500.00", total="8500.00")
    # El sustituto declara la relación 04 hacia el cancelado.
    db.add(CfdiRelacionado(comprobante_id=cid_bueno, tipo_relacion="04",
                           uuid_relacionado="33333333-3333-3333-3333-333333333333"))
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


async def _n_sin_nomina(db: AsyncSession, eid: int, *, uuid: str, rfc_emisor: str = "CHL960913IX9") -> None:
    """Un CFDI tipo `N` con detalle y `error_normalizacion`, **sin fila en `nomina`**: el que el
    `join` interno del universo borra del informe. El XML se corrompió en disco o se perdió."""
    comprobante = await factories.crear_comprobante(
        db,
        empresa_id=eid,
        uuid=uuid,
        rfc_emisor=rfc_emisor,
        tipo_comprobante="N",
        fecha_emision=datetime(2026, 7, 1, 9, 0),
    )
    db.add(
        ComprobanteDetalle(
            comprobante_id=comprobante.comprobante_id,
            version="4.0",
            xml_hash="f" * 64,
            etl_version=1,
            error_normalizacion="XMLSyntaxError: Premature end of data in tag Comprobante",
        )
    )
    await db.commit()


async def test_un_cfdi_que_el_etl_no_pudo_leer_no_desaparece_sin_bandera(db: AsyncSession) -> None:
    """**El segundo hallazgo Critical de la revisión final.** B-05 era el único informe del grupo
    que no llamaba a `universo_nomina.banderas_de_no_normalizables`: un CFDI de nómina del
    ejercicio cuyo XML el ETL no pudo leer quedaba fuera del `join` con `nomina` y **no dejaba
    ningún rastro**. El acumulado del empleado salía corto por ese recibo y el patrón emitía la
    constancia de percepciones —el documento con el que el trabajador declara ante el SAT— con una
    quincena de menos, creyendo que estaba completa."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="bb000001-0000-0000-0000-000000000001",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30))
    await _n_sin_nomina(db, eid, uuid="bb000002-0000-0000-0000-000000000002")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    banderas = [b for b in resultado.banderas if b.clave == "SIN_NORMALIZAR"]
    assert len(banderas) == 1, [b.clave for b in resultado.banderas]
    assert banderas[0].ambito == "uuid:bb000002-0000-0000-0000-000000000002"
    assert banderas[0].severidad == "alta"
    # La fila del CFDI sano sí sale: la bandera avisa, no borra nada.
    assert len(resultado.filas) == 1


async def test_las_banderas_de_no_normalizables_no_filtran_por_emisor(db: AsyncSession) -> None:
    """El universo de B-05 no filtra por `rfc_emisor` (B-05.R3 depende de ver todos los patrones),
    así que su consulta de banderas tampoco puede filtrarlo: un CFDI roto de un **segundo** patrón
    es justo el caso que este informe existe para señalar, y desaparecería sin bandera."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="bb000003-0000-0000-0000-000000000003",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30))
    await _n_sin_nomina(db, eid, uuid="bb000004-0000-0000-0000-000000000004", rfc_emisor="XAXX010101000")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    ambitos = {b.ambito for b in resultado.banderas if b.clave == "SIN_NORMALIZAR"}
    assert ambitos == {"uuid:bb000004-0000-0000-0000-000000000004"}


async def test_cancelado_excluido_lleva_su_propia_clave(db: AsyncSession) -> None:
    """Con `incluir_cancelados=False` el cancelado huérfano NO suma, y eso se reporta con
    `CANCELADO_EXCLUIDO` — **no** con `COMPROBANTE_CANCELADO`, que en B-01/B-02 significa lo
    contrario ("se incluyó y sus importes suman"). Antes de la revisión final las dos lecturas
    compartían clave y quien filtrara la hoja `Banderas` por ella en B-02 y en B-05 del mismo
    periodo sacaba conclusiones opuestas del mismo dato."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="bb000005-0000-0000-0000-000000000005",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          estatus=EstatusCfdi.CANCELADO,
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                          total_percepciones="8000.00", total="8000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    claves = [b.clave for b in resultado.banderas]
    assert "CANCELADO_EXCLUIDO" in claves
    assert "COMPROBANTE_CANCELADO" not in claves
    bandera = next(b for b in resultado.banderas if b.clave == "CANCELADO_EXCLUIDO")
    assert bandera.severidad == "alta"
    assert resultado.filas == []  # no hay nada que acumular


async def test_cancelado_incluido_suma_y_lleva_la_clave_compartida(db: AsyncSession) -> None:
    """La rama que **no tenía ninguna prueba** (ninguna prueba de B-05 pasaba
    `incluir_cancelados=True`) y la peligrosa de las dos: el cancelado entra al acumulado, así que
    infla el ingreso anual del empleado en su constancia. Antes no emitía **ninguna** bandera."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="bb000006-0000-0000-0000-000000000006",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          estatus=EstatusCfdi.CANCELADO,
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                          total_percepciones="8000.00", total="8000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026, incluir_cancelados=True))
    assert len(resultado.filas) == 1
    assert _fila(resultado, "Total percepciones") == Decimal("8000.00")
    bandera = next(b for b in resultado.banderas if b.clave == "COMPROBANTE_CANCELADO")
    assert bandera.ambito == "uuid:bb000006-0000-0000-0000-000000000006"
    assert bandera.severidad == "alta"
    assert "suman" in bandera.mensaje
    assert not [b for b in resultado.banderas if b.clave == "CANCELADO_EXCLUIDO"]


async def test_no_verificado_entra_al_acumulado_con_bandera(db: AsyncSession) -> None:
    """§11 del diseño: la divergencia de R-T1 se acepta **con la condición** de que todo
    comprobante incluido que no sea vigente lleve bandera. B-05 no la cumplía y no tiene columna
    de estatus, así que el acumulado mezclaba `vigente` y `no_verificado` sin distinguirlos — y
    como la verificación contra el SAT es asíncrona por diseño, ese es el estado **normal** de un
    ejercicio recién descargado, no un caso de borde."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="bb000007-0000-0000-0000-000000000007",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          estatus=EstatusCfdi.NO_VERIFICADO)
    await insertar_nomina(db, empresa_id=eid, uuid="bb000008-0000-0000-0000-000000000008",
                          fecha_pago=date(2026, 7, 15), fecha_final_pago=date(2026, 7, 15),
                          estatus=EstatusCfdi.VIGENTE)

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    ambitos = {b.ambito for b in resultado.banderas if b.clave == "ESTATUS_NO_VERIFICADO"}
    # Solo el no verificado: un vigente no lleva bandera de estatus.
    assert ambitos == {"uuid:bb000007-0000-0000-0000-000000000007"}
    assert next(b for b in resultado.banderas if b.clave == "ESTATUS_NO_VERIFICADO").severidad == "media"


async def test_gravado_y_exento_descuadrados_emiten_bandera(db: AsyncSession) -> None:
    """Identidades #4 y #5 de B-00, cotejadas **al generar el informe** y no solo en las pruebas.

    Este informe recalcula gravado y exento de los nodos (correcto para una constancia) mientras
    B-01/B-02 reportan lo que declara el encabezado: con un CFDI descuadrado los dos daban cifras
    distintas del mismo concepto para el mismo periodo sin que ninguno avisara, y dentro de esta
    misma fila "Total percepciones" (encabezado) no cuadra con gravado + exento (nodos)."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="bb000009-0000-0000-0000-000000000009",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "8000.00", "500.00")],
                          total_percepciones="8500.00", total="8500.00",
                          total_gravado="9999.99", total_exento="1111.11")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    descuadres = [b for b in resultado.banderas if b.clave == "TOTALES_DESCUADRADOS"]
    mensajes = " | ".join(b.mensaje for b in descuadres)
    assert "total_gravado" in mensajes, [b.mensaje for b in resultado.banderas]
    assert "total_exento" in mensajes, [b.mensaje for b in resultado.banderas]
    assert all(b.severidad == "alta" and b.ambito == "uuid:bb000009-0000-0000-0000-000000000009" for b in descuadres)


async def test_gravado_y_exento_cuadrados_no_emiten_bandera(db: AsyncSession) -> None:
    """La otra mitad: sin ella, una comparación invertida pasaría la prueba de arriba igual."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="bb00000a-0000-0000-0000-00000000000a",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "8000.00", "500.00")],
                          total_percepciones="8500.00", total="8500.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert [b for b in resultado.banderas if b.clave == "TOTALES_DESCUADRADOS"] == []


async def test_nombre_empleado_es_del_trabajador_no_del_patron(db: AsyncSession) -> None:
    """La columna "Nombre empleado" sale de `comprobante_detalle.nombre_receptor`, no de
    `comprobante.razon_social_emisor` (que es el nombre de la EMPRESA). B-05 ya lo hacía bien;
    esta prueba lo fija, porque hasta la revisión final **ninguna** prueba del proyecto miraba esa
    columna en ningún informe — y por eso B-01/B-02 llevaban el nombre del patrón en todas sus
    filas sin que nadie lo notara."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="bb00000b-0000-0000-0000-00000000000b",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          nombre_receptor="JUANA INVENTADA DE PRUEBA")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Nombre empleado") == "JUANA INVENTADA DE PRUEBA"
