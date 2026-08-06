"""B-10 · Validación de datos del receptor (§B-10 del documento fuente).

**El propósito, y por qué este informe importa aunque no lleve un solo importe.** Audita la
calidad de los datos del trabajador timbrados en el complemento de nómina: RFC, CURP, NSS,
cuenta bancaria, fechas de relación laboral, SBC y SDI. Los errores que detecta generan
requerimientos del SAT y problemas de acreditación ante el IMSS, y son **invisibles en los
informes de importes**: los otros cinco informes del grupo B (B-01, B-02, B-04, B-05, B-07)
pueden cuadrar perfectamente con un NSS mal capturado o una CURP que no corresponde al RFC,
porque ninguno de ellos mira esos campos, solo los importes.

**Grano: una fila por hallazgo, `(rfc_receptor, clave_validación)`.** Es el formato
accionable: cada fila es algo que corregir. Se descartó a propósito el formato pivotado (una
columna por validación, una fila por empleado) que también ofrece la ficha B-10: expondría
un parámetro sin efecto (`severidad_minima` no tendría nada que filtrar de forma limpia en un
pivote) y está fuera del alcance declarado de esta tarea.

**Las 21 validaciones en alcance, en cuatro grupos con dificultad propia:**

1. **Estructura** (`app.informes.validadores`, puro, sin BD): RFC, CURP, NSS y cuenta
   bancaria por expresión regular y dígito verificador.
2. **De conjunto** (`CURP_DUPLICADA`, `RFC_DUPLICADO`, `NSS_DUPLICADO`): no se ven mirando un
   CFDI aislado, hay que cruzar **todos** los comprobantes del rango, no solo el más reciente
   de cada empleado.
3. **Entre periodos** (`DATOS_CAMBIANTES`): un mismo RFC con distinta CURP, NSS o fecha de
   inicio de relación laboral en quincenas distintas — error de captura que solo aparece
   comparando periodos.
4. **Derivadas de importes** (`SDI_MENOR_SD_IMPLICITO`): el SDI declarado contra el sueldo
   diario que se deduce del propio CFDI (`Σ percepción '001' / días pagados`).

Las dos que la ficha original también pide (`SBC_SOBRE_TOPE`, `SBC_BAJO_MINIMO`) **no** se
implementan: necesitan la UMA y el salario mínimo vigente, que viven en una tabla de
configuración de la fase 3 que todavía no existe. `test_las_dos_validaciones_de_sbc_diferidas_no_aparecen`
en `tests/test_informe_b10.py` verifica que de verdad no aparecen, para que su ausencia sea
una decisión comprobada y no un olvido silencioso.

**B-10.R1 — SBC y SDI son conceptos distintos, y hay que respetarlo.** El SBC es la base de
cotización ante el IMSS (topada a 25 UMA); el SDI es el salario diario integrado de los
artículos 84 y 89 de la LFT, base de indemnizaciones. Un SDI **inferior** al SBC es
teóricamente posible aunque infrecuente (los conceptos usan bases distintas), así que
`SDI_MENOR_SBC` es severidad **media**, no un error absoluto como `SBC_CERO` o `SDI_CERO`.

**Reglas de aplicabilidad — cuándo una validación se omite (no cuándo se relaja).** Las 21
validaciones son en principio independientes entre sí, pero varias necesitan un dato que
puede faltar, y comparar contra `None` no está definido. Se omiten (no se marcan, ni en un
sentido ni en el otro) en estos casos, todos documentados aquí para que ninguno sea un olvido:

- **Comparaciones numéricas** (`SBC_CERO`, `SDI_CERO`, `SDI_MENOR_SBC`,
  `SDI_MENOR_SD_IMPLICITO`): se omiten si falta el operando (`sbc`/`sdi`/`num_dias_pagados`
  en `None`, o días pagados `<= 0` para el implícito, que dividiría por cero). Un campo
  ausente no satisface ninguna comparación numérica definida; no se interpreta "ausente"
  como "cero" porque la ficha no lo pide y esa interpretación no distinguiría un dato que
  falta de un dato que de verdad es cero.
- **`FECHA_INICIO_POSTERIOR` y `ANTIGUEDAD_INCONSISTENTE`**: se omiten si falta cualquiera de
  las dos fechas que comparan (o, para la segunda, si falta `@Antigüedad`).
- **`CURP_ENTIDAD`** se omite si la CURP ya falló `CURP_ESTRUCTURA`: sin la forma general
  correcta, las posiciones 12-13 no son fiables y marcar el mismo defecto dos veces con dos
  claves distintas no añade información, solo ruido.
- **`NSS_DIGITO_VERIFICADOR`** se omite si el NSS no tiene longitud 11: el cálculo de Luhn
  sobre una cadena de longitud incorrecta no es significativo, y `NSS_LONGITUD` ya señala ese
  defecto.
- **`NSS_LONGITUD`, `NSS_DIGITO_VERIFICADOR` y `CUENTA_INVALIDA`** se omiten cuando el campo
  está **vacío** (no solo mal formado). Es una decisión de diseño explícita, no forzada por
  ninguna prueba de la tarea: la ficha declara `NSS_FALTANTE` condicionado a
  `tipo_regimen='02'` (no incondicional), lo que implica que un NSS vacío bajo otro régimen
  (asimilados a salarios, por ejemplo) es un estado legítimo, no un defecto — y evaluar
  longitud o dígito verificador sobre un campo que se espera vacío sería puro ruido en el
  caso más común. `BANCO_SIN_CUENTA` cumple el mismo papel para la cuenta bancaria: un
  empleado sin banco registrado y sin cuenta (pagado en efectivo) no tiene nada que corregir;
  `CUENTA_INVALIDA` solo tiene sentido sobre una cuenta que sí se capturó. **Esta decisión se
  reporta explícitamente como duda** al cierre de la tarea, por si el criterio real de la
  empresa fuera distinto.
- **`RFC_CURP_INCONSISTENTE`** se omite si la CURP es `None` (la ausencia ya la cubre
  `CURP_ESTRUCTURA`, que sí se evalúa siempre porque la CURP es obligatoria en el complemento
  de nómina y el RFC nunca es `NULL` en el esquema).
- **`CURP_DUPLICADA`, `RFC_DUPLICADO`, `NSS_DUPLICADO` y `DATOS_CAMBIANTES`** ignoran los
  valores vacíos: un CURP o NSS vacío compartido por varios RFC no es una duplicidad real de
  identidad, es ausencia de dato en varios lados a la vez, y ya la señalan otras reglas.

**Identidad del empleado: `comprobante_detalle.nombre_receptor`, no
`comprobante.razon_social_emisor`.** B-01/B-02 usan `razon_social_emisor` para la columna
"Nombre empleado" a falta de otra fuente en su momento; B-04 ya señaló que ese dato es la
razón social del **emisor** (el patrón), no del empleado, y B-05/B-07 corrigieron usando el
campo correcto. Este informe sigue el criterio corregido.

**Validaciones por empleado (grupos 1 y 4): la ÚLTIMA fotografía, no todas.** El brief lo
pide explícito ("trae el último `nomina_receptor` por `rfc_receptor`"): para RFC, CURP, NSS,
SBC, SDI, fechas y el SDI implícito se usa el comprobante con `fecha_pago` más reciente de
cada empleado en el rango — mismo criterio de "última fotografía" que B-04/B-05/B-07 (el
universo viene ordenado ascendente por `fecha_pago`, así que sobrescribir en el orden de
iteración deja la más reciente). Las validaciones de **conjunto** y **entre periodos**
(grupos 2 y 3) sí recorren todos los comprobantes del rango, porque su propósito es
precisamente comparar entre ellos.

**Banderas del informe: solo las del universo compartido, no las de estatus.** Este informe
no emite banderas del propio hallazgo (los hallazgos SON las filas: cada uno ya lleva su
severidad y su descripción). Sí hereda `SIN_NORMALIZAR`/`COMPLEMENTO_AUSENTE`
(`universo_nomina.banderas_de_no_normalizables`), porque un CFDI que el ETL no pudo
normalizar tampoco puede auditarse. No se incluyen `ESTATUS_NO_VERIFICADO`/
`COMPROBANTE_CANCELADO`/`DATOS_DE_CORRIDA_ANTERIOR` (`universo_nomina.banderas_de_estatus`):
esas describen el estatus del CFDI ante el SAT, un eje distinto de la calidad de los datos
del receptor que este informe audita, y ya las cubre B-02 para quien necesite esa dimensión.

**Cero N+1 (regla 11).** El universo se trae con una sola consulta
(`universo_nomina.universo`, con `tipo_nomina` fijo en `AMBOS`: la calidad de los datos del
receptor no depende de si la nómina es ordinaria o extraordinaria, y filtrar produciría
"últimas fotografías" incompletas). Las percepciones `'001'` para `SDI_MENOR_SD_IMPLICITO` se
suman con una segunda consulta agregada, sobre los comprobantes de la última fotografía de
cada empleado únicamente (no sobre todo el universo). Ninguna consulta se hace por empleado.

**Este informe es el que más datos personales expone del catálogo** (CURP, NSS y cuenta
bancaria son literalmente el objeto de las validaciones), así que `CURP` y `NSS` se declaran
`sensible=True` (spec §8); el motor de informes (`app.informes.excel.escribir_libro`) es
quien enmascara, esta consulta solo declara.

**`Decimal` de punta a punta; sin `round()` ni `quantize()`** (el redondeo lo hace
`app.informes.excel` al escribir la celda)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import universo_nomina, validadores as v
from app.informes.base import Columna, ResultadoInforme, Severidad
from app.models.empresa import Empresa
from app.models.nomina import NominaPercepcion

CLAVE = "B-10"
NOMBRE = "Validación de datos del receptor"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por hallazgo (empleado, validación). Audita la calidad de los datos del "
    "trabajador timbrados en el complemento de nómina — RFC, CURP, NSS, cuenta bancaria, "
    "fechas y SBC/SDI —, errores que generan requerimientos del SAT y problemas de "
    "acreditación ante el IMSS y que los informes de importes no pueden ver."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Ver la constante homónima de `app.informes.b02_conceptos_patron`: mismo razonamiento
(todo el grupo B declara `("N",)`) y mismo consumidor (el pre-vuelo del ETL en
`app.worker.tasks._generar_informe_async`)."""

