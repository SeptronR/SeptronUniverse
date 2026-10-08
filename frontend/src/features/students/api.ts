import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  BulkImportResult,
  CreditTransfer,
  Enrollment,
  Guardian,
  Hold,
  IdCard,
  PromotionPreview,
  Standing,
  StudentCreateResult,
  StudentDashboard,
  StudentDetail,
  StudentDocument,
  StudentListItem,
  StudentStats,
  TermRecord,
  Transfer,
  UndertakingStatus,
  VerifyResult,
  WardSummary,
} from './types';

const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const post = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false };
const blob = (url: string, params: Params = {}) => api.get(url, { params, responseType: 'blob' }) as unknown as Promise<Blob>;
const upload = <T>(url: string, file: File, fields: Record<string, string | undefined> = {}, params: Params = {}) => {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([k, v]) => v !== undefined && v !== '' && form.append(k, v));
  return api.post(url, form, { params, idempotent: false } as AxiosRequestConfig) as unknown as Promise<Envelope<T>>;
};

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;

/** Students, enrolment, holds, standing, transfers, credit transfers, portals (Prompts/07 §07.8). */
export const studentsApi = {
  // master
  list: (params: Params = {}) => get<StudentListItem[]>('/students', { params }),
  one: (id: string) => get<StudentDetail>(`/students/${id}`),
  create: (body: Body) => post<StudentCreateResult>('/students', body, once),
  update: (id: string, body: Body) => put<StudentDetail>(`/students/${id}`, body),
  changeStatus: (id: string, body: Body) => post<StudentDetail>(`/students/${id}/status`, body, once),
  photo: (id: string, file: File) => upload<StudentDetail>(`/students/${id}/photo`, file),
  stats: () => get<StudentStats>('/students/stats'),
  exportXlsx: (params: Params = {}) => blob('/students/export', params),
  importTemplate: () => blob('/students/import-template'),
  bulkImport: (file: File, dryRun: boolean) =>
    upload<BulkImportResult>('/students/bulk-import', file, {}, { dry_run: dryRun || undefined }),
  idCards: (student_ids: string[]) => post<{ job_id: string }>('/students/id-cards', { student_ids }, once),
  idCard: (id: string) => get<IdCard>(`/students/${id}/id-card`),
  idCardPdf: (id: string) => blob(`/students/${id}/id-card.pdf`),
  // guardians
  guardians: (id: string) => get<Guardian[]>(`/students/${id}/guardians`),
  addGuardian: (id: string, body: Body) => post<Guardian>(`/students/${id}/guardians`, body, once),
  updateGuardian: (id: string, gid: string, body: Body) => put<Guardian>(`/students/${id}/guardians/${gid}`, body),
  removeGuardian: (id: string, gid: string) => del<null>(`/students/${id}/guardians/${gid}`),
  guardianConsent: (id: string, consent: boolean) =>
    put<StudentDetail>(`/students/${id}/guardian-consent`, { guardian_portal_consent: consent }),
  // documents
  documents: (id: string) => get<StudentDocument[]>(`/students/${id}/documents`),
  addDocument: (id: string, file: File, fields: { doc_type: string; expires_on?: string; remarks?: string }) =>
    upload<StudentDocument>(`/students/${id}/documents`, file, fields),
  verifyDocument: (docId: string, remarks?: string) => post<StudentDocument>(`/documents/${docId}/verify`, { remarks }, once),
  deleteDocument: (docId: string) => del<null>(`/documents/${docId}`),
  // enrolment
  enrollments: (id: string) => get<Enrollment[]>(`/students/${id}/enrollments`),
  termRecords: (enrollmentId: string) => get<TermRecord[]>(`/enrollments/${enrollmentId}/term-records`),
  changeSection: (enrollmentId: string, body: Body) => post<Enrollment>(`/enrollments/${enrollmentId}/section`, body, once),
  exit: (enrollmentId: string, body: Body) => post<Enrollment>(`/enrollments/${enrollmentId}/exit`, body, once),
  promote: (batchId: string, dryRun: boolean, body: Body = {}) =>
    post<PromotionPreview>(`/batches/${batchId}/promote`, { ...body, dry_run: dryRun }, once),
  standing: (id: string) => get<Standing>(`/students/${id}/standing`),
  // holds
  holdsQueue: (params: Params = {}) => get<Hold[]>('/student-holds', { params }),
  holds: (id: string) => get<Hold[]>(`/students/${id}/holds`),
  placeHold: (id: string, body: Body) => post<Hold>(`/students/${id}/holds`, body, once),
  releaseHold: (holdId: string, reason: string) => post<Hold>(`/student-holds/${holdId}/release`, { reason }, once),
  // transfers
  transfersQueue: (params: Params = {}) => get<Transfer[]>('/student-transfers', { params }),
  transfers: (id: string) => get<Transfer[]>(`/students/${id}/transfers`),
  requestTransfer: (id: string, body: Body) => post<Transfer>(`/students/${id}/transfers`, body, once),
  transferAction: (tid: string, action: 'approve' | 'reject' | 'complete', body: Body = {}) =>
    post<Transfer>(`/student-transfers/${tid}/${action}`, body, once),
  // credit transfers
  creditTransfers: (params: Params = {}) => get<CreditTransfer[]>('/credit-transfers', { params }),
  myCreditTransfers: () => get<CreditTransfer[]>('/credit-transfers/me'),
  studentCreditTransfers: (id: string) => get<CreditTransfer[]>(`/students/${id}/credit-transfers`),
  submitCreditTransfer: (body: Body) => post<CreditTransfer>('/credit-transfers', body, once),
  attachCertificate: (ctId: string, file: File) => upload<CreditTransfer>(`/credit-transfers/${ctId}/certificate`, file),
  creditTransferAction: (ctId: string, action: 'verify' | 'approve' | 'reject', body: Body = {}) =>
    post<CreditTransfer>(`/credit-transfers/${ctId}/${action}`, body, once),
  // portals
  me: () => get<StudentDetail>('/students/me'),
  updateMe: (body: Body) => put<StudentDetail>('/students/me', body),
  dashboard: () => get<StudentDashboard>('/students/me/dashboard'),
  pendingUndertakings: () => get<UndertakingStatus[]>('/students/me/undertakings/pending'),
  acceptUndertaking: (body: Body) => post<unknown>('/students/me/undertakings', body, once),
  myIdCard: () => get<IdCard>('/students/me/id-card'),
  myIdCardPdf: () => blob('/students/me/id-card.pdf'),
  wards: () => get<WardSummary[]>('/guardians/me/wards'),
  wardDashboard: (studentId: string) => get<StudentDashboard>(`/guardians/me/wards/${studentId}/dashboard`),
  // public
  verify: (token: string) => get<VerifyResult>(`/verify/${encodeURIComponent(token)}`),
};
