# SeptronUniverse — Glossary & Orbit → Universe Mapping

## 1. Higher-education glossary

| Term | Meaning in SeptronUniverse |
|---|---|
| Institution | The tenant: a university or a standalone college. Every table carries `institution_id`. |
| College | A constituent/affiliated/autonomous college, campus or study centre inside an institution (`colleges.college_type`). A standalone college is an institution with one auto-created college. |
| Faculty (unit) | Optional grouping of departments ("School of Engineering"); headed by a dean. Not to be confused with *faculty* = teaching staff. |
| Department | Academic or administrative unit; owns programmes and courses; headed by an HOD. |
| Programme | A degree/diploma/certificate offering (B.Tech CSE, MBA, PhD Physics) with level, mode, duration and intake. |
| Regulation | A versioned rule set (R2024) governing a programme cohort: attendance, passing, grading, grace, exit points. Students are pinned to the regulation of their admission year. |
| Curriculum / programme structure | Term-wise list of courses (with credit buckets) under a programme-regulation. |
| Course | A subject unit (code, title, L-T-P-C, type). Owned by a regulation; cloned per regulation. |
| L-T-P-C | Lecture-Tutorial-Practical hours per week and Credits. |
| Elective basket | A group of courses from which a student picks *n* (PE/OE/minor/honours/MOOC). |
| Batch | Admission-year cohort of a programme (2024-BTECH-CSE); has sections (class groups) and a current term. |
| Academic year / term | 2025-26 / Odd semester; terms carry registration, add-drop and instruction dates and a status machine. |
| Course offering | A course taught in a term by a department (with section code, faculty, seats). Timetable, attendance, marks and results hang off offerings. |
| Registration | A student's per-term selection of offerings (cart) subject to credit limits, prerequisites, seats, holds and advisor approval. |
| Arrear / backlog | A failed course awaiting a passing attempt; tracked in `student_arrears`. |
| Hold | A block placed on a student (registration/exam/transcript/graduation/hostel) until released. |
| Academic standing | good / warning / probation / dismissal computed from regulation rules at result publish. |
| CIA / CAT | Continuous Internal Assessment / Continuous Assessment Test — internal marks components. |
| ESE | End-Semester Examination (external component). |
| Assessment scheme | Per-regulation split of CIA/ESE with components, weights, best-of rules and pass rules. |
| Exam session | A conducted examination cycle (Nov/Dec 2025 ESE; supplementary; arrear) with papers, registrations, hall tickets, valuation and results. |
| Hall ticket | Admit card with photo and signed QR; issued only to eligible, fee-paid, hold-free registrations. |
| Dummy number | Anonymised identifier assigned to an answer script during valuation; decoded by a separate role after finalisation. |
| Double valuation | Two independent evaluations; discrepancy above a threshold triggers a third. |
| Moderation | COE-approved adjustment (scale/grace/cap) applied to a paper's marks. |
| SGPA / CGPA | Semester / Cumulative Grade Point Average = Σ(credits × grade points) / Σ credits. |
| Result version | Every change to a published result creates a new immutable version row; the previous one becomes `superseded`. |
| Revaluation / photocopy / challenge | Post-result services with fees; applied only above a minimum delta. |
| Malpractice | Exam misconduct case with inquiry, hearing, punishment and appeal. |
| Condonation | Approval (with fee) to treat attendance between the floor and the threshold as eligible. |
| Detention | Ineligibility to appear for exams (attendance/CIA) or to be promoted (backlogs). |
| NEP multiple entry/exit | Award of certificate/diploma/degree at defined exit points; re-entry with carried credits. |
| ABC / APAAR | Academic Bank of Credits / Automated Permanent Academic Account Registry (12-digit student id). |
| DigiLocker / NAD | Government digital credential depositories to which grade cards/degrees are pushed. |
| OBE | Outcome-Based Education: PEO (programme educational objectives), PO (programme outcomes), PSO (programme-specific outcomes), CO (course outcomes), CO-PO mapping, attainment, CQI. |
| NAAC / NBA / NIRF / AISHE | Accreditation (institution), accreditation (programme), ranking framework, all-India survey — each a metrics framework in the accreditation registry. |
| IQAC | Internal Quality Assurance Cell — owns accreditation cycles, AQAR and surveys. |
| Affiliation | Relationship between a university and colleges that run its programmes and exams. |
| College data submission | Term-wise data a college submits to its university (registrations, CIA, eligibility, exam registrations). |
| BoS / Academic Council / Senate | Governance committees whose resolutions approve regulations, results and degrees. |
| DC / RAC | Doctoral (Research Advisory) Committee for a PhD scholar. |
| ETD / Shodhganga | Electronic thesis deposit; INFLIBNET repository. |
| PBAS / API / CAS | Performance-Based Appraisal System / Academic Performance Indicator score / Career Advancement Scheme. |
| Regulatory pack | Country pack (IN, GENERIC) supplying categories, grading defaults, id formats, metric definitions and statutory templates. |
| Feature key | Registered switch controlling a module/sub-feature per institution. |
| Scope | Unit (institution/college/faculty/department/program/offering/self) attached to a role assignment. |
| Visibility | self / ownership / scoped / view_all rule that filters rows for a user. |

