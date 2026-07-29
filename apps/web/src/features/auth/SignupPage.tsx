// Signup de arranque del primer administrador (spec 2026-07-29). Solo se muestra cuando la BD no tiene
// usuarios; crea la cuenta Firebase (con contraseña) + el registro local admin vía POST /v1/auth/bootstrap.
import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate } from 'react-router';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/ToastProvider';
import { useAuth } from '@/auth/AuthContext';
import { ApiError } from '@/lib/api';
import { api } from '@/lib/client';

const ERROR_MENSAJE: Record<string, string> = {
  TOKEN_INVALIDO: 'El token de arranque es incorrecto.',
  CORREO_DUPLICADO: 'Ya existe una cuenta con ese correo.',
  BOOTSTRAP_YA_REALIZADO: 'El administrador ya fue creado. Inicia sesión.',
  BOOTSTRAP_DESHABILITADO: 'El alta de arranque no está habilitada en el servidor.',
};

export function SignupPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { needsBootstrap } = useAuth();
  const [correo, setCorreo] = useState('');
  const [nombre, setNombre] = useState('');
  const [password, setPassword] = useState('');
  const [confirmar, setConfirmar] = useState('');
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  if (needsBootstrap === false) return <Navigate to="/login" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmar) {
      setError('Las contraseñas no coinciden.');
      return;
    }
    setEnviando(true);
    try {
      await api.crearAdminBootstrap({ correo, nombre, password, token });
      toast('Administrador creado. Inicia sesión con tus credenciales.', 'ok');
      navigate('/login', { replace: true });
    } catch (err) {
      if (err instanceof ApiError) setError(ERROR_MENSAJE[err.codigo] ?? err.message);
      else setError('No se pudo completar el alta.');
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="min-h-screen grid place-items-center bg-bg p-8">
      <div className="w-full max-w-[420px] flex flex-col gap-6">
        <div className="flex items-center gap-3">
          <div className="size-10 rounded-lg bg-primary text-white grid place-items-center font-bold text-[15px] tracking-tight">HC</div>
          <div>
            <div className="text-[22px] font-bold leading-tight">Hub CFDI</div>
            <div className="text-xs text-text-muted">Configuración inicial</div>
          </div>
        </div>

        <div className="bg-surface border border-border rounded-lg p-6 flex flex-col gap-4">
          <div className="text-lg font-semibold">Crear administrador</div>
          <p className="m-0 text-[13px] text-text-muted text-pretty">
            No hay usuarios en el sistema. Crea la cuenta del administrador inicial. Necesitas el
            <span className="font-mono"> BOOTSTRAP_ADMIN_TOKEN</span> definido en el servidor.
          </p>
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="su-nombre" className="text-xs font-semibold text-text-muted">Nombre</label>
              <input id="su-nombre" required value={nombre} onChange={(e) => setNombre(e.target.value)} className="h-9 border border-border rounded px-2.5" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="su-mail" className="text-xs font-semibold text-text-muted">Correo</label>
              <input id="su-mail" type="email" required value={correo} onChange={(e) => setCorreo(e.target.value)} className="h-9 border border-border rounded px-2.5" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="su-pass" className="text-xs font-semibold text-text-muted">Contraseña (mín. 8)</label>
              <input id="su-pass" type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-9 border border-border rounded px-2.5" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="su-pass2" className="text-xs font-semibold text-text-muted">Confirmar contraseña</label>
              <input id="su-pass2" type="password" required autoComplete="new-password" value={confirmar} onChange={(e) => setConfirmar(e.target.value)} className="h-9 border border-border rounded px-2.5" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="su-token" className="text-xs font-semibold text-text-muted">Token de arranque</label>
              <input id="su-token" required value={token} onChange={(e) => setToken(e.target.value)} className="h-9 border border-border rounded px-2.5 font-mono" />
            </div>
            {error && (
              <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] font-medium">{error}</div>
            )}
            <Button type="submit" loading={enviando} className="justify-center">Crear administrador</Button>
          </form>
        </div>
      </div>
    </div>
  );
}
