# PHASE 16 — POST-RESULT SERVICES

## Pre-Requisite
Phases 01–15 complete (published, versioned results; scripts coded/archived; fees linkage; workflow engine; holds; committees table exists — Phase 33 adds the governance UI).

## Objective
Everything students and the exam office do **after** a result is published: retotaling / photocopy / revaluation / challenge-valuation requests with fees, minimum-delta rules, refunds and **new result versions**; the supplementary/arrear loop (session creation from open arrears, registration reuse from Phase 14); **malpractice** inquiry → hearing → punishment → appeal with debarment that feeds eligibility and results; withheld results and their release; detention and readmission; **transcripts** (provisional/consolidated/final/duplicate/migration) with fees, workflow and verification; rank lists and medals; result correction requests.

## Feature keys
`results.revaluation`, `results.photocopy`, `results.supplementary`, `results.malpractice`, `results.transcripts`, `results.rank_lists` (on, standard); `results.challenge_valuation` (off, professional); `exams.reval` permissions ride on `results.revaluation`.

## Visibility rules
| Role | Reval/photocopy requests | Malpractice cases | Transcripts | Rank lists |
|---|---|---|---|---|
| student | **S** (raise, pay, track, download photocopy) | S (own case: notice, statement, decision, appeal) | S (request, pay, download) | S (own rank) |
| parent | W (read) | W (read) | W (read) | W |
| evaluator (reval) | O (assigned reval scripts, dummy numbers) | — | — | — |
| exam_cell | A (`exams:reval`: assign, process) | A (`exams:malpractice`: register, inquiry) | A (generate) | A |
| controller_of_examinations | A (decide, refunds approve) | A (decide punishment) | A (issue) | A (publish) |
| discipline_committee / committee members | — | O (cases assigned to their committee) | — | — |
| registrar | A (read) | A (read) | A (approve/issue) | A |
| hod | D (read) | D (read) | — | D |
| accountant | fee status | fines | fee status | — |
| auditor | A (read) | A (read) | A (read) | A (read) |

## 16.1 Database tables
Section 16: `reval_requests, malpractice_cases, transcripts`; uses `answer_scripts, valuation_assignments, script_valuations, script_final_marks, result_processing_runs, student_course_results, student_term_results` (§15–16), `exam_sessions, exam_registrations, exam_registration_items` (§15), `student_arrears` (§11), `student_holds`, `student_term_records`, `student_program_enrollments` (§8), `committees` (§30), `fee_invoices` (§13), `issued_documents` (§25 — created by Phase 26; until then transcripts store the PDF URL and verification token columns directly). Expected delta migration: none.

## 16.2 Alembic migration
`0016_phase16_post_result_seed.py` — data-only: notification templates (`results.reval_decided`, `results.malpractice_notice`, `results.transcript_ready`), malpractice punishment scale template (IN pack: warning / cancel paper / cancel session / debar 1–4 terms / expel) in `platform_settings['malpractice_scale']`, transcript templates (platform `document_templates(transcript)`). Demo seed `--only post_result`: 25 reval requests (mixed types/states, 8 marks changed), a supplementary session for open arrears, 5 malpractice cases across stages (one debarred), 12 transcript requests, rank lists for batch 2024 term N.

## 16.3 Models — `models/post_result.py`
`RevalRequest`, `MalpracticeCase`, `Transcript`; helper value objects `RankListEntry` (computed, not persisted; optional cache in `platform_settings`-free materialized view `rank_lists_mv` refreshed by job). Enums: `RevalType` (retotaling|photocopy|revaluation|challenge), `RevalStatus`, `MalpracticeCategory`, `Punishment`, `MalpracticeStatus`, `TranscriptType`, `TranscriptStatus`.

