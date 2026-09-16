/** Role slugs (docs/Roles_and_Permissions.md §1), modules/actions (§2), portal homes (Prompts/00 §4.6). */
export const ROLES = {
  SUPER_ADMIN: 'super_admin',
  SUPPORT_AGENT: 'support_agent',
  INSTITUTION_ADMIN: 'institution_admin',
  VICE_CHANCELLOR: 'vice_chancellor',
  REGISTRAR: 'registrar',
  CONTROLLER_OF_EXAMINATIONS: 'controller_of_examinations',
  EXAM_CELL: 'exam_cell',
  EXAM_DECODER: 'exam_decoder',
  DEAN: 'dean',
  HOD: 'hod',
  CLASS_ADVISOR: 'class_advisor',
  FACULTY: 'faculty',
  GUEST_FACULTY: 'guest_faculty',
  EXTERNAL_EXAMINER: 'external_examiner',
  INVIGILATOR: 'invigilator',
  RESEARCH_GUIDE: 'research_guide',
  RESEARCH_SCHOLAR: 'research_scholar',
  RESEARCH_CELL: 'research_cell',
  IQAC_COORDINATOR: 'iqac_coordinator',
  OBE_COORDINATOR: 'obe_coordinator',
  ADMISSIONS_OFFICER: 'admissions_officer',
  ACCOUNTANT: 'accountant',
  HR_OFFICER: 'hr_officer',
  PLACEMENT_OFFICER: 'placement_officer',
  ALUMNI_COORDINATOR: 'alumni_coordinator',
  HOSTEL_WARDEN: 'hostel_warden',
  HOSTEL_GATE_STAFF: 'hostel_gate_staff',
  LIBRARIAN: 'librarian',
  TRANSPORT_MANAGER: 'transport_manager',
  INVENTORY_MANAGER: 'inventory_manager',
  ESTATE_OFFICER: 'estate_officer',
  SECURITY_OFFICER: 'security_officer',
  MEDICAL_OFFICER: 'medical_officer',
  SPORTS_OFFICER: 'sports_officer',
  GRIEVANCE_OFFICER: 'grievance_officer',
  DISCIPLINE_COMMITTEE: 'discipline_committee',
  COMMITTEE_SECRETARY: 'committee_secretary',
  LEGAL_OFFICER: 'legal_officer',
  PIO: 'pio',
  RECEPTIONIST: 'receptionist',
  DRIVER: 'driver',
  INTEGRATION_ADMIN: 'integration_admin',
  COLLEGE_ADMIN: 'college_admin',
  COLLEGE_EXAM_COORDINATOR: 'college_exam_coordinator',
  AUDITOR: 'auditor',
  RECRUITER: 'recruiter',
  LEARNER: 'learner',
  STUDENT: 'student',
  PARENT: 'parent',
  ALUMNI: 'alumni',
  APPLICANT: 'applicant',
} as const;
export type RoleSlug = (typeof ROLES)[keyof typeof ROLES];

export const MODULES = [
  'dashboard', 'institutions', 'colleges', 'faculties', 'departments', 'users', 'roles', 'features', 'sessions',
  'programs', 'regulations', 'curriculum', 'courses', 'batches', 'offerings', 'registration', 'timetable',
  'attendance', 'marks', 'projects', 'exams', 'results', 'degrees', 'obe', 'lms', 'admissions', 'students',
  'credit_transfers', 'faculty', 'hr', 'recruitment', 'leaves', 'payroll', 'research', 'phd', 'fees', 'scholarships',
  'no_dues', 'hostel', 'library', 'transport', 'inventory', 'procurement', 'accounting', 'events', 'facilities',
  'health', 'sports', 'placement', 'alumni', 'fundraising', 'mentoring', 'grievances', 'discipline', 'surveys',
  'clubs', 'accreditation', 'governance', 'legal', 'rti', 'efile', 'affiliation', 'communication', 'calendar',
  'templates', 'certificates', 'reports', 'analytics', 'audit_logs', 'settings', 'integrations', 'jobs', 'website',
] as const;
export type ModuleName = (typeof MODULES)[number];

export const ACTIONS = {
  VIEW: 'view',
  VIEW_ALL: 'view_all',
  CREATE: 'create',
  UPDATE: 'update',
  DELETE: 'delete',
  APPROVE: 'approve',
  PUBLISH: 'publish',
  EXPORT: 'export',
  MANAGE: 'manage',
  VIEW_PII: 'view_pii',
} as const;

/** Portal-only roles are bounced from the admin shell to their portal home (AdminShellRoute / PortalRoute). */
export const PORTAL_HOME: Partial<Record<RoleSlug, string>> = {
  student: '/student',
  learner: '/student',
  parent: '/parent',
  faculty: '/faculty',
  guest_faculty: '/faculty',
  alumni: '/alumni',
  hostel_warden: '/warden',
  hostel_gate_staff: '/warden/gate',
  driver: '/driver',
  external_examiner: '/evaluator',
  research_scholar: '/scholar',
  recruiter: '/recruiter',
  applicant: '/apply',
};
export const PORTAL_ONLY_ROLES = Object.keys(PORTAL_HOME) as RoleSlug[];

export const GENDER = [
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'other', label: 'Other' },
  { value: 'undisclosed', label: 'Prefer not to say' },
] as const;

/** Reservation categories come from the regulatory pack via GET /public/config (Phase 01); this is the IN default. */
export const CATEGORY_FALLBACK = ['GEN', 'EWS', 'OBC-NCL', 'OBC-CL', 'SC', 'ST'] as const;

export const BLOOD_GROUP = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'] as const;

export const PAGE_SIZES = [10, 25, 50, 100, 200] as const;
export const DEFAULT_PAGE_SIZE = 25;
export const MAX_PAGE_SIZE = 200;
