// Modal de confirmación para acciones destructivas — exige escribir el RFC (doc 08 §5.5).
// Generalizado a partir del modal de "Eliminar e.firma" (demo.html:869-882); ahora también lo usa
// el borrado de empresa.
import type { ReactNode } from 'react';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';

export function ConfirmarRfcModal({
  titulo,
  descripcion,
  rfc,
  textoConfirmar = 'Eliminar',
  onCancelar,
  onConfirmar,
}: {
  titulo: string;
  descripcion: ReactNode;
  rfc: string;
  textoConfirmar?: string;
  onCancelar: () => void;
  onConfirmar: () => void;
}) {
  const [valor, setValor] = useState('');
  const deshabilitado = valor.trim().toUpperCase() !== rfc;

  return (
    <Modal titleId="cf-t" onClose={onCancelar}>
      <h2 id="cf-t" className="m-0 text-lg font-semibold">{titulo}</h2>
      <p className="m-0 text-[13px] text-text-muted text-pretty">{descripcion}</p>
      <input
        aria-label="RFC de confirmación"
        value={valor}
        onChange={(e) => setValor(e.target.value)}
        placeholder="RFC"
        className="h-9 border border-border rounded px-2.5 font-mono"
      />
      <div className="flex gap-2 justify-end">
        <Button variant="secondary" onClick={onCancelar}>Cancelar</Button>
        <Button variant="danger" disabled={deshabilitado} onClick={onConfirmar}>{textoConfirmar}</Button>
      </div>
    </Modal>
  );
}
