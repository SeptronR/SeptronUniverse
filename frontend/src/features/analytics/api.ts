import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, params?: Params) => api.get(url, { params }) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T = Any>(url: string, body?: unknown, cfg: AxiosRequestConfig = once) => api.post(url, body ?? {}, cfg) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T = Any>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;

/** `dims[x]` / `params[x]` / `point[x]` / `filter[x]` query style of Prompts/35 §35.8. */
export const bracket = (prefix: string, o: Record<string, unknown> = {}): Params =>
  Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => [`${prefix}[${k}]`, String(v)]));

/** Dashboards, analytics, KPI targets, read models, digests and early warning (Prompts/35 §35.8). */
export const anApi = {
  dashboard: (p: Params = {}) => get('/dashboard', p),
  widget: (key: string, p: Params = {}) => get(`/dashboard/widgets/${encodeURIComponent(key)}`, p),
  pins: (b: { pinned_keys: string[]; hidden_keys: string[] }) => put('/dashboard/pins', b),
  layout: (role: string) => get(`/dashboard/layouts/${role}`),
  putLayout: (role: string, b: Body) => put(`/dashboard/layouts/${role}`, b),
  resetLayout: (role: string) => post(`/dashboard/layouts/${role}/reset`),
  // charts
  catalogue: (module?: string) => get('/analytics/charts', { module }),
  chart: (key: string, p: Params = {}, dims: Record<string, unknown> = {}, params: Record<string, unknown> = {}) =>
    get(`/analytics/charts/${encodeURIComponent(key)}`, { ...p, ...bracket('dims', dims), ...bracket('params', params) }),
  chartCsv: (key: string, p: Params = {}) => api.get(`/analytics/charts/${encodeURIComponent(key)}`, { params: { ...p, format: 'csv' }, responseType: 'blob' }) as unknown as Promise<Blob>,
  drilldown: (key: string, point: Record<string, unknown>, page = 1) => get(`/analytics/charts/${encodeURIComponent(key)}/drilldown`, { ...bracket('point', point), page }),
  exportChart: (key: string, b: Body) => post(`/analytics/charts/${encodeURIComponent(key)}/export`, b),
  insights: (module: string, filters: Record<string, unknown> = {}) => get(`/analytics/insights/${module}`, bracket('filter', filters)),
  // KPI
  targets: (college_id?: string) => get('/analytics/targets', { college_id }),
  putTargets: (b: Body) => put('/analytics/targets', b),
  evaluate: () => post('/analytics/targets/evaluate'),
  alerts: (active?: boolean) => get('/analytics/alerts', { active }),
  // read models / digests
  readmodels: () => get('/analytics/readmodels'),
  refresh: (views: string[] = []) => post('/analytics/readmodels/refresh', { views }),
  digests: () => get('/analytics/digests'),
  createDigest: (b: Body) => post('/analytics/digests', b),
  deleteDigest: (id: string) => del(`/analytics/digests/${id}`),
  sendDigest: (id: string) => post(`/analytics/digests/${id}/send-now`),
  // early warning
  cohort: (p: Params = {}) => get('/risk/cohort', p),
  trend: (p: Params = {}) => get('/risk/cohort/trend', p),
  riskStudents: (p: Params = {}) => get('/risk/students', p),
  interventions: (enrollmentId: string) => get(`/risk/students/${enrollmentId}/interventions`),
  logIntervention: (enrollmentId: string, b: Body) => post(`/risk/students/${enrollmentId}/interventions`, b),
  effectiveness: (p: Params = {}) => get('/risk/effectiveness', p),
  exportCohort: (b: Body) => post('/risk/cohort/export', b),
};
