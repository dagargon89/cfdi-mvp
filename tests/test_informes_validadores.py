"""Validadores puros de datos del receptor (ficha B-10). Sin BD: reglas de estructura."""

from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.informes import validadores as v
from app.informes.excel import HOJAS_CON_ENCABEZADO


@pytest.mark.parametrize("rfc", ["VECJ880326XXX", "ÑAAA000101AA1", "AAA&000101AA1"])
def test_rfc_persona_fisica_valido(rfc: str) -> None:
    assert v.rfc_persona_fisica_valido(rfc) is True


@pytest.mark.parametrize("rfc", [None, "", "EKU9003173C9", "VECJ880326", "vecj880326xxx", "VECJ8803261XXX"])
def test_rfc_persona_fisica_invalido(rfc: str | None) -> None:
    """`EKU9003173C9` es de persona moral (3 letras iniciales): no cumple el patrón de
    física, que exige 4."""
    assert v.rfc_persona_fisica_valido(rfc) is False


def test_curp_valida() -> None:
    assert v.curp_valida("VECJ880326HDFLNS09") is True
    assert v.curp_valida(None) is False
    assert v.curp_valida("VECJ880326XDFLNS09") is False  # ni H ni M


def test_curp_entidad() -> None:
    assert v.curp_entidad_valida("VECJ880326HDFLNS09") is True  # DF
    assert v.curp_entidad_valida("VECJ880326HCHLNS09") is True  # CH
    assert v.curp_entidad_valida("VECJ880326HZZLNS09") is False
    assert v.curp_entidad_valida(None) is False


def test_nss_digito_verificador() -> None:
    """Luhn sobre las 10 primeras posiciones; la 11ª es el verificador.

    `12345678903` se verificó a mano y con script antes de fijarlo aquí (ver el docstring
    del módulo `validadores`): la suma de Luhn de `1234567890` da 47, y 47 + 3 = 50 es
    múltiplo de 10, así que el dígito verificador correcto para ese cuerpo SÍ es 3. No es un
    valor ajustado para que la prueba pase, es el que el algoritmo real produce.
    """
    assert v.nss_digito_verificador_valido("12345678903") is True
    assert v.nss_digito_verificador_valido("12345678901") is False
    assert v.nss_digito_verificador_valido(None) is False
    assert v.nss_digito_verificador_valido("123") is False


def test_cuenta_bancaria_longitud() -> None:
    for largo in (10, 11, 16, 18):
        assert v.cuenta_bancaria_longitud_valida("1" * largo) is True
    assert v.cuenta_bancaria_longitud_valida("1" * 12) is False
    assert v.cuenta_bancaria_longitud_valida(None) is False


def test_antiguedad_iso_a_dias() -> None:
    """`@Antigüedad` viene como duración ISO 8601 (`P663W`, `P3Y2M`)."""
    assert v.antiguedad_iso_a_dias("P1W") == 7
    assert v.antiguedad_iso_a_dias("P663W") == 663 * 7
    assert v.antiguedad_iso_a_dias("P1Y") == 365
    assert v.antiguedad_iso_a_dias("P1Y2M") == 365 + 60
    assert v.antiguedad_iso_a_dias("P10D") == 10
    assert v.antiguedad_iso_a_dias(None) is None
    assert v.antiguedad_iso_a_dias("663 semanas") is None


def test_dato_personal_en_texto_detecta_curp_y_nss_embebidos() -> None:
    """Auditoría del enmascaramiento por el lado que el mecanismo no cubre: un dato personal
    completo dentro de una frase, en una columna que no está declarada `sensible=True`. Es
    exactamente cómo B-10 filtraba CURP y NSS con `enmascarar_datos_personales=True`."""
    assert v.dato_personal_en_texto("La CURP 'VECJ880326HDFLNS09' también aparece con otro RFC.") == "CURP"
    assert v.dato_personal_en_texto("VECJ880326HDFLNS09") == "CURP"
    assert v.dato_personal_en_texto("El NSS '12345678903' no cumple el dígito verificador.") == "NSS"
    # Devuelve el TIPO, nunca el valor: quien la llama imprime el resultado en una terminal.
    assert v.dato_personal_en_texto("VECJ880326HDFLNS09") not in {"VECJ880326HDFLNS09", None}


