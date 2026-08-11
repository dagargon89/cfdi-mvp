"""B-05 · Acumulado anual por empleado. Papel de trabajo del cálculo anual del ISR."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b05_acumulado_anual as b05
from app.informes import universo_nomina
from app.models.cfdi_detalle import CfdiRelacionado, ComprobanteDetalle
from app.models.configuracion_fiscal import CatalogoPercepcionMarca
from app.models.enums import EstatusCfdi, PeriodicidadTarifa
from app.repositories import tarifa_isr as repo_tarifa
from app.services import anexo8
from app.services import configuracion_fiscal as cfg
from app.services import tarifa_isr as t
from tests import factories
from tests.helpers_nomina import insertar_nomina

_CONFIRMADO_EN = datetime(2026, 8, 6, 12, 0, 0)
_ACTOR = "quien@revisa.mx"


async def _empresa(db: AsyncSession) -> int:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    return empresa.empresa_id


async def _sembrar_marcas(
    db: AsyncSession, tmp_path: Path, marcas: list[tuple[str, bool]], *, confirmadas: bool
) -> None:
    """Siembra `catalogo_percepcion_marca` **por el servicio de la tarea 2**, no con `INSERT`
    directos: así cada prueba ejercita el camino real, incluido el invariante de confirmación
    —que es justo lo que se está probando— y la validación de `tipo_percepcion` contra
    `c_TipoPercepcion`. Mismo criterio que `tests/test_informe_b03.py`.

    Cada marca es `(tipo_percepcion, es_ingreso_ordinario)`. El resto de los campos son los
    mínimos que el cargador exige; B-05 solo mira `es_ingreso_ordinario`.
    """
    renglones = ["catalogo_percepcion_marca:"]
    for tipo, ordinario in marcas:
        renglones += [
            f"  - tipo_percepcion: '{tipo}'",
            f"    es_ingreso_ordinario: {str(ordinario).lower()}",
            "    base_exencion: NINGUNA",
            "    integra_sbc: false",
            "    es_provisionable: false",
        ]
    ruta = tmp_path / "marcas.yaml"
    ruta.write_text("\n".join(renglones) + "\n", encoding="utf-8")
    await cfg.cargar_desde_yaml(db, ruta)
    if not confirmadas:
        return
    for fila in (await db.scalars(select(CatalogoPercepcionMarca))).all():
        fila.confirmado_por = "uid-prueba"
        fila.confirmado_en = _CONFIRMADO_EN
    await db.commit()


def _renglones_ejercicio() -> tuple[t.Renglon, ...]:
    """Dos renglones estructuralmente válidos para `tarifa_isr.validar` (arrancan en 0.01, tasas
    crecientes, la última entre 30 % y 40 %), **no** la tabla anual real del Anexo 8: el bloque
    anual del ejercicio no existe todavía en ningún boletín público con el que comparar, así que,
    igual que `tests/test_informe_b09.py::_renglones_sinteticos`, aquí solo importa que la
    aritmética se pueda verificar a mano, no que la cifra sea la oficial.

    Renglón 1: `[0.01, 10000.00]`, cuota fija 0.00, tasa 10 %.
    Renglón 2: `[10000.01, en adelante]`, cuota fija 1000.00, tasa 30 %.
    """
    return (
        t.Renglon(1, Decimal("0.01"), Decimal("10000.00"), Decimal("0.00"), Decimal("0.10")),
        t.Renglon(2, Decimal("10000.01"), None, Decimal("1000.00"), Decimal("0.30")),
    )


async def _sembrar_tarifa_ejercicio(db: AsyncSession, ejercicio: int = 2026) -> None:
    """Siembra y confirma la tarifa `EJERCICIO` por el repositorio real (`guardar_importadas` +
    `confirmar`), igual que `tests/test_informe_b09.py::_sembrar_tarifa`: ejercita el mismo
    invariante de confirmación que se está probando, en vez de un `INSERT` directo."""
    extraida = anexo8.TarifaExtraida(
        ejercicio=ejercicio,
        periodicidad=PeriodicidadTarifa.EJERCICIO,
        encabezado=f"Tarifa EJERCICIO {ejercicio} (fixture de prueba)",
        renglones=_renglones_ejercicio(),
    )
    guardadas = await repo_tarifa.guardar_importadas(db, [extraida], fuente="Anexo 8, DOF (fixture)", sha256="c" * 64)
    await db.commit()
    await repo_tarifa.confirmar(
        db, ejercicio=ejercicio, periodicidad=PeriodicidadTarifa.EJERCICIO,
        huella_revisada=guardadas[0].huella, actor=_ACTOR,
    )
    await db.commit()


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


async def test_el_cfdi_sustituido_se_reporta_con_la_clave_compartida(db: AsyncSession) -> None:
    """La bandera de exclusión por sustitución usa `universo_nomina.CLAVE_CFDI_SUSTITUIDO`, no un
    literal propio.

    **Ninguna prueba de B-05 miraba esa clave** —solo las de B-03—, así que la línea que la emite
    se podía cambiar sin que la suite se enterara, y con ella la trazabilidad de las exclusiones:
    la clave es la columna por la que se filtra la hoja `Banderas`, y dos ortografías entre
    informes la vuelven inútil. Se asevera contra la **constante** a propósito: eso fija que este
    informe la consume en vez de escribirla a mano. Que la constante valga `"CFDI_SUSTITUIDO"` lo
    fijan las pruebas de B-03, que sí aseveran el texto.
    """
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="3a000001-0000-0000-0000-000000000001",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          estatus=EstatusCfdi.NO_VERIFICADO,
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                          total_percepciones="8000.00", total="8000.00")
    cid_bueno = await insertar_nomina(db, empresa_id=eid, uuid="3a000002-0000-0000-0000-000000000002",
                                      fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                                      percepciones=[("001", "001", "Sueldo", "8500.00", "0.00")],
                                      total_percepciones="8500.00", total="8500.00")
    db.add(CfdiRelacionado(comprobante_id=cid_bueno, tipo_relacion="04",
                           uuid_relacionado="3a000001-0000-0000-0000-000000000001"))
    await db.commit()

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    avisos = [b for b in resultado.banderas if b.clave == universo_nomina.CLAVE_CFDI_SUSTITUIDO]
    assert len(avisos) == 1, [b.clave for b in resultado.banderas]
    # Ámbito por UUID del **sustituido** (el excluido), no del sustituto: es el que hay que poder
    # localizar. Y severidad baja: no es un defecto del patrón, es una sustitución bien hecha.
    assert avisos[0].ambito == "uuid:3a000001-0000-0000-0000-000000000001"
    assert avisos[0].severidad == "baja"


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


async def test_no_hay_columna_sujeto_a_calculo_anual(db: AsyncSession) -> None:
    """La columna 26 del documento fuente ("Sujeto a cálculo anual", B-05.R2) sigue fuera de
    alcance: exige datos que este informe no tiene (fecha de baja, umbral vigente del ejercicio,
    aviso por escrito del trabajador), y afirmarla sin ellos sería una aseveración fiscal sin
    sustento.

    **Esta prueba antes aseveraba también la ausencia de "ISR anual teórico" y de la columna 11**
    ("Gravado ordinario"). Las dos correcciones son del mismo tipo —el sujeto de la prueba
    cambió, no la prueba se acomodó a la implementación—: la 11 la desbloqueó
    `catalogo_percepcion_marca` (tarea 8 de la fase 3) y "ISR anual teórico" —junto con "Subsidio
    anual acreditable" y "Diferencia a cargo / favor"— los desbloquea la tarifa `EJERCICIO` (esta
    tarea). Ver `test_las_tres_columnas_anuales_existen_siempre` para las tres columnas nuevas."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30))
    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    titulos = [c.titulo for c in resultado.columnas]
    assert not any("cálculo anual" in t.lower() for t in titulos)


