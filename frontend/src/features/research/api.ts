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

/** Research & faculty development (Prompts/30 §30.8). */
export const rsApi = {
  // publications
  publications: (p: Params = {}) => get('/research/publications', p),
  publication: (id: string) => get(`/research/publications/${id}`),
  addPublication: (b: Body) => post('/research/publications', b),
  updatePublication: (id: string, b: Body) => put(`/research/publications/${id}`, b),
  deletePublication: (id: string) => del(`/research/publications/${id}`),
  claim: (id: string, b: Body = {}) => post(`/research/publications/${id}/claim-coauthor`, b),
  importPreview: (b: Body) => post('/research/publications/import/preview', b),
  importApply: (b: Body) => post('/research/publications/import/apply?inline=true', b),
  verify: (b: Body) => post('/research/publications/verify', b),
  syncCitations: () => post('/research/publications/sync-citations'),
  // patents
  patents: (p: Params = {}) => get('/research/patents', p),
  addPatent: (b: Body) => post('/research/patents', b),
  updatePatent: (id: string, b: Body) => put(`/research/patents/${id}`, b),
  // projects
  projects: (p: Params = {}) => get('/research/projects', p),
  myProjects: () => get('/research/projects/me'),
  project: (id: string) => get(`/research/projects/${id}`),
  addProject: (b: Body) => post('/research/projects', b),
  projectAction: (id: string, b: Body) => post(`/research/projects/${id}/action`, b),
  ledger: (id: string) => get(`/research/projects/${id}/ledger`),
  expense: (id: string, b: Body) => post(`/research/projects/${id}/expense-requests`, b),
  addReport: (id: string, b: Body) => post(`/research/projects/${id}/reports`, b),
  addStaff: (id: string, b: Body) => post(`/research/projects/${id}/staff`, b),
  // consultancy
  consultancies: (p: Params = {}) => get('/research/consultancies', p),
  addConsultancy: (b: Body) => post('/research/consultancies', b),
  receipt: (id: string, b: Body) => post(`/research/consultancies/${id}/receipts`, b),
  shares: (id: string) => get(`/research/consultancies/${id}/shares`),
  // ethics
  committees: () => get('/research/ethics/committees'),
  addCommittee: (b: Body) => post('/research/ethics/committees', b),
  applications: (p: Params = {}) => get('/research/ethics/applications', p),
  apply: (b: Body) => post('/research/ethics/applications', b),
  review: (id: string, b: Body) => post(`/research/ethics/applications/${id}/review`, b),
  decide: (id: string, b: Body) => post(`/research/ethics/applications/${id}/decide`, b),
  amend: (id: string, kind: string, b: Body) => post(`/research/ethics/approvals/${id}/${kind}`, { ...b, kind }),
  // incentives
  slabs: () => get('/research/incentives/slabs'),
  incentives: (p: Params = {}) => get('/research/incentives', p),
  myIncentives: () => get('/research/incentives/me'),
  requestIncentive: (b: Body) => post('/research/incentives', b),
  decideIncentive: (id: string, b: Body) => post(`/research/incentives/${id}/decide`, b),
  disburse: (id: string, b: Body) => post(`/research/incentives/${id}/disburse`, b),
  // FDP / awards
  fdp: (p: Params = {}) => get('/research/fdp', p),
  addFdp: (b: Body) => post('/research/fdp', b),
  compliance: (p: Params) => get('/research/fdp/compliance', p),
  awards: (p: Params = {}) => get('/research/awards', p),
  addAward: (b: Body) => post('/research/awards', b),
  // MoUs / collaborations / start-ups
  mous: (p: Params = {}) => get('/research/mous', p),
  mou: (id: string) => get(`/research/mous/${id}`),
  addMou: (b: Body) => post('/research/mous', b),
  updateMou: (id: string, b: Body) => put(`/research/mous/${id}`, b),
  submitMou: (id: string) => post(`/research/mous/${id}/submit`),
  signMou: (id: string, b: Body) => post(`/research/mous/${id}/sign`, b),
  renewMou: (id: string) => post(`/research/mous/${id}/renew`),
  mouCollabs: (id: string) => get(`/research/mous/${id}/collaborations`),
  addCollab: (id: string, b: Body) => post(`/research/mous/${id}/collaborations`, b),
  collaborations: (p: Params = {}) => get('/research/collaborations', p),
  activityReport: (year: number) => get('/research/mous/activity-report', { year }),
  startups: (p: Params = {}) => get('/research/startups', p),
  addStartup: (b: Body) => post('/research/startups', b),
  stage: (id: string, b: Body) => post(`/research/startups/${id}/stage`, b),
  // API score / profile / stats
  computeApi: (b: Body) => post('/research/api-score/compute?inline=true', b),
  apiScore: (p: Params = {}) => get('/research/api-score', p),
  rankings: (p: Params = {}) => get('/research/api-score/rankings', p),
  myProfile: () => get('/research/profile/me'),
  profile: (staffId: string) => get(`/research/profile/${staffId}`),
  stats: (p: Params = {}) => get('/research/stats', p),
  report: (kind: string, p: Params = {}) => get(`/research/reports/${kind}`, p),
  evidencePack: (criterion: string, period?: number) => post(`/research/evidence-pack?criterion=${encodeURIComponent(criterion)}${period ? `&period=${period}` : ''}`),
};
