# SeptronUniverse — Technical Architecture (platform building blocks)

Same stack and layering as SeptronOrbit (FastAPI async · SQLAlchemy 2 async + Alembic · PostgreSQL 15 · Redis 7 · Celery 5 | React 18 + TS + Vite · Zustand · TanStack Query · Tailwind/Radix | Flutter). This document specifies the platform building blocks that are **new or hardened** relative to Orbit and that every phase prompt relies on. Diagrams: `Architecture.md`. Decisions: `docs/ADR/`.

## 1. Request pipeline

```
Nginx/Traefik → GZip → CORS → RequestLogger (request_id, tenant, user) → InstitutionContext (X-Institution-*, X-College-Id, RLS SET LOCAL)
→ ReadOnlyMode gate → Auth (JWT, session check) → feature_required → permission_required → scope → route → service → repository (visible_to) → DB
→ envelope ok() | APIError(code) ; AuditMiddleware fallback ; domain events flushed with the transaction (outbox)
```

- **Envelope**: `{success, data, message, meta:{visibility, pagination:{page,page_size,total,total_pages}, pii}}`; `ok()` runs `jsonable_encoder`; errors `{success:false, error:{code, message, details}}` with codes from the catalogue (`VALIDATION`, `PERMISSION_DENIED`, `FEATURE_DISABLED`, `NOT_FOUND`, `CONFLICT`, `STALE_VERSION`, `READ_ONLY`, `RATE_LIMITED`, `IDEMPOTENT_REPLAY`, `HOLD_BLOCKED`, `RECORD_LOCKED`, `INTEGRATION_FAILED`).
- **API conventions**: `page/page_size ≤ 200`, `sort=-field`, `filter[field][op]=value`, `include=` expansions, `fields=` sparse, `/bulk` with partial-success reports, downloads via job → signed URL, `Idempotency-Key` on non-idempotent POSTs, `ETag`/`If-Match` on masters.
- Global exception handler always attaches CORS headers (Orbit lesson).

## 2. Tenancy & isolation

- `institutions` (tenant) → `colleges` → `faculties` → `departments`. Every tenant table has `institution_id`; academic tables also `college_id`.
- **PostgreSQL RLS**: `ALTER TABLE … ENABLE ROW LEVEL SECURITY; CREATE POLICY tenant_isolation USING (institution_id = current_setting('app.institution_id')::uuid)`; the app role is not `BYPASSRLS`; `InstitutionContextMiddleware` issues `SET LOCAL app.institution_id` on the request transaction; Celery tasks set it explicitly; super-admin cross-tenant queries use a dedicated `platform` role with explicit audit.
- `BaseRepository` still filters `institution_id` (belt and braces) + scope + `deleted_at IS NULL` + `visible_to(user, module)`.
- Institution **timezone/locale/currency** on the tenant; UTC in DB; academic `DATE`s in institution TZ; `Fmt` helpers on all clients.
- Per-tenant file prefixes (`{institution_id}/…`), plan quotas, signed URLs (time-limited), MIME sniffing, size limits, optional ClamAV, thumbnails, retention.

## 3. Authorization
See `docs/Authorization_and_Visibility.md` (feature → permission → scope → visibility resolver → field masking → record-state rules → impersonation).

## 4. Domain events & outbox

- Services call `events.emit("result.published", payload)` inside the DB transaction → row in `domain_events(id, institution_id, type, payload, created_at, status, attempts, next_attempt_at)`.
- **Relay** (Beat every 5 s + `LISTEN/NOTIFY` wake-up) moves pending events to Celery topics; consumers: notifications dispatcher, webhooks, search indexer, metric cache invalidation, ABC/DigiLocker push, analytics read models, feature-flag cache invalidation.
- At-least-once delivery; consumers are idempotent (`event_id` dedupe table). Dead-letter after N attempts with admin retry UI (`/admin/jobs/dead-letters`).
- `domain_events` partitioned monthly; retention 90 days (payload archived to S3).

## 5. Idempotency, concurrency, sequences

