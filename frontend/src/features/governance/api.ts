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
const del = <T = Any>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;
const pdf = (url: string) => api.get(url, { responseType: 'blob' }) as unknown as Promise<Blob>;

/** Governance: committees, meetings / minutes / resolutions, legal, RTI, audit paras, e-File, policies (Prompts/33 §33.8). */
export const govApi = {
  // committees
  committees: (p: Params = {}) => get('/governance/committees', p),
  myCommittees: () => get('/governance/committees/me'),
  coverage: () => get('/governance/committees/coverage'),
  templates: () => get('/governance/committees/templates'),
  committee: (id: string) => get(`/governance/committees/${id}`),
  createCommittee: (b: Body) => post('/governance/committees', b),
  fromTemplate: (b: Body) => post('/governance/committees/from-template', b),
  updateCommittee: (id: string, b: Body) => put(`/governance/committees/${id}`, b),
  reconstitute: (id: string, b: Body) => post(`/governance/committees/${id}/reconstitute`, b),
  addMember: (id: string, b: Body) => post(`/governance/committees/${id}/members`, b),
  updateMember: (id: string, b: Body) => put(`/governance/committee-members/${id}`, b),
  removeMember: (id: string) => del(`/governance/committee-members/${id}`),
  me: () => get('/governance/me'),
  // meetings
  meetings: (p: Params = {}) => get('/governance/meetings', p),
  myMeetings: () => get('/governance/meetings/me'),
  meeting: (id: string) => get(`/governance/meetings/${id}`),
  createMeeting: (b: Body) => post('/governance/meetings', b),
  updateMeeting: (id: string, b: Body) => put(`/governance/meetings/${id}`, b),
  setAgenda: (id: string, b: Body) => put(`/governance/meetings/${id}/agenda`, b),
  suggestions: (id: string) => get(`/governance/meetings/${id}/agenda/suggestions`),
  notice: (id: string, channels: string[]) => post(`/governance/meetings/${id}/notice`, { channels }),
  attendance: (id: string, b: Body) => post(`/governance/meetings/${id}/attendance`, b),
  draftMinutes: (id: string, b: Body) => post(`/governance/meetings/${id}/minutes`, b),
  submitMinutes: (id: string) => post(`/governance/meetings/${id}/minutes/submit`),
  approveMinutes: (id: string, b: Body) => post(`/governance/meetings/${id}/minutes/approve`, b),
  corrigendum: (id: string, b: Body) => post(`/governance/meetings/${id}/corrigendum`, b),
  cancelMeeting: (id: string, reason: string) => post(`/governance/meetings/${id}/cancel`, { reason }),
  minutesPdf: (id: string) => pdf(`/governance/meetings/${id}/minutes.pdf`),
  // resolutions / ATR
  resolutions: (p: Params = {}) => get('/governance/resolutions', p),
  resolution: (id: string) => get(`/governance/resolutions/${id}`),
  lookup: (entity_type: string, entity_id: string) => get('/governance/resolutions/lookup', { entity_type, entity_id }),
  link: (id: string, b: Body) => post(`/governance/resolutions/${id}/link`, b),
  resolutionStatus: (id: string, b: Body) => post(`/governance/resolutions/${id}/status`, b),
  extract: (id: string) => get(`/governance/resolutions/${id}/extract.pdf`),
  submitAtr: (id: string, b: Body) => post(`/governance/resolutions/${id}/atr`, b),
  decideAtr: (id: string, b: Body) => post(`/governance/atr/${id}/decide`, b),
  // legal
  cases: (p: Params = {}) => get('/legal/cases', p),
  legalCase: (id: string) => get(`/legal/cases/${id}`),
  createCase: (b: Body) => post('/legal/cases', b),
  hearing: (id: string, b: Body) => post(`/legal/cases/${id}/hearings`, b),
  outcome: (id: string, b: Body) => post(`/legal/cases/${id}/outcome`, b),
  caseDocuments: (id: string) => get(`/legal/cases/${id}/documents`),
  legalCalendar: (days = 60) => get('/legal/calendar', { days }),
  // RTI
  rti: (p: Params = {}) => get('/rti/requests', p),
  rtiOne: (id: string) => get(`/rti/requests/${id}`),
  createRti: (b: Body) => post('/rti/requests', b),
  assignRti: (id: string, b: Body) => post(`/rti/requests/${id}/assign`, b),
  consultRti: (id: string, b: Body) => post(`/rti/requests/${id}/consult`, b),
  respondRti: (id: string, b: Body) => post(`/rti/requests/${id}/respond`, b),
  appealRti: (id: string, b: Body) => post(`/rti/requests/${id}/appeal`, b),
  decideRti: (id: string, b: Body) => post(`/rti/requests/${id}/appeal/decide`, b),
  closeRti: (id: string) => post(`/rti/requests/${id}/close`, {}),
  rtiReturn: (period: string) => get('/rti/returns', { period, inline: true }),
  // audit paras
  paras: (p: Params = {}) => get('/audit-paras', p),
  myParas: () => get('/audit-paras/me'),
  paraDashboard: () => get('/audit-paras/dashboard'),
  createPara: (b: Body) => post('/audit-paras', b),
  replyPara: (id: string, b: Body) => post(`/audit-paras/${id}/reply`, b),
  paraStatus: (id: string, b: Body) => post(`/audit-paras/${id}/status`, b),
  registers: () => get('/accreditation/audits'),
  // e-File
  efiles: (box: 'inbox' | 'outbox' | 'mine' | 'all', p: Params = {}) => get(box === 'all' ? '/efiles' : `/efiles/${box}`, p),
  efile: (id: string) => get(`/efiles/${id}`),
  createEfile: (b: Body) => post('/efiles', b),
  moveEfile: (id: string, b: Body) => post(`/efiles/${id}/move`, b),
  closeEfile: (id: string, summary: string) => post(`/efiles/${id}/close`, { summary }),
  reopenEfile: (id: string, reason: string) => post(`/efiles/${id}/reopen`, { reason }),
  notingsPdf: (id: string) => pdf(`/efiles/${id}/notings.pdf`),
  pendency: (p: Params = {}) => get('/efiles/pendency', p),
  // policies
  policies: (p: Params = {}) => get('/policies', p),
  policy: (id: string) => get(`/policies/${id}`),
  createPolicy: (b: Body) => post('/policies', b),
  updatePolicy: (id: string, b: Body) => put(`/policies/${id}`, b),
  submitPolicy: (id: string) => post(`/policies/${id}/submit`),
  approvePolicy: (id: string, b: Body) => post(`/policies/${id}/approve`, b),
  publishPolicy: (id: string) => post(`/policies/${id}/publish`),
  supersedePolicy: (id: string) => post(`/policies/${id}/supersede`),
  acknowledge: (id: string) => post(`/policies/${id}/acknowledge`),
  acks: (id: string) => get(`/policies/${id}/acknowledgements`),
  pendingAcks: () => get('/policies/me/pending-ack'),
  // stats
  stats: (year?: number) => get('/governance/stats', { year }),
};
