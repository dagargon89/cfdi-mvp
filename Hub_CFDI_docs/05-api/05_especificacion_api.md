# 05 — Especificación de la API

| Campo | Valor |
|---|---|
| Documento | 05 — Especificación de API |
| Versión | 2.1 (**congelada** — freeze de Fase 1, 2026-07-27; ver README/CLAUDE.md tabla de fase) |
| Fecha | 2026-07-27 |
| Auth | Bearer — Firebase ID token verificado server-side |
| Base URL | `/v1` |
| Formato | JSON UTF-8 |
| Depende de | [`01_SRS`](../01-vision/01_SRS_especificacion_requisitos.md) · [`03_modelo_de_datos`](../03-datos/03_modelo_de_datos.md) · [`04_plan_de_seguridad`](../04-seguridad/04_plan_de_seguridad.md) |

> FastAPI genera OpenAPI automáticamente; este documento incluye la interfaz `ApiClient` literal (§9, **congelada**) y cualquier cambio de firma la actualiza en la misma sesión (Gobernanza v3 mejora 4).

---

## 1. Convenciones

### 1.1 Versionado
Prefijo `/v1` en URL. Cambios incompatibles ⇒ `/v2` (no previsto en MVP).

### 1.2 Autenticación
`Authorization: Bearer <firebase_id_token>` en toda petición (salvo `/health`). El backend verifica firma/exp/aud/revocación y resuelve usuario local activo + permiso sobre la empresa de la ruta (doc 04 §3.2). No hay API keys ni sesiones de cookie.

### 1.3 Códigos de estado
| Código | Semántica en este sistema |
|---|---|
| 200 | Lectura/actualización exitosa |
| 201 | Recurso creado |
| 202 | Trabajo asíncrono aceptado (descargas, validaciones, export) |
| 400 | Payload inválido (validación Pydantic) |
| 401 | Token ausente/inválido/expirado |
| 403 | Usuario inactivo, sin permiso sobre la empresa, o rol insuficiente |
| 404 | No existe **o no pertenece a una empresa autorizada** (respuesta idéntica, anti-enumeración) |
| 409 | Conflicto (RFC duplicado, transición ilegal de job) |
| 422 | Regla de negocio violada (rango inválido, e.firma vencida) |
| 429 | Rate limit excedido |
| 500 | Error no controlado (sin detalle interno al cliente) |

### 1.4 Formato de error estándar
```json
{
  "error": {
    "codigo": "EFIRMA_VENCIDA",
    "mensaje": "La e.firma de la empresa venció el 2026-06-30.",
    "detalle": {"not_after": "2026-06-30T23:59:59"},
    "trace_id": "8f2c…"
  }
}
```

### 1.5 Rate limiting
| Grupo | Endpoints | Límite |
|---|---|---|
| Auth-sensibles | alta e.firma, usuarios/permisos | 10/min/usuario |
| Mutantes | descargas, validaciones, reintentos, notificaciones | 30/min/usuario |
| Lectura | listados, monitoreo | 120/min/usuario |
| Export | export Excel | 5/min/usuario |

### 1.6 Paginación
`?page=1&per_page=50` (máx 200). Respuesta: `{ "data": [...], "page": 1, "per_page": 50, "total": 1234 }`. Orden por defecto documentado por recurso; estable (desempate por id).

---

## 2. Recurso: Sesión y usuarios (prioridad 1)

### GET /v1/me — Perfil y permisos del usuario autenticado
Resuelve el usuario local y sus empresas autorizadas; primera llamada de la SPA tras login.
**Autenticación:** Bearer. **Rate limit:** lectura.
**Respuesta 200:**
```json
{ "usuario_id": 3, "correo": "ana@demo.test", "nombre": "Ana Torres",
  "rol_global": "operador",
  "empresas": [ {"empresa_id": 7, "nombre": "Comercializadora Demo", "rfc": "EKU9003173C9", "rol": "operador"} ] }
```
**Errores:** 401 · 403 (uid sin usuario local o inactivo).
**Seguridad:** es el único endpoint que no requiere `empresa_id`; no revela usuarios ajenos.

### POST /v1/usuarios — Alta de usuario *(admin)*
Body: `{ "correo": "...", "nombre": "...", "rol_global": "operador" }` → 201. Bitácora. **Errores:** 403 (no admin) · 409 (correo existente).

