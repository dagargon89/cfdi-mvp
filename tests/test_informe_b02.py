"""B-02 · Nómina agrupada por conceptos del patrón.

Las cuatro reglas que este informe tiene que respetar y que las herramientas comerciales
fallan (según el §B-02 del documento fuente):

- B-02.R1: dos nodos con el mismo (tipo, clave) en un CFDI se SUMAN, no se sobrescriben.
- B-02.R3: la etiqueta lleva prefijo de naturaleza; 'Ajuste al neto' existe como D/004/099
  y como O/999/099 en los datos reales de la empresa 11 y no debe colapsar en una columna.
- B-02.R4 / R-T7: celda sin dato = 0, no vacío.
- B-02.R5: el orden de columnas es determinista entre corridas.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b02_conceptos_patron as b02
from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.enums import EstatusCfdi
from app.models.nomina import Nomina
from tests import factories
from tests.helpers_nomina import insertar_nomina

# Rango de pruebas: todas las nóminas normalizadas de este archivo pagan el 2026-06-30.
_DESDE = date(2026, 6, 1)
_HASTA = date(2026, 7, 31)
# Fecha de emisión dentro de ese mismo rango, para los comprobantes que NO tienen fila en
# `nomina` y por tanto se acotan por `Comprobante.fecha_emision` (ver `_rango_de_emision`).
_EMITIDO_EN_RANGO = datetime(2026, 6, 30, 9, 30)


def _columna(resultado, titulo: str) -> int:  # type: ignore[no-untyped-def]
    titulos = [c.titulo for c in resultado.columnas]
    assert titulo in titulos, f"falta la columna {titulo!r}; hay {titulos}"
    return titulos.index(titulo)


async def test_una_fila_por_comprobante_con_columnas_dinamicas(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111")

    p = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31))
    resultado = await b02.consultar(db, empresa.empresa_id, p)

    assert len(resultado.filas) == 1
    indice = _columna(resultado, f"P{b02.SEPARADOR_ETIQUETA}001{b02.SEPARADOR_ETIQUETA}001{b02.SEPARADOR_ETIQUETA}Sueldo")
    assert resultado.filas[0][indice] == Decimal("8759.70")


async def test_concepto_repetido_se_suma(db: AsyncSession) -> None:
    """B-02.R1. Sobrescribir en vez de sumar subvalúa la nómina en silencio."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="22222222-2222-2222-2222-222222222222",
        percepciones=[("019", "019", "Horas extra", "300.00", "0.00"), ("019", "019", "Horas extra", "450.00", "0.00")],
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    indice = _columna(resultado, f"P{b02.SEPARADOR_ETIQUETA}019{b02.SEPARADOR_ETIQUETA}019{b02.SEPARADOR_ETIQUETA}Horas extra")
    assert resultado.filas[0][indice] == Decimal("750.00")


async def test_colision_de_clave_entre_naturalezas_no_colapsa(db: AsyncSession) -> None:
    """B-02.R3, con el caso real de la empresa 11: 'Ajuste al neto' es D/004/099 y O/999/099."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="33333333-3333-3333-3333-333333333333",
        deducciones=[("004", "099", "Ajuste al neto", "0.04")],
        otros_pagos=[("999", "099", "Ajuste al neto", "0.05", "0.00")],
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    sep = b02.SEPARADOR_ETIQUETA
    indice_deduccion = _columna(resultado, f"D{sep}004{sep}099{sep}Ajuste al neto")
    indice_otro = _columna(resultado, f"O{sep}999{sep}099{sep}Ajuste al neto")
    assert indice_deduccion != indice_otro
    assert resultado.filas[0][indice_deduccion] == Decimal("0.04")
    assert resultado.filas[0][indice_otro] == Decimal("0.05")


async def test_celda_sin_dato_es_cero_no_vacio(db: AsyncSession) -> None:
    """R-T7: un nulo en columna de importe es indistinguible de 'no aplica' y rompe
    cualquier suma en hoja de cálculo."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="44444444-4444-4444-4444-444444444444",
        rfc_receptor="XEXX010101000",
        percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
    )
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="55555555-5555-5555-5555-555555555555",
        rfc_receptor="XAXX010101000",
        percepciones=[("002", "002", "Aguinaldo", "5000.00", "0.00")],
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    sep = b02.SEPARADOR_ETIQUETA
    indice_aguinaldo = _columna(resultado, f"P{sep}002{sep}002{sep}Aguinaldo")
    valores = {fila[_columna(resultado, "UUID")]: fila[indice_aguinaldo] for fila in resultado.filas}
    assert valores["44444444-4444-4444-4444-444444444444"] == Decimal("0")
    assert valores["55555555-5555-5555-5555-555555555555"] == Decimal("5000.00")


