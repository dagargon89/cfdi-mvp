# Descarga y vista previa de metadata del SAT — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir la metadata que el SAT entrega en un job `METADATA` (archivo TXT `~`-delimitado dentro del ZIP) en algo consumible: vista previa paginada en el detalle del job y descarga como CSV, más un filtro CFDI/METADATA en el monitoreo de jobs.

**Architecture:** Se agrega solo una capa de lectura/exportación sobre lo ya construido. Un servicio nuevo (`app/services/metadata_export.py`) abre los `paquete_*.zip` del job, extrae y parsea el TXT `~`; dos endpoints síncronos lo exponen (JSON paginado para preview, CSV para descarga); el frontend muestra una tabla en el `JobDrawer` y un botón de descarga, y añade un filtro por tipo de solicitud en el listado. No se toca cómo se solicita ni cómo se archiva la metadata.

**Tech Stack:** Backend FastAPI + SQLAlchemy async + pytest (asyncio, testcontainers MySQL). Frontend React + TanStack Query + TypeScript (Vite). Sin framework de test unitario en el front (verificación por `tsc`/`eslint` + prueba manual).

## Global Constraints

- **Ruta de storage:** `storage_root/{empresa_id}/{job_id}/paquete_{n}.zip` — layout existente (`app/core/config.py:24`, `storage_root` default `"./storage"`), NO inventar otra.
- **Permiso de lectura:** los endpoints nuevos usan `require_empresa(RolEmpresa.CONSULTA)` (patrón de las descargas por comprobante).
- **Encabezados del CSV/preview:** tal cual del SAT (`Uuid`, `RfcEmisor`, …), sin traducir.
- **Codificación del CSV:** UTF-8 con BOM (`utf-8-sig`) para que Excel lea acentos.
- **Paginación de la preview:** `per_page = 100`, `page` 1-based. El CSV baja TODAS las filas, sin paginar.
- **Límite de seguridad de pruebas:** los tests jamás tocan la red del SAT ni un servidor real; se usan ZIPs de doble construidos en el test.
- **Errores HTTP:** mapear excepciones del servicio a `HTTPException(422, detail={"codigo": ..., "mensaje": ...})`, mismo sobre que `crear_descarga_endpoint` (`app/api/v1/descargas.py:36-43`).
- **Commits:** en la rama `feat/descarga-metadata-sat`. Cada commit termina con:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

**Nuevos:**
- `app/services/metadata_export.py` — parseo del TXT `~` de los ZIPs de un job → filas / CSV. Excepciones tipadas. No toca la BD (recibe el `Job` ya cargado).
- `tests/test_metadata_export.py` — pruebas del servicio y de los endpoints.

**Modificados:**
- `app/api/v1/schemas.py` — schema `MetadataPreviewOut`.
- `app/api/v1/descargas.py` — 2 endpoints nuevos + param `solicitud` en el listado de jobs.
- `app/repositories/jobs.py` — filtro `solicitud` en `listar()`.
- `apps/web/src/lib/api.ts` — tipo `MetadataPreview`, métodos nuevos en la interfaz, filtro `solicitud` en `listarJobs`.
- `apps/web/src/lib/api.http.ts` — implementación de los métodos nuevos + filtro.
- `apps/web/src/hooks/useJobs.ts` — pasar el filtro `solicitud`.
- `apps/web/src/features/descargas/JobDrawer.tsx` — tabla de preview + botón "Descargar CSV".
- `apps/web/src/features/descargas/DescargasPage.tsx` — selector de filtro Solicitud.

---

## Task 1: Servicio de parseo de metadata

**Files:**
- Create: `app/services/metadata_export.py`
- Test: `tests/test_metadata_export.py`

**Interfaces:**
- Consumes: `app.models.job.Job`, `app.models.enums.SolicitudTipo`, `app.models.enums.EstadoJob`.
- Produces:
  - `parsear_metadata(storage_root: str, job: Job) -> tuple[list[str], list[list[str]]]` — devuelve `(headers, filas)`.
  - `generar_csv_metadata(storage_root: str, job: Job) -> bytes` — CSV completo con BOM.
  - `class MetadataNoAplicableError(Exception)` — el job no es de tipo `METADATA`.
  - `class MetadataNoDisponibleError(Exception)` — job no `DESCARGADO`, sin carpeta de paquetes, o sin ningún `.txt`.

- [ ] **Step 1: Escribir los tests que fallan**

