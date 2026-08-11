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
_COL_PERIODO = b09._COL_PERIODO
_COL_NOMBRE_EMPLEADO = b09._COL_NOMBRE_EMPLEADO
_COL_NUM_EMPLEADO = b09._COL_NUM_EMPLEADO
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
_COL_ISR_RETENIDO_CFDI = b09._COL_ISR_RETENIDO_CFDI
_COL_SUBSIDIO_CFDI = b09._COL_SUBSIDIO_CFDI
_COL_DIFERENCIA_ISR = b09._COL_DIFERENCIA_ISR
_COL_DIFERENCIA_SUBSIDIO = b09._COL_DIFERENCIA_SUBSIDIO


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


async def _sembrar_param_desde_enero(db: AsyncSession, clave: str, valor: str) -> None:
    """Como `_sembrar_param`, pero con `vigencia_desde=2026-01-01` en vez de febrero: lo necesita
    la prueba de I2 (más abajo) para el factor y el tope del subsidio, que ahí se mantienen
    constantes todo el año mientras solo `UMA_MENSUAL` varía por tramo. `confirmar_param_fiscal`
    (la ruta real, no un `UPDATE` directo) ejercita el mismo invariante de confirmación que
    `_sembrar_param`."""
    await cfg.guardar_param_fiscal(
        db, clave=clave, valor=Decimal(valor), vigencia_desde=date(2026, 1, 1), origen=OrigenValor.SEMILLA,
        fuente="Fixture de prueba",
    )
    await db.commit()
    await cfg.confirmar_param_fiscal(db, clave=clave, vigencia_desde=date(2026, 1, 1), valor=Decimal(valor), actor=_ACTOR)
    await db.commit()


