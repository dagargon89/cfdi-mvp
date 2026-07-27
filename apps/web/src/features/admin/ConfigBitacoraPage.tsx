// demo.html:724-781 (P11 Config·Bitácora) + lógica demo.html:1389-1394. Las pestañas son rutas reales
// (/admin/config, /admin/bitacora) — doc 09 §2 les asigna rutas separadas, a diferencia del `adminTab`
// en memoria del prototipo.
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router';
import { api } from '@/lib/client';

export function ConfigBitacoraPage() {
  const { pathname } = useLocation();
  const enBitacora = pathname.startsWith('/admin/bitacora');

  const { data: config } = useQuery({ queryKey: ['config'], queryFn: () => api.listarConfiguracion(), enabled: !enBitacora });
  const { data: bitacoraPage } = useQuery({ queryKey: ['bitacora'], queryFn: () => api.listarBitacora(), enabled: enBitacora });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-1 bg-surface-alt rounded-md p-0.5 w-fit">
        <Link
          to="/admin/config"
          className="h-[30px] rounded px-3.5 text-[13px] font-semibold inline-flex items-center"
          style={{ background: !enBitacora ? 'var(--surface)' : 'transparent', color: !enBitacora ? 'var(--primary)' : 'var(--text-muted)' }}
        >
          Configuración
        </Link>
        <Link
          to="/admin/bitacora"
          className="h-[30px] rounded px-3.5 text-[13px] font-semibold inline-flex items-center"
          style={{ background: enBitacora ? 'var(--surface)' : 'transparent', color: enBitacora ? 'var(--primary)' : 'var(--text-muted)' }}
        >
          Bitácora
        </Link>
      </div>

      {!enBitacora && (
        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          <table>
            <caption className="sr-only">Parámetros de configuración</caption>
            <thead>
              <tr className="bg-surface-alt">
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Clave</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Ejercicio fiscal</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Valor</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Descripción</th>
              </tr>
            </thead>
            <tbody>
              {config?.map((c) => (
                <tr key={c.clave} className="border-t border-border h-10">
                  <td className="px-3 font-mono text-[13px]">{c.clave}</td>
                  <td className="px-3 font-mono text-xs text-text-muted">{c.ejercicio_fiscal}</td>
                  <td className="px-3 font-mono text-[13px] font-medium">{c.valor}</td>
                  <td className="px-3 py-2 text-xs text-text-muted text-pretty">{c.descripcion}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {enBitacora && (
        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          <table>
            <caption className="sr-only">Bitácora de acciones</caption>
            <thead>
              <tr className="bg-surface-alt">
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Fecha</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Actor</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Acción</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Entidad</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Detalle</th>
              </tr>
            </thead>
            <tbody>
              {bitacoraPage?.data.map((b) => (
                <tr key={b.bitacora_id} className="border-t border-border h-10">
                  <td className="px-3 font-mono text-xs whitespace-nowrap">{b.created_at}</td>
                  <td className="px-3 font-mono text-xs">{b.actor}</td>
                  <td className="px-3 text-[13px] font-medium">{b.accion}</td>
                  <td className="px-3 font-mono text-xs text-text-muted">{b.entidad}</td>
                  <td className="px-3 py-2 font-mono text-xs text-text-muted">{JSON.stringify(b.detalle)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
