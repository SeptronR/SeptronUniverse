# PHASE 11 — ATTENDANCE & ELIGIBILITY

## Pre-Requisite
Phases 01–10 complete (sessions generated from published timetables, rosters from confirmed registrations, regulation rules, workflow engine, holidays, devices from Phase 06).

## Objective
Session-wise student attendance per course offering (manual grid, session QR, biometric/RFID punches, geo-fenced app check-in, offline queue), finalize lock with audited post-finalization edits, extra classes, on-duty requests, per-offering summaries with the shortfall calculator, **condonation** workflow with fee, versioned **term eligibility snapshots** (attendance / CIA / fees / holds) that gate exam registration and hall tickets, detention lists, guardian alerts and threshold warnings — all with Mine vs offering/department/all views.

## Feature keys
`attendance.core`, `attendance.on_duty`, `attendance.eligibility_detention`, `attendance.guardian_alerts` (on, starter); `attendance.qr`, `attendance.condonation`, `attendance.offline_mobile` (on, standard); `attendance.biometric`, `attendance.rfid`, `attendance.geo_app` (off, standard). `attendance.staff` was delivered in Phase 06.

## Visibility rules
| Role | Sessions & marks | Summaries | OD / condonation | Eligibility |
|---|---|---|---|---|
| student | S (own attendance per offering) | S (+ shortfall calculator) | S (apply/track) | S (read decision) |
| parent | W | W | W (read) | W (read) |
| faculty | O (sessions of own offerings: mark/finalize) | O | O (recommend OD for own offerings) | — |
| class_advisor / mentor | O (advisees/mentees read) | O | O (recommend) | O (read) |
| hod | D (`attendance:view_all@department`, edit_finalized with reason) | D | D (recommend condonation) | D (read) |
| registrar / principal | A | A | A (approve condonation) | A (compute, decide) |
| exam_cell / COE | A (read) | A | — | A (`exams:eligibility`: compute/apply) |
| accountant | — | — | — | A (fee flag read) |
| auditor | A (read) | A | A (read) | A (read) |

## 11.1 Database tables
Section 12: `class_sessions, student_class_attendance (+default partition), on_duty_requests, attendance_summaries, attendance_condonations, term_eligibility`; `attendance_devices` (§9), `holidays` — exist. Expected delta migration: none.

## 11.2 Alembic migration
`0011_phase11_attendance_seed.py` — data-only: none. Demo seed `--only attendance`: attendance for the last 6 weeks of sessions (85 % present distribution; 12 students below 75 %, 4 below 65 %), 5 OD requests, 3 condonation requests, summaries computed, eligibility snapshot v1 for the current term.

## 11.3 Models — `models/attendance.py`
`StudentClassAttendance` (partitioned parent; `__table_args__` with `postgresql_partition_by="RANGE (session_date)"`), `OnDutyRequest`, `AttendanceSummary`, `AttendanceCondonation`, `TermEligibility`; `ClassSession` from Phase 10 gains the attendance methods. Enums: `AttendanceMark` (present/absent/late/on_duty/leave/medical/exempt), `AttendanceSource`, `OdReasonType`, `OdStatus`, `EligibilityBand` (eligible/condonable/not_eligible/condoned), `CondonationStatus`, `EligibilityDecision`.

## 11.4 Schemas — `app/schemas/attendance.py`
`SessionForAttendance` (session + roster with current marks), `BulkMarkRequest{marks:[{student_program_enrollment_id, status, remarks?}], mark_rest_as?: present|absent, source}`, `MarkResult{updated, unchanged, rejected[]}`, `QrIssueResponse{token, expires_at, png_base64}`, `QrCheckinRequest{token, geo?}`, `GeoCheckinRequest{session_id, lat, lng}`, `PunchIngest{device_token, punches:[{identifier, at, direction?}]}`, `FinalizeRequest{note?}`, `EditFinalizedRequest{marks, reason}`, `SummaryResponse{offering, totals, pct, eligibility, sessions_needed_for_threshold, sessions_can_miss}`, `MySummaryResponse{term, overall_pct (credit-weighted), per_offering[]}`, `OdCreate/Response/Decision`, `CondonationCreate/Response/Decision`, `EligibilityComputeRequest{term_id, college_id?, program_id?, offering_ids?}` + `EligibilityRunSummary`, `EligibilityRow{student, offering, attendance_pct, cia, fee_ok, hold_ok, decision, reason_codes, version}`, `DetentionListRow`, `AlertConfig{consecutive_absences, checkpoints[]}`, `OfflineBatch{items:[BulkMarkRequest with client_ids, idempotency_key]}` + `OfflineBatchResult`.

