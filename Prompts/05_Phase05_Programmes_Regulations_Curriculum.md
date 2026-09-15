# PHASE 05 — PROGRAMMES, REGULATIONS & CURRICULUM

## Pre-Requisite
Phases 01–04 complete (platform, auth/RBAC/features/visibility, institution structure & terms, comms + workflow engine).

## Objective
The academic backbone: programmes (level, mode, duration, intake, approving body, exam authority), **versioned regulations** with the rules JSON that drives attendance/passing/grading/grace/exit points, programme-regulation bindings, programme structure per term (credit limits, exit points), **courses** owned by a regulation (L-T-P-C, types, syllabus, prerequisites/co-/anti-requisites), elective baskets (PE/OE/minor/honours/MOOC/vertical), grading scales and assessment schemes (configuration only), BoS/Academic-Council approval through the workflow engine, regulation clone/lock, public course catalogue feed, value-added/CE courses. Batches and sections are created here too (structure), while students join them in Phase 07.

## Feature keys
`academics.programs`, `academics.regulations`, `academics.curriculum`, `academics.elective_baskets` (on, starter); `academics.minors_honours` (off, standard); `academics.value_added_courses` (on, standard); `academics.bos_approval_workflow` (off, professional; depends `workflow.engine`, `governance.committees`); `academics.public_catalog` (on, standard; depends `website.core`). `academics.credit_transfer_mooc`, `academics.nep_exit_reentry`, `academics.abc_apaar` register here but are exercised in Phase 07.

## Visibility rules
- Programmes/regulations/courses/baskets/structures: **readable institution-wide** by all staff (`programs:view` etc. granted to faculty, HOD, dean, registrar, COE, IQAC…); students/parents read the curriculum of their own programme-regulation (self via enrolment, Phase 07) and the public catalogue.
- Edit: `programs:manage` (registrar, institution_admin), `curriculum:manage`/`courses:create|update` scoped: HOD @department may draft courses of their department; dean @faculty approves; `regulations:approve` (dean/academic council secretary/VC); `college_admin` @college for college-level regulations.
- Batches/sections: `batches:view` institution-wide; `batches:manage` registrar/HOD @department.

## 05.1 Database tables
Section 7 tables: `grading_scales, programs, regulations, program_regulations, program_structure_terms, assessment_schemes, assessment_components, courses, course_prerequisites, elective_baskets, elective_basket_courses, curriculum_courses, batches, batch_sections` — exist. Expected delta migration: none.

## 05.2 Alembic migration
`0005_phase05_academic_seed.py` — data-only: no rows (pack defaults were copied at onboarding). Provide `scripts/seed_demo_institution.py --only academics`: 2 programmes (B.Tech CSE 8 terms, MBA 4 terms), regulations R2024 (active) and R2022 (superseded), full structure for B.Tech Sem 1–8 with core/PE/OE baskets, 40 courses with prerequisites, grading scale 10-point, assessment schemes THEORY-40-60/LAB-50-50/PROJECT, batches 2024/2025 with sections A/B.

## 05.3 Models — `models/academic.py` (extend), `models/curriculum.py`
`GradingScale`, `Program`, `Regulation`, `ProgramRegulation`, `ProgramStructureTerm`, `AssessmentScheme`, `AssessmentComponent`, `Course`, `CoursePrerequisite`, `ElectiveBasket`, `ElectiveBasketCourse`, `CurriculumCourse`, `Batch`, `BatchSection`. Enums: `ProgramLevel`, `ProgramMode`, `TermPattern`, `ExamAuthority`, `RegulationStatus`, `CourseType`, `CourseStatus`, `PrereqRelation`, `BasketType`, `AllocationMode`, `BatchStatus`. `Regulation.rules` typed by a Pydantic model `RegulationRules` (all keys in `docs/Academic_Core_Design.md` §1a with defaults) validated on write.

