# Runbook — Tenant restore (logical)

1. Super admin A requests `tenant_restore {institution, export_key, target_dsn}`; super admin B approves (`/super-admin/ops/scripts`).
2. The job decrypts the export and loads CSVs into the scratch DSN; row counts are compared with the export manifest.
3. The institution reviews; selected rows are copied back with a reviewed SQL script inside a read-only window for that tenant; the copy-back is recorded in the incident / change ticket.
Full point-in-time restores use pgBackRest (`backup_restore_dr.md`).
