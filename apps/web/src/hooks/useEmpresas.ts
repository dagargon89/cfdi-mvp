import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/client';

export function useEmpresas() {
  return useQuery({ queryKey: ['empresas'], queryFn: () => api.listarEmpresas() });
}
