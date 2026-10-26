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
const q = (institution: string) => `?institution=${encodeURIComponent(institution)}`;

/** PhD & research-scholar management (Prompts/31 §31.8). */
export const phdApi = {
  // scholars / portal
  scholars: (p: Params = {}) => get('/phd/scholars', p),
  scholar: (id: string) => get(`/phd/scholars/${id}`),
  createScholar: (b: Body) => post('/phd/scholars', b),
  updateScholar: (id: string, b: Body) => put(`/phd/scholars/${id}`, b),
  allocateGuide: (id: string, b: Body) => post(`/phd/scholars/${id}/guide`, b),
  discontinue: (id: string, b: Body) => post(`/phd/scholars/${id}/discontinue`, b),
  guideLoad: (p: Params = {}) => get('/phd/guides/load', p),
  me: () => get('/phd/me'),
  dashboard: () => get('/phd/me/dashboard'),
  // coursework
  coursework: (id: string) => get(`/phd/scholars/${id}/coursework`),
  planCoursework: (id: string, b: Body) => put(`/phd/scholars/${id}/coursework`, b),
  exemption: (id: string, b: Body) => post(`/phd/scholars/${id}/coursework/exemption`, b),
  completeCoursework: (id: string) => post(`/phd/scholars/${id}/coursework/complete`),
  // DC
  dc: (id: string) => get(`/phd/scholars/${id}/dc`),
  constitute: (id: string, b: Body) => post(`/phd/scholars/${id}/dc`, b),
  reconstitute: (id: string, b: Body) => put(`/phd/scholars/${id}/dc/members`, b),
  meetings: (id: string) => get(`/phd/scholars/${id}/dc-meetings`),
  schedule: (id: string, b: Body) => post(`/phd/scholars/${id}/dc-meetings`, b),
  minutes: (mid: string, b: Body) => put(`/phd/dc-meetings/${mid}/minutes`, b),
  approveMeeting: (mid: string, b: Body = {}) => post(`/phd/dc-meetings/${mid}/approve`, b),
  // progress
  reports: (id: string) => get(`/phd/scholars/${id}/progress-reports`),
  periods: (id: string) => get(`/phd/scholars/${id}/progress-periods`),
  submitReport: (id: string, b: Body) => post(`/phd/scholars/${id}/progress-reports`, b),
  guideReview: (rid: string, b: Body) => post(`/phd/progress-reports/${rid}/guide-review`, b),
  dcReview: (rid: string, b: Body) => post(`/phd/progress-reports/${rid}/dc-review`, b),
  compliance: (p: Params = {}) => get('/phd/progress-reports/compliance', p),
  cancellationDecision: (rid: string, b: Body) => post(`/phd/requests/${rid}/cancellation-decision`, b),
  // fellowships
  fellowships: (id: string) => get(`/phd/scholars/${id}/fellowship`),
  createFellowship: (id: string, b: Body) => post(`/phd/scholars/${id}/fellowship`, b),
  statement: (id: string, year?: number) => get(`/phd/scholars/${id}/fellowship/statement`, { year }),
  updateFellowship: (fid: string, b: Body) => put(`/phd/fellowships/${fid}`, b),
  run: (month: string) => post('/phd/fellowships/run?inline=true', { month }),
  disbursements: (p: Params = {}) => get('/phd/disbursements', p),
  approve: (did: string) => post(`/phd/disbursements/${did}/approve`),
  hold: (did: string, reason: string) => post(`/phd/disbursements/${did}/hold`, { reason }),
  release: (did: string) => post(`/phd/disbursements/${did}/release`),
  contingency: (did: string, b: Body) => post(`/phd/disbursements/${did}/contingency`, b),
  pay: (b: Body) => post('/phd/disbursements/pay', b),
  myDisbursements: () => get('/phd/fellowships/me'),
  // requests
  requests: (p: Params = {}) => get('/phd/requests', p),
  scholarRequests: (id: string) => get(`/phd/scholars/${id}/requests`),
  raise: (id: string, b: Body) => post(`/phd/scholars/${id}/requests`, b),
  noc: (rid: string, b: Body) => post(`/phd/requests/${rid}/guide-noc`, b),
  decide: (rid: string, b: Body) => post(`/phd/requests/${rid}/decide`, b),
  // thesis
  thesisQueue: (p: Params = {}) => get('/phd/thesis', p),
  theses: (id: string) => get(`/phd/scholars/${id}/thesis`),
  submitThesis: (id: string, b: Body) => post(`/phd/scholars/${id}/thesis`, b),
  check: (tid: string) => post(`/phd/thesis/${tid}/plagiarism/check?inline=true`),
  dcApproval: (tid: string) => post(`/phd/thesis/${tid}/dc-approval`),
  rejectThesis: (tid: string, reason: string) => post(`/phd/thesis/${tid}/reject`, { reason }),
  certificateUrl: (tid: string) => `/api/v1/phd/thesis/${tid}/certificate.pdf`,
  // examiners
  tracker: (p: Params = {}) => get('/phd/examiners', p),
  panel: (tid: string) => get(`/phd/thesis/${tid}/examiners`),
  propose: (tid: string, b: Body) => post(`/phd/thesis/${tid}/examiners`, b),
  decidePanel: (tid: string, b: Body) => post(`/phd/thesis/${tid}/examiners/decide`, b),
  recommendations: (tid: string) => get(`/phd/thesis/${tid}/recommendations`),
  invite: (eid: string) => post(`/phd/examiners/${eid}/invite`, {}),
  dispatch: (eid: string) => post(`/phd/examiners/${eid}/dispatch`),
  report: (eid: string, b: Body) => post(`/phd/examiners/${eid}/report`, b),
  replace: (eid: string, b: Body) => post(`/phd/examiners/${eid}/replace`, b),
  remuneration: (eid: string, b: Body) => post(`/phd/examiners/${eid}/remuneration`, b),
  tokenView: (institution: string, token: string) => get(`/phd/examiners/respond/${token}${q(institution)}`),
  tokenRespond: (institution: string, token: string, b: Body) => post(`/phd/examiners/respond/${token}${q(institution)}`, b),
  tokenReport: (institution: string, token: string, b: Body) => post(`/phd/examiners/respond/${token}/report${q(institution)}`, b),
  // viva / award / ETD
  upcoming: () => get('/phd/viva/upcoming'),
  viva: (tid: string) => get(`/phd/thesis/${tid}/viva`),
  scheduleViva: (tid: string, b: Body) => post(`/phd/thesis/${tid}/viva`, b),
  vivaResult: (vid: string, b: Body) => post(`/phd/viva/${vid}/result`, b),
  awards: (p: Params = {}) => get('/phd/awards', p),
  etdStatus: () => get('/phd/awards/etd-status'),
  award: (tid: string) => get(`/phd/thesis/${tid}/award`),
  requestAward: (tid: string, b: Body) => post(`/phd/thesis/${tid}/award`, b),
  etd: (tid: string) => get(`/phd/thesis/${tid}/etd`),
  upload: (tid: string, repository = 'shodhganga') => post(`/phd/thesis/${tid}/etd?inline=true`, { repository }),
  retryEtd: (eid: string) => post(`/phd/etd/${eid}/retry`),
  embargo: (eid: string, b: Body) => post(`/phd/etd/${eid}/embargo`, b),
  // stats / reports
  stats: (p: Params = {}) => get('/phd/stats', p),
  reportUrl: (kind: string, year?: number) => `/api/v1/phd/reports/${kind}?inline=true&format=xlsx${year ? `&year=${year}` : ''}`,
};
