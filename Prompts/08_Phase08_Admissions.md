# PHASE 08 — ADMISSIONS

## Pre-Requisite
Phases 01–07 complete (students service exists: `student_service.create(source="admission")`).

## Objective
Higher-ed admissions end-to-end: admission cycles per level with programme intakes, entrance sources and merit formulas; **seat matrix** (quota × category); public multi-preference online application with documents and application fee; verification queue; merit lists with configurable tie-breaks; **counselling rounds with reservation-aware seat allotment** (GEN-first, horizontal PwD, de-reservation policy); offers; accept-and-pay; admit → student + enrolment + registration number; lateral entry; import from state counselling CSV; withdrawal/refund rules; enquiry/lead CRM; open enrolment for non-degree learners; applicant portal.

## Feature keys
`admissions.cycles`, `admissions.online_application`, `admissions.merit_lists`, `admissions.seat_matrix`, `admissions.document_verification`, `admissions.offers` (on, starter); `admissions.counselling_allotment`, `admissions.entrance_import`, `admissions.lateral_entry`, `admissions.enquiry_crm`, `admissions.refunds` (on, standard); `admissions.open_enrolment` (off, standard); `website.enquiry` (on).

## Visibility rules
- Applicants: `admissions:view_all` for admissions_officer/registrar/institution_admin (@institution or @college); `college_admin` @college; `hod` sees applicants with a preference for their department's programmes (read); **applicant** sees own application (`applicant` role, time-boxed until cycle archive); accountant sees application-fee invoices (Phase 12).
- Enquiries: assigned counsellor (ownership `assigned_to`) + `admissions:view_all`.
- Cycles/seat matrix/merit lists: readable by all staff with `admissions:view`; public endpoints expose published merit lists (masked: application number + rank only) when the cycle setting allows.

## 08.1 Database tables
Section 10: `admission_cycles, admission_cycle_programs, seat_matrix, applicants, applicant_preferences, applicant_document_verifications, merit_lists, merit_list_entries, counselling_rounds, seat_allotments, admission_offers, enquiries` (+ `student_transfers` from Phase 07, `website_enquiries` §32) — exist. Expected delta migration: none.

## 08.2 Alembic migration
`0008_phase08_admissions_seed.py` — data-only: default `form_config` template (steps, fields, required documents by level) in `platform_settings['admission_form_template']`; IN pack quota/category lists already in pack. Demo seed `--only admissions`: UG 2026 cycle with B.Tech CSE (intake 120) and MBA (60), seat matrix, 300 applicants (mixed categories/quotas, 20 PwD, 10 lateral), 40 verified, entrance scores, 2 counselling rounds.

## 08.3 Models — `models/admissions.py`
`AdmissionCycle`, `AdmissionCycleProgram`, `SeatMatrix`, `Applicant`, `ApplicantPreference`, `ApplicantDocumentVerification`, `MeritList`, `MeritListEntry`, `CounsellingRound`, `SeatAllotment`, `AdmissionOffer`, `Enquiry`. Enums: `CycleLevel`, `CycleStatus`, `EntranceSource`, `Quota`, `ApplicantStatus`, `DocVerificationStatus`, `MeritListStatus`, `RoundStatus`, `AllotmentStatus`, `OfferType`, `EnquiryStage`.

## 08.4 Schemas — `app/schemas/admissions.py`
`CycleCreate/Update/Response` (+ `form_config`, `required_documents`, `de_reservation_policy`), `CycleProgramIn/Out` (intake, lateral intake, entrance source, eligibility rules JSON, merit formula, tie-breaks), `SeatMatrixReplace{rows:[{program_id, college_id, quota, category, seats}]}` + `SeatStatusResponse`, `PublicApplicationCreate` (personal, contact, category/quota/PwD, entrance details, qualifying exams, preferences[], documents refs), `ApplicantUpdate`, `ApplicantResponse` (masked for staff without `view_pii`), `ApplicantSelfResponse`, `ApplicantTimeline`, `DocumentVerifyRequest{status, remarks}`, `MeritGenerateRequest{program_ids?, quota?, category?, name}`, `MeritListResponse`, `MeritEntry`, `RoundCreate/Update`, `ChoiceFillingRequest{preferences[]}`, `AllotmentRunRequest{round_id, dry_run}` + `AllotmentSummary`, `AllotmentResponse`, `AllotmentDecision{action: accept|float|freeze|decline}`, `OfferResponse`, `AdmitRequest{section_id?, registration_number?}`, `ImportRequest{file_url, mapping, dry_run}`, `WithdrawalRequest{reason}`, `EnquiryCreate/Update/Response`, `PublicCycleInfo`.

