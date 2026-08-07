"""Alarma de vigencia y sincronización de valores fiscales.

Lo que estas pruebas fijan: la alarma **no depende de internet**. La UMA cambia el 1 de febrero
y el salario mínimo el 1 de enero; esas fechas son conocidas, así que el sistema puede saber que
está desactualizado sin leer el DOF. Es la defensa que no se rompe cuando una página cambia de
estructura.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion_fiscal import ParamFiscal
from app.models.enums import OrigenValor
from app.services import sincronizacion_fiscal as sync


def _param(clave: str, valor: str, desde: date, *, confirmado: bool) -> ParamFiscal:
    return ParamFiscal(
        ejercicio=desde.year, clave=clave, valor=Decimal(valor), vigencia_desde=desde, vigencia_hasta=None,
        origen=OrigenValor.SEMILLA, fuente="prueba",
        confirmado_por="uid" if confirmado else None,
        confirmado_en=datetime(2026, 8, 6) if confirmado else None,
    )


async def test_valor_ausente_genera_alerta(db: AsyncSession) -> None:
    alertas = await sync.alertas_de_vigencia(db, date(2026, 8, 6))
    claves = {a.clave for a in alertas}
    assert "UMA_DIARIA" in claves
    assert next(a for a in alertas if a.clave == "UMA_DIARIA").motivo == "AUSENTE"


async def test_valor_propuesto_pero_sin_confirmar_genera_alerta_distinta(db: AsyncSession) -> None:
    """Distinguirlas es lo que hace la alarma accionable: una pide capturar, la otra un clic."""
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=False))
    await db.commit()

    alertas = await sync.alertas_de_vigencia(db, date(2026, 8, 6))
    de_uma = next(a for a in alertas if a.clave == "UMA_DIARIA")
    assert de_uma.motivo == "SIN_CONFIRMAR"


async def test_valor_del_ejercicio_anterior_esta_caducado(db: AsyncSession) -> None:
    """El 1 de febrero de 2026 ya pasó y el valor vigente es de 2025: caducado."""
    db.add(_param("UMA_DIARIA", "113.140000", date(2025, 2, 1), confirmado=True))
    await db.commit()

    alertas = await sync.alertas_de_vigencia(db, date(2026, 8, 6))
    de_uma = next(a for a in alertas if a.clave == "UMA_DIARIA")
    assert de_uma.motivo == "CADUCADO"
    assert de_uma.fecha_esperada == date(2026, 2, 1)


async def test_antes_de_la_fecha_de_actualizacion_no_hay_alerta(db: AsyncSession) -> None:
    """En enero de 2026, la UMA de febrero de 2025 sigue siendo la vigente: no es caducidad."""
    db.add(_param("UMA_DIARIA", "113.140000", date(2025, 2, 1), confirmado=True))
    await db.commit()

    alertas = await sync.alertas_de_vigencia(db, date(2026, 1, 15))
    assert not [a for a in alertas if a.clave == "UMA_DIARIA"]


async def test_valor_confirmado_y_al_dia_no_genera_alerta(db: AsyncSession) -> None:
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=True))
    await db.commit()
    alertas = await sync.alertas_de_vigencia(db, date(2026, 8, 6))
    assert not [a for a in alertas if a.clave == "UMA_DIARIA"]


async def test_un_valor_implausible_se_marca_sospechoso(db: AsyncSession) -> None:
    """Atrapa el dedazo (117.31 capturado como 11731) y el parseo de la columna equivocada."""
    anterior = Decimal("113.14")
    assert sync.es_implausible(anterior, Decimal("11731.00")) is True
    # El salario mínimo 2026 subió 13%: el margen debe tolerarlo sin chillar.
    assert sync.es_implausible(Decimal("278.80"), Decimal("315.04")) is False


async def test_sincronizar_falla_ruidosamente_sin_token(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nunca se traga el error dejando un valor viejo con cara de vigente."""
    monkeypatch.setattr(sync, "_token_banxico", lambda: None)
    with pytest.raises(sync.SincronizacionNoConfigurada):
        await sync.sincronizar_tipo_cambio(db, hoy=date(2026, 8, 6))