### PUT /v1/usuarios/{usuario_id}/permisos — Asignar empresas *(admin)*
Body: `{ "permisos": [ {"empresa_id": 7, "rol": "operador"} ] }` → 200. Reemplaza el conjunto; bitácora.

### PATCH /v1/usuarios/{usuario_id} — Activar/desactivar, rol *(admin)*
`{ "activo": false }` → 200; efecto inmediato (RF-AUTH-04). Bitácora.

## 3. Recurso: Empresas (prioridades 1–2)

### GET /v1/empresas — Empresas autorizadas del usuario
**Respuesta 200:** lista con `empresa_id, nombre, rfc, activo, efirma: {presente, not_after} | null`.

### POST /v1/empresas — Alta *(admin)*
Body: `{ "nombre": "...", "rfc": "EKU9003173C9", "plantilla_nomenclatura": null }` → 201. **Errores:** 409 RFC duplicado · 400 RFC malformado. Bitácora.

### PATCH /v1/empresas/{empresa_id} — Edición / baja lógica *(admin)*
`{ "activo": false }` desactiva sin borrar historial (RF-EMP-02). Bitácora.

## 4. Recurso: Bóveda de e.firmas (prioridad 1)

### POST /v1/empresas/{empresa_id}/efirma — Alta/reemplazo *(operador+)*
`multipart/form-data`: `cer` (archivo), `key` (archivo), `password` (campo). El backend valida (abre, RFC coincide, vigente), cifra y persiste (RF-BOV-01).
**Respuesta 201:**
```json
{ "num_serie": "30001000000400002325", "not_before": "2024-08-01T00:00:00",
  "not_after": "2028-08-01T00:00:00", "dias_para_vencer": 735 }
```
**Errores:** 422 (`EFIRMA_NO_ABRE`, `RFC_NO_COINCIDE`, `EFIRMA_VENCIDA`) · 403.
**Seguridad:** nunca devuelve material de llave; la contraseña no se loguea; alta en bitácora; rate limit auth-sensible.

### GET /v1/empresas/{empresa_id}/efirma — Metadatos
200 con serie/vigencia, o 404 si no hay e.firma. Nunca contenido.

### DELETE /v1/empresas/{empresa_id}/efirma — Eliminar *(operador+)*
204; el historial de jobs/comprobantes permanece (RF-BOV-04). Bitácora.

## 5. Recurso: Descargas / jobs (prioridad 2)

### POST /v1/empresas/{empresa_id}/descargas — Crear descarga *(operador+)*
Trocea el rango en jobs (≤ 12 meses) y los encola (RF-DESC-01/03).
Body: `{ "tipo": "recibido", "solicitud": "CFDI", "desde": "2023-01-01", "hasta": "2025-12-31" }`
**Respuesta 202:** `{ "job_ids": [41, 42, 43], "ventanas": 3 }`
**Errores:** 422 (`EFIRMA_VENCIDA`, `RANGO_INVALIDO`, `EMPRESA_INACTIVA`) · 403. Bitácora del disparo (RF-SYNC-02).

### GET /v1/empresas/{empresa_id}/jobs — Monitoreo (RF-SYNC-03)
Query: `estado?, origen?, desde?, hasta?, page`. **200:** paginado con `job_id, tipo, solicitud, origen, ventana {desde, hasta}, estado, intentos, paquetes, mensaje, updated_at`.

### GET /v1/empresas/{empresa_id}/jobs/{job_id} — Detalle
200 con la fila completa (incluye `id_solicitud`). 404 si no es de la empresa.

### POST /v1/empresas/{empresa_id}/jobs/{job_id}/reintentar — Re-encolar ERROR *(operador+)*
202. **Errores:** 409 si el job no está en `ERROR` (transición ilegal). Bitácora.

## 6. Recurso: Comprobantes (prioridades 2–3)

### GET /v1/empresas/{empresa_id}/comprobantes — Listado (RF-LIST-01)
Query: `desde?, hasta?, tipo_comprobante?, estatus?, rfc_contraparte?, q? (razón social), page, per_page, orden?`.
**200:** paginado con las columnas del índice (uuid, folio, emisor/receptor, razón social, total, fecha, tipo, estatus, estatus_verificado_at).
**Seguridad:** consulta siempre acotada a la empresa del contexto; sin N+1.

