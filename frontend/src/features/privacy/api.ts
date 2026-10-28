import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, params?: Params) => api.get(url, { params }) as unknown as Promise<Envelope<T>>;
const post = <T = Any>(url: string, body?: unknown, params?: Params) => api.post(url, body ?? {}, { params }) as unknown as Promise<Envelope<T>>;

/** Privacy office, security posture, QA — Prompts/43 §43.9. */
export const privacyApi = {
  purposes: () => get('/privacy/purposes'),
  banner: () => get('/privacy/consent-banner'),
  bulk: (grants: Record<string, boolean>, notice_version?: string, on_behalf_student_id?: string) =>
    post('/consents/bulk', { grants, notice_version, on_behalf_student_id }),
  withdraw: (purpose: string) => post(`/consents/${purpose}/withdraw`),
  wards: () => get('/consents/wards'),
  report: (p: Params = {}) => get('/privacy/consents/report', p),
  notices: () => get('/privacy/notices'),
  saveNotice: (key: string, texts: Record<string, string>) => post('/privacy/notices', { key, texts }),
  publishNotice: (key: string) => post(`/privacy/notices/${key}/publish`),
  dsrs: (p: Params = {}) => get('/data-subject-requests', p),
  myDsrs: () => get('/data-subject-requests/me'),
  createDsr: (request_type: string, details?: string, on_behalf_student_id?: string) =>
    post('/data-subject-requests', { request_type, details, on_behalf_student_id }),
  dsr: (id: string) => get(`/data-subject-requests/${id}`),
  identity: (id: string, otp: string) => post(`/data-subject-requests/${id}/identity`, { method: 'otp', otp }),
  act: (id: string, action: string, reason?: string, corrections: Any[] = []) =>
    post(`/data-subject-requests/${id}/action`, { action, reason, corrections }),
  workItemDone: (id: string, n: number) => post(`/data-subject-requests/${id}/work-items/${n}/done`),
  dashboard: () => get('/privacy/dsr/dashboard'),
  register: () => get('/privacy/dsr/register'),
  pii: () => get('/privacy/pii-inventory'),
  maskingAudit: () => post('/privacy/masking-audit'),
  maskingLatest: () => get('/privacy/masking-audit/latest'),
  posture: () => get('/security/posture'),
  postureCheck: () => post('/security/posture/check'),
  mfa: () => get('/security/mfa-enforcement'),
  enforceMfa: (grace_days: number) => post('/security/mfa-enforcement/enforce', {}, { grace_days }),
  scans: () => get('/security/scans'),
  vapt: () => get('/security/vapt'),
  iso: () => get('/security/iso-readiness'),
  platformPosture: () => get('/security/platform-posture'),
  jwt: () => get('/security/jwt'),
  runSuite: (suite: string, env = 'dev') => post('/qa/suites/run', {}, { suite, env }),
  runs: () => get('/qa/suites/runs'),
  report2: (id: string) => get(`/qa/suites/runs/${id}/report`),
  golden: () => post('/qa/golden/run'),
  matrix: () => get('/qa/access-matrix'),
  loadResults: () => get('/qa/load-results'),
};
