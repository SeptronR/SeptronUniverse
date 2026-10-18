import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  AlertConfig,
  Checkin,
  Condonation,
  DetentionRow,
  EligibilityRow,
  EligibilityRun,
  HistoryRow,
  MarkResult,
  MissingSession,
  MySummary,
  OfferingSummary,
  OfflineResult,
  OnDuty,
  QrIssue,
  RegisterGrid,
  SessionSheet,
  SummaryRow,
  UnmatchedPunch,
} from './types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T>(url: string, body?: unknown, config: AxiosRequestConfig = once) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const upload = <T>(url: string, file: File) => {
  const fd = new FormData();
  fd.append('file', file);
  return api.post(url, fd, once) as unknown as Promise<Envelope<T>>;
};

/** Marking, QR / geo, summaries, OD, condonation, eligibility (Prompts/11 §11.8). */
export const attendanceApi = {
  sheet: (sessionId: string) => get<SessionSheet>(`/class-sessions/${sessionId}/attendance`),
  /** Bulk mark carries an Idempotency-Key (axios interceptor default). */
  mark: (sessionId: string, b: Body) => api.post(`/class-sessions/${sessionId}/attendance`, b) as unknown as Promise<Envelope<MarkResult>>,
  finalize: (sessionId: string, note?: string) => post<SessionSheet>(`/class-sessions/${sessionId}/finalize`, { note: note ?? null }),
  editFinalized: (sessionId: string, b: Body) => post<MarkResult>(`/class-sessions/${sessionId}/attendance/edit-finalized`, b),
  issueQr: (sessionId: string) => post<QrIssue>(`/class-sessions/${sessionId}/qr`),
  qrCheckin: (token: string) => post<Checkin>('/attendance/qr-checkin', { token }),
  geoCheckin: (b: Body) => post<Checkin>('/attendance/geo-checkin', b),
  offline: (b: Body) => post<OfflineResult>('/attendance/offline-batch', b),
  unmatched: () => get<UnmatchedPunch[]>('/attendance/punches/unmatched'),
  missing: (params: Params = {}) => get<MissingSession[]>('/attendance/missing-sessions', { params }),
  summaries: (params: Params = {}) => get<SummaryRow[]>('/attendance/summary', { params }),
  offerings: (params: Params = {}) => get<OfferingSummary[]>('/attendance/summary/offerings', { params }),
  me: (params: Params = {}) => get<MySummary>('/attendance/summary/me', { params }),
  history: (params: Params = {}) => get<HistoryRow[]>('/attendance/history/me', { params }),
  student: (id: string, params: Params = {}) => get<MySummary>(`/attendance/summary/student/${id}`, { params }),
  register: (params: Params) => get<RegisterGrid>('/attendance/register', { params }),
  exportRegister: (params: Params) => get<{ job_id: string }>('/attendance/register', { params: { ...params, export: true } }),
  recompute: (termId: string) =>
    post<{ job_id: string }>('/attendance/recompute', undefined, { params: { term_id: termId }, idempotent: false } as AxiosRequestConfig),
  alertConfig: () => get<AlertConfig>('/attendance/alert-config'),
  saveAlertConfig: (b: Body) => put<AlertConfig>('/attendance/alert-config', b),
  ods: (params: Params = {}) => get<OnDuty[]>('/on-duty', { params }),
  applyOd: (b: Body) => post<OnDuty>('/on-duty', b),
  odDocument: (id: string, f: File) => upload<OnDuty>(`/on-duty/${id}/documents`, f),
  odAction: (id: string, action: 'recommend' | 'approve' | 'reject' | 'withdraw', comment?: string) =>
    post<OnDuty>(`/on-duty/${id}/${action}`, action === 'withdraw' ? undefined : { comment: comment ?? null }),
  condonations: (params: Params = {}) => get<Condonation[]>('/condonations', { params }),
  myCondonations: () => get<Condonation[]>('/condonations/me'),
  requestCondonation: (b: Body) => post<Condonation>('/condonations', b),
  condonationDocument: (id: string, f: File) => upload<Condonation>(`/condonations/${id}/documents`, f),
  condonationAction: (id: string, action: 'recommend' | 'approve' | 'reject', comment?: string) =>
    post<Condonation>(`/condonations/${id}/${action}`, { comment: comment ?? null }),
  compute: (termId: string, b: Body) => post<EligibilityRun>(`/terms/${termId}/eligibility/compute`, b),
  versions: (termId: string) => get<number[]>(`/terms/${termId}/eligibility/versions`),
  eligibility: (termId: string, params: Params = {}) => get<EligibilityRow[]>(`/terms/${termId}/eligibility`, { params }),
  decide: (id: string, b: Body) => post<EligibilityRow>(`/eligibility/${id}/decide`, b),
  detention: (termId: string, params: Params = {}) => get<DetentionRow[]>(`/terms/${termId}/detention-list`, { params }),
  exportDetention: (termId: string, params: Params = {}) =>
    get<{ job_id: string }>(`/terms/${termId}/detention-list`, { params: { ...params, export: true } }),
  notifyDetained: (termId: string) => post<{ notified: number }>(`/terms/${termId}/detention-list/notify`),
  myEligibility: (params: Params = {}) => get<EligibilityRow[]>('/eligibility/me', { params }),
};
