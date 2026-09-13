# SeptronUniverse — Progress Checklist

Single source of truth for **what is done and what comes next**. Update this file at the end of every session (tick items, add the commit hash). Work is done **one batch per session** to keep context small — see [docs/HANDOFF.md](docs/HANDOFF.md) for the session-start protocol and the prompt to paste.

Branch: `planning-docs` (off `main`). Plan: [MASTER_PLAN.md](MASTER_PLAN.md).

## Stage 1 — Planning document set

| Batch | Scope | Status | Commit |
|---|---|---|---|
| A | `README.md`, `docs/` (13 docs), `docs/ADR/` (8) | ✅ done | `c4e6b64` |
| B | `Architecture.md`, `Database_Schema.sql` (406 tables + 5 partition defaults; validated on PostgreSQL 18 incl. RLS + immutability trigger) | ✅ done | `89239ac` |
| C | `Prompts/00_HOW_TO_USE.md`, `Prompts/00_PREREQUISITE_Project_Setup.md`, prompts **01–06**, `scripts/verify_prompts_vs_schema.py` | ✅ done | `60f1342` |
| D | Prompts **07–13** (Round 1 student lifecycle) | ✅ done | `352a720` |
| E | Prompts **14–18** (Round 2 examinations & outcomes); guard script now accepts views/triggers | ✅ done | `8ef555a` |
| F | Prompts **19–26** (Round 3 campus services); guard script now accepts named indexes | ✅ done | `e336760` |
| G | Prompts **27–34** (Round 4 engagement, research, quality) | ☐ next | |
| H | Prompts **35–44** (Round 5 platform & delivery) | ☐ | |
| I | `RUN_AFTER_PHASE.md`, `QA_Test_Plan.md` (skeleton), `Real_World_Launch_Plan.md` (skeleton), `.claude/launch.json`, `docker-compose.yml`, `nginx/nginx.conf`, `.gitignore`, `.github/workflows/*` | ☐ | |
| J | Final review: run `scripts/verify_prompts_vs_schema.py` over all prompts, cross-check `docs/Coverage_Matrix.md` rows → prompts, merge `planning-docs` → `main` | ☐ | |

### Prompt inventory (Stage 1)

| # | Prompt file | Status |
|---|---|---|
| 00 | `00_HOW_TO_USE.md` | ✅ |
| 00 | `00_PREREQUISITE_Project_Setup.md` | ✅ |
| 01 | `01_Phase01_Infrastructure_Platform_Services.md` | ✅ |
| 02 | `02_Phase02_Auth_RBAC_Features_Visibility.md` | ✅ |
| 03 | `03_Phase03_Institution_Structure_Sessions_Settings.md` | ✅ |
| 04 | `04_Phase04_Communication_Core_Workflow_Engine.md` | ✅ |
| 05 | `05_Phase05_Programmes_Regulations_Curriculum.md` | ✅ |
| 06 | `06_Phase06_Staff_Faculty_HR_Recruitment_CAS.md` | ✅ |
| 07 | `07_Phase07_Students_Enrolment_Holds_Standing.md` | ✅ |
| 08 | `08_Phase08_Admissions.md` | ✅ |
| 09 | `09_Phase09_Course_Offerings_Faculty_Allocation_Registration.md` | ✅ |
| 10 | `10_Phase10_Timetable_Rooms.md` | ✅ |
| 11 | `11_Phase11_Attendance_Eligibility.md` | ✅ |
| 12 | `12_Phase12_Fees_Scholarships_NoDues.md` | ✅ |
| 13 | `13_Phase13_Internal_Assessment_OBE_Definitions_LMS_Projects.md` | ✅ |
| 14 | `14_Phase14_Exam_Administration.md` | ✅ |
| 15 | `15_Phase15_Evaluation_Results.md` | ✅ |
| 16 | `16_Phase16_Post_Result_Services.md` | ✅ |
| 17 | `17_Phase17_OBE_Attainment_CQI.md` | ✅ |
| 18 | `18_Phase18_Degrees_Convocation_Digital_Credentials.md` | ✅ |
| 19 | `19_Phase19_Library.md` | ✅ |
| 20 | `20_Phase20_Hostel_Mess_Staff_Accommodation.md` | ✅ |
| 21 | `21_Phase21_Transport.md` | ✅ |
| 22 | `22_Phase22_Inventory_Procurement_Bills.md` | ✅ |
| 23 | `23_Phase23_Accounting_Budget.md` | ✅ |
| 24 | `24_Phase24_Communication_Advanced.md` | ✅ |
| 25 | `25_Phase25_Calendar_Events_Facilities.md` | ✅ |
| 26 | `26_Phase26_Document_Templates_Certificates_Requests.md` | ✅ |
| 27 | `27_Phase27_Mentoring_Grievances_Discipline_Surveys_Clubs.md` | ☐ |
| 28 | `28_Phase28_Placement_Internships_Training.md` | ☐ |
| 29 | `29_Phase29_Alumni_Endowments_Fundraising.md` | ☐ |
| 30 | `30_Phase30_Research_Faculty_Development.md` | ☐ |
| 31 | `31_Phase31_PhD_Research_Scholar_Management.md` | ☐ |
| 32 | `32_Phase32_Accreditation_Compliance_IQAC.md` | ☐ |
| 33 | `33_Phase33_Governance_Committees_Legal_EFile.md` | ☐ |
| 34 | `34_Phase34_Affiliation_Management.md` | ☐ |
| 35 | `35_Phase35_Dashboards_Analytics_Early_Warning.md` | ☐ |
| 36 | `36_Phase36_Reports.md` | ☐ |
| 37 | `37_Phase37_Audit_Logs_Settings.md` | ☐ |
| 38 | `38_Phase38_Super_Admin_SaaS.md` | ☐ |
| 39 | `39_Phase39_Portals_PWA.md` | ☐ |
| 40 | `40_Phase40_Public_Website_Catalogue_Admission_Portal.md` | ☐ |
| 41 | `41_Phase41_Integrations_Hub_Data_Migration.md` | ☐ |
| 42 | `42_Phase42_Flutter_Mobile_App.md` | ☐ |
| 43 | `43_Phase43_Testing_Security_Privacy_Hardening.md` | ☐ |
| 44 | `44_Phase44_Deployment_CICD_Operations.md` | ☐ |

