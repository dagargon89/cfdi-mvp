"""Resolución por vigencia, invariante de confirmación y carga de la configuración fiscal.

La regla central que estas pruebas fijan: **un valor sin confirmar no calcula.** Sembrar o
sincronizar propone; solo una persona activa. Y la ausencia se distingue del cero: `None`
nunca es `Decimal("0")`, porque un cero en un tope de exención produce exenciones falsas.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion_fiscal import ConfiguracionEmpresa, ParamFiscal
from app.models.enums import OrigenValor, ZonaSalarial
from app.services import configuracion_fiscal as cfg
from tests import factories


def _param(clave: str, valor: str, desde: date, *, confirmado: bool, hasta: date | None = None) -> ParamFiscal:
    return ParamFiscal(
        ejercicio=desde.year, clave=clave, valor=Decimal(valor), vigencia_desde=desde, vigencia_hasta=hasta,
        origen=OrigenValor.SEMILLA, fuente="prueba",
        confirmado_por="uid-prueba" if confirmado else None,
        confirmado_en=datetime(2026, 8, 6, 12, 0, 0) if confirmado else None,
    )


async def test_valor_vigente_resuelve_por_fecha(db: AsyncSession) -> None:
    db.add(_param("UMA_DIARIA", "113.140000", date(2025, 2, 1), hasta=date(2026, 1, 31), confirmado=True))
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=True))
    await db.commit()

    # Enero de 2026 todavía usa la UMA publicada en febrero de 2025.
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 1, 15)) == Decimal("113.140000")
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) == Decimal("117.310000")
    # El día exacto del corte cuenta para el tramo nuevo.
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 2, 1)) == Decimal("117.310000")


async def test_un_valor_sin_confirmar_no_calcula(db: AsyncSession) -> None:
    """El invariante central de la fase: sembrar propone, no activa."""
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=False))
    await db.commit()

    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None
    # Pero la propuesta se puede ver, con su procedencia, para que el aviso sea accionable.
    propuesto = await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 30))
    assert propuesto is not None
    assert propuesto.valor == Decimal("117.310000")
    assert propuesto.confirmado is False
    assert propuesto.fuente == "prueba"


async def test_confirmar_activa_el_valor(db: AsyncSession) -> None:
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=False))
    await db.commit()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) is None

    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None
    fila.confirmado_por = "uid-prueba"
    fila.confirmado_en = datetime(2026, 8, 6, 12, 0, 0)
    await db.commit()

    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) == Decimal("117.310000")


async def test_sin_valor_devuelve_none_no_cero(db: AsyncSession) -> None:
    """Un cero en un tope de exención produce exenciones falsas: la ausencia debe ser `None`."""
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None
    assert await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 30)) is None


async def test_fecha_anterior_a_toda_vigencia_devuelve_none(db: AsyncSession) -> None:
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=True))
    await db.commit()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2025, 12, 31)) is None


async def test_salario_minimo_depende_de_la_zona_configurada(db: AsyncSession) -> None:
    """Ciudad Juárez es ZLFN: el mínimo aplicable es 440.87, no 315.04. Sin zona configurada,
    no hay default — devuelve `None` y B-10 no evalúa la validación."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    db.add(ConfiguracionEmpresa(empresa_id=empresa.empresa_id))  # zona nula a propósito
    db.add(_param("SALARIO_MINIMO_GENERAL", "315.040000", date(2026, 1, 1), confirmado=True))
    db.add(_param("SALARIO_MINIMO_ZLFN", "440.870000", date(2026, 1, 1), confirmado=True))
    await db.commit()

    # Sin zona configurada: ningún default, ni el general.
    assert await cfg.salario_minimo_de_empresa(db, empresa.empresa_id, date(2026, 6, 1)) is None

    config = await cfg.configuracion_de_empresa(db, empresa.empresa_id)
    assert config is not None
    config.zona_salarial = ZonaSalarial.ZLFN
    await db.commit()
    assert await cfg.salario_minimo_de_empresa(db, empresa.empresa_id, date(2026, 6, 1)) == Decimal("440.870000")

    config.zona_salarial = ZonaSalarial.GENERAL
    await db.commit()
    assert await cfg.salario_minimo_de_empresa(db, empresa.empresa_id, date(2026, 6, 1)) == Decimal("315.040000")


