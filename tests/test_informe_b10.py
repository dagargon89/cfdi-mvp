"""B-10 · Validación de datos del receptor.

Los errores de este informe generan requerimientos del SAT y problemas ante el IMSS, y son
**invisibles en los informes de importes**: todos los demás pueden cuadrar con un NSS mal
capturado.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b10_validacion_receptor as b10
from tests import factories
from tests.helpers_nomina import insertar_nomina


def _p(**kw: object) -> b10.Parametros:
    base = {"fecha_desde": date(2026, 6, 1), "fecha_hasta": date(2026, 7, 31)}
    base.update(kw)
    return b10.Parametros(**base)  # type: ignore[arg-type]


async def _empresa(db: AsyncSession) -> int:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    return empresa.empresa_id


def _claves(resultado: object) -> set[str]:
    titulos = [c.titulo for c in resultado.columnas]  # type: ignore[attr-defined]
    i = titulos.index("Validación")
    return {f[i] for f in resultado.filas}  # type: ignore[attr-defined]


async def test_una_fila_por_hallazgo(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="11111111-1111-1111-1111-111111111111",
        rfc_receptor="XAXX010101000",
        curp="VECJ880326HDFLNS09",
        nss="",
        tipo_regimen="02",
        puesto="",
        departamento="",
    )

    resultado = await b10.consultar(db, eid, _p())
    claves = _claves(resultado)
    assert "NSS_FALTANTE" in claves
    assert "PUESTO_VACIO" in claves
    assert "DEPARTAMENTO_VACIO" in claves
    # Una fila por hallazgo, no una por empleado.
    assert len(resultado.filas) >= 3


async def test_datos_correctos_no_generan_hallazgos(db: AsyncSession) -> None:
    """Si un empleado bien capturado produjera hallazgos, el informe sería ruido.

    `antiguedad="P339W"` (no `P330W`): se verificó con `(fecha_final_pago -
    fecha_inicio_rel_laboral).days` que la antigüedad real entre 2020-01-01 y 2026-06-30 es
    de 2372 días (339 semanas exactas serían 2373, 1 día de diferencia, dentro de la
    tolerancia de dos semanas). `P330W` (2310 días) queda a 62 días de esa fecha —fuera de
    tolerancia— y habría hecho fallar esta prueba con un falso `ANTIGUEDAD_INCONSISTENTE`
    sobre un dato que en realidad está bien capturado. Es el mismo tipo de verificación que
    el dígito verificador del NSS: no se copia un valor de ejemplo sin comprobar que cumple.
    """
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="22222222-2222-2222-2222-222222222222",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        tipo_regimen="02",
        puesto="Auxiliar",
        departamento="Administración",
        sbc="500.00",
        sdi="600.00",
        fecha_inicio_rel_laboral=date(2020, 1, 1),
        antiguedad="P339W",
        banco="002",
        cuenta_bancaria="1234567890",
        percepciones=[("001", "001", "Sueldo", "7500.00", "0.00")],
        dias="15.000",
    )

    resultado = await b10.consultar(db, eid, _p())
    assert resultado.filas == [], _claves(resultado)


async def test_rfc_curp_inconsistente(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="33333333-3333-3333-3333-333333333333",
        rfc_receptor="VECJ880326XXX",
        curp="AAAA880326HDFLNS09",
        nss="12345678903",
    )
    assert "RFC_CURP_INCONSISTENTE" in _claves(await b10.consultar(db, eid, _p()))


async def test_curp_duplicada_y_rfc_duplicado(db: AsyncSession) -> None:
    """Validaciones de conjunto: no se ven mirando un CFDI aislado."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="44444444-4444-4444-4444-444444444441",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
    )
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="44444444-4444-4444-4444-444444444442",
        rfc_receptor="AAAA880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
    )

    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "CURP_DUPLICADA" in claves
    assert "NSS_DUPLICADO" in claves


async def test_datos_cambiantes_entre_periodos(db: AsyncSession) -> None:
    """Un mismo RFC con distinta CURP entre quincenas: error de captura que solo se ve
    comparando periodos."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="55555555-5555-5555-5555-555555555551",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        fecha_pago=date(2026, 6, 30),
        fecha_final_pago=date(2026, 6, 30),
    )
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="55555555-5555-5555-5555-555555555552",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS08",
        nss="12345678903",
        fecha_pago=date(2026, 7, 15),
        fecha_final_pago=date(2026, 7, 15),
    )

    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "DATOS_CAMBIANTES" in claves


async def test_sdi_menor_al_salario_diario_implicito(db: AsyncSession) -> None:
    """El SDI declarado es menor que el sueldo diario que se deduce del propio CFDI."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="66666666-6666-6666-6666-666666666666",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        sbc="500.00",
        sdi="100.00",
        dias="15.000",
        percepciones=[("001", "001", "Sueldo", "7500.00", "0.00")],
    )
    assert "SDI_MENOR_SD_IMPLICITO" in _claves(await b10.consultar(db, eid, _p()))


async def test_fecha_inicio_posterior_al_periodo(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="77777777-7777-7777-7777-777777777777",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        fecha_final_pago=date(2026, 6, 30),
        fecha_inicio_rel_laboral=date(2026, 12, 1),
    )
    assert "FECHA_INICIO_POSTERIOR" in _claves(await b10.consultar(db, eid, _p()))


async def test_banco_sin_cuenta_y_cuenta_invalida(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="88888888-8888-8888-8888-888888888881",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        banco="002",
        cuenta_bancaria="",
    )
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="88888888-8888-8888-8888-888888888882",
        rfc_receptor="AAAA880326XXX",
        curp="AAAA880326HDFLNS09",
        nss="12345678903",
        banco="002",
        cuenta_bancaria="123456789012",
    )

    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "BANCO_SIN_CUENTA" in claves
    assert "CUENTA_INVALIDA" in claves


async def test_severidad_minima_filtra(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="99999999-9999-9999-9999-999999999999",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        puesto="",
        departamento="",
    )

    todas = await b10.consultar(db, eid, _p())
    solo_altas = await b10.consultar(db, eid, _p(severidad_minima="alta"))
    assert "PUESTO_VACIO" in _claves(todas)
    assert "PUESTO_VACIO" not in _claves(solo_altas)


async def test_las_dos_validaciones_de_sbc_diferidas_no_aparecen(db: AsyncSession) -> None:
    """Necesitan UMA y salario mínimo de la fase 3."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        sbc="999999.00",
    )
    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "SBC_SOBRE_TOPE" not in claves
    assert "SBC_BAJO_MINIMO" not in claves


async def test_curp_y_nss_se_declaran_sensibles(db: AsyncSession) -> None:
    """B-10.R2: este informe es el que más datos personales expone, así que el
    enmascaramiento importa más aquí que en ninguno."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="",
    )
    resultado = await b10.consultar(db, eid, _p())
    por_titulo = {c.titulo: c for c in resultado.columnas}
    assert por_titulo["CURP"].sensible is True
    assert por_titulo["NSS"].sensible is True


async def test_sin_comprobantes_devuelve_aviso(db: AsyncSession) -> None:
    eid = await _empresa(db)
    resultado = await b10.consultar(db, eid, _p(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31)))
    assert resultado.filas == [] and resultado.aviso is not None
