"""Los cinco endpoints de la tarifa del ISR (Anexo 8 de la RMF) — Task 6, doc 05 §8bis.

Lo que estas pruebas fijan, en una frase: **una tarifa sin confirmar no calcula, y confirmar
exige la huella de lo que se revisó** — el mismo invariante que ya fijó
`tests/test_api_configuracion.py` para `param_fiscal`, aplicado a una tabla con renglones en
vez de un escalar. Dos cosas nuevas que ese precedente no cubre:

- **La subida de un archivo real** (el PDF del Anexo 8) puede fallar de tres formas distintas
  —demasiado grande, no es un PDF válido, no trae ninguna tarifa reconocible— y cada una tiene
  que traducirse al código HTTP correcto sin que el mensaje del módulo se pierda ni se reescriba.
- **La periodicidad que "aplica"** no es una preferencia de la pantalla: sale del universo real
  de CFDI de nómina (B-09.R1), así que estas pruebas insertan recibos de verdad para ejercerla.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bitacora import Bitacora
from app.models.enums import PeriodicidadTarifa, RolGlobal
from app.services import tarifa_isr as t
from tests import factories
from tests.helpers_nomina import insertar_nomina

ADMIN = {"Authorization": "Bearer uid-admin"}
ANEXO_2026 = Path(__file__).parent / "fixtures" / "anexo8-2026.pdf"


async def _admin(db: AsyncSession) -> None:
    await factories.crear_usuario(db, uid="uid-admin", correo="admin@demo.test", rol_global=RolGlobal.ADMIN)


def _quincenal() -> list[t.Renglon]:
    """Tarifa de 15 días válida (pasa las seis pruebas del Anexo I.1), a propósito **distinta**
    de la que trae el documento real de 2026 (esa tiene 11 renglones, ver `test_anexo8.py`):
    así una corrección manual con estos valores nunca coincide con el PDF por accidente, que es
    justo lo que la prueba de reimportación protegida necesita ejercer."""
    return [
        t.Renglon(1, Decimal("0.01"), Decimal("416.70"), Decimal("0.00"), Decimal("0.0192")),
        t.Renglon(2, Decimal("416.71"), Decimal("3537.15"), Decimal("7.95"), Decimal("0.0640")),
        t.Renglon(3, Decimal("3537.16"), Decimal("6216.15"), Decimal("207.75"), Decimal("0.1088")),
        t.Renglon(4, Decimal("6216.16"), Decimal("7225.95"), Decimal("499.20"), Decimal("0.1600")),
        t.Renglon(5, Decimal("7225.96"), None, Decimal("660.75"), Decimal("0.3500")),
    ]


def _cuerpo(renglones: list[t.Renglon]) -> dict[str, Any]:
    return {
        "renglones": [
            {
                "renglon": r.renglon,
                "limite_inferior": str(r.limite_inferior),
                "limite_superior": str(r.limite_superior) if r.limite_superior is not None else None,
                "cuota_fija": str(r.cuota_fija),
                "tasa_excedente": str(r.tasa_excedente),
            }
            for r in renglones
        ]
    }


async def _contar_bitacora(db: AsyncSession, accion: str) -> int:
    return (await db.scalar(select(func.count()).select_from(Bitacora).where(Bitacora.accion == accion))) or 0


# --------------------------------------------------------------------------------------
# 1-2: importar el Anexo 8 real deja propuestas, con su bitácora
# --------------------------------------------------------------------------------------


async def test_importar_el_anexo_real_deja_siete_propuestas(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    r = await client.post(
        "/v1/configuracion/tarifa-isr/importar",
        files={"archivo": ("anexo8-2026.pdf", ANEXO_2026.read_bytes(), "application/pdf")},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert len(cuerpo["tarifas"]) == 7
    assert all(tarifa["confirmada"] is False for tarifa in cuerpo["tarifas"])
    assert all(tarifa["origen"] == "IMPORTADA" for tarifa in cuerpo["tarifas"])


async def test_importar_escribe_bitacora_en_la_misma_transaccion(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    r = await client.post(
        "/v1/configuracion/tarifa-isr/importar",
        files={"archivo": ("anexo8-2026.pdf", ANEXO_2026.read_bytes(), "application/pdf")},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text

    fila = await db.scalar(
        select(Bitacora).where(
            Bitacora.accion == "importar_tarifa_isr",
            Bitacora.entidad == "tarifa_isr:2026/DIAS_15",
        )
    )
    assert fila is not None
    assert fila.actor == "admin@demo.test"
    assert await _contar_bitacora(db, "importar_tarifa_isr") == 7


# --------------------------------------------------------------------------------------
# 3: la configuración fiscal es de administrador
# --------------------------------------------------------------------------------------


async def test_un_operador_no_puede_importar(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)

    r = await client.post(
        "/v1/configuracion/tarifa-isr/importar",
        files={"archivo": ("anexo8-2026.pdf", ANEXO_2026.read_bytes(), "application/pdf")},
        headers={"Authorization": "Bearer uid-op"},
    )
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------------------
# 4-5: un documento que no sirve se rechaza con el mensaje del módulo, tal cual
# --------------------------------------------------------------------------------------


async def test_un_archivo_que_no_es_el_anexo_devuelve_422_con_mensaje_en_espanol(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    r = await client.post(
        "/v1/configuracion/tarifa-isr/importar",
        files={"archivo": ("no-es-un-pdf.pdf", b"esto no es un PDF, es basura", "application/pdf")},
        headers=ADMIN,
    )
    assert r.status_code == 422, r.text
    cuerpo = r.json()["error"]
    assert cuerpo["codigo"] == "DOCUMENTO_INVALIDO"
    assert "Anexo 8" in cuerpo["mensaje"]
    # El nombre de la clase de excepción es para el log, nunca para la respuesta.
    assert "DocumentoInvalido" not in cuerpo["mensaje"]


async def test_un_archivo_mayor_al_limite_devuelve_413(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    basura = b"0" * (11 * 1024 * 1024)
    r = await client.post(
        "/v1/configuracion/tarifa-isr/importar",
        files={"archivo": ("demasiado-grande.pdf", basura, "application/pdf")},
        headers=ADMIN,
    )
    assert r.status_code == 413, r.text
    cuerpo = r.json()["error"]
    assert cuerpo["codigo"] == "ARCHIVO_DEMASIADO_GRANDE"
    assert "1 MB" in cuerpo["mensaje"], "el mensaje dice el tamaño esperado, no solo que es grande"


# --------------------------------------------------------------------------------------
# 6-7: la corrección manual entra por la misma puerta de validación
# --------------------------------------------------------------------------------------


async def test_corregir_un_renglon_limpia_la_confirmacion_y_deja_origen_manual(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/tarifa-isr/2026/DIAS_15", json=_cuerpo(_quincenal()), headers=ADMIN
    )
    assert r.status_code == 200, r.text
    huella = r.json()["huella"]

    r = await client.post(
        "/v1/configuracion/tarifa-isr/2026/DIAS_15/confirmar", json={"huella": huella}, headers=ADMIN
    )
    assert r.status_code == 200, r.text
    assert r.json()["confirmada"] is True

    # Corregir un renglón después de confirmar: una cifra distinta es una tarifa nueva.
    corregida = _quincenal()
    corregida[-1] = t.Renglon(5, Decimal("7225.96"), None, Decimal("665.00"), Decimal("0.3500"))
    r = await client.put(
        "/v1/configuracion/tarifa-isr/2026/DIAS_15", json=_cuerpo(corregida), headers=ADMIN
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["origen"] == "MANUAL"
    assert cuerpo["confirmada"] is False, "corregir limpia la confirmación anterior"
    assert cuerpo["difiere_del_documento"] is True


async def test_corregir_con_un_hueco_devuelve_422_diciendo_el_valor_esperado(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    con_hueco = _quincenal()
    con_hueco[1] = t.Renglon(2, Decimal("416.72"), Decimal("3537.15"), Decimal("7.95"), Decimal("0.0640"))

    r = await client.put(
        "/v1/configuracion/tarifa-isr/2026/DIAS_15", json=_cuerpo(con_hueco), headers=ADMIN
    )
    assert r.status_code == 422, r.text
    cuerpo = r.json()["error"]
    assert cuerpo["codigo"] == "TARIFA_INVALIDA"
    assert "416.71" in cuerpo["mensaje"], "el mensaje dice el valor correcto, no solo que está mal"
    assert "TarifaInvalida" not in cuerpo["mensaje"]


# --------------------------------------------------------------------------------------
# 8-9: confirmar exige la huella de lo que se revisó
# --------------------------------------------------------------------------------------


async def test_confirmar_con_la_huella_correcta_activa_la_tarifa(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/tarifa-isr/2026/DIAS_10", json=_cuerpo(_quincenal()), headers=ADMIN
    )
    assert r.status_code == 200, r.text
    huella = r.json()["huella"]

    r = await client.post(
        "/v1/configuracion/tarifa-isr/2026/DIAS_10/confirmar", json={"huella": huella}, headers=ADMIN
    )
    assert r.status_code == 200, r.text
    assert r.json()["confirmada"] is True
    assert r.json()["confirmado_por"] == "admin@demo.test"


async def test_confirmar_con_una_huella_vieja_devuelve_409(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/tarifa-isr/2026/DIAS_10", json=_cuerpo(_quincenal()), headers=ADMIN
    )
    huella_vieja = r.json()["huella"]

    # Otra corrección cambia la huella antes de que se confirme la primera lectura.
    otra = _quincenal()
    otra[-1] = t.Renglon(5, Decimal("7225.96"), None, Decimal("700.00"), Decimal("0.3500"))
    r = await client.put(
        "/v1/configuracion/tarifa-isr/2026/DIAS_10", json=_cuerpo(otra), headers=ADMIN
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        "/v1/configuracion/tarifa-isr/2026/DIAS_10/confirmar", json={"huella": huella_vieja}, headers=ADMIN
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["codigo"] == "TARIFA_CAMBIO"


# --------------------------------------------------------------------------------------
# 10: reimportar no pisa una corrección manual en silencio
# --------------------------------------------------------------------------------------


async def test_reimportar_sobre_una_correccion_manual_devuelve_409(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/tarifa-isr/2026/DIAS_15", json=_cuerpo(_quincenal()), headers=ADMIN
    )
    assert r.status_code == 200, r.text
    huella_manual = r.json()["huella"]

    r = await client.post(
        "/v1/configuracion/tarifa-isr/importar",
        files={"archivo": ("anexo8-2026.pdf", ANEXO_2026.read_bytes(), "application/pdf")},
        headers=ADMIN,
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["codigo"] == "CORRECCION_MANUAL"

    # La corrección sigue en pie, intacta: el intento de reimportar no la tocó.
    r = await client.get("/v1/configuracion/tarifa-isr", headers=ADMIN)
    assert r.status_code == 200, r.text
    tarifas = {(x["ejercicio"], x["periodicidad"]): x for x in r.json()["tarifas"]}
    assert (2026, "DIAS_15") in tarifas
    assert tarifas[(2026, "DIAS_15")]["origen"] == "MANUAL"
    assert tarifas[(2026, "DIAS_15")]["huella"] == huella_manual
    # Nada del PDF se importó: es todo o nada por documento.
    assert (2026, "DIARIA") not in tarifas


# --------------------------------------------------------------------------------------
# 11: borrar solo opera sobre una propuesta sin confirmar
# --------------------------------------------------------------------------------------


async def test_borrar_una_propuesta_la_quita_y_borrar_una_confirmada_da_409(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/tarifa-isr/2026/DIAS_15", json=_cuerpo(_quincenal()), headers=ADMIN
    )
    assert r.status_code == 200, r.text

    r = await client.delete("/v1/configuracion/tarifa-isr/2026/DIAS_15", headers=ADMIN)
    assert r.status_code == 204, r.text

    r = await client.get("/v1/configuracion/tarifa-isr", headers=ADMIN)
    assert r.json()["tarifas"] == []

    # Una confirmada no se borra así: hay que corregir o reimportar encima.
    r = await client.put(
        "/v1/configuracion/tarifa-isr/2026/DIAS_10", json=_cuerpo(_quincenal()), headers=ADMIN
    )
    huella = r.json()["huella"]
    r = await client.post(
        "/v1/configuracion/tarifa-isr/2026/DIAS_10/confirmar", json={"huella": huella}, headers=ADMIN
    )
    assert r.status_code == 200, r.text

    r = await client.delete("/v1/configuracion/tarifa-isr/2026/DIAS_10", headers=ADMIN)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["codigo"] == "TARIFA_CONFIRMADA"

    r = await client.get("/v1/configuracion/tarifa-isr", headers=ADMIN)
    assert [x["periodicidad"] for x in r.json()["tarifas"]] == ["DIAS_10"], "la confirmada sigue ahí"


# --------------------------------------------------------------------------------------
# 12-13: la periodicidad que aplica sale del universo real de CFDI de nómina (B-09.R1)
# --------------------------------------------------------------------------------------


async def test_listar_incluye_la_comprobacion_y_la_periodicidad_que_aplica(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="11111111-1111-4111-8111-111111111111",
        periodicidad="04",  # quincenal → DIAS_15
        total_gravado="5000.00",
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    r = await client.put(
        "/v1/configuracion/tarifa-isr/2026/DIAS_15", json=_cuerpo(_quincenal()), headers=ADMIN
    )
    assert r.status_code == 200, r.text

    r = await client.get("/v1/configuracion/tarifa-isr", headers=ADMIN)
    assert r.status_code == 200, r.text
    tarifas = r.json()["tarifas"]
    assert len(tarifas) == 1
    quincenal = tarifas[0]
    assert quincenal["periodicidad"] == "DIAS_15"
    assert quincenal["aplica_a_la_nomina"] is True
    assert quincenal["comprobacion"] is not None
    assert quincenal["comprobacion"]["uuid"] == "11111111-1111-4111-8111-111111111111"
    assert quincenal["comprobacion"]["isr_timbrado"] == "366.910000"
    assert r.json()["periodicidades_sin_tarifa"] == []


async def test_aplica_a_la_nomina_exige_tambien_el_ejercicio_actual(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """En cuanto convivan el Anexo 8 de dos ejercicios para la misma periodicidad —lo normal en
    diciembre, cuando se importa el del año que entra sin haber descartado el del que termina—,
    solo la del ejercicio en curso puede decir "es la que aplica a tu nómina". Sin el ejercicio en
    la comparación, las dos tarjetas de la misma periodicidad lo dirían a la vez, las dos
    expandidas."""
    await _admin(db)
    anio_actual = date.today().year
    anio_pasado = anio_actual - 1
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="33333333-3333-4333-8333-333333333333",
        periodicidad="04",  # quincenal → DIAS_15
        total_gravado="5000.00",
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    r = await client.put(f"/v1/configuracion/tarifa-isr/{anio_actual}/DIAS_15", json=_cuerpo(_quincenal()), headers=ADMIN)
    assert r.status_code == 200, r.text
    r = await client.put(f"/v1/configuracion/tarifa-isr/{anio_pasado}/DIAS_15", json=_cuerpo(_quincenal()), headers=ADMIN)
    assert r.status_code == 200, r.text

    r = await client.get("/v1/configuracion/tarifa-isr", headers=ADMIN)
    assert r.status_code == 200, r.text
    tarifas = {x["ejercicio"]: x for x in r.json()["tarifas"]}
    assert tarifas[anio_actual]["aplica_a_la_nomina"] is True
    assert tarifas[anio_pasado]["aplica_a_la_nomina"] is False


async def test_listar_avisa_cuando_la_nomina_usa_una_periodicidad_sin_tarifa_publicada(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    await insertar_nomina(
        db,
        empresa_id=empresa.empresa_id,
        uuid="22222222-2222-4222-8222-222222222222",
        periodicidad="03",  # catorcenal: el Anexo no la publica
        total_gravado="5000.00",
        deducciones=[("002", "002", "ISR", "366.91")],
    )
    await db.commit()

    r = await client.get("/v1/configuracion/tarifa-isr", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["tarifas"] == []
    assert r.json()["periodicidades_sin_tarifa"] == ["03"]
