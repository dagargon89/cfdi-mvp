"""Disparador 2 (spec §6.3): reproceso por lote de los XML que ya están en disco."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.cfdi_detalle import CfdiConcepto, ComprobanteDetalle
from app.models.nomina import NominaPercepcion
from app.services import normalizacion_lote
from app.services.normalizacion import DatosComprobante
from tests import factories, fixtures_cfdi


async def _comprobante_con_xml(db: AsyncSession, empresa_id: int, uuid: str, xml: bytes, tipo: str) -> int:
    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), "comprobantes")
    os.makedirs(carpeta, exist_ok=True)
    nombre = f"{uuid}.xml"
    with open(os.path.join(carpeta, nombre), "wb") as f:
        f.write(xml)
    ruta_relativa = os.path.join(str(empresa_id), "comprobantes", nombre)
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa_id, uuid=uuid, tipo_comprobante=tipo, xml_path=ruta_relativa
    )
    return comprobante.comprobante_id


async def test_normaliza_lote_y_es_idempotente(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    cid = await _comprobante_con_xml(db, empresa.empresa_id, "77777777-7777-7777-7777-777777777777", fixtures_cfdi.cfdi_nomina(), "N")

    resumen = await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [cid])
    assert resumen == {"normalizados": 1, "con_error": 0, "omitidos": 0}
    assert await db.scalar(select(func.count()).select_from(NominaPercepcion).where(NominaPercepcion.comprobante_id == cid)) == 2

    # Segunda corrida: mismo hash y misma versión del ETL → se omite, no se reprocesa.
    resumen = await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [cid])
    assert resumen == {"normalizados": 0, "con_error": 0, "omitidos": 1}
    assert await db.scalar(select(func.count()).select_from(NominaPercepcion).where(NominaPercepcion.comprobante_id == cid)) == 2


async def test_lote_totalmente_omitido_no_deja_transaccion_abierta(db: AsyncSession) -> None:
    """Ronda de corrección: si TODOS los comprobantes del lote caen en la rama de
    "omitido" (el caso normal del pre-vuelo de la tarea 13, que reusará este servicio
    justo antes de consultar el informe con la misma sesión), el único `SELECT` que abre
    `normalizar_lote` no debe dejar una transacción de lectura abierta al retornar — si
    la dejara, quien siga usando `db` heredaría un snapshot de `REPEATABLE READ` de antes
    de normalizar y no vería lo que él mismo acaba de escribir."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    cid = await _comprobante_con_xml(db, empresa.empresa_id, "dddddddd-dddd-dddd-dddd-dddddddddddd", fixtures_cfdi.cfdi_ingreso(uuid="dddddddd-dddd-dddd-dddd-dddddddddddd"), "I")

    # Primera corrida: normaliza. Segunda corrida: todo el lote se omite (mismo hash/ETL_VERSION).
    await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [cid])
    resumen = await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [cid])
    assert resumen == {"normalizados": 0, "con_error": 0, "omitidos": 1}

    assert db.in_transaction() is False


async def test_xml_ausente_en_disco_cuenta_como_error_no_como_excepcion(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    comprobante = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="88888888-8888-8888-8888-888888888888", xml_path="11/comprobantes/no-existe.xml"
    )

    resumen = await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [comprobante.comprobante_id])
    assert resumen == {"normalizados": 0, "con_error": 1, "omitidos": 0}

    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == comprobante.comprobante_id))
    assert detalle is not None
    assert detalle.error_normalizacion is not None


async def test_un_xml_corrupto_no_aborta_el_lote(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    malo = await _comprobante_con_xml(db, empresa.empresa_id, "99999999-9999-9999-9999-999999999999", b"<esto no es un cfdi>", "I")
    bueno = await _comprobante_con_xml(db, empresa.empresa_id, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", fixtures_cfdi.cfdi_ingreso(), "I")

    resumen = await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [malo, bueno])
    assert resumen == {"normalizados": 1, "con_error": 1, "omitidos": 0}

    detalle_bueno = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == bueno))
    assert detalle_bueno is not None
    assert detalle_bueno.error_normalizacion is None


