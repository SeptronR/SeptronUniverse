# PHASE 17 — OBE ATTAINMENT & CONTINUOUS QUALITY IMPROVEMENT

## Pre-Requisite
Phases 01–16 complete (OBE definitions and question→CO maps from Phase 13, locked internal marks with `question_wise`, published results with question-wise script valuations from Phase 15, surveys table exists — Phase 27 adds the survey UI; this phase reads `feedback_surveys/feedback_responses` when present).

## Objective
Compute Outcome-Based Education attainment from data that already exists — no re-entry: **CO attainment** per offering from CIA question-wise marks and ESE question-wise valuations (or apportioned ESE totals), **PO/PSO attainment** per programme-batch from CO-PO matrices, **indirect attainment** from course-exit/programme-exit/alumni/employer surveys, targets and level bands per regulation/programme, gap analysis, the **CQI action register**, attainment dashboards (heatmaps, radar), and NBA SAR Criterion-3 exports — with reproducible runs (config snapshots).

## Feature keys
`obe.attainment` (off, professional; depends `obe.definitions`, `assessment.question_wise_co`), `obe.indirect_surveys` (off, professional; depends `surveys.core`), `obe.cqi` (off, professional; depends `obe.attainment`), `obe.nba_export` (off, professional; depends `obe.attainment`). Institutions enable them through the super-admin Features tab (dependency confirmation).

## Visibility rules
- CO attainment per offering: **faculty own offerings** (ownership `course_offering_faculty`), course coordinators, HOD `obe:view@department`, OBE coordinator/IQAC/dean/COE `obe:view_all`; students **do not** see attainment (setting `obe.show_students=false` by default; when true, students see their own CO achievement per offering as a self view).
- PO attainment per programme-batch: HOD (own programmes), dean (faculty unit), OBE coordinator/IQAC/registrar/VC (all), auditor read.
- Configs: `obe:configure` (OBE coordinator, dean). CQI actions: owner (ownership `owner_staff_id`) + HOD department + `obe:manage`.

## 17.1 Database tables
Section 17: `attainment_configs, attainment_runs, co_attainments, po_attainments, cqi_actions`; reads `course_outcomes, co_po_mappings, outcome_definitions, peo_po_mappings, assessment_questions, internal_marks, offering_assessments, assessment_components` (§14), `script_valuations, script_final_marks, exam_papers, student_course_results` (§15–16), `feedback_surveys, feedback_responses` (§26), `curriculum_courses, program_regulations, batches` (§7). Expected delta migration: none.

## 17.2 Alembic migration
`0017_phase17_attainment_seed.py` — data-only: default `attainment_configs` template per pack (targets 60/60, levels 40/50/60, direct 80/indirect 20, CIA 30/ESE 70, targets 2.0) written to `platform_settings['attainment_defaults']` and copied per regulation/programme on first run. Demo seed `--only attainment`: configs for both programmes, CO runs for all offerings of the published term, a PO run for batch 2024, course-exit survey responses (mock) for 6 offerings, 8 CQI actions.

## 17.3 Models — `models/obe_attainment.py`
`AttainmentConfig`, `AttainmentRun`, `CoAttainment`, `PoAttainment`, `CqiAction`. Enums: `ConfigScope` (regulation|program), `RunScope` (offering|program_batch), `RunStatus`, `CqiStatus`. Value objects (Pydantic): `LevelBand`, `CoBreakdown` (per assessment: students assessed/above target/pct/level), `PoBreakdown` (per contributing course: CO levels × map levels).

## 17.4 Schemas — `app/schemas/obe_attainment.py`
`AttainmentConfigIn/Out` (scope, targets, levels[], weights, CO/PO target levels, `ese_apportion_strategy: question_wise|qp_pattern|uniform`), `CoRunRequest{offering_id, include_indirect: bool, survey_id?}`, `PoRunRequest{program_id, batch_id, include_indirect: bool, term_upto?: int}`, `RunResponse{status, config_snapshot, computed_at, warnings[]}`, `CoAttainmentResponse{offering, cos:[{co, students_assessed, students_above_target, cia_level, ese_level, direct_level, indirect_level, final_level, target, gap, breakdown}]}`, `PoAttainmentResponse{program, batch, outcomes:[{outcome, direct, indirect, final, target, gap, contributing_courses, breakdown}]}`, `ProgramAttainmentTrend{batches:[…]}`, `CoPoHeatmap`, `GapListRow{scope, outcome, gap, suggested_action}`, `CqiActionIn/Out` (+ workflow-free status transitions), `NbaExportRequest{program_id, batch_id, format: xlsx|docx}`, `StudentCoAchievement{offering, cos:[{co, marks_pct, above_target}]}`, `IndirectSurveySummary{survey, responses, mean_by_co|outcome}`.

