import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  AdmitResult,
  Allotment,
  AllotmentSummary,
  Applicant,
  ApplicantListItem,
  Cycle,
  CycleProgram,
  Enquiry,
  EnquiryStats,
  ImportResult,
  MeritList,
  MeritListDetail,
  Offer,
  Payment,
  PublicCycle,
  Round,
  SeatStatus,
  TimelineEntry,
} from './types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;

const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const post = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false };
const upload = <T>(url: string, file: File, fields: Record<string, string | undefined> = {}, params: Params = {}) => {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([k, v]) => v !== undefined && v !== '' && form.append(k, v));
  return api.post(url, form, { params, idempotent: false } as AxiosRequestConfig) as unknown as Promise<Envelope<T>>;
};
const pub = (institution: string) => ({ params: { institution } });

/** Admissions: cycles, seat matrix, applicants, merit, counselling, offers, enquiries, applicant portal (Prompts/08 §08.8). */
export const admissionsApi = {
  // cycles
  cycles: (params: Params = {}) => get<Cycle[]>('/admissions/cycles', { params }),
  cycle: (id: string) => get<Cycle>(`/admissions/cycles/${id}`),
  createCycle: (body: Body) => post<Cycle>('/admissions/cycles', body, once),
  updateCycle: (id: string, body: Body) => put<Cycle>(`/admissions/cycles/${id}`, body),
  cycleStatus: (id: string, status: string, reason?: string) => post<Cycle>(`/admissions/cycles/${id}/status`, { status, reason }, once),
  programs: (id: string) => get<CycleProgram[]>(`/admissions/cycles/${id}/programs`),
  savePrograms: (id: string, programs: Body[]) => put<CycleProgram[]>(`/admissions/cycles/${id}/programs`, { programs }),
  seatStatus: (id: string) => get<SeatStatus>(`/admissions/cycles/${id}/seat-status`),
  saveSeatMatrix: (id: string, rows: Body[]) => put<SeatStatus>(`/admissions/cycles/${id}/seat-matrix`, { rows }),
  // applicants
  applicants: (params: Params = {}) => get<ApplicantListItem[]>('/admissions/applicants', { params }),
  applicant: (id: string) => get<Applicant>(`/admissions/applicants/${id}`),
  updateApplicant: (id: string, body: Body) => put<Applicant>(`/admissions/applicants/${id}`, body),
  timeline: (id: string) => get<TimelineEntry[]>(`/admissions/applicants/${id}/timeline`),
  verifyDocument: (id: string, docType: string, body: Body) =>
    post<Applicant>(`/admissions/applicants/${id}/documents/${docType}/verify`, body, once),
  verificationQueue: (params: Params = {}) => get<Applicant[]>('/admissions/verification-queue', { params }),
  changeStatus: (id: string, status: string, reason: string) =>
    post<Applicant>(`/admissions/applicants/${id}/status`, { status, reason }, once),
  withdraw: (id: string, reason: string) => post<{ applicant: Applicant }>(`/admissions/applicants/${id}/withdraw`, { reason }, once),
  offer: (id: string, body: Body) => post<Offer>(`/admissions/applicants/${id}/offer`, body, once),
  offers: (params: Params = {}) => get<Offer[]>('/admissions/offers', { params }),
  admit: (id: string, body: Body) => post<AdmitResult>(`/admissions/applicants/${id}/admit`, body),
  importCsv: (cycleId: string, file: File, dryRun: boolean, mapping?: string) =>
    upload<ImportResult>('/admissions/applicants/import', file, { cycle_id: cycleId, mapping }, { dry_run: dryRun }),
  exportXlsx: (params: Params = {}) => get<{ job_id: string }>('/admissions/applicants/export', { params }),
  // merit
  generateMerit: (cycleId: string, body: Body) => post<MeritList>(`/admissions/cycles/${cycleId}/merit-lists`, body, once),
  meritLists: (params: Params = {}) => get<MeritList[]>('/admissions/merit-lists', { params }),
  meritList: (id: string) => get<MeritListDetail>(`/admissions/merit-lists/${id}`),
  publishMerit: (id: string) => post<MeritList>(`/admissions/merit-lists/${id}/publish`, undefined, once),
  // counselling
  rounds: (cycleId: string) => get<Round[]>(`/admissions/cycles/${cycleId}/rounds`),
  createRound: (cycleId: string, body: Body) => post<Round>(`/admissions/cycles/${cycleId}/rounds`, body, once),
  updateRound: (id: string, body: Body) => put<Round>(`/admissions/rounds/${id}`, body),
  roundStatus: (id: string, status: string) => post<Round>(`/admissions/rounds/${id}/status`, { status }, once),
  runAllotment: (id: string, dryRun: boolean) =>
    post<AllotmentSummary>(`/admissions/rounds/${id}/run-allotment`, undefined, { params: { dry_run: dryRun }, idempotent: false } as AxiosRequestConfig),
  allotments: (id: string) => get<Allotment[]>(`/admissions/rounds/${id}/allotments`),
  roundSummary: (id: string) => get<AllotmentSummary>(`/admissions/rounds/${id}/summary`),
  // enquiries
  enquiries: (params: Params = {}) => get<Enquiry[]>('/admissions/enquiries', { params }),
  enquiryStats: () => get<EnquiryStats>('/admissions/enquiries/stats'),
  createEnquiry: (body: Body) => post<Enquiry>('/admissions/enquiries', body, once),
  updateEnquiry: (id: string, body: Body) => put<Enquiry>(`/admissions/enquiries/${id}`, body),
  assignEnquiry: (id: string, user_id: string) => post<Enquiry>(`/admissions/enquiries/${id}/assign`, { user_id }, once),
  convertEnquiry: (id: string, body: Body) => post<Enquiry>(`/admissions/enquiries/${id}/convert`, body, once),
  // applicant portal
  me: () => get<Applicant>('/applicants/me'),
  updateMe: (body: Body) => put<Applicant>('/applicants/me', body),
  myPreferences: (preferences: Body[]) => put<Applicant>('/applicants/me/preferences', { preferences }),
  myChoices: (preferences: Body[]) => put<Applicant>('/applicants/me/choices', { preferences }),
  myEligibility: () => get<{ priority: number; program_code: string; eligible: boolean; reasons: string[] }[]>('/applicants/me/eligibility'),
  myDocument: (docType: string, file: File) => upload<Applicant>('/applicants/me/documents', file, { doc_type: docType }),
  submit: () => post<Applicant>('/applicants/me/submit', undefined, once),
  pay: (purpose: 'application' | 'admission') =>
    post<Payment>('/applicants/me/pay', undefined, { params: { purpose }, idempotent: false } as AxiosRequestConfig),
  myTimeline: () => get<TimelineEntry[]>('/applicants/me/timeline'),
  myAllotment: () => get<Allotment | null>('/applicants/me/allotment'),
  decide: (id: string, action: string) => post<Allotment>(`/applicants/me/allotment/${id}/decision`, { action }, once),
  withdrawMe: (reason: string) => post<{ applicant: Applicant; refund: Payment | null }>('/applicants/me/withdraw', { reason }, once),
  // public
  publicCycles: (institution: string) => get<{ name: string; slug: string; level: string; status: string; closes_at: string | null; application_fee_paise: number }[]>('/public/admissions/cycles', pub(institution)),
  publicCycle: (institution: string, slug: string) => get<PublicCycle>(`/public/admissions/cycles/${slug}`, pub(institution)),
  start: (institution: string, slug: string, body: Body) =>
    post<{ otp_sent: boolean; dev_otp: string | null; application_number: string | null; username: string | null }>(
      `/public/admissions/${slug}/start`,
      body,
      { ...pub(institution), idempotent: false } as AxiosRequestConfig,
    ),
  publicMerit: (institution: string, slug: string, id: string) =>
    get<{ name: string; cycle: string; published_at: string | null; entries: { rank: number; application_number: string }[] }>(
      `/public/admissions/${slug}/merit-lists/${id}`,
      pub(institution),
    ),
};
