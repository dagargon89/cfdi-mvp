"""Lectura y escritura de la configuración fiscal (§12 del diseño, §2.12 y §3.1 del
documento fuente): resolución de un valor por su fecha de vigencia, el invariante de
confirmación, y el cargador desde YAML.

El invariante que gobierna todo este módulo: **un valor sin confirmar no calcula.**
`valor_vigente` devuelve *solo* filas con `confirmado_en` no nulo. Sembrar, cargar o
sincronizar **proponen**; solo una persona confirma. Es lo que hace segura la
sincronización automática: si una semilla o un raspador se equivocan, no corrompen ningún
cálculo. Su complemento es `valor_propuesto`, que sí devuelve lo que está esperando
confirmación *con su procedencia*, para que la ausencia sea accionable — la diferencia
entre "falta la UMA, ve a buscarla" y "la UMA 2026 está propuesta con su liga al boletín
del INEGI, confírmala".

La ausencia nunca es cero
-------------------------
Todos los resolutores devuelven `None` cuando no hay dato, jamás `Decimal("0")` ni un
default plausible. Un cero en un tope de exención produce exenciones falsas; un
`SALARIO_MINIMO_GENERAL` asumido para una empresa de la Zona Libre de la Frontera Norte
produce falsos negativos en "empleado por debajo del mínimo". `None` obliga al informe a
decir "no evalué esto y te digo por qué", que es información; un cero es una mentira.

Por qué el solapamiento de vigencias se rechaza al escribir, y no se arregla al leer
------------------------------------------------------------------------------------
Nada en el esquema impide que dos tramos de la misma clave se solapen: MySQL no tiene
restricciones de exclusión como Postgres, y una PK `(clave, vigencia_desde)` solo evita
repetir la *misma* fecha de inicio. El caso real: alguien captura el
`SALARIO_MINIMO_GENERAL` de 2027 y teclea mal el año — `vigencia_desde` 2026-06-15 en vez
de 2027-01-01, con `vigencia_hasta` nulo. Quedan dos tramos "vigentes hasta nuevo aviso"
para la misma clave y, como se resuelve por el `vigencia_desde` más reciente que no exceda
la fecha, toda nómina pagada entre el 15 de junio y el 31 de diciembre de 2026 tomaría el
valor equivocado: sin error, sin excepción y sin rastro.

Por eso `guardar_param_fiscal` —la única puerta de escritura de `param_fiscal`, la usan el
cargador y los endpoints de captura manual— **rechaza** cualquier fila que se solape con un
tramo existente de la misma clave, y en particular garantiza que a lo sumo una fila por
clave quede con `vigencia_hasta` nulo **mientras las escrituras de esa clave estén
serializadas**. Esa precisión no es retórica: un `SELECT` normal en InnoDB con REPEATABLE
READ es una lectura consistente por MVCC y no toma candado, así que dos transacciones
simultáneas leerían el mismo snapshot, ninguna vería el tramo de la otra, las dos pasarían
el chequeo y la PK tampoco las detendría porque los `vigencia_desde` difieren (basta un
doble clic en el `PUT` de la pantalla de configuración). La lectura de tramos va por eso
`FOR UPDATE`: el segundo escritor se bloquea en el gap lock del rango de la clave, relee al
desbloquearse —una lectura con candado ve la última versión confirmada, no el snapshot— y
detecta el solapamiento. Fuera de esa serialización (dos procesos escribiendo por rutas que
no pasen por esta función, o un `INSERT` a mano en la base) la garantía no existe.

**No se cierra automáticamente el tramo anterior.** Es la decisión menos cómoda y la
correcta: cerrar solo el tramo previo al insertar uno nuevo hace que el error de captura de
arriba sea *indistinguible* de la intención — el sistema aceptaría la fila con la fecha mal
tecleada, cerraría el tramo bueno el 14 de junio y decidiría por su cuenta un hecho fiscal
(que el mínimo de 2026 dejó de aplicar a media noche del 14 de junio) a partir de un dato
que nadie revisó. Es exactamente lo que el invariante de confirmación existe para evitar.
Exigir que el tramo venga cerrado cuesta un campo más en el mismo renglón del YAML —el
cargador ordena las filas por `(clave, vigencia_desde)`, así que cerrar el tramo viejo y
abrir el nuevo en una sola edición del archivo funciona— y convierte una corrupción
silenciosa en un error al cargar, que es barato.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

import yaml
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comprobante import Comprobante
from app.models.configuracion_fiscal import (
    CatalogoPercepcionMarca,
    ConfiguracionEmpresa,
    MapConceptoProvision,
    MapDepartamento,
    ParamFiscal,
    TablaVacaciones,
)
from app.models.empresa import Empresa
from app.models.enums import BaseExencion, CategoriaProvision, OrigenValor, ZonaSalarial
from app.models.nomina import NominaDeduccion, NominaOtroPago, NominaPercepcion, NominaReceptor

_E = TypeVar("_E", bound=Enum)

# Claves de `param_fiscal`, no importes: qué renglón hay que leer según la zona salarial
# configurada en la empresa. Los valores viven en la tabla (§2.12: ningún importe fiscal
# se codifica en el programa).
_CLAVE_SALARIO_MINIMO: dict[ZonaSalarial, str] = {
    ZonaSalarial.GENERAL: "SALARIO_MINIMO_GENERAL",
    ZonaSalarial.ZLFN: "SALARIO_MINIMO_ZLFN",
}

# Lista blanca de claves de `param_fiscal`. Sin ella, `clave: UMA_DIARA` carga limpio,
# alguien lo confirma de buena fe, y `valor_vigente(db, "UMA_DIARIA", ...)` devuelve `None`
# para siempre: el informe reporta "falta la UMA" mientras el valor está capturado y
# confirmado dos letras más allá. Agregar una clave nueva es agregarla aquí, a propósito.
CLAVES_PARAM_FISCAL: frozenset[str] = frozenset(
    {
        "UMA_DIARIA",
        "UMA_MENSUAL",
        "UMA_ANUAL",
        "SALARIO_MINIMO_GENERAL",
        "SALARIO_MINIMO_ZLFN",
        "TIPO_CAMBIO_USD",
    }
)

# `param_fiscal.valor` es `Numeric(18,6)`: 12 dígitos enteros y 6 decimales. Fuera de ese
# molde MySQL no guarda el número, revienta con un `DataError 1264/1406` a media escritura —
# un 500 opaco donde debía haber un mensaje que dijera qué está mal. Se comprueba aquí, en la
# puerta, para que el cargador de YAML y la captura manual reciban el mismo error.
_VALOR_MAXIMO: Decimal = Decimal(10) ** 12
_DECIMALES_MAXIMOS = 6


class ErrorDeConfiguracion(ValueError):
    """Un dato de configuración fiscal que no se puede aceptar tal como viene.

    Hereda de `ValueError` a propósito: quien carga una semilla espera un `ValueError`, y
    quien quiera distinguir el caso puede atrapar esta clase. El mensaje siempre dice qué
    archivo, qué renglón y qué campo — un fallo al cargar es barato, un cálculo incorrecto
    tres meses después no.
    """


class SolapamientoDeVigencia(ErrorDeConfiguracion):
    """Dos tramos de la misma clave que se pisan. Ver el docstring del módulo: es el error
    que el esquema de MySQL no puede impedir y que haría que un valor equivocado se
    aplicara en silencio."""


class CorreccionManualProtegida(ErrorDeConfiguracion):
    """La fila que se iba a escribir ya existe con `origen: MANUAL` y dice otra cosa.

    Solo se lanza cuando quien escribe pide expresamente `proteger_correccion_manual` (lo
    hace el cargador de semillas, no la captura manual). Es una negativa a escribir, no un
    error del dato: el cargador la traduce en un renglón omitido con su explicación.
    """


class CatalogoDelSatIlegible(ErrorDeConfiguracion):
    """No se pudo enumerar `c_TipoPercepcion` del catálogo embebido de `satcfdi`.

    Se distingue de un dato inválido porque no lo es: lo que falla es la herramienta con la
    que se iba a validar. Quien la atrape debe **negarse a escribir** (ver
    `exige_tipo_percepcion_conocido`), no dejar pasar el renglón.
    """


class NoEncontrado(ErrorDeConfiguracion):
    """Se pidió confirmar un renglón que no existe. Es un caso aparte de "el dato está mal":
    la superficie HTTP lo traduce en `404` y la línea de comandos en un mensaje que dice qué
    clave y qué vigencia buscó."""


class ValorCambio(ErrorDeConfiguracion):
    """Se confirmó un importe distinto del almacenado. Ver `confirmar_param_fiscal`."""


class DudaNoVista(ErrorDeConfiguracion):
    """Se confirmó una marca sin tener delante la duda que hoy tiene. Ver `duda_no_vista`."""


class MarcasCambiaron(ErrorDeConfiguracion):
    """Se confirmaron marcas distintas de las almacenadas. Ver `marcas_difieren`."""


def tipos_percepcion_del_sat() -> frozenset[str]:
    """Las claves de `c_TipoPercepcion` que trae la versión pinada de `satcfdi` (44 hoy).

    Import perezoso: enumerar el catálogo abre un sqlite y despickla cada renglón, y no todo
    el que importa este módulo lo necesita.

    **Sin `lru_cache` propio, a propósito.** La caché vive en un solo sitio,
    `catalogos._tipos_de_cache`, que ya memoiza el resultado y —desde la ronda 2— no memoiza
    los fallos. Poner una segunda capa aquí no ahorraría nada medible (construir un
    `frozenset` de 44 cadenas) y sí duplicaría el invariante "el fallo no se queda pegado" en
    un lugar donde la próxima persona no lo buscaría. Propaga `CatalogoIlegible`.
    """
    from app.informes import catalogos

    return frozenset(clave for clave, _ in catalogos.tipos_de_estricto("P"))


def exige_tipo_percepcion_conocido(tipo: str, contexto: str = "") -> None:
    """Rechaza un `tipo_percepcion` que no está en el catálogo del SAT.

    Es el mismo argumento que la lista blanca `CLAVES_PARAM_FISCAL`, y aquí muerde más
    fuerte: `150` en vez de `015` crea una marca huérfana que se puede confirmar sin ruido,
    mientras la `015` de verdad sigue sin confirmar y sin calcular. Silencioso en las dos
    puntas — B-03 no aplicaría la exención que sí toca, y nadie leería jamás la que se
    capturó. El conjunto es cerrado y verificado (44 claves), así que no hay motivo para
    aceptar nada fuera de él.

    Si el catálogo no se puede leer, **no se deja pasar**: lanza `CatalogoDelSatIlegible`.
    La regla de `app/informes/catalogos.py` —"un catálogo ilegible no aborta el informe"—
    es sobre resolver una *descripción* al leer; aquí el catálogo es la única defensa de una
    *escritura*, y escribir sin poder validar es justo lo que esta función existe para
    impedir.

    Ese rechazo es **transitorio**: el fallo de lectura no se memoiza (ver
    `catalogos._tipos_de_cache`), así que en cuanto el catálogo vuelva a ser legible la
    siguiente petición pasa, sin reiniciar nada.
    """
    prefijo = f"{contexto}: " if contexto else ""
    from app.informes.catalogos import CatalogoIlegible

    try:
        conocidos = tipos_percepcion_del_sat()
    except CatalogoIlegible as exc:
        raise CatalogoDelSatIlegible(
            f"{prefijo}no se pudo leer el catálogo `c_TipoPercepcion` de `satcfdi` ({exc}), así que no hay "
            f"con qué comprobar que {tipo!r} existe. No se escribe: una marca sobre un tipo inventado se "
            "confirma sin ruido y después no la lee nadie nunca. Vuelve a intentarlo."
        ) from exc
    if not conocidos:
        # El catálogo se leyó y está vacío. No debería pasar nunca, pero si pasa tampoco hay
        # con qué validar, y el criterio es el mismo: no se escribe.
        raise CatalogoDelSatIlegible(
            f"{prefijo}el catálogo `c_TipoPercepcion` de `satcfdi` se leyó pero no trae ningún tipo, así que "
            f"no hay con qué comprobar que {tipo!r} existe. No se escribe."
        )
    if tipo not in conocidos:
        raise ErrorDeConfiguracion(
            f"{prefijo}`tipo_percepcion` = {tipo!r} no existe en el catálogo `c_TipoPercepcion` del SAT "
            f"({len(conocidos)} claves en la versión instalada de `satcfdi`). Revisa los ceros a la "
            "izquierda: '015' y '150' se teclean casi igual y solo uno es un tipo de percepción."
        )


@dataclass(frozen=True)
class ValorFiscal:
    """Un valor de `param_fiscal` con su procedencia, para que la UI pueda decir de dónde
    salió y si ya lo revisó alguien."""

    valor: Decimal
    vigencia_desde: date
    origen: OrigenValor
    fuente: str
    confirmado: bool


# --------------------------------------------------------------------------------------
# Resolución por vigencia
# --------------------------------------------------------------------------------------


async def _tramo(db: AsyncSession, clave: str, en_fecha: date, *, confirmado: bool) -> ParamFiscal | None:
    """El tramo de `clave` aplicable en `en_fecha`: el `vigencia_desde` más reciente que no
    la excede y cuyo `vigencia_hasta` (nulo = hasta nuevo aviso) no la deja fuera.

    La PK `(clave, vigencia_desde)` sirve exactamente a este filtro y a este orden, así que
    no hace falta ningún índice adicional.
    """
    estado = ParamFiscal.confirmado_en.is_not(None) if confirmado else ParamFiscal.confirmado_en.is_(None)
    stmt = (
        select(ParamFiscal)
        .where(
            ParamFiscal.clave == clave,
            ParamFiscal.vigencia_desde <= en_fecha,
            or_(ParamFiscal.vigencia_hasta.is_(None), ParamFiscal.vigencia_hasta >= en_fecha),
            estado,
        )
        .order_by(ParamFiscal.vigencia_desde.desc())
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


async def valor_vigente(db: AsyncSession, clave: str, en_fecha: date) -> Decimal | None:
    """El valor **confirmado** de `clave` aplicable en `en_fecha`, o `None`.

    Nunca lanza y nunca devuelve cero por ausencia: `None` significa "no hay valor que se
    pueda usar para calcular", ya sea porque nadie lo capturó o porque nadie lo confirmó.
    Quien llama decide qué decirle al usuario (`valor_propuesto` distingue los dos casos).
    """
    fila = await _tramo(db, clave, en_fecha, confirmado=True)
    return fila.valor if fila is not None else None


async def valor_propuesto(db: AsyncSession, clave: str, en_fecha: date) -> ValorFiscal | None:
    """El valor **sin confirmar** que está esperando para `clave` en `en_fecha`, con su
    procedencia, o `None` si ni siquiera hay propuesta. Es lo que hace accionable la
    ausencia: "la UMA 2026 está propuesta, confírmala" en vez de "falta la UMA"."""
    fila = await _tramo(db, clave, en_fecha, confirmado=False)
    if fila is None:
        return None
    return ValorFiscal(
        valor=fila.valor,
        vigencia_desde=fila.vigencia_desde,
        origen=fila.origen,
        fuente=fila.fuente,
        confirmado=False,
    )


async def marcas_de_percepcion(db: AsyncSession) -> dict[str, CatalogoPercepcionMarca]:
    """Las marcas **confirmadas** del §3.1, indexadas por `tipo_percepcion` — una sola
    consulta, para que un informe que recorre miles de percepciones no haga una por renglón
    (regla 11).

    Mismo invariante que `valor_vigente`, y por una razón más fuerte: `factor_exencion`
    alimenta el cálculo de exenciones igual que la UMA, pero mientras la UMA se verifica
    contra un boletín oficial, estos factores son 44 derivaciones del art. 93 de la LISR
    hechas a mano. Un tipo que falte aquí porque nadie lo confirmó sale como bandera
    (`FALTA_CATALOGO_DE_MARCAS`), no como un cero que parecería "no tuvo ingreso ordinario".

    Al leer `factor_exencion`, ojo con la unidad: con `PORCENTAJE` va en escala 0-100, no
    como fracción. Está documentado junto a la columna en `app/models/configuracion_fiscal.py`.
    """
    filas = (await db.scalars(select(CatalogoPercepcionMarca).where(CatalogoPercepcionMarca.confirmado_en.is_not(None)))).all()
    return {fila.tipo_percepcion: fila for fila in filas}


async def marcas_propuestas(db: AsyncSession) -> dict[str, CatalogoPercepcionMarca]:
    """Las marcas cargadas que **esperan confirmación**, para que la ausencia sea accionable:
    "el tipo 022 está propuesto con base UMA_DIAS y factor 90, revísalo" en vez de "falta el
    catálogo de marcas"."""
    filas = (await db.scalars(select(CatalogoPercepcionMarca).where(CatalogoPercepcionMarca.confirmado_en.is_(None)))).all()
    return {fila.tipo_percepcion: fila for fila in filas}


