# SeptronUniverse — Feature-Flag Registry (super-admin control of every feature)

Every module and sub-feature in SeptronUniverse is a **registered feature key**. The super admin enables or disables each key per institution; subscription plans provide defaults; the backend, web app and mobile app all gate on the same effective set. Institution admins may switch off (never on) what the platform enabled.

## 1. Mechanism

### 1.1 Code registry (source of truth)

```python
# app/core/features.py
@register_feature(
    key="hostel.leave_outpass",
    group="campus",
    name="Hostel out-pass & leave",
    description="Out-pass/leave requests with guardian OTP consent and gate QR marking.",
    default_enabled=True,
    min_plan_tier="standard",          # starter | standard | professional | university
    depends_on=["hostel.core", "comms.sms"],
    is_core=False,
)
```
- `FEATURE_REGISTRY: dict[str, FeatureDef]` is imported by routers, nav definitions and the seed script. A CI test (`test_feature_registry.py`) fails when any router `dependencies=[Depends(feature_required(...))]`, `NAV_GROUPS` item, or Flutter `moreMenuModules` entry cites an unregistered key, and when a registered key has no gate anywhere.
- `platform_features` table mirrors the registry for display (seeded/refreshed on deploy).

### 1.2 Per-tenant flags

```
institution_feature_flags ( institution_id, feature_key, platform_enabled BOOL, institution_enabled BOOL DEFAULT TRUE,
                            source (plan|override), config JSONB, set_by, set_at, UNIQUE(institution_id, feature_key) )
feature_flag_changes ( institution_id, feature_key, old JSONB, new JSONB, changed_by, changed_at, reason )
```
**Effective(key) = platform_enabled AND institution_enabled.** Missing row → the tenant's plan (`subscription_plans.enabled_features`) decides; without a subscription the registry `default_enabled` applies. Implemented in Phase 02 (`app/services/feature_service.py`): every change writes `feature_flag_changes`, is audited, emits `feature_flag.changed` (consumer `features.invalidate_cache`) and drops the Redis key `features:{institution}` immediately; core keys are immutable (409), enabling a key auto-enables its `depends_on` chain only with `confirm_dependencies=true`, and disabling a key that enabled features depend on answers `409 RULE_VIOLATION` listing the dependants.

### 1.3 Plans
`subscription_plans.enabled_features[]` are applied on onboarding and plan change (rows `source='plan'`). Overrides (`source='override'`) survive plan changes and are shown as "overridden" in the UI. A key above the plan's tier can still be enabled by override (super admin decision).

### 1.4 Enforcement
| Layer | Rule |
|---|---|
| Backend routers | `api_router.include_router(hostel_router, dependencies=[Depends(feature_required("hostel.core"))])`; sub-feature keys on individual routes. Disabled → `403 {code:"FEATURE_DISABLED", feature:"hostel.core"}`. |
| Celery / Beat | Tasks call `features.is_enabled(institution_id, key)` before acting; Beat jobs skip disabled tenants; notifications for disabled features are suppressed. |
| `/auth/me` | returns `features: string[]` (effective keys) alongside `permissions[]`. |
| Web | `useFeature(key)`, `<FeatureRoute feature>`, `<FeatureGuard feature>`; `NAV_GROUPS` items carry `feature`; disabled features are hidden (an admin-only hint "enabled by your plan / disabled by super admin" appears in Settings → Features). |
| Mobile | `AuthState.hasFeature(key)`; `moreMenuModules`/tabs carry `feature`; disabled screens are unregistered. |
| Dependencies | Enabling a key auto-enables `depends_on` after confirmation; disabling a key that others depend on is blocked with the list; `is_core` keys cannot be disabled. |

### 1.5 Super-admin UI
- **Institutions → :id → Features**: grouped toggles with search, plan badge, "apply plan defaults", "diff vs plan", per-feature `config` editor (limits, provider, thresholds), change log.
- **Platform → Feature matrix**: institutions × features grid with bulk enable/disable and CSV export.
- **Institution admin → Settings → Features**: read-only view of platform state + their own on/off switch per non-core key.

### 1.6 Verification (API + UI, per phase)
1. `GET /auth/me` for a user of an institution with `X` disabled → `features` excludes `X`.
2. Calling any `X`-gated endpoint → `403 FEATURE_DISABLED`.
3. Web: nav item and route hidden; deep link shows "feature not enabled". Mobile: More grid excludes the module.
4. Enable `X` in super admin → all three become available without redeploy (flags cached ≤ 60 s in Redis, invalidated by domain event `feature_flag.changed`).

## 2. Registry

Columns: **Key** · **Name** · **What it gates** · **Default** (on/off) · **Tier** (starter/standard/professional/university) · **Depends on**.