## 16.4 Schemas — `app/schemas/post_result.py`
`RevalEligibilityResponse{items:[{result_row, allowed_types[], fees{…}, window_ends_at}]}`, `RevalCreate{exam_registration_item_id, request_type}` (+ bulk), `RevalResponse` (status, fee, original/revised, delta, refund_due, photocopy url when ready), `RevalAssignRequest{evaluator_staff_id|external, due_at}`, `RevalDecision{revised_marks?, decision: marks_changed|no_change|rejected, remarks}`, `RevalRunRequest{session_id}` (bulk apply → result run), `SupplementaryCreateRequest{term_id, exam_kind: supplementary|arrear, from_session_id?, fee_rules}` + `SupplementaryPreview{students, papers}`, `MalpracticeCaseCreate` (from Phase 14 report or manual), `InquiryUpdate{committee_id, hearing_at, invalidate_paper?}`, `StudentStatementSubmit{text, attachments}`, `MalpracticeDecision{punishment, debar_terms?, decision_text, cancel_items[]}`, `AppealCreate{grounds, attachments}`, `AppealDecision`, `WithheldReleaseRequest{result_ids[], reason}`, `DetentionRow`, `ReadmissionRequest{enrollment_id, term_id, reason}`, `TranscriptRequestCreate{transcript_type, copies, delivery, purpose}`, `TranscriptResponse`, `TranscriptIssueRequest`, `RankListQuery{batch_id, term_id|cumulative, program_id, top_n}`, `RankListEntry{rank, student_masked, sgpa|cgpa, credits}`, `MedalAwardCreate{batch_id, medal, student_program_enrollment_id, citation}`, `CorrectionRequestCreate{result_id, reason, evidence}`.

## 16.5 Repository
`reval_repository.py` (`module="exams"` bespoke `reval`; self predicate via item → enrolment; evaluator ownership via `valuation_assignments`; college scope), `malpractice_repository.py` (self; committee-member ownership through `committee_members.user_id`), `transcript_repository.py` (`module="results"` bespoke `transcript`; self/wards), `rank_repository.py` (aggregate queries over current published `student_term_results` / enrolments; ties by CGPA then credits then registration number).

## 16.6 Services
- `reval_service.py`
  1. `eligibility(enrollment, session)`: published rows of the session with `result_status ∈ (pass, fail)` and `paper_type='theory'` (practicals/projects/internal not revaluable per rule), within `rules.reval.window_days` after publication; allowed types by regulation (`retotaling`, `photocopy`, `revaluation`, `challenge` when `results.challenge_valuation` and a prior revaluation exists); fees per type from `rules.reval.*`.
  2. `create(item, type)` (student/parent; `Idempotency-Key`): one request per (item, type); invoice `source_type='reval_request'` → `fee_pending`; on payment → `fee_paid`; photocopy → job produces watermarked scan (`answer_scripts.scan_url` or a scanning task for exam cell) → `evaluated` with url; retotaling → exam cell recheck of question-wise sums → decision; revaluation → **assign** to a different evaluator (not V1/V2; dummy-number projection reused) → `script_valuations(round=9x)` → `decide`: `delta = revised − original`; applied only when `|delta| ≥ rules.reval.min_delta_to_apply` → `marks_changed` else `no_change`; `refund_due` when changed and `rules.reval.refund_if_changed` → Phase 12 refund request auto-created; challenge → external panel (2 evaluators) → average.
  3. `apply(session)` (COE): all `marks_changed` requests → `result_service.create_run(run_type='revaluation')` → compute → verify → approve → publish creates **new versions** (Phase 15) for affected rows; grade cards regenerated; arrears/standing updated (pass after reval clears the arrear); emits `results.reval_decided` per student.
  4. Deadlines and reminders; status machine `submitted → fee_paid → assigned → evaluated → marks_changed|no_change|rejected → closed`.
- `supplementary_service.py` (`results.supplementary`): `preview(term, kind)` → students with open arrears (`student_arrears.status='open'`) and courses → `create_session` (Phase 14 service, `exam_kind='supplementary'|'arrear'`, papers only for those courses, `is_arrear_only`) → registrations built via Phase 14 (`attempt_type='arrear'`); results published through Phase 15 with `run_type='supplementary_merge'` (term results re-versioned, CGPA per attempt policy, arrears cleared).
- `malpractice_service.py`
  1. Cases from Phase 14 reports (`reported`) or registered manually; `case_number` from sequence; item `status='malpractice'`; result row for that item computed as `withheld` until decided (Phase 15 anomaly `MALPRACTICE_PENDING`).
  2. Inquiry: assign committee (`committees(type='discipline'|'custom')` or the exam-cell panel), notice to student + guardian (`results.malpractice_notice`), student statement (portal), hearing scheduling, evidence.
  3. Decision (COE / committee chair): punishment per scale — `none` (release withheld → recompute item), `warning`, `cancel_paper` (item `result_status='malpractice'`, grade `MP`, arrear opened), `cancel_session` (all items of the session `MP`), `debar_terms` (`debar_until_term_id`; Phase 14 registration and Phase 11 eligibility mark `debarred` for sessions up to that term; `exam` hold placed until then), `expel` (Phase 07 status `expelled`, `all` hold); decision text; notifications; correction run (`run_type='correction'`) publishes new versions for affected rows.
  4. Appeal (student, within window) → `appealed` → appeal committee decision → `appeal_decided` (uphold/modify) → adjustments via another correction run; `closed`.
