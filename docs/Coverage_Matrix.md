# SeptronUniverse — Coverage Matrix

Verification that every feature from the reference inventories has a home: **source item → phase → feature key(s) → main tables**. A blank in any column is a gap; none are allowed at doc-set sign-off (`scripts/verify_prompts_vs_schema.py` cross-checks table names against `Database_Schema.sql`).

## A. SAMARTH eGov (Govt. of India university ERP, 9 packages / 40+ modules)

| SAMARTH module | Phase | Feature key(s) | Tables |
|---|---|---|---|
| Organizational Unit | 03 | core.institution, institution.multi_college, institution.faculties | institutions, colleges, faculties, departments |
| User Management | 02 | core.auth, core.rbac, security.* | users, roles, permissions, user_roles, sessions |
| Programme and Courses | 05 | academics.programs/regulations/curriculum/elective_baskets | programs, regulations, program_regulations, program_structure_terms, courses, curriculum_courses, elective_baskets |
| Student | 07 | students.* | students, student_program_enrollments, student_term_records, student_holds, student_guardians |
| Admissions | 08 | admissions.* | admission_cycles, seat_matrix, applicants, merit_lists, counselling_rounds, seat_allotments |
| Evaluation & Grading | 13–16 | assessment.*, exams.*, results.* | assessment_schemes, internal_marks, exam_sessions, answer_scripts, script_valuations, student_course_results, student_term_results |
| Hostel Management | 20 | hostel.* | hostels, hostel_rooms, hostel_beds, hostel_allocations, mess_* |
| Convocation | 18 | degrees.convocation, degrees.certificates | convocations, convocation_registrations, degrees_awarded |
| Alumni Portal | 29, 39 | alumni.core, alumni.portal, portals.alumni | alumni_profiles, alumni_events |
| Student Feedback Management | 27 | surveys.core, surveys.sss | feedback_surveys, feedback_responses |
| Training and Placement | 28 | placement.* | companies, placement_drives, drive_applications, placement_offers, training_programs |
| Employee Management | 06 | hr.staff, hr.faculty_profiles, hr.service_book | staff, faculty_profiles, staff_documents |
| Recruitment | 06 | hr.recruitment, hr.reservation_roster | job_postings, job_applications, interview_panels |
| Leave Management | 06 | hr.leaves, hr.leave_encashment | leave_types, staff_leaves, staff_leave_balances |
| Payroll Management | 06 | hr.payroll, hr.statutory_payroll, hr.loans_advances | staff_payrolls, payroll_components, loans_advances |
| Knowledge Management | 13, 19 | lms.content, lms.study_materials, library.eresources | course_contents, library e-resources |
| Career Advancement Scheme | 06 | hr.appraisal_pbas, hr.cas_promotions, research.api_score | appraisals, cas_applications |
| Training of Trainers | 30 | research.fdp | faculty_developments |
| Budget & Accounts | 23 | accounting.core, accounting.budgets | income_records, expense_records, budget_heads |
| Bill Tracking | 22 | inventory.bills | vendor_bills |
| Inventory Management | 22 | inventory.core, inventory.assets | items, stores, assets |
| Research Project Management | 30 | research.projects_grants, accounting.grants_ledger | research_projects |
| Core Communication | 04, 24 | comms.* | notification_templates, message_logs, announcements |
| Estate Management | 25 | facilities.room_booking, facilities.amc, timetable.rooms | buildings, rooms, room_bookings, amc_contracts |
| Legal Case Management | 33 | governance.legal | legal_cases |
| File Management & Tracking | 33 | governance.efile | efiles, efile_movements |
| RTI Management | 33 | governance.rti | rti_requests |
| Health Management | 25 | facilities.health_centre | health_visits, insurance_policies |
| Service Desk | 25 | facilities.service_desk | service_requests |
| Sports Management | 25 | facilities.sports | sports_teams, sports_events, sports_participation |
| Minutes & Resolutions Archive | 33 | governance.committees, governance.minutes | committees, meetings, resolutions, action_taken_reports |
| Fleet Management | 21 | transport.* | vehicles, routes, trips |
| Content Federation | 40 | website.core | website tables |
| Essential Services | 25 | facilities.service_desk, facilities.canteen_wallet | service_requests, canteens |
| Grievance Management | 27 | grievances.* | grievances, grievance_updates |
| Security Management | 25 | facilities.visitor_gate, facilities.emergency_sos | visitor_passes, emergency_alerts |
| Endowment Management | 29 | alumni.fundraising, alumni.donations_80g | fundraising_campaigns, donations |
| Residential Accommodation (staff) | 20 | hostel.staff_quarters | staff_quarters, staff_quarter_allocations |
| Affiliation Management | 34 | affiliation.* | affiliation_applications, affiliation_program_approvals, college_data_submissions, exam_centres |

