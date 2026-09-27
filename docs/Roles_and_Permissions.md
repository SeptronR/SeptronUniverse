# SeptronUniverse — Roles & Permissions

Permission strings are `module:action`. Roles are seeded per institution from the 51 platform templates (`app/core/rbac/registry.py` → `RbacService.seed_institution_roles`) and are editable in the permission-matrix UI. A role assignment carries a **scope** (`user_roles.scope_type/scope_id`) and an optional validity window. Row-level visibility is defined in `docs/Authorization_and_Visibility.md`.

**Implemented in Phase 02.** The catalogue (916 `module:action` rows), the templates and their default grants live in `app/core/rbac/registry.py` and are written to the database by revision `0002_phase02_auth_seed`, `scripts/seed_platform.py` and `POST /install` (the same code path). `module:manage` is the module wildcard `Principal.has()` honours — with one exception: **`view_pii` is never implied** and must be granted explicitly, so `institution_admin` holds every `exams:*` action individually and `exams:decode` stays a deliberate, separate grant. The two platform roles (`super_admin`, `support_agent`) are never cloned into a tenant; `super_admin` carries no permission rows at all because the `users.is_super_admin` flag short-circuits `has()`.

## 1. Roles

### 1.1 Platform roles

| Role | Description |
|---|---|
| super_admin | Operates the platform: institutions, plans, features, impersonation (audited), integrations health. |
| support_agent | Read-only across institutions with masked PII; can open tenant support tickets; cannot write. |

### 1.2 Institution roles (seeded per tenant)

| Role | Scope default | Description |
|---|---|---|
| institution_admin | institution | Full administrative control inside the tenant (not feature enablement beyond what the platform allows). |
| vice_chancellor / principal | institution | Executive read-all + high-level approvals and escalations. |
| registrar | institution | Students, admissions, enrolment, transfers, holds, certificates, degrees, affiliation, statutory reports. |
| controller_of_examinations | institution | Owns examinations end-to-end; sole approver/publisher of results; degree award recommendation. |
| exam_cell | institution/college | Exam operations (registrations, hall tickets, seating, invigilation, coding, valuation assignment, result verification). No decode/publish. |
| exam_decoder | institution | Only decodes dummy numbers after finalisation (separation of duties). |
| dean | faculty | Faculty-level academic approvals, course allocation approval, regulation approval. |
| hod | department | Department academics: offerings, allocation, workload, marks verification, condonation recommendation, leave approvals. |
| class_advisor | offering/section | Registration approvals and advisee monitoring for a batch section. |
| faculty | self (+ ownership) | Teaching: attendance, marks, LMS, lesson plans, projects; own leaves/payslips/research. |
| guest_faculty | self (+ ownership) | Faculty subset (no leave/payroll self-service beyond remuneration slips). |
| external_examiner | self (assigned bundles) | Time-boxed; evaluates assigned bundles (dummy numbers) and sets question papers. |
| invigilator | self (duties) | Duty view, exam-hall attendance, malpractice reporting. |
| research_guide | self (scholars) | Guides PhD scholars: DC, progress, thesis panel. |
| research_scholar | self | PhD scholar self-service. |
| research_cell | institution | Research administration: projects, grants, incentives, ethics, MoUs, incubation, PhD administration. |
| iqac_coordinator | institution | Accreditation registry, metrics, evidence, cycles, surveys (SSS), audits. |
| obe_coordinator | institution/program | PO/PSO/CO definitions, attainment runs, CQI. |
| admissions_officer | institution/college | Admission cycles, verification, merit, counselling, offers, admit. |
| accountant | institution/college | Fees (collect/refund/reconcile), scholarships disbursement, no-dues, payroll runs, accounting, vendor bills; **view_all** on staff, leaves and staff attendance. |
| hr_officer | institution | Staff master, leave policies/approvals, staff attendance devices, payroll configuration, recruitment, appraisal, CAS. |
| placement_officer | institution/college | Companies, drives, eligibility, offers, internships, training, statistics. |
| alumni_coordinator | institution | Alumni verification, events, campaigns, donations. |
| hostel_warden | hostel | Hostel operations for assigned hostels. |
| hostel_gate_staff | hostel | Gate QR mark-out/return only. |
| librarian | institution/college | Library operations, fines, no-dues sign-off. |
| transport_manager | institution | Transport operations. |
| inventory_manager | institution/college | Stores, procurement, assets, bills. |
| estate_officer | institution | Facilities, room/equipment booking approvals, service desk, AMC. |
| security_officer | institution | Visitor & gate management, emergency alerts. |
| medical_officer | institution | Health centre records (confidential). |
| sports_officer | institution | Sports teams, events, achievements verification. |
| grievance_officer | institution | Grievance triage, SLA, committee routing. |
| discipline_committee | institution | Discipline cases and sanctions. |
| committee_secretary | committee | Meetings, minutes, resolutions, ATRs for assigned committees. |
| legal_officer | institution | Legal case register. |
| pio | institution | RTI requests. |
| receptionist | institution/college | Enquiries, visitor passes, basic lookups. |
| driver | self | Driver app (trips, GPS). |
| integration_admin | institution | Integration connections, API keys, webhooks, imports. |
| college_admin | college | Institution-admin subset scoped to one college (affiliated/constituent). |
| college_exam_coordinator | college | College-side exam data submissions and exam-centre operations. |
| auditor | institution (time-boxed) | Read-only across modules for peer teams / financial audit. |
| recruiter | self (own company) | Company user: drives, applicants (consented fields), rounds, offers. |
| learner | self | Non-degree participant (CE/value-added courses). |
| student | self | Student self-service. |
| parent | wards | Guardian self-service for consented wards. |
| alumni | self | Alumni self-service. |
| applicant | self | Application-only account (time-boxed). |
| mentor (derived) | assigned mentees | Not seeded; derived from `mentor_assignments`. |

