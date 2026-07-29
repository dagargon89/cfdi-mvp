// Auto-registro con aprobación (spec 2026-07-29): cualquiera puede crear cuenta en Firebase, pero
// queda "pendiente" hasta que un administrador la apruebe en /admin/usuarios. Layout dividido (AuthLayout).
import { createUserWithEmailAndPassword, signOut } from 'firebase/auth';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { Button } from '@/components/ui/Button';
import { ApiError } from '@/lib/api';
import { api } from '@/lib/client';
import { getFirebaseAuth } from '@/lib/firebase';
import { AuthLayout } from './AuthLayout';

const FIREBASE_ERROR_MENSAJE: Record<string, string> = {
  'auth/email-already-in-use': 'Ya existe una cuenta con ese correo.',
  'auth/weak-password': 'La contraseña es muy débil (mínimo 6 caracteres).',
  'auth/invalid-email': 'Ese correo no tiene un formato válido.',
};

const API_ERROR_MENSAJE: Record<string, string> = {
  YA_REGISTRADO: 'Ya existe una cuenta con ese correo.',
  REGISTRO_NO_DISPONIBLE: 'El registro no está disponible todavía; el primer usuario es el administrador.',
};

const INPUT = 'h-10 border border-border rounded-md px-3 bg-surface';

export function RegistroPage() {
  const [nombre, setNombre] = useState('');
  const [correo, setCorreo] = useState('');
  const [password, setPassword] = useState('');
  const [confirmar, setConfirmar] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmar) {
      setError('Las contraseñas no coinciden.');
      return;
    }
    const auth = getFirebaseAuth();
    if (!auth) return;
    setEnviando(true);
    try {
      await createUserWithEmailAndPassword(auth, correo, password);
      await api.registrarUsuario({ nombre });
      await signOut(auth); // no dejarlo "logueado": la cuenta queda pendiente de aprobación
      setOk(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(API_ERROR_MENSAJE[err.codigo] ?? err.message);
      } else {
        const codigo = err instanceof Error && 'code' in err ? String((err as { code: string }).code) : '';
        setError(FIREBASE_ERROR_MENSAJE[codigo] ?? 'No se pudo completar el registro.');
      }
    } finally {
      setEnviando(false);
    }
  }

  return (
    <AuthLayout>
      <div className="flex flex-col gap-1.5">
        <h1 className="m-0 text-[22px] font-bold tracking-tight">Crear cuenta</h1>
        <p className="m-0 text-[13px] text-text-muted">Solicita acceso a Hub CFDI.</p>
      </div>

      {ok ? (
        <div className="flex flex-col gap-4">
          <div role="status" className="bg-primary-soft text-primary rounded-md px-3 py-3 text-sm font-medium text-pretty">
            Cuenta creada. Un administrador debe aprobar tu acceso antes de que puedas entrar.
          </div>
          <Link to="/login" className="text-primary text-[13px] font-semibold">Ir a iniciar sesión</Link>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="rg-nombre" className="text-xs font-semibold text-text-muted">Nombre</label>
            <input id="rg-nombre" required value={nombre} onChange={(e) => setNombre(e.target.value)} className={INPUT} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="rg-mail" className="text-xs font-semibold text-text-muted">Correo</label>
            <input id="rg-mail" type="email" required value={correo} onChange={(e) => setCorreo(e.target.value)} placeholder="tu@correo.com" className={INPUT} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="rg-pass" className="text-xs font-semibold text-text-muted">Contraseña</label>
            <input id="rg-pass" type="password" required minLength={6} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className={INPUT} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="rg-pass2" className="text-xs font-semibold text-text-muted">Confirmar contraseña</label>
            <input id="rg-pass2" type="password" required autoComplete="new-password" value={confirmar} onChange={(e) => setConfirmar(e.target.value)} className={INPUT} />
          </div>
          {error && (
            <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] font-medium">
              {error}
            </div>
          )}
          <Button type="submit" loading={enviando} className="h-10 justify-center">
            Crear cuenta
          </Button>
          <p className="m-0 text-[13px] text-text-muted text-center">
            ¿Ya tienes cuenta? <Link to="/login" className="text-primary font-medium">Iniciar sesión</Link>
          </p>
        </form>
      )}
    </AuthLayout>
  );
}