_CERO = Decimal("0")
_TOLERANCIA_SDI_SBC = Decimal("0.8")
"""`SDI_MENOR_SBC` (B-10.R1, media): el SDI se considera anómalamente bajo frente al SBC solo
por debajo del 80% de este — un SDI algo menor que el SBC es teóricamente normal (bases
distintas, ver docstring del módulo); muy por debajo ya es sospechoso de captura."""

_TOLERANCIA_ANTIGUEDAD_DIAS = 14
"""Dos semanas: absorbe la aproximación de `validadores.antiguedad_iso_a_dias` (años de 365
días, meses de 30) frente al cálculo exacto por fecha."""

_ORDEN_SEVERIDAD: dict[Severidad, int] = {"alta": 0, "media": 1, "baja": 2}
"""Orden de clasificación de filas (alta, media, baja) y de filtrado por `severidad_minima`:
a menor número, más severa."""

# Claves y descripciones de "puesto/departamento vacío" (§ficha B-10): además de None y
# cadena vacía, los valores centinela que el patrón usa para decir "no aplica" sin dejar el
# campo realmente vacío.
_VALORES_VACIOS_TEXTO = frozenset({"", "ninguno", "n/a", "na"})


class Parametros(BaseModel):
    fecha_desde: date = Field(description="Inicio del rango, sobre `nomina.fecha_pago`.")
    fecha_hasta: date = Field(description="Fin del rango, inclusivo.")
    severidad_minima: Literal["alta", "media", "baja"] = Field(
        "baja", description="Solo se listan hallazgos de esta severidad o más alta (alta > media > baja)."
    )
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
    """Adaptador local a `universo_nomina.ParametrosUniverso`. B-10 no expone `tipo_nomina`:
    la calidad de los datos del receptor no depende de si la nómina es ordinaria o
    extraordinaria, y filtrar por tipo dejaría "últimas fotografías" incompletas para
    empleados cuyo CFDI más reciente del rango fuera del tipo excluido (mismo razonamiento
    que `b04_matriz_empleado_periodo._ParametrosUniverso` y `b07_prestamos._ParametrosUniverso`)."""

    fecha_desde: date
    fecha_hasta: date
    incluir_cancelados: bool
    tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"