### 2.1 Core & security (`core.*` are non-toggleable)

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| core.auth | Authentication | login, OTP, refresh, password flows | on | starter | — |
| core.rbac | Roles & permissions | roles, permission matrix, scopes | on | starter | — |
| core.institution | Institution structure | institution profile, colleges, departments | on | starter | — |
| core.settings | Settings | settings k/v, branding | on | starter | — |
| core.audit_logs | Audit logs | audit middleware & UI | on | starter | — |
| core.dashboard | Dashboards | role dashboards | on | starter | — |
| core.notifications_inapp | In-app notifications | bell, inbox, WebSocket | on | starter | — |
| core.background_jobs | Background jobs | jobs table & tray | on | starter | — |
| security.mfa | Multi-factor auth | TOTP for privileged roles | on | starter | — |
| security.sso | Single sign-on | OIDC/SAML login | off | professional | integrations.sso |
| security.ip_allowlist_exam_ops | IP allow-list for exam ops | restrict decode/publish to IPs | off | professional | — |
| security.session_management | Session management | active sessions, revoke, login history | on | starter | — |
| privacy.dpdp_consent | DPDP consent | consent records & banners | on | starter | — |
| privacy.data_subject_requests | Data-subject requests | export/erasure requests | on | standard | privacy.dpdp_consent |
| i18n.web | Web localisation | language switch on web | off | standard | — |

### 2.2 Institution

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| institution.multi_college | Multiple colleges/campuses | college switcher, college scopes | off | university | — |
| institution.faculties | Faculties/schools | faculty layer between college and department | off | standard | — |
| institution.holidays | Holiday calendar | holidays master | on | starter | — |
| institution.themes | Themes & branding | colour themes, table styles, logos | on | starter | — |
| institution.number_sequences_custom | Custom number formats | editable patterns for reg/hall-ticket/certificate numbers | on | standard | — |

### 2.3 Academics

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| academics.programs | Programmes | programme master | on | starter | — |
| academics.regulations | Regulations | versioned regulations & rules | on | starter | academics.programs |
| academics.curriculum | Curriculum structure | structure terms, curriculum courses | on | starter | academics.regulations |
| academics.elective_baskets | Elective baskets | baskets, choice forms | on | starter | academics.curriculum |
| academics.minors_honours | Minors & honours | minor programmes, honours tracks | off | standard | academics.elective_baskets |
| academics.value_added_courses | Value-added / certificate courses | VAC/CE courses & open enrolment | on | standard | academics.programs |
| academics.credit_transfer_mooc | MOOC / credit transfer | credit_transfers workflow | on | standard | academics.curriculum |
| academics.nep_exit_reentry | NEP multiple entry/exit | exit points, exit awards, re-entry | on | standard | degrees.certificates |
| academics.abc_apaar | ABC / APAAR | APAAR ids, ABC ledger | on | standard | integrations.digilocker_nad |
| academics.bos_approval_workflow | BoS approval workflow | regulation approval via committees | off | professional | workflow.engine, governance.committees |
| academics.public_catalog | Public course catalogue | `/catalog` pages | on | standard | website.core |

### 2.4 Students

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| students.core | Student records | student master, enrolments, term records | on (core) | starter | — |
| students.guardians_portal | Guardian portal | guardian users, consent | on | starter | portals.parent |
| students.documents | Student documents | document uploads/verification | on | starter | — |
| students.undertakings | Undertakings & consents | e-accept of affidavits | on | standard | documents.templates |
| students.id_cards | ID cards | ID card generation | on | starter | documents.templates |
| students.bulk_import | Bulk import | CSV/XLSX student import | on | starter | — |
| students.holds | Holds | student_holds & gates | on | standard | — |
| students.academic_standing | Academic standing | standing rules & flags | on | standard | results.processing |
| students.international_office | International students | passport/visa/FRRO tracking | off | standard | — |
| students.transfers_migration | Transfers & migration | transfer requests, certificates | on | standard | documents.templates |
| students.self_service_profile | Self-service profile | student edits own contact/photo | on | starter | portals.student |

### 2.5 Admissions

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| admissions.cycles | Admission cycles | cycles, cycle programmes | on | starter | — |
| admissions.online_application | Online application | public apply portal | on | starter | admissions.cycles |
| admissions.entrance_import | Entrance/counselling import | CSV import of ranks/allotments | on | standard | admissions.cycles |
| admissions.merit_lists | Merit lists | merit computation & publish | on | starter | admissions.cycles |
| admissions.seat_matrix | Seat matrix | quota × category seats | on | starter | admissions.cycles |
| admissions.counselling_allotment | Counselling & allotment | rounds, choice filling, allotment | on | standard | admissions.seat_matrix, admissions.merit_lists |
| admissions.document_verification | Document verification | verification queue | on | starter | admissions.cycles |
| admissions.offers | Admission offers | offer letters | on | starter | documents.templates |
| admissions.lateral_entry | Lateral entry | lateral intake handling | on | standard | admissions.cycles |
| admissions.enquiry_crm | Enquiry CRM | enquiries pipeline | on | standard | comms.sms |
| admissions.open_enrolment | Open enrolment | non-degree learner admission | off | standard | academics.value_added_courses |
| admissions.refunds | Admission refunds | withdrawal refund rules | on | standard | fees.refunds |