## B. Commercial college-ERP feature lists (MasterSoft, Creatrix, vmedulife, edumerge, Edhitch, iCloudEMS, OpenEduCat)

| Feature | Phase | Feature key(s) |
|---|---|---|
| Lead capture / counselling CRM | 08 | admissions.enquiry_crm |
| Digital application, merit automation, payment, eligibility config, reservation mapping, seat allocation, ID generation | 08 | admissions.* |
| Custom fee heads, reminders, multi-mode payment (UPI/Razorpay/PayU/Cashfree), instalments, reconciliation, defaulters, receipts, penalties | 12 | fees.* |
| Biometric/GPS/RFID attendance, auto-sync, dashboards, staff attendance, proxy control | 11 | attendance.* |
| Internal & external exams, script evaluation workflows, result publishing, credit grading, revaluation/supplementary | 13–16 | exams.*, results.* |
| Timetable with conflict resolution, classroom allocation, substitution alerts | 10 | timetable.* |
| CO/PO/PSO mapping & attainment | 13, 17 | obe.* |
| Hostel resident tracking, allocation, maintenance | 20 | hostel.* |
| OPAC, barcode/RFID, fines, e-journals, repository | 19 | library.* |
| Transport GPS, driver records, SOS | 21, 25 | transport.gps_live, facilities.emergency_sos |
| Faculty payroll, appraisal, development | 06, 30 | hr.*, research.fdp |
| Publications, patents, consultancy, funded research, incubation | 30 | research.* |
| Scholarships, career guidance, placement, higher-education progression, skills, alumni, grievances, mentoring | 12, 27, 28, 29 | fees.scholarships, mentoring.*, placement.*, alumni.*, grievances.* |
| NAAC documentation, IQAC, AQAR, evidence repository, OBE attainment, feedback analysis | 32, 17, 27 | accreditation.*, obe.attainment, surveys.* |
| Strategic planning, audit trails, RBAC, e-governance | 33, 37, 02 | governance.*, core.audit_logs, core.rbac |
| Mobile apps for all stakeholders, live alerts, digital ID, notes distribution, assignment submission, centralised messaging | 42, 24, 26, 13 | mobile.*, comms.*, students.id_cards, lms.* |
| One-click dashboards, KPI tracking, compliance exports | 35, 36 | analytics.*, reports.* |
| Moodle/LTI, Tally/SAP/Zoho, CRM, gateways, DigiLocker integrations | 41 | integrations.* |
| 2FA, IP restriction, encryption, backups, uptime, audit | 02, 43, 44 | security.*, privacy.* |

## C. International registrar / SIS practice

| Feature | Phase | Feature key(s) |
|---|---|---|
| Public course catalogue | 05, 40 | academics.public_catalog, website.course_catalog |
| Prerequisites / co-requisites / anti-requisites | 05, 09 | academics.curriculum, registration.core |
| Registration cart, add/drop, waitlists, credit limits | 09 | registration.* |
| Holds (registration/transcript/graduation) | 07 | students.holds |
| Academic standing / probation / dismissal | 07 | students.academic_standing |
| Degree audit | 18 | degrees.eligibility |
| Tamper-proof transcripts with QR | 16, 18 | results.transcripts, degrees.verification_portal |
| Incompletes, withdrawals (W), audit grades | 15 | results.processing |
| Grade appeals | 16 | results.revaluation, results.challenge_valuation |
| Transfer-credit evaluation | 07 | academics.credit_transfer_mooc |
| Graduation application / commencement | 18 | degrees.convocation |
| Enrolment verification letters | 26 | documents.certificate_requests |
| FERPA-style parent access consent | 07 | students.guardians_portal |
| Financial aid | 12 | fees.scholarships |
| Housing | 20 | hostel.* |
| Health / immunisation | 25 | facilities.health_centre |
| Athletics | 25 | facilities.sports |
| Career services | 28 | placement.* |
| Academic advising | 27 | mentoring.* |
| Study abroad / exchange | 30 | research.mous_collaborations |
| International students office | 07 | students.international_office |

## D. NEP 2020 and Indian regulators

