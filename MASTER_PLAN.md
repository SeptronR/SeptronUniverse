> **Approved master plan** (planning session of 2026-09-12/13). Execution status lives in [PROGRESS.md](PROGRESS.md); session hand-off instructions in [docs/HANDOFF.md](docs/HANDOFF.md). Sections 5 (phases), 6 (academic core), 7 (feature flags), 8 (visibility), 9 (user flows), 10 (mobile UI) are the design authority for the phase prompts.

# SeptronUniverse — College & University ERP: Master Plan

## 1. Context

**SeptronOrbit** (`C:/Users/user/source/septronR repo/SeptronOrbit`) is a shipped, multi-tenant *School* ERP: FastAPI + SQLAlchemy 2 async + PostgreSQL 15 + Redis 7 + Celery 5; React 18/TS/Vite + Zustand + TanStack Query + Tailwind/Radix; Flutter mobile; 149 tables, 52 route modules, 531 backend tests, 15 Playwright suites; deployed via `ghcr.io/septronr/orbit-api` → `orbit-infra` (Traefik VPS). Built prompt-driven (`Prompts/00_PREREQUISITE` + 25 phase prompts + 5 fix prompts; later `featurePrompts/` with migrations + verification checklists).

**SeptronUniverse** (`C:/Users/user/source/septronR repo/SeptronUniverse`, empty repo) is a **new application for colleges and universities** following the *same architecture, stack, layer conventions and prompt-driven process*, designed for higher education: programmes/regulations/credits, course registration, a full examination lifecycle, OBE, hostel, placement, alumni, research & PhD, governance, accreditation and university ↔ affiliated-college workflows. **Every feature is a super-admin-controlled flag** (§7); **every record is visible through an explicit self / ownership / scoped / view_all model** (§8); **mobile has a role-based shell with a defined information architecture** (§10).

### 1.1 Decisions taken (confirmed with the user)

| # | Decision | Choice |
|---|---|---|
| 1 | Code strategy | **Greenfield repo, identical architecture.** Port patterns (not files) from Orbit; fix Orbit's structural debts from day one (§4.2). |
| 2 | Tenancy | **Institution → colleges/campuses → faculties → departments.** Tenant = `institution`; standalone college = institution with one auto-created college. Affiliation workflows in scope. |
| 3 | Market | **India-first, global-ready** via regulatory packs (`IN` first, `GENERIC` stub). |
| 4 | First deliverable | **Full planning-document set** committed to SeptronUniverse; code build follows phase by phase. |
| 5 | Feature control | Every module/sub-feature is a registered flag; super admin enables per institution; plans give defaults; backend/frontend/mobile gate on it. |
| 6 | Visibility | Every people/records module supports **self** ("My …") and, when the role holds `view_all` within its scope, the wider view — both shown side by side (e.g., accountant: own leaves/attendance **and** all staff, leaves, attendance). |

### 1.2 Research basis

SAMARTH eGov (40+ modules), commercial Indian college ERPs (MasterSoft, Creatrix, vmedulife, edumerge, Edhitch, iCloudEMS, OpenEduCat), NEP 2020 / ABC / APAAR / NCrF, NAAC / NBA / NIRF / AISHE, UGC PhD Regulations 2022, Indian exam regulations, international registrar SIS practice, and Orbit's as-built inventory. Sources §19.

---

## 2. Product definition

| Institution type | What differs | Tenancy shape |
|---|---|---|
| Affiliated college | University syllabus; internal marks + university result import; no own degree | `institution(type=affiliated_college)`, 1 college, `programs.exam_authority='university'` |
| Autonomous college | Own regulations/exams/grading (BoS/Academic Council); degree via parent university | `institution(type=autonomous_college)`, 1 college |
| University (state/private/deemed) | Multi-college/campus, affiliation, central exams, PhD, convocation, research | `institution(type=university)`, N colleges |
| Multi-campus institution | Same regulations, separate campuses | N `colleges(kind=campus)` |

Behaviour switched by `institution.type`, feature flags, regulatory pack.

---

## 3. Architecture carried over from Orbit (unchanged)

| Layer | Reused as-is |
|---|---|
| Backend | FastAPI async · SQLAlchemy 2 async + Alembic · PostgreSQL 15 · Redis 7 · Celery 5 (queues `notifications, emails, reports, scheduled` + Beat) · Pydantic v2 · pytest-asyncio + httpx · WeasyPrint + Jinja2 · openpyxl · boto3/local storage · JWT HS256 (access 15 min in memory, refresh 7 d httpOnly, JTI blacklist) · OTP · bcrypt 12 · Redis rate limiter · captcha |
| Layering | Route → Service → Repository → Model; registries (reports, charts, metrics, features, adapters, packs); `notify_event()` → Celery → channel clients |
| Frontend | React 18 + TS + Vite · Router v6 guards · Zustand · TanStack Query v5 · Axios (Bearer + tenant headers, envelope unwrap, single-flight refresh) · Tailwind + Radix `components/ui` · Recharts wrappers · FullCalendar · dnd-kit · TipTap · themes-as-data + table styles · `NAV_GROUPS` · portals · PWA |
| Mobile | Flutter 3.22+, Riverpod, go_router, dio, secure storage, feature-first layout, role→tabs registry, 11 locales, FCM, thermal printing |
| Infra | Docker Compose · GitHub Actions → `ghcr.io/septronr/universe-api` → `repository-dispatch` → `orbit-infra` (`compose/apps/universe-*.yml`, Traefik) |
| SaaS | Super-admin panel, plans/subscriptions, impersonation, self-serve registration, public website, marketing site |

---

## 4. What changes vs Orbit

### 4.1 Vocabulary & tenancy renames

| Orbit | Universe |
|---|---|
| `schools/school_id`, `X-School-*`, `SchoolContextMiddleware`, `get_school_id` | `institutions/institution_id`, `X-Institution-*`, `InstitutionContextMiddleware`, `get_institution_id` |
| — | `colleges/college_id`, `X-College-Id`, `get_college_scope`; `faculties`; `departments(college_id, faculty_id?, hod_staff_id)` |
| `user_roles(user_id, role_id)` | `user_roles(user_id, role_id, scope_type, scope_id)` — **scope layer** |
| `school_feature_flags` (16 keys) | `institution_feature_flags` from a ~190-key registry (§7) |
| `academic_years/terms` | same, with term status machine & registration/add-drop/instruction dates |
| `classes/sections/subjects/timetable` | `programs → regulations → program_regulations → program_structure_terms → curriculum_courses → courses`; `batches/batch_sections`; `course_offerings`; offering-based timetables |
| `students/student_enrollments/student_parents` | `students` (+ ids, category/quota, holds, standing) / `student_program_enrollments` / `student_term_records` / `student_guardians` |
| `exams/student_marks` | full exam suite (§6.5) |
| `homework/lesson_plans/ptm` | `lms_assignments / lesson_plans / mentoring` |
| `fee_structures(class)` | `fee_structures(program, regulation, batch, category, quota, term)`; `fee_invoices.payer_type/source_type/source_id` |
| — | `number_sequences`, `workflow_*`, `background_jobs`, `domain_events` (outbox), `student_holds`, `integration_connections`, `api_keys`, `webhooks`, `idempotency_keys` |

### 4.2 Backend building blocks (Phase 00/01) — Orbit lessons + architectural gaps