### 2.6 Registration, timetable, attendance

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| registration.core | Course registration | windows, registrations | on | starter | academics.curriculum |
| registration.self_service | Student self-registration | student cart | on | starter | registration.core, portals.student |
| registration.advisor_approval | Advisor approval | approval queue | on | standard | registration.core, workflow.engine |
| registration.elective_allocation | Elective allocation | choice forms, allocation runs | on | standard | academics.elective_baskets |
| registration.waitlist | Waitlists | offering waitlists | on | standard | registration.core |
| registration.add_drop | Add/drop | add-drop windows | on | starter | registration.core |
| registration.arrears | Arrear registration | arrears register & windows | on | starter | results.processing |
| registration.audit_courses | Audit courses | non-credit audit | off | standard | registration.core |
| registration.overrides | Registration overrides | admin overrides with reason | on | standard | registration.core |
| timetable.core | Timetable | timetables, entries, sessions | on | starter | — |
| timetable.rooms | Rooms & buildings | room master | on | starter | — |
| timetable.substitutions | Substitutions | substitution requests, auto-flag | on | standard | hr.leaves |
| timetable.auto_generate | Auto timetable | constraint solver | off | professional | timetable.core |
| timetable.ical | iCal export | personal/section iCal | on | starter | timetable.core |
| attendance.core | Attendance | session attendance | on | starter | timetable.core |
| attendance.qr | QR attendance | session QR check-in | on | standard | attendance.core, mobile.app |
| attendance.biometric | Biometric devices | punch ingest | off | standard | integrations.biometric_rfid |
| attendance.geo_app | Geo-fenced app attendance | GPS-verified marking | off | standard | mobile.app |
| attendance.rfid | RFID | RFID punches | off | standard | integrations.biometric_rfid |
| attendance.on_duty | On-duty | OD requests | on | starter | attendance.core |
| attendance.condonation | Condonation | condonation workflow + fee | on | standard | attendance.core, workflow.engine |
| attendance.eligibility_detention | Eligibility & detention | eligibility snapshots, detention lists | on | starter | attendance.core |
| attendance.guardian_alerts | Guardian alerts | absence notifications | on | starter | comms.sms |
| attendance.staff | Staff attendance | staff check-in, devices | on | standard | hr.staff |
| attendance.offline_mobile | Offline attendance | mobile write queue | on | standard | mobile.offline |

### 2.7 Fees

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| fees.core | Fee management | heads, structures, invoices, payments | on | starter | — |
| fees.structures_by_quota | Quota/category structures | structure dimensions | on | starter | fees.core |
| fees.instalments | Instalments | instalment schedules | on | starter | fees.core |
| fees.auto_late_fee | Automatic late fee | Beat late-fee posting | on | standard | fees.instalments |
| fees.online_payment | Online payment | gateway checkout | on | starter | integrations.payments |
| fees.upi_qr | UPI QR | static/dynamic UPI QR receipts | on | standard | fees.online_payment |
| fees.offline_challan_reconciliation | Offline payments | challan/NEFT/DD with UTR reconciliation | on | standard | fees.core |
| fees.discounts | Discounts & concessions | discount rules | on | starter | fees.core |
| fees.staff_ward_concession | Staff-ward concession | automatic concession for staff wards | off | standard | fees.discounts, hr.staff |
| fees.fines | Fines | fine configuration | on | starter | fees.core |
| fees.scholarships | Scholarships | scholarship applications & disbursement | on | standard | fees.core, workflow.engine |
| fees.nsp_integration | NSP integration | NSP references/exports | off | professional | integrations.nsp |
| fees.no_dues | No-dues clearance | multi-department sign-off | on | standard | workflow.engine |
| fees.refunds | Refunds | refund workflow | on | standard | fees.core |
| fees.receipt_cancellation_approval | Receipt cancellation approval | cancellation via workflow | on | standard | workflow.engine |
| fees.gst_invoicing | GST invoicing | GST fields/reports | off | standard | accounting.gst_reports |
| fees.thermal_receipts | Thermal receipts | mobile ESC/POS printing | on | standard | mobile.app |
| fees.accounting_export | Accounting export | Tally/Zoho export | off | standard | accounting.tally_export |

