"""B-03 · Desglose gravado / exento por percepción.

Lo que estas pruebas fijan, en orden de importancia:

1. **Un valor sin confirmar no calcula, y la ausencia nunca es cero.** Con la UMA solo
   propuesta, las cuatro columnas dependientes de configuración salen **vacías** y hay
   **una sola** bandera que dice que basta confirmarla, con su fuente. Un cero en un tope
   de exención produce exenciones falsas.
2. **Una bandera por causa, no una por fila.** Es la lección del colapso de banderas de la
   fase 2: una hoja con decenas de avisos idénticos sepulta los que sí importan.
3. **Cada regla con su gemela negativa.** Una bandera que dispara siempre es peor que no
   tenerla.

La configuración se siembra **con el servicio de la tarea 2** (`cargar_desde_yaml` y
`guardar_param_fiscal`), no con `INSERT` directos: así cada prueba ejercita el camino real,
incluido el invariante de confirmación —que es justo lo que se está probando— y la
validación del `tipo_percepcion` contra `c_TipoPercepcion`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b03_gravado_exento as b03
from app.models.configuracion_fiscal import CatalogoPercepcionMarca, ConfiguracionEmpresa, ParamFiscal
from app.models.enums import OrigenValor, ZonaSalarial
from app.services import configuracion_fiscal as cfg
from tests import factories
from tests.helpers_nomina import insertar_nomina

_DESDE = date(2026, 6, 1)
_HASTA = date(2026, 7, 31)
_PAGO = date(2026, 6, 30)

# Cifras 2026 reales (las de `config/fiscal/param_fiscal.yaml`), para que los topes que
# calculan estas pruebas sean los que producirá la instalación de verdad.
_UMA_DIARIA = "117.31"
_UMA_ANUAL = "42794.64"
_SM_ZLFN = "440.87"

_CONFIRMADO_EN = datetime(2026, 8, 6, 12, 0, 0)
_FUENTE = "INEGI, boletín UMA 2026 (fixture de prueba)"


# --------------------------------------------------------------------------------------
# Siembra de configuración, siempre por el servicio
# --------------------------------------------------------------------------------------


def _yaml_marcas(marcas: list[dict[str, Any]]) -> str:
    """El YAML de `catalogo_percepcion_marca` escrito a mano.

    No se usa `yaml.safe_dump`: `tipo_percepcion` y `factor_exencion` tienen que salir
    **entrecomillados** ('002' no es 2, y un factor sin comillas se lee como float y pierde
    precisión). Volcar un dict deja esa decisión en manos del serializador, que es
    exactamente la trampa que el cargador existe para atrapar.
    """
    renglones = ["catalogo_percepcion_marca:"]
    for marca in marcas:
        renglones.append(f"  - tipo_percepcion: '{marca['tipo']}'")
        renglones.append(f"    es_ingreso_ordinario: {str(marca.get('ordinario', True)).lower()}")
        renglones.append(f"    base_exencion: {marca['base']}")
        if marca.get("factor") is not None:
            renglones.append(f"    factor_exencion: '{marca['factor']}'")
        renglones.append(f"    integra_sbc: {str(marca.get('integra_sbc', False)).lower()}")
        renglones.append(f"    es_provisionable: {str(marca.get('provisionable', False)).lower()}")
        if marca.get("tope_conjunto"):
            renglones.append("    sujeto_a_tope_conjunto: true")
        if marca.get("nota"):
            renglones.append(f"    nota_revision: '{marca['nota']}'")
    return "\n".join(renglones) + "\n"


async def _sembrar_marcas(db: AsyncSession, tmp_path: Path, marcas: list[dict[str, Any]], *, confirmadas: bool = True) -> None:
    ruta = tmp_path / "marcas.yaml"
    ruta.write_text(_yaml_marcas(marcas), encoding="utf-8")
    await cfg.cargar_desde_yaml(db, ruta)
    if not confirmadas:
        return
    for fila in (await db.scalars(select(CatalogoPercepcionMarca))).all():
        fila.confirmado_por = "uid-prueba"
        fila.confirmado_en = _CONFIRMADO_EN
    await db.commit()


async def _sembrar_param(
    db: AsyncSession, clave: str, valor: str, *, confirmado: bool, desde: date = date(2026, 2, 1)
) -> None:
    await cfg.guardar_param_fiscal(
        db, clave=clave, valor=Decimal(valor), vigencia_desde=desde, origen=OrigenValor.SEMILLA, fuente=_FUENTE
    )
    await db.commit()
    if not confirmado:
        return
    fila = await db.get(ParamFiscal, (clave, desde))
    assert fila is not None
    fila.confirmado_por = "uid-prueba"
    fila.confirmado_en = _CONFIRMADO_EN
    await db.commit()


async def _zona(db: AsyncSession, empresa_id: int, zona: ZonaSalarial) -> None:
    db.add(ConfiguracionEmpresa(empresa_id=empresa_id, zona_salarial=zona))
    await db.commit()


# --------------------------------------------------------------------------------------
# Utilidades de lectura del resultado
# --------------------------------------------------------------------------------------


def _columna(resultado: Any, titulo: str) -> int:
    titulos = [c.titulo for c in resultado.columnas]
    assert titulo in titulos, f"falta la columna {titulo!r}; hay {titulos}"
    return titulos.index(titulo)


def _valor(resultado: Any, fila: int, titulo: str) -> Any:
    return resultado.filas[fila][_columna(resultado, titulo)]


def _claves(resultado: Any) -> list[str]:
    return [b.clave for b in resultado.banderas]


def _de_clave(resultado: Any, clave: str) -> list[Any]:
    return [b for b in resultado.banderas if b.clave == clave]


def _p(**extra: Any) -> Any:
    return b03.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA, **extra)


# --------------------------------------------------------------------------------------
# 1-2. El grano y las columnas de datos
# --------------------------------------------------------------------------------------


async def test_una_fila_por_nodo_de_percepcion(db: AsyncSession) -> None:
    """Grano largo, no pivotado: tres percepciones en un CFDI son tres filas."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="11111111-1111-1111-1111-111111111111",
        percepciones=[
            ("001", "001", "Sueldo", "8000.00", "0.00"),
            ("002", "002", "Aguinaldo", "3000.00", "1000.00"),
            ("019", "019", "Horas extra", "250.00", "250.00"),
        ],
        total_percepciones="12500.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert len(resultado.filas) == 3
    tipos = [_valor(resultado, i, "Tipo percepción") for i in range(3)]
    assert tipos == ["001", "002", "019"]
    # El grano largo conserva la clave y el concepto del patrón fila por fila.
    assert _valor(resultado, 1, "Concepto patrón") == "Aguinaldo"
    assert _valor(resultado, 1, "Importe total") == Decimal("4000.00")
    # La descripción sale del catálogo del SAT, no del texto del patrón.
    assert _valor(resultado, 0, "Descripción SAT") is not None