def test_dato_personal_en_texto_no_marca_lo_que_no_lo_es() -> None:
    """Los falsos positivos importan tanto como los negativos: una comprobación que grita con
    cualquier celda se desactiva, y entonces deja de proteger."""
    assert v.dato_personal_en_texto(None) is None
    assert v.dato_personal_en_texto("") is None
    assert v.dato_personal_en_texto("****NS09") is None  # ya enmascarada por el motor
    assert v.dato_personal_en_texto("****2101") is None
    assert v.dato_personal_en_texto("VECJ880326XXX") is None  # RFC, 13 caracteres
    assert v.dato_personal_en_texto("JUANA INVENTADA DE PRUEBA") is None
    assert v.dato_personal_en_texto(Decimal("8759.70")) is None  # no es `str`
    # Un UUID con el último segmento todo numérico tiene 12 dígitos seguidos: las guardas de
    # frontera del patrón evitan que se reporte como un NSS de 11.
    assert v.dato_personal_en_texto("11111111-1111-1111-1111-111111111111") is None


# --- El auditor anti-fuga del libro (`fugas_de_datos_personales_en_libro`) ---
#
# Estas pruebas son puras (openpyxl en memoria, sin BD): fijan el comportamiento del auditor
# mismo. Las que lo ejercen end-to-end sobre un informe real viven en `tests/test_informe_b10.py`.

_CURP_INVENTADA = "VECJ880326HDFLNS09"
_CURP_MAL_FORMADA = "MALA880326HDF"  # 13 caracteres: no cumple el patrón, sí identifica a la persona
_VALORES = {"CURP": [_CURP_INVENTADA, _CURP_MAL_FORMADA], "NSS": ["12345678901"]}


def _libro(hojas: dict[str, list[list[object]]]) -> Workbook:
    """Un libro con las hojas y filas dadas, en el orden dado."""
    wb = Workbook()
    wb.remove(wb.active)
    for nombre, filas in hojas.items():
        ws = wb.create_sheet(nombre)
        for fila in filas:
            ws.append(fila)
    return wb


def test_fuga_en_la_fila_de_encabezado_no_publica_el_valor() -> None:
    """**El hallazgo Critical de la revisión.** Auditar la fila 1 como una fila cualquiera es
    correcto —es la corrección del hueco B—, pero el nombre de la columna con el que se reporta una
    fuga sale de esa misma fila 1. Cuando la celda que dispara la fuga **es** el encabezado, el
    campo `columna` acababa siendo el dato personal, y de ahí salía a la consola del script y al
    mensaje de aserción de la suite: la fuga dentro del aviso de fuga.

    No era teórico: los títulos dinámicos de B-01 y B-02 se construyen con el `@Concepto` del XML,
    texto libre no controlado — la misma clase de contenido que causó el incidente de B-10.

    Se asevera lo fuerte: **ningún** campo del hallazgo ni su `descripcion` contiene el valor.
    """
    libro = _libro({"Datos": [["RFC empleado", _CURP_INVENTADA], ["VECJ880326XXX", "****NS09"]]})

    fugas = v.fugas_de_datos_personales_en_libro(libro, _VALORES)

    assert [(f.hoja, f.fila, f.tipo) for f in fugas] == [("Datos", 1, "CURP"), ("Datos", 1, "CURP")]
    assert {f.deteccion for f in fugas} == {"patrón", "valor"}
    # La columna se nombra por posición, no con su propio contenido.
    assert {f.columna for f in fugas} == {"columna 2"}
    for fuga in fugas:
        for campo in (fuga.hoja, fuga.columna, fuga.tipo, fuga.deteccion, fuga.descripcion):
            assert _CURP_INVENTADA not in campo, "un reporte de fuga no puede reproducir el valor que denuncia"


