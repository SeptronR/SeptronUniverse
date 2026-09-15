# PHASE 13 — INTERNAL ASSESSMENT, OBE DEFINITIONS, LMS-LITE & PROJECTS

## Pre-Requisite
Phases 01–12 complete (offerings with rosters, assessment schemes from Phase 05, workflow engine, fees for nothing here, question bank tables in place).

## Objective
Continuous internal assessment driven by the regulation's assessment scheme: offering assessments instantiated from components, **question → CO mapping** with Bloom levels, question-wise internal marks with the submit → verify → lock chain, best-of/scaling consolidation (CIA), post-lock change requests via workflow, submission to the university for affiliated colleges; **OBE definitions** (PEO/PO/PSO/CO, CO-PO matrix with justifications, NBA defaults from the pack); **LMS-lite** (modules/contents, assignments with rubrics and late penalties, quizzes built from the question bank/blueprints/paper builder carried from Orbit, study materials, discussions, announcements), lesson plans tied to sessions and course files; **student projects/dissertations** with guides and reviews — all feeding `internal_marks` so CIA and attainment need no re-entry.

## Feature keys
`assessment.internal_marks`, `assessment.marks_workflow` (on, starter); `assessment.question_wise_co`, `assessment.marks_change_requests`, `assessment.projects`, `obe.definitions`, `lms.content`, `lms.assignments`, `lms.quizzes`, `lms.question_bank`, `lms.blueprints_paper_builder`, `lms.study_materials`, `lms.discussions`, `lms.lesson_plans`, `lms.course_files` (on, standard); `lms.online_class_links` (on, standard; depends `integrations.video_conf`); `lms.similarity_check` (off, professional); `lms.lti_moodle` (off, professional).

## Visibility rules
- Offering assessments / internal marks / LMS content: **faculty own offerings** (ownership `course_offering_faculty`), **students own registered offerings** (self via confirmed items), HOD department (`marks:view_all@department`, verify), exam cell/COE institution (`marks:lock`, read), registrar read, parents wards' marks (read), auditor read.
- OBE definitions: PO/PSO/PEO per programme editable by `obe:manage` (OBE coordinator, HOD for own programmes, dean); COs per course by course owners (faculty of the department, HOD); read institution-wide.
- Question bank: authors own questions (ownership `created_by`), department shares (`lms:view_all@department`), COE/exam cell read for ESE papers (Phase 14).
- Projects: members (students self), guides (ownership `guide_staff_id`), HOD department, panel members (review link).

## 13.1 Database tables
Section 14: `outcome_definitions, peo_po_mappings, course_outcomes, co_po_mappings, offering_assessments, assessment_questions, internal_marks, cia_consolidations, marks_change_requests, student_projects, project_members, project_reviews, syllabus_topics, questions, question_options, question_blueprints, question_papers, study_materials, course_modules, course_contents, content_views, lms_assignments, assignment_submissions, quizzes, quiz_attempts, course_announcements, discussion_threads, discussion_posts, lesson_plans, course_files`; `assessment_schemes, assessment_components` (§7) — exist. Expected delta migration: none.

## 13.2 Alembic migration
`0013_phase13_assessment_seed.py` — data-only: NBA PO set (12 POs for engineering; generic 8 for others) as platform `outcome_definitions` templates in `platform_settings['obe_templates']` (copied per programme on demand); Bloom levels. Demo seed `--only assessment`: POs/PSOs for both programmes, 6 COs per course with CO-PO matrix, offering assessments per scheme (CAT-1, CAT-2, assignment, quiz, lab), question maps, internal marks for CAT-1 (submitted/verified/locked mix), 2 change requests, LMS modules/contents for 10 offerings, 3 assignments with submissions, 2 quizzes with attempts, 5 projects with reviews, lesson plans and course files.

