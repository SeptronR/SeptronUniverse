# SeptronUniverse — College & University ERP

Multi-tenant Higher-Education ERP for **affiliated colleges, autonomous colleges, universities (state / private / deemed) and multi-campus institutions**. It is the higher-education sibling of **SeptronOrbit** (school ERP) and follows the same architecture, stack, layer conventions and prompt-driven build process.

| Layer | Stack |
|---|---|
| Backend | FastAPI (async, Python 3.12) · SQLAlchemy 2 async + Alembic · PostgreSQL 15+ (+ Row-Level Security) · Redis 7 · Celery 5 · Pydantic v2 · WeasyPrint + Jinja2 |
| Frontend | React 18 + TypeScript + Vite · React Router v6 · TanStack Query v5 · Zustand · Tailwind + Radix · Recharts · FullCalendar · dnd-kit · TipTap |
| Mobile | Flutter 3.22+ · Riverpod · go_router · dio · drift (offline) · FCM |
| Infra | Docker Compose · GitHub Actions → `ghcr.io/septronr/universe-api` → `orbit-infra` (Traefik) |

## What makes it "higher-ed"

- **Tenancy:** `institution → colleges/campuses → faculties → departments`, with university ↔ affiliated-college workflows.
- **Academics:** programmes → regulations (versioned rules) → curriculum → courses (L-T-P-C) → **course offerings** per term; credit-based registration (NEP 2020 / CBCS, multiple entry-exit, ABC/APAAR).
- **Examinations:** registration & hall tickets → coded (dummy-number) valuation, double valuation, moderation → versioned immutable results (SGPA/CGPA) → revaluation, supplementary, malpractice → convocation & digital credentials (DigiLocker/NAD/ABC).
- **Outcome-Based Education:** PEO/PO/PSO/CO, CO-PO mapping, direct + indirect attainment, CQI.
- **Campus & people:** hostel/mess, library, transport, inventory/procurement, HR/payroll/recruitment/CAS, research & PhD lifecycle, placement & alumni, mentoring/grievances/discipline/surveys, events & facilities, governance (committees, minutes, RTI, legal), accreditation (NAAC/NBA/NIRF/AISHE).
- **Platform:** every feature is a super-admin-controlled flag per institution; every record is visible through a self / ownership / scoped / `view_all` model; approval-workflow engine; transactional outbox; integrations hub; data-migration toolkit.

Institution types (`institutions.institution_type`): `university`, `deemed_university`, `autonomous_college`, `affiliated_college`, `standalone_college`, `multi_campus`. Demo seeds: `--type university | autonomous | affiliated`.

## Repository map

```
backend/                          FastAPI API, Celery workers, Alembic, scripts (see backend/app tree below)
frontend/                         React + Vite web app (admin shell + portals)
flutter/                          Flutter mobile app skeleton (Phase 42 builds the app)
e2e/                              Playwright UI suites, one project per round
docs/                             design authority (see list below) · docs/ADR/ decisions
Prompts/                          one self-contained build prompt per phase (00 prerequisite, 01–44)
Database_Schema.sql               canonical DDL — single source of truth for table/column names (411 CREATE TABLE)
Architecture.md · MASTER_PLAN.md  diagrams and the approved plan
PROGRESS.md · docs/HANDOFF.md     resume points: what is done, what comes next, session protocol
RUN_AFTER_PHASE.md                runbook after each phase (deps, migrate, seed, guards, API script, UI checklist, commit)
QA_Test_Plan.md · Real_World_Launch_Plan.md   QA sweeps and provider/government onboarding trackers
docker-compose.yml                local 8-service stack (postgres, redis, backend, celery_worker, celery_beat, flower, frontend, nginx)
docker-compose.prod.yml           single-host production topology skeleton (Phase 44 completes it)
docker/postgres/init/01_roles.sql creates universe_app (runtime, NOT BYPASSRLS) / universe_platform (schema owner, BYPASSRLS — Alembic migrates as it)
nginx/nginx.conf                  reverse proxy (/api, /ws, /uploads, /site → SSR, security headers, 25M body)
.github/workflows/                guards · security · verify · build · frontend-build · frontend-deploy · release · mobile-release
.claude/launch.json               Claude Code launch targets (backend, backend-noredis, celery-worker, celery-beat, frontend, flower, ssr)
```

Backend layout (`Prompts/00_PREREQUISITE_Project_Setup.md` §2): `app/api/v1` (router + `PUBLIC_ROUTES`), `app/core` (config, security, middleware, errors, features, `authz/` visibility resolver + masking, `packs/` regulatory packs, events/outbox, idempotency, jobs, `workflow/engine.py`, audit, tenancy, files, rate limit, WebSocket hub, logging), `app/db/session.py` (RLS context), `app/models` (mixins + platform models), `app/schemas`, `app/repositories/base.py`, `app/services`, `app/integrations/registry.py`, `app/tasks` (Celery, outbox relay, Beat), `alembic/`, `scripts/` (guards, seeders, scaffolder, `verify/` API scripts).

## Environment setup

