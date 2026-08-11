"""La comprobación de una tarifa contra un recibo real.

Su propósito no es auditar al patrón: es detectar un **error de carga**. Una tarifa de otra
periodicidad o de otro ejercicio, guardada por error en el slot equivocado, es aritméticamente
coherente —pasa las seis pruebas del Anexo I.1, que solo miran si los renglones son consistentes
entre sí, nunca dónde se guardaron— y solo se delata al aplicarla a un recibo de verdad, como una
diferencia relativa grande contra lo timbrado, no un número absurdo. Eso es lo que fija
`test_una_tarifa_de_otra_periodicidad_cargada_en_el_slot_equivocado_se_delata`, que es la razón de
existir de este módulo.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EstatusCfdi, OrigenTarifa, PeriodicidadTarifa
from app.models.nomina import Nomina
from app.repositories.tarifa_isr import TarifaGuardada
from app.services import comprobacion_tarifa
from app.services import tarifa_isr as t
from tests import factories
from tests.helpers_nomina import insertar_nomina

# Tarifa de 15 días del Anexo 8 de 2026 (los cinco primeros renglones bastan para estas pruebas,
# con el quinto abierto para que valide).
QUINCENAL = (
    t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
    t.Renglon(2, Decimal("416.71"), Decimal("3537.15"), Decimal("7.95"), Decimal("0.0640")),
    t.Renglon(3, Decimal("3537.16"), Decimal("6216.15"), Decimal("207.75"), Decimal("0.1088")),
    t.Renglon(4, Decimal("6216.16"), Decimal("7225.95"), Decimal("499.20"), Decimal("0.1600")),
    t.Renglon(5, Decimal("7225.96"), None, Decimal("660.75"), Decimal("0.3500")),
)

# Tarifa del ejercicio (anual): mismos tramos multiplicados por 24, para que sea internamente
# coherente igual que la real. Es la tabla equivocada que las 6 pruebas no pueden detectar.
ANUAL = (
    t.Renglon(1, Decimal("0.01"), Decimal("10000.80"), Decimal("0.00"), Decimal("0.0192")),
    t.Renglon(2, Decimal("10000.81"), Decimal("84891.60"), Decimal("190.80"), Decimal("0.0640")),
    t.Renglon(3, Decimal("84891.61"), None, Decimal("4986.00"), Decimal("0.3500")),
)


def _tarifa(renglones: tuple[t.Renglon, ...], periodicidad: PeriodicidadTarifa) -> TarifaGuardada:
    return TarifaGuardada(
        ejercicio=2026,
        periodicidad=periodicidad,
        origen=OrigenTarifa.IMPORTADA,
        fuente="Anexo 8 DOF 28-12-2025",
        documento_sha256="a" * 64,
        encabezado="IV. Tarifa aplicable cuando hagan pagos que correspondan a un periodo de 15 dias",
        importado_en=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        confirmado_por=None,
        confirmado_en=None,
        renglones=renglones,
    )


async def _empresa(db: AsyncSession) -> int:
    empresa = await factories.crear_empresa(db, nombre="Empresa de prueba", rfc="CHL960913IX9")
    return empresa.empresa_id


async def test_elige_un_recibo_ordinario_no_uno_extraordinario(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="11111111-1111-4111-8111-111111111111", tipo_nomina="E",
        total_gravado="50000.00", deducciones=[("002", "002", "ISR", "9000.00")],
    )
    await insertar_nomina(
        db, empresa_id=eid, uuid="22222222-2222-4222-8222-222222222222", tipo_nomina="O",
        total_gravado="5000.00", deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.uuid == "22222222-2222-4222-8222-222222222222"


async def test_prefiere_el_recibo_con_los_dias_nominales_y_no_advierte(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="33333333-3333-4333-8333-333333333333", dias="9.000",
        total_gravado="3000.00", deducciones=[("002", "002", "ISR", "100.00")],
    )
    await insertar_nomina(
        db, empresa_id=eid, uuid="44444444-4444-4444-8444-444444444444", dias="15.000",
        total_gravado="5000.00", deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.uuid == "44444444-4444-4444-8444-444444444444"
    assert hecha.advertencias == ()


async def test_si_no_hay_recibo_limpio_usa_el_que_haya_y_explica_por_que_difiere(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="55555555-5555-4555-8555-555555555555", dias="9.000",
        total_gravado="3000.00", deducciones=[("002", "002", "ISR", "100.00")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert any("prorrateado" in a for a in hecha.advertencias)


async def test_el_gravado_sale_del_cfdi_y_no_de_las_marcas_de_percepcion(db: AsyncSession) -> None:
    """`catalogo_percepcion_marca` está vacío en esta prueba, como está en la base real: las 44
    marcas siguen sin confirmar. Si la comprobación derivara la base de ellas, saldría vacía justo
    la primera vez que alguien carga una tarifa, que es cuando más se necesita."""
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="66666666-6666-4666-8666-666666666666",
        total_gravado="5000.00", deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.gravado == Decimal("5000.00")


async def test_el_isr_timbrado_sale_de_la_deduccion_002(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="77777777-7777-4777-8777-777777777777", total_gravado="5000.00",
        deducciones=[("004", "004", "Otra deduccion", "500.00"), ("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.isr_timbrado == Decimal("366.91")


async def test_una_tarifa_correcta_da_una_diferencia_de_pesos(db: AsyncSession) -> None:
    """Renglón 3: 207.75 + (5000.00 − 3537.16) × 0.1088 = 366.91, que es lo timbrado."""
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="88888888-8888-4888-8888-888888888888", total_gravado="5000.00",
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.renglon == 3
    assert hecha.isr_calculado == Decimal("366.91")
    assert abs(hecha.diferencia) <= Decimal("1.00")


async def test_una_tarifa_de_otra_periodicidad_cargada_en_el_slot_equivocado_se_delata(
    db: AsyncSession,
) -> None:
    """**La prueba que justifica este módulo.** Una tarifa anual guardada por error en el slot de
    15 días (por ejemplo, porque el extractor confundió la tabla) es internamente coherente y pasa
    las seis pruebas del Anexo I.1 sin problema: esas pruebas solo verifican que los renglones sean
    consistentes entre sí, nunca en qué periodicidad quedaron guardados. Lo único que la delata es
    aplicarla a un recibo real.

    La señal no es un ISR absurdo: los tramos de la tarifa anual son ~24 veces más grandes que los
    de la quincenal, así que el gravado de un recibo cae casi siempre en el primer renglón y el ISR
    calculado sale **sistemáticamente desplazado hacia abajo**, no descabellado. Por eso la marca de
    "tabla equivocada" es una diferencia relativa grande —más de la mitad del impuesto—, no una
    diferencia de pesos (que sí es normal: subsidio al empleo, ajustes del periodo, art. 174) ni un
    orden de magnitud (que este escenario no puede producir). Si esta prueba pasara con una
    diferencia de unos cuantos pesos, la comprobación no estaría cerrando ningún hueco."""
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="99999999-9999-4999-8999-999999999999",
        total_gravado="5000.00", deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(ANUAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert abs(hecha.diferencia) > hecha.isr_timbrado / 2


async def test_sin_recibos_de_nomina_devuelve_None(db: AsyncSession) -> None:
    """Una base sin nómina no rompe la pantalla: el panel dirá que no hay recibos con los que
    comprobar, que es distinto de que la tarifa esté mal."""
    await _empresa(db)
    await db.commit()
    assert await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15)) is None


async def test_un_recibo_sin_deduccion_de_isr_advierte_en_vez_de_dar_un_falso_positivo(db: AsyncSession) -> None:
    """Sin esta advertencia, un recibo sin la deducción 002 deja `isr_timbrado` en 0 en silencio, y
    la diferencia contra el ISR calculado luce como la "diferencia enorme" que el propio panel
    enseña a leer como tarifa de otro año o de otra periodicidad — un falso positivo en la única
    ayuda a la decisión que tiene quien no es contador."""
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        total_gravado="5000.00", deducciones=[],
    )

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.isr_timbrado == Decimal("0")
    assert any("no trae una deducción de ISR" in a for a in hecha.advertencias)


async def test_dias_pagados_nulos_no_interpolan_none_en_la_advertencia(db: AsyncSession) -> None:
    """`revision_tarifa._seccion_comprobacion` ya se protegió de este mismo error (`str(None)` es
    `"None"`, no una cadena vacía). Un recibo real puede no traer `num_dias_pagados` — la columna
    es nula en el modelo — y la advertencia no debe mostrarle a quien no es contador el texto
    literal "None"."""
    eid = await _empresa(db)
    cid = await insertar_nomina(
        db, empresa_id=eid, uuid="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        total_gravado="5000.00", deducciones=[("002", "002", "ISR", "366.91")],
    )
    fila = await db.get(Nomina, cid)
    assert fila is not None
    fila.num_dias_pagados = None
    await db.commit()

    hecha = await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15))
    assert hecha is not None
    assert hecha.dias_pagados is None
    advertencia = next(a for a in hecha.advertencias if "prorrateado" in a)
    assert "None" not in advertencia


async def test_no_toma_recibos_cancelados_ni_con_error_de_normalizacion(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", estatus=EstatusCfdi.CANCELADO,
        total_gravado="5000.00", deducciones=[("002", "002", "ISR", "366.91")],
    )
    await insertar_nomina(
        db, empresa_id=eid, uuid="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        error_normalizacion="XML ilegible", total_gravado="5000.00",
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    assert await comprobacion_tarifa.comprobar(db, tarifa=_tarifa(QUINCENAL, PeriodicidadTarifa.DIAS_15)) is None
