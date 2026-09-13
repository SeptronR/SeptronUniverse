# PHASE 18 — DEGREES, CONVOCATION & DIGITAL CREDENTIALS

## Pre-Requisite
Phases 01–17 complete (published results with credits/CGPA/arrears, holds, no-dues from Phase 12, transcripts from Phase 16, ABC ledger rows from Phase 15, governance `resolutions` table exists — Phase 33 adds its UI; document templates from Phase 26 are not yet available: degree/provisional templates use platform defaults until then).

## Objective
Close the student lifecycle: a **degree eligibility engine** (credit buckets, backlogs, CGPA, duration, mandatory non-credit, holds, dues), NEP exit awards (certificate/diploma) from Phase 07 exits, **convocation** events with registrations (in-person/absentia, fee, gown), degree/diploma/certificate awards with serial numbers, signed QR and optional eSign, provisional certificates, **digital credentials** pushed to DigiLocker/NAD and **ABC** credit ledger pushes (adapters with mocks), the public verification portal, revocation/reissue, and the graduation → alumni transition.

## Feature keys
`degrees.eligibility`, `degrees.convocation`, `degrees.certificates`, `degrees.provisional`, `degrees.verification_portal` (on, standard); `degrees.esign` (off, professional; depends `integrations.esign`); `degrees.digilocker_nad` (off, professional; depends `integrations.digilocker_nad`); `degrees.abc_push` (off, professional; depends `academics.abc_apaar`); `academics.nep_exit_reentry` (on).

## Visibility rules
| Role | Eligibility checks | Convocation | Awards / certificates | Digital credentials |
|---|---|---|---|---|
| student | **S** (own eligibility, reasons) | S (register, pay, gown) | S (own award, download) | S (push status) |
| parent | W | W | W | — |
| alumni | S | S (past) | S | S |
| registrar | A (run, review, override with reason) | A (manage) | A (award batch, issue, reissue, revoke) | A |
| controller_of_examinations | A (read; award recommendation) | — | A (award) | — |
| vice_chancellor / principal | A | A | A (council approval) | — |
| hod / dean | D / F (read) | — | D / F (read) | — |
| accountant | — | fee status | — | — |
| college_admin | C | C | C (recommend; university issues) | — |
| iqac | A (aggregates: GPH/GPHD) | A | A (counts) | — |
| auditor | A (read) | A (read) | A (read) | A (read) |

## 18.1 Database tables
Section 16: `degree_eligibility_checks, convocations, convocation_registrations, degrees_awarded, digital_credentials, abc_credit_ledger`; uses `student_program_enrollments, student_term_records, student_holds` (§8), `student_course_results, student_term_results, transcripts` (§16), `no_dues_requests` (§13), `program_structure_terms, curriculum_courses, regulations` (§7), `resolutions` (§30), `issued_documents, document_serials` (§25 — Phase 26; until then the PDF URL and serial columns on `degrees_awarded` are written directly), `fee_invoices` (§13). Expected delta migration: none.

## 18.2 Alembic migration
`0018_phase18_degrees_seed.py` — data-only: platform `document_templates` for degree, diploma, certificate, provisional certificate, convocation invitation (bilingual, IN pack), notification templates (`degrees.eligible`, `degrees.awarded`, `convocation.registration_open`, `credentials.pushed`). Demo seed `--only degrees`: eligibility run for batch 2022 (final year) with 180 eligible / 15 ineligible (reasons mix), a convocation with 150 registrations (30 absentia), awards issued for 150 with serials/QR, 10 provisional certificates, digital credential rows (mock pushed/acknowledged), ABC ledger pushes, 2 NEP diploma exits, 1 revoked/reissued award.

## 18.3 Models — `models/degrees.py`
`DegreeEligibilityCheck`, `Convocation`, `ConvocationRegistration`, `DegreeAwarded`, `DigitalCredential`, `AbcCreditLedger` (model owned here; rows inserted by Phase 15). Enums: `AwardType`, `AwardStatus` (recommended|council_approved|issued|cancelled|reissued), `ConvocationStatus`, `RegistrationMode`, `CredentialEntityType`, `CredentialChannel`, `CredentialStatus`, `LedgerStatus`.

