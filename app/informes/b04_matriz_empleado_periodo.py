"""B-04 · Matriz empleado × periodo. Informe de control de completitud (§B-04 del
documento fuente).

**El grano cambia respecto a B-01/B-02.** Ahí una fila es un CFDI; aquí una fila es un
**empleado** y una columna es un **periodo de pago teórico** (`app.informes.periodos`), no
un concepto. No es un informe de conciliación de importes: es el que responde "¿qué
quincenas le faltan a quién?" de un vistazo — altas y bajas sin documentar, saltos de sueldo
anómalos, timbrados dobles.

**Excepción declarada a R-T7 ("cero, no vacío").** Todo el resto del proyecto pone
`Decimal("0")` en una celda de importe sin dato. Aquí una celda sin CFDI queda en `None` a
propósito: `None` significa "no hubo nómina en ese periodo", que es exactamente el hallazgo
que este informe existe para mostrar. Ponerle cero lo borraría — un hueco de dos quincenas
se vería idéntico a dos quincenas pagadas en cero. Las columnas de resumen de la ficha
(cobertura, total, promedio, dispersión) sí siguen R-T7 sin excepción: ahí "sin dato" es
`Decimal("0")`, porque no son celdas del eje de periodos.

**Universo: se reusa `app.informes.universo_nomina.universo()` sin modificarlo**, pero con
un adaptador local (`_ParametrosUniverso`) que fija `tipo_nomina="AMBOS"` sin exponerlo como
parámetro del informe. A diferencia de B-01/B-02, que sí dejan escoger ordinaria/
extraordinaria/ambas porque reportan CFDI uno a uno, B-04 necesita ver **todas** las nóminas
del empleado para juzgar si un periodo tuvo pago — filtrar por tipo aquí produciría huecos
falsos en la matriz que no son huecos reales, sino nóminas extraordinarias excluidas por el
parámetro. `PERIODO_DUPLICADO` (B-04.R4) sí distingue `tipo_nomina='O'` puntualmente, pero
eso es una regla de la celda, no un filtro del universo.

**Divergencia declarada de la guía de implementación (fase 2, `CORTE_IRREGULAR`).** El brief
dice: "`periodos.asignar_a_corte(eje, fecha_final_pago)` por cada CFDI; si `es_irregular`,
bandera `CORTE_IRREGULAR`." Se comprobó en vivo que esa instrucción literal no basta:
`asignar_a_corte` solo marca `es_irregular=True` cuando la fecha cae **fuera de todo el
eje**; para una periodicidad quincenal, una `fecha_final_pago` del día 20 SÍ cae dentro de la
ventana `[16, 30]` de la Q2 y `asignar_a_corte` la acepta como regular (`(indice, False)`),
aunque el día 20 no sea un corte teórico de nada. La regla B-04.R5, leída tal cual dice el
documento fuente ("cuando `fecha_final_pago` no cae en ningún corte teórico"), entiende
"corte teórico" como el **día puntual de cierre** (15, el último día del mes, etc.), no como
la ventana quincenal completa. Por eso este módulo usa `asignar_a_corte` exactamente como se
indica para la asignación de la celda (fase 2, sin tocar `periodos.py`, que ya está probado
y es contrato con B-07), pero calcula `CORTE_IRREGULAR` por su cuenta comparando
`fecha_final_pago == eje[indice].fin` — un chequeo estrictamente más exigente que subsume el
caso que sí cubre `es_irregular` (fechas fuera de todo el eje nunca coinciden con un
`.fin`) y además detecta el caso que se le escapaba. Sin este ajuste, la prueba
`test_corte_irregular` (fecha del día 20 en periodicidad quincenal) no puede pasar sin
modificar `periodos.py`, y modificarlo cambiaría el contrato que B-07 va a heredar.

**Dos casos que no fallan en silencio (guía de la tarea):**

1. Si `periodos.periodicidad_dominante()` sobre las `nomina_receptor.periodicidad_pago` del
   universo devuelve `None` (ninguna reconocida), no hay eje que construir. Se devuelve un
   `ResultadoInforme` con columnas de identidad únicamente (nunca cero columnas: una matriz
   sin columnas se ve igual que un informe vacío legítimo y nadie sabría por qué), aviso y
   la bandera `PERIODICIDAD_INDETERMINADA`.
2. Un CFDI sin `fecha_final_pago` no se puede ubicar en el eje: se excluye de la matriz y se
   marca con `FECHA_FINAL_PAGO_AUSENTE` para que no desaparezca sin dejar rastro.

**Precisión de B-04.R2 (`PERIODO_FALTANTE`) que la prueba obligó a corregir.** La primera
lectura ("vacía y hay un CFDI en un periodo posterior") marcaba también los huecos *antes*
del primer dato observado — el caso simétrico de la cola que la regla sí exceptúa: un
empleado cuyo único CFDI del rango está a la mitad (alta a media quincena, o rango de
consulta que empieza antes de su ingreso) se veía con `PERIODO_FALTANTE` en todos los
periodos anteriores a esa primera nómina, un falso positivo por la misma razón que la regla
ya exceptúa la cola — no hubo nómina que timbrar porque el empleado no existía todavía, no
porque se haya omitido un timbrado. `test_hueco_al_final_no_marca_periodo_faltante` lo
expone con un solo CFDI a media serie: fallaba porque marcaba el periodo anterior a esa única
nómina. La regla correcta —y la que implementa este módulo— acota el hueco por **ambos**
lados: solo se marca un índice vacío que quede **entre** el primer y el último periodo con
dato del empleado (`range(min(indices_con_dato) + 1, max(indices_con_dato))`), nunca antes
del primero ni después del último.

**Las etiquetas de periodo de este informe NO son las de B-07, y no deben cruzarse.** B-04
asigna cada CFDI a su celda por `fecha_final_pago` (B-04.R1: el fin del periodo devengado es lo
que define "esa quincena tuvo nómina"); B-07 asigna por `fecha_pago`, porque para la continuidad
de un préstamo lo que importa es en qué periodo **apareció** el descuento. Cada elección es la
correcta para su propósito y ninguna se cambia, pero con el patrón real de esta empresa —timbrado
y pago desfasados: la nómina del 30 de junio se paga/timbra a inicios de julio— **las etiquetas no
coinciden**: un `PERIODO_FALTANTE` que aquí sale en `2026-06 Q2` se lee como hueco de
`2026-07 Q1` en B-07 (y el docstring de B-07 habla de comparar contra "la secuencia teórica de
B-04"). Al cruzar los dos informes hay que traducir la etiqueta, no suponer que hablan de la misma
quincena.

**Sin `round()` ni `quantize()`** (el redondeo lo hace `app.informes.excel` al escribir la
celda, R-T4). `Decimal` de punta a punta; para la desviación estándar, `Decimal.sqrt()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import periodos, universo_nomina
from app.informes.base import Bandera, Columna, ResultadoInforme
from app.informes.identidades_b00 import CLAVE_TIPO_DEDUCCION_ISR
from app.models.empresa import Empresa
from app.models.nomina import NominaDeduccion

CLAVE = "B-04"
NOMBRE = "Matriz empleado × periodo"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por empleado y una columna por periodo de pago teórico. Informe de control de "
    "completitud: qué quincenas faltan, qué altas y bajas no están documentadas y qué saltos "
    "de sueldo son anómalos."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Ver la constante homónima de `app.informes.b02_conceptos_patron`: mismo razonamiento y
mismo consumidor (el pre-vuelo del ETL en `app.worker.tasks._generar_informe_async`)."""

