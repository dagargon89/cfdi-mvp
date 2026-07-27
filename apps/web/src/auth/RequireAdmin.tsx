import { Outlet } from 'react-router';
import { useAuth } from './AuthContext';
import { DeniedScreen } from '@/features/shared/DeniedScreen';

/** Los módulos /admin/* solo son visibles en el nav para admin (demo.html:1176-1179); aquí además se
 * bloquea la ruta en sí — el backend real hará el 403 (doc 05 §2), esto solo evita una tabla vacía. */
export function RequireAdmin() {
  const { usuario } = useAuth();
  if (usuario?.rol_global !== 'admin') return <DeniedScreen />;
  return <Outlet />;
}
