// La "empresa actual" es estado pegajoso (sticky) del sidebar, no derivado de la ruta — así se
// comporta el prototipo: `st.empresaId` (demo.html:1000-1013) solo cambia al entrar a otra empresa o
// al cerrar sesión; navegar a Admin o de vuelta a Empresas NO lo limpia (`ir('usuarios')` sólo cambia
// `screen`, nunca toca `empresaId` — de ahí que en el demo el sidebar mantenga Bóveda/Descargas/etc.
// visibles aun estando en Admin). Montado dentro de <RequireAuth> para que se resetee solo al cerrar
// sesión (el árbol entero se desmonta al redirigir a /login).
import { createContext, useContext, useState, type ReactNode } from 'react';

interface Store {
  empresaId: number | null;
  setEmpresaId: (id: number | null) => void;
}

const Ctx = createContext<Store | null>(null);

export function CurrentEmpresaProvider({ children }: { children: ReactNode }) {
  const [empresaId, setEmpresaId] = useState<number | null>(null);
  return <Ctx.Provider value={{ empresaId, setEmpresaId }}>{children}</Ctx.Provider>;
}

export function useCurrentEmpresaId(): Store {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useCurrentEmpresaId debe usarse dentro de <CurrentEmpresaProvider>');
  return ctx;
}
