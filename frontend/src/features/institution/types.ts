/** Institution structure, academic sessions and settings types (Prompts/03 §03.4 — mirrors app/schemas/*.py). */

export interface InstitutionProfile {
  id: string;
  name: string;
  short_name: string | null;
  slug: string;
  code: string | null;
  institution_type: string;
  regulatory_pack: string;
  timezone: string;
  locale: string;
  currency: string;
  parent_university_name: string | null;
  aishe_code: string | null;
  aicte_pid: string | null;
  naac_id: string | null;
  ugc_status: string | null;
  gstin: string | null;
  address: Record<string, string> | null;
  contact: Record<string, string> | null;
  logo_url: string | null;
  website_url: string | null;
  status: string;
  version: number;
  established_year: number | null;
  vision: string | null;
  mission: string | null;
  head_title: string | null;
  head_name: string | null;
  head_signature_url: string | null;
  seal_url: string | null;
  letterhead_url: string | null;
  updated_at: string;
}

export interface College {
  id: string;
  institution_id: string;
  code: string;
  name: string;
  slug: string | null;
  college_type: string;
  affiliation_number: string | null;
  affiliated_since: string | null;
  principal_staff_id: string | null;
  exam_centre_code: string | null;
  is_exam_centre: boolean;
  aishe_code: string | null;
  aicte_pid: string | null;
  gstin: string | null;
  logo_url: string | null;
  timezone: string | null;
  is_main: boolean;
  is_active: boolean;
  version: number;
  department_count: number;
  can_edit: boolean;
}

export interface Faculty {
  id: string;
  college_id: string;
  code: string;
  name: string;
  dean_user_id: string | null;
  dean_name: string | null;
  version: number;
  department_count: number;
}

export interface Department {
  id: string;
  college_id: string;
  faculty_id: string | null;
  code: string;
  name: string;
  department_type: string;
  hod_staff_id: string | null;
  hod_user_id: string | null;
  hod_name: string | null;
  established_year: number | null;
  description: string | null;
  version: number;
  college_code: string | null;
  faculty_code: string | null;
}

export interface TermBrief {
  id: string;
  name: string;
  term_type: string;
  sequence: number;
  start_date: string;
  end_date: string;
  status: string;
  is_current: boolean;
}

export interface AcademicYear {
  id: string;
  college_id: string | null;
  name: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  is_locked: boolean;
  version: number;
  terms: TermBrief[];
}

export interface TermCloseCheck {
  key: string;
  label: string;
  passed: boolean;
  detail: string | null;
}

export interface AcademicTerm extends TermBrief {
  college_id: string | null;
  academic_year_id: string;
  academic_year_name: string | null;
  registration_start: string | null;
  registration_end: string | null;
  add_drop_end: string | null;
  last_instruction_date: string | null;
  is_locked: boolean;
  version: number;
  next_status: string | null;
  blocking_checks: TermCloseCheck[];
}

export interface RolloverTerm {
  name: string;
  term_type: string;
  sequence: number;
  start_date: string;
  end_date: string;
}

export interface RolloverPayload {
  new_year_name: string;
  start_date: string;
  end_date: string;
  terms: RolloverTerm[];
  promote_batches: boolean;
  college_id?: string | null;
  lock_previous?: boolean;
}

export interface Holiday {
  id: string;
  college_id: string | null;
  name: string;
  holiday_date: string;
  end_date: string | null;
  holiday_type: string;
  applies_to: string;
}

export interface HolidayBulkResult {
  succeeded: number;
  created: Holiday[];
  failed: { index: number; code: string; message: string }[];
}

export interface NumberSequence {
  id: string;
  college_id: string | null;
  scope_key: string;
  pattern: string;
  next_value: number;
  padding: number;
  reset_policy: string;
  sample: string | null;
}

export interface SettingItem {
  category: string;
  key: string;
  value: unknown;
  value_type: 'str' | 'int' | 'bool' | 'list' | 'json' | 'enum';
  is_public: boolean;
  default: unknown;
  is_default: boolean;
  choices: string[];
  label: string | null;
  feature: string | null;
}

export interface SettingsCategory {
  category: string;
  items: SettingItem[];
}

export interface PlatformInstitution {
  id: string;
  name: string;
  short_name: string | null;
  slug: string;
  code: string | null;
  institution_type: string;
  regulatory_pack: string;
  timezone: string;
  status: string;
  created_at: string;
  college_count: number;
  user_count: number;
  plan_code: string | null;
  subscription_status: string | null;
}

export interface OnboardingPayload {
  institution: {
    name: string;
    short_name?: string;
    slug: string;
    code?: string;
    institution_type: string;
    timezone: string;
  };
  admin: { username: string; email: string; display_name: string; phone?: string };
  plan_code: string;
  pack: string;
  seed_demo: boolean;
}

export interface OnboardingResult {
  institution: InstitutionProfile;
  main_college_id: string | null;
  roles_created: number;
  defaults: Record<string, unknown>;
  plan_code: string;
  features_enabled: number;
  admin_user_id: string;
  admin_username: string;
  admin_temp_password: string;
  demo_job_id: string | null;
}

export const INSTITUTION_TYPES = [
  'university',
  'deemed_university',
  'autonomous_college',
  'affiliated_college',
  'standalone_college',
  'multi_campus',
] as const;
export const COLLEGE_TYPES = ['constituent', 'affiliated', 'autonomous', 'campus', 'deemed_unit', 'study_centre', 'main'] as const;
export const DEPARTMENT_TYPES = ['academic', 'administrative', 'research_centre'] as const;
export const TERM_TYPES = ['odd', 'even', 'summer', 'trimester', 'annual'] as const;
export const TERM_STATUSES = ['planned', 'registration', 'in_progress', 'exam', 'result_processing', 'closed'] as const;
export const HOLIDAY_TYPES = ['public', 'institution', 'restricted', 'exam_break'] as const;