async def test_el_porcentaje_exento_es_sobre_el_importe_total_de_la_fila(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="22222222-2222-2222-2222-222222222222",
        percepciones=[("002", "002", "Aguinaldo", "3000.00", "1000.00")],
        total_percepciones="4000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Importe total") == Decimal("4000.00")
    assert _valor(resultado, 0, "% exento") == Decimal("25")


# --------------------------------------------------------------------------------------
# 3-4. B-03.R1 — el tope por tipo, con la UMA confirmada
# --------------------------------------------------------------------------------------


async def test_tope_uma_dias_es_factor_por_uma_y_el_exceso_lo_que_sobra(db: AsyncSession, tmp_path: Path) -> None:
    """B-03.R1 con `UMA_DIAS`: aguinaldo, 30 días de UMA (art. 93-XIV LISR)."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "002", "base": "UMA_DIAS", "factor": "30"}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="33333333-3333-3333-3333-333333333333",
        percepciones=[("002", "002", "Aguinaldo", "0.00", "4000.00")],
        total_percepciones="4000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    tope = Decimal("30") * Decimal(_UMA_DIARIA)  # 3519.30
    assert _valor(resultado, 0, "Base de exención") == "UMA_DIAS"
    assert _valor(resultado, 0, "UMA aplicable") == Decimal(_UMA_DIARIA)
    assert _valor(resultado, 0, "Tope de exención") == tope
    assert _valor(resultado, 0, "Exceso sobre el tope") == Decimal("4000.00") - tope
    assert "FALTA_UMA" not in _claves(resultado)
    assert "UMA_SIN_CONFIRMAR" not in _claves(resultado)


async def test_el_exceso_es_cero_cuando_el_exento_cabe_en_el_tope(db: AsyncSession, tmp_path: Path) -> None:
    """Gemela negativa de la anterior: `max(0, exento - tope)`, nunca un negativo."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "002", "base": "UMA_DIAS", "factor": "30"}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="44444444-4444-4444-4444-444444444444",
        percepciones=[("002", "002", "Aguinaldo", "0.00", "1000.00")],
        total_percepciones="1000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Exceso sobre el tope") == Decimal("0")
    assert "EXENCION_EXCEDIDA" not in _claves(resultado)


async def test_tope_porcentaje_se_calcula_sobre_el_importe_total(db: AsyncSession, tmp_path: Path) -> None:
    """B-03.R1 con `PORCENTAJE`: horas extra, 50% (art. 93-I LISR)."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "019", "base": "PORCENTAJE", "factor": "50"}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="55555555-5555-5555-5555-555555555555",
        percepciones=[("019", "019", "Horas extra", "600.00", "400.00")],
        total_percepciones="1000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Tope de exención") == Decimal("500.00")
    assert _valor(resultado, 0, "Exceso sobre el tope") == Decimal("0")


async def test_el_factor_porcentaje_esta_en_escala_0_100_no_en_fraccion(db: AsyncSession, tmp_path: Path) -> None:
    """Tratar el `100` como fracción exentaría **cien veces de menos**: el tope de un tipo
    exento al 100% sería el 1% del importe. La convención la fija la semilla de la tarea 3 y
    está documentada junto a la columna del modelo."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "005", "base": "PORCENTAJE", "factor": "100"}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="66666666-6666-6666-6666-666666666666",
        percepciones=[("005", "031", "Fondo ahorro", "0.00", "2000.00")],
        total_percepciones="2000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Tope de exención") == Decimal("2000.00")
    assert _valor(resultado, 0, "Exceso sobre el tope") == Decimal("0")


# --------------------------------------------------------------------------------------
# 5-6. La degradación: propuesta sin confirmar frente a ausencia
# --------------------------------------------------------------------------------------


async def test_uma_propuesta_sin_confirmar_vacia_los_topes_y_deja_una_sola_bandera(
    db: AsyncSession, tmp_path: Path
) -> None:
    """El estado que hoy tiene la instalación real: 5 parámetros y 44 marcas, ninguno
    confirmado. Es la ruta que más importa que quede bien."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=False)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "002", "base": "UMA_DIAS", "factor": "30"}])
    for i, uuid_cfdi in enumerate(("77777777-7777-7777-7777-777777777771", "77777777-7777-7777-7777-777777777772")):
        await insertar_nomina(
            db,
            empresa_id=empresa.empresa_id,
            uuid=uuid_cfdi,
            rfc_receptor=f"XAXX01010100{i}",
            percepciones=[("002", "002", "Aguinaldo", "0.00", "4000.00")],
            total_percepciones="4000.00",
        )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    # Las dos filas siguen ahí y sus columnas de datos, normales.
    assert len(resultado.filas) == 2
    assert _valor(resultado, 0, "Importe exento") == Decimal("4000.00")
    assert _valor(resultado, 0, "% exento") == Decimal("100")
    # Las dependientes de configuración, vacías. Nunca cero.
    for fila in range(2):
        assert _valor(resultado, fila, "Tope de exención") is None
        assert _valor(resultado, fila, "Exceso sobre el tope") is None
        assert _valor(resultado, fila, "UMA aplicable") is None

    # Exactamente UNA bandera, no una por fila, y accionable: dice la fuente y que basta
    # confirmarla.
    avisos = _de_clave(resultado, "UMA_SIN_CONFIRMAR")
    assert len(avisos) == 1
    assert avisos[0].severidad == "alta"
    assert avisos[0].ambito == "informe"
    assert _FUENTE in avisos[0].mensaje
    assert "2" in avisos[0].mensaje, "la bandera tiene que traer el conteo de filas afectadas"
    assert "FALTA_UMA" not in _claves(resultado)


async def test_sin_uma_en_absoluto_la_bandera_es_falta_uma(db: AsyncSession, tmp_path: Path) -> None:
    """Los dos estados piden acciones distintas: capturarla frente a confirmarla."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_marcas(db, tmp_path, [{"tipo": "002", "base": "UMA_DIAS", "factor": "30"}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="88888888-8888-8888-8888-888888888888",
        percepciones=[("002", "002", "Aguinaldo", "0.00", "4000.00")],
        total_percepciones="4000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Tope de exención") is None
    assert _valor(resultado, 0, "UMA aplicable") is None
    faltantes = _de_clave(resultado, "FALTA_UMA")
    assert len(faltantes) == 1
    assert faltantes[0].severidad == "alta"
    assert "UMA_SIN_CONFIRMAR" not in _claves(resultado)