## 13.3 Models — `models/assessment.py`, `models/obe.py`, `models/lms.py`, `models/projects.py`, `models/content.py`
`OfferingAssessment`, `AssessmentQuestion`, `InternalMark`, `CiaConsolidation`, `MarksChangeRequest`; `OutcomeDefinition`, `PeoPoMapping`, `CourseOutcome`, `CoPoMapping`; `CourseModule`, `CourseContent`, `ContentView`, `LmsAssignment`, `AssignmentSubmission`, `Quiz`, `QuizAttempt`, `CourseAnnouncement`, `DiscussionThread`, `DiscussionPost`, `LessonPlan`, `CourseFile`; `StudentProject`, `ProjectMember`, `ProjectReview`; `SyllabusTopic`, `Question`, `QuestionOption`, `QuestionBlueprint`, `QuestionPaper`, `StudyMaterial`. Enums: `AssessmentStatus`, `ComponentCategory`, `ChangeRequestStatus`, `OutcomeType`, `BloomLevel`, `ContentType`, `AssignmentStatus`, `SubmissionStatus`, `QuizStatus`, `AttemptStatus`, `ShowResult`, `ProjectType/Status`, `QuestionType`, `Difficulty`, `PaperPurpose/Status`, `LessonStatus`.

## 13.4 Schemas — `app/schemas/assessment.py`, `obe.py`, `lms.py`, `projects.py`, `content.py`
`OfferingAssessmentResponse` (+ component, status, deadline, question map summary), `InstantiateRequest{scheme_override?}`, `QuestionMapReplace{questions:[{question_no, max_marks, co_id, bloom_level, part}]}`, `MarksBulkUpsert{rows:[{student_program_enrollment_id, marks?, is_absent?, is_exempt?, question_wise?}], source?}` + `MarksResult`, `MarksGridResponse` (students × questions/total, status), `SubmitRequest`, `VerifyRequest{decision, comment}`, `LockRequest`, `ConsolidateResponse{rows:[{student, component_breakdown, cia_total, cia_scaled}], status}`, `ChangeRequestCreate{target_type, target_id, new_value, reason, evidence_url}`, `ChangeRequestDecision`, `SubmitToUniversityRequest`, `OutcomeIn/Out` (PEO/PO/PSO), `PeoPoMatrix`, `CoIn/Out`, `CoPoMatrixReplace{cells:[{co_id, outcome_id, level, justification}]}`, `ModuleIn/Out`, `ContentIn/Out`, `ContentViewPing{progress_pct}`, `AssignmentIn/Out`, `SubmissionCreate` (files/text), `GradeBulk{rows:[{submission_id, marks, rubric_scores, feedback}]}`, `QuizIn/Out`, `QuizStartResponse` (shuffled questions without answers), `QuizAnswerSave`, `QuizSubmitResponse`, `PushToMarksRequest`, `AnnouncementIn/Out`, `ThreadIn/Out`, `PostIn/Out`, `LessonPlanIn/Out` + `DeliverRequest{session_id}`, `CourseFileChecklist`, `ProjectIn/Out`, `MemberIn`, `ReviewIn/Out`, `SyllabusTopicIn/Out`, `QuestionIn/Out` (bilingual bodies, options, answer key, tags, CO), `BlueprintIn/Out`, `PaperGenerateRequest{blueprint_id, strategy}` + `PaperOut`, `StudyMaterialIn/Out`.

## 13.5 Repository
`assessment_repository.py` (`module="marks"`; ownership faculty via offering; student self via items; department scope via offering; `FOR UPDATE` on `offering_assessments` during lock/consolidate), `obe_repository.py` (`module="obe"`), `lms_repository.py` (`module="lms"`), `project_repository.py` (`module="projects"`; member/guide/panel links), `content_repository.py` (`module="lms"`; author ownership). Register ownership links: `marks` (faculty own offerings; student self), `lms` (same), `projects` (member/guide/panel).

