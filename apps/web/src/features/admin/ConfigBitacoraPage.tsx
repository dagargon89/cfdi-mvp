// demo.html:724-781 (P11 Config·Bitácora) + lógica demo.html:1389-1394. Las pestañas son rutas reales
// (/admin/config, /admin/bitacora) — doc 09 §2 les asigna rutas separadas, a diferencia del `adminTab`
// en memoria del prototipo. La pestaña "Correo" (RF-NOT-01) se añadió tras el freeze (2026-07-28):
// configuración de correo saliente por UI en vez de variable de entorno.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router';
import { Button } from '@/components/ui/Button';
import { ConfirmarModal } from '@/components/ui/ConfirmarModal';
import { Paginador, type TamañoPagina } from '@/components/ui/Paginador';
import { Switch } from '@/components/ui/Switch';
import { useToast } from '@/components/ui/ToastProvider';
import { ApiError, type Automatizaciones } from '@/lib/api';
import { api } from '@/lib/client';
import { ConfiguracionFiscalPage } from './ConfiguracionFiscalPage';

// Tareas automáticas (beat) que el admin puede apagar/prender, con lo que pasa al desactivarlas.
const AUTOMATIZACIONES: { key: keyof Automatizaciones; nombre: string; queHace: string; consecuencia: string }[] = [
  {
    key: 'sync_diaria',
    nombre: 'Descarga diaria del SAT',
    queHace: 'Baja automáticamente tus comprobantes nuevos del SAT cada día.',
    consecuencia: 'Dejarán de descargarse comprobantes nuevos por sí solos; tendrás que iniciar cada descarga manualmente desde la sección Descargas.',
  },
  {
    key: 'lista_69b',
    nombre: 'Actualización de la lista 69-B (EFOS)',
    queHace: 'Actualiza a diario la lista negra del SAT (69-B) y la cruza con tus comprobantes.',
    consecuencia: 'Dejará de actualizarse la lista 69-B y de cruzarse con tus comprobantes; podrías no enterarte de emisores que entren a la lista negra.',
  },
  {
    key: 're_verificar',
    nombre: 'Re-verificación de vigencia',
    queHace: 'Revisa periódicamente si tus comprobantes vigentes fueron cancelados después.',
    consecuencia: 'Dejará de revisarse si un comprobante fue cancelado tras emitirse; su estatus podría quedar desactualizado.',
  },
  {
    key: 'limpieza',
    nombre: 'Limpieza automática de almacenamiento',
    queHace: 'Libera disco a diario borrando archivos temporales: exports de descarga masiva viejos y paquetes crudos del SAT ya indexados. Nunca borra tus XML fiscales.',
    consecuencia: 'El servidor dejará de liberar espacio solo; los exports y paquetes descargados se irán acumulando en disco.',
  },
];

export function ConfigBitacoraPage() {
  const { pathname } = useLocation();
  const enBitacora = pathname.startsWith('/admin/bitacora');
  const enCorreo = pathname.startsWith('/admin/correo');
  const enFiscal = pathname.startsWith('/admin/fiscal');
  const [pagina, setPagina] = useState(1);
  const [porPagina, setPorPagina] = useState<TamañoPagina>(25);
  const perPageEfectivo = porPagina === 'todos' ? 100_000 : porPagina;

  const qc = useQueryClient();
  const { toast } = useToast();
  const enConfig = !enBitacora && !enCorreo && !enFiscal;

  const { data: autos } = useQuery({ queryKey: ['automatizaciones'], queryFn: () => api.obtenerAutomatizaciones(), enabled: enConfig });
  const { data: bitacoraPage } = useQuery({
    queryKey: ['bitacora', pagina, perPageEfectivo],
    queryFn: () => api.listarBitacora({ page: pagina, per_page: perPageEfectivo }),
    enabled: enBitacora,
  });

  const [confirmar, setConfirmar] = useState<null | (typeof AUTOMATIZACIONES)[number]>(null);
  const guardarAutos = useMutation({
    mutationFn: (next: Automatizaciones) => api.guardarAutomatizaciones(next),
    onSuccess: (data) => { qc.setQueryData(['automatizaciones'], data); toast('Automatizaciones actualizadas', 'ok'); },
    onError: () => toast('No se pudo guardar el cambio', 'error'),
  });

  function alternar(item: (typeof AUTOMATIZACIONES)[number], activoActual: boolean) {
    if (!autos) return;
    if (activoActual) setConfirmar(item); // desactivar -> pedir confirmación
    else guardarAutos.mutate({ ...autos, [item.key]: true }); // activar -> directo
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-1 bg-surface-alt rounded-md p-0.5 w-fit">
        {[
          { href: '/admin/config', etiqueta: 'Configuración', activa: enConfig },
          { href: '/admin/fiscal', etiqueta: 'Fiscal', activa: enFiscal },
          { href: '/admin/correo', etiqueta: 'Correo', activa: enCorreo },
          { href: '/admin/bitacora', etiqueta: 'Bitácora', activa: enBitacora },
        ].map((t) => (
          <Link
            key={t.href}
            to={t.href}
            aria-current={t.activa ? 'page' : undefined}
            className="h-[30px] rounded px-3.5 text-[13px] font-semibold inline-flex items-center"
            style={{ background: t.activa ? 'var(--surface)' : 'transparent', color: t.activa ? 'var(--primary)' : 'var(--text-muted)' }}
          >
            {t.etiqueta}
          </Link>
        ))}
      </div>

      {enConfig && (
        <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-1">
          <h3 className="m-0 text-[15px] font-semibold">Automatizaciones</h3>
          <p className="m-0 text-xs text-text-muted">Tareas que Hub CFDI ejecuta solo, en segundo plano. Puedes apagarlas cuando lo necesites.</p>
          <div className="mt-3 flex flex-col divide-y divide-border">
            {AUTOMATIZACIONES.map((item) => {
              const activo = autos ? autos[item.key] : true;
              return (
                <div key={item.key} className="flex items-start justify-between gap-4 py-3.5 first:pt-0 last:pb-0">
                  <div className="min-w-0">
                    <div className="text-[14px] font-semibold">{item.nombre}</div>
                    <p className="m-0 mt-0.5 text-[13px] text-text-muted text-pretty">{item.queHace}</p>
                    {autos && !activo && (
                      <p className="m-0 mt-1.5 text-[12px] text-warning text-pretty">Desactivada · {item.consecuencia}</p>
                    )}
                  </div>
                  <Switch checked={activo} disabled={!autos || guardarAutos.isPending} onChange={() => alternar(item, activo)} label={item.nombre} />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {enFiscal && <ConfiguracionFiscalPage />}

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

      {confirmar && (
        <ConfirmarModal
          titulo={`Desactivar "${confirmar.nombre}"`}
          mensaje={<>{confirmar.consecuencia} ¿Seguro que quieres desactivarla?</>}
          textoConfirmar="Desactivar"
          tono="danger"
          onCancelar={() => setConfirmar(null)}
          onConfirmar={() => {
            if (autos) guardarAutos.mutate({ ...autos, [confirmar.key]: false });
            setConfirmar(null);
          }}
        />
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