- `withheld_service.py`: list withheld rows with reasons (`WITHHELD_HOLD`, `MALPRACTICE_PENDING`, fee due); auto-release when the cause clears (hold released, fee paid, case decided `none`) via consumers → correction run per affected student; manual release with reason (COE).
- `detention_service.py`: detained students per term (from eligibility/results); readmission request (`students.readmission` workflow: registrar) → new term record for the same term in the next year (`entry_type='readmission'` on enrolment history), fee structure reassignment (Phase 12), registration reopened for that term (Phase 09 window `readmission`).
- `transcript_service.py` (`results.transcripts`): request (student/alumni/registrar) with type/copies/delivery → invoice (`source_type='transcript'`) → workflow `transcripts.issue` (registrar verifies dues: `no_dues` for `final`; `transcript|all` holds block) → generate PDF from template (all published current rows across terms, SGPA/CGPA, class, credits; provisional when degree not yet awarded; migration transcript includes the migration certificate reference) → `verification_token` (QR → `/verify/{token}`) → issue (email/pickup/post; duplicate copies numbered); reissue with new token on later result versions (old token shows "superseded").
- `rank_service.py` (`results.rank_lists`): term rank (SGPA) and cumulative rank (CGPA) per batch/programme over **current published** rows; ties: CGPA → credits earned → earlier registration number; exclude students with active arrears from "class rank with distinction" when `rules.class_rules.first_attempt_only`; publish rank list (masked names for public if allowed); **medals** (gold/silver/bronze per programme-batch) as `student_achievements(category='academic')` rows (Phase 27 table exists) + certificate (Phase 26) — created here, displayed later.
- `correction_service.py`: staff-raised correction requests on published rows (typo/mapping errors) → workflow `marks.change` target `course_result` (Phase 13) → COE → correction run.

## 16.7 Events / jobs
Emits: `reval.requested/fee_paid/assigned/evaluated/decided/applied`, `photocopy.ready`, `supplementary.session_created`, `malpractice.registered/notice_sent/hearing_scheduled/decided/appealed/appeal_decided/closed`, `results.withheld_released`, `student.readmitted`, `transcript.requested/issued`, `rank_list.published`, `medal.awarded`. Consumers: notifications (all student-facing steps), Phase 12 (`fees.payment_received` → reval/transcript transitions; refunds), Phase 14 (debar → registration `debarred`), Phase 11 (debar → eligibility), Phase 15 (correction/reval/supplementary runs), Phase 07 (holds/expulsion/readmission), Phase 18 (transcript for degree bundle), Phase 27 (medals as achievements). Jobs: `reval.photocopy_scan`, `reval.apply_run`, `supplementary.create`, `transcripts.generate`, `rank_lists.compute`, `malpractice.notice_pdf`. Beat: `reval.window_close` (daily), `reval.due_reminders`, `malpractice.hearing_reminders`, `withheld.auto_release` (hourly), `transcripts.reminders`. Workflows: `transcripts.issue`, `students.readmission`, `marks.change` (reuse), `malpractice.appeal` (committee).

