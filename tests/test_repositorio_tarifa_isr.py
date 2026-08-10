"""Persistencia de las tarifas: el invariante de confirmación y los cinco casos de reimportación.

El caso que estas pruebas fijan y que es fácil de romper: **reimportar un documento cuyos renglones
cambiaron limpia la confirmación**, y reimportar sobre una corrección manual no pisa nada.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrigenTarifa, PeriodicidadTarifa
from app.repositories import tarifa_isr as repo
from app.services import anexo8
from app.services import tarifa_isr as t

SHA_A = "a" * 64
SHA_B = "b" * 64


def _renglones(cuota_segundo: str = "7.95") -> list[t.Renglon]:
    return [
        t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
        t.Renglon(2, Decimal("416.71"), Decimal("3537.15"), Decimal(cuota_segundo), Decimal("0.0640")),
        t.Renglon(3, Decimal("3537.16"), None, Decimal("207.75"), Decimal("0.3500")),
    ]


def _extraida(cuota_segundo: str = "7.95") -> anexo8.TarifaExtraida:
    return anexo8.TarifaExtraida(
        ejercicio=2026,
        periodicidad=PeriodicidadTarifa.DIAS_15,
        encabezado="IV. Tarifa aplicable cuando hagan pagos que correspondan a un periodo de 15 dias",
        renglones=tuple(_renglones(cuota_segundo)),
    )


async def test_lo_importado_entra_sin_confirmar(db: AsyncSession) -> None:
    guardadas = await repo.guardar_importadas(db, [_extraida()], fuente="Anexo 8 DOF 28-12-2025", sha256=SHA_A)
    await db.commit()
    assert len(guardadas) == 1
    assert guardadas[0].confirmado_en is None
    assert guardadas[0].origen is OrigenTarifa.IMPORTADA
    assert guardadas[0].documento_sha256 == SHA_A
    assert await repo.vigente(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15) is None


async def test_reimportar_el_mismo_documento_es_idempotente(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    antes = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert antes is not None

    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    despues = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert despues is not None
    assert despues.huella == antes.huella
    assert len(despues.renglones) == 3


async def test_reimportar_con_los_mismos_renglones_conserva_la_confirmacion(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella,
        actor="dgarcia@planjuarez.org",
    )
    await db.commit()

    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_B)
    await db.commit()
    despues = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert despues is not None
    assert despues.confirmado_por == "dgarcia@planjuarez.org"


async def test_reimportar_con_renglones_distintos_limpia_la_confirmacion(db: AsyncSession) -> None:
    """Regla 2 de `guardar_param_fiscal`: un valor distinto es un valor nuevo y necesita que alguien
    lo vuelva a mirar. Si no, una resolución posterior activaría cifras que nadie revisó."""
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="quien",
    )
    await db.commit()

    await repo.guardar_importadas(db, [_extraida(cuota_segundo="8.95")], fuente="f", sha256=SHA_B)
    await db.commit()
    despues = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert despues is not None
    assert despues.confirmado_en is None
    assert despues.confirmado_por is None
    assert despues.renglones[1].cuota_fija == Decimal("8.95")


async def test_reimportar_sobre_una_correccion_manual_no_pisa_nada(db: AsyncSession) -> None:
    await repo.guardar_manual(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=_renglones("8.95"),
        fuente="corregido a mano",
    )
    await db.commit()

    with pytest.raises(repo.CorreccionManualProtegida):
        await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.rollback()

    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    assert fila.renglones[1].cuota_fija == Decimal("8.95")
    assert fila.origen is OrigenTarifa.MANUAL


async def test_corregir_a_mano_limpia_la_confirmacion_y_marca_el_origen(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="quien",
    )
    await db.commit()

    await repo.guardar_manual(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=_renglones("8.95"),
        fuente="corregido a mano",
    )
    await db.commit()
    despues = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert despues is not None
    assert despues.origen is OrigenTarifa.MANUAL
    assert despues.confirmado_en is None


async def test_una_correccion_que_rompe_la_continuidad_se_rechaza(db: AsyncSession) -> None:
    malos = _renglones()
    malos[2] = t.Renglon(3, Decimal("3537.00"), None, Decimal("207.75"), Decimal("0.3500"))
    with pytest.raises(t.TarifaInvalida, match="3537.16"):
        await repo.guardar_manual(
            db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=malos, fuente="x",
        )


async def test_corregir_puede_quitar_y_agregar_renglones(db: AsyncSession) -> None:
    """Un ejercicio futuro puede traer otro número de renglones; sin esto la corrección serviría
    de poco. El `PUT` recibe la lista completa, así que quitar es no mandarlo."""
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()

    dos = [
        t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
        t.Renglon(2, Decimal("416.71"), None, Decimal("7.95"), Decimal("0.3500")),
    ]
    await repo.guardar_manual(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=dos, fuente="x",
    )
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    assert len(fila.renglones) == 2


async def test_confirmar_con_una_huella_que_ya_no_corresponde_se_rechaza(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    with pytest.raises(repo.ValorCambio):
        await repo.confirmar(
            db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15,
            huella_revisada="0" * 64, actor="quien",
        )


async def test_confirmar_dos_veces_es_idempotente_y_no_reescribe_quien_confirmo(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    _, cambio_primero = await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="primera",
    )
    await db.commit()
    segunda, cambio_segundo = await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="segunda",
    )
    await db.commit()
    assert cambio_primero is True
    assert cambio_segundo is False
    assert segunda.confirmado_por == "primera"


async def test_una_tarifa_confirmada_la_devuelve_vigente(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="quien",
    )
    await db.commit()
    viva = await repo.vigente(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert viva is not None
    assert len(viva.renglones) == 3


async def test_borrar_una_tarifa_confirmada_se_rechaza(db: AsyncSession) -> None:
    """Un borrado que hace desaparecer una tarifa confirmada sin sustituto convierte un cálculo que
    funcionaba en un cálculo ausente, sin explicación."""
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    await repo.confirmar(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada=fila.huella, actor="quien",
    )
    await db.commit()
    with pytest.raises(repo.YaConfirmada):
        await repo.borrar(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)


async def test_borrar_una_propuesta_se_lleva_sus_renglones(db: AsyncSession) -> None:
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    await repo.borrar(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    await db.commit()
    assert await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15) is None


async def test_guardar_importadas_es_todo_o_nada(db: AsyncSession) -> None:
    """Si una de las tarifas del documento no se puede guardar, no se guarda ninguna: un Anexo 8 a
    medio cargar no se distingue de uno que traía menos tablas."""
    buena = _extraida()
    protegida = anexo8.TarifaExtraida(
        ejercicio=2026, periodicidad=PeriodicidadTarifa.MENSUAL, encabezado="V. Tarifa mensual",
        renglones=tuple(_renglones()),
    )
    await repo.guardar_manual(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.MENSUAL, renglones=_renglones("8.95"), fuente="mano",
    )
    await db.commit()

    with pytest.raises(repo.CorreccionManualProtegida):
        await repo.guardar_importadas(db, [buena, protegida], fuente="f", sha256=SHA_A)
    await db.rollback()

    # La buena tampoco quedó.
    assert await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15) is None
