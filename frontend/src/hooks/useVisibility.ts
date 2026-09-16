import { useCallback, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import type { Envelope, ScopeName, VisibilityMeta } from '@/utils/types';

const EMPTY: VisibilityMeta = { self: true, scopes: [], default: 'self', pii: false };

/**
 * Reads `meta.visibility` from the last list response of a module (React Query cache) and exposes
 * `{ self, scopes, active, setActive }`; the active scope is written to `?scope=` so it becomes part of the query key.
 */
export const useVisibility = (module: string) => {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const visibility = useMemo<VisibilityMeta>(() => {
    const entries = qc.getQueriesData<Envelope<unknown>>({ queryKey: [module] });
    for (let i = entries.length - 1; i >= 0; i--) {
      const v = entries[i][1]?.meta?.visibility;
      if (v) return v;
    }
    return EMPTY;
  }, [qc, module]);
  const active = (params.get('scope') as ScopeName | null) ?? visibility.default;
  const setActive = useCallback(
    (scope: ScopeName) => {
      const next = new URLSearchParams(params);
      next.set('scope', scope);
      next.delete('page');
      setParams(next, { replace: true });
    },
    [params, setParams],
  );
  return { ...visibility, active, setActive, hasTabs: visibility.scopes.length > 0 };
};
