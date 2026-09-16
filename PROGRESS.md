# SeptronUniverse — Progress Checklist

Single source of truth for **what is done and what comes next**. Update this file at the end of every session (tick items, add the commit hash). Work is done **one batch per session** to keep context small — see [docs/HANDOFF.md](docs/HANDOFF.md) for the session-start protocol and the prompt to paste.

Branch: Stage 1 on `planning-docs` (merged to `main`); Stage 2 uses one branch per phase off `main` (`phase-00`, `phase-01`, ...). Plan: [MASTER_PLAN.md](MASTER_PLAN.md).

## Stage 1 — Planning document set

| Batch | Scope | Status | Commit |
|---|---|---|---|
| A | `README.md`, `docs/` (13 docs), `docs/ADR/` (8) | ✅ done | `c4e6b64` |
| B | `Architecture.md`, `Database_Schema.sql` (406 tables + 5 partition defaults; validated on PostgreSQL 18 incl. RLS + immutability trigger) | ✅ done | `89239ac` |
| C | `Prompts/00_HOW_TO_USE.md`, `Prompts/00_PREREQUISITE_Project_Setup.md`, prompts **01–06**, `scripts/verify_prompts_vs_schema.py` | ✅ done | `60f1342` |
| D | Prompts **07–13** (Round 1 student lifecycle) | ✅ done | `352a720` |
| E | Prompts **14–18** (Round 2 examinations & outcomes); guard script now accepts views/triggers | ✅ done | `8ef555a` |
| F | Prompts **19–26** (Round 3 campus services); guard script now accepts named indexes | ✅ done | `e336760` |
| G | Prompts **27–34** (Round 4 engagement, research, quality) | ✅ done | `dec5e8f` |
| H | Prompts **35–44** (Round 5 platform & delivery); Phase 35 read models = materialized views only (no new tables) | ✅ done | `352cd3a` |
| I | `RUN_AFTER_PHASE.md`, `QA_Test_Plan.md` (skeleton), `Real_World_Launch_Plan.md` (skeleton), `.claude/launch.json`, `docker-compose.yml` (+ `docker/postgres/init/01_roles.sql`), `nginx/nginx.conf`, `.gitignore`, `.github/workflows/*` (8 workflows) | ✅ done | `c549c32` |
| J | Final review: `scripts/verify_prompts_vs_schema.py` over all 44 prompts (0 missing, 481 schema objects); `docs/Coverage_Matrix.md` cross-checked row by row (116 rows → 0 uncovered after 5 matrix fixes + Phase 02 `core.rbac` cite); `planning-docs` merged → `main` (`--no-ff`) | ✅ done | `1c5bfbe` |

### Prompt inventory (Stage 1)

