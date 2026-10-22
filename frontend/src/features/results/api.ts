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
const blob = (url: string, params?: Params) => api.get(url, { params, responseType: 'blob' }) as unknown as Promise<Blob>;

/** Evaluation & results (Prompts/15 §15.8). Evaluator routes return dummy numbers only. */
export const resultsApi = {
  // coding & custody
  bundles: (paperId: string) => get(`/exam-papers/${paperId}/bundles`),
  createBundles: (paperId: string, size = 30) => post(`/exam-papers/${paperId}/bundles`, { size }),
  code: (bundleId: string) => post(`/bundles/${bundleId}/code`),
  custody: (bundleId: string) => get(`/bundles/${bundleId}/custody`),
  logCustody: (bundleId: string, b: Body) => post(`/bundles/${bundleId}/custody`, b),
  // valuation (exam cell)
  assign: (paperId: string, b: Body) => post(`/exam-papers/${paperId}/valuation/assign`, b),
  valuationStatus: (paperId: string) => get(`/exam-papers/${paperId}/valuation/status`),
  reassign: (id: string, b: Body) => post(`/valuation-assignments/${id}/reassign`, b),
  reconcile: (paperId: string) => post(`/exam-papers/${paperId}/valuation/reconcile`),
  thirdAssign: (paperId: string, b: Body) => post(`/exam-papers/${paperId}/valuation/third-assign`, b),
  // evaluator
  myBundles: () => get('/valuation/me/bundles'),
  bundleScripts: (bundleId: string) => get(`/valuation/bundles/${bundleId}/scripts`),
  submitMarks: (scriptId: string, round: number, b: Body) => post(`/answer-scripts/${scriptId}/valuations/${round}`, b),
  submitBundle: (bundleId: string) => post(`/valuation/bundles/${bundleId}/submit`),
  scan: (scriptId: string) => get(`/answer-scripts/${scriptId}/scan`),
  // moderation & decode
  moderation: (paperId: string) => get(`/exam-papers/${paperId}/moderation`),
  propose: (paperId: string, b: Body) => post(`/exam-papers/${paperId}/moderation`, b),
  moderationAction: (id: string, action: 'approve' | 'apply' | 'revert') => post(`/moderation-actions/${id}/${action}`, {}),
  decode: (paperId: string) => post(`/exam-papers/${paperId}/decode`),
  // runs
  runs: (p: Params = {}) => get('/result-runs', { params: p }),
  run: (id: string) => get(`/result-runs/${id}`),
  createRun: (b: Body) => post('/result-runs', b),
  anomalies: (id: string, code?: string) => get(`/result-runs/${id}/anomalies`, { params: { code } }),
  runAction: (id: string, action: 'verify' | 'approve' | 'rollback', b: Body = {}) => post(`/result-runs/${id}/${action}`, b),
  publish: (id: string, b: Body) => post(`/result-runs/${id}/publish`, b),
  rows: (id: string, p: Params = {}) => get(`/result-runs/${id}/rows`, { params: p }),
  exportRun: (id: string) => blob(`/result-runs/${id}/export`),
  gradeCards: (runId: string) => post(`/result-runs/${runId}/grade-cards`),
  // views
  myResults: (p: Params = {}) => get('/results/me', { params: p }),
  wardResults: (studentId: string) => get(`/results/wards/${studentId}`),
  offeringResults: (offeringId: string) => get(`/course-offerings/${offeringId}/results`),
  tabulation: (p: Params) => get('/results/tabulation', { params: p }),
  tabulationXlsx: (p: Params) => blob('/results/tabulation/export', p),
  analysis: (p: Params) => get('/results/analysis', { params: p }),
  rankList: (p: Params) => get('/results/rank-list', { params: p }),
  myCards: () => get('/grade-cards/me'),
  cardPdf: (id: string) => blob(`/grade-cards/${id}.pdf`),
  // legacy import
  legacyUpload: (batch_id: string, term_number: number, file: File, mapping?: Body) => {
    const fd = new FormData();
    fd.append('batch_id', batch_id);
    fd.append('term_number', String(term_number));
    if (mapping) fd.append('mapping', JSON.stringify(mapping));
    fd.append('file', file);
    return api.post('/legacy-results/imports', fd, once) as unknown as Promise<Envelope<Any>>;
  },
  legacy: (id: string) => get(`/legacy-results/imports/${id}`),
  legacyAction: (id: string, action: 'validate' | 'apply' | 'rollback') => post(`/legacy-results/imports/${id}/${action}`),
  // custody & retention
  archive: (sessionId: string) => post(`/exam-sessions/${sessionId}/scripts/archive`, {}),
  destroy: (sessionId: string, approval_note: string) => post(`/exam-sessions/${sessionId}/scripts/destroy`, { approval_note }),
  register: (sessionId: string) => get(`/exam-sessions/${sessionId}/scripts/register`),
  // public
  lookup: (b: Body) => post('/public/results/lookup', b),
  verify: (token: string) => get(`/verify/${token}`),
};
