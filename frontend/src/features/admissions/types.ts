/** Admissions types — mirror app/schemas/admissions.py (Prompts/08 §08.4). */

export interface Cycle {
  id: string;
  college_id: string | null;
  academic_year_id: string;
  name: string;
  slug: string;
  level: string;
  application_fee_paise: number;
  opens_at: string | null;
  closes_at: string | null;
  status: string;
  form_config: Record<string, unknown> | null;
  required_documents: RequiredDocument[] | null;
  de_reservation_policy: { convert?: Record<string, string>; final_round_number?: number } | null;
  version: number;
  created_at: string;
  programs_count: number;
  applicants_count: number;
  intake_total: number;
}

export interface RequiredDocument {
  doc_type: string;
  label?: string | null;
  required?: boolean;
  entry_types?: string[] | null;
}

export interface CycleProgram {
  id: string;
  cycle_id: string;
  program_id: string;
  college_id: string;
  program_code: string | null;
  program_name: string | null;
  college_name: string | null;
  department_id: string | null;
  intake: number;
  lateral_intake: number;
  entrance_source: string;
  eligibility_rules: Record<string, unknown> | null;
  merit_formula: { field: string; weight: number; max?: number }[] | null;
  tie_break: string[] | null;
}

export interface SeatRow {
  id: string;
  program_id: string;
  college_id: string;
  program_code: string | null;
  quota: string;
  category: string;
  seats: number;
  filled: number;
  vacant: number;
}

export interface ProgramSeatTotal {
  program_id: string;
  college_id: string;
  program_code: string | null;
  intake: number;
  lateral_intake: number;
  seats: number;
  filled: number;
  balanced: boolean;
}

export interface SeatStatus {
  cycle_id: string;
  rows: SeatRow[];
  programs: ProgramSeatTotal[];
  quotas: string[];
  categories: string[];
}

export interface Preference {
  priority: number;
  program_id: string;
  college_id: string;
  program_code: string | null;
  program_name: string | null;
}

export interface ApplicantDocument {
  doc_type: string;
  file_url: string | null;
  status: string;
  remarks: string | null;
  verified_at: string | null;
}

export interface Payment {
  ref: string;
  amount_paise: number;
  status: string;
  provider?: string;
  paid_at?: string | null;
  workflow_instance_id?: string | null;
  policy?: string;
}

export interface Allotment {
  id: string;
  round_id: string;
  round_number: number | null;
  applicant_id: string;
  application_number: string | null;
  applicant_name: string | null;
  program_id: string;
  program_code: string | null;
  program_name: string | null;
  college_id: string;
  quota: string;
  category: string;
  priority: number | null;
  status: string;
  admission_fee_paise: number | null;
  accepted_at: string | null;
  reporting_deadline: string | null;
  payment: Payment | null;
  created_at: string;
}

export interface Applicant {
  id: string;
  cycle_id: string;
  cycle_name: string | null;
  cycle_slug: string | null;
  application_number: string;
  user_id: string | null;
  first_name: string;
  middle_name: string | null;
  last_name: string | null;
  name: string;
  dob: string | null;
  gender: string | null;
  category: string | null;
  is_pwd: boolean;
  quota_claimed: string | null;
  nationality: string | null;
  domicile_state: string | null;
  phone: string | null;
  email: string | null;
  contact: Record<string, string> | null;
  entrance: Record<string, unknown> | null;
  qualifying_exams: { level?: string; board?: string; year?: number; pct?: number; subjects?: string[] }[] | null;
  merit_score: string | null;
  status: string;
  entry_type: string;
  source: string;
  remarks: string | null;
  submitted_at: string | null;
  admitted_student_id: string | null;
  preferences: Preference[];
  documents: ApplicantDocument[];
  missing_documents: string[];
  payments: Record<string, Payment>;
  allotment: Allotment | null;
  allowed_transitions: string[];
  version: number;
  created_at: string;
}

export interface ApplicantListItem {
  id: string;
  cycle_id: string;
  application_number: string;
  name: string;
  category: string | null;
  is_pwd: boolean;
  quota_claimed: string | null;
  entry_type: string;
  source: string;
  status: string;
  merit_score: string | null;
  phone: string | null;
  email: string | null;
  first_preference: string | null;
  submitted_at: string | null;
  docs_pending: number;
}

export interface TimelineEntry {
  at: string;
  action: string;
  status_from: string | null;
  status_to: string | null;
  by: string | null;
  remarks: string | null;
}

