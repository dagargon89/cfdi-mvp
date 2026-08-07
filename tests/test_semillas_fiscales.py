"""Coherencia de las semillas fiscales.

Estas pruebas **no** validan los valores contra la ley (eso lo revisa el dueño del repo con el
`README.md` que esta tarea produce): validan que las semillas sean internamente coherentes,
cargables, y que **ninguna llegue confirmada**. Un factor de exención mal capturado no lo atrapa
una prueba; una semilla contradictoria o autoconfirmada sí.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BaseExencion
from app.services import configuracion_fiscal as cfg

_RAIZ = Path(__file__).resolve().parent.parent / "config" / "fiscal"


def test_tabla_de_vacaciones_es_monotona_y_arranca_en_doce() -> None:
    """Art. 76 LFT tras la reforma de 2023: 12 días el primer año, y nunca decrece."""
    datos = yaml.safe_load((_RAIZ / "tabla_vacaciones.yaml").read_text(encoding="utf-8"))
    filas = sorted(datos["tabla_vacaciones"], key=lambda f: f["anios_antiguedad"])
    assert filas[0]["anios_antiguedad"] == 1
    assert filas[0]["dias"] == 12
    dias = [f["dias"] for f in filas]
    assert dias == sorted(dias), "los días de vacaciones no pueden decrecer con la antigüedad"
    assert 20 in dias, "el art. 76 llega a 20 días al quinto año"


def test_la_tabla_de_vacaciones_reproduce_la_progresion_del_articulo_76() -> None:
    """La progresión **exacta** del art. 76 LFT, no solo que no decrezca.

    Ronda 1 de arreglos: `test_tabla_de_vacaciones_es_monotona_y_arranca_en_doce` no protege
    lo que la semilla y el modelo afirman que protege. Cambiar el renglón de 11 años de
    `dias: 24` a `dias: 22` —un dedazo perfectamente verosímil— lo deja pasar: la tabla sigue
    siendo no decreciente, sigue arrancando en 12 y sigue conteniendo el 20. Y esa red es
    justamente el argumento por el que `tabla_vacaciones` no lleva puerta de confirmación, así
    que tenía que ser una red de verdad.

    Aquí se reconstruye la tabla desde el texto del artículo y se compara renglón por renglón:

        "…no podrá ser inferior a doce días laborables, y que aumentará en dos días
         laborables, hasta llegar a veinte, por cada año subsecuente de servicios.
         A partir del sexto año, el periodo de vacaciones aumentará en dos días por cada
         cinco de servicios."

    Se comprueba además la resolución para **todos** los años de 1 a 50, no solo para los que
    tienen renglón propio, porque el resolutor toma el mayor `anios_antiguedad` que no exceda
    la antigüedad consultada: un tramo mal abierto (p. ej. capturar el 12 en vez del 11)
    produciría el valor equivocado para años sin renglón propio aunque la lista de renglones
    se viera bien.

    Alcance, para que la afirmación no crezca de más: esto valida **el archivo del repo**, no
    la fila de la base. No protege contra una edición del YAML en el servidor ni contra un
    `UPDATE` a mano sobre `tabla_vacaciones`.
    """

    def dias_segun_el_articulo_76(anios: int) -> int:
        # Primer párrafo: 12 al primer año, +2 por año subsecuente, hasta llegar a 20 (año 5).
        if anios <= 5:
            return 10 + 2 * anios
        # Segundo párrafo: a partir del sexto, +2 por cada cinco años de servicios.
        return 20 + 2 * ((anios - 1) // 5)

    datos = yaml.safe_load((_RAIZ / "tabla_vacaciones.yaml").read_text(encoding="utf-8"))
    filas = sorted(datos["tabla_vacaciones"], key=lambda f: f["anios_antiguedad"])

    for fila in filas:
        anios, dias = fila["anios_antiguedad"], fila["dias"]
        esperado = dias_segun_el_articulo_76(anios)
        assert dias == esperado, (
            f"art. 76 LFT: con {anios} año(s) de antigüedad corresponden {esperado} días, "
            f"y la semilla dice {dias}"
        )

    # La resolución completa, incluidos los años sin renglón propio.
    for anios in range(1, 51):
        aplicable = max(
            (f for f in filas if f["anios_antiguedad"] <= anios), key=lambda f: f["anios_antiguedad"]
        )
        esperado = dias_segun_el_articulo_76(anios)
        assert aplicable["dias"] == esperado, (
            f"con {anios} año(s) el resolutor tomaría el renglón de {aplicable['anios_antiguedad']} "
            f"({aplicable['dias']} días) y el art. 76 da {esperado}"
        )


def test_marcas_de_percepcion_son_coherentes() -> None:
    """Un tipo con base de exención distinta de NINGUNA debe traer factor, y al revés."""
    datos = yaml.safe_load((_RAIZ / "catalogo_percepcion.yaml").read_text(encoding="utf-8"))
    for fila in datos["catalogo_percepcion_marca"]:
        tipo = fila["tipo_percepcion"]
        assert isinstance(tipo, str), f"la clave {tipo!r} debe ser texto, no entero"
        assert len(tipo) == 3, f"la clave {tipo!r} debe tener tres posiciones"
        if fila["base_exencion"] == "NINGUNA":
            assert fila.get("factor_exencion") is None, f"{tipo}: sin base de exención no puede haber factor"
        else:
            assert fila.get("factor_exencion") is not None, f"{tipo}: con base de exención hace falta el factor"
            assert float(fila["factor_exencion"]) > 0, f"{tipo}: el factor debe ser positivo"


def test_separacion_y_jubilacion_no_son_ingreso_ordinario() -> None:
    """B-05.R4: tienen régimen fiscal propio (arts. 95 y 96 LISR) y no se acumulan al ordinario.

    Los cinco códigos están verificados contra el catálogo real de satcfdi
    (`C75b_c_TipoPercepcion`, 44 tipos), no de memoria:
      022 Prima por antigüedad · 023 Pagos por separación · 025 Indemnizaciones
      039 Jubilaciones, pensiones o haberes de retiro · 044 idem en parcialidades
    Los tres primeros caen bajo el art. 95 de la LISR, que los agrupa explícitamente
    ("primas de antigüedad, retiro e indemnizaciones u otros pagos por separación").
    Omitir 025 marcaría las indemnizaciones como ingreso ordinario y **sobreestimaría la
    base anual del ISR** en la columna 11 de B-05.

    Ronda 1 de arreglos: se agregan 051, 052 y 053. Esos cinco eran una lista de VERIFICACIÓN
    (se comprobó que están bien), no una lista EXHAUSTIVA, y la primera semilla los confundió:
    dejó los tres tipos de pagos a extrabajadores jubilados como ingreso ordinario gravado
    "por prudencia". El catálogo del SAT no es ambiguo con ellos —dice literalmente
    "derivados de jubilación en parcialidades", "obtengan una jubilación en parcialidades" y
    "una jubilación en una sola exhibición"—, así que son pagos de jubilación y les alcanza el
    mismo régimen: la fracción IV del art. 93 a los dos de parcialidades y la XIII (vía art.
    96-Bis) al de una sola exhibición. Dejarlos gravados no era la opción conservadora, era la
    marca equivocada en la dimensión de mayor efecto.
    """
    datos = yaml.safe_load((_RAIZ / "catalogo_percepcion.yaml").read_text(encoding="utf-8"))
    por_tipo = {f["tipo_percepcion"]: f for f in datos["catalogo_percepcion_marca"]}
    for tipo in ("022", "023", "025", "039", "044", "051", "052", "053"):
        assert tipo in por_tipo, f"falta sembrar el tipo {tipo}"
        assert por_tipo[tipo]["es_ingreso_ordinario"] is False, f"{tipo} no es ingreso ordinario"


def test_todo_parametro_fiscal_declara_su_fuente() -> None:
    """Sin fuente, un revisor no puede verificar el valor: es el requisito que hace la semilla
    auditable, y por eso el cargador lo exige."""
    datos = yaml.safe_load((_RAIZ / "param_fiscal.yaml").read_text(encoding="utf-8"))
    for fila in datos["param_fiscal"]:
        fuente = fila.get("fuente", "")
        assert fuente, f"{fila['clave']}: falta la fuente"
        assert "http" in fuente or any(c.isdigit() for c in fuente), (
            f"{fila['clave']}: la fuente debe citar una liga o una fecha de publicación, no ser genérica")


def test_toda_marca_dudosa_esta_senalada() -> None:
    """Las 39 dudas declaradas son un **campo**, no un comentario.

    Ronda 2 de la tarea 4. Antes esta prueba recorría las líneas buscando la cadena `REVISAR`
    y comprobaba que llevaran un dígito; al pasar las dudas a `nota_revision` se habría quedado
    sin ninguna línea que mirar y habría seguido en verde sin comprobar nada — la prueba
    fantasma otra vez. Ahora comprueba lo que de verdad importa: que las 39 sigan ahí y que
    lleguen a la fila, porque los comentarios no se cargan y la pantalla de confirmación las
    necesita al lado del botón.
    """
    datos = yaml.safe_load((_RAIZ / "catalogo_percepcion.yaml").read_text(encoding="utf-8"))
    filas = datos["catalogo_percepcion_marca"]
    con_duda = {f["tipo_percepcion"] for f in filas if (f.get("nota_revision") or "").strip()}
    sin_duda = {f["tipo_percepcion"] for f in filas} - con_duda

    assert len(filas) == 44
    assert sin_duda == {"001", "002", "003", "021", "028"}, (
        "cambió el conjunto de tipos sin duda declarada; si es a propósito, actualiza también "
        "config/fiscal/README.md §5.3"
    )
    assert len(con_duda) == 39
    for fila in filas:
        nota = fila.get("nota_revision")
        if nota is not None:
            # Decir QUÉ genera la duda, no solo que la hay: una nota de tres palabras no le
            # sirve a quien tiene que decidir si confirma.
            assert len(nota.strip()) > 40, f"{fila['tipo_percepcion']}: la duda es demasiado escueta"


async def test_las_dudas_declaradas_llegan_a_la_base(db: AsyncSession) -> None:
    """El defecto que motivó la columna: las 39 dudas estaban en comentarios `# REVISAR` del
    YAML, los comentarios no se cargan, y la pantalla acababa ofreciendo 44 botones
    "Confirmar" sin una sola razón para dudar a la vista. Es el mismo caso que
    `sujeto_a_tope_conjunto`: si algo tiene que verse al confirmar, tiene que ser una columna.
    """
    await cfg.cargar_desde_yaml(db, _RAIZ / "catalogo_percepcion.yaml")
    marcas = await cfg.marcas_propuestas(db)

    con_nota = {tipo for tipo, m in marcas.items() if m.nota_revision}
    assert len(con_nota) == 39
    # Verbatim, no resumida: el valor de la nota está en el texto que se derivó contra la ley.
    assert "art. 27, fracción VII LSS" in (marcas["010"].nota_revision or "")
    # Los subpuntos (a)/(b) sobreviven al viaje: son renglones lógicos, no ajuste de ancho.
    nota_011 = marcas["011"].nota_revision or ""
    assert "\n(a) " in nota_011 and "\n(b) " in nota_011


async def test_las_semillas_se_cargan_y_ninguna_queda_confirmada(db: AsyncSession) -> None:
    """El invariante de la fase, aplicado a las semillas: cargar propone, no activa."""
    await cfg.cargar_desde_yaml(db, _RAIZ / "tabla_vacaciones.yaml")
    await cfg.cargar_desde_yaml(db, _RAIZ / "catalogo_percepcion.yaml")
    resumen = await cfg.cargar_desde_yaml(db, _RAIZ / "param_fiscal.yaml")
    assert resumen["param_fiscal"] > 0

    # La ley se aplica sola (no lleva confirmación); los importes, no.
    assert await cfg.dias_de_vacaciones(db, 1) == 12
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) is None
    propuesto = await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 1))
    assert propuesto is not None
    assert "inegi" in propuesto.fuente.lower()


async def test_el_tope_conjunto_de_prevision_social_llega_a_la_base(db: AsyncSession) -> None:
    """Los seis tipos sujetos al tope conjunto tienen que ser identificables por máquina.

    Ronda 1 de arreglos. Hay 16 renglones con `base_exencion: PORCENTAJE` y solo seis están
    sujetos al tope conjunto de previsión social del penúltimo párrafo del art. 93 LISR; los
    otros diez están exceptuados por el último párrafo. Antes esa distinción vivía **solo en
    los comentarios del YAML**, que no se cargan: quien calculara la exención tendría que
    llevar la lista escrita en el código de B-03 — una lista fiscal codificada en el programa,
    justo lo que prohíbe el §2.12. Por eso es una columna.

    La prueba comprueba las dos mitades: que los seis lleguen marcados, y que ninguno de los
    otros diez con base PORCENTAJE lo esté (un `true` de más exenta de menos, y es igual de
    silencioso que un `true` de menos).
    """
    await cfg.cargar_desde_yaml(db, _RAIZ / "catalogo_percepcion.yaml")
    marcas = await cfg.marcas_propuestas(db)

    con_tope = {tipo for tipo, m in marcas.items() if m.sujeto_a_tope_conjunto}
    assert con_tope == {"015", "029", "030", "034", "035", "037"}, (
        "cambió el conjunto de tipos sujetos al tope conjunto de previsión social; si es a "
        "propósito, actualiza también config/fiscal/README.md §5.3.D"
    )

    # Ningún tipo sin exención puede llevar el tope: no hay exención que topar.
    for tipo, marca in marcas.items():
        if marca.sujeto_a_tope_conjunto:
            assert marca.base_exencion is not BaseExencion.NINGUNA, f"{tipo}: tope sin exención"


async def test_las_dos_zonas_de_salario_minimo_estan_sembradas(db: AsyncSession) -> None:
    """Las dos, porque la zona aplicable es configuración de cada empresa y no se puede adivinar."""
    await cfg.cargar_desde_yaml(db, _RAIZ / "param_fiscal.yaml")
    for clave in ("SALARIO_MINIMO_GENERAL", "SALARIO_MINIMO_ZLFN"):
        assert await cfg.valor_propuesto(db, clave, date(2026, 6, 1)) is not None, f"falta sembrar {clave}"
