"""Herramienta de línea de comandos de la configuración fiscal
(`app/scripts/administrar_configuracion.py`).

Lo que estas pruebas fijan, en una frase: **la herramienta no es una puerta trasera.** Un
script que escribe en las mismas tablas que la pantalla es exactamente la forma que tiene un
invariante de evaporarse —el código compila, el valor entra, y tres meses después un informe
calcula con una cifra que nadie miró—, así que lo que se comprueba aquí no es que el comando
"funcione" sino que **se niegue** en cada caso en que la pantalla se negaría:

- confirmar un importe que no coincide con el almacenado **no confirma** y sale con error;
- confirmar una marca con una huella vieja **no confirma**;
- capturar **no** confirma (dos actos, no uno);
- un tramo que solapa vigencias **se rechaza**.

Y dos que protegen el rastro, que es la razón de existir de la herramienta frente a la
alternativa de emitir un token y suplantar una sesión: **cada cambio deja bitácora con el
marcador de línea de comandos**, y si la bitácora falla el cambio se revierte con ella.

Cada afirmación va con su gemela negativa: sin ella, una guarda que rechazara *todo* pasaría
igual de verde y no protegería nada.

Tres trampas de la evidencia por mutación, las tres ya pisadas en esta fase
---------------------------------------------------------------------------
Ninguna prueba de este archivo se dio por buena sin romper a propósito lo que dice proteger y
comprobar que **falla**. Al hacerlo aparecieron tres formas de que esa comprobación mienta, y
quedan anotadas aquí porque se van a volver a pisar:

1. **Un `-k` que no selecciona ninguna prueba sale con código 5 y se ve igual que una prueba
   muerta.** Hay que mirar el conteo de selección, no el código de salida. (Ojo también con el
   parser del conteo: `pytest -q` no imprime "collected N items", solo el resumen final.)
2. **Una mutación que solo hace *pasar* la prueba también "cambia algo".** Hay que exigir que
   la prueba **FALLE**, no que el resultado sea distinto.
3. **El anclaje de la mutación puede casar en el sitio equivocado.** `"    if fila.valor !=
   valor:"` es subcadena de `"        if fila.valor != valor:"`, así que un `replace` sustituyó
   el `if` de `guardar_param_fiscal` en vez del de `confirmar_param_fiscal`: la mutación
   "sobrevivía" por un motivo falso. Los anclajes tienen que incluir la línea siguiente.

Y la quinta, que es de la misma familia y **ya costó tres veces en esta fase**:

5. **Una prueba que ejercita el camino del cliente NO prueba la puerta.** Toda comprobación que
   el comando hace *antes* de llamar al servicio —el vistazo previo del plan, la comparación de
   `--marcas`, la regla del `isatty`— **tapa** la guarda de dentro, así que la mutación que borra
   la guarda sobrevive y la evidencia dice que está protegida cuando no lo está. Pasó con M1
   (ronda 2, el vistazo previo tapando la comparación del importe), con el `isatty` (ronda 3, que
   además no protegía nada) y con M25 (ronda 4, `--marcas` tapando `marcas_difieren`). **Hay que
   llamar a la puerta directamente**, como hacen
   `test_la_guarda_que_decide_esta_dentro_de_la_transaccion` y
   `test_la_puerta_del_servicio_rechaza_aunque_la_marca_no_calcule_nada`.

Y una sexta, de la misma familia pero al revés en el tiempo, que apareció al corregir B-08
(`tests/test_informe_b08.py`, ronda 1):

6. **Arreglar un defecto puede desactivar en silencio la protección de una prueba en otro sitio,
   y la evidencia vieja sigue pareciendo válida.** *Defensa en profundidad buena, prueba muerta
   mala.* En B-08 el arreglo de un Critical hizo que el promedio del salario diario **descartara**
   los periodos sin sueldo; a partir de ahí, la mutación que quitaba el filtro de nóminas
   ordinarias ya no cambiaba el resultado del escenario de su prueba —la nómina extraordinaria del
   fixture era justamente un periodo sin sueldo—, así que esa prueba dejó de proteger el filtro que
   dice proteger **sin que nadie la tocara**. Solo se vio porque la ronda de corrección volvió a
   correr las mutaciones **viejas**, no únicamente las nuevas.

   La lección práctica: **al arreglar un defecto, reverifica las mutaciones anteriores del mismo
   módulo.** Una mutación que muere hoy puede sobrevivir mañana por un arreglo correcto hecho en
   otra parte, y ninguna suite verde lo delata. Si una mutación vieja empieza a sobrevivir, el
   fixture es lo que hay que reforzar (en B-08: darle a la nómina extraordinaria una percepción de
   sueldo, para que incluirla vuelva a cambiar la cifra), no la mutación lo que hay que retirar.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bitacora import Bitacora
from app.models.configuracion_fiscal import (
    CatalogoPercepcionMarca,
    ConfiguracionEmpresa,
    MapConceptoProvision,
    MapDepartamento,
    ParamFiscal,
)
from app.models.enums import BaseExencion, CategoriaProvision, EstatusCfdi, OrigenValor, RolGlobal, ZonaSalarial
from app.models.nomina import NominaDeduccion, NominaPercepcion, NominaReceptor
from app.scripts import administrar_configuracion as cli
from app.services import configuracion_fiscal as cfg
from tests import factories

ACTOR = "admin@demo.test"
RFC_EMPRESA = "CHL960913IX9"


async def _admin(db: AsyncSession) -> None:
    await factories.crear_usuario(db, uid="uid-admin", correo=ACTOR, rol_global=RolGlobal.ADMIN)


def _args(*argv: str) -> argparse.Namespace:
    return cli.construir_parser().parse_args(list(argv))


async def _correr(db: AsyncSession, *argv: str) -> int:
    """Corre un comando y devuelve **el código de salida que vería el shell**."""
    return await cli.ejecutar(db, _args(*argv))


def _param(
    clave: str,
    valor: str,
    desde: date,
    *,
    hasta: date | None = None,
    confirmado: bool = False,
    origen: OrigenValor = OrigenValor.SEMILLA,
) -> ParamFiscal:
    return ParamFiscal(
        clave=clave,
        vigencia_desde=desde,
        ejercicio=desde.year,
        valor=Decimal(valor),
        vigencia_hasta=hasta,
        origen=origen,
        fuente="INEGI, boletín UMA 2026",
        confirmado_por="otro@demo.test" if confirmado else None,
        confirmado_en=datetime(2026, 8, 1, 9, 0, 0) if confirmado else None,
    )


def _marca(
    tipo: str, *, nota: str | None = None, tope: bool = False, sin_multiplicador: bool = False
) -> CatalogoPercepcionMarca:
    return CatalogoPercepcionMarca(
        tipo_percepcion=tipo,
        es_ingreso_ordinario=False,
        base_exencion=BaseExencion.PORCENTAJE,
        factor_exencion=Decimal("100.0000"),
        integra_sbc=False,
        es_provisionable=False,
        sujeto_a_tope_conjunto=tope,
        multiplicador_no_derivable=sin_multiplicador,
        nota_revision=nota,
    )


def _huella_marcas(fila: CatalogoPercepcionMarca) -> str:
    """La huella de las seis marcas de una fila, tal como la muestra `estado --percepciones`."""
    return cfg.huella_de_marcas(cfg.MarcasQueSeConfirman.de_fila(fila))


async def _bitacora(db: AsyncSession, accion: str) -> list[Bitacora]:
    return list((await db.scalars(select(Bitacora).where(Bitacora.accion == accion))).all())


async def _contar(db: AsyncSession, modelo: Any) -> int:
    return (await db.scalar(select(func.count()).select_from(modelo))) or 0


# --------------------------------------------------------------------------------------
# 1. Confirmar un importe: la guarda del valor
# --------------------------------------------------------------------------------------


async def test_confirmar_un_valor_que_no_coincide_no_confirma(db: AsyncSession) -> None:
    """El caso real: la propuesta cambió entre que se leyó el estado y que se tecleó el
    comando (una recarga de semillas, otro administrador, Banxico). Sin esta guarda la
    herramienta sería justo la forma de confirmar a ciegas lo que el invariante impide."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "118.000000", date(2026, 2, 1)))
    await db.commit()

    codigo = await _correr(
        db, "confirmar-valor", "--actor", ACTOR, "--valor", "UMA_DIARIA", "117.31", "2026-02-01", "--si"
    )

    assert codigo == 1, "un valor que no coincide tiene que salir con código distinto de cero"
    db.expire_all()
    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None and fila.confirmado_en is None
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None
    assert await _bitacora(db, "confirmar_param_fiscal") == []


async def test_confirmar_el_valor_que_si_coincide_lo_activa(db: AsyncSession) -> None:
    """La gemela: sin ella, una guarda que rechazara *todo* pasaría igual de verde."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "118.000000", date(2026, 2, 1)))
    await db.commit()

    codigo = await _correr(
        db, "confirmar-valor", "--actor", ACTOR, "--valor", "UMA_DIARIA", "118.00", "2026-02-01", "--si"
    )

    assert codigo == 0
    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) == Decimal("118.000000")
    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None and fila.confirmado_por == ACTOR


async def test_la_guarda_que_decide_esta_dentro_de_la_transaccion(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El vistazo previo que imprime el plan es cortesía, no la guarda.

    Sin esta prueba, quitar la comparación de `cfg.confirmar_param_fiscal` **no rompería
    ninguna otra**: el vistazo previo la taparía y la evidencia por mutación diría que la
    guarda del servicio está protegida cuando no lo estaría (verificado — la mutación
    sobrevivía). Aquí se hace mentir al vistazo, que es también lo que pasa de verdad cuando
    otro escritor cambia la cifra entre que se imprimió el plan y que la persona respondió.
    """
    await _admin(db)
    db.add(_param("UMA_DIARIA", "118.000000", date(2026, 2, 1)))
    await db.commit()

    async def _vistazo_que_miente(*_args: Any, **_kwargs: Any) -> cli._TramoLeido:
        return cli._TramoLeido(
            valor=Decimal("117.31"),
            ejercicio=2026,
            vigencia_hasta=None,
            origen=OrigenValor.SEMILLA,
            fuente="INEGI, boletín UMA 2026",
            confirmado_por=None,
            confirmado=False,
        )

    monkeypatch.setattr(cli, "leer_tramo", _vistazo_que_miente)

    codigo = await _correr(
        db, "confirmar-valor", "--actor", ACTOR, "--valor", "UMA_DIARIA", "117.31", "2026-02-01", "--si"
    )

    assert codigo == 1, "la comparación bajo candado tiene que rechazarlo aunque el plan dijera que sí"
    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None
    assert await _bitacora(db, "confirmar_param_fiscal") == []


