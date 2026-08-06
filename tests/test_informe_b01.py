"""B-01 · Nómina agrupada por catálogo SAT.

La diferencia esencial con B-02 (B-01.R1): las columnas de tipo se generan desde el
**catálogo**, no desde los datos, con cero cuando no hay movimiento. Eso hace el informe
comparable entre periodos, que es lo que exige una póliza contable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b01_catalogo_sat as b01
from tests import factories
from tests.helpers_nomina import insertar_nomina  # helper compartido; ver nota del paso 6


def _p(**kw: object) -> b01.Parametros:
    base: dict[str, object] = {"fecha_desde": date(2026, 6, 1), "fecha_hasta": date(2026, 7, 31)}
    base.update(kw)
    return b01.Parametros(**base)  # type: ignore[arg-type]


def _titulos(resultado: object) -> list[str]:
    return [c.titulo for c in resultado.columnas]  # type: ignore[attr-defined]


async def test_columnas_vienen_del_catalogo_no_de_los_datos(db: AsyncSession) -> None:
    """El corazón de B-01.R1: un tipo que NO está en los datos igual tiene su columna."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111",
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")])

    resultado = await b01.consultar(db, empresa.empresa_id, _p())
    titulos = _titulos(resultado)

    # El tipo 002 (aguinaldo) no aparece en los datos y sí debe tener columna.
    assert any(t.startswith("P 002") for t in titulos), titulos
    # Y muchas columnas: el catálogo completo, no las dos del comprobante.
    dinamicas = [t for t in titulos if t.startswith(("P ", "D ", "O "))]
    assert len(dinamicas) > 100, len(dinamicas)


async def test_celda_sin_movimiento_es_cero_no_vacio(db: AsyncSession) -> None:
    """R-T7. Un nulo en columna de importe rompe cualquier suma en hoja de cálculo."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="22222222-2222-2222-2222-222222222222",
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")])

    resultado = await b01.consultar(db, empresa.empresa_id, _p())
    titulos = _titulos(resultado)
    indice_002 = next(i for i, t in enumerate(titulos) if t.startswith("P 002"))
    assert resultado.filas[0][indice_002] == Decimal("0")


async def test_agrupa_por_tipo_no_por_clave_del_patron(db: AsyncSession) -> None:
    """Dos claves internas distintas del mismo tipo del catálogo caen en la misma columna.
    Es exactamente lo contrario de B-02, y el motivo de que este informe exista."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="33333333-3333-3333-3333-333333333333",
                          percepciones=[("001", "001", "Sueldo", "5000.00", "0.00"),
                                        ("001", "077", "Sueldo eventual", "3000.00", "0.00")])

    resultado = await b01.consultar(db, empresa.empresa_id, _p())
    titulos = _titulos(resultado)
    indice_001 = next(i for i, t in enumerate(titulos) if t.startswith("P 001"))
    assert resultado.filas[0][indice_001] == Decimal("8000.00")


async def test_solo_tipos_con_movimiento_reduce_y_avisa(db: AsyncSession) -> None:
    """B-01.R2: al activarlo el informe deja de ser comparable entre periodos, así que
    tiene que decirlo — si no, alguien compara dos meses con columnas distintas."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="44444444-4444-4444-4444-444444444444",
                          percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
                          deducciones=[("002", "045", "ISR", "500.00")])

    completo = await b01.consultar(db, empresa.empresa_id, _p())
    reducido = await b01.consultar(db, empresa.empresa_id, _p(solo_tipos_con_movimiento=True))

    dinamicas_completo = [t for t in _titulos(completo) if t.startswith(("P ", "D ", "O "))]
    dinamicas_reducido = [t for t in _titulos(reducido) if t.startswith(("P ", "D ", "O "))]
    assert len(dinamicas_reducido) < len(dinamicas_completo)
    assert len(dinamicas_reducido) == 2, dinamicas_reducido
    assert any(b.clave == "CONJUNTO_REDUCIDO" for b in reducido.banderas)
    assert not any(b.clave == "CONJUNTO_REDUCIDO" for b in completo.banderas)


async def test_curp_y_nss_se_declaran_sensibles(db: AsyncSession) -> None:
    """El motor enmascara según la marca; el informe solo la declara."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="55555555-5555-5555-5555-555555555555")

    resultado = await b01.consultar(db, empresa.empresa_id, _p())
    por_titulo = {c.titulo: c for c in resultado.columnas}
    assert por_titulo["CURP"].sensible is True
    assert por_titulo["NSS"].sensible is True
    assert por_titulo["RFC empleado"].sensible is False


async def test_subsidio_causado_y_aplicado(db: AsyncSession) -> None:
    """Definiciones de B-00: `subsidio` sale de `subsidio_causado` del otro pago 002, y
    `subsidio_aplicado` de su `importe`."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="66666666-6666-6666-6666-666666666666",
                          otros_pagos=[("002", "035", "Subsidio", "120.00", "200.00")])

    resultado = await b01.consultar(db, empresa.empresa_id, _p())
    titulos = _titulos(resultado)
    fila = resultado.filas[0]
    assert fila[titulos.index("Subsidio causado")] == Decimal("200.00")
    assert fila[titulos.index("Subsidio aplicado")] == Decimal("120.00")


async def test_sin_comprobantes_devuelve_aviso(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    resultado = await b01.consultar(db, empresa.empresa_id, _p(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31)))
    assert resultado.filas == []
    assert resultado.aviso is not None


async def test_orden_de_columnas_es_determinista(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="77777777-7777-7777-7777-777777777777")
    primera = await b01.consultar(db, empresa.empresa_id, _p())
    segunda = await b01.consultar(db, empresa.empresa_id, _p())
    assert _titulos(primera) == _titulos(segunda)