### 2.8 Internal assessment & LMS

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| assessment.internal_marks | Internal assessment | schemes, components, marks | on | starter | registration.core |
| assessment.question_wise_co | Question-wise CO marks | question map, question-wise entry | on | standard | obe.definitions |
| assessment.marks_workflow | Marks workflow | submit/verify/lock chain | on | starter | assessment.internal_marks |
| assessment.marks_change_requests | Marks change requests | post-lock corrections | on | standard | workflow.engine |
| assessment.projects | Projects & dissertations | project groups, reviews | on | standard | assessment.internal_marks |
| lms.content | Course content | modules, contents, views | on | standard | registration.core |
| lms.assignments | Assignments | assignments & submissions | on | standard | lms.content |
| lms.similarity_check | Similarity check | plagiarism on submissions | off | professional | integrations.plagiarism |
| lms.quizzes | Quizzes | quizzes/attempts | on | standard | lms.question_bank |
| lms.question_bank | Question bank | questions, tags, syllabus topics | on | standard | — |
| lms.blueprints_paper_builder | Blueprints & paper builder | QP generation | on | standard | lms.question_bank |
| lms.study_materials | Study materials | publishable materials | on | standard | lms.content |
| lms.discussions | Discussions | threads & posts | on | standard | lms.content |
| lms.lesson_plans | Lesson plans | lesson plans & delivery tick-off | on | standard | timetable.core |
| lms.course_files | Course files | checklist & audit | on | standard | lms.lesson_plans |
| lms.online_class_links | Online class links | Zoom/Meet links on sessions | on | standard | integrations.video_conf |
| lms.lti_moodle | LTI / Moodle | external LMS sync | off | professional | integrations.lti |

### 2.9 Examinations & results

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| exams.sessions | Exam sessions | sessions, papers, date-sheets | on | starter | registration.core |
| exams.registration_fee | Exam registration & fee | registration + fee invoice | on | starter | exams.sessions, fees.core |
| exams.eligibility_snapshot | Eligibility snapshot | apply term eligibility to registrations | on | starter | attendance.eligibility_detention |
| exams.hall_tickets | Hall tickets | PDF + QR + verify | on | starter | documents.templates |
| exams.face_verification | Face verification | face-match at hall attendance | off | professional | integrations.face_verification |
| exams.seating | Seating plans | seating generation | on | standard | timetable.rooms |
| exams.invigilation | Invigilation | duty roster, swaps, remuneration | on | standard | hr.staff |
| exams.qp_management | Question-paper management | setters, upload, scrutiny | on | standard | — |
| exams.qp_watermark_print_log | QP watermark & print log | watermarked prints, log | on | standard | exams.qp_management |
| exams.clash_detection | Clash detection | date-sheet clash checks | on | starter | exams.sessions |
| exams.online_proctored | Online / proctored exams | quiz-engine exams with proctoring | off | professional | lms.quizzes |
| exams.practical_viva | Practical / viva / dissertation | paper types & marks | on | starter | exams.sessions |
| exams.coding_dummy | Dummy-number coding | bundles, coding, decode | on | standard | exams.sessions |
| exams.double_valuation | Double valuation | second valuation + discrepancy | off | professional | exams.coding_dummy |
| exams.onscreen_valuation | Onscreen valuation | scanned scripts UI | off | professional | exams.coding_dummy |
| exams.moderation | Moderation | moderation actions | on | standard | exams.coding_dummy |
| exams.grace | Grace marks | grace rules | on | standard | results.processing |
| exams.relative_grading | Relative grading | z-score grading | off | professional | results.processing |
| exams.external_examiners | External examiners | time-boxed accounts, remuneration | on | standard | exams.coding_dummy |
| exams.remuneration | Exam remuneration | payroll lines for exam work | on | standard | hr.payroll |
| exams.script_custody | Script custody & retention | custody log, destruction register | on | standard | exams.coding_dummy |
| results.processing | Result processing | runs, grades, SGPA/CGPA | on | starter | exams.sessions |
| results.publication_portal | Result publication | student/public result views | on | starter | results.processing |
| results.grade_cards | Grade cards | grade card PDFs | on | starter | documents.templates |
| results.transcripts | Transcripts | transcript requests | on | standard | documents.templates |
| results.revaluation | Revaluation | reval requests | on | standard | results.processing |
| results.photocopy | Photocopy / retotaling | photocopy & retotaling requests | on | standard | results.revaluation |
| results.challenge_valuation | Challenge valuation | third-party challenge | off | professional | results.revaluation |
| results.supplementary | Supplementary / arrear exams | supplementary sessions | on | starter | exams.sessions |
| results.malpractice | Malpractice | cases, hearings, punishments | on | standard | governance.committees |
| results.rank_lists | Rank lists & medals | ranks, medals | on | standard | results.processing |
| results.legacy_import | Legacy result import | import past results | on | standard | data.migration_toolkit |
| results.sms_masked_notify | Masked result SMS | SMS with masked details | on | standard | comms.sms |

