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
const del = <T = Any>(url: string, params?: Params) => api.delete(url, { params }) as unknown as Promise<Envelope<T>>;

export const EXAM_SECTIONS = ['marks', 'qp_print', 'custody', 'valuation', 'moderation', 'decode', 'runs', 'publication', 'post_result'] as const;

/** Audit explorer, chain integrity, exam audit, security console, settings catalogue, retention (Prompts/37 §37.8). */
export const auditApi = {
  list: (p: Params = {}) => get('/audit-logs', p),
  me: (p: Params = {}) => get('/audit-logs/me', p),
  detail: (id: string) => get(`/audit-logs/${id}`),
  timeline: (record_type: string, record_id: string) => get('/audit-logs/timeline', { record_type, record_id }),
  whoViewed: (record_type: string, record_id: string) => get('/audit-logs/who-viewed', { record_type, record_id }),
  summary: (p: Params = {}) => get('/audit-logs/summary', p),
  export: (query: Body, format: string) => post('/audit-logs/export', { query, format }),
  verify: (b: Body) => post('/audit-logs/verify-chain', b),
  digests: (p: Params = {}) => get('/audit-logs/chain-digests', p),
  examSection: (sid: string, section: string, paper_id?: string) => get(`/exams/${sid}/audit`, { section, paper_id }),
  examSummary: (sid: string) => get(`/exams/${sid}/audit/summary`),
  examExport: (sid: string, format = 'pdf') => post(`/exams/${sid}/audit/export`, { format }),
  events: (p: Params = {}) => get('/security/events', p),
  anomalies: (active?: boolean) => get('/security/anomalies', { active }),
  ack: (id: string, note: string) => post(`/security/anomalies/${id}/acknowledge`, { note }),
  sessions: (p: Params = {}) => get('/security/sessions', p),
  revoke: (b: Body) => post('/security/sessions/revoke', b),
  loginHistory: (p: Params = {}) => get('/security/login-history', p),
  catalogue: (p: Params = {}) => get('/settings/catalogue', p),
  effective: (p: Params = {}) => get('/settings/effective', p),
  history: (p: Params = {}) => get('/settings/history', p),
  changesSince: (since: string) => get('/settings/changes-since', { since }),
  save: (items: Body[], reason?: string) => put('/settings', { items, reason }),
  reset: (key: string, reason?: string) => post(`/settings/${key}/reset${reason ? `?reason=${encodeURIComponent(reason)}` : ''}`),
  clearOverride: (key: string, college_id: string, reason?: string) => del(`/settings/${key}/override`, { college_id, reason }),
  exportSettings: () => get('/settings/export'),
  importSettings: (json: Body, dry_run: boolean, reason?: string) => post(`/settings/import?dry_run=${dry_run}`, { json, reason }),
  featureChanges: (p: Params = {}) => get('/settings/feature-changes', p),
  platformActions: (p: Params = {}) => get('/settings/platform-actions', p),
  policies: () => get('/retention/policies'),
  putPolicies: (values: Body, reason?: string) => put('/retention/policies', { values, reason }),
  preview: (data_class: string) => get('/retention/preview', { data_class }),
  purge: (data_class: string) => post('/retention/purge', { data_class }),
  archive: (data_class: string, period: string) => post('/retention/archive', { data_class, period }),
  manifests: () => get('/retention/manifests'),
  restore: (manifest_id: string) => post('/retention/restore', { manifest_id }),
  holds: (active = true) => get('/retention/legal-holds', { active }),
  addHold: (b: Body) => post('/retention/legal-holds', b),
  clearHold: (id: string) => del(`/retention/legal-holds/${id}`),
};