async def test_un_lote_no_confirma_ninguno_si_uno_no_coincide(db: AsyncSession) -> None:
    """Los cinco valores de 2026 se confirman juntos. Confirmar tres y morir en el cuarto
    dejaría los informes calculando con media tabla, que es peor que no calcular."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    db.add(_param("UMA_MENSUAL", "3566.220000", date(2026, 2, 1)))
    await db.commit()

    codigo = await _correr(
        db,
        "confirmar-valor",
        "--actor",
        ACTOR,
        "--valor",
        "UMA_DIARIA",
        "117.31",
        "2026-02-01",
        "--valor",
        "UMA_MENSUAL",
        "9999.99",  # este no coincide
        "2026-02-01",
        "--si",
    )

    assert codigo == 1
    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None, (
        "el que sí coincidía tampoco se confirma: el lote es todo o nada"
    )
    assert await _bitacora(db, "confirmar_param_fiscal") == []


async def test_el_lote_completo_se_confirma_de_una(db: AsyncSession) -> None:
    """La gemela del lote."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    db.add(_param("UMA_MENSUAL", "3566.220000", date(2026, 2, 1)))
    await db.commit()

    codigo = await _correr(
        db,
        "confirmar-valor",
        "--actor",
        ACTOR,
        "--valor",
        "UMA_DIARIA",
        "117.31",
        "2026-02-01",
        "--valor",
        "UMA_MENSUAL",
        "3566.22",
        "2026-02-01",
        "--si",
    )

    assert codigo == 0
    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) == Decimal("117.31")
    assert await cfg.valor_vigente(db, "UMA_MENSUAL", date(2026, 6, 30)) == Decimal("3566.22")
    assert len(await _bitacora(db, "confirmar_param_fiscal")) == 2


# --------------------------------------------------------------------------------------
# 2. Confirmar una marca: la guarda de la huella
# --------------------------------------------------------------------------------------


async def test_confirmar_una_marca_con_una_huella_vieja_no_confirma(db: AsyncSession) -> None:
    """El escenario concurrente: se leyó la marca sin duda (o con otra), alguien le agregó
    una, y el comando llega tarde. Confirmar significa responder por lo que se miró."""
    await _admin(db)
    fila = _marca("010", nota="Revisar el art. 93 fracción XIV.")
    db.add(fila)
    await db.commit()
    huella_vieja = cfg.huella_de_nota("Revisar el art. 93 fracción XIV.")

    fila.nota_revision = "Ojo: la exención cambió con la reforma de 2026."
    await db.commit()

    codigo = await _correr(
        db, "confirmar-marca", "010", "--huella", str(huella_vieja),
        "--marcas", _huella_marcas(fila), "--actor", ACTOR, "--si",
    )

    assert codigo == 1
    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}, "una duda no vista no puede acabar confirmada"
    assert await _bitacora(db, "confirmar_marca_percepcion") == []


async def test_confirmar_una_marca_con_la_huella_vigente_si_confirma(db: AsyncSession) -> None:
    """La gemela: leer la duda de hoy y confirmar funciona sin fricción."""
    await _admin(db)
    nota = "Ojo: la exención cambió con la reforma de 2026."
    fila = _marca("010", nota=nota)
    db.add(fila)
    await db.commit()

    codigo = await _correr(
        db, "confirmar-marca", "010", "--huella", str(cfg.huella_de_nota(nota)),
        "--marcas", _huella_marcas(fila), "--actor", ACTOR, "--si",
    )

    assert codigo == 0
    db.expire_all()
    assert set(await cfg.marcas_de_percepcion(db)) == {"010"}


async def test_sin_duda_no_sirve_cuando_la_marca_si_tiene_una(db: AsyncSession) -> None:
    """`--sin-duda` es una afirmación ("la marca que revisé no tenía ninguna"), no un atajo
    para saltarse la huella. Si la marca sí tiene duda, es mentira y se rechaza."""
    await _admin(db)
    fila = _marca("010", nota="Revisar el art. 93 fracción XIV.")
    db.add(fila)
    await db.commit()

    codigo = await _correr(
        db, "confirmar-marca", "010", "--sin-duda", "--marcas", _huella_marcas(fila), "--actor", ACTOR, "--si"
    )

    assert codigo == 1
    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}


async def test_sin_duda_si_sirve_cuando_la_marca_no_tiene_ninguna(db: AsyncSession) -> None:
    """La gemela: 5 de las 44 marcas sembradas no traen duda, y la huella no puede volverlas
    más costosas de confirmar."""
    await _admin(db)
    fila = _marca("010", nota=None)
    db.add(fila)
    await db.commit()

    codigo = await _correr(
        db, "confirmar-marca", "010", "--sin-duda", "--marcas", _huella_marcas(fila), "--actor", ACTOR, "--si"
    )

    assert codigo == 0
    db.expire_all()
    assert set(await cfg.marcas_de_percepcion(db)) == {"010"}


async def test_confirmar_una_marca_exige_decir_algo_sobre_la_duda(db: AsyncSession) -> None:
    """Sin `--huella` ni `--sin-duda` no hay default: este es el comando que activa un valor
    fiscal, y omitir el campo sería confirmar sin decir qué se tenía delante."""
    await _admin(db)
    fila = _marca("010", nota=None)
    db.add(fila)
    await db.commit()

    codigo = await _correr(db, "confirmar-marca", "010", "--marcas", _huella_marcas(fila), "--actor", ACTOR, "--si")

    assert codigo == 1
    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}


# --------------------------------------------------------------------------------------
# 3. Capturar no confirma, y no se salta la puerta de escritura
# --------------------------------------------------------------------------------------


async def test_capturar_deja_el_valor_sin_confirmar(db: AsyncSession) -> None:
    """Capturar y confirmar son dos actos distintos, igual que en la pantalla: fusionarlos
    dejaría entrar un valor fiscal a un cálculo sin que nadie lo mirara."""
    await _admin(db)

    codigo = await _correr(
        db,
        "capturar-valor",
        "UMA_DIARIA",
        "--valor",
        "117.31",
        "--vigencia-desde",
        "2026-02-01",
        "--fuente",
        "DOF 2026-01-15",
        "--actor",
        ACTOR,
        "--si",
    )

    assert codigo == 0
    db.expire_all()
    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None
    assert fila.origen is OrigenValor.MANUAL
    assert fila.confirmado_en is None, "capturar NO confirma"
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None


async def test_confirmar_lo_capturado_si_lo_activa(db: AsyncSession) -> None:
    """La gemela: el segundo acto deliberado es lo que hace que el valor calcule."""
    await _admin(db)
    await _correr(
        db, "capturar-valor", "UMA_DIARIA", "--valor", "117.31", "--vigencia-desde", "2026-02-01",
        "--fuente", "DOF 2026-01-15", "--actor", ACTOR, "--si",
    )

    codigo = await _correr(
        db, "confirmar-valor", "--actor", ACTOR, "--valor", "UMA_DIARIA", "117.31", "2026-02-01", "--si"
    )

    assert codigo == 0
    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) == Decimal("117.31")


async def test_capturar_un_tramo_que_solapa_vigencias_se_rechaza(db: AsyncSession) -> None:
    """La regla que solo vive dentro de `guardar_param_fiscal`. Comprobarla aquí es lo que
    demuestra que la herramienta **pasa por la puerta** y no construye el `ParamFiscal` a
    mano: si lo construyera, este caso entraría sin ruido y toda nómina pagada en el traslape
    tomaría el valor equivocado."""
    await _admin(db)
    db.add(_param("SALARIO_MINIMO_GENERAL", "315.040000", date(2026, 1, 1)))
    await db.commit()

    codigo = await _correr(
        db,
        "capturar-valor",
        "SALARIO_MINIMO_GENERAL",
        "--valor",
        "330.00",
        "--vigencia-desde",
        "2026-06-15",  # el año mal tecleado: debía ser 2027-01-01
        "--fuente",
        "CONASAMI 2027",
        "--actor",
        ACTOR,
        "--si",
    )

    assert codigo == 1
    db.expire_all()
    assert await _contar(db, ParamFiscal) == 1, "no se escribe un segundo tramo abierto de la misma clave"


async def test_capturar_un_tramo_que_no_solapa_si_entra(db: AsyncSession) -> None:
    """La gemela: cerrar el tramo viejo y abrir el nuevo es exactamente lo que se espera que
    funcione. Sin esto, la prueba de arriba pasaría igual con un comando que rechazara todo."""
    await _admin(db)
    db.add(_param("SALARIO_MINIMO_GENERAL", "315.040000", date(2026, 1, 1), hasta=date(2026, 12, 31)))
    await db.commit()

    codigo = await _correr(
        db, "capturar-valor", "SALARIO_MINIMO_GENERAL", "--valor", "330.00", "--vigencia-desde", "2027-01-01",
        "--fuente", "CONASAMI 2027", "--actor", ACTOR, "--si",
    )

    assert codigo == 0
    db.expire_all()
    assert await _contar(db, ParamFiscal) == 2


