// Configuración de una organización — /e/:id/configuracion.
//
// **Por qué vive aquí y no como otra pestaña de /admin/config** (la decisión que el brief pedía
// justificar): todo /admin/* está detrás de `RequireAdmin` y el ítem del sidebar solo existe para
// el rol admin, pero el backend abrió esta configuración a más gente a propósito — `GET` pide
// CONSULTA y `PUT` pide OPERADOR (`app/api/v1/configuracion.py`), con el argumento de que un
// usuario de consulta ya puede generar los informes cuyo resultado depende de la zona salarial, y
// esconderle la entrada mientras se le muestra la salida no protege nada. Montarla bajo /admin la
// habría cerrado justo a los operadores que la usan. Además es configuración *de una empresa*, y
// /admin/config no tiene empresa en la URL: todas las pantallas con `empresa_id` viven en /e/:id/*.
//
// Las dos mitades de la pantalla responden a dos preguntas distintas:
//   1. Política laboral: tres campos que nacen vacíos y que **degradan informes** mientras lo estén.
//   2. Clasificación: qué es cada concepto que la nómina de esta empresa emitió. La lista la trae
//      el servidor (`conceptos-observados`) porque nadie conoce de memoria las claves internas de
//      su sistema de nómina: se reconoce la descripción y se elige categoría, nunca se teclea una
//      clave.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/ToastProvider';
import { useEmpresaCtx } from '@/empresa/EmpresaContext';
import { ApiError } from '@/lib/api';
import type { CategoriaProvision, ConceptoObservado, MapeosEmpresa, ZonaSalarial } from '@/lib/api';
import { api } from '@/lib/client';

const INPUT_CLASS = 'h-9 border border-border rounded px-2.5';

const CATEGORIAS: { valor: CategoriaProvision; etiqueta: string }[] = [
  { valor: 'AGUINALDO', etiqueta: 'Aguinaldo' },
  { valor: 'VACACIONES', etiqueta: 'Vacaciones' },
  { valor: 'PRIMA_VACACIONAL', etiqueta: 'Prima vacacional' },
  // No es relleno: es lo que permite que la clasificación esté *completa*. Sin esta opción,
  // "este concepto no es ninguna de las tres" sería indistinguible de "todavía no lo he mirado".
  { valor: 'NO_APLICA', etiqueta: 'Ninguna de las anteriores' },
];

const ZONAS: { valor: ZonaSalarial; etiqueta: string; ayuda: string }[] = [
  { valor: 'GENERAL', etiqueta: 'Resto del país (salario mínimo general)', ayuda: 'Aplica a toda la República salvo los municipios de la franja fronteriza norte.' },
  { valor: 'ZLFN', etiqueta: 'Zona Libre de la Frontera Norte', ayuda: 'Municipios fronterizos del norte, con un salario mínimo bastante más alto que el general.' },
];

function claveDeConcepto(c: { naturaleza: string; tipo: string; clave: string | null }): string {
  return `${c.naturaleza}/${c.tipo}/${c.clave ?? '—'}`;
}

/** El importe llega como cadena y así se muestra: `Number()` perdería la escala almacenada. Solo
 * se agrupan los miles para poder leerlo. */
function importeLegible(valor: string): string {
  const [enteros, decimales] = valor.split('.');
  const conMiles = enteros.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return decimales ? `${conMiles}.${decimales.slice(0, 2)}` : conMiles;
}

export function ConfiguracionEmpresaPage() {
  const { empresa, puedeMutar } = useEmpresaCtx();

  return (
    <div className="flex flex-col gap-5">
      {!puedeMutar && (
        <div className="bg-surface-alt border border-border rounded-md px-3 py-2 text-[13px] text-text-muted text-pretty">
          Tu rol en esta empresa es de <strong>consulta</strong>: puedes ver cómo está configurada y por qué los informes
          salen como salen, pero no cambiarla. Para modificarla pide el rol de operador a un administrador.
        </div>
      )}
      <PoliticaLaboral empresaId={empresa.empresa_id} puedeMutar={puedeMutar} />
      <Clasificacion empresaId={empresa.empresa_id} puedeMutar={puedeMutar} />
    </div>
  );
}