async def test_orden_de_columnas_es_determinista(db: AsyncSession) -> None:
    """B-02.R5: percepciones, luego otros pagos, luego deducciones; dentro de cada
    naturaleza por tipo y clave como texto."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="66666666-6666-6666-6666-666666666666",
        percepciones=[("005", "031", "Fondo ahorro empresa", "0.00", "500.00"), ("001", "001", "Sueldo", "8000.00", "0.00")],
        deducciones=[("002", "045", "I.S.R. mes", "391.10"), ("001", "052", "I.M.S.S.", "200.00")],
        otros_pagos=[("002", "035", "Subs al Empleo mes", "0.00", "0.00")],
    )

    p = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31))
    primera = await b02.consultar(db, empresa.empresa_id, p)
    segunda = await b02.consultar(db, empresa.empresa_id, p)
    assert [c.titulo for c in primera.columnas] == [c.titulo for c in segunda.columnas]

    dinamicas = [c.titulo for c in primera.columnas if b02.SEPARADOR_ETIQUETA in c.titulo]
    assert [t[0] for t in dinamicas] == ["P", "P", "O", "D", "D"]
    assert dinamicas[0].startswith("P") and "001" in dinamicas[0]
    assert dinamicas[1].startswith("P") and "005" in dinamicas[1]


async def test_concepto_inconsistente_usa_la_descripcion_mas_frecuente(db: AsyncSession) -> None:
    """R-T9: se agrupa por (tipo, clave) y se reporta la descripción más frecuente, con
    bandera. Agrupar por descripción produciría columnas duplicadas del mismo concepto."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    for indice, concepto in enumerate(("Sueldo", "Sueldo", "Sueldos")):
        await insertar_nomina(
            db,
            empresa_id=empresa.empresa_id,
            uuid=f"7777777{indice}-7777-7777-7777-777777777777",
            rfc_receptor=f"XAXX01010100{indice}",
            percepciones=[("001", "001", concepto, "8000.00", "0.00")],
            deducciones=[],
        )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))

    sep = b02.SEPARADOR_ETIQUETA
    dinamicas = [c.titulo for c in resultado.columnas if sep in c.titulo]
    assert dinamicas == [f"P{sep}001{sep}001{sep}Sueldo"]
    assert any(b.clave == "CONCEPTO_INCONSISTENTE" for b in resultado.banderas)
    entrada = next(e for e in resultado.diccionario if e.etiqueta == dinamicas[0])
    assert entrada.concepto_canonico == "Sueldo"
    assert entrada.descripciones_alternas == ["Sueldos"]


async def test_cancelados_se_excluyen_por_defecto(db: AsyncSession) -> None:
    """R-T1."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="88888888-8888-8888-8888-888888888888", estatus=EstatusCfdi.CANCELADO)

    p = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31))
    assert (await b02.consultar(db, empresa.empresa_id, p)).filas == []

    p_con = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31), incluir_cancelados=True)
    assert len((await b02.consultar(db, empresa.empresa_id, p_con)).filas) == 1


async def test_columnas_personales_declaran_sensible_y_entregan_el_dato_en_claro(db: AsyncSession) -> None:
    """spec §8, con el contrato de la ronda de corrección 1 de la tarea 10: el enmascaramiento
    es responsabilidad del motor (`app.informes.excel`), no de esta consulta. B-02 solo marca
    `CURP` y `NSS` como `sensible=True` y entrega el dato en claro; `enmascarar_datos_personales`
    sigue viajando en `Parametros` porque de ahí lo toma `ContextoInforme.parametros` cuando el
    endpoint arma el contexto para `escribir_libro`."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="99999999-9999-9999-9999-999999999999")

    p = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31))
    resultado = await b02.consultar(db, empresa.empresa_id, p)

    indice_curp = _columna(resultado, "CURP")
    indice_nss = _columna(resultado, "NSS")
    assert resultado.columnas[indice_curp].sensible is True
    assert resultado.columnas[indice_nss].sensible is True
    assert resultado.filas[0][indice_curp] == "XXXX800101HCHXXX01"
    assert resultado.filas[0][indice_nss] == "12345678901"


