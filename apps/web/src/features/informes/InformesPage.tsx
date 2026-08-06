// Sección Informes (doc spec §7.2) — catálogo de informes con formulario generado a partir del
// JSON Schema de `parametros`. Ningún parámetro de un informe concreto (p. ej. B-02) está
// hardcodeado aquí: las fases 2-3 solo agregan entradas al catálogo del backend, esta pantalla
// no cambia. El sondeo de tarea → descarga sigue el mismo patrón que ComprobantesPage/DescargasPage.
import { useQuery } from '@tanstack/react-query';
import { FileSpreadsheet } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/ToastProvider';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import { ApiError } from '@/lib/api';
import type { InformeCatalogo } from '@/lib/api';
import { api } from '@/lib/client';

/** Subconjunto de JSON Schema que necesitamos leer de `InformeCatalogo.parametros` — el backend
 * puede mandar más llaves (title, description, etc.), aquí solo se usan las que arman el formulario. */
interface PropiedadParametro {
  type?: string;
  format?: string;
  enum?: string[];
  default?: unknown;
}
interface ParametrosSchema {
  properties?: Record<string, PropiedadParametro>;
  required?: string[];
}

type ValorParametro = string | boolean;

const INTERVALO_SONDEO_MS = 300;
/** Tope del sondeo. El pre-vuelo del ETL corre dentro de la tarea del informe, así que la primera
 * generación posterior a subir `ETL_VERSION` puede tardar minutos de verdad. Pero el bucle tiene
 * que terminar en algún momento: una pestaña girando sin fin invita a recargar y relanzar, y dos
 * generaciones en paralelo son dos pre-vuelos concurrentes sobre los mismos comprobantes. */
const ESPERA_MAXIMA_MS = 10 * 60 * 1000;