// --- 1. Política laboral -----------------------------------------------------------------------

function PoliticaLaboral({ empresaId, puedeMutar }: { empresaId: number; puedeMutar: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data } = useQuery({ queryKey: ['configuracion-empresa', empresaId], queryFn: () => api.obtenerConfiguracionEmpresa(empresaId) });

  const [zona, setZona] = useState<'' | ZonaSalarial>('');
  const [aguinaldo, setAguinaldo] = useState('');
  const [prima, setPrima] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setZona(data.zona_salarial ?? '');
    setAguinaldo(data.dias_aguinaldo === null ? '' : String(data.dias_aguinaldo));
    setPrima(data.factor_prima_vacacional === null ? '' : data.factor_prima_vacacional);
  }, [data]);

  const guardar = useMutation({
    mutationFn: () =>
      api.guardarConfiguracionEmpresa(empresaId, {
        zona_salarial: zona === '' ? null : zona,
        dias_aguinaldo: aguinaldo.trim() === '' ? null : Number(aguinaldo),
        // El factor viaja como **cadena**: un número JSON pasa por `float` y el backend lo rechaza.
        factor_prima_vacacional: prima.trim() === '' ? null : prima.trim(),
      }),
    onSuccess: (fila) => {
      qc.setQueryData(['configuracion-empresa', empresaId], fila);
      toast('Configuración de la empresa guardada', 'ok');
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'No se pudo guardar la configuración.'),
  });

  const faltantes = [
    data?.zona_salarial ? null : 'zona salarial',
    data?.dias_aguinaldo === null || data?.dias_aguinaldo === undefined ? 'días de aguinaldo' : null,
    data?.factor_prima_vacacional ? null : 'factor de prima vacacional',
  ].filter((x): x is string => x !== null);

  return (
    <section className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3 max-w-3xl">
      <div>
        <h3 className="m-0 text-[15px] font-semibold">Política laboral de esta organización</h3>
        <p className="m-0 mt-1 text-[13px] text-text-muted text-pretty">
          Tres datos que la ley deja a cada patrón y que ningún CFDI trae. <strong>Nacen vacíos a propósito</strong>: no
          hay valor por omisión razonable, y suponer uno daría por buenos cálculos que nadie revisó.
        </p>
      </div>

      {data && faltantes.length > 0 && (
        <div role="status" className="bg-warning-soft text-warning rounded-md px-3 py-2.5 text-[13px] flex items-start gap-2">
          <AlertTriangle className="size-4 shrink-0 mt-0.5" aria-hidden />
          {/* Las dos cifras de los mínimos vivían escritas aquí, en la única pantalla cuya tesis
              es que no hay valor por omisión razonable. Coincidían hoy y el 1 de enero mentirían
              sin que nada las actualizara — y las de verdad están en Configuración → Fiscal, que
              esta pantalla no puede leer (es de admin). Mejor decir el hecho, que no caduca, que
              una cifra que sí. */}
          <span className="text-pretty">
            Falta {faltantes.join(', ')}. Mientras tanto: <strong>sin zona salarial, B-10 no evalúa si un salario quedó
            por debajo del mínimo</strong> — el mínimo de la Zona Libre de la Frontera Norte es bastante más alto que el
            general, así que dar por hecho el general convertiría incumplimientos reales en "todo en orden". Sin días de
            aguinaldo ni factor de prima, la provisión de pasivo laboral no se puede estimar.
          </span>
        </div>
      )}

      <form
        className="flex flex-col gap-3.5"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          guardar.mutate();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <label htmlFor="zona-salarial" className="text-xs font-semibold text-text-muted">Zona salarial (art. 94 LFT)</label>
          <select id="zona-salarial" value={zona} disabled={!puedeMutar} onChange={(e) => setZona(e.target.value as '' | ZonaSalarial)} className={INPUT_CLASS}>
            <option value="">— Sin elegir —</option>
            {ZONAS.map((z) => (
              <option key={z.valor} value={z.valor}>{z.etiqueta}</option>
            ))}
          </select>
          <span className="text-[11px] text-text-muted">{ZONAS.find((z) => z.valor === zona)?.ayuda ?? 'Decide contra qué salario mínimo se comparan los sueldos de esta empresa.'}</span>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="dias-aguinaldo" className="text-xs font-semibold text-text-muted">Días de aguinaldo</label>
            <input
              id="dias-aguinaldo"
              type="number"
              min={1}
              max={365}
              step={1}
              value={aguinaldo}
              disabled={!puedeMutar}
              onChange={(e) => setAguinaldo(e.target.value)}
              placeholder="15"
              className={`${INPUT_CLASS} font-mono`}
            />
            <span className="text-[11px] text-text-muted">El mínimo legal son 15 días (art. 87 LFT); muchos patrones dan más.</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="factor-prima" className="text-xs font-semibold text-text-muted">Factor de prima vacacional</label>
            <input
              id="factor-prima"
              inputMode="decimal"
              autoComplete="off"
              value={prima}
              disabled={!puedeMutar}
              onChange={(e) => setPrima(e.target.value)}
              placeholder="0.25"
              className={`${INPUT_CLASS} font-mono`}
            />
            <span className="text-[11px] text-text-muted">Proporción sobre el salario de los días de vacaciones. El mínimo legal es 0.25 (art. 80 LFT).</span>
          </div>
        </div>

        {error && <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] text-pretty">{error}</div>}

        {puedeMutar && (
          <div className="flex justify-end">
            <Button type="submit" loading={guardar.isPending} disabled={guardar.isPending}>Guardar</Button>
          </div>
        )}
      </form>
    </section>
  );
}

