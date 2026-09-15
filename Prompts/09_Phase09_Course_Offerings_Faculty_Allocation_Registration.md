# PHASE 09 — COURSE OFFERINGS, FACULTY ALLOCATION & COURSE REGISTRATION

## Pre-Requisite
Phases 01–08 complete (students with term records; curriculum; HR workloads; workflow engine; fees stub until Phase 12).

## Objective
The term operating model: **course offerings** (course × term × college × department × section with faculty and seats; bulk-generated from the curriculum for target batches), faculty allocation from HOD proposals with workload checks, **registration windows** (regular/add-drop/late/arrear/summer/audit/minor-honours), the student **registration cart** with credit min/max, prerequisite/co-/anti-requisite checks, seat control under row locks, waitlists, elective choice forms and allocation runs (priority-CGPA/FCFS/lottery/manual), advisor approval via workflow, arrears register, admin overrides and bulk registration, rosters, fee linkage. From here on, attendance, marks and results hang off offerings and confirmed registration items.

## Feature keys
`registration.core`, `registration.self_service`, `registration.add_drop`, `registration.arrears` (on, starter); `registration.advisor_approval`, `registration.elective_allocation`, `registration.waitlist`, `registration.overrides` (on, standard); `registration.audit_courses` (off, standard); `hr.workload` (on).

## Visibility rules
- Offerings: institution-wide read for staff; students see offerings of their programme-regulation/term; `offerings:manage@department` (HOD), `offerings:create` registrar/dean.
- Registrations: **student** self; **class_advisor** advisees (approval); **hod** department; **registrar/institution_admin** all (`registration:manage/override`); parents read wards' confirmed items; faculty see rosters of own offerings (ownership link `course_offering_faculty.staff_id`).
- Arrears: self; advisor/HOD/registrar as above; COE read (Phase 14).
- Ownership link **own offerings** registered here for `students` module too (faculty see students registered in their offerings — needed by attendance/marks).

## 09.1 Database tables
Section 11: `course_offerings, course_offering_faculty, course_offering_targets, registration_windows, course_registrations, course_registration_items, elective_choice_forms, elective_allocation_runs, offering_waitlists, student_arrears`; plus `faculty_workloads, course_allocation_proposals` (§9) — exist. Expected delta migration: none.

## 09.2 Alembic migration
`0009_phase09_registration_seed.py` — data-only: none. Demo seed `--only offerings`: offerings for the current term for batches 2024/2025 (all curriculum courses, 2 sections each), faculty allocated, PE basket with 4 offerings (seats 30), registration windows (regular open now; add-drop; arrear), 380 registrations submitted/approved, 15 waitlisted, 10 arrears registrations, 20 elective choice forms.

## 09.3 Models — `models/offerings.py`, `models/registration.py`
`CourseOffering`, `CourseOfferingFaculty`, `CourseOfferingTarget`, `RegistrationWindow`, `CourseRegistration`, `CourseRegistrationItem`, `ElectiveChoiceForm`, `ElectiveAllocationRun`, `OfferingWaitlist`, `StudentArrear`. Enums: `OfferingStatus`, `DeliveryMode`, `FacultyRole`, `WindowType`, `RegistrationStatus`, `ItemStatus`, `RegistrationType`, `WaitlistStatus`, `ArrearStatus`.

## 09.4 Schemas — `app/schemas/offerings.py`, `registration.py`
`OfferingCreate/Update/Response` (course summary, term, department, section, coordinator, faculty[], seats/enrolled/waitlist, delivery mode, link, targets[], status), `BulkFromCurriculumRequest{term_id, batch_ids[], sections_per_course, default_seats, include_baskets}` + `BulkPreview`, `OfferingFacultyReplace{items:[{staff_id, role, hours_per_week}]}`, `OfferingTargetsReplace`, `RosterItem`, `WindowCreate/Update/Response`, `CatalogResponse{term, structure_term, limits{min,max,normal}, curriculum:[…offerings grouped by course with mandatory flag], baskets:[…], arrears:[…], holds[], undertakings_pending[], fee_preview}`, `CartItemAdd{offering_id, registration_type, priority?}`, `RegistrationResponse` (+ items with statuses, totals, workflow timeline, fee invoice), `SubmitResponse`, `AdvisorDecision{decision, comment, item_decisions?}`, `ChoiceFormSubmit{choices:[{course_id, priority}]}`, `AllocationRunRequest{basket_id, term_id, mode?, dry_run}` + `AllocationSummary`, `WaitlistResponse`, `ArrearResponse`, `OverrideRequest{reason, max_credits?, skip_prerequisites?[], skip_holds?}`, `BulkRegisterRequest{batch_id, section_id?, term_id, include_electives:false}`.

