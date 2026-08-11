"""`app.informes.configuracion_isr`: la degradación por partes de la configuración fiscal del
ISR — qué está confirmado para una fecha y qué le falta al informe.

El invariante que estas pruebas fijan, y el que más importa: **un valor sin confirmar no
cuenta como presente.** `test_una_tarifa_sin_confirmar_no_cuenta_como_presente` es la que
protege eso; si se rompe, todo el subsistema de confirmación deja de servir para algo.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.informes import configuracion_isr as ci
from app.models.configuracion_fiscal import CatalogoPercepcionMarca, ParamFiscal
from app.models.enums import BaseExencion, OrigenValor, PeriodicidadTarifa
from app.repositories import tarifa_isr as repo_tarifa
from app.services import anexo8
from app.services import configuracion_fiscal as cfg
from app.services import tarifa_isr as t

_EJERCICIO = 2026
_FECHA = date(2026, 3, 15)
_FUENTE = "Anexo 8, DOF 28-12-2025"


def _renglones() -> tuple[t.Renglon, ...]:
    return (
        t.Renglon(1, Decimal("0.01"), Decimal("1000.00"), Decimal("0.00"), Decimal("0.0500")),
        t.Renglon(2, Decimal("1000.01"), None, Decimal("50.00"), Decimal("0.3500")),
    )


async def _sembrar_tarifa(
    db: AsyncSession, periodicidad: PeriodicidadTarifa, *, confirmar: bool, sha256: str = "a" * 64
) -> None:
    extraida = anexo8.TarifaExtraida(
        ejercicio=_EJERCICIO,
        periodicidad=periodicidad,
        encabezado=f"Tarifa de prueba {periodicidad.value}",
        renglones=_renglones(),
    )
    guardadas = await repo_tarifa.guardar_importadas(db, [extraida], fuente=_FUENTE, sha256=sha256)
    await db.commit()
    if confirmar:
        fila = guardadas[0]
        await repo_tarifa.confirmar(
            db, ejercicio=_EJERCICIO, periodicidad=periodicidad, huella_revisada=fila.huella, actor="quien@revisa.mx"
        )
        await db.commit()


async def _sembrar_marca(db: AsyncSession, tipo: str, *, confirmar: bool) -> None:
    db.add(
        CatalogoPercepcionMarca(
            tipo_percepcion=tipo,
            es_ingreso_ordinario=True,
            base_exencion=BaseExencion.NINGUNA,
            factor_exencion=None,
            integra_sbc=True,
            es_provisionable=False,
            confirmado_por="quien@revisa.mx" if confirmar else None,
            confirmado_en=datetime(2026, 1, 5) if confirmar else None,
        )
    )
    await db.commit()


async def _sembrar_param(
    db: AsyncSession, clave: str, valor: str, *, desde: date, hasta: date | None = None, confirmar: bool
) -> None:
    await cfg.guardar_param_fiscal(
        db, clave=clave, valor=Decimal(valor), vigencia_desde=desde, vigencia_hasta=hasta,
        origen=OrigenValor.SEMILLA, fuente=_FUENTE,
    )
    await db.commit()
    if not confirmar:
        return
    fila = await db.get(ParamFiscal, (clave, desde))
    assert fila is not None
    fila.confirmado_por = "quien@revisa.mx"
    fila.confirmado_en = datetime(2026, 1, 5)
    await db.commit()


# --------------------------------------------------------------------------------------
# 1. Base limpia: las tres faltas
# --------------------------------------------------------------------------------------


async def test_sin_nada_confirmado_reporta_las_tres_faltas(db: AsyncSession) -> None:
    resultado = await ci.resolver(
        db,
        ejercicio=_EJERCICIO,
        en_fecha=_FECHA,
        periodicidades=[PeriodicidadTarifa.DIAS_15],
        tipos_presentes={"001"},
    )

    assert resultado.hay_tarifa(PeriodicidadTarifa.DIAS_15) is False
    assert resultado.hay_marcas({"001"}) is False
    assert resultado.hay_subsidio is False
    assert len(resultado.faltantes) == 3

    texto = " ".join(resultado.faltantes)
    # Ninguna etiqueta visible es un nombre de enum ni una clave en mayúsculas: quien lee esto
    # no sabe qué es `DIAS_15` ni `PeriodicidadTarifa`, pero sí sabe leer "Quincenal (15 días)".
    assert "DIAS_15" not in texto
    assert "PeriodicidadTarifa" not in texto
    # Dice dónde cargarlo, no solo que falta.
    assert "Configuración" in texto
    assert "Anexo 8" in texto


# --------------------------------------------------------------------------------------
# 2. El invariante central: sembrar no activa
# --------------------------------------------------------------------------------------


async def test_una_tarifa_sin_confirmar_no_cuenta_como_presente(db: AsyncSession) -> None:
    await _sembrar_tarifa(db, PeriodicidadTarifa.DIAS_15, confirmar=False)

    resultado = await ci.resolver(
        db,
        ejercicio=_EJERCICIO,
        en_fecha=_FECHA,
        periodicidades=[PeriodicidadTarifa.DIAS_15],
        tipos_presentes=set(),
    )

    assert resultado.hay_tarifa(PeriodicidadTarifa.DIAS_15) is False
    aviso_tarifa = next(f for f in resultado.faltantes if "Anexo 8" in f)
    assert "DIAS_15" not in aviso_tarifa
    assert "Quincenal" in aviso_tarifa  # la etiqueta legible, no el nombre del enum


# --------------------------------------------------------------------------------------
# 3. Degradación por partes: con tarifa y marcas, solo falta el subsidio
# --------------------------------------------------------------------------------------


async def test_con_tarifa_y_marcas_pero_sin_subsidio_solo_falta_el_subsidio(db: AsyncSession) -> None:
    await _sembrar_tarifa(db, PeriodicidadTarifa.DIAS_15, confirmar=True)
    await _sembrar_marca(db, "001", confirmar=True)

    resultado = await ci.resolver(
        db,
        ejercicio=_EJERCICIO,
        en_fecha=_FECHA,
        periodicidades=[PeriodicidadTarifa.DIAS_15],
        tipos_presentes={"001"},
    )

    assert resultado.hay_tarifa(PeriodicidadTarifa.DIAS_15) is True
    assert resultado.hay_marcas({"001"}) is True
    assert resultado.hay_subsidio is False
    assert len(resultado.faltantes) == 1
    assert resultado.faltantes[0] == ci.BANDERA_SIN_SUBSIDIO


# --------------------------------------------------------------------------------------
# 4. Las marcas se exigen solo de los tipos presentes, no de las 44 del catálogo
# --------------------------------------------------------------------------------------


async def test_las_marcas_se_exigen_solo_de_los_tipos_presentes(db: AsyncSession) -> None:
    await _sembrar_marca(db, "001", confirmar=True)
    await _sembrar_marca(db, "005", confirmar=True)
    for i in range(2, 45):
        tipo = f"{i:03d}"
        if tipo in ("001", "005"):
            continue
        await _sembrar_marca(db, tipo, confirmar=False)

    resultado = await ci.resolver(
        db, ejercicio=_EJERCICIO, en_fecha=_FECHA, periodicidades=[], tipos_presentes={"001", "005"}
    )

    assert resultado.hay_marcas({"001", "005"}) is True
    # Con un tipo de los 42 sin confirmar sí falta, para no perder el invariante de paso.
    assert resultado.hay_marcas({"001", "005", "002"}) is False
    # Sin periodicidades pedidas no hay aviso de tarifa, y con "001"/"005" confirmados no hay
    # aviso de marcas: lo único que falta en este escenario es el subsidio (no se sembró).
    assert resultado.faltantes == (ci.BANDERA_SIN_SUBSIDIO,)


# --------------------------------------------------------------------------------------
# 5. Cero N+1: no una consulta por periodicidad (regla 11)
# --------------------------------------------------------------------------------------


async def test_resolver_no_hace_una_consulta_por_periodicidad(db: AsyncSession, engine: AsyncEngine) -> None:
    await _sembrar_tarifa(db, PeriodicidadTarifa.DIAS_15, confirmar=True)

    cinco_periodicidades = [
        PeriodicidadTarifa.DIARIA,
        PeriodicidadTarifa.DIAS_7,
        PeriodicidadTarifa.DIAS_10,
        PeriodicidadTarifa.DIAS_15,
        PeriodicidadTarifa.MENSUAL,
    ]

    consultas: list[str] = []

    def _contar(conn: object, cursor: object, statement: str, parameters: object, context: object, executemany: bool) -> None:
        consultas.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _contar)
    try:
        await ci.resolver(
            db,
            ejercicio=_EJERCICIO,
            en_fecha=_FECHA,
            periodicidades=cinco_periodicidades,
            tipos_presentes={"001"},
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _contar)

    # Fijo, sin importar que se hayan pedido cinco periodicidades: dos consultas de tarifa
    # (cabeceras + renglones), tres de param_fiscal (una por clave del subsidio) y una de
    # marcas. Si esto creciera con el número de periodicidades, sería el N+1 que la regla 11
    # prohíbe — verificado dejando el número exacto, no un margen, para que un futuro cambio
    # que reintroduzca el bucle lo note de inmediato.
    assert len(consultas) == 6, f"se esperaban 6 consultas, se emitieron {len(consultas)}: {consultas}"


# --------------------------------------------------------------------------------------
# 6. El subsidio se resuelve por fecha, no por un único tramo
# --------------------------------------------------------------------------------------


async def test_el_subsidio_se_resuelve_por_fecha(db: AsyncSession) -> None:
    await _sembrar_param(
        db, "SUBSIDIO_FACTOR_UMA", "0.1310", desde=date(2026, 1, 1), hasta=date(2026, 1, 31), confirmar=True
    )
    await _sembrar_param(
        db, "SUBSIDIO_FACTOR_UMA", "0.1350", desde=date(2026, 2, 1), hasta=None, confirmar=True
    )

    resultado_enero = await ci.resolver(
        db, ejercicio=_EJERCICIO, en_fecha=date(2026, 1, 15), periodicidades=[], tipos_presentes=set()
    )
    resultado_marzo = await ci.resolver(
        db, ejercicio=_EJERCICIO, en_fecha=date(2026, 3, 15), periodicidades=[], tipos_presentes=set()
    )

    assert resultado_enero.factor_subsidio == Decimal("0.1310")
    assert resultado_marzo.factor_subsidio == Decimal("0.1350")
