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
const blob = (url: string, body?: unknown) => api.post(url, body ?? {}, { responseType: 'blob' }) as unknown as Promise<Blob>;

/** Document templates, issued register, bulk, serial registers, certificate requests (Prompts/26 §26.8). */
export const docApi = {
  // templates
  templates: (p: Params = {}) => get('/documents/templates', p),
  template: (id: string) => get(`/documents/templates/${id}`),
  createTemplate: (b: Body) => post('/documents/templates', b),
  updateTemplate: (id: string, b: Body) => put(`/documents/templates/${id}`, b),
  publish: (id: string, change_note: string) => post(`/documents/templates/${id}/publish`, { change_note }),
  versions: (id: string) => get(`/documents/templates/${id}/versions`),
  lint: (id: string) => get(`/documents/templates/${id}/lint`),
  usage: (id: string) => get(`/documents/templates/${id}/usage`),
  variables: (t: string) => get(`/documents/templates/variables/${t}`),
  preview: (id: string, b: Body = {}) => blob(`/documents/templates/${id}/preview`, b),
  // issued register
  issued: (p: Params = {}) => get('/documents/issued', p),
  document: (id: string) => get(`/documents/issued/${id}`),
  revoke: (id: string, reason: string) => post(`/documents/issued/${id}/revoke`, { reason }),
  reissue: (id: string, reason: string) => post(`/documents/issued/${id}/reissue`, { reason }),
  signedLink: (id: string, b: Body = {}) => post(`/documents/issued/${id}/signed-link`, b),
  mine: () => get('/documents/me'),
  wards: () => get('/documents/wards'),
  render: (b: Body) => post('/documents/render', b),
  stats: () => get('/documents/stats'),
  settings: () => get('/documents/settings'),
  // bulk
  bulk: (b: Body) => post('/documents/bulk', b),
  bulkJob: (id: string) => get(`/documents/bulk/${id}`),
  // serial registers
  registers: () => get('/documents/registers'),
  register: (r: string, p: Params = {}) => get(`/documents/registers/${r}`, p),
  reserve: (r: string, count: number) => post(`/documents/registers/${r}/reserve`, { count }),
  voidSerial: (r: string, serial_no: string, reason: string) => post(`/documents/registers/${r}/void`, { serial_no, reason }),
  reconcile: (r: string) => get(`/documents/registers/${r}/reconcile`),
  exportRegister: (r: string) => get(`/documents/registers/${r}/export`),
  // certificate requests
  requestTypes: () => get('/certificate-requests/types'),
  createRequest: (b: Body) => post('/certificate-requests', b),
  myRequests: () => get('/certificate-requests/me'),
  wardRequests: () => get('/certificate-requests/wards'),
  cancelRequest: (id: string) => del(`/certificate-requests/${id}`),
  requests: (p: Params = {}) => get('/certificate-requests', p),
  request: (id: string) => get(`/certificate-requests/${id}`),
  decide: (id: string, action: string, remarks?: string) => post(`/certificate-requests/${id}/decide`, { action, remarks }),
  generate: (id: string) => post(`/certificate-requests/${id}/generate`, {}),
  issue: (id: string, b: Body = {}) => post(`/certificate-requests/${id}/issue`, b),
  collected: (id: string, collected_by: string) => post(`/certificate-requests/${id}/collected`, { collected_by }),
  // public verification
  verify: (token: string) => get(`/verify/${token}`),
  verifyHash: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return api.post('/verify/hash', fd) as unknown as Promise<Envelope<Any>>;
  },
};