async def test_sincronizar_propone_sin_confirmar(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Como todo lo demás: propone. Ni la API más confiable activa un valor por su cuenta."""
    from app.services import configuracion_fiscal as cfg

    async def _falso_banxico(*_a: object, **_k: object) -> list[tuple[date, Decimal]]:
        return [(date(2026, 8, 5), Decimal("18.4321"))]

    monkeypatch.setattr(sync, "_token_banxico", lambda: "token-de-prueba")
    monkeypatch.setattr(sync, "_consultar_serie", _falso_banxico)

    propuestos = await sync.sincronizar_tipo_cambio(db, hoy=date(2026, 8, 6))
    assert propuestos == 1
    assert await cfg.valor_vigente(db, "TIPO_CAMBIO_USD", date(2026, 8, 5)) is None
    propuesto = await cfg.valor_propuesto(db, "TIPO_CAMBIO_USD", date(2026, 8, 5))
    assert propuesto is not None
    assert propuesto.origen is OrigenValor.SINCRONIZADO
    assert "banxico" in propuesto.fuente.lower()


# --------------------------------------------------------------------------------------
# Añadidas en esta tarea sobre los ocho casos del brief
# --------------------------------------------------------------------------------------


async def test_una_propuesta_vieja_sin_confirmar_sigue_siendo_caducidad(db: AsyncSession) -> None:
    """Lo único capturado es del ejercicio anterior y además nadie lo confirmó.

    No es `SIN_CONFIRMAR`: confirmar esa propuesta **no arreglaría nada**, porque el valor que
    activaría sigue siendo el de 2025. La acción que toca es capturar el de 2026, y ese es el
    mensaje de `CADUCADO`.
    """
    db.add(_param("UMA_DIARIA", "113.140000", date(2025, 2, 1), confirmado=False))
    await db.commit()

    de_uma = next(a for a in await sync.alertas_de_vigencia(db, date(2026, 8, 6)) if a.clave == "UMA_DIARIA")
    assert de_uma.motivo == "CADUCADO"


async def test_una_propuesta_mas_nueva_que_lo_confirmado_pide_un_clic(db: AsyncSession) -> None:
    """El valor del ejercicio está confirmado y encima llegó una corrección esperando revisión.

    Sin este caso, una fe de erratas propuesta sobre un valor ya confirmado quedaría invisible:
    la clave está "al día" y la propuesta nueva no la vería nadie.
    """
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=True))
    db.add(_param("UMA_DIARIA", "117.400000", date(2026, 7, 1), confirmado=False))
    await db.commit()

    de_uma = next(a for a in await sync.alertas_de_vigencia(db, date(2026, 8, 6)) if a.clave == "UMA_DIARIA")
    assert de_uma.motivo == "SIN_CONFIRMAR"
    assert de_uma.vigencia_desde == date(2026, 7, 1)


async def test_el_salario_minimo_cambia_el_primero_de_enero(db: AsyncSession) -> None:
    """La otra fecha del calendario: el 15 de enero de 2026 el mínimo de 2025 ya caducó,
    mientras que la UMA de 2025 todavía no (ver `test_antes_de_la_fecha_...`)."""
    db.add(_param("SALARIO_MINIMO_GENERAL", "278.800000", date(2025, 1, 1), confirmado=True))
    await db.commit()

    de_sm = next(a for a in await sync.alertas_de_vigencia(db, date(2026, 1, 15)) if a.clave == "SALARIO_MINIMO_GENERAL")
    assert de_sm.motivo == "CADUCADO"
    assert de_sm.fecha_esperada == date(2026, 1, 1)


async def test_el_tipo_de_cambio_no_entra_en_la_alarma_de_calendario(db: AsyncSession) -> None:
    """No cambia por decreto en una fecha fija, así que no tiene caducidad de calendario.

    Si entrara, estaría en rojo todos los días —nadie confirma a mano un tipo de cambio
    diario— y una alarma siempre encendida es una alarma que se aprende a ignorar.
    """
    assert "TIPO_CAMBIO_USD" not in sync.FECHAS_DE_ACTUALIZACION
    assert not [a for a in await sync.alertas_de_vigencia(db, date(2026, 8, 6)) if a.clave == "TIPO_CAMBIO_USD"]


async def test_el_margen_de_plausibilidad_tolera_la_inflacion_y_atrapa_el_orden_de_magnitud() -> None:
    """Los dos bordes del margen elegido (50%), con casos reales."""
    # La UMA sube alrededor de la inflación: 113.14 -> 117.31 es 3.7%.
    assert sync.es_implausible(Decimal("113.14"), Decimal("117.31")) is False
    # El mínimo de la ZLFN se duplicó por decreto en 2019: se marca, y está bien que se marque.
    assert sync.es_implausible(Decimal("88.36"), Decimal("176.72")) is True
    # Punto decimal corrido hacia abajo: 18.4321 leído como 1.84321.
    assert sync.es_implausible(Decimal("18.4321"), Decimal("1.84321")) is True
    # Un valor anterior no positivo no se puede comparar; se marca en vez de callarse.
    assert sync.es_implausible(Decimal("0"), Decimal("18.4321")) is True


async def test_un_valor_sincronizado_implausible_se_propone_marcado(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Se propone igual —no se descarta—, pero la `fuente` lo dice y trae la desviación.

    La `fuente` es lo que la pantalla enseña antes del botón de confirmar, así que es el
    único sitio donde la marca llega a los ojos de quien decide.
    """
    from app.services import configuracion_fiscal as cfg

    await cfg.guardar_param_fiscal(
        db, clave="TIPO_CAMBIO_USD", valor=Decimal("18.4321"), vigencia_desde=date(2026, 8, 4),
        vigencia_hasta=date(2026, 8, 4), origen=OrigenValor.MANUAL, fuente="captura previa",
    )
    await db.commit()

    async def _falso_banxico(*_a: object, **_k: object) -> list[tuple[date, Decimal]]:
        return [(date(2026, 8, 5), Decimal("184.321"))]  # columna equivocada

    monkeypatch.setattr(sync, "_token_banxico", lambda: "token-de-prueba")
    monkeypatch.setattr(sync, "_consultar_serie", _falso_banxico)

    assert await sync.sincronizar_tipo_cambio(db, hoy=date(2026, 8, 6)) == 1
    propuesto = await cfg.valor_propuesto(db, "TIPO_CAMBIO_USD", date(2026, 8, 5))
    assert propuesto is not None
    assert "SOSPECHOSO" in propuesto.fuente
    assert "900" in propuesto.fuente  # 18.4321 -> 184.321 es +900.0%


async def test_sincronizar_ignora_un_dato_con_fecha_futura(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una fecha posterior a hoy solo puede venir de un parseo mal hecho (dd/mm leído como
    mm/dd), y escribirla crearía un tramo de vigencia que empieza en el futuro."""
    from app.services import configuracion_fiscal as cfg

    async def _falso_banxico(*_a: object, **_k: object) -> list[tuple[date, Decimal]]:
        return [(date(2026, 12, 8), Decimal("18.4321"))]

    monkeypatch.setattr(sync, "_token_banxico", lambda: "token-de-prueba")
    monkeypatch.setattr(sync, "_consultar_serie", _falso_banxico)

    assert await sync.sincronizar_tipo_cambio(db, hoy=date(2026, 8, 6)) == 0
    assert await cfg.valor_propuesto(db, "TIPO_CAMBIO_USD", date(2026, 12, 8)) is None


async def test_sincronizar_es_idempotente(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Correrla dos veces con el mismo dato no reescribe nada: la segunda propone cero.

    Importa porque la tarea es diaria y `oportuno` devuelve el último dato disponible, que en
    un puente puede ser el mismo tres días seguidos. Sin esto, reescribiría la `fuente` de una
    fila que quizá alguien ya confirmó.
    """
    async def _falso_banxico(*_a: object, **_k: object) -> list[tuple[date, Decimal]]:
        return [(date(2026, 8, 5), Decimal("18.4321"))]

    monkeypatch.setattr(sync, "_token_banxico", lambda: "token-de-prueba")
    monkeypatch.setattr(sync, "_consultar_serie", _falso_banxico)

    assert await sync.sincronizar_tipo_cambio(db, hoy=date(2026, 8, 6)) == 1
    assert await sync.sincronizar_tipo_cambio(db, hoy=date(2026, 8, 6)) == 0


async def test_sincronizar_falla_ruidosamente_si_la_serie_llega_vacia(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una serie sin datos no es "todo en orden": es la API diciendo algo que no entendemos."""
    async def _falso_banxico(*_a: object, **_k: object) -> list[tuple[date, Decimal]]:
        return []

    monkeypatch.setattr(sync, "_token_banxico", lambda: "token-de-prueba")
    monkeypatch.setattr(sync, "_consultar_serie", _falso_banxico)

    with pytest.raises(sync.SincronizacionFallida):
        await sync.sincronizar_tipo_cambio(db, hoy=date(2026, 8, 6))


def test_la_respuesta_de_banxico_se_lee_sin_pasar_por_float() -> None:
    """El `dato` llega como cadena y tiene que convertirse **desde** cadena.

    `Decimal(float("18.4321"))` da 18.43209999999999894... : el error entra antes de que nadie
    pueda revisarlo, y la fila que se guarda ya no es la que publicó Banxico.
    """
    cuerpo = {
        "bmx": {
            "series": [
                {
                    "idSerie": "SF43718",
                    "titulo": "Tipo de cambio pesos por dólar E.U.A.",
                    "datos": [{"fecha": "05/08/2026", "dato": "18.4321"}, {"fecha": "06/08/2026", "dato": "N/E"}],
                }
            ]
        }
    }
    datos = sync._leer_datos(cuerpo, "SF43718")
    assert datos == [(date(2026, 8, 5), Decimal("18.4321"))]  # el "N/E" se descarta, no se vuelve cero
    assert datos[0][1] == Decimal("18.4321")


def test_una_respuesta_con_otra_forma_falla_ruidosamente() -> None:
    """Si Banxico cambia el JSON, el síntoma tiene que ser un error, no cero valores propuestos."""
    with pytest.raises(sync.SincronizacionFallida):
        sync._leer_datos({"bmx": {"series": []}}, "SF43718")
    with pytest.raises(sync.SincronizacionFallida):
        sync._leer_datos({"otra_cosa": 1}, "SF43718")


async def test_la_alarma_avisa_si_la_sincronizacion_falló(db: AsyncSession) -> None:
    """El fallo de la API no se queda en el log: sube a la misma lista que ve el administrador."""
    from app.repositories import configuracion as config_repo

    await config_repo.establecer(
        db, sync.CLAVE_ESTADO_SINCRONIZACION, {"fallo": "falta el token de Banxico", "cuando": "2026-08-06T05:00:00"}
    )
    await db.commit()

    alerta = next(a for a in await sync.alertas_de_vigencia(db, date(2026, 8, 6)) if a.clave == sync.CLAVE_BANXICO)
    assert alerta.motivo == "SINCRONIZACION_FALLIDA"
    assert "token" in alerta.detalle


async def test_la_alarma_avisa_si_el_catalogo_del_sat_no_se_puede_leer(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El catálogo ilegible cierra la captura de percepciones (503) y degrada B-01; sin este
    aviso, el administrador solo vería los dos síntomas sin la causa."""
    from app.informes import catalogos

    def _revienta() -> list[tuple[str, str]]:
        raise catalogos.CatalogoIlegible("sqlite a medio montar")

    monkeypatch.setattr(sync, "_tipos_percepcion", _revienta)

    alerta = next(a for a in await sync.alertas_de_vigencia(db, date(2026, 8, 6)) if a.clave == sync.CLAVE_CATALOGO_SAT)
    assert alerta.motivo == "CATALOGO_ILEGIBLE"


async def test_la_alarma_avisa_si_satcfdi_lleva_mucho_sin_actualizarse(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`satcfdi` versiona por fecha (`AA.M.micro`), así que su edad se sabe sin consultar PyPI.

    Sin este aviso, el síntoma de una librería vieja sería "no puedo capturar un tipo de
    percepción que el SAT ya publicó", y nadie lo relacionaría con la versión instalada.
    """
    monkeypatch.setattr(sync, "_version_de_satcfdi", lambda: "24.1.0")
    alerta = next(
        a for a in await sync.alertas_de_vigencia(db, date(2026, 8, 6)) if a.clave == sync.CLAVE_VERSION_SATCFDI
    )
    assert alerta.motivo == "LIBRERIA_DESACTUALIZADA"
    assert "24.1.0" in alerta.detalle

    monkeypatch.setattr(sync, "_version_de_satcfdi", lambda: "26.7.4")
    assert not [
        a for a in await sync.alertas_de_vigencia(db, date(2026, 8, 6)) if a.clave == sync.CLAVE_VERSION_SATCFDI
    ]


async def test_una_version_de_satcfdi_que_no_se_puede_leer_no_apaga_la_comprobacion(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el esquema de versiones cambia, la alarma lo dice en vez de desactivarse en silencio."""
    monkeypatch.setattr(sync, "_version_de_satcfdi", lambda: "1.2.3-rc1")
    alerta = next(
        a for a in await sync.alertas_de_vigencia(db, date(2026, 8, 6)) if a.clave == sync.CLAVE_VERSION_SATCFDI
    )
    assert alerta.motivo == "LIBRERIA_DESACTUALIZADA"


async def test_la_tarea_del_beat_no_corre_si_el_admin_la_apago(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mismo interruptor que las otras cuatro automatizaciones de /admin/config."""
    from app.worker import tasks

    async def _apagada(_db: object, clave: str, default: object) -> object:
        return False if clave == "auto_vigencia_fiscal" else default

    monkeypatch.setattr(tasks.config_repo, "valor", _apagada)
    resultado = await tasks._revisar_vigencia_fiscal_async()
    assert resultado == {"alertas": 0, "propuestos": 0, "razon": "desactivada"}
