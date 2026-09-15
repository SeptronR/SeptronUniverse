# PHASE 06 — STAFF, FACULTY, HR, RECRUITMENT & CAS

## Pre-Requisite
Phases 01–05 complete.

## Objective
People and payroll for a college/university: designations and staff master (regular/contract/guest/visiting), faculty academic profiles (ORCID/Scopus/AICTE/VIDWAN ids, cadre, PhD-guide status, scholar load), qualifications, documents, service book; leave types (CL/EL/ML/duty/study/sabbatical/LTC), leave requests & balances with the workflow engine, encashment; **statutory payroll** (components, salary structures, PF/ESI/PT/TDS, Form 16 data, increments, arrears, loans/advances, exam & guest remuneration lines); staff attendance (biometric/self check-in/geo) and holidays integration; recruitment (postings → reservation roster → screening → panels → offer → joining); PBAS appraisal; CAS with API score; faculty workload norms and course-allocation proposals. Everything supports the **self vs view_all** rule (e.g., accountant sees all staff/leaves/attendance and their own).

## Feature keys
`hr.staff` (on), `hr.faculty_profiles` (on), `hr.guest_faculty` (on, standard), `hr.leaves` (on), `hr.leave_encashment` (off, standard), `hr.payroll` (on, standard), `hr.statutory_payroll` (on, standard), `hr.loans_advances` (off, standard), `hr.staff_attendance` (on, standard), `hr.service_book` (on, standard), `hr.recruitment` (off, professional), `hr.reservation_roster` (off, professional), `hr.appraisal_pbas` (off, professional), `hr.cas_promotions` (off, professional), `hr.workload` (on, standard), `attendance.staff` (on, standard), `attendance.biometric` (off), `attendance.geo_app` (off).

## Visibility rules (the canonical self/view_all example)
| Role | Staff | Leaves | Staff attendance | Payroll | Appraisal/CAS | Recruitment |
|---|---|---|---|---|---|---|
| any staff | S (own profile) | S (apply, balance, history) | S (own, self check-in) | S (own payslips, Form 16) | S (own) | — |
| hod | D (`hr:view_all@department`) | S + D (approve) | S + D | — | D (review) | D (panels) |
| dean | F | S + F | S + F | — | F | F |
| **accountant** | **A (view)** | **S + A (view)** | **S + A (view)** | **A (manage, generate, mark paid)** | — | — |
| hr_officer | A (manage, view_pii) | S + A (manage, approve) | S + A (manage, devices) | A (generate, statutory config) | A | A (manage) |
| registrar / institution_admin | A | S + A | S + A | A (view) | A | A |
| auditor | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) |

Ownership links registered: `staff` (self: `Staff.user_id == p.id`; department via `Staff.department_id` for HOD scope; faculty unit via department→faculty), `leaves` (self: `StaffLeave.staff_id == p.staff_id`; approver link: pending workflow step assigned to `p.id`), `staff_attendance` (self), `payroll` (self), `appraisals` (self + reviewer link), `job_applications` (panel member link).

## 06.1 Database tables
Section 9: `designations, staff, staff_documents, service_book_entries, faculty_profiles, faculty_qualifications, leave_types, staff_leaves, staff_leave_balances, attendance_devices, staff_attendance, payroll_components, staff_salary_structures, staff_payrolls, staff_payroll_items, loans_advances, job_postings, job_applications, interview_panels, interview_scores, appraisals, cas_applications, faculty_workloads, course_allocation_proposals` — exist. Expected delta migration: none.

## 06.2 Alembic migration
`0006_phase06_hr_seed.py` — data-only: IN pack `payroll_components` template (Basic, DA, HRA, TA, Special; PF employee 12 % / employer 12 % (+EPS), ESI 0.75 %/3.25 % under threshold, PT slab by state, TDS by regime, LWF), `leave_types` template (CL 12, EL 30 accrual monthly 2.5, ML 20, Duty, Study, Sabbatical, Maternity 182, Paternity 15, LTC), designation template by cadre. Copied per institution by `seed_institution_defaults` (idempotent).