_COLUMNAS: tuple[tuple[str, str, bool], ...] = (
    ("RFC empleado", "texto", False),
    ("Nombre", "texto", False),
    ("Núm. empleado", "texto", False),
    ("Validación", "texto", False),
    ("Severidad", "texto", False),
    ("Descripción del hallazgo", "texto", False),
    ("CURP", "texto", True),
    ("NSS", "texto", True),
    ("SBC", "monto", False),
    ("SDI", "monto", False),
    ("Fecha inicio relación laboral", "fecha", False),
    ("Fecha final de pago", "fecha", False),
)


def _columnas() -> list[Columna]:
    return [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS]  # type: ignore[arg-type]


@dataclass(slots=True)
class _Identidad:
    """Última fotografía de `nomina_receptor` de un empleado en el rango, más lo que hace
    falta de `Comprobante`/`ComprobanteDetalle`/`Nomina` para evaluar y desplegar sus
    hallazgos."""

    comprobante_id: int
    rfc: str
    nombre: str | None
    num_empleado: str | None
    curp: str | None
    nss: str | None
    tipo_regimen: str | None
    sbc: Decimal | None
    sdi: Decimal | None
    fecha_inicio_rel_laboral: date | None
    fecha_final_pago: date | None
    num_dias_pagados: Decimal | None
    antiguedad: str | None
    banco: str | None
    cuenta_bancaria: str | None
    puesto: str | None
    departamento: str | None