## 08.5 Repository
`admission_repository.py` (cycles, programmes, seat matrix with `FOR UPDATE` per row during allotment), `applicant_repository.py` (`module="admissions"`; search by application number/name/phone; filters cycle/programme preference/status/category/quota/verified; self predicate `Applicant.user_id == p.id`; scope columns institution/college via preferences → `college_id`), `merit_repository.py`, `counselling_repository.py`, `enquiry_repository.py` (ownership `assigned_to`).

## 08.6 Services
- `cycle_service.py`: CRUD; `status` machine `draft → open → closed → merit_processing → counselling → completed → archived`; opening requires ≥ 1 programme and seat matrix rows summing to intake per programme (`Σ seats == intake + lateral_intake`); `form_config` validation; `public_info(slug)`.
- `application_service.py`
  1. Public create (captcha + rate limit; `applicant` user created with OTP-verified phone/email; time-boxed to cycle archive); draft save; preferences ≤ setting `max_preferences`.
  2. `submit`: validate required fields/documents per level (`form_config`), eligibility rules per preferred programme (`eligibility_rules` JSON evaluated: min qualifying %, subjects, age, entrance exam required), create application-fee invoice (Phase 12 `fee_service.create_invoice(payer_type='applicant', source_type='application_fee')`; before Phase 12 use the stub service), status `submitted`; on payment event → `fee_paid` → `under_verification`.
  3. Verification queue: per-document verify/reject (`resubmit` requests notify applicant); all verified → `verified`; any rejected → `doc_rejected`.
  4. Status machine per `docs/Academic_Core_Design.md` §2b with allowed transitions map; every change → timeline + notification (`admissions.status_changed`).
  5. Withdrawal → refund rule (`admissions.refunds`: before allotment 100 % minus processing fee; after acceptance per cycle policy) → Phase 12 refund request.
  6. Import from counselling CSV (job): mapping JSON, dry-run report, creates applicants with `source='counselling_import'`, `status='allotted'` when the file carries allotment.
- `merit_service.py`: `generate(cycle, filters, name)` (job): eligible = `verified|waitlisted`; score = Σ weight × normalised field (entrance score normalised by exam max, qualifying % as is, institution test score); tie-breaks in order (`entrance_score desc`, `dob asc`, `submitted_at asc`, configurable); category rank within category; stores `formula_snapshot`; `publish` → notifications + public masked list if allowed; superseding an older list on regenerate.
- `counselling_service.py`
  1. Rounds with choice-filling windows; `choice_filling` updates `applicant_preferences` (locked outside window).
  2. `run_allotment(round, dry_run)` (job; seat rows locked `FOR UPDATE`): iterate applicants by overall merit rank; for each, walk preferences in priority order; try **GEN** seat of that (programme, college, quota) first; if none and applicant category ≠ GEN try own category seat; PwD horizontal: first fill from `pwd` supernumerary/earmarked rows; a `float` applicant from a previous round keeps the earlier seat unless upgraded; `freeze` skips; lateral applicants only against lateral seats; result rows `seat_allotments(status='allotted')`; unfilled reserved seats convert per `de_reservation_policy` only in the round flagged `is_final`; summary per programme × quota × category; dry-run returns without persisting.
  3. Decisions: `accept` → admission-fee invoice (Phase 12) → on payment `accepted`; `float`/`freeze`; `decline` releases the seat; `lapsed` after `reporting_deadline` (Beat) releases seats.
  4. `admit(applicant, section?)` (admissions_officer/registrar): requires `accepted` (fee paid) + verified docs; calls `student_service.create(source="admission")` with data mapped from the applicant (guardians, category, quota, entrance snapshot copied to `students` profile JSON), links `admitted_student_id`, increments `seat_matrix.filled`, status `admitted`; emits `applicant.admitted`.
  5. Open enrolment (`programs.is_open_enrolment`): `verified → admitted` directly on fee (learner role).
- `enquiry_service.py`: CRM stages, assignment, follow-ups (Beat reminders), conversion link to applicant; website enquiries (Phase 40) feed in; stats (source → stage funnel).
- Public seat-status / merit endpoints with caching.

## 08.7 Events / jobs
Emits: `admissions.cycle_opened/closed`, `applicant.submitted/fee_paid/verified/doc_rejected/merit_listed/allotted/accepted/declined/lapsed/withdrawn/admitted`, `merit_list.published`, `enquiry.created/stage_changed`. Consumers: notifications (every applicant status change with templates `admissions.status_changed`), Phase 12 (`fees.invoice_paid` → application/admission fee transitions), Phase 07 (`applicant.admitted` handled synchronously), search index (applicants). Jobs: `admissions.merit_generate`, `admissions.allotment_run`, `admissions.import`, `admissions.export`. Beat: `admissions.lapse_allotments` (hourly), `admissions.close_cycles` (daily), `enquiries.follow_up_reminders` (daily 09:00). Workflow: none (decisions are role-gated actions; refunds go through `fees.refund`).

