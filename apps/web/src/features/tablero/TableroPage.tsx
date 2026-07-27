// demo.html:219-292 (P3 Tablero) + lógica demo.html:1194-1221,1287-1290.
import { useQuery } from '@tanstack/react-query';
import { KeyRound } from 'lucide-react';
import { Link, useNavigate } from 'react-router';
import { EstadoChip } from '@/components/ui/EstadoChip';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import { useBreakpoint } from '@/hooks/useBreakpoint';
import { useJobs } from '@/hooks/useJobs';
import { api } from '@/lib/client';
import { diasParaVencer, fechaCorta, umbralVigenciaDias } from '@/lib/domain';
import { alertaVista } from '@/features/alertas/alertaVista';

export function TableroPage() {
  const { empresa } = useEmpresaCtx();
  const { esCompacto } = useBreakpoint();
  const navigate = useNavigate();

  const { data: config } = useQuery({ queryKey: ['config'], queryFn: () => api.listarConfiguracion() });
  const { data: comprobantes } = useQuery({ queryKey: ['comprobantes', empresa.empresa_id], queryFn: () => api.listarComprobantes(empresa.empresa_id) });
  const { data: jobsPage } = useJobs(empresa.empresa_id);
  const { data: eventosPage } = useQuery({ queryKey: ['eventos-count', empresa.empresa_id], queryFn: () => api.listarEventos(empresa.empresa_id) });

  const umbral = umbralVigenciaDias(config ?? []);
  const jobs = jobsPage?.data ?? [];
  const eventos = eventosPage?.data ?? [];
  const alertas = eventos.map((e) => alertaVista(e, empresa.empresa_id));

  const dias = empresa.efirma?.presente ? diasParaVencer(empresa.efirma.not_after!) : null;
  const bannerEfirma = !empresa.efirma?.presente
    ? { tono: 'danger', texto: 'Esta empresa no tiene e.firma en la bóveda; las descargas fallarán.' }
    : dias !== null && dias <= umbral
      ? { tono: 'warning', texto: `La e.firma vence en ${dias} días (${fechaCorta(empresa.efirma.not_after)}). Renuévala para no interrumpir las descargas.` }
      : null;

  const kpis = [
    { label: 'Comprobantes', valor: String(comprobantes?.total ?? 0), pie: 'en el acervo', color: 'text-text-strong' },
    { label: 'Jobs activos', valor: String(jobs.filter((j) => j.estado === 'SOLICITADO' || j.estado === 'EN_PROCESO').length), pie: 'en proceso ahora', color: 'text-info' },
    { label: 'Jobs con error', valor: String(jobs.filter((j) => j.estado === 'ERROR').length), pie: 'requieren reintento', color: 'text-danger' },
    { label: 'Alertas', valor: String(eventos.length), pie: 'sin atender', color: eventos.length ? 'text-warning' : 'text-success' },
  ];

  return (
    <div className="flex flex-col gap-4">
      {bannerEfirma && (
        <div
          role="status"
          className={`flex items-center gap-2.5 rounded-lg px-3.5 py-3 ${bannerEfirma.tono === 'danger' ? 'text-danger bg-danger-soft' : 'text-warning bg-warning-soft'}`}
        >
          <KeyRound className="size-4.5 shrink-0" aria-hidden />
          <span className="flex-1 text-[13px] font-medium">{bannerEfirma.texto}</span>
          <Link to={`/e/${empresa.empresa_id}/efirma`} className="font-semibold underline">
            Ir a la bóveda
          </Link>
        </div>
      )}

      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
        {kpis.map((k) => (
          <div key={k.label} className="bg-surface border border-border rounded-lg px-4 py-3.5 flex flex-col gap-1">
            <span className="text-xs font-semibold text-text-muted">{k.label}</span>
            <span className={`text-2xl font-bold tracking-tight ${k.color}`}>{k.valor}</span>
            <span className="text-xs text-text-muted">{k.pie}</span>
          </div>
        ))}
      </div>

      <div className="grid gap-4 items-start" style={{ gridTemplateColumns: esCompacto ? 'minmax(0,1fr)' : 'minmax(0,1.4fr) minmax(0,1fr)' }}>
        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
            <h3 className="m-0 text-[15px] font-semibold flex-1">Descargas recientes</h3>
            <Link to={`/e/${empresa.empresa_id}/descargas`} className="text-primary font-semibold text-[13px]">Ver todas</Link>
          </div>
          <table>
            <caption className="sr-only">Descargas recientes de la empresa</caption>
            <thead>
              <tr className="bg-surface-alt">
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Job</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Periodo</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Estado</th>
              </tr>
            </thead>
            <tbody>
              {jobs.slice(0, 4).map((j) => (
                <tr
                  key={j.job_id}
                  onClick={() => navigate(`/e/${empresa.empresa_id}/descargas/${j.job_id}`)}
                  className="border-t border-border cursor-pointer h-10 hover:bg-primary-soft"
                >
                  <td className="px-3 font-mono text-[13px]">#{j.job_id}</td>
                  <td className="px-3 text-[13px] text-text-muted">{j.desde} → {j.hasta}</td>
                  <td className="px-3"><EstadoChip estado={j.estado} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
            <h3 className="m-0 text-[15px] font-semibold flex-1">Alertas activas</h3>
            <Link to={`/e/${empresa.empresa_id}/alertas`} className="text-primary font-semibold text-[13px]">Ver todas</Link>
          </div>
          <div className="flex flex-col">
            {alertas.slice(0, 3).map((a, i) => (
              <div key={i} className="flex gap-2.5 px-4 py-3 border-t border-border">
                <span className={`size-[26px] shrink-0 rounded-md grid place-items-center ${a.fg} ${a.bg}`}>
                  <a.Icon className="size-[15px]" aria-hidden />
                </span>
                <span className="flex-1 flex flex-col gap-0.5">
                  <span className="text-[13px] font-semibold">{a.titulo}</span>
                  <span className="text-xs text-text-muted text-pretty">{a.detalle}</span>
                </span>
              </div>
            ))}
            {alertas.length === 0 && <div className="py-6 px-4 text-center text-text-muted text-[13px]">Sin alertas activas</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