@dataclass(slots=True)
class _Hallazgo:
    rfc: str
    clave: str
    severidad: Severidad
    mensaje: str


def _a_decimal(valor: Decimal | float | None) -> Decimal | None:
    """`Numeric` puede llegar como `Decimal` o como `float` según el atributo mapeado; nunca
    se opera en binario (mismo patrón que `identidades_b00._dec`), y `None` se conserva como
    `None` (no como cero: las comparaciones numéricas de este informe se omiten sobre datos
    ausentes, ver docstring del módulo)."""
    if valor is None:
        return None
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def _vacio_texto(valor: str | None) -> bool:
    """`PUESTO_VACIO`/`DEPARTAMENTO_VACIO`: `None`, cadena vacía, o los centinelas de "no
    aplica" que el patrón captura sin dejar el campo realmente vacío (`Ninguno`, `N/A`),
    comparados sin distinguir mayúsculas ni espacios sobrantes."""
    if valor is None:
        return True
    return valor.strip().lower() in _VALORES_VACIOS_TEXTO


def _vacio(valor: str | None) -> bool:
    """Vacío para NSS/cuenta bancaria: `None` o cadena vacía tras quitar espacios."""
    return valor is None or valor.strip() == ""


async def _percepciones_001_por_comprobante(db: AsyncSession, ids: list[int]) -> dict[int, Decimal]:
    """`SUM(importe_gravado + importe_exento)` de las percepciones `tipo_percepcion='001'`
    (Sueldo), por comprobante — una sola consulta agregada (regla 11: cero N+1), acotada a
    los comprobantes de la última fotografía de cada empleado, no a todo el universo."""
    if not ids:
        return {}
    filas = await db.execute(
        select(NominaPercepcion.comprobante_id, func.sum(NominaPercepcion.importe_gravado + NominaPercepcion.importe_exento))
        .where(NominaPercepcion.comprobante_id.in_(ids), NominaPercepcion.tipo_percepcion == "001")
        .group_by(NominaPercepcion.comprobante_id)
    )
    resultado: dict[int, Decimal] = {}
    for comprobante_id, suma in filas:
        decimal_suma = _a_decimal(suma)
        if decimal_suma is not None:
            resultado[int(comprobante_id)] = decimal_suma
    return resultado


