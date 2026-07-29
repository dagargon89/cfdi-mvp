# Diseño — Descarga y vista previa de metadata del SAT

**Fecha:** 2026-07-29
**Autor:** David García (con Claude)
**Estado:** Aprobado, listo para plan de implementación

## 1. Problema

El sistema ya permite crear solicitudes de descarga masiva al SAT de tipo `CFDI` y `METADATA`
(`solicitud` del job). Para `CFDI` el flujo está completo: el ZIP del SAT se guarda, se indexan los
XML y el usuario puede ver/descargar cada comprobante. Para `METADATA` el flujo se corta a la mitad:

- El SAT entrega la metadata como un ZIP (base64) que trae un archivo `.txt` delimitado por `~`
  (formato estándar del SAT: `Uuid~RfcEmisor~NombreEmisor~RfcReceptor~NombreReceptor~RfcPac~`
  `FechaEmision~FechaCertificacionSat~MontoTotal~EfectoComprobante~Estatus~FechaCancelacion`).
- El worker guarda ese ZIP crudo en `storage/{empresa_id}/{job_id}/paquete_N.zip`
  (`app/worker/tasks.py:105-107`).
- El indexador **descarta** todo lo que no sea `.xml` (`app/services/resguardo.py:135`), así que un job
  METADATA queda `DESCARGADO` pero produce 0 comprobantes indexados y **su contenido no se ve ni se
  descarga en ningún lado**. Hoy solo se ve el job en sí (Monitoreo de jobs), no su metadata.

**Objetivo:** convertir la metadata descargada en algo consumible — verla en pantalla y bajarla como
CSV — sin tocar cómo se solicita ni cómo se archiva.

## 2. Decisiones tomadas (brainstorming)

| Decisión | Elección |
|---|---|
| Fuente de la metadata | El TXT `~` **real del SAT** dentro del ZIP del job METADATA (no derivarla de la BD) |
| Formato de descarga | **CSV** |
| Encabezados del CSV | **Tal cual del SAT** (`Uuid`, `RfcEmisor`, …), sin traducir |
| Disparador de la descarga | **Por job METADATA** ya `DESCARGADO` |
| Vista previa en pantalla | **Sí**, tabla paginada en el detalle del job |
| Filtro CFDI/METADATA | En **Monitoreo de jobs** (Descargas), no en la lista de Comprobantes |
| Mecanismo | **Síncrono** (`Response`/`StreamingResponse`), no tarea Celery |

**Fuera de alcance (YAGNI):** indexar la metadata en una tabla de BD; enriquecer los comprobantes CFDI
con el estatus de cancelación de la metadata; export en Excel/otros formatos; descarga combinada por
empresa+rango de varios jobs.

## 3. Arquitectura

La feature agrega **solo una capa de lectura/exportación** sobre lo que ya existe:

```
Job METADATA (ya DESCARGADO)
  → storage/{empresa}/{job}/paquete_N.zip           [ya existe, sin cambios]
  → [NUEVO] app/services/metadata_export.py: abre los zips, extrae el .txt ~-delimitado, junta filas
  → [NUEVO] GET .../jobs/{job_id}/metadata      → JSON paginado (vista previa)
  → [NUEVO] GET .../jobs/{job_id}/metadata.csv  → CSV completo (descarga)
  → [NUEVO] JobDrawer: tabla de preview + botón "Descargar CSV"
  → [NUEVO] filtro Solicitud (CFDI/METADATA) en Monitoreo de jobs
```

## 4. Backend

### 4.1 Servicio `app/services/metadata_export.py` (nuevo)

Responsabilidad única: de los ZIPs de un job → filas de metadata / bytes de CSV. No toca la BD.

```
parsear_metadata(storage_root, empresa_id, job_id) -> (headers: list[str], filas: list[list[str]])
generar_csv_metadata(storage_root, empresa_id, job_id) -> bytes   # reutiliza parsear_metadata
```

Lógica de `parsear_metadata`:
1. Reutiliza `_ruta_paquetes(storage_root, empresa_id, job_id)` (patrón de `resguardo.py:69`).
2. Recorre `paquete_*.zip` ordenados; dentro de cada uno abre las entradas **`.txt`** (case-insensitive).
3. Cada TXT es `~`-delimitado con **fila de encabezado**. Se conserva el encabezado del **primer** TXT
   y se **omite** el de los siguientes (varios paquetes → un solo conjunto de columnas). Se descartan
   líneas vacías (el TXT del SAT suele traer una línea final vacía).
4. Devuelve `(headers, filas)` con los valores tal cual (sin reinterpretar tipos).

`generar_csv_metadata`:
- Llama a `parsear_metadata`, escribe con el módulo `csv` (delimitador coma, quoting automático por si un
  nombre trae comas/comillas), codificación **UTF-8 con BOM** (`utf-8-sig`) para que Excel abra bien los
  acentos.

Excepciones tipadas (patrón de `app/services/descargas.py`):
- `MetadataNoAplicableError` — el job no es de tipo METADATA.
- `MetadataNoDisponibleError` — el job no está `DESCARGADO`, o no hay carpeta de paquetes, o ningún
  `.txt` dentro (p. ej. el SAT devolvió `5004` "sin resultados").