async def test_salario_minimo_sin_confirmar_no_se_usa_aunque_haya_zona(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    db.add(ConfiguracionEmpresa(empresa_id=empresa.empresa_id, zona_salarial=ZonaSalarial.ZLFN))
    db.add(_param("SALARIO_MINIMO_ZLFN", "440.870000", date(2026, 1, 1), confirmado=False))
    await db.commit()
    assert await cfg.salario_minimo_de_empresa(db, empresa.empresa_id, date(2026, 6, 1)) is None


async def test_cargar_yaml_es_idempotente_y_no_confirma(db: AsyncSession, tmp_path: Path) -> None:
    """Cargar una semilla nunca la confirma: eso es acto humano."""
    ruta = tmp_path / "param.yaml"
    ruta.write_text(
        "param_fiscal:\n"
        "  - ejercicio: 2026\n"
        "    clave: UMA_DIARIA\n"
        "    valor: '117.31'\n"
        "    vigencia_desde: 2026-02-01\n"
        "    vigencia_hasta: null\n"
        "    fuente: 'INEGI, boletin UMA 2026'\n",
        encoding="utf-8",
    )

    primero = await cfg.cargar_desde_yaml(db, ruta)
    segundo = await cfg.cargar_desde_yaml(db, ruta)
    assert primero["param_fiscal"] == 1
    assert segundo["param_fiscal"] == 1  # actualiza, no duplica

    # Cargada pero NO confirmada: no calcula.
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) is None
    propuesto = await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 1))
    assert propuesto is not None
    assert propuesto.valor == Decimal("117.31")


async def test_cargar_yaml_valida_lo_que_no_puede_estar_mal(db: AsyncSession, tmp_path: Path) -> None:
    """Un valor negativo o una vigencia invertida es un error de captura: hay que atraparlo al
    cargar, no al calcular un informe tres meses después."""
    negativo = tmp_path / "negativo.yaml"
    negativo.write_text(
        "param_fiscal:\n  - ejercicio: 2026\n    clave: UMA_DIARIA\n    valor: '-5.00'\n"
        "    vigencia_desde: 2026-02-01\n    vigencia_hasta: null\n    fuente: 'x'\n",
        encoding="utf-8")
    with pytest.raises(ValueError):
        await cfg.cargar_desde_yaml(db, negativo)

    invertida = tmp_path / "invertida.yaml"
    invertida.write_text(
        "param_fiscal:\n  - ejercicio: 2026\n    clave: UMA_DIARIA\n    valor: '117.31'\n"
        "    vigencia_desde: 2026-06-01\n    vigencia_hasta: 2026-02-01\n    fuente: 'x'\n",
        encoding="utf-8")
    with pytest.raises(ValueError):
        await cfg.cargar_desde_yaml(db, invertida)

    sin_fuente = tmp_path / "sin_fuente.yaml"
    sin_fuente.write_text(
        "param_fiscal:\n  - ejercicio: 2026\n    clave: UMA_DIARIA\n    valor: '117.31'\n"
        "    vigencia_desde: 2026-02-01\n    vigencia_hasta: null\n",
        encoding="utf-8")
    # Sin fuente nadie puede revisar el valor: es un error de captura, no un campo opcional.
    with pytest.raises(ValueError):
        await cfg.cargar_desde_yaml(db, sin_fuente)


async def test_los_mapeos_por_empresa_exigen_empresa_id(db: AsyncSession, tmp_path: Path) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    ruta = tmp_path / "mapeo.yaml"
    ruta.write_text(
        "map_departamento:\n  - departamento_texto: Direccion\n    centro_costo: ADMIN\n", encoding="utf-8")
    with pytest.raises(ValueError):
        await cfg.cargar_desde_yaml(db, ruta)

    resumen = await cfg.cargar_desde_yaml(db, ruta, empresa_id=empresa.empresa_id)
    assert resumen["map_departamento"] == 1
    assert (await cfg.centro_de_costo(db, empresa.empresa_id))["Direccion"] == "ADMIN"


async def test_dias_de_vacaciones_por_antiguedad(db: AsyncSession) -> None:
    from app.models.configuracion_fiscal import TablaVacaciones

    db.add(TablaVacaciones(anios_antiguedad=1, dias=12))
    db.add(TablaVacaciones(anios_antiguedad=5, dias=20))
    await db.commit()

    assert await cfg.dias_de_vacaciones(db, 1) == 12
    assert await cfg.dias_de_vacaciones(db, 5) == 20
    # Una antigüedad entre dos renglones toma el mayor que no la excede: el art. 76 crece cada
    # cinco años después del quinto, así que buscar el renglón exacto fallaría con 7 años.
    assert await cfg.dias_de_vacaciones(db, 7) == 20
    assert await cfg.dias_de_vacaciones(db, 0) is None


