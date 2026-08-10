// Panel de la tarifa del ISR (Anexo 8 de la RMF) — Task 10 del plan de 2026-08-10 (tarifa ISR).
// Vive en su propio archivo porque `ConfiguracionFiscalPage.tsx` ya tenía ~700 líneas antes de
// esto; comparte con esa página el mismo invariante ("un valor sin confirmar no calcula"), el
// mismo chip de tres estados y los mismos helpers de formato (`ChipEstadoFiscal`, `fiscalComun`).
//
// Quién usa esto, y por qué eso decide casi todo lo que sigue (doc de diseño §3.1): **el dueño del
// Hub no es contador.** Es quien descarga el PDF del Anexo 8, lo importa, mira la rejilla de
// renglones y decide si confirma; su contador es un revisor externo que no tiene cuenta aquí. De
// ahí que:
// - las etiquetas se muestren **ya traducidas por el servidor** (`etiqueta`) y nunca el nombre del
//   enum de la columna (`DIAS_15`, `TARIFA_ISR`);
// - la tarifa que de verdad aplica a la nómina (`aplica_a_la_nomina`, resuelta por el servidor a
//   partir de lo que la nómina timbra de verdad, no una preferencia de esta pantalla) vaya primero
//   y expandida, y las demás queden colapsadas sin competir por la atención de nadie;
// - la comprobación contra un recibo real (§7.3 del diseño) se rotule como lo que es —una
//   comprobación de carga, no un dictamen fiscal— con el ISR que el propio CFDI ya trae al lado;
// - y los mensajes de error del servidor se muestren **tal cual**: ya vienen en español llano
//   diciendo qué hacer, y reescribirlos aquí solo los empobrecería.
//
// La regla que atraviesa toda la rejilla de renglones: `tasa_porcentaje` la calcula siempre el
// servidor y viaja junto a `tasa_excedente`. Esta pantalla **nunca** multiplica por 100 por su
// cuenta — es el único número de todo este panel donde equivocar la escala cambia el resultado
// exactamente por cien.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  ExternalLink,
  FileWarning,
  Info,
  Plus,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/ToastProvider';
import { ApiError } from '@/lib/api';
import type { ComprobacionTarifa, PeriodicidadTarifaIsr, TarifaIsr, TarifaIsrRenglon, TarifaIsrRenglonIn } from '@/lib/api';
import { api } from '@/lib/client';
import { ChipEstadoFiscal } from './ChipEstadoFiscal';
import { fechaHoraLegible, fechaLegible, importeLegible, partirFuente, type EstadoFiscal } from './fiscalComun';

const URL_MINISITIO_SAT = 'https://www.sat.gob.mx/consulta/85039/consulta-la-normatividad-vigente-y-sus-anexos';

/** El orden en que se listan las tarifas cuando ninguna (o más de una) "aplica a la nómina": el
 * mismo orden en que el Anexo 8 publica los rubros de nómina, de la periodicidad más corta a la
 * más larga y el cálculo del ejercicio al final. */
const ORDEN_PERIODICIDAD: PeriodicidadTarifaIsr[] = ['DIARIA', 'DIAS_7', 'DIAS_10', 'DIAS_15', 'MENSUAL', 'EJERCICIO'];

/** Catálogo `c_PeriodicidadPago` del CFDI — no es un valor fiscal ni cambia con el ejercicio, es
 * el catálogo del SAT que ya trae todo emisor de nómina. Solo hace falta para nombrar en español
 * la clave cruda que `periodicidades_sin_tarifa` devuelve ("03"); una clave sin traducir en
 * pantalla sería tan opaca como el nombre de un enum. */
const NOMBRE_PERIODICIDAD_CFDI: Record<string, string> = {
  '01': 'diaria',
  '02': 'semanal',
  '03': 'catorcenal',
  '04': 'quincenal',
  '05': 'mensual',
  '06': 'bimestral',
  '07': 'por unidad de obra',
  '08': 'por comisión',
  '09': 'por precio alzado',
  '10': 'decenal',
  '99': 'de otra periodicidad',
};

const TEXTO_ESTADO_TARIFA: Record<EstadoFiscal, string> = {
  confirmado: 'Confirmada · calcula',
  propuesto: 'Propuesta · sin confirmar',
  ausente: 'Sin capturar',
};

interface Aviso {
  tono: 'warning' | 'info';
  texto: string;
}

