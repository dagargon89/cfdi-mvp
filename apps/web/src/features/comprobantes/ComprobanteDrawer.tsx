// demo.html:836-867 (drawer de comprobante) + lógica demo.html:1251-1252.
// Descargar PDF/Detalle/Zip añadido tras el freeze (2026-07-28, RF-RES-03/D2) — a diferencia
// del XML (ya una URL firmada), estos se generan al vuelo detrás de auth normal, así que se
// piden como Blob y se disparan como descarga (ver lib/descargarBlob.ts).
// Cada documento es un "split" con color/ícono propios: la parte grande descarga y la pestaña
// del ojo previsualiza en una pestaña nueva (el .zip no se previsualiza).
import { Archive, Eye, FileCheck2, FileCode2, FileText, Loader2, type LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { Drawer, DrawerHeader } from '@/components/ui/Drawer';
import { EstadoChip } from '@/components/ui/EstadoChip';
import { useToast } from '@/components/ui/ToastProvider';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import type { Comprobante } from '@/lib/api';
import { api } from '@/lib/client';
import { descargarBlob } from '@/lib/descargarBlob';
import { money } from '@/lib/domain';

type Doc = 'pdf' | 'detalle' | 'zip';
type Previsualizable = 'pdf' | 'detalle';
type Tono = 'info' | 'primary' | 'success' | 'warning';

const TONO: Record<Tono, { wrap: string; main: string }> = {
  info: { wrap: 'border-info/30', main: 'text-info bg-info-soft hover:bg-info/15' },
  primary: { wrap: 'border-primary/30', main: 'text-primary bg-primary-soft hover:bg-primary/15' },
  success: { wrap: 'border-success/30', main: 'text-success bg-success-soft hover:bg-success/15' },
  warning: { wrap: 'border-warning/40', main: 'text-warning bg-warning-soft hover:bg-warning/15' },
};

function SplitDescarga({ tono, Icon, label, href, onDescargar, onPreview, descargando, previsualizando, disabled }: {
  tono: Tono;
  Icon: LucideIcon;
  label: string;
  href?: string;
  onDescargar?: () => void;
  onPreview?: () => void;
  descargando?: boolean;
  previsualizando?: boolean;
  disabled?: boolean;
}) {
  const t = TONO[tono];
  const mainCls = `flex-1 inline-flex items-center justify-center gap-2 h-9 px-3 text-[13px] font-semibold ${t.main} disabled:opacity-50 disabled:pointer-events-none`;
  return (
    <div className={`flex w-full rounded-md border ${t.wrap} overflow-hidden`}>
      {href ? (
        <a href={href} target="_blank" rel="noreferrer" className={mainCls}>
          <Icon className="size-4 shrink-0" aria-hidden /> {label}
        </a>
      ) : (
        <button type="button" onClick={onDescargar} disabled={disabled || !onDescargar} className={mainCls}>
          {descargando ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Icon className="size-4 shrink-0" aria-hidden />} {label}
        </button>
      )}
      {onPreview && (
        <button
          type="button"
          onClick={onPreview}
          disabled={disabled}
          title="Previsualizar"
          aria-label={`Previsualizar ${label}`}
          className={`inline-flex items-center justify-center h-9 px-2.5 border-l ${t.wrap} ${t.main} disabled:opacity-50 disabled:pointer-events-none`}
        >
          {previsualizando ? <Loader2 className="size-[15px] animate-spin" aria-hidden /> : <Eye className="size-[15px]" aria-hidden />}
        </button>
      )}
    </div>
  );
}

export function ComprobanteDrawer({ comprobante, esEfos, onClose }: { comprobante: Comprobante; esEfos: boolean; onClose: () => void }) {
  const { empresa } = useEmpresaCtx();
  const { toast } = useToast();
  const [descargando, setDescargando] = useState<Doc | null>(null);
  const [previsualizando, setPrevisualizando] = useState<Previsualizable | null>(null);
  const ocupado = descargando !== null || previsualizando !== null;

  function pedirBlob(tipo: Previsualizable) {
    return tipo === 'pdf'
      ? api.descargarComprobantePdf(empresa.empresa_id, comprobante.comprobante_id)
      : api.descargarComprobanteDetalle(empresa.empresa_id, comprobante.comprobante_id);
  }

  async function descargar(tipo: Doc) {
    setDescargando(tipo);
    try {
      const { blob, nombre } =
        tipo === 'pdf'
          ? { blob: await pedirBlob('pdf'), nombre: `${comprobante.uuid}.pdf` }
          : tipo === 'detalle'
            ? { blob: await pedirBlob('detalle'), nombre: `${comprobante.uuid}_detalle.pdf` }
            : { blob: await api.descargarComprobanteZip(empresa.empresa_id, comprobante.comprobante_id), nombre: `${comprobante.uuid}.zip` };
      descargarBlob(blob, nombre);
    } catch {
      toast('No se pudo descargar el archivo', 'error');
    } finally {
      setDescargando(null);
    }
  }

  async function previsualizar(tipo: Previsualizable) {
    setPrevisualizando(tipo);
    // Abrir la pestaña ANTES del await evita que el bloqueador de popups la corte tras la petición.
    const ventana = window.open('', '_blank');
    try {
      const blob = await pedirBlob(tipo);
      const url = URL.createObjectURL(blob);
      if (ventana) ventana.location.href = url;
      else window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60_000); // liberar tras dar tiempo a que la pestaña cargue
    } catch {
      ventana?.close();
      toast('No se pudo previsualizar el documento', 'error');
    } finally {
      setPrevisualizando(null);
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
      <div className="border-t border-border p-4 flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-text-muted">Descargar documentos</span>
          <span className="text-[11px] text-text-muted inline-flex items-center gap-1">
            <Eye className="size-3.5" aria-hidden /> previsualizar
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <SplitDescarga
            tono="info"
            Icon={FileCode2}
            label="XML"
            href={comprobante.xml_path ?? undefined}
            onPreview={
              comprobante.xml_path
                ? () => {
                    const u = comprobante.xml_path!;
                    window.open(`${u}${u.includes('?') ? '&' : '?'}inline=1`, '_blank', 'noreferrer');
                  }
                : undefined
            }
          />
          <SplitDescarga
            tono="primary"
            Icon={FileText}
            label="PDF"
            onDescargar={() => descargar('pdf')}
            descargando={descargando === 'pdf'}
            onPreview={() => previsualizar('pdf')}
            previsualizando={previsualizando === 'pdf'}
            disabled={ocupado}
          />
          <SplitDescarga
            tono="success"
            Icon={FileCheck2}
            label="Detalle"
            onDescargar={() => descargar('detalle')}
            descargando={descargando === 'detalle'}
            onPreview={() => previsualizar('detalle')}
            previsualizando={previsualizando === 'detalle'}
            disabled={ocupado}
          />
          <SplitDescarga
            tono="warning"
            Icon={Archive}
            label="Todo (.zip)"
            onDescargar={() => descargar('zip')}
            descargando={descargando === 'zip'}
            disabled={ocupado}
          />
        </div>
      </div>
    </Drawer>
  );
}