## 2. Orbit → Universe rename table

### 2.1 Concepts and identifiers

| Orbit | Universe | Notes |
|---|---|---|
| School | Institution (+ College) | tenant root; sub-tenant |
| `school_id` | `institution_id` (+ `college_id` where scoped) | on every table; RLS |
| `X-School-Id` / `X-School-Slug` | `X-Institution-Id` / `X-Institution-Slug` (+ `X-College-Id`) | headers |
| `SchoolContextMiddleware` | `InstitutionContextMiddleware` | |
| `get_school_id` | `get_institution_id` (+ `get_college_scope`) | dependencies |
| `school_feature_flags` (16 keys) | `institution_feature_flags` (registry ≈ 230 keys) | |
| Academic year | Academic year + term (status machine) | |
| Class / section | Programme-batch / batch section | |
| Subject | Course (versioned per regulation) | |
| Class-subject / timetable slot | Course offering / timetable entry (offering-based) | |
| Teacher, class teacher | Faculty, class advisor | |
| Parent | Guardian (consent-controlled) | |
| Homework | Assignment (LMS) | |
| Lesson plan | Lesson plan (per offering) | |
| PTM | Mentoring sessions & bookings | |
| Exam (class × subject) | Exam session → exam paper (course) | |
| Admit card | Hall ticket | |
| Marks entry | Internal marks (CIA) + script valuations (ESE) | |
| Report card | Grade card | |
| Promotion | Term promotion (batch) | |
| Transfer certificate | TC / migration certificate | |
| Fee structure (class) | Fee structure (programme × regulation × batch × category × quota × term) | |
| Principal / vice-principal | Vice-chancellor / principal / dean | |
| School admin | Institution admin / college admin | |
| Accountant | Accountant (accounts officer) | same, higher-ed scope |
| Receptionist | Receptionist / admissions officer | |
| Super admin | Super admin (+ support agent) | |

### 2.2 Tables

