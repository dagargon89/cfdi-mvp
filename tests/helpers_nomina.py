"""Helper compartido de pruebas: inserción de un CFDI de nómina normalizado.

Extraído de `tests/test_informe_b02.py` (donde vivía como `_nomina`, local a ese archivo)
porque los cinco informes del grupo B de la fase 2 (B-01, B-02, B-04, B-05, B-07) necesitan
el mismo universo de datos y repetirlo en cada archivo de pruebas es la misma duplicación
que la revisión final de la fase 1 señaló como riesgo principal, pero en las pruebas en vez
de en el código de producción.

Se declaran los parámetros desde el principio, aunque cada tarea use solo un subconjunto:
agregarlos a mitad del plan dejaría pruebas ya escritas contra una firma que todavía no
existe (las tareas 4 a 7 de esta fase los usan todos).

`total_impuestos_retenidos` y `total_otras_deducciones` (ronda de corrección 1 de la tarea 3)
se agregaron después de que la primera versión de este helper no pudiera fijar
`total_impuestos_retenidos`, lo que dejaba sin ejercitar la novena identidad de B-00 (ISR
retenido, spec `app.informes.identidades_b00`) en la única rama donde B-01 la comprueba
(`declarado is not None`): la comparación nunca corría en ninguna prueba del proyecto.

**Siempre inserta una fila de `comprobante_detalle`** (revisión final de la fase 2). Antes no lo
hacía, así que `detalle` llegaba como `None` a **todas** las pruebas de B-01, B-04, B-05, B-07 y
B-10 — y ese hueco es la razón por la que nadie vio que B-01 y B-02 llenaban su columna "Nombre
empleado" con `comprobante.razon_social_emisor`, el nombre de la EMPRESA: con `detalle is None`
ninguna prueba podía distinguir el campo correcto del equivocado, porque los dos habrían dado
`None`. Un CFDI normalizado siempre tiene su fila 1:1 en `comprobante_detalle` (spec §5.1), así
que insertarla es además lo fiel a la realidad. `nombre_receptor` es un nombre **inventado** por
defecto (regla 12: los datos de la empresa emisora están autorizados, los de personas no).

Dos trampas de este helper, ambas defectos reales de la fase 1:

- **`None` significa "usa el default", nunca "vacío".** Se comprueba con `if x is None:`,
  jamás con `x or default`: una lista vacía es *falsy* en Python, así que
  `deducciones=[]` para suprimir la deducción por defecto no funcionaría con `or` — ese fue
  el defecto real.
- **`rfc_emisor` por defecto es el RFC de la propia empresa** (`CHL960913IX9`), porque B-01,
  B-02, B-04, B-05 y B-07 filtran su universo por `Comprobante.rfc_emisor == rfc_empresa`
  (la empresa es el patrón). Un default distinto vaciaría el universo de los cinco informes
  y sus pruebas fallarían con un mensaje confuso ("sin CFDI de nómina en el rango") en vez de
  señalar la causa real. B-05 lo sobrescribe a propósito para probar `MULTI_PATRON`.

Datos de fixture (regla 12 de `Hub_CFDI_docs/CLAUDE.md`): el RFC y la razón social de la
empresa emisora son los reales de la propia empresa (`CHL960913IX9`) — están autorizados.
El receptor es el genérico de pruebas `XAXX010101000`. CURP y NSS son **siempre inventados**,
sin excepción, porque son datos personales y no de la empresa.
"""

from __future__ import annotations

from datetime import date

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.enums import EstatusCfdi
from app.models.nomina import Nomina, NominaDeduccion, NominaOtroPago, NominaPercepcion, NominaReceptor, NominaTotales
from tests import factories


