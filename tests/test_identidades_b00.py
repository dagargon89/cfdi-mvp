"""Las 9 identidades contables de B-00 sobre la capa normalizada.

Es la comprobación más fuerte que existe sobre el ETL y el criterio de cierre de la fase:
los totales que el complemento de Nómina 1.2 **declara** contra la suma de sus propios
nodos. Un CFDI timbrado por el SAT las cumple por construcción, así que un descuadre aquí
solo puede ser un nodo que el ETL lee mal — el tipo de bug que en este dominio se descubre
cuando la autoridad lo señala. Ocho informes más se van a construir sobre esta capa.

Antes vivían únicamente en `scripts/verificar_informes.py` (entonces `verificar_fase1.py`), fuera de `testpaths`, así que nada
las mantenía verdes. Ahora la implementación es una sola (`app/informes/identidades_b00.py`)
y tiene dos llamadores: este archivo, sobre XML sintéticos que pasan por el ETL completo, y
el script, sobre los CFDI reales de la empresa.

Todo el recorrido es real: XML → `normalizar_lote` → tablas normalizadas → identidades. No
se insertan filas a mano en ninguna parte; hacerlo comprobaría las aserciones contra los
mismos números que el test escribió, no contra lo que el ETL leyó del XML.
"""

from __future__ import annotations

import os
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.informes import identidades_b00
from app.models.nomina import Nomina, NominaTotales
from app.services import normalizacion_lote
from tests import factories, fixtures_cfdi

# Percepciones coherentes con los tres totales del nodo `Percepciones`: sueldo gravado (001),
# separación por indemnización gravada (022) y jubilación exenta (039).
PERCEPCIONES_CON_LOS_TRES_TOTALES = (
    '<nomina12:Percepcion TipoPercepcion="001" Clave="001" Concepto="Sueldo" '
    'ImporteGravado="8000.00" ImporteExento="0.00" />'
    '<nomina12:Percepcion TipoPercepcion="022" Clave="022" Concepto="Prima por antiguedad" '
    'ImporteGravado="1000.00" ImporteExento="0.00" />'
    '<nomina12:Percepcion TipoPercepcion="039" Clave="039" Concepto="Jubilacion en una exhibicion" '
    'ImporteGravado="0.00" ImporteExento="500.00" />'
)

PARAMETROS_CON_LOS_TRES_TOTALES = {
    "total_sueldos": "8000.00",
    "total_separacion_indemnizacion": "1000.00",
    "total_jubilacion_pension_retiro": "500.00",
    "total_gravado": "9000.00",
    "total_exento": "500.00",
    "total_percepciones": "9500.00",
    "total_deducciones": "1091.10",
    "subtotal": "9500.00",
    "descuento": "1091.10",
    "total": "8408.90",
}

# Recibo ordinario con el subsidio al empleo pagado de verdad (120.50), no en 0.00: es lo que
# hace que la identidad 3 compare dos números y no `0 == 0`. Todo lo demás sale de los valores
# por defecto del fixture: percepciones 8759.70 + 500.00 = 9259.70, deducciones 1091.10.
# subtotal = 9259.70 + 120.50 = 9380.20; total = 9380.20 − 1091.10 = 8289.10.
PARAMETROS_CON_OTRO_PAGO_NO_CERO = {
    "otros_pagos_xml": (
        '<nomina12:OtroPago TipoOtroPago="002" Clave="035" Concepto="Subs al Empleo mes" Importe="120.50">'
        '<nomina12:SubsidioAlEmpleo SubsidioCausado="120.50" /></nomina12:OtroPago>'
    ),
    "total_otros_pagos": "120.50",
    "subtotal": "9380.20",
    "total": "8289.10",
}


