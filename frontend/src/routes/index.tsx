import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import PrivateRoute from './PrivateRoute';
import AdminShellRoute from './AdminShellRoute';
import PermissionRoute from './PermissionRoute';
import FeatureRoute from './FeatureRoute';
import SuperAdminRoute from './SuperAdminRoute';
import PortalRoute from './PortalRoute';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import NotFoundPage from '@/pages/NotFoundPage';

/**
 * Guard chain (docs/Technical_Architecture.md §14):
 *   PrivateRoute → SuperAdminRoute | AdminShellRoute(FeatureRoute(PermissionRoute(page))) | PortalRoute
 * Phases add lazy pages here; keep route-level code splitting.
 */
const LoginPage = lazy(() => import('@/pages/LoginPage'));
const ForgotPasswordPage = lazy(() => import('@/pages/ForgotPasswordPage'));
const ResetPasswordPage = lazy(() => import('@/pages/ResetPasswordPage'));
const MfaEnrolmentPage = lazy(() => import('@/pages/MfaEnrolmentPage'));
const DashboardPage = lazy(() => import('@/pages/DashboardPage'));
const AccessDeniedPage = lazy(() => import('@/pages/AccessDeniedPage'));
const FeatureDisabledPage = lazy(() => import('@/pages/FeatureDisabledPage'));
const PortalHomePage = lazy(() => import('@/pages/PortalHomePage'));
// Phase 02 — auth, RBAC, features, entitlements
const ProfilePage = lazy(() => import('@/features/auth/pages/ProfilePage'));
const UsersPage = lazy(() => import('@/features/auth/pages/UsersPage'));
const RolesPage = lazy(() => import('@/features/auth/pages/RolesPage'));
const SettingsFeaturesPage = lazy(() => import('@/features/auth/pages/SettingsFeaturesPage'));
const EntitlementsPage = lazy(() => import('@/features/auth/pages/EntitlementsPage'));
const InstitutionFeaturesPage = lazy(() => import('@/features/auth/pages/InstitutionFeaturesPage'));
const FeatureMatrixPage = lazy(() => import('@/features/auth/pages/FeatureMatrixPage'));
// Phase 03 — institution structure, academic sessions, settings
const InstitutionProfilePage = lazy(() => import('@/features/institution/pages/InstitutionProfilePage'));
const CollegesPage = lazy(() => import('@/features/institution/pages/CollegesPage'));
const DepartmentsPage = lazy(() => import('@/features/institution/pages/DepartmentsPage'));
const AcademicYearsPage = lazy(() => import('@/features/institution/pages/AcademicYearsPage'));
const AcademicTermPage = lazy(() => import('@/features/institution/pages/AcademicTermPage'));
const HolidaysPage = lazy(() => import('@/features/institution/pages/HolidaysPage'));
const SettingsPage = lazy(() => import('@/features/institution/pages/SettingsPage'));
const NumberSequencesPage = lazy(() => import('@/features/institution/pages/NumberSequencesPage'));
const PlatformInstitutionsPage = lazy(() => import('@/features/institution/pages/PlatformInstitutionsPage'));
const PlatformInstitutionDetailPage = lazy(() => import('@/features/institution/pages/PlatformInstitutionDetailPage'));
// Phase 04 — communication core & approvals
const CommunicationsPage = lazy(() => import('@/features/communication/pages/CommunicationsPage'));
const AnnouncementsPage = lazy(() => import('@/features/communication/pages/AnnouncementsPage'));
const NotificationsPage = lazy(() => import('@/features/communication/pages/NotificationsPage'));
const NotificationPreferencesPage = lazy(() => import('@/features/communication/pages/NotificationPreferencesPage'));
const ApprovalsPage = lazy(() => import('@/features/workflow/pages/ApprovalsPage'));
const ApprovalInstancePage = lazy(() => import('@/features/workflow/pages/ApprovalInstancePage'));
const WorkflowsAdminPage = lazy(() => import('@/features/workflow/pages/WorkflowsAdminPage'));
// Phase 05 — programmes, regulations & curriculum
const ProgramsPage = lazy(() => import('@/features/academics/pages/ProgramsPage'));
const RegulationsPage = lazy(() => import('@/features/academics/pages/RegulationsPage'));
const RegulationWorkspacePage = lazy(() => import('@/features/academics/pages/RegulationWorkspacePage'));
const CoursesPage = lazy(() => import('@/features/academics/pages/CoursesPage'));
const GradingPage = lazy(() => import('@/features/academics/pages/GradingPage'));
const BatchesPage = lazy(() => import('@/features/academics/pages/BatchesPage'));
const CatalogPage = lazy(() => import('@/features/academics/pages/CatalogPage'));
const CatalogProgramPage = lazy(() =>
  import('@/features/academics/pages/CatalogPage').then((m) => ({ default: m.CatalogProgramPage })),
);
// Phase 06 — staff, faculty, HR, recruitment & CAS
const StaffPage = lazy(() => import('@/features/hr/pages/StaffPage'));
const StaffDetailPage = lazy(() => import('@/features/hr/pages/StaffDetailPage'));
const MySpacePage = lazy(() => import('@/features/hr/pages/MySpacePage'));
const LeavesPage = lazy(() => import('@/features/hr/pages/LeavesPage'));
const StaffAttendancePage = lazy(() => import('@/features/hr/pages/AttendancePage'));
const PayrollPage = lazy(() => import('@/features/hr/pages/PayrollPage'));
const LoansPage = lazy(() => import('@/features/hr/pages/LoansPage'));
const RecruitmentPage = lazy(() => import('@/features/hr/pages/RecruitmentPage'));
const AppraisalsPage = lazy(() => import('@/features/hr/pages/AppraisalsPage'));
const WorkloadPage = lazy(() => import('@/features/hr/pages/WorkloadPage'));
const CareersPage = lazy(() => import('@/features/hr/pages/CareersPage'));
// Phase 07 — students, enrolment, holds, standing
const StudentsPage = lazy(() => import('@/features/students/pages/StudentsPage'));
const NewStudentPage = lazy(() => import('@/features/students/pages/NewStudentPage'));
const StudentDetailPage = lazy(() => import('@/features/students/pages/StudentDetailPage'));
const PromotionPage = lazy(() => import('@/features/students/pages/PromotionPage'));
const HoldsPage = lazy(() => import('@/features/students/pages/HoldsPage'));
const TransfersPage = lazy(() => import('@/features/students/pages/TransfersPage'));
const CreditTransfersPage = lazy(() => import('@/features/students/pages/CreditTransfersPage'));
const StudentHomePage = lazy(() => import('@/features/students/pages/StudentPortal'));
type PortalPage =
  | 'StudentUndertakingsPage'
  | 'StudentProfilePage'
  | 'StudentIdCardPage'
  | 'StudentCurriculumPage'
  | 'StudentCreditTransfersPage';
