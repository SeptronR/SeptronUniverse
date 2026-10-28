# Runbook — Scaling workers & replicas

* API: `API_REPLICAS` (compose `deploy.replicas`), `WEB_CONCURRENCY` per replica (≈ 2 × vCPU). Watch p95 and DB connections — every replica holds `DB_POOL_SIZE + DB_MAX_OVERFLOW` connections to pgbouncer.
* Workers: concurrency per queue from `platform_settings['ops'].capacity.celery_concurrency` (`C_<QUEUE>` env). Documents (PDF) workers are CPU / memory heavy — scale replicas rather than concurrency.
* The capacity page (`/super-admin/ops/capacity`) proposes changes when queue peaks exceed 1 000 or connections exceed 85 % of the pool.
