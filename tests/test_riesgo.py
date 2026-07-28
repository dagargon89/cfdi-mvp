"""Cancelaciones tardías (RF-RIES-01) — `registrar_cancelacion_tardia` en aislamiento
(el enganche real desde una transición vigente→cancelado se prueba de punta a punta en
`tests/test_worker_comprobantes.py`, que sí ejerce `_validar_lote_async` completo)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TipoEvento
from app.services import riesgo as riesgo_service
from tests.factories import crear_comprobante, crear_empresa

pytestmark = pytest.mark.asyncio


async def test_registrar_cancelacion_tardia_mes_anterior_genera_evento(db: AsyncSession) -> None:
    empresa = await crear_empresa(db)
    c = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111", fecha_emision=datetime(2026, 6, 15))

    evento = await riesgo_service.registrar_cancelacion_tardia(db, c, hoy=date(2026, 7, 28))
    await db.commit()

    assert evento is not None
    assert evento.tipo is TipoEvento.CANCELACION_TARDIA
    assert evento.detalle["uuid"] == c.uuid
    assert evento.detalle["rfc_emisor"] == c.rfc_emisor


async def test_registrar_cancelacion_tardia_mes_en_curso_no_genera_evento(db: AsyncSession) -> None:
    empresa = await crear_empresa(db)
    c = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="22222222-2222-2222-2222-222222222222", fecha_emision=datetime(2026, 7, 10))

    evento = await riesgo_service.registrar_cancelacion_tardia(db, c, hoy=date(2026, 7, 28))
    assert evento is None


async def test_registrar_cancelacion_tardia_sin_fecha_emision_no_genera_evento(db: AsyncSession) -> None:
    empresa = await crear_empresa(db)
    # `crear_comprobante(fecha_emision=None)` cae al default de la factory (no un NULL real) —
    # se fuerza el atributo directo en el objeto ya cargado, sin volver a tocar la BD.
    c = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="33333333-3333-3333-3333-333333333333")
    c.fecha_emision = None

    evento = await riesgo_service.registrar_cancelacion_tardia(db, c, hoy=date(2026, 7, 28))
    assert evento is None


async def test_registrar_cancelacion_tardia_no_duplica_al_re_correr(db: AsyncSession) -> None:
    empresa = await crear_empresa(db)
    c = await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="44444444-4444-4444-4444-444444444444", fecha_emision=datetime(2026, 6, 15))

    primero = await riesgo_service.registrar_cancelacion_tardia(db, c, hoy=date(2026, 7, 28))
    await db.commit()
    segundo = await riesgo_service.registrar_cancelacion_tardia(db, c, hoy=date(2026, 7, 28))

    assert primero is not None
    assert segundo is None
