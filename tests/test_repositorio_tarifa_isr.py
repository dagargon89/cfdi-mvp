"""Persistencia de las tarifas: el invariante de confirmación y los cinco casos de reimportación.

El caso que estas pruebas fijan y que es fácil de romper: **reimportar un documento cuyos renglones
cambiaron limpia la confirmación**, y reimportar sobre una corrección manual no pisa nada.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.configuracion_fiscal import TarifaIsr
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

    # Se comprueba ANTES del `rollback`, dentro de la misma transacción: los `flush()` pendientes
    # ya son visibles aquí. Una implementación entrelazada (comprobar y escribir cada tarifa en el
    # mismo bucle, en vez de comprobarlas todas antes de escribir la primera) habría escrito
    # `buena` — que va primero en la lista — antes de llegar a `protegida` y descubrir el choque.
    # Comprobar solo después del `rollback` no distinguiría los dos diseños: los flushes de una
    # transacción no comprometida se revierten sin importar en qué orden se hicieron.
    assert await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15) is None

    await db.rollback()

    # Y después del rollback, tampoco: por si acaso.
    assert await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15) is None


async def test_escribir_reverifica_la_proteccion_bajo_candado(db: AsyncSession) -> None:
    """Cierra el hueco entre la pre-comprobación de `guardar_importadas` (una lectura simple, que en
    InnoDB ve el snapshot de la transacción) y la escritura real bajo `FOR UPDATE` (que siempre lee
    el último committeado). Si el origen se volviera `MANUAL` con una huella distinta entre esos dos
    momentos, solo la comprobación de dentro de `_escribir` la vería. No hace falta simular
    concurrencia real: basta con que la protección siga aplicando al llegar a `_escribir` con
    `proteger_correccion_manual=True` sobre una fila `MANUAL` que ya está ahí con otra huella."""
    await repo.guardar_manual(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=_renglones("8.95"),
        fuente="corregido a mano",
    )
    await db.commit()

    with pytest.raises(repo.CorreccionManualProtegida):
        await repo._escribir(
            db,
            ejercicio=2026,
            periodicidad=PeriodicidadTarifa.DIAS_15,
            renglones=_renglones(),
            origen=OrigenTarifa.IMPORTADA,
            fuente="f",
            sha256=SHA_A,
            encabezado="x",
            proteger_correccion_manual=True,
        )
    await db.rollback()

    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    assert fila.origen is OrigenTarifa.MANUAL
    assert fila.renglones[1].cuota_fija == Decimal("8.95")


async def test_la_reverificacion_bajo_candado_ve_el_ultimo_estado_no_uno_cacheado(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """El `FOR UPDATE` de `_escribir` sí toma el candado a nivel de fila y sí lee el último
    committeado *a nivel de SQL* — eso nunca falló. El riesgo está una capa arriba, en el mapa de
    identidad de SQLAlchemy: si el objeto `TarifaIsr` de esa clave primaria **sigue vivo en algún
    lado de la sesión**, `db.scalar(select(TarifaIsr)...)` devuelve ese mismo objeto Python tal cual
    —con los atributos de cuando se cargó— y no lo actualiza con la fila fresca, a menos que la
    consulta lleve `populate_existing=True`.

    Importante sobre esta prueba: **no basta con reproducir la secuencia de `guardar_importadas`
    tal cual** (`obtener()` en la pre-comprobación, seguido de `_escribir`) porque `obtener()`
    siempre convierte la fila a `TarifaGuardada` y suelta el objeto ORM — sin ninguna otra
    referencia, Python lo recolecta antes de que `_escribir` vuelva a consultar esa clave primaria,
    y entonces la consulta posterior de todos modos construye un objeto nuevo con datos frescos,
    con o sin `populate_existing` (se verificó empíricamente: dos llamadas sucesivas a `obtener()`
    en la misma sesión, sin retener nada entre medias, devuelven objetos Python con `id()`
    distintos). El caso real que `populate_existing` cierra es el de **cualquier código que sí
    retenga el objeto ORM** —`db.get(TarifaIsr, ...)` en vez de pasar por `obtener()`, un endpoint
    que lo guarda para otra cosa en el mismo request— y por eso se reproduce aquí cargándolo así
    directamente y reteniéndolo vivo en `cabecera_viva` durante toda la prueba.
    """
    await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()

    # Carga el ORM crudo y lo retiene vivo — a propósito, es lo que `obtener()` nunca hace (siempre
    # lo convierte a `TarifaGuardada` y lo suelta). Simula cualquier ruta futura que sí lo haga.
    cabecera_viva = await db.get(TarifaIsr, (2026, PeriodicidadTarifa.DIAS_15))
    assert cabecera_viva is not None
    assert cabecera_viva.origen is OrigenTarifa.IMPORTADA

    # Otra sesión corrige la tarifa a mano con otros renglones, y confirma su transacción.
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as otra:
        await repo.guardar_manual(
            otra, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=_renglones("8.95"),
            fuente="corregido por otro proceso",
        )
        await otra.commit()

    # `db` reimporta el mismo documento de siempre. Sin `populate_existing=True` en el `FOR UPDATE`
    # de `_escribir`, éste devolvería el mismo objeto que `cabecera_viva` referencia —origen todavía
    # IMPORTADA— y la protección nunca se dispararía.
    with pytest.raises(repo.CorreccionManualProtegida):
        await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_B)
    await db.rollback()

    fila = await repo.obtener(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
    assert fila is not None
    assert fila.origen is OrigenTarifa.MANUAL
    assert fila.renglones[1].cuota_fija == Decimal("8.95")

    # `cabecera_viva` se sigue referenciando aquí a propósito, para que quede claro que su vida útil
    # cubre toda la prueba: si Python la recolectara antes, esto dejaría de reproducir el caso.
    assert cabecera_viva is not None


async def test_reimportar_con_la_misma_huella_que_la_correccion_manual_actualiza_el_origen(
    db: AsyncSession,
) -> None:
    """Sexto caso (ver el docstring del módulo): el documento reimportado coincide número por número
    con lo que se corrigió a mano. Ya no hay nada que proteger, así que el origen pasa de `MANUAL` a
    `IMPORTADA`: de ahora en adelante el documento vuelve a ser la fuente."""
    await repo.guardar_manual(
        db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, renglones=_renglones(), fuente="mano",
    )
    await db.commit()

    guardadas = await repo.guardar_importadas(db, [_extraida()], fuente="f", sha256=SHA_A)
    await db.commit()
    assert guardadas[0].origen is OrigenTarifa.IMPORTADA


async def test_confirmar_una_tarifa_inexistente_se_rechaza(db: AsyncSession) -> None:
    with pytest.raises(repo.NoEncontrada):
        await repo.confirmar(
            db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15, huella_revisada="0" * 64, actor="quien",
        )


async def test_borrar_una_tarifa_inexistente_se_rechaza(db: AsyncSession) -> None:
    with pytest.raises(repo.NoEncontrada):
        await repo.borrar(db, ejercicio=2026, periodicidad=PeriodicidadTarifa.DIAS_15)
