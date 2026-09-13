# ADR 0007 — Status columns as VARCHAR + Python enums

**Status:** accepted (2026-09-13)

## Decision
Status/type columns are `VARCHAR(30)` validated by Python `str` enums in schemas and services (optionally CHECK constraints), not PostgreSQL enum types.

## Consequences
Adding a status is a code change plus (optionally) a CHECK update — no `ALTER TYPE` migrations; the Orbit `compat.ENUM` wrapper is unnecessary.