# --------------------------------------------------------------------------------------
# B-05.R4 — La columna 11, "Gravado ordinario"
# --------------------------------------------------------------------------------------


async def test_gravado_ordinario_excluye_separacion_y_jubilacion(db: AsyncSession, tmp_path: Path) -> None:
    """**La prueba central de B-05.R4.** Los ingresos por separación (art. 95 LISR) y por
    jubilación (art. 96) tienen régimen fiscal propio y **no** se acumulan al gravado ordinario,
    que es la base del cálculo anual del ISR del art. 97. Sumarlos sobreestima el ISR anual.

    Cuáles son esos tipos lo dice el dato (`es_ingreso_ordinario`), no una lista en el programa
    (§2.12): aquí `022` (prima de antigüedad, régimen de separación) y `039` (jubilación en una
    exhibición) se siembran con la marca en `false`, y la columna tiene que dejarlos fuera
    mientras "Total gravado" —que sí los suma— sigue valiendo el total.
    """
    eid = await _empresa(db)
    await _sembrar_marcas(db, tmp_path, [("001", True), ("022", False), ("039", False)], confirmadas=True)
    await insertar_nomina(db, empresa_id=eid, uuid="c0000001-0000-0000-0000-000000000001",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00"),
                                        ("022", "022", "Prima de antigüedad", "5000.00", "0.00"),
                                        ("039", "039", "Jubilación", "3000.00", "0.00")],
                          total_percepciones="16000.00", total="16000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Total gravado") == Decimal("16000.00")
    assert _fila(resultado, "Gravado ordinario") == Decimal("8000.00")
    # No hay nada que reportar: el catálogo alcanzó para clasificar todos los tipos.
    assert not [b for b in resultado.banderas if b.clave in ("FALTA_MARCA", "MARCA_SIN_CONFIRMAR")]


