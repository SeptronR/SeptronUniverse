/** Programmes, regulations & curriculum (Prompts/05 §05.4). Decimals (credits, durations) arrive as strings. */
export type Num = string | number;

export const PROGRAM_LEVELS = ['certificate', 'diploma', 'ug', 'pg', 'pg_diploma', 'integrated', 'mphil', 'phd'] as const;
export const PROGRAM_MODES = ['regular', 'part_time', 'distance', 'online'] as const;
export const TERM_PATTERNS = ['semester', 'year', 'trimester'] as const;
export const COURSE_TYPES = [
  'core', 'program_elective', 'open_elective', 'lab', 'integrated_lab', 'project', 'internship', 'seminar', 'mooc',
  'audit', 'mandatory_non_credit', 'ability_enhancement', 'skill_enhancement', 'value_added', 'minor', 'honours',
] as const;
export const COURSE_STATUSES = ['draft', 'approved', 'active', 'retired'] as const;
export const BASKET_TYPES = ['program_elective', 'open_elective', 'minor', 'honours', 'mooc', 'vertical'] as const;
export const ALLOCATION_MODES = ['priority_cgpa', 'fcfs', 'lottery', 'manual'] as const;
export const COMPONENT_CATEGORIES = ['cia', 'ese_theory', 'ese_practical', 'viva', 'project_review'] as const;
export const CREDIT_BUCKETS = ['HS', 'BS', 'ES', 'PC', 'PE', 'OE', 'EEC', 'MC', 'VAC', 'AEC', 'SEC'] as const;

export interface Program {
  id: string;
  college_id: string;
  faculty_id: string | null;
  department_id: string;
  code: string;
  name: string;
  degree_name: string;
  specialization: string | null;
  level: string;
  mode: string;
  term_pattern: string;
  duration_years: Num;
  total_terms: number;
  max_duration_years: Num | null;
  sanctioned_intake: number | null;
  lateral_intake: number | null;
  approving_body: string | null;
  exam_authority: string;
  is_nep_multidisciplinary: boolean;
  is_open_enrolment: boolean;
  status: string;
  version: number;
  college_code: string | null;
  department_code: string | null;
  can_edit: boolean;
}

export interface Regulation {
  id: string;
  college_id: string | null;
  code: string;
  name: string;
  effective_from_admission_year: number;
  grading_scale_id: string | null;
  rules: Record<string, unknown>;
  status: 'draft' | 'approved' | 'active' | 'superseded';
  approved_by: string | null;
  approved_at: string | null;
  locked_at: string | null;
  superseded_by_id: string | null;
  version: number;
  created_at: string;
  course_count: number;
  program_count: number;
  predecessor_id: string | null;
  workflow_instance_id: string | null;
  rules_locked: boolean;
  structure_locked: boolean;
}

export interface RulesHelpItem {
  key: string;
  default: unknown;
  description: string;
}

export interface ProgramRegulation {
  id: string;
  program_id: string;
  regulation_id: string;
  rules_override: Record<string, unknown> | null;
  total_credits_required: Num;
  status: string;
  version: number;
  program_code: string | null;
  program_name: string | null;
  regulation_code: string | null;
  regulation_status: string | null;
  total_terms: number | null;
}

export interface Prerequisite {
  id: string;
  related_course_id: string;
  relation: 'prerequisite' | 'corequisite' | 'antirequisite';
  min_grade: string | null;
  is_hard: boolean;
  related_code: string | null;
  related_title: string | null;
}

export interface SyllabusUnit {
  unit: number;
  title: string;
  topics: string[];
  hours?: number | null;
}

export interface Course {
  id: string;
  regulation_id: string;
  department_id: string;
  college_id: string | null;
  code: string;
  title: string;
  short_title: string | null;
  course_type: string;
  lecture_hours: number;
  tutorial_hours: number;
  practical_hours: number;
  credits: Num;
  contact_hours_per_week: number | null;
  assessment_scheme_id: string | null;
  cia_max: number | null;
  ese_max: number | null;
  is_credit_bearing: boolean;
  is_gradable: boolean;
  syllabus: SyllabusUnit[] | null;
  textbooks: string[] | null;
  is_public_catalog: boolean;
  status: string;
  version: number;
  regulation_code: string | null;
  regulation_status: string | null;
  department_code: string | null;
  scheme_code: string | null;
  ltpc: string | null;
  can_edit: boolean;
  prerequisites: Prerequisite[];
}

export interface StructureTerm {
  id?: string;
  term_number: number;
  name: string;
  min_credits: Num;
  normal_credits: Num;
  max_credits: Num;
  is_exit_point: boolean;
  exit_award: string | null;
}

