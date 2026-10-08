// Configuración de la empresa con sus apartados — /e/:id/configuracion[/alertas|/notificaciones].
//
// Alertas y Notificaciones vivían como entradas propias del sidebar; se agrupan aquí para que el
// menú lateral quede con lo que se usa a diario. El contador de alertas pendientes se conserva en
// la pestaña y en la entrada "Configuración" del sidebar, para que mover la sección no las esconda.
import { useQuery } from '@tanstack/react-query';
import { Link, Outlet, useLocation } from 'react-router';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import { api } from '@/lib/client';

export function ConfiguracionLayout() {
  const { empresa, rol } = useEmpresaCtx();
  const { pathname } = useLocation();
  const base = `/e/${empresa.empresa_id}/configuracion`;
  // Mismo queryKey que el sidebar: una sola petición para los dos contadores.
  const { data: eventos } = useQuery({
    queryKey: ['eventos-count', empresa.empresa_id],
    queryFn: () => api.listarEventos(empresa.empresa_id),
    enabled: rol !== 'consulta',
  });

  const pestañas = [
    { href: base, etiqueta: 'Empresa', activa: pathname === base || pathname === `${base}/` },
    // Alertas y Notificaciones no aplican al rol de solo consulta en esa empresa.
    ...(rol !== 'consulta'
      ? [
          { href: `${base}/alertas`, etiqueta: 'Alertas', activa: pathname.startsWith(`${base}/alertas`), badge: eventos?.total },
          { href: `${base}/notificaciones`, etiqueta: 'Notificaciones', activa: pathname.startsWith(`${base}/notificaciones`) },
        ]
      : []),
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* Con una sola pestaña (rol de consulta) la barra no aporta nada. */}
      {pestañas.length > 1 && (
        <nav aria-label="Apartados de configuración" className="flex gap-1 bg-surface-alt rounded-md p-0.5 w-fit max-w-full overflow-x-auto">
          {pestañas.map((t) => (
            <Link
              key={t.href}
              to={t.href}
              aria-current={t.activa ? 'page' : undefined}
              className="h-[30px] rounded px-3.5 text-[13px] font-semibold inline-flex items-center gap-1.5 whitespace-nowrap"
              style={{ background: t.activa ? 'var(--surface)' : 'transparent', color: t.activa ? 'var(--primary)' : 'var(--text-muted)' }}
            >
              {t.etiqueta}
              {'badge' in t && !!t.badge && (
                <span className="bg-danger text-white rounded-full min-w-[18px] h-[18px] px-1.5 text-[11px] font-bold grid place-items-center">{t.badge}</span>
              )}
            </Link>
          ))}
        </nav>
      )}
      <Outlet />
    </div>
  );
}
