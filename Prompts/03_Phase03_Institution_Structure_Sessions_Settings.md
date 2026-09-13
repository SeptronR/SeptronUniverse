# PHASE 03 — INSTITUTION STRUCTURE, ACADEMIC SESSIONS & SETTINGS

## Pre-Requisite
Phases 01–02 complete (platform, auth, RBAC, features, visibility).

## Objective
The organisational and calendar backbone every module hangs off: institution profile (type, regulatory pack, timezone/locale/currency, statutory ids, branding), colleges/campuses/study centres, faculties, departments (HOD), academic years and terms with their status machine and rollover/close procedures, holidays, number sequences, settings key/value by category with theme inheritance (platform → institution → user), provider test buttons, and the onboarding wizard for a new institution (seed roles, permissions, pack defaults, demo data).

## Feature keys
`institution.multi_college` (off; university tier), `institution.faculties` (off; standard), `institution.holidays` (on), `institution.themes` (on), `institution.number_sequences_custom` (on; standard), `academics.regulations`? — no (Phase 05). Core `core.institution`, `core.settings` gate the base routes.

## Visibility rules
Institution/colleges/faculties/departments/years/terms/holidays are **institution-wide readable** by any authenticated user of the institution (`institutions:view` granted to all roles), college-scoped users see their college first (default filter) but may read all colleges; edit requires `institutions:manage`/`colleges:manage` (institution_admin, registrar) — `college_admin` may edit only their college (`@college` scope). Settings: read for admins; `settings:manage` to write; public settings exposed via `/public/config`.

## 03.1 Database tables
Section 2 (`institutions, institution_profile, colleges, faculties, departments, institution_settings, holidays, number_sequences`) and section 7 (`academic_years, academic_terms`) already exist. Expected delta migration: none.

## 03.2 Alembic migration
`0003_phase03_settings_seed.py` — data-only: default `institution_settings` categories/keys template (see 03.6 table) stored in `platform_settings['settings_template']`; default theme tokens; default `number_sequences` patterns template.

## 03.3 Models
`models/platform.py` (already) + `models/academic.py`: `AcademicYear`, `AcademicTerm` (mixins `TenantModelMixin`, `CollegeScopedMixin`). Enums: `InstitutionType`, `CollegeType`, `DepartmentType`, `TermType`, `TermStatus`.

## 03.4 Schemas — `app/schemas/institution.py`, `academic_sessions.py`, `settings.py`
`InstitutionProfileResponse/Update` (name, short_name, type, pack, timezone, locale, currency, statutory ids, address, contact, logo, website, head signature/seal urls), `CollegeCreate/Update/Response` (type, affiliation number, principal, exam centre flags, statutory ids), `FacultyCreate/Response`, `DepartmentCreate/Update/Response` (faculty, HOD, type), `AcademicYearCreate/Update/Response` (+ `is_current`, `is_locked`), `AcademicTermCreate/Update/Response` (dates, registration window, add-drop end, last instruction date, status), `TermStatusChange{status}`, `RolloverRequest{new_year_name, start_date, end_date, terms:[…], promote_batches: bool}`, `HolidayCreate/Response` + `HolidayBulkImport`, `NumberSequenceCreate/Update/Response{scope_key, pattern, next_value, padding, reset_policy}` + `NumberSequencePreview`, `SettingResponse{category, key, value, value_type, is_public}`, `SettingsBulkUpdate{items:[…]}`, `SettingsCategoryResponse`, `ProviderTestRequest{channel, to}`, `OnboardingRequest{institution: …, admin: …, plan_code, pack, seed_demo: bool}`.