export interface CurriculumCourse {
  id?: string;
  term_number: number;
  course_id: string;
  basket_code: string | null;
  is_mandatory: boolean;
  credit_bucket: string | null;
  sequence: number;
  course_code?: string | null;
  course_title?: string | null;
  course_type?: string | null;
  credits?: Num | null;
  ltpc?: string | null;
}

export interface BasketCourse {
  course_id: string;
  offering_department_id: string | null;
  code: string | null;
  title: string | null;
  credits: Num | null;
}

export interface Basket {
  id: string;
  program_regulation_id: string;
  code: string;
  name: string;
  basket_type: string;
  term_number: number | null;
  min_choose: number;
  max_choose: number;
  credits_required: Num | null;
  allocation_mode: string;
  version: number;
  courses: BasketCourse[];
}

export interface Structure {
  program_regulation_id: string;
  program_id: string;
  regulation_id: string;
  regulation_status: string;
  total_terms: number;
  term_pattern: string;
  total_credits_required: Num;
  version: number;
  locked: boolean;
  terms: StructureTerm[];
  courses: CurriculumCourse[];
  baskets: Basket[];
  exit_points: { after_term: number; award: string; min_credits: number }[];
}

export interface StructureIssue {
  code: string;
  severity: 'error' | 'warning';
  message: string;
  term_number: number | null;
  course_id: string | null;
}

export interface StructureValidation {
  program_regulation_id: string;
  credit_totals_by_term: Record<string, Num>;
  mandatory_credits: Num;
  basket_credits: Num;
  total: Num;
  required: Num;
  issues: StructureIssue[];
  valid: boolean;
}

export interface RegulationDiff {
  regulation_id: string;
  regulation_code: string;
  predecessor_id: string | null;
  predecessor_code: string | null;
  added: { code: string; title: string; credits: Num; course_type: string }[];
  removed: { code: string; title: string; credits: Num; course_type: string }[];
  changed: { code: string; title: string; fields: Record<string, { old: unknown; new: unknown }> }[];
  rules_changed: Record<string, { old: unknown; new: unknown }>;
  unchanged_count: number;
}

export interface GradeRange {
  grade: string;
  min_pct: number;
  max_pct: number | null;
  points: number;
  is_fail?: boolean | null;
}

export interface GradingScale {
  id: string;
  regulation_id: string | null;
  name: string;
  scale_type: string;
  ranges: GradeRange[];
  special_grades: { grade: string; meaning: string }[] | null;
  max_grade_point: Num;
  is_default: boolean;
  version: number;
}

export interface AssessmentComponent {
  id?: string;
  code: string;
  name: string;
  category: string;
  max_marks: number;
  scaled_to: Num | null;
  weight_pct?: Num | null;
  best_of?: { take: number; of: number; group?: string | null } | null;
  sequence: number;
  is_mandatory?: boolean;
  co_mappable?: boolean;
}

export interface AssessmentScheme {
  id: string;
  regulation_id: string;
  code: string;
  name: string;
  applies_to_course_types: string[];
  cia_weight: number;
  ese_weight: number;
  cia_max: number;
  ese_max: number;
  pass_rules: Record<string, number>;
  is_default: boolean;
  version: number;
  components: AssessmentComponent[];
  regulation_code: string | null;
}

export interface BatchSection {
  id: string;
  batch_id: string;
  name: string;
  capacity: number | null;
  class_advisor_staff_id: string | null;
  class_advisor_user_id: string | null;
  class_advisor_name: string | null;
  is_active: boolean;
}

export interface Batch {
  id: string;
  college_id: string;
  program_id: string;
  program_regulation_id: string;
  admission_year: number;
  entry_type: string;
  code: string;
  name: string | null;
  expected_graduation_year: number | null;
  current_term_number: number;
  status: string;
  version: number;
  sections: BatchSection[];
  program_code: string | null;
  regulation_code: string | null;
}

export interface PublicCourse {
  code: string;
  title: string;
  course_type: string;
  credits: Num;
  lecture_hours: number;
  tutorial_hours: number;
  practical_hours: number;
  term_number: number | null;
  regulation: string;
  department: string | null;
  syllabus: SyllabusUnit[] | null;
  textbooks: string[] | null;
}

export interface PublicProgram {
  code: string;
  name: string;
  degree_name: string;
  specialization: string | null;
  level: string;
  mode: string;
  duration_years: Num;
  total_terms: number;
  sanctioned_intake: number | null;
  college: string;
  college_name: string | null;
  department: string | null;
  regulation: string | null;
  total_credits: Num | null;
  courses: PublicCourse[];
}

export const num = (v: Num | null | undefined): number => (v === null || v === undefined || v === '' ? 0 : Number(v));
export const label = (s: string) => s.replace(/_/g, ' ');