## 09.5 Repository
`offering_repository.py` (`module="offerings"`; filters term/college/department/course/faculty/status; `for_update` on seat changes; `roster(offering)`), `registration_repository.py` (`module="registration"`; self predicate via enrolment → `Student.user_id`; advisor link via `BatchSection.class_advisor_staff_id` of the term record; department scope via enrolment; `selectinload(items)`), `window_repository.py` (`open_windows(term, enrollment)` by `applies_to` rules), `choice_form_repository.py`, `waitlist_repository.py`, `arrear_repository.py` (`open_for(enrollment)`). Register ownership link `own_offerings` on `students` (faculty → students with confirmed items in their offerings, current term).

## 09.6 Services
- `offering_service.py`
  1. CRUD; `section_code` unique per (term, course); requires `course.status='active'` and regulation active (Phase 05 rule); `max_seats` default from `course.max_seats`/setting; `is_arrear_only` offerings for backlog-only courses.
  2. `bulk_from_curriculum(request)`: for each target batch → its programme-regulation structure term = `batch.current_term_number` → mandatory courses + basket courses (if `include_baskets`) → offerings (dedupe existing), targets rows, sections per course; preview then apply (job when > 200).
  3. Faculty allocation: `replace_faculty` validates staff active, teaching, department (or cross-department allowed with dean approval flag), computes `faculty_workloads` (Phase 06 service) and warns/blocks when above norm (setting `hr.workload_enforce=block|warn`); `apply_allocation_proposal(proposal)` from Phase 06.
  4. Status `planned → open (registration) → closed (add-drop end) → in_progress → marks_entry (Phase 13) → completed (Phase 15)`; `cancelled` only with zero confirmed items (else substitute).
  5. Roster export (XLSX) and `enrolled_count` recomputation job.
- `registration_service.py`
  1. `catalog(enrollment, term)`: window lookup (`applies_to` match; else 409 `WINDOW_CLOSED`); limits from structure term (or window override); curriculum courses → offerings targeted to the batch/section (fallback: any offering of the course in the college); baskets with choice status; open arrears (`student_arrears.status='open'` → arrear offerings or `is_arrear_only`); holds (`hold_service.assert_clear(enrollment,'registration')` reported, not raised); undertakings pending; fee preview (Phase 12 `fee_service.preview_registration`, stub before).
  2. `add_item(cart, offering, type)` (locks offering row): checks — offering open for the term; course belongs to enrolment's regulation (or basket/minor allowed); **prerequisite**: hard `prerequisite` needs a `student_course_results` row with `result_status='pass'` (+ `min_grade`) [Phase 15 table; before Phase 15, `credit_transfers.approved` and a dev bypass flag]; `corequisite` must be in the cart (validated at submit); `antirequisite` blocks if passed/registered; duplicates; credit projection ≤ max; seat: `enrolled_count < max_seats` → `selected` and `enrolled_count += 1` else `waitlisted` (+ waitlist row with position) if `registration.waitlist` else 409 `SEATS_FULL`; audit type allowed only when `registration.audit_courses`.
  3. `remove_item`: within window → `dropped` (seat released → promote first waitlisted → notify with `offered_until`); after `add_drop_end` (locked) → not allowed via self (registrar `withdraw` marks `withdrawn` = `W`).
  4. `submit(cart, idempotency)`: co-requisite completeness; credits `min ≤ Σ ≤ max`; holds (`assert_clear`); undertakings; `requires_fee_clearance` → no overdue invoices (Phase 12); arrear items require an `arrear`-type window or `rules.allow_arrear_with_regular`; attempt numbers = `arrears.attempts + 1`; fee invoice (`fee_service.create_registration_invoice`: tuition per structure + per-credit arrear fee + late fee when window is `late`) — Phase 12; status `submitted` → if window `requires_advisor_approval` and `registration.advisor_approval` → workflow `registration.advisor` (approver = class advisor of the section; fallback HOD) → `advisor_pending`; else `approved` directly; emits `registration.submitted`.
  5. Workflow hooks: approved → items `selected → confirmed`, `student_term_records.status='registered'`, `credits_registered`, student `provisional/admitted → active`, arrears `open → registered`, emits `registration.approved` (→ attendance rosters Phase 11, fees Phase 12, LMS enrolment Phase 13, search); rejected/changes_requested → back to `draft` with advisor comment.
  6. Auto-lock at `add_drop_end` (Beat `registration.lock_windows`): `approved → locked`; later removal only via registrar `withdraw`.
  7. `override(registration, request)` (registrar): raise max credits, skip listed prerequisites, skip holds (reason mandatory, audited).
  8. `bulk_register(batch, term)`: registrar registers all active enrolments for mandatory courses (electives excluded unless allocated), auto-approved, seats enforced (report shortfalls).
