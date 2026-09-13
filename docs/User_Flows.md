# SeptronUniverse — User Flows by Role

End-to-end journeys the phase prompts must implement. Each step names the screen (web `/path`, mobile `Tab › Screen`) and the primary endpoint. Phase numbers refer to `docs/Feature_Inventory.md`.

## 1. Applicant (Phase 08, 40)

| Step | Screen | Endpoint |
|---|---|---|
| Enquire | `/site/:slug/enquiry` | `POST /public/enquiries` |
| Create application (multi-programme preferences, documents, fee) | `/apply/:cycle` (steps: profile → qualifications → preferences → documents → review → pay) | `POST /public/admissions/{cycle}/apply`, `POST /admissions/applicants/{id}/submit`, `POST /fees/online/initiate` |
| Track status / resubmit rejected documents | `/apply/:cycle/status` | `GET /admissions/applicants/me`, `POST …/documents/{type}` |
| Merit / allotment / accept & pay | `/apply/:cycle/allotment` | `GET /admissions/allotments/me`, `POST /admissions/allotments/{id}/accept` |
| Admitted → credentials → undertakings | email/SMS with login; `/student/onboarding` | `POST /admissions/applicants/{id}/admit` (staff), `POST /students/me/undertakings` |

## 2. Student (Phases 07–18, 19, 20, 27, 28, 29)

| Journey | Screens (web / mobile) | Key endpoints |
|---|---|---|
| Onboarding: profile, guardian consent, undertakings, ID card | `/student/onboarding`, `/student/profile` · Student › More › Profile | `PUT /students/me`, `POST /students/me/undertakings`, `GET /students/me/id-card.pdf` |
| Term registration: cart, electives, arrears, credit meter, fee | `/student/registration` · Student › Academics › Registration | `GET /registration/me/catalog`, `POST /registration/me/items`, `POST /elective-baskets/{id}/choices`, `POST /registration/me/submit`, `POST /fees/online/initiate` |
| Timetable & LMS: content, assignments, quizzes, discussions | `/student/timetable`, `/student/courses/:offeringId` · Academics › Courses | `GET /timetables/view?me`, `GET /course-offerings/{id}/modules`, `POST /assignments/{id}/submit`, `POST /quizzes/{id}/start` |
| Attendance %, shortfall calculator, QR check-in, OD/condonation | `/student/attendance` · Academics › Attendance | `GET /attendance/summary?me`, `POST /attendance/qr-checkin`, `POST /on-duty`, `POST /condonations` |
| Internal marks view, CO progress | `/student/marks` | `GET /course-offerings/{id}/assessments?me` |
| Exam registration & fee → hall ticket (offline PDF) → seating | `/student/exams` · Exams | `GET /exam-registration/me`, `POST /exam-registration/me/submit`, `GET /exam-registrations/me/hall-ticket.pdf` |
| Results, grade card, SGPA/CGPA, standing | `/student/results` · Exams › Results | `GET /results/me`, `GET /students/me/grade-card/{term}.pdf` |
| Revaluation / photocopy / challenge (fee) | `/student/exams/reval` | `POST /reval-requests`, `POST /fees/online/initiate` |
| Supplementary registration | `/student/exams` (arrear tab) | `GET /exam-registration/me?session_id=` |
| Fees: dues, pay (UPI/gateway), receipts, scholarships, no-dues | `/student/fees` · Fees | `GET /fees/me/dues`, `POST /fees/online/initiate`, `GET /fees/me/receipts`, `POST /scholarships/{id}/apply`, `GET /no-dues/me` |
| Hostel: apply, out-pass (guardian OTP), mess, complaints, room change | `/student/hostel` · More › Hostel | `POST /hostel-applications`, `POST /hostel-leaves`, `GET /mess-subscriptions/me`, `POST /hostel-complaints` |
| Library: my books, OPAC, fines | `/student/library` | `GET /library/me`, `GET /library/opac` |
| Certificate & transcript requests (fee, workflow) | `/student/requests` | `POST /certificate-requests`, `POST /students/me/transcripts` |
| Placement: profile/resume, drives, apply, rounds, offers, internships, training | `/student/placement` · More › Placement | `PUT /placement/profile/me`, `GET /placement/drives?eligible=me`, `POST /drives/{id}/apply`, `POST /offers/{id}/accept` |
| Mentor sessions, counselling, surveys, grievances, clubs, activity hours | `/student/mentor`, `/student/surveys`, `/student/grievances`, `/student/clubs` | `POST /mentoring/bookings`, `POST /surveys/{id}/respond`, `POST /grievances`, `POST /activity-hours` |
| Holds & standing visibility | banner on `/student` home | `GET /students/me/holds` |
| Degree: eligibility, convocation registration, degree/DigiLocker | `/student/degree` | `GET /degree-eligibility/me`, `POST /convocations/{id}/register`, `GET /degrees/me` |
| Exit → alumni profile | `/alumni/portal` | `GET/PUT /alumni/me` |

