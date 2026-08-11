"""B-09 · Recálculo de ISR y subsidio al empleo por recibo.

Lo que estas pruebas fijan, en orden de importancia:

1. **La degradación es por partes**: sin tarifa o sin marcas confirmadas no hay filas (una base
   inventada sería peor que ningún informe); sin subsidio sí hay filas, con sus tres columnas
   vacías.
2. **La base gravable son solo las percepciones ordinarias.** Es la prueba central del módulo
   (`test_la_base_gravable_excluye_las_percepciones_no_ordinarias`): un aguinaldo mezclado en la
   base produce un ISR teórico mayor al real y el informe acusaría al patrón de un exceso que no
   existe.
3. **Un recibo raro (cero días pagados, sin receptor, o sin periodicidad) no tumba la corrida
   completa.** Se captura, se deja sin calcular y se marca con una bandera — el resto del
   universo se sigue reportando.
4. **B-09.R1: la periodicidad sin tarifa publicada por el SAT usa la mensual prorrateada,
   marcada, y nunca bloquea el informe completo.** Catorcenal, bimestral, por obra, comisión,
   precio alzado u "otra" no tienen tarifa propia en el Anexo 8 (`tarifa_isr.PARA_CFDI` las
   traduce a `None`); sin esta regla esos recibos saldrían mudos —todas las columnas vacías y
   sin ninguna bandera—, que es peor que un aviso.

Los valores esperados de las columnas de cálculo (renglón, límite inferior, excedente, tasa,
impuesto marginal, cuota fija, ISR determinado) están calculados **a mano** en el docstring de
cada prueba, con la tarifa de 15 días del Anexo 8 de 2026 (la misma de
`tests/test_tarifa_isr.py::_quincenal`), nunca copiados de lo que devuelve el código: lo que este
informe afirma es delicado (que un proveedor de nómina retuvo distinto de lo que dice la ley) y
si el cálculo de la prueba está mal, la acusación es nuestra.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b09_recalculo_isr as b09
from app.informes import registro
from app.models.configuracion_fiscal import CatalogoPercepcionMarca, ParamFiscal
from app.models.enums import BaseExencion, OrigenValor, PeriodicidadTarifa
from app.models.nomina import Nomina, NominaReceptor
from app.repositories import tarifa_isr as repo_tarifa
from app.services import anexo8
from app.services import configuracion_fiscal as cfg
from app.services import tarifa_isr as t
from tests import factories
from tests.helpers_nomina import insertar_nomina

_DESDE = date(2026, 6, 1)
_HASTA = date(2026, 7, 31)
_EJERCICIO = 2026
_CONFIRMADO_EN = datetime(2026, 8, 11, 12, 0, 0)
_ACTOR = "quien@revisa.mx"

# Cifras reales del subsidio al empleo 2026 (`config/fiscal/param_fiscal.yaml`, tramo vigente
# desde febrero), para que las pruebas usen la misma configuración que produce la instalación
# real cuando alguien la confirme.
_UMA_MENSUAL = "3566.22"
_SUBSIDIO_FACTOR_UMA = "0.1502"
_SUBSIDIO_TOPE_INGRESO = "11492.66"

# Índices de columna con nombre, nunca números sueltos dentro de las aserciones.
_COL_BASE = b09._COL_BASE
_COL_TARIFA_APLICADA = b09._COL_TARIFA_APLICADA
_COL_RENGLON = b09._COL_RENGLON
_COL_LIMITE_INFERIOR = b09._COL_LIMITE_INFERIOR
_COL_EXCEDENTE = b09._COL_EXCEDENTE
_COL_TASA = b09._COL_TASA
_COL_IMPUESTO_MARGINAL = b09._COL_IMPUESTO_MARGINAL
_COL_CUOTA_FIJA = b09._COL_CUOTA_FIJA
_COL_ISR_DETERMINADO = b09._COL_ISR_DETERMINADO
_COL_SUBSIDIO_TEORICO = b09._COL_SUBSIDIO_TEORICO
_COL_ISR_A_RETENER_TEORICO = b09._COL_ISR_A_RETENER_TEORICO
_COL_SUBSIDIO_A_ENTREGAR_TEORICO = b09._COL_SUBSIDIO_A_ENTREGAR_TEORICO


# --------------------------------------------------------------------------------------
# Siembra de configuración, siempre por el servicio/repositorio real (ejercita el invariante
# de confirmación, que es justo lo que estas pruebas verifican).
# --------------------------------------------------------------------------------------


def _renglones_quincenal() -> tuple[t.Renglon, ...]:
    """Los cinco primeros renglones de la tarifa de 15 días del Anexo 8 de 2026 (los mismos de
    `tests/test_tarifa_isr.py::_quincenal`, con las tasas ya en fracción)."""
    return (
        t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
        t.Renglon(2, Decimal("416.71"), Decimal("3537.15"), Decimal("7.95"), Decimal("0.0640")),
        t.Renglon(3, Decimal("3537.16"), Decimal("6216.15"), Decimal("207.75"), Decimal("0.1088")),
        t.Renglon(4, Decimal("6216.16"), Decimal("7225.95"), Decimal("499.20"), Decimal("0.1600")),
        t.Renglon(5, Decimal("7225.96"), None, Decimal("660.75"), Decimal("0.3500")),
    )


def _renglones_sinteticos() -> tuple[t.Renglon, ...]:
    """Dos renglones estructuralmente válidos (pasan `tarifa_isr.validar`), los mismos de
    `tests/test_configuracion_isr.py::_renglones` — no son una cifra publicada por el SAT, así
    que solo se usan para la tarifa **mensual** de repuesto de B-09.R1, donde lo que se prueba
    es que el prorrateo y la bandera ocurren, no una cifra oficial de la mensual."""
    return (
        t.Renglon(1, Decimal("0.01"), Decimal("1000.00"), Decimal("0.00"), Decimal("0.0500")),
        t.Renglon(2, Decimal("1000.01"), None, Decimal("50.00"), Decimal("0.3500")),
    )


async def _sembrar_tarifa(db: AsyncSession, periodicidad: PeriodicidadTarifa, renglones: tuple[t.Renglon, ...], *, sha256: str) -> None:
    extraida = anexo8.TarifaExtraida(
        ejercicio=_EJERCICIO,
        periodicidad=periodicidad,
        encabezado=f"Tarifa {periodicidad.value} {_EJERCICIO} (fixture de prueba)",
        renglones=renglones,
    )
    guardadas = await repo_tarifa.guardar_importadas(db, [extraida], fuente="Anexo 8, DOF (fixture)", sha256=sha256)
    await db.commit()
    await repo_tarifa.confirmar(
        db, ejercicio=_EJERCICIO, periodicidad=periodicidad, huella_revisada=guardadas[0].huella, actor=_ACTOR
    )
    await db.commit()


async def _sembrar_tarifa_quincenal(db: AsyncSession) -> None:
    await _sembrar_tarifa(db, PeriodicidadTarifa.DIAS_15, _renglones_quincenal(), sha256="a" * 64)


async def _sembrar_tarifa_mensual(db: AsyncSession) -> None:
    await _sembrar_tarifa(db, PeriodicidadTarifa.MENSUAL, _renglones_sinteticos(), sha256="b" * 64)


async def _sembrar_marca(db: AsyncSession, tipo: str, *, ordinario: bool, confirmar: bool = True) -> None:
    db.add(
        CatalogoPercepcionMarca(
            tipo_percepcion=tipo,
            es_ingreso_ordinario=ordinario,
            base_exencion=BaseExencion.NINGUNA,
            factor_exencion=None,
            integra_sbc=True,
            es_provisionable=False,
            confirmado_por=_ACTOR if confirmar else None,
            confirmado_en=_CONFIRMADO_EN if confirmar else None,
        )
    )
    await db.commit()


async def _sembrar_param(db: AsyncSession, clave: str, valor: str, *, confirmar: bool = True) -> None:
    await cfg.guardar_param_fiscal(
        db, clave=clave, valor=Decimal(valor), vigencia_desde=date(2026, 2, 1), origen=OrigenValor.SEMILLA,
        fuente="Fixture de prueba",
    )
    await db.commit()
    if not confirmar:
        return
    fila = await db.get(ParamFiscal, (clave, date(2026, 2, 1)))
    assert fila is not None
    fila.confirmado_por = _ACTOR
    fila.confirmado_en = _CONFIRMADO_EN
    await db.commit()


async def _empresa_con_configuracion_confirmada(db: AsyncSession) -> int:
    """Siembra y **confirma** la tarifa quincenal, las marcas (`001` ordinaria, `002` no
    ordinaria, `005` ordinaria — el fondo de ahorro real de la instalación) y el subsidio.
    Es el estado en el que "todo está confirmado" para las pruebas que no ejercitan
    degradación."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_tarifa_quincenal(db)
    await _sembrar_marca(db, "001", ordinario=True)
    await _sembrar_marca(db, "002", ordinario=False)
    await _sembrar_marca(db, "005", ordinario=True)
    await _sembrar_param(db, "UMA_MENSUAL", _UMA_MENSUAL)
    await _sembrar_param(db, "SUBSIDIO_FACTOR_UMA", _SUBSIDIO_FACTOR_UMA)
    await _sembrar_param(db, "SUBSIDIO_TOPE_INGRESO", _SUBSIDIO_TOPE_INGRESO)
    return empresa.empresa_id