def test_un_titulo_dinamico_con_dato_personal_no_se_usa_como_etiqueta() -> None:
    """La otra mitad del Critical: el título contamina la etiqueta aunque la fuga esté en **otra**
    fila. Es el caso de B-01/B-02 con un `@Concepto` del XML que trajera el dato.

    La CURP del título está **mal formada**, así que solo la ve la comprobación por valor: sin ella
    el título se publicaría tal cual.
    """
    libro = _libro(
        {
            "Datos": [
                ["RFC empleado", f"P¦001¦001¦Sueldo de {_CURP_MAL_FORMADA}"],
                ["VECJ880326XXX", f"Revisar {_CURP_INVENTADA}"],
            ]
        }
    )

    fugas = v.fugas_de_datos_personales_en_libro(libro, _VALORES)

    # La fuga de la fila 2 se reporta con la posición, no con el título contaminado.
    de_la_fila_2 = [f for f in fugas if f.fila == 2]
    assert de_la_fila_2, [f.descripcion for f in fugas]
    assert {f.columna for f in de_la_fila_2} == {"columna 2"}
    for fuga in fugas:
        assert _CURP_MAL_FORMADA not in fuga.descripcion and _CURP_INVENTADA not in fuga.descripcion


def test_un_titulo_limpio_si_se_usa_como_etiqueta() -> None:
    """La mitad negativa: sin ella, nombrar **siempre** por posición pasaría igual y el diagnóstico
    sería peor de lo que era."""
    libro = _libro({"Datos": [["RFC empleado", "Descripción del hallazgo"], ["VECJ880326XXX", f"Revisar {_CURP_INVENTADA}"]]})

    fugas = v.fugas_de_datos_personales_en_libro(libro, _VALORES)

    assert [f.columna for f in fugas] == ["Descripción del hallazgo", "Descripción del hallazgo"]


def test_la_hoja_parametros_se_reporta_por_posicion() -> None:
    """**Hallazgo Important de la revisión.** `Parámetros` no tiene fila de títulos: su fila 1 ya es
    contenido (`["Informe", "B-05 · ..."]`, ver `excel._escribir_parametros`). Tomarla como
    encabezado reportaba una fuga de la columna "Valor" como si la columna se llamara
    "B-05 · Acumulado anual" — un diagnóstico que manda a mirar donde no es.

    `excel.HOJAS_CON_ENCABEZADO` es la fuente de verdad, y vive en el módulo que escribe el libro.
    """
    assert "Parámetros" not in HOJAS_CON_ENCABEZADO
    libro = _libro(
        {
            "Parámetros": [
                ["Informe", "B-05 · Acumulado anual"],
                ["Generado por", "consulta@test.mx"],
                ["Parámetro", "Valor"],
                ["curp_del_empleado", _CURP_INVENTADA],
            ]
        }
    )

    fugas = v.fugas_de_datos_personales_en_libro(libro, _VALORES)

    assert [(f.hoja, f.fila, f.columna) for f in fugas] == [("Parámetros", 4, "columna 2"), ("Parámetros", 4, "columna 2")]
    assert all("B-05" not in f.columna for f in fugas), "no se inventa un título donde la hoja no lo tiene"


def test_las_cuatro_hojas_se_auditan() -> None:
    """El hueco B, en su forma más directa: las cuatro hojas viajan en el mismo archivo."""
    libro = _libro(
        {
            "Datos": [["RFC empleado"], ["VECJ880326XXX"]],
            "Parámetros": [["Informe", "B-10"]],
            "Banderas": [["Bandera", "Severidad", "Ámbito", "Mensaje"], ["X", "baja", "informe", f"Corregir {_CURP_INVENTADA}."]],
            "Diccionario": [["Etiqueta"], [f"P¦001¦001¦{_CURP_INVENTADA}"]],
        }
    )

    fugas = v.fugas_de_datos_personales_en_libro(libro, _VALORES)

    assert {f.hoja for f in fugas} == {"Banderas", "Diccionario"}
    assert ("Banderas", 2, "Mensaje") in {(f.hoja, f.fila, f.columna) for f in fugas}


