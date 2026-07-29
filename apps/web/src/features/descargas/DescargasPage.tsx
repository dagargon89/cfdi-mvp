// demo.html:385-501 (P5 Descargas) + lógica demo.html:1224-1225,1339-1356.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Button } from '@/components/ui/Button';
import { EstadoChip } from '@/components/ui/EstadoChip';
import { Paginador, type TamañoPagina } from '@/components/ui/Paginador';
import { useToast } from '@/components/ui/ToastProvider';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import { useBreakpoint } from '@/hooks/useBreakpoint';
import { useJobs } from '@/hooks/useJobs';
import { ApiError } from '@/lib/api';
import { api } from '@/lib/client';
import { maxMesesVentana, ventanasDe } from '@/lib/domain';
import { JobDrawer } from './JobDrawer';

const DEMO_CONTROLS = import.meta.env.VITE_DEMO_CONTROLS === 'true';

export function DescargasPage() {
  const { empresa, puedeMutar } = useEmpresaCtx();
  const { esMovil, esEscritorio } = useBreakpoint();
  const { toast } = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { job: jobParam } = useParams();

  const { data: config } = useQuery({ queryKey: ['config'], queryFn: () => api.listarConfiguracion() });
  const [pagina, setPagina] = useState(1);
  const [porPagina, setPorPagina] = useState<TamañoPagina>(25);
  const [filtroSolicitud, setFiltroSolicitud] = useState<'' | 'CFDI' | 'METADATA'>('');
  const perPageEfectivo = porPagina === 'todos' ? 100_000 : porPagina;
  const { data: jobsPage } = useJobs(empresa.empresa_id, pagina, filtroSolicitud || undefined, perPageEfectivo);
  const jobs = jobsPage?.data ?? [];

  const [tipo, setTipo] = useState<'recibido' | 'emitido'>('recibido');
  const [solicitud, setSolicitud] = useState<'CFDI' | 'METADATA'>('CFDI');
  const [desde, setDesde] = useState('2023-01-01');
  const [hasta, setHasta] = useState('2025-12-31');
  const [simVencida, setSimVencida] = useState(false);
  const [error, setError] = useState<{ codigo: string; mensaje: string } | null>(null);

  const maxMeses = maxMesesVentana(config ?? []);
  const ventanas = useMemo(() => ventanasDe(desde, hasta, maxMeses), [desde, hasta, maxMeses]);

  const crear = useMutation({
    mutationFn: () => api.crearDescarga(empresa.empresa_id, { tipo, solicitud, desde, hasta, simVencidaDemo: DEMO_CONTROLS ? simVencida : undefined }),
    onSuccess: (r) => {
      setError(null);
      setPagina(1); // los jobs nuevos aparecen primero (orden desc por job_id)
      qc.invalidateQueries({ queryKey: ['jobs', empresa.empresa_id] });
      toast(`${r.ventanas} solicitud(es) enviadas al SAT`, 'ok');
    },
    onError: (e) => {
      if (e instanceof ApiError) setError({ codigo: `${e.status} · ${e.codigo}`, mensaje: e.message });
      toast('No se pudo crear la descarga', 'error');
    },
  });

  const reintentar = useMutation({
    mutationFn: (jobId: number) => api.reintentarJob(empresa.empresa_id, jobId),
    onSuccess: (_data, jobId) => {
      qc.invalidateQueries({ queryKey: ['jobs', empresa.empresa_id] });
      toast(`Job #${jobId} reenviado al SAT`, 'ok');
      navigate(`/e/${empresa.empresa_id}/descargas`);
    },
  });

  const jobDrawer = jobParam ? jobs.find((j) => j.job_id === Number(jobParam)) ?? null : null;
  const previewTitulo = ventanas.length
    ? `Preview del troceo: ${ventanas.length} ventana(s) de máximo ${maxMeses} meses`
    : 'Rango inválido: la fecha final debe ser posterior a la inicial';

  return (
    <div className="flex flex-col gap-4">
      {puedeMutar && (
        <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3.5">
          <h3 className="m-0 text-[15px] font-semibold">Nueva descarga</h3>
          <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="d-tipo" className="text-xs font-semibold text-text-muted">Tipo</label>
              <select id="d-tipo" value={tipo} onChange={(e) => setTipo(e.target.value as typeof tipo)} className="h-9 border border-border rounded px-2">
                <option value="recibido">Recibidos</option>
                <option value="emitido">Emitidos</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="d-sol" className="text-xs font-semibold text-text-muted">Solicitud</label>
              <select id="d-sol" value={solicitud} onChange={(e) => setSolicitud(e.target.value as typeof solicitud)} className="h-9 border border-border rounded px-2">
                <option value="CFDI">CFDI (XML)</option>
                <option value="METADATA">Metadata</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="d-desde" className="text-xs font-semibold text-text-muted">Desde</label>
              <input id="d-desde" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} className="h-9 border border-border rounded px-2" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="d-hasta" className="text-xs font-semibold text-text-muted">Hasta</label>
              <input id="d-hasta" type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} className="h-9 border border-border rounded px-2" />
            </div>
          </div>

          <div className="bg-surface-alt rounded-md p-3 flex flex-col gap-2">
            <span className="text-xs font-semibold text-text-muted">{previewTitulo}</span>
            <div className="flex flex-wrap gap-2">
              {ventanas.map((v) => (
                <span key={v.label} className="bg-surface border border-border rounded-md px-2.5 py-1.5 font-mono text-xs">{v.label}</span>
              ))}
            </div>
          </div>

          {error && (
            <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2.5 flex flex-col gap-0.5">
              <strong className="text-[13px] font-mono">{error.codigo}</strong>
              <span className="text-[13px] text-pretty">{error.mensaje}</span>
            </div>
          )}

          <div className="flex items-center gap-3 flex-wrap">
            <Button onClick={() => crear.mutate()} loading={crear.isPending} disabled={crear.isPending || ventanas.length === 0}>
              Lanzar descarga
            </Button>
            {DEMO_CONTROLS && (
              <label className="inline-flex items-center gap-1.5 text-xs text-text-muted cursor-pointer">
                <input type="checkbox" checked={simVencida} onChange={(e) => setSimVencida(e.target.checked)} /> Simular e.firma vencida (422)
              </label>
            )}
          </div>
        </div>
      )}

      <div className="bg-surface border border-border rounded-lg overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <h3 className="m-0 text-[15px] font-semibold flex-1">Monitoreo de jobs</h3>
          <select
            aria-label="Filtrar por tipo de solicitud"
            value={filtroSolicitud}
            onChange={(e) => { setFiltroSolicitud(e.target.value as typeof filtroSolicitud); setPagina(1); }}
            className="h-8 border border-border rounded px-2 text-[13px]"
          >
            <option value="">Todas</option>
            <option value="CFDI">CFDI</option>
            <option value="METADATA">Metadata</option>
          </select>
        </div>

        {esEscritorio && !esMovil && jobs.length > 0 && (
          <table>
            <caption className="sr-only">Jobs de descarga</caption>
            <thead>
              <tr className="bg-surface-alt">
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Job</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Tipo</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Periodo</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Estado</th>
                <th scope="col" className="text-right text-xs font-semibold px-3 py-2">Intentos</th>
                <th scope="col" className="text-right text-xs font-semibold px-3 py-2">Paquetes</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Actualizado</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr
                  key={j.job_id}
                  onClick={() => navigate(`/e/${empresa.empresa_id}/descargas/${j.job_id}`)}
                  tabIndex={0}
                  className="border-t border-border cursor-pointer h-10 hover:bg-primary-soft"
                  style={{ background: j.estado === 'ERROR' ? '#FCF6F7' : 'transparent' }}
                >
                  <td className="px-3 font-mono text-[13px]">#{j.job_id}</td>
                  <td className="px-3 text-[13px]">{j.tipo === 'recibido' ? 'Recibidos' : 'Emitidos'} · {j.solicitud}</td>
                  <td className="px-3 text-[13px] text-text-muted whitespace-nowrap">{j.desde} → {j.hasta}</td>
                  <td className="px-3"><EstadoChip estado={j.estado} /></td>
                  <td className="px-3 text-right font-mono text-[13px]">{j.intentos}</td>
                  <td className="px-3 text-right font-mono text-[13px]">{j.paquetes}</td>
                  <td className="px-3 text-xs text-text-muted whitespace-nowrap">{j.updated_at.slice(5, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {esMovil && jobs.length > 0 && (
          <div className="flex flex-col">
            {jobs.map((j) => (
              <button
                key={j.job_id}
                type="button"
                onClick={() => navigate(`/e/${empresa.empresa_id}/descargas/${j.job_id}`)}
                className="text-left border-0 border-t border-border px-4 py-3 flex flex-col gap-1.5 cursor-pointer w-full"
                style={{ background: j.estado === 'ERROR' ? '#FCF6F7' : 'transparent' }}
              >
                <span className="flex items-center gap-2 w-full">
                  <span className="font-mono text-[13px] font-semibold">#{j.job_id}</span>
                  <span className="flex-1" />
                  <EstadoChip estado={j.estado} />
                </span>
                <span className="text-xs text-text-muted">{j.tipo === 'recibido' ? 'Recibidos' : 'Emitidos'} · {j.solicitud}</span>
                <span className="font-mono text-xs text-text-muted">{j.desde} → {j.hasta}</span>
                <span className="text-xs text-text-muted">Intentos {j.intentos} · Paquetes {j.paquetes} · {j.updated_at.slice(5, 16)}</span>
              </button>
            ))}
          </div>
        )}

        {jobs.length === 0 && <div className="p-8 text-center text-text-muted text-[13px]">Aún no hay descargas para esta empresa.</div>}

        {jobsPage && (
          <Paginador
            page={pagina}
            perPage={jobsPage.per_page}
            total={jobsPage.total}
            onChange={setPagina}
            pageSize={porPagina}
            pageSizeOptions={[10, 25, 50, 100, 'todos']}
            onPageSizeChange={(v) => { setPorPagina(v); setPagina(1); }}
          />
        )}
      </div>

      {jobDrawer && (
        <JobDrawer
          job={jobDrawer}
          puedeMutar={puedeMutar}
          onClose={() => navigate(`/e/${empresa.empresa_id}/descargas`)}
          onReintentar={() => reintentar.mutate(jobDrawer.job_id)}
          reintentando={reintentar.isPending}
        />
      )}
    </div>
  );
}
