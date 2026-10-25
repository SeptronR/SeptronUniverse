import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, params?: Params) => api.get(url, { params }) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T = Any>(url: string, body?: unknown) => api.post(url, body ?? {}, once) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T = Any>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;

/** Calendar, events & facilities (Prompts/25 §25.8). */
export const facApi = {
  // calendar
  calendar: (p: Params = {}) => get('/calendar', p),
  calendarEntries: () => get('/calendar/events'),
  saveEntry: (b: Body, id?: string) => (id ? put(`/calendar/events/${id}`, b) : post('/calendar/events', b)),
  deleteEntry: (id: string) => del(`/calendar/events/${id}`),
  calendarPdf: () => get('/calendar/pdf'),
  feedToken: () => post('/calendar/feed-token'),
  revokeFeed: () => del('/calendar/feed-token'),
  // events
  events: (p: Params = {}) => get('/events', p),
  event: (id: string) => get(`/events/${id}`),
  createEvent: (b: Body) => post('/events', b),
  eventAction: (id: string, action: string) => post(`/events/${id}/action`, { action }),
  register: (id: string) => post(`/events/${id}/register`, { person_type: 'student' }),
  registrations: (id: string) => get(`/events/${id}/registrations`),
  attendance: (id: string, b: Body) => post(`/events/${id}/attendance`, b),
  certificates: (id: string) => post(`/events/${id}/certificates`, { only_attended: true }),
  report: (id: string) => get(`/events/${id}/report`),
  myEvents: () => get('/events/me'),
  // bookings
  availability: (p: Params) => get('/facilities/rooms/availability', p),
  bookings: (p: Params = {}) => get('/facilities/room-bookings', p),
  book: (b: Body) => post('/facilities/room-bookings', b),
  decide: (id: string, action: string) => post(`/facilities/room-bookings/${id}/decide`, { action }),
  cancelBooking: (id: string) => post(`/facilities/room-bookings/${id}/cancel`),
  equipment: () => get('/facilities/equipment-bookings'),
  eqAct: (id: string, act: string, b: Body = {}) => post(`/facilities/equipment-bookings/${id}/${act}`, b),
  // service desk
  tickets: (p: Params = {}) => get('/facilities/service-requests', p),
  raise: (b: Body) => post('/facilities/service-requests', b),
  ticketAct: (id: string, act: string, b: Body = {}) => post(`/facilities/service-requests/${id}/${act}`, b),
  dashboard: () => get('/facilities/service-desk/dashboard'),
  amc: () => get('/facilities/amc-contracts'),
  lostFound: () => get('/facilities/lost-found'),
  reportLost: (b: Body) => post('/facilities/lost-found', b),
  // security
  visitors: (p: Params = {}) => get('/facilities/visitor-passes', p),
  issuePass: (b: Body) => post('/facilities/visitor-passes', b),
  scan: (b: Body) => post('/facilities/visitor-passes/scan', b),
  inside: () => get('/facilities/visitor-passes/inside'),
  alerts: () => get('/emergency/alerts'),
  alertAct: (id: string, act: string, b: Body = {}) => post(`/emergency/alerts/${id}/${act}`, b),
  // wellness
  healthStats: () => get('/health/stats'),
  healthVisits: () => get('/health/visits'),
  myVisits: () => get('/health/visits/me'),
  slots: () => get('/counselling/slots/available'),
  bookSlot: (id: string) => post(`/counselling/slots/${id}/book`, {}),
  myAppointments: () => get('/counselling/appointments/me'),
  utilisation: () => get('/counselling/utilisation'),
  // sports / wallet
  teams: () => get('/sports/teams'),
  sportsEvents: () => get('/sports/events'),
  participation: () => get('/sports/participation'),
  verify: (id: string) => post(`/sports/participation/${id}/verify`),
  wallet: () => get('/wallet/me'),
  topup: (amount_paise: number) => post('/wallet/topup', { amount_paise }),
  debit: (b: Body) => post('/wallet/debit', b),
  canteens: () => get('/canteens'),
  settlement: (p: Params = {}) => get('/wallet/settlement', p),
};
