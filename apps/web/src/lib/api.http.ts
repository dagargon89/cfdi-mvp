// Implementación HTTP real contra el backend FastAPI — cubre lo que Sprint 0-4 construyó
// (sesión, empresas, bóveda, usuarios admin, bitácora, descargas/jobs, comprobantes/validar/
// export, eventos/EFOS/notificaciones, config de correo saliente). El listado genérico de
// `configuracion` (P11) no tiene endpoint real todavía — lib/client.ts combina este objeto
// con api.mock.ts para ese método, no lo uses solo.
import { ApiError } from './api';
import type { ApiClient, BitacoraEntrada, Comprobante, ConfigSmtp, EmpresaResumen, Evento, Job, MetadataPreview, Page, UsuarioAdmin } from './api';
import { getIdToken } from './firebase';

const BASE_URL = import.meta.env.VITE_API_BASE_URL;

interface ErrorEnvelope {
  error: { codigo: string; mensaje: string; trace_id?: string; detalle?: unknown };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getIdToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  const data: unknown = text ? JSON.parse(text) : null;

  if (!res.ok) {
    const envelope = data as ErrorEnvelope;
    throw new ApiError(res.status, envelope?.error?.codigo ?? 'ERROR', envelope?.error?.mensaje ?? 'Error de red.');
  }
  return data as T;
}

/** Como `request()` pero para respuestas binarias (PDF/zip) — nunca intenta `JSON.parse` del
 * cuerpo exitoso; si falla, el backend igual manda el sobre de error de siempre en JSON. */
async function requestBlob(path: string, init: RequestInit = {}): Promise<Blob> {
  const token = await getIdToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });

  if (!res.ok) {
    const text = await res.text();
    let envelope: ErrorEnvelope | null = null;
    try {
      envelope = text ? JSON.parse(text) : null;
    } catch {
      // el cuerpo de error no era JSON — se usa el mensaje genérico de abajo
    }
    throw new ApiError(res.status, envelope?.error?.codigo ?? 'ERROR', envelope?.error?.mensaje ?? 'Error de red.');
  }
  return res.blob();
}

type ApiClientHttpSubset = Pick<
  ApiClient,
  | 'me'
  | 'estadoBootstrap'
  | 'crearAdminBootstrap'
  | 'listarEmpresas'
  | 'crearEmpresa'
  | 'actualizarEmpresa'
  | 'eliminarEmpresa'
  | 'subirEfirma'
  | 'obtenerEfirma'
  | 'eliminarEfirma'
  | 'crearDescarga'
  | 'listarJobs'
  | 'reintentarJob'
  | 'listarComprobantes'
  | 'validarLote'
  | 'exportarExcel'
  | 'estadoTarea'
  | 'descargarComprobantePdf'
  | 'descargarComprobanteDetalle'
  | 'descargarComprobanteZip'
  | 'descargarLoteZip'
  | 'obtenerMetadata'
  | 'descargarMetadataCsv'
  | 'listarUsuarios'
  | 'registrarUsuario'
  | 'actualizarUsuario'
  | 'eliminarUsuario'
  | 'listarBitacora'
  | 'listarEventos'
  | 'obtenerNotificaciones'
  | 'guardarNotificaciones'
  | 'obtenerConfigSmtp'
  | 'guardarConfigSmtp'
  | 'probarConfigSmtp'
>;

