// demo.html:172-218 (P2 Empresas) + lógica demo.html:1182-1191,1283-1285.
import { useQuery } from '@tanstack/react-query';
import { Building2, Clock, ShieldCheck, ShieldX } from 'lucide-react';
import { Link, useNavigate } from 'react-router';
import { Button } from '@/components/ui/Button';
import { useAuth } from '@/auth/AuthContext';
import { useEmpresas } from '@/hooks/useEmpresas';
import { api } from '@/lib/client';
import type { EmpresaResumen } from '@/lib/api';
import { diasParaVencer, umbralVigenciaDias } from '@/lib/domain';

function ChipEfirma({ empresa, umbral }: { empresa: EmpresaResumen; umbral: number }) {
  if (!empresa.efirma?.presente) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold text-danger bg-danger-soft whitespace-nowrap">
        <ShieldX className="size-3.5" aria-hidden /> Sin e.firma
      </span>
    );
  }
  const dias = diasParaVencer(empresa.efirma.not_after!);
  if (dias <= umbral) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold text-warning bg-warning-soft whitespace-nowrap">
        <Clock className="size-3.5" aria-hidden /> e.firma por vencer · {dias} días
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold text-success bg-success-soft whitespace-nowrap">
      <ShieldCheck className="size-3.5" aria-hidden /> e.firma vigente
    </span>
  );
}

function EmpresaCard({ empresa, umbral }: { empresa: EmpresaResumen; umbral: number }) {
  const navigate = useNavigate();
  const { data: eventos } = useQuery({ queryKey: ['eventos-count', empresa.empresa_id], queryFn: () => api.listarEventos(empresa.empresa_id) });
  const inactiva = !empresa.activo;
  const sinEfirma = !empresa.efirma?.presente;

  return (
    <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-3" style={{ opacity: inactiva ? 0.6 : 1 }}>
      <div className="flex items-start gap-2.5">
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-[15px] text-pretty">{empresa.nombre}</div>
          <div className="font-mono text-xs text-text-muted mt-0.5">{empresa.rfc}</div>
        </div>
        <span className="text-[11px] font-semibold text-text-muted bg-surface-alt rounded-md px-2 py-0.5 whitespace-nowrap">{empresa.rol}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <ChipEfirma empresa={empresa} umbral={umbral} />
        {inactiva && <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold text-text-muted bg-surface-alt">Inactiva</span>}
        {!!eventos?.total && (
          <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold text-danger bg-danger-soft">{eventos.total} alertas</span>
        )}
      </div>
      <div className="flex flex-wrap gap-2 mt-0.5">
        <Button disabled={inactiva} onClick={() => navigate(`/e/${empresa.empresa_id}`)}>
          Abrir
        </Button>
        {sinEfirma && (
          <Button variant="secondary" disabled={inactiva} onClick={() => navigate(`/e/${empresa.empresa_id}/efirma`)}>
            Dar de alta e.firma
          </Button>
        )}
      </div>
    </div>
  );
}

export function EmpresasPage() {
  const { usuario } = useAuth();
  const { data: empresas } = useEmpresas();
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: () => api.listarConfiguracion() });
  const umbral = umbralVigenciaDias(config ?? []);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end gap-3">
        <div>
          <h2 className="m-0 text-[22px] font-bold">Mis empresas</h2>
          <p className="mt-1 mb-0 text-text-muted">
            {empresas?.length ?? 0} empresa(s) con acceso · rol global {usuario?.rol_global}
          </p>
        </div>
      </div>
      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
        {empresas?.map((e) => <EmpresaCard key={e.empresa_id} empresa={e} umbral={umbral} />)}
      </div>
      {usuario?.rol_global === 'consulta' && (
        <div className="bg-surface border border-dashed border-border rounded-lg px-4 py-3 flex items-center gap-3">
          <span className="text-xs text-text-muted flex-1 text-pretty">
            Prueba de permisos del guion de validación: intentar entrar a una empresa sin asignación.
          </span>
          <Link
            to="/e/8"
            className="h-8 border border-border bg-surface rounded-md px-3 text-[13px] font-semibold inline-flex items-center hover:bg-surface-alt"
          >
            Abrir empresa 8 sin permiso
          </Link>
        </div>
      )}
      {empresas?.length === 0 && (
        <div className="bg-surface border border-border rounded-lg p-8 text-center text-text-muted text-sm flex items-center justify-center gap-2">
          <Building2 className="size-4" aria-hidden /> No tienes empresas asignadas.
        </div>
      )}
    </div>
  );
}
