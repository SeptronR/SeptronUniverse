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
  // Phase 09 — student registration cart, faculty offerings + roster, advisor registration approvals
  static const studentRegistration = '/app/registration';
  static const myOfferings = '/app/offerings/mine';
  static const offeringRoster = '/app/offerings/roster';
  static const registrationApprovals = '/app/registration/approvals';
  // Phase 10 — my timetable (student / faculty), today's sessions, substitutions
  static const myTimetable = '/app/timetable';
  static const todaySessions = '/app/timetable/today';
  static const substitutions = '/app/timetable/substitutions';
  // Phase 11 — attendance (faculty marking, student / parent rings, HOD condonations)
  static const attendance = '/app/attendance';
  static const myAttendance = '/app/attendance/me';
  static const condonations = '/app/attendance/condonations';
  // Phase 12 — fees (student / parent dues, accountant collect + reconciliation, office no-dues sign-off)
  static const myFees = '/app/fees';
  // Phase 13 — faculty marks entry, HOD verification, student courses & marks
  static const facultyMarks = '/app/marks';
  // Phase 14 — student exams, faculty duties, invigilator hall attendance
  static const myExams = '/app/exams';
  // Phase 19 — library (members), ward library (parents), circulation scanner (librarian)
  static const myLibrary = '/app/library';
  static const wardLibrary = '/app/library/ward';
  static const libraryCirculation = '/app/library/circulation';
  // Phase 18 — degree (students / alumni), eligibility, award approvals, convocation scanner (registrar)
  static const myDegree = '/app/degree';
  static const degreeEligibility = '/app/degrees/eligibility';
  static const awardApprovals = '/app/degrees/approvals';
  static const convocationScanner = '/app/degrees/scanner';
  // Phase 17 — OBE attainment (faculty), dashboard (HOD / IQAC), CQI actions
  static const attainment = '/app/attainment';
  static const attainmentDashboard = '/app/attainment/dashboard';
  static const cqiActions = '/app/cqi';
  // Phase 15 — results, evaluation, result runs
  static const myResults = '/app/results';
  static const evaluation = '/app/evaluation';
  static const resultRuns = '/app/result-runs';
  static const myDuties = '/app/exams/duties';
  static const examConduct = '/app/exams/conduct';
  static const marksVerification = '/app/marks/verification';
  static const myCourses = '/app/courses';
  static const feeCollect = '/app/fees/collect';
  static const feeReconcile = '/app/fees/reconcile';
  static const noDuesSignoff = '/app/no-dues/signoff';
  static const placeholder = '/app/placeholder';

  /// Universal links handled by deeplinks.dart
  static const verify = '/verify/:token';
  static const apply = '/apply/:cycle';
}