async def test_el_importe_se_convierte_desde_texto_y_no_desde_float(db: AsyncSession) -> None:
    """`Decimal(float("12345678901.123456"))` ya trae el error antes de que nadie lo pueda
    corregir: se convierte en `...455`. La herramienta lee el importe como texto, así que la
    cifra almacenada es exactamente la que se tecleó."""
    await _admin(db)
    exacto = "12345678901.123456"

    codigo = await _correr(
        db, "capturar-valor", "UMA_ANUAL", "--valor", exacto, "--vigencia-desde", "2026-02-01",
        "--fuente", "prueba de precisión", "--actor", ACTOR, "--si",
    )

    assert codigo == 0
    db.expire_all()
    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_ANUAL"))
    assert fila is not None
    assert fila.valor == Decimal(exacto)
    assert fila.valor != Decimal(str(float(exacto))), "pasar por float habría corrompido el último dígito"


# --------------------------------------------------------------------------------------
# 4. La bitácora: el marcador de línea de comandos, y su atomicidad
# --------------------------------------------------------------------------------------


async def test_la_bitacora_dice_que_el_cambio_entro_por_la_terminal(db: AsyncSession) -> None:
    """Es el punto de la herramienta. La alternativa descartada era emitir un token de
    Firebase y llamar a la API: el rastro diría que alguien usó la pantalla cuando no fue así."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    assert await _correr(
        db, "confirmar-valor", "--actor", ACTOR, "--valor", "UMA_DIARIA", "117.31", "2026-02-01", "--si"
    ) == 0

    filas = await _bitacora(db, "confirmar_param_fiscal")
    assert len(filas) == 1
    detalle = filas[0].detalle
    assert detalle is not None
    assert detalle["via"] == cli.VIA_LINEA_DE_COMANDOS
    assert detalle["herramienta"] == "app.scripts.administrar_configuracion"
    assert filas[0].actor == ACTOR
    assert filas[0].entidad == "param_fiscal:UMA_DIARIA@2026-02-01"
    # El anterior y el nuevo, que es lo que sustituye al diff de git en una configuración que
    # se administra sin archivos.
    assert detalle["anterior"] == {"valor": "117.310000", "confirmado": False}
    assert detalle["nuevo"] == {"valor": "117.310000", "confirmado": True}


async def test_la_misma_confirmacion_por_la_pantalla_no_lleva_el_marcador(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """La gemela que le da sentido al marcador: si la pantalla también lo pusiera, no
    distinguiría nada y la bitácora seguiría sin poder decir por dónde entró el cambio."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    r = await client.post(
        "/v1/configuracion/fiscal/UMA_DIARIA/confirmar",
        json={"vigencia_desde": "2026-02-01", "valor": "117.31"},
        headers={"Authorization": "Bearer uid-admin"},
    )
    assert r.status_code == 200, r.text

    filas = await _bitacora(db, "confirmar_param_fiscal")
    assert len(filas) == 1
    assert filas[0].detalle is not None
    assert "via" not in filas[0].detalle


async def test_capturar_deja_el_anterior_y_el_nuevo_con_marcador(db: AsyncSession) -> None:
    await _admin(db)
    db.add(_param("UMA_DIARIA", "113.140000", date(2026, 2, 1), confirmado=True))
    await db.commit()

    assert await _correr(
        db, "capturar-valor", "UMA_DIARIA", "--valor", "117.31", "--vigencia-desde", "2026-02-01",
        "--fuente", "DOF 2026-01-15", "--actor", ACTOR, "--si",
    ) == 0

    filas = await _bitacora(db, "capturar_param_fiscal")
    assert len(filas) == 1
    detalle = filas[0].detalle
    assert detalle is not None
    assert detalle["via"] == cli.VIA_LINEA_DE_COMANDOS
    assert detalle["anterior"]["valor"] == "113.140000"
    assert detalle["anterior"]["confirmado"] is True
    assert detalle["nuevo"]["valor"] == "117.310000"
    # La cifra cambió, así que la confirmación anterior se limpió: la regla vive dentro de
    # `guardar_param_fiscal` y la herramienta la hereda por pasar por ahí.
    assert detalle["nuevo"]["confirmado"] is False


async def test_si_la_bitacora_falla_la_confirmacion_se_revierte(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regla 8: la bitácora va en la misma transacción. Un valor fiscal activado sin rastro de
    quién lo activó es peor que un valor sin activar."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    async def _revienta(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("la bitácora no se pudo escribir")

    monkeypatch.setattr(cli.bitacora_service, "registrar", _revienta)

    with pytest.raises(RuntimeError):
        await _correr(
            db, "confirmar-valor", "--actor", ACTOR, "--valor", "UMA_DIARIA", "117.31", "2026-02-01", "--si"
        )

    db.expire_all()
    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None and fila.confirmado_en is None, "sin bitácora no queda confirmación"
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None


async def test_con_la_bitacora_sana_la_confirmacion_queda(db: AsyncSession) -> None:
    """La gemela de la reversión: sin ella, un comando que nunca escribiera nada pasaría la
    prueba de arriba."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    assert await _correr(
        db, "confirmar-valor", "--actor", ACTOR, "--valor", "UMA_DIARIA", "117.31", "2026-02-01", "--si"
    ) == 0

    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) == Decimal("117.31")
    assert len(await _bitacora(db, "confirmar_param_fiscal")) == 1


# --------------------------------------------------------------------------------------
# 5. Seguro de correr: el actor, y no aplicar nada que nadie mirara
# --------------------------------------------------------------------------------------


async def test_un_actor_que_no_es_usuario_del_hub_se_rechaza(db: AsyncSession) -> None:
    """Un correo mal tecleado deja una bitácora que ya no se puede atribuir a nadie."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    codigo = await _correr(
        db, "confirmar-valor", "--actor", "dgarcia@planjuarez.ogr", "--valor", "UMA_DIARIA",
        "117.31", "2026-02-01", "--si",
    )

    assert codigo == 1
    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None


async def test_un_actor_externo_declarado_si_pasa(db: AsyncSession) -> None:
    """La gemela: la salida explícita para una recuperación ante desastre donde todavía no
    hay usuarios. Que exista es lo que hace que la comprobación no bloquee lo legítimo."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    codigo = await _correr(
        db, "confirmar-valor", "--actor", "consultor@externo.mx", "--actor-externo",
        "--valor", "UMA_DIARIA", "117.31", "2026-02-01", "--si",
    )

    assert codigo == 0
    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) == Decimal("117.31")
    assert (await _bitacora(db, "confirmar_param_fiscal"))[0].actor == "consultor@externo.mx"


async def test_sin_terminal_y_sin_bandera_no_escribe_nada(db: AsyncSession) -> None:
    """Un cron al que se le olvidó `--si` tiene que fallar, no aplicar cambios que nadie miró.
    (Bajo pytest `sys.stdin` no es una terminal, que es justo el caso que se prueba.)"""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    codigo = await _correr(db, "confirmar-valor", "--actor", ACTOR, "--valor", "UMA_DIARIA", "117.31", "2026-02-01")

    assert codigo == 1
    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None


async def test_responder_que_no_cancela_sin_escribir(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Y el default de la pregunta es **no**: cualquier cosa que no sea "s" cancela."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    async def _dice_que_no(*_a: Any, **_k: Any) -> bool:
        return False

    monkeypatch.setattr(cli, "pregunta", _dice_que_no)

    codigo = await _correr(db, "confirmar-valor", "--actor", ACTOR, "--valor", "UMA_DIARIA", "117.31", "2026-02-01")

    assert codigo == 1
    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None


# --------------------------------------------------------------------------------------
# 6. `estado`: lo que sustituye a mirar la pantalla
# --------------------------------------------------------------------------------------


async def test_estado_se_lee_en_una_terminal_y_dice_lo_que_decide(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """No es un volcado de JSON: es lo que alguien lee para decidir si confirma. Tiene que
    traer la cifra, la vigencia, la procedencia y **si está confirmado**, en español."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    db.add(_param("SALARIO_MINIMO_ZLFN", "440.870000", date(2026, 1, 1), confirmado=True))
    await db.commit()

    assert await _correr(db, "estado") == 0

    salida = capsys.readouterr().out
    assert '"clave":' not in salida and not salida.lstrip().startswith("{"), "no es un volcado de JSON"
    assert "UMA_DIARIA" in salida
    assert "117.310000" in salida
    assert "2026-02-01" in salida
    assert "INEGI, boletín UMA 2026" in salida
    assert "sin confirmar no calcula" in salida, "el estado que decide si el valor se usa"
    assert "otro@demo.test" in salida, "quién confirmó el que sí está confirmado"
    # Las claves de las que no hay ni propuesta, que es el tercer estado del cuadro.
    assert "UMA_MENSUAL" in salida
    assert "ALERTAS DE VIGENCIA" in salida


async def test_estado_no_miente_cuando_no_hay_nada(db: AsyncSession, capsys: pytest.CaptureFixture[str]) -> None:
    """La gemela: con la tabla vacía tiene que decirlo, no imprimir un cuadro en blanco que
    se lea como "todo en orden"."""
    await _admin(db)

    assert await _correr(db, "estado") == 0

    salida = capsys.readouterr().out
    assert "0 capturado(s), 0 confirmado(s)" in salida
    assert "los informes reportarán todo como faltante" in salida


# --------------------------------------------------------------------------------------
# 7. Configuración de una empresa
# --------------------------------------------------------------------------------------


async def test_configurar_empresa_guarda_la_zona_salarial(db: AsyncSession) -> None:
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id

    codigo = await _correr(
        db, "configurar-empresa", "--empresa-id", str(empresa_id), "--zona-salarial", "ZLFN",
        "--actor", ACTOR, "--si",
    )

    assert codigo == 0
    db.expire_all()
    config = await db.get(ConfiguracionEmpresa, empresa_id)
    assert config is not None and config.zona_salarial is ZonaSalarial.ZLFN
    detalle = (await _bitacora(db, "guardar_configuracion_empresa"))[0].detalle
    assert detalle is not None and detalle["via"] == cli.VIA_LINEA_DE_COMANDOS