export const apiHttp: ApiClientHttpSubset = {
  me: () => request('/v1/me'),

  estadoBootstrap: () => request<{ needs_bootstrap: boolean }>(`/v1/auth/bootstrap-status`),

  crearAdminBootstrap: (body) => request<void>(`/v1/auth/bootstrap`, { method: 'POST', body: JSON.stringify(body) }),

  listarEmpresas: () => request<EmpresaResumen[]>('/v1/empresas'),

  crearEmpresa: (input) =>
    request('/v1/empresas', { method: 'POST', body: JSON.stringify(input) }),

  actualizarEmpresa: (empresaId, input) =>
    request(`/v1/empresas/${empresaId}`, { method: 'PATCH', body: JSON.stringify(input) }),

  eliminarEmpresa: (empresaId) => request(`/v1/empresas/${empresaId}`, { method: 'DELETE' }),

  subirEfirma: (empresaId, { cer, key, password }) => {
    const form = new FormData();
    form.set('cer', cer);
    form.set('key', key);
    form.set('password', password);
    return request(`/v1/empresas/${empresaId}/efirma`, { method: 'POST', body: form });
  },

  obtenerEfirma: (empresaId) => request(`/v1/empresas/${empresaId}/efirma`),

  eliminarEfirma: (empresaId) => request(`/v1/empresas/${empresaId}/efirma`, { method: 'DELETE' }),

  crearDescarga: (empresaId, { tipo, solicitud, desde, hasta }) =>
    request(`/v1/empresas/${empresaId}/descargas`, { method: 'POST', body: JSON.stringify({ tipo, solicitud, desde, hasta }) }),

  listarJobs: (empresaId, f) => {
    const params = new URLSearchParams();
    if (f?.estado) params.set('estado', f.estado);
    if (f?.origen) params.set('origen', f.origen);
    if (f?.solicitud) params.set('solicitud', f.solicitud);
    if (f?.page) params.set('page', String(f.page));
    const qs = params.toString();
    return request<Page<Job>>(`/v1/empresas/${empresaId}/jobs${qs ? `?${qs}` : ''}`);
  },

  reintentarJob: (empresaId, jobId) => request(`/v1/empresas/${empresaId}/jobs/${jobId}/reintentar`, { method: 'POST' }),

  listarComprobantes: (empresaId, f) => {
    const params = new URLSearchParams();
    if (f?.desde) params.set('desde', f.desde);
    if (f?.hasta) params.set('hasta', f.hasta);
    if (f?.estatus) params.set('estatus', f.estatus);
    if (f?.tipo_comprobante) params.set('tipo_comprobante', f.tipo_comprobante);
    if (f?.direccion) params.set('direccion', f.direccion);
    if (f?.q) params.set('q', f.q);
    if (f?.page) params.set('page', String(f.page));
    const qs = params.toString();
    return request<Page<Comprobante>>(`/v1/empresas/${empresaId}/comprobantes${qs ? `?${qs}` : ''}`);
  },

  validarLote: (empresaId, alcance) =>
    request(`/v1/empresas/${empresaId}/comprobantes/validar`, { method: 'POST', body: JSON.stringify({ alcance }) }),

  exportarExcel: (empresaId, f) => {
    const params = new URLSearchParams();
    for (const [clave, valor] of Object.entries(f ?? {})) {
      if (valor) params.set(clave, valor);
    }
    const qs = params.toString();
    return request(`/v1/empresas/${empresaId}/comprobantes/export${qs ? `?${qs}` : ''}`);
  },

  estadoTarea: (tareaId) => request(`/v1/tareas/${tareaId}`),

  descargarComprobantePdf: (empresaId, comprobanteId) => requestBlob(`/v1/empresas/${empresaId}/comprobantes/${comprobanteId}/pdf`),

  descargarComprobanteDetalle: (empresaId, comprobanteId) => requestBlob(`/v1/empresas/${empresaId}/comprobantes/${comprobanteId}/detalle`),

  descargarComprobanteZip: (empresaId, comprobanteId) => requestBlob(`/v1/empresas/${empresaId}/comprobantes/${comprobanteId}/paquete`),

  descargarLoteZip: (empresaId, comprobanteIds) =>
    request(`/v1/empresas/${empresaId}/comprobantes/descargar-zip`, { method: 'POST', body: JSON.stringify({ comprobante_ids: comprobanteIds }) }),

  obtenerMetadata: (empresaId, jobId, page) =>
    request<MetadataPreview>(`/v1/empresas/${empresaId}/jobs/${jobId}/metadata${page ? `?page=${page}` : ''}`),

  descargarMetadataCsv: (empresaId, jobId) =>
    requestBlob(`/v1/empresas/${empresaId}/jobs/${jobId}/metadata.csv`),

  listarUsuarios: () => request<UsuarioAdmin[]>('/v1/usuarios'),

  registrarUsuario: (body) => request<void>(`/v1/auth/registro`, { method: 'POST', body: JSON.stringify(body) }),

  actualizarUsuario: (id, body) => request<void>(`/v1/usuarios/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  eliminarUsuario: (id) => request<void>(`/v1/usuarios/${id}`, { method: 'DELETE' }),

  listarBitacora: (f) => {
    const params = f?.page ? `?page=${f.page}` : '';
    return request<Page<BitacoraEntrada>>(`/v1/bitacora${params}`);
  },

  listarEventos: (empresaId, f) => {
    const params = new URLSearchParams();
    if (f?.tipo) params.set('tipo', f.tipo);
    if (f?.page) params.set('page', String(f.page));
    const qs = params.toString();
    return request<Page<Evento>>(`/v1/empresas/${empresaId}/eventos${qs ? `?${qs}` : ''}`);
  },

  obtenerNotificaciones: (empresaId) => request(`/v1/empresas/${empresaId}/notificaciones`),

  guardarNotificaciones: (empresaId, destinos) =>
    request(`/v1/empresas/${empresaId}/notificaciones`, { method: 'PUT', body: JSON.stringify({ destinos }) }),

  obtenerConfigSmtp: () => request<ConfigSmtp>('/v1/config/smtp'),

  guardarConfigSmtp: (input) => request('/v1/config/smtp', { method: 'PUT', body: JSON.stringify(input) }),

  probarConfigSmtp: (input) => request('/v1/config/smtp/probar', { method: 'POST', body: JSON.stringify(input) }),
};
