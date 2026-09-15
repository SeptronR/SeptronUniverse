# PHASE 07 — STUDENTS, ENROLMENT, HOLDS & ACADEMIC STANDING

## Pre-Requisite
Phases 01–06 complete (platform, auth/RBAC/features/visibility, institution/terms, comms/workflow, programmes/regulations/batches, HR).

## Objective
The student master and the enrolment model that every later module keys on: student records (registration number, APAAR/ABC ids, category/quota, encrypted Aadhaar/bank, international fields), guardians with consent-controlled portal access, documents, undertakings (anti-ragging/conduct/data consent — e-accepted), **programme enrolments** pinned to a programme-regulation and batch, **term records**, batch promotion/detention, NEP multiple exit/re-entry, credit transfers (MOOC/ABC/prior learning), transfers/migration, **holds** and **academic standing**, ID cards, bulk import, student self-service profile, and the student/parent portal foundations. Admissions (Phase 08) will create students through this module's service.

## Feature keys
`students.core` (core), `students.guardians_portal`, `students.documents`, `students.id_cards`, `students.bulk_import`, `students.self_service_profile` (on, starter); `students.undertakings`, `students.holds`, `students.academic_standing`, `students.transfers_migration` (on, standard); `students.international_office` (off, standard); `academics.credit_transfer_mooc`, `academics.nep_exit_reentry` (on, standard); `academics.abc_apaar` (on, standard; depends `integrations.digilocker_nad`); `portals.student`, `portals.parent` (on).

## Visibility rules
| Role | Students | Enrolments/term records | Holds | Undertakings/documents |
|---|---|---|---|---|
| student | S (own profile, self-update limited) | S | S (read) | S |
| parent | W (wards with `guardian_portal_consent`) | W | W (read) | W (read) |
| faculty | O (students registered in own offerings — link lands in Phase 09; until then mentees/advisees) | O | — | — |
| class_advisor / mentor | O (advisees/mentees) | O | O (read) | O (read) |
| hod | D (`students:view_all@department`) | D | D (read) | D |
| dean | F | F | F | F |
| registrar / institution_admin | A (manage, `students:view_pii`) | A | A (place/release) | A |
| accountant | A (view) | A (view) | A (read; place `fees`-sourced holds via Phase 12) | — |
| admissions_officer | A (view; admit) | — | — | — |
| librarian / warden | A (lookup, masked) / H | — | A/H (place library/hostel holds) | — |
| college_admin | C | C | C | C |
| auditor | A (read) | A (read) | A (read) | A (read) |

Ownership links registered: `students` self (`Student.user_id == p.id`), wards (`StudentGuardian.user_id == p.id AND Student.guardian_portal_consent`), advisees (`BatchSection.class_advisor_staff_id == p.staff_id` via current term record), mentees (Phase 27 adds), own offerings (Phase 09 adds). Scope columns: institution/college/department (`StudentProgramEnrollment.department_id`), faculty via department.

## 07.1 Database tables
Section 8 (`students, student_guardians, student_documents, student_undertakings, student_program_enrollments, student_term_records, student_holds, student_transfers, credit_transfers`) plus `batches, batch_sections` (section 7), `number_sequences`, `credential_sheets`, `consent_records` — exist. Expected delta migration: none.

## 07.2 Alembic migration
`0007_phase07_students_seed.py` — data-only: undertaking templates (anti_ragging, conduct, data_consent, photo_consent, hostel_rules) as platform `document_templates` (template_type `undertaking`, IN pack texts). Demo seed `--only students`: 400 students across 2 programmes × batches 2024/2025 × sections, guardians, documents, undertakings accepted, term records for the current term, 5 holds, 3 credit transfers, 2 exited students.

## 07.3 Models — `models/students.py`
`Student` (encrypted `aadhaar_encrypted`, `bank_details_encrypted`), `StudentGuardian`, `StudentDocument`, `StudentUndertaking`, `StudentProgramEnrollment`, `StudentTermRecord`, `StudentHold`, `StudentTransfer`, `CreditTransfer`. Enums: `Gender`, `Category`, `StudentStatus`, `EntryType`, `EnrollmentStatus`, `TermRecordStatus`, `HoldType`, `AcademicStanding`, `TransferType`, `CreditTransferSource/Status`, `UndertakingType`. Relationships `lazy="noload"`; repositories use `selectinload`.