| Orbit table(s) | Universe table(s) |
|---|---|
| schools, school_profile, school_settings | institutions, institution_profile, institution_settings (+ colleges, faculties) |
| users, password_reset_tokens | users, password_reset_tokens (+ user_sessions, mfa_secrets, login_history) |
| roles, permissions, role_permissions, user_roles | roles, permissions, role_permissions, user_roles (+ scope_type, scope_id, valid_from/to) |
| academic_years, academic_terms | academic_years, academic_terms (extended) |
| admission_form_configs, admission_forms | admission_cycles, admission_cycle_programs, seat_matrix, applicants, applicant_preferences, applicant_document_verifications, merit_lists, merit_list_entries, counselling_rounds, seat_allotments, admission_offers, enquiries |
| classes, sections, subjects, class_subjects | programs, regulations, program_regulations, program_structure_terms, courses, course_prerequisites, curriculum_courses, elective_baskets, elective_basket_courses, batches, batch_sections, course_offerings, course_offering_faculty, course_offering_targets |
| timetables, attendance_periods | buildings, rooms, time_slots, timetables, timetable_entries, timetable_substitutions, class_sessions |
| students, student_enrollments, student_parents, student_documents, student_promotions, student_transfers | students, student_guardians, student_documents, student_undertakings, student_program_enrollments, student_term_records, student_holds, student_transfers, credit_transfers |
| departments, designations, staff, staff_documents, leave_types, staff_leaves, staff_leave_balances, staff_payrolls, staff_attendance | same names + faculty_profiles, faculty_qualifications, faculty_workloads, job_postings, job_applications, interview_panels, appraisals, cas_applications, loans_advances, payroll_components |
| holidays, attendance_sessions, student_attendance, student_period_attendance, biometric_devices | holidays, class_sessions, student_class_attendance, on_duty_requests, attendance_summaries, attendance_condonations, term_eligibility, attendance_devices |
| fee_categories, fee_structures, fee_discounts, student_fee_assignments, fee_invoices, fee_invoice_items, fee_payments, fine_configurations, v2_fee_* , student_discount_assignments | fee_heads, fee_structures, fee_structure_items, fee_discounts, student_fee_assignments, fee_invoices (+ payer_type/source_type/source_id), fee_invoice_items, fee_payments, fee_refunds, fine_configurations, offline_payment_reconciliations, scholarships, scholarship_applications, no_dues_requests, no_dues_signoffs |
| exam_types, exams, admit_card_configs, student_marks, grading_scales, report_card_templates, exam_question_papers | assessment_schemes, assessment_components, offering_assessments, assessment_questions, internal_marks, cia_consolidations, marks_change_requests, exam_sessions, exam_papers, exam_registrations, exam_registration_items, exam_seating_plans, exam_seat_allocations, invigilation_duties, exam_attendance, question_paper_assignments, question_paper_print_log, answer_script_bundles, answer_scripts, script_custody_log, valuation_assignments, script_valuations, script_final_marks, moderation_actions, grading_scales, result_processing_runs, student_course_results, student_term_results, result_publications, grade_cards, transcripts, reval_requests, malpractice_cases, legacy_result_imports |
| content tables (questions, question_options, question_tags, question_usages, syllabus_topics, question_blueprints, blueprint_rules, content_assets, content_documents, document_sections/items/options) | carried as-is (question bank, blueprints, paper builder, study materials) |
| book_categories, books, library_members, book_issues, library_fines | carried + library_copies, library_eresources, library_reservations |
| vehicles, routes, stops, student_transport, staff_transport, vehicle_maintenance, vehicle_fuel_log, gps_devices, vehicle_gps_logs, transport_trips, trip_stop_events, trip_student_events | carried |
| inventory_categories, items, stores, stock_entries, stock_issues, suppliers, purchase_orders, purchase_order_items, vendor_inventory (8) | carried + indents, quotations, goods_receipts, assets, asset_audits, vendor_bills, amc_contracts |
| income_categories, expense_categories, income_records, expense_records, budget_heads | carried + budget_allocations, grant_ledgers, bank_reconciliations |
| notification_templates, notifications, bulk_messages, message_logs, announcements, device_tokens, notification_preferences, conversation_sessions, wa_processed_messages | carried + domain_events (outbox), dlt_templates, whatsapp_templates, announcement_acknowledgements, emergency_alerts |
| homework, homework_submissions, lesson_plans, ptm_events, ptm_slots, ptm_bookings | lms_assignments, assignment_submissions, lesson_plans, mentoring_slots, mentoring_bookings, mentoring_sessions |
| calendar_events | calendar_events (+ academic_calendar_items), events, event_registrations |
| document_templates | document_templates, certificate_requests, document_serials |
| audit_logs | audit_logs (partitioned, hash-chained) |
| subscription_plans, school_subscriptions, school_feature_flags, impersonation_logs, platform_settings | subscription_plans, institution_subscriptions, institution_feature_flags, feature_flag_changes, platform_features, impersonation_logs, platform_settings, support_tickets, usage_meters |
| school_website_config, gallery_albums, gallery_images, website_notices, website_events, website_enquiries, website_content_items, school_domains | institution_website_config, gallery_albums, gallery_images, website_notices, website_events, website_enquiries, website_content_items, institution_domains |
| pending_registrations, demo_requests | pending_registrations, demo_requests |
| personal_expenses | — (not carried) |

### 2.3 New platform tables (no Orbit equivalent)

`number_sequences`, `workflow_definitions`, `workflow_instances`, `workflow_steps`, `workflow_delegations`, `background_jobs`, `domain_events`, `idempotency_keys`, `api_keys`, `webhooks`, `webhook_deliveries`, `integration_connections`, `integration_health_checks`, `data_imports`, `data_import_rows`, `consent_records`, `data_subject_requests`, `search_documents` (view), `user_sessions`, `mfa_secrets`, `login_history`, `ip_allowlists`, `read_only_modes`, `help_articles`, `feedback_entries`.

### 2.4 Code-level renames

| Orbit | Universe |
|---|---|
| `app/services/school_service.py` (ALL_PERMISSIONS, ROLE_PERMISSIONS, SYSTEM_ROLES, seed_school_defaults) | `app/core/rbac/registry.py` (PERMISSIONS, ROLE_TEMPLATES), `app/services/institution_service.py` (`seed_institution_defaults`) |
| `app/schemas/phaseN.py` | `app/schemas/<domain>.py` |
| `utils/audit.py` (unused) + `AuditMiddleware` | `core/audit.py` (`log_audit`, hash chain) + middleware fallback |
| `X-Total-Count` header | envelope `pagination` |
| `core/scoping.py` (`assert_can_read_student`) | `core/authz/visibility.py` (`VisibilityResolver`) |
| `data/default_plans.py` `enabled_modules` (6 keys) | `core/features.py` registry (≈230 keys) |
| Frontend `pages/<module>` + `api/<module>.ts` | `features/<module>/{api,hooks,pages,components,types}` |
| `store/academicYearStore.ts` | `store/sessionStore.ts` (year + term + college) |
| Flutter `role_tabs.dart` | `role_shells.dart` (+ feature/visibility gating) |
