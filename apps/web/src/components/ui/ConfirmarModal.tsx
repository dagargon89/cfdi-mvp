// Modal de confirmación simple (sí/no) sobre el Modal base — para acciones que necesitan un
// "¿estás seguro?" con una advertencia, sin teclear nada (a diferencia de ConfirmarRfcModal).
import { AlertTriangle } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from './Button';
import { Modal } from './Modal';

export function ConfirmarModal({ titulo, mensaje, textoConfirmar = 'Confirmar', tono = 'danger', onCancelar, onConfirmar }: {
  titulo: string;
  mensaje: ReactNode;
  textoConfirmar?: string;
  tono?: 'danger' | 'primary';
  onCancelar: () => void;
  onConfirmar: () => void;
}) {
  return (
    <Modal titleId="confirmar-modal-titulo" onClose={onCancelar}>
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 shrink-0 ${tono === 'danger' ? 'text-warning' : 'text-primary'}`}>
          <AlertTriangle className="size-5" aria-hidden />
        </div>
        <div className="flex flex-col gap-1.5">
          <h3 id="confirmar-modal-titulo" className="m-0 text-[15px] font-semibold">{titulo}</h3>
          <p className="m-0 text-[13px] text-text-muted text-pretty">{mensaje}</p>
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancelar}>Cancelar</Button>
        <Button variant={tono === 'danger' ? 'danger' : 'primary'} onClick={onConfirmar}>{textoConfirmar}</Button>
      </div>
    </Modal>
  );
}