## 06.3 Models — `models/hr.py`
`Designation`, `Staff` (+ encrypted `pan_encrypted`, `aadhaar_encrypted`, `bank_details_encrypted` via `EncryptedBytes` type), `StaffDocument`, `ServiceBookEntry`, `FacultyProfile`, `FacultyQualification`, `LeaveType`, `StaffLeave`, `StaffLeaveBalance`, `AttendanceDevice`, `StaffAttendance`, `PayrollComponent`, `StaffSalaryStructure`, `StaffPayroll`, `StaffPayrollItem`, `LoanAdvance`, `JobPosting`, `JobApplication`, `InterviewPanel`, `InterviewScore`, `Appraisal`, `CasApplication`, `FacultyWorkload`, `CourseAllocationProposal`. Enums: `EmploymentType`, `StaffCategory`, `StaffStatus`, `Cadre`, `LeaveStatus`, `AttendanceStatus`, `PayrollStatus`, `ComponentType`, `CalcType`, `ApplicationStatus`, `AppraisalStatus`.

## 06.4 Schemas — `app/schemas/hr.py`, `leaves.py`, `payroll.py`, `recruitment.py`
`DesignationIn/Out`, `StaffCreate/Update/Response` (masked PII by default; `StaffDetailResponse` with `Masked[str]` fields), `StaffSelfUpdate` (contact/photo/emergency only), `FacultyProfileIn/Out`, `QualificationIn/Out`, `StaffDocumentIn/Out`, `ServiceBookEntryIn/Out`, `StaffBulkImportResult`, `LeaveTypeIn/Out`, `LeaveApply{leave_type_id, from_date, to_date, half_day?, reason, document_url?}`, `LeaveResponse` (+ workflow timeline), `LeaveBalanceResponse`, `LeaveEncashRequest`, `AttendanceDeviceIn/Out`, `StaffAttendanceMark{date, status, check_in?, check_out?}`, `SelfCheckinRequest{geo?}`, `PunchIngest{device_token, punches:[{employee_code, at, direction}]}`, `PayrollComponentIn/Out`, `SalaryStructureIn/Out`, `PayrollGenerateRequest{month, year, college_id?, staff_ids?}`, `PayrollResponse` (+ items), `PayslipPdf`, `Form16Data`, `LoanIn/Out`, `JobPostingIn/Out`, `JobApplicationIn/Out`, `PanelIn/Out`, `ScoreIn`, `AppraisalSelfIn`, `AppraisalReviewIn`, `CasApplicationIn/Out`, `WorkloadResponse`, `AllocationProposalIn/Out`.

## 06.5 Repository
`staff_repository.py` (`module="hr"`; search trgm; filters department/designation/type/status; `selectinload(FacultyProfile)`), `leave_repository.py` (`module="leaves"`), `leave_balance_repository.py`, `staff_attendance_repository.py` (`module="attendance"` with `staff_` actions), `payroll_repository.py` (`module="payroll"`; `FOR UPDATE` on payroll generation per staff/month), `recruitment_repository.py` (`module="recruitment"`), `appraisal_repository.py`, `workload_repository.py`. Visibility registrations per the table above.

## 06.6 Services
- `staff_service.py`
  1. Create staff → `employee_id` from `number_sequences('empid')`; auto-create user (username = employee id, temp password, `must_change_password`) with role from designation category (`faculty` for teaching, `receptionist`/custom otherwise) via RBAC; guest/visiting → `hourly_rate_paise` required; emits `staff.created`.
  2. Update with optimistic version; PII fields require `hr:view_pii` to read and `hr:manage` to write; self-update limited to `StaffSelfUpdate`.
  3. Exit: `status='exited'`, `exit_date`, deactivate user (sessions revoked), service book entry; blocked while open leaves/payroll pending.
  4. Documents with expiry reminders (Beat `hr.document_expiry` weekly); service book entries appended by promotion/increment/transfer/award/disciplinary/LWP events.
  5. Faculty profile upsert; `is_phd_guide` requires `guide_recognition_no`; `max_scholars` default from pack by cadre (8/6/4); qualifications (exactly one `is_highest`).
  6. Bulk import CSV (job) with partial-success report; export XLSX (masked unless `view_pii`).