## 3. Parent (Phases 07, 11, 12, 20, 27, 39)

| Journey | Screens | Endpoints |
|---|---|---|
| Link wards (OTP), ward switcher | `/parent` · Parent › Home | `GET /dashboard/parent` |
| Attendance, results, timetable, notices | Parent › Academics | `GET /attendance/summary?student_id`, `GET /results?student_id`, `GET /announcements` |
| Pay fees (UPI), receipts | Parent › Fees | `GET /fees/dues?student_id`, `POST /fees/online/initiate` |
| Hostel out-pass consent (OTP), transport live | Parent › More | `POST /hostel-leaves/{id}/guardian-consent`, `GET /transport/live?student_id` |
| Mentor meeting, grievances, surveys | Parent › More | `POST /mentoring/bookings`, `POST /grievances`, `POST /surveys/{id}/respond` |

## 4. Faculty (Phases 06, 09–13, 14, 15, 27, 30)

| Journey | Screens | Endpoints |
|---|---|---|
| My timetable, today's sessions | `/faculty` · Faculty › Home | `GET /timetables/view?me`, `GET /class-sessions?me&date` |
| Take attendance (grid / QR / offline), extra class, finalize | `/faculty/attendance` · Attendance | `POST /class-sessions/{id}/attendance`, `POST /class-sessions/{id}/qr`, `POST /class-sessions/{id}/finalize` |
| Lesson plan tick-off, course file | `/faculty/offerings/:id/plan` · Courses | `POST /course-offerings/{id}/lesson-plan`, `PUT …/course-file` |
| LMS: content, assignments grading, quizzes, announcements | `/faculty/offerings/:id/lms` · Courses | `POST /course-offerings/{id}/modules|contents`, `POST /assignments/{id}/grade`, `POST /course-offerings/{id}/quizzes` |
| Internal marks: question-wise entry → submit; CO preview | `/faculty/marks/:offeringId` · Marks | `POST /offering-assessments/{id}/questions`, `POST …/marks`, `POST …/submit` |
| Projects: guide, reviews | `/faculty/projects` | `POST /projects/{id}/reviews` |
| Invigilation duties, swaps | `/faculty/duties` · More › Duties | `GET /invigilation-duties?me`, `POST /invigilation-duties/{id}/swap-request` |
| Evaluator: bundles (dummy numbers), question-wise marks | `/evaluator/bundles/:id` · More › Evaluation | `GET /valuation/me/bundles`, `POST /answer-scripts/{id}/valuations/{round}` |
| Mentees: 360°, logs, early-warning, referrals | `/faculty/mentees` · More › Mentees | `GET /mentoring/assignments?me`, `POST /mentoring/sessions`, `GET /risk-flags?mentor=me` |
| Advisee registrations approval | `/faculty/advisees/registrations` · Approvals | `GET /registration/pending?advisor=me`, `POST /registration/{id}/approve` |
| Leave apply/balance, my attendance, payslips | `/me/leaves`, `/me/payslips` · More | `POST /leaves`, `GET /leaves/me/balance`, `GET /payroll/me/payslips` |
| Research profile, publications, projects, incentives | `/faculty/research` | `GET/POST /faculty/{id}/publications|projects`, `POST /research/incentives` |
| Workload, appraisal (PBAS), CAS | `/faculty/workload`, `/faculty/appraisal` | `GET /faculty/{id}/workload`, `POST /appraisals` |
| Survey results (own courses) | `/faculty/surveys` | `GET /surveys/{id}/analytics?target_id=me` |

## 5. Class advisor / mentor
Approve registrations → advisee dashboard (attendance, marks, dues, holds, risk) → mentoring logs & bookings → counselling referral → parent communication (`POST /communications/send` with template).

## 6. HOD (Phases 05, 06, 09–13, 30, 33)
Course allocation proposal & workload (`POST /departments/{id}/course-allocation`) → offerings → marks verification (`POST /offering-assessments/{id}/verify`) → condonation recommendation → department attendance/marks status dashboards (`GET /dashboard/hod`) → leave approvals (`POST /leaves/{id}/approve`) → indents (`POST /indents`) → BoS agenda/minutes (`POST /meetings`) → department metrics for accreditation (`GET /accreditation/metrics?college_id&department`).

## 7. Dean
Faculty-level approvals (workflow inbox) → regulation approvals → cross-department reports → course allocation approval → events approvals.

## 8. Registrar (Phases 03, 07, 08, 18, 26, 34, 36)
Academic years/terms (`POST /academic-terms`) → admission cycle → seat matrix → merit/counselling → admit → registration numbers (`number_sequences`) → transfers/migration → holds → certificate/transcript queue (`GET /certificate-requests?status=pending`) → degree eligibility runs → convocation → affiliation applications & college submissions → statutory reports.

