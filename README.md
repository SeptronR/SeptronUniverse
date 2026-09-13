# SeptronUniverse — College & University ERP

Multi-tenant Higher-Education ERP for **affiliated colleges, autonomous colleges, universities (state / private / deemed) and multi-campus institutions**. It is the higher-education sibling of **SeptronOrbit** (school ERP) and follows the same architecture, stack, layer conventions and prompt-driven build process.

| Layer | Stack |
|---|---|
| Backend | FastAPI (async) · SQLAlchemy 2 async + Alembic · PostgreSQL 15 (+ Row-Level Security) · Redis 7 · Celery 5 · Pydantic v2 · WeasyPrint + Jinja2 |
| Frontend | React 18 + TypeScript + Vite · React Router v6 · TanStack Query v5 · Zustand · Tailwind + Radix · Recharts · FullCalendar · dnd-kit · TipTap |
| Mobile | Flutter 3.22+ · Riverpod · go_router · dio · drift (offline) · FCM |
| Infra | Docker Compose · GitHub Actions → `ghcr.io/septronr/universe-api` → `orbit-infra` (Traefik) |

## What makes it "higher-ed"

- **Tenancy:** `institution → colleges/campuses → faculties → departments`, with university ↔ affiliated-college workflows.
- **Academics:** programmes → regulations (versioned rules) → curriculum → courses (L-T-P-C) → **course offerings** per term; credit-based registration (NEP 2020 / CBCS, multiple entry-exit, ABC/APAAR).
- **Examinations:** registration & hall tickets → coded (dummy-number) valuation, double valuation, moderation → versioned immutable results (SGPA/CGPA) → revaluation, supplementary, malpractice → convocation & digital credentials (DigiLocker/NAD/ABC).
- **Outcome-Based Education:** PEO/PO/PSO/CO, CO-PO mapping, direct + indirect attainment, CQI.
- **Campus & people:** hostel/mess, library, transport, inventory/procurement, HR/payroll/recruitment/CAS, research & PhD lifecycle, placement & alumni, mentoring/grievances/discipline/surveys, events & facilities, governance (committees, minutes, RTI, legal), accreditation (NAAC/NBA/NIRF/AISHE).
- **Platform:** every feature is a super-admin-controlled flag per institution; every record is visible through a self / ownership / scoped / `view_all` model; approval-workflow engine; transactional outbox; integrations hub; data-migration toolkit.

## Repository map (planning phase)

```
README.md                         this file
Architecture.md                   Mermaid diagrams (tenancy, authz, exam lifecycle, result versioning, module map, ERD, topology)
Database_Schema.sql               canonical DDL — single source of truth for table/column names
Prompts/00_HOW_TO_USE.md          how to run the phase prompts (rounds, gates, definition of done)
Prompts/00_PREREQUISITE_...md     project setup with paste-ready boilerplate
Prompts/NN_PhaseNN_*.md           one self-contained prompt per phase (01–44)
docs/Academic_Core_Design.md      column-level design of the academic core (structure, admissions, registration, attendance, exams, OBE, …)
docs/Feature_Flags.md             feature-key registry + super-admin control mechanism
docs/Authorization_and_Visibility.md  four-layer authz + role × module visibility matrix
docs/User_Flows.md                end-to-end journeys per role
docs/Mobile_App_UI_Structure.md   Flutter role shells, tabs, screens, offline rules
docs/Coverage_Matrix.md           source inventories → phase → feature key → tables
docs/Glossary_and_Orbit_Mapping.md  glossary + Orbit → Universe rename table
docs/Feature_Inventory.md         full feature list per module × institution type
docs/Roles_and_Permissions.md     roles, permission registry, default role → permission map
docs/Regulatory_Pack_IN.md        India pack (NEP, ABC/APAAR, NAAC/NBA/NIRF/AISHE, UGC PhD, DLT/DPDP/GST)
docs/Integrations_Catalogue.md    adapter interfaces and providers
docs/Technical_Architecture.md    platform building blocks (outbox, RLS, workflow, jobs, files, WS, search, observability, data lifecycle)
docs/ADR/                         architecture decision records
RUN_AFTER_PHASE.md                runbook after each phase (migrate, seed, drift/authz checks, API smoke, run apps)
QA_Test_Plan.md                   per-role UI functional sweep plan
Real_World_Launch_Plan.md         provider/government onboarding tracker
```

Source code lands in `backend/`, `frontend/` and `flutter/` as the phase prompts are executed.

## How to use the prompts

1. Read `Prompts/00_HOW_TO_USE.md`, then execute `Prompts/00_PREREQUISITE_Project_Setup.md`.
2. Execute prompts in numeric order (rounds are sequential; prompts inside a round may run in parallel worktrees when they touch disjoint models).
3. After each prompt run `RUN_AFTER_PHASE.md`: migrate, seed, run the schema-drift and authz/feature audits, then **verify through the API and the UI** (scripted API calls per role + UI functional checks). Commit before starting the next prompt.

## Verification philosophy

Phases are verified **functionally** — by calling the API directly (per-role smoke/functional scripts) and by exercising the UI (Playwright suites and per-role sweeps) — not by unit tests. Structural CI guards (schema drift, authz/feature audit, single Alembic head, supply-chain scans) remain.

## Related repositories

- `../SeptronOrbit` — the school ERP whose architecture and conventions this project mirrors.
- `../orbit-infra` — shared production platform (Traefik, Postgres, Redis, monitoring); Universe deploys as `compose/apps/universe-{dev,demo,prod}-api.yml`.
