// demo.html:836-867 (drawer de comprobante) + lógica demo.html:1251-1252.
// Descargar PDF/Detalle/Zip añadido tras el freeze (2026-07-28, RF-RES-03/D2) — a diferencia
// del XML (ya una URL firmada), estos se generan al vuelo detrás de auth normal, así que se
// piden como Blob y se disparan como descarga (ver lib/descargarBlob.ts).
import { useState } from 'react';
import { Drawer, DrawerHeader } from '@/components/ui/Drawer';
import { EstadoChip } from '@/components/ui/EstadoChip';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/ToastProvider';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import type { Comprobante } from '@/lib/api';
import { api } from '@/lib/client';
import { descargarBlob } from '@/lib/descargarBlob';
import { money } from '@/lib/domain';

type Descarga = 'pdf' | 'detalle' | 'zip';

export function ComprobanteDrawer({ comprobante, esEfos, onClose }: { comprobante: Comprobante; esEfos: boolean; onClose: () => void }) {
  const { empresa } = useEmpresaCtx();
  const { toast } = useToast();
  const [cargando, setCargando] = useState<Descarga | null>(null);

  async function descargar(tipo: Descarga) {
    setCargando(tipo);
    try {
      const { blob, nombre } =
        tipo === 'pdf'
          ? { blob: await api.descargarComprobantePdf(empresa.empresa_id, comprobante.comprobante_id), nombre: `${comprobante.uuid}.pdf` }
          : tipo === 'detalle'
            ? { blob: await api.descargarComprobanteDetalle(empresa.empresa_id, comprobante.comprobante_id), nombre: `${comprobante.uuid}_detalle.pdf` }
            : { blob: await api.descargarComprobanteZip(empresa.empresa_id, comprobante.comprobante_id), nombre: `${comprobante.uuid}.zip` };
      descargarBlob(blob, nombre);
    } catch {
      toast('No se pudo descargar el archivo', 'error');
    } finally {
      setCargando(null);
    }
  }

  return (
    <Drawer label="Detalle del comprobante" onClose={onClose}>
      <DrawerHeader title="Comprobante" onClose={onClose} />
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3.5">
        <div className="self-start"><EstadoChip estado={comprobante.estatus} /></div>

        {esEfos && (
          <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2.5 text-[13px] text-pretty">
            Emisor en lista 69-B con situación definitivo. Revisa la deducibilidad de este comprobante.
          </div>
        )}

        <dl className="m-0 flex flex-col gap-3">
          <div><dt className="text-xs text-text-muted font-semibold">UUID</dt><dd className="mt-0.5 mb-0 font-mono text-xs break-all">{comprobante.uuid}</dd></div>
          <div><dt className="text-xs text-text-muted font-semibold">Emisor</dt><dd className="mt-0.5 mb-0 text-[13px]">{comprobante.razon_social_emisor} · <span className="font-mono">{comprobante.rfc_emisor}</span></dd></div>
          <div><dt className="text-xs text-text-muted font-semibold">Receptor</dt><dd className="mt-0.5 mb-0 font-mono text-[13px]">{comprobante.rfc_receptor}</dd></div>
          <div><dt className="text-xs text-text-muted font-semibold">Total</dt><dd className="mt-0.5 mb-0 font-mono text-base font-semibold">{money(comprobante.total ?? 0)}</dd></div>
          <div><dt className="text-xs text-text-muted font-semibold">Archivo XML</dt><dd className="mt-0.5 mb-0 text-[13px]">{comprobante.xml_path ? 'Disponible' : 'No disponible'}</dd></div>
          <div><dt className="text-xs text-text-muted font-semibold">Estatus verificado</dt><dd className="mt-0.5 mb-0 font-mono text-xs">{comprobante.estatus_verificado_at ?? '—'}</dd></div>
        </dl>
      </div>
      <div className="border-t border-border p-4 flex gap-2 flex-wrap">
        {comprobante.xml_path ? (
          <a
            href={comprobante.xml_path}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-md px-4 h-9 text-sm font-semibold border border-border bg-surface text-text-strong hover:bg-surface-alt"
          >
            Descargar XML
          </a>
        ) : (
          <Button variant="secondary" disabled>Descargar XML</Button>
        )}
        <Button variant="secondary" onClick={() => descargar('pdf')} loading={cargando === 'pdf'} disabled={cargando !== null}>
          Descargar PDF
        </Button>
        <Button variant="secondary" onClick={() => descargar('detalle')} loading={cargando === 'detalle'} disabled={cargando !== null}>
          Descargar Detalle
        </Button>
        <Button variant="secondary" onClick={() => descargar('zip')} loading={cargando === 'zip'} disabled={cargando !== null}>
          Descargar todo (.zip)
        </Button>
      </div>
    </Drawer>
  );
}