async def test_gravado_ordinario_acumula_todos_los_cfdi_del_ejercicio(db: AsyncSession, tmp_path: Path) -> None:
    """La gemela de acumulación: la columna es anual, no del último CFDI, y suma solo el gravado
    (no el exento) de los tipos ordinarios."""
    eid = await _empresa(db)
    await _sembrar_marcas(db, tmp_path, [("001", True), ("022", False)], confirmadas=True)
    for sufijo, fecha in (("1", date(2026, 6, 30)), ("2", date(2026, 7, 15))):
        await insertar_nomina(db, empresa_id=eid, uuid=f"c000000{sufijo}-0000-0000-0000-00000000000{sufijo}",
                              fecha_pago=fecha, fecha_final_pago=fecha,
                              percepciones=[("001", "001", "Sueldo", "8000.00", "500.00"),
                                            ("022", "022", "Prima de antigüedad", "1000.00", "0.00")],
                              total_percepciones="9500.00", total="9500.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Gravado ordinario") == Decimal("16000.00")
    # El exento no entra (la columna es `Σ importe_gravado`) y la prima de antigüedad tampoco.
    assert _fila(resultado, "Total gravado") == Decimal("18000.00")
    assert _fila(resultado, "Total exento") == Decimal("1000.00")


async def test_sin_catalogo_de_marcas_la_columna_va_vacia_con_una_sola_bandera(db: AsyncSession) -> None:
    """Sin marcas, la columna sale `None` — **nunca cero**: un cero ahí diría "este empleado no
    tuvo ingreso ordinario", que es una afirmación fiscal falsa sobre alguien que cobró todo el
    año, y viaja a su constancia de percepciones.

    Y **una** bandera por causa, con ámbito `informe`, no una por fila: es la lección del
    colapso de banderas de la fase 2. Este es además el estado de la instalación real hoy.

    **La clave es `FALTA_MARCA`, la misma que emite B-03** para el mismo hueco (ronda 1: la
    primera versión usaba `FALTA_CATALOGO_DE_MARCAS`). Lo único que hace útil una clave de
    bandera es que quien filtre la hoja por ella encuentre todos los informes que tienen ese
    hueco, y el hueco es literalmente el mismo. Lo que sí difiere a propósito es el ámbito: en
    B-03 es `tipo:0NN` porque cada tipo pierde solo su propio tope; aquí la columna se vacía
    entera para todos los empleados, así que el daño es de la corrida."""
    eid = await _empresa(db)
    for sufijo, fecha in (("1", date(2026, 6, 30)), ("2", date(2026, 7, 15))):
        await insertar_nomina(db, empresa_id=eid, uuid=f"c100000{sufijo}-0000-0000-0000-00000000000{sufijo}",
                              fecha_pago=fecha, fecha_final_pago=fecha,
                              percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                              total_percepciones="8000.00", total="8000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Gravado ordinario") is None
    faltantes = [b for b in resultado.banderas if b.clave == "FALTA_MARCA"]
    assert len(faltantes) == 1, [b.clave for b in resultado.banderas]
    assert faltantes[0].severidad == "alta" and faltantes[0].ambito == "informe"
    assert "001" in faltantes[0].mensaje
    assert "MARCA_SIN_CONFIRMAR" not in [b.clave for b in resultado.banderas]


async def test_marcas_sin_confirmar_degradan_igual_y_la_bandera_dice_que_hay_propuesta(
    db: AsyncSession, tmp_path: Path
) -> None:
    """**La decisión de esta tarea, fijada por prueba:** la columna 11 exige marcas
    **confirmadas**. Con la marca cargada pero sin confirmar la columna sigue vacía.

    Y la bandera distingue este estado del anterior: dice que hay una propuesta esperando y qué
    afirma, así que el arreglo es un clic en vez de una búsqueda. Es el estado real de la
    instalación (44 marcas cargadas, ninguna confirmada), así que es la ruta más transitada."""
    eid = await _empresa(db)
    await _sembrar_marcas(db, tmp_path, [("001", True)], confirmadas=False)
    await insertar_nomina(db, empresa_id=eid, uuid="c2000001-0000-0000-0000-000000000001",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                          total_percepciones="8000.00", total="8000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Gravado ordinario") is None
    sin_confirmar = [b for b in resultado.banderas if b.clave == "MARCA_SIN_CONFIRMAR"]
    assert len(sin_confirmar) == 1, [b.clave for b in resultado.banderas]
    assert sin_confirmar[0].severidad == "alta" and sin_confirmar[0].ambito == "informe"
    # Procedencia: qué dice la propuesta, para que confirmarla sea una decisión y no un acto de fe.
    assert "001 → ingreso ordinario: sí" in sin_confirmar[0].mensaje
    # Y no se confunde con la ausencia: son dos estados distintos y dos claves distintas.
    assert "FALTA_MARCA" not in [b.clave for b in resultado.banderas]


