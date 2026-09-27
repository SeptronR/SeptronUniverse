import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  AcademicTerm,
  AcademicYear,
  College,
  Department,
  Faculty,
  Holiday,
  HolidayBulkResult,
  InstitutionProfile,
  NumberSequence,
  OnboardingPayload,
  OnboardingResult,
  PlatformInstitution,
  RolloverPayload,
  SettingsCategory,
} from './types';

const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const post = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;

type Params = Record<string, string | number | boolean | undefined | null>;

/** Institution structure, sessions, holidays, sequences, settings and onboarding (Prompts/03 §03.8). */
export const institutionApi = {
  // profile
  profile: () => get<InstitutionProfile>('/institution/profile'),
  updateProfile: (body: Record<string, unknown>) => put<InstitutionProfile>('/institution/profile', body),
  uploadLogo: (file: File, kind: 'logo' | 'seal' | 'signature' | 'letterhead' = 'logo') => {
    const form = new FormData();
    form.append('file', file);
    form.append('kind', kind);
    return post<{ logo_url: string; key: string }>('/institution/profile/logo', form, { idempotent: false });
  },
  // colleges
  colleges: (params: Params = {}) => get<College[]>('/colleges', { params }),
  createCollege: (body: Record<string, unknown>) => post<College>('/colleges', body),
  updateCollege: (id: string, body: Record<string, unknown>) => put<College>(`/colleges/${id}`, body),
  deleteCollege: (id: string) => del<null>(`/colleges/${id}`),
  // faculties + departments
  faculties: (params: Params = {}) => get<Faculty[]>('/faculties', { params }),
  createFaculty: (body: Record<string, unknown>) => post<Faculty>('/faculties', body, { idempotent: false }),
  updateFaculty: (id: string, body: Record<string, unknown>) => put<Faculty>(`/faculties/${id}`, body),
  departments: (params: Params = {}) => get<Department[]>('/departments', { params }),
  createDepartment: (body: Record<string, unknown>) => post<Department>('/departments', body),
  updateDepartment: (id: string, body: Record<string, unknown>) => put<Department>(`/departments/${id}`, body),
  deleteDepartment: (id: string) => del<null>(`/departments/${id}`),
  assignHod: (id: string, userId: string) => put<Department>(`/departments/${id}/hod`, { user_id: userId }),
  // academic years / terms
  years: (params: Params = {}) => get<AcademicYear[]>('/academic-years', { params }),
  createYear: (body: Record<string, unknown>) => post<AcademicYear>('/academic-years', body, { idempotent: false }),
  updateYear: (id: string, body: Record<string, unknown>) => put<AcademicYear>(`/academic-years/${id}`, body),
  setCurrentYear: (id: string) => post<AcademicYear>(`/academic-years/${id}/set-current`, undefined, { idempotent: false }),
  lockYear: (id: string, lock: boolean) =>
    post<AcademicYear>(`/academic-years/${id}/${lock ? 'lock' : 'unlock'}`, undefined, { idempotent: false }),
  rollover: (body: RolloverPayload) => post<{ year: AcademicYear; current_term_id: string }>('/academic-years/rollover', body),
  terms: (params: Params = {}) => get<AcademicTerm[]>('/academic-terms', { params }),
  term: (id: string) => get<AcademicTerm>(`/academic-terms/${id}`),
  currentTerm: (collegeId?: string | null) =>
    get<AcademicTerm | null>('/academic-terms/current', { params: { college_id: collegeId ?? undefined } }),
  createTerm: (body: Record<string, unknown>) => post<AcademicTerm>('/academic-terms', body, { idempotent: false }),
  updateTerm: (id: string, body: Record<string, unknown>) => put<AcademicTerm>(`/academic-terms/${id}`, body),
  changeTermStatus: (id: string, status: string) =>
    post<AcademicTerm>(`/academic-terms/${id}/status`, { status }, { idempotent: false }),
  setCurrentTerm: (id: string) => post<AcademicTerm>(`/academic-terms/${id}/set-current`, undefined, { idempotent: false }),
  // holidays
  holidays: (params: Params = {}) => get<Holiday[]>('/holidays', { params }),
  createHoliday: (body: Record<string, unknown>) => post<Holiday>('/holidays', body, { idempotent: false }),
  deleteHoliday: (id: string) => del<null>(`/holidays/${id}`),
  importHolidays: (csv: string) => post<HolidayBulkResult>('/holidays/bulk-import', { csv }),
  holidaysIcs: (params: Params = {}) => api.get('/holidays/export.ics', { params, responseType: 'blob' }),
  // number sequences
  sequences: (params: Params = {}) => get<NumberSequence[]>('/number-sequences', { params }),
  createSequence: (body: Record<string, unknown>) => post<NumberSequence>('/number-sequences', body, { idempotent: false }),
  updateSequence: (id: string, body: Record<string, unknown>) => put<NumberSequence>(`/number-sequences/${id}`, body),
  previewSequence: (id: string, body: Record<string, unknown> = {}) =>
    post<{ values: string[]; tokens: Record<string, string> }>(`/number-sequences/${id}/preview`, body, { idempotent: false }),
  // settings
  settings: (category?: string) => get<SettingsCategory[]>('/settings', { params: { category } }),
  updateSettings: (items: { category: string; key: string; value: unknown }[]) =>
    put<SettingsCategory[]>('/settings', { items }),
  testProvider: (channel: string, to: string) =>
    post<{ provider: string; status: string; reference: string | null }>('/settings/test-provider', { channel, to }, { idempotent: false }),
  // platform (super admin)
  platformInstitutions: (params: Params = {}) => get<PlatformInstitution[]>('/platform/institutions', { params }),
  platformInstitution: (id: string) => get<PlatformInstitution>(`/platform/institutions/${id}`),
  onboard: (body: OnboardingPayload) => post<OnboardingResult>('/platform/institutions', body),
  suspend: (id: string, reason?: string) =>
    post<PlatformInstitution>(`/platform/institutions/${id}/suspend`, { reason }, { idempotent: false }),
  activate: (id: string) => post<PlatformInstitution>(`/platform/institutions/${id}/activate`, undefined, { idempotent: false }),
};
