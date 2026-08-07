// Doc 08: el color comunica estado pero **nunca es el único indicador** — siempre chip con texto e
// ícono. Lo usan las dos secciones de la pestaña Fiscal, con textos distintos según lo que se está
// confirmando (un importe o un juego de marcas), pero con los mismos tres estados y los mismos
// colores: quien aprendió que ámbar+⚠ = "no calcula" en la primera sección no lo tiene que volver
// a aprender en la segunda.
import { AlertCircle, AlertTriangle, CheckCircle2 } from 'lucide-react';
import type { EstadoFiscal } from './fiscalComun';

const ESTILO: Record<EstadoFiscal, { fg: string; bg: string; Icon: typeof CheckCircle2 }> = {
  confirmado: { fg: 'text-success', bg: 'bg-success-soft', Icon: CheckCircle2 },
  propuesto: { fg: 'text-warning', bg: 'bg-warning-soft', Icon: AlertTriangle },
  ausente: { fg: 'text-danger', bg: 'bg-danger-soft', Icon: AlertCircle },
};

export function ChipEstadoFiscal({ estado, texto }: { estado: EstadoFiscal; texto: string }) {
  const { fg, bg, Icon } = ESTILO[estado];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${fg} ${bg}`}>
      <Icon className="size-3.5" aria-hidden /> {texto}
    </span>
  );
}
