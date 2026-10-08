/** Phase 07 student types (mirror app/schemas/students.py). Decimals arrive as strings. */
export type Dec = string | number;

export interface StudentListItem {
  id: string;
  registration_number: string;
  first_name: string;
  last_name: string | null;
  full_name: string;
  college_id: string;
  college_code: string | null;
  department_code: string | null;
  program_id: string | null;
  program_code: string | null;
  batch_id: string | null;
  batch_code: string | null;
  section_name: string | null;
  term_number: number | null;
  enrollment_status: string | null;
  status: string;
  academic_standing: string | null;
  open_holds: number;
  category: string | null;
  gender: string | null;
  phone: string | null;
  email: string | null;
  photo_url: string | null;
  apaar_id: string | null;
  is_self: boolean;
  is_ward: boolean;
}

export interface Enrollment {
  id: string;
  student_id: string;
  college_id: string;
  program_id: string;
  program_code: string | null;
  program_name: string | null;
  total_terms: number | null;
  batch_id: string;
  batch_code: string | null;
  program_regulation_id: string;
  regulation_code: string | null;
  department_id: string;
  department_code: string | null;
  admission_date: string;
  entry_type: string;
  entry_term_number: number;
  specialization: string | null;
  is_honours: boolean;
  expected_exit_term: number | null;
  status: string;
  exit_award: string | null;
  exit_date: string | null;
  credits_earned: Dec;
  cgpa: Dec | null;
  academic_standing: string;
  current_term_number: number | null;
  section_id: string | null;
  section_name: string | null;
  open_holds: number;
  version: number;
}

export interface TermRecord {
  id: string;
  student_program_enrollment_id: string;
  term_id: string;
  term_name: string | null;
  academic_year_name: string | null;
  term_number: number;
  section_id: string | null;
  section_name: string | null;
  roll_number: string | null;
  status: string;
  credits_registered: Dec;
  credits_earned: Dec;
  sgpa: Dec | null;
  cgpa: Dec | null;
  attendance_pct: Dec | null;
  result_status: string | null;
}

export interface Hold {
  id: string;
  student_program_enrollment_id: string;
  student_id: string | null;
  registration_number: string | null;
  student_name: string | null;
  hold_type: string;
  reason: string;
  placed_by: string;
  placed_by_name: string | null;
  placed_at: string;
  released_by: string | null;
  released_by_name: string | null;
  released_at: string | null;
  release_reason: string | null;
  source_type: string | null;
  is_open: boolean;
  can_release: boolean;
}

export interface Guardian {
  id: string;
  student_id: string;
  user_id: string | null;
  username: string | null;
  relation: string;
  name: string;
  phone: string | null;
  email: string | null;
  occupation: string | null;
  annual_income_paise: number | null;
  is_primary: boolean;
  portal_access: boolean;
}

export interface StudentDocument {
  id: string;
  student_id: string;
  doc_type: string;
  file_url: string;
  verified_by: string | null;
  verified_at: string | null;
  expires_on: string | null;
  remarks: string | null;
  uploaded_at: string;
  is_verified: boolean;
  is_expired: boolean;
}

export interface UndertakingStatus {
  undertaking_type: string;
  name: string;
  template_id: string | null;
  version: string | null;
  required: boolean;
  accepted: boolean;
  accepted_at: string | null;
  body: string | null;
}

export interface StudentDetail extends StudentListItem {
  middle_name: string | null;
  dob: string | null;
  blood_group: string | null;
  sub_category: string | null;
  is_pwd: boolean;
  pwd_pct: number | null;
  is_minority: boolean;
  minority_type: string | null;
  religion: string | null;
  nationality: string | null;
  mother_tongue: string | null;
  domicile_state: string | null;
  permanent_address: Record<string, unknown> | null;
  current_address: Record<string, unknown> | null;
  emergency_contact: { name?: string; phone?: string; relation?: string } | null;
  aadhaar: string | null;
  bank_details: string | null;
  abc_id: string | null;
  enrolment_number: string | null;
  is_international: boolean;
  guardian_portal_consent: boolean;
  admission_quota: string | null;
  admission_mode: string | null;
  admission_date: string | null;
  user_id: string | null;
  username: string | null;
  is_adult: boolean;
  version: number;
  enrollment: Enrollment | null;
  current_term: TermRecord | null;
  holds: Hold[];
  guardians: Guardian[];
  documents: StudentDocument[];
  undertakings: UndertakingStatus[];
  allowed_transitions: string[];
}

export interface StudentCreateResult {
  student: StudentDetail;
  username: string | null;
  temp_password: string | null;
  guardian_accounts: { guardian_id: string; username: string | null; temp_password: string | null; reused: boolean }[];
}

export interface PromotionRow {
  student_id: string;
  enrollment_id: string;
  registration_number: string;
  name: string;
  section_name: string | null;
  backlogs: number;
}