## 07.4 Schemas — `app/schemas/students.py`
`StudentCreate` (personal, category/quota, contacts, addresses, guardians[], programme/batch/regulation, entry type/term, admission date/mode, apaar_id, is_international + passport/visa/frro), `StudentUpdate` (registrar), `StudentSelfUpdate` (phone/email/current address/photo/emergency contact), `StudentResponse` (masked PII by default; `Masked[str]` for aadhaar/bank), `StudentDetailResponse` (+ enrolment, current term record, holds summary, standing, guardians, documents, undertakings status), `StudentListItem`, `GuardianIn/Out`, `GuardianPortalConsentUpdate`, `DocumentIn/Out`, `UndertakingAccept{undertaking_type, template_id, signature_data_url?}`, `EnrollmentResponse`, `TermRecordResponse`, `PromoteBatchRequest{batch_id, to_term_number, apply_detention_rule: bool, dry_run: bool}` + `PromotionPreview{promoted[], detained[{student, backlogs}], on_break[]}`, `ExitRequest{exit_award, exit_date, reason}`, `ReentryRequest{program_id, batch_id, entry_term_number, carried_credit_transfer_ids[]}`, `HoldCreate{hold_type, reason, source_type?, source_id?}`, `HoldResponse`, `HoldReleaseRequest{reason}`, `TransferCreate/Response`, `CreditTransferCreate/Response/Decision`, `StandingResponse{standing, history[]}`, `BulkImportResult{succeeded, failed:[{row, reason}]}`, `IdCardRequest{student_ids[]}`, `StudentStats`.

## 07.5 Repository
`student_repository.py` (`module="students"`; trgm search on name/registration number/phone/email; filters college/department/programme/batch/section/status/category/standing/has_holds; `selectinload(enrollments.current)`), `enrollment_repository.py`, `term_record_repository.py` (`get_or_create(enrollment, term)`), `hold_repository.py` (`open_holds(enrollment_id, gate)`), `transfer_repository.py`, `credit_transfer_repository.py`, `guardian_repository.py`. Visibility registrations per the table above (`students`, `enrollments` share the module `students`).

## 07.6 Services
- `student_service.py`
  1. `create(data, source="manual"|"admission")`: validate category/quota against the pack; APAAR checksum (`packs.validators.validate_apaar`); `registration_number` from `number_sequences` (`regno:{yyyy}:{program_code}` or institution pattern) unless supplied by the affiliating university (`institution.type=affiliated_college` → optional manual with uniqueness); create user (username = registration number, temp password, role `student`, `must_change_password`); guardians → optional guardian users (role `parent`, linked by phone/email; reuse existing guardian user across siblings) when `students.guardians_portal`; programme enrolment (`program_regulation` = active regulation for the programme whose `effective_from_admission_year ≤ admission year`, unless given), batch (create-if-missing per college/programme/year/entry type), term record for the current term; consent records (`data_consent`); emits `student.created` (→ search index, fees assignment in Phase 12, library membership in Phase 19, ABC registration in Phase 18).
  2. `update` (registrar) with `version`; `self_update` limited; PII read/write gated by `students:view_pii`/`students:manage`.
  3. Status transitions (`provisional → admitted → active` on first confirmed registration [Phase 09 event], `on_break`, `detained`, `dropped_out`, `transferred`, `exited`, `graduated` [Phase 18], `alumni` [Phase 29], `expelled` [Phase 27], `deceased`) with allowed-transition map and audit; deactivating the user on terminal states except `graduated/alumni`.
  4. Guardians CRUD; `guardian_portal_consent` toggle by the student (adult) or registrar; parents see only consented wards.
  5. Documents CRUD with verification and expiry (Beat `students.document_expiry`); undertakings: accept records ip/user-agent/signature; **gates**: registration (Phase 09) and hostel (Phase 20) require `anti_ragging` + `conduct` accepted for the current academic year (setting `students.undertakings_required=[…]`).
  6. ID cards: job renders `document_templates(id_card)` with QR (signed token → `/verify/{token}`) per student, zip; single download.
  7. Bulk import (job) from CSV/XLSX template (`registration_number?,first_name,last_name,dob,gender,category,quota,program_code,batch_code,section,entry_type,phone,email,guardian_name,guardian_phone,apaar_id,…`) with dry-run and partial-success report; export XLSX (masked unless `view_pii`).
  8. `stats(scope)`: counts by programme/batch/category/gender/standing/status for dashboards and AISHE.