## 11.5 Repository
`attendance_repository.py` (`module="attendance"`; sessions ownership `ClassSession.staff_id == p.staff_id`; student self via confirmed registration items; department scope through `course_offerings.department_id`; `upsert_marks(session, rows)` with `ON CONFLICT (session_id, student_program_enrollment_id, session_date) DO UPDATE`), `summary_repository.py` (recompute per offering with a single aggregate query), `od_repository.py`, `condonation_repository.py`, `eligibility_repository.py` (`latest_version(term_record, offering)`).

## 11.6 Services
- `attendance_service.py`
  1. `session_for_marking(session, principal)`: roster = confirmed/registered items of the offering (Phase 09) minus withdrawn; existing marks; approved OD/leave auto-fill (`on_duty`/`leave`) for the date; session must be `scheduled|conducted` and date ≤ today (+ setting `attendance.future_marking_days=0`).
  2. `bulk_mark(session, request, principal)`: faculty of the offering (ownership) or HOD/registrar; idempotent upsert; `mark_rest_as`; sets session `conducted`, `attendance_status='taken'`; audit summary (counts) not per row; schedules summary recompute (debounced job per offering) and **guardian alerts** (consecutive absences ≥ setting → `attendance.absent_alert` to guardians with consent, once per streak).
  3. `finalize(session)`: lock; edits afterwards require `attendance:edit_finalized` + reason → per-row audit with old/new; HOD/registrar only. Beat `attendance.auto_finalize` finalizes sessions older than N days (setting) and flags `not_taken` sessions to HOD (`attendance.missing_sessions_digest`).
  4. QR: `issue_qr(session)` → signed token (120 s, rotating) shown by faculty; `qr_checkin(token, geo?)` marks the calling student `present` if registered in the offering and within optional geofence; duplicate check-ins ignored; late window setting → `late`.
  5. Geo app check-in (`attendance.geo_app`): student check-in during the session window inside the room/campus fence (settings) → `present` pending faculty review (`source='app'`).
  6. Device punches (`attendance.biometric|rfid`): token-authenticated ingest; map identifier (enrolment/registration number or card id) → student; attach to the session running at that time in that room/device location (`attendance_devices.location` ↔ `rooms`); unknown/ambiguous punches returned for review.
  7. Offline batch endpoint: accepts multiple session batches with client ids and `Idempotency-Key` per batch; returns per-item results; conflicts on finalized sessions reported (`RECORD_LOCKED`) — mobile shows them.