def _hallazgos_estructurales_y_derivados(identidad: _Identidad, percepciones_001: Decimal | None) -> list[_Hallazgo]:
    """Grupos 1 (estructura) y 4 (derivadas de importes) más las validaciones de fecha y de
    campos de texto vacíos: todo lo que se evalúa sobre la ÚLTIMA fotografía de un solo
    empleado, sin cruzar con otros CFDI del rango."""
    hallazgos: list[_Hallazgo] = []
    rfc = identidad.rfc

    def _marca(clave: str, severidad: Severidad, mensaje: str) -> None:
        hallazgos.append(_Hallazgo(rfc=rfc, clave=clave, severidad=severidad, mensaje=mensaje))

    # --- Estructura ---
    if not v.rfc_persona_fisica_valido(rfc):
        _marca("RFC_ESTRUCTURA", "alta", f"El RFC {rfc!r} no cumple la estructura de persona física.")

    curp_estructura_valida = v.curp_valida(identidad.curp)
    if not curp_estructura_valida:
        _marca("CURP_ESTRUCTURA", "alta", f"La CURP {identidad.curp!r} no cumple la estructura esperada.")
    elif not v.curp_entidad_valida(identidad.curp):
        # Solo se evalúa si la estructura general ya es válida (ver docstring del módulo):
        # sin eso, las posiciones 12-13 no son fiables y ya se marcó CURP_ESTRUCTURA.
        _marca("CURP_ENTIDAD", "media", f"La CURP {identidad.curp!r} no trae una clave de entidad federativa reconocida en las posiciones 12-13.")

    if identidad.curp is not None and not _vacio(identidad.curp) and not _vacio(rfc):
        if rfc[:10] != identidad.curp[:10]:
            _marca(
                "RFC_CURP_INCONSISTENTE",
                "alta",
                f"Las primeras 10 posiciones del RFC ({rfc[:10]!r}) no coinciden con las de la CURP ({identidad.curp[:10]!r}).",
            )

    if not _vacio(identidad.nss):
        nss = identidad.nss
        assert nss is not None  # para mypy: `_vacio` ya descartó `None`
        if len(nss) != 11:
            _marca("NSS_LONGITUD", "media", f"El NSS {nss!r} tiene {len(nss)} caracteres; se esperan 11.")
        elif not v.nss_digito_verificador_valido(nss):
            # Solo se evalúa con longitud correcta (ver docstring): Luhn sobre una longitud
            # equivocada no es significativo y ya se marcó NSS_LONGITUD.
            _marca("NSS_DIGITO_VERIFICADOR", "media", f"El NSS {nss!r} no cumple el dígito verificador (Luhn).")
    elif identidad.tipo_regimen == "02":
        _marca("NSS_FALTANTE", "alta", "El NSS está vacío con `tipo_regimen='02'` (régimen obligatorio de cotización IMSS).")

    # --- SBC / SDI (B-10.R1) ---
    sbc, sdi = identidad.sbc, identidad.sdi
    if identidad.tipo_regimen == "02" and sbc is not None and sbc <= 0:
        _marca("SBC_CERO", "alta", f"El SBC declarado es {sbc} con `tipo_regimen='02'`.")
    if sdi is not None and sdi <= 0:
        _marca("SDI_CERO", "alta", f"El SDI declarado es {sdi}.")
    if sbc is not None and sdi is not None and sdi < sbc * _TOLERANCIA_SDI_SBC:
        # Media, no alta (B-10.R1): un SDI inferior al SBC es teóricamente posible.
        _marca("SDI_MENOR_SBC", "media", f"El SDI ({sdi}) es menor al 80% del SBC ({sbc}); son conceptos distintos, pero conviene revisar.")

    if sdi is not None and percepciones_001 is not None and identidad.num_dias_pagados is not None and identidad.num_dias_pagados > 0:
        sd_implicito = percepciones_001 / identidad.num_dias_pagados
        if sdi < sd_implicito:
            _marca(
                "SDI_MENOR_SD_IMPLICITO",
                "alta",
                f"El SDI declarado ({sdi}) es menor al sueldo diario implícito en el CFDI "
                f"(Σ percepción '001' / días pagados = {percepciones_001} / {identidad.num_dias_pagados} = {sd_implicito}).",
            )

    # --- Fechas ---
    if identidad.fecha_inicio_rel_laboral is not None and identidad.fecha_final_pago is not None:
        if identidad.fecha_inicio_rel_laboral > identidad.fecha_final_pago:
            _marca(
                "FECHA_INICIO_POSTERIOR",
                "alta",
                f"`fecha_inicio_rel_laboral` ({identidad.fecha_inicio_rel_laboral}) es posterior a `fecha_final_pago` ({identidad.fecha_final_pago}).",
            )
        dias_declarados = v.antiguedad_iso_a_dias(identidad.antiguedad)
        if dias_declarados is not None:
            dias_calculados = (identidad.fecha_final_pago - identidad.fecha_inicio_rel_laboral).days
            if abs(dias_declarados - dias_calculados) > _TOLERANCIA_ANTIGUEDAD_DIAS:
                _marca(
                    "ANTIGUEDAD_INCONSISTENTE",
                    "baja",
                    f"`@Antigüedad` ({identidad.antiguedad!r} = {dias_declarados} días) difiere en más de "
                    f"{_TOLERANCIA_ANTIGUEDAD_DIAS} días del cálculo desde `fecha_inicio_rel_laboral` ({dias_calculados} días).",
                )

    # --- Puesto / departamento ---
    if _vacio_texto(identidad.puesto):
        _marca("PUESTO_VACIO", "baja", "El puesto está vacío, nulo o es un valor centinela (`Ninguno`/`N/A`).")
    if _vacio_texto(identidad.departamento):
        _marca("DEPARTAMENTO_VACIO", "baja", "El departamento está vacío, nulo o es un valor centinela (`Ninguno`/`N/A`).")

    # --- Cuenta bancaria ---
    banco_presente = not _vacio(identidad.banco)
    cuenta_presente = not _vacio(identidad.cuenta_bancaria)
    if cuenta_presente:
        cuenta = identidad.cuenta_bancaria
        assert cuenta is not None
        if not v.cuenta_bancaria_longitud_valida(cuenta):
            _marca("CUENTA_INVALIDA", "baja", f"La cuenta bancaria tiene {len(cuenta)} caracteres; se esperan 10, 11, 16 o 18.")
    elif banco_presente:
        _marca("BANCO_SIN_CUENTA", "baja", f"El banco ({identidad.banco!r}) está capturado pero la cuenta bancaria está vacía.")

    return hallazgos


