import 'package:flutter/material.dart';

import '../auth/auth_state.dart';
import '../constants.dart';
import 'routes.dart';

/// A bottom tab of a role shell (≤ 5 per role, docs/Mobile_App_UI_Structure.md §2/§3).
class ShellTab {
  const ShellTab(
      {required this.titleKey,
      required this.icon,
      required this.route,
      this.permission,
      this.feature});

  final String titleKey;
  final IconData icon;
  final String route;
  final String? permission;
  final String? feature;
}

/// An entry of the More grid: `{titleKey, icon, route, color, permission, feature, roles}`.
class MoreMenuModule {
  const MoreMenuModule({
    required this.titleKey,
    required this.icon,
    required this.route,
    required this.color,
    this.permission,
    this.feature,
    this.roles = const [],
  });

  final String titleKey;
  final IconData icon;
  final String route;
  final Color color;
  final String? permission;
  final String? feature;
  final List<String> roles;

  bool visibleFor(AuthState auth) {
    if (roles.isNotEmpty &&
        !roles.any(auth.roles.contains) &&
        !auth.isSuperAdmin) {
      return false;
    }
    if (feature != null && !auth.hasFeature(feature!)) return false;
    if (permission != null && !auth.canSpec(permission!)) return false;
    return true;
  }
}

const _commonTabs = [
  ShellTab(titleKey: 'home', icon: Icons.home_outlined, route: AppRoutes.home),
  ShellTab(
      titleKey: 'notifications',
      icon: Icons.notifications_outlined,
      route: AppRoutes.notifications),
  ShellTab(
      titleKey: 'more', icon: Icons.grid_view_outlined, route: AppRoutes.more),
];

const _staffTabs = [
  ShellTab(titleKey: 'home', icon: Icons.home_outlined, route: AppRoutes.home),
  ShellTab(
      titleKey: 'approvals',
      icon: Icons.fact_check_outlined,
      route: AppRoutes.approvals),
  ShellTab(
      titleKey: 'notifications',
      icon: Icons.notifications_outlined,
      route: AppRoutes.notifications),
  ShellTab(
      titleKey: 'more', icon: Icons.grid_view_outlined, route: AppRoutes.more),
];

ShellTab _t(String key, IconData icon, String route, {String? permission, String? feature}) =>
    ShellTab(titleKey: key, icon: icon, route: route, permission: permission, feature: feature);

final _home = _t('home', Icons.home_outlined, AppRoutes.home);
final _more = _t('more', Icons.grid_view_outlined, AppRoutes.more);
final _approvals = _t('approvals', Icons.fact_check_outlined, AppRoutes.approvals);
final _alerts = _t('notifications', Icons.notifications_outlined, AppRoutes.notifications);

