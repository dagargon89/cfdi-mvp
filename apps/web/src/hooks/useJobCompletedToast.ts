import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { mockEvents } from '@/lib/api.mock';
import { useToast } from '@/components/ui/ToastProvider';

/** Monta una vez (AppShell) — traduce el evento 'job-completed' del mock (demo.html:1096) al toast
 * "Job #id descargado" y refresca la caché de jobs al instante en vez de esperar el próximo poll. */
export function useJobCompletedToast() {
  const { toast } = useToast();
  const qc = useQueryClient();

  useEffect(() => {
    const onCompleted = (e: Event) => {
      const { jobId } = (e as CustomEvent<{ jobId: number }>).detail;
      toast(`Job #${jobId} descargado`, 'ok');
      qc.invalidateQueries({ queryKey: ['jobs'] });
    };
    mockEvents.addEventListener('job-completed', onCompleted);
    return () => mockEvents.removeEventListener('job-completed', onCompleted);
  }, [toast, qc]);
}
