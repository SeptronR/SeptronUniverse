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

/** Library (Prompts/19 §19.8). */
export const libraryApi = {
  stats: () => get('/library/stats'),
  categories: () => get('/library/categories'),
  saveCategory: (b: Body, id?: string) => (id ? put(`/library/categories/${id}`, b) : post('/library/categories', b)),
  books: (p: Params = {}) => get('/library/books', { params: p }),
  book: (id: string) => get(`/library/books/${id}`),
  createBook: (b: Body) => post('/library/books', b),
  updateBook: (id: string, b: Body) => put(`/library/books/${id}`, b),
  deleteBook: (id: string) => del(`/library/books/${id}`),
  importBooks: (b: Body) => post('/library/books/import', b),
  copies: (id: string) => get(`/library/books/${id}/copies`),
  addCopies: (id: string, b: Body) => post(`/library/books/${id}/copies/bulk`, b),
  copyStatus: (id: string, b: Body) => put(`/library/copies/${id}/status`, b),
  resolve: (p: Params) => get('/library/copies/resolve', { params: p }),
  // members
  members: (p: Params = {}) => get('/library/members', { params: p }),
  member: (id: string) => get(`/library/members/${id}`),
  me: () => get('/library/members/me'),
  myIssues: () => get('/library/members/me/issues'),
  myFines: () => get('/library/members/me/fines'),
  wards: () => get('/library/members/wards'),
  createMember: (b: Body) => post('/library/members', b),
  memberRules: (id: string, b: Body) => put(`/library/members/${id}/rules`, b),
  suspend: (id: string) => post(`/library/members/${id}/suspend`),
  activate: (id: string) => post(`/library/members/${id}/activate`),
  // circulation
  issue: (b: Body) => post('/library/circulation/issue', b, idem),
  return: (b: Body) => post('/library/circulation/return', b, idem),
  renew: (issue_id: string) => post('/library/circulation/renew', { issue_id }, idem),
  lost: (b: Body) => post('/library/circulation/lost', b, idem),
  selfRenew: (issue_id: string) => post('/library/circulation/self-renew', { issue_id }),
  issues: (p: Params = {}) => get('/library/issues', { params: p }),
  // reservations
  reservations: (p: Params = {}) => get('/library/reservations', { params: p }),
  reserve: (b: Body) => post('/library/reservations', b),
  cancelReservation: (id: string) => del(`/library/reservations/${id}`),
  // fines
  fines: (p: Params = {}) => get('/library/fines', { params: p }),
  waive: (issue_id: string, reason: string) => post(`/library/fines/${issue_id}/waive`, { reason }),
  // e-resources
  eresources: () => get('/library/eresources'),
  saveEresource: (b: Body, id?: string) => (id ? put(`/library/eresources/${id}`, b) : post('/library/eresources', b)),
  // ILL
  ill: () => get('/library/ill-requests'),
  requestIll: (b: Body) => post('/library/ill-requests', b),
  illAction: (id: string, action: 'decide' | 'receive' | 'return', b: Body = {}) => post(`/library/ill-requests/${id}/${action}`, b),
  // ops
  stockVerification: (b: Body) => post('/library/stock-verification', b),
  stockResult: (jobId: string) => get(`/library/stock-verification/${jobId}`),
  sync: (b: Body) => post('/library/sync/koha', b),
  syncStatus: () => get('/library/sync/status'),
  report: (kind: string) => get(`/library/reports/${kind}`),
  // public OPAC
  opac: (p: Params) => get('/opac/search', { params: p }),
  newArrivals: (institution: string) => get('/opac/new-arrivals', { params: { institution } }),
};