- `leave_service.py`
  1. Leave types per institution (from pack); accrual job (`hr.leave_accrual` monthly/yearly per type), carry-forward at year start (cap), balances table maintained transactionally.
  2. Apply: validate overlap, balance (unless `is_paid=false`), holidays/week-offs excluded from `days_count` (`holiday_service.is_holiday`), document required for ML > 3 days; start workflow `leave.approval` (approver = HOD@department of staff, then HR if configured); status `pending`.
  3. Hooks: on approve → `approved`, balance `used += days`, staff attendance rows `on_leave` for the range, **timetable substitutions requested** for affected sessions (event `leave.approved` consumed by Phase 10), notify; on reject → `rejected`; cancel by staff while pending or before start (approved → balance restored).
  4. Encashment (`hr.leave_encashment`): request → workflow → payroll item.
  5. Views: `mine` (self), `team` (HOD scope), `all` (`leaves:view_all`); calendar feed.
- `staff_attendance_service.py`: mark (HR/admin), self check-in/out (`attendance.geo_app`: geo-fence radius from settings), device punch ingest (`attendance.biometric`; token auth; pairs punches → check-in/out; unknown employee codes reported), monthly summary (present/absent/leave/OD/LOP days) used by payroll; regularisation requests via workflow `attendance.regularise` (optional definition); holidays/week-offs auto-marked.
- `payroll_service.py`
  1. Components: earning/deduction/employer contribution; `calc_type` fixed/pct_of_basic/formula (safe expression over component codes)/statutory (`pf`, `esi`, `pt`, `tds`, `lwf` computed by `statutory.py` with pack rules and configurable thresholds/slabs in settings `payroll.*`).
  2. Salary structure effective-dated per staff; increments create a new structure (+ service book entry); arrears computed when effective date is in the past.
  3. `generate(month, year, scope)` (job): for each staff: paid days from attendance summary (LOP = unauthorised absences), pro-rata for joiners/leavers, components → items, loans EMI deduction, remuneration lines pulled from `staff_payroll_items` sources (exam duties Phase 14/15, guest hours from timetable sessions Phase 10 × `hourly_rate_paise`, fellowship for scholars Phase 31), TDS projection; status `draft`; idempotent per (staff, month, year) with `FOR UPDATE`.
  4. Approve (`payroll:approve`), mark paid with payment ref (`payroll:mark_paid`) → payslip PDF job (WeasyPrint) + notification; bank advice CSV; statutory registers (PF ECR, ESI, PT, TDS 24Q data) and Form 16 data export (job).
  5. Loans/advances: request → workflow → schedule; EMI auto-deducted; foreclosure.
- `recruitment_service.py`: postings (reservation roster JSON validated against the 100-/200-point roster pack helper), public application form (`/public/careers`), screening scores, shortlisting (rule + manual), panels & scores (weighted), selection → offer letter (document template) → joining creates staff (links application); emits `recruitment.*`.
- `appraisal_service.py`: PBAS self-assessment JSON (pack schema: teaching, research, extension, admin), auto-fill research metrics from Phase 30 tables when present, reviewer scoring → workflow `hr.appraisal`; CAS: eligibility date by cadre/years, API breakdown auto-computed (`research.api_score` when enabled), screening/interview/approval; on approve → new designation + salary structure + service book entry.
- `workload_service.py`: compute per staff per term from `course_offering_faculty.hours_per_week` (Phase 09) + admin hours (designation default) → compare with cadre norm (settings `hr.workload_norms` e.g., professor 14, associate 16, assistant 18); HOD `course_allocation_proposals` submit → dean approve → apply (Phase 09 consumes).

