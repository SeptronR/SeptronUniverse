import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, params?: Params) => api.get(url, { params }) as unknown as Promise<Envelope<T>>;
const post = <T = Any>(url: string, body?: unknown, params?: Params) => api.post(url, body ?? {}, { params }) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;

/** Operations console + public status — Prompts/44 §44.9. */
export const opsApi = {
  overview: () => get('/platform/ops/overview'),
  deploys: () => get('/platform/ops/deploys'),
  noteDeploy: (id: string, note: string) => post(`/platform/ops/deploys/${id}/notes`, { note }),
  backups: () => get('/platform/ops/backups'),
  drills: () => get('/platform/ops/restore-drills'),
  recordDrill: (b: Any) => post('/platform/ops/restore-drills', b),
  alerts: (active?: boolean) => get('/platform/ops/alerts', { active }),
  rules: () => get('/platform/ops/alerts/rules'),
  testAlert: (rule: string) => post('/platform/ops/alerts/test', {}, { rule }),
  incidents: () => get('/platform/ops/incidents'),
  openIncident: (b: Any) => post('/platform/ops/incidents', b),
  updateIncident: (id: string, state: string, message: string) => post(`/platform/ops/incidents/${id}/update`, { state, message }),
  setComponent: (key: string, state: string | null, message?: string) => put(`/platform/ops/status/components/${key}`, { state, message }),
  capacity: () => get('/platform/ops/capacity'),
  snapshot: () => post('/platform/ops/capacity/snapshot'),
  partitions: () => get('/platform/ops/partitions'),
  ensurePartitions: () => post('/platform/ops/partitions/ensure'),
  cacheWarm: () => post('/platform/ops/cache-warm'),
  runScript: (script: string, params: Any) => post('/platform/ops/scripts/run', { script, params }),
  approveScript: (id: string) => post(`/platform/ops/scripts/runs/${id}/approve`),
  scriptRuns: () => get('/platform/ops/scripts/runs'),
  config: () => get('/platform/ops/config'),
  releases: () => get('/platform/releases'),
  addRelease: (b: Any) => post('/platform/releases', b),
  announce: (v: string) => post(`/platform/releases/${v}/announce`),
  publicStatus: () => get('/public/status'),
  history: (component: string, days = 90) => get('/public/status/history', { component, days }),
};