- `enrollment_service.py`
  1. `promote_batch(request)`: for each active enrolment in the batch with a term record for the current term: if `backlog_count > rules.max_backlogs_for_promotion` (from `student_arrears`, Phase 09/15) → `detained` (enrolment status + term record `detained`); else create next term record (`term_number+1`) and set batch `current_term_number`; `dry_run` returns the preview; emits `batch.promoted`, `student.detained`; hook from Phase 03 rollover (`on_rollover`) calls this when `promote_batches=true`.
  2. `exit(enrollment, award)`: allowed only at `program_structure_terms.is_exit_point` and `credits_earned ≥ exit_points[award].min_credits` (Phase 15 keeps `credits_earned`; before that the check reads the field); status `exited_early`, student `exited`, emits `student.exited` → Phase 18 creates `degrees_awarded(certificate|diploma)`.
  3. `reentry(request)`: new enrolment `entry_type='exit_reentry'` (partial unique index guarantees one active), links carried credit transfers (`credit_transfers.source='internal_prior'`), term record at `entry_term_number`.
  4. `change_section`, `change_regulation` (explicit, audited; creates `credit_transfers(internal_prior)` mapping by course code equivalence).
  5. `recompute_standing(enrollment)` (called by Phase 15 publish; rules from `RulesResolver.rules.standing_rules`): evaluates SGPA/CGPA history → `good|warning|probation|dismissal`; `dismissal` places an `all` hold and notifies; history stored in `audit_logs`.
