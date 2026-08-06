"""B-01 · Nómina agrupada por catálogo SAT (§B-01 del documento fuente).

Hermano de B-02 (`app.informes.b02_conceptos_patron`): mismo universo de CFDI de nómina,
pero con un propósito exactamente opuesto en la generación de columnas.

**La diferencia esencial, que es todo el propósito de este informe (B-01.R1).** B-02
genera una columna por cada concepto **observado en los datos**, con las claves internas
del patrón. B-01 genera una columna por cada **tipo del catálogo del SAT**
(`app.informes.catalogos.tipos_de`), esté o no en los datos, con cero cuando no hay
movimiento. Eso lo hace comparable entre periodos y entre organizaciones —el conjunto de
columnas no cambia de un mes a otro— que es lo que se necesita para alimentar pólizas
contables.

**Se agrupa por tipo, no por `(tipo, clave)` como B-02.** Dos nodos con el mismo tipo del
catálogo pero claves internas distintas del patrón (p. ej. `("001", "001", ...)` y
`("001", "077", ...)`) caen en la **misma** columna: es exactamente lo contrario de
B-02.R3/R-T9, y el motivo de que este informe exista aparte de B-02.

**El costo: más de 150 columnas.** 44 tipos de percepción + 107 de deducción + 10 de otro
pago (contados en la tarea 3 sobre `app.informes.catalogos`). Por eso existe
`solo_tipos_con_movimiento` (B-01.R2): restringe las columnas dinámicas al conjunto
observado en el periodo. Al activarlo el informe **deja de ser comparable** entre
periodos, y por eso emite `CONJUNTO_REDUCIDO` —una bandera informativa, no un error— para
que quien reciba el Excel no lo compare contra otro mes creyendo que las columnas
coinciden.

**Universo y banderas de estatus compartidos con B-02** (`app.informes.universo_nomina`):
mismo `join`, mismo margen de timbrado para no perder recibos rotos de la hoja `Datos`,
mismas banderas `SIN_NORMALIZAR` / `COMPLEMENTO_AUSENTE` / `DATOS_DE_CORRIDA_ANTERIOR` /
`ESTATUS_NO_VERIFICADO` / `COMPROBANTE_CANCELADO`. Ver ese módulo para el razonamiento
completo — no se repite aquí a propósito: si dos informes del mismo periodo lo calculan
cada uno por su cuenta, en cuanto diverjan un carácter darán totales distintos entre sí.

**La identidad del ISR (B-00 #9) sí se comprueba aquí y no en B-02.** B-02 agrupa por
concepto del patrón y no tiene una noción estable de "el tipo 002 de deducción"; B-01 sí,
porque agrupa por tipo del catálogo. Así que `nomina_totales.total_impuestos_retenidos`
se coteja contra la suma de la columna `D 002` (ISR), la novena identidad de B-00 que
B-02 deja pendiente explícitamente para este informe.
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
from app.informes.base import Bandera, Columna, EntradaDiccionario, ResultadoInforme
from app.informes.identidades_b00 import CLAVE_TIPO_DEDUCCION_ISR
from app.models.empresa import Empresa
from app.models.nomina import NominaDeduccion, NominaOtroPago, NominaPercepcion

CLAVE = "B-01"
NOMBRE = "Nómina agrupada por catálogo SAT"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por CFDI de nómina, con una columna por cada tipo del catálogo del SAT de "
    "percepción, deducción y otro pago, esté o no en los datos. Comparable entre periodos "
    "y organizaciones; pensado para alimentar pólizas contables."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Ver la constante homónima de `app.informes.b02_conceptos_patron`: mismo razonamiento
(todo el grupo B declara `("N",)`), mismo consumidor (el pre-vuelo del ETL en
`app.worker.tasks._generar_informe_async`)."""

_CERO = Decimal("0")

_ORDEN_NATURALEZA: tuple[str, ...] = ("P", "O", "D")
"""Orden de las naturalezas en las columnas dinámicas: el orden de lectura de un recibo de
nómina (percepciones, otros pagos, deducciones), igual que B-02."""

