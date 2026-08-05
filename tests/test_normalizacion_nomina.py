"""ETL del complemento de Nómina 1.2.

Estas pruebas fijan los tres errores que el documento fuente advierte como los más
frecuentes: `@Antigüedad` lleva diéresis en el nombre del atributo, el mismo
`(tipo, clave)` puede repetirse y debe sumarse (B-02.R1), y el caso espejo del fondo de
ahorro NO se consolida (R-T10).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services import normalizacion
from tests import fixtures_cfdi


def test_normaliza_cabecera_de_nomina() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina())

    assert datos.nomina is not None
    cab = datos.nomina.cabecera
    assert cab.version_nomina == "1.2"
    assert cab.tipo_nomina == "O"
    assert cab.fecha_pago == date(2026, 6, 30)
    assert cab.fecha_inicial_pago == date(2026, 6, 16)
    assert cab.fecha_final_pago == date(2026, 6, 30)
    assert cab.num_dias_pagados == Decimal("15.000")
    assert cab.total_percepciones == Decimal("9259.70")
    assert cab.registro_patronal == "B5510768108"


def test_normaliza_receptor_con_antiguedad_con_dieresis() -> None:
    """`@Antigüedad` lleva diéresis en el nombre del atributo — fuente frecuente de
    fallos de parseo (§2.7 del fuente). Se guarda como texto, nunca como número."""
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina())

    assert datos.nomina is not None
    r = datos.nomina.receptor
    assert r.antiguedad == "P663W"
    assert r.curp == "XXXX800101HCHXXX01"
    assert r.nss == "12345678901"
    assert r.fecha_inicio_rel_laboral == date(2013, 9, 1)
    assert r.periodicidad_pago == "04"
    assert r.tipo_contrato == "01"
    assert r.num_empleado == "039"
    assert r.riesgo_puesto == "1"
    assert r.salario_base_cot_apor == Decimal("583.98")
    assert r.salario_diario_integrado == Decimal("607.34")
    assert r.clave_ent_fed == "CHH"


def test_normaliza_percepciones_deducciones_y_otros_pagos() -> None:
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina())
    assert datos.nomina is not None
    nom = datos.nomina

    assert [(p.tipo_percepcion, p.clave, p.importe_gravado, p.importe_exento) for p in nom.percepciones] == [
        ("001", "001", Decimal("8759.70"), Decimal("0.00")),
        ("005", "031", Decimal("0.00"), Decimal("500.00")),
    ]
    assert [(d.tipo_deduccion, d.clave, d.importe) for d in nom.deducciones] == [
        ("001", "052", Decimal("200.00")),
        ("002", "045", Decimal("391.10")),
        ("004", "067", Decimal("500.00")),
    ]
    assert len(nom.otros_pagos) == 1
    otro = nom.otros_pagos[0]
    assert (otro.tipo_otro_pago, otro.clave, otro.importe) == ("002", "035", Decimal("0.00"))
    assert otro.subsidio_causado == Decimal("0.00")

    assert nom.totales.total_gravado == Decimal("8759.70")
    assert nom.totales.total_exento == Decimal("500.00")
    assert nom.totales.total_impuestos_retenidos == Decimal("391.10")
    assert nom.totales.total_otras_deducciones == Decimal("700.00")


def test_concepto_repetido_se_conserva_como_dos_filas() -> None:
    """B-02.R1: el ETL NO consolida. Devuelve los dos nodos tal cual y es el informe el
    que los suma. Colapsarlos aquí perdería la trazabilidad contra el XML."""
    percepciones = (
        '<nomina12:Percepcion TipoPercepcion="019" Clave="019" Concepto="Horas extra" '
        'ImporteGravado="300.00" ImporteExento="0.00" />'
        '<nomina12:Percepcion TipoPercepcion="019" Clave="019" Concepto="Horas extra" '
        'ImporteGravado="450.00" ImporteExento="0.00" />'
    )
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina(percepciones_xml=percepciones))

    assert datos.nomina is not None
    repetidas = [p for p in datos.nomina.percepciones if p.tipo_percepcion == "019"]
    assert len(repetidas) == 2
    assert sum(p.importe_gravado for p in repetidas) == Decimal("750.00")


def test_espejo_del_fondo_de_ahorro_se_conserva_en_las_tres_naturalezas() -> None:
    """R-T10: el mismo flujo aparece como percepción exenta, deducción y otro pago. El
    ETL refleja el XML; consolidar aquí falsearía el informe."""
    datos = normalizacion.normalizar(
        fixtures_cfdi.cfdi_nomina(
            otros_pagos_xml='<nomina12:OtroPago TipoOtroPago="999" Clave="099" Concepto="Fondo ahorro" Importe="500.00" />'
        )
    )
    assert datos.nomina is not None
    nom = datos.nomina
    assert any(p.tipo_percepcion == "005" and p.importe_exento == Decimal("500.00") for p in nom.percepciones)
    assert any(d.tipo_deduccion == "004" and d.importe == Decimal("500.00") for d in nom.deducciones)
    assert any(o.importe == Decimal("500.00") for o in nom.otros_pagos)


def test_incapacidad_cuando_el_nodo_existe() -> None:
    incapacidades = (
        "<nomina12:Incapacidades>"
        '<nomina12:Incapacidad DiasIncapacidad="3" TipoIncapacidad="02" ImporteMonetario="1200.00" />'
        "</nomina12:Incapacidades>"
    )
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina(incapacidades_xml=incapacidades))

    assert datos.nomina is not None
    assert len(datos.nomina.incapacidades) == 1
    inc = datos.nomina.incapacidades[0]
    assert (inc.dias_incapacidad, inc.tipo_incapacidad, inc.importe_monetario) == (3, "02", Decimal("1200.00"))


def test_sin_nodos_opcionales_no_truena() -> None:
    """Los 8 CFDI reales de la empresa 11 no traen `Incapacidades`. Ausente ≠ error."""
    datos = normalizacion.normalizar(fixtures_cfdi.cfdi_nomina())
    assert datos.nomina is not None
    assert datos.nomina.incapacidades == []
