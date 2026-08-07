// Pestaña "Fiscal" de /admin/config (ruta real /admin/fiscal — ver el comentario de cabecera de
// ConfigBitacoraPage.tsx: las pestañas de esta pantalla son rutas, no estado en memoria).
//
// Lo que esta pantalla tiene que comunicar, y es el motivo de que exista:
// **un valor sin confirmar no calcula.** El sistema puede *proponer* un valor —sembrado de una
// fuente oficial o sincronizado desde Banxico— pero hasta que una persona lo confirma, los
// informes lo tratan como ausente. De ahí que los tres estados (confirmado, propuesto, ausente)
// tengan que distinguirse de un vistazo y que "Confirmar" sea un solo clic: es la acción que
// convierte una alarma en un dato usable.
//
// Lo que NO es: el volcado crudo de parámetros clave/valor que se eliminó de esta misma página en
// julio (commit 1845a68), con razón. Aquí cada valor se presenta por lo que significa —"Unidad de
// Medida y Actualización (UMA) diaria", no `UMA_DIARIA`—, con su vigencia en fechas legibles, su
// fuente como liga, y **qué se degrada** mientras no esté confirmado.
//
// La pestaña tiene **dos secciones y un solo invariante**: los valores de `param_fiscal` (aquí) y
// las marcas de exención del art. 93 (`MarcasPercepcionSection`). Comparten los tres estados, el
// chip y el formato de fechas — ver `fiscalComun.ts` y `ChipEstadoFiscal.tsx`.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, AlertTriangle, CalendarClock, CheckCircle2, ExternalLink, History, Wrench } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/ToastProvider';
import { ApiError } from '@/lib/api';
import type { AlertaVigencia, MotivoAlertaVigencia, ParametroFiscal } from '@/lib/api';
import { api } from '@/lib/client';
import { ChipEstadoFiscal } from './ChipEstadoFiscal';
import { MarcasPercepcionSection } from './MarcasPercepcionSection';
import { fechaHoraLegible, fechaLegible, type EstadoFiscal } from './fiscalComun';

// --- catálogo de presentación ---------------------------------------------------------------
// El backend manda la clave; el significado en español llano vive aquí. `siFalta` es lo que se
// degrada mientras el valor no esté confirmado — decir solo "falta" no le sirve a nadie.
interface FichaClave {
  nombre: string;
  grupo: string;
  queEs: string;
  cuandoCambia: string;
  deDondeSale: string;
  siFalta: string;
}

const GRUPO_UMA = 'Unidad de Medida y Actualización (UMA)';
const GRUPO_SM = 'Salarios mínimos';
const GRUPO_TC = 'Tipo de cambio';

