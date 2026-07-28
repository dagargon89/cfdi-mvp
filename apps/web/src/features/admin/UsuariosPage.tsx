// demo.html:695-721 (P10 Usuarios) + lógica demo.html:1388.
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Paginador } from '@/components/ui/Paginador';
import { api } from '@/lib/client';

// `listarUsuarios()` devuelve el arreglo completo (no está paginado en el backend — la
// lista de usuarios internos del despacho es chica); se pagina aquí solo en cliente para
// que la tabla se vea consistente con el resto del proyecto.
const POR_PAGINA = 20;

export function UsuariosPage() {
  const { data: usuarios } = useQuery({ queryKey: ['usuarios'], queryFn: () => api.listarUsuarios() });
  const [pagina, setPagina] = useState(1);
  const usuariosPagina = (usuarios ?? []).slice((pagina - 1) * POR_PAGINA, pagina * POR_PAGINA);

  return (
    <div className="flex flex-col gap-4">
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
            </tr>
          </thead>
          <tbody>
            {usuariosPagina.map((u) => (
              <tr key={u.usuario_id} className="border-t border-border h-10">
                <td className="px-3 text-[13px] font-semibold">{u.nombre}</td>
                <td className="px-3 font-mono text-xs">{u.correo}</td>
                <td className="px-3"><span className="text-xs font-semibold text-primary bg-primary-soft rounded-md px-2 py-0.5">{u.rol_global}</span></td>
                <td className="px-3 py-2 text-xs text-text-muted text-pretty">
                  {u.rol_global === 'admin'
                    ? 'Todas las empresas (rol global admin)'
                    : u.permisos.map((p) => `${p.empresa_nombre} (${p.rol})`).join(' · ') || 'Sin asignaciones'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Paginador page={pagina} perPage={POR_PAGINA} total={usuarios?.length ?? 0} onChange={setPagina} />
      </div>
    </div>
  );
}
