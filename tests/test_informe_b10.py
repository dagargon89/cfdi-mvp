"""B-10 · Validación de datos del receptor.

Los errores de este informe generan requerimientos del SAT y problemas ante el IMSS, y son
**invisibles en los informes de importes**: todos los demás pueden cuadrar con un NSS mal
capturado.
"""

from __future__ import annotations

import io
from datetime import date, datetime

import openpyxl
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b10_validacion_receptor as b10, excel, validadores
from app.informes.base import ContextoInforme
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
    """Un mismo RFC con distinto NSS entre quincenas: error de captura que solo se ve
    comparando periodos.

    La prueba usaba antes dos CURP distintas, pero ese caso concreto lo reporta `RFC_DUPLICADO`
    y `DATOS_CAMBIANTES` ya no lo cubre (revisión final: dos claves de severidad alta para un
    solo defecto producían dos filas en un informe cuyo grano es "una fila = algo que
    corregir"). Ver `test_rfc_duplicado_es_la_unica_clave_del_rfc_con_varias_curp`."""
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
        curp="VECJ880326HDFLNS09",
        nss="98765432105",
        fecha_pago=date(2026, 7, 15),
        fecha_final_pago=date(2026, 7, 15),
    )

    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "DATOS_CAMBIANTES" in claves


async def test_rfc_duplicado_es_la_unica_clave_del_rfc_con_varias_curp(db: AsyncSession) -> None:
    """`RFC_DUPLICADO`: un mismo RFC con dos CURP distintas en el rango.

    Doble propósito. (1) Cubre `RFC_DUPLICADO`, que no tenía ninguna prueba: se podía borrar del
    módulo sin que la suite se enterara. (2) Fija la decisión de la revisión final sobre el
    reporte doble: este hecho lo reporta **solo** `RFC_DUPLICADO`, no también `DATOS_CAMBIANTES`.
    """
    eid = await _empresa(db)
    for sufijo, curp, fecha in (
        ("1", "VECJ880326HDFLNS09", date(2026, 6, 30)),
        ("2", "VECJ880326HDFLNS08", date(2026, 7, 15)),
    ):
        await insertar_nomina(
            db,
            empresa_id=eid,
            uuid=f"5555555a-5555-5555-5555-55555555555{sufijo}",
            rfc_receptor="VECJ880326XXX",
            curp=curp,
            nss="12345678903",
            fecha_pago=fecha,
            fecha_final_pago=fecha,
        )

    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "RFC_DUPLICADO" in claves
    assert "DATOS_CAMBIANTES" not in claves, "el mismo defecto no debe generar dos filas"


async def test_rfc_estructura(db: AsyncSession) -> None:
    """El receptor de un CFDI de nómina es siempre persona física: un RFC de persona moral
    (3 letras iniciales) es un error de captura."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a0000001-0000-0000-0000-000000000001",
        rfc_receptor="EKU9003173C9",
        curp="EKUX900317HDFLNS01",
        nss="12345678903",
    )
    assert "RFC_ESTRUCTURA" in _claves(await b10.consultar(db, eid, _p()))


async def test_curp_estructura(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a0000002-0000-0000-0000-000000000002",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326XDFLNS09",  # ni H ni M en la posición del sexo
        nss="12345678903",
    )
    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "CURP_ESTRUCTURA" in claves
    # Con la estructura general mal, las posiciones 12-13 no son fiables: no se marca también
    # CURP_ENTIDAD (regla de aplicabilidad del docstring del módulo).
    assert "CURP_ENTIDAD" not in claves


async def test_curp_entidad(db: AsyncSession) -> None:
    """Estructura correcta pero `ZZ` no es una clave de entidad federativa del RENAPO."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a0000003-0000-0000-0000-000000000003",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HZZLNS09",
        nss="12345678903",
    )
    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "CURP_ENTIDAD" in claves
    assert "CURP_ESTRUCTURA" not in claves


async def test_nss_longitud(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a0000004-0000-0000-0000-000000000004",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="123456789",  # 9 caracteres
    )
    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "NSS_LONGITUD" in claves
    # Luhn sobre una longitud equivocada no es significativo y no se evalúa.
    assert "NSS_DIGITO_VERIFICADOR" not in claves