### POST /v1/empresas/{empresa_id}/comprobantes/validar — Validación en lote *(operador+)* (RF-VAL-02)
Body: `{ "alcance": "no_verificados" | "todos" | {"uuids": [...]}}` → 202 `{ "tarea_id": "..." }`.

### GET /v1/empresas/{empresa_id}/comprobantes/export — Export a Excel (RF-LIST-02)
Mismos filtros del listado. **202** `{ "tarea_id": "..." }` → al completar, `GET /v1/tareas/{tarea_id}` responde `{ "estado": "completada", "descarga_url": "/v1/descargas-archivo/…" }` (URL firmada temporal, acotada a la empresa).

## 7. Recurso: Vigilancia y eventos (prioridad 3)

### GET /v1/empresas/{empresa_id}/eventos — Alertas (RF-RIES)
Query: `tipo? (cancelacion_tardia|efos|efirma_por_vencer|error_descarga|resumen_sync), desde?, page`.
**200:** paginado con `evento_id, tipo, detalle, created_at`. El `detalle` de EFOS incluye RFC, situación y UUIDs afectados.

### GET /v1/efos/estado — Versión de la lista 69-B cargada
**200:** `{ "version_lista": "2026-07-25", "registros": 12873 }`. Lectura global (cualquier usuario autenticado).

## 8. Recursos: Notificaciones, configuración y bitácora

### GET·PUT /v1/empresas/{empresa_id}/notificaciones — Destinos y suscripciones *(operador+)* (RF-NOT-01)
PUT body: `{ "destinos": [ {"correo": "conta@demo.test", "eventos": ["efos","cancelacion_tardia"]} ] }` → 200. Bitácora.

### GET·PUT /v1/configuracion — Parámetros operativos *(admin)* (RF-CFG-01)
Claves JSON versionadas por ejercicio (`max_meses_ventana`, `hora_sync`, `umbral_vigencia_dias`, …). PUT en bitácora.

### GET /v1/bitacora — Consulta *(admin)* (RF-BIT-01)
Query: `actor?, accion?, entidad?, desde?, hasta?, page`. Solo lectura.

---

## 9. Interfaz `ApiClient` (congelada — freeze de Fase 1, 2026-07-27)

Literal de `apps/web/src/lib/api.ts`. Dos campos y un módulo se añadieron respecto al borrador porque el
demo (Claude Design) los ejercita: `Job.id_solicitud` y `Comprobante.xml_path` (los muestran los drawers
P6/P7), y `listarUsuarios`/`listarConfiguracion`/`listarBitacora` (P10/P11, antes solo descritos como
endpoints REST en §2/§8 sin entrada en esta interfaz). Las mutaciones de usuarios de §2 (alta, permisos,
activar/desactivar) no se añaden aquí porque P10 es de solo lectura en el demo — se agregan cuando exista
una UI real que las use.

