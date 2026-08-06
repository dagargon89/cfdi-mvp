"""Configuración fiscal para los informes de nómina B-03, B-06 y B-08 (§12 del diseño,
§2.12 y §3.1 del documento fuente): UMA, salario mínimo, marcas de exención por tipo de
percepción, y los mapeos de cada organización (departamento -> centro de costo, concepto
de nómina -> categoría de provisión).

`param_fiscal` frente a la tabla `Configuracion` que ya existe
----------------------------------------------------------------
`Configuracion` (`app/models/configuracion.py`) versiona por `ejercicio_fiscal` en texto
y guarda `valor` como JSON; le basta un valor por ejercicio porque sirve a las reglas
operativas del propio Hub CFDI (ventanas de descarga, reintentos, hora de sync, etc.),
que no cambian a mitad de año. `param_fiscal` resuelve un problema distinto: la UMA
cambia de valor el 1 de febrero, a mitad del ejercicio fiscal, así que un solo valor por
`ejercicio_fiscal` no alcanza para expresar los dos tramos de vigencia que coexisten en
un mismo año (ver la prueba `test_param_fiscal_admite_dos_tramos_en_un_ejercicio`).
Además cada fila de `param_fiscal` carga procedencia (`origen`, `fuente`,
`confirmado_por`, `confirmado_en`): quién sembró el valor, de dónde salió, quién lo
confirmó antes de usarlo en un informe. `Configuracion` no necesita nada de eso para sus
propios valores. Son dos mecanismos para dos necesidades distintas — aunque las dos
tablas se administren desde la misma pantalla (tarea 5), **no deben fusionarse**:
fusionarlas perdería la vigencia partida de la UMA o la procedencia de cada valor.

`configuracion_empresa` nace con sus tres campos en NULL — decisión explícita
--------------------------------------------------------------------------------
Ninguno de `zona_salarial`, `dias_aguinaldo` ni `factor_prima_vacacional` tiene default.
Para `zona_salarial`: el mínimo aplicable cambia el resultado de una validación de
cumplimiento. Ciudad Juárez está en la Zona Libre de la Frontera Norte, donde el mínimo
2026 es 440.87 contra 315.04 del régimen general — si el campo naciera en "GENERAL" por
default, una empresa de zona frontera que nunca configuró el valor obtendría falsos
negativos en "empleado por debajo del mínimo". Un default plausible aquí es peor que un
hueco visible que obliga a configurar el dato antes de confiar en el informe. Lo mismo
aplica a `dias_aguinaldo` (el mínimo legal son 15 días, pero cada organización puede dar
más) y a `factor_prima_vacacional` (mínimo legal 0.25, art. 80 LFT): la ley pone un piso,
no un valor único, y adivinar cuál aplica en cada empresa es responsabilidad de quien
configura el sistema, no de este modelo. **No le pongas default a estos tres campos.**

Por qué esta tabla y no columnas en `empresas`
-------------------------------------------------
`empresas` es la tabla caliente del listado de la UI; la fase 1 de los informes CFDI
estableció no tocarla y colgar los datos nuevos de una tabla aparte. Además estos tres
valores son política laboral de cada organización, no identidad de la empresa.

Reglas duras que aplican a todo este módulo: las claves de catálogo (`tipo_percepcion`,
`tipo`, `naturaleza`) son texto, nunca entero — los ceros a la izquierda son
significativos. Los importes usan `Decimal`/`Numeric`, nunca `float`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import BaseExencion, CategoriaProvision, OrigenValor, ZonaSalarial, enum_column

_TABLA_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


class ParamFiscal(Base):
    """UMA, salario mínimo y tipo de cambio, con vigencia y procedencia.

    PK compuesta `(clave, vigencia_desde)`: una misma clave (p. ej. `UMA_DIARIA`) puede
    tener varios tramos de vigencia dentro del mismo `ejercicio`, porque la UMA cambia el
    1 de febrero mientras que el ejercicio fiscal corre de enero a diciembre.
    `vigencia_hasta` nulo significa "vigente hasta nuevo aviso", no "sin vigencia" — es
    el estado normal del tramo más reciente.

    Claves esperadas: `UMA_DIARIA`, `UMA_MENSUAL`, `UMA_ANUAL`, `SALARIO_MINIMO_GENERAL`,
    `SALARIO_MINIMO_ZLFN`, `TIPO_CAMBIO_USD`.
    """

    __tablename__ = "param_fiscal"
    __table_args__ = (_TABLA_ARGS,)

    clave: Mapped[str] = mapped_column(String(40), primary_key=True)
    vigencia_desde: Mapped[date] = mapped_column(Date, primary_key=True)
    ejercicio: Mapped[int] = mapped_column(Integer, nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    vigencia_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    origen: Mapped[OrigenValor] = mapped_column(enum_column(OrigenValor), nullable=False)
    # Procedencia: de dónde salió el valor. Sin esto nadie puede revisar una semilla.
    fuente: Mapped[str] = mapped_column(String(500), nullable=False)
    sincronizado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Sembrar propone, no activa: `confirmado_en` nulo es el estado inicial legítimo,
    # distinto de "no hay valor" (el valor sí existe, solo falta que alguien lo revise).
    confirmado_por: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CatalogoPercepcionMarca(Base):
    """Marcas por tipo de percepción de nómina (§3.1 del documento fuente) que el catálogo
    `c_TipoPercepcion` del SAT no trae: si es ingreso ordinario, sobre qué base se calcula
    su tramo exento, si integra al SBC y si es provisionable (aguinaldo/vacaciones/etc.).

    Lleva confirmación como `param_fiscal`, y por la misma razón, solo que aquí pesa más:
    `factor_exencion` alimenta el cálculo de exenciones igual que la UMA, los factores del
    art. 93 de la LISR también cambian por reforma, y —a diferencia de la UMA, que se
    verifica contra un único boletín oficial— son ~46 derivaciones hechas a mano, el dato
    más propenso a error de toda la fase. Sin esta puerta, la UMA exigiría un clic y los 46
    factores se aplicarían solos en cuanto alguien los cargara.
    """

    __tablename__ = "catalogo_percepcion_marca"
    __table_args__ = (_TABLA_ARGS,)

    # Clave del catálogo del SAT como texto: '002' no puede volverse 2.
    tipo_percepcion: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    es_ingreso_ordinario: Mapped[bool] = mapped_column(Boolean, nullable=False)
    base_exencion: Mapped[BaseExencion] = mapped_column(enum_column(BaseExencion), nullable=False)
    # NULL cuando `base_exencion` es NINGUNA: no hay tramo exento que calcular.
    factor_exencion: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    integra_sbc: Mapped[bool] = mapped_column(Boolean, nullable=False)
    es_provisionable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Mismo invariante que `param_fiscal`: sembrar propone, solo una persona activa.
    confirmado_por: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MapDepartamento(Base):
    """Traduce el texto libre de `departamento` en la nómina (`nomina_receptor.departamento`)
    al centro de costo de cada organización. El mismo texto puede mapear a centros de
    costo distintos en empresas distintas — por eso cuelga de `empresa_id`, no es global."""

    __tablename__ = "map_departamento"
    __table_args__ = (_TABLA_ARGS,)

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="CASCADE"), primary_key=True)
    departamento_texto: Mapped[str] = mapped_column(String(100), primary_key=True)
    centro_costo: Mapped[str] = mapped_column(String(100), nullable=False)


class MapConceptoProvision(Base):
    """Asocia un concepto de nómina de la organización (`naturaleza` + `tipo` + `clave`,
    la clave interna del patrón de percepción/deducción) con la categoría de provisión
    contable a la que corresponde (aguinaldo, vacaciones, prima vacacional)."""

    __tablename__ = "map_concepto_provision"
    __table_args__ = (_TABLA_ARGS,)

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="CASCADE"), primary_key=True)
    naturaleza: Mapped[str] = mapped_column(CHAR(1), primary_key=True)
    tipo: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    clave: Mapped[str] = mapped_column(String(15), primary_key=True)
    categoria: Mapped[CategoriaProvision] = mapped_column(enum_column(CategoriaProvision), nullable=False)


class TablaVacaciones(Base):
    """Días de vacaciones por año de antigüedad, art. 76 de la LFT. Es ley federal, no una
    regla de cada patrón: por eso es una tabla global, sin `empresa_id`.

    **No lleva confirmación**, a diferencia de `param_fiscal` y `catalogo_percepcion_marca`
    — decisión explícita, no olvido. Los otros dos exigen confirmación porque son valores
    que cambian por decreto (la UMA, cada febrero) o derivaciones con criterio (los ~46
    factores del art. 93). Esta tabla es la transcripción literal de un solo artículo, con
    dos columnas de enteros, estable desde la reforma de 2023 y verificable de un vistazo
    contra la ley; un error de captura aquí lo atrapa la prueba de monotonía de la semilla,
    no una revisión humana renglón por renglón. Poner una puerta de confirmación donde el
    dato no puede sorprender solo enseña a la gente a confirmar sin mirar, y eso desgasta
    la puerta donde sí importa.
    """

    __tablename__ = "tabla_vacaciones"
    __table_args__ = (_TABLA_ARGS,)

    anios_antiguedad: Mapped[int] = mapped_column(Integer, primary_key=True)
    dias: Mapped[int] = mapped_column(Integer, nullable=False)


class ConfiguracionEmpresa(Base):
    """Política laboral de cada organización. Los tres campos nacen en NULL a propósito
    — ver la justificación completa en el docstring del módulo: un default aquí puede
    esconder un falso negativo en una validación de cumplimiento."""

    __tablename__ = "configuracion_empresa"
    __table_args__ = (_TABLA_ARGS,)

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="CASCADE"), primary_key=True)
    zona_salarial: Mapped[ZonaSalarial | None] = mapped_column(enum_column(ZonaSalarial), nullable=True)
    dias_aguinaldo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    factor_prima_vacacional: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
