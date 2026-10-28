import 'package:flutter/material.dart';

import '../../features/academic_structure/academic_structure_screens.dart';
import '../../features/announcements/announcements_screens.dart';
import '../../features/approvals/approvals_screen.dart';
import '../../features/auth/profile_screens.dart';
import '../../features/hr/hr_screens.dart';
import '../../features/notifications/notifications_screens.dart';
import '../../features/registration/registration_screens.dart';
import '../../features/attendance/attendance_screens.dart';
import '../../features/fees/fees_screens.dart';
import '../../features/assessment/assessment_screens.dart';
import '../../features/exams/exam_screens.dart';
import '../../features/results/result_screens.dart';
import '../../features/obe/obe_screens.dart';
import '../../features/degrees/degree_screens.dart';
import '../../features/library/library_screens.dart';
import '../../features/hostel/hostel_screens.dart';
import '../../features/transport/transport_screens.dart';
import '../../features/inventory/inventory_screens.dart';
import '../../features/accounting/accounting_screens.dart';
import '../../features/communication/comms_screens.dart';
import '../../features/documents/documents_screens.dart';
import '../../features/student_support/support_screens.dart';
import '../../features/facilities/facilities_screens.dart';
import '../../features/results/post_result_screens.dart';
import '../../features/timetable/timetable_screens.dart';
import '../../features/settings/settings_screen.dart';
import '../../features/admissions/admissions_screens.dart';
import '../../features/alumni/alumni_screens.dart';
import '../../features/placement/placement_screens.dart';
import '../../features/affiliation/affiliation_screens.dart';
import '../../features/analytics/analytics_screens.dart';
import '../../features/reports/reports_screens.dart';
import '../../features/audit/audit_screens.dart';
import '../../features/portals/portal_screens.dart';
import '../../features/integrations/integrations_screens.dart';
import '../../features/privacy/privacy_screens.dart';
import '../../features/website/website_screens.dart';
import '../../features/saas/saas_screens.dart';
import '../../features/governance/governance_screens.dart';
import '../../features/iqac/iqac_screens.dart';
import '../../features/phd/phd_screens.dart';
import '../../features/research/research_screens.dart';
import '../../features/students/students_screens.dart';
import '../../shared/widgets/placeholder_screen.dart';
import 'routes.dart';

/// A registered screen: route → widget builder, gated by permission/feature (docs/Mobile_App_UI_Structure.md §1).
class ScreenEntry {
  const ScreenEntry({
    required this.route,
    required this.builder,
    this.titleKey,
    this.permission,
    this.feature,
    this.roles = const [],
  });

  final String route;
  final Widget Function(BuildContext context, Map<String, String> params)
      builder;
  final String? titleKey;

  /// `module:action` required to open the screen (null = any authenticated user).
  final String? permission;

  /// Feature key required (null = none).
  final String? feature;

  /// Restrict to these role slugs (empty = any).
  final List<String> roles;
}

/// Single route → widget map for tabs and pushed routes. Phases register their screens here (NN.10);
/// unknown routes resolve to [PlaceholderScreen].
class ScreenRegistry {
  ScreenRegistry._();

