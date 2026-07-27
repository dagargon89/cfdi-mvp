// Reglas de dominio puras, sin estado — portadas de la lógica del prototipo (Component.renderVals()
// en el .dc.html de Claude Design). Reutilizadas tanto por la UI (preview antes de enviar al backend)
// como por lib/api.mock.ts (cálculo de resultados simulados).
import type { ConfiguracionItem } from './api';

export function diasParaVencer(notAfter: string, hoy: Date = new Date()): number {
  const fin = new Date(notAfter.slice(0, 10));
  return Math.round((fin.getTime() - new Date(hoy.toISOString().slice(0, 10)).getTime()) / 86_400_000);
}

export function umbralVigenciaDias(config: ConfiguracionItem[]): number {
  return Number(config.find((c) => c.clave === 'umbral_vigencia_dias')?.valor ?? 15);
}

export function maxMesesVentana(config: ConfiguracionItem[]): number {
  return Number(config.find((c) => c.clave === 'max_meses_ventana')?.valor ?? 12);
}

export function money(n: number): string {
  return new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' }).format(n);
}

export function fechaCorta(s: string | null): string {
  return s ? s.slice(0, 10) : '—';
}

export interface Ventana {
  desde: string;
  hasta: string;
  label: string;
}

/** Trocea [desde, hasta] en ventanas de máximo `maxMeses` meses (RF-DESC-01/03, doc 09 §5 preview). */
export function ventanasDe(desde: string, hasta: string, maxMeses: number): Ventana[] {
  const out: Ventana[] = [];
  let d = new Date(desde);
  const fin = new Date(hasta);
  if (Number.isNaN(d.getTime()) || Number.isNaN(fin.getTime()) || d > fin) return out;
  let guard = 0;
  while (d <= fin && guard++ < 40) {
    const corte = new Date(d);
    corte.setMonth(corte.getMonth() + maxMeses);
    corte.setDate(corte.getDate() - 1);
    const f = corte > fin ? fin : corte;
    const desdeStr = d.toISOString().slice(0, 10);
    const hastaStr = f.toISOString().slice(0, 10);
    out.push({ desde: desdeStr, hasta: hastaStr, label: `${desdeStr} → ${hastaStr}` });
    d = new Date(f);
    d.setDate(d.getDate() + 1);
  }
  return out;
}