async def test_banderas_de_descuadre_y_neto(db: AsyncSession) -> None:
    """Identidades de B-00 fuera de tolerancia y `NETO_NEGATIVO`."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        percepciones=[("001", "001", "Sueldo", "5000.00", "0.00")],
        total_percepciones="8759.70",  # no coincide con la suma de percepciones
        total="-10.00",
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    claves = {b.clave for b in resultado.banderas}
    assert "TOTALES_DESCUADRADOS" in claves
    assert "NETO_NEGATIVO" in claves


async def test_dias_pagados_atipico_para_quincenal(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", dias="20.000")

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    assert any(b.clave == "DIAS_PAGADOS_ATIPICO" for b in resultado.banderas)


async def test_sin_comprobantes_devuelve_aviso(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31)))
    assert resultado.filas == []
    assert resultado.aviso is not None


async def test_concepto_repetido_con_descripciones_distintas_se_suma(db: AsyncSession) -> None:
    """B-02.R1, la mitad de la regla que `test_concepto_repetido_se_suma` no ejercita.

    Cuando los dos nodos repetidos tienen la MISMA descripción, `GROUP BY` de SQL ya los
    agrupa en una sola fila y el `SUM` de la base de datos hace toda la suma: el `+=` de
    Python en `_conceptos_por_comprobante` nunca se ejecuta más de una vez por fila. Aquí
    las dos apariciones del mismo (tipo, clave) tienen descripciones DISTINTAS en el MISMO
    comprobante, así que SQL las agrupa en dos filas separadas (agrupa también por
    `concepto`) y es el acumulador de Python el que las suma. Si alguien cambiara
    `importes[...] += importe` por `= importe`, esta prueba fallaría aunque las otras 10
    sigan verdes."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="cccccccc-cccc-cccc-cccc-cccccccccccc",
        percepciones=[
            ("019", "019", "Horas extra", "300.00", "0.00"),
            ("019", "019", "Horas extra (ajuste)", "450.00", "0.00"),
        ],
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    sep = b02.SEPARADOR_ETIQUETA
    dinamicas_percepcion = [c.titulo for c in resultado.columnas if c.titulo.startswith(f"P{sep}019{sep}019")]
    assert len(dinamicas_percepcion) == 1  # mismo (tipo, clave): una sola columna, no dos
    indice = _columna(resultado, dinamicas_percepcion[0])
    assert resultado.filas[0][indice] == Decimal("750.00")