async def _sembrar_uma_dos_tramos(db: AsyncSession, *, valor_enero: str, valor_febrero: str) -> None:
    """Dos tramos de vigencia de `UMA_MENSUAL` dentro del mismo 2026: uno para enero
    (`vigencia_desde=2026-01-01`, `vigencia_hasta=2026-01-31`) y otro desde el 1 de febrero. Es
    la simulación mínima, dentro de un solo ejercicio, del hecho que `config/fiscal/README.md`
    documenta (la UMA cambia el 1 de febrero) y que la prueba de I2 necesita: dos fechas de pago
    del mismo año con un valor vigente distinto cada una."""
    await cfg.guardar_param_fiscal(
        db, clave="UMA_MENSUAL", valor=Decimal(valor_enero), vigencia_desde=date(2026, 1, 1),
        vigencia_hasta=date(2026, 1, 31), origen=OrigenValor.SEMILLA, fuente="Fixture de prueba",
    )
    await cfg.guardar_param_fiscal(
        db, clave="UMA_MENSUAL", valor=Decimal(valor_febrero), vigencia_desde=date(2026, 2, 1),
        origen=OrigenValor.SEMILLA, fuente="Fixture de prueba",
    )
    await db.commit()
    await cfg.confirmar_param_fiscal(
        db, clave="UMA_MENSUAL", vigencia_desde=date(2026, 1, 1), valor=Decimal(valor_enero), actor=_ACTOR
    )
    await cfg.confirmar_param_fiscal(
        db, clave="UMA_MENSUAL", vigencia_desde=date(2026, 2, 1), valor=Decimal(valor_febrero), actor=_ACTOR
    )
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
        num_empleado="101",
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

    # Encargo extra de la revisión de la tarea anterior: las tres columnas nuevas que ya se
    # contaban ("son 24") pero cuyo contenido nadie afirmaba. `fecha_pago` por defecto de
    # `insertar_nomina` es el 30 de junio de 2026, así que el periodo es el mes 6; el nombre lo
    # pone `comprobante_detalle.nombre_receptor` (el fijo por defecto del helper); el número de
    # empleado es el que se pidió explícitamente para este recibo, "101".
    fila_101 = next(f for f in resultado.filas if f[b09._COL_UUID] == "11111111-1111-4111-8111-111111111101")
    assert fila_101[_COL_PERIODO] == 6
    assert fila_101[_COL_NOMBRE_EMPLEADO] == "JUANA INVENTADA DE PRUEBA"
    assert fila_101[_COL_NUM_EMPLEADO] == "101"

    # Con el subsidio confirmado (`_empresa_con_configuracion_confirmada`), la nota de
    # `BANDERA_SIN_SUBSIDIO` no debe aparecer: la comparación sí se pudo hacer.
    assert resultado.notas == []


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
    prueba anterior: no depende del subsidio.

    Ronda de corrección de la tarea 4: sin subsidio, `isr_a_retener_teorico` es `None` en toda
    fila, así que ninguna de `COINCIDE`/`DIFERENCIA_MENOR`/`DIFERENCIA_MAYOR`/
    `DIFERENCIA_SISTEMATICA` puede dispararse — el informe sale con cero banderas de
    comparación. Sin una nota que lo diga, eso se lee como "todo coincide" cuando la verdad es
    que no se comparó nada; `resultado.notas` tiene que decirlo en español llano."""
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

    # Ninguna bandera de comparación pudo dispararse (todas dependen del subsidio), y eso tiene
    # que quedar explicado, no silencioso.
    assert [b for b in resultado.banderas if b.clave in ("COINCIDE", "DIFERENCIA_MENOR", "DIFERENCIA_MAYOR")] == []
    assert len(resultado.notas) == 1
    nota = resultado.notas[0]
    assert "no" in nota.lower() and "significa" in nota.lower()
    assert "subsidio" in nota.lower()
    assert "BANDERA_SIN_SUBSIDIO" not in nota


# --------------------------------------------------------------------------------------
# 7bis. C1+C2 — la cobertura que faltaba: las cuatro columnas de comparación, por valor
# --------------------------------------------------------------------------------------


async def test_todo_confirmado_y_correcto_no_produce_hallazgos(db: AsyncSession) -> None:
    """C1+C2, la prueba que faltaba. Antes de esta corrección, ninguna prueba de este archivo
    aseveraba las cuatro columnas de comparación (`ISR retenido en el CFDI`, `Subsidio causado en
    el CFDI`, `Diferencia de ISR`, `Diferencia de subsidio`) **por valor** — solo indirectamente,
    vía qué bandera dispara cada umbral —y esa falta de cobertura directa es lo que dejó pasar
    los dos Critical de la revisión final. Un recibo donde el proveedor de nómina timbró TODO
    correcto no debe llevar ninguna bandera de hallazgo (severidad alta o media): solo
    `COINCIDE`, que es la lectura de "este recibo no necesita revisión".

    Base 5000.00, quincenal, 15 días exactos (mismo caso base que
    `test_las_columnas_del_calculo_reproducen_la_tarifa` y la sección 13):

        ISR determinado              = 366.91  (renglón 3: 207.75 + (5000.00−3537.16)×0.1088)
        Subsidio teórico               = 267.83  (mensualizado 5000×30/15=10000.00 ≤ tope
                                                    11492.66; mensual 0.1502×3566.22=535.646244
                                                    → 535.65; del periodo 535.65×15/30=267.825
                                                    → 267.83)
        ISR a retener teórico          = max(0, 366.91 − 267.83) = 99.08
        Subsidio a entregar teórico    = max(0, 267.83 − 366.91) = 0.00 (el ISR ya cubre el
                                                                          subsidio)

    El proveedor timbra exactamente esos números: ISR retenido (`nomina_deduccion` tipo `002`)
    99.08, y en `nomina_otro_pago` (tipo `002`) `SubsidioCausado` 267.83 —el subsidio
    DETERMINADO del periodo, la columna que C2 corrige— con `Importe` (subsidio entregado en
    efectivo) 0.00, coherente con que el ISR ya lo cubre por completo:

        Diferencia de ISR      = 99.08 − 99.08   = 0.00
        Diferencia de subsidio = 267.83 − 267.83 = 0.00

    (Antes de C2, "Diferencia de subsidio" comparaba `SubsidioCausado` contra el subsidio A
    ENTREGAR teórico, no contra el subsidio teórico: 267.83 − 0.00 = 267.83, una acusación falsa
    de 267.83 pesos sobre un recibo timbrado sin ningún error.)
    """
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="99999999-9999-4999-8999-999999999901",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "99.08")],
        otros_pagos=[("002", "002", "Subsidio", "0.00", "267.83")],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    fila = resultado.filas[0]
    assert fila[_COL_ISR_A_RETENER_TEORICO] == Decimal("99.08")
    assert fila[_COL_SUBSIDIO_A_ENTREGAR_TEORICO] == Decimal("0.00")
    assert fila[_COL_ISR_RETENIDO_CFDI] == Decimal("99.08")
    assert fila[_COL_SUBSIDIO_CFDI] == Decimal("267.83")
    assert fila[_COL_DIFERENCIA_ISR] == Decimal("0.00")
    assert fila[_COL_DIFERENCIA_SUBSIDIO] == Decimal("0.00")

    hallazgos = [b for b in resultado.banderas if b.severidad in ("alta", "media")]
    assert hallazgos == []
    coincide = [b for b in resultado.banderas if b.clave == "COINCIDE"]
    assert len(coincide) == 1


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


# --------------------------------------------------------------------------------------
# 13. Tarea 4 — las ocho banderas de juicio (§6 del diseño)
#
# Todas las pruebas de esta sección usan un sueldo de 5000.00 en una quincena de 15 días
# exactos (el mismo caso base que `test_las_columnas_del_calculo_reproducen_la_tarifa`), con
# la configuración completa confirmada (tarifa + marcas + subsidio), así que
# `isr_a_retener_teorico` es siempre el mismo punto de partida para las tres primeras pruebas
# (los tres umbrales de comparación). Se calcula a mano una sola vez aquí, con la misma
# aritmética que ya fijó la tarea 3:
#
#   ISR determinado (renglón 3): 207.75 + (5000.00 − 3537.16) × 0.1088 = 366.91
#   Subsidio mensualizado: 5000.00 × 30 / 15 = 10000.00 ≤ 11492.66 (tope) → sí aplica
#   Subsidio mensual: 0.1502 × 3566.22 = 535.646244 → 535.65 (ROUND_HALF_UP)
#   Subsidio del periodo: 535.65 × 15 / 30 = 267.825 → 267.83 (ROUND_HALF_UP)
#   ISR a retener teórico: max(0, 366.91 − 267.83) = 99.08
# --------------------------------------------------------------------------------------

_ISR_A_RETENER_TEORICO_BASE = Decimal("99.08")
"""El punto de partida de las tres pruebas de umbral: ver la cuenta completa arriba."""


async def test_coincide_hasta_dos_centavos(db: AsyncSession) -> None:
    """B-09.R4, borde exacto inferior: una diferencia de exactamente 0.02 pesos —ni un centavo
    más— sigue siendo `COINCIDE`. isr_cfdi = 99.08 + 0.02 = 99.10; diferencia = 99.10 − 99.08 =
    0.02, y 0.02 ≤ 0.02 (el propio umbral), así que coincide."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="88888888-8888-4888-8888-888888888801",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "99.10")],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    assert resultado.filas[0][_COL_ISR_A_RETENER_TEORICO] == _ISR_A_RETENER_TEORICO_BASE
    coincide = [b for b in resultado.banderas if b.clave == "COINCIDE"]
    assert len(coincide) == 1
    assert coincide[0].severidad == "baja"
    assert "88888888-8888-4888-8888-888888888801" in coincide[0].ambito
    assert [b.clave for b in resultado.banderas if b.clave in ("DIFERENCIA_MENOR", "DIFERENCIA_MAYOR")] == []