## 2. Permission registry

Standard actions: `view` (self + ownership), `view_all` (role scope), `create`, `update`, `delete`, `approve`, `publish`, `export`, `manage` (wildcard within scope), `view_pii` (unmask). Bespoke actions listed per module.

| Module | Bespoke actions |
|---|---|
| dashboard | — |
| institutions, colleges, faculties, departments | — |
| users | reset_password, impersonate (platform only) |
| roles | assign, clone |
| features | institution_toggle |
| sessions (academic years/terms) | rollover, close, lock |
| programs, regulations, curriculum, courses, batches | clone (regulations), promote (batches) |
| offerings | allocate_faculty, bulk_create |
| registration | self, approve, allocate, override, bulk |
| timetable | generate, publish, substitute |
| attendance | mark, self, condone, edit_finalized, staff_view_all, staff_self, device_manage |
| marks | enter, verify, lock, correct |
| projects | guide, review |
| exams | configure, self, eligibility, hall_tickets, seating, invigilation, conduct, qp, qp_print, code, custody, valuation_assign, evaluate, moderate, decode, reval, malpractice |
| results | compute, verify, approve, publish, self, transcript, legacy_import |
| degrees | award, issue, convocation_manage |
| obe | configure, compute, export |
| lms | manage (own offerings), grade |
| admissions | verify, merit, allot, import, admit, refund |
| students | holds, standing, exit, transfer, undertakings, id_card, bulk_import, self |
| credit_transfers | verify, approve |
| faculty (profiles) | research, workload_manage |
| hr | service_book, recruitment, appraisal, cas, guest_manage |
| leaves | self, approve, encash |
| payroll | self, generate, approve, mark_paid, statutory |
| research | ethics, incentives, mous, incubation |
| phd | guide, dc, examine, fellowship, etd |
| fees | self, collect, refund, cancel_receipt, reconcile, structure_manage, concession |
| scholarships | verify, sanction, disburse |
| no_dues | request, approve (per department) |
| hostel | self, allot, gate, warden, roll_call, mess_manage, discipline |
| library | self, circulate, fines |
| transport | gps_ingest, driver |
| inventory | indent, approve_indent, receive, issue, asset_audit |
| procurement | quote, po_approve, bill_approve |
| accounting | post, reconcile, export |
| events | organise, certify |
| facilities | book, approve_booking, service_assign |
| health | record (confidential) |
| sports | manage |
| placement | self, drive_manage, override_eligibility, offer_manage, recruiter |
| alumni | self, verify, campaign |
| fundraising | receipt |
| mentoring | self, manage, wards, refer |
| grievances | create, triage, resolve, escalate, committee |
| discipline | decide, appeal |
| surveys | respond, analyse |
| clubs | manage, verify_hours |
| accreditation | compute, override, submit, evidence |
| governance | committees, minutes, resolutions |
| legal, rti, efile, audit_paras | — |
| affiliation | apply, inspect, decide, submit, verify_submission |
| communication | send, bulk, template_manage, emergency |
| calendar | — |
| templates | render |
| certificates | self, request_approve, issue |
| reports | run, schedule, statutory |
| analytics | — |
| audit_logs | verify_chain |
| settings | — |
| integrations | connect, api_keys, webhooks, import |
| jobs | cancel |
| website | publish |

## 3. Default role → permission map (excerpt of the seed; full map lives in `app/core/rbac/registry.py` and is regenerated into `docs/Access_Matrix.csv` by `scripts/gen_access_matrix.py`)