async def test_desempate_de_concepto_canonico_es_deterministico(db: AsyncSession) -> None:
    """B-02.R5: con dos descripciones empatadas en frecuencia para el mismo concepto, el
    desempate debe ser estable entre corridas —alfabético—, no depender del orden de filas
    de un `GROUP BY` sin `ORDER BY` (no garantizado por MySQL entre ejecuciones).

    El orden de inserción es deliberado: "Sueldos" (el alfabéticamente MAYOR) se inserta
    antes que "Sueldo" (el menor), manteniendo el empate 2-2. Así, un desempate viejo por
    "primero visto" (`Counter.most_common(1)[0][0]`) elegiría "Sueldos", mientras que el
    desempate correcto (alfabético) elige "Sueldo" — los dos algoritmos discrepan y la
    prueba sí distingue entre ellos. Con "Sueldo" insertado primero (como en un intento
    anterior de esta prueba), ambos desempates coinciden por casualidad y la prueba no
    protege nada, aunque pase."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    for indice, concepto in enumerate(("Sueldos", "Sueldo", "Sueldos", "Sueldo")):
        await insertar_nomina(
            db,
            empresa_id=empresa.empresa_id,
            uuid=f"dddddddd-dddd-dddd-dddd-ddddddddddd{indice}",
            rfc_receptor=f"XAXX0101010{indice:02d}",
            percepciones=[("001", "001", concepto, "8000.00", "0.00")],
            deducciones=[],
        )

    p = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31))
    primera = await b02.consultar(db, empresa.empresa_id, p)
    segunda = await b02.consultar(db, empresa.empresa_id, p)

    sep = b02.SEPARADOR_ETIQUETA
    titulo_esperado = f"P{sep}001{sep}001{sep}Sueldo"  # empate 2-2: "Sueldo" < "Sueldos" alfabéticamente
    assert [c.titulo for c in primera.columnas if sep in c.titulo] == [titulo_esperado]
    assert [c.titulo for c in segunda.columnas if sep in c.titulo] == [titulo_esperado]


async def test_bandera_clave_vacia(db: AsyncSession) -> None:
    """Un concepto sin clave del patrón no se puede identificar de forma estable entre
    periodos: se marca con `CLAVE_VACIA` en vez de descartarse en silencio."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        percepciones=[("999", "", "Concepto sin clave", "100.00", "0.00")],
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    assert any(b.clave == "CLAVE_VACIA" for b in resultado.banderas)


async def test_bandera_deduccion_mayor_percepcion(db: AsyncSession) -> None:
    """Las deducciones no pueden exceder lo que hay para deducir (percepciones + otros
    pagos): si lo hacen, el neto no cuadra y algo está mal capturado."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="ffffffff-ffff-ffff-ffff-ffffffffffff",
        percepciones=[("001", "001", "Sueldo", "100.00", "0.00")],
        deducciones=[("002", "045", "I.S.R. mes", "500.00")],
        otros_pagos=[],
        total_percepciones="100.00",
        total_deducciones="500.00",
        total_otros_pagos="0.00",
        total="-400.00",
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    assert any(b.clave == "DEDUCCION_MAYOR_PERCEPCION" for b in resultado.banderas)


async def test_diccionario_trae_la_descripcion_del_catalogo_sat(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="cccccccc-cccc-cccc-cccc-cccccccccccc")

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    entrada = next(e for e in resultado.diccionario if e.naturaleza == "P" and e.tipo == "001")
    assert entrada.descripcion_sat == "Sueldos, Salarios Rayas y Jornales"


async def test_serie_sale_del_detalle_del_comprobante(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    # `insertar_nomina` ya crea la fila 1:1 de `comprobante_detalle` (revisión final de la fase 2),
    # así que la serie se fija por parámetro; añadir otra fila aquí violaría la llave primaria.
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="dddddddd-dddd-dddd-dddd-dddddddddddd", serie="N")

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    assert resultado.filas[0][_columna(resultado, "Serie")] == "N"


async def _n_sin_nomina(
    db: AsyncSession,
    *,
    empresa_id: int,
    uuid: str,
    error_normalizacion: str | None = None,
    con_detalle: bool = True,
    rfc_emisor: str = "CHL960913IX9",
    fecha_emision: datetime = _EMITIDO_EN_RANGO,
    estatus: EstatusCfdi = EstatusCfdi.VIGENTE,
) -> int:
    """Un CFDI tipo `N` **sin fila en `nomina`**: el que el `join` interno del universo borra
    del informe. `con_detalle=False` es el que nunca pasó por el ETL; con detalle y
    `error_normalizacion` es el que el ETL intentó y no pudo; con detalle y sin error es un
    tipo `N` que el SAT entregó sin complemento de nómina."""
    comprobante = await factories.crear_comprobante(
        db,
        empresa_id=empresa_id,
        uuid=uuid,
        rfc_emisor=rfc_emisor,
        tipo_comprobante="N",
        estatus=estatus,
        fecha_emision=fecha_emision,
    )
    if con_detalle:
        db.add(
            ComprobanteDetalle(
                comprobante_id=comprobante.comprobante_id,
                version="4.0",
                xml_hash="f" * 64,
                etl_version=1,
                error_normalizacion=error_normalizacion,
            )
        )
        await db.commit()
    return comprobante.comprobante_id


async def test_nomina_que_fallo_el_etl_no_desaparece_del_informe_sin_bandera(db: AsyncSession) -> None:
    """**El hallazgo Critical de la revisión final.** El universo hace `join` con `nomina`, así
    que un tipo `N` cuyo XML se corrompió en disco queda fuera de la hoja `Datos`. Sin la
    segunda consulta, el Excel sale con una fila donde debería haber dos, la hoja `Parámetros`
    declara "Filas: 1" y la hoja `Banderas` está vacía: el patrón concilia un recibo creyendo
    que son todos. Un recibo que desaparece en silencio es un error fiscal, no un bug."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="11111111-0000-0000-0000-111111111111")
    await _n_sin_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="22222222-0000-0000-0000-222222222222",
        error_normalizacion="XMLSyntaxError: Premature end of data in tag Comprobante",
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA))

    assert len(resultado.filas) == 1
    assert resultado.filas[0][_columna(resultado, "UUID")] == "11111111-0000-0000-0000-111111111111"
    faltantes = [b for b in resultado.banderas if b.clave == "SIN_NORMALIZAR"]
    assert len(faltantes) == 1, f"se esperaba una bandera SIN_NORMALIZAR; hubo {[b.clave for b in resultado.banderas]}"
    assert faltantes[0].ambito == "uuid:22222222-0000-0000-0000-222222222222"
    assert faltantes[0].severidad == "alta"
    assert "Premature end of data" in faltantes[0].mensaje