/** Convierte `fecha_desde` → "Fecha desde" — no hay título en el schema, solo la llave. */
function etiquetar(clave: string): string {
  const texto = clave.replace(/_/g, ' ');
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

function valorInicial(prop: PropiedadParametro): ValorParametro {
  if (prop.type === 'boolean') return typeof prop.default === 'boolean' ? prop.default : false;
  if (prop.enum) return typeof prop.default === 'string' ? prop.default : (prop.enum[0] ?? '');
  return typeof prop.default === 'string' ? prop.default : '';
}

export function InformesPage() {
  const { empresa } = useEmpresaCtx();
  const { toast } = useToast();

  const { data, isLoading, isError } = useQuery({ queryKey: ['informes'], queryFn: () => api.listarInformes() });
  const informes = data ?? [];

  const [claveSeleccionada, setClaveSeleccionada] = useState<string | null>(null);
  const informeSeleccionado = informes.find((i) => i.clave === claveSeleccionada) ?? null;
  const schema = (informeSeleccionado?.parametros ?? {}) as ParametrosSchema;
  const propiedades = schema.properties ?? {};
  const requeridos = schema.required ?? [];

  const [valores, setValores] = useState<Record<string, ValorParametro>>({});
  const [generando, setGenerando] = useState(false);
  const [error, setError] = useState<{ codigo: string; mensaje: string } | null>(null);

  // Al elegir un informe (o cambiar de catálogo tras un refetch), reinicia el formulario a los
  // defaults del schema — no depende de qué informe sea, solo de sus `properties`.
  useEffect(() => {
    if (!claveSeleccionada || !data) {
      setValores({});
      return;
    }
    const informe = data.find((i) => i.clave === claveSeleccionada);
    if (!informe) return;
    const props = ((informe.parametros ?? {}) as ParametrosSchema).properties ?? {};
    const iniciales: Record<string, ValorParametro> = {};
    for (const [clave, prop] of Object.entries(props)) iniciales[clave] = valorInicial(prop);
    setValores(iniciales);
    setError(null);
  }, [claveSeleccionada, data]);

  const grupos = informes.reduce<Record<string, InformeCatalogo[]>>((acc, informe) => {
    (acc[informe.grupo] ??= []).push(informe);
    return acc;
  }, {});

  const faltanRequeridos = requeridos.some((clave) => {
    const v = valores[clave];
    return v === undefined || v === '';
  });

  const desenmascarado = propiedades['enmascarar_datos_personales'] !== undefined && valores['enmascarar_datos_personales'] === false;

  async function esperarTarea(tareaId: string): Promise<{ estado: 'pendiente' | 'completada' | 'fallida' | 'expirada'; url?: string }> {
    let estado: 'pendiente' | 'completada' | 'fallida' = 'pendiente';
    let url: string | undefined;
    const limite = Date.now() + ESPERA_MAXIMA_MS;
    while (estado === 'pendiente') {
      if (Date.now() > limite) return { estado: 'expirada' };
      await new Promise((r) => setTimeout(r, INTERVALO_SONDEO_MS));
      const t = await api.estadoTarea(tareaId);
      estado = t.estado;
      url = t.descarga_url;
    }
    return { estado, url };
  }

  async function generar() {
    if (!informeSeleccionado) return;
    setError(null);
    setGenerando(true);
    toast('Generando informe…', 'info');
    try {
      const { tarea_id } = await api.generarInforme(empresa.empresa_id, informeSeleccionado.clave, valores);
      const { estado, url } = await esperarTarea(tarea_id);
      if (estado === 'completada' && url) {
        window.open(url, '_blank');
        toast(`${url.split('/').pop() ?? 'informe'} listo`, 'ok');
      } else if (estado === 'expirada') {
        // Sigue corriendo en el servidor: relanzarla ahora solo duplicaría el trabajo.
        toast('El informe sigue generándose en el servidor. Espera unos minutos antes de volver a lanzarlo.', 'info');
      } else {
        toast('No se pudo generar el informe', 'error');
      }
    } catch (e) {
      if (e instanceof ApiError) {
        setError({ codigo: `${e.status} · ${e.codigo}`, mensaje: e.message });
      } else {
        toast('No se pudo generar el informe', 'error');
      }
    } finally {
      setGenerando(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4" style={{ gridTemplateColumns: 'minmax(260px, 340px) 1fr' }}>
        <div className="flex flex-col gap-3">
          {isLoading && <div className="bg-surface border border-border rounded-lg p-4 text-[13px] text-text-muted">Cargando catálogo de informes…</div>}
          {isError && <div role="alert" className="bg-danger-soft text-danger rounded-md px-3 py-2.5 text-[13px]">No se pudo cargar el catálogo de informes.</div>}
          {!isLoading && !isError && informes.length === 0 && (
            <div className="bg-surface border border-border rounded-lg p-4 text-[13px] text-text-muted">Todavía no hay informes disponibles.</div>
          )}
          {Object.entries(grupos).map(([grupo, items]) => (
            <div key={grupo} className="bg-surface border border-border rounded-lg overflow-hidden">
              <div className="px-4 py-2.5 border-b border-border bg-surface-alt">
                <h3 className="m-0 text-xs font-semibold text-text-muted">Grupo {grupo}</h3>
              </div>
              <div className="flex flex-col">
                {items.map((informe) => (
                  <button
                    key={informe.clave}
                    type="button"
                    onClick={() => setClaveSeleccionada(informe.clave)}
                    className="text-left border-0 border-t border-border first:border-t-0 px-4 py-3 flex flex-col gap-1 cursor-pointer w-full"
                    style={{ background: informe.clave === claveSeleccionada ? 'var(--primary-soft)' : 'transparent' }}
                  >
                    <span className="text-[13px] font-semibold">{informe.nombre}</span>
                    <span className="text-xs text-text-muted text-pretty">{informe.descripcion}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3.5">
          {!informeSeleccionado && <div className="text-[13px] text-text-muted">Elige un informe de la lista para configurar sus parámetros.</div>}

          {informeSeleccionado && (
            <>
              <div>
                <h3 className="m-0 text-[15px] font-semibold">{informeSeleccionado.nombre}</h3>
                <p className="m-0 mt-1 text-xs text-text-muted text-pretty">{informeSeleccionado.descripcion}</p>
              </div>

              <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                {Object.entries(propiedades).map(([clave, prop]) => {
                  const id = `inf-${clave}`;
                  const requerido = requeridos.includes(clave);

                  if (prop.type === 'boolean') {
                    return (
                      <label key={clave} className="inline-flex items-center gap-2 text-[13px] cursor-pointer self-end pb-1.5">
                        <input
                          type="checkbox"
                          id={id}
                          checked={valores[clave] === true}
                          onChange={(e) => setValores((v) => ({ ...v, [clave]: e.target.checked }))}
                        />
                        {etiquetar(clave)}
                      </label>
                    );
                  }

                  if (prop.enum) {
                    return (
                      <div key={clave} className="flex flex-col gap-1.5">
                        <label htmlFor={id} className="text-xs font-semibold text-text-muted">{etiquetar(clave)}</label>
                        <select
                          id={id}
                          value={typeof valores[clave] === 'string' ? valores[clave] : ''}
                          onChange={(e) => setValores((v) => ({ ...v, [clave]: e.target.value }))}
                          className="h-9 border border-border rounded px-2"
                        >
                          {prop.enum.map((opcion) => (
                            <option key={opcion} value={opcion}>{opcion}</option>
                          ))}
                        </select>
                      </div>
                    );
                  }

                  return (
                    <div key={clave} className="flex flex-col gap-1.5">
                      <label htmlFor={id} className="text-xs font-semibold text-text-muted">
                        {etiquetar(clave)}{requerido && ' *'}
                      </label>
                      <input
                        id={id}
                        type={prop.format === 'date' ? 'date' : 'text'}
                        required={requerido}
                        value={typeof valores[clave] === 'string' ? valores[clave] : ''}
                        onChange={(e) => setValores((v) => ({ ...v, [clave]: e.target.value }))}
                        className="h-9 border border-border rounded px-2"
                      />
                    </div>
                  );
                })}
              </div>

              {desenmascarado && (
                <div role="alert" className="bg-danger-soft text-danger rounded-md px-3 py-2.5 text-[13px] text-pretty">
                  Se generará con CURP, NSS y cuenta bancaria a la vista. Queda registrado en la bitácora.
                </div>
              )}

              {error && (
                <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2.5 flex flex-col gap-0.5">
                  <strong className="text-[13px] font-mono">{error.codigo}</strong>
                  <span className="text-[13px] text-pretty">{error.mensaje}</span>
                </div>
              )}

              <div>
                <Button onClick={generar} loading={generando} disabled={generando || faltanRequeridos}>
                  <FileSpreadsheet className="size-[15px]" aria-hidden /> Generar
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
