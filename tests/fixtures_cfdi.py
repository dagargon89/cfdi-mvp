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


def cfdi_nomina(
    *,
    uuid: str = "77777777-7777-7777-7777-777777777777",
    fecha: str = "2026-07-01T09:30:00",
    fecha_pago: str = "2026-06-30",
    fecha_inicial: str = "2026-06-16",
    fecha_final: str = "2026-06-30",
    dias_pagados: str = "15.000",
    tipo_nomina: str = "O",
    total_percepciones: str = "9259.70",
    total_deducciones: str = "1091.10",
    total_otros_pagos: str = "0.00",
    subtotal: str = "9259.70",
    descuento: str = "1091.10",
    total: str = "8168.60",
    percepciones_xml: str | None = None,
    deducciones_xml: str | None = None,
    otros_pagos_xml: str | None = None,
    incapacidades_xml: str = "",
    total_gravado: str = "8759.70",
    total_exento: str = "500.00",
) -> bytes:
    """CFDI 4.0 tipo N con complemento de Nómina 1.2. Todos los datos personales son
    inventados: la CURP y el NSS no corresponden a ninguna persona real."""
    percepciones_default = (
        '<nomina12:Percepcion TipoPercepcion="001" Clave="001" Concepto="Sueldo" '
        'ImporteGravado="8759.70" ImporteExento="0.00" />'
        '<nomina12:Percepcion TipoPercepcion="005" Clave="031" Concepto="Fondo ahorro empresa" '
        'ImporteGravado="0.00" ImporteExento="500.00" />'
    )
    deducciones_default = (
        '<nomina12:Deduccion TipoDeduccion="001" Clave="052" Concepto="I.M.S.S." Importe="200.00" />'
        '<nomina12:Deduccion TipoDeduccion="002" Clave="045" Concepto="I.S.R. mes" Importe="391.10" />'
        '<nomina12:Deduccion TipoDeduccion="004" Clave="067" Concepto="Fondo de ahorro Empresa" Importe="500.00" />'
    )
    otros_default = (
        '<nomina12:OtroPago TipoOtroPago="002" Clave="035" Concepto="Subs al Empleo mes" Importe="0.00">'
        '<nomina12:SubsidioAlEmpleo SubsidioCausado="0.00" /></nomina12:OtroPago>'
    )
    percepciones_nodo = (
        f'<nomina12:Percepciones TotalSueldos="{total_gravado}" TotalGravado="{total_gravado}" '
        f'TotalExento="{total_exento}">{percepciones_xml or percepciones_default}</nomina12:Percepciones>'
    )
    deducciones_nodo = (
        '<nomina12:Deducciones TotalOtrasDeducciones="700.00" TotalImpuestosRetenidos="391.10">'
        f"{deducciones_xml or deducciones_default}</nomina12:Deducciones>"
    )
    otros_nodo = f"<nomina12:OtrosPagos>{otros_pagos_xml or otros_default}</nomina12:OtrosPagos>"
    complemento_nomina = (
        '<nomina12:Nomina xmlns:nomina12="http://www.sat.gob.mx/nomina12" Version="1.2" '
        f'TipoNomina="{tipo_nomina}" FechaPago="{fecha_pago}" FechaInicialPago="{fecha_inicial}" '
        f'FechaFinalPago="{fecha_final}" NumDiasPagados="{dias_pagados}" '
        f'TotalPercepciones="{total_percepciones}" TotalDeducciones="{total_deducciones}" '
        f'TotalOtrosPagos="{total_otros_pagos}">'
        '<nomina12:Emisor RegistroPatronal="B5510768108" />'
        '<nomina12:Receptor Curp="XXXX800101HCHXXX01" NumSeguridadSocial="12345678901" '
        'FechaInicioRelLaboral="2013-09-01" Antigüedad="P663W" TipoContrato="01" '
        'Sindicalizado="No" TipoJornada="01" TipoRegimen="02" NumEmpleado="039" '
        'Departamento="Direccion" Puesto="Director" RiesgoPuesto="1" PeriodicidadPago="04" '
        'Banco="002" CuentaBancaria="1234567890" SalarioBaseCotApor="583.98" '
        'SalarioDiarioIntegrado="607.34" ClaveEntFed="CHH" />'
        f"{percepciones_nodo}{deducciones_nodo}{otros_nodo}{incapacidades_xml}"
        "</nomina12:Nomina>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0" '
        f'Serie="N" Folio="12" Fecha="{fecha}" MetodoPago="PUE" Moneda="MXN" '
        f'SubTotal="{subtotal}" Descuento="{descuento}" Total="{total}" '
        'TipoDeComprobante="N" Exportacion="01" LugarExpedicion="31000" '
        'NoCertificado="00001000000504465028" Certificado="Y2VydA==" Sello="c2VsbG8=">'
        '<cfdi:Emisor Rfc="CHL960913IX9" Nombre="CENTRO HUMANO DE LIDERAZGO" RegimenFiscal="601" />'
        '<cfdi:Receptor Rfc="XAXX010101000" Nombre="EMPLEADO DE PRUEBA" '
        'DomicilioFiscalReceptor="31000" RegimenFiscalReceptor="605" UsoCFDI="CN01" />'
        "<cfdi:Conceptos>"
        '<cfdi:Concepto ClaveProdServ="84111505" Cantidad="1" ClaveUnidad="ACT" '
        f'Descripcion="Pago de nomina" ValorUnitario="{subtotal}" Importe="{subtotal}" '
        f'Descuento="{descuento}" ObjetoImp="01" />'
        "</cfdi:Conceptos>"
        '<cfdi:Complemento>'
        f"{complemento_nomina}"
        '<tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" '
        f'Version="1.1" UUID="{uuid}" FechaTimbrado="{fecha}" RfcProvCertif="AAA010101AAA" '
        'SelloCFD="c2VsbG8=" NoCertificadoSAT="00001000000504465028" SelloSAT="c2VsbG8=" />'
        "</cfdi:Complemento>"
        "</cfdi:Comprobante>"
    ).encode()