async def test_un_tipo_con_gravado_cero_no_bloquea_la_columna(db: AsyncSession, tmp_path: Path) -> None:
    """**La configuración real de este cliente hoy**, y el defecto que encontró la auditoría de la
    ronda 2: la puerta todo-o-nada exigía marca confirmada para tipos que **no pueden mover la
    suma ni un centavo**.

    De las 44 marcas solo dos le aplican a esta empresa: `001` Sueldos (108,757.80 de gravado, sin
    duda declarada, confirmable de inmediato) y `005` Fondo de Ahorro (0.00 de gravado, todo
    exento, **con** duda declarada sobre si integra el SBC, así que se queda en la cola hasta que
    alguien haga esa revisión fiscal). O sea: la única marca que va a quedar sin confirmar es
    justamente la que tiene gravado cero, y la columna 11 —la base del cálculo anual del ISR del
    art. 97 y de la constancia de percepciones— salía vacía **para toda la plantilla** por ella.

    Es el cuarto caso del mismo patrón en esta fase: condicionar algo a que un valor esté
    confirmado sin preguntarse si ese algo *usa* el valor (ver la regla general en el docstring de
    `b03_gravado_exento`). `Σ importe_gravado` de un tipo cuyo gravado es cero es cero, valga lo
    que valga su `es_ingreso_ordinario`.
    """
    eid = await _empresa(db)
    # `001` confirmado; `005` cargado después y **sin** confirmar (el orden importa: el helper
    # confirma todo lo que hay en la tabla en el momento de la llamada).
    await _sembrar_marcas(db, tmp_path, [("001", True)], confirmadas=True)
    await _sembrar_marcas(db, tmp_path, [("005", True)], confirmadas=False)
    await insertar_nomina(db, empresa_id=eid, uuid="c4000001-0000-0000-0000-000000000001",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00"),
                                        ("005", "005", "Fondo de ahorro", "0.00", "1200.00")],
                          total_percepciones="9200.00", total="9200.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    # La columna calcula: el único tipo que aporta gravado tiene su marca confirmada.
    assert _fila(resultado, "Gravado ordinario") == Decimal("8000.00")
    assert _fila(resultado, "Total gravado") == Decimal("8000.00")
    assert _fila(resultado, "Total exento") == Decimal("1200.00")
    # Y no se avisa de nada: no hay ningún hueco que impida calcular.
    assert not [b for b in resultado.banderas if b.clave in ("FALTA_MARCA", "MARCA_SIN_CONFIRMAR")], [
        b.mensaje for b in resultado.banderas
    ]


async def test_el_mismo_tipo_con_gravado_distinto_de_cero_si_bloquea_la_columna(
    db: AsyncSession, tmp_path: Path
) -> None:
    """**La gemela exacta de la anterior:** mismo fixture, mismas marcas, mismo estado de
    confirmación. Lo único que cambia es que el `005` sin confirmar ahora **sí** trae gravado, y
    entonces la columna se vacía.

    Esa es la pareja que prueba que el acotamiento es por "no puede mover la suma" y no un
    "ignora los tipos sin confirmar". Sin ella, quitar la puerta todo-o-nada del todo pasaría la
    prueba de arriba igual de verde — y una base de ISR corta con apariencia de completa es
    exactamente el error que la puerta existe para evitar.
    """
    eid = await _empresa(db)
    await _sembrar_marcas(db, tmp_path, [("001", True)], confirmadas=True)
    await _sembrar_marcas(db, tmp_path, [("005", True)], confirmadas=False)
    await insertar_nomina(db, empresa_id=eid, uuid="c5000001-0000-0000-0000-000000000001",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00"),
                                        ("005", "005", "Fondo de ahorro", "1200.00", "0.00")],
                          total_percepciones="9200.00", total="9200.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Gravado ordinario") is None
    sin_confirmar = [b for b in resultado.banderas if b.clave == "MARCA_SIN_CONFIRMAR"]
    assert len(sin_confirmar) == 1, [b.clave for b in resultado.banderas]
    assert "005" in sin_confirmar[0].mensaje


async def test_un_tipo_con_gravado_cero_en_un_cfdi_y_no_en_otro_si_cuenta(
    db: AsyncSession, tmp_path: Path
) -> None:
    """El borde entre las dos anteriores: el acotamiento mira el **agregado del ejercicio**, no
    cada comprobante por separado.

    El `005` va con gravado 0.00 en junio y 1200 en julio. Si el filtro se aplicara por
    comprobante, la fila de junio calcularía con un tipo sin clasificar y la base saldría corta
    justo en el caso que la puerta protege. Un tipo que aporta gravado **en algún** periodo del
    ejercicio necesita su marca confirmada."""
    eid = await _empresa(db)
    await _sembrar_marcas(db, tmp_path, [("001", True)], confirmadas=True)
    await _sembrar_marcas(db, tmp_path, [("005", True)], confirmadas=False)
    for sufijo, fecha, gravado_005 in (("1", date(2026, 6, 30), "0.00"), ("2", date(2026, 7, 15), "1200.00")):
        await insertar_nomina(db, empresa_id=eid, uuid=f"c600000{sufijo}-0000-0000-0000-00000000000{sufijo}",
                              fecha_pago=fecha, fecha_final_pago=fecha,
                              percepciones=[("001", "001", "Sueldo", "8000.00", "0.00"),
                                            ("005", "005", "Fondo de ahorro", gravado_005, "0.00")],
                              total_percepciones="9200.00", total="9200.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Gravado ordinario") is None
    assert [b.clave for b in resultado.banderas if b.clave == "MARCA_SIN_CONFIRMAR"] == ["MARCA_SIN_CONFIRMAR"]


