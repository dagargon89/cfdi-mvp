"""Representaciones descargables de un CFDI — PDF (RF-RES-03/D2) y "Detalle del CFDI"
(constancia de validación tipo la del portal del SAT), además del XML ya cubierto por
`app/services/resguardo.py`.

Todo se genera al vuelo a partir del XML ya guardado (`comprobante.xml_path`) — nada se
pre-genera ni se cachea en disco: el "Detalle" en particular depende del `estatus` más
reciente (RF-VAL), así que generarlo de nuevo cada vez es lo correcto, no un desperdicio.
"""

from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime
from html import escape
from typing import Any

from app.models.comprobante import Comprobante
from app.models.enums import EstatusCfdi

_EFECTO_TEXTO = {
    "I": "Ingreso",
    "E": "Egreso",
    "T": "Traslado",
    "N": "Nómina",
    "P": "Pago",
}

_ESTATUS_TEXTO = {
    EstatusCfdi.VIGENTE: "Vigente",
    EstatusCfdi.CANCELADO: "Cancelado",
    EstatusCfdi.NO_VERIFICADO: "No verificado",
}


def leer_xml_de_disco(storage_root: str, comprobante: Comprobante) -> bytes | None:
    """`None` si el comprobante no tiene XML guardado o el archivo ya no existe en disco —
    el caller decide si eso es un 404 (endpoint individual) o un fallo tolerado (lote)."""
    if not comprobante.xml_path:
        return None
    ruta = os.path.join(storage_root, comprobante.xml_path)
    if not os.path.isfile(ruta):
        return None
    with open(ruta, "rb") as f:
        return f.read()


def generar_pdf(xml_bytes: bytes) -> bytes:
    """Representación impresa completa (conceptos, impuestos, timbre fiscal, QR) — motor
    ya incluido en `satcfdi` (`satcfdi.render`, sobre `weasyprint`, sin red)."""
    from satcfdi.cfdi import CFDI
    from satcfdi.render import pdf_bytes

    resultado: bytes = pdf_bytes(CFDI.from_string(xml_bytes))
    return resultado


def _moneda_fmt(valor: Any) -> str:
    if valor is None:
        return ""
    return f"${float(valor):,.2f}"


def _texto_o_guion(valor: Any) -> str:
    return str(valor) if valor is not None else "—"


def generar_detalle(xml_bytes: bytes, estatus: EstatusCfdi) -> bytes:
    """Constancia compacta de validación ("Detalle del CFDI") — formato propio (no lo
    genera `satcfdi`), inspirado en la vista de validación del SAT. `estatus` viene de la
    BD (RF-VAL), no del XML: el XML nunca sabe si fue cancelado después de emitirse."""
    from satcfdi.cfdi import CFDI
    from weasyprint import HTML

    c = CFDI.from_string(xml_bytes)
    tfd = c["Complemento"]["TimbreFiscalDigital"]
    impuestos = c.get("Impuestos") or {}
    tipo = c.get("TipoDeComprobante")
    tipo_code = getattr(tipo, "code", None) or str(tipo)
    fecha = c.get("Fecha")
    fecha_txt = fecha.isoformat() if isinstance(fecha, datetime) else _texto_o_guion(fecha)
    timbrado = tfd.get("FechaTimbrado")
    timbrado_txt = timbrado.isoformat() if isinstance(timbrado, datetime) else _texto_o_guion(timbrado)
    # El acuse del SAT muestra solo la clave ("MXN"), no la descripción del catálogo.
    moneda = c.get("Moneda")
    moneda_txt = getattr(moneda, "code", None) or _texto_o_guion(moneda)

    campos = [
        ("Folio Fiscal", str(tfd["UUID"]).upper()),
        ("Fecha y Hora de Expedición", fecha_txt),
        ("Fecha y Hora de Certificación", timbrado_txt),
        ("Nombre o Razón Social del Receptor", _texto_o_guion(c["Receptor"].get("Nombre"))),
        ("RFC del Receptor", str(c["Receptor"]["Rfc"])),
        ("Estado del Comprobante", _ESTATUS_TEXTO.get(estatus, estatus.value)),
        ("Efecto del Comprobante", _EFECTO_TEXTO.get(tipo_code, tipo_code)),
        ("Moneda", moneda_txt),
        ("Monto Total", _moneda_fmt(c.get("Total"))),
        ("Total Impuestos Trasladados", _moneda_fmt(impuestos.get("TotalImpuestosTrasladados"))),
        ("Total Impuestos Retenidos", _moneda_fmt(impuestos.get("TotalImpuestosRetenidos"))),
    ]

    def campo(indice: int) -> str:
        etiqueta, valor = campos[indice]
        return f'<span class="etiqueta">{escape(etiqueta)}:</span> {escape(str(valor))}'

    def fila(izq: int, der: int, ancho: int) -> str:
        return (
            f'<div class="fila"><span class="celda" style="width:{ancho}px">{campo(izq)}</span>'
            f'<span class="celda celda-der">{campo(der)}</span></div>'
        )

    # Réplica del acuse "Detalle del CFDI" del portal de verificación del SAT, hoja horizontal:
    # Folio Fiscal a todo el ancho y después pares en dos columnas. En el documento original la
    # segunda columna NO arranca en el mismo punto en todas las filas: fechas/receptor la tienen
    # más a la derecha (412px) que estado/moneda/impuestos (308px) — se replica tal cual.
    cuerpo = (
        f'<div class="fila">{campo(0)}</div>'
        + fila(1, 2, 412)
        + fila(3, 4, 412)
        + fila(5, 6, 308)
        + fila(7, 8, 308)
        + fila(9, 10, 308)
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
        @page {{ size: letter landscape; margin: 0; }}
        body {{ margin: 0; padding: 66px 60px 0 57px; font-family: Arial, "Liberation Sans", Helvetica, sans-serif; color: #000; }}
        h1 {{ font-size: 32px; font-weight: 400; margin: 0 0 27px; color: #3b3b3b; letter-spacing: -0.5px; }}
        .fila {{ margin: 0 0 40px 10px; font-size: 13px; line-height: 1.25; }}
        .celda {{ display: inline-block; vertical-align: top; padding-right: 24px; box-sizing: border-box; }}
        .celda-der {{ width: 400px; }}
        .etiqueta {{ font-weight: bold; }}
    </style></head><body>
        <h1>Detalle del CFDI</h1>
        {cuerpo}
    </body></html>"""
    pdf_bytes_result: bytes = HTML(string=html).write_pdf()
    return pdf_bytes_result


def generar_paquete_zip(comprobante: Comprobante, xml_bytes: bytes) -> bytes:
    """`.zip` en memoria con XML + PDF + Detalle de un solo comprobante."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{comprobante.uuid}.xml", xml_bytes)
        zf.writestr(f"{comprobante.uuid}.pdf", generar_pdf(xml_bytes))
        zf.writestr(f"{comprobante.uuid}_detalle.pdf", generar_detalle(xml_bytes, comprobante.estatus))
    return buffer.getvalue()
