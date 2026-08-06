"""Validadores puros de datos del receptor (ficha B-10). Sin BD: solo reglas de estructura
sobre un valor aislado — RFC, CURP, NSS, cuenta bancaria y la duración ISO 8601 de
`@Antigüedad`. Las reglas que necesitan cruzar varios CFDI (duplicados, cambios entre
periodos, comparación contra el SDI implícito) viven en `app.informes.b10_validacion_receptor`,
que es quien tiene la consulta a la BD y el universo completo.

**Verificación real del dígito verificador del NSS.** El algoritmo de Luhn aplicado a un
NSS de prueba se comprobó a mano y con un script antes de fijar cualquier valor en las
pruebas (ver `tests/test_informes_validadores.py` y `tests/test_informe_b10.py`): no basta
con "parece un NSS", el dígito 11 tiene que satisfacer la suma módulo 10 de verdad. El NSS
de referencia `12345678903` SÍ la satisface (suma de los 10 primeros con el patrón de Luhn +
el dígito 11 = 50, múltiplo de 10); se conserva tal cual porque ya es correcto, no porque se
haya ajustado el validador para que lo acepte.
"""

from __future__ import annotations

import re

# RFC de persona física (spec B-10): 4 letras (incluye Ñ y &, usados en apellidos
# compuestos/paterno de una sola letra), 6 dígitos de fecha, 3 caracteres de homoclave.
# Un RFC de persona moral tiene solo 3 letras iniciales y por eso no cumple este patrón
# (`EKU9003173C9` de las pruebas es justo ese caso).
_PATRON_RFC_PERSONA_FISICA = re.compile(r"^[A-ZÑ&]{4}[0-9]{6}[A-Z0-9]{3}$")

# CURP: 4 letras, 6 dígitos de fecha, sexo (H/M), 5 consonantes internas, un carácter
# alfanumérico (diferenciador de homonimia) y un dígito verificador final.
_PATRON_CURP = re.compile(r"^[A-Z]{4}[0-9]{6}[HM][A-Z]{5}[A-Z0-9][0-9]$")

# Claves de entidad federativa de la CURP (Instructivo Normativo de la CURP, RENAPO): las
# 32 entidades más `NE` para quien nació en el extranjero. Posiciones 12-13 (1-indexado) de
# una CURP bien formada.
ENTIDADES_CURP = frozenset(
    {
        "AS", "BC", "BS", "CC", "CL", "CM", "CS", "CH", "DF", "DG", "GT", "GR", "HG", "JC",
        "MC", "MN", "MS", "NT", "NL", "OC", "PL", "QO", "QR", "SP", "SL", "SR", "TC", "TS",
        "TL", "VZ", "YN", "ZS", "NE",
    }
)

# Longitudes de cuenta bancaria válidas en México: cuenta simple (10), CLABE corta usada
# por algunos bancos (11, poco común), tarjeta de débito (16) y CLABE interbancaria (18).
_LONGITUDES_CUENTA_VALIDAS = frozenset({10, 11, 16, 18})

# Duración ISO 8601 (solo la parte de fecha: años, meses, semanas, días — el complemento de
# nómina no usa la parte de horas). El `(?=\d)` tras la `P` exige que aparezca al menos un
# componente: "P" sola no es una duración válida.
_PATRON_DURACION_ISO = re.compile(r"^P(?=\d)(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?$")

_DIAS_POR_ANIO = 365
"""Aproximación deliberada (ver `antiguedad_iso_a_dias`): un año calendario real tiene 365
o 366 días según sea bisiesto, pero la duración ISO 8601 del atributo `@Antigüedad` no dice
en qué año cae, así que no hay bisiesto que aplicar de forma exacta. `ANTIGUEDAD_INCONSISTENTE`
(en `b10_validacion_receptor`) compara este cálculo con tolerancia de dos semanas
precisamente para absorber esta y las demás aproximaciones de esta función."""

_DIAS_POR_MES = 30
"""Igual de aproximado que `_DIAS_POR_ANIO` y por la misma razón: un mes tiene entre 28 y 31
días reales; 30 es el valor convencional para convertir duraciones ISO 8601 sin fecha de
referencia (lo mismo que hacen la mayoría de los parsers de `P_Y_M_D`)."""


