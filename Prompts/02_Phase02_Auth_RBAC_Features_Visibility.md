# PHASE 02 — AUTH, RBAC, FEATURE FLAGS, VISIBILITY & ENTITLEMENTS

## Pre-Requisite
Phase 01 complete (schema applied, platform models, jobs/outbox/WS/file service, web shell).

## Objective
Everything that decides *who may do what and see which rows*: login (password, OTP, SSO hook), refresh-token rotation with reuse detection, JTI blacklist, lockout, MFA (TOTP) for privileged roles, session management, login history, password policy, IP allow-lists for exam operations; roles and the permission matrix with **scopes**; the **feature-flag registry** with per-institution flags and the super-admin Features tab; the **visibility resolver** with ownership links; PII masking; time-boxed accounts (external examiner, auditor, applicant); credential sheets; subscription entitlements (seat/storage/SMS limits, grace); impersonation with banner and audit. Also the `/install` bootstrap and `seed_platform.py`.

## Feature keys
`security.mfa` (on, starter), `security.session_management` (on), `security.ip_allowlist_exam_ops` (off, professional), `security.sso` (off, professional; depends `integrations.sso`), `privacy.dpdp_consent` (on), `privacy.data_subject_requests` (on, standard). Core keys are already registered.

## Visibility rules
- `users`: `users:view_all` @scope for institution_admin/hr_officer/registrar; everyone sees self (`/auth/me`).
- `roles`: institution-wide read for admins; `roles:manage` to edit.
- `user_sessions`, `login_history`, `mfa_secrets`: **self only**; `security_officer`/institution_admin with `users:view_all` see sessions (masked IPs) for support.
- `institution_feature_flags`: super admin (platform), institution_admin read + `features:institution_toggle`.
- `consent_records`, `data_subject_requests`: self; `privacy` officer role (`settings:manage`) sees all.

## 02.1 Database tables
Already created in Phase 01 (sections 3–5): `users, password_reset_tokens, user_sessions, mfa_secrets, login_history, ip_allowlists, device_tokens, credential_sheets, permissions, roles, role_permissions, user_roles, platform_features, institution_feature_flags, feature_flag_changes, consent_records, data_subject_requests, impersonation_logs (§32), subscription_plans, institution_subscriptions, usage_meters (§32)`. Verify they exist; expected delta migration: none.

## 02.2 Alembic migration
`0002_phase02_auth_seed.py` — data-only revision: upserts the permission catalogue from `app/core/rbac/registry.py` (module × action + bespoke), the 51 role templates, `platform_features` from `FEATURE_REGISTRY`, and default `subscription_plans.enabled_features` per tier (idempotent `ON CONFLICT DO NOTHING/UPDATE`). Schema delta: none.

## 02.3 Models
`app/models/platform.py` already has these; add `models/saas.py` for `SubscriptionPlan`, `InstitutionSubscription`, `UsageMeter`, `ImpersonationLog`. Enums (`app/enums/auth.py`): `UserType`, `ScopeType`, `LoginOutcome`, `SubscriptionStatus`.

## 02.4 Schemas — `app/schemas/auth.py`, `rbac.py`, `features.py`, `privacy.py`
`LoginRequest{identifier, password, mfa_code?}`, `LoginResponse{access_token, user: MeUser, institution: InstitutionSummary, permissions[], features[], scopes[], mfa_required?: bool, mfa_setup_required?: bool}`, `OtpSendRequest{phone|email}`, `OtpVerifyRequest`, `RefreshResponse{access_token}`, `ForgotPasswordRequest`, `ResetPasswordRequest{token, password}`, `ChangePasswordRequest`, `MfaSetupResponse{secret, otpauth_url, qr_png_base64}`, `MfaConfirmRequest{code}`, `MfaDisableRequest{password, code}`, `SessionResponse{id, device_label, platform, ip_masked, last_seen_at, current}`, `MeUser{id, institution_id, username, email, phone, display_name, avatar_url, user_type, is_super_admin, role_slugs[], scopes[{scope_type, scope_id, label}], mfa_enabled, must_change_password}`, `RoleCreate/Update/Response`, `PermissionResponse`, `RolePermissionMatrix{modules:[{module, actions:[{action, granted}]}]}`, `UserRoleAssign{role_id, scope_type, scope_id?, valid_from?, valid_to?}`, `UserCreate/Update/Response` (masked fields), `CredentialSheetRequest{audience, ids[]}`, `FeatureDefResponse`, `InstitutionFeatureFlagResponse{key, platform_enabled, institution_enabled, effective, source, config}`, `FeatureToggleRequest{enabled, reason?, config?}`, `ConsentRequest{purpose, granted}`, `DataSubjectRequestCreate`, `ImpersonateRequest{target_user_id, reason}`, `EntitlementsResponse{plan, status, limits, usage, grace_until}`.

