"""B-07 · Cartera de préstamos y descuentos recurrentes (§B-07 del documento fuente).

**El grano es `(rfc_receptor, tipo_deduccion, clave)`:** una fila por préstamo o descuento
recurrente de cada empleado (Infonavit, Fonacot, caja de ahorro, pensión alimenticia, etc.).
No es un informe de conciliación de importes: su propósito es rastrear algo que **el CFDI
no contiene**, el saldo del préstamo. El comprobante solo trae el descuento del periodo, así
que ninguna herramienta comercial hace este informe — el valor está en el **control de
continuidad** (B-07.R1), no en los totales.

**B-07.R1 — Continuidad, el hallazgo por el que existe este informe.** Se compara la serie
de periodos en los que aparece el descuento contra el eje teórico de `app.informes.periodos`
(el mismo módulo que usa B-04, tal como lo fija la ficha): tres clasificaciones.

- `CONTINUO`: sin huecos entre el primer y el último periodo con descuento, y el último
  coincide con el último periodo del eje.
- `INTERRUMPIDO`: hay huecos **intermedios** (periodos del eje, entre el primero y el
  último con descuento, sin descuento). Los huecos se listan en el mensaje de
  `DESCUENTO_INTERRUMPIDO`, porque el hueco concreto —qué quincena se dejó de descontar— es
  la información accionable: un préstamo cuyo descuento se detuvo sin liquidarse es dinero
  que la empresa dejó de recuperar y que nadie notó.
- `CONCLUIDO`: sin huecos intermedios, pero el último descuento es anterior al último periodo
  del eje — probablemente el préstamo se liquidó y por eso dejó de descontarse.

Nótese la prioridad: un hueco intermedio siempre clasifica como `INTERRUMPIDO`, incluso si
además el último descuento con dato es anterior al final del eje (un préstamo puede estar
interrumpido y además sin descuentos recientes a la vez; lo primero es lo urgente).

**La asignación usa `fecha_pago`, no `fecha_final_pago`, y la semántica de ventana de
`periodos.asignar_a_corte` es la correcta aquí** (a diferencia de B-04, que necesita la
semántica de día exacto para `CORTE_IRREGULAR` y la calcula aparte sin tocar `periodos.py`):
lo que importa para la continuidad es si el descuento **apareció** en ese periodo, no si el
timbrado cayó justo el día de corte. Por eso este módulo no reimplementa nada de
`periodos.py`, solo lo consume.

**Si no se puede construir el eje** (ninguna `periodicidad_pago` reconocida en el universo),
la columna `Continuidad` queda en `None` para todas las filas y se emite una sola bandera de
informe, `CONTINUIDAD_INDETERMINADA` — no se inventa una clasificación sin base teórica. El
resto del informe (identidad, agregados, modal) se sigue calculando: a diferencia de B-04,
cuyo informe completo *es* la matriz de periodos, aquí el eje solo alimenta una columna.

**El descuento modal, y por qué no es el promedio.** El modal es el valor más frecuente de
la serie y es lo que identifica la amortización pactada. Un ajuste ocasional (un abono
extra, una corrección) desvía el promedio pero no cambia cuál importe se repite más. El
desempate de la moda es por el **importe mayor**: una amortización pactada suele ser el
valor alto de la serie, y el ajuste el bajo — justo lo opuesto de lo que un desempate por
frecuencia de aparición o por importe menor elegiría.

**B-07.R3 — `AMORTIZACION_MODIFICADA`.** Se parte la serie (ordenada por fecha) en dos
mitades y se compara la moda de cada una. Si difieren, se reporta con las dos fases y sus
fechas: es lo esperado en un crédito Infonavit cuando se actualiza el factor de descuento,
así que no es un error, es información. Solo se evalúa con al menos
`_MINIMO_AMORTIZACION_MODIFICADA` descuentos: con menos, cada mitad tendría muy pocos datos
para que comparar modas distinga un cambio sostenido de un dato aislado.

**Alcance, B-07.R2.** Las columnas 10 a 13 de la ficha (monto original, saldo estimado,
descuentos restantes, fecha de liquidación) **no se implementan**: sin el monto original no
hay con qué estimarlas, y **no se infiere del descuento** — un préstamo con descuentos
irregulares (por incapacidades, ajustes) haría cualquier estimación así una ficción con
apariencia de dato duro. Por eso tampoco se declara un parámetro para capturar el monto
original: sería un control sin efecto, ya que ningún cálculo de este módulo lo usaría.

**Sin columna sensible, verificado.** La ficha de este informe solo pide RFC, nombre y
número de empleado — a diferencia de B-01/B-02/B-04/B-05, que sí reportan CURP y/o NSS. Este
módulo no las trae ni las declara, así que ninguna `Columna` de `_COLUMNAS` lleva
`sensible=True`. No es un descuido: es la ausencia de datos personales que la propia ficha
dicta para este informe.

**Cero N+1 (regla 11).** El universo se obtiene de `app.informes.universo_nomina.universo()`
(una sola consulta) y las deducciones del rango con una segunda consulta agregada
(`_deducciones_por_comprobante`, `GROUP BY comprobante_id, tipo_deduccion, clave` — análogo a
B-02.R1 "sumar, no sobrescribir" para el caso, raro pero permitido por el esquema, de dos
nodos de deducción con el mismo `(tipo, clave)` en el mismo CFDI). Ninguna consulta se hace
por préstamo ni por periodo.

**Sin `round()` ni `quantize()`** (el redondeo lo hace `app.informes.excel` al escribir la
celda). `Decimal` de punta a punta.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import catalogos, periodos, universo_nomina
from app.informes.base import Bandera, Columna, ResultadoInforme
from app.models.empresa import Empresa
from app.models.nomina import NominaDeduccion

CLAVE = "B-07"
NOMBRE = "Cartera de préstamos y descuentos recurrentes"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por préstamo o descuento recurrente de cada empleado (rfc, tipo de deducción, "
    "clave). El CFDI no contiene el saldo, solo el descuento del periodo, así que el valor de "
    "este informe está en el control de continuidad: detecta un descuento que se detuvo sin "
    "liquidarse."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Ver la constante homónima de `app.informes.b02_conceptos_patron`: mismo razonamiento
(todo el grupo B declara `("N",)`) y mismo consumidor (el pre-vuelo del ETL en
`app.worker.tasks._generar_informe_async`)."""

