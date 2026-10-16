import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  AllocationSummary,
  Arrear,
  BulkPreview,
  Catalog,
  ChoiceForm,
  Offering,
  RegWindow,
  Registration,
  RegistrationListItem,
  RosterItem,
} from './types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;

const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const post = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const withParams = (params: Params) => ({ params, idempotent: false }) as AxiosRequestConfig;

export interface WorkloadWarning {
  name: string;
  total_hours: number;
  norm_hours: number;
}

/** Offerings, windows, registration cart / approvals, electives, arrears (Prompts/09 §09.8). */
export const registrationApi = {
  offerings: (params: Params = {}) => get<Offering[]>('/course-offerings', { params }),
  offering: (id: string) => get<Offering>(`/course-offerings/${id}`),
  myOfferings: (params: Params = {}) => get<Offering[]>('/course-offerings/mine', { params }),
  createOffering: (body: Body) => post<Offering>('/course-offerings', body, once),
  updateOffering: (id: string, body: Body) => put<Offering>(`/course-offerings/${id}`, body),
  offeringStatus: (id: string, status: string) => post<Offering>(`/course-offerings/${id}/status`, { status }, once),
  offeringFaculty: (id: string, items: Body[], allow_cross_department = false) =>
    put<{ offering: Offering; warnings: WorkloadWarning[] }>(`/course-offerings/${id}/faculty`, {
      items,
      allow_cross_department,
    }),
  bulk: (body: Body, dry_run: boolean) =>
    post<BulkPreview>('/course-offerings/bulk-from-curriculum', body, withParams({ dry_run })),
  roster: (id: string, include_waitlist = false) =>
    get<RosterItem[]>(`/course-offerings/${id}/roster`, { params: { include_waitlist } }),
  rosterExport: (id: string) => get<{ job_id: string }>(`/course-offerings/${id}/roster/export`),
  windows: (params: Params = {}) => get<RegWindow[]>('/registration-windows', { params }),
  createWindow: (body: Body) => post<RegWindow>('/registration-windows', body, once),
  windowStatus: (id: string, status: string) => post<RegWindow>(`/registration-windows/${id}/status`, { status }, once),
  catalog: (params: Params = {}) => get<Catalog>('/registration/me/catalog', { params }),
  mine: (params: Params = {}) => get<Registration | null>('/registration/me', { params }),
  myHistory: () => get<Registration[]>('/registration/me/history'),
  addItem: (body: Body) => post<Registration>('/registration/me/items', body, once),
  removeItem: (id: string) => del<Registration>(`/registration/me/items/${id}`),
  submit: (key: string) =>
    post<Registration>('/registration/me/submit', undefined, {
      headers: { 'Idempotency-Key': key },
      idempotent: false,
    } as AxiosRequestConfig),
  acceptWaitlist: (id: string) => post<Registration>(`/registration/me/waitlist/${id}/accept`, undefined, once),
  list: (params: Params = {}) => get<RegistrationListItem[]>('/registration', { params }),
  get: (id: string) => get<Registration>(`/registration/${id}`),
  decide: (id: string, action: 'approve' | 'reject' | 'request-changes', body: Body) =>
    post<Registration>(`/registration/${id}/${action}`, body, once),
  override: (id: string, body: Body) => post<Registration>(`/registration/${id}/override`, body, once),
  withdrawItem: (id: string, itemId: string, reason: string) =>
    post<Registration>(`/registration/${id}/withdraw-item/${itemId}`, { reason }, once),
  lock: (id: string, lock: boolean) => post<Registration>(`/registration/${id}/${lock ? 'lock' : 'unlock'}`, {}, once),
  bulkRegister: (body: Body) => post<{ job_id: string }>('/registration/bulk-register', body, once),
  saveChoices: (basketId: string, body: Body, replace: boolean) =>
    replace
      ? put<ChoiceForm>(`/elective-baskets/${basketId}/choices/me`, body)
      : post<ChoiceForm>(`/elective-baskets/${basketId}/choices/me`, body, once),
  basketForms: (basketId: string, term_id: string) =>
    get<ChoiceForm[]>(`/elective-baskets/${basketId}/choices`, { params: { term_id } }),
  allocate: (basketId: string, term_id: string, mode: string, dry_run: boolean) =>
    post<AllocationSummary & { job_id?: string }>(
      `/elective-baskets/${basketId}/allocate`,
      undefined,
      withParams({ term_id, mode, dry_run }),
    ),
  manual: (basketId: string, form_id: string, course_id: string) =>
    post<ChoiceForm>(`/elective-baskets/${basketId}/manual`, { form_id, course_id }, once),
  arrears: (params: Params = {}) => get<Arrear[]>('/arrears', { params }),
  waive: (id: string, reason: string) => post<Arrear>(`/arrears/${id}/waive`, { reason }, once),
};
