# Runbook — Redis restart

Redis holds the Celery broker (DB 1), results (DB 2), caches and rate-limit / heartbeat keys (DB 0) with AOF persistence.
1. `docker compose restart redis` — `/ready` turns 503 for the outage, the API keeps serving cached-free requests, WebSocket clients reconnect with backoff.
2. Workers reconnect automatically (`broker_connection_retry_on_startup`); queued tasks survive via AOF; in-flight tasks with `acks_late` are redelivered (jobs are idempotent).
3. Verify: queue depths drain, heartbeats return within 1 minute, `/ready` 200.
