# SeptronUniverse — Academic Core Design (column level)

This document is the design authority for the higher-education academic core. `Database_Schema.sql` is the naming authority; if the two disagree, fix the SQL first and then this document. Phase prompts copy DDL slices from the SQL, never from here.

## 0. Conventions assumed on every table

Not repeated below:

- `id UUID PK`, `institution_id UUID FK→institutions NOT NULL` (RLS-enforced), `created_at/updated_at TIMESTAMPTZ`, `created_by UUID FK→users`, `is_active BOOL DEFAULT TRUE`, `deleted_at TIMESTAMPTZ NULL`, `deleted_by UUID NULL`, `version INT DEFAULT 1` (optimistic lock on editable masters).
- `college_id UUID FK→colleges` appears where a row belongs to exactly one college; `NULL college_id` on an academic row means **institution-wide** (a university-level regulation, a central exam session).
- Money is `INTEGER` paise (`*_paise`). Percentages `NUMERIC(5,2)`. Grades `VARCHAR(3)`. Status columns are `VARCHAR(30)` backed by Python `str` enums (values listed inline), never PostgreSQL enum types.
- Tenant-scoped UNIQUE constraints always include `institution_id`; partial unique indexes are written as `UNIQUE INDEX name(cols) WHERE …`.
- Timestamps are stored UTC; academic dates (`DATE`) are interpreted in `institutions.timezone`.
- Every table is owned by exactly one module; other modules read through service interfaces or subscribe to domain events (`import-linter` enforces this).

Two reused Orbit tables are **extended** rather than redesigned so the academic core can hook in:

- `fee_invoices` gains `payer_type ('student','applicant','college','alumni','staff','company')`, `source_type VARCHAR(40)` (`course_registration`, `exam_registration`, `reval_request`, `hostel_allocation`, `mess_subscription`, `condonation`, `affiliation_application`, `transcript`, `certificate_request`, `convocation_registration`, `hostel_disciplinary`, `library_fine`, `scholarship_credit`), `source_id UUID` — the **fee-linkage pattern** used everywhere below.
- `departments` gains `college_id`, `faculty_id NULL`, `department_type ('academic','administrative','research_centre')`, `hod_staff_id`.

---

## 1. Academic structure

### 1a. Tables

```
academic_years ( college_id NULL, name "2025-26", start_date, end_date, is_current BOOL, is_locked BOOL,
                 UNIQUE(institution_id, college_id, name),
                 UNIQUE INDEX one_current_year(institution_id, college_id) WHERE is_current )

academic_terms ( college_id NULL, academic_year_id FK, name "Odd Sem 2025-26",
                 term_type (odd|even|summer|trimester|annual), sequence SMALLINT,
                 start_date, end_date, registration_start, registration_end, add_drop_end, last_instruction_date,
                 is_current BOOL, is_locked BOOL,
                 status (planned|registration|in_progress|exam|result_processing|closed),
                 UNIQUE(institution_id, college_id, academic_year_id, term_type, sequence) )

faculties ( college_id, code, name, dean_staff_id FK→staff NULL, UNIQUE(institution_id, college_id, code) )

programs ( college_id, faculty_id NULL, department_id, code "BTECH-CSE", name, degree_name "B.Tech", specialization NULL,
           level (certificate|diploma|ug|pg|pg_diploma|integrated|mphil|phd), mode (regular|part_time|distance|online),
           term_pattern (semester|year|trimester), duration_years NUMERIC(3,1), total_terms SMALLINT, max_duration_years NUMERIC(3,1),
           sanctioned_intake SMALLINT, lateral_intake SMALLINT, approving_body VARCHAR(40) "AICTE|UGC|NCTE|PCI|BCI|NMC|INC|COA|state",
           exam_authority (university|autonomous_college), is_nep_multidisciplinary BOOL, is_open_enrolment BOOL,
           status (draft|active|closed), UNIQUE(institution_id, college_id, code) )

regulations ( college_id NULL, code "R2024", name, effective_from_admission_year SMALLINT, grading_scale_id FK→grading_scales,
              rules JSONB, status (draft|approved|active|superseded), approved_by, approved_at, approval_resolution_id FK→resolutions NULL, locked_at,
              superseded_by_id FK→regulations NULL, UNIQUE(institution_id, college_id, code) )
```

`regulations.rules` JSONB keys (all overridable in `program_regulations.rules_override`):

| Key | Default | Meaning |
|---|---|---|
| `attendance_min_pct` | 75 | eligibility threshold |
| `condonation_floor_pct` | 65 | below this no condonation |
| `condonation_fee_paise` | 0 | fee for condonation |
| `attendance_mode` | `course_wise` | `course_wise` or `aggregate` |
| `ese_pass_min_pct`, `total_pass_min_pct`, `cia_pass_min_pct` | 45, 50, null | pass rules |
| `include_failed_credits_in_sgpa` | true | denominator rule |
| `cgpa_attempt_policy` | `latest` | `latest` or `best` |
| `percentage_formula` | `cgpa*10` | evaluated expression |
| `class_rules` | `[{name:"Distinction",min_cgpa:8.5,first_attempt_only:true},{name:"First",min_cgpa:6.5},{name:"Second",min_cgpa:5.0}]` | first satisfied wins |
| `grace` | `{max_per_course:5,max_courses_per_term:2,max_total_per_term:8,scope:"total"}` | grace caps |
| `double_valuation` | `{enabled:true,discrepancy_pct:15,resolution:"avg_closest_two"}` | `third_final`, `best_two_avg` also allowed |
| `reval` | `{min_delta_to_apply:5,fee_paise,photocopy_fee_paise,challenge_fee_paise,refund_if_changed:true}` | post-result rules |
| `exit_points` | `[{after_term:2,award:"certificate",min_credits:40},{after_term:4,award:"diploma",min_credits:80},{after_term:6,award:"degree",min_credits:120},{after_term:8,award:"honours",min_credits:160}]` | NEP exits |
| `minor_credits`, `honours_credits`, `mooc_max_credits` | 18, 18, 12 | credit caps |
| `max_backlogs_for_promotion` | 4 | detention rule |
| `min_cgpa_for_degree` | 5.0 | degree eligibility |
| `standing_rules` | `[{status:"warning",when:{sgpa_below:5.0}},{status:"probation",when:{cgpa_below:5.0,consecutive_terms:1}},{status:"dismissal",when:{cgpa_below:4.0,consecutive_terms:2}}]` | academic standing |
| `mooc_grade_map` | `{ "90-100":"O", … }` | MOOC score → letter grade |
| `print_grace_note` | true | footnote on grade card |

```
program_regulations ( program_id, regulation_id, rules_override JSONB, total_credits_required NUMERIC(5,1),
                      status (draft|active|closed), UNIQUE(program_id, regulation_id) )

program_structure_terms ( program_regulation_id, term_number SMALLINT, name "Semester 3", min_credits NUMERIC(4,1), max_credits, normal_credits,
                          is_exit_point BOOL, exit_award VARCHAR(30) NULL, UNIQUE(program_regulation_id, term_number) )

courses ( college_id NULL, department_id (owning), regulation_id, code "CS3401", title, short_title,
          course_type (core|program_elective|open_elective|lab|integrated_lab|project|internship|seminar|mooc|audit|
                       mandatory_non_credit|ability_enhancement|skill_enhancement|value_added|minor|honours),
          lecture_hours SMALLINT, tutorial_hours SMALLINT, practical_hours SMALLINT, credits NUMERIC(4,1), contact_hours_per_week SMALLINT,
          assessment_scheme_id FK NULL (default resolved from regulation by course_type), cia_max SMALLINT, ese_max SMALLINT,
          is_credit_bearing BOOL, is_gradable BOOL, min_seats SMALLINT, max_seats SMALLINT,
          syllabus JSONB [{unit,title,topics[],hours}], textbooks JSONB, references JSONB, is_public_catalog BOOL,
          status (draft|approved|active|retired), UNIQUE(institution_id, regulation_id, code) )

course_prerequisites ( course_id, related_course_id, relation (prerequisite|corequisite|antirequisite),
                       min_grade VARCHAR(3) NULL, is_hard BOOL DEFAULT TRUE, UNIQUE(course_id, related_course_id, relation) )

curriculum_courses ( program_regulation_id, term_number, course_id, elective_basket_id NULL, is_mandatory BOOL,
                     credit_bucket VARCHAR(30) "HS|BS|ES|PC|PE|OE|EEC|MC|VAC|AEC|SEC", sequence,
                     UNIQUE(program_regulation_id, term_number, course_id) )

elective_baskets ( program_regulation_id, code, name "Professional Elective III",
                   basket_type (program_elective|open_elective|minor|honours|mooc|vertical),
                   term_number NULL, min_choose SMALLINT, max_choose SMALLINT, credits_required NUMERIC(4,1),
                   allocation_mode (priority_cgpa|fcfs|lottery|manual), UNIQUE(program_regulation_id, code) )

elective_basket_courses ( basket_id, course_id, offering_department_id, UNIQUE(basket_id, course_id) )

batches ( college_id, program_id, program_regulation_id, admission_year SMALLINT, entry_type (regular|lateral),
          code "2024-BTECH-CSE", name, expected_graduation_year, current_term_number SMALLINT,
          status (active|graduating|graduated|closed), UNIQUE(institution_id, college_id, program_id, admission_year, entry_type) )

batch_sections ( batch_id, name "A", capacity SMALLINT, class_advisor_staff_id FK→staff NULL, UNIQUE(batch_id, name) )
```

**Students and enrolments**

```
students ( college_id, user_id FK→users UNIQUE NULL, registration_number VARCHAR(30) (university-level), enrolment_number VARCHAR(30) NULL,
           apaar_id VARCHAR(20) NULL, abc_id VARCHAR(20) NULL, aadhaar_encrypted BYTEA NULL,
           first_name, middle_name, last_name, dob DATE, gender, blood_group,
           category (GEN|EWS|OBC_NCL|OBC_CL|SC|ST), sub_category VARCHAR(40), is_pwd BOOL, pwd_pct SMALLINT, pwd_type,
           is_minority BOOL, minority_type, religion, nationality, is_international BOOL, passport JSONB, visa JSONB, frro JSONB,
           domicile_state, mother_tongue, photo_url, phone, email,
           permanent_address JSONB, current_address JSONB, bank_details JSONB (encrypted), guardian_portal_consent BOOL DEFAULT TRUE,
           admission_quota, admission_mode, admission_date,
           status (provisional|admitted|active|on_break|detained|dropped_out|transferred|exited|graduated|alumni|expelled|deceased),
           UNIQUE(institution_id, registration_number),
           UNIQUE INDEX uq_student_apaar(institution_id, apaar_id) WHERE apaar_id IS NOT NULL )

student_guardians ( student_id, user_id NULL, relation (father|mother|guardian|spouse|other), name, phone, email, occupation, address JSONB,
                    is_primary BOOL, portal_access BOOL, UNIQUE(student_id, relation, name) )

student_documents ( student_id, doc_type VARCHAR(60), file_url, verified_by NULL, verified_at, expires_on NULL, remarks )

student_undertakings ( student_id, undertaking_type (anti_ragging|conduct|hostel_rules|data_consent|photo_consent|custom),
                       template_id FK→document_templates, accepted_at, ip, user_agent, signature_url NULL,
                       UNIQUE(student_id, undertaking_type, template_id) )

student_program_enrollments ( college_id, student_id, program_id, batch_id, program_regulation_id, department_id,
           admission_date, entry_type (regular|lateral|migrated|readmission|exit_reentry), entry_term_number SMALLINT,
           specialization VARCHAR(100), minor_program_id FK→programs NULL, is_honours BOOL, expected_exit_term SMALLINT,
           status (active|break|detained|completed|exited_early|withdrawn|transferred|expelled),
           exit_award VARCHAR(30) NULL, exit_date NULL, credits_earned NUMERIC(6,1), cgpa NUMERIC(4,2),
           academic_standing (good|warning|probation|dismissal) DEFAULT 'good',
           UNIQUE(student_id, program_id, batch_id),
           UNIQUE INDEX one_active_enrollment(student_id) WHERE status IN ('active','break','detained') )

student_term_records ( student_program_enrollment_id, term_id, term_number, section_id FK→batch_sections NULL, roll_number VARCHAR(20),
           status (pending_registration|registered|in_progress|exam_pending|completed|detained|on_break|withdrawn),
           credits_registered, credits_earned, sgpa, cgpa, attendance_pct, result_status,
           UNIQUE(student_program_enrollment_id, term_id) )

student_holds ( student_program_enrollment_id, hold_type (registration|exam|transcript|graduation|hostel|library|all),
                reason TEXT, placed_by, placed_at, released_by NULL, released_at NULL, source_type VARCHAR(40) NULL, source_id UUID NULL,
                INDEX(student_program_enrollment_id) WHERE released_at IS NULL )

course_offerings ( college_id, term_id, course_id, department_id (offering dept), section_code "A" / "ELE-1",
           coordinator_staff_id, max_seats SMALLINT, enrolled_count SMALLINT, waitlist_count SMALLINT,
           delivery_mode (offline|online|hybrid), online_class_link TEXT NULL,
           assessment_scheme_id NULL (override), is_arrear_only BOOL,
           status (planned|open|closed|in_progress|marks_entry|completed|cancelled),
           UNIQUE(institution_id, term_id, course_id, section_code) )

course_offering_faculty ( offering_id, staff_id, role (coordinator|instructor|lab_instructor|teaching_assistant), hours_per_week SMALLINT,
                          UNIQUE(offering_id, staff_id, role) )

course_offering_targets ( offering_id, batch_id, section_id NULL, term_number SMALLINT, UNIQUE(offering_id, batch_id, section_id) )

credit_transfers ( student_program_enrollment_id, term_id, source (swayam|nptel|coursera|other_mooc|abc|other_university|prior_learning|internal_prior),
           source_course_code, source_title, source_institution, credits NUMERIC(4,1), source_grade, source_score_pct,
           equivalent_course_id NULL, elective_basket_id NULL, certificate_url, abc_credit_ref VARCHAR(60),
           status (submitted|verified|approved|rejected|credited), approved_by, approved_at, result_id FK→student_course_results NULL )

number_sequences ( college_id NULL, scope_key "regno:2026:BTECH", pattern "{college_code}{yy}{prog_code}{seq:3}", next_value INT,
           UNIQUE(institution_id, college_id, scope_key) )
```

