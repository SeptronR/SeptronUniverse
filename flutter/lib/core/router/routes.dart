/// Route constants: `/app/<module>/<screen>` (docs/Mobile_App_UI_Structure.md §1).
class AppRoutes {
  AppRoutes._();

  static const splash = '/';
  static const login = '/login';
  static const picker = '/picker';
  static const home = '/app/home';
  static const more = '/app/more';
  static const approvals = '/app/approvals/inbox';
  static const notifications = '/app/notifications';
  static const profile = '/app/profile';
  static const profilePassword = '/app/profile/password';
  static const profileMfa = '/app/profile/mfa';
  static const profileSessions = '/app/profile/sessions';
  static const settings = '/app/settings';
  static const announcements = '/app/announcements';
  static const notificationPreferences = '/app/notifications/preferences';
  static const academicCourses = '/app/academics/courses';
  static const academicCurriculum = '/app/academics/curriculum';
  static const placeholder = '/app/placeholder';

  /// Universal links handled by deeplinks.dart
  static const verify = '/verify/:token';
  static const apply = '/apply/:cycle';
}
