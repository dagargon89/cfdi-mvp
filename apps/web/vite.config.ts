import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';

// Variables sin las cuales una build de producción sale rota en silencio:
// - VITE_API_BASE_URL vacía activa el modo demo (`src/lib/client.ts`) y la app funciona con
//   datos INVENTADOS sin avisar a nadie.
// - Sin las de Firebase, el login muestra "configuración pendiente".
const OBLIGATORIAS_EN_PRODUCCION = [
  'VITE_API_BASE_URL',
  'VITE_FIREBASE_API_KEY',
  'VITE_FIREBASE_AUTH_DOMAIN',
  'VITE_FIREBASE_PROJECT_ID',
  'VITE_FIREBASE_APP_ID',
] as const;

export default defineConfig(({ command, mode }) => {
  if (command === 'build' && mode === 'production') {
    const env = loadEnv(mode, process.cwd(), 'VITE_');
    const faltantes = OBLIGATORIAS_EN_PRODUCCION.filter((clave) => !env[clave]?.trim());
    if (faltantes.length) {
      throw new Error(`Build de producción cancelada: faltan ${faltantes.join(', ')}.`);
    }
    if (env.VITE_DEMO_CONTROLS === 'true') {
      throw new Error('Build de producción cancelada: VITE_DEMO_CONTROLS=true expone controles de demo.');
    }
  }

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { '@': path.resolve(__dirname, 'src') },
    },
    server: { port: 5173 },
  };
});
