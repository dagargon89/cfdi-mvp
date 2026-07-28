"""Tareas Celery de validación en lote y export (RF-VAL, RF-LIST-02) — lógica real, sin
Celery ni HTTP. `consultar_estatus_xml` se reemplaza por un doble: nunca toca el SAT real
(es un endpoint público, pero igual no hay razón para tocarlo en pruebas automatizadas)."""

from __future__ import annotations

import os

import openpyxl
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.models.comprobante import Comprobante
from app.models.enums import EstatusCfdi
from app.worker import tasks as worker_tasks
from tests.factories import crear_comprobante, crear_empresa

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _sesion_de_prueba_en_worker(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """`worker_tasks.SessionLocal` apunta a `DATABASE_URL` (placeholder en pruebas) — las
    tareas se prueban aquí llamando su lógica async directo (sin `asyncio.run`/Celery), así
    que basta apuntarlo al mismo engine que usa el fixture `db` (testcontainer real)."""
    monkeypatch.setattr(worker_tasks, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))


def _escribir_xml(empresa_id: int, contenido: bytes = b"<xml/>") -> str:
    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), "comprobantes")
    os.makedirs(carpeta, exist_ok=True)
    ruta_absoluta = os.path.join(carpeta, "prueba.xml")
    with open(ruta_absoluta, "wb") as f:
        f.write(contenido)
    return os.path.relpath(ruta_absoluta, get_settings().storage_root)


def _escribir_xml_valido(empresa_id: int, uuid: str, nombre_archivo: str) -> str:
    """A diferencia de `_escribir_xml` (bytes crudos, sirve para `validar_lote` porque
    `consultar_estatus_xml` va mockeado) — aquí se necesita un CFDI parseable de verdad
    porque `generar_pdf`/`generar_detalle` sí lo procesan con `satcfdi`."""
    from tests.test_resguardo import _xml

    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), "comprobantes")
    os.makedirs(carpeta, exist_ok=True)
    ruta_absoluta = os.path.join(carpeta, nombre_archivo)
    with open(ruta_absoluta, "wb") as f:
        f.write(_xml(uuid))
    return os.path.relpath(ruta_absoluta, get_settings().storage_root)


async def test_validar_lote_actualiza_estatus(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_tasks, "consultar_estatus_xml", lambda xml: "Vigente")
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    ruta = _escribir_xml(empresa.empresa_id)
    c = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111", xml_path=ruta)

    resultado = await worker_tasks._validar_lote_async(empresa.empresa_id, [c.comprobante_id])
    assert resultado == {"total": 1, "exitosos": 1, "fallidos": 0}

    await db.refresh(c)
    assert c.estatus is EstatusCfdi.VIGENTE
    assert c.estatus_verificado_at is not None


async def test_validar_lote_marca_cancelado(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_tasks, "consultar_estatus_xml", lambda xml: "Cancelado")
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    ruta = _escribir_xml(empresa.empresa_id)
    c = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="22222222-2222-2222-2222-222222222222", xml_path=ruta)

    await worker_tasks._validar_lote_async(empresa.empresa_id, [c.comprobante_id])
    await db.refresh(c)
    assert c.estatus is EstatusCfdi.CANCELADO


async def test_validar_lote_no_aborta_por_un_fallo_parcial(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """RF-VAL-02: un CFDI no consultable no aborta el lote."""

    def _falla_o_exito(xml: bytes) -> str:
        if xml == b"malo":
            raise RuntimeError("SAT no disponible")
        return "Vigente"

    monkeypatch.setattr(worker_tasks, "consultar_estatus_xml", _falla_o_exito)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    ruta_ok = _escribir_xml(empresa.empresa_id, b"bueno")
    c_ok = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="33333333-3333-3333-3333-333333333333", xml_path=ruta_ok)
    c_sin_archivo = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="44444444-4444-4444-4444-444444444444", xml_path=None)

    resultado = await worker_tasks._validar_lote_async(empresa.empresa_id, [c_ok.comprobante_id, c_sin_archivo.comprobante_id])
    assert resultado == {"total": 2, "exitosos": 1, "fallidos": 1}

    await db.refresh(c_ok)
    assert c_ok.estatus is EstatusCfdi.VIGENTE


