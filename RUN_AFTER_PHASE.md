# Runbook: commands to run after every phase (Stage 2)

Run these from the project root (`SeptronUniverse`) on Windows PowerShell after executing a phase prompt and **before** committing `feat(phase-NN): …`. Adapted from SeptronOrbit's `RUN_AFTER_PHASE.md`; the guard list grows as phases add scripts (each is skipped while its file does not exist yet — Phase 44 completes this file).

Order per phase: **1 update deps → 2 migrate → 3 seed → 4 guards → 5 API verification script → 6 UI checklist → 7 regenerate artefacts → 8 commit + `PROGRESS.md`**.

---

## 0) One-time setup (first time on a machine)

### Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
Copy-Item .env.example .env          # then edit DATABASE_URL / PLATFORM_DATABASE_URL / REDIS_URL
cd ..
```

### Frontend
```powershell
cd frontend
npm install
if (Test-Path .env.example) { Copy-Item .env.example .env -Force }
cd ..
```

### Infrastructure — PostgreSQL 15+ and Redis 7 (both required; Redis is not optional in Universe)

Option A — Docker (recommended, matches `docker-compose.yml`):
```powershell
docker compose up -d postgres redis
```
Option B — local services. Create the two roles and the database exactly as `Prompts/00_PREREQUISITE_Project_Setup.md` §8 describes (`universe_app` is **not** `BYPASSRLS`; `universe_platform` is and **owns the schema** — Phase 01 decision):
```powershell
psql -U postgres -c "CREATE DATABASE universe;"
psql -U postgres -f docker/postgres/init/01_roles.sql      # roles + ownership + default privileges (idempotent)
```
Defaults in `backend/.env.example`: `DATABASE_URL=postgresql+asyncpg://universe_app:pass@…` (runtime, RLS applies), `PLATFORM_DATABASE_URL=postgresql+asyncpg://universe_platform:pass@…` (**Alembic migrates with this one** — `alembic/env.py` picks it up; keep both set) and `redis://localhost:6379/0`.

No Redis on the workstation? The API cannot start (`/ready`, Celery, WebSocket hub all need it). For shell/UI work only, `python backend/scripts/dev_api_fakeredis.py` (launcher `backend-noredis`) runs the API with an in-memory Redis stand-in — no worker/Beat, jobs stay queued unless enqueued with `inline=true` (dev route). The API verification scripts still need the real stack.

### Flutter (only when a phase touches `flutter/`)
```powershell
cd flutter
flutter pub get
cd ..
```

---

## 1) After every new phase (update dependencies)

```powershell
cd backend; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; pip install -r requirements-dev.txt; cd ..
cd frontend; npm install; cd ..
```

---

## 2) Migrate — one revision per phase, single head, zero drift

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
alembic current
alembic heads                                   # must print exactly ONE head
alembic upgrade head
python scripts/check_schema_drift.py            # Base.metadata vs Database_Schema.sql → 0 diffs
cd ..
```

Rules (from `Prompts/00_PREREQUISITE_Project_Setup.md` §3.22 and ADR 0001/0007):
- The phase's revision is hand-written as `NNNN_phaseNN_<module>.py` with a real `down_revision`. `alembic revision --autogenerate` may be used **only** to draft it; open the file and keep only this phase's changes.
- `0001_phase01_initial_schema.py` applies `Database_Schema.sql` through `alembic/sql_loader.py` (the file is resolved from the repo root, `SCHEMA_SQL_PATH` or `/app/Database_Schema.sql` in containers); every later revision is **delta-only** (most phases: data-only seed revisions — "Expected delta migration: none"). `alembic downgrade base` drops every object but keeps `alembic_version` and the schema grants.
- Alembic connects as the **platform role** (`PLATFORM_DATABASE_URL`): the schema is owned by `universe_platform` (BYPASSRLS — outbox relay, partition maintenance and the `search_documents` refresh run on it) and `0001` grants the runtime privileges to `universe_app`, which is bound by RLS as a non-owner.
- A phase that adds tables also appends them to `scripts/phase_manifest.py` (`check_schema_drift.py --phase NN`).
- Never `Base.metadata.create_all` outside `check_schema_drift.py`. Never `alembic stamp` blindly: if the DB is out of sync, rebuild it (section 9).
- Expand/contract: no destructive DDL in the same release as the code that stops using it (`# contract-of: <revision>` marker; lint `check_migration_safety.py` arrives in Phase 44).

Parallel prompts inside a round (Round 3/4 only): each worktree chains on the round's base revision; after merging run `alembic merge heads -m "round-N merge"` **once**, then `alembic upgrade head` and the drift check again.

---

