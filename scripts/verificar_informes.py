"""Verificación en vivo de los informes de nómina contra los datos reales (spec §13, §14).

Comprueba las 9 identidades de B-00 (fuente: `Hub_CFDI_docs/00-fuentes/especificacion-
informes-cfdi.md`, sección "B-00 · Definiciones comunes al grupo") sobre los CFDI de
nómina ya normalizados, que B-02 produce filas y columnas dinámicas consistentes con esos
mismos datos, y (desde la fase 2) que **los seis informes del catálogo** —no solo B-02—
corren sin lanzar, no salen vacíos por error, enmascaran toda columna `sensible=True` y **no
dejan ninguna CURP ni ningún NSS de ningún empleado en ninguna celda de ninguna de las cuatro
hojas**.

Esa última comprobación se agregó en la revisión final de la fase 2 y es la razón por la que
este script no vio la fuga más grave del catálogo: comprobaba el **mecanismo** (que las columnas
declaradas `sensible=True` salieran enmascaradas) y nunca el **resultado** (que las columnas no
sensibles no trajeran el dato personal dentro de una frase). B-10 interpolaba la CURP y el NSS en
su columna "Descripción del hallazgo" —no sensible, y que no puede serlo sin volverse ilegible—,
así que 6 de 7 filas salían con el dato completo con `enmascarar_datos_personales=True`.

**Ahora compara por patrón Y por valor, sobre las cuatro hojas.** La red vive en
`validadores.fugas_de_datos_personales_en_libro`, compartida con la prueba anti-fuga de
`tests/test_informe_b10.py`. Hasta el cierre de la fase 2 este script solo buscaba por **patrón**
y solo en la hoja `Datos`, con el argumento de que no debía manejar CURP ni NSS reales. Ese
argumento se descartó a propósito: el script **ya** lee la BD real (calcula las identidades de
B-00 sobre los datos de nómina, que incluyen al receptor), así que ya tiene acceso; compararlos en
memoria sin imprimirlos es seguro; y es la **única** forma de atrapar una CURP **mal formada**
interpolada en un mensaje, que por definición no coincide con el patrón de una CURP. Las hojas
`Banderas`, `Parámetros` y `Diccionario` se auditan porque viajan en el mismo archivo: un mensaje
de bandera que interpolara un dato personal salía igual de la empresa, y los mensajes de bandera
son texto libre.

**Contrato duro que eso no cambia:** este script **nunca imprime** una CURP, un NSS ni una cuenta
bancaria. Cuando encuentra una fuga reporta la hoja, la fila, la columna y el tipo de dato —nunca
el valor— porque se corre en una terminal cuyo historial queda guardado.

Las identidades **no se implementan aquí**: viven en `app/informes/identidades_b00.py` y
`tests/test_identidades_b00.py` las corre en cada pasada de la suite sobre XML sintéticos.
Este script es el otro llamador de esa misma implementación, el que la ejerce contra los
CFDI reales. Antes las identidades vivían solo en este archivo, fuera de `testpaths`, así
que nada las mantenía verdes.

Deliberadamente **no hardcodea** cuántas nóminas, filas o columnas dinámicas esperar: eso
quedaría obsoleto en cuanto se descargue más historia del SAT. Lo que sí es fijo son las
identidades contables — un XML timbrado por el SAT las cumple por construcción, así que
si alguna falla aquí es un bug de nuestro ETL, nunca un dato malo.

No imprime CURP, NSS ni cuenta bancaria: son datos personales de personas reales y esto
se corre en una terminal cuyo historial queda guardado.

Uso: `python scripts/verificar_informes.py` (dentro del contenedor `api`, o con el `.venv`
del host apuntando a la misma base). Sale con código 1 si alguna comprobación falla.
"""

from __future__ import annotations

import asyncio
import io
import re
import sys
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import openpyxl

from app.db.session import SessionLocal
from app.informes import b02_conceptos_patron as b02
from app.informes import excel, identidades_b00, registro, validadores
from app.informes.base import ContextoInforme
from app.models.comprobante import Comprobante
from app.models.nomina import NominaReceptor
from app.services import normalizacion

EMPRESA_ID = 11

_HOJAS_ESPERADAS = {"Datos", "Parámetros", "Banderas", "Diccionario"}
_MASCARA_RE = re.compile(r"^\*{4}([^*]{4})?$")  # `enmascarar()`: "****" o "****" + últimos 4

