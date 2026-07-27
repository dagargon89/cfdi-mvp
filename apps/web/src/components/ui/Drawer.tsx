// demo.html:787-867 (drawer de job / comprobante) generalizado a shell reusable.
import type { ReactNode } from 'react';
import { X } from 'lucide-react';
import { useFocusTrap } from './useFocusTrap';

export function Drawer({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  const ref = useFocusTrap(true, onClose);
  return (
    <div className="fixed inset-0 z-[60] flex justify-end">
      <div onClick={onClose} className="absolute inset-0 bg-[rgba(30,39,51,.28)] animate-dc-fade" />
      <aside
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="relative w-[min(460px,92vw)] h-full bg-surface border-l border-border shadow-[-8px_0_24px_rgba(30,39,51,.12)] flex flex-col animate-dc-slide"
      >
        {children}
      </aside>
    </div>
  );
}

export function DrawerHeader({ title, onClose }: { title: ReactNode; onClose: () => void }) {
  return (
    <div className="flex items-center gap-2.5 p-4 border-b border-border">
      <h2 className="m-0 text-base font-semibold flex-1">{title}</h2>
      <button
        type="button"
        onClick={onClose}
        aria-label="Cerrar"
        className="size-7.5 border-0 bg-transparent rounded-md cursor-pointer text-text-muted grid place-items-center hover:bg-surface-alt"
      >
        <X className="size-4.5" aria-hidden />
      </button>
    </div>
  );
}