## 18.4 Schemas — `app/schemas/degrees.py`
`EligibilityRunRequest{batch_id|program_id, include_exits: bool}` + `EligibilityRunSummary{eligible, ineligible, by_reason}`, `EligibilityCheckResponse{enrollment, credits_earned/required, bucket_breakdown[], backlog_count, cgpa, min_cgpa_ok, duration_ok, dues_cleared, holds_clear, mandatory_noncredit_ok, is_eligible, reasons[]}`, `EligibilityOverride{decision, reason}`, `ConvocationIn/Out` (name, date, venue, deadline, fee, status, counts), `ConvocationRegister{mode, gown_size?, guests?}`, `ConvocationRegistrationResponse`, `AwardBatchRequest{convocation_id?, enrollment_ids[]|batch_id, award_type, date_of_award, resolution_id?}` + `AwardBatchPreview`, `DegreeAwardedResponse` (degree name, specialization, class, CGPA, date, certificate number, serial, status, pdf url, credential status), `IssueRequest{esign: bool}`, `RevokeRequest{reason}`, `ReissueRequest{reason, corrections?}`, `ProvisionalRequest{enrollment_id}`, `CredentialPushRequest{entity_type, entity_ids[], channel}` + `PushSummary`, `CredentialStatusResponse`, `AbcPushRequest{student_ids?|term_id}` + `AbcPushSummary`, `VerifyResponse{valid, entity_type, institution, holder_masked, award, issued_at, revoked, hash, version_note}`, `GraduationStatsResponse{gph, on_time_pct, by_program}`.

## 18.5 Repository
`degree_repository.py` (`module="degrees"`; self via enrolment; wards; college/department scopes; `latest_check(enrollment)`), `convocation_repository.py`, `credential_repository.py` (`module="degrees"`; by entity), `abc_ledger_repository.py` (pending rows; per student), aggregate queries for GPH/GPHD (Phase 32 metrics).

## 18.6 Services
- `eligibility_service.py`
  1. `run(scope, include_exits)` (job): for each active/completed enrolment in scope: `credits_earned` from current published `student_course_results` (`result_status='pass'` and `counts_toward_cgpa`, plus approved credit transfers), **bucket breakdown** vs `curriculum_courses.credit_bucket` requirements (Σ per bucket from the programme structure; minors/honours from baskets), `backlog_count` from `student_arrears(open)`, CGPA vs `rules.min_cgpa_for_degree`, duration ≤ `programs.max_duration_years` from admission date, mandatory non-credit courses (`course_type='mandatory_non_credit'`) passed, `holds_clear` (`graduation|all`), `dues_cleared` (Phase 12 `no_dues_requests(purpose='graduation').status='cleared'` or zero outstanding when setting allows) → `is_eligible` + `reasons[]` (`CREDITS_SHORT:<bucket>`, `BACKLOGS`, `CGPA_BELOW_MIN`, `DURATION_EXCEEDED`, `MANDATORY_NONCREDIT`, `HOLD_GRADUATION`, `DUES_PENDING`); new row per run (history); emits `degrees.eligibility_computed` → notifications to eligible/ineligible with reasons (setting).
  2. NEP exits (`include_exits`): enrolments with `status='exited_early'` (Phase 07) → eligibility for `exit_award` using `rules.exit_points[award].min_credits` → award rows `award_type = certificate|diploma`.
  3. `override(check, decision, reason)` (registrar; audited) for documented exceptions (e.g., council-approved credit equivalence).
  4. Auto-run: consumer of `results.published` for final-term batches; `no_dues.cleared` and `hold.released` re-evaluate the single enrolment.