async def _normalizar_xml(db: AsyncSession, empresa_id: int, uuid: str, xml: bytes, total: str) -> int:
    """Deja el XML en disco, registra su comprobante y lo pasa por el ETL de verdad.

    `total` se pasa explícito porque `comprobantes.total` viene de la metadata del SAT y el
    ETL no lo toca (spec §4.2: la tabla caliente no se modifica). Las identidades 6-8 cotejan
    justo ese valor contra el encabezado normalizado, así que el default del factory (1160.00)
    haría fallar la identidad por un dato de prueba incoherente, no por un bug.
    """
    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), "comprobantes")
    os.makedirs(carpeta, exist_ok=True)
    nombre = f"{uuid}.xml"
    with open(os.path.join(carpeta, nombre), "wb") as f:
        f.write(xml)
    comprobante = await factories.crear_comprobante(
        db,
        empresa_id=empresa_id,
        uuid=uuid,
        rfc_emisor="CHL960913IX9",
        tipo_comprobante="N",
        total=Decimal(total),
        xml_path=os.path.join(str(empresa_id), "comprobantes", nombre),
    )
    resumen = await normalizacion_lote.normalizar_lote(db, empresa_id, [comprobante.comprobante_id])
    assert resumen == {"normalizados": 1, "con_error": 0, "omitidos": 0}, resumen
    return comprobante.comprobante_id


async def test_las_nueve_identidades_se_cumplen_en_el_recibo_ordinario(db: AsyncSession) -> None:
    """El caso base, que además es el espejo del fondo de ahorro (R-T10): los mismos 500.00
    aparecen como percepción exenta (005/031) y como deducción (004/067). El ETL no consolida,
    y las identidades tienen que cuadrar igual con el flujo duplicado.

    El `OtroPago` lleva un importe **distinto de cero** a propósito. Con el 0.00 del fixture
    por defecto, la identidad 3 (`total_otros_pagos`) se cumplía comparando 0 contra 0, que es
    verdad para cualquier ETL, incluso uno que no leyera el nodo `OtrosPagos`. Con 120.50, el
    valor tiene que haber salido del XML — y arrastra a las identidades 6 y 8, porque el
    subtotal es percepciones + otros pagos."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _normalizar_xml(
        db,
        empresa.empresa_id,
        "77777777-7777-7777-7777-777777777777",
        fixtures_cfdi.cfdi_nomina(**PARAMETROS_CON_OTRO_PAGO_NO_CERO),
        total="8289.10",
    )

    v = await identidades_b00.verificar(db, empresa.empresa_id)
    assert v.fallas == []
    assert v.comprobantes == 1
    # No basta con que no haya fallas: hay que saber que los 10 cotejos se ejecutaron. Un
    # cotejo que no corre no puede fallar, así que sin esta aserción borrar ocho de las nueve
    # identidades dejaría esta prueba verde.
    assert v.cotejos == identidades_b00.COTEJOS_POR_COMPROBANTE_COMPLETO


async def test_identidades_con_concepto_repetido_del_mismo_tipo_y_clave(db: AsyncSession) -> None:
    """B-02.R1 desde el lado del ETL: dos nodos con el mismo `(tipo, clave)` en un CFDI. Si el
    escritor sobrescribiera en vez de insertar los dos, `total_percepciones` declarado (9509.70)
    dejaría de cuadrar con la suma de nodos y la identidad 1 lo detectaría."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    percepciones = (
        '<nomina12:Percepcion TipoPercepcion="001" Clave="001" Concepto="Sueldo" '
        'ImporteGravado="8759.70" ImporteExento="0.00" />'
        '<nomina12:Percepcion TipoPercepcion="019" Clave="019" Concepto="Horas extra" '
        'ImporteGravado="300.00" ImporteExento="0.00" />'
        '<nomina12:Percepcion TipoPercepcion="019" Clave="019" Concepto="Horas extra" '
        'ImporteGravado="450.00" ImporteExento="0.00" />'
    )
    await _normalizar_xml(
        db,
        empresa.empresa_id,
        "88888888-8888-8888-8888-888888888888",
        fixtures_cfdi.cfdi_nomina(
            percepciones_xml=percepciones,
            total_percepciones="9509.70",
            total_gravado="9509.70",
            total_exento="0.00",
            subtotal="9509.70",
            total="8418.60",
        ),
        total="8418.60",
    )

    v = await identidades_b00.verificar(db, empresa.empresa_id)
    assert v.fallas == []
    assert v.comprobantes == 1
    assert v.cotejos == identidades_b00.COTEJOS_POR_COMPROBANTE_COMPLETO


