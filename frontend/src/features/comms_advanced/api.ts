import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T = Any>(url: string, body?: unknown) => api.post(url, body ?? {}, once) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T = Any>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;
const blob = (url: string, params?: Params) => api.get(url, { responseType: 'blob', params }) as unknown as Promise<Blob>;

/** Communication advanced (Prompts/24 §24.8). */
export const commsApi = {
  // segments
  fields: () => get('/comms/segments/fields'),
  preview: (rules: Body) => post('/comms/segments/preview', rules),
  segments: () => get('/comms/segments'),
  saveSegment: (b: Body, id?: string) => (id ? put(`/comms/segments/${id}`, b) : post('/comms/segments', b)),
  deleteSegment: (id: string) => del(`/comms/segments/${id}`),
  // campaigns
  campaigns: (p: Params = {}) => get('/comms/campaigns', { params: p }),
  campaign: (id: string) => get(`/comms/campaigns/${id}`),
  createCampaign: (b: Body) => post('/comms/campaigns', b),
  updateCampaign: (id: string, b: Body) => put(`/comms/campaigns/${id}`, b),
  compliance: (id: string) => post(`/comms/campaigns/${id}/compliance-check`),
  action: (id: string, b: Body) => post(`/comms/campaigns/${id}/action`, b),
  report: (id: string) => get(`/comms/campaigns/${id}/report`),
  recipients: (id: string, p: Params = {}) => get(`/comms/campaigns/${id}/recipients`, { params: p }),
  // announcements
  announcementAnalytics: (id: string) => get(`/comms/announcements/${id}/analytics`),
  remind: (id: string, channels: string[]) => post(`/comms/announcements/${id}/remind`, { channels }),
  // emergency
  broadcast: (b: Body) => post('/comms/emergency/broadcast', b),
  allClear: (id: string, message: string) => post(`/comms/emergency/${id}/all-clear`, { message }),
  emergencyLog: () => get('/comms/emergency/log'),
  // bot
  flows: () => get('/comms/bot/flows'),
  saveFlows: (b: Body) => put('/comms/bot/flows', b),
  sessions: (p: Params = {}) => get('/comms/bot/sessions', { params: p }),
  session: (id: string) => get(`/comms/bot/sessions/${id}`),
  closeHandoff: (id: string) => post(`/comms/bot/sessions/${id}/handoff-close`),
  // assistant
  assistantMe: () => get('/assistant/me'),
  optIn: (accepted: boolean) => post('/assistant/opt-in', { accepted }),
  chat: (b: Body) => post('/assistant/chat', b),
  conversations: () => get('/assistant/conversations'),
  conversation: (id: string) => get(`/assistant/conversations/${id}`),
  assistantUsage: () => get('/assistant/admin/usage'),
  // simulator
  inbox: () => get('/comms/simulator/inbox'),
  clearInbox: () => del('/comms/simulator/inbox'),
  inboundWhatsapp: (b: Body) => post('/comms/simulator/inbound-whatsapp', b),
  // analytics
  delivery: (p: Params = {}) => get('/comms/analytics/delivery', { params: p }),
  providers: () => get('/comms/analytics/providers'),
  exportDelivery: (p: Params = {}) => blob('/comms/analytics/export', p),
  myMessages: (p: Params = {}) => get('/comms/me/messages', { params: p }),
};