export function TarifaIsrPanel() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [aviso, setAviso] = useState<Aviso | null>(null);
  const [enCorreccion, setEnCorreccion] = useState<TarifaIsr | null>(null);
  const [enDescarte, setEnDescarte] = useState<TarifaIsr | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['tarifas-isr'],
    queryFn: () => api.listarTarifasIsr(),
  });

  const invalidar = () => qc.invalidateQueries({ queryKey: ['tarifas-isr'] });

  const importar = useMutation({
    mutationFn: (archivo: File) => api.importarTarifaIsr(archivo),
    onSuccess: (r) => {
      setAviso(null);
      invalidar();
      toast(`Anexo 8 importado: ${r.tarifas.length} tarifas de nómina quedaron sin confirmar, listas para revisar.`, 'ok');
    },
    onError: (e) => setAviso({ tono: 'warning', texto: e instanceof ApiError ? e.message : 'No se pudo importar el documento.' }),
  });

  const confirmar = useMutation({
    mutationFn: (tarifa: TarifaIsr) => api.confirmarTarifaIsr(tarifa.ejercicio, tarifa.periodicidad, tarifa.huella),
    onSuccess: (fila) => {
      setAviso(null);
      invalidar();
      toast(`${fila.etiqueta}: tarifa confirmada. Los informes de nómina ya calculan con ella.`, 'ok');
    },
    onError: (e) => {
      // 409 TARIFA_CAMBIO: la tarifa cambió entre que se pintó la pantalla y el clic (otra
      // persona la corrigió, o llegó una reimportación). Se recarga y se muestra el mensaje del
      // servidor tal cual — ya dice qué hacer, reescribirlo no ayudaría.
      if (e instanceof ApiError && e.codigo === 'TARIFA_CAMBIO') invalidar();
      setAviso({ tono: 'warning', texto: e instanceof ApiError ? e.message : 'No se pudo confirmar la tarifa.' });
    },
  });

  if (isLoading) return <p className="text-text-muted text-[13px]">Cargando la tarifa del ISR…</p>;
  if (isError) {
    return (
      <div role="alert" className="bg-danger-soft text-danger rounded-md px-3 py-2 text-[13px]">
        {error instanceof ApiError ? error.message : 'No se pudo cargar la tarifa del ISR.'}
      </div>
    );
  }

  // La tarifa que aplica a la nómina primero (la decide el servidor, no una preferencia de esta
  // pantalla); las demás en el mismo orden en que el Anexo 8 las publica.
  const tarifas = [...(data?.tarifas ?? [])].sort((a, b) => {
    if (a.aplica_a_la_nomina !== b.aplica_a_la_nomina) return a.aplica_a_la_nomina ? -1 : 1;
    const oa = ORDEN_PERIODICIDAD.indexOf(a.periodicidad);
    const ob = ORDEN_PERIODICIDAD.indexOf(b.periodicidad);
    if (oa !== ob) return oa - ob;
    return b.ejercicio - a.ejercicio;
  });
  const periodicidadesSinTarifa = data?.periodicidades_sin_tarifa ?? [];

  function abrirSelector() {
    fileRef.current?.click();
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-2">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <h3 className="m-0 text-[15px] font-semibold">Tarifa del ISR de sueldos y salarios (Anexo 8)</h3>
            <p className="m-0 mt-1 text-[13px] text-text-muted text-pretty max-w-[78ch]">
              La tarifa del ISR se publica cada año en el <strong>Anexo 8 de la Resolución Miscelánea Fiscal</strong>, en
              el Diario Oficial de la Federación de finales de diciembre. Hub CFDI lee las tablas de ese documento
              oficial —nunca las calcula ni las descarga sola—, y como con el resto de la configuración fiscal,{' '}
              <strong>una tarifa sin confirmar no calcula</strong>: los informes de nómina la tratan como si no
              existiera hasta que una persona la revisa y la confirma.
            </p>
          </div>
          <div className="flex flex-col items-end gap-1.5 shrink-0">
            {/* input de archivo oculto: el botón visible dispara el selector nativo (mismo patrón
                que `subirEfirma` en EfirmaPage, sin el paso intermedio de mostrar el nombre). */}
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => {
                const archivo = e.target.files?.[0] ?? null;
                e.target.value = '';
                if (archivo) importar.mutate(archivo);
              }}
            />
            <Button type="button" onClick={abrirSelector} disabled={importar.isPending} loading={importar.isPending}>
              <Upload className="size-4" aria-hidden /> {tarifas.length === 0 ? 'Importar Anexo 8' : 'Reimportar Anexo 8'}
            </Button>
            <a
              href={URL_MINISITIO_SAT}
              target="_blank"
              rel="noreferrer noopener"
              className="text-[12px] font-semibold text-primary inline-flex items-center gap-1"
            >
              Minisitio de normatividad del SAT <ExternalLink className="size-3" aria-hidden />
            </a>
          </div>
        </div>
      </div>

      {aviso && (
        <div
          role="alert"
          className={`rounded-md px-3 py-2.5 text-[13px] flex items-start gap-2 ${aviso.tono === 'warning' ? 'bg-warning-soft text-warning' : 'bg-info-soft text-info'}`}
        >
          <AlertTriangle className="size-4 shrink-0 mt-0.5" aria-hidden />
          <span className="text-pretty">{aviso.texto}</span>
        </div>
      )}

      {tarifas.length === 0 ? (
        <div className="bg-surface border border-dashed border-border rounded-lg p-6 flex flex-col items-center gap-2 text-center">
          <FileWarning className="size-6 text-text-muted" aria-hidden />
          <p className="m-0 text-[13px] text-text-muted text-pretty max-w-[60ch]">
            Todavía no se ha importado ninguna tarifa. Descarga el Anexo 8 vigente del minisitio de normatividad del
            SAT e impórtalo aquí: Hub CFDI extrae las tablas de nómina del documento y las deja listas para revisar.
          </p>
          <Button type="button" onClick={abrirSelector} disabled={importar.isPending} loading={importar.isPending}>
            <Upload className="size-4" aria-hidden /> Importar Anexo 8
          </Button>
        </div>
      ) : (
        <>
          {periodicidadesSinTarifa.length > 0 && <AvisoSinTarifa claves={periodicidadesSinTarifa} />}

          <div className="flex flex-col gap-2.5">
            {tarifas.map((tarifa) => (
              <TarjetaTarifa
                key={`${tarifa.ejercicio}-${tarifa.periodicidad}`}
                tarifa={tarifa}
                confirmando={
                  confirmar.isPending &&
                  confirmar.variables?.ejercicio === tarifa.ejercicio &&
                  confirmar.variables?.periodicidad === tarifa.periodicidad
                }
                onConfirmar={() => { setAviso(null); confirmar.mutate(tarifa); }}
                onCorregir={() => { setAviso(null); setEnCorreccion(tarifa); }}
                onDescartar={() => { setAviso(null); setEnDescarte(tarifa); }}
              />
            ))}
          </div>
        </>
      )}

      {enCorreccion && (
        <ModalCorregirTarifa
          tarifa={enCorreccion}
          onCerrar={() => setEnCorreccion(null)}
          onGuardado={(fila) => {
            setEnCorreccion(null);
            invalidar();
            toast(`${fila.etiqueta}: renglones guardados. Queda sin confirmar hasta que la revises y la confirmes.`, 'ok');
          }}
        />
      )}

      {enDescarte && (
        <ModalDescartarTarifa
          tarifa={enDescarte}
          onCerrar={() => setEnDescarte(null)}
          onDescartado={() => {
            const etiqueta = enDescarte.etiqueta;
            setEnDescarte(null);
            invalidar();
            toast(`${etiqueta}: importación descartada.`, 'ok');
          }}
        />
      )}
    </section>
  );
}