_CLAVE_OTRO_PAGO_SUBSIDIO = "002"
"""Tipo del catálogo `c_TipoOtroPago` para "Subsidio para el empleo efectivamente entregado
al trabajador" (B-00). De ahí salen las columnas fijas `Subsidio causado` (su
`subsidio_causado`) y `Subsidio aplicado` (su `importe`)."""


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango, sobre `nomina.fecha_pago` (R-T6).")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    tipo_nomina: Literal["O", "E", "AMBOS"] = Field("AMBOS", description="Ordinaria, extraordinaria o ambas.")
    incluir_cancelados: bool = Field(False, description="Por defecto solo vigentes (R-T1).")
    solo_tipos_con_movimiento: bool = Field(
        False,
        description=(
            "Reduce las columnas dinámicas al conjunto observado en el periodo (B-01.R2), en vez "
            "del catálogo completo (más de 150 columnas). Rompe la comparabilidad entre periodos "
            "y organizaciones, y lo señala con la bandera informativa `CONJUNTO_REDUCIDO`."
        ),
    )
    enmascarar_datos_personales: bool = Field(
        True,
        description=(
            "Enmascara CURP, NSS y cuenta bancaria (spec §8). Lo aplica el motor de informes "
            "(`app.informes.excel.escribir_libro`) sobre las columnas que esta consulta marca "
            "como `sensible=True`, no esta consulta directamente."
        ),
    )


# Columnas fijas: identificación, nómina, patrón y empleado. El tercer elemento es
# `sensible` (spec §8): CURP y NSS son las únicas columnas fijas con datos personales.
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

# Columnas de totales y subsidio: van después de las dinámicas del catálogo.
_COLUMNAS_TOTALES: tuple[tuple[str, str, bool], ...] = (
    ("Total sueldos", "monto", False),
    ("Total separación indemnización", "monto", False),
    ("Total jubilación pensión retiro", "monto", False),
    ("Total percepciones", "monto", False),
    ("Total gravado", "monto", False),
    ("Total exento", "monto", False),
    ("Total otros pagos", "monto", False),
    ("Total deducciones", "monto", False),
    ("Subsidio causado", "monto", False),
    ("Subsidio aplicado", "monto", False),
    ("Total (neto)", "monto", False),
)


def _titulo(naturaleza: str, tipo: str, descripcion_sat: str) -> str:
    """`naturaleza tipo descripción`, separados por espacios.

    A diferencia de `b02_conceptos_patron.etiqueta`, que usa `SEPARADOR_ETIQUETA` (`¦`)
    porque su etiqueta lleva la clave y el concepto **libres del patrón** —que pueden traer
    diagonales y hacen ambiguo cualquier separador de texto corriente (R-T8)—, aquí no hay
    clave del patrón ni texto libre: la descripción es la del catálogo del SAT, fija por
    tipo. No hay ambigüedad que evitar, y un espacio se lee mejor en la cabecera de un Excel.
    """
    return f"{naturaleza} {tipo} {descripcion_sat}"


def _columnas_base() -> list[Columna]:
    """Columnas fijas y de totales, sin las dinámicas del catálogo: lo que se devuelve
    cuando no hay universo que reportar (empresa inexistente o sin CFDI en el rango)."""
    return [
        Columna(titulo=titulo, tipo=tipo, sensible=sensible)  # type: ignore[arg-type]
        for titulo, tipo, sensible in _COLUMNAS_FIJAS + _COLUMNAS_TOTALES
    ]


async def _importes_por_comprobante_y_tipo(db: AsyncSession, ids: list[int]) -> dict[int, dict[tuple[str, str], Decimal]]:
    """Suma por `(comprobante_id, (naturaleza, tipo))` —**sin** la clave del patrón, que es
    justo la diferencia con B-02 (B-01.R1): dos nodos del mismo tipo con claves internas
    distintas caen en la misma celda."""
    importes: dict[int, dict[tuple[str, str], Decimal]] = defaultdict(dict)
    if not ids:
        return importes

    fuentes = (
        ("P", NominaPercepcion, NominaPercepcion.tipo_percepcion, NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento),
        ("O", NominaOtroPago, NominaOtroPago.tipo_otro_pago, NominaOtroPago.importe),
        ("D", NominaDeduccion, NominaDeduccion.tipo_deduccion, NominaDeduccion.importe),
    )
    for naturaleza, modelo, columna_tipo, expresion_importe in fuentes:
        filas = await db.execute(
            select(modelo.comprobante_id, columna_tipo.label("tipo"), func.sum(expresion_importe).label("importe"))
            .where(modelo.comprobante_id.in_(ids))
            .group_by(modelo.comprobante_id, columna_tipo)
        )
        for fila in filas:
            importe = fila.importe if isinstance(fila.importe, Decimal) else Decimal(str(fila.importe))
            importes[int(fila.comprobante_id)][(naturaleza, str(fila.tipo))] = importe
    return importes


