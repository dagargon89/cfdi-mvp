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

`nomina`, `pagos` y `pago_totales` de `DatosComprobante` quedan tipados como `Any` a
propósito: las tareas 5 y 6 agregan `DatosNomina`/`DatosPago`/`DatosPagoTotales` y solo
tendrán que afinar el tipo aquí, no el resto del árbol. Esta tarea solo los deja en su
valor "sin complemento" (`None`/`[]`/`None`).
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
class DatosComprobante:
    encabezado: DatosEncabezado
    conceptos: list[DatosConcepto] = field(default_factory=list)
    relacionados: list[DatosRelacionado] = field(default_factory=list)
    # Tipo definitivo (`DatosNomina | None`) lo pone la tarea 5; aquí solo existe el campo.
    nomina: Any | None = None
    # Tipo definitivo (`list[DatosPago]`) lo pone la tarea 6; aquí solo existe el campo.
    pagos: list[Any] = field(default_factory=list)
    # Tipo definitivo (`DatosPagoTotales | None`) lo pone la tarea 6; aquí solo existe el campo.
    pago_totales: Any | None = None


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


def normalizar(xml_bytes: bytes) -> DatosComprobante:
    """Parsea el XML completo. Lanza si el XML no es un CFDI legible; el caller decide
    qué hacer con el fallo (spec §6.2: se persiste en `error_normalizacion`)."""
    from satcfdi.cfdi import CFDI

    c = CFDI.from_string(xml_bytes)
    return DatosComprobante(encabezado=_encabezado(c), conceptos=_conceptos(c), relacionados=_relacionados(c))