## 17.5 Repository
`attainment_repository.py` (`module="obe"`; configs by scope with fallback; runs; CO/PO rows with `selectinload`; heatmap/trend aggregates; ownership: offerings via `course_offering_faculty`; scope columns institution/college/department via offering/programme), `cqi_repository.py` (ownership `owner_staff_id`), read-only helpers over Phase 13/15 tables (`question_marks(offering)` = union of internal question-wise marks and ESE question-wise valuations resolved through `exam_registration_items → answer_scripts → script_valuations(final round)`).

## 17.6 Services
- `attainment_config_service.py`: get effective config for (regulation|program) with fallback order program → regulation → platform defaults; validation (levels ascending, weights sum 100 for direct/indirect and CIA/ESE); versioned edits (config snapshot stored on every run so past runs stay reproducible).
- `co_attainment_service.py`
  1. `run(offering, include_indirect)` (job; requires all CIA components `locked` and, when the offering's course had an ESE paper, results `published`; otherwise `warnings`).
  2. Per assessment (CIA components with `co_mappable` and `question_wise` marks): student CO marks = Σ marks of questions tagged to the CO; CO max = Σ max of those questions; `pct_students_above_target = count(student_co_marks ≥ target_marks_pct × co_max) / assessed` → level via `levels` bands (1/2/3; 0 when below band 1).
  3. ESE: question-wise from `script_valuations` (final resolved round) when available (`ese_apportion_strategy=question_wise`); else apportion ESE total by CO weights declared in `exam_papers.qp_pattern` (`qp_pattern`); else uniform across COs (warning `ESE_UNIFORM_APPORTION`).
  4. `cia_level` = average of CIA assessment levels (weighted by component `weight_pct` when set); `direct_level = cia_weight × cia_level + ese_weight × ese_level` (weights from config, normalised to 1).
  5. Indirect (`obe.indirect_surveys`): course-exit survey (`feedback_surveys.survey_type='course_exit'`, target_type `offering`) questions tagged `co_id` → mean response mapped to 1–3 by scale thresholds → `indirect_level`.
  6. `final_level = direct_weight × direct + indirect_weight × indirect` (indirect ignored → direct only, warning `NO_INDIRECT`); `gap = target_level − final_level`; rows `co_attainments`; emits `obe.co_attainment_computed`; per-student CO achievement cache for the optional student view.
  7. Auto-trigger: consumer of `results.published` (Phase 15) runs CO attainment for all offerings of the published term (setting `obe.auto_run=true`).
- `po_attainment_service.py`
  1. `run(program, batch, include_indirect, term_upto)` (job): contributing courses = curriculum courses of the batch's programme-regulation up to `term_upto` (default current) that have a CO run for the batch's offerings (`course_offering_targets.batch_id`); for each CO run: course→PO contribution = `Σ_CO (CO_final × map_level) / Σ_CO map_level` per PO/PSO mapped; programme PO direct = mean over contributing courses (optionally credit-weighted, config); indirect from programme-exit / alumni / employer surveys tagged `outcome_id`; `final = direct_weight × direct + indirect_weight × indirect`; gap; `contributing_courses` count; rows `po_attainments`; PEO attainment derived through `peo_po_mappings` (reported, not stored).
  2. Trend across batches; heatmap course × PO; `warnings` when < 60 % of mapped courses have CO runs (`INSUFFICIENT_COVERAGE`).
- `cqi_service.py` (`obe.cqi`): gap list (CO gaps per offering, PO gaps per batch) → create actions (scope, outcome, gap, action text, owner, due date) → status `planned → in_progress → done → verified` (HOD/OBE coordinator verifies with evidence) → reminders (Beat); link actions to the next run to show closure (gap before/after); NBA Criterion 7 evidence.
- `nba_export_service.py` (`obe.nba_export`): XLSX/DOCX with Criterion 3 tables (3.1 CO statements & CO-PO matrix, 3.2 attainment per course, 3.3 PO/PSO attainment with direct/indirect split and targets, CQI actions) using `openpyxl`/`python-docx` templates; also feeds Phase 32 metrics (`obe.co_attainment`, `obe.po_attainment`).
- Dashboards: `GET /obe/dashboard?program_id&batch_id` (radar of PO/PSO, heatmap, gap list, coverage %) for HOD/IQAC; `GET /course-offerings/{id}/attainment/heatmap` for faculty (Phase 13 preview promoted to computed values).

## 17.7 Events / jobs
Emits: `obe.co_attainment_computed`, `obe.po_attainment_computed`, `obe.gap_detected`, `cqi.action_created/updated/verified`, `obe.export_generated`. Consumers: `results.published` → `obe.auto_run` (this phase), `marks.locked` (Phase 13) → CO run refresh (debounced), `surveys.closed` (Phase 27) → indirect recompute, Phase 32 metrics invalidation, notifications (gap detected → HOD/owner; CQI due reminders). Jobs: `obe.co_run`, `obe.po_run`, `obe.nba_export`, `obe.batch_recompute`. Beat: `cqi.due_reminders` (weekly), `obe.coverage_digest` (monthly to OBE coordinator). Workflows: none (CQI verification is a role action).

## 17.8 Endpoints
```
GET/PUT  /api/v1/attainment-configs?scope_type&scope_id · GET /attainment-configs/effective?program_id [obe:configure|view] {obe.attainment}
POST     /api/v1/course-offerings/{id}/attainment/compute (job) · GET /course-offerings/{id}/attainment · GET /course-offerings/{id}/attainment/heatmap · GET /course-offerings/{id}/attainment/runs [obe:compute|view (own offering)]
GET      /api/v1/course-offerings/{id}/attainment/students · GET /attainment/me?offering_id= [obe:view|self (setting)]
POST     /api/v1/programs/{id}/batches/{bid}/attainment/compute (job) · GET /programs/{id}/attainment?batch_id · GET /programs/{id}/attainment/trend · GET /programs/{id}/attainment/heatmap?batch_id [obe:compute|view]
POST     /api/v1/obe/recompute-term?term_id= (job, all offerings) [obe:compute]
GET      /api/v1/obe/dashboard?program_id&batch_id · GET /obe/gaps?program_id&batch_id&threshold [obe:view]
GET      /api/v1/obe/indirect/summary?survey_id [obe:view] {obe.indirect_surveys}
GET/POST /api/v1/cqi-actions · PUT /cqi-actions/{id} · POST /cqi-actions/{id}/status · POST /cqi-actions/{id}/verify [obe:manage|view (owner)] {obe.cqi}
POST     /api/v1/obe/export/nba-sar (job) · GET /obe/exports/{job_id} [obe:export] {obe.nba_export}
```

## 17.9 Frontend
- `/admin/obe/config` (effective config viewer per programme/regulation; editor with validation and history), `/faculty/offerings/:id/attainment` (compute button with prerequisites checklist (CIA locked / results published / survey present), CO table with per-assessment breakdown drawer, CIA/ESE/direct/indirect/final columns, target/gap chips, heatmap CO × assessment, student CO achievement drill-down), `/admin/obe/program-attainment` (programme/batch picker → radar PO/PSO, course × PO heatmap, direct vs indirect bars, coverage %, gap list with "create CQI action"), `/admin/obe/trend` (batches over time), `/admin/obe/cqi` (kanban by status, owner filter, due dates, evidence upload, verify), `/admin/obe/exports` (NBA SAR generation and downloads), IQAC dashboard widgets (Phase 32 reuses).
- Student portal (setting-gated) `/student/courses/:offeringId/outcomes` (own CO achievement).
- Nav: QUALITY & GOVERNANCE › OBE Attainment, CQI, NBA Export; ACADEMICS › (faculty) Attainment on offering page.

## 17.10 Mobile
Faculty: Courses › offering › Attainment (read-only CO table and heatmap image); HOD/IQAC shell: Attainment dashboard (radar, gap list), CQI actions (update status, upload evidence photo). No student screens unless the setting is on (then a simple CO achievement list).

## 17.11 API verification — `scripts/verify/17_attainment.ps1`
Roles: `obe` (obe_coordinator), `hod.cse`, `dean.eng`, `faculty.1` (offering X), `faculty.3`, `iqac`, `student.1`, `auditor.tmp`.
1. Enable `obe.attainment` (+ dependencies) for the demo institution via super admin; `GET /attainment-configs/effective?program_id=BTECH` → platform defaults until `PUT` as `obe` sets targets (levels not ascending → 422; weights ≠ 100 → 422).
2. Prerequisites: `POST /course-offerings/X/attainment/compute` before CIA lock → 202 with `warnings=[CIA_NOT_LOCKED]` and no rows (or 409 when setting `obe.strict_prereq=true`); after Phase 13 lock and Phase 15 publish → run `computed`.
3. Formula check (script): for offering X, CO1 with 2 CIA questions (Q1a 5 marks, Q2 10) and ESE question-wise: compute expected `pct_students_above_target` from seeded marks (target 60 % of 15) and level band; assert `cia_level`, `ese_level`, `direct_level = 0.3×cia + 0.7×ese`, `final = 0.8×direct + 0.2×indirect` when a course-exit survey exists, else `final = direct` with warning `NO_INDIRECT`; `gap = target − final`.
4. ESE apportionment: an offering whose paper lacks question-wise valuations but has `qp_pattern` CO weights → `ese_apportion_strategy=qp_pattern` used (breakdown shows); neither → uniform with warning.
5. Visibility: `GET /course-offerings/X/attainment` as `faculty.1` → 200; as `faculty.3` → 404; as `hod.cse` → 200; `GET /attainment/me` as `student.1` with setting off → 403 `FEATURE_DISABLED`/`PERMISSION_DENIED`; on → own CO achievement only.
6. PO run: `POST /programs/BTECH/batches/2024/attainment/compute` → job; `GET /programs/BTECH/attainment?batch_id=2024` → 12 POs + 2 PSOs with direct/indirect/final/gap; assert course→PO contribution for one course = Σ(CO_final × level)/Σ level from the CO run and the CO-PO matrix; coverage warning when only 50 % of mapped courses have CO runs (dev: delete one CO run) → `INSUFFICIENT_COVERAGE`.
7. Indirect: seed programme-exit survey responses tagged to PO3 → indirect level appears; `include_indirect=false` → direct only.
8. Auto-run: publish a correction run in Phase 15 dev → `obe.auto_run` triggers CO recompute for affected offerings (new `attainment_runs` row).
9. Reproducibility: change config targets → old run rows unchanged and `config_snapshot` differs on the new run.
10. CQI: `GET /obe/gaps?threshold=0` lists POs/COs with gap > 0; create action for PO3 owner `hod.cse` due next month → `planned`; `hod.cse` `status in_progress` → `done` with evidence → `obe` verify → `verified`; `faculty.3` updating someone else's action → 404; Beat reminder for overdue actions notifies owner.
11. NBA export: job → XLSX with sheets 3.1/3.2/3.3/CQI; values match API responses (spot-check two cells); feature off → 403.
12. Dashboard: `GET /obe/dashboard?program_id&batch_id` as `iqac` → radar data, heatmap matrix, coverage %; `auditor` read OK; `POST compute` as auditor → 403.

## 17.12 UI verification
1. Config editor validation and history; effective config banner on attainment pages.
2. Offering attainment page: prerequisites checklist, compute job, CO table with breakdown drawer, heatmap, student drill-down (permission-gated); student outcomes page when enabled.
3. Programme attainment: radar, heatmap, direct/indirect bars, coverage, gap list → create CQI action inline; trend page across batches.
4. CQI kanban with evidence upload and verify; reminders visible in notifications.
5. NBA export download; IQAC dashboard widgets show attainment tiles.
6. Mobile: HOD dashboard radar and CQI status update with photo evidence.

## 17.13 Deliverables checklist
- [ ] Config service with fallbacks and validation; CO attainment (CIA question-wise, ESE question-wise/apportioned/uniform, indirect via surveys, weights, bands, gaps, warnings, per-student achievement), PO/PSO attainment (contribution formula, coverage, indirect, trend, heatmap), auto-run on publish, reproducible snapshots, CQI register with verification and reminders, NBA SAR export, dashboards
- [ ] Ownership/visibility registrations; events/jobs/Beat; demo seed `--only attainment`
- [ ] Web + mobile; `scripts/verify/17_attainment.ps1` passes (incl. formula assertions); UI checklist done; guards green; commit `feat(phase-17): OBE attainment & CQI`
