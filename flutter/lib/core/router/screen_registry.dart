import 'package:flutter/material.dart';

import '../../features/academic_structure/academic_structure_screens.dart';
import '../../features/announcements/announcements_screens.dart';
import '../../features/approvals/approvals_screen.dart';
import '../../features/auth/profile_screens.dart';
import '../../features/notifications/notifications_screens.dart';
import '../../features/settings/settings_screen.dart';
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
      builder: (_, __) => const PlaceholderScreen(title: 'Home'),
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
      builder: (_, params) =>
          CurriculumScreen(programRegulationId: params['pr']),
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
