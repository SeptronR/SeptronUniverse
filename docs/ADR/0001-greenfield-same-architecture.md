# ADR 0001 — Greenfield repository mirroring SeptronOrbit's architecture

**Status:** accepted (2026-09-13)

## Context
SeptronOrbit (school ERP) is a working multi-tenant FastAPI + React + Flutter system with a proven prompt-driven build process. SeptronUniverse targets colleges and universities whose academic model (programmes/regulations/credits, course registration, coded valuation, versioned results) differs fundamentally from classes/sections. Orbit also carries structural debt (hand-declared tenant columns, inconsistent envelope, unguarded modules, multiple Alembic heads).

## Decision
Build SeptronUniverse as a new repository that ports Orbit's **patterns** (stack, layering, conventions, prompt format, deployment pipeline) but not its files, and fixes the known debts from Phase 00 (mixins, BaseRepository, envelope everywhere, authz/feature audit, schema drift check, single-head CI guard).

## Consequences
Reusable modules (auth, RBAC, comms, fees, library, transport, inventory, accounting, HR, templates, audit, super admin, website) are re-implemented against the new base classes; the higher-ed core is designed fresh. Operational knowledge and `orbit-infra` are shared.
