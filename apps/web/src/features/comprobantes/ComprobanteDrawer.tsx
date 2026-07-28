// demo.html:836-867 (drawer de comprobante) + lógica demo.html:1251-1252.
import { Drawer, DrawerHeader } from '@/components/ui/Drawer';
import { EstadoChip } from '@/components/ui/EstadoChip';
import { Button } from '@/components/ui/Button';
import type { Comprobante } from '@/lib/api';
import { money } from '@/lib/domain';

export function ComprobanteDrawer({ comprobante, esEfos, onClose }: { comprobante: Comprobante; esEfos: boolean; onClose: () => void }) {
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
      <div className="border-t border-border p-4 flex gap-2">
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
      </div>
    </Drawer>
  );
}