### 1b. How CBCS / NEP 2020 fits

- **Credits everywhere.** `courses.credits` and L-T-P live on the versioned course row (a course row is owned by a regulation: "CS3401 under R2021" and "CS3401 under R2024" are two rows). Never mutate a course under an `active` regulation — clone it into a new regulation (`POST /regulations/{id}/clone`).
- **Regulation versioning.** A student is pinned to `program_regulation_id` at enrolment. Migration to another regulation is an explicit update with audit + course equivalence via `credit_transfers(source='internal_prior')`.
- **Multiple entry / exit.** `regulations.rules.exit_points` + `program_structure_terms.is_exit_point`. Exit = `student_program_enrollments.status='exited_early', exit_award='diploma'` + a `degrees_awarded` row. Re-entry = new enrolment `entry_type='exit_reentry'`, credits carried by `credit_transfers`.
- **Major / minor / honours.** `minor_program_id` + `elective_baskets.basket_type IN (minor, honours)`; bucket accounting in degree eligibility.
- **MOOC / SWAYAM.** `credit_transfers` → on approval creates a `student_course_results` row (`attempt_type='credit_transfer'`), letter grade from `rules.mooc_grade_map`.
- **ABC / APAAR.** `students.apaar_id`; every published result pushes to `abc_credit_ledger` via Celery.
- **Holds & standing.** `student_holds` block the action named by `hold_type`; `academic_standing` recomputed at every result publish from `rules.standing_rules`.

### 1c. Endpoints

```
GET/POST   /api/v1/programs                              → list/create [programs:view|create] {academics.programs}
PUT        /api/v1/programs/{id}                         → update [programs:update]
GET/POST   /api/v1/regulations                           → list/create [regulations:view|create] {academics.regulations}
POST       /api/v1/regulations/{id}/approve              → draft→approved; locks rules JSON (workflow/resolution optional) [regulations:approve]
POST       /api/v1/regulations/{id}/clone                → new regulation with all courses cloned [regulations:create]
GET/PUT    /api/v1/program-regulations/{id}/structure    → get/replace structure terms + curriculum courses [curriculum:manage]
GET/POST   /api/v1/courses                               → list (filters: regulation, dept, type, text)/create [courses:view|create]
PUT        /api/v1/courses/{id}/prerequisites            → replace prerequisite set [courses:update]
GET/POST   /api/v1/elective-baskets                      → CRUD baskets & courses [curriculum:manage] {academics.elective_baskets}
GET/POST   /api/v1/batches                               → list/create (auto-creates sections) [batches:view|create]
POST       /api/v1/batches/{id}/promote                  → advance term, create term records, apply detention rule [batches:manage]
GET/POST   /api/v1/course-offerings                      → list (term, dept, faculty)/create [offerings:view|create]
POST       /api/v1/course-offerings/bulk-from-curriculum → generate offerings for a term from curriculum [offerings:create]
GET        /api/v1/students/{id}/enrollments             → enrolment history + term records [students:view]
POST       /api/v1/students/{id}/exit                    → NEP exit with award [students:manage] {academics.nep_exit_reentry}
GET/POST   /api/v1/students/{id}/holds                   → list/place hold [students:holds] {students.holds}
POST       /api/v1/student-holds/{id}/release            → release hold [students:holds]
POST       /api/v1/credit-transfers                      → submit MOOC/ABC transfer [credit_transfers:create] {academics.credit_transfer_mooc}
POST       /api/v1/credit-transfers/{id}/approve         → approve → creates result row [credit_transfers:approve]
GET        /api/v1/public/catalog                        → public course catalogue (no auth) {academics.public_catalog}
```

### 1d. Pages
`/admin/academics/programs`, `/admin/academics/regulations/:id` (tabs Rules | Courses | Structure per term | Baskets | Diff vs previous), `/admin/academics/courses`, `/admin/academics/batches/:id` (sections, students, term timeline), `/admin/academics/offerings` (term picker; dept × course grid; faculty assign), `/admin/students/:id` (360°: enrolment, holds, standing), `/student/credit-transfers`, public `/catalog`.

### 1e. Rules
- Σ curriculum credits per programme-regulation = `total_credits_required` (validated on approve).
- Offering creation requires `course.status='active'` and `regulation.status='active'`.
- Batch promotion creates `student_term_records` for `active` enrolments; students with `backlogs > max_backlogs_for_promotion` get `detained`.
- Holds: `registration` blocks registration submit; `exam` blocks exam registration; `transcript` blocks transcript issue; `graduation` blocks degree award; `hostel` blocks hostel allotment; `all` = every gate.

### 1f. Integration
Fees: structures attach to `program_id + term_number + category + quota` (effective-dated). Comms: offering-open, promotion, hold placed/released. Reports: curriculum credit distribution, batch strength, NEP exit stats.

---

## 2. Admissions (higher-ed)

### 2a. Tables

```
admission_cycles ( college_id NULL, academic_year_id, name "UG 2026", level (ug|pg|phd|diploma|lateral|certificate), application_fee_paise,
           opens_at, closes_at, status (draft|open|closed|merit_processing|counselling|completed|archived), form_config JSONB, required_documents JSONB,
           de_reservation_policy JSONB )

admission_cycle_programs ( cycle_id, program_id, college_id, intake SMALLINT, lateral_intake SMALLINT,
           entrance_source (jee|neet|cuet|state_cet|gate|cat|institution_test|merit_only), eligibility_rules JSONB,
           merit_formula JSONB [{field:"entrance_score",weight:60},{field:"qualifying_pct",weight:40}], tie_break JSONB ["entrance_score","dob_asc","submitted_at"],
           UNIQUE(cycle_id, program_id, college_id) )

seat_matrix ( cycle_id, program_id, college_id,
           quota (state|all_india|management|nri|supernumerary|lateral|sports|defence|pwd|kashmiri_migrant|ews_vertical|staff_ward),
           category (GEN|EWS|OBC_NCL|SC|ST|OTHER), seats SMALLINT, filled SMALLINT, UNIQUE(cycle_id, program_id, college_id, quota, category) )

applicants ( cycle_id, application_number VARCHAR(30), user_id NULL, first_name, last_name, dob, gender, category, is_pwd, quota_claimed, nationality, domicile_state,
           contact JSONB, entrance JSONB {exam, roll_no, score, rank, category_rank, year}, qualifying_exams JSONB [{level, board, year, pct, subjects}],
           documents JSONB, merit_score NUMERIC(8,3), status, application_fee_invoice_id, admitted_student_id NULL,
           entry_type (regular|lateral|migration), source (online|offline|counselling_import), remarks,
           UNIQUE(institution_id, application_number) )

applicant_preferences ( applicant_id, program_id, college_id, priority SMALLINT, UNIQUE(applicant_id, priority) )

applicant_document_verifications ( applicant_id, doc_type, file_url, status (pending|verified|rejected|resubmit), verified_by, verified_at, remarks,
           UNIQUE(applicant_id, doc_type) )

merit_lists ( cycle_id, program_id NULL, college_id NULL, name, quota NULL, category NULL, formula_snapshot JSONB,
           status (draft|published|superseded), generated_at, published_at )

merit_list_entries ( merit_list_id, applicant_id, rank, category_rank, score, tie_break JSONB, UNIQUE(merit_list_id, applicant_id) )

counselling_rounds ( cycle_id, round_number, name, choice_filling_start, choice_filling_end, allotment_at, reporting_deadline,
           status (planned|choice_filling|allotted|reporting|closed) )

seat_allotments ( round_id, applicant_id, program_id, college_id, seat_matrix_id, quota, category,
           status (allotted|accepted|float|freeze|upgraded|declined|lapsed|admitted), admission_fee_paise, fee_invoice_id, accepted_at, reported_at,
           UNIQUE(round_id, applicant_id) )

admission_offers ( applicant_id, program_id, college_id, offer_type (provisional|confirmed), valid_until, conditions JSONB, letter_url, status )

enquiries ( source (walk_in|web|phone|referral|event|agent), name, phone, email, program_interest JSONB, stage (new|contacted|counselled|applied|admitted|lost),
           assigned_to, follow_up_on, notes JSONB, applicant_id NULL )

student_transfers ( student_id, transfer_type (migration_in|migration_out|inter_college|program_change|inter_university),
           from_ref JSONB, to_ref JSONB, migration_certificate_no, tc_no, reason, requested_at, approved_by, effective_date,
           status (requested|dues_check|approved|rejected|completed), fee_invoice_id )
```

### 2b. Applicant status machine

```
draft → submitted → fee_paid → under_verification → verified | doc_rejected (→ resubmit → under_verification)
verified → merit_listed → allotted → accepted → provisionally_admitted → admitted   (terminal; student row created; registration number generated)
allotted → declined | lapsed ; verified → waitlisted → allotted ; any → withdrawn | rejected
```
`admitted` is terminal for the applicant; `students.status` continues (`provisional → admitted → active` after first course registration).

### 2c. Endpoints

```
GET/POST   /api/v1/admissions/cycles                              → CRUD cycles [admissions:view|manage] {admissions.cycles}
PUT        /api/v1/admissions/cycles/{id}/seat-matrix             → replace seat matrix [admissions:manage] {admissions.seat_matrix}
POST       /api/v1/public/admissions/{cycle_slug}/apply           → public application (draft) {admissions.online_application}
POST       /api/v1/admissions/applicants/{id}/submit              → validate + application-fee invoice [admissions:create]
GET        /api/v1/admissions/applicants                          → list/filter/search [admissions:view]
POST       /api/v1/admissions/applicants/{id}/documents/{type}/verify → verify/reject doc [admissions:verify] {admissions.document_verification}
POST       /api/v1/admissions/cycles/{id}/merit-lists/generate    → compute merit (job) [admissions:merit] {admissions.merit_lists}
POST       /api/v1/admissions/merit-lists/{id}/publish            → publish + notify [admissions:merit]
POST       /api/v1/admissions/rounds/{id}/run-allotment           → seat allotment (job) [admissions:allot] {admissions.counselling_allotment}
POST       /api/v1/admissions/allotments/{id}/accept              → applicant accepts → admission-fee invoice [admissions:create]
POST       /api/v1/admissions/applicants/{id}/admit               → create student + enrolment + term record; reg number [admissions:approve]
POST       /api/v1/admissions/applicants/import                   → bulk import (state counselling CSV) [admissions:import] {admissions.entrance_import}
GET        /api/v1/admissions/cycles/{id}/seat-status             → filled/vacant by quota×category [admissions:view]
GET/POST   /api/v1/admissions/enquiries                           → CRM [admissions:view|create] {admissions.enquiry_crm}
POST       /api/v1/students/{id}/transfers                        → migration/transfer request [students:manage] {students.transfers_migration}
```

### 2d. Pages
Public `/apply/:cycle` (multi-step, save draft, pay, upload docs, track status). Admin `/admin/admissions/cycles/:id` (tabs Programs & Intake | Seat Matrix | Applicants | Verification queue | Merit lists | Counselling rounds | Seat status | Reports), `/admin/admissions/applicants/:id` (timeline, docs, verification, actions), `/admin/admissions/enquiries` (kanban by stage).

### 2e. Rules
- Merit score = Σ weight × normalised field; ties by `tie_break` list.
- Allotment: iterate merit rank; for each applicant walk preferences; try GEN seat first for everyone (Indian norm), then the claimed category seat in the claimed quota; PwD horizontal reservation; unfilled reserved seats convert in the last round per `de_reservation_policy`.
- Registration number issued only on `admit` (fee paid + docs verified) via `number_sequences` (`UPDATE … RETURNING`).
- Lateral entry: `entry_term_number=3`, batch `entry_type='lateral'` (or merged per policy), `credit_transfers` for exempted credits.
- Open enrolment (`programs.is_open_enrolment`) skips merit/counselling: `verified → admitted` directly (learner role).

### 2f. Integration
Fees: application fee (`payer_type='applicant'`), admission fee; on `admit` create student fee assignment. Comms: status templates. Reports: intake vs filled, category-wise (AISHE / NAAC 2.1.2), source of admission.

---

## 3. Course registration

### 3a. Tables