- `convocation_service.py` (`degrees.convocation`): events (date, venue, deadline, fee, gown sizes), status `planned → registration_open → closed → completed`; registration by eligible students/alumni (in-person/absentia; guests count; fee invoice `source_type='convocation_registration'`); seat/queue lists, gown allocation report, attendance marking on the day (QR from registration), citation lists for medals (Phase 16); notifications and reminders.
- `award_service.py`
  1. `award_batch(request)` (registrar/COE): eligible enrolments only (latest check `is_eligible` or overridden) → `degrees_awarded(status='recommended')` with `degree_name/specialization/result_class/cgpa` from term results and programme, `date_of_award` (convocation date or given); `council_approved` requires `resolution_id` when `governance.minutes` is enabled (Academic Council / Executive Council resolution) else registrar approval; emits `degrees.recommended/approved`.
  2. `issue(award, esign)`: `certificate_number` + `serial_no` from `number_sequences` (`degree:{yyyy}` / `serial:degree`), PDF from template (bilingual, seal, signatures), signed QR (`/verify/{token}`), optional eSign/DSC via `ESignProvider` (`degrees.esign`) with `esign_ref`, `status='issued'`, `issued_documents` row when Phase 26 exists; enrolment → `completed`, student → `graduated` (Phase 07), alumni profile auto-created (Phase 29 consumer of `student.graduated`; if Phase 29 not yet built, event is queued for it), `student_term_records` untouched; emits `degrees.issued`.
  3. Provisional certificate (`degrees.provisional`): for eligible-not-yet-awarded students (fee optional) → PDF + QR; superseded when the degree is issued.
  4. Revoke (registrar + reason; e.g., malpractice appeal, error) → `cancelled`, QR verify shows revoked, credentials revoked (18.6 credentials), student status back to `completed` (not `graduated`); reissue (corrections: name spelling, class) → new serial, old marked `reissued` with reference.
  5. Bulk printing job (documents queue) with print order by serial; degree register export (statutory).
- `credential_service.py` (`degrees.digilocker_nad`): `push(entity_type, ids, channel)`: build payload per channel schema (DigiLocker Issuer: document type, holder ids (APAAR/Aadhaar-hash), metadata, PDF/JSON), `payload_hash`, adapter `CredentialDepository.push_credential` (mock acknowledges), statuses `pending → pushed → acknowledged | failed` with retries (outbox consumer), revoke on award cancel, status queries; `abc_push(scope)` (`degrees.abc_push`): pending `abc_credit_ledger` rows → `CreditBank.push_credits` in batches per student (`push_batch_id`), acknowledgements, revocation + re-push when a result version supersedes (Phase 15 emits `results.version_created`); dashboards of push health; eligibility for credential push requires `students.apaar_id` (else `SKIPPED_NO_APAAR`).
- `verification_service.py` (`degrees.verification_portal`): public `/verify/{token}` for degrees/provisionals/grade cards/transcripts/ID cards (single endpoint from Phase 07, now unified): returns validity, holder masked, award summary, issue date, revocation, `hash`, and a "superseded by newer version" note; rate-limited + captcha for bulk; employers can request an official verification letter (fee, Phase 26 certificate request).
- `graduation_stats_service.py`: GPH (graduated on time / admitted), GPHD (PhD graduated), median CGPA per programme-batch for Phase 32/36.

## 18.7 Events / jobs
Emits: `degrees.eligibility_computed`, `degrees.eligibility_overridden`, `convocation.registration_open/closed`, `convocation.registered`, `degrees.recommended/approved/issued/revoked/reissued`, `degrees.provisional_issued`, `credentials.pushed/acknowledged/failed/revoked`, `abc.pushed/acknowledged/failed`, `student.graduated`. Consumers: `results.published`/`no_dues.cleared`/`hold.released` → eligibility (this phase), notifications (eligibility, convocation, awards, credential status), Phase 07 (student status), Phase 29 (alumni profile creation), Phase 32 (metrics), Phase 12 (fees), Phase 15 (`results.version_created` → ABC revoke/re-push). Jobs: `degrees.eligibility_run`, `degrees.award_batch`, `degrees.issue_batch` (PDF/eSign), `degrees.print_batch`, `credentials.push`, `abc.push`, `degrees.register_export`. Beat: `credentials.retry_failed` (hourly), `abc.push_pending` (nightly), `convocation.reminders` (daily in window). Workflows: `degrees.council_approval` (optional: registrar → VC) when governance minutes are not used.

