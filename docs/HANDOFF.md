# Session Hand-off — how to resume SeptronUniverse work in a fresh session

Work is deliberately split into **one batch per session** to keep context and token use small. This file tells a new session exactly what to read, what to produce, and how to hand back.

## 1. Start-of-session protocol (≈ 5 minutes of reading)

1. Read `PROGRESS.md` → find the first ☐ batch. That is the only scope for this session.
2. Read `MASTER_PLAN.md` **§5** rows for the phases in the batch, plus the design sections they point to: §6 (academic core), §7 (feature keys), §8 (visibility), §9 (user flows), §10 (mobile).
3. Read `docs/Academic_Core_Design.md` sections for those phases (column-level tables, state machines, formulas, endpoints, pages).
4. Read `Prompts/00_HOW_TO_USE.md` §6 (prompt anatomy) and **two finished prompts as format exemplars**: `Prompts/12_Phase12_Fees_Scholarships_NoDues.md` (money + workflows) and `Prompts/13_Phase13_Internal_Assessment_OBE_Definitions_LMS_Projects.md` (academic + LMS). Match their depth and structure exactly.
5. Grep `Database_Schema.sql` for the tables of the batch (section headers `-- ===== NN. …`) — **copy table names, never invent them**.
6. Check `docs/Feature_Flags.md` for the feature keys of the batch and `docs/Roles_and_Permissions.md` for permission actions.

Do **not** re-read SeptronOrbit or the whole doc set; everything needed is in the files above.

## 2. What a batch produces

For each phase in the batch, one file `Prompts/NN_PhaseNN_<Title>.md` (names listed in `PROGRESS.md`) with these sections, in order:

```
# PHASE NN — TITLE
## Pre-Requisite · ## Objective · ## Feature keys · ## Visibility rules (table per role when the module has people/records)
## NN.1 Database tables (list the tables from Database_Schema.sql section(s); "Expected delta migration: none")
## NN.2 Alembic migration (data-only seed revision + demo seed `--only <module>` contents)
## NN.3 Models · ## NN.4 Schemas · ## NN.5 Repository (module key, ownership links, scope columns, locks)
## NN.6 Services (numbered business rules, formulas, status machines, hooks)
## NN.7 Events / jobs (emits, consumers, jobs, Beat, workflow definitions)
## NN.8 Endpoints (METHOD path → description [module:action] {feature.key})
## NN.9 Frontend (pages with tabs/filters/columns/actions, ScopeTabs, portal pages, nav entries)
## NN.10 Mobile (screens per role shell, or "none in this phase")
## NN.11 API verification — scripts/verify/NN_<module>.ps1 (numbered, per role, expected status codes / envelope / meta.visibility / business outcomes)
## NN.12 UI verification (numbered checklist per role)
## NN.13 Deliverables checklist (+ commit message `feat(phase-NN): …`)
```

Hard rules (from ADRs and the plan):
- **No unit tests** — verification is API scripts + UI checks; structural guards only.
- Every endpoint cites `[module:action]` and, when gated, `{feature.key}`; every list endpoint returns `meta.visibility`; portals are self-only; admin shell shows Mine | Dept | College | All per `docs/Authorization_and_Visibility.md`.
- Money in paise; statuses `VARCHAR(30)` + Python enums; soft delete; optimistic `version`; RLS via `institution_id`; `college_id` where scoped.
- Published results immutable (new version rows); dummy numbers never exposed to evaluators; `Idempotency-Key` on non-idempotent POSTs; `FOR UPDATE` on seats/money/sequences.
- Fee linkage: any chargeable action calls `fee_service.create_invoice(payer_type, source_type, source_id, …)`.
- Approvals go through the workflow engine (Phase 04) using the shipped definition keys; long work through `background_jobs`; side effects through domain events (outbox).

## 3. End-of-session protocol

1. `python scripts/verify_prompts_vs_schema.py Prompts/NN_*.md` for the new files → 0 missing.
2. `git add -A && git commit` with message `docs: batch <X> - <round name> phase prompts NN-MM` + a bullet per phase + `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
3. Update `PROGRESS.md`: tick the batch and each prompt, add the commit hash, mark the next batch `☐ next`; append to the decisions log if anything was decided.
4. Commit `PROGRESS.md` (`docs: progress - batch <X> done`).
5. Reply with a 5–10 line summary and the exact prompt for the next session (§4).

## 4. Prompt to paste into the next session

```
Continue the SeptronUniverse planning doc set. Read PROGRESS.md and docs/HANDOFF.md first, then produce the next ☐ batch exactly as HANDOFF.md §2 specifies (same depth as Prompts/12_* and 13_*). Verify with scripts/verify_prompts_vs_schema.py, commit, update PROGRESS.md, and stop after that batch.
```

Batch contents for reference:
- **E** (Round 2): 14 Exam administration · 15 Evaluation & results · 16 Post-result services · 17 OBE attainment & CQI · 18 Degrees, convocation & digital credentials — design in `docs/Academic_Core_Design.md` §5–§6 and schema sections 15–17.
- **F** (Round 3): 19 Library · 20 Hostel/mess/staff accommodation · 21 Transport · 22 Inventory/procurement/bills · 23 Accounting/budget · 24 Communication advanced · 25 Calendar/events/facilities · 26 Document templates/certificates/requests — schema sections 18–25, design §9, §16.
- **G** (Round 4): 27 Mentoring/grievances/discipline/surveys/clubs · 28 Placement/internships/training · 29 Alumni/endowments/fundraising · 30 Research & faculty development · 31 PhD · 32 Accreditation/IQAC · 33 Governance · 34 Affiliation — schema sections 26–31, design §7, §8, §10–§15.
- **H** (Round 5): 35 Dashboards/analytics · 36 Reports · 37 Audit/settings · 38 Super admin/SaaS · 39 Portals/PWA · 40 Website/catalogue · 41 Integrations hub/migration · 42 Flutter app (use `docs/Mobile_App_UI_Structure.md`) · 43 Testing/security/privacy · 44 Deployment/CI/CD — schema section 32 + platform tables, `docs/Integrations_Catalogue.md`, `docs/Technical_Architecture.md`.
- **I**: runbooks and infra files copied/adapted from SeptronOrbit (`RUN_AFTER_PHASE.md`, `QA_Test_Plan.md` skeleton, `Real_World_Launch_Plan.md` skeleton, `.claude/launch.json`, `docker-compose.yml`, `nginx/nginx.conf`, `.gitignore`, `.github/workflows/*`). Only this batch may read the Orbit repo (`../SeptronOrbit`) for the file shapes.
- **J**: final cross-check and merge to `main`.

## 5. Stage 2 (building the software) — same idea

Each build session executes exactly one prompt: paste the prompt, implement (a)–(n) from `Prompts/00_HOW_TO_USE.md` §3, run `RUN_AFTER_PHASE.md`, run the phase's API verification script and UI checklist, commit `feat(phase-NN): …`, tick `PROGRESS.md` Stage 2 with the verification results. Never start the next phase in the same session.