| # | Prompt file | Status |
|---|---|---|
| 00 | `00_HOW_TO_USE.md` | ✅ |
| 00 | `00_PREREQUISITE_Project_Setup.md` | ✅ |
| 01 | `01_Phase01_Infrastructure_Platform_Services.md` | ✅ |
| 02 | `02_Phase02_Auth_RBAC_Features_Visibility.md` | ✅ |
| 03 | `03_Phase03_Institution_Structure_Sessions_Settings.md` | ✅ |
| 04 | `04_Phase04_Communication_Core_Workflow_Engine.md` | ✅ |
| 05 | `05_Phase05_Programmes_Regulations_Curriculum.md` | ✅ |
| 06 | `06_Phase06_Staff_Faculty_HR_Recruitment_CAS.md` | ✅ |
| 07 | `07_Phase07_Students_Enrolment_Holds_Standing.md` | ✅ |
| 08 | `08_Phase08_Admissions.md` | ✅ |
| 09 | `09_Phase09_Course_Offerings_Faculty_Allocation_Registration.md` | ✅ |
| 10 | `10_Phase10_Timetable_Rooms.md` | ✅ |
| 11 | `11_Phase11_Attendance_Eligibility.md` | ✅ |
| 12 | `12_Phase12_Fees_Scholarships_NoDues.md` | ✅ |
| 13 | `13_Phase13_Internal_Assessment_OBE_Definitions_LMS_Projects.md` | ✅ |
| 14 | `14_Phase14_Exam_Administration.md` | ✅ |
| 15 | `15_Phase15_Evaluation_Results.md` | ✅ |
| 16 | `16_Phase16_Post_Result_Services.md` | ✅ |
| 17 | `17_Phase17_OBE_Attainment_CQI.md` | ✅ |
| 18 | `18_Phase18_Degrees_Convocation_Digital_Credentials.md` | ✅ |
| 19 | `19_Phase19_Library.md` | ✅ |
| 20 | `20_Phase20_Hostel_Mess_Staff_Accommodation.md` | ✅ |
| 21 | `21_Phase21_Transport.md` | ✅ |
| 22 | `22_Phase22_Inventory_Procurement_Bills.md` | ✅ |
| 23 | `23_Phase23_Accounting_Budget.md` | ✅ |
| 24 | `24_Phase24_Communication_Advanced.md` | ✅ |
| 25 | `25_Phase25_Calendar_Events_Facilities.md` | ✅ |
| 26 | `26_Phase26_Document_Templates_Certificates_Requests.md` | ✅ |
| 27 | `27_Phase27_Mentoring_Grievances_Discipline_Surveys_Clubs.md` | ✅ |
| 28 | `28_Phase28_Placement_Internships_Training.md` | ✅ |
| 29 | `29_Phase29_Alumni_Endowments_Fundraising.md` | ✅ |
| 30 | `30_Phase30_Research_Faculty_Development.md` | ✅ |
| 31 | `31_Phase31_PhD_Research_Scholar_Management.md` | ✅ |
| 32 | `32_Phase32_Accreditation_Compliance_IQAC.md` | ✅ |
| 33 | `33_Phase33_Governance_Committees_Legal_EFile.md` | ✅ |
| 34 | `34_Phase34_Affiliation_Management.md` | ✅ |
| 35 | `35_Phase35_Dashboards_Analytics_Early_Warning.md` | ✅ |
| 36 | `36_Phase36_Reports.md` | ✅ |
| 37 | `37_Phase37_Audit_Logs_Settings.md` | ✅ |
| 38 | `38_Phase38_Super_Admin_SaaS.md` | ✅ |
| 39 | `39_Phase39_Portals_PWA.md` | ✅ |
| 40 | `40_Phase40_Public_Website_Catalogue_Admission_Portal.md` | ✅ |
| 41 | `41_Phase41_Integrations_Hub_Data_Migration.md` | ✅ |
| 42 | `42_Phase42_Flutter_Mobile_App.md` | ✅ |
| 43 | `43_Phase43_Testing_Security_Privacy_Hardening.md` | ✅ |
| 44 | `44_Phase44_Deployment_CICD_Operations.md` | ✅ |

## Stage 2 — Build (execute the prompts, one phase per session)

**Stage 1 is complete (Batch J, 2026-09-15). Phase 00 done (2026-09-16, merged to `main`). Phase 01 done (2026-09-16, merged to `main` as `2001f1b`).** Next session: branch `phase-02` off `main`, then execute `Prompts/02_Phase02_Auth_RBAC_Features_Visibility.md` (row `02` below is ☐ next); tick here with the commit hash and the verification script result (`scripts/verify/NN_*.ps1` pass/fail) after each phase. **Redis is required from Phase 01 onward** — the live `01_platform.ps1` run (worker + Beat) is still owed on a machine with Redis (see the Phase 01 row and decisions log 2026-09-16).