## 3) Seed — platform registries, then the demo institution

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python scripts/seed_platform.py                          # permissions, role templates, features (docs/Feature_Flags.md), plans, packs — idempotent
python scripts/seed_demo_institution.py --type university --only <module>   # the module key named in the prompt's NN.2 (e.g. --only fees)
cd ..
```

- First run on an empty DB: `python scripts/seed_demo_institution.py --type university --only base` (Phase 02) creates `demo-uni`, its colleges, roles and one demo user per role; credentials are written to `LOCAL_TEST_CREDENTIALS.md` (git-ignored — never commit).
- Full re-seed of every module in one go (Phase 43 onwards): `python scripts/seed_demo_institution.py --type university --all`.
- Other institution types for verification: `--type autonomous`, `--type affiliated`.

---

## 4) Structural guards (CI runs the same list in `.github/workflows/guards.yml`)

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
ruff check app scripts; black --check app scripts; mypy app
lint-imports                                             # import-linter contracts (pyproject.toml)
python scripts/check_schema_drift.py                     # Phase 00 — 0 diffs
python scripts/check_authz_coverage.py                   # Phase 00 — every route has permission + feature or is in PUBLIC_ROUTES
python scripts/check_feature_registry.py                 # Phase 00 — registry ↔ docs/Feature_Flags.md ↔ DB seed
# Guards added by later phases — run each one as soon as the file exists:
python scripts/check_metric_registry.py                  # Phase 32 — every seeded metric key has a registered computation
python scripts/check_report_registry.py                  # Phase 36 — every /…/reports/{key} route resolves to a registered report
python scripts/check_adapter_registry.py                 # Phase 41 — every capability in docs/Integrations_Catalogue.md has adapters + mock
python scripts/check_audit_coverage.py                   # Phase 37 — 0 unaudited mutations
python scripts/check_pii_masking.py                      # Phase 43 — PII inventory fields are Masked[] and never logged
python scripts/check_access_matrix.py                    # Phase 43 — 0 unexpected grants vs docs/Roles_and_Permissions.md §3
python scripts/check_migration_safety.py                 # Phase 44 — expand/contract lint on the new revision
cd ..
cd frontend; npm run lint; npx tsc --noEmit; cd ..
# Only when the phase changed flutter/:
cd flutter; flutter analyze; dart format --set-exit-if-changed lib; cd ..
```

One-liner that runs every guard that exists (same loop as CI):
```powershell
cd backend; .\.venv\Scripts\Activate.ps1
foreach ($g in "check_schema_drift","check_authz_coverage","check_feature_registry","check_metric_registry","check_report_registry","check_adapter_registry","check_audit_coverage","check_pii_masking","check_access_matrix","check_migration_safety") {
  if (Test-Path "scripts/$g.py") { Write-Host "== $g"; python "scripts/$g.py"; if ($LASTEXITCODE -ne 0) { throw "$g failed" } } else { Write-Host "-- $g (not yet present)" }
}
cd ..
```

Security scans (`security.yml`, Phase 43) are CI-only; run locally when a phase adds dependencies: `pip-audit -r requirements.txt`, `npm audit --audit-level=high`, `bandit -r app -q`.

---

## 5) Run the stack (local development)

Preferred — Claude Code launcher (`.claude/launch.json`): `backend`, `celery-worker`, `celery-beat`, `frontend`, `frontend-demo-api`, `flower`.

