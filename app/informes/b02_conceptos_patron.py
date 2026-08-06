"""B-02 · Nómina agrupada por conceptos del patrón (§B-02 del documento fuente).

Es el informe que producen OneFacture, ezaudita, MiAdminXML y Audita CFDI, y el peor
especificado de todos. Reproduce la nómina como la concibe el patrón —con sus claves y
descripciones internas— para cotejar el CFDI timbrado contra el recibo del sistema de
nómina, concepto por concepto.

Grano: una fila por comprobante. Cada concepto distinto del patrón es una columna generada
en tiempo de ejecución.

Las cuatro trampas que este módulo evita a propósito:

1. **Sumar, no sobrescribir** (B-02.R1). El esquema Nómina 1.2 permite varios nodos con el
   mismo `(tipo, clave)` en un CFDI. El valor de la celda es `SUM(...)`.
2. **Prefijo de naturaleza en la etiqueta** (B-02.R3). `tipo_percepcion='002'` (aguinaldo)
   y `tipo_deduccion='002'` (ISR) comparten el texto `002`.
3. **Identidad por `(tipo, clave)`, nunca por descripción** (R-T9). El `@Concepto` es texto
   libre del patrón y varía entre periodos por errores de captura.
4. **Cero, no vacío** (R-T7).

**Nota de alcance:** el desglose por gravado/exento dentro de cada percepción (columnas
`(G)` y `(E)` separadas para el mismo concepto) está en la ficha B-02 del documento fuente,
pero se aplaza: duplicaría el conjunto de columnas dinámicas y alteraría su orden (B-02.R5),
y es trabajo suficiente para ameritar su propia tarea. Por ahora la celda de cada percepción
reporta `importe_gravado + importe_exento` ya sumados (ver `_conceptos_por_comprobante`).

**Divergencia declarada de R-T1 (§11 del diseño).** El diseño dice "por defecto solo
`VIGENTE`". Lo implementado excluye únicamente los `CANCELADO`, así que los `no_verificado`
—los que todavía no se le han consultado al SAT— **sí entran al informe**. Es una decisión
tomada a propósito, no un descuido: la verificación de estatus contra el SAT es un proceso
asíncrono e independiente de la descarga, así que exigir `VIGENTE` borraría del informe toda
la nómina cuyo estatus aún no se ha consultado — pérdida silenciosa de filas, que en este
dominio es peor que el problema que resuelve. Para que la inclusión no sea invisible, cada
comprobante incluido que no sea `vigente` lleva bandera: `ESTATUS_NO_VERIFICADO` (media) o
`COMPROBANTE_CANCELADO` (alta, que solo puede aparecer con `incluir_cancelados=True`).

**Ningún CFDI de nómina desaparece en silencio.** La consulta principal exige fila en
`nomina`, así que un tipo `N` que el ETL no pudo normalizar (XML corrupto, XML perdido) o
que llegó sin complemento de nómina no puede aparecer en la hoja `Datos` — no hay datos que
poner. Lo que sí ocurre siempre es que aparezca en `Banderas`, con su UUID:
`_banderas_de_no_normalizables` lo garantiza (§9 del diseño). Un patrón que concilia siete
recibos creyendo que son ocho comete un error fiscal que descubre cuando la autoridad se lo
señala.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import catalogos, universo_nomina
from app.informes.base import Bandera, Columna, EntradaDiccionario, ResultadoInforme, SEPARADOR_ETIQUETA
from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.empresa import Empresa
from app.models.nomina import Nomina, NominaDeduccion, NominaOtroPago, NominaPercepcion, NominaReceptor, NominaTotales

CLAVE = "B-02"
NOMBRE = "Nómina agrupada por conceptos del patrón"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por CFDI de nómina, con una columna por cada concepto del patrón. "
    "Sirve para cotejar el CFDI timbrado contra el recibo del sistema de nómina, concepto por concepto."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Tipos de comprobante que este informe necesita normalizados (todo el grupo B: solo `N`).

Lo consume el pre-vuelo del ETL (`app.worker.tasks._generar_informe_async`) para acotar
`ids_pendientes`. Sin este filtro, la primera generación de informe posterior a subir
`ETL_VERSION` reprocesa el histórico completo de la empresa —ingresos, egresos, pagos—
dentro de la tarea del informe, en serie y con un commit por comprobante. La constante
vive aquí, en el informe que declara lo que necesita, y no en la tarea, que no tiene por
qué saber de nómina.
"""