_CERO = Decimal("0")

_MINIMO_AMORTIZACION_MODIFICADA = 4
"""Mínimo de descuentos en la serie para evaluar B-07.R3. Con menos de dos por mitad, la
moda de cada mitad es casi siempre un dato aislado (cuenta 1), y comparar dos datos aislados
no distingue un cambio sostenido de amortización de un ajuste puntual."""


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango, sobre `nomina.fecha_pago`.")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    tipos_deduccion: list[str] | None = Field(
        None, description="Claves de `c_TipoDeduccion` a incluir (p. ej. `009` Infonavit); `None` incluye todas."
    )
    incluir_cancelados: bool = Field(False, description="Por defecto solo vigentes (R-T1).")
    enmascarar_datos_personales: bool = Field(
        True,
        description=(
            "Sin efecto en este informe: la ficha de B-07 no pide CURP ni NSS, así que no hay "
            "ninguna columna que este informe marque `sensible=True` (ver docstring del módulo). "
            "Se conserva el parámetro por consistencia con el resto del grupo B."
        ),
    )


@dataclass(slots=True)
class _ParametrosUniverso:
    """Adaptador local a `universo_nomina.ParametrosUniverso`. B-07 no expone `tipo_nomina`
    al usuario: un préstamo se descuenta igual en nómina ordinaria o extraordinaria, y
    filtrar por tipo produciría huecos falsos en la continuidad (mismo razonamiento que
    `b04_matriz_empleado_periodo._ParametrosUniverso`)."""

    fecha_desde: date
    fecha_hasta: date
    incluir_cancelados: bool
    tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"