| Phase | Status | Commit | API verification | UI verification |
|---|---|---|---|---|
| 00 Prerequisite | ✅ done | `d4ffa74` | in-process ASGI checks pass (health, 404/401/422 envelopes, X-Request-Id, CORS, /metrics, docs); guards drift/authz/feature-registry green; `scripts/verify/00_prerequisite.ps1` + `GET /ready` **deferred** (no Redis locally — run on the server / at Phase 01 start) | Vite shell renders login (RHF+Zod errors), `/dashboard` → `/login` redirect, 404 page; `tsc`/`eslint` clean; `flutter analyze` clean |
| 01 | ✅ done | `8878031` | `alembic upgrade head` on the empty local PG18 = 411 tables, single head, downgrade/upgrade round-trip; `check_schema_drift.py --phase 01` = 0 (44 models); authz/feature-registry/import-linter/ruff/black/mypy/bandit green; `scripts/verify/01_platform_inprocess.py` **PASS (45 checks)** — health/ready, public + mobile config, read-only gate (env + super-admin window + revert), help, feedback + Idempotency-Key replay/409, search, jobs (`_dev/jobs/sleep` queued→running→succeeded with `jobs:{user}` progress events, cancel 409/queued-cancel), signed upload route (200/403/expired), WS 4401/hello/pong, tenant `X-Institution-Id` pins RLS; `01_platform_db.py outbox-inprocess` (test.ping consumed once, test.fail re-armed with backoff, duplicate skipped) and `partitions` (12 monthly partitions created, default rows moved) pass; `file_service_check.py` PASS (8). **Deferred — needs Redis:** the live `scripts/verify/01_platform.ps1` run (Celery worker + Beat: step 5 relay through the broker, step 7 tray over uvicorn, `/ready` with real Redis) — run on the server / once Redis exists locally | Checklist 1–6 walked in Chrome against `backend-noredis` + Vite with a `dev_token.py` session: shell (MAIN group only), navbar placeholders, appearance menu (theme/mode/table style persist across reload); `/jobs` updates live (tray badge, progress bar → 100 %, cancel → toast); read-only banner + disabled write buttons when the window is open; `Ctrl+K` palette returns gracefully with no hits and offers “See all results”; `/help` lists 5 platform articles, detail renders, feedback form validates then submits + toasts; 403/feature-disabled/404 pages render with a Back link |
| 02 | ☐ next | | | |
| 03 | ☐ | | | |
| 04 | ☐ | | | |
| 05 | ☐ | | | |
| 06 | ☐ | | | |
| 07 | ☐ | | | |
| 08 | ☐ | | | |
| 09 | ☐ | | | |
| 10 | ☐ | | | |
| 11 | ☐ | | | |
| 12 | ☐ | | | |
| 13 | ☐ | | | |
| 14 | ☐ | | | |
| 15 | ☐ | | | |
| 16 | ☐ | | | |
| 17 | ☐ | | | |
| 18 | ☐ | | | |
| 19 | ☐ | | | |
| 20 | ☐ | | | |
| 21 | ☐ | | | |
| 22 | ☐ | | | |
| 23 | ☐ | | | |
| 24 | ☐ | | | |
| 25 | ☐ | | | |
| 26 | ☐ | | | |
| 27 | ☐ | | | |
| 28 | ☐ | | | |
| 29 | ☐ | | | |
| 30 | ☐ | | | |
| 31 | ☐ | | | |
| 32 | ☐ | | | |
| 33 | ☐ | | | |
| 34 | ☐ | | | |
| 35 | ☐ | | | |
| 36 | ☐ | | | |
| 37 | ☐ | | | |
| 38 | ☐ | | | |
| 39 | ☐ | | | |
| 40 | ☐ | | | |
| 41 | ☐ | | | |
| 42 | ☐ | | | |
| 43 | ☐ | | | |
| 44 | ☐ | | | |

## Validation commands (run before every commit)

```bash
python scripts/verify_prompts_vs_schema.py            # all prompts' table refs exist in Database_Schema.sql
grep -c "^CREATE TABLE" Database_Schema.sql           # 411 (406 + 5 partition defaults)
```
Schema re-validation on a local PostgreSQL (optional, after any DDL change):
```bash
psql -U postgres -c "CREATE DATABASE universe_schema_check;" && psql -U postgres -d universe_schema_check -v ON_ERROR_STOP=1 -q -f Database_Schema.sql && psql -U postgres -c "DROP DATABASE universe_schema_check;"
```

## Decisions log (append-only)