export interface MeritList {
  id: string;
  cycle_id: string;
  program_id: string | null;
  name: string;
  quota: string | null;
  category: string | null;
  formula_snapshot: Record<string, unknown> | null;
  status: string;
  generated_at: string | null;
  published_at: string | null;
  job_id: string | null;
  created_at: string;
  entries_count: number;
}

export interface MeritEntry {
  rank: number;
  category_rank: number | null;
  score: string | null;
  applicant_id: string;
  application_number: string;
  name: string;
  category: string | null;
  is_pwd: boolean;
}

export interface MeritListDetail extends MeritList {
  entries: MeritEntry[];
}

export interface Round {
  id: string;
  cycle_id: string;
  round_number: number;
  name: string | null;
  choice_filling_start: string | null;
  choice_filling_end: string | null;
  allotment_at: string | null;
  reporting_deadline: string | null;
  status: string;
  is_final: boolean;
  allotments_count: number;
}

export interface AllotmentSummary {
  round_id: string;
  round_number: number;
  dry_run: boolean;
  is_final: boolean;
  considered: number;
  allotted: number;
  upgraded: number;
  retained: number;
  unallotted: number;
  rows: { program_id: string; program_code: string | null; quota: string; category: string; seats: number; filled: number; allotted_now: number }[];
  conversions: { program_code: string | null; quota: string; from_category: string; to_category: string; seats: number }[];
  allotments: { application_number: string; program_code: string | null; quota: string; category: string; priority: number; kind: string }[];
  job_id: string | null;
}

export interface Offer {
  id: string;
  applicant_id: string;
  application_number: string | null;
  applicant_name: string | null;
  program_id: string;
  program_code: string | null;
  offer_type: string;
  valid_until: string | null;
  letter_html: string | null;
  status: string;
  created_at: string;
}

export interface AdmitResult {
  student_id: string;
  registration_number: string;
  username: string | null;
  temp_password: string | null;
  applicant: Applicant;
}

export interface ImportResult {
  dry_run: boolean;
  total: number;
  succeeded: number;
  allotted: number;
  failed: { row: number; error: string }[];
  job_id: string | null;
}

export interface Enquiry {
  id: string;
  college_id: string | null;
  source: string;
  name: string;
  phone: string | null;
  email: string | null;
  program_interest: string[] | null;
  stage: string;
  assigned_to: string | null;
  assigned_name: string | null;
  follow_up_on: string | null;
  notes: { at: string; by: string; text: string }[];
  applicant_id: string | null;
  application_number: string | null;
  created_at: string;
}

export interface EnquiryStats {
  total: number;
  by_stage: Record<string, number>;
  by_source: Record<string, number>;
  funnel: { stage: string; count: number; pct: number }[];
}

export interface PublicCycle {
  name: string;
  slug: string;
  level: string;
  status: string;
  application_fee_paise: number;
  opens_at: string | null;
  closes_at: string | null;
  is_open: boolean;
  institution: { name: string; slug: string };
  programs: { program_id: string; code: string | null; name: string | null; college_name: string | null; intake: number; lateral_intake: number; entrance_source: string; eligibility_rules: Record<string, unknown> | null }[];
  required_documents: RequiredDocument[];
  categories: { code: string; name: string }[];
  quotas: { code: string; name: string }[];
  published_merit_lists: { id: string; name: string; published_at: string | null }[];
}

export const CYCLE_STATUSES = ['draft', 'open', 'closed', 'merit_processing', 'counselling', 'completed', 'archived'];
export const CYCLE_NEXT: Record<string, string[]> = {
  draft: ['open'],
  open: ['closed'],
  closed: ['open', 'merit_processing'],
  merit_processing: ['counselling', 'completed'],
  counselling: ['completed'],
  completed: ['archived'],
  archived: [],
};
export const APPLICANT_STATUSES = [
  'draft', 'submitted', 'fee_paid', 'under_verification', 'verified', 'doc_rejected', 'waitlisted', 'merit_listed',
  'allotted', 'accepted', 'admitted', 'declined', 'lapsed', 'withdrawn', 'rejected',
];
export const ENQUIRY_STAGES = ['new', 'contacted', 'counselled', 'applied', 'admitted', 'lost'];
export const ROUND_NEXT: Record<string, string[]> = {
  planned: ['choice_filling', 'allotted'],
  choice_filling: ['planned', 'allotted'],
  allotted: ['reporting', 'closed'],
  reporting: ['closed'],
  closed: [],
};

export const label = (s: string | null | undefined) =>
  s ? s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : '—';
export const rupees = (paise: number | null | undefined) =>
  paise == null ? '—' : `₹${(paise / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