- `Idempotency-Key` header on POST for payments, registrations, marks submit, attendance bulk, imports: stored in Redis (24 h) + `idempotency_keys` table (key, user, route, request_hash, response, status); replay returns the stored response (`IDEMPOTENT_REPLAY`).
- Optimistic locking: `version` column on editable masters; `If-Match`/body `version` → `409 STALE_VERSION`.
- Pessimistic locks where money/seats move: `SELECT … FOR UPDATE` on `course_offerings`, `fee_invoices`, `seat_matrix`, `hostel_beds`.
- `number_sequences` atomic `UPDATE … SET next_value = next_value + 1 RETURNING` with pattern rendering.

## 6. Workflow engine (approvals)

```
workflow_definitions ( institution_id, module, key "leave.approval", name, steps JSONB [{order, approver:{role|scope_rule|user}, mode:sequential|parallel, sla_hours, escalate_to}], is_active, version )
workflow_instances ( definition_id, entity_type, entity_id, status (pending|approved|rejected|cancelled|escalated), current_step, started_by, started_at, closed_at )
workflow_steps ( instance_id, order, approver_user_id (resolved), status, acted_by, acted_at, comment, sla_due_at )
workflow_delegations ( from_user_id, to_user_id, module NULL, from_on, to_on )
```
- Modules register **hooks** (`on_approved`, `on_rejected`) so side-effects stay in module code; the engine only routes and records.
- Shipped definitions: leave approval, condonation, marks change, registration advisor approval, indent/PO, receipt cancellation, refund, certificate request, transcript, regulation approval, affiliation application, grievance escalation, event approval, room booking, scholarship sanction, CAS/appraisal, PhD requests, no-dues.
- Inbox endpoint `GET /workflow/inbox` (all pending for the user, with delegation); SLA escalation by Beat; audit on every action.

## 7. Background jobs

`background_jobs(id, institution_id, type, params, status (queued|running|succeeded|failed|cancelled), progress_pct, message, result_url, error, requested_by, started_at, finished_at)`; Celery task wrapper `@job("hall_tickets.generate")` updates progress; cancellation flag checked between chunks; WebSocket channel `jobs:{user}` streams progress; jobs tray in web navbar and mobile. All bulk PDFs, imports/exports, result runs, allocation runs, metric computes, elective allocations, migration applies run as jobs.

## 8. Celery topology

| Queue | Work |
|---|---|
| notifications | dispatch/deliver messages |
| emails | email sends |
| documents | bulk PDFs (hall tickets, grade cards, certificates) |
| reports | report/export generation |
| integrations | adapter calls with rate limits (payments webhooks excluded — synchronous) |
| scheduled | Beat jobs |
Beat catalogue: outbox relay, late-fee posting, fee reminders, attendance warnings (3 checkpoints), eligibility recompute, result-publish notifications, ABC/DigiLocker retries, metric refresh, SLA escalations, hostel late-return, leave accrual, library overdue, subscription reminders, backups, archival, demo reset, health checks, feature-flag cache refresh. Every task receives `institution_id`, sets RLS context, checks feature flags, is idempotent.

## 9. Realtime
WebSocket endpoint `/ws` with token auth; Redis pub/sub fan-out (multi-worker safe); channels: `notifications:{user}`, `jobs:{user}`, `fleet:{institution}`, `exam-board:{session}` (COE status), `dashboard:{institution}` (optional). Fallback polling for degraded networks.

## 10. Search
`search_documents` materialized view (entity_type, entity_id, institution_id, college_id, title, subtitle, tsvector, visibility_scope) refreshed by outbox consumer; `GET /search?q=` applies visibility rules; web command palette (`Ctrl+K`), mobile search field.

## 11. Security

| Control | Design |
|---|---|
| Auth | JWT HS256 → RS256 with `kid` rotation; access 15 min (memory), refresh 7 d httpOnly cookie with rotation & reuse detection; JTI blacklist; login lockout; OTP rate limits; captcha on public forms |
| MFA | TOTP (RFC 6238) mandatory for super_admin, COE, exam_decoder, registrar, institution_admin (configurable); recovery codes |
| Sessions | `user_sessions` (device, ip, last_seen); revoke one/all; login history |
| IP allow-lists | per institution for `exams:decode`, `results:publish`, `features:*` |
| API keys / webhooks | scoped keys, hashed at rest, rate limits; HMAC-signed webhooks |
| PII | encrypted columns (pgcrypto/app-level AES-GCM), masking by default, `view_pii`, PII-free logs, screenshot block on mobile valuation screens |
| Audit | `audit_logs` partitioned monthly, hash-chained (`prev_hash`, `hash`), `verify_chain` endpoint; super-admin action audit; impersonation audit |
| Headers | HSTS, CSP, X-Frame-Options, Referrer-Policy; CORS per environment |
| Supply chain | pip-audit, npm audit, semgrep/bandit, trivy, gitleaks, SBOM in CI |
| Privacy | DPDP consent records, DSR workflows, retention policies, tenant export/erasure |
| Secrets | env/vault only; never in repo or `.claude/settings.local.json` |