async def test_diferencia_menor_hasta_un_peso(db: AsyncSession) -> None:
    """B-09.R4, borde exacto superior de `DIFERENCIA_MENOR`: una diferencia de exactamente 1.00
    peso —el borde, no un centavo antes— todavía es redondeo, no error. isr_cfdi =
    99.08 + 1.00 = 100.08; diferencia = 100.08 − 99.08 = 1.00, y 0.02 < 1.00 ≤ 1.00 (el propio
    umbral)."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="88888888-8888-4888-8888-888888888802",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "100.08")],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    menor = [b for b in resultado.banderas if b.clave == "DIFERENCIA_MENOR"]
    assert len(menor) == 1
    assert menor[0].severidad == "baja"
    assert [b.clave for b in resultado.banderas if b.clave in ("COINCIDE", "DIFERENCIA_MAYOR")] == []


async def test_diferencia_mayor_pasado_un_peso(db: AsyncSession) -> None:
    """B-09.R4, un centavo pasado el borde: 1.01 pesos de diferencia ya no es redondeo. isr_cfdi
    = 99.08 + 1.01 = 100.09; diferencia = 100.09 − 99.08 = 1.01 > 1.00."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="88888888-8888-4888-8888-888888888803",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "100.09")],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    mayor = [b for b in resultado.banderas if b.clave == "DIFERENCIA_MAYOR"]
    assert len(mayor) == 1
    assert mayor[0].severidad == "alta"
    assert [b.clave for b in resultado.banderas if b.clave in ("COINCIDE", "DIFERENCIA_MENOR")] == []


