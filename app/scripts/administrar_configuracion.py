"""Administra la configuración fiscal desde una terminal: leer el estado, capturar valores,
**confirmarlos**, y clasificar los conceptos y departamentos de una empresa.

Por qué existe
--------------
Las tareas 1-6 de la fase 3 dejaron toda la configuración administrable desde una pantalla
web. Quien administra el Hub no siempre tiene navegador delante —trabajo remoto, recuperación
ante desastre, un despliegue que hay que dejar configurado— y necesita capturar y confirmar
igual. La alternativa descartada fue emitir un token de Firebase de su cuenta y llamar a la
API: técnicamente funciona, pero suplanta su sesión y **el rastro de auditoría mentiría**,
diría que alguien usó la pantalla cuando no fue así. Esta herramienta hace lo mismo dejando
constancia de por dónde entró (`detalle.via = "linea_de_comandos"` en cada fila de bitácora),
que es la única diferencia honesta entre las dos rutas.

Lo que esta herramienta NO es
------------------------------
**No es una puerta trasera.** Todo invariante que el endpoint hace cumplir, se hace cumplir
aquí *ejerciendo el mismo código*, no una copia:

- toda escritura de `param_fiscal` pasa por `cfg.guardar_param_fiscal`, donde viven el
  rechazo de solapamiento de vigencias, el candado contra escrituras concurrentes y el
  limpiado de la confirmación cuando la cifra cambia. Aquí no se construye ningún
  `ParamFiscal` a mano;
- confirmar un importe pasa por `cfg.confirmar_param_fiscal`, que **exige el valor que se
  confirma** y rechaza si no coincide con el almacenado;
- confirmar una marca pasa por `cfg.confirmar_marca_percepcion`, que **exige la huella de su
  `nota_revision`** y el juego completo de marcas;
- cada cambio deja bitácora **en la misma transacción** (regla 8), con el valor anterior y el
  nuevo. Si la bitácora falla, el cambio se revierte con ella.

Si mañana alguien endurece una de esas guardas en el servicio, esta herramienta se endurece
sola. Ese es todo el diseño.

Quién es el actor
-----------------
`--actor correo@dominio` es **obligatorio** en todo lo que escribe y no tiene default. La
autorización aquí no es un rol: es tener el shell y las credenciales de la base, que es el
poder de un DBA. Lo que el actor registra es **quién responde** por el cambio, y por eso se
comprueba contra `usuarios`: un actor tecleado mal deja una bitácora que no se puede auditar.
`--actor-externo` es la salida explícita para una recuperación ante desastre donde todavía no
hay usuarios.

Uso:
    python -m app.scripts.administrar_configuracion estado
    python -m app.scripts.administrar_configuracion estado --percepciones --empresa-id 11
    python -m app.scripts.administrar_configuracion confirmar-valor --actor a@b.mx \\
        --valor UMA_DIARIA 117.31 2026-02-01
    python -m app.scripts.administrar_configuracion capturar-valor UMA_DIARIA \\
        --valor 117.31 --vigencia-desde 2026-02-01 --fuente "DOF 2026-01-15" --actor a@b.mx
    python -m app.scripts.administrar_configuracion confirmar-marca 015 --huella <sha256> --actor a@b.mx
    python -m app.scripts.administrar_configuracion configurar-empresa --empresa-id 11 \\
        --zona-salarial ZLFN --actor a@b.mx
    python -m app.scripts.administrar_configuracion observados --empresa-id 11
    python -m app.scripts.administrar_configuracion clasificar --empresa-id 11 \\
        --concepto P/001/001 NO_APLICA --actor a@b.mx

Sale con código distinto de cero ante cualquier fallo, y también cuando la persona cancela:
que nada se haya escrito no es un éxito del que un script de despliegue deba seguir adelante.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.informes import catalogos
from app.models.configuracion_fiscal import (
    CatalogoPercepcionMarca,
    ConfiguracionEmpresa,
    MapConceptoProvision,
    MapDepartamento,
    ParamFiscal,
)
from app.models.empresa import Empresa
from app.models.enums import CategoriaProvision, OrigenValor, RolGlobal, ZonaSalarial
from app.models.usuario import Usuario
from app.services import bitacora as bitacora_service
from app.services import configuracion_fiscal as cfg
from app.services import sincronizacion_fiscal as sincronizacion

# El marcador que es el punto de la herramienta: la bitácora tiene que poder distinguir un
# cambio hecho desde la pantalla de uno hecho desde una terminal. Sin él, la única forma de
# administrar sin navegador sería suplantar una sesión, y el rastro diría algo que no pasó.
VIA_LINEA_DE_COMANDOS = "linea_de_comandos"
_HERRAMIENTA = "app.scripts.administrar_configuracion"

# Las tres naturalezas de concepto del complemento de Nómina (percepción, deducción, otro
# pago). Es el mismo conjunto que recorre `cfg.observados_de_empresa`.
_NATURALEZAS = ("P", "D", "O")


class ErrorDeUso(Exception):
    """Algo que la persona que teclea puede corregir: una clave que no existe, un importe que
    no es un número, una empresa que no está. Se imprime sin traza y sale con código 1 — una
    traza de Python para "tecleaste ZLNF en vez de ZLFN" esconde el mensaje útil."""


def _detalle(**campos: Any) -> dict[str, Any]:
    """El `detalle` de bitácora con el marcador de por dónde entró el cambio.

    `via` va en el `detalle` y no en la `accion` a propósito: la acción tiene que seguir
    siendo `confirmar_param_fiscal` para que la pantalla de bitácora agrupe los dos caminos
    bajo el mismo hecho —confirmar un valor es lo mismo se haga por donde se haga—, mientras
    que *cómo* se hizo es una circunstancia del renglón.
    """
    return {"via": VIA_LINEA_DE_COMANDOS, "herramienta": _HERRAMIENTA, **campos}


# --------------------------------------------------------------------------------------
# Conversión de lo que llega por la línea de comandos
# --------------------------------------------------------------------------------------


def importe(texto: str, campo: str) -> Decimal:
    """Un importe fiscal desde **texto**, jamás desde `float`.

    `Decimal(str)` es exacto; `Decimal(float(str))` no: verificado, `12345678901.123456`
    pasado por `float` se convierte en `...455`, y la cifra almacenada dejaría de ser la que
    se revisó. Es la misma regla que la API aplica a los números JSON (`_sin_float`) y el
    cargador al YAML (`_decimal`), por la misma razón.
    """
    try:
        valor = Decimal(texto.strip())
    except InvalidOperation:
        raise ErrorDeUso(f"`{campo}` no es un número válido ({texto!r}).") from None
    if not valor.is_finite():
        raise ErrorDeUso(f"`{campo}` tiene que ser un número finito y llegó {texto!r}.")
    return valor


def _fecha(texto: str, campo: str) -> date:
    try:
        return date.fromisoformat(texto.strip())
    except ValueError:
        raise ErrorDeUso(f"`{campo}` no es una fecha AAAA-MM-DD válida ({texto!r}).") from None


def _categoria(texto: str) -> CategoriaProvision:
    try:
        return CategoriaProvision(texto.strip().upper())
    except ValueError:
        opciones = ", ".join(c.value for c in CategoriaProvision)
        raise ErrorDeUso(f"`{texto}` no es una categoría de provisión. Opciones: {opciones}.") from None


def _zona(texto: str) -> ZonaSalarial:
    try:
        return ZonaSalarial(texto.strip().upper())
    except ValueError:
        opciones = ", ".join(z.value for z in ZonaSalarial)
        raise ErrorDeUso(f"`{texto}` no es una zona salarial. Opciones: {opciones}.") from None


def concepto_partido(texto: str) -> tuple[str, str, str]:
    """`P/001/019` -> `("P", "001", "019")`.

    Se parte por los **dos primeros** separadores y no por todos: la `clave` es un texto que
    inventa el sistema de nómina del patrón y puede traer barras. Las claves de catálogo del
    SAT se conservan como texto (`'001'`, nunca `1`): los ceros a la izquierda cuentan y
    `'015'` no es `'150'`.
    """
    partes = texto.strip().split("/", 2)
    if len(partes) != 3:
        raise ErrorDeUso(
            f"`{texto}` no tiene la forma NATURALEZA/TIPO/CLAVE (p. ej. `P/001/019`). "
            "La naturaleza es P, D u O; el tipo son las 3 posiciones del catálogo del SAT."
        )
    naturaleza, tipo, clave = (p.strip() for p in partes)
    if naturaleza.upper() not in _NATURALEZAS:
        raise ErrorDeUso(
            f"`{texto}`: la naturaleza es {naturaleza!r} y tiene que ser P (percepción), "
            "D (deducción) u O (otro pago)."
        )
    if len(tipo) != 3:
        raise ErrorDeUso(
            f"`{texto}`: el tipo es {tipo!r} y el catálogo del SAT usa 3 posiciones. Revisa los ceros "
            "a la izquierda: '015' y '150' se teclean casi igual y no son el mismo concepto."
        )
    if not clave or len(clave) > 15:
        raise ErrorDeUso(f"`{texto}`: la clave es {clave!r} y tiene que medir entre 1 y 15 caracteres.")
    return naturaleza.upper(), tipo, clave


# --------------------------------------------------------------------------------------
# Seguridad de operación: quién, y no hacer nada a ciegas
# --------------------------------------------------------------------------------------


async def exige_actor(db: AsyncSession, correo: str, *, externo: bool) -> str:
    """El correo de quien responde por el cambio, comprobado contra `usuarios`.

    No es un control de acceso —quien corre esto ya tiene la base delante— sino de **calidad
    del rastro**: `dgarcia@planjuarez.ogr` se acepta igual de bien que el bueno y deja una
    bitácora que ya no se puede atribuir a nadie. Con `--actor-externo` se salta la
    comprobación, que es lo que hace falta en una recuperación donde aún no hay usuarios.
    """
    limpio = correo.strip()
    if not limpio or "@" not in limpio:
        raise ErrorDeUso(f"`--actor` tiene que ser un correo (llegó {correo!r}).")
    if len(limpio) > 190:
        raise ErrorDeUso("`--actor` no cabe en la columna `bitacora.actor` (máximo 190 caracteres).")
    if externo:
        return limpio
    usuario = (
        await db.execute(select(Usuario.rol_global, Usuario.activo).where(Usuario.correo == limpio))
    ).first()
    if usuario is None:
        raise ErrorDeUso(
            f"`{limpio}` no es el correo de ningún usuario del Hub, así que la bitácora quedaría a "
            "nombre de nadie. Revisa si lo tecleaste mal, o usa `--actor-externo` si de verdad "
            "quieres registrar a alguien que no tiene cuenta (recuperación ante desastre)."
        )
    if not usuario.activo:
        raise ErrorDeUso(
            f"`{limpio}` es un usuario dado de baja. Usa el correo de alguien que responda por el "
            "cambio hoy, o `--actor-externo` si es a propósito."
        )
    if usuario.rol_global is not RolGlobal.ADMIN:
        # No se bloquea: la pantalla exige `admin` para lo global y `operador` para lo de una
        # empresa, y aquí no hay sesión que comprobar. Pero que el rastro diga "lo confirmó
        # alguien que por la pantalla no habría podido" es exactamente lo que hay que ver.
        print(
            f"AVISO: {limpio} tiene rol '{usuario.rol_global.value}'. Por la pantalla no habría "
            "podido hacer este cambio; queda registrado igual, con su nombre.",
            file=sys.stderr,
        )
    return limpio


def pregunta(texto: str, *, si: bool) -> bool:
    """Confirmación interactiva. `--si` la salta (para un despliegue automatizado), y sin
    terminal **no** se asume que sí: un cron que se quedó sin `--si` tiene que fallar, no
    aplicar cambios que nadie miró.

    El default es **no**: cualquier cosa que no sea "s"/"si"/"sí" cancela, incluido un Enter
    de más pegado desde otra ventana."""
    if si:
        print(f"{texto} -> sí (--si)")
        return True
    if not sys.stdin.isatty():
        raise ErrorDeUso(
            "No hay terminal para preguntar y la acción necesita confirmación. Vuelve a correrlo "
            "con `--si` si de verdad quieres aplicarla sin que nadie la mire."
        )
    print(f"{texto} [s/N]: ", end="", flush=True)
    return sys.stdin.readline().strip().lower() in ("s", "si", "sí")


# --------------------------------------------------------------------------------------
# Lecturas para el estado y para los planes
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _TramoLeido:
    """Un tramo tal como está hoy. Se lee **por columnas y no como entidad** a propósito:
    cargar el `ParamFiscal` por el ORM lo metería en el mapa de identidad y la lectura
    `FOR UPDATE` de la puerta de escritura devolvería ese mismo objeto sin refrescarlo, así
    que la guarda del valor compararía contra lo que se leyó antes en vez de contra lo que hay.
    Ver el argumento largo en `cfg.snapshot_de_tramo`."""

    valor: Decimal
    ejercicio: int
    vigencia_hasta: date | None
    origen: OrigenValor
    fuente: str
    confirmado_por: str | None
    confirmado: bool


async def leer_tramo(db: AsyncSession, clave: str, vigencia_desde: date) -> _TramoLeido | None:
    fila = (
        await db.execute(
            select(
                ParamFiscal.valor,
                ParamFiscal.ejercicio,
                ParamFiscal.vigencia_hasta,
                ParamFiscal.origen,
                ParamFiscal.fuente,
                ParamFiscal.confirmado_por,
                ParamFiscal.confirmado_en,
            ).where(ParamFiscal.clave == clave, ParamFiscal.vigencia_desde == vigencia_desde)
        )
    ).first()
    if fila is None:
        return None
    return _TramoLeido(
        valor=fila.valor,
        ejercicio=fila.ejercicio,
        vigencia_hasta=fila.vigencia_hasta,
        origen=fila.origen,
        fuente=fila.fuente,
        confirmado_por=fila.confirmado_por,
        confirmado=fila.confirmado_en is not None,
    )


@dataclass(frozen=True)
class _MarcaLeida:
    """Las marcas de un tipo tal como están hoy, con la huella de su duda. Por columnas, por
    la misma razón que `_TramoLeido`."""

    marcas: cfg.MarcasQueCalculan
    nota_revision: str | None
    huella: str | None
    confirmado_por: str | None
    confirmado: bool


async def leer_marca(db: AsyncSession, tipo: str) -> _MarcaLeida | None:
    fila = (
        await db.execute(
            select(
                CatalogoPercepcionMarca.es_ingreso_ordinario,
                CatalogoPercepcionMarca.base_exencion,
                CatalogoPercepcionMarca.factor_exencion,
                CatalogoPercepcionMarca.integra_sbc,
                CatalogoPercepcionMarca.es_provisionable,
                CatalogoPercepcionMarca.sujeto_a_tope_conjunto,
                CatalogoPercepcionMarca.nota_revision,
                CatalogoPercepcionMarca.confirmado_por,
                CatalogoPercepcionMarca.confirmado_en,
            ).where(CatalogoPercepcionMarca.tipo_percepcion == tipo)
        )
    ).first()
    if fila is None:
        return None
    return _MarcaLeida(
        marcas=cfg.MarcasQueCalculan(
            es_ingreso_ordinario=fila.es_ingreso_ordinario,
            base_exencion=fila.base_exencion,
            factor_exencion=fila.factor_exencion,
            integra_sbc=fila.integra_sbc,
            es_provisionable=fila.es_provisionable,
            sujeto_a_tope_conjunto=fila.sujeto_a_tope_conjunto,
        ),
        nota_revision=fila.nota_revision,
        huella=cfg.huella_de_nota(fila.nota_revision),
        confirmado_por=fila.confirmado_por,
        confirmado=fila.confirmado_en is not None,
    )


async def _exige_empresa(db: AsyncSession, empresa_id: int) -> Empresa:
    empresa = await db.get(Empresa, empresa_id)
    if empresa is None:
        raise ErrorDeUso(f"No existe la empresa {empresa_id}.")
    return empresa


# --------------------------------------------------------------------------------------
# `estado`: lo que sustituye a mirar la pantalla
# --------------------------------------------------------------------------------------


def _si_no(valor: bool) -> str:
    return "sí" if valor else "no"


def _vigencia(desde: date, hasta: date | None) -> str:
    return f"del {desde} al {hasta}" if hasta else f"desde {desde}, hasta nuevo aviso"


async def _mostrar_valores_fiscales(db: AsyncSession) -> None:
    filas = list(
        (await db.scalars(select(ParamFiscal).order_by(ParamFiscal.clave, ParamFiscal.vigencia_desde))).all()
    )
    confirmados = sum(1 for f in filas if f.confirmado_en is not None)
    print(f"VALORES FISCALES — {len(filas)} capturado(s), {confirmados} confirmado(s)")
    if not filas:
        print("  (ninguno; los informes reportarán todo como faltante)")
    for fila in filas:
        print(f"\n  {fila.clave}  ({_vigencia(fila.vigencia_desde, fila.vigencia_hasta)})")
        print(f"      cifra        {fila.valor}   ejercicio {fila.ejercicio}")
        print(f"      procedencia  {fila.origen.value} — {fila.fuente}")
        if fila.confirmado_en is not None:
            print(f"      confirmado   sí, por {fila.confirmado_por} el {fila.confirmado_en:%Y-%m-%d %H:%M} UTC")
        else:
            print("      confirmado   NO — sin confirmar no calcula: ningún informe lo usa todavía")

    sin_valor = sorted(cfg.CLAVES_PARAM_FISCAL - {f.clave for f in filas})
    if sin_valor:
        print(f"\n  Sin ninguna propuesta capturada: {', '.join(sin_valor)}")


async def _mostrar_alertas(db: AsyncSession, hoy: date) -> None:
    alertas = await sincronizacion.alertas_de_vigencia(db, hoy)
    print(f"\nALERTAS DE VIGENCIA al {hoy} — {len(alertas)}")
    if not alertas:
        print("  (ninguna: todo al día)")
    for alerta in alertas:
        print(f"  [{alerta.motivo}] {alerta.clave}")
        if alerta.detalle:
            print(f"      {alerta.detalle}")


async def _mostrar_percepciones(db: AsyncSession, *, detallado: bool) -> None:
    filas = list(
        (await db.scalars(select(CatalogoPercepcionMarca).order_by(CatalogoPercepcionMarca.tipo_percepcion))).all()
    )
    # `tipos_de` falla abierto (devuelve vacío si el catálogo no se puede leer): aquí se está
    # leyendo, y una descripción ausente no impide revisar una marca. Escribir sí falla cerrado.
    descripciones = dict(catalogos.tipos_de("P"))
    confirmadas = sum(1 for f in filas if f.confirmado_en is not None)
    con_duda = sum(1 for f in filas if f.nota_revision is not None)
    total_sat = len(descripciones) or len(filas)
    print(
        f"\nMARCAS DE PERCEPCIÓN — {len(filas)} de {total_sat} capturadas, "
        f"{confirmadas} confirmada(s), {con_duda} con duda declarada"
    )
    if not detallado:
        print("  (usa `estado --percepciones` para verlas una por una, con su huella)")
        return
    for fila in filas:
        descripcion = descripciones.get(fila.tipo_percepcion) or "(sin descripción en el catálogo instalado)"
        print(f"\n  {fila.tipo_percepcion}  {descripcion}")
        print(
            f"      ingreso ordinario: {_si_no(fila.es_ingreso_ordinario)}   "
            f"integra SBC: {_si_no(fila.integra_sbc)}   provisionable: {_si_no(fila.es_provisionable)}"
        )
        factor = fila.factor_exencion if fila.factor_exencion is not None else "—"
        print(
            f"      exención: base {fila.base_exencion.value}, factor {factor}   "
            f"tope conjunto art. 93: {_si_no(fila.sujeto_a_tope_conjunto)}"
        )
        if fila.nota_revision:
            print(f"      DUDA DECLARADA: {fila.nota_revision}")
            print(f"      huella de la duda: {cfg.huella_de_nota(fila.nota_revision)}")
        if fila.confirmado_en is not None:
            print(f"      confirmada   sí, por {fila.confirmado_por} el {fila.confirmado_en:%Y-%m-%d %H:%M} UTC")
        else:
            print("      confirmada   NO — sin confirmar no calcula ninguna exención")


async def _mostrar_empresa(db: AsyncSession, empresa_id: int) -> None:
    empresa = await _exige_empresa(db, empresa_id)
    print(f"\nEMPRESA {empresa_id} — {empresa.nombre} ({empresa.rfc})")
    config = await cfg.configuracion_de_empresa(db, empresa_id)
    zona = config.zona_salarial.value if config is not None and config.zona_salarial else None
    dias = config.dias_aguinaldo if config is not None else None
    factor = config.factor_prima_vacacional if config is not None else None
    print(f"  zona salarial            {zona or 'SIN CONFIGURAR — B-10 no puede validar el salario mínimo'}")
    print(f"  días de aguinaldo        {dias if dias is not None else 'sin configurar'}")
    print(f"  factor prima vacacional  {factor if factor is not None else 'sin configurar'}")

    observados = await cfg.observados_de_empresa(db, empresa)
    clasificables = [c for c in observados.conceptos if c.clave is not None]
    sin_clasificar = sum(1 for c in clasificables if c.categoria is None)
    sin_mapear = sum(1 for d in observados.departamentos if d.centro_costo is None)
    print(
        f"  conceptos observados     {len(observados.conceptos)} "
        f"({sin_clasificar} sin clasificar de los {len(clasificables)} que se pueden clasificar)"
    )
    print(f"  departamentos observados {len(observados.departamentos)} ({sin_mapear} sin centro de costo)")


async def cmd_estado(db: AsyncSession, args: argparse.Namespace) -> int:
    await _mostrar_valores_fiscales(db)
    await _mostrar_alertas(db, date.today())
    await _mostrar_percepciones(db, detallado=bool(args.percepciones))
    if args.empresa_id is not None:
        await _mostrar_empresa(db, int(args.empresa_id))
    return 0


# --------------------------------------------------------------------------------------
# `observados`: la lista de la que se eligen las categorías
# --------------------------------------------------------------------------------------


async def cmd_observados(db: AsyncSession, args: argparse.Namespace) -> int:
    """Lo que la nómina de la empresa **emitió de verdad**, para poder clasificar sin conocer
    las claves internas del sistema de nómina del patrón (que nadie sabe de memoria)."""
    empresa = await _exige_empresa(db, int(args.empresa_id))
    observados = await cfg.observados_de_empresa(db, empresa)

    print(f"CONCEPTOS OBSERVADOS — empresa {empresa.empresa_id} ({empresa.rfc}), {len(observados.conceptos)}")
    if not observados.conceptos:
        print("  (ninguno: esta empresa no tiene CFDI de nómina emitidos normalizados)")
    for c in observados.conceptos:
        identificador = f"{c.naturaleza}/{c.tipo}/{c.clave}" if c.clave else f"{c.naturaleza}/{c.tipo}/(sin clave)"
        print(f"\n  {identificador}  {c.concepto or ''}")
        print(f"      catálogo SAT  {catalogos.descripcion(c.naturaleza, c.tipo) or '(sin descripción)'}")
        print(f"      aparece en    {c.comprobantes} comprobante(s), {c.importe} en total")
        if c.clave is None:
            print("      categoría     NO SE PUEDE CLASIFICAR: el concepto viajó sin clave (B-02 lo señala)")
        else:
            print(f"      categoría     {c.categoria.value if c.categoria else 'SIN CLASIFICAR'}")

    print(f"\nDEPARTAMENTOS OBSERVADOS — {len(observados.departamentos)}")
    for d in observados.departamentos:
        print(f"  {d.departamento_texto}  ({d.comprobantes} comprobante(s))  -> {d.centro_costo or 'SIN MAPEAR'}")
    return 0


# --------------------------------------------------------------------------------------
# `confirmar-valor`
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Peticion:
    clave: str
    valor: Decimal
    vigencia_desde: date


def peticiones_de(crudas: Sequence[Sequence[str]]) -> list[_Peticion]:
    """Los `--valor CLAVE IMPORTE VIGENCIA_DESDE` convertidos y validados, antes de tocar la
    base. Se rechaza aquí una clave desconocida —además de en la puerta de escritura— para que
    un lote de cinco no llegue a escribir tres y morir en el cuarto."""
    peticiones: list[_Peticion] = []
    vistas: set[tuple[str, date]] = set()
    for cruda in crudas:
        clave, texto_valor, texto_fecha = cruda[0].strip(), cruda[1], cruda[2]
        if clave not in cfg.CLAVES_PARAM_FISCAL:
            raise ErrorDeUso(
                f"`{clave}` no es una clave conocida de param_fiscal. "
                f"Esperadas: {', '.join(sorted(cfg.CLAVES_PARAM_FISCAL))}."
            )
        peticion = _Peticion(
            clave=clave,
            valor=importe(texto_valor, f"el importe de {clave}"),
            vigencia_desde=_fecha(texto_fecha, f"la vigencia de {clave}"),
        )
        if (peticion.clave, peticion.vigencia_desde) in vistas:
            raise ErrorDeUso(
                f"`{clave}` desde {peticion.vigencia_desde} viene dos veces en la misma corrida. "
                "Deja uno solo: si los dos importes difieren, el segundo chocaría con el primero."
            )
        vistas.add((peticion.clave, peticion.vigencia_desde))
        peticiones.append(peticion)
    return peticiones


async def cmd_confirmar_valor(db: AsyncSession, args: argparse.Namespace) -> int:
    """Confirma uno o varios tramos. Todo el lote va en **una** transacción: confirmar tres de
    cinco valores de la UMA dejaría los informes calculando con media tabla de 2026."""
    peticiones = peticiones_de(args.valor)
    actor = await exige_actor(db, args.actor, externo=bool(args.actor_externo))

    print(f"Se van a CONFIRMAR {len(peticiones)} valor(es) fiscal(es), a nombre de {actor}:\n")
    problemas: list[str] = []
    por_hacer = 0
    for p in peticiones:
        leido = await leer_tramo(db, p.clave, p.vigencia_desde)
        if leido is None:
            problemas.append(f"{p.clave} desde {p.vigencia_desde}: no hay ningún tramo capturado con esa vigencia.")
            print(f"  {p.clave:24} {p.valor:>14}  desde {p.vigencia_desde}   NO EXISTE")
            continue
        if leido.valor != p.valor:
            problemas.append(
                f"{p.clave} desde {p.vigencia_desde}: confirmaste {p.valor} y lo almacenado es {leido.valor}."
            )
            print(f"  {p.clave:24} {p.valor:>14}  desde {p.vigencia_desde}   NO COINCIDE (hay {leido.valor})")
            continue
        estado = "ya estaba confirmado, no se tocará" if leido.confirmado else "se confirmará"
        if not leido.confirmado:
            por_hacer += 1
        print(f"  {p.clave:24} {leido.valor:>14}  desde {p.vigencia_desde}   {estado}")
        print(f"  {'':24} procedencia: {leido.origen.value} — {leido.fuente}")

    if problemas:
        print("\nNo se escribió nada. Confirmar es afirmar que revisaste esa cifra exacta:", file=sys.stderr)
        for problema in problemas:
            print(f"  - {problema}", file=sys.stderr)
        print("Vuelve a leer el estado (`estado`) y corrige lo que mandas.", file=sys.stderr)
        return 1

    if por_hacer == 0:
        print("\nTodo estaba ya confirmado. No hay nada que hacer.")
        return 0

    print("\nConfirmar ACTIVA el valor: a partir de aquí los informes calculan con él.")
    if not pregunta("¿Continuar?", si=bool(args.si)):
        print("Cancelado: no se escribió nada.")
        return 1

    try:
        for p in peticiones:
            try:
                # El vistazo de arriba es cortesía: **la guarda que decide es esta**, dentro de
                # la transacción y bajo el candado del rango de la clave. Entre que el plan se
                # imprimió y que la persona respondió pudo entrar otro escritor —una recarga de
                # semillas, la sincronización de Banxico—, y ese es justo el hueco por el que
                # existe el invariante. Sin este `except`, ese caso saldría como traza de
                # Python en vez de decir qué pasó.
                fila, cambio = await cfg.confirmar_param_fiscal(
                    db, clave=p.clave, vigencia_desde=p.vigencia_desde, valor=p.valor, actor=actor
                )
            except cfg.ErrorDeConfiguracion as exc:
                raise ErrorDeUso(
                    f"{exc}\nNo se confirmó ninguno de los {len(peticiones)} valores: el lote es todo o nada."
                ) from None
            if not cambio:
                continue
            await bitacora_service.registrar(
                db,
                actor=actor,
                accion="confirmar_param_fiscal",
                entidad=f"param_fiscal:{p.clave}@{p.vigencia_desde.isoformat()}",
                detalle=_detalle(
                    clave=p.clave,
                    anterior={"valor": str(fila.valor), "confirmado": False},
                    nuevo={"valor": str(fila.valor), "confirmado": True},
                ),
            )
        # La bitácora se escribe **dentro** de esta transacción (regla 8): si `registrar`
        # falla, el `rollback` de abajo se lleva también las confirmaciones. Un valor activado
        # sin rastro de quién lo activó es peor que un valor sin activar.
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    print(f"\nListo: {por_hacer} valor(es) confirmado(s) por {actor} desde la línea de comandos.")
    return 0


# --------------------------------------------------------------------------------------
# `capturar-valor`
# --------------------------------------------------------------------------------------


async def cmd_capturar_valor(db: AsyncSession, args: argparse.Namespace) -> int:
    """Captura o corrige un tramo a mano. Queda con `origen: MANUAL` y **sin confirmar**:
    capturar no confirma, ni siquiera cuando quien captura es quien confirmaría. Es el mismo
    reparto que la pantalla, y por el mismo motivo — fusionarlos dejaría entrar un valor
    fiscal a un cálculo sin que nadie lo mirara."""
    clave: str = args.clave.strip()
    valor = importe(args.valor, f"el importe de {clave}")
    vigencia_desde = _fecha(args.vigencia_desde, "--vigencia-desde")
    vigencia_hasta = _fecha(args.vigencia_hasta, "--vigencia-hasta") if args.vigencia_hasta else None
    actor = await exige_actor(db, args.actor, externo=bool(args.actor_externo))

    previo = await leer_tramo(db, clave, vigencia_desde)
    print(f"CAPTURAR {clave} ({_vigencia(vigencia_desde, vigencia_hasta)}), a nombre de {actor}\n")
    if previo is None:
        print("  antes    (no había ningún tramo con esa vigencia)")
    else:
        print(f"  antes    {previo.valor}   {previo.origen.value} — {previo.fuente}")
        print(f"           confirmado: {_si_no(previo.confirmado)}")
    print(f"  después  {valor}   MANUAL — {args.fuente}")
    print("           confirmado: no (capturar no confirma; se confirma aparte)")
    if previo is not None and previo.confirmado and previo.valor != valor:
        print("\n  OJO: la cifra cambia, así que la confirmación de este tramo se BORRA y el valor")
        print("  deja de calcular hasta que alguien vuelva a confirmarlo.")

    # Se pregunta solo cuando se pisa algo. Capturar un tramo nuevo no destruye nada y la
    # puerta de escritura ya rechaza lo incoherente; obligar a un `--si` ahí sería ruido que
    # enseña a teclear `--si` sin leer, que es como se gasta esta misma puerta.
    if previo is not None and not pregunta("\n¿Sobrescribir el tramo que ya existe?", si=bool(args.si)):
        print("Cancelado: no se escribió nada.")
        return 1

    try:
        # `snapshot_de_tramo` toma el candado del rango de la clave antes que
        # `guardar_param_fiscal`, sobre ese mismo rango: dos capturas simultáneas de la misma
        # clave se serializan en vez de cruzarse.
        anterior = await cfg.snapshot_de_tramo(db, clave, vigencia_desde)
        try:
            fila = await cfg.guardar_param_fiscal(
                db,
                clave=clave,
                valor=valor,
                vigencia_desde=vigencia_desde,
                vigencia_hasta=vigencia_hasta,
                origen=OrigenValor.MANUAL,
                fuente=args.fuente,
                ejercicio=int(args.ejercicio) if args.ejercicio is not None else None,
            )
        except cfg.ErrorDeConfiguracion as exc:
            raise ErrorDeUso(str(exc)) from None
        # La columna es `Numeric(18,6)`: releerla hace que lo que se imprime y lo que va a la
        # bitácora digan la cifra con la escala que quedó almacenada ("117.310000"), no la que
        # se tecleó ("117.31").
        await db.refresh(fila)
        await bitacora_service.registrar(
            db,
            actor=actor,
            accion="capturar_param_fiscal",
            entidad=f"param_fiscal:{clave}@{vigencia_desde.isoformat()}",
            detalle=_detalle(clave=clave, anterior=anterior, nuevo=cfg.detalle_de_tramo(fila)),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    print(f"\nGuardado: {clave} = {fila.valor} desde {vigencia_desde}, origen MANUAL.")
    print("PENDIENTE DE CONFIRMACIÓN: todavía no calcula. Confírmalo con `confirmar-valor`.")
    return 0


# --------------------------------------------------------------------------------------
# `confirmar-marca`
# --------------------------------------------------------------------------------------


async def cmd_confirmar_marca(db: AsyncSession, args: argparse.Namespace) -> int:
    """Confirma las marcas de un tipo de percepción.

    Dos guardas, y ninguna es decorativa:

    1. **La huella de la duda** se teclea a mano (`--huella`, o `--sin-duda` para afirmar que
       la marca revisada no tenía ninguna). No se rellena sola con lo que este mismo proceso
       acaba de leer: rellenarla convertiría "confirmo habiendo leído la advertencia" en
       "confirmo lo que sea que diga ahora", que es exactamente lo que la huella impide.
    2. **El juego de marcas** que se muestra es el que se manda a confirmar, y la puerta lo
       vuelve a leer bajo candado y lo compara. Si algo cambió entre que se imprimió y que se
       respondió, se rechaza en vez de confirmar otra cosa.
    """
    tipo: str = args.tipo.strip()
    actor = await exige_actor(db, args.actor, externo=bool(args.actor_externo))
    if args.huella is None and not args.sin_duda:
        raise ErrorDeUso(
            "Falta la guarda de la duda: pasa `--huella <sha256>` con la huella que muestra "
            "`estado --percepciones`, o `--sin-duda` para afirmar que la marca que revisaste no "
            "tenía ninguna duda declarada. No hay default: confirmar es responder por lo que se miró."
        )
    if args.huella is not None and args.sin_duda:
        raise ErrorDeUso("`--huella` y `--sin-duda` se contradicen: manda una sola.")
    huella: str | None = args.huella.strip() if args.huella is not None else None

    leida = await leer_marca(db, tipo)
    if leida is None:
        raise ErrorDeUso(
            f"No hay marcas capturadas para el tipo {tipo}. Cárgalas primero "
            "(`python -m app.scripts.cargar_configuracion_fiscal ...`) y confírmalas después."
        )
    descripcion = dict(catalogos.tipos_de("P")).get(tipo) or "(sin descripción en el catálogo instalado)"
    marcas = leida.marcas
    print(f"CONFIRMAR la marca {tipo} — {descripcion}, a nombre de {actor}\n")
    print(f"  ingreso ordinario      {_si_no(marcas.es_ingreso_ordinario)}")
    print(f"  integra SBC            {_si_no(marcas.integra_sbc)}")
    print(f"  provisionable          {_si_no(marcas.es_provisionable)}")
    print(f"  base de exención       {marcas.base_exencion.value}")
    print(f"  factor de exención     {marcas.factor_exencion if marcas.factor_exencion is not None else '—'}")
    print(f"  tope conjunto art. 93  {_si_no(marcas.sujeto_a_tope_conjunto)}")
    if leida.nota_revision:
        print(f"\n  DUDA DECLARADA: {leida.nota_revision}")
    else:
        print("\n  (sin duda declarada)")

    if leida.confirmado:
        print(f"\nYa estaba confirmada por {leida.confirmado_por}. No hay nada que hacer.")
        return 0

    print("\nConfirmar ACTIVA estas marcas: B-03 empezará a calcular exenciones con ellas.")
    if not pregunta("¿Continuar?", si=bool(args.si)):
        print("Cancelado: no se escribió nada.")
        return 1

    try:
        try:
            fila, cambio = await cfg.confirmar_marca_percepcion(
                db, tipo=tipo, marcas=marcas, nota_revision_hash=huella, actor=actor
            )
        except cfg.DudaNoVista as exc:
            raise ErrorDeUso(
                f"{exc}\nLa huella que muestra `estado --percepciones` para {tipo} es "
                f"{leida.huella}."
            ) from None
        except cfg.ErrorDeConfiguracion as exc:
            raise ErrorDeUso(str(exc)) from None
        if cambio:
            await bitacora_service.registrar(
                db,
                actor=actor,
                accion="confirmar_marca_percepcion",
                entidad=f"catalogo_percepcion_marca:{tipo}",
                detalle=_detalle(
                    tipo_percepcion=tipo,
                    anterior={**cfg.detalle_de_marcas(marcas), "confirmado": False},
                    nuevo={**cfg.detalle_de_marcas(marcas), "confirmado": True},
                ),
            )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    print(f"\nListo: marca {fila.tipo_percepcion} confirmada por {actor} desde la línea de comandos.")
    return 0


# --------------------------------------------------------------------------------------
# `configurar-empresa`
# --------------------------------------------------------------------------------------


async def cmd_configurar_empresa(db: AsyncSession, args: argparse.Namespace) -> int:
    """Zona salarial, días de aguinaldo y factor de prima vacacional de una empresa.

    **Lo que no se menciona se conserva**, al revés que el `PUT` de la pantalla, que reemplaza
    los tres. En una pantalla los tres campos están a la vista y mandarlos todos es lo que el
    usuario ve; en una terminal, `--zona-salarial ZLFN` borrando los días de aguinaldo que
    alguien capturó el mes pasado sería una pérdida silenciosa. Borrar tiene su propia bandera
    (`--sin-dias-aguinaldo`, etc.), que es lo que lo hace un acto explícito.
    """
    empresa = await _exige_empresa(db, int(args.empresa_id))
    actor = await exige_actor(db, args.actor, externo=bool(args.actor_externo))

    pedidos = (
        args.zona_salarial is not None
        or args.dias_aguinaldo is not None
        or args.factor_prima_vacacional is not None
        or args.sin_zona_salarial
        or args.sin_dias_aguinaldo
        or args.sin_factor_prima_vacacional
    )
    if not pedidos:
        raise ErrorDeUso("No pediste ningún cambio. Pasa al menos uno de los tres campos (o su `--sin-...`).")
    for pedido, borrado, nombre in (
        (args.zona_salarial, args.sin_zona_salarial, "zona-salarial"),
        (args.dias_aguinaldo, args.sin_dias_aguinaldo, "dias-aguinaldo"),
        (args.factor_prima_vacacional, args.sin_factor_prima_vacacional, "factor-prima-vacacional"),
    ):
        if pedido is not None and borrado:
            raise ErrorDeUso(f"`--{nombre}` y `--sin-{nombre}` se contradicen: manda una sola.")

    config = await db.get(ConfiguracionEmpresa, empresa.empresa_id, with_for_update=True)
    nueva_zona = config.zona_salarial if config is not None else None
    nuevos_dias = config.dias_aguinaldo if config is not None else None
    nuevo_factor = config.factor_prima_vacacional if config is not None else None
    if args.zona_salarial is not None:
        nueva_zona = _zona(args.zona_salarial)
    if args.sin_zona_salarial:
        nueva_zona = None
    if args.dias_aguinaldo is not None:
        nuevos_dias = int(args.dias_aguinaldo)
        if not 1 <= nuevos_dias <= 365:
            raise ErrorDeUso(f"`--dias-aguinaldo` tiene que estar entre 1 y 365 y llegó {nuevos_dias}.")
    if args.sin_dias_aguinaldo:
        nuevos_dias = None
    if args.factor_prima_vacacional is not None:
        nuevo_factor = importe(args.factor_prima_vacacional, "--factor-prima-vacacional")
        # `Numeric(5,4)` en la columna. Se rechaza en vez de redondear, por lo mismo que los
        # importes de `param_fiscal`: guardar una cifra distinta de la que se tecleó convierte
        # el siguiente intento de corregirla en un error inexplicable.
        exponente = nuevo_factor.as_tuple().exponent
        if not Decimal(0) < nuevo_factor <= Decimal("9.9999"):
            raise ErrorDeUso(
                f"`--factor-prima-vacacional` tiene que ser positivo y no pasar de 9.9999 "
                f"(llegó {nuevo_factor}). El mínimo legal es 0.25 (art. 80 LFT)."
            )
        if isinstance(exponente, int) and -exponente > 4:
            raise ErrorDeUso(
                f"`--factor-prima-vacacional` trae {-exponente} decimales y la columna guarda 4 "
                f"(llegó {nuevo_factor}). Recórtalo tú, para que lo guardado sea lo que tecleaste."
            )
    if args.sin_factor_prima_vacacional:
        nuevo_factor = None

    antes = cfg.detalle_de_config_empresa(config) if config is not None else None
    print(f"CONFIGURAR la empresa {empresa.empresa_id} — {empresa.nombre}, a nombre de {actor}\n")
    print(f"  {'campo':26} {'antes':>22}   después")
    for nombre, previo, nuevo in (
        ("zona salarial", antes["zona_salarial"] if antes else None, nueva_zona.value if nueva_zona else None),
        ("días de aguinaldo", antes["dias_aguinaldo"] if antes else None, nuevos_dias),
        (
            "factor prima vacacional",
            antes["factor_prima_vacacional"] if antes else None,
            str(nuevo_factor) if nuevo_factor is not None else None,
        ),
    ):
        marca = " " if str(previo) == str(nuevo) else "*"
        print(f"{marca} {nombre:26} {str(previo or 'sin configurar'):>22}   {nuevo or 'sin configurar'}")

    if nueva_zona is None and antes is not None and antes["zona_salarial"]:
        print("\n  OJO: al quitar la zona salarial, B-10 deja de poder validar el salario mínimo.")
    if not pregunta("\n¿Guardar?", si=bool(args.si)):
        print("Cancelado: no se escribió nada.")
        return 1

    try:
        if config is None:
            config = ConfiguracionEmpresa(empresa_id=empresa.empresa_id)
            db.add(config)
        config.zona_salarial = nueva_zona
        config.dias_aguinaldo = nuevos_dias
        config.factor_prima_vacacional = nuevo_factor
        await db.flush()
        await db.refresh(config)  # escala real de `Numeric(5,4)`
        await bitacora_service.registrar(
            db,
            actor=actor,
            accion="guardar_configuracion_empresa",
            entidad=f"empresa:{empresa.empresa_id}",
            detalle=_detalle(anterior=antes, nuevo=cfg.detalle_de_config_empresa(config)),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    print(f"\nListo: configuración de la empresa {empresa.empresa_id} guardada por {actor}.")
    return 0


# --------------------------------------------------------------------------------------
# `clasificar`
# --------------------------------------------------------------------------------------


async def cmd_clasificar(db: AsyncSession, args: argparse.Namespace) -> int:
    """Clasifica conceptos (categoría de provisión) y departamentos (centro de costo).

    **Por omisión mezcla, no reemplaza.** El `PUT` de la pantalla manda las dos listas
    completas porque la pantalla las tiene todas a la vista; aquí, `--concepto P/001/001
    NO_APLICA` borrando los otros veinte mapeos sería una pérdida silenciosa que se nota tres
    meses después, cuando B-08 no cuadra. `--reemplazar` es la forma explícita de pedir lo
    otro, y entonces las bajas salen enumeradas en el plan antes de aplicarse.
    """
    empresa = await _exige_empresa(db, int(args.empresa_id))
    actor = await exige_actor(db, args.actor, externo=bool(args.actor_externo))

    conceptos: dict[tuple[str, str, str], CategoriaProvision] = {}
    for cruda in args.concepto or []:
        terna = concepto_partido(cruda[0])
        if terna in conceptos:
            raise ErrorDeUso(f"`{cruda[0]}` viene dos veces en la misma corrida. Deja uno solo.")
        conceptos[terna] = _categoria(cruda[1])
    departamentos: dict[str, str] = {}
    for cruda in args.departamento or []:
        texto, centro = cruda[0].strip(), cruda[1].strip()
        if not texto or len(texto) > 100 or not centro or len(centro) > 100:
            raise ErrorDeUso(
                f"`--departamento {cruda[0]!r} {cruda[1]!r}`: los dos textos son obligatorios y no "
                "pasan de 100 caracteres."
            )
        if texto in departamentos:
            raise ErrorDeUso(f"El departamento {texto!r} viene dos veces en la misma corrida. Deja uno solo.")
        departamentos[texto] = centro
    if not conceptos and not departamentos and not args.reemplazar:
        raise ErrorDeUso("No pediste ninguna clasificación. Pasa al menos un `--concepto` o `--departamento`.")

    observados = await cfg.observados_de_empresa(db, empresa)
    texto_de = {
        (c.naturaleza, c.tipo, c.clave): (c.concepto or "") for c in observados.conceptos if c.clave is not None
    }
    depto_observado = {d.departamento_texto for d in observados.departamentos}
    if not args.permitir_no_observado:
        # La clave la inventa el sistema de nómina del patrón: un dedazo produce un mapeo que
        # no casa con nada, mientras el concepto de verdad sigue sin clasificar. Silencioso en
        # las dos puntas, igual que `150` por `015` en las marcas de percepción.
        fantasmas = [f"{n}/{t}/{c}" for (n, t, c) in conceptos if (n, t, c) not in texto_de]
        fantasmas += [f"departamento {d!r}" for d in departamentos if d not in depto_observado]
        if fantasmas:
            raise ErrorDeUso(
                "Esto no aparece en ningún CFDI de nómina de la empresa: "
                + ", ".join(fantasmas)
                + ".\nLo más probable es un dedazo en la clave; míralas con `observados --empresa-id "
                f"{empresa.empresa_id}`. Si de verdad quieres adelantarte a un concepto que todavía no "
                "se emite, pasa `--permitir-no-observado`."
            )

    previas_conceptos = await cfg.categorias_de_provision(db, empresa.empresa_id)
    previos_deptos = await cfg.centro_de_costo(db, empresa.empresa_id)
    finales_conceptos = dict(conceptos) if args.reemplazar else {**previas_conceptos, **conceptos}
    finales_deptos = dict(departamentos) if args.reemplazar else {**previos_deptos, **departamentos}

    modo = "REEMPLAZAR" if args.reemplazar else "mezclar con lo que ya hay"
    print(f"CLASIFICAR la empresa {empresa.empresa_id} — {empresa.nombre} ({modo}), a nombre de {actor}\n")
    cambios = _imprimir_plan_conceptos(previas_conceptos, finales_conceptos, texto_de)
    cambios += _imprimir_plan_departamentos(previos_deptos, finales_deptos)
    if cambios == 0:
        print("  (nada que cambiar: ya estaba todo así)")
        return 0

    if not pregunta(f"\n¿Aplicar {cambios} cambio(s)?", si=bool(args.si)):
        print("Cancelado: no se escribió nada.")
        return 1

    # Forma del `detalle` idéntica a la del endpoint (`MapeosEmpresaOut.model_dump`), para que
    # la pantalla de bitácora enseñe los dos caminos con el mismo cuadro.
    anterior = _detalle_mapeos(previas_conceptos, previos_deptos)
    try:
        await db.execute(delete(MapDepartamento).where(MapDepartamento.empresa_id == empresa.empresa_id))
        await db.execute(delete(MapConceptoProvision).where(MapConceptoProvision.empresa_id == empresa.empresa_id))
        # Orden estable de inserción por clave natural: dos corridas de la **misma** empresa
        # competirían por las mismas filas, y tomar los candados siempre en el mismo orden es
        # lo que impide el ciclo de espera (mismo argumento que el `sorted()` del cargador).
        for texto in sorted(finales_deptos):
            db.add(
                MapDepartamento(
                    empresa_id=empresa.empresa_id, departamento_texto=texto, centro_costo=finales_deptos[texto]
                )
            )
        for naturaleza, tipo, clave in sorted(finales_conceptos):
            db.add(
                MapConceptoProvision(
                    empresa_id=empresa.empresa_id,
                    naturaleza=naturaleza,
                    tipo=tipo,
                    clave=clave,
                    categoria=finales_conceptos[(naturaleza, tipo, clave)],
                )
            )
        await db.flush()
        await bitacora_service.registrar(
            db,
            actor=actor,
            accion="guardar_mapeos_empresa",
            entidad=f"empresa:{empresa.empresa_id}",
            detalle=_detalle(anterior=anterior, nuevo=_detalle_mapeos(finales_conceptos, finales_deptos)),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    print(f"\nListo: {cambios} cambio(s) aplicados por {actor} desde la línea de comandos.")
    return 0


def _imprimir_plan_conceptos(
    previas: dict[tuple[str, str, str], CategoriaProvision],
    finales: dict[tuple[str, str, str], CategoriaProvision],
    texto_de: dict[tuple[str, str, str], str],
) -> int:
    cambios = 0
    print("CONCEPTOS")
    for terna in sorted(set(previas) | set(finales)):
        identificador = "/".join(terna)
        nombre = texto_de.get(terna, "")
        antes = previas.get(terna)
        despues = finales.get(terna)
        if antes == despues:
            print(f"    {identificador:22} {nombre[:28]:28} {despues.value if despues else ''} (sin cambio)")
            continue
        cambios += 1
        if antes is None:
            print(f"  + {identificador:22} {nombre[:28]:28} -> {despues.value if despues else ''}")
        elif despues is None:
            print(f"  - {identificador:22} {nombre[:28]:28} SE BORRA (estaba {antes.value})")
        else:
            print(f"  ~ {identificador:22} {nombre[:28]:28} {antes.value} -> {despues.value}")
    return cambios


def _imprimir_plan_departamentos(previos: dict[str, str], finales: dict[str, str]) -> int:
    cambios = 0
    print("DEPARTAMENTOS")
    for texto in sorted(set(previos) | set(finales)):
        antes = previos.get(texto)
        despues = finales.get(texto)
        if antes == despues:
            print(f"    {texto[:40]:40} {despues or ''} (sin cambio)")
            continue
        cambios += 1
        if antes is None:
            print(f"  + {texto[:40]:40} -> {despues}")
        elif despues is None:
            print(f"  - {texto[:40]:40} SE BORRA (estaba {antes})")
        else:
            print(f"  ~ {texto[:40]:40} {antes} -> {despues}")
    return cambios


def _detalle_mapeos(
    conceptos: dict[tuple[str, str, str], CategoriaProvision], departamentos: dict[str, str]
) -> dict[str, Any]:
    return {
        "departamentos": [
            {"departamento_texto": texto, "centro_costo": departamentos[texto]} for texto in sorted(departamentos)
        ],
        "conceptos_provision": [
            {"naturaleza": n, "tipo": t, "clave": c, "categoria": conceptos[(n, t, c)].value}
            for (n, t, c) in sorted(conceptos)
        ],
    }


# --------------------------------------------------------------------------------------
# Línea de comandos
# --------------------------------------------------------------------------------------


def _agregar_actor(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--actor", required=True, help="Correo de quien responde por el cambio. Va a la bitácora.")
    sub.add_argument(
        "--actor-externo",
        action="store_true",
        help="Acepta un actor que no es usuario del Hub (recuperación ante desastre).",
    )
    sub.add_argument("--si", action="store_true", help="No pregunta: aplica lo que muestra el plan.")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.administrar_configuracion",
        description="Administra la configuración fiscal sin navegador. Deja bitácora con marcador de terminal.",
    )
    subs = parser.add_subparsers(dest="comando", required=True)

    estado = subs.add_parser("estado", help="Muestra toda la configuración fiscal.")
    estado.add_argument("--percepciones", action="store_true", help="Lista las 44 marcas con su huella.")
    estado.add_argument("--empresa-id", type=int, default=None, help="Agrega la configuración de esa empresa.")

    observados = subs.add_parser("observados", help="Conceptos y departamentos que la nómina emitió de verdad.")
    observados.add_argument("--empresa-id", type=int, required=True)

    confirmar = subs.add_parser("confirmar-valor", help="Confirma uno o varios valores fiscales.")
    confirmar.add_argument(
        "--valor",
        nargs=3,
        action="append",
        required=True,
        metavar=("CLAVE", "IMPORTE", "VIGENCIA_DESDE"),
        help="Repetible. El importe se manda como texto y se compara con el almacenado.",
    )
    _agregar_actor(confirmar)

    capturar = subs.add_parser("capturar-valor", help="Captura o corrige un valor a mano (queda sin confirmar).")
    capturar.add_argument("clave", help="Clave de param_fiscal, p. ej. UMA_DIARIA.")
    capturar.add_argument("--valor", required=True, help="El importe, como texto (nunca pasa por float).")
    capturar.add_argument("--vigencia-desde", required=True, metavar="AAAA-MM-DD")
    capturar.add_argument("--vigencia-hasta", default=None, metavar="AAAA-MM-DD")
    capturar.add_argument("--fuente", required=True, help="De dónde salió el valor. Sin ella no se puede revisar.")
    capturar.add_argument("--ejercicio", type=int, default=None, help="Por omisión, el año de --vigencia-desde.")
    _agregar_actor(capturar)

    marca = subs.add_parser("confirmar-marca", help="Confirma las marcas de un tipo de percepción.")
    marca.add_argument("tipo", help="Clave de c_TipoPercepcion, 3 posiciones (p. ej. 015).")
    marca.add_argument("--huella", default=None, help="La huella de la duda, tal como la muestra `estado`.")
    marca.add_argument(
        "--sin-duda", action="store_true", help="Afirma que la marca revisada no tenía duda declarada."
    )
    _agregar_actor(marca)

    empresa = subs.add_parser("configurar-empresa", help="Zona salarial, aguinaldo y prima vacacional.")
    empresa.add_argument("--empresa-id", type=int, required=True)
    empresa.add_argument("--zona-salarial", default=None, help="GENERAL o ZLFN.")
    empresa.add_argument("--dias-aguinaldo", type=int, default=None)
    empresa.add_argument("--factor-prima-vacacional", default=None, help="Como texto, p. ej. 0.25.")
    empresa.add_argument("--sin-zona-salarial", action="store_true", help="Borra la zona salarial.")
    empresa.add_argument("--sin-dias-aguinaldo", action="store_true")
    empresa.add_argument("--sin-factor-prima-vacacional", action="store_true")
    _agregar_actor(empresa)

    clasificar = subs.add_parser("clasificar", help="Categoría de provisión y centro de costo de una empresa.")
    clasificar.add_argument("--empresa-id", type=int, required=True)
    clasificar.add_argument(
        "--concepto",
        nargs=2,
        action="append",
        metavar=("NATURALEZA/TIPO/CLAVE", "CATEGORIA"),
        help="Repetible, p. ej. `--concepto P/001/019 VACACIONES`.",
    )
    clasificar.add_argument(
        "--departamento", nargs=2, action="append", metavar=("TEXTO", "CENTRO_COSTO"), help="Repetible."
    )
    clasificar.add_argument(
        "--reemplazar",
        action="store_true",
        help="Borra lo que no venga en esta corrida (como el PUT de la pantalla). Las bajas salen en el plan.",
    )
    clasificar.add_argument(
        "--permitir-no-observado",
        action="store_true",
        help="Acepta clasificar algo que no aparece en ningún CFDI de la empresa (probable dedazo).",
    )
    _agregar_actor(clasificar)

    return parser


_COMANDOS = {
    "estado": cmd_estado,
    "observados": cmd_observados,
    "confirmar-valor": cmd_confirmar_valor,
    "capturar-valor": cmd_capturar_valor,
    "confirmar-marca": cmd_confirmar_marca,
    "configurar-empresa": cmd_configurar_empresa,
    "clasificar": cmd_clasificar,
}


async def ejecutar(db: AsyncSession, args: argparse.Namespace) -> int:
    """El cuerpo de un comando sobre una sesión que le dan hecha, y **el código de salida**.

    Separado de `main` para que las pruebas puedan correrlo contra la base de pruebas sin
    tocar `SessionLocal`, y para que lo que ellas comprueban sea exactamente el número que
    ve el shell. `ErrorDeUso` sale como 1 con su mensaje y sin traza; cualquier otra excepción
    se propaga con su traza —un fallo que la persona no puede corregir tecleando mejor tiene
    que verse entero— y el intérprete sale igualmente con código distinto de cero.
    """
    try:
        return await _COMANDOS[args.comando](db, args)
    except ErrorDeUso as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1


async def _correr(args: argparse.Namespace) -> int:
    async with SessionLocal() as db:
        return await ejecutar(db, args)


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_correr(construir_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