_CERO = Decimal("0")
_TOLERANCIA = universo_nomina.TOLERANCIA

_MARGEN_TIMBRADO_DIAS = universo_nomina.MARGEN_TIMBRADO_DIAS
"""Alias de `universo_nomina.MARGEN_TIMBRADO_DIAS` (ver ese módulo para la justificación).
Se conserva el nombre público en este módulo porque `tests/test_informe_b02.py` lo lee
directamente (`b02._MARGEN_TIMBRADO_DIAS`) para calcular sus casos de prueba."""

# Orden de naturalezas del informe: replica el orden de lectura de un recibo de nómina
# (B-02, fase 3 del algoritmo): percepciones, otros pagos, deducciones.
_ORDEN_NATURALEZA = {"P": 0, "O": 1, "D": 2}

# Días nominales por periodicidad, para la bandera DIAS_PAGADOS_ATIPICO (B-02).
_RANGO_DIAS = {
    "01": (Decimal("1"), Decimal("1")),  # diario
    "02": (Decimal("1"), Decimal("7")),  # semanal
    "03": (Decimal("1"), Decimal("14")),  # catorcenal
    "04": (Decimal("1"), Decimal("16")),  # quincenal
    "05": (Decimal("1"), Decimal("31")),  # mensual
    "06": (Decimal("1"), Decimal("10")),  # decenal
}


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango, sobre `nomina.fecha_pago` (R-T6).")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    tipo_nomina: Literal["O", "E", "AMBOS"] = Field("AMBOS", description="Ordinaria, extraordinaria o ambas.")
    incluir_cancelados: bool = Field(False, description="Por defecto solo vigentes (R-T1).")
    enmascarar_datos_personales: bool = Field(
        True,
        description=(
            "Enmascara CURP, NSS y cuenta bancaria (spec §8). Lo aplica el motor de informes "
            "(`app.informes.excel.escribir_libro`) sobre las columnas que esta consulta marca "
            "como `sensible=True`, no esta consulta directamente."
        ),
    )


def etiqueta(naturaleza: str, tipo: str, clave: str | None, concepto: str | None) -> str:
    """`naturaleza ¦ tipo ¦ clave ¦ concepto` (R-T8 más el prefijo de B-02.R3)."""
    partes = [naturaleza, tipo, clave or "", concepto or ""]
    return SEPARADOR_ETIQUETA.join(partes)


# Columnas fijas: identificación, nómina, patrón y empleado (bloques de B-01). El tercer
# elemento es `sensible` (spec §8): CURP y NSS son las únicas columnas fijas con datos
# personales; el motor las enmascara si `enmascarar_datos_personales` está activo.
_COLUMNAS_FIJAS: tuple[tuple[str, str, bool], ...] = (
    ("Ejercicio", "entero", False),
    ("Periodo", "entero", False),
    ("UUID", "texto", False),
    ("Serie", "texto", False),
    ("Folio", "texto", False),
    ("Estado SAT", "texto", False),
    ("Tipo nómina", "texto", False),
    ("Fecha pago", "fecha", False),
    ("Fecha inicial", "fecha", False),
    ("Fecha final", "fecha", False),
    ("Días pagados", "decimal", False),
    ("Periodicidad", "texto", False),
    ("RFC patrón", "texto", False),
    ("Registro patronal", "texto", False),
    ("RFC empleado", "texto", False),
    ("Nombre empleado", "texto", False),
    ("CURP", "texto", True),
    ("NSS", "texto", True),
    ("Núm. empleado", "texto", False),
    ("Departamento", "texto", False),
    ("Puesto", "texto", False),
    ("Tipo régimen", "texto", False),
    ("SBC", "monto", False),
    ("SDI", "monto", False),
)

