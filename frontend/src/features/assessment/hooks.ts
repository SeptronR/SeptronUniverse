import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

/** `useQ(key, fn)` — query keys live under `['assessment', …]`; mutations invalidate that root (+ `lms`). */
export const useQ = <T>(key: unknown[], fn: () => Promise<T>, enabled = true) =>
  useQuery({ queryKey: ['assessment', ...key], queryFn: fn, enabled, retry: false });

export function useAssessmentMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['assessment'] }) });
}
