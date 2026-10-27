import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { getApiError } from '@/api/axios';
import { ChartView, type ChartData } from '@/components/charts/ChartView';
import { FeatureGuard } from '@/components/shared/FeatureGuard';
import { anApi } from '../api';
import { drillUrl } from './drill';

/**
 * Insights tab for any module list page (Prompts/35 §35.9): `<InsightsTab module="students" filters={current} />`
 * reads `/analytics/insights/{module}` with the DataTable's current filters, so the charts follow the list.
 */
export function InsightsTab({ module, filters = {} }: { module: string; filters?: Record<string, unknown> }) {
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ['insights', module, filters], queryFn: () => anApi.insights(module, filters), retry: false });
  const charts = ((q.data?.data as { charts?: ChartData[] } | undefined)?.charts ?? []) as ChartData[];
  return (
    <FeatureGuard feature="analytics.core">
      {q.isError && <p className="text-sm text-destructive">{getApiError(q.error)}</p>}
      {q.isLoading && <p className="text-sm text-muted-foreground">Loading insights…</p>}
      {!q.isLoading && !charts.length && !q.isError && <p className="text-sm text-muted-foreground">No charts for this list.</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        {charts.map((c) => (
          <ChartView
            key={c.key}
            data={c}
            onPoint={(p) => {
              const url = drillUrl(c, p);
              if (url) navigate(url);
            }}
          />
        ))}
      </div>
    </FeatureGuard>
  );
}