## 13.6 Services
- `assessment_service.py`
  1. `instantiate(offering)` (auto on offering `open`, or manual): components of the offering's scheme (override) → `offering_assessments` rows with `max_marks`, deadlines from settings (`assessment.marks_deadline_days`).
  2. Question map (`assessment.question_wise_co`): parts/questions with max marks summing to `max_marks`; CO ids from the course's COs; Bloom levels.
  3. `bulk_upsert_marks(assessment, rows, principal)`: faculty of offering while status ∈ `planned|conducted|marks_entry`; validates `0 ≤ marks ≤ max`; question-wise sums must equal `marks` (or compute `marks` from question-wise); absent/exempt flags; `Idempotency-Key`; sets status `marks_entry`; per-row `version`; audit summary.
  4. Chain: `submit` (faculty; all rostered students have a mark/absent/exempt) → `submitted` → `verify` (HOD; reject with comment returns to `marks_entry`) → `verified` → `lock` (exam cell/COE; also auto-lock after `marks_entry_deadline + N` days, Beat) → `locked`; emits `marks.locked` → OBE (Phase 17) and eligibility (Phase 11 `is_cia_ok`).
  5. `consolidate(offering)`: per student per component: apply `best_of` (take k of n within group), `Σ(marks/max × scaled_to)`, scale to `cia_max` → `cia_consolidations(status='computed')`; HOD approve → `hod_approved`; lock; for `programs.exam_authority='university'` → `submit_to_university` → `submitted_to_university` (Phase 34 `college_data_submissions(type='cia_marks')`); emits `cia.consolidated`.
  6. Change requests (`assessment.marks_change_requests`): after lock, faculty/HOD raise with old/new/reason/evidence → workflow `marks.change` (HOD → COE) → apply (recompute consolidation if locked → `RECORD_LOCKED` unless reopened by COE) → audit.
- `obe_service.py`: PEO/PO/PSO per programme (import NBA/generic template from pack), PEO-PO matrix, COs per course (code/statement/Bloom; 4–8 recommended), CO-PO/PSO matrix (levels 1–3 with justification; validation: every CO maps to ≥ 1 PO); versions follow regulation locks (COs of an active regulation editable only via a new regulation or `obe:manage` override with audit); exports (NBA Criterion 3 tables partial — attainment in Phase 17).
- `lms_service.py`
  1. Modules/contents (files via file service, video links, SCORM zip stored and served, embeds), release dates, CO tags, student `content_views` progress, completion %.
  2. Assignments: publish/close; submissions (files/text; max size; late allowed with penalty %/day; attempts); grading with rubric (`rubric_scores` → marks) bulk; optional similarity check via `PlagiarismChecker` adapter (job); when `offering_assessment_id` set → on grade write scaled marks into `internal_marks` (single write path); return/resubmit.
  3. Quizzes: from `question_papers` (frozen); start (attempt row, shuffled order, timer), autosave answers, submit/auto-submit at end, auto-score MCQ/MSQ/TF/numeric, manual score short/long; proctoring options (fullscreen, tab-switch limit → events) for `exams.online_proctored` (Phase 14 reuses); `push_to_marks` → `internal_marks` when linked to a component.
  4. Announcements (per offering; notifications), discussions (threads/posts/answers/upvotes; moderation by faculty), online class links (adapter `VideoConference.create_meeting` when enabled; else manual link).
  5. LTI/Moodle (flag): course/grade sync adapter stubs.
- `lesson_plan_service.py`: unit-wise plan with planned dates/hours/CO/resources; `deliver(session)` links to a `class_sessions` row and marks `delivered`; deviation report (planned vs actual); course file checklist (syllabus, timetable, lesson plan, question papers, marks, attainment, feedback) with completion % and HOD audit.
- `project_service.py`: projects per offering (`project|internship_project|dissertation` course types), members (1–4), guide/co-guide (faculty; external guide JSON), status flow, reviews (panel, rubric, marks) linked to `offering_assessments` (project_review components) → marks written to `internal_marks`; final viva handled by Phase 14 as `paper_type='project_viva'`.
- `content_service.py` (carried from Orbit): syllabus topics, question bank (bilingual, options, answer keys, tags, CO/topic/Bloom/difficulty, usage counts), blueprints (parts × counts × marks × CO/Bloom/difficulty distribution), paper generation (random within constraints; manual edits; freeze; bilingual print), study materials (publish to offering/course; students read).

