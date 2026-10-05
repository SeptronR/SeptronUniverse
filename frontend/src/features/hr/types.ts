/** Phase 06 HR types (mirror app/schemas/hr.py, leaves.py, payroll.py, recruitment.py). Decimals arrive as strings. */
export type Dec = string | number;

export interface Designation {
  id: string;
  name: string;
  code: string | null;
  cadre: string | null;
  category: string;
  level: number | null;
  is_active: boolean;
  staff_count: number;
}

export interface Staff {
  id: string;
  employee_id: string;
  full_name: string;
  first_name: string;
  last_name: string | null;
  college_id: string | null;
  department_id: string | null;
  department_code: string | null;
  designation_id: string | null;
  designation_name: string | null;
  cadre: string | null;
  employment_type: string;
  staff_category: string;
  status: string;
  user_id: string | null;
  username: string | null;
  photo_url: string | null;
  joining_date: string | null;
  phone: string | null;
  email: string | null;
  hourly_rate_paise: number | null;
  version: number;
  is_self: boolean;
}

export interface StaffDetail extends Staff {
  dob: string | null;
  gender: string | null;
  blood_group: string | null;
  address: Record<string, unknown> | null;
  emergency_contact: Record<string, unknown> | null;
  exit_date: string | null;
  exit_reason: string | null;
  pan: string | null;
  aadhaar: string | null;
  bank_details: string | null;
  pf_number: string | null;
  esi_number: string | null;
  uan: string | null;
  reports_to_name: string | null;
  has_faculty_profile: boolean;
}

export interface FacultyProfile {
  id: string;
  aicte_faculty_id: string | null;
  orcid: string | null;
  scopus_id: string | null;
  google_scholar_id: string | null;
  vidwan_id: string | null;
  highest_qualification: string | null;
  is_phd: boolean;
  phd_year: number | null;
  is_phd_guide: boolean;
  guide_recognition_no: string | null;
  max_scholars: number | null;
  experience_teaching_months: number;
  experience_industry_months: number;
  experience_research_months: number;
  specializations: string[] | null;
  api_score: Dec | null;
  cadre: string | null;
}

export interface Qualification {
  id: string;
  degree: string;
  discipline: string | null;
  university: string | null;
  year: number | null;
  is_highest: boolean;
}

export interface StaffDocument {
  id: string;
  doc_type: string;
  file_url: string;
  expires_on: string | null;
  verified_at: string | null;
  uploaded_at: string;
}

