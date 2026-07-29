"""Exportación de la metadata del SAT de un job METADATA.

El SAT entrega la metadata como un TXT delimitado por `~` (con fila de encabezado) dentro del
ZIP del job. El resguardo (`app/services/resguardo.py`) solo indexa `.xml`, así que ese TXT queda
archivado sin procesar en `storage_root/{empresa_id}/{job_id}/paquete_N.zip`. Este servicio lo lee
y lo convierte en filas (vista previa) o en CSV (descarga). No toca la BD: recibe el `Job` ya cargado.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import zipfile

from app.models.enums import EstadoJob, SolicitudTipo
from app.models.job import Job

logger = logging.getLogger(__name__)

_DELIMITADOR = "~"


class MetadataNoAplicableError(Exception):
    """El job no es de tipo METADATA (no hay metadata que exportar)."""


class MetadataNoDisponibleError(Exception):
    """El job no está DESCARGADO, o sus paquetes no contienen ningún TXT de metadata."""


def _carpeta_paquetes(storage_root: str, empresa_id: int, job_id: int) -> str:
    # Mismo layout que resguardo._ruta_paquetes / worker._ruta_paquete.
    return os.path.join(storage_root, str(empresa_id), str(job_id))


def parsear_metadata(storage_root: str, job: Job) -> tuple[list[str], list[list[str]]]:
    """Abre los paquete_*.zip del job, extrae el/los TXT ~ y devuelve (headers, filas).

    Conserva el encabezado del primer TXT y omite el de los siguientes (varios paquetes → un solo
    conjunto de columnas). Descarta líneas vacías (el TXT del SAT trae una línea final vacía).
    """
    if job.solicitud is not SolicitudTipo.METADATA:
        raise MetadataNoAplicableError("Este job no es de tipo METADATA.")
    if job.estado is not EstadoJob.DESCARGADO:
        raise MetadataNoDisponibleError("El job todavía no está descargado.")

    carpeta = _carpeta_paquetes(storage_root, job.empresa_id, job.job_id)
    if not os.path.isdir(carpeta):
        raise MetadataNoDisponibleError("No hay paquetes descargados para este job.")

    headers: list[str] | None = None
    filas: list[list[str]] = []
    encontro_txt = False

    for nombre_zip in sorted(os.listdir(carpeta)):
        if not nombre_zip.lower().endswith(".zip"):
            continue
        try:
            with zipfile.ZipFile(os.path.join(carpeta, nombre_zip)) as zf:
                for nombre in zf.namelist():
                    if not nombre.lower().endswith(".txt"):
                        continue
                    encontro_txt = True
                    texto = zf.read(nombre).decode("utf-8-sig", errors="replace")
                    lineas = [ln for ln in texto.splitlines() if ln.strip()]
                    if not lineas:
                        continue
                    if headers is None:
                        headers = lineas[0].split(_DELIMITADOR)
                    filas.extend(ln.split(_DELIMITADOR) for ln in lineas[1:])
        except zipfile.BadZipFile as exc:
            logger.warning("parsear_metadata: %s no es un zip válido (job %s): %s", os.path.join(carpeta, nombre_zip), job.job_id, exc)

    if not encontro_txt or headers is None:
        raise MetadataNoDisponibleError("Los paquetes de este job no contienen metadata.")
    return headers, filas


def generar_csv_metadata(storage_root: str, job: Job) -> bytes:
    """CSV (UTF-8 con BOM) de toda la metadata del job. Encabezados tal cual del SAT."""
    headers, filas = parsear_metadata(storage_root, job)
    buf = io.StringIO()
    escritor = csv.writer(buf)
    escritor.writerow(headers)
    escritor.writerows(filas)
    return buf.getvalue().encode("utf-8-sig")