async def centro_de_costo(db: AsyncSession, empresa_id: int) -> dict[str, str]:
    """Departamento (texto libre de la nómina) -> centro de costo, para una empresa."""
    filas = (
        await db.execute(
            select(MapDepartamento.departamento_texto, MapDepartamento.centro_costo).where(
                MapDepartamento.empresa_id == empresa_id
            )
        )
    ).all()
    return {texto: centro for texto, centro in filas}


async def categorias_de_provision(db: AsyncSession, empresa_id: int) -> dict[tuple[str, str, str], CategoriaProvision]:
    """`(naturaleza, tipo, clave)` -> categoría de provisión contable, para una empresa."""
    filas = (
        await db.execute(
            select(
                MapConceptoProvision.naturaleza,
                MapConceptoProvision.tipo,
                MapConceptoProvision.clave,
                MapConceptoProvision.categoria,
            ).where(MapConceptoProvision.empresa_id == empresa_id)
        )
    ).all()
    return {(naturaleza, tipo, clave): categoria for naturaleza, tipo, clave, categoria in filas}


# --------------------------------------------------------------------------------------
# Lo que la nómina emitió de verdad: configurar es reconocer y elegir, no teclear
# --------------------------------------------------------------------------------------

# Las tres tablas de conceptos del complemento de Nómina, con su naturaleza y las columnas
# que cambian de nombre en cada una. `otro_pago` no lleva gravado/exento: su importe es uno
# solo. Tenerlas en una tabla evita escribir la misma consulta tres veces con un nombre
# distinto y que las tres se separen a la primera corrección.
_TABLAS_DE_CONCEPTO: tuple[tuple[str, Any, Any, Any], ...] = (
    (
        "P",
        NominaPercepcion,
        NominaPercepcion.tipo_percepcion,
        NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento,
    ),
    ("D", NominaDeduccion, NominaDeduccion.tipo_deduccion, NominaDeduccion.importe),
    ("O", NominaOtroPago, NominaOtroPago.tipo_otro_pago, NominaOtroPago.importe),
)