## 18.8 Endpoints
```
POST     /api/v1/degree-eligibility/run (job) · GET /degree-eligibility?batch_id&program_id&eligible= · GET /degree-eligibility/{id} · POST /degree-eligibility/{id}/override [degrees:view|manage] {degrees.eligibility}
GET      /api/v1/degree-eligibility/me [degrees:view (self)]
GET/POST /api/v1/convocations · PUT /convocations/{id} · POST /convocations/{id}/status · GET /convocations/{id}/registrations · GET /convocations/{id}/reports/{gowns|seating|attendance} [degrees:convocation_manage|view] {degrees.convocation}
POST     /api/v1/convocations/{id}/register (Idempotency-Key) · GET /convocations/me · POST /convocations/{id}/attendance (QR) [degrees:view (self)|convocation_manage]
POST     /api/v1/degrees/award-batch?dry_run= (job) · GET /degrees?batch_id&status&program_id · GET /degrees/{id} · POST /degrees/{id}/approve · POST /degrees/{id}/issue · POST /degrees/{id}/revoke · POST /degrees/{id}/reissue [degrees:award|issue|manage] {degrees.certificates}
POST     /api/v1/degrees/issue-batch (job) · POST /degrees/print-batch (job) · GET /degrees/register/export [degrees:issue]
GET      /api/v1/degrees/me · GET /degrees/{id}/certificate.pdf [degrees:view (self)|issue]
POST     /api/v1/degrees/provisional (job/single) · GET /degrees/provisional/me [degrees:issue|view (self)] {degrees.provisional}
POST     /api/v1/credentials/push (job) · GET /credentials?entity_type&status · GET /credentials/{id} · POST /credentials/{id}/retry · POST /credentials/{id}/revoke [degrees:issue] {degrees.digilocker_nad}
GET      /api/v1/credentials/me [degrees:view (self)]
POST     /api/v1/abc/push (job) · GET /abc/ledger?student_id&status · GET /abc/ledger/me · POST /abc/ledger/{id}/retry [degrees:issue|view (self)] {degrees.abc_push}
GET      /api/v1/verify/{token} · POST /verify/bulk (employer, captcha) {public} {degrees.verification_portal}
GET      /api/v1/degrees/stats?program_id&batch_id [degrees:view_all] (GPH/GPHD/median CGPA)
```

## 18.9 Frontend
- `/admin/degrees/eligibility` (run wizard: batch/programme, include exits → job → grid with `is_eligible`, reasons chips, bucket breakdown drawer, override dialog with reason, notify eligible/ineligible, export), `/admin/degrees/convocations` (events; registrations table with mode/gown/fee status; reports; day-of attendance scanner page), `/admin/degrees/awards` (award batch wizard: source (convocation/batch) → preview → resolution picker (when governance enabled) → recommend → approve → issue batch with eSign toggle → print batch; awards table with serials, status, certificate download, revoke/reissue dialogs; degree register export), `/admin/degrees/provisional`, `/admin/degrees/credentials` (push jobs per channel, status board with retries, ABC ledger view with per-student rows and revoke/re-push history, APAAR-missing list), `/admin/degrees/stats`.
- Student portal `/student/degree` (eligibility card with reasons and links to fix (holds/no-dues), convocation registration & payment, gown size, invitation download, degree/provisional download, credential push status with DigiLocker link, ABC ledger summary), alumni portal (Phase 29) reuses `/degrees/me`.
- Public `/verify/:token` (unified: degree/provisional/grade card/transcript/ID card; masked holder; revoked/superseded states), `/verify/bulk` (employer form with captcha).
- Nav: EXAMINATIONS › Degrees & Convocation (Eligibility, Convocations, Awards, Provisional, Digital credentials, Stats).

## 18.10 Mobile
Student: More › Degree (eligibility with reasons, convocation register/pay, QR invitation, certificate download/share, credential status); Registrar shell: eligibility grid (read + override), award approvals, convocation-day attendance scanner (QR), credential push status; Alumni: Degree & credentials (Phase 29 shell).

