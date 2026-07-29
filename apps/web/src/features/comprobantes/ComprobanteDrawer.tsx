// demo.html:836-867 (drawer de comprobante) + lógica demo.html:1251-1252.
// Descargar PDF/Detalle/Zip añadido tras el freeze (2026-07-28, RF-RES-03/D2) — a diferencia
// del XML (ya una URL firmada), estos se generan al vuelo detrás de auth normal, así que se
// piden como Blob y se disparan como descarga (ver lib/descargarBlob.ts).
// Cada botón (salvo el .zip) es un "split": la parte grande descarga y la pestaña del ojo
// previsualiza el documento en una pestaña nueva sin descargarlo.
import { Eye, Loader2 } from 'lucide-react';
import { useState, type ReactNode } from 'react';
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

const MAIN =
  'inline-flex items-center gap-2 h-9 px-3.5 text-sm font-semibold text-text-strong ' +
  'hover:bg-surface-alt disabled:opacity-50 disabled:pointer-events-none';

/** Botón dividido: acción principal (descargar) + pestaña opcional con ojo (previsualizar). */
function SplitDescarga({ main, onPreview, previewLoading, disabled }: {
  main: ReactNode;
  onPreview?: () => void;
  previewLoading?: boolean;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex rounded-md border border-border overflow-hidden bg-surface">
      {main}
      {onPreview && (
        <button
          type="button"
          onClick={onPreview}
          disabled={disabled}
          title="Previsualizar"
          aria-label="Previsualizar documento"
          className="inline-flex items-center justify-center h-9 px-2.5 border-l border-border text-text-strong hover:bg-surface-alt disabled:opacity-50 disabled:pointer-events-none"
        >
          {previewLoading ? <Loader2 className="size-[15px] animate-spin" aria-hidden /> : <Eye className="size-[15px]" aria-hidden />}
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

  async function pedirBlob(tipo: Previsualizable) {
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
      <div className="border-t border-border p-4 flex gap-2 flex-wrap">
        {comprobante.xml_path ? (
          <SplitDescarga
            onPreview={() => {
              const url = comprobante.xml_path!;
              window.open(`${url}${url.includes('?') ? '&' : '?'}inline=1`, '_blank', 'noreferrer');
            }}
            main={
              <a href={comprobante.xml_path} target="_blank" rel="noreferrer" className={MAIN}>
                Descargar XML
              </a>
            }
          />
        ) : (
          <SplitDescarga main={<span className={`${MAIN} opacity-50 pointer-events-none`}>Descargar XML</span>} />
        )}

        <SplitDescarga
          disabled={ocupado}
          previewLoading={previsualizando === 'pdf'}
          onPreview={() => previsualizar('pdf')}
          main={
            <button type="button" onClick={() => descargar('pdf')} disabled={ocupado} className={MAIN}>
              {descargando === 'pdf' && <Loader2 className="size-4 animate-spin" aria-hidden />} Descargar PDF
            </button>
          }
        />

        <SplitDescarga
          disabled={ocupado}
          previewLoading={previsualizando === 'detalle'}
          onPreview={() => previsualizar('detalle')}
          main={
            <button type="button" onClick={() => descargar('detalle')} disabled={ocupado} className={MAIN}>
              {descargando === 'detalle' && <Loader2 className="size-4 animate-spin" aria-hidden />} Descargar Detalle
            </button>
          }
        />

        <SplitDescarga
          main={
            <button type="button" onClick={() => descargar('zip')} disabled={ocupado} className={MAIN}>
              {descargando === 'zip' && <Loader2 className="size-4 animate-spin" aria-hidden />} Descargar todo (.zip)
            </button>
          }
        />
      </div>
    </Drawer>
  );
}
