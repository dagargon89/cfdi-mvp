"""La hoja que revisa un contador. Lo que estas pruebas fijan es qué **no** puede faltar en ella.

El dueño del Hub no es contador; quien tiene que validar fiscalmente la tarifa es su contador, que
no tiene cuenta en la aplicación (darle admin le abriría la bóveda de e.firmas, los usuarios y la
bitácora completa). La solución acordada: el dueño confirma, y esta hoja es lo que le manda a su
contador para que la revise antes.

`hoja_html`/`hoja_pdf` son funciones puras sobre `TarifaGuardada` (Task 4) y `Comprobacion`
(Task 5) — las primeras pruebas de este archivo no tocan la base de datos ni necesitan las
fixtures pesadas de `conftest.py` (MySQL efímero, Firebase falso).

Al final va un puñado de pruebas del endpoint `GET .../hoja-revision` — que la ruta responda un
PDF, que sea `require_admin`, que un 404 diga qué tarifa falta, y que **no escriba bitácora**
(es una lectura, a diferencia de importar, corregir, confirmar o borrar).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bitacora import Bitacora
from app.models.enums import OrigenTarifa, PeriodicidadTarifa, RolGlobal
from app.repositories.tarifa_isr import TarifaGuardada
from app.services import revision_tarifa
from app.services import tarifa_isr as t
from app.services.comprobacion_tarifa import Comprobacion
from tests import factories

ADMIN = {"Authorization": "Bearer uid-admin-revision"}


async def _admin(db: AsyncSession) -> None:
    await factories.crear_usuario(db, uid="uid-admin-revision", correo="admin-revision@demo.test", rol_global=RolGlobal.ADMIN)


async def _contar_bitacora(db: AsyncSession) -> int:
    return (await db.scalar(select(func.count()).select_from(Bitacora))) or 0

# Tres renglones bastan: el tercero, abierto, lleva una tasa (21.36 %) elegida para que la prueba
# del porcentaje no pueda confundirse con una casualidad de redondeo.
_RENGLONES = (
    t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
    t.Renglon(2, Decimal("416.71"), Decimal("3537.15"), Decimal("7.95"), Decimal("0.0640")),
    t.Renglon(3, Decimal("3537.16"), None, Decimal("207.75"), Decimal("0.2136")),
)


def _tarifa() -> TarifaGuardada:
    return TarifaGuardada(
        ejercicio=2026,
        periodicidad=PeriodicidadTarifa.DIAS_15,
        origen=OrigenTarifa.IMPORTADA,
        fuente="Anexo 8 DOF 28-12-2025",
        documento_sha256="a" * 64,
        encabezado="IV. Tarifa aplicable cuando hagan pagos que correspondan a un periodo de 15 dias",
        importado_en=datetime(2026, 8, 10, 12, 0),
        confirmado_por=None,
        confirmado_en=None,
        renglones=_RENGLONES,
    )


def _tarifa_confirmada() -> TarifaGuardada:
    base = _tarifa()
    return TarifaGuardada(
        ejercicio=base.ejercicio,
        periodicidad=base.periodicidad,
        origen=base.origen,
        fuente=base.fuente,
        documento_sha256=base.documento_sha256,
        encabezado=base.encabezado,
        importado_en=base.importado_en,
        confirmado_por="admin@demo.test",
        confirmado_en=datetime(2026, 8, 10, 13, 30),
        renglones=base.renglones,
    )


def _tarifa_manual() -> TarifaGuardada:
    base = _tarifa()
    return TarifaGuardada(
        ejercicio=base.ejercicio,
        periodicidad=base.periodicidad,
        origen=OrigenTarifa.MANUAL,
        fuente="Corrección manual de admin@demo.test el 2026-08-10",
        documento_sha256=None,
        encabezado=base.encabezado,
        importado_en=base.importado_en,
        confirmado_por=None,
        confirmado_en=None,
        renglones=base.renglones,
    )


def _comprobacion() -> Comprobacion:
    return Comprobacion(
        uuid="11111111-1111-4111-8111-111111111111",
        fecha_inicial_pago=date(2026, 8, 1),
        fecha_final_pago=date(2026, 8, 15),
        num_empleado="EMP-001",
        dias_pagados=Decimal("15"),
        gravado=Decimal("5000.00"),
        renglon=2,
        limite_inferior=Decimal("416.71"),
        tasa_excedente=Decimal("0.0640"),
        isr_calculado=Decimal("366.91"),
        isr_timbrado=Decimal("366.91"),
        diferencia=Decimal("0.00"),
        advertencias=("El recibo trae percepciones que no son sueldo ordinario.",),
    )


def test_la_hoja_trae_las_tasas_en_porcentaje() -> None:
    """Un contador lee 21.36 %, no 0.2136. La fracción también va, como dato secundario."""
    html = revision_tarifa.hoja_html(_tarifa(), None)
    assert "21.36" in html
    # La fracción cruda sigue presente, como dato secundario — no se reemplaza, se acompaña.
    assert "0.2136" in html


def test_la_hoja_cita_el_documento_y_su_huella() -> None:
    html = revision_tarifa.hoja_html(_tarifa(), None)
    assert "periodo de 15 dias" in html
    assert ("a" * 64) in html


def test_la_hoja_marca_los_renglones_editados_a_mano() -> None:
    """El aviso es **a nivel de tarifa, no por renglón**: `_escribir` (Task 4) reemplaza los
    renglones completos en cada corrección, así que no hay forma de saber cuál cambió de valor y
    cuál no. Marcar cada fila afirmaría que las tres cambiaron, que puede ser falso — por eso el
    aviso aparece una sola vez, no una por renglón (antes de este arreglo aparecía tres veces,
    una por fila de `_RENGLONES`)."""
    html = revision_tarifa.hoja_html(_tarifa_manual(), None)
    assert "editado a mano" in html.lower()
    assert html.lower().count("editado a mano") == 1


def test_la_hoja_no_dice_editado_a_mano_si_la_tarifa_es_importada() -> None:
    html = revision_tarifa.hoja_html(_tarifa(), None)
    assert "editado a mano" not in html.lower()


def test_el_aviso_de_edicion_manual_no_afirma_que_algun_renglon_cambio() -> None:
    """Guardar el modal de corrección sin tocar ningún valor también deja `origen: MANUAL`
    (comportamiento correcto y deliberado). El sistema no conserva cuál renglón cambió y cuál
    no, así que lo único que sabe de verdad es que hubo una edición manual — **no** que algún
    renglón tenga hoy un valor distinto del documento. Este defecto se detectó comparando un PDF
    real, renglón por renglón, contra el Anexo 8 oficial: los 11 renglones eran idénticos y el
    aviso, aun así, decía que "uno o más ya no son los del documento" — una afirmación falsa en
    un documento cuyo propósito es que el contador confíe en él sin poder mirar el sistema por
    dentro. El texto correcto solo afirma el hecho conocido (edición manual) y plantea la
    posibilidad de una diferencia, nunca la certeza."""
    html = revision_tarifa.hoja_html(_tarifa_manual(), None).lower()
    # Ninguna forma que afirme el hecho como consumado: "ya no son", "cambiaron", "ya no es".
    assert "ya no son" not in html
    assert "cambiaron" not in html
    # El texto sí tiene que dejar la posibilidad abierta y decir qué hacer al respecto.
    assert "puede que" in html
    assert "compara la tabla completa" in html


def test_la_hoja_muestra_la_fuente_y_la_fecha_de_importacion() -> None:
    """Parte de la procedencia que el brief exige junto a la huella (§7.4 del diseño): de dónde
    salió la tarifa y cuándo se cargó — nada que la prueba de la huella o el encabezado ya cubra."""
    html = revision_tarifa.hoja_html(_tarifa(), None)
    assert "Anexo 8 DOF 28-12-2025" in html
    assert "10/08/2026 12:00" in html


def test_la_hoja_dice_que_falta_confirmar_y_que_pasa_cuando_se_confirme() -> None:
    html = revision_tarifa.hoja_html(_tarifa(), None)
    assert "falta confirmar" in html.lower()


def test_la_hoja_dice_quien_confirmo_y_cuando_si_ya_esta_confirmada() -> None:
    html = revision_tarifa.hoja_html(_tarifa_confirmada(), None)
    assert "admin@demo.test" in html
    assert "falta confirmar" not in html.lower()


def test_la_hoja_rotula_la_comprobacion_como_no_dictamen() -> None:
    html = revision_tarifa.hoja_html(_tarifa(), _comprobacion())
    assert "no es un dictamen" in html.lower()
    assert "El recibo trae percepciones que no son sueldo ordinario." in html


def test_la_hoja_no_muestra_la_palabra_none_cuando_un_dato_de_la_comprobacion_falta() -> None:
    """`str(None)` es la cadena `"None"`, no vacía — un `or "—"` aplicado *después* de convertir a
    texto nunca dispara. Esta prueba fija que los campos opcionales de la comprobación (fechas,
    número de empleado, días pagados) se traducen a un guion, no al literal `None`."""
    sin_fechas = Comprobacion(
        uuid="22222222-2222-4222-8222-222222222222",
        fecha_inicial_pago=None,
        fecha_final_pago=None,
        num_empleado=None,
        dias_pagados=None,
        gravado=Decimal("5000.00"),
        renglon=2,
        limite_inferior=Decimal("416.71"),
        tasa_excedente=Decimal("0.0640"),
        isr_calculado=Decimal("366.91"),
        isr_timbrado=Decimal("366.91"),
        diferencia=Decimal("0.00"),
        advertencias=(),
    )
    html = revision_tarifa.hoja_html(_tarifa(), sin_fechas)
    assert "None" not in html
    assert "—" in html


def test_el_pdf_se_genera_y_pesa_algo() -> None:
    pdf = revision_tarifa.hoja_pdf(_tarifa(), _comprobacion())
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000


# --------------------------------------------------------------------------------------
# El endpoint: GET .../tarifa-isr/{ejercicio}/{periodicidad}/hoja-revision
# --------------------------------------------------------------------------------------


async def test_el_endpoint_devuelve_el_pdf_inline_y_no_escribe_bitacora(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Distinto de `_RENGLONES`: aquí hace falta una tarifa que pase las seis pruebas del Anexo
    I.1 completas (incluida la tasa del renglón abierto, que debe caer entre 0.30 y 0.40) para
    que el `PUT` de corrección la acepte — `_RENGLONES` solo sirve para ejercer `hoja_html`
    directamente, sin pasar por esa validación."""
    await _admin(db)
    renglones_validos = (
        t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
        t.Renglon(2, Decimal("416.71"), Decimal("3537.15"), Decimal("7.95"), Decimal("0.0640")),
        t.Renglon(3, Decimal("3537.16"), Decimal("6216.15"), Decimal("207.75"), Decimal("0.1088")),
        t.Renglon(4, Decimal("6216.16"), Decimal("7225.95"), Decimal("499.20"), Decimal("0.1600")),
        t.Renglon(5, Decimal("7225.96"), None, Decimal("660.75"), Decimal("0.3500")),
    )
    cuerpo_renglones = {
        "renglones": [
            {
                "renglon": r.renglon,
                "limite_inferior": str(r.limite_inferior),
                "limite_superior": str(r.limite_superior) if r.limite_superior is not None else None,
                "cuota_fija": str(r.cuota_fija),
                "tasa_excedente": str(r.tasa_excedente),
            }
            for r in renglones_validos
        ]
    }
    r = await client.put("/v1/configuracion/tarifa-isr/2026/DIAS_15", json=cuerpo_renglones, headers=ADMIN)
    assert r.status_code == 200, r.text

    antes = await _contar_bitacora(db)
    r = await client.get("/v1/configuracion/tarifa-isr/2026/DIAS_15/hoja-revision", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert 'filename="tarifa-isr-2026-quincenal.pdf"' in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF")
    # Es una lectura: generar la hoja no deja rastro en la bitácora, a diferencia de importar,
    # corregir, confirmar o borrar (que sí escriben, y ya lo fijan las pruebas de la Task 6).
    assert await _contar_bitacora(db) == antes


async def test_el_endpoint_es_solo_de_administrador(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await factories.crear_usuario(db, uid="uid-op-revision", correo="op-revision@demo.test", rol_global=RolGlobal.OPERADOR)
    r = await client.get(
        "/v1/configuracion/tarifa-isr/2026/DIAS_15/hoja-revision",
        headers={"Authorization": "Bearer uid-op-revision"},
    )
    assert r.status_code == 403, r.text


async def test_el_endpoint_da_404_si_no_hay_tarifa(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)
    r = await client.get("/v1/configuracion/tarifa-isr/2031/DIAS_15/hoja-revision", headers=ADMIN)
    assert r.status_code == 404, r.text
    assert r.json()["error"]["codigo"] == "TARIFA_NO_ENCONTRADA"
