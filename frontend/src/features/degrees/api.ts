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
const blob = (url: string, params?: Params) => api.get(url, { params, responseType: 'blob' }) as unknown as Promise<Blob>;

/** Degrees, convocation & digital credentials (Prompts/18 §18.8). */
export const degreesApi = {
  programs: () => get('/programs', { params: { page_size: 200 } }),
  batches: (program_id?: string) => get('/batches', { params: { program_id, page_size: 200 } }),
  // eligibility
  runEligibility: (b: Body) => post('/degree-eligibility/run', b),
  eligibility: (p: Params = {}) => get('/degree-eligibility', { params: p }),
  eligibilityMe: () => get('/degree-eligibility/me'),
  override: (id: string, b: Body) => post(`/degree-eligibility/${id}/override`, b),
  // convocations
  convocations: () => get('/convocations'),
  createConvocation: (b: Body) => post('/convocations', b),
  updateConvocation: (id: string, b: Body) => put(`/convocations/${id}`, b),
  convocationStatus: (id: string, status: string) => post(`/convocations/${id}/status`, { status }),
  registrations: (id: string, p: Params = {}) => get(`/convocations/${id}/registrations`, { params: p }),
  report: (id: string, kind: 'gowns' | 'seating' | 'attendance') => get(`/convocations/${id}/reports/${kind}`),
  register: (id: string, b: Body) => post(`/convocations/${id}/register`, b, { idempotent: true } as AxiosRequestConfig),
  myConvocations: () => get('/convocations/me'),
  attendance: (id: string, b: Body) => post(`/convocations/${id}/attendance`, b),
  // awards
  awardBatch: (b: Body, dry_run = false) => post('/degrees/award-batch', b, { ...once, params: { dry_run } }),
  awards: (p: Params = {}) => get('/degrees', { params: p }),
  approve: (id: string, b: Body = {}) => post(`/degrees/${id}/approve`, b),
  issue: (id: string, esign = false) => post(`/degrees/${id}/issue`, { esign }),
  issueBatch: (b: Body) => post('/degrees/issue-batch', b),
  printBatch: (b: Body) => post('/degrees/print-batch', b),
  revoke: (id: string, reason: string) => post(`/degrees/${id}/revoke`, { reason }),
  reissue: (id: string, b: Body) => post(`/degrees/${id}/reissue`, b),
  certificate: (id: string) => blob(`/degrees/${id}/certificate.pdf`),
  register_csv: (batch_id?: string) => blob('/degrees/register/export', { batch_id }),
  myDegrees: () => get('/degrees/me'),
  stats: (p: Params = {}) => get('/degrees/stats', { params: p }),
  // provisional
  provisional: (enrollment_id: string) => post('/degrees/provisional', { enrollment_id }),
  myProvisional: () => get('/degrees/provisional/me'),
  // credentials / ABC
  pushCredentials: (b: Body) => post('/credentials/push', b),
  credentials: (p: Params = {}) => get('/credentials', { params: p }),
  retryCredential: (id: string) => post(`/credentials/${id}/retry`),
  revokeCredential: (id: string) => post(`/credentials/${id}/revoke`),
  myCredentials: () => get('/credentials/me'),
  abcPush: (b: Body = {}) => post('/abc/push', b),
  abcLedger: (p: Params = {}) => get('/abc/ledger', { params: p }),
  abcMe: () => get('/abc/ledger/me'),
  abcRetry: (id: string) => post(`/abc/ledger/${id}/retry`),
  // public
  bulkVerify: (b: Body) => post('/verify/bulk', b),
};

export function openBlob(b: Blob, name: string) {
  const url = URL.createObjectURL(b);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
