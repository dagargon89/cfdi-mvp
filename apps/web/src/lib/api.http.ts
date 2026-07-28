// Implementación HTTP real contra el backend FastAPI — cubre exactamente lo que Sprint 0-1
// construyó (sesión, empresas, bóveda, usuarios admin, bitácora). Todo lo demás (descargas,
// comprobantes, alertas, notificaciones, config) no tiene endpoint real todavía — lib/client.ts
// combina este objeto con api.mock.ts para esos métodos, no lo uses solo ni lo importes aparte.
import { ApiError } from './api';
import type { ApiClient, BitacoraEntrada, EmpresaResumen, Page, UsuarioAdmin } from './api';
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

  listarUsuarios: () => request<UsuarioAdmin[]>('/v1/usuarios'),

  listarBitacora: (f) => {
    const params = f?.page ? `?page=${f.page}` : '';
    return request<Page<BitacoraEntrada>>(`/v1/bitacora${params}`);
  },
};