```typescript
// apps/web/src/lib/api.ts — contrato único; api.mock.ts hoy, api.http.ts cuando exista el backend real
export type Rol = 'admin' | 'operador' | 'consulta';
export type EstadoJob = 'NUEVO' | 'SOLICITADO' | 'EN_PROCESO' | 'TERMINADA' | 'DESCARGADO' | 'ERROR';
export type EstatusCfdi = 'vigente' | 'cancelado' | 'no_verificado';
export type TipoEvento = 'cancelacion_tardia' | 'efos' | 'efirma_por_vencer' | 'error_descarga' | 'resumen_sync';

export interface Page<T> { data: T[]; page: number; per_page: number; total: number }
export interface EmpresaResumen { empresa_id: number; nombre: string; rfc: string; rol: Rol;
                                  activo: boolean; efirma: { presente: boolean; not_after: string | null } | null }
export interface Job { job_id: number; tipo: 'emitido' | 'recibido'; solicitud: 'CFDI' | 'METADATA';
                       origen: 'manual' | 'sync'; desde: string; hasta: string; estado: EstadoJob;
                       intentos: number; paquetes: number; mensaje: string | null; updated_at: string;
                       id_solicitud: string | null }
export interface Comprobante { comprobante_id: number; uuid: string; folio: string | null;
                               rfc_emisor: string; rfc_receptor: string; razon_social_emisor: string | null;
                               total: number | null; fecha_emision: string | null; tipo_comprobante: string | null;
                               estatus: EstatusCfdi; estatus_verificado_at: string | null; xml_path: string | null }
export interface Evento { evento_id: number; tipo: TipoEvento; detalle: Record<string, unknown>; created_at: string }
export interface NotificacionDestino { correo: string; eventos: TipoEvento[] }
export interface UsuarioAdmin { usuario_id: number; correo: string; nombre: string; rol_global: Rol;
                                activo: boolean; permisos: { empresa_id: number; empresa_nombre: string; rol: Rol }[] }
export interface ConfiguracionItem { clave: string; ejercicio_fiscal: string; valor: string; descripcion: string }
export interface BitacoraEntrada { bitacora_id: number; actor: string; accion: string; entidad: string;
                                   detalle: Record<string, unknown>; created_at: string }

export interface ApiClient {
  // Sesión (prioridad 1)
  me(): Promise<{ usuario_id: number; correo: string; nombre: string; rol_global: Rol; empresas: EmpresaResumen[] }>;
  // Empresas
  listarEmpresas(): Promise<EmpresaResumen[]>;
  crearEmpresa(input: { nombre: string; rfc: string }): Promise<EmpresaResumen>;
  // Bóveda (prioridad 1)
  subirEfirma(empresaId: number, files: { cer: File; key: File; password: string; escenarioDemo?: string }):
    Promise<{ num_serie: string; not_before: string; not_after: string; dias_para_vencer: number }>;
  obtenerEfirma(empresaId: number): Promise<{ num_serie: string; not_before: string; not_after: string } | null>;
  eliminarEfirma(empresaId: number): Promise<void>;
  // Descargas (prioridad 2)
  crearDescarga(empresaId: number, input: { tipo: 'emitido' | 'recibido'; solicitud: 'CFDI' | 'METADATA';
                desde: string; hasta: string; simVencidaDemo?: boolean }): Promise<{ job_ids: number[]; ventanas: number }>;
  listarJobs(empresaId: number, f?: { estado?: EstadoJob; origen?: 'manual' | 'sync'; page?: number }): Promise<Page<Job>>;
  reintentarJob(empresaId: number, jobId: number): Promise<void>;
  // Comprobantes (prioridades 2–3)
  listarComprobantes(empresaId: number, f?: { desde?: string; hasta?: string; estatus?: EstatusCfdi;
                     tipo_comprobante?: string; q?: string; page?: number }): Promise<Page<Comprobante>>;
  validarLote(empresaId: number, alcance: 'no_verificados' | 'todos' | { uuids: string[] }): Promise<{ tarea_id: string }>;
  exportarExcel(empresaId: number, f?: Record<string, string>): Promise<{ tarea_id: string }>;
  estadoTarea(tareaId: string): Promise<{ estado: 'pendiente' | 'completada' | 'fallida'; descarga_url?: string }>;
  // Vigilancia y notificaciones (prioridad 3)
  listarEventos(empresaId: number, f?: { tipo?: TipoEvento; page?: number }): Promise<Page<Evento>>;
  obtenerNotificaciones(empresaId: number): Promise<{ destinos: NotificacionDestino[] }>;
  guardarNotificaciones(empresaId: number, destinos: NotificacionDestino[]): Promise<void>;
  // Administración (añadido en el freeze — doc 05 §2/§8, consumido por P10/P11; solo lectura)
  listarUsuarios(): Promise<UsuarioAdmin[]>;
  listarConfiguracion(): Promise<ConfiguracionItem[]>;
  listarBitacora(f?: { page?: number }): Promise<Page<BitacoraEntrada>>;
}
```

Campos `escenarioDemo`/`simVencidaDemo` de `subirEfirma`/`crearDescarga` son exclusivos de
`VITE_DEMO_CONTROLS` (fuerzan la respuesta del backend simulado para la sesión de validación) — no
existen en `api.http.ts` cuando se construya el backend real.

> Cobertura: sesión/usuarios, empresas, bóveda, descargas/máquina de estados (crear/monitorear/reintentar), comprobantes (listar/validar/exportar), eventos, notificaciones, administración (usuarios/configuración/bitácora, solo lectura) — todos los módulos del SRS §3.
