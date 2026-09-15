# ADR 0003 — Every feature is a registered, super-admin-controlled flag

**Status:** accepted (2026-09-13)

## Decision
A code-level registry (`app/core/features.py`) defines ≈230 feature keys with group, defaults, plan tier and dependencies. `institution_feature_flags` stores `platform_enabled` (super admin) and `institution_enabled` (institution admin, may only switch off); effective = both. Routers include `feature_required(key)`; `/auth/me` returns effective keys; web and mobile hide disabled features; Celery/Beat skip disabled tenants. CI fails if any router/nav/tab cites an unregistered key.

## Consequences
Pilots can run on subsets; plans map to defaults; per-feature `config` allows limits/providers. Every phase prompt lists the keys it introduces.