Every role also carries `dashboard:view`, `jobs:view|cancel` and — since Phase 03 — `institutions:view`: the institution profile, colleges, faculties, departments, academic years/terms and holidays are institution-wide readable by any member (revision `0003` back-fills the grant into roles already cloned into tenants). The platform tenant routes (`/platform/institutions`) additionally require the super-admin flag, so an institution's own `institutions:manage` never reaches them.

| Role | Grants |
|---|---|
| institution_admin | `*:manage` on all institution modules; `features:institution_toggle`; no `exams:decode` by default (assign explicitly) |
| vice_chancellor / principal | `*:view_all`; `leaves:approve`; `regulations:approve`; `degrees:award`; `governance:manage`; escalations |
| registrar | `students:manage`, `students:view_pii`, `admissions:manage`, `credit_transfers:approve`, `certificates:issue`, `results:transcript`, `degrees:award|issue|convocation_manage`, `affiliation:manage`, `sessions:manage`, `reports:statutory`, `hr:view_all`, `fees:view_all`, `hostel:view_all` |
| controller_of_examinations | `exams:manage` (all bespoke), `results:manage` (compute/verify/approve/publish/transcript), `marks:lock|correct`, `degrees:award`, `students:view_all`, `hr:view_all`, `fees:view_all` (exam fees), `reports:run` |
| exam_cell | `exams:configure|eligibility|hall_tickets|seating|invigilation|conduct|qp|qp_print|code|custody|valuation_assign|reval|malpractice`, `results:compute|verify`, `students:view_all`, `attendance:view_all` |
| exam_decoder | `exams:decode` only |
| dean | `*:view_all@faculty`, `leaves:approve@faculty`, `regulations:approve`, `offerings:allocate_faculty@faculty`, `events:approve` |
| hod | `students:view_all@department`, `hr:view_all@department`, `leaves:approve@department`, `attendance:view_all@department`, `attendance:condone` (recommend), `marks:verify`, `offerings:manage@department`, `faculty:workload_manage`, `inventory:approve_indent@department`, `governance:minutes` (BoS), `accreditation:view@department` |
| faculty | `attendance:mark|self`, `marks:enter|view`, `students:view` (ownership), `lms:manage|grade` (own), `projects:guide|review`, `timetable:view`, `leaves:self|create`, `payroll:self`, `research:manage` (self), `mentoring:manage` (own), `exams:evaluate` (when assigned), `exams:invigilation` (own duties), `surveys:analyse` (own) |
| class_advisor | faculty + `registration:approve` (advisees), `students:view` (advisees), `mentoring:manage` |
| external_examiner | `exams:evaluate`, `exams:qp` (assigned), `payroll:self` (remuneration) |
| invigilator | `exams:conduct` (own duties), `exams:malpractice` (report) |
| research_guide | faculty + `phd:guide|dc|examine` (own scholars) |
| research_scholar | `phd:self`, `students:self`, `fees:self`, `library:self` |
| research_cell | `research:manage`, `phd:manage`, `accounting:view_all` (grants), `hr:view_all` (profiles) |
| iqac_coordinator | `accreditation:manage`, `surveys:manage`, `obe:view`, `*:view_all` (aggregates), `reports:statutory` |
| obe_coordinator | `obe:manage|configure|compute|export`, `marks:view_all` |
| admissions_officer | `admissions:manage|verify|merit|allot|import|admit|refund`, `students:view_all`, `fees:view_all` (admission fees) |
| **accountant** | `fees:manage|collect|refund|cancel_receipt|reconcile|structure_manage|concession|view_all`, `scholarships:disburse`, `no_dues:approve`, `payroll:manage|self`, `accounting:manage`, `procurement:bill_approve`, `library:fines`, **`hr:view_all`**, **`leaves:view_all`**, **`leaves:self|create`**, **`attendance:staff_view_all`**, **`attendance:staff_self`**, `students:view_all`, `hostel:view_all` (fees) |
| hr_officer | `hr:manage|service_book|recruitment|appraisal|cas|guest_manage`, `leaves:manage|approve|encash`, `attendance:staff_view_all|device_manage`, `payroll:generate|statutory`, `hr:view_pii` |
| placement_officer | `placement:manage|drive_manage|override_eligibility|offer_manage`, `students:view_all`, `results:view_all` (CGPA/backlogs), `attendance:view_all` (%), `reports:run` |
| alumni_coordinator | `alumni:manage|verify|campaign`, `fundraising:manage|receipt` |
| hostel_warden | `hostel:manage|allot|gate|warden|roll_call|mess_manage|discipline`@hostel, `students:view`@hostel, `attendance:view`@hostel, `fees:view`@hostel |
| hostel_gate_staff | `hostel:gate`@hostel |
| librarian | `library:manage|circulate|fines`, `students:view_all` (members), `hr:view_all` (members), `no_dues:approve` (library) |
| transport_manager | `transport:manage` |
| inventory_manager | `inventory:manage|receive|issue|asset_audit`, `procurement:quote|po_approve` |
| estate_officer | `facilities:manage|approve_booking|service_assign`, `timetable:view_all` (rooms) |
| security_officer | `facilities:manage` (visitors/gate), `communication:emergency` |
| medical_officer | `health:manage|record` |
| sports_officer | `sports:manage`, `clubs:verify_hours` |
| grievance_officer | `grievances:triage|resolve|escalate|committee`, `students:view` (cases) |
| discipline_committee | `discipline:manage|decide|appeal`, `students:view` (cases) |
| committee_secretary | `governance:committees|minutes|resolutions`@committee |
| legal_officer | `legal:manage` · pio | `rti:manage` |
| receptionist | `admissions:create` (enquiries), `facilities:manage` (visitor passes), `students:view` (lookup, masked) |
| driver | `transport:driver` |
| integration_admin | `integrations:manage|connect|api_keys|webhooks|import`, `jobs:view_all` |
| college_admin | institution_admin grants scoped `@college` minus `regulations:approve`, `results:publish`, `degrees:award`, `features:*` |
| college_exam_coordinator | `affiliation:submit`, `exams:conduct|hall_tickets`@college, `marks:view_all`@college, `results:view_all`@college |
| auditor | `*:view_all` (read), `reports:run`, `accreditation:view` — no writes; time-boxed |
| recruiter | `placement:recruiter` (own drives) |
| learner | `students:self`, `registration:self`, `lms:view`, `fees:self`, `certificates:self` |
| student | `students:self|undertakings|id_card`, `registration:self`, `attendance:self`, `marks:view` (self), `exams:self`, `results:self`, `fees:self`, `scholarships:create`, `no_dues:request`, `hostel:self`, `library:self`, `placement:self`, `mentoring:self`, `surveys:respond`, `grievances:create`, `clubs:view`, `certificates:self`, `credit_transfers:create`, `events:view`, `alumni:self` (after exit) |
| parent | `students:view` (wards), `attendance:view` (wards), `results:view` (wards), `fees:self` (pay for wards), `hostel:view` (wards, consent), `mentoring:wards`, `surveys:respond`, `grievances:create`, `communication:view` |
| alumni | `alumni:self`, `certificates:self`, `results:transcript` (self), `placement:self` (jobs board), `fundraising:view` |
| applicant | `admissions:create` (own application), `fees:self` |