async def test_nomina_que_nunca_paso_por_el_etl_tambien_lleva_bandera(db: AsyncSession) -> None:
    """Sin fila en `comprobante_detalle` en absoluto: se descargó y nunca se normalizó."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _n_sin_nomina(db, empresa_id=empresa.empresa_id, uuid="33333333-0000-0000-0000-333333333333", con_detalle=False)

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA))

    bandera = next(b for b in resultado.banderas if b.clave == "SIN_NORMALIZAR")
    assert bandera.ambito == "uuid:33333333-0000-0000-0000-333333333333"
    assert "nunca pasó por el ETL" in bandera.mensaje


async def test_tipo_n_sin_complemento_de_nomina_da_complemento_ausente(db: AsyncSession) -> None:
    """§9 del diseño: el ETL hizo su trabajo y el XML no traía complemento de nómina. Es un
    caso distinto de `SIN_NORMALIZAR` y se distingue porque se arregla distinto."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _n_sin_nomina(db, empresa_id=empresa.empresa_id, uuid="44444444-0000-0000-0000-444444444444")

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA))

    bandera = next(b for b in resultado.banderas if b.clave == "COMPLEMENTO_AUSENTE")
    assert bandera.ambito == "uuid:44444444-0000-0000-0000-444444444444"
    assert bandera.severidad == "alta"
    assert not any(b.clave == "SIN_NORMALIZAR" for b in resultado.banderas)


async def test_si_fallan_todas_el_libro_vacio_no_sale_mudo(db: AsyncSession) -> None:
    """El peor caso: ningún CFDI del rango se pudo normalizar. La hoja `Datos` sale vacía —no
    hay nada que poner— pero el aviso "sin CFDI de nómina en el rango" sería una mentira si no
    fuera acompañado de las banderas. Un libro vacío y sin banderas es indistinguible de un
    periodo en el que de verdad no hubo nómina."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _n_sin_nomina(db, empresa_id=empresa.empresa_id, uuid="55555555-0000-0000-0000-555555555555", error_normalizacion="XML ilegible")

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA))

    assert resultado.filas == []
    assert resultado.aviso is not None
    assert [b.clave for b in resultado.banderas] == ["SIN_NORMALIZAR"]


async def test_bandera_de_datos_de_corrida_anterior_cuando_el_reproceso_fallo(db: AsyncSession) -> None:
    """El contrato de `registrar_error`: ante un fallo del ETL los hijos de la última corrida
    buena se conservan a propósito y el consumidor debe comprobar `error_normalizacion IS NULL`
    antes de confiar en la fila. Escenario: se normalizó bien, subió `ETL_VERSION`, el reproceso
    falló. La fila entra con los importes viejos —perderla sería peor— y la bandera avisa de que
    no son los del XML que hay hoy en disco."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="66666666-0000-0000-0000-666666666666",
        serie="N",
        error_normalizacion="DataError: valor demasiado largo para comprobante_detalle.moneda",
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA))

    assert len(resultado.filas) == 1  # la fila NO se pierde
    bandera = next(b for b in resultado.banderas if b.clave == "DATOS_DE_CORRIDA_ANTERIOR")
    assert bandera.ambito == "uuid:66666666-0000-0000-0000-666666666666"
    assert bandera.severidad == "alta"
    assert "DataError" in bandera.mensaje


