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

/** Exam administration (Prompts/14 §14.8). */
export const examsApi = {
  sessions: (p: Params = {}) => get('/exam-sessions', { params: p }),
  session: (id: string) => get(`/exam-sessions/${id}`),
  createSession: (b: Body) => post('/exam-sessions', b),
  updateSession: (id: string, b: Body) => put(`/exam-sessions/${id}`, b),
  status: (id: string, status: string) => post(`/exam-sessions/${id}/status`, { status }),
  papers: (id: string) => get(`/exam-sessions/${id}/papers`),
  papersBulk: (id: string, dry: boolean) => post(`/exam-sessions/${id}/papers/bulk`, { dry_run: dry }, { ...once, params: { dry_run: dry } }),
  dateSheet: (id: string, entries: Body[]) => put(`/exam-sessions/${id}/date-sheet`, { entries }),
  clashes: (id: string) => post(`/exam-sessions/${id}/date-sheet/check-clashes`),
  publishDateSheet: (id: string, force = false) => post(`/exam-sessions/${id}/date-sheet/publish`, {}, { ...once, params: { force } }),
  dateSheetPdf: (id: string) => blob(`/exam-sessions/${id}/date-sheet.pdf`),
  dateSheetIcs: (id: string) => blob(`/exam-sessions/${id}/date-sheet.ics`),
  registrations: (id: string, p: Params = {}) => get(`/exam-sessions/${id}/registrations`, { params: p }),
  regAction: (id: string, action: 'cancel' | 'debar' | 'reinstate', reason: string) => post(`/exam-registrations/${id}/${action}`, { reason }),
  bulkRegister: (id: string) => post(`/exam-sessions/${id}/registrations/bulk`),
  applyEligibility: (id: string, recompute = false) => post(`/exam-sessions/${id}/eligibility/apply`, { recompute }),
  eligibilitySummary: (id: string) => get(`/exam-sessions/${id}/eligibility/summary`),
  generateHallTickets: (id: string, only_missing = true) => post(`/exam-sessions/${id}/hall-tickets/generate`, { only_missing }),
  hallTicket: (regId: string) => blob(`/exam-registrations/${regId}/hall-ticket.pdf`),
  seatingGenerate: (id: string, b: Body) => post(`/exam-sessions/${id}/seating/generate`, b),
  seating: (id: string, p: Params = {}) => get(`/exam-sessions/${id}/seating`, { params: p }),
  publishSeating: (id: string, p: Params = {}) => post(`/exam-sessions/${id}/seating/publish`, {}, { ...once, params: p }),
  chart: (planId: string, door = false) => blob(`/exam-seating-plans/${planId}/${door ? 'door-list' : 'chart'}.pdf`),
  autoAssign: (id: string, b: Body) => post(`/exam-sessions/${id}/invigilation/auto-assign`, b),
  roster: (id: string, p: Params = {}) => get(`/exam-sessions/${id}/invigilation`, { params: p }),
  swapDecide: (dutyId: string, decision: 'approve' | 'reject', with_staff_id?: string) => post(`/invigilation-duties/${dutyId}/swap/${decision}`, {}, { ...once, params: { with_staff_id } }),
  remuneration: (id: string) => get(`/exam-sessions/${id}/remuneration`),
  qp: (paperId: string) => get(`/exam-papers/${paperId}/qp-assignments`),
  qpCreate: (paperId: string, b: Body) => post(`/exam-papers/${paperId}/qp-assignments`, b),
  qpScrutinise: (id: string, decision: 'approve' | 'reject', remarks?: string) => post(`/qp-assignments/${id}/scrutinise`, { decision, remarks: remarks ?? null }),
  qpSelect: (id: string) => post(`/qp-assignments/${id}/select`),
  qpPrint: (id: string, copies: number) => post(`/qp-assignments/${id}/print`, { copies }),
  qpDownload: (token: string) => blob(`/qp/download/${token}`),
  hallRoster: (paperId: string) => get(`/exam-papers/${paperId}/attendance`),
  /** Hall attendance carries an Idempotency-Key (axios interceptor default). */
  markHall: (paperId: string, items: Body[]) => api.post(`/exam-papers/${paperId}/attendance`, { items }) as unknown as Promise<Envelope<Any>>,
  malpractice: (paperId: string, b: Body) => post(`/exam-papers/${paperId}/malpractice-reports`, b),
  myDuties: () => get('/invigilation-duties/me'),
  swapRequest: (id: string, reason: string, with_staff_id?: string) => post(`/invigilation-duties/${id}/swap-request`, { reason, with_staff_id: with_staff_id ?? null }),
  dutyLetter: (id: string) => blob(`/invigilation-duties/${id}/letter.pdf`),
  myQp: () => get('/qp-assignments/me'),
  qpUpload: (id: string, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return api.post(`/qp-assignments/${id}/upload`, fd, once) as unknown as Promise<Envelope<Any>>;
  },
  qpGenerate: (id: string) => post(`/qp-assignments/${id}/generate-from-blueprint`),
  myRegistration: (p: Params = {}) => get('/exam-registration/me', { params: p }),
  /** Submit carries an Idempotency-Key (axios interceptor default). */
  submit: (p: Params = {}) => api.post('/exam-registration/me/submit', {}, { params: p }) as unknown as Promise<Envelope<Any>>,
  myHallTicket: (p: Params = {}) => blob('/exam-registration/me/hall-ticket.pdf', p),
  mySeats: () => get('/exam-registration/me/seat'),
};

export function openBlob(b: Blob, filename?: string) {
  const url = URL.createObjectURL(b);
  if (filename) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
  } else window.open(url, '_blank', 'noopener');
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