### 2.10 OBE & degrees

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| obe.definitions | OBE definitions | PEO/PO/PSO/CO, CO-PO matrix | on | standard | academics.curriculum |
| obe.attainment | Attainment computation | CO/PO runs | off | professional | obe.definitions, assessment.question_wise_co |
| obe.indirect_surveys | Indirect attainment | survey-linked attainment | off | professional | surveys.core |
| obe.cqi | CQI register | CQI actions | off | professional | obe.attainment |
| obe.nba_export | NBA SAR export | criterion-3 exports | off | professional | obe.attainment |
| degrees.eligibility | Degree eligibility | eligibility engine | on | standard | results.processing |
| degrees.convocation | Convocation | events & registrations | on | standard | events.core |
| degrees.certificates | Degree certificates | awards, serials, PDFs | on | standard | documents.templates |
| degrees.provisional | Provisional certificates | provisional issue | on | standard | degrees.certificates |
| degrees.esign | e-Sign certificates | DSC/eSign adapter | off | professional | integrations.esign |
| degrees.digilocker_nad | DigiLocker / NAD push | credential push | off | professional | integrations.digilocker_nad |
| degrees.abc_push | ABC credit push | ledger push | off | professional | academics.abc_apaar |
| degrees.verification_portal | Verification portal | public `/verify` | on | standard | degrees.certificates |

### 2.11 HR, research & PhD

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| hr.staff | Staff management | staff master, documents | on | starter | — |
| hr.faculty_profiles | Faculty profiles | academic ids, cadre, guide status | on | starter | hr.staff |
| hr.guest_faculty | Guest / visiting faculty | hourly remuneration | on | standard | hr.payroll |
| hr.leaves | Leave management | types, requests, balances | on | starter | workflow.engine |
| hr.leave_encashment | Leave encashment | encashment rules | off | standard | hr.leaves, hr.payroll |
| hr.payroll | Payroll | payroll runs, payslips | on | standard | hr.staff |
| hr.statutory_payroll | Statutory payroll | PF/ESI/PT/TDS, Form 16 | on | standard | hr.payroll |
| hr.loans_advances | Loans & advances | loan schedules | off | standard | hr.payroll |
| hr.staff_attendance | Staff attendance | check-in, devices | on | standard | hr.staff |
| hr.service_book | Service book | service records | on | standard | hr.staff |
| hr.recruitment | Recruitment | postings → appointment | off | professional | workflow.engine |
| hr.reservation_roster | Reservation roster | roster validation | off | professional | hr.recruitment |
| hr.appraisal_pbas | Appraisal (PBAS) | self-appraisal workflow | off | professional | workflow.engine |
| hr.cas_promotions | CAS promotions | CAS applications | off | professional | hr.appraisal_pbas |
| hr.workload | Workload | workload computation & norms | on | standard | registration.core |
| research.publications | Publications | publication records | on | standard | hr.faculty_profiles |
| research.patents | Patents | patent records | on | standard | hr.faculty_profiles |
| research.projects_grants | Projects & grants | funded projects, utilisation | on | standard | accounting.grants_ledger |
| research.consultancy | Consultancy | consultancy records | on | standard | hr.faculty_profiles |
| research.ethics_committee | Ethics committees | IEC/IAEC approvals | off | professional | governance.committees |
| research.seed_grants_incentives | Seed grants & incentives | incentive workflows | off | professional | workflow.engine |
| research.fdp | FDP & development | FDP records | on | standard | hr.faculty_profiles |
| research.mous_collaborations | MoUs & collaborations | MoU register | on | standard | — |
| research.incubation | Incubation & start-ups | incubation register | off | professional | — |
| research.api_score | API score | API/CAS computation | off | professional | research.publications |
| phd.core | PhD scholars | scholar records, guides | off | professional | academics.programs |
| phd.coursework | PhD coursework | coursework registration/results | off | professional | phd.core |
| phd.dc_meetings | Doctoral committee | DC constitution & meetings | off | professional | phd.core |
| phd.progress_reports | Progress reports | half-yearly reports | off | professional | phd.core |
| phd.fellowships | Fellowships | fellowship disbursement | off | professional | phd.core, hr.payroll |
| phd.extensions_guide_change | Scholar requests | extension, guide change | off | professional | workflow.engine |
| phd.thesis_plagiarism | Thesis & plagiarism | submissions, similarity | off | professional | integrations.plagiarism |
| phd.external_examiners | Thesis examiners | examiner panel | off | professional | phd.thesis_plagiarism |
| phd.viva | Viva-voce | viva scheduling | off | professional | phd.external_examiners |
| phd.etd_upload | ETD upload | Shodhganga/institutional | off | professional | integrations.koha_dspace_shodhganga |
| phd.scholar_portal | Scholar portal | scholar self-service | off | professional | phd.core |

