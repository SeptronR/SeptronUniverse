import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  AllocationProposal,
  Application,
  Appraisal,
  Attendance,
  AttendanceSummary,
  CasApplication,
  Designation,
  Device,
  FacultyProfile,
  Form16,
  Leave,
  LeaveBalance,
  LeaveCalendarItem,
  LeaveType,
  Loan,
  Panel,
  Payroll,
  PayrollComponent,
  PbasSchema,
  Posting,
  PublicPosting,
  Qualification,
  Register,
  SalaryStructure,
  ServiceBookEntry,
  Staff,
  StaffDetail,
  StaffDocument,
  Workload,
} from './types';

const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const post = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false };
const blob = (url: string, params: Params = {}) => api.get(url, { params, responseType: 'blob' }) as unknown as Promise<Blob>;

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;

/** Staff, leaves, staff attendance, payroll, loans, recruitment, appraisal/CAS, workload (Prompts/06 §06.8). */
export const hrApi = {
  // staff
  designations: () => get<Designation[]>('/designations'),
  staff: (params: Params = {}) => get<Staff[]>('/staff', { params }),
  staffOne: (id: string) => get<StaffDetail>(`/staff/${id}`),
  me: () => get<StaffDetail>('/staff/me'),
  updateMe: (body: Body) => put<StaffDetail>('/staff/me', body),
  createStaff: (body: Body) => post<{ staff: StaffDetail; username: string | null; temp_password: string | null }>('/staff', body),
  updateStaff: (id: string, body: Body) => put<StaffDetail>(`/staff/${id}`, body),
  exitStaff: (id: string, body: Body) => post<StaffDetail>(`/staff/${id}/exit`, body, once),
  exportStaff: (params: Params = {}) => blob('/staff/export', params),
  bulkImport: (csv: string) => post<{ job_id: string }>('/staff/bulk-import', { csv }, once),
  facultyProfile: (id: string) => get<FacultyProfile | null>(`/staff/${id}/faculty-profile`),
  saveFacultyProfile: (id: string, body: Body) => put<FacultyProfile>(`/staff/${id}/faculty-profile`, body),
  qualifications: (id: string) => get<Qualification[]>(`/staff/${id}/qualifications`),
  addQualification: (id: string, body: Body) => post<Qualification[]>(`/staff/${id}/qualifications`, body, once),
  documents: (id: string) => get<StaffDocument[]>(`/staff/${id}/documents`),
  addDocument: (id: string, body: Body) => post<StaffDocument>(`/staff/${id}/documents`, body, once),
  serviceBook: (id: string) => get<ServiceBookEntry[]>(`/staff/${id}/service-book`),
  addServiceEntry: (id: string, body: Body) => post<ServiceBookEntry>(`/staff/${id}/service-book`, body, once),
  // leaves
  leaveTypes: () => get<LeaveType[]>('/leave-types'),
  leaves: (params: Params = {}) => get<Leave[]>('/leaves', { params }),
  leave: (id: string) => get<Leave>(`/leaves/${id}`),
  applyLeave: (body: Body) => post<Leave>('/leaves', body),
  cancelLeave: (id: string) => post<Leave>(`/leaves/${id}/cancel`, undefined, once),
  decideLeave: (id: string, decision: 'approve' | 'reject', comment?: string) =>
    post<Leave>(`/leaves/${id}/${decision}`, { comment }, once),
  myBalance: (year?: number) => get<LeaveBalance[]>('/leaves/me/balance', { params: { year } }),
  balances: (staffId: string) => get<LeaveBalance[]>('/leaves/balances', { params: { staff_id: staffId } }),
  calendar: (params: Params = {}) => get<LeaveCalendarItem[]>('/leaves/calendar', { params }),
  encash: (body: Body) => post<{ workflow_instance_id: string; amount_paise: number }>('/leaves/encash', body, once),
  // staff attendance
  attendance: (params: Params = {}) => get<Attendance[]>('/staff-attendance', { params }),
  summary: (params: Params = {}) => get<AttendanceSummary[]>('/staff-attendance/summary', { params }),
  mark: (body: Body) => post<Attendance>('/staff-attendance/mark', body, once),
  checkIn: (geo?: { lat: number; lng: number; accuracy_m?: number }) =>
    post<Attendance>('/staff-attendance/self-checkin', geo ? { geo } : {}, once),
  checkOut: () => post<Attendance>('/staff-attendance/self-checkout', {}, once),
  regularise: (body: Body) => post<{ workflow_instance_id: string }>('/staff-attendance/regularise', body, once),
  devices: () => get<Device[]>('/attendance-devices'),
  createDevice: (body: Body) => post<Device>('/attendance-devices', body, once),
  // payroll
  components: () => get<PayrollComponent[]>('/payroll/components'),
  saveComponent: (id: string | null, body: Body) =>
    id ? put<PayrollComponent>(`/payroll/components/${id}`, body) : post<PayrollComponent>('/payroll/components', body, once),
  structures: (staffId: string) => get<SalaryStructure[]>(`/staff/${staffId}/salary-structures`),
  addStructure: (staffId: string, body: Body) => post<SalaryStructure>(`/staff/${staffId}/salary-structures`, body, once),
  generate: (body: Body) => post<{ job_id: string }>('/payroll/generate', body),
  payroll: (params: Params = {}) => get<Payroll[]>('/payroll', { params }),
  payrollOne: (id: string) => get<Payroll>(`/payroll/${id}`),
  myPayslips: (year?: number) => get<Payroll[]>('/payroll/me', { params: { year } }),
  approvePayroll: (id: string) => post<Payroll>(`/payroll/${id}/approve`, undefined, once),
  approveMany: (ids: string[]) => post<{ succeeded: string[]; failed: unknown[] }>('/payroll/approve', { ids }, once),
  markPaid: (id: string, payment_ref: string) => post<Payroll>(`/payroll/${id}/mark-paid`, { payment_ref }, once),
  payslip: (id: string) => blob(`/payroll/${id}/payslip.pdf`),
  register: (kind: string, month: number, year: number) => get<Register>(`/payroll/registers/${kind}`, { params: { month, year } }),
  form16: (year: number, staffId?: string) => get<Form16>('/payroll/form16', { params: { year, staff_id: staffId } }),
  bankAdvice: (month: number, year: number) => blob('/payroll/bank-advice', { month, year }),
  loans: (params: Params = {}) => get<Loan[]>('/loans', { params }),
  createLoan: (body: Body) => post<Loan>('/loans', body, once),
  foreclose: (id: string) => post<Loan>(`/loans/${id}/foreclose`, undefined, once),
  // recruitment
  postings: (params: Params = {}) => get<Posting[]>('/recruitment/postings', { params }),
  createPosting: (body: Body) => post<Posting>('/recruitment/postings', body, once),
  postingAction: (id: string, action: 'publish' | 'close' | 'cancel') => post<Posting>(`/recruitment/postings/${id}/${action}`, undefined, once),
  applications: (postingId: string) => get<Application[]>(`/recruitment/postings/${postingId}/applications`),
  appAction: (id: string, action: string, body: Body = {}) => post<{ status: string }>(`/recruitment/applications/${id}/${action}`, body, once),
  panels: (postingId: string) => get<Panel[]>(`/recruitment/postings/${postingId}/panels`),
  createPanel: (postingId: string, body: Body) => post<Panel>(`/recruitment/postings/${postingId}/panels`, body, once),
  score: (panelId: string, body: Body) => post<{ total: string }>(`/recruitment/panels/${panelId}/scores`, body, once),
  publicPostings: (institution?: string) => get<PublicPosting[]>('/public/careers', { params: { institution } }),
  publicApply: (postingId: string, body: Body) => post<{ reference: string }>(`/public/careers/${postingId}/apply`, body),
  // appraisal / CAS
  pbasSchema: () => get<PbasSchema>('/appraisals/schema'),
  appraisals: (params: Params = {}) => get<Appraisal[]>('/appraisals', { params }),
  saveAppraisal: (body: Body) => post<Appraisal>('/appraisals', body, once),
  submitAppraisal: (id: string) => post<Appraisal>(`/appraisals/${id}/submit`, undefined, once),
  reviewAppraisal: (id: string, body: Body) => post<Appraisal>(`/appraisals/${id}/review`, body, once),
  cas: (params: Params = {}) => get<CasApplication[]>('/cas-applications', { params }),
  createCas: (body: Body = {}) => post<CasApplication>('/cas-applications', body, once),
  submitCas: (id: string) => post<CasApplication>(`/cas-applications/${id}/submit`, undefined, once),
  decideCas: (id: string, body: Body) => post<CasApplication>(`/cas-applications/${id}/decide`, body, once),
  // workload
  myWorkload: (staffId: string, termId?: string) => get<Workload>(`/faculty/${staffId}/workload`, { params: { term_id: termId } }),
  workload: (departmentId: string, termId?: string) => get<Workload[]>('/workload', { params: { department_id: departmentId, term_id: termId } }),
  allocation: (departmentId: string) => get<AllocationProposal>(`/departments/${departmentId}/course-allocation`),
  saveAllocation: (departmentId: string, proposals: Body[]) =>
    post<AllocationProposal>(`/departments/${departmentId}/course-allocation`, { proposals }, once),
  allocationAction: (id: string, action: 'submit' | 'approve' | 'apply') => post<AllocationProposal>(`/course-allocation/${id}/${action}`, {}, once),
};
