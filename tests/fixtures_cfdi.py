"""Constructores de XML de CFDI sintéticos para las pruebas del ETL.

**Ningún XML real entra a git**: los de la empresa 11 contienen CURP, NSS y cuentas
bancarias de personas reales (spec §13). Todo lo de aquí es inventado.

Los XML no llevan sello ni certificado válidos: `satcfdi.CFDI.from_string` parsea sin
validar la firma, que es exactamente lo que el ETL necesita.
"""

from __future__ import annotations

_TIMBRE = (
    '<complemento><tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" '
    'Version="1.1" UUID="{uuid}" FechaTimbrado="{timbrado}" RfcProvCertif="AAA010101AAA" '
    'SelloCFD="c2VsbG8=" NoCertificadoSAT="00001000000504465028" SelloSAT="c2VsbG8=" /></complemento>'
)


def cfdi_ingreso(
    *,
    uuid: str = "11111111-1111-1111-1111-111111111111",
    fecha: str = "2026-07-01T10:00:00",
    timbrado: str = "2026-07-01T10:05:00",
    serie: str = "A",
    folio: str = "1582",
    moneda: str = "MXN",
    tipo_cambio: str = "1",
    subtotal: str = "7000.00",
    descuento: str | None = None,
    total: str = "7560.00",
    conceptos_xml: str | None = None,
    relacionados_xml: str = "",
) -> bytes:
    """CFDI 4.0 de ingreso con un concepto y un traslado de IVA al 8 %."""
    concepto_default = (
        '<cfdi:Concepto ClaveProdServ="84111506" Cantidad="1" ClaveUnidad="E48" '
        'Descripcion="Servicios de facturacion" ValorUnitario="7000.00" Importe="7000.00" ObjetoImp="02">'
        "<cfdi:Impuestos><cfdi:Traslados>"
        '<cfdi:Traslado Base="7000.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.080000" Importe="560.00" />'
        "</cfdi:Traslados></cfdi:Impuestos></cfdi:Concepto>"
    )
    atributo_descuento = f' Descuento="{descuento}"' if descuento is not None else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0" '
        f'Serie="{serie}" Folio="{folio}" Fecha="{fecha}" FormaPago="03" MetodoPago="PUE" '
        f'Moneda="{moneda}" TipoCambio="{tipo_cambio}" SubTotal="{subtotal}"{atributo_descuento} Total="{total}" '
        'TipoDeComprobante="I" Exportacion="01" LugarExpedicion="31000" '
        'NoCertificado="00001000000504465028" Certificado="Y2VydA==" Sello="c2VsbG8=">'
        f"{relacionados_xml}"
        '<cfdi:Emisor Rfc="CHL960913IX9" Nombre="CENTRO HUMANO DE LIDERAZGO" RegimenFiscal="601" />'
        '<cfdi:Receptor Rfc="XAXX010101000" Nombre="PUBLICO EN GENERAL" '
        'DomicilioFiscalReceptor="31000" RegimenFiscalReceptor="616" UsoCFDI="G03" />'
        f"<cfdi:Conceptos>{conceptos_xml or concepto_default}</cfdi:Conceptos>"
        + _TIMBRE.format(uuid=uuid, timbrado=timbrado).replace("complemento", "cfdi:Complemento")
        + "</cfdi:Comprobante>"
    ).encode()


def relacionados(tipo_relacion: str, *uuids: str) -> str:
    """Bloque `CfdiRelacionados`. En 4.0 puede haber varios con distinto `TipoRelacion`."""
    hijos = "".join(f'<cfdi:CfdiRelacionado UUID="{u}" />' for u in uuids)
    return f'<cfdi:CfdiRelacionados TipoRelacion="{tipo_relacion}">{hijos}</cfdi:CfdiRelacionados>'
