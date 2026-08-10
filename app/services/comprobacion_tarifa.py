"""La comprobación de una tarifa contra un recibo real.

Su propósito no es auditar al patrón: es detectar un **error de carga**. Una tarifa de otra
periodicidad o de otro ejercicio, guardada por error en el slot equivocado, es aritméticamente
coherente —pasa las seis pruebas del Anexo I.1, que solo miran si los renglones son consistentes
entre sí, nunca dónde se guardaron— y solo se delata al aplicarla a un recibo de verdad. No produce
un ISR absurdo: produce uno **sistemáticamente desplazado**, porque los tramos de una tarifa de otra
escala no dividen el ingreso donde deberían. Eso es lo que fija
`test_una_tarifa_de_otra_periodicidad_cargada_en_el_slot_equivocado_se_delata`, que es la razón de
existir de este módulo.

Cuatro reglas para que esto ayude en vez de confundir (§7.3 del diseño):

1. **Usa el gravado que el propio CFDI declara** (`nomina_totales.total_gravado`), no una base
   recalculada a partir de las marcas de percepción. Las 44 marcas de `catalogo_percepcion_marca`
   están sin confirmar, así que una base derivada saldría vacía justo cuando más se necesita la
   comprobación: al cargar la tarifa por primera vez.
2. **Elige un recibo ordinario y sencillo**: `tipo_nomina = 'O'`, sin cancelar, sin error de
   normalización, con gravado positivo, y de preferencia con los días pagados iguales a los
   nominales de la periodicidad. Si no existe ninguno así de limpio, usa el que haya y explica por
   qué la diferencia es esperada.
3. **Una diferencia no acusa a nadie.** El ISR timbrado puede incluir subsidio al empleo, ajustes
   del periodo o el procedimiento del art. 174 del Reglamento; una diferencia de pesos es normal.
   Lo que esto detecta es un error de carga: una tarifa de otra periodicidad o de otro ejercicio deja
   una diferencia **relativa grande** (más de la mitad del impuesto), no de pesos.
4. **No es un dictamen fiscal.** Es un cálculo sobre un recibo, sin universo, sin banderas y sin
   archivo de salida. `POST …/confirmar` no exige que esto cuadre — exigirlo bloquearía una tarifa
   correcta cuando el patrón aplicó subsidio, que es el caso normal.

**La tarifa `EJERCICIO` (anual) es un caso aparte.** No tiene una periodicidad de recibo propia —el
Anexo la publica para el ingreso de *todo un año*, no para un recibo—, así que se usa el recibo
mensual más reciente, aplicado tal cual (sin proyectar nada): es la única comparación disponible,
aunque un mes y un año no sean comparables. Por eso se advierte que esta comparación en particular
solo sirve para ver que las cifras están en la escala correcta, no para juzgar si la tarifa anual
está bien cargada — eso no lo puede decir un solo recibo mensual.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.enums import EstatusCfdi, PeriodicidadTarifa
from app.models.nomina import Nomina, NominaDeduccion, NominaPercepcion, NominaReceptor, NominaTotales
from app.repositories.tarifa_isr import TarifaGuardada
from app.services import tarifa_isr as reglas

# Claves de catálogos del SAT que este módulo necesita. Se guardan aquí, como texto, en vez de
# importarlas de otro módulo: son códigos de catálogo (c_TipoNomina, c_TipoDeduccion,
# c_TipoPercepcion), no importes fiscales, y `tarifa_isr.PARA_CFDI` ya fija el mismo precedente de
# escribir las claves del CFDI literalmente en este paquete.
_TIPO_NOMINA_ORDINARIO: Final = "O"
_TIPO_DEDUCCION_ISR: Final = "002"
_TIPO_PERCEPCION_SUELDO: Final = "001"


@dataclass(frozen=True)
class Comprobacion:
    """Los dos números lado a lado que alguien que no es contador puede comparar de un vistazo."""

    uuid: str
    fecha_inicial_pago: date | None
    fecha_final_pago: date | None
    num_empleado: str | None
    dias_pagados: Decimal | None
    gravado: Decimal
    renglon: int
    limite_inferior: Decimal
    tasa_excedente: Decimal
    isr_calculado: Decimal
    isr_timbrado: Decimal
    diferencia: Decimal
    advertencias: tuple[str, ...]


def _periodicidad_cfdi_para(periodicidad: PeriodicidadTarifa) -> str:
    """La clave de `c_PeriodicidadPago` que corresponde a esta periodicidad de tarifa, invirtiendo
    `reglas.PARA_CFDI` (la primera clave cuyo valor sea `periodicidad`).

    `EJERCICIO` (la tarifa anual) no tiene una periodicidad de recibo propia: ninguna clave de
    `PARA_CFDI` apunta a ella, porque el Anexo la publica para el cálculo del ejercicio completo,
    no para un recibo individual. En ese caso se usa la mensual — el recibo más parecido en
    frecuencia y la única comparación disponible, aunque un mes y un año no sean comparables.
    """
    if periodicidad is PeriodicidadTarifa.EJERCICIO:
        for clave, valor in reglas.PARA_CFDI.items():
            if valor is PeriodicidadTarifa.MENSUAL:
                return clave
        raise AssertionError("PARA_CFDI no tiene una clave para MENSUAL")  # pragma: no cover
    for clave, valor in reglas.PARA_CFDI.items():
        if valor is periodicidad:
            return clave
    raise AssertionError(f"PARA_CFDI no tiene ninguna clave para {periodicidad}")  # pragma: no cover


def _dias_nominales_para(periodicidad: PeriodicidadTarifa) -> Decimal:
    """Los días que cubre un recibo "limpio" de esta periodicidad. La anual usa los de la mensual,
    por la misma razón que `_periodicidad_cfdi_para`: no tiene un recibo propio."""
    if periodicidad is PeriodicidadTarifa.EJERCICIO:
        return reglas.DIAS_NOMINALES[PeriodicidadTarifa.MENSUAL]
    return reglas.DIAS_NOMINALES[periodicidad]


async def comprobar(db: AsyncSession, *, tarifa: TarifaGuardada) -> Comprobacion | None:
    """Aplica `tarifa` a un recibo real y devuelve los dos números lado a lado.

    **Usa el gravado que el propio CFDI declara** (`nomina_totales.total_gravado`), no una base
    recalculada desde `catalogo_percepcion_marca`: las 44 marcas están sin confirmar, así que una
    base derivada saldría vacía justo cuando más se necesita la comprobación —al cargar la tarifa
    por primera vez—. Es una aproximación consciente: si el recibo trae percepciones
    extraordinarias, la diferencia contra lo timbrado es esperada, y por eso se advierte en vez de
    callarlo.

    **No decide nada.** Quien confirma mira los dos números; el endpoint de confirmación no exige
    que cuadren, porque el ISR timbrado puede incluir subsidio al empleo, ajustes del periodo o el
    procedimiento del art. 174 del Reglamento, y exigir coincidencia bloquearía tarifas correctas.

    Devuelve `None` si no hay ningún recibo elegible (base sin nómina, o solo cancelados / con
    error de normalización) — distinto de que la tarifa esté mal.
    """
    periodicidad_cfdi = _periodicidad_cfdi_para(tarifa.periodicidad)
    dias_nominales = _dias_nominales_para(tarifa.periodicidad)

    # Correlacionadas a `Nomina`, no subconsultas independientes: así la selección del recibo sigue
    # siendo una sola sentencia (regla 11), sin una consulta adicional por candidato ni una segunda
    # consulta para el recibo ya elegido.
    isr_timbrado_sub = (
        select(func.sum(NominaDeduccion.importe))
        .where(
            NominaDeduccion.comprobante_id == Nomina.comprobante_id,
            NominaDeduccion.tipo_deduccion == _TIPO_DEDUCCION_ISR,
        )
        .correlate(Nomina)
        .scalar_subquery()
    )
    tiene_extraordinarias_sub = (
        select(func.count())
        .select_from(NominaPercepcion)
        .where(
            NominaPercepcion.comprobante_id == Nomina.comprobante_id,
            NominaPercepcion.tipo_percepcion != _TIPO_PERCEPCION_SUELDO,
        )
        .correlate(Nomina)
        .scalar_subquery()
    )

    fila = (
        await db.execute(
            select(
                Comprobante.uuid,
                Nomina.fecha_inicial_pago,
                Nomina.fecha_final_pago,
                Nomina.num_dias_pagados,
                NominaReceptor.num_empleado,
                NominaTotales.total_gravado,
                isr_timbrado_sub.label("isr_timbrado"),
                tiene_extraordinarias_sub.label("tiene_extraordinarias"),
            )
            .join(NominaReceptor, NominaReceptor.comprobante_id == Nomina.comprobante_id)
            .join(NominaTotales, NominaTotales.comprobante_id == Nomina.comprobante_id)
            .join(Comprobante, Comprobante.comprobante_id == Nomina.comprobante_id)
            .outerjoin(ComprobanteDetalle, ComprobanteDetalle.comprobante_id == Nomina.comprobante_id)
            .where(
                Comprobante.estatus != EstatusCfdi.CANCELADO,
                ComprobanteDetalle.error_normalizacion.is_(None),
                Nomina.tipo_nomina == _TIPO_NOMINA_ORDINARIO,
                NominaReceptor.periodicidad_pago == periodicidad_cfdi,
                NominaTotales.total_gravado > 0,
            )
            .order_by((Nomina.num_dias_pagados == dias_nominales).desc(), Nomina.fecha_pago.desc())
            .limit(1)
        )
    ).first()
    if fila is None:
        return None

    uuid, fecha_inicial, fecha_final, dias_pagados, num_empleado, gravado_bruto, isr_timbrado_bruto, tiene_extraordinarias = fila
    gravado = gravado_bruto if isinstance(gravado_bruto, Decimal) else Decimal(str(gravado_bruto))
    isr_timbrado = (
        Decimal("0")
        if isr_timbrado_bruto is None
        else isr_timbrado_bruto
        if isinstance(isr_timbrado_bruto, Decimal)
        else Decimal(str(isr_timbrado_bruto))
    )

    renglon = reglas.renglon_para(tarifa.renglones, gravado)
    isr_calculado = reglas.isr_de(tarifa.renglones, gravado)

    advertencias: list[str] = []
    if dias_pagados is None or dias_pagados != dias_nominales:
        advertencias.append(
            f"Los días pagados del recibo ({dias_pagados}) no son los {dias_nominales} de la "
            "periodicidad, así que el importe está prorrateado y la diferencia es esperada."
        )
    if tarifa.periodicidad is PeriodicidadTarifa.EJERCICIO:
        advertencias.append(
            "La tarifa anual no se aplica a un recibo individual; esta comparación solo sirve "
            "para ver que las cifras están en la escala correcta."
        )
    if tiene_extraordinarias:
        advertencias.append(
            "El recibo trae percepciones que no son sueldo ordinario, así que parte del gravado "
            "no debería entrar en este cálculo."
        )

    return Comprobacion(
        uuid=uuid,
        fecha_inicial_pago=fecha_inicial,
        fecha_final_pago=fecha_final,
        num_empleado=num_empleado,
        dias_pagados=dias_pagados,
        gravado=gravado,
        renglon=renglon.renglon,
        limite_inferior=renglon.limite_inferior,
        tasa_excedente=renglon.tasa_excedente,
        isr_calculado=isr_calculado,
        isr_timbrado=isr_timbrado,
        diferencia=isr_calculado - isr_timbrado,
        advertencias=tuple(advertencias),
    )