## 02.5 Repository
`repositories/user_repository.py` (`module="users"`; `get_by_identifier` matches username/email/phone within institution or platform; `selectinload(User.roles)`), `role_repository.py`, `permission_repository.py`, `user_role_repository.py`, `session_repository.py`, `feature_flag_repository.py`, `consent_repository.py`, `subscription_repository.py`. Visibility registrations: `users` (self predicate `User.id == p.id`; scope columns institution/college via `user_roles`), `jobs` already done.

## 02.6 Services
- `services/auth_service.py`
  1. `login(identifier, password, mfa_code, request)`: find user (institution resolved from `X-Institution-Slug`/host or platform); check `is_active`, `valid_from/valid_to` (time-boxed accounts); lockout key `login_fail:{inst}:{identifier}` ≥ 5 in 15 min → `429 RATE_LIMITED`; bcrypt verify; if `mfa_enabled` or role requires MFA (`security.mfa` on and role in `MFA_REQUIRED_ROLES` = super_admin, controller_of_examinations, exam_decoder, registrar, institution_admin, accountant (configurable in settings)) → require `mfa_code` (`403 MFA_REQUIRED` with `mfa_setup_required` when not yet enrolled); create session row (`refresh_family`, `refresh_jti`), set httpOnly `refresh_token` cookie (`Path=/api/v1/auth/refresh`, `SameSite=Strict`, `Secure` in prod), return access token + principal payload; write `login_history`.
  2. `refresh(cookie)`: decode; lookup session by `refresh_jti`; if revoked/unknown but family known → **reuse detected** → revoke whole family, `401`; else rotate (new jti, same family), extend `expires_at`.
  3. `logout(all=False)`: revoke session (or family / all sessions), blacklist access JTI until expiry.
  4. OTP: `send_otp(phone|email)` → Redis `otp:{dest}` (6 digits, 5 min), rate `otp_rate:{dest}` 1/min, Celery `notifications.send_sms_otp`; `verify_otp` → same as login (no MFA step if OTP is the second factor by policy).
  5. Password flows: forgot (token sha256, 1 h, single-use, email via outbox), reset, change (policy: ≥ 10 chars, 3 of 4 classes, not in last 5 hashes — store `password_history` in `users.preferences`), `must_change_password` gate.
  6. MFA: `setup` (pyotp secret encrypted with `INTEGRATION_ENCRYPTION_KEY`, QR PNG), `confirm`, `disable` (password + code), recovery codes (10, hashed, single-use).
  7. Sessions: list (self), revoke one/all; `login_history` list (self; admins masked).
  8. `load_principal(db, user_id, request)`: user + roles (+ scopes, validity) + flat permissions (role→permission expanded; `module:manage` wildcard) + effective features (`features.effective_features`) + impersonator from `X-Impersonation` session if any.
  9. SSO hook: `GET /auth/sso/{provider}/start` and `/callback` use the `IdentityProvider` adapter (mock in this phase); JIT-link by verified email; role mapping from `institution_settings[security.sso_role_map]`.
  10. IP allow-list check dependency `ip_allowlisted("exam_decode")` used by Phase 15 routes; `security.ip_allowlist_exam_ops` flag.