/** El aviso de la regla B-09.R1: enterarse aquí de que una periodicidad no tiene tarifa es mejor
 * que enterarse cuando un informe de nómina salga rotulado. */
function AvisoSinTarifa({ claves }: { claves: string[] }) {
  const nombres = claves.map((c) => NOMBRE_PERIODICIDAD_CFDI[c] ?? `de la periodicidad ${c}`);
  const listado = nombres.length === 1 ? nombres[0] : `${nombres.slice(0, -1).join(', ')} ni ${nombres[nombres.length - 1]}`;
  const plural = nombres.length > 1;
  return (
    <p
      role="status"
      className="m-0 text-[12px] text-text-strong text-pretty max-w-[78ch] flex items-start gap-1.5 bg-info-soft rounded-md px-3 py-2"
    >
      <Info className="size-3.5 shrink-0 mt-0.5 text-info" aria-hidden />
      <span>
        El Anexo 8 no publica tarifa <strong>{listado}</strong>, y tu nómina sí la timbra con {plural ? 'esas periodicidades' : 'esa periodicidad'}.
        Con {plural ? 'ellas' : 'ella'}, el cálculo se hace proporcionando la tarifa mensual y queda rotulado en el
        informe.
      </span>
    </p>
  );
}

// --- una tarjeta por tarifa ----------------------------------------------------------------------