@dataclass(frozen=True)
class ConceptoObservado:
    """Un concepto de nómina que la empresa **realmente emitió**, con lo que hace falta para
    reconocerlo sin conocer su clave.

    `clave` es la clave interna del sistema de nómina del patrón y puede venir nula: el
    complemento no la exige. Un concepto sin clave no se puede clasificar
    (`map_concepto_provision` la lleva en la PK), así que se muestra para que se vea el hueco,
    pero no se puede clasificar.
    """

    naturaleza: str
    tipo: str
    clave: str | None
    concepto: str | None
    comprobantes: int
    importe: Decimal
    categoria: CategoriaProvision | None


@dataclass(frozen=True)
class DepartamentoObservado:
    departamento_texto: str
    comprobantes: int
    centro_costo: str | None


@dataclass(frozen=True)
class Observados:
    conceptos: list[ConceptoObservado]
    departamentos: list[DepartamentoObservado]


async def observados_de_empresa(db: AsyncSession, empresa: Empresa) -> Observados:
    """Los conceptos y departamentos que **aparecen de verdad** en los CFDI de nómina de la
    empresa, con la categoría o el centro de costo que ya tengan.

    Existe porque pedirle al usuario que teclee `P/002/047` era pedirle un dato que no tiene:
    esas claves las inventa el sistema de nómina del patrón y nadie las conoce de memoria. Con
    esta lista se enumera lo que la nómina emitió, la persona **reconoce la descripción**
    —"Aguinaldo", "Prima vacacional"— y elige categoría; nunca teclea una clave. Es también la
    única forma de saber si la clasificación está **completa**, que es la condición que B-08
    necesita para distinguir "no se pagó aguinaldo" de "sí se pagó y no sé en cuál concepto".

    **Sin filtro de fecha ni de estatus, a propósito.** No es un informe: es el inventario de
    lo que hay que configurar, y un concepto que solo apareció en una nómina de hace dos años
    o en un CFDI cancelado sigue necesitando categoría — si no, la clasificación nunca queda
    completa y B-08 nunca se genera.

    Cuatro consultas agregadas en total (una por naturaleza más la de departamentos), todas
    con `GROUP BY` en la base: ni una por renglón (regla 11). Vive aquí y no en la superficie
    HTTP porque la pantalla y `app/scripts/administrar_configuracion.py` tienen que enumerar
    **lo mismo**: dos copias de esta consulta se separarían y la lista del script mostraría un
    inventario distinto del que dice si la clasificación está completa.
    """
    categorias = await categorias_de_provision(db, empresa.empresa_id)
    centros = await centro_de_costo(db, empresa.empresa_id)

    conceptos: list[ConceptoObservado] = []
    for naturaleza, modelo, columna_tipo, columna_importe in _TABLAS_DE_CONCEPTO:
        filas = (
            await db.execute(
                select(
                    columna_tipo,
                    modelo.clave,
                    # El patrón puede haber usado varios textos para la misma clave; se muestra
                    # uno. B-02 ya emite `CONCEPTO_INCONSISTENTE` para ese caso, así que aquí
                    # repetir el diagnóstico solo duplicaría la fuente de verdad.
                    func.min(modelo.concepto),
                    func.count(func.distinct(Comprobante.comprobante_id)),
                    func.coalesce(func.sum(columna_importe), 0),
                )
                .join(Comprobante, Comprobante.comprobante_id == modelo.comprobante_id)
                .where(
                    Comprobante.empresa_id == empresa.empresa_id,
                    # La empresa es el patrón (§11 del diseño): los conceptos que hay que
                    # clasificar son los que ella emitió, no los de una nómina recibida.
                    Comprobante.rfc_emisor == empresa.rfc,
                    Comprobante.tipo_comprobante == "N",
                )
                .group_by(columna_tipo, modelo.clave)
                .order_by(columna_tipo, modelo.clave)
            )
        ).all()
        for tipo, clave, concepto, comprobantes, importe in filas:
            conceptos.append(
                ConceptoObservado(
                    naturaleza=naturaleza,
                    tipo=tipo,
                    clave=clave,
                    concepto=concepto,
                    comprobantes=comprobantes,
                    importe=importe if isinstance(importe, Decimal) else Decimal(str(importe)),
                    categoria=categorias.get((naturaleza, tipo, clave)) if clave is not None else None,
                )
            )

    filas_depto = (
        await db.execute(
            select(
                NominaReceptor.departamento,
                func.count(func.distinct(Comprobante.comprobante_id)),
            )
            .join(Comprobante, Comprobante.comprobante_id == NominaReceptor.comprobante_id)
            .where(
                Comprobante.empresa_id == empresa.empresa_id,
                Comprobante.rfc_emisor == empresa.rfc,
                Comprobante.tipo_comprobante == "N",
                # Un departamento nulo no se puede mapear (`departamento_texto` va en la PK de
                # `map_departamento`), así que listarlo solo agregaría un renglón inaccionable.
                # B-06 lo trata aparte con su propia bandera.
                NominaReceptor.departamento.is_not(None),
            )
            .group_by(NominaReceptor.departamento)
            .order_by(NominaReceptor.departamento)
        )
    ).all()
    return Observados(
        conceptos=conceptos,
        departamentos=[
            DepartamentoObservado(departamento_texto=texto, comprobantes=cuenta, centro_costo=centros.get(texto))
            for texto, cuenta in filas_depto
        ],
    )


