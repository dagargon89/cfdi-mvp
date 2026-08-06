"""B-05 · Acumulado anual por empleado (§B-05 del documento fuente).

**Propósito.** Papel de trabajo del cálculo anual del ISR (art. 97 LISR) y base de la
constancia de percepciones que el patrón entrega al trabajador. A diferencia de B-01/B-02
(una fila por CFDI) y B-04 (una fila por empleado × periodo), aquí una fila es un
`(rfc_receptor, ejercicio)`: el ejercicio completo, consolidado.

**Por qué su exactitud importa más que la de los otros informes del grupo.** Un importe mal
acumulado aquí no se queda en el Excel: viaja a la constancia de percepciones, y de ahí a la
declaración anual del trabajador. Un CFDI contado dos veces no es un error de reporte, es un
ingreso duplicado que el empleado declara ante el SAT.

**B-05.R1 — Resolución de sustituciones, la regla más delicada de este informe.** Un CFDI de
nómina cancelado y sustituido debe contar **una** vez: se toma el sustituto, se descarta el
sustituido. La cadena se resuelve por `cfdi_relacionado` con `tipo_relacion='04'`: se obtienen
los `uuid_relacionado` que los comprobantes del universo declaran con esa relación, y se
excluye del acumulado cualquier comprobante cuyo propio UUID caiga en ese conjunto — sin
importar su estatus. Si el sustituido no está en la base (nunca se descargó, o quedó fuera
del ejercicio), no hay nada que excluir y el acumulado ya es correcto.

Esta exclusión se aplica **siempre**, independientemente de `incluir_cancelados`. La razón es
que la regla protege exactamente el caso en el que el estatus por sí solo NO basta: un
sustituido cuyo `estatus` local todavía no se ha re-verificado contra el SAT (sigue
`no_verificado`, o incluso `vigente` si la corrida de verificación no ha llegado a él) pasaría
cualquier filtro basado solo en `estatus`, y las dos versiones —la buena y la mala— se
sumarían las dos. La única señal confiable de que un comprobante fue reemplazado es la
relación `tipo_relacion='04'` que el sustituto declara, no el estatus del sustituido.

**B-05.R3 — Multipatrón.** Si el mismo `rfc_receptor` aparece con dos `rfc_emisor` distintos
en el ejercicio (después de resolver R1), el cálculo anual es incompleto por construcción:
el patrón que genera este informe solo ve una parte de los ingresos del empleado. Se emite
`MULTI_PATRON` y el acumulado se conserva (no se descarta el empleado): es mejor un total
parcial con la advertencia visible que ningún total.

**Por qué el universo NO filtra por `rfc_emisor == rfc_empresa`, a diferencia de B-01/B-02/
B-04.** Esos tres informes reportan CFDI del patrón hacia sus propios empleados y acotan el
universo a "emitidos por la empresa" (`app.informes.universo_nomina.universo`). B-05 existe
para detectar precisamente el caso en que ese supuesto no se sostiene (R3): un empleado que
cobra de más de un RFC dentro de los datos de esta empresa. Filtrar por `rfc_emisor` haría
invisible la mitad del problema que esta regla existe para señalar. Por esa misma razón este
módulo no reutiliza `universo_nomina.universo()` (que sí filtra por `rfc_emisor`); construye
su propia consulta, acotada por `empresa_id` y por **ejercicio** (`YEAR(fecha_pago)`), no por
`fecha_desde`/`fecha_hasta`.

**Identidad del empleado: del CFDI más reciente, y con el nombre correcto.** Los campos de
identidad (columna 2) salen del CFDI con `fecha_pago` máxima del ejercicio, no del primero:
si el empleado cambió de puesto o departamento a media año, interesa su último estado. El
nombre se toma de `comprobante_detalle.nombre_receptor` — a diferencia de B-01/B-02, que por
no tener otra fuente usan `comprobante.razon_social_emisor` (la razón social del **emisor**,
no del empleado) con una etiqueta "Nombre empleado" que promete algo que no es (defecto que
B-04 ya señaló y evitó omitiendo la columna). Aquí sí existe el campo correcto y se usa.

**SBC y SDI son promedios ponderados por días pagados**, no promedios simples
(`Σ(valor × días) / Σ días`, con guarda de división por cero): un periodo de 5 días pesa
menos que uno de 15 en el promedio del ejercicio.

**Gravado y exento se recalculan de los nodos, no del encabezado.** A diferencia de B-01/B-02
(que reportan `nomina_totales.total_gravado/total_exento` tal cual los declara el CFDI), aquí
se suma `NominaPercepcion.importe_gravado`/`importe_exento` directamente — mismo criterio que
`app.informes.identidades_b00`: es lo que se puede verificar contra los nodos, y una constancia
fiscal no debe heredar sin cotejar un descuadre del encabezado que la identidad B-00 #4/#5 ya
sabe detectar.

**Alcance.** Se implementan las columnas 1–10 y 12–23 del documento fuente. La columna 11
("Gravado ordinario") necesita la marca `es_ingreso_ordinario` de una tabla de configuración
de la fase 3 (§3.1), y las columnas 24–26 (ISR anual teórico, diferencia, sujeto a cálculo
anual) necesitan la tarifa de ISR — ninguna de las dos existe todavía. No se declaran columnas
ni parámetros para ellas: una columna vacía en un papel de trabajo fiscal es peor que su
ausencia, porque quien lo revise no puede distinguir "cero" de "no calculado".

**Sin `round()` ni `quantize()`** (el redondeo lo hace `app.informes.excel` al escribir la
celda). `Decimal` de punta a punta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes.base import Bandera, Columna, ResultadoInforme
from app.informes.identidades_b00 import CLAVE_TIPO_DEDUCCION_ISR
from app.models.cfdi_detalle import CfdiRelacionado, ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.empresa import Empresa
from app.models.enums import EstatusCfdi
from app.models.nomina import Nomina, NominaDeduccion, NominaOtroPago, NominaPercepcion, NominaReceptor, NominaTotales

CLAVE = "B-05"
NOMBRE = "Acumulado anual por empleado"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por empleado y ejercicio: el papel de trabajo del cálculo anual del ISR (art. "
    "97 LISR) y la base de la constancia de percepciones. Resuelve sustituciones (un CFDI "
    "cancelado y reemplazado cuenta una vez) y avisa cuando el mismo empleado cobra de más "
    "de un patrón en el ejercicio."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Ver la constante homónima de `app.informes.b02_conceptos_patron`: mismo razonamiento
(todo el grupo B declara `("N",)`) y mismo consumidor (el pre-vuelo del ETL en
`app.worker.tasks._generar_informe_async`)."""

