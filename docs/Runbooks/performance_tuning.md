# Runbook — Performance tuning

Measured, not speculative. Per release: `SELECT query, calls, mean_exec_time FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10` on staging after the Phase 43 load scenarios (`load/`); each offender gets an expand migration (`CREATE INDEX CONCURRENTLY`) or a query fix, with before / after numbers recorded below.

Defaults on the §17 reference host: `shared_buffers` 4 GB, `work_mem` 32 MB, pgbouncer transaction pooling (pool 200; RLS context is `SET LOCAL` per transaction, so pooling is safe), `DB_POOL_SIZE` 20 + 10 overflow per API replica, API statement timeout 30 s, report jobs 10 min, Celery concurrency notifications 8 / emails 4 / documents 4 / reports 4 / integrations 4 / scheduled 2, Redis `maxmemory` 2 GB (`noeviction`; cache keys carry TTLs), SSR page cache TTL from `website.cache_ttl_seconds`.

| Date | Query / area | Before p95 | Change | After p95 |
|---|---|---|---|---|
| _pending staging load run_ | | | | |