async def test_isr_cero_con_base_sin_subsidio_confirmado_avisa_con_severidad_media(db: AsyncSession) -> None:
    """Corrección de la revisión final (C1): sin el subsidio confirmado no se puede afirmar que
    esta retención de 0.00 sea el hallazgo más grave del informe (podría ser el subsidio
    cubriendo el ISR de un sueldo bajo) ni que no lo sea, así que la bandera se emite igual —
    callarla sería tan falso como acusar— pero con severidad MEDIA, no ALTA, y pidiendo confirmar
    el subsidio para saberlo con certeza (ver el docstring de `_bandera_diferencia_sistematica`...
    perdón, del bloque `ISR_CERO_CON_BASE` en `consultar`, para la justificación completa).

    Antes de esta corrección la bandera salía con severidad ALTA sin importar el subsidio, que es
    justo el defecto que `test_isr_cero_con_base_no_sale_con_el_subsidio_confirmado` (más abajo)
    expone: con el subsidio confirmado, este mismo recibo de 500.00 NO debe llevar la bandera —
    esta prueba, en cambio, aísla el caso en que el subsidio sigue sin confirmarse."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_tarifa_quincenal(db)
    await _sembrar_marca(db, "001", ordinario=True)
    await insertar_nomina(
        db, empresa_id=empresa.empresa_id, uuid="88888888-8888-4888-8888-888888888804",
        percepciones=[("001", "001", "Sueldo", "500.00", "0.00")],
        deducciones=[],
    )
    await db.commit()

    resultado = await b09.consultar(db, empresa.empresa_id, _p())

    fila = resultado.filas[0]
    assert fila[_COL_RENGLON] == 2
    assert fila[_COL_ISR_A_RETENER_TEORICO] is None

    cero_con_base = [b for b in resultado.banderas if b.clave == "ISR_CERO_CON_BASE"]
    assert len(cero_con_base) == 1
    assert cero_con_base[0].severidad == "media"
    assert "88888888-8888-4888-8888-888888888804" in cero_con_base[0].ambito


async def test_isr_cero_con_base_no_sale_con_el_subsidio_confirmado(db: AsyncSession) -> None:
    """**El escenario que expone el defecto de C1.** Mismo recibo que la prueba anterior (base
    500.00, quincenal, 15 días, ISR retenido 0.00), pero ahora con el subsidio SÍ confirmado
    (`_empresa_con_configuracion_confirmada`). Con la tarifa quincenal real, 500.00 cae en el
    renglón 2 (416.71–3537.15, cuota 7.95, tasa 0.0640):

        excedente         = 500.00 − 416.71 = 83.29
        impuesto marginal = 83.29 × 0.0640  = 5.33056 → 5.33 (ROUND_HALF_UP)
        ISR determinado   = 7.95 + 5.33     = 13.28

    Subsidio (UMA 3566.22, factor 0.1502, tope 11492.66 — los valores de 2026):

        mensualizado    = 500.00 × 30 / 15 = 1000.00 ≤ 11492.66 (tope)
        subsidio mensual = 0.1502 × 3566.22 = 535.646244 → 535.65
        subsidio periodo = 535.65 × 15 / 30 = 267.825 → 267.83

        ISR a retener teórico = max(0, 13.28 − 267.83) = 0.00

    El subsidio absorbe por completo el ISR determinado: retener 0.00 es exactamente lo correcto
    para este sueldo, y es la población que el subsidio al empleo existe para proteger. Antes de
    la corrección, esta bandera se disparaba de todos modos (el renglón por sí solo bastaba) y
    acusaba a este recibo, correctamente calculado, del hallazgo más grave del informe."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="88888888-8888-4888-8888-888888888809",
        percepciones=[("001", "001", "Sueldo", "500.00", "0.00")],
        deducciones=[],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    fila = resultado.filas[0]
    assert fila[_COL_RENGLON] == 2
    assert fila[_COL_ISR_A_RETENER_TEORICO] == Decimal("0.00")

    cero_con_base = [b for b in resultado.banderas if b.clave == "ISR_CERO_CON_BASE"]
    assert cero_con_base == []


