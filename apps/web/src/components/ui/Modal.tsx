// demo.html:869-882 (modal "Eliminar e.firma") generalizado a modal de confirmación reusable.
import type { ReactNode } from 'react';
import { useFocusTrap } from './useFocusTrap';

export function Modal({ titleId, onClose, children }: { titleId: string; onClose: () => void; children: ReactNode }) {
  const ref = useFocusTrap(true, onClose);
  return (
    <div className="fixed inset-0 z-[70] grid place-items-center p-6">
      <div onClick={onClose} className="absolute inset-0 bg-[rgba(30,39,51,.35)] animate-dc-fade" />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative w-full max-w-[440px] bg-surface rounded-lg shadow-lg p-5 flex flex-col gap-3.5 animate-dc-up"
      >
        {children}
      </div>
    </div>
  );
}
