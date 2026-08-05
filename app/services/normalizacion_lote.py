"""Normalización por lote: lee el XML de disco, lo parsea y lo persiste (spec §6.3).

Compartido por el disparador 2 (tarea de reproceso) y el disparador 3 (pre-vuelo del
informe). Ningún XML individual aborta el lote.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.comprobante import Comprobante
from app.repositories import normalizacion as repo_normalizacion
from app.services import normalizacion, representaciones

logger = logging.getLogger(__name__)


async def normalizar_lote(db: AsyncSession, empresa_id: int, comprobante_ids: list[int]) -> dict[str, int]:
    """Devuelve `{"normalizados": n, "con_error": n, "omitidos": n}`.

    `omitidos` son los que ya estaban al día (mismo hash, misma `ETL_VERSION`). Commitea
    por comprobante: un lote largo que se interrumpa deja avanzado lo que ya procesó.
    """
    storage_root = get_settings().storage_root
    resumen = {"normalizados": 0, "con_error": 0, "omitidos": 0}

    for comprobante_id in comprobante_ids:
        comprobante = await db.scalar(
            select(Comprobante).where(Comprobante.comprobante_id == comprobante_id, Comprobante.empresa_id == empresa_id)
        )
        if comprobante is None:
            continue  # id de otra empresa: se ignora, igual que en `validar_lote`

        xml_bytes = representaciones.leer_xml_de_disco(storage_root, comprobante)
        if xml_bytes is None:
            await repo_normalizacion.registrar_error(db, comprobante_id, "0" * 64, "El XML no está en disco.")
            await db.commit()
            resumen["con_error"] += 1
            continue

        xml_hash = normalizacion.hash_xml(xml_bytes)
        if not await repo_normalizacion.necesita_normalizar(db, comprobante_id, xml_hash):
            resumen["omitidos"] += 1
            continue

        try:
            await repo_normalizacion.escribir(db, comprobante_id, normalizacion.normalizar(xml_bytes), xml_hash)
            await db.commit()
            resumen["normalizados"] += 1
        except Exception as exc:  # noqa: BLE001 — un XML corrupto no aborta el lote
            await db.rollback()
            logger.warning("normalizar_lote: comprobante %s no se pudo normalizar: %s", comprobante_id, exc)
            await repo_normalizacion.registrar_error(db, comprobante_id, xml_hash, str(exc))
            await db.commit()
            resumen["con_error"] += 1

    return resumen
