"""B-09 · Recálculo de ISR y subsidio al empleo por recibo (§B-09 del documento fuente).

**Lo que este informe afirma, y lo que no.** Compara el ISR que cada recibo debería tener según
la tarifa que el SAT publica en el Anexo 8 de la RMF contra el que el patrón timbró en el CFDI.
**No dictamina** que una diferencia sea un error: dice que, con la tarifa cargada y confirmada en
este Hub, el número no coincide. Una diferencia real puede venir de varias fuentes legítimas que
este informe no reproduce — el subsidio al empleo (si no está confirmado, este informe ni
siquiera lo calcula: ver la degradación abajo), un periodo irregular (menos o más días que los
nominales de su periodicidad, prorrateado por el art. 175 del Reglamento), o el procedimiento
opcional del art. 174 (ingreso mensual estimado con ajuste posterior), que este informe no
implementa y solo detecta por indicio (Task 4). Lo que este informe **sí** puede afirmar con
certeza es que compara contra la tarifa vigente, y que si el número del patrón no coincide, hay
algo que revisar — no necesariamente un error del proveedor de nómina.

Grano: **una fila por recibo (UUID)**, igual que el resto del universo del grupo B que reporta
CFDI de nómina uno a uno.

Esta tarea (3 del plan) entrega **filas y columnas correctas**: el universo, la base gravable, el
recálculo y las 21 columnas del documento fuente. Las banderas de comparación (`COINCIDE`,
`DIFERENCIA_MAYOR`, `PERIODO_IRREGULAR`, `PERCEPCIONES_EXTRAORDINARIAS`,
`PROCEDIMIENTO_ART174`, `DIFERENCIA_SISTEMATICA`, `ISR_CERO_CON_BASE`) son la tarea 4 y no viven
aquí — la única bandera que esta tarea sí emite es `RECIBO_NO_CALCULABLE` (ver abajo), porque es
la que impide que un solo recibo raro tumbe la corrida completa.

La base gravable son **solo las percepciones ordinarias**
-----------------------------------------------------------
`Σ importe_gravado` de las percepciones cuyo tipo está marcado `es_ingreso_ordinario = true` en
`catalogo_percepcion_marca` **confirmada** — nunca el gravado total del recibo. Un aguinaldo, una
PTU o una prima vacacional no se gravan con la tarifa del periodo (tienen su propio tratamiento),
así que meterlos en la base infla el ISR teórico y produce una acusación falsa contra el patrón.
Ver `_gravado_por_tipo` y `_base_ordinaria`.

La degradación es por partes (§5 del diseño), heredada de `app.informes.configuracion_isr`
--------------------------------------------------------------------------------------------
- **Sin tarifa confirmada** para alguna periodicidad presente en los recibos del rango, o **sin
  alguna marca de percepción confirmada** de los tipos que de verdad aparecen: **no se generan
  filas**, y el `aviso` es literalmente el texto de `configuracion_isr` (nunca reescrito aquí).
  Una base gravable inventada con el gravado total sería peor que ningún informe.
- **Sin el subsidio al empleo** (UMA mensual, factor o tope sin confirmar): el informe **sí se
  genera** — el ISR determinado no depende del subsidio — y solo las tres columnas del subsidio
  (`Subsidio al empleo teórico`, `ISR a retener teórico`, `Subsidio a entregar teórico`, y lo que
  de ellas depende: `Diferencia de subsidio`) quedan vacías.

El recibo con cero días pagados (hueco explícito de esta tarea)
--------------------------------------------------------------------
`tarifa_isr.isr_del_periodo` y `subsidio_del_periodo` lanzan `TarifaInvalida` cuando
`num_dias_pagados <= 0` (una baja el día 1 es un dato real, no un caso imaginario). Esta tarea
**captura** esa excepción por recibo, deja sus columnas de cálculo vacías (`None`, nunca cero: un
cero ahí se leería como "no le tocó ISR", que es un hallazgo distinto de "no se pudo calcular") y
emite una bandera `RECIBO_NO_CALCULABLE` de severidad alta con el mensaje de la excepción — la
corrida completa sigue, no se rompe por un recibo atípico.

**Ningún importe fiscal literal vive en este archivo** (§2.12): la tarifa, la UMA mensual y los
parámetros del subsidio salen de `app.informes.configuracion_isr`, resueltos por fecha y
confirmados. **Todo redondeo a dos decimales con `ROUND_HALF_UP`**, igual que
`app.services.tarifa_isr`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import configuracion_isr, universo_nomina
from app.informes.base import Bandera, Columna, ResultadoInforme
from app.informes.configuracion_isr import ConfiguracionIsr
from app.informes.identidades_b00 import CLAVE_TIPO_DEDUCCION_ISR
from app.models.empresa import Empresa
from app.models.enums import PeriodicidadTarifa
from app.models.nomina import NominaDeduccion, NominaOtroPago, NominaPercepcion
from app.services import tarifa_isr

CLAVE = "B-09"
NOMBRE = "Recálculo de ISR y subsidio al empleo"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por recibo, con el ISR recalculado contra la tarifa que el SAT publica en el "
    "Anexo 8 y puesto al lado del que el patrón timbró. Compara contra la tarifa publicada; no "
    "dictamina — una diferencia puede venir del subsidio, de un periodo irregular o de otro "
    "procedimiento legal (art. 174 del Reglamento)."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Todo el grupo B declara `("N",)`: ver el docstring homónimo de `b02_conceptos_patron`."""

