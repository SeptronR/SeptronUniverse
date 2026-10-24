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

/// Tabs per role (§3). Phase 42 fills the per-role tab sets; every role has the common shell until then.
List<ShellTab> tabsForRole(String role) {
  if (Roles.portalOnly.contains(role)) return _commonTabs;
  return _staffTabs;
}

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
