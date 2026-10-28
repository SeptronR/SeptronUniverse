# Runbook — Outbox backlog / relay stuck

Signals: alert `OutboxLag` (> 120 s), `outbox_pending` rising, `/ready` 503 with `outbox` check failing.
1. `GET /platform/ops/overview` → `outbox`, `queues`. Is the `scheduled` worker alive (`worker_alive{queue="scheduled"}`)? Restart it: `docker compose up -d --no-deps worker-scheduled`.
2. Dead events (`status='dead'`) do not block the relay; inspect them on `/admin/integrations/dead-letters` (kind outbox) and replay after fixing the consumer.
3. A poison event (same id failing repeatedly): read `last_error`, fix the consumer or mark it dead (`UPDATE domain_events SET status='dead' WHERE id=…` on the platform role, audited in the incident notes).
4. After recovery confirm `outbox_lag_seconds` < 30 s.