const CATALOGO: Record<string, FichaClave> = {
  UMA_DIARIA: {
    nombre: 'UMA diaria',
    grupo: GRUPO_UMA,
    queEs: 'La base con la que se calcula casi toda exención del artículo 93 de la LISR ("15 días de UMA", "90 UMA por año de servicio").',
    cuandoCambia: 'Cada año, el 1 de febrero.',
    deDondeSale: 'Boletín anual de la UMA del INEGI.',
    siFalta: 'Los informes de nómina no pueden calcular el tope exento de cada percepción: dejan vacías las columnas de tope y exceso (nunca en cero) y avisan por qué.',
  },
  UMA_MENSUAL: {
    nombre: 'UMA mensual',
    grupo: GRUPO_UMA,
    queEs: 'La UMA diaria por 30.4. Se usa en las exenciones y topes que la ley expresa en meses.',
    cuandoCambia: 'Cada año, el 1 de febrero, junto con la UMA diaria.',
    deDondeSale: 'Boletín anual de la UMA del INEGI (viene en el mismo documento).',
    siFalta: 'Los topes que la ley expresa en meses de UMA no se pueden calcular y quedan vacíos.',
  },
  UMA_ANUAL: {
    nombre: 'UMA anual',
    grupo: GRUPO_UMA,
    queEs: 'El tope conjunto de las exenciones de previsión social del penúltimo párrafo del artículo 93 de la LISR es 1 UMA anual por trabajador.',
    cuandoCambia: 'Cada año, el 1 de febrero, junto con la UMA diaria.',
    deDondeSale: 'Boletín anual de la UMA del INEGI (viene en el mismo documento).',
    siFalta: 'El tope conjunto de previsión social no se puede aplicar, y sin él las exenciones de esos conceptos se verían más altas de lo que la ley permite.',
  },
  SALARIO_MINIMO_GENERAL: {
    nombre: 'Salario mínimo general diario',
    grupo: GRUPO_SM,
    queEs: 'El mínimo del resto del país (fuera de la Zona Libre de la Frontera Norte). Base de las exenciones que la ley expresa en días de salario mínimo.',
    cuandoCambia: 'Cada año, el 1 de enero.',
    deDondeSale: 'Resolución del CONASAMI publicada en el Diario Oficial de la Federación.',
    siFalta: 'B-10 no puede comprobar si un salario quedó por debajo del mínimo, y las exenciones que se calculan en días de salario mínimo quedan vacías.',
  },
  SALARIO_MINIMO_ZLFN: {
    nombre: 'Salario mínimo diario de la Zona Libre de la Frontera Norte',
    grupo: GRUPO_SM,
    queEs: 'El mínimo de los municipios fronterizos del norte. Es muy distinto del general, así que la zona salarial de cada organización decide cuál aplica.',
    cuandoCambia: 'Cada año, el 1 de enero.',
    deDondeSale: 'Resolución del CONASAMI publicada en el Diario Oficial de la Federación.',
    siFalta: 'Las organizaciones de la zona fronteriza no pueden validarse contra su mínimo real; usar el general daría falsos negativos.',
  },
  TIPO_CAMBIO_USD: {
    nombre: 'Tipo de cambio del dólar (FIX)',
    grupo: GRUPO_TC,
    queEs: 'El tipo de cambio para solventar obligaciones en moneda extranjera, por fecha.',
    cuandoCambia: 'Todos los días hábiles.',
    deDondeSale: 'Serie SF43718 del Banco de México (se puede sincronizar automáticamente).',
    siFalta: 'Los comprobantes en dólares no se pueden convertir a pesos y quedan fuera de los importes comparables.',
  },
};

const ORDEN_GRUPOS = [GRUPO_UMA, GRUPO_SM, GRUPO_TC];

function ficha(clave: string): FichaClave {
  return (
    CATALOGO[clave] ?? {
      nombre: clave,
      grupo: 'Otros valores',
      queEs: 'Valor fiscal que los informes usan en sus cálculos.',
      cuandoCambia: 'Sin fecha de actualización conocida.',
      deDondeSale: 'Publicación oficial correspondiente.',
      siFalta: 'Los cálculos que dependen de este valor quedan vacíos.',
    }
  );
}

const ORIGEN_TEXTO: Record<string, string> = {
  SEMILLA: 'Lo trajo Hub CFDI de su fuente oficial',
  MANUAL: 'Lo capturó una persona',
  SINCRONIZADO: 'Lo bajó Hub CFDI automáticamente de su fuente',
};

// --- formato ---------------------------------------------------------------------------------
// `fechaLegible` y `fechaHoraLegible` viven en `fiscalComun.ts`: las usan las dos secciones.

function hoyISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** La fuente es texto libre que suele traer la URL del boletín o del DOF dentro. Se parte para
 * poder ofrecerla como liga: revisar el valor contra su fuente es lo que se le pide a quien
 * confirma, y obligarlo a copiar una URL a mano es pedirle que no lo haga. */
function partirFuente(fuente: string): { texto: string; url: string | null } {
  const encontrado = /(https?:\/\/[^\s)]+)/.exec(fuente);
  if (!encontrado) return { texto: fuente, url: null };
  return { texto: fuente.replace(encontrado[1], '').replace(/[—–-]\s*$/, '').trim(), url: encontrado[1] };
}

/** El importe se muestra tal cual llega (cadena): `Number()` perdería la escala almacenada. Solo
 * se recortan los ceros decimales de relleno ("117.310000" → "117.31"), que no son información. */
