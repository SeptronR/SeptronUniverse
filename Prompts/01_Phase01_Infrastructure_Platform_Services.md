# PHASE 01 — INFRASTRUCTURE & PLATFORM SERVICES

## Pre-Requisite
`00_PREREQUISITE_Project_Setup.md` complete: monorepo skeleton, boilerplate files, Docker Compose up, `/health` OK, guards runnable.

## Objective
Turn the skeleton into a running platform: apply the canonical schema through Alembic, model the platform tables, wire observability, the file service, background jobs with a tray, the transactional-outbox relay, idempotency, the Redis-backed WebSocket hub, global search, read-only mode, and the web shell (sidebar, navbar with institution/college switcher and year/term selector, jobs tray, notification bell). No business modules yet — but everything a business module needs.

## Feature keys
Registers the core keys (non-toggleable): `core.auth`, `core.rbac`, `core.institution`, `core.settings`, `core.audit_logs`, `core.dashboard`, `core.notifications_inapp`, `core.background_jobs`; plus `platform.read_only_mode` (default on), `search.global` (default on), `platform.help_center`, `platform.in_app_feedback`, `platform.guided_tours` (default on, starter).

## Visibility rules
- `background_jobs`: **self** (requester) for everyone; `jobs:view_all` for institution_admin/integration_admin (institution scope); super admin all.
- `notifications`: self only. `help_articles`: everyone in the institution (+ platform articles). `feedback_entries`: self; `settings:view_all` sees all.

## 01.1 Database tables
Sections **1–6** of `Database_Schema.sql`: `institutions, institution_profile, colleges, faculties, departments, institution_settings, holidays, number_sequences, users, password_reset_tokens, user_sessions, mfa_secrets, login_history, ip_allowlists, device_tokens, credential_sheets, permissions, roles, role_permissions, user_roles, platform_features, institution_feature_flags, feature_flag_changes, background_jobs, domain_events (+default partition), event_consumptions, idempotency_keys, workflow_definitions, workflow_instances, workflow_steps, workflow_delegations, api_keys, webhooks, webhook_deliveries (+default), integration_connections, integration_health_checks, data_imports, data_import_rows, consent_records, data_subject_requests, read_only_modes, help_articles, feedback_entries, audit_logs (+default)`.
Also the helper functions (`trigger_set_updated_at`, `attach_updated_at_trigger`, `current_institution_id`, `trigger_bump_version`), the RLS block (§34), the trigger block (§35) and seeds (§36). **Copy — do not retype.**

## 01.2 Alembic migration — `0001_phase01_initial_schema.py`
Schema-first: the initial revision applies the entire canonical `Database_Schema.sql` so that every later phase finds its tables in place (the same "verify tables exist" discipline Orbit used).
```python
# alembic/versions/0001_phase01_initial_schema.py
from alembic import op
from alembic.sql_loader import load_statements   # splits the file into statements, honouring $$ dollar-quoted blocks and DO $$ … $$;
revision, down_revision = "0001", None
def upgrade():
    for stmt in load_statements("../Database_Schema.sql"):
        op.execute(stmt)
def downgrade():
    op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
```
`alembic/sql_loader.py`: reads the file, strips `--` comments outside strings, splits on `;` at depth 0 (track `$$`/`$tag$` quoting and single quotes), yields non-empty statements. Verify with `alembic upgrade head` on an empty DB → table count 411, then `alembic downgrade base && alembic upgrade head` again.
Rule for all later phases: **expected delta migrations = none**. If a phase needs a change, edit `Database_Schema.sql` first (it stays canonical), then add `NNNN_phaseNN_<module>_delta.py` with the same change, and update `docs/Academic_Core_Design.md`. `scripts/check_schema_drift.py --phase NN` compares only the tables in `scripts/phase_manifest.py[NN]`.

## 01.3 Models — `app/models/platform.py`
`Institution`, `InstitutionProfile`, `College`, `Faculty`, `Department`, `InstitutionSetting`, `Holiday`, `NumberSequence`, `User`, `PasswordResetToken`, `UserSession`, `MfaSecret`, `LoginHistory`, `IpAllowlist`, `DeviceToken`, `CredentialSheet`, `Permission`, `Role`, `RolePermission`, `UserRole`, `PlatformFeature`, `InstitutionFeatureFlag`, `FeatureFlagChange`, `BackgroundJob`, `DomainEvent`, `EventConsumption`, `IdempotencyKey`, `WorkflowDefinition`, `WorkflowInstance`, `WorkflowStep`, `WorkflowDelegation`, `ApiKey`, `Webhook`, `WebhookDelivery`, `IntegrationConnection`, `IntegrationHealthCheck`, `DataImport`, `DataImportRow`, `ConsentRecord`, `DataSubjectRequest`, `ReadOnlyMode`, `HelpArticle`, `FeedbackEntry`, `AuditLog`. Use the mixins from `models/base.py`; relationships `lazy="noload"` with explicit `selectinload` in repositories (Orbit convention). `DomainEvent`, `WebhookDelivery`, `AuditLog` map to the partitioned parents (`__table_args__ = {"postgresql_partition_by": "RANGE (created_at)"}`). `scripts/phase_manifest.py["01"]` lists these tables; run `check_schema_drift.py --phase 01` → 0 diffs.