## 16.8 Endpoints
```
GET      /api/v1/reval/eligibility?session_id= [exams:self] {results.revaluation}
POST     /api/v1/reval-requests (Idempotency-Key) · GET /reval-requests/me · GET /reval-requests/{id} · GET /reval-requests/{id}/photocopy.pdf [exams:self] {results.photocopy}
GET      /api/v1/exam-sessions/{id}/reval-requests?type&status · POST /reval-requests/{id}/assign · POST /reval-requests/{id}/retotal · POST /reval-requests/{id}/decide · POST /reval-requests/{id}/reject [exams:reval]
GET      /api/v1/valuation/me/reval-scripts · POST /reval-requests/{id}/valuation [exams:evaluate (assigned)]
POST     /api/v1/exam-sessions/{id}/reval/apply (job → run) [results:compute|approve] {results.revaluation}
POST     /api/v1/exam-sessions/{id}/challenge-panel · POST /reval-requests/{id}/challenge/decide [exams:reval] {results.challenge_valuation}
POST     /api/v1/exam-sessions/supplementary/preview · POST /exam-sessions/supplementary (job) [exams:manage] {results.supplementary}
GET/POST /api/v1/malpractice-cases · GET /malpractice-cases/{id} · POST /malpractice-cases/{id}/inquiry · /notice · /hearing · /decide · /close [exams:malpractice] {results.malpractice}
GET      /api/v1/malpractice-cases/me · POST /malpractice-cases/{id}/statement · POST /malpractice-cases/{id}/appeal [exams:self]
POST     /api/v1/malpractice-cases/{id}/appeal/decide [exams:malpractice (committee)]
GET      /api/v1/results/withheld?session_id · POST /results/withheld/release [results:approve]
GET      /api/v1/terms/{id}/detained · POST /readmissions · POST /readmissions/{id}/approve|reject [students:manage|self]
GET      /api/v1/transcripts/types (fees) · POST /transcripts/requests (Idempotency-Key) · GET /transcripts/me · GET /transcripts/{id}/download [results:transcript|self] {results.transcripts}
GET      /api/v1/transcripts/requests?status · POST /transcripts/{id}/approve|generate|issue|reissue|cancel [results:transcript]
GET      /api/v1/results/rank-lists?batch_id&term_id|cumulative&program_id&top_n · POST /results/rank-lists/publish · GET /public/results/rank-lists/{id} [results:view_all|public] {results.rank_lists}
GET/POST /api/v1/results/medals · POST /results/medals/{id}/revoke [results:approve]
POST     /api/v1/results/corrections · GET /results/corrections?status [marks:correct|results:verify]
GET      /api/v1/verify/{token}                                           → transcript verification {public}
```

## 16.9 Frontend
- `/admin/exams/sessions/:id` tabs **Revaluation** (requests table by type/status, assign evaluator, retotal panel, decide dialog with original/revised/delta and rule feedback, photocopy scan upload, bulk apply → run link), **Malpractice** (case list, case page: report, evidence gallery, notice PDF, student statement, hearing scheduler, decision dialog with punishment scale and affected items, appeal timeline), **Withheld** (rows with reasons, release), **Supplementary** (preview arrears → create session wizard).
- `/admin/results/transcripts` (requests queue with dues/hold checks, generate, issue, reissue; templates by type), `/admin/results/rank-lists` (compute, preview with ties explanation, publish, medals dialog), `/admin/results/corrections`, `/admin/students/detained` (per term, readmission approvals).
- Student portal `/student/exams/reval` (eligible items with type chips and fees, request & pay, status timeline, photocopy download), `/student/exams/malpractice` (notice, statement form, decision, appeal), `/student/transcripts` (request with type/copies/delivery, pay, download, verify QR), `/student/results` gains "revised" markers and rank; alumni portal transcript request (Phase 29 reuses).
- Nav: EXAMINATIONS › Revaluation, Malpractice, Withheld, Supplementary, Transcripts, Rank lists & medals, Corrections; STUDENTS › Detained & readmission.

## 16.10 Mobile
Student: Exams › Revaluation (request & pay, timeline, photocopy view), Malpractice (notice/statement/appeal), Transcripts (request/pay/download/share), Results rank badge; Parent: read; Evaluator: reval scripts entry (dummy numbers); COE/exam cell: reval queue decisions, malpractice case decisions (hearing schedule), withheld release, transcript issue approvals.