## 4. Scope rules

- `institution_admin`, `registrar`, `controller_of_examinations`, `iqac_coordinator`, `hr_officer` default to `scope_type='institution'`.
- `college_admin`, `college_exam_coordinator`, `exam_cell` (in university tenants), `admissions_officer`, `accountant`, `librarian`, `placement_officer` may be `college`-scoped; several assignments give the union.
- `dean` → `faculty`; `hod` → `department`; `class_advisor` → `offering`/section; `hostel_warden`/`hostel_gate_staff` → hostel (stored as `scope_type='self'` + `hostels.warden_staff_id` ownership); `committee_secretary` → committee.
- `external_examiner`, `auditor`, `applicant` carry `valid_from/valid_to`.
- Enforced by `allowed_scope_types(role_slug, default_scope_type)` (Phase 02): a unit-scoped template (dean → faculty, hod → department, class_advisor → offering, committee_secretary → committee, college_admin/college_exam_coordinator → college, hostel/self roles → self) may only be assigned with that scope and a `scope_id` that exists **inside the institution** (otherwise `422 VALIDATION`); institution roles may additionally be college-scoped where §4 allows it. `users.valid_from/valid_to` time-box the account itself — an expired account answers `401 UNAUTHENTICATED` ("account expired") and the Beat job `auth.expire_time_boxed_accounts` revokes its sessions.
- MFA: `security.mfa` plus the role list in `app/core/rbac/registry.py:MFA_REQUIRED_ROLES` (super_admin, controller_of_examinations, exam_decoder, registrar, institution_admin, accountant) decide who must present a TOTP code; an institution can narrow the list with `institution_settings[security.mfa_required_roles]` (the demo tenant does).

## 5. Verification (API + UI)

1. For each role in §3, log in as the seeded demo user and call the module list endpoints: expected 200 with `meta.visibility` matching the matrix; forbidden modules → 403 `PERMISSION_DENIED`.
2. Permission-matrix UI: toggling `leaves:view_all` for `accountant` off hides the *All* tab on Leaves after re-login; toggling on restores it.
3. `scripts/gen_access_matrix.py` regenerates `docs/Access_Matrix.csv` (route × role) after each phase; the diff is reviewed in the PR.