## 01.4 Schemas — `app/schemas/platform.py`
`HealthResponse`, `JobResponse` (id, job_type, status, progress_pct, message, result_url, created_at), `JobListQuery`, `ReadOnlyModeRequest`, `HelpArticleResponse`, `FeedbackCreate`, `SearchResult` (entity_type, entity_id, title, subtitle, route), `InstitutionSummary` (id, name, slug, type, logo_url, timezone, locale, currency), `CollegeSummary`.

## 01.5 Repository
`repositories/platform_repository.py`: `JobRepository(BaseRepository[BackgroundJob], module="jobs")`, `SearchRepository` (queries `search_documents` with `plainto_tsquery` + visibility scope), `HelpRepository`, `FeedbackRepository`, `ReadOnlyModeRepository`. Register visibility: `ModuleVisibility("jobs", BackgroundJob, self_predicate=lambda p, m: m.requested_by == p.id, scope_columns={"institution": "institution_id"})`.

## 01.6 Services
- `services/job_service.py`: `enqueue(db, principal, job_type, params, queue)` → row + Celery `apply_async(args=[job_id], queue=…)`; `cancel(job_id)` sets `cancel_requested`; `progress(job_id, pct, message)` publishes on Redis channel `jobs:{user_id}`; cleanup Beat job purges succeeded jobs older than 7 days (files older than `expires_at`).
- `services/file_service.py`: `save(upload, folder, allowed_types, max_mb, institution_id)` → key `{institution_id}/{folder}/{uuid}.{ext}`; MIME sniff with `python-magic`; quota check against plan (`storage_gb`); `signed_url(key, ttl)`; local backend serves `/uploads/{key}?sig=…&exp=…` (HMAC), S3 backend presigns; optional ClamAV via `CLAMAV_HOST`.
- `services/search_service.py`: `search(principal, q, entity_types)` → top 20 with routes; refresh of `search_documents` is triggered by the outbox consumer `search.reindex` (`REFRESH MATERIALIZED VIEW CONCURRENTLY` throttled to ≤ 1/min) — Phase 07+ emit `student.created` etc.
- `services/read_only_service.py`: platform or tenant read-only windows (`read_only_modes`), cached in Redis (`ro:platform`, `ro:{institution_id}`), consulted by the middleware.
- `services/help_service.py`, `services/feedback_service.py`.
- `core/ws.py`: `WebSocketHub` with Redis pub/sub (`aioredis.pubsub`), channels `notifications:{user}`, `jobs:{user}`, `fleet:{institution}`, `exam-board:{session}`; auth via `?token=` (access JWT); heartbeat 30 s; per-connection channel allow-list from principal.
- `core/logging.py`: structlog JSON with `request_id`, `institution_id`, `user_id`; Sentry init when `SENTRY_DSN`.
- `tasks/outbox.py`: `relay` (every 5 s) with `FOR UPDATE SKIP LOCKED`, exponential backoff (`next_attempt_at = now + 2^attempts min`), dead-letter after 10 attempts; `tasks/beat.py` registers: `outbox.relay` (5 s), `jobs.cleanup` (daily 03:00), `read_only.expire` (1 min), `integrations.health` (15 min), `partitions.ensure_next_month` (monthly; creates next-month partitions for `domain_events`, `webhook_deliveries`, `audit_logs`, `message_logs`, `student_class_attendance`, `vehicle_gps_logs`).

## 01.7 Events / jobs
- Emits: `platform.read_only_changed`, `job.finished`.
- Consumers registered: `search.reindex` ← (`*.created|updated|deleted` for students/staff/courses/applicants, wired by later phases), `webhooks.deliver` ← all events for institutions with active webhooks (Phase 41 completes delivery; here the consumer records `webhook_deliveries` rows).