_COLUMNAS_TOTALES: tuple[tuple[str, str, bool], ...] = (
    ("Total sueldos", "monto", False),
    ("Total separación indemnización", "monto", False),
    ("Total jubilación pensión retiro", "monto", False),
    ("Total percepciones", "monto", False),
    ("Total gravado", "monto", False),
    ("Total exento", "monto", False),
    ("Total otros pagos", "monto", False),
    ("Total deducciones", "monto", False),
    ("Total (neto)", "monto", False),
)


# `_universo`, `_rango_de_emision` y `_banderas_de_no_normalizables` se extrajeron a
# `app.informes.universo_nomina` en la tarea 3 (B-01), que necesitaba exactamente la misma
# lógica: si dos informes del mismo periodo la calculan cada uno por su cuenta, en cuanto
# diverjan un carácter darán totales distintos y nadie sabrá cuál creer. Se conservan estos
# alias delgados con el nombre y la firma de siempre porque son los que usa el resto de este
# módulo (y, en el caso de `_MARGEN_TIMBRADO_DIAS`, lo que lee `tests/test_informe_b02.py`).
_universo = universo_nomina.universo
_rango_de_emision = universo_nomina.rango_de_emision
_banderas_de_no_normalizables = universo_nomina.banderas_de_no_normalizables


async def _conceptos_por_comprobante(
    db: AsyncSession, ids: list[int]
) -> tuple[dict[tuple[int, tuple[str, str, str]], Decimal], dict[tuple[str, str, str], Counter[str]]]:
    """Suma por `(comprobante_id, (naturaleza, tipo, clave))` y frecuencias de descripción
    por concepto. La suma la hace la BD (`SUM`), que es lo que implementa B-02.R1."""
    importes: dict[tuple[int, tuple[str, str, str]], Decimal] = defaultdict(lambda: _CERO)
    descripciones: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    if not ids:
        return importes, descripciones

    fuentes = (
        ("P", NominaPercepcion, NominaPercepcion.tipo_percepcion, NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento),
        ("O", NominaOtroPago, NominaOtroPago.tipo_otro_pago, NominaOtroPago.importe),
        ("D", NominaDeduccion, NominaDeduccion.tipo_deduccion, NominaDeduccion.importe),
    )
    for naturaleza, modelo, columna_tipo, expresion_importe in fuentes:
        # `COLLATE utf8mb4_bin` SOLO sobre la descripción, en el `SELECT` y en el `GROUP BY`
        # (la misma expresión en los dos sitios, o `ONLY_FULL_GROUP_BY` la rechaza).
        #
        # La colación de la tabla es `utf8mb4_unicode_ci`, insensible a mayúsculas y acentos:
        # "SUELDO" y "Sueldo" en el mismo comprobante colapsaban en un solo grupo y MySQL
        # devolvía un representante arbitrario, con dos consecuencias — el título de la
        # columna podía variar entre corridas, y `CONCEPTO_INCONSISTENTE`, que existe
        # precisamente para avisar de descripciones divergentes del mismo concepto, no las
        # veía nunca.
        #
        # Forzar la colación binaria **no parte la columna en dos**: la identidad de columna
        # es `(naturaleza, tipo, clave)` y se arma en Python (R-T9, ver el `+=` de abajo), así
        # que las dos filas que ahora devuelve el `GROUP BY` caen en la misma celda con el
        # mismo importe total. Lo único que cambia es que las dos descripciones llegan al
        # `Counter`, que es lo que se quería.
        #
        # `clave` NO se colaciona: ahí sí forma parte de la identidad de la columna, y
        # separarla convertiría en dos columnas lo que el patrón capturó como una sola con un
        # descuido de mayúsculas. Que la colación insensible elija un representante arbitrario
        # de la clave queda anotado como deuda; no se ha observado en datos reales.
        concepto = func.coalesce(modelo.concepto, "").collate("utf8mb4_bin")
        filas = await db.execute(
            select(
                modelo.comprobante_id,
                columna_tipo.label("tipo"),
                func.coalesce(modelo.clave, "").label("clave"),
                concepto.label("concepto"),
                func.sum(expresion_importe).label("importe"),
            )
            .where(modelo.comprobante_id.in_(ids))
            .group_by(modelo.comprobante_id, columna_tipo, modelo.clave, concepto)
        )
        for fila in filas:
            concepto_id = (naturaleza, str(fila.tipo), str(fila.clave))
            importe = fila.importe if isinstance(fila.importe, Decimal) else Decimal(str(fila.importe))
            # Se agrupa por (tipo, clave); la descripción NO forma parte de la identidad
            # (R-T9), así que dos descripciones del mismo concepto se acumulan aquí.
            importes[(int(fila.comprobante_id), concepto_id)] += importe
            if fila.concepto:
                descripciones[concepto_id][str(fila.concepto)] += 1
    return importes, descripciones