async def test_nss_digito_verificador(db: AsyncSession) -> None:
    """11 dígitos exactos, pero el dígito verificador de Luhn no cuadra (`...01` en vez de
    `...03`, verificado en `tests/test_informes_validadores.py`)."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a0000005-0000-0000-0000-000000000005",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678901",
    )
    claves = _claves(await b10.consultar(db, eid, _p()))
    assert "NSS_DIGITO_VERIFICADOR" in claves
    assert "NSS_LONGITUD" not in claves


async def test_sbc_cero(db: AsyncSession) -> None:
    """Un SBC en cero bajo `tipo_regimen='02'` (obligatorio IMSS) es imposible: sin base de
    cotización no hay cuota que enterar."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a0000006-0000-0000-0000-000000000006",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        tipo_regimen="02",
        sbc="0.00",
        sdi="600.00",
    )
    assert "SBC_CERO" in _claves(await b10.consultar(db, eid, _p()))


async def test_sdi_cero(db: AsyncSession) -> None:
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a0000007-0000-0000-0000-000000000007",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        sbc="500.00",
        sdi="0.00",
    )
    assert "SDI_CERO" in _claves(await b10.consultar(db, eid, _p()))


async def test_sdi_menor_sbc(db: AsyncSession) -> None:
    """B-10.R1: severidad **media**, no alta. Un SDI algo menor que el SBC es teóricamente
    normal (bases distintas); por debajo del 80% ya es sospechoso de captura."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a0000008-0000-0000-0000-000000000008",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        sbc="1000.00",
        sdi="700.00",  # 70% del SBC, por debajo del umbral de 80%
        dias="15.000",
        percepciones=[("001", "001", "Sueldo", "1000.00", "0.00")],
    )
    resultado = await b10.consultar(db, eid, _p())
    titulos = [c.titulo for c in resultado.columnas]
    fila = next(f for f in resultado.filas if f[titulos.index("Validación")] == "SDI_MENOR_SBC")
    assert fila[titulos.index("Severidad")] == "media"


async def test_sdi_no_menor_al_80_por_ciento_del_sbc_no_dispara(db: AsyncSession) -> None:
    """La otra mitad de la prueba anterior: sin ella, una comparación invertida (o un umbral
    puesto al revés) pasaría igual y no protegería nada."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a0000009-0000-0000-0000-000000000009",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        sbc="1000.00",
        sdi="900.00",  # 90% del SBC: menor que el SBC, pero dentro de lo normal
        dias="15.000",
        percepciones=[("001", "001", "Sueldo", "1000.00", "0.00")],
    )
    assert "SDI_MENOR_SBC" not in _claves(await b10.consultar(db, eid, _p()))


