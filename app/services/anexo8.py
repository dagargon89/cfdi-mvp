"""Extrae las tarifas de sueldos del PDF del Anexo 8 de la Resolución Miscelánea Fiscal.

**Módulo puro:** recibe bytes y devuelve tarifas. No toca la base ni la red.

Por qué esto no contradice la doctrina de `sincronizacion_fiscal`
----------------------------------------------------------------
Ese módulo argumenta —y sigue vigente— que no se raspan fuentes oficiales, porque un raspador que
falla devuelve otra cosa y el resultado es un valor fiscal viejo con cara de vigente. Aquí hay dos
diferencias que acotan esa regla en vez de romperla:

1. **La tarifa se auto-verifica.** Las seis pruebas del Anexo I.1 (`tarifa_isr.validar`) la
   contradicen aritméticamente si la extracción se corrompe. Una UMA mal leída es un número
   plausible y no hay redundancia interna que la delate.
2. **El documento lo aporta una persona.** No hay URL que este código visite solo; hay un archivo
   que alguien subió deliberadamente y cuya huella se guarda.

Las tres trampas del documento real, verificadas contra el Anexo 8 de 2026
--------------------------------------------------------------------------
1. **Cada encabezado aparece dos veces**: en el "Contenido" de la primera página y sobre su tabla.
   La ocurrencia del índice no tiene renglones detrás. Por eso una ocurrencia solo cuenta si le
   sigue el bloque de columnas (`$ $ $ %`), y si no, se descarta en silencio: no es un error del
   documento, es su índice.
2. **El pie de página del DOF se intercala a media tabla** ("Domingo 28 de diciembre de 2025 DIARIO
   OFICIAL", entre los renglones 5 y 6 de la tarifa quincenal). Por eso los renglones se buscan por
   patrón y las líneas que no son cuatro números se ignoran, en vez de cortar la tabla ahí. Cortar
   produciría una tarifa incompleta que falla la validación, y el usuario vería un error falso sobre
   un documento correcto.
3. **Las tarifas que no son de nómina tienen la misma forma de cuatro columnas** (enajenación de
   inmuebles del art. 126, y las de los arts. 106 y 116). Por eso el ancla exige el **fundamento
   legal citado**, no la forma: es lo único que las distingue.

Y dos más, encontradas al correr el extractor contra el documento completo en vez de un fragmento:

4. **La mención del índice de una tabla puede tener otra tabla —ajena— cerca.** En el índice, la
   mención del rubro C.I. ("... ejercicio de 2025 ...") queda, más adelante en ese mismo párrafo del
   índice, a algunos cientos de caracteres de las columnas de la tabla del art. 126 (enajenación de
   inmuebles), que no es la tabla anual. Buscar el símbolo `$ $ $ %` sin exigir el resto del
   encabezado ("Limite inferior Limite superior Cuota fija...") y sin acotar la distancia lo
   suficiente cuela esa tabla ajena como si fuera la correcta; ver el docstring de `_COLUMNAS`.
5. **El primer renglón de la tabla anual del ejercicio 2026 (rubro C.I) publica su cuota fija como
   "0" a secas, sin los dos decimales que trae el resto de las tablas** ("0.01 10,135.11 0 1.92",
   no "... 0.00 1.92"). La tabla anual del ejercicio 2025 sí usa "0.00" como todas las demás; es
   solo la de 2026 la que lo hace distinto. Es así en el documento oficial, no un defecto de la
   extracción; ver `_RENGLON`.

Y una última, que es la más peligrosa porque las pruebas de validación no la ven: **un Anexo 8
contiene tarifas de dos ejercicios**. El de 2026 trae la anual del ejercicio 2025 en su rubro C.I.
El ejercicio se lee del encabezado de cada tabla, nunca del nombre del archivo ni del año de la RMF.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

import pypdfium2

from app.models.enums import PeriodicidadTarifa
from app.services import tarifa_isr

MAXIMO_BYTES: Final = 10 * 1024 * 1024
MAXIMO_PAGINAS: Final = 100


class DocumentoInvalido(ValueError):
    """El archivo no sirve como Anexo 8. El mensaje se le muestra a una persona: dice qué se
    esperaba y qué hacer, no qué falló por dentro."""


class ArchivoDemasiadoGrande(DocumentoInvalido):
    """El archivo excede el límite de tamaño o de páginas.

    Subclase y no un `DocumentoInvalido` más porque el endpoint responde 413 en este caso y 422 en
    los demás, y distinguirlos por el texto del mensaje sería una condición que se rompe la primera
    vez que alguien mejora una redacción.
    """


@dataclass(frozen=True)
class TarifaExtraida:
    ejercicio: int
    periodicidad: PeriodicidadTarifa
    encabezado: str
    renglones: tuple[tarifa_isr.Renglon, ...]


@dataclass(frozen=True)
class _Ancla:
    periodicidad: PeriodicidadTarifa
    patron: re.Pattern[str]


def _sin_acentos(texto: str) -> str:
    """Quita los acentos para que el ancla no se rompa por una tilde perdida en la extracción.
    Los números de artículo se siguen exigiendo literales: son lo que distingue una tarifa de
    sueldos de una de arrendamiento."""
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


# Anclas: periodicidad + fundamento, ambos exigidos. Se escriben sin acentos porque el texto se
# normaliza antes de buscar. `.{0,160}?` absorbe los saltos de línea que el PDF mete a media frase.
_ANCLAS: Final[tuple[_Ancla, ...]] = (
    _Ancla(
        PeriodicidadTarifa.DIARIA,
        re.compile(
            r"cantidad de trabajo realizado.{0,160}?correspondiente a (?P<ejercicio>\d{4}),?"
            r".{0,60}?calculada en dias.{0,160}?96 de la Ley del ISR y 175 de su Reglamento",
            re.S,
        ),
    ),
    _Ancla(
        PeriodicidadTarifa.DIAS_7,
        re.compile(
            r"periodo de 7 dias,?.{0,60}?correspondiente a (?P<ejercicio>\d{4})"
            r".{0,160}?96 de la Ley del ISR y 175 de su Reglamento",
            re.S,
        ),
    ),
    _Ancla(
        PeriodicidadTarifa.DIAS_10,
        re.compile(
            r"periodo de 10 dias,?.{0,60}?correspondiente a (?P<ejercicio>\d{4})"
            r".{0,160}?96 de la Ley del ISR y 175 de su Reglamento",
            re.S,
        ),
    ),
    _Ancla(
        PeriodicidadTarifa.DIAS_15,
        re.compile(
            r"periodo de 15 dias,?.{0,60}?correspondiente a (?P<ejercicio>\d{4})"
            r".{0,160}?96 de la Ley del ISR y 175 de su Reglamento",
            re.S,
        ),
    ),
    _Ancla(
        PeriodicidadTarifa.MENSUAL,
        re.compile(
            r"Tarifa aplicable durante (?P<ejercicio>\d{4}) para el calculo de los pagos provisionales "
            r"mensuales.{0,160}?96 de la Ley del ISR y 175 de su Reglamento",
            re.S,
        ),
    ),
    _Ancla(
        PeriodicidadTarifa.EJERCICIO,
        re.compile(
            r"impuesto correspondiente al ejercicio de (?P<ejercicio>\d{4})"
            r".{0,160}?97 y 152 de la Ley del ISR",
            re.S,
        ),
    ),
)

# Encabezado de columnas de una tabla real. No es solo el símbolo "$ $ $ %" —aparece 31 veces en el
# documento, delante de tablas de nómina y de las que no lo son, y por sí solo no dice de cuál
# tabla es—, sino la fila completa que lo antecede: "Limite inferior Limite superior Cuota fija Por
# ciento para aplicarse sobre el excedente del limite inferior", verificada como idéntica delante
# de las 31 tablas del documento. Esa frase completa es la que distingue una tabla de verdad de su
# mención en el índice, no la distancia a la que aparece.
#
# Sigue habiendo un límite de caracteres antes de la frase (no puede haber ninguno: una búsqueda
# sin cota siempre encuentra ALGUNA tabla más adelante en el documento, sea la que sea —comprobado:
# desde la mención del índice de la tarifa diaria, sin cota, la primera coincidencia está a 11,160
# caracteres—). Pero ya no es la única defensa ni una cuestión de calibrarlo fino: medido contra
# las 7 tablas reales, entre el fundamento y esta frase solo cabe la cola de la cita legal (", asi
# como la regla 3.12.2.", 28 caracteres) y, si el salto de página cae ahí, el pie del DOF ("Domingo
# 28 de diciembre de 2025 DIARIO OFICIAL", 47 caracteres) — nunca los dos a la vez en este
# documento, pero 100 cubre ambos con holgura. Las dos coincidencias falsas del índice (rubro C.I.)
# quedan a 296 y 459 caracteres de la tabla ajena del art. 126 que las sigue: casi tres veces el
# límite, no 18 caracteres de por medio como con el margen anterior (200 contra un real de 136 y un
# falso de 404).
_MAX_PREFIJO_ANTES_DE_COLUMNAS: Final = 100
_COLUMNAS: Final = re.compile(
    r".{0," + str(_MAX_PREFIJO_ANTES_DE_COLUMNAS) + r"}?Limite inferior Limite superior Cuota fija "
    r"Por ciento para aplicarse sobre el excedente del limite inferior \$ \$ \$ %",
    re.S,
)

# Un renglón: límite inferior, límite superior (o "En adelante"), cuota fija y porcentaje.
#
# La cuota fija normalmente lleva dos decimales ("0.00"), pero el primer renglón de las dos tablas
# anuales (rubro C.I, ejercicios 2025 y 2026) lo publica como "0" a secas, sin punto ni decimales;
# es así en el documento, no un defecto de la extracción. Por eso la cuota admite también un cero
# sin decimales, y no en general un entero cualquiera: solo ese caso real necesita la alternativa.
_RENGLON: Final = re.compile(
    r"(?P<inferior>\d[\d,]*\.\d{2}) (?P<superior>\d[\d,]*\.\d{2}|En adelante) "
    r"(?P<cuota>\d[\d,]*\.\d{2}|0) (?P<tasa>\d{1,2}\.\d{2})"
)


def _texto_plano(pdf: bytes) -> str:
    """Todo el PDF como una sola cadena, sin acentos, con espacios colapsados.

    Se aplana a una línea a propósito: el PDF corta las frases del encabezado con saltos, así que
    buscar por línea obligaría a reconstruirlas. Los renglones se recuperan igual porque se buscan
    por patrón, no por posición.
    """
    if len(pdf) > MAXIMO_BYTES:
        raise ArchivoDemasiadoGrande(
            f"El archivo es más grande de lo que debería ({len(pdf) // 1024 // 1024} MB; el Anexo 8 pesa "
            "menos de 1 MB). ¿Es el archivo correcto?"
        )
    try:
        documento = pypdfium2.PdfDocument(pdf)
    except (pypdfium2.PdfiumError, ValueError, OSError) as exc:
        # Los tres tipos que pypdfium2 puede lanzar ante un archivo que no es un PDF legible. No se
        # captura `Exception` a secas: taparía un error de programación nuestro con un mensaje que le
        # echa la culpa al archivo del usuario.
        raise DocumentoInvalido(
            "No pude abrir este archivo como PDF. Descarga el Anexo 8 del portal del SAT y súbelo tal cual."
        ) from exc
    if len(documento) > MAXIMO_PAGINAS:
        raise ArchivoDemasiadoGrande(
            f"El archivo trae {len(documento)} páginas y el Anexo 8 trae menos de {MAXIMO_PAGINAS}. "
            "¿Es el archivo correcto?"
        )
    crudo = "\n".join(documento[i].get_textpage().get_text_range() for i in range(len(documento)))
    if len(crudo.strip()) < 500:
        raise DocumentoInvalido(
            "Este PDF no tiene texto, parece un escaneo o una foto. Descarga el archivo del portal del "
            "SAT en vez de una copia escaneada."
        )
    return re.sub(r"\s+", " ", _sin_acentos(crudo))


def _renglones_desde(texto: str, inicio: int) -> tuple[tarifa_isr.Renglon, ...]:
    """Los renglones consecutivos a partir de `inicio`, hasta el que dice "En adelante".

    "En adelante" es el delimitador porque el último renglón de toda tarifa del Anexo lo lleva. Sin
    él haría falta adivinar dónde termina la tabla, y el encabezado siguiente no siempre está cerca.
    """
    renglones: list[tarifa_isr.Renglon] = []
    for numero, m in enumerate(_RENGLON.finditer(texto, inicio), start=1):
        superior = None if m.group("superior") == "En adelante" else Decimal(m.group("superior").replace(",", ""))
        renglones.append(
            tarifa_isr.Renglon(
                renglon=numero,
                limite_inferior=Decimal(m.group("inferior").replace(",", "")),
                limite_superior=superior,
                cuota_fija=Decimal(m.group("cuota").replace(",", "")),
                # El único lugar de todo el sistema donde se divide entre 100.
                tasa_excedente=Decimal(m.group("tasa")) / Decimal(100),
            )
        )
        if superior is None:
            break
    return tuple(renglones)


def extraer(pdf: bytes) -> list[TarifaExtraida]:
    """Las tarifas de sueldos del documento. Lanza `DocumentoInvalido` si no hay ninguna, o si dos
    tarifas salieron con la misma clave (ejercicio, periodicidad).

    Cada tarifa extraída pasa `tarifa_isr.validar` aquí mismo: si una falla, **no se devuelve
    ninguna**. Un Anexo 8 a medio cargar deja un estado que después nadie sabe interpretar, porque
    no se distingue de un documento que legítimamente traía menos tablas.

    La comprobación de clave repetida no es una precaución de más: es la red que atrapa ruidosamente
    un fallo del ancla que, de otro modo, sería silencioso. Si `_COLUMNAS` alguna vez enganchara la
    tabla de otro rubro (ver su docstring), esa tabla ajena sale con el ejercicio y la periodicidad
    correctos —los toma del propio fundamento que sí matcheó— pero con los renglones de otra tarifa,
    y esa combinación ya existe en la lista: dos tarifas con la misma clave.
    """
    texto = _texto_plano(pdf)
    encontradas: list[TarifaExtraida] = []
    vistas: set[tuple[int, PeriodicidadTarifa]] = set()

    for ancla in _ANCLAS:
        for m in ancla.patron.finditer(texto):
            columnas = _COLUMNAS.match(texto, m.end())
            if columnas is None:
                # La mención del índice: no tiene su propia tabla inmediatamente detrás. No es un
                # error del documento, es su índice.
                continue
            renglones = _renglones_desde(texto, columnas.end())
            if not renglones:
                continue
            tarifa_isr.validar(list(renglones))
            ejercicio = int(m.group("ejercicio"))
            clave = (ejercicio, ancla.periodicidad)
            if clave in vistas:
                raise DocumentoInvalido(
                    f"Encontré más de una tarifa {ancla.periodicidad.value.lower()} del ejercicio "
                    f"{ejercicio} en este archivo. Un Anexo 8 no trae dos veces la misma tabla; revisa "
                    "que el PDF no esté dañado, duplicado o mezclado con otro documento."
                )
            vistas.add(clave)
            encontradas.append(
                TarifaExtraida(
                    ejercicio=ejercicio,
                    periodicidad=ancla.periodicidad,
                    encabezado=" ".join(m.group(0).split())[:1000],
                    renglones=renglones,
                )
            )

    if not encontradas:
        raise DocumentoInvalido(
            "No encontré ninguna tarifa de sueldos en este archivo. Debe ser el Anexo 8 de la Resolución "
            "Miscelánea Fiscal (busca 'Anexo 8' y el año en el portal del SAT). No se cargó nada."
        )
    return encontradas