def _p(**extra: Any) -> b09.Parametros:
    return b09.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA, **extra)


def _claves(resultado: Any) -> list[str]:
    return [b.clave for b in resultado.banderas]


# --------------------------------------------------------------------------------------
# 1-2. La degradación por partes: sin tarifa o sin marcas, no hay filas
# --------------------------------------------------------------------------------------


async def test_sin_tarifa_confirmada_no_genera_filas_y_dice_que_falta(db: AsyncSession) -> None:
    """El estado real de la instalación hoy (§2 del diseño): sin ninguna tarifa cargada. El
    `aviso` tiene que decir qué falta y dónde subirlo, y no puede filtrarse un nombre de enum
    (`PeriodicidadTarifa`, `DIAS_15`) a una pantalla que el dueño del Hub —que no es contador—
    va a leer."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db, empresa_id=empresa.empresa_id, uuid="00000000-0000-4000-8000-000000000001",
        percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
    )

    resultado = await b09.consultar(db, empresa.empresa_id, _p())

    assert resultado.filas == []
    assert resultado.aviso is not None
    assert "Anexo 8" in resultado.aviso
    assert "Configuración" in resultado.aviso
    assert "PeriodicidadTarifa" not in resultado.aviso
    assert "DIAS_15" not in resultado.aviso


async def test_sin_marcas_confirmadas_no_genera_filas(db: AsyncSession) -> None:
    """Con la tarifa confirmada pero sin ninguna marca: sin saber qué es ingreso ordinario no
    hay base que armar, y una base con el gravado total sería peor que ningún informe."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_tarifa_quincenal(db)
    await insertar_nomina(
        db, empresa_id=empresa.empresa_id, uuid="00000000-0000-4000-8000-000000000002",
        percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
    )

    resultado = await b09.consultar(db, empresa.empresa_id, _p())

    assert resultado.filas == []
    assert resultado.aviso is not None