| Requirement | Phase | Feature key(s) |
|---|---|---|
| CBCS credits, L-T-P-C, credit buckets | 05 | academics.curriculum |
| Multiple entry / exit with certificate/diploma/degree | 05, 07, 18 | academics.nep_exit_reentry, degrees.certificates |
| ABC / APAAR ids and credit ledger | 07, 18 | academics.abc_apaar, degrees.abc_push |
| MOOC / SWAYAM / NPTEL credit transfer | 07, 41 | academics.credit_transfer_mooc, integrations.swayam_nptel |
| DigiLocker / NAD digital credentials | 18, 41 | degrees.digilocker_nad, integrations.digilocker_nad |
| NSP scholarships | 12, 41 | fees.nsp_integration, integrations.nsp |
| AISHE / NIRF / AICTE / UGC returns | 32, 36 | accreditation.*, reports.statutory |
| UGC PhD Regulations 2022 (coursework, DC, progress, plagiarism < 10 %, examiners, viva, Shodhganga) | 31 | phd.* |
| Anti-ragging / ICC committees, undertakings | 07, 27, 33 | students.undertakings, grievances.committees, governance.committees |
| DLT SMS, DPDP, GST | 04, 43, 12 | comms.sms, privacy.*, fees.gst_invoicing |

## E. SeptronOrbit as-built inventory (149 tables) → Universe

| Orbit area (tables) | Universe phase | Disposition |
|---|---|---|
| auth (users, password_reset_tokens, device_tokens, QR tokens, biometric_devices, gps_devices) | 02, 11, 21 | carried (institution scope) |
| rbac (roles, permissions, role_permissions, user_roles) | 02 | carried + scope columns |
| school, school_profile, school_settings, platform_settings | 03, 38 | → institutions, institution_profile, institution_settings |
| academic_years, academic_terms | 03 | carried + term status/dates |
| admission_form_configs, admission_forms, demo_requests, pending_registrations, leads | 08, 38, 40 | → admission cycles/applicants; SaaS registration carried |
| classes, sections, subjects, class_subjects, timetables, attendance_periods | 05, 09, 10 | → programs/courses/offerings/batch_sections/timetables |
| students, student_enrollments, student_parents, student_documents, student_promotions, student_transfers | 07 | → students, student_program_enrollments, student_term_records, student_guardians, student_documents, student_transfers |
| staff, departments, designations, staff_documents, leave_types, staff_leaves, staff_leave_balances, staff_payrolls, staff_attendance | 06 | carried + faculty_profiles, statutory payroll |
| holidays, attendance_sessions, student_attendance, student_period_attendance | 03, 11 | → holidays, class_sessions, student_class_attendance |
| fees v1 + v2 tables, fine_configurations, student_discount_assignments, receipts | 12 | unified fee model with fee-linkage columns |
| exam_types, exams, admit_card_configs, student_marks, grading_scales, report_card_templates, exam_question_papers | 13–16, 26 | → exam suite; grading_scales carried; templates carried |
| content (questions, options, tags, usages, syllabus_topics, blueprints, blueprint_rules, content_assets/documents/sections/items) | 13, 14 | carried (question bank, blueprints, paper builder, study materials) |
| library (book_categories, books, library_members, book_issues, library_fines) | 19 | carried + e-resources |
| transport (vehicles, routes, stops, student_transport, staff_transport, maintenance, fuel, gps logs, trips, trip events) | 21 | carried |
| inventory (categories, items, stores, suppliers, POs, stock entries/issues) + vendor_inventory (8) | 22 | carried; vendor store behind `inventory.vendor_store` |
| accounting (income/expense categories & records, budget_heads) | 23 | carried + grants ledger |
| communications (notification_templates, notifications, bulk_messages, message_logs, announcements, notification_preferences, conversation_sessions, wa_processed_messages) | 04, 24 | carried + outbox, DLT registry, bot flows, AI assistant |
| homework, homework_submissions, lesson_plans, ptm_* | 13, 27 | → lms_assignments, lesson_plans, mentoring |
| calendar_events | 25 | carried + academic calendar |
| document_templates (+ bulk render jobs) | 26, 01 | carried + certificate requests, background_jobs |
| audit_logs (partitioned) | 37 | carried + hash chain |
| super_admin (subscription_plans, school_subscriptions, school_feature_flags, impersonation_logs) | 38 | carried; feature flags → registry-driven |
| website (config, gallery, notices, events, enquiries, content, domains) + marketing | 40 | carried + catalogue pages |
| personal_expenses | — | not carried (school-specific) |
| portals (parent, student, teacher, driver), PWA, web push | 39 | carried + faculty/alumni/warden/evaluator/scholar/recruiter |
| Flutter (33 features, 11 locales, thermal print, GPS queue) | 42 | carried + role shells, offline cache/queue |
| tests/security/deploy/orbit-infra | 43, 44 | carried (API/UI verification instead of unit tests) |

## F. Visibility requirement (self vs view_all)

| Requirement | Where |
|---|---|
| Every people/records module exposes self and (when permitted) wider views | `docs/Authorization_and_Visibility.md` §4–5; each phase prompt's **Visibility rules** section |
| Accountant sees all staff, leaves, attendance + own | matrix row `accountant`; Phase 06/12 prompts; verification step 1 |
| Mobile Mine/Dept/All segments | `docs/Mobile_App_UI_Structure.md` §2.4 |
