# ISO/IEC 27001:2022 readiness — Annex A mapping

How the platform supports the operating organisation's ISMS. Status is the **platform's** contribution (organisational
controls such as HR screening are the operator's). Summary served by `GET /api/v1/security/iso-readiness`.

| Control | Title | Platform mechanism | Status | Evidence |
|---|---|---|---|---|
| A.5.15 | Access control | RBAC (54 role templates), scopes, feature flags, access matrix guard | implemented | `docs/Access_Matrix.csv`, `check_access_matrix.py` |
| A.5.16 | Identity management | users / roles lifecycle, time-boxed accounts, SSO | implemented | Phase 02 |
| A.5.17 | Authentication information | password policy, breached-password check, MFA | implemented | `app/core/security.py`, `app/core/hardening.py` |
| A.5.18 | Access rights review | access matrix export, role assignment audit | partial | quarterly review procedure pending |
| A.5.19 | Supplier relationships | provider connections catalogue, per-provider DPAs | partial | `docs/Integrations_Catalogue.md`; DPAs held by the operator |
| A.5.23 | Cloud services | deployment on managed services with backups | partial | Phase 44 |
| A.5.24 | Incident management planning | runbooks, breach notification | implemented | `docs/Runbooks/incident_dpdp_breach.md` |
| A.5.28 | Collection of evidence | hash-chained audit log, digests, manifests | implemented | Phase 37 |
| A.5.30 | ICT readiness for business continuity | backups, restore drills, DR | partial | Phase 44 |
| A.5.33 | Protection of records | immutable results / documents, retention | implemented | `immutability_check.py` |
| A.5.34 | Privacy and protection of PII | DPDP consents, DSR workflow, PII inventory, masking | implemented | Phase 43 privacy office |
| A.8.2 | Privileged access rights | super admin / support split, impersonation logging | implemented | Phase 38 |
| A.8.3 | Information access restriction | RLS tenant isolation, college / department scope | implemented | `visibility_check.py` |
| A.8.5 | Secure authentication | MFA enforcement, session limits | implemented | `/security/mfa-enforcement` |
| A.8.9 | Configuration management | settings template, audited settings changes | implemented | Phase 37 settings console |
| A.8.12 | Data leakage prevention | PII masking, screenshot blocking (mobile), export controls | implemented | `check_pii_masking.py`, `SafeScreen` |
| A.8.13 | Information backup | encrypted backups | partial | Phase 44 |
| A.8.15 | Logging | structured logs with PII redaction, security events | implemented | `app/core/logging.py` |
| A.8.16 | Monitoring activities | anomalies, posture dashboard | implemented | Phase 37 / 43 |
| A.8.20 | Network security | CORS allow-list, IP allow-lists for exam ops | implemented | posture `ip_allowlist_exam_ops` |
| A.8.24 | Use of cryptography | AES-GCM at rest, TLS, HMAC webhooks, RS256 option | implemented | `app/core/security.py` |
| A.8.25 | Secure development life cycle | CI guards, scans, SBOM | implemented | `.github/workflows/security.yml` |
| A.8.26 | Application security requirements | ASVS L2 checklist | implemented | `ASVS_L2_Checklist.md` |
| A.8.28 | Secure coding | ruff / mypy / semgrep / bandit in CI | implemented | CI |
| A.8.29 | Security testing | verification runner, VAPT | partial | `run_all.py`; external VAPT pending |
| A.8.32 | Change management | phase branches, PR checks | implemented | `PROGRESS.md` |
| A.8.33 | Test information | demo data only on non-production, suites refuse production | implemented | `run_all.py` guard |

## Policy templates for the operating organisation

Information security, access control, backup, incident response, secure development, supplier security and
acceptable use policies are maintained by the operator; outlines live in `docs/Security/policies/` (to be adapted to the
organisation's structure before certification).
