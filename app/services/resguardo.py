"""Resguardo e índice (RF-RES-01/02/03, doc 06 §2.5 "resguardo encadenado").

Se dispara automáticamente al final de la descarga de un job (T9, `app/worker/tasks.py`) —
nunca es una tarea Celery aparte. Idempotente: correr dos veces sobre el mismo job nunca
duplica filas (`UNIQUE(empresa_id, uuid)`, doc 03 §2.2) y un XML corrupto no aborta el lote.
"""

from __future__ import annotations

import logging
import os
import re
import zipfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.comprobante import Comprobante
from app.models.empresa import Empresa
from app.models.enums import EstatusCfdi
from app.models.job import Job
from app.repositories import normalizacion as repo_normalizacion
from app.sat_hub.sat_facade import CamposCFDI, parse_cfdi
from app.services import normalizacion

logger = logging.getLogger("app.worker")

_INVALIDOS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_LARGO_MAX = 150


def sanear_nombre_archivo(valor: str) -> str:
    """Quita separadores de ruta y caracteres inválidos (doc 06 §2.7 A03) — ningún token de
    la plantilla puede hacer que el nombre final escape del directorio de destino."""
    limpio = _INVALIDOS.sub("_", valor).strip().strip(".")
    return (limpio or "archivo")[:_LARGO_MAX]


def render_nombre(plantilla: str, campos: CamposCFDI, estatus: EstatusCfdi) -> str:
    """Nomenclatura configurable (RF-RES-02): tokens ``{razon_social}``, ``{uuid_last4}``,
    ``{folio}``, ``{estatus}``. Plantilla inválida o con token desconocido cae a un default
    seguro — nunca truena el resguardo de todo el lote por una plantilla mal escrita."""
    valores = {
        "razon_social": campos.razon_social_emisor or "SIN_NOMBRE",
        "uuid_last4": campos.uuid[-4:],
        "folio": campos.folio or "SIN_FOLIO",
        "estatus": estatus.value,
    }
    try:
        nombre = plantilla.format(**valores)
    except (KeyError, IndexError, ValueError):
        nombre = f"{valores['razon_social']}_{valores['uuid_last4']}"
    return sanear_nombre_archivo(nombre) + ".xml"


def _evitar_colision(ruta: str) -> str:
    """Dos comprobantes distintos pueden rendir el mismo nombre bajo la plantilla — nunca
    sobreescribir, desambiguar con un sufijo."""
    if not os.path.exists(ruta):
        return ruta
    base, ext = os.path.splitext(ruta)
    contador = 2
    candidata = f"{base}_{contador}{ext}"
    while os.path.exists(candidata):
        contador += 1
        candidata = f"{base}_{contador}{ext}"
    return candidata


def _ruta_paquetes(storage_root: str, empresa_id: int, job_id: int) -> str:
    return os.path.join(storage_root, str(empresa_id), str(job_id))


def _ruta_comprobantes(storage_root: str, empresa_id: int) -> str:
    return os.path.join(storage_root, str(empresa_id), "comprobantes")


async def _indexar_xml(db: AsyncSession, job: Job, empresa: Empresa, xml_bytes: bytes, storage_root: str) -> bool:
    campos = parse_cfdi(xml_bytes)

    ya_existe = await db.scalar(
        select(Comprobante.comprobante_id).where(Comprobante.empresa_id == empresa.empresa_id, Comprobante.uuid == campos.uuid)
    )
    if ya_existe is not None:
        return False  # re-descarga del mismo CFDI — no duplica (idempotencia)

    nombre = render_nombre(empresa.plantilla_nomenclatura, campos, EstatusCfdi.NO_VERIFICADO)
    carpeta_destino = _ruta_comprobantes(storage_root, empresa.empresa_id)
    os.makedirs(carpeta_destino, exist_ok=True)
    ruta_absoluta = _evitar_colision(os.path.join(carpeta_destino, nombre))
    with open(ruta_absoluta, "wb") as f:
        f.write(xml_bytes)
    ruta_relativa = os.path.relpath(ruta_absoluta, storage_root)

    comprobante = Comprobante(
        empresa_id=empresa.empresa_id,
        job_id=job.job_id,
        uuid=campos.uuid,
        folio=campos.folio,
        rfc_emisor=campos.rfc_emisor,
        rfc_receptor=campos.rfc_receptor,
        razon_social_emisor=campos.razon_social_emisor,
        total=campos.total,
        fecha_emision=campos.fecha_emision,
        tipo_comprobante=campos.tipo_comprobante,
        estatus=EstatusCfdi.NO_VERIFICADO,  # RF-RES-03: registro estructurado siempre
        xml_path=ruta_relativa,  # relativa a storage_root — nunca la ruta absoluta del disco
    )
    db.add(comprobante)
    await db.flush()  # asigna `comprobante.comprobante_id` (autoincrement) — se necesita abajo

    # Disparador 1 del ETL (spec §6.3): lo que entra por descarga queda normalizado en la
    # misma transacción. Un fallo aquí NO impide indexar — el índice es lo que la UI necesita;
    # la normalización es un extra que alimenta informes. Se registra el error y se sigue.
    xml_hash = normalizacion.hash_xml(xml_bytes)
    try:
        datos = normalizacion.normalizar(xml_bytes)
        await repo_normalizacion.escribir(db, comprobante.comprobante_id, datos, xml_hash)
    except Exception as exc:  # noqa: BLE001 — se registra y se sigue, nunca se propaga
        logger.warning("indexar: no se pudo normalizar el comprobante %s: %s", comprobante.comprobante_id, exc)
        await repo_normalizacion.registrar_error(db, comprobante.comprobante_id, xml_hash, str(exc))

    return True


async def indexar_job(db: AsyncSession, job: Job, empresa: Empresa) -> int:
    """Abre los paquetes ya escritos del job, parsea cada XML e indexa en `comprobantes`.

    Devuelve cuántos comprobantes nuevos se indexaron. Un fallo aquí NUNCA revierte el job
    (ya llegó a DESCARGADO legítimamente, los crudos están a salvo) — solo se loguea; puede
    volver a llamarse después sin duplicar nada.
    """
    settings = get_settings()
    carpeta_paquetes = _ruta_paquetes(settings.storage_root, job.empresa_id, job.job_id)
    if not os.path.isdir(carpeta_paquetes):
        logger.warning("indexar_job: no existe %s (job %s); nada que indexar.", carpeta_paquetes, job.job_id)
        return 0

    nuevos = 0
    for nombre_zip in sorted(os.listdir(carpeta_paquetes)):
        if not nombre_zip.endswith(".zip"):
            continue
        ruta_zip = os.path.join(carpeta_paquetes, nombre_zip)
        try:
            with zipfile.ZipFile(ruta_zip) as zf:
                for nombre_xml in zf.namelist():
                    if not nombre_xml.lower().endswith(".xml"):
                        continue
                    try:
                        if await _indexar_xml(db, job, empresa, zf.read(nombre_xml), settings.storage_root):
                            nuevos += 1
                    except Exception as exc:  # noqa: BLE001 — un XML corrupto no aborta el lote (RF-RES/RF-VAL)
                        logger.warning("indexar_job: no se pudo indexar %s de %s (job %s): %s", nombre_xml, nombre_zip, job.job_id, exc)
        except zipfile.BadZipFile as exc:
            logger.warning("indexar_job: %s no es un zip válido (job %s): %s", ruta_zip, job.job_id, exc)

    await db.commit()
    return nuevos
