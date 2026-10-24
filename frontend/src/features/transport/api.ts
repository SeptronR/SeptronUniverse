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
const post = <T = Any>(url: string, body?: unknown, config: AxiosRequestConfig = once) => api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T = Any>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;
const blob = (url: string, params?: Params) => api.get(url, { responseType: 'blob', params }) as unknown as Promise<Blob>;

/** Transport (Prompts/21 §21.8). */
export const transportApi = {
  colleges: () => get('/colleges', { params: { page_size: 100 } }),
  // fleet
  vehicles: (p: Params = {}) => get('/transport/vehicles', { params: p }),
  compliance: () => get('/transport/vehicles/compliance'),
  saveVehicle: (b: Body, id?: string) => (id ? put(`/transport/vehicles/${id}`, b) : post('/transport/vehicles', b)),
  retireVehicle: (id: string) => post(`/transport/vehicles/${id}/retire`),
  maintenance: (id: string) => get(`/transport/vehicles/${id}/maintenance`),
  addMaintenance: (id: string, b: Body) => post(`/transport/vehicles/${id}/maintenance`, b),
  fuel: (id: string) => get(`/transport/vehicles/${id}/fuel`),
  addFuel: (id: string, b: Body) => post(`/transport/vehicles/${id}/fuel`, b),
  costs: (id: string) => get(`/transport/vehicles/${id}/costs`),
  // routes
  routes: (p: Params = {}) => get('/transport/routes', { params: p }),
  publicRoutes: () => get('/transport/routes/public'),
  saveRoute: (b: Body, id?: string) => (id ? put(`/transport/routes/${id}`, b) : post('/transport/routes', b)),
  deleteRoute: (id: string) => del(`/transport/routes/${id}`),
  addStop: (id: string, b: Body) => post(`/transport/routes/${id}/stops`, b),
  updateStop: (id: string, b: Body) => put(`/transport/stops/${id}`, b),
  reorder: (id: string, stop_ids: string[]) => post(`/transport/routes/${id}/stops/reorder`, { stop_ids }),
  routeSheet: (id: string) => blob(`/transport/routes/${id}/sheet.pdf`),
  // allocations
  allocations: (p: Params = {}) => get('/transport/allocations', { params: p }),
  allocate: (b: Body) => post('/transport/allocations', b),
  bulk: (b: Body) => post('/transport/allocations/bulk', b),
  change: (id: string, b: Body) => post(`/transport/allocations/${id}/change`, b),
  setStatus: (id: string, action: 'suspend' | 'close' | 'reactivate', reason?: string) => post(`/transport/allocations/${id}/${action}`, { reason }),
  requests: (status = 'pending') => get('/transport/requests', { params: { status } }),
  decide: (id: string, b: Body) => post(`/transport/requests/${id}/decide`, b),
  me: () => get('/transport/me'),
  wards: () => get('/transport/wards'),
  request: (b: Body) => post('/transport/me/request', b),
  myRequests: () => get('/transport/me/requests'),
  // trips
  trips: (p: Params = {}) => get('/transport/trips', { params: p }),
  trip: (id: string) => get(`/transport/trips/${id}`),
  schedule: (b: Body) => post('/transport/trips/schedule', b),
  adhoc: (b: Body) => post('/transport/trips', b),
  cancel: (id: string, reason: string) => post(`/transport/trips/${id}/cancel`, { reason }),
  driverTrips: (date?: string) => get('/transport/driver/trips', { params: { date } }),
  start: (id: string, b: Body) => post(`/transport/trips/${id}/start`, b),
  end: (id: string, b: Body) => post(`/transport/trips/${id}/end`, b),
  stopEvent: (id: string, b: Body) => post(`/transport/trips/${id}/stop-event`, b),
  manifest: (id: string) => get(`/transport/trips/${id}/manifest`),
  scan: (id: string, b: Body) => post(`/transport/trips/${id}/passenger-scan`, b, idem),
  // GPS
  live: (p: Params = {}) => get('/transport/live', { params: p }),
  trace: (id: string) => get(`/transport/trips/${id}/trace`),
  gpx: (id: string) => blob(`/transport/trips/${id}/trace`, { format: 'gpx' }),
  ping: (b: Body) => post('/transport/gps/ingest', b),
  devices: () => get('/transport/gps-devices'),
  addDevice: (b: Body) => post('/transport/gps-devices', b),
  rotate: (id: string) => post(`/transport/gps-devices/${id}/rotate-token`),
  removeDevice: (id: string) => del(`/transport/gps-devices/${id}`),
  // reports
  stats: () => get('/transport/stats'),
  report: (kind: string) => get(`/transport/reports/${kind}`),
  exportReport: (kind: string) => get(`/transport/reports/${kind}`, { params: { format: 'xlsx' } }),
};
