// Las 44 marcas de exención del art. 93 de la LISR (`catalogo_percepcion_marca`, doc 05 §8bis),
// dentro de la pestaña Fiscal y bajo la sección de valores fiscales: es el mismo invariante y la
// misma persona quien lo ejerce.
//
// **Por qué esta sección no se construyó en la primera vuelta y por qué se puede construir ahora.**
// Las 44 marcas se sembraron con 39 **dudas declaradas** —qué genera la incertidumbre en ese tipo,
// derivada contra el texto de la LISR y la LSS— y hasta la ronda 2 de la tarea 4 vivían en
// comentarios del YAML: no llegaban a la base y no viajaban en la respuesta. Una tabla con 44
// botones "Confirmar" sin ellas a la vista dejaría confirmar a ciegas exactamente lo que el
// invariante existe para impedir, y encima haría *parecer* revisado lo que nadie revisó. Hoy
// `nota_revision` es una columna y viaja en el `GET`, así que la duda puede estar donde tiene que
// estar: al lado del botón. De ahí que aquí la nota no se pliegue ni se resuma — si se pudiera
// pasar por alto, estaríamos en el punto de partida.
//
// **Lo que esta pantalla desbloquea:** hoy hay 0 marcas confirmadas, y una marca sin confirmar no
// participa en ningún cálculo de exención. Mientras siga así, B-03 no calcula exenciones. Esta es
// la única puerta para cambiarlo, y solo la puede cruzar una persona.
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, Info, Minus, ShieldAlert } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Switch } from '@/components/ui/Switch';
import { useToast } from '@/components/ui/ToastProvider';
import { ApiError } from '@/lib/api';
import type { BaseExencion, MarcaPercepcion, MarcaPercepcionConfirmarIn } from '@/lib/api';
import { api } from '@/lib/client';
import { ChipEstadoFiscal } from './ChipEstadoFiscal';
import { fechaHoraLegible, type EstadoFiscal } from './fiscalComun';

/** Cómo nombrar un tipo en un mensaje. La descripción la manda el servidor (`descripcion_sat`,
 * del mismo `c_TipoPercepcion` que valida la escritura); un tipo **sin fila** no tiene ninguna,
 * porque `claves_sin_marcas` solo trae la clave. Antes esto lo resolvía una copia del catálogo en
 * el cliente: se borró, porque además de describir decidía qué tarjetas existen —y por tanto el
 * denominador del "0 de 44"—, y se quedaba vieja al subir la versión de `satcfdi`. */
function nombreDelTipo(tipo: string, marca: MarcaPercepcion | null): string {
  return marca?.descripcion_sat ? `${tipo} · ${marca.descripcion_sat}` : tipo;
}

// --- presentación de las marcas ----------------------------------------------------------------

/** Cómo se lee cada base de exención, y **en qué unidad está el factor**. La escala del porcentaje
 * es la trampa de todo este catálogo: la semilla lo captura en **0-100, no como fracción**, así que
 * `100` es el cien por ciento. Leerlo como fracción multiplicaría por cien la exención de los seis
 * tipos de previsión social; por eso el texto nunca dice solo "100" ni solo "%". */
const BASE_EXENCION: Record<BaseExencion, { etiqueta: string; unidad: string; ayudaFactor: string }> = {
  NINGUNA: {
    etiqueta: 'Sin exención — gravado íntegro',
    unidad: '',
    ayudaFactor: '',
  },
  UMA_DIAS: {
    etiqueta: 'Días de UMA',
    unidad: 'días de UMA',
    ayudaFactor: 'Número de días de UMA exentos. La ley lo dice así ("15 veces el salario mínimo… hoy UMA"); el importe en pesos lo calcula el informe con la UMA diaria confirmada.',
  },
  SM_DIAS: {
    etiqueta: 'Días de salario mínimo',
    unidad: 'días de salario mínimo',
    ayudaFactor: 'Número de días de salario mínimo exentos. Se resuelve con el mínimo de la zona salarial de cada organización.',
  },
  PORCENTAJE: {
    etiqueta: 'Porcentaje del importe',
    unidad: '% del importe',
    ayudaFactor: 'Porcentaje en escala 0 a 100, NO una fracción: escribe 100 para el cien por ciento y 50 para la mitad. Un 0.5 aquí significa medio por ciento.',
  },
};

/** El factor tal como llega ("100.0000"), sin los ceros de relleno, que no son información. Nunca
 * pasa por `Number`: el contrato lo manda como cadena justamente para que no lo toque un `float`. */
function factorLegible(valor: string): string {
  if (!valor.includes('.')) return valor;
  const recortado = valor.replace(/0+$/, '').replace(/\.$/, '');
  return recortado === '' ? valor : recortado;
}

/** La misma cifra escrita de dos maneras ("100", "100.00", "0100") es **un solo valor** para el
 * servidor, que compara `Decimal`. Esta normalización existe solo para no avisar de un cambio que
 * no lo es; nunca pasa por `Number` (el contrato prohíbe que un importe toque un `float`) y no
 * decide nada fiscal: lo que se guarda es lo que se tecleó, y lo valida el backend. */
function factorNormalizado(valor: string | null): string | null {
  if (valor === null) return null;
  const t = valor.trim();
  if (t === '' || !/^\d+(\.\d*)?$|^\.\d+$/.test(t)) return t || null;
  const [enteros = '', decimales = ''] = t.split('.');
  const e = enteros.replace(/^0+(?=\d)/, '') || '0';
  const d = decimales.replace(/0+$/, '');
  return d ? `${e}.${d}` : e;
}