async def test_periodo_irregular_cuando_los_dias_no_son_los_nominales(db: AsyncSession) -> None:
    """9 días pagados en una quincena (nominal: 15) es un periodo irregular — hubo prorrateo,
    y cualquier diferencia de ISR de este recibo frente a la tarifa puede venir de ahí."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="88888888-8888-4888-8888-888888888805",
        dias="9.000",
        percepciones=[("001", "001", "Sueldo", "3000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "100.00")],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    irregular = [b for b in resultado.banderas if b.clave == "PERIODO_IRREGULAR"]
    assert len(irregular) == 1
    assert irregular[0].severidad == "baja"
    assert "9" in irregular[0].mensaje
    assert "15" in irregular[0].mensaje


async def test_percepciones_extraordinarias_marca_el_recibo(db: AsyncSession) -> None:
    """El recibo trae un aguinaldo (tipo `002`, marcado `es_ingreso_ordinario = false` en
    `_empresa_con_configuracion_confirmada`): la bandera sale del dato confirmado del catálogo,
    no de una lista de tipos escrita en el código (§6 del diseño)."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="88888888-8888-4888-8888-888888888806",
        percepciones=[
            ("001", "001", "Sueldo", "5000.00", "0.00"),
            ("002", "002", "Aguinaldo", "2000.00", "0.00"),
        ],
        deducciones=[("002", "002", "ISR", "366.91")],
        total_gravado="7000.00",
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    extraordinarias = [b for b in resultado.banderas if b.clave == "PERCEPCIONES_EXTRAORDINARIAS"]
    assert len(extraordinarias) == 1
    assert extraordinarias[0].severidad == "media"
    assert "88888888-8888-4888-8888-888888888806" in extraordinarias[0].ambito