## 01.8 Endpoints
```
GET    /health · /ready · /metrics                                    → infra (public, no envelope)
GET    /api/v1/public/config                                          → platform config for clients: pack lists (categories, quotas), theme names, captcha provider, min app versions {public}
GET    /api/v1/jobs                                                   → my jobs (or all with jobs:view_all) [jobs:view]
GET    /api/v1/jobs/{id}                                              → job status [jobs:view]
POST   /api/v1/jobs/{id}/cancel                                       → request cancel [jobs:cancel]
GET    /api/v1/search?q=&types=                                       → global search (visibility-aware) [dashboard:view] {search.global}
GET    /api/v1/help/articles?module=                                  → help centre [dashboard:view] {platform.help_center}
POST   /api/v1/feedback                                               → in-app feedback [dashboard:view] {platform.in_app_feedback}
GET    /api/v1/platform/read-only                                     → current read-only state (public)
POST   /api/v1/platform/read-only                                     → set platform/tenant read-only window [settings:manage] (tenant) / super admin (platform) {platform.read_only_mode}
POST   /api/v1/mobile/config                                          → min_version, force_update, maintenance banner, feature hints (public)
WS     /ws?token=                                                     → hub (channels by principal)
```
Auth dependencies for `[jobs:*]` arrive in Phase 02; until then routes are wired with the dependencies and verified after Phase 02 (Phase 01's own verification uses `/health`, `/ready`, `/public/config`, `/platform/read-only`, WS handshake rejection without token).

## 01.9 Frontend
- `App.tsx` provider tree: QueryClientProvider → Router → ThemeProvider → I18n → Toaster; `routes/index.tsx` with lazy pages and the guard chain from PREREQUISITE §4.4.
- `components/layout/AppLayout` with `Sidebar` (data-driven `NAV_GROUPS`, permission+feature filtered, collapsible groups), `Navbar` (institution/college switcher — visible when the principal has >1 scope or is super admin; academic year/term selector fed by `/academic-years` from Phase 03 — render a placeholder until then; global search `Ctrl+K` → `/search`; `JobsTray` (WebSocket `jobs:{user}` + fallback polling `/jobs`); `NotificationCenter` bell placeholder; impersonation banner; read-only banner from `sessionStore.readOnly`).
- Pages: `/dashboard` placeholder with `StatCard` grid, `/jobs` (DataTable: type, status, progress, result link, cancel), `/help` (article list/detail), `/access-denied`, `/not-found`, `/feature-disabled`.
- `lib/ws.ts`: single WebSocket client with reconnect (2 s → 30 s), channel subscriptions, dispatch to stores.
- `components/shared/DataTable` complete (server pagination/sort/filter/columns/export button calling a job); `ScopeTabs`; `FormField` wrappers; `MoneyInput`; `DateField`.
- Theme system + 5 themes + table styles; `tokens.json` export.

## 01.10 Mobile
None in this phase (skeleton only). `core/network/dio_client.dart` may be wired against `/health` and `/mobile/config`.

## 01.11 API verification — `scripts/verify/01_platform.ps1`
1. `GET /health` → 200 `{status:"ok"}`; `GET /ready` → 200.
2. `GET /api/v1/public/config` → 200 envelope `{success:true, data:{packs:{IN:{categories:[…]}}, themes:[5], min_app_versions:{…}}}`.
3. `GET /api/v1/platform/read-only` → `{data:{platform:false}}`; set `READ_ONLY_MODE=true` env (or POST as super admin after Phase 02) → `POST /api/v1/feedback` → 503 `READ_ONLY`; revert.
4. `alembic upgrade head` on empty DB → `SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'` = 411; `alembic heads` prints one head; `python scripts/check_schema_drift.py --phase 01` → 0 diffs.
5. Outbox: insert a `domain_events` row manually (`event_type='test.ping'`) → within 10 s `status='dispatched'` (consumer `test.ping` logs it) and one `event_consumptions` row; insert with a failing consumer → `attempts` increments and `next_attempt_at` set.
6. WebSocket: connect to `/ws` without token → close code 4401; with a forged token → 4401.
7. Jobs: call the internal `POST /api/v1/_dev/jobs/sleep?seconds=5` (dev-only route registered when `APP_ENV=development`) → job row `queued→running→succeeded`, progress events received on `jobs:{user}` (use `wscat` with a dev token minted by `scripts/dev_token.py`).
8. File service: `python scripts/verify/file_service_check.py` uploads a PNG and a renamed `.exe` → PNG stored under `{institution}/…`, `.exe` rejected (`VALIDATION`), signed URL works and expires.
9. Partitions: `SELECT count(*) FROM pg_inherits WHERE inhparent='domain_events'::regclass` ≥ 2 after running `beat.partitions.ensure_next_month`.

## 01.12 UI verification
1. `npm run dev` → `/dashboard` renders inside `AppLayout` with sidebar groups (only MAIN populated), navbar with placeholders, theme toggle works, table style switch persists.
2. `/jobs` lists jobs and updates live when the dev sleep job runs (progress bar → 100 %).
3. Read-only banner appears when `GET /platform/read-only` returns true; write buttons disabled.
4. `Ctrl+K` opens the command palette; search returns "no results" gracefully (no data yet).
5. `/help` renders platform articles; feedback widget submits and toasts.
6. Access-denied / feature-disabled / not-found pages render with a back link.

## 01.13 Deliverables checklist
- [ ] `0001_phase01_initial_schema.py` + `sql_loader.py`; `alembic upgrade head` from empty DB = 411 tables; single head
- [ ] Platform models (44) matching the SQL; `check_schema_drift.py --phase 01` = 0
- [ ] Job service + `@job` decorator + tray channel; file service (local/S3, signed URLs, quota); search service; read-only mode; WebSocket hub on Redis pub/sub; JSON logging + Sentry; outbox relay + Beat catalogue; partition maintenance
- [ ] Endpoints in 01.8 with envelope; `PUBLIC_ROUTES` registered; `check_authz_coverage.py` passes (routes carry dependencies even though auth lands in Phase 02)
- [ ] Web shell: layout, sidebar, navbar, jobs tray, notification center placeholder, command palette, DataTable, ScopeTabs, form wrappers, theme system
- [ ] `scripts/verify/01_platform.ps1` passes; UI checklist done; commit `feat(phase-01): infrastructure & platform services`