_CERO = Decimal("0")

_CLAVE_DEDUCCION_ISR = CLAVE_TIPO_DEDUCCION_ISR
"""`"002"` (catálogo `c_TipoDeduccion`), reexportado de `identidades_b00` para no declarar
dos veces la misma clave."""

_CLAVE_DEDUCCION_IMSS = "001"
"""Clave del catálogo `c_TipoDeduccion` de "Seguridad social" (columna 17, IMSS retenido)."""

_CLAVE_DEDUCCION_FONDO_AHORRO = "004"
"""Clave del catálogo `c_TipoDeduccion` de "Aportaciones a Fondo de ahorro" (columna 18)."""

_CLAVE_DEDUCCION_INFONAVIT = "009"
"""Clave del catálogo `c_TipoDeduccion` de "Descuento por incapacidad... Infonavit" — en la
práctica, el descuento de crédito Infonavit (columna 19)."""

_CLAVE_OTRO_PAGO_SUBSIDIO = "002"
"""Clave del catálogo `c_TipoOtroPago` de "Subsidio para el empleo efectivamente entregado al
trabajador" (columnas 15–16). Mismo valor que `b01_catalogo_sat._CLAVE_OTRO_PAGO_SUBSIDIO`,
declarado aparte a propósito: es una clave de catálogo, no lógica compartida entre módulos."""

_TIPO_RELACION_SUSTITUCION = "04"
"""`tipo_relacion` del nodo `CfdiRelacionado` que declara "Este CFDI sustituye a otro
anterior" (catálogo `c_TipoRelacion` del SAT). Es la única señal de la que B-05.R1 depende."""


