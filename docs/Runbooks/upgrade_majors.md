# Runbook — Upgrading PostgreSQL / Redis major versions

PostgreSQL: rehearse on staging with `pg_upgrade --link` from a restored backup; schedule a maintenance window; take a full backup; stop the stack; upgrade; `ANALYZE`; start; run smoke + drift check; new pgBackRest stanza-upgrade. Redis: AOF is forward compatible — rolling restart with the new image, verify queues drain.
