// demo.html:293-384 (P4 Bóveda e.firma) + lógica demo.html:1291-1337.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, Clock, ShieldCheck, ShieldX } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { ConfirmarRfcModal } from '@/components/ui/ConfirmarRfcModal';
import { useToast } from '@/components/ui/ToastProvider';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import { api } from '@/lib/client';
import { ApiError } from '@/lib/api';
import { diasParaVencer, fechaCorta, umbralVigenciaDias } from '@/lib/domain';

const DEMO_CONTROLS = import.meta.env.VITE_DEMO_CONTROLS === 'true';
type Escenario = 'exito' | 'EFIRMA_NO_ABRE' | 'RFC_NO_COINCIDE' | 'EFIRMA_VENCIDA';

export function EfirmaPage() {
  const { empresa, puedeMutar } = useEmpresaCtx();
  const { toast } = useToast();
  const qc = useQueryClient();

  const { data: efirma } = useQuery({ queryKey: ['efirma', empresa.empresa_id], queryFn: () => api.obtenerEfirma(empresa.empresa_id) });
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: () => api.listarConfiguracion() });
  const umbral = umbralVigenciaDias(config ?? []);

  const [cerNombre, setCerNombre] = useState('Sin archivo seleccionado');
  const [keyNombre, setKeyNombre] = useState('Sin archivo seleccionado');
  const [cerFile, setCerFile] = useState<File | null>(null);
  const [keyFile, setKeyFile] = useState<File | null>(null);
  const [password, setPassword] = useState('');
  const [escenario, setEscenario] = useState<Escenario>('exito');
  const [error, setError] = useState<{ codigo: string; mensaje: string } | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [modalAbierto, setModalAbierto] = useState(false);

  const subir = useMutation({
    mutationFn: () =>
      api.subirEfirma(empresa.empresa_id, {
        cer: cerFile as File,
        key: keyFile as File,
        password,
        escenarioDemo: DEMO_CONTROLS ? escenario : undefined,
      }),
    onSuccess: (r) => {
      setPassword('');
      setError(null);
      setOk(`e.firma registrada. Serie ${r.num_serie}, vigente hasta ${r.not_after.slice(0, 10)}.`);
      toast('e.firma registrada correctamente', 'ok');
      qc.invalidateQueries({ queryKey: ['efirma', empresa.empresa_id] });
      qc.invalidateQueries({ queryKey: ['empresas'] });
    },
    onError: (e) => {
      setPassword('');
      if (e instanceof ApiError) setError({ codigo: e.codigo, mensaje: e.message });
      toast('No se pudo registrar la e.firma', 'error');
    },
  });

  const eliminar = useMutation({
    mutationFn: () => api.eliminarEfirma(empresa.empresa_id),
    onSuccess: () => {
      setModalAbierto(false);
      toast('e.firma eliminada de la bóveda', 'ok');
      qc.invalidateQueries({ queryKey: ['efirma', empresa.empresa_id] });
      qc.invalidateQueries({ queryKey: ['empresas'] });
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setOk(null);
    subir.mutate();
  }

  const dias = efirma ? diasParaVencer(efirma.not_after) : null;
  const estadoInfo =
    dias === null ? null : dias <= 0
      ? { texto: 'Vencida', fg: 'text-danger', bg: 'bg-danger-soft', Icon: ShieldX }
      : dias <= umbral
        ? { texto: 'Por vencer', fg: 'text-warning', bg: 'bg-warning-soft', Icon: Clock }
        : { texto: 'Vigente', fg: 'text-success', bg: 'bg-success-soft', Icon: ShieldCheck };

  return (
    <div className="flex flex-col gap-4 max-w-[920px]">
      <div>
        <h2 className="m-0 text-[22px] font-bold">Bóveda de e.firma</h2>
        <p className="mt-1 mb-0 text-text-muted text-pretty">
          La e.firma se cifra en el servidor; el prototipo nunca la re-muestra ni la almacena en el navegador.
        </p>
      </div>

      {efirma && estadoInfo && (
        <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3">
          <div className="flex items-center gap-2.5">
            <span className={`size-[30px] rounded-md grid place-items-center ${estadoInfo.fg} ${estadoInfo.bg}`}>
              <estadoInfo.Icon className="size-[17px]" aria-hidden />
            </span>
            <h3 className="m-0 text-[15px] font-semibold flex-1">e.firma registrada</h3>
            <span className={`text-xs font-semibold rounded-md px-2 py-0.5 ${estadoInfo.fg} ${estadoInfo.bg}`}>{estadoInfo.texto}</span>
          </div>
          <dl className="m-0 grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            <div className="min-w-0"><dt className="text-xs text-text-muted font-semibold">Número de serie</dt><dd className="mt-0.5 mb-0 font-mono text-[13px] break-all">{efirma.num_serie}</dd></div>
            <div className="min-w-0"><dt className="text-xs text-text-muted font-semibold">Vigente desde</dt><dd className="mt-0.5 mb-0 font-mono text-[13px] break-all">{fechaCorta(efirma.not_before)}</dd></div>
            <div className="min-w-0"><dt className="text-xs text-text-muted font-semibold">Vigente hasta</dt><dd className="mt-0.5 mb-0 font-mono text-[13px] break-all">{fechaCorta(efirma.not_after)}</dd></div>
            <div className="min-w-0"><dt className="text-xs text-text-muted font-semibold">Días restantes</dt><dd className={`mt-0.5 mb-0 font-mono text-[13px] break-all ${estadoInfo.fg}`}>{dias} días</dd></div>
          </dl>
          {puedeMutar && (
            <div className="flex gap-2 border-t border-border pt-3">
              <Button variant="danger" onClick={() => setModalAbierto(true)}>Eliminar e.firma</Button>
            </div>
          )}
        </div>
      )}

      {puedeMutar && (
        <form onSubmit={onSubmit} className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3.5">
          <h3 className="m-0 text-[15px] font-semibold">{efirma ? 'Reemplazar e.firma' : 'Dar de alta e.firma'}</h3>
          <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <div className="min-w-0 flex flex-col gap-1.5">
              <label htmlFor="ef-cer" className="text-xs font-semibold text-text-muted">Certificado (.cer)</label>
              <input
                id="ef-cer" type="file" accept=".cer" aria-describedby="ef-cer-h"
                onChange={(e) => { const f = e.target.files?.[0] ?? null; setCerFile(f); setCerNombre(f?.name ?? 'Sin archivo seleccionado'); }}
                className="border border-border rounded px-2 py-1.5 text-[13px] min-w-0"
              />
              <span id="ef-cer-h" className="text-xs text-text-muted break-all">{cerNombre}</span>
            </div>
            <div className="min-w-0 flex flex-col gap-1.5">
              <label htmlFor="ef-key" className="text-xs font-semibold text-text-muted">Llave privada (.key)</label>
              <input
                id="ef-key" type="file" accept=".key" aria-describedby="ef-key-h"
                onChange={(e) => { const f = e.target.files?.[0] ?? null; setKeyFile(f); setKeyNombre(f?.name ?? 'Sin archivo seleccionado'); }}
                className="border border-border rounded px-2 py-1.5 text-[13px] min-w-0"
              />
              <span id="ef-key-h" className="text-xs text-text-muted break-all">{keyNombre}</span>
            </div>
            <div className="min-w-0 flex flex-col gap-1.5">
              <label htmlFor="ef-pass" className="text-xs font-semibold text-text-muted">Contraseña de la llave</label>
              <input
                id="ef-pass" type="password" autoComplete="new-password" aria-describedby="ef-pass-h"
                value={password} onChange={(e) => setPassword(e.target.value)}
                className="h-9 border border-border rounded px-2.5 min-w-0"
              />
              <span id="ef-pass-h" className="text-xs text-text-muted">No se guarda en el navegador ni se vuelve a mostrar.</span>
            </div>
          </div>

          {DEMO_CONTROLS && (
            <div className="border border-dashed border-border rounded-md px-3 py-2.5 flex items-center gap-2.5 flex-wrap">
              <label htmlFor="ef-esc" className="text-xs font-semibold text-text-muted">Escenario del demo</label>
              <select id="ef-esc" value={escenario} onChange={(e) => setEscenario(e.target.value as Escenario)} className="h-[30px] border border-border rounded px-2 text-[13px]">
                <option value="exito">Éxito — e.firma válida</option>
                <option value="EFIRMA_NO_ABRE">Error EFIRMA_NO_ABRE</option>
                <option value="RFC_NO_COINCIDE">Error RFC_NO_COINCIDE</option>
                <option value="EFIRMA_VENCIDA">Error EFIRMA_VENCIDA</option>
              </select>
              <span className="text-xs text-text-muted flex-1 min-w-[200px] text-pretty">Solo para la sesión de validación: fuerza la respuesta del backend simulado.</span>
            </div>
          )}

          {error && (
            <div role="alert" className="bg-danger-soft rounded-md px-2.5 py-2.5 flex gap-2 text-danger">
              <AlertCircle className="size-[17px] shrink-0 mt-px" aria-hidden />
              <span className="min-w-0 flex flex-col gap-0.5">
                <strong className="text-[13px] font-mono break-all">{error.codigo}</strong>
                <span className="text-[13px] text-pretty break-words">{error.mensaje}</span>
              </span>
            </div>
          )}
          {ok && (
            <div role="status" className="bg-success-soft rounded-md px-2.5 py-2.5 flex gap-2 text-success">
              <ShieldCheck className="size-[17px] shrink-0 mt-px" aria-hidden />
              <span className="min-w-0 text-[13px] text-pretty break-words">{ok}</span>
            </div>
          )}

          <div className="flex gap-2 items-center">
            <Button type="submit" loading={subir.isPending} disabled={subir.isPending}>
              {subir.isPending ? 'Validando…' : efirma ? 'Reemplazar e.firma' : 'Registrar e.firma'}
            </Button>
            <span className="text-xs text-text-muted">Se registra en bitácora como <span className="font-mono">alta_efirma</span>.</span>
          </div>
        </form>
      )}

      {!puedeMutar && (
        <div className="bg-surface-alt rounded-lg px-4 py-3.5 text-text-muted text-[13px]">
          Tu rol de consulta no permite dar de alta ni reemplazar la e.firma.
        </div>
      )}

      {modalAbierto && (
        <ConfirmarRfcModal
          titulo="Eliminar e.firma"
          descripcion={
            <>
              Los jobs programados de esta empresa fallarán hasta que se registre una nueva e.firma. Escribe el RFC{' '}
              <strong className="font-mono text-text-strong">{empresa.rfc}</strong> para confirmar.
            </>
          }
          rfc={empresa.rfc}
          onCancelar={() => setModalAbierto(false)}
          onConfirmar={() => eliminar.mutate()}
        />
      )}
    </div>
  );
}
