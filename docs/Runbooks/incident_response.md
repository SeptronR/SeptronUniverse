# Runbook — Incident response

1. Declare: open an incident on `/super-admin/ops/incidents` (components affected, first message) — the status page and institution admins are informed.
2. Roles: incident lead, communications, scribe. Updates at least every 30 minutes (`POST /platform/ops/incidents/{id}/update`).
3. Mitigate first (rollback, read-only window, scale, provider fallback), then fix.
4. Resolve with a summary; post-incident review within 5 working days; follow-ups in `QA_Findings.csv` / VAPT tracker. Personal-data breaches follow `incident_dpdp_breach.md` in parallel.
