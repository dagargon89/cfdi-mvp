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

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import b02_conceptos_patron as b02
from app.models.enums import EstatusCfdi
from app.models.nomina import Nomina, NominaDeduccion, NominaOtroPago, NominaPercepcion, NominaReceptor, NominaTotales
from tests import factories


async def _nomina(
    db: AsyncSession,
    *,
    empresa_id: int,
    uuid: str,
    num_empleado: str = "039",
    rfc_receptor: str = "XAXX010101000",
    fecha_pago: date = date(2026, 6, 30),
    percepciones: list[tuple[str, str, str, str, str]] | None = None,
    deducciones: list[tuple[str, str, str, str]] | None = None,
    otros_pagos: list[tuple[str, str, str, str]] | None = None,
    total_percepciones: str = "8759.70",
    total_deducciones: str = "591.10",
    total_otros_pagos: str = "0.00",
    total: str = "8168.60",
    estatus: EstatusCfdi = EstatusCfdi.VIGENTE,
    dias: str = "15.000",
) -> int:
    """Inserta un CFDI de nómina normalizado. Las tuplas son
    (tipo, clave, concepto, gravado, exento) para percepciones y (tipo, clave, concepto,
    importe) para deducciones y otros pagos."""
    comprobante = await factories.crear_comprobante(
        db,
        empresa_id=empresa_id,
        uuid=uuid,
        rfc_emisor="CHL960913IX9",
        rfc_receptor=rfc_receptor,
        tipo_comprobante="N",
        estatus=estatus,
        total=Decimal(total),
        fecha_emision=None,
    )
    cid = comprobante.comprobante_id
    db.add(
        Nomina(
            comprobante_id=cid,
            version_nomina="1.2",
            tipo_nomina="O",
            fecha_pago=fecha_pago,
            fecha_inicial_pago=date(fecha_pago.year, fecha_pago.month, 16),
            fecha_final_pago=fecha_pago,
            num_dias_pagados=Decimal(dias),
            total_percepciones=Decimal(total_percepciones),
            total_deducciones=Decimal(total_deducciones),
            total_otros_pagos=Decimal(total_otros_pagos),
            registro_patronal="B5510768108",
        )
    )
    db.add(
        NominaReceptor(
            comprobante_id=cid,
            curp="XXXX800101HCHXXX01",
            nss="12345678901",
            num_empleado=num_empleado,
            departamento="Direccion",
            puesto="Director",
            periodicidad_pago="04",
            tipo_regimen="02",
            salario_base_cot_apor=Decimal("583.98"),
            salario_diario_integrado=Decimal("607.34"),
        )
    )
    db.add(NominaTotales(comprobante_id=cid, total_gravado=Decimal(total_percepciones), total_exento=Decimal("0")))
    if percepciones is None:
        percepciones = [("001", "001", "Sueldo", total_percepciones, "0.00")]
    for tipo, clave, concepto, gravado, exento in percepciones:
        db.add(
            NominaPercepcion(
                comprobante_id=cid,
                tipo_percepcion=tipo,
                clave=clave,
                concepto=concepto,
                importe_gravado=Decimal(gravado),
                importe_exento=Decimal(exento),
            )
        )
    if deducciones is None:
        deducciones = [("002", "045", "I.S.R. mes", total_deducciones)]
    for tipo, clave, concepto, importe in deducciones:
        db.add(NominaDeduccion(comprobante_id=cid, tipo_deduccion=tipo, clave=clave, concepto=concepto, importe=Decimal(importe)))
    for tipo, clave, concepto, importe in otros_pagos or []:
        db.add(NominaOtroPago(comprobante_id=cid, tipo_otro_pago=tipo, clave=clave, concepto=concepto, importe=Decimal(importe)))
    await db.commit()
    return cid


def _columna(resultado, titulo: str) -> int:  # type: ignore[no-untyped-def]
    titulos = [c.titulo for c in resultado.columnas]
    assert titulo in titulos, f"falta la columna {titulo!r}; hay {titulos}"
    return titulos.index(titulo)


async def test_una_fila_por_comprobante_con_columnas_dinamicas(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111")

    p = b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31))
    resultado = await b02.consultar(db, empresa.empresa_id, p)

    assert len(resultado.filas) == 1
    indice = _columna(resultado, f"P{b02.SEPARADOR_ETIQUETA}001{b02.SEPARADOR_ETIQUETA}001{b02.SEPARADOR_ETIQUETA}Sueldo")
    assert resultado.filas[0][indice] == Decimal("8759.70")


async def test_concepto_repetido_se_suma(db: AsyncSession) -> None:
    """B-02.R1. Sobrescribir en vez de sumar subvalúa la nómina en silencio."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _nomina(
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
    await _nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="33333333-3333-3333-3333-333333333333",
        deducciones=[("004", "099", "Ajuste al neto", "0.04")],
        otros_pagos=[("999", "099", "Ajuste al neto", "0.05")],
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
    await _nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="44444444-4444-4444-4444-444444444444",
        rfc_receptor="XEXX010101000",
        percepciones=[("001", "001", "Sueldo", "8000.00", "0.00")],
    )
    await _nomina(
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
    await _nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="66666666-6666-6666-6666-666666666666",
        percepciones=[("005", "031", "Fondo ahorro empresa", "0.00", "500.00"), ("001", "001", "Sueldo", "8000.00", "0.00")],
        deducciones=[("002", "045", "I.S.R. mes", "391.10"), ("001", "052", "I.M.S.S.", "200.00")],
        otros_pagos=[("002", "035", "Subs al Empleo mes", "0.00")],
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
        await _nomina(
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
    await _nomina(db, empresa_id=empresa.empresa_id, uuid="88888888-8888-8888-8888-888888888888", estatus=EstatusCfdi.CANCELADO)

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
    await _nomina(db, empresa_id=empresa.empresa_id, uuid="99999999-9999-9999-9999-999999999999")

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
    await _nomina(
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
    await _nomina(db, empresa_id=empresa.empresa_id, uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", dias="20.000")

    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 7, 31)))
    assert any(b.clave == "DIAS_PAGADOS_ATIPICO" for b in resultado.banderas)


async def test_sin_comprobantes_devuelve_aviso(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    resultado = await b02.consultar(db, empresa.empresa_id, b02.Parametros(fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31)))
    assert resultado.filas == []
    assert resultado.aviso is not None