## 05.4 Schemas — `app/schemas/academics.py`, `curriculum.py`
`ProgramCreate/Update/Response`, `RegulationCreate/Update/Response` (+ `rules: RegulationRules`), `RegulationCloneRequest{code, name, effective_from_admission_year}`, `RegulationApproveRequest{resolution_id?}`, `ProgramRegulationCreate/Response{total_credits_required, rules_override}`, `StructureTermIn/Out`, `CurriculumCourseIn/Out`, `StructureReplaceRequest{terms:[…], courses:[…]}` + `StructureValidationResponse{credit_totals_by_term, total, required, issues[]}`, `CourseCreate/Update/Response` (L-T-P-C, type, scheme, syllabus JSON, textbooks, catalog flag), `PrerequisiteSet{items:[{related_course_id, relation, min_grade?, is_hard}]}`, `BasketCreate/Update/Response` + `BasketCoursesReplace`, `GradingScaleCreate/Update/Response`, `AssessmentSchemeCreate/Update/Response` (+ components), `BatchCreate/Update/Response`, `BatchSectionIn/Out`, `PublicCatalogProgram/Course` (no internal ids beyond codes), `RegulationDiffResponse` (courses added/removed/changed vs previous regulation).

## 05.5 Repository
`program_repository.py` (`module="programs"`, scope columns institution/college/faculty/department), `regulation_repository.py` (`module="regulations"`; `with_courses`), `course_repository.py` (`module="courses"`, search by code/title trgm, filters regulation/department/type/status), `curriculum_repository.py` (structure terms + curriculum courses + baskets in one loader), `grading_repository.py`, `assessment_scheme_repository.py`, `batch_repository.py` (`module="batches"`; `promote` support). Visibility registrations for the five modules (self predicates none; scope columns as above).

## 05.6 Services
- `program_service.py`: CRUD; `exam_authority` defaults from institution type (affiliated → `university`); `is_open_enrolment` only for `certificate|diploma` levels; closing a programme requires no active batches; emits `program.created/updated`.
- `regulation_service.py`
  1. Create draft with `rules` (validated against `RegulationRules`; pack defaults pre-filled).
  2. `approve(id, resolution_id?)`: if `academics.bos_approval_workflow` → start workflow `regulation.approval` and approve on hook; else direct with `regulations:approve`; approved → editable structure but rules locked; `activate` sets `status='active'`, `locked_at`; **no edits to courses/structure under active** — all mutating endpoints raise `409 RECORD_LOCKED`.
  3. `clone(id, …)`: deep copy regulation + courses (new codes keep the same `code`, new ids) + structures + baskets + schemes/components; new regulation `draft`; source `superseded_by_id` set on activation of the clone (source → `superseded`).
  4. `diff(id)` vs `superseded` predecessor.
  5. `rules_effective(program_regulation)` = regulation.rules ⊕ `rules_override` (used by attendance, exams, results in later phases via `RulesResolver`).
- `curriculum_service.py`
  1. `replace_structure(program_regulation_id, request)`: transactional replace of terms + curriculum courses + baskets; validations: term numbers 1..`total_terms`, `min ≤ normal ≤ max` credits, every course belongs to the same regulation and is `approved|active`, basket courses ⊂ regulation courses, Σ mandatory credits + Σ basket `credits_required` == `total_credits_required` (warning if mismatch on draft, error on approve), exit points align with `rules.exit_points`.
  2. `validate(program_regulation_id)` → `StructureValidationResponse`.
  3. Prerequisite graph must be acyclic (`prerequisite` relation) — DFS check on `PUT /courses/{id}/prerequisites`; a course cannot be its own prerequisite; `antirequisite` symmetric.