# Grano garantizado no vacío cuando hay nóminas normalizadas en el rango: una fila por
# CFDI (B-01, B-02), por nodo de percepción (B-03), por empleado (B-04, B-05) o por
# (empleado, tipo, clave) de deducción (B-07). B-10 tiene grano de *hallazgo*: cero filas ahí
# significa "sin hallazgos", un resultado legítimo que no debe tratarse como falla — solo se
# avisa.
#
# B-03 entra en la lista aunque sus columnas de topes salgan vacías mientras la configuración
# fiscal esté sin confirmar: lo que degrada son cuatro columnas, no el grano. Un CFDI de
# nómina normalizado siempre trae al menos un nodo de percepción, así que cero filas ahí es
# una falla igual que en B-02.
_CLAVES_CON_FILAS_GARANTIZADAS = {"B-01", "B-02", "B-03", "B-04", "B-05", "B-07"}


_MAX_FUGAS_REPORTADAS = 10
"""Cuántas fugas se detallan por informe antes de resumir el resto. Una fuga real suele afectar a
todas las filas de una columna; con cientos de empleados la lista completa sepultaría las demás
fallas del script — el mismo razonamiento que el colapso de `ESTATUS_NO_VERIFICADO`."""


async def _valores_personales_del_universo(db: AsyncSession) -> dict[str, list[str]]:
    """CURP y NSS de **todos** los receptores de nómina de la empresa, para la comprobación por
    valor de `validadores.fugas_de_datos_personales_en_libro`.

    **Se leen a propósito, y no se imprimen nunca.** Es el único modo de atrapar una CURP mal
    formada interpolada en un mensaje: por definición no coincide con el patrón de una CURP, así
    que el detector estructural no puede verla. Y se recogen de **todo** el universo, no de la fila
    que se está auditando, porque una CURP de otro empleado en la celda de un tercero se escapaba
    de las dos redes a la vez. Solo viven en memoria y solo se usan como aguja de una búsqueda de
    subcadena; lo que sale a la consola es el conteo, nunca un valor.
    """
    consulta = (
        select(NominaReceptor.curp, NominaReceptor.nss)
        .join(Comprobante, Comprobante.comprobante_id == NominaReceptor.comprobante_id)
        .where(Comprobante.empresa_id == EMPRESA_ID)
        .distinct()
    )
    curps: set[str] = set()
    nss: set[str] = set()
    for curp, numero_seguridad in (await db.execute(consulta)).all():
        if curp:
            curps.add(str(curp))
        if numero_seguridad:
            nss.add(str(numero_seguridad))
    print(f"Datos personales del universo para la comprobación por valor: {len(curps)} CURP y {len(nss)} NSS (no se imprimen)")
    return {"CURP": sorted(curps), "NSS": sorted(nss)}


async def _verificar_identidades_b00(db: AsyncSession) -> tuple[int, list[str]]:
    """Corre las identidades del módulo compartido y las reporta por consola."""
    v = await identidades_b00.verificar(db, EMPRESA_ID)

    print(f"CFDI de nómina normalizados: {v.comprobantes}")
    if not v.comprobantes:
        print("FALLA: no hay nóminas normalizadas; ¿corrió el reproceso (normalizacion_lote.normalizar_lote)?")
        return 0, ["no hay CFDI de nómina normalizados"]

    # `cotejos` es lo que hace auditable a la propia verificación: sin él, "cero fallas" no
    # distingue entre "todo cuadra" y "no se comprobó nada". Se imprime el número real, no el
    # teórico: un atributo ausente en el XML no se compara y por tanto no cuenta.
    print(f"Cotejos ejecutados: {v.cotejos} (máximo {identidades_b00.COTEJOS_POR_COMPROBANTE_COMPLETO} por CFDI)")
    if v.cotejos < v.comprobantes * identidades_b00.IDENTIDADES_POR_COMPROBANTE:
        print(
            f"AVISO: se esperaban al menos {v.comprobantes * identidades_b00.IDENTIDADES_POR_COMPROBANTE} cotejos. "
            "Algún atributo del complemento no vino en el XML; revisa qué CFDI y por qué."
        )

    return v.comprobantes, v.fallas