def _banderas_del_comprobante(
    comprobante: Comprobante,
    nomina: Nomina,
    receptor: NominaReceptor | None,
    totales: NominaTotales | None,
    suma_percepciones: Decimal,
    suma_deducciones: Decimal,
    suma_otros: Decimal,
) -> list[Bandera]:
    """Identidades de B-00 y las validaciones de la ficha B-02.

    No valida `total_impuestos_retenidos` contra el ISR retenido: esa identidad pertenece a
    B-01, que agrupa por tipo del catálogo. Aquí bastan los tres totales del complemento.

    `DATOS_DE_CORRIDA_ANTERIOR`, `COMPROBANTE_CANCELADO` y `ESTATUS_NO_VERIFICADO` (con la
    divergencia declarada de R-T1: ver docstring del módulo) son del mismo universo que B-01 y
    viven en `universo_nomina` desde la tarea 3 para no duplicar la lógica. **No se emiten
    aquí**: `universo_nomina.banderas_de_estatus` recibe el universo completo porque el colapso
    por umbral de `ESTATUS_NO_VERIFICADO` es una decisión sobre el conjunto, así que la llama
    `consultar` una sola vez.
    """
    ambito = f"uuid:{comprobante.uuid}"
    banderas: list[Bandera] = []

    identidades = (
        ("total_percepciones", nomina.total_percepciones, suma_percepciones),
        ("total_deducciones", nomina.total_deducciones, suma_deducciones),
        ("total_otros_pagos", nomina.total_otros_pagos, suma_otros),
    )
    banderas.extend(universo_nomina.banderas_de_totales_descuadrados(ambito, identidades))
    if comprobante.total is not None and comprobante.total < 0:
        banderas.append(Bandera(clave="NETO_NEGATIVO", severidad="alta", ambito=ambito, mensaje=f"El total del CFDI es {comprobante.total}."))

    if suma_deducciones > suma_percepciones + suma_otros + _TOLERANCIA:
        banderas.append(
            Bandera(
                clave="DEDUCCION_MAYOR_PERCEPCION",
                severidad="alta",
                ambito=ambito,
                mensaje=f"Deducciones {suma_deducciones} > percepciones + otros pagos {suma_percepciones + suma_otros}.",
            )
        )

    periodicidad = receptor.periodicidad_pago if receptor else None
    dias = nomina.num_dias_pagados
    if periodicidad in _RANGO_DIAS and dias is not None:
        minimo, maximo = _RANGO_DIAS[periodicidad]
        if not (minimo <= dias <= maximo):
            banderas.append(
                Bandera(
                    clave="DIAS_PAGADOS_ATIPICO",
                    severidad="media",
                    ambito=ambito,
                    mensaje=f"{dias} días para periodicidad {periodicidad} (esperado {minimo}–{maximo}).",
                )
            )
    return banderas