## 12. Data lifecycle & operations

- Partitioning: `audit_logs`, `student_class_attendance`, `message_logs`, `domain_events`, `webhook_deliveries` (monthly/term).
- Materialized read models for dashboards/analytics refreshed by Beat; invalidated by events.
- Scripts: `rollover_academic_year.py` (creates next year/terms, batches promote), `close_term.py` (locks term, snapshots), `archive_year.py` (moves cold partitions to archive schema/S3), `seed_demo_institution.py --type university|autonomous|affiliated`.
- Backups: nightly `pg_dump` per tenant + WAL archiving (PITR), S3 versioning for uploads; quarterly restore drills; DR targets RPO 15 min / RTO 4 h.
- Migrations: expand/contract discipline (no destructive DDL in the same release as code that stops using it); lint in CI; backend container owns `alembic upgrade head`; workers `RUN_MIGRATIONS=0`.
- Read-only/maintenance mode: platform or per tenant; writes → `503 READ_ONLY`; banner on all clients.
- Environments: dev / demo (nightly reset) / prod on `orbit-infra` (`compose/apps/universe-*.yml`); feature-flag defaults per environment.

## 13. Observability
Prometheus (`prometheus-fastapi-instrumentator`, Celery exporter), Sentry (backend/web/mobile), structured JSON logs with `request_id`, `institution_id`, `user_id`, `job_id`; Flower; uptime checks; alert rules (error rate, queue depth, outbox lag, DB connections, disk); per-tenant rate limits; adapter circuit breakers.

## 14. Frontend architecture
- `src/features/<module>/{api,hooks,pages,components,types}`; shared `components/{ui,shared,layout,charts}`; `store/{authStore,sessionStore,notificationStore}`; `lib/{queryClient,push,captcha,payments,seo}`.
- Generated API types (`openapi-typescript`) → thin `api/*.ts` wrappers; RHF + Zod on every form; `DataTable` server-side (pagination/sort/filter/columns/export); virtualized keyboard-first grids (marks, attendance); `useVisibility` tabs; `useFeature`/`usePermission` guards; jobs tray; notification center; command palette; print stylesheets; WCAG AA (axe in Playwright); route-level code splitting with bundle budgets.
- Guards: `PrivateRoute → SuperAdminRoute | AdminShellRoute(FeatureRoute(PermissionRoute(page))) | PortalRoute`.

## 15. Mobile architecture
See `docs/Mobile_App_UI_Structure.md`.

## 16. Developer workflow
- `scripts/scaffold_module.py <module>` generates model/schema/repository/service/router/feature-key/permission entries/TS api/hooks/page/nav/mobile screen stubs following the conventions.
- Lint/format/type-check (ruff, black, mypy, eslint, prettier, dart analyze), `import-linter` contracts, pre-commit, conventional commits, ADRs in `docs/ADR/`.
- **Verification is functional**: per-phase API scripts (PowerShell/httpx per role) + UI functional checks (Playwright suites per round, manual per-role sweeps). Structural CI guards: schema drift, authz/feature audit, single Alembic head, feature registry check, supply-chain scans. No unit-test suites are required.

## 17. Non-functional targets
100 institutions; ≤ 50 000 active students & 5 000 staff per institution; 200 colleges per university tenant; list p95 < 300 ms; detail p95 < 150 ms; registration rush 5 000 concurrent students; result publish 20 000 rows/min; hall-ticket bulk 10 000 PDFs < 15 min; result run 10 000 × 8 courses < 10 min; availability 99.5 %; LCP < 2.5 s; mobile cold start < 2 s; OWASP ASVS L2; VAPT before launch.