/// Tabs per role — docs/Mobile_App_UI_Structure.md §3 / Prompts/42 §42.6 (≤ 5 each; tabs whose feature or
/// permission the principal lacks are dropped by [RoleShellScaffold]). Unlisted roles get the staff shell.
final Map<String, List<ShellTab>> roleTabs = {
  Roles.student: [
    _home,
    _t('timetable', Icons.calendar_view_week_outlined, AppRoutes.myTimetable, feature: 'timetable.core'),
    _t('fees', Icons.payments_outlined, AppRoutes.myFees, feature: 'fees.core'),
    _t('results', Icons.school_outlined, AppRoutes.myResults),
    _more,
  ],
  Roles.parent: [
    _home,
    _t('attendance', Icons.fact_check_outlined, AppRoutes.myAttendance),
    _t('fees', Icons.payments_outlined, AppRoutes.myFees, feature: 'fees.core'),
    _alerts,
    _more,
  ],
  Roles.faculty: [
    _home,
    _t('attendance', Icons.how_to_reg_outlined, AppRoutes.attendance, feature: 'attendance.core'),
    _t('marks', Icons.edit_note_outlined, AppRoutes.facultyMarks),
    _t('courses', Icons.menu_book_outlined, AppRoutes.myCourses),
    _more,
  ],
  Roles.guestFaculty: [
    _home,
    _t('attendance', Icons.how_to_reg_outlined, AppRoutes.attendance, feature: 'attendance.core'),
    _t('marks', Icons.edit_note_outlined, AppRoutes.facultyMarks),
    _more,
  ],
  Roles.hod: [
    _home,
    _approvals,
    _t('department', Icons.groups_outlined, AppRoutes.studentsSearch, permission: 'students:view'),
    _t('reports', Icons.insights_outlined, AppRoutes.reports),
    _more,
  ],
  Roles.dean: [_home, _approvals, _t('reports', Icons.insights_outlined, AppRoutes.reports), _more],
  Roles.registrar: [
    _home,
    _approvals,
    _t('students', Icons.person_search_outlined, AppRoutes.studentsSearch, permission: 'students:view'),
    _t('reports', Icons.insights_outlined, AppRoutes.reports),
    _more,
  ],
  Roles.institutionAdmin: [
    _home,
    _approvals,
    _t('students', Icons.person_search_outlined, AppRoutes.studentsSearch, permission: 'students:view'),
    _t('reports', Icons.insights_outlined, AppRoutes.reports),
    _more,
  ],
  Roles.controllerOfExaminations: [
    _home,
    _t('sessions', Icons.event_note_outlined, AppRoutes.examConduct),
    _t('valuation', Icons.rate_review_outlined, AppRoutes.evaluation),
    _t('results', Icons.workspace_premium_outlined, AppRoutes.resultRuns),
    _more,
  ],
  Roles.examCell: [
    _home,
    _t('sessions', Icons.event_note_outlined, AppRoutes.examConduct),
    _t('valuation', Icons.rate_review_outlined, AppRoutes.evaluation),
    _more,
  ],
  Roles.accountant: [
    _home,
    _t('collect', Icons.point_of_sale_outlined, AppRoutes.feeCollect, feature: 'fees.core'),
    _t('fees', Icons.receipt_long_outlined, AppRoutes.feeReconcile, feature: 'fees.core'),
    _t('hr', Icons.badge_outlined, AppRoutes.hrTab, permission: 'hr:view_all'),
    _more,
  ],
  Roles.hrOfficer: [
    _home,
    _t('staff', Icons.badge_outlined, AppRoutes.hrTab),
    _t('leaves', Icons.event_busy_outlined, AppRoutes.hrLeaves),
    _t('attendance', Icons.fingerprint, AppRoutes.hrAttendance),
    _more,
  ],
  Roles.admissionsOfficer: [
    _home,
    _t('applicants', Icons.assignment_ind_outlined, AppRoutes.applicantsSearch),
    _t('enquiries', Icons.support_agent_outlined, AppRoutes.enquiries),
    _more,
  ],
  Roles.placementOfficer: [
    _home,
    _t('drives', Icons.work_outline, AppRoutes.placementDrives),
    _t('students', Icons.person_search_outlined, AppRoutes.studentsSearch, permission: 'students:view'),
    _more,
  ],
  Roles.hostelWarden: [
    _home,
    _t('outPasses', Icons.exit_to_app, AppRoutes.outPasses),
    _t('rollCall', Icons.checklist, AppRoutes.rollCall),
    _t('gate', Icons.qr_code_scanner, AppRoutes.hostelGate),
    _more,
  ],
  Roles.hostelGateStaff: [
    _t('gate', Icons.qr_code_scanner, AppRoutes.hostelGate),
    _t('outPasses', Icons.today_outlined, AppRoutes.outPasses),
    _t('settings', Icons.settings_outlined, AppRoutes.settings),
  ],
  Roles.librarian: [
    _home,
    _t('circulation', Icons.qr_code_scanner, AppRoutes.libraryCirculation),
    _t('library', Icons.local_library_outlined, AppRoutes.myLibrary),
    _more,
  ],
  Roles.iqacCoordinator: [
    _home,
    _t('iqac', Icons.verified_outlined, AppRoutes.iqacHub),
    _t('reports', Icons.insights_outlined, AppRoutes.reports),
    _approvals,
    _more,
  ],
  Roles.researchScholar: [
    _home,
    _t('progress', Icons.timeline_outlined, AppRoutes.scholarHub),
    _t('research', Icons.science_outlined, AppRoutes.research),
    _alerts,
    _more,
  ],
  Roles.alumni: [
    _home,
    _t('alumni', Icons.diversity_3_outlined, AppRoutes.alumniHub),
    _t('events', Icons.event_outlined, AppRoutes.campusEvents),
    _t('profile', Icons.person_outline, AppRoutes.profile),
    _more,
  ],
  Roles.driver: [
    _home,
    _t('route', Icons.directions_bus_outlined, AppRoutes.driverTrips),
    _t('settings', Icons.settings_outlined, AppRoutes.settings),
  ],
  Roles.externalExaminer: [
    _t('bundles', Icons.inventory_2_outlined, AppRoutes.evaluation),
    _t('duties', Icons.assignment_outlined, AppRoutes.myDuties),
    _t('profile', Icons.person_outline, AppRoutes.profile),
  ],
  Roles.recruiter: [
    _t('drives', Icons.work_outline, AppRoutes.placementDrives),
    _alerts,
    _t('profile', Icons.person_outline, AppRoutes.profile),
  ],
  Roles.superAdmin: [
    _t('institutions', Icons.apartment_outlined, AppRoutes.platformHub),
    _t('support', Icons.support_agent_outlined, AppRoutes.tenantSupport),
    _alerts,
    _more,
  ],
  Roles.supportAgent: [
    _t('institutions', Icons.apartment_outlined, AppRoutes.platformHub),
    _t('support', Icons.support_agent_outlined, AppRoutes.tenantSupport),
    _more,
  ],
};

/// Tabs for the principal's primary role (multi-role users switch view from More).
List<ShellTab> tabsForRole(String role) {
  final tabs = roleTabs[role];
  if (tabs != null) return tabs;
  if (Roles.portalOnly.contains(role)) return _commonTabs;
  return _staffTabs;
}

/// Roles whose lists open details in a side pane on tablets (`mobile.tablet_layout`).
const masterDetailRoles = {
  Roles.hod,
  Roles.controllerOfExaminations,
  Roles.examCell,
  Roles.accountant,
  Roles.registrar,
  Roles.institutionAdmin,
};

