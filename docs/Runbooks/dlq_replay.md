# Runbook — Dead-letter replay

Dead letters exist for outbox events, webhook deliveries and notifications (`dlq_size{kind}`).
1. Find the cause first (provider outage, bad config, consumer bug) — replaying into the same failure only grows the DLQ.
2. `/admin/integrations/dead-letters` → kind → *Replay all* (or `POST /integrations/dead-letters/replay {kind, ids}`); discards need a reason (audited).
3. Webhook endpoints auto-disabled after consecutive dead deliveries must be re-enabled by the tenant once their receiver is fixed.
