// demo.html:161-171 (403 sin permiso) — también cubre "empresa no existe" (doc 05 §1.3: 404 y 403
// responden igual por anti-enumeración), igual que el botón "Abrir empresa 8 sin permiso" del demo.
import { ShieldX } from 'lucide-react';
import { Link } from 'react-router';

export function DeniedScreen() {
  return (
    <div className="my-12 mx-auto max-w-[460px] text-center flex flex-col items-center gap-3">
      <div className="size-12 rounded-full bg-danger-soft text-danger grid place-items-center">
        <ShieldX className="size-6" aria-hidden />
      </div>
      <h2 className="m-0 text-lg font-semibold">No tienes acceso a esta empresa</h2>
      <p className="m-0 text-text-muted text-pretty">
        Tu cuenta no tiene permisos asignados sobre esta empresa. Pide a un administrador que te agregue en
        Administración → Usuarios.
      </p>
      <Link
        to="/empresas"
        className="h-9 border border-border bg-surface rounded-md px-4 font-semibold inline-flex items-center hover:bg-surface-alt"
      >
        Volver a mis empresas
      </Link>
    </div>
  );
}
