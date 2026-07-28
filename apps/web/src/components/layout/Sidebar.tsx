// demo.html:172-260 (aside de navegación, selector de empresa, colapsar, usuario/logout).
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from 'react-router';
import { Building2, ChevronsLeft, LogOut } from 'lucide-react';
import { NAV_ICON } from '@/components/ui/icons';
import { useAuth } from '@/auth/AuthContext';
import { useEmpresas } from '@/hooks/useEmpresas';
import { useCurrentEmpresaId } from '@/empresa/currentEmpresaStore';
import { api } from '@/lib/client';

interface NavItem {
  key: string;
  label: string;
  Icon: (typeof NAV_ICON)[keyof typeof NAV_ICON];
  href: string;
  active: boolean;
  badge?: number;
}

function iniciales(nombre: string): string {
  return nombre.split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase();
}

export function Sidebar({ esCompacto }: { esCompacto: boolean }) {
  const [abierto, setAbierto] = useState(true);
  const [selectorAbierto, setSelectorAbierto] = useState(false);
  const [buscar, setBuscar] = useState('');
  const { usuario, logout } = useAuth();
  const { data: empresas } = useEmpresas();
  const { empresaId } = useCurrentEmpresaId();
  const location = useLocation();
  const navigate = useNavigate();

  const sidebarOpen = esCompacto ? false : abierto;
  const width = sidebarOpen ? 264 : 72;
  const empresaActiva = empresas?.find((e) => e.empresa_id === empresaId) ?? null;

  const { data: eventos } = useQuery({
    queryKey: ['eventos-count', empresaId],
    queryFn: () => api.listarEventos(empresaId!),
    enabled: !!empresaId,
  });

  const path = location.pathname;
  const items: NavItem[] = [{ key: 'empresas', label: 'Empresas', Icon: NAV_ICON.edificio, href: '/empresas', active: path === '/empresas' }];
  if (empresaActiva) {
    const base = `/e/${empresaActiva.empresa_id}`;
    items.push(
      { key: 'tablero', label: 'Tablero', Icon: NAV_ICON.tablero, href: base, active: path === base },
      { key: 'efirma', label: 'Bóveda e.firma', Icon: NAV_ICON.llave, href: `${base}/efirma`, active: path.startsWith(`${base}/efirma`) },
      { key: 'descargas', label: 'Descargas', Icon: NAV_ICON.descarga, href: `${base}/descargas`, active: path.startsWith(`${base}/descargas`) },
      { key: 'comprobantes', label: 'Comprobantes', Icon: NAV_ICON.lista, href: `${base}/comprobantes`, active: path.startsWith(`${base}/comprobantes`) },
      { key: 'alertas', label: 'Alertas', Icon: NAV_ICON.triangulo, href: `${base}/alertas`, active: path.startsWith(`${base}/alertas`), badge: eventos?.total },
      { key: 'notificaciones', label: 'Notificaciones', Icon: NAV_ICON.campana, href: `${base}/notificaciones`, active: path.startsWith(`${base}/notificaciones`) },
    );
  }
  if (usuario?.rol_global === 'admin') {
    items.push(
      { key: 'usuarios', label: 'Usuarios', Icon: NAV_ICON.usuarios, href: '/admin/usuarios', active: path === '/admin/usuarios' },
      { key: 'admin', label: 'Config · Bitácora', Icon: NAV_ICON.engrane, href: '/admin/config', active: path.startsWith('/admin/config') || path.startsWith('/admin/bitacora') || path.startsWith('/admin/correo') },
    );
  }

  const empresasBuscadas = (empresas ?? [])
    .filter((e) => e.activo)
    .filter((e) => `${e.nombre} ${e.rfc}`.toLowerCase().includes(buscar.toLowerCase()));

  return (
    <aside
      aria-label="Navegación principal"
      style={{ width }}
      className="shrink-0 bg-surface border-r border-border flex flex-col sticky top-0 h-screen transition-[width] duration-[180ms] ease-out overflow-hidden"
    >
      <div className="h-14 flex items-center gap-2.5 px-3.5 border-b border-border">
        <div className="size-7 shrink-0 rounded-md bg-primary text-white grid place-items-center font-bold text-[11px]">HC</div>
        {sidebarOpen && <span className="font-bold text-[15px] whitespace-nowrap">Hub CFDI</span>}
      </div>

      {empresaId != null && (
        <div className="p-3 border-b border-border relative">
          <button
            type="button"
            onClick={() => setSelectorAbierto((s) => !s)}
            aria-haspopup="listbox"
            title={empresaActiva?.nombre ?? 'Sin acceso a esta empresa'}
            className="w-full flex items-center gap-2 bg-surface-alt border border-border rounded-md p-2 cursor-pointer text-left hover:border-primary"
          >
            <Building2 className="size-4 shrink-0 text-text-muted" aria-hidden />
            {sidebarOpen && (
              <span className="flex-1 min-w-0 flex flex-col">
                <span className="text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis">{empresaActiva?.nombre ?? 'Sin acceso a esta empresa'}</span>
                {empresaActiva && <span className="font-mono text-[11px] text-text-muted">{empresaActiva.rfc}</span>}
              </span>
            )}
          </button>
          {selectorAbierto && (
            <div
              role="listbox"
              className="absolute z-40 left-3 top-16 w-62 bg-surface border border-border rounded-lg shadow-md p-2 animate-dc-up"
            >
              <input
                aria-label="Buscar empresa"
                placeholder="Buscar empresa o RFC"
                value={buscar}
                onChange={(e) => setBuscar(e.target.value)}
                className="w-full h-8 border border-border rounded px-2 mb-1.5"
              />
              {empresasBuscadas.map((e) => (
                <button
                  key={e.empresa_id}
                  type="button"
                  onClick={() => {
                    setSelectorAbierto(false);
                    setBuscar('');
                    navigate(`/e/${e.empresa_id}`);
                  }}
                  className="w-full flex flex-col text-left gap-0 rounded-md px-2 py-1.5 cursor-pointer hover:bg-primary-soft"
                  style={{ background: e.empresa_id === empresaActiva?.empresa_id ? 'var(--primary-soft)' : 'transparent' }}
                >
                  <span className="text-[13px] font-semibold">{e.nombre}</span>
                  <span className="font-mono text-[11px] text-text-muted">{e.rfc}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <nav className="flex-1 overflow-y-auto p-2 flex flex-col gap-0.5">
        {items.map((n) => (
          <Link
            key={n.key}
            to={n.href}
            title={n.label}
            aria-current={n.active ? 'page' : undefined}
            className="flex items-center gap-2.5 w-full rounded-md px-2.5 h-9 text-left hover:bg-surface-alt"
            style={{ background: n.active ? 'var(--primary-soft)' : 'transparent', color: n.active ? 'var(--primary)' : 'var(--text-strong)', fontWeight: n.active ? 600 : 500 }}
          >
            <n.Icon className="size-[18px] shrink-0" aria-hidden />
            {sidebarOpen && <span className="flex-1 whitespace-nowrap overflow-hidden text-ellipsis text-[13px]">{n.label}</span>}
            {!!n.badge && (
              <span className="bg-danger text-white rounded-full min-w-[18px] h-[18px] px-1.5 text-[11px] font-bold grid place-items-center">{n.badge}</span>
            )}
          </Link>
        ))}
      </nav>

      <div className="border-t border-border p-2 flex flex-col gap-0.5">
        {!esCompacto && (
          <button
            type="button"
            onClick={() => setAbierto((s) => !s)}
            className="flex items-center gap-2.5 border-0 bg-transparent rounded-md h-[34px] px-2.5 cursor-pointer text-text-muted hover:bg-surface-alt"
          >
            <ChevronsLeft className={`size-[18px] transition-transform ${sidebarOpen ? '' : 'rotate-180'}`} aria-hidden />
            {sidebarOpen && <span className="text-[13px] whitespace-nowrap">Colapsar</span>}
          </button>
        )}
        <div className="flex items-center gap-2.5 px-2.5 py-1.5">
          <span className="size-[26px] shrink-0 rounded-full bg-primary-soft text-primary grid place-items-center text-[11px] font-bold">
            {usuario ? iniciales(usuario.nombre) : ''}
          </span>
          {sidebarOpen && usuario && (
            <span className="flex-1 min-w-0 flex flex-col">
              <span className="text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis">{usuario.nombre}</span>
              <span className="text-[11px] text-text-muted">{usuario.rol_global}</span>
            </span>
          )}
          <button
            type="button"
            onClick={() => void logout()}
            title="Cerrar sesión"
            aria-label="Cerrar sesión"
            className="border-0 bg-transparent cursor-pointer text-text-muted grid place-items-center size-[26px] rounded-md hover:bg-surface-alt hover:text-danger"
          >
            <LogOut className="size-[17px]" aria-hidden />
          </button>
        </div>
      </div>
    </aside>
  );
}