## 06.7 Events / jobs
Emits: `staff.created/updated/exited`, `leave.applied/approved/rejected/cancelled`, `staff_attendance.marked`, `payroll.generated/approved/paid`, `recruitment.posted/selected/joined`, `appraisal.submitted/approved`, `cas.approved`, `workload.computed`. Consumers: `search.reindex` (staff), `notifications` (leave decisions, payslip ready, posting published), Phase 10 `timetable.substitutions_from_leave`. Jobs: `hr.bulk_import`, `payroll.generate`, `payroll.payslips`, `payroll.statutory_export`, `hr.export`. Beat: `hr.leave_accrual` (1st of month 01:00), `hr.leave_carry_forward` (year start), `hr.document_expiry` (weekly), `attendance.auto_mark_holidays` (daily 00:10), `payroll.reminder` (25th). Workflows used: `leave.approval`, `attendance.regularise`, `hr.loan`, `hr.appraisal`, `hr.cas`, `hr.leave_encashment`.

## 06.8 Endpoints
```
GET/POST /api/v1/designations · PUT/DELETE /designations/{id} [hr:manage]
GET/POST /api/v1/staff · GET/PUT /staff/{id} · POST /staff/{id}/exit · POST /staff/{id}/photo · GET /staff/export · POST /staff/bulk-import [hr:view_all|create|update|manage|export] {hr.staff}
GET/PUT  /api/v1/staff/me                                        → own profile (limited fields) [auth]
GET/PUT  /api/v1/staff/{id}/faculty-profile · GET/POST /staff/{id}/qualifications · /documents · /service-book [hr:view|manage; faculty:research for own profile] {hr.faculty_profiles|hr.service_book}
GET/POST /api/v1/leave-types · PUT /leave-types/{id} [hr:manage] {hr.leaves}
GET      /api/v1/leaves?scope=self|team|all&status=                → resolver-filtered list with meta.visibility [leaves:view|view_all]
POST     /api/v1/leaves                                            → apply (self) [leaves:create]
POST     /api/v1/leaves/{id}/cancel · GET /leaves/{id} [leaves:view]
POST     /api/v1/leaves/{id}/approve · /reject                     → via workflow act [leaves:approve]
GET      /api/v1/leaves/me/balance · GET /leaves/calendar?department_id [leaves:self|view_all]
POST     /api/v1/leaves/encash [leaves:encash] {hr.leave_encashment}
GET      /api/v1/staff-attendance?scope=self|team|all&month=       → [attendance:staff_self|staff_view_all] {attendance.staff}
POST     /api/v1/staff-attendance/mark · POST /staff-attendance/self-checkin · /self-checkout [attendance:staff_view_all|staff_self]
POST     /api/v1/staff-attendance/regularise · GET /staff-attendance/summary?month= [attendance:staff_self|staff_view_all]
GET/POST /api/v1/attendance-devices · POST /attendance-devices/{id}/punches (device token) [attendance:device_manage] {attendance.biometric}
GET/POST /api/v1/payroll/components · PUT /payroll/components/{id} [payroll:statutory] {hr.payroll}
GET/POST /api/v1/staff/{id}/salary-structures [payroll:manage]
POST     /api/v1/payroll/generate · GET /payroll?month&year&status · GET /payroll/{id} · POST /payroll/{id}/approve · /mark-paid · GET /payroll/{id}/payslip.pdf [payroll:generate|manage|approve|mark_paid|view]
GET      /api/v1/payroll/me?year=                                  → own payslips [payroll:self]
GET      /api/v1/payroll/registers/{pf|esi|pt|tds}?month&year · GET /payroll/form16?year&staff_id [payroll:statutory] {hr.statutory_payroll}
GET/POST /api/v1/loans · POST /loans/{id}/foreclose [payroll:manage; self create] {hr.loans_advances}
GET/POST /api/v1/recruitment/postings · PUT /postings/{id} · POST /postings/{id}/publish|close [hr:recruitment] {hr.recruitment}
POST     /api/v1/public/careers/{posting_id}/apply {public}
GET      /api/v1/recruitment/postings/{id}/applications · POST /applications/{id}/screen|shortlist|select|offer|join [hr:recruitment]
GET/POST /api/v1/recruitment/postings/{id}/panels · POST /panels/{id}/scores [hr:recruitment]
GET/POST /api/v1/appraisals · POST /appraisals/{id}/submit · /review [hr:appraisal; self] {hr.appraisal_pbas}
GET/POST /api/v1/cas-applications · POST /cas-applications/{id}/submit|screen|decide [hr:cas; self] {hr.cas_promotions}
GET      /api/v1/faculty/{id}/workload?term_id= · GET /workload?department_id&term_id [faculty:workload_manage|self] {hr.workload}
GET/POST /api/v1/departments/{id}/course-allocation?term_id= · POST /course-allocation/{id}/submit|approve|apply [faculty:workload_manage]
```

