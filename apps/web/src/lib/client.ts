// Único punto de wiring entre la interfaz (api.ts) y la implementación activa.
// Hooks y pantallas importan `api` de aquí — nunca api.mock.ts/api.http.ts directamente.
//
// Con backend configurado se usa SOLO el cliente real. Antes se mezclaba `{ ...apiMock, ...apiHttp }`
// para cubrir lo que el backend aún no tenía, y eso dejó un hueco que nadie veía: un método que
// faltara en el cliente real lo respondía el doble de pruebas **en producción**, con datos
// inventados (pasó con `listarConfiguracion`: la vista previa del troceo prometía ventanas de 12
// meses mientras el backend troceaba en 2). Ahora `apiHttp` está tipado como `ApiClient` completo,
// así que un método faltante es un error de compilación, no un dato falso.
//
// Sin VITE_API_BASE_URL todo usa el doble (modo demo). La build de producción se niega a compilar
// sin esa variable — ver vite.config.ts.
import type { ApiClient } from './api';
import { apiMock } from './api.mock';
import { apiHttp } from './api.http';

const backendConfigured = Boolean(import.meta.env.VITE_API_BASE_URL);

export const api: ApiClient = backendConfigured ? apiHttp : apiMock;
