// Hub_CFDI_docs/01-vision/08_identidad_visual_design_system.md §"anatomía de tabla" — el
// paginador es parte de la secuencia de teclado estándar (tabla → paginador → drawer).
// Opcionalmente muestra un selector de "cuántos ver por página" (incluida la opción "Todos").
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from './Button';

export type TamañoPagina = number | 'todos';

export function Paginador({
  page,
  perPage,
  total,
  onChange,
  pageSize,
  pageSizeOptions,
  onPageSizeChange,
}: {
  page: number;
  perPage: number;
  total: number;
  onChange: (page: number) => void;
  pageSize?: TamañoPagina;
  pageSizeOptions?: TamañoPagina[];
  onPageSizeChange?: (v: TamañoPagina) => void;
}) {
  const conSelector = !!(pageSizeOptions && onPageSizeChange);
  const totalPaginas = pageSize === 'todos' ? 1 : Math.max(1, Math.ceil(total / perPage));
  // Sin selector, el paginador clásico se oculta cuando sobra (una sola página). Con selector,
  // siempre se muestra para poder cambiar el tamaño aunque haya una sola página.
  if (totalPaginas <= 1 && !conSelector) return null;

  return (
    <nav aria-label="Paginación" className="flex items-center justify-between gap-3 px-4 py-3 border-t border-border">
      <div className="flex items-center gap-3">
        {conSelector && (
          <label className="flex items-center gap-1.5 text-xs text-text-muted">
            Mostrar
            <select
              value={String(pageSize)}
              onChange={(e) => onPageSizeChange!(e.target.value === 'todos' ? 'todos' : Number(e.target.value))}
              className="h-8 border border-border rounded-md bg-surface px-1.5 text-[13px] text-text-strong"
              aria-label="Filas por página"
            >
              {pageSizeOptions!.map((opt) => (
                <option key={String(opt)} value={String(opt)}>
                  {opt === 'todos' ? 'Todos' : opt}
                </option>
              ))}
            </select>
          </label>
        )}
        <span className="text-xs text-text-muted">
          {totalPaginas > 1 ? `Página ${page} de ${totalPaginas} · ` : ''}
          {total} en total
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <Button variant="secondary" onClick={() => onChange(page - 1)} disabled={page <= 1 || pageSize === 'todos'} aria-label="Página anterior">
          <ChevronLeft className="size-[15px]" aria-hidden />
        </Button>
        <Button variant="secondary" onClick={() => onChange(page + 1)} disabled={page >= totalPaginas || pageSize === 'todos'} aria-label="Página siguiente">
          <ChevronRight className="size-[15px]" aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
