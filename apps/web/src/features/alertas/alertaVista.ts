// demo.html:1209-1221 (alertaVista) — compartido entre TableroPage (preview) y AlertasPage (lista completa).
import { AlertTriangle, Clock, KeyRound, type LucideIcon } from 'lucide-react';
import type { Evento } from '@/lib/api';
import { money } from '@/lib/domain';

export interface AlertaVista {
  fg: string;
  bg: string;
  Icon: LucideIcon;
  tipo: string;
  titulo: string;
  detalle: string;
  uuids: string[] | null;
  createdAt: string;
  accionTexto: string;
  accionHref: string;
}

export function alertaVista(ev: Evento, empresaId: number): AlertaVista {
  const createdAt = ev.created_at.slice(0, 16);
  if (ev.tipo === 'efos') {
    const d = ev.detalle as { rfc: string; situacion: string; uuids: string[]; total_afectado: number };
    return {
      fg: 'text-danger', bg: 'bg-danger-soft', Icon: AlertTriangle, tipo: 'efos',
      titulo: 'Emisor en lista 69-B',
      detalle: `RFC ${d.rfc} con situación ${d.situacion}. ${d.uuids.length} comprobante(s) por ${money(d.total_afectado)} podrían no ser deducibles.`,
      uuids: d.uuids, createdAt,
      accionTexto: 'Ver comprobantes del emisor',
      accionHref: `/e/${empresaId}/comprobantes?q=${encodeURIComponent(d.rfc)}`,
    };
  }
  if (ev.tipo === 'cancelacion_tardia') {
    const d = ev.detalle as { uuid: string; mes_emision: string; detectado: string };
    return {
      fg: 'text-warning', bg: 'bg-warning-soft', Icon: Clock, tipo: 'cancelacion_tardia',
      titulo: 'Cancelación tardía detectada',
      detalle: `Comprobante emitido en ${d.mes_emision} y cancelado en ${d.detectado.slice(0, 7)}. Afecta un ejercicio ya declarado.`,
      uuids: [d.uuid], createdAt,
      accionTexto: 'Abrir comprobante',
      accionHref: `/e/${empresaId}/comprobantes?q=${encodeURIComponent(d.uuid)}`,
    };
  }
  const d = ev.detalle as { not_after: string; dias_restantes: number };
  return {
    fg: 'text-warning', bg: 'bg-warning-soft', Icon: KeyRound, tipo: 'efirma_por_vencer',
    titulo: 'e.firma por vencer',
    detalle: `Vence el ${d.not_after} — quedan ${d.dias_restantes} días.`,
    uuids: null, createdAt,
    accionTexto: 'Ir a la bóveda',
    accionHref: `/e/${empresaId}/efirma`,
  };
}
