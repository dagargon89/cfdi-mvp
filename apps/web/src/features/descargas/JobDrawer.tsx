// demo.html:787-834 (drawer de job) + lógica demo.html:1241-1250,1398-1404.
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Drawer, DrawerHeader } from '@/components/ui/Drawer';
import { EstadoChip } from '@/components/ui/EstadoChip';
import type { Job } from '@/lib/api';

const ORDEN: Job['estado'][] = ['SOLICITADO', 'EN_PROCESO', 'TERMINADA', 'DESCARGADO'];

export function JobDrawer({ job, puedeMutar, onClose, onReintentar, reintentando }: {
  job: Job;
  puedeMutar: boolean;
  onClose: () => void;
  onReintentar: () => void;
  reintentando: boolean;
}) {
  const idx = ORDEN.indexOf(job.estado);
  const puedeReintentar = job.estado === 'ERROR' && puedeMutar;

  return (
    <Drawer label="Detalle del job" onClose={onClose}>
      <DrawerHeader title={<>Job <span className="font-mono">#{job.job_id}</span></>} onClose={onClose} />
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
        <div className="self-start"><EstadoChip estado={job.estado} /></div>

        <dl className="m-0 grid gap-3" style={{ gridTemplateColumns: '1fr 1fr' }}>
          <div><dt className="text-xs text-text-muted font-semibold">Tipo</dt><dd className="mt-0.5 mb-0 text-[13px]">{job.tipo === 'recibido' ? 'Recibidos' : 'Emitidos'} · {job.solicitud}</dd></div>
          <div><dt className="text-xs text-text-muted font-semibold">Origen</dt><dd className="mt-0.5 mb-0 text-[13px]">{job.origen}</dd></div>
          <div><dt className="text-xs text-text-muted font-semibold">Periodo</dt><dd className="mt-0.5 mb-0 font-mono text-[13px]">{job.desde} → {job.hasta}</dd></div>
          <div><dt className="text-xs text-text-muted font-semibold">Id de solicitud</dt><dd className="mt-0.5 mb-0 font-mono text-xs">{job.id_solicitud ?? '—'}</dd></div>
          <div><dt className="text-xs text-text-muted font-semibold">Intentos</dt><dd className="mt-0.5 mb-0 font-mono text-[13px]">{job.intentos}</dd></div>
          <div><dt className="text-xs text-text-muted font-semibold">Paquetes</dt><dd className="mt-0.5 mb-0 font-mono text-[13px]">{job.paquetes}</dd></div>
        </dl>

        <div className="flex flex-col gap-2">
          <span className="text-xs font-semibold text-text-muted">Máquina de estados</span>
          {ORDEN.map((nombre, i) => {
            const hecho = idx >= 0 && i <= idx;
            const errorAqui = job.estado === 'ERROR' && i === 0;
            return (
              <div key={nombre} className="flex items-center gap-2.5">
                <span className="size-2.5 rounded-full shrink-0" style={{ background: errorAqui ? 'var(--danger)' : hecho ? 'var(--success)' : 'var(--border)' }} />
                <span className={`font-mono text-xs ${i === idx ? 'font-semibold' : 'font-normal'} ${hecho || errorAqui ? 'text-text-strong' : 'text-text-muted'}`}>{nombre}</span>
                <span className="flex-1 h-px bg-surface-alt" />
                <span className="text-xs text-text-muted">{hecho ? job.updated_at.slice(5, 16) : '—'}</span>
              </div>
            );
          })}
        </div>

        {job.mensaje && <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2.5 text-[13px] text-pretty">{job.mensaje}</div>}
        <div className="text-xs text-text-muted">Última verificación: <span className="font-mono">{job.updated_at}</span></div>
      </div>
      {puedeReintentar && (
        <div className="border-t border-border p-4 flex gap-2">
          <Button onClick={onReintentar} loading={reintentando} disabled={reintentando}>
            <RefreshCw className="size-[15px]" aria-hidden /> Reintentar descarga
          </Button>
        </div>
      )}
    </Drawer>
  );
}