Manual terminals:
```powershell
# Terminal 1 — API (the app lives in backend/main.py, not app/main.py)
cd backend; .\.venv\Scripts\Activate.ps1; $env:PYTHONUTF8="1"; uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Celery worker (all six queues) — required for outbox relay, notifications, PDFs, reports, imports
cd backend; .\.venv\Scripts\Activate.ps1; celery -A app.tasks.celery_app worker -Q notifications,emails,documents,reports,integrations,scheduled -c 4 --loglevel=info --pool=solo

# Terminal 3 — Celery Beat (outbox relay every 5 s, scheduled jobs)
cd backend; .\.venv\Scripts\Activate.ps1; celery -A app.tasks.celery_app beat --loglevel=info

# Terminal 4 — web
cd frontend; npm run dev
```
Or everything in containers: `docker compose up` (8 services — see `docker-compose.yml`; nginx on http://localhost, API on :8000, web on :5173, Flower on :5555).

Quick health checks:
```powershell
Invoke-RestMethod http://localhost:8000/health          # {status:"ok"}
Invoke-RestMethod http://localhost:8000/ready           # DB + Redis + storage + migrations head + outbox lag
Start-Process http://localhost:8000/docs
Start-Process http://localhost:5173
```

---

## 6) API verification — the phase's script, every role

```powershell
cd backend
.\scripts\verify\NN_<module>.ps1                        # e.g. .\scripts\verify\12_fees.ps1  (dot-sources scripts/verify/_common.ps1; -BaseUrl http://localhost:8000/api/v1)
cd ..
```
- The script must pass **for every role listed in the prompt's NN.11** (status codes, envelope, `meta.visibility`, business outcomes). Fix the code, not the script, unless the prompt is wrong (then fix the prompt and note it in `PROGRESS.md`).
- Phase 01 (`01_platform.ps1`) needs the API **and** a Celery worker + Beat (outbox step 5, job step 7); it mints the super-admin token with `scripts/dev_token.py` until Phase 02 ships login. `scripts/verify/01_platform_inprocess.py` (fakeredis, ASGI transport, no uvicorn) proves the same contracts on a machine without Redis and is a good pre-flight before the live run.
- Regression: re-run the previous phase's script too (`scripts/verify/run_all.ps1 --suite api_round_<n>` once Phase 43 ships the runner; until then, run the scripts of the current round by hand).

## 7) UI verification — the prompt's NN.12 checklist

Walk the checklist per role in the browser against the running stack (Playwright round suites in `e2e/` from Phase 43 onward: `cd e2e; npx playwright test --project round<n>`). Log defects in `QA_Test_Plan.md` §8 format / `QA_Findings.csv`.

---

## 8) Regenerate derived artefacts, then commit

```powershell
cd backend; .\.venv\Scripts\Activate.ps1
python scripts/export_openapi.py                         # backend/openapi.json (+ Dart/TS generation input)
python scripts/gen_access_matrix.py                      # docs/Access_Matrix.csv (route × role)
cd ..
cd frontend; npm run gen:api; cd ..                      # src/api/generated/openapi.d.ts (backend must be running on :8000)
git add -A
git commit -m "feat(phase-NN): <module>"                 # message from the prompt's NN.13
```
Then tick the phase in `PROGRESS.md` (Stage 2 table: commit hash, `scripts/verify/NN_*.ps1` pass/fail, UI checklist done) and commit `docs: progress - phase NN done`. **Never start the next phase in the same session** (`docs/HANDOFF.md` §5).

---

## 9) Missed phases or broken DB? Catch up / rebuild

### Option A — keep data (schema mostly intact)
```powershell
cd backend; .\.venv\Scripts\Activate.ps1
alembic current; alembic heads; alembic upgrade head
python scripts/check_schema_drift.py
python scripts/seed_platform.py
cd ..
```

### Option B — fresh rebuild (destructive, guaranteed clean baseline)
```powershell
psql -U postgres -c "DROP DATABASE IF EXISTS universe;"
psql -U postgres -c "CREATE DATABASE universe;"
psql -U postgres -f docker/postgres/init/01_roles.sql    # ownership → universe_platform, USAGE → universe_app
cd backend; .\.venv\Scripts\Activate.ps1
alembic upgrade head                                     # runs as PLATFORM_DATABASE_URL: 0001 loads Database_Schema.sql, later revisions apply deltas/seeds
python scripts/check_schema_drift.py
python scripts/seed_platform.py
python scripts/seed_demo_institution.py --type university --all   # (--only base until Phase 43 ships --all)
cd ..
```
Docker variant: `docker compose down -v; docker compose up -d postgres redis` then the same `alembic`/seed commands (or `docker compose run --rm -e RUN_MIGRATIONS=1 backend true`).

### Schema validation against the canonical DDL (after any change to `Database_Schema.sql`)
```powershell
psql -U postgres -c "CREATE DATABASE universe_schema_check;"
psql -U postgres -d universe_schema_check -v ON_ERROR_STOP=1 -q -f Database_Schema.sql
psql -U postgres -c "DROP DATABASE universe_schema_check;"
python scripts/verify_prompts_vs_schema.py               # every prompt's table refs exist (Stage 1 guard, keep green)
```

---

## 10) Per-phase checklist (copy into the session)

- [ ] deps updated · `alembic heads` = 1 · `alembic upgrade head` · drift = 0
- [ ] `seed_platform.py` · `seed_demo_institution.py --only <module>`
- [ ] guards green (authz, feature registry, drift, + metric/report/adapter/audit/pii/access-matrix/migration-safety where present, import-linter, ruff/black/mypy, eslint/tsc, flutter analyze when mobile changed)
- [ ] `scripts/verify/NN_<module>.ps1` passes for every role in NN.11
- [ ] NN.12 UI checklist walked per role (Playwright round suite green from Phase 43)
- [ ] `export_openapi.py` · `gen_access_matrix.py` · `npm run gen:api`
- [ ] commit `feat(phase-NN): …` · `PROGRESS.md` Stage 2 row ticked with results