async def test_configurar_empresa_conserva_lo_que_no_se_menciona(db: AsyncSession) -> None:
    """Al revés que el `PUT` de la pantalla, que reemplaza los tres campos porque los tres
    están a la vista. En una terminal, `--zona-salarial ZLFN` borrando los días de aguinaldo
    que alguien capturó el mes pasado sería una pérdida silenciosa."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    db.add(ConfiguracionEmpresa(empresa_id=empresa_id, dias_aguinaldo=30))
    await db.commit()

    assert await _correr(
        db, "configurar-empresa", "--empresa-id", str(empresa_id), "--zona-salarial", "ZLFN",
        "--actor", ACTOR, "--si",
    ) == 0

    db.expire_all()
    config = await db.get(ConfiguracionEmpresa, empresa_id)
    assert config is not None
    assert config.zona_salarial is ZonaSalarial.ZLFN
    assert config.dias_aguinaldo == 30, "lo que no se menciona no se borra"


async def test_borrar_un_campo_de_la_empresa_exige_su_propia_bandera(db: AsyncSession) -> None:
    """La gemela: borrar tiene que ser expresable, y explícito."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    db.add(ConfiguracionEmpresa(empresa_id=empresa_id, dias_aguinaldo=30))
    await db.commit()

    assert await _correr(
        db, "configurar-empresa", "--empresa-id", str(empresa_id), "--sin-dias-aguinaldo",
        "--actor", ACTOR, "--si",
    ) == 0

    db.expire_all()
    config = await db.get(ConfiguracionEmpresa, empresa_id)
    assert config is not None and config.dias_aguinaldo is None


# --------------------------------------------------------------------------------------
# 8. Clasificar conceptos y departamentos
# --------------------------------------------------------------------------------------


async def _nomina(db: AsyncSession, empresa_id: int, uuid: str, departamento: str) -> None:
    """Un CFDI de nómina emitido por la empresa, con dos percepciones y una deducción."""
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa_id, uuid=uuid, rfc_emisor=RFC_EMPRESA, tipo_comprobante="N",
        estatus=EstatusCfdi.VIGENTE,
    )
    cid = comprobante.comprobante_id
    db.add(NominaReceptor(comprobante_id=cid, departamento=departamento))
    db.add(
        NominaPercepcion(
            comprobante_id=cid, tipo_percepcion="001", clave="001", concepto="SUELDO",
            importe_gravado=Decimal("8000.00"), importe_exento=Decimal("0.00"),
        )
    )
    db.add(
        NominaPercepcion(
            comprobante_id=cid, tipo_percepcion="001", clave="019", concepto="VACACIONES A TIEMPO",
            importe_gravado=Decimal("500.00"), importe_exento=Decimal("0.00"),
        )
    )
    db.add(
        NominaDeduccion(
            comprobante_id=cid, tipo_deduccion="001", clave="IMSS", concepto="IMSS", importe=Decimal("250.00")
        )
    )
    await db.commit()


async def test_clasificar_rechaza_una_clave_que_la_nomina_nunca_emitio(db: AsyncSession) -> None:
    """Las claves las inventa el sistema de nómina del patrón: un dedazo produce un mapeo que
    no casa con nada mientras el concepto de verdad sigue sin clasificar. Silencioso en las
    dos puntas, igual que `150` por `015` en las marcas de percepción."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    await _nomina(db, empresa_id, "88888888-8888-8888-8888-888888888881", "VENTAS")

    codigo = await _correr(
        db, "clasificar", "--empresa-id", str(empresa_id),
        "--concepto", "P/001/091", "VACACIONES",  # 091 en vez de 019
        "--actor", ACTOR, "--si",
    )

    assert codigo == 1
    db.expire_all()
    assert await _contar(db, MapConceptoProvision) == 0


async def test_clasificar_una_clave_observada_si_entra(db: AsyncSession) -> None:
    """La gemela: la clave que la nómina sí emitió se clasifica sin fricción."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    await _nomina(db, empresa_id, "88888888-8888-8888-8888-888888888881", "VENTAS")

    codigo = await _correr(
        db, "clasificar", "--empresa-id", str(empresa_id),
        "--concepto", "P/001/001", "NO_APLICA",
        "--concepto", "P/001/019", "VACACIONES",
        "--actor", ACTOR, "--si",
    )

    assert codigo == 0
    db.expire_all()
    categorias = await cfg.categorias_de_provision(db, empresa_id)
    assert categorias[("P", "001", "001")] is CategoriaProvision.NO_APLICA
    assert categorias[("P", "001", "019")] is CategoriaProvision.VACACIONES
    detalle = (await _bitacora(db, "guardar_mapeos_empresa"))[0].detalle
    assert detalle is not None and detalle["via"] == cli.VIA_LINEA_DE_COMANDOS
    assert detalle["anterior"]["conceptos_provision"] == []
    assert len(detalle["nuevo"]["conceptos_provision"]) == 2


async def test_clasificar_mezcla_con_lo_que_ya_habia(db: AsyncSession) -> None:
    """Por omisión no borra lo que no se menciona: `--concepto P/001/001 ...` tirando los
    otros veinte mapeos sería una pérdida que se nota tres meses después, cuando B-08 no
    cuadra."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    await _nomina(db, empresa_id, "88888888-8888-8888-8888-888888888881", "VENTAS")
    db.add(
        MapConceptoProvision(
            empresa_id=empresa_id, naturaleza="P", tipo="001", clave="019",
            categoria=CategoriaProvision.VACACIONES,
        )
    )
    db.add(MapDepartamento(empresa_id=empresa_id, departamento_texto="VENTAS", centro_costo="CC-01"))
    await db.commit()

    assert await _correr(
        db, "clasificar", "--empresa-id", str(empresa_id),
        "--concepto", "P/001/001", "NO_APLICA", "--actor", ACTOR, "--si",
    ) == 0

    db.expire_all()
    categorias = await cfg.categorias_de_provision(db, empresa_id)
    assert set(categorias) == {("P", "001", "001"), ("P", "001", "019")}
    assert await cfg.centro_de_costo(db, empresa_id) == {"VENTAS": "CC-01"}


async def test_reemplazar_si_borra_lo_que_no_venga(db: AsyncSession) -> None:
    """La gemela: la semántica del `PUT` de la pantalla sigue siendo expresable, con bandera."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    await _nomina(db, empresa_id, "88888888-8888-8888-8888-888888888881", "VENTAS")
    db.add(
        MapConceptoProvision(
            empresa_id=empresa_id, naturaleza="P", tipo="001", clave="019",
            categoria=CategoriaProvision.VACACIONES,
        )
    )
    await db.commit()

    assert await _correr(
        db, "clasificar", "--empresa-id", str(empresa_id), "--reemplazar",
        "--concepto", "P/001/001", "NO_APLICA", "--actor", ACTOR, "--si",
    ) == 0

    db.expire_all()
    assert set(await cfg.categorias_de_provision(db, empresa_id)) == {("P", "001", "001")}


