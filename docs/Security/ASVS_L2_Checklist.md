# OWASP ASVS 4.0.3 Level 2 — self-assessment

Status: **pass** (control in place with evidence) · **partial** · **gap**. Evidence links point at code, CI guards or
runbooks. Reviewed in Phase 43; re-assessed before each VAPT.

| Area | Requirement (summary) | Status | Evidence |
|---|---|---|---|
| V1 Architecture | Threat model, trust boundaries documented | partial | `docs/Technical_Architecture.md` §11, `docs/Security/VAPT_Scope.md` |
| V2 Authentication | Password ≥ 10, 3 of 4 classes, history, breached-password check | pass | `app/core/security.py` `check_password_policy`, `app/core/hardening.py` `check_breached_password` |
| V2 | Brute-force protection (lockout, rate limits, captcha after failures) | pass | Phase 02 lockout, `app/core/rate_limit.py` |
| V2 | MFA (TOTP) for privileged roles, enforcement with grace | pass | `auth_service._mfa_required`, `/security/mfa-enforcement` |
| V3 Session | Refresh rotation + reuse detection, revocation, max age | pass | Phase 02 `user_sessions`, `security.session_max_days` posture check |
| V3 | Tokens: signed, `kid` rotation, short-lived access tokens | partial | HS256 + `kid`; RS256 + JWKS when `JWT_RSA_PRIVATE_KEY` set (INT-005) |
| V4 Access control | Deny by default, every route gated | pass | `check_authz_coverage.py` (0 offenders), `check_access_matrix.py` |
| V4 | Tenant isolation at the database | pass | Postgres RLS on 391 tables, `scripts/verify/visibility_check.py` |
| V4 | IDOR: invisible rows answer 404 | pass | service visibility predicates; verify scripts per phase |
| V5 Validation | Schema validation on every input, JSON depth / size limits | pass | Pydantic models, `SecurityHeadersMiddleware` (413 / depth 64) |
| V5 | Output encoding / XSS sanitisation of rich text | pass | Phase 40 allow-list sanitiser, React escaping |
| V5 | SSRF protection on outbound URLs | pass | `assert_public_url` (webhooks; private ranges refused) |
| V5 | Template injection | pass | Jinja2 sandboxed environment for notification / document templates |
| V6 Cryptography | AES-GCM for `*_encrypted` columns, key rotation procedure | pass | `encrypt_secret`, `integrations.reencrypt_secrets` job, `docs/Runbooks/jwt_key_rotation.md` |
| V7 Logging | Security events logged, PII redacted, tamper-evident audit | pass | `redact_pii` processor, hash-chained `audit_logs` (append-only grants, INT-001) |
| V8 Data protection | PII inventory, masking, DSR handling | pass | `app/core/pii_inventory.json`, `check_pii_masking.py`, DSR workflow |
| V9 Communications | TLS everywhere, HSTS | partial | nginx TLS (Phase 44), HSTS on https responses |
| V10 Malicious code | Dependency / secret scanning | pass | `security.yml` (pip-audit, npm audit, gitleaks, trivy, semgrep, bandit, osv) |
| V12 Files | MIME sniffing, extension allow-list, size limits, EXIF strip | pass | `app/core/files.py`, Phase 40 gallery re-encode |
| V13 API | Rate limits per API key, scoped keys, webhook signatures | pass | Phase 41 API keys / webhooks |
| V14 Configuration | Security headers, CSP, no secrets in code, debug off in prod | partial | CSP report-only (INT-004); secrets from env only |