async def test_exportar_excel_genera_archivo_streaming(db: AsyncSession) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="55555555-5555-5555-5555-555555555555", razon_social_emisor="ACME")
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="66666666-6666-6666-6666-666666666666", razon_social_emisor="OTRA")

    resultado = await worker_tasks._exportar_excel_async(empresa.empresa_id, {})
    assert resultado["filas"] == 2

    ruta_absoluta = os.path.join(get_settings().storage_root, resultado["ruta"])
    assert os.path.isfile(ruta_absoluta)

    wb = openpyxl.load_workbook(ruta_absoluta)
    ws = wb.active
    filas = list(ws.iter_rows(values_only=True))
    assert filas[0] == worker_tasks._COLUMNAS_EXPORT
    assert len(filas) == 3  # encabezado + 2 comprobantes


async def test_exportar_excel_respeta_filtros(db: AsyncSession) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="77777777-7777-7777-7777-777777777777", estatus=EstatusCfdi.VIGENTE)
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="88888888-8888-8888-8888-888888888888", estatus=EstatusCfdi.CANCELADO)

    resultado = await worker_tasks._exportar_excel_async(empresa.empresa_id, {"estatus": "cancelado"})
    assert resultado["filas"] == 1


async def test_validar_lote_scoped_a_empresa(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """`por_ids` (usado por la tarea) está acotado a `empresa_id` — un comprobante_id de otra
    empresa en la lista nunca se toca (defensa en profundidad además del check en la API)."""
    monkeypatch.setattr(worker_tasks, "consultar_estatus_xml", lambda xml: "Vigente")
    empresa_a = await crear_empresa(db, rfc="EKU9003173C9")
    empresa_b = await crear_empresa(db, rfc="XAXX010101000")
    ruta = _escribir_xml(empresa_b.empresa_id)
    c_de_b = await crear_comprobante(db, empresa_id=empresa_b.empresa_id, uuid="99999999-9999-9999-9999-999999999999", xml_path=ruta)

    resultado = await worker_tasks._validar_lote_async(empresa_a.empresa_id, [c_de_b.comprobante_id])
    assert resultado == {"total": 1, "exitosos": 0, "fallidos": 0}

    result = await db.scalar(select(Comprobante).where(Comprobante.comprobante_id == c_de_b.comprobante_id))
    assert result is not None
    assert result.estatus is EstatusCfdi.NO_VERIFICADO  # nunca se tocó


async def test_descargar_zip_lote_incluye_los_seleccionados(db: AsyncSession) -> None:
    import zipfile

    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    ruta1 = _escribir_xml_valido(empresa.empresa_id, "AAAA1111-1111-1111-1111-111111111111", "uno.xml")
    ruta2 = _escribir_xml_valido(empresa.empresa_id, "BBBB2222-2222-2222-2222-222222222222", "dos.xml")
    c1 = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="AAAA1111-1111-1111-1111-111111111111", xml_path=ruta1)
    c2 = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="BBBB2222-2222-2222-2222-222222222222", xml_path=ruta2)

    resultado = await worker_tasks._descargar_zip_lote_async(empresa.empresa_id, [c1.comprobante_id, c2.comprobante_id])
    assert resultado["solicitados"] == 2
    assert resultado["incluidos"] == 2

    ruta_zip = os.path.join(get_settings().storage_root, resultado["ruta"])
    assert os.path.isfile(ruta_zip)
    with zipfile.ZipFile(ruta_zip) as zf:
        nombres = set(zf.namelist())
        assert nombres == {
            "AAAA1111-1111-1111-1111-111111111111.xml",
            "AAAA1111-1111-1111-1111-111111111111.pdf",
            "AAAA1111-1111-1111-1111-111111111111_detalle.pdf",
            "BBBB2222-2222-2222-2222-222222222222.xml",
            "BBBB2222-2222-2222-2222-222222222222.pdf",
            "BBBB2222-2222-2222-2222-222222222222_detalle.pdf",
        }


async def test_descargar_zip_lote_omite_comprobante_sin_xml(db: AsyncSession) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    ruta_ok = _escribir_xml_valido(empresa.empresa_id, "CCCC3333-3333-3333-3333-333333333333", "tres.xml")
    c_ok = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="CCCC3333-3333-3333-3333-333333333333", xml_path=ruta_ok)
    c_sin_archivo = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="DDDD4444-4444-4444-4444-444444444444", xml_path=None)

    resultado = await worker_tasks._descargar_zip_lote_async(empresa.empresa_id, [c_ok.comprobante_id, c_sin_archivo.comprobante_id])
    assert resultado["solicitados"] == 2
    assert resultado["incluidos"] == 1  # el que no tiene XML se omite, no aborta el lote
