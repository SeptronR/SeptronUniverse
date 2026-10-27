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

export type ReportFormat = 'xlsx' | 'csv' | 'pdf' | 'docx' | 'json';

/** Reports registry, runs, registers, builder, statutory, schedules, access log (Prompts/36 §36.8). */
export const repApi = {
  catalogue: (p: Params = {}) => get('/reports/catalogue', p),
  run: (b: { key: string; params?: Body; format?: ReportFormat; scope?: string; inline_preview?: boolean; deliver_to?: Body }) => post('/reports/run', b),
  runs: (p: Params = {}) => get('/reports/runs', p),
  runOne: (id: string) => get(`/reports/runs/${id}`),
  cancel: (id: string) => post(`/reports/runs/${id}/cancel`),
  downloadUrl: (id: string) => get<{ url: string }>(`/reports/runs/${id}/download`, { redirect: false }),
  favourites: () => get('/reports/favourites'),
  toggleFavourite: (key: string) => post('/reports/favourites/toggle', { key }),
  registers: () => get('/reports/registers'),
  runRegister: (b: Body) => post('/reports/registers/run', b),
  models: () => get('/reports/models'),
  model: (key: string) => get(`/reports/models/${key}`),
  preview: (b: Body) => post('/reports/builder/preview', b),
  builderRun: (definition: Body, format: ReportFormat) => post('/reports/builder/run', { definition, format }),
  saved: () => get('/reports/saved'),
  save: (b: Body) => post('/reports/saved', b),
  updateSaved: (id: string, b: Body) => put(`/reports/saved/${id}`, b),
  deleteSaved: (id: string) => del(`/reports/saved/${id}`),
  shareSaved: (id: string, roles: string[]) => post(`/reports/saved/${id}/share`, { roles }),
  runSaved: (id: string, format: ReportFormat) => post(`/reports/saved/${id}/run?format=${format}`),
  statutory: () => get('/reports/statutory'),
  statutoryOne: (code: string, period: string, discipline?: string) => get(`/reports/statutory/${code}`, { period, discipline }),
  generate: (code: string, b: Body) => post(`/reports/statutory/${code}/generate`, b),
  review: (code: string, period: string, b: Body, discipline?: string) =>
    post(`/reports/statutory/${code}/${period}/review${discipline ? `?discipline=${discipline}` : ''}`, b),
  diff: (code: string, period: string, vs?: string) => get(`/reports/statutory/${code}/${period}/diff`, { vs }),
  pack: (code: string, period: string) => post(`/reports/statutory/${code}/${period}/pack`),
  schedules: () => get('/reports/schedules'),
  createSchedule: (b: Body) => post('/reports/schedules', b),
  updateSchedule: (id: string, b: Body) => put(`/reports/schedules/${id}`, b),
  deleteSchedule: (id: string) => del(`/reports/schedules/${id}`),
  runNow: (id: string) => post(`/reports/schedules/${id}/run-now`),
  pause: (id: string) => post(`/reports/schedules/${id}/pause`),
  resume: (id: string) => post(`/reports/schedules/${id}/resume`),
  history: (id: string) => get(`/reports/schedules/${id}/history`),
  accessLog: (p: Params = {}) => get('/reports/access-log', p),
};
