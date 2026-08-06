"""Coherencia de las semillas fiscales.

Estas pruebas **no** validan los valores contra la ley (eso lo revisa el dueño del repo con el
`README.md` que esta tarea produce): validan que las semillas sean internamente coherentes,
cargables, y que **ninguna llegue confirmada**. Un factor de exención mal capturado no lo atrapa
una prueba; una semilla contradictoria o autoconfirmada sí.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import configuracion_fiscal as cfg

_RAIZ = Path(__file__).resolve().parent.parent / "config" / "fiscal"


def test_tabla_de_vacaciones_es_monotona_y_arranca_en_doce() -> None:
    """Art. 76 LFT tras la reforma de 2023: 12 días el primer año, y nunca decrece."""
    datos = yaml.safe_load((_RAIZ / "tabla_vacaciones.yaml").read_text(encoding="utf-8"))
    filas = sorted(datos["tabla_vacaciones"], key=lambda f: f["anios_antiguedad"])
    assert filas[0]["anios_antiguedad"] == 1
    assert filas[0]["dias"] == 12
    dias = [f["dias"] for f in filas]
    assert dias == sorted(dias), "los días de vacaciones no pueden decrecer con la antigüedad"
    assert 20 in dias, "el art. 76 llega a 20 días al quinto año"


def test_marcas_de_percepcion_son_coherentes() -> None:
    """Un tipo con base de exención distinta de NINGUNA debe traer factor, y al revés."""
    datos = yaml.safe_load((_RAIZ / "catalogo_percepcion.yaml").read_text(encoding="utf-8"))
    for fila in datos["catalogo_percepcion_marca"]:
        tipo = fila["tipo_percepcion"]
        assert isinstance(tipo, str), f"la clave {tipo!r} debe ser texto, no entero"
        assert len(tipo) == 3, f"la clave {tipo!r} debe tener tres posiciones"
        if fila["base_exencion"] == "NINGUNA":
            assert fila.get("factor_exencion") is None, f"{tipo}: sin base de exención no puede haber factor"
        else:
            assert fila.get("factor_exencion") is not None, f"{tipo}: con base de exención hace falta el factor"
            assert float(fila["factor_exencion"]) > 0, f"{tipo}: el factor debe ser positivo"


def test_separacion_y_jubilacion_no_son_ingreso_ordinario() -> None:
    """B-05.R4: tienen régimen fiscal propio (arts. 95 y 96 LISR) y no se acumulan al ordinario.

    Los cinco códigos están verificados contra el catálogo real de satcfdi
    (`C75b_c_TipoPercepcion`, 44 tipos), no de memoria:
      022 Prima por antigüedad · 023 Pagos por separación · 025 Indemnizaciones
      039 Jubilaciones, pensiones o haberes de retiro · 044 idem en parcialidades
    Los tres primeros caen bajo el art. 95 de la LISR, que los agrupa explícitamente
    ("primas de antigüedad, retiro e indemnizaciones u otros pagos por separación").
    Omitir 025 marcaría las indemnizaciones como ingreso ordinario y **sobreestimaría la
    base anual del ISR** en la columna 11 de B-05.
    """
    datos = yaml.safe_load((_RAIZ / "catalogo_percepcion.yaml").read_text(encoding="utf-8"))
    por_tipo = {f["tipo_percepcion"]: f for f in datos["catalogo_percepcion_marca"]}
    for tipo in ("022", "023", "025", "039", "044"):
        assert tipo in por_tipo, f"falta sembrar el tipo {tipo}"
        assert por_tipo[tipo]["es_ingreso_ordinario"] is False, f"{tipo} no es ingreso ordinario"


def test_todo_parametro_fiscal_declara_su_fuente() -> None:
    """Sin fuente, un revisor no puede verificar el valor: es el requisito que hace la semilla
    auditable, y por eso el cargador lo exige."""
    datos = yaml.safe_load((_RAIZ / "param_fiscal.yaml").read_text(encoding="utf-8"))
    for fila in datos["param_fiscal"]:
        fuente = fila.get("fuente", "")
        assert fuente, f"{fila['clave']}: falta la fuente"
        assert "http" in fuente or any(c.isdigit() for c in fuente), (
            f"{fila['clave']}: la fuente debe citar una liga o una fecha de publicación, no ser genérica")


def test_toda_marca_dudosa_esta_senalada() -> None:
    """Un valor no confirmado lleva `REVISAR` con su tipo, para que la revisión sepa dónde mirar."""
    texto = (_RAIZ / "catalogo_percepcion.yaml").read_text(encoding="utf-8")
    for linea in texto.splitlines():
        if "REVISAR" in linea:
            assert any(c.isdigit() for c in linea), f"la duda debe decir de qué tipo es: {linea!r}"


async def test_las_semillas_se_cargan_y_ninguna_queda_confirmada(db: AsyncSession) -> None:
    """El invariante de la fase, aplicado a las semillas: cargar propone, no activa."""
    await cfg.cargar_desde_yaml(db, _RAIZ / "tabla_vacaciones.yaml")
    await cfg.cargar_desde_yaml(db, _RAIZ / "catalogo_percepcion.yaml")
    resumen = await cfg.cargar_desde_yaml(db, _RAIZ / "param_fiscal.yaml")
    assert resumen["param_fiscal"] > 0

    # La ley se aplica sola (no lleva confirmación); los importes, no.
    assert await cfg.dias_de_vacaciones(db, 1) == 12
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 1)) is None
    propuesto = await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 1))
    assert propuesto is not None
    assert "inegi" in propuesto.fuente.lower()


async def test_las_dos_zonas_de_salario_minimo_estan_sembradas(db: AsyncSession) -> None:
    """Las dos, porque la zona aplicable es configuración de cada empresa y no se puede adivinar."""
    await cfg.cargar_desde_yaml(db, _RAIZ / "param_fiscal.yaml")
    for clave in ("SALARIO_MINIMO_GENERAL", "SALARIO_MINIMO_ZLFN"):
        assert await cfg.valor_propuesto(db, clave, date(2026, 6, 1)) is not None, f"falta sembrar {clave}"