const studentPortal = (name: PortalPage) =>
  lazy(() => import('@/features/students/pages/StudentPortal').then((m) => ({ default: m[name] })));
const StudentUndertakingsPage = studentPortal('StudentUndertakingsPage');
const StudentProfilePage = studentPortal('StudentProfilePage');
const StudentIdCardPage = studentPortal('StudentIdCardPage');
const StudentCurriculumPage = studentPortal('StudentCurriculumPage');
const StudentCreditTransfersPage = studentPortal('StudentCreditTransfersPage');
const UndertakingGate = lazy(() =>
  import('@/features/students/pages/StudentPortal').then((m) => ({ default: m.UndertakingGate })),
);
const ParentHomePage = lazy(() => import('@/features/students/pages/ParentPortal'));
const VerifyPage = lazy(() => import('@/features/students/pages/VerifyPage'));
// Phase 09 — offerings & registration
const OfferingsPage = lazy(() => import('@/features/registration/pages/OfferingsPage'));
const OfferingRosterPage = lazy(() =>
  import('@/features/registration/pages/OfferingsPage').then((m) => ({ default: m.OfferingRosterPage })),
);
const RegistrationsPage = lazy(() => import('@/features/registration/pages/RegistrationsPage'));
const RegistrationDetailPage = lazy(() =>
  import('@/features/registration/pages/RegistrationsPage').then((m) => ({ default: m.RegistrationDetailPage })),
);
const RegWindowsPage = lazy(() =>
  import('@/features/registration/pages/AdminRegistrationPages').then((m) => ({ default: m.WindowsPage })),
);
const AllocationPage = lazy(() =>
  import('@/features/registration/pages/AdminRegistrationPages').then((m) => ({ default: m.AllocationPage })),
);
const ArrearsPage = lazy(() =>
  import('@/features/registration/pages/AdminRegistrationPages').then((m) => ({ default: m.ArrearsPage })),
);
const StudentRegistrationPage = lazy(() => import('@/features/registration/pages/StudentRegistrationPage'));
const StudentRegistrationsHistory = lazy(() =>
  import('@/features/registration/pages/StudentRegistrationPage').then((m) => ({ default: m.StudentRegistrationsHistory })),
);
const FacultyOfferingsPage = lazy(() =>
  import('@/features/registration/pages/StudentRegistrationPage').then((m) => ({ default: m.FacultyOfferingsPage })),
);
// Phase 08 — admissions
const CyclesPage = lazy(() => import('@/features/admissions/pages/CyclesPage'));
const CycleWorkspacePage = lazy(() => import('@/features/admissions/pages/CycleWorkspacePage'));
const ApplicantsPage = lazy(() => import('@/features/admissions/pages/ApplicantsPage'));
const AdmissionsVerificationPage = lazy(() =>
  import('@/features/admissions/pages/ApplicantsPage').then((m) => ({ default: m.VerificationPage })),
);
const ApplicantDetailPage = lazy(() => import('@/features/admissions/pages/ApplicantDetailPage'));
const EnquiriesPage = lazy(() => import('@/features/admissions/pages/EnquiriesPage'));
const PublicAdmissionsPage = lazy(() => import('@/features/admissions/pages/PublicAdmissionsPage'));
const PublicMeritPage = lazy(() =>
  import('@/features/admissions/pages/PublicAdmissionsPage').then((m) => ({ default: m.PublicMeritPage })),
);
const ApplyPage = lazy(() => import('@/features/admissions/pages/ApplyPage'));
const ApplicantStatusPage = lazy(() => import('@/features/admissions/pages/ApplicantStatusPage'));
// Phase 01 — platform services
const JobsPage = lazy(() => import('@/features/platform/pages/JobsPage'));
const HelpPage = lazy(() => import('@/features/platform/pages/HelpPage'));
const SearchPage = lazy(() => import('@/features/platform/pages/SearchPage'));

