"""Tables each phase owns in ``Database_Schema.sql`` — consumed by ``check_schema_drift.py --phase NN``.

Phase 00 mapped the tables the core skeleton needs; Phase 01 lists all 44 platform tables (sections 2-6); every later
phase appends its section's tables. Materialized views (Phase 35) are registered under ``VIEWS`` so the drift guard
skips them.
"""

PHASES: dict[str, list[str]] = {
    "00": [
        "institutions",
        "colleges",
        "users",
        "permissions",
        "roles",
        "role_permissions",
        "user_roles",
        "platform_features",
        "institution_feature_flags",
        "feature_flag_changes",
        "background_jobs",
        "domain_events",
        "event_consumptions",
        "idempotency_keys",
        "workflow_definitions",
        "workflow_instances",
        "workflow_steps",
        "workflow_delegations",
        "read_only_modes",
        "audit_logs",
    ],
    "01": [
        # §2 tenancy
        "institutions",
        "institution_profile",
        "colleges",
        "faculties",
        "departments",
        "institution_settings",
        "holidays",
        "number_sequences",
        # §3 auth
        "users",
        "password_reset_tokens",
        "user_sessions",
        "mfa_secrets",
        "login_history",
        "ip_allowlists",
        "device_tokens",
        "credential_sheets",
        # §4 rbac
        "permissions",
        "roles",
        "role_permissions",
        "user_roles",
        # §5 features
        "platform_features",
        "institution_feature_flags",
        "feature_flag_changes",
        # §6 platform services
        "background_jobs",
        "domain_events",
        "event_consumptions",
        "idempotency_keys",
        "workflow_definitions",
        "workflow_instances",
        "workflow_steps",
        "workflow_delegations",
        "api_keys",
        "webhooks",
        "webhook_deliveries",
        "integration_connections",
        "integration_health_checks",
        "data_imports",
        "data_import_rows",
        "consent_records",
        "data_subject_requests",
        "read_only_modes",
        "help_articles",
        "feedback_entries",
        "audit_logs",
    ],
    "02": [
        # §32 SaaS tables the entitlement / impersonation services need (Prompts/02 §02.3); the auth, RBAC and
        # feature tables of this phase were mapped in Phase 01
        "subscription_plans",
        "institution_subscriptions",
        "usage_meters",
        "impersonation_logs",
    ],
    "03": [
        # section 7 academic sessions (Prompts/03 §03.1); the section 2 tenancy tables were mapped in Phase 01
        "academic_years",
        "academic_terms",
    ],
    "04": [
        # section 23 communication (Prompts/04 §04.1); workflow tables + device_tokens were mapped in Phase 01
        "notification_templates",
        "dlt_templates",
        "whatsapp_templates",
        "notification_preferences",
        "notifications",
        "message_logs",
        "announcements",
        "announcement_acknowledgements",
        "conversation_sessions",
        "wa_processed_messages",
        "workflow_definitions",
        "workflow_instances",
        "workflow_steps",
        "workflow_delegations",
        "device_tokens",
    ],
    # Phase 05 — programmes, regulations & curriculum (section 7; no new tables)
    "05": [
        "grading_scales",
        "programs",
        "regulations",
        "program_regulations",
        "program_structure_terms",
        "assessment_schemes",
        "assessment_components",
        "courses",
        "course_prerequisites",
        "elective_baskets",
        "elective_basket_courses",
        "curriculum_courses",
        "batches",
        "batch_sections",
    ],
    "06": [
        "designations",
        "staff",
        "staff_documents",
        "service_book_entries",
        "faculty_profiles",
        "faculty_qualifications",
        "leave_types",
        "staff_leaves",
        "staff_leave_balances",
        "attendance_devices",
        "staff_attendance",
        "payroll_components",
        "staff_salary_structures",
        "staff_payrolls",
        "staff_payroll_items",
        "loans_advances",
        "job_postings",
        "job_applications",
        "interview_panels",
        "interview_scores",
        "appraisals",
        "cas_applications",
        "faculty_workloads",
        "course_allocation_proposals",
    ],
}

VIEWS: set[str] = set()


def tables_for(phase: str) -> list[str]:
    key = phase.zfill(2)
    if key not in PHASES:
        raise SystemExit(f"phase {key!r} is not in scripts/phase_manifest.py")
    return PHASES[key]


def all_tables() -> set[str]:
    return {t for tables in PHASES.values() for t in tables}
