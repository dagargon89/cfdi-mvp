"""Complemento de Nómina 1.2 (spec §5.3, §2.6–§2.11 del documento fuente).

Dos decisiones deliberadas:

- `nomina_totales` fusiona `nomina_percepciones_tot` y `nomina_deducciones_tot` del
  documento fuente: ambos son 1:1 con el comprobante y separarlos solo agrega un JOIN.
- Ni `nomina_percepcion` ni `nomina_deduccion` ni `nomina_otro_pago` llevan restricción
  de unicidad sobre `(comprobante_id, tipo, clave)`: el esquema del SAT permite nodos
  repetidos y el valor correcto es la SUMA, no el último (B-02.R1). Una restricción aquí
  haría fallar el ETL en CFDI perfectamente válidos.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_TABLA_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


class Nomina(Base):
    __tablename__ = "nomina"
    __table_args__ = (Index("idx_nomina_fecha_pago", "fecha_pago"), Index("idx_nomina_final_pago", "fecha_final_pago"), _TABLA_ARGS)

    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), primary_key=True)
    version_nomina: Mapped[str | None] = mapped_column(String(5), nullable=True)
    tipo_nomina: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    fecha_pago: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_inicial_pago: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_final_pago: Mapped[date | None] = mapped_column(Date, nullable=True)
    num_dias_pagados: Mapped[Decimal | None] = mapped_column(Numeric(9, 3), nullable=True)
    total_percepciones: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_deducciones: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_otros_pagos: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    registro_patronal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rfc_patron_origen: Mapped[str | None] = mapped_column(String(13), nullable=True)
    origen_recurso: Mapped[str | None] = mapped_column(String(2), nullable=True)
    monto_recurso_propio: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class NominaReceptor(Base):
    """Datos del trabajador. `curp`, `nss` y `cuenta_bancaria` son **datos personales**:
    todo informe que los emita respeta el enmascaramiento del spec §8."""

    __tablename__ = "nomina_receptor"
    __table_args__ = (Index("idx_nom_receptor_curp", "curp"), Index("idx_nom_receptor_nss", "nss"), _TABLA_ARGS)

    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), primary_key=True)
    curp: Mapped[str | None] = mapped_column(CHAR(18), nullable=True)
    nss: Mapped[str | None] = mapped_column(String(15), nullable=True)
    fecha_inicio_rel_laboral: Mapped[date | None] = mapped_column(Date, nullable=True)
    antiguedad: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tipo_contrato: Mapped[str | None] = mapped_column(String(2), nullable=True)
    sindicalizado: Mapped[str | None] = mapped_column(String(2), nullable=True)
    tipo_jornada: Mapped[str | None] = mapped_column(String(2), nullable=True)
    tipo_regimen: Mapped[str | None] = mapped_column(String(2), nullable=True)
    num_empleado: Mapped[str | None] = mapped_column(String(15), nullable=True)
    departamento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    puesto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    riesgo_puesto: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    periodicidad_pago: Mapped[str | None] = mapped_column(String(2), nullable=True)
    banco: Mapped[str | None] = mapped_column(String(3), nullable=True)
    cuenta_bancaria: Mapped[str | None] = mapped_column(String(18), nullable=True)
    salario_base_cot_apor: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    salario_diario_integrado: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    clave_ent_fed: Mapped[str | None] = mapped_column(String(3), nullable=True)


class NominaPercepcion(Base):
    __tablename__ = "nomina_percepcion"
    __table_args__ = (Index("idx_percepcion_concepto", "comprobante_id", "tipo_percepcion", "clave"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    tipo_percepcion: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    clave: Mapped[str | None] = mapped_column(String(15), nullable=True)
    concepto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    importe_gravado: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    importe_exento: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))


class NominaDeduccion(Base):
    __tablename__ = "nomina_deduccion"
    __table_args__ = (Index("idx_deduccion_concepto", "comprobante_id", "tipo_deduccion", "clave"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    tipo_deduccion: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    clave: Mapped[str | None] = mapped_column(String(15), nullable=True)
    concepto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    importe: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))


class NominaOtroPago(Base):
    __tablename__ = "nomina_otro_pago"
    __table_args__ = (Index("idx_otro_pago_concepto", "comprobante_id", "tipo_otro_pago", "clave"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    tipo_otro_pago: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    clave: Mapped[str | None] = mapped_column(String(15), nullable=True)
    concepto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    importe: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    subsidio_causado: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    saldo_a_favor: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    anio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remanente_sal_fav: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class NominaIncapacidad(Base):
    __tablename__ = "nomina_incapacidad"
    __table_args__ = (Index("idx_incapacidad_comp", "comprobante_id"), _TABLA_ARGS)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), nullable=False)
    dias_incapacidad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tipo_incapacidad: Mapped[str | None] = mapped_column(String(2), nullable=True)
    importe_monetario: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class NominaTotales(Base):
    """Fusión de `nomina_percepciones_tot` y `nomina_deducciones_tot` del documento fuente."""

    __tablename__ = "nomina_totales"
    __table_args__ = (_TABLA_ARGS,)

    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobantes.comprobante_id", ondelete="CASCADE"), primary_key=True)
    total_sueldos: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_separacion_indemnizacion: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_jubilacion_pension_retiro: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_gravado: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_exento: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_otras_deducciones: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_impuestos_retenidos: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