_CERO = Decimal("0")
_UMBRAL_VARIACION = Decimal("0.30")
"""30 % de variación relativa (B-04.R3)."""

Metrica = Literal["NETO", "TOTAL_PERCEPCIONES", "GRAVADO", "ISR_RETENIDO", "DIAS_PAGADOS", "NUM_CFDI"]

_TIPO_POR_METRICA: dict[str, str] = {
    "NETO": "monto",
    "TOTAL_PERCEPCIONES": "monto",
    "GRAVADO": "monto",
    "ISR_RETENIDO": "monto",
    "DIAS_PAGADOS": "decimal",
    "NUM_CFDI": "entero",
}
"""Tipo de columna de cada periodo, según la métrica (guía de la tarea): `monto` salvo
`NUM_CFDI` (`entero`) y `DIAS_PAGADOS` (`decimal`)."""


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango del eje de periodos.")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    metrica: Metrica = Field("NETO", description="Qué valor reporta cada celda de la matriz.")
    incluir_cancelados: bool = Field(False, description="Por defecto solo vigentes (R-T1).")
    enmascarar_datos_personales: bool = Field(
        True,
        description=(
            "Enmascara CURP y NSS (spec §8). Lo aplica el motor de informes "
            "(`app.informes.excel.escribir_libro`) sobre las columnas que esta consulta marca "
            "como `sensible=True`, no esta consulta directamente."
        ),
    )


