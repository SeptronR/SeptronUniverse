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
const pdf = (url: string) => api.get(url, { responseType: 'blob' }) as unknown as Promise<Blob>;

/** Affiliation: registry, applications, inspections, decisions, programme approvals, fees, submissions, centres (Prompts/34 §34.8). */
export const affApi = {
  // registry / dashboards
  colleges: (p: Params = {}) => get('/affiliation/colleges', p),
  profile: (id: string) => get(`/affiliation/colleges/${id}/profile`),
  updateProfile: (id: string, b: Body) => put(`/affiliation/colleges/${id}/profile`, b),
  collegeDashboard: (id: string) => get(`/affiliation/colleges/${id}/dashboard`),
  myDashboard: () => get('/affiliation/colleges/me/dashboard'),
  documents: (id: string) => get(`/affiliation/colleges/${id}/documents`),
  addDocument: (id: string, b: Body) => post(`/affiliation/colleges/${id}/documents`, b),
  portfolio: () => get('/affiliation/portfolio'),
  // applications
  applications: (p: Params = {}) => get('/affiliation/applications', p),
  application: (id: string) => get(`/affiliation/applications/${id}`),
  createApplication: (b: Body) => post('/affiliation/applications', b),
  updateApplication: (id: string, b: Body) => put(`/affiliation/applications/${id}`, b),
  applicationAction: (id: string, action: 'submit' | 'withdraw', remarks?: string) => post(`/affiliation/applications/${id}/action`, { action, remarks }),
  checklist: (id: string) => get(`/affiliation/applications/${id}/checklist`),
  feePreview: (id: string) => get(`/affiliation/applications/${id}/fee-preview`),
  scrutiny: (id: string, b: Body) => post(`/affiliation/applications/${id}/scrutiny`, b),
  scheduleInspection: (id: string, b: Body) => post(`/affiliation/applications/${id}/inspection/schedule`, b),
  inspectionReport: (id: string, b: Body) => post(`/affiliation/applications/${id}/inspection/report`, b),
  respondDeficiency: (id: string, did: string, b: Body) => post(`/affiliation/applications/${id}/deficiencies/${did}/respond`, b),
  closeDeficiency: (id: string, did: string, b: Body) => post(`/affiliation/applications/${id}/deficiencies/${did}/close`, b),
  reinspect: (id: string, b: Body) => post(`/affiliation/applications/${id}/reinspect`, b),
  decide: (id: string, b: Body) => post(`/affiliation/applications/${id}/decide`, b),
  orderPdf: (id: string) => pdf(`/affiliation/applications/${id}/order.pdf`),
  myInspections: () => get('/affiliation/inspections/me'),
  inspections: (p: Params = {}) => get('/affiliation/inspections', p),
  // programme approvals / fees
  approvals: (p: Params = {}) => get('/affiliation/program-approvals', p),
  updateApproval: (id: string, b: Body) => put(`/affiliation/program-approvals/${id}`, b),
  approvalCheck: (p: Params) => get('/affiliation/program-approvals/check', p),
  carryForward: (academic_year_id: string) => post('/affiliation/program-approvals/carry-forward?inline=true', { academic_year_id }),
  feeSchedules: (p: Params = {}) => get('/affiliation/fee-schedules', p),
  createFeeSchedule: (b: Body) => post('/affiliation/fee-schedules', b),
  updateFeeSchedule: (id: string, b: Body) => put(`/affiliation/fee-schedules/${id}`, b),
  dues: (p: Params = {}) => get('/affiliation/dues', p),
  // submissions
  windows: (p: Params) => get('/affiliation/submissions/windows', p),
  submissions: (p: Params = {}) => get('/affiliation/submissions', p),
  submission: (id: string) => get(`/affiliation/submissions/${id}`),
  createSubmission: (b: Body) => post('/affiliation/submissions', b),
  extract: (id: string) => post(`/affiliation/submissions/${id}/extract?inline=true`),
  importFile: (id: string, b: Body) => post(`/affiliation/submissions/${id}/import?inline=true`, b),
  validate: (id: string) => post(`/affiliation/submissions/${id}/validate?inline=true`),
  report: (id: string) => get(`/affiliation/submissions/${id}/report`),
  submissionAction: (id: string, action: string, remarks?: string) => post(`/affiliation/submissions/${id}/action`, { action, remarks }),
  compliance: (p: Params) => get('/affiliation/submissions/compliance', p),
  collegeStatus: (sessionId: string) => get(`/affiliation/exam-sessions/${sessionId}/college-status`),
  // exam centres
  centres: (p: Params = {}) => get('/affiliation/exam-centres', p),
  centre: (id: string) => get(`/affiliation/exam-centres/${id}`),
  createCentre: (b: Body) => post('/affiliation/exam-centres', b),
  updateCentre: (id: string, b: Body) => put(`/affiliation/exam-centres/${id}`, b),
  allocate: (b: Body) => post('/affiliation/exam-centres/allocate?inline=true', b),
  appointment: (id: string) => post(`/affiliation/exam-centres/${id}/appointment?inline=true`),
  centreDashboard: (id: string) => get(`/affiliation/exam-centres/${id}/dashboard`),
  myCentres: () => get('/affiliation/exam-centres/me'),
  // returns
  returns: (kind: string, p: Params = {}) => get(`/affiliation/returns/${kind}`, { inline: true, ...p }),
};
