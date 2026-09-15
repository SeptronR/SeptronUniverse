# ADR 0004 — Row-level visibility resolver

**Status:** accepted (2026-09-13)

## Decision
Authorization has four layers (feature → permission → scope → visibility). Permission action `view` covers self + ownership; `view_all` covers the role's scope. `VisibilityResolver.predicate(user, module)` = self ∪ ownership (derived from teaching/mentoring/advising/guardian/warden/guide/valuation links) ∪ scope-if-view_all, applied by `BaseRepository.visible_to()`. List responses return `meta.visibility` so clients render Mine/Dept/College/All views. Sensitive fields are masked unless `module:view_pii`.

## Consequences
One list endpoint per module; portals are self-only; the admin shell shows the wider views the role has (e.g., accountant: own leaves/attendance and all staff/leaves/attendance). Existence leaks are avoided by returning 404 for invisible rows.
