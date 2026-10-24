import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const idem = { idempotent: true } as AxiosRequestConfig;
const post = <T = Any>(url: string, body?: unknown, config: AxiosRequestConfig = once) => api.post(url, body ?? {}, config) as unknown as Promise<Envelope<T>>;
const blob = (url: string) => api.get(url, { responseType: 'blob' }) as unknown as Promise<Blob>;

/** Post-result services (Prompts/16 §16.8). */
export const postResultApi = {
  sessions: () => get('/exam-sessions'),
  terms: () => get('/academic-terms'),
  batches: () => get('/batches', { params: { page_size: 200 } }),
  // revaluation
  eligibility: (session_id: string) => get('/reval/eligibility', { params: { session_id } }),
  requestReval: (b: Body) => post('/reval-requests', b, idem),
  myReval: () => get('/reval-requests/me'),
  photocopy: (id: string) => blob(`/reval-requests/${id}/photocopy.pdf`),
  sessionReval: (id: string, p: Params = {}) => get(`/exam-sessions/${id}/reval-requests`, { params: p }),
  assign: (id: string, b: Body) => post(`/reval-requests/${id}/assign`, b),
  retotal: (id: string, b: Body) => post(`/reval-requests/${id}/retotal`, b),
  decide: (id: string, b: Body) => post(`/reval-requests/${id}/decide`, b),
  reject: (id: string, b: Body = {}) => post(`/reval-requests/${id}/reject`, b),
  applyReval: (sessionId: string) => post(`/exam-sessions/${sessionId}/reval/apply`),
  challengePanel: (sessionId: string, b: Body) => post(`/exam-sessions/${sessionId}/challenge-panel`, b),
  // supplementary
  suppPreview: (b: Body) => post('/exam-sessions/supplementary/preview', b),
  suppCreate: (b: Body) => post('/exam-sessions/supplementary', b),
  // malpractice
  cases: (p: Params = {}) => get('/malpractice-cases', { params: p }),
  myCases: () => get('/malpractice-cases/me'),
  case: (id: string) => get(`/malpractice-cases/${id}`),
  caseAction: (id: string, action: string, b: Body = {}) => post(`/malpractice-cases/${id}/${action}`, b),
  // withheld / detained
  withheld: (session_id?: string) => get('/results/withheld', { params: { session_id } }),
  release: (b: Body) => post('/results/withheld/release', b),
  detained: (termId: string) => get(`/terms/${termId}/detained`),
  readmissions: () => get('/readmissions'),
  readmit: (b: Body) => post('/readmissions', b),
  readmissionDecide: (id: string, action: 'approve' | 'reject', comment?: string) => post(`/readmissions/${id}/${action}`, { comment }),
  // transcripts
  transcriptTypes: () => get('/transcripts/types'),
  requestTranscript: (b: Body) => post('/transcripts/requests', b, idem),
  transcriptRequests: (status?: string) => get('/transcripts/requests', { params: { status } }),
  myTranscripts: () => get('/transcripts/me'),
  transcriptChecks: (id: string) => get(`/transcripts/${id}/checks`),
  transcriptAction: (id: string, action: string, b: Body = {}) => post(`/transcripts/${id}/${action}`, b),
  downloadTranscript: (id: string) => blob(`/transcripts/${id}/download`),
  // rank lists, medals, corrections
  rankLists: (p: Params) => get('/results/rank-lists', { params: p }),
  myRank: () => get('/results/rank-lists/me'),
  publishRank: (b: Body) => post('/results/rank-lists/publish', b),
  medals: (p: Params = {}) => get('/results/medals', { params: p }),
  award: (b: Body) => post('/results/medals', b),
  revokeMedal: (id: string) => post(`/results/medals/${id}/revoke`),
  corrections: (status?: string) => get('/results/corrections', { params: { status } }),
  raiseCorrection: (b: Body) => post('/results/corrections', b),
  correctionDecide: (id: string, action: 'approve' | 'reject', comment?: string) => post(`/results/corrections/${id}/${action}`, { comment }),
};