async def _verificar_b02(db: AsyncSession, comprobantes_normalizados: int) -> list[str]:
    fallas: list[str] = []

    resultado = await b02.consultar(
        db,
        EMPRESA_ID,
        b02.Parametros(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 12, 31)),
    )
    dinamicas = [c.titulo for c in resultado.columnas if b02.SEPARADOR_ETIQUETA in c.titulo]
    print(f"\nB-02: {len(resultado.filas)} filas, {len(resultado.columnas)} columnas totales, {len(dinamicas)} columnas dinámicas, {len(resultado.banderas)} banderas")
    print("Conceptos detectados (naturaleza¦tipo¦clave¦concepto):")
    for titulo in dinamicas:
        print("  ", titulo)

    if len(resultado.filas) != comprobantes_normalizados:
        fallas.append(
            f"B-02 devolvió {len(resultado.filas)} filas para {comprobantes_normalizados} CFDI de nómina normalizados en el rango 2026-01-01/2026-12-31"
        )
    if not dinamicas:
        fallas.append("B-02 no produjo ninguna columna dinámica; ¿hay datos en nomina_percepcion/deduccion/otro_pago?")
    if not resultado.diccionario:
        fallas.append("B-02 no produjo entradas de Diccionario para las columnas dinámicas detectadas")

    # Caso real de colisión que B-02.R3 debe resolver: `099` como clave de deducción y de
    # otro pago a la vez ("Ajuste al neto" en ambas naturalezas). Si aparece, confirma que
    # el prefijo de naturaleza en la etiqueta evita que se confundan; si no aparece en este
    # rango de datos no es una falla — es informativo.
    claves_por_tipo: dict[str, set[str]] = {"P": set(), "O": set(), "D": set()}
    for titulo in dinamicas:
        partes = titulo.split(b02.SEPARADOR_ETIQUETA)
        if len(partes) >= 3:
            claves_por_tipo.setdefault(partes[0], set()).add(partes[2])
    colisiones = claves_por_tipo["D"] & claves_por_tipo["O"]
    if colisiones:
        print(f"Claves compartidas entre deducción y otro pago (naturaleza distinta, R3 en acción): {sorted(colisiones)}")

    if resultado.banderas:
        print("\nBanderas de B-02:")
        for bandera in resultado.banderas:
            print(f"  [{bandera.severidad}] {bandera.clave} · {bandera.ambito} · {bandera.mensaje}")
        if any(bandera.clave == "TOTALES_DESCUADRADOS" for bandera in resultado.banderas):
            fallas.append(
                "B-02 emitió TOTALES_DESCUADRADOS sobre CFDI reales timbrados por el SAT: es un bug del ETL, no un hallazgo del informe"
            )
    else:
        print("\nB-02 no emitió banderas.")

    return fallas


def _parametros_minimos(clave: str) -> dict[str, object]:
    """Parámetros mínimos —solo lo requerido, todo lo demás con su default declarado,
    incluido `enmascarar_datos_personales=True`— para ejercitar cada informe del catálogo
    contra el histórico completo de la empresa."""
    if clave == "B-05":
        return {"ejercicio": 2026}
    return {"fecha_desde": date(2026, 1, 1), "fecha_hasta": date(2026, 12, 31)}


