import { Outlet } from 'react-router';
import { useAuth } from './AuthContext';
import { DeniedScreen } from '@/features/shared/DeniedScreen';

/** Los módulos /admin/* solo son visibles en el nav para admin (demo.html:1176-1179); aquí además se
 * bloquea la ruta en sí — el backend real hará el 403 (doc 05 §2), esto solo evita una tabla vacía.
 *
 * El mensaje es propio y no el de empresa: quien llegue aquí sin ser administrador tiene que leer
 * *por qué* no le toca, no un error crudo ni un texto que habla de una empresa que no viene al
 * caso. Pero **el texto lo pone la ruta, no el guardián**: este mismo componente cubre
 * /admin/usuarios, /admin/config y /admin/bitácora, y explicarle a quien abre la bitácora que "la
 * UMA es la misma para todas las empresas" es contestarle a una pregunta que no hizo. El de por
 * omisión dice lo único que vale para las cuatro; la ruta fiscal pasa el suyo (ver App.tsx). */
export function RequireAdmin({ mensaje }: { mensaje?: string } = {}) {
  const { usuario } = useAuth();
  if (usuario?.rol_global !== 'admin') {
    return (
      <DeniedScreen
        titulo="Esta sección es solo para administradores"
        mensaje={
          mensaje ??
          'Esta pantalla administra la instalación entera —usuarios, configuración y bitácora—, así que solo un administrador entra. Lo tuyo, la configuración de cada organización a la que tienes acceso, está en Empresa → Configuración.'
        }
        enlace={{ href: '/empresas', texto: 'Volver a mis empresas' }}
      />
    );
  }
  return <Outlet />;
}