class Parametros(BaseModel):
    ejercicio: int = Field(description="Año fiscal sobre `YEAR(nomina.fecha_pago)`. El grano del informe es (empleado, ejercicio).")
    incluir_cancelados: bool = Field(
        False,
        description=(
            "Un CFDI cancelado que no fue sustituido (B-05.R1) es un recibo huérfano: no representa "
            "un pago que subsista. Por defecto se excluye del acumulado; con este parámetro en True "
            "se incluye, marcado con `COMPROBANTE_CANCELADO`. Los cancelados que SÍ fueron sustituidos "
            "se excluyen siempre, sin importar este parámetro (ver B-05.R1 en el docstring del módulo)."
        ),
    )
    enmascarar_datos_personales: bool = Field(
        True,
        description=(
            "Enmascara CURP (spec §8). Lo aplica el motor de informes "
            "(`app.informes.excel.escribir_libro`) sobre las columnas que esta consulta marca "
            "como `sensible=True`, no esta consulta directamente."
        ),
    )


# Columnas 1 a 10 (identidad, fechas del ejercicio y los tres totales del encabezado).
_COLUMNAS_UNO_A_DIEZ: tuple[tuple[str, str, bool], ...] = (
    ("Ejercicio", "entero", False),
    ("RFC empleado", "texto", False),
    ("CURP", "texto", True),
    ("Nombre empleado", "texto", False),
    ("Núm. empleado", "texto", False),
    ("Departamento", "texto", False),
    ("Puesto", "texto", False),
    ("Fecha inicio relación laboral", "fecha", False),
    ("Fecha primer pago del ejercicio", "fecha", False),
    ("Fecha último pago del ejercicio", "fecha", False),
    ("Núm. de CFDI", "entero", False),
    ("Días pagados del ejercicio", "decimal", False),
    ("Total percepciones", "monto", False),
    ("Total gravado", "monto", False),
    ("Total exento", "monto", False),
)

# Columnas 12 a 23 (la 11 queda fuera de alcance: ver docstring del módulo).
_COLUMNAS_DOCE_A_VEINTITRES: tuple[tuple[str, str, bool], ...] = (
    ("Ingreso por separación", "monto", False),
    ("Ingreso por jubilación", "monto", False),
    ("ISR retenido", "monto", False),
    ("Subsidio causado", "monto", False),
    ("Subsidio entregado en efectivo", "monto", False),
    ("IMSS retenido", "monto", False),
    ("Aportaciones a fondo de ahorro", "monto", False),
    ("Descuentos Infonavit", "monto", False),
    ("Otras deducciones", "monto", False),
    ("Neto pagado", "monto", False),
    ("SBC promedio ponderado", "monto", False),
    ("SDI promedio ponderado", "monto", False),
)

_COLUMNAS: tuple[tuple[str, str, bool], ...] = _COLUMNAS_UNO_A_DIEZ + _COLUMNAS_DOCE_A_VEINTITRES


def _columnas() -> list[Columna]:
    return [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS]  # type: ignore[arg-type]


def _a_decimal(valor: Decimal | float | None) -> Decimal:
    """`Numeric` puede llegar como `Decimal` o `float` según el atributo mapeado; nunca se
    opera en binario (mismo patrón que `identidades_b00._dec`)."""
    if valor is None:
        return _CERO
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


@dataclass(slots=True)
class _Acumulador:
    """Lo que se va sumando por `rfc_receptor` a lo largo de la iteración del universo ya
    resuelto (post B-05.R1). Un campo por columna agregada; los campos de identidad (fecha de
    inicio, nombre, etc.) se resuelven aparte porque no se suman."""

    uuids: set[str]
    dias_pagados: Decimal = _CERO
    total_percepciones: Decimal = _CERO
    total_gravado: Decimal = _CERO
    total_exento: Decimal = _CERO
    total_separacion: Decimal = _CERO
    total_jubilacion: Decimal = _CERO
    isr_retenido: Decimal = _CERO
    subsidio_causado: Decimal = _CERO
    subsidio_entregado: Decimal = _CERO
    imss_retenido: Decimal = _CERO
    fondo_ahorro: Decimal = _CERO
    infonavit: Decimal = _CERO
    total_deducciones: Decimal = _CERO
    neto_pagado: Decimal = _CERO
    suma_sbc_dias: Decimal = _CERO
    suma_sdi_dias: Decimal = _CERO
    fecha_primer_pago: date | None = None
    fecha_ultimo_pago: date | None = None
    fecha_inicio_rel_laboral: date | None = None
    rfc_emisores: set[str] = field(default_factory=set)