## 06.9 Frontend
- `/admin/hr/staff` (DataTable with department/designation/type filters; masked PII; detail page tabs Profile | Faculty profile | Qualifications | Documents | Service book | Leaves | Attendance | Payroll | Workload; exit dialog; bulk import; export), `/me` (My profile, My leaves [apply form, balance cards, history], My attendance [self check-in with geo], My payslips, My appraisal).
- `/admin/hr/leaves` with **ScopeTabs Mine | Team | All** driven by `meta.visibility` (accountant sees Mine + All; HOD Mine + Team; HR Mine + All + approvals queue), calendar view, approve/reject drawer with `WorkflowTimeline`.
- `/admin/hr/attendance` (ScopeTabs; monthly grid; devices tab; regularisation queue), `/admin/hr/payroll` (components & statutory config, salary structures, generate wizard (month → scope → preview → generate job), payroll run table, approve/mark-paid, payslip download, registers, Form 16), `/admin/hr/loans`, `/admin/hr/recruitment` (postings, applications pipeline kanban: applied → screened → shortlisted → interviewed → selected → offered → joined; panels & scores), `/admin/hr/appraisals`, `/admin/hr/cas`, `/admin/hr/workload` (department grid vs norms; allocation proposal editor), public `/careers`.
- Nav: PEOPLE › Staff, Leaves, Staff Attendance, Payroll, Recruitment, Appraisals & CAS, Workload; MAIN › My Space (self items).

## 06.10 Mobile
Faculty/staff shell: **More › Leaves** (apply, balance, history), **My attendance** (self check-in/out with geo, month view), **Payslips** (list, PDF share), **Profile** (faculty profile read; research tab later); HOD/Dean: **Approvals** (leave cards), **Department › Staff** (list, detail masked), workload view; **Accountant shell › HR tab**: All staff, All leaves (+ Mine segment), All staff attendance (+ Mine segment); HR officer shell: Staff, Leaves (All/Approvals/Mine), Attendance (All/Mine), Payroll runs (approve, mark paid).