## 13.7 Events / jobs
Emits: `assessment.instantiated`, `marks.submitted/verified/locked/changed`, `cia.consolidated/submitted_to_university`, `obe.definitions_changed`, `lms.content_published`, `assignment.published/graded`, `quiz.published/attempt_submitted`, `project.created/reviewed`, `lesson.delivered`. Consumers: notifications (deadlines, publication, grades), Phase 11 eligibility (`is_cia_ok`), Phase 17 attainment (`marks.locked`), Phase 34 submissions, `search.reindex` (questions/contents optional). Jobs: `assessment.import_marks` (XLSX), `assessment.export`, `lms.similarity_check`, `content.paper_generate`, `lms.scorm_unpack`. Beat: `assessment.deadline_reminders` (daily), `assessment.auto_lock` (nightly per setting), `assignments.close_due` (hourly), `quizzes.auto_submit` (minute). Workflows: `marks.change`.

## 13.8 Endpoints
```
GET      /api/v1/course-offerings/{id}/assessments · POST /course-offerings/{id}/assessments/instantiate [marks:view|enter] {assessment.internal_marks}
GET/PUT  /api/v1/offering-assessments/{id}/questions [marks:enter] {assessment.question_wise_co}
GET      /api/v1/offering-assessments/{id}/marks (grid) · POST /offering-assessments/{id}/marks (bulk, Idempotency-Key) · POST /offering-assessments/{id}/marks/import (job) · GET /export [marks:view|enter|export]
POST     /api/v1/offering-assessments/{id}/submit · /verify · /lock · /reopen [marks:enter|verify|lock] {assessment.marks_workflow}
GET/POST /api/v1/course-offerings/{id}/cia/consolidate · POST /cia/{id}/approve · /lock · /submit-to-university [marks:verify|lock]
GET/POST /api/v1/marks-change-requests · POST /marks-change-requests/{id}/approve|reject|apply [marks:correct] {assessment.marks_change_requests}
GET      /api/v1/marks/me?term_id=                                        → own internal marks per offering [marks:view (self)]
GET/PUT  /api/v1/programs/{id}/outcomes · POST /programs/{id}/outcomes/import-template · PUT /programs/{id}/peo-po-matrix [obe:manage|view] {obe.definitions}
GET/PUT  /api/v1/courses/{id}/outcomes · PUT /courses/{id}/co-po-matrix · GET /courses/{id}/co-po-matrix/export [obe:manage|view]
GET/POST /api/v1/course-offerings/{id}/modules · PUT/DELETE /modules/{id} · GET/POST /modules/{id}/contents · PUT/DELETE /contents/{id} · POST /contents/{id}/view [lms:manage|view] {lms.content}
GET/POST /api/v1/course-offerings/{id}/assignments · PUT /assignments/{id} · POST /assignments/{id}/publish|close · GET /assignments/{id}/submissions · POST /assignments/{id}/submit · POST /assignments/{id}/grade · POST /assignments/{id}/similarity-check (job) [lms:manage|grade|view] {lms.assignments}
GET/POST /api/v1/course-offerings/{id}/quizzes · PUT /quizzes/{id} · POST /quizzes/{id}/publish|close · POST /quizzes/{id}/start · PUT /quiz-attempts/{id}/answers · POST /quiz-attempts/{id}/submit · GET /quizzes/{id}/attempts · POST /quizzes/{id}/grade-manual · POST /quizzes/{id}/push-to-marks [lms:manage|view] {lms.quizzes}
GET/POST /api/v1/course-offerings/{id}/announcements · GET/POST /course-offerings/{id}/threads · GET/POST /threads/{id}/posts · POST /posts/{id}/upvote|mark-answer [lms:view|manage] {lms.discussions}
POST     /api/v1/course-offerings/{id}/online-link · POST /class-sessions/{id}/meeting (adapter) [lms:manage] {lms.online_class_links}
GET/POST /api/v1/course-offerings/{id}/lesson-plan · PUT /lesson-plans/{id} · POST /lesson-plans/{id}/deliver · GET /course-offerings/{id}/lesson-plan/deviation [lms:manage|view] {lms.lesson_plans}
GET/PUT  /api/v1/course-offerings/{id}/course-file · POST /course-files/{id}/audit [lms:manage|view_all] {lms.course_files}
GET/POST /api/v1/course-offerings/{id}/projects · PUT /projects/{id} · PUT /projects/{id}/members · POST /projects/{id}/reviews · GET /projects/me [projects:guide|review|view|self] {assessment.projects}
GET/POST /api/v1/courses/{id}/syllabus-topics · GET/POST /questions · PUT/DELETE /questions/{id} · POST /questions/import · GET/POST /blueprints · POST /question-papers/generate · GET/PUT /question-papers/{id} · POST /question-papers/{id}/freeze · GET /question-papers/{id}/print?lang= [lms:manage|view] {lms.question_bank|lms.blueprints_paper_builder}
GET/POST /api/v1/study-materials · PUT /study-materials/{id} · POST /study-materials/{id}/publish · GET /study-materials/me [lms:manage|view] {lms.study_materials}
```