# --------------------------------------------------------------------------------------
# 3. El grano y las 21 columnas
# --------------------------------------------------------------------------------------


async def test_con_todo_confirmado_una_fila_por_recibo(db: AsyncSession) -> None:
    """Con todo confirmado, dos recibos producen dos filas de 24 columnas. El documento fuente
    numera 21 renglones, pero sus dos primeros agrupan varios campos ("UUID / Fecha pago /
    Periodo", "RFC / Nombre / Núm. empleado"); expandidos uno a uno —como ya hace B-03 con el
    mismo tipo de grupo— son 24 columnas físicas, no 21 (una ronda de revisión de esta misma
    tarea corrigió el conteo original)."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="11111111-1111-4111-8111-111111111101",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await insertar_nomina(
        db, empresa_id=eid, uuid="11111111-1111-4111-8111-111111111102",
        rfc_receptor="XAXX010101001",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    assert len(resultado.filas) == 2
    assert len(resultado.columnas) == 24
    assert [c.titulo for c in resultado.columnas].count("UUID") == 1


# --------------------------------------------------------------------------------------
# 4. La prueba central: la base gravable excluye lo no ordinario
# --------------------------------------------------------------------------------------


async def test_la_base_gravable_excluye_las_percepciones_no_ordinarias(db: AsyncSession) -> None:
    """El aguinaldo no se grava con la tarifa del periodo: su gravado no entra en la base.
    Sueldo 5000.00 (tipo 001, ordinario) + aguinaldo 2000.00 (tipo 002, NO ordinario)
    → la base es 5000.00, y el ISR el del renglón 3: 207.75 + (5000.00 − 3537.16) × 0.1088
    = 366.91. Si la base fuera 7000.00 el ISR sería 499.20 + (7000.00 − 6216.16) × 0.1600
    = 624.61, así que el error no se disimula: son 257.70 pesos de diferencia."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="11111111-1111-4111-8111-111111111111",
        percepciones=[
            ("001", "001", "Sueldo", "5000.00", "0.00"),
            ("002", "002", "Aguinaldo", "2000.00", "0.00"),
        ],
        deducciones=[("002", "002", "ISR", "366.91")],
        total_gravado="7000.00",
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    fila = resultado.filas[0]
    assert fila[_COL_BASE] == Decimal("5000.00")
    assert fila[_COL_ISR_DETERMINADO] == Decimal("366.91")