function TarjetaTarifa({
  tarifa,
  confirmando,
  onConfirmar,
  onCorregir,
  onDescartar,
}: {
  tarifa: TarifaIsr;
  confirmando: boolean;
  onConfirmar: () => void;
  onCorregir: () => void;
  onDescartar: () => void;
}) {
  // La que aplica a la nómina arranca expandida; las demás, colapsadas — no compiten por la
  // atención de quien solo necesita revisar la que de verdad usa.
  const [expandida, setExpandida] = useState(tarifa.aplica_a_la_nomina);
  const estado: EstadoFiscal = tarifa.confirmada ? 'confirmado' : 'propuesto';
  const { texto: fuenteTexto, url: fuenteUrl } = partirFuente(tarifa.fuente);

  function alternar() {
    setExpandida((v) => !v);
  }

  return (
    <article className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3">
      {/* Encabezado plegable. Es un `<div role="button">` con teclado propio, no un `<button>`
          real, porque el contenido incluye un encabezado (`h5`) y un párrafo — contenido de
          bloque que el modelo de contenido de `<button>` no admite; anidarlo ahí produciría HTML
          inválido y algunos lectores de pantalla lo aplanarían. */}
      <div
        role="button"
        tabIndex={0}
        onClick={alternar}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            alternar();
          }
        }}
        aria-expanded={expandida}
        className="flex items-start justify-between gap-4 flex-wrap cursor-pointer w-full"
      >
        <div className="min-w-0 flex items-start gap-2">
          {expandida ? (
            <ChevronDown className="size-4 shrink-0 mt-0.5 text-text-muted" aria-hidden />
          ) : (
            <ChevronRight className="size-4 shrink-0 mt-0.5 text-text-muted" aria-hidden />
          )}
          <div className="min-w-0">
            <h5 className="m-0 text-[14px] font-semibold flex items-center gap-2 flex-wrap">
              {tarifa.etiqueta}
              <span className="text-[12px] font-normal text-text-muted">· ejercicio {tarifa.ejercicio}</span>
            </h5>
            {tarifa.aplica_a_la_nomina && (
              <p className="m-0 mt-0.5 text-[12px] font-semibold text-primary">Es la que aplica a tu nómina</p>
            )}
          </div>
        </div>
        <ChipEstadoFiscal estado={estado} texto={TEXTO_ESTADO_TARIFA[estado]} />
      </div>

      {expandida && (
        <div className="flex flex-col gap-3">
          {/* Encabezado citado literal del documento oficial. */}
          <blockquote className="m-0 border-l-4 border-border pl-3 py-1 text-[12px] text-text-muted italic text-pretty">
            “{tarifa.encabezado}”
          </blockquote>

          <p className="m-0 text-[12px] text-text-muted text-pretty">
            <strong>{tarifa.origen === 'IMPORTADA' ? 'Importada del documento oficial' : 'Corregida a mano'}:</strong>{' '}
            {fuenteTexto}{' '}
            {fuenteUrl && (
              <a href={fuenteUrl} target="_blank" rel="noreferrer noopener" className="text-primary font-semibold inline-flex items-center gap-1">
                Ver la fuente <ExternalLink className="size-3" aria-hidden />
              </a>
            )}
            {tarifa.documento_sha256 && (
              <>
                {' '}
                · huella del documento <code className="font-mono text-[11px] break-all">{tarifa.documento_sha256}</code>
              </>
            )}
            {' '}· importada el {fechaHoraLegible(tarifa.importado_en)}
          </p>

          {tarifa.difiere_del_documento && (
            <p className="m-0 text-[12px] bg-warning-soft text-warning rounded-md px-3 py-2 text-pretty flex items-start gap-2">
              <AlertTriangle className="size-3.5 shrink-0 mt-0.5" aria-hidden />
              <span>
                <strong>Los renglones de esta tarifa se corrigieron a mano</strong> y ya no son exactamente los del
                último documento importado. Revísalos contra el Anexo 8 antes de confirmar.
              </span>
            </p>
          )}

          <RejillaRenglones renglones={tarifa.renglones} />

          <ComprobacionCarga comprobacion={tarifa.comprobacion} renglones={tarifa.renglones} />

          {tarifa.confirmada ? (
            <p className="m-0 text-[13px] text-success">
              Confirmada por <strong>{tarifa.confirmado_por}</strong>
              {tarifa.confirmado_en ? ` el ${fechaHoraLegible(tarifa.confirmado_en)}` : ''}. Los informes de nómina ya
              calculan el ISR con esta tarifa.
            </p>
          ) : (
            <p className="m-0 text-[13px] text-warning text-pretty">
              <strong>Mientras no la confirmes:</strong> los informes de nómina no calculan el ISR con esta tarifa.
            </p>
          )}

          <div className="flex gap-2 flex-wrap">
            {!tarifa.confirmada && (
              <Button type="button" disabled={confirmando} loading={confirmando} onClick={onConfirmar}>
                Confirmar esta tarifa
              </Button>
            )}
            <Button type="button" variant="secondary" onClick={onCorregir}>
              {tarifa.confirmada ? 'Corregir' : 'Corregir los renglones'}
            </Button>
            {!tarifa.confirmada && (
              <Button type="button" variant="danger" onClick={onDescartar}>
                <Trash2 className="size-4" aria-hidden /> Descartar
              </Button>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

// --- la rejilla de renglones -----------------------------------------------------------------------

function RejillaRenglones({ renglones }: { renglones: TarifaIsrRenglon[] }) {
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-[13px] border-collapse min-w-[560px]">
        <thead>
          <tr className="text-left text-[11px] font-semibold text-text-muted uppercase tracking-wide border-b border-border">
            <th className="py-1.5 px-1 font-semibold">Renglón</th>
            <th className="py-1.5 px-1 font-semibold">Límite inferior</th>
            <th className="py-1.5 px-1 font-semibold">Límite superior</th>
            <th className="py-1.5 px-1 font-semibold">Cuota fija</th>
            <th className="py-1.5 px-1 font-semibold">Tasa sobre excedente</th>
          </tr>
        </thead>
        <tbody>
          {renglones.map((r) => (
            <tr key={r.renglon} className="border-b border-border last:border-0">
              <td className="py-1.5 px-1 font-mono text-text-muted">{r.renglon}</td>
              <td className="py-1.5 px-1 font-mono">${importeLegible(r.limite_inferior)}</td>
              <td className="py-1.5 px-1 font-mono">
                {r.limite_superior === null ? 'En adelante' : `$${importeLegible(r.limite_superior)}`}
              </td>
              <td className="py-1.5 px-1 font-mono">${importeLegible(r.cuota_fija)}</td>
              <td className="py-1.5 px-1">
                {/* El porcentaje es la columna PRINCIPAL —como lo publica el SAT y como lo lee un
                    contador—, y lo calcula siempre el servidor: esta pantalla nunca multiplica
                    `tasa_excedente` por 100 por su cuenta. La fracción queda como dato secundario,
                    para quien sí conoce el Anexo 8 y quiere comparar contra la columna guardada. */}
                <span className="font-mono font-semibold">{r.tasa_porcentaje} %</span>{' '}
                <span className="font-mono text-[11px] text-text-muted">({importeLegible(r.tasa_excedente)})</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- la comprobación con un recibo real ---------------------------------------------------------

function ComprobacionCarga({ comprobacion, renglones }: { comprobacion: ComprobacionTarifa | null; renglones: TarifaIsrRenglon[] }) {
  if (!comprobacion) {
    return (
      <p className="m-0 text-[12px] text-text-muted text-pretty bg-surface-alt rounded-md px-3 py-2 flex items-start gap-1.5">
        <Info className="size-3.5 shrink-0 mt-0.5" aria-hidden />
        <span>
          No hay ningún recibo de nómina timbrado con esta periodicidad para comprobar la carga contra un caso real.
          Puedes confirmar revisando los renglones contra el documento oficial de arriba.
        </span>
      </p>
    );
  }

  // El porcentaje del renglón que aplicó al recibo **se busca**, no se calcula: `comprobacion`
  // solo trae la fracción (igual que los renglones de la tarifa), pero el mismo renglón ya vive en
  // `renglones` con su `tasa_porcentaje` calculado por el servidor. Cruzarlos por número de
  // renglón evita la única multiplicación por 100 que este panel no puede hacer por su cuenta.
  const filaRenglon = renglones.find((r) => r.renglon === comprobacion.renglon) ?? null;

  const periodo =
    comprobacion.fecha_inicial_pago && comprobacion.fecha_final_pago
      ? `del ${fechaLegible(comprobacion.fecha_inicial_pago)} al ${fechaLegible(comprobacion.fecha_final_pago)}`
      : 'sin fechas de pago en el CFDI';

  return (
    <div className="bg-surface-alt border border-border rounded-md p-3 flex flex-col gap-1.5">
      <p className="m-0 text-[12px] font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
        <ClipboardCheck className="size-3.5" aria-hidden /> Comprobación de carga contra un recibo real — no es un dictamen fiscal
      </p>
      <p className="m-0 text-[12px] text-text-muted">
        Recibo {periodo}
        {comprobacion.num_empleado ? ` · empleado ${comprobacion.num_empleado}` : ''}
        {comprobacion.dias_pagados ? ` · ${comprobacion.dias_pagados} días pagados` : ''}
      </p>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-x-4 gap-y-1.5 text-[13px] mt-1">
        <CampoComprobacion nombre="Gravado del recibo (del propio CFDI)">${importeLegible(comprobacion.gravado)}</CampoComprobacion>
        <CampoComprobacion nombre="Renglón de la tarifa que le toca">
          {comprobacion.renglon}{' '}
          <span className="text-[11px] font-normal text-text-muted">
            (límite inferior ${importeLegible(comprobacion.limite_inferior)}{filaRenglon ? ` · ${filaRenglon.tasa_porcentaje} %` : ''})
          </span>
        </CampoComprobacion>
        <CampoComprobacion nombre="ISR con la tarifa que estás confirmando">${importeLegible(comprobacion.isr_calculado)}</CampoComprobacion>
        <CampoComprobacion nombre="ISR que dice el CFDI">${importeLegible(comprobacion.isr_timbrado)}</CampoComprobacion>
        <CampoComprobacion nombre="Diferencia">${importeLegible(comprobacion.diferencia)}</CampoComprobacion>
      </div>
      {comprobacion.advertencias.length > 0 && (
        <ul className="m-0 mt-1 pl-4 flex flex-col gap-0.5 text-[12px] text-text-muted list-disc">
          {comprobacion.advertencias.map((a, i) => (
            <li key={i} className="text-pretty">{a}</li>
          ))}
        </ul>
      )}
      <p className="m-0 mt-1 text-[11px] text-text-muted text-pretty">
        Una diferencia pequeña es normal: el ISR timbrado puede incluir subsidio al empleo, ajustes del periodo o el
        procedimiento del artículo 174 del Reglamento. Esta comprobación detecta errores de carga —una tarifa de otro
        año o de otra periodicidad daría una diferencia enorme, no de pesos—; no dictamina si el recibo está bien
        calculado.
      </p>
    </div>
  );
}

function CampoComprobacion({ nombre, children }: { nombre: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className="text-[11px] font-semibold text-text-muted uppercase tracking-wide">{nombre}</span>
      <span className="font-mono font-semibold">{children}</span>
    </div>
  );
}

// --- corrección de renglones ----------------------------------------------------------------------

const INPUT_CLASS = 'h-8 border border-border rounded px-2 bg-surface';
const PATRON_DECIMAL = /^\d+(\.\d+)?$/;

/** Un renglón en edición. Vive como texto libre mientras se captura —igual que el resto de los
 * formularios fiscales de esta pestaña— y solo se convierte al `TarifaIsrRenglonIn` del contrato
 * al guardar, tras la validación de forma. `id` es una clave estable para React y para React solo:
 * no viaja al servidor, que numera los renglones por su posición en la lista. */
interface RenglonBorrador {
  id: string;
  limite_inferior: string;
  limite_superior: string; // '' significa "en adelante" (null en el contrato)
  cuota_fija: string;
  tasa_excedente: string;
}

function renglonABorrador(r: TarifaIsrRenglon): RenglonBorrador {
  return {
    id: `renglon-${r.renglon}`,
    limite_inferior: importeLegible(r.limite_inferior),
    limite_superior: r.limite_superior === null ? '' : importeLegible(r.limite_superior),
    cuota_fija: importeLegible(r.cuota_fija),
    tasa_excedente: importeLegible(r.tasa_excedente),
  };
}

let siguienteIdBorrador = 0;
function nuevoBorrador(): RenglonBorrador {
  siguienteIdBorrador += 1;
  return { id: `nuevo-${siguienteIdBorrador}`, limite_inferior: '', limite_superior: '', cuota_fija: '', tasa_excedente: '' };
}

/** Corrección manual de una tarifa completa. Manda la lista **completa** de renglones, no un
 * diff, porque el servidor vuelve a comprobar las seis reglas del Anexo I.1 sobre la tarifa
 * entera: mover un límite puede romper la continuidad con su vecino. Esta ventana solo valida lo
 * evidente (formato de número, un único renglón sin techo y que sea el último) — las seis reglas
 * las decide el servidor, que es donde viven y donde no se pueden esquivar. */
function ModalCorregirTarifa({
  tarifa,
  onCerrar,
  onGuardado,
}: {
  tarifa: TarifaIsr;
  onCerrar: () => void;
  onGuardado: (fila: TarifaIsr) => void;
}) {
  const [filas, setFilas] = useState<RenglonBorrador[]>(() => tarifa.renglones.map(renglonABorrador));
  const [error, setError] = useState<string | null>(null);

  const guardar = useMutation({
    mutationFn: (renglones: TarifaIsrRenglonIn[]) => api.corregirTarifaIsr(tarifa.ejercicio, tarifa.periodicidad, renglones),
    onSuccess: onGuardado,
    // El mensaje se muestra tal cual: si una de las seis reglas del Anexo I.1 no pasa, el
    // servidor ya dice cuál renglón y por qué, en español llano.
    onError: (e) => setError(e instanceof ApiError ? e.message : 'No se pudieron guardar los renglones.'),
  });

  function actualizar(id: string, campo: keyof Omit<RenglonBorrador, 'id'>, valor: string) {
    setFilas((fs) => fs.map((f) => (f.id === id ? { ...f, [campo]: valor } : f)));
  }

  function agregarFila() {
    setFilas((fs) => [...fs, nuevoBorrador()]);
  }

  function quitarFila(id: string) {
    setFilas((fs) => (fs.length > 1 ? fs.filter((f) => f.id !== id) : fs));
  }

  function moverFila(id: string, delta: number) {
    setFilas((fs) => {
      const i = fs.findIndex((f) => f.id === id);
      const j = i + delta;
      if (i === -1 || j < 0 || j >= fs.length) return fs;
      const copia = [...fs];
      [copia[i], copia[j]] = [copia[j], copia[i]];
      return copia;
    });
  }

  function intentarGuardar() {
    setError(null);
    for (const f of filas) {
      if (!PATRON_DECIMAL.test(f.limite_inferior.trim()) || !PATRON_DECIMAL.test(f.cuota_fija.trim()) || !PATRON_DECIMAL.test(f.tasa_excedente.trim())) {
        setError('Escribe el límite inferior, la cuota fija y la tasa como números, con punto decimal y sin separadores de miles (por ejemplo 368.10 o 0.192000).');
        return;
      }
      if (f.limite_superior.trim() !== '' && !PATRON_DECIMAL.test(f.limite_superior.trim())) {
        setError('El límite superior tiene que ser un número, o quedar vacío para "en adelante".');
        return;
      }
    }
    const sinTecho = filas.filter((f) => f.limite_superior.trim() === '');
    if (sinTecho.length !== 1) {
      setError(
        sinTecho.length === 0
          ? 'Ningún renglón quedó sin límite superior: el último tiene que quedar "en adelante" (el campo vacío).'
          : 'Más de un renglón quedó sin límite superior: solo el último puede quedar "en adelante".',
      );
      return;
    }
    if (filas[filas.length - 1].limite_superior.trim() !== '') {
      setError('El renglón sin límite superior tiene que ser el último de la tabla.');
      return;
    }
    guardar.mutate(
      filas.map((f, i) => ({
        renglon: i + 1,
        limite_inferior: f.limite_inferior.trim(),
        limite_superior: f.limite_superior.trim() === '' ? null : f.limite_superior.trim(),
        cuota_fija: f.cuota_fija.trim(),
        tasa_excedente: f.tasa_excedente.trim(),
      })),
    );
  }

  return (
    <Modal titleId="titulo-corregir-tarifa" onClose={onCerrar} ancho="amplio">
      <h3 id="titulo-corregir-tarifa" className="m-0 text-base font-semibold text-pretty">
        Corregir los renglones de {tarifa.etiqueta} · ejercicio {tarifa.ejercicio}
      </h3>
      <p className="m-0 text-[13px] text-text-muted text-pretty">
        Se manda la tabla <strong>completa</strong>, no solo lo que cambia. Lo que guardes queda{' '}
        <strong>sin confirmar</strong>, aunque la tarifa ya estuviera confirmada: quien la confirmó revisó otros
        renglones.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-[13px] border-collapse min-w-[640px]">
          <thead>
            <tr className="text-left text-[11px] font-semibold text-text-muted uppercase tracking-wide border-b border-border">
              <th className="py-1.5 px-1">#</th>
              <th className="py-1.5 px-1">Límite inferior</th>
              <th className="py-1.5 px-1">Límite superior (vacío = "en adelante")</th>
              <th className="py-1.5 px-1">Cuota fija</th>
              <th className="py-1.5 px-1">Tasa (fracción, no %)</th>
              <th className="py-1.5 px-1" />
            </tr>
          </thead>
          <tbody>
            {filas.map((f, i) => (
              <tr key={f.id} className="border-b border-border last:border-0 align-top">
                <td className="py-1.5 px-1 font-mono text-text-muted">{i + 1}</td>
                <td className="py-1.5 px-1">
                  <input
                    aria-label={`Límite inferior del renglón ${i + 1}`}
                    value={f.limite_inferior}
                    onChange={(e) => actualizar(f.id, 'limite_inferior', e.target.value)}
                    inputMode="decimal"
                    placeholder="0.01"
                    className={`${INPUT_CLASS} font-mono w-28`}
                  />
                </td>
                <td className="py-1.5 px-1">
                  <input
                    aria-label={`Límite superior del renglón ${i + 1}`}
                    value={f.limite_superior}
                    onChange={(e) => actualizar(f.id, 'limite_superior', e.target.value)}
                    inputMode="decimal"
                    placeholder="en adelante"
                    className={`${INPUT_CLASS} font-mono w-28`}
                  />
                </td>
                <td className="py-1.5 px-1">
                  <input
                    aria-label={`Cuota fija del renglón ${i + 1}`}
                    value={f.cuota_fija}
                    onChange={(e) => actualizar(f.id, 'cuota_fija', e.target.value)}
                    inputMode="decimal"
                    placeholder="0.00"
                    className={`${INPUT_CLASS} font-mono w-24`}
                  />
                </td>
                <td className="py-1.5 px-1">
                  <input
                    aria-label={`Tasa sobre excedente del renglón ${i + 1}`}
                    value={f.tasa_excedente}
                    onChange={(e) => actualizar(f.id, 'tasa_excedente', e.target.value)}
                    inputMode="decimal"
                    placeholder="0.192000"
                    className={`${INPUT_CLASS} font-mono w-28`}
                  />
                </td>
                <td className="py-1.5 px-1 whitespace-nowrap">
                  <button type="button" onClick={() => moverFila(f.id, -1)} disabled={i === 0} aria-label={`Subir renglón ${i + 1}`} className="p-1 disabled:opacity-30 cursor-pointer">
                    <ArrowUp className="size-3.5" aria-hidden />
                  </button>
                  <button type="button" onClick={() => moverFila(f.id, 1)} disabled={i === filas.length - 1} aria-label={`Bajar renglón ${i + 1}`} className="p-1 disabled:opacity-30 cursor-pointer">
                    <ArrowDown className="size-3.5" aria-hidden />
                  </button>
                  <button type="button" onClick={() => quitarFila(f.id)} disabled={filas.length <= 1} aria-label={`Quitar renglón ${i + 1}`} className="p-1 text-danger disabled:opacity-30 cursor-pointer">
                    <X className="size-3.5" aria-hidden />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <Button type="button" variant="secondary" onClick={agregarFila}>
          <Plus className="size-4" aria-hidden /> Agregar renglón
        </Button>
      </div>

      <p className="m-0 text-[11px] text-text-muted text-pretty">
        La tasa se captura como <strong>fracción decimal</strong>, tal como la guarda la columna — igual que en el
        documento oficial: 19.2&nbsp;% se escribe <code className="font-mono">0.192000</code>, no{' '}
        <code className="font-mono">19.2</code>.
      </p>

      {error && <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] text-pretty">{error}</div>}

      <div className="flex gap-2 justify-end">
        <Button type="button" variant="secondary" onClick={onCerrar}>Cancelar</Button>
        <Button type="button" loading={guardar.isPending} disabled={guardar.isPending} onClick={intentarGuardar}>
          Guardar sin confirmar
        </Button>
      </div>
    </Modal>
  );
}

// --- descartar una tarifa sin confirmar --------------------------------------------------------

function ModalDescartarTarifa({
  tarifa,
  onCerrar,
  onDescartado,
}: {
  tarifa: TarifaIsr;
  onCerrar: () => void;
  onDescartado: () => void;
}) {
  const [error, setError] = useState<string | null>(null);

  const descartar = useMutation({
    mutationFn: () => api.descartarTarifaIsr(tarifa.ejercicio, tarifa.periodicidad),
    onSuccess: onDescartado,
    onError: (e) => setError(e instanceof ApiError ? e.message : 'No se pudo descartar la tarifa.'),
  });

  return (
    <Modal titleId="titulo-descartar-tarifa" onClose={onCerrar}>
      <h3 id="titulo-descartar-tarifa" className="m-0 text-base font-semibold text-pretty">
        Descartar {tarifa.etiqueta} · ejercicio {tarifa.ejercicio}
      </h3>
      <p className="m-0 text-[13px] text-text-muted text-pretty">
        Se borra esta importación o corrección, que todavía no está confirmada. Sirve para limpiar una tabla cargada
        por error. Para reemplazar una tarifa <strong>ya confirmada</strong>, en cambio, hay que corregirla a mano o
        reimportar el documento correcto encima: una tarifa activa no se borra, se sustituye.
      </p>

      {error && <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] text-pretty">{error}</div>}

      <div className="flex gap-2 justify-end">
        <Button type="button" variant="secondary" onClick={onCerrar}>Cancelar</Button>
        <Button type="button" variant="danger" loading={descartar.isPending} disabled={descartar.isPending} onClick={() => descartar.mutate()}>
          Descartar
        </Button>
      </div>
    </Modal>
  );
}