```
registration_windows ( college_id, term_id, name, window_type (regular|add_drop|late|arrear|summer|audit|minor_honours),
           applies_to JSONB {batch_ids:[],program_ids:[],term_numbers:[]}, starts_at, ends_at, late_fee_paise,
           requires_advisor_approval BOOL, requires_fee_clearance BOOL, max_credits_override NUMERIC(4,1),
           status (scheduled|open|closed) )

course_registrations ( college_id, student_program_enrollment_id, term_id, student_term_record_id, window_id,
           status (draft|submitted|advisor_pending|approved|changes_requested|rejected|locked), total_credits NUMERIC(4,1),
           fee_invoice_id, submitted_at, approved_by, approved_at, locked_at, workflow_instance_id NULL,
           UNIQUE(student_program_enrollment_id, term_id) )

course_registration_items ( registration_id, offering_id, course_id,
           registration_type (regular|arrear|improvement|audit|minor|honours|re_registration|mooc),
           attempt_number SMALLINT, priority SMALLINT NULL,
           status (selected|waitlisted|confirmed|dropped|withdrawn|rejected|substituted),
           is_credit_bearing BOOL, added_at, dropped_at, drop_reason, prerequisite_override_by NULL, UNIQUE(registration_id, offering_id) )

elective_choice_forms ( student_program_enrollment_id, elective_basket_id, term_id, choices JSONB [{course_id,priority}],
           allocated_course_id NULL, allocation_run_id NULL, status (submitted|allocated|unallocated|manual),
           UNIQUE(student_program_enrollment_id, elective_basket_id, term_id) )

elective_allocation_runs ( elective_basket_id, term_id, mode, params JSONB, run_at, run_by, summary JSONB, job_id )

offering_waitlists ( offering_id, student_program_enrollment_id, position SMALLINT, status (waiting|offered|promoted|expired|cancelled), offered_until,
           UNIQUE(offering_id, student_program_enrollment_id) )

student_arrears ( student_program_enrollment_id, course_id, first_failed_term_id, last_attempt_term_id, attempts SMALLINT,
           status (open|registered|cleared|waived), cleared_result_id NULL, UNIQUE(student_program_enrollment_id, course_id) )
```

### 3b. State machine
`draft → submitted → (advisor_pending → approved | changes_requested → draft) → locked` (auto-lock at `add_drop_end`). Items: `selected → confirmed` on approval; `selected → waitlisted` when seats full; `waitlisted → confirmed` on promotion; `confirmed → dropped` within add/drop; `confirmed → withdrawn` after add/drop (grade `W`).

### 3c. Endpoints

```
GET/POST   /api/v1/registration-windows                          → CRUD windows [registration:manage] {registration.core}
GET        /api/v1/registration/me/catalog?term_id=              → eligible offerings for the student (curriculum + arrears + baskets) [registration:self] {registration.self_service}
POST       /api/v1/registration/me/items                         → add offering (prereq/credit/seat/hold checks) [registration:self]
DELETE     /api/v1/registration/me/items/{id}                    → drop [registration:self] {registration.add_drop}
POST       /api/v1/registration/me/submit                        → submit (Idempotency-Key) → advisor approval + fee invoice [registration:self]
POST       /api/v1/registration/{id}/approve | reject            → advisor action [registration:approve] {registration.advisor_approval}
GET        /api/v1/registration/pending?advisor=me               → advisor queue [registration:approve]
POST       /api/v1/elective-baskets/{id}/choices                 → student priorities [registration:self]
POST       /api/v1/elective-baskets/{id}/allocate?term_id=       → run allocation (job) [registration:allocate] {registration.elective_allocation}
POST       /api/v1/course-offerings/{id}/waitlist/promote        → manual promote [registration:manage] {registration.waitlist}
POST       /api/v1/registration/bulk-register                    → admin bulk-register a batch for core courses [registration:manage]
GET        /api/v1/students/{id}/arrears                         → open backlogs [students:view] {registration.arrears}
POST       /api/v1/registration/{id}/override                    → override credits/prereq with reason [registration:override] {registration.overrides}
GET        /api/v1/course-offerings/{id}/roster                  → confirmed students (export) [offerings:view]
```

### 3d. Pages
Student `/student/registration` (cart: curriculum pre-ticked, arrear tab, elective priority drag-list, credit meter, prereq warnings, hold banner, fee summary, submit). Advisor `/faculty/advisees/registrations` (approve with per-item notes). Admin `/admin/registration/windows`, `/admin/registration/allocation`, `/admin/offerings/:id/roster`.

### 3e. Rules
- Credits: `min_credits ≤ Σ confirmed credit-bearing ≤ max_credits` (structure term; window override).
- Prerequisite (hard): a `student_course_results` row with `result_status='pass'` (and `grade ≥ min_grade`); co-requisite must be in the same registration; anti-requisite blocks.
- Registration hold blocks submit (`student_holds.hold_type IN ('registration','all')`).
- Seats: `enrolled_count < max_seats` else waitlist; `SELECT … FOR UPDATE` on the offering row.
- Elective allocation `priority_cgpa`: CGPA desc (tie: registration number); `fcfs`: by `submitted_at`; `lottery`: seeded random; unallocated → manual.
- Arrears only in `arrear` windows (or regular if `rules.allow_arrear_with_regular`); `attempt_number = arrears.attempts + 1`.
- Fee: tuition (term structure) + per-credit arrear fee + late fee; `requires_fee_clearance` blocks submit with prior dues.

### 3f. Integration
Fees (`source_type='course_registration'`), comms (advisor approval, waitlist promotion), attendance rosters = confirmed items, reports (registration status by batch, fill rates).

---

## 4. Timetable & attendance

### 4a. Tables

```
buildings ( college_id, code, name, address, floors SMALLINT )

rooms ( college_id, building_id NULL, code, name, room_type (classroom|lab|seminar|auditorium|exam_hall|smart_class|sports|other),
        capacity SMALLINT, exam_capacity SMALLINT, features JSONB, is_bookable BOOL, UNIQUE(institution_id, college_id, code) )

time_slots ( college_id, slot_group "Default", name "P1", sequence, start_time, end_time, slot_type (lecture|lab|break|lunch),
        UNIQUE(institution_id, college_id, slot_group, name) )

timetables ( college_id, term_id, scope_type (section|batch|department), scope_id, name, version SMALLINT, status (draft|published|archived),
        effective_from, published_by, UNIQUE(term_id, scope_type, scope_id, version) )

timetable_entries ( timetable_id, term_id, offering_id, section_id NULL, day_of_week SMALLINT, time_slot_id, room_id, staff_id,
        session_type (lecture|tutorial|lab|project), week_pattern (all|odd|even), slot_span SMALLINT DEFAULT 1,
        UNIQUE INDEX uq_room(term_id, room_id, day_of_week, time_slot_id) WHERE is_active,
        UNIQUE INDEX uq_staff(term_id, staff_id, day_of_week, time_slot_id) WHERE is_active,
        UNIQUE INDEX uq_section(term_id, section_id, day_of_week, time_slot_id) WHERE is_active )

timetable_substitutions ( timetable_entry_id, on_date, substitute_staff_id, reason, status (requested|approved|rejected), source (manual|leave_auto) )

class_sessions ( college_id, term_id, offering_id, timetable_entry_id NULL, session_date, time_slot_id NULL, start_time, end_time, staff_id,
        session_type, topic, lesson_plan_item_id NULL, online_link NULL,
        status (scheduled|conducted|cancelled|rescheduled), attendance_status (not_taken|taken|finalized), attendance_taken_at, finalized_at,
        UNIQUE(offering_id, session_date, start_time) )

student_class_attendance ( session_id, student_program_enrollment_id, status (present|absent|late|on_duty|leave|medical|exempt),
        source (manual|biometric|qr|app|rfid), marked_by, marked_at, remarks, UNIQUE(session_id, student_program_enrollment_id) )
        -- partitioned by term (RANGE on session_date)

on_duty_requests ( student_program_enrollment_id, from_date, to_date, reason_type (sports|nss|ncc|placement|conference|other), documents JSONB,
        recommended_by, approved_by, status (requested|recommended|approved|rejected), sessions_applied JSONB, workflow_instance_id )

attendance_summaries ( offering_id, student_program_enrollment_id, total_sessions, present, absent, on_duty, late, pct NUMERIC(5,2),
        eligibility (eligible|condonable|not_eligible|condoned), computed_at, UNIQUE(offering_id, student_program_enrollment_id) )

attendance_condonations ( college_id, student_program_enrollment_id, term_id, offering_id NULL, actual_pct,
        reason_type (medical|sports|bereavement|other), documents JSONB, fee_invoice_id, workflow_instance_id,
        status (requested|hod_recommended|approved|rejected), approved_by, approved_at )

term_eligibility ( student_term_record_id, offering_id, attendance_pct, cia_marks, cia_max, is_attendance_ok, is_cia_ok, is_fee_ok, is_hold_ok,
        decision (eligible|detained|condoned|debarred|pending), reason_codes JSONB, decided_by, decided_at, version,
        UNIQUE(student_term_record_id, offering_id, version) )
```

### 4b. Endpoints

```
GET/POST   /api/v1/rooms, /api/v1/time-slots, /api/v1/buildings          → CRUD [timetable:manage] {timetable.rooms}
POST       /api/v1/timetables                                          → create draft for scope [timetable:create] {timetable.core}
POST       /api/v1/timetables/{id}/entries                             → add entry; returns conflicts [timetable:create]
POST       /api/v1/timetables/{id}/auto-generate                       → constraint-based generator (job) [timetable:generate] {timetable.auto_generate}
POST       /api/v1/timetables/{id}/publish                             → publish; generates class_sessions minus holidays [timetable:publish]
GET        /api/v1/timetables/view?faculty_id|section_id|room_id|me    → weekly view [timetable:view]
GET        /api/v1/class-sessions?offering_id&date                     → sessions [attendance:view]
POST       /api/v1/class-sessions/{id}/attendance                      → bulk mark (upsert, Idempotency-Key) [attendance:mark] {attendance.core}
POST       /api/v1/class-sessions/{id}/finalize                        → lock [attendance:mark]; edits need [attendance:edit_finalized]
POST       /api/v1/class-sessions/extra                                → extra/remedial class [attendance:mark]
POST       /api/v1/class-sessions/{id}/qr                              → session QR token (120 s) [attendance:mark] {attendance.qr}
POST       /api/v1/attendance/qr-checkin                               → student scans [attendance:self]
GET        /api/v1/attendance/summary?offering_id | student_id | me    → % per course [attendance:view|self]
POST       /api/v1/on-duty, /on-duty/{id}/approve                      → OD flow [attendance:self|approve] {attendance.on_duty}
POST       /api/v1/condonations, /condonations/{id}/approve            → condonation flow [attendance:condone] {attendance.condonation}
POST       /api/v1/terms/{id}/eligibility/compute                      → compute term_eligibility (job) [exams:eligibility] {attendance.eligibility_detention}
GET        /api/v1/terms/{id}/detention-list?college_id&program_id     → detained students [exams:eligibility]
POST       /api/v1/attendance/devices/{id}/punches                     → biometric/RFID ingest (device token) {attendance.biometric|rfid}
```