- `services/rbac_service.py`: roles CRUD (system roles cannot be deleted/renamed), clone, permission matrix get/set (diff-audited), assign/revoke user roles with scope validation (scope_id must exist and belong to the institution; `college_admin` requires college scope; `hod` requires department scope …), `seed_institution_roles(institution)` from templates.
- `services/user_service.py`: user CRUD (admin), bulk credential sheets (job → PDF/XLSX with temporary passwords, `must_change_password=TRUE`), deactivate/reactivate, impersonation start/stop (`impersonation_logs`, session flag; every write audited with `impersonator_id`).
- `services/feature_service.py`: `list_definitions()`, `list_institution_flags(institution_id)` (registry ∪ flags → effective), `set_platform_flag(institution_id, key, enabled, reason, config)` (super admin; enabling auto-enables `depends_on` after client confirmation `confirm_dependencies=true`; disabling a key others depend on → `409 RULE_VIOLATION` listing dependants; core keys immutable), `set_institution_flag(key, enabled)` (institution admin; cannot exceed platform), `apply_plan_defaults(institution_id)`, `matrix()` (institutions × features); every change → `feature_flag_changes` + event `feature_flag.changed` (consumer invalidates Redis `features:{institution}`); `compute_effective_features`.
- `services/entitlement_service.py`: `require_active_subscription(principal)` (status `active|trial`; `grace` → read-only for writes with `402`-style `RULE_VIOLATION` code `SUBSCRIPTION_GRACE`; `expired` → 403), `enforce_seat_limit(kind="student"|"staff")` on create, `usage_meters` monthly job, renewal reminders (Beat) — used by later phases.
- `services/privacy_service.py`: consent record/withdraw; DSR create/track; export job (`data.export_portability` in Phase 41 completes).
- `services/install_service.py`: `POST /install` guarded by `INSTALL_SECRET_KEY` (one-time): runs `seed_platform`, creates super admin, marks installed in `platform_settings`.
- `core/authz/masking.py`: `mask_pii(payload, principal, module)` masks `aadhaar`, `pan`, `bank_details`, `salary`, `phone` (last 4), `email` (first 2 chars) unless `module:view_pii`; applied in response schemas via a `Masked[str]` annotated type.

## 02.7 Events / jobs
Emits: `user.created`, `user.deactivated`, `role.updated`, `user_role.assigned/revoked`, `feature_flag.changed`, `session.revoked`, `subscription.changed`, `consent.changed`. Consumers: `features.invalidate_cache` ← `feature_flag.changed`; `notifications.*` ← password reset/OTP (Phase 04 completes channels; this phase uses the mock providers). Beat: `auth.cleanup_sessions` (hourly), `auth.expire_time_boxed_accounts` (daily), `subscriptions.reminders` (daily), `usage.meter` (monthly). Workflow definitions: none.

## 02.8 Endpoints
```
POST   /api/v1/auth/login                         → password (+ mfa_code) login {public}
POST   /api/v1/auth/send-otp · /verify-otp        → OTP login {public, rate-limited, captcha optional}
POST   /api/v1/auth/refresh                        → rotate refresh cookie → new access token {public}
POST   /api/v1/auth/logout?all=                    → revoke session(s) [auth]
GET    /api/v1/auth/me                             → MeUser + permissions[] + features[] + scopes[] + visibility defaults [auth]
POST   /api/v1/auth/forgot-password · /reset-password · /change-password {public / auth}
POST   /api/v1/auth/mfa/setup · /confirm · /disable · /recovery-codes/regenerate [auth] {security.mfa}
GET    /api/v1/auth/sessions · DELETE /auth/sessions/{id} · DELETE /auth/sessions [auth] {security.session_management}
GET    /api/v1/auth/login-history [auth]
GET    /api/v1/auth/sso/{provider}/start · GET /auth/sso/{provider}/callback {public} {security.sso}
GET    /api/v1/permissions                         → catalogue [roles:view]
GET/POST /api/v1/roles · GET/PUT/DELETE /roles/{id} · POST /roles/{id}/clone [roles:view|create|update|delete]
GET/PUT /api/v1/roles/{id}/permissions             → matrix [roles:view|manage]
GET/POST /api/v1/users · GET/PUT /users/{id} · POST /users/{id}/deactivate · /reactivate [users:view_all|create|update]
GET/POST /api/v1/users/{id}/roles · DELETE /users/{id}/roles/{assignment_id} [roles:assign]
POST   /api/v1/users/{id}/reset-password           → admin reset → must_change_password [users:reset_password]
POST   /api/v1/users/credential-sheets             → bulk job [users:create]
POST   /api/v1/users/{id}/impersonate · POST /auth/impersonation/stop [users:impersonate] (super admin / support_agent read-only)
GET    /api/v1/features                            → registry (definitions) [features:view]
GET    /api/v1/institutions/{id}/features          → effective flags [features:view] (super admin / institution admin)
PUT    /api/v1/institutions/{id}/features/{key}    → platform toggle (super admin) [features:manage]
PUT    /api/v1/features/{key}/institution-toggle   → institution admin switch [features:institution_toggle]
POST   /api/v1/institutions/{id}/features/apply-plan-defaults [features:manage]
GET    /api/v1/platform/features/matrix            → institutions × features (super admin) [features:manage]
GET    /api/v1/entitlements                        → plan, limits, usage [settings:view]
POST   /api/v1/consents · GET /consents/me · POST /data-subject-requests · GET /data-subject-requests/me [auth] {privacy.*}
POST   /api/v1/install                              → one-time bootstrap {public, INSTALL_SECRET_KEY}
```