async def test_art_174_se_detecta_en_el_concepto_de_la_deduccion(db: AsyncSession) -> None:
    """Detección deliberadamente laxa (§6 del diseño): el concepto "RETENCIÓN ART. 174" —en
    mayúsculas y con acento, para probar que la normalización de verdad quita ambos— dispara la
    bandera porque contiene "174" una vez normalizado. El segundo recibo, con la deducción
    "ISR" a secas, **no** la dispara: nombrar el impuesto no es lo mismo que mencionar el
    artículo."""
    eid = await _empresa_con_configuracion_confirmada(db)
    await insertar_nomina(
        db, empresa_id=eid, uuid="88888888-8888-4888-8888-888888888807",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "RETENCIÓN ART. 174", "366.91")],
    )
    await insertar_nomina(
        db, empresa_id=eid, uuid="88888888-8888-4888-8888-888888888808",
        rfc_receptor="XAXX010101099",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    art174 = [b for b in resultado.banderas if b.clave == "PROCEDIMIENTO_ART174"]
    assert len(art174) == 1
    assert art174[0].severidad == "baja"
    assert "88888888-8888-4888-8888-888888888807" in art174[0].ambito
    assert "88888888-8888-4888-8888-888888888808" not in art174[0].ambito


# --------------------------------------------------------------------------------------
# 14. `DIFERENCIA_SISTEMATICA` — la única bandera de la corrida completa, no de una fila
#
# Los tres empleados comparten el mismo sueldo base (5000.00, quincenal, 15 días) que las
# pruebas de umbral de arriba, así que `isr_a_retener_teorico` es el mismo 99.08 para los tres.
# "Todos retenidos 50.00 por debajo de lo que dice la tarifa" es entonces
# isr_cfdi = 99.08 − 50.00 = 49.08 para los tres, y diferencia_isr = 49.08 − 99.08 = −50.00:
# la misma cifra y el mismo signo en los tres, muy por encima del umbral de 1.00 peso.
# --------------------------------------------------------------------------------------


async def test_diferencia_sistematica_exige_tres_empleados_y_el_mismo_signo(db: AsyncSession) -> None:
    """Tres empleados con la misma base y todos retenidos 50.00 por debajo de lo que dice la
    tarifa (isr_cfdi = 49.08 contra un isr_a_retener_teorico de 99.08 para los tres): eso no son
    tres errores, es otro procedimiento o una tarifa mal cargada, y el informe tiene que
    decirlo.

    Corrección de la revisión final (I1): el mensaje anterior decía "todos por debajo de lo que
    retuvo el patrón", una referencia invertida (lo que puede estar por encima o por debajo es la
    retención respecto de la TARIFA, no respecto de sí misma). `diferencia = isr_cfdi −
    isr_a_retener_teorico = 49.08 − 99.08 = −50.00 < 0`, así que aquí el patrón retuvo POR DEBAJO
    de lo que marca la tarifa — se asevera la frase completa, no solo la palabra "todos"."""
    eid = await _empresa_con_configuracion_confirmada(db)
    for n, uuid_base in enumerate(("aaaa", "bbbb", "cccc"), start=1):
        await insertar_nomina(
            db, empresa_id=eid,
            uuid=f"{uuid_base * 2}-{uuid_base}-4{uuid_base[:3]}-8{uuid_base[:3]}-{uuid_base * 3}",
            num_empleado=f"00{n}",
            percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
            deducciones=[("002", "002", "ISR", "49.08")],
        )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    sistematicas = [b for b in resultado.banderas if b.clave == "DIFERENCIA_SISTEMATICA"]
    assert len(sistematicas) == 1
    assert sistematicas[0].severidad == "alta"
    assert sistematicas[0].ambito == "informe"
    assert "todos retuvieron por debajo de lo que marca la tarifa" in sistematicas[0].mensaje.lower()


async def test_diferencia_sistematica_dice_por_encima_cuando_el_patron_retuvo_de_mas(db: AsyncSession) -> None:
    """Gemela de signo contrario de la prueba anterior (I1): tres empleados retenidos 50.00 POR
    ENCIMA de lo que marca la tarifa (isr_cfdi = 99.08 + 50.00 = 149.08 contra un
    isr_a_retener_teorico de 99.08 para los tres). `diferencia = 149.08 − 99.08 = +50.00 > 0`, así
    que el mensaje tiene que decir "por encima", no "por debajo" — antes de esta corrección el
    texto no distinguía sujeto (tarifa) de referencia (patrón), y esta prueba fija el sentido
    correcto en el caso que la prueba original no cubría."""
    eid = await _empresa_con_configuracion_confirmada(db)
    for n, uuid_base in enumerate(("aaaa", "bbbb", "cccc"), start=1):
        await insertar_nomina(
            db, empresa_id=eid,
            uuid=f"{uuid_base * 2}-{uuid_base}-4{uuid_base[:3]}-8{uuid_base[:3]}-{uuid_base * 3}",
            num_empleado=f"00{n}",
            percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
            deducciones=[("002", "002", "ISR", "149.08")],
        )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    sistematicas = [b for b in resultado.banderas if b.clave == "DIFERENCIA_SISTEMATICA"]
    assert len(sistematicas) == 1
    assert "todos retuvieron por encima de lo que marca la tarifa" in sistematicas[0].mensaje.lower()


async def test_diferencia_sistematica_no_sale_con_dos_empleados(db: AsyncSession) -> None:
    """Gemela negativa: la misma situación exacta, pero con **dos** empleados en vez de tres.
    'Todos difieren igual' es trivialmente cierto en una muestra de dos, así que la bandera no
    debe salir — es justo el ruido que el umbral de tres evita."""
    eid = await _empresa_con_configuracion_confirmada(db)
    for n, uuid_base in enumerate(("aaaa", "bbbb"), start=1):
        await insertar_nomina(
            db, empresa_id=eid,
            uuid=f"{uuid_base * 2}-{uuid_base}-4{uuid_base[:3]}-8{uuid_base[:3]}-{uuid_base * 3}",
            num_empleado=f"00{n}",
            percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
            deducciones=[("002", "002", "ISR", "49.08")],
        )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    sistematicas = [b for b in resultado.banderas if b.clave == "DIFERENCIA_SISTEMATICA"]
    assert sistematicas == []


async def test_diferencia_sistematica_no_sale_con_signos_mezclados(db: AsyncSession) -> None:
    """Tres empleados, pero dos retenidos por arriba de la tarifa y uno por abajo: diferencias
    dispersas apuntan a ajustes individuales de cada recibo, no a un procedimiento distinto, así
    que la bandera no debe salir aunque haya tres empleados y las tres diferencias superen el
    peso. isr_a_retener_teorico es 99.08 para los tres; dos reciben isr_cfdi = 99.08 + 60.00 =
    159.08 (diferencia +60.00) y uno isr_cfdi = 99.08 − 60.00 = 39.08 (diferencia −60.00)."""
    eid = await _empresa_con_configuracion_confirmada(db)
    isr_cfdi_por_empleado = ("159.08", "159.08", "39.08")
    for n, (uuid_base, isr_cfdi) in enumerate(zip(("aaaa", "bbbb", "cccc"), isr_cfdi_por_empleado), start=1):
        await insertar_nomina(
            db, empresa_id=eid,
            uuid=f"{uuid_base * 2}-{uuid_base}-4{uuid_base[:3]}-8{uuid_base[:3]}-{uuid_base * 3}",
            num_empleado=f"00{n}",
            percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
            deducciones=[("002", "002", "ISR", isr_cfdi)],
        )
    await db.commit()

    resultado = await b09.consultar(db, eid, _p())

    sistematicas = [b for b in resultado.banderas if b.clave == "DIFERENCIA_SISTEMATICA"]
    assert sistematicas == []


# --------------------------------------------------------------------------------------
# 15. I2 — el subsidio se resuelve por la fecha de pago de cada recibo, no por una del ejercicio
# --------------------------------------------------------------------------------------


async def test_el_subsidio_se_resuelve_por_la_fecha_de_pago_de_cada_recibo(db: AsyncSession) -> None:
    """Corrección de la revisión final (I2): antes la configuración se resolvía una sola vez por
    EJERCICIO, con la fecha de pago **más reciente** del año como referencia para el subsidio —
    así que un recibo de enero se calculaba con los valores vigentes en, por ejemplo, julio.
    `config/fiscal/README.md` documenta que la UMA cambia el 1 de febrero (enero de un ejercicio
    usa la del año anterior), así que en cuanto una corrida cubriera enero y febrero a la vez,
    esa resolución producía una diferencia sistemática **inventada por el propio Hub**, no por
    el proveedor de nómina: `DIFERENCIA_MAYOR` en cada recibo de enero y `DIFERENCIA_SISTEMATICA`
    sobre la corrida.

    Se simulan dos tramos de `UMA_MENSUAL` dentro de 2026 (enero: 1000.00; desde el 1 de
    febrero: 2000.00 — números redondos, no las cifras oficiales, para que la aritmética se siga
    a mano), con `SUBSIDIO_FACTOR_UMA` (0.10) y `SUBSIDIO_TOPE_INGRESO` (99999.99, muy por
    encima del gravado para que el tope nunca se cruce) constantes todo el año. Dos recibos
    idénticos por lo demás (base 5000.00, quincenal, 15 días), uno pagado el 15 de enero y otro
    el 15 de febrero:

        Subsidio mensual enero   = 0.10 × 1000.00 = 100.00 → del periodo: 100.00 × 15/30 = 50.00
        Subsidio mensual febrero = 0.10 × 2000.00 = 200.00 → del periodo: 200.00 × 15/30 = 100.00

    Si el código siguiera cacheando por ejercicio con la fecha más reciente (febrero) como
    representante, el recibo de enero saldría también con 100.00 de subsidio en vez de 50.00 —
    el defecto que esta prueba haría fallar."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_tarifa_quincenal(db)
    await _sembrar_marca(db, "001", ordinario=True)
    await _sembrar_param_desde_enero(db, "SUBSIDIO_FACTOR_UMA", "0.10")
    await _sembrar_param_desde_enero(db, "SUBSIDIO_TOPE_INGRESO", "99999.99")
    await _sembrar_uma_dos_tramos(db, valor_enero="1000.00", valor_febrero="2000.00")
    await insertar_nomina(
        db, empresa_id=empresa.empresa_id, uuid="aaaaaaaa-1111-4111-8111-111111111101",
        fecha_pago=date(2026, 1, 15), fecha_inicial_pago=date(2026, 1, 1), fecha_final_pago=date(2026, 1, 15),
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "0.00")],
    )
    await insertar_nomina(
        db, empresa_id=empresa.empresa_id, uuid="bbbbbbbb-2222-4222-8222-222222222202",
        rfc_receptor="XAXX010101002",
        fecha_pago=date(2026, 2, 15), fecha_inicial_pago=date(2026, 2, 1), fecha_final_pago=date(2026, 2, 15),
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        deducciones=[("002", "002", "ISR", "0.00")],
    )
    await db.commit()

    resultado = await b09.consultar(
        db, empresa.empresa_id,
        b09.Parametros(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 2, 28)),
    )

    por_uuid = {fila[b09._COL_UUID]: fila for fila in resultado.filas}
    assert por_uuid["aaaaaaaa-1111-4111-8111-111111111101"][_COL_SUBSIDIO_TEORICO] == Decimal("50.00")
    assert por_uuid["bbbbbbbb-2222-4222-8222-222222222202"][_COL_SUBSIDIO_TEORICO] == Decimal("100.00")