export interface PromotionPreview {
  batch_id: string;
  batch_code: string;
  from_term_number: number;
  to_term_number: number;
  from_term: Record<string, unknown> | null;
  to_term: Record<string, unknown> | null;
  max_backlogs: number;
  dry_run: boolean;
  promoted: PromotionRow[];
  detained: PromotionRow[];
  on_break: PromotionRow[];
  already_promoted: number;
  blocking: string | null;
  job_id: string | null;
}

export interface StandingHistoryItem {
  at: string;
  from_standing: string | null;
  to_standing: string;
  cgpa: number | null;
  sgpa: number | null;
  term_number: number | null;
  by: string | null;
}

export interface Standing {
  enrollment_id: string;
  standing: string;
  cgpa: Dec | null;
  rules: Record<string, unknown>[];
  history: StandingHistoryItem[];
}

export interface Transfer {
  id: string;
  student_id: string;
  registration_number: string | null;
  student_name: string | null;
  transfer_type: string;
  from_ref: Record<string, unknown> | null;
  to_ref: Record<string, unknown> | null;
  migration_certificate_no: string | null;
  tc_no: string | null;
  reason: string | null;
  requested_at: string;
  effective_date: string | null;
  status: string;
  workflow_instance_id: string | null;
  workflow_status: string | null;
  current_step: number | null;
  can_act: boolean;
}

export interface CreditTransfer {
  id: string;
  student_program_enrollment_id: string;
  student_id: string | null;
  registration_number: string | null;
  student_name: string | null;
  department_code: string | null;
  source: string;
  source_course_code: string | null;
  source_title: string;
  source_institution: string | null;
  credits: Dec;
  source_grade: string | null;
  source_score_pct: Dec | null;
  letter_grade: string | null;
  equivalent_course_id: string | null;
  equivalent_course: string | null;
  certificate_url: string | null;
  status: string;
  workflow_instance_id: string | null;
  workflow_status: string | null;
  current_step: number | null;
  can_act: boolean;
  created_at: string | null;
}

export interface BulkImportResult {
  dry_run: boolean;
  total: number;
  succeeded: number;
  failed: { row: number; reason: string; field: string | null }[];
  created: Record<string, unknown>[];
  job_id: string | null;
}

export interface IdCard {
  student_id: string;
  registration_number: string;
  name: string;
  program: string | null;
  batch: string | null;
  college: string | null;
  institution: string | null;
  blood_group: string | null;
  photo_url: string | null;
  emergency_phone: string | null;
  valid_until: string | null;
  token: string;
  verify_url: string;
}

export interface StatBucket {
  key: string;
  label: string;
  count: number;
}

export interface StudentStats {
  total: number;
  by_status: StatBucket[];
  by_program: StatBucket[];
  by_batch: StatBucket[];
  by_standing: StatBucket[];
}

export interface StudentDashboard {
  student: StudentDetail;
  enrollment: Enrollment | null;
  current_term: TermRecord | null;
  holds: Hold[];
  undertakings_pending: UndertakingStatus[];
  standing: string | null;
  credit_transfers_pending: number;
  quick_links: { key: string; label: string; route: string; feature: string | null }[];
}

export interface WardSummary {
  student_id: string;
  registration_number: string;
  name: string;
  relation: string | null;
  program_code: string | null;
  batch_code: string | null;
  term_number: number | null;
  status: string;
  academic_standing: string | null;
  open_holds: number;
  photo_url: string | null;
}

export interface VerifyResult {
  valid: boolean;
  document_type: string;
  holder_name: string | null;
  registration_number: string | null;
  program: string | null;
  status: string | null;
  institution: string | null;
  college: string | null;
  valid_until: string | null;
  message: string | null;
}

export const STUDENT_STATUSES = [
  'provisional',
  'admitted',
  'active',
  'on_break',
  'detained',
  'dropped_out',
  'transferred',
  'exited',
  'graduated',
  'alumni',
  'expelled',
  'deceased',
];
export const STANDINGS = ['good', 'warning', 'probation', 'dismissal'];
export const HOLD_TYPES = ['registration', 'exam', 'transcript', 'graduation', 'hostel', 'library', 'all'];
export const RELATIONS = ['father', 'mother', 'guardian', 'spouse', 'other'];
export const TRANSFER_TYPES = ['migration_out', 'migration_in', 'inter_college', 'program_change', 'inter_university'];
export const CT_SOURCES = ['nptel', 'swayam', 'coursera', 'other_mooc', 'abc', 'other_university', 'prior_learning'];
export const ENTRY_TYPES = ['regular', 'lateral', 'migrated', 'readmission'];
export const GENDERS = [
  { value: 'M', label: 'Male' },
  { value: 'F', label: 'Female' },
  { value: 'O', label: 'Other' },
];

export const label = (s: string | null | undefined) =>
  s ? s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : '—';

export const STANDING_VARIANT: Record<string, 'success' | 'warning' | 'destructive' | 'secondary'> = {
  good: 'success',
  warning: 'warning',
  probation: 'destructive',
  dismissal: 'destructive',
};

/** Address JSON → one line. */
export const addressLine = (a: Record<string, unknown> | null | undefined) =>
  a ? Object.values(a).filter((v) => typeof v === 'string' && v).join(', ') : null;