## 02.9 Frontend
- Pages: `/login` (identifier/password, OTP tab, SSO buttons when enabled, MFA code step, forced password change), `/forgot-password`, `/reset-password`, `/profile` (details, change password, MFA setup with QR, sessions with revoke, login history, consents), `/admin/users` (DataTable, create, roles & scopes drawer with scope pickers per role, deactivate, credential sheets), `/admin/roles` (list, clone, permission matrix page: rows = modules, columns = actions, toggle-all, diff preview before save), `/super-admin/institutions/:id/features` (**Features tab**: grouped toggles with search, plan badge, dependency confirmation dialog, per-feature config JSON editor, change log), `/super-admin/features/matrix`, `/admin/settings/features` (institution view: read-only platform state + institution switch), `/admin/settings/entitlements`.
- `authStore.setSession` populated from `/auth/me`; `useVisibility` default scopes from `/auth/me`; impersonation banner with **Stop** button.
- Role → home mapping in `utils/constants.ts` `PORTAL_HOME`; `LoginPage` redirects accordingly.
- Nav: ADMIN group gets Users, Roles, Features (institution), Entitlements.

## 02.10 Mobile
`features/auth`: login (password/OTP), MFA code step, forced password change, biometric lock setting, sessions list/revoke; `AuthState` fills `permissions`, `features`, `scopes`; `role_shells.dart` picks the shell from `role_slugs`.