### 4c. Pages
`/admin/timetable/:termId` (drag-drop grid; conflict badges; faculty/room views), `/faculty/attendance` (today's sessions → tap-mark grid, QR mode, offline queue), `/student/attendance` (per-course % with shortfall calculator), `/admin/attendance/eligibility` (threshold, condonation queue, detention export), `/admin/attendance/devices`.

### 4d. Rules
- `pct = (present + on_duty + late) / (total_sessions − exempt) × 100` per offering; term % = credit-weighted average (report only).
- Eligibility: `pct ≥ attendance_min_pct` eligible; `condonation_floor_pct ≤ pct < min` condonable (fee + workflow); below floor → detained for that course (or aggregate per `attendance_mode`).
- Finalized sessions are append-only: edits require `attendance:edit_finalized` and write audit diffs.
- Session generation on publish: entry × each term date on `day_of_week`, skipping `holidays`, honouring `week_pattern`.
- Staff leave approved → `timetable_substitutions(source='leave_auto', status='requested')` for affected entries.

### 4e. Integration
HR (leave → substitution), comms (guardian alert after N consecutive absences; threshold warnings at 3 checkpoints), exams (`term_eligibility` gates hall tickets), fees (condonation fee), mobile (offline queue, QR).

---

## 5. Examinations

### 5a. Assessment configuration (per regulation)

```
assessment_schemes ( regulation_id, code "THEORY-40-60", name, applies_to_course_types JSONB, cia_weight SMALLINT 40, ese_weight SMALLINT 60,
        cia_max SMALLINT, ese_max SMALLINT, pass_rules JSONB {ese_min_pct:45,total_min_pct:50,cia_min_pct:null}, is_default BOOL, UNIQUE(regulation_id, code) )

assessment_components ( scheme_id, code "CAT1", name, category (cia|ese_theory|ese_practical|viva|project_review), max_marks SMALLINT,
        scaled_to NUMERIC(5,2), weight_pct NUMERIC(5,2), best_of JSONB {take:2,of:3,group:"CAT"}, sequence, is_mandatory, co_mappable BOOL,
        UNIQUE(scheme_id, code) )

offering_assessments ( offering_id, component_id, name "CAT-1", max_marks, scheduled_on, marks_entry_deadline,
        status (planned|conducted|marks_entry|submitted|verified|locked), question_paper_id NULL, locked_by, locked_at,
        UNIQUE(offering_id, component_id) )

assessment_questions ( offering_assessment_id, question_no "1a", max_marks NUMERIC(5,2), co_id FK→course_outcomes, bloom_level, part "A|B|C",
        UNIQUE(offering_assessment_id, question_no) )

internal_marks ( offering_assessment_id, student_program_enrollment_id, marks NUMERIC(6,2) NULL, is_absent, is_exempt,
        question_wise JSONB {"1a":4,"1b":3.5}, entered_by, entered_at, verified_by, version SMALLINT,
        UNIQUE(offering_assessment_id, student_program_enrollment_id) )

cia_consolidations ( offering_id, student_program_enrollment_id, component_breakdown JSONB, cia_total NUMERIC(6,2), cia_scaled NUMERIC(6,2),
        status (computed|hod_approved|locked|submitted_to_university), locked_by, locked_at, UNIQUE(offering_id, student_program_enrollment_id) )

marks_change_requests ( target_type (internal_mark|script_final|course_result), target_id, old_value JSONB, new_value JSONB, reason, evidence_url,
        requested_by, approved_by, workflow_instance_id, status (requested|hod_approved|coe_approved|applied|rejected), applied_at )

student_projects ( offering_id, title, project_type (mini|major|dissertation|internship_project), guide_staff_id, co_guide_staff_id NULL,
        external_guide JSONB NULL, abstract TEXT, status (proposed|approved|in_progress|submitted|evaluated) )
project_members ( project_id, student_program_enrollment_id, role (lead|member), UNIQUE(project_id, student_program_enrollment_id) )
project_reviews ( project_id, review_no SMALLINT, scheduled_on, panel JSONB, rubric_scores JSONB, marks NUMERIC(6,2), remarks,
        offering_assessment_id NULL, UNIQUE(project_id, review_no) )
```

### 5b. Exam sessions, registration, hall tickets

```
exam_sessions ( college_id NULL, term_id, name "Nov/Dec 2025 ESE", exam_kind (regular|supplementary|arrear|improvement|special|summer|practical),
        coe_staff_id, registration_start, registration_end, late_fee_until,
        fee_rules JSONB {per_course_paise, per_arrear_paise, max_paise, late_fee_paise, practical_paise},
        hall_ticket_release_at, start_date, end_date, valuation_mode (single|double), discrepancy_pct NUMERIC(5,2), grading_scale_id NULL,
        status (draft|registration_open|registration_closed|scheduled|in_progress|valuation|result_processing|results_published|closed), is_locked )

exam_papers ( exam_session_id, course_id, paper_code, paper_type (theory|practical|project_viva|dissertation|online), exam_date, session_slot (FN|AN|EVE),
        start_time, duration_minutes, max_marks, qp_pattern JSONB, quiz_id NULL (online mode),
        status (planned|qp_ready|conducted|scripts_received|valuation|finalized), UNIQUE(exam_session_id, course_id, paper_type) )

exam_registrations ( college_id, exam_session_id, student_program_enrollment_id, status (draft|submitted|fee_pending|confirmed|cancelled|debarred),
        fee_invoice_id, total_fee_paise, hall_ticket_number, hall_ticket_issued_at, hall_ticket_qr_token, hall_ticket_pdf_url, eligibility_snapshot JSONB,
        UNIQUE(exam_session_id, student_program_enrollment_id), UNIQUE(exam_session_id, hall_ticket_number) )

exam_registration_items ( exam_registration_id, exam_paper_id, course_id, attempt_type (regular|arrear|improvement|grade_improvement),
        attempt_number, fee_paise, eligibility (eligible|condoned|detained|debarred|pending),
        status (registered|cancelled|absent|appeared|malpractice|withheld), UNIQUE(exam_registration_id, exam_paper_id) )
```

### 5c. Seating, invigilation, question papers, scripts

```
exam_seating_plans ( exam_session_id, exam_date, session_slot, room_id, capacity_used, layout JSONB, status (draft|published),
        UNIQUE(exam_session_id, exam_date, session_slot, room_id) )
exam_seat_allocations ( seating_plan_id, exam_registration_item_id, seat_number, row_no, col_no, UNIQUE(seating_plan_id, seat_number), UNIQUE(exam_registration_item_id) )

invigilation_duties ( exam_session_id, exam_date, session_slot, room_id, staff_id,
        role (chief_superintendent|hall_superintendent|invigilator|reliever|flying_squad|observer),
        status (assigned|accepted|swap_requested|swapped|absent|completed), remuneration_paise,
        UNIQUE(exam_session_id, exam_date, session_slot, staff_id) )

exam_attendance ( exam_registration_item_id, status (present|absent|late|malpractice), answer_booklet_number, face_match_score NULL, marked_by, marked_at,
        UNIQUE(exam_registration_item_id) )

question_paper_assignments ( exam_paper_id, setter_staff_id NULL, external_setter JSONB, set_label "A", blueprint_id NULL,
        status (invited|accepted|submitted|scrutinised|approved|selected|printed|rejected),
        file_key_encrypted TEXT, submitted_at, scrutiny_by, scrutiny_remarks, remuneration_paise, UNIQUE(exam_paper_id, set_label) )
question_paper_print_log ( exam_paper_id, set_label, printed_by, printed_at, copies SMALLINT, watermark_text, ip )

answer_script_bundles ( exam_paper_id, room_id NULL, bundle_number, script_count, status (created|coded|dispatched|received|in_valuation|valuated|decoded|archived),
        coded_by, coded_at, custody_holder_staff_id, custody_location, UNIQUE(exam_paper_id, bundle_number) )

answer_scripts ( exam_registration_item_id, bundle_id, dummy_number VARCHAR(20), barcode, pages SMALLINT, scan_url NULL,
        status (received|coded|in_valuation|valuated|discrepancy|third_valuation|finalized|moderated|decoded|revaluation|archived|destroyed),
        UNIQUE(exam_registration_item_id), UNIQUE(bundle_id, dummy_number) )
  -- dummy_number ↔ registration mapping is readable only by [exams:decode]; evaluators use a projection WITHOUT exam_registration_item_id.

script_custody_log ( bundle_id, action (created|dispatched|received|handed_over|returned|archived|destroyed), from_staff_id, to_staff_id, at, location, remarks )
```

### 5d. Valuation and moderation

```
valuation_assignments ( exam_paper_id, bundle_id, evaluator_staff_id NULL, external_evaluator JSONB, evaluator_type (internal|external), valuation_round SMALLINT,
        status (assigned|accepted|in_progress|submitted|verified), assigned_at, due_at, submitted_at, remuneration_paise, UNIQUE(bundle_id, valuation_round) )

script_valuations ( answer_script_id, valuation_round, evaluator_id, marks NUMERIC(6,2), question_wise JSONB, annotations_url, submitted_at, is_locked,
        UNIQUE(answer_script_id, valuation_round) )

script_final_marks ( answer_script_id, marks_v1, marks_v2, marks_v3, discrepancy NUMERIC(6,2), rule_applied VARCHAR(40), computed_marks NUMERIC(6,2),
        moderated_marks NUMERIC(6,2) NULL, moderation_action_id NULL, final_marks NUMERIC(6,2),
        status (pending|resolved|needs_third|moderated|final), UNIQUE(answer_script_id) )

moderation_actions ( exam_paper_id, action_type (scale_up|scale_down|add_flat|grace|normalize|cap), rule JSONB, justification, proposed_by, approved_by (COE),
        affected_count, status (proposed|approved|applied|reverted) )
```

### 5e. Results, grading, publication, credentials

```
grading_scales ( regulation_id NULL, name, scale_type (absolute|relative),
        ranges JSONB [{grade:"O",min_pct:90,max_pct:100,grade_point:10,is_fail:false}, …],
        relative_config JSONB {method:"mean_sd", bands:[{grade:"O",min_z:1.5},…], min_class_size:30},
        special_grades JSONB {absent:"AB",withheld:"WH",malpractice:"MP",withdrawn:"W",incomplete:"I",audit:"AU"},
        UNIQUE(institution_id, name) )

result_processing_runs ( exam_session_id, scope JSONB {college_ids,program_ids}, run_type (provisional|final|revaluation|supplementary_merge|correction|legacy_import),
        status (queued|computing|computed|verified|approved|published|rolled_back|failed), triggered_by, verified_by, approved_by, approval_resolution_id NULL,
        published_at, stats JSONB {students,courses,pass_pct,withheld}, config_snapshot JSONB, checksum VARCHAR(64), error_log JSONB, job_id )

student_course_results ( college_id, student_program_enrollment_id, term_id, course_id, offering_id NULL, exam_session_id NULL, exam_registration_item_id NULL,
        attempt_number SMALLINT, attempt_type (regular|arrear|improvement|credit_transfer|audit|re_registration|legacy),
        credits NUMERIC(4,1), cia_marks, cia_max, ese_marks, ese_max, grace_marks NUMERIC(4,1) DEFAULT 0, grace_reason, moderation_delta,
        total_marks, total_max, percentage NUMERIC(5,2), letter_grade VARCHAR(3), grade_point NUMERIC(3,1),
        result_status (pass|fail|absent|withheld|malpractice|detained|incomplete|withdrawn|exempted|audit_pass|audit_fail),
        counts_toward_cgpa BOOL, is_current BOOL, version SMALLINT, supersedes_id NULL, run_id FK→result_processing_runs,
        status (draft|computed|verified|approved|published|superseded), published_at, hash VARCHAR(64),
        UNIQUE(student_program_enrollment_id, course_id, attempt_number, version) )
  -- TRIGGER trg_results_immutable: reject UPDATE when OLD.status='published' unless only is_current/status→'superseded' change.

student_term_results ( student_term_record_id, run_id, credits_registered, credits_earned, sgpa NUMERIC(4,2), cgpa NUMERIC(4,2), cumulative_credits,
        backlog_count SMALLINT, result_class VARCHAR(30), status (computed|approved|published|withheld|superseded), version, is_current, published_at,
        UNIQUE(student_term_record_id, version) )

result_publications ( run_id, exam_session_id, published_by, published_at, audience (student|college|public), notify JSONB, withheld_list JSONB )

grade_cards ( student_term_result_id, document_number, pdf_url, qr_token, template_id, generated_at, version, UNIQUE(institution_id, document_number) )

transcripts ( student_program_enrollment_id, transcript_type (provisional|consolidated|final|duplicate|migration), document_number, pdf_url,
        verification_token, fee_invoice_id, workflow_instance_id, requested_at, issued_at, issued_by,
        status (requested|fee_pending|generated|issued|cancelled) )

reval_requests ( exam_session_id, exam_registration_item_id, answer_script_id, request_type (retotaling|photocopy|revaluation|challenge),
        fee_invoice_id, status (submitted|fee_paid|assigned|evaluated|marks_changed|no_change|rejected|closed), original_marks, revised_marks, delta,
        evaluator_assignment_id NULL, decided_by, decided_at, refund_due BOOL, UNIQUE(exam_registration_item_id, request_type) )

malpractice_cases ( exam_session_id, exam_registration_item_id, case_number, reported_by, reported_at,
        category (copying|impersonation|device|material|misconduct|tampering|other), evidence JSONB, invigilator_report TEXT, student_statement TEXT,
        committee_id FK→committees NULL, hearing_at,
        punishment (none|warning|cancel_paper|cancel_session|debar_terms|expel), debar_until_term_id NULL, decision_text, decided_by, decided_at,
        status (reported|under_inquiry|hearing_scheduled|decided|appealed|appeal_decided|closed), UNIQUE(institution_id, case_number) )

legacy_result_imports ( batch_id, term_number, file_url, mapping JSONB, validation_report JSONB, status (uploaded|validated|applied|rolled_back), run_id, job_id )

degree_eligibility_checks ( student_program_enrollment_id, checked_at, credits_earned, credits_required, bucket_breakdown JSONB, backlog_count, cgpa, min_cgpa_ok,
        duration_ok, dues_cleared, holds_clear, mandatory_noncredit_ok, is_eligible, reasons JSONB, run_id NULL )

convocations ( name, held_on, venue, registration_deadline, fee_paise, status (planned|registration_open|closed|completed) )
convocation_registrations ( convocation_id, student_program_enrollment_id, mode (in_person|absentia), fee_invoice_id, gown_size, status,
        UNIQUE(convocation_id, student_program_enrollment_id) )

degrees_awarded ( student_program_enrollment_id, award_type (certificate|diploma|degree|honours|pg_diploma|phd), degree_name, specialization, result_class, cgpa,
        date_of_award, certificate_number, serial_no, convocation_id NULL, pdf_url, esign_ref NULL,
        status (recommended|council_approved|issued|cancelled|reissued), approved_by, approval_resolution_id NULL, digital_credential_id NULL,
        UNIQUE(institution_id, certificate_number) )

digital_credentials ( entity_type (grade_card|transcript|degree|provisional_certificate), entity_id, channel (digilocker|nad|abc|internal),
        payload_hash, payload JSONB, pushed_at, ack_ref, status (pending|pushed|acknowledged|failed|revoked), response JSONB, UNIQUE(entity_type, entity_id, channel) )

abc_credit_ledger ( student_id, apaar_id, student_course_result_id UNIQUE, term_id, course_code, course_title, credits, letter_grade, grade_point, academic_year,
        status (pending|pushed|acknowledged|failed|revoked), push_batch_id, response JSONB )
```

### 5f. Status machines

**Component marks** (`offering_assessments.status`): `planned → conducted → marks_entry → submitted (faculty) → verified (HOD) → locked (exam cell)`. Post-lock changes only via `marks_change_requests`.

**CIA consolidation**: `computed → hod_approved → locked → submitted_to_university` (affiliated colleges only).

**Answer script**: `received → coded → in_valuation → valuated (V1[,V2]) → [discrepancy → third_valuation] → finalized → [moderated] → decoded → archived → destroyed`.

**Result lifecycle (per run and per row)**:
```
draft ──compute──▶ computed ──verify (exam cell checklist)──▶ verified ──approve (COE)──▶ approved ──publish──▶ published
published ──(reval | grace | correction | malpractice decision)──▶ NEW version row (supersedes_id) draft → … → published ; old row status=superseded, is_current=false
approved/published ──withhold (dues, malpractice pending)──▶ result_status=withheld (row stays; grade card shows WH)
computed/verified ──rollback──▶ run.status=rolled_back (only before publish)
```
`hash = sha256(student, course, attempt, marks, grade, version)` printed in QR; run `checksum` = hash of all row hashes.

### 5g. Endpoints (grouped)

```
# configuration
GET/POST   /api/v1/assessment-schemes                              → per regulation [exams:configure] {assessment.internal_marks}
GET/PUT    /api/v1/grading-scales/{id}                              → absolute/relative scale [exams:configure]
# internal assessment
GET        /api/v1/course-offerings/{id}/assessments                → components instantiated [marks:view]
POST       /api/v1/offering-assessments/{id}/questions              → CO-tagged question map [marks:enter] {assessment.question_wise_co}
POST       /api/v1/offering-assessments/{id}/marks                  → bulk upsert (question-wise optional, Idempotency-Key) [marks:enter]
POST       /api/v1/offering-assessments/{id}/submit | verify | lock → workflow [marks:enter|marks:verify|marks:lock] {assessment.marks_workflow}
POST       /api/v1/course-offerings/{id}/cia/consolidate            → best-of & scaling → cia_consolidations [marks:verify]
POST       /api/v1/marks-change-requests, /{id}/approve             → post-lock correction with audit [marks:correct] {assessment.marks_change_requests}
GET/POST   /api/v1/course-offerings/{id}/projects, /projects/{id}/reviews → projects & reviews [projects:manage] {assessment.projects}
# exam session
GET/POST   /api/v1/exam-sessions                                    → CRUD [exams:manage] {exams.sessions}
POST       /api/v1/exam-sessions/{id}/papers/bulk                   → papers from offerings + arrears [exams:manage]
POST       /api/v1/exam-sessions/{id}/date-sheet/publish            → clash check → publish [exams:manage] {exams.clash_detection}
POST       /api/v1/exam-sessions/{id}/open-registration             → status change + notify [exams:manage]
GET        /api/v1/exam-registration/me?session_id=                 → auto-built registration (regular + arrears) with fee preview [exams:self]
POST       /api/v1/exam-registration/me/submit                      → creates fee invoice (Idempotency-Key) [exams:self] {exams.registration_fee}
POST       /api/v1/exam-sessions/{id}/eligibility/apply             → snapshot term_eligibility into items [exams:eligibility] {exams.eligibility_snapshot}
POST       /api/v1/exam-sessions/{id}/hall-tickets/generate         → bulk PDFs w/ photo + signed QR (documents queue) [exams:hall_tickets] {exams.hall_tickets}
GET        /api/v1/hall-tickets/verify/{token}                      → public QR verification
POST       /api/v1/exam-sessions/{id}/seating/generate              → allocate by room capacity, mixed-course adjacency [exams:seating] {exams.seating}
POST       /api/v1/exam-sessions/{id}/invigilation/auto-assign      → duty roster by availability/leave/load [exams:invigilation] {exams.invigilation}
POST       /api/v1/invigilation-duties/{id}/swap-request | accept   → swaps [exams:invigilation]
POST       /api/v1/exam-papers/{id}/attendance                      → hall attendance + booklet numbers (+ face match) [exams:conduct]
# QP & scripts
POST       /api/v1/exam-papers/{id}/qp-assignments                  → invite setters [exams:qp] {exams.qp_management}
POST       /api/v1/qp-assignments/{id}/upload | scrutinise | select → encrypted upload; selection [exams:qp]
POST       /api/v1/qp-assignments/{id}/print                        → watermarked print + log [exams:qp] {exams.qp_watermark_print_log}
POST       /api/v1/exam-papers/{id}/bundles ; POST /bundles/{id}/code → create bundles; assign dummy numbers [exams:code] {exams.coding_dummy}
POST       /api/v1/bundles/{id}/custody                             → custody hand-over log [exams:code] {exams.script_custody}
# valuation
POST       /api/v1/exam-papers/{id}/valuation/assign                → bundles → evaluators per round [exams:valuation_assign]
GET        /api/v1/valuation/me/bundles                             → evaluator worklist (dummy numbers only) [exams:evaluate]
POST       /api/v1/answer-scripts/{id}/valuations/{round}           → submit marks (question-wise) [exams:evaluate]
POST       /api/v1/exam-papers/{id}/valuation/reconcile             → discrepancy, flag third valuation [exams:valuation_assign] {exams.double_valuation}
POST       /api/v1/moderation-actions, /{id}/approve, /{id}/apply   → moderation workflow [exams:moderate] {exams.moderation}
POST       /api/v1/exam-papers/{id}/decode                          → dummy→student mapping, writes ese_marks (audited) [exams:decode]
# results
POST       /api/v1/exam-sessions/{id}/results/compute               → run (job): grades, SGPA/CGPA, class, standing [results:compute] {results.processing}
GET        /api/v1/result-runs/{id}/review                          → anomalies: missing CIA, absent w/ marks, grace applied [results:verify]
POST       /api/v1/result-runs/{id}/verify | approve | publish      → workflow (approve = COE only) [results:verify|approve|publish]
GET        /api/v1/results/me?term_id=                              → student result (published only) [results:self] {results.publication_portal}
GET        /api/v1/public/results/lookup?reg_no&dob                 → public lookup when audience=public
GET        /api/v1/students/{id}/grade-card/{term_id}.pdf           → grade card [results:view] {results.grade_cards}
POST       /api/v1/students/{id}/transcripts                        → request transcript (fee, workflow) [results:transcript] {results.transcripts}
POST       /api/v1/reval-requests, /{id}/assign, /{id}/decide       → revaluation lifecycle [exams:self|exams:reval] {results.revaluation}
POST       /api/v1/malpractice-cases, /{id}/decide, /{id}/appeal    → malpractice [exams:malpractice] {results.malpractice}
POST       /api/v1/legacy-results/import | validate | apply          → legacy import [results:compute] {results.legacy_import}
POST       /api/v1/degree-eligibility/run?batch_id=                 → eligibility check (job) [degrees:view] {degrees.eligibility}
POST       /api/v1/degrees/award-batch, /degrees/{id}/issue         → award + certificate PDF + DigiLocker push [degrees:award|issue] {degrees.certificates}
GET        /api/v1/verify/{token}                                   → public credential verification {degrees.verification_portal}
```

### 5h. Pages
`/admin/exams/sessions/:id` (tabs Papers & Timetable | Registrations | Eligibility | Hall Tickets | Seating | Invigilation | QP | Coding | Valuation | Moderation | Results Run | Reval | Malpractice | Custody), `/faculty/marks/:offeringId` (component grid, question-wise mode, CO heatmap preview, submit), `/hod/marks-verification`, `/evaluator/bundles/:id` (dummy list, per-question entry, progress), `/coe/results/runs/:id` (anomaly review, pass % by course, approve/publish), `/student/exams` (register, hall ticket, results, reval, transcript), `/admin/degrees` (eligibility, convocation, award batch), `/verify/:token` public.

### 5i. Rules and formulas
- `cia_total` = per component: apply `best_of`, then `Σ(component_marks / max_marks × scaled_to)`; scale to `cia_max`.
- `ese_marks` = `script_final_marks.final_marks` scaled to `ese_max`; practical ESE separate component.
- Pass: `ese ≥ ese_min_pct% × ese_max AND total ≥ total_min_pct% × total_max (AND cia ≥ cia_min if set)`. Failing ESE alone → `fail`, letter `U`, GP 0.
- Absolute grade: lookup `ranges` by `percentage`; relative: `z = (x − μ)/σ` over paper cohort, `min_class_size` else absolute.
- **SGPA** = `Σ(Ci × GPi) / Σ Ci` over credit-bearing courses registered in the term (`include_failed_credits_in_sgpa` controls denominator).
- **CGPA** = `Σ(Ci × GPi) / Σ Ci` over all courses using the attempt chosen by `cgpa_attempt_policy`; credit-transfer rows included if `counts_toward_cgpa`.
- Percentage = eval(`percentage_formula`). Class: first rule in `class_rules` satisfied; `first_attempt_only` requires zero arrear-type attempts.
- Double valuation: `discrepancy = |V1 − V2|`; if `> discrepancy_pct% × max_marks` → third valuation; resolution `avg_closest_two` (default): mean of the two closest of {V1,V2,V3}; else `(V1+V2)/2`.
- Grace: only when shortfall ≤ `max_per_course` and per-term caps hold; recorded in `grace_marks` with `grace_reason`; footnoted if `print_grace_note`.
- Revaluation: `delta = revised − original`; applied only if `|delta| ≥ min_delta_to_apply`, else `no_change`; refund per `refund_if_changed`; creates a new result version.
- Exam clash: a student registered for two papers on the same `exam_date + session_slot` blocks `date-sheet/publish` (report lists conflicts).
- Hall ticket gate: registration `confirmed` AND every item `eligibility ∈ (eligible, condoned)` AND no active debar AND no `exam|all` hold AND (optional setting) no dues flags.
- Withheld: `result_status='withheld'` when malpractice pending or fee due; auto-release on closure/payment.
- Degree eligibility: credits per bucket ≥ required, `backlog_count = 0`, `cgpa ≥ min_cgpa_for_degree`, duration ≤ `max_duration_years`, mandatory non-credit done, no `graduation|all` hold, `dues_cleared` (incl. hostel caution deposit).
- Result isolation: every result row carries `college_id`; college users are scope-filtered; central sessions have `college_id NULL` but runs publish per `scope.college_ids`.

### 5j. Integration
Fees: exam registration (`source_type='exam_registration'`), reval/photocopy/transcript/convocation fees, evaluator/invigilator remuneration → payroll adjustments. Comms: hall ticket ready, result published (masked SMS + push), reval outcome. Documents: hall ticket / grade card / degree templates. Reports: `exam.pass_pct_by_course`, `exam.result_analysis_by_batch`, `exam.arrear_summary`, `exam.evaluator_turnaround`, `exam.malpractice_register`. DigiLocker/NAD/ABC: outbox → Celery `push_digital_credential` with retry.

---

## 6. OBE (Outcome-Based Education)

### 6a. Tables

```
outcome_definitions ( scope_type (institution|program), scope_id, outcome_type (PEO|PO|PSO), code "PO1", statement TEXT, framework VARCHAR(30) "NBA_ENGG_2024",
        sequence, UNIQUE(scope_type, scope_id, outcome_type, code) )
peo_po_mappings ( peo_id, po_id, level SMALLINT CHECK 1..3, UNIQUE(peo_id, po_id) )
course_outcomes ( course_id, code "CO1", statement, bloom_level (remember|understand|apply|analyze|evaluate|create), sequence, UNIQUE(course_id, code) )
co_po_mappings ( course_outcome_id, outcome_id, level SMALLINT CHECK 1..3, justification, UNIQUE(course_outcome_id, outcome_id) )
attainment_configs ( scope_type (regulation|program), scope_id, target_student_pct 60, target_marks_pct 60,
        levels JSONB [{level:1,min_pct:40},{level:2,min_pct:50},{level:3,min_pct:60}], direct_weight 80, indirect_weight 20,
        cia_weight_in_direct 30, ese_weight_in_direct 70, po_target_level NUMERIC(3,2) 2.0, co_target_level 2.0 )
attainment_runs ( scope_type (offering|program_batch), scope_id, config_snapshot JSONB, status (queued|computed|failed), run_at, job_id )
co_attainments ( offering_id, course_outcome_id, run_id, students_assessed, students_above_target, direct_pct, direct_level NUMERIC(3,2),
        cia_level, ese_level, indirect_level NULL, final_level, target_level, gap, computed_at, UNIQUE(offering_id, course_outcome_id, run_id) )
po_attainments ( program_id, batch_id, outcome_id, run_id, direct_level, indirect_level, final_level, target_level, gap, contributing_courses SMALLINT, computed_at,
        UNIQUE(program_id, batch_id, outcome_id, run_id) )
cqi_actions ( scope_type (offering|course|program), scope_id, outcome_id NULL, gap NUMERIC(3,2), action_text, owner_staff_id, due_on,
        status (planned|in_progress|done|verified), evidence_url, reviewed_by )
```
Indirect attainment reuses `feedback_surveys` (§8): course-exit survey questions tagged `co_id`; programme-exit/alumni/employer surveys tagged `outcome_id`.

### 6b. Formulas
- Per question-CO: student CO marks = Σ marks of questions tagged to the CO; CO max = Σ max of those questions.
- Per assessment CO attainment: `pct_students = count(student_co_marks ≥ target_marks_pct × co_max) / assessed` → level via `levels` bands.
- Direct CO level = `cia_weight × avg(CIA assessment levels) + ese_weight × ESE level` (ESE from question-wise valuation; if absent, ESE total apportioned by CO weights declared in `exam_papers.qp_pattern`).
- Final CO = `direct_weight × direct + indirect_weight × indirect` (course-exit survey mean mapped to 1–3).
- Course→PO contribution = `Σ_CO (CO_final × map_level) / Σ_CO map_level` for each mapped PO.
- Programme PO direct (per batch) = mean of course→PO contributions across the batch's curriculum courses mapping to the PO; PO final = `direct_weight × direct + indirect_weight × indirect`; `gap = target − final` → CQI action required when gap > 0.

### 6c. Endpoints
```
GET/PUT  /api/v1/programs/{id}/outcomes                → PEO/PO/PSO editor (import NBA defaults from pack) [obe:manage] {obe.definitions}
GET/PUT  /api/v1/courses/{id}/outcomes                 → COs [obe:manage]
PUT      /api/v1/courses/{id}/co-po-matrix             → matrix upsert [obe:manage]
GET/PUT  /api/v1/attainment-configs                    → targets/weights [obe:configure]
POST     /api/v1/course-offerings/{id}/attainment/compute → CO run (job) [obe:compute] {obe.attainment}
GET      /api/v1/course-offerings/{id}/attainment      → CO table + per-assessment breakdown [obe:view]
POST     /api/v1/programs/{id}/batches/{bid}/attainment/compute → PO run [obe:compute]
GET      /api/v1/programs/{id}/attainment?batch_id     → PO/PSO dashboard [obe:view]
GET/POST /api/v1/cqi-actions                           → CQI register [obe:manage] {obe.cqi}
GET      /api/v1/obe/export/nba-sar?program_id&batch_id → Criterion 3 tables (XLSX) [obe:export] {obe.nba_export}
```
Pages: `/admin/obe/programs/:id` (PO/PSO/PEO, PEO-PO map), `/faculty/courses/:id/outcomes` (CO editor, CO-PO matrix with justifications), `/faculty/offerings/:id/attainment` (heatmap), `/admin/obe/program-attainment` (radar per batch, gap list, CQI actions).

---

## 7. Faculty academic, HR extensions, research

```
faculty_profiles ( staff_id UNIQUE, department_id, college_id, aicte_faculty_id, orcid, scopus_id, google_scholar_id, vidwan_id, highest_qualification, is_phd, phd_year,
        is_phd_guide, guide_recognition_no, max_scholars SMALLINT, experience_teaching_months, experience_industry_months, experience_research_months,
        specializations JSONB, api_score NUMERIC(6,2), api_updated_at, joining_date, cadre (professor|associate|assistant|lecturer|adjunct|visiting|guest),
        employment_type (regular|contract|guest|visiting), hourly_rate_paise NULL )
faculty_qualifications ( staff_id, degree, discipline, university, year, is_highest )
faculty_workloads ( staff_id, term_id, theory_hours, tutorial_hours, lab_hours, project_hours, admin_hours, research_hours, total_hours, max_allowed_hours,
        status (draft|hod_approved|dean_approved), UNIQUE(staff_id, term_id) )
course_allocation_proposals ( department_id, term_id, proposals JSONB [{offering_id,staff_id,role}], status (draft|submitted|dean_approved|applied), submitted_by, approved_by )
lesson_plans ( offering_id, unit_no, topic, planned_date, planned_hours, delivery_method, co_id, resources JSONB, actual_date NULL, actual_session_id NULL,
        status (planned|delivered|deferred), sequence )
course_files ( offering_id UNIQUE, checklist JSONB [{item:"Syllabus",done:true,url}], completion_pct, audited_by, audited_at, remarks )

job_postings ( title, department_id, cadre, vacancies SMALLINT, reservation JSONB (roster points), qualifications JSONB, opens_at, closes_at, status (draft|open|closed|filled|cancelled) )
job_applications ( posting_id, applicant JSONB, documents JSONB, api_score NUMERIC(6,2), screening_score, status (applied|screened|shortlisted|interviewed|selected|offered|joined|rejected) )
interview_panels ( posting_id, scheduled_at, members JSONB, venue ) ; interview_scores ( panel_id, application_id, scores JSONB, remarks )
appraisals ( staff_id, academic_year_id, self_assessment JSONB (PBAS), reviewer_staff_id, reviewer_score, final_score, workflow_instance_id, status (draft|submitted|reviewed|approved) )
cas_applications ( staff_id, from_cadre, to_cadre, api_breakdown JSONB, eligibility_date, workflow_instance_id, status (draft|submitted|screened|interviewed|approved|rejected) )
loans_advances ( staff_id, type (festival|vehicle|housing|salary_advance), principal_paise, emi_paise, start_month, balance_paise, status )

publications ( staff_id, pub_type (journal|conference|book|chapter|patent_pub), title, venue, year, doi, issn_isbn, indexing (sci|scie|scopus|wos|ugc_care|other|none),
        impact_factor NUMERIC(6,3), authors JSONB, author_position SMALLINT, citations SMALLINT, evidence_url, is_verified, verified_by )
patents ( staff_id, title, application_no, country, filed_on, published_on, granted_on, status (filed|published|granted|commercialised), co_inventors JSONB )
research_projects ( pi_staff_id, co_pi JSONB, title, funding_agency, scheme, sanctioned_paise, received_paise, start_on, end_on,
        status (applied|sanctioned|ongoing|completed|closed), utilisation JSONB, budget_heads JSONB, ethics_approval_id NULL )
consultancies ( staff_id, client, title, amount_paise, institution_share_paise, start_on, end_on, status )
faculty_developments ( staff_id, event_type (fdp|workshop|conference|certification|mooc|industry_training), title, organiser, from_on, to_on,
        role (attended|organised|resource_person), hours, certificate_url )
faculty_awards ( staff_id, title, agency, year, level (institution|state|national|international) )
ethics_committees ( type (iec|iaec|ibsc), members JSONB ) ; ethics_approvals ( committee_id, project_title, pi_staff_id, submitted_on, decision (approved|revise|rejected), approval_no, valid_to )
research_incentives ( type (seed_grant|publication_incentive|travel_grant|patent_filing_support), staff_id, amount_paise, justification, workflow_instance_id, status )
mous ( partner, partner_type (industry|university|government|ngo), country, type (academic|research|placement|exchange), signed_on, valid_to, activities JSONB, document_url )
collaborations ( mou_id NULL, title, type (joint_research|exchange|joint_degree|internship), participants JSONB, outcomes JSONB )
incubation_startups ( name, founders JSONB, sector, stage (idea|prototype|incubated|funded|graduated), funding_paise, mentor_staff_id, registered_on, status )
```
Rules: workload = Σ `course_offering_faculty.hours_per_week` + admin hours vs cadre cap (settings). Guest faculty remuneration = hours × `hourly_rate_paise` → payroll line. Recruitment roster validated against `reservation` points. Feeds NAAC 2.4/3.x/6.3, NIRF FRU/RP, NBA Criterion 5.

Endpoints: `GET/PUT /api/v1/faculty/{id}/profile`, `GET /api/v1/faculty/{id}/workload?term_id`, `POST /api/v1/departments/{id}/course-allocation`, `GET/POST /api/v1/course-offerings/{id}/lesson-plan`, `GET/PUT /api/v1/course-offerings/{id}/course-file`, `GET/POST /api/v1/faculty/{id}/publications|patents|projects|consultancies|fdp|awards`, `POST /api/v1/faculty/{id}/api-score/compute`, `GET/POST /api/v1/recruitment/postings`, `/postings/{id}/applications`, `/panels`, `GET/POST /api/v1/appraisals`, `GET/POST /api/v1/cas-applications`, `GET/POST /api/v1/research/ethics-approvals`, `/research/incentives`, `/research/mous`, `/research/startups`.
Pages: `/faculty/profile`, `/faculty/research`, `/hod/course-allocation/:termId`, `/hod/workload`, `/admin/hr/recruitment/:postingId`, `/admin/hr/appraisals`, `/admin/research/*`.

---

## 8. Student support

```
mentor_assignments ( mentor_staff_id, student_program_enrollment_id, term_id, from_on, to_on, status, UNIQUE(student_program_enrollment_id, term_id) )
mentoring_slots ( mentor_staff_id, starts_at, ends_at, capacity SMALLINT ) ; mentoring_bookings ( slot_id, student_program_enrollment_id, status )
mentoring_sessions ( mentor_assignment_id, held_on, mode, notes TEXT, concerns JSONB [academic,personal,financial,health], action_items JSONB, follow_up_on, is_confidential BOOL )
counselling_referrals ( student_program_enrollment_id, referred_by, counsellor_staff_id, reason, status (referred|scheduled|in_progress|closed), is_confidential )
risk_flags ( student_program_enrollment_id, score NUMERIC(5,2), factors JSONB {attendance, cia, dues, standing, hostel}, level (low|medium|high), computed_at, acknowledged_by )
scholarships ( name, provider (central_govt|state_govt|institution|private|alumni), amount_paise, amount_type (fixed|fee_pct|fee_full),
        eligibility_rules JSONB {categories,min_cgpa,max_income_paise,programs}, academic_year_id, applications_open, applications_close )
scholarship_applications ( scholarship_id, student_program_enrollment_id, income_paise, documents JSONB,
        status (applied|verified|recommended|sanctioned|disbursed|rejected), sanctioned_paise, disbursement_mode (fee_credit|bank_transfer|external_portal),
        external_ref "NSP-…", fee_discount_id NULL, workflow_instance_id )
grievances ( ticket_number, raised_by_user_id NULL, student_program_enrollment_id NULL,
        category (academic|exam|fee|hostel|harassment|ragging|discrimination|infrastructure|other), is_anonymous, description, attachments JSONB, priority,
        committee (grievance_cell|icc|anti_ragging|sc_st_cell|obc_cell), assigned_to, sla_due_at,
        status (open|acknowledged|under_review|resolved|closed|escalated|reopened), resolution TEXT, resolved_at, satisfaction_rating )
grievance_updates ( grievance_id, by_user_id, note, is_internal, at )
disciplinary_cases ( subject_type (student|staff), subject_id, case_number, category, description, evidence JSONB, committee_id FK→committees, hearing_at,
        sanctions JSONB [{type:"warning|fine|suspension|expulsion|community_service", …}], fee_invoice_id NULL, appeal_status, decided_by, decided_at,
        status (reported|inquiry|hearing|decided|appealed|closed) )
feedback_surveys ( survey_type (course|faculty|institution|course_exit|program_exit|alumni|employer|hostel|parent|sss), term_id, title,
        questions JSONB [{id,text,scale,co_id?,outcome_id?}], audience_rules JSONB, is_anonymous, opens_at, closes_at, status )
feedback_responses ( survey_id, respondent_hash VARCHAR(64), target_type (offering|staff|institution|program|hostel), target_id, answers JSONB, submitted_at,
        UNIQUE(survey_id, respondent_hash, target_id) )
clubs ( name, club_type (technical|cultural|sports|social|professional_chapter|nss|ncc|extension), faculty_advisor_id, description, budget_paise )
club_members ( club_id, student_program_enrollment_id, role (member|secretary|president|treasurer), from_on, to_on )
club_events ( club_id, title, held_on, venue, participants_count, budget_paise, report_url, images JSONB, event_id FK→events NULL )
activity_hours ( student_program_enrollment_id, activity_type (nss|ncc|community_service|club|sports), hours NUMERIC(5,1), on_date, verified_by, credits_course_id NULL )
student_achievements ( student_program_enrollment_id, category (sports|cultural|technical|research|hackathon), title, level, position, held_on, evidence_url, verified_by )
```
Endpoints: `GET/POST /api/v1/mentoring/assignments`, `/assignments/bulk-assign`, `/mentoring/slots`, `/mentoring/sessions`, `GET/POST /api/v1/scholarships`, `/scholarships/{id}/apply`, `/scholarship-applications/{id}/sanction` (creates fee discount), `POST /api/v1/grievances` (public + auth), `/grievances/{id}/update|resolve|escalate`, `GET/POST /api/v1/discipline/cases`, `/cases/{id}/decide|appeal`, `GET/POST /api/v1/surveys`, `/surveys/{id}/respond`, `/surveys/{id}/analytics?target_id`, `GET/POST /api/v1/clubs`, `/activity-hours`, `GET /api/v1/risk-flags?level=high`.
Pages: `/faculty/mentees`, `/student/mentor`, `/admin/scholarships`, `/admin/grievances` (kanban + SLA), `/admin/discipline`, `/admin/surveys/:id/results`, `/student/clubs`, `/admin/students/risk`.

---

## 9. Hostel, mess & staff accommodation

```
hostels ( college_id, name, hostel_type (boys|girls|coed|pg|international|staff), warden_staff_id, address, capacity, mess_id NULL )
hostel_blocks ( hostel_id, name, floors SMALLINT )
hostel_rooms ( block_id, room_number, floor, capacity SMALLINT, room_type (single|double|triple|dorm), has_ac, amenities JSONB,
        status (available|full|maintenance|blocked), UNIQUE(block_id, room_number) )
hostel_beds ( room_id, bed_label, status (vacant|allocated|blocked), UNIQUE(room_id, bed_label) )
hostel_fee_plans ( hostel_id, room_type, academic_year_id, fee_per_term_paise, caution_deposit_paise, mess_advance_paise )
hostel_applications ( student_program_enrollment_id, academic_year_id, hostel_preference JSONB, room_type_pref, distance_km, priority_score,
        status (applied|waitlisted|allotted|declined|cancelled) )
hostel_allocations ( student_program_enrollment_id, bed_id, hostel_id, academic_year_id, from_on, to_on NULL,
        status (allotted|checked_in|vacated|transferred|evicted), fee_invoice_id, caution_deposit_invoice_id, check_in_at, check_out_at, room_condition JSONB,
        UNIQUE INDEX one_active_bed(bed_id) WHERE status IN ('allotted','checked_in'),
        UNIQUE INDEX one_active_student(student_program_enrollment_id) WHERE status IN ('allotted','checked_in') )
room_change_requests ( allocation_id, requested_bed_id NULL, reason, status (requested|approved|rejected|applied) )
hostel_roll_calls ( hostel_id, on_date, taken_by, taken_at ) ; hostel_roll_call_entries ( roll_call_id, allocation_id, status (present|absent|on_leave), UNIQUE(roll_call_id, allocation_id) )
mess_plans ( hostel_id NULL, name, diet (veg|nonveg|jain|special), monthly_fee_paise, menu JSONB )
mess_subscriptions ( student_program_enrollment_id, mess_plan_id, from_on, to_on, status, fee_invoice_id )
mess_attendance ( mess_subscription_id, on_date, meal (breakfast|lunch|snacks|dinner), status (taken|skipped|rebate), source )
mess_bills ( mess_subscription_id, month, days_billed, rebate_days, amount_paise, fee_invoice_id )
hostel_visitors ( hostel_id, student_program_enrollment_id, visitor_name, relation, phone, id_proof_type, id_proof_no, in_at, out_at, approved_by )
hostel_leaves ( student_program_enrollment_id, leave_type (out_pass|day_leave|home_leave|medical), from_at, to_at, destination, reason,
        guardian_consent (pending|otp_verified|not_required), status (requested|approved|rejected|out|returned|late_return|absconding),
        approved_by, actual_out_at, actual_return_at, late_minutes, qr_token )
hostel_complaints ( hostel_id, room_id, student_program_enrollment_id, category, description, service_request_id FK→service_requests NULL, status )
hostel_disciplinary_records ( student_program_enrollment_id, hostel_id, incident_on, description, action (warning|fine|suspension|eviction), fine_paise, fee_invoice_id, decided_by )
staff_quarters ( college_id, unit_code, type, rent_paise, status (vacant|allocated|maintenance) ) ; staff_quarter_allocations ( quarter_id, staff_id, from_on, to_on, rent_deduction BOOL )
```
Endpoints: `GET/POST /api/v1/hostels`, `/hostels/{id}/blocks|rooms|beds` (bulk), `POST /api/v1/hostel-applications`, `/hostel-applications/allot` (auto by priority + preference), `POST /api/v1/hostel-allocations/{id}/check-in|vacate|transfer`, `GET /api/v1/hostels/{id}/occupancy`, `POST /api/v1/hostel-leaves`, `/hostel-leaves/{id}/approve|mark-out|mark-return` (gate QR), `POST /api/v1/hostel-roll-calls`, `POST /api/v1/hostel-visitors`, `GET/POST /api/v1/mess-plans`, `/mess-subscriptions`, `/mess-bills/generate`, `POST /api/v1/hostel-complaints`, `GET/POST /api/v1/staff-quarters`.
Pages: `/admin/hostel/occupancy` (block/floor map), `/warden/leaves` (approve; gate scan), `/warden/roll-call`, `/student/hostel`. Rules: guardian OTP for `home_leave` if minor/policy; late return → auto disciplinary note; vacate blocks `dues_cleared` until caution deposit settled; hostel hold blocks allotment.

---

## 10. Placement, internships, training & alumni

```
companies ( name, sector, website, hq_city, tier (dream|super_dream|core|mass), contacts JSONB, is_blacklisted, notes, recruiter_user_ids JSONB )
placement_drives ( company_id, title, job_role, job_type (full_time|internship|intern_ppo|part_time), ctc_min_paise, ctc_max_paise, stipend_paise, locations JSONB, bond JSONB,
        eligibility_rules JSONB {min_cgpa,max_active_backlogs,max_history_backlogs,programs,batches,min_10th_pct,min_12th_pct,max_gap_years,allowed_if_already_placed:false},
        registration_deadline, drive_on, mode (on_campus|off_campus|virtual|pooled), status (draft|open|closed|in_progress|completed|cancelled), jd_url, owner_staff_id )
drive_rounds ( drive_id, round_no, name, round_type (pre_placement_talk|aptitude|coding|gd|technical|hr|final), scheduled_at, venue, UNIQUE(drive_id, round_no) )
drive_applications ( drive_id, student_program_enrollment_id, eligibility_snapshot JSONB, is_eligible, override_by NULL,
        status (applied|ineligible|shortlisted|in_process|rejected|selected|offer_accepted|offer_declined|withdrawn|absent), resume_url, UNIQUE(drive_id, student_program_enrollment_id) )
drive_round_results ( application_id, round_id, status (cleared|not_cleared|absent|pending), score, remarks, UNIQUE(application_id, round_id) )
placement_offers ( application_id, company_id, role, ctc_paise, ctc_breakup JSONB, location, offer_letter_url, offered_on, joining_on,
        status (offered|accepted|declined|revoked|joined|not_joined), is_ppo, UNIQUE(application_id) )
placement_policies ( batch_id NULL, program_id NULL, max_offers SMALLINT 1, dream_ctc_threshold_paise, allow_upgrade_if_dream BOOL, opt_out_allowed BOOL )
student_placement_profiles ( student_program_enrollment_id UNIQUE, resume_url, resume_json JSONB (builder), skills JSONB, is_opted_out, opt_out_reason,
        higher_studies JSONB {exam,score,institution}, placement_status (unplaced|placed|multiple|opted_out), is_blacklisted, blacklist_reason )
internships ( student_program_enrollment_id, company_id NULL, company_name, role, from_on, to_on, stipend_paise, mentor, evaluation JSONB, certificate_url,
        noc_document_id NULL, credits_course_id NULL )
training_programs ( type (aptitude|soft_skills|technical|mock_interview), title, trainer, from_on, to_on, batches JSONB ) ; training_attendance ( program_id, student_program_enrollment_id, sessions_attended, score )
company_feedback ( drive_id, ratings JSONB, remarks )
alumni_profiles ( student_id UNIQUE, user_id NULL, graduation_year, program_id, current_company, designation, city, country, linkedin_url, email, phone,
        is_verified, willing_to_mentor, willing_to_recruit, consent_contact BOOL, last_updated_by_alumni_at )
alumni_employment_history ( alumni_id, company, designation, from_on, to_on, is_current )
alumni_events ( title, held_on, venue, type (meet|webinar|reunion|mentorship), registrations_count, event_id FK→events NULL )
alumni_jobs ( posted_by_alumni_id, title, company, location, description, apply_url, expires_on )
fundraising_campaigns ( title, goal_paise, raised_paise, from_on, to_on, purpose, status )
donations ( donor_type (alumni|corporate|individual), donor_ref JSONB, campaign_id NULL, amount_paise, on_date, receipt_no, is_80g, pan_encrypted, mode )
```
Rules: eligibility evaluated live from `student_term_results.cgpa` (current), `student_arrears`, 10th/12th from applicant record; one-offer policy with dream upgrade; `% placed = placed / (eligible − opted_out)` feeds NIRF GO / NAAC 5.2. Recruiter users see only their drives and consented profile fields.
Endpoints: `GET/POST /api/v1/companies`, `/placement/drives`, `POST /drives/{id}/publish` (eligible list + notify), `/drives/{id}/apply`, `/drives/{id}/rounds/{r}/results` (bulk), `POST /placement-offers`, `/offers/{id}/accept|decline`, `GET /placement/stats?batch_id`, `GET/POST /internships`, `/training-programs`, `GET/PUT /alumni/me`, `GET /alumni/directory`, `POST /alumni/events`, `/alumni/jobs`, `/fundraising/campaigns`, `/donations` (+ 80G receipt PDF), recruiter portal `/api/v1/recruiter/*`.
Pages: `/admin/placement/drives/:id` (funnel), `/student/placement`, `/recruiter/portal`, `/alumni/portal`, `/admin/placement/reports`, `/admin/alumni/fundraising`.

---

## 11. Accreditation & compliance registry

```
accreditation_frameworks ( code "NAAC_2024|NBA_UG_ENGG|NIRF_ENGG|AISHE|AICTE_APPROVAL|UGC_12B", name, version, is_active )
framework_criteria ( framework_id, code "2.6.3", parent_id NULL, title, description, metric_type (quantitative|qualitative|qn_ql), max_score NUMERIC(6,2),
        period_type (academic_year|calendar_year|five_year), metric_key VARCHAR(80) NULL, UNIQUE(framework_id, code) )
metric_definitions ( key "students.pass_pct_final_year", name, description, unit, source_module, computation_key (registry function), params_schema JSONB, is_derived, depends_on JSONB )
metric_values ( college_id NULL, metric_key, period_label "2025-26", program_id NULL, value NUMERIC(14,4), numerator NUMERIC(14,4), denominator NUMERIC(14,4),
        breakdown JSONB, computed_at, source (auto|manual|override), overridden_by, override_reason, verified_by, verified_at,
        UNIQUE(institution_id, college_id, metric_key, period_label, program_id) )
evidence_documents ( framework_criterion_id NULL, metric_key NULL, period_label, title, doc_type, file_url, uploaded_by, verified_by, tags JSONB )
accreditation_cycles ( framework_id, college_id NULL, program_id NULL (NBA), name "NAAC Cycle 3", period_from, period_to, submission_due_on, coordinator_staff_id,
        status (planning|data_collection|drafting|internal_review|submitted|peer_visit|result), score NUMERIC(5,2), grade VARCHAR(5) )
criterion_responses ( cycle_id, framework_criterion_id, narrative TEXT, metric_value_ids JSONB, evidence_ids JSONB, owner_staff_id, status (draft|in_review|approved|final), reviewed_by,
        UNIQUE(cycle_id, framework_criterion_id) )
compliance_submissions ( framework_id, period_label, submission_type (aqar|nirf_data|aishe|aicte_approval|ugc_annual), payload JSONB, file_url, status (draft|generated|submitted|acknowledged), submitted_on, ack_ref )
audit_registers ( audit_type (academic|administrative|green|energy|gender|financial_statutory|ag), period_label, auditor, report_url, findings JSONB, status )
```
Derived metrics (computation_key → source): enrolment by category/gender/state (AISHE; NAAC 2.1.1/2.1.2), FSR (2.2.1 / NIRF), pass % final year (2.6.3), dropout %, placed % / higher studies % (5.2.1/5.2.2), qualifying-exam clearers (5.2.3), scholarship beneficiaries (5.1.1), sports/cultural awards (5.3.1), SSS (2.7.1), median salary (NIRF GMS), GPH/GPHD, full-time & PhD faculty % (2.4.x), FQE/FRU, publications per teacher, Scopus/WoS counts, books/chapters (3.3.x), grants (3.1.1), consultancy (3.5.x), FDP (6.3.x), patents (3.4.x), MoUs/collaborations (3.7.x), CBCS/elective %, new/value-added courses (1.2.x/1.3.x), internships % (1.3.4), CO/PO attainment (NBA 3), infra/library/IT spend (4.x), gender/PwD ratios, grievance SLA (7.x), events organised, affiliation counts. Each `metric_values` row keeps numerator/denominator/breakdown for peer-team traceability.
Endpoints: `GET /api/v1/accreditation/frameworks`, `POST /accreditation/metrics/compute?period&framework` (job), `GET /accreditation/metrics?period&framework`, `PUT /accreditation/metrics/{key}/override`, `POST /accreditation/evidence`, `GET/POST /accreditation/cycles`, `PUT /accreditation/cycles/{id}/criteria/{code}`, `GET /accreditation/cycles/{id}/export?format=naac_ssr|nba_sar|aqar`, `POST /accreditation/submissions/generate?type=nirf|aishe`, `GET/POST /accreditation/audits`.
Pages: `/iqac/dashboard`, `/iqac/metrics` (grid with drill-down), `/iqac/cycles/:id/criteria/:code`, `/iqac/evidence`, `/iqac/audits`.

---

## 12. Affiliation (university tenant)

```
colleges ( … foundation cols …, college_type (constituent|affiliated|autonomous|campus|deemed_unit|study_centre), affiliation_number, affiliated_since, principal_staff_id,
        exam_centre_code, is_exam_centre, aishe_code, aicte_pid )
affiliation_applications ( college_id, academic_year_id, application_type (new|renewal|extension|intake_increase|program_addition|program_closure|autonomy),
        programs JSONB, documents JSONB, fee_invoice_id, inspection_committee JSONB, inspection_on, inspection_report_url, deficiencies JSONB, workflow_instance_id,
        status (draft|submitted|fee_paid|scrutiny|inspection_scheduled|inspected|compliance_pending|approved|conditional|rejected|withdrawn), decided_by, order_no, order_url )
affiliation_program_approvals ( college_id, program_id, academic_year_id, sanctioned_intake, lateral_intake, approval_status (provisional|permanent|conditional|withdrawn),
        order_no, valid_from, valid_to, conditions JSONB, UNIQUE(college_id, program_id, academic_year_id) )
affiliation_fee_schedules ( academic_year_id, fee_type (affiliation|continuation|inspection|intake_increase|exam_processing_per_student|recognition), amount_paise, per_unit (flat|per_program|per_student) )
college_data_submissions ( college_id, term_id, exam_session_id NULL,
        submission_type (student_registrations|course_registrations|cia_marks|attendance_eligibility|practical_marks|exam_registrations|internal_faculty_list),
        status (draft|submitted|verified|returned|accepted|locked), record_count, file_url NULL, submitted_by, submitted_at, verified_by, remarks,
        UNIQUE(college_id, term_id, submission_type) )
exam_centres ( exam_session_id, college_id, centre_code, chief_superintendent_staff_id, capacity, assigned_colleges JSONB )
```
Model: affiliated colleges have `programs.exam_authority='university'` → `exam_sessions.college_id IS NULL` (central); `exam_registrations`, `answer_scripts`, `student_course_results` carry `college_id`. Colleges submit CIA via `cia_consolidations.status='submitted_to_university'` aggregated in `college_data_submissions`; the university values centrally (scripts coded by centre) and publishes per college. Autonomous colleges run everything with `college_id` set; the university consumes `degrees_awarded` recommendations. Fees: `fee_invoices.payer_type='college'`.
Endpoints: `GET/POST /api/v1/affiliation/applications`, `/applications/{id}/submit|schedule-inspection|record-inspection|decide`, `GET/PUT /affiliation/colleges/{id}/program-approvals`, `POST /affiliation/submissions` (college), `/submissions/{id}/verify|return|accept` (university), `GET /affiliation/colleges/{id}/dashboard`, `GET /affiliation/exam-sessions/{id}/college-status`.
Pages: `/university/affiliation/colleges`, `/university/affiliation/applications/:id`, `/college/submissions/:termId`, `/university/exams/sessions/:id/colleges`.

---

## 13. LMS-lite

```
course_modules ( offering_id, title, sequence, is_published )
course_contents ( module_id, content_type (file|video|link|text|scorm|embed), title, body TEXT, file_url, duration_minutes, release_at, co_ids JSONB, sequence, view_count )
content_views ( content_id, student_program_enrollment_id, first_viewed_at, last_viewed_at, progress_pct, UNIQUE(content_id, student_program_enrollment_id) )
lms_assignments ( offering_id, offering_assessment_id NULL, title, instructions, attachments JSONB, due_at, max_marks, allow_late BOOL, late_penalty_pct_per_day, max_file_mb,
        rubric JSONB, co_ids JSONB, is_group BOOL, similarity_check BOOL, status (draft|published|closed) )
assignment_submissions ( assignment_id, student_program_enrollment_id, files JSONB, text_answer, submitted_at, is_late, attempt SMALLINT, marks NUMERIC(6,2), rubric_scores JSONB,
        feedback, graded_by, graded_at, similarity_pct, status (submitted|graded|returned|resubmit), UNIQUE(assignment_id, student_program_enrollment_id, attempt) )
quizzes ( offering_id, question_paper_id FK (question bank, Orbit reuse), offering_assessment_id NULL, title, starts_at, ends_at, duration_minutes, attempts_allowed, shuffle_questions,
        show_result (immediate|after_close|never), proctoring JSONB {webcam_snapshots, tab_switch_limit, fullscreen}, status )
quiz_attempts ( quiz_id, student_program_enrollment_id, attempt_no, started_at, submitted_at, answers JSONB, auto_score, manual_score, total_score, proctor_events JSONB,
        status (in_progress|submitted|auto_submitted|graded), UNIQUE(quiz_id, student_program_enrollment_id, attempt_no) )
course_announcements ( offering_id, title, body, posted_by, pinned, posted_at )
discussion_threads ( offering_id, title, created_by, is_locked, is_pinned ) ; discussion_posts ( thread_id, parent_post_id NULL, author_user_id, body, attachments, is_answer, upvotes )
```
Key rule: when `offering_assessment_id` is set on an assignment/quiz/project review, grading writes into `internal_marks` (scaled to component `max_marks`) — LMS work flows into CIA and OBE with no re-entry. Endpoints: `GET/POST /api/v1/course-offerings/{id}/modules|contents`, `POST /contents/{id}/view`, `GET/POST /course-offerings/{id}/assignments`, `POST /assignments/{id}/submit`, `/assignments/{id}/grade` (bulk), `POST /course-offerings/{id}/quizzes`, `/quizzes/{id}/start|answer|submit`, `/quizzes/{id}/push-to-marks`, `GET/POST /course-offerings/{id}/announcements|threads`. Pages: `/faculty/offerings/:id/lms`, `/student/courses/:offeringId`.

---

## 14. PhD & research-scholar lifecycle (UGC PhD Regulations 2022)

```
research_scholars ( student_program_enrollment_id UNIQUE, guide_staff_id, co_guide_staff_id NULL, external_co_guide JSONB NULL, mode (full_time|part_time),
        fellowship_type (jrf|srf|institution|project|none), registration_date, coursework_status (pending|in_progress|completed|exempted), coursework_exemption_reason,
        max_duration_end, status (admitted|coursework|registered|synopsis_submitted|thesis_submitted|under_evaluation|viva_scheduled|awarded|discontinued) )
doctoral_committees ( scholar_id UNIQUE, members JSONB [{staff_id|external, role}], constituted_on )
dc_meetings ( scholar_id, meeting_no SMALLINT, held_on, minutes TEXT, recommendations JSONB, status (scheduled|held|approved), UNIQUE(scholar_id, meeting_no) )
scholar_progress_reports ( scholar_id, period_label "2026-H1", report_url, guide_remarks, dc_rating (satisfactory|unsatisfactory), status (submitted|guide_reviewed|dc_reviewed) )
scholar_fellowships ( scholar_id, type, monthly_paise, from_on, to_on, contingency_paise, hra_applicable BOOL ) ; fellowship_disbursements ( fellowship_id, month, amount_paise, status, payroll_ref )
scholar_requests ( scholar_id, request_type (extension|change_of_guide|mode_change|leave|coursework_exemption), details JSONB, workflow_instance_id, status )
thesis_submissions ( scholar_id, stage (pre_synopsis|synopsis|thesis|revised_thesis), file_url, submitted_at, similarity_pct NUMERIC(5,2), plagiarism_report_url,
        ai_generated_pct NULL, status (submitted|plagiarism_checked|dc_approved|rejected) )
thesis_examiners ( thesis_id, examiner JSONB {name, affiliation, email}, is_external BOOL, state, country, invited_at, accepted_at, report_url, report_received_at,
        recommendation (accept|minor|major|reject), remuneration_paise, status (proposed|approved|invited|accepted|declined|report_received) )
viva_voce ( thesis_id UNIQUE, scheduled_at, venue_or_link, panel JSONB, result (recommended|re_viva|not_recommended), report_url, held_at )
etd_uploads ( thesis_id, repository (shodhganga|institutional), handle, uploaded_at, status )
```
Rules (pack-configurable): guide load ≤ `faculty_profiles.max_scholars`; coursework must be `completed|exempted` before `registered`; progress report every 6 months; `similarity_pct < 10` (excluding references/quotes) before DC approval of thesis; examiner panel ≥ 2 external (one outside state / country per policy); viva only after all reports `accept|minor`; `awarded` → `degrees_awarded(award_type='phd')` + ETD upload job + fellowship stop.
Endpoints: `GET/POST /api/v1/phd/scholars`, `/scholars/{id}/guide`, `/scholars/{id}/dc`, `/scholars/{id}/dc-meetings`, `/scholars/{id}/progress-reports`, `/scholars/{id}/fellowship`, `/scholars/{id}/requests`, `/scholars/{id}/thesis` (upload → plagiarism adapter), `/thesis/{id}/examiners`, `/thesis/{id}/viva`, `/thesis/{id}/award`, `/thesis/{id}/etd`.
Pages: `/scholar/portal` (progress, thesis, fellowship, requests), `/faculty/scholars` (guide view), `/admin/research/phd` (registrar/dean view, DC constitution, examiners, viva, awards).

---

## 15. Governance: committees, meetings, legal & e-file

```
committees ( name, type (bos|academic_council|executive_council|senate|finance|iqac|anti_ragging|icc|grievance|research_board|purchase|discipline|custom),
        department_id NULL, chair_staff_id, secretary_staff_id, constituted_on, valid_to, quorum_rule JSONB )
committee_members ( committee_id, member_type (staff|external|student), staff_id NULL, external JSONB, role, from_on, to_on )
meetings ( committee_id, meeting_no, held_on, venue_or_link, agenda JSONB [{item, doc_url}], quorum_met BOOL, attendance JSONB, minutes_url, minutes_text, status (scheduled|held|minutes_draft|minutes_approved) )
resolutions ( meeting_id, number "AC/2026/14", subject, text, action_owner_staff_id, due_on, status (passed|deferred|rejected|implemented), linked_entity JSONB {type,id} )
action_taken_reports ( resolution_id, report_text, submitted_by, submitted_at, status )
legal_cases ( case_no, court, case_type, parties JSONB, counsel, filed_on, next_hearing, status (open|hearing|judgement|appeal|closed), documents JSONB, outcome )
rti_requests ( applicant JSONB, received_on, due_on, subject, pio_staff_id, fee_paise, response_url, status (received|assigned|responded|appealed|closed), first_appeal JSONB )
audit_paras ( audit_register_id, para_no, description, amount_paise NULL, owner_staff_id, reply_text, status (open|replied|settled|dropped) )
efiles ( file_no, subject, category, created_by, current_holder_user_id, priority, status (open|in_movement|closed), closed_at )
efile_movements ( efile_id, from_user_id, to_user_id, noting TEXT, attachments JSONB, moved_at, action (forward|return|approve|reject) )
policies ( title, category, version, approved_resolution_id NULL, effective_from, file_url, status (draft|approved|superseded) )
```
Resolutions may be cited by `regulations.approval_resolution_id`, `result_processing_runs.approval_resolution_id`, `degrees_awarded.approval_resolution_id`, `policies.approved_resolution_id`. Endpoints: `GET/POST /api/v1/governance/committees`, `/committees/{id}/members`, `/meetings`, `/meetings/{id}/minutes|approve`, `/resolutions`, `/resolutions/{id}/atr`, `GET/POST /api/v1/legal/cases`, `/rti/requests`, `/audit-paras`, `/efiles`, `/efiles/{id}/move`, `/policies`. Pages: `/admin/governance/committees/:id`, `/admin/governance/meetings/:id`, `/admin/legal`, `/admin/rti`, `/admin/efiles`, `/admin/policies`.

---

## 16. Events, facilities, safety & campus services

```
events ( event_type (conference|seminar|workshop|fdp|guest_lecture|cultural|sports|outreach|exhibition|alumni|convocation), title, organiser_department_id, organiser_staff_id,
        from_on, to_on, venue_room_id NULL, venue_text, budget_paise, sponsor JSONB, participants_count, external_participants_count, report_url, images JSONB,
        naac_criterion VARCHAR(10) NULL, status (proposed|approved|scheduled|completed|cancelled), workflow_instance_id )
event_registrations ( event_id, person_type (student|staff|external), person_id NULL, external JSONB, fee_invoice_id NULL, attended BOOL, certificate_document_id NULL )
room_bookings ( room_id, requested_by, purpose, from_at, to_at, expected_headcount, workflow_instance_id, status (requested|approved|rejected|cancelled) )
equipment_bookings ( asset_id FK→assets, requested_by, from_at, to_at, purpose, status )
service_requests ( category (electrical|plumbing|it|network|furniture|cleaning|civil|security|other), location_room_id NULL, location_text, description, attachments JSONB,
        priority, requested_by, assigned_to, vendor_id NULL, sla_due_at, status (open|assigned|in_progress|resolved|closed|reopened), resolution, rating )
amc_contracts ( vendor_id, asset_category, from_on, to_on, value_paise, sla JSONB, status )
visitor_passes ( visitor JSONB, host_user_id, purpose, valid_from, valid_to, gate_in_at, gate_out_at, vehicle_no, id_proof, status )
emergency_alerts ( raised_by_user_id, location JSONB, alert_type (sos|fire|medical|security), status (raised|acknowledged|resolved), responders JSONB )
health_visits ( person_type, person_id, visited_at, complaint, diagnosis, treatment, referred_to, is_confidential ) ; insurance_policies ( person_type, person_id, provider, policy_no, valid_to )
counselling_appointments ( counsellor_staff_id, slot_at, person_type, person_id, status, is_confidential )
sports_teams ( sport, level (institution|inter_college|university|state|national), coach_staff_id ) ; sports_events ( title, level, from_on, to_on, venue ) ; sports_participation ( event_id, student_program_enrollment_id, team_id NULL, result, evidence_url )
lost_found_items ( description, found_at, location, status (reported|claimed|disposed), claimant )
canteens ( name, location, vendor_id ) ; wallet_accounts ( person_type, person_id, balance_paise ) ; wallet_transactions ( account_id, type (topup|debit|refund), amount_paise, merchant, ref )
```
Endpoints: `GET/POST /api/v1/events`, `/events/{id}/register|attendance|certificates`, `/room-bookings`, `/equipment-bookings`, `/service-requests`, `/service-requests/{id}/assign|resolve`, `/visitor-passes`, `POST /emergency/sos`, `/health/visits`, `/counselling/appointments`, `/sports/*`, `/lost-found`, `/wallet/*`. Pages: `/admin/events`, `/admin/facilities/bookings`, `/admin/service-desk` (kanban + SLA), `/admin/security/visitors`, `/admin/health`, `/admin/sports`.

---

## 17. RBAC summary for the academic core

Roles and permission modules are listed in `docs/Roles_and_Permissions.md`; the data-scope layer (`user_roles.scope_type/scope_id`) and the row-level visibility resolver are specified in `docs/Authorization_and_Visibility.md`. Every endpoint above cites `[module:action]` and, where gated, `{feature.key}` from `docs/Feature_Flags.md`.

## 18. Build order (academic core within the 44-phase plan)

03 institution/terms → 05 programmes/regulations/courses → 06 HR → 07 students/enrolments/holds → 08 admissions → 09 offerings/registration → 10 timetable → 11 attendance/eligibility → 12 fees → 13 internal assessment + OBE definitions + LMS + projects → 14 exam administration → 15 valuation/results → 16 post-result → 17 OBE attainment → 18 degrees/convocation/credentials → 20 hostel → 27 support → 28 placement → 29 alumni → 30 research → 31 PhD → 32 accreditation → 33 governance → 34 affiliation. Each phase = one Alembic migration + models + repos + services + routers + pages + mobile screens + seed + API/UI verification.

## 19. Design risks and how the model handles them

1. **Regulation drift** — regulation ownership + `active` lock + clone; students pinned via `program_regulation_id`.
2. **Retroactive grade changes without trail** — versioned `student_course_results`, immutability trigger, `marks_change_requests`/`reval_requests` via workflow + audit.
3. **Result tampering** — per-row `hash`, per-run `checksum`, signed QR → `/verify/{token}`, `digital_credentials` log, hash-chained audit.
4. **Dummy-number leakage** — evaluator projection omits identity; `exams:decode` is a distinct role; decode audited.
5. **Multi-college isolation** — `college_id` on registrations/scripts/results/runs, role scope layer, `BaseRepository` filters, RLS backstop.
6. **Eligibility disputes at hall-ticket time** — versioned `term_eligibility` snapshots with reason codes copied into registrations; condonation is a workflow with fee.
7. **SGPA/CGPA variations** — all knobs in `regulations.rules`; computation is a pure function over `config_snapshot`.
8. **Backlog drift** — `student_arrears` maintained transactionally at publish; registration reads it.
9. **ABC/APAAR mismatches** — `abc_credit_ledger` 1:1 with published rows; revisions revoke + re-push.
10. **CIA/LMS/OBE double entry** — single write path into `internal_marks`; attainment reads question-wise marks.
11. **Race conditions** — `SELECT … FOR UPDATE`, `number_sequences`, unique constraints, `Idempotency-Key`.
12. **Affiliated-college data chaos** — `college_data_submissions` lock state gates result runs.
13. **Holds bypassed** — every gate (registration, exam registration, hall ticket, transcript, degree, hostel) checks `student_holds` through one `HoldService.assert_clear(enrollment, gate)`.