def test_fuga_dato_personal_rechaza_un_campo_con_dato_personal() -> None:
    """El cable trampa de `FugaDatoPersonal.__post_init__`: la garantía principal está en
    `_nombre_de_columna`, pero si alguien construyera el hallazgo por otra ruta la clase falla en
    vez de publicar el valor. **Falla, no censura**: recortarlo en silencio dejaría la red
    aparentando funcionar.

    Y la excepción tampoco nombra el valor — sería la misma fuga por otra vía.
    """
    with pytest.raises(ValueError) as excinfo:
        v.FugaDatoPersonal(hoja="Datos", fila=1, columna=_CURP_INVENTADA, tipo="CURP", deteccion="patrón")
    assert _CURP_INVENTADA not in str(excinfo.value)
    assert "columna" in str(excinfo.value)
    # Un hallazgo bien formado sí se construye.
    assert v.FugaDatoPersonal(hoja="Datos", fila=1, columna="columna 2", tipo="CURP", deteccion="valor").fila == 1


def test_un_valor_personal_demasiado_corto_no_se_busca() -> None:
    """`LONGITUD_MINIMA_VALOR_PERSONAL`: una captura basura de dos caracteres aparecería como
    subcadena de media hoja y convertiría la red en ruido, que es otra forma de desactivarla."""
    assert v.LONGITUD_MINIMA_VALOR_PERSONAL == 8
    libro = _libro({"Datos": [["RFC empleado"], ["VECJ880326XXX"]]})
    assert v.fugas_de_datos_personales_en_libro(libro, {"CURP": ["X"], "NSS": ["88"]}) == []
    # Y uno de longitud suficiente sí: sin esta mitad, la prueba pasaría con la búsqueda desactivada.
    assert v.fugas_de_datos_personales_en_libro(libro, {"CURP": ["VECJ8803"]}) != []


# --- El renderizado del hallazgo (`FugaDatoPersonal.__repr__`) ---


def _fuga_contaminada() -> pytest.ExceptionInfo[ValueError]:
    """Dispara el cable trampa y devuelve el `ExceptionInfo` con el marco ya capturado.

    El objeto contaminado **solo existe** dentro del marco de `__post_init__` (un dataclass con
    `slots=True` puebla sus campos antes de correr `__post_init__`, así que `self` ya lleva el valor
    crudo cuando la capa 2 lanza). Ese marco es justo el que el formateador de tracebacks renderiza.
    """
    with pytest.raises(ValueError) as excinfo:
        v.FugaDatoPersonal(hoja="Datos", fila=1, columna=_CURP_INVENTADA, tipo="CURP", deteccion="patrón")
    return excinfo


def test_el_traceback_del_cable_trampa_no_reproduce_el_valor() -> None:
    """**El hallazgo de la ronda 2.** El mensaje de la excepción nunca llevó el valor, pero el
    mensaje no es la única vía por la que el contexto de una excepción llega a una pantalla: el
    formateador de tracebacks de pytest imprime los **argumentos del marco** donde se levantó la
    excepción, y ahí `self` es el objeto contaminado (un dataclass con `slots=True` puebla sus campos
    antes de correr `__post_init__`). Salía como:

        self = FugaDatoPersonal(hoja='Datos', fila=1, columna='VECJ880326HDFLNS09', ...)

    que es el incidente original por otro mecanismo.

    **Ejercita el formateador de verdad**, no `repr()` a secas: `excinfo.getrepr` es el mismo que usa
    el reporte de la terminal, con `funcargs=True` como se lo pasa pytest al renderizar un fallo.
    Probar solo `repr(objeto)` no habría cubierto el defecto, porque el defecto no estaba en el
    mensaje sino en cómo lo renderiza otra herramienta.

    Se asevera sobre la línea `self = ...`, que es **el único marco que el `--tb=auto` por defecto
    —el de CI— renderiza con sus argumentos**. Ver el residual declarado abajo y en el docstring de
    `FugaDatoPersonal`.
    """
    excinfo = _fuga_contaminada()
    renderizado = str(excinfo.getrepr(style="long", funcargs=True))

    linea_self = next((l for l in renderizado.splitlines() if l.startswith("self = FugaDatoPersonal(")), None)
    assert linea_self is not None, "el marco del cable trampa no se renderizó: la prueba no comprobaría nada"
    assert _CURP_INVENTADA not in linea_self, "el traceback del cable trampa reproduce el valor que denuncia"
    # El diagnóstico sobrevive a la elisión: se ve qué se elidió y en qué hoja/fila.
    assert v.TEXTO_ELIDIDO in linea_self and "hoja='Datos'" in linea_self and "fila=1" in linea_self

    # **Residual declarado, no cubierto por ningún `__repr__`.** Con `--tb=long` (que NO es el
    # default) pytest renderiza también el marco del `__init__` que genera `@dataclass`, y ahí los
    # valores crudos son sus propios parámetros: `columna = 'VECJ...'`. Ningún método del objeto
    # puede alcanzar los locales de una función generada. Lo mismo vale para `--showlocals` y para
    # `valores_por_tipo` en el marco del propio auditor. Lo que sí queda cerrado —y es lo que corre
    # en CI— lo fija `test_la_salida_real_de_pytest_no_reproduce_el_valor`.