async def test_no_verificado_entra_con_bandera_media(db: AsyncSession) -> None:
    """Divergencia declarada de R-T1: los `no_verificado` entran (excluirlos borraría del
    informe toda nómina cuyo estatus aún no se ha consultado al SAT), pero nunca sin
    distinguirse de los vigentes."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="77777777-0000-0000-0000-777777777777", estatus=EstatusCfdi.NO_VERIFICADO)

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA))

    assert len(resultado.filas) == 1
    bandera = next(b for b in resultado.banderas if b.clave == "ESTATUS_NO_VERIFICADO")
    assert bandera.ambito == "uuid:77777777-0000-0000-0000-777777777777"
    assert bandera.severidad == "media"


async def test_cancelado_incluido_a_proposito_lleva_bandera_alta(db: AsyncSession) -> None:
    """Con `incluir_cancelados=True` los importes del cancelado suman en el `importe_total` del
    Diccionario. Antes entraban sin distinguirse de los vigentes."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="88888888-0000-0000-0000-888888888888", estatus=EstatusCfdi.CANCELADO)

    p = b02.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA, incluir_cancelados=True)
    resultado = await b02.consultar(db, empresa.empresa_id, p)

    assert len(resultado.filas) == 1
    bandera = next(b for b in resultado.banderas if b.clave == "COMPROBANTE_CANCELADO")
    assert bandera.ambito == "uuid:88888888-0000-0000-0000-888888888888"
    assert bandera.severidad == "alta"
    # Un vigente no lleva ninguna de las dos banderas de estatus.
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="88888888-0000-0000-0000-999999999999", rfc_receptor="XEXX010101000")
    resultado = await b02.consultar(db, empresa.empresa_id, p)
    ambitos = {b.ambito for b in resultado.banderas if b.clave in {"COMPROBANTE_CANCELADO", "ESTATUS_NO_VERIFICADO"}}
    assert ambitos == {"uuid:88888888-0000-0000-0000-888888888888"}


