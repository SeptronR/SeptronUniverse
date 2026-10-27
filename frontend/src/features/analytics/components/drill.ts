import type { ChartData } from '@/components/charts/ChartView';

/** Point → list-page URL with the chart's dims and the clicked id / label applied as filters (same visibility). */
export function drillUrl(data: ChartData, point: Record<string, unknown>): string | null {
  const d = data.drilldown;
  if (!d?.route) return null;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(d.filters ?? {})) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  if (d.id_field && point._id) qs.set(d.id_field, String(point._id));
  if (d.label_field) {
    const v = d.label_field === 'series' ? point.series : point.label;
    if (v !== undefined && v !== null && v !== '—') qs.set(d.label_field === 'series' ? 'status' : d.label_field, String(v));
  }
  const s = qs.toString();
  return s ? `${d.route}?${s}` : d.route;
}
