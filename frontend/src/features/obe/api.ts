import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T = Any>(url: string, body?: unknown, config: AxiosRequestConfig = once) => api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;

/** OBE attainment, CQI and NBA export (Prompts/17 §17.8). */
export const obeApi = {
  // lookups (Phase 05)
  programs: () => get('/programs', { params: { page_size: 200 } }),
  batches: (program_id: string) => get('/batches', { params: { program_id, page_size: 200 } }),
  // configs
  effective: (program_id: string) => get('/attainment-configs/effective', { params: { program_id } }),
  configs: (p: Params = {}) => get('/attainment-configs', { params: p }),
  saveConfig: (b: Body) => put('/attainment-configs', b),
  // CO attainment
  coCompute: (offeringId: string, b: Body = {}) => post(`/course-offerings/${offeringId}/attainment/compute`, b),
  co: (offeringId: string, run_id?: string) => get(`/course-offerings/${offeringId}/attainment`, { params: { run_id } }),
  coHeatmap: (offeringId: string) => get(`/course-offerings/${offeringId}/attainment/heatmap`),
  coRuns: (offeringId: string) => get(`/course-offerings/${offeringId}/attainment/runs`),
  coStudents: (offeringId: string) => get(`/course-offerings/${offeringId}/attainment/students`),
  me: (offering_id: string) => get('/attainment/me', { params: { offering_id } }),
  // PO attainment
  poCompute: (programId: string, batchId: string, b: Body = {}) => post(`/programs/${programId}/batches/${batchId}/attainment/compute`, b),
  po: (programId: string, batch_id: string) => get(`/programs/${programId}/attainment`, { params: { batch_id } }),
  poTrend: (programId: string) => get(`/programs/${programId}/attainment/trend`),
  poHeatmap: (programId: string, batch_id: string) => get(`/programs/${programId}/attainment/heatmap`, { params: { batch_id } }),
  recomputeTerm: (term_id: string) => post('/obe/recompute-term', undefined, { ...once, params: { term_id } }),
  dashboard: (program_id: string, batch_id: string) => get('/obe/dashboard', { params: { program_id, batch_id } }),
  gaps: (p: Params) => get('/obe/gaps', { params: p }),
  indirect: (survey_id: string) => get('/obe/indirect/summary', { params: { survey_id } }),
  // CQI
  cqi: (p: Params = {}) => get('/cqi-actions', { params: p }),
  cqiCreate: (b: Body) => post('/cqi-actions', b),
  cqiUpdate: (id: string, b: Body) => put(`/cqi-actions/${id}`, b),
  cqiStatus: (id: string, b: Body) => post(`/cqi-actions/${id}/status`, b),
  cqiVerify: (id: string, b: Body) => post(`/cqi-actions/${id}/verify`, b),
  // NBA export
  nbaExport: (b: Body) => post('/obe/export/nba-sar', b),
  exportJob: (jobId: string) => get(`/obe/exports/${jobId}`),
};
