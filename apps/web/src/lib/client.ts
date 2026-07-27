// Único punto de wiring entre la interfaz (api.ts) y la implementación activa (api.mock.ts hoy).
// Hooks y pantallas importan `api` de aquí — nunca api.mock.ts directamente.
import type { ApiClient } from './api';
import { apiMock } from './api.mock';

export const api: ApiClient = apiMock;
