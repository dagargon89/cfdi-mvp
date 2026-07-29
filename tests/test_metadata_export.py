"""Servicio de exportación de metadata del SAT (parseo del TXT ~ de los paquetes de un job
METADATA → filas / CSV). Sin red del SAT: los ZIPs se construyen como dobles en el test."""

from __future__ import annotations

import io
import os
import zipfile
from datetime import date

import pytest

from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoJob
from app.models.job import Job
from app.services import metadata_export
from app.services.metadata_export import MetadataNoAplicableError, MetadataNoDisponibleError

_HEADER = "Uuid~RfcEmisor~NombreEmisor~RfcReceptor~NombreReceptor~RfcPac~FechaEmision~FechaCertificacionSat~MontoTotal~EfectoComprobante~Estatus~FechaCancelacion"
_FILA_1 = "11111111-1111-1111-1111-111111111111~AAA010101AAA~EMISOR, S.A. DE C.V.~BBB020202BBB~RECEPTOR SA~PPP030303PPP~2026-01-05T10:00:00~2026-01-05T10:05:00~1160.00~I~Vigente~"
_FILA_2 = "22222222-2222-2222-2222-222222222222~AAA010101AAA~EMISOR, S.A. DE C.V.~BBB020202BBB~RECEPTOR SA~PPP030303PPP~2026-01-06T11:00:00~2026-01-06T11:05:00~500.00~I~Cancelado~2026-02-01T09:00:00"


def _job(tmp_path, *, solicitud=SolicitudTipo.METADATA, estado=EstadoJob.DESCARGADO) -> Job:
    return Job(
        job_id=1,
        empresa_id=7,
        tipo=TipoJob.RECIBIDO,
        solicitud=solicitud,
        origen=OrigenJob.MANUAL,
        fecha_inicial=date(2026, 1, 1),
        fecha_final=date(2026, 1, 31),
        estado=estado,
        intentos=0,
        paquetes=1,
    )


def _escribir_zip_txt(storage_root: str, empresa_id: int, job_id: int, indice: int, contenido: str) -> None:
    carpeta = os.path.join(storage_root, str(empresa_id), str(job_id))
    os.makedirs(carpeta, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"metadata_{indice}.txt", contenido.encode("utf-8"))
    with open(os.path.join(carpeta, f"paquete_{indice}.zip"), "wb") as f:
        f.write(buf.getvalue())


def test_parsear_un_paquete(tmp_path) -> None:
    root = str(tmp_path)
    _escribir_zip_txt(root, 7, 1, 1, f"{_HEADER}\n{_FILA_1}\n{_FILA_2}\n")
    headers, filas = metadata_export.parsear_metadata(root, _job(tmp_path))
    assert headers[0] == "Uuid" and headers[-1] == "FechaCancelacion"
    assert len(filas) == 2
    assert filas[0][0] == "11111111-1111-1111-1111-111111111111"
    assert filas[1][-1] == "2026-02-01T09:00:00"


def test_parsear_multipaquete_un_solo_header(tmp_path) -> None:
    root = str(tmp_path)
    _escribir_zip_txt(root, 7, 1, 1, f"{_HEADER}\n{_FILA_1}\n")
    _escribir_zip_txt(root, 7, 1, 2, f"{_HEADER}\n{_FILA_2}\n")
    headers, filas = metadata_export.parsear_metadata(root, _job(tmp_path))
    assert len(headers) == 12
    assert len(filas) == 2  # sin el header repetido del 2º paquete


def test_parsear_descarta_lineas_vacias(tmp_path) -> None:
    root = str(tmp_path)
    _escribir_zip_txt(root, 7, 1, 1, f"{_HEADER}\n{_FILA_1}\n\n")  # línea final vacía
    _, filas = metadata_export.parsear_metadata(root, _job(tmp_path))
    assert len(filas) == 1


def test_job_no_metadata(tmp_path) -> None:
    with pytest.raises(MetadataNoAplicableError):
        metadata_export.parsear_metadata(str(tmp_path), _job(tmp_path, solicitud=SolicitudTipo.CFDI))


def test_job_no_descargado(tmp_path) -> None:
    with pytest.raises(MetadataNoDisponibleError):
        metadata_export.parsear_metadata(str(tmp_path), _job(tmp_path, estado=EstadoJob.EN_PROCESO))


def test_sin_txt_en_paquetes(tmp_path) -> None:
    root = str(tmp_path)
    carpeta = os.path.join(root, "7", "1")
    os.makedirs(carpeta, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("algo.xml", b"<x/>")  # solo XML, ningún .txt (caso SAT 5004)
    with open(os.path.join(carpeta, "paquete_1.zip"), "wb") as f:
        f.write(buf.getvalue())
    with pytest.raises(MetadataNoDisponibleError):
        metadata_export.parsear_metadata(root, _job(tmp_path))


def test_generar_csv_con_bom_y_quoting(tmp_path) -> None:
    root = str(tmp_path)
    _escribir_zip_txt(root, 7, 1, 1, f"{_HEADER}\n{_FILA_1}\n")
    csv_bytes = metadata_export.generar_csv_metadata(root, _job(tmp_path))
    assert csv_bytes.startswith(b"\xef\xbb\xbf")  # BOM UTF-8
    texto = csv_bytes.decode("utf-8-sig")
    assert texto.splitlines()[0].startswith("Uuid,")
    assert '"EMISOR, S.A. DE C.V."' in texto  # el nombre con coma va entrecomillado
