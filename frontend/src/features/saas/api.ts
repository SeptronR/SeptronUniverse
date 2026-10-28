import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, params?: Params) => api.get(url, { params }) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T = Any>(url: string, body?: unknown) => api.post(url, body ?? {}, once) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T = Any>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;
const inv = (n: string) => n.split('/').map(encodeURIComponent).join('/');

/** Platform console (super admin / support agent) — Prompts/38 §38.8. */
export const platformApi = {
  dashboard: (refresh = false) => get('/platform/dashboard', { refresh }),
  alerts: () => get('/platform/alerts'),
  resolveAlert: (id: string) => post(`/platform/alerts/${id}/resolve`),
  audit: (p: Params = {}) => get('/platform/audit', p),
  institutions: (p: Params = {}) => get('/platform/institutions', p),
  institution: (id: string) => get(`/platform/institutions/${id}`),
  preview: (template: string, plan_code: string) => get('/platform/onboarding/preview', { template, plan_code }),
  status: (id: string, action: string, reason: string) => post(`/platform/institutions/${id}/status`, { action, reason }),
  export: (id: string) => post(`/platform/institutions/${id}/export`, { include: ['db', 'files'], format: 'json' }),
  reset: (id: string, confirm_slug: string) => post(`/platform/institutions/${id}/reset`, { confirm_slug }),
  erase: (id: string, confirm_slug: string, reason: string) => post(`/platform/institutions/${id}/erase`, { confirm_slug, reason }),
  caps: (id: string, caps: Body) => put(`/platform/institutions/${id}/usage-caps`, { caps }),
  plans: () => get('/platform/plans'),
  createPlan: (b: Body) => post('/platform/plans', b),
  updatePlan: (id: string, b: Body) => put(`/platform/plans/${id}`, b),
  deactivatePlan: (id: string) => post(`/platform/plans/${id}/deactivate`),
  changePreview: (planId: string, institution_id: string) => get(`/platform/plans/${planId}/change-preview`, { institution_id }),
  subscription: (id: string) => get(`/platform/institutions/${id}/subscription`),
  assign: (id: string, b: Body) => post(`/platform/institutions/${id}/subscription`, b),
  change: (id: string, plan_id: string, effective = 'now') => post(`/platform/institutions/${id}/subscription/change`, { plan_id, effective }),
  renew: (id: string) => post(`/platform/institutions/${id}/subscription/renew`, {}),
  cancel: (id: string, reason: string) => post(`/platform/institutions/${id}/subscription/cancel`, { reason, at_period_end: true }),
  manualPay: (id: string, number: string, payment_ref: string) => post(`/platform/institutions/${id}/subscription/invoices/${inv(number)}/pay`, { mode: 'manual', manual: { payment_ref } }),
  invoices: (p: Params = {}) => get('/platform/billing/invoices', p),
  usage: (p: Params = {}) => get('/platform/usage', p),
  meter: () => post('/platform/usage/meter'),
  usageExport: () => get('/platform/usage/export'),
  impersonations: (p: Params = {}) => get('/platform/impersonations', p),
  forceStop: (id: string, reason: string) => post(`/platform/impersonations/${id}/force-stop`, { reason }),
  feedback: (p: Params = {}) => get('/platform/feedback', p),
  triage: (id: string, b: Body) => post(`/platform/feedback/${id}/triage`, b),
  toTicket: (id: string) => post(`/platform/feedback/${id}/to-ticket`),
  announcements: () => get('/platform/announcements'),
  activeAnnouncements: () => get('/platform/announcements/active'),
  dismiss: (id: string) => post(`/platform/announcements/${id}/dismiss`),
  createAnnouncement: (b: Body) => post('/platform/announcements', b),
  deleteAnnouncement: (id: string) => del(`/platform/announcements/${id}`),
  health: (p: Params = {}) => get('/platform/health', p),
  outages: () => get('/platform/health/outages'),
  retry: (connection_ids: string[]) => post('/platform/health/retry', { connection_ids }),
  disable: (id: string, reason: string) => post(`/platform/health/connections/${id}/disable`, { reason }),
  settings: () => get('/platform/settings'),
  saveSettings: (values: Body, reason?: string) => put('/platform/settings', { values, reason }),
  registrations: (p: Params = {}) => get('/platform/registrations', p),
  registrationAction: (id: string, action: string) => post(`/platform/registrations/${id}/action`, { action }),
  demoRequests: (p: Params = {}) => get('/platform/demo-requests', p),
  updateDemo: (id: string, status: string, notes?: string) => put(`/platform/demo-requests/${id}`, { status, notes }),
};

/** Both sides: support tickets, help authoring, read-only windows; tenant billing. */
export const supportApi = {
  tickets: (p: Params = {}) => get('/support/tickets', p),
  ticket: (id: string) => get(`/support/tickets/${id}`),
  create: (b: Body) => post('/support/tickets', b),
  reply: (id: string, text: string, internal = false) => post(`/support/tickets/${id}/reply`, { text, internal }),
  assign: (id: string, user_id: string) => post(`/support/tickets/${id}/assign`, { user_id }),
  status: (id: string, status: string, resolution?: string) => post(`/support/tickets/${id}/status`, { status, resolution }),
  rate: (id: string, rating: number) => post(`/support/tickets/${id}/rate`, { rating }),
  diagnostics: (id: string) => get(`/support/tickets/${id}/diagnostics`),
  helpList: (p: Params = {}) => get('/help/admin/articles', p),
  helpCreate: (b: Body) => post('/help/admin/articles', b),
  helpUpdate: (id: string, b: Body) => put(`/help/admin/articles/${id}`, b),
  helpDelete: (id: string) => del(`/help/admin/articles/${id}`),
  helpExport: () => get('/help/admin/export'),
  helpImport: (articles: Body[]) => post('/help/admin/import', { articles }),
  windows: (p: Params = {}) => get('/platform/read-only/schedules', p),
  schedule: (b: Body) => post('/platform/read-only/schedules', b),
  cancelWindow: (id: string) => del(`/platform/read-only/schedules/${id}`),
};

export const billingApi = {
  subscription: () => get('/billing/subscription'),
  plans: () => get('/billing/plans'),
  invoices: () => get('/billing/invoices'),
  pdfUrl: (number: string) => `/billing/invoices/${inv(number)}.pdf`,
  pay: (number: string) => post(`/billing/invoices/${inv(number)}/pay`, { mode: 'gateway' }),
  usage: () => get('/billing/usage'),
  export: () => post('/billing/export', { include: ['db', 'files'], format: 'json' }),
  upgrade: (plan_code: string, note?: string) =>
    post(`/billing/upgrade-request?plan_code=${encodeURIComponent(plan_code)}${note ? `&note=${encodeURIComponent(note)}` : ''}`),
  me: () => get('/auth/me'),
};
