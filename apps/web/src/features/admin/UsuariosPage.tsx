// demo.html:695-721 (P10 Usuarios) + lógica demo.html:1388.
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/client';

export function UsuariosPage() {
  const { data: usuarios } = useQuery({ queryKey: ['usuarios'], queryFn: () => api.listarUsuarios() });

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
            {usuarios?.map((u) => (
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
      </div>
    </div>
  );
}