- 2026-09-13 — Greenfield repo mirroring Orbit architecture; tenant = institution + colleges; India-first packs; full doc set first (MASTER_PLAN §1.1).
- 2026-09-13 — **No unit tests**: verification via API scripts + UI functional checks; structural CI guards only (ADR 0006).
- 2026-09-13 — Schema-first: Alembic `0001` applies `Database_Schema.sql`; phase migrations are delta-only; table count 406 (design grew from the ~270 estimate — accepted).
- 2026-09-13 — One batch per session; `PROGRESS.md` + `docs/HANDOFF.md` are the resume points.
- 2026-09-13 — Table ownership across Round 3: `amc_contracts` (§21) and `emergency_alerts` (§23) are owned by Phase 25 (facilities); `conversation_sessions`/`wa_processed_messages` are created in Phase 04 but the bot logic lives in Phase 24; Phase 22 seeds a `vendor` portal role; Phase 26 back-fills earlier `pdf_url` rows into `issued_documents` and becomes the single renderer/verify endpoint.
- 2026-09-13 — Round 4 ownership: Phase 27 ships a minimal `committees` CRUD stub that Phase 33 replaces (same tables); `exam_centres` CRUD from Phase 14 moves under Phase 34; the metric registry (`app/core/metrics.py`) is defined in Phase 32 but every earlier module registers its computation functions (CI guard `check_metric_registry.py`); Phase 30 owns `publications` incl. scholar tagging used by Phase 31.
- 2026-09-13 — User asked mid-batch why implementation has not started: Stage 1 (doc set) precedes Stage 2 (build) by design; Stage 2 may start any time after this batch since prompts 00–34 are complete — decide at the start of the next session (Batch H vs Stage 2 Phase 00/01).
- 2026-09-13 — Round 5 ownership: Phase 35 adds **materialized views only** (`mv_*` read models, created by `0035_…` and mirrored into `Database_Schema.sql` as a new section 37; drift guard treats them as views) and stores early-warning interventions as Phase 27 `mentoring_sessions` rows; Phase 36 retro-registers every Round 1–4 `/…/reports/{key}` export into the report registry (old routes stay as aliases) and owns the renderers Phase 32 calls; Phase 37 consolidates all retention/purge/archival jobs (incl. Phase 25 visitor PII purge) and adds `check_audit_coverage.py`; Phase 38 records SaaS billing on `institution_subscriptions`/`pending_registrations` (never tenant fee tables) and delegates tenant/user export implementation to Phase 41; Phase 39 aggregates portal pages without new visibility rules (self/wards/ownership only); Phase 43 seeds a 52nd role template `privacy_officer` and permissions `privacy:manage`, `security:manage`, `qa:run`; Phases 42–44 add no DDL.
- 2026-09-15 — Batch I: infra files are written so CI is green before any code exists — every workflow has a `detect` job and each guard script (`check_metric_registry.py` … `check_migration_safety.py`) switches itself on when its file appears; `guards.yml` is also `workflow_call`-ed by `build.yml`. Phase 43/44 workflows (`security.yml`, `verify.yml`, `release.yml`, `mobile-release.yml`) ship now as self-enabling skeletons those phases complete. The Postgres role bootstrap lives in `docker/postgres/init/01_roles.sql` (not named in the prerequisite prompt's tree; Phase 00 should reference it). `nginx.conf` keeps `/site/` on a `$ssr_upstream` map (default `backend`; Phase 40 switches it to `ssr:5175`). Prompts unchanged (guard: 0 missing).
- 2026-09-15 — Batch J (Stage 1 sign-off): guard 44/44 prompts 0 missing; Coverage Matrix cross-check found no uncovered rows, only naming drift — matrix rows now use exact schema table names (`user_sessions`, `library_eresources`, `transport_routes`/`transport_trips`, the five website tables) and the mobile row lists Phase 07 as owner of `students.id_cards`; Phase 02 prompt names `core.auth`/`core.rbac` explicitly (registered in Phase 01, non-toggleable). `planning-docs` merged into `main` with `--no-ff`; **Stage 2 starts from `main`** — branch `phase-00` (or similar) off `main` per build session. Not pushed to `origin` (user to push).
- 2026-09-16 — **Phase 00 executed** (branch `phase-00`, commit `d4ffa74`). Decisions: (1) `models/platform.py` maps the 20 tables the core skeleton needs (tenancy, auth, RBAC, features, jobs, events, idempotency, workflow, read-only, audit); Phase 01 completes the 44 and adds `phase_manifest.py["01"]`; `check_schema_drift.py` compares only modelled tables by default (`--phase NN` = manifest, `--strict` = every SQL table, Phase 43+). (2) `PUBLIC_ROUTES` holds `POST /api/v1/auth/login` as a Phase 00 placeholder returning `401 UNAUTHENTICATED` so `_common.ps1` has a real endpoint; Phase 02 replaces the module. (3) `IDEMPOTENT_REPLAY` is answered as **200 with the stored envelope** plus `meta.idempotent_replay=true` and header `Idempotent-Replayed: true` (Phase 09/42 wording "same response"). (4) Feature seeding: `seed_platform.py` upserts all 356 `docs/Feature_Flags.md` keys into `platform_features` (group from the doc section, `is_core` = `core.*`) and derives plan `enabled_features` per tier; permissions/plans reuse the canonical §36 statements verbatim; role templates (NULL `institution_id`) are inserted when missing. (5) Demo seeders register with `@seeder("<module>", after=[...])` in `backend/scripts/seeders/<module>.py`; Phase 02 adds `base`. (6) Runtime: local machine has PostgreSQL 18 (`universe` DB + roles created; **empty — Phase 01 runs `alembic upgrade head` on it**) but **no Redis** (port 6379 is held by a VS Code process; Memurai install did not complete) — user decided to test the live stack (`/ready`, `00_prerequisite.ps1`, compose) on the server; every later phase needs Redis for `/ready`, Celery and the verification scripts. (7) Table count note: `Database_Schema.sql` = 405 tables + 6 partition defaults = 411 (Stage 1 wrote "406 + 5"; the grep total 411 is what CI checks). (8) `ORJSONResponse` is deprecated in FastAPI 0.135 — kept per the prompt, warning filtered in `main.py`; revisit in Phase 44. (9) Flutter formatting: SDK constraint stays `>=3.4.0` (CI pins Flutter 3.22.x), so `require_trailing_commas` was dropped from `analysis_options.yaml` (old formatter); l10n output is committed under `flutter/lib/l10n/`.
- 2026-09-16 — **Phase 01 executed** (branch `phase-01` off `main` after `phase-00` was merged `--no-ff`; commit `8878031`). Decisions: (1) **DDL owner = platform role**: `alembic/env.py` connects with `PLATFORM_DATABASE_URL` (falls back to `DATABASE_URL`); revision `0001` grants tables/sequences/functions + default privileges to the *other* role, so `universe_app` runs under RLS as a non-owner while the outbox relay, partition maintenance, job bookkeeping and the `search_documents` refresh run on `PlatformSessionLocal` (BYPASSRLS). Empirically necessary: with FORCE RLS the app role without a tenant context sees only `institution_id IS NULL` rows, and a matview refresh runs as the matview owner. `docker/postgres/init/01_roles.sql` now makes `universe_platform` the DB/schema owner; the local `universe` DB was rebuilt that way. CI already migrated as `universe_platform`. (2) **RLS context via `SELECT set_config('app.institution_id', :i, true)`** re-applied by an `after_begin` session hook (`db/session.py: bind_tenant/set_tenant`): the Phase 00 `SET LOCAL … = :i` form is a syntax error under asyncpg (bind parameters are not allowed in `SET`) and `SET LOCAL` would have died at the first mid-request/mid-job commit. (3) `0001` applies `Database_Schema.sql` through `alembic/sql_loader.py` (dollar-quote/string-aware splitter; file resolved from repo root, `SCHEMA_SQL_PATH` or `/app/Database_Schema.sql` — compose mounts it because the build context is `backend/`); `downgrade()` drops objects individually instead of `DROP SCHEMA public CASCADE` (the prompt's snippet) so `alembic_version` and the schema grants survive. The base-table count check excludes `alembic_version` (411 + 1). (4) Outbox: `@consumer(name, events=[…])` wrapper is idempotent via `event_consumptions`, a raising consumer re-arms the event (`attempts+1`, `next_attempt_at = now + 2^attempts min`, dead after 10) — the relay no longer increments `attempts` on a successful dispatch; `celery.loader.import_default_modules()` runs before routing so every `include`d task module registers its consumers; `webhooks.deliver` subscribes to `*` (every event gets a second consumption row). (5) `feature_required()` without a tenant context (super admin / platform user) falls back to the key's registry default instead of 403 — platform routes (`POST /platform/read-only`) stay reachable; the read-only middleware exempts `/api/v1/platform/read-only` so a window can always be lifted. (6) File service: `FILE_MIME_SNIFFER=builtin` (signature sniffer, default — python-magic hangs/has no libmagic on Windows) or `magic` (compose sets it; libmagic1 in the image); `GET /uploads/{key}?sig=&exp=` replaces the Phase 00 static mount and nginx now proxies `/uploads/` to the API. (7) Jobs: only `queued` rows start (a worker skips rows another runner claimed); `job.finished` is written by the wrapper; `/_dev/jobs/sleep?inline=true` runs the body inside the API for worker-less machines. (8) Guards: `check_schema_drift.py` matched `checked_at` as a `CHECK` constraint — fixed with whole-word matching; `seed_demo_institution.py` aliases itself in `sys.modules` so seeders importing `seed_demo_institution` register in the running module; Phase 01 routes declare `response_model=Envelope[…]` so `npm run gen:api` yields real schemas (26). (9) Local runtime: still **no Redis** (port 6379 free now, no Memurai/WSL/Docker). Added `scripts/dev_api_fakeredis.py` (launcher `backend-noredis`) and the fakeredis-backed `01_platform_inprocess.py` harness; `fakeredis` is a dev dependency. The live `01_platform.ps1` (worker + Beat) is deferred to the server — everything else in §01.11 was proven in-process or against the dev API. (10) `pip-audit --strict` (CI) was already red on Phase 00 pins: bumped pillow 12.3.0, orjson 3.11.6, weasyprint 70.0, python-multipart 0.0.31, pydantic-settings 2.14.2; still open — `starlette` PYSEC-2026-2280 (fix needs Starlette 1.x → FastAPI ≥ 0.136, revisit with the ORJSONResponse deprecation in Phase 44) and `ecdsa` PYSEC-2026-1325 via `python-jose` (Phase 43: consider PyJWT). (11) Prompt deviations noted: 01.8 `POST /mobile/config` is also served as `GET` (Phase 42 wording); `GET /help/articles/{slug}` added for the detail page; help-centre authoring stays with Phase 37.
