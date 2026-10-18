import {
  Activity,
  ArrowRightLeft,
  Ban,
  Repeat,
  TrendingUp,
  Banknote,
  Briefcase,
  CalendarCheck,
  ClipboardCheck,
  Clock,
  Gauge,
  HandCoins,
  Contact,
  UserRound,
  BookOpen,
  GraduationCap,
  Percent,
  ScrollText,
  UsersRound,
  BellRing,
  CheckSquare,
  GitBranch,
  Megaphone,
  MessagesSquare,
  Building,
  Building2,
  CalendarDays,
  CalendarRange,
  Hash,
  Landmark,
  Settings,
  CreditCard,
  LayoutDashboard,
  LifeBuoy,
  ShieldCheck,
  ToggleLeft,
  Users,
  type LucideIcon,
} from 'lucide-react';

/**
 * Sidebar navigation (Prompts/00 §4.5). Items are gated by `can(module, action ?? 'view') || canAny(altActions)`
 * and `useFeature(feature)`. Phases append `{ label, to, icon, module, action?, feature? }` under their group.
 */
export type NavItem = {
  label: string;
  to: string;
  icon: LucideIcon;
  module: string;
  action?: string;
  altActions?: string[];
  feature?: string;
  roles?: string[];
  /** live counter shown next to the label (Phase 04: `approvals` = pending approvals inbox) */
  badge?: 'approvals';
};

export type NavGroup = { title: string; items: NavItem[] };

