# ADR 0006 — Verification through API scripts and UI functional checks

**Status:** accepted (2026-09-13)

## Context
The product owner requires that features be verified by exercising the real system — calling the API directly and using the UI — rather than by unit-test suites.

## Decision
Each phase prompt ends with **API verification** (per-role scripted calls with expected status/envelope/visibility) and **UI verification** (page/flow checks; Playwright suites per round; per-role manual sweeps recorded in `QA_Test_Plan.md`). Structural CI guards remain (schema drift, authz/feature audit, single Alembic head, feature registry check, supply-chain scans). No pytest unit coverage is required.

## Consequences
A demo institution seeder and per-role demo accounts are prerequisites for every phase; scripts live in `backend/scripts/verify/<phase>.ps1|py`; regressions are caught by re-running earlier phase scripts.
