# Runbook — Backups, restore & disaster recovery

**Backups.** pgBackRest full weekly (Sun 01:00 UTC), incremental every 6 h, continuous WAL archive (`archive_timeout` 300 s → RPO ≤ 5–15 min), daily `verify`; client-side AES-256; retention 5 fulls (~30 days) + archive; S3 lifecycle keeps 12 monthly fulls. Every run posts to `/internal/ops/backup-report`; `BackupTooOld` fires after 6 h without success.

**Restore drill (quarterly, `0 3 1 */3 *`).** `scripts/ops/restore_drill.sh` on a scratch host: PITR to now-10 min, alembic head, row counts on 20 tables, audit chain, RPO / RTO measured and posted (`/super-admin/ops/backups`). Targets: RPO 15 min, RTO 4 h.

**DR (primary host lost).** 1) Provision a replacement host from the orbit-infra playbook. 2) `pgbackrest --stanza=universe restore --type=time --target=<last good>`. 3) Start the stack with `READ_ONLY_MODE=true`, verify (`run_all.py --suite smoke`, audit chain). 4) Switch DNS / Traefik. 5) Lift read-only, announce on the status page. Record the timeline as a drill.
