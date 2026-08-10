"""Verificación en vivo de la carga de la tarifa del ISR (Task 12, doc de diseño §7-§8).

Comprueba, contra la base de datos real y los archivos reales del proyecto —nunca contra
dobles—, las 11 afirmaciones del brief de esta tarea: que el Anexo 8 oficial se importa
completo, que la tarifa de 15 días queda estructuralmente correcta, que nada quedó en escala
de porcentaje, que corregir a mano limpia la confirmación y protege contra una reimportación
que la pisaría, que confirmar activa de verdad el cálculo, que la comprobación contra un
recibo real es de pesos y no de órdenes de magnitud, que la alarma de vigencia se enciende y
se apaga, y que la hoja de revisión en PDF se genera.

Por qué llama a las funciones del endpoint directamente, y no por HTTP
------------------------------------------------------------------------
Los cinco endpoints de `app.api.v1.configuracion` exigen `require_admin`, que verifica un ID
token real de Firebase contra el proyecto de producción (`cfdi-app`). Este script no tiene ni
debe fabricar un token así: hacerlo implicaría autenticarse de verdad contra un servicio
externo solo para correr una verificación local, un efecto colateral que no le corresponde a
este script. La alternativa —construir el token igual que lo haría el navegador— no prueba
nada que valga la pena: el contrato ya lo fija `app.api.deps.require_admin`, que ninguna tarea
de este plan tocó.

Lo que sí se ejerce, real y sin doblar: la función del endpoint completa (validación,
traducción de excepciones a los códigos HTTP que promete el diseño, escritura de bitácora),
el repositorio, las reglas puras, el extractor del PDF y **la misma base MySQL** que usan
`api`/`worker`/`beat`. Se le pasa un `admin` fabricado en memoria (nunca escrito en `usuarios`)
con el único atributo que esas funciones leen (`.correo`), y un `UploadFile` construido sobre
los bytes reales de `tests/fixtures/anexo8-2026.pdf`. Es el mismo compromiso que ya acepta
`scripts/verificar_informes.py` en su docstring: nunca se llama dos veces al SAT ni a Firebase
solo para verificar, pero tampoco se sustituye la base de datos real por un doble.

Punto de control no negociable: la base tiene que quedar exactamente como se encontró
----------------------------------------------------------------------------------------
Esta base tiene datos fiscales reales de la empresa 11 (`CHL960913IX9`): 8 CFDI de nómina
quincenales, 5 valores de `param_fiscal` confirmados y 6 tramos más (UMA 2025 y subsidio al
empleo, sembrados por la Task 7) sin confirmar, además de las 44 marcas de
`catalogo_percepcion_marca`, ninguna confirmada. Este script **crea tarifas de prueba y las
confirma** para poder ejercer el camino completo — y al terminar las descarta y lo dice en su
salida (paso 11). Antes de empezar comprueba que `tarifa_isr` esté vacía (así estaba antes de
esta tarea) y se **niega a correr** si no lo está, porque solo puede prometer dejar la tabla
como la encontró si sabe con certeza qué había antes. Lo que este script NUNCA toca, ni para
leer con intención de modificar: ni `param_fiscal` ni `catalogo_percepcion_marca` — se toma una
fotografía de sus conteos al empezar y se compara al final.

La bitácora que las cuatro escrituras (importar/corregir/confirmar/borrar) dejan **no se
borra**: es append-only por diseño (regla 8 de `CLAUDE.md`) y limpiarla violaría esa regla
para "dejar la base como estaba" en una tabla que, por definición, nunca vuelve atrás. Queda
marcada con `actor="verificacion@script"`, distinguible de cualquier acción real de un
administrador, y el paso 11 imprime cuántas filas nuevas dejó.

Uso: `.venv/bin/python scripts/verificar_tarifa_isr.py` (host, con `DATABASE_URL` apuntando al
MySQL real de `docker compose`) o `docker compose exec api python scripts/verificar_tarifa_isr.py`.
Sale con código 1 si alguna comprobación falla o si la base no estaba vacía al empezar.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import configuracion
from app.api.v1.schemas import (
    ImportacionTarifasOut,
    TarifaIsrConfirmarIn,
    TarifaIsrCorregirIn,
    TarifaIsrRenglonIn,
)
from app.db.session import SessionLocal
from app.models.bitacora import Bitacora
from app.models.configuracion_fiscal import CatalogoPercepcionMarca, ParamFiscal, TarifaIsr, TarifaIsrRenglon
from app.models.enums import OrigenTarifa, PeriodicidadTarifa
from app.repositories import tarifa_isr as repo
from app.services import sincronizacion_fiscal as sincronizacion
from app.services import tarifa_isr as reglas

ANEXO_2026 = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "anexo8-2026.pdf"

EJERCICIO = 2026
PERIODICIDAD_QUE_APLICA = PeriodicidadTarifa.DIAS_15
"""La nómina real de la empresa 11 es quincenal (8 CFDI de junio-julio de 2026): es la única
periodicidad observada, así que es la única tarifa que necesita quedar confirmada para que la
alarma de vigencia se apague y la única con recibos reales para comprobarse."""

# Objeto en memoria, nunca escrito en `usuarios`: las funciones de endpoint que se llaman aquí
# directamente (ver el docstring del módulo) solo leen `.correo` de su parámetro `admin`, para
# el actor de la bitácora y el texto de `fuente`. Marcado como script, no como David, para que
# la bitácora distinga sus filas de una acción real de un administrador.
ADMIN = SimpleNamespace(correo="verificacion@script")

# Las 7 tarifas que el Anexo 8 de 2026 trae de verdad (§C.I): las 5 periodicidades del
# ejercicio en curso, más la anual del propio 2026 y la anual del ejercicio **2025** (el
# cálculo anual que se presenta durante 2026 es el del año que acaba de cerrar). Fijado aquí
# con nombre, y no solo `len(...) == 7`, porque `test_anexo8.py` ya probó que un extractor con
# el ancla equivocada puede devolver 7 tarifas con el ejercicio de la anual mal puesto.
TARIFAS_ESPERADAS: frozenset[tuple[int, PeriodicidadTarifa]] = frozenset(
    {
        (2026, PeriodicidadTarifa.DIARIA),
        (2026, PeriodicidadTarifa.DIAS_7),
        (2026, PeriodicidadTarifa.DIAS_10),
        (2026, PeriodicidadTarifa.DIAS_15),
        (2026, PeriodicidadTarifa.MENSUAL),
        (2026, PeriodicidadTarifa.EJERCICIO),
        (2025, PeriodicidadTarifa.EJERCICIO),
    }
)


def _tarifa_de_prueba_valida() -> list[reglas.Renglon]:
    """Una tarifa de 15 días válida (pasa las seis pruebas del Anexo I.1 en `tarifa_isr.validar`)
    y a propósito **distinta** de la que trae el PDF real de 2026 (esa tiene 11 renglones): así
    la corrección manual del paso 4 nunca coincide con el documento por accidente, que es justo
    lo que necesita ejercer la protección contra reimportar del paso 5. Mismos números que
    `tests/test_api_tarifa_isr.py::_quincenal`, con el mismo propósito."""
    return [
        reglas.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
        reglas.Renglon(2, Decimal("416.71"), Decimal("3537.15"), Decimal("7.95"), Decimal("0.0640")),
        reglas.Renglon(3, Decimal("3537.16"), Decimal("6216.15"), Decimal("207.75"), Decimal("0.1088")),
        reglas.Renglon(4, Decimal("6216.16"), Decimal("7225.95"), Decimal("499.20"), Decimal("0.1600")),
        reglas.Renglon(5, Decimal("7225.96"), None, Decimal("660.75"), Decimal("0.3500")),
    ]


def _cuerpo_correccion(renglones: list[reglas.Renglon]) -> TarifaIsrCorregirIn:
    return TarifaIsrCorregirIn(
        renglones=[
            TarifaIsrRenglonIn(
                renglon=r.renglon,
                limite_inferior=r.limite_inferior,
                limite_superior=r.limite_superior,
                cuota_fija=r.cuota_fija,
                tasa_excedente=r.tasa_excedente,
            )
            for r in renglones
        ]
    )


def _archivo_anexo() -> UploadFile:
    return UploadFile(BytesIO(ANEXO_2026.read_bytes()), filename="anexo8-2026.pdf")


def _codigo_de(exc: HTTPException) -> str | None:
    return exc.detail.get("codigo") if isinstance(exc.detail, dict) else None


# --------------------------------------------------------------------------------------
# 1-3: importar el Anexo 8 real y comprobar su forma
# --------------------------------------------------------------------------------------


async def _paso_1_importar(db: AsyncSession) -> tuple[ImportacionTarifasOut, list[str]]:
    print("\n--- 1. Importar tests/fixtures/anexo8-2026.pdf por el endpoint ---")
    fallas: list[str] = []
    resultado = await configuracion.importar_tarifa_isr(archivo=_archivo_anexo(), admin=ADMIN, db=db)
    obtenidas = {(t.ejercicio, t.periodicidad) for t in resultado.tarifas}
    print(f"Tarifas importadas: {len(resultado.tarifas)} -> {sorted((e, p.value) for e, p in obtenidas)}")

    if len(resultado.tarifas) != 7:
        fallas.append(f"Se importaron {len(resultado.tarifas)} tarifas del Anexo 8 y se esperaban 7")
    if obtenidas != TARIFAS_ESPERADAS:
        fallas.append(
            "Las (ejercicio, periodicidad) importadas no son las 7 esperadas (incluida la anual 2025 del "
            f"rubro C.I): faltan {sorted(TARIFAS_ESPERADAS - obtenidas)}, sobran {sorted(obtenidas - TARIFAS_ESPERADAS)}"
        )
    no_propuestas = [t for t in resultado.tarifas if t.confirmada or t.origen is not OrigenTarifa.IMPORTADA]
    if no_propuestas:
        fallas.append(
            f"{len(no_propuestas)} tarifa(s) no quedaron como propuesta IMPORTADA sin confirmar tras importar"
        )
    return resultado, fallas


def _paso_2_estructura_quincenal(resultado: ImportacionTarifasOut) -> list[str]:
    print("\n--- 2. Estructura de la tarifa de 15 días de 2026 ---")
    fallas: list[str] = []
    quincenal = next(
        (t for t in resultado.tarifas if t.ejercicio == EJERCICIO and t.periodicidad is PeriodicidadTarifa.DIAS_15),
        None,
    )
    if quincenal is None:
        fallas.append("No se encontró la tarifa DIAS_15 de 2026 entre las importadas")
        return fallas

    print(f"Renglones: {len(quincenal.renglones)}")
    if len(quincenal.renglones) != 11:
        fallas.append(f"La tarifa de 15 días de 2026 tiene {len(quincenal.renglones)} renglones, se esperaban 11")
        return fallas

    primero, ultimo = quincenal.renglones[0], quincenal.renglones[-1]
    print(f"  renglón 1: limite_inferior={primero.limite_inferior}")
    print(f"  renglón {ultimo.renglon}: limite_superior={ultimo.limite_superior}, tasa_excedente={ultimo.tasa_excedente}")

    if Decimal(primero.limite_inferior) != Decimal("0.01"):
        fallas.append(f"El primer renglón arranca en {primero.limite_inferior}, se esperaba 0.01")
    if ultimo.limite_superior is not None:
        fallas.append(f"El último renglón tiene límite superior {ultimo.limite_superior}; debería ir sin techo")
    if Decimal(ultimo.tasa_excedente) != Decimal("0.35"):
        fallas.append(f"El último renglón tiene tasa {ultimo.tasa_excedente}, se esperaba 0.35")
    return fallas


def _paso_3_ninguna_tasa_en_porcentaje(resultado: ImportacionTarifasOut) -> list[str]:
    print("\n--- 3. Ninguna tasa almacenada quedó en escala de porcentaje ---")
    fallas: list[str] = []
    total = 0
    maxima = Decimal("0")
    for t in resultado.tarifas:
        for r in t.renglones:
            total += 1
            tasa = Decimal(r.tasa_excedente)
            maxima = max(maxima, tasa)
            if tasa >= 1:
                fallas.append(
                    f"{t.periodicidad.value} {t.ejercicio} renglón {r.renglon}: tasa_excedente={tasa} >= 1 "
                    "(parece estar en porcentaje, no en fracción)"
                )
    print(f"{total} renglones revisados en las 7 tarifas; tasa máxima observada: {maxima}")
    return fallas


# --------------------------------------------------------------------------------------
# 4-5: corregir a mano limpia la confirmación, y protege contra una reimportación que la pisara
# --------------------------------------------------------------------------------------


async def _paso_4_corregir_limpia_confirmacion(
    db: AsyncSession, resultado_import: ImportacionTarifasOut
) -> list[str]:
    print("\n--- 4. Confirmar la quincenal y luego corregir un renglón por el PUT ---")
    fallas: list[str] = []
    quincenal = next(
        t for t in resultado_import.tarifas if t.ejercicio == EJERCICIO and t.periodicidad is PeriodicidadTarifa.DIAS_15
    )

    confirmada = await configuracion.confirmar_tarifa_isr(
        ejercicio=EJERCICIO,
        periodicidad=PeriodicidadTarifa.DIAS_15,
        body=TarifaIsrConfirmarIn(huella=quincenal.huella),
        admin=ADMIN,
        db=db,
    )
    print(f"Confirmada antes de corregir: {confirmada.confirmada} (por {confirmada.confirmado_por})")
    if not confirmada.confirmada:
        fallas.append("La quincenal 2026 no quedó confirmada antes de ejercer la corrección manual")

    corregida = await configuracion.corregir_tarifa_isr(
        ejercicio=EJERCICIO,
        periodicidad=PeriodicidadTarifa.DIAS_15,
        body=_cuerpo_correccion(_tarifa_de_prueba_valida()),
        admin=ADMIN,
        db=db,
    )
    print(
        f"Tras corregir: origen={corregida.origen.value}, confirmada={corregida.confirmada}, "
        f"difiere_del_documento={corregida.difiere_del_documento}"
    )
    if corregida.confirmada:
        fallas.append("Corregir un renglón no limpió la confirmación previa (`confirmada` sigue en True)")
    if corregida.origen is not OrigenTarifa.MANUAL:
        fallas.append(f"Tras corregir, el origen quedó en {corregida.origen.value}, se esperaba MANUAL")
    if not corregida.difiere_del_documento:
        fallas.append("Tras corregir, `difiere_del_documento` quedó en False y se esperaba True")
    return fallas


async def _paso_5_reimportar_protegido(db: AsyncSession) -> list[str]:
    print("\n--- 5. Reimportar el mismo PDF sobre una corrección manual ---")
    fallas: list[str] = []
    antes = await repo.obtener(db, ejercicio=EJERCICIO, periodicidad=PeriodicidadTarifa.DIAS_15)

    try:
        await configuracion.importar_tarifa_isr(archivo=_archivo_anexo(), admin=ADMIN, db=db)
        fallas.append(
            "Reimportar el mismo PDF sobre una corrección manual no lanzó nada; se esperaba 409 CORRECCION_MANUAL"
        )
    except HTTPException as exc:
        codigo = _codigo_de(exc)
        print(f"Reimportar devolvió {exc.status_code} {codigo}")
        if exc.status_code != 409:
            fallas.append(f"Reimportar sobre una corrección manual devolvió {exc.status_code}, se esperaba 409")
        if codigo != "CORRECCION_MANUAL":
            fallas.append(f"Reimportar sobre una corrección manual devolvió el código {codigo}, se esperaba CORRECCION_MANUAL")
        # Nada se escribió antes de que `guardar_importadas` lanzara (ver su docstring: la
        # primera pasada solo lee); se revierte por higiene, no porque haya algo que deshacer.
        await db.rollback()

    despues = await repo.obtener(db, ejercicio=EJERCICIO, periodicidad=PeriodicidadTarifa.DIAS_15)
    sigue_en_pie = (
        despues is not None
        and despues.origen is OrigenTarifa.MANUAL
        and antes is not None
        and despues.huella == antes.huella
    )
    if not sigue_en_pie:
        fallas.append("La corrección manual de la quincenal 2026 no siguió en pie tras el intento de reimportar")
    else:
        print("La corrección manual sigue en pie tras el intento de reimportar (mismo origen, misma huella).")
    return fallas


# --------------------------------------------------------------------------------------
# 6-7: descartar, reimportar y confirmar; la resolución pasa de ausente a presente
# --------------------------------------------------------------------------------------


async def _paso_6_y_7_descartar_reimportar_confirmar(
    db: AsyncSession,
) -> tuple[ImportacionTarifasOut | None, list[str]]:
    print("\n--- 6-7. Descartar la corrección, reimportar, y confirmar la quincenal con su huella ---")
    fallas: list[str] = []

    await configuracion.borrar_tarifa_isr(
        ejercicio=EJERCICIO, periodicidad=PeriodicidadTarifa.DIAS_15, admin=ADMIN, db=db
    )
    print("Corrección manual de la quincenal 2026 descartada (DELETE de la propuesta sin confirmar).")

    resultado = await configuracion.importar_tarifa_isr(archivo=_archivo_anexo(), admin=ADMIN, db=db)
    print(f"Reimportado tras descartar: {len(resultado.tarifas)} tarifas.")
    if len(resultado.tarifas) != 7:
        fallas.append(f"Tras descartar y reimportar se obtuvieron {len(resultado.tarifas)} tarifas, se esperaban 7")

    vigente_antes = await repo.vigente(db, ejercicio=EJERCICIO, periodicidad=PeriodicidadTarifa.DIAS_15)
    print(f"`repo.vigente()` antes de confirmar: {'presente (defecto)' if vigente_antes is not None else 'ausente'}")
    if vigente_antes is not None:
        fallas.append("`repo.vigente` devolvió una tarifa antes de confirmarla; debería devolver None")

    quincenal = next(
        (t for t in resultado.tarifas if t.ejercicio == EJERCICIO and t.periodicidad is PeriodicidadTarifa.DIAS_15),
        None,
    )
    if quincenal is None:
        fallas.append("La quincenal 2026 no apareció entre las tarifas reimportadas; no se puede confirmar")
        return None, fallas

    confirmada = await configuracion.confirmar_tarifa_isr(
        ejercicio=EJERCICIO,
        periodicidad=PeriodicidadTarifa.DIAS_15,
        body=TarifaIsrConfirmarIn(huella=quincenal.huella),
        admin=ADMIN,
        db=db,
    )
    if not confirmada.confirmada:
        fallas.append("La quincenal 2026 no quedó confirmada tras `POST .../confirmar` con su huella")

    presente_despues = await repo.vigente(db, ejercicio=EJERCICIO, periodicidad=PeriodicidadTarifa.DIAS_15)
    print(f"`repo.vigente()` después de confirmar: {'presente' if presente_despues is not None else 'AUSENTE (defecto)'}")
    if presente_despues is None:
        fallas.append("`repo.vigente` sigue devolviendo None después de confirmar la quincenal 2026")

    listado_final = await configuracion.listar_tarifa_isr(admin=ADMIN, db=db)
    return listado_final, fallas


# --------------------------------------------------------------------------------------
# 8: la comprobación contra un recibo real
# --------------------------------------------------------------------------------------


def _paso_8_comprobacion(listado: ImportacionTarifasOut) -> list[str]:
    print("\n--- 8. Comprobación de la quincenal confirmada contra un recibo real ---")
    fallas: list[str] = []
    quincenal = next(
        (t for t in listado.tarifas if t.ejercicio == EJERCICIO and t.periodicidad is PeriodicidadTarifa.DIAS_15),
        None,
    )
    if quincenal is None:
        fallas.append("La quincenal 2026 no aparece en `GET /tarifa-isr` tras confirmarla")
        return fallas
    if quincenal.comprobacion is None:
        fallas.append(
            "No hay comprobación contra un recibo real para la quincenal 2026 confirmada: "
            "¿la empresa 11 dejó de tener nómina quincenal ordinaria con gravado > 0?"
        )
        return fallas

    c = quincenal.comprobacion
    isr_calculado = Decimal(c.isr_calculado)
    isr_timbrado = Decimal(c.isr_timbrado)
    diferencia = Decimal(c.diferencia)
    print(
        f"UUID {c.uuid} · renglón {c.renglon} · gravado {c.gravado} · "
        f"isr_calculado={isr_calculado} · isr_timbrado={isr_timbrado} · diferencia={diferencia}"
    )
    if c.advertencias:
        print(f"  advertencias: {list(c.advertencias)}")

    if c.renglon < 1:
        fallas.append(f"La comprobación trae un renglón inválido: {c.renglon}")

    # "De pesos, no de órdenes de magnitud": el propio módulo (`comprobacion_tarifa`, §7.3 del
    # diseño) dice que una diferencia relativa de más de la mitad del impuesto es la señal de
    # una tarifa mal cargada (otra periodicidad u otro ejercicio en el slot equivocado). Aquí se
    # exige un margen bastante más generoso —el doble del ISR timbrado— para no duplicar ese
    # umbral de diseño: basta con descartar un error de "orden de magnitud" (10x, 100x), no con
    # replicar el límite exacto que ya prueba `test_comprobacion_tarifa.py`.
    if isr_timbrado > 0 and abs(diferencia) > isr_timbrado * 2:
        fallas.append(
            f"La diferencia ({diferencia}) es más del doble del ISR timbrado ({isr_timbrado}): parece un error "
            "de carga (otra periodicidad/ejercicio en el slot), no una diferencia de pesos por subsidio o ajustes"
        )
    return fallas


# --------------------------------------------------------------------------------------
# 9: la alarma de vigencia, antes (encendida) y después (apagada)
# --------------------------------------------------------------------------------------


def _paso_9a_alerta_antes(alertas: list[sincronizacion.AlertaVigencia]) -> list[str]:
    print("\n--- 9a. Alerta TARIFA_ISR antes de cargar nada ---")
    fallas: list[str] = []
    de_tarifa = [a for a in alertas if a.clave == sincronizacion.CLAVE_TARIFA_ISR]
    print(f"Alertas TARIFA_ISR encontradas: {[(a.motivo, a.detalle) for a in de_tarifa]}")
    if len(de_tarifa) != 1:
        fallas.append(f"Se esperaba exactamente una alerta TARIFA_ISR antes de cargar tarifas y hay {len(de_tarifa)}")
    elif de_tarifa[0].motivo not in ("AUSENTE", "SIN_CONFIRMAR"):
        fallas.append(f"La alerta TARIFA_ISR antes de cargar tenía motivo {de_tarifa[0].motivo}, se esperaba AUSENTE o SIN_CONFIRMAR")
    return fallas


def _paso_9b_alerta_despues(alertas: list[sincronizacion.AlertaVigencia]) -> list[str]:
    print("\n--- 9b. Alerta TARIFA_ISR tras confirmar la quincenal ---")
    fallas: list[str] = []
    de_tarifa = [a for a in alertas if a.clave == sincronizacion.CLAVE_TARIFA_ISR]
    if de_tarifa:
        fallas.append(
            f"La alerta TARIFA_ISR sigue encendida tras confirmar la quincenal 2026 (motivo {de_tarifa[0].motivo}): "
            f"{de_tarifa[0].detalle}"
        )
    else:
        print("Apagada: no hay alerta TARIFA_ISR con la única periodicidad observada (quincenal) ya confirmada.")
    return fallas


# --------------------------------------------------------------------------------------
# 10: la hoja de revisión en PDF
# --------------------------------------------------------------------------------------


async def _paso_10_hoja_pdf(db: AsyncSession) -> list[str]:
    print("\n--- 10. Hoja de revisión en PDF ---")
    fallas: list[str] = []
    respuesta = await configuracion.hoja_revision_tarifa_isr(
        ejercicio=EJERCICIO, periodicidad=PeriodicidadTarifa.DIAS_15, admin=ADMIN, db=db
    )
    cuerpo = respuesta.body
    print(f"Hoja de revisión generada: {len(cuerpo)} bytes, media_type={respuesta.media_type}")
    if not cuerpo.startswith(b"%PDF"):
        fallas.append(f"La hoja de revisión no empieza con %PDF (primeros bytes: {cuerpo[:16]!r})")
    return fallas


# --------------------------------------------------------------------------------------
# 11: dejar la base como estaba, y decirlo
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Fotografia:
    """Lo que este script promete no tocar. Se toma antes de empezar y se compara al final:
    una comparación es la única forma honesta de decir "no lo toqué", en vez de solo afirmarlo."""

    param_fiscal_total: int
    param_fiscal_confirmados: int
    catalogo_percepcion_total: int
    catalogo_percepcion_confirmados: int
    bitacora_total: int


async def _fotografia(db: AsyncSession) -> _Fotografia:
    param_total = (await db.scalar(select(func.count()).select_from(ParamFiscal))) or 0
    param_confirmados = (
        await db.scalar(select(func.count()).select_from(ParamFiscal).where(ParamFiscal.confirmado_en.is_not(None)))
    ) or 0
    marca_total = (await db.scalar(select(func.count()).select_from(CatalogoPercepcionMarca))) or 0
    marca_confirmadas = (
        await db.scalar(
            select(func.count()).select_from(CatalogoPercepcionMarca).where(CatalogoPercepcionMarca.confirmado_en.is_not(None))
        )
    ) or 0
    bitacora_total = (await db.scalar(select(func.count()).select_from(Bitacora))) or 0
    return _Fotografia(
        param_fiscal_total=int(param_total),
        param_fiscal_confirmados=int(param_confirmados),
        catalogo_percepcion_total=int(marca_total),
        catalogo_percepcion_confirmados=int(marca_confirmadas),
        bitacora_total=int(bitacora_total),
    )


async def _paso_11_revertir(db: AsyncSession, antes: _Fotografia) -> list[str]:
    print("\n--- 11. Dejar la base como estaba ---")
    fallas: list[str] = []

    ejercicios_creados = {ejercicio for ejercicio, _periodicidad in TARIFAS_ESPERADAS}
    await db.execute(delete(TarifaIsrRenglon).where(TarifaIsrRenglon.ejercicio.in_(ejercicios_creados)))
    resultado_borrado = await db.execute(delete(TarifaIsr).where(TarifaIsr.ejercicio.in_(ejercicios_creados)))
    await db.commit()
    print(
        f"Descartadas {resultado_borrado.rowcount} cabecera(s) de `tarifa_isr` de los ejercicios "
        f"{sorted(ejercicios_creados)} (con sus renglones), creadas por esta corrida."
    )

    quedan = await repo.listar(db)
    if quedan:
        fallas.append(
            f"NO SE PUDO DEJAR `tarifa_isr` COMO SE ENCONTRÓ: siguen quedando {len(quedan)} tarifa(s) tras el "
            "borrado de limpieza. Revisa la tabla a mano antes de seguir."
        )
    else:
        print("`tarifa_isr` queda vacía, igual que al empezar esta corrida.")

    despues = await _fotografia(db)
    if (despues.param_fiscal_total, despues.param_fiscal_confirmados) != (antes.param_fiscal_total, antes.param_fiscal_confirmados):
        fallas.append(
            f"`param_fiscal` cambió: antes {antes.param_fiscal_total} fila(s) ({antes.param_fiscal_confirmados} "
            f"confirmada(s)), ahora {despues.param_fiscal_total} ({despues.param_fiscal_confirmados}). Este "
            "script no debía tocar esa tabla; revísala a mano."
        )
    else:
        print(f"`param_fiscal` sin cambios: {despues.param_fiscal_total} fila(s), {despues.param_fiscal_confirmados} confirmada(s).")

    if (despues.catalogo_percepcion_total, despues.catalogo_percepcion_confirmados) != (
        antes.catalogo_percepcion_total,
        antes.catalogo_percepcion_confirmados,
    ):
        fallas.append(
            f"`catalogo_percepcion_marca` cambió: antes {antes.catalogo_percepcion_total} fila(s) "
            f"({antes.catalogo_percepcion_confirmados} confirmada(s)), ahora {despues.catalogo_percepcion_total} "
            f"({despues.catalogo_percepcion_confirmados}). Este script no debía tocar esa tabla; revísala a mano."
        )
    else:
        print(
            f"`catalogo_percepcion_marca` sin cambios: {despues.catalogo_percepcion_total} fila(s), "
            f"{despues.catalogo_percepcion_confirmados} confirmada(s)."
        )

    nuevas_bitacora = despues.bitacora_total - antes.bitacora_total
    print(
        f"La bitácora ganó {nuevas_bitacora} fila(s) nueva(s) (importar/corregir/confirmar/borrar de esta "
        "corrida). NO se borran: `bitacora` es append-only por diseño (regla 8 de CLAUDE.md) y limpiarla "
        "violaría esa regla para dejar constancia de una prueba que, por definición, no tiene efecto final. "
        "Quedan marcadas con actor='verificacion@script', distinguibles de cualquier acción real de un "
        "administrador."
    )
    return fallas


# --------------------------------------------------------------------------------------


async def main() -> int:
    print(f"Verificación en vivo de la tarifa del ISR — {ANEXO_2026}")

    async with SessionLocal() as db:
        preexistentes = await repo.listar(db)
    if preexistentes:
        print(
            f"\nABORTA: ya hay {len(preexistentes)} tarifa(s) en `tarifa_isr` "
            f"({sorted((t.ejercicio, t.periodicidad.value) for t in preexistentes)}). Este script solo puede "
            "prometer dejar la tabla como la encontró si empieza sabiendo con certeza qué había antes, y hoy "
            "no está vacía. No se tocó nada; revisa la tabla a mano antes de correrlo."
        )
        return 1

    async with SessionLocal() as db:
        fotografia_antes = await _fotografia(db)
        alertas_antes = await sincronizacion.alertas_de_vigencia(db, date.today())
    fallas = _paso_9a_alerta_antes(alertas_antes)

    # Todo lo que crea datos de prueba (pasos 1-8 y 10, más la lectura de la alarma "después") va
    # en este `try`, y la limpieza del paso 11 va en su `finally` — no después del bloque, sino
    # *dentro* de él. La diferencia importa: si algo de aquí lanza una excepción no prevista (un
    # bug real, un corte transitorio de MySQL), el `finally` corre de todos modos y las 7
    # cabeceras con sus 77 renglones no quedan abandonadas en la base real sin ningún aviso.
    # Comprobado inyectando un `raise` temporal justo antes de la limpieza y confirmando por SQL
    # que la base queda igual de limpia (ver el reporte de la Task 12).
    listado_final: ImportacionTarifasOut | None = None
    try:
        async with SessionLocal() as db:
            resultado_1, f = await _paso_1_importar(db)
            fallas += f

            fallas += _paso_2_estructura_quincenal(resultado_1)
            fallas += _paso_3_ninguna_tasa_en_porcentaje(resultado_1)

            fallas += await _paso_4_corregir_limpia_confirmacion(db, resultado_1)
            fallas += await _paso_5_reimportar_protegido(db)

            listado_final, f = await _paso_6_y_7_descartar_reimportar_confirmar(db)
            fallas += f

            if listado_final is not None:
                fallas += _paso_8_comprobacion(listado_final)

            fallas += await _paso_10_hoja_pdf(db)

        async with SessionLocal() as db:
            alertas_despues = await sincronizacion.alertas_de_vigencia(db, date.today())
        fallas += _paso_9b_alerta_despues(alertas_despues)
    except Exception as exc:  # noqa: BLE001 - cualquier excepción no prevista es un defecto que reportar, no esconder
        traceback.print_exc()
        fallas.append(f"Excepción no manejada durante la verificación: {type(exc).__name__}: {exc}")
    finally:
        async with SessionLocal() as db:
            fallas += await _paso_11_revertir(db, fotografia_antes)

    if fallas:
        print("\nFALLAS:")
        for falla in fallas:
            print("  -", falla)
        return 1
    print("\nTodas las comprobaciones pasaron, y la base quedó como se encontró.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