## 13.9 Frontend
- Faculty `/faculty/marks/:offeringId` (assessment tabs per component; question map editor with CO/Bloom; **marks grid** (virtualized, keyboard-first, question-wise mode, absent/exempt toggles, import XLSX, validation badges); submit; status stepper; CO heatmap preview; change-request dialog after lock), `/faculty/offerings/:id/cia` (consolidation table, best-of applied, approve), `/faculty/offerings/:id/lms` (modules/contents editor with uploads/SCORM/embed, assignments (rubric builder, submissions grading grid with similarity %), quizzes (paper picker, settings, attempts, manual grading, push to marks), announcements, discussions, online class links), `/faculty/offerings/:id/plan` (lesson plan editor, deliver tick from sessions, deviation report, course-file checklist), `/faculty/projects` (projects, members, reviews with rubric), `/faculty/question-bank` (questions with bilingual editor + KaTeX, tags, import; blueprints; paper builder with generate/freeze/print), `/faculty/courses/:id/outcomes` (CO editor, CO-PO matrix with justification popovers).
- HOD `/hod/marks-verification` (queue of submitted assessments; verify/reject; CIA approvals), `/admin/obe/programs/:id` (PEO/PO/PSO, PEO-PO matrix, import template), exam cell `/admin/assessment/locks` (lock/reopen queue, university submission status).
- Student portal `/student/courses/:offeringId` (modules & content viewer with progress, assignments submit with late warning, quizzes with timer/autosave, discussions, announcements, materials, my marks per component, project page), `/student/marks`.
- Nav: ACADEMICS › Internal Marks, LMS, Question Bank, Lesson Plans; EXAMINATIONS › Marks Verification/Locks; QUALITY › OBE Definitions.

## 13.10 Mobile
Faculty: **Marks tab** (assessment list → question-wise entry grid with numpad → submit), Courses (LMS: upload content from camera/files, grade submissions with rubric, quiz attempts view, announcements, discussions, lesson plan tick-off); Student: Academics › Courses (content viewer, assignment submit with photo/PDF, quiz taking with timer/offline-safe autosave, discussions), Marks (per component), Projects; HOD: Approvals (marks verification cards).

