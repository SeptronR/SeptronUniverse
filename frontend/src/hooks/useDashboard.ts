import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { anApi } from '@/features/analytics/api';
import { wsClient } from '@/lib/ws';

export interface DashboardQuery {
  role?: string;
  scope?: string;
  college_id?: string;
  department_id?: string;
  term_id?: string;
}

/**
 * Role dashboard from `GET /dashboard` (Prompts/35 §35.9): polls every 5 min and re-fetches on the
 * `dashboard:{institution}` WebSocket `kpi.refreshed` message (live refresh; `updated` flips for a toast).
 */
export function useDashboard(q: DashboardQuery) {
  const qc = useQueryClient();
  const [updated, setUpdated] = useState(0);
  const query = useQuery({
    queryKey: ['dashboard', q],
    queryFn: () => anApi.dashboard({ ...q }),
    refetchInterval: 5 * 60_000,
    retry: false,
  });
  useEffect(
    () =>
      wsClient.subscribe('dashboard', (data) => {
        if ((data as { type?: string })?.type === 'kpi.refreshed') {
          void qc.invalidateQueries({ queryKey: ['dashboard'] });
          setUpdated((n) => n + 1);
        }
      }),
    [qc],
  );
  return { ...query, updated };
}