async def test_identidades_con_los_nodos_opcionales_ausentes(db: AsyncSession) -> None:
    """Un recibo sin `Deducciones`, sin `OtrosPagos` y sin `TotalImpuestosRetenidos`. Ausente
    no es cero declarado: los atributos que el XML no trae llegan como `None` y no se comparan,
    mientras que las sumas de nodos inexistentes valen 0."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await _normalizar_xml(
        db,
        empresa.empresa_id,
        "99999999-9999-9999-9999-999999999999",
        fixtures_cfdi.cfdi_nomina(
            percepciones_xml='<nomina12:Percepcion TipoPercepcion="001" Clave="001" Concepto="Sueldo" ImporteGravado="8000.00" ImporteExento="0.00" />',
            sin_deducciones=True,
            sin_otros_pagos=True,
            total_percepciones="8000.00",
            total_deducciones="0.00",
            total_otros_pagos="0.00",
            total_gravado="8000.00",
            total_exento="0.00",
            subtotal="8000.00",
            descuento="0.00",
            total="8000.00",
        ),
        total="8000.00",
    )

    v = await identidades_b00.verificar(db, empresa.empresa_id)
    assert v.fallas == []
    assert v.comprobantes == 1
    # Uno menos que el recibo completo: sin nodo `Deducciones` no hay atributo
    # `TotalImpuestosRetenidos` que cotejar (identidad 9). Ausente no se compara y por eso
    # tampoco cuenta — pero el número se asevera para que se note si desaparece otro.
    assert v.cotejos == identidades_b00.COTEJOS_POR_COMPROBANTE_COMPLETO - 1


async def test_identidades_con_los_tres_totales_de_percepciones_poblados(db: AsyncSession) -> None:
    """`TotalSueldos`, `TotalSeparacionIndemnizacion` y `TotalJubilacionPensionRetiro` en el
    mismo recibo: las tres columnas de dinero de B-02 que un recibo ordinario deja vacías."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    cid = await _normalizar_xml(
        db,
        empresa.empresa_id,
        "aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa",
        fixtures_cfdi.cfdi_nomina(percepciones_xml=PERCEPCIONES_CON_LOS_TRES_TOTALES, **PARAMETROS_CON_LOS_TRES_TOTALES),
        total="8408.90",
    )

    v = await identidades_b00.verificar(db, empresa.empresa_id)
    assert v.fallas == []
    assert v.comprobantes == 1
    assert v.cotejos == identidades_b00.COTEJOS_POR_COMPROBANTE_COMPLETO

    totales = await db.scalar(select(NominaTotales).where(NominaTotales.comprobante_id == cid))
    assert totales is not None
    assert totales.total_sueldos == Decimal("8000.000000")
    assert totales.total_separacion_indemnizacion == Decimal("1000.000000")
    assert totales.total_jubilacion_pension_retiro == Decimal("500.000000")


async def test_un_descuadre_en_la_base_si_se_detecta(db: AsyncSession) -> None:
    """La prueba de que las otras no pasan por casualidad. Se altera en la BD un total ya
    normalizado —exactamente lo que haría un ETL que leyera mal ese nodo— y la verificación
    tiene que señalarlo con su UUID. Sin este caso, `fallas == []` podría significar tanto
    "todo cuadra" como "no se comprobó nada"."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    cid = await _normalizar_xml(
        db,
        empresa.empresa_id,
        "bbbbbbbb-0000-0000-0000-bbbbbbbbbbbb",
        fixtures_cfdi.cfdi_nomina(),
        total="8168.60",
    )

    await db.execute(update(Nomina).where(Nomina.comprobante_id == cid).values(total_percepciones=Decimal("9999.99")))
    await db.commit()

    v = await identidades_b00.verificar(db, empresa.empresa_id)
    assert v.comprobantes == 1
    assert v.cotejos == identidades_b00.COTEJOS_POR_COMPROBANTE_COMPLETO
    assert len(v.fallas) == 1
    assert "total_percepciones" in v.fallas[0]
    assert "bbbbbbbb-0000-0000-0000-bbbbbbbbbbbb" in v.fallas[0]