# Ninguna columna es `sensible=True` (ver docstring del módulo): la ficha de B-07 no pide
# CURP ni NSS.
_COLUMNAS: tuple[tuple[str, str, bool], ...] = (
    ("RFC empleado", "texto", False),
    ("Nombre empleado", "texto", False),
    ("Núm. empleado", "texto", False),
    ("Tipo deducción", "texto", False),
    ("Clave", "texto", False),
    ("Descripción SAT", "texto", False),
    ("Núm. de descuentos", "entero", False),
    ("Total descontado", "monto", False),
    ("Descuento modal", "monto", False),
    ("Descuento promedio", "monto", False),
    ("Primer descuento", "fecha", False),
    ("Último descuento", "fecha", False),
    ("Continuidad", "texto", False),
)


def _columnas() -> list[Columna]:
    return [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS]  # type: ignore[arg-type]


async def _deducciones_por_comprobante(
    db: AsyncSession, ids: list[int], tipos_deduccion: list[str] | None
) -> dict[tuple[int, str, str], Decimal]:
    """Suma por `(comprobante_id, tipo_deduccion, clave)`: una sola consulta agregada para
    todo el universo (regla 11: cero N+1). El `SUM` en la BD implementa el análogo de
    B-02.R1 ("sumar, no sobrescribir") para el caso de dos nodos de deducción con el mismo
    `(tipo, clave)` en el mismo CFDI: el esquema Nómina 1.2 lo permite, aunque en la práctica
    sea raro para deducciones."""
    resultado: dict[tuple[int, str, str], Decimal] = {}
    if not ids:
        return resultado

    condiciones: list[Any] = [NominaDeduccion.comprobante_id.in_(ids)]
    if tipos_deduccion:
        condiciones.append(NominaDeduccion.tipo_deduccion.in_(tipos_deduccion))

    filas = await db.execute(
        select(
            NominaDeduccion.comprobante_id,
            NominaDeduccion.tipo_deduccion,
            func.coalesce(NominaDeduccion.clave, "").label("clave"),
            func.sum(NominaDeduccion.importe).label("importe"),
        )
        .where(*condiciones)
        .group_by(NominaDeduccion.comprobante_id, NominaDeduccion.tipo_deduccion, NominaDeduccion.clave)
    )
    for comprobante_id, tipo, clave, importe in filas:
        valor = importe if isinstance(importe, Decimal) else Decimal(str(importe))
        resultado[(int(comprobante_id), str(tipo), str(clave))] = valor
    return resultado


def _modal(valores: Sequence[Decimal]) -> Decimal:
    """El valor más frecuente de la serie (ver docstring del módulo). Desempate por el
    importe MAYOR: una amortización pactada suele ser el valor alto, no el ajuste."""
    conteo = Counter(valores)
    return max(conteo.items(), key=lambda par: (par[1], par[0]))[0]


def _continuidad(fechas: Sequence[date], eje: Sequence[periodos.Corte]) -> tuple[str | None, list[str]]:
    """B-07.R1: clasifica la continuidad de un grano contra el eje teórico de periodos.
    Devuelve `(clasificación, huecos)`; `huecos` solo es no vacío cuando la clasificación es
    `INTERRUMPIDO`. `None` si `fechas` no se puede ubicar en el eje (eje vacío)."""
    indices = sorted({periodos.asignar_a_corte(eje, fecha)[0] for fecha in fechas})
    if not indices or indices[0] < 0:
        return None, []

    primero, ultimo = indices[0], indices[-1]
    faltantes = sorted(set(range(primero + 1, ultimo)) - set(indices))
    if faltantes:
        return "INTERRUMPIDO", [eje[i].etiqueta for i in faltantes]
    if ultimo < len(eje) - 1:
        return "CONCLUIDO", []
    return "CONTINUO", []