async def test_universo_solo_los_emitidos_por_la_empresa(db: AsyncSession) -> None:
    """§11 del diseño: el universo del grupo B son los `N` **emitidos** por la empresa, que es
    el patrón. Inerte hoy con una sola empresa, pero sin la condición el informe mezclaría dos
    patrones en la misma hoja en cuanto exista una segunda — o en cuanto se descargue una
    nómina recibida. Aplica tanto a la hoja `Datos` como a las banderas."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    ajeno = await factories.crear_comprobante(
        db,
        empresa_id=empresa.empresa_id,
        uuid="99999999-0000-0000-0000-999999999999",
        rfc_emisor="OTRO900101AAA",
        tipo_comprobante="N",
        estatus=EstatusCfdi.VIGENTE,
        fecha_emision=_EMITIDO_EN_RANGO,
    )
    db.add(
        Nomina(
            comprobante_id=ajeno.comprobante_id,
            version_nomina="1.2",
            tipo_nomina="O",
            fecha_pago=date(2026, 6, 30),
            total_percepciones=Decimal("100.00"),
            total_deducciones=Decimal("0.00"),
            total_otros_pagos=Decimal("0.00"),
        )
    )
    await db.commit()
    # Y uno ajeno más que además está sin normalizar: tampoco debe generar bandera.
    await _n_sin_nomina(
        db, empresa_id=empresa.empresa_id, uuid="99999999-0000-0000-0000-aaaaaaaaaaaa", rfc_emisor="OTRO900101AAA", con_detalle=False
    )

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA))

    assert resultado.filas == []
    assert resultado.banderas == []


async def test_bandera_aunque_el_timbrado_caiga_despues_del_rango_de_pago(db: AsyncSession) -> None:
    """**El caso real que la primera versión de esta corrección perdía.** En la BD de la
    empresa 11 los 8 CFDI de nómina están timbrados **al día siguiente** del pago, y la RMF
    (2.7.5.3) permite hasta 11 días hábiles de desfase.

    Escenario exacto: informe de junio, nómina pagada el 30 de junio, **timbrada el 1 de
    julio**, con el ETL fallido. Con la ventana de banderas pegada a `[desde, hasta+1día)`, el
    informe salía con 0 filas, 0 banderas y el aviso "Sin CFDI de nómina en el rango
    solicitado" — el fallo que esta consulta existe para evitar, reproducido contra datos
    reales por la re-revisión."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="cafe0001-0000-0000-0000-000000000001", fecha_pago=date(2026, 6, 30))
    await _n_sin_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="cafe0002-0000-0000-0000-000000000002",
        error_normalizacion="XMLSyntaxError: Premature end of data in tag Comprobante",
        fecha_emision=datetime(2026, 7, 1, 9, 30),  # timbrado al día siguiente del pago
    )

    # Rango de PAGO que termina el 30 de junio: el timbrado del 1 de julio queda fuera de él.
    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 6, 30)))

    assert len(resultado.filas) == 1
    faltantes = [b for b in resultado.banderas if b.clave == "SIN_NORMALIZAR"]
    assert len(faltantes) == 1, f"la nómina timbrada al día siguiente del pago no puede desaparecer; banderas: {resultado.banderas}"
    assert faltantes[0].ambito == "uuid:cafe0002-0000-0000-0000-000000000002"


async def test_las_banderas_se_acotan_al_rango_de_emision_con_margen_de_timbrado(db: AsyncSession) -> None:
    """La ventana de banderas lleva `_MARGEN_TIMBRADO_DIAS` de holgura a los dos lados, porque
    el timbrado puede ir después del pago (RMF 2.7.5.3) o anticiparse. Pero sigue siendo una
    ventana: un `N` roto de un ejercicio ajeno no debe aparecer en el informe de este mes, o la
    hoja `Banderas` se llena de entradas irrelevantes y deja de leerse — que es otra manera de
    perder el aviso."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    margen = b02._MARGEN_TIMBRADO_DIAS
    casos = {
        # (uuid, fecha_emision) → ¿debe salir bandera?
        "aaaaaaaa-1111-0000-0000-aaaaaaaaaaaa": (datetime(2025, 3, 15, 10, 0), False),  # otro ejercicio
        "aaaaaaaa-2222-0000-0000-aaaaaaaaaaaa": (datetime.combine(_HASTA, datetime.min.time()) + timedelta(days=margen, hours=23), True),
        "aaaaaaaa-3333-0000-0000-aaaaaaaaaaaa": (datetime.combine(_HASTA, datetime.min.time()) + timedelta(days=margen + 1), False),
        "aaaaaaaa-4444-0000-0000-aaaaaaaaaaaa": (datetime.combine(_DESDE, datetime.min.time()) - timedelta(days=margen), True),
        "aaaaaaaa-5555-0000-0000-aaaaaaaaaaaa": (datetime.combine(_DESDE, datetime.min.time()) - timedelta(seconds=1, days=margen), False),
    }
    for uuid, (fecha_emision, _) in casos.items():
        await _n_sin_nomina(db, empresa_id=empresa.empresa_id, uuid=uuid, con_detalle=False, fecha_emision=fecha_emision)

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA))

    ambitos = {b.ambito for b in resultado.banderas}
    assert ambitos == {f"uuid:{uuid}" for uuid, (_, esperada) in casos.items() if esperada}


async def test_descripciones_que_solo_difieren_en_mayusculas_se_detectan(db: AsyncSession) -> None:
    """`utf8mb4_unicode_ci` es insensible a mayúsculas y acentos: "SUELDO" y "Sueldo" en el
    MISMO comprobante colapsaban en un grupo del `GROUP BY` y MySQL devolvía un representante
    arbitrario, así que el título de la columna no era determinista y `CONCEPTO_INCONSISTENTE`
    —la bandera que existe justo para avisar de esto— no las veía.

    Con `COLLATE utf8mb4_bin` sobre la descripción son dos filas, pero **no** dos columnas: la
    identidad de columna es `(naturaleza, tipo, clave)` y se arma en Python (R-T9), así que las
    dos filas caen en la misma celda y su importe se suma."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="c011a710-0000-0000-0000-000000000001",
        percepciones=[("001", "001", "SUELDO", "5000.00", "0.00"), ("001", "001", "Sueldo", "3000.00", "0.00")],
    )

    p = b02.Parametros(fecha_desde=_DESDE, fecha_hasta=_HASTA)
    primera = await b02.consultar(db, empresa.empresa_id, p)
    segunda = await b02.consultar(db, empresa.empresa_id, p)

    sep = b02.SEPARADOR_ETIQUETA
    dinamicas = [c.titulo for c in primera.columnas if c.titulo.startswith(f"P{sep}001{sep}001")]
    assert len(dinamicas) == 1, f"una sola columna para (P, 001, 001); hubo {dinamicas}"
    assert primera.filas[0][_columna(primera, dinamicas[0])] == Decimal("8000.00")  # 5000 + 3000
    assert any(b.clave == "CONCEPTO_INCONSISTENTE" for b in primera.banderas)

    entrada = next(e for e in primera.diccionario if e.etiqueta == dinamicas[0])
    assert entrada.concepto_canonico == "SUELDO"  # empate 1-1 → desempate alfabético estable
    assert entrada.descripciones_alternas == ["Sueldo"]
    assert [c.titulo for c in segunda.columnas] == [c.titulo for c in primera.columnas]


