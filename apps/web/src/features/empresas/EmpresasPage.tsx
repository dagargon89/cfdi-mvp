// demo.html:172-218 (P2 Empresas) + lógica demo.html:1182-1191,1283-1285.
// Alta/baja de empresa (RF-EMP-01/02) no estaban en el prototipo — se agregaron cuando el
// backend real ya las soportaba y David preguntó cómo hacerlo.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Building2, Clock, Power, ShieldCheck, ShieldX, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { Button } from '@/components/ui/Button';
import { ConfirmarRfcModal } from '@/components/ui/ConfirmarRfcModal';
import { useToast } from '@/components/ui/ToastProvider';
import { useAuth } from '@/auth/AuthContext';
import { useEmpresas } from '@/hooks/useEmpresas';
import { api } from '@/lib/client';
import { ApiError } from '@/lib/api';
import type { EmpresaResumen } from '@/lib/api';
import { diasParaVencer, umbralVigenciaDias } from '@/lib/domain';
import { NuevaEmpresaModal } from './NuevaEmpresaModal';

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

function EmpresaCard({ empresa, umbral, esAdmin }: { empresa: EmpresaResumen; umbral: number; esAdmin: boolean }) {
  const navigate = useNavigate();
  const { toast } = useToast();
  const qc = useQueryClient();
  const { data: eventos } = useQuery({ queryKey: ['eventos-count', empresa.empresa_id], queryFn: () => api.listarEventos(empresa.empresa_id) });
  const inactiva = !empresa.activo;
  const sinEfirma = !empresa.efirma?.presente;
  const [modalBorrar, setModalBorrar] = useState(false);

  const toggleActivo = useMutation({
    mutationFn: () => api.actualizarEmpresa(empresa.empresa_id, { activo: inactiva }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresas'] });
      toast(inactiva ? 'Empresa activada' : 'Empresa desactivada', 'ok');
    },
  });

  const eliminar = useMutation({
    mutationFn: () => api.eliminarEmpresa(empresa.empresa_id),
    onSuccess: () => {
      setModalBorrar(false);
      qc.invalidateQueries({ queryKey: ['empresas'] });
      toast('Empresa eliminada', 'ok');
    },
    onError: (e) => {
      setModalBorrar(false);
      toast(e instanceof ApiError ? e.message : 'No se pudo eliminar la empresa.', 'error');
    },
  });

  return (
    <div className="bg-surface border border-border rounded-lg p-5 flex flex-col gap-4 h-full transition-shadow hover:shadow-sm" style={{ opacity: inactiva ? 0.6 : 1 }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-semibold text-[15px] leading-snug text-pretty">{empresa.nombre}</div>
          <div className="font-mono text-xs text-text-muted mt-1">{empresa.rfc}</div>
        </div>
        <span className="shrink-0 text-[11px] font-semibold text-text-muted bg-surface-alt rounded-full px-2.5 py-1 whitespace-nowrap capitalize">{empresa.rol}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <ChipEfirma empresa={empresa} umbral={umbral} />
        {inactiva && <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold text-text-muted bg-surface-alt">Inactiva</span>}
        {!!eventos?.total && (
          <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold text-danger bg-danger-soft">{eventos.total} alertas</span>
        )}
      </div>
      <div className="mt-auto pt-4 border-t border-border flex flex-col gap-2">
        <Button className="w-full justify-center" disabled={inactiva} onClick={() => navigate(`/e/${empresa.empresa_id}`)}>
          Abrir
        </Button>
        {sinEfirma && (
          <Button variant="secondary" className="w-full justify-center" disabled={inactiva} onClick={() => navigate(`/e/${empresa.empresa_id}/efirma`)}>
            Dar de alta e.firma
          </Button>
        )}
        {esAdmin && (
          <div className="flex gap-2">
            <Button variant="secondary" className="flex-1 justify-center" onClick={() => toggleActivo.mutate()} loading={toggleActivo.isPending} disabled={toggleActivo.isPending}>
              <Power className="size-3.5" aria-hidden /> {inactiva ? 'Activar' : 'Desactivar'}
            </Button>
            <Button variant="danger" className="flex-1 justify-center" onClick={() => setModalBorrar(true)}>
              <Trash2 className="size-3.5" aria-hidden /> Eliminar
            </Button>
          </div>
        )}
      </div>
      {modalBorrar && (
        <ConfirmarRfcModal
          titulo="Eliminar empresa"
          descripcion={
            <>
              Esto borra la empresa por completo (a diferencia de "Desactivar", que conserva el historial). Solo
              funciona si nunca tuvo e.firma, descargas ni comprobantes. Escribe el RFC{' '}
              <strong className="font-mono text-text-strong">{empresa.rfc}</strong> para confirmar.
            </>
          }
          rfc={empresa.rfc}
          onCancelar={() => setModalBorrar(false)}
          onConfirmar={() => eliminar.mutate()}
        />
      )}
    </div>
  );
}

export function EmpresasPage() {
  const { usuario } = useAuth();
  const { data: empresas } = useEmpresas();
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: () => api.listarConfiguracion() });
  const umbral = umbralVigenciaDias(config ?? []);
  const esAdmin = usuario?.rol_global === 'admin';
  const [modalAbierto, setModalAbierto] = useState(false);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <h2 className="m-0 text-[22px] font-bold">Mis empresas</h2>
          <p className="mt-1 mb-0 text-text-muted">
            {empresas?.length ?? 0} empresa(s) con acceso · rol global {usuario?.rol_global}
          </p>
        </div>
        {esAdmin && <Button onClick={() => setModalAbierto(true)}>Nueva empresa</Button>}
      </div>
      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
        {empresas?.map((e) => <EmpresaCard key={e.empresa_id} empresa={e} umbral={umbral} esAdmin={esAdmin} />)}
      </div>
      {modalAbierto && <NuevaEmpresaModal onClose={() => setModalAbierto(false)} />}
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
