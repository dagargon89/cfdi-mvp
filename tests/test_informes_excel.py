"""Motor de informes: el libro común de cuatro hojas (spec §10) y el enmascaramiento.

Las aserciones se hacen sobre valores de celda, nunca sobre bytes del archivo (spec §13).
"""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from openpyxl import load_workbook

from app.informes import excel
from app.informes.base import Bandera, Columna, ContextoInforme, EntradaDiccionario, ResultadoInforme


def _resultado_demo() -> ResultadoInforme:
    return ResultadoInforme(
        columnas=[
            Columna(titulo="UUID", tipo="texto"),
            Columna(titulo="Fecha pago", tipo="fecha"),
            Columna(titulo="P¦001¦001¦Sueldo", tipo="monto"),
        ],
        filas=[["11111111-1111-1111-1111-111111111111", datetime(2026, 6, 30).date(), Decimal("8759.700000")]],
        banderas=[Bandera(clave="NETO_NEGATIVO", severidad="alta", ambito="uuid:1111", mensaje="El total es negativo.")],
        diccionario=[
            EntradaDiccionario(
                etiqueta="P¦001¦001¦Sueldo",
                naturaleza="P",
                tipo="001",
                descripcion_sat="Sueldos, Salarios Rayas y Jornales",
                clave_patron="001",
                concepto_canonico="Sueldo",
                descripciones_alternas=["Sueldos"],
                num_comprobantes=8,
                importe_total=Decimal("70077.60"),
            )
        ],
    )


def _contexto() -> ContextoInforme:
    return ContextoInforme(
        clave="B-02",
        nombre="Nómina agrupada por conceptos del patrón",
        usuario="dgarcia@planjuarez.org",
        generado_en=datetime(2026, 8, 5, 11, 30, 0),
        parametros={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31", "enmascarar_datos_personales": True},
        etl_version=1,
    )


def test_libro_tiene_las_cuatro_hojas() -> None:
    wb = load_workbook(io.BytesIO(excel.escribir_libro(_resultado_demo(), _contexto())))
    assert wb.sheetnames == ["Datos", "Parámetros", "Banderas", "Diccionario"]


def test_hoja_datos_lleva_encabezado_y_valores() -> None:
    wb = load_workbook(io.BytesIO(excel.escribir_libro(_resultado_demo(), _contexto())))
    ws = wb["Datos"]

    assert [c.value for c in ws[1]] == ["UUID", "Fecha pago", "P¦001¦001¦Sueldo"]
    fila = [c.value for c in ws[2]]
    assert fila[0] == "11111111-1111-1111-1111-111111111111"
    # Redondeo único al presentar (R-T4): 6 decimales en BD → 2 en la celda.
    assert float(fila[2]) == 8759.70
    # Encabezado congelado para que la tabla sea navegable.
    assert ws.freeze_panes == "A2"


def test_hoja_parametros_permite_reproducir_la_corrida() -> None:
    """Sin esta hoja un Excel circulando por correo no se puede auditar (spec §10)."""
    wb = load_workbook(io.BytesIO(excel.escribir_libro(_resultado_demo(), _contexto())))
    ws = wb["Parámetros"]
    contenido = {ws.cell(row=f, column=1).value: ws.cell(row=f, column=2).value for f in range(1, ws.max_row + 1)}

    assert contenido["Informe"] == "B-02 · Nómina agrupada por conceptos del patrón"
    assert contenido["Generado por"] == "dgarcia@planjuarez.org"
    assert contenido["Versión del ETL"] == 1
    assert contenido["Filas"] == 1
    assert contenido["fecha_desde"] == "2026-06-01"
    assert contenido["enmascarar_datos_personales"] == "True"


def test_hoja_banderas_y_diccionario() -> None:
    wb = load_workbook(io.BytesIO(excel.escribir_libro(_resultado_demo(), _contexto())))

    banderas = wb["Banderas"]
    assert [c.value for c in banderas[1]] == ["Bandera", "Severidad", "Ámbito", "Mensaje"]
    assert [c.value for c in banderas[2]] == ["NETO_NEGATIVO", "alta", "uuid:1111", "El total es negativo."]

    diccionario = wb["Diccionario"]
    fila = [c.value for c in diccionario[2]]
    assert fila[0] == "P¦001¦001¦Sueldo"
    assert fila[1] == "P"
    assert fila[3] == "Sueldos, Salarios Rayas y Jornales"
    assert fila[6] == "Sueldos"  # descripciones alternas, unidas por '; '


def test_informe_vacio_produce_libro_con_aviso_no_una_excepcion() -> None:
    """spec §9: sin filas no es un error."""
    vacio = ResultadoInforme(columnas=[Columna(titulo="UUID", tipo="texto")], filas=[], aviso="Sin comprobantes en el rango solicitado.")
    wb = load_workbook(io.BytesIO(excel.escribir_libro(vacio, _contexto())))

    assert "Datos" in wb.sheetnames
    parametros = wb["Parámetros"]
    contenido = {parametros.cell(row=f, column=1).value: parametros.cell(row=f, column=2).value for f in range(1, parametros.max_row + 1)}
    assert contenido["Filas"] == 0
    assert contenido["Aviso"] == "Sin comprobantes en el rango solicitado."


def test_enmascarar_conserva_los_ultimos_cuatro() -> None:
    assert excel.enmascarar("XXXX800101HCHXXX01") == "****XX01"
    assert excel.enmascarar("12345678901") == "****8901"
    assert excel.enmascarar(None) is None
    assert excel.enmascarar("123") == "****"  # demasiado corto para conservar 4


def test_columna_sensible_se_enmascara_solo_si_el_parametro_esta_activo() -> None:
    """El motor, no el informe, decide si enmascara (ronda de corrección 1): un informe solo
    marca `sensible=True` y entrega el dato en claro."""
    resultado = ResultadoInforme(
        columnas=[
            Columna(titulo="CURP", tipo="texto", sensible=True),
            Columna(titulo="Nombre", tipo="texto"),
        ],
        filas=[["XXXX800101HCHXXX01", "Juan Pérez"]],
    )
    ctx_enmascarado = replace(_contexto(), parametros={"enmascarar_datos_personales": True})
    ctx_en_claro = replace(_contexto(), parametros={"enmascarar_datos_personales": False})

    wb_enmascarado = load_workbook(io.BytesIO(excel.escribir_libro(resultado, ctx_enmascarado)))
    fila = [c.value for c in wb_enmascarado["Datos"][2]]
    assert fila[0] == "****XX01"
    assert fila[1] == "Juan Pérez"  # la columna no sensible nunca se toca

    wb_en_claro = load_workbook(io.BytesIO(excel.escribir_libro(resultado, ctx_en_claro)))
    fila = [c.value for c in wb_en_claro["Datos"][2]]
    assert fila[0] == "XXXX800101HCHXXX01"
    assert fila[1] == "Juan Pérez"


def test_columna_decimal_no_se_redondea_a_dos_decimales() -> None:
    """Solo `monto` se redondea a 2 decimales (R-T4); `decimal` conserva su precisión."""
    resultado = ResultadoInforme(columnas=[Columna(titulo="Tasa", tipo="decimal")], filas=[[Decimal("12.345678")]])
    wb = load_workbook(io.BytesIO(excel.escribir_libro(resultado, _contexto())))
    valor = wb["Datos"][2][0].value
    assert round(float(valor), 6) == 12.345678
