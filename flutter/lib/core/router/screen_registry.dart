import 'package:flutter/material.dart';

import '../../features/academic_structure/academic_structure_screens.dart';
import '../../features/announcements/announcements_screens.dart';
import '../../features/approvals/approvals_screen.dart';
import '../../features/auth/profile_screens.dart';
import '../../features/hr/hr_screens.dart';
import '../../features/notifications/notifications_screens.dart';
import '../../features/settings/settings_screen.dart';
import '../../features/admissions/admissions_screens.dart';
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