async def test_una_marca_sin_confirmar_no_calcula_el_tope(db: AsyncSession, tmp_path: Path) -> None:
    """El mismo invariante sobre el otro insumo: `factor_exencion` alimenta el cálculo igual
    que la UMA, y son 44 derivaciones del art. 93 hechas a mano."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "002", "base": "UMA_DIAS", "factor": "30"}], confirmadas=False)
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="99999999-9999-9999-9999-999999999999",
        percepciones=[("002", "002", "Aguinaldo", "0.00", "4000.00")],
        total_percepciones="4000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Base de exención") is None
    assert _valor(resultado, 0, "Tope de exención") is None
    avisos = _de_clave(resultado, "MARCA_SIN_CONFIRMAR")
    assert len(avisos) == 1
    assert "002" in avisos[0].ambito
    # La UMA sí está confirmada: no debe salir su bandera.
    assert "FALTA_UMA" not in _claves(resultado)
    assert "UMA_SIN_CONFIRMAR" not in _claves(resultado)


async def test_un_tipo_sin_marca_alguna_emite_falta_marca(db: AsyncSession, tmp_path: Path) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "002", "base": "UMA_DIAS", "factor": "30"}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        percepciones=[("029", "029", "Vales de despensa", "0.00", "500.00")],
        total_percepciones="500.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Tope de exención") is None
    faltantes = _de_clave(resultado, "FALTA_MARCA")
    assert len(faltantes) == 1
    assert "029" in faltantes[0].ambito


# --------------------------------------------------------------------------------------
# La duda declarada: un factor que la propia semilla dice que podría estar mal
# --------------------------------------------------------------------------------------


async def test_una_marca_con_duda_declarada_no_calcula_el_tope(db: AsyncSession, tmp_path: Path) -> None:
    """Los nueve tipos cuyo multiplicador no viene en el CFDI (`90 UMA por año de servicio`,
    `15 UMA diarias`, `1 UMA por domingo`) llevan esa advertencia en `nota_revision`, que es
    un campo de la base. Calcular el tope con el factor tal cual supondría un multiplicador
    de 1: la exención de un trabajador con antigüedad larga saldría muy por debajo y el
    informe lo acusaría de un exceso inexistente."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [{"tipo": "022", "base": "UMA_DIAS", "factor": "90", "ordinario": False, "nota": "el factor 90 es POR CADA ANIO DE SERVICIO"}],
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        percepciones=[("022", "022", "Prima de antiguedad", "0.00", "60000.00")],
        total_percepciones="60000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    # La base sí se informa (es un hecho de la marca confirmada); el número, no.
    assert _valor(resultado, 0, "Base de exención") == "UMA_DIAS"
    assert _valor(resultado, 0, "Tope de exención") is None
    assert _valor(resultado, 0, "Exceso sobre el tope") is None
    dudas = _de_clave(resultado, "MARCA_CON_DUDA_DECLARADA")
    assert len(dudas) == 1
    assert "022" in dudas[0].ambito
    assert "EXENCION_EXCEDIDA" not in _claves(resultado)


async def test_la_bandera_de_duda_declarada_cita_la_nota_en_vez_de_suponerla(
    db: AsyncSession, tmp_path: Path
) -> None:
    """39 de las 44 marcas traen nota y solo nueve la traen por el multiplicador. Afirmar que
    la duda es la del multiplicador manda a resolver la duda equivocada: la del `029` es sobre
    el SBC, la del `005` sobre los requisitos de deducibilidad. La bandera cita el texto."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [{"tipo": "005", "base": "PORCENTAJE", "factor": "100", "nota": "requisitos de deducibilidad del art. 27-XI"}],
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c3",
        percepciones=[("005", "031", "Fondo ahorro", "0.00", "2000.00")],
        total_percepciones="2000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    dudas = _de_clave(resultado, "MARCA_CON_DUDA_DECLARADA")
    assert len(dudas) == 1
    assert "requisitos de deducibilidad del art. 27-XI" in dudas[0].mensaje
    assert "año de servicio" not in dudas[0].mensaje, "no se supone cuál es la duda"


async def test_base_ninguna_con_duda_declarada_sigue_dando_tope_cero(db: AsyncSession, tmp_path: Path) -> None:
    """La duda solo puede bloquear lo que depende del factor, y `NINGUNA` no tiene factor
    (`factor_exencion` es `NULL` y el cargador lo exige así). Vaciar ahí las columnas de tope
    y exceso deja huecos donde no hay nada que capturar — 14 de los 16 tipos `NINGUNA` de la
    semilla traen nota."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [{"tipo": "045", "base": "NINGUNA", "integra_sbc": True, "nota": "el art. 94-VII les da una base propia"}],
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="d4d4d4d4-d4d4-d4d4-d4d4-d4d4d4d4d4d4",
        percepciones=[("045", "045", "Acciones", "5000.00", "1000.00")],
        total_percepciones="6000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Base de exención") == "NINGUNA"
    assert _valor(resultado, 0, "Tope de exención") == Decimal("0")
    assert _valor(resultado, 0, "Exceso sobre el tope") == Decimal("1000.00")
    assert "MARCA_CON_DUDA_DECLARADA" not in _claves(resultado)
    assert len(_de_clave(resultado, "EXENCION_INDEBIDA")) == 1


async def test_una_marca_sin_duda_declarada_si_calcula_el_tope(db: AsyncSession, tmp_path: Path) -> None:
    """Gemela negativa de la anterior: la regla no puede bloquear todos los topes."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "022", "base": "UMA_DIAS", "factor": "90", "ordinario": False}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="cccccccc-cccc-cccc-cccc-cccccccccccc",
        percepciones=[("022", "022", "Prima de antiguedad", "0.00", "60000.00")],
        total_percepciones="60000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Tope de exención") == Decimal("90") * Decimal(_UMA_DIARIA)
    assert "MARCA_CON_DUDA_DECLARADA" not in _claves(resultado)


# --------------------------------------------------------------------------------------
# 7. B-03.R2 — acumulación anual
# --------------------------------------------------------------------------------------


async def test_el_acumulado_anual_excede_el_tope_aunque_ningun_periodo_lo_haga(
    db: AsyncSession, tmp_path: Path
) -> None:
    """B-03.R2, la regla que hace útil el informe: dos pagos de 2000, cada uno muy por
    debajo del tope de 30 UMA (3519.30), suman 4000 y sí lo exceden."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "002", "base": "UMA_DIAS", "factor": "30"}])
    for i, (uuid_cfdi, pago) in enumerate(
        (("dddddddd-dddd-dddd-dddd-ddddddddddd1", date(2026, 6, 30)), ("dddddddd-dddd-dddd-dddd-ddddddddddd2", date(2026, 7, 15)))
    ):
        await insertar_nomina(
            db,
            empresa_id=empresa.empresa_id,
            uuid=uuid_cfdi,
            fecha_pago=pago,
            percepciones=[("002", "002", "Aguinaldo", "0.00", "2000.00")],
            total_percepciones="2000.00",
        )
        assert i in (0, 1)

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    # Ninguna fila sola excede: el exceso por fila es cero.
    assert [_valor(resultado, i, "Exceso sobre el tope") for i in range(2)] == [Decimal("0"), Decimal("0")]
    excedidas = _de_clave(resultado, "EXENCION_EXCEDIDA")
    assert len(excedidas) == 1, "una bandera por (empleado, tipo, ejercicio), no una por fila"
    assert excedidas[0].severidad == "alta"
    assert "XAXX010101000" in excedidas[0].ambito
    assert "2026" in excedidas[0].ambito


