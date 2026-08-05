"""Complemento de Pagos 2.0 (spec §5.2, §2.5 del documento fuente).

`equivalencia_dr` es `Numeric(18, 10)`, no 6: es un factor de conversión entre monedas y
el estándar admite 10 decimales.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_TABLA_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


class Pago(Base):
    __tablename__ = "pago"
    __table_args__ = (Index("idx_pago_comp", "comprobante_id"), Index("idx_pago_fecha", "fecha_pago"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    num_pago: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_pago: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    forma_de_pago_p: Mapped[str | None] = mapped_column(String(2), nullable=True)
    moneda_p: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    tipo_cambio_p: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    monto: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    num_operacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rfc_emisor_cta_ord: Mapped[str | None] = mapped_column(String(13), nullable=True)
    cta_ordenante: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rfc_emisor_cta_ben: Mapped[str | None] = mapped_column(String(13), nullable=True)
    cta_beneficiario: Mapped[str | None] = mapped_column(String(50), nullable=True)


class PagoDocto(Base):
    __tablename__ = "pago_docto"
    __table_args__ = (Index("idx_docto_documento", "id_documento"), Index("idx_docto_comp", "comprobante_id"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pago_id: Mapped[int] = mapped_column(ForeignKey("pago.id", ondelete="CASCADE"), nullable=False)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    id_documento: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    serie: Mapped[str | None] = mapped_column(String(25), nullable=True)
    folio: Mapped[str | None] = mapped_column(String(40), nullable=True)
    moneda_dr: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    equivalencia_dr: Mapped[Decimal | None] = mapped_column(Numeric(18, 10), nullable=True)
    num_parcialidad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imp_saldo_ant: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    imp_pagado: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    imp_saldo_insoluto: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    objeto_imp_dr: Mapped[str | None] = mapped_column(String(2), nullable=True)


class PagoDoctoImpuesto(Base):
    __tablename__ = "pago_docto_impuesto"
    __table_args__ = (Index("idx_pdi_comp", "comprobante_id", "naturaleza", "impuesto"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pago_docto_id: Mapped[int] = mapped_column(ForeignKey("pago_docto.id", ondelete="CASCADE"), nullable=False)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    naturaleza: Mapped[str] = mapped_column(CHAR(1), nullable=False)
    impuesto: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    tipo_factor: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tasa_o_cuota: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class PagoTotales(Base):
    """1:1 con el comprobante — nodo `pago20:Totales` (§2.5 del fuente). Los campos no
    informados quedan en `NULL`, no en cero: "no vino" y "vino en cero" son distintos aquí."""

    __tablename__ = "pago_totales"
    __table_args__ = (_TABLA_ARGS,)

    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), primary_key=True)
    total_traslados_base_iva16: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_impuesto_iva16: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_base_iva8: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_impuesto_iva8: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_base_iva0: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_impuesto_iva0: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_traslados_base_iva_exento: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_retenciones_iva: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_retenciones_isr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_retenciones_ieps: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    monto_total_pagos: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
