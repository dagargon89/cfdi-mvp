// Lo que comparten las dos secciones de la pestaña Fiscal (valores de `param_fiscal` y marcas de
// `catalogo_percepcion_marca`): los tres estados del invariante y el formato de importes y fuentes. Las fechas se formatean con
// `@/lib/fechas`, como en el resto de la interfaz.
//
// Archivo sin JSX a propósito — el chip vive en `ChipEstadoFiscal.tsx`, para no mezclar
// componentes con utilidades en el mismo módulo (regla `react-refresh/only-export-components`).

/** Los tres estados que el invariante "un valor sin confirmar no calcula" obliga a distinguir:
 * `confirmado` calcula, `propuesto` existe pero no calcula, `ausente` ni siquiera existe. */
export type EstadoFiscal = 'confirmado' | 'propuesto' | 'ausente';

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
