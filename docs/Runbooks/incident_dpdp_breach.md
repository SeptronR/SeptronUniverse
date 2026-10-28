# Runbook — personal-data breach (DPDP Act 2023 / Rules)

Owner: platform security lead + the affected institution's privacy officer. Severity: always **SEV-1** until scoped.

## 0–1 hour: contain
1. Open an incident channel; record the timeline (UTC) from the first signal (alert, report, `audit.anomaly_detected`).
2. Contain: revoke affected sessions (`POST /security/sessions/revoke`), rotate exposed credentials (API keys, webhook
   secrets, provider secrets — `integrations.reencrypt_secrets`), enable read-only mode for the tenant if writes are
   involved (`POST /platform/read-only`), block offending IPs at the edge.
3. Preserve evidence: export the relevant `audit_logs` range, verify the hash chain (`/audit/chain/verify`), snapshot
   application logs (already PII-redacted) and database (point-in-time backup reference).

## 1–24 hours: assess
4. Scope: which tenants, which data principals, which categories (use the PII inventory classes — identifier,
   financial, health, biometric, minor raise the severity), how many records, whether data left the system.
5. Decide notification duties with the institution (the Data Fiduciary): the Data Protection Board and each affected
   data principal must be informed **without delay** (draft rules: detailed report within **72 hours**).

## 24–72 hours: notify
6. Board intimation (template below) through the institution's privacy officer; principal notices in plain language
   (what happened, what data, what we did, what they can do, contact) via e-mail / SMS / in-app (`notify_event` with
   a dedicated template; never include the breached data itself).
7. Regulators / CERT-In: report cyber incidents to CERT-In within **6 hours** of noticing them (CERT-In directions 2022).

## After
8. Root cause, fix, retest (add a row to `docs/Security/VAPT_Findings.csv`), update this runbook, post-incident review
   within 10 working days, evidence added to the ISO readiness pack.

### Board intimation template
> Data Fiduciary: <institution>, privacy officer <name, contact>. Nature of breach: <…>. Time of occurrence / detection:
> <…>. Personal data affected: <categories, approx. number of principals>. Likely consequences: <…>. Measures taken /
> proposed: <containment, mitigation>. Notice to principals: <date, channel>.