## 03.5 Repository
`institution_repository.py` (profile, settings with `(institution_id, college_id, category, key)` upsert, public settings), `college_repository.py` (`module="colleges"`), `department_repository.py` (`module="departments"`, scope columns institution/college/faculty), `academic_session_repository.py` (years/terms; `get_current_term(college_id)`; overlapping-date check), `holiday_repository.py`, `sequence_repository.py` (`next_value(scope_key, college_id)` with `UPDATE … RETURNING` inside the caller's transaction; `render(pattern, context)` supports `{yy}`, `{yyyy}`, `{college_code}`, `{prog_code}`, `{term}`, `{seq:N}`).

## 03.6 Services
- `institution_service.py`
  1. `get_profile / update_profile` (audit diff; logo upload via file service; changing `timezone` is allowed only when no term is `in_progress`).
  2. `onboard(request)` (super admin): create institution (+ auto `colleges.is_main` when type ≠ university), `institution_profile`, `seed_institution_roles`, `seed_institution_defaults(pack)` (categories, grading scales, assessment schemes, frameworks, templates, settings template, number sequences), plan subscription + feature defaults (`feature_service.apply_plan_defaults`), first `institution_admin` user (credential email), optional demo seed job; emits `institution.created`.
  3. Settings: `get(category)`, `bulk_update(items)` with type validation per key (schema below), `public()`; Redis cache `settings:{institution}:{category}` invalidated on write; theme resolution order user → institution → platform.
  4. Provider tests: `test_channel(channel, to)` → adapter (mock/live) send + `message_logs` row.
- `college_service.py`: CRUD (code unique per institution; `is_main` exactly one per non-university institution; `study_centre` allowed only for `programs.mode ∈ distance/online` later); college-scoped admin restrictions; emits `college.created`.
- `department_service.py`: CRUD, HOD assignment (must be staff of the college; assigning also grants the `hod` role scoped to the department via `rbac_service.assign_role`), faculties (dean assignment likewise grants `dean` @faculty).
- `academic_session_service.py`
  1. Year CRUD; exactly one `is_current` per (institution, college) (partial unique index); `lock` prevents edits to registrations/attendance/results of that year.
  2. Term CRUD; sequence unique; dates within year; `registration_start ≤ registration_end ≤ add_drop_end ≤ last_instruction_date ≤ end_date`.
  3. Term status machine `planned → registration → in_progress → exam → result_processing → closed` (only forward; `closed` requires all offerings `completed`/`cancelled` (Phase 09) and results published (Phase 15) — checks are pluggable `TermCloseChecks` registry).
  4. `rollover(request)`: creates next year + terms, sets current, optionally promotes batches (Phase 05/07 hook `on_rollover`), emits `academic_year.rolled_over`.
  5. `set_current_term(term)` → emits `academic_term.changed` (clients refresh selectors).
- `holiday_service.py`: CRUD, bulk import CSV (`name,date,end_date,type,applies_to`), iCal export, `is_holiday(date, college_id, applies_to)` helper used by timetable/attendance.
- `sequence_service.py`: CRUD, preview, `next(scope_key)` (atomic), yearly/term reset policy applied by Beat `sequences.reset` at year start.

Settings template (category → keys, type, default; institution admins edit in the Settings page):

| Category | Keys |
|---|---|
| general | institution_display_name (str), academic_calendar_locale (str), date_format (str, dd/MM/yyyy), first_day_of_week (int), theme (str, indigo), table_style (str, minimal), logo_dark_url (str) |
| security | mfa_required_roles (list), session_timeout_minutes (int, 480), password_min_length (int, 10), ip_allowlist_enforced (bool), sso_role_map (json) |
| academics | attendance_min_pct_default (int, 75), credit_limits_enforced (bool), allow_arrear_with_regular (bool), catalog_public (bool) |
| admissions | application_fee_default_paise (int), auto_admit_on_fee (bool), reservation_policy (json) |
| fees | receipt_prefix (str), late_fee_grace_days (int), gateway_provider (str), upi_vpa (str), gst_enabled (bool) |
| exams | valuation_mode_default (single/double), discrepancy_pct_default (int, 15), hall_ticket_requires_no_dues (bool), result_public_lookup (bool) |
| hostel | guardian_otp_required_for_home_leave (bool), late_return_grace_minutes (int) |
| communication | sms_sender_id (str), dlt_entity_id (str), whatsapp_number (str), quiet_hours (json), digest_default (str) |
| integrations | provider overrides (json per capability; secrets in `integration_connections` only) |
| privacy | retention_days_logs (int, 365), consent_texts_version (str) |

## 03.7 Events / jobs
Emits: `institution.created`, `institution.updated`, `college.created/updated`, `department.updated`, `academic_year.created/rolled_over`, `academic_term.changed/status_changed`, `holiday.changed`, `settings.changed`. Consumers: `features.invalidate_cache`, `settings.invalidate_cache`, `search.reindex` (departments). Beat: `sequences.reset` (daily 00:05), `terms.auto_status` (daily: `planned→registration` on `registration_start`, `registration→in_progress` on `start_date` if setting `terms.auto_advance=true`). Workflow: none.

## 03.8 Endpoints
```
GET/PUT  /api/v1/institution/profile                         → profile [institutions:view|manage] {core.institution}
POST     /api/v1/institution/profile/logo                     → upload [institutions:manage]
GET/POST /api/v1/colleges · GET/PUT/DELETE /colleges/{id}     → [colleges:view|create|update|delete] {institution.multi_college for >1}
GET/POST /api/v1/faculties · PUT/DELETE /faculties/{id}       → [departments:manage] {institution.faculties}
GET/POST /api/v1/departments · GET/PUT/DELETE /departments/{id} · PUT /departments/{id}/hod → [departments:view|manage]
GET/POST /api/v1/academic-years · PUT /academic-years/{id} · POST /academic-years/{id}/set-current · /lock · /unlock [sessions:view|manage|lock]
POST     /api/v1/academic-years/rollover                      → next year + terms (+ promote) [sessions:rollover]
GET/POST /api/v1/academic-terms · PUT /academic-terms/{id} · POST /academic-terms/{id}/status · /set-current [sessions:view|manage|close]
GET      /api/v1/academic-terms/current?college_id=           → current term [auth]
GET/POST /api/v1/holidays · PUT/DELETE /holidays/{id} · POST /holidays/bulk-import · GET /holidays/export.ics [institutions:view|manage] {institution.holidays}
GET/POST /api/v1/number-sequences · PUT /number-sequences/{id} · POST /number-sequences/{id}/preview [settings:manage] {institution.number_sequences_custom}
GET      /api/v1/settings?category= · PUT /settings           → bulk update [settings:view|manage] {core.settings}
GET      /api/v1/settings/public                              → public keys {public}
POST     /api/v1/settings/test-provider                       → send test SMS/email/WhatsApp [settings:manage]
POST     /api/v1/platform/institutions                        → onboarding wizard (super admin) [institutions:create]
GET      /api/v1/platform/institutions · GET/PUT /platform/institutions/{id} · POST /platform/institutions/{id}/suspend|activate [institutions:manage] (super admin)
```

## 03.9 Frontend
- `/admin/institution` (profile form with logo, statutory ids, branding preview), `/admin/colleges` (table + drawer; type badges; principal picker; exam-centre flag), `/admin/departments` (tree by faculty; HOD picker; department type), `/admin/academic-years` (years with terms timeline; set current; lock; **Rollover wizard**: new year → terms template → promote batches toggle → summary), `/admin/academic-terms/:id` (dates, windows, status stepper with blocking checks list), `/admin/holidays` (calendar + table, bulk import, iCal), `/admin/settings` (tabbed by category with typed inputs, theme & table-style pickers with live preview, provider test buttons), `/admin/number-sequences` (pattern editor with preview), `/super-admin/institutions` (list, onboarding wizard: institution → admin → plan → pack → demo data → done), `/super-admin/institutions/:id` (profile, subscription, features tab from Phase 02, suspend).
- Navbar: **Institution/College switcher** now live (colleges from `/colleges`); **Year/Term selector** from `/academic-years` + `/academic-terms`; `sessionStore` persists selections and clears query cache on change.
- Nav: ADMIN group gets Institution, Colleges, Departments, Academic Years, Holidays, Settings, Number Sequences.

## 03.10 Mobile
`core/session`: institution/college picker (multi-scope users), current term chip; `features/settings`: language/theme; no admin editing on mobile in this phase.

## 03.11 API verification — `scripts/verify/03_institution.ps1`
Roles: `superadmin`, `inst.admin`, `registrar`, `college.admin.b`, `student.1`.
1. `GET /institution/profile` as `student.1` → 200 (read-all); `PUT` → 403.
2. `PUT /institution/profile` as `inst.admin` with `timezone=Asia/Kolkata`, statutory ids → 200; audit row with old/new diff.
3. Colleges: `POST /colleges` (code `C`) as `inst.admin` → 201; duplicate code → 409 `CONFLICT`; `college.admin.b` `PUT /colleges/{A}` → 404 (invisible), `PUT /colleges/{B}` → 200.
4. Departments: create `ECE` under college A; `PUT /departments/{ECE}/hod {staff_id: faculty.1}` → 200 and `GET /users/{faculty.1}/roles` shows `hod@department:ECE`.
5. Years/terms: create `2026-27` with terms Odd/Even; second `set-current` on the same college flips the previous; overlapping term dates → 422; `POST /academic-terms/{odd}/status {status:"in_progress"}` from `planned` → 409 (must pass through `registration`); `registration` → 200.
6. `GET /academic-terms/current` as student → the current term.
7. Rollover: `POST /academic-years/rollover` → new year + 2 terms, current switched, event `academic_year.rolled_over` dispatched.
8. Holidays: bulk import CSV with 5 rows (one invalid date) → `{succeeded:4, failed:[{index:3, code:"VALIDATION"}]}`; `GET /holidays/export.ics` → valid iCal.
9. Sequences: create `regno:{yyyy}:{college_code}` pattern `{college_code}{yy}{seq:4}`; preview → `A260001`; call `next` twice via dev route → `A260001`, `A260002`; concurrent 50 calls (PowerShell jobs) → 50 distinct values.
10. Settings: `PUT /settings` with `exams.discrepancy_pct_default = "abc"` → 422; with `15` → 200; `GET /settings/public` (unauthenticated) exposes only `is_public` keys.
11. `POST /settings/test-provider {channel:"sms", to:"+911234567890"}` → 202 and a `message_logs` row with provider `mock`.
12. Onboarding: super admin `POST /platform/institutions` (type `autonomous_college`, pack IN, plan standard, seed_demo=false) → 201; new institution has 1 main college, 50 roles, permissions, pack grading scale/assessment scheme/frameworks, feature flags per plan; admin credential email logged.
13. Suspend: `POST /platform/institutions/{new}/suspend` → its users' login → 403.

## 03.12 UI verification
1. Institution profile edits save with toast and audit entry visible under `/admin/audit-logs` (Phase 37 page; verify via API now).
2. Colleges/departments pages: create, edit, HOD assign; college switcher lists the new college; switching clears cached lists.
3. Academic years: rollover wizard end-to-end; term status stepper shows blocking reasons; year lock disables edits.
4. Holidays calendar shows imported rows; iCal download works.
5. Settings tabs: typed inputs, validation messages, theme picker live preview, table-style switch, provider test buttons show result toast.
6. Super-admin onboarding wizard creates an institution and lands on its detail page with Features tab.
7. Navbar year/term selector persists across reloads and updates the dashboard placeholder.

## 03.13 Deliverables checklist
- [ ] Institution profile/onboarding, colleges, faculties, departments (+HOD/dean role grants), academic years/terms with status machine and rollover, holidays (bulk/iCal), number sequences (atomic), settings with typed template + cache + public keys, provider tests
- [ ] Events + Beat jobs in 03.7; `seed_institution_defaults(pack)` implemented for IN and GENERIC
- [ ] Web pages + navbar switchers; mobile pickers
- [ ] `scripts/verify/03_institution.ps1` passes; UI checklist done; drift/authz/feature guards green; commit `feat(phase-03): institution structure, sessions, settings`
