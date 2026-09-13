# ADR 0005 — Domain events via transactional outbox

**Status:** accepted (2026-09-13)

## Decision
Services emit domain events into `domain_events` within the same DB transaction; a relay moves them to Celery consumers (notifications, webhooks, search, metrics, ABC/DigiLocker push, analytics). Delivery is at-least-once; consumers are idempotent; failures dead-letter with admin retry.

## Consequences
No lost notifications or webhooks on crashes; integrations and caches stay consistent with committed data; `domain_events` is partitioned and archived.