_DOS_DECIMALES = Decimal("0.01")

_CLAVE_OTRO_PAGO_SUBSIDIO = "002"
"""Clave de `c_TipoOtroPago` del "Subsidio para el empleo". Mismo valor y mismo criterio que
`b05_acumulado_anual._CLAVE_OTRO_PAGO_SUBSIDIO`: se declara localmente porque, a diferencia del
ISR (una identidad de B-00 con una sola clave inequívoca), esta constante no tiene todavía un
hogar compartido — no vale la pena crear uno para una constante que dos módulos ya repiten igual."""


def _redondear(valor: Decimal) -> Decimal:
    return valor.quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)


def _dec(valor: object) -> Decimal:
    """`func.sum` puede devolver `Decimal`, `float` o `None` según el dialecto; nunca se compara
    en binario (mismo patrón que `universo_nomina._dec`)."""
    if valor is None:
        return Decimal("0")
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango, sobre `nomina.fecha_pago` (R-T6).")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    incluir_cancelados: bool = Field(False, description="Por defecto solo vigentes (R-T1).")


@dataclass(slots=True)
class _ParametrosUniverso:
    """Adaptador local a `universo_nomina.ParametrosUniverso`. B-09 no expone `tipo_nomina`: el
    ISR se retiene también en nómina extraordinaria (aguinaldo, PTU), así que filtrar por tipo
    escondería justo los recibos que más vale comparar. Mismo patrón que
    `b03_gravado_exento._ParametrosUniverso`."""

    fecha_desde: date
    fecha_hasta: date
    incluir_cancelados: bool
    tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"


# --------------------------------------------------------------------------------------
# Las 21 columnas, en el orden del documento fuente
# --------------------------------------------------------------------------------------

_COLUMNAS: tuple[tuple[str, str], ...] = (
    ("UUID", "texto"),
    ("Fecha pago", "fecha"),
    ("RFC empleado", "texto"),
    ("Periodicidad", "texto"),
    ("Días pagados", "decimal"),
    ("Base gravable", "monto"),
    ("Tarifa aplicada", "texto"),
    ("Renglón de la tarifa", "entero"),
    ("Límite inferior", "monto"),
    ("Excedente", "monto"),
    ("Tasa sobre excedente (%)", "decimal"),
    ("Impuesto marginal", "monto"),
    ("Cuota fija", "monto"),
    ("ISR determinado", "monto"),
    ("Subsidio al empleo teórico", "monto"),
    ("ISR a retener teórico", "monto"),
    ("Subsidio a entregar teórico", "monto"),
    ("ISR retenido en el CFDI", "monto"),
    ("Subsidio en el CFDI", "monto"),
    ("Diferencia de ISR", "monto"),
    ("Diferencia de subsidio", "monto"),
)

(
    _COL_UUID,
    _COL_FECHA_PAGO,
    _COL_RFC_EMPLEADO,
    _COL_PERIODICIDAD,
    _COL_DIAS_PAGADOS,
    _COL_BASE,
    _COL_TARIFA_APLICADA,
    _COL_RENGLON,
    _COL_LIMITE_INFERIOR,
    _COL_EXCEDENTE,
    _COL_TASA,
    _COL_IMPUESTO_MARGINAL,
    _COL_CUOTA_FIJA,
    _COL_ISR_DETERMINADO,
    _COL_SUBSIDIO_TEORICO,
    _COL_ISR_A_RETENER_TEORICO,
    _COL_SUBSIDIO_A_ENTREGAR_TEORICO,
    _COL_ISR_RETENIDO_CFDI,
    _COL_SUBSIDIO_CFDI,
    _COL_DIFERENCIA_ISR,
    _COL_DIFERENCIA_SUBSIDIO,
) = range(len(_COLUMNAS))