async def test_el_acumulado_anual_bajo_el_tope_no_emite_bandera(db: AsyncSession, tmp_path: Path) -> None:
    """Gemela negativa de B-03.R2. Una bandera que dispara siempre es peor que no tenerla."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "002", "base": "UMA_DIAS", "factor": "30"}])
    for uuid_cfdi, pago in (
        ("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee1", date(2026, 6, 30)),
        ("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee2", date(2026, 7, 15)),
    ):
        await insertar_nomina(
            db,
            empresa_id=empresa.empresa_id,
            uuid=uuid_cfdi,
            fecha_pago=pago,
            percepciones=[("002", "002", "Aguinaldo", "0.00", "1500.00")],
            total_percepciones="1500.00",
        )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert "EXENCION_EXCEDIDA" not in _claves(resultado)


async def test_el_acumulado_anual_mira_todo_el_ejercicio_no_solo_el_rango(
    db: AsyncSession, tmp_path: Path
) -> None:
    """El tope es del ejercicio: un pago de febrero cuenta aunque el informe sea de junio.
    Evaluarlo solo contra el rango dejaría pasar el caso que la regla existe para detectar."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "002", "base": "UMA_DIAS", "factor": "30"}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="ffffffff-ffff-ffff-ffff-fffffffffff1",
        fecha_pago=date(2026, 2, 15),
        percepciones=[("002", "002", "Aguinaldo", "0.00", "3000.00")],
        total_percepciones="3000.00",
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="ffffffff-ffff-ffff-ffff-fffffffffff2",
        fecha_pago=date(2026, 6, 30),
        percepciones=[("002", "002", "Aguinaldo", "0.00", "1000.00")],
        total_percepciones="1000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert len(resultado.filas) == 1, "el rango del informe es junio-julio"
    assert _valor(resultado, 0, "Exceso sobre el tope") == Decimal("0")
    assert len(_de_clave(resultado, "EXENCION_EXCEDIDA")) == 1


async def test_un_tipo_porcentual_compara_el_exento_anual_contra_el_importe_anual(
    db: AsyncSession, tmp_path: Path
) -> None:
    """El tope anual de un tipo con base `PORCENTAJE` es proporcional al importe, así que
    tiene que salir del **importe anual**, no de la suma de los topes de las filas impresas.

    El defecto que evita: con un informe de un mes se comparaba el exento de *todo el año*
    contra el tope de *ese mes*, y cualquier tipo porcentual con pagos fuera del rango salía
    marcado como excedido sin estarlo.
    """
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "019", "base": "PORCENTAJE", "factor": "50"}])
    for uuid_cfdi, pago in (
        ("a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a1", date(2026, 3, 15)),
        ("a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a2", date(2026, 6, 30)),
    ):
        await insertar_nomina(
            db,
            empresa_id=empresa.empresa_id,
            uuid=uuid_cfdi,
            fecha_pago=pago,
            percepciones=[("019", "019", "Horas extra", "500.00", "500.00")],
            total_percepciones="1000.00",
        )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert len(resultado.filas) == 1, "el rango del informe es junio-julio"
    # Exento anual 1000 contra tope anual 50% de 2000 = 1000: justo en el límite, no lo excede.
    assert "EXENCION_EXCEDIDA" not in _claves(resultado)


