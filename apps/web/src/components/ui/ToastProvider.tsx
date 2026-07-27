// Puerta de toasts — demo.html:884-893,1060-1068 (stack inferior derecho, éxito/info auto-descartan
// a los 4s, error persiste hasta que el usuario lo cierra).
import { AlertCircle, CheckCircle2, RefreshCw, X } from 'lucide-react';
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

type Tipo = 'ok' | 'info' | 'error';
interface ToastItem { id: string; texto: string; tipo: Tipo }

const TIPO_ESTILO: Record<Tipo, { fg: string; Icon: typeof CheckCircle2; anim: string }> = {
  ok: { fg: 'text-success', Icon: CheckCircle2, anim: '' },
  info: { fg: 'text-info', Icon: RefreshCw, anim: 'animate-spin' },
  error: { fg: 'text-danger', Icon: AlertCircle, anim: '' },
};

interface ToastApi {
  toast: (texto: string, tipo?: Tipo) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const cerrar = useCallback((id: string) => setItems((s) => s.filter((t) => t.id !== id)), []);

  const toast = useCallback(
    (texto: string, tipo: Tipo = 'ok') => {
      const id = String(counter.current++);
      setItems((s) => [...s, { id, texto, tipo }]);
      if (tipo !== 'error') setTimeout(() => cerrar(id), 4000);
    },
    [cerrar],
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div aria-live="polite" className="fixed right-5 bottom-5 z-[80] flex flex-col gap-2 items-end">
        {items.map((t) => {
          const { fg, Icon, anim } = TIPO_ESTILO[t.tipo];
          return (
            <div
              key={t.id}
              role="status"
              className="flex items-center gap-2.5 bg-surface border border-border rounded-lg shadow-md px-3.5 py-2.5 min-w-[260px] animate-dc-up"
              style={{ borderLeftWidth: 3, borderLeftColor: `var(--${t.tipo === 'ok' ? 'success' : t.tipo === 'info' ? 'info' : 'danger'})` }}
            >
              <Icon className={`size-4 shrink-0 ${fg} ${anim}`} aria-hidden />
              <span className="flex-1 text-sm text-pretty">{t.texto}</span>
              <button
                type="button"
                onClick={() => cerrar(t.id)}
                aria-label="Descartar"
                className="border-0 bg-transparent cursor-pointer text-text-muted size-5.5 grid place-items-center rounded hover:bg-surface-alt"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast debe usarse dentro de <ToastProvider>');
  return ctx;
}
