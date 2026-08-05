"""ETL: XML de CFDI → dataclasses (spec §6.1).

Servicio **puro**: sin BD, sin sesión, sin I/O de disco. Recibe los bytes del XML y
devuelve el árbol de datos que el escritor (`app/repositories/normalizacion.py`)
persiste. Es el único módulo que conoce `satcfdi`.

Tres detalles que `satcfdi` resuelve y de los que este módulo depende:

- Los importes ya vienen como `Decimal`. **No se convierten a float** (regla R-T4).
- Las claves de catálogo vienen como objetos `Code` con `.code` y `.description`; se
  guarda la clave textual (`_clave`).
- Los nodos con cardinalidad variable llegan a veces como lista y a veces como mapa con
  un hijo nombrado (`Percepciones.Percepcion` es mapa+lista, `OtrosPagos` es lista
  directa). `_lista` normaliza ambas formas.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

ETL_VERSION = 1
"""Subir este número fuerza el reproceso de todo el histórico (spec §6.2)."""

_CERO = Decimal("0")


# --------------------------------------------------------------------------- #
# Dataclasses de salida
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class DatosImpuesto:
    naturaleza: str  # 'T' traslado | 'R' retención
    impuesto: str
    tipo_factor: str | None
    tasa_o_cuota: Decimal | None
    base: Decimal | None
    importe: Decimal | None


@dataclass(slots=True)
class DatosConcepto:
    num_linea: int
    clave_prod_serv: str | None
    no_identificacion: str | None
    cantidad: Decimal | None
    clave_unidad: str | None
    unidad: str | None
    descripcion: str | None
    valor_unitario: Decimal | None
    importe: Decimal | None
    descuento: Decimal
    objeto_imp: str | None
    impuestos: list[DatosImpuesto] = field(default_factory=list)


@dataclass(slots=True)
class DatosRelacionado:
    tipo_relacion: str
    uuid_relacionado: str


@dataclass(slots=True)
class DatosEncabezado:
    version: str | None
    serie: str | None
    fecha_timbrado: datetime | None
    forma_pago: str | None
    metodo_pago: str | None
    moneda: str | None
    tipo_cambio: Decimal | None
    subtotal: Decimal | None
    descuento: Decimal
    lugar_expedicion: str | None
    exportacion: str | None
    regimen_emisor: str | None
    nombre_receptor: str | None
    domicilio_receptor: str | None
    regimen_receptor: str | None
    uso_cfdi: str | None
    no_certificado: str | None
    no_certificado_sat: str | None


@dataclass(slots=True)
class DatosNominaCabecera:
    version_nomina: str | None
    tipo_nomina: str | None
    fecha_pago: date | None
    fecha_inicial_pago: date | None
    fecha_final_pago: date | None
    num_dias_pagados: Decimal | None
    total_percepciones: Decimal | None
    total_deducciones: Decimal | None
    total_otros_pagos: Decimal | None
    registro_patronal: str | None
    rfc_patron_origen: str | None
    origen_recurso: str | None
    monto_recurso_propio: Decimal | None


@dataclass(slots=True)
class DatosNominaReceptor:
    curp: str | None
    nss: str | None
    fecha_inicio_rel_laboral: date | None
    antiguedad: str | None
    tipo_contrato: str | None
    sindicalizado: str | None
    tipo_jornada: str | None
    tipo_regimen: str | None
    num_empleado: str | None
    departamento: str | None
    puesto: str | None
    riesgo_puesto: str | None
    periodicidad_pago: str | None
    banco: str | None
    cuenta_bancaria: str | None
    salario_base_cot_apor: Decimal | None
    salario_diario_integrado: Decimal | None
    clave_ent_fed: str | None


@dataclass(slots=True)
class DatosPercepcion:
    tipo_percepcion: str
    clave: str | None
    concepto: str | None
    importe_gravado: Decimal
    importe_exento: Decimal


@dataclass(slots=True)
class DatosDeduccion:
    tipo_deduccion: str
    clave: str | None
    concepto: str | None
    importe: Decimal


@dataclass(slots=True)
class DatosOtroPago:
    tipo_otro_pago: str
    clave: str | None
    concepto: str | None
    importe: Decimal
    subsidio_causado: Decimal | None
    saldo_a_favor: Decimal | None
    anio: int | None
    remanente_sal_fav: Decimal | None


@dataclass(slots=True)
class DatosIncapacidad:
    dias_incapacidad: int | None
    tipo_incapacidad: str | None
    importe_monetario: Decimal | None


@dataclass(slots=True)
class DatosNominaTotales:
    total_sueldos: Decimal | None
    total_separacion_indemnizacion: Decimal | None
    total_jubilacion_pension_retiro: Decimal | None
    total_gravado: Decimal | None
    total_exento: Decimal | None
    total_otras_deducciones: Decimal | None
    total_impuestos_retenidos: Decimal | None


@dataclass(slots=True)
class DatosNomina:
    cabecera: DatosNominaCabecera
    receptor: DatosNominaReceptor
    totales: DatosNominaTotales
    percepciones: list[DatosPercepcion] = field(default_factory=list)
    deducciones: list[DatosDeduccion] = field(default_factory=list)
    otros_pagos: list[DatosOtroPago] = field(default_factory=list)
    incapacidades: list[DatosIncapacidad] = field(default_factory=list)


@dataclass(slots=True)
class DatosPagoDocto:
    id_documento: str
    serie: str | None
    folio: str | None
    moneda_dr: str | None
    equivalencia_dr: Decimal | None
    num_parcialidad: int | None
    imp_saldo_ant: Decimal | None
    imp_pagado: Decimal | None
    imp_saldo_insoluto: Decimal | None
    objeto_imp_dr: str | None
    impuestos: list[DatosImpuesto] = field(default_factory=list)


@dataclass(slots=True)
class DatosPago:
    num_pago: int
    fecha_pago: datetime | None
    forma_de_pago_p: str | None
    moneda_p: str | None
    tipo_cambio_p: Decimal | None
    monto: Decimal | None
    num_operacion: str | None
    rfc_emisor_cta_ord: str | None
    rfc_emisor_cta_ben: str | None
    cta_ordenante: str | None
    cta_beneficiario: str | None
    doctos: list[DatosPagoDocto] = field(default_factory=list)


@dataclass(slots=True)
class DatosPagoTotales:
    total_traslados_base_iva16: Decimal | None
    total_traslados_impuesto_iva16: Decimal | None
    total_traslados_base_iva8: Decimal | None
    total_traslados_impuesto_iva8: Decimal | None
    total_traslados_base_iva0: Decimal | None
    total_traslados_impuesto_iva0: Decimal | None
    total_traslados_base_iva_exento: Decimal | None
    total_retenciones_iva: Decimal | None
    total_retenciones_isr: Decimal | None
    total_retenciones_ieps: Decimal | None
    monto_total_pagos: Decimal | None


@dataclass(slots=True)
class DatosComprobante:
    encabezado: DatosEncabezado
    conceptos: list[DatosConcepto] = field(default_factory=list)
    relacionados: list[DatosRelacionado] = field(default_factory=list)
    nomina: DatosNomina | None = None
    pagos: list[DatosPago] = field(default_factory=list)
    pago_totales: DatosPagoTotales | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def hash_xml(xml_bytes: bytes) -> str:
    """SHA-256 hexadecimal del XML original — base de la idempotencia (spec §6.2)."""
    return hashlib.sha256(xml_bytes).hexdigest()


def _clave(valor: Any) -> str | None:
    """Clave textual de un catálogo. `satcfdi` devuelve `Code('002', 'IVA')`; interesa
    `'002'`. Nunca se convierte a entero: destruiría los ceros a la izquierda."""
    if valor is None:
        return None
    codigo = getattr(valor, "code", None)
    return str(codigo) if codigo is not None else str(valor)


def _lista(nodo: Any, clave_hijo: str) -> list[Any]:
    """Normaliza las dos formas en que `satcfdi` entrega colecciones: lista directa
    (`OtrosPagos`) o mapa con un hijo nombrado (`Percepciones` → `Percepcion`)."""
    if nodo is None:
        return []
    if isinstance(nodo, list):
        return nodo
    hijo = nodo.get(clave_hijo)
    if hijo is None:
        return []
    return hijo if isinstance(hijo, list) else [hijo]


def _decimal(valor: Any) -> Decimal | None:
    if valor is None:
        return None
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def _decimal_o_cero(valor: Any) -> Decimal:
    """Campos que el estándar declara opcionales pero que valen cero cuando faltan
    (`Descuento` a nivel comprobante y a nivel concepto, §2.1 y §2.2 del fuente)."""
    convertido = _decimal(valor)
    return _CERO if convertido is None else convertido


def _fecha_hora(valor: Any) -> datetime | None:
    return valor if isinstance(valor, datetime) else None


def _fecha(valor: Any) -> date | None:
    """`FechaPago` de nómina llega como `date`; un `datetime` se recorta a su fecha."""
    if isinstance(valor, datetime):
        return valor.date()
    return valor if isinstance(valor, date) else None


# --------------------------------------------------------------------------- #
# Parseo
# --------------------------------------------------------------------------- #


def _impuestos_de_concepto(concepto: Any) -> list[DatosImpuesto]:
    impuestos_nodo = concepto.get("Impuestos") or {}
    resultado: list[DatosImpuesto] = []
    for naturaleza, llave in (("T", "Traslados"), ("R", "Retenciones")):
        agrupados = impuestos_nodo.get(llave) or {}
        # `Traslados`/`Retenciones` es un mapa con llave compuesta '002|Tasa|0.160000'.
        valores = agrupados.values() if hasattr(agrupados, "values") else agrupados
        for nodo in valores:
            resultado.append(
                DatosImpuesto(
                    naturaleza=naturaleza,
                    impuesto=_clave(nodo.get("Impuesto")) or "",
                    tipo_factor=_clave(nodo.get("TipoFactor")),
                    tasa_o_cuota=_decimal(nodo.get("TasaOCuota")),
                    base=_decimal(nodo.get("Base")),
                    importe=_decimal(nodo.get("Importe")),
                )
            )
    return resultado


def _impuestos_de_docto(docto: Any) -> list[DatosImpuesto]:
    """Los atributos del complemento de pagos llevan sufijo `DR`: `BaseDR`, `ImpuestoDR`,
    `TasaOCuotaDR`, `ImporteDR` — no son los mismos nombres que a nivel concepto."""
    impuestos_nodo = docto.get("ImpuestosDR") or {}
    resultado: list[DatosImpuesto] = []
    for naturaleza, llave in (("T", "TrasladosDR"), ("R", "RetencionesDR")):
        agrupados = impuestos_nodo.get(llave) or {}
        valores = agrupados.values() if hasattr(agrupados, "values") else agrupados
        for nodo in valores:
            resultado.append(
                DatosImpuesto(
                    naturaleza=naturaleza,
                    impuesto=_clave(nodo.get("ImpuestoDR")) or "",
                    tipo_factor=_clave(nodo.get("TipoFactorDR")),
                    tasa_o_cuota=_decimal(nodo.get("TasaOCuotaDR")),
                    base=_decimal(nodo.get("BaseDR")),
                    importe=_decimal(nodo.get("ImporteDR")),
                )
            )
    return resultado


def _pagos(nodo: Any) -> tuple[list[DatosPago], DatosPagoTotales | None]:
    """Parsea el complemento de Pagos 2.0. El grano del informe A-05 es una fila por
    documento pagado en cada pago, así que se conserva la jerarquía pago → documento →
    impuestos completa."""
    pagos: list[DatosPago] = []
    for indice, pago_nodo in enumerate(_lista(nodo.get("Pago"), "Pago"), start=1):
        doctos = [
            DatosPagoDocto(
                id_documento=str(d.get("IdDocumento") or "").upper(),
                serie=d.get("Serie"),
                folio=d.get("Folio"),
                moneda_dr=_clave(d.get("MonedaDR")),
                equivalencia_dr=_decimal(d.get("EquivalenciaDR")),
                num_parcialidad=int(d["NumParcialidad"]) if d.get("NumParcialidad") is not None else None,
                imp_saldo_ant=_decimal(d.get("ImpSaldoAnt")),
                imp_pagado=_decimal(d.get("ImpPagado")),
                imp_saldo_insoluto=_decimal(d.get("ImpSaldoInsoluto")),
                objeto_imp_dr=_clave(d.get("ObjetoImpDR")),
                impuestos=_impuestos_de_docto(d),
            )
            for d in _lista(pago_nodo.get("DoctoRelacionado"), "DoctoRelacionado")
        ]
        pagos.append(
            DatosPago(
                num_pago=indice,
                fecha_pago=_fecha_hora(pago_nodo.get("FechaPago")),
                forma_de_pago_p=_clave(pago_nodo.get("FormaDePagoP")),
                moneda_p=_clave(pago_nodo.get("MonedaP")),
                tipo_cambio_p=_decimal(pago_nodo.get("TipoCambioP")),
                monto=_decimal(pago_nodo.get("Monto")),
                num_operacion=pago_nodo.get("NumOperacion"),
                rfc_emisor_cta_ord=pago_nodo.get("RfcEmisorCtaOrd"),
                rfc_emisor_cta_ben=pago_nodo.get("RfcEmisorCtaBen"),
                cta_ordenante=pago_nodo.get("CtaOrdenante"),
                cta_beneficiario=pago_nodo.get("CtaBeneficiario"),
                doctos=doctos,
            )
        )

    totales_nodo = nodo.get("Totales")
    totales = None
    if totales_nodo is not None:
        totales = DatosPagoTotales(
            total_traslados_base_iva16=_decimal(totales_nodo.get("TotalTrasladosBaseIVA16")),
            total_traslados_impuesto_iva16=_decimal(totales_nodo.get("TotalTrasladosImpuestoIVA16")),
            total_traslados_base_iva8=_decimal(totales_nodo.get("TotalTrasladosBaseIVA8")),
            total_traslados_impuesto_iva8=_decimal(totales_nodo.get("TotalTrasladosImpuestoIVA8")),
            total_traslados_base_iva0=_decimal(totales_nodo.get("TotalTrasladosBaseIVA0")),
            total_traslados_impuesto_iva0=_decimal(totales_nodo.get("TotalTrasladosImpuestoIVA0")),
            total_traslados_base_iva_exento=_decimal(totales_nodo.get("TotalTrasladosBaseIVAExento")),
            total_retenciones_iva=_decimal(totales_nodo.get("TotalRetencionesIVA")),
            total_retenciones_isr=_decimal(totales_nodo.get("TotalRetencionesISR")),
            total_retenciones_ieps=_decimal(totales_nodo.get("TotalRetencionesIEPS")),
            monto_total_pagos=_decimal(totales_nodo.get("MontoTotalPagos")),
        )
    return pagos, totales


def _encabezado(c: Any) -> DatosEncabezado:
    tfd = (c.get("Complemento") or {}).get("TimbreFiscalDigital") or {}
    emisor = c.get("Emisor") or {}
    receptor = c.get("Receptor") or {}
    return DatosEncabezado(
        version=_clave(c.get("Version")),
        serie=c.get("Serie"),
        fecha_timbrado=_fecha_hora(tfd.get("FechaTimbrado")),
        forma_pago=_clave(c.get("FormaPago")),
        metodo_pago=_clave(c.get("MetodoPago")),
        moneda=_clave(c.get("Moneda")),
        tipo_cambio=_decimal(c.get("TipoCambio")),
        subtotal=_decimal(c.get("SubTotal")),
        descuento=_decimal_o_cero(c.get("Descuento")),
        lugar_expedicion=_clave(c.get("LugarExpedicion")),
        exportacion=_clave(c.get("Exportacion")),
        regimen_emisor=_clave(emisor.get("RegimenFiscal")),
        nombre_receptor=receptor.get("Nombre"),
        domicilio_receptor=_clave(receptor.get("DomicilioFiscalReceptor")),
        regimen_receptor=_clave(receptor.get("RegimenFiscalReceptor")),
        uso_cfdi=_clave(receptor.get("UsoCFDI")),
        no_certificado=c.get("NoCertificado"),
        no_certificado_sat=tfd.get("NoCertificadoSAT"),
    )


def _conceptos(c: Any) -> list[DatosConcepto]:
    resultado: list[DatosConcepto] = []
    for indice, concepto in enumerate(c.get("Conceptos") or [], start=1):
        resultado.append(
            DatosConcepto(
                num_linea=indice,
                clave_prod_serv=_clave(concepto.get("ClaveProdServ")),
                no_identificacion=concepto.get("NoIdentificacion"),
                cantidad=_decimal(concepto.get("Cantidad")),
                clave_unidad=_clave(concepto.get("ClaveUnidad")),
                unidad=concepto.get("Unidad"),
                descripcion=concepto.get("Descripcion"),
                valor_unitario=_decimal(concepto.get("ValorUnitario")),
                importe=_decimal(concepto.get("Importe")),
                descuento=_decimal_o_cero(concepto.get("Descuento")),
                objeto_imp=_clave(concepto.get("ObjetoImp")),
                impuestos=_impuestos_de_concepto(concepto),
            )
        )
    return resultado


def _relacionados(c: Any) -> list[DatosRelacionado]:
    """`CfdiRelacionados` puede venir como un nodo o como lista de nodos, cada uno con su
    propio `TipoRelacion` (§2.4 del fuente)."""
    nodo = c.get("CfdiRelacionados")
    if nodo is None:
        return []
    grupos = nodo if isinstance(nodo, list) else [nodo]
    resultado: list[DatosRelacionado] = []
    for grupo in grupos:
        tipo = _clave(grupo.get("TipoRelacion")) or ""
        for relacionado in _lista(grupo.get("CfdiRelacionado"), "CfdiRelacionado"):
            uuid_rel = relacionado.get("UUID") if hasattr(relacionado, "get") else relacionado
            if uuid_rel:
                resultado.append(DatosRelacionado(tipo_relacion=tipo, uuid_relacionado=str(uuid_rel).upper()))
    return resultado


def _nomina(nodo: Any) -> DatosNomina:
    """Parsea el complemento de Nómina 1.2 completo (cabecera, receptor, percepciones,
    deducciones, otros pagos, incapacidades y totales). No consolida: si el XML repite
    un `(tipo, clave)` o refleja el mismo concepto en percepción/deducción/otro pago
    (p. ej. el fondo de ahorro), el ETL devuelve cada nodo tal cual — sumar es trabajo
    del informe (B-02), no del ETL."""
    emisor = nodo.get("Emisor") or {}
    entidad = nodo.get("EntidadSNCF") or {}
    receptor_nodo = nodo.get("Receptor") or {}
    percepciones_nodo = nodo.get("Percepciones") or {}
    deducciones_nodo = nodo.get("Deducciones") or {}

    cabecera = DatosNominaCabecera(
        version_nomina=_clave(nodo.get("Version")),
        tipo_nomina=_clave(nodo.get("TipoNomina")),
        fecha_pago=_fecha(nodo.get("FechaPago")),
        fecha_inicial_pago=_fecha(nodo.get("FechaInicialPago")),
        fecha_final_pago=_fecha(nodo.get("FechaFinalPago")),
        num_dias_pagados=_decimal(nodo.get("NumDiasPagados")),
        total_percepciones=_decimal(nodo.get("TotalPercepciones")),
        total_deducciones=_decimal(nodo.get("TotalDeducciones")),
        total_otros_pagos=_decimal(nodo.get("TotalOtrosPagos")),
        registro_patronal=emisor.get("RegistroPatronal"),
        rfc_patron_origen=emisor.get("RfcPatronOrigen"),
        origen_recurso=_clave(entidad.get("OrigenRecurso")),
        monto_recurso_propio=_decimal(entidad.get("MontoRecursoPropio")),
    )

    receptor = DatosNominaReceptor(
        curp=receptor_nodo.get("Curp"),
        nss=receptor_nodo.get("NumSeguridadSocial"),
        fecha_inicio_rel_laboral=_fecha(receptor_nodo.get("FechaInicioRelLaboral")),
        # El nombre del atributo lleva diéresis — no es un error de tipeo (§2.7 del fuente).
        antiguedad=receptor_nodo.get("Antigüedad"),
        tipo_contrato=_clave(receptor_nodo.get("TipoContrato")),
        sindicalizado=_clave(receptor_nodo.get("Sindicalizado")),
        tipo_jornada=_clave(receptor_nodo.get("TipoJornada")),
        tipo_regimen=_clave(receptor_nodo.get("TipoRegimen")),
        num_empleado=receptor_nodo.get("NumEmpleado"),
        departamento=receptor_nodo.get("Departamento"),
        puesto=receptor_nodo.get("Puesto"),
        riesgo_puesto=_clave(receptor_nodo.get("RiesgoPuesto")),
        periodicidad_pago=_clave(receptor_nodo.get("PeriodicidadPago")),
        banco=_clave(receptor_nodo.get("Banco")),
        cuenta_bancaria=receptor_nodo.get("CuentaBancaria"),
        salario_base_cot_apor=_decimal(receptor_nodo.get("SalarioBaseCotApor")),
        salario_diario_integrado=_decimal(receptor_nodo.get("SalarioDiarioIntegrado")),
        clave_ent_fed=_clave(receptor_nodo.get("ClaveEntFed")),
    )

    percepciones = [
        DatosPercepcion(
            tipo_percepcion=_clave(p.get("TipoPercepcion")) or "",
            clave=p.get("Clave"),
            concepto=p.get("Concepto"),
            importe_gravado=_decimal_o_cero(p.get("ImporteGravado")),
            importe_exento=_decimal_o_cero(p.get("ImporteExento")),
        )
        for p in _lista(percepciones_nodo, "Percepcion")
    ]

    deducciones = [
        DatosDeduccion(
            tipo_deduccion=_clave(d.get("TipoDeduccion")) or "",
            clave=d.get("Clave"),
            concepto=d.get("Concepto"),
            importe=_decimal_o_cero(d.get("Importe")),
        )
        for d in _lista(deducciones_nodo, "Deduccion")
    ]

    otros_pagos: list[DatosOtroPago] = []
    for o in _lista(nodo.get("OtrosPagos"), "OtroPago"):
        # `satcfdi` aplana `SubsidioAlEmpleo` directamente al valor de `SubsidioCausado`
        # (no es un mapa anidado, a diferencia de `CompensacionSaldosAFavor`). Ojo: no usar
        # `o.get("SubsidioAlEmpleo") or {}` porque `Decimal("0.00")` es falsy en Python y
        # el subsidio causado real puede ser cero.
        compensacion = o.get("CompensacionSaldosAFavor") or {}
        otros_pagos.append(
            DatosOtroPago(
                tipo_otro_pago=_clave(o.get("TipoOtroPago")) or "",
                clave=o.get("Clave"),
                concepto=o.get("Concepto"),
                importe=_decimal_o_cero(o.get("Importe")),
                subsidio_causado=_decimal(o.get("SubsidioAlEmpleo")),
                saldo_a_favor=_decimal(compensacion.get("SaldoAFavor")),
                anio=int(compensacion["Año"]) if compensacion.get("Año") is not None else None,
                remanente_sal_fav=_decimal(compensacion.get("RemanenteSalFav")),
            )
        )

    incapacidades = [
        DatosIncapacidad(
            dias_incapacidad=int(i["DiasIncapacidad"]) if i.get("DiasIncapacidad") is not None else None,
            tipo_incapacidad=_clave(i.get("TipoIncapacidad")),
            importe_monetario=_decimal(i.get("ImporteMonetario")),
        )
        for i in _lista(nodo.get("Incapacidades"), "Incapacidad")
    ]

    totales = DatosNominaTotales(
        total_sueldos=_decimal(percepciones_nodo.get("TotalSueldos")),
        total_separacion_indemnizacion=_decimal(percepciones_nodo.get("TotalSeparacionIndemnizacion")),
        total_jubilacion_pension_retiro=_decimal(percepciones_nodo.get("TotalJubilacionPensionRetiro")),
        total_gravado=_decimal(percepciones_nodo.get("TotalGravado")),
        total_exento=_decimal(percepciones_nodo.get("TotalExento")),
        total_otras_deducciones=_decimal(deducciones_nodo.get("TotalOtrasDeducciones")),
        total_impuestos_retenidos=_decimal(deducciones_nodo.get("TotalImpuestosRetenidos")),
    )

    return DatosNomina(
        cabecera=cabecera,
        receptor=receptor,
        totales=totales,
        percepciones=percepciones,
        deducciones=deducciones,
        otros_pagos=otros_pagos,
        incapacidades=incapacidades,
    )


def normalizar(xml_bytes: bytes) -> DatosComprobante:
    """Parsea el XML completo. Lanza si el XML no es un CFDI legible; el caller decide
    qué hacer con el fallo (spec §6.2: se persiste en `error_normalizacion`)."""
    from satcfdi.cfdi import CFDI

    c = CFDI.from_string(xml_bytes)
    complemento = c.get("Complemento") or {}
    nomina_nodo = complemento.get("Nomina")
    pagos_nodo = complemento.get("Pagos")
    pagos, pago_totales = _pagos(pagos_nodo) if pagos_nodo is not None else ([], None)
    return DatosComprobante(
        encabezado=_encabezado(c),
        conceptos=_conceptos(c),
        relacionados=_relacionados(c),
        nomina=_nomina(nomina_nodo) if nomina_nodo is not None else None,
        pagos=pagos,
        pago_totales=pago_totales,
    )