## 06.11 API verification — `scripts/verify/06_hr.ps1`
Roles: `hr`, `accountant`, `hod.cse`, `dean.eng`, `faculty.1`, `faculty.2` (ECE), `registrar`, `student.1`, `auditor.tmp`.
1. Seed `--only hr` (30 staff across CSE/ECE/Commerce, designations, leave types, components, salary structures).
2. `POST /staff` as `hr` (teaching, CSE) → 201; `employee_id` generated; user created with role `faculty`; `GET /staff/{id}` as `hod.cse` → PII masked (`pan` = `******34F`), as `hr` (has `hr:view_pii`) → full; as `hod.ece` → 404.
3. `GET /staff` as `accountant` → 200, `meta.visibility.scopes=["institution"]`, count = all; as `faculty.1` → only self; `PUT /staff/{other}` as `faculty.1` → 404; `PUT /staff/me` (phone) → 200.
4. Leaves: `faculty.1` `POST /leaves` (CL 2 days spanning a holiday) → `days_count=1`; balance reflects `pending`; `GET /leaves?scope=all` as `faculty.1` → narrowed to self (`meta.visibility.scopes=[]`); as `accountant` → `scopes=["institution"]` and the leave is listed; as `hod.cse` → `scopes=["department"]`, listed; as `hod.ece` → not listed.
5. Approval: `POST /leaves/{id}/approve` as `accountant` → 403 (view_all ≠ approve); as `hod.cse` → 200 → status `approved`, balance `used=1`, staff attendance rows `on_leave`, event `leave.approved` dispatched; `faculty.1` notified.
6. Overlapping leave → 409; ML 5 days without document → 422; cancel approved leave before start → balance restored.
7. Encashment disabled by default → `POST /leaves/encash` → 403 `FEATURE_DISABLED`; enable → workflow instance created.
8. Attendance: `faculty.1` self check-in with geo outside fence (setting radius 200 m) → 422; inside → 201; `hr` marks `absent` for `faculty.2` on a working day; device punch ingest with token → pairs into check-in/out; unknown code reported in response; `GET /staff-attendance?scope=all` as `accountant` → 200 all; `scope=self` → own rows.
9. Payroll: `POST /payroll/generate {month, year}` as `accountant` → job; run rows `draft` with items: Basic/DA/HRA, PF 12 %, PT slab, LOP deduction for `faculty.2` absent day, loan EMI for a seeded loan; regenerate same month → idempotent (no duplicates); approve → `approved`; mark paid → payslip PDF job; `GET /payroll/me` as `faculty.1` → own payslip only; as `student.1` → 403; registers PF/ESI/PT/TDS return rows; Form 16 data for `faculty.1` year.
10. Salary increment effective last month → arrears item in next run; service book entry created.
11. Recruitment (enable feature): posting with roster JSON invalid → 422; publish → `GET /public/careers` lists it; public apply → application; screen/shortlist/panel score/select/offer/join → staff created and linked.
12. Appraisal/CAS (enable): self-submit → workflow to `hod.cse` → review → approved; CAS application eligibility date computed; approve → designation changed + salary structure + service book entry.
13. Workload: after Phase 09 seed exists this returns hours; now returns 0 with norm and `status` computed; allocation proposal submit/approve/apply endpoints respond 200/409 appropriately (apply requires offerings — deferred check message).
14. Auditor: `GET /staff`, `/leaves?scope=all`, `/payroll` → 200 read; `POST /leaves` → 403.

## 06.12 UI verification
1. Staff list/detail: masks, tabs, exit dialog, bulk import job in tray, export.
2. **Leaves page as accountant shows tabs Mine | All** (no Team); as HOD Mine | Team; as HR Mine | All + Approvals; apply form validation (overlap, document); workflow timeline on a leave.
3. Attendance page: monthly grid per scope; self check-in button with geo prompt; devices tab; regularisation queue.
4. Payroll wizard → job → run table → approve → mark paid → payslip opens; registers download; Form 16 page.
5. Recruitment pipeline kanban drag between stages; public careers page + apply form.
6. Appraisal form auto-fills counts; CAS application flow.
7. Mobile: leave apply/approve, self check-in, payslip share; accountant HR tab shows All + Mine segments.

## 06.13 Deliverables checklist
- [ ] Staff/designations/faculty profiles/qualifications/documents/service book with PII masking and self-update; bulk import/export
- [ ] Leave types/accrual/carry-forward; apply/approve via workflow with balances, holidays, substitution event; encashment
- [ ] Staff attendance (mark, self check-in geo, device ingest, regularisation, summaries)
- [ ] Payroll (components incl. statutory, salary structures/increments/arrears, generation job, approve/pay, payslips, registers, Form 16, loans)
- [ ] Recruitment, appraisal (PBAS), CAS, workload & allocation proposals
- [ ] Visibility registrations proving self vs view_all for staff/leaves/attendance/payroll; ScopeTabs on web; segments on mobile
- [ ] Events/Beat/workflow definitions; demo seed `--only hr`
- [ ] `scripts/verify/06_hr.ps1` passes; UI checklist done; guards green; commit `feat(phase-06): staff, faculty, hr, recruitment, cas`
