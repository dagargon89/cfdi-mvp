// Lo que comparten las dos secciones de la pestaña Fiscal (valores de `param_fiscal` y marcas de
// `catalogo_percepcion_marca`): los tres estados del invariante y el formato de fechas.
//
// Archivo sin JSX a propósito — el chip vive en `ChipEstadoFiscal.tsx`, para no mezclar
// componentes con utilidades en el mismo módulo (regla `react-refresh/only-export-components`).

/** Los tres estados que el invariante "un valor sin confirmar no calcula" obliga a distinguir:
 * `confirmado` calcula, `propuesto` existe pero no calcula, `ausente` ni siquiera existe. */
export type EstadoFiscal = 'confirmado' | 'propuesto' | 'ausente';

const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

/** "2026-02-01" → "1 de febrero de 2026". Parte la cadena a mano: `new Date('2026-02-01')` la
 * interpreta como UTC y en un huso negativo (el nuestro) mostraría el día anterior. */
export function fechaLegible(iso: string): string {
  const [a, m, d] = iso.slice(0, 10).split('-').map(Number);
  if (!a || !m || !d) return iso;
  return `${d} de ${MESES[m - 1]} de ${a}`;
}

/** Las marcas de tiempo (`confirmado_en`, `sincronizado_en`) llegan **sin zona y en UTC** —así son
 * todas las columnas `DateTime` del proyecto—, así que hay que decírselo al navegador antes de
 * darles formato: sin la `Z`, un "2026-08-07 00:40" de UTC se leía como local y la pantalla decía
 * que el valor se confirmó el 7 de agosto cuando aquí eran las 18:40 del 6. */
export function fechaHoraLegible(isoUtc: string): string {
  const d = new Date(`${isoUtc.replace(' ', 'T').replace(/Z$/, '')}Z`);
  if (Number.isNaN(d.getTime())) return fechaLegible(isoUtc);
  return `${d.getDate()} de ${MESES[d.getMonth()]} de ${d.getFullYear()} a las ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** Un número decimal tal como llega ("117.310000", "0.064000"), sin los ceros de relleno, que no
 * son información — sirve tanto para importes como para fracciones (tasas, factores). Nunca pasa
 * por `Number`: los contratos fiscales mandan estas cifras como cadena justamente para que no las
 * toque un `float`, y esta función solo recorta texto. */
export function importeLegible(valor: string): string {
  if (!valor.includes('.')) return valor;
  const recortado = valor.replace(/0+$/, '').replace(/\.$/, '');
  return recortado === '' ? valor : recortado;
}

/** La fuente de un valor fiscal es texto libre que suele traer la URL del boletín o del DOF
 * dentro. Se parte para poder ofrecerla como liga: revisar el valor contra su fuente es lo que se
 * le pide a quien confirma, y obligarlo a copiar una URL a mano es pedirle que no lo haga. */
export function partirFuente(fuente: string): { texto: string; url: string | null } {
  const encontrado = /(https?:\/\/[^\s)]+)/.exec(fuente);
  if (!encontrado) return { texto: fuente, url: null };
  return { texto: fuente.replace(encontrado[1], '').replace(/[—–-]\s*$/, '').trim(), url: encontrado[1] };
}
