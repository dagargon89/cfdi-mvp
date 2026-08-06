"""Tablas de configuración fiscal (§12 del diseño, §2.12 y §3.1 del documento fuente).

Lo que estas pruebas fijan a propósito:
- `param_fiscal` admite dos tramos de vigencia en un mismo ejercicio (la UMA cambia el 1 de
  febrero, el salario mínimo el 1 de enero).
- Cada valor carga su procedencia, y `confirmado_en` nulo es un estado legítimo y distinto de
  "no hay valor".
- `configuracion_empresa` nace con los tres campos nulos: no hay default para la zona salarial
  porque el mínimo aplicable cambia el resultado de una validación de cumplimiento.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion_fiscal import (
    CatalogoPercepcionMarca,
    ConfiguracionEmpresa,
    MapConceptoProvision,
    MapDepartamento,
    ParamFiscal,
    TablaVacaciones,
)
from app.models.enums import BaseExencion, CategoriaProvision, OrigenValor, ZonaSalarial
from tests import factories


async def test_param_fiscal_admite_dos_tramos_en_un_ejercicio(db: AsyncSession) -> None:
    """La UMA cambia el 1 de febrero: enero todavía usa la del año anterior."""
    db.add(ParamFiscal(ejercicio=2026, clave="UMA_DIARIA", valor=Decimal("113.140000"),
                       vigencia_desde=date(2025, 2, 1), vigencia_hasta=date(2026, 1, 31),
                       origen=OrigenValor.SEMILLA, fuente="INEGI, boletín UMA 2025"))
    db.add(ParamFiscal(ejercicio=2026, clave="UMA_DIARIA", valor=Decimal("117.310000"),
                       vigencia_desde=date(2026, 2, 1), vigencia_hasta=None,
                       origen=OrigenValor.SEMILLA, fuente="INEGI, boletín UMA 2026"))
    await db.commit()

    filas = list((await db.execute(select(ParamFiscal).order_by(ParamFiscal.vigencia_desde))).scalars().all())
    assert len(filas) == 2
    # `vigencia_hasta` nula significa "vigente hasta nuevo aviso", no "sin vigencia".
    assert filas[1].vigencia_hasta is None
    assert filas[0].valor == Decimal("113.140000")


async def test_un_valor_nace_sin_confirmar(db: AsyncSession) -> None:
    """Sembrar propone, no activa: `confirmado_en` nulo es el estado inicial legítimo."""
    db.add(ParamFiscal(ejercicio=2026, clave="UMA_DIARIA", valor=Decimal("117.310000"),
                       vigencia_desde=date(2026, 2, 1), vigencia_hasta=None,
                       origen=OrigenValor.SEMILLA, fuente="INEGI, boletín UMA 2026"))
    await db.commit()

    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None
    assert fila.confirmado_en is None
    assert fila.confirmado_por is None
    # La procedencia siempre viaja con el valor: sin fuente, nadie puede revisarlo.
    assert fila.fuente != ""
    assert fila.origen is OrigenValor.SEMILLA


async def test_confirmar_registra_quien_y_cuando(db: AsyncSession) -> None:
    db.add(ParamFiscal(ejercicio=2026, clave="UMA_DIARIA", valor=Decimal("117.310000"),
                       vigencia_desde=date(2026, 2, 1), vigencia_hasta=None,
                       origen=OrigenValor.SEMILLA, fuente="INEGI"))
    await db.commit()

    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None
    fila.confirmado_por = "uid-de-prueba"
    fila.confirmado_en = datetime(2026, 8, 6, 12, 0, 0)
    await db.commit()

    recargada = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert recargada is not None
    assert recargada.confirmado_por == "uid-de-prueba"
    assert recargada.confirmado_en is not None


async def test_marca_de_percepcion_conserva_la_clave_como_texto(db: AsyncSession) -> None:
    db.add(CatalogoPercepcionMarca(tipo_percepcion="002", es_ingreso_ordinario=True,
                                   base_exencion=BaseExencion.UMA_DIAS, factor_exencion=Decimal("30.0000"),
                                   integra_sbc=True, es_provisionable=True))
    db.add(CatalogoPercepcionMarca(tipo_percepcion="022", es_ingreso_ordinario=False,
                                   base_exencion=BaseExencion.NINGUNA, factor_exencion=None,
                                   integra_sbc=False, es_provisionable=False))
    await db.commit()

    marca = await db.scalar(select(CatalogoPercepcionMarca).where(CatalogoPercepcionMarca.tipo_percepcion == "002"))
    assert marca is not None
    # '002' no puede volverse 2.
    assert marca.tipo_percepcion == "002"
    assert marca.factor_exencion == Decimal("30.0000")
    sin_exencion = await db.scalar(
        select(CatalogoPercepcionMarca).where(CatalogoPercepcionMarca.tipo_percepcion == "022"))
    assert sin_exencion is not None
    assert sin_exencion.factor_exencion is None


async def test_configuracion_de_empresa_nace_sin_defaults(db: AsyncSession) -> None:
    """Decisión explícita: la zona salarial no tiene default porque el mínimo aplicable
    cambia el resultado de una validación de cumplimiento (Juárez es ZLFN, no general)."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    db.add(ConfiguracionEmpresa(empresa_id=empresa.empresa_id))
    await db.commit()

    cfg = await db.scalar(select(ConfiguracionEmpresa).where(ConfiguracionEmpresa.empresa_id == empresa.empresa_id))
    assert cfg is not None
    assert cfg.zona_salarial is None
    assert cfg.dias_aguinaldo is None
    assert cfg.factor_prima_vacacional is None

    cfg.zona_salarial = ZonaSalarial.ZLFN
    await db.commit()
    recargada = await db.scalar(
        select(ConfiguracionEmpresa).where(ConfiguracionEmpresa.empresa_id == empresa.empresa_id))
    assert recargada is not None
    assert recargada.zona_salarial is ZonaSalarial.ZLFN