def _hallazgos_de_conjunto(todas: list[_Identidad]) -> list[_Hallazgo]:
    """Grupo 2: `CURP_DUPLICADA`, `RFC_DUPLICADO`, `NSS_DUPLICADO`. Cruza **todos** los
    comprobantes del rango (no solo la última fotografía de cada empleado): una duplicidad de
    identidad no se ve mirando un solo CFDI."""
    curp_a_rfcs: dict[str, set[str]] = {}
    rfc_a_curps: dict[str, set[str]] = {}
    nss_a_rfcs: dict[str, set[str]] = {}

    for identidad in todas:
        if not _vacio(identidad.curp):
            curp = identidad.curp
            assert curp is not None
            curp_a_rfcs.setdefault(curp, set()).add(identidad.rfc)
            rfc_a_curps.setdefault(identidad.rfc, set()).add(curp)
        if not _vacio(identidad.nss):
            nss = identidad.nss
            assert nss is not None
            nss_a_rfcs.setdefault(nss, set()).add(identidad.rfc)

    hallazgos: list[_Hallazgo] = []
    for curp, rfcs in curp_a_rfcs.items():
        if len(rfcs) > 1:
            for rfc in rfcs:
                otros = sorted(rfcs - {rfc})
                hallazgos.append(
                    _Hallazgo(
                        rfc=rfc,
                        clave="CURP_DUPLICADA",
                        severidad="alta",
                        mensaje=f"La CURP {curp!r} también aparece con otro(s) RFC en el rango: {otros}.",
                    )
                )
    for rfc, curps in rfc_a_curps.items():
        if len(curps) > 1:
            hallazgos.append(
                _Hallazgo(
                    rfc=rfc,
                    clave="RFC_DUPLICADO",
                    severidad="alta",
                    mensaje=f"El RFC {rfc!r} aparece con más de una CURP en el rango: {sorted(curps)}.",
                )
            )
    for nss, rfcs in nss_a_rfcs.items():
        if len(rfcs) > 1:
            for rfc in rfcs:
                otros = sorted(rfcs - {rfc})
                hallazgos.append(
                    _Hallazgo(
                        rfc=rfc,
                        clave="NSS_DUPLICADO",
                        severidad="alta",
                        mensaje=f"El NSS {nss!r} también aparece con otro(s) RFC en el rango: {otros}.",
                    )
                )
    return hallazgos