async def dias_de_vacaciones(db: AsyncSession, anios: int) -> int | None:
    """Días de vacaciones que corresponden a `anios` de antigüedad (art. 76 LFT).

    Toma el renglón con el mayor `anios_antiguedad` que no exceda `anios`, no el renglón
    exacto: después del quinto año la tabla crece cada cinco, así que con 7 años de
    antigüedad no hay renglón propio y aplica el de 5. `None` si no hay renglón aplicable
    (p. ej. con menos de un año cumplido, donde el derecho se calcula proporcional y no
    sale de esta tabla).
    """
    stmt = (
        select(TablaVacaciones.dias)
        .where(TablaVacaciones.anios_antiguedad <= anios)
        .order_by(TablaVacaciones.anios_antiguedad.desc())
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


async def configuracion_de_empresa(db: AsyncSession, empresa_id: int) -> ConfiguracionEmpresa | None:
    """La política laboral configurada de una empresa, o `None` si nunca se capturó."""
    return await db.get(ConfiguracionEmpresa, empresa_id)


async def salario_minimo_de_empresa(db: AsyncSession, empresa_id: int, en_fecha: date) -> Decimal | None:
    """El salario mínimo aplicable a la empresa en esa fecha, resolviendo en dos pasos:
    primero la zona configurada, después la clave que le corresponde.

    Devuelve `None` —**sin mirar los valores**— cuando la zona no está configurada: no hay
    default. Ciudad Juárez está en la ZLFN, donde el mínimo es muy superior al general;
    asumir "GENERAL" convertiría a todos los empleados de una empresa fronteriza en
    "cumple" cuando quizá no cumplen. B-10 traduce ese `None` en "no evalué esta validación
    y te digo por qué". También devuelve `None` si el valor de la zona no está confirmado.
    """
    config = await configuracion_de_empresa(db, empresa_id)
    if config is None or config.zona_salarial is None:
        return None
    return await valor_vigente(db, _CLAVE_SALARIO_MINIMO[config.zona_salarial], en_fecha)


# --------------------------------------------------------------------------------------
# Escritura de `param_fiscal`: la puerta única, con el rechazo de solapamientos
# --------------------------------------------------------------------------------------


def _se_solapan(desde_a: date, hasta_a: date | None, desde_b: date, hasta_b: date | None) -> bool:
    """Dos intervalos cerrados por ambos extremos (con `None` = infinito) que comparten al
    menos un día."""
    return (hasta_b is None or desde_a <= hasta_b) and (hasta_a is None or desde_b <= hasta_a)


async def guardar_param_fiscal(
    db: AsyncSession,
    *,
    clave: str,
    valor: Decimal,
    vigencia_desde: date,
    vigencia_hasta: date | None = None,
    origen: OrigenValor,
    fuente: str,
    ejercicio: int | None = None,
    contexto: str = "",
    proteger_correccion_manual: bool = False,
) -> ParamFiscal:
    """Inserta o actualiza un tramo de `param_fiscal`. **Nunca** escribe `confirmado_por`
    ni `confirmado_en`: confirmar es un acto humano y tiene su propia ruta.

    Es la única puerta de escritura de la tabla —la usan el cargador de YAML y la captura
    manual— porque es donde viven las reglas que el esquema no puede sostener:

    1. **Ningún solapamiento con otro tramo de la misma clave** (ver el docstring del
       módulo). Como consecuencia, a lo sumo una fila por clave queda con `vigencia_hasta`
       nulo *mientras las escrituras de esa clave estén serializadas* — de eso se encarga
       el `FOR UPDATE` de la lectura de tramos. No se cierra el tramo anterior por cuenta
       propia.
    2. **Si la cifra cambia, la confirmación anterior se limpia.** Un valor distinto es un
       valor nuevo y necesita confirmación nueva; si no, corregir una cifra en el YAML la
       activaría sin que nadie la mirara. Cambiar solo la fuente o la vigencia no tira la
       confirmación: la cifra revisada sigue siendo la misma.
    3. **La clave tiene que estar en `CLAVES_PARAM_FISCAL`.** Una clave inventada se
       captura, se confirma y no la lee nadie nunca.

    Con `proteger_correccion_manual` (lo pide el cargador de semillas, no la captura
    manual) lanza `CorreccionManualProtegida` en vez de pisar una fila que ya tiene
    `origen: MANUAL` y dice algo distinto.

    `contexto` es un prefijo para los mensajes de error (p. ej. "param.yaml, param_fiscal[2]").
    """
    prefijo = f"{contexto}: " if contexto else ""
    if clave not in CLAVES_PARAM_FISCAL:
        raise ErrorDeConfiguracion(
            f"{prefijo}`clave` = {clave!r} no es una clave conocida de param_fiscal. "
            f"Esperadas: {', '.join(sorted(CLAVES_PARAM_FISCAL))}. Una clave con una letra de más se "
            "captura y se confirma sin problema, y después nadie la lee jamás."
        )
    if valor <= 0:
        raise ErrorDeConfiguracion(
            f"{prefijo}`valor` debe ser positivo (llegó {valor}). Un cero o un negativo en un tope de "
            "exención o en un salario mínimo produce cálculos falsos sin que nadie los note."
        )
    if valor >= _VALOR_MAXIMO:
        raise ErrorDeConfiguracion(
            f"{prefijo}`valor` no cabe en la columna (llegó {valor}; el máximo son 12 dígitos enteros). "
            "Sin este rechazo MySQL revienta a media escritura con un error que no dice qué renglón fue."
        )
    exponente = valor.as_tuple().exponent
    if isinstance(exponente, int) and -exponente > _DECIMALES_MAXIMOS:
        # Rechazar y no redondear. La columna guarda 6 decimales, así que un valor con más se
        # almacenaría *distinto del que la persona revisó* — y entonces su siguiente intento de
        # confirmarlo chocaría con un 409 "el valor cambió" que no podría explicarse, porque el
        # que cambió fue el sistema. Ningún valor fiscal real (UMA, salario mínimo, tipo de
        # cambio) pasa de 4 decimales: el límite no aprieta a nadie y cierra el hueco.
        raise ErrorDeConfiguracion(
            f"{prefijo}`valor` trae {-exponente} decimales y la columna guarda {_DECIMALES_MAXIMOS} "
            f"(llegó {valor}). Redondearlo en silencio guardaría una cifra distinta de la que revisaste; "
            "recórtalo tú a 6 decimales para que lo confirmado sea exactamente lo que miraste."
        )
    if not fuente.strip():
        raise ErrorDeConfiguracion(
            f"{prefijo}`fuente` no puede ir vacía: sin ella nadie puede revisar de dónde salió el valor."
        )
    if vigencia_hasta is not None and vigencia_hasta < vigencia_desde:
        raise ErrorDeConfiguracion(
            f"{prefijo}`vigencia_hasta` ({vigencia_hasta}) es anterior a `vigencia_desde` ({vigencia_desde})."
        )

    # `with_for_update()` no es una optimización: sin él esta lectura es un snapshot MVCC
    # que no toma candado, dos escritores simultáneos de la misma clave no se ven y los dos
    # pasan el chequeo de solapamiento (verificado: dos tramos abiertos). Con él, el segundo
    # espera en el gap lock del rango de la clave y relee la última versión confirmada.
    # El orden de adquisición es una clave por llamada, y el cargador escribe sus claves
    # ordenadas alfabéticamente (ver `cargar_desde_yaml`): dos cargas concurrentes toman los
    # candados de `param_fiscal` en el mismo orden, así que entre ellos no hay ciclo de
    # espera posible. **La garantía se limita a esta tabla:** los bucles de
    # `catalogo_percepcion_marca` y `tabla_vacaciones` recorren los renglones en el orden del
    # archivo, no ordenados, así que dos cargas simultáneas de archivos con los mismos tipos
    # en distinto orden sí podrían interbloquearse. El riesgo práctico es bajo (cargar
    # semillas es una operación manual y poco frecuente) y por eso no se ordena también ahí,
    # pero la afirmación no debe leerse como global.
    tramos = list(
        (await db.scalars(select(ParamFiscal).where(ParamFiscal.clave == clave).with_for_update())).all()
    )
    if proteger_correccion_manual:
        previa = next((t for t in tramos if t.vigencia_desde == vigencia_desde), None)
        ejercicio_efectivo = ejercicio if ejercicio is not None else vigencia_desde.year
        if previa is not None and previa.origen is OrigenValor.MANUAL and (
            previa.valor != valor
            or previa.vigencia_hasta != vigencia_hasta
            or previa.fuente != fuente
            or previa.ejercicio != ejercicio_efectivo
        ):
            raise CorreccionManualProtegida(
                f"`{clave}` desde {vigencia_desde} fue corregida a mano (valor {previa.valor}, "
                f"fuente {previa.fuente!r}) y la semilla dice otra cosa (valor {valor}, fuente {fuente!r})."
            )

    for otro in tramos:
        if otro.vigencia_desde == vigencia_desde:
            continue  # es la misma fila: se está actualizando, no agregando otro tramo
        if _se_solapan(vigencia_desde, vigencia_hasta, otro.vigencia_desde, otro.vigencia_hasta):
            raise SolapamientoDeVigencia(
                f"{prefijo}el tramo {vigencia_desde}..{vigencia_hasta or 'nuevo aviso'} de `{clave}` se "
                f"solapa con el que ya existe ({otro.vigencia_desde}..{otro.vigencia_hasta or 'nuevo aviso'}, "
                f"valor {otro.valor}). Cierra el tramo anterior poniéndole `vigencia_hasta` el día previo, "
                "o corrige la fecha si tecleaste mal el año: dos tramos vigentes a la vez harían que el "
                "valor equivocado se usara en silencio."
            )

    fila = next((t for t in tramos if t.vigencia_desde == vigencia_desde), None)
    if fila is None:
        fila = ParamFiscal(
            clave=clave,
            vigencia_desde=vigencia_desde,
            ejercicio=ejercicio if ejercicio is not None else vigencia_desde.year,
            valor=valor,
            vigencia_hasta=vigencia_hasta,
            origen=origen,
            fuente=fuente,
        )
        db.add(fila)
    else:
        if fila.valor != valor:
            fila.valor = valor
            fila.confirmado_por = None
            fila.confirmado_en = None
        fila.ejercicio = ejercicio if ejercicio is not None else vigencia_desde.year
        fila.vigencia_hasta = vigencia_hasta
        fila.fuente = fuente
        # Llegar aquí protegiendo y con `origen: MANUAL` significa que la semilla dice
        # exactamente lo mismo que la corrección a mano: no hay nada que escribir, y
        # degradar el origen a SEMILLA borraría el rastro de quién revisó ese renglón.
        if not (proteger_correccion_manual and fila.origen is OrigenValor.MANUAL):
            fila.origen = origen
    await db.flush()
    return fila


# --------------------------------------------------------------------------------------
# Confirmación: la puerta que activa un valor fiscal
# --------------------------------------------------------------------------------------
#
# Vive aquí, y no en `app/api/v1/configuracion.py`, por el mismo argumento que
# `guardar_param_fiscal`: hay **dos** clientes que confirman —la pantalla y
# `app/scripts/administrar_configuracion.py`— y una segunda copia de estas guardas en el
# script sería una puerta trasera con la forma exacta de la puerta buena. Las funciones no
# escriben bitácora ni hacen `commit`: eso lo hace quien llama, en la misma transacción, y es
# lo que le permite a cada cliente dejar constancia de *por dónde* entró.

# `param_fiscal.confirmado_por` y `catalogo_percepcion_marca.confirmado_por` son VARCHAR(128)
# y `usuarios.correo` es VARCHAR(190). El recorte evita un DataError 1406 de MySQL a media
# escritura y no pierde nada auditable: la fila de bitácora de la misma transacción guarda el
# `actor` completo (VARCHAR(190)).
_LARGO_CONFIRMADO_POR = 128


def _ahora() -> datetime:
    """`datetime` sin zona, como todas las columnas `DateTime` del proyecto (que son naive en
    UTC). Mismo patrón que `app/worker/tasks.py`."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def huella_de_nota(nota: str | None) -> str | None:
    """Huella de una duda declarada, para que confirmar pueda exigir **haberla visto**.

    SHA-256 del texto en UTF-8, o `None` si no hay duda. Es un valor **opaco**: lo emite quien
    lista las marcas (el `GET` de la API, o el `estado` de la línea de comandos) y el cliente
    lo devuelve tal cual al confirmar. Nadie fuera de este módulo tiene que saber qué algoritmo
    es, y ese es el punto — si el cliente lo calculara, tendría que reproducir la normalización
    byte a byte y cualquier diferencia sería un rechazo que no se podría explicar.

    Se hashea el texto **ya normalizado** tal como está en la base (`_normaliza_nota` en el
    `PUT` y `_texto` en el cargador ya recortan espacios y convierten el vacío en `None`), así
    que la misma duda siempre produce la misma huella.
    """
    if nota is None:
        return None
    return hashlib.sha256(nota.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MarcasQueCalculan:
    """Las seis marcas del §3.1 que **calculan**: lo que se revisa y lo que se confirma.

    Es la forma que entienden las guardas, independiente de Pydantic y de argparse, para que
    la pantalla y la línea de comandos comparen contra lo mismo. `nota_revision` no está: no
    entra en la comparación (ver `marcas_difieren`) y su guarda propia es la huella.
    """

    es_ingreso_ordinario: bool
    base_exencion: BaseExencion
    factor_exencion: Decimal | None
    integra_sbc: bool
    es_provisionable: bool
    sujeto_a_tope_conjunto: bool

    @classmethod
    def de_fila(cls, fila: CatalogoPercepcionMarca) -> MarcasQueCalculan:
        return cls(
            es_ingreso_ordinario=fila.es_ingreso_ordinario,
            base_exencion=fila.base_exencion,
            factor_exencion=fila.factor_exencion,
            integra_sbc=fila.integra_sbc,
            es_provisionable=fila.es_provisionable,
            sujeto_a_tope_conjunto=fila.sujeto_a_tope_conjunto,
        )


def marcas_difieren(fila: CatalogoPercepcionMarca, marcas: MarcasQueCalculan) -> bool:
    """Si las marcas que **calculan** cambiaron. Decide dos cosas: si la captura tiene que
    limpiar la confirmación, y si el confirmar se rechaza.

    `nota_revision` queda fuera de **esta** comparación, y por dos razones distintas según
    para qué se use la función:

    - Para el rechazo al confirmar: lo que se confirma no lleva la nota. Obligar a reenviar
      verbatim un texto de 800 caracteres solo añadiría un rechazo por una diferencia de
      espacios en prosa — el mismo fallo inexplicable que evitamos al rechazar el redondeo
      silencioso. Que la duda se vea al confirmar lo garantiza la huella.
    - Para limpiar la confirmación al capturar: la nota sí cuenta, pero **asimétricamente**, y
      eso no cabe en una comparación de igualdad. Va aparte, en `_duda_nueva`.
    """
    return (
        fila.es_ingreso_ordinario != marcas.es_ingreso_ordinario
        or fila.base_exencion is not marcas.base_exencion
        or fila.factor_exencion != marcas.factor_exencion
        or fila.integra_sbc != marcas.integra_sbc
        or fila.es_provisionable != marcas.es_provisionable
        # Sin este renglón, confirmar una marca de previsión social con un cuerpo que no
        # menciona el tope pasaría y activaría una bandera que nadie miró.
        or fila.sujeto_a_tope_conjunto != marcas.sujeto_a_tope_conjunto
    )


def duda_no_vista(fila: CatalogoPercepcionMarca, huella_enviada: str | None) -> bool:
    """Si quien confirma **no tenía delante la duda que la marca tiene ahora**.

    Es el hueco que `marcas_difieren` deja abierto a propósito, en su forma concurrente: A abre
    `001` sin duda, B le agrega una (o la agrega una recarga de semilla), A confirma → las seis
    marcas no cambiaron → pasa, confirmado, con una duda que nunca vio. Justo lo que la puerta
    de confirmación existe para impedir.

    **Se compara la huella y no el texto.** La razón por la que `marcas_difieren` excluye
    `nota_revision` sigue siendo buena y no cambia: obligar a reenviar 800 caracteres de prosa
    verbatim produciría un rechazo por un espacio en blanco. La huella conserva la garantía sin
    esa fragilidad.

    **Asimétrica, exactamente como `_duda_nueva`, y por el mismo argumento:**

    - la marca tiene duda ahora y la huella no coincide (o no vino) → se rechaza: se estaría
      confirmando sin haber visto la advertencia vigente;
    - la marca **no** tiene duda ahora → pasa, venga la huella que venga. Quien revisó lo hizo
      con una duda que desde entonces alguien resolvió, es decir contra *más* información de la
      que hay hoy. Resolver una duda no invalida una revisión; que aparezca una, sí.
    """
    if fila.nota_revision is None:
        return False
    return huella_enviada != huella_de_nota(fila.nota_revision)


def detalle_de_tramo(fila: ParamFiscal) -> dict[str, Any]:
    """El tramo en tipos que el `JSON` de `bitacora` sabe guardar. El `Decimal` va como texto:
    serializarlo a `float` en el rastro de auditoría perdería precisión justo en el dato que se
    está auditando."""
    return {
        "valor": str(fila.valor),
        "ejercicio": fila.ejercicio,
        "vigencia_hasta": fila.vigencia_hasta.isoformat() if fila.vigencia_hasta else None,
        "origen": fila.origen.value,
        "fuente": fila.fuente,
        "confirmado": fila.confirmado_en is not None,
    }


def detalle_de_marcas(marcas: MarcasQueCalculan) -> dict[str, Any]:
    """Las seis marcas para el `detalle` de bitácora, con el `Decimal` como texto."""
    return {
        "es_ingreso_ordinario": marcas.es_ingreso_ordinario,
        "base_exencion": marcas.base_exencion.value,
        "factor_exencion": str(marcas.factor_exencion) if marcas.factor_exencion is not None else None,
        "integra_sbc": marcas.integra_sbc,
        "es_provisionable": marcas.es_provisionable,
        "sujeto_a_tope_conjunto": marcas.sujeto_a_tope_conjunto,
    }


def detalle_de_config_empresa(config: ConfiguracionEmpresa) -> dict[str, Any]:
    """La política laboral de una empresa para el `detalle` de bitácora."""
    return {
        "zona_salarial": config.zona_salarial.value if config.zona_salarial else None,
        "dias_aguinaldo": config.dias_aguinaldo,
        "factor_prima_vacacional": (
            str(config.factor_prima_vacacional) if config.factor_prima_vacacional is not None else None
        ),
    }


async def snapshot_de_tramo(db: AsyncSession, clave: str, vigencia_desde: date) -> dict[str, Any] | None:
    """El contenido del tramo **antes** de escribirlo, para el `detalle` de la bitácora.

    Dos decisiones que parecen detalle y no lo son:

    1. **Selecciona columnas, no la entidad.** Cargar el `ParamFiscal` por el ORM lo metería
       en el mapa de identidad, y la lectura `FOR UPDATE` de `guardar_param_fiscal` devolvería
       *ese mismo objeto* sin refrescar sus atributos (SQLAlchemy no pisa lo ya cargado salvo
       con `populate_existing()`): el candado seguiría tomándose, pero la comprobación de
       solapamiento razonaría sobre el snapshot viejo. Una fila de columnas no toca el mapa de
       identidad.
    2. **Toma el candado sobre el mismo rango** que `guardar_param_fiscal` (`clave = ...`), no
       sobre la fila exacta. Un rango más angosto aquí y uno más ancho después abriría un ciclo
       de espera entre dos escrituras de la misma clave con `vigencia_desde` distintos; con el
       mismo rango, la segunda simplemente espera a la primera.
    """
    fila = (
        await db.execute(
            select(
                ParamFiscal.vigencia_desde,
                ParamFiscal.ejercicio,
                ParamFiscal.valor,
                ParamFiscal.vigencia_hasta,
                ParamFiscal.origen,
                ParamFiscal.fuente,
                ParamFiscal.confirmado_en,
            )
            .where(ParamFiscal.clave == clave)
            .with_for_update()
        )
    ).all()
    previa = next((f for f in fila if f.vigencia_desde == vigencia_desde), None)
    if previa is None:
        return None
    return {
        "valor": str(previa.valor),
        "ejercicio": previa.ejercicio,
        "vigencia_hasta": previa.vigencia_hasta.isoformat() if previa.vigencia_hasta else None,
        "origen": previa.origen.value,
        "fuente": previa.fuente,
        "confirmado": previa.confirmado_en is not None,
    }


async def confirmar_param_fiscal(
    db: AsyncSession, *, clave: str, vigencia_desde: date, valor: Decimal, actor: str
) -> tuple[ParamFiscal, bool]:
    """Confirma un tramo propuesto: a partir de aquí `valor_vigente` lo devuelve y los informes
    calculan con él. Devuelve la fila y **si cambió algo** (falso al reconfirmar lo ya
    confirmado, que es idempotente y no merece renglón de bitácora).

    **Exige `valor`, el importe que se está confirmando, y rechaza si no coincide con el
    almacenado.** Sin esa comparación, una propuesta que cambió entre que se leyó y que se
    confirmó —una recarga de semillas, otro administrador, la sincronización de Banxico— se
    confirmaría a ciegas, que es justo el escenario contra el que existe el invariante.

    El `FOR UPDATE` toma el mismo rango por clave que `guardar_param_fiscal`, así que una
    captura simultánea de la misma clave espera en vez de colarse entre la comparación del
    valor y la escritura de la confirmación.

    No escribe bitácora ni hace `commit`: quien llama lo hace en la misma transacción.
    """
    tramos = list((await db.scalars(select(ParamFiscal).where(ParamFiscal.clave == clave).with_for_update())).all())
    fila = next((t for t in tramos if t.vigencia_desde == vigencia_desde), None)
    if fila is None:
        raise NoEncontrado(f"No hay ningún tramo de `{clave}` que arranque el {vigencia_desde}.")

    if fila.valor != valor:
        # `Decimal("117.31") == Decimal("117.310000")` es verdadero: la comparación es por
        # valor numérico, no por escala, así que quien confirma no tiene que adivinar los
        # decimales con los que la columna `Numeric(18,6)` devolvió la cifra.
        raise ValorCambio(
            f"El valor de `{clave}` cambió mientras revisabas: está en {fila.valor} y confirmaste "
            f"{valor}. Vuelve a leer el estado y revísalo otra vez antes de confirmar."
        )

    if fila.confirmado_en is not None:
        # Idempotente: reconfirmar lo ya confirmado no cambia nada, así que tampoco reescribe
        # quién lo confirmó (sería borrar el rastro del que sí lo revisó).
        return fila, False

    fila.confirmado_por = actor[:_LARGO_CONFIRMADO_POR]
    fila.confirmado_en = _ahora()
    await db.flush()
    return fila, True


async def confirmar_marca_percepcion(
    db: AsyncSession,
    *,
    tipo: str,
    marcas: MarcasQueCalculan,
    nota_revision_hash: str | None,
    actor: str,
) -> tuple[CatalogoPercepcionMarca, bool]:
    """Confirma las marcas de un tipo de percepción: a partir de aquí `marcas_de_percepcion`
    las devuelve y los informes calculan exenciones con ellas. Devuelve la fila y si cambió algo.

    Pide el juego completo de marcas —no solo el tipo— por la misma razón que los importes: lo
    que se confirma es *lo que se revisó*, y si cambió entre la lectura y el acto, se rechaza.
    Y pide la **huella** de la duda: confirmar no es editar, pero sí es afirmar que se miró lo
    que se activa, y la duda es parte de eso (ver `duda_no_vista`).

    No escribe bitácora ni hace `commit`: quien llama lo hace en la misma transacción.
    """
    exige_tipo_percepcion_conocido(tipo)
    fila = await db.get(CatalogoPercepcionMarca, tipo, with_for_update=True)
    if fila is None:
        raise NoEncontrado(f"No hay marcas capturadas para el tipo de percepción {tipo}.")
    # Antes que `marcas_difieren`: si apareció una duda, ese es el diagnóstico útil aunque
    # además hayan cambiado las marcas — "mira la advertencia nueva" dice más que "algo cambió".
    if duda_no_vista(fila, nota_revision_hash):
        raise DudaNoVista(
            f"El tipo {tipo} tiene una duda declarada que no estaba a la vista cuando lo revisaste "
            "(la agregó otra persona o una recarga de semillas). Vuelve a leer el estado, lee la "
            "duda y confirma después: confirmar es responder por lo que se miró."
        )
    if marcas_difieren(fila, marcas):
        raise MarcasCambiaron(
            f"Las marcas del tipo {tipo} cambiaron mientras las revisabas. Vuelve a leer el estado "
            "y revísalas otra vez antes de confirmarlas."
        )
    if fila.confirmado_en is not None:
        return fila, False

    fila.confirmado_por = actor[:_LARGO_CONFIRMADO_POR]
    fila.confirmado_en = _ahora()
    await db.flush()
    return fila, True


# --------------------------------------------------------------------------------------
# Cargador desde YAML
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _FilaParam:
    ejercicio: int | None
    clave: str
    valor: Decimal
    vigencia_desde: date
    vigencia_hasta: date | None
    fuente: str
    contexto: str


@dataclass(frozen=True)
class _FilaMarca:
    tipo_percepcion: str
    es_ingreso_ordinario: bool
    base_exencion: BaseExencion
    factor_exencion: Decimal | None
    integra_sbc: bool
    es_provisionable: bool
    sujeto_a_tope_conjunto: bool
    nota_revision: str | None


@dataclass(frozen=True)
class _FilaVacaciones:
    anios_antiguedad: int
    dias: int


@dataclass(frozen=True)
class _FilaDepartamento:
    departamento_texto: str
    centro_costo: str


@dataclass(frozen=True)
class _FilaProvision:
    naturaleza: str
    tipo: str
    clave: str
    categoria: CategoriaProvision


@dataclass(frozen=True)
class _FilaConfigEmpresa:
    zona_salarial: ZonaSalarial | None
    dias_aguinaldo: int | None
    factor_prima_vacacional: Decimal | None


@dataclass
class _Plan:
    """Todo el archivo ya validado y convertido, antes de tocar la base."""

    secciones: list[str] = field(default_factory=list)
    params: list[_FilaParam] = field(default_factory=list)
    marcas: list[_FilaMarca] = field(default_factory=list)
    vacaciones: list[_FilaVacaciones] = field(default_factory=list)
    departamentos: list[_FilaDepartamento] = field(default_factory=list)
    provisiones: list[_FilaProvision] = field(default_factory=list)
    config_empresa: list[_FilaConfigEmpresa] = field(default_factory=list)


_SECCIONES_POR_EMPRESA = ("map_departamento", "map_concepto_provision", "configuracion_empresa")
_SECCIONES = ("param_fiscal", "catalogo_percepcion_marca", "tabla_vacaciones", *_SECCIONES_POR_EMPRESA)


def _requerido(fila: Mapping[str, object], campo: str, ctx: str) -> object:
    bruto = fila.get(campo)
    if bruto is None:
        raise ErrorDeConfiguracion(f"{ctx}: falta el campo obligatorio `{campo}`.")
    return bruto


def _texto(bruto: object, campo: str, ctx: str, *, largo: int | None = None, largo_max: int | None = None) -> str:
    """`largo` fija la longitud exacta (claves de catálogo); `largo_max` el ancho de la
    columna, para que un texto largo salga como `ValueError` con su renglón y no como un
    `DataError` 1406 de MySQL a media escritura."""
    if not isinstance(bruto, str):
        raise ErrorDeConfiguracion(
            f"{ctx}: `{campo}` debe ser texto y llegó como {type(bruto).__name__} ({bruto!r}). "
            "Las claves de catálogo del SAT van entrecomilladas en el YAML: '001' no es 1."
        )
    valor = bruto.strip()
    if not valor:
        raise ErrorDeConfiguracion(f"{ctx}: `{campo}` no puede ir vacío.")
    if largo is not None and len(valor) != largo:
        raise ErrorDeConfiguracion(f"{ctx}: `{campo}` debe tener {largo} posiciones y trae {len(valor)} ({valor!r}).")
    if largo_max is not None and len(valor) > largo_max:
        raise ErrorDeConfiguracion(
            f"{ctx}: `{campo}` no puede pasar de {largo_max} caracteres y trae {len(valor)} "
            "(la columna lo truncaría o la escritura fallaría)."
        )
    return valor


def _decimal(bruto: object, campo: str, ctx: str) -> Decimal:
    if isinstance(bruto, bool):
        raise ErrorDeConfiguracion(f"{ctx}: `{campo}` debe ser un número, no un booleano.")
    if isinstance(bruto, float):
        raise ErrorDeConfiguracion(
            f"{ctx}: `{campo}` llegó como float ({bruto!r}) y perdería precisión. Entrecomíllalo en el "
            "YAML (`valor: '123.45'`) para que se convierta exacto a Decimal."
        )
    if isinstance(bruto, int):
        return Decimal(bruto)
    if isinstance(bruto, str):
        try:
            return Decimal(bruto.strip())
        except InvalidOperation:
            raise ErrorDeConfiguracion(f"{ctx}: `{campo}` no es un número válido ({bruto!r}).") from None
    raise ErrorDeConfiguracion(f"{ctx}: `{campo}` debe ser un número entrecomillado y llegó {type(bruto).__name__}.")


def _entero(bruto: object, campo: str, ctx: str) -> int:
    if isinstance(bruto, bool) or not isinstance(bruto, int):
        raise ErrorDeConfiguracion(f"{ctx}: `{campo}` debe ser un entero y llegó {bruto!r}.")
    return bruto


def _booleano(bruto: object, campo: str, ctx: str) -> bool:
    if not isinstance(bruto, bool):
        raise ErrorDeConfiguracion(f"{ctx}: `{campo}` debe ser true o false y llegó {bruto!r}.")
    return bruto


def _fecha(bruto: object, campo: str, ctx: str) -> date:
    if isinstance(bruto, datetime):
        return bruto.date()
    if isinstance(bruto, date):
        return bruto
    if isinstance(bruto, str):
        try:
            return date.fromisoformat(bruto.strip())
        except ValueError:
            raise ErrorDeConfiguracion(f"{ctx}: `{campo}` no es una fecha AAAA-MM-DD válida ({bruto!r}).") from None
    raise ErrorDeConfiguracion(f"{ctx}: `{campo}` debe ser una fecha AAAA-MM-DD y llegó {bruto!r}.")


def _opcion(bruto: object, enum_cls: type[_E], campo: str, ctx: str) -> _E:
    texto = _texto(bruto, campo, ctx)
    try:
        return enum_cls(texto)
    except ValueError:
        validos = ", ".join(str(e.value) for e in enum_cls)
        raise ErrorDeConfiguracion(f"{ctx}: `{campo}` = {texto!r} no es válido. Opciones: {validos}.") from None


def _filas(bruto: object, seccion: str, ruta: Path) -> list[Mapping[str, object]]:
    if not isinstance(bruto, list):
        raise ErrorDeConfiguracion(f"{ruta.name}: la sección `{seccion}` debe ser una lista de renglones.")
    filas: list[Mapping[str, object]] = []
    for i, cruda in enumerate(bruto):
        if not isinstance(cruda, dict):
            raise ErrorDeConfiguracion(f"{ruta.name}, {seccion}[{i}]: cada renglón debe ser un mapa de campos.")
        filas.append({str(k): v for k, v in cruda.items()})
    return filas


def _leer_plan(ruta: Path) -> _Plan:
    """Lee y valida el archivo completo **antes** de escribir nada. Cualquier problema sale
    como `ErrorDeConfiguracion` diciendo archivo, renglón y campo."""
    if not ruta.is_file():
        raise ErrorDeConfiguracion(f"No existe el archivo de configuración {ruta}.")
    try:
        crudo: object = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ErrorDeConfiguracion(f"{ruta.name}: el YAML no se pudo interpretar ({exc}).") from None
    plan = _Plan()
    if crudo is None:
        return plan
    if not isinstance(crudo, dict):
        raise ErrorDeConfiguracion(f"{ruta.name}: el archivo debe ser un mapa de secciones.")
    documento: dict[str, object] = {str(k): v for k, v in crudo.items()}

    desconocidas = sorted(set(documento) - set(_SECCIONES))
    if desconocidas:
        raise ErrorDeConfiguracion(
            f"{ruta.name}: sección(es) desconocida(s) {desconocidas}. Válidas: {', '.join(_SECCIONES)}."
        )

    for seccion in _SECCIONES:
        if seccion not in documento:
            continue
        plan.secciones.append(seccion)
        # Clave natural -> renglón donde apareció primero. Dos renglones con la misma clave
        # natural son un error de captura ('022' pegado dos veces es el más probable de la
        # semilla de percepciones) y hay que atraparlo aquí: en las tablas con PK compuesta
        # reventaría como `IntegrityError` a media escritura, y en `param_fiscal` —donde el
        # segundo renglón simplemente actualiza al primero— pasaría callado, con el resumen
        # informando dos renglones cargados donde solo quedó uno, y la cifra del último.
        vistas: dict[object, int] = {}
        for i, fila in enumerate(_filas(documento[seccion], seccion, ruta)):
            ctx = f"{ruta.name}, {seccion}[{i}]"
            natural: object
            if seccion == "param_fiscal":
                param = _leer_param(fila, ctx)
                natural = (param.clave, param.vigencia_desde)
                plan.params.append(param)
            elif seccion == "catalogo_percepcion_marca":
                marca = _leer_marca(fila, ctx)
                natural = marca.tipo_percepcion
                plan.marcas.append(marca)
            elif seccion == "tabla_vacaciones":
                vacaciones = _leer_vacaciones(fila, ctx)
                natural = vacaciones.anios_antiguedad
                plan.vacaciones.append(vacaciones)
            elif seccion == "map_departamento":
                departamento = _FilaDepartamento(
                    departamento_texto=_texto(
                        _requerido(fila, "departamento_texto", ctx), "departamento_texto", ctx, largo_max=100
                    ),
                    centro_costo=_texto(_requerido(fila, "centro_costo", ctx), "centro_costo", ctx, largo_max=100),
                )
                natural = departamento.departamento_texto
                plan.departamentos.append(departamento)
            elif seccion == "map_concepto_provision":
                provision = _leer_provision(fila, ctx)
                natural = (provision.naturaleza, provision.tipo, provision.clave)
                plan.provisiones.append(provision)
            else:
                # La sección describe una sola empresa (la que dice `--empresa-id`), así que
                # cualquier segundo renglón es duplicado por definición.
                natural = "configuracion_empresa"
                plan.config_empresa.append(_leer_config_empresa(fila, ctx))

            anterior = vistas.get(natural)
            if anterior is not None:
                raise ErrorDeConfiguracion(
                    f"{ctx}: la clave natural {natural!r} ya venía en {seccion}[{anterior}] del mismo "
                    "archivo. Dos renglones con la misma clave se pisan entre sí: el archivo diría una "
                    "cosa y la base guardaría la del último. Deja uno solo."
                )
            vistas[natural] = i
    return plan


def _leer_param(fila: Mapping[str, object], ctx: str) -> _FilaParam:
    clave = _texto(_requerido(fila, "clave", ctx), "clave", ctx, largo_max=40)
    if clave not in CLAVES_PARAM_FISCAL:
        raise ErrorDeConfiguracion(
            f"{ctx}: `clave` = {clave!r} no es una clave conocida de param_fiscal. "
            f"Esperadas: {', '.join(sorted(CLAVES_PARAM_FISCAL))}. Una clave con una letra de más se "
            "captura y se confirma sin problema, y después nadie la lee jamás."
        )
    vigencia_desde = _fecha(_requerido(fila, "vigencia_desde", ctx), "vigencia_desde", ctx)
    hasta_bruto = fila.get("vigencia_hasta")
    vigencia_hasta = None if hasta_bruto is None else _fecha(hasta_bruto, "vigencia_hasta", ctx)
    if vigencia_hasta is not None and vigencia_hasta < vigencia_desde:
        raise ErrorDeConfiguracion(
            f"{ctx}: `vigencia_hasta` ({vigencia_hasta}) es anterior a `vigencia_desde` ({vigencia_desde})."
        )
    valor = _decimal(_requerido(fila, "valor", ctx), "valor", ctx)
    if valor <= 0:
        raise ErrorDeConfiguracion(
            f"{ctx}: `valor` debe ser positivo (llegó {valor}). Un cero o un negativo en un tope de exención "
            "o en un salario mínimo produce cálculos falsos sin que nadie los note."
        )
    ejercicio_bruto = fila.get("ejercicio")
    return _FilaParam(
        ejercicio=None if ejercicio_bruto is None else _entero(ejercicio_bruto, "ejercicio", ctx),
        clave=clave,
        valor=valor,
        vigencia_desde=vigencia_desde,
        vigencia_hasta=vigencia_hasta,
        # `fuente` es obligatoria: sin ella nadie puede revisar el valor antes de confirmarlo.
        fuente=_texto(_requerido(fila, "fuente", ctx), "fuente", ctx, largo_max=500),
        contexto=ctx,
    )


def _leer_marca(fila: Mapping[str, object], ctx: str) -> _FilaMarca:
    base = _opcion(_requerido(fila, "base_exencion", ctx), BaseExencion, "base_exencion", ctx)
    factor_bruto = fila.get("factor_exencion")
    factor = None if factor_bruto is None else _decimal(factor_bruto, "factor_exencion", ctx)
    if base is BaseExencion.NINGUNA and factor is not None:
        raise ErrorDeConfiguracion(f"{ctx}: con `base_exencion: NINGUNA` no puede haber `factor_exencion`.")
    if base is not BaseExencion.NINGUNA and factor is None:
        raise ErrorDeConfiguracion(f"{ctx}: `base_exencion: {base.value}` exige un `factor_exencion`.")
    if factor is not None and factor <= 0:
        raise ErrorDeConfiguracion(f"{ctx}: `factor_exencion` debe ser positivo (llegó {factor}).")
    # Opcional y por omisión falso: aplica a una minoría de los tipos, así que el renglón
    # solo lo declara donde el art. 93 lo impone. Ver la columna en el modelo.
    tope_bruto = fila.get("sujeto_a_tope_conjunto")
    tope = False if tope_bruto is None else _booleano(tope_bruto, "sujeto_a_tope_conjunto", ctx)
    if tope and base is BaseExencion.NINGUNA:
        raise ErrorDeConfiguracion(
            f"{ctx}: `sujeto_a_tope_conjunto: true` no tiene sentido con `base_exencion: NINGUNA` — "
            "el tope conjunto del art. 93 de la LISR limita una exención, y aquí no hay ninguna que "
            "limitar. O el tipo sí tiene exención y falta capturarla, o la marca del tope sobra."
        )
    # La duda declarada del renglón, si la trae. Es opcional: 5 de los 44 tipos no tienen
    # ninguna. Va como campo y no como comentario porque los comentarios no se cargan, y la
    # pantalla de confirmación necesita enseñarla al lado del botón (ver el modelo).
    nota_bruta = fila.get("nota_revision")
    nota = None if nota_bruta is None else _texto(nota_bruta, "nota_revision", ctx)

    tipo_percepcion = _texto(_requerido(fila, "tipo_percepcion", ctx), "tipo_percepcion", ctx, largo=3)
    exige_tipo_percepcion_conocido(tipo_percepcion, ctx)
    return _FilaMarca(
        tipo_percepcion=tipo_percepcion,
        es_ingreso_ordinario=_booleano(_requerido(fila, "es_ingreso_ordinario", ctx), "es_ingreso_ordinario", ctx),
        base_exencion=base,
        factor_exencion=factor,
        integra_sbc=_booleano(_requerido(fila, "integra_sbc", ctx), "integra_sbc", ctx),
        es_provisionable=_booleano(_requerido(fila, "es_provisionable", ctx), "es_provisionable", ctx),
        sujeto_a_tope_conjunto=tope,
        nota_revision=nota,
    )


def _leer_vacaciones(fila: Mapping[str, object], ctx: str) -> _FilaVacaciones:
    anios = _entero(_requerido(fila, "anios_antiguedad", ctx), "anios_antiguedad", ctx)
    dias = _entero(_requerido(fila, "dias", ctx), "dias", ctx)
    if anios < 1:
        raise ErrorDeConfiguracion(f"{ctx}: `anios_antiguedad` arranca en 1 (art. 76 LFT) y llegó {anios}.")
    if dias < 1:
        raise ErrorDeConfiguracion(f"{ctx}: `dias` debe ser positivo y llegó {dias}.")
    return _FilaVacaciones(anios_antiguedad=anios, dias=dias)


def _leer_provision(fila: Mapping[str, object], ctx: str) -> _FilaProvision:
    return _FilaProvision(
        naturaleza=_texto(_requerido(fila, "naturaleza", ctx), "naturaleza", ctx, largo=1),
        tipo=_texto(_requerido(fila, "tipo", ctx), "tipo", ctx, largo=3),
        clave=_texto(_requerido(fila, "clave", ctx), "clave", ctx, largo_max=15),
        categoria=_opcion(_requerido(fila, "categoria", ctx), CategoriaProvision, "categoria", ctx),
    )


def _leer_config_empresa(fila: Mapping[str, object], ctx: str) -> _FilaConfigEmpresa:
    zona_bruto = fila.get("zona_salarial")
    dias_bruto = fila.get("dias_aguinaldo")
    factor_bruto = fila.get("factor_prima_vacacional")
    dias = None if dias_bruto is None else _entero(dias_bruto, "dias_aguinaldo", ctx)
    factor = None if factor_bruto is None else _decimal(factor_bruto, "factor_prima_vacacional", ctx)
    if dias is not None and dias < 1:
        raise ErrorDeConfiguracion(f"{ctx}: `dias_aguinaldo` debe ser positivo y llegó {dias}.")
    if factor is not None and factor <= 0:
        raise ErrorDeConfiguracion(f"{ctx}: `factor_prima_vacacional` debe ser positivo y llegó {factor}.")
    return _FilaConfigEmpresa(
        zona_salarial=None if zona_bruto is None else _opcion(zona_bruto, ZonaSalarial, "zona_salarial", ctx),
        dias_aguinaldo=dias,
        factor_prima_vacacional=factor,
    )


@dataclass(frozen=True)
class ResultadoCarga:
    """Lo que hizo una carga: cuántos renglones escribió por tabla y cuáles se saltó."""

    filas: dict[str, int]
    omitidos: list[str]


async def cargar_desde_yaml(
    db: AsyncSession, ruta: Path, *, empresa_id: int | None = None, forzar: bool = False
) -> dict[str, int]:
    """Carga un archivo de semilla y devuelve cuántos renglones **escribió** por tabla.

    Envoltura de `cargar_desde_yaml_detallado` que se queda solo con el conteo; usa la otra
    si necesitas saber qué renglones se omitieron y por qué.
    """
    return (await cargar_desde_yaml_detallado(db, ruta, empresa_id=empresa_id, forzar=forzar)).filas


async def cargar_desde_yaml_detallado(
    db: AsyncSession, ruta: Path, *, empresa_id: int | None = None, forzar: bool = False
) -> ResultadoCarga:
    """Carga un archivo de semilla.

    Es **idempotente**: la clave natural de cada tabla decide si el renglón se inserta o se
    actualiza, así que volver a correrlo no duplica nada. Y **nunca confirma**: todo lo que
    entra queda esperando que una persona lo revise, incluso si viene de una fuente
    impecable. Si al recargar cambia el contenido de un renglón, la confirmación previa se
    limpia (en `param_fiscal` y en `catalogo_percepcion_marca`, las dos tablas con puerta).

    **No pisa correcciones manuales.** Un `param_fiscal` con `origen: MANUAL` que diga algo
    distinto del YAML se omite y se reporta, en vez de escribirse. El caso que lo motiva:
    sale una fe de erratas, un admin corrige la fuente por el endpoint (que sí deja bitácora),
    y tres semanas después alguien recarga las semillas; sin esta protección la fila volvería
    a `SEMILLA` con la fuente vieja, conservando la confirmación —porque la cifra coincide— y
    sin ningún rastro del borrado, ya que el cargador no escribe bitácora. Con `forzar=True`
    la semilla gana; es la salida explícita.

    El archivo se valida entero antes de escribir el primer renglón, y la escritura va en
    una sola transacción: o entra todo o no entra nada. Un fallo al cargar es barato; media
    semilla aplicada, no.
    """
    plan = _leer_plan(ruta)

    por_empresa = [s for s in plan.secciones if s in _SECCIONES_POR_EMPRESA]
    if por_empresa and empresa_id is None:
        raise ErrorDeConfiguracion(
            f"{ruta.name}: la(s) sección(es) {por_empresa} son por empresa y hace falta `empresa_id`. "
            "El mismo texto de departamento mapea a centros de costo distintos en empresas distintas: "
            "cargarlo sin decir a cuál pertenece no tiene un default seguro."
        )
    if por_empresa and empresa_id is not None and await db.get(Empresa, empresa_id) is None:
        raise ErrorDeConfiguracion(f"{ruta.name}: no existe la empresa {empresa_id}.")

    resumen = {seccion: 0 for seccion in plan.secciones}
    omitidos: list[str] = []
    try:
        # Ordenar por (clave, vigencia_desde) hace dos cosas: permite cerrar el tramo viejo y
        # abrir el nuevo en una sola edición del archivo sin depender del orden de los
        # renglones, y fija un orden total de adquisición de candados (`FOR UPDATE` es por
        # clave), así que dos cargas simultáneas no se pueden interbloquear.
        for param in sorted(plan.params, key=lambda f: (f.clave, f.vigencia_desde)):
            try:
                await guardar_param_fiscal(
                    db,
                    clave=param.clave,
                    valor=param.valor,
                    vigencia_desde=param.vigencia_desde,
                    vigencia_hasta=param.vigencia_hasta,
                    origen=OrigenValor.SEMILLA,
                    fuente=param.fuente,
                    ejercicio=param.ejercicio,
                    contexto=param.contexto,
                    proteger_correccion_manual=not forzar,
                )
            except CorreccionManualProtegida as exc:
                omitidos.append(f"{exc} Usa --forzar para que gane la semilla.")
                continue
            resumen["param_fiscal"] += 1

        if plan.marcas:
            existentes_marca = {m.tipo_percepcion: m for m in (await db.scalars(select(CatalogoPercepcionMarca))).all()}
            for marca in plan.marcas:
                destino = existentes_marca.get(marca.tipo_percepcion)
                if destino is None:
                    db.add(
                        CatalogoPercepcionMarca(
                            tipo_percepcion=marca.tipo_percepcion,
                            es_ingreso_ordinario=marca.es_ingreso_ordinario,
                            base_exencion=marca.base_exencion,
                            factor_exencion=marca.factor_exencion,
                            integra_sbc=marca.integra_sbc,
                            es_provisionable=marca.es_provisionable,
                            sujeto_a_tope_conjunto=marca.sujeto_a_tope_conjunto,
                            nota_revision=marca.nota_revision,
                        )
                    )
                else:
                    # Igual que en `param_fiscal`: si alguna marca cambia, lo confirmado ya no
                    # describe lo que hay, y un `factor_exencion` distinto es una exención
                    # distinta. Vuelve a la cola de revisión.
                    if (
                        destino.es_ingreso_ordinario != marca.es_ingreso_ordinario
                        or destino.base_exencion is not marca.base_exencion
                        or destino.factor_exencion != marca.factor_exencion
                        or destino.integra_sbc != marca.integra_sbc
                        or destino.es_provisionable != marca.es_provisionable
                        or destino.sujeto_a_tope_conjunto != marca.sujeto_a_tope_conjunto
                        # Una duda **nueva o distinta** también devuelve la marca a la cola, y
                        # de forma asimétrica: que la nota desaparezca no limpia nada. Ver
                        # `_duda_nueva` en `app/api/v1/configuracion.py` para el argumento
                        # completo; en corto: confirmar significa "una persona revisó esto y
                        # responde por ello", y si aparece una duda que esa persona no tenía
                        # delante, la confirmación afirma una revisión que no ocurrió contra
                        # esa información. Resolverla, en cambio, no invalida nada.
                        or (marca.nota_revision is not None and marca.nota_revision != destino.nota_revision)
                    ):
                        destino.confirmado_por = None
                        destino.confirmado_en = None
                    destino.es_ingreso_ordinario = marca.es_ingreso_ordinario
                    destino.base_exencion = marca.base_exencion
                    destino.factor_exencion = marca.factor_exencion
                    destino.integra_sbc = marca.integra_sbc
                    destino.es_provisionable = marca.es_provisionable
                    destino.sujeto_a_tope_conjunto = marca.sujeto_a_tope_conjunto
                    destino.nota_revision = marca.nota_revision
                resumen["catalogo_percepcion_marca"] += 1

        if plan.vacaciones:
            existentes_vac = {v.anios_antiguedad: v for v in (await db.scalars(select(TablaVacaciones))).all()}
            for renglon in plan.vacaciones:
                destino_vac = existentes_vac.get(renglon.anios_antiguedad)
                if destino_vac is None:
                    db.add(TablaVacaciones(anios_antiguedad=renglon.anios_antiguedad, dias=renglon.dias))
                else:
                    destino_vac.dias = renglon.dias
                resumen["tabla_vacaciones"] += 1

        if empresa_id is not None:
            resumen.update(await _cargar_por_empresa(db, plan, empresa_id))

        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return ResultadoCarga(filas=resumen, omitidos=omitidos)


async def _cargar_por_empresa(db: AsyncSession, plan: _Plan, empresa_id: int) -> dict[str, int]:
    """Las tres secciones que cuelgan de una empresa. Cada una precarga lo existente con una
    sola consulta y decide en memoria si inserta o actualiza (regla 11: nada de una consulta
    por renglón)."""
    resumen: dict[str, int] = {}

    if "map_departamento" in plan.secciones:
        existentes = {
            d.departamento_texto: d
            for d in (await db.scalars(select(MapDepartamento).where(MapDepartamento.empresa_id == empresa_id))).all()
        }
        for depto in plan.departamentos:
            destino = existentes.get(depto.departamento_texto)
            if destino is None:
                db.add(
                    MapDepartamento(
                        empresa_id=empresa_id,
                        departamento_texto=depto.departamento_texto,
                        centro_costo=depto.centro_costo,
                    )
                )
            else:
                destino.centro_costo = depto.centro_costo
        resumen["map_departamento"] = len(plan.departamentos)

    if "map_concepto_provision" in plan.secciones:
        existentes_prov = {
            (p.naturaleza, p.tipo, p.clave): p
            for p in (
                await db.scalars(select(MapConceptoProvision).where(MapConceptoProvision.empresa_id == empresa_id))
            ).all()
        }
        for prov in plan.provisiones:
            destino_prov = existentes_prov.get((prov.naturaleza, prov.tipo, prov.clave))
            if destino_prov is None:
                db.add(
                    MapConceptoProvision(
                        empresa_id=empresa_id,
                        naturaleza=prov.naturaleza,
                        tipo=prov.tipo,
                        clave=prov.clave,
                        categoria=prov.categoria,
                    )
                )
            else:
                destino_prov.categoria = prov.categoria
        resumen["map_concepto_provision"] = len(plan.provisiones)

    if "configuracion_empresa" in plan.secciones:
        if len(plan.config_empresa) > 1:
            raise ErrorDeConfiguracion(
                "configuracion_empresa: la sección describe una sola empresa y trae "
                f"{len(plan.config_empresa)} renglones."
            )
        actual = await db.get(ConfiguracionEmpresa, empresa_id)
        for config in plan.config_empresa:
            if actual is None:
                db.add(
                    ConfiguracionEmpresa(
                        empresa_id=empresa_id,
                        zona_salarial=config.zona_salarial,
                        dias_aguinaldo=config.dias_aguinaldo,
                        factor_prima_vacacional=config.factor_prima_vacacional,
                    )
                )
            else:
                actual.zona_salarial = config.zona_salarial
                actual.dias_aguinaldo = config.dias_aguinaldo
                actual.factor_prima_vacacional = config.factor_prima_vacacional
        resumen["configuracion_empresa"] = len(plan.config_empresa)

    await db.flush()
    return resumen