def _amortizacion_modificada(
    serie: Sequence[tuple[date, Decimal]],
) -> tuple[Decimal, date, date, Decimal, date, date] | None:
    """B-07.R3: compara la moda de la primera mitad de la serie (ordenada por fecha) contra
    la segunda. `None` si no hay suficientes datos o si la moda no cambió. Si cambió, devuelve
    `(modal_fase_1, inicio_1, fin_1, modal_fase_2, inicio_2, fin_2)`."""
    if len(serie) < _MINIMO_AMORTIZACION_MODIFICADA:
        return None
    mitad = len(serie) // 2
    primera, segunda = serie[:mitad], serie[mitad:]
    modal_1 = _modal([importe for _, importe in primera])
    modal_2 = _modal([importe for _, importe in segunda])
    if modal_1 == modal_2:
        return None
    return modal_1, primera[0][0], primera[-1][0], modal_2, segunda[0][0], segunda[-1][0]


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=_columnas(), aviso="La empresa no existe.")

    p_universo = _ParametrosUniverso(fecha_desde=p.fecha_desde, fecha_hasta=p.fecha_hasta, incluir_cancelados=p.incluir_cancelados)
    filas_universo = list((await db.execute(universo_nomina.universo(empresa_id, rfc_empresa, p_universo))).all())
    # Se resuelve ANTES del retorno temprano (mismo criterio que B-01/B-02/B-04): si el ETL
    # falló en TODOS los CFDI del rango, la hoja Datos sale vacía y esta bandera es el único
    # rastro de que había nómina que reportar.
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, rfc_empresa, p_universo)

    if not filas_universo:
        return ResultadoInforme(
            columnas=_columnas(),
            banderas=banderas_fuera,
            aviso="Sin CFDI de nómina en el rango solicitado.",
        )

    ids = [comprobante.comprobante_id for comprobante, *_ in filas_universo]
    importes_por_concepto = await _deducciones_por_comprobante(db, ids, p.tipos_deduccion)

    banderas: list[Bandera] = list(banderas_fuera)

    if not importes_por_concepto:
        return ResultadoInforme(
            columnas=_columnas(),
            banderas=banderas,
            aviso="Sin descuentos recurrentes en el rango solicitado.",
        )

    # `fecha_pago` y `rfc_receptor` de cada comprobante del universo, para ubicar cada
    # concepto agregado en su grano y en el eje de periodos.
    identidad_por_cid: dict[int, tuple[date | None, str]] = {
        comprobante.comprobante_id: (nomina.fecha_pago, comprobante.rfc_receptor) for comprobante, nomina, _receptor, _totales, _detalle in filas_universo
    }

    # Identidad del empleado (nombre, núm. de empleado): última fotografía por RFC, igual
    # criterio que B-04/B-05 (`filas_universo` viene ordenado por `fecha_pago` ascendente,
    # mismo `order_by` de `universo_nomina.universo`).
    identidad_empleado: dict[str, tuple[str | None, str | None]] = {}
    ultima_fecha_por_rfc: dict[str, date] = {}
    for comprobante, nomina, receptor, _totales, detalle in filas_universo:
        rfc = comprobante.rfc_receptor
        fecha = nomina.fecha_pago
        if fecha is None:
            continue
        if rfc not in ultima_fecha_por_rfc or fecha >= ultima_fecha_por_rfc[rfc]:
            ultima_fecha_por_rfc[rfc] = fecha
            identidad_empleado[rfc] = (receptor.num_empleado if receptor else None, detalle.nombre_receptor if detalle else None)

    # Eje teórico de periodos (B-07.R1), compartido con B-04: se construye una sola vez para
    # todo el informe con la periodicidad dominante del universo. Si no hay ninguna
    # periodicidad reconocida, no se inventa clasificación: la columna queda en `None` y se
    # emite una sola bandera de informe.
    periodicidad = periodos.periodicidad_dominante([receptor.periodicidad_pago if receptor else None for _, _, receptor, _, _ in filas_universo])
    eje: list[periodos.Corte] | None = None
    if periodicidad is None:
        banderas.append(
            Bandera(
                clave="CONTINUIDAD_INDETERMINADA",
                severidad="alta",
                ambito="informe",
                mensaje=(
                    "Ninguna `nomina_receptor.periodicidad_pago` del rango es una periodicidad "
                    "reconocida (02/03/04/05/06); la columna Continuidad no se pudo clasificar "
                    "para ningún préstamo o descuento recurrente."
                ),
            )
        )
    else:
        # Ancla para periodicidades de paso fijo (02/03): el primer `fecha_pago` observado
        # en el universo (`construir_eje` la ignora para periodicidades de día fijo).
        fechas_pago = [nomina.fecha_pago for _, nomina, _, _, _ in filas_universo if nomina.fecha_pago is not None]
        ancla = min(fechas_pago) if fechas_pago else None
        eje = periodos.construir_eje(periodicidad, p.fecha_desde, p.fecha_hasta, primer_corte_observado=ancla)

    # Agrupa por el grano del informe: (rfc_receptor, tipo_deduccion, clave). Cada entrada es
    # ya el importe sumado del comprobante (fase de `_deducciones_por_comprobante`), así que
    # cada elemento de la lista representa un periodo con descuento, no un nodo XML.
    grano: dict[tuple[str, str, str], list[tuple[date, Decimal]]] = defaultdict(list)
    for (comprobante_id, tipo, clave), importe in importes_por_concepto.items():
        fecha_pago, rfc = identidad_por_cid[comprobante_id]
        if fecha_pago is None:
            continue
        grano[(rfc, tipo, clave)].append((fecha_pago, importe))

    filas: list[list[Any]] = []
    for rfc, tipo, clave in sorted(grano):
        serie = sorted(grano[(rfc, tipo, clave)], key=lambda par: par[0])
        fechas = [fecha for fecha, _ in serie]
        importes = [importe for _, importe in serie]

        num_empleado, nombre = identidad_empleado.get(rfc, (None, None))
        modal = _modal(importes)
        total = sum(importes, _CERO)
        promedio = total / Decimal(len(importes))

        continuidad: str | None = None
        if eje is not None:
            continuidad, huecos = _continuidad(fechas, eje)
            if continuidad == "INTERRUMPIDO":
                banderas.append(
                    Bandera(
                        clave="DESCUENTO_INTERRUMPIDO",
                        severidad="alta",
                        ambito=f"rfc:{rfc}|deduccion:{tipo}/{clave}",
                        mensaje=(
                            f"El descuento se detuvo sin liquidarse en: {', '.join(huecos)}. "
                            "Es dinero que la empresa dejó de recuperar en esos periodos."
                        ),
                    )
                )

        cambio = _amortizacion_modificada(serie)
        if cambio is not None:
            modal_1, inicio_1, fin_1, modal_2, inicio_2, fin_2 = cambio
            banderas.append(
                Bandera(
                    clave="AMORTIZACION_MODIFICADA",
                    severidad="baja",
                    ambito=f"rfc:{rfc}|deduccion:{tipo}/{clave}",
                    mensaje=(
                        f"El descuento modal cambió de {modal_1} ({inicio_1} a {fin_1}) a {modal_2} "
                        f"({inicio_2} a {fin_2}); es lo esperado en un crédito Infonavit al actualizarse "
                        "el factor de descuento, no necesariamente un error."
                    ),
                )
            )

        filas.append(
            [
                rfc,
                nombre,
                num_empleado,
                tipo,
                clave or None,
                catalogos.descripcion("D", tipo),
                len(serie),
                total,
                modal,
                promedio,
                fechas[0],
                fechas[-1],
                continuidad,
            ]
        )

    return ResultadoInforme(columnas=_columnas(), filas=filas, banderas=banderas)