/// More-grid modules registered by the phases (`moreMenuModules.add(...)` in NN.10).
final List<MoreMenuModule> moreMenuModules = [
  // Phase 04 — announcements (every role with communication:view)
  const MoreMenuModule(
      titleKey: 'announcements',
      icon: Icons.campaign_outlined,
      route: AppRoutes.announcements,
      color: Colors.indigo,
      permission: 'communication:view',
      feature: 'comms.announcements'),
  // Phase 05 — courses (staff) and my curriculum (students; populated from Phase 07)
  const MoreMenuModule(
      titleKey: 'courses',
      icon: Icons.menu_book_outlined,
      route: AppRoutes.academicCourses,
      color: Colors.teal,
      permission: 'courses:view',
      feature: 'academics.regulations'),
  const MoreMenuModule(
      titleKey: 'curriculum',
      icon: Icons.account_tree_outlined,
      route: AppRoutes.academicCurriculum,
      color: Colors.deepPurple,
      feature: 'academics.curriculum',
      roles: ['student']),
  // Phase 06 — HR self-service (every staff role) and the HR module (accountant / HR officer / HOD / dean)
  const MoreMenuModule(
      titleKey: 'leaves',
      icon: Icons.event_busy_outlined,
      route: AppRoutes.hrLeaves,
      color: Colors.orange,
      permission: 'leaves:self',
      feature: 'hr.leaves'),
  const MoreMenuModule(
      titleKey: 'myAttendance',
      icon: Icons.fingerprint,
      route: AppRoutes.hrAttendance,
      color: Colors.green,
      permission: 'attendance:staff_self',
      feature: 'attendance.staff'),
  const MoreMenuModule(
      titleKey: 'payslips',
      icon: Icons.receipt_long_outlined,
      route: AppRoutes.hrPayslips,
      color: Colors.brown,
      permission: 'payroll:self',
      feature: 'hr.payroll'),
  const MoreMenuModule(
      titleKey: 'hr',
      icon: Icons.badge_outlined,
      route: AppRoutes.hrTab,
      color: Colors.cyan,
      permission: 'hr:view_all',
      feature: 'hr.staff'),
  // Phase 07 — student self-service and the staff students search (advisees / department / all per visibility)
  const MoreMenuModule(
      titleKey: 'profile',
      icon: Icons.person_outline,
      route: AppRoutes.studentProfile,
      color: Colors.blue,
      permission: 'students:self',
      feature: 'students.self_service_profile',
      roles: ['student']),
  const MoreMenuModule(
      titleKey: 'idCard',
      icon: Icons.badge,
      route: AppRoutes.studentIdCard,
      color: Colors.indigo,
      permission: 'students:self',
      feature: 'students.id_cards',
      roles: ['student']),
  const MoreMenuModule(
      titleKey: 'undertakings',
      icon: Icons.assignment_turned_in_outlined,
      route: AppRoutes.studentUndertakings,
      color: Colors.amber,
      permission: 'students:self',
      feature: 'students.undertakings',
      roles: ['student']),
  const MoreMenuModule(
      titleKey: 'creditTransfers',
      icon: Icons.swap_horiz,
      route: AppRoutes.studentCreditTransfers,
      color: Colors.pink,
      permission: 'credit_transfers:create',
      feature: 'academics.credit_transfer_mooc',
      roles: ['student']),
  const MoreMenuModule(
      titleKey: 'students',
      icon: Icons.school_outlined,
      route: AppRoutes.studentsSearch,
      color: Colors.lightBlue,
      permission: 'students:view|students:view_all',
      feature: 'students.core'),
  // Phase 08 — admissions office: applicants (document verify) and enquiries
  const MoreMenuModule(
      titleKey: 'applicants',
      icon: Icons.how_to_reg_outlined,
      route: AppRoutes.applicantsSearch,
      color: Colors.deepPurple,
      permission: 'admissions:view_all',
      feature: 'admissions.cycles'),
  const MoreMenuModule(
      titleKey: 'enquiries',
      icon: Icons.support_agent,
      route: AppRoutes.enquiries,
      color: Colors.orange,
      permission: 'admissions:create|admissions:manage',
      feature: 'admissions.enquiry_crm'),
  // Phase 09 — registration (student), my offerings (faculty), registration approvals (advisor / HOD)
  const MoreMenuModule(
      titleKey: 'registration',
      icon: Icons.playlist_add_check,
      route: AppRoutes.studentRegistration,
      color: Colors.indigo,
      permission: 'registration:self',
      feature: 'registration.self_service',
      roles: ['student']),
  const MoreMenuModule(
      titleKey: 'my_offerings',
      icon: Icons.class_outlined,
      route: AppRoutes.myOfferings,
      color: Colors.teal,
      permission: 'offerings:view',
      feature: 'registration.core',
      roles: ['faculty', 'class_advisor', 'hod', 'guest_faculty']),
  const MoreMenuModule(
      titleKey: 'registration_approvals',
      icon: Icons.fact_check_outlined,
      route: AppRoutes.registrationApprovals,
      color: Colors.green,
      permission: 'registration:approve',
      feature: 'registration.advisor_approval'),
  // Phase 10 — timetable (student / faculty), today's sessions (faculty), substitutions (faculty requests, HOD)
  const MoreMenuModule(
      titleKey: 'timetable',
      icon: Icons.calendar_view_week,
      route: AppRoutes.myTimetable,
      color: Colors.blue,
      permission: 'timetable:view',
      feature: 'timetable.core',
      roles: ['student', 'faculty', 'class_advisor', 'hod', 'guest_faculty']),
  const MoreMenuModule(
      titleKey: 'today_sessions',
      icon: Icons.today,
      route: AppRoutes.todaySessions,
      color: Colors.orange,
      permission: 'attendance:mark',
      feature: 'timetable.core',
      roles: ['faculty', 'class_advisor', 'hod', 'guest_faculty']),
  const MoreMenuModule(
      titleKey: 'substitutions',
      icon: Icons.swap_horiz,
      route: AppRoutes.substitutions,
      color: Colors.purple,
      permission: 'timetable:substitute',
      feature: 'timetable.substitutions',
      roles: ['faculty', 'class_advisor', 'hod']),
  // Phase 11 — attendance (faculty marking, student rings, HOD condonations)
  const MoreMenuModule(
      titleKey: 'attendance',
      icon: Icons.fact_check,
      route: AppRoutes.attendance,
      color: Colors.green,
      permission: 'attendance:mark',
      feature: 'attendance.core',
      roles: ['faculty', 'class_advisor', 'hod', 'guest_faculty']),
  const MoreMenuModule(
      titleKey: 'my_attendance',
      icon: Icons.donut_large,
      route: AppRoutes.myAttendance,
      color: Colors.teal,
      permission: 'attendance:self|attendance:view',
      feature: 'attendance.core',
      roles: ['student', 'parent']),
  const MoreMenuModule(
      titleKey: 'condonations',
      icon: Icons.gavel,
      route: AppRoutes.condonations,
      color: Colors.deepOrange,
      permission: 'attendance:condone',
      feature: 'attendance.condonation',
      roles: ['hod']),
  // Phase 16 — revaluation / malpractice / transcripts (students), reval queue (COE, exam cell)
  const MoreMenuModule(
      titleKey: 'revaluation',
      icon: Icons.rate_review_outlined,
      route: AppRoutes.myReval,
      color: Colors.deepOrange,
      permission: 'exams:self',
      feature: 'results.revaluation',
      roles: ['student']),
  const MoreMenuModule(
      titleKey: 'malpractice',
      icon: Icons.gavel_outlined,
      route: AppRoutes.myMalpractice,
      color: Colors.red,
      permission: 'exams:self',
      feature: 'results.malpractice',
      roles: ['student']),
  const MoreMenuModule(
      titleKey: 'transcripts',
      icon: Icons.description_outlined,
      route: AppRoutes.myTranscripts,
      color: Colors.indigo,
      permission: 'results:self',
      feature: 'results.transcripts',
      roles: ['student', 'alumni']),
  const MoreMenuModule(
      titleKey: 'reval_queue',
      icon: Icons.rule_folder_outlined,
      route: AppRoutes.revalQueue,
      color: Colors.deepOrange,
      permission: 'exams:reval',
      feature: 'results.revaluation',
      roles: ['controller_of_examinations', 'exam_cell']),
  // Phase 25 — SOS, responder, events, service requests, wellness, wallet, gate scan
  const MoreMenuModule(
      titleKey: 'sos',
      icon: Icons.sos,
      route: AppRoutes.sos,
      color: Colors.red,
      permission: 'facilities:view|facilities:book',
      feature: 'facilities.emergency_sos'),
  const MoreMenuModule(
      titleKey: 'sos_responder',
      icon: Icons.emergency_share_outlined,
      route: AppRoutes.sosResponder,
      color: Colors.red,
      permission: 'facilities:manage',
      feature: 'facilities.emergency_sos'),
  const MoreMenuModule(
      titleKey: 'events',
      icon: Icons.event_outlined,
      route: AppRoutes.campusEvents,
      color: Colors.teal,
      permission: 'events:view|events:organise',
      feature: 'events.core'),
  const MoreMenuModule(
      titleKey: 'service_requests',
      icon: Icons.build_outlined,
      route: AppRoutes.serviceRequests,
      color: Colors.brown,
      permission: 'facilities:view|facilities:book',
      feature: 'facilities.service_desk'),
  const MoreMenuModule(
      titleKey: 'wellness',
      icon: Icons.favorite_outline,
      route: AppRoutes.wellness,
      color: Colors.pink,
      permission: 'facilities:view|facilities:book',
      feature: 'facilities.counselling_appointments'),
  const MoreMenuModule(
      titleKey: 'wallet',
      icon: Icons.account_balance_wallet_outlined,
      route: AppRoutes.wallet,
      color: Colors.green,
      permission: 'facilities:view',
      feature: 'facilities.canteen_wallet'),
  const MoreMenuModule(
      titleKey: 'gate_scan',
      icon: Icons.qr_code_scanner,
      route: AppRoutes.gateScan,
      color: Colors.blueGrey,
      permission: 'facilities:manage',
      feature: 'facilities.visitor_gate'),
  // Phase 27 — mentees, high-risk, mentor, grievances (+ officer board), discipline, surveys, clubs, hours queue
  const MoreMenuModule(
      titleKey: 'mentees',
      icon: Icons.diversity_3_outlined,
      route: AppRoutes.mentees,
      color: Colors.teal,
      permission: 'mentoring:manage',
      feature: 'mentoring.core'),
  const MoreMenuModule(
      titleKey: 'high_risk',
      icon: Icons.warning_amber_outlined,
      route: AppRoutes.highRisk,
      color: Colors.red,
      permission: 'mentoring:view_all',
      feature: 'mentoring.early_warning'),
  const MoreMenuModule(
      titleKey: 'my_mentor',
      icon: Icons.person_pin_outlined,
      route: AppRoutes.myMentor,
      color: Colors.teal,
      permission: 'mentoring:self',
      feature: 'mentoring.core'),
  const MoreMenuModule(
      titleKey: 'grievances',
      icon: Icons.report_outlined,
      route: AppRoutes.grievances,
      color: Colors.deepOrange,
      permission: 'grievances:create',
      feature: 'grievances.core'),
  const MoreMenuModule(
      titleKey: 'grievance_board',
      icon: Icons.view_kanban_outlined,
      route: AppRoutes.grievanceBoard,
      color: Colors.deepOrange,
      permission: 'grievances:triage',
      feature: 'grievances.core'),
  const MoreMenuModule(
      titleKey: 'discipline_notices',
      icon: Icons.gavel_outlined,
      route: AppRoutes.disciplineNotices,
      color: Colors.brown,
      permission: null,
      feature: 'discipline.core'),
  const MoreMenuModule(
      titleKey: 'surveys',
      icon: Icons.poll_outlined,
      route: AppRoutes.surveys,
      color: Colors.purple,
      permission: 'surveys:respond',
      feature: 'surveys.core'),
  const MoreMenuModule(
      titleKey: 'clubs',
      icon: Icons.groups_outlined,
      route: AppRoutes.clubs,
      color: Colors.green,
      permission: 'clubs:view',
      feature: 'clubs.core'),
  const MoreMenuModule(
      titleKey: 'hours_verification',
      icon: Icons.fact_check_outlined,
      route: AppRoutes.hoursVerification,
      color: Colors.green,
      permission: 'clubs:verify_hours',
      feature: 'clubs.core'),
  const MoreMenuModule(
      titleKey: 'parent_support',
      icon: Icons.family_restroom_outlined,
      route: AppRoutes.parentSupport,
      color: Colors.teal,
      permission: 'mentoring:wards',
      feature: 'mentoring.core'),
  // Phase 34 — affiliation (college admin / principal), exam centre (coordinator), affiliation office, inspections
  const MoreMenuModule(
      titleKey: 'affiliation',
      icon: Icons.apartment_outlined,
      route: AppRoutes.collegeAffiliation,
      color: Colors.brown,
      permission: 'affiliation:apply',
      feature: 'affiliation.core'),
  const MoreMenuModule(
      titleKey: 'exam_centre',
      icon: Icons.meeting_room_outlined,
      route: AppRoutes.examCentreDesk,
      color: Colors.brown,
      permission: 'affiliation:submit',
      feature: 'affiliation.exam_centres'),
  // Phase 37 — audit & security (institution admin / registrar) and exam audit (COE)
  const MoreMenuModule(
      titleKey: 'audit_logs',
      icon: Icons.policy_outlined,
      route: AppRoutes.auditHub,
      color: Colors.blueGrey,
      permission: 'audit_logs:view_all',
      feature: 'core.audit_logs'),
  const MoreMenuModule(
      titleKey: 'exam_audit',
      icon: Icons.fact_check_outlined,
      route: AppRoutes.examAudit,
      color: Colors.deepPurple,
      permission: 'exams:audit',
      feature: 'exams.sessions'),
  // Phase 40 — website quick actions
  const MoreMenuModule(
      titleKey: 'website',
      icon: Icons.public,
      route: AppRoutes.websiteQuick,
      color: Colors.blue,
      permission: 'website:publish',
      feature: 'website.core'),
  // Phase 41 — integration health
  const MoreMenuModule(
      titleKey: 'integrations',
      icon: Icons.hub,
      route: AppRoutes.integrationsHealth,
      color: Colors.teal,
      permission: 'integrations:view',
      feature: 'core.settings'),
  // Phase 39 — notification centre (every role)
  const MoreMenuModule(
      titleKey: 'notifications',
      icon: Icons.notifications_active_outlined,
      route: AppRoutes.notificationCentre,
      color: Colors.orange,
      feature: 'core.notifications_inapp'),
  // Phase 38 — platform hub (super admin / support agent), support and billing (institution admin)
  const MoreMenuModule(
      titleKey: 'platform',
      icon: Icons.admin_panel_settings_outlined,
      route: AppRoutes.platformHub,
      color: Colors.indigo,
      permission: 'platform:view',
      feature: 'core.institution'),
  const MoreMenuModule(
      titleKey: 'support',
      icon: Icons.support_agent,
      route: AppRoutes.tenantSupport,
      color: Colors.teal,
      permission: 'support:manage',
      feature: 'core.settings'),
  const MoreMenuModule(
      titleKey: 'billing',
      icon: Icons.receipt_long_outlined,
      route: AppRoutes.tenantBilling,
      color: Colors.brown,
      permission: 'settings:manage',
      feature: 'core.settings'),
  // Phase 36 — reports (registrar / HOD / COE / accountant / placement / IQAC)
  const MoreMenuModule(
      titleKey: 'reports',
      icon: Icons.summarize_outlined,
      route: AppRoutes.reports,
      color: Colors.indigo,
      permission: 'reports:run',
      feature: 'reports.core'),
  // Phase 35 — early warning analytics (HOD / registrar / mentor)
  const MoreMenuModule(
      titleKey: 'early_warning',
      icon: Icons.monitor_heart_outlined,
      route: AppRoutes.riskCohort,
      color: Colors.red,
      permission: 'mentoring:manage|mentoring:view_all',
      feature: 'analytics.early_warning'),
  const MoreMenuModule(
      titleKey: 'affiliation_office',
      icon: Icons.domain_verification_outlined,
      route: AppRoutes.affiliationOffice,
      color: Colors.brown,
      permission: 'affiliation:view_all',
      feature: 'affiliation.core'),
  const MoreMenuModule(
      titleKey: 'inspections',
      icon: Icons.fact_check_outlined,
      route: AppRoutes.myInspections,
      color: Colors.brown,
      permission: 'affiliation:inspect',
      feature: 'affiliation.inspections'),
  // Phase 33 — governance (staff: meetings / ATRs / e-file / policy acks), committee desk (secretary), approvals
  const MoreMenuModule(
      titleKey: 'governance',
      icon: Icons.account_balance_outlined,
      route: AppRoutes.governanceHub,
      color: Colors.blueGrey,
      permission: 'governance:view',
      feature: 'governance.committees'),
  const MoreMenuModule(
      titleKey: 'committee_desk',
      icon: Icons.groups_outlined,
      route: AppRoutes.committeeDesk,
      color: Colors.blueGrey,
      permission: 'governance:minutes',
      feature: 'governance.minutes'),
  const MoreMenuModule(
      titleKey: 'governance_approvals',
      icon: Icons.approval_outlined,
      route: AppRoutes.governanceApprovals,
      color: Colors.blueGrey,
      permission: 'governance:approve',
      feature: 'governance.committees'),
  // Phase 32 — IQAC (coordinator) and department quality (HOD / faculty: metrics, responses, evidence, findings)
  const MoreMenuModule(
      titleKey: 'iqac',
      icon: Icons.verified_outlined,
      route: AppRoutes.iqacHub,
      color: Colors.indigo,
      permission: 'accreditation:manage',
      feature: 'accreditation.aishe'),
  const MoreMenuModule(
      titleKey: 'department_quality',
      icon: Icons.fact_check_outlined,
      route: AppRoutes.departmentQuality,
      color: Colors.indigo,
      permission: 'accreditation:evidence',
      feature: 'accreditation.aishe'),
  // Phase 31 — My PhD (scholars), my scholars (guides), PhD approvals (research cell)
  const MoreMenuModule(
      titleKey: 'my_phd',
      icon: Icons.school_outlined,
      route: AppRoutes.scholarHub,
      color: Colors.deepPurple,
      permission: 'phd:self',
      feature: 'phd.scholar_portal',
      roles: ['research_scholar']),
  const MoreMenuModule(
      titleKey: 'my_scholars',
      icon: Icons.groups_2_outlined,
      route: AppRoutes.guideScholars,
      color: Colors.deepPurple,
      permission: 'phd:guide',
      feature: 'phd.core'),
  const MoreMenuModule(
      titleKey: 'phd_approvals',
      icon: Icons.approval_outlined,
      route: AppRoutes.phdApprovals,
      color: Colors.deepPurple,
      permission: 'phd:manage',
      feature: 'phd.core'),
  // Phase 30 — research (faculty), verification queue (HOD / research cell), approvals (research cell)
  const MoreMenuModule(
      titleKey: 'research',
      icon: Icons.science_outlined,
      route: AppRoutes.research,
      color: Colors.indigo,
      permission: 'research:manage',
      feature: 'research.publications'),
  const MoreMenuModule(
      titleKey: 'research_verification',
      icon: Icons.fact_check_outlined,
      route: AppRoutes.researchVerification,
      color: Colors.indigo,
      permission: 'research:verify',
      feature: 'research.publications'),
  const MoreMenuModule(
      titleKey: 'research_approvals',
      icon: Icons.approval_outlined,
      route: AppRoutes.researchApprovals,
      color: Colors.indigo,
      permission: 'research:incentives',
      feature: 'research.publications'),
  // Phase 29 — alumni shell (alumni) and the alumni office (coordinator)
  const MoreMenuModule(
      titleKey: 'alumni',
      icon: Icons.school_outlined,
      route: AppRoutes.alumniHub,
      color: Colors.deepPurple,
      roles: ['alumni'],
      feature: 'alumni.portal'),
  const MoreMenuModule(
      titleKey: 'alumni_office',
      icon: Icons.verified_user_outlined,
      route: AppRoutes.alumniOffice,
      color: Colors.deepPurple,
      permission: 'alumni:verify',
      feature: 'alumni.core'),
  // Phase 28 — placement (student / parent / officer / internship faculty)
  const MoreMenuModule(
      titleKey: 'placement',
      icon: Icons.work_outline,
      route: AppRoutes.placement,
      color: Colors.indigo,
      permission: 'placement:self',
      feature: 'placement.core'),
  const MoreMenuModule(
      titleKey: 'ward_placement',
      icon: Icons.work_history_outlined,
      route: AppRoutes.wardPlacement,
      color: Colors.indigo,
      permission: 'placement:wards',
      feature: 'placement.core'),
  const MoreMenuModule(
      titleKey: 'placement_drives',
      icon: Icons.business_center_outlined,
      route: AppRoutes.placementDrives,
      color: Colors.indigo,
      permission: 'placement:drive_manage',
      feature: 'placement.core'),
  const MoreMenuModule(
      titleKey: 'internship_evaluation',
      icon: Icons.assignment_turned_in_outlined,
      route: AppRoutes.internshipEvaluation,
      color: Colors.indigo,
      permission: 'placement:evaluate',
      feature: 'placement.internships'),
  // Phase 26 — documents, ward documents, certificate queue, verify
  const MoreMenuModule(
      titleKey: 'documents',
      icon: Icons.description_outlined,
      route: AppRoutes.myDocuments,
      color: Colors.indigo,
      permission: 'certificates:self',
      feature: 'documents.templates'),
  const MoreMenuModule(
      titleKey: 'certificate_queue',
      icon: Icons.assignment_turned_in_outlined,
      route: AppRoutes.certificateQueue,
      color: Colors.indigo,
      permission: 'certificates:issue|certificates:request_approve',
      feature: 'documents.certificate_requests'),
  const MoreMenuModule(
      titleKey: 'verify_document',
      icon: Icons.qr_code_2,
      route: AppRoutes.verifyDocument,
      color: Colors.blueGrey,
      permission: null),
  // Phase 24 — campaigns, emergency broadcast (security officer), assistant, my messages
  const MoreMenuModule(
      titleKey: 'campaigns',
      icon: Icons.campaign_outlined,
      route: AppRoutes.campaigns,
      color: Colors.deepOrange,
      permission: 'communication:bulk|communication:approve',
      feature: 'comms.bulk_campaigns'),
  const MoreMenuModule(
      titleKey: 'emergency_broadcast',
      icon: Icons.warning_amber_outlined,
      route: AppRoutes.emergencyBroadcast,
      color: Colors.red,
      permission: 'communication:emergency',
      feature: 'comms.emergency_broadcast'),
  const MoreMenuModule(
      titleKey: 'assistant',
      icon: Icons.smart_toy_outlined,
      route: AppRoutes.assistant,
      color: Colors.purple,
      feature: 'comms.ai_assistant'),
  const MoreMenuModule(
      titleKey: 'my_messages',
      icon: Icons.mark_email_unread_outlined,
      route: AppRoutes.myMessages,
      color: Colors.blueGrey,
      permission: 'communication:view|communication:send',
      feature: 'comms.announcements'),
  // Phase 23 — accounting (accountant), department budget (HOD), grants (PI)
  const MoreMenuModule(
      titleKey: 'accounting',
      icon: Icons.account_balance_outlined,
      route: AppRoutes.accountingHome,
      color: Colors.green,
      permission: 'accounting:view_all',
      feature: 'accounting.core',
      roles: ['accountant', 'vice_chancellor', 'institution_admin']),
  const MoreMenuModule(
      titleKey: 'budget',
      icon: Icons.pie_chart_outline,
      route: AppRoutes.departmentBudget,
      color: Colors.green,
      permission: 'accounting:view',
      feature: 'accounting.budgets',
      roles: ['hod']),
  const MoreMenuModule(
      titleKey: 'grants',
      icon: Icons.science_outlined,
      route: AppRoutes.myGrants,
      color: Colors.indigo,
      permission: 'accounting:view',
      feature: 'accounting.grants_ledger',
      roles: ['faculty', 'hod', 'research_guide']),
  // Phase 22 — store keeper stock / receive, staff indents / assets, asset audit scanner
  const MoreMenuModule(
      titleKey: 'stock',
      icon: Icons.inventory_outlined,
      route: AppRoutes.stockLookup,
      color: Colors.brown,
      permission: 'inventory:issue',
      feature: 'inventory.core',
      roles: ['store_keeper', 'inventory_manager']),
  const MoreMenuModule(
      titleKey: 'receive_goods',
      icon: Icons.local_shipping_outlined,
      route: AppRoutes.grnReceive,
      color: Colors.brown,
      permission: 'inventory:receive',
      feature: 'inventory.procurement',
      roles: ['store_keeper', 'inventory_manager']),
  const MoreMenuModule(
      titleKey: 'indents',
      icon: Icons.assignment_outlined,
      route: AppRoutes.myIndents,
      color: Colors.deepPurple,
      permission: 'inventory:indent',
      feature: 'inventory.procurement'),
  const MoreMenuModule(
      titleKey: 'my_assets',
      icon: Icons.devices_other_outlined,
      route: AppRoutes.myAssets,
      color: Colors.blueGrey,
      permission: 'inventory:view',
      feature: 'inventory.assets'),
  const MoreMenuModule(
      titleKey: 'asset_audit',
      icon: Icons.qr_code_scanner,
      route: AppRoutes.assetAudit,
      color: Colors.teal,
      permission: 'inventory:asset_audit',
      feature: 'inventory.assets'),
  // Phase 21 — driver trips, my transport (students / staff), ward transport (parents), fleet (transport manager)
  const MoreMenuModule(
      titleKey: 'driver_trips',
      icon: Icons.directions_bus,
      route: AppRoutes.driverTrips,
      color: Colors.blue,
      permission: 'transport:driver',
      feature: 'transport.core',
      roles: ['driver']),
  const MoreMenuModule(
      titleKey: 'transport',
      icon: Icons.directions_bus_outlined,
      route: AppRoutes.myTransport,
      color: Colors.blue,
      permission: 'transport:view',
      feature: 'transport.core',
      roles: ['student', 'learner', 'faculty', 'hod', 'class_advisor', 'guest_faculty']),
  const MoreMenuModule(
      titleKey: 'ward_transport',
      icon: Icons.directions_bus_outlined,
      route: AppRoutes.wardTransport,
      color: Colors.blue,
      permission: 'transport:view',
      feature: 'transport.core',
      roles: ['parent']),
  const MoreMenuModule(
      titleKey: 'fleet',
      icon: Icons.airport_shuttle_outlined,
      route: AppRoutes.fleetStatus,
      color: Colors.blueGrey,
      permission: 'transport:manage',
      feature: 'transport.core',
      roles: ['transport_manager']),
  // Phase 20 — hostel (students), ward hostel (parents), out-passes / gate / roll-call (warden, gate staff)
  const MoreMenuModule(
      titleKey: 'hostel',
      icon: Icons.bed_outlined,
      route: AppRoutes.myHostel,
      color: Colors.indigo,
      permission: 'hostel:self',
      feature: 'hostel.core',
      roles: ['student', 'learner']),
  const MoreMenuModule(
      titleKey: 'ward_hostel',
      icon: Icons.bed_outlined,
      route: AppRoutes.wardHostel,
      color: Colors.indigo,
      permission: 'hostel:view',
      feature: 'hostel.core',
      roles: ['parent']),
  const MoreMenuModule(
      titleKey: 'out_passes',
      icon: Icons.exit_to_app,
      route: AppRoutes.outPasses,
      color: Colors.orange,
      permission: 'hostel:warden',
      feature: 'hostel.leave_outpass',
      roles: ['hostel_warden']),
  const MoreMenuModule(
      titleKey: 'hostel_gate',
      icon: Icons.qr_code_scanner,
      route: AppRoutes.hostelGate,
      color: Colors.teal,
      permission: 'hostel:gate',
      feature: 'hostel.gate_qr',
      roles: ['hostel_warden', 'hostel_gate_staff']),
  const MoreMenuModule(
      titleKey: 'roll_call',
      icon: Icons.fact_check_outlined,
      route: AppRoutes.rollCall,
      color: Colors.green,
      permission: 'hostel:roll_call',
      feature: 'hostel.night_roll_call',
      roles: ['hostel_warden']),
  // Phase 19 — library (members), ward library (parents), circulation scanner (librarian)
  const MoreMenuModule(
      titleKey: 'library',
      icon: Icons.local_library_outlined,
      route: AppRoutes.myLibrary,
      color: Colors.brown,
      permission: 'library:self',
      feature: 'library.core',
      roles: ['student', 'faculty', 'hod', 'class_advisor', 'guest_faculty', 'alumni', 'learner', 'research_scholar']),
  const MoreMenuModule(
      titleKey: 'ward_library',
      icon: Icons.local_library_outlined,
      route: AppRoutes.wardLibrary,
      color: Colors.brown,
      permission: 'library:self',
      feature: 'library.core',
      roles: ['parent']),
  const MoreMenuModule(
      titleKey: 'library_circulation',
      icon: Icons.qr_code_scanner,
      route: AppRoutes.libraryCirculation,
      color: Colors.teal,
      permission: 'library:circulate',
      feature: 'library.core',
      roles: ['librarian']),
  // Phase 18 — degree (students / alumni), eligibility + approvals + convocation scanner (registrar / VC)
  const MoreMenuModule(
      titleKey: 'degree',
      icon: Icons.school_outlined,
      route: AppRoutes.myDegree,
      color: Colors.indigo,
      permission: 'degrees:view',
      feature: 'degrees.eligibility',
      roles: ['student', 'alumni', 'learner']),
  const MoreMenuModule(
      titleKey: 'degree_eligibility',
      icon: Icons.fact_check_outlined,
      route: AppRoutes.degreeEligibility,
      color: Colors.teal,
      permission: 'degrees:view_all',
      feature: 'degrees.eligibility',
      roles: ['registrar', 'controller_of_examinations', 'vice_chancellor']),
  const MoreMenuModule(
      titleKey: 'award_approvals',
      icon: Icons.approval_outlined,
      route: AppRoutes.awardApprovals,
      color: Colors.deepPurple,
      permission: 'degrees:award',
      feature: 'degrees.certificates',
      roles: ['registrar', 'vice_chancellor']),
  const MoreMenuModule(
      titleKey: 'convocation_scanner',
      icon: Icons.qr_code_scanner,
      route: AppRoutes.convocationScanner,
      color: Colors.orange,
      permission: 'degrees:convocation_manage',
      feature: 'degrees.convocation',
      roles: ['registrar']),
  // Phase 17 — attainment (faculty), attainment dashboard + CQI (HOD / IQAC / OBE coordinator / dean)
  const MoreMenuModule(
      titleKey: 'attainment',
      icon: Icons.insights_outlined,
      route: AppRoutes.attainment,
      color: Colors.deepPurple,
      permission: 'obe:compute',
      feature: 'obe.attainment',
      roles: ['faculty', 'hod', 'class_advisor', 'guest_faculty']),
  const MoreMenuModule(
      titleKey: 'attainment_dashboard',
      icon: Icons.radar_outlined,
      route: AppRoutes.attainmentDashboard,
      color: Colors.indigo,
      permission: 'obe:view',
      feature: 'obe.attainment',
      roles: ['hod', 'dean', 'iqac_coordinator', 'obe_coordinator']),
  const MoreMenuModule(
      titleKey: 'cqi_actions',
      icon: Icons.task_alt_outlined,
      route: AppRoutes.cqiActions,
      color: Colors.teal,
      permission: 'obe:view',
      feature: 'obe.cqi',
      roles: ['faculty', 'hod', 'dean', 'iqac_coordinator', 'obe_coordinator']),
  // Phase 15 — results (students), evaluation (faculty / external examiners), result runs (exam cell / COE)
  const MoreMenuModule(
      titleKey: 'results',
      icon: Icons.grade_outlined,
      route: AppRoutes.myResults,
      color: Colors.green,
      permission: 'results:self',
      feature: 'results.publication_portal',
      roles: ['student', 'learner']),
  const MoreMenuModule(
      titleKey: 'evaluation',
      icon: Icons.rate_review_outlined,
      route: AppRoutes.evaluation,
      color: Colors.indigo,
      permission: 'exams:evaluate',
      feature: 'exams.coding_dummy',
      roles: ['faculty', 'hod', 'external_examiner', 'class_advisor', 'guest_faculty']),
  const MoreMenuModule(
      titleKey: 'result_runs',
      icon: Icons.fact_check_outlined,
      route: AppRoutes.resultRuns,
      color: Colors.teal,
      permission: 'results:verify',
      feature: 'results.processing',
      roles: ['exam_cell', 'controller_of_examinations']),
  // Phase 14 — exams (students), duties (faculty / invigilators), hall attendance (invigilators / exam cell)
  const MoreMenuModule(
      titleKey: 'exams',
      icon: Icons.event_note,
      route: AppRoutes.myExams,
      color: Colors.deepOrange,
      permission: 'exams:self',
      feature: 'exams.sessions',
      roles: ['student', 'learner']),
  const MoreMenuModule(
      titleKey: 'exam_duties',
      icon: Icons.assignment_ind_outlined,
      route: AppRoutes.myDuties,
      color: Colors.brown,
      permission: 'exams:invigilation',
      feature: 'exams.invigilation',
      roles: ['faculty', 'hod', 'invigilator', 'class_advisor', 'guest_faculty']),
  const MoreMenuModule(
      titleKey: 'exam_conduct',
      icon: Icons.how_to_reg_outlined,
      route: AppRoutes.examConduct,
      color: Colors.red,
      permission: 'exams:conduct',
      feature: 'exams.sessions',
      roles: ['invigilator', 'exam_cell', 'controller_of_examinations', 'college_exam_coordinator']),
  // Phase 13 — marks (faculty), verification (HOD), courses & marks (students)
  const MoreMenuModule(
      titleKey: 'marks',
      icon: Icons.edit_note,
      route: AppRoutes.facultyMarks,
      color: Colors.indigo,
      permission: 'marks:enter',
      feature: 'assessment.internal_marks',
      roles: ['faculty', 'class_advisor', 'hod', 'guest_faculty']),
  const MoreMenuModule(
      titleKey: 'marks_verification',
      icon: Icons.verified_outlined,
      route: AppRoutes.marksVerification,
      color: Colors.teal,
      permission: 'marks:verify',
      feature: 'assessment.marks_workflow',
      roles: ['hod']),
  const MoreMenuModule(
      titleKey: 'my_courses',
      icon: Icons.menu_book,
      route: AppRoutes.myCourses,
      color: Colors.blue,
      permission: 'marks:view',
      feature: 'assessment.internal_marks',
      roles: ['student', 'learner']),
  // Phase 12 — fees (student / parent tab; accountant collect + reconciliation; office no-dues sign-off)
  const MoreMenuModule(
      titleKey: 'fees',
      icon: Icons.account_balance_wallet_outlined,
      route: AppRoutes.myFees,
      color: Colors.green,
      permission: 'fees:self',
      feature: 'fees.core',
      roles: ['student', 'parent', 'learner']),
  const MoreMenuModule(
      titleKey: 'fee_collect',
      icon: Icons.point_of_sale,
      route: AppRoutes.feeCollect,
      color: Colors.indigo,
      permission: 'fees:collect',
      feature: 'fees.core',
      roles: ['accountant']),
  const MoreMenuModule(
      titleKey: 'fee_reconcile',
      icon: Icons.compare_arrows,
      route: AppRoutes.feeReconcile,
      color: Colors.blueGrey,
      permission: 'fees:reconcile',
      feature: 'fees.offline_challan_reconciliation',
      roles: ['accountant']),
  const MoreMenuModule(
      titleKey: 'no_dues_signoff',
      icon: Icons.task_alt,
      route: AppRoutes.noDuesSignoff,
      color: Colors.deepPurple,
      permission: 'no_dues:approve',
      feature: 'fees.no_dues',
      roles: ['accountant', 'librarian', 'hostel_warden', 'hod', 'sports_officer', 'transport_manager', 'placement_officer']),
  // Phase 03 — language / theme / college picker (every role)
  const MoreMenuModule(
      titleKey: 'settings',
      icon: Icons.settings_outlined,
      route: AppRoutes.settings,
      color: Colors.blueGrey),
];

List<MoreMenuModule> moreMenuFor(AuthState auth) =>
    moreMenuModules.where((m) => m.visibleFor(auth)).toList();
