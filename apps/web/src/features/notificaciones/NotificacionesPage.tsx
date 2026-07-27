// demo.html:646-692 (P9 Notificaciones) + lógica demo.html:1372-1386.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/ToastProvider';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import { api } from '@/lib/client';
import type { TipoEvento } from '@/lib/api';

const EVENTOS_LABEL: Record<TipoEvento, string> = {
  efos: 'EFOS (69-B)',
  cancelacion_tardia: 'Cancelación tardía',
  error_descarga: 'Error de descarga',
  efirma_por_vencer: 'e.firma por vencer',
  resumen_sync: 'Resumen de sincronización',
};
const EVENTOS_DISPONIBLES: TipoEvento[] = ['efos', 'cancelacion_tardia', 'error_descarga', 'efirma_por_vencer'];

export function NotificacionesPage() {
  const { empresa, puedeMutar } = useEmpresaCtx();
  const { toast } = useToast();
  const qc = useQueryClient();

  const { data } = useQuery({ queryKey: ['notificaciones', empresa.empresa_id], queryFn: () => api.obtenerNotificaciones(empresa.empresa_id) });
  const destinos = data?.destinos ?? [];

  const [correo, setCorreo] = useState('');
  const [eventos, setEventos] = useState<TipoEvento[]>(['efos', 'cancelacion_tardia']);

  const guardar = useMutation({
    mutationFn: () => api.guardarNotificaciones(empresa.empresa_id, [...destinos, { correo: correo.trim(), eventos }]),
    onSuccess: () => {
      setCorreo('');
      setEventos(['efos', 'cancelacion_tardia']);
      qc.invalidateQueries({ queryKey: ['notificaciones', empresa.empresa_id] });
      toast('Destino agregado', 'ok');
    },
  });

  function agregar() {
    if (!correo.trim().includes('@')) {
      toast('Escribe un correo válido', 'error');
      return;
    }
    guardar.mutate();
  }

  function toggleEvento(k: TipoEvento) {
    setEventos((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));
  }

  return (
    <div className="flex flex-col gap-4 max-w-[900px]">
      <div className="bg-surface border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-border"><h3 className="m-0 text-[15px] font-semibold">Destinos de notificación</h3></div>
        <table>
          <caption className="sr-only">Destinos y suscripciones</caption>
          <thead>
            <tr className="bg-surface-alt">
              <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Correo</th>
              <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Eventos suscritos</th>
              <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Estado</th>
            </tr>
          </thead>
          <tbody>
            {destinos.map((d) => (
              <tr key={d.correo} className="border-t border-border h-10">
                <td className="px-3 font-mono text-[13px]">{d.correo}</td>
                <td className="px-3 py-2 text-xs text-text-muted">{d.eventos.map((e) => EVENTOS_LABEL[e]).join(' · ')}</td>
                <td className="px-3"><span className="text-xs font-semibold text-success bg-success-soft rounded-md px-2 py-0.5">Activo</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {puedeMutar && (
        <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3">
          <h3 className="m-0 text-[15px] font-semibold">Agregar destino</h3>
          <div className="flex flex-col gap-1.5 max-w-[320px]">
            <label htmlFor="n-mail" className="text-xs font-semibold text-text-muted">Correo</label>
            <input id="n-mail" type="email" value={correo} onChange={(e) => setCorreo(e.target.value)} placeholder="alguien@demo.test" className="h-9 border border-border rounded px-2.5" />
          </div>
          <fieldset className="border-0 p-0 m-0 flex flex-col gap-2">
            <legend className="text-xs font-semibold text-text-muted p-0">Eventos</legend>
            <div className="flex flex-wrap gap-2.5">
              {EVENTOS_DISPONIBLES.map((k) => (
                <label
                  key={k}
                  className="inline-flex items-center gap-1.5 border border-border rounded-md px-2.5 py-1.5 text-[13px] cursor-pointer"
                  style={{ background: eventos.includes(k) ? 'var(--primary-soft)' : '#fff' }}
                >
                  <input type="checkbox" checked={eventos.includes(k)} onChange={() => toggleEvento(k)} /> {EVENTOS_LABEL[k]}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <Button onClick={agregar} loading={guardar.isPending} disabled={guardar.isPending}>Guardar destino</Button>
          </div>
        </div>
      )}
    </div>
  );
}
