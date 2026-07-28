// Hub_CFDI_docs/01-vision/08_identidad_visual_design_system.md §"anatomía de tabla" — el
// paginador es parte de la secuencia de teclado estándar (tabla → paginador → drawer).
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from './Button';

export function Paginador({ page, perPage, total, onChange }: { page: number; perPage: number; total: number; onChange: (page: number) => void }) {
  const totalPaginas = Math.max(1, Math.ceil(total / perPage));
  if (totalPaginas <= 1) return null;

  return (
    <nav aria-label="Paginación" className="flex items-center justify-between gap-3 px-4 py-3 border-t border-border">
      <span className="text-xs text-text-muted">
        Página {page} de {totalPaginas} · {total} en total
      </span>
      <div className="flex items-center gap-1.5">
        <Button variant="secondary" onClick={() => onChange(page - 1)} disabled={page <= 1} aria-label="Página anterior">
          <ChevronLeft className="size-[15px]" aria-hidden />
        </Button>
        <Button variant="secondary" onClick={() => onChange(page + 1)} disabled={page >= totalPaginas} aria-label="Página siguiente">
          <ChevronRight className="size-[15px]" aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
