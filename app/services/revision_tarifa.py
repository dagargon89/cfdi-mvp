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


def _renglon_html(r: reglas.Renglon) -> str:
    """Una fila de la tabla de renglones. El **porcentaje es la columna principal** —como lo
    publica el SAT y como lo lee un contador—, con la fracción cruda al lado como dato
    secundario, nunca al revés.

    **Sin distintivo por renglón.** Antes esta fila marcaba "Corregido a mano" en las filas de
    una tarifa de origen `MANUAL`, pero `_escribir` (Task 4) reemplaza los renglones **completos**
    en cada corrección — no hay forma de saber, con lo que `TarifaGuardada` guarda hoy, cuál
    renglón cambió de valor y cuál no. Marcarlos todos era una afirmación falsa ("se tocaron los
    cinco") cuando puede que solo uno haya cambiado, en un documento cuyo propósito es que
    alguien confíe en él sin entrar al sistema. El aviso de corrección manual va una sola vez, a
    nivel de tarifa, en `_tabla_renglones` — ver esa función para la divergencia declarada.
    """
    limite_superior = str(r.limite_superior) if r.limite_superior is not None else "En adelante"
    porcentaje = reglas.a_porcentaje(r.tasa_excedente)
    return (
        "<tr>"
        f"<td>{r.renglon}</td>"
        f"<td>{escape(str(r.limite_inferior))}</td>"
        f"<td>{escape(limite_superior)}</td>"
        f"<td>{escape(str(r.cuota_fija))}</td>"
        f'<td class="col-principal">{escape(str(porcentaje))} %</td>'
        f"<td>{escape(str(r.tasa_excedente))}</td>"
        "</tr>"
    )


def _tabla_renglones(tarifa: TarifaGuardada) -> str:
    """La tabla de renglones, con un aviso **a nivel de tarifa** —no por renglón— cuando el
    origen es `MANUAL`.

    **Divergencia declarada del §7.4 del diseño.** El diseño pedía los renglones corregidos
    marcados "con lo que decía el documento al lado". Eso no se entrega: `TarifaGuardada` (Task 4,
    interfaz congelada que esta tarea no puede tocar) no conserva el valor anterior renglón por
    renglón, solo el conjunto vigente y el `origen`. El dato sí existe — la bitácora de
    `corregir_tarifa_isr` guarda el `anterior`/`nuevo` completo de cada corrección (ver
    `app/api/v1/configuracion.py`, acción `corregir_tarifa_isr`) — pero mostrarlo aquí exigiría
    una consulta nueva a `Bitacora`, extender la firma de `hoja_html` (hoy fijada a
    `(tarifa, comprobacion)`, sin acceso a la sesión) y sus pruebas; queda fuera de esta tarea a
    propósito, para decidirse aparte.

    Mientras tanto, marcar cada renglón como "corregido a mano" sería peor que no marcar nada:
    una corrección reemplaza los renglones **completos** aunque solo uno haya cambiado de valor,
    así que un distintivo por renglón afirmaría que los cinco cambiaron cuando pudo haber sido
    uno solo — información falsa en un documento cuyo propósito es que el contador confíe en él
    sin entrar al sistema.

    **El aviso a nivel de tarifa tiene el mismo límite y hay que redactarlo con el mismo
    cuidado.** Guardar el modal de corrección sin tocar ningún valor también deja `origen:
    MANUAL` (comportamiento correcto: guardar es una afirmación, y limpia la confirmación
    anterior), así que "hubo una edición manual" no implica "algún renglón cambió de valor" — lo
    único que el sistema sabe de verdad es que alguien abrió el modal y guardó, no qué guardó.
    Un aviso que afirmara "uno o más renglones ya no son los del documento" sería falso en ese
    caso, y esta hoja existe justo para que el contador confíe en lo que dice sin poder mirar el
    sistema por dentro — una afirmación falsa aquí es peor que no decir nada. Por eso el texto
    solo afirma el hecho conocido (que se editó a mano) y deja la posibilidad —no la certeza— de
    que algo difiera, con la instrucción de qué hacer al respecto.
    """
    aviso = (
        '<p class="aviso-manual"><strong>Origen: editado a mano.</strong> Esta tarifa se editó '
        "a mano después de importarla. El sistema no guarda qué se cambió, así que puede que "
        "algún renglón ya no coincida con el documento citado arriba: compara la tabla completa "
        "contra el Anexo 8 antes de validarla.</p>"
        if tarifa.origen is OrigenTarifa.MANUAL
        else ""
    )
    filas = "".join(_renglon_html(r) for r in tarifa.renglones)
    return (
        f"{aviso}"
        "<table class=\"tabla-renglones\"><thead><tr>"
        "<th>Renglón</th><th>Límite inferior</th><th>Límite superior</th><th>Cuota fija</th>"
        '<th class="col-principal">Tasa (%)</th><th>Tasa (fracción)</th>'
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
    if comprobacion is None:
        return (
            '<div class="comprobacion">'
            f"<p><strong>{escape(_ROTULO_NO_DICTAMEN)}</strong></p>"
            "<p>No hay una comprobación disponible: no se encontró en la base un recibo de "
            "nómina ordinario, sin cancelar y con gravado positivo para esta periodicidad. Eso "
            "no dice nada sobre si la tarifa está bien o mal cargada.</p>"
            "</div>"
        )
    porcentaje = reglas.a_porcentaje(comprobacion.tasa_excedente)
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
    importación); la tabla de renglones con el porcentaje como columna principal y, si aplica,
    un aviso de corrección manual a nivel de tarifa (ver `_tabla_renglones` para por qué no es
    por renglón); la comprobación rotulada como comprobación de carga (no dictamen); y al pie qué
    falta o quién confirmó y cuándo.
    """
    etiqueta = reglas.ETIQUETAS_TARIFA[tarifa.periodicidad]
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