- `elective_service.py`: choice forms (submit/replace within window; priorities unique; courses ⊂ basket); `allocate(basket, term, mode, dry_run)` (job): candidates = forms submitted; `priority_cgpa` sorts by current CGPA desc (`student_term_results` latest; before Phase 15 by registration number), `fcfs` by `submitted_at`, `lottery` seeded random; walk each student's choices → first offering with free seat → `allocated_course_id` + cart item `selected` (or `confirmed` when auto-approve setting); unallocated → `manual`; summary; emits `elective.allocated` → notifications.
- `waitlist_service.py`: promotion on seat release (FCFS), `offered_until` 48 h → accept (student) → confirmed; expire (Beat) → next.
- `arrear_service.py`: maintained transactionally by Phase 15 publish (`fail → open`, `pass → cleared`); registration reads/updates `registered`; waiver by registrar with reason; per-student arrears view.

## 09.7 Events / jobs
Emits: `offering.created/updated/status_changed`, `offering.faculty_changed`, `registration.submitted/approved/rejected/locked/withdrawn`, `registration.item_dropped`, `waitlist.offered/promoted/expired`, `elective.allocated`, `arrear.registered/waived`. Consumers: notifications (window open/closing reminders, approval decisions, waitlist offers, allocation results), Phase 06 `workload.recompute` ← `offering.faculty_changed`, Phase 11 `attendance.roster_sync` ← `registration.approved/item_dropped/withdrawn`, Phase 12 `fees.registration_invoice`, Phase 13 `lms.enrol`. Jobs: `offerings.bulk_from_curriculum`, `offerings.roster_export`, `registration.bulk_register`, `elective.allocate`, `registration.export`. Beat: `registration.window_status` (5 min: scheduled→open→closed), `registration.lock_windows` (hourly), `waitlist.expire` (hourly), `registration.reminders` (daily during windows). Workflow: `registration.advisor`.