async def _sustituidos(db: AsyncSession, ids_universo: list[int]) -> set[str]:
    """B-05.R1: los `uuid_relacionado` que los comprobantes del universo declaran con
    `tipo_relacion='04'` — el conjunto de UUID que deben excluirse del acumulado porque un
    sustituto (dentro del mismo universo) ya los reemplazó.

    Se consulta sobre `CfdiRelacionado.comprobante_id IN ids_universo`, es decir, la relación
    la declara el **sustituto**; `uuid_relacionado` es el UUID del **sustituido**, que puede o
    no tener su propia fila en `comprobantes` (si nunca se descargó, no hay nada que excluir y
    el acumulado ya es correcto — no es un error, es la ausencia de dato que se documenta en
    el módulo)."""
    if not ids_universo:
        return set()
    filas = await db.execute(
        select(CfdiRelacionado.uuid_relacionado).where(
            CfdiRelacionado.comprobante_id.in_(ids_universo),
            CfdiRelacionado.tipo_relacion == _TIPO_RELACION_SUSTITUCION,
        )
    )
    return {str(uuid_relacionado) for uuid_relacionado in filas.scalars().all()}


async def _sumas_por_comprobante(db: AsyncSession, ids: list[int]) -> dict[int, dict[str, Decimal]]:
    """Los agregados por comprobante que no vienen ya resueltos en el encabezado (gravado,
    exento, ISR, IMSS, fondo de ahorro, Infonavit, total de deducciones, subsidio) — una sola
    consulta agregada por tabla hija, para todo el universo del ejercicio (regla 11: cero
    N+1, nunca un `SELECT` por comprobante)."""
    sumas: dict[int, dict[str, Decimal]] = {}
    if not ids:
        return sumas

    percepciones = await db.execute(
        select(
            NominaPercepcion.comprobante_id,
            func.sum(NominaPercepcion.importe_gravado).label("gravado"),
            func.sum(NominaPercepcion.importe_exento).label("exento"),
        )
        .where(NominaPercepcion.comprobante_id.in_(ids))
        .group_by(NominaPercepcion.comprobante_id)
    )
    for comprobante_id, gravado, exento in percepciones:
        sumas.setdefault(int(comprobante_id), {})["gravado"] = _a_decimal(gravado)
        sumas[int(comprobante_id)]["exento"] = _a_decimal(exento)

    deducciones = await db.execute(
        select(
            NominaDeduccion.comprobante_id,
            NominaDeduccion.tipo_deduccion,
            func.sum(NominaDeduccion.importe).label("importe"),
        )
        .where(NominaDeduccion.comprobante_id.in_(ids))
        .group_by(NominaDeduccion.comprobante_id, NominaDeduccion.tipo_deduccion)
    )
    clave_a_campo = {
        _CLAVE_DEDUCCION_ISR: "isr",
        _CLAVE_DEDUCCION_IMSS: "imss",
        _CLAVE_DEDUCCION_FONDO_AHORRO: "fondo_ahorro",
        _CLAVE_DEDUCCION_INFONAVIT: "infonavit",
    }
    for comprobante_id, tipo_deduccion, importe in deducciones:
        cid = int(comprobante_id)
        fila = sumas.setdefault(cid, {})
        importe_dec = _a_decimal(importe)
        fila["deducciones"] = fila.get("deducciones", _CERO) + importe_dec
        campo = clave_a_campo.get(str(tipo_deduccion))
        if campo is not None:
            fila[campo] = fila.get(campo, _CERO) + importe_dec

    otros_pagos = await db.execute(
        select(
            NominaOtroPago.comprobante_id,
            func.sum(NominaOtroPago.subsidio_causado).label("subsidio_causado"),
            func.sum(NominaOtroPago.importe).label("subsidio_entregado"),
        )
        .where(NominaOtroPago.comprobante_id.in_(ids), NominaOtroPago.tipo_otro_pago == _CLAVE_OTRO_PAGO_SUBSIDIO)
        .group_by(NominaOtroPago.comprobante_id)
    )
    for comprobante_id, subsidio_causado, subsidio_entregado in otros_pagos:
        cid = int(comprobante_id)
        fila = sumas.setdefault(cid, {})
        fila["subsidio_causado"] = _a_decimal(subsidio_causado)
        fila["subsidio_entregado"] = _a_decimal(subsidio_entregado)

    return sumas


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=_columnas(), aviso="La empresa no existe.")

    # Universo por ejercicio (YEAR(fecha_pago) = p.ejercicio), no por rango de fechas — y sin
    # filtrar por `rfc_emisor` (ver docstring del módulo: B-05.R3 depende de verlos todos).
    # Orden ascendente por fecha_pago: permite resolver "identidad del CFDI más reciente"
    # sobrescribiendo en el orden de iteración (mismo patrón que B-04).
    filas_universo = list(
        (
            await db.execute(
                select(Comprobante, Nomina, NominaReceptor, NominaTotales, ComprobanteDetalle)
                .join(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
                .outerjoin(NominaReceptor, NominaReceptor.comprobante_id == Comprobante.comprobante_id)
                .outerjoin(NominaTotales, NominaTotales.comprobante_id == Comprobante.comprobante_id)
                .outerjoin(ComprobanteDetalle, ComprobanteDetalle.comprobante_id == Comprobante.comprobante_id)
                .where(
                    Comprobante.empresa_id == empresa_id,
                    Comprobante.tipo_comprobante == "N",
                    func.extract("year", Nomina.fecha_pago) == p.ejercicio,
                )
                .order_by(Comprobante.rfc_receptor, Nomina.fecha_pago, Comprobante.comprobante_id)
            )
        ).all()
    )

    if not filas_universo:
        return ResultadoInforme(columnas=_columnas(), aviso=f"Sin CFDI de nómina en el ejercicio {p.ejercicio}.")

    ids_universo = [fila[0].comprobante_id for fila in filas_universo]

    # B-05.R1: se resuelve ANTES de acumular nada, y se aplica siempre — no depende de
    # `incluir_cancelados` (ver docstring del módulo: protege justo el caso en el que el
    # estatus del sustituido todavía no refleja la cancelación).
    sustituidos = await _sustituidos(db, ids_universo)

    banderas: list[Bandera] = []
    filas_resueltas: list[Any] = []
    for fila in filas_universo:
        comprobante = fila[0]
        if comprobante.uuid in sustituidos:
            banderas.append(
                Bandera(
                    clave="CFDI_SUSTITUIDO",
                    severidad="baja",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=(
                        "Excluido del acumulado: otro CFDI del ejercicio lo declara sustituido "
                        "(`cfdi_relacionado.tipo_relacion='04'`). Su sustituto ya cuenta este ingreso "
                        "(B-05.R1); incluir ambos duplicaría el ingreso anual del empleado."
                    ),
                )
            )
            continue
        if comprobante.estatus == EstatusCfdi.CANCELADO and not p.incluir_cancelados:
            banderas.append(
                Bandera(
                    clave="COMPROBANTE_CANCELADO",
                    severidad="alta",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=(
                        "El CFDI está cancelado ante el SAT y no fue sustituido por otro; se excluyó "
                        "del acumulado porque `incluir_cancelados=False`. No representa un pago vigente."
                    ),
                )
            )
            continue
        filas_resueltas.append(fila)

    if not filas_resueltas:
        return ResultadoInforme(
            columnas=_columnas(),
            banderas=banderas,
            aviso=f"Sin CFDI de nómina vigentes en el ejercicio {p.ejercicio} tras resolver sustituciones y cancelados.",
        )

    ids_resueltos = [fila[0].comprobante_id for fila in filas_resueltas]
    sumas_por_cid = await _sumas_por_comprobante(db, ids_resueltos)

    acumuladores: dict[str, _Acumulador] = {}
    identidad: dict[str, tuple[str | None, str | None, str | None, str | None, str | None]] = {}

    for comprobante, nomina, receptor, totales, detalle in filas_resueltas:
        rfc = comprobante.rfc_receptor
        acc = acumuladores.setdefault(rfc, _Acumulador(uuids=set()))
        sumas = sumas_por_cid.get(comprobante.comprobante_id, {})

        acc.uuids.add(comprobante.uuid)
        acc.rfc_emisores.add(comprobante.rfc_emisor)
        acc.dias_pagados += _a_decimal(nomina.num_dias_pagados)
        acc.total_percepciones += _a_decimal(nomina.total_percepciones)
        acc.total_gravado += sumas.get("gravado", _CERO)
        acc.total_exento += sumas.get("exento", _CERO)
        acc.total_separacion += _a_decimal(totales.total_separacion_indemnizacion if totales else None)
        acc.total_jubilacion += _a_decimal(totales.total_jubilacion_pension_retiro if totales else None)
        acc.isr_retenido += sumas.get("isr", _CERO)
        acc.subsidio_causado += sumas.get("subsidio_causado", _CERO)
        acc.subsidio_entregado += sumas.get("subsidio_entregado", _CERO)
        acc.imss_retenido += sumas.get("imss", _CERO)
        acc.fondo_ahorro += sumas.get("fondo_ahorro", _CERO)
        acc.infonavit += sumas.get("infonavit", _CERO)
        acc.total_deducciones += sumas.get("deducciones", _CERO)
        acc.neto_pagado += _a_decimal(comprobante.total)

        sbc = _a_decimal(receptor.salario_base_cot_apor if receptor else None)
        sdi = _a_decimal(receptor.salario_diario_integrado if receptor else None)
        dias = _a_decimal(nomina.num_dias_pagados)
        acc.suma_sbc_dias += sbc * dias
        acc.suma_sdi_dias += sdi * dias

        if nomina.fecha_pago is not None:
            if acc.fecha_primer_pago is None or nomina.fecha_pago < acc.fecha_primer_pago:
                acc.fecha_primer_pago = nomina.fecha_pago
            if acc.fecha_ultimo_pago is None or nomina.fecha_pago >= acc.fecha_ultimo_pago:
                acc.fecha_ultimo_pago = nomina.fecha_pago

        fecha_inicio = receptor.fecha_inicio_rel_laboral if receptor else None
        if fecha_inicio is not None and (acc.fecha_inicio_rel_laboral is None or fecha_inicio < acc.fecha_inicio_rel_laboral):
            acc.fecha_inicio_rel_laboral = fecha_inicio

        # Identidad (columna 2): del CFDI más reciente del ejercicio. `filas_resueltas` viene
        # ordenado por `fecha_pago` ascendente (mismo `order_by` de la consulta principal), así
        # que sobrescribir en el orden de iteración deja la fotografía más reciente.
        identidad[rfc] = (
            receptor.curp if receptor else None,
            detalle.nombre_receptor if detalle else None,
            receptor.num_empleado if receptor else None,
            receptor.departamento if receptor else None,
            receptor.puesto if receptor else None,
        )

    # B-05.R3: multipatrón, sobre el acumulado ya resuelto (post R1).
    for rfc, acc in acumuladores.items():
        if len(acc.rfc_emisores) > 1:
            banderas.append(
                Bandera(
                    clave="MULTI_PATRON",
                    severidad="alta",
                    ambito=f"rfc:{rfc}",
                    mensaje=(
                        f"{rfc} tiene CFDI de nómina de {len(acc.rfc_emisores)} RFC emisores distintos "
                        f"en el ejercicio {p.ejercicio} ({', '.join(sorted(acc.rfc_emisores))}); el "
                        "cálculo anual es incompleto por construcción: este informe solo ve una parte "
                        "de sus ingresos."
                    ),
                )
            )

    filas: list[list[Any]] = []
    for rfc in sorted(acumuladores):
        acc = acumuladores[rfc]
        curp, nombre, num_empleado, departamento, puesto = identidad[rfc]

        otras_deducciones = acc.total_deducciones - acc.isr_retenido - acc.imss_retenido - acc.fondo_ahorro - acc.infonavit
        sbc_promedio = (acc.suma_sbc_dias / acc.dias_pagados) if acc.dias_pagados else _CERO
        sdi_promedio = (acc.suma_sdi_dias / acc.dias_pagados) if acc.dias_pagados else _CERO

        filas.append(
            [
                p.ejercicio,
                rfc,
                curp,
                nombre,
                num_empleado,
                departamento,
                puesto,
                acc.fecha_inicio_rel_laboral,
                acc.fecha_primer_pago,
                acc.fecha_ultimo_pago,
                len(acc.uuids),
                acc.dias_pagados,
                acc.total_percepciones,
                acc.total_gravado,
                acc.total_exento,
                acc.total_separacion,
                acc.total_jubilacion,
                acc.isr_retenido,
                acc.subsidio_causado,
                acc.subsidio_entregado,
                acc.imss_retenido,
                acc.fondo_ahorro,
                acc.infonavit,
                otras_deducciones,
                acc.neto_pagado,
                sbc_promedio,
                sdi_promedio,
            ]
        )

    return ResultadoInforme(columnas=_columnas(), filas=filas, banderas=banderas)