def test_la_salida_real_de_pytest_no_reproduce_el_valor(tmp_path: Path) -> None:
    """La comprobación autoritativa: **la salida real de `pytest`** en un subproceso, con la
    invocación por defecto (sin `--tb`, sin `-l`), que es la de CI.

    Existe porque `getrepr` es la API del formateador y podría dejar de ser la que usa el reporte
    real. Esto ejercita el binario completo. Y la prueba interna **no** envuelve la llamada en
    `pytest.raises`, que es la situación de las tres pruebas de `tests/test_informe_b10.py` que
    llaman al auditor directamente — las que motivaron el hallazgo.

    El valor se le pasa al subproceso por el entorno y no incrustado en el archivo generado: si
    estuviera en el fuente, el traceback lo imprimiría como parte del código de la prueba y esto
    fallaría por un artefacto del andamiaje, no por el defecto que persigue.
    """
    archivo = tmp_path / "test_fuga_sin_capturar.py"
    archivo.write_text(
        "import os\n"
        "from app.informes import validadores as v\n"
        "\n"
        "def test_dispara_el_cable_trampa() -> None:\n"
        "    v.FugaDatoPersonal(hoja='Datos', fila=1, columna=os.environ['CURP_DE_PRUEBA'],\n"
        "                       tipo='CURP', deteccion='patrón')\n",
        encoding="utf-8",
    )
    raiz = Path(__file__).resolve().parent.parent
    resultado = subprocess.run(
        [sys.executable, "-m", "pytest", str(archivo), "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        cwd=raiz,
        env={**os.environ, "PYTHONPATH": str(raiz), "CURP_DE_PRUEBA": _CURP_INVENTADA},
    )
    salida = resultado.stdout + resultado.stderr

    # Premisas: la prueba interna falló de verdad y su traceback se imprimió con el marco del trampa.
    assert resultado.returncode != 0, "la prueba interna debía fallar; si no, no hay traceback que auditar"
    assert "self = FugaDatoPersonal(" in salida, "el marco del cable trampa no se renderizó: la prueba no comprueba nada"
    assert v.TEXTO_ELIDIDO in salida, "el campo contaminado debe verse elidido, no ausente"
    # Nunca el valor en el mensaje de la aserción: sería la misma fuga que denuncia.
    lineas_con_fuga = [n for n, linea in enumerate(salida.splitlines(), start=1) if _CURP_INVENTADA in linea]
    assert lineas_con_fuga == [], f"la salida real de pytest reproduce el valor en las líneas {lineas_con_fuga}"


def test_el_repr_conserva_el_diagnostico_de_un_hallazgo_limpio() -> None:
    """La mitad negativa, y la razón de no usar `repr=False` a secas: el `repr` **sí** se usa en el
    camino sano —las premisas `assert fugas == []` de `tests/test_informe_b10.py` reportan la lista
    de hallazgos—, así que apagarlo dejaría `<FugaDatoPersonal object at 0x...>` y perdería justo lo
    que hace accionable el fallo. Sin esta prueba, elidir todo pasaría igual."""
    fuga = v.FugaDatoPersonal(hoja="Banderas", fila=2, columna="Mensaje", tipo="CURP", deteccion="valor")

    assert repr(fuga) == "FugaDatoPersonal(hoja='Banderas', fila=2, columna='Mensaje', tipo='CURP', deteccion='valor')"
    assert v.TEXTO_ELIDIDO not in repr(fuga)
    assert v.TEXTO_ELIDIDO not in fuga.descripcion
