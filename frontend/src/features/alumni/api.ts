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

/** Alumni, endowments & fundraising (Prompts/29 §29.8). */
export const alApi = {
  // self
  me: () => get('/alumni/me'),
  updateMe: (b: Body) => put('/alumni/me', b),
  employment: () => get('/alumni/me/employment'),
  addEmployment: (b: Body) => post('/alumni/me/employment', b),
  updateEmployment: (id: string, b: Body) => put(`/alumni/me/employment/${id}`, b),
  deleteEmployment: (id: string) => del(`/alumni/me/employment/${id}`),
  engagement: () => get('/alumni/me/engagement'),
  cardUrl: '/api/v1/alumni/me/card.pdf',
  // claim (public)
  claim: (institution: string, b: Body) => post(`/alumni/claim?institution=${encodeURIComponent(institution)}`, b),
  claimVerify: (institution: string, b: Body) => post(`/alumni/claim/verify?institution=${encodeURIComponent(institution)}`, b),
  // coordinator
  profiles: (p: Params = {}) => get('/alumni/profiles', p),
  profile: (id: string) => get(`/alumni/profiles/${id}`),
  verify: (id: string, b: Body) => post(`/alumni/profiles/${id}/verify`, b),
  merge: (b: Body) => post('/alumni/profiles/merge', b),
  importRows: (b: Body) => post('/alumni/import/inline', b),
  importJob: (b: Body) => post('/alumni/import', b),
  exportJob: (p: Params = {}) => get('/alumni/profiles/export', p),
  claimLinks: () => post('/alumni/profiles/claim-links'),
  // directory
  directory: (p: Params = {}) => get('/alumni/directory', p),
  contact: (id: string, message: string) => post(`/alumni/directory/${id}/contact-request`, { message }),
  // events
  events: (p: Params = {}) => get('/alumni/events', p),
  event: (id: string) => get(`/alumni/events/${id}`),
  createEvent: (b: Body) => post('/alumni/events', b),
  invite: (id: string, b: Body) => post(`/alumni/events/${id}/invite`, b),
  myEvents: () => get('/alumni/events/me'),
  register: (eventId: string) => post(`/events/${eventId}/register`, {}),
  // jobs
  jobs: (p: Params = {}) => get('/alumni/jobs', p),
  postJob: (b: Body) => post('/alumni/jobs', b),
  myJobs: () => get('/alumni/jobs/me'),
  moderate: (id: string, b: Body) => post(`/alumni/jobs/${id}/moderate`, b),
  click: (id: string) => post(`/alumni/jobs/${id}/click`),
  lead: (id: string) => post(`/alumni/jobs/${id}/lead`),
  stats: (p: Params = {}) => get('/alumni/stats', p),
  // fundraising
  campaigns: (p: Params = {}) => get('/fundraising/campaigns', p),
  campaign: (id: string) => get(`/fundraising/campaigns/${id}`),
  createCampaign: (b: Body) => post('/fundraising/campaigns', b),
  updateCampaign: (id: string, b: Body) => put(`/fundraising/campaigns/${id}`, b),
  closeCampaign: (id: string) => post(`/fundraising/campaigns/${id}/close`),
  publicCampaigns: (institution: string) => get('/fundraising/campaigns/public', { institution }),
  donate: (b: Body) => post('/fundraising/donate', b, {}),
  donatePublic: (institution: string, b: Body) => post(`/fundraising/donate/public?institution=${encodeURIComponent(institution)}`, b, {}),
  myDonations: () => get('/fundraising/donations/me'),
  donations: (p: Params = {}) => get('/fundraising/donations', p),
  recordDonation: (b: Body) => post('/fundraising/donations', b),
  refund: (id: string, b: Body) => post(`/fundraising/donations/${id}/refund`, b),
  donor: (key: string) => get(`/fundraising/donors/${encodeURIComponent(key)}`),
  receipt: (id: string) => post(`/fundraising/donations/${id}/receipt-80g`),
  reissue: (id: string, b: Body) => post(`/fundraising/donations/${id}/receipt-80g/reissue`, b),
  register80g: (fy: string) => get('/fundraising/80g/register', { fy }),
  tenBd: (fy: string) => get('/fundraising/80g/10bd', { fy }),
};