# --------------------------------------------------------------------------------------
# 5. El fondo de ahorro exento no infla la base
# --------------------------------------------------------------------------------------


async def test_el_fondo_de_ahorro_exento_no_entra_en_la_base(db: AsyncSession) -> None:
    """El caso real de la instalación (§2 del diseño): el fondo de ahorro (`005`) se timbra con
    gravado 0.00 y exento 7613.04, y está marcado como ingreso ordinario. Un error de agregación
    que sumara el exento junto con el gravado no se vería en los importes de la fila —seguirían
    siendo los del CFDI— solo se vería en que la base dejara de ser 0.00."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="22222222-2222-4222-8222-222222222222",
        percepciones=[("005", "031", "Fondo ahorro", "0.00", "7613.04")],
        total_gravado="0.00",
        deducciones=[],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    fila = resultado.filas[0]
    assert fila[_COL_BASE] == Decimal("0.00")


# --------------------------------------------------------------------------------------
# 6. Las columnas del cálculo reproducen la tarifa, a mano
# --------------------------------------------------------------------------------------


async def test_las_columnas_del_calculo_reproducen_la_tarifa(db: AsyncSession) -> None:
    """Un sueldo de 5000.00 gravados en una quincena de 15 días exactos (sin prorrateo) cae en
    el **renglón 3** de la tarifa (3537.16 – 6216.15, cuota fija 207.75, tasa 0.1088), porque
    416.70 < 3537.16 < 5000.00 ≤ 6216.15:

    excedente         = 5000.00 − 3537.16 = 1462.84
    impuesto marginal = 1462.84 × 0.1088  = 159.156992 → 159.16 (ROUND_HALF_UP a 2 decimales)
    ISR determinado   = 207.75 + 159.16   = 366.91

    La columna de tasa se muestra como porcentaje (`tarifa_isr.a_porcentaje`), no como la
    fracción cruda que guarda la tarifa: 0.1088 × 100 = 10.88.
    """
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="33333333-3333-4333-8333-333333333333",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    fila = resultado.filas[0]
    assert fila[_COL_RENGLON] == 3
    assert fila[_COL_LIMITE_INFERIOR] == Decimal("3537.16")
    assert fila[_COL_EXCEDENTE] == Decimal("1462.84")
    assert fila[_COL_TASA] == Decimal("10.88")
    assert fila[_COL_IMPUESTO_MARGINAL] == Decimal("159.16")
    assert fila[_COL_CUOTA_FIJA] == Decimal("207.75")
    assert fila[_COL_ISR_DETERMINADO] == Decimal("366.91")


# --------------------------------------------------------------------------------------
# 7. Degradación por partes: sin subsidio, el ISR sigue calculándose
# --------------------------------------------------------------------------------------


async def test_sin_subsidio_confirmado_las_columnas_del_subsidio_van_vacias_pero_el_isr_se_calcula(
    db: AsyncSession,
) -> None:
    """El subsidio al empleo no bloquea el ISR determinado (§5 del diseño): sin `UMA_MENSUAL`,
    `SUBSIDIO_FACTOR_UMA` ni `SUBSIDIO_TOPE_INGRESO` confirmados, el informe se genera igual,
    con las tres columnas del subsidio vacías. El ISR determinado es el mismo 366.91 de la
    prueba anterior: no depende del subsidio."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_tarifa_quincenal(db)
    await _sembrar_marca(db, "001", ordinario=True)
    # Ningún parámetro del subsidio se siembra ni se confirma.
    await insertar_nomina(
        db, empresa_id=empresa.empresa_id, uuid="44444444-4444-4444-8444-444444444444",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    resultado = await b09.consultar(db, empresa.empresa_id, _p())

    assert len(resultado.filas) == 1
    fila = resultado.filas[0]
    assert fila[_COL_ISR_DETERMINADO] == Decimal("366.91")
    assert fila[_COL_SUBSIDIO_TEORICO] is None
    assert fila[_COL_ISR_A_RETENER_TEORICO] is None
    assert fila[_COL_SUBSIDIO_A_ENTREGAR_TEORICO] is None


# --------------------------------------------------------------------------------------
# 8. El catálogo
# --------------------------------------------------------------------------------------


async def test_el_informe_esta_en_el_catalogo() -> None:
    definicion = registro.obtener("B-09")
    assert definicion.CLAVE == "B-09"
    assert "B-09" in [entrada["clave"] for entrada in registro.catalogo()]


# --------------------------------------------------------------------------------------
# 9. El recibo con cero días pagados no tumba la corrida (hueco explícito de esta tarea)
# --------------------------------------------------------------------------------------


async def test_un_recibo_con_cero_dias_pagados_no_tumba_la_corrida_y_lleva_bandera(db: AsyncSession) -> None:
    """`isr_del_periodo` lanza `TarifaInvalida` cuando `num_dias_pagados <= 0` (una baja el día
    1 es un dato real). El informe tiene que capturarlo, dejar las columnas de cálculo de ESE
    recibo vacías, marcarlo con una bandera, y seguir reportando el resto del universo — no
    reventar la corrida completa por un recibo raro."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="55555555-5555-4555-8555-555555555501",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await insertar_nomina(
        db, empresa_id=eid, uuid="55555555-5555-4555-8555-555555555502",
        rfc_receptor="XAXX010101002",
        dias="0.000",
        percepciones=[("001", "001", "Sueldo", "500.00", "0.00")],
        deducciones=[],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    assert len(resultado.filas) == 2, "el recibo raro no debe desaparecer de la hoja Datos"
    por_uuid = {fila[b09._COL_UUID]: fila for fila in resultado.filas}
    fila_rara = por_uuid["55555555-5555-4555-8555-555555555502"]
    assert fila_rara[_COL_ISR_DETERMINADO] is None
    assert fila_rara[_COL_RENGLON] is None

    fila_normal = por_uuid["55555555-5555-4555-8555-555555555501"]
    assert fila_normal[_COL_ISR_DETERMINADO] == Decimal("366.91")

    banderas_recibo = [b for b in resultado.banderas if b.clave == "RECIBO_NO_CALCULABLE"]
    assert len(banderas_recibo) == 1
    assert banderas_recibo[0].severidad == "alta"
    assert "55555555-5555-4555-8555-555555555502" in banderas_recibo[0].ambito


# --------------------------------------------------------------------------------------
# 10-11. B-09.R1 — la periodicidad sin tarifa publicada usa la mensual prorrateada
# --------------------------------------------------------------------------------------


async def test_periodicidad_sin_tarifa_publicada_usa_la_mensual_prorrateada_y_marca(db: AsyncSession) -> None:
    """El Anexo 8 no publica tarifa para la periodicidad catorcenal (`03`; ver
    `tarifa_isr.PARA_CFDI`). Con la tarifa **mensual** confirmada (los dos renglones sintéticos
    de `_renglones_sinteticos`, que sí pasan `tarifa_isr.validar`), el recibo se recalcula
    prorrateando por sus propios días pagados contra el mes (30 días nominales):

    Sueldo 500.00 gravados en 14 días →
    elevada = 500.00 × 30 / 14 = 1071.428571… → 1071.43 (ROUND_HALF_UP)
    Esa base cae en el renglón 2 (1000.01 en adelante, cuota 50.00, tasa 0.35):
    marginal  = (1071.43 − 1000.01) × 0.35 = 71.42 × 0.35 = 24.997 → 25.00
    completo  = 50.00 + 25.00 = 75.00
    ISR determinado = 75.00 × 14 / 30 = 35.00
    """
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_marca(db, "001", ordinario=True)
    await _sembrar_tarifa_mensual(db)
    await insertar_nomina(
        db, empresa_id=empresa.empresa_id, uuid="66666666-6666-4666-8666-666666666601",
        periodicidad="03", dias="14.000",
        percepciones=[("001", "001", "Sueldo", "500.00", "0.00")],
        deducciones=[],
    )
    await db.commit()

    resultado = await b09.consultar(db, empresa.empresa_id, _p())

    assert len(resultado.filas) == 1
    fila = resultado.filas[0]
    assert fila[_COL_ISR_DETERMINADO] == Decimal("35.00")

    banderas_prop = [b for b in resultado.banderas if b.clave == "TARIFA_PROPORCIONADA"]
    assert len(banderas_prop) == 1
    assert banderas_prop[0].severidad == "media"
    assert "66666666-6666-4666-8666-666666666601" in banderas_prop[0].ambito


async def test_periodicidad_sin_tarifa_publicada_sin_mensual_confirmada_cae_en_no_calculable(
    db: AsyncSession,
) -> None:
    """Gemela negativa: sin la tarifa mensual de repuesto confirmada, el recibo catorcenal no se
    puede calcular. El informe **sigue generándose** — la periodicidad catorcenal no entra en el
    bloqueo global de B-09 (§ del módulo), así que su falta no le quita el informe a una empresa
    que nunca paga catorcenal."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_marca(db, "001", ordinario=True)
    # Ninguna tarifa se confirma: ni la catorcenal (que no existe en el Anexo 8) ni la mensual
    # de repuesto.
    await insertar_nomina(
        db, empresa_id=empresa.empresa_id, uuid="66666666-6666-4666-8666-666666666602",
        periodicidad="03", dias="14.000",
        percepciones=[("001", "001", "Sueldo", "500.00", "0.00")],
        deducciones=[],
    )
    await db.commit()

    resultado = await b09.consultar(db, empresa.empresa_id, _p())

    assert len(resultado.filas) == 1, "el informe se genera igual: la periodicidad catorcenal no bloquea nada"
    fila = resultado.filas[0]
    assert fila[_COL_ISR_DETERMINADO] is None

    banderas_no_calc = [b for b in resultado.banderas if b.clave == "RECIBO_NO_CALCULABLE"]
    assert len(banderas_no_calc) == 1
    assert banderas_no_calc[0].severidad == "alta"


# --------------------------------------------------------------------------------------
# 12. El mismo patrón del recibo de 0 días: sin receptor o sin días pagados
# --------------------------------------------------------------------------------------


async def test_un_recibo_sin_receptor_o_sin_dias_pagados_cae_en_no_calculable(db: AsyncSession) -> None:
    """El mismo tratamiento que el recibo de 0 días pagados, para los otros dos datos del propio
    CFDI que también pueden faltar: `num_dias_pagados` es nullable en el modelo, y
    `nomina_receptor` llega por `LEFT JOIN` en `universo_nomina.universo` — un XML sin ese nodo
    (o sin el atributo) es un hueco real, no un caso de laboratorio. Ninguno de los dos debe
    tumbar la corrida."""
    eid = await _empresa_con_configuracion_confirmada(db)
    cid_sin_dias = await insertar_nomina(
        db, empresa_id=eid, uuid="77777777-7777-4777-8777-777777777701",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")], deducciones=[],
    )
    cid_sin_receptor = await insertar_nomina(
        db, empresa_id=eid, uuid="77777777-7777-4777-8777-777777777702",
        rfc_receptor="XAXX010101003",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")], deducciones=[],
    )
    await db.execute(update(Nomina).where(Nomina.comprobante_id == cid_sin_dias).values(num_dias_pagados=None))
    await db.execute(delete(NominaReceptor).where(NominaReceptor.comprobante_id == cid_sin_receptor))
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    assert len(resultado.filas) == 2, "ninguno de los dos huecos debe tumbar la corrida"
    por_uuid = {fila[b09._COL_UUID]: fila for fila in resultado.filas}
    assert por_uuid["77777777-7777-4777-8777-777777777701"][_COL_ISR_DETERMINADO] is None
    assert por_uuid["77777777-7777-4777-8777-777777777702"][_COL_ISR_DETERMINADO] is None

    banderas_no_calc = [b for b in resultado.banderas if b.clave == "RECIBO_NO_CALCULABLE"]
    assert len(banderas_no_calc) == 2