## 18.11 API verification — `scripts/verify/18_degrees.ps1`
Roles: `registrar`, `coe`, `vc` (vice_chancellor), `hod.cse`, `accountant`, `student.final` (eligible), `student.backlog` (open arrear), `student.dues` (no-dues pending), `student.hold` (graduation hold), `student.exit` (NEP diploma exit), `parent.1`, `alumni.1`, public.
1. Seed `--only degrees` (leaves batch 2022's run to the script).
2. Eligibility run for batch 2022 → job → `student.final` `is_eligible=true` with `bucket_breakdown` totals = curriculum requirements; `student.backlog` → `BACKLOGS`; `student.dues` → `DUES_PENDING`; `student.hold` → `HOLD_GRADUATION`; a student with a failed mandatory non-credit course → `MANDATORY_NONCREDIT`; a 7-year-old admission with `max_duration_years=6` → `DURATION_EXCEEDED`; `GET /degree-eligibility/me` as `student.backlog` → own row with reasons; `hod.cse` `GET` → department rows only.
3. Override `student.backlog` to eligible with reason as `registrar` → audited; as `coe` → 403.
4. Re-evaluation: clear `student.dues` no-dues (Phase 12 dev) → event → new check row `is_eligible=true` without a full run.
5. NEP exit: `student.exit` (diploma exit from Phase 07, credits ≥ 80) → included with `include_exits=true` → award row `award_type=diploma` recommended.
6. Convocation: create event (fee ₹1,500, deadline next week) → `registration_open`; `student.final` registers in-person (gown L, 2 guests) → invoice `source_type=convocation_registration`; pay → `registered`; `student.backlog` registering → 409 `RULE_VIOLATION` `NOT_ELIGIBLE`; replay with same key → replay; after deadline → 409; reports (gowns/seating) return rows; attendance scan (dev QR) marks attended.
7. Awards: `award-batch?dry_run=true` for the convocation → preview count = eligible & registered (setting `award_requires_registration`) ; run → `recommended`; `approve` without resolution while `governance.minutes` enabled → 422 requiring `resolution_id`; with a dev resolution → `council_approved`; `issue` (eSign feature off) → `issued` with `certificate_number`, `serial_no`, PDF, QR token; enrolment `completed`, student `graduated`, event `student.graduated`; `GET /degrees/me` as `student.final` → award + PDF; as `parent.1` → 200; `accountant` → 403.
8. eSign (feature on, mock adapter): issue → `esign_ref` set and PDF contains signature block.
9. Provisional: issue for an eligible-not-awarded student → PDF + QR; after degree issue → verify of the provisional token shows `superseded`.
10. Revoke/reissue: revoke an award with reason → `cancelled`, verify → `revoked`, credentials revoked, student status `completed`; reissue with corrected name → new serial, old `reissued` referencing new; register export lists both with statuses.
11. Verification: public `GET /verify/{token}` for a degree → valid + masked holder + hash; tampered token → 404; `POST /verify/bulk` with captcha (mock) → results; rate limit after N/min → 429.
12. Digital credentials (feature on, mock DigiLocker): push degrees for the batch → rows `pushed → acknowledged`; student without APAAR → `SKIPPED_NO_APAAR`; `GET /credentials/me` as `student.final` → status; simulate failure on one → `failed` → `retry` → `acknowledged`.
13. ABC (feature on, mock): `POST /abc/push` → pending ledger rows `pushed/acknowledged` in batches with `push_batch_id`; Phase 15 correction run (dev) creating a new version for one result → old ledger row `revoked`, new row `pending` → nightly push → `acknowledged`; `GET /abc/ledger/me` as `student.final` → own rows.
14. Stats: `GET /degrees/stats?program_id=BTECH&batch_id=2022` → GPH (on-time graduates / admitted) matches seeded counts; `iqac` read OK.
15. University tenant: `college.admin.b` `award-batch` → creates `recommended` only; `issue` → 403 (university issues); registrar of the university issues college B awards.

## 18.12 UI verification
1. Eligibility page: run wizard, reasons chips with fix links, bucket drawer, override dialog, notify buttons, export.
2. Convocation pages: event setup, registrations with fee status, day-of attendance scanner (QR from student app), reports.
3. Awards wizard through recommend → approve (resolution picker) → issue batch (eSign toggle) → print batch; awards table with download/revoke/reissue; register export.
4. Credentials board: push per channel, retries, APAAR-missing list; ABC ledger view with revoke/re-push history.
5. Student degree page: eligibility with reasons, convocation registration/payment, certificate download, credential status with DigiLocker link; public verify page states (valid/revoked/superseded); employer bulk verify.
6. Mobile: student degree screen + QR invitation; registrar attendance scanner; alumni degree download.

## 18.13 Deliverables checklist
- [ ] Eligibility engine (buckets, backlogs, CGPA, duration, mandatory non-credit, holds, dues, NEP exits, overrides, auto re-evaluation), convocations (events, registration+fee, reports, attendance), awards (batch → council approval via resolution/workflow → issue with serials/QR/eSign → provisional → revoke/reissue → register), digital credentials (DigiLocker/NAD adapter, retries, revoke), ABC push (batches, revoke/re-push on versions), unified verification portal (+ bulk), graduation stats
- [ ] Student/graduated/alumni transitions and events; visibility registrations; demo seed `--only degrees`
- [ ] Web + mobile; `scripts/verify/18_degrees.ps1` passes; UI checklist done; guards green; commit `feat(phase-18): degrees, convocation, digital credentials`