function importeLegible(valor: string): string {
  if (!valor.includes('.')) return valor;
  const recortado = valor.replace(/0+$/, '').replace(/\.$/, '');
  return recortado === '' ? valor : recortado;
}

// --- chip de estado ---------------------------------------------------------------------------
// El chip vive en `ChipEstadoFiscal.tsx` (lo comparten las dos secciones). Aquí solo los textos:
// lo que se confirma en esta sección es un importe.
const TEXTO_ESTADO: Record<EstadoFiscal, string> = {
  confirmado: 'Confirmado · calcula',
  propuesto: 'Propuesto · sin confirmar',
  ausente: 'Sin capturar',
};

function ChipEstado({ estado }: { estado: EstadoFiscal }) {
  return <ChipEstadoFiscal estado={estado} texto={TEXTO_ESTADO[estado]} />;
}

// --- la alarma de vigencia ---------------------------------------------------------------------
// Seis motivos que **no se presentan igual a propósito**. Tres hablan de un valor y piden acciones
// distintas —capturar / un clic / actualizar el ejercicio—; los otros tres no hablan de ningún
// valor sino de la maquinaria que los mantiene al día. Mezclarlos haría que la alerta mintiera: un
// catálogo que no se puede abrir no es un valor "ausente" ni pide ir a capturar nada, y quien lo
// leyera en la misma lista buscaría una cifra que no existe.
//
// Por eso van en dos bloques con encabezado propio, y los de maquinaria en tono neutro: casi
// siempre son "falta configurar o actualizar algo en el servidor", no "el sistema está averiado".

const MOTIVOS_DE_VALOR: MotivoAlertaVigencia[] = ['AUSENTE', 'SIN_CONFIRMAR', 'CADUCADO'];

const PRESENTACION_ALERTA: Record<MotivoAlertaVigencia, { etiqueta: string; fg: string; bg: string; Icon: typeof AlertTriangle }> = {
  AUSENTE: { etiqueta: 'Falta capturarlo', fg: 'text-danger', bg: 'bg-danger-soft', Icon: AlertCircle },
  SIN_CONFIRMAR: { etiqueta: 'Es un clic: falta confirmarlo', fg: 'text-warning', bg: 'bg-warning-soft', Icon: AlertTriangle },
  CADUCADO: { etiqueta: 'Caducado: es de un ejercicio anterior', fg: 'text-danger', bg: 'bg-danger-soft', Icon: CalendarClock },
  CATALOGO_ILEGIBLE: { etiqueta: 'No se puede leer el catálogo del SAT', fg: 'text-info', bg: 'bg-info-soft', Icon: Wrench },
  LIBRERIA_DESACTUALIZADA: { etiqueta: 'La librería del SAT lleva más de un año', fg: 'text-info', bg: 'bg-info-soft', Icon: Wrench },
  SINCRONIZACION_FALLIDA: { etiqueta: 'La sincronización automática no corrió', fg: 'text-info', bg: 'bg-info-soft', Icon: Wrench },
};

/** El `detalle` del servidor trae los identificadores entre acentos graves (`` `UMA_DIARIA` ``).
 * Se pintan en monoespaciada (doc 08) en vez de mostrar los acentos crudos. */
function DetalleAlerta({ texto }: { texto: string }) {
  return (
    <>
      {texto.split('`').map((parte, i) =>
        i % 2 === 1 ? (
          <code key={i} className="font-mono text-[12px]">{parte}</code>
        ) : (
          <span key={i}>{parte}</span>
        ),
      )}
    </>
  );
}

function FilaAlerta({ alerta, hayTarjeta }: { alerta: AlertaVigencia; hayTarjeta: boolean }) {
  const { etiqueta, fg, bg, Icon } = PRESENTACION_ALERTA[alerta.motivo];
  const nombre = CATALOGO[alerta.clave]?.nombre;
  return (
    <li className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0">
      <div className="flex items-center gap-2 flex-wrap">
        {/* Doc 08: el color nunca es el único indicador — chip con texto e ícono. */}
        <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${fg} ${bg}`}>
          <Icon className="size-3.5" aria-hidden /> {etiqueta}
        </span>
        {nombre ? <span className="text-[13px] font-semibold">{nombre}</span> : null}
        <code className="font-mono text-[12px] text-text-muted">{alerta.clave}</code>
        {hayTarjeta && (
          <a href={`#param-${alerta.clave}`} className="text-[12px] font-semibold text-primary">
            Ir al valor
          </a>
        )}
      </div>
      <p className="m-0 text-[13px] text-text-muted text-pretty max-w-[80ch]">
        <DetalleAlerta texto={alerta.detalle} />
      </p>
    </li>
  );
}