function SiNo({ valor }: { valor: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1 font-semibold ${valor ? 'text-text-strong' : 'text-text-muted'}`}>
      {valor ? <Check className="size-3.5" aria-hidden /> : <Minus className="size-3.5" aria-hidden />}
      {valor ? 'Sí' : 'No'}
    </span>
  );
}

function Marca({ nombre, children, ayuda }: { nombre: string; children: React.ReactNode; ayuda: string }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className="text-[11px] font-semibold text-text-muted uppercase tracking-wide">{nombre}</span>
      <span className="text-[13px]">{children}</span>
      <span className="text-[11px] text-text-muted text-pretty">{ayuda}</span>
    </div>
  );
}

// --- filtros -----------------------------------------------------------------------------------

type Filtro = 'usados' | 'duda' | 'pendientes' | 'todos';

// --- la sección ----------------------------------------------------------------------------------

interface Aviso {
  tono: 'warning' | 'info';
  texto: string;
}

export function MarcasPercepcionSection() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [filtroElegido, setFiltroElegido] = useState<Filtro | null>(null);
  const [enCaptura, setEnCaptura] = useState<{ tipo: string; marca: MarcaPercepcion | null } | null>(null);
  const [aviso, setAviso] = useState<Aviso | null>(null);

  const { data: catalogo, isLoading, isError, error } = useQuery({
    queryKey: ['marcas-percepcion'],
    queryFn: () => api.listarMarcasPercepcion(),
  });

  const tiposUsados = useTiposUsadosPorLaNomina();

  const confirmar = useMutation({
    mutationFn: ({ tipo, marcas: m }: { tipo: string; nombre: string; marcas: MarcaPercepcionConfirmarIn }) =>
      api.confirmarMarcaPercepcion(tipo, m),
    onSuccess: (fila) => {
      setAviso(null);
      void qc.invalidateQueries({ queryKey: ['marcas-percepcion'] });
      toast(`Tipo ${fila.tipo_percepcion} confirmado. B-03 ya calcula la exención de este tipo con estas marcas.`, 'ok');
    },
    onError: (e, { nombre }) => {
      const manejado = avisoDeErrorDeCatalogo(e, setAviso);
      if (manejado) return;
      // Los dos 409 **no son errores del usuario**: algo cambió entre que se pintó la pantalla y
      // el clic. Se refresca y se explica, igual que el `VALOR_CAMBIO` de la sección de arriba —
      // mostrar el mensaje crudo dejaría a la persona sin saber qué hacer. Se distinguen porque
      // piden cosas distintas: uno manda a revisar las marcas, el otro a **leer la duda**.
      if (e instanceof ApiError && e.codigo === 'DUDA_NO_VISTA') {
        void qc.invalidateQueries({ queryKey: ['marcas-percepcion'] });
        setAviso({
          tono: 'warning',
          texto:
            `No se confirmó nada: el tipo ${nombre} tiene ahora una duda declarada que no estaba a la vista cuando lo ` +
            'revisabas (la agregó otra persona o una recarga de semillas). Ya volvimos a cargar la pantalla: léela y ' +
            'confirma después, porque confirmar es responder por lo que se miró. Si la duda se hubiera resuelto en ese ' +
            'rato, en cambio, la confirmación habría pasado: quien revisó lo hizo con más información de la que hay hoy.',
        });
        return;
      }
      if (e instanceof ApiError && e.codigo === 'MARCAS_CAMBIARON') {
        void qc.invalidateQueries({ queryKey: ['marcas-percepcion'] });
        setAviso({
          tono: 'warning',
          texto:
            `No se confirmó nada: las marcas del tipo ${nombre} cambiaron mientras las ` +
            'revisabas. Ya volvimos a cargar la pantalla con las marcas actuales: revísalas otra vez —incluida su duda, si la ' +
            'tiene— y vuelve a confirmar si son correctas.',
        });
        return;
      }
      toast(e instanceof ApiError ? mensajeDe422(e.message) : 'No se pudieron confirmar las marcas.', 'error');
    },
  });

  if (isLoading) return <p className="text-text-muted text-[13px]">Cargando las marcas de exención…</p>;
  if (isError) {
    return (
      <div role="alert" className="bg-danger-soft text-danger rounded-md px-3 py-2 text-[13px]">
        {error instanceof ApiError ? error.message : 'No se pudieron cargar las marcas de exención.'}
      </div>
    );
  }

  const porTipo = new Map((catalogo?.marcas ?? []).map((m) => [m.tipo_percepcion, m]));
  // El **denominador lo pone el servidor**: `claves_sin_marcas` son los tipos de
  // `c_TipoPercepcion` que todavía no tienen ninguna fila, y son el tercer estado (ausente), igual
  // que `claves_sin_valor` arriba. Se le suman los tipos que la nómina **sí emite**: si uno de
  // esos no tiene fila y tampoco viniera en `claves_sin_marcas` —el catálogo del SAT no se pudo
  // leer y llegó vacía— quedaría invisible justo cuando es el más urgente.
  const tipos = [...new Set([...(catalogo?.claves_sin_marcas ?? []), ...porTipo.keys(), ...(tiposUsados.tipos ?? [])])].sort();

  const confirmadas = tipos.filter((t) => porTipo.get(t)?.confirmado).length;
  const conDuda = tipos.filter((t) => porTipo.get(t)?.nota_revision).length;
  const sinCapturar = tipos.filter((t) => !porTipo.has(t)).length;
  // Una **propuesta** sin confirmar es un tipo que tiene marcas y no está confirmado. Los tipos
  // sin marcas capturadas no son propuestas de nada: contarlos aquí además de en `sinCapturar`
  // daba 88 elementos en un catálogo de 44 y hacía que los dos contadores se contradijeran.
  const pendientes = tipos.filter((t) => porTipo.has(t) && !porTipo.get(t)?.confirmado).length;
  const usados = tiposUsados.tipos ? tipos.filter((t) => tiposUsados.tipos?.has(t)) : [];

  // El filtro por omisión es "los que tu nómina usa" **solo cuando esa lente existe y no está
  // vacía**: es la diferencia entre "revisa 39 dudas" y "revisa la que te aplica". No es un
  // escondite —el contador de arriba sigue diciendo cuántas hay en total, el chip activo dice
  // cuántas se están viendo, y un clic muestra las 44—, pero sí decide por dónde empezar.
  const filtro: Filtro = filtroElegido ?? (usados.length > 0 ? 'usados' : 'todos');
  const visibles = tipos.filter((t) => {
    if (filtro === 'usados') return tiposUsados.tipos?.has(t) ?? true;
    if (filtro === 'duda') return Boolean(porTipo.get(t)?.nota_revision);
    if (filtro === 'pendientes') return !porTipo.get(t)?.confirmado;
    return true;
  });

  const FILTROS: { clave: Filtro; texto: string; visible: boolean }[] = [
    { clave: 'usados', texto: `Los que tu nómina usa (${usados.length})`, visible: usados.length > 0 },
    { clave: 'duda', texto: `Con duda declarada (${conDuda})`, visible: conDuda > 0 },
    { clave: 'pendientes', texto: `Sin confirmar (${pendientes})`, visible: pendientes > 0 },
    { clave: 'todos', texto: `Los ${tipos.length} tipos del catálogo`, visible: true },
  ];

  return (
    <section className="flex flex-col gap-3">
      <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-2">
        <h3 className="m-0 text-[15px] font-semibold">Exenciones por tipo de percepción (artículo 93 de la LISR)</h3>
        <p className="m-0 text-[13px] text-text-muted text-pretty max-w-[78ch]">
          Cada tipo de percepción del catálogo del SAT lleva cinco marcas que deciden cómo se trata en los informes de
          nómina: si es ingreso ordinario, cuánto exenta y sobre qué base, si integra al salario base de cotización y si
          entra al pasivo laboral. Hub CFDI las <strong>propone</strong> a partir del texto de la LISR y de la LSS, pero
          —igual que los valores de arriba— <strong>una marca sin confirmar no calcula</strong>: mientras nadie la
          confirme, B-03 no exenta nada de ese tipo.
        </p>
        <div className="flex flex-wrap gap-2 mt-1">
          <ChipEstadoFiscal estado="confirmado" texto="Confirmadas · calculan" />
          <span className="text-[13px] text-text-muted self-center">{confirmadas} de {tipos.length}</span>
          {pendientes > 0 && (
            <>
              <ChipEstadoFiscal estado="propuesto" texto="Propuestas · sin confirmar" />
              <span className="text-[13px] text-text-muted self-center">{pendientes}</span>
            </>
          )}
          {sinCapturar > 0 && (
            <>
              <ChipEstadoFiscal estado="ausente" texto="Sin marcas capturadas" />
              <span className="text-[13px] text-text-muted self-center">{sinCapturar}</span>
            </>
          )}
        </div>
        <p className="m-0 mt-1 text-[12px] text-text-muted text-pretty max-w-[78ch]">
          <strong>{conDuda} de estos tipos traen una duda declarada</strong>: qué genera la incertidumbre en ese tipo y
          qué habría que verificar antes de darlo por bueno. Se muestra completa junto a su botón de confirmar, porque
          confirmar es responder por la revisión y no se puede responder por lo que no se tuvo delante.
        </p>
        <p className="m-0 text-[12px] text-text-muted text-pretty max-w-[78ch]">
          <strong>Si corriges una marca confirmada, vuelve a quedar propuesta</strong> — y también si al corregirla
          <strong> aparece o cambia</strong> su duda, aunque no muevas ninguna marca: quien la confirmó no tenía esa duda
          delante, así que su revisión ya no cubre lo que hoy se sabe. <strong>Resolver</strong> una duda (borrarla) no
          quita la confirmación: resolverla no invalida nada.
        </p>
      </div>

      {tiposUsados.error && (
        <p role="status" className="m-0 text-[12px] text-text-muted text-pretty flex items-start gap-1.5">
          <Info className="size-3.5 shrink-0 mt-0.5" aria-hidden />
          <span>
            No se pudo revisar qué tipos aparecen en la nómina de <strong>todas</strong> tus organizaciones (al menos una
            no respondió), así que se muestran los {tipos.length} tipos del catálogo. El atajo solo aparece cuando se
            puede armar completo: con una organización de menos, la lista de "los que tu nómina usa" escondería
            precisamente los tipos que solo esa emite.
          </span>
        </p>
      )}

      {tiposUsados.cargando ? (
        // No se pintan los 44 para colapsarlos a 2 medio segundo después: el salto deja sin
        // contexto a quien ya iba leyendo (y a un lector de pantalla, sin lo que estaba leyendo).
        <p role="status" className="m-0 text-[13px] text-text-muted">Revisando qué tipos aparecen de verdad en la nómina de tus organizaciones…</p>
      ) : (
      <>
      <div className="flex flex-wrap items-center gap-2">
        {FILTROS.filter((f) => f.visible).map((f) => (
          <button
            key={f.clave}
            type="button"
            aria-pressed={filtro === f.clave}
            onClick={() => setFiltroElegido(f.clave)}
            className={`rounded-md px-2.5 py-1 text-xs font-semibold border cursor-pointer ${
              filtro === f.clave ? 'bg-primary text-white border-primary' : 'bg-surface text-text-strong border-border hover:bg-surface-alt'
            }`}
          >
            {f.texto}
          </button>
        ))}
        <span className="text-[12px] text-text-muted">Viendo {visibles.length} de {tipos.length}.</span>
      </div>

      {filtro === 'usados' && (
        <p className="m-0 text-[12px] text-text-muted text-pretty max-w-[78ch] flex items-start gap-1.5">
          <Info className="size-3.5 shrink-0 mt-0.5" aria-hidden />
          <span>
            Estos son los tipos que <strong>aparecen hoy</strong> en los CFDI de nómina de tus organizaciones; los otros{' '}
            {tipos.length - usados.length} siguen sin confirmar. Si tu nómina empieza a timbrar uno de ellos, tendrás que
            revisarlo antes de que B-03 pueda exentarlo — este filtro dice qué es urgente, no qué se puede ignorar.
          </span>
        </p>
      )}

      {aviso && (
        <div
          role="alert"
          className={`rounded-md px-3 py-2.5 text-[13px] flex items-start gap-2 ${aviso.tono === 'warning' ? 'bg-warning-soft text-warning' : 'bg-info-soft text-info'}`}
        >
          <AlertTriangle className="size-4 shrink-0 mt-0.5" aria-hidden />
          <span className="text-pretty">{aviso.texto}</span>
        </div>
      )}

      <div className="flex flex-col gap-2.5">
        {visibles.map((tipo) => (
          <TarjetaMarca
            key={tipo}
            tipo={tipo}
            marca={porTipo.get(tipo) ?? null}
            usadoEnNomina={tiposUsados.tipos?.has(tipo) ?? false}
            // Solo **la tarjeta en la que se hizo clic** se pone a cargar: con el `isPending`
            // compartido, un clic dejaba las 44 en estado de carga y parecía que la pantalla
            // entera estaba haciendo algo.
            confirmando={confirmar.isPending && confirmar.variables?.tipo === tipo}
            onConfirmar={(m) => { setAviso(null); confirmar.mutate({ tipo, nombre: nombreDelTipo(tipo, porTipo.get(tipo) ?? null), marcas: m }); }}
            onEditar={() => { setAviso(null); setEnCaptura({ tipo, marca: porTipo.get(tipo) ?? null }); }}
          />
        ))}
        {visibles.length === 0 && <p className="m-0 text-[13px] text-text-muted">No hay tipos que cumplan este filtro.</p>}
      </div>
      </>
      )}

      {enCaptura && (
        <ModalMarca
          tipo={enCaptura.tipo}
          marca={enCaptura.marca}
          onCerrar={() => setEnCaptura(null)}
          onGuardado={(fila, estabaConfirmada) => {
            setEnCaptura(null);
            void qc.invalidateQueries({ queryKey: ['marcas-percepcion'] });
            if (estabaConfirmada && !fila.confirmado) {
              // Ver a una marca confirmada volver a "propuesta" sin explicación parece un fallo.
              setAviso({
                tono: 'info',
                texto:
                  `El tipo ${fila.tipo_percepcion} volvió a quedar sin confirmar. Es lo previsto: confirmar significa que ` +
                  'una persona revisó estas marcas y responde por ellas, y lo que se revisó ya no es lo que está guardado ' +
                  '—cambió una marca, o apareció o cambió su duda—. Revísalo y vuelve a confirmarlo cuando estés de acuerdo.',
              });
            } else {
              setAviso(null);
            }
            toast(`Tipo ${fila.tipo_percepcion} guardado. Queda sin confirmar hasta que lo revises y lo confirmes.`, 'ok');
          }}
        />
      )}
    </section>
  );
}

/** Cómo se llama en español cada campo del cuerpo, para poder nombrarlo en un mensaje de error sin
 * escupir el identificador del esquema. */
const NOMBRE_CAMPO: Record<string, string> = {
  es_ingreso_ordinario: 'Es ingreso ordinario',
  base_exencion: 'Base de exención',
  factor_exencion: 'El factor de exención',
  integra_sbc: 'Integra al salario base de cotización',
  es_provisionable: 'Es provisionable',
  sujeto_a_tope_conjunto: 'Sujeto al tope conjunto de previsión social',
  nota_revision: 'La duda declarada',
};

/** Por qué estos dos campos no llevan valor por omisión. Un "Field required" a secas no lo dice, y
 * es justo lo que hay que entender para no volver a omitirlos. */
const POR_QUE_OBLIGATORIO: Record<string, string> = {
  sujeto_a_tope_conjunto:
    'no tiene valor por omisión a propósito: es el mismo dato con el que se confirma, y darlo por «no» en silencio activaría una exención de previsión social sin su tope y B-03 exentaría de más.',
  nota_revision:
    'no tiene valor por omisión a propósito: si lo tuviera, guardar una corrección borraría en silencio una duda que alguien derivó contra la ley. Para decir que ya no hay duda, hay que dejarla vacía a mano.',
};

/** Un 422 de Pydantic llega como "campo: mensaje en inglés" (`api.http.ts` ya lo saca del sobre
 * `detail`, que si no se mostraría como "Error de red."). Aquí se termina de traducir lo poco que
 * este formulario puede provocar; **lo que no se reconoce se muestra tal cual**, porque un mensaje
 * del servidor que no entendemos sigue siendo mejor pista que una paráfrasis inventada. */
function mensajeDe422(bruto: string): string {
  return bruto
    .split(' · ')
    .map((parte) => {
      const [campo, ...resto] = parte.split(': ');
      const detalle = resto.join(': ');
      const nombre = NOMBRE_CAMPO[campo];
      // Los mensajes que escribe el propio backend ya vienen en español; Pydantic solo les antepone
      // "Value error, ".
      if (parte.startsWith('Value error, ')) return parte.slice('Value error, '.length);
      if (!nombre) return parte;
      if (detalle.startsWith('Value error, ')) return detalle.slice('Value error, '.length);
      if (detalle === 'Field required') return `Falta ${nombre.toLowerCase()}, y ${POR_QUE_OBLIGATORIO[campo] ?? 'es obligatorio.'}`;
      if (detalle.startsWith('Input should be greater than 0')) return `${nombre} tiene que ser mayor que cero.`;
      if (detalle.startsWith('Input should be less than')) return `${nombre} es demasiado grande para la columna que lo guarda (5 dígitos enteros).`;
      if (detalle.includes('decimal places')) return `${nombre} admite hasta 4 decimales, y los de más se rechazan en vez de redondearse: guardar una cifra distinta de la que revisaste haría inexplicable el siguiente aviso de "cambió mientras lo revisabas".`;
      return `${nombre}: ${detalle}`;
    })
    .join(' ');
}

/** El 503 del catálogo del SAT **no es un error del usuario ni definitivo**: el servidor falla
 * cerrado porque no puede comprobar que la clave existe, y el fallo no se memoiza, así que en
 * cuanto el catálogo vuelva a ser legible el siguiente intento pasa. Decirle "error" a secas a
 * quien está capturando lo mandaría a buscar qué escribió mal, que es justo lo que no pasó. */
function avisoDeErrorDeCatalogo(e: unknown, setAviso: (a: Aviso) => void): boolean {
  if (e instanceof ApiError && e.codigo === 'CATALOGO_SAT_ILEGIBLE') {
    setAviso({
      tono: 'warning',
      texto:
        'No se pudo verificar la clave contra el catálogo de tipos de percepción del SAT, así que no se escribió nada ' +
        '(antes que guardar una marca sobre un tipo que quizá no existe, el servidor prefiere no guardar). No es algo ' +
        'que tengas que corregir y suele resolverse solo: inténtalo otra vez en un momento.',
    });
    return true;
  }
  return false;
}

/** Qué tipos de percepción **aparecen de verdad** en los CFDI de nómina de las organizaciones a las
 * que este administrador tiene acceso, según `conceptos-observados`.
 *
 * **Es una lente, no un permiso ni un filtro del servidor.** Estas marcas son federales y globales;
 * los conceptos observados son por empresa, así que la unión de todas las organizaciones es lo más
 * cercano a "lo que esta instalación timbra". Si algo falla —no hay empresas, el endpoint no
 * responde, el rol no alcanza— la lente simplemente no existe y se ven los 44 tipos: **falla hacia
 * mostrar de más**, nunca hacia esconder un tipo que alguien tenía que revisar.
 *
 * `cargando` existe para que la lista **no salte**: mientras las consultas por organización no
 * resuelven, la sección no pinta todavía los 44 tipos para colapsarlos después a 2. Un lector de
 * pantalla que ya iba leyendo la lista se quedaría sin lo que estaba leyendo. */
function useTiposUsadosPorLaNomina(): { tipos: Set<string> | null; error: boolean; cargando: boolean } {
  const { data: empresas, isError: errorEmpresas, isPending: cargandoEmpresas } = useQuery({
    queryKey: ['empresas'],
    queryFn: () => api.listarEmpresas(),
  });
  const observados = useQueries({
    // Una consulta por organización porque el endpoint es por empresa. Son cuatro agregados con
    // `GROUP BY` cada una y el resultado casi no cambia, así que se cachea largo: esta pantalla no
    // es un tablero en vivo.
    queries: (empresas ?? []).map((e) => ({
      queryKey: ['conceptos-observados', e.empresa_id],
      queryFn: () => api.obtenerConceptosObservados(e.empresa_id),
      staleTime: 5 * 60_000,
    })),
  });

  if (errorEmpresas) return { tipos: null, error: true, cargando: false };
  if (cargandoEmpresas) return { tipos: null, error: false, cargando: true };
  if (!empresas || empresas.length === 0) return { tipos: null, error: false, cargando: false };
  if (observados.some((q) => q.isPending)) return { tipos: null, error: false, cargando: true };
  // **`some`, no `every`.** Con tres organizaciones y una que responde 500, las otras dos
  // resuelven y la unión se armaría solo con las que funcionaron: un tipo usado exclusivamente por
  // la que falló desaparecería del filtro sin que nada lo dijera. Es la única dirección en la que
  // esta lente puede esconder algo, y esconder es justo lo que no puede hacer — si no se pudo
  // armar completa, no hay lente y se ven los 44.
  if (observados.some((q) => q.isError)) return { tipos: null, error: true, cargando: false };

  const tipos = new Set<string>();
  for (const q of observados) {
    for (const c of q.data?.conceptos ?? []) {
      // `naturaleza: 'P'` son las percepciones; las deducciones y otros pagos tienen sus propios
      // catálogos y no se marcan aquí.
      if (c.naturaleza === 'P') tipos.add(c.tipo);
    }
  }
  return { tipos, error: false, cargando: false };
}

// --- una tarjeta por tipo -------------------------------------------------------------------------

function TarjetaMarca({
  tipo,
  marca,
  usadoEnNomina,
  confirmando,
  onConfirmar,
  onEditar,
}: {
  tipo: string;
  marca: MarcaPercepcion | null;
  usadoEnNomina: boolean;
  confirmando: boolean;
  onConfirmar: (m: MarcaPercepcionConfirmarIn) => void;
  onEditar: () => void;
}) {
  const estado: EstadoFiscal = marca === null ? 'ausente' : marca.confirmado ? 'confirmado' : 'propuesto';
  const chip = marca === null ? 'Sin marcas capturadas' : marca.confirmado ? 'Confirmado · calcula' : 'Propuesto · sin confirmar';

  return (
    <article className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0 flex items-start gap-2.5">
          {/* Identificador fiscal en monoespaciada (doc 08). */}
          <code className="font-mono text-[13px] font-semibold bg-surface-alt rounded px-1.5 py-0.5 shrink-0">{tipo}</code>
          <div className="min-w-0">
            <h5 className="m-0 text-[14px] font-semibold text-pretty">
              {marca?.descripcion_sat ?? 'Tipo de percepción del catálogo del SAT'}
            </h5>
            <p className="m-0 mt-0.5 text-[11px] text-text-muted">
              Catálogo <code className="font-mono">c_TipoPercepcion</code> del SAT
              {/* La descripción la resuelve el servidor del mismo `satcfdi` que valida la
                  escritura, y solo para las filas que existen: un tipo sin marcas capturadas
                  llega en `claves_sin_marcas`, que trae la clave y nada más. */}
              {marca !== null && marca.descripcion_sat === null && ' · el catálogo instalado no describe esta clave'}
              {marca === null && ' · su descripción aparece en cuanto tenga marcas capturadas'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {usadoEnNomina && (
            <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold whitespace-nowrap text-primary bg-primary-soft">
              <Check className="size-3.5" aria-hidden /> Aparece en tu nómina
            </span>
          )}
          <ChipEstadoFiscal estado={estado} texto={chip} />
        </div>
      </div>

      {marca === null ? (
        <div className="flex flex-col gap-2">
          <p className="m-0 text-[13px] text-warning text-pretty">
            <strong>Mientras no tenga marcas:</strong> no hay nada que confirmar y B-03 no tiene con qué calcular la
            exención de este tipo. Si tu nómina nunca lo timbra, no hace falta capturarlo.
          </p>
          <div><Button type="button" variant="secondary" onClick={onEditar}>Capturar las marcas</Button></div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {marca.nota_revision && <DudaDeclarada texto={marca.nota_revision} />}

          <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-x-5 gap-y-3">
            <Marca nombre="Ingreso ordinario" ayuda="Sueldo y conceptos del día a día; los de separación o retiro no lo son.">
              <SiNo valor={marca.es_ingreso_ordinario} />
            </Marca>
            <Marca nombre="Base de exención" ayuda={BASE_EXENCION[marca.base_exencion].etiqueta}>
              <span className="font-mono">{marca.base_exencion}</span>
            </Marca>
            <Marca
              nombre="Cuánto exenta"
              ayuda={
                marca.base_exencion === 'PORCENTAJE'
                  ? 'El factor está en escala 0 a 100: 100 es el cien por ciento del importe, no cien veces.'
                  : marca.base_exencion === 'NINGUNA'
                    ? 'Ninguna fracción del artículo 93 exenta este tipo.'
                    : 'El importe en pesos lo resuelve el informe con el valor confirmado de la UMA o del salario mínimo.'
              }
            >
              <span className="font-semibold">
                {marca.base_exencion !== 'NINGUNA' && marca.factor_exencion !== null && (
                  <span className="font-mono">{factorLegible(marca.factor_exencion)} </span>
                )}
                {marca.base_exencion === 'NINGUNA' ? BASE_EXENCION.NINGUNA.etiqueta : BASE_EXENCION[marca.base_exencion].unidad}
              </span>
            </Marca>
            <Marca nombre="Integra al SBC" ayuda="Salario base de cotización del artículo 27 de la LSS.">
              <SiNo valor={marca.integra_sbc} />
            </Marca>
            <Marca nombre="Provisionable" ayuda="Marca informativa del catálogo: el pasivo laboral lo calcula B-08 a partir de la clasificación de conceptos de cada empresa, no de esta casilla. Ningún informe la lee todavía.">
              <SiNo valor={marca.es_provisionable} />
            </Marca>
            <Marca
              nombre="Tope conjunto de previsión social"
              ayuda="Penúltimo párrafo del art. 93: la SUMA de las exenciones de previsión social de un trabajador se limita a 1 UMA anual. Se aplica aparte del factor de arriba."
            >
              <SiNo valor={marca.sujeto_a_tope_conjunto} />
            </Marca>
          </div>

          {marca.confirmado ? (
            <p className="m-0 text-[13px] text-success">
              Confirmado por <strong>{marca.confirmado_por}</strong>
              {marca.confirmado_en ? ` el ${fechaHoraLegible(marca.confirmado_en)}` : ''}. B-03 calcula la exención de este
              tipo con estas marcas.
            </p>
          ) : (
            <p className="m-0 text-[13px] text-warning text-pretty">
              <strong>Mientras no lo confirmes:</strong> B-03 no exenta nada de este tipo — trata su importe como gravado y
              deja constancia de que la marca está sin revisar.
            </p>
          )}

          <div className="flex gap-2 flex-wrap">
            {!marca.confirmado && (
              <Button type="button" disabled={confirmando} loading={confirmando} onClick={() => onConfirmar(cuerpoDeConfirmacion(marca))}>
                Confirmar estas marcas
              </Button>
            )}
            <Button type="button" variant="secondary" onClick={onEditar}>
              {marca.confirmado ? 'Corregir' : 'Corregir las marcas'}
            </Button>
          </div>
        </div>
      )}
    </article>
  );
}

/** La duda declarada, entera y sin plegar. Si se pudiera pasar por alto, esta pantalla volvería a
 * ser la tabla de 44 botones "Confirmar" que la tarea 5 se negó a construir. */
function DudaDeclarada({ texto }: { texto: string }) {
  return (
    <div className="bg-warning-soft border-l-4 border-warning rounded-r-md px-3 py-2.5 flex items-start gap-2">
      <ShieldAlert className="size-4 shrink-0 mt-0.5 text-warning" aria-hidden />
      <div className="min-w-0">
        <p className="m-0 text-[12px] font-semibold uppercase tracking-wide text-warning">Duda declarada — revísala antes de confirmar</p>
        <p className="m-0 mt-1 text-[13px] text-text-strong text-pretty">{texto}</p>
      </div>
    </div>
  );
}

/** El cuerpo exacto del `confirmar`: las seis marcas que calculan (lo que el servidor compara para
 * responder 409 `MARCAS_CAMBIARON`) **más la huella de la duda que se tenía delante**.
 *
 * La huella se **copia tal cual** de lo que devolvió el `GET`. No se calcula aquí a propósito: es
 * opaca, y reproducir la normalización del servidor byte a byte para acabar difiriendo en un
 * espacio produciría un 409 inexplicable. `null` es un valor legítimo — afirma "esta marca no
 * traía duda", que es el caso de 5 de las 44. */
function cuerpoDeConfirmacion(m: MarcaPercepcion): MarcaPercepcionConfirmarIn {
  return {
    es_ingreso_ordinario: m.es_ingreso_ordinario,
    base_exencion: m.base_exencion,
    factor_exencion: m.factor_exencion,
    integra_sbc: m.integra_sbc,
    es_provisionable: m.es_provisionable,
    sujeto_a_tope_conjunto: m.sujeto_a_tope_conjunto,
    nota_revision_hash: m.nota_revision_hash,
  };
}

// --- captura / corrección --------------------------------------------------------------------------

const INPUT_CLASS = 'h-9 border border-border rounded px-2.5 bg-surface';

function Campo({ id, etiqueta, ayuda, children }: { id: string; etiqueta: string; ayuda: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-semibold text-text-muted">{etiqueta}</label>
      {children}
      <span className="text-[11px] text-text-muted text-pretty">{ayuda}</span>
    </div>
  );
}

function CampoSwitch({ id, etiqueta, ayuda, checked, onChange, disabled }: {
  id: string; etiqueta: string; ayuda: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean;
}) {
  return (
    <div className="flex items-start gap-3">
      <Switch id={id} checked={checked} onChange={onChange} disabled={disabled} label={etiqueta} />
      <div className="min-w-0">
        <label htmlFor={id} className="text-[13px] font-semibold">{etiqueta}</label>
        <p className="m-0 text-[11px] text-text-muted text-pretty">{ayuda}</p>
      </div>
    </div>
  );
}

/** Captura o corrección de las marcas de un tipo. **Capturar no confirma**, y este formulario es
 * también donde se resuelve —o se estrecha— la duda declarada, que es parte de revisarla. */
function ModalMarca({
  tipo,
  marca,
  onCerrar,
  onGuardado,
}: {
  tipo: string;
  marca: MarcaPercepcion | null;
  onCerrar: () => void;
  onGuardado: (fila: MarcaPercepcion, estabaConfirmada: boolean) => void;
}) {
  const [ordinario, setOrdinario] = useState(marca?.es_ingreso_ordinario ?? true);
  const [base, setBase] = useState<BaseExencion>(marca?.base_exencion ?? 'NINGUNA');
  const [factor, setFactor] = useState(marca?.factor_exencion ? factorLegible(marca.factor_exencion) : '');
  const [sbc, setSbc] = useState(marca?.integra_sbc ?? false);
  const [provisionable, setProvisionable] = useState(marca?.es_provisionable ?? false);
  const [tope, setTope] = useState(marca?.sujeto_a_tope_conjunto ?? false);
  const [nota, setNota] = useState(marca?.nota_revision ?? '');
  const [error, setError] = useState<string | null>(null);

  const notaLimpia = nota.trim() || null;
  const cambiaronMarcas =
    marca !== null &&
    (marca.es_ingreso_ordinario !== ordinario ||
      marca.base_exencion !== base ||
      // Se comparan **los dos lados normalizados**. Antes se comparaba el factor formateado
      // ("100") contra la cadena cruda tecleada, así que escribir "100.00" avisaba de que la
      // confirmación se iba a perder cuando el servidor compara `Decimal` y la conserva: un aviso
      // que no se cumple enseña a ignorar los avisos.
      factorNormalizado(marca.factor_exencion) !== (base === 'NINGUNA' ? null : factorNormalizado(factor)) ||
      marca.integra_sbc !== sbc ||
      marca.es_provisionable !== provisionable ||
      marca.sujeto_a_tope_conjunto !== tope);
  const dudaNueva = marca !== null && notaLimpia !== null && notaLimpia !== marca.nota_revision;
  const perderaConfirmacion = Boolean(marca?.confirmado) && (cambiaronMarcas || dudaNueva);

  const guardar = useMutation({
    mutationFn: () =>
      api.guardarMarcaPercepcion(tipo, {
        es_ingreso_ordinario: ordinario,
        base_exencion: base,
        // `NINGUNA` exige el factor nulo; el resto lo exige presente. El importe viaja como
        // **cadena**: mandarlo como número JSON lo haría pasar por `float` y el backend lo rechaza.
        factor_exencion: base === 'NINGUNA' ? null : factor.trim(),
        integra_sbc: sbc,
        es_provisionable: provisionable,
        // Los dos campos que **no llevan default** en el servidor: se mandan siempre, incluso
        // cuando no cambian. Omitirlos da 422, y es la respuesta correcta.
        sujeto_a_tope_conjunto: base === 'NINGUNA' ? false : tope,
        nota_revision: notaLimpia,
      }),
    onSuccess: (fila) => onGuardado(fila, Boolean(marca?.confirmado)),
    onError: (e) => {
      if (e instanceof ApiError && e.codigo === 'CATALOGO_SAT_ILEGIBLE') {
        setError(
          'No se pudo verificar la clave contra el catálogo del SAT, así que no se guardó nada. No es algo que tengas ' +
            'que corregir y suele resolverse solo: inténtalo otra vez en un momento.',
        );
        return;
      }
      setError(e instanceof ApiError ? mensajeDe422(e.message) : 'No se pudieron guardar las marcas.');
    },
  });

  const factorNumerico = Number(factor.trim());
  const avisoEscala =
    base === 'PORCENTAJE' && factor.trim() !== '' && Number.isFinite(factorNumerico) && factorNumerico > 0 && factorNumerico < 1
      ? `Escribiste ${factor.trim()}, que en escala 0 a 100 es ${factor.trim()} por ciento del importe (menos de un uno por ciento). Si querías la mitad, escribe 50; si querías todo, escribe 100.`
      : base === 'PORCENTAJE' && Number.isFinite(factorNumerico) && factorNumerico > 100
        ? `${factor.trim()} % exenta más que el importe completo. El máximo con sentido aquí es 100.`
        : null;

  return (
    <Modal titleId="titulo-marca-percepcion" onClose={onCerrar} ancho="amplio">
      <h3 id="titulo-marca-percepcion" className="m-0 text-base font-semibold text-pretty">
        {marca ? 'Corregir' : 'Capturar'} las marcas de <code className="font-mono">{tipo}</code>
        {marca?.descripcion_sat ? ` · ${marca.descripcion_sat}` : ''}
      </h3>
      <p className="m-0 text-[13px] text-text-muted text-pretty">
        Lo que guardes queda <strong>sin confirmar</strong>: se guarda como propuesta y no entra a ningún cálculo de
        exención hasta que lo confirmes.
      </p>

      {perderaConfirmacion && (
        <div role="status" className="bg-warning-soft text-warning rounded-md px-3 py-2 text-[13px] text-pretty flex items-start gap-2">
          <AlertTriangle className="size-4 shrink-0 mt-0.5" aria-hidden />
          <span>
            Este tipo está confirmado y al guardar <strong>volverá a quedar sin confirmar</strong>
            {cambiaronMarcas ? ', porque estás cambiando una de las marcas que calculan' : ''}
            {cambiaronMarcas && dudaNueva ? ' y ' : ''}
            {!cambiaronMarcas && dudaNueva ? ', porque estás dejando una duda que antes no estaba' : ''}
            {cambiaronMarcas && dudaNueva ? 'porque estás dejando una duda distinta de la que había' : ''}. Quien lo
            confirmó revisó otra cosa, así que hará falta confirmarlo de nuevo.
          </span>
        </div>
      )}

      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          // Solo se comprueba aquí la *forma* del dato. Las reglas fiscales (factor positivo, hasta
          // 4 decimales, coherencia con la base) las decide el servidor, que es donde viven y donde
          // no se pueden esquivar; sus mensajes se muestran tal cual porque explican qué corregir.
          if (base !== 'NINGUNA' && !/^\d+(\.\d+)?$/.test(factor.trim())) {
            setError('Escribe el factor como número, con punto decimal y sin separadores de miles (por ejemplo 15 o 100).');
            return;
          }
          guardar.mutate();
        }}
      >
        <CampoSwitch
          id="marca-ordinario"
          etiqueta="Es ingreso ordinario"
          ayuda="Sueldo, horas extra, comisiones y demás conceptos del día a día. Los pagos por separación, las indemnizaciones y las jubilaciones no lo son."
          checked={ordinario}
          onChange={setOrdinario}
        />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Campo
            id="marca-base"
            etiqueta="Base de exención"
            ayuda="Sobre qué se calcula el tramo exento. Sin exención en el artículo 93, elige «Sin exención»: es preferible dejarlo gravado y declarar la duda que inventar un factor."
          >
            <select
              id="marca-base"
              value={base}
              onChange={(e) => {
                const nueva = e.target.value as BaseExencion;
                setBase(nueva);
                // El servidor rechaza con 422 el factor con `NINGUNA` y el tope con `NINGUNA`; el
                // formulario refleja la misma regla en vez de dejar mandar un cuerpo imposible.
                if (nueva === 'NINGUNA') { setFactor(''); setTope(false); }
              }}
              className={INPUT_CLASS}
            >
              <option value="NINGUNA">Sin exención — gravado íntegro</option>
              <option value="UMA_DIAS">Días de UMA</option>
              <option value="SM_DIAS">Días de salario mínimo</option>
              <option value="PORCENTAJE">Porcentaje del importe (escala 0-100)</option>
            </select>
          </Campo>

          {base !== 'NINGUNA' && (
            <Campo
              id="marca-factor"
              etiqueta={base === 'PORCENTAJE' ? 'Porcentaje exento (0 a 100)' : `Factor — ${BASE_EXENCION[base].unidad}`}
              ayuda={BASE_EXENCION[base].ayudaFactor}
            >
              <div className="flex items-center gap-2">
                <input
                  id="marca-factor"
                  required
                  inputMode="decimal"
                  autoComplete="off"
                  value={factor}
                  onChange={(e) => setFactor(e.target.value)}
                  placeholder={base === 'PORCENTAJE' ? '100' : '15'}
                  className={`${INPUT_CLASS} font-mono flex-1 min-w-0`}
                />
                <span className="text-[12px] text-text-muted whitespace-nowrap">{BASE_EXENCION[base].unidad}</span>
              </div>
            </Campo>
          )}
        </div>

        {base === 'PORCENTAJE' && (
          <p className="m-0 text-[12px] text-text-strong bg-info-soft rounded-md px-3 py-2 text-pretty flex items-start gap-2">
            <Info className="size-4 shrink-0 mt-0.5 text-info" aria-hidden />
            <span>
              El porcentaje se captura en <strong>escala 0 a 100, no como fracción</strong>:{' '}
              <code className="font-mono">100</code> = el cien por ciento del importe,{' '}
              <code className="font-mono">50</code> = la mitad, <code className="font-mono">0.5</code> = medio por ciento.
              {factor.trim() !== '' && Number.isFinite(factorNumerico) && (
                <> Con <code className="font-mono">{factor.trim()}</code> se exentaría el <strong>{factor.trim()} %</strong> del importe.</>
              )}
            </span>
          </p>
        )}

        {avisoEscala && (
          <p role="status" className="m-0 text-[12px] bg-warning-soft text-warning rounded-md px-3 py-2 text-pretty">
            {avisoEscala}
          </p>
        )}

        <CampoSwitch
          id="marca-sbc"
          etiqueta="Integra al salario base de cotización"
          ayuda="Artículo 27 de la LSS: todo integra salvo nueve exclusiones tasadas, y varias son parciales (hasta un tope; el excedente sí integra). Esta marca es un sí/no y no puede expresar un tope: si el caso es parcial, déjalo en el supuesto típico y escríbelo en la duda."
          checked={sbc}
          onChange={setSbc}
        />

        <CampoSwitch
          id="marca-provisionable"
          etiqueta="Es provisionable"
          ayuda="Si el concepto es de los que se devengan (aguinaldo, prima vacacional). Informativa: B-08 calcula el pasivo laboral con la clasificación de conceptos de cada empresa, no con esta casilla, así que cambiarla no altera ningún informe — pero sí obliga a volver a confirmar la marca."
          checked={provisionable}
          onChange={setProvisionable}
        />

        <CampoSwitch
          id="marca-tope"
          etiqueta="Sujeto al tope conjunto de previsión social"
          ayuda={
            base === 'NINGUNA'
              ? 'No aplica sin exención: el tope limita una exención y aquí no hay ninguna que limitar (el servidor lo rechaza).'
              : 'Penúltimo párrafo del artículo 93: la SUMA de las exenciones de previsión social de un trabajador se limita a 1 UMA anual cuando el sueldo más la exención pasan de 7 UMA anuales. Aplica a becas, vales de despensa y de restaurante, ayuda para artículos escolares, anteojos y gastos de funeral. El párrafo EXCEPTÚA a jubilaciones y pensiones, indemnizaciones por riesgos de trabajo, reembolsos y seguros de gastos médicos, seguros de vida, gastos de funeral y fondos de ahorro. Es una marca aparte porque el tope se aplica sobre la suma, no sobre el factor de este tipo.'
          }
          checked={tope}
          onChange={setTope}
          disabled={base === 'NINGUNA'}
        />

        <Campo
          id="marca-nota"
          etiqueta="Duda declarada (obligatoria — vacío significa «ya no hay duda»)"
          ayuda="Qué genera la incertidumbre en este tipo y qué habría que verificar antes de darlo por bueno. Es lo que va a leer quien lo confirme. Dejarla vacía es afirmar que la duda quedó resuelta: nunca se borra sola, y si la dejas o la cambias este tipo vuelve a quedar sin confirmar."
        >
          <textarea
            id="marca-nota"
            rows={4}
            value={nota}
            onChange={(e) => setNota(e.target.value)}
            placeholder="Sin duda declarada."
            className="border border-border rounded px-2.5 py-2 text-[13px] bg-surface resize-y"
          />
        </Campo>

        {marca?.nota_revision && notaLimpia === null && (
          <p role="status" className="m-0 text-[12px] bg-info-soft text-text-strong rounded-md px-3 py-2 text-pretty">
            Vas a <strong>borrar</strong> la duda declarada de este tipo. Se guarda como "sin duda", que es afirmar que la
            verificaste. Resolver una duda no quita ninguna confirmación.
          </p>
        )}

        {error && <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] text-pretty">{error}</div>}

        <div className="flex gap-2 justify-end">
          <Button type="button" variant="secondary" onClick={onCerrar}>Cancelar</Button>
          <Button type="submit" loading={guardar.isPending} disabled={guardar.isPending}>Guardar sin confirmar</Button>
        </div>
      </form>
    </Modal>
  );
}