async def test_la_clasificacion_completa_solo_cuenta_percepciones(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """Lo que B-08 concilia es cuánto **se pagó ya** de aguinaldo, vacaciones y prima
    vacacional, y eso son percepciones: una deducción no puede ser aguinaldo — el aguinaldo no
    se le descuenta a nadie. Contar las deducciones dejaría el marcador clavado en un número
    que nadie puede bajar a cero y B-08 nunca se generaría, por una razón sin sentido.

    La nómina de esta empresa trae **una deducción sin clasificar** (`D/001/IMSS`) y dos
    departamentos sin centro de costo, y aun así, con las dos percepciones clasificadas, la
    clasificación tiene que quedar COMPLETA.
    """
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    await _nomina(db, empresa_id, "88888888-8888-8888-8888-888888888881", "VENTAS")

    assert await _correr(
        db, "clasificar", "--empresa-id", str(empresa_id),
        "--concepto", "P/001/001", "NO_APLICA",
        "--concepto", "P/001/019", "VACACIONES",
        "--actor", ACTOR, "--si",
    ) == 0

    salida = capsys.readouterr().out
    assert "COMPLETA" in salida, salida
    db.expire_all()
    # La deducción sigue sin clasificar, y eso es correcto: no participa.
    assert ("D", "001", "IMSS") not in await cfg.categorias_de_provision(db, empresa_id)


async def test_una_percepcion_sin_clasificar_si_deja_la_clasificacion_incompleta(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """La gemela: sin ella, un contador que dijera "COMPLETA" siempre pasaría igual de verde."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    await _nomina(db, empresa_id, "88888888-8888-8888-8888-888888888881", "VENTAS")

    assert await _correr(
        db, "clasificar", "--empresa-id", str(empresa_id),
        "--concepto", "P/001/001", "NO_APLICA", "--actor", ACTOR, "--si",
    ) == 0

    salida = capsys.readouterr().out
    assert "COMPLETA" not in salida
    assert "faltan 1 percepción(es)" in salida
    assert "P/001/019" in salida, "tiene que decir cuál falta, no solo cuántas"


async def test_observados_enumera_lo_que_la_nomina_emitio(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """La lista de la que se eligen las categorías, para no tener que teclear una clave que
    nadie conoce de memoria."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    await _nomina(db, empresa_id, "88888888-8888-8888-8888-888888888881", "VENTAS")

    assert await _correr(db, "observados", "--empresa-id", str(empresa_id)) == 0

    salida = capsys.readouterr().out
    assert "P/001/019" in salida
    assert "VACACIONES A TIEMPO" in salida, "el texto del patrón es lo que la persona reconoce"
    assert "SIN CLASIFICAR" in salida
    assert "VENTAS" in salida and "SIN MAPEAR" in salida


# --------------------------------------------------------------------------------------
# 9. El generador de comandos, y la garantía de la huella en una terminal
# --------------------------------------------------------------------------------------

_DUDA = "Verificar contra el art. 93 fracción XIV: la exención podría estar topada."


async def test_los_comandos_generados_llevan_la_duda_encima(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """Teclear 64 caracteres por marca no lo hace nadie, pero el punto de la huella es que
    quien confirma **haya visto la duda**. La duda va impresa encima de su comando: no hay
    forma de llegar a la línea que se copia sin pasar por la advertencia."""
    await _admin(db)
    db.add(_marca("010", nota=_DUDA))
    await db.commit()

    assert await _correr(db, "estado", "--percepciones", "--como-comandos", "--actor", ACTOR) == 0

    salida = capsys.readouterr().out
    assert f"# DUDA: {_DUDA}" in salida
    huella = str(cfg.huella_de_nota(_DUDA))
    assert f"--huella {huella}" in salida
    # La duda va **antes** que el comando que se copia, no después.
    assert salida.index("# DUDA:") < salida.index("confirmar-marca 010")
    assert f"--actor {ACTOR}" in salida


async def test_una_marca_ya_confirmada_no_sale_en_los_comandos(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """La gemela del generador: solo se listan las pendientes. Si listara todas, la lista
    nunca bajaría y nadie sabría qué le falta."""
    await _admin(db)
    fila = _marca("010", nota=None)
    fila.confirmado_por = ACTOR
    fila.confirmado_en = datetime(2026, 8, 1, 9, 0, 0)
    db.add(fila)
    await db.commit()

    assert await _correr(db, "estado", "--percepciones", "--como-comandos", "--actor", ACTOR) == 0

    salida = capsys.readouterr().out
    assert "confirmar-marca 010" not in salida
    assert "0 MARCA(S) PENDIENTE(S)" in salida


async def test_el_generador_no_finge_una_garantia_que_no_tiene(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """Una versión anterior escondía la huella cuando `sys.stdout.isatty()` era falso y decía
    que así "una tubería no puede confirmar una marca con una duda". Era falso —`estado
    --percepciones` las entrega sin comprobar nada, la huella es `sha256` de la duda que la
    propia salida imprime, y `script -qc` fabrica un pty— y además **estorbaba a quien sí
    lee**: `| less`, que es como se leen 39 marcas que no caben en pantalla, deja `isatty()` en
    falso y borraba las huellas.

    Se retiró. Esta prueba fija que **no vuelva**: la salida es la misma vaya a donde vaya (bajo
    pytest está capturada, o sea que no es una terminal), y el texto no promete lo que no puede
    cumplir.
    """
    await _admin(db)
    db.add(_marca("010", nota=_DUDA))
    await db.commit()

    assert await _correr(db, "estado", "--percepciones", "--como-comandos", "--actor", ACTOR) == 0

    salida = capsys.readouterr().out
    assert str(cfg.huella_de_nota(_DUDA)) in salida, (
        "la salida capturada no es una terminal, y aun así entrega la huella: sin esto volvería "
        "la regla que castigaba a quien pagina la lista para leerla"
    )
    assert "no puede" not in salida.lower().split("# ---")[0].replace("no puede comprobarlo", ""), (
        "la cabecera no puede afirmar que algo es imposible"
    )
    assert "no finge" in salida


async def test_como_comandos_exige_percepciones(db: AsyncSession) -> None:
    await _admin(db)
    assert await _correr(db, "estado", "--como-comandos") == 1


# --------------------------------------------------------------------------------------
# 10. Conversión de la línea de comandos
# --------------------------------------------------------------------------------------


def test_las_claves_de_catalogo_se_conservan_como_texto() -> None:
    """`'001'` nunca `1`: los ceros a la izquierda cuentan, y `'015'` no es `'150'`."""
    assert cli.concepto_partido("P/001/019") == ("P", "001", "019")
    # La clave del patrón puede traer barras: se parte por los dos primeros separadores.
    assert cli.concepto_partido("P/005/A/B") == ("P", "005", "A/B")


@pytest.mark.parametrize("texto", ["P/1/019", "X/001/019", "P/001/", "P001019"])
def test_una_terna_mal_formada_se_rechaza(texto: str) -> None:
    """La gemela: sin esto, `P/1/019` se guardaría con un tipo de una posición que no casa con
    ningún concepto del SAT."""
    with pytest.raises(cli.ErrorDeUso):
        cli.concepto_partido(texto)


def test_un_importe_que_no_es_numero_se_rechaza() -> None:
    with pytest.raises(cli.ErrorDeUso):
        cli.importe("117,31", "el importe")
    assert cli.importe(" 117.31 ", "el importe") == Decimal("117.31")


# --------------------------------------------------------------------------------------
# 11. La guarda de las seis marcas, y las carreras que abre la propia pregunta
# --------------------------------------------------------------------------------------


async def test_con_si_hay_que_mandar_las_marcas_que_se_confirman(db: AsyncSession) -> None:
    """El agujero que quedaba: el comando **se mandaba a sí mismo** las marcas, así que con
    `--si` nadie comprobaba las seis. Escenario real: el lunes obtienes la huella de la duda de
    `010`; el miércoles alguien pone `sujeto_a_tope_conjunto=True` por el `PUT` sin tocar la
    nota, así que la huella sigue valiendo; el jueves confirmas y activas una bandera que nunca
    viste. Por la pantalla eso es un `409 MARCAS_CAMBIARON`."""
    await _admin(db)
    db.add(_marca("010", nota=None))
    await db.commit()

    codigo = await _correr(db, "confirmar-marca", "010", "--sin-duda", "--actor", ACTOR, "--si")

    assert codigo == 1
    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}


async def test_sin_si_las_marcas_salen_en_el_plan_y_las_compara_la_persona(
    db: AsyncSession, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """La gemela: sin `--si` la huella de las marcas es opcional porque el plan las imprime en
    claro y hay que teclear "s" — ahí quien compara es la persona, igual que en la pantalla.
    Exigirla también ahí sería fricción sin garantía nueva."""
    await _admin(db)
    db.add(_marca("010", nota=None, tope=True))
    await db.commit()

    async def _dice_que_si(*_a: Any, **_k: Any) -> bool:
        return True

    monkeypatch.setattr(cli, "pregunta", _dice_que_si)

    codigo = await _correr(db, "confirmar-marca", "010", "--sin-duda", "--actor", ACTOR)

    assert codigo == 0
    salida = capsys.readouterr().out
    assert "tope conjunto art. 93 (B-03)   sí" in salida, "las seis tienen que verse antes de decidir"
    assert "integra SBC" in salida and "provisionable" in salida
    db.expire_all()
    assert set(await cfg.marcas_de_percepcion(db)) == {"010"}


async def test_una_huella_de_marcas_vieja_no_confirma(db: AsyncSession) -> None:
    """El lunes/miércoles/jueves, ejercido: la huella de la duda sigue siendo válida (la nota no
    se tocó) y aun así hay que rechazarlo, porque el tope cambió."""
    await _admin(db)
    fila = _marca("010", nota=_DUDA)
    db.add(fila)
    await db.commit()
    huella_lunes = _huella_marcas(fila)

    fila.sujeto_a_tope_conjunto = True  # el miércoles, por el PUT, sin tocar la nota
    await db.commit()

    codigo = await _correr(
        db, "confirmar-marca", "010", "--huella", str(cfg.huella_de_nota(_DUDA)),
        "--marcas", huella_lunes, "--actor", ACTOR, "--si",
    )

    assert codigo == 1
    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}, "una bandera que nadie vio no puede quedar activa"


async def test_la_huella_de_marcas_de_hoy_si_confirma(db: AsyncSession) -> None:
    """La gemela de la anterior."""
    await _admin(db)
    fila = _marca("010", nota=None, tope=True)
    db.add(fila)
    await db.commit()

    codigo = await _correr(
        db, "confirmar-marca", "010", "--sin-duda", "--marcas", _huella_marcas(fila), "--actor", ACTOR, "--si"
    )

    assert codigo == 0
    db.expire_all()
    assert set(await cfg.marcas_de_percepcion(db)) == {"010"}


async def test_la_huella_de_marcas_no_incluye_la_nota(db: AsyncSession) -> None:
    """Si la nota entrara en la huella de las marcas, **resolver una duda invalidaría una
    revisión en vuelo** — lo contrario de la asimetría que `duda_no_vista` protege. Son dos
    huellas porque son dos cosas que se mueven por separado."""
    sin_nota = cfg.MarcasQueSeConfirman.de_fila(_marca("010", nota=None))
    con_nota = cfg.MarcasQueSeConfirman.de_fila(_marca("010", nota=_DUDA))
    assert cfg.huella_de_marcas(sin_nota) == cfg.huella_de_marcas(con_nota)
    # Y la gemela: una marca que sí cambia, cambia la huella.
    assert cfg.huella_de_marcas(sin_nota) != cfg.huella_de_marcas(
        cfg.MarcasQueSeConfirman.de_fila(_marca("010", tope=True))
    )


async def test_configurar_empresa_no_pisa_lo_que_cambio_mientras_respondias(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La pregunta convierte una ventana de milisegundos en una de minutos. Y el candado **no**
    se puede tomar antes de preguntar: una sesión abandonada en el `[s/N]:` bloquearía el `PUT`
    de esa empresa hasta el timeout de InnoDB. Así que se relee dentro de la transacción y se
    compara con el plan que se aprobó."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    db.add(ConfiguracionEmpresa(empresa_id=empresa_id, dias_aguinaldo=30))
    await db.commit()

    async def _mientras_responde(*_a: Any, **_k: Any) -> bool:
        config = await db.get(ConfiguracionEmpresa, empresa_id)
        assert config is not None
        config.dias_aguinaldo = 15  # otro administrador, mientras la persona lee el plan
        await db.commit()
        return True

    monkeypatch.setattr(cli, "pregunta", _mientras_responde)

    codigo = await _correr(
        db, "configurar-empresa", "--empresa-id", str(empresa_id), "--zona-salarial", "ZLFN", "--actor", ACTOR
    )

    assert codigo == 1
    db.expire_all()
    config = await db.get(ConfiguracionEmpresa, empresa_id)
    assert config is not None
    assert config.dias_aguinaldo == 15, "lo del otro se conserva"
    assert config.zona_salarial is None, "y lo nuestro no se aplica sobre un plan que ya no describe lo que hay"


async def test_configurar_empresa_si_nadie_toca_nada_guarda(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La gemela: sin ella, una comprobación que abortara siempre pasaría igual de verde."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    db.add(ConfiguracionEmpresa(empresa_id=empresa_id, dias_aguinaldo=30))
    await db.commit()

    async def _dice_que_si(*_a: Any, **_k: Any) -> bool:
        return True

    monkeypatch.setattr(cli, "pregunta", _dice_que_si)

    codigo = await _correr(
        db, "configurar-empresa", "--empresa-id", str(empresa_id), "--zona-salarial", "ZLFN", "--actor", ACTOR
    )

    assert codigo == 0
    db.expire_all()
    config = await db.get(ConfiguracionEmpresa, empresa_id)
    assert config is not None and config.zona_salarial is ZonaSalarial.ZLFN and config.dias_aguinaldo == 30


async def test_clasificar_no_borra_lo_que_otro_clasifico_mientras_respondias(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`clasificar` reemplaza todo lo de la empresa, así que aplicar un plan viejo **borra** lo
    que el otro acaba de guardar. El endpoint tiene la misma ventana y no la cierra; aquí sí,
    porque aquí la abre nuestra propia pregunta."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    await _nomina(db, empresa_id, "88888888-8888-8888-8888-888888888881", "VENTAS")

    async def _mientras_responde(*_a: Any, **_k: Any) -> bool:
        db.add(
            MapConceptoProvision(
                empresa_id=empresa_id, naturaleza="P", tipo="001", clave="019",
                categoria=CategoriaProvision.VACACIONES,
            )
        )
        await db.commit()
        return True

    monkeypatch.setattr(cli, "pregunta", _mientras_responde)

    codigo = await _correr(
        db, "clasificar", "--empresa-id", str(empresa_id), "--concepto", "P/001/001", "NO_APLICA", "--actor", ACTOR
    )

    assert codigo == 1
    db.expire_all()
    categorias = await cfg.categorias_de_provision(db, empresa_id)
    assert categorias == {("P", "001", "019"): CategoriaProvision.VACACIONES}, "lo del otro sigue ahí"


# --------------------------------------------------------------------------------------
# 12. Que la herramienta arranque de verdad: `main()`, `SessionLocal` y el motor real
# --------------------------------------------------------------------------------------


async def test_la_herramienta_arranca_de_verdad_contra_mysql(db: AsyncSession, mysql_url: str) -> None:
    """Todas las demás pruebas entran por `ejecutar(db, ...)` con la sesión ya hecha, así que
    `main()`, `asyncio.run` y `SessionLocal` —el motor de verdad, contra MySQL— no los ejercita
    ninguna. Lo primero que descubriría la corrida real sería que el proceso ni arranca.

    Se corre en un **subproceso**, que es la única forma de ejercitar `asyncio.run` desde una
    prueba que ya vive en un bucle, y con un comando de **solo lectura**.
    """
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    proc = subprocess.run(
        [sys.executable, "-m", "app.scripts.administrar_configuracion", "estado"],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": mysql_url},
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "UMA_DIARIA" in proc.stdout
    assert "117.310000" in proc.stdout
    assert "sin confirmar no calcula" in proc.stdout


async def test_el_proceso_real_sale_con_error_cuando_el_comando_esta_mal(
    db: AsyncSession, mysql_url: str
) -> None:
    """La gemela: el código de salida distinto de cero tiene que llegar hasta el shell. Un
    `main()` que devolviera 0 pasara lo que pasara haría verde la prueba de arriba igual."""
    await _admin(db)

    proc = subprocess.run(
        [sys.executable, "-m", "app.scripts.administrar_configuracion", "confirmar-valor",
         "--actor", ACTOR, "--valor", "UMA_INVENTADA", "1.00", "2026-02-01", "--si"],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": mysql_url},
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert proc.returncode != 0
    assert "no es una clave conocida" in proc.stderr


# --------------------------------------------------------------------------------------
# 13. Las dos marcas que hoy no lee ningún informe
# --------------------------------------------------------------------------------------


async def test_una_marca_que_no_lee_ningun_informe_igual_invalida_la_confirmacion(
    db: AsyncSession,
) -> None:
    """`integra_sbc` y `es_provisionable` no las lee ningún informe **todavía**, y aun así
    entran en la comparación que rechaza el confirmar.

    Es el mismo argumento que este módulo ya aceptó para `sujeto_a_tope_conjunto`: lo que la
    confirmación protege no es "lo que calcula hoy" sino **lo que la fila afirma**, y
    `marcas_de_percepcion` devuelve la fila entera. El día que un informe lea `integra_sbc` —es
    la base de cotización del IMSS, lo va a leer— leería un valor que nadie revisó. Sacarlas de
    la comparación cambiaría una fricción visible hoy por un hueco silencioso mañana.
    """
    await _admin(db)
    fila = _marca("010", nota=None)
    db.add(fila)
    await db.commit()
    huella_de_antes = _huella_marcas(fila)

    fila.integra_sbc = True  # cambia una marca que hoy no calcula nada
    await db.commit()

    codigo = await _correr(
        db, "confirmar-marca", "010", "--sin-duda", "--marcas", huella_de_antes, "--actor", ACTOR, "--si"
    )

    assert codigo == 1, "confirmar contra una fila que ya dice otra cosa se rechaza, calcule o no"
    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}


@pytest.mark.parametrize("campo", ["integra_sbc", "es_provisionable"])
async def test_la_puerta_del_servicio_rechaza_aunque_la_marca_no_calcule_nada(
    db: AsyncSession, campo: str
) -> None:
    """La misma afirmación, pero **contra la puerta del servicio**, que es la que comparten la
    pantalla y la terminal.

    La prueba de arriba no sirve para esto y la evidencia por mutación lo demostró: quitar
    `integra_sbc` de `marcas_difieren` la dejaba pasar, porque el comando compara la huella
    *antes* de llegar a la puerta y ese vistazo la tapaba. Es la tercera vez en esta fase que una
    comprobación externa esconde la guarda interna. Aquí se llama a `confirmar_marca_percepcion`
    directamente con unas marcas que difieren solo en el campo huérfano, que es lo que hace la
    pantalla cuando el cuerpo del `POST` trae un valor viejo.
    """
    await _admin(db)
    fila = _marca("010", nota=None)
    db.add(fila)
    await db.commit()

    revisadas = replace(cfg.MarcasQueSeConfirman.de_fila(fila), **{campo: not getattr(fila, campo)})

    with pytest.raises(cfg.MarcasCambiaron):
        await cfg.confirmar_marca_percepcion(
            db, tipo="010", marcas=revisadas, nota_revision_hash=None, actor=ACTOR
        )

    await db.rollback()
    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}, (
        f"`{campo}` no lo lee ningún informe todavía, pero confirmar una fila que dice otra cosa "
        "sigue siendo confirmar sin haber mirado: el día que un informe lo lea, leería un valor "
        "que nadie revisó"
    )


@pytest.mark.parametrize("campo", ["integra_sbc", "es_provisionable"])
async def test_la_puerta_del_servicio_si_confirma_lo_que_coincide(db: AsyncSession, campo: str) -> None:
    """La gemela de la anterior, y la que impide que `marcas_difieren` se vuelva "rechaza
    siempre": con las seis iguales, confirma."""
    await _admin(db)
    fila = _marca("010", nota=None)
    setattr(fila, campo, True)
    db.add(fila)
    await db.commit()

    _, cambio = await cfg.confirmar_marca_percepcion(
        db,
        tipo="010",
        marcas=cfg.MarcasQueSeConfirman.de_fila(fila),
        nota_revision_hash=None,
        actor=ACTOR,
    )
    await db.commit()

    assert cambio is True
    db.expire_all()
    assert set(await cfg.marcas_de_percepcion(db)) == {"010"}


async def test_las_seis_entran_en_la_huella_incluidas_las_dos_huerfanas(db: AsyncSession) -> None:
    """La gemela, al nivel de la huella: si `huella_de_marcas` ignorara las dos huérfanas, la
    prueba de arriba pasaría igual y el hueco quedaría abierto."""
    base = cfg.MarcasQueSeConfirman.de_fila(_marca("010"))
    for campo in (
        "es_ingreso_ordinario",
        "integra_sbc",
        "es_provisionable",
        "sujeto_a_tope_conjunto",
        # La séptima (tarea 7b), y es el caso fácil de la regla: esta **sí** calcula.
        "multiplicador_no_derivable",
    ):
        distinta = replace(base, **{campo: not getattr(base, campo)})
        assert cfg.huella_de_marcas(base) != cfg.huella_de_marcas(distinta), (
            f"`{campo}` tiene que mover la huella: si no, se puede cambiar bajo una confirmación"
        )


async def test_el_estado_dice_que_dos_marcas_no_las_lee_nadie(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """El coste real de las dos huérfanas no es la guarda, es el trabajo inútil: quien revisa
    las 44 puede "corregir" `es_provisionable` para arreglar la provisión de B-08 —que sale de
    `map_concepto_provision`, no de ahí—, no cambiar ningún resultado y perder la confirmación.
    Decirlo donde se revisa es lo que lo evita."""
    await _admin(db)
    db.add(_marca("010", nota=None))
    await db.commit()

    assert await _correr(db, "estado", "--percepciones") == 0

    salida = capsys.readouterr().out
    assert "Las que hoy calculan:" in salida
    assert "ingreso ordinario (B-05)" in salida
    assert "exención (B-03)" in salida
    assert "ningún informe las lee todavía" in salida
    assert "B-08 sale de la clasificación de conceptos" in salida.replace("\n", " ").replace("  ", " ") or (
        "B-08" in salida and "clasificar" in salida
    )
    assert "B-06" not in salida, "el pasivo laboral es B-08; B-06 es el de centros de costo"


# --------------------------------------------------------------------------------------
# 14. Recargar una semilla de empresa no puede borrar lo que no menciona
# --------------------------------------------------------------------------------------


async def test_recargar_una_semilla_no_borra_los_campos_que_no_menciona(
    db: AsyncSession, tmp_path: Path
) -> None:
    """El caso verificado: empresa con `ZLFN / 15 / 0.25`, se recarga un YAML que solo trae
    `zona_salarial`. Antes quedaba `ZLFN / None / None`, **sin bitácora** —el cargador no
    escribe ninguna a propósito—, y sin días de aguinaldo B-08 deja de generarse: un informe se
    apagaba y no había rastro de quién lo apagó.

    Es la misma decisión que `cmd_configurar_empresa` ya tomaba ("lo que no se menciona se
    conserva"), y el cargador es el camino **documentado** en `empresa.yaml.ejemplo`.
    """
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    db.add(
        ConfiguracionEmpresa(
            empresa_id=empresa_id,
            zona_salarial=ZonaSalarial.ZLFN,
            dias_aguinaldo=15,
            factor_prima_vacacional=Decimal("0.2500"),
        )
    )
    await db.commit()

    ruta = tmp_path / "empresa-solo-zona.yaml"
    ruta.write_text("configuracion_empresa:\n  - zona_salarial: ZLFN\n", encoding="utf-8")

    resultado = await cfg.cargar_desde_yaml_detallado(db, ruta, empresa_id=empresa_id)

    db.expire_all()
    config = await db.get(ConfiguracionEmpresa, empresa_id)
    assert config is not None
    assert config.zona_salarial is ZonaSalarial.ZLFN
    assert config.dias_aguinaldo == 15, "el archivo no los menciona: no se tocan"
    assert config.factor_prima_vacacional == Decimal("0.2500")
    # Y el resumen lo dice, para que no sea una conservación silenciosa tampoco.
    avisos = " ".join(resultado.conservados)
    assert "dias_aguinaldo" in avisos and "factor_prima_vacacional" in avisos
    assert "no los menciona" in avisos


async def test_un_null_explicito_si_borra(db: AsyncSession, tmp_path: Path) -> None:
    """La gemela, y es la que hace que la de arriba no sea "el cargador ya no escribe nada":
    ausente conserva, `null` **borra**. La diferencia es la intención declarada, y el rastro de
    ese borrado es el propio archivo en git — el único que tiene el cargador."""
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    db.add(ConfiguracionEmpresa(empresa_id=empresa_id, zona_salarial=ZonaSalarial.ZLFN, dias_aguinaldo=15))
    await db.commit()

    ruta = tmp_path / "empresa-borra.yaml"
    ruta.write_text("configuracion_empresa:\n  - zona_salarial: ZLFN\n    dias_aguinaldo: null\n", encoding="utf-8")

    resultado = await cfg.cargar_desde_yaml_detallado(db, ruta, empresa_id=empresa_id)

    db.expire_all()
    config = await db.get(ConfiguracionEmpresa, empresa_id)
    assert config is not None
    assert config.dias_aguinaldo is None, "un `null` explícito es una orden de borrar"
    assert any("se BORRÓ" in aviso for aviso in resultado.conservados), "y se dice en voz alta"


async def test_la_primera_carga_escribe_lo_que_el_archivo_trae(db: AsyncSession, tmp_path: Path) -> None:
    """Y la gemela de la gemela: sobre una empresa sin configuración, el cargador sigue creando
    la fila con lo que el archivo declara. Sin esto, "conservar lo que no se menciona" podría
    haberse implementado como "no escribir nunca"."""
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id

    ruta = tmp_path / "empresa-nueva.yaml"
    ruta.write_text(
        "configuracion_empresa:\n  - zona_salarial: ZLFN\n    dias_aguinaldo: 30\n"
        "    factor_prima_vacacional: '0.25'\n",
        encoding="utf-8",
    )

    await cfg.cargar_desde_yaml_detallado(db, ruta, empresa_id=empresa_id)

    db.expire_all()
    config = await db.get(ConfiguracionEmpresa, empresa_id)
    assert config is not None
    assert config.zona_salarial is ZonaSalarial.ZLFN
    assert config.dias_aguinaldo == 30
    assert config.factor_prima_vacacional == Decimal("0.2500")


# --------------------------------------------------------------------------------------
# 15. La cadena de la colación: variantes ortográficas de `departamento_texto`
# --------------------------------------------------------------------------------------
#
# Estas pruebas corren contra **MySQL de verdad** (el contenedor efímero del conftest) y no
# contra una simulación en Python, porque el defecto vive en cómo agrupa la base: una versión en
# memoria compararía con `==` de Python y no reproduciría ni el PAD SPACE ni la insensibilidad a
# mayúsculas de `utf8mb4_unicode_ci`, que es justo lo que se está probando.


async def _nomina_con_departamento(db: AsyncSession, empresa_id: int, uuid: str, departamento: str) -> None:
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa_id, uuid=uuid, rfc_emisor=RFC_EMPRESA, tipo_comprobante="N",
        estatus=EstatusCfdi.VIGENTE,
    )
    db.add(NominaReceptor(comprobante_id=comprobante.comprobante_id, departamento=departamento))
    await db.commit()


async def test_las_variantes_ortograficas_se_enumeran_una_por_una(db: AsyncSession) -> None:
    """La cadena que esto corta, eslabón por eslabón: el agrupamiento iba con la colación de la
    columna (`utf8mb4_unicode_ci`, **PAD SPACE** y sin distinguir mayúsculas), así que las tres
    variantes colapsaban en un renglón con `COUNT = 3`; la pantalla nunca las enumeraba;
    `sin_mapear` se calculaba sobre la lista colapsada y llegaba a cero; la pantalla escribía "ya
    están todos agrupados"; y B-06 emitía `DEPARTAMENTO_SIN_MAPEO` nombrando textos que la
    pantalla no había enseñado jamás. **Dos superficies contradiciéndose.**

    `utf8mb4_bin` no habría servido: distingue mayúsculas pero sigue siendo PAD SPACE, así que
    `'Edificios '` y `'Edificios'` seguirían colapsando (verificado contra
    `information_schema.COLLATIONS` en MySQL 8.4).
    """
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    for i, texto in enumerate(("EDIFICIOS", "Edificios", "Edificios ")):
        await _nomina_con_departamento(db, empresa_id, f"99999999-9999-9999-9999-99999999000{i}", texto)

    observados = await cfg.observados_de_empresa(db, empresa)

    textos = sorted(d.departamento_texto for d in observados.departamentos)
    assert textos == ["EDIFICIOS", "Edificios", "Edificios "], (
        "cada secuencia de bytes distinta es su propio renglón, incluido el espacio final"
    )
    assert all(d.comprobantes == 1 for d in observados.departamentos), "y cada una con SU cuenta, no la suma"


async def test_dos_departamentos_de_verdad_distintos_siguen_siendo_dos(db: AsyncSession) -> None:
    """La gemela: enumerar byte a byte no puede partir lo que no está partido. Sin ella, un
    agrupamiento roto de otra forma —por comprobante, digamos— pasaría igual de verde."""
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    await _nomina_con_departamento(db, empresa_id, "99999999-9999-9999-9999-999999990010", "EDIFICIOS")
    await _nomina_con_departamento(db, empresa_id, "99999999-9999-9999-9999-999999990011", "EDIFICIOS")
    await _nomina_con_departamento(db, empresa_id, "99999999-9999-9999-9999-999999990012", "SOCIAL")

    observados = await cfg.observados_de_empresa(db, empresa)

    por_texto = {d.departamento_texto: d for d in observados.departamentos}
    assert set(por_texto) == {"EDIFICIOS", "SOCIAL"}
    assert por_texto["EDIFICIOS"].comprobantes == 2, "el mismo texto exacto sí agrupa"
    assert por_texto["SOCIAL"].comprobantes == 1


async def test_la_clave_de_la_base_la_decide_mysql_y_delata_las_variantes(db: AsyncSession) -> None:
    """Enumerar sin más dejaría al operador intentando mapear la segunda variante para recibir un
    1062. `clave_en_la_base` es la clave que `map_departamento` usaría, calculada por **MySQL**
    con la colación real de esa tabla — no por una copia de la colación escrita en Python, que
    sería infiel (`utf8mb4_unicode_ci` también iguala acentos)."""
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    for i, texto in enumerate(("EDIFICIOS", "Edificios ", "SOCIAL")):
        await _nomina_con_departamento(db, empresa_id, f"99999999-9999-9999-9999-99999999002{i}", texto)

    observados = await cfg.observados_de_empresa(db, empresa)
    por_texto = {d.departamento_texto: d for d in observados.departamentos}

    # Las dos variantes comparten clave, y es la misma para las dos.
    assert por_texto["EDIFICIOS"].clave_en_la_base == por_texto["Edificios "].clave_en_la_base
    # Y un departamento sin variantes es su propia clave: así la pantalla sabe a quién avisar.
    assert por_texto["SOCIAL"].clave_en_la_base == "SOCIAL"
    con_aviso = [d.departamento_texto for d in observados.departamentos if d.clave_en_la_base != d.departamento_texto]
    assert con_aviso and "SOCIAL" not in con_aviso


async def test_mapear_las_dos_variantes_se_rechaza_explicando_por_que(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """El segundo eslabón, el que enumerar solo no cierra: la PK de `map_departamento` no puede
    guardar las dos, así que el `INSERT` da 1062. Sin traducirlo, el operador ve un
    `IntegrityError` crudo — y enumerar las variantes para luego reventar es peor que no
    enumerarlas.

    La colisión **no se detecta reimplementando la colación**: se intenta escribir y se traduce
    lo que MySQL contesta, citando su propio valor duplicado.
    """
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    for i, texto in enumerate(("EDIFICIOS", "Edificios ")):
        await _nomina_con_departamento(db, empresa_id, f"99999999-9999-9999-9999-99999999003{i}", texto)

    codigo = await _correr(
        db, "clasificar", "--empresa-id", str(empresa_id),
        "--departamento", "EDIFICIOS", "CC-01",
        "--departamento", "Edificios ", "CC-02",
        "--actor", ACTOR, "--si",
    )

    assert codigo == 1
    salida = capsys.readouterr()
    # **Esta aserción es la que hace honesta la prueba.** La primera versión pasaba por el motivo
    # equivocado: el comando recortaba el texto, `'Edificios '` se volvía `'Edificios'`, y lo que
    # rechazaba era la guarda de "no aparece en ningún CFDI" — la colisión no se llegaba a
    # intentar nunca. Lo destapó la mutación que quitaba la traducción del 1062 y no hacía fallar
    # nada. Sin comprobar **por qué** falla, esto era una de esas pruebas que no protegen nada.
    assert "misma clave para la base" in salida.err, salida.err
    assert "MySQL dijo" in salida.err, "el valor duplicado lo tiene que decir la base, no nosotros"
    db.expire_all()
    assert await _contar(db, MapDepartamento) == 0, "o entran las dos o no entra ninguna"


async def test_mapear_una_sola_variante_si_entra(db: AsyncSession) -> None:
    """La gemela: la limitación es "solo una", no "ninguna". Sin esto, un rechazo que abortara
    cualquier mapeo de departamentos pasaría igual de verde la prueba de arriba."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    for i, texto in enumerate(("EDIFICIOS", "Edificios ")):
        await _nomina_con_departamento(db, empresa_id, f"99999999-9999-9999-9999-99999999004{i}", texto)

    codigo = await _correr(
        db, "clasificar", "--empresa-id", str(empresa_id),
        "--departamento", "EDIFICIOS", "CC-01", "--actor", ACTOR, "--si",
    )

    assert codigo == 0
    # Sin `expire_all()`: las dos consultas de abajo son SELECT frescos, y expirar dejaría el
    # `empresa` cargado sin atributos y su recarga perezosa reventaría fuera del contexto async.
    assert await cfg.centro_de_costo(db, empresa_id) == {"EDIFICIOS": "CC-01"}
    # Y la otra variante sigue SIN mapeo, que es lo que B-06 va a reportar: las dos superficies
    # dicen lo mismo, que es el punto de todo esto.
    observados = await cfg.observados_de_empresa(db, empresa)
    sin_centro = [d.departamento_texto for d in observados.departamentos if d.centro_costo is None]
    assert sin_centro == ["Edificios "]


async def test_el_estado_avisa_de_las_variantes_que_comparten_clave(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """Y se dice donde se mira, no solo en el README: quien lee `observados` tiene que ver que
    solo una de las dos podrá llevar centro de costo, **antes** de gastar el intento."""
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc=RFC_EMPRESA)
    empresa_id = empresa.empresa_id
    for i, texto in enumerate(("EDIFICIOS", "Edificios ")):
        await _nomina_con_departamento(db, empresa_id, f"99999999-9999-9999-9999-99999999005{i}", texto)

    assert await _correr(db, "observados", "--empresa-id", str(empresa_id)) == 0

    salida = capsys.readouterr().out
    assert "[Edificios ]" in salida, "el corchete es lo único que hace visible el espacio final"
    assert "comparte clave" in salida
    assert "Solo UNA puede llevar centro de costo" in salida
    assert "README" in salida, "el arreglo de fondo tiene que ser localizable desde aquí"


async def test_la_colacion_de_las_dos_columnas_es_la_que_esta_asumida(db: AsyncSession) -> None:
    """Todo lo de arriba depende de una propiedad del **esquema**, no del código: que las dos
    columnas vivan en `utf8mb4_unicode_ci` (PAD SPACE, insensible a mayúsculas). Si alguien la
    cambia —o si un servidor con otro default se cuela porque los modelos dejaran de declararla—
    las variantes dejarían de colisionar y la mitad de estas pruebas pasaría sin probar nada.

    Se comprueba contra `information_schema` de la base de pruebas, que es la única forma de
    saber que el entorno de pruebas y el de producción coinciden en esto.
    """
    filas = (
        await db.execute(
            text(
                "SELECT TABLE_NAME, COLLATION_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME IN ('departamento_texto', 'departamento')"
            )
        )
    ).all()

    por_tabla = {tabla: colacion for tabla, colacion in filas}
    assert por_tabla["map_departamento"] == "utf8mb4_unicode_ci"
    assert por_tabla["nomina_receptor"] == "utf8mb4_unicode_ci"

    pad = (
        await db.execute(
            text(
                "SELECT PAD_ATTRIBUTE FROM information_schema.COLLATIONS "
                "WHERE COLLATION_NAME = 'utf8mb4_unicode_ci'"
            )
        )
    ).scalar_one()
    assert pad == "PAD SPACE", "si dejara de ser PAD SPACE, el espacio final ya no colisionaría"

# --------------------------------------------------------------------------------------
# 16. `multiplicador_no_derivable` (tarea 7b)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("campo", ["multiplicador_no_derivable"])
async def test_la_puerta_del_servicio_rechaza_si_cambio_el_multiplicador(
    db: AsyncSession, campo: str
) -> None:
    """**Llamando a la puerta directamente**, no por el camino del comando, que es la lección de
    la ronda anterior: la comparación de `--marcas` taparía `marcas_difieren` y la mutación que
    la borra sobreviviría.

    Este campo es el caso fácil de la regla de la ronda 3 —*entra en la comparación porque **sí**
    calcula*—: apagarlo en uno de los nueve tipos hace que B-03 publique un tope calculado
    suponiendo un multiplicador de 1, que es un exceso del patrón inventado.
    """
    await _admin(db)
    fila = _marca("010", nota=None, sin_multiplicador=True)
    db.add(fila)
    await db.commit()

    revisadas = replace(cfg.MarcasQueSeConfirman.de_fila(fila), **{campo: False})

    with pytest.raises(cfg.MarcasCambiaron):
        await cfg.confirmar_marca_percepcion(
            db, tipo="010", marcas=revisadas, nota_revision_hash=None, actor=ACTOR
        )

    await db.rollback()
    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}


async def test_el_estado_muestra_el_multiplicador_entre_las_que_calculan(
    db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """Va en el grupo de "las que hoy calculan", no en las informativas: B-03 la lee. Y cuando
    está puesta se explica, porque si no parece un campo más que se puede desmarcar."""
    await _admin(db)
    db.add(_marca("010", nota=None, sin_multiplicador=True))
    await db.commit()

    assert await _correr(db, "estado", "--percepciones") == 0

    salida = capsys.readouterr().out
    calculan, informativas = salida.split("Informativas", 1)
    assert "multiplicador no derivable     sí" in calculan, (
        "esta marca SÍ calcula: ponerla entre las informativas invitaría a cambiarla sin coste"
    )
    assert "multiplicador" not in informativas, (
        "y no puede aparecer también en el bloque informativo: diría dos cosas contrarias"
    )
    assert "deja el tope vacío en vez de suponer que el multiplicador es 1" in salida


async def test_la_semilla_carga_la_bandera_y_rechaza_lo_incoherente(db: AsyncSession, tmp_path: Path) -> None:
    """El cargador la lee, y **la rechaza con `base_exencion: NINGUNA`**: lo que la bandera dice
    es que al factor le falta un multiplicador, y sin exención no hay factor. Misma regla que
    `sujeto_a_tope_conjunto` y por el mismo motivo — una bandera que no puede ser cierta es un
    error de captura, no una opción."""
    bueno = tmp_path / "bueno.yaml"
    bueno.write_text(
        "catalogo_percepcion_marca:\n"
        "  - tipo_percepcion: '022'\n"
        "    es_ingreso_ordinario: false\n"
        "    base_exencion: UMA_DIAS\n"
        "    factor_exencion: '90'\n"
        "    integra_sbc: false\n"
        "    es_provisionable: false\n"
        "    multiplicador_no_derivable: true\n",
        encoding="utf-8",
    )
    await cfg.cargar_desde_yaml(db, bueno)
    db.expire_all()
    fila = await db.get(CatalogoPercepcionMarca, "022")
    assert fila is not None and fila.multiplicador_no_derivable is True

    malo = tmp_path / "malo.yaml"
    malo.write_text(
        "catalogo_percepcion_marca:\n"
        "  - tipo_percepcion: '001'\n"
        "    es_ingreso_ordinario: true\n"
        "    base_exencion: NINGUNA\n"
        "    integra_sbc: true\n"
        "    es_provisionable: false\n"
        "    multiplicador_no_derivable: true\n",
        encoding="utf-8",
    )
    with pytest.raises(cfg.ErrorDeConfiguracion, match="multiplicador_no_derivable"):
        await cfg.cargar_desde_yaml(db, malo)


async def test_recargar_la_semilla_con_la_bandera_distinta_limpia_la_confirmacion(
    db: AsyncSession, tmp_path: Path
) -> None:
    """La gemela del cargador: si al recargar cambia, la marca vuelve a la cola de revisión.
    Sin esto, corregir la bandera de uno de los nueve la activaría sin que nadie la mirara — y es
    justo el campo que decide si se publica un tope inventado."""
    fila = _marca("022", nota=None, sin_multiplicador=False)
    fila.base_exencion = BaseExencion.UMA_DIAS
    fila.factor_exencion = Decimal("90.0000")
    fila.confirmado_por = ACTOR
    fila.confirmado_en = datetime(2026, 8, 1, 9, 0, 0)
    db.add(fila)
    await db.commit()

    ruta = tmp_path / "recarga.yaml"
    ruta.write_text(
        "catalogo_percepcion_marca:\n"
        "  - tipo_percepcion: '022'\n"
        "    es_ingreso_ordinario: false\n"
        "    base_exencion: UMA_DIAS\n"
        "    factor_exencion: '90'\n"
        "    integra_sbc: false\n"
        "    es_provisionable: false\n"
        "    multiplicador_no_derivable: true\n",
        encoding="utf-8",
    )
    await cfg.cargar_desde_yaml(db, ruta)

    db.expire_all()
    recargada = await db.get(CatalogoPercepcionMarca, "022")
    assert recargada is not None
    assert recargada.multiplicador_no_derivable is True
    assert recargada.confirmado_en is None, "cambió el campo que decide el cálculo: vuelve a revisión"