async def test_bandera_periodo_traslapado(db: AsyncSession) -> None:
    """Dos nóminas ordinarias del mismo empleado con rangos que se intersectan: casi
    siempre un timbrado doble."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    rfc_receptor = "XAXX010101099"
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="11111111-2222-3333-4444-555555555555", rfc_receptor=rfc_receptor, fecha_pago=date(2026, 6, 30))
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="66666666-7777-8888-9999-000000000000", rfc_receptor=rfc_receptor, fecha_pago=date(2026, 6, 20))

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    assert any(b.clave == "PERIODO_TRASLAPADO" for b in resultado.banderas)


async def test_nombre_empleado_es_del_trabajador_no_del_patron(db: AsyncSession) -> None:
    """**El único hueco que sobrevivió al barrido por mutación del re-revisor.** La ola de
    correcciones arregló esta columna en B-01 y en B-02 —traía `comprobante.razon_social_emisor`,
    el nombre de la EMPRESA, repetido en todas las filas de un papel de trabajo fiscal— pero solo
    dejó prueba en B-01, B-05 y B-07. Revertir B-02 a `razon_social_emisor` dejaba los seis
    archivos de pruebas de informes verdes: el sesgo natural de quien arregla dos informes y prueba
    uno.

    La segunda aserción es la que hace que la prueba no sea vacua: sin ella, un `None` (el valor que
    daba el campo cuando el helper de pruebas no insertaba `comprobante_detalle`) o cualquier otro
    valor equivocado pasaría igual mientras no fuera el nombre esperado. `"EMISOR DE PRUEBA SA DE
    CV"` es el default de `factories.crear_comprobante` para `razon_social_emisor`, es decir, el
    valor exacto que la mutación pondría ahí."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(db, empresa_id=empresa.empresa_id, uuid="aaaa1111-bbbb-2222-cccc-333333333333",
                          nombre_receptor="JUANA INVENTADA DE PRUEBA")

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    nombre = resultado.filas[0][_columna(resultado, "Nombre empleado")]
    assert nombre == "JUANA INVENTADA DE PRUEBA"
    assert nombre != "EMISOR DE PRUEBA SA DE CV", "es la razón social del EMISOR: el nombre del patrón, no del trabajador"