### 2.12 Campus services

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| library.core | Library | catalogue, circulation | on | starter | — |
| library.opac | OPAC | public catalogue search | on | starter | library.core |
| library.eresources | E-resources | journals, e-books | on | standard | library.core |
| library.rfid_barcode | Barcode / RFID | scanning | on | standard | library.core |
| library.fines | Library fines | fine rules & invoices | on | starter | fees.core |
| library.inter_library_loan | Inter-library loan | ILL requests | off | professional | library.core |
| library.koha_sync | Koha / DSpace sync | external library sync | off | professional | integrations.koha_dspace_shodhganga |
| hostel.core | Hostel | hostels, rooms, allocations | off | standard | — |
| hostel.mess | Mess | plans, subscriptions, attendance | off | standard | hostel.core |
| hostel.mess_billing | Mess billing | monthly bills | off | standard | hostel.mess, fees.core |
| hostel.leave_outpass | Out-pass & leave | requests, guardian OTP | off | standard | hostel.core, comms.sms |
| hostel.gate_qr | Gate QR | mark-out/return scanning | off | standard | hostel.leave_outpass, mobile.app |
| hostel.night_roll_call | Night roll call | roll-call attendance | off | standard | hostel.core |
| hostel.room_change | Room change | change requests | off | standard | hostel.core |
| hostel.visitors | Visitors | visitor log | off | standard | hostel.core |
| hostel.complaints | Complaints | complaints → service desk | off | standard | facilities.service_desk |
| hostel.discipline | Hostel discipline | disciplinary records & fines | off | standard | hostel.core |
| hostel.staff_quarters | Staff quarters | quarters allocation | off | standard | hr.staff |
| transport.core | Transport | vehicles, routes, allocations | off | standard | — |
| transport.gps_live | Live GPS | devices, trips, live map | off | standard | transport.core |
| transport.staff | Staff transport | staff allocations | off | standard | transport.core |
| transport.fees | Transport fees | route fees | off | standard | fees.core |
| inventory.core | Inventory | stores, items, issues | off | standard | — |
| inventory.procurement | Procurement | indents, quotations, POs, GRN | off | standard | workflow.engine |
| inventory.vendor_portal | Vendor portal | supplier registration/quotes | off | professional | inventory.procurement |
| inventory.lab_consumables | Lab consumables | chemicals, safety data | off | standard | inventory.core |
| inventory.assets | Assets | asset register, depreciation | off | standard | inventory.core |
| inventory.asset_qr | Asset QR tags | QR labels & audits | off | standard | inventory.assets |
| inventory.bills | Vendor bills | bill tracking | off | standard | inventory.procurement |
| inventory.vendor_store | Vendor store | campus store (Orbit vendor inventory) | off | standard | inventory.core |
| accounting.core | Accounting | income/expense, ledgers | off | standard | — |
| accounting.budgets | Budgets | department budgets | off | standard | accounting.core |
| accounting.grants_ledger | Grants ledger | project ledgers | off | professional | accounting.core |
| accounting.gst_reports | GST reports | GST returns data | off | standard | accounting.core |
| accounting.tally_export | Tally / Zoho export | vouchers export | off | standard | accounting.core |

### 2.13 Events, facilities, communication, documents

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| events.core | Events | events, registrations | on | standard | — |
| events.certificates | Event certificates | participation certificates | on | standard | documents.templates |
| facilities.room_booking | Room booking | venue booking | on | standard | timetable.rooms |
| facilities.equipment_booking | Equipment booking | asset booking | off | standard | inventory.assets |
| facilities.service_desk | Service desk | maintenance/IT tickets | on | standard | — |
| facilities.lost_found | Lost & found | register | off | standard | facilities.service_desk |
| facilities.amc | AMC contracts | AMC register | off | standard | inventory.assets |
| facilities.visitor_gate | Visitor & gate | campus passes | off | standard | — |
| facilities.emergency_sos | Emergency / SOS | SOS alerts, broadcast | off | standard | mobile.app, comms.push |
| facilities.health_centre | Health centre | visits, insurance | off | standard | — |
| facilities.counselling_appointments | Counselling appointments | slots & bookings | off | standard | mentoring.counselling |
| facilities.sports | Sports | teams, events, participation | off | standard | — |
| facilities.canteen_wallet | Canteen & wallet | prepaid wallet | off | professional | integrations.payments |
| comms.sms | SMS | SMS channel | on | starter | — |
| comms.whatsapp | WhatsApp | WhatsApp channel | off | standard | — |
| comms.email | Email | email channel | on | starter | — |
| comms.push | Push | FCM/WebPush | on | starter | — |
| comms.announcements | Announcements | announcements | on | starter | — |
| comms.announcement_ack | Acknowledgements | read receipts | on | standard | comms.announcements |
| comms.emergency_broadcast | Emergency broadcast | all-channel blast | off | standard | comms.sms |
| comms.bulk_campaigns | Bulk campaigns | segments, campaigns | on | standard | comms.sms |
| comms.scheduled_sends | Scheduled sends | scheduling | on | standard | comms.bulk_campaigns |
| comms.whatsapp_bot | WhatsApp bot | chat flows | off | professional | comms.whatsapp |
| comms.ai_assistant | AI assistant | LLM assistant | off | professional | — |
| comms.preferences | Notification preferences | per-user preferences | on | starter | — |
| calendar.core | Calendar | academic calendar, events | on | starter | — |
| calendar.ical | iCal export | institution feeds | on | starter | calendar.core |
| calendar.personal_feed | Personal iCal feed | per-user token feeds | on | standard | calendar.core |
| workflow.engine | Workflow engine | approval workflows | on | starter | — |
| workflow.delegation | Delegation | delegate approvals | on | standard | workflow.engine |
| documents.templates | Document templates | builder/renderer | on | starter | — |
| documents.bilingual_templates | Bilingual templates | dual-language documents | off | standard | documents.templates |
| documents.certificate_requests | Certificate requests | self-service with fee/workflow | on | standard | workflow.engine, fees.core |
| documents.bulk_generation | Bulk generation | jobs for bulk PDFs | on | starter | core.background_jobs |
| documents.serial_registers | Serial registers | numbered registers | on | standard | documents.templates |
| documents.watermark_signed_links | Watermark & signed links | watermarked downloads | on | standard | documents.templates |