async def test_fallo_a_mitad_de_flush_no_envenena_el_resto_del_lote(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ronda de corrección (misma lección de la tarea 8): un `ValueError` puro de
    `normalizar()` nunca toca la BD, así que no prueba nada sobre el aislamiento de la
    transacción. Este caso es el que de verdad importa: `escribir()` truena **a mitad de
    un `flush`** — como pasaría con un `DataError` real de MySQL porque un valor del XML
    no entra en una columna acotada (`comprobante_detalle.moneda` es `CHAR(3)`, spec §5).

    A diferencia del escritor de la tarea 7 (que nunca commitea y se protege con un
    SAVEPOINT en el caller, ver `app/services/resguardo.py`), `normalizar_lote` sí
    commitea por comprobante — así que aquí el orden `rollback()` → `registrar_error()`
    → `commit()` dentro del propio `except` es lo que evita el `PendingRollbackError`,
    sin necesitar ningún savepoint."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    malo = await _comprobante_con_xml(db, empresa.empresa_id, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", fixtures_cfdi.cfdi_ingreso(uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), "I")
    bueno = await _comprobante_con_xml(db, empresa.empresa_id, "cccccccc-cccc-cccc-cccc-cccccccccccc", fixtures_cfdi.cfdi_ingreso(uuid="cccccccc-cccc-cccc-cccc-cccccccccccc"), "I")

    escribir_original = normalizacion_lote.repo_normalizacion.escribir
    llamadas: list[int] = []

    async def _escribir_con_fallo_en_el_primero(
        db_: AsyncSession, comprobante_id: int, datos: DatosComprobante, xml_hash: str
    ) -> None:
        llamadas.append(comprobante_id)
        if len(llamadas) == 1:
            # `DataError` real de MySQL a mitad de un `flush`, no un `ValueError` de
            # mentiras: este valor no entra en `comprobante_detalle.moneda` (`CHAR(3)`).
            db_.add(ComprobanteDetalle(comprobante_id=comprobante_id, moneda="DEMASIADO_LARGO", xml_hash=xml_hash, etl_version=1))
            await db_.flush()
            return
        await escribir_original(db_, comprobante_id, datos, xml_hash)

    monkeypatch.setattr(normalizacion_lote.repo_normalizacion, "escribir", _escribir_con_fallo_en_el_primero)

    resumen = await normalizacion_lote.normalizar_lote(db, empresa.empresa_id, [malo, bueno])
    assert resumen == {"normalizados": 1, "con_error": 1, "omitidos": 0}

    detalle_malo = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == malo))
    assert detalle_malo is not None
    assert detalle_malo.error_normalizacion is not None

    detalle_bueno = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == bueno))
    assert detalle_bueno is not None
    assert detalle_bueno.error_normalizacion is None
    conceptos = (await db.scalars(select(CfdiConcepto).where(CfdiConcepto.comprobante_id == bueno))).all()
    assert len(conceptos) > 0  # normalizado de verdad, con hijos en las tablas


async def test_endpoint_de_reproceso_encola_y_pide_operador(client, db: AsyncSession, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.models.enums import RolEmpresa, RolGlobal
    from app.worker import tasks

    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    operador = await factories.crear_usuario(db, uid="op", correo="op@test.mx", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)
    consulta = await factories.crear_usuario(db, uid="con", correo="con@test.mx", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, consulta, empresa, RolEmpresa.CONSULTA)

    encoladas: list[tuple[int, str]] = []

    class _Tarea:
        id = "tarea-fake"

    monkeypatch.setattr(
        tasks.normalizar_comprobantes,
        "delay",
        lambda empresa_id, alcance, ids=None: (encoladas.append((empresa_id, alcance)), _Tarea())[1],
    )

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/informes/normalizar",
        json={"alcance": "pendientes"},
        headers={"Authorization": "Bearer op"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["tarea_id"] == "tarea-fake"
    assert encoladas == [(empresa.empresa_id, "pendientes")]

    # Rol de consulta no puede disparar un reproceso.
    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/informes/normalizar",
        json={"alcance": "pendientes"},
        headers={"Authorization": "Bearer con"},
    )
    assert r.status_code == 403
