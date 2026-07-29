// Pantalla de inicio de sesión — layout dividido (ver AuthLayout): panel de marca + este formulario.
// Autenticación real con Firebase (decisión de David: Firebase real desde ahora).
import { AlertTriangle } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, Navigate } from 'react-router';
import { Button } from '@/components/ui/Button';
import { useAuth } from '@/auth/AuthContext';
import { AuthLayout } from './AuthLayout';

export function LoginPage() {
  const { firebaseConfigured, usuario, loginError, login, needsBootstrap, limpiarLoginError } = useAuth();
  const [correo, setCorreo] = useState('');
  const [password, setPassword] = useState('');
  const [enviando, setEnviando] = useState(false);

  // Una visita fresca a /login no debe arrastrar un loginError dejado por el onAuthStateChanged
  // global (p. ej. tras registrarse: la cuenta queda pendiente y ese listener setea el error en
  // segundo plano). Limpiar solo al montar no afecta el caso de un intento de login real, que
  // vuelve a setear el mensaje a través de login() -> onAuthStateChanged.
  useEffect(() => {
    limpiarLoginError();
  }, [limpiarLoginError]);

  if (needsBootstrap === null) return null; // aún cargando el estado de bootstrap
  if (needsBootstrap) return <Navigate to="/bootstrap" replace />;
  if (usuario) return <Navigate to="/empresas" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setEnviando(true);
    try {
      await login(correo, password);
    } catch {
      // loginError ya quedó seteado por AuthContext
    } finally {
      setEnviando(false);
    }
  }

  return (
    <AuthLayout>
      <div className="flex flex-col gap-1.5">
        <h1 className="m-0 text-[22px] font-bold tracking-tight">Iniciar sesión</h1>
        <p className="m-0 text-[13px] text-text-muted">Accede a tu cuenta de Hub CFDI.</p>
      </div>

      {!firebaseConfigured ? (
        <div role="alert" className="bg-warning-soft text-warning rounded-md px-2.5 py-3 text-sm font-medium flex gap-2">
          <AlertTriangle className="size-4.5 shrink-0 mt-0.5" aria-hidden />
          <span>
            Configuración de Firebase pendiente. Define <code className="font-mono">VITE_FIREBASE_*</code> en{' '}
            <code className="font-mono">.env.local</code> (ver <code className="font-mono">.env.example</code>) para poder iniciar sesión.
          </span>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="li-mail" className="text-xs font-semibold text-text-muted">Correo</label>
            <input
              id="li-mail"
              type="email"
              required
              value={correo}
              onChange={(e) => setCorreo(e.target.value)}
              placeholder="tu@correo.com"
              className="h-10 border border-border rounded-md px-3 bg-surface"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="li-pass" className="text-xs font-semibold text-text-muted">Contraseña</label>
            <input
              id="li-pass"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-10 border border-border rounded-md px-3 bg-surface"
            />
          </div>
          {loginError && (
            <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] font-medium">
              {loginError}
            </div>
          )}
          <Button type="submit" loading={enviando} className="h-10 justify-center">
            Entrar
          </Button>
          <p className="m-0 text-[13px] text-text-muted text-center">
            ¿No tienes cuenta? <Link to="/registro" className="text-primary font-medium">Crear cuenta</Link>
          </p>
        </form>
      )}
    </AuthLayout>
  );
}