@dataclass(slots=True)
class _ParametrosUniverso:
    """Adaptador local a `universo_nomina.ParametrosUniverso`. B-04 no expone `tipo_nomina`
    al usuario (ver docstring del módulo): siempre `AMBOS`, para no producir huecos falsos en
    la matriz por nóminas extraordinarias excluidas del universo."""

    fecha_desde: date
    fecha_hasta: date
    incluir_cancelados: bool
    tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"


# Columnas de identidad del empleado. Sin "Nombre empleado": la ficha de B-04 no la pide y la
# matriz se identifica por RFC. Cuando este módulo se escribió, B-01/B-02 llenaban esa columna con
# `comprobante.razon_social_emisor` (el nombre del PATRÓN) y omitirla era además la forma de no
# repetir un dato equivocado; la revisión final de la fase 2 corrigió esos dos informes para que
# usen `comprobante_detalle.nombre_receptor`, así que hoy la omisión aquí es solo de alcance: si
# alguna vez se agrega, el campo correcto ya existe y es el que usan los otros cinco informes.
_COLUMNAS_IDENTIDAD: tuple[tuple[str, str, bool], ...] = (
    ("RFC empleado", "texto", False),
    ("Núm. empleado", "texto", False),
    ("CURP", "texto", True),
    ("NSS", "texto", True),
    ("Departamento", "texto", False),
    ("Puesto", "texto", False),
)


def _columnas_identidad() -> list[Columna]:
    """Lo que se devuelve cuando no hay universo o no se puede construir el eje: nunca cero
    columnas (una matriz sin columnas se confunde con un informe vacío legítimo)."""
    return [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS_IDENTIDAD]  # type: ignore[arg-type]


@dataclass(slots=True)
class _DatoCfdi:
    """Lo que aporta un CFDI a la celda (empleado, periodo) a la que se asignó."""

    tipo_nomina: str | None
    total: Decimal
    total_percepciones: Decimal
    total_gravado: Decimal
    dias_pagados: Decimal
    isr: Decimal


def _a_decimal(valor: Decimal | float | None) -> Decimal:
    """`Numeric` puede llegar como `Decimal` o, según el atributo mapeado, como `float`;
    nunca se opera en binario (mismo patrón que `identidades_b00._dec`)."""
    if valor is None:
        return _CERO
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def _valor_metrica(metrica: str, datos: Sequence[_DatoCfdi]) -> Decimal | int:
    """Fase 3 del algoritmo: el valor de una celda con al menos un CFDI, para la métrica
    elegida. Con más de un CFDI en la celda (ver `PERIODO_DUPLICADO`) se suma, salvo
    `NUM_CFDI`, que cuenta."""
    if metrica == "NUM_CFDI":
        return len(datos)
    if metrica == "NETO":
        return sum((d.total for d in datos), _CERO)
    if metrica == "TOTAL_PERCEPCIONES":
        return sum((d.total_percepciones for d in datos), _CERO)
    if metrica == "GRAVADO":
        return sum((d.total_gravado for d in datos), _CERO)
    if metrica == "ISR_RETENIDO":
        return sum((d.isr for d in datos), _CERO)
    if metrica == "DIAS_PAGADOS":
        return sum((d.dias_pagados for d in datos), _CERO)
    raise ValueError(f"Métrica no soportada: {metrica!r}.")  # pragma: no cover - Literal ya lo impide


