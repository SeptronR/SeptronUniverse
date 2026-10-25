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
const del = <T = Any>(url: string, params?: Params) => api.delete(url, { params }) as unknown as Promise<Envelope<T>>;

/** Placement, internships, training and the recruiter portal (Prompts/28 §28.8). */
export const plApi = {
  // companies
  companies: (p: Params = {}) => get('/placement/companies', p),
  company: (id: string) => get(`/placement/companies/${id}`),
  createCompany: (b: Body) => post('/placement/companies', b),
  updateCompany: (id: string, b: Body) => put(`/placement/companies/${id}`, b),
  blacklistCompany: (id: string, b: Body) => post(`/placement/companies/${id}/blacklist`, b),
  inviteRecruiter: (id: string, b: Body) => post(`/placement/companies/${id}/recruiters/invite`, b),
  companyFeedback: (id: string) => get(`/placement/companies/${id}/feedback`),
  // policies
  policies: () => get('/placement/policies'),
  createPolicy: (b: Body) => post('/placement/policies', b),
  updatePolicy: (id: string, b: Body) => put(`/placement/policies/${id}`, b),
  effectivePolicy: (p: Params) => get('/placement/policies/effective', p),
  // drives
  drives: (p: Params = {}) => get('/placement/drives', p),
  drive: (id: string) => get(`/placement/drives/${id}`),
  createDrive: (b: Body) => post('/placement/drives', b),
  updateDrive: (id: string, b: Body) => put(`/placement/drives/${id}`, b),
  driveAction: (id: string, action: string, reason?: string) => post(`/placement/drives/${id}/action`, { action, reason }),
  preview: (id: string) => get(`/placement/drives/${id}/eligibility-preview`),
  eligibleList: (id: string) => get(`/placement/drives/${id}/eligible-list`),
  applications: (id: string, p: Params = {}) => get(`/placement/drives/${id}/applications`, p),
  shortlist: (id: string, rows: Body[]) => post(`/placement/drives/${id}/shortlist`, { rows }),
  reEvaluate: (id: string) => post(`/placement/drives/${id}/re-evaluate`),
  rounds: (id: string) => get(`/placement/drives/${id}/rounds`),
  addRound: (id: string, b: Body) => post(`/placement/drives/${id}/rounds`, b),
  updateRound: (id: string, b: Body) => put(`/placement/rounds/${id}`, b),
  roundResults: (id: string, b: Body) => post(`/placement/rounds/${id}/results`, b),
  funnel: (id: string) => get(`/placement/drives/${id}/funnel`),
  driveFeedback: (id: string, b: Body) => post(`/placement/drives/${id}/feedback`, b),
  // student
  openDrives: () => get('/placement/drives/open'),
  apply: (id: string, b: Body = {}) => post(`/placement/drives/${id}/apply`, b, {}),
  withdraw: (id: string) => post(`/placement/applications/${id}/withdraw`),
  myApplications: () => get('/placement/applications/me'),
  wardApplications: () => get('/placement/applications/wards'),
  override: (b: Body) => post('/placement/applications/override-eligibility', b),
  // offers
  offers: (p: Params = {}) => get('/placement/offers', p),
  offer: (id: string) => get(`/placement/offers/${id}`),
  createOffer: (b: Body) => post('/placement/offers', b),
  myOffers: () => get('/placement/offers/me'),
  wardOffers: () => get('/placement/offers/wards'),
  decide: (id: string, action: 'accept' | 'decline', reason?: string) => post(`/placement/offers/${id}/decision`, { action, reason }),
  offerStatus: (id: string, status: string, reason?: string) => post(`/placement/offers/${id}/status`, { status, reason }),
  pendingOffers: () => get('/placement/offers/pending'),
  confirmPending: (applicationId: string) => post(`/placement/offers/pending/${applicationId}/confirm`),
  // profiles
  myProfile: () => get('/placement/profile/me'),
  updateProfile: (b: Body) => put('/placement/profile/me', b),
  renderResume: (template_key: string) => post('/placement/profile/me/resume/render', { template_key }),
  optOut: (b: Body) => post('/placement/profile/me/opt-out', b),
  profiles: (p: Params = {}) => get('/placement/profiles', p),
  profile: (enrollmentId: string) => get(`/placement/profiles/${enrollmentId}`),
  // blacklist
  blacklist: () => get('/placement/blacklist'),
  addBlacklist: (b: Body) => post('/placement/blacklist', b),
  removeBlacklist: (enrollmentId: string, reason?: string) => del(`/placement/blacklist/${enrollmentId}`, { reason }),
  // stats & reports
  stats: (p: Params = {}) => get('/placement/stats', p),
  nirfSheet: (p: Params = {}) => get('/placement/stats/nirf-sheet', p),
  report: (kind: string) => get(`/placement/reports/${kind}`),
  // internships
  internships: (p: Params = {}) => get('/internships', p),
  internship: (id: string) => get(`/internships/${id}`),
  createInternship: (b: Body) => post('/internships', b),
  updateInternship: (id: string, b: Body) => put(`/internships/${id}`, b),
  noc: (id: string, b: Body = {}) => post(`/internships/${id}/noc`, b),
  evaluate: (id: string, b: Body) => post(`/internships/${id}/evaluate`, b),
  ppo: (id: string, b: Body) => post(`/internships/${id}/ppo`, b),
  myInternships: () => get('/internships/me'),
  // training
  trainings: () => get('/training/programs'),
  createTraining: (b: Body) => post('/training/programs', b),
  updateTraining: (id: string, b: Body) => put(`/training/programs/${id}`, b),
  trainingAttendance: (id: string, rows: Body[]) => post(`/training/programs/${id}/attendance`, { rows }),
  trainingScores: (id: string, rows: Body[]) => post(`/training/programs/${id}/scores`, { rows }),
  myTraining: () => get('/training/me'),
  // recruiter portal
  recruiterMe: () => get('/recruiter/me'),
  recruiterDrives: () => get('/recruiter/drives'),
  recruiterCreateDrive: (b: Body) => post('/recruiter/drives', b),
  recruiterUpdateDrive: (id: string, b: Body) => put(`/recruiter/drives/${id}`, b),
  recruiterApplicants: (id: string) => get(`/recruiter/drives/${id}/applicants`),
  recruiterShortlistUrl: (id: string) => `/recruiter/drives/${id}/shortlist.xlsx`,
  recruiterShortlist: (id: string) => api.get(`/recruiter/drives/${id}/shortlist.xlsx`, { responseType: 'blob' }) as unknown as Promise<Blob>,
  recruiterAddRound: (id: string, b: Body) => post(`/recruiter/drives/${id}/rounds`, b),
  recruiterResults: (roundId: string, b: Body) => post(`/recruiter/rounds/${roundId}/results`, b),
  recruiterOffer: (id: string, b: Body) => post(`/recruiter/drives/${id}/offers`, b),
  recruiterFeedback: (id: string, b: Body) => post(`/recruiter/drives/${id}/feedback`, b),
};
