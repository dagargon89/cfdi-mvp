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
