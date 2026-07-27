// Hub_CFDI_docs/01-vision/08_identidad_visual_design_system.md §5.2, extendido con `no_verificado`
// (el único estado que usa el mock — demo.html:933-943 — y que doc 08 no listaba explícitamente).
import {
  AlertCircle,
  CheckCircle2,
  CirclePlus,
  Clock,
  PackageCheck,
  RefreshCw,
  Send,
  ShieldCheck,
  ShieldX,
  type LucideIcon,
} from 'lucide-react';
import type { EstadoJob, EstatusCfdi } from '@/lib/api';

const ESTADOS = {
  DESCARGADO: { fg: 'text-success', bg: 'bg-success-soft', Icon: CheckCircle2, anim: '' },
  EN_PROCESO: { fg: 'text-info', bg: 'bg-info-soft', Icon: RefreshCw, anim: 'animate-spin' },
  SOLICITADO: { fg: 'text-info', bg: 'bg-info-soft', Icon: Send, anim: '' },
  TERMINADA: { fg: 'text-warning', bg: 'bg-warning-soft', Icon: PackageCheck, anim: '' },
  ERROR: { fg: 'text-danger', bg: 'bg-danger-soft', Icon: AlertCircle, anim: '' },
  NUEVO: { fg: 'text-neutral', bg: 'bg-neutral-soft', Icon: CirclePlus, anim: '' },
  vigente: { fg: 'text-success', bg: 'bg-success-soft', Icon: ShieldCheck, anim: '' },
  cancelado: { fg: 'text-danger', bg: 'bg-danger-soft', Icon: ShieldX, anim: '' },
  no_verificado: { fg: 'text-neutral', bg: 'bg-neutral-soft', Icon: Clock, anim: '' },
} satisfies Record<EstadoJob | EstatusCfdi, { fg: string; bg: string; Icon: LucideIcon; anim: string }>;

export function EstadoChip({ estado }: { estado: EstadoJob | EstatusCfdi }) {
  const { fg, bg, Icon, anim } = ESTADOS[estado];
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${fg} ${bg}`}>
      <Icon className={`size-3.5 ${anim}`} aria-hidden /> {estado}
    </span>
  );
}
