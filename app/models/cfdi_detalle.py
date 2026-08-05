# app/models/cfdi_detalle.py
"""Encabezado extendido y cuerpo del comprobante (spec §5.1).

`comprobantes` es la tabla caliente del listado de la UI y no se toca: el encabezado
extendido vive aquí, en una tabla 1:1, para que un fallo del ETL no pueda dañar el
índice del que depende la aplicación (spec §4.2).

Todas las claves de catálogo son texto y todos los importes `Numeric(18, 6)` — ver las
reglas duras del spec §5.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_TABLA_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


class ComprobanteDetalle(Base):
    """1:1 con `comprobantes`. `xml_hash` + `etl_version` son la base de la idempotencia
    del ETL (spec §6.2); `error_normalizacion` guarda el fallo para que el pre-vuelo no
    reintente el mismo XML corrupto en cada corrida."""

    __tablename__ = "comprobante_detalle"
    __table_args__ = (_TABLA_ARGS,)

    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[str | None] = mapped_column(String(5), nullable=True)
    serie: Mapped[str | None] = mapped_column(String(25), nullable=True)
    fecha_timbrado: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    forma_pago: Mapped[str | None] = mapped_column(String(2), nullable=True)
    metodo_pago: Mapped[str | None] = mapped_column(String(3), nullable=True)
    moneda: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    tipo_cambio: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    descuento: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    lugar_expedicion: Mapped[str | None] = mapped_column(String(5), nullable=True)
    exportacion: Mapped[str | None] = mapped_column(String(2), nullable=True)
    regimen_emisor: Mapped[str | None] = mapped_column(String(3), nullable=True)
    nombre_receptor: Mapped[str | None] = mapped_column(String(300), nullable=True)
    domicilio_receptor: Mapped[str | None] = mapped_column(String(5), nullable=True)
    regimen_receptor: Mapped[str | None] = mapped_column(String(3), nullable=True)
    uso_cfdi: Mapped[str | None] = mapped_column(String(4), nullable=True)
    no_certificado: Mapped[str | None] = mapped_column(String(20), nullable=True)
    no_certificado_sat: Mapped[str | None] = mapped_column(String(20), nullable=True)
    xml_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    etl_version: Mapped[int] = mapped_column(Integer, nullable=False)
    normalizado_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_normalizacion: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CfdiConcepto(Base):
    __tablename__ = "cfdi_concepto"
    __table_args__ = (
        UniqueConstraint("comprobante_id", "num_linea", name="uq_concepto_linea"),
        _TABLA_ARGS,
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    num_linea: Mapped[int] = mapped_column(Integer, nullable=False)
    clave_prod_serv: Mapped[str | None] = mapped_column(String(8), nullable=True)
    no_identificacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cantidad: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    clave_unidad: Mapped[str | None] = mapped_column(String(3), nullable=True)
    unidad: Mapped[str | None] = mapped_column(String(20), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    valor_unitario: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    descuento: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    objeto_imp: Mapped[str | None] = mapped_column(String(2), nullable=True)


class CfdiConceptoImpuesto(Base):
    """Impuestos a nivel concepto. `comprobante_id` está desnormalizado a propósito: los
    informes de impuestos por tasa agregan sin pasar por `cfdi_concepto` (§2.3 del fuente)."""

    __tablename__ = "cfdi_concepto_impuesto"
    __table_args__ = (
        Index("idx_cci_comp_impuesto", "comprobante_id", "naturaleza", "impuesto", "tasa_o_cuota"),
        _TABLA_ARGS,
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    concepto_id: Mapped[int] = mapped_column(ForeignKey("cfdi_concepto.id", ondelete="CASCADE"), nullable=False)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    naturaleza: Mapped[str] = mapped_column(CHAR(1), nullable=False)
    impuesto: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    tipo_factor: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tasa_o_cuota: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class CfdiRelacionado(Base):
    __tablename__ = "cfdi_relacionado"
    __table_args__ = (
        UniqueConstraint("comprobante_id", "tipo_relacion", "uuid_relacionado", name="uq_relacionado"),
        _TABLA_ARGS,
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    tipo_relacion: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    uuid_relacionado: Mapped[str] = mapped_column(CHAR(36), nullable=False)