async def test_un_solo_tipo_sin_marca_deja_la_columna_vacia_en_vez_de_sumar_lo_conocido(
    db: AsyncSession, tmp_path: Path
) -> None:
    """El catálogo se exige **completo** para los tipos presentes.

    Sumar solo los tipos clasificados daría una base de ISR anual **corta con apariencia de
    completa** —el error espejo del que B-05.R4 existe para evitar—, y nadie que mire la celda
    podría distinguirla de una suma correcta. Aquí `001` está confirmado y `022` no está en el
    catálogo: la columna se vacía entera y la bandera nombra el tipo que falta."""
    eid = await _empresa(db)
    await _sembrar_marcas(db, tmp_path, [("001", True)], confirmadas=True)
    await insertar_nomina(db, empresa_id=eid, uuid="c3000001-0000-0000-0000-000000000001",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00"),
                                        ("022", "022", "Prima de antigüedad", "5000.00", "0.00")],
                          total_percepciones="13000.00", total="13000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    assert _fila(resultado, "Gravado ordinario") is None
    faltantes = [b for b in resultado.banderas if b.clave == "FALTA_MARCA"]
    assert len(faltantes) == 1
    # La bandera nombra el tipo que falta y solo ese: dice qué capturar, no qué sobra.
    assert "percepción 022," in faltantes[0].mensaje, faltantes[0].mensaje


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


async def _insertar_no_verificados(db: AsyncSession, eid: int, cuantos: int) -> list[str]:
    """`cuantos` CFDI de nómina `no_verificado` del mismo empleado, uno por quincena de 2026.

    Reproduce en pequeño la forma real del problema: la verificación de estatus contra el SAT es
    asíncrona, así que un ejercicio recién descargado deja **todos** sus comprobantes en
    `no_verificado` — y B-05, que agrupa por empleado, los condensa en una sola fila de datos.
    Devuelve los UUID en el mismo orden en que `universo_nomina.universo` los ordena
    (`fecha_pago` ascendente), que es el orden del que sale la muestra de la bandera colapsada.
    """
    uuids: list[str] = []
    for indice in range(cuantos):
        # Una quincena por comprobante desde el 15 de enero: 24 cortes disponibles en el año,
        # de sobra para cualquier umbral entre 10 y 25.
        mes, quincena = divmod(indice, 2)
        fecha = date(2026, mes + 1, 15 if quincena == 0 else 28)
        uuid_cfdi = f"be0000{indice:02d}-0000-0000-0000-0000000000{indice:02d}"
        await insertar_nomina(db, empresa_id=eid, uuid=uuid_cfdi,
                              fecha_pago=fecha, fecha_final_pago=fecha,
                              estatus=EstatusCfdi.NO_VERIFICADO)
        uuids.append(uuid_cfdi)
    return uuids


async def test_no_verificado_por_debajo_del_umbral_sigue_siendo_una_bandera_por_uuid(db: AsyncSession) -> None:
    """La mitad **retrocompatible** del colapso por umbral: mientras los comprobantes sin verificar
    sean menos de `UMBRAL_COLAPSO_NO_VERIFICADO`, cada uno conserva su bandera con `ambito` por
    UUID — que es la columna por la que se filtra la hoja `Banderas`.

    Sin esta prueba, subir el colapso a "siempre" pasaría inadvertido y sería un cambio del
    contrato de salida: se perdería la trazabilidad por comprobante del caso normal.
    """
    eid = await _empresa(db)
    uuids = await _insertar_no_verificados(db, eid, universo_nomina.UMBRAL_COLAPSO_NO_VERIFICADO - 1)

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    banderas = [b for b in resultado.banderas if b.clave == "ESTATUS_NO_VERIFICADO"]
    assert len(banderas) == len(uuids)
    assert {b.ambito for b in banderas} == {f"uuid:{u}" for u in uuids}
    assert all(b.severidad == "media" for b in banderas)


