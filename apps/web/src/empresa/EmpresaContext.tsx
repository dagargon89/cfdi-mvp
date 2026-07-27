// Resuelve la empresa actual (:id de la ruta) contra las empresas autorizadas del usuario — el
// equivalente en el cliente de `entrarEmpresa()`/`rolEn()` del prototipo (demo.html:1044-1051,1133-1136).
// Cualquier :id que no aparezca en listarEmpresas() (no existe o sin permiso — doc 05 §1.3, misma
// respuesta por anti-enumeración) marca `denied: true` en el contexto en vez de tirar el árbol entero.
//
// Importante: EmpresaProvider debe ser ANCESTRO de AppShell (no al revés) para esta ruta — si el
// Sidebar quedara fuera del árbol donde se provee este contexto, nunca vería en qué empresa está el
// usuario y jamás mostraría los ítems de navegación de empresa (bug real: ver App.tsx).
import { createContext, useContext, useEffect } from 'react';
import { Outlet, useParams } from 'react-router';
import type { EmpresaResumen, Rol } from '@/lib/api';
import { useEmpresas } from '@/hooks/useEmpresas';
import { DeniedScreen } from '@/features/shared/DeniedScreen';
import { useCurrentEmpresaId } from './currentEmpresaStore';

interface EmpresaCtxValue {
  empresa: EmpresaResumen | null;
  rol: Rol | null;
  puedeMutar: boolean;
  denied: boolean;
}

const Ctx = createContext<EmpresaCtxValue | null>(null);

export function EmpresaProvider() {
  const { id } = useParams();
  const empresaId = Number(id);
  const { data: empresas, isLoading } = useEmpresas();
  const { setEmpresaId } = useCurrentEmpresaId();

  const empresa = empresas?.find((e) => e.empresa_id === empresaId) ?? null;

  // Sincroniza la empresa "pegajosa" del sidebar en cuanto esta ruta resuelve una empresa válida —
  // así Bóveda/Descargas/Comprobantes/Alertas/Notificaciones siguen visibles al navegar a Admin.
  useEffect(() => {
    if (empresa) setEmpresaId(empresa.empresa_id);
  }, [empresa, setEmpresaId]);

  if (isLoading) return null;
  const value: EmpresaCtxValue = empresa
    ? { empresa, rol: empresa.rol, puedeMutar: empresa.rol === 'operador' || empresa.rol === 'admin', denied: false }
    : { empresa: null, rol: null, puedeMutar: false, denied: true };

  return (
    <Ctx.Provider value={value}>
      <Outlet />
    </Ctx.Provider>
  );
}

/** Dentro de AppShell, dentro de EmpresaProvider: pinta DeniedScreen o delega a la pantalla pedida. */
export function EmpresaGate() {
  const ctx = useContext(Ctx);
  if (ctx?.denied) return <DeniedScreen />;
  return <Outlet />;
}

/** Para pantallas dentro de /e/:id/* (ya pasado el EmpresaGate) — lanza si empresa no está resuelta. */
export function useEmpresaCtx(): { empresa: EmpresaResumen; rol: Rol; puedeMutar: boolean } {
  const ctx = useContext(Ctx);
  if (!ctx || ctx.denied || !ctx.empresa || !ctx.rol) {
    throw new Error('useEmpresaCtx debe usarse dentro de una ruta /e/:id/* ya autorizada (después de <EmpresaGate>)');
  }
  return { empresa: ctx.empresa, rol: ctx.rol, puedeMutar: ctx.puedeMutar };
}
