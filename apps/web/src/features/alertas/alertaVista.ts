// demo.html:1209-1221 (alertaVista) — compartido entre TableroPage (preview) y AlertasPage (lista completa).
import { AlertTriangle, Clock, KeyRound, RefreshCw, type LucideIcon } from 'lucide-react';
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
  if (ev.tipo === 'resumen_sync') {
    const d = ev.detalle as { fecha?: string; empresas?: number };
    return {
      fg: 'text-info', bg: 'bg-info-soft', Icon: RefreshCw, tipo: 'resumen_sync',
      titulo: 'Sincronización diaria',
      detalle: `Sincronización del ${d.fecha ?? '—'}: ${d.empresas ?? 0} empresa(s) procesada(s).`,
      uuids: null, createdAt,
      accionTexto: 'Ver descargas',
      accionHref: `/e/${empresaId}/descargas`,
    };
  }
  if (ev.tipo === 'error_descarga') {
    const d = ev.detalle as { mensaje?: string };
    return {
      fg: 'text-danger', bg: 'bg-danger-soft', Icon: AlertTriangle, tipo: 'error_descarga',
      titulo: 'Error en una descarga',
      detalle: d.mensaje ?? 'Ocurrió un error al descargar del SAT.',
      uuids: null, createdAt,
      accionTexto: 'Ver descargas',
      accionHref: `/e/${empresaId}/descargas`,
    };
  }
  // efirma_por_vencer: el backend crea este evento cuando la e.firma bloquea la sincronización
  // (ausente o vencida) y guarda el motivo en `detalle.mensaje` — no trae fecha ni días.
  const d = ev.detalle as { mensaje?: string };
  return {
    fg: 'text-warning', bg: 'bg-warning-soft', Icon: KeyRound, tipo: 'efirma_por_vencer',
    titulo: 'Problema con la e.firma',
    detalle: d.mensaje ?? 'Revisa la vigencia de la e.firma de esta empresa.',
    uuids: null, createdAt,
    accionTexto: 'Ir a la bóveda',
    accionHref: `/e/${empresaId}/efirma`,
  };
}