  static final Map<String, ScreenEntry> _entries = {
    AppRoutes.home: ScreenEntry(
      route: AppRoutes.home,
      titleKey: 'home',
      // Phase 07 — student / parent dashboards (other roles keep the placeholder)
      builder: (_, __) => const HomeScreen(),
    ),
    AppRoutes.more: ScreenEntry(
      route: AppRoutes.more,
      titleKey: 'more',
      builder: (_, __) => const PlaceholderScreen(title: 'More'),
    ),
    AppRoutes.approvals: ScreenEntry(
      route: AppRoutes.approvals,
      titleKey: 'approvals',
      feature: 'workflow.engine',
      builder: (_, __) => const ApprovalsScreen(),
    ),
    AppRoutes.notifications: ScreenEntry(
      route: AppRoutes.notifications,
      titleKey: 'notifications',
      builder: (_, __) => const NotificationsScreen(),
    ),
    // Phase 02 — profile, password, MFA and sessions (auth screens are reachable by every signed-in user)
    AppRoutes.profile: ScreenEntry(
      route: AppRoutes.profile,
      titleKey: 'profile',
      builder: (_, __) => const ProfileScreen(),
    ),
    AppRoutes.profilePassword: ScreenEntry(
      route: AppRoutes.profilePassword,
      titleKey: 'changePassword',
      builder: (_, __) => const ChangePasswordScreen(),
    ),
    AppRoutes.profileMfa: ScreenEntry(
      route: AppRoutes.profileMfa,
      titleKey: 'mfa',
      feature: 'security.mfa',
      builder: (_, __) => const MfaSetupScreen(),
    ),
    AppRoutes.profileSessions: ScreenEntry(
      route: AppRoutes.profileSessions,
      titleKey: 'sessions',
      feature: 'security.session_management',
      builder: (_, __) => const SessionsScreen(),
    ),
    // Phase 04 — notification preferences, announcements (approvals + notifications tabs replaced above)
    AppRoutes.notificationPreferences: ScreenEntry(
      route: AppRoutes.notificationPreferences,
      titleKey: 'notificationPreferences',
      feature: 'comms.preferences',
      builder: (_, __) => const NotificationPreferencesScreen(),
    ),
    AppRoutes.announcements: ScreenEntry(
      route: AppRoutes.announcements,
      titleKey: 'announcements',
      feature: 'comms.announcements',
      permission: 'communication:view',
      builder: (_, params) => AnnouncementsScreen(openId: params['id']),
    ),
    // Phase 05 — read-only academic structure (courses + syllabus; a programme-regulation's curriculum by term)
    AppRoutes.academicCourses: ScreenEntry(
      route: AppRoutes.academicCourses,
      titleKey: 'courses',
      feature: 'academics.regulations',
      permission: 'courses:view',
      builder: (_, params) => CoursesScreen(openId: params['id']),
    ),
    AppRoutes.academicCurriculum: ScreenEntry(
      route: AppRoutes.academicCurriculum,
      titleKey: 'curriculum',
      feature: 'academics.curriculum',
      // Phase 07 — students open their own curriculum through the enrolment (no `pr` param)
      builder: (_, params) => params['pr'] == null
          ? const StudentCurriculumScreen()
          : CurriculumScreen(programRegulationId: params['pr']),
    ),
    // Phase 06 — leaves, my attendance, payslips (staff self-service) and the HR tab (All | Mine segments)
    AppRoutes.hrLeaves: ScreenEntry(
      route: AppRoutes.hrLeaves,
      titleKey: 'leaves',
      feature: 'hr.leaves',
      permission: 'leaves:self',
      builder: (_, __) => const LeavesScreen(),
    ),
    AppRoutes.hrAttendance: ScreenEntry(
      route: AppRoutes.hrAttendance,
      titleKey: 'myAttendance',
      feature: 'attendance.staff',
      permission: 'attendance:staff_self',
      builder: (_, __) => const MyAttendanceScreen(),
    ),
    AppRoutes.hrPayslips: ScreenEntry(
      route: AppRoutes.hrPayslips,
      titleKey: 'payslips',
      feature: 'hr.payroll',
      permission: 'payroll:self',
      builder: (_, __) => const PayslipsScreen(),
    ),
    AppRoutes.hrTab: ScreenEntry(
      route: AppRoutes.hrTab,
      titleKey: 'hr',
      feature: 'hr.staff',
      permission: 'hr:view_all',
      builder: (_, __) => const HrTabScreen(),
    ),
    // Phase 07 — student self-service; students search → 360° for staff (scope / PII decided by the API)
    AppRoutes.studentProfile: ScreenEntry(
      route: AppRoutes.studentProfile,
      titleKey: 'profile',
      feature: 'students.self_service_profile',
      permission: 'students:self',
      builder: (_, __) => const StudentProfileScreen(),
    ),
    AppRoutes.studentUndertakings: ScreenEntry(
      route: AppRoutes.studentUndertakings,
      titleKey: 'undertakings',
      feature: 'students.undertakings',
      permission: 'students:self',
      builder: (_, __) => const StudentUndertakingsScreen(),
    ),
    AppRoutes.studentIdCard: ScreenEntry(
      route: AppRoutes.studentIdCard,
      titleKey: 'idCard',
      feature: 'students.id_cards',
      permission: 'students:self',
      builder: (_, __) => const StudentIdCardScreen(),
    ),
    AppRoutes.studentCreditTransfers: ScreenEntry(
      route: AppRoutes.studentCreditTransfers,
      titleKey: 'creditTransfers',
      feature: 'academics.credit_transfer_mooc',
      permission: 'credit_transfers:create',
      builder: (_, __) => const StudentCreditTransfersScreen(),
    ),
    AppRoutes.studentsSearch: ScreenEntry(
      route: AppRoutes.studentsSearch,
      titleKey: 'students',
      feature: 'students.core',
      permission: 'students:view|students:view_all',
      builder: (_, __) => const StudentsSearchScreen(),
    ),
    AppRoutes.studentDetail: ScreenEntry(
      route: AppRoutes.studentDetail,
      titleKey: 'student',
      feature: 'students.core',
      permission: 'students:view|students:view_all',
      builder: (_, params) => StudentDetailScreen(id: params['id'] ?? ''),
    ),
    // Phase 08 — admissions office (applicant flows stay on the web portal /apply/:cycle)
    AppRoutes.applicantsSearch: ScreenEntry(
      route: AppRoutes.applicantsSearch,
      titleKey: 'applicants',
      feature: 'admissions.cycles',
      permission: 'admissions:view_all',
      builder: (_, __) => const ApplicantsSearchScreen(),
    ),
    AppRoutes.applicantDetail: ScreenEntry(
      route: AppRoutes.applicantDetail,
      titleKey: 'applicant',
      feature: 'admissions.cycles',
      permission: 'admissions:view_all',
      builder: (_, params) => ApplicantDetailScreen(id: params['id'] ?? ''),
    ),
    AppRoutes.enquiries: ScreenEntry(
      route: AppRoutes.enquiries,
      titleKey: 'enquiries',
      feature: 'admissions.enquiry_crm',
      permission: 'admissions:create|admissions:manage',
      builder: (_, __) => const EnquiriesScreen(),
    ),
    // Phase 09 — registration cart (student), my offerings + roster (faculty), registration approvals (advisor)
    AppRoutes.studentRegistration: ScreenEntry(
      route: AppRoutes.studentRegistration,
      titleKey: 'registration',
      feature: 'registration.self_service',
      permission: 'registration:self',
      builder: (_, __) => const StudentRegistrationScreen(),
    ),
    AppRoutes.myOfferings: ScreenEntry(
      route: AppRoutes.myOfferings,
      titleKey: 'my_offerings',
      feature: 'registration.core',
      permission: 'offerings:view|offerings:view_all',
      builder: (_, __) => const MyOfferingsScreen(),
    ),
    AppRoutes.offeringRoster: ScreenEntry(
      route: AppRoutes.offeringRoster,
      titleKey: 'roster',
      feature: 'registration.core',
      permission: 'offerings:view|offerings:view_all',
      builder: (_, params) => OfferingRosterScreen(id: params['id'] ?? ''),
    ),
    AppRoutes.registrationApprovals: ScreenEntry(
      route: AppRoutes.registrationApprovals,
      titleKey: 'registration_approvals',
      feature: 'registration.advisor_approval',
      permission: 'registration:approve',
      builder: (_, __) => const RegistrationApprovalsScreen(),
    ),
    // Phase 10 — timetable (week / day, cached offline 24 h), today's sessions, substitutions
    AppRoutes.myTimetable: ScreenEntry(
      route: AppRoutes.myTimetable,
      titleKey: 'timetable',
      feature: 'timetable.core',
      permission: 'timetable:view',
      builder: (_, __) => const MyTimetableScreen(),
    ),
    AppRoutes.todaySessions: ScreenEntry(
      route: AppRoutes.todaySessions,
      titleKey: 'today_sessions',
      feature: 'timetable.core',
      permission: 'attendance:view|attendance:self|attendance:mark',
      builder: (_, __) => const TodaySessionsScreen(),
    ),
    AppRoutes.substitutions: ScreenEntry(
      route: AppRoutes.substitutions,
      titleKey: 'substitutions',
      feature: 'timetable.substitutions',
      permission: 'timetable:substitute|timetable:approve',
      builder: (_, __) => const SubstitutionsScreen(),
    ),
    // Phase 11 — attendance (faculty tap-mark grid + offline queue, student rings / calculator, HOD condonations)
    AppRoutes.attendance: ScreenEntry(
      route: AppRoutes.attendance,
      titleKey: 'attendance',
      feature: 'attendance.core',
      permission: 'attendance:mark',
      builder: (_, __) => const FacultyAttendanceScreen(),
    ),
    AppRoutes.myAttendance: ScreenEntry(
      route: AppRoutes.myAttendance,
      titleKey: 'my_attendance',
      feature: 'attendance.core',
      permission: 'attendance:self|attendance:view',
      builder: (_, __) => const StudentAttendanceScreen(),
    ),
    AppRoutes.condonations: ScreenEntry(
      route: AppRoutes.condonations,
      titleKey: 'condonations',
      feature: 'attendance.condonation',
      permission: 'attendance:condone',
      builder: (_, __) => const CondonationRecommendScreen(),
    ),
    // Phase 16 — revaluation, malpractice, transcripts, reval queue
    AppRoutes.myReval: ScreenEntry(
      route: AppRoutes.myReval,
      titleKey: 'revaluation',
      feature: 'results.revaluation',
      permission: 'exams:self',
      builder: (_, __) => const RevalScreen(),
    ),
    AppRoutes.myMalpractice: ScreenEntry(
      route: AppRoutes.myMalpractice,
      titleKey: 'malpractice',
      feature: 'results.malpractice',
      permission: 'exams:self',
      builder: (_, __) => const MyMalpracticeScreen(),
    ),
    AppRoutes.myTranscripts: ScreenEntry(
      route: AppRoutes.myTranscripts,
      titleKey: 'transcripts',
      feature: 'results.transcripts',
      permission: 'results:self',
      builder: (_, __) => const MyTranscriptsScreen(),
    ),
    AppRoutes.revalQueue: ScreenEntry(
      route: AppRoutes.revalQueue,
      titleKey: 'reval_queue',
      feature: 'results.revaluation',
      permission: 'exams:reval',
      builder: (_, __) => const RevalQueueScreen(),
    ),
    // Phase 25 — calendar, events & facilities
    AppRoutes.sos: ScreenEntry(
      route: AppRoutes.sos,
      titleKey: 'sos',
      feature: 'facilities.emergency_sos',
      permission: 'facilities:view|facilities:book',
      builder: (_, __) => const SosScreen(),
    ),
    AppRoutes.sosResponder: ScreenEntry(
      route: AppRoutes.sosResponder,
      titleKey: 'sos_responder',
      feature: 'facilities.emergency_sos',
      permission: 'facilities:manage',
      builder: (_, __) => const SosResponderScreen(),
    ),
    AppRoutes.campusEvents: ScreenEntry(
      route: AppRoutes.campusEvents,
      titleKey: 'events',
      feature: 'events.core',
      permission: 'events:view|events:organise',
      builder: (_, __) => const CampusEventsScreen(),
    ),
    AppRoutes.serviceRequests: ScreenEntry(
      route: AppRoutes.serviceRequests,
      titleKey: 'service_requests',
      feature: 'facilities.service_desk',
      permission: 'facilities:view|facilities:book',
      builder: (_, __) => const ServiceRequestsScreen(),
    ),
    AppRoutes.wellness: ScreenEntry(
      route: AppRoutes.wellness,
      titleKey: 'wellness',
      feature: 'facilities.counselling_appointments',
      permission: 'facilities:view|facilities:book',
      builder: (_, __) => const WellnessScreen(),
    ),
    AppRoutes.wallet: ScreenEntry(
      route: AppRoutes.wallet,
      titleKey: 'wallet',
      feature: 'facilities.canteen_wallet',
      permission: 'facilities:view',
      builder: (_, __) => const WalletScreen(),
    ),
    AppRoutes.gateScan: ScreenEntry(
      route: AppRoutes.gateScan,
      titleKey: 'gate_scan',
      feature: 'facilities.visitor_gate',
      permission: 'facilities:manage',
      builder: (_, __) => const VisitorGateScanScreen(),
    ),
    // Phase 27 — student support
    AppRoutes.mentees: ScreenEntry(
      route: AppRoutes.mentees,
      titleKey: 'mentees',
      feature: 'mentoring.core',
      permission: 'mentoring:manage',
      builder: (_, __) => const MenteesScreen(),
    ),
    AppRoutes.mentorSlots: ScreenEntry(
      route: AppRoutes.mentorSlots,
      titleKey: 'mentor_slots',
      feature: 'mentoring.appointment_slots',
      permission: 'mentoring:manage',
      builder: (_, __) => const MentorSlotsScreen(),
    ),
    AppRoutes.highRisk: ScreenEntry(
      route: AppRoutes.highRisk,
      titleKey: 'high_risk',
      feature: 'mentoring.early_warning',
      permission: 'mentoring:view_all',
      builder: (_, __) => const HighRiskScreen(),
    ),
    AppRoutes.myMentor: ScreenEntry(
      route: AppRoutes.myMentor,
      titleKey: 'my_mentor',
      feature: 'mentoring.core',
      permission: 'mentoring:self',
      builder: (_, __) => const MyMentorScreen(),
    ),
    AppRoutes.grievances: ScreenEntry(
      route: AppRoutes.grievances,
      titleKey: 'grievances',
      feature: 'grievances.core',
      permission: 'grievances:create',
      builder: (_, __) => const GrievancesScreen(),
    ),
    AppRoutes.grievanceBoard: ScreenEntry(
      route: AppRoutes.grievanceBoard,
      titleKey: 'grievance_board',
      feature: 'grievances.core',
      permission: 'grievances:triage',
      builder: (_, __) => const GrievanceBoardScreen(),
    ),
    AppRoutes.disciplineNotices: ScreenEntry(
      route: AppRoutes.disciplineNotices,
      titleKey: 'discipline_notices',
      feature: 'discipline.core',
      builder: (_, __) => const DisciplineNoticesScreen(),
    ),
    AppRoutes.surveys: ScreenEntry(
      route: AppRoutes.surveys,
      titleKey: 'surveys',
      feature: 'surveys.core',
      permission: 'surveys:respond',
      builder: (_, __) => const SurveysScreen(),
    ),
    AppRoutes.clubs: ScreenEntry(
      route: AppRoutes.clubs,
      titleKey: 'clubs',
      feature: 'clubs.core',
      permission: 'clubs:view',
      builder: (_, __) => const ClubsScreen(),
    ),
    AppRoutes.hoursVerification: ScreenEntry(
      route: AppRoutes.hoursVerification,
      titleKey: 'hours_verification',
      feature: 'clubs.core',
      permission: 'clubs:verify_hours',
      builder: (_, __) => const HoursVerificationScreen(),
    ),
    AppRoutes.parentSupport: ScreenEntry(
      route: AppRoutes.parentSupport,
      titleKey: 'parent_support',
      feature: 'mentoring.core',
      permission: 'mentoring:wards',
      builder: (_, __) => const ParentSupportScreen(),
    ),
    // Phase 30 — research
    AppRoutes.research: ScreenEntry(
      route: AppRoutes.research,
      titleKey: 'research',
      feature: 'research.publications',
      permission: 'research:manage',
      builder: (_, __) => const FacultyResearchScreen(),
    ),
    AppRoutes.researchVerification: ScreenEntry(
      route: AppRoutes.researchVerification,
      titleKey: 'research_verification',
      feature: 'research.publications',
      permission: 'research:verify',
      builder: (_, __) => const ResearchVerificationScreen(),
    ),
    AppRoutes.researchApprovals: ScreenEntry(
      route: AppRoutes.researchApprovals,
      titleKey: 'research_approvals',
      feature: 'research.publications',
      permission: 'research:incentives',
      builder: (_, __) => const ResearchApprovalsScreen(),
    ),
    // Phase 32 — IQAC
    AppRoutes.iqacHub: ScreenEntry(
      route: AppRoutes.iqacHub,
      titleKey: 'iqac',
      feature: 'accreditation.aishe',
      permission: 'accreditation:manage',
      builder: (_, __) => const IqacHubScreen(),
    ),
    AppRoutes.departmentQuality: ScreenEntry(
      route: AppRoutes.departmentQuality,
      titleKey: 'department_quality',
      feature: 'accreditation.aishe',
      permission: 'accreditation:evidence',
      builder: (_, __) => const IqacHubScreen(department: true),
    ),
    // Phase 37 — audit & security (read-only), COE exam audit summary
    AppRoutes.auditHub: ScreenEntry(
      route: AppRoutes.auditHub,
      titleKey: 'audit_logs',
      feature: 'core.audit_logs',
      permission: 'audit_logs:view_all|audit_logs:security',
      builder: (_, __) => const AuditHubScreen(),
    ),
    AppRoutes.examAudit: ScreenEntry(
      route: AppRoutes.examAudit,
      titleKey: 'exam_audit',
      feature: 'exams.sessions',
      permission: 'exams:audit',
      builder: (_, __) => const ExamAuditSummaryScreen(),
    ),
    // Phase 40 — website quick actions (institution admin / registrar)
    AppRoutes.websiteQuick: ScreenEntry(
      route: AppRoutes.websiteQuick,
      titleKey: 'website',
      feature: 'website.core',
      permission: 'website:manage|website:publish',
      builder: (_, __) => const WebsiteQuickScreen(),
    ),
    // Phase 43 — my consents / data requests (every signed-in user)
    AppRoutes.privacy: ScreenEntry(
      route: AppRoutes.privacy,
      titleKey: 'privacy',
      feature: 'privacy.dpdp_consent',
      builder: (_, __) => const PrivacyScreen(),
    ),
    // Phase 41 — integration health (institution admin)
    AppRoutes.integrationsHealth: ScreenEntry(
      route: AppRoutes.integrationsHealth,
      titleKey: 'integrations',
      feature: 'core.settings',
      permission: 'integrations:view|integrations:manage',
      builder: (_, __) => const IntegrationsHealthScreen(),
    ),
    // Phase 39 — notification centre + preferences (self only)
    AppRoutes.notificationCentre: ScreenEntry(
      route: AppRoutes.notificationCentre,
      titleKey: 'notifications',
      feature: 'core.notifications_inapp',
      builder: (_, __) => const NotificationCentreScreen(),
    ),
    AppRoutes.notificationSettings: ScreenEntry(
      route: AppRoutes.notificationSettings,
      titleKey: 'notifications',
      feature: 'comms.preferences',
      builder: (_, __) => const NotificationPreferencesScreen(),
    ),
    // Phase 38 — platform hub, tenant support / billing
    AppRoutes.platformHub: ScreenEntry(
      route: AppRoutes.platformHub,
      titleKey: 'platform',
      feature: 'core.institution',
      permission: 'platform:view',
      builder: (_, __) => const PlatformHubScreen(),
    ),
    AppRoutes.tenantSupport: ScreenEntry(
      route: AppRoutes.tenantSupport,
      titleKey: 'support',
      feature: 'core.settings',
      permission: 'support:create|support:manage',
      builder: (_, __) => const TenantSupportScreen(),
    ),
    AppRoutes.tenantBilling: ScreenEntry(
      route: AppRoutes.tenantBilling,
      titleKey: 'billing',
      feature: 'core.settings',
      permission: 'settings:manage',
      builder: (_, __) => const TenantBillingScreen(),
    ),
    // Phase 36 — reports
    AppRoutes.reports: ScreenEntry(
      route: AppRoutes.reports,
      titleKey: 'reports',
      feature: 'reports.core',
      permission: 'reports:run|reports:view',
      builder: (_, __) => const ReportsScreen(),
    ),
    // Phase 35 — early warning analytics
    AppRoutes.riskCohort: ScreenEntry(
      route: AppRoutes.riskCohort,
      titleKey: 'early_warning',
      feature: 'analytics.early_warning',
      permission: 'mentoring:manage|mentoring:view_all',
      builder: (_, __) => const RiskCohortScreen(),
    ),
    // Phase 34 — affiliation
    AppRoutes.collegeAffiliation: ScreenEntry(
      route: AppRoutes.collegeAffiliation,
      titleKey: 'affiliation',
      feature: 'affiliation.core',
      permission: 'affiliation:apply',
      builder: (_, __) => const CollegeAffiliationScreen(),
    ),
    AppRoutes.examCentreDesk: ScreenEntry(
      route: AppRoutes.examCentreDesk,
      titleKey: 'exam_centre',
      feature: 'affiliation.exam_centres',
      permission: 'affiliation:submit',
      builder: (_, __) => const ExamCentreCoordinatorScreen(),
    ),
    AppRoutes.affiliationOffice: ScreenEntry(
      route: AppRoutes.affiliationOffice,
      titleKey: 'affiliation_office',
      feature: 'affiliation.core',
      permission: 'affiliation:view_all',
      builder: (_, __) => const AffiliationOfficeScreen(),
    ),
    AppRoutes.myInspections: ScreenEntry(
      route: AppRoutes.myInspections,
      titleKey: 'inspections',
      feature: 'affiliation.inspections',
      permission: 'affiliation:inspect',
      builder: (_, __) => const InspectorScreen(),
    ),
    // Phase 33 — governance
    AppRoutes.governanceHub: ScreenEntry(
      route: AppRoutes.governanceHub,
      titleKey: 'governance',
      feature: 'governance.committees',
      permission: 'governance:view',
      builder: (_, __) => const GovernanceHubScreen(),
    ),
    AppRoutes.committeeDesk: ScreenEntry(
      route: AppRoutes.committeeDesk,
      titleKey: 'committee_desk',
      feature: 'governance.minutes',
      permission: 'governance:minutes',
      builder: (_, __) => const CommitteeDeskScreen(),
    ),
    AppRoutes.governanceApprovals: ScreenEntry(
      route: AppRoutes.governanceApprovals,
      titleKey: 'governance_approvals',
      feature: 'governance.committees',
      permission: 'governance:approve',
      builder: (_, __) => const GovernanceApprovalsScreen(),
    ),
    // Phase 31 — PhD
    AppRoutes.scholarHub: ScreenEntry(
      route: AppRoutes.scholarHub,
      titleKey: 'my_phd',
      feature: 'phd.scholar_portal',
      permission: 'phd:self',
      builder: (_, __) => const ScholarHubScreen(),
    ),
    AppRoutes.guideScholars: ScreenEntry(
      route: AppRoutes.guideScholars,
      titleKey: 'my_scholars',
      feature: 'phd.core',
      permission: 'phd:guide',
      builder: (_, __) => const GuideScholarsScreen(),
    ),
    AppRoutes.phdApprovals: ScreenEntry(
      route: AppRoutes.phdApprovals,
      titleKey: 'phd_approvals',
      feature: 'phd.core',
      permission: 'phd:manage',
      builder: (_, __) => const PhdApprovalsScreen(),
    ),
    // Phase 29 — alumni
    AppRoutes.alumniHub: ScreenEntry(
      route: AppRoutes.alumniHub,
      titleKey: 'alumni',
      feature: 'alumni.portal',
      permission: 'alumni:self',
      builder: (_, __) => const AlumniHubScreen(),
    ),
    AppRoutes.alumniOffice: ScreenEntry(
      route: AppRoutes.alumniOffice,
      titleKey: 'alumni_office',
      feature: 'alumni.core',
      permission: 'alumni:verify',
      builder: (_, __) => const AlumniCoordinatorScreen(),
    ),
    // Phase 28 — placement
    AppRoutes.placement: ScreenEntry(
      route: AppRoutes.placement,
      titleKey: 'placement',
      feature: 'placement.core',
      permission: 'placement:self',
      builder: (_, __) => const StudentPlacementScreen(),
    ),
    AppRoutes.wardPlacement: ScreenEntry(
      route: AppRoutes.wardPlacement,
      titleKey: 'ward_placement',
      feature: 'placement.core',
      permission: 'placement:wards',
      builder: (_, __) => const ParentPlacementScreen(),
    ),
    AppRoutes.placementDrives: ScreenEntry(
      route: AppRoutes.placementDrives,
      titleKey: 'placement_drives',
      feature: 'placement.core',
      permission: 'placement:drive_manage',
      builder: (_, __) => const PlacementOfficerScreen(),
    ),
    AppRoutes.internshipEvaluation: ScreenEntry(
      route: AppRoutes.internshipEvaluation,
      titleKey: 'internship_evaluation',
      feature: 'placement.internships',
      permission: 'placement:evaluate',
      builder: (_, __) => const InternshipEvaluationScreen(),
    ),
    // Phase 26 — documents
    AppRoutes.myDocuments: ScreenEntry(
      route: AppRoutes.myDocuments,
      titleKey: 'documents',
      feature: 'documents.templates',
      permission: 'certificates:self',
      builder: (_, __) => const MyDocumentsScreen(),
    ),
    AppRoutes.wardDocuments: ScreenEntry(
      route: AppRoutes.wardDocuments,
      titleKey: 'ward_documents',
      feature: 'documents.templates',
      permission: 'certificates:self',
      builder: (_, __) => const WardDocumentsScreen(),
    ),
    AppRoutes.certificateQueue: ScreenEntry(
      route: AppRoutes.certificateQueue,
      titleKey: 'certificate_queue',
      feature: 'documents.certificate_requests',
      permission: 'certificates:issue|certificates:request_approve',
      builder: (_, __) => const CertificateQueueScreen(),
    ),
    AppRoutes.verifyDocument: ScreenEntry(
      route: AppRoutes.verifyDocument,
      titleKey: 'verify_document',
      builder: (_, __) => const DocumentVerifyScreen(),
    ),
    // Phase 24 — communication advanced
    AppRoutes.campaigns: ScreenEntry(
      route: AppRoutes.campaigns,
      titleKey: 'campaigns',
      feature: 'comms.bulk_campaigns',
      permission: 'communication:bulk|communication:approve|communication:view_all',
      builder: (_, __) => const CampaignsScreen(),
    ),
    AppRoutes.emergencyBroadcast: ScreenEntry(
      route: AppRoutes.emergencyBroadcast,
      titleKey: 'emergency_broadcast',
      feature: 'comms.emergency_broadcast',
      permission: 'communication:emergency',
      builder: (_, __) => const EmergencyBroadcastScreen(),
    ),
    AppRoutes.assistant: ScreenEntry(
      route: AppRoutes.assistant,
      titleKey: 'assistant',
      feature: 'comms.ai_assistant',
      builder: (_, __) => const AssistantScreen(),
    ),
    AppRoutes.myMessages: ScreenEntry(
      route: AppRoutes.myMessages,
      titleKey: 'my_messages',
      feature: 'comms.announcements',
      permission: 'communication:view|communication:send|communication:bulk',
      builder: (_, __) => const MyMessagesScreen(),
    ),
    // Phase 23 — accounting
    AppRoutes.accountingHome: ScreenEntry(
      route: AppRoutes.accountingHome,
      titleKey: 'accounting',
      feature: 'accounting.core',
      permission: 'accounting:view_all',
      builder: (_, __) => const AccountingHomeScreen(),
    ),
    AppRoutes.departmentBudget: ScreenEntry(
      route: AppRoutes.departmentBudget,
      titleKey: 'budget',
      feature: 'accounting.budgets',
      permission: 'accounting:view',
      builder: (_, __) => const DepartmentBudgetScreen(),
    ),
    AppRoutes.myGrants: ScreenEntry(
      route: AppRoutes.myGrants,
      titleKey: 'grants',
      feature: 'accounting.grants_ledger',
      permission: 'accounting:view',
      builder: (_, __) => const MyGrantsScreen(),
    ),
    // Phase 22 — inventory
    AppRoutes.stockLookup: ScreenEntry(
      route: AppRoutes.stockLookup,
      titleKey: 'stock',
      feature: 'inventory.core',
      permission: 'inventory:issue',
      builder: (_, __) => const StockLookupScreen(),
    ),
    AppRoutes.grnReceive: ScreenEntry(
      route: AppRoutes.grnReceive,
      titleKey: 'receive_goods',
      feature: 'inventory.procurement',
      permission: 'inventory:receive',
      builder: (_, __) => const GrnReceiveScreen(),
    ),
    AppRoutes.myIndents: ScreenEntry(
      route: AppRoutes.myIndents,
      titleKey: 'indents',
      feature: 'inventory.procurement',
      permission: 'inventory:indent',
      builder: (_, __) => const MyIndentsScreen(),
    ),
    AppRoutes.myAssets: ScreenEntry(
      route: AppRoutes.myAssets,
      titleKey: 'my_assets',
      feature: 'inventory.assets',
      permission: 'inventory:view',
      builder: (_, __) => const MyAssetsScreen(),
    ),
    AppRoutes.assetAudit: ScreenEntry(
      route: AppRoutes.assetAudit,
      titleKey: 'asset_audit',
      feature: 'inventory.assets',
      permission: 'inventory:asset_audit',
      builder: (_, __) => const AssetAuditScanScreen(),
    ),
    // Phase 21 — transport: driver trips, my / ward transport, fleet status
    AppRoutes.driverTrips: ScreenEntry(
      route: AppRoutes.driverTrips,
      titleKey: 'driver_trips',
      feature: 'transport.core',
      permission: 'transport:driver',
      builder: (_, __) => const DriverTripsScreen(),
    ),
    AppRoutes.myTransport: ScreenEntry(
      route: AppRoutes.myTransport,
      titleKey: 'transport',
      feature: 'transport.core',
      permission: 'transport:view',
      builder: (_, __) => const MyTransportScreen(),
    ),
    AppRoutes.wardTransport: ScreenEntry(
      route: AppRoutes.wardTransport,
      titleKey: 'ward_transport',
      feature: 'transport.core',
      permission: 'transport:view',
      builder: (_, __) => const WardTransportScreen(),
    ),
    AppRoutes.fleetStatus: ScreenEntry(
      route: AppRoutes.fleetStatus,
      titleKey: 'fleet',
      feature: 'transport.core',
      permission: 'transport:manage',
      builder: (_, __) => const FleetStatusScreen(),
    ),
    // Phase 20 — hostel (students), ward hostel (parents), out-passes / gate / roll-call
    AppRoutes.myHostel: ScreenEntry(
      route: AppRoutes.myHostel,
      titleKey: 'hostel',
      feature: 'hostel.core',
      permission: 'hostel:self',
      builder: (_, __) => const StudentHostelScreen(),
    ),
    AppRoutes.wardHostel: ScreenEntry(
      route: AppRoutes.wardHostel,
      titleKey: 'ward_hostel',
      feature: 'hostel.core',
      permission: 'hostel:view',
      builder: (_, __) => const WardHostelScreen(),
    ),
    AppRoutes.outPasses: ScreenEntry(
      route: AppRoutes.outPasses,
      titleKey: 'out_passes',
      feature: 'hostel.leave_outpass',
      permission: 'hostel:warden',
      builder: (_, __) => const OutPassApprovalsScreen(),
    ),
    AppRoutes.hostelGate: ScreenEntry(
      route: AppRoutes.hostelGate,
      titleKey: 'hostel_gate',
      feature: 'hostel.gate_qr',
      permission: 'hostel:gate',
      builder: (_, __) => const GateScanScreen(),
    ),
    AppRoutes.rollCall: ScreenEntry(
      route: AppRoutes.rollCall,
      titleKey: 'roll_call',
      feature: 'hostel.night_roll_call',
      permission: 'hostel:roll_call',
      builder: (_, __) => const RollCallScreen(),
    ),
    // Phase 19 — library (members), ward library (parents), circulation scanner (librarian)
    AppRoutes.myLibrary: ScreenEntry(
      route: AppRoutes.myLibrary,
      titleKey: 'library',
      feature: 'library.core',
      permission: 'library:self',
      builder: (_, __) => const MyLibraryScreen(),
    ),
    AppRoutes.wardLibrary: ScreenEntry(
      route: AppRoutes.wardLibrary,
      titleKey: 'ward_library',
      feature: 'library.core',
      permission: 'library:self',
      builder: (_, __) => const MyLibraryScreen(ward: true),
    ),
    AppRoutes.libraryCirculation: ScreenEntry(
      route: AppRoutes.libraryCirculation,
      titleKey: 'library_circulation',
      feature: 'library.core',
      permission: 'library:circulate',
      builder: (_, __) => const LibraryCirculationScreen(),
    ),
    // Phase 18 — degree (students / alumni), eligibility, approvals, convocation-day scanner (registrar)
    AppRoutes.myDegree: ScreenEntry(
      route: AppRoutes.myDegree,
      titleKey: 'degree',
      feature: 'degrees.eligibility',
      permission: 'degrees:view',
      builder: (_, __) => const StudentDegreeScreen(),
    ),
    AppRoutes.degreeEligibility: ScreenEntry(
      route: AppRoutes.degreeEligibility,
      titleKey: 'degree_eligibility',
      feature: 'degrees.eligibility',
      permission: 'degrees:view_all',
      builder: (_, __) => const DegreeEligibilityScreen(),
    ),
    AppRoutes.awardApprovals: ScreenEntry(
      route: AppRoutes.awardApprovals,
      titleKey: 'award_approvals',
      feature: 'degrees.certificates',
      permission: 'degrees:award',
      builder: (_, __) => const AwardApprovalsScreen(),
    ),
    AppRoutes.convocationScanner: ScreenEntry(
      route: AppRoutes.convocationScanner,
      titleKey: 'convocation_scanner',
      feature: 'degrees.convocation',
      permission: 'degrees:convocation_manage',
      builder: (_, __) => const ConvocationScannerScreen(),
    ),
    // Phase 17 — attainment (faculty), attainment dashboard (HOD / IQAC), CQI actions
    AppRoutes.attainment: ScreenEntry(
      route: AppRoutes.attainment,
      titleKey: 'attainment',
      feature: 'obe.attainment',
      permission: 'obe:compute',
      builder: (_, __) => const AttainmentOfferingsScreen(),
    ),
    AppRoutes.attainmentDashboard: ScreenEntry(
      route: AppRoutes.attainmentDashboard,
      titleKey: 'attainment_dashboard',
      feature: 'obe.attainment',
      permission: 'obe:view',
      builder: (_, __) => const AttainmentDashboardScreen(),
    ),
    AppRoutes.cqiActions: ScreenEntry(
      route: AppRoutes.cqiActions,
      titleKey: 'cqi_actions',
      feature: 'obe.cqi',
      permission: 'obe:view',
      builder: (_, __) => const CqiActionsScreen(),
    ),
    // Phase 15 — results (students), evaluation (evaluators), result runs (COE / exam cell)
    AppRoutes.myResults: ScreenEntry(
      route: AppRoutes.myResults,
      titleKey: 'results',
      feature: 'results.publication_portal',
      permission: 'results:self',
      builder: (_, __) => const StudentResultsScreen(),
    ),
    AppRoutes.evaluation: ScreenEntry(
      route: AppRoutes.evaluation,
      titleKey: 'evaluation',
      feature: 'exams.coding_dummy',
      permission: 'exams:evaluate',
      builder: (_, __) => const EvaluationScreen(),
    ),
    AppRoutes.resultRuns: ScreenEntry(
      route: AppRoutes.resultRuns,
      titleKey: 'result_runs',
      feature: 'results.processing',
      permission: 'results:verify',
      builder: (_, __) => const ResultRunsScreen(),
    ),
    // Phase 14 — exams (student registration / hall ticket, faculty duties, hall attendance)
    AppRoutes.myExams: ScreenEntry(
      route: AppRoutes.myExams,
      titleKey: 'exams',
      feature: 'exams.sessions',
      permission: 'exams:self',
      builder: (_, __) => const StudentExamsScreen(),
    ),
    AppRoutes.myDuties: ScreenEntry(
      route: AppRoutes.myDuties,
      titleKey: 'exam_duties',
      feature: 'exams.invigilation',
      permission: 'exams:invigilation',
      builder: (_, __) => const MyDutiesScreen(),
    ),
    AppRoutes.examConduct: ScreenEntry(
      route: AppRoutes.examConduct,
      titleKey: 'exam_conduct',
      feature: 'exams.sessions',
      permission: 'exams:conduct',
      builder: (_, __) => const ExamConductScreen(),
    ),
    // Phase 13 — marks entry (faculty), verification (HOD), courses & marks (students)
    AppRoutes.facultyMarks: ScreenEntry(
      route: AppRoutes.facultyMarks,
      titleKey: 'marks',
      feature: 'assessment.internal_marks',
      permission: 'marks:enter',
      builder: (_, __) => const FacultyMarksScreen(),
    ),
    AppRoutes.marksVerification: ScreenEntry(
      route: AppRoutes.marksVerification,
      titleKey: 'marks_verification',
      feature: 'assessment.marks_workflow',
      permission: 'marks:verify',
      builder: (_, __) => const MarksVerificationScreen(),
    ),
    AppRoutes.myCourses: ScreenEntry(
      route: AppRoutes.myCourses,
      titleKey: 'my_courses',
      feature: 'assessment.internal_marks',
      permission: 'marks:view',
      builder: (_, __) => const StudentMarksScreen(),
    ),
    // Phase 12 — fees (student / parent tab, accountant collect + reconciliation, office no-dues sign-off)
    AppRoutes.myFees: ScreenEntry(
      route: AppRoutes.myFees,
      titleKey: 'fees',
      feature: 'fees.core',
      permission: 'fees:self',
      builder: (_, __) => const StudentFeesScreen(),
    ),
    AppRoutes.feeCollect: ScreenEntry(
      route: AppRoutes.feeCollect,
      titleKey: 'fee_collect',
      feature: 'fees.core',
      permission: 'fees:collect',
      builder: (_, __) => const CollectScreen(),
    ),
    AppRoutes.feeReconcile: ScreenEntry(
      route: AppRoutes.feeReconcile,
      titleKey: 'fee_reconcile',
      feature: 'fees.offline_challan_reconciliation',
      permission: 'fees:reconcile',
      builder: (_, __) => const ReconcileReviewScreen(),
    ),
    AppRoutes.noDuesSignoff: ScreenEntry(
      route: AppRoutes.noDuesSignoff,
      titleKey: 'no_dues_signoff',
      feature: 'fees.no_dues',
      permission: 'no_dues:approve',
      builder: (_, __) => const NoDuesSignoffScreen(),
    ),
    // Phase 03 — language / theme / college (every role; no admin editing on mobile)
    AppRoutes.settings: ScreenEntry(
      route: AppRoutes.settings,
      titleKey: 'settings',
      builder: (_, __) => const AppSettingsScreen(),
    ),
  };

  static void register(ScreenEntry entry) {
    assert(!_entries.containsKey(entry.route),
        'duplicate screen route ${entry.route}');
    _entries[entry.route] = entry;
  }

  static void registerAll(Iterable<ScreenEntry> entries) =>
      entries.forEach(register);

  static ScreenEntry? lookup(String route) => _entries[route];

  static Iterable<ScreenEntry> get all => _entries.values;

  static Widget build(
      BuildContext context, String route, Map<String, String> params) {
    final entry = _entries[route];
    if (entry == null) return PlaceholderScreen(title: route, notFound: true);
    return entry.builder(context, params);
  }
}