// --- 2. Clasificación de lo que la nómina emitió -----------------------------------------------

function Clasificacion({ empresaId, puedeMutar }: { empresaId: number; puedeMutar: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: observados, isLoading } = useQuery({
    queryKey: ['conceptos-observados', empresaId],
    queryFn: () => api.obtenerConceptosObservados(empresaId),
  });
  // **Lo que ya está guardado**, que no es lo mismo que lo observado. El `PUT` reemplaza las dos
  // listas completas, así que reconstruirlas solo desde `conceptos-observados` borraba en silencio
  // cualquier renglón almacenado cuya clave natural no apareciera ahí: un concepto que la nómina
  // dejó de emitir, un departamento que cambió de nombre, o cualquier fila que alguien haya
  // capturado por API. Guardar la clasificación no puede tener el efecto colateral de olvidar lo
  // que no se estaba mirando.
  const { data: guardados, isLoading: cargandoGuardados, isError: errorGuardados } = useQuery({
    queryKey: ['mapeos-empresa', empresaId],
    queryFn: () => api.obtenerMapeosEmpresa(empresaId),
  });

  // Estado editable de las dos listas. La categoría vive por concepto y el centro de costo por
  // departamento; el `PUT` reemplaza las dos completas, así que se mandan siempre juntas.
  const [categorias, setCategorias] = useState<Record<string, CategoriaProvision | ''>>({});
  const [centros, setCentros] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!observados) return;
    setCategorias(Object.fromEntries(observados.conceptos.map((c) => [claveDeConcepto(c), c.categoria ?? ''])));
    setCentros(Object.fromEntries(observados.departamentos.map((d) => [d.departamento_texto, d.centro_costo ?? ''])));
  }, [observados]);

  const guardar = useMutation({
    mutationFn: () => {
      // Se parte de **lo almacenado** y encima se aplican los cambios de esta pantalla. Los
      // renglones que no se están editando —los que no aparecen en `conceptos-observados`— viajan
      // igual, así que el reemplazo total del `PUT` deja de ser una pérdida silenciosa.
      const departamentos = new Map((guardados?.departamentos ?? []).map((d) => [d.departamento_texto, d.centro_costo]));
      for (const [texto, centro] of Object.entries(centros)) {
        if (centro.trim() === '') departamentos.delete(texto); // vaciar el campo sí es desagrupar
        else departamentos.set(texto, centro.trim());
      }

      const conceptos = new Map(
        (guardados?.conceptos_provision ?? []).map((c) => [claveDeConcepto(c), c] as const),
      );
      for (const c of observados?.conceptos ?? []) {
        if (c.clave === null) continue; // sin clave no hay PK: no se puede clasificar
        const clave = claveDeConcepto(c);
        const categoria = categorias[clave];
        if (!categoria) conceptos.delete(clave); // volver a "— Sin clasificar —" sí borra
        else conceptos.set(clave, { naturaleza: c.naturaleza, tipo: c.tipo, clave: c.clave, categoria });
      }

      const cuerpo: MapeosEmpresa = {
        departamentos: [...departamentos].map(([departamento_texto, centro_costo]) => ({ departamento_texto, centro_costo })),
        conceptos_provision: [...conceptos.values()],
      };
      return api.guardarMapeosEmpresa(empresaId, cuerpo);
    },
    onSuccess: (fila) => {
      qc.setQueryData(['mapeos-empresa', empresaId], fila);
      void qc.invalidateQueries({ queryKey: ['conceptos-observados', empresaId] });
      toast('Clasificación guardada', 'ok');
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'No se pudo guardar la clasificación.'),
  });

  if (isLoading || cargandoGuardados) return <p className="text-text-muted text-[13px]">Cargando lo que la nómina de esta empresa emitió…</p>;
  if (!observados) return null;

  // **Solo percepciones.** Lo que B-08 concilia es cuánto se pagó ya de aguinaldo, vacaciones y
  // prima vacacional, y eso son percepciones por definición: una deducción no puede ser aguinaldo
  // —el aguinaldo no se le descuenta a nadie— y `c_TipoOtroPago` son subsidios, viáticos y
  // reintegros. Contarlas dejaba el marcador clavado en un número que solo bajaba capturando
  // `NO_APLICA` en renglones que nunca debieron entrar: trabajo sin sentido. El criterio es el
  // mismo que `percepciones_sin_clasificar` en el backend y en la herramienta de terminal; si lo
  // cambias aquí, cámbialo en los tres o volverán a decir cosas distintas el mismo día.
  const clasificables = observados.conceptos.filter((c) => c.naturaleza === 'P' && c.clave !== null);
  const sinClasificarAhora = clasificables.filter((c) => !categorias[claveDeConcepto(c)]).length;
  const sinMapearAhora = observados.departamentos.filter((d) => !centros[d.departamento_texto]?.trim()).length;
  const sinClave = observados.conceptos.filter((c) => c.clave === null);

  return (
    <section className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-4">
      <div>
        <h3 className="m-0 text-[15px] font-semibold">Qué es cada concepto de tu nómina</h3>
        <p className="m-0 mt-1 text-[13px] text-text-muted text-pretty max-w-[80ch]">
          Esta lista no la inventamos: son los conceptos y departamentos que <strong>aparecen de verdad</strong> en los
          CFDI de nómina que esta empresa emitió. Las claves las pone tu sistema de nómina, así que no hay que
          teclearlas: reconoce la descripción y elige de la lista.
        </p>
      </div>

      {observados.conceptos.length === 0 ? (
        <p className="m-0 text-[13px] text-text-muted">
          Todavía no hay CFDI de nómina emitidos por esta empresa, así que no hay nada que clasificar.
        </p>
      ) : (
        <>
          <div
            role="status"
            className={`rounded-md px-3 py-2.5 text-[13px] flex items-start gap-2 ${sinClasificarAhora === 0 ? 'bg-success-soft text-success' : 'bg-warning-soft text-warning'}`}
          >
            {sinClasificarAhora === 0 ? <CheckCircle2 className="size-4 shrink-0 mt-0.5" aria-hidden /> : <AlertTriangle className="size-4 shrink-0 mt-0.5" aria-hidden />}
            <span className="text-pretty">
              {sinClasificarAhora === 0 ? (
                <>
                  Las {clasificables.length} percepciones con clave están clasificadas. Con la clasificación completa, el
                  informe de provisión de pasivo laboral (B-08) puede generarse: sabe que un aguinaldo pagado de cero es
                  un hecho y no un hueco.
                </>
              ) : (
                <>
                  Te faltan <strong>{sinClasificarAhora}</strong> de {clasificables.length} percepciones por clasificar.
                  Hasta que no quede ninguna, <strong>B-08 (provisión de pasivo laboral) no se puede generar</strong>: con
                  una sola percepción sin revisar, "no se pagó aguinaldo" es indistinguible de "sí se pagó y no sé en cuál
                  concepto viene". Las deducciones y los otros pagos no cuentan: no puede haberse pagado aguinaldo en un
                  descuento.
                </>
              )}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table>
              <caption className="sr-only">Conceptos de nómina observados y su categoría de provisión</caption>
              <thead>
                <tr className="bg-surface-alt">
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Como lo llama tu nómina</th>
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Tipo del catálogo del SAT</th>
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Clave</th>
                  <th scope="col" className="text-right text-xs font-semibold px-3 py-2">CFDI</th>
                  <th scope="col" className="text-right text-xs font-semibold px-3 py-2">Importe</th>
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Es…</th>
                </tr>
              </thead>
              <tbody>
                {observados.conceptos.map((c) => (
                  <FilaConcepto
                    key={claveDeConcepto(c)}
                    concepto={c}
                    valor={categorias[claveDeConcepto(c)] ?? ''}
                    puedeMutar={puedeMutar}
                    onCambiar={(v) => setCategorias((s) => ({ ...s, [claveDeConcepto(c)]: v }))}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {sinClave.length > 0 && (
            <p className="m-0 text-[12px] text-text-muted text-pretty">
              {sinClave.length === 1 ? 'Un concepto viene' : `${sinClave.length} conceptos vienen`} sin clave en el CFDI.
              No se {sinClave.length === 1 ? 'puede' : 'pueden'} clasificar (la clave es lo que identifica al concepto) y
              tampoco {sinClave.length === 1 ? 'cuenta' : 'cuentan'} como pendiente. Es un dato que tendría que corregir
              quien emite la nómina.
            </p>
          )}
        </>
      )}

      {observados.departamentos.length > 0 && (
        <>
          <div className="border-t border-border pt-3">
            <h4 className="m-0 text-[14px] font-semibold">Departamentos y centros de costo</h4>
            <p className="m-0 mt-1 text-[13px] text-text-muted text-pretty max-w-[80ch]">
              Los departamentos tal como vienen escritos en la nómina. Agrúpalos en centros de costo para que el informe
              de costo de nómina (B-06) sume por centro; {sinMapearAhora > 0 ? `mientras falten (${sinMapearAhora}), agrupa por el texto crudo y lo avisa.` : 'ya están todos agrupados.'}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table>
              <caption className="sr-only">Departamentos observados y su centro de costo</caption>
              <thead>
                <tr className="bg-surface-alt">
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Departamento en la nómina</th>
                  <th scope="col" className="text-right text-xs font-semibold px-3 py-2">CFDI</th>
                  <th scope="col" className="text-left text-xs font-semibold px-3 py-2">Centro de costo</th>
                </tr>
              </thead>
              <tbody>
                {observados.departamentos.map((d) => (
                  <tr key={d.departamento_texto} className="border-t border-border">
                    <td className="px-3 py-2 font-mono text-xs">{d.departamento_texto}</td>
                    <td className="px-3 py-2 text-right text-[13px] tabular-nums">{d.comprobantes}</td>
                    <td className="px-3 py-2">
                      <input
                        aria-label={`Centro de costo de ${d.departamento_texto}`}
                        value={centros[d.departamento_texto] ?? ''}
                        disabled={!puedeMutar}
                        onChange={(e) => setCentros((s) => ({ ...s, [d.departamento_texto]: e.target.value }))}
                        placeholder="Sin agrupar"
                        className={`${INPUT_CLASS} w-full max-w-[260px]`}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {error && <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] text-pretty">{error}</div>}

      {/* Sin saber qué hay guardado no se puede guardar: el `PUT` reemplaza las dos listas
          completas, así que mandarlas armadas solo con lo que se ve borraría lo que no se ve. */}
      {errorGuardados && (
        <div role="alert" className="bg-warning-soft text-warning rounded-md px-2.5 py-2 text-[13px] text-pretty">
          No se pudo leer la clasificación que ya estaba guardada, así que no se puede guardar ahora: al guardar se
          reemplaza la lista completa, y hacerlo a ciegas borraría los renglones que hoy no aparecen en esta pantalla.
          Vuelve a cargarla en un momento.
        </div>
      )}

      {puedeMutar && !errorGuardados && (observados.conceptos.length > 0 || observados.departamentos.length > 0) && (
        <div className="flex justify-end">
          <Button type="button" loading={guardar.isPending} disabled={guardar.isPending} onClick={() => { setError(null); guardar.mutate(); }}>
            Guardar clasificación
          </Button>
        </div>
      )}
    </section>
  );
}

function FilaConcepto({
  concepto,
  valor,
  puedeMutar,
  onCambiar,
}: {
  concepto: ConceptoObservado;
  valor: CategoriaProvision | '';
  puedeMutar: boolean;
  onCambiar: (v: CategoriaProvision | '') => void;
}) {
  const sinClave = concepto.clave === null;
  // Solo las percepciones se clasifican; ver el comentario de `clasificables`. Ofrecer
  // "Aguinaldo" en el renglón de una deducción era la invitación de verdad a capturar tonterías.
  const esPercepcion = concepto.naturaleza === 'P';
  return (
    <tr className="border-t border-border">
      <td className="px-3 py-2 text-[13px] font-medium">{concepto.concepto ?? '(sin descripción)'}</td>
      <td className="px-3 py-2 text-[13px] text-text-muted">
        <span className="font-mono text-xs">{concepto.tipo}</span> {concepto.descripcion_sat ?? ''}
      </td>
      <td className="px-3 py-2 font-mono text-xs text-text-muted">{concepto.naturaleza}/{concepto.clave ?? '—'}</td>
      <td className="px-3 py-2 text-right text-[13px] tabular-nums">{concepto.comprobantes}</td>
      <td className="px-3 py-2 text-right font-mono text-xs tabular-nums">{importeLegible(concepto.importe)}</td>
      <td className="px-3 py-2">
        {sinClave ? (
          <span className="text-[12px] text-text-muted">Sin clave: no se puede clasificar</span>
        ) : !esPercepcion ? (
          <span className="text-[12px] text-text-muted">
            No participa: solo las percepciones se clasifican
            {valor ? ` (guardado: ${CATEGORIAS.find((c) => c.valor === valor)?.etiqueta ?? valor})` : ''}
          </span>
        ) : (
          <select
            aria-label={`Categoría de ${concepto.concepto ?? claveDeConcepto(concepto)}`}
            value={valor}
            disabled={!puedeMutar}
            onChange={(e) => onCambiar(e.target.value as CategoriaProvision | '')}
            className={`${INPUT_CLASS} min-w-[200px]`}
            style={valor === '' ? { borderColor: 'var(--warning)' } : undefined}
          >
            <option value="">— Sin clasificar —</option>
            {CATEGORIAS.map((c) => (
              <option key={c.valor} value={c.valor}>{c.etiqueta}</option>
            ))}
          </select>
        )}
      </td>
    </tr>
  );
}