Crea `tests/test_metadata_export.py`:

```python
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
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_metadata_export.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.metadata_export'`.

- [ ] **Step 3: Implementar el servicio**

Crea `app/services/metadata_export.py`:

```python
"""Exportación de la metadata del SAT de un job METADATA.

El SAT entrega la metadata como un TXT delimitado por `~` (con fila de encabezado) dentro del
ZIP del job. El resguardo (`app/services/resguardo.py`) solo indexa `.xml`, así que ese TXT queda
archivado sin procesar en `storage_root/{empresa_id}/{job_id}/paquete_N.zip`. Este servicio lo lee
y lo convierte en filas (vista previa) o en CSV (descarga). No toca la BD: recibe el `Job` ya cargado.
"""

from __future__ import annotations

import csv
import io
import os
import zipfile

from app.models.enums import EstadoJob, SolicitudTipo
from app.models.job import Job

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
        except zipfile.BadZipFile:
            continue

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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_metadata_export.py -v`
Expected: PASS (los 7 tests de este archivo).

- [ ] **Step 5: Commit**

```bash
git add app/services/metadata_export.py tests/test_metadata_export.py
git commit -m "feat: Servicio de exportación de metadata del SAT (parseo TXT ~ → filas/CSV)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Endpoints de preview (JSON) y descarga (CSV)

**Files:**
- Modify: `app/api/v1/schemas.py` (agregar `MetadataPreviewOut`)
- Modify: `app/api/v1/descargas.py` (2 endpoints nuevos)
- Test: `tests/test_metadata_export.py` (agregar tests de endpoint)

**Interfaces:**
- Consumes: `metadata_export.parsear_metadata`, `metadata_export.generar_csv_metadata`, `MetadataNoAplicableError`, `MetadataNoDisponibleError` (Task 1); `jobs_repo.por_id_de_empresa`; `get_settings().storage_root`.
- Produces:
  - `GET /v1/empresas/{empresa_id}/jobs/{job_id}/metadata?page=N` → `MetadataPreviewOut`.
  - `GET /v1/empresas/{empresa_id}/jobs/{job_id}/metadata.csv` → `Response` CSV.
  - `class MetadataPreviewOut(BaseModel)`: `headers: list[str]`, `filas: list[list[str]]`, `total: int`, `page: int`, `per_page: int`.

- [ ] **Step 1: Escribir los tests de endpoint que fallan**

Agrega al final de `tests/test_metadata_export.py`:

```python
# --- Tests de endpoint (usan las fixtures `client` y `db` de conftest) ---

from httpx import AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.models.enums import RolGlobal  # noqa: E402
from tests.factories import crear_empresa, crear_usuario  # noqa: E402

pytestmark = pytest.mark.asyncio


async def _empresa_con_job_metadata(db: AsyncSession, storage_root: str, *, estado=EstadoJob.DESCARGADO) -> Job:
    await crear_usuario(db, uid="uid-meta", correo="meta@demo.test", rol_global=RolGlobal.ADMIN)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    job = Job(
        empresa_id=empresa.empresa_id,
        tipo=TipoJob.RECIBIDO,
        solicitud=SolicitudTipo.METADATA,
        origen=OrigenJob.MANUAL,
        fecha_inicial=date(2026, 1, 1),
        fecha_final=date(2026, 1, 31),
        estado=estado,
        intentos=0,
        paquetes=1,
    )
    db.add(job)
    await db.flush()
    await db.commit()
    _escribir_zip_txt(storage_root, empresa.empresa_id, job.job_id, 1, f"{_HEADER}\n{_FILA_1}\n{_FILA_2}\n")
    return job