async def test_no_verificado_a_partir_del_umbral_colapsa_en_una_sola_bandera(db: AsyncSession) -> None:
    """A partir del umbral, una sola bandera con `ambito="informe"` y **ninguna** por UUID.

    Es la mitad que resuelve el problema. Con la nómina real de la empresa (4 empleados × 24
    quincenas) un ejercicio recién descargado producía ~96 banderas `ESTATUS_NO_VERIFICADO`
    idénticas para **4 filas** de datos en este informe, y esas 96 filas **entierran** las
    banderas de severidad alta de la misma hoja (`SIN_NORMALIZAR`, `TOTALES_DESCUADRADOS`,
    `MULTI_PATRON`), que son los hallazgos accionables. Se comprobó por mutación: devolviendo
    `banderas_de_estatus` a una bandera por UUID sin umbral, esta prueba falla.

    La bandera colapsada no pierde información: lleva el conteo, la razón por la que importa (la
    verificación es asíncrona y conviene correrla antes de usar el informe) y una muestra de UUID
    declarada como tal, con el total.
    """
    eid = await _empresa(db)
    uuids = await _insertar_no_verificados(db, eid, universo_nomina.UMBRAL_COLAPSO_NO_VERIFICADO)

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))
    banderas = [b for b in resultado.banderas if b.clave == "ESTATUS_NO_VERIFICADO"]
    assert len(banderas) == 1, [b.ambito for b in banderas]
    bandera = banderas[0]
    assert bandera.ambito == "informe"
    assert bandera.severidad == "media"
    # Ninguna bandera de esta clave conserva el grano por UUID.
    assert not [b for b in banderas if b.ambito.startswith("uuid:")]
    # El conteo real de comprobantes afectados, no el de filas del informe (que es 1: un empleado).
    assert f"{len(uuids)} comprobantes" in bandera.mensaje, bandera.mensaje
    assert len(resultado.filas) == 1
    # Por qué importa: la verificación es asíncrona y conviene correrla antes de usar el informe.
    assert "asíncrona" in bandera.mensaje and "volver a generar el informe" in bandera.mensaje
    # Muestra explícita —con su total— para que quien la lea pueda empezar por algún lado.
    assert f"Muestra de {universo_nomina.MUESTRA_UUID_COLAPSO} de los {len(uuids)} UUID" in bandera.mensaje, bandera.mensaje
    for uuid_citado in uuids[: universo_nomina.MUESTRA_UUID_COLAPSO]:
        assert uuid_citado in bandera.mensaje
    assert uuids[-1] not in bandera.mensaje, "es una muestra, no la lista completa"


async def test_cancelado_y_corrida_anterior_no_se_colapsan(db: AsyncSession) -> None:
    """El colapso es **solo** de `ESTATUS_NO_VERIFICADO`, y esta prueba lo fija.

    `COMPROBANTE_CANCELADO` exige que el usuario pida `incluir_cancelados=True` explícitamente,
    así que su volumen es una decisión suya y no una consecuencia del calendario de la
    verificación asíncrona. `DATOS_DE_CORRIDA_ANTERIOR` exige un fallo del ETL sobre ese CFDI
    concreto: es raro, y cada caso importa individualmente porque su mensaje trae el
    `error_normalizacion` propio — colapsarlos perdería información, no ruido.
    """
    eid = await _empresa(db)
    cuantos = universo_nomina.UMBRAL_COLAPSO_NO_VERIFICADO + 2
    for indice in range(cuantos):
        mes, quincena = divmod(indice, 2)
        fecha = date(2026, mes + 1, 15 if quincena == 0 else 28)
        await insertar_nomina(db, empresa_id=eid, uuid=f"bf0000{indice:02d}-0000-0000-0000-0000000000{indice:02d}",
                              fecha_pago=fecha, fecha_final_pago=fecha,
                              estatus=EstatusCfdi.CANCELADO,
                              error_normalizacion="XML no encontrado en disco")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026, incluir_cancelados=True))
    for clave in ("COMPROBANTE_CANCELADO", "DATOS_DE_CORRIDA_ANTERIOR"):
        banderas = [b for b in resultado.banderas if b.clave == clave]
        assert len(banderas) == cuantos, f"{clave} no se colapsa: {len(banderas)} de {cuantos}"
        assert all(b.ambito.startswith("uuid:") for b in banderas)


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


# --------------------------------------------------------------------------------------
# El bloque anual (Anexo I.4, art. 97 LISR): las tres columnas nuevas
# --------------------------------------------------------------------------------------


async def test_las_tres_columnas_anuales_existen_siempre(db: AsyncSession) -> None:
    """Igual que "Gravado ordinario": las tres columnas del bloque anual se declaran aunque no
    haya ninguna configuración fiscal cargada (ni marcas ni tarifa `EJERCICIO`). Con todo
    ausente, las tres van `None` — y las dos banderas que explican por qué (`FALTA_MARCA`,
    porque sin marcas no hay "Gravado ordinario"; `FALTA_TARIFA_EJERCICIO`, porque tampoco hay
    tarifa) aparecen juntas."""
    eid = await _empresa(db)
    await insertar_nomina(db, empresa_id=eid, uuid="e0000001-0000-0000-0000-000000000001",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30))

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))

    titulos = [c.titulo for c in resultado.columnas]
    assert "ISR anual teórico" in titulos
    assert "Subsidio anual acreditable" in titulos
    assert "Diferencia a cargo / favor" in titulos
    assert _fila(resultado, "ISR anual teórico") is None
    assert _fila(resultado, "Subsidio anual acreditable") is None
    assert _fila(resultado, "Diferencia a cargo / favor") is None
    claves = [b.clave for b in resultado.banderas]
    assert "FALTA_MARCA" in claves
    assert "FALTA_TARIFA_EJERCICIO" in claves