export const NAV_GROUPS: NavGroup[] = [
  {
    title: 'MAIN',
    items: [
      { label: 'Dashboard', to: '/dashboard', icon: LayoutDashboard, module: 'dashboard' },
      // Phase 01 — platform services
      { label: 'Background jobs', to: '/jobs', icon: Activity, module: 'jobs', feature: 'core.background_jobs' },
      { label: 'Help centre', to: '/help', icon: LifeBuoy, module: 'dashboard', feature: 'platform.help_center' },
      // Phase 04 — approvals inbox (every signed-in user; the badge counts pending steps)
      { label: 'Approvals', to: '/approvals', icon: CheckSquare, module: 'dashboard', feature: 'workflow.engine', badge: 'approvals' },
      { label: 'Notifications', to: '/notifications', icon: BellRing, module: 'dashboard', feature: 'core.notifications_inapp' },
      // Phase 06 — my space (own profile, leaves, attendance, payslips)
      { label: 'My Space', to: '/me', icon: UserRound, module: 'hr', feature: 'hr.staff' },
    ],
  },
  {
    title: 'ACADEMICS',
    items: [
      // Phase 05 — programmes, regulations & curriculum
      { label: 'Programmes', to: '/admin/academics/programs', icon: GraduationCap, module: 'programs', feature: 'academics.programs' },
      { label: 'Regulations', to: '/admin/academics/regulations', icon: ScrollText, module: 'regulations', feature: 'academics.regulations' },
      { label: 'Courses', to: '/admin/academics/courses', icon: BookOpen, module: 'courses', feature: 'academics.regulations' },
      {
        label: 'Grading & Schemes',
        to: '/admin/academics/grading',
        icon: Percent,
        module: 'regulations',
        feature: 'academics.regulations',
      },
      { label: 'Batches', to: '/admin/academics/batches', icon: UsersRound, module: 'batches', feature: 'academics.programs' },
      // Phase 09 — offerings, registration, windows, elective allocation, arrears
      { label: 'Offerings', to: '/admin/academics/offerings', icon: BookOpen, module: 'offerings', feature: 'registration.core' },
      { label: 'Registration', to: '/admin/registration', icon: ClipboardCheck, module: 'registration', altActions: ['view_all', 'approve'], feature: 'registration.core' },
      { label: 'Windows', to: '/admin/registration/windows', icon: CalendarRange, module: 'registration', action: 'manage', feature: 'registration.core' },
      { label: 'Elective allocation', to: '/admin/registration/allocation', icon: Percent, module: 'registration', action: 'allocate', altActions: ['manage'], feature: 'registration.elective_allocation' },
      { label: 'Arrears', to: '/admin/registration/arrears', icon: ScrollText, module: 'registration', altActions: ['view_all', 'approve'], feature: 'registration.arrears' },
      // Phase 11 — attendance
      { label: 'Attendance', to: '/admin/attendance', icon: ClipboardCheck, module: 'attendance', altActions: ['view_all'], feature: 'attendance.core' },
      { label: 'On-duty requests', to: '/admin/attendance/od', icon: ClipboardCheck, module: 'attendance', action: 'condone', altActions: ['view_all', 'edit_finalized'], feature: 'attendance.on_duty' },
      { label: 'Condonations', to: '/admin/attendance/condonations', icon: ClipboardCheck, module: 'attendance', action: 'condone', altActions: ['view_all'], feature: 'attendance.condonation' },
      // Phase 10 — timetable & rooms
      { label: 'Timetable', to: '/admin/timetable', icon: CalendarRange, module: 'timetable', altActions: ['view_all'], feature: 'timetable.core' },
      { label: 'Rooms & Slots', to: '/admin/facilities/rooms', icon: Building2, module: 'timetable', altActions: ['view_all'], feature: 'timetable.rooms' },
      { label: 'Substitutions', to: '/admin/timetable/substitutions', icon: Repeat, module: 'timetable', action: 'substitute', altActions: ['approve', 'manage'], feature: 'timetable.substitutions' },
      { label: 'Sessions', to: '/admin/timetable/sessions', icon: Clock, module: 'attendance', altActions: ['view_all', 'mark'], feature: 'timetable.core' },
    ],
  },
  {
    title: 'EXAMINATIONS',
    items: [
      // Phase 11 — eligibility snapshots / detention (Phase 14 joins this group)
      // Phase 13 — marks verification (HOD) and locks (exam cell)
      { label: 'Marks verification', to: '/admin/assessment/verification', icon: ClipboardCheck, module: 'marks', action: 'verify', altActions: [], feature: 'assessment.marks_workflow' },
      { label: 'Marks locks', to: '/admin/assessment/locks', icon: ClipboardCheck, module: 'marks', action: 'lock', altActions: [], feature: 'assessment.marks_workflow' },
      { label: 'Eligibility', to: '/admin/attendance/eligibility', icon: ClipboardCheck, module: 'exams', action: 'eligibility', altActions: [], feature: 'attendance.eligibility_detention' },
    ],
  },
  {
    title: 'ADMISSIONS',
    items: [
      // Phase 08 — cycles, applicants, verification, merit & counselling (cycle workspace tabs), enquiries
      { label: 'Cycles', to: '/admin/admissions/cycles', icon: CalendarRange, module: 'admissions', feature: 'admissions.cycles' },
      { label: 'Applicants', to: '/admin/admissions/applicants', icon: UserRound, module: 'admissions', action: 'view_all', feature: 'admissions.cycles' },
      { label: 'Verification', to: '/admin/admissions/verification', icon: ClipboardCheck, module: 'admissions', action: 'verify', feature: 'admissions.document_verification' },
      { label: 'Merit & Counselling', to: '/admin/admissions/cycles?focus=counselling', icon: ScrollText, module: 'admissions', action: 'merit', altActions: ['allot'], feature: 'admissions.merit_lists' },
      { label: 'Enquiries', to: '/admin/admissions/enquiries', icon: MessagesSquare, module: 'admissions', feature: 'admissions.enquiry_crm' },
    ],
  },
  {
    title: 'STUDENTS',
    items: [
      // Phase 07 — students, enrolment, holds, standing
      { label: 'Students', to: '/admin/students', icon: GraduationCap, module: 'students', altActions: ['view_all'], feature: 'students.core' },
      { label: 'Promotion', to: '/admin/students/promotion', icon: TrendingUp, module: 'batches', action: 'promote', feature: 'students.core' },
      {
        label: 'Holds',
        to: '/admin/students/holds',
        icon: Ban,
        module: 'students',
        action: 'holds',
        altActions: ['view_all'],
        feature: 'students.holds',
      },
      {
        label: 'Transfers',
        to: '/admin/students/transfers',
        icon: ArrowRightLeft,
        module: 'students',
        action: 'transfer',
        feature: 'students.transfers_migration',
      },
      {
        label: 'Credit transfers',
        to: '/admin/students/credit-transfers',
        icon: Repeat,
        module: 'credit_transfers',
        action: 'verify',
        altActions: ['approve'],
        feature: 'academics.credit_transfer_mooc',
      },
    ],
  },
  {
    title: 'PEOPLE',
    items: [
      // Phase 06 — staff, leaves, attendance, payroll, recruitment, appraisal & CAS, workload
      { label: 'Staff', to: '/admin/hr/staff', icon: Contact, module: 'hr', action: 'view_all', feature: 'hr.staff' },
      { label: 'Leaves', to: '/admin/hr/leaves', icon: CalendarCheck, module: 'leaves', altActions: ['view_all'], feature: 'hr.leaves' },
      {
        label: 'Staff Attendance',
        to: '/admin/hr/attendance',
        icon: Clock,
        module: 'attendance',
        action: 'staff_view_all',
        altActions: ['staff_self'],
        feature: 'attendance.staff',
      },
      { label: 'Payroll', to: '/admin/hr/payroll', icon: Banknote, module: 'payroll', action: 'view_all', altActions: ['view', 'generate'], feature: 'hr.payroll' },
      { label: 'Loans', to: '/admin/hr/loans', icon: HandCoins, module: 'payroll', action: 'self', altActions: ['view_all'], feature: 'hr.loans_advances' },
      { label: 'Recruitment', to: '/admin/hr/recruitment', icon: Briefcase, module: 'hr', action: 'recruitment', feature: 'hr.recruitment' },
      { label: 'Appraisals & CAS', to: '/admin/hr/appraisals', icon: ClipboardCheck, module: 'hr', feature: 'hr.appraisal_pbas' },
      { label: 'Workload', to: '/admin/hr/workload', icon: Gauge, module: 'faculty', action: 'workload_manage', altActions: ['view_all'], feature: 'hr.workload' },
    ],
  },
  { title: 'CAMPUS', items: [] },
  {
    title: 'FINANCE',
    items: [
      // Phase 12 — fees, scholarships & no-dues
      { label: 'Fees', to: '/admin/fees', icon: Banknote, module: 'fees', action: 'view_all', altActions: ['collect'], feature: 'fees.core' },
      { label: 'Collect', to: '/admin/fees/collect', icon: HandCoins, module: 'fees', action: 'collect', altActions: [], feature: 'fees.core' },
      { label: 'Structures', to: '/admin/fees/structures', icon: ScrollText, module: 'fees', action: 'structure_manage', altActions: ['view_all'], feature: 'fees.core' },
      { label: 'Discounts', to: '/admin/fees/discounts', icon: Percent, module: 'fees', action: 'concession', altActions: ['approve'], feature: 'fees.discounts' },
      { label: 'Fines', to: '/admin/fees/fines', icon: Ban, module: 'fees', action: 'structure_manage', altActions: [], feature: 'fees.fines' },
      { label: 'Invoices', to: '/admin/fees/invoices', icon: ScrollText, module: 'fees', action: 'view_all', altActions: ['view', 'collect'], feature: 'fees.core' },
      { label: 'Payments', to: '/admin/fees/payments', icon: Banknote, module: 'fees', action: 'view_all', altActions: ['collect', 'cancel_receipt'], feature: 'fees.core' },
      { label: 'Gateway orders', to: '/admin/fees/online', icon: Activity, module: 'fees', action: 'view_all', altActions: ['collect'], feature: 'fees.online_payment' },
      { label: 'Reconciliation', to: '/admin/fees/reconcile', icon: ArrowRightLeft, module: 'fees', action: 'reconcile', altActions: [], feature: 'fees.offline_challan_reconciliation' },
      { label: 'Day-book', to: '/admin/fees/day-book', icon: CalendarCheck, module: 'fees', action: 'view_all', altActions: ['collect'], feature: 'fees.core' },
      { label: 'Refunds', to: '/admin/fees/refunds', icon: Repeat, module: 'fees', action: 'refund', altActions: ['approve', 'view_all'], feature: 'fees.refunds' },
      { label: 'Scholarships', to: '/admin/fees/scholarships', icon: GraduationCap, module: 'scholarships', action: 'view_all', altActions: ['verify', 'approve', 'sanction', 'disburse'], feature: 'fees.scholarships' },
      { label: 'No-dues', to: '/admin/fees/no-dues', icon: ClipboardCheck, module: 'no_dues', action: 'approve', altActions: ['view_all'], feature: 'fees.no_dues' },
      { label: 'Reports', to: '/admin/fees/reports', icon: TrendingUp, module: 'fees', action: 'view_all', altActions: ['export'], feature: 'fees.core' },
    ],
  },
  { title: 'ENGAGEMENT', items: [] },
  {
    title: 'QUALITY & GOVERNANCE',
    items: [
      // Phase 13 — OBE definitions
      { label: 'OBE definitions', to: '/admin/obe/programs', icon: ScrollText, module: 'obe', action: 'manage', altActions: ['view', 'view_all'], feature: 'obe.definitions' },
    ],
  },
  {
    title: 'COMMUNICATION',
    items: [
      // Phase 04 — communication core
      {
        label: 'Communications',
        to: '/admin/communications',
        icon: MessagesSquare,
        module: 'communication',
        action: 'view_all',
        altActions: ['template_manage', 'send', 'create'],
        feature: 'core.notifications_inapp',
      },
      { label: 'Announcements', to: '/announcements', icon: Megaphone, module: 'communication', feature: 'comms.announcements' },
    ],
  },
  {
    title: 'ADMIN',
    items: [
      // Phase 03 — institution structure, academic sessions, settings
      { label: 'Institution', to: '/admin/institution', icon: Landmark, module: 'institutions', feature: 'core.institution' },
      { label: 'Colleges', to: '/admin/colleges', icon: Building2, module: 'institutions', feature: 'core.institution' },
      { label: 'Departments', to: '/admin/departments', icon: Building, module: 'institutions', feature: 'core.institution' },
      {
        label: 'Academic Years',
        to: '/admin/academic-years',
        icon: CalendarRange,
        module: 'sessions',
        altActions: ['manage'],
        feature: 'core.institution',
      },
      { label: 'Holidays', to: '/admin/holidays', icon: CalendarDays, module: 'institutions', feature: 'institution.holidays' },
      { label: 'Settings', to: '/admin/settings', icon: Settings, module: 'settings', feature: 'core.settings' },
      {
        label: 'Number Sequences',
        to: '/admin/number-sequences',
        icon: Hash,
        module: 'settings',
        action: 'manage',
        feature: 'institution.number_sequences_custom',
      },
      { label: 'Workflows', to: '/admin/workflows', icon: GitBranch, module: 'settings', action: 'manage', feature: 'workflow.engine' },
      // super admin only (features:manage is platform-only): tenants + onboarding wizard
      {
        label: 'Tenants',
        to: '/super-admin/institutions',
        icon: Landmark,
        module: 'features',
        action: 'manage',
        feature: 'core.institution',
      },
      // Phase 02 — auth, RBAC, features, entitlements
      { label: 'Users', to: '/admin/users', icon: Users, module: 'users', action: 'view_all', feature: 'core.rbac' },
      { label: 'Roles', to: '/admin/roles', icon: ShieldCheck, module: 'roles', feature: 'core.rbac' },
      {
        label: 'Features',
        to: '/admin/settings/features',
        icon: ToggleLeft,
        module: 'features',
        action: 'institution_toggle',
        feature: 'core.settings',
      },
      {
        label: 'Entitlements',
        to: '/admin/settings/entitlements',
        icon: CreditCard,
        module: 'settings',
        feature: 'core.settings',
      },
    ],
  },
];