- `course_service.py`: CRUD (code unique per regulation; L-T-P → `contact_hours_per_week`; credits ≥ 0; `is_credit_bearing=false` for audit/mandatory_non_credit; scheme default by course_type from regulation defaults); status `draft → approved → active → retired`; `bulk_import` CSV (`code,title,type,L,T,P,credits,department_code,scheme_code`) as a job with partial-success report; public catalogue projection.
- `grading_service.py`: grading scales (ranges must cover 0–100 without overlap; exactly one fail grade), assessment schemes (component weights/max consistent: `Σ scaled_to = cia_max`; `best_of.take ≤ of`), copy-from-pack.
- `batch_service.py`: create batch per (college, programme, admission year, entry type) with sections A…N and capacities; `current_term_number` maintained by Phase 07 promotion; `class_advisor` assignment grants role `class_advisor@offering/section` (RBAC service); rollover hook `on_rollover` (Phase 03) → for each active batch propose promotion (executed in Phase 07 once term records exist).

## 05.7 Events / jobs
Emits: `program.created/updated`, `regulation.approved/activated/superseded`, `course.created/updated/retired`, `curriculum.replaced`, `batch.created`. Consumers: `search.reindex` (courses), `catalog.invalidate` (public cache). Jobs: `courses.bulk_import`. Workflow: `regulation.approval` (hook `on_approved` → `regulation_service.mark_approved`). Beat: none.

## 05.8 Endpoints
```
GET/POST /api/v1/programs · GET/PUT/DELETE /programs/{id} · POST /programs/{id}/close [programs:view|create|update|delete|manage] {academics.programs}
GET/POST /api/v1/regulations · GET/PUT /regulations/{id} · POST /regulations/{id}/approve · /activate · /clone · GET /regulations/{id}/diff [regulations:*] {academics.regulations}
GET      /api/v1/regulations/{id}/rules-effective?program_id=       → merged rules [regulations:view]
GET/POST /api/v1/program-regulations · PUT /program-regulations/{id} [curriculum:manage]
GET/PUT  /api/v1/program-regulations/{id}/structure · POST /program-regulations/{id}/structure/validate [curriculum:view|manage] {academics.curriculum}
GET/POST /api/v1/elective-baskets · PUT/DELETE /elective-baskets/{id} · PUT /elective-baskets/{id}/courses [curriculum:manage] {academics.elective_baskets}
GET/POST /api/v1/courses · GET/PUT/DELETE /courses/{id} · POST /courses/{id}/status · PUT /courses/{id}/prerequisites · POST /courses/bulk-import · GET /courses/export [courses:*]
GET/POST /api/v1/grading-scales · PUT /grading-scales/{id} [exams:configure]
GET/POST /api/v1/assessment-schemes · PUT /assessment-schemes/{id} · PUT /assessment-schemes/{id}/components [exams:configure]
GET/POST /api/v1/batches · GET/PUT /batches/{id} · PUT /batches/{id}/sections · PUT /batches/{id}/sections/{sid}/advisor [batches:view|create|update|manage]
GET      /api/v1/public/catalog?program=&level=&college=            → public catalogue {public} {academics.public_catalog}
GET      /api/v1/public/catalog/programs/{code} · /courses/{regulation}/{code} {public}
```

## 05.9 Frontend
- `/admin/academics/programs` (DataTable: code, name, level, mode, department, intake, exam authority, status; drawer form), `/admin/academics/regulations` (list with status chips) and `/admin/academics/regulations/:id` (tabs **Rules** — grouped form for every rules key with defaults and help text; **Courses** — table with inline status, bulk import, export; **Structure** — per-term editor with drag-drop course assignment, credit meters (min/normal/max), basket chips, exit-point toggles, validate button showing issues; **Baskets** — basket editor with allocation mode; **Diff** — vs predecessor; header actions Approve / Activate / Clone with confirmations and lock banners), `/admin/academics/courses` (search, filters, detail drawer: L-T-P-C, syllabus units editor, prerequisites graph editor with cycle warning), `/admin/academics/grading` (scales with range editor + preview; schemes with component table and weight validation), `/admin/academics/batches` (batches per programme/year; sections & advisors), public `/catalog` (programme cards → course lists; SEO), `/catalog/:program`.
- Nav: ACADEMICS › Programmes, Regulations, Courses, Grading & Schemes, Batches.