## 13.11 API verification — `scripts/verify/13_assessment.ps1`
Roles: `faculty.1` (offering X), `faculty.3`, `hod.cse`, `exam.cell`, `obe` (obe_coordinator), `student.1` (in X), `student.2`, `parent.1`.
1. Seed `--only assessment`; `GET /course-offerings/X/assessments` as `faculty.1` → components from scheme; as `faculty.3` → 404; instantiate twice → idempotent.
2. Question map: parts A/B summing to 60 of `max_marks=50` → 422; correct → 200; CO from another course → 422.
3. Marks: bulk upsert 40 rows question-wise (sum mismatch on one row → rejected with reason), absent flags; `GET marks` grid; replay same key → replay; `student.2` (not in roster) → rejected; as `student.1` `GET /marks/me` → own row only (no other students).
4. Submit with a missing student → 409 listing; complete → `submitted`; `verify` as `faculty.1` → 403; as `hod.cse` reject with comment → `marks_entry`; resubmit → verify → `verified`; `lock` as `hod.cse` → 403; as `exam.cell` → `locked`; `POST marks` after lock → 409 `RECORD_LOCKED`.
5. Change request: `faculty.1` raises for one student (old 32 → new 35, evidence) → workflow HOD approve → COE approve → apply → mark updated, audit rows, consolidation recomputed.
6. Consolidation: CAT-1/CAT-2/CAT-3 with `best_of {take:2, of:3}` → verify `cia_total` for a known student against the formula; scaled to `cia_max=40`; HOD approve; lock; university submission for an affiliated programme (dev institution) → `submitted_to_university` and a `college_data_submissions(type='cia_marks')` row (Phase 34 table exists).
7. Eligibility hook: run Phase 11 compute → `is_cia_ok=false` for a student below `cia_pass_min_pct` when the regulation sets it.
8. OBE: import NBA template for B.Tech → 12 POs + 2 PSOs; COs for course CS101 (6); CO-PO matrix with a CO mapped to nothing → 422; valid → 200; `faculty.3` (ECE) editing CSE COs → 403; `obe` coordinator → 200.
9. LMS: create module + PDF content + video link; `student.1` view ping 100 % → progress; `student.2` → 404; assignment publish (due tomorrow, late 10 %/day) → `student.1` submits text+file → grade with rubric → marks written to the linked `offering_assessment` internal mark (scaled) — verify `internal_marks` row; late submission after due → `is_late=true` and penalty applied on grade; similarity check (feature on, mock adapter) → `similarity_pct` set.
10. Quiz: paper generated from blueprint (10 MCQ) → freeze → quiz publish (10 min, 1 attempt) → `student.1` start → answers autosave → submit → auto score; second attempt → 409; `push_to_marks` → internal mark; `quizzes.auto_submit` closes an expired attempt.
11. Discussions: thread/post/upvote/mark-answer; faculty lock thread → student post → 409.
12. Lesson plan: 12 items; deliver item 3 against session S → `delivered`, `actual_session_id` set; deviation report shows planned vs actual dates; course file checklist completion % updates when marks locked/plan delivered; HOD audit.
13. Projects: create dissertation project with 3 members and guide `faculty.1`; review 1 with rubric → marks to `project_review` component; `student.1` `GET /projects/me` → own; member from another offering → 422.
14. Question bank: bilingual MCQ with 4 options (1 correct) → 201; import CSV 50 questions (2 bad) → report; blueprint with CO distribution → generate paper → print bilingual → PDF; freeze → edit → 409.
15. Visibility: `GET /offering-assessments/{id}/marks` as `parent.1` for ward's offering → 200 read-only row of the ward; `hod.ece` → 404.

## 13.12 UI verification
1. Marks grid keyboard entry (Tab/Enter navigation), question-wise mode, import XLSX, validation, submit → stepper → HOD verify screen → exam cell lock; change request dialog and timeline.
2. CO heatmap preview updates from question-wise marks; CO-PO matrix editor with justification popovers; PO import template.
3. LMS pages: content upload/SCORM play, assignment rubric grading, quiz taking with timer/autosave (refresh keeps answers), discussion moderation, announcements to students (bell).
4. Lesson plan tick-off from sessions; deviation report; course-file checklist with audit.
5. Projects page: members, reviews with rubric → marks appear in the student's marks page.
6. Question bank editor with KaTeX preview; blueprint → generate → print bilingual.
7. Mobile: faculty marks numpad entry + submit; student assignment submit via camera; quiz attempt with offline-safe autosave.

## 13.13 Deliverables checklist
- [ ] Offering assessments (instantiate, question→CO map, marks bulk/import/export, submit/verify/lock/reopen, auto-lock), CIA consolidation (best-of/scaling, approve/lock/university submission), change requests workflow
- [ ] OBE definitions (PEO/PO/PSO/CO, matrices, template import, validation)
- [ ] LMS-lite (modules/contents/progress, assignments+rubrics+late penalty+similarity, quizzes from question bank with autosave/auto-score/proctoring options/push-to-marks, announcements, discussions, online links), lesson plans + deviation + course files, projects + reviews → marks, question bank/blueprints/paper builder/study materials (Orbit carry-over)
- [ ] Single write path into `internal_marks`; events/jobs/Beat/workflow; visibility links; demo seed `--only assessment`
- [ ] Web + mobile; `scripts/verify/13_assessment.ps1` passes; UI checklist done; guards green; commit `feat(phase-13): internal assessment, OBE definitions, LMS, projects`