def _columnas() -> list[Columna]:
    return [Columna(titulo=titulo, tipo=tipo) for titulo, tipo in _COLUMNAS]  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Datos de la base de datos: universo + agregados, sin N+1 (regla 11)
# --------------------------------------------------------------------------------------


async def _gravado_por_tipo(db: AsyncSession, ids: list[int]) -> dict[int, dict[str, Decimal]]:
    """Gravado por `(comprobante_id, tipo_percepcion)`, una sola consulta agregada para todo el
    universo. Mismo patrón que `b05_acumulado_anual._sumas_por_comprobante`: separar por tipo es
    lo único que permite quedarse después solo con las percepciones ordinarias — B-09 nunca usa
    el gravado total del recibo (ver el docstring del módulo)."""
    if not ids:
        return {}
    resultado: dict[int, dict[str, Decimal]] = {}
    filas = await db.execute(
        select(
            NominaPercepcion.comprobante_id,
            NominaPercepcion.tipo_percepcion,
            func.sum(NominaPercepcion.importe_gravado).label("gravado"),
        )
        .where(NominaPercepcion.comprobante_id.in_(ids))
        .group_by(NominaPercepcion.comprobante_id, NominaPercepcion.tipo_percepcion)
    )
    for comprobante_id, tipo_percepcion, gravado in filas:
        por_tipo = resultado.setdefault(int(comprobante_id), {})
        por_tipo[str(tipo_percepcion)] = _dec(gravado)
    return resultado


async def _isr_y_subsidio_cfdi(db: AsyncSession, ids: list[int]) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    """Lo que el patrón timbró: ISR retenido (`nomina_deduccion` tipo `002`) y subsidio causado
    (`nomina_otro_pago` tipo `002`, campo `subsidio_causado`), una consulta agregada por tabla
    para todo el universo (regla 11)."""
    isr: dict[int, Decimal] = {}
    subsidio: dict[int, Decimal] = {}
    if not ids:
        return isr, subsidio

    filas_isr = await db.execute(
        select(NominaDeduccion.comprobante_id, func.sum(NominaDeduccion.importe))
        .where(NominaDeduccion.comprobante_id.in_(ids), NominaDeduccion.tipo_deduccion == CLAVE_TIPO_DEDUCCION_ISR)
        .group_by(NominaDeduccion.comprobante_id)
    )
    for comprobante_id, importe in filas_isr:
        isr[int(comprobante_id)] = _redondear(_dec(importe))

    filas_subsidio = await db.execute(
        select(NominaOtroPago.comprobante_id, func.sum(NominaOtroPago.subsidio_causado))
        .where(
            NominaOtroPago.comprobante_id.in_(ids),
            NominaOtroPago.tipo_otro_pago == _CLAVE_OTRO_PAGO_SUBSIDIO,
        )
        .group_by(NominaOtroPago.comprobante_id)
    )
    for comprobante_id, importe in filas_subsidio:
        subsidio[int(comprobante_id)] = _redondear(_dec(importe))

    return isr, subsidio


def _es_ordinaria(config: ConfiguracionIsr, tipo: str) -> bool:
    marca = config.marcas.get(tipo)
    return marca is not None and marca.es_ingreso_ordinario


def _base_ordinaria(config: ConfiguracionIsr, por_tipo: dict[str, Decimal]) -> Decimal:
    """B-09: `Σ importe_gravado` de los tipos ordinarios de este recibo. Nunca el gravado total
    (ver el docstring del módulo)."""
    return _redondear(sum((importe for tipo, importe in por_tipo.items() if _es_ordinaria(config, tipo)), Decimal("0")))