## 05.10 Mobile
Read-only `features/academic_structure`: my programme/regulation curriculum viewer (for students from Phase 07), course detail with syllabus; faculty: courses of their department. No editing.

## 05.11 API verification — `scripts/verify/05_academics.ps1`
Roles: `registrar`, `hod.cse`, `dean.eng`, `faculty.1`, `student.1`, unauthenticated.
1. Seed `--only academics`; `GET /programs` as `faculty.1` → 200 (read-all); `POST /programs` as `faculty.1` → 403.
2. `POST /regulations` (draft, rules with `attendance_min_pct=80`) as `registrar` → 201; `PUT` rules `ese_pass_min_pct="x"` → 422.
3. Courses: `POST /courses` under the draft regulation as `hod.cse` (own department) → 201; under another department → 403 (scope); duplicate code in the same regulation → 409.
4. Prerequisites: set `CS201 → prerequisite CS101`; then `CS101 → prerequisite CS201` → 422 `RULE_VIOLATION` (cycle).
5. Structure: `PUT …/structure` with Σ credits ≠ required → `validate` lists issue; approve attempt → 409 listing issues; fix → validate clean → `POST /regulations/{id}/approve` as `dean.eng` → status `approved`; as `hod.cse` → 403.
6. Activate → `active`; `PUT /courses/{id}` under it → 409 `RECORD_LOCKED`; `POST /regulations/{id}/clone` → new draft with same course codes and new ids; edit a cloned course → 200; activate clone → source `superseded`, `superseded_by_id` set; `GET /regulations/{clone}/diff` shows changed course.
7. BoS workflow: enable `academics.bos_approval_workflow`; approve → instance `regulation.approval` pending for `dean.eng`; act approve → regulation approved via hook.
8. Baskets: create PE-III with `min_choose=1,max_choose=1,credits_required=3`, courses from another regulation → 422.
9. Grading: scale ranges with a gap (80–89, 70–78) → 422; scheme components `Σ scaled_to ≠ cia_max` → 422.
10. Batches: create 2026 batch with sections A/B; assign advisor `faculty.1` to A → `GET /users/{faculty.1}/roles` shows `class_advisor@offering:<section>`.
11. Bulk import 20 courses CSV with 2 bad rows → job succeeded, report `succeeded=18, failed=2` with reasons; `GET /courses/export` → XLSX.
12. Public: unauthenticated `GET /public/catalog` → programmes with `is_public_catalog` courses only; internal ids absent; disable `academics.public_catalog` → 403.

## 05.12 UI verification
1. Regulation page: rules form saves; structure editor drag-drop and credit meters; validate panel; approve/activate flow with lock banner; clone creates and navigates to the new draft; diff tab highlights changes.
2. Courses: search by code/title, syllabus units editor, prerequisite editor blocks cycles with a message.
3. Grading & schemes pages validate ranges/weights inline.
4. Batches page: sections and advisor assignment.
5. Public catalogue renders and is indexable (title/meta), hidden when the feature is off.
6. Mobile: student curriculum viewer (after Phase 07 seed) and faculty course detail.

## 05.13 Deliverables checklist
- [ ] Models/schemas/repos/services for programmes, regulations (rules model, approve/activate/clone/diff/lock), programme-regulations, structure + validation, courses (+prerequisite graph, bulk import/export, status), baskets, grading scales, assessment schemes, batches/sections (+advisor role grant)
- [ ] `RulesResolver` (`rules_effective`) exposed for later phases; BoS workflow definition hook
- [ ] Events, catalogue cache, demo seed `--only academics`
- [ ] Web pages (regulation workspace, courses, grading, batches, public catalogue); mobile read-only viewers
- [ ] `scripts/verify/05_academics.ps1` passes; UI checklist done; guards green; commit `feat(phase-05): programmes, regulations, curriculum`
