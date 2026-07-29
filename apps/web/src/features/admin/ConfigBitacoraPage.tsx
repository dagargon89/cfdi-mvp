// demo.html:724-781 (P11 Config·Bitácora) + lógica demo.html:1389-1394. Las pestañas son rutas reales
// (/admin/config, /admin/bitacora) — doc 09 §2 les asigna rutas separadas, a diferencia del `adminTab`
// en memoria del prototipo. La pestaña "Correo" (RF-NOT-01) se añadió tras el freeze (2026-07-28):
// configuración de correo saliente por UI en vez de variable de entorno.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router';
import { Button } from '@/components/ui/Button';
import { Paginador, type TamañoPagina } from '@/components/ui/Paginador';
import { useToast } from '@/components/ui/ToastProvider';
import { ApiError } from '@/lib/api';
import { api } from '@/lib/client';

export function ConfigBitacoraPage() {
  const { pathname } = useLocation();
  const enBitacora = pathname.startsWith('/admin/bitacora');
  const enCorreo = pathname.startsWith('/admin/correo');
  const [pagina, setPagina] = useState(1);
  const [porPagina, setPorPagina] = useState<TamañoPagina>(25);
  const perPageEfectivo = porPagina === 'todos' ? 100_000 : porPagina;

  const { data: config } = useQuery({ queryKey: ['config'], queryFn: () => api.listarConfiguracion(), enabled: !enBitacora && !enCorreo });
  const { data: bitacoraPage } = useQuery({
    queryKey: ['bitacora', pagina, perPageEfectivo],
    queryFn: () => api.listarBitacora({ page: pagina, per_page: perPageEfectivo }),
    enabled: enBitacora,
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-1 bg-surface-alt rounded-md p-0.5 w-fit">
        <Link
          to="/admin/config"
          className="h-[30px] rounded px-3.5 text-[13px] font-semibold inline-flex items-center"
          style={{ background: !enBitacora && !enCorreo ? 'var(--surface)' : 'transparent', color: !enBitacora && !enCorreo ? 'var(--primary)' : 'var(--text-muted)' }}
        >
          Configuración
        </Link>
        <Link
          to="/admin/correo"
          className="h-[30px] rounded px-3.5 text-[13px] font-semibold inline-flex items-center"
          style={{ background: enCorreo ? 'var(--surface)' : 'transparent', color: enCorreo ? 'var(--primary)' : 'var(--text-muted)' }}
        >
          Correo
        </Link>
        <Link
          to="/admin/bitacora"
          className="h-[30px] rounded px-3.5 text-[13px] font-semibold inline-flex items-center"
          style={{ background: enBitacora ? 'var(--surface)' : 'transparent', color: enBitacora ? 'var(--primary)' : 'var(--text-muted)' }}
        >
          Bitácora
        </Link>
      </div>

      {!enBitacora && !enCorreo && (
        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          <table>
            <caption className="sr-only">Parámetros de configuración</caption>
            <thead>
              <tr className="bg-surface-alt">
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Clave</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Ejercicio fiscal</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Valor</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Descripción</th>
              </tr>
            </thead>
            <tbody>
              {config?.map((c) => (
                <tr key={c.clave} className="border-t border-border h-10">
                  <td className="px-3 font-mono text-[13px]">{c.clave}</td>
                  <td className="px-3 font-mono text-xs text-text-muted">{c.ejercicio_fiscal}</td>
                  <td className="px-3 font-mono text-[13px] font-medium">{c.valor}</td>
                  <td className="px-3 py-2 text-xs text-text-muted text-pretty">{c.descripcion}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {enCorreo && <ConfigCorreoForm />}

      {enBitacora && (
        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          <table>
            <caption className="sr-only">Bitácora de acciones</caption>
            <thead>
              <tr className="bg-surface-alt">
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Fecha</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Actor</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Acción</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Entidad</th>
                <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Detalle</th>
              </tr>
            </thead>
            <tbody>
              {bitacoraPage?.data.map((b) => (
                <tr key={b.bitacora_id} className="border-t border-border h-10">
                  <td className="px-3 font-mono text-xs whitespace-nowrap">{b.created_at}</td>
                  <td className="px-3 font-mono text-xs">{b.actor}</td>
                  <td className="px-3 text-[13px] font-medium">{b.accion}</td>
                  <td className="px-3 font-mono text-xs text-text-muted">{b.entidad}</td>
                  <td className="px-3 py-2 font-mono text-xs text-text-muted">{JSON.stringify(b.detalle)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {bitacoraPage && (
            <Paginador
              page={pagina}
              perPage={bitacoraPage.per_page}
              total={bitacoraPage.total}
              onChange={setPagina}
              pageSize={porPagina}
              pageSizeOptions={[10, 25, 50, 100, 'todos']}
              onPageSizeChange={(v) => { setPorPagina(v); setPagina(1); }}
            />
          )}
        </div>
      )}
    </div>
  );
}

const INPUT_CLASS = 'h-9 border border-border rounded px-2.5';

function ConfigCorreoForm() {
  const { toast } = useToast();
  const qc = useQueryClient();
  const { data: actual } = useQuery({ queryKey: ['config-smtp'], queryFn: () => api.obtenerConfigSmtp() });

  const [host, setHost] = useState('');
  const [port, setPort] = useState(587);
  const [usuario, setUsuario] = useState('');
  const [password, setPassword] = useState('');
  const [remitente, setRemitente] = useState('');
  const [tls, setTls] = useState(true);
  const [correoPrueba, setCorreoPrueba] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Precarga el formulario con lo ya guardado (nunca la contraseña — el campo empieza vacío
  // y solo se sobreescribe si el usuario teclea una nueva, RF-NOT-01).
  useEffect(() => {
    if (!actual?.configurado) return;
    setHost(actual.host ?? '');
    setPort(actual.port ?? 587);
    setUsuario(actual.usuario ?? '');
    setRemitente(actual.remitente ?? '');
    setTls(actual.tls ?? true);
  }, [actual]);

  const datosFormulario = { host: host.trim(), port, usuario: usuario.trim(), password: password || undefined, remitente: remitente.trim(), tls };

  const guardar = useMutation({
    mutationFn: () => api.guardarConfigSmtp(datosFormulario),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['config-smtp'] });
      setPassword('');
      toast('Configuración de correo guardada', 'ok');
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'No se pudo guardar la configuración.'),
  });

  const probar = useMutation({
    mutationFn: () => api.probarConfigSmtp({ ...datosFormulario, correo_destino: correoPrueba.trim() }),
    onSuccess: () => toast(`Correo de prueba enviado a ${correoPrueba.trim()}`, 'ok'),
    onError: (e) => toast(e instanceof ApiError ? e.message : 'No se pudo enviar el correo de prueba.', 'error'),
  });

  return (
    <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-4 max-w-xl">
      <p className="text-[13px] text-text-muted m-0">
        Cuenta de correo que Hub CFDI usa para enviar las notificaciones (RF-NOT-01) — un correo normal
        (Gmail, Office 365, etc.) con una <strong>contraseña de aplicación</strong>, no tu contraseña de acceso habitual.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          guardar.mutate();
        }}
        className="flex flex-col gap-3.5"
      >
        <div className="grid grid-cols-[2fr_1fr] gap-3">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="smtp-host" className="text-xs font-semibold text-text-muted">Servidor SMTP</label>
            <input id="smtp-host" required value={host} onChange={(e) => setHost(e.target.value)} placeholder="smtp.gmail.com" className={INPUT_CLASS} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="smtp-port" className="text-xs font-semibold text-text-muted">Puerto</label>
            <input id="smtp-port" required type="number" value={port} onChange={(e) => setPort(Number(e.target.value))} className={INPUT_CLASS} />
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="smtp-usuario" className="text-xs font-semibold text-text-muted">Correo</label>
          <input id="smtp-usuario" required type="email" value={usuario} onChange={(e) => setUsuario(e.target.value)} placeholder="notificaciones@tudominio.com" className={INPUT_CLASS} />
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="smtp-password" className="text-xs font-semibold text-text-muted">Contraseña de aplicación</label>
          <input
            id="smtp-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={actual?.configurado ? '(sin cambios — ya hay una guardada)' : ''}
            className={INPUT_CLASS}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="smtp-remitente" className="text-xs font-semibold text-text-muted">Nombre del remitente</label>
          <input id="smtp-remitente" required value={remitente} onChange={(e) => setRemitente(e.target.value)} placeholder="Hub CFDI" className={INPUT_CLASS} />
        </div>

        <label className="flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={tls} onChange={(e) => setTls(e.target.checked)} />
          Usar TLS (recomendado — la mayoría de los proveedores lo requieren)
        </label>

        {error && <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px]">{error}</div>}

        <div className="flex gap-2 justify-end">
          <Button type="submit" loading={guardar.isPending} disabled={guardar.isPending}>
            Guardar
          </Button>
        </div>
      </form>

      <hr className="border-border" />

      <div className="flex flex-col gap-1.5">
        <label htmlFor="smtp-prueba" className="text-xs font-semibold text-text-muted">Enviar un correo de prueba a</label>
        <div className="flex gap-2">
          <input
            id="smtp-prueba"
            type="email"
            value={correoPrueba}
            onChange={(e) => setCorreoPrueba(e.target.value)}
            placeholder="tu-correo@ejemplo.com"
            className={`${INPUT_CLASS} flex-1`}
          />
          <Button
            type="button"
            variant="secondary"
            loading={probar.isPending}
            disabled={probar.isPending || !correoPrueba.trim() || !host.trim() || !usuario.trim() || !remitente.trim()}
            onClick={() => probar.mutate()}
          >
            Enviar prueba
          </Button>
        </div>
      </div>
    </div>
  );
}