## 08.8 Endpoints
```
GET/POST /api/v1/admissions/cycles · GET/PUT /admissions/cycles/{id} · POST /admissions/cycles/{id}/status [admissions:view|manage] {admissions.cycles}
GET/PUT  /api/v1/admissions/cycles/{id}/programs [admissions:manage]
GET/PUT  /api/v1/admissions/cycles/{id}/seat-matrix · GET /admissions/cycles/{id}/seat-status [admissions:view|manage] {admissions.seat_matrix}
GET      /api/v1/public/admissions/cycles · GET /public/admissions/cycles/{slug} {public}
POST     /api/v1/public/admissions/{slug}/start                       → create applicant account (OTP) + draft {public, captcha}
GET/PUT  /api/v1/applicants/me · POST /applicants/me/documents · PUT /applicants/me/preferences · POST /applicants/me/submit · POST /applicants/me/withdraw [applicant self] {admissions.online_application}
GET      /api/v1/applicants/me/timeline · GET /applicants/me/allotment · POST /applicants/me/allotment/{id}/decision {accept|float|freeze|decline} [applicant self]
GET      /api/v1/admissions/applicants?cycle_id&status&program_id&category&quota&search [admissions:view_all]
GET/PUT  /api/v1/admissions/applicants/{id} · GET /admissions/applicants/{id}/timeline [admissions:view_all|update]
POST     /api/v1/admissions/applicants/{id}/documents/{doc_type}/verify [admissions:verify] {admissions.document_verification}
POST     /api/v1/admissions/applicants/{id}/status                      → manual transition with reason [admissions:manage]
POST     /api/v1/admissions/cycles/{id}/merit-lists (generate job) · GET /merit-lists?cycle_id · GET /merit-lists/{id} · POST /merit-lists/{id}/publish [admissions:merit] {admissions.merit_lists}
GET      /api/v1/public/admissions/{slug}/merit-lists/{id}              → masked public list {public}
GET/POST /api/v1/admissions/cycles/{id}/rounds · PUT /rounds/{id} · POST /rounds/{id}/status [admissions:allot] {admissions.counselling_allotment}
POST     /api/v1/admissions/rounds/{id}/run-allotment?dry_run= (job) · GET /rounds/{id}/allotments · GET /rounds/{id}/summary [admissions:allot]
POST     /api/v1/admissions/applicants/{id}/offer · GET /admissions/offers?cycle_id [admissions:manage] {admissions.offers}
POST     /api/v1/admissions/applicants/{id}/admit                        → student created [admissions:admit]
POST     /api/v1/admissions/applicants/import?dry_run= (job) · GET /admissions/applicants/export [admissions:import|export] {admissions.entrance_import}
GET/POST /api/v1/admissions/enquiries · PUT /enquiries/{id} · POST /enquiries/{id}/assign · POST /enquiries/{id}/convert · GET /enquiries/stats [admissions:view|create|update] {admissions.enquiry_crm}
POST     /api/v1/public/enquiries {public, captcha}
```

## 08.9 Frontend
- Public applicant portal `/apply/:cycle` (steps: account (OTP) → personal → qualifications/entrance → preferences (drag order, eligibility hints per programme) → documents (upload with type) → review → pay → done), `/apply/:cycle/status` (timeline, resubmit documents, allotment card with accept/float/freeze/decline and pay), public `/admissions` listing and `/admissions/:slug/merit/:id`.
- Admin `/admin/admissions/cycles` and `/admin/admissions/cycles/:id` (tabs **Programmes & intake** | **Seat matrix** (grid quota × category per programme with totals vs intake) | **Applicants** (DataTable + status filters + bulk actions) | **Verification queue** (document viewer side-by-side, verify/reject with remarks) | **Merit lists** (generate wizard: scope, name → job → table; publish) | **Counselling rounds** (round editor; run allotment dry-run → summary matrix → confirm; allotments table with decisions) | **Offers** | **Seat status** (filled/vacant heatmap) | **Reports**), `/admin/admissions/applicants/:id` (timeline, documents, actions: status, offer, admit with section picker), `/admin/admissions/enquiries` (kanban by stage, assignment, follow-ups, convert).
- Nav: ADMISSIONS › Cycles, Applicants, Verification, Merit & Counselling, Enquiries.

