// Sustituye el login simulado del demo (demo.html:32-159) por Firebase Auth real (email/contraseña).
// Tras autenticar, resuelve el usuario local con api.me() — el equivalente de lo que hará el backend
// real con el uid de Firebase (doc 02 §4.1). Si el correo no tiene usuario local, se cierra la sesión
// de Firebase y se muestra un error, en vez de dejar pasar a alguien sin registro en el sistema.
import { onAuthStateChanged, signInWithEmailAndPassword, signOut } from 'firebase/auth';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { ApiError } from '@/lib/api';
import type { ApiClient } from '@/lib/api';
import { api } from '@/lib/client';
import { firebaseConfigured, getFirebaseAuth } from '@/lib/firebase';

type Usuario = Awaited<ReturnType<ApiClient['me']>>;

interface AuthApi {
  firebaseConfigured: boolean;
  loading: boolean;
  usuario: Usuario | null;
  loginError: string | null;
  needsBootstrap: boolean | null;
  setNeedsBootstrap: (v: boolean) => void;
  login: (correo: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthApi | null>(null);

const FIREBASE_ERROR_MENSAJE: Record<string, string> = {
  'auth/invalid-credential': 'Correo o contraseña incorrectos.',
  'auth/invalid-email': 'Ese correo no tiene un formato válido.',
  'auth/too-many-requests': 'Demasiados intentos. Espera un momento y vuelve a intentar.',
  'auth/user-disabled': 'Esta cuenta está deshabilitada.',
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [needsBootstrap, setNeedsBootstrap] = useState<boolean | null>(null);

  useEffect(() => {
    api.estadoBootstrap()
      .then((r) => setNeedsBootstrap(r.needs_bootstrap))
      .catch(() => setNeedsBootstrap(false)); // ante fallo, no bloquear el login
  }, []);

  useEffect(() => {
    if (!firebaseConfigured) {
      setLoading(false);
      return;
    }
    const auth = getFirebaseAuth();
    if (!auth) return;
    return onAuthStateChanged(auth, async (fbUser) => {
      if (!fbUser) {
        setUsuario(null);
        setLoading(false);
        return;
      }
      try {
        setUsuario(await api.me());
      } catch (e) {
        setLoginError(e instanceof ApiError ? 'No existe un usuario de Hub CFDI para este correo en este entorno.' : 'No se pudo iniciar sesión.');
        await signOut(auth);
        setUsuario(null);
      } finally {
        setLoading(false);
      }
    });
  }, []);

  async function login(correo: string, password: string) {
    const auth = getFirebaseAuth();
    if (!auth) return;
    setLoginError(null);
    try {
      await signInWithEmailAndPassword(auth, correo, password);
    } catch (e) {
      const codigo = e instanceof Error && 'code' in e ? String((e as { code: string }).code) : '';
      setLoginError(FIREBASE_ERROR_MENSAJE[codigo] ?? 'No se pudo iniciar sesión.');
      throw e;
    }
  }

  async function logout() {
    const auth = getFirebaseAuth();
    if (auth) await signOut(auth);
    setUsuario(null);
  }

  return (
    <AuthContext.Provider value={{ firebaseConfigured, loading, usuario, loginError, needsBootstrap, setNeedsBootstrap, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth debe usarse dentro de <AuthProvider>');
  return ctx;
}
