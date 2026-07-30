// Modal de edición de usuario (admin): cambia el rol global y asigna empresas con su rol por-empresa.
// El backend ya expone PATCH /usuarios/{id} (rol) y PUT /usuarios/{id}/permisos (reemplaza el set).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/ToastProvider';
import type { Rol, UsuarioAdmin } from '@/lib/api';
import { ApiError } from '@/lib/api';
import { api } from '@/lib/client';

const SELECT = 'h-9 border border-border rounded-md bg-surface px-2.5 text-[13px] text-text-strong';

type Seleccion = Record<number, { asignada: boolean; rol: Exclude<Rol, 'admin'> }>;

export function EditarUsuarioModal({ usuario, onClose }: { usuario: UsuarioAdmin; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: empresas } = useQuery({ queryKey: ['empresas'], queryFn: () => api.listarEmpresas() });

  const [rolGlobal, setRolGlobal] = useState<Rol>(usuario.rol_global);
  const [seleccion, setSeleccion] = useState<Seleccion>(() => {
    const inicial: Seleccion = {};
    for (const p of usuario.permisos) inicial[p.empresa_id] = { asignada: true, rol: p.rol === 'operador' ? 'operador' : 'consulta' };
    return inicial;
  });

  const esAdmin = rolGlobal === 'admin';

  const guardar = useMutation({
    mutationFn: async () => {
      if (rolGlobal !== usuario.rol_global) await api.actualizarUsuario(usuario.usuario_id, { rol_global: rolGlobal });
      if (rolGlobal !== 'admin') {
        const permisos = (empresas ?? [])
          .filter((e) => seleccion[e.empresa_id]?.asignada)
          .map((e) => ({ empresa_id: e.empresa_id, rol: seleccion[e.empresa_id].rol }));
        await api.guardarPermisos(usuario.usuario_id, permisos);
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['usuarios'] });
      toast('Usuario actualizado', 'ok');
      onClose();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : 'No se pudo guardar', 'error'),
  });

  function set(empresaId: number, cambio: Partial<Seleccion[number]>) {
    setSeleccion((s) => ({ ...s, [empresaId]: { asignada: s[empresaId]?.asignada ?? false, rol: s[empresaId]?.rol ?? 'consulta', ...cambio } }));
  }

  return (
    <Modal titleId="editar-usuario-titulo" onClose={onClose}>
      <div className="flex flex-col gap-1">
        <h3 id="editar-usuario-titulo" className="m-0 text-[15px] font-semibold">Editar usuario</h3>
        <p className="m-0 text-[13px] text-text-muted">{usuario.nombre} · <span className="font-mono">{usuario.correo}</span></p>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="eu-rol" className="text-xs font-semibold text-text-muted">Rol global</label>
        <select id="eu-rol" value={rolGlobal} onChange={(e) => setRolGlobal(e.target.value as Rol)} className={SELECT}>
          <option value="admin">Admin</option>
          <option value="operador">Operador</option>
          <option value="consulta">Consulta</option>
        </select>
      </div>

      {esAdmin ? (
        <p className="m-0 text-[13px] text-text-muted bg-surface-alt rounded-md px-3 py-2.5 text-pretty">
          Los administradores tienen acceso a <strong>todas las empresas</strong>. No hace falta asignarlas una por una.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold text-text-muted">Empresas asignadas</span>
          <div className="border border-border rounded-md divide-y divide-border max-h-[280px] overflow-y-auto">
            {(empresas ?? []).map((e) => {
              const sel = seleccion[e.empresa_id];
              return (
                <div key={e.empresa_id} className="flex items-center gap-3 px-3 py-2">
                  <input
                    type="checkbox"
                    id={`eu-emp-${e.empresa_id}`}
                    checked={sel?.asignada ?? false}
                    onChange={(ev) => set(e.empresa_id, { asignada: ev.target.checked })}
                    className="size-4"
                  />
                  <label htmlFor={`eu-emp-${e.empresa_id}`} className="flex-1 min-w-0 text-[13px] truncate">
                    {e.nombre} <span className="font-mono text-xs text-text-muted">{e.rfc}</span>
                  </label>
                  <select
                    aria-label={`Rol en ${e.nombre}`}
                    value={sel?.rol ?? 'consulta'}
                    disabled={!sel?.asignada}
                    onChange={(ev) => set(e.empresa_id, { rol: ev.target.value as Exclude<Rol, 'admin'> })}
                    className={`${SELECT} h-8 disabled:opacity-50`}
                  >
                    <option value="operador">Operador</option>
                    <option value="consulta">Consulta</option>
                  </select>
                </div>
              );
            })}
            {empresas?.length === 0 && <div className="px-3 py-3 text-[13px] text-text-muted">No hay empresas registradas.</div>}
          </div>
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={guardar.isPending}>Cancelar</Button>
        <Button onClick={() => guardar.mutate()} loading={guardar.isPending} disabled={guardar.isPending}>Guardar</Button>
      </div>
    </Modal>
  );
}
