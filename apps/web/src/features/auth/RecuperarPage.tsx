// Recuperar contraseña — siempre responde con el mismo mensaje neutro, exista o no la cuenta,
// para no filtrar qué correos están registrados (mismo criterio que Firebase para este flujo).
import { sendPasswordResetEmail } from 'firebase/auth';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { Button } from '@/components/ui/Button';
import { getFirebaseAuth } from '@/lib/firebase';

export function RecuperarPage() {
  const [correo, setCorreo] = useState('');
  const [ok, setOk] = useState(false);
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const auth = getFirebaseAuth();
    if (!auth) return;
    setEnviando(true);
    try {
      await sendPasswordResetEmail(auth, correo);
    } catch {
      // Sin importar el error (correo no existe, formato inválido, etc.), el mensaje es el mismo.
    } finally {
      setOk(true);
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
          <div className="text-lg font-semibold">Recuperar contraseña</div>

          {ok ? (
            <div className="flex flex-col gap-4">
              <div role="status" className="bg-primary-soft text-primary rounded-md px-2.5 py-3 text-sm font-medium">
                Si el correo existe, te enviamos un enlace para restablecer tu contraseña.
              </div>
              <Link to="/login" className="text-primary text-[13px] font-semibold">Volver a iniciar sesión</Link>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="rc-mail" className="text-xs font-semibold text-text-muted">Correo</label>
                <input
                  id="rc-mail"
                  type="email"
                  required
                  value={correo}
                  onChange={(e) => setCorreo(e.target.value)}
                  className="h-9 border border-border rounded px-2.5"
                />
              </div>
              <Button type="submit" loading={enviando} className="justify-center">
                Enviar enlace
              </Button>
              <Link to="/login" className="text-primary text-[13px] text-center">Volver a iniciar sesión</Link>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
