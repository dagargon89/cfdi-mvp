import { Outlet } from 'react-router';
import { useAuth } from './AuthContext';
import { DeniedScreen } from '@/features/shared/DeniedScreen';

/** Los módulos /admin/* solo son visibles en el nav para admin (demo.html:1176-1179); aquí además se
 * bloquea la ruta en sí — el backend real hará el 403 (doc 05 §2), esto solo evita una tabla vacía.
 *
 * El mensaje es propio y no el de empresa: quien llegue a /admin/fiscal sin ser administrador tiene
 * que leer *por qué* no le toca y a dónde ir, no un error crudo ni un texto que habla de una empresa
 * que no viene al caso. La configuración fiscal es política federal (aplica a todas las empresas);
 * la de la propia organización sí está abierta a su operador, en Empresa → Configuración. */
export function RequireAdmin() {
  const { usuario } = useAuth();
  if (usuario?.rol_global !== 'admin') {
    return (
      <DeniedScreen
        titulo="Esta sección es solo para administradores"
        mensaje="La configuración fiscal (UMA, salarios mínimos, tipo de cambio) es la misma para todas las empresas de esta instalación, así que solo un administrador la captura y la confirma. La configuración de tu organización —zona salarial, aguinaldo, prima vacacional y la clasificación de sus conceptos de nómina— sí está a tu alcance, en Empresa → Configuración."
        enlace={{ href: '/empresas', texto: 'Volver a mis empresas' }}
      />
    );
  }
  return <Outlet />;
}