async def test_endpoint_preview_ok(client: AsyncClient, db: AsyncSession, monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings

    root = str(tmp_path)
    monkeypatch.setattr(get_settings(), "storage_root", root)
    job = await _empresa_con_job_metadata(db, root)
    res = await client.get(f"/v1/empresas/{job.empresa_id}/jobs/{job.job_id}/metadata")
    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["headers"][0] == "Uuid"
    assert cuerpo["total"] == 2
    assert cuerpo["per_page"] == 100
    assert len(cuerpo["filas"]) == 2


async def test_endpoint_preview_job_cfdi_422(client: AsyncClient, db: AsyncSession, monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings

    root = str(tmp_path)
    monkeypatch.setattr(get_settings(), "storage_root", root)
    await crear_usuario(db, uid="uid-meta2", correo="meta2@demo.test", rol_global=RolGlobal.ADMIN)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    job = Job(
        empresa_id=empresa.empresa_id, tipo=TipoJob.RECIBIDO, solicitud=SolicitudTipo.CFDI,
        origen=OrigenJob.MANUAL, fecha_inicial=date(2026, 1, 1), fecha_final=date(2026, 1, 31),
        estado=EstadoJob.DESCARGADO, intentos=0, paquetes=1,
    )
    db.add(job)
    await db.flush()
    await db.commit()
    res = await client.get(f"/v1/empresas/{job.empresa_id}/jobs/{job.job_id}/metadata")
    assert res.status_code == 422
    assert res.json()["error"]["codigo"] == "METADATA_NO_APLICABLE"


async def test_endpoint_preview_job_inexistente_404(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-meta3", correo="meta3@demo.test", rol_global=RolGlobal.ADMIN)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    res = await client.get(f"/v1/empresas/{empresa.empresa_id}/jobs/999999/metadata")
    assert res.status_code == 404


async def test_endpoint_csv_ok(client: AsyncClient, db: AsyncSession, monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings

    root = str(tmp_path)
    monkeypatch.setattr(get_settings(), "storage_root", root)
    job = await _empresa_con_job_metadata(db, root)
    res = await client.get(f"/v1/empresas/{job.empresa_id}/jobs/{job.job_id}/metadata.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert f"metadata_job{job.job_id}.csv" in res.headers["content-disposition"]
    assert res.content.startswith(b"\xef\xbb\xbf")
```

Nota: el envelope de error del backend es `{"error": {"codigo": ..., "mensaje": ...}}` (ver `tests/test_descargas_api.py` para confirmar la forma exacta que assertea el proyecto; ajusta el path del assert si difiere).

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_metadata_export.py -k endpoint -v`
Expected: FAIL — 404 en todas (las rutas aún no existen).

- [ ] **Step 3: Agregar el schema `MetadataPreviewOut`**

En `app/api/v1/schemas.py`, junto a `JobOut`/`JobPageOut` (después de la línea 127), agrega:

```python
class MetadataPreviewOut(BaseModel):
    headers: list[str]
    filas: list[list[str]]
    total: int
    page: int
    per_page: int
```

- [ ] **Step 4: Implementar los endpoints**

En `app/api/v1/descargas.py`:

Agrega a los imports (junto a los `from app.services...` existentes):

```python
from app.api.v1.schemas import MetadataPreviewOut
from app.core.config import get_settings
from app.services import metadata_export
from app.services.metadata_export import MetadataNoAplicableError, MetadataNoDisponibleError
from fastapi import Response
```

(Asegúrate de que `MetadataPreviewOut` quede en el `from app.api.v1.schemas import (...)` ya existente y `Response` en el `from fastapi import ...` ya existente, sin duplicar líneas de import.)

Agrega al final del archivo (después de `reintentar_job_endpoint`):

```python
_METADATA_PER_PAGE = 100


def _job_o_404(job: object | None) -> None:
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")


def _mapear_error_metadata(exc: Exception) -> HTTPException:
    if isinstance(exc, MetadataNoAplicableError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "METADATA_NO_APLICABLE", "mensaje": str(exc)})
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "METADATA_NO_DISPONIBLE", "mensaje": str(exc)})


@router.get("/jobs/{job_id}/metadata", response_model=MetadataPreviewOut)
async def preview_metadata_endpoint(
    empresa_id: int,
    job_id: int,
    page: int = 1,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> MetadataPreviewOut:
    job = await jobs_repo.por_id_de_empresa(db, empresa_id, job_id)
    _job_o_404(job)
    try:
        headers, filas = metadata_export.parsear_metadata(get_settings().storage_root, job)
    except (MetadataNoAplicableError, MetadataNoDisponibleError) as exc:
        raise _mapear_error_metadata(exc) from exc

    inicio = max(page - 1, 0) * _METADATA_PER_PAGE
    return MetadataPreviewOut(
        headers=headers,
        filas=filas[inicio : inicio + _METADATA_PER_PAGE],
        total=len(filas),
        page=page,
        per_page=_METADATA_PER_PAGE,
    )


@router.get("/jobs/{job_id}/metadata.csv")
async def descargar_metadata_csv_endpoint(
    empresa_id: int,
    job_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    job = await jobs_repo.por_id_de_empresa(db, empresa_id, job_id)
    _job_o_404(job)
    try:
        csv_bytes = metadata_export.generar_csv_metadata(get_settings().storage_root, job)
    except (MetadataNoAplicableError, MetadataNoDisponibleError) as exc:
        raise _mapear_error_metadata(exc) from exc
    return Response(
        csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="metadata_job{job_id}.csv"'},
    )
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `pytest tests/test_metadata_export.py -v`
Expected: PASS (todos, servicio + endpoints).

- [ ] **Step 6: Commit**

```bash
git add app/api/v1/schemas.py app/api/v1/descargas.py tests/test_metadata_export.py
git commit -m "feat: Endpoints de preview (JSON) y descarga (CSV) de metadata del SAT

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Filtro por tipo de solicitud en el listado de jobs

**Files:**
- Modify: `app/repositories/jobs.py:102-120` (`listar`)
- Modify: `app/api/v1/descargas.py:62-72` (`listar_jobs_endpoint`)
- Test: `tests/test_metadata_export.py` (un test más)

**Interfaces:**
- Consumes: `app.models.enums.SolicitudTipo`.
- Produces: `jobs_repo.listar(..., solicitud: SolicitudTipo | None = None)` y `GET /v1/empresas/{empresa_id}/jobs?solicitud=METADATA`.

- [ ] **Step 1: Escribir el test que falla**

Agrega a `tests/test_metadata_export.py`:

```python
async def test_listar_jobs_filtra_por_solicitud(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-filtro", correo="filtro@demo.test", rol_global=RolGlobal.ADMIN)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    for sol in (SolicitudTipo.CFDI, SolicitudTipo.METADATA):
        db.add(Job(
            empresa_id=empresa.empresa_id, tipo=TipoJob.RECIBIDO, solicitud=sol, origen=OrigenJob.MANUAL,
            fecha_inicial=date(2026, 1, 1), fecha_final=date(2026, 1, 31), estado=EstadoJob.DESCARGADO,
            intentos=0, paquetes=1,
        ))
    await db.commit()
    res = await client.get(f"/v1/empresas/{empresa.empresa_id}/jobs?solicitud=METADATA")
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) == 1 and data[0]["solicitud"] == "METADATA"
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `pytest tests/test_metadata_export.py::test_listar_jobs_filtra_por_solicitud -v`
Expected: FAIL — devuelve 2 jobs (el filtro aún no existe) o error de parámetro.

- [ ] **Step 3: Agregar el filtro al repositorio**

En `app/repositories/jobs.py`, importa `SolicitudTipo` (junto a `EstadoJob, OrigenJob` en el import de `app.models.enums`), y en `listar` agrega el parámetro y el filtro:

```python
async def listar(
    db: AsyncSession,
    empresa_id: int,
    *,
    estado: EstadoJob | None = None,
    origen: OrigenJob | None = None,
    solicitud: SolicitudTipo | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[Job], int]:
    filtros = [Job.empresa_id == empresa_id]
    if estado is not None:
        filtros.append(Job.estado == estado)
    if origen is not None:
        filtros.append(Job.origen == origen)
    if solicitud is not None:
        filtros.append(Job.solicitud == solicitud)
    # ... (resto igual)
```

- [ ] **Step 4: Pasar el parámetro en el endpoint**

En `app/api/v1/descargas.py`, importa `SolicitudTipo` (junto a `EstadoJob, OrigenJob, RolEmpresa` en el import de enums) y en `listar_jobs_endpoint`:

```python
async def listar_jobs_endpoint(
    empresa_id: int,
    estado: EstadoJob | None = None,
    origen: OrigenJob | None = None,
    solicitud: SolicitudTipo | None = None,
    page: int = 1,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> JobPageOut:
    jobs, total = await jobs_repo.listar(db, empresa_id, estado=estado, origen=origen, solicitud=solicitud, page=page)
    return JobPageOut(data=[job_a_out(j) for j in jobs], page=page, per_page=50, total=total)
```

- [ ] **Step 5: Correr el test para verificar que pasa**

Run: `pytest tests/test_metadata_export.py::test_listar_jobs_filtra_por_solicitud -v`
Expected: PASS.

- [ ] **Step 6: Verificar que la suite de descargas no se rompió**

Run: `pytest tests/test_descargas_api.py tests/test_metadata_export.py -v`
Expected: PASS (el nuevo parámetro es opcional; no rompe llamadas existentes).

- [ ] **Step 7: Commit**

```bash
git add app/repositories/jobs.py app/api/v1/descargas.py tests/test_metadata_export.py
git commit -m "feat: Filtro por tipo de solicitud (CFDI/METADATA) en el listado de jobs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: ApiClient del frontend — tipos y métodos

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/api.http.ts`

**Interfaces:**
- Produces (en `ApiClient`):
  - `obtenerMetadata(empresaId: number, jobId: number, page?: number): Promise<MetadataPreview>`
  - `descargarMetadataCsv(empresaId: number, jobId: number): Promise<Blob>`
  - `listarJobs(empresaId, f?: { estado?; origen?; solicitud?: 'CFDI' | 'METADATA'; page? })` (se agrega `solicitud`)
  - `interface MetadataPreview { headers: string[]; filas: string[][]; total: number; page: number; per_page: number }`

- [ ] **Step 1: Agregar el tipo y las firmas en `api.ts`**

En `apps/web/src/lib/api.ts`, agrega el tipo (cerca de `Job`):

```typescript
export interface MetadataPreview {
  headers: string[];
  filas: string[][];
  total: number;
  page: number;
  per_page: number;
}
```

Modifica la firma de `listarJobs` (línea ~171) para sumar `solicitud`:

```typescript
  listarJobs(empresaId: number, f?: { estado?: EstadoJob; origen?: 'manual' | 'sync'; solicitud?: 'CFDI' | 'METADATA'; page?: number }): Promise<Page<Job>>;
```

Agrega las dos firmas nuevas (junto a `descargarComprobanteZip`, línea ~189):

```typescript
  obtenerMetadata(empresaId: number, jobId: number, page?: number): Promise<MetadataPreview>;
  descargarMetadataCsv(empresaId: number, jobId: number): Promise<Blob>;
```

- [ ] **Step 2: Implementar en `api.http.ts`**

En `apps/web/src/lib/api.http.ts`:

1. Agrega `'obtenerMetadata'` y `'descargarMetadataCsv'` al `Pick<ApiClient, ...>` (`ApiClientHttpSubset`, junto a `'descargarComprobanteZip'`).

2. Actualiza `listarJobs` para pasar `solicitud`:

```typescript
  listarJobs: (empresaId, f) => {
    const params = new URLSearchParams();
    if (f?.estado) params.set('estado', f.estado);
    if (f?.origen) params.set('origen', f.origen);
    if (f?.solicitud) params.set('solicitud', f.solicitud);
    if (f?.page) params.set('page', String(f.page));
    const qs = params.toString();
    return request<Page<Job>>(`/v1/empresas/${empresaId}/jobs${qs ? `?${qs}` : ''}`);
  },
```

3. Agrega las dos implementaciones (junto a `descargarComprobanteZip`):

```typescript
  obtenerMetadata: (empresaId, jobId, page) =>
    request<MetadataPreview>(`/v1/empresas/${empresaId}/jobs/${jobId}/metadata${page ? `?page=${page}` : ''}`),
  descargarMetadataCsv: (empresaId, jobId) =>
    requestBlob(`/v1/empresas/${empresaId}/jobs/${jobId}/metadata.csv`),
```

4. Asegúrate de importar `MetadataPreview` desde `./api` en el import de tipos existente (junto a `Job`, `Page`, etc.).

- [ ] **Step 3: Verificar tipos**

Run: `cd apps/web && npm run typecheck`
Expected: sin errores.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/api.http.ts
git commit -m "feat(web): ApiClient para metadata (preview/CSV) y filtro solicitud en listarJobs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: JobDrawer — vista previa y botón de descarga

**Files:**
- Modify: `apps/web/src/features/descargas/JobDrawer.tsx`

**Interfaces:**
- Consumes: `api.obtenerMetadata`, `api.descargarMetadataCsv` (Task 4); `descargarBlob` (`@/lib/descargarBlob`); `useEmpresaCtx` (`@/empresa/EmpresaContext`); `useToast` (`@/components/ui/ToastProvider`); `useQuery` (`@tanstack/react-query`).

Contexto: `JobDrawer` hoy es presentacional y recibe `job`. Para la preview necesita el `empresa_id` y datos de red. Se obtiene la empresa con `useEmpresaCtx()` (mismo patrón que `ComprobanteDrawer.tsx:19`), y la metadata con `useQuery` habilitado solo cuando aplica.

- [ ] **Step 1: Añadir imports y hooks de datos**

En `apps/web/src/features/descargas/JobDrawer.tsx`, agrega imports:

```typescript
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import { useToast } from '@/components/ui/ToastProvider';
import { api } from '@/lib/client';
import { descargarBlob } from '@/lib/descargarBlob';
```

Dentro del componente `JobDrawer`, al inicio (después de `const puedeReintentar = ...`):

```typescript
  const { empresa } = useEmpresaCtx();
  const { toast } = useToast();
  const esMetadata = job.solicitud === 'METADATA' && job.estado === 'DESCARGADO';
  const [page, setPage] = useState(1);
  const [descargando, setDescargando] = useState(false);

  const metadataQuery = useQuery({
    queryKey: ['metadata', empresa.empresa_id, job.job_id, page],
    queryFn: () => api.obtenerMetadata(empresa.empresa_id, job.job_id, page),
    enabled: esMetadata,
  });

  async function descargarCsv() {
    setDescargando(true);
    try {
      const blob = await api.descargarMetadataCsv(empresa.empresa_id, job.job_id);
      descargarBlob(blob, `metadata_job${job.job_id}.csv`);
    } catch {
      toast('No se pudo descargar el CSV de metadata', 'error');
    } finally {
      setDescargando(false);
    }
  }

  const totalPaginas = metadataQuery.data ? Math.max(1, Math.ceil(metadataQuery.data.total / metadataQuery.data.per_page)) : 1;
```

- [ ] **Step 2: Renderizar la tabla de preview**

Dentro del `<div className="flex-1 overflow-y-auto ...">`, después del bloque de "Última verificación" (línea ~52) y antes de cerrar ese div, agrega:

```tsx
        {esMetadata && (
          <div className="flex flex-col gap-2">
            <span className="text-xs font-semibold text-text-muted">Metadata del SAT</span>
            {metadataQuery.isLoading && <div className="text-[13px] text-text-muted">Cargando metadata…</div>}
            {metadataQuery.isError && (
              <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2.5 text-[13px]">
                Este job no trajo metadata para mostrar.
              </div>
            )}
            {metadataQuery.data && (
              <>
                <div className="text-xs text-text-muted">{metadataQuery.data.total} registro(s)</div>
                <div className="overflow-x-auto border border-border rounded">
                  <table className="w-full border-collapse text-[12px]">
                    <thead>
                      <tr>
                        {metadataQuery.data.headers.map((h) => (
                          <th key={h} className="text-left px-2 py-1 font-semibold bg-surface-alt whitespace-nowrap">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {metadataQuery.data.filas.map((fila, i) => (
                        <tr key={i} className="border-t border-border">
                          {fila.map((celda, j) => (
                            <td key={j} className="px-2 py-1 font-mono whitespace-nowrap">{celda || '—'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {totalPaginas > 1 && (
                  <div className="flex items-center gap-2 text-[13px]">
                    <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="disabled:opacity-40">← Anterior</button>
                    <span className="text-text-muted">Página {page} de {totalPaginas}</span>
                    <button disabled={page >= totalPaginas} onClick={() => setPage((p) => p + 1)} className="disabled:opacity-40">Siguiente →</button>
                  </div>
                )}
              </>
            )}
          </div>
        )}
```

- [ ] **Step 3: Añadir el botón de descarga en el pie**

Reemplaza el bloque del pie (`{puedeReintentar && (...)}`, líneas ~54-60) por uno que muestre ambos botones cuando corresponda:

```tsx
      {(puedeReintentar || (esMetadata && !!metadataQuery.data)) && (
        <div className="border-t border-border p-4 flex gap-2">
          {puedeReintentar && (
            <Button onClick={onReintentar} loading={reintentando} disabled={reintentando}>
              <RefreshCw className="size-[15px]" aria-hidden /> Reintentar descarga
            </Button>
          )}
          {esMetadata && !!metadataQuery.data && (
            <Button onClick={descargarCsv} loading={descargando} disabled={descargando}>
              <Download className="size-[15px]" aria-hidden /> Descargar CSV
            </Button>
          )}
        </div>
      )}
```

- [ ] **Step 4: Verificar tipos y lint**

Run: `cd apps/web && npm run typecheck && npm run lint`
Expected: sin errores.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/descargas/JobDrawer.tsx
git commit -m "feat(web): Vista previa de metadata + botón Descargar CSV en el detalle del job

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Filtro de solicitud en Monitoreo de jobs

**Files:**
- Modify: `apps/web/src/hooks/useJobs.ts`
- Modify: `apps/web/src/features/descargas/DescargasPage.tsx`

**Interfaces:**
- Consumes: `api.listarJobs` con `solicitud` (Task 4).
- Produces: `useJobs(empresaId, page, filtroSolicitud?)` y un selector en la UI del Monitoreo.

- [ ] **Step 1: Extender el hook `useJobs`**

En `apps/web/src/hooks/useJobs.ts`:

```typescript
export function useJobs(empresaId: number, page = 1, solicitud?: 'CFDI' | 'METADATA') {
  return useQuery({
    queryKey: ['jobs', empresaId, page, solicitud ?? 'todas'],
    queryFn: () => api.listarJobs(empresaId, { page, solicitud }),
    refetchInterval: (query) => (query.state.data?.data.some((j) => EN_CURSO.includes(j.estado)) ? 1500 : false),
  });
}
```

- [ ] **Step 2: Añadir el estado y el selector en `DescargasPage`**

En `apps/web/src/features/descargas/DescargasPage.tsx`:

1. Agrega el estado del filtro (junto a los `useState` existentes, ~línea 37):

```typescript
  const [filtroSolicitud, setFiltroSolicitud] = useState<'' | 'CFDI' | 'METADATA'>('');
```

2. Pasa el filtro al hook (línea ~29):

```typescript
  const { data: jobsPage } = useJobs(empresa.empresa_id, pagina, filtroSolicitud || undefined);
```

3. En la cabecera del panel "Monitoreo de jobs" (donde está `<h3 ...>Monitoreo de jobs</h3>`, ~línea 131), agrega el selector junto al título:

```tsx
          <select
            aria-label="Filtrar por tipo de solicitud"
            value={filtroSolicitud}
            onChange={(e) => { setFiltroSolicitud(e.target.value as typeof filtroSolicitud); setPagina(1); }}
            className="h-8 border border-border rounded px-2 text-[13px]"
          >
            <option value="">Todas</option>
            <option value="CFDI">CFDI</option>
            <option value="METADATA">Metadata</option>
          </select>
```

- [ ] **Step 3: Verificar tipos y lint**

Run: `cd apps/web && npm run typecheck && npm run lint`
Expected: sin errores.

- [ ] **Step 4: Verificación manual en la app corriendo**

Con backend (`docker compose up -d`) y front (`npm run dev`) arriba:
1. En Descargas → Monitoreo de jobs, el selector "Todas / CFDI / Metadata" filtra la lista.
2. Al abrir un job METADATA `DESCARGADO`, aparece la tabla de preview y el botón "Descargar CSV"; el CSV baja y abre en Excel con acentos correctos.
3. En un job CFDI, NO aparecen ni la tabla ni el botón.

(Nota: hoy no existe ningún job METADATA real en `storage/`. La verificación end-to-end completa requiere disparar una solicitud METADATA real contra la empresa 11 — efecto colateral consciente sobre el SAT de producción — como indica la sección 7 del spec.)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/hooks/useJobs.ts apps/web/src/features/descargas/DescargasPage.tsx
git commit -m "feat(web): Filtro CFDI/METADATA en el Monitoreo de jobs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** §4.1 servicio → Task 1; §4.2 endpoints + schema → Task 2; §4.3 filtro repo/endpoint → Task 3; §5.1 ApiClient → Task 4; §5.2 JobDrawer → Task 5; §5.3 DescargasPage → Task 6; §6 pruebas backend → Tasks 1-3 (los tests van con cada tarea), pruebas front → verificación `tsc`/`eslint`/manual (el proyecto no tiene test unitario de front); §7 verificación en vivo → nota en Task 6 Step 4.
- **Sin placeholders:** todo el código está escrito; no hay "TBD"/"similar a".
- **Consistencia de tipos:** `parsear_metadata`/`generar_csv_metadata` reciben `(storage_root, job)` en Task 1 y así se llaman en Task 2; `MetadataPreviewOut` (backend) ↔ `MetadataPreview` (front) tienen los mismos campos; `obtenerMetadata`/`descargarMetadataCsv`/`listarJobs(solicitud)` se declaran en Task 4 y se consumen en Tasks 5-6; excepciones `MetadataNoAplicableError`/`MetadataNoDisponibleError` definidas en Task 1 y mapeadas en Task 2.