| Building block | Purpose |
|---|---|
| `models/base.py` mixins: `UUIDPrimaryKey`, `Timestamp`, `SoftDelete`, `Tenant`, `CollegeScoped`, **`OptimisticLock`** (`version` int, 409 on stale update) | Uniform columns; no drift; safe concurrent edits on masters |
| `repositories/base.py` `BaseRepository[Model]` — tenant + scope + soft-delete filters always; `visible_to(user, module)` hook | Missed filters were Orbit's #1 security finding |
| `core/authz/`: `feature_required`, `permission_required`, `scope`, **`VisibilityResolver`**, **field masking** (`mask_pii`) | Four-layer authorization (§8) |
| **PostgreSQL RLS (defense in depth)**: `SET LOCAL app.institution_id` per request; policies on every tenant table | Even a missed filter cannot leak across tenants |
| `utils/response.py` `ok()` + `jsonable_encoder`; pagination in envelope; **error-code catalogue** (`APIError(code, message, details)`, documented codes) | Consistent envelope, machine-readable errors |
| `core/features.py` registry + `institution_feature_flags` | §7 |
| `core/packs/` regulatory packs | Decision 3 |
| `core/workflow/` approval-workflow engine | Configurable approvers per institution |
| `core/events.py` **domain events + transactional outbox** (`domain_events` table written in the same transaction; Beat/worker relays to Celery consumers: notifications, webhooks, search index, metrics invalidation, ABC push, analytics) | At-least-once delivery; no lost notifications on crash |
| `core/idempotency.py` — `Idempotency-Key` header for POST payments/registrations/imports/marks submit (Redis + `idempotency_keys`) | Safe retries from flaky mobile networks |
| `core/jobs.py` + `background_jobs` (progress, cancel, result_url) | All long tasks visible & cancellable |
| `core/tenancy.py` — institution **timezone/locale/currency**; store UTC, render in institution TZ; academic dates as DATE | Correct term dates, receipts, hall tickets |
| `core/files.py` — per-tenant prefixes, plan quotas, signed URLs, MIME sniffing, optional ClamAV, thumbnails, retention | Safe uploads at scale |
| `core/ws.py` — WebSocket fan-out via **Redis pub/sub** (multi-worker safe) channels: notifications, job progress, live fleet | Orbit was in-process only |
| `core/security.py` — MFA (TOTP), session registry & revoke, refresh-token rotation, JWT key rotation (kid), IP allowlists for exam ops, API keys (scoped, rate-limited), webhook signing, impersonation banner + audit | Privileged roles protected |
| `core/audit.py` — explicit `log_audit` + middleware fallback; **hash-chained** audit rows; super-admin action audit | Tamper-evident |
| `scripts/`: `check_schema_drift.py`, `verify_prompts_vs_schema.py`, `gen_access_matrix.py`, `export_openapi.py`, **`scaffold_module.py`** (generates model/schema/repo/service/router/tests/TS api/page/nav skeleton per pattern), `seed_demo_institution.py`, `rollover_academic_year.py`, `close_term.py`, `archive_year.py` | Consistency, productivity, operations |
| CI: `alembic heads`=1, no `create_all`, authz/feature audit tests, drift check, ruff/black/mypy, eslint/prettier, pre-commit, conventional commits, **expand/contract migration lint** (no destructive DDL without a follow-up) | Zero-downtime deploys |
| Redis required; global exception handler adds CORS; schemas by domain; statuses `VARCHAR(30)` + Python enums; results versioned/immutable | Orbit findings |
| Observability: Prometheus, Sentry, JSON logs with request/tenant/user ids, Flower, uptime, alert rules, per-tenant rate limits, adapter circuit breakers/timeouts/retries | Ops |
| Data lifecycle: partitioning (`audit_logs`, `student_class_attendance`, `message_logs`, `domain_events`), materialized read models for analytics refreshed by Beat, archival of closed years, backups per tenant (+ S3 versioning for uploads), DR (RPO 15 min / RTO 4 h targets), tenant export/erasure, soft-delete restore UI + purge policy | Scale + compliance |
| **API conventions** (in PREREQUISITE): `page/page_size ≤ 200`, `sort=-field`, `filter[field][op]=`, `include=` expansions, sparse `fields=`, `/bulk` endpoints returning partial-success reports, downloads always via job → signed URL, `Idempotency-Key` on non-idempotent POSTs, `ETag/If-Match` on masters (optimistic lock), consistent UUID ids + human numbers via sequences | One contract for web, mobile, integrations |
| **Modular monolith boundaries**: each module owns its tables (only the owner writes them); cross-module access via service interfaces or domain events; enforced by `import-linter` contracts in CI (no importing another module's repository) | Keeps 44 modules decoupled; enables later extraction |
| **Celery**: queues `notifications, emails, documents (bulk PDFs), reports, integrations (rate-limited adapters), scheduled`; every task carries `institution_id` and sets the RLS context; dead-letter queue + admin retry UI for outbox/webhook failures; graceful shutdown | Reliability at scale |
| **Ops modes**: readiness vs liveness probes; **read-only/maintenance mode** toggle (platform or per tenant) for exam days and migrations; nightly demo-tenant reset | Exam-day resilience |
| **Supply-chain security in CI**: `pip-audit`/`npm audit`, SAST (bandit/semgrep), container scan (trivy), secrets scan (gitleaks), SBOM | Orbit had none |

### 4.3 Frontend architecture deltas

- **Feature-folder convention** `src/features/<module>/{api,hooks,pages,components,types}` (Orbit: flat `pages/` + `api/`); shared `components/ui|shared|layout|charts`.
- **Generated API types** from OpenAPI (`openapi-typescript`) + thin `api/*.ts` wrappers; RHF + Zod on **every** form (Orbit: 5 files); `DataTable` with server-side pagination/sort/filter/column chooser/export; virtualized grids for marks/attendance with keyboard-first entry; command palette + global search; background-jobs tray; notification center; print stylesheets; WCAG AA (axe in Playwright).
- Guards: `PrivateRoute / FeatureRoute / PermissionRoute / PortalRoute / SuperAdminRoute / AdminShellRoute`; `useFeature`, `usePermission`, **`useVisibility(module)`** → renders "Mine | Department | College | All" tabs from the API's `visibility` meta (§8).
- Navbar: institution/college switcher, academic year/term selector, global search, jobs tray, notifications, impersonation banner.
- Portals (outside admin shell): student, parent, faculty, alumni, warden, driver, applicant, evaluator, scholar.

---

## 5. Feature inventory by phase (44 phases + 00)

Legend: **R** reuse · **R+** reuse & extend · **N** new. Each line maps to §7 feature keys and §8 visibility rules.

### Round 0 — Foundation & platform services

| Phase | Module | Type | Scope summary |
|---|---|---|---|
| 00 | Prerequisite / project setup | R+ | Monorepo skeleton, stack pins, coding standards, tenancy + RLS, mixins (incl. optimistic lock), base repository + visibility hook, envelope + error catalogue, registries (features/packs/metrics/adapters/events), scaffolder, CI guards, ADR folder |
| 01 | Infrastructure & platform services | R+ | Backend/frontend bootstrap, compose, Alembic initial, health, middleware, observability, file service, `background_jobs` + tray, outbox relay, idempotency, Redis pub/sub WebSocket, global search scaffold, shell (sidebar, year/term selector, college switcher), generated TS types pipeline |
| 02 | Auth, RBAC, feature flags, visibility & entitlements | R+ | JWT/OTP/refresh rotation/blacklist/lockout, forgot/reset/change password, MFA, sessions, login history, password policy, IP allowlist, SSO hooks, roles + permission matrix UI, **role scopes**, **VisibilityResolver + ownership links**, PII masking permissions, external-examiner/applicant accounts, credential sheets, feature registry + flags + `feature_required`, entitlements (seats/storage/SMS), impersonation |
| 03 | Institution structure, sessions & settings | N | Institution profile/type/pack/TZ/locale/currency, colleges, faculties, departments, academic years & terms (status machine, rollover/close procedures), settings k/v (+ theme inheritance), holidays, `number_sequences`, provider test buttons |
| 04 | Communication core & workflow engine | R+ | Templates by event (versioned), channels, DLT/WhatsApp template registries, preferences/quiet hours/digest/unsubscribe, message logs, announcements, WebSocket bell; **approval-workflow engine** (definitions per module, steps by role/scope, SLA, delegation, escalation, inbox) |
| 05 | Programmes, regulations & curriculum | N | Programmes, regulations (rules JSONB, approve/clone/lock via workflow/resolution), structure terms, courses (L-T-P-C, types, syllabus, pre/co/anti-requisites), elective baskets, minors/honours, MOOC equivalence, grading scales, public catalogue feed, value-added/CE courses |
| 06 | Staff, faculty, HR, recruitment & CAS | R+ | Departments/designations, staff master (regular/contract/guest/visiting with hourly remuneration), faculty profiles, qualifications, documents, service book, leave types (CL/EL/ML/duty/study/sabbatical/LTC, encashment) + leaves/balances (self + approvals), **statutory payroll** (PF/ESI/PT/TDS, Form 16, increments, arrears, loans/advances, exam & guest remuneration lines), staff attendance (biometric/self check-in/geo), holidays, recruitment (postings → reservation roster → screening → panels → appointment), **annual self-appraisal (PBAS) with reviewer workflow**, CAS/promotion with API score, workload norms |

### Round 1 — Student lifecycle

| Phase | Module | Type | Scope summary |
|---|---|---|---|
| 07 | Students, enrolment, holds & standing | R+ | Student master (APAAR/ABC, category/quota, encrypted Aadhaar, international fields), guardians + consent, documents, undertakings, programme enrolments, term records, batches/sections, promotion/detention, NEP exit/re-entry, credit transfers, transfers/migration, holds, academic standing, ID cards, bulk import, student self-service profile (self view) |
| 08 | Admissions | N | Cycles, cycle-programmes, seat matrix, public application (applicant portal), verification queue, merit lists, counselling & reservation-aware allotment, offers, admit → student, lateral entry, CSV import, refunds, enquiry CRM, open enrolment |
| 09 | Offerings, faculty allocation & registration | N | Offerings, targets, allocation proposals & workload, registration windows, student cart (credits/prereq/seat/hold checks), elective allocation, waitlists, advisor approval, arrears, overrides, fee linkage, rosters |
| 10 | Timetable & rooms | R+ → N | Rooms, slot groups, versioned timetables → `class_sessions`, conflicts, substitutions, faculty/room/section/my views, iCal, optional auto-generate |
| 11 | Attendance & eligibility | R+ → N | Session-wise attendance (manual/QR/biometric/geo/RFID/offline), finalize lock, extra classes, on-duty, summaries + shortfall calculator, condonation workflow, eligibility snapshots, detention lists, guardian alerts; **my attendance** (student/staff) vs offering/department/all views |
| 12 | Fees, scholarships & no-dues | R+ | Fee structures by programme × regulation × batch × category × quota × term (effective-dated), instalment schedules + automatic late fees, fee-linkage invoices, discounts/concessions (incl. staff-ward), scholarships (NSP refs, disbursement), fines, gateway interface + Razorpay + UPI QR, **offline payments** (challan/NEFT/DD with UTR reconciliation, cheque-bounce handling), receipts (PDF/thermal) with cancellation-by-approval, day-book/cash-bank registers, dues, multi-department no-dues, refunds, GST, ledgers, accounting export; **my dues/receipts** vs counter/all |
| 13 | Internal assessment, OBE definitions, LMS-lite & projects | N | Schemes/components, offering assessments, question→CO map, internal marks workflow, CIA consolidation, change requests; PEO/PO/PSO/CO + CO-PO matrix; LMS content/assignments/quizzes/materials/discussions/lesson plans/course files; projects/dissertations; online-class links |

### Round 2 — Examinations & outcomes

| Phase | Module | Type | Scope summary |
|---|---|---|---|
| 14 | Exam administration | N | Sessions, papers/date-sheet + clash detection, registration (eligibility, fees, holds), hall tickets (QR, offline PDF, optional face-match adapter), seating, invigilation roster, QP management (blueprints, encrypted upload, **watermarked print with print log**), hall attendance, malpractice reporting, online/proctored, practical/viva/dissertation |
| 15 | Evaluation & results | N | Bundles, dummy coding, valuation assignments, question-wise valuations, onscreen optional, double valuation → third, moderation, decode, result runs → grades/SGPA/CGPA/class, arrears, verify/approve/publish, versioned immutable results, grade cards, tabulation, analysis, legacy import, **script custody & retention/destruction register** |
| 16 | Post-result services | N | Retotaling/photocopy/revaluation/challenge, supplementary loop, malpractice inquiry→appeal, withheld, detention/readmission, transcripts, rank lists |
| 17 | OBE attainment & CQI | N | Attainment configs/runs (CO/PO/PSO), indirect via surveys, gaps, CQI, NBA export |
| 18 | Degrees, convocation & digital credentials | N | Eligibility engine, convocation, awards + serials/QR, provisional certificates, DigiLocker/NAD/ABC adapters, eSign, verification portal |

### Round 3 — Campus services

| Phase | Module | Type | Scope summary |
|---|---|---|---|
| 19 | Library | R+ | Catalogue/copies/e-resources, members, circulation, fines, OPAC, barcode/RFID, Koha/DSpace sync; **my books** vs all |
| 20 | Hostel, mess & staff accommodation | N | Hostels/blocks/rooms/beds, fee plans, applications/allotment, room-change requests, check-in/vacate, **night roll-call attendance**, mess (plans, subscriptions, attendance, rebates, monthly bills), visitors, out-pass with guardian OTP, gate QR, complaints, discipline, no-dues, staff quarters; **my hostel** vs warden's hostels vs all |
| 21 | Transport | R | Vehicles/routes/stops/allocations, GPS/trips, live fleet, driver app, maintenance/fuel, fees |
| 22 | Inventory, procurement & bills | R+ | Stores/items/suppliers, **vendor registration portal**, indents (workflow), quotation comparison (GeM/tender refs), POs, GRN, issues, lab consumables & chemicals with safety data, assets with QR tags & depreciation, AMC links, vendor bills |
| 23 | Accounting & budget | R+ | Income/expense, budgets & utilisation, grants ledgers, fee sync, reconciliation, Tally/Zoho export, GST reports |
| 24 | Communication advanced | R | Bulk campaigns/segments, scheduled sends, announcements with **acknowledgement/read receipts**, **emergency broadcast** (all channels), WhatsApp bot flows, AI assistant (higher-ed tools), simulator, delivery analytics |
| 25 | Calendar, events & facilities | R+ → N | Academic calendar, personal iCal feeds (Google/Outlook), events (conferences/FDPs/cultural/sports; registrations, budgets, certificates), room & **equipment booking**, service desk (+ lost & found), AMC, visitor/gate, **SOS/emergency alerts** (mobile), health centre + counselling appointment slots, sports, canteen/wallet (optional) |
| 26 | Document templates, certificates & requests | R+ | Builder/renderer for all certificates (**bilingual templates**), certificate requests (fee + workflow), serial registers, bulk jobs, watermarking & time-limited signed download links |

### Round 4 — Engagement, research & quality

| Phase | Module | Type | Scope summary |
|---|---|---|---|
| 27 | Mentoring, grievances, discipline, surveys & clubs | N | Mentor assignments & logs with **appointment slots**, counselling, early-warning flags, grievances (committees, SLA, anonymous), discipline register, surveys (course-exit/faculty/SSS/programme-exit/alumni/employer/hostel/parent), clubs/NSS/NCC with **activity-hours ledger → credit mapping**, achievements |
| 28 | Placement, internships & training | N | Companies + **recruiter portal** (post drives, view shortlists, schedule PPT/rounds, feedback), drives/rounds, eligibility snapshots & overrides, offers/policies, student blacklist for policy violations, profiles/opt-out, internships (NOC letters), training programmes, resume builder, stats |
| 29 | Alumni, endowments & fundraising | N | Profiles, directory (consent), events, jobs board, campaigns, donations/80G, portal |
| 30 | Research & faculty development | N | Publications, patents, grants (budget/purchase/utilisation), consultancy, **ethics committees (IEC/IAEC) approvals**, **seed grants, publication incentives & travel grants (workflow)**, FDPs, awards, MoUs/collaborations, incubation, API score |
| 31 | PhD & research-scholar management | N | Admission, guides & load, coursework (exemptions), DC/RAC meetings, progress reports, fellowships, **extension & change-of-guide requests**, synopsis, thesis + plagiarism, examiners, viva, award, ETD upload, scholar portal |
| 32 | Accreditation & compliance (IQAC) | N | Frameworks/criteria, metric registry, overrides, evidence, cycles & responses (incl. best practices/distinctiveness narratives), exports, audit registers |
| 33 | Governance: committees, meetings, legal & e-file | N | Committees, meetings, minutes/resolutions, ATRs, legal cases, RTI, **statutory/AG audit paras register**, e-file, policies |
| 34 | Affiliation management | N | Applications/inspections/orders, programme approvals, fee schedules, college data submissions, exam centres, dashboards |

### Round 5 — Platform & delivery

| Phase | Module | Type | Scope summary |
|---|---|---|---|
| 35 | Dashboards, analytics & early-warning | R+ | Role dashboards, chart registry, drill-down, student risk score, materialized read models |
| 36 | Reports | R+ | Report registry, statutory reports, scheduled |
| 37 | Audit logs & settings | R | Audit UI (hash-chain verify), exam audit views, settings, retention policies |
| 38 | Super admin & SaaS | R+ | Institutions, Features tab & matrix, plans/billing, usage metering, impersonation, `support_agent` read-only role, onboarding wizard (by institution type), suspension/export/reset, read-only mode, platform announcements, tenant support tickets, **help centre & in-app feedback**, integration health, super-admin audit |
| 39 | Portals & PWA | R+ | Student/parent/faculty/alumni/warden/evaluator/scholar/applicant/recruiter portals, PWA + push, notification center, guided tours & contextual help |
| 40 | Public website, catalogue & admission portal | R+ | Website, notices/events/gallery/enquiry, course catalogue, apply, verify, custom domains, marketing site |
| 41 | Integrations hub & data migration toolkit | N | Adapter registry, connections, API keys/webhooks, OpenAPI docs; adapters (payments/UPI/SMS/WhatsApp/email/push/SSO/LTI/video/DigiLocker/NAD/ABC/NSP/SWAYAM/Scopus/ORCID/plagiarism/Koha/DSpace/Shodhganga/biometric/RFID/Tally/eSign/eKYC/Workspace); migration toolkit (templates, validation, dry-run, apply, rollback, legacy results) |
| 42 | Flutter mobile app | R+ | Full role-based UI per §10 (shells, tabs, screen registry, offline, deep links, QR, payments, printing) |
| 43 | Testing, security & privacy hardening | R+ | Fixtures, isolation/scope/visibility tests, authz/feature audit, immutability tests, SGPA golden tests, load tests, security headers, DPDP (consent, DSR), PII masking, retention, **VAPT before launch + ISO 27001-readiness checklist**, SAST/dependency/secret scans in CI, seed demo institution (`--type university|autonomous|affiliated`), access matrix, QA plan |
| 44 | Deployment, CI/CD & operations | R | Dockerfiles, compose prod, Actions → ghcr → orbit-infra, expand/contract migrations, backups + restore drills, monitoring/alerts, runbooks, launch tracker |

**Deliberately not carried from Orbit** (school-specific): PTM (→ mentoring), homework (→ assignments), class promotion (→ term promotion), personal expenses, vendor inventory (optional flag), admission kanban (→ cycles).

---

## 6. Academic core design (detail for Prompts 03–18 and `Database_Schema.sql`)

Conventions on every table: `id UUID PK`, `institution_id`, `created_at/updated_at`, `created_by`, `is_active`, `deleted_at/deleted_by`, `version` (optimistic lock on masters), money INTEGER paise; `college_id` where a row belongs to one college; tenant-scoped UNIQUEs include `institution_id`.

### 6.1 Academic structure (Phases 03, 05, 07)

```
academic_years ( college_id NULL, name, start_date, end_date, is_current, is_locked, UNIQUE(institution_id, college_id, name) )
academic_terms ( college_id NULL, academic_year_id, name, term_type, sequence, start_date, end_date, registration_start, registration_end, add_drop_end,
                 last_instruction_date, is_current, is_locked, status(planned|registration|in_progress|exam|result_processing|closed) )
faculties ( college_id, code, name, dean_staff_id )
programs ( college_id, faculty_id NULL, department_id, code, name, degree_name, level(certificate|diploma|ug|pg|pg_diploma|integrated|mphil|phd),
           mode(regular|part_time|distance|online), term_pattern(semester|year|trimester), duration_years, total_terms, max_duration_years,
           sanctioned_intake, lateral_intake, approving_body, exam_authority(university|autonomous_college), is_nep_multidisciplinary, is_open_enrolment )
regulations ( college_id NULL, code, name, effective_from_admission_year, grading_scale_id, rules JSONB, status(draft|approved|active|superseded), approved_by/at, approval_resolution_id, locked_at )
  rules JSONB: attendance_min_pct 75, condonation_floor_pct 65, condonation_fee_paise, ese_pass_min_pct 45, total_pass_min_pct 50, cia_pass_min_pct,
    include_failed_credits_in_sgpa, cgpa_attempt_policy(latest|best), percentage_formula "cgpa*10", class_rules [{name,min_cgpa,first_attempt_only}],
    grace {max_per_course,max_courses_per_term,max_total_per_term}, double_valuation {enabled,discrepancy_pct 15,resolution}, reval {min_delta_to_apply 5, fees…},
    exit_points [{after_term,award,min_credits}], minor_credits, honours_credits, mooc_max_credits, max_backlogs_for_promotion, min_cgpa_for_degree,
    standing_rules [{status:"probation", when:{cgpa_below:5.0, consecutive_terms:1}}, {status:"dismissal", when:{cgpa_below:4.0, consecutive_terms:2}}]
program_regulations ( program_id, regulation_id, rules_override JSONB, total_credits_required, status )
program_structure_terms ( program_regulation_id, term_number, name, min_credits, max_credits, normal_credits, is_exit_point, exit_award )
courses ( college_id NULL, department_id, regulation_id, code, title, course_type(core|program_elective|open_elective|lab|integrated_lab|project|internship|seminar|mooc|audit|
          mandatory_non_credit|ability_enhancement|skill_enhancement|value_added|minor|honours), L,T,P, credits, contact_hours_per_week, assessment_scheme_id NULL, cia_max, ese_max,
          is_credit_bearing, is_gradable, min_seats, max_seats, syllabus JSONB, textbooks JSONB, is_public_catalog, status, UNIQUE(institution_id, regulation_id, code) )
course_prerequisites ( course_id, related_course_id, relation(prerequisite|corequisite|antirequisite), min_grade, is_hard )
curriculum_courses ( program_regulation_id, term_number, course_id, elective_basket_id NULL, is_mandatory, credit_bucket, sequence )
elective_baskets ( program_regulation_id, code, name, basket_type(program_elective|open_elective|minor|honours|mooc|vertical), term_number, min_choose, max_choose, credits_required, allocation_mode(priority_cgpa|fcfs|lottery|manual) ) ; elective_basket_courses ( basket_id, course_id, offering_department_id )
batches ( college_id, program_id, program_regulation_id, admission_year, entry_type(regular|lateral), code, expected_graduation_year, current_term_number, status ) ; batch_sections ( batch_id, name, capacity, class_advisor_staff_id )
students ( college_id, user_id, registration_number, enrolment_number, apaar_id, abc_id, aadhaar_encrypted, names, dob, gender, blood_group, category(GEN|EWS|OBC_NCL|OBC_CL|SC|ST), sub_category, is_pwd, pwd_pct, minority, religion,
           nationality, is_international, passport JSONB, visa JSONB, frro JSONB, domicile_state, photo_url, contacts, addresses JSONB, guardians JSONB, guardian_portal_consent, bank_details JSONB, admission_quota, admission_mode, admission_date,
           status(provisional|admitted|active|on_break|detained|dropped_out|transferred|exited|graduated|alumni|expelled|deceased), UNIQUE(institution_id, registration_number), UNIQUE(institution_id, apaar_id) WHERE apaar_id IS NOT NULL )
student_guardians ( student_id, user_id NULL, relation, name, phone, email, is_primary, portal_access BOOL )
student_program_enrollments ( college_id, student_id, program_id, batch_id, program_regulation_id, department_id, admission_date, entry_type(regular|lateral|migrated|readmission|exit_reentry), entry_term_number, specialization, minor_program_id, is_honours, expected_exit_term,
           status(active|break|detained|completed|exited_early|withdrawn|transferred|expelled), exit_award, exit_date, credits_earned, cgpa, academic_standing(good|warning|probation|dismissal), UNIQUE INDEX one_active(student_id) WHERE status IN ('active','break','detained') )
student_term_records ( student_program_enrollment_id, term_id, term_number, section_id, roll_number, status, credits_registered, credits_earned, sgpa, cgpa, attendance_pct, result_status )
student_holds ( student_program_enrollment_id, hold_type(registration|exam|transcript|graduation|hostel|library|all), reason, placed_by/at, released_by/at, source_type, source_id )
student_undertakings ( student_id, undertaking_type(anti_ragging|conduct|hostel_rules|data_consent|custom), template_id, accepted_at, ip, signature_url )
course_offerings ( college_id, term_id, course_id, department_id, section_code, coordinator_staff_id, max_seats, enrolled_count, waitlist_count, delivery_mode, online_class_link, assessment_scheme_id NULL, is_arrear_only,
           status(planned|open|closed|in_progress|marks_entry|completed|cancelled), UNIQUE(institution_id, term_id, course_id, section_code) )
course_offering_faculty ( offering_id, staff_id, role, hours_per_week ) ; course_offering_targets ( offering_id, batch_id, section_id NULL, term_number )
credit_transfers ( student_program_enrollment_id, term_id, source(swayam|nptel|coursera|other_mooc|abc|other_university|prior_learning|internal_prior), source_course_code, source_title, source_institution, credits, source_grade, equivalent_course_id, elective_basket_id, certificate_url, abc_credit_ref, status(submitted|verified|approved|rejected|credited), result_id )
number_sequences ( college_id NULL, scope_key, pattern, next_value, UNIQUE(institution_id, college_id, scope_key) )
```
Rules: courses/structures owned by a regulation — never mutate under `active`; clone. Students pinned via `program_regulation_id`. NEP exit = `exited_early` + `degrees_awarded`; re-entry = new enrolment + `credit_transfers`. Σ curriculum credits = `total_credits_required` on approve. Batch promotion creates term records; backlogs > max → `detained`; `standing_rules` evaluated at each publish. Holds block the action named by `hold_type`.

### 6.2 Admissions (Phase 08)

```
admission_cycles ( college_id NULL, academic_year_id, name, level, application_fee_paise, opens_at, closes_at, status(draft|open|closed|merit_processing|counselling|completed|archived), form_config JSONB, required_documents JSONB )
admission_cycle_programs ( cycle_id, program_id, college_id, intake, lateral_intake, entrance_source(jee|neet|cuet|state_cet|gate|cat|institution_test|merit_only), eligibility_rules JSONB, merit_formula JSONB )
seat_matrix ( cycle_id, program_id, college_id, quota, category, seats, filled )
applicants ( cycle_id, application_number, user_id, personal fields, category, is_pwd, quota_claimed, entrance JSONB, qualifying_exams JSONB, documents JSONB, merit_score, status, application_fee_invoice_id, admitted_student_id, entry_type, source, UNIQUE(institution_id, application_number) )
applicant_preferences ( applicant_id, program_id, college_id, priority ) ; applicant_document_verifications ( applicant_id, doc_type, file_url, status, verified_by, remarks )
merit_lists ( cycle_id, program_id, college_id, quota, category, formula_snapshot, status ) ; merit_list_entries ( merit_list_id, applicant_id, rank, category_rank, score, tie_break )
counselling_rounds ( cycle_id, round_number, choice_filling_start/end, allotment_at, reporting_deadline, status ) ; seat_allotments ( round_id, applicant_id, program_id, college_id, seat_matrix_id, quota, category, status(allotted|accepted|float|freeze|upgraded|declined|lapsed|admitted), fee_invoice_id )
admission_offers ( applicant_id, program_id, college_id, offer_type(provisional|confirmed), valid_until, conditions, letter_url, status ) ; enquiries ( source, name, contacts, program_interest, stage, assigned_to, notes ) ; student_transfers ( student_id, transfer_type, from/to JSONB, certificate numbers, status, fee_invoice_id )
```
Applicant status: `draft → submitted → fee_paid → under_verification → verified | doc_rejected(→resubmit) → merit_listed → allotted → accepted → provisionally_admitted → admitted` (creates student + enrolment + term record + registration number); side exits `waitlisted|declined|lapsed|withdrawn|rejected`. Merit = Σ weight × normalised field; reservation-aware allotment (GEN first, PwD horizontal, de-reservation last round); registration number only on admit.

### 6.3 Course registration (Phase 09)

```
registration_windows ( college_id, term_id, name, window_type(regular|add_drop|late|arrear|summer|audit|minor_honours), applies_to JSONB, starts_at, ends_at, late_fee_paise, requires_advisor_approval, requires_fee_clearance, max_credits_override, status )
course_registrations ( student_program_enrollment_id, term_id, student_term_record_id, window_id, status(draft|submitted|advisor_pending|approved|changes_requested|rejected|locked), total_credits, fee_invoice_id, submitted_at, approved_by/at, locked_at, UNIQUE(student_program_enrollment_id, term_id) )
course_registration_items ( registration_id, offering_id, course_id, registration_type(regular|arrear|improvement|audit|minor|honours|re_registration|mooc), attempt_number, priority, status(selected|waitlisted|confirmed|dropped|withdrawn|rejected|substituted), is_credit_bearing, prerequisite_override_by )
elective_choice_forms ( student_program_enrollment_id, elective_basket_id, term_id, choices JSONB, allocated_course_id, allocation_run_id, status ) ; elective_allocation_runs ( elective_basket_id, term_id, mode, params, summary )
offering_waitlists ( offering_id, student_program_enrollment_id, position, status(waiting|offered|promoted|expired|cancelled), offered_until )
student_arrears ( student_program_enrollment_id, course_id, first_failed_term_id, last_attempt_term_id, attempts, status(open|registered|cleared|waived), cleared_result_id, UNIQUE(student_program_enrollment_id, course_id) )
```
Rules: credit min/max; hard prerequisite needs passing result; co-requisite in same registration; anti-requisite blocks; registration hold blocks submit; seats under `FOR UPDATE`; `priority_cgpa` allocation; arrear attempt = attempts + 1; invoice = tuition + per-credit arrear + late fee; auto-lock at `add_drop_end`; later drops = `W`.

### 6.4 Timetable, attendance & eligibility (Phases 10, 11)

```
rooms ( college_id, building_id, code, name, room_type, capacity, exam_capacity, features JSONB, is_bookable ) ; time_slots ( college_id, slot_group, name, sequence, start_time, end_time, slot_type )
timetables ( college_id, term_id, scope_type(section|batch|department), scope_id, name, version, status(draft|published|archived), effective_from )
timetable_entries ( timetable_id, term_id, offering_id, section_id, day_of_week, time_slot_id, room_id, staff_id, session_type, week_pattern, slot_span, UNIQUE per (term, room|staff|section, day, slot) WHERE is_active )
timetable_substitutions ( timetable_entry_id, on_date, substitute_staff_id, reason, status )
class_sessions ( term_id, offering_id, timetable_entry_id, session_date, time_slot_id, start/end, staff_id, session_type, topic, lesson_plan_item_id, online_link, status(scheduled|conducted|cancelled|rescheduled), attendance_status(not_taken|taken|finalized) )
student_class_attendance ( session_id, student_program_enrollment_id, status(present|absent|late|on_duty|leave|medical|exempt), source(manual|biometric|qr|app|rfid), marked_by/at )
on_duty_requests ( student_program_enrollment_id, from/to, reason_type, documents, recommended_by, approved_by, status, sessions_applied )
attendance_summaries ( offering_id, student_program_enrollment_id, totals, pct, eligibility(eligible|condonable|not_eligible|condoned), computed_at )
attendance_condonations ( student_program_enrollment_id, term_id, offering_id NULL, actual_pct, reason_type, documents, fee_invoice_id, workflow_instance_id, status )
term_eligibility ( student_term_record_id, offering_id, attendance_pct, cia_marks, is_attendance_ok, is_cia_ok, is_fee_ok, is_hold_ok, decision(eligible|detained|condoned|debarred|pending), reason_codes JSONB, decided_by/at, version )
```
Rules: `pct = (present + on_duty + late)/(total − exempt)`; ≥ 75 eligible; 65–75 condonable (fee + workflow); < 65 detained. Publish generates sessions (minus holidays). Finalized sessions append-only. Guardian alerts after N absences; 3 checkpoints. Staff leave flags substitutions.

### 6.5 Examinations (Phases 13–16)

**Assessment configuration & internal marks**
```
assessment_schemes ( regulation_id, code, name, applies_to_course_types, cia_weight, ese_weight, cia_max, ese_max, pass_rules JSONB, is_default )
assessment_components ( scheme_id, code, name, category(cia|ese_theory|ese_practical|viva|project_review), max_marks, scaled_to, weight_pct, best_of JSONB, sequence, is_mandatory, co_mappable )
offering_assessments ( offering_id, component_id, name, max_marks, scheduled_on, marks_entry_deadline, status(planned|conducted|marks_entry|submitted|verified|locked), question_paper_id, locked_by/at )
assessment_questions ( offering_assessment_id, question_no, max_marks, co_id, bloom_level, part )
internal_marks ( offering_assessment_id, student_program_enrollment_id, marks, is_absent, is_exempt, question_wise JSONB, entered_by/at, verified_by, version )
cia_consolidations ( offering_id, student_program_enrollment_id, component_breakdown JSONB, cia_total, cia_scaled, status(computed|hod_approved|locked|submitted_to_university) )
marks_change_requests ( target_type(internal_mark|script_final|course_result), target_id, old/new JSONB, reason, evidence_url, workflow_instance_id, status )
student_projects ( offering_id, title, project_type(mini|major|dissertation|internship_project), guide_staff_id, co_guide, external_guide JSONB, status ) ; project_members ; project_reviews ( project_id, review_no, scheduled_on, panel JSONB, rubric_scores JSONB, marks, offering_assessment_id )
```
**Sessions, registration, hall tickets, conduct**
```
exam_sessions ( college_id NULL, term_id, name, exam_kind(regular|supplementary|arrear|improvement|special|summer|practical), coe_staff_id, registration_start/end, late_fee_until, fee_rules JSONB, hall_ticket_release_at, start/end_date, valuation_mode(single|double), discrepancy_pct, grading_scale_id,
                status(draft|registration_open|registration_closed|scheduled|in_progress|valuation|result_processing|results_published|closed), is_locked )
exam_papers ( exam_session_id, course_id, paper_code, paper_type(theory|practical|project_viva|dissertation|online), exam_date, session_slot(FN|AN|EVE), start_time, duration, max_marks, qp_pattern JSONB, quiz_id NULL, status )
exam_registrations ( college_id, exam_session_id, student_program_enrollment_id, status(draft|submitted|fee_pending|confirmed|cancelled|debarred), fee_invoice_id, total_fee_paise, hall_ticket_number, hall_ticket_qr_token, eligibility_snapshot JSONB, UNIQUE(exam_session_id, hall_ticket_number) )
exam_registration_items ( exam_registration_id, exam_paper_id, course_id, attempt_type(regular|arrear|improvement|grade_improvement), attempt_number, fee_paise, eligibility, status(registered|cancelled|absent|appeared|malpractice|withheld) )
exam_seating_plans ( exam_session_id, exam_date, session_slot, room_id, capacity_used, layout JSONB, status ) ; exam_seat_allocations ( seating_plan_id, exam_registration_item_id, seat_number, row, col )
invigilation_duties ( exam_session_id, exam_date, session_slot, room_id, staff_id, role(chief_superintendent|hall_superintendent|invigilator|reliever|flying_squad|observer), status, remuneration_paise )
exam_attendance ( exam_registration_item_id, status(present|absent|late|malpractice), answer_booklet_number, marked_by/at )
question_paper_assignments ( exam_paper_id, setter_staff_id / external_setter JSONB, set_label, status(invited|accepted|submitted|scrutinised|approved|selected|printed|rejected), file_key_encrypted, blueprint_id, scrutiny_by, remuneration_paise )
```
**Scripts, valuation, moderation**
```
answer_script_bundles ( exam_paper_id, room_id, bundle_number, script_count, status(created|coded|dispatched|received|in_valuation|valuated|decoded), coded_by/at )
answer_scripts ( exam_registration_item_id, bundle_id, dummy_number, barcode, pages, scan_url, status(received|coded|in_valuation|valuated|discrepancy|third_valuation|finalized|moderated|decoded|revaluation), UNIQUE(bundle_id, dummy_number) )
valuation_assignments ( exam_paper_id, bundle_id, evaluator_staff_id / external_evaluator JSONB, evaluator_type(internal|external), valuation_round, status, due_at, remuneration_paise )
script_valuations ( answer_script_id, valuation_round, evaluator_id, marks, question_wise JSONB, annotations_url, submitted_at, is_locked )
script_final_marks ( answer_script_id, marks_v1, marks_v2, marks_v3, discrepancy, rule_applied, computed_marks, moderated_marks, moderation_action_id, final_marks, status )
moderation_actions ( exam_paper_id, action_type(scale_up|scale_down|add_flat|grace|normalize|cap), rule JSONB, justification, proposed_by, approved_by, affected_count, status(proposed|approved|applied|reverted) )
```
**Results, credentials, post-result**
```
grading_scales ( regulation_id NULL, name, scale_type(absolute|relative), ranges JSONB, relative_config JSONB, special_grades JSONB )
result_processing_runs ( exam_session_id, scope JSONB, run_type(provisional|final|revaluation|supplementary_merge|correction|legacy_import), status(queued|computing|computed|verified|approved|published|rolled_back|failed), triggered_by, verified_by, approved_by, approval_resolution_id, published_at, stats JSONB, config_snapshot JSONB, checksum )
student_course_results ( college_id, student_program_enrollment_id, term_id, course_id, offering_id, exam_session_id, exam_registration_item_id, attempt_number, attempt_type(regular|arrear|improvement|credit_transfer|audit|re_registration|legacy), credits, cia_marks/max, ese_marks/max, grace_marks, grace_reason, moderation_delta,
                         total_marks/max, percentage, letter_grade, grade_point, result_status(pass|fail|absent|withheld|malpractice|detained|incomplete|withdrawn|exempted|audit_pass|audit_fail), counts_toward_cgpa, is_current, version, supersedes_id, run_id, status(draft|computed|verified|approved|published|superseded), published_at, hash,
                         UNIQUE(student_program_enrollment_id, course_id, attempt_number, version) )
student_term_results ( student_term_record_id, run_id, credits_registered, credits_earned, sgpa, cgpa, cumulative_credits, backlog_count, result_class, status, version, is_current )
result_publications ( run_id, exam_session_id, published_by/at, audience(student|college|public), notify JSONB, withheld_list JSONB ) ; grade_cards ( student_term_result_id, document_number, pdf_url, qr_token, template_id, version ) ; transcripts ( student_program_enrollment_id, transcript_type, document_number, pdf_url, verification_token, fee_invoice_id, workflow_instance_id, status )
reval_requests ( exam_session_id, exam_registration_item_id, answer_script_id, request_type(retotaling|photocopy|revaluation|challenge), fee_invoice_id, status(submitted|fee_paid|assigned|evaluated|marks_changed|no_change|rejected|closed), original/revised_marks, delta, refund_due )
malpractice_cases ( exam_session_id, exam_registration_item_id, case_number, category, evidence, reports, committee_id, hearing_at, punishment(none|warning|cancel_paper|cancel_session|debar_terms|expel), debar_until_term_id, status(reported|under_inquiry|hearing_scheduled|decided|appealed|appeal_decided|closed) )
legacy_result_imports ( batch_id, term_number, file_url, mapping JSONB, validation_report JSONB, status(uploaded|validated|applied|rolled_back), run_id )
degree_eligibility_checks ( student_program_enrollment_id, credits_earned/required, bucket_breakdown JSONB, backlog_count, cgpa, duration_ok, dues_cleared, holds_clear, mandatory_noncredit_ok, is_eligible, reasons )
convocations ( name, held_on, venue, registration_deadline, fee_paise, status ) ; convocation_registrations ( convocation_id, student_program_enrollment_id, mode(in_person|absentia), fee_invoice_id, gown_size )
degrees_awarded ( student_program_enrollment_id, award_type(certificate|diploma|degree|honours|pg_diploma|phd), degree_name, specialization, result_class, cgpa, date_of_award, certificate_number, serial_no, convocation_id, pdf_url, status(recommended|council_approved|issued|cancelled|reissued), approval_resolution_id, digital_credential_id, esign_ref )
digital_credentials ( entity_type(grade_card|transcript|degree|provisional_certificate), entity_id, channel(digilocker|nad|abc|internal), payload_hash, payload, pushed_at, ack_ref, status, response )
abc_credit_ledger ( student_id, apaar_id, student_course_result_id UNIQUE, term_id, course_code, course_title, credits, letter_grade, grade_point, academic_year, status(pending|pushed|acknowledged|failed|revoked), push_batch_id )
```
**State machines** — Component marks `planned → conducted → marks_entry → submitted → verified (HOD) → locked (exam cell)`; post-lock via change requests. Script `received → coded → in_valuation → valuated → [discrepancy → third_valuation] → finalized → [moderated] → decoded`. Result `draft → computed → verified → approved (COE) → published`; later changes = new version; `withheld` is a status; rollback only before publish; trigger blocks UPDATE on published rows except `is_current`/`status→superseded`.

**Formulas & rules** — `cia_total` per component (`best_of`, Σ marks/max × scaled_to) scaled to `cia_max`; ESE = `final_marks` scaled. Pass: `ese ≥ ese_pass_min_pct` AND `total ≥ total_pass_min_pct` (AND `cia ≥ cia_pass_min_pct` if set). Absolute grade by ranges; relative by z-bands. **SGPA** = Σ(Cᵢ×GPᵢ)/ΣCᵢ; **CGPA** over `cgpa_attempt_policy` attempts; percentage = `percentage_formula`; class = first satisfied `class_rules`. Double valuation: `|V1−V2| > discrepancy_pct × max` → third; `avg_closest_two`. Grace within caps. Revaluation applies if `|delta| ≥ min_delta_to_apply`. Hall-ticket gate: `confirmed` AND items `eligible|condoned` AND no debar/hold AND (optional) no dues. Exam clash blocks date-sheet publish. Degree eligibility: credits per bucket, `backlog_count=0`, CGPA ≥ min, duration ≤ max, mandatory non-credit, no hold, dues cleared.

### 6.6 OBE (Phases 13, 17)

```
outcome_definitions ( scope_type(institution|program), scope_id, outcome_type(PEO|PO|PSO), code, statement, framework, sequence ) ; peo_po_mappings ( peo_id, po_id, level ) ; course_outcomes ( course_id, code, statement, bloom_level, sequence ) ; co_po_mappings ( course_outcome_id, outcome_id, level, justification )
attainment_configs ( scope_type, scope_id, target_student_pct, target_marks_pct, levels JSONB, direct_weight, indirect_weight, cia_weight_in_direct, ese_weight_in_direct, co_target_level, po_target_level )
attainment_runs ( scope_type(offering|program_batch), scope_id, config_snapshot, status ) ; co_attainments ( offering_id, course_outcome_id, run_id, students_assessed, students_above_target, direct_pct, direct_level, cia_level, ese_level, indirect_level, final_level, target_level, gap ) ; po_attainments ( program_id, batch_id, outcome_id, run_id, direct_level, indirect_level, final_level, target_level, gap, contributing_courses ) ; cqi_actions ( scope_type, scope_id, outcome_id, gap, action_text, owner_staff_id, due_on, status, evidence_url )
```
Formulas: CO marks = Σ question marks tagged to CO; attainment = % students ≥ `target_marks_pct` → level; direct CO = `cia_weight × avg(CIA levels) + ese_weight × ESE level`; final CO = `direct_weight × direct + indirect_weight × indirect`; course→PO = Σ(CO_final × level)/Σ level; programme PO = mean; gap → CQI. Single write path into `internal_marks`.

### 6.7 Faculty, PhD, student support, hostel, placement, alumni, LMS, events/facilities, governance (Phases 06, 13, 20, 25, 27–31, 33)

```
faculty_profiles ( staff_id UNIQUE, department_id, college_id, ids (aicte, orcid, scopus, scholar, vidwan), highest_qualification, is_phd, is_phd_guide, guide_recognition_no, max_scholars, experience months, specializations, api_score, cadre ) ; faculty_qualifications ; faculty_workloads ( staff_id, term_id, hours by type, total, max_allowed, status ) ; course_allocation_proposals ; lesson_plans ; course_files
job_postings ( title, department_id, cadre, vacancies, reservation JSONB, opens/closes, status ) ; job_applications ( posting_id, applicant JSONB, documents, api_score, status(applied|screened|shortlisted|interviewed|selected|offered|joined|rejected) ) ; interview_panels ; cas_applications ( staff_id, from_cadre, to_cadre, api_breakdown JSONB, workflow_instance_id, status )
publications, patents, research_projects, consultancies, faculty_developments, faculty_awards, mous ( partner, type, signed_on, valid_to, activities JSONB ), collaborations, incubation_startups ( name, founders, stage, funding_paise, status )
research_scholars ( student_program_enrollment_id, guide_staff_id, co_guide_staff_id, mode(full_time|part_time), fellowship_type, registration_date, coursework_status, status(admitted|coursework|registered|synopsis_submitted|thesis_submitted|under_evaluation|viva_scheduled|awarded|discontinued) )
doctoral_committees ( scholar_id, members JSONB ) ; dc_meetings ( scholar_id, meeting_no, held_on, minutes, recommendations, status ) ; scholar_progress_reports ( scholar_id, period, report_url, guide_remarks, dc_rating, status ) ; scholar_fellowships ( scholar_id, type, monthly_paise, from/to, contingency_paise )
thesis_submissions ( scholar_id, stage(pre_synopsis|synopsis|thesis|revised_thesis), file_url, similarity_pct, plagiarism_report_url, status ) ; thesis_examiners ( thesis_id, examiner JSONB, is_external, state, report_url, recommendation(accept|minor|major|reject), status ) ; viva_voce ( thesis_id, scheduled_at, panel JSONB, result, report_url ) ; etd_uploads ( thesis_id, repository(shodhganga|institutional), handle, uploaded_at )
mentor_assignments ( mentor_staff_id, student_program_enrollment_id, term_id ) ; mentoring_sessions ( concerns JSONB, action_items, follow_up_on, is_confidential ) ; counselling_referrals ; risk_flags ( student_program_enrollment_id, score, factors JSONB, level, computed_at )
scholarships ; scholarship_applications ; grievances ; grievance_updates ; disciplinary_cases ( subject_type(student|staff), subject_id, category, committee_id, sanctions JSONB, appeal_status, status ) ; feedback_surveys ; feedback_responses ; clubs ; club_members ; club_events ; student_achievements
hostels ; hostel_blocks ; hostel_rooms ; hostel_beds ; hostel_fee_plans ; hostel_applications ; hostel_allocations (partial-unique one active bed/student) ; mess_plans ; mess_subscriptions ; mess_attendance ; hostel_visitors ; hostel_leaves ( leave_type, guardian_consent(pending|otp_verified|not_required), status(requested|approved|rejected|out|returned|late_return|absconding), late_minutes ) ; hostel_disciplinary_records ; staff_quarters ; staff_quarter_allocations
companies ; placement_drives ( eligibility_rules JSONB ) ; drive_rounds ; drive_applications ( eligibility_snapshot ) ; drive_round_results ; placement_offers ; placement_policies ; student_placement_profiles ; internships ; training_programs
alumni_profiles ; alumni_employment_history ; alumni_events ; fundraising_campaigns ; donations ( donor_type, amount_paise, campaign_id, receipt_no, is_80g )
course_modules ; course_contents ; content_views ; lms_assignments ; assignment_submissions ; quizzes ; quiz_attempts ; course_announcements ; discussion_threads ; discussion_posts
events ( event_type, organiser_department_id, dates, venue_room_id, budget_paise, participants_count, report_url, naac_criterion ) ; event_registrations ; event_certificates ; room_bookings ( room_id, requested_by, purpose, from/to, workflow_instance_id, status ) ; service_requests ( category, location, priority, assigned_to, sla_due_at, status ) ; amc_contracts ; visitor_passes ; health_visits ; insurance_policies ; sports_teams ; sports_events ; sports_participation ; canteens ; wallet_accounts ; wallet_transactions
committees ( name, type(bos|academic_council|executive_council|senate|finance|iqac|anti_ragging|icc|grievance|research_board|custom), chair_staff_id ) ; committee_members ; meetings ( committee_id, held_on, agenda JSONB, quorum_met, attendance JSONB, minutes_url ) ; resolutions ( meeting_id, number, text, action_owner, due_on, status ) ; action_taken_reports ; legal_cases ; rti_requests ; efiles ; policies
```
Rules: guide load ≤ `max_scholars`; thesis requires `similarity_pct < 10` (pack) + DC recommendation; ≥ 2 external examiners (one outside state); viva after `accept|minor`; award → `degrees_awarded(phd)` + ETD job. Regulation activation, result approval and degree award may cite a `resolutions` row when `governance.minutes` is on. Hostel late return → disciplinary note; vacate blocks `dues_cleared` until caution deposit settled. LMS grading writes scaled marks into `internal_marks`.

### 6.8 Accreditation registry & affiliation (Phases 32, 34)

```
accreditation_frameworks ; framework_criteria ( framework_id, code, parent_id, title, metric_type, max_score, period_type, metric_key ) ; metric_definitions ( key, name, unit, source_module, computation_key, params_schema, is_derived, depends_on )
metric_values ( college_id NULL, metric_key, period_label, program_id NULL, value, numerator, denominator, breakdown JSONB, source(auto|manual|override), override_reason, verified_by ) ; evidence_documents ; accreditation_cycles ; criterion_responses ; compliance_submissions ( submission_type(aqar|nirf_data|aishe|aicte_approval|ugc_annual), payload JSONB, file_url, status, ack_ref ) ; audit_registers
affiliation_applications ( college_id, academic_year_id, application_type, programs JSONB, documents, fee_invoice_id, inspection_committee, inspection_on, report_url, deficiencies, workflow_instance_id, status, order_no ) ; affiliation_program_approvals ; affiliation_fee_schedules
college_data_submissions ( college_id, term_id, exam_session_id, submission_type(student_registrations|course_registrations|cia_marks|attendance_eligibility|practical_marks|exam_registrations|internal_faculty_list), status(draft|submitted|verified|returned|accepted|locked), record_count, file_url ) ; exam_centres
```
Derived metrics with numerator/denominator/breakdown (enrolment by category, FSR, pass %, dropout, placed %, higher studies, scholarships, SSS, median salary, GPH/GPHD, PhD faculty %, FQE/FRU, publications, grants, consultancy, FDP, patents, MoUs, CBCS %, value-added courses, internships, CO/PO attainment, spend ratios, gender/PwD, grievance SLA, events, awards, affiliation counts). University cannot run results for a college whose CIA submission is not `accepted`.

---

## 7. Feature-flag registry (super-admin control of every feature)

### 7.1 Mechanism

| Piece | Design |
|---|---|
| Code registry | `app/core/features.py`: `@register_feature(key, group, name, description, default_enabled, min_plan_tier, depends_on, is_core)`; seeded into `platform_features`; **registry is the source of truth** (CI test: every router/nav/tab cites a registered key) |
| Per-tenant flags | `institution_feature_flags(institution_id, feature_key, platform_enabled, institution_enabled, source(plan|override), config JSONB, set_by, set_at)`; **effective = platform_enabled AND institution_enabled**; institution admin can only switch `institution_enabled` |
| Plans | `subscription_plans.enabled_features[]` defaults; overrides preserved and marked |
| Backend | `feature_required(key)` at router include (module keys) and on routes (sub-feature keys) → 403 `FEATURE_DISABLED`; Celery/Beat skip disabled tenants; notifications suppressed |
| Clients | `/auth/me.features[]`; React `useFeature/FeatureRoute/FeatureGuard`; `NAV_GROUPS` gated by permission **and** feature; Flutter `AuthState.hasFeature()` gates tabs/More grid |
| Dependencies | Enabling auto-enables `depends_on` (confirm); disabling a dependency is blocked; `core.*` cannot be disabled |
| Super-admin UI | Institutions → :id → **Features** tab (grouped toggles, search, apply plan defaults, diff vs plan, per-feature `config`, change log) + platform-wide institutions × features matrix |
| Audit & tests | Changes audited; tests assert 403 + hidden nav/tab when disabled |

### 7.2 Feature keys (★ = core, non-toggleable; ≈230 keys, full table in `docs/Feature_Flags.md`)

| Group | Keys |
|---|---|
| core & security | ★`core.auth`, ★`core.rbac`, ★`core.institution`, ★`core.settings`, ★`core.audit_logs`, ★`core.dashboard`, ★`core.notifications_inapp`, ★`core.background_jobs`, `security.mfa`, `security.sso`, `security.ip_allowlist_exam_ops`, `security.session_management`, `privacy.dpdp_consent`, `privacy.data_subject_requests`, `i18n.web` |
| institution | `institution.multi_college`, `institution.faculties`, `institution.holidays`, `institution.themes`, `institution.number_sequences_custom` |
| academics | `academics.programs`, `academics.regulations`, `academics.curriculum`, `academics.elective_baskets`, `academics.minors_honours`, `academics.value_added_courses`, `academics.credit_transfer_mooc`, `academics.nep_exit_reentry`, `academics.abc_apaar`, `academics.bos_approval_workflow`, `academics.public_catalog` |
| students | ★`students.core`, `students.guardians_portal`, `students.documents`, `students.undertakings`, `students.id_cards`, `students.bulk_import`, `students.holds`, `students.academic_standing`, `students.international_office`, `students.transfers_migration`, `students.self_service_profile` |
| admissions | `admissions.cycles`, `admissions.online_application`, `admissions.entrance_import`, `admissions.merit_lists`, `admissions.seat_matrix`, `admissions.counselling_allotment`, `admissions.document_verification`, `admissions.offers`, `admissions.lateral_entry`, `admissions.enquiry_crm`, `admissions.open_enrolment`, `admissions.refunds` |
| registration | `registration.core`, `registration.self_service`, `registration.advisor_approval`, `registration.elective_allocation`, `registration.waitlist`, `registration.add_drop`, `registration.arrears`, `registration.audit_courses`, `registration.overrides` |
| timetable | `timetable.core`, `timetable.rooms`, `timetable.substitutions`, `timetable.auto_generate`, `timetable.ical` |
| attendance | `attendance.core`, `attendance.qr`, `attendance.biometric`, `attendance.geo_app`, `attendance.rfid`, `attendance.on_duty`, `attendance.condonation`, `attendance.eligibility_detention`, `attendance.guardian_alerts`, `attendance.staff`, `attendance.offline_mobile` |
| fees | `fees.core`, `fees.structures_by_quota`, `fees.instalments`, `fees.auto_late_fee`, `fees.online_payment`, `fees.upi_qr`, `fees.offline_challan_reconciliation`, `fees.discounts`, `fees.staff_ward_concession`, `fees.fines`, `fees.scholarships`, `fees.nsp_integration`, `fees.no_dues`, `fees.refunds`, `fees.receipt_cancellation_approval`, `fees.gst_invoicing`, `fees.thermal_receipts`, `fees.accounting_export` |
| assessment & LMS | `assessment.internal_marks`, `assessment.question_wise_co`, `assessment.marks_workflow`, `assessment.marks_change_requests`, `assessment.projects`, `lms.content`, `lms.assignments`, `lms.similarity_check`, `lms.quizzes`, `lms.question_bank`, `lms.blueprints_paper_builder`, `lms.study_materials`, `lms.discussions`, `lms.lesson_plans`, `lms.course_files`, `lms.online_class_links`, `lms.lti_moodle` |
| exams | `exams.sessions`, `exams.registration_fee`, `exams.eligibility_snapshot`, `exams.hall_tickets`, `exams.face_verification`, `exams.seating`, `exams.invigilation`, `exams.qp_management`, `exams.qp_watermark_print_log`, `exams.clash_detection`, `exams.online_proctored`, `exams.practical_viva`, `exams.coding_dummy`, `exams.double_valuation`, `exams.onscreen_valuation`, `exams.moderation`, `exams.grace`, `exams.relative_grading`, `exams.external_examiners`, `exams.remuneration`, `exams.script_custody` |
| results | `results.processing`, `results.publication_portal`, `results.grade_cards`, `results.transcripts`, `results.revaluation`, `results.photocopy`, `results.challenge_valuation`, `results.supplementary`, `results.malpractice`, `results.rank_lists`, `results.legacy_import`, `results.sms_masked_notify` |
| obe | `obe.definitions`, `obe.attainment`, `obe.indirect_surveys`, `obe.cqi`, `obe.nba_export` |
| degrees | `degrees.eligibility`, `degrees.convocation`, `degrees.certificates`, `degrees.provisional`, `degrees.esign`, `degrees.digilocker_nad`, `degrees.abc_push`, `degrees.verification_portal` |
| hr | `hr.staff`, `hr.faculty_profiles`, `hr.guest_faculty`, `hr.leaves`, `hr.leave_encashment`, `hr.payroll`, `hr.statutory_payroll`, `hr.loans_advances`, `hr.staff_attendance`, `hr.service_book`, `hr.recruitment`, `hr.reservation_roster`, `hr.appraisal_pbas`, `hr.cas_promotions`, `hr.workload` |
| research & phd | `research.publications`, `research.patents`, `research.projects_grants`, `research.consultancy`, `research.ethics_committee`, `research.seed_grants_incentives`, `research.fdp`, `research.mous_collaborations`, `research.incubation`, `research.api_score`, `phd.core`, `phd.coursework`, `phd.dc_meetings`, `phd.progress_reports`, `phd.fellowships`, `phd.extensions_guide_change`, `phd.thesis_plagiarism`, `phd.external_examiners`, `phd.viva`, `phd.etd_upload`, `phd.scholar_portal` |
| campus | `library.core`, `library.opac`, `library.eresources`, `library.rfid_barcode`, `library.fines`, `library.inter_library_loan`, `library.koha_sync`, `hostel.core`, `hostel.mess`, `hostel.mess_billing`, `hostel.leave_outpass`, `hostel.gate_qr`, `hostel.night_roll_call`, `hostel.room_change`, `hostel.visitors`, `hostel.complaints`, `hostel.discipline`, `hostel.staff_quarters`, `transport.core`, `transport.gps_live`, `transport.staff`, `transport.fees`, `inventory.core`, `inventory.procurement`, `inventory.vendor_portal`, `inventory.lab_consumables`, `inventory.assets`, `inventory.asset_qr`, `inventory.bills`, `inventory.vendor_store`, `accounting.core`, `accounting.budgets`, `accounting.grants_ledger`, `accounting.gst_reports`, `accounting.tally_export` |
| events & facilities | `events.core`, `events.certificates`, `facilities.room_booking`, `facilities.equipment_booking`, `facilities.service_desk`, `facilities.lost_found`, `facilities.amc`, `facilities.visitor_gate`, `facilities.emergency_sos`, `facilities.health_centre`, `facilities.counselling_appointments`, `facilities.sports`, `facilities.canteen_wallet` |
| communication | `comms.sms`, `comms.whatsapp`, `comms.email`, `comms.push`, `comms.announcements`, `comms.announcement_ack`, `comms.emergency_broadcast`, `comms.bulk_campaigns`, `comms.scheduled_sends`, `comms.whatsapp_bot`, `comms.ai_assistant`, `comms.preferences`, `calendar.core`, `calendar.ical`, `calendar.personal_feed`, `workflow.engine`, `workflow.delegation` |
| documents | `documents.templates`, `documents.bilingual_templates`, `documents.certificate_requests`, `documents.bulk_generation`, `documents.serial_registers`, `documents.watermark_signed_links` |
| engagement | `mentoring.core`, `mentoring.appointment_slots`, `mentoring.early_warning`, `mentoring.counselling`, `grievances.core`, `grievances.anonymous`, `grievances.committees`, `discipline.core`, `surveys.core`, `surveys.sss`, `clubs.core`, `clubs.activity_hours_credits`, `clubs.achievements`, `placement.core`, `placement.recruiter_portal`, `placement.internships`, `placement.training`, `placement.resume_builder`, `alumni.core`, `alumni.portal`, `alumni.jobs_board`, `alumni.fundraising`, `alumni.donations_80g` |
| quality & governance | `accreditation.naac`, `accreditation.nba`, `accreditation.nirf`, `accreditation.aishe`, `accreditation.aicte_ugc`, `accreditation.evidence_repo`, `accreditation.iqac_cycles`, `accreditation.audit_registers`, `governance.committees`, `governance.minutes`, `governance.legal`, `governance.rti`, `governance.audit_paras`, `governance.efile`, `governance.policies`, `affiliation.core`, `affiliation.inspections`, `affiliation.data_submissions`, `affiliation.exam_centres`, `affiliation.fees` |
| platform | `analytics.core`, `analytics.early_warning`, `reports.core`, `reports.scheduled`, `reports.statutory`, `portals.student`, `portals.parent`, `portals.faculty`, `portals.alumni`, `portals.warden`, `portals.evaluator`, `portals.scholar`, `portals.recruiter`, `portals.pwa_push`, `platform.help_center`, `platform.in_app_feedback`, `platform.guided_tours`, `platform.read_only_mode`, `website.core`, `website.custom_domain`, `website.course_catalog`, `website.enquiry`, `mobile.app`, `mobile.offline`, `mobile.biometric_lock`, `mobile.tablet_layout`, `integrations.api_keys_webhooks`, `integrations.payments`, `integrations.sso`, `integrations.lti`, `integrations.video_conf`, `integrations.digilocker_nad`, `integrations.nsp`, `integrations.swayam_nptel`, `integrations.scopus_crossref_orcid`, `integrations.plagiarism`, `integrations.koha_dspace_shodhganga`, `integrations.biometric_rfid`, `integrations.face_verification`, `integrations.esign`, `integrations.aadhaar_ekyc`, `integrations.email_domain_auth`, `integrations.workspace_provisioning`, `data.migration_toolkit`, `data.export_portability`, `search.global` |

---

## 8. Authorization & data-visibility model (self · ownership · scoped · view_all)

### 8.1 Four layers, evaluated in order on every request

| Layer | Mechanism | Failure |
|---|---|---|
| 1. Feature | `feature_required(key)` | 403 `FEATURE_DISABLED` |
| 2. Permission | `permission_required(module, action)`; action semantics: `view` = self + ownership scopes; `view_all` = the role's scope; `manage/approve/…` = within scope | 403 `PERMISSION_DENIED` |
| 3. Scope | `user_roles.scope_type/scope_id` (institution/college/faculty/department/program/offering/self) narrows every `view_all/manage` to that unit; multiple roles = union | rows outside scope invisible |
| 4. Visibility (row-level) | `VisibilityResolver.predicate(user, module)` = **self ∪ ownership ∪ (scope if view_all)** applied by `BaseRepository.visible_to()`; Postgres RLS as tenant backstop | rows filtered, never 403 |

Plus **field-level masking** (`students:view_pii`, `hr:view_pii`, `fees:view_bank` — Aadhaar/bank/salary masked by default), **record-state rules** (published/locked rows read-only regardless of permission), and **impersonation** (banner + audit).

**Ownership links** derived (not duplicated) from: `course_offering_faculty` (own offerings), `mentor_assignments`, `batch_sections.class_advisor_staff_id` (advisees), `student_guardians.user_id` (wards), `hostels.warden_staff_id` (residents), `departments.hod_staff_id`, `faculties.dean_staff_id`, `research_scholars.guide_staff_id`, `valuation_assignments` (bundles), `committee_members`, `placement_drives.owner`, `service_requests.assigned_to`.

### 8.2 API & UI conventions

- One list endpoint per module (`GET /leaves`) filtered by the resolver; `?scope=self|own|department|college|all` selects a tab (validated against what the user may see); `GET …/me` shortcuts for self.
- Every list response carries `meta.visibility = {self: true, scopes: ["department","all"]}` → React `useVisibility(module)` renders tabs **Mine | Department | College | All**; mobile renders segmented control.
- Portals = self/ownership only; admin shell = all tabs the role has.
- Self-service always available where it makes sense: My profile, My leaves (apply/track), My attendance, My payslips, My timetable, My courses/marks (faculty), My dues/receipts, My hostel, My library, My requests, My approvals inbox.

### 8.3 Role × module visibility matrix (S = self · O = ownership scope · D = department · F = faculty unit · H = own hostels · W = wards · C = college · A = institution-wide (`view_all`) · — = none; verb in brackets = beyond view)

| Role | Students | Staff/HR | Leaves | Staff attendance | Student attendance | Marks/Results | Fees | Hostel | Placement | Library | Payroll | Approvals inbox |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| institution_admin | A (manage) | A (manage) | S + A (approve) | S + A | A | A | A | A | A | A | A | A |
| registrar | A (manage) | A | S | S | A | A | A | A | A | — | S | students/admissions/affiliation |
| controller_of_examinations | A | A | S | S | A | A (approve, publish) | A (exam fees) | — | — | — | S | results/reval/malpractice |
| exam_cell / exam_decoder | A | — | S | S | A | A (ops) / decode only | — | — | — | — | S | — |
| dean | F | F | S + F (approve) | S + F | F | F | F | — | F | — | S | F workflows |
| hod | D (manage) | D | S + D (approve) | S + D | D | D (verify) | D | — | D | — | S | D workflows |
| faculty | O (own offerings + mentees) | S | S | S | O (mark) | O (enter) | — | — | — | S | S | own |
| class_advisor / mentor | O (advisees/mentees) | S | S | S | O | O | O (dues) | O | O | S | S | registrations |
| **accountant** | **A** | **A** | **S + A** | **S + A** | — | — | **A (collect, refund)** | A (fees) | — | A (fines) | **A (manage)** | fee refunds |
| hr_officer | — | A (manage) | S + A (manage) | S + A (manage) | — | — | — | — | — | — | A (generate) | leaves/recruitment |
| admissions_officer | A (admit) | S | S | S | — | — | A (admission fees) | — | — | — | S | applications |
| placement_officer | A (profiles, CGPA/backlogs) | S | S | S | A (%) | A (CGPA) | — | — | A (manage) | — | S | drives |
| hostel_warden / gate | H | S | S | S | H | — | H (dues) | H (manage) / gate only | — | — | S | out-passes |
| librarian | A (members) | A (members) | S | S | — | — | A (fines) | — | — | A (manage) | S | — |
| iqac_coordinator | A (metrics) | A (metrics) | S | S | A (aggregates) | A (aggregates) | A (aggregates) | A | A | A | S | cycles |
| college_admin | C | C | S + C (approve) | S + C | C | C | C | C | C | C | C | C workflows |
| research_guide | O (scholars) | S | S | S | — | O | — | — | — | S | S | scholar reports |
| external_examiner / invigilator | — (dummy nos only) | — | — | — | — | O (bundles) | — | — | — | — | S (remuneration) | — |
| student | S | — | — | — | S | S | S | S | S | S | — | own requests |
| parent | W | — | — | — | W | W | W (pay) | W | W | W | — | — |
| alumni | S | — | — | — | — | S (transcripts) | S (certificate fees) | — | S (jobs) | — | — | — |
| recruiter (company user) | O (applicants to own drives, consented profile fields only) | — | — | — | — | O (CGPA/backlog flags only) | — | — | O (own drives) | — | — | — |
| auditor (time-boxed, read-only) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | — |
| support_agent (platform, read-only) | A across institutions (read, masked PII, audited) | | | | | | | | | | | |
| super_admin | A across institutions (impersonation-audited) | | | | | | | | | | | |

Default role→permission map in `docs/Roles_and_Permissions.md` encodes this matrix (`view` vs `view_all` per module per role, plus ownership rules); tests in Phase 43 assert it (e.g., *accountant lists all leaves and sees own leave in "Mine"; faculty cannot list students outside own offerings*).

---

## 9. User flows by role (journeys the prompts must implement end-to-end)

| Role | Key flows |
|---|---|
| Applicant | Enquire → apply (multi-programme, docs, fee) → track status → verification/resubmit → merit/allotment → accept & pay → admitted → first login |
| Student | Onboarding (undertakings, profile, guardian consent) → term registration (cart, electives, arrears, fee) → timetable & LMS → attendance % / shortfall → OD/condonation request → internal marks view → exam registration & fee → hall ticket (offline) → results/grade card → reval/photocopy → supplementary → hostel apply/out-pass/mess/complaints → library → scholarships → certificate/transcript requests → placement profile/drives/offers → mentor sessions → surveys → grievances → no-dues → convocation/degree/DigiLocker → alumni |
| Parent | Link wards → attendance/results/dues → pay fees (UPI) → hostel out-pass consent (OTP) → notices → mentor meeting → grievances |
| Faculty | My timetable → take attendance (QR/offline) → lesson plan/course file → LMS content/assignments/quizzes → internal marks (question-wise) → submit → CO attainment view → invigilation duties → evaluator bundles → mentees & early-warning → leave apply → payslip → research profile/publications → workload → surveys results |
| Class advisor / mentor | Approve registrations → advisee dashboard (attendance, marks, dues, holds) → mentoring logs → counselling referral → parent communication |
| HOD | Course allocation & workload → offerings → marks verification → condonation recommend → dept attendance/marks status → leave approvals → dept reports → BoS agenda/minutes → accreditation metrics for dept |
| Dean | Faculty-level approvals → regulation approvals → cross-department reports |
| Registrar | Admission cycle → seat matrix → merit/counselling → admit → registration numbers → transfers/migration → holds → certificates/transcripts → degree eligibility → convocation → affiliation applications & data submissions → statutory reports |
| COE / exam cell / decoder | Session setup → date-sheet (clash check) → registrations & fees → eligibility apply → hall tickets → seating → invigilation → QP → bundles/coding → valuation assignment (internal/external) → discrepancy/third → moderation → decode → result run → verify/approve/publish → reval → supplementary → malpractice → grade cards/transcripts → ABC push |
| External examiner | Time-boxed login → assigned bundles (dummy numbers) → question-wise marks → submit → remuneration slip |
| Accountant | Counter collection (search → dues → collect → receipt/thermal) → online reconciliation → refunds → scholarships disbursement → no-dues sign-off → fee reports → Tally export → payroll runs → **view all staff, leaves, attendance** alongside **My leaves / My attendance** |
| HR officer | Staff onboarding → documents → leave policies/approvals → attendance devices → payroll → recruitment → CAS |
| Admissions officer | Enquiries → cycle ops → verification queue → merit/counselling → offers → admit |
| Placement officer | Companies → drives & eligibility → applications → rounds → offers → stats (NIRF) → training programmes |
| Hostel warden / gate | Allotment → check-in → out-pass approvals → gate QR mark-out/return → visitors → complaints → discipline → mess → vacate/no-dues |
| Librarian | Catalogue → circulation (barcode) → reservations → fines → e-resources → no-dues sign-off |
| IQAC coordinator | Metric compute → evidence → cycles/criteria narratives → AQAR/SSR/NIRF/AISHE export → surveys (SSS) → audit registers |
| Research guide / scholar | Guide: scholars, DC meetings, progress, thesis evaluation panel · Scholar: coursework, progress reports, fellowship, synopsis/thesis upload with plagiarism, viva, ETD |
| Committee secretary | Meeting → agenda → attendance/quorum → minutes → resolutions → ATR |
| College admin (affiliated) | College-scoped everything → term data submissions to university → exam centre ops → result release view |
| Institution admin | Onboarding wizard → structure → roles/scopes → features (institution-enabled) → settings/branding → integrations → announcements → dashboards |
| Super admin | Create institution → plan → **features** → onboarding → impersonate → usage/billing → support tickets → integration health |

---

## 10. Mobile application UI structure (Flutter — Phase 42)

### 10.1 App architecture (Orbit's feature-first layout + additions)

```
lib/
  core/
    config/env.dart · constants.dart · providers.dart
    network/  dio_client.dart (Bearer, X-Institution-*, X-College-Id, envelope unwrap, single-flight refresh, Idempotency-Key, retry/backoff)
    auth/     auth_controller (bootstrap → /auth/me → role, permissions, features, visibility), session, biometric_lock
    router/   app_router (go_router, redirects by auth/role/feature/permission), routes.dart, role_shells.dart, screen_registry.dart, deeplinks.dart (push payload → route; universal links /verify, /apply)
    offline/  drift (sqlite) read-model cache (timetable, attendance summaries, hall ticket PDF, results, dues, notices) + write queue (attendance marks, GPS pings, gate scans, out-pass decisions) with conflict rules; sync service; OfflineBanner
    theme/    tokens shared with web (JSON: brand ramps, semantic colors, 5 themes, table styles) → Material 3 ColorScheme; institution branding
    l10n/     11 locales (ARB), nav labels, completeness tests
    notifications/ FCM + local notifications, topics per role/college, inbox provider
    remote_config/ /mobile/config (min version/force update, feature hints, maintenance banner)
    analytics/ Sentry/Crashlytics + screen events
    print/    thermal receipts (esc_pos), share/PDF viewer
    scan/     QR/barcode scanner (attendance, gate, library, hall ticket verify)
    payments/ Razorpay SDK + UPI intent
  shared/   models (generated from OpenAPI where stable; hand-written otherwise), utils (Fmt, media_url), widgets (catalogue §10.4)
  features/<feature>/{data,domain,application,presentation}
```
Gating: `AuthState.can(module, action)`, `hasFeature(key)`, `visibility(module)`; `moreMenuModules` entries carry `{permission, feature, roles}`; unknown route → `PlaceholderScreen`.

### 10.2 Global navigation model

- **Splash → Login** (identifier/password · OTP · SSO) → **institution/college picker** (multi-scope users) → **role shell**.
- **Role shell** = bottom `NavigationBar` (≤ 5 tabs) + **More** grid (feature/permission-gated modules with colour/icon) + tab-specific FAB (primary action) + app bar (college/term chip, search, notifications, profile).
- **Multi-role users** (e.g., HOD + faculty): shell of the highest role; "Switch view" in profile; approvals inbox aggregated.
- **Visibility inside screens**: segmented control **Mine | Dept | College | All** driven by `meta.visibility`.
- **Approvals inbox** (workflow engine) is a first-class tab for approver roles.
- Deep links from push: `route` + `params`; cold-start routing after auth.

### 10.3 Role shells (tabs → screens)

| Role | Tabs (bottom) | More grid / secondary screens |
|---|---|---|
| Student | **Home** (today's classes, attendance ring, dues chip, notices, quick actions) · **Academics** (timetable, attendance per course + shortfall calc, registration cart/electives/arrears, LMS courses → content/assignments/quizzes/discussions) · **Exams** (register + fee, hall ticket offline PDF, seating, results, grade cards, reval/photocopy, transcripts, arrears) · **Fees** (dues, pay UPI/Razorpay, receipts, scholarships, no-dues status) · **More** | Hostel (apply, out-pass with guardian OTP, mess, complaints, visitors), Library (my books, OPAC, fines), Placement (profile, drives, applications, offers, internships, training), Mentor (sessions), Surveys, Grievances, Clubs/events, Certificates & requests, ID card (QR), Holds & standing, Credit transfers, Projects, Convocation, Profile & undertakings, Settings (language, theme, biometric lock, notifications) |
| Parent | **Home** (ward switcher, attendance, dues, notices) · **Academics** (attendance, results, timetable) · **Fees** (pay, receipts) · **More** | Hostel consent/out-pass status, transport live, mentor meetings, surveys, grievances, notices, profile |
| Faculty | **Home** (today's sessions, pending tasks, mentee alerts, duties) · **Attendance** (session list → tap-mark grid, QR mode, offline queue, extra class) · **Marks** (offering assessments → question-wise entry → submit; CO preview) · **Courses** (LMS: modules/content upload, assignments grading, quizzes, announcements; lesson plan tick-off; course file) · **More** | My timetable, Mentees (360°, logs, referrals), Advisees registrations approval, Leaves (apply/balance) & My attendance, Payslips, Workload, Research profile (publications/projects), Invigilation duties, Evaluator bundles (dummy numbers, question-wise entry), Surveys results, Approvals inbox, Profile |
| HOD / Dean | **Home** (dept KPIs: attendance, marks status, pending) · **Approvals** (leaves, condonation, marks verify, registrations, indents, change requests) · **Department** (staff, students, offerings, allocation, workload) · **Reports** · **More** | Attendance/marks monitoring, timetable, BoS meetings/minutes, accreditation metrics, budgets, events, all faculty screens (self) |
| Registrar / Institution admin | **Home** (institution KPIs) · **Approvals** · **Students** (global search → 360° profile: enrolment, attendance, results, dues, holds, hostel, documents) · **Reports** · **More** | Admissions cycle status, affiliation, certificates queue, holds, announcements, settings, integrations health |
| COE / Exam cell | **Home** (session status board) · **Sessions** (papers/date-sheet, registrations, eligibility, hall tickets, seating, invigilation) · **Valuation** (bundles, assignments, discrepancies, moderation, decode) · **Results** (runs, anomalies, approve/publish, reval, malpractice) · **More** | QP management, remuneration, exam audit, reports |
| Accountant | **Home** (today's collection, dues, reconciliation) · **Collect** (search → dues → collect → receipt/thermal print) · **Fees** (invoices, receipts, refunds, scholarships, no-dues) · **HR** (**All staff · All leaves · All staff attendance** with **Mine** segment for own leaves/attendance) · **More** | Payroll runs & payslips, accounting/budgets, Tally export, reports, my profile |
| HR officer | **Home** · **Staff** · **Leaves** (all + approvals + mine) · **Attendance** (devices, all + mine) · **More** | Payroll, recruitment, CAS, service book |
| Admissions officer | **Home** · **Applicants** (verification queue, docs) · **Merit/Counselling** · **Enquiries** · **More** | Seat status, offers, imports |
| Placement officer | **Home** · **Drives** (funnel by round) · **Students** (eligibility) · **Companies** · **More** | Offers, internships, training, stats |
| Hostel warden / gate staff | **Home** (occupancy, pending out-passes) · **Out-passes** (approve; **Gate scan** QR mark-out/return, late list) · **Residents** (rooms/beds, allocations, complaints, discipline) · **Mess** · **More** | Visitors, staff quarters, fees, reports |
| Librarian | **Home** · **Circulation** (scan issue/return/renew) · **Catalogue** · **Members** · **More** | Reservations, fines, e-resources, reports |
| IQAC coordinator | **Home** (criteria completion) · **Metrics** · **Evidence** · **Cycles** · **More** | Surveys, audits, exports |
| Research scholar | **Home** · **Progress** (reports, DC meetings) · **Thesis** (uploads, plagiarism, examiners, viva) · **Fellowship** · **More** | Coursework, publications, profile |
| Alumni | **Home** · **Directory** · **Events** · **Give** · **Profile** | Transcripts/certificates requests, jobs board, mentorship |
| Driver | **Home** · **Route** (trip start/stop, stops, GPS queue) · **Settings** | Vehicle checks |
| External examiner | **Bundles** · **Entry** · **Profile** | Remuneration |
| Super admin | Institutions · Features · Health · Impersonate (web-first; mobile read-only) | |

### 10.4 Shared widget catalogue

`StatCard`, `ModuleCard`, `ActionTile`, `ApprovalCard`, `FilterChipBar`, `SegmentedScope` (Mine/Dept/All), `SearchField`, `DetailRow`, `Timeline`, `AttendanceRing`, `ShortfallCalculator`, `GradeBadge`, `DueChip`, `HoldBanner`, `QRScannerSheet`, `QRCodeCard` (ID/hall ticket), `OfflineBanner`/`SyncStatus`, `PdfViewerScreen`, `ReceiptPrintSheet`, `MarksEntryGrid` (keyboard/numpad, question-wise), `AttendanceGrid` (tap-cycle statuses), `TimetableWeek`, `CalendarStrip`, `EmptyStateIllustration`, `Skeletons`, `ConfirmDialog`, `BottomSheetPicker`, `WardSwitcher`, `CollegeTermChip`, `NotificationTile`, `JobProgressTile`.

### 10.5 Cross-cutting mobile behaviours

UX principles: ≤ 3 taps to any daily action (attendance, pay, out-pass), large touch targets for grids, one-hand reach for primary FABs, **tablet master-detail layouts** for HOD/COE/accountant and landscape marks/attendance grids, dark mode, consistent empty/error/offline states. Offline-first reads with stale badges; write queue with per-item status & conflict resolution (server wins for finalized sessions; client prompts otherwise); push deep links; biometric app lock & session timeout; force-update & maintenance modes; institution branding & 5 themes; accessibility (font scaling, semantics); analytics/crash reporting; secure storage; certificate pinning (optional); image/document capture with compression; share/download to files; UPI intent & gateway SDK; QR scanning across attendance/gate/library/verify; language switch; Play/App Store release via Fastlane/Codemagic; golden + widget + integration tests; l10n completeness and no-hardcoded-strings tests (as Orbit).

---

## 11. Coverage cross-check (verification that nothing is missed)

| Source inventory | Item → Universe phase |
|---|---|
| **SAMARTH Base** | Organizational Unit → 03 · User Management → 02 |
| **SAMARTH Academics & student lifecycle** | Programme & Courses → 05 · Student → 07 · Admissions → 08 · Evaluation & Grading → 13–16 · Hostel → 20 · Convocation → 18 · Alumni Portal → 29/39 · Student Feedback → 27 · Training & Placement → 28 |
| **SAMARTH HR** | Employee Mgmt/Recruitment/Leave/Payroll/CAS → 06 · Knowledge Mgmt → 13/19 · Training of Trainers → 30 |
| **SAMARTH Finance & supply chain** | Budget & Accounts → 23 · Bill Tracking → 22 · Inventory → 22 · Research Project Mgmt → 30 |
| **SAMARTH Governance** | Core Communication → 04/24 · Estate → 25 · Legal → 33 · File Tracking → 33 · RTI → 33 · Health → 25 · Service Desk → 25 · Sports → 25 · Minutes & Resolutions → 33 · Fleet → 21 · Content Federation → 40 · Essential Services → 25 · Grievance → 27 · Security → 25 · Endowment → 29 · Residential Accommodation → 20 · Affiliation → 34 |
| **Commercial college ERP lists** | CRM → 08 · Online admission → 08 · Fee → 12 · Attendance devices → 11 · Exams incl. reval/supplementary → 13–16 · Timetable → 10 · OBE → 13/17 · Hostel → 20 · Library → 19 · Transport → 21 · Payroll/HR/appraisal → 06 · Research/startups → 30 · Scholarships/career/placement/alumni/grievance/mentoring → 12/27/28/29 · NAAC/IQAC/NBA/NIRF → 32 · Governance/audit/RBAC → 33/37/02 · Portals/mobile/digital ID → 39/42/26 · Reporting/analytics → 35/36 · Integrations → 41 · Security (2FA, IP restriction, backups) → 02/43/44 |
| **International registrar SIS** | Catalogue → 05/40 · Prerequisites → 05/09 · Cart/add-drop/waitlist → 09 · Holds → 07 · Standing/probation → 07 · Degree audit → 18 · Transcripts → 16/18 · Incompletes/withdrawals → 15 · Appeals → 16 · Transfer credit → 07 · Graduation/commencement → 18 · Enrolment verification → 26 · FERPA-style consent → 07 · Financial aid → 12 · Housing → 20 · Health/immunization → 25 · Athletics → 25 · Career services → 28 · Advising → 27 · Exchange → 30 · International students → 07 |
| **NEP 2020 / regulators** | CBCS → 05 · Multiple entry/exit → 05/07/18 · ABC/APAAR → 07/18 · MOOC transfer → 07/41 · DigiLocker/NAD → 18/41 · NSP → 12/41 · AISHE/NIRF/AICTE/UGC → 32/36 · UGC PhD Regs → 31 · Anti-ragging/ICC → 07/27/33 |
| **Orbit as-built (149 tables)** | auth/OTP/device tokens/QR/biometric/GPS → 02/11/21 · RBAC → 02 · profile/settings/themes → 03 · years/terms → 03 · admissions/leads/demo/registration/install → 08/38/40 · classes/subjects/timetable → 05/09/10 · students/parents/docs/promotions/transfers/ID/import/credentials → 07/02/26 · staff/leave/payroll/attendance/holidays → 06/03 · attendance sessions/periods/QR → 11 · fees v1+v2/receipts/online → 12 · exams/admit cards/marks/grading/templates/QPs → 14/15/26 · content (question bank/blueprints/paper builder/materials) → 13/14 · library → 19 · transport/trips/GPS/live/driver → 21 · inventory/POs/vendor → 22 · accounting → 23 · communication (templates/bulk/logs/announcements/preferences/WhatsApp/chat flows/AI/simulator) → 04/24 · homework/lesson plans/PTM → 13/27 · calendar → 25 · templates/bulk jobs → 26/01 · audit → 37 · dashboards/charts/reports → 35/36 · super admin → 38 · website + marketing → 40 · portals/PWA/push → 39 · Flutter → 42 · tests/security/deploy → 43/44 |
| **Visibility requirement** | Self vs view_all per module/role → §8 matrix → Phase 02 resolver + per-module prompts' "Mine/All" pages + Phase 43 tests |

---

## 12. Roles & permission modules

**Platform:** `super_admin`.
**Institution roles (seeded per tenant):** `institution_admin`, `vice_chancellor`/`principal`, `registrar`, `controller_of_examinations`, `exam_cell`, `exam_decoder`, `dean`, `hod`, `class_advisor`, `faculty`, `external_examiner`, `invigilator`, `research_guide`, `research_scholar`, `iqac_coordinator`, `obe_coordinator`, `admissions_officer`, `placement_officer`, `alumni_coordinator`, `hostel_warden`, `hostel_gate_staff`, `librarian`, `accountant` (accounts_officer), `hr_officer`, `research_cell`, `grievance_officer`, `discipline_committee`, `committee_secretary`, `legal_officer`, `pio`, `estate_officer`, `medical_officer`, `sports_officer`, `security_officer`, `transport_manager`, `inventory_manager`, `receptionist`, `driver`, `college_admin`, `college_exam_coordinator`, `integration_admin`, `guest_faculty`, `auditor` (time-boxed read-only for peer teams/financial audit), `recruiter` (company portal), `learner` (non-degree/CE participant), `student`, `parent`, `alumni`, `applicant`. Platform: `super_admin`, `support_agent` (read-only, masked PII). `mentor` derived.

**Permission modules** (actions `view, view_all, create, update, delete, approve, publish, export, manage, view_pii` + bespoke): `dashboard, institutions, colleges, users, roles, features, sessions, programs, regulations, curriculum, courses, batches, offerings, registration(+self, approve, allocate, override), timetable(+generate, publish), attendance(+mark, self, condone, edit_finalized), marks(+enter, verify, lock, correct), projects, exams(+configure, self, eligibility, hall_tickets, seating, invigilation, conduct, qp, code, valuation_assign, evaluate, moderate, decode, reval, malpractice), results(+compute, verify, approve, publish, self, transcript), degrees(+award, issue), obe(+configure, compute, export), lms, admissions(+verify, merit, allot, import), students(+holds, standing), credit_transfers, faculty(+research), hr, recruitment, leaves(+self, approve), payroll(+self), research, phd(+guide, dc, examine), fees(+self, collect, refund), scholarships, no_dues, hostel(+self, allot, gate, warden), library(+self), transport, inventory, procurement, accounting, events, facilities, health, sports, placement(+self), alumni, fundraising, mentoring, grievances, discipline, surveys, clubs, accreditation(+override, submit), governance(+minutes, resolutions), legal, rti, efile, affiliation(+inspect, decide, submit), communication, calendar, templates, certificates(+self), reports, analytics, audit_logs, settings, integrations, jobs, website`.

---

## 13. Technical & architectural gaps filled (consolidated)

| Area | Addition |
|---|---|
| Authorization | Feature → permission → scope → visibility resolver → field masking → record-state rules; RLS backstop; impersonation audit (§8) |
| Feature control | Registry + flags + plan defaults + gating on 3 clients + CI test (§7) |
| Reliability | Transactional outbox for domain events (notifications, webhooks, ABC push, search, metrics); idempotency keys; optimistic locking; `FOR UPDATE` + `number_sequences`; retries/circuit breakers on adapters |
| Workflow & jobs | Approval-workflow engine; `background_jobs` with progress/cancel; Beat catalogue (fee reminders, attendance warnings, eligibility compute, result notifications, ABC retries, metric refresh, SLA escalations, hostel late-return, leave accrual, library overdue, backups, archival) |
| API | Versioned `/api/v1`, error-code catalogue, OpenAPI → generated TS types (+ optional Dart), API keys/webhooks, per-tenant rate limits, request-size/time limits |
| Multi-tenancy | Institution TZ/locale/currency; per-tenant file prefixes/quotas; tenant export/erasure/reset; custom domains; branding on emails/PDFs |
| Security & privacy | MFA, sessions, refresh rotation, JWT key rotation, IP allowlists, encrypted PII, masking, DPDP consent/DSR, retention, hash-chained audit, secrets via env/vault, DLT/WhatsApp template registries |
| Data | Partitioning, materialized read models, archival of closed years, year rollover/term close scripts, migration toolkit (legacy results), backups per tenant, DR targets, expand/contract migrations |
| Realtime & search | Redis pub/sub WebSocket channels; `tsvector` global search (permission-aware) |
| Frontend | Feature folders, generated types, RHF+Zod everywhere, server-side DataTable, virtualized keyboard-first grids, Mine/All tabs, jobs tray, command palette, print CSS, WCAG AA |
| Mobile | §10: offline cache + write queue, deep links, biometric lock, remote config/force update, shared theme tokens, QR/payments/printing, per-role shells |
| Dev process | Scaffolder CLI, ADRs, lint/format/type-check, import-linter, pre-commit, conventional commits, supply-chain scans, per-round Playwright, seed demo institution, access-matrix generator, QA plan/CSV findings, launch tracker |

### 13.1 Non-functional targets (design envelope)

| Dimension | Target |
|---|---|
| Scale | 100 institutions; up to 50 000 active students and 5 000 staff per institution; 200 colleges per university tenant; 10 years of history |
| API latency | list endpoints p95 < 300 ms (≤ 200 rows); detail p95 < 150 ms; search p95 < 500 ms |
| Peaks | registration window: 5 000 concurrent students, seat checks under row locks, no double-allocation; result publish: 20 000 result rows/min notified via outbox; hall-ticket bulk PDF 10 000 in < 15 min on `documents` queue |
| Result run | 10 000 students × 8 courses computed in < 10 min, reproducible from `config_snapshot` |
| Availability | 99.5 % monthly (single-region India, `orbit-infra` VPS class); read-only mode during migrations; RPO 15 min / RTO 4 h |
| Frontend | LCP < 2.5 s on 4G, initial bundle < 350 KB gz per route chunk, WCAG AA, last 2 versions of Chrome/Edge/Firefox/Safari |
| Mobile | cold start < 2 s, offline attendance for a full day, crash-free sessions > 99.5 % |
| Security | MFA for privileged roles, OWASP ASVS L2 controls, VAPT pass before launch, secrets never in repo |

---

## 14. Deliverables to produce after approval (the planning-doc set)

All under `C:/Users/user/source/septronR repo/SeptronUniverse/`, in reviewed batches:

| # | File | Content |
|---|---|---|
| 1 | `README.md` | Product, institution types, stack, repo map, prompt usage |
| 2 | `docs/Academic_Core_Design.md` | §6 at full column level, state machines, formulas, endpoints, pages |
| 3 | `docs/Feature_Flags.md` | §7 registry table + mechanism + super-admin UI spec |
| 4 | `docs/Authorization_and_Visibility.md` | §8 layers, resolver algorithm, ownership links, matrix, API/UI conventions, test cases |
| 5 | `docs/User_Flows.md` | §9 expanded per role with screens/endpoints per step |
| 6 | `docs/Mobile_App_UI_Structure.md` | §10 expanded: per-role tab/screen trees, widget catalogue, offline rules, deep-link map |
| 7 | `docs/Coverage_Matrix.md` | §11 expanded: source item → phase → feature key → tables |
| 8 | `docs/Glossary_and_Orbit_Mapping.md` | Glossary; rename table for every Orbit table/module; not-carried list |
| 9 | `docs/Feature_Inventory.md` | §5 expanded; module × institution type × R/R+/N |
| 10 | `docs/Roles_and_Permissions.md` | Roles, permission registry, default role→permission (view vs view_all), scope rules |
| 11 | `docs/Regulatory_Pack_IN.md` | NEP/ABC/APAAR/DigiLocker/NAD/NSP, UGC PhD, NAAC/NBA/NIRF/AISHE metrics, DLT/DPDP/GST; GENERIC stub |
| 12 | `docs/Integrations_Catalogue.md` | Adapter interfaces, providers, prerequisites, mocks |
| 13 | `docs/Technical_Architecture.md` | §4.2/§13 in depth: outbox, RLS, idempotency, jobs, workflow, files, WS, search, observability, data lifecycle, DR, error catalogue, ADR index |
| 14 | `Architecture.md` | Mermaid: tenancy, four-layer authz, feature-flag flow, outbox, workflow, registration flow, exam lifecycle, result versioning, module dependency map, academic ERD, compose topology, mobile shell |
| 15 | `Database_Schema.sql` | Canonical DDL (~270 tables incl. platform tables), RLS policies, triggers, indexes, seeds (permissions, roles, features, pack data, grading, NBA POs, NAAC criteria) |
| 16 | `Prompts/00_HOW_TO_USE.md` | Rounds, parallelisation, per-phase checklist, gates |
| 17 | `Prompts/00_PREREQUISITE_Project_Setup.md` | Orbit's 10-section structure with paste-ready boilerplate for all §4.2 building blocks, frontend conventions, compose, nginx, standards, checklist |
| 18 | `Prompts/01…44_PhaseNN_*.md` | Per phase: Pre-Requisite → Objective → **Feature keys** → **Visibility rules (self/own/all per role)** → DDL slice → Alembic → Models → Schemas → Repository → Service (rules) → Events/Celery/Beat → Endpoints (`METHOD path → desc [module:action] {feature}`) → Frontend (pages incl. Mine/All tabs, api, nav, portal widgets) → **Mobile screens** → Tests (incl. visibility) → Verification → Deliverables |
| 19 | `RUN_AFTER_PHASE.md`, `QA_Test_Plan.md` (skeleton), `Real_World_Launch_Plan.md` (skeleton), `docs/ADR/0001-…md` (initial ADRs) | Runbooks & governance |
| 20 | `.claude/launch.json`, `docker-compose.yml`, `nginx/nginx.conf`, `.gitignore`, `.github/workflows/*` | From Orbit with renames |

Batches: **A** 1–13 · **B** 14–15 · **C** 16–17 + prompts 01–06 · **D** 07–13 · **E** 14–18 · **F** 19–26 · **G** 27–34 · **H** 35–44 · **I** 19–20.

### 14.1 Definition of done per phase (encoded in `00_HOW_TO_USE.md` and every prompt's deliverables checklist)

(a) models + one Alembic migration (expand/contract safe) · (b) Pydantic schemas by domain · (c) repository on `BaseRepository` with visibility hook · (d) service with rules, `log_audit`, domain events · (e) routes with `permission_required` **and** `feature_required`, envelope, error codes · (f) workflow definitions / Beat jobs / outbox consumers where applicable · (g) tests: unit + API + tenant/scope/**visibility** (Mine vs All per role) + feature-disabled · (h) generated TS types + `api/*.ts` + hooks · (i) web pages with Mine/All tabs, filters, pagination, export, RHF+Zod forms · (j) `NAV_GROUPS` entries with `{module, action, feature}` · (k) mobile screens registered in `screen_registry` + role tabs/More grid · (l) feature keys, permissions, roles and visibility rules added to the registries/docs · (m) seed demo data for the module · (n) access matrix + OpenAPI regenerated, drift/authz/feature audits green, smoke script passes.

---

## 15. Build order & dependencies (after the doc set)

```
00 → 01 → 02 → 03 → 04 → 05 → 06
                          └→ 07 → 08 → 09 → 10 → 11 → 12 → 13
                                                        └→ 14 → 15 → 16 → 17 → 18
07/12 → 19, 20, 21, 22, 23 (parallel)   04 → 24, 25, 26 (parallel)
07/15 → 27, 28, 29, 30 → 31 → 32       04 → 33 ; 15 → 34
all → 35, 36, 37, 38, 39, 40 → 41 → 42 → 43 → 44
```
Rounds sequential; in-round parallel prompts only with disjoint models and one Alembic revision each, merged once per round.

---

## 16. Verification

**Doc set:** (1) `verify_prompts_vs_schema.py` — every table/column in prompts exists in `Database_Schema.sql`; (2) every permission, feature key and visibility rule in prompts exists in the registries; (3) every §5 item, §9 flow and §11 row resolves to phase + feature key + tables + mobile screen; (4) Mermaid renders.

**Per build phase:** (1) `alembic upgrade head` from empty, single head, drift = 0; (2) authz/feature audit tests; feature disabled → 403 + hidden nav/tab; (3) smoke per role: list endpoints return envelope with correct `meta.visibility`; forbidden role → 403; other institution/college → isolated (RLS test with a raw query); (4) **visibility tests**: accountant sees all leaves + own in Mine; faculty sees only own-offering students; parent only wards; warden only own hostels; (5) exam phases: immutability trigger, dummy projection, SGPA golden, clash detection; (6) frontend build/vitest/Playwright; Flutter analyze + golden + l10n tests; offline queue test.

---

## 17. Design risks & mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | Regulation drift | Regulation ownership + locking + clone; students pinned |
| 2 | Retroactive grade changes | Versioned results, immutability trigger, workflow + audit |
| 3 | Result tampering | Row hash, run checksum, signed QR verify, credential push log, hash-chained audit |
| 4 | Dummy-number leakage | Evaluator projection, separate decode role, audited |
| 5 | Multi-college isolation | `college_id` + scope layer + `BaseRepository` + RLS backstop |
| 6 | Eligibility disputes | Versioned snapshots; condonation as workflow |
| 7 | SGPA/CGPA variants | All knobs in `regulations.rules`; pure function over `config_snapshot` |
| 8 | Backlog drift | `student_arrears` maintained at publish |
| 9 | ABC/APAAR mismatches | 1:1 ledger, revoke + re-push |
| 10 | CIA/LMS/OBE double entry | Single write path into `internal_marks` |
| 11 | Race conditions | `FOR UPDATE`, sequences, uniques, idempotency keys |
| 12 | Affiliated-college data chaos | Submission lock state gates results |
| 13 | Feature-flag sprawl | Registry-driven CI test; dependency graph |
| 14 | Visibility bugs (over/under exposure) | Single resolver, `meta.visibility` contract, matrix-driven tests per role |
| 15 | Workflow over-generalisation | Linear/parallel steps only; module hooks; 12 shipped definitions |
| 16 | Lost notifications/webhooks | Transactional outbox + relay + retries |
| 17 | Provider integrations never live (Orbit lesson) | Adapters + mocks; launch tracker from day one |
| 18 | Mobile offline conflicts | Server-wins for finalized data; explicit conflict UI; idempotent writes |
| 19 | Scope creep (44 phases) | Flags allow pilots on subsets; rounds independently shippable |

---

## 18. Assumptions & open decisions (defaults chosen)

Statuses `VARCHAR(30)` + Python enums; WeasyPrint PDFs; web English + i18n scaffold; Flutter 11 locales; timetable auto-generation, onscreen valuation, face verification, canteen/wallet, Aadhaar eKYC, certificate pinning off by default; Razorpay first behind `PaymentGateway`; OIDC first, SAML later; generated Dart models only for stable read APIs; single-region (India) hosting on `orbit-infra` with nightly demo reset; ODL/distance programmes supported via `programs.mode` + `colleges(kind=study_centre)` + exam centres (no separate ODL module); phase granularity adjustable at prompt-generation time.

---

## 19. Sources

- SAMARTH eGov: https://samarth.edu.in/product-guide/ · https://docs.samarth.ac.in/docs/governance/affiliation_management_system/
- College/University ERP guide: https://www.myleadingcampus.com/blogview/what-is-college-university-erp-a-complete-practical-guide-for-autonomous-colleges-and-deemed-universities-2025-edition/
- Higher-ed ERP/SIS: https://www.fullfabric.com/articles/best-erp-systems-higher-education-2026 · https://www.fullfabric.com/articles/top-student-information-systems-2026 · https://unicloud360.com/blog/university-erp-systems-guide/ · https://openeducat.org/what-is-education-erp/
- NEP 2020 / ABC / APAAR: https://www.pib.gov.in/FactsheetDetails.aspx?id=150650 · https://en.wikipedia.org/wiki/Academic_Bank_of_Credits_(India) · https://www.myleadingcampus.com/apaar-id/
- OBE / NBA: https://www.creatrixcampus.com/outcome-based-education-software · https://www.edhitch.com/Outcome_Based_Education_OBE_Software.html · https://www.edhitch.com/what-is-co-po-mapping.html
- NAAC/NIRF: https://www.edumerge.com/products/college-erp/accreditation-management · https://campus24x7.in/blogs/naac-accreditation-erp-software-india · https://www.edhitch.com/NAAC_Accreditation.html · https://openeducat.org/compliance/naac/
- Exams & post-result: https://vmedulife.com/blog/examination-and-assessment-system/top-15-examination-management-system-features-every-college-and-university-needs/ · https://www.eklavvya.com/blog/answer-sheet-photocopy-revaluation-process/ · https://siddhartha.edu.in/wp-content/uploads/2025/09/university-malpractice-guidelines.pdf
- PhD / Shodhganga / plagiarism: https://www.inflibnet.ac.in/activities/ · https://cutn.ac.in/wp-content/uploads/2023/08/CUTN_PhD_Regulations_2022_05082023.pdf · https://samvikresearch.com/blog/ugc-revised-plagiarism-ai-guidelines-2026
- Campus modules: https://vmedulife.com/blog/erp-lms/erp-modules-a-complete-guide-to-essential-education-erp-modules-for-modern-institutions/ · https://www.skolaro.com/college-erp
- Registrar SIS: https://openeducat.org/articles/degree-audit-reporting-system-guide/ · https://corecampus.com/student-information-system-registrar-secret-weapon/
- Integrations: https://aristeksystems.com/blog/your-guide-to-lti-elearning-standard/ · https://nad.digilocker.gov.in/students · https://en.wikipedia.org/wiki/National_Scholarship_Portal
- Affiliation: https://www.iitms.co.in/university-erp/college-affiliation/