async def test_el_isr_anual_usa_la_tarifa_del_ejercicio_sin_prorratear(db: AsyncSession, tmp_path: Path) -> None:
    """El Anexo I.4 aplica `isr_de` (Anexo I.2) directamente sobre el gravado ordinario
    acumulado del ejercicio, sin elevar ni prorratear — a diferencia de B-09, que sí prorratea
    por periodo (art. 175). No hay "días pagados" que prorratear en un cálculo que ya es del año
    completo, y `tarifa_isr.DIAS_NOMINALES` ni siquiera trae una entrada para `EJERCICIO`: si el
    código llamara a `isr_del_periodo` en vez de a `isr_de`, este caso reventaría con un
    `KeyError` en vez de dar el número correcto.

    **Cálculo a mano**, con la tarifa sintética de `_renglones_ejercicio` (renglón 1:
    `[0.01, 10000.00]` cuota 0.00 tasa 10 %; renglón 2: `[10000.01, ∞)` cuota 1000.00 tasa 30 %)
    y una base (gravado ordinario) de 20000.00, que cae en el renglón 2:

        excedente = 20000.00 − 10000.01 = 9999.99
        marginal  = 9999.99 × 0.30 = 2999.997 → 3000.00 (ROUND_HALF_UP a 2 decimales)
        ISR anual = 1000.00 (cuota fija) + 3000.00 = 4000.00
    """
    eid = await _empresa(db)
    await _sembrar_marcas(db, tmp_path, [("001", True)], confirmadas=True)
    await _sembrar_tarifa_ejercicio(db)
    await insertar_nomina(db, empresa_id=eid, uuid="e0000002-0000-0000-0000-000000000002",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "20000.00", "0.00")],
                          total_percepciones="20000.00", total="20000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))

    assert _fila(resultado, "Gravado ordinario") == Decimal("20000.00")
    assert _fila(resultado, "ISR anual teórico") == Decimal("4000.00")


async def test_sin_marcas_confirmadas_las_tres_columnas_van_vacias(db: AsyncSession) -> None:
    """Se hereda la degradación de "Gravado ordinario" (B-05.R4): sin marcas confirmadas no hay
    base ordinaria, y sin base ordinaria no hay ISR anual que calcular — así que las tres
    columnas del bloque anual van vacías, aunque la tarifa `EJERCICIO` SÍ esté confirmada. No se
    sustituye la base por "Total gravado" para rescatar el cálculo: sería un número plausible y
    fiscalmente equivocado (sumaría también lo que tiene régimen propio, B-05.R4)."""
    eid = await _empresa(db)
    await _sembrar_tarifa_ejercicio(db)
    await insertar_nomina(db, empresa_id=eid, uuid="e0000003-0000-0000-0000-000000000003",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "20000.00", "0.00")],
                          total_percepciones="20000.00", total="20000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))

    assert _fila(resultado, "Gravado ordinario") is None
    assert _fila(resultado, "ISR anual teórico") is None
    assert _fila(resultado, "Subsidio anual acreditable") is None
    assert _fila(resultado, "Diferencia a cargo / favor") is None
    claves = [b.clave for b in resultado.banderas]
    assert "FALTA_MARCA" in claves
    # La tarifa SÍ está confirmada: si esta bandera apareciera también, la prueba no aislaría
    # cuál de las dos causas está degradando el bloque.
    assert "FALTA_TARIFA_EJERCICIO" not in claves