## 9. Controller of Examinations / exam cell / decoder (Phases 14–16, 18)
Session setup → papers & date-sheet (clash check) → open registration → eligibility apply → hall tickets (job) → seating → invigilation roster → QP assignments/scrutiny/print (watermark) → bundles/coding (decoder) → valuation assignment (internal/external, rounds) → reconcile discrepancies → moderation (COE approve) → decode (decoder) → result run → review anomalies → verify (exam cell) → approve & publish (COE) → notifications → reval → supplementary → malpractice hearings → grade cards/transcripts → ABC/DigiLocker push → script custody & retention.

## 10. External examiner
Time-boxed login (link) → assigned bundles (dummy numbers only) → question-wise marks → submit → remuneration slip.

## 11. Accountant (Phases 06, 12, 22, 23)
Counter collection (search student → dues → collect → receipt/thermal) (`POST /fees/collect`) → online reconciliation (`GET /fees/online/reconcile`) → offline challan/UTR reconciliation → receipt cancellation via approval → refunds → scholarship disbursement → no-dues sign-off → fee reports → Tally export → payroll runs (`POST /payroll/generate`) → vendor bills → **view all staff, leaves, staff attendance** (`GET /staff`, `GET /leaves?scope=all`, `GET /staff-attendance?scope=all`) alongside **My leaves / My attendance** (`?scope=self`).

## 12. HR officer (Phase 06)
Staff onboarding & documents → service book → leave policies & approvals → attendance devices → payroll statutory config → payslips → recruitment (posting → roster → screening → panels → offer → joining) → appraisal cycles → CAS.

## 13. Admissions officer (Phase 08)
Enquiries pipeline → cycle operations → verification queue → merit lists → counselling rounds → offers → admit → refunds.

## 14. Placement officer (Phase 28)
Companies & recruiter users → drives with eligibility → publish (eligible list) → applications → rounds & results → offers → policies (one offer / dream upgrade) → internships & NOCs → training programmes → stats (NIRF/NAAC) → company feedback.

## 15. Hostel warden / gate staff (Phase 20)
Applications → auto-allot → check-in → out-pass approvals → gate QR mark-out/return (late list) → night roll call → visitors → complaints → discipline → mess bills → vacate/no-dues.

## 16. Librarian (Phase 19)
Catalogue & copies → circulation (barcode issue/return/renew) → reservations → fines → e-resources → member no-dues sign-off → reports.

## 17. IQAC coordinator (Phase 32)
Frameworks → metric compute (job) → review numerators/denominators → overrides with reason → evidence upload → cycle → criterion narratives → AQAR/SSR/NIRF/AISHE export → SSS survey → audits.

## 18. Research guide / scholar (Phase 31)
Guide: scholars list, DC meetings, progress review, thesis examiner recommendations, viva panel. Scholar: coursework registration/results → progress reports → fellowship → requests (extension/guide change) → synopsis → thesis upload (plagiarism) → examiners → viva → ETD upload → award.

## 19. Committee secretary (Phase 33)
Committee & members → meeting schedule → agenda → attendance/quorum → minutes → resolutions → ATR follow-ups; resolutions referenced by regulation approvals, result approvals, degree awards.

## 20. College admin (affiliated college, Phase 34)
College-scoped everything → term data submissions (registrations, CIA, eligibility, exam registrations) → exam centre operations → result release view → affiliation renewal applications.

## 21. Institution admin (Phases 02, 03, 38)
Onboarding wizard → structure (colleges/faculties/departments) → roles & scopes → features (institution-enabled) → settings & branding → integrations → announcements → dashboards → read-only mode during exams.

## 22. Super admin (Phase 38)
Create institution (type, pack) → plan → **Features tab** → onboarding (seed roles/permissions/pack defaults/demo) → impersonate (audited) → usage & billing → support tickets → integration health → platform announcements → tenant export/suspend/reset.

## 23. Recruiter (company user, Phase 28)
Login → post/edit drive (draft, placement officer approves) → view eligible & applied (consented fields) → schedule rounds → upload round results → offers → feedback.

## 24. Auditor (time-boxed, read-only)
Login → read-only access across modules for the period → export evidence lists → no writes.

## 25. Cross-cutting flows
- **Approval inbox** (workflow engine): any approver sees pending items across modules, acts, delegates; SLA escalations by Beat.
- **Background jobs**: user starts bulk action → job tray shows progress → download link (signed URL).
- **Notifications**: outbox → channels per preference; in-app inbox with deep links; announcement acknowledgement.
- **Certificate verification (public)**: `/verify/:token` → document status, hash, issuer.
- **Read-only mode**: platform/tenant toggle shows banner; writes return `503 READ_ONLY`.
