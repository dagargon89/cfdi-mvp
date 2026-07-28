// Alta de empresa (RF-EMP-01, doc 05 §3 POST /v1/empresas) — no existía en el prototipo original
// ni en el demo (doc 09 nunca diseñó esta pantalla); admin-only, backend ya la soporta.
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/ToastProvider';
import { ApiError } from '@/lib/api';
import { api } from '@/lib/client';

export function NuevaEmpresaModal({ onClose }: { onClose: () => void }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [nombre, setNombre] = useState('');
  const [rfc, setRfc] = useState('');
  const [error, setError] = useState<string | null>(null);

  const crear = useMutation({
    mutationFn: () => api.crearEmpresa({ nombre: nombre.trim(), rfc: rfc.trim().toUpperCase() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresas'] });
      toast('Empresa creada', 'ok');
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'No se pudo crear la empresa.'),
  });

  return (
    <Modal titleId="ne-t" onClose={onClose}>
      <h2 id="ne-t" className="m-0 text-lg font-semibold">
        Nueva empresa
      </h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          crear.mutate();
        }}
        className="flex flex-col gap-3.5"
      >
        <div className="flex flex-col gap-1.5">
          <label htmlFor="ne-nombre" className="text-xs font-semibold text-text-muted">
            Razón social
          </label>
          <input
            id="ne-nombre"
            required
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            className="h-9 border border-border rounded px-2.5"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="ne-rfc" className="text-xs font-semibold text-text-muted">
            RFC
          </label>
          <input
            id="ne-rfc"
            required
            minLength={12}
            maxLength={13}
            value={rfc}
            onChange={(e) => setRfc(e.target.value)}
            placeholder="EKU9003173C9"
            className="h-9 border border-border rounded px-2.5 font-mono uppercase"
          />
        </div>
        {error && <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px]">{error}</div>}
        <div className="flex gap-2 justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" loading={crear.isPending} disabled={crear.isPending}>
            Crear
          </Button>
        </div>
      </form>
    </Modal>
  );
}