## 08.10 Mobile
Applicant flows stay on the responsive web portal (PWA). Admissions officer shell: **Applicants** (search, detail, document verify with camera preview), **Enquiries** (assigned to me, call/WhatsApp buttons, stage update).

## 08.11 API verification — `scripts/verify/08_admissions.ps1`
Roles: `admissions`, `registrar`, `hod.cse`, `college.admin.b`, `student.1`, public, applicant accounts created during the run.
1. Seed `--only admissions`; `GET /admissions/cycles` as `student.1` → 403; as `hod.cse` → 200.
2. Open cycle with seat matrix Σ ≠ intake → 409; fix → `open`; `GET /public/admissions/cycles/{slug}` → programmes + fee + windows.
3. Public start with OTP (mock) → applicant account; `PUT /applicants/me` + preferences (3) + documents; submit without required marksheet → 422 listing missing; add → 200 `submitted`; invoice created (`payer_type=applicant`); simulate payment event (`POST /_dev/fees/pay/{invoice}`) → `fee_paid`.
4. Verification: `admissions` verifies 2 docs, rejects 1 with remarks → applicant `doc_rejected`; applicant resubmits → `under_verification`; verify → `verified`; applicant timeline has all steps; notifications logged.
5. Eligibility: applicant with qualifying % below rule → submit 422 `RULE_VIOLATION` `NOT_ELIGIBLE` for that preference (others allowed) when `strict_eligibility=true`.
6. Merit: generate for B.Tech → job → list with ranks; tie: two applicants equal score → ordered by `dob asc`; category ranks present; publish → public masked list shows application number + rank only; regenerate → previous `superseded`.
7. Allotment dry-run round 1: summary shows filled per quota × category; assert an OBC applicant with GEN-rank inside GEN seats is allotted a **GEN** seat; a PwD applicant gets a PwD earmarked seat; lateral applicant only lateral seats; run → `seat_allotments` rows; seat rows `filled` updated under lock (run twice concurrently → no over-allotment: total filled ≤ seats).
8. Decisions: applicant `accept` → admission-fee invoice; pay → `accepted`; another `float` → retains seat and is considered for upgrade in round 2 (assert upgrade when a higher preference frees); `decline` → seat released; Beat `lapse_allotments` after deadline → `lapsed` + seat released.
9. Round 2 `is_final` with de-reservation policy → unfilled SC seats converted to GEN per policy; summary shows conversions.
10. Admit: `POST /admissions/applicants/{id}/admit` before fee → 409; after → 201 with `student_id`, registration number, user created; applicant `admitted`; `seat_matrix.filled` incremented; `GET /students/{id}` shows category/quota copied; admitting again → 409.
11. Import counselling CSV (100 rows, 5 bad) dry-run → report; apply → applicants `allotted` with `source=counselling_import`.
12. Withdrawal after allotment → refund request created (Phase 12) with policy amount; before → full minus processing fee.
13. Enquiries: public `POST /public/enquiries` (captcha mock) → row; assign to `admissions`; stage → `applied` via convert links applicant; stats funnel counts.
14. Visibility: `college.admin.b` sees only applicants with preferences for college B; `hod.cse` sees CSE-preference applicants read-only (`PUT` → 403).

## 08.12 UI verification
1. Applicant portal end-to-end on mobile viewport: OTP, steps, uploads, payment (mock), status page with timeline and allotment decision buttons.
2. Cycle workspace: seat matrix grid validation, verification queue with document viewer, merit generation and publish, counselling dry-run summary → run, allotments table with decisions and upgrades, seat-status heatmap.
3. Applicant detail: timeline, manual status change with reason, offer letter preview, admit dialog with section picker → navigates to the new student page.
4. Enquiries kanban drag; convert to applicant.
5. Public merit list page masked.
6. Mobile admissions officer: applicant search + document verify; enquiry stage update.

## 08.13 Deliverables checklist
- [ ] Cycles/programmes/seat matrix; public application + applicant accounts; verification; status machine + timeline; merit lists (formula, tie-breaks, publish, public masked); counselling rounds with reservation-aware allotment (GEN-first, PwD horizontal, float/freeze/upgrade, lapse, de-reservation); offers; admit → student; open enrolment; import/export; withdrawal/refund policy; enquiries CRM
- [ ] Events/jobs/Beat; notifications for every applicant transition; demo seed `--only admissions`
- [ ] Web pages + mobile screens; `scripts/verify/08_admissions.ps1` passes; UI checklist done; guards green; commit `feat(phase-08): admissions`