async def _isr_por_comprobante(db: AsyncSession, ids: list[int]) -> dict[int, Decimal]:
    """`SUM(importe)` de las deducciones tipo ISR (`CLAVE_TIPO_DEDUCCION_ISR`), por
    comprobante — una sola consulta agregada para todo el universo (regla 11: cero N+1)."""
    if not ids:
        return {}
    filas = await db.execute(
        select(NominaDeduccion.comprobante_id, func.sum(NominaDeduccion.importe))
        .where(NominaDeduccion.comprobante_id.in_(ids), NominaDeduccion.tipo_deduccion == CLAVE_TIPO_DEDUCCION_ISR)
        .group_by(NominaDeduccion.comprobante_id)
    )
    resultado: dict[int, Decimal] = {}
    for comprobante_id, suma in filas:
        resultado[int(comprobante_id)] = _a_decimal(suma)
    return resultado


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=_columnas_identidad(), aviso="La empresa no existe.")

    p_universo = _ParametrosUniverso(fecha_desde=p.fecha_desde, fecha_hasta=p.fecha_hasta, incluir_cancelados=p.incluir_cancelados)
    filas_universo = list((await db.execute(universo_nomina.universo(empresa_id, rfc_empresa, p_universo))).all())
    # Se resuelve ANTES del retorno temprano, igual que en B-01/B-02: si el ETL falló en TODOS
    # los CFDI del rango, la hoja Datos sale vacía y estas banderas son el único rastro.
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, rfc_empresa, p_universo)

    if not filas_universo:
        return ResultadoInforme(
            columnas=_columnas_identidad(),
            banderas=banderas_fuera,
            aviso="Sin CFDI de nómina en el rango solicitado.",
        )

    # Fase 1: periodicidad dominante y eje teórico de columnas.
    periodicidad = periodos.periodicidad_dominante([receptor.periodicidad_pago if receptor else None for _, _, receptor, _, _ in filas_universo])
    if periodicidad is None:
        banderas_fuera.append(
            Bandera(
                clave="PERIODICIDAD_INDETERMINADA",
                severidad="alta",
                ambito="informe",
                mensaje=(
                    "Ningún `nomina_receptor.periodicidad_pago` del rango es una periodicidad "
                    "reconocida (02/03/04/05/06); no se puede construir el eje de periodos."
                ),
            )
        )
        return ResultadoInforme(
            columnas=_columnas_identidad(),
            banderas=banderas_fuera,
            aviso="No se pudo determinar una periodicidad de pago dominante: el informe no puede construir su eje de periodos.",
        )

    # Para "02"/"03" (paso fijo, sin día de mes fijo) el eje necesita un ancla: el primer
    # corte observado en el universo (MIN de `fecha_final_pago`). `construir_eje` ignora este
    # argumento para las periodicidades de día fijo, así que pasarlo siempre es inocuo.
    fechas_finales = [nomina.fecha_final_pago for _, nomina, _, _, _ in filas_universo if nomina.fecha_final_pago is not None]
    ancla = min(fechas_finales) if fechas_finales else None
    eje = periodos.construir_eje(periodicidad, p.fecha_desde, p.fecha_hasta, primer_corte_observado=ancla)

    ids = [comprobante.comprobante_id for comprobante, *_ in filas_universo]
    isr_por_cid = await _isr_por_comprobante(db, ids)

    banderas: list[Bandera] = list(banderas_fuera)
    # `ESTATUS_NO_VERIFICADO` / `COMPROBANTE_CANCELADO` / `DATOS_DE_CORRIDA_ANTERIOR`: la
    # condición con la que el §11 del diseño acepta la divergencia de R-T1 ("todo comprobante
    # incluido que no sea vigente lleva bandera"). Este informe no la cumplía y no tiene columna
    # de estatus en `Datos` (a diferencia de B-01/B-02, que sí traen "Estado SAT"), así que una
    # celda de la matriz llena por un CFDI cancelado ante el SAT decía "esa quincena está
    # cubierta" sin ninguna marca — y como la verificación contra el SAT es asíncrona por diseño,
    # `no_verificado` es el estado normal de un rango recién descargado. Recibe el universo
    # completo, no un comprobante: el colapso por umbral de `ESTATUS_NO_VERIFICADO` es una
    # decisión sobre el conjunto (ver su docstring).
    banderas.extend(universo_nomina.banderas_de_estatus(universo_nomina.comprobantes_y_detalles(filas_universo)))
    # celdas[rfc][indice] = CFDI asignados a esa celda de la matriz.
    celdas: dict[str, dict[int, list[_DatoCfdi]]] = {}
    # Última fotografía del receptor observada por empleado (filas_universo viene ordenado
    # por `fecha_pago` ascendente — mismo `order_by` de `universo_nomina.universo` —, así que
    # sobrescribir en el orden de iteración deja la más reciente).
    identidad: dict[str, tuple[str | None, str | None, str | None, str | None, str | None]] = {}

    for comprobante, nomina, receptor, totales, _detalle in filas_universo:
        rfc = comprobante.rfc_receptor
        identidad[rfc] = (
            receptor.num_empleado if receptor else None,
            receptor.curp if receptor else None,
            receptor.nss if receptor else None,
            receptor.departamento if receptor else None,
            receptor.puesto if receptor else None,
        )

        if nomina.fecha_final_pago is None:
            # No hay fecha con la que asignar el CFDI a ningún corte del eje (B-04, fase 2).
            banderas.append(
                Bandera(
                    clave="FECHA_FINAL_PAGO_AUSENTE",
                    severidad="alta",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje="El CFDI no trae `fecha_final_pago`; no se puede ubicar en el eje de periodos y se excluye de la matriz.",
                )
            )
            continue

        # Fase 2: la asignación es por `fecha_final_pago`, no por `fecha_pago` (B-04.R1).
        indice, _ = periodos.asignar_a_corte(eje, nomina.fecha_final_pago)
        # `CORTE_IRREGULAR` (B-04.R5): ver la divergencia declarada en el docstring del
        # módulo. No se usa el booleano de `asignar_a_corte` directamente: coincidir con la
        # VENTANA de un corte no es lo mismo que coincidir con su día de cierre teórico.
        en_eje = 0 <= indice < len(eje)
        if not (en_eje and nomina.fecha_final_pago == eje[indice].fin):
            etiqueta_cercana = eje[indice].etiqueta if en_eje else "fuera del eje"
            banderas.append(
                Bandera(
                    clave="CORTE_IRREGULAR",
                    severidad="media",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=(
                        f"`fecha_final_pago` ({nomina.fecha_final_pago}) no coincide con el cierre teórico de "
                        f"ningún corte de periodicidad {periodicidad}; se asignó al más cercano ({etiqueta_cercana})."
                    ),
                )
            )
        if not en_eje:
            continue  # Eje vacío (ancla fuera de rango): no hay celda posible.

        dato = _DatoCfdi(
            tipo_nomina=nomina.tipo_nomina,
            total=_a_decimal(comprobante.total),
            total_percepciones=_a_decimal(nomina.total_percepciones),
            total_gravado=_a_decimal(totales.total_gravado if totales else None),
            dias_pagados=_a_decimal(nomina.num_dias_pagados),
            isr=isr_por_cid.get(comprobante.comprobante_id, _CERO),
        )
        celdas.setdefault(rfc, {}).setdefault(indice, []).append(dato)

    # B-04.R4: `PERIODO_DUPLICADO` — más de un CFDI con `tipo_nomina='O'` en la misma celda.
    for rfc, por_indice in celdas.items():
        for indice, datos in por_indice.items():
            ordinarias = sum(1 for d in datos if d.tipo_nomina == "O")
            if ordinarias > 1:
                etiqueta = eje[indice].etiqueta if 0 <= indice < len(eje) else str(indice)
                banderas.append(
                    Bandera(
                        clave="PERIODO_DUPLICADO",
                        severidad="alta",
                        ambito=f"rfc:{rfc}",
                        mensaje=f"{ordinarias} CFDI de nómina ordinaria (tipo_nomina='O') en el periodo {etiqueta}; probable timbrado doble.",
                    )
                )

    tipo_periodo = _TIPO_POR_METRICA[p.metrica]
    # Promedio y desviación estándar de un conteo de CFDI pueden no ser enteros; el resto de
    # las métricas conserva su propio tipo.
    tipo_agregado = "decimal" if tipo_periodo == "entero" else tipo_periodo

    columnas = _columnas_identidad()
    columnas += [Columna(titulo=corte.etiqueta, tipo=tipo_periodo) for corte in eje]  # type: ignore[arg-type]
    columnas += [
        Columna(titulo="Núm. de periodos con pago", tipo="entero"),
        Columna(titulo="Núm. de periodos esperados", tipo="entero"),
        Columna(titulo="% de cobertura", tipo="decimal"),
        Columna(titulo="Total del rango", tipo=tipo_periodo),  # type: ignore[arg-type]
        Columna(titulo="Promedio por periodo", tipo=tipo_agregado),  # type: ignore[arg-type]
        Columna(titulo="Desviación estándar", tipo=tipo_agregado),  # type: ignore[arg-type]
        Columna(titulo="Coeficiente de variación", tipo="decimal"),
    ]

    filas: list[list[Any]] = []
    for rfc in sorted(identidad):
        num_empleado, curp, nss, departamento, puesto = identidad[rfc]
        por_indice = celdas.get(rfc, {})

        valores: list[Decimal | int | None] = []
        dias_por_indice: dict[int, Decimal] = {}
        indices_con_dato: list[int] = []
        for indice in range(len(eje)):
            datos_celda = por_indice.get(indice)
            if datos_celda:
                valores.append(_valor_metrica(p.metrica, datos_celda))
                dias_por_indice[indice] = sum((d.dias_pagados for d in datos_celda), _CERO)
                indices_con_dato.append(indice)
            else:
                # Excepción declarada a R-T7 (ver docstring del módulo): `None`, no cero.
                valores.append(None)

        # B-04.R2: PERIODO_FALTANTE solo entre el primer y el último periodo con dato del
        # empleado. Ni antes del primero (probable alta a media serie: no había empleado que
        # timbrar) ni después del último (probable baja: ver docstring del módulo, y la
        # corrección documentada ahí sobre la lectura inicial de esta regla).
        if indices_con_dato:
            primer_con_dato = min(indices_con_dato)
            ultimo_con_dato = max(indices_con_dato)
            for indice in range(primer_con_dato + 1, ultimo_con_dato):
                if indice not in indices_con_dato:
                    banderas.append(
                        Bandera(
                            clave="PERIODO_FALTANTE",
                            severidad="alta",
                            ambito=f"rfc:{rfc}",
                            mensaje=(
                                f"Sin CFDI en el periodo {eje[indice].etiqueta}, pero hay nómina posterior en el rango "
                                f"({eje[ultimo_con_dato].etiqueta}); probable omisión de timbrado."
                            ),
                        )
                    )

        # B-04.R3: VARIACION_ANOMALA contra el periodo inmediatamente anterior del eje,
        # solo si ambos tienen los mismos días pagados (evita marcar quincenas cortas
        # legítimas, p. ej. un alta a media quincena).
        for indice in indices_con_dato:
            anterior = indice - 1
            if anterior not in dias_por_indice or dias_por_indice[indice] != dias_por_indice[anterior]:
                continue
            valor_actual, valor_anterior = valores[indice], valores[anterior]
            if valor_actual is None or valor_anterior is None:
                continue
            dec_anterior = Decimal(valor_anterior)
            if dec_anterior == 0:
                continue  # Variación relativa no definida contra una base de cero.
            variacion = abs(Decimal(valor_actual) - dec_anterior) / abs(dec_anterior)
            if variacion > _UMBRAL_VARIACION:
                banderas.append(
                    Bandera(
                        clave="VARIACION_ANOMALA",
                        severidad="media",
                        ambito=f"rfc:{rfc}",
                        mensaje=(
                            f"{eje[anterior].etiqueta} → {eje[indice].etiqueta}: variación de {(variacion * 100):.2f}% "
                            f"con los mismos días pagados ({dias_por_indice[indice]})."
                        ),
                    )
                )

        # Columnas de resumen de la ficha (siempre siguen R-T7: sin dato es Decimal("0")).
        num_con_pago = len(indices_con_dato)
        num_esperados = len(eje)
        cobertura = (Decimal(num_con_pago) / Decimal(num_esperados)) if num_esperados else _CERO

        valores_con_dato = [valores[i] for i in indices_con_dato]
        valores_decimal = [Decimal(v) for v in valores_con_dato if v is not None]
        total_decimal = sum(valores_decimal, _CERO)
        total_del_rango: Decimal | int = int(total_decimal) if p.metrica == "NUM_CFDI" else total_decimal
        media = (total_decimal / Decimal(num_con_pago)) if num_con_pago else _CERO

        if num_con_pago >= 2:
            varianza = sum(((v - media) ** 2 for v in valores_decimal), _CERO) / Decimal(num_con_pago)
            desviacion = varianza.sqrt()
            coef_variacion = (desviacion / media) if media != 0 else _CERO
        else:
            desviacion = _CERO
            coef_variacion = _CERO

        fila: list[Any] = [rfc, num_empleado, curp, nss, departamento, puesto]
        fila += valores
        fila += [num_con_pago, num_esperados, cobertura, total_del_rango, media, desviacion, coef_variacion]
        filas.append(fila)

    return ResultadoInforme(columnas=columnas, filas=filas, banderas=banderas)