async def test_la_diferencia_del_ejercicio_dice_a_cargo_o_a_favor(db: AsyncSession, tmp_path: Path) -> None:
    """Anexo I.4, paso 5: `diferencia = ISR_anual − subsidio_acreditable − ISR_retenido`.
    Positiva es a cargo del trabajador, negativa es a favor — los dos signos, en dos empleados
    de la misma corrida para que ninguno de los dos se cuele como el único caso probado.

    **Empleado A** (gravado ordinario 20000.00 → ISR anual 4000.00, igual que en
    `test_el_isr_anual_usa_la_tarifa_del_ejercicio_sin_prorratear`), sin subsidio y con
    2000.00 → 500.00 de ISR retenido en el ejercicio:

        diferencia = 4000.00 − 0.00 − 500.00 = 3500.00  → positiva, A CARGO

    **Empleado B** (gravado ordinario 5000.00, renglón 1):

        excedente = 5000.00 − 0.01 = 4999.99
        marginal  = 4999.99 × 0.10 = 499.999 → 500.00 (ROUND_HALF_UP)
        ISR anual = 0.00 (cuota fija) + 500.00 = 500.00

    con subsidio acreditable 400.00 e ISR retenido 300.00:

        diferencia = 500.00 − 400.00 − 300.00 = −200.00  → negativa, A FAVOR
    """
    eid = await _empresa(db)
    await _sembrar_marcas(db, tmp_path, [("001", True)], confirmadas=True)
    await _sembrar_tarifa_ejercicio(db)
    await insertar_nomina(db, empresa_id=eid, uuid="e0000004-0000-0000-0000-000000000004",
                          rfc_receptor="XAXX010101000",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "20000.00", "0.00")],
                          total_percepciones="20000.00",
                          deducciones=[("002", "045", "ISR", "500.00")], total_deducciones="500.00",
                          total="19500.00")
    await insertar_nomina(db, empresa_id=eid, uuid="e0000005-0000-0000-0000-000000000005",
                          rfc_receptor="AAAA010101AA1",
                          fecha_pago=date(2026, 7, 15), fecha_final_pago=date(2026, 7, 15),
                          percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
                          total_percepciones="5000.00",
                          deducciones=[("002", "045", "ISR", "300.00")], total_deducciones="300.00",
                          otros_pagos=[("002", "035", "Subsidio", "0.00", "400.00")],
                          total="4700.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))

    titulos = [c.titulo for c in resultado.columnas]
    idx_rfc = titulos.index("RFC empleado")
    idx_subsidio = titulos.index("Subsidio anual acreditable")
    idx_diferencia = titulos.index("Diferencia a cargo / favor")
    por_rfc_subsidio = {fila[idx_rfc]: fila[idx_subsidio] for fila in resultado.filas}
    por_rfc_diferencia = {fila[idx_rfc]: fila[idx_diferencia] for fila in resultado.filas}
    # "Subsidio anual acreditable" es `acc.subsidio_causado` (columna 15), no
    # `acc.subsidio_entregado` (columna 16): A no tiene registro de `otro_pago` y suma 0.00; B
    # declaró `subsidio_causado=400.00` con `importe` (subsidio entregado en efectivo) en 0.00 —
    # si esta columna tomara la 16 en vez de la 15, saldría 0.00 también para B, y la diferencia
    # de B sería -600.00 en vez de -200.00.
    assert por_rfc_subsidio["XAXX010101000"] == Decimal("0.00")
    assert por_rfc_subsidio["AAAA010101AA1"] == Decimal("400.00")
    assert por_rfc_diferencia["XAXX010101000"] == Decimal("3500.00")
    assert por_rfc_diferencia["AAAA010101AA1"] == Decimal("-200.00")


async def test_separacion_y_jubilacion_no_entran_en_la_base_anual(db: AsyncSession, tmp_path: Path) -> None:
    """B-05.R4, ahora sobre el ISR anual: un empleado con ingreso por separación (régimen propio,
    art. 95 LISR) no lo ve sumado a la base del cálculo anual del art. 97. La base la sigue
    dando "Gravado ordinario" (columna 11, que ya excluye separación y jubilación por marca) —
    esta prueba no reimplementa esa exclusión, solo fija que el bloque anual la hereda en vez de
    usar "Total gravado" (que sí sumaría los 5000.00 de más).

    Con gravado ordinario 8000.00 (solo el tipo `001`, marcado ordinario; el tipo `022` —prima de
    antigüedad, régimen de separación— se excluye por marca):

        excedente = 8000.00 − 0.01 = 7999.99
        marginal  = 7999.99 × 0.10 = 799.999 → 800.00 (ROUND_HALF_UP)
        ISR anual = 0.00 (cuota fija) + 800.00 = 800.00

    Si el ISR anual usara "Total gravado" (13000.00) en vez de "Gravado ordinario", el renglón
    aplicable seguiría siendo el 1, pero el ISR saldría 1300.00 en vez de 800.00 — la prueba
    fallaría con ese número si alguien reintrodujera el defecto.
    """
    eid = await _empresa(db)
    await _sembrar_marcas(db, tmp_path, [("001", True), ("022", False)], confirmadas=True)
    await _sembrar_tarifa_ejercicio(db)
    await insertar_nomina(db, empresa_id=eid, uuid="e0000006-0000-0000-0000-000000000006",
                          fecha_pago=date(2026, 6, 30), fecha_final_pago=date(2026, 6, 30),
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00"),
                                        ("022", "022", "Prima de antigüedad", "5000.00", "0.00")],
                          total_percepciones="13000.00", total_separacion="5000.00", total="13000.00")

    resultado = await b05.consultar(db, eid, b05.Parametros(ejercicio=2026))

    assert _fila(resultado, "Gravado ordinario") == Decimal("8000.00")
    assert _fila(resultado, "ISR anual teórico") == Decimal("800.00")