- `summary_service.py`: `recompute(offering[, student])`: `pct = (present + on_duty + late) / (total_sessions − exempt) × 100` over `conducted|finalized` sessions; band from `RulesResolver` (`attendance_min_pct`, `condonation_floor_pct`); `sessions_needed_for_threshold` = smallest n with `(present+n)/(total+n) ≥ min`; `sessions_can_miss`; term overall = credit-weighted; writes `attendance_summaries`; **checkpoint warnings** (Beat `attendance.checkpoints` at 25/50/75 % of instruction days, setting): students below threshold get `attendance.below_threshold` notifications (student + guardian + mentor).
- `od_service.py`: student applies (date range, reason, documents); faculty of affected offerings recommend or HOD; approve (registrar/HOD per setting) → `sessions_applied` computed (sessions of the student's offerings in range) → marks set to `on_duty` (creating rows for future sessions on generation via consumer of `session.created`); reject/withdraw; workflow `attendance.on_duty` optional; OD excluded from absence streaks.
- `condonation_service.py` (`attendance.condonation`): eligible when `condonation_floor ≤ pct < min` (course-wise or aggregate per `attendance_mode`); request (student/advisor) with reason/documents → workflow `attendance.condonation` (HOD recommend → registrar/principal approve) → fee invoice (`rules.condonation_fee_paise`, Phase 12 `source_type='condonation'`) → on approval + payment → `attendance_summaries.eligibility='condoned'` and eligibility snapshot regenerated for that offering; reject → stays `condonable/not_eligible`.
- `eligibility_service.py`
  1. `compute(term, scope)` (job; `exams:eligibility`): for every (term record, confirmed offering) → attendance pct/band (course-wise) or aggregate (mode), `is_cia_ok` (Phase 13 `cia_consolidations` vs `cia_pass_min_pct` when set; else true), `is_fee_ok` (Phase 12 overdue check when setting `exams.eligibility_requires_fee_clear`), `is_hold_ok` (`hold_service` gate `exam`), decision `eligible | condonable→pending | not_eligible→detained | condoned | debarred (malpractice, Phase 16)`, `reason_codes` (`ATT_BELOW_MIN`, `ATT_CONDONABLE`, `CIA_FAIL`, `FEE_DUE`, `HOLD_EXAM`, `DEBARRED`); new **version** per compute (previous versions retained); summary counts; emits `eligibility.computed`.
  2. `decide(row, decision, reason)` manual override by registrar (`condoned` without fee only with `exams:eligibility` + reason).
  3. `detention_list(term, filters)`; export; notify detained students/guardians (once per version, setting).
  4. Phase 14 consumes `latest_version` into `exam_registrations.eligibility_snapshot`; Phase 15 marks `result_status='detained'` for detained items.

## 11.7 Events / jobs
Emits: `attendance.marked`, `attendance.finalized`, `attendance.edited_after_finalize`, `attendance.absent_alert`, `attendance.below_threshold`, `od.requested/approved/rejected`, `condonation.requested/approved/rejected`, `eligibility.computed`, `eligibility.decided`. Consumers: notifications (alerts, warnings, OD/condonation decisions, detention notices), Phase 12 `fees.condonation_invoice`, Phase 14 `exams.eligibility_snapshot`, Phase 27 `mentoring.risk_flags` (below threshold), `session.created` → apply approved OD marks. Jobs: `attendance.recompute_summaries` (debounced), `eligibility.compute`, `attendance.export`. Beat: `attendance.auto_finalize` (nightly), `attendance.missing_sessions_digest` (daily 18:00 to HODs), `attendance.checkpoints` (daily check against instruction-day milestones), `attendance.streak_alerts` (nightly). Workflows: `attendance.condonation`, `attendance.on_duty` (optional).

## 11.8 Endpoints
```
GET      /api/v1/class-sessions/{id}/attendance                           → roster + marks [attendance:mark|view (own offering)] {attendance.core}
POST     /api/v1/class-sessions/{id}/attendance                           → bulk mark (Idempotency-Key) [attendance:mark]
POST     /api/v1/class-sessions/{id}/finalize · POST /class-sessions/{id}/attendance/edit-finalized [attendance:mark|edit_finalized]
POST     /api/v1/class-sessions/{id}/qr · POST /attendance/qr-checkin [attendance:mark|self] {attendance.qr}
POST     /api/v1/attendance/geo-checkin [attendance:self] {attendance.geo_app}
POST     /api/v1/attendance/devices/{id}/punches (device token) · GET /attendance/punches/unmatched [attendance:device_manage] {attendance.biometric|rfid}
POST     /api/v1/attendance/offline-batch [attendance:mark] {attendance.offline_mobile}
GET      /api/v1/attendance/summary?offering_id=&scope=own|department|all · GET /attendance/summary/me?term_id= · GET /attendance/summary/student/{id} [attendance:view|view_all|self]
GET      /api/v1/attendance/register?offering_id=&from&to                 → session × student grid export [attendance:view]
GET/POST /api/v1/on-duty · POST /on-duty/{id}/recommend|approve|reject|withdraw [attendance:self|mark|approve] {attendance.on_duty}
GET/POST /api/v1/condonations · POST /condonations/{id}/recommend|approve|reject · GET /condonations/me [attendance:condone|self] {attendance.condonation}
POST     /api/v1/terms/{id}/eligibility/compute (job) · GET /terms/{id}/eligibility?offering_id&decision&version · POST /eligibility/{id}/decide [exams:eligibility] {attendance.eligibility_detention}
GET      /api/v1/terms/{id}/detention-list?college_id&program_id&export= [exams:eligibility|view_all]
GET      /api/v1/eligibility/me?term_id= [attendance:self]
GET/PUT  /api/v1/attendance/alert-config [settings:manage] {attendance.guardian_alerts}
```

## 11.9 Frontend
- Faculty `/faculty/attendance` (today/date picker → session cards → **marking grid**: name/photo/roll, tap-cycle status, mark-rest-as, OD/leave prefilled, QR mode full-screen with rotating code and live check-in counter, finalize button, edit-after-finalize dialog with reason), `/faculty/attendance/summary` (per offering table with % bands, checkpoint flags, export register).
- Admin `/admin/attendance` (ScopeTabs Own | Department | All; offering summaries; missing-session report; devices tab with unmatched punches review; alert config), `/admin/attendance/od` (queue: recommend/approve), `/admin/attendance/condonations` (queue with pct, documents, workflow timeline, fee status), `/admin/attendance/eligibility` (term picker → compute job → grid by offering with decision chips and reason codes, version selector, manual decide with reason, detention list export, notify button).
- Student portal `/student/attendance` (per-course cards with % ring, band colour, **shortfall calculator** ("attend next N sessions to reach 75 %" / "can miss N"), session history, QR scan button, OD/condonation requests with status), parent ward attendance (read).
- Nav: ACADEMICS › Attendance; EXAMINATIONS › Eligibility (Phase 14 group).

## 11.10 Mobile
Faculty: **Attendance tab** — sessions list, tap-mark grid (large targets), bulk present, QR projector mode, offline queue with sync status and conflict prompts, finalize; Student: Academics › Attendance (rings, calculator, QR scan check-in, OD request with photo docs), Home attendance ring; Parent: ward attendance; HOD: department summary and condonation recommendations.

## 11.11 API verification — `scripts/verify/11_attendance.ps1`
Roles: `faculty.1` (owns offering X), `faculty.3`, `hod.cse`, `registrar`, `exam.cell`, `student.1` (in X), `student.2` (not in X), `parent.1`, `advisor.1`.
1. Seed `--only attendance`; `GET /class-sessions/{sX}/attendance` as `faculty.1` → roster = confirmed items; as `faculty.3` → 404; as `hod.cse` → 200.
2. Bulk mark (all present, 3 absent) → counts; re-post identical with the same `Idempotency-Key` → replay; changed statuses → `updated`; marking a student not in the roster → `rejected[]` with reason; future session → 409.
3. Finalize → further `POST attendance` → 409 `RECORD_LOCKED`; `edit-finalized` as `faculty.1` → 403; as `hod.cse` with reason → 200 and audit rows with old/new.
4. QR: issue → token; `qr-checkin` as `student.1` → `present(source=qr)`; as `student.2` → 409 `RULE_VIOLATION` `NOT_REGISTERED`; expired token → 401; second scan → no-op.
5. Geo: feature off → 403; on → inside fence → `present(source=app)`, outside → 422.
6. Device punches: ingest with a valid device token (identifier = registration number, time inside session sX in the device's room) → mark created `source=biometric`; unknown identifier → listed in `unmatched`; wrong token → 401.
7. Offline batch with 2 sessions (one finalized) → per-item results: finalized items `RECORD_LOCKED`, others applied; duplicate batch key → replay.
8. Summaries: `GET /attendance/summary?offering_id=X` → pct per student; `student.1` at 72 % → band `condonable`, `sessions_needed_for_threshold` correct (verify formula with the seeded counts); `GET /attendance/summary/me` as `student.1` → credit-weighted overall + per offering; as `parent.1` for ward → 200; for a non-consented ward → 404.
9. Alerts: mark `student.1` absent in 3 consecutive sessions → one `attendance.absent_alert` message log to the guardian (not three); checkpoint job at 50 % instruction days → `below_threshold` notifications to students < 75 % (+ guardian + mentor).
10. OD: `student.1` applies for 2 days (sports) → `faculty.1` recommend → `hod.cse` approve → sessions in range marked `on_duty`, pct recomputed excluding them from absences; OD on a date with a finalized session → mark updated via privileged path with audit.
11. Condonation: `student.1` (72 %) request → workflow HOD recommend → registrar approve → invoice `source_type=condonation` (stub records) → simulate payment → summary `condoned`; a student at 60 % requesting → 409 `RULE_VIOLATION` `BELOW_CONDONATION_FLOOR`.
12. Eligibility: `POST /terms/{t}/eligibility/compute` as `exam.cell` → job → rows for every (term record, offering): `student.1` → `condoned` (after 11), the 60 % student → `detained` with `ATT_BELOW_MIN`, a student with an `exam` hold → `reason_codes` contains `HOLD_EXAM`; recompute → version 2 (v1 retained); `decide` override to `eligible` with reason as registrar → audited; `GET /eligibility/me` as `student.1` → own rows only; detention list export XLSX.
13. Visibility: `GET /attendance/summary?scope=all` as `faculty.1` → narrowed to own offerings (`meta.visibility.scopes=[]`); as `hod.cse` → department; as `registrar` → institution.

## 11.12 UI verification
1. Faculty marking grid: tap-cycle, mark-rest-as, prefilled OD, finalize lock, edit-after-finalize (HOD) with reason; QR mode counter increments as students scan (second browser).
2. Student attendance page: rings, bands, shortfall calculator numbers match the API; QR scan flow (mobile); OD/condonation request forms with document upload and status timeline.
3. Admin ScopeTabs behave per role; devices tab shows unmatched punches; alert config saves.
4. Eligibility page: compute job → grid → version switch → manual decide → detention export; notify sends to detained students.
5. Mobile faculty offline: mark in airplane mode → reconnect → synced with conflict prompt for the finalized session; student ring on Home.

## 11.13 Deliverables checklist
- [ ] Marking (grid/QR/geo/device/offline) with roster from registrations, idempotent upserts, finalize lock + audited edits, extra sessions link; summaries with bands and calculator; alerts/checkpoints; OD; condonation workflow + fee; versioned eligibility compute/decide/detention list
- [ ] Ownership/visibility registrations (faculty own sessions, students self, wards, department/institution)
- [ ] Events/jobs/Beat/workflows; demo seed `--only attendance`
- [ ] Web + mobile; `scripts/verify/11_attendance.ps1` passes; UI checklist done; guards green; commit `feat(phase-11): attendance & eligibility`