function AlarmaDeVigencia({ alertas, claves }: { alertas: AlertaVigencia[]; claves: string[] }) {
  const deValor = alertas.filter((a) => MOTIVOS_DE_VALOR.includes(a.motivo));
  const deMaquinaria = alertas.filter((a) => !MOTIVOS_DE_VALOR.includes(a.motivo));

  return (
    <div className="flex flex-col gap-3">
      {deValor.length > 0 ? (
        <section role="status" className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-1">
          <h4 className="m-0 text-[14px] font-semibold">Qué necesita tu atención hoy</h4>
          <p className="m-0 text-[12px] text-text-muted text-pretty max-w-[80ch]">
            Se revisa cada vez que abres esta pantalla, contra el calendario: <strong>la UMA cambia el 1 de febrero</strong>{' '}
            y <strong>el salario mínimo el 1 de enero</strong>. Por eso el sistema sabe que un valor caducó sin consultar
            ninguna página — y un valor confirmado del año pasado sigue calculando aunque esté mal, que es lo que esta
            lista existe para que no pase.
          </p>
          <ul className="list-none p-0 m-0 mt-1 flex flex-col divide-y divide-border">
            {deValor.map((a) => (
              <FilaAlerta key={`${a.clave}-${a.motivo}`} alerta={a} hayTarjeta={claves.includes(a.clave)} />
            ))}
          </ul>
        </section>
      ) : (
        <p className="m-0 text-[13px] text-success flex items-center gap-1.5">
          <CheckCircle2 className="size-4 shrink-0" aria-hidden />
          Ningún valor fiscal está caducado ni esperando confirmación.
        </p>
      )}

      {deMaquinaria.length > 0 && (
        <section role="status" className="bg-surface-alt border border-border rounded-lg p-4 flex flex-col gap-1">
          <h4 className="m-0 text-[14px] font-semibold flex items-center gap-1.5">
            <Wrench className="size-4 shrink-0 text-text-muted" aria-hidden />
            Revisiones del sistema
          </h4>
          <p className="m-0 text-[12px] text-text-muted text-pretty max-w-[80ch]">
            Esto <strong>no habla de ningún valor fiscal</strong>: es la maquinaria que los mantiene al día. No hay nada
            que capturar ni que confirmar aquí, y ningún informe se detiene por esto — normalmente es algo que falta
            configurar o actualizar en el servidor, y lo resuelve quien administra la instalación.
          </p>
          <ul className="list-none p-0 m-0 mt-1 flex flex-col divide-y divide-border">
            {deMaquinaria.map((a) => (
              <FilaAlerta key={`${a.clave}-${a.motivo}`} alerta={a} hayTarjeta={false} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

// --- pantalla ---------------------------------------------------------------------------------

interface EnCaptura {
  clave: string;
  /** El tramo que se está corrigiendo, o `null` cuando se captura uno nuevo. */
  tramo: ParametroFiscal | null;
}

export function ConfiguracionFiscalPage() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['configuracion-fiscal'],
    queryFn: () => api.listarConfiguracionFiscal(),
  });

  const [enCaptura, setEnCaptura] = useState<EnCaptura | null>(null);
  const [conflicto, setConflicto] = useState<string | null>(null);

  const confirmar = useMutation({
    mutationFn: (p: ParametroFiscal) => api.confirmarParametroFiscal(p.clave, { vigencia_desde: p.vigencia_desde, valor: p.valor }),
    onSuccess: (fila) => {
      setConflicto(null);
      void qc.invalidateQueries({ queryKey: ['configuracion-fiscal'] });
      toast(`${ficha(fila.clave).nombre}: valor confirmado. Los informes ya calculan con él.`, 'ok');
    },
    onError: (e, p) => {
      // El 409 no es un error del usuario: la propuesta cambió entre que se pintó la pantalla y
      // el clic (una recarga de semillas, otro administrador, la sincronización). Se refresca la
      // pantalla y se explica; mostrar el mensaje crudo dejaría al usuario sin saber qué hacer.
      if (e instanceof ApiError && e.codigo === 'VALOR_CAMBIO') {
        void qc.invalidateQueries({ queryKey: ['configuracion-fiscal'] });
        setConflicto(
          `No se confirmó nada: el valor de ${ficha(p.clave).nombre} cambió mientras lo revisabas (tú viste ${importeLegible(p.valor)}). ` +
            'Ya volvimos a cargar la pantalla con el valor actual: revísalo otra vez contra su fuente y vuelve a confirmar si es correcto.',
        );
        return;
      }
      toast(e instanceof ApiError ? e.message : 'No se pudo confirmar el valor.', 'error');
    },
  });

  if (isLoading) return <p className="text-text-muted text-[13px]">Cargando la configuración fiscal…</p>;
  if (isError) {
    return (
      <div role="alert" className="bg-danger-soft text-danger rounded-md px-3 py-2 text-[13px]">
        {error instanceof ApiError ? error.message : 'No se pudo cargar la configuración fiscal.'}
      </div>
    );
  }

  const parametros = data?.parametros ?? [];
  const clavesSinValor = data?.claves_sin_valor ?? [];

  // Un renglón por clave: el tramo más reciente manda (es el que la pantalla presenta) y los
  // anteriores quedan como historia.
  const porClave = new Map<string, ParametroFiscal[]>();
  for (const p of parametros) {
    const lista = porClave.get(p.clave) ?? [];
    lista.push(p);
    porClave.set(p.clave, lista);
  }
  for (const lista of porClave.values()) lista.sort((a, b) => b.vigencia_desde.localeCompare(a.vigencia_desde));

  const claves = [...new Set([...porClave.keys(), ...clavesSinValor])];
  const pendientes = [...porClave.values()].filter((t) => !t[0].confirmado).length;
  const confirmados = [...porClave.values()].filter((t) => t[0].confirmado).length;

  const grupos = ORDEN_GRUPOS.map((grupo) => ({ grupo, claves: claves.filter((c) => ficha(c).grupo === grupo).sort() }))
    .concat({ grupo: 'Otros valores', claves: claves.filter((c) => !ORDEN_GRUPOS.includes(ficha(c).grupo)).sort() })
    .filter((g) => g.claves.length > 0);

  return (
    <div className="flex flex-col gap-4">
      <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-2">
        <h3 className="m-0 text-[15px] font-semibold">Valores fiscales</h3>
        <p className="m-0 text-[13px] text-text-muted text-pretty max-w-[70ch]">
          Los informes de nómina calculan con estos valores. Hub CFDI puede <strong>proponer</strong> uno —traído de su
          fuente oficial o sincronizado—, pero <strong>hasta que una persona lo confirma, los informes lo tratan como
          si no existiera</strong>. Confirmar es decir "revisé esta cifra contra su fuente y es correcta".
        </p>
        <div className="flex flex-wrap gap-2 mt-1">
          <ChipEstado estado="confirmado" />
          <span className="text-[13px] text-text-muted self-center">{confirmados} de {claves.length}</span>
          {pendientes > 0 && (
            <>
              <ChipEstado estado="propuesto" />
              <span className="text-[13px] text-text-muted self-center">{pendientes} esperando un clic</span>
            </>
          )}
          {clavesSinValor.length > 0 && (
            <>
              <ChipEstado estado="ausente" />
              <span className="text-[13px] text-text-muted self-center">{clavesSinValor.length} por capturar</span>
            </>
          )}
        </div>
        <p className="m-0 mt-1 text-[12px] text-text-muted">
          La política laboral de cada organización (zona salarial, aguinaldo, prima vacacional y la clasificación de sus
          conceptos de nómina) se configura por empresa, en <strong>Empresa → Configuración</strong>.
        </p>
      </div>

      {/* La alarma de vigencia (doc 05 §8bis), lo primero después de la explicación: es lo que hay
          que hacer hoy. Va antes de las tarjetas porque una tarjeta dice cómo está un valor, y
          esto dice cuál de todos te está esperando. */}
      <AlarmaDeVigencia alertas={data?.alertas ?? []} claves={claves} />

      {conflicto && (
        <div role="alert" className="bg-warning-soft text-warning rounded-md px-3 py-2.5 text-[13px] flex items-start gap-2">
          <AlertTriangle className="size-4 shrink-0 mt-0.5" aria-hidden />
          <span className="text-pretty">{conflicto}</span>
        </div>
      )}

      {grupos.map(({ grupo, claves: clavesDelGrupo }) => (
        <section key={grupo} className="flex flex-col gap-2">
          <h4 className="m-0 text-[13px] font-semibold text-text-muted uppercase tracking-wide">{grupo}</h4>
          <div className="flex flex-col gap-2.5">
            {clavesDelGrupo.map((clave) => (
              <TarjetaClave
                key={clave}
                clave={clave}
                tramos={porClave.get(clave) ?? []}
                // Solo la tarjeta en la que se hizo clic: con el `isPending` compartido, confirmar
                // un valor ponía las seis en estado de carga.
                confirmando={confirmar.isPending && confirmar.variables?.clave === clave}
                onConfirmar={(p) => confirmar.mutate(p)}
                onCapturar={(tramo) => { setConflicto(null); setEnCaptura({ clave, tramo }); }}
              />
            ))}
          </div>
        </section>
      ))}

      {enCaptura && (
        <ModalCaptura
          clave={enCaptura.clave}
          tramo={enCaptura.tramo}
          onCerrar={() => setEnCaptura(null)}
          onGuardado={() => {
            setEnCaptura(null);
            void qc.invalidateQueries({ queryKey: ['configuracion-fiscal'] });
            toast('Valor guardado. Queda sin confirmar hasta que lo revises y lo confirmes.', 'ok');
          }}
        />
      )}

      {/* La segunda mitad del mismo invariante: las marcas de exención del art. 93. Va debajo
          porque depende de la primera — las exenciones se calculan con la UMA y el salario mínimo
          confirmados de arriba. */}
      <div className="border-t border-border pt-4 mt-2">
        <MarcasPercepcionSection />
      </div>
    </div>
  );
}

function TarjetaClave({
  clave,
  tramos,
  confirmando,
  onConfirmar,
  onCapturar,
}: {
  clave: string;
  tramos: ParametroFiscal[];
  confirmando: boolean;
  onConfirmar: (p: ParametroFiscal) => void;
  onCapturar: (tramo: ParametroFiscal | null) => void;
}) {
  const [verHistoria, setVerHistoria] = useState(false);
  const f = ficha(clave);
  const actual = tramos[0] ?? null;
  const estado: EstadoFiscal = actual === null ? 'ausente' : actual.confirmado ? 'confirmado' : 'propuesto';
  const anteriores = tramos.slice(1);
  const hoy = hoyISO();

  return (
    // El `id` es el destino de "Ir al valor" de la alarma de arriba: la alerta dice qué pasa y
    // esta tarjeta es donde se arregla.
    <article id={`param-${clave}`} className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3 scroll-mt-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h5 className="m-0 text-[14px] font-semibold">{f.nombre}</h5>
          <p className="m-0 mt-0.5 text-[12px] text-text-muted">
            {/* Identificador fiscal en monoespaciada (doc 08). */}
            <code className="font-mono">{clave}</code> · {f.cuandoCambia}
          </p>
        </div>
        <ChipEstado estado={estado} />
      </div>

      {actual === null ? (
        <div className="flex flex-col gap-2">
          <p className="m-0 text-[13px] text-pretty">{f.queEs}</p>
          <p className="m-0 text-[13px] text-warning text-pretty">
            <strong>Mientras no esté capturado:</strong> {f.siFalta}
          </p>
          <p className="m-0 text-[12px] text-text-muted text-pretty">
            <strong>De dónde sale:</strong> {f.deDondeSale}
          </p>
          <div>
            <Button type="button" onClick={() => onCapturar(null)}>Capturar valor</Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2.5">
          <div className="flex items-baseline gap-3 flex-wrap">
            <span className="font-mono text-[22px] font-semibold leading-none">{importeLegible(actual.valor)}</span>
            <span className="text-[13px] text-text-muted">
              {actual.vigencia_desde > hoy ? 'Entra en vigor el' : 'En vigor desde el'} {fechaLegible(actual.vigencia_desde)}
              {actual.vigencia_hasta ? ` y hasta el ${fechaLegible(actual.vigencia_hasta)}` : ''} · ejercicio {actual.ejercicio}
            </span>
          </div>

          <Procedencia parametro={actual} />

          {actual.confirmado ? (
            <p className="m-0 text-[13px] text-success">
              Confirmado por <strong>{actual.confirmado_por}</strong>
              {actual.confirmado_en ? ` el ${fechaHoraLegible(actual.confirmado_en)}` : ''}. Los informes calculan con este valor.
            </p>
          ) : (
            <p className="m-0 text-[13px] text-warning text-pretty">
              <strong>Mientras no lo confirmes:</strong> {f.siFalta}
            </p>
          )}

          <div className="flex gap-2 flex-wrap">
            {!actual.confirmado && (
              <Button type="button" disabled={confirmando} loading={confirmando} onClick={() => onConfirmar(actual)}>
                Confirmar {importeLegible(actual.valor)}
              </Button>
            )}
            <Button type="button" variant="secondary" onClick={() => onCapturar(actual)}>
              {actual.confirmado ? 'Corregir' : 'Corregir el valor'}
            </Button>
            <Button type="button" variant="secondary" onClick={() => onCapturar(null)}>
              Agregar otra vigencia
            </Button>
          </div>

          {anteriores.length > 0 && (
            <div className="border-t border-border pt-2">
              <button
                type="button"
                onClick={() => setVerHistoria((v) => !v)}
                className="inline-flex items-center gap-1.5 border-0 bg-transparent p-0 cursor-pointer text-[12px] font-semibold text-primary"
                aria-expanded={verHistoria}
              >
                <History className="size-3.5" aria-hidden />
                {verHistoria ? 'Ocultar' : 'Ver'} {anteriores.length} {anteriores.length === 1 ? 'vigencia anterior' : 'vigencias anteriores'}
              </button>
              {verHistoria && (
                <ul className="list-none p-0 m-0 mt-2 flex flex-col gap-1.5">
                  {anteriores.map((p) => (
                    <li key={p.vigencia_desde} className="text-[12px] text-text-muted flex items-center gap-2 flex-wrap">
                      <span className="font-mono">{importeLegible(p.valor)}</span>
                      <span>
                        del {fechaLegible(p.vigencia_desde)}
                        {p.vigencia_hasta ? ` al ${fechaLegible(p.vigencia_hasta)}` : ' en adelante'}
                      </span>
                      <ChipEstado estado={p.confirmado ? 'confirmado' : 'propuesto'} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function Procedencia({ parametro }: { parametro: ParametroFiscal }) {
  const { texto, url } = partirFuente(parametro.fuente);
  return (
    <p className="m-0 text-[12px] text-text-muted text-pretty">
      <strong>{ORIGEN_TEXTO[parametro.origen] ?? parametro.origen}:</strong> {texto}{' '}
      {url && (
        <a href={url} target="_blank" rel="noreferrer noopener" className="text-primary font-semibold inline-flex items-center gap-1">
          Ver la fuente <ExternalLink className="size-3" aria-hidden />
        </a>
      )}
      {parametro.sincronizado_en && <> · Sincronizado el {fechaHoraLegible(parametro.sincronizado_en)}</>}
    </p>
  );
}

const INPUT_CLASS = 'h-9 border border-border rounded px-2.5';

/** Captura o corrección de un tramo. Capturar **no confirma**: el valor queda propuesto y hace
 * falta un segundo acto deliberado para activarlo (por eso el modal lo dice en voz alta). */
function ModalCaptura({
  clave,
  tramo,
  onCerrar,
  onGuardado,
}: {
  clave: string;
  tramo: ParametroFiscal | null;
  onCerrar: () => void;
  onGuardado: () => void;
}) {
  const f = ficha(clave);
  const [valor, setValor] = useState(tramo ? importeLegible(tramo.valor) : '');
  const [desde, setDesde] = useState(tramo?.vigencia_desde ?? '');
  const [hasta, setHasta] = useState(tramo?.vigencia_hasta ?? '');
  const [fuente, setFuente] = useState(tramo?.fuente ?? '');
  const [error, setError] = useState<string | null>(null);

  const guardar = useMutation({
    mutationFn: () =>
      api.capturarParametroFiscal(clave, {
        // El importe viaja como **cadena**: mandarlo como número JSON lo haría pasar por `float`
        // y el backend lo rechaza con 422 justamente por eso.
        valor: valor.trim(),
        vigencia_desde: desde,
        vigencia_hasta: hasta || null,
        fuente: fuente.trim(),
      }),
    onSuccess: onGuardado,
    onError: (e) => setError(e instanceof ApiError ? e.message : 'No se pudo guardar el valor.'),
  });

  return (
    <Modal titleId="titulo-captura-fiscal" onClose={onCerrar}>
      <h3 id="titulo-captura-fiscal" className="m-0 text-base font-semibold">
        {tramo ? 'Corregir' : 'Capturar'} {f.nombre}
      </h3>
      <p className="m-0 text-[13px] text-text-muted text-pretty">
        Lo que captures queda <strong>sin confirmar</strong>: se guarda como propuesta y no entra a ningún cálculo hasta
        que lo confirmes. {f.deDondeSale}
      </p>

      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          // Solo se comprueba aquí la *forma* del dato. Las reglas fiscales (positivo, hasta 6
          // decimales, sin solapar vigencias) las decide el servidor, que es donde viven y donde
          // no se pueden esquivar; sus mensajes se muestran tal cual porque explican qué corregir.
          if (!/^[+-]?\d+(\.\d+)?$/.test(valor.trim())) {
            setError('Escribe el valor como número, con punto decimal y sin separadores de miles (por ejemplo 117.31).');
            return;
          }
          guardar.mutate();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <label htmlFor="captura-valor" className="text-xs font-semibold text-text-muted">Valor</label>
          <input
            id="captura-valor"
            required
            inputMode="decimal"
            autoComplete="off"
            value={valor}
            onChange={(e) => setValor(e.target.value)}
            placeholder="117.31"
            className={`${INPUT_CLASS} font-mono`}
          />
          <span className="text-[11px] text-text-muted">Hasta 6 decimales. En pesos, sin signo de moneda.</span>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="captura-desde" className="text-xs font-semibold text-text-muted">Vigente desde</label>
            <input id="captura-desde" required type="date" value={desde} onChange={(e) => setDesde(e.target.value)} className={INPUT_CLASS} disabled={tramo !== null} />
            {tramo !== null && <span className="text-[11px] text-text-muted">Identifica el tramo; para otra fecha, agrega una vigencia nueva.</span>}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="captura-hasta" className="text-xs font-semibold text-text-muted">Vigente hasta (opcional)</label>
            <input id="captura-hasta" type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} className={INPUT_CLASS} />
            <span className="text-[11px] text-text-muted">Vacío = sigue vigente hasta nuevo aviso.</span>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="captura-fuente" className="text-xs font-semibold text-text-muted">Fuente</label>
          <input
            id="captura-fuente"
            required
            value={fuente}
            onChange={(e) => setFuente(e.target.value)}
            placeholder="DOF 09-12-2025, resolución del CONASAMI — https://…"
            className={INPUT_CLASS}
          />
          <span className="text-[11px] text-text-muted">De dónde sacaste la cifra. Si incluyes la liga, la pantalla la muestra para que cualquiera pueda revisarla.</span>
        </div>

        {error && <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] text-pretty">{error}</div>}

        <div className="flex gap-2 justify-end">
          <Button type="button" variant="secondary" onClick={onCerrar}>Cancelar</Button>
          <Button type="submit" loading={guardar.isPending} disabled={guardar.isPending}>Guardar sin confirmar</Button>
        </div>
      </form>
    </Modal>
  );
}
