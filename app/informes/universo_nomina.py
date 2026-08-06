"""Universo y banderas de estatus compartidos por los informes del grupo B que reportan
CFDI de nómina uno a uno (tipo `N`, emitidos por la empresa, acotados sobre `fecha_pago`).

Extraído en la tarea 3 (B-01) al escribir la **segunda** copia de esta lógica —B-02 ya la
tenía— siguiendo la instrucción de diseño de la revisión final de la fase 1: si dos
informes del mismo periodo calculan el universo o las banderas de estatus cada uno por su
cuenta, en cuanto diverjan un carácter darán totales distintos entre sí y nadie sabrá cuál
creer. Lo que sí queda deliberadamente duplicado (no aquí) es lo propio de cada informe:
B-02 agrupa por `(naturaleza, tipo, clave)` y emite `CONCEPTO_INCONSISTENTE`,
`CLAVE_VACIA`, `DEDUCCION_MAYOR_PERCEPCION`, `NETO_NEGATIVO`, `DIAS_PAGADOS_ATIPICO` y
`PERIODO_TRASLAPADO`; B-01 agrupa por `(naturaleza, tipo)` y emite `CONJUNTO_REDUCIDO`.
Ninguna de esas es una identidad del universo compartido, así que viven en su propio
módulo.

Lo compartido son tres cosas:

1. `universo()`: qué comprobantes entran (fase 1 del algoritmo de B-02, idéntica en B-01).
2. `rango_de_emision()` + `banderas_de_no_normalizables()`: los CFDI de nómina que el
   `join` con `nomina` de `universo()` deja fuera, recuperados por `fecha_emision` (§9 del
   diseño) para que ninguno desaparezca en silencio de la hoja `Datos`.
3. `banderas_de_estatus()`, `banderas_de_totales_descuadrados()` y
   `banderas_de_gravado_y_exento_descuadrados()`: las banderas de estatus del comprobante/ETL y
   las de descuadre entre los totales del encabezado de Nómina y la suma de sus nodos, que no
   dependen de cómo cada informe agrupe sus columnas dinámicas.

**`banderas_de_estatus()` la llaman cinco de los seis informes del grupo B** —B-01, B-02, B-04,
B-05 y B-07—, no solo B-01/B-02 como al cerrar la fase 2. La sexta, B-10, la omite y lo argumenta;
ver el final de este párrafo. (No confundir con `banderas_de_no_normalizables()`, que sí la llaman
**los seis**: un CFDI que el ETL no pudo leer tampoco se puede auditar, así que B-10 también la
necesita.) Es la
condición explícita con la que el §11 del diseño acepta la divergencia de R-T1 ("todo
comprobante incluido que no sea vigente lleva bandera"): B-04, B-05 y B-07 la omitían, así que
una celda de la matriz de B-04 llena por un CFDI cancelado ante el SAT decía "esa quincena está
cubierta" sin marca, un hueco de B-07 podía quedar tapado por un CFDI que el SAT ya no reconoce,
y el acumulado anual de B-05 mezclaba `vigente` con `no_verificado` sin distinguirlos — y como
la verificación contra el SAT es asíncrona por diseño, `no_verificado` es el estado **normal** de
un ejercicio recién descargado, no un caso de borde. B-10 sí la omite y lo argumenta en su propio
docstring (su grano es el hallazgo, no el comprobante).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes.base import Bandera
from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.enums import EstatusCfdi
from app.models.nomina import Nomina, NominaPercepcion, NominaReceptor, NominaTotales

TOLERANCIA = Decimal("0.01")
"""Tolerancia de redondeo para comparar un total declarado contra la suma de sus nodos."""

MARGEN_TIMBRADO_DIAS = 31
"""Holgura, en días naturales y hacia los dos lados, entre `nomina.fecha_pago` (con la que
se acota el universo) y `Comprobante.fecha_emision` (lo único disponible para acotar los
CFDI que no llegaron a tener fila en `nomina`). Ver `rango_de_emision`.

