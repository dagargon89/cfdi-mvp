"""La hoja de revisión de una tarifa del ISR — lo que el dueño del Hub le manda a su contador.

El dueño del Hub no es contador. Quien tiene que decir si la tarifa del ISR está fiscalmente
correcta es su contador, y ese contador **no tiene cuenta en la aplicación**: confirmar exige rol
de administrador, y dárselo a alguien externo le abriría la bóveda de e.firmas, los usuarios y la
bitácora completa — inaceptable para una sola revisión. La solución acordada (§7.4 del diseño): el
dueño confirma, y esta hoja es lo que le manda al contador para que la revise **antes**.

Eso fija el contenido: todo lo que hace falta para decir "sí, es correcta" sin entrar al sistema
— la tarifa completa con las tasas en porcentaje, de dónde salió y con qué huella, si algún
renglón se corrigió a mano, la comprobación contra un recibo real (rotulada como lo que es, una
comprobación de carga y no un dictamen), y qué falta o quién ya confirmó. Y fija el formato: un
PDF, generado en el servidor y no con la impresión del navegador, porque el archivo se adjunta a
un correo tal cual — eso es justo lo que se va a hacer con él.

Sigue el patrón de `app.services.representaciones` (weasyprint, HTML armado a mano con
`html.escape`, sin plantillas), pero en hoja **vertical** (`letter portrait`): esto es una tabla
larga y angosta, no un acuse de una sola página horizontal como el "Detalle del CFDI".

**Divergencia declarada del §7.4 del diseño:** el diseño pedía "imprimible y exportable a Excel,
reutilizando el motor de informes". Aquí se entrega solo el PDF. El motor de informes exige
universo, banderas y parámetros que una hoja de una sola tabla no tiene, y un PDF ya es imprimible
y adjuntable — forzar el motor de informes aquí lo convertiría en el sitio equivocado para un
documento de una sola tabla. Si el contador llega a pedir Excel, es un añadido, no un rediseño.

**Todo lo que viene de datos se escapa con `html.escape`, incluido `encabezado`**: ese texto sale
del documento que alguien subió (Task 3, `anexo8.extraer`), así que es entrada externa igual que
cualquier otro dato de usuario, aunque hoy en la práctica solo lo produzca un extractor confiable.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from app.models.enums import OrigenTarifa
from app.repositories.tarifa_isr import TarifaGuardada
from app.services import tarifa_isr as reglas
from app.services.comprobacion_tarifa import Comprobacion

_ROTULO_NO_DICTAMEN = (
    "Esto no es un dictamen fiscal: es una comprobación de que la tarifa se cargó bien."
)


def _fecha(dt: datetime | None) -> str:
    """Formato legible para un contador. Todas las columnas `DateTime` del proyecto son naive en
    UTC (ver `tarifa_isr._ahora`), así que no hace falta convertir zona horaria aquí."""
    return escape(dt.strftime("%d/%m/%Y %H:%M")) if dt is not None else "—"


def _renglon_html(r: reglas.Renglon, *, corregido_a_mano: bool) -> str:
    """Una fila de la tabla de renglones. El **porcentaje es la columna principal** —como lo
    publica el SAT y como lo lee un contador—, con la fracción cruda al lado como dato
    secundario, nunca al revés.

    La conversión a porcentaje reutiliza `app.api.v1.configuracion._a_porcentaje` (import
    diferido, ver `hoja_html`): es el único número de toda la hoja donde equivocar la escala
    cambia el resultado por cien, y no hay motivo para tener una segunda multiplicación por 100
    en el sistema cuando ya existe una.
    """
    from app.api.v1.configuracion import _a_porcentaje

    limite_superior = str(r.limite_superior) if r.limite_superior is not None else "En adelante"
    porcentaje = _a_porcentaje(r.tasa_excedente)
    marca = ' <span class="badge-manual">Corregido a mano</span>' if corregido_a_mano else ""
    return (
        "<tr>"
        f"<td>{r.renglon}</td>"
        f"<td>{escape(str(r.limite_inferior))}</td>"
        f"<td>{escape(limite_superior)}</td>"
        f"<td>{escape(str(r.cuota_fija))}</td>"
        f'<td class="col-principal">{escape(str(porcentaje))} %</td>'
        f"<td>{escape(str(r.tasa_excedente))}</td>"
        f"<td>{marca}</td>"
        "</tr>"
    )


def _tabla_renglones(tarifa: TarifaGuardada) -> str:
    corregida_a_mano = tarifa.origen is OrigenTarifa.MANUAL
    aviso = (
        '<p class="aviso-manual"><strong>Esta tarifa fue corregida a mano</strong> y ya no es, '
        "por definición, lo que decía el último documento importado (si coincidiera número por "
        "número con el documento, el sistema la habría regresado sola al origen «documento» — "
        "ver el caso 6 de reimportación en <code>app.repositories.tarifa_isr</code>). El sistema "
        "no conserva, renglón por renglón, el valor que traía el documento antes de la "
        "corrección; si el contador necesita compararlos, hace falta también el documento "
        "original citado abajo.</p>"
        if corregida_a_mano
        else ""
    )
    filas = "".join(_renglon_html(r, corregido_a_mano=corregida_a_mano) for r in tarifa.renglones)
    return (
        f"{aviso}"
        "<table class=\"tabla-renglones\"><thead><tr>"
        "<th>Renglón</th><th>Límite inferior</th><th>Límite superior</th><th>Cuota fija</th>"
        '<th class="col-principal">Tasa (%)</th><th>Tasa (fracción)</th><th></th>'
        "</tr></thead><tbody>"
        f"{filas}"
        "</tbody></table>"
    )


def _seccion_procedencia(tarifa: TarifaGuardada) -> str:
    huella_documento = (
        escape(tarifa.documento_sha256)
        if tarifa.documento_sha256
        else "— (corrección manual: no proviene de un documento)"
    )
    return (
        '<div class="procedencia">'
        f"<p><span class=\"etiqueta\">Documento citado:</span> {escape(tarifa.encabezado)}</p>"
        f"<p><span class=\"etiqueta\">Fuente:</span> {escape(tarifa.fuente)}</p>"
        f"<p><span class=\"etiqueta\">Huella SHA-256 del documento:</span> "
        f'<span class="mono">{huella_documento}</span></p>'
        f"<p><span class=\"etiqueta\">Huella de estos renglones:</span> "
        f'<span class="mono">{escape(tarifa.huella)}</span></p>'
        f"<p><span class=\"etiqueta\">Importado el:</span> {_fecha(tarifa.importado_en)}</p>"
        "</div>"
    )


def _seccion_comprobacion(comprobacion: Comprobacion | None) -> str:
    """La comprobación de §7.3, rotulada como lo que es: una comprobación de que la tarifa se
    cargó bien, nunca un dictamen sobre si la tarifa en sí es correcta — eso lo decide el
    contador al leer el resto de la hoja, no este cálculo."""
    from app.api.v1.configuracion import _a_porcentaje

    if comprobacion is None:
        return (
            '<div class="comprobacion">'
            f"<p><strong>{escape(_ROTULO_NO_DICTAMEN)}</strong></p>"
            "<p>No hay una comprobación disponible: no se encontró en la base un recibo de "
            "nómina ordinario, sin cancelar y con gravado positivo para esta periodicidad. Eso "
            "no dice nada sobre si la tarifa está bien o mal cargada.</p>"
            "</div>"
        )
    porcentaje = _a_porcentaje(comprobacion.tasa_excedente)
    advertencias = "".join(f"<li>{escape(a)}</li>" for a in comprobacion.advertencias)
    bloque_advertencias = f"<ul>{advertencias}</ul>" if advertencias else "<p>Sin advertencias.</p>"
    dias = str(comprobacion.dias_pagados) if comprobacion.dias_pagados is not None else "—"
    empleado = escape(comprobacion.num_empleado) if comprobacion.num_empleado else "—"
    # `str(None)` es `"None"`, no una cadena vacía: un `or "—"` sobre el resultado de `str(...)`
    # nunca dispararía, así que el `None` se comprueba antes de convertir a texto, no después.
    fecha_inicial = str(comprobacion.fecha_inicial_pago) if comprobacion.fecha_inicial_pago is not None else "—"
    fecha_final = str(comprobacion.fecha_final_pago) if comprobacion.fecha_final_pago is not None else "—"
    return (
        '<div class="comprobacion">'
        f"<p><strong>{escape(_ROTULO_NO_DICTAMEN)}</strong></p>"
        "<table class=\"tabla-comprobacion\"><tbody>"
        f"<tr><td>UUID del recibo</td><td class=\"mono\">{escape(comprobacion.uuid)}</td></tr>"
        f"<tr><td>Periodo</td><td>{escape(fecha_inicial)} — "
        f"{escape(fecha_final)} ({escape(dias)} días pagados)</td></tr>"
        f"<tr><td>Empleado</td><td>{empleado}</td></tr>"
        f"<tr><td>Gravado</td><td>{escape(str(comprobacion.gravado))}</td></tr>"
        f"<tr><td>Renglón aplicado</td><td>{comprobacion.renglon} (límite inferior "
        f"{escape(str(comprobacion.limite_inferior))}, tasa {escape(str(porcentaje))} % / "
        f"{escape(str(comprobacion.tasa_excedente))})</td></tr>"
        f"<tr><td>ISR calculado con esta tarifa</td><td>{escape(str(comprobacion.isr_calculado))}</td></tr>"
        f"<tr><td>ISR timbrado en el recibo</td><td>{escape(str(comprobacion.isr_timbrado))}</td></tr>"
        f"<tr><td>Diferencia</td><td>{escape(str(comprobacion.diferencia))}</td></tr>"
        "</tbody></table>"
        f"{bloque_advertencias}"
        "</div>"
    )


def _pie_confirmacion(tarifa: TarifaGuardada) -> str:
    if not tarifa.confirmada:
        return (
            '<p class="pie-confirmacion"><strong>Falta confirmar esta tarifa.</strong> '
            "Mientras no se confirme, ningún cálculo la usa.</p>"
        )
    confirmado_por = escape(tarifa.confirmado_por) if tarifa.confirmado_por else "—"
    return (
        '<p class="pie-confirmacion">Confirmada por '
        f"<strong>{confirmado_por}</strong> el {_fecha(tarifa.confirmado_en)}. A partir de esa "
        "fecha, los cálculos de nómina que corresponden a esta periodicidad usan esta tarifa.</p>"
    )


def hoja_html(tarifa: TarifaGuardada, comprobacion: Comprobacion | None) -> str:
    """El HTML completo de la hoja de revisión, en el orden que fija el brief de la Task 11:
    título con la etiqueta legible y el ejercicio; procedencia (fuente, huella SHA-256, fecha de
    importación); la tabla de renglones con el porcentaje como columna principal y los
    renglones corregidos a mano marcados; la comprobación rotulada como comprobación de carga
    (no dictamen); y al pie qué falta o quién confirmó y cuándo.

    **Import diferido de `app.api.v1.configuracion`** (`_ETIQUETAS_TARIFA`, `_a_porcentaje`): ese
    módulo importa este (`from app.services import revision_tarifa`, para exponer el endpoint) al
    nivel de módulo, así que un `import` de este módulo a nivel de módulo hacia `configuracion`
    cerraría un ciclo. Aquí basta con la etiqueta legible y la conversión a porcentaje, y las dos
    solo hacen falta cuando de verdad se genera la hoja — importarlas en el cuerpo de la función,
    no arriba del archivo, evita el ciclo sin duplicar ninguna de las dos.
    """
    from app.api.v1.configuracion import _ETIQUETAS_TARIFA

    etiqueta = _ETIQUETAS_TARIFA[tarifa.periodicidad]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
        @page {{ size: letter portrait; margin: 40px 36px; }}
        body {{ margin: 0; font-family: Arial, "Liberation Sans", Helvetica, sans-serif; color: #000; font-size: 11px; }}
        h1 {{ font-size: 20px; font-weight: 700; margin: 0 0 4px; color: #1E2733; }}
        h2 {{ font-size: 13px; font-weight: 700; margin: 18px 0 6px; color: #1E2733; border-bottom: 1px solid #ccc; padding-bottom: 2px; }}
        .subtitulo {{ color: #556070; margin: 0 0 16px; }}
        .etiqueta {{ font-weight: bold; }}
        .mono {{ font-family: "Liberation Mono", monospace; font-size: 10px; word-break: break-all; }}
        .procedencia p {{ margin: 2px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 4px; }}
        th, td {{ border: 1px solid #999; padding: 4px 6px; text-align: right; font-size: 10.5px; }}
        th:first-child, td:first-child {{ text-align: center; }}
        .tabla-comprobacion td:first-child {{ text-align: left; font-weight: bold; width: 220px; }}
        .tabla-comprobacion td {{ text-align: left; }}
        .col-principal {{ background: #EAF1FA; font-weight: bold; }}
        .badge-manual {{ display: inline-block; background: #9A5B00; color: #fff; font-size: 9px; padding: 1px 5px; border-radius: 3px; }}
        .aviso-manual {{ background: #FFF4E5; border: 1px solid #9A5B00; padding: 6px 8px; margin: 6px 0; }}
        .comprobacion {{ margin-top: 6px; }}
        .pie-confirmacion {{ margin-top: 20px; padding-top: 8px; border-top: 1px solid #999; }}
    </style></head><body>
        <h1>Hoja de revisión — Tarifa del ISR</h1>
        <p class="subtitulo">{escape(etiqueta)} · Ejercicio {tarifa.ejercicio}</p>
        <h2>Procedencia</h2>
        {_seccion_procedencia(tarifa)}
        <h2>Tarifa</h2>
        {_tabla_renglones(tarifa)}
        <h2>Comprobación contra un recibo real</h2>
        {_seccion_comprobacion(comprobacion)}
        {_pie_confirmacion(tarifa)}
    </body></html>"""


def hoja_pdf(tarifa: TarifaGuardada, comprobacion: Comprobacion | None) -> bytes:
    """El mismo contenido de `hoja_html`, en PDF — generado en el servidor con `weasyprint`
    (mismo motor que `app.services.representaciones`), no con la impresión del navegador, porque
    el archivo se adjunta a un correo tal cual."""
    from weasyprint import HTML

    resultado: bytes = HTML(string=hoja_html(tarifa, comprobacion)).write_pdf()
    return resultado
