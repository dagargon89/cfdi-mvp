"""Escritor idempotente (spec §6.2).

Lo que estas pruebas fijan: reprocesar el mismo XML no duplica hijos, un XML corrupto
deja rastro para que el pre-vuelo no lo reintente en cada corrida, y subir `ETL_VERSION`
sí fuerza el reproceso.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cfdi_detalle import CfdiConcepto, CfdiConceptoImpuesto, ComprobanteDetalle
from app.models.nomina import NominaDeduccion, NominaPercepcion, NominaReceptor
from app.repositories import normalizacion as repo
from app.services import normalizacion
from tests import factories, fixtures_cfdi


async def _comprobante(db: AsyncSession, uuid: str, tipo: str = "I") -> int:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    c = await factories.crear_comprobante(db, empresa_id=empresa.empresa_id, uuid=uuid, tipo_comprobante=tipo)
    return c.comprobante_id


async def test_escribe_encabezado_conceptos_e_impuestos(db: AsyncSession) -> None:
    cid = await _comprobante(db, "11111111-1111-1111-1111-111111111111")
    xml = fixtures_cfdi.cfdi_ingreso()

    await repo.escribir(db, cid, normalizacion.normalizar(xml), normalizacion.hash_xml(xml))
    await db.commit()

    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == cid))
    assert detalle is not None
    assert detalle.version == "4.0"
    assert detalle.etl_version == normalizacion.ETL_VERSION
    assert detalle.normalizado_at is not None
    assert detalle.error_normalizacion is None
    assert await db.scalar(select(func.count()).select_from(CfdiConcepto).where(CfdiConcepto.comprobante_id == cid)) == 1
    assert await db.scalar(select(func.count()).select_from(CfdiConceptoImpuesto).where(CfdiConceptoImpuesto.comprobante_id == cid)) == 1


async def test_reprocesar_no_duplica_hijos(db: AsyncSession) -> None:
    """Borrar-e-insertar por `comprobante_id`, no `INSERT` a ciegas."""
    cid = await _comprobante(db, "22222222-2222-2222-2222-222222222222", tipo="N")
    xml = fixtures_cfdi.cfdi_nomina()
    datos = normalizacion.normalizar(xml)
    h = normalizacion.hash_xml(xml)

    await repo.escribir(db, cid, datos, h)
    await db.commit()
    await repo.escribir(db, cid, datos, h)
    await db.commit()

    assert await db.scalar(select(func.count()).select_from(NominaPercepcion).where(NominaPercepcion.comprobante_id == cid)) == 2
    assert await db.scalar(select(func.count()).select_from(NominaDeduccion).where(NominaDeduccion.comprobante_id == cid)) == 3
    assert await db.scalar(select(func.count()).select_from(NominaReceptor).where(NominaReceptor.comprobante_id == cid)) == 1


async def test_necesita_normalizar_respeta_hash_y_version(db: AsyncSession) -> None:
    cid = await _comprobante(db, "33333333-3333-3333-3333-333333333333")
    xml = fixtures_cfdi.cfdi_ingreso()
    h = normalizacion.hash_xml(xml)

    assert await repo.necesita_normalizar(db, cid, h) is True

    await repo.escribir(db, cid, normalizacion.normalizar(xml), h)
    await db.commit()

    # Mismo hash y misma versión → no hay nada que hacer.
    assert await repo.necesita_normalizar(db, cid, h) is False
    # XML distinto → sí.
    assert await repo.necesita_normalizar(db, cid, "f" * 64) is True

    # Subir la versión del ETL fuerza el reproceso de todo el histórico.
    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == cid))
    assert detalle is not None
    detalle.etl_version = normalizacion.ETL_VERSION - 1
    await db.commit()
    assert await repo.necesita_normalizar(db, cid, h) is True


async def test_registrar_error_deja_rastro_y_evita_reintento(db: AsyncSession) -> None:
    """Un XML corrupto se registra con su hash: sin esto, el pre-vuelo del informe lo
    reintentaría en cada corrida para siempre (spec §6.2)."""
    cid = await _comprobante(db, "44444444-4444-4444-4444-444444444444")

    await repo.registrar_error(db, cid, "a" * 64, "XML mal formado")
    await db.commit()

    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == cid))
    assert detalle is not None
    assert detalle.error_normalizacion == "XML mal formado"
    assert await repo.necesita_normalizar(db, cid, "a" * 64) is False


async def test_error_previo_se_limpia_al_reprocesar_bien(db: AsyncSession) -> None:
    cid = await _comprobante(db, "55555555-5555-5555-5555-555555555555")
    xml = fixtures_cfdi.cfdi_ingreso()
    h = normalizacion.hash_xml(xml)

    await repo.registrar_error(db, cid, h, "fallo transitorio")
    await db.commit()
    await repo.escribir(db, cid, normalizacion.normalizar(xml), h)
    await db.commit()

    detalle = await db.scalar(select(ComprobanteDetalle).where(ComprobanteDetalle.comprobante_id == cid))
    assert detalle is not None
    assert detalle.error_normalizacion is None


async def test_ids_pendientes_filtra_por_tipo(db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    nomina = await factories.crear_comprobante(
        db,
        empresa_id=empresa.empresa_id,
        uuid="66666666-6666-6666-6666-666666666666",
        tipo_comprobante="N",
        xml_path="11/comprobantes/nomina.xml",
    )
    await factories.crear_comprobante(
        db,
        empresa_id=empresa.empresa_id,
        uuid="77777777-7777-7777-7777-777777777777",
        tipo_comprobante="I",
        xml_path="11/comprobantes/ingreso.xml",
    )

    pendientes = await repo.ids_pendientes(db, empresa.empresa_id, solo_tipo="N")
    assert pendientes == [nomina.comprobante_id]


async def test_comprobante_sin_xml_no_es_pendiente(db: AsyncSession) -> None:
    """`ids_pendientes` promete comprobantes que se pueden normalizar. Uno sin XML en
    disco no puede normalizarse, así que no es pendiente: es otra cosa. Sin esta prueba,
    alguien podría quitar el filtro `xml_path.is_not(None)` en el futuro y nada lo
    impediría — la tarea 9 le crearía una fila de error con un hash de relleno en cada
    corrida, generando ruido permanente en `comprobante_detalle`."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    sin_xml = await factories.crear_comprobante(
        db, empresa_id=empresa.empresa_id, uuid="88888888-8888-8888-8888-888888888888", tipo_comprobante="I"
    )
    assert sin_xml.xml_path is None

    assert await repo.ids_pendientes(db, empresa.empresa_id) == []
