import {
  Activity,
  Bus,
  MapPin,
  Radio,
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
      // Phase 15 — valuation (evaluators), result registers, legacy import (coding / valuation / runs live in the session workspace)
      { label: 'Valuation', to: '/faculty/evaluation', icon: ClipboardCheck, module: 'exams', action: 'evaluate', feature: 'exams.coding_dummy' },
      { label: 'Tabulation register', to: '/admin/results/tabulation', icon: ScrollText, module: 'results', action: 'view_all', feature: 'results.rank_lists' },
      { label: 'Result analysis', to: '/admin/results/analysis', icon: TrendingUp, module: 'results', action: 'view_all', feature: 'results.rank_lists' },
      { label: 'Rank lists', to: '/admin/results/rank-lists', icon: GraduationCap, module: 'results', action: 'view_all', feature: 'results.rank_lists' },
      { label: 'Legacy result import', to: '/admin/results/legacy-import', icon: Repeat, module: 'results', action: 'legacy_import', feature: 'results.legacy_import' },
      // Phase 14 — exam sessions (papers, date-sheet, registrations, hall tickets, seating, invigilation, QP, conduct)
      { label: 'Exam sessions', to: '/admin/exams/sessions', icon: CalendarCheck, module: 'exams', action: 'view_all', altActions: ['configure', 'manage', 'view'], feature: 'exams.sessions' },
      // Phase 13 — marks verification (HOD) and locks (exam cell)
      { label: 'Marks verification', to: '/admin/assessment/verification', icon: ClipboardCheck, module: 'marks', action: 'verify', altActions: [], feature: 'assessment.marks_workflow' },
      { label: 'Marks locks', to: '/admin/assessment/locks', icon: ClipboardCheck, module: 'marks', action: 'lock', altActions: [], feature: 'assessment.marks_workflow' },
      { label: 'Eligibility', to: '/admin/attendance/eligibility', icon: ClipboardCheck, module: 'exams', action: 'eligibility', altActions: [], feature: 'attendance.eligibility_detention' },
      // Phase 18 — degrees & convocation
      { label: 'Degree eligibility', to: '/admin/degrees/eligibility', icon: GraduationCap, module: 'degrees', action: 'view_all', altActions: ['manage', 'award'], feature: 'degrees.eligibility' },
      { label: 'Convocations', to: '/admin/degrees/convocations', icon: CalendarCheck, module: 'degrees', action: 'convocation_manage', altActions: ['view_all'], feature: 'degrees.convocation' },
      { label: 'Degree awards', to: '/admin/degrees/awards', icon: ScrollText, module: 'degrees', action: 'award', altActions: ['issue', 'view_all', 'create'], feature: 'degrees.certificates' },
      { label: 'Provisional certificates', to: '/admin/degrees/provisional', icon: ScrollText, module: 'degrees', action: 'issue', feature: 'degrees.provisional' },
      { label: 'Digital credentials', to: '/admin/degrees/credentials', icon: ShieldCheck, module: 'degrees', action: 'issue', feature: 'degrees.digilocker_nad' },
      { label: 'Graduation stats', to: '/admin/degrees/stats', icon: TrendingUp, module: 'degrees', action: 'view_all', feature: 'degrees.certificates' },
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
  {
    title: 'CAMPUS',
    items: [
      // Phase 19 — library
      { label: 'Library catalogue', to: '/admin/library/catalogue', icon: BookOpen, module: 'library', action: 'view_all', altActions: ['manage', 'circulate'], feature: 'library.core' },
      { label: 'Circulation', to: '/admin/library/circulation', icon: Repeat, module: 'library', action: 'circulate', altActions: ['manage'], feature: 'library.core' },
      { label: 'Library issues', to: '/admin/library/issues', icon: ClipboardCheck, module: 'library', action: 'view_all', altActions: ['manage', 'circulate'], feature: 'library.core' },
      { label: 'Reservations', to: '/admin/library/reservations', icon: Clock, module: 'library', action: 'circulate', altActions: ['manage'], feature: 'library.core' },
      { label: 'Library fines', to: '/admin/library/fines', icon: HandCoins, module: 'library', action: 'fines', altActions: ['manage'], feature: 'library.fines' },
      { label: 'Library members', to: '/admin/library/members', icon: UsersRound, module: 'library', action: 'view_all', altActions: ['manage'], feature: 'library.core' },
      { label: 'E-resources', to: '/admin/library/eresources', icon: Landmark, module: 'library', action: 'manage', feature: 'library.eresources' },
      { label: 'Inter-library loans', to: '/admin/library/ill', icon: ArrowRightLeft, module: 'library', action: 'manage', feature: 'library.inter_library_loan' },
      { label: 'Stock verification', to: '/admin/library/stock-verification', icon: ClipboardCheck, module: 'library', action: 'manage', feature: 'library.core' },
      { label: 'Library reports', to: '/admin/library/reports', icon: TrendingUp, module: 'library', action: 'view_all', altActions: ['manage'], feature: 'library.core' },
      // Phase 20 — hostel, mess, staff quarters
      { label: 'Hostels', to: '/admin/hostel/hostels', icon: Building2, module: 'hostel', action: 'view_all', altActions: ['manage', 'warden'], feature: 'hostel.core' },
      { label: 'Hostel applications', to: '/admin/hostel/applications', icon: ClipboardCheck, module: 'hostel', action: 'allot', altActions: ['view_all', 'warden'], feature: 'hostel.core' },
      { label: 'Hostel allocations', to: '/admin/hostel/allocations', icon: UsersRound, module: 'hostel', action: 'view_all', altActions: ['warden', 'allot', 'manage'], feature: 'hostel.core' },
      { label: 'Room changes', to: '/admin/hostel/room-changes', icon: Repeat, module: 'hostel', action: 'warden', altActions: ['manage'], feature: 'hostel.room_change' },
      { label: 'Night roll-call', to: '/admin/hostel/roll-call', icon: Clock, module: 'hostel', action: 'roll_call', altActions: ['warden', 'manage'], feature: 'hostel.night_roll_call' },
      { label: 'Mess', to: '/admin/hostel/mess', icon: HandCoins, module: 'hostel', action: 'mess_manage', altActions: ['warden', 'manage'], feature: 'hostel.mess' },
      { label: 'Visitors', to: '/admin/hostel/visitors', icon: Contact, module: 'hostel', action: 'gate', altActions: ['warden', 'manage', 'view_all'], feature: 'hostel.visitors' },
      { label: 'Leaves & out-pass', to: '/admin/hostel/leaves', icon: CalendarCheck, module: 'hostel', action: 'warden', altActions: ['gate', 'manage', 'view_all'], feature: 'hostel.leave_outpass' },
      { label: 'Hostel complaints', to: '/admin/hostel/complaints', icon: MessagesSquare, module: 'hostel', action: 'warden', altActions: ['manage', 'view_all'], feature: 'hostel.complaints' },
      { label: 'Hostel discipline', to: '/admin/hostel/discipline', icon: ShieldCheck, module: 'hostel', action: 'discipline', altActions: ['warden', 'manage', 'view_all'], feature: 'hostel.discipline' },
      { label: 'Staff quarters', to: '/admin/hostel/quarters', icon: Building, module: 'hostel', action: 'manage', altActions: ['view_all'], feature: 'hostel.staff_quarters' },
      { label: 'Hostel reports', to: '/admin/hostel/reports', icon: TrendingUp, module: 'hostel', action: 'view_all', altActions: ['warden', 'manage'], feature: 'hostel.core' },
      // Phase 16 — post-result services
      { label: 'Revaluation', to: '/admin/exams/revaluation', icon: Repeat, module: 'exams', action: 'reval', altActions: ['view_all'], feature: 'results.revaluation' },
      { label: 'Malpractice', to: '/admin/exams/malpractice', icon: ShieldCheck, module: 'exams', action: 'malpractice', altActions: ['view_all'], feature: 'results.malpractice' },
      { label: 'Withheld results', to: '/admin/results/withheld', icon: Ban, module: 'results', action: 'approve', altActions: ['view_all', 'manage'], feature: 'results.processing' },
      { label: 'Supplementary', to: '/admin/exams/supplementary', icon: CalendarRange, module: 'exams', action: 'manage', feature: 'results.supplementary' },
      { label: 'Transcripts', to: '/admin/results/transcripts', icon: ScrollText, module: 'results', action: 'transcript', altActions: ['manage'], feature: 'results.transcripts' },
      { label: 'Rank lists & medals', to: '/admin/results/medals', icon: GraduationCap, module: 'results', action: 'view_all', altActions: ['approve', 'manage'], feature: 'results.rank_lists' },
      { label: 'Result corrections', to: '/admin/results/corrections', icon: CheckSquare, module: 'results', action: 'verify', altActions: ['manage'], feature: 'results.processing' },
      { label: 'Detained & readmission', to: '/admin/students/detained', icon: UserRound, module: 'students', action: 'view_all', altActions: ['manage'], feature: 'results.processing' },
      // Phase 24 — communication advanced
      { label: 'Campaigns', to: '/admin/comms/campaigns', icon: Radio, module: 'communication', action: 'bulk', altActions: ['send', 'approve', 'manage'], feature: 'comms.bulk_campaigns' },
      { label: 'Audience segments', to: '/admin/comms/segments', icon: UserRound, module: 'communication', action: 'bulk', altActions: ['send', 'manage'], feature: 'comms.bulk_campaigns' },
      { label: 'Emergency broadcast', to: '/admin/comms/emergency', icon: Activity, module: 'communication', action: 'emergency', altActions: ['manage'], feature: 'comms.emergency_broadcast' },
      { label: 'WhatsApp bot', to: '/admin/comms/bot', icon: Repeat, module: 'communication', action: 'template_manage', altActions: ['bulk', 'manage'], feature: 'comms.whatsapp_bot' },
      { label: 'Delivery analytics', to: '/admin/comms/analytics', icon: TrendingUp, module: 'communication', action: 'bulk', altActions: ['approve', 'manage'], feature: 'comms.bulk_campaigns' },
      { label: 'Message simulator', to: '/admin/comms/simulator', icon: Radio, module: 'communication', action: 'manage', altActions: ['bulk'], feature: 'comms.bulk_campaigns' },
      // Phase 23 — accounting & budget
      { label: 'Finance dashboard', to: '/admin/accounting/dashboard', icon: LayoutDashboard, module: 'accounting', action: 'view_all', altActions: ['manage'], feature: 'accounting.core' },
      { label: 'Chart of accounts', to: '/admin/accounting/chart', icon: GitBranch, module: 'accounting', action: 'view_all', altActions: ['manage'], feature: 'accounting.core' },
      { label: 'Ledger', to: '/admin/accounting/ledger', icon: ScrollText, module: 'accounting', action: 'view_all', altActions: ['manage'], feature: 'accounting.core' },
      { label: 'Income', to: '/admin/accounting/income', icon: Banknote, module: 'accounting', action: 'post', altActions: ['view_all', 'manage'], feature: 'accounting.core' },
      { label: 'Expenses', to: '/admin/accounting/expenses', icon: CreditCard, module: 'accounting', action: 'post', altActions: ['view_all', 'approve', 'view'], feature: 'accounting.core' },
      { label: 'Budgets', to: '/admin/accounting/budgets', icon: Gauge, module: 'accounting', action: 'view_all', altActions: ['manage', 'approve'], feature: 'accounting.budgets' },
      { label: 'Department budget', to: '/admin/accounting/budgets/me', icon: Gauge, module: 'accounting', action: 'view', altActions: ['post'], feature: 'accounting.budgets' },
      { label: 'Grants', to: '/admin/accounting/grants', icon: Landmark, module: 'accounting', action: 'view_all', altActions: ['manage'], feature: 'accounting.grants_ledger' },
      { label: 'Reconciliation', to: '/admin/accounting/reconciliation', icon: CheckSquare, module: 'accounting', action: 'reconcile', altActions: ['view_all'], feature: 'accounting.core' },
      { label: 'GST', to: '/admin/accounting/gst', icon: Percent, module: 'accounting', action: 'view_all', altActions: ['manage'], feature: 'accounting.gst_reports' },
      { label: 'Voucher exports', to: '/admin/accounting/exports', icon: ArrowRightLeft, module: 'accounting', action: 'export', altActions: ['view_all'], feature: 'accounting.tally_export' },
      { label: 'Statements', to: '/admin/accounting/statements', icon: TrendingUp, module: 'accounting', action: 'view_all', altActions: ['manage'], feature: 'accounting.core' },
      { label: 'Periods', to: '/admin/accounting/periods', icon: CalendarRange, module: 'accounting', action: 'manage', feature: 'accounting.core' },
      // Phase 22 — inventory & procurement
      { label: 'Items', to: '/admin/inventory/items', icon: ClipboardCheck, module: 'inventory', action: 'view_all', altActions: ['manage', 'issue', 'receive'], feature: 'inventory.core' },
      { label: 'Stores', to: '/admin/inventory/stores', icon: Building, module: 'inventory', action: 'view_all', altActions: ['manage', 'issue', 'receive', 'approve_indent'], feature: 'inventory.core' },
      { label: 'Suppliers', to: '/admin/inventory/suppliers', icon: Contact, module: 'inventory', action: 'manage', altActions: [], feature: 'inventory.core' },
      { label: 'Indents', to: '/admin/inventory/indents', icon: ScrollText, module: 'inventory', action: 'view_all', altActions: ['indent', 'approve_indent', 'issue', 'manage'], feature: 'inventory.procurement' },
      { label: 'Quotations', to: '/admin/inventory/quotations', icon: Percent, module: 'procurement', action: 'quote', altActions: ['manage'], feature: 'inventory.procurement' },
      { label: 'Purchase orders', to: '/admin/inventory/purchase-orders', icon: Briefcase, module: 'procurement', action: 'view_all', altActions: ['po_approve', 'create'], feature: 'inventory.procurement' },
      { label: 'Goods receipts', to: '/admin/inventory/goods-receipts', icon: CheckSquare, module: 'inventory', action: 'receive', altActions: ['view_all', 'manage'], feature: 'inventory.procurement' },
      { label: 'Assets', to: '/admin/inventory/assets', icon: Hash, module: 'inventory', action: 'view_all', altActions: ['manage', 'asset_audit', 'approve_indent'], feature: 'inventory.assets' },
      { label: 'Asset audits', to: '/admin/inventory/audits', icon: ShieldCheck, module: 'inventory', action: 'asset_audit', altActions: ['manage', 'view_all'], feature: 'inventory.assets' },
      { label: 'Vendor bills', to: '/admin/inventory/bills', icon: Banknote, module: 'procurement', action: 'bill_approve', altActions: [], feature: 'inventory.bills' },
      { label: 'Campus store', to: '/admin/inventory/vendor-store', icon: HandCoins, module: 'inventory', action: 'issue', altActions: ['manage'], feature: 'inventory.vendor_store' },
      { label: 'Inventory reports', to: '/admin/inventory/reports', icon: TrendingUp, module: 'inventory', action: 'view_all', altActions: ['manage'], feature: 'inventory.core' },
      { label: 'Inventory settings', to: '/admin/inventory/settings', icon: Settings, module: 'inventory', action: 'manage', feature: 'inventory.core' },
      { label: 'My indents & assets', to: '/staff/indents', icon: UserRound, module: 'inventory', action: 'indent', feature: 'inventory.procurement' },
      // Phase 21 — transport
      { label: 'Fleet', to: '/admin/transport/fleet', icon: Bus, module: 'transport', action: 'view_all', altActions: ['manage'], feature: 'transport.core' },
      { label: 'Routes', to: '/admin/transport/routes', icon: MapPin, module: 'transport', action: 'view_all', altActions: ['manage'], feature: 'transport.core' },
      { label: 'Transport allocations', to: '/admin/transport/allocations', icon: UsersRound, module: 'transport', action: 'view_all', altActions: ['manage'], feature: 'transport.core' },
      { label: 'Trips', to: '/admin/transport/trips', icon: CalendarDays, module: 'transport', action: 'view_all', altActions: ['manage'], feature: 'transport.core' },
      { label: 'Live map', to: '/admin/transport/live', icon: Activity, module: 'transport', action: 'view_all', altActions: ['manage'], feature: 'transport.gps_live' },
      { label: 'GPS devices', to: '/admin/transport/devices', icon: Radio, module: 'transport', action: 'manage', feature: 'transport.gps_live' },
      { label: 'Transport reports', to: '/admin/transport/reports', icon: TrendingUp, module: 'transport', action: 'view_all', altActions: ['manage'], feature: 'transport.core' },
      { label: 'Transport settings', to: '/admin/transport/settings', icon: Settings, module: 'transport', action: 'manage', feature: 'transport.core' },
      { label: 'My transport', to: '/staff/transport', icon: Bus, module: 'transport', action: 'view', feature: 'transport.core' },
    ],
  },
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
      // Phase 17 — OBE attainment, trend, config, CQI, NBA export
      { label: 'OBE attainment', to: '/admin/obe/program-attainment', icon: TrendingUp, module: 'obe', action: 'view', altActions: ['view_all', 'manage'], feature: 'obe.attainment' },
      { label: 'Attainment trend', to: '/admin/obe/trend', icon: TrendingUp, module: 'obe', action: 'view', altActions: ['view_all', 'manage'], feature: 'obe.attainment' },
      { label: 'Attainment config', to: '/admin/obe/config', icon: Settings, module: 'obe', action: 'configure', feature: 'obe.attainment' },
      { label: 'CQI actions', to: '/admin/obe/cqi', icon: ClipboardCheck, module: 'obe', action: 'manage', altActions: ['view', 'view_all'], feature: 'obe.cqi' },
      { label: 'NBA export', to: '/admin/obe/exports', icon: ScrollText, module: 'obe', action: 'export', feature: 'obe.nba_export' },
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