### 4.2 Endpoints (en `app/api/v1/descargas.py`)

Ambos síncronos, permiso `RolEmpresa.CONSULTA`, cargan el job con
`jobs_repo.por_id_de_empresa(db, empresa_id, job_id)` (404 si no existe), y mapean las excepciones del
servicio a `HTTPException` (422 con `{codigo, mensaje}`, mismo patrón que `crear_descarga_endpoint`).

| Método | Ruta | Respuesta |
|---|---|---|
| `GET` | `/empresas/{empresa_id}/jobs/{job_id}/metadata?page=N` | `MetadataPreviewOut` (JSON) |
| `GET` | `/empresas/{empresa_id}/jobs/{job_id}/metadata.csv` | `Response` CSV, `text/csv`, `Content-Disposition: attachment; filename="metadata_job{job_id}.csv"` |

`MetadataPreviewOut` (nuevo en `app/api/v1/schemas.py`):
```
headers: list[str]
filas:   list[list[str]]     # solo la página pedida
total:   int                 # total de filas (todas las páginas)
page:    int
per_page: int                # 100
```
Paginación: `per_page = 100`, `page` 1-based; el JSON solo devuelve la porción de esa página. El CSV
**no** pagina: baja todas las filas.

### 4.3 Filtro por solicitud en el listado de jobs

- `GET /empresas/{empresa_id}/jobs` suma el query param opcional `solicitud: SolicitudTipo | None`.
- `jobs_repo.listar(...)` suma el filtro opcional `solicitud` (mismo estilo que `estado`/`origen`).

## 5. Frontend (`apps/web`)

### 5.1 ApiClient (`src/lib/api.ts` + `src/lib/api.http.ts`)
- `obtenerMetadata(empresaId, jobId, page?) : Promise<MetadataPreview>` donde
  `MetadataPreview = { headers: string[]; filas: string[][]; total: number; page: number; per_page: number }`.
- `descargarMetadataCsv(empresaId, jobId) : Promise<void>` — descarga de archivo, mismo patrón que las
  descargas por comprobante existentes en `api.http.ts`.
- `listarJobs` suma el filtro opcional `solicitud?: 'CFDI' | 'METADATA'`.

### 5.2 `JobDrawer.tsx`
Cuando `job.solicitud === 'METADATA' && job.estado === 'DESCARGADO'`:
- **Tabla de vista previa** con los encabezados del SAT y las filas de la página actual; controles de
  página (anterior/siguiente) y contador "N registros". Estado de carga y de error (si el servicio
  devuelve `MetadataNoDisponibleError`, mostrar un aviso amable: "Este job no trajo metadata").
- Botón **"Descargar CSV"** en el pie del drawer (junto a Reintentar), llama a `descargarMetadataCsv`.

### 5.3 `DescargasPage.tsx`
- Selector `Solicitud: Todos / CFDI / Metadata` junto a los filtros existentes del Monitoreo de jobs;
  pasa el valor a `listarJobs`.

## 6. Pruebas

**Backend — `tests/test_metadata_export.py`** (dobles, sin red del SAT — mismo límite de seguridad de
sprints previos):
- ZIP con un TXT `~` (header + N filas) → `parsear_metadata` devuelve headers y filas correctas.
- Multi-paquete (`paquete_1.zip` + `paquete_2.zip`) → un solo header, filas concatenadas.
- Línea final vacía del TXT → se descarta.
- `generar_csv_metadata` → CSV con BOM, comas, quoting correcto ante valores con `,`/`"`.
- Job no METADATA → `MetadataNoAplicableError`.
- Job no `DESCARGADO` / sin `.txt` (caso `5004`) → `MetadataNoDisponibleError`.
- Endpoint `GET .../metadata` paginación: `page` fuera de rango → página vacía + `total` correcto.
- Endpoint `GET .../metadata.csv` → headers HTTP correctos (`Content-Type`, `Content-Disposition`).
- `GET .../jobs?solicitud=METADATA` → filtra correctamente.

**Frontend:**
- Botón "Descargar CSV" y tabla de preview aparecen **solo** para METADATA + DESCARGADO.
- El filtro de Monitoreo de jobs pasa el parámetro `solicitud`.

## 7. Verificación en vivo (post-implementación)

Como no existe aún ningún job METADATA en `storage/` (todos los paquetes actuales son CFDI), la
verificación real requiere que David dispare una solicitud METADATA contra la empresa 11 (efecto
colateral consciente: encola una solicitud real al SAT con la e.firma de producción). Tras completarse:
confirmar la preview en pantalla y el CSV descargado contra el TXT crudo del ZIP en disco.

## 8. Archivos afectados

**Nuevos:**
- `app/services/metadata_export.py`
- `tests/test_metadata_export.py`

**Modificados:**
- `app/api/v1/descargas.py` — 2 endpoints nuevos + param `solicitud` en el listado.
- `app/api/v1/schemas.py` — `MetadataPreviewOut`.
- `app/repositories/jobs.py` — filtro `solicitud` en `listar`.
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/api.http.ts` — métodos nuevos + filtro.
- `apps/web/src/features/descargas/JobDrawer.tsx` — tabla de preview + botón CSV.
- `apps/web/src/features/descargas/DescargasPage.tsx` — filtro Solicitud.