async def test_antiguedad_inconsistente(db: AsyncSession) -> None:
    """`@Antigüedad` declarada contra el cálculo desde `fecha_inicio_rel_laboral`, con
    tolerancia de dos semanas para absorber la aproximación de la conversión ISO 8601.

    `P52W` (364 días) contra un alta de 2020-01-01 y un cierre de 2026-06-30 (2372 días reales):
    más de 5 años de diferencia, muy fuera de la tolerancia."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a000000a-0000-0000-0000-00000000000a",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        fecha_final_pago=date(2026, 6, 30),
        fecha_inicio_rel_laboral=date(2020, 1, 1),
        antiguedad="P52W",
    )
    assert "ANTIGUEDAD_INCONSISTENTE" in _claves(await b10.consultar(db, eid, _p()))


async def test_cuenta_extranamente_larga_es_invalida_y_la_correcta_no(db: AsyncSession) -> None:
    """`CUENTA_INVALIDA` en sus dos sentidos, sobre el mismo informe: 12 caracteres no es una
    longitud de cuenta mexicana; 18 (CLABE) sí."""
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a000000b-0000-0000-0000-00000000000b",
        rfc_receptor="VECJ880326XXX",
        curp="VECJ880326HDFLNS09",
        nss="12345678903",
        banco="002",
        cuenta_bancaria="1" * 18,
    )
    assert "CUENTA_INVALIDA" not in _claves(await b10.consultar(db, eid, _p()))


async def test_conteo_de_validaciones_ejecutadas(db: AsyncSession) -> None:
    """**La bandera que hace auditable al propio informe** (§13 del diseño, el mismo
    razonamiento que `identidades_b00.verificar` y su `cotejos`).

    Una validación que no corre no puede fallar, así que `filas == []` no distingue "los datos
    están bien" de "no se validó nada" — y una prueba que asevera eso pasa **más fácil** cuando
    alguien borra una comprobación. El revisor de la fase 2 lo comprobó por mutación: borró siete
    de las 21 validaciones y la suite siguió verde. Con este número aseverado, borrar una la
    rompe.

    El fixture tiene **todos** los campos poblados, así que se ejecutan las 15 validaciones por
    empleado que no son mutuamente excluyentes, más las 3 de conjunto y 1 entre periodos del
    único RFC del rango.
    """
    eid = await _empresa(db)
    await insertar_nomina(
        db,
        empresa_id=eid,
        uuid="a000000c-0000-0000-0000-00000000000c",
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
    bandera = next(b for b in resultado.banderas if b.clave == "VALIDACIONES_EJECUTADAS")
    esperadas = b10.VALIDACIONES_POR_EMPLEADO_COMPLETO + b10.VALIDACIONES_DE_CONJUNTO + b10.VALIDACIONES_ENTRE_PERIODOS_POR_RFC
    assert f"Se ejecutaron {esperadas} validaciones" in bandera.mensaje, bandera.mensaje
    assert bandera.severidad == "baja" and bandera.ambito == "informe"
    # Y el fixture no produce hallazgos: es el mismo camino limpio de
    # `test_datos_correctos_no_generan_hallazgos`, pero ahora con el conteo que lo hace auditable.
    assert resultado.filas == [], _claves(resultado)


async def test_ninguna_celda_de_datos_lleva_curp_ni_nss_completos(db: AsyncSession) -> None:
    """**El hallazgo Critical de la revisión final.** Con `enmascarar_datos_personales=True` las
    columnas `CURP` y `NSS` salían enmascaradas (`****NS09`) pero la columna "Descripción del
    hallazgo" —que no es sensible ni puede serlo sin volverse ilegible— interpolaba el dato crudo:
    6 de 7 filas filtraban la CURP y el NSS completos de cada empleado con algún defecto.

    Escenario real: un usuario con rol `CONSULTA` —el que por diseño solo puede generar
    enmascarado— pide B-10 y lo manda por correo a quien va a corregir las capturas.

    Se recorre el libro **ya escrito**, no el `ResultadoInforme`, porque el enmascaramiento lo
    aplica el motor: es el archivo que circula por correo lo que hay que auditar. Y se recorren
    TODAS las celdas de texto, no solo las declaradas sensibles — verificar el mecanismo no es
    verificar el resultado.

    **Dos comprobaciones, no una, porque la de patrón sola tiene un punto ciego.**
    `dato_personal_en_texto` busca la *estructura* de una CURP o de un NSS, así que no puede ver
    una CURP **mal formada** interpolada en un mensaje — y el mensaje de `CURP_ESTRUCTURA` es
    justamente el que solo puede llevar una CURP mal formada. Un dato personal defectuoso sigue
    siendo un dato personal (una CURP con un carácter equivocado identifica igual a la persona),
    así que se agrega la comprobación por **valor**: ninguna celda de la fila puede contener como
    subcadena la CURP ni el NSS que ese mismo empleado trae en la BD. Esto se descubrió por
    mutación: reintroducir el dato crudo en el mensaje de `CURP_ESTRUCTURA` dejaba pasar la
    versión anterior de esta prueba, que solo hacía la comprobación de patrón.
    """
    eid = await _empresa(db)
    # Cuatro CFDI que entre ellos disparan **todas** las validaciones cuyo mensaje interpolaba el
    # dato: estructura de CURP y de NSS, entidad, inconsistencia RFC/CURP, los tres duplicados y
    # `DATOS_CAMBIANTES`. Los valores son inventados (regla 12).
    valores_por_empleado = [
        # (uuid, rfc, curp, nss, fecha)
        ("c0000001-0000-0000-0000-000000000001", "VECJ880326XXX", "VECJ880326HDFLNS09", "12345678901", date(2026, 6, 30)),
        ("c0000002-0000-0000-0000-000000000002", "AAAA880326XXX", "VECJ880326HDFLNS09", "12345678901", date(2026, 7, 15)),
        ("c0000003-0000-0000-0000-000000000003", "AAAA880326XXX", "AAAA880326HZZLNS08", "98765432101", date(2026, 7, 31)),
        # CURP mal formada (13 caracteres) y NSS de longitud equivocada: dispara
        # `CURP_ESTRUCTURA`, `RFC_CURP_INCONSISTENTE` y `NSS_LONGITUD`, los tres mensajes que la
        # comprobación de patrón por sí sola no puede auditar.
        ("c0000004-0000-0000-0000-000000000004", "BBBB880326XXX", "MALA880326HDF", "123456789", date(2026, 7, 31)),
    ]
    for uuid_cfdi, rfc, curp, nss, fecha in valores_por_empleado:
        await insertar_nomina(
            db,
            empresa_id=eid,
            uuid=uuid_cfdi,
            rfc_receptor=rfc,
            curp=curp,
            nss=nss,
            fecha_pago=fecha,
            fecha_final_pago=fecha,
            banco="002",
            cuenta_bancaria="123456789012",
        )

    p = _p()
    assert p.enmascarar_datos_personales is True, "el default del informe es enmascarar"
    resultado = await b10.consultar(db, eid, p)
    claves = _claves(resultado)
    # Premisa: si el fixture no dispara estas validaciones, la prueba no comprueba sus mensajes.
    for clave_esperada in ("CURP_ESTRUCTURA", "CURP_ENTIDAD", "RFC_CURP_INCONSISTENTE", "NSS_LONGITUD",
                           "NSS_DIGITO_VERIFICADOR", "CURP_DUPLICADA", "NSS_DUPLICADO", "RFC_DUPLICADO",
                           "DATOS_CAMBIANTES"):
        assert clave_esperada in claves, f"el fixture debe disparar {clave_esperada} para auditar su mensaje"

    ctx = ContextoInforme(
        clave=b10.CLAVE,
        nombre=b10.NOMBRE,
        usuario="consulta@test.mx",
        generado_en=datetime(2026, 8, 6, 12, 0),
        parametros=p.model_dump(mode="json"),
        etl_version=1,
    )
    hoja = openpyxl.load_workbook(io.BytesIO(excel.escribir_libro(resultado, ctx)))["Datos"]

    titulos = [c.titulo for c in resultado.columnas]
    indice_curp, indice_nss = titulos.index("CURP"), titulos.index("NSS")
    # Nunca el valor en el mensaje de una aserción que falla: sería la misma fuga que denuncia.
    fugas: list[str] = []
    for numero_fila, (fila_escrita, fila_cruda) in enumerate(zip(hoja.iter_rows(min_row=2, values_only=True), resultado.filas), start=2):
        crudos = {"CURP": fila_cruda[indice_curp], "NSS": fila_cruda[indice_nss]}
        for indice, valor in enumerate(fila_escrita):
            if validadores.dato_personal_en_texto(valor) is not None:
                fugas.append(f"patrón de {validadores.dato_personal_en_texto(valor)} en '{titulos[indice]}' (fila {numero_fila})")
            if indice in (indice_curp, indice_nss) or not isinstance(valor, str):
                continue
            for tipo, crudo in crudos.items():
                if crudo and str(crudo) in valor:
                    fugas.append(f"valor de {tipo} del propio empleado dentro de '{titulos[indice]}' (fila {numero_fila})")
    assert fugas == [], f"datos personales en la hoja Datos con enmascaramiento activo: {fugas}"


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
