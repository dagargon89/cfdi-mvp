// demo.html:505-607 (P7 Comprobantes) + lógica demo.html:1227-1237,1359-1370.
import { useQuery } from '@tanstack/react-query';
import { FileSpreadsheet } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'react-router';
import { Button } from '@/components/ui/Button';
import { EstadoChip } from '@/components/ui/EstadoChip';
import { useToast } from '@/components/ui/ToastProvider';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import { useBreakpoint } from '@/hooks/useBreakpoint';
import { api } from '@/lib/client';
import type { Comprobante, EstatusCfdi } from '@/lib/api';
import { money } from '@/lib/domain';
import { ComprobanteDrawer } from './ComprobanteDrawer';

export function ComprobantesPage() {
  const { empresa } = useEmpresaCtx();
  const { esMovil, esEscritorio } = useBreakpoint();
  const { toast } = useToast();
  const [params] = useSearchParams();

  const [q, setQ] = useState(params.get('q') ?? '');
  const [estatus, setEstatus] = useState<EstatusCfdi | ''>('');
  const [tipo, setTipo] = useState('');
  const [desde, setDesde] = useState('');
  const [abierto, setAbierto] = useState<Comprobante | null>(null);
  const [exportando, setExportando] = useState(false);

  const filtros = { q: q || undefined, estatus: estatus || undefined, tipo_comprobante: tipo || undefined, desde: desde || undefined };
  const { data: page } = useQuery({ queryKey: ['comprobantes', empresa.empresa_id, filtros], queryFn: () => api.listarComprobantes(empresa.empresa_id, filtros) });
  const { data: totalEmpresa } = useQuery({ queryKey: ['comprobantes', empresa.empresa_id], queryFn: () => api.listarComprobantes(empresa.empresa_id) });
  const { data: efosPage } = useQuery({ queryKey: ['eventos', empresa.empresa_id, 'efos'], queryFn: () => api.listarEventos(empresa.empresa_id, { tipo: 'efos' }) });

  const comprobantes = page?.data ?? [];
  const efosUuids = new Set((efosPage?.data ?? []).flatMap((e) => (e.detalle.uuids as string[]) ?? []));
  const totalSuma = comprobantes.reduce((a, c) => a + (c.total ?? 0), 0);
  const resumen = `${comprobantes.length} de ${totalEmpresa?.total ?? 0} · total ${money(totalSuma)}`;

  function limpiar() {
    setQ(''); setEstatus(''); setTipo(''); setDesde('');
  }

  async function exportar() {
    setExportando(true);
    toast('Generando exportación…', 'info');
    try {
      const { tarea_id } = await api.exportarExcel(empresa.empresa_id, filtros as Record<string, string>);
      let estado = 'pendiente';
      let url: string | undefined;
      while (estado === 'pendiente') {
        await new Promise((r) => setTimeout(r, 300));
        const t = await api.estadoTarea(tarea_id);
        estado = t.estado;
        url = t.descarga_url;
      }
      toast(`${url?.split('/').pop() ?? 'archivo'} descargado`, 'ok');
    } finally {
      setExportando(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="bg-surface border border-border rounded-lg px-4 py-3 flex gap-3 flex-wrap items-end">
        <div className="flex flex-col gap-1.5 flex-1 min-w-[200px]">
          <label htmlFor="f-q" className="text-xs font-semibold text-text-muted">Buscar</label>
          <input id="f-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="UUID, RFC, razón social o folio" className="h-[34px] border border-border rounded px-2.5" />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="f-est" className="text-xs font-semibold text-text-muted">Estatus</label>
          <select id="f-est" value={estatus} onChange={(e) => setEstatus(e.target.value as EstatusCfdi | '')} className="h-[34px] border border-border rounded px-2">
            <option value="">Todos</option>
            <option value="vigente">Vigente</option>
            <option value="cancelado">Cancelado</option>
            <option value="no_verificado">No verificado</option>
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="f-tipo" className="text-xs font-semibold text-text-muted">Tipo</label>
          <select id="f-tipo" value={tipo} onChange={(e) => setTipo(e.target.value)} className="h-[34px] border border-border rounded px-2">
            <option value="">Todos</option>
            <option value="I">Ingreso</option>
            <option value="E">Egreso</option>
            <option value="P">Pago</option>
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="f-desde" className="text-xs font-semibold text-text-muted">Emitido desde</label>
          <input id="f-desde" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} className="h-[34px] border border-border rounded px-2" />
        </div>
        <Button variant="secondary" onClick={limpiar}>Limpiar</Button>
        <Button onClick={exportar} loading={exportando} disabled={exportando}>
          <FileSpreadsheet className="size-[15px]" aria-hidden /> Exportar
        </Button>
      </div>

      <div className="bg-surface border border-border rounded-lg overflow-hidden">
        <div className="flex items-center px-4 py-3 border-b border-border gap-2">
          <h3 className="m-0 text-[15px] font-semibold flex-1">Comprobantes</h3>
          <span className="text-xs text-text-muted">{resumen}</span>
        </div>

        {esEscritorio && !esMovil && comprobantes.length > 0 && (
          <div className="overflow-x-auto">
            <table>
              <caption className="sr-only">Comprobantes recibidos y emitidos</caption>
              <thead>
                <tr className="bg-surface-alt">
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">UUID</th>
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Emisor</th>
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">RFC</th>
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Folio</th>
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Emisión</th>
                  <th scope="col" className="text-right text-xs font-semibold px-3 py-2">Total</th>
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Estatus</th>
                </tr>
              </thead>
              <tbody>
                {comprobantes.map((c) => (
                  <tr
                    key={c.comprobante_id}
                    onClick={() => setAbierto(c)}
                    className="border-t border-border cursor-pointer h-10 hover:bg-primary-soft"
                    style={{ background: c.estatus === 'cancelado' ? '#FCF6F7' : 'transparent' }}
                  >
                    <td className="px-3 font-mono text-xs whitespace-nowrap">{c.uuid.slice(0, 13)}…</td>
                    <td className="px-3 text-[13px] max-w-[220px] overflow-hidden text-ellipsis whitespace-nowrap">{c.razon_social_emisor}</td>
                    <td className="px-3 font-mono text-xs">{c.rfc_emisor}</td>
                    <td className="px-3 font-mono text-xs">{c.folio ?? '—'}</td>
                    <td className="px-3 text-[13px] text-text-muted whitespace-nowrap">{c.fecha_emision?.slice(0, 10)}</td>
                    <td className="px-3 text-right font-mono text-[13px] font-medium">{money(c.total ?? 0)}</td>
                    <td className="px-3"><EstadoChip estado={c.estatus} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {esMovil && comprobantes.length > 0 && (
          <div className="flex flex-col">
            {comprobantes.map((c) => (
              <button
                key={c.comprobante_id}
                type="button"
                onClick={() => setAbierto(c)}
                className="text-left border-0 border-t border-border px-4 py-3 flex flex-col gap-1.5 w-full cursor-pointer"
                style={{ background: c.estatus === 'cancelado' ? '#FCF6F7' : 'transparent' }}
              >
                <span className="flex items-center gap-2 w-full">
                  <span className="text-[13px] font-semibold flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">{c.razon_social_emisor}</span>
                  <EstadoChip estado={c.estatus} />
                </span>
                <span className="font-mono text-xs text-text-muted">{c.rfc_emisor} · {c.uuid.slice(0, 13)}…</span>
                <span className="flex items-baseline gap-2 w-full">
                  <span className="text-xs text-text-muted">{c.fecha_emision?.slice(0, 10)} · folio {c.folio ?? '—'}</span>
                  <span className="flex-1" />
                  <span className="font-mono text-sm font-semibold">{money(c.total ?? 0)}</span>
                </span>
              </button>
            ))}
          </div>
        )}

        {comprobantes.length === 0 && (
          <div className="py-10 px-6 text-center flex flex-col items-center gap-2.5">
            <span className="text-[13px] text-text-muted">Sin resultados con estos filtros.</span>
            <Button variant="secondary" onClick={limpiar}>Limpiar los filtros</Button>
          </div>
        )}
      </div>

      {abierto && <ComprobanteDrawer comprobante={abierto} esEfos={efosUuids.has(abierto.uuid)} onClose={() => setAbierto(null)} />}
    </div>
  );
}