## 16.11 API verification — `scripts/verify/16_post_result.ps1`
Roles: `coe`, `exam.cell`, `faculty.5` (reval evaluator), `faculty.1` (original evaluator — must be excluded), `registrar`, `committee.sec`, `student.1`, `student.fail` (failed course), `student.mp` (malpractice reported), `parent.1`, `accountant`, `alumni.1`, public.
1. Seed `--only post_result`; `GET /reval/eligibility` as `student.1` → theory items within window with allowed types and fees; a practical item excluded; after `window_days` (dev time shift) → empty.
2. Revaluation: `POST /reval-requests {item, revaluation}` → `fee_pending` + invoice `source_type=reval_request`; duplicate → 409; pay (dev) → `fee_paid`; assign to `faculty.1` → 409 `EVALUATOR_CONFLICT`; to `faculty.5` → `assigned`; `faculty.5` `GET /valuation/me/reval-scripts` → dummy number only; submit revised marks +3 (below `min_delta_to_apply=5`) → decide → `no_change`, `refund_due=false`; second request for another item revised +8 → `marks_changed`, `refund_due=true` → refund request exists (Phase 12).
3. Retotaling: request → exam cell `retotal` finds a sum error → `marks_changed` delta 2 (retotaling ignores min-delta per rule flag) ; photocopy: request → scan job (dev mock) → `photocopy.pdf` watermarked with student reg no; other student's request → 404.
4. Apply: `POST /exam-sessions/{id}/reval/apply` → revaluation run → verify/approve/publish (Phase 15 chain) → new version rows for changed items only; `GET /results/me` shows `revised`; grade card regenerated; a failing course that now passes → `student_arrears` cleared.
5. Challenge (feature on): after a revaluation, challenge request → panel of 2 → average applied when `|delta| ≥ min`.
6. Supplementary: preview → students with open arrears and their courses; create → Phase 14 session `exam_kind=supplementary` with `is_arrear_only` papers; `student.fail` registration auto-built with `attempt_type=arrear`; run through Phase 14/15 dev shortcuts → `supplementary_merge` publish → CGPA per `cgpa_attempt_policy`, arrear `cleared`.
7. Malpractice: case for `student.mp` exists (`reported`) and its result row is `withheld` (`MALPRACTICE_PENDING`); inquiry assign committee (`committees` dev row) + notice → student + guardian notifications; `student.mp` submits statement; hearing scheduled; decision `cancel_paper` → item `MP`, arrear opened, correction run publishes; decision `debar_terms=2` on another case → `debar_until_term_id` set, `exam` hold placed, Phase 14 registration for the next session → `debarred`, Phase 11 eligibility recompute → `debarred`; appeal within window → committee `appeal/decide` modify to `warning` → correction run restores marks, hold released; `student.1` reading another student's case → 404.
8. Withheld: list shows reasons; release a `WITHHELD_HOLD` row after the hold is released (Beat auto) → correction run → visible to student.
9. Detention/readmission: detained list for the term; readmission request → registrar approve → new term record (readmission), fee reassignment event, registration window `readmission` available.
10. Transcripts: `POST /transcripts/requests {consolidated, copies:2, delivery:digital}` as `student.1` → invoice; pay → workflow to registrar; with an open `transcript` hold → approve → 409 `HOLD_BLOCKED`; release → approve → generate → PDF with all published terms, CGPA; issue → download; `GET /verify/{token}` (public) → summary + hash; after a later result version → old token → `superseded`, reissue → new token; `alumni.1` request `final` → requires no-dues cleared (Phase 12) → blocked until cleared; `parent.1` download ward transcript → 200; `accountant` sees fee status only.
11. Rank lists: compute term rank for batch 2024 → ties resolved (assert two equal-SGPA students ordered by CGPA then credits); publish → student sees own rank; public masked list (when allowed); medals: award gold to rank 1 → `student_achievements` row; revoke.
12. Corrections: faculty raises correction on a published row → workflow HOD → COE → correction run → new version; audit trail complete.
13. Auditor reads all queues; writes 403.

## 16.12 UI verification
1. Student reval page: eligible items with fees, request & pay flow, timeline, photocopy download; malpractice notice/statement/appeal pages; transcript request/pay/download with QR verify.
2. Session Revaluation tab: assign/retotal/decide dialogs with rule feedback; bulk apply → run; Malpractice case page with evidence, hearing scheduler, punishment scale, appeal timeline; Withheld tab release; Supplementary wizard.
3. Transcript queue: dues/hold checks visible, generate/issue/reissue; rank lists page with ties tooltip and medals dialog; corrections queue; detained/readmission page.
4. Mobile: student reval request & pay, transcript share, malpractice statement; evaluator reval entry; COE decisions.

## 16.13 Deliverables checklist
- [ ] Revaluation family (eligibility/window/fees, retotaling, photocopy scan, revaluation with evaluator exclusion and min-delta, challenge, refunds, bulk apply → versioned run), supplementary loop, malpractice lifecycle (inquiry/notice/statement/hearing/decision/appeal/debarment/expulsion effects), withheld release, detention/readmission, transcripts (fees, workflow, holds/no-dues, PDF, verify, reissue), rank lists/medals, corrections
- [ ] Visibility registrations; events/jobs/Beat/workflows; demo seed `--only post_result`
- [ ] Web + mobile; `scripts/verify/16_post_result.ps1` passes; UI checklist done; guards green; commit `feat(phase-16): post-result services`