def _hallazgos_entre_periodos(todas: list[_Identidad]) -> list[_Hallazgo]:
    """Grupo 3: `DATOS_CAMBIANTES` — un mismo RFC con distinta CURP, NSS o fecha de inicio de
    relación laboral entre comprobantes del rango. Solo aparece comparando periodos, nunca
    mirando un CFDI aislado."""
    por_rfc: dict[str, list[_Identidad]] = {}
    for identidad in todas:
        por_rfc.setdefault(identidad.rfc, []).append(identidad)

    hallazgos: list[_Hallazgo] = []
    for rfc, identidades in por_rfc.items():
        # `i.curp is not None` (además de `not _vacio(i.curp)`) es lo que permite a mypy
        # --strict angostar `str | None` a `str` dentro de la comprehension: `_vacio` es una
        # función cualquiera para el checker, no un type guard.
        curps = {i.curp for i in identidades if i.curp is not None and not _vacio(i.curp)}
        nss_vistos = {i.nss for i in identidades if i.nss is not None and not _vacio(i.nss)}
        fechas_inicio = {i.fecha_inicio_rel_laboral for i in identidades if i.fecha_inicio_rel_laboral is not None}

        campos_cambiantes = []
        if len(curps) > 1:
            campos_cambiantes.append(f"CURP: {sorted(curps)}")
        if len(nss_vistos) > 1:
            campos_cambiantes.append(f"NSS: {sorted(nss_vistos)}")
        if len(fechas_inicio) > 1:
            campos_cambiantes.append(f"fecha de inicio de relación laboral: {sorted(fechas_inicio)}")

        if campos_cambiantes:
            hallazgos.append(
                _Hallazgo(
                    rfc=rfc,
                    clave="DATOS_CAMBIANTES",
                    severidad="alta",
                    mensaje=f"El RFC {rfc!r} tiene valores distintos entre periodos del rango — {'; '.join(campos_cambiantes)}.",
                )
            )
    return hallazgos


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=_columnas(), aviso="La empresa no existe.")

    p_universo = _ParametrosUniverso(fecha_desde=p.fecha_desde, fecha_hasta=p.fecha_hasta, incluir_cancelados=p.incluir_cancelados)
    filas_universo = list((await db.execute(universo_nomina.universo(empresa_id, rfc_empresa, p_universo))).all())
    # Se resuelve ANTES del retorno temprano (mismo criterio que el resto del grupo B): si el
    # ETL falló en TODOS los CFDI del rango, la hoja Datos sale vacía y esta bandera es el
    # único rastro de que había nómina que auditar.
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, rfc_empresa, p_universo)

    if not filas_universo:
        return ResultadoInforme(
            columnas=_columnas(),
            banderas=banderas_fuera,
            aviso="Sin CFDI de nómina en el rango solicitado.",
        )

    # `todas`: una `_Identidad` por comprobante, para las validaciones de conjunto y entre
    # periodos (grupos 2 y 3), que necesitan ver TODO el rango.
    # `ultima_por_rfc`: se sobrescribe en el orden de iteración; `filas_universo` viene
    # ordenado ascendente por `fecha_pago` (mismo `order_by` de `universo_nomina.universo`),
    # así que al terminar el recorrido queda la más reciente de cada empleado.
    todas: list[_Identidad] = []
    ultima_por_rfc: dict[str, _Identidad] = {}
    for comprobante, nomina, receptor, _totales, detalle in filas_universo:
        identidad = _Identidad(
            comprobante_id=comprobante.comprobante_id,
            rfc=comprobante.rfc_receptor,
            nombre=detalle.nombre_receptor if detalle else None,
            num_empleado=receptor.num_empleado if receptor else None,
            curp=receptor.curp if receptor else None,
            nss=receptor.nss if receptor else None,
            tipo_regimen=receptor.tipo_regimen if receptor else None,
            sbc=_a_decimal(receptor.salario_base_cot_apor if receptor else None),
            sdi=_a_decimal(receptor.salario_diario_integrado if receptor else None),
            fecha_inicio_rel_laboral=receptor.fecha_inicio_rel_laboral if receptor else None,
            fecha_final_pago=nomina.fecha_final_pago,
            num_dias_pagados=_a_decimal(nomina.num_dias_pagados),
            antiguedad=receptor.antiguedad if receptor else None,
            banco=receptor.banco if receptor else None,
            cuenta_bancaria=receptor.cuenta_bancaria if receptor else None,
            puesto=receptor.puesto if receptor else None,
            departamento=receptor.departamento if receptor else None,
        )
        todas.append(identidad)
        ultima_por_rfc[identidad.rfc] = identidad

    ids_ultima_fotografia = [identidad.comprobante_id for identidad in ultima_por_rfc.values()]
    percepciones_001 = await _percepciones_001_por_comprobante(db, ids_ultima_fotografia)

    hallazgos: list[_Hallazgo] = []
    for rfc, identidad in ultima_por_rfc.items():
        hallazgos.extend(_hallazgos_estructurales_y_derivados(identidad, percepciones_001.get(identidad.comprobante_id)))
    hallazgos.extend(_hallazgos_de_conjunto(todas))
    hallazgos.extend(_hallazgos_entre_periodos(todas))

    umbral = _ORDEN_SEVERIDAD[p.severidad_minima]
    hallazgos_filtrados = [h for h in hallazgos if _ORDEN_SEVERIDAD[h.severidad] <= umbral]
    hallazgos_filtrados.sort(key=lambda h: (h.rfc, _ORDEN_SEVERIDAD[h.severidad], h.clave))

    filas: list[list[Any]] = []
    for h in hallazgos_filtrados:
        identidad = ultima_por_rfc[h.rfc]
        filas.append(
            [
                identidad.rfc,
                identidad.nombre,
                identidad.num_empleado,
                h.clave,
                h.severidad,
                h.mensaje,
                identidad.curp,
                identidad.nss,
                identidad.sbc,
                identidad.sdi,
                identidad.fecha_inicio_rel_laboral,
                identidad.fecha_final_pago,
            ]
        )

    return ResultadoInforme(columnas=_columnas(), filas=filas, banderas=banderas_fuera)