# --------------------------------------------------------------------------------------
# La consulta
# --------------------------------------------------------------------------------------


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=_columnas(), aviso="La empresa no existe.")

    p_universo = _ParametrosUniverso(p.fecha_desde, p.fecha_hasta, p.incluir_cancelados)
    filas_universo = list((await db.execute(universo_nomina.universo(empresa_id, rfc_empresa, p_universo))).all())
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, rfc_empresa, p_universo)

    if not filas_universo:
        return ResultadoInforme(
            columnas=_columnas(), banderas=banderas_fuera, aviso="Sin CFDI de nómina en el rango solicitado."
        )

    ids = [fila[0].comprobante_id for fila in filas_universo]
    gravado_por_tipo = await _gravado_por_tipo(db, ids)
    isr_cfdi_por_comprobante, subsidio_cfdi_por_comprobante = await _isr_y_subsidio_cfdi(db, ids)

    # Lo que hace falta resolver en `configuracion_isr`: las periodicidades traducidas (la
    # traducción con `PARA_CFDI` es de este informe, porque es quien lee los recibos) y los
    # tipos de percepción que de verdad aparecen — nunca las 44 claves del catálogo completo.
    periodicidades_presentes: set[PeriodicidadTarifa] = set()
    fecha_representativa_por_ejercicio: dict[int, date] = {}
    for _comprobante, nomina, receptor, _totales, _detalle in filas_universo:
        if nomina.fecha_pago is not None:
            ejercicio = nomina.fecha_pago.year
            actual = fecha_representativa_por_ejercicio.get(ejercicio)
            if actual is None or nomina.fecha_pago > actual:
                fecha_representativa_por_ejercicio[ejercicio] = nomina.fecha_pago
        codigo = receptor.periodicidad_pago if receptor is not None else None
        traducida = tarifa_isr.PARA_CFDI.get(codigo) if codigo is not None else None
        if traducida is not None:
            periodicidades_presentes.add(traducida)

    tipos_presentes: set[str] = {tipo for por_tipo in gravado_por_tipo.values() for tipo in por_tipo}
    periodicidades_ordenadas = sorted(periodicidades_presentes, key=lambda per: per.value)

    # Se resuelve una vez por ejercicio presente (acotado por el calendario, no por el número de
    # recibos: regla 11), con la fecha de pago más reciente de ese ejercicio como referencia para
    # los parámetros del subsidio vigentes por fecha. La tarifa no depende de la fecha dentro del
    # ejercicio, solo del ejercicio y la periodicidad.
    configs: dict[int, ConfiguracionIsr] = {}
    for ejercicio, fecha in fecha_representativa_por_ejercicio.items():
        configs[ejercicio] = await configuracion_isr.resolver(
            db,
            ejercicio=ejercicio,
            en_fecha=fecha,
            periodicidades=periodicidades_ordenadas,
            tipos_presentes=tipos_presentes,
        )

    # La degradación es por partes (§5 del diseño): sin tarifa o sin marcas, nada se genera y el
    # aviso es literalmente el texto de `configuracion_isr` (nunca reescrito aquí). Sin subsidio
    # sí se genera — su texto (`BANDERA_SIN_SUBSIDIO`) se descarta de la lista de bloqueo.
    bloqueantes: list[str] = []
    vistos: set[str] = set()
    for config_ejercicio in configs.values():
        for falta in config_ejercicio.faltantes:
            if falta != configuracion_isr.BANDERA_SIN_SUBSIDIO and falta not in vistos:
                vistos.add(falta)
                bloqueantes.append(falta)
    if bloqueantes:
        return ResultadoInforme(columnas=_columnas(), banderas=banderas_fuera, aviso=" ".join(bloqueantes))

    banderas: list[Bandera] = list(banderas_fuera)
    banderas.extend(universo_nomina.banderas_de_estatus(universo_nomina.comprobantes_y_detalles(filas_universo)))

    filas: list[list[Any]] = []
    for comprobante, nomina, receptor, _totales, _detalle in filas_universo:
        cid = comprobante.comprobante_id
        fecha_pago = nomina.fecha_pago
        ejercicio = fecha_pago.year if fecha_pago is not None else None
        config = configs.get(ejercicio) if ejercicio is not None else None
        codigo = receptor.periodicidad_pago if receptor is not None else None
        periodicidad_tarifa = tarifa_isr.PARA_CFDI.get(codigo) if codigo is not None else None
        dias_pagados = nomina.num_dias_pagados

        base = _base_ordinaria(config, gravado_por_tipo.get(cid, {})) if config is not None else Decimal("0.00")

        renglon: int | None = None
        limite_inferior: Decimal | None = None
        excedente: Decimal | None = None
        tasa: Decimal | None = None
        impuesto_marginal: Decimal | None = None
        cuota_fija: Decimal | None = None
        isr_determinado: Decimal | None = None
        subsidio_teorico: Decimal | None = None
        isr_a_retener_teorico: Decimal | None = None
        subsidio_a_entregar_teorico: Decimal | None = None
        tarifa_aplicada: str | None = None

        if config is not None and periodicidad_tarifa is not None and dias_pagados is not None:
            dias_nominales = tarifa_isr.DIAS_NOMINALES.get(periodicidad_tarifa)
            renglones = config.tarifas.get(periodicidad_tarifa, ())
            if dias_nominales is not None and renglones:
                tarifa_aplicada = f"{ejercicio} · {tarifa_isr.ETIQUETAS_TARIFA[periodicidad_tarifa]}"
                try:
                    # `isr_del_periodo` se llama primero: si `dias_pagados` es cero o negativo
                    # lanza aquí, antes de que la elevación de la base de abajo pudiera dividir
                    # entre cero por su cuenta.
                    isr_determinado = tarifa_isr.isr_del_periodo(renglones, base, dias_pagados, dias_nominales)
                    base_para_renglon = (
                        base if dias_pagados == dias_nominales else _redondear(base * dias_nominales / dias_pagados)
                    )
                    r = tarifa_isr.renglon_para(renglones, base_para_renglon)
                    excedente = _redondear(base_para_renglon - r.limite_inferior)
                    impuesto_marginal = _redondear(excedente * r.tasa_excedente)
                    renglon = r.renglon
                    limite_inferior = r.limite_inferior
                    # `a_porcentaje`, no la fracción cruda de la columna: es el único número de
                    # la tarifa donde una escala equivocada cambia el resultado, y es exactamente
                    # para esto que Task 1 construyó el helper — las otras dos pantallas que
                    # muestran una tasa (`app.api.v1.configuracion`,
                    # `app.services.revision_tarifa`) ya lo usan; el dueño del Hub no es contador
                    # y no debe leer `0.1088` donde el resto del sistema muestra `10.88`.
                    tasa = tarifa_isr.a_porcentaje(r.tasa_excedente)
                    cuota_fija = r.cuota_fija

                    if config.hay_subsidio:
                        uma_mensual = config.uma_mensual
                        factor_subsidio = config.factor_subsidio
                        tope_subsidio = config.tope_subsidio
                        assert uma_mensual is not None
                        assert factor_subsidio is not None
                        assert tope_subsidio is not None
                        subsidio_teorico = tarifa_isr.subsidio_del_periodo(
                            base, dias_pagados, uma_mensual, factor_subsidio, tope_subsidio
                        )
                        isr_a_retener_teorico = tarifa_isr.isr_a_retener(isr_determinado, subsidio_teorico)
                        subsidio_a_entregar_teorico = tarifa_isr.subsidio_a_entregar(isr_determinado, subsidio_teorico)
                except tarifa_isr.TarifaInvalida as exc:
                    renglon = limite_inferior = excedente = tasa = impuesto_marginal = cuota_fija = None
                    isr_determinado = None
                    subsidio_teorico = isr_a_retener_teorico = subsidio_a_entregar_teorico = None
                    banderas.append(
                        Bandera(
                            clave="RECIBO_NO_CALCULABLE",
                            severidad="alta",
                            ambito=f"uuid:{comprobante.uuid}",
                            mensaje=f"No se pudo recalcular el ISR de este recibo con la tarifa: {exc}",
                        )
                    )

        isr_cfdi = isr_cfdi_por_comprobante.get(cid, Decimal("0.00"))
        subsidio_cfdi = subsidio_cfdi_por_comprobante.get(cid, Decimal("0.00"))
        diferencia_isr = None if isr_a_retener_teorico is None else _redondear(isr_cfdi - isr_a_retener_teorico)
        diferencia_subsidio = (
            None if subsidio_a_entregar_teorico is None else _redondear(subsidio_cfdi - subsidio_a_entregar_teorico)
        )

        filas.append(
            [
                comprobante.uuid,
                fecha_pago,
                comprobante.rfc_receptor,
                codigo,
                dias_pagados,
                base,
                tarifa_aplicada,
                renglon,
                limite_inferior,
                excedente,
                tasa,
                impuesto_marginal,
                cuota_fija,
                isr_determinado,
                subsidio_teorico,
                isr_a_retener_teorico,
                subsidio_a_entregar_teorico,
                isr_cfdi,
                subsidio_cfdi,
                diferencia_isr,
                diferencia_subsidio,
            ]
        )

    return ResultadoInforme(columnas=_columnas(), filas=filas, banderas=banderas)
