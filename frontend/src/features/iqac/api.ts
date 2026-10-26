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
const enc = encodeURIComponent;

/** Accreditation & compliance / IQAC (Prompts/32 §32.8). */
export const iqacApi = {
  // frameworks
  frameworks: () => get('/accreditation/frameworks'),
  framework: (code: string) => get(`/accreditation/frameworks/${enc(code)}`),
  frameworkMetrics: (code: string) => get(`/accreditation/frameworks/${enc(code)}/metrics`),
  // metrics
  definitions: (p: Params = {}) => get('/accreditation/metrics/definitions', p),
  compute: (b: Body, inline = false) => post(`/accreditation/metrics/compute${inline ? '?inline=true' : ''}`, b),
  values: (p: Params = {}) => get('/accreditation/metrics', p),
  value: (key: string, p: Params) => get(`/accreditation/metrics/${enc(key)}`, p),
  trend: (key: string) => get(`/accreditation/metrics/${enc(key)}/trend`),
  drilldown: (key: string, p: Params) => get(`/accreditation/metrics/${enc(key)}/drilldown`, p),
  drilldownExport: (key: string, p: Params) => get(`/accreditation/metrics/${enc(key)}/drilldown/export`, p),
  override: (key: string, b: Body) => put(`/accreditation/metrics/${enc(key)}/override`, b),
  verify: (key: string, b: Body) => post(`/accreditation/metrics/${enc(key)}/verify`, b),
  manual: (key: string, b: Body) => put(`/accreditation/metrics/${enc(key)}/manual`, b),
  overrides: () => get('/accreditation/metrics/overrides'),
  // evidence
  evidence: (p: Params = {}) => get('/accreditation/evidence', p),
  createEvidence: (b: Body) => post('/accreditation/evidence', b),
  updateEvidence: (id: string, b: Body) => put(`/accreditation/evidence/${id}`, b),
  deleteEvidence: (id: string) => del(`/accreditation/evidence/${id}`),
  verifyEvidence: (id: string, action = 'verify') => post(`/accreditation/evidence/${id}/verify`, { action }),
  suggestions: (status = 'pending') => get('/accreditation/evidence/suggestions', { status }),
  acceptSuggestion: (id: string) => post(`/accreditation/evidence/suggestions/${enc(id)}/accept`),
  dismissSuggestion: (id: string) => post(`/accreditation/evidence/suggestions/${enc(id)}/dismiss`),
  pack: (criterion: string, period?: string) => post(`/accreditation/evidence/pack?criterion=${enc(criterion)}${period ? `&period=${enc(period)}` : ''}`),
  // cycles
  cycles: (p: Params = {}) => get('/accreditation/cycles', p),
  cycle: (id: string) => get(`/accreditation/cycles/${id}`),
  createCycle: (b: Body) => post('/accreditation/cycles', b),
  updateCycle: (id: string, b: Body) => put(`/accreditation/cycles/${id}`, b),
  cycleStatus: (id: string, b: Body) => post(`/accreditation/cycles/${id}/status`, b),
  progress: (id: string) => get(`/accreditation/cycles/${id}/progress`),
  criteria: (id: string) => get(`/accreditation/cycles/${id}/criteria`),
  criterion: (id: string, code: string) => get(`/accreditation/cycles/${id}/criteria/${enc(code)}`),
  saveCriterion: (id: string, code: string, b: Body) => put(`/accreditation/cycles/${id}/criteria/${enc(code)}`, b),
  assign: (id: string, b: Body) => post(`/accreditation/cycles/${id}/criteria/assign`, b),
  submit: (id: string, code: string) => post(`/accreditation/cycles/${id}/criteria/${enc(code)}/submit`),
  review: (id: string, code: string, b: Body) => post(`/accreditation/cycles/${id}/criteria/${enc(code)}/review`, b),
  versions: (id: string, code: string) => get(`/accreditation/cycles/${id}/criteria/${enc(code)}/versions`),
  bestPractice: (id: string, b: Body) => post(`/accreditation/cycles/${id}/best-practices`, b),
  distinctiveness: (id: string, b: Body) => post(`/accreditation/cycles/${id}/distinctiveness`, b),
  exportCycle: (id: string, b: Body) => post(`/accreditation/cycles/${id}/export`, b),
  exports: (id: string) => get(`/accreditation/cycles/${id}/exports`),
  // submissions
  submissions: (p: Params = {}) => get('/accreditation/submissions', p),
  submission: (id: string) => get(`/accreditation/submissions/${id}`),
  createSubmission: (b: Body) => post('/accreditation/submissions', b),
  generate: (id: string) => post(`/accreditation/submissions/${id}/generate?inline=true`),
  diff: (id: string) => get(`/accreditation/submissions/${id}/diff`),
  markSubmitted: (id: string, b: Body) => post(`/accreditation/submissions/${id}/submitted`, b),
  // audits
  audits: (p: Params = {}) => get('/accreditation/audits', p),
  audit: (id: string) => get(`/accreditation/audits/${id}`),
  createAudit: (b: Body) => post('/accreditation/audits', b),
  updateAudit: (id: string, b: Body) => put(`/accreditation/audits/${id}`, b),
  updateFinding: (id: string, no: number, b: Body) => put(`/accreditation/audits/${id}/findings/${no}`, b),
  auditDashboard: () => get('/accreditation/audits/dashboard'),
  // consistency / disclosures / dashboard
  runConsistency: (period: string) => post(`/accreditation/consistency/check?inline=true&period=${enc(period)}`),
  consistency: (period: string) => get('/accreditation/consistency', { period }),
  disclosures: () => get('/accreditation/disclosures'),
  refreshDisclosures: () => post('/accreditation/disclosures/refresh'),
  dashboard: (period?: string) => get('/accreditation/dashboard', { period }),
};