def _agregados_de_una_pasada(
    importes: dict[tuple[int, tuple[str, str, str]], Decimal],
) -> tuple[dict[int, dict[str, Decimal]], Counter[tuple[str, str, str]], dict[tuple[str, str, str], Decimal]]:
    """Recorre `importes` una sola vez para producir los tres agregados que antes se
    recalculaban recorriendo `importes` completo por cada fila y por cada concepto —
    una búsqueda cuadrática en el número de comprobantes × conceptos que en una empresa
    de cientos de empleados con un ejercicio completo puede volver el informe impráctico
    en Python puro. No cambia ningún resultado, solo el costo.

    Devuelve:
    - suma por comprobante y naturaleza (P/O/D), para las identidades de
      `_banderas_del_comprobante`.
    - conteo de comprobantes por concepto, para `EntradaDiccionario.num_comprobantes`.
    - importe total por concepto, para `EntradaDiccionario.importe_total`.
    """
    suma_por_comprobante: dict[int, dict[str, Decimal]] = {}
    conteo_por_concepto: Counter[tuple[str, str, str]] = Counter()
    total_por_concepto: dict[tuple[str, str, str], Decimal] = defaultdict(lambda: _CERO)
    for (comprobante_id, concepto_id), importe in importes.items():
        naturaleza = concepto_id[0]
        fila = suma_por_comprobante.setdefault(comprobante_id, {"P": _CERO, "O": _CERO, "D": _CERO})
        fila[naturaleza] += importe
        conteo_por_concepto[concepto_id] += 1
        total_por_concepto[concepto_id] += importe
    return suma_por_comprobante, conteo_por_concepto, total_por_concepto


