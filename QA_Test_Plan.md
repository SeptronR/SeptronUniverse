# SeptronUniverse — End-to-End UI QA Test Plan

_Status: **skeleton** (Batch I). Phase 43 fills §3 (per-role sweeps from every prompt's NN.12), §7 (entry/exit criteria, release gate) and creates `QA_Findings.csv`; Phase 44 adds the DR-drill and status-page gates. Shape adapted from SeptronOrbit's `QA_Test_Plan.md`._

## Context

A systematic pass through **every UI feature** of SeptronUniverse as a real end user, across the web admin shell, the portals (student / parent / faculty / applicant / alumni / recruiter / driver), the public site and the Flutter app, **with every seeded role** — functional testing first, then integration (cross-module) scenarios, then system-level checks. Written so a testing agent does **not** need to explore the app: every step names the page route, tab, button label and column as the phase prompt specifies them (`Prompts/NN_*.md` §NN.9 and §NN.12). Where the literal label is unknown it is marked `(verify exact label in UI)`.

Verification philosophy (ADR 0006): **no unit tests**. This plan is the UI half of verification; the API half is `backend/scripts/verify/NN_*.ps1` per role (`run_all.py --suite api_all`). Playwright suites in `e2e/` (Phase 43) automate §3 and §5 one `test.step` per checklist line with `axe` on every page; this document remains the manual sweep and the source of truth for what the suites must cover.

---

## 0. Known risk areas — check these FIRST (carried over from Orbit's findings; re-confirm in Universe)

1. **Unguarded frontend routes** — every admin route must be wrapped in `FeatureRoute` + `PermissionRoute`; every list must show `ScopeTabs` only from `meta.visibility`. Log in as `librarian`, type `/admin/payroll`, `/admin/exams/results`, `/admin/settings/roles`, `/super-admin` into the address bar: the page must not render **and** the Network tab must show 403 (`PERMISSION_DENIED` / `FEATURE_DISABLED`). A render with a 403 underneath is cosmetic; a render **with data** is a security bug (P0).
2. **Super-admin console guard** — `/super-admin/*` checks `is_super_admin`, not only "authenticated": `inst.admin` navigating there directly gets nothing (403 on `/platform/*`).
3. **Result publication separation of duties** (ADR 0008) — only `coe` can publish; `exam.cell` can verify but the Publish button is absent and `POST /results/…/publish` returns 403; `decoder` is the only role that sees dummy ↔ register-number mapping; evaluators (`faculty.1`, `examiner.ext`) never see register numbers on valuation screens.
4. **Published results are immutable** — after publish, edit controls disappear; a revaluation/correction creates a **new version row** (`result_versions`) and the old one stays readable.
5. **Redis and Celery are required** — welcome emails, receipts, hall tickets, reports and the outbox relay run in workers. If any action (register, collect fee, generate hall tickets) hangs, the worker/beat is the first suspect; foreground requests must still return within seconds (job tray shows progress).
6. **Providers in mock mode** — with `*_PROVIDER=mock`, payments/SMS/WhatsApp/email/push must complete gracefully (mock receipts, `message_logs` rows) and never crash; with a provider configured but unreachable, the UI must show a clear error, not a blank screen.
7. **Money is paise** — every amount in the UI must render as rupees with two decimals; totals across invoices, receipts, concessions, refunds and ledgers must reconcile to the paise.
8. **Idempotency** — double-clicking Submit on registration, fee collection, out-pass, application submit must create one record (`Idempotency-Key`; second call returns `IDEMPOTENT_REPLAY`).
9. **Read-only mode** — with a read-only window active (platform or tenant) every write shows the banner and returns `503 READ_ONLY`; reads keep working.
10. **PII masking** — Aadhaar/bank/medical/caste fields are masked unless the role has `<module>:view_pii`; masked values stay masked in exports and PDFs.

---

## 1. Environment setup

| Component | Local | Notes |
|---|---|---|
| Backend | `http://localhost:8000` (`uvicorn main:app --reload`) — `/docs`, `/health`, `/ready` | Postgres + Redis required; worker + beat running (`RUN_AFTER_PHASE.md` §5) |
| Web | `http://localhost:5173` (`npm run dev`) | admin shell + portals |
| Public site (SSR, Phase 40) | `http://localhost:5175` or `/site/demo-uni` via nginx | custom-domain tests need a hosts-file entry |
| Flutter (Phase 42) | Android emulator / device, iOS simulator | report as an explicit gap when no SDK is available — do not skip silently |
| Full stack | `docker compose up` → `http://localhost` (nginx) | Flower `:5555` for task inspection |
| Staging | `https://staging-app.universe.septronr.com` | pipeline-deployed (`build.yml` → `orbit-infra`); §7 release gate runs here |

Drive the web app via the Browser tool (`preview_start`). After every significant action check the console **and** the Network tab (envelope `{data, meta, error}`; no 5xx, no unexpected 403). Seed: `python scripts/seed_platform.py && python scripts/seed_demo_institution.py --type university --all` (credentials → `LOCAL_TEST_CREDENTIALS.md`).

---

## 2. Test accounts per role (seeded — do **not** create by hand)

`seed_demo_institution.py` creates institution `demo-uni` (type `university`; `--type autonomous|affiliated` for the other shapes) with colleges A/B, departments CSE/ECE/ME, programmes, terms and one user per role. Identifiers used throughout the phase prompts' NN.11 sections:

| Identifier | Role | Scope / notes |
|---|---|---|
| `superadmin`, `superadmin.2` | super_admin | platform; `.2` for four-eyes approvals |
| `support.agent` | support_agent | read-only, PII masked |
| `inst.admin` | institution_admin | demo-uni |
| `vc`, `principal` | vice_chancellor / principal | executive read-all + approvals |
| `registrar` | registrar | students, admissions, certificates, degrees |
| `coe`, `exam.cell`, `decoder` | controller_of_examinations / exam_cell / exam_decoder | separation of duties (§0.3) |
| `dean.eng` | dean | faculty of engineering |
| `hod.cse`, `hod.ece` | hod | departments |
| `advisor.1`, `advisor.cse.a` | class_advisor | batch section |
| `faculty.1` … `faculty.5`, `faculty.ece`, `faculty.m1` (mentor) | faculty | own offerings only |
| `examiner.ext` | external_examiner | assigned bundles, time-boxed |
| `research.cell`, `scholar.1`, (guide = `faculty.2`) | research_cell / research_scholar / research_guide | PhD lifecycle |
| `iqac`, `obe` | iqac_coordinator / obe_coordinator | accreditation, attainment |
| `admissions` | admissions_officer | cycles, merit, offers |
| `accountant`, `hr` | accountant / hr_officer | fees/accounting; staff/leave/payroll |
| `placement.off`, `recruiter.1` | placement_officer / recruiter | drives; company user |
| `alumni.1` | alumni | self |
| `warden.h1`, `warden.boys`, `warden.girls` | hostel_warden | assigned hostels |
| `librarian`, `transport.mgr`, `driver.1`, `inventory.mgr`, `estate.off`, `security.off`, `medical.off`, `sports.off` | campus services roles | as named |
| `grievance.off`, `discipline`, `committee.sec`, `legal.off`, `pio` | student support / governance | |
| `integration.admin`, `privacy.off`, `security.off` | integration_admin / privacy_officer / security | Phases 41/43 |
| `college.admin.b`, `college.exam.b` | college_admin / college_exam_coordinator | college B (affiliated flows) |
| `auditor.tmp` | auditor | time-boxed read-only |
| `student.1`, `student.2`, `student.hold`, `student.arrear`, `student.dues`, `student.final`, `student.minor`, `student.risk`, `student.tc` | student | fixtures for holds, arrears, dues, final year, minor, early-warning, TC |
| `parent.1` | parent | ward = `student.1` (consented) |
| `applicant.1`, `learner.1`, `vendor.a` | applicant / learner / vendor | public-facing portals |

Passwords: see `LOCAL_TEST_CREDENTIALS.md` (never committed). If a role above is missing after seeding, that is itself a finding against the phase that owns it.

---

## 3. Functional test scripts by module (literal steps) — _filled in Phase 43 from each prompt's NN.12_

One subsection per phase in build order. Each subsection = page route(s) → per-role numbered steps (button/tab/column labels as in NN.9) → expected result → the NN.11 API step that proves the same outcome. Until filled, execute the prompt's **NN.12 UI verification** list directly.

| § | Phase | Module | Primary routes | Roles to sweep | Source checklist |
|---|---|---|---|---|---|
| 3.1 | 02 | Auth, RBAC, features | `/login`, `/profile`, `/admin/settings/roles`, `/super-admin/features` | all (login), `inst.admin`, `superadmin` | `Prompts/02_*.md` §02.12 |
| 3.2 | 03 | Institution structure, sessions, settings | `/admin/institution/*`, `/admin/sessions` | `inst.admin`, `registrar`, `college.admin.b` | §03.12 |
| 3.3 | 04 | Communication core, workflow engine | `/admin/communication`, `/inbox`, `/approvals` | `inst.admin`, `hod.cse`, `student.1` | §04.12 |
| 3.4 | 05 | Programmes, regulations, curriculum | `/admin/academics/*` | `dean.eng`, `hod.cse`, `registrar` | §05.12 |
| 3.5 | 06 | Staff, HR, recruitment, CAS | `/admin/staff/*`, `/admin/hr/*` | `hr`, `hod.cse`, `faculty.1`, `accountant` | §06.12 |
| 3.6 | 07 | Students, enrolment, holds, standing | `/admin/students/*` | `registrar`, `hod.cse`, `advisor.1`, `student.hold` | §07.12 |
| 3.7 | 08 | Admissions | `/admin/admissions/*`, `/apply/:cycle` | `admissions`, `applicant.1`, `registrar` | §08.12 |
| 3.8 | 09 | Offerings, allocation, registration | `/admin/offerings/*`, `/student/registration` | `hod.cse`, `advisor.1`, `student.1`, `student.arrear` | §09.12 |
| 3.9 | 10 | Timetable & rooms | `/admin/timetable/*` | `hod.cse`, `faculty.1`, `student.1` | §10.12 |
| 3.10 | 11 | Attendance & eligibility | `/admin/attendance/*`, `/faculty/attendance` | `faculty.1`, `hod.cse`, `student.1`, `parent.1` | §11.12 |
| 3.11 | 12 | Fees, scholarships, no-dues | `/admin/fees/*`, `/student/fees` | `accountant`, `registrar`, `student.dues`, `parent.1` | §12.12 |
| 3.12 | 13 | Internal assessment, OBE definitions, LMS, projects | `/admin/assessment/*`, `/faculty/lms/*` | `faculty.1`, `hod.cse`, `obe`, `student.1` | §13.12 |
| 3.13 | 14 | Exam administration | `/admin/exams/*` | `coe`, `exam.cell`, `college.exam.b`, `student.1` | §14.12 |
| 3.14 | 15 | Evaluation & results | `/admin/exams/valuation/*`, `/admin/exams/results/*` | `coe`, `exam.cell`, `decoder`, `faculty.1`, `examiner.ext` | §15.12 |
| 3.15 | 16 | Post-result services | `/admin/exams/revaluation`, `/student/results` | `coe`, `student.1`, `accountant` | §16.12 |
| 3.16 | 17 | OBE attainment & CQI | `/admin/obe/*` | `obe`, `hod.cse`, `faculty.1` | §17.12 |
| 3.17 | 18 | Degrees, convocation, credentials | `/admin/degrees/*`, `/student/credentials` | `registrar`, `coe`, `student.final` | §18.12 |
| 3.18 | 19–26 | Campus services (library, hostel, transport, inventory, accounting, comms advanced, facilities, documents) | `/admin/library/*` … `/admin/documents/*` | service roles + `student.1` | §19.12–§26.12 |
| 3.19 | 27–34 | Engagement, research, quality (mentoring/grievances, placement, alumni, research, PhD, accreditation, governance, affiliation) | `/admin/mentoring/*` … `/admin/affiliation/*` | `faculty.m1`, `placement.off`, `research.cell`, `scholar.1`, `iqac`, `committee.sec`, `college.admin.b` | §27.12–§34.12 |
| 3.20 | 35–41 | Platform (dashboards, reports, audit/settings, super admin, portals/PWA, website, integrations/migration) | `/admin/dashboard`, `/admin/reports`, `/admin/audit`, `/super-admin/*`, `/site/demo-uni`, `/admin/integrations` | `inst.admin`, `superadmin`, `integration.admin`, `auditor.tmp` | §35.12–§41.12 |
| 3.21 | 42 | Flutter app (all role shells) | device | every portal/field role | §42.12 |
| 3.22 | 43–44 | Hardening, ops console, status page | `/admin/privacy`, `/super-admin/ops/*`, `/status` | `privacy.off`, `superadmin`, public | §43.12–§44.12 |

---

## 4. Role-based access verification checklist

For each role: log in, confirm the nav shows only permitted modules (`NAV_GROUPS` gates), confirm direct-URL navigation to an unpermitted module is blocked by the **backend** (403 in the Network tab), and confirm the `ScopeTabs` offered (Mine | Dept | College | All) match `docs/Authorization_and_Visibility.md` for that role.

| Role | Should access (highlights) | Must NOT effectively access (backend-level) | Expected scope tabs |
|---|---|---|---|
| super_admin | everything, all institutions | — (impersonation is audited) | All |
| support_agent | read across institutions, PII masked | any write | All (read) |
| institution_admin | everything inside demo-uni | other tenants; feature toggles beyond the plan | All |
| college_admin (`college.admin.b`) | institution-admin subset for college B | college A data | College |
| registrar | students, admissions, certificates, degrees, affiliation | valuation, publish, fees collection | All |
| controller_of_examinations | exams end-to-end incl. publish | fee collection, HR | All |
| exam_cell | exam operations | decode, publish | College/All |
| exam_decoder | decode after finalisation | everything else | — |
| dean / hod | faculty / department academics, approvals | other departments' Mine data, publish | Dept / Faculty |
| class_advisor | advisee registrations, monitoring | other sections | Mine (section) |
| faculty | own offerings: attendance, marks, LMS | other offerings, staff edit, fees | Mine |
| external_examiner | assigned bundles (dummy numbers) | register numbers, anything else | Mine |
| accountant | fees, scholarships, no-dues, payroll runs, accounting | students/staff edit, results | All |
| hr_officer | staff, leaves, payroll config, recruitment | fees, exams | All |
| librarian / hostel_warden / transport_manager / inventory_manager / estate_officer / security_officer | own module | everything else | All / hostel-scoped |
| placement_officer / alumni_coordinator / research_cell / iqac_coordinator / obe_coordinator | own module | student edit, fees | All |
| integration_admin | connections, keys, webhooks, imports | tenant data modules | All |
| auditor | read-only across modules (time-boxed) | any write; expired window → 401 | All (read) |
| student | `/student` self only | any other student, admin modules | — |
| parent | `/parent` consented wards only | other wards, admin modules | — |
| applicant / alumni / recruiter / learner / driver | own portal | admin modules | — |

---

## 5. End-to-end integration scenarios (primary focus — run in order, without skipping)

Each scenario chains modules and roles. Expand to literal steps in Phase 43; the API twin of each scenario lives in the phase scripts named.

| # | Scenario | Roles | Phases | Key assertions |
|---|---|---|---|---|
| E2E-1 | Admission → enrolment → fee invoice → payment → receipt → no-dues | `admissions`, `applicant.1`, `registrar`, `accountant`, `student.1`, `parent.1` | 08, 07, 12, 26 | invoice from `fee_service.create_invoice`; receipt PDF via Phase 26; parent sees same balance |
| E2E-2 | Course registration → timetable → attendance → eligibility → hall ticket | `student.1`, `advisor.1`, `hod.cse`, `faculty.1`, `exam.cell` | 09, 10, 11, 14 | shortage → condonation workflow; hall ticket blocked for `student.dues` until dues cleared |
| E2E-3 | Exam → coded valuation (dummy numbers) → moderation → decode → publish → immutable version → revaluation | `coe`, `exam.cell`, `faculty.1`, `examiner.ext`, `decoder`, `student.1` | 14, 15, 16 | evaluators never see register numbers; publish only by `coe`; new `result_versions` row on revaluation; grade card PDF regenerates with version tag |
| E2E-4 | CO-PO mapping → internal + external marks → attainment run → CQI action | `obe`, `faculty.1`, `hod.cse` | 13, 17 | attainment numbers match the formula in `docs/Academic_Core_Design.md`; drill-down respects visibility |
| E2E-5 | Degree eligibility → convocation registration + fee → degree issue → DigiLocker/NAD push (mock) → public verify | `registrar`, `coe`, `student.final`, public | 18, 26, 41 | `/verify/:token` shows status/hash; revoke → verify shows revoked |
| E2E-6 | Hostel application → allotment → mess plan → out-pass (QR at gate) → late-return notification to parent | `student.1`, `warden.h1`, gate staff, `parent.1` | 20, 24 | gate scan idempotent; parent notification in `message_logs` |
| E2E-7 | Placement drive → eligibility filter → application → rounds → offer → acceptance → statistics | `placement.off`, `recruiter.1`, `student.final` | 28, 35 | recruiter sees only consented fields; stats tile matches offers |
| E2E-8 | PhD admission → guide allotment → DC meetings → progress → thesis submission → plagiarism (mock) → viva → award | `research.cell`, `scholar.1`, `faculty.2` (guide) | 31, 30, 18 | UGC timelines enforced; thesis repository deposit (mock) |
| E2E-9 | Affiliated college submits marks/attendance → university verifies → results consolidated | `college.exam.b`, `college.admin.b`, `coe`, `uni.registrar` | 34, 15 | college B cannot see college A; university sees both |
| E2E-10 | SaaS registration → provisioning → plan features → institution admin first login → feature toggle propagates | public, `superadmin`, new institution admin | 38, 02 | disabled feature: nav hidden, route 403, mobile screen hidden |
| E2E-11 | Visibility matrix: same list as `faculty.1` / `hod.cse` / `dean.eng` / `registrar` | four roles | 07, 09, 11 | Mine ⊂ Dept ⊂ Faculty ⊂ All; `meta.visibility.scopes` matches tabs |
| E2E-12 | Role/permission change → live enforcement (no re-login) | `inst.admin`, `librarian` | 02 | removed permission → 403 on next request; nav updates after refresh |
| E2E-13 | Multi-tenant isolation via super admin (two demo tenants) | `superadmin`, `inst.admin` × 2 | 38, 43 | zero cross-tenant rows; RLS raw check (Phase 43) = 0 |
| E2E-14 | Grievance → SLA escalation → committee → resolution → survey | `student.1`, `grievance.off`, `committee.sec` | 27, 33 | Beat escalation fires; anonymity preserved where chosen |
| E2E-15 | Data migration workbook → dry-run → apply → reconciliation → rollback | `integration.admin` | 41 | error report per row; rollback restores counts |
| E2E-16 | Early-warning signal → mentor intervention → attendance/marks recovery on dashboard | `faculty.m1`, `hod.cse`, `student.risk` | 35, 27 | intervention stored as `mentoring_sessions`; `mv_*` refresh reflects it |

---

## 6. System-level / non-functional checks

1. **Session refresh**: idle > 15 min → next action silently refreshes via the httpOnly cookie (no forced re-login); refresh rotation invalidates the old refresh token.
2. **Logout / blacklist**: replay an old access token after logout → 401 (`TOKEN_REVOKED`); sessions page revoke → other device logged out.
3. **Read-only window** (platform and tenant): banner on web + mobile; writes `503 READ_ONLY`; window end → writes resume.
4. **Subscription grace / expiry** (Phase 38): grace → writes 402 except billing; expired → login shows renewal only.
5. **Background jobs**: bulk hall tickets (10 000 in demo) → tray progress → download; worker restart mid-job → resumes without duplicates.
6. **Notifications**: outbox → in-app inbox + channel per preference; announcement acknowledgement recorded.
7. **Responsive**: 375 px width for `/student`, `/parent`, `/faculty`, `/driver` portals and the public site — no horizontal scroll, touch targets ≥ 44 px; dark mode; print stylesheets (hall ticket, grade card, receipt, transcript).
8. **Accessibility**: `axe` 0 serious/critical on every page (automated in e2e); keyboard-only path through login → registration → submit.
9. **i18n**: switch locale (hi/ta/te/…) on portals → labels/dates/numbers localised; bilingual PDFs render Indic fonts.
10. **Console/network hygiene**: log every uncaught error or failed request even when the UI looks fine.
11. **Validation spot-check**: ≥ 5 deliberate validation errors across forms (fee head with ₹0, student without DOB, leave with To < From, marks > max, registration over credit limit) → clear messages, never stack traces.
12. **Performance smell**: list pages with the demo volume load < 1 s; p95 targets in `docs/Technical_Architecture.md` §17 are measured by the Phase 43 load suite, not here.

---

## 7. Entry / exit criteria, severity scale and release gate

**Entry:** demo seed `--all` completed, guards green. **Exit:** §10 release gate. **Severity:** P0 data loss / leak / security · P1 blocks a role's core flow · P2 wrong result with a workaround · P3 cosmetic.

- **Entry**: all phases up to the tested round committed; `RUN_AFTER_PHASE.md` guards green; demo seed `--all` succeeded; `run_all.py --suite api_round_<n>` green.
- **Exit per round**: §3 sweeps for the round executed for every role listed; §5 scenarios touching the round pass; 0 open P0/P1; P2 triaged with owner.
- **Severity**: **P0** security/data-integrity (cross-tenant, unmasked PII, unauthorised publish, money mismatch) · **P1** blocks a role's core flow · **P2** wrong but workaround exists · **P3** cosmetic/text.
- **Release gate (staging)**: all P0/P1 closed · `api_all` + `e2e all` + `visibility` + `immutability` + `golden` green (`verify.yml`) · load thresholds met (Phase 43) · security scans without high findings (`security.yml`) · VAPT retest passed (Phase 43) · restore drill within 100 days (Phase 44) · status page + runbooks walked (Phase 44).

---

## 8. Bug tracking format

Log every defect in `QA_Findings.csv` with columns: `id, phase, role, page_or_endpoint, steps (plan reference e.g. 3.11-step-4 / E2E-3-step-6), expected, actual, console_or_network_error, severity (P0–P3), status (open|fixed|verified|wontfix), owner, fixed_in_commit`. Findings under §0 or §4/E2E-11/12/13 default to P0.

---

## Verification

Execute this plan by driving the running web app (5173), the public site and the Flutter app through the Browser tool / device against the backend (8000) with the seeded roles. Each functional step is verified by: action succeeds with no console/network error → data persists on reload → propagates wherever §5 says it should. RBAC/visibility checks (§0, §4, E2E-11/12/13) are verified by **backend** 403/scoped responses in the Network tab, never by what the frontend renders. The API scripts (`run_all.py`) run first as the sanity gate; they do not replace this walkthrough.

## 9. Automated suites (Phase 43)

| Suite | Command | Needs | Gate |
|---|---|---|---|
| static guards | `python scripts/verify/run_all.py --suite static` | DB + Redis | 0 offenders / diffs |
| golden datasets | `--suite golden` (18 cases through the production calculators) | — | 0 diffs |
| isolation | `--suite visibility` (RLS on every tenant table, no cross-tenant rows, no `SET ROLE`) | DB | 0 leaks |
| immutability | `--suite immutability` (result triggers, append-only audit grants) | DB | 0 failures |
| API per phase | `--suite api_all` / `--suite api_round_N` (`scripts/verify/NN_*.ps1`, PowerShell 7) | running seeded API | 0 failed phases |
| E2E + axe | `cd e2e && npx playwright test` (portals + admin sweeps) | running web + API | 0 serious / critical axe issues |
| load | `k6 run load/<scenario>.js` (staging) | staging stack + `--load` fixtures | thresholds in each script |

Reports: `backend/reports/qa/<suite>-<timestamp>/{junit.xml,summary.md,summary.json}`; `/admin/qa` runs suites as jobs
outside production. Findings go to `QA_Findings.csv` (id, phase, role, page / endpoint, severity, status, owner,
fixed-in commit).

## 10. Release gate

All P0 / P1 findings closed · every suite above green on the release candidate · load thresholds met on staging ·
VAPT gate `pass` (`GET /security/vapt`) · restore drill within 30 days (Phase 44) · posture score ≥ 90 with no `fail`
controls on the pilot tenants.
