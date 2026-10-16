/** Offerings & registration types — mirror app/schemas/offerings.py + registration.py (Prompts/09 §09.4). */
export interface FacultyOut {
  staff_id: string;
  name: string | null;
  employee_id: string | null;
  role: string;
  hours_per_week: number;
  total_hours: number | null;
  norm_hours: number | null;
  load_status: string | null;
}
export interface TargetOut {
  batch_id: string;
  batch_code: string | null;
  section_id: string | null;
  section_name: string | null;
  term_number: number;
}
export interface Offering {
  id: string;
  term_id: string;
  term_name: string | null;
  course_id: string;
  course_code: string | null;
  course_title: string | null;
  course_type: string | null;
  credits: number;
  department_id: string;
  department_code: string | null;
  college_code: string | null;
  section_code: string;
  coordinator_name: string | null;
  faculty: FacultyOut[];
  max_seats: number | null;
  enrolled_count: number;
  waitlist_count: number;
  seats_left: number | null;
  delivery_mode: string;
  targets: TargetOut[];
  status: string;
  version: number;
  is_mine: boolean;
}
export interface BulkPreview {
  term_id: string;
  dry_run: boolean;
  total: number;
  to_create: number;
  existing: number;
  targets_added: number;
  job_id: string | null;
  warnings: string[];
  items: {
    course_code: string;
    course_title: string;
    section_code: string;
    batch_codes: string[];
    mandatory: boolean;
    basket_code: string | null;
    exists: boolean;
  }[];
}
export interface RosterItem {
  item_id: string;
  registration_number: string | null;
  name: string | null;
  program_code: string | null;
  batch_code: string | null;
  section_name: string | null;
  registration_type: string;
  attempt_number: number;
  status: string;
}
export interface RegWindow {
  id: string;
  term_id: string;
  term_name: string | null;
  name: string;
  window_type: string;
  applies_to: Record<string, unknown> | null;
  starts_at: string;
  ends_at: string;
  late_fee_paise: number;
  requires_advisor_approval: boolean;
  requires_fee_clearance: boolean;
  max_credits_override: number | null;
  status: string;
  is_open_now: boolean;
}
export interface CatalogOffering {
  offering_id: string;
  section_code: string;
  faculty: string[];
  max_seats: number | null;
  enrolled_count: number;
  waitlist_count: number;
  seats_left: number | null;
  targeted: boolean;
  status: string;
}
export interface CatalogCourse {
  course_id: string;
  code: string;
  title: string;
  credits: number;
  course_type: string | null;
  mandatory: boolean;
  requisites: { relation: string; course_code: string | null; met: boolean; is_hard: boolean }[];
  prerequisites_met: boolean;
  offerings: CatalogOffering[];
  in_cart: string | null;
}
export interface ChoiceForm {
  id: string;
  basket_id: string;
  term_id: string;
  choices: { course_id: string; code: string | null; title: string | null; priority: number }[];
  status: string;
  allocated_course_code: string | null;
  student_name?: string | null;
  registration_number?: string | null;
}
export interface CatalogBasket {
  basket_id: string;
  code: string;
  name: string;
  min_choose: number;
  max_choose: number;
  courses: CatalogCourse[];
  choice_form: ChoiceForm | null;
}
export interface Catalog {
  term: { id: string; name: string; status: string };
  structure_term: { term_number: number; name: string | null } | null;
  limits: { min: number; max: number; normal: number; overridden: boolean };
  window: RegWindow | null;
  windows: RegWindow[];
  curriculum: CatalogCourse[];
  baskets: CatalogBasket[];
  arrears: {
    arrear_id: string;
    course_id: string;
    code: string;
    title: string;
    credits: number;
    attempts: number;
    status: string;
    offerings: CatalogOffering[];
    in_cart: string | null;
  }[];
  holds: string[];
  hold_details: { id: string; hold_type: string; reason: string }[];
  undertakings_pending: string[];
  fee_preview: {
    registration_fee_paise: number;
    arrear_fee_paise: number;
    late_fee_paise: number;
    total_paise: number;
    note: string | null;
  };
  registration_id: string | null;
  registration_status: string | null;
  audit_courses_enabled: boolean;
}
export interface RegItem {
  id: string;
  offering_id: string;
  course_id: string;
  course_code: string | null;
  course_title: string | null;
  credits: number;
  section_code: string | null;
  registration_type: string;
  attempt_number: number;
  status: string;
  drop_reason: string | null;
  waitlist: { id: string; position: number; status: string; offered_until: string | null } | null;
}
export interface Registration {
  id: string;
  student_id: string | null;
  student_name: string | null;
  registration_number: string | null;
  program_code: string | null;
  batch_code: string | null;
  section_name: string | null;
  department_code: string | null;
  term_id: string;
  term_name: string | null;
  term_number: number | null;
  window_name: string | null;
  status: string;
  total_credits: number;
  limits: { min: number; max: number; normal: number; overridden: boolean } | null;
  items: RegItem[];
  fee: { ref: string; amount_paise: number; status: string } | null;
  submitted_at: string | null;
  approved_at: string | null;
  locked_at: string | null;
  workflow_instance_id: string | null;
  advisor_comment: string | null;
  overrides: Record<string, unknown> | null;
  checks: { key: string; label: string; passed: boolean; detail?: string | null }[];
  warnings?: string[];
}
export interface RegistrationListItem {
  id: string;
  student_id: string | null;
  student_name: string | null;
  registration_number: string | null;
  program_code: string | null;
  batch_code: string | null;
  section_name: string | null;
  term_name: string | null;
  status: string;
  total_credits: number;
  items_count: number;
  waitlisted_count: number;
  submitted_at: string | null;
}
export interface AllocationSummary {
  run_id: string | null;
  basket_code: string | null;
  mode: string;
  dry_run: boolean;
  candidates: number;
  allocated: number;
  unallocated: number;
  per_course: { code: string; allocated: number; seats: number }[];
  results: {
    form_id: string;
    student_name: string | null;
    registration_number: string | null;
    rank: number;
    sort_key: string | null;
    allocated_course_code: string | null;
    choice_number: number | null;
    status: string;
  }[];
}
export interface Arrear {
  id: string;
  student_id: string | null;
  student_name: string | null;
  registration_number: string | null;
  program_code: string | null;
  batch_code: string | null;
  course_code: string | null;
  course_title: string | null;
  credits: number;
  attempts: number;
  status: string;
}

export const label = (s: string | null | undefined) =>
  s ? s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) : '—';
export const rupees = (paise: number) => `₹${(paise / 100).toLocaleString('en-IN')}`;
export const OFFERING_STATUSES = ['planned', 'open', 'closed', 'in_progress', 'marks_entry', 'completed', 'cancelled'];
export const WINDOW_TYPES = ['regular', 'add_drop', 'late', 'arrear', 'summer', 'audit', 'minor_honours'];
export const REG_STATUSES = ['draft', 'submitted', 'advisor_pending', 'approved', 'changes_requested', 'rejected', 'locked'];
