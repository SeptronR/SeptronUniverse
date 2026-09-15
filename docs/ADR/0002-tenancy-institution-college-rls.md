# ADR 0002 — Tenant = institution; colleges as sub-tenants; RLS backstop

**Status:** accepted (2026-09-13)

## Decision
The tenant root is `institutions` (a university or a standalone college). `colleges` (constituent/affiliated/autonomous/campus/study centre) are sub-units; academic rows carry both `institution_id` and `college_id` (NULL = institution-wide). Role assignments carry a scope (`user_roles.scope_type/scope_id`). PostgreSQL Row-Level Security on every tenant table (`app.institution_id` set per request/task) is a defence-in-depth backstop for the application-level filters in `BaseRepository`.

## Consequences
A standalone college is an institution with one auto-created college, so all code paths are identical. Multi-college isolation (results, registrations, scripts) is enforced by `college_id` + scope + resolver. Celery tasks must set the RLS context explicitly.