- `hold_service.py`: `place(enrollment, hold_type, reason, source)`, `release(hold, reason)`, `assert_clear(enrollment, gate)` raising `409 HOLD_BLOCKED {hold_type, reason}` — used by registration (`registration|all`), exam registration/hall ticket (`exam|all`), transcript (`transcript|all`), degree (`graduation|all`), hostel allotment (`hostel|all`), library issue (`library|all`); sources: manual, fees (Phase 12 auto-places `registration/exam` holds for overdue per setting), library (Phase 19), hostel (Phase 20), discipline (Phase 27); notifies student/guardian on place/release.
- `transfer_service.py`: migration/transfer requests with workflow `students.transfer` (registrar → principal), dues check (`no_dues` request auto-created, Phase 12), certificates (TC/migration via Phase 26 templates; numbers from sequences), status machine `requested → dues_check → approved → completed`.
- `credit_transfer_service.py`: submit (student) with certificate; verify (department/registrar) → `equivalent_course_id` or basket; approve → creates `student_course_results(attempt_type='credit_transfer')` through Phase 15 service (before Phase 15 exists, approval stores `status='approved'` and Phase 15 backfills on install — document this in the prompt's notes); MOOC credits capped by `rules.mooc_max_credits`; ABC fetch via adapter (`CreditBank.fetch_learner`) when `academics.abc_apaar`.
- Portals foundation: `GET /students/me/dashboard` (profile, enrolment, term, holds, undertakings pending, quick links) and `GET /guardians/me/wards` (+ per-ward dashboard) — later phases add widgets.

## 07.7 Events / jobs
Emits: `student.created/updated/status_changed/exited/reentered`, `guardian.linked`, `undertaking.accepted`, `hold.placed/released`, `batch.promoted`, `student.detained`, `standing.changed`, `transfer.requested/completed`, `credit_transfer.approved`. Consumers: `search.reindex`, `notifications` (welcome + credentials, hold placed/released, promotion/detention, transfer decisions), Phase 12 `fees.assign_on_create`, Phase 19 `library.member_on_create`, Phase 18 `abc.register`. Jobs: `students.bulk_import`, `students.export`, `students.id_cards`. Beat: `students.document_expiry` (weekly), `students.undertaking_reminders` (start of year). Workflows: `students.transfer`, `students.credit_transfer` (department verify → registrar).

## 07.8 Endpoints
```
GET/POST /api/v1/students · GET/PUT /students/{id} · POST /students/{id}/status · POST /students/{id}/photo [students:view|view_all|create|update|manage]
GET/PUT  /api/v1/students/me · GET /students/me/dashboard [students:self] {portals.student}
GET      /api/v1/students/stats?college_id&program_id&batch_id [students:view_all]
POST     /api/v1/students/bulk-import?dry_run= · GET /students/export · GET /students/import-template [students:bulk_import|export] {students.bulk_import}
POST     /api/v1/students/id-cards (job) · GET /students/{id}/id-card.pdf [students:id_card] {students.id_cards}
GET/POST /api/v1/students/{id}/guardians · PUT/DELETE /students/{id}/guardians/{gid} · PUT /students/{id}/guardian-consent [students:update|self] {students.guardians_portal}
GET      /api/v1/guardians/me/wards · GET /guardians/me/wards/{student_id}/dashboard [students:view (wards)] {portals.parent}
GET/POST /api/v1/students/{id}/documents · POST /documents/{id}/verify · DELETE /documents/{id} [students:update|view] {students.documents}
GET      /api/v1/students/me/undertakings/pending · POST /students/me/undertakings [students:undertakings|self] {students.undertakings}
GET      /api/v1/students/{id}/enrollments · GET /enrollments/{id} · GET /enrollments/{id}/term-records [students:view]
POST     /api/v1/enrollments/{id}/section · POST /enrollments/{id}/change-regulation [students:manage]
POST     /api/v1/batches/{id}/promote?dry_run= [batches:promote]
POST     /api/v1/enrollments/{id}/exit · POST /students/{id}/reentry [students:exit] {academics.nep_exit_reentry}
GET/POST /api/v1/students/{id}/holds · POST /student-holds/{id}/release [students:holds|view] {students.holds}
GET      /api/v1/students/{id}/standing [students:view] {students.academic_standing}
GET/POST /api/v1/students/{id}/transfers · POST /student-transfers/{id}/approve|complete [students:transfer] {students.transfers_migration}
GET/POST /api/v1/credit-transfers · POST /credit-transfers/{id}/verify|approve|reject · GET /credit-transfers/me [credit_transfers:create|verify|approve|view] {academics.credit_transfer_mooc}
GET      /api/v1/verify/{token}                                          → public verification of ID card / documents {public}
```

## 07.9 Frontend
- `/admin/students` (DataTable: reg no, name, programme, batch/section, term, status, standing chip, holds badge; filters; ScopeTabs Mine(advisees) | Department | College | All; bulk import wizard with dry-run report; export; ID cards job), `/admin/students/new` (5-step wizard: personal → academic (programme/batch/regulation auto) → guardians → documents → review), `/admin/students/:id` (360°: header with photo/reg no/status/standing/holds; tabs Profile | Guardians | Documents | Undertakings | Enrolment & term records | Holds | Transfers | Credit transfers | Attendance/Marks/Fees/Hostel/Library placeholders for later phases), `/admin/students/promotion` (batch picker → dry-run preview table → confirm), `/admin/students/holds` (queue), `/admin/students/transfers`, `/admin/students/credit-transfers` (verification queue).
- Student portal `/student` (dashboard cards; pending undertakings banner blocks other actions until accepted; profile self-update; ID card QR; credit-transfer submission; holds banner with reason and contact), parent portal `/parent` (ward switcher; ward dashboard; consent-limited).
- Nav: STUDENTS › Students, Promotion, Holds, Transfers, Credit transfers.

## 07.10 Mobile
Student shell: Home (profile card, holds banner, pending undertakings gate), More › Profile (self-update, photo), ID card (QR), Credit transfers (submit with certificate photo); Parent shell: ward switcher + dashboard; Registrar/HOD/Faculty: Students search → 360° (masked), advisees list.

## 07.11 API verification — `scripts/verify/07_students.ps1`
Roles: `registrar`, `hod.cse`, `hod.ece`, `advisor.1`, `faculty.2`, `accountant`, `student.1`, `parent.1`, `parent.noconsent`, `librarian`.
1. Seed `--only students`; `GET /students` as `registrar` → 400 rows, `meta.visibility.scopes=["institution"]`, `pii=true`; as `hod.cse` → CSE only, `scopes=["department"]`; as `advisor.1` → own section only, `scopes=[]`; as `faculty.2` → empty (no offerings yet); as `accountant` → all, `pii=false` (aadhaar masked).
2. `POST /students` (B.Tech CSE, batch 2026 auto-create, guardians ×2, apaar valid) as `registrar` → 201; `registration_number` pattern matches; user `student` created; guardian users created/reused (second student with the same guardian phone → same guardian user); invalid APAAR checksum → 422; category `XYZ` → 422 (pack).
3. `GET /students/me` as `student.1` → own; `PUT /students/me {first_name:"X"}` → 422 (not self-editable); `{phone:"…"}` → 200.
4. Undertakings: `GET /students/me/undertakings/pending` → 2 pending for a fresh student; `POST /students/me/undertakings {anti_ragging}` → accepted with ip; `POST /_dev/gates/registration-check` (dev) → `HOLD_BLOCKED`-style `RULE_VIOLATION` `UNDERTAKING_PENDING` until `conduct` accepted.
5. Guardians: `parent.1` `GET /guardians/me/wards` → 1 ward; ward toggles `guardian_portal_consent=false` → `parent.1` sees 0 wards and `GET /students/{ward}` → 404; `parent.noconsent` sees nothing.
6. Holds: `librarian` `POST /students/{id}/holds {hold_type:"library"}` → 201; `registrar` `POST … {hold_type:"all"}` → 201; `hold_service.assert_clear` via dev route for gate `registration` → 409 `HOLD_BLOCKED`; `librarian` releasing the `all` hold → 403; registrar releases → `GET /students/{id}/holds` shows released with reason; student notified.
7. Promotion: `POST /batches/{2024}/promote?dry_run=true` → preview lists 2 detained (seeded backlogs > 4) and 198 promoted; run → term records created for term N+1, `current_term_number` incremented, `student.detained` events, detained enrolments `status=detained`; re-run → idempotent (no duplicate term records).
8. Exit: `POST /enrollments/{id}/exit {exit_award:"diploma"}` for a student in term 3 (not an exit point) → 409 `RULE_VIOLATION`; term 4 with credits ≥ 80 → 200 → status `exited_early`, event `student.exited`; re-entry → new enrolment `exit_reentry`, only one active enrolment (unique index).
9. Standing: dev route sets CGPA history → `recompute_standing` → `probation`; `GET /students/{id}/standing` shows history; `dismissal` places an `all` hold.
10. Transfer: `POST /students/{id}/transfers {transfer_type:"migration_out"}` → workflow instance for registrar; approve → status `approved`; complete → certificate numbers assigned (or placeholder until Phase 26) and student `transferred`.
11. Credit transfer: student submits NPTEL certificate (4 credits) → `hod.cse` verify with equivalent course → registrar approve → status `approved` (result row created when Phase 15 exists); 4th transfer exceeding `mooc_max_credits=12` → 422.
12. Bulk import: dry-run 50 rows (3 bad) → report; apply → 47 created; export XLSX masked as `accountant`, unmasked as `registrar`.
13. ID cards: job → zip; `GET /verify/{token}` (public) → student name + reg no + status.
14. Auditor: reads OK, writes 403.

## 07.12 UI verification
1. Students list as registrar/HOD/advisor/accountant shows the expected scopes and masking; ScopeTabs present only for roles with `view_all`.
2. New-student wizard end-to-end; 360° page tabs; status change dialog with allowed transitions only.
3. Promotion page dry-run table with detained reasons; confirm runs the job; tray shows progress.
4. Holds queue: place/release with reasons; student portal shows the hold banner.
5. Student portal: pending undertakings gate blocks navigation to registration/hostel until accepted; profile self-update; ID card QR opens `/verify`.
6. Parent portal: ward switcher; consent removal hides the ward on next load.
7. Mobile: student profile/ID card/undertakings; parent ward switcher; registrar student search.

## 07.13 Deliverables checklist
- [ ] Student master + guardians (+ portal consent) + documents + undertakings (+ gates) + enrolments + term records + promotion/detention + exit/re-entry + holds service (`assert_clear`) + standing recompute + transfers workflow + credit transfers + ID cards + bulk import/export + stats
- [ ] Visibility registrations (self, wards, advisees; department/college scopes) with `meta.visibility`
- [ ] Events/jobs/workflows; demo seed `--only students`; portal dashboards (student/parent)
- [ ] Web pages + mobile screens; `scripts/verify/07_students.ps1` passes; UI checklist done; guards green; commit `feat(phase-07): students, enrolment, holds, standing`