## 02.11 API verification — `scripts/verify/02_auth_rbac.ps1`
Seed first: `python scripts/seed_platform.py && python scripts/seed_demo_institution.py --type university --only base` (creates demo institution `demo-uni`, colleges A/B, departments, and users: `superadmin`, `inst.admin`, `registrar`, `coe`, `exam.cell`, `decoder`, `dean.eng`, `hod.cse`, `faculty.1`, `advisor.1`, `accountant`, `hr`, `admissions`, `placement`, `warden.h1`, `gate.h1`, `librarian`, `iqac`, `college.admin.b`, `student.1`, `parent.1`, `alumni.1`, `auditor.tmp` (valid 7 days), `examiner.ext` (valid 30 days)).
1. Login `student.1` → 200; response has `access_token`, `permissions` containing `students:self`, `features` containing `core.auth`; cookie `refresh_token` set with `HttpOnly; SameSite=Strict`.
2. Wrong password ×5 → 6th attempt 429 `RATE_LIMITED` within 15 min.
3. `POST /auth/refresh` → new access token; replay the **old** refresh cookie → 401 and the session family is revoked (subsequent refresh with the new cookie also 401).
4. `coe` login without MFA enrolled → 403 `MFA_REQUIRED` + `mfa_setup_required=true`; `POST /auth/mfa/setup` (with a temporary limited token) → secret; `confirm` with a code from `pyotp` → login with code → 200.
5. `GET /auth/me` as `accountant` → `permissions` include `hr:view_all`, `leaves:view_all`, `leaves:self`, `attendance:staff_view_all`, `payroll:manage`; scopes `[institution]`.
6. `GET /roles` as `student.1` → 403 `PERMISSION_DENIED`; as `inst.admin` → 200 with 50 institution roles.
7. Permission matrix: `PUT /roles/{accountant}/permissions` removing `leaves:view_all` → `GET /auth/me` (accountant, re-login) no longer has it; restore.
8. Scopes: assign `hod` to `faculty.1` with `scope_type=department, scope_id=<CSE>`; `GET /auth/me` shows the scope; assign with a department of another institution → 422 `VALIDATION`.
9. Features: as super admin `PUT /institutions/{demo}/features/hostel.core {enabled:false}` → `GET /auth/me` (student) `features` lacks `hostel.core` within 60 s (or immediately after event); `GET /api/v1/hostels` (stub route from scaffold) → 403 `FEATURE_DISABLED`; disabling `fees.core` while `fees.scholarships` is on → 409 listing dependants; enabling `hostel.gate_qr` without `hostel.leave_outpass` → 409 unless `confirm_dependencies=true` (then both enabled).
10. Institution toggle: `inst.admin` `PUT /features/hostel.mess/institution-toggle {enabled:false}` → effective false; `{enabled:true}` when platform disabled → 409.
11. Time-boxed: `auditor.tmp` login → 200; after setting `valid_to` in the past (dev route) → 401 with code `UNAUTHENTICATED` and message "account expired".
12. Impersonation: super admin `POST /users/{inst.admin}/impersonate` → token; `GET /auth/me` shows `impersonator_id`; creating a role during impersonation writes `audit_logs.impersonator_id`; `support_agent` impersonation attempt to write → 403.
13. PII masking: `GET /users/{hr}` as `inst.admin` (no `users:view_pii`) → `phone` masked `******7890`; as `hr` with `hr:view_pii` → full.
14. Entitlements: set demo plan `student_limit=1` via super admin; `POST /students` (stub) → 403 `RULE_VIOLATION` code `SEAT_LIMIT`; revert.
15. Sessions: list shows 2 devices; revoke other → its refresh → 401.
16. `POST /install` again → 409 (already installed).

## 02.12 UI verification
1. Login as each seeded role → lands on the correct home (`PORTAL_HOME`); sidebar shows only permitted + enabled items.
2. Accountant: sidebar shows PEOPLE › Staff (read), Leaves, Staff Attendance (placeholders) and FINANCE; student sees only the portal.
3. Roles page: matrix toggles, diff preview, save → toast; system role rename disabled.
4. Users page: create user with role + scope picker (department dropdown scoped to institution); credential sheet job appears in the tray and downloads.
5. Super-admin Features tab: toggle `hostel.core` off → the demo institution admin's sidebar loses Hostel after refresh; dependency dialog on `hostel.gate_qr`; change log shows entries.
6. Profile: MFA enrol with QR + code; sessions list; revoke; consents toggle.
7. Impersonation banner visible and "Stop impersonating" returns to super admin.

## 02.13 Deliverables checklist
- [ ] Auth flows (password/OTP/refresh rotation/logout/forgot/reset/change/MFA/sessions/login history/SSO hook/time-boxed accounts)
- [ ] RBAC: roles CRUD/clone, permission matrix, scoped assignments with validation, `seed_institution_roles`
- [ ] Feature registry, per-institution flags with dependency rules, institution toggle, plan defaults, matrix, cache invalidation via event
- [ ] Visibility resolver wired into `BaseRepository`, `meta.visibility` in list envelopes, PII masking
- [ ] Entitlements (subscription status, seat/storage/SMS limits), impersonation with audit, privacy consents/DSR, `/install`
- [ ] `seed_platform.py`, `seed_demo_institution.py --only base` with all demo roles, `LOCAL_TEST_CREDENTIALS.md` generated
- [ ] Web pages + mobile auth; `scripts/verify/02_auth_rbac.ps1` passes; UI checklist done; `check_authz_coverage.py` green; commit `feat(phase-02): auth, rbac, features, visibility`
