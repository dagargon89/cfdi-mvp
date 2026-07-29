import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/client';
import type { EstadoJob } from '@/lib/api';

// NUEVO incluido: contra el backend real hay una ventana breve entre crear el job y que el
// worker de Celery lo levante (con el mock, avanzarJob() salta directo a SOLICITADO).
const EN_CURSO: EstadoJob[] = ['NUEVO', 'SOLICITADO', 'EN_PROCESO'];

/** Poll corto mientras haya jobs en curso — sustituye al event-bus del prototipo para reflejar la
 * progresión simulada de avanzarJob() (demo.html:1088-1097) sin acoplar la UI al mock. */
export function useJobs(empresaId: number, page = 1, solicitud?: 'CFDI' | 'METADATA') {
  return useQuery({
    queryKey: ['jobs', empresaId, page, solicitud ?? 'todas'],
    queryFn: () => api.listarJobs(empresaId, { page, solicitud }),
    refetchInterval: (query) => (query.state.data?.data.some((j) => EN_CURSO.includes(j.estado)) ? 1500 : false),
  });
}
