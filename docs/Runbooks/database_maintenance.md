# Runbook — Database maintenance

* Partitions: `beat.partitions.ensure_next_month` creates next month's partitions for `domain_events`, `webhook_deliveries`, `audit_logs`, `message_logs`, `student_class_attendance`, `vehicle_gps_logs`; `/super-admin/ops/partitions` shows gaps; *Ensure* runs it on demand.
* Bloat / vacuum: autovacuum defaults are tuned for the reference host; check `pg_stat_user_tables.n_dead_tup` on the DB dashboard; `VACUUM (ANALYZE)` heavy tables off-peak.
* Reindex: `REINDEX INDEX CONCURRENTLY …` off-peak.
* Slow queries: `pg_stat_statements` top 10 reviewed per release (`performance_tuning.md`).
