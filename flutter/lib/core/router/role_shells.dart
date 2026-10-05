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
    if (permission != null) {
      final parts = permission!.split(':');
      if (!auth.can(parts[0], parts.length > 1 ? parts[1] : 'view')) {
        return false;
      }
    }
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
  // Phase 03 — language / theme / college picker (every role)
  const MoreMenuModule(
      titleKey: 'settings',
      icon: Icons.settings_outlined,
      route: AppRoutes.settings,
      color: Colors.blueGrey),
];

List<MoreMenuModule> moreMenuFor(AuthState auth) =>
    moreMenuModules.where((m) => m.visibleFor(auth)).toList();