async def test_recargar_con_otro_valor_limpia_la_confirmacion(db: AsyncSession, tmp_path: Path) -> None:
    """Un valor distinto es un valor nuevo: necesita confirmación nueva. Si no, corregir una
    cifra en el YAML la activaría sin que nadie la mirara."""
    ruta = tmp_path / "param.yaml"
    ruta.write_text(
        "param_fiscal:\n  - ejercicio: 2026\n    clave: UMA_DIARIA\n    valor: '117.31'\n"
        "    vigencia_desde: 2026-02-01\n    vigencia_hasta: null\n    fuente: 'INEGI 2026'\n",
        encoding="utf-8")
    await cfg.cargar_desde_yaml(db, ruta)

    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None
    fila.confirmado_por = "uid-prueba"
    fila.confirmado_en = datetime(2026, 8, 6, 12, 0, 0)
    await db.commit()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) == Decimal("117.31")

    # Misma clave y misma vigencia, otra cifra: la confirmación anterior ya no vale para ella.
    ruta.write_text(
        "param_fiscal:\n  - ejercicio: 2026\n    clave: UMA_DIARIA\n    valor: '118.00'\n"
        "    vigencia_desde: 2026-02-01\n    vigencia_hasta: null\n    fuente: 'INEGI 2026 (fe de erratas)'\n",
        encoding="utf-8")
    await cfg.cargar_desde_yaml(db, ruta)

    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) is None
    propuesto = await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 1))
    assert propuesto is not None
    assert propuesto.valor == Decimal("118.00")
    # Solo el cambio de cifra limpia la confirmación; recargar lo mismo no la tira.
    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None
    fila.confirmado_por = "uid-prueba"
    fila.confirmado_en = datetime(2026, 8, 6, 12, 0, 0)
    await db.commit()
    await cfg.cargar_desde_yaml(db, ruta)
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) == Decimal("118.00")


async def test_dos_tramos_abiertos_para_la_misma_clave_se_rechazan(db: AsyncSession, tmp_path: Path) -> None:
    """El escenario que MySQL no puede impedir en el esquema (no hay restricciones de
    exclusión como en Postgres): alguien captura el salario mínimo de 2027 y teclea mal el
    año — `vigencia_desde: 2026-06-15` en vez de `2027-01-01`, con `vigencia_hasta` nulo.
    Quedarían dos tramos abiertos para la misma clave y toda nómina pagada entre el 15 de
    junio y el 31 de diciembre de 2026 tomaría el valor equivocado, sin error y sin rastro.
    Se rechaza en la escritura.
    """
    db.add(_param("SALARIO_MINIMO_GENERAL", "315.040000", date(2026, 1, 1), confirmado=True))
    await db.commit()

    con_typo = tmp_path / "typo.yaml"
    con_typo.write_text(
        "param_fiscal:\n  - ejercicio: 2027\n    clave: SALARIO_MINIMO_GENERAL\n    valor: '340.20'\n"
        "    vigencia_desde: 2026-06-15\n    vigencia_hasta: null\n    fuente: 'DOF 2026 (hipotetico)'\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="solapa"):
        await cfg.cargar_desde_yaml(db, con_typo)

    # Ni se escribió la fila mala ni se tocó la buena.
    total = await db.scalar(select(func.count()).select_from(ParamFiscal))
    assert total == 1
    assert await cfg.valor_vigente(db, "SALARIO_MINIMO_GENERAL", date(2026, 7, 1)) == Decimal("315.040000")
    assert await cfg.valor_vigente(db, "SALARIO_MINIMO_GENERAL", date(2026, 12, 31)) == Decimal("315.040000")

    # La salida es cerrar el tramo anterior explícitamente, en el mismo archivo.
    corregido = tmp_path / "corregido.yaml"
    corregido.write_text(
        "param_fiscal:\n  - ejercicio: 2026\n    clave: SALARIO_MINIMO_GENERAL\n    valor: '315.04'\n"
        "    vigencia_desde: 2026-01-01\n    vigencia_hasta: 2026-12-31\n    fuente: 'DOF 09-12-2025'\n"
        "  - ejercicio: 2027\n    clave: SALARIO_MINIMO_GENERAL\n    valor: '340.20'\n"
        "    vigencia_desde: 2027-01-01\n    vigencia_hasta: null\n    fuente: 'DOF 2026 (hipotetico)'\n",
        encoding="utf-8")
    resumen = await cfg.cargar_desde_yaml(db, corregido)
    assert resumen["param_fiscal"] == 2

    # 2026 sigue confirmado (su cifra no cambió); 2027 entra como propuesta y no calcula.
    assert await cfg.valor_vigente(db, "SALARIO_MINIMO_GENERAL", date(2026, 12, 31)) == Decimal("315.040000")
    assert await cfg.valor_vigente(db, "SALARIO_MINIMO_GENERAL", date(2027, 6, 1)) is None
    propuesto = await cfg.valor_propuesto(db, "SALARIO_MINIMO_GENERAL", date(2027, 6, 1))
    assert propuesto is not None
    assert propuesto.valor == Decimal("340.20")
