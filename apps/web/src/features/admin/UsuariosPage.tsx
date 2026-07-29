// demo.html:695-721 (P10 Usuarios) + lógica demo.html:1388.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Paginador } from '@/components/ui/Paginador';
import { useToast } from '@/components/ui/ToastProvider';
import { api } from '@/lib/client';

// `listarUsuarios()` devuelve el arreglo completo (no está paginado en el backend — la
// lista de usuarios internos del despacho es chica); se pagina aquí solo en cliente para
// que la tabla se vea consistente con el resto del proyecto.
const POR_PAGINA = 20;

export function UsuariosPage() {
  const { data: usuarios } = useQuery({ queryKey: ['usuarios'], queryFn: () => api.listarUsuarios() });
  const [pagina, setPagina] = useState(1);
  const usuariosPagina = (usuarios ?? []).slice((pagina - 1) * POR_PAGINA, pagina * POR_PAGINA);
  const pendientes = (usuarios ?? []).filter((u) => !u.aprobado).length;

  const qc = useQueryClient();
  const { toast } = useToast();

  const aprobar = useMutation({
    mutationFn: (id: number) => api.actualizarUsuario(id, { aprobado: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['usuarios'] });
      toast('Usuario aprobado', 'ok');
    },
    onError: () => toast('No se pudo aprobar', 'error'),
  });
  const rechazar = useMutation({
    mutationFn: (id: number) => api.eliminarUsuario(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['usuarios'] });
      toast('Solicitud rechazada', 'ok');
    },
    onError: () => toast('No se pudo rechazar', 'error'),
  });

  return (
    <div className="flex flex-col gap-4">
      {pendientes > 0 && (
        <div className="bg-warning-soft text-warning rounded-md px-3 py-2 text-[13px] font-semibold">
          {pendientes} solicitud{pendientes === 1 ? '' : 'es'} pendiente{pendientes === 1 ? '' : 's'} de aprobación
        </div>
      )}
      <div className="bg-surface border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-border"><h3 className="m-0 text-[15px] font-semibold">Usuarios y permisos</h3></div>
        <table>
          <caption className="sr-only">Usuarios del sistema</caption>
          <thead>
            <tr className="bg-surface-alt">
              <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Usuario</th>
              <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Correo</th>
              <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Rol global</th>
              <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Empresas asignadas</th>
              <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Estado</th>
              <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {usuariosPagina.map((u) => {
              const estado = !u.aprobado
                ? { texto: 'Pendiente', fg: 'text-warning', bg: 'bg-warning-soft' }
                : !u.activo
                  ? { texto: 'Inactivo', fg: 'text-neutral', bg: 'bg-neutral-soft' }
                  : { texto: 'Activo', fg: 'text-success', bg: 'bg-success-soft' };
              return (
                <tr key={u.usuario_id} className="border-t border-border h-10">
                  <td className="px-3 text-[13px] font-semibold">{u.nombre}</td>
                  <td className="px-3 font-mono text-xs">{u.correo}</td>
                  <td className="px-3"><span className="text-xs font-semibold text-primary bg-primary-soft rounded-md px-2 py-0.5">{u.rol_global}</span></td>
                  <td className="px-3 py-2 text-xs text-text-muted text-pretty">
                    {u.rol_global === 'admin'
                      ? 'Todas las empresas (rol global admin)'
                      : u.permisos.map((p) => `${p.empresa_nombre} (${p.rol})`).join(' · ') || 'Sin asignaciones'}
                  </td>
                  <td className="px-3">
                    <span className={`text-xs font-semibold rounded-md px-2 py-0.5 ${estado.fg} ${estado.bg}`}>{estado.texto}</span>
                  </td>
                  <td className="px-3">
                    {!u.aprobado && (
                      <div className="flex items-center gap-2">
                        <Button
                          variant="primary"
                          className="h-7 px-2.5 text-xs"
                          loading={aprobar.isPending && aprobar.variables === u.usuario_id}
                          disabled={aprobar.isPending || rechazar.isPending}
                          onClick={() => aprobar.mutate(u.usuario_id)}
                        >
                          Aprobar
                        </Button>
                        <Button
                          variant="danger"
                          className="h-7 px-2.5 text-xs"
                          loading={rechazar.isPending && rechazar.variables === u.usuario_id}
                          disabled={aprobar.isPending || rechazar.isPending}
                          onClick={() => {
                            if (confirm(`¿Rechazar la solicitud de ${u.nombre} (${u.correo})? Se borrará su cuenta.`)) {
                              rechazar.mutate(u.usuario_id);
                            }
                          }}
                        >
                          Rechazar
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Paginador page={pagina} perPage={POR_PAGINA} total={usuarios?.length ?? 0} onChange={setPagina} />
      </div>
    </div>
  );
}