### 2.14 Engagement & quality

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| mentoring.core | Mentoring | assignments, sessions | on | standard | — |
| mentoring.appointment_slots | Mentor slots | bookable slots | on | standard | mentoring.core |
| mentoring.early_warning | Early warning | risk flags | off | professional | analytics.early_warning |
| mentoring.counselling | Counselling | referrals | on | standard | mentoring.core |
| grievances.core | Grievances | tickets, SLA | on | standard | workflow.engine |
| grievances.anonymous | Anonymous grievances | public form | on | standard | grievances.core |
| grievances.committees | Grievance committees | ICC/anti-ragging routing | on | standard | governance.committees |
| discipline.core | Discipline | cases, sanctions | on | standard | governance.committees |
| surveys.core | Surveys | surveys & responses | on | standard | — |
| surveys.sss | Student satisfaction survey | SSS template | on | standard | surveys.core |
| clubs.core | Clubs & activities | clubs, events | on | standard | — |
| clubs.activity_hours_credits | Activity hours → credits | NSS/NCC hours ledger | off | standard | clubs.core |
| clubs.achievements | Achievements | verified achievements | on | standard | clubs.core |
| placement.core | Placement | companies, drives, offers | on | standard | — |
| placement.recruiter_portal | Recruiter portal | company users | off | professional | placement.core |
| placement.internships | Internships | internship records, NOC | on | standard | placement.core |
| placement.training | Training programmes | training & attendance | on | standard | placement.core |
| placement.resume_builder | Resume builder | structured resumes | on | standard | placement.core |
| alumni.core | Alumni | profiles, directory | on | standard | — |
| alumni.portal | Alumni portal | self-service | on | standard | alumni.core |
| alumni.jobs_board | Alumni jobs board | job posts | off | standard | alumni.portal |
| alumni.fundraising | Fundraising | campaigns | off | professional | alumni.core |
| alumni.donations_80g | Donations & 80G | receipts | off | professional | alumni.fundraising |
| accreditation.naac | NAAC | NAAC framework & metrics | off | professional | — |
| accreditation.nba | NBA | NBA framework | off | professional | obe.attainment |
| accreditation.nirf | NIRF | NIRF data | off | professional | — |
| accreditation.aishe | AISHE | AISHE data | on | standard | — |
| accreditation.aicte_ugc | AICTE / UGC returns | approval data packs | off | professional | — |
| accreditation.evidence_repo | Evidence repository | evidence files | off | professional | — |
| accreditation.iqac_cycles | IQAC cycles | cycles & narratives | off | professional | accreditation.naac |
| accreditation.audit_registers | Audit registers | academic/green/gender audits | off | professional | — |
| governance.committees | Committees | committees & members | on | standard | — |
| governance.minutes | Meetings & minutes | meetings, resolutions, ATR | on | standard | governance.committees |
| governance.legal | Legal cases | case register | off | professional | — |
| governance.rti | RTI | RTI requests | off | professional | — |
| governance.audit_paras | Audit paras | statutory/AG audit paras | off | professional | accreditation.audit_registers |
| governance.efile | e-File | file movement & noting | off | professional | — |
| governance.policies | Policies | policy repository | on | standard | — |
| affiliation.core | Affiliation | college affiliation records | off | university | institution.multi_college |
| affiliation.inspections | Inspections | inspection workflow | off | university | affiliation.core |
| affiliation.data_submissions | College data submissions | term submissions | off | university | affiliation.core |
| affiliation.exam_centres | Exam centres | centres per session | off | university | exams.sessions |
| affiliation.fees | Affiliation fees | fee schedules | off | university | fees.core |

### 2.15 Platform