31 días —un mes natural— y no los ~16 que bastarían para cubrir los 11 días hábiles de la
regla 2.7.5.3 de la RMF: el costo de una bandera de más es que el patrón la lea y la
descarte; el de una de menos es un recibo que nunca ve. Con datos sanos esta consulta no
devuelve nada, así que el margen no cuesta ruido en la operación normal."""


class ParametrosUniverso(Protocol):
    """Lo que `universo()`, `rango_de_emision()` y `banderas_de_no_normalizables()`
    necesitan de los `Parametros` de cada informe. B-01 y B-02 declaran sus propios
    `Parametros` (Pydantic, con más campos cada uno) y ambos cumplen este `Protocol` por
    estructura, sin heredar de nada — es lo que permite que las tres funciones de este
    módulo no dependan de cuál informe las llama.

    `tipo_nomina` se tipa igual de estricto que en los dos `Parametros` reales
    (`Literal["O", "E", "AMBOS"]`) y no como `str`: un atributo de `Protocol` se comprueba de
    forma invariante (puede escribirse, no solo leerse), así que un `str` ahí rechazaría en
    `mypy --strict` a cualquier `Parametros` cuyo campo sea el `Literal` más específico —
    que es exactamente lo que B-01 y B-02 declaran.
    """

    fecha_desde: date
    fecha_hasta: date
    tipo_nomina: Literal["O", "E", "AMBOS"]
    incluir_cancelados: bool


def universo(empresa_id: int, rfc_empresa: str, p: ParametrosUniverso) -> Select[Any]:
    """Fase 1 del algoritmo de B-02, común a todo el grupo B que reporta uno-a-uno por CFDI
    de nómina: qué comprobantes entran.

    `rfc_emisor == rfc_empresa` implementa el "**emitidos** por la empresa" del universo del
    grupo B (§11 del diseño): la empresa es el patrón. Con una sola empresa que es a la vez
    patrón la condición es inerte, pero en cuanto exista una segunda empresa —o se descargue
    una nómina recibida— sin ella el informe mezclaría dos patrones en la misma hoja.
    """
    consulta = (
        select(Comprobante, Nomina, NominaReceptor, NominaTotales, ComprobanteDetalle)
        .join(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
        .outerjoin(NominaReceptor, NominaReceptor.comprobante_id == Comprobante.comprobante_id)
        .outerjoin(NominaTotales, NominaTotales.comprobante_id == Comprobante.comprobante_id)
        .outerjoin(ComprobanteDetalle, ComprobanteDetalle.comprobante_id == Comprobante.comprobante_id)
        .where(
            Comprobante.empresa_id == empresa_id,
            Comprobante.rfc_emisor == rfc_empresa,
            Comprobante.tipo_comprobante == "N",
            Nomina.fecha_pago >= p.fecha_desde,
            Nomina.fecha_pago <= p.fecha_hasta,
        )
        .order_by(Nomina.fecha_pago, Comprobante.comprobante_id)
    )
    if not p.incluir_cancelados:
        consulta = consulta.where(Comprobante.estatus != EstatusCfdi.CANCELADO)
    if p.tipo_nomina != "AMBOS":
        consulta = consulta.where(Nomina.tipo_nomina == p.tipo_nomina)
    return consulta


def rango_de_emision(p: ParametrosUniverso) -> tuple[datetime, datetime]:
    """Rango de `Comprobante.fecha_emision` con el que se acotan los CFDI de nómina que
    **no** pueden entrar al informe por `universo()`.

    **Por qué el criterio es distinto al del universo.** El universo se acota por
    `nomina.fecha_pago` (R-T6), pero un tipo `N` que nunca se normalizó, o que llegó sin
    complemento de nómina, no tiene fila en `nomina`: no existe `fecha_pago` con la que
    acotarlo. El único dato de fecha disponible es el del encabezado del CFDI, que ya está
    en `comprobantes`.

    **La fecha de timbrado NO coincide con la de pago, y el margen no es opcional.** En la
    BD real de la empresa 11 los 8 CFDI de nómina están timbrados **al día siguiente** del
    pago (pago 2026-06-30 → emisión 2026-07-01; pago 2026-07-15 → emisión 2026-07-16), y la
    RMF (regla 2.7.5.3) permite timbrar hasta 11 días hábiles después del último día del
    periodo pagado, además de admitir el timbrado anticipado. Sin margen, un informe de
    `[2026-06-01, 2026-06-30]` con una nómina pagada el 30 de junio, timbrada el 1 de julio
    y con el ETL fallido salía con **0 filas y 0 banderas** y el aviso "Sin CFDI de nómina en
    el rango solicitado" — exactamente el fallo que esta consulta existe para evitar.

    Por eso el margen se aplica a **los dos extremos** (`MARGEN_TIMBRADO_DIAS`) y es
    holgado. El criterio para elegirlo es asimétrico a propósito: **una bandera de más se ve
    y se descarta; una de menos no se ve nunca.** Lo único que el margen debe seguir
    acotando es que un `N` roto de un ejercicio ajeno no aparezca en el informe de este mes,
    porque una hoja `Banderas` con decenas de entradas irrelevantes es una hoja que nadie
    lee — que es otra forma de perder el aviso.

    Intervalo **semiabierto** en el extremo superior en vez de `<= ... 23:59:59.999999`:
    `fecha_emision` es `DATETIME` sin fracción de segundo, y MySQL redondea los microsegundos
    de la constante hacia arriba al comparar, con lo que `datetime.max.time()` incluiría un
    día de más.
    """
    return (
        datetime.combine(p.fecha_desde - timedelta(days=MARGEN_TIMBRADO_DIAS), time.min),
        datetime.combine(p.fecha_hasta + timedelta(days=MARGEN_TIMBRADO_DIAS + 1), time.min),
    )


async def banderas_de_no_normalizables(db: AsyncSession, empresa_id: int, rfc_empresa: str | None, p: ParametrosUniverso) -> list[Bandera]:
    """Los CFDI de nómina que el informe **no puede** presentar, uno por bandera (§9 del diseño).

    **`rfc_empresa=None` desactiva el filtro de emisor**, para el único informe del grupo cuyo
    universo tampoco lo aplica: B-05 no puede filtrar por `rfc_emisor` porque su regla
    `MULTI_PATRON` existe precisamente para detectar al empleado que cobra de más de un RFC (ver
    el docstring de `b05_acumulado_anual`). Si esta consulta filtrara por emisor y el universo de
    ese informe no, un CFDI de nómina roto de un segundo patrón —el caso que B-05 existe para
    señalar— desaparecería sin bandera del informe más delicado del catálogo. Los otros cinco
    informes pasan el RFC de la empresa y el filtro se aplica igual que antes.

    `universo()` hace `join` con `nomina`: sin fila en `nomina` el comprobante queda fuera
    de la hoja `Datos`, y ahí se acaba cualquier rastro de que existió. Esta segunda consulta
    lo recupera y lo reporta con su UUID, distinguiendo tres causas:

    - sin fila en `comprobante_detalle` → `SIN_NORMALIZAR`: nunca pasó por el ETL.
    - con `error_normalizacion` → `SIN_NORMALIZAR`: el ETL lo intentó y falló (XML corrupto
      o perdido en disco).
    - con detalle y sin error → `COMPLEMENTO_AUSENTE`: es un tipo `N` que el SAT entregó sin
      complemento de nómina. El ETL hizo su trabajo; el XML no trae nómina que normalizar.

    Los tres son de severidad alta: cada uno significa un recibo que el patrón no verá en la
    hoja `Datos` y que, sin bandera, conciliaría creyendo que no existe.

    No se aplica el filtro `tipo_nomina`: es un atributo del complemento de nómina, que estos
    comprobantes justamente no tienen. Un `N` sin normalizar se reporta con cualquier valor
    del parámetro — no se puede saber si habría entrado al filtro, y callarlo sería el fallo
    que esta consulta existe para evitar.
    """
    inicio, fin = rango_de_emision(p)
    consulta = (
        select(Comprobante.uuid, ComprobanteDetalle.comprobante_id, ComprobanteDetalle.error_normalizacion)
        .outerjoin(ComprobanteDetalle, ComprobanteDetalle.comprobante_id == Comprobante.comprobante_id)
        .outerjoin(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
        .where(
            Comprobante.empresa_id == empresa_id,
            Comprobante.tipo_comprobante == "N",
            Nomina.comprobante_id.is_(None),
            Comprobante.fecha_emision >= inicio,
            Comprobante.fecha_emision < fin,
        )
        .order_by(Comprobante.comprobante_id)
    )
    if rfc_empresa is not None:
        consulta = consulta.where(Comprobante.rfc_emisor == rfc_empresa)
    if not p.incluir_cancelados:
        consulta = consulta.where(Comprobante.estatus != EstatusCfdi.CANCELADO)

    banderas: list[Bandera] = []
    for uuid_cfdi, detalle_id, error in (await db.execute(consulta)).all():
        ambito = f"uuid:{uuid_cfdi}"
        if detalle_id is None:
            banderas.append(
                Bandera(
                    clave="SIN_NORMALIZAR",
                    severidad="alta",
                    ambito=ambito,
                    mensaje="CFDI de nómina que nunca pasó por el ETL: no tiene fila en `comprobante_detalle` y no aparece en la hoja Datos.",
                )
            )
        elif error:
            banderas.append(
                Bandera(
                    clave="SIN_NORMALIZAR",
                    severidad="alta",
                    ambito=ambito,
                    mensaje=f"El ETL no pudo leer su XML, así que no aparece en la hoja Datos: {error}",
                )
            )
        else:
            banderas.append(
                Bandera(
                    clave="COMPLEMENTO_AUSENTE",
                    severidad="alta",
                    ambito=ambito,
                    mensaje="CFDI tipo N sin complemento de nómina: no hay datos de nómina que reportar, así que no aparece en la hoja Datos.",
                )
            )
    return banderas


def banderas_de_estatus(comprobante: Comprobante, detalle: ComprobanteDetalle | None) -> list[Bandera]:
    """`DATOS_DE_CORRIDA_ANTERIOR`, `COMPROBANTE_CANCELADO` y `ESTATUS_NO_VERIFICADO`: no
    dependen de cómo cada informe agrupe sus columnas dinámicas, solo del estatus del
    comprobante ante el SAT y de si la última corrida del ETL falló sobre él.

    **Contrato de `repositories.normalizacion.registrar_error`:** ante un fallo del ETL los
    hijos de la última corrida buena se conservan a propósito (es el mejor estado conocido)
    y el consumidor debe comprobar `error_normalizacion IS NULL` antes de confiar en la fila.
    Los informes de este grupo eligen presentarla —perder el recibo sería peor— y avisar con
    `DATOS_DE_CORRIDA_ANTERIOR`: los importes son los de la corrida anterior del ETL, no los
    del XML que hay hoy en disco.

    **Divergencia declarada de R-T1** (documentada en B-02, aplica igual aquí): el diseño
    dice "por defecto solo `VIGENTE`". Lo implementado excluye únicamente los `CANCELADO`,
    así que los `no_verificado` —los que todavía no se le han consultado al SAT— sí entran.
    Exigir `VIGENTE` borraría del informe toda la nómina cuyo estatus aún no se ha
    consultado, y en este dominio la pérdida silenciosa de filas es peor que el problema que
    resuelve. Para que la inclusión no sea invisible: `ESTATUS_NO_VERIFICADO` (media) o
    `COMPROBANTE_CANCELADO` (alta, que solo puede aparecer con `incluir_cancelados=True`).
    """
    banderas: list[Bandera] = []
    ambito = f"uuid:{comprobante.uuid}"

    if detalle is not None and detalle.error_normalizacion:
        banderas.append(
            Bandera(
                clave="DATOS_DE_CORRIDA_ANTERIOR",
                severidad="alta",
                ambito=ambito,
                mensaje=(
                    "La última normalización de este CFDI falló; la fila se construyó con los datos de la corrida "
                    f"anterior del ETL y pueden estar desactualizados: {detalle.error_normalizacion}"
                ),
            )
        )

    if comprobante.estatus == EstatusCfdi.CANCELADO:
        banderas.append(
            Bandera(
                clave="COMPROBANTE_CANCELADO",
                severidad="alta",
                ambito=ambito,
                # Antes de la extracción (en B-02) este mensaje decía "sus importes suman en
                # el `importe_total` del Diccionario" — correcto ahí, pero esta función la
                # llaman ahora varios informes y no todos tienen una hoja Diccionario con esa
                # columna (B-01, por ejemplo, sí; otro informe futuro sobre este mismo
                # universo podría no tenerla). Se generalizó a propósito (ronda de
                # corrección 1 de la tarea 3): no es una transcripción literal de B-02.
                mensaje=(
                    "El CFDI está cancelado ante el SAT y se incluyó porque `incluir_cancelados=True`; "
                    "sus importes suman en el informe."
                ),
            )
        )
    elif comprobante.estatus == EstatusCfdi.NO_VERIFICADO:
        banderas.append(
            Bandera(
                clave="ESTATUS_NO_VERIFICADO",
                severidad="media",
                ambito=ambito,
                mensaje=(
                    "Su estatus todavía no se le ha consultado al SAT, así que podría estar cancelado. "
                    "Se incluye a propósito para no perder filas (divergencia declarada de R-T1)."
                ),
            )
        )
    return banderas


def banderas_de_totales_descuadrados(ambito: str, identidades: Sequence[tuple[str, Decimal | None, Decimal]]) -> list[Bandera]:
    """`TOTALES_DESCUADRADOS`: un total que declara el encabezado del complemento de Nómina no
    coincide con la suma de sus nodos, fuera de `TOLERANCIA`. `identidades` es
    `(nombre, declarado, calculado)`; un `declarado is None` no se compara (ausencia no es
    descuadre).

    Los llamadores cotejan con ella `total_percepciones`, `total_deducciones`,
    `total_otros_pagos` y `total_impuestos_retenidos` (identidades #1, #2, #3 y #9 de B-00);
    `total_gravado` y `total_exento` (#4 y #5) las cotejan a través de
    `banderas_de_gravado_y_exento_descuadrados`, que trae de la BD los datos que hacen falta y
    termina llamando aquí."""
    banderas: list[Bandera] = []
    for nombre, declarado, calculado in identidades:
        if declarado is not None and abs(declarado - calculado) > TOLERANCIA:
            banderas.append(
                Bandera(
                    clave="TOTALES_DESCUADRADOS",
                    severidad="alta",
                    ambito=ambito,
                    mensaje=f"{nombre} declarado {declarado} ≠ suma de nodos {calculado}.",
                )
            )
    return banderas


async def banderas_de_gravado_y_exento_descuadrados(db: AsyncSession, ids: Sequence[int]) -> list[Bandera]:
    """Identidades **#4 y #5 de B-00** (`nomina_totales.total_gravado` = Σ `importe_gravado` de
    las percepciones, y lo análogo para el exento), como banderas `TOTALES_DESCUADRADOS` al
    generar cualquier informe.

    **Por qué hacía falta, y por qué es una sola implementación compartida.** Estas dos
    identidades solo corrían en `tests/test_identidades_b00.py` y en
    `scripts/verificar_informes.py`; ningún informe las cotejaba al generarse. El efecto es que
    "Total gravado" y "Total exento" significan dos cosas distintas según el informe —B-01/B-02
    los reportan **del encabezado** (`nomina_totales`), B-05 los **recalcula de los nodos** para
    la constancia de percepciones— y con un CFDI descuadrado los dos informes daban cifras
    distintas del mismo concepto para el mismo periodo **sin una sola advertencia**. Peor dentro
    de una misma fila de B-05: "Total percepciones" viene del encabezado y "Total gravado +
    Total exento" de los nodos, así que la fila no cuadraba consigo misma en silencio. Las dos
    lecturas son correctas para su propósito y no se cambian; lo que se corrige es que el
    descuadre que las separa ahora se reporta.

    Una sola consulta agregada para todo el universo (regla 11: cero N+1). El `join` con
    `nomina_totales` es interno a propósito: sin fila ahí no hay total declarado que cotejar, y
    la ausencia de `nomina_totales` ya la reporta `identidades_b00.verificar` como falla del ETL.
    Una percepción ausente deja el `SUM` en `NULL`, que se compara como cero (una nómina que
    declara gravado y no trae percepciones **sí** es un descuadre real).
    """
    if not ids:
        return []
    consulta = (
        select(
            Comprobante.uuid,
            NominaTotales.total_gravado,
            NominaTotales.total_exento,
            func.sum(NominaPercepcion.importe_gravado).label("gravado"),
            func.sum(NominaPercepcion.importe_exento).label("exento"),
        )
        .join(NominaTotales, NominaTotales.comprobante_id == Comprobante.comprobante_id)
        .outerjoin(NominaPercepcion, NominaPercepcion.comprobante_id == Comprobante.comprobante_id)
        .where(Comprobante.comprobante_id.in_(ids))
        # Las cuatro columnas no agregadas van en el `GROUP BY` aunque dependan funcionalmente
        # del `comprobante_id`: `ONLY_FULL_GROUP_BY` (activo por defecto en MySQL 8) no siempre
        # deduce la dependencia a través de un `join`.
        .group_by(Comprobante.comprobante_id, Comprobante.uuid, NominaTotales.total_gravado, NominaTotales.total_exento)
        .order_by(Comprobante.comprobante_id)
    )

    banderas: list[Bandera] = []
    for uuid_cfdi, total_gravado, total_exento, gravado, exento in (await db.execute(consulta)).all():
        banderas.extend(
            banderas_de_totales_descuadrados(
                f"uuid:{uuid_cfdi}",
                (
                    ("total_gravado", _dec_o_none(total_gravado), _dec(gravado)),
                    ("total_exento", _dec_o_none(total_exento), _dec(exento)),
                ),
            )
        )
    return banderas


def _dec(valor: object) -> Decimal:
    """`func.sum` puede devolver `Decimal`, `float` o `None` según el dialecto; nunca se compara
    en binario (mismo patrón que `identidades_b00._dec`). `None` es cero: sin percepciones, la
    suma de nodos es cero."""
    if valor is None:
        return Decimal("0")
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def _dec_o_none(valor: object) -> Decimal | None:
    """Como `_dec`, pero conserva el `None` de un total **declarado** ausente: ahí sí importa la
    distinción, porque `banderas_de_totales_descuadrados` no compara lo que no se declaró."""
    if valor is None:
        return None
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))
