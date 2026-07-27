// demo.html:869-882 (modal "Eliminar e.firma") — exige escribir el RFC para confirmar (doc 08 §5.5).
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';

export function EliminarEfirmaModal({ rfc, onCancelar, onConfirmar }: { rfc: string; onCancelar: () => void; onConfirmar: () => void }) {
  const [valor, setValor] = useState('');
  const deshabilitado = valor.trim().toUpperCase() !== rfc;

  return (
    <Modal titleId="mb-t" onClose={onCancelar}>
      <h2 id="mb-t" className="m-0 text-lg font-semibold">Eliminar e.firma</h2>
      <p className="m-0 text-[13px] text-text-muted text-pretty">
        Los jobs programados de esta empresa fallarán hasta que se registre una nueva e.firma. Escribe el RFC{' '}
        <strong className="font-mono text-text-strong">{rfc}</strong> para confirmar.
      </p>
      <input
        aria-label="RFC de confirmación"
        value={valor}
        onChange={(e) => setValor(e.target.value)}
        placeholder="RFC"
        className="h-9 border border-border rounded px-2.5 font-mono"
      />
      <div className="flex gap-2 justify-end">
        <Button variant="secondary" onClick={onCancelar}>Cancelar</Button>
        <Button variant="danger" disabled={deshabilitado} onClick={onConfirmar}>Eliminar</Button>
      </div>
    </Modal>
  );
}
