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
  // Phase 06 — HR self-service + the HR tab
  static const hrLeaves = '/app/hr/leaves';
  static const hrAttendance = '/app/hr/attendance';
  static const hrPayslips = '/app/hr/payslips';
  static const hrTab = '/app/hr';
  // Phase 07 — student self-service, students search + 360°
  static const studentProfile = '/app/student/profile';
  static const studentUndertakings = '/app/student/undertakings';
  static const studentIdCard = '/app/student/id-card';
  static const studentCreditTransfers = '/app/student/credit-transfers';
  static const studentsSearch = '/app/students';
  static const studentDetail = '/app/students/detail';
  // Phase 08 — admissions office: applicants search + detail (document verify), enquiries
  static const applicantsSearch = '/app/admissions/applicants';
  static const applicantDetail = '/app/admissions/applicants/detail';
  static const enquiries = '/app/admissions/enquiries';
  static const placeholder = '/app/placeholder';

  /// Universal links handled by deeplinks.dart
  static const verify = '/verify/:token';
  static const apply = '/apply/:cycle';
}