async def test_mapeos_de_organizacion_cuelgan_de_la_empresa(db: AsyncSession) -> None:
    """Dos empresas pueden tener el mismo texto de departamento con centros de costo distintos."""
    a = await factories.crear_empresa(db, rfc="CHL960913IX9", nombre="Empresa A")
    b = await factories.crear_empresa(db, rfc="EKU9003173C9", nombre="Empresa B")

    db.add(MapDepartamento(empresa_id=a.empresa_id, departamento_texto="Direccion", centro_costo="ADMIN"))
    db.add(MapDepartamento(empresa_id=b.empresa_id, departamento_texto="Direccion", centro_costo="GERENCIA"))
    db.add(MapConceptoProvision(empresa_id=a.empresa_id, naturaleza="P", tipo="001", clave="019",
                                categoria=CategoriaProvision.VACACIONES))
    await db.commit()

    de_a = await db.scalar(select(MapDepartamento).where(MapDepartamento.empresa_id == a.empresa_id))
    de_b = await db.scalar(select(MapDepartamento).where(MapDepartamento.empresa_id == b.empresa_id))
    assert de_a is not None and de_b is not None
    assert de_a.centro_costo == "ADMIN" and de_b.centro_costo == "GERENCIA"

    provision = await db.scalar(select(MapConceptoProvision).where(MapConceptoProvision.empresa_id == a.empresa_id))
    assert provision is not None
    # La clave interna del patrón, como texto.
    assert (provision.naturaleza, provision.tipo, provision.clave) == ("P", "001", "019")


async def test_borrar_la_empresa_arrastra_su_configuracion(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    db.add(MapDepartamento(empresa_id=empresa.empresa_id, departamento_texto="Direccion", centro_costo="ADMIN"))
    db.add(ConfiguracionEmpresa(empresa_id=empresa.empresa_id, zona_salarial=ZonaSalarial.ZLFN))
    await db.commit()

    await db.delete(empresa)
    await db.commit()
    assert await db.scalar(select(MapDepartamento).where(MapDepartamento.empresa_id == empresa.empresa_id)) is None
    assert await db.scalar(
        select(ConfiguracionEmpresa).where(ConfiguracionEmpresa.empresa_id == empresa.empresa_id)) is None


async def test_tabla_de_vacaciones_es_global(db: AsyncSession) -> None:
    """Art. 76 de la LFT: es ley federal, no una regla de cada patrón."""
    db.add(TablaVacaciones(anios_antiguedad=1, dias=12))
    db.add(TablaVacaciones(anios_antiguedad=2, dias=14))
    await db.commit()

    filas = list((await db.execute(select(TablaVacaciones).order_by(TablaVacaciones.anios_antiguedad))).scalars().all())
    assert [(f.anios_antiguedad, f.dias) for f in filas] == [(1, 12), (2, 14)]
