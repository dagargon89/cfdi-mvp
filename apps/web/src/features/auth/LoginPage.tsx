// Puerto de demo.html:32-70 (P1 Login) — el selector de "cuentas de demostración" del prototipo se
// sustituye por un formulario real de Firebase Auth (decisión de David: Firebase real desde ahora).
import { AlertTriangle } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, Navigate } from 'react-router';
import { Button } from '@/components/ui/Button';
import { useAuth } from '@/auth/AuthContext';

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
    <div className="min-h-screen grid place-items-center bg-bg p-8">
      <div className="w-full max-w-[420px] flex flex-col gap-6">
        <div className="flex items-center gap-3">
          <div className="size-10 rounded-lg bg-primary text-white grid place-items-center font-bold text-[15px] tracking-tight">HC</div>
          <div>
            <div className="text-[22px] font-bold leading-tight">Hub CFDI</div>
            <div className="text-xs text-text-muted">Descarga masiva y cumplimiento CFDI</div>
          </div>
        </div>

        <div className="bg-surface border border-border rounded-lg p-6 flex flex-col gap-4">
          <div className="text-lg font-semibold">Iniciar sesión</div>

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
                  className="h-9 border border-border rounded px-2.5"
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
                  className="h-9 border border-border rounded px-2.5"
                />
              </div>
              {loginError && (
                <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] font-medium">
                  {loginError}
                </div>
              )}
              <Button type="submit" loading={enviando} className="justify-center">
                Entrar
              </Button>
              <div className="flex text-[13px]">
                <Link to="/registro" className="text-primary">Crear cuenta</Link>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