async def test_sin_valor_al_cierre_del_ejercicio_no_se_inventa_un_tope_anual(
    db: AsyncSession, tmp_path: Path
) -> None:
    """El tope anual se resuelve con el valor vigente al **cierre** del ejercicio. Si ese
    tramo no existe, la comparación anual no se hace y la bandera lo dice, en vez de tomar
    cero por tope y acusar de un exceso a todos los empleados del informe."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    # Tramo cerrado el 30 de junio: la fila del 30 de junio sí tiene UMA, el 31 de diciembre no.
    await cfg.guardar_param_fiscal(
        db,
        clave="UMA_DIARIA",
        valor=Decimal(_UMA_DIARIA),
        vigencia_desde=date(2026, 2, 1),
        vigencia_hasta=date(2026, 6, 30),
        origen=OrigenValor.SEMILLA,
        fuente=_FUENTE,
    )
    await db.commit()
    fila = await db.get(ParamFiscal, ("UMA_DIARIA", date(2026, 2, 1)))
    assert fila is not None
    fila.confirmado_por = "uid-prueba"
    fila.confirmado_en = _CONFIRMADO_EN
    await db.commit()
    await _sembrar_marcas(db, tmp_path, [{"tipo": "002", "base": "UMA_DIAS", "factor": "30"}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="b3b3b3b3-b3b3-b3b3-b3b3-b3b3b3b3b3b3",
        fecha_pago=date(2026, 6, 30),
        percepciones=[("002", "002", "Aguinaldo", "0.00", "9000.00")],
        total_percepciones="9000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    # La fila sí tiene tope (la UMA existe a su fecha de pago) y lo excede.
    assert _valor(resultado, 0, "Tope de exención") == Decimal("30") * Decimal(_UMA_DIARIA)
    excedidas = _de_clave(resultado, "EXENCION_EXCEDIDA")
    assert len(excedidas) == 1
    assert "no se pudo comparar contra el tope anual" in excedidas[0].mensaje


# --------------------------------------------------------------------------------------
# El tope conjunto de previsión social (penúltimo párrafo del art. 93)
# --------------------------------------------------------------------------------------


async def test_el_tope_conjunto_de_prevision_social_se_evalua_sobre_la_suma_anual(
    db: AsyncSession, tmp_path: Path
) -> None:
    """Los seis tipos afectados llevan `PORCENTAJE 100` (la exención en bruto), así que su
    tope por tipo nunca se excede. El límite real es la **suma** anual contra 1 UMA anual, y
    se lee del dato (`sujeto_a_tope_conjunto`), no de una lista escrita en el programa."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [
            {"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
            {"tipo": "034", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
        ],
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1",
        percepciones=[
            ("029", "029", "Vales de despensa", "0.00", "30000.00"),
            ("034", "034", "Utiles escolares", "0.00", "20000.00"),
        ],
        total_percepciones="50000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    # Ninguno de los dos excede su tope por tipo (100% del importe).
    assert [_valor(resultado, i, "Exceso sobre el tope") for i in range(2)] == [Decimal("0"), Decimal("0")]
    # Clave propia, no `EXENCION_EXCEDIDA`: el exceso de B-03.R2 es comprobable contra un tope
    # de la ley y este es explícitamente condicional (no se evalúa la precondición de 7 UMA).
    # Si hubiera que distinguirlos leyendo la prosa del mensaje —como hacía esta prueba—, el
    # usuario que filtra la hoja `Banderas` tampoco podría.
    conjuntas = _de_clave(resultado, "TOPE_CONJUNTO_EXCEDIDO")
    assert len(conjuntas) == 1, "una bandera por (empleado, ejercicio)"
    assert "XAXX010101000" in conjuntas[0].ambito
    assert "EXENCION_EXCEDIDA" not in _claves(resultado)


async def test_el_tope_conjunto_se_evalua_aunque_las_marcas_traigan_duda_declarada(
    db: AsyncSession, tmp_path: Path
) -> None:
    """**Los seis tipos sujetos al tope conjunto traen los seis `nota_revision` en la semilla
    real**, así que esta es la única configuración que existe en producción — y era la que
    ninguna prueba cubría.

    El tope conjunto **no necesita** el `factor_exencion` dudoso: suma `importe_exento` y lo
    compara contra 1 UMA anual. Hacer que la duda sobre el factor apague también esta
    comprobación dejaba inerte la única protección contra el "exentar de más" de esos seis
    tipos, y encima en silencio: la bandera que sí salía hablaba de su tope por tipo, que con
    `PORCENTAJE 100` es inexcedible por construcción.
    """
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [
            {
                "tipo": "029",
                "base": "PORCENTAJE",
                "factor": "100",
                "tope_conjunto": True,
                "nota": "la exclusion del SBC es parcial (40% del salario minimo diario)",
            },
            {
                "tipo": "034",
                "base": "PORCENTAJE",
                "factor": "100",
                "tope_conjunto": True,
                "nota": "la analogia con beca es mia, no del texto",
            },
        ],
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="d3d3d3d3-d3d3-d3d3-d3d3-d3d3d3d3d3d3",
        percepciones=[
            ("029", "029", "Vales de despensa", "0.00", "30000.00"),
            ("034", "034", "Utiles escolares", "0.00", "20000.00"),
        ],
        total_percepciones="50000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    # La duda sí apaga el tope **por tipo**, que es lo que depende del factor.
    assert _valor(resultado, 0, "Tope de exención") is None
    assert len(_de_clave(resultado, "MARCA_CON_DUDA_DECLARADA")) == 2
    # Pero no el tope conjunto, que no depende del factor.
    conjuntas = _de_clave(resultado, "TOPE_CONJUNTO_EXCEDIDO")
    assert len(conjuntas) == 1
    assert "XAXX010101000" in conjuntas[0].ambito


async def test_el_tope_conjunto_suma_los_tipos_pagados_fuera_del_rango(
    db: AsyncSession, tmp_path: Path
) -> None:
    """El tope conjunto es una suma **entre tipos** y **anual**: un tipo pagado en enero
    consume la misma UMA anual que uno pagado en junio, aunque el informe sea de junio.

    Es la misma clase de defecto que B-03.R2 (comparar un acumulado anual contra un tope del
    rango), solo que aplicado al **conjunto de tipos** en vez de a los importes: la consulta
    agregada tiene que cubrir todos los tipos con `sujeto_a_tope_conjunto` del ejercicio, no
    solo los que aparecen en las filas impresas.
    """
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [
            {"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
            {"tipo": "034", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
        ],
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="e3e3e3e3-e3e3-e3e3-e3e3-e3e3e3e3e3e3",
        fecha_pago=date(2026, 1, 31),
        percepciones=[("029", "029", "Vales de despensa", "0.00", "30000.00")],
        total_percepciones="30000.00",
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="f3f3f3f3-f3f3-f3f3-f3f3-f3f3f3f3f3f3",
        fecha_pago=date(2026, 6, 30),
        percepciones=[("034", "034", "Utiles escolares", "0.00", "20000.00")],
        total_percepciones="20000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert len(resultado.filas) == 1, "el rango del informe es junio-julio"
    conjuntas = _de_clave(resultado, "TOPE_CONJUNTO_EXCEDIDO")
    assert len(conjuntas) == 1
    assert "50000" in conjuntas[0].mensaje


async def test_el_filtro_por_tipo_no_apaga_el_tope_conjunto(db: AsyncSession, tmp_path: Path) -> None:
    """Pedir el informe de un solo tipo acota qué filas se imprimen, no contra qué se compara
    la suma del art. 93."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [
            {"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
            {"tipo": "034", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
        ],
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="a4a4a4a4-a4a4-a4a4-a4a4-a4a4a4a4a4a4",
        percepciones=[
            ("029", "029", "Vales de despensa", "0.00", "30000.00"),
            ("034", "034", "Utiles escolares", "0.00", "20000.00"),
        ],
        total_percepciones="50000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p(tipo_percepcion="034"))

    assert len(resultado.filas) == 1
    assert len(_de_clave(resultado, "TOPE_CONJUNTO_EXCEDIDO")) == 1


async def test_sin_uma_anual_el_tope_conjunto_avisa_que_no_lo_evaluo(
    db: AsyncSession, tmp_path: Path
) -> None:
    """La única protección contra el "exentar de más" de esos seis tipos no puede dejar de
    correr en silencio."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(
        db, tmp_path, [{"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True}]
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="b4b4b4b4-b4b4-b4b4-b4b4-b4b4b4b4b4b4",
        percepciones=[("029", "029", "Vales de despensa", "0.00", "30000.00")],
        total_percepciones="30000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    faltantes = _de_clave(resultado, "FALTA_UMA_ANUAL")
    assert len(faltantes) == 1
    assert faltantes[0].severidad == "alta"


async def test_una_marca_sujeta_al_tope_conjunto_sin_confirmar_avisa_aunque_no_se_imprima(
    db: AsyncSession, tmp_path: Path
) -> None:
    """**Tercera vía del mismo error, y la razón de que el aviso no cuelgue de las filas.**

    El alcance del tope conjunto se calcula con las marcas **confirmadas**, y eso está bien:
    calcular con una marca sin confirmar violaría el invariante. Pero *decidir si hay que
    avisar* no necesita la marca confirmada — es el mismo razonamiento que ya falló dos veces
    en este módulo. Aquí `034` está sujeta al tope, sin confirmar y pagada **fuera del rango**,
    así que no imprime fila: si el aviso viviera en `MARCA_SIN_CONFIRMAR` (que se alimenta de
    las filas impresas) el informe se quedaría mudo mientras la suma real (50 000) pasa de 1
    UMA anual.
    """
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [{"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True}],
        confirmadas=True,
    )
    # `034` se carga después y se deja SIN confirmar.
    await _sembrar_marcas(
        db,
        tmp_path,
        [{"tipo": "034", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True}],
        confirmadas=False,
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="e5e5e5e5-e5e5-e5e5-e5e5-e5e5e5e5e5e1",
        fecha_pago=date(2026, 6, 30),
        percepciones=[("029", "029", "Vales de despensa", "0.00", "30000.00")],
        total_percepciones="30000.00",
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="e5e5e5e5-e5e5-e5e5-e5e5-e5e5e5e5e5e2",
        fecha_pago=date(2026, 1, 31),
        percepciones=[("034", "034", "Utiles escolares", "0.00", "20000.00")],
        total_percepciones="20000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    avisos = _de_clave(resultado, "TOPE_CONJUNTO_SIN_EVALUAR")
    assert len(avisos) == 1
    assert avisos[0].severidad == "alta"
    assert avisos[0].ambito == "ejercicio:2026"
    assert "034" in avisos[0].mensaje


async def test_con_nada_confirmado_el_tope_conjunto_avisa_igual(db: AsyncSession, tmp_path: Path) -> None:
    """El estado de producción de hoy: 44 marcas, ninguna confirmada. El tipo sujeto al tope
    se pagó fuera del rango, así que tampoco imprime fila."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [
            {"tipo": "001", "base": "NINGUNA", "integra_sbc": True},
            {"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
        ],
        confirmadas=False,
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="f5f5f5f5-f5f5-f5f5-f5f5-f5f5f5f5f5f1",
        fecha_pago=date(2026, 1, 31),
        percepciones=[("029", "029", "Vales de despensa", "0.00", "60000.00")],
        total_percepciones="60000.00",
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="f5f5f5f5-f5f5-f5f5-f5f5-f5f5f5f5f5f2",
        fecha_pago=date(2026, 6, 30),
        percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
        total_percepciones="8000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert len(_de_clave(resultado, "TOPE_CONJUNTO_SIN_EVALUAR")) == 1


async def test_el_filtro_por_tipo_no_esconde_el_aviso_del_tope_conjunto(
    db: AsyncSession, tmp_path: Path
) -> None:
    """Misma vía, por el filtro en vez de por el rango."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [
            {"tipo": "001", "base": "NINGUNA", "integra_sbc": True},
            {"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
        ],
        confirmadas=False,
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="a6a6a6a6-a6a6-a6a6-a6a6-a6a6a6a6a6a6",
        percepciones=[
            ("001", "001", "Sueldo", "8000.00", "0.00"),
            ("029", "029", "Vales de despensa", "0.00", "60000.00"),
        ],
        total_percepciones="68000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p(tipo_percepcion="001"))

    assert len(resultado.filas) == 1
    assert len(_de_clave(resultado, "TOPE_CONJUNTO_SIN_EVALUAR")) == 1


async def test_con_todo_confirmado_no_hay_aviso_de_tope_conjunto_sin_evaluar(
    db: AsyncSession, tmp_path: Path
) -> None:
    """Gemela negativa: el aviso es sobre lo que **no** se pudo evaluar. Si todo está
    confirmado, el tope se evalúa y el aviso sobra."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db, tmp_path, [{"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True}]
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="b6b6b6b6-b6b6-b6b6-b6b6-b6b6b6b6b6b6",
        percepciones=[("029", "029", "Vales de despensa", "0.00", "60000.00")],
        total_percepciones="60000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert "TOPE_CONJUNTO_SIN_EVALUAR" not in _claves(resultado)
    assert len(_de_clave(resultado, "TOPE_CONJUNTO_EXCEDIDO")) == 1


async def test_una_marca_sujeta_al_tope_sin_importes_no_genera_ruido(
    db: AsyncSession, tmp_path: Path
) -> None:
    """Gemela negativa del aviso: solo se avisa de lo que de verdad quedó sin sumar. Una
    bandera que sale siempre no la lee nadie.

    **El `029` se paga, pero íntegramente gravado.** Es a propósito: la primera versión de esta
    prueba no lo incluía en absoluto, y entonces el tipo ni siquiera aparecía en el acumulado —
    quitar la condición `exento > 0` no cambiaba nada y la prueba sobrevivía a esa mutación sin
    proteger la condición que dice proteger. Con un renglón presente y en cero, la única forma
    de que no salga el aviso es que la condición esté.
    """
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [
            {"tipo": "001", "base": "NINGUNA", "integra_sbc": True},
            {"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
        ],
        confirmadas=False,
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="c6c6c6c6-c6c6-c6c6-c6c6-c6c6c6c6c6c6",
        percepciones=[
            ("001", "001", "Sueldo", "8000.00", "0.00"),
            ("029", "029", "Vales de despensa", "5000.00", "0.00"),
        ],
        total_percepciones="13000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert "TOPE_CONJUNTO_SIN_EVALUAR" not in _claves(resultado)


async def test_un_empleado_sin_filas_en_el_rango_no_se_pierde_del_tope_conjunto(
    db: AsyncSession, tmp_path: Path
) -> None:
    """Cuarta vía: el empleado cuyos pagos de previsión social caen **todos** fuera del rango.

    No lleva bandera propia —el informe no habla de él, no hay ninguna fila suya que mirar—
    pero tampoco desaparece: se cuenta en una bandera colapsada por ejercicio que dice cuántos
    son y que basta ampliar el rango. Callarlo sería el mismo silencio que costó C2.
    """
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [
            {"tipo": "001", "base": "NINGUNA", "integra_sbc": True},
            {"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
        ],
    )
    # Este empleado sí sale en el informe y no excede nada.
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="d6d6d6d6-d6d6-d6d6-d6d6-d6d6d6d6d6d1",
        rfc_receptor="XAXX010101000",
        fecha_pago=date(2026, 6, 30),
        percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
        total_percepciones="8000.00",
    )
    # Este excede el tope conjunto, pero todos sus pagos caen fuera del rango del informe.
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="d6d6d6d6-d6d6-d6d6-d6d6-d6d6d6d6d6d2",
        rfc_receptor="XEXX010101000",
        fecha_pago=date(2026, 1, 31),
        percepciones=[("029", "029", "Vales de despensa", "0.00", "60000.00")],
        total_percepciones="60000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert [f[_columna(resultado, "RFC empleado")] for f in resultado.filas] == ["XAXX010101000"]
    # Nadie del informe excede: ninguna bandera individual.
    assert "TOPE_CONJUNTO_EXCEDIDO" not in _claves(resultado)
    fuera = _de_clave(resultado, "TOPE_CONJUNTO_EXCEDIDO_FUERA_DEL_INFORME")
    assert len(fuera) == 1
    assert fuera[0].ambito == "ejercicio:2026"
    assert "1" in fuera[0].mensaje


async def test_la_marca_sin_confirmar_avisa_de_su_tope_conjunto(db: AsyncSession, tmp_path: Path) -> None:
    """La frase que distingue una marca sin confirmar cualquiera de una sujeta al tope
    conjunto: en la segunda, lo que no se evalúa no es solo su tope por tipo —inexcedible con
    `PORCENTAJE 100`— sino la única comprobación que puede detectar el exceso."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [
            {"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
            {"tipo": "005", "base": "PORCENTAJE", "factor": "100"},
        ],
        confirmadas=False,
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="e6e6e6e6-e6e6-e6e6-e6e6-e6e6e6e6e6e6",
        percepciones=[
            ("029", "029", "Vales de despensa", "0.00", "1000.00"),
            ("005", "031", "Fondo ahorro", "0.00", "1000.00"),
        ],
        total_percepciones="2000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    por_ambito = {b.ambito: b for b in _de_clave(resultado, "MARCA_SIN_CONFIRMAR")}
    assert "tope conjunto" in por_ambito["tipo:029"].mensaje
    # Y su gemela negativa: el 005 está exceptuado, así que la frase no debe salir.
    assert "tope conjunto" not in por_ambito["tipo:005"].mensaje


async def test_el_tope_conjunto_no_dispara_por_debajo_de_una_uma_anual(db: AsyncSession, tmp_path: Path) -> None:
    """Gemela negativa del tope conjunto."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db, tmp_path, [{"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True}]
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1",
        percepciones=[("029", "029", "Vales de despensa", "0.00", "5000.00")],
        total_percepciones="5000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert "TOPE_CONJUNTO_EXCEDIDO" not in _claves(resultado)


async def test_un_tipo_exceptuado_del_tope_conjunto_no_suma_en_el(db: AsyncSession, tmp_path: Path) -> None:
    """El último párrafo del art. 93 exceptúa, entre otros, el fondo de ahorro. Meterlo en la
    suma haría saltar la bandera en una nómina perfectamente correcta — y la lista de
    exceptuados tampoco se escribe en el programa: sale de la misma columna.

    **Hay un tipo con `sujeto_a_tope_conjunto` en la misma nómina a propósito.** Sin él, el
    conjunto de tipos sujetos al tope estaría vacío y la comprobación ni siquiera correría:
    la prueba pasaría igual con un informe que ignorase la columna por completo (se verificó
    mutando `_banderas_de_tope_conjunto` para que sumara todos los tipos — la primera versión
    de esta prueba sobrevivió a esa mutación). Con el `029` presente y por debajo del tope, la
    única forma de que no salte la bandera es que el `005` de verdad no sume.
    """
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "UMA_ANUAL", _UMA_ANUAL, confirmado=True)
    await _sembrar_marcas(
        db,
        tmp_path,
        [
            {"tipo": "005", "base": "PORCENTAJE", "factor": "100"},
            {"tipo": "029", "base": "PORCENTAJE", "factor": "100", "tope_conjunto": True},
        ],
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1",
        percepciones=[
            ("005", "031", "Fondo ahorro", "0.00", "50000.00"),
            ("029", "029", "Vales de despensa", "0.00", "1000.00"),
        ],
        total_percepciones="51000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    # 50000 + 1000 pasarían de 1 UMA anual (42794.64); solo 1000 está sujeto al tope.
    assert "TOPE_CONJUNTO_EXCEDIDO" not in _claves(resultado)


# --------------------------------------------------------------------------------------
# 8. B-03.R3 — exención indebida
# --------------------------------------------------------------------------------------


async def test_base_ninguna_con_exento_positivo_es_exencion_indebida(db: AsyncSession, tmp_path: Path) -> None:
    """B-03.R3: hallazgo de auditoría directo. El sueldo no tiene tramo exento."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "001", "base": "NINGUNA", "integra_sbc": True}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="d1d1d1d1-d1d1-d1d1-d1d1-d1d1d1d1d1d1",
        percepciones=[("001", "001", "Sueldo", "7000.00", "1000.00")],
        total_percepciones="8000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    # `NINGUNA` no necesita la UMA para saber que el tope es cero.
    assert _valor(resultado, 0, "Tope de exención") == Decimal("0")
    assert _valor(resultado, 0, "Exceso sobre el tope") == Decimal("1000.00")
    indebidas = _de_clave(resultado, "EXENCION_INDEBIDA")
    assert len(indebidas) == 1
    assert indebidas[0].severidad == "alta"
    assert "001" in indebidas[0].ambito
    # Y **solo** esa: con tope cero, la acumulación anual de B-03.R2 emitiría además una
    # `EXENCION_EXCEDIDA` que describe peor el mismo hallazgo. Dos banderas para un hallazgo
    # es la forma barata de que la hoja deje de leerse.
    assert "EXENCION_EXCEDIDA" not in _claves(resultado)


async def test_base_ninguna_sin_exento_no_emite_bandera(db: AsyncSession, tmp_path: Path) -> None:
    """Gemela negativa de B-03.R3."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "001", "base": "NINGUNA", "integra_sbc": True}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="e1e1e1e1-e1e1-e1e1-e1e1-e1e1e1e1e1e1",
        percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
        total_percepciones="8000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Exceso sobre el tope") == Decimal("0")
    assert "EXENCION_INDEBIDA" not in _claves(resultado)


# --------------------------------------------------------------------------------------
# 9. `SM_DIAS` y la zona salarial
# --------------------------------------------------------------------------------------


async def test_sm_dias_sin_zona_configurada_deja_el_tope_vacio(db: AsyncSession, tmp_path: Path) -> None:
    """`salario_minimo_de_empresa` devuelve `None` **sin mirar los valores** cuando la zona
    no está configurada: el mínimo de la Zona Libre de la Frontera Norte (440.87) es muy
    distinto del general (315.04) y no hay valor por omisión."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "SALARIO_MINIMO_ZLFN", _SM_ZLFN, confirmado=True, desde=date(2026, 1, 1))
    await _sembrar_marcas(db, tmp_path, [{"tipo": "003", "base": "SM_DIAS", "factor": "15"}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="f1f1f1f1-f1f1-f1f1-f1f1-f1f1f1f1f1f1",
        percepciones=[("003", "003", "PTU", "0.00", "9000.00")],
        total_percepciones="9000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Tope de exención") is None
    faltantes = _de_clave(resultado, "FALTA_ZONA_SALARIAL")
    assert len(faltantes) == 1
    assert faltantes[0].severidad == "alta"


async def test_sm_dias_con_zona_zlfn_calcula_sobre_el_minimo_de_frontera(
    db: AsyncSession, tmp_path: Path
) -> None:
    """Gemela positiva: con la zona configurada, el tope sale sobre 440.87."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _zona(db, empresa.empresa_id, ZonaSalarial.ZLFN)
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_param(db, "SALARIO_MINIMO_ZLFN", _SM_ZLFN, confirmado=True, desde=date(2026, 1, 1))
    await _sembrar_marcas(db, tmp_path, [{"tipo": "003", "base": "SM_DIAS", "factor": "15"}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2",
        percepciones=[("003", "003", "PTU", "0.00", "9000.00")],
        total_percepciones="9000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert _valor(resultado, 0, "Tope de exención") == Decimal("15") * Decimal(_SM_ZLFN)
    assert "FALTA_ZONA_SALARIAL" not in _claves(resultado)


# --------------------------------------------------------------------------------------
# 10-12. Contrato de salida
# --------------------------------------------------------------------------------------


async def test_curp_y_nss_son_columnas_sensibles_y_el_informe_no_enmascara(db: AsyncSession) -> None:
    """El motor enmascara, el informe declara (spec §8). Si el informe enmascarara por su
    cuenta, `enmascarar_datos_personales=False` no podría devolver el valor en claro."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b2",
        curp="XXXX800101HCHXXX01",
        nss="12345678901",
        percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
        total_percepciones="8000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    sensibles = {c.titulo for c in resultado.columnas if c.sensible}
    assert sensibles == {"CURP", "NSS"}
    # Valor en claro: el enmascarado lo aplica `app.informes.excel.escribir_libro`.
    assert _valor(resultado, 0, "CURP") == "XXXX800101HCHXXX01"
    assert _valor(resultado, 0, "NSS") == "12345678901"


async def test_ninguna_bandera_menciona_curp_ni_nss(db: AsyncSession, tmp_path: Path) -> None:
    """Ya pasó una vez en B-10 y fue una fuga real: el `ambito` y el `mensaje` de una bandera
    van a una hoja que **no** se enmascara."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _sembrar_param(db, "UMA_DIARIA", _UMA_DIARIA, confirmado=True)
    await _sembrar_marcas(db, tmp_path, [{"tipo": "001", "base": "NINGUNA", "integra_sbc": True}])
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="c2c2c2c2-c2c2-c2c2-c2c2-c2c2c2c2c2c2",
        curp="XXXX800101HCHXXX01",
        nss="12345678901",
        percepciones=[("001", "001", "Sueldo", "7000.00", "1000.00")],
        total_percepciones="8000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert resultado.banderas, "la prueba no vale nada si no hay banderas que revisar"
    for bandera in resultado.banderas:
        texto = f"{bandera.ambito} {bandera.mensaje}"
        assert "XXXX800101HCHXXX01" not in texto
        assert "12345678901" not in texto


async def test_sin_comprobantes_en_el_rango_hay_aviso_y_no_filas(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")

    resultado = await b03.consultar(db, empresa.empresa_id, _p())

    assert resultado.filas == []
    assert resultado.aviso is not None
    # Las columnas se declaran igual: un libro sin encabezados no se puede leer.
    assert [c.titulo for c in resultado.columnas][0] == "UUID"


async def test_el_orden_de_filas_es_determinista_entre_corridas(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="d2d2d2d2-d2d2-d2d2-d2d2-d2d2d2d2d2d2",
        fecha_pago=date(2026, 7, 15),
        percepciones=[("019", "019", "Horas extra", "500.00", "0.00"), ("001", "001", "Sueldo", "8000.00", "0.00")],
        total_percepciones="8500.00",
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="e2e2e2e2-e2e2-e2e2-e2e2-e2e2e2e2e2e2",
        fecha_pago=date(2026, 6, 30),
        percepciones=[("002", "002", "Aguinaldo", "1000.00", "0.00"), ("001", "001", "Sueldo", "8000.00", "0.00")],
        total_percepciones="9000.00",
    )

    primera = await b03.consultar(db, empresa.empresa_id, _p())
    segunda = await b03.consultar(db, empresa.empresa_id, _p())

    huella = [(f[_columna(primera, "UUID")], f[_columna(primera, "Tipo percepción")]) for f in primera.filas]
    assert huella == [(f[_columna(segunda, "UUID")], f[_columna(segunda, "Tipo percepción")]) for f in segunda.filas]
    # Por fecha de pago primero, y dentro del comprobante por tipo del catálogo.
    assert huella == [
        ("e2e2e2e2-e2e2-e2e2-e2e2-e2e2e2e2e2e2", "001"),
        ("e2e2e2e2-e2e2-e2e2-e2e2-e2e2e2e2e2e2", "002"),
        ("d2d2d2d2-d2d2-d2d2-d2d2-d2d2d2d2d2d2", "001"),
        ("d2d2d2d2-d2d2-d2d2-d2d2-d2d2d2d2d2d2", "019"),
    ]


async def test_el_filtro_por_tipo_de_percepcion_acota_las_filas(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="f2f2f2f2-f2f2-f2f2-f2f2-f2f2f2f2f2f2",
        percepciones=[("001", "001", "Sueldo", "8000.00", "0.00"), ("002", "002", "Aguinaldo", "1000.00", "0.00")],
        total_percepciones="9000.00",
    )

    resultado = await b03.consultar(db, empresa.empresa_id, _p(tipo_percepcion="002"))

    assert len(resultado.filas) == 1
    assert _valor(resultado, 0, "Tipo percepción") == "002"


async def test_el_informe_esta_en_el_registro() -> None:
    from app.informes import registro

    assert registro.obtener("B-03") is b03
    assert b03.TIPOS_COMPROBANTE == ("N",)