async def insertar_nomina(
    db: AsyncSession,
    *,
    empresa_id: int,
    uuid: str,
    num_empleado: str = "039",
    rfc_receptor: str = "XAXX010101000",
    rfc_emisor: str = "CHL960913IX9",
    curp: str = "XXXX800101HCHXXX01",
    nss: str = "12345678901",
    fecha_pago: date = date(2026, 6, 30),
    fecha_inicial_pago: date | None = None,
    fecha_final_pago: date | None = None,
    periodicidad: str = "04",
    tipo_nomina: str = "O",
    dias: str = "15.000",
    percepciones: list[tuple[str, str, str, str, str]] | None = None,
    deducciones: list[tuple[str, str, str, str]] | None = None,
    otros_pagos: list[tuple[str, str, str, str, str]] | None = None,
    total_percepciones: str = "8759.70",
    total_deducciones: str = "591.10",
    total_otros_pagos: str = "0.00",
    total_gravado: str | None = None,
    total_exento: str | None = None,
    total_separacion: str | None = None,
    total_jubilacion: str | None = None,
    total_impuestos_retenidos: str | None = None,
    total_otras_deducciones: str | None = None,
    total: str = "8168.60",
    estatus: EstatusCfdi = EstatusCfdi.VIGENTE,
    tipo_regimen: str = "02",
    sbc: str = "583.98",
    sdi: str = "607.34",
    departamento: str = "Direccion",
    puesto: str = "Director",
    fecha_inicio_rel_laboral: date | None = None,
    banco: str | None = None,
    cuenta_bancaria: str | None = None,
    antiguedad: str | None = None,
    nombre_receptor: str | None = "JUANA INVENTADA DE PRUEBA",
    serie: str | None = None,
    error_normalizacion: str | None = None,
) -> int:
    """Inserta un CFDI de nómina normalizado (comprobante + complemento) y devuelve el
    `comprobante_id`.

    Las tuplas de `percepciones` son `(tipo, clave, concepto, gravado, exento)`; las de
    `deducciones`, `(tipo, clave, concepto, importe)`; las de `otros_pagos`,
    `(tipo, clave, concepto, importe, subsidio_causado)`.

    `nombre_receptor`, `serie` y `error_normalizacion` van a la fila de `comprobante_detalle`, que
    este helper inserta siempre (ver el docstring del módulo).
    """
    if fecha_inicial_pago is None:
        fecha_inicial_pago = date(fecha_pago.year, fecha_pago.month, 16)
    if fecha_final_pago is None:
        fecha_final_pago = fecha_pago

    comprobante = await factories.crear_comprobante(
        db,
        empresa_id=empresa_id,
        uuid=uuid,
        rfc_emisor=rfc_emisor,
        rfc_receptor=rfc_receptor,
        tipo_comprobante="N",
        estatus=estatus,
        total=Decimal(total),
        fecha_emision=None,
    )
    cid = comprobante.comprobante_id
    # Fila 1:1 de `comprobante_detalle` (spec §5.1): de aquí sale "Nombre empleado" en B-01, B-02,
    # B-05, B-07 y B-10, y `error_normalizacion` es lo que dispara `DATOS_DE_CORRIDA_ANTERIOR`.
    # `xml_hash` y `etl_version` son NOT NULL en el modelo, así que se fijan a un valor de prueba.
    db.add(
        ComprobanteDetalle(
            comprobante_id=cid,
            serie=serie,
            nombre_receptor=nombre_receptor,
            xml_hash=f"{cid:064d}",
            etl_version=1,
            error_normalizacion=error_normalizacion,
        )
    )
    db.add(
        Nomina(
            comprobante_id=cid,
            version_nomina="1.2",
            tipo_nomina=tipo_nomina,
            fecha_pago=fecha_pago,
            fecha_inicial_pago=fecha_inicial_pago,
            fecha_final_pago=fecha_final_pago,
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
            curp=curp,
            nss=nss,
            num_empleado=num_empleado,
            departamento=departamento,
            puesto=puesto,
            periodicidad_pago=periodicidad,
            tipo_regimen=tipo_regimen,
            salario_base_cot_apor=Decimal(sbc),
            salario_diario_integrado=Decimal(sdi),
            fecha_inicio_rel_laboral=fecha_inicio_rel_laboral,
            banco=banco,
            cuenta_bancaria=cuenta_bancaria,
            antiguedad=antiguedad,
        )
    )
    if percepciones is None:
        percepciones = [("001", "001", "Sueldo", total_percepciones, "0.00")]
    # `total_gravado`/`total_exento` del encabezado se derivan de los NODOS por defecto, para que las
    # identidades #4 y #5 de B-00 se cumplan por construcción (revisión final de la fase 2). Antes
    # eran `total_percepciones` y `0` fijos, lo que dejaba descuadrado cualquier fixture con importe
    # exento — invisible mientras ningún informe cotejaba esas dos identidades al generarse, y ahora
    # sí las cotejan (`universo_nomina.banderas_de_gravado_y_exento_descuadrados`). Se pueden fijar a
    # mano para construir un descuadre a propósito, que es justo lo que prueban
    # `test_gravado_declarado_descuadrado_emite_bandera` y su gemela del exento.
    gravado_de_nodos = sum((Decimal(g) for _t, _c, _con, g, _e in percepciones), Decimal("0"))
    exento_de_nodos = sum((Decimal(e) for _t, _c, _con, _g, e in percepciones), Decimal("0"))
    db.add(
        NominaTotales(
            comprobante_id=cid,
            total_gravado=Decimal(total_gravado) if total_gravado is not None else gravado_de_nodos,
            total_exento=Decimal(total_exento) if total_exento is not None else exento_de_nodos,
            total_separacion_indemnizacion=Decimal(total_separacion) if total_separacion is not None else None,
            total_jubilacion_pension_retiro=Decimal(total_jubilacion) if total_jubilacion is not None else None,
            total_impuestos_retenidos=Decimal(total_impuestos_retenidos) if total_impuestos_retenidos is not None else None,
            total_otras_deducciones=Decimal(total_otras_deducciones) if total_otras_deducciones is not None else None,
        )
    )
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
    if otros_pagos is None:
        otros_pagos = []
    for tipo, clave, concepto, importe, subsidio_causado in otros_pagos:
        db.add(
            NominaOtroPago(
                comprobante_id=cid,
                tipo_otro_pago=tipo,
                clave=clave,
                concepto=concepto,
                importe=Decimal(importe),
                subsidio_causado=Decimal(subsidio_causado) if subsidio_causado else None,
            )
        )
    await db.commit()
    return cid