async def _verificar_informe_del_catalogo(
    db: AsyncSession, clave: str, comprobantes_normalizados: int, valores_personales: dict[str, list[str]]
) -> list[str]:
    """Corre un informe del catálogo end-to-end (consulta + libro de Excel) y comprueba
    que no lance, que su grano no salga vacío por error, que ninguna columna declarada
    `sensible=True` se cuele sin enmascarar al archivo que circula por correo, y que ninguna de las
    cuatro hojas lleve la CURP o el NSS de ningún empleado del universo."""
    definicion = registro.obtener(clave)

    try:
        p = definicion.Parametros(**_parametros_minimos(clave))
        resultado = await definicion.consultar(db, EMPRESA_ID, p)
    except Exception as exc:  # noqa: BLE001 — se reporta cualquier excepción, no se re-lanza
        return [f"{clave} lanzó al generarse: {type(exc).__name__}: {exc}"]

    fallas: list[str] = []
    print(f"\n{clave}: {len(resultado.filas)} filas, {len(resultado.columnas)} columnas, {len(resultado.banderas)} banderas")

    if not resultado.filas:
        mensaje = f"{clave} devolvió 0 filas con {comprobantes_normalizados} CFDI de nómina normalizados en el rango"
        if clave in _CLAVES_CON_FILAS_GARANTIZADAS and comprobantes_normalizados:
            fallas.append(mensaje)
        elif comprobantes_normalizados:
            print(f"  AVISO: {mensaje} (grano de hallazgo: puede ser un resultado legítimo, no se marca como falla)")

    ctx = ContextoInforme(
        clave=definicion.CLAVE,
        nombre=definicion.NOMBRE,
        usuario="verificacion@script",
        generado_en=datetime.now(timezone.utc).replace(tzinfo=None),
        parametros=p.model_dump(mode="json"),
        etl_version=normalizacion.ETL_VERSION,
    )
    libro = openpyxl.load_workbook(io.BytesIO(excel.escribir_libro(resultado, ctx)))

    if set(libro.sheetnames) != _HOJAS_ESPERADAS:
        fallas.append(f"{clave} no tiene las cuatro hojas esperadas: {libro.sheetnames}")
        return fallas

    ws = libro["Datos"]
    filas_datos = list(ws.iter_rows(min_row=2, values_only=True))

    columnas_sensibles = [i for i, columna in enumerate(resultado.columnas) if columna.sensible]
    if columnas_sensibles:
        for fila in filas_datos:
            for idx in columnas_sensibles:
                valor = fila[idx] if idx < len(fila) else None
                if valor is None or valor == "":
                    continue
                if not _MASCARA_RE.match(str(valor)):
                    fallas.append(
                        f"{clave}: la columna sensible '{resultado.columnas[idx].titulo}' salió sin enmascarar "
                        "(¿escribir_libro no recibió enmascarar_datos_personales=True?)"
                    )
                    break
            if fallas:
                break

    # La comprobación de arriba verifica el **mecanismo** (que las columnas declaradas sensibles
    # salgan enmascaradas); esta verifica el **resultado**, que es lo que nadie comprobaba y por lo
    # que B-10 emitía CURP y NSS completos con el enmascaramiento activado: los interpolaba en el
    # texto de su columna "Descripción del hallazgo", que no es sensible ni puede serlo. Se auditan
    # las CUATRO hojas (viajan en el mismo archivo) y por las dos vías (patrón y valor); ver el
    # docstring del módulo y `validadores.fugas_de_datos_personales_en_libro`. Nunca se imprime el
    # valor encontrado —solo hoja, fila, columna y tipo— porque este script se corre en una terminal
    # cuyo historial queda guardado.
    fugas = validadores.fugas_de_datos_personales_en_libro(libro, valores_personales)
    for fuga in fugas[:_MAX_FUGAS_REPORTADAS]:
        fallas.append(f"{clave}: dato personal en el libro con enmascarar_datos_personales=True — {fuga.descripcion}")
    if len(fugas) > _MAX_FUGAS_REPORTADAS:
        fallas.append(f"{clave}: y {len(fugas) - _MAX_FUGAS_REPORTADAS} fuga(s) más de datos personales en el mismo libro")

    return fallas


async def _verificar_catalogo(db: AsyncSession, comprobantes_normalizados: int, valores_personales: dict[str, list[str]]) -> list[str]:
    """Recorre los seis informes del catálogo (Task 8, fase 2): el registro es la fuente
    de verdad de lo que existe, así que un informe nuevo entra a esta comprobación en
    cuanto se registra en `app.informes.registro`, sin tocar este script."""
    fallas: list[str] = []
    for clave in sorted(registro.REGISTRO):
        fallas.extend(await _verificar_informe_del_catalogo(db, clave, comprobantes_normalizados, valores_personales))
    return fallas


async def main() -> int:
    async with SessionLocal() as db:
        comprobantes_normalizados, fallas_b00 = await _verificar_identidades_b00(db)
        print(f"Identidades de B-00 por CFDI: {identidades_b00.IDENTIDADES_POR_COMPROBANTE}")

        fallas_b02 = await _verificar_b02(db, comprobantes_normalizados)
        valores_personales = await _valores_personales_del_universo(db)
        fallas_catalogo = await _verificar_catalogo(db, comprobantes_normalizados, valores_personales)

    fallas = fallas_b00 + fallas_b02 + fallas_catalogo
    if fallas:
        print("\nFALLAS:")
        for falla in fallas:
            print("  -", falla)
        return 1
    print("\nTodas las comprobaciones pasaron.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
