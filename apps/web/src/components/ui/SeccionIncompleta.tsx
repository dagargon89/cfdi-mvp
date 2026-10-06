// Leyenda roja para secciones que todavía no están listas. El contenido vive en
// `lib/seccionesIncompletas.ts`; si la sección no está registrada, no se pinta nada.
import { OctagonAlert } from 'lucide-react';
import { seccionIncompleta } from '@/lib/seccionesIncompletas';

export function SeccionIncompleta({ id }: { id: string }) {
  const seccion = seccionIncompleta(id);
  if (!seccion) return null;

  return (
    <div role="note" aria-label={`Sección incompleta: ${seccion.titulo}`} className="flex gap-3 rounded-md border border-danger bg-danger-soft px-3.5 py-3 text-danger">
      <OctagonAlert className="size-[18px] shrink-0 mt-px" aria-hidden />
      <div className="flex flex-col gap-1 min-w-0">
        <span className="text-[11px] font-bold uppercase tracking-wide">No está completo aún</span>
        <span className="text-[13px] font-semibold text-pretty">{seccion.titulo}</span>
        <span className="text-[13px] text-pretty">{seccion.motivo}</span>
        <span className="text-[13px] text-pretty">
          <strong className="font-semibold">Qué falta:</strong> {seccion.falta}
        </span>
      </div>
    </div>
  );
}

/** Marca compacta para listas (p. ej. el catálogo de informes): solo avisa; el detalle va en la leyenda. */
export function MarcaIncompleta({ id }: { id: string }) {
  if (!seccionIncompleta(id)) return null;
  return (
    <span className="inline-flex items-center gap-1 self-start rounded border border-danger bg-danger-soft px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-danger">
      <OctagonAlert className="size-3" aria-hidden /> Incompleto
    </span>
  );
}
