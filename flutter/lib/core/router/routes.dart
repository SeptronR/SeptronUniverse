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
  // Phase 16 — revaluation, malpractice, transcripts (students), reval queue (COE / exam cell)
  static const myReval = '/app/exams/reval';
  static const myMalpractice = '/app/exams/malpractice';
  static const myTranscripts = '/app/transcripts';
  static const revalQueue = '/app/exams/reval-queue';
  // Phase 25 — SOS, responder, events, service requests, wellness, wallet, gate scan
  static const sos = '/app/sos';
  static const sosResponder = '/app/sos/responder';
  static const campusEvents = '/app/events';
  static const serviceRequests = '/app/service-requests';
  static const wellness = '/app/wellness';
  static const wallet = '/app/wallet';
  static const gateScan = '/app/gate-scan';
  // Phase 27 — mentoring, early warning, grievances, discipline, surveys, clubs
  static const mentees = '/app/mentees';
  static const mentorSlots = '/app/mentor-slots';
  static const highRisk = '/app/high-risk';
  static const myMentor = '/app/my-mentor';
  static const grievances = '/app/grievances';
  static const grievanceBoard = '/app/grievance-board';
  static const disciplineNotices = '/app/discipline';
  static const surveys = '/app/surveys';
  static const clubs = '/app/clubs';
  static const hoursVerification = '/app/hours-verification';
  static const parentSupport = '/app/parent-support';
  // Phase 30 — research (faculty / HOD verification / research cell approvals)
  static const research = '/app/research';
  static const researchVerification = '/app/research-verification';
  static const researchApprovals = '/app/research-approvals';
  // Phase 32 — IQAC hub (coordinator) and department quality (HOD / faculty)
  static const iqacHub = '/app/iqac';
  static const departmentQuality = '/app/department-quality';
  // Phase 31 — PhD (scholar hub / guide scholars / research cell approvals)
  static const scholarHub = '/app/scholar';
  static const guideScholars = '/app/my-scholars';
  static const phdApprovals = '/app/phd-approvals';
  // Phase 29 — alumni shell + alumni office
  static const alumniHub = '/app/alumni';
  static const alumniOffice = '/app/alumni-office';
  // Phase 28 — placement, internships, training
  static const placement = '/app/placement';
  static const wardPlacement = '/app/ward-placement';
  static const placementDrives = '/app/placement-drives';
  static const internshipEvaluation = '/app/internship-evaluation';
  // Phase 26 — documents, certificate queue, verify
  static const myDocuments = '/app/documents';
  static const wardDocuments = '/app/ward-documents';
  static const certificateQueue = '/app/certificate-queue';
  static const verifyDocument = '/app/verify';
  // Phase 24 — campaigns (communication officer), emergency broadcast, assistant, my messages
  static const campaigns = '/app/comms/campaigns';
  static const emergencyBroadcast = '/app/comms/emergency';
  static const assistant = '/app/assistant';
  static const myMessages = '/app/comms/messages';
  // Phase 23 — accounting (accountant), department budget (HOD), grants (PI)
  static const accountingHome = '/app/accounting';
  static const departmentBudget = '/app/accounting/budget';
  static const myGrants = '/app/accounting/grants';
  // Phase 22 — stock / receive goods (store keeper), indents / my assets (staff), audit scanner
  static const stockLookup = '/app/inventory/stock';
  static const grnReceive = '/app/inventory/receive';
  static const myIndents = '/app/inventory/indents';
  static const myAssets = '/app/inventory/assets';
  static const assetAudit = '/app/inventory/audit';
  // Phase 21 — transport: driver trips, my / ward transport, fleet status (transport manager)
  static const driverTrips = '/app/transport/driver';
  static const myTransport = '/app/transport';
  static const wardTransport = '/app/transport/ward';
  static const fleetStatus = '/app/transport/fleet';
  // Phase 20 — hostel (students), ward hostel (parents), out-passes / gate / roll-call (warden, gate staff)
  static const myHostel = '/app/hostel';
  static const wardHostel = '/app/hostel/ward';
  static const outPasses = '/app/hostel/out-passes';
  static const hostelGate = '/app/hostel/gate';
  static const rollCall = '/app/hostel/roll-call';
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