export interface ServiceBookEntry {
  id: string;
  entry_type: string;
  effective_date: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface LeaveType {
  id: string;
  code: string;
  name: string;
  annual_quota: Dec | null;
  accrual: string;
  carry_forward_max: Dec | null;
  is_paid: boolean;
  is_encashable: boolean;
  requires_document: boolean;
  is_active: boolean;
}

export interface Leave {
  id: string;
  staff_id: string;
  staff_name: string | null;
  employee_id: string | null;
  department_code: string | null;
  leave_type_id: string;
  leave_type_code: string | null;
  leave_type_name: string | null;
  from_date: string;
  to_date: string;
  days_count: Dec;
  half_day: string | null;
  reason: string | null;
  document_url: string | null;
  status: string;
  review_comment: string | null;
  workflow_instance_id: string | null;
  workflow_status: string | null;
  current_step: number | null;
  created_at: string;
  is_mine: boolean;
  can_act: boolean;
}

export interface LeaveBalance {
  leave_type_id: string;
  code: string;
  name: string;
  year: number;
  annual_quota: Dec | null;
  opening: Dec;
  accrued: Dec;
  used: Dec;
  encashed: Dec;
  balance: Dec;
  pending: Dec;
  available: Dec | null;
  is_paid: boolean;
  is_encashable: boolean;
}

export interface LeaveCalendarItem {
  id: string;
  staff_name: string;
  department_code: string | null;
  leave_type_code: string;
  from_date: string;
  to_date: string;
  days_count: Dec;
  status: string;
}

export interface Attendance {
  id: string;
  staff_id: string;
  staff_name: string | null;
  employee_id: string | null;
  attendance_date: string;
  status: string;
  check_in_time: string | null;
  check_out_time: string | null;
  source: string;
  remarks: string | null;
}

export interface AttendanceSummary {
  staff_id: string;
  staff_name: string;
  employee_id: string;
  days_in_month: number;
  present: number;
  absent: number;
  half_day: number;
  on_leave: number;
  on_duty: number;
  holiday: number;
  week_off: number;
  lop_days: number;
  unmarked: number;
}

export interface Device {
  id: string;
  name: string;
  device_type: string;
  location: string | null;
  last_seen_at: string | null;
  is_active: boolean;
  token: string | null;
}

export interface PayrollComponent {
  id: string;
  code: string;
  name: string;
  component_type: string;
  calc_type: string;
  formula: Record<string, unknown> | null;
  statutory_kind: string | null;
  is_taxable: boolean;
  sequence: number;
  is_active: boolean;
}

export interface SalaryStructure {
  id: string;
  effective_from: string;
  effective_to: string | null;
  pay_level: string | null;
  basic_paise: number;
  components: Record<string, unknown>;
  ctc_paise: number | null;
  monthly_gross_paise: number | null;
}

export interface PayrollItem {
  id: string;
  label: string;
  component_type: string;
  amount_paise: number;
  source_type: string | null;
}

export interface Payroll {
  id: string;
  staff_id: string;
  staff_name: string | null;
  employee_id: string | null;
  department_code: string | null;
  month: number;
  year: number;
  working_days: number | null;
  paid_days: Dec | null;
  lop_days: Dec;
  gross_paise: number;
  deductions_paise: number;
  employer_contrib_paise: number;
  net_paise: number;
  status: string;
  payment_ref: string | null;
  payslip_url: string | null;
  items: PayrollItem[];
}

export interface Register {
  kind: string;
  columns: string[];
  rows: Record<string, unknown>[];
  totals: Record<string, number>;
}

export interface Form16 {
  staff_name: string;
  employee_id: string;
  pan: string | null;
  financial_year: string;
  assessment_year: string;
  regime: string;
  months: { period: string; gross: number; tds: number; pt?: number; pf?: number; status?: string }[];
  gross_salary_paise: number;
  standard_deduction_paise: number;
  professional_tax_paise: number;
  pf_employee_paise: number;
  taxable_income_paise: number;
  tax_on_income_paise: number;
  tds_deducted_paise: number;
  quarters: Record<string, number>;
}

export interface Loan {
  id: string;
  staff_id: string;
  staff_name: string | null;
  employee_id: string | null;
  loan_type: string;
  principal_paise: number;
  emi_paise: number;
  start_month: string;
  balance_paise: number;
  status: string;
  emis_remaining: number | null;
}

export interface Posting {
  id: string;
  title: string;
  department_code: string | null;
  cadre: string | null;
  vacancies: number;
  reservation: { roster?: string; vacancies?: Record<string, number> } | null;
  qualifications: string[] | null;
  description: string | null;
  closes_at: string | null;
  status: string;
  pipeline: Record<string, number>;
}

export interface PublicPosting {
  id: string;
  title: string;
  department: string | null;
  cadre: string | null;
  vacancies: number;
  reservation: { vacancies?: Record<string, number> } | null;
  qualifications: string[] | null;
  description: string | null;
  closes_at: string | null;
}

export interface Application {
  id: string;
  posting_id: string;
  name: string | null;
  email: string | null;
  phone: string | null;
  category: string | null;
  screening_score: Dec | null;
  interview_total: Dec | null;
  status: string;
  staff_id: string | null;
  applicant: Record<string, unknown> | null;
}

export interface Panel {
  id: string;
  scheduled_at: string;
  venue: string | null;
  members: { user_id: string; name: string; role: string; weight: number }[];
}

export interface Appraisal {
  id: string;
  staff_id: string;
  staff_name: string | null;
  employee_id: string | null;
  academic_year: string | null;
  self_assessment: { values?: Record<string, Record<string, number>>; auto?: Record<string, number> } | null;
  self_score: Dec | null;
  reviewer_score: Dec | null;
  final_score: Dec | null;
  status: string;
  workflow_instance_id: string | null;
  breakdown: Record<string, number>;
  auto_filled: Record<string, number>;
}

export type PbasSchema = Record<string, { label: string; max: number; items: Record<string, { label: string; max: number; per_unit: number; auto?: string }> }>;

export interface CasApplication {
  id: string;
  staff_id: string;
  staff_name: string | null;
  from_cadre: string;
  to_cadre: string;
  eligibility_date: string | null;
  eligible_now: boolean;
  api_breakdown: Record<string, unknown> | null;
  status: string;
  workflow_instance_id: string | null;
}

export interface Workload {
  staff_id: string;
  staff_name: string;
  employee_id: string;
  cadre: string | null;
  theory_hours: number;
  tutorial_hours: number;
  lab_hours: number;
  admin_hours: number;
  total_hours: number;
  norm_hours: number | null;
  load_status: string;
  note: string | null;
}

export interface AllocationProposal {
  id: string;
  department_id: string;
  term_id: string;
  proposals: { course_id: string; staff_id: string; hours: number; role: string }[];
  status: string;
  workflow_instance_id: string | null;
  note: string | null;
}

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** ₹ with Indian grouping from paise. */
export const inr = (paise: number | null | undefined) =>
  paise == null ? '—' : (paise / 100).toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });

export const num = (v: Dec | null | undefined) => (v == null ? '—' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: 1 }));

export const label = (s: string | null | undefined) => (s ? s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : '—');

/** Local calendar date `YYYY-MM-DD` (not UTC — the institution's day starts at local midnight). */
export const localDate = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
