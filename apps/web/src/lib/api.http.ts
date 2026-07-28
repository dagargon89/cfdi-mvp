// Implementación HTTP real contra el backend FastAPI — cubre lo que Sprint 0-3 construyó
// (sesión, empresas, bóveda, usuarios admin, bitácora, descargas/jobs, comprobantes/validar/
// export). Todo lo demás (alertas, notificaciones, config) no tiene endpoint real todavía —
// lib/client.ts combina este objeto con api.mock.ts para esos métodos, no lo uses solo.
import { ApiError } from './api';
import type { ApiClient, BitacoraEntrada, Comprobante, EmpresaResumen, Job, Page, UsuarioAdmin } from './api';
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

type ApiClientHttpSubset = Pick<
  ApiClient,
  | 'me'
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
  | 'listarUsuarios'
  | 'listarBitacora'
>;

export const apiHttp: ApiClientHttpSubset = {
  me: () => request('/v1/me'),

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

  listarUsuarios: () => request<UsuarioAdmin[]>('/v1/usuarios'),

  listarBitacora: (f) => {
    const params = f?.page ? `?page=${f.page}` : '';
    return request<Page<BitacoraEntrada>>(`/v1/bitacora${params}`);
  },
};
