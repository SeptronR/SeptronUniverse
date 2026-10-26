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
// Phase 11 — attendance
const FacultyAttendancePage = lazy(() => import('@/features/attendance/pages/FacultyAttendancePages').then((m) => ({ default: m.FacultyAttendancePage })));
const FacultySummaryPage = lazy(() => import('@/features/attendance/pages/FacultyAttendancePages').then((m) => ({ default: m.FacultySummaryPage })));
const AdminAttendancePage = lazy(() => import('@/features/attendance/pages/AdminAttendancePages').then((m) => ({ default: m.AdminAttendancePage })));
const OdQueuePage = lazy(() => import('@/features/attendance/pages/AdminAttendancePages').then((m) => ({ default: m.OdQueuePage })));
const CondonationsPage = lazy(() => import('@/features/attendance/pages/AdminAttendancePages').then((m) => ({ default: m.CondonationsPage })));
const EligibilityPage = lazy(() => import('@/features/attendance/pages/AdminAttendancePages').then((m) => ({ default: m.EligibilityPage })));
const StudentAttendancePage = lazy(() => import('@/features/attendance/pages/StudentAttendancePage').then((m) => ({ default: m.StudentAttendancePage })));
const ParentAttendancePage = lazy(() => import('@/features/attendance/pages/StudentAttendancePage').then((m) => ({ default: m.ParentAttendancePage })));
// Phase 12 — fees, scholarships & no-dues
const FeesDashboardPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeesDashboardPage })));
const FeeStructuresPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeStructuresPage })));
const FeeDiscountsPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeDiscountsPage })));
const FeeFinesPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeFinesPage })));
const FeeInvoicesPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeInvoicesPage })));
const FeeCollectPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeCollectPage })));
const FeePaymentsPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeePaymentsPage })));
const FeeOnlinePage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeOnlinePage })));
const FeeReconcilePage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeReconcilePage })));
const FeeDayBookPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeDayBookPage })));
const FeeRefundsPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeRefundsPage })));
const FeeScholarshipsPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeScholarshipsPage })));
const FeeNoDuesPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeNoDuesPage })));
const FeeReportsPage = lazy(() => import('@/features/fees/pages/AdminFeesPages').then((m) => ({ default: m.FeeReportsPage })));
// Phase 13 — internal assessment, OBE, LMS, projects, question bank
const FacultyMarksPage = lazy(() => import('@/features/assessment/pages/FacultyAssessmentPages').then((m) => ({ default: m.FacultyMarksPage })));
const CiaPage = lazy(() => import('@/features/assessment/pages/FacultyAssessmentPages').then((m) => ({ default: m.CiaPage })));
const OfferingLmsPage = lazy(() => import('@/features/assessment/pages/FacultyAssessmentPages').then((m) => ({ default: m.OfferingLmsPage })));
const LessonPlanPage = lazy(() => import('@/features/assessment/pages/FacultyAssessmentPages').then((m) => ({ default: m.LessonPlanPage })));
const FacultyProjectsPage = lazy(() => import('@/features/assessment/pages/FacultyAssessmentPages').then((m) => ({ default: m.FacultyProjectsPage })));
const QuestionBankPage = lazy(() => import('@/features/assessment/pages/FacultyAssessmentPages').then((m) => ({ default: m.QuestionBankPage })));
const CourseOutcomesPage = lazy(() => import('@/features/assessment/pages/FacultyAssessmentPages').then((m) => ({ default: m.CourseOutcomesPage })));
const MarksVerificationPage = lazy(() => import('@/features/assessment/pages/AdminAssessmentPages').then((m) => ({ default: m.MarksVerificationPage })));
const MarksLocksPage = lazy(() => import('@/features/assessment/pages/AdminAssessmentPages').then((m) => ({ default: m.MarksLocksPage })));
const ProgramOutcomesPage = lazy(() => import('@/features/assessment/pages/AdminAssessmentPages').then((m) => ({ default: m.ProgramOutcomesPage })));
const ObeProgramsPage = lazy(() => import('@/features/assessment/pages/AdminAssessmentPages').then((m) => ({ default: m.ObeProgramsPage })));
const StudentCoursePage = lazy(() => import('@/features/assessment/pages/StudentCoursePages').then((m) => ({ default: m.StudentCoursePage })));
const StudentMarksPage = lazy(() => import('@/features/assessment/pages/StudentCoursePages').then((m) => ({ default: m.StudentMarksPage })));
// Phase 15 — evaluation & results
const EvaluatorPortalPage = lazy(() => import('@/features/results/pages/ResultPages').then((m) => ({ default: m.EvaluatorPortalPage })));
const StudentResultsPage = lazy(() => import('@/features/results/pages/ResultPages').then((m) => ({ default: m.StudentResultsPage })));
const ParentResultsPage = lazy(() => import('@/features/results/pages/ResultPages').then((m) => ({ default: m.ParentResultsPage })));
const OfferingResultsPage = lazy(() => import('@/features/results/pages/ResultPages').then((m) => ({ default: m.OfferingResultsPage })));
const TabulationPage = lazy(() => import('@/features/results/pages/ResultPages').then((m) => ({ default: m.TabulationPage })));
const ResultAnalysisPage = lazy(() => import('@/features/results/pages/ResultPages').then((m) => ({ default: m.ResultAnalysisPage })));
const RankListPage = lazy(() => import('@/features/results/pages/ResultPages').then((m) => ({ default: m.RankListPage })));
const LegacyImportPage = lazy(() => import('@/features/results/pages/ResultPages').then((m) => ({ default: m.LegacyImportPage })));
const PublicResultLookupPage = lazy(() => import('@/features/results/pages/ResultPages').then((m) => ({ default: m.PublicResultLookupPage })));
// Phase 16 — post-result services (web screens owed since Phase 16)
const RevaluationAdminPage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.RevaluationAdminPage })));
const MalpracticeAdminPage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.MalpracticeAdminPage })));
const WithheldPage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.WithheldPage })));
const SupplementaryPage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.SupplementaryPage })));
const TranscriptsAdminPage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.TranscriptsAdminPage })));
const RankMedalsPage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.RankMedalsPage })));
const CorrectionsPage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.CorrectionsPage })));
const DetainedPage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.DetainedPage })));
const StudentRevalPage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.StudentRevalPage })));
const StudentMalpracticePage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.StudentMalpracticePage })));
const StudentTranscriptsPage = lazy(() => import('@/features/post_result/pages/PostResultPages').then((m) => ({ default: m.StudentTranscriptsPage })));
// Phase 27 — mentoring, early warning, grievances, discipline, surveys, clubs, committees stub
const SsMentoringAdminPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.MentoringAdminPage })));
const SsMenteesPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.MenteesPage })));
const SsMentee360Page = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.Mentee360Page })));
const SsRiskPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.RiskPage })));
const SsGrievancesPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.GrievancesAdminPage })));
const SsGrievanceTicketPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.GrievanceTicketPage })));
const SsStudentGrievancesPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.StudentGrievancesPage })));
const SsPublicGrievancePage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.PublicGrievancePage })));
const SsGrievanceTrackPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.GrievanceTrackPage })));
const SsDisciplinePage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.DisciplinePage })));
const SsDisciplineCasePage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.DisciplineCasePage })));
const SsStudentDisciplinePage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.StudentDisciplinePage })));
const SsSurveysAdminPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.SurveysAdminPage })));
const SsSurveyDetailPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.SurveyDetailPage })));
const SsMySurveysPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.MySurveysPage })));
const SsFacultySurveysPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.FacultySurveysPage })));
const SsClubsAdminPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.ClubsAdminPage })));
const SsStudentClubsPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.StudentClubsPage })));
const SsStudentMentorPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.StudentMentorPage })));
const SsParentSupportPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.ParentSupportPage })));
const SsCommitteesPage = lazy(() => import('@/features/student_support/pages/SupportPages').then((m) => ({ default: m.CommitteesStubPage })));
// Phase 28 — placement, internships, training, recruiter portal
const PlCompaniesPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.CompaniesPage })));
const PlCompanyPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.CompanyPage })));
const PlPoliciesPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.PoliciesPage })));
const PlDrivesPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.DrivesPage })));
const PlDrivePage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.DrivePage })));
const PlOffersPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.OffersPage })));
const PlProfilesPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.ProfilesPage })));
const PlBlacklistPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.BlacklistPage })));
const PlInternshipsPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.InternshipsPage })));
const PlTrainingPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.TrainingPage })));
const PlStatsPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.StatsPage })));
// Phase 29 — alumni, endowments & fundraising
const AlProfilesPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.ProfilesPage })));
const AlProfilePage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.ProfilePage })));
const AlDirectoryPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.DirectoryPage })));
const AlEventsPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.EventsPage })));
const AlJobsAdminPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.JobsAdminPage })));
const AlFundraisingPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.FundraisingPage })));
const AlStatsPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.StatsPage })));
const AlHomePage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.AlumniHomePage })));
const AlProfileSelfPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.AlumniProfileSelfPage })));
const AlEventsPortalPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.AlumniEventsPortalPage })));
const AlJobsPortalPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.AlumniJobsPortalPage })));
const AlGivePage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.AlumniGivePage })));
const AlClaimPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.AlumniClaimPage })));
const AlPublicCampaignsPage = lazy(() => import('@/features/alumni/pages/AlumniPages').then((m) => ({ default: m.PublicCampaignsPage })));
// Phase 30 — research & faculty development
const RsPublicationsPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.PublicationsPage })));
const RsPatentsPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.PatentsPage })));
const RsProjectsPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.ProjectsPage })));
const RsProjectPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.ProjectPage })));
const RsConsultancyPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.ConsultancyPage })));
const RsEthicsPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.EthicsPage })));
const RsIncentivesPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.IncentivesPage })));
const RsFdpPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.FdpPage })));
const RsMousPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.MousPage })));
const RsMouPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.MouPage })));
const RsStartupsPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.StartupsPage })));
const RsApiScorePage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.ApiScorePage })));
const RsStatsPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.StatsPage })));
const RsFacultyResearchPage = lazy(() => import('@/features/research/pages/ResearchPages').then((m) => ({ default: m.FacultyResearchPage })));
const PlStudentPlacementPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.StudentPlacementPage })));
const PlParentPlacementPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.ParentPlacementPage })));
const PlFacultyInternshipsPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.FacultyInternshipsPage })));
const PlRecruiterDrivesPage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.RecruiterDrivesPage })));
const PlRecruiterDrivePage = lazy(() => import('@/features/placement/pages/PlacementPages').then((m) => ({ default: m.RecruiterDrivePage })));
// Phase 26 — document templates, certificates & requests
const DocTemplatesPage = lazy(() => import('@/features/documents/pages/DocumentPages').then((m) => ({ default: m.TemplatesPage })));
const DocIssuedPage = lazy(() => import('@/features/documents/pages/DocumentPages').then((m) => ({ default: m.IssuedRegisterPage })));
const DocBulkPage = lazy(() => import('@/features/documents/pages/DocumentPages').then((m) => ({ default: m.BulkGenerationPage })));
const DocRegistersPage = lazy(() => import('@/features/documents/pages/DocumentPages').then((m) => ({ default: m.SerialRegistersPage })));
const DocRequestsPage = lazy(() => import('@/features/documents/pages/DocumentPages').then((m) => ({ default: m.RequestsQueuePage })));
const DocSettingsPage = lazy(() => import('@/features/documents/pages/DocumentPages').then((m) => ({ default: m.DocumentSettingsPage })));
const MyDocumentsPage = lazy(() => import('@/features/documents/pages/DocumentPages').then((m) => ({ default: m.MyDocumentsPage })));
const WardDocumentsPage = lazy(() => import('@/features/documents/pages/DocumentPages').then((m) => ({ default: m.WardDocumentsPage })));
const DocVerifyPage = lazy(() => import('@/features/documents/pages/DocumentPages').then((m) => ({ default: m.DocVerifyPage })));
const VerifyLandingPage = lazy(() => import('@/features/documents/pages/DocumentPages').then((m) => ({ default: m.VerifyLandingPage })));
// Phase 25 — calendar, events & facilities
const FacCalendarPage = lazy(() => import('@/features/facilities/pages/FacilitiesPages').then((m) => ({ default: m.CalendarPage })));
const FacEventsPage = lazy(() => import('@/features/facilities/pages/FacilitiesPages').then((m) => ({ default: m.EventsPage })));
const FacBookingsPage = lazy(() => import('@/features/facilities/pages/FacilitiesPages').then((m) => ({ default: m.BookingsPage })));
const FacServiceDeskPage = lazy(() => import('@/features/facilities/pages/FacilitiesPages').then((m) => ({ default: m.ServiceDeskPage })));
const FacSecurityPage = lazy(() => import('@/features/facilities/pages/FacilitiesPages').then((m) => ({ default: m.SecurityPage })));
const FacWellnessPage = lazy(() => import('@/features/facilities/pages/FacilitiesPages').then((m) => ({ default: m.WellnessPage })));
const FacSportsPage = lazy(() => import('@/features/facilities/pages/FacilitiesPages').then((m) => ({ default: m.SportsPage })));
const FacWalletPage = lazy(() => import('@/features/facilities/pages/FacilitiesPages').then((m) => ({ default: m.WalletPage })));
// Phase 24 — communication advanced
const CommsSegmentsPage = lazy(() => import('@/features/comms_advanced/pages/CommsAdvancedPages').then((m) => ({ default: m.SegmentsPage })));
const CommsCampaignsPage = lazy(() => import('@/features/comms_advanced/pages/CommsAdvancedPages').then((m) => ({ default: m.CampaignsPage })));
const CommsEmergencyPage = lazy(() => import('@/features/comms_advanced/pages/CommsAdvancedPages').then((m) => ({ default: m.EmergencyPage })));
const CommsBotPage = lazy(() => import('@/features/comms_advanced/pages/CommsAdvancedPages').then((m) => ({ default: m.BotPage })));
const CommsAssistantPage = lazy(() => import('@/features/comms_advanced/pages/CommsAdvancedPages').then((m) => ({ default: m.AssistantPage })));
const CommsSimulatorPage = lazy(() => import('@/features/comms_advanced/pages/CommsAdvancedPages').then((m) => ({ default: m.SimulatorPage })));
const CommsAnalyticsPage = lazy(() => import('@/features/comms_advanced/pages/CommsAdvancedPages').then((m) => ({ default: m.DeliveryAnalyticsPage })));
const CommsMyMessagesPage = lazy(() => import('@/features/comms_advanced/pages/CommsAdvancedPages').then((m) => ({ default: m.MyMessagesPage })));
// Phase 23 — accounting & budget
const AccountingDashboardPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.AccountingDashboardPage })));
const AcctChartPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.ChartPage })));
const AcctLedgerPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.LedgerPage })));
const AcctIncomePage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.IncomePage })));
const AcctExpensesPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.ExpensesPage })));
const AcctBudgetsPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.BudgetsPage })));
const AcctMyBudgetPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.MyBudgetPage })));
const AcctGrantsPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.GrantsPage })));
const AcctReconciliationPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.ReconciliationPage })));
const AcctGstPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.GstPage })));
const AcctExportsPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.ExportsPage })));
const AcctStatementsPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.StatementsPage })));
const AcctPeriodsPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.PeriodsPage })));
const AcctFacultyGrantsPage = lazy(() => import('@/features/accounting/pages/AccountingPages').then((m) => ({ default: m.FacultyGrantsPage })));
// Phase 22 — inventory, procurement, assets, bills, supplier portal
const InvItemsPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.ItemsPage })));
const InvStoresPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.StoresPage })));
const InvSuppliersPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.SuppliersPage })));
const InvIndentsPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.IndentsPage })));
const InvQuotationsPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.QuotationsPage })));
const InvPurchaseOrdersPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.PurchaseOrdersPage })));
const InvGoodsReceiptsPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.GoodsReceiptsPage })));
const InvAssetsPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.AssetsPage })));
const InvAuditsPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.AuditsPage })));
const InvBillsPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.BillsPage })));
const InvVendorStorePage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.VendorStorePage })));
const InventoryReportsPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.InventoryReportsPage })));
const InventorySettingsPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.InventorySettingsPage })));
const StaffIndentsPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.StaffIndentsPage })));
const VendorHomePage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.VendorHomePage })));
const VendorRegisterPage = lazy(() => import('@/features/inventory/pages/InventoryPages').then((m) => ({ default: m.VendorRegisterPage })));
// Phase 21 — transport
const FleetPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.FleetPage })));
const RoutesPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.RoutesPage })));
const TransportAllocationsPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.AllocationsPage })));
const TripsPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.TripsPage })));
const LiveMapPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.LiveMapPage })));
const GpsDevicesPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.DevicesPage })));
const TransportReportsPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.TransportReportsPage })));
const TransportSettingsPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.TransportSettingsPage })));
const MyTransportPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.MyTransportPage })));
const ParentTransportPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.ParentTransportPage })));
const StaffTransportPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.StaffTransportPage })));
const DriverPage = lazy(() => import('@/features/transport/pages/TransportPages').then((m) => ({ default: m.DriverPage })));
// Phase 20 — hostel, mess, staff quarters
const HostelsPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.HostelsPage })));
const HostelApplicationsPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.ApplicationsPage })));
const HostelAllocationsPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.AllocationsPage })));
const RoomChangesPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.RoomChangesPage })));
const RollCallPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.RollCallPage })));
const MessPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.MessPage })));
const HostelVisitorsPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.VisitorsPage })));
const HostelLeavesPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.LeavesPage })));
const HostelComplaintsPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.ComplaintsPage })));
const HostelDisciplinePage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.DisciplinePage })));
const QuartersPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.QuartersPage })));
const HostelReportsPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.HostelReportsPage })));
const StudentHostelPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.StudentHostelPage })));
const ParentHostelPage = lazy(() => import('@/features/hostel/pages/HostelPages').then((m) => ({ default: m.ParentHostelPage })));
// Phase 19 — library
const CataloguePage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.CataloguePage })));
const CirculationPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.CirculationPage })));
const LibraryIssuesPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.IssuesPage })));
const LibraryReservationsPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.ReservationsPage })));
const LibraryFinesPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.FinesPage })));
const LibraryMembersPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.MembersPage })));
const EresourcesPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.EresourcesPage })));
const IllPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.IllPage })));
const StockVerificationPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.StockVerificationPage })));
const LibraryReportsPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.LibraryReportsPage })));
const MyLibraryPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.MyLibraryPage })));
const WardLibraryPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.WardLibraryPage })));
const OpacPage = lazy(() => import('@/features/library/pages/LibraryPages').then((m) => ({ default: m.OpacPage })));
// Phase 18 — degrees, convocation, digital credentials
const DegreeEligibilityPage = lazy(() => import('@/features/degrees/pages/DegreePages').then((m) => ({ default: m.DegreeEligibilityPage })));
const ConvocationsPage = lazy(() => import('@/features/degrees/pages/DegreePages').then((m) => ({ default: m.ConvocationsPage })));
const AwardsPage = lazy(() => import('@/features/degrees/pages/DegreePages').then((m) => ({ default: m.AwardsPage })));
const ProvisionalPage = lazy(() => import('@/features/degrees/pages/DegreePages').then((m) => ({ default: m.ProvisionalPage })));
const CredentialsPage = lazy(() => import('@/features/degrees/pages/DegreePages').then((m) => ({ default: m.CredentialsPage })));
const GraduationStatsPage = lazy(() => import('@/features/degrees/pages/DegreePages').then((m) => ({ default: m.GraduationStatsPage })));
const StudentDegreePage = lazy(() => import('@/features/degrees/pages/DegreePages').then((m) => ({ default: m.StudentDegreePage })));
const BulkVerifyPage = lazy(() => import('@/features/degrees/pages/DegreePages').then((m) => ({ default: m.BulkVerifyPage })));
// Phase 17 — OBE attainment, CQI, NBA export
const ObeConfigPage = lazy(() => import('@/features/obe/pages/ObePages').then((m) => ({ default: m.ObeConfigPage })));
const OfferingAttainmentPage = lazy(() => import('@/features/obe/pages/ObePages').then((m) => ({ default: m.OfferingAttainmentPage })));
const ProgramAttainmentPage = lazy(() => import('@/features/obe/pages/ObePages').then((m) => ({ default: m.ProgramAttainmentPage })));
const AttainmentTrendPage = lazy(() => import('@/features/obe/pages/ObePages').then((m) => ({ default: m.AttainmentTrendPage })));
const CqiBoardPage = lazy(() => import('@/features/obe/pages/ObePages').then((m) => ({ default: m.CqiBoardPage })));
const NbaExportPage = lazy(() => import('@/features/obe/pages/ObePages').then((m) => ({ default: m.NbaExportPage })));
const StudentOutcomesPage = lazy(() => import('@/features/obe/pages/ObePages').then((m) => ({ default: m.StudentOutcomesPage })));
// Phase 14 — exam administration
const ExamSessionsPage = lazy(() => import('@/features/exams/pages/ExamPages').then((m) => ({ default: m.ExamSessionsPage })));
const ExamSessionWorkspacePage = lazy(() => import('@/features/exams/pages/ExamPages').then((m) => ({ default: m.ExamSessionWorkspacePage })));
const MyDutiesPage = lazy(() => import('@/features/exams/pages/ExamPages').then((m) => ({ default: m.MyDutiesPage })));
const MyQpPage = lazy(() => import('@/features/exams/pages/ExamPages').then((m) => ({ default: m.MyQpPage })));
const StudentExamsPage = lazy(() => import('@/features/exams/pages/ExamPages').then((m) => ({ default: m.StudentExamsPage })));
const ParentExamsPage = lazy(() => import('@/features/exams/pages/ExamPages').then((m) => ({ default: m.ParentExamsPage })));
const StudentFeesPage = lazy(() => import('@/features/fees/pages/StudentFeesPage').then((m) => ({ default: m.StudentFeesPage })));
const ParentFeesPage = lazy(() => import('@/features/fees/pages/StudentFeesPage').then((m) => ({ default: m.ParentFeesPage })));
// Phase 10 — timetable & rooms
const RoomsPage = lazy(() =>
  import('@/features/timetable/pages/TimetablePages').then((m) => ({ default: m.RoomsPage })),
);
const SlotsPage = lazy(() =>
  import('@/features/timetable/pages/TimetablePages').then((m) => ({ default: m.SlotsPage })),
);
const TimetableEditorPage = lazy(() =>
  import('@/features/timetable/pages/TimetablePages').then((m) => ({ default: m.TimetableEditorPage })),
);
const SubstitutionsPage = lazy(() =>
  import('@/features/timetable/pages/TimetablePages').then((m) => ({ default: m.SubstitutionsPage })),
);
const SessionsPage = lazy(() =>
  import('@/features/timetable/pages/TimetablePages').then((m) => ({ default: m.SessionsPage })),
);
const MyTimetablePage = lazy(() =>
  import('@/features/timetable/pages/TimetablePages').then((m) => ({ default: m.MyTimetablePage })),
);
const RoomKioskPage = lazy(() =>
  import('@/features/timetable/pages/TimetablePages').then((m) => ({ default: m.RoomKioskPage })),
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
  { path: '/opac', element: page(<OpacPage />) },
  // Phase 29 — public alumni claim and the website campaigns / donation form (tenant by ?institution=<slug>)
  { path: '/alumni-claim', element: page(<AlClaimPage />) },
  { path: '/give', element: page(<AlPublicCampaignsPage />) },
  { path: '/vendor/register', element: page(<VendorRegisterPage />) },
  { path: '/verify/bulk', element: page(<BulkVerifyPage />) },
  // Phase 27 — public anonymous grievance form and tracking (tenant from ?institution=)
  { path: '/grievance', element: page(<SsPublicGrievancePage />) },
  { path: '/grievance/track', element: page(<SsGrievanceTrackPage />) },
  { path: '/verify', element: page(<VerifyLandingPage />) },
  // Phase 26 — unified verification over the issued-document register (all types)
  { path: '/verify/:token', element: page(<DocVerifyPage />) },
  // Phase 15 — public result lookup (reg. no + DOB; the API checks the setting / audience)
  { path: '/results/lookup', element: page(<PublicResultLookupPage />) },
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
              // Phase 10 — timetable & rooms (staff read institution-wide; edits narrowed by the services)
              ['/admin/facilities/rooms', 'timetable.rooms', 'timetable', 'view', [['timetable', 'view_all']], <RoomsPage key="tr" />],
              ['/admin/timetable/slots', 'timetable.core', 'timetable', 'update', [['timetable', 'manage']], <SlotsPage key="ts" />],
              ['/admin/timetable/substitutions', 'timetable.substitutions', 'timetable', 'substitute', [['timetable', 'approve'], ['timetable', 'manage']], <SubstitutionsPage key="tu" />],
              ['/admin/timetable/sessions', 'timetable.core', 'attendance', 'view', [['attendance', 'view_all'], ['attendance', 'mark']], <SessionsPage key="tx" />],
              ['/admin/timetable', 'timetable.core', 'timetable', 'view', [['timetable', 'view_all']], <TimetableEditorPage key="te" />],
              ['/admin/timetable/:termId', 'timetable.core', 'timetable', 'view', [['timetable', 'view_all']], <TimetableEditorPage key="tt" />],
              ['/rooms/:id/today', 'timetable.rooms', 'timetable', 'view', [['timetable', 'view_all']], <RoomKioskPage key="rk" />],
              ['/timetable', 'timetable.core', 'timetable', 'view', [], <MyTimetablePage key="tm" />],
              // Phase 11 — attendance (narrowed further by the services)
              ['/admin/attendance/od', 'attendance.on_duty', 'attendance', 'condone', [['attendance', 'view_all'], ['attendance', 'mark'], ['attendance', 'edit_finalized']], <OdQueuePage key="ao" />],
              ['/admin/attendance/condonations', 'attendance.condonation', 'attendance', 'condone', [['attendance', 'view_all'], ['attendance', 'view']], <CondonationsPage key="ac" />],
              ['/admin/attendance/eligibility', 'attendance.eligibility_detention', 'exams', 'eligibility', [['attendance', 'view_all'], ['fees', 'view_all']], <EligibilityPage key="ae" />],
              ['/admin/attendance', 'attendance.core', 'attendance', 'view_all', [['attendance', 'view'], ['attendance', 'edit_finalized']], <AdminAttendancePage key="aa" />],
              // Phase 16 — post-result services
              ['/admin/exams/revaluation', 'results.revaluation', 'exams', 'reval', [['exams', 'view_all'], ['exams', 'manage']], <RevaluationAdminPage key="pr1" />],
              ['/admin/exams/malpractice', 'results.malpractice', 'exams', 'malpractice', [['exams', 'view_all'], ['exams', 'manage']], <MalpracticeAdminPage key="pr2" />],
              ['/admin/exams/supplementary', 'results.supplementary', 'exams', 'manage', [], <SupplementaryPage key="pr3" />],
              ['/admin/results/withheld', 'results.processing', 'results', 'approve', [['results', 'manage'], ['results', 'view_all']], <WithheldPage key="pr4" />],
              ['/admin/results/transcripts', 'results.transcripts', 'results', 'transcript', [['results', 'manage']], <TranscriptsAdminPage key="pr5" />],
              ['/admin/results/medals', 'results.rank_lists', 'results', 'view_all', [['results', 'approve'], ['results', 'manage']], <RankMedalsPage key="pr6" />],
              ['/admin/results/corrections', 'results.processing', 'results', 'verify', [['marks', 'correct'], ['results', 'manage']], <CorrectionsPage key="pr7" />],
              ['/admin/students/detained', 'results.processing', 'students', 'view_all', [['students', 'manage']], <DetainedPage key="pr8" />],
              // Phase 26 — documents (role type limits and scopes in the services)
              // Phase 27 — student support (ownership / confidentiality / scopes in the services)
              ['/admin/mentoring', 'mentoring.core', 'mentoring', 'view_all', [['mentoring', 'manage']], <SsMentoringAdminPage key="ssm" />],
              ['/admin/risk', 'mentoring.early_warning', 'mentoring', 'view_all', [['mentoring', 'manage']], <SsRiskPage key="ssr" />],
              ['/admin/grievances', 'grievances.core', 'grievances', 'view_all', [['grievances', 'triage'], ['grievances', 'view'], ['grievances', 'manage']], <SsGrievancesPage key="ssg" />],
              ['/admin/grievances/:id', 'grievances.core', 'grievances', 'view_all', [['grievances', 'triage'], ['grievances', 'view'], ['grievances', 'manage']], <SsGrievanceTicketPage key="ssgt" />],
              ['/admin/discipline', 'discipline.core', 'discipline', 'view_all', [['discipline', 'manage'], ['discipline', 'decide'], ['discipline', 'view']], <SsDisciplinePage key="ssd" />],
              ['/admin/discipline/:id', 'discipline.core', 'discipline', 'view_all', [['discipline', 'manage'], ['discipline', 'decide'], ['discipline', 'view']], <SsDisciplineCasePage key="ssdc" />],
              ['/admin/surveys', 'surveys.core', 'surveys', 'manage', [['surveys', 'view_all'], ['surveys', 'analyse']], <SsSurveysAdminPage key="sss" />],
              ['/admin/surveys/:id', 'surveys.core', 'surveys', 'manage', [['surveys', 'view_all'], ['surveys', 'analyse']], <SsSurveyDetailPage key="sssd" />],
              ['/admin/clubs', 'clubs.core', 'clubs', 'view_all', [['clubs', 'verify_hours'], ['clubs', 'manage']], <SsClubsAdminPage key="ssc" />],
              ['/admin/governance/committees', 'governance.committees', 'governance', 'committees', [['governance', 'manage'], ['governance', 'view']], <SsCommitteesPage key="ssgc" />],
              // Phase 28 — placement (eligibility, policy, consent and scopes in the services)
              ['/admin/placement/companies', 'placement.core', 'placement', 'view_all', [['placement', 'manage'], ['placement', 'drive_manage']], <PlCompaniesPage key="plc" />],
              ['/admin/placement/companies/:id', 'placement.core', 'placement', 'view_all', [['placement', 'manage'], ['placement', 'drive_manage']], <PlCompanyPage key="plcd" />],
              ['/admin/placement/policies', 'placement.core', 'placement', 'view_all', [['placement', 'manage'], ['placement', 'drive_manage']], <PlPoliciesPage key="plp" />],
              ['/admin/placement/drives', 'placement.core', 'placement', 'view_all', [['placement', 'manage'], ['placement', 'drive_manage']], <PlDrivesPage key="pld" />],
              ['/admin/placement/drives/:id', 'placement.core', 'placement', 'view_all', [['placement', 'manage'], ['placement', 'drive_manage']], <PlDrivePage key="pldd" />],
              ['/admin/placement/offers', 'placement.core', 'placement', 'view_all', [['placement', 'manage'], ['placement', 'drive_manage']], <PlOffersPage key="plo" />],
              ['/admin/placement/profiles', 'placement.core', 'placement', 'view_all', [['placement', 'manage'], ['placement', 'drive_manage']], <PlProfilesPage key="plpr" />],
              ['/admin/placement/blacklist', 'placement.core', 'placement', 'view_all', [['placement', 'manage'], ['placement', 'drive_manage']], <PlBlacklistPage key="plb" />],
              ['/admin/placement/stats', 'placement.core', 'placement', 'view_all', [['placement', 'manage'], ['placement', 'drive_manage']], <PlStatsPage key="pls" />],
              ['/admin/placement/internships', 'placement.internships', 'placement', 'view_all', [['placement', 'manage'], ['placement', 'evaluate']], <PlInternshipsPage key="pli" />],
              ['/admin/placement/training', 'placement.training', 'placement', 'manage', [['placement', 'view_all']], <PlTrainingPage key="plt" />],
              // Phase 29 — alumni & fundraising (consent projection, verification and scopes in the services)
              ['/admin/alumni/profiles', 'alumni.core', 'alumni', 'view_all', [['alumni', 'manage'], ['alumni', 'verify']], <AlProfilesPage key="alp" />],
              ['/admin/alumni/profiles/:id', 'alumni.core', 'alumni', 'view_all', [['alumni', 'manage'], ['alumni', 'verify']], <AlProfilePage key="alpd" />],
              ['/admin/alumni/directory', 'alumni.portal', 'alumni', 'view_all', [['alumni', 'manage'], ['placement', 'manage']], <AlDirectoryPage key="ald" />],
              ['/admin/alumni/events', 'alumni.core', 'alumni', 'manage', [['alumni', 'view_all']], <AlEventsPage key="ale" />],
              ['/admin/alumni/jobs', 'alumni.jobs_board', 'alumni', 'manage', [['alumni', 'view_all'], ['placement', 'manage']], <AlJobsAdminPage key="alj" />],
              ['/admin/alumni/fundraising', 'alumni.fundraising', 'fundraising', 'manage', [['alumni', 'campaign'], ['fundraising', 'receipt'], ['fundraising', 'view_all']], <AlFundraisingPage key="alf" />],
              ['/admin/alumni/stats', 'alumni.core', 'alumni', 'view_all', [['alumni', 'manage']], <AlStatsPage key="als" />],
              // Phase 30 — research & faculty development (ownership, scopes, locks and workflows in the services)
              ['/admin/research/publications', 'research.publications', 'research', 'view', [['research', 'view_all'], ['research', 'manage']], <RsPublicationsPage key="rsp" />],
              ['/admin/research/verification', 'research.publications', 'research', 'verify', [['research', 'manage']], <RsPublicationsPage key="rsv" verification />],
              ['/admin/research/patents', 'research.patents', 'research', 'view', [['research', 'view_all'], ['research', 'manage']], <RsPatentsPage key="rspt" />],
              ['/admin/research/projects', 'research.projects_grants', 'research', 'view', [['research', 'view_all'], ['research', 'manage'], ['accounting', 'view_all']], <RsProjectsPage key="rspr" />],
              ['/admin/research/projects/:id', 'research.projects_grants', 'research', 'view', [['research', 'view_all'], ['research', 'manage'], ['accounting', 'view_all']], <RsProjectPage key="rsprd" />],
              ['/admin/research/consultancy', 'research.consultancy', 'research', 'view', [['research', 'view_all'], ['research', 'manage'], ['accounting', 'view_all']], <RsConsultancyPage key="rsc" />],
              ['/admin/research/ethics', 'research.ethics_committee', 'research', 'ethics', [['research', 'view'], ['research', 'view_all'], ['research', 'manage']], <RsEthicsPage key="rse" />],
              ['/admin/research/incentives', 'research.seed_grants_incentives', 'research', 'incentives', [['research', 'view'], ['research', 'view_all'], ['research', 'manage'], ['accounting', 'manage']], <RsIncentivesPage key="rsi" />],
              ['/admin/research/fdp', 'research.fdp', 'research', 'view', [['research', 'view_all'], ['research', 'manage']], <RsFdpPage key="rsf" />],
              ['/admin/research/awards', 'research.fdp', 'research', 'view', [['research', 'view_all'], ['research', 'manage']], <RsFdpPage key="rsa" />],
              ['/admin/research/mous', 'research.mous_collaborations', 'research', 'mous', [['research', 'view'], ['research', 'view_all'], ['research', 'manage']], <RsMousPage key="rsm" />],
              ['/admin/research/mous/:id', 'research.mous_collaborations', 'research', 'mous', [['research', 'view'], ['research', 'view_all'], ['research', 'manage']], <RsMouPage key="rsmd" />],
              ['/admin/research/startups', 'research.incubation', 'research', 'incubation', [['research', 'view'], ['research', 'view_all'], ['research', 'manage']], <RsStartupsPage key="rss" />],
              ['/admin/research/api-score', 'research.api_score', 'research', 'manage', [['research', 'view_all'], ['hr', 'view_all']], <RsApiScorePage key="rsapi" />],
              ['/admin/research/stats', 'research.publications', 'research', 'view_all', [['reports', 'export']], <RsStatsPage key="rsst" />],
              ['/admin/documents/templates', 'documents.templates', 'templates', 'view', [['templates', 'manage'], ['certificates', 'issue']], <DocTemplatesPage key="dt" />],
              ['/admin/documents/issued', 'documents.templates', 'certificates', 'view_all', [['certificates', 'issue'], ['certificates', 'manage']], <DocIssuedPage key="di" />],
              ['/admin/documents/bulk', 'documents.bulk_generation', 'certificates', 'issue', [['certificates', 'manage']], <DocBulkPage key="db" />],
              ['/admin/documents/registers', 'documents.serial_registers', 'certificates', 'issue', [['certificates', 'view_all'], ['templates', 'manage']], <DocRegistersPage key="dr" />],
              ['/admin/documents/requests', 'documents.certificate_requests', 'certificates', 'request_approve', [['certificates', 'issue'], ['certificates', 'view_all'], ['certificates', 'manage']], <DocRequestsPage key="dq" />],
              ['/admin/documents/settings', 'documents.templates', 'templates', 'manage', [['certificates', 'manage']], <DocSettingsPage key="ds" />],
              // Phase 25 — calendar, events & facilities (narrowed by the services: self / department / college / all)
              ['/admin/events', 'events.core', 'events', 'view_all', [['events', 'organise'], ['events', 'approve'], ['events', 'manage']], <FacEventsPage key="fev" />],
              ['/admin/facilities/bookings', 'facilities.room_booking', 'facilities', 'approve_booking', [['facilities', 'view_all'], ['facilities', 'manage']], <FacBookingsPage key="fbk" />],
              ['/admin/facilities/service-desk', 'facilities.service_desk', 'facilities', 'service_assign', [['facilities', 'view_all'], ['facilities', 'manage']], <FacServiceDeskPage key="fsd" />],
              ['/admin/security', 'facilities.visitor_gate', 'facilities', 'manage', [['facilities', 'view_all']], <FacSecurityPage key="fse" />],
              ['/admin/sports', 'facilities.sports', 'sports', 'manage', [['sports', 'view_all']], <FacSportsPage key="fsp" />],
              // Phase 24 — communication advanced (audience narrowed by the services: department / college / all)
              ['/admin/comms/campaigns', 'comms.bulk_campaigns', 'communication', 'bulk', [['communication', 'send'], ['communication', 'approve'], ['communication', 'manage']], <CommsCampaignsPage key="cc" />],
              ['/admin/comms/segments', 'comms.bulk_campaigns', 'communication', 'bulk', [['communication', 'send'], ['communication', 'manage']], <CommsSegmentsPage key="cs" />],
              ['/admin/comms/emergency', 'comms.emergency_broadcast', 'communication', 'emergency', [['communication', 'manage']], <CommsEmergencyPage key="ce" />],
              ['/admin/comms/bot', 'comms.whatsapp_bot', 'communication', 'template_manage', [['communication', 'bulk'], ['communication', 'manage']], <CommsBotPage key="cb" />],
              ['/admin/comms/simulator', 'comms.bulk_campaigns', 'communication', 'manage', [['communication', 'bulk']], <CommsSimulatorPage key="csim" />],
              ['/admin/comms/analytics', 'comms.bulk_campaigns', 'communication', 'bulk', [['communication', 'approve'], ['communication', 'manage']], <CommsAnalyticsPage key="ca" />],
              // Phase 23 — accounting & budget (narrowed by the services: own / department / PI / college / all)
              ['/admin/accounting/dashboard', 'accounting.core', 'accounting', 'view_all', [['accounting', 'manage']], <AccountingDashboardPage key="ad" />],
              ['/admin/accounting/chart', 'accounting.core', 'accounting', 'view_all', [['accounting', 'manage']], <AcctChartPage key="ach" />],
              ['/admin/accounting/ledger', 'accounting.core', 'accounting', 'view_all', [['accounting', 'manage']], <AcctLedgerPage key="al" />],
              ['/admin/accounting/income', 'accounting.core', 'accounting', 'post', [['accounting', 'view_all'], ['accounting', 'manage']], <AcctIncomePage key="ai" />],
              ['/admin/accounting/expenses', 'accounting.core', 'accounting', 'post', [['accounting', 'view_all'], ['accounting', 'approve'], ['accounting', 'view']], <AcctExpensesPage key="ae" />],
              ['/admin/accounting/budgets/me', 'accounting.budgets', 'accounting', 'view', [['accounting', 'post']], <AcctMyBudgetPage key="abm" />],
              ['/admin/accounting/budgets', 'accounting.budgets', 'accounting', 'view_all', [['accounting', 'manage'], ['accounting', 'approve']], <AcctBudgetsPage key="ab" />],
              ['/admin/accounting/grants', 'accounting.grants_ledger', 'accounting', 'view_all', [['accounting', 'manage'], ['research', 'view_all']], <AcctGrantsPage key="ag" />],
              ['/admin/accounting/reconciliation', 'accounting.core', 'accounting', 'reconcile', [['accounting', 'view_all']], <AcctReconciliationPage key="ar" />],
              ['/admin/accounting/gst', 'accounting.gst_reports', 'accounting', 'view_all', [['accounting', 'manage']], <AcctGstPage key="agst" />],
              ['/admin/accounting/exports', 'accounting.tally_export', 'accounting', 'export', [['accounting', 'view_all']], <AcctExportsPage key="aex" />],
              ['/admin/accounting/statements', 'accounting.core', 'accounting', 'view_all', [['reports', 'export']], <AcctStatementsPage key="ast" />],
              ['/admin/accounting/periods', 'accounting.core', 'accounting', 'manage', [], <AcctPeriodsPage key="ap" />],
              // Phase 22 — inventory & procurement (narrowed by the services: own / custodian / store keeper / department / college / all)
              ['/admin/inventory/items', 'inventory.core', 'inventory', 'view_all', [['inventory', 'manage'], ['inventory', 'issue'], ['inventory', 'receive']], <InvItemsPage key="ii" />],
              ['/admin/inventory/stores', 'inventory.core', 'inventory', 'view_all', [['inventory', 'manage'], ['inventory', 'issue'], ['inventory', 'receive'], ['inventory', 'approve_indent']], <InvStoresPage key="is" />],
              ['/admin/inventory/suppliers', 'inventory.core', 'inventory', 'manage', [['procurement', 'view_all'], ['procurement', 'quote']], <InvSuppliersPage key="isu" />],
              ['/admin/inventory/indents', 'inventory.procurement', 'inventory', 'view_all', [['inventory', 'indent'], ['inventory', 'approve_indent'], ['inventory', 'issue'], ['inventory', 'manage']], <InvIndentsPage key="iin" />],
              ['/admin/inventory/quotations', 'inventory.procurement', 'procurement', 'quote', [['procurement', 'manage'], ['inventory', 'manage']], <InvQuotationsPage key="iq" />],
              ['/admin/inventory/purchase-orders', 'inventory.procurement', 'procurement', 'view_all', [['procurement', 'po_approve'], ['procurement', 'create'], ['inventory', 'manage']], <InvPurchaseOrdersPage key="ipo" />],
              ['/admin/inventory/goods-receipts', 'inventory.procurement', 'inventory', 'receive', [['inventory', 'view_all'], ['inventory', 'manage']], <InvGoodsReceiptsPage key="igr" />],
              ['/admin/inventory/assets', 'inventory.assets', 'inventory', 'view_all', [['inventory', 'manage'], ['inventory', 'asset_audit'], ['inventory', 'approve_indent']], <InvAssetsPage key="ia" />],
              ['/admin/inventory/audits', 'inventory.assets', 'inventory', 'asset_audit', [['inventory', 'manage'], ['inventory', 'view_all']], <InvAuditsPage key="iau" />],
              ['/admin/inventory/bills', 'inventory.bills', 'procurement', 'bill_approve', [['inventory', 'manage'], ['inventory', 'view_all'], ['accounting', 'view']], <InvBillsPage key="ib" />],
              ['/admin/inventory/vendor-store', 'inventory.vendor_store', 'inventory', 'issue', [['inventory', 'manage']], <InvVendorStorePage key="ivs" />],
              ['/admin/inventory/reports', 'inventory.core', 'inventory', 'view_all', [['inventory', 'manage'], ['reports', 'export']], <InventoryReportsPage key="ir" />],
              ['/admin/inventory/settings', 'inventory.core', 'inventory', 'manage', [], <InventorySettingsPage key="ist" />],
              ['/staff/indents', 'inventory.procurement', 'inventory', 'indent', [['inventory', 'view']], <StaffIndentsPage key="sin" />],
              // Phase 21 — transport (narrowed by the services: college / driver-owned / all; department for HODs)
              ['/admin/transport/fleet', 'transport.core', 'transport', 'view_all', [['transport', 'manage']], <FleetPage key="tf" />],
              ['/admin/transport/routes', 'transport.core', 'transport', 'view_all', [['transport', 'manage']], <RoutesPage key="tr" />],
              ['/admin/transport/allocations', 'transport.core', 'transport', 'view_all', [['transport', 'manage']], <TransportAllocationsPage key="ta" />],
              ['/admin/transport/trips', 'transport.core', 'transport', 'view_all', [['transport', 'manage']], <TripsPage key="tt" />],
              ['/admin/transport/live', 'transport.gps_live', 'transport', 'view_all', [['transport', 'manage']], <LiveMapPage key="tl" />],
              ['/admin/transport/devices', 'transport.gps_live', 'transport', 'manage', [], <GpsDevicesPage key="td" />],
              ['/admin/transport/reports', 'transport.core', 'transport', 'view_all', [['transport', 'manage']], <TransportReportsPage key="tz" />],
              ['/admin/transport/settings', 'transport.core', 'transport', 'manage', [], <TransportSettingsPage key="ts" />],
              ['/staff/transport', 'transport.core', 'transport', 'view', [['transport', 'manage']], <StaffTransportPage key="tsm" />],
              // Phase 20 — hostel (narrowed by the services: warden-owned hostels / college / all; department for HODs)
              ['/admin/hostel/hostels', 'hostel.core', 'hostel', 'view_all', [['hostel', 'manage'], ['hostel', 'warden']], <HostelsPage key="hh" />],
              ['/admin/hostel/applications', 'hostel.core', 'hostel', 'allot', [['hostel', 'view_all'], ['hostel', 'warden']], <HostelApplicationsPage key="ha" />],
              ['/admin/hostel/allocations', 'hostel.core', 'hostel', 'view_all', [['hostel', 'warden'], ['hostel', 'allot'], ['hostel', 'manage']], <HostelAllocationsPage key="hl" />],
              ['/admin/hostel/room-changes', 'hostel.room_change', 'hostel', 'warden', [['hostel', 'manage']], <RoomChangesPage key="hr" />],
              ['/admin/hostel/roll-call', 'hostel.night_roll_call', 'hostel', 'roll_call', [['hostel', 'warden'], ['hostel', 'manage']], <RollCallPage key="hc" />],
              ['/admin/hostel/mess', 'hostel.mess', 'hostel', 'mess_manage', [['hostel', 'warden'], ['hostel', 'manage']], <MessPage key="hm" />],
              ['/admin/hostel/visitors', 'hostel.visitors', 'hostel', 'gate', [['hostel', 'warden'], ['hostel', 'manage'], ['hostel', 'view_all']], <HostelVisitorsPage key="hv" />],
              ['/admin/hostel/leaves', 'hostel.leave_outpass', 'hostel', 'warden', [['hostel', 'gate'], ['hostel', 'manage'], ['hostel', 'view_all']], <HostelLeavesPage key="hp" />],
              ['/admin/hostel/complaints', 'hostel.complaints', 'hostel', 'warden', [['hostel', 'manage'], ['hostel', 'view_all']], <HostelComplaintsPage key="hx" />],
              ['/admin/hostel/discipline', 'hostel.discipline', 'hostel', 'discipline', [['hostel', 'warden'], ['hostel', 'manage'], ['hostel', 'view_all']], <HostelDisciplinePage key="hd" />],
              ['/admin/hostel/quarters', 'hostel.staff_quarters', 'hostel', 'manage', [['hostel', 'view_all']], <QuartersPage key="hq" />],
              ['/admin/hostel/reports', 'hostel.core', 'hostel', 'view_all', [['hostel', 'warden'], ['hostel', 'manage']], <HostelReportsPage key="hz" />],
              // Phase 19 — library (narrowed by the services: own / wards / department / college / all)
              ['/admin/library/catalogue', 'library.core', 'library', 'view_all', [['library', 'manage'], ['library', 'circulate']], <CataloguePage key="lc" />],
              ['/admin/library/circulation', 'library.core', 'library', 'circulate', [['library', 'manage']], <CirculationPage key="lx" />],
              ['/admin/library/issues', 'library.core', 'library', 'view_all', [['library', 'manage'], ['library', 'circulate']], <LibraryIssuesPage key="li" />],
              ['/admin/library/reservations', 'library.core', 'library', 'circulate', [['library', 'manage']], <LibraryReservationsPage key="lr" />],
              ['/admin/library/fines', 'library.fines', 'library', 'fines', [['library', 'manage']], <LibraryFinesPage key="lf" />],
              ['/admin/library/members', 'library.core', 'library', 'view_all', [['library', 'manage']], <LibraryMembersPage key="lm" />],
              ['/admin/library/eresources', 'library.eresources', 'library', 'manage', [], <EresourcesPage key="le" />],
              ['/admin/library/ill', 'library.inter_library_loan', 'library', 'manage', [], <IllPage key="ll" />],
              ['/admin/library/stock-verification', 'library.core', 'library', 'manage', [], <StockVerificationPage key="ls" />],
              ['/admin/library/reports', 'library.core', 'library', 'view_all', [['library', 'manage']], <LibraryReportsPage key="lp" />],
              // Phase 18 — degrees & convocation (narrowed by the services: units / institution)
              ['/admin/degrees/eligibility', 'degrees.eligibility', 'degrees', 'view_all', [['degrees', 'manage'], ['degrees', 'award']], <DegreeEligibilityPage key="de" />],
              ['/admin/degrees/convocations', 'degrees.convocation', 'degrees', 'convocation_manage', [['degrees', 'view_all']], <ConvocationsPage key="dc" />],
              ['/admin/degrees/awards', 'degrees.certificates', 'degrees', 'award', [['degrees', 'issue'], ['degrees', 'view_all'], ['degrees', 'create']], <AwardsPage key="da" />],
              ['/admin/degrees/provisional', 'degrees.provisional', 'degrees', 'issue', [], <ProvisionalPage key="dp" />],
              ['/admin/degrees/credentials', 'degrees.digilocker_nad', 'degrees', 'issue', [], <CredentialsPage key="dd" />],
              ['/admin/degrees/stats', 'degrees.certificates', 'degrees', 'view_all', [], <GraduationStatsPage key="ds" />],
              // Phase 17 — OBE attainment (narrowed by the services: own offerings / units / institution)
              ['/admin/obe/config', 'obe.attainment', 'obe', 'configure', [['obe', 'view'], ['obe', 'view_all'], ['obe', 'manage']], <ObeConfigPage key="oc" />],
              ['/admin/obe/program-attainment', 'obe.attainment', 'obe', 'view', [['obe', 'view_all'], ['obe', 'manage']], <ProgramAttainmentPage key="op" />],
              ['/admin/obe/offerings/:id/attainment', 'obe.attainment', 'obe', 'view', [['obe', 'view_all'], ['obe', 'manage'], ['obe', 'compute']], <OfferingAttainmentPage key="oo" />],
              ['/admin/obe/trend', 'obe.attainment', 'obe', 'view', [['obe', 'view_all'], ['obe', 'manage']], <AttainmentTrendPage key="ot" />],
              ['/admin/obe/cqi', 'obe.cqi', 'obe', 'manage', [['obe', 'view'], ['obe', 'view_all']], <CqiBoardPage key="oq" />],
              ['/admin/obe/exports', 'obe.nba_export', 'obe', 'export', [], <NbaExportPage key="ox" />],
              // Phase 15 — result registers, analysis, rank lists, legacy import
              ['/admin/results/tabulation', 'results.rank_lists', 'results', 'view_all', [['results', 'manage']], <TabulationPage key="rt" />],
              ['/admin/results/analysis', 'results.rank_lists', 'results', 'view_all', [['results', 'manage']], <ResultAnalysisPage key="ra" />],
              ['/admin/results/rank-lists', 'results.rank_lists', 'results', 'view_all', [['results', 'manage']], <RankListPage key="rr" />],
              ['/admin/results/legacy-import', 'results.legacy_import', 'results', 'legacy_import', [], <LegacyImportPage key="rl" />],
              // Phase 14 — exam sessions (exam cell / COE; HOD and auditors read)
              ['/admin/exams/sessions', 'exams.sessions', 'exams', 'view_all', [['exams', 'configure'], ['exams', 'manage'], ['exams', 'view']], <ExamSessionsPage key="es" />],
              ['/admin/exams/sessions/:id', 'exams.sessions', 'exams', 'view_all', [['exams', 'configure'], ['exams', 'manage'], ['exams', 'view']], <ExamSessionWorkspacePage key="ew" />],
              // Phase 13 — marks verification / locks, OBE programme outcomes
              ['/admin/assessment/verification', 'assessment.marks_workflow', 'marks', 'verify', [], <MarksVerificationPage key="mv" />],
              ['/admin/assessment/locks', 'assessment.marks_workflow', 'marks', 'lock', [], <MarksLocksPage key="ml" />],
              ['/admin/obe/programs', 'obe.definitions', 'obe', 'manage', [['obe', 'view'], ['obe', 'view_all']], <ObeProgramsPage key="op" />],
              ['/admin/obe/programs/:id', 'obe.definitions', 'obe', 'manage', [['obe', 'view'], ['obe', 'view_all']], <ProgramOutcomesPage key="po" />],
              // Phase 12 — fees (accountant / registrar / auditor; HOD + offices reach no-dues and scholarships)
              ['/admin/fees', 'fees.core', 'fees', 'view_all', [['fees', 'collect']], <FeesDashboardPage key="fd" />],
              ['/admin/fees/collect', 'fees.core', 'fees', 'collect', [], <FeeCollectPage key="fc" />],
              ['/admin/fees/structures', 'fees.core', 'fees', 'structure_manage', [['fees', 'view_all']], <FeeStructuresPage key="fs" />],
              ['/admin/fees/discounts', 'fees.discounts', 'fees', 'concession', [['fees', 'view_all'], ['fees', 'approve']], <FeeDiscountsPage key="fdi" />],
              ['/admin/fees/fines', 'fees.fines', 'fees', 'structure_manage', [['fees', 'view_all']], <FeeFinesPage key="ff" />],
              ['/admin/fees/invoices', 'fees.core', 'fees', 'view_all', [['fees', 'view'], ['fees', 'collect']], <FeeInvoicesPage key="fi" />],
              ['/admin/fees/payments', 'fees.core', 'fees', 'view_all', [['fees', 'collect'], ['fees', 'cancel_receipt']], <FeePaymentsPage key="fp" />],
              ['/admin/fees/online', 'fees.online_payment', 'fees', 'view_all', [['fees', 'collect']], <FeeOnlinePage key="fo" />],
              ['/admin/fees/reconcile', 'fees.offline_challan_reconciliation', 'fees', 'reconcile', [], <FeeReconcilePage key="fr" />],
              ['/admin/fees/day-book', 'fees.core', 'fees', 'view_all', [['fees', 'collect']], <FeeDayBookPage key="fb" />],
              ['/admin/fees/refunds', 'fees.refunds', 'fees', 'refund', [['fees', 'view_all'], ['fees', 'approve']], <FeeRefundsPage key="frf" />],
              ['/admin/fees/scholarships', 'fees.scholarships', 'scholarships', 'view_all', [['scholarships', 'verify'], ['scholarships', 'approve'], ['scholarships', 'sanction'], ['scholarships', 'disburse']], <FeeScholarshipsPage key="fsc" />],
              ['/admin/fees/no-dues', 'fees.no_dues', 'no_dues', 'approve', [['no_dues', 'view_all']], <FeeNoDuesPage key="fnd" />],
              ['/admin/fees/reports', 'fees.core', 'fees', 'view_all', [['fees', 'export']], <FeeReportsPage key="frp" />],
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
          { path: '/me/messages', element: page(<CommsMyMessagesPage />) },
          { path: '/assistant', element: page(<CommsAssistantPage />) },
          // Phase 26 — staff documents (experience / service / NOC requests)
          { path: '/staff/documents', element: page(<MyDocumentsPage />) },
          // Phase 25 — self-service campus pages (the API scopes every list to the caller)
          { path: '/calendar', element: page(<FacCalendarPage />) },
          { path: '/events', element: page(<FacEventsPage />) },
          { path: '/facilities/bookings', element: page(<FacBookingsPage />) },
          { path: '/requests', element: page(<FacServiceDeskPage />) },
          { path: '/wellness', element: page(<FacWellnessPage />) },
          { path: '/sports', element: page(<FacSportsPage />) },
          { path: '/wallet', element: page(<FacWalletPage />) },
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
              ['timetable', <MyTimetablePage key="t" />],
              ['attendance', <StudentAttendancePage key="a" />],
              ['fees', <StudentFeesPage key="f" />],
              ['marks', <StudentMarksPage key="mk" />],
              ['exams', <StudentExamsPage key="ex" />],
              ['results', <StudentResultsPage key="res" />],
              ['courses/:offeringId', <StudentCoursePage key="sc" />],
              ['courses/:offeringId/outcomes', <FeatureRoute key="so" feature="obe.attainment"><StudentOutcomesPage /></FeatureRoute>],
              ['degree', <FeatureRoute key="dg" feature="degrees.eligibility"><StudentDegreePage /></FeatureRoute>],
              ['library', <FeatureRoute key="lb" feature="library.core"><MyLibraryPage /></FeatureRoute>],
              ['hostel', <FeatureRoute key="hs" feature="hostel.core"><StudentHostelPage /></FeatureRoute>],
              ['exams/reval', <FeatureRoute key="srv" feature="results.revaluation"><StudentRevalPage /></FeatureRoute>],
              ['exams/malpractice', <FeatureRoute key="smp" feature="results.malpractice"><StudentMalpracticePage /></FeatureRoute>],
              ['transcripts', <FeatureRoute key="str" feature="results.transcripts"><StudentTranscriptsPage /></FeatureRoute>],
              ['transport', <FeatureRoute key="tp" feature="transport.core"><MyTransportPage /></FeatureRoute>],
              ['documents', <FeatureRoute key="doc" feature="documents.templates"><MyDocumentsPage /></FeatureRoute>],
              ['mentor', <FeatureRoute key="ssm" feature="mentoring.core"><SsStudentMentorPage /></FeatureRoute>],
              ['grievances', <FeatureRoute key="ssg" feature="grievances.core"><SsStudentGrievancesPage /></FeatureRoute>],
              ['discipline', <FeatureRoute key="ssd" feature="discipline.core"><SsStudentDisciplinePage /></FeatureRoute>],
              ['surveys', <FeatureRoute key="sss" feature="surveys.core"><SsMySurveysPage /></FeatureRoute>],
              ['clubs', <FeatureRoute key="ssc" feature="clubs.core"><SsStudentClubsPage /></FeatureRoute>],
              ['placement', <FeatureRoute key="pls" feature="placement.core"><PlStudentPlacementPage /></FeatureRoute>],
            ] as const
          ).map(([path, node]) => ({ path, element: page(<UndertakingGate>{node}</UndertakingGate>) })),
        ],
      },
      {
        path: '/parent',
        element: <PortalRoute roles={['parent']} title="Parent" />,
        children: [
          { index: true, element: page(<FeatureRoute feature="portals.parent"><ParentHomePage /></FeatureRoute>) },
          { path: 'timetable', element: page(<FeatureRoute feature="timetable.core"><MyTimetablePage /></FeatureRoute>) },
          { path: 'attendance', element: page(<FeatureRoute feature="attendance.core"><ParentAttendancePage /></FeatureRoute>) },
          { path: 'fees', element: page(<FeatureRoute feature="fees.core"><ParentFeesPage /></FeatureRoute>) },
          { path: 'exams/:studentId', element: page(<FeatureRoute feature="exams.sessions"><ParentExamsPage /></FeatureRoute>) },
          { path: 'results/:studentId', element: page(<FeatureRoute feature="results.publication_portal"><ParentResultsPage /></FeatureRoute>) },
          { path: 'library', element: page(<FeatureRoute feature="library.core"><WardLibraryPage /></FeatureRoute>) },
          { path: 'hostel', element: page(<FeatureRoute feature="hostel.core"><ParentHostelPage /></FeatureRoute>) },
          { path: 'transport', element: page(<FeatureRoute feature="transport.core"><ParentTransportPage /></FeatureRoute>) },
          { path: 'documents', element: page(<FeatureRoute feature="documents.templates"><WardDocumentsPage /></FeatureRoute>) },
          { path: 'support', element: page(<FeatureRoute feature="mentoring.core"><SsParentSupportPage /></FeatureRoute>) },
          { path: 'placement', element: page(<FeatureRoute feature="placement.core"><PlParentPlacementPage /></FeatureRoute>) },
        ],
      },
      {
        path: '/faculty',
        element: <PortalRoute roles={['faculty', 'guest_faculty']} title="Faculty" />,
        children: [
          { index: true, element: page(<PortalHomePage />) },
          { path: 'offerings', element: page(<FacultyOfferingsPage />) },
          { path: 'offerings/:id', element: page(<OfferingRosterPage />) },
          // Phase 15 — evaluator portal (dummy numbers only) and the offering result sheet
          { path: 'evaluation', element: page(<FeatureRoute feature="exams.coding_dummy"><EvaluatorPortalPage /></FeatureRoute>) },
          { path: 'offerings/:id/results', element: page(<FeatureRoute feature="results.publication_portal"><OfferingResultsPage /></FeatureRoute>) },
          { path: 'library', element: page(<FeatureRoute feature="library.core"><MyLibraryPage /></FeatureRoute>) },
          { path: 'grants', element: page(<FeatureRoute feature="accounting.grants_ledger"><AcctFacultyGrantsPage /></FeatureRoute>) },
          // Phase 17 — CO attainment of an own offering
          { path: 'offerings/:id/attainment', element: page(<FeatureRoute feature="obe.attainment"><OfferingAttainmentPage /></FeatureRoute>) },
          // Phase 14 — exam duties and question-paper setting
          { path: 'duties', element: page(<FeatureRoute feature="exams.invigilation"><MyDutiesPage /></FeatureRoute>) },
          { path: 'qp', element: page(<FeatureRoute feature="exams.qp_management"><MyQpPage /></FeatureRoute>) },
          // Phase 13 — marks, CIA, LMS, lesson plan, projects, question bank, course outcomes
          { path: 'marks/:offeringId', element: page(<FeatureRoute feature="assessment.internal_marks"><FacultyMarksPage /></FeatureRoute>) },
          { path: 'offerings/:id/cia', element: page(<FeatureRoute feature="assessment.internal_marks"><CiaPage /></FeatureRoute>) },
          { path: 'offerings/:id/lms', element: page(<FeatureRoute feature="lms.content"><OfferingLmsPage /></FeatureRoute>) },
          { path: 'offerings/:id/plan', element: page(<FeatureRoute feature="lms.lesson_plans"><LessonPlanPage /></FeatureRoute>) },
          { path: 'projects', element: page(<FeatureRoute feature="assessment.projects"><FacultyProjectsPage /></FeatureRoute>) },
          { path: 'question-bank', element: page(<FeatureRoute feature="lms.question_bank"><QuestionBankPage /></FeatureRoute>) },
          { path: 'courses/:id/outcomes', element: page(<FeatureRoute feature="obe.definitions"><CourseOutcomesPage /></FeatureRoute>) },
          { path: 'timetable', element: page(<FeatureRoute feature="timetable.core"><MyTimetablePage /></FeatureRoute>) },
          { path: 'attendance', element: page(<FeatureRoute feature="attendance.core"><FacultyAttendancePage /></FeatureRoute>) },
          { path: 'attendance/summary', element: page(<FeatureRoute feature="attendance.core"><FacultySummaryPage /></FeatureRoute>) },
          { path: 'mentees', element: page(<FeatureRoute feature="mentoring.core"><SsMenteesPage /></FeatureRoute>) },
          { path: 'mentees/:enrollmentId', element: page(<FeatureRoute feature="mentoring.core"><SsMentee360Page /></FeatureRoute>) },
          { path: 'surveys', element: page(<FeatureRoute feature="surveys.core"><SsFacultySurveysPage /></FeatureRoute>) },
          { path: 'internships', element: page(<FeatureRoute feature="placement.internships"><PlFacultyInternshipsPage /></FeatureRoute>) },
          // Phase 30 — my research (profile, publications, patents, projects PI dashboard, incentives, FDP, API score)
          { path: 'research', element: page(<FeatureRoute feature="research.publications"><RsFacultyResearchPage /></FeatureRoute>) },
          { path: 'research/projects/:id', element: page(<FeatureRoute feature="research.projects_grants"><RsProjectPage /></FeatureRoute>) },
          { path: 'documents', element: page(<FeatureRoute feature="documents.templates"><MyDocumentsPage /></FeatureRoute>) },
        ],
      },
      {
        path: '/alumni',
        element: <PortalRoute roles={['alumni']} title="Alumni" />,
        children: [
          // Phase 29 — alumni portal {alumni.portal}: home, profile & privacy, directory, events, jobs, give
          { index: true, element: page(<FeatureRoute feature="alumni.portal"><AlHomePage /></FeatureRoute>) },
          { path: 'profile', element: page(<FeatureRoute feature="alumni.portal"><AlProfileSelfPage /></FeatureRoute>) },
          { path: 'directory', element: page(<FeatureRoute feature="alumni.portal"><AlDirectoryPage portal /></FeatureRoute>) },
          { path: 'events', element: page(<FeatureRoute feature="alumni.core"><AlEventsPortalPage /></FeatureRoute>) },
          { path: 'jobs', element: page(<FeatureRoute feature="alumni.jobs_board"><AlJobsPortalPage /></FeatureRoute>) },
          { path: 'give', element: page(<FeatureRoute feature="alumni.fundraising"><AlGivePage /></FeatureRoute>) },
          { path: 'documents', element: page(<FeatureRoute feature="documents.templates"><MyDocumentsPage /></FeatureRoute>) },
        ],
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
        children: [{ index: true, element: page(<FeatureRoute feature="transport.core"><DriverPage /></FeatureRoute>) }],
      },
      {
        path: '/vendor',
        element: <PortalRoute roles={['vendor']} title="Supplier" />,
        children: [{ index: true, element: page(<FeatureRoute feature="inventory.vendor_portal"><VendorHomePage /></FeatureRoute>) }],
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
        // Phase 28 — recruiter portal {placement.recruiter_portal}: own company drives, consented applicants, rounds, offers
        children: [
          { index: true, element: page(<FeatureRoute feature="placement.recruiter_portal"><PlRecruiterDrivesPage /></FeatureRoute>) },
          { path: 'drives', element: page(<FeatureRoute feature="placement.recruiter_portal"><PlRecruiterDrivesPage /></FeatureRoute>) },
          { path: 'drives/:id', element: page(<FeatureRoute feature="placement.recruiter_portal"><PlRecruiterDrivePage /></FeatureRoute>) },
        ],
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