## 09.8 Endpoints
```
GET/POST /api/v1/course-offerings · GET/PUT /course-offerings/{id} · POST /course-offerings/{id}/status · DELETE (cancel) [offerings:view|create|update|manage]
POST     /api/v1/course-offerings/bulk-from-curriculum?dry_run= (job) [offerings:bulk_create]
PUT      /api/v1/course-offerings/{id}/faculty · PUT /course-offerings/{id}/targets [offerings:allocate_faculty|manage]
GET      /api/v1/course-offerings/{id}/roster · GET /course-offerings/{id}/roster/export [offerings:view (own or scope)]
GET      /api/v1/course-offerings/mine?term_id=                          → faculty's offerings [auth]
GET/POST /api/v1/registration-windows · PUT /registration-windows/{id} · POST /registration-windows/{id}/status [registration:manage] {registration.core}
GET      /api/v1/registration/me/catalog?term_id= [registration:self] {registration.self_service}
GET      /api/v1/registration/me?term_id= · POST /registration/me/items · DELETE /registration/me/items/{item_id} [registration:self]
POST     /api/v1/registration/me/submit (Idempotency-Key) [registration:self]
POST     /api/v1/registration/me/waitlist/{id}/accept [registration:self] {registration.waitlist}
GET      /api/v1/registration?scope=advisees|department|all&term_id&status [registration:view|approve|view_all]
GET      /api/v1/registration/{id} · POST /registration/{id}/approve|reject|request-changes [registration:approve] {registration.advisor_approval}
POST     /api/v1/registration/{id}/override · POST /registration/{id}/withdraw-item/{item_id} · POST /registration/{id}/lock|unlock [registration:override|manage] {registration.overrides}
POST     /api/v1/registration/bulk-register (job) [registration:bulk]
GET/POST /api/v1/elective-baskets/{id}/choices/me · PUT (replace) [registration:self]
POST     /api/v1/elective-baskets/{id}/allocate?term_id&dry_run= (job) · GET /elective-allocation-runs/{id} [registration:allocate] {registration.elective_allocation}
GET      /api/v1/students/{id}/arrears · GET /arrears/me · POST /arrears/{id}/waive [students:view|self|manage] {registration.arrears}
GET      /api/v1/students/{id}/registrations                              → history [students:view]
```

## 09.9 Frontend
- `/admin/academics/offerings` (term picker; grid department × course; create/edit drawer; faculty assignment with workload badge (hours vs norm, block/warn); targets; bulk-from-curriculum wizard with preview; status actions; roster page with export), `/admin/registration/windows` (calendar-like list, applies-to builder), `/admin/registration` (ScopeTabs Advisees | Department | All; DataTable status/credits/fee; detail with items, checks results, workflow timeline; approve/reject/request-changes; override dialog; withdraw item; bulk-register wizard), `/admin/registration/allocation` (basket + term → dry-run summary → run → results table with manual assignment for unallocated), `/admin/registration/arrears` (per student/course; waive).
- Student portal `/student/registration` (**cart**: curriculum courses pre-ticked with mandatory locks, basket pickers, arrears tab, audit tab (feature), credit meter min/normal/max, prerequisite/anti-requisite hints, seat availability + waitlist join, holds/undertakings banners, fee preview, submit with confirmation; status/timeline; waitlist offers with accept; elective choice form with drag-to-rank), `/student/registrations` history.
- Faculty `/faculty/offerings` (my offerings, roster), parent `/parent` ward's confirmed courses.
- Nav: ACADEMICS › Offerings, Registration, Windows, Elective allocation, Arrears.

## 09.10 Mobile
Student: Academics › Registration (cart with the same checks, submit, timeline, waitlist accept, elective ranking); Faculty: Courses › My offerings (roster); Advisor: Approvals (registration cards with items and approve/reject/request-changes); HOD: Department › Offerings (faculty assignment read, workload badges).

