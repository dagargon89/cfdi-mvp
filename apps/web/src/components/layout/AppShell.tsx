// demo.html:257-274 (header) + contenedor <main> — layout compartido por todas las pantallas autenticadas.
import { Outlet, useLocation } from 'react-router';
import { Sidebar } from './Sidebar';
import { useAuth } from '@/auth/AuthContext';
import { useCurrentEmpresaId } from '@/empresa/currentEmpresaStore';
import { useEmpresas } from '@/hooks/useEmpresas';
import { useBreakpoint } from '@/hooks/useBreakpoint';
import { useJobCompletedToast } from '@/hooks/useJobCompletedToast';

function tituloDePantalla(pathname: string, empresaNombre: string | undefined): string {
  if (pathname === '/empresas') return 'Empresas';
  if (pathname.includes('/efirma')) return 'Bóveda de e.firma';
  if (pathname.includes('/descargas')) return 'Descargas';
  if (pathname.includes('/comprobantes')) return 'Comprobantes';
  if (pathname.includes('/alertas')) return 'Alertas y eventos';
  if (pathname.includes('/notificaciones')) return 'Notificaciones';
  if (pathname === '/admin/usuarios') return 'Administración · Usuarios';
  if (pathname.startsWith('/admin/')) return 'Administración · Configuración';
  if (/^\/e\/\d+$/.test(pathname)) return empresaNombre ?? 'Tablero';
  return 'Hub CFDI';
}

export function AppShell() {
  const { usuario } = useAuth();
  const { empresaId } = useCurrentEmpresaId();
  const { data: empresas } = useEmpresas();
  const empresaActiva = empresas?.find((e) => e.empresa_id === empresaId) ?? null;
  const { esCompacto, esMovil } = useBreakpoint();
  const location = useLocation();
  useJobCompletedToast();

  const rolActual = empresaActiva?.rol ?? usuario?.rol_global ?? 'sin acceso';

  return (
    <div className="min-h-screen flex bg-bg">
      <Sidebar esCompacto={esCompacto} />
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 shrink-0 bg-surface border-b border-border flex items-center gap-3 px-6 sticky top-0 z-20">
          <h1 className="m-0 text-base font-semibold whitespace-nowrap overflow-hidden text-ellipsis">
            {tituloDePantalla(location.pathname, empresaActiva?.nombre)}
          </h1>
          <span className="flex-1" />
          {empresaActiva && <span className="font-mono text-xs text-text-muted">{empresaActiva.rfc}</span>}
          <span className="text-xs text-text-muted border-l border-border pl-3 whitespace-nowrap">
            Rol: <strong className="text-text-strong">{rolActual}</strong>
          </span>
        </header>
        <main className="flex-1 flex flex-col gap-5 max-w-[1440px] w-full" style={{ padding: esMovil ? 12 : 24 }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
