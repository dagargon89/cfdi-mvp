// demo.html:161-171 (403 sin permiso) — también cubre "empresa no existe" (doc 05 §1.3: 404 y 403
// responden igual por anti-enumeración), igual que el botón "Abrir empresa 8 sin permiso" del demo.
// Los textos son parametrizables porque el mismo bloqueo cubre dos casos que no se explican igual:
// no tener permiso sobre una empresa, y no ser administrador (ver RequireAdmin).
import { ShieldX } from 'lucide-react';
import { Link } from 'react-router';

export function DeniedScreen({
  titulo = 'No tienes acceso a esta empresa',
  mensaje = 'Tu cuenta no tiene permisos asignados sobre esta empresa. Pide a un administrador que te agregue en Administración → Usuarios.',
  enlace = { href: '/empresas', texto: 'Volver a mis empresas' },
}: {
  titulo?: string;
  mensaje?: string;
  enlace?: { href: string; texto: string };
} = {}) {
  return (
    <div className="my-12 mx-auto max-w-[460px] text-center flex flex-col items-center gap-3">
      <div className="size-12 rounded-full bg-danger-soft text-danger grid place-items-center">
        <ShieldX className="size-6" aria-hidden />
      </div>
      <h2 className="m-0 text-lg font-semibold">{titulo}</h2>
      <p className="m-0 text-text-muted text-pretty">{mensaje}</p>
      <Link
        to={enlace.href}
        className="h-9 border border-border bg-surface rounded-md px-4 font-semibold inline-flex items-center hover:bg-surface-alt"
      >
        {enlace.texto}
      </Link>
    </div>
  );
}
