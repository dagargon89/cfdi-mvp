// demo.html:609-643 (P8 Alertas) + lógica demo.html:1209-1222.
import { useQuery } from '@tanstack/react-query';
import { Link, Navigate } from 'react-router';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import { api } from '@/lib/client';
import { alertaVista } from './alertaVista';

export function AlertasPage() {
  const { empresa, rol } = useEmpresaCtx();
  const { data: eventosPage } = useQuery({ queryKey: ['eventos', empresa.empresa_id], queryFn: () => api.listarEventos(empresa.empresa_id), enabled: rol !== 'consulta' });

  // El rol de solo consulta no tiene acceso a Alertas — si entra por URL directa, al tablero.
  if (rol === 'consulta') return <Navigate to={`/e/${empresa.empresa_id}`} replace />;
  const alertas = (eventosPage?.data ?? []).map((e) => alertaVista(e, empresa.empresa_id));

  return (
    <div className="flex flex-col gap-3 max-w-[900px]">
      {alertas.map((a, i) => (
        <div key={i} className="bg-surface border border-border rounded-lg p-4 flex gap-3" style={{ borderLeftWidth: 3, borderLeftColor: `var(--${a.fg.replace('text-', '')})` }}>
          <span className={`size-[30px] shrink-0 rounded-md grid place-items-center ${a.fg} ${a.bg}`}>
            <a.Icon className="size-[17px]" aria-hidden />
          </span>
          <div className="flex-1 min-w-0 flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="m-0 text-[15px] font-semibold">{a.titulo}</h3>
              <span className={`text-[11px] font-semibold rounded-md px-2 py-0.5 ${a.fg} ${a.bg}`}>{a.tipo}</span>
              <span className="flex-1" />
              <span className="text-xs text-text-muted">{a.createdAt}</span>
            </div>
            <p className="m-0 text-[13px] text-text-muted text-pretty">{a.detalle}</p>
            {a.uuids && (
              <div className="flex flex-col gap-1">
                <span className="text-xs font-semibold text-text-muted">Comprobantes afectados</span>
                {a.uuids.map((u) => (
                  <span key={u} className="font-mono text-xs bg-surface-alt rounded px-2 py-1 inline-block w-fit">{u}</span>
                ))}
              </div>
            )}
            <div>
              <Link
                to={a.accionHref}
                className="h-8 border border-border bg-surface rounded-md px-3 text-[13px] font-semibold inline-flex items-center hover:bg-surface-alt"
              >
                {a.accionTexto}
              </Link>
            </div>
          </div>
        </div>
      ))}
      {alertas.length === 0 && (
        <div className="bg-surface border border-border rounded-lg p-12 text-center text-text-muted text-[13px]">Sin alertas activas</div>
      )}
    </div>
  );
}