def rfc_persona_fisica_valido(rfc: str | None) -> bool:
    """`RFC_ESTRUCTURA`: RFC de persona física, patrón `^[A-ZÑ&]{4}[0-9]{6}[A-Z0-9]{3}$`.

    Un RFC de persona moral (3 letras iniciales, como `EKU9003173C9`) no cumple este patrón
    a propósito: el receptor de un CFDI de nómina es siempre una persona física."""
    if rfc is None:
        return False
    return _PATRON_RFC_PERSONA_FISICA.fullmatch(rfc) is not None


def curp_valida(curp: str | None) -> bool:
    """`CURP_ESTRUCTURA`: patrón `^[A-Z]{4}[0-9]{6}[HM][A-Z]{5}[A-Z0-9][0-9]$`."""
    if curp is None:
        return False
    return _PATRON_CURP.fullmatch(curp) is not None


def curp_entidad_valida(curp: str | None) -> bool:
    """`CURP_ENTIDAD`: las posiciones 12-13 (1-indexado) son una clave de entidad válida
    (`ENTIDADES_CURP`). No exige que el resto de la CURP cumpla `curp_valida`: solo mira esas
    dos posiciones, así que basta con que la cadena tenga al menos 13 caracteres."""
    if curp is None or len(curp) < 13:
        return False
    return curp[11:13] in ENTIDADES_CURP


def nss_digito_verificador_valido(nss: str | None) -> bool:
    """`NSS_DIGITO_VERIFICADOR`: algoritmo de Luhn sobre las 10 primeras posiciones; la
    posición 11 es el dígito verificador.

    Luhn clásico: contando desde la izquierda en base 1, se duplica cada dígito en posición
    par de los 10 primeros (si el doble pasa de 9, se le resta 9, equivalente a sumar sus dos
    cifras); el resto se suma tal cual. La suma total —incluyendo el dígito verificador sin
    duplicar— debe ser múltiplo de 10."""
    if nss is None or len(nss) != 11 or not nss.isdigit():
        return False
    digitos = [int(c) for c in nss]
    cuerpo, verificador = digitos[:10], digitos[10]
    total = 0
    for posicion, digito in enumerate(cuerpo, start=1):
        if posicion % 2 == 0:
            doble = digito * 2
            total += doble - 9 if doble > 9 else doble
        else:
            total += digito
    total += verificador
    return total % 10 == 0


def cuenta_bancaria_longitud_valida(cuenta: str | None) -> bool:
    """`CUENTA_INVALIDA`: longitud de 10, 11, 16 o 18 caracteres (`_LONGITUDES_CUENTA_VALIDAS`)."""
    if cuenta is None:
        return False
    return len(cuenta) in _LONGITUDES_CUENTA_VALIDAS


def antiguedad_iso_a_dias(antiguedad: str | None) -> int | None:
    """Convierte la duración ISO 8601 del atributo `@Antigüedad` (`P663W`, `P3Y2M`, `P10D`,
    etc.) a días. `None` si `antiguedad` es `None` o no tiene forma de duración ISO 8601 con
    al menos un componente de fecha.

    **Aproximación deliberada, documentada aquí y no solo en el llamador.** Meses y años no
    tienen un número fijo de días (ver `_DIAS_POR_ANIO`/`_DIAS_POR_MES`), así que esta
    conversión es necesariamente aproximada cuando la duración incluye `Y` o `M`. Es exacta
    cuando solo usa `W` o `D` (semanas y días sí tienen equivalencia fija). `ANTIGUEDAD_INCONSISTENTE`
    (`b10_validacion_receptor`) compara este resultado con tolerancia de dos semanas
    precisamente para no confundir esta aproximación con un error de captura real."""
    if antiguedad is None:
        return None
    coincidencia = _PATRON_DURACION_ISO.fullmatch(antiguedad)
    if coincidencia is None:
        return None
    anios, meses, semanas, dias = (int(grupo) if grupo is not None else 0 for grupo in coincidencia.groups())
    return anios * _DIAS_POR_ANIO + meses * _DIAS_POR_MES + semanas * 7 + dias