def _banderas_de_periodos_traslapados(filas_crudas: list[tuple[Comprobante, Nomina]]) -> list[Bandera]:
    """`PERIODO_TRASLAPADO`: dos nóminas ordinarias del mismo empleado con rangos que se
    intersectan. Casi siempre es un timbrado doble."""
    banderas: list[Bandera] = []
    por_empleado: dict[str, list[tuple[Comprobante, Nomina]]] = defaultdict(list)
    for comprobante, nomina in filas_crudas:
        if nomina.tipo_nomina == "O":
            por_empleado[comprobante.rfc_receptor].append((comprobante, nomina))

    for rfc, registros in por_empleado.items():
        ordenados = sorted(registros, key=lambda par: par[1].fecha_inicial_pago or date.min)
        for anterior, siguiente in zip(ordenados, ordenados[1:]):
            fin_anterior = anterior[1].fecha_final_pago
            inicio_siguiente = siguiente[1].fecha_inicial_pago
            if fin_anterior and inicio_siguiente and inicio_siguiente <= fin_anterior:
                banderas.append(
                    Bandera(
                        clave="PERIODO_TRASLAPADO",
                        severidad="alta",
                        ambito=f"rfc:{rfc}",
                        mensaje=f"{anterior[0].uuid} termina el {fin_anterior} y {siguiente[0].uuid} inicia el {inicio_siguiente}.",
                    )
                )
    return banderas


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(
            columnas=[
                Columna(titulo=titulo, tipo=tipo, sensible=sensible)  # type: ignore[arg-type]
                for titulo, tipo, sensible in _COLUMNAS_FIJAS + _COLUMNAS_TOTALES
            ],
            aviso="La empresa no existe.",
        )

    filas_universo = list((await db.execute(_universo(empresa_id, rfc_empresa, p))).all())
    # Se resuelve ANTES del retorno temprano: si el ETL falló en TODOS los CFDI del rango, la
    # hoja Datos sale vacía y estas banderas son el único rastro de que había nómina que
    # reportar. Un libro vacío sin banderas es indistinguible de "no hubo nómina".
    banderas_fuera = await _banderas_de_no_normalizables(db, empresa_id, rfc_empresa, p)

    if not filas_universo:
        columnas = [
            Columna(titulo=titulo, tipo=tipo, sensible=sensible)  # type: ignore[arg-type]
            for titulo, tipo, sensible in _COLUMNAS_FIJAS + _COLUMNAS_TOTALES
        ]
        return ResultadoInforme(
            columnas=columnas,
            banderas=banderas_fuera,
            aviso="Sin CFDI de nómina en el rango solicitado.",
        )

    ids = [fila[0].comprobante_id for fila in filas_universo]
    importes, descripciones = await _conceptos_por_comprobante(db, ids)
    suma_por_comprobante, conteo_por_concepto, total_por_concepto = _agregados_de_una_pasada(importes)
    # Identidades #4 y #5 de B-00 (gravado y exento del encabezado contra la suma de sus nodos).
    # Este informe reporta "Total gravado"/"Total exento" tal como los declara `nomina_totales`,
    # mientras que B-05 los recalcula de los nodos para la constancia de percepciones: con un CFDI
    # descuadrado los dos daban cifras distintas del mismo concepto para el mismo periodo y ninguno
    # emitía bandera, porque estas dos identidades solo corrían en las pruebas y en el script de
    # verificación. Ver `universo_nomina.banderas_de_gravado_y_exento_descuadrados`.
    banderas_gravado_exento = await universo_nomina.banderas_de_gravado_y_exento_descuadrados(db, ids)

    # Fase 2 y 3: conjunto de columnas dinámicas, con orden determinista (B-02.R5).
    conceptos = sorted(
        {concepto for _, concepto in importes},
        key=lambda c: (_ORDEN_NATURALEZA.get(c[0], 9), c[1], c[2]),
    )

    banderas: list[Bandera] = list(banderas_fuera) + banderas_gravado_exento
    # `banderas_de_estatus` recibe el universo completo, no un comprobante: el colapso por umbral
    # de `ESTATUS_NO_VERIFICADO` es una decisión sobre el conjunto (ver su docstring).
    banderas.extend(universo_nomina.banderas_de_estatus(universo_nomina.comprobantes_y_detalles(filas_universo)))
    diccionario: list[EntradaDiccionario] = []
    etiquetas: dict[tuple[str, str, str], str] = {}
    for concepto in conceptos:
        naturaleza, tipo, clave = concepto
        frecuencias = descripciones.get(concepto, Counter())
        # Desempate explícito y estable: mayor frecuencia primero, y a igualdad la
        # descripción alfabéticamente menor. `Counter.most_common()` desempata por orden
        # de inserción, que depende del orden de filas de un `GROUP BY` sin `ORDER BY` —
        # no garantizado entre corridas (R5). Con dos descripciones empatadas (p. ej.
        # "Sueldo" y "Sueldos" 50/50 en el periodo) el título podía cambiar de una
        # ejecución a otra sin este desempate.
        canonico = min(frecuencias.items(), key=lambda kv: (-kv[1], kv[0]))[0] if frecuencias else None
        alternas = sorted(d for d in frecuencias if d != canonico)
        etiquetas[concepto] = etiqueta(naturaleza, tipo, clave, canonico)

        if len(frecuencias) > 1:
            banderas.append(
                Bandera(
                    clave="CONCEPTO_INCONSISTENTE",
                    severidad="baja",
                    ambito=f"concepto:{naturaleza}/{tipo}/{clave}",
                    mensaje=f"Descripciones distintas para el mismo concepto: {canonico!r} y {alternas}.",
                )
            )
        if not clave:
            banderas.append(
                Bandera(
                    clave="CLAVE_VACIA",
                    severidad="media",
                    ambito=f"concepto:{naturaleza}/{tipo}",
                    mensaje="El concepto no trae clave del patrón; no se puede identificar de forma estable.",
                )
            )

        diccionario.append(
            EntradaDiccionario(
                etiqueta=etiquetas[concepto],
                naturaleza=naturaleza,
                tipo=tipo,
                descripcion_sat=catalogos.descripcion(naturaleza, tipo),
                clave_patron=clave or None,
                concepto_canonico=canonico,
                descripciones_alternas=alternas,
                num_comprobantes=conteo_por_concepto[concepto],
                importe_total=total_por_concepto[concepto],
            )
        )

    columnas = [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS_FIJAS]  # type: ignore[arg-type]
    columnas += [Columna(titulo=etiquetas[c], tipo="monto") for c in conceptos]
    columnas += [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS_TOTALES]  # type: ignore[arg-type]

    filas: list[list[Any]] = []
    for comprobante, nomina, receptor, totales, detalle in filas_universo:
        cid = comprobante.comprobante_id
        suma = suma_por_comprobante.get(cid, {"P": _CERO, "O": _CERO, "D": _CERO})
        banderas.extend(_banderas_del_comprobante(comprobante, nomina, receptor, totales, suma["P"], suma["D"], suma["O"]))

        # CURP y NSS salen en claro: `Columna(sensible=True)` ya lo declaró arriba, y es
        # el motor (`app.informes.excel.escribir_libro`) quien enmascara, no esta consulta
        # (ronda de corrección 1 de la tarea 10).
        curp = receptor.curp if receptor else None
        nss = receptor.nss if receptor else None

        fija: list[Any] = [
            nomina.fecha_pago.year if nomina.fecha_pago else None,
            nomina.fecha_pago.month if nomina.fecha_pago else None,
            comprobante.uuid,
            detalle.serie if detalle else None,
            comprobante.folio,
            comprobante.estatus.value,
            nomina.tipo_nomina,
            nomina.fecha_pago,
            nomina.fecha_inicial_pago,
            nomina.fecha_final_pago,
            nomina.num_dias_pagados,
            receptor.periodicidad_pago if receptor else None,
            comprobante.rfc_emisor,
            nomina.registro_patronal,
            comprobante.rfc_receptor,
            # "Nombre empleado" es `comprobante_detalle.nombre_receptor`, el nombre del
            # **trabajador**. Hasta la revisión final aquí iba `comprobante.razon_social_emisor` —el
            # nombre de la EMPRESA— con la justificación de que "no hay campo de razón social del
            # receptor en el modelo": es falsa desde la fase 2 (`ComprobanteDetalle.nombre_receptor`
            # existe y B-05/B-07/B-10 ya lo usan), y el resultado era un papel de trabajo fiscal con
            # el nombre del patrón repetido en todas las filas de la columna "Nombre empleado".
            detalle.nombre_receptor if detalle else None,
            curp,
            nss,
            receptor.num_empleado if receptor else None,
            receptor.departamento if receptor else None,
            receptor.puesto if receptor else None,
            receptor.tipo_regimen if receptor else None,
            receptor.salario_base_cot_apor if receptor else None,
            receptor.salario_diario_integrado if receptor else None,
        ]
        # R-T7: cero, no vacío.
        dinamicas: list[Any] = [importes.get((cid, concepto), _CERO) for concepto in conceptos]
        totales_fila: list[Any] = [
            totales.total_sueldos if totales else None,
            totales.total_separacion_indemnizacion if totales else None,
            totales.total_jubilacion_pension_retiro if totales else None,
            nomina.total_percepciones,
            totales.total_gravado if totales else None,
            totales.total_exento if totales else None,
            nomina.total_otros_pagos,
            nomina.total_deducciones,
            comprobante.total,
        ]
        filas.append(fija + dinamicas + totales_fila)

    banderas.extend(_banderas_de_periodos_traslapados([(fila[0], fila[1]) for fila in filas_universo]))

    return ResultadoInforme(columnas=columnas, filas=filas, banderas=banderas, diccionario=diccionario)