const page = (node: React.ReactNode) => (
  <ErrorBoundary>
    <Suspense fallback={<PageSkeleton />}>{node}</Suspense>
  </ErrorBoundary>
);

export const router = createBrowserRouter([
  { path: '/login', element: page(<LoginPage />) },
  { path: '/forgot-password', element: page(<ForgotPasswordPage />) },
  { path: '/reset-password', element: page(<ResetPasswordPage />) },
  // enrolment with the limited mfa_setup token: the user has no session yet (403 MFA_REQUIRED)
  { path: '/mfa-setup', element: page(<MfaEnrolmentPage />) },
  { path: '/access-denied', element: page(<AccessDeniedPage />) },
  { path: '/feature-disabled', element: page(<FeatureDisabledPage />) },
  // Phase 05 — public course catalogue (no sign-in; the API checks academics.public_catalog for the tenant)
  { path: '/catalog', element: page(<CatalogPage />) },
  { path: '/catalog/:program', element: page(<CatalogProgramPage />) },
  // Phase 06 — public careers page (no sign-in; the API checks hr.recruitment for the tenant)
  { path: '/careers', element: page(<CareersPage />) },
  // Phase 07 — public ID card / document verification (QR target)
  { path: '/verify/:token', element: page(<VerifyPage />) },
  // Phase 08 — public admissions: cycles, masked merit lists and the application wizard (account step needs no
  // sign-in; the API checks the admissions features for the tenant)
  { path: '/admissions', element: page(<PublicAdmissionsPage />) },
  { path: '/admissions/:slug/merit/:id', element: page(<PublicMeritPage />) },
  { path: '/apply/:cycle', element: page(<ApplyPage />) },
  {
    element: <PrivateRoute />,
    children: [
      {
        element: <AdminShellRoute />,
        children: [
          { index: true, element: <Navigate to="/dashboard" replace /> },
          {
            path: '/dashboard',
            element: page(
              <FeatureRoute feature="core.dashboard">
                <PermissionRoute module="dashboard">
                  <DashboardPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
          // Phase 02 — my profile (password, MFA, sessions, consents) is reachable by every signed-in user
          { path: '/profile', element: page(<ProfilePage />) },
          {
            path: '/admin/users',
            element: page(
              <FeatureRoute feature="core.rbac">
                <PermissionRoute module="users" action="view_all">
                  <UsersPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
          {
            path: '/admin/roles',
            element: page(
              <FeatureRoute feature="core.rbac">
                <PermissionRoute module="roles">
                  <RolesPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
          {
            path: '/admin/settings/features',
            element: page(
              <FeatureRoute feature="core.settings">
                <PermissionRoute module="features">
                  <SettingsFeaturesPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
          {
            path: '/admin/settings/entitlements',
            element: page(
              <FeatureRoute feature="core.settings">
                <PermissionRoute module="settings">
                  <EntitlementsPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
          // Phase 03 — institution structure, academic sessions, settings
          ...(
            [
              ['/admin/institution', 'core.institution', 'institutions', 'view', <InstitutionProfilePage key="i" />],
              ['/admin/colleges', 'core.institution', 'institutions', 'view', <CollegesPage key="c" />],
              ['/admin/departments', 'core.institution', 'institutions', 'view', <DepartmentsPage key="d" />],
              ['/admin/academic-years', 'core.institution', 'institutions', 'view', <AcademicYearsPage key="y" />],
              ['/admin/academic-terms/:id', 'core.institution', 'institutions', 'view', <AcademicTermPage key="t" />],
              ['/admin/holidays', 'institution.holidays', 'institutions', 'view', <HolidaysPage key="h" />],
              ['/admin/settings', 'core.settings', 'settings', 'view', <SettingsPage key="s" />],
              ['/admin/number-sequences', 'institution.number_sequences_custom', 'settings', 'manage', <NumberSequencesPage key="n" />],
            ] as const
          ).map(([path, feature, module, action, node]) => ({
            path,
            element: page(
              <FeatureRoute feature={feature}>
                <PermissionRoute module={module} action={action}>
                  {node}
                </PermissionRoute>
              </FeatureRoute>,
            ),
          })),
          // Phase 05 — programmes, regulations & curriculum (institution-wide readable by staff)
          ...(
            [
              ['/admin/academics/programs', 'academics.programs', 'programs', <ProgramsPage key="p" />],
              ['/admin/academics/regulations', 'academics.regulations', 'regulations', <RegulationsPage key="r" />],
              ['/admin/academics/regulations/:id', 'academics.regulations', 'regulations', <RegulationWorkspacePage key="w" />],
              ['/admin/academics/courses', 'academics.regulations', 'courses', <CoursesPage key="c" />],
              ['/admin/academics/grading', 'academics.regulations', 'regulations', <GradingPage key="g" />],
              ['/admin/academics/batches', 'academics.programs', 'batches', <BatchesPage key="b" />],
            ] as const
          ).map(([path, feature, module, node]) => ({
            path,
            element: page(
              <FeatureRoute feature={feature}>
                <PermissionRoute module={module} action="view">
                  {node}
                </PermissionRoute>
              </FeatureRoute>,
            ),
          })),
          // Phase 06 — HR (own-record pages need only the staff self-service grants)
          { path: '/me', element: page(<FeatureRoute feature="hr.staff"><MySpacePage /></FeatureRoute>) },
          ...(
            [
              ['/admin/hr/staff', 'hr.staff', 'hr', 'view_all', <StaffPage key="s" />],
              ['/admin/hr/staff/:id', 'hr.staff', 'hr', 'view', <StaffDetailPage key="sd" />],
              ['/admin/hr/leaves', 'hr.leaves', 'leaves', 'view', <LeavesPage key="l" />],
              ['/admin/hr/attendance', 'attendance.staff', 'attendance', 'staff_self', <StaffAttendancePage key="a" />],
              ['/admin/hr/loans', 'hr.loans_advances', 'payroll', 'self', <LoansPage key="lo" />],
              ['/admin/hr/recruitment', 'hr.recruitment', 'hr', 'recruitment', <RecruitmentPage key="r" />],
              ['/admin/hr/appraisals', 'hr.appraisal_pbas', 'hr', 'view', <AppraisalsPage key="ap" />],
            ] as const
          ).map(([path, feature, module, action, node]) => ({
            path,
            element: page(
              <FeatureRoute feature={feature}>
                <PermissionRoute module={module} action={action}>
                  {node}
                </PermissionRoute>
              </FeatureRoute>,
            ),
          })),
          {
            path: '/admin/hr/payroll',
            element: page(
              <FeatureRoute feature="hr.payroll">
                <PermissionRoute module="payroll" action="view" anyOf={[['payroll', 'view_all'], ['payroll', 'generate']]}>
                  <PayrollPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
          {
            path: '/admin/hr/workload',
            element: page(
              <FeatureRoute feature="hr.workload">
                <PermissionRoute module="faculty" action="view" anyOf={[['faculty', 'workload_manage'], ['faculty', 'view_all']]}>
                  <WorkloadPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
          // Phase 07 — students (advisors / HODs read their own slice; ScopeTabs only with view_all)
          ...(
            [
              ['/admin/students', 'students.core', 'students', 'view', [['students', 'view_all']], <StudentsPage key="s" />],
              ['/admin/students/new', 'students.core', 'students', 'create', [], <NewStudentPage key="n" />],
              ['/admin/students/promotion', 'students.core', 'batches', 'promote', [], <PromotionPage key="p" />],
              ['/admin/students/holds', 'students.holds', 'students', 'holds', [['students', 'view_all'], ['library', 'manage'], ['hostel', 'manage']], <HoldsPage key="h" />],
              ['/admin/students/transfers', 'students.transfers_migration', 'students', 'transfer', [['students', 'view_all']], <TransfersPage key="t" />],
              ['/admin/students/credit-transfers', 'academics.credit_transfer_mooc', 'credit_transfers', 'verify', [['credit_transfers', 'approve'], ['credit_transfers', 'view_all']], <CreditTransfersPage key="c" />],
              ['/admin/students/:id', 'students.core', 'students', 'view', [['students', 'view_all']], <StudentDetailPage key="d" />],
              // Phase 09 — offerings (staff read institution-wide) and registration (advisees | department | all)
              ['/admin/academics/offerings', 'registration.core', 'offerings', 'view', [['offerings', 'view_all']], <OfferingsPage key="of" />],
              ['/admin/academics/offerings/:id/roster', 'registration.core', 'offerings', 'view', [['offerings', 'view_all']], <OfferingRosterPage key="or" />],
              ['/admin/registration', 'registration.core', 'registration', 'view', [['registration', 'view_all'], ['registration', 'approve']], <RegistrationsPage key="rg" />],
              ['/admin/registration/windows', 'registration.core', 'registration', 'manage', [['registration', 'view_all']], <RegWindowsPage key="rw" />],
              ['/admin/registration/allocation', 'registration.elective_allocation', 'registration', 'allocate', [['registration', 'manage']], <AllocationPage key="ra" />],
              ['/admin/registration/arrears', 'registration.arrears', 'registration', 'view', [['registration', 'view_all'], ['registration', 'approve'], ['students', 'view_all']], <ArrearsPage key="rr" />],
              ['/admin/registration/:id', 'registration.core', 'registration', 'view', [['registration', 'view_all'], ['registration', 'approve']], <RegistrationDetailPage key="rd" />],
              // Phase 08 — admissions (cycles readable by all staff; applicants need view_all — HOD / college slices)
              ['/admin/admissions/cycles', 'admissions.cycles', 'admissions', 'view', [], <CyclesPage key="ac" />],
              ['/admin/admissions/cycles/:id', 'admissions.cycles', 'admissions', 'view', [], <CycleWorkspacePage key="aw" />],
              ['/admin/admissions/applicants', 'admissions.cycles', 'admissions', 'view_all', [], <ApplicantsPage key="aa" />],
              ['/admin/admissions/applicants/:id', 'admissions.cycles', 'admissions', 'view_all', [], <ApplicantDetailPage key="ad" />],
              ['/admin/admissions/verification', 'admissions.document_verification', 'admissions', 'verify', [], <AdmissionsVerificationPage key="av" />],
              ['/admin/admissions/enquiries', 'admissions.enquiry_crm', 'admissions', 'view', [], <EnquiriesPage key="ae" />],
            ] as [string, string, string, string, [string, string][], React.ReactNode][]
          ).map(([path, feature, module, action, anyOf, node]) => ({
            path,
            element: page(
              <FeatureRoute feature={feature}>
                <PermissionRoute module={module} action={action} anyOf={anyOf}>
                  {node}
                </PermissionRoute>
              </FeatureRoute>,
            ),
          })),
          // Phase 04 — communication core & approvals (self-service pages need no module permission)
          { path: '/notifications', element: page(<NotificationsPage />) },
          {
            path: '/profile/notifications',
            element: page(
              <FeatureRoute feature="comms.preferences">
                <NotificationPreferencesPage />
              </FeatureRoute>,
            ),
          },
          ...['/announcements', '/announcements/:id'].map((path) => ({
            path,
            element: page(
              <FeatureRoute feature="comms.announcements">
                <PermissionRoute module="communication">
                  <AnnouncementsPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          })),
          ...['/approvals', '/approvals/instances/:id'].map((path, i) => ({
            path,
            element: page(<FeatureRoute feature="workflow.engine">{i === 0 ? <ApprovalsPage /> : <ApprovalInstancePage />}</FeatureRoute>),
          })),
          {
            path: '/admin/communications',
            element: page(
              <FeatureRoute feature="core.notifications_inapp">
                <PermissionRoute module="communication" action="view_all" anyOf={[['communication', 'template_manage'], ['communication', 'send'], ['communication', 'create']]}>
                  <CommunicationsPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
          {
            path: '/admin/workflows',
            element: page(
              <FeatureRoute feature="workflow.engine">
                <PermissionRoute module="settings" action="manage">
                  <WorkflowsAdminPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
          {
            path: '/jobs',
            element: page(
              <FeatureRoute feature="core.background_jobs">
                <PermissionRoute module="jobs">
                  <JobsPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
          ...['/help', '/help/:slug'].map((path) => ({
            path,
            element: page(
              <FeatureRoute feature="platform.help_center">
                <PermissionRoute module="dashboard">
                  <HelpPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          })),
          {
            path: '/search',
            element: page(
              <FeatureRoute feature="search.global">
                <PermissionRoute module="dashboard">
                  <SearchPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
        ],
      },
      {
        path: '/platform',
        element: <SuperAdminRoute />,
        children: [{ index: true, element: page(<DashboardPage />) }],
      },
      {
        path: '/super-admin',
        element: <SuperAdminRoute />,
        children: [
          { path: 'institutions', element: page(<PlatformInstitutionsPage />) },
          { path: 'institutions/:id', element: page(<PlatformInstitutionDetailPage />) },
          { path: 'institutions/:id/features', element: page(<InstitutionFeaturesPage />) },
          { path: 'features/matrix', element: page(<FeatureMatrixPage />) },
        ],
      },
      // Portals (self-only). Phase 39 fills the pages; the shells exist so PORTAL_HOME targets resolve.
      {
        path: '/student',
        element: <PortalRoute roles={['student', 'learner']} title="Student" />,
        // Phase 07 — dashboard + self-service; pending undertakings gate every page but the dashboard / undertakings
        children: [
          { index: true, element: page(<FeatureRoute feature="portals.student"><StudentHomePage /></FeatureRoute>) },
          { path: 'undertakings', element: page(<StudentUndertakingsPage />) },
          ...(
            [
              ['profile', <StudentProfilePage key="p" />],
              ['id-card', <StudentIdCardPage key="i" />],
              ['curriculum', <StudentCurriculumPage key="c" />],
              ['credit-transfers', <StudentCreditTransfersPage key="t" />],
              ['registration', <StudentRegistrationPage key="r" />],
              ['registrations', <StudentRegistrationsHistory key="h" />],
            ] as const
          ).map(([path, node]) => ({ path, element: page(<UndertakingGate>{node}</UndertakingGate>) })),
        ],
      },
      {
        path: '/parent',
        element: <PortalRoute roles={['parent']} title="Parent" />,
        children: [{ index: true, element: page(<FeatureRoute feature="portals.parent"><ParentHomePage /></FeatureRoute>) }],
      },
      {
        path: '/faculty',
        element: <PortalRoute roles={['faculty', 'guest_faculty']} title="Faculty" />,
        children: [
          { index: true, element: page(<PortalHomePage />) },
          { path: 'offerings', element: page(<FacultyOfferingsPage />) },
          { path: 'offerings/:id', element: page(<OfferingRosterPage />) },
        ],
      },
      {
        path: '/alumni',
        element: <PortalRoute roles={['alumni']} title="Alumni" />,
        children: [{ index: true, element: page(<PortalHomePage />) }],
      },
      {
        path: '/warden',
        element: <PortalRoute roles={['hostel_warden', 'hostel_gate_staff']} title="Warden" />,
        children: [
          { index: true, element: page(<PortalHomePage />) },
          { path: 'gate', element: page(<PortalHomePage />) },
        ],
      },
      {
        path: '/driver',
        element: <PortalRoute roles={['driver']} title="Driver" />,
        children: [{ index: true, element: page(<PortalHomePage />) }],
      },
      {
        path: '/evaluator',
        element: <PortalRoute roles={['external_examiner']} title="Evaluator" />,
        children: [{ index: true, element: page(<PortalHomePage />) }],
      },
      {
        path: '/scholar',
        element: <PortalRoute roles={['research_scholar']} title="Scholar" />,
        children: [{ index: true, element: page(<PortalHomePage />) }],
      },
      {
        path: '/recruiter',
        element: <PortalRoute roles={['recruiter']} title="Recruiter" />,
        children: [{ index: true, element: page(<PortalHomePage />) }],
      },
      {
        path: '/apply',
        element: <PortalRoute roles={['applicant']} title="Admissions" />,
        // Phase 08 — applicant portal: status, timeline, allotment decisions, payments (mobile deep link /apply/:cycle)
        children: [
          { index: true, element: page(<ApplicantStatusPage />) },
          { path: ':cycle/status', element: page(<ApplicantStatusPage />) },
        ],
      },
    ],
  },
  { path: '*', element: page(<NotFoundPage />) },
]);

export default function AppRoutes() {
  return <RouterProvider router={router} />;
}