| Key | Name | What it gates | Default | Tier | Depends on |
|---|---|---|---|---|---|
| analytics.core | Analytics | chart registry, insights tabs | on | standard | — |
| analytics.early_warning | Early-warning analytics | risk scoring job | off | professional | analytics.core |
| reports.core | Reports | report registry | on | starter | — |
| reports.scheduled | Scheduled reports | schedules | on | standard | reports.core |
| reports.statutory | Statutory reports | AISHE/NIRF/AICTE/UGC/NSP | off | professional | reports.core |
| portals.student | Student portal | student portal & PWA | on | starter | — |
| portals.parent | Parent portal | parent portal | on | starter | — |
| portals.faculty | Faculty portal | faculty portal | on | starter | — |
| portals.alumni | Alumni portal | alumni portal | on | standard | alumni.core |
| portals.warden | Warden portal | warden/gate | off | standard | hostel.core |
| portals.evaluator | Evaluator portal | external evaluator | on | standard | exams.external_examiners |
| portals.scholar | Scholar portal | PhD scholar | off | professional | phd.core |
| portals.recruiter | Recruiter portal | company users | off | professional | placement.recruiter_portal |
| portals.pwa_push | PWA & web push | manifest, push | on | starter | — |
| platform.help_center | Help centre | in-app help | on | starter | — |
| platform.in_app_feedback | In-app feedback | feedback widget | on | starter | — |
| platform.guided_tours | Guided tours | onboarding tours | on | starter | — |
| platform.read_only_mode | Read-only mode | maintenance toggle | on | starter | — |
| website.core | Public website | institution site | on | starter | — |
| website.custom_domain | Custom domain | domain mapping | off | standard | website.core |
| website.course_catalog | Catalogue pages | public catalogue | on | standard | academics.public_catalog |
| website.enquiry | Website enquiry | enquiry forms | on | starter | admissions.enquiry_crm |
| mobile.app | Mobile app | Flutter app access | on | starter | — |
| mobile.offline | Offline mode | read cache + write queue | on | standard | mobile.app |
| mobile.biometric_lock | Biometric app lock | device biometrics | on | starter | mobile.app |
| mobile.tablet_layout | Tablet layouts | master-detail layouts | on | standard | mobile.app |
| integrations.api_keys_webhooks | API keys & webhooks | outbound integration | off | professional | — |
| integrations.payments | Payment gateways | Razorpay/PayU/Cashfree/Stripe | on | starter | — |
| integrations.sso | SSO providers | OIDC/SAML | off | professional | — |
| integrations.lti | LTI 1.3 | LMS interoperability | off | professional | — |
| integrations.video_conf | Video conferencing | Zoom/Meet | off | standard | — |
| integrations.digilocker_nad | DigiLocker / NAD / ABC | government depositories | off | professional | — |
| integrations.nsp | NSP | scholarship portal | off | professional | — |
| integrations.swayam_nptel | SWAYAM / NPTEL | MOOC credit import | off | standard | — |
| integrations.scopus_crossref_orcid | Scopus / Crossref / ORCID | publication lookup | off | professional | — |
| integrations.plagiarism | Plagiarism checkers | DrillBit/Urkund/Turnitin | off | professional | — |
| integrations.koha_dspace_shodhganga | Koha / DSpace / Shodhganga | library & repositories | off | professional | — |
| integrations.biometric_rfid | Biometric / RFID devices | device protocols | off | standard | — |
| integrations.face_verification | Face verification | face-match adapter | off | professional | — |
| integrations.esign | eSign / DSC | digital signatures | off | professional | — |
| integrations.aadhaar_ekyc | Aadhaar eKYC | identity verification | off | professional | — |
| integrations.email_domain_auth | Email domain auth | SPF/DKIM/DMARC per tenant domain | off | standard | comms.email |
| integrations.workspace_provisioning | Workspace provisioning | Google/M365 accounts | off | professional | integrations.sso |
| data.migration_toolkit | Migration toolkit | templates, validation, apply, rollback | on | standard | core.background_jobs |
| data.export_portability | Data export | tenant/user exports | on | standard | core.background_jobs |
| search.global | Global search | tsvector search | on | starter | — |

## 3. Plan defaults (illustrative)

| Tier | Includes |
|---|---|
| starter | all `starter` keys with default on |
| standard | starter + all `standard` keys with default on |
| professional | standard + `professional` keys (default on where marked, else off but enable-able) |
| university | professional + `university` keys (`institution.multi_college`, `affiliation.*`) |

Keys with default **off** are never auto-enabled by a plan; they are switched on per institution in the Features tab (their `depends_on` chain is enabled automatically after confirmation).

## 4. Seed & drift rules

- `Database_Schema.sql` seeds `platform_features` from this table; `scripts/check_feature_registry.py` diffs the code registry against the doc and the DB seed in CI.
- A phase prompt must list the keys it introduces under **Feature keys**; the registry entry is part of that phase's deliverables.
