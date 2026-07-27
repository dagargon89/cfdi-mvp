// Único punto de wiring entre la interfaz (api.ts) y la(s) implementación(es) activa(s).
// Hooks y pantallas importan `api` de aquí — nunca api.mock.ts/api.http.ts directamente.
//
// Backend real (Sprint 0-1) ya cubre sesión/empresas/bóveda/usuarios/bitácora — esos métodos
// se enrutan a api.http.ts. Todo lo que el backend aún no construye (descargas, comprobantes,
// alertas, notificaciones, config — Sprint 2-4) sigue resuelto por api.mock.ts. Sin
// VITE_API_BASE_URL configurado, todo cae de vuelta al mock completo (comportamiento de antes).
import type { ApiClient } from './api';
import { apiMock } from './api.mock';
import { apiHttp } from './api.http';

const backendConfigured = Boolean(import.meta.env.VITE_API_BASE_URL);

export const api: ApiClient = backendConfigured ? { ...apiMock, ...apiHttp } : apiMock;