async def _subsidio_causado_por_comprobante(db: AsyncSession, ids: list[int]) -> dict[int, Decimal]:
    """`Subsidio causado` (B-00): `SUM(subsidio_causado)` del otro pago tipo
    `_CLAVE_OTRO_PAGO_SUBSIDIO`. `Subsidio aplicado` sale de `importes` (su `importe`, ya
    sumado por tipo en `_importes_por_comprobante_y_tipo`) y no necesita esta consulta
    aparte."""
    if not ids:
        return {}
    filas = await db.execute(
        select(NominaOtroPago.comprobante_id, func.sum(NominaOtroPago.subsidio_causado))
        .where(NominaOtroPago.comprobante_id.in_(ids), NominaOtroPago.tipo_otro_pago == _CLAVE_OTRO_PAGO_SUBSIDIO)
        .group_by(NominaOtroPago.comprobante_id)
    )
    resultado: dict[int, Decimal] = {}
    for comprobante_id, suma in filas:
        if suma is None:
            continue
        resultado[int(comprobante_id)] = suma if isinstance(suma, Decimal) else Decimal(str(suma))
    return resultado


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=_columnas_base(), aviso="La empresa no existe.")

    filas_universo = list((await db.execute(universo_nomina.universo(empresa_id, rfc_empresa, p))).all())
    # Se resuelve ANTES del retorno temprano, igual que en B-02: si el ETL falló en TODOS los
    # CFDI del rango, la hoja Datos sale vacía y estas banderas son el único rastro de que
    # había nómina que reportar.
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, rfc_empresa, p)

    if not filas_universo:
        return ResultadoInforme(
            columnas=_columnas_base(),
            banderas=banderas_fuera,
            aviso="Sin CFDI de nómina en el rango solicitado.",
        )

    ids = [fila[0].comprobante_id for fila in filas_universo]
    importes = await _importes_por_comprobante_y_tipo(db, ids)
    subsidio_causado_por_cid = await _subsidio_causado_por_comprobante(db, ids)

    # B-01.R2: el conjunto de tipos con al menos un nodo en el periodo, cuando
    # `solo_tipos_con_movimiento` reduce el catálogo completo a lo observado.
    observados: set[tuple[str, str]] = {clave for por_tipo in importes.values() for clave in por_tipo}

    banderas: list[Bandera] = list(banderas_fuera)
    if p.solo_tipos_con_movimiento:
        banderas.append(
            Bandera(
                clave="CONJUNTO_REDUCIDO",
                severidad="baja",
                ambito="informe",
                mensaje=(
                    "`solo_tipos_con_movimiento` está activo: las columnas dinámicas son solo las "
                    "observadas en este periodo, no el catálogo completo del SAT. Este informe NO es "
                    "comparable contra uno generado sin este parámetro, ni contra otro periodo (B-01.R2)."
                ),
            )
        )

    # Fase 2: conjunto de columnas dinámicas, orden determinista por naturaleza y luego por
    # clave como texto (ya lo entrega `catalogos.tipos_de`, ordenado — B-01.R1 más R-T8).
    columnas_dinamicas: list[tuple[str, str, str]] = [
        (naturaleza, tipo, descripcion_sat)
        for naturaleza in _ORDEN_NATURALEZA
        for tipo, descripcion_sat in catalogos.tipos_de(naturaleza)
        if not p.solo_tipos_con_movimiento or (naturaleza, tipo) in observados
    ]

    columnas = [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS_FIJAS]  # type: ignore[arg-type]
    columnas += [Columna(titulo=_titulo(naturaleza, tipo, descripcion_sat), tipo="monto") for naturaleza, tipo, descripcion_sat in columnas_dinamicas]
    columnas += [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS_TOTALES]  # type: ignore[arg-type]

    # Diccionario: una entrada por columna dinámica, con su descripción del catálogo del SAT.
    # `clave_patron` y `concepto_canonico` no aplican aquí (no hay clave ni texto libre del
    # patrón involucrados, a diferencia de B-02) y quedan en `None` a propósito.
    conteo_por_tipo: Counter[tuple[str, str]] = Counter()
    total_por_tipo: dict[tuple[str, str], Decimal] = defaultdict(lambda: _CERO)
    for por_tipo in importes.values():
        for clave, importe in por_tipo.items():
            conteo_por_tipo[clave] += 1
            total_por_tipo[clave] += importe

    diccionario: list[EntradaDiccionario] = [
        EntradaDiccionario(
            etiqueta=_titulo(naturaleza, tipo, descripcion_sat),
            naturaleza=naturaleza,
            tipo=tipo,
            descripcion_sat=descripcion_sat,
            clave_patron=None,
            concepto_canonico=None,
            num_comprobantes=conteo_por_tipo[(naturaleza, tipo)],
            importe_total=total_por_tipo[(naturaleza, tipo)],
        )
        for naturaleza, tipo, descripcion_sat in columnas_dinamicas
    ]

    filas: list[list[Any]] = []
    for comprobante, nomina, receptor, totales, detalle in filas_universo:
        cid = comprobante.comprobante_id
        por_tipo = importes.get(cid, {})
        suma_percepciones = sum((importe for (naturaleza, _tipo), importe in por_tipo.items() if naturaleza == "P"), _CERO)
        suma_deducciones = sum((importe for (naturaleza, _tipo), importe in por_tipo.items() if naturaleza == "D"), _CERO)
        suma_otros = sum((importe for (naturaleza, _tipo), importe in por_tipo.items() if naturaleza == "O"), _CERO)

        ambito = f"uuid:{comprobante.uuid}"
        banderas.extend(universo_nomina.banderas_de_estatus(comprobante, detalle))
        identidades = (
            ("total_percepciones", nomina.total_percepciones, suma_percepciones),
            ("total_deducciones", nomina.total_deducciones, suma_deducciones),
            ("total_otros_pagos", nomina.total_otros_pagos, suma_otros),
            # Novena identidad de B-00: aquí sí se puede cotejar (a diferencia de B-02,
            # que agrupa por concepto del patrón, no por tipo del catálogo).
            (
                "total_impuestos_retenidos",
                totales.total_impuestos_retenidos if totales else None,
                por_tipo.get(("D", CLAVE_TIPO_DEDUCCION_ISR), _CERO),
            ),
        )
        banderas.extend(universo_nomina.banderas_de_totales_descuadrados(ambito, identidades))

        curp = receptor.curp if receptor else None
        nss = receptor.nss if receptor else None
        subsidio_causado = subsidio_causado_por_cid.get(cid, _CERO)
        subsidio_aplicado = por_tipo.get(("O", _CLAVE_OTRO_PAGO_SUBSIDIO), _CERO)

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
            comprobante.razon_social_emisor,
            curp,
            nss,
            receptor.num_empleado if receptor else None,
            receptor.departamento if receptor else None,
            receptor.puesto if receptor else None,
            receptor.tipo_regimen if receptor else None,
            receptor.salario_base_cot_apor if receptor else None,
            receptor.salario_diario_integrado if receptor else None,
        ]
        # R-T7: cero, no vacío. Es el corazón de B-01.R1: un tipo del catálogo sin
        # movimiento en este comprobante igual tiene su celda, en cero.
        dinamicas: list[Any] = [por_tipo.get((naturaleza, tipo), _CERO) for naturaleza, tipo, _ in columnas_dinamicas]
        totales_fila: list[Any] = [
            totales.total_sueldos if totales else None,
            totales.total_separacion_indemnizacion if totales else None,
            totales.total_jubilacion_pension_retiro if totales else None,
            nomina.total_percepciones,
            totales.total_gravado if totales else None,
            totales.total_exento if totales else None,
            nomina.total_otros_pagos,
            nomina.total_deducciones,
            subsidio_causado,
            subsidio_aplicado,
            comprobante.total,
        ]
        filas.append(fija + dinamicas + totales_fila)

    return ResultadoInforme(columnas=columnas, filas=filas, banderas=banderas, diccionario=diccionario)
