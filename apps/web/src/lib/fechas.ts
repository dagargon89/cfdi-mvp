// Formato único de fechas en la interfaz: `dd/mm/aaaa` y, si el dato trae hora, `dd/mm/aaaa HH:mm`
// (24 horas). Toda fecha que se muestre pasa por aquí — nunca `slice`, `toLocaleString` ni la
// cadena ISO tal cual.
//
// Hay tres tipos de dato y cada uno tiene su función, porque no se tratan igual:
//   - `fecha`: solo día ("2026-09-01", o la parte de fecha de un timestamp). Se parte el texto a
//     mano: `new Date('2026-09-01')` lo lee como UTC y en nuestro huso (negativo) mostraría el 31.
//   - `fechaHora`: marcas de tiempo del servidor (`created_at`, `updated_at`, `*_en`...). Llegan en
//     UTC y **sin zona** —así son todas las columnas `DateTime` del backend—, así que se les añade la
//     `Z` y se muestran en la hora local del navegador.
//   - `fechaHoraSinZona`: fechas que ya vienen en hora local de su origen y no deben convertirse —
//     la `fecha_emision` de un CFDI es la hora del emisor, no UTC.

const SIN_DATO = '—';

function dos(n: number): string {
  return String(n).padStart(2, '0');
}

/** "2026-09-01" o "2026-09-01T16:21:52" → "01/09/2026". */
export function fecha(valor: string | null | undefined): string {
  if (!valor) return SIN_DATO;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(valor);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : valor;
}

/** Marca de tiempo del servidor (UTC sin zona) → "06/10/2026 13:06" en la hora local. */
export function fechaHora(valor: string | null | undefined): string {
  if (!valor) return SIN_DATO;
  const d = new Date(`${valor.replace(' ', 'T').replace(/(Z|[+-]\d{2}:?\d{2})$/, '')}Z`);
  if (Number.isNaN(d.getTime())) return fecha(valor);
  return `${dos(d.getDate())}/${dos(d.getMonth() + 1)}/${d.getFullYear()} ${dos(d.getHours())}:${dos(d.getMinutes())}`;
}

/** Fecha y hora que se muestran tal como vienen, sin conversión de zona (p. ej. la emisión de un
 * CFDI) → "01/09/2026 16:21". Si no trae hora, solo la fecha. */
export function fechaHoraSinZona(valor: string | null | undefined): string {
  if (!valor) return SIN_DATO;
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(valor);
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : fecha(valor);
}

/** "2026-05" → "05/2026" (periodos de un mes). */
export function mes(valor: string | null | undefined): string {
  if (!valor) return SIN_DATO;
  const m = /^(\d{4})-(\d{2})/.exec(valor);
  return m ? `${m[2]}/${m[1]}` : valor;
}

/** Rango de días: "01/09/2026 → 30/09/2026". */
export function rango(desde: string | null | undefined, hasta: string | null | undefined): string {
  return `${fecha(desde)} → ${fecha(hasta)}`;
}
