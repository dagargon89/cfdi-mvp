import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/client';
import type { EstadoJob } from '@/lib/api';

const EN_CURSO: EstadoJob[] = ['SOLICITADO', 'EN_PROCESO'];

/** Poll corto mientras haya jobs en curso — sustituye al event-bus del prototipo para reflejar la
 * progresión simulada de avanzarJob() (demo.html:1088-1097) sin acoplar la UI al mock. */
export function useJobs(empresaId: number) {
  return useQuery({
    queryKey: ['jobs', empresaId],
    queryFn: () => api.listarJobs(empresaId),
    refetchInterval: (query) => (query.state.data?.data.some((j) => EN_CURSO.includes(j.estado)) ? 1500 : false),
  });
}