## 09.11 API verification — `scripts/verify/09_registration.ps1`
Roles: `registrar`, `hod.cse`, `dean.eng`, `faculty.1` (allocated), `faculty.3` (not allocated), `advisor.1`, `student.1` (CSE sem 3, advisee of advisor.1), `student.arrear` (open arrear), `student.hold` (registration hold), `parent.1`.
1. Seed `--only offerings`; `GET /course-offerings?term_id` as `faculty.3` → 200 read; `PUT /course-offerings/{x}/faculty` as `faculty.3` → 403; as `hod.cse` for a CSE offering → 200; workload of `faculty.1` above norm with `hr.workload_enforce=block` → 409 `RULE_VIOLATION` `WORKLOAD_EXCEEDED`; with `warn` → 200 + `warnings[]`.
2. Bulk from curriculum dry-run for batch 2025 → preview N offerings; apply → created without duplicates on re-run.
3. Catalog: `GET /registration/me/catalog` as `student.1` → mandatory courses with targeted offerings, basket PE-III with 4 options, limits {min 16, max 26}, `holds=[]`, `fee_preview`; as `student.hold` → `holds=[registration]`.
4. Cart: add mandatory offerings (5) → `selected`, `enrolled_count` increments; add a course whose prerequisite is not passed → 409 `RULE_VIOLATION` `PREREQUISITE_NOT_MET` (dev flag off); add a full offering (`max_seats` reached) → `waitlisted` with position 1; add an `antirequisite` of a passed course → 409; credits above max → 409 `CREDIT_LIMIT`.
5. Submit with credits below min → 409; with co-requisite missing → 409 listing the pair; fix → 200 `advisor_pending`, invoice created (Phase 12 stub records the intent), workflow instance for `advisor.1`; replay the same request with the same `Idempotency-Key` → same response (`IDEMPOTENT_REPLAY`).
6. `POST /registration/{id}/approve` as `faculty.3` → 403; as `advisor.1` → `approved`, items `confirmed`, term record `registered`, `credits_registered` set, student status `active`, event `registration.approved`; parent `GET /guardians/me/wards/{id}/dashboard` shows confirmed courses.
7. `student.hold` submit → 409 `HOLD_BLOCKED`; registrar `override {skip_holds:true, reason}` → submit passes; audit row with reason.
8. Waitlist: drop a confirmed item in another student's approved registration (advisor request-changes → drop) → seat released → `student.1`'s waitlisted item `offered` with `offered_until`; `POST /registration/me/waitlist/{id}/accept` → `confirmed`; Beat `waitlist.expire` on an expired offer → next in line.
9. Add/drop lock: move `add_drop_end` to yesterday, run `registration.lock_windows` → `locked`; `DELETE /registration/me/items/{id}` → 409 `RECORD_LOCKED`; registrar `withdraw-item` → `withdrawn` (Phase 15 will print `W`).
10. Arrears: `student.arrear` catalog lists the open arrear with an `arrear` window open; add → `registration_type=arrear`, `attempt_number=2`; submit outside an arrear window with `allow_arrear_with_regular=false` → 409; waive by registrar → `waived`.
11. Elective allocation: 20 choice forms → `allocate?mode=priority_cgpa&dry_run=true` → summary (per course allocated/unallocated); run → items created; a student ranked lowest with all choices full → `manual`; `fcfs` mode ordering verified with two forms differing by `submitted_at`.
12. Bulk register batch 2026 (fresh, no electives) → all mandatory items confirmed; shortfall report when an offering lacks seats.
13. Visibility: `GET /registration?scope=all` as `advisor.1` → narrowed to advisees, `meta.visibility.scopes=[]`; as `hod.cse` → `department`; as `registrar` → `institution`; `GET /students` as `faculty.1` → students in own offerings (link active), as `faculty.3` → empty.

## 09.12 UI verification
1. Offerings grid, faculty assignment with workload badges (block vs warn), bulk wizard preview → apply, roster export.
2. Student cart: pre-ticked mandatory, prerequisite hint, seat counters and waitlist join, credit meter turns red above max, holds/undertakings banners block submit, fee preview, submit → timeline; waitlist offer accept; elective rank drag; history page.
3. Advisor approvals: registration detail with checks, approve/reject/request-changes with comment; HOD/registrar ScopeTabs; override dialog with reason; withdraw item after lock.
4. Allocation page dry-run → run → manual assignment of unallocated.
5. Arrears page: per-student list, waive with reason.
6. Mobile: student cart submit; advisor approval; faculty roster.

## 09.13 Deliverables checklist
- [ ] Offerings (CRUD, bulk from curriculum, faculty allocation + workload enforcement, targets, status, rosters), windows with applies-to rules and status Beat, catalog, cart with all checks (prereq/co/anti, credits, seats+waitlist, holds, undertakings), submit with idempotency + fee linkage + advisor workflow, hooks (confirm items, term record, student active), lock/withdraw, overrides, bulk register, elective choice forms + allocation modes, waitlist promotion/expiry, arrears register
- [ ] Ownership link `own_offerings` on students; visibility for registration (self/advisees/department/all)
- [ ] Events/jobs/Beat/workflow; demo seed `--only offerings`
- [ ] Web + mobile; `scripts/verify/09_registration.ps1` passes; UI checklist done; guards green; commit `feat(phase-09): offerings, allocation, registration`