Requirements: Python 3.12, Node 20+, PostgreSQL 15+ and Redis 7 (both required — Redis is not optional), Flutter 3.22+ (mobile only), PowerShell 7 for the verification scripts.

### Option A — Docker (recommended)

```powershell
docker compose up -d postgres redis      # infrastructure only, or `docker compose up` for all 8 services
```

### Option B — local services (Windows / Linux)

```powershell
psql -U postgres -c "CREATE DATABASE universe;"
psql -U postgres -f docker/postgres/init/01_roles.sql          # universe_app / universe_platform (password: pass), ownership + grants
# Redis: `redis-server` (Linux/macOS) or Memurai / Redis for Windows on :6379
```

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1               # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env                # edit DATABASE_URL / PLATFORM_DATABASE_URL / REDIS_URL / SECRET_KEY
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Celery worker and Beat (separate terminals): `celery -A app.tasks.celery_app worker -Q notifications,emails,documents,reports,integrations,scheduled -c 4 --pool=solo` and `celery -A app.tasks.celery_app beat`. Flower: `celery -A app.tasks.celery_app flower --port=5555`.

### Frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev                                # http://localhost:5173 — /api, /ws, /uploads, /health proxy to :8000
npm run gen:api                            # regenerate src/api/generated/openapi.d.ts from the running API
```

### Mobile

```powershell
cd flutter
flutter pub get
flutter analyze
flutter run --dart-define=APP_API_URL=http://10.0.2.2:8000/api/v1
```

## Database bootstrap

1. Roles + database as above (`01_roles.sql`).
2. Schema: `alembic upgrade head` — `0001_phase01_initial_schema.py` applies `Database_Schema.sql` (411 tables, RLS, triggers, seeds) as the platform role (`PLATFORM_DATABASE_URL`); `python scripts/check_schema_drift.py --phase 01` → 0 diffs.
3. `python scripts/seed_platform.py` — permissions, role templates, `platform_features` (from `docs/Feature_Flags.md`), plans, packs, super admin (credentials → `LOCAL_TEST_CREDENTIALS.md`, git-ignored).
4. `python scripts/seed_demo_institution.py --type university --only base` (Phase 02) — demo institution, colleges, roles and one demo user per role.

Health: `GET /health` → `{status:"ok"}`, `GET /ready` → DB + Redis + storage + migration head + outbox lag (503 `degraded` when a hard dependency fails), `/api/v1/docs` for Swagger, `/metrics` for Prometheus. Without a local Redis, `python scripts/dev_api_fakeredis.py` starts the API with an in-memory stand-in (dev only, no workers).

## How to run the phase prompts

1. Read `Prompts/00_HOW_TO_USE.md`; `Prompts/00_PREREQUISITE_Project_Setup.md` is done (this skeleton).
2. Execute prompts in numeric order — one phase per session (`docs/HANDOFF.md` §5). Rounds are sequential; prompts inside a round may run in parallel worktrees when they touch disjoint models (one Alembic revision each, `alembic merge heads` once per round).
3. `python backend/scripts/scaffold_module.py <module> --feature <key> --permissions <module> --phase NN` generates the module skeleton following every convention.
4. After each prompt run `RUN_AFTER_PHASE.md`: deps → migrate (`alembic heads` = 1, `check_schema_drift.py` = 0) → seed → guards → the phase's `scripts/verify/NN_<module>.ps1` → UI checklist → `export_openapi.py` + `gen_access_matrix.py` + `npm run gen:api` → commit `feat(phase-NN): …` → tick `PROGRESS.md`.

## Verification philosophy

Phases are verified **functionally** (ADR 0006) — by calling the API per role (`backend/scripts/verify/*.ps1`, dot-sourcing `_common.ps1`) and by exercising the UI (Playwright suites in `e2e/`, per-role sweeps in `QA_Test_Plan.md`) — not by unit tests. Structural CI guards remain and must be green before the next phase:

```powershell
cd backend
python scripts/check_schema_drift.py        # Base.metadata vs Database_Schema.sql (--phase NN, --strict)
python scripts/check_authz_coverage.py      # every /api/v1 route has permission_required + feature_required or is in PUBLIC_ROUTES
python scripts/check_feature_registry.py    # code registry ↔ docs/Feature_Flags.md (↔ platform_features with --db)
ruff check app scripts; black --check app scripts; mypy app; lint-imports; bandit -r app -q -ll
cd ../frontend; npm run lint; npx tsc --noEmit
cd ../flutter; flutter analyze; dart format --set-exit-if-changed lib
```

## Deployment

Images are built by `.github/workflows/build.yml` and pushed to `ghcr.io/septronr/universe-api:{env}-{sha}`; deployment runs on the shared **`../orbit-infra`** platform (Traefik, Postgres, Redis, monitoring) as `compose/apps/universe-{dev,demo,prod}-api.yml`. `docker-compose.prod.yml` documents the single-host topology; Phase 44 finishes the pipeline (release, migrations with advisory lock, backups, DR).

## Related repositories

- `../SeptronOrbit` — the school ERP whose architecture and conventions this project mirrors.
- `../orbit-infra` — shared production platform.