## Stage 2 — Build (execute the prompts, one phase per session)

Not started. When Stage 1 is complete, execute `Prompts/00_PREREQUISITE_Project_Setup.md` first, then phases in order; tick here with the commit hash and the verification script result (`scripts/verify/NN_*.ps1` pass/fail) after each phase.

| Phase | Status | Commit | API verification | UI verification |
|---|---|---|---|---|
| 00 Prerequisite | ☐ | | n/a | n/a |
| 01 | ☐ | | | |
| 02 | ☐ | | | |
| 03 | ☐ | | | |
| 04 | ☐ | | | |
| 05 | ☐ | | | |
| 06 | ☐ | | | |
| 07 | ☐ | | | |
| 08 | ☐ | | | |
| 09 | ☐ | | | |
| 10 | ☐ | | | |
| 11 | ☐ | | | |
| 12 | ☐ | | | |
| 13 | ☐ | | | |
| 14 | ☐ | | | |
| 15 | ☐ | | | |
| 16 | ☐ | | | |
| 17 | ☐ | | | |
| 18 | ☐ | | | |
| 19 | ☐ | | | |
| 20 | ☐ | | | |
| 21 | ☐ | | | |
| 22 | ☐ | | | |
| 23 | ☐ | | | |
| 24 | ☐ | | | |
| 25 | ☐ | | | |
| 26 | ☐ | | | |
| 27 | ☐ | | | |
| 28 | ☐ | | | |
| 29 | ☐ | | | |
| 30 | ☐ | | | |
| 31 | ☐ | | | |
| 32 | ☐ | | | |
| 33 | ☐ | | | |
| 34 | ☐ | | | |
| 35 | ☐ | | | |
| 36 | ☐ | | | |
| 37 | ☐ | | | |
| 38 | ☐ | | | |
| 39 | ☐ | | | |
| 40 | ☐ | | | |
| 41 | ☐ | | | |
| 42 | ☐ | | | |
| 43 | ☐ | | | |
| 44 | ☐ | | | |

## Validation commands (run before every commit)

```bash
python scripts/verify_prompts_vs_schema.py            # all prompts' table refs exist in Database_Schema.sql
grep -c "^CREATE TABLE" Database_Schema.sql           # 411 (406 + 5 partition defaults)
```
Schema re-validation on a local PostgreSQL (optional, after any DDL change):
```bash
psql -U postgres -c "CREATE DATABASE universe_schema_check;" && psql -U postgres -d universe_schema_check -v ON_ERROR_STOP=1 -q -f Database_Schema.sql && psql -U postgres -c "DROP DATABASE universe_schema_check;"
```

## Decisions log (append-only)

- 2026-09-13 — Greenfield repo mirroring Orbit architecture; tenant = institution + colleges; India-first packs; full doc set first (MASTER_PLAN §1.1).
- 2026-09-13 — **No unit tests**: verification via API scripts + UI functional checks; structural CI guards only (ADR 0006).
- 2026-09-13 — Schema-first: Alembic `0001` applies `Database_Schema.sql`; phase migrations are delta-only; table count 406 (design grew from the ~270 estimate — accepted).
- 2026-09-13 — One batch per session; `PROGRESS.md` + `docs/HANDOFF.md` are the resume points.
- 2026-09-13 — Table ownership across Round 3: `amc_contracts` (§21) and `emergency_alerts` (§23) are owned by Phase 25 (facilities); `conversation_sessions`/`wa_processed_messages` are created in Phase 04 but the bot logic lives in Phase 24; Phase 22 seeds a `vendor` portal role; Phase 26 back-fills earlier `pdf_url` rows into `issued_documents` and becomes the single renderer/verify endpoint.
