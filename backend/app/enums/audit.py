"""Audit, security-event, settings-catalogue and retention vocabularies — Prompts/37 §37.2 / §37.3.

Single source for revision ``0037`` (settings catalogue metadata, retention defaults), the Phase 37 services and the
demo seeder. Nothing here is stored per row: ``AuditAction`` names the actions modules already write through
``log_audit``; ``SUMMARY_TEMPLATES`` renders the explorer's summary line per ``module:action``.
"""

from enum import StrEnum
from typing import Any


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    VIEW = "view"
    VIEW_PII = "view_pii"
    EXPORT = "export"
    DOWNLOAD = "download"
    LOGIN = "login"
    LOGOUT = "logout"
    APPROVE = "approve"
    REJECT = "reject"
    PUBLISH = "publish"
    LOCK = "lock"
    UNLOCK = "unlock"
    DECODE = "decode"
    IMPERSONATE = "impersonate"
    SETTINGS_CHANGE = "settings_change"
    FEATURE_TOGGLE = "feature_toggle"


class SecurityEventType(StrEnum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOCKED = "locked"
    MFA_FAILED = "mfa_failed"
    MFA_CHANGE = "mfa_change"
    PASSWORD_RESET = "password_reset"
    SESSION_REVOKED = "session_revoked"
    IMPERSONATION = "impersonation"
    IP_ALLOWLIST_CHANGE = "ip_allowlist_change"
    API_KEY = "api_key"
    EXPORT = "export"
    PII_UNMASK = "pii_unmask"
    FEATURE_TOGGLE = "feature_toggle"
    SETTINGS_CHANGE = "settings_change"


class RetentionDataClass(StrEnum):
    LOGIN_HISTORY = "login_history"
    NOTIFICATIONS = "notifications"
    MESSAGE_LOGS = "message_logs"
    DOMAIN_EVENTS = "domain_events"
    WEBHOOK_DELIVERIES = "webhook_deliveries"
    JOB_FILES = "job_files"
    REPORT_FILES = "report_files"
    DOCUMENT_PREVIEWS = "document_previews"
    VISITOR_PII = "visitor_pii"
    GPS_LOGS = "gps_logs"
    AUDIT_LOGS = "audit_logs"
    ATTENDANCE = "attendance"


class ArchiveStatus(StrEnum):
    ARCHIVED = "archived"
    RESTORED = "restored"
    FAILED = "failed"


# ---- audit explorer -------------------------------------------------------------------------------------------------
MAX_QUERY_DAYS = 366
DEFAULT_QUERY_DAYS = 30
CHAIN_BATCH = 10_000

# modules whose rows feed the security console (besides login_history / sessions / impersonation / allow-lists)
SECURITY_MODULES = ("auth", "users", "roles", "features", "integrations", "reports", "exports", "security", "settings")

# record types whose reads are listed by "who viewed" (confidential records)
CONFIDENTIAL_RECORD_TYPES = (
    "student",
    "students",
    "health_visit",
    "health_visits",
    "grievance",
    "grievances",
    "staff",
    "answer_script",
    "answer_scripts",
    "exam_paper",
)
VIEW_ACTIONS = ("view", "view_pii", "download")
DECODE_ACTIONS = ("decode", "exams:decode")

# record type → module whose ``view_pii`` unmasks old/new values (default: the row's module)
RECORD_PII_MODULE: dict[str, str] = {
    "student": "students",
    "students": "students",
    "staff": "hr",
    "user": "users",
    "health_visit": "health",
    "grievance": "grievances",
    "applicant": "admissions",
}
PII_VALUE_KEYS: dict[str, str] = {
    "phone": "phone",
    "mobile": "phone",
    "alternate_phone": "phone",
    "email": "email",
    "personal_email": "email",
    "aadhaar": "generic",
    "aadhaar_encrypted": "generic",
    "pan": "generic",
    "bank_details": "generic",
    "bank_details_encrypted": "generic",
    "account_number": "generic",
    "passport": "generic",
    "dob": "generic",
    "permanent_address": "generic",
    "current_address": "generic",
}

# ``module:action`` → summary line ({field} from new_values; missing fields render empty)
SUMMARY_TEMPLATES: dict[str, str] = {
    "fees:collect": "Collected ₹{amount} receipt {number}",
    "fees:payment": "Payment ₹{amount} receipt {number}",
    "fees:refund": "Refund ₹{amount}",
    "students:create": "Student {registration_number} created",
    "students:update": "Student record updated",
    "students:view_pii": "Viewed personal data ({fields})",
    "settings:update": "Settings changed: {keys}",
    "settings:reset": "Setting reset to default: {key}",
    "settings:import": "Settings imported ({applied} keys)",
    "settings:override_clear": "College override cleared: {key}",
    "exams:decode": "Decoded {decoded} scripts",
    "exams:exams:decode": "Decoded {decoded} scripts",
    "results:publish": "Results published",
    "reports:run": "Report {key} run",
    "reports:download": "Report {key} downloaded",
    "reports:preview": "Report {key} previewed",
    "auth:login": "Signed in",
    "users:session_revoke": "Sessions revoked ({count})",
    "audit_logs:export": "Audit rows exported",
    "audit_logs:verify_chain": "Audit chain verified ({rows} rows)",
    "security:session_revoke": "Sessions revoked by an administrator ({count})",
    "security:anomaly_ack": "Anomaly {rule} acknowledged",
    "retention:purge": "Purged {rows} {data_class} rows",
    "retention:archive": "Archived {data_class} {period}",
    "retention:legal_hold_set": "Legal hold set on {data_class}",
    "features:toggle": "Feature {feature_key} switched",
}

# record type → SQL giving the record's (college_id, department_id) for college / department-scoped explorers
# (``record_scope_resolvers`` of Prompts/37 §37.5 — filled here for the core record types; ``:rid`` is the record id)
RECORD_SCOPE_SQL: dict[str, str] = {
    "student": "SELECT e.college_id, e.department_id FROM student_program_enrollments e WHERE e.student_id = {rid}",
    "student_program_enrollment": "SELECT e.college_id, e.department_id FROM student_program_enrollments e WHERE e.id = {rid}",
    "staff": "SELECT s.college_id, s.department_id FROM staff s WHERE s.id = {rid}",
    "program": "SELECT p.college_id, p.department_id FROM programs p WHERE p.id = {rid}",
    "batch": "SELECT b.college_id, p.department_id FROM batches b JOIN programs p ON p.id = b.program_id WHERE b.id = {rid}",
    "course_offering": "SELECT o.college_id, o.department_id FROM course_offerings o WHERE o.id = {rid}",
    "department": "SELECT d.college_id, d.id FROM departments d WHERE d.id = {rid}",
    "fee_invoice": "SELECT e.college_id, e.department_id FROM fee_invoices i JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id WHERE i.id = {rid}",
    "grievance": "SELECT g.college_id, e.department_id FROM grievances g LEFT JOIN student_program_enrollments e ON e.id = g.student_program_enrollment_id WHERE g.id = {rid}",
    "exam_session": "SELECT x.college_id, NULL::uuid FROM exam_sessions x WHERE x.id = {rid}",
}
RECORD_SCOPE_SQL.update(
    {(k + "es" if k.endswith("ch") else k + "s"): v for k, v in list(RECORD_SCOPE_SQL.items()) if k != "staff"}
)

# ---- exam audit -----------------------------------------------------------------------------------------------------
EXAM_AUDIT_SECTIONS = (
    "marks",
    "qp_print",
    "custody",
    "valuation",
    "moderation",
    "decode",
    "runs",
    "publication",
    "post_result",
)
# custody chain: the action each step must follow (a missing predecessor is a gap)
CUSTODY_ORDER = ("created", "dispatched", "received", "handed_over", "returned", "archived", "destroyed")

# ---- settings -------------------------------------------------------------------------------------------------------
SENSITIVE_CATEGORIES = ("security", "privacy", "fees", "exams", "audit")
# full key → (depends_on full key, required truthy value description)
SETTING_DEPENDENCIES: dict[str, tuple[str, str]] = {
    "fees.gst_enabled": ("fees.gstin", "GSTIN must be set before GST is enabled"),
}
# platform-only keys: read-only for tenants (409 RULE_VIOLATION on write)
PLATFORM_SCOPED_KEYS = frozenset({"security.jwt_kid", "audit.digest_signing_key_id"})
# keys only the platform operator's plan may change (Phase 38 entitlements explain the reason)
PLAN_LOCKED_KEYS: dict[str, str] = {
    "reports.max_rows": "Row cap follows the subscription plan",
    "comms.credits": "Message credits are allotted by the plan",
}
ENV_LOCKED_KEYS = frozenset({"security.jwt_kid"})
RESTART_KEYS = frozenset({"integrations.provider_overrides"})
# categories whose keys may be overridden per college
COLLEGE_SCOPED_CATEGORIES = frozenset(
    {"academics", "attendance", "fees", "timetable", "registration", "hostel", "transport", "library", "communication"}
)

# ---- retention ------------------------------------------------------------------------------------------------------
RETENTION_DEFAULTS: dict[str, Any] = {
    "login_history_days": 365,
    "notifications_days": 180,
    "message_logs_days": 365,
    "domain_events_days": 90,
    "webhook_deliveries_days": 90,
    "job_files_days": 30,
    "report_files_days": 30,
    "document_previews_days": 7,
    "visitor_pii_days": 90,
    "gps_logs_days": 180,
    "audit_logs_archive_after_years": 2,
    "attendance_archive_after_years": 3,
    "legal_hold": [],
}
# platform maximums an institution may not exceed (and minimums for the audit / attendance archives)
RETENTION_MAXIMUMS: dict[str, int] = {
    "login_history_days": 1095,
    "notifications_days": 730,
    "message_logs_days": 1095,
    "domain_events_days": 365,
    "webhook_deliveries_days": 365,
    "job_files_days": 180,
    "report_files_days": 365,
    "document_previews_days": 30,
    "visitor_pii_days": 365,
    "gps_logs_days": 730,
    "audit_logs_archive_after_years": 10,
    "attendance_archive_after_years": 10,
}
RETENTION_MINIMUMS: dict[str, int] = {"audit_logs_archive_after_years": 1, "attendance_archive_after_years": 1}

# data class → (policy key, purge SQL target). ``{cutoff}`` binds ``:cutoff``; ``{hold}`` the legal-hold exemption.
PURGE_TARGETS: dict[str, dict[str, Any]] = {
    "login_history": {
        "policy": "login_history_days",
        "table": "login_history",
        "ts": "occurred_at",
        "user_col": "user_id",
    },
    "notifications": {
        "policy": "notifications_days",
        "table": "notifications",
        "ts": "created_at",
        "user_col": "user_id",
    },
    "message_logs": {
        "policy": "message_logs_days",
        "table": "message_logs",
        "ts": "created_at",
        "user_col": "user_id",
        "content_only": True,
    },
    "domain_events": {
        "policy": "domain_events_days",
        "table": "domain_events",
        "ts": "created_at",
        "where": "status = 'dispatched'",
    },
    "webhook_deliveries": {"policy": "webhook_deliveries_days", "table": "webhook_deliveries", "ts": "created_at"},
    "visitor_pii": {"policy": "visitor_pii_days", "table": "visitor_passes", "ts": "valid_to", "anonymise": True},
    "gps_logs": {"policy": "gps_logs_days", "table": "vehicle_gps_logs", "ts": "recorded_at"},
    "job_files": {"policy": "job_files_days", "files": "jobs"},
    "report_files": {"policy": "report_files_days", "files": "reports"},
    "document_previews": {"policy": "document_previews_days", "files": "previews"},
}
# data class → partitioned parent table archived by period
ARCHIVE_TARGETS: dict[str, dict[str, str]] = {
    "attendance": {
        "table": "student_class_attendance",
        "ts": "session_date",
        "policy": "attendance_archive_after_years",
    },
    "message_logs": {"table": "message_logs", "ts": "created_at", "policy": "message_logs_days"},
    "audit_logs": {"table": "audit_logs", "ts": "occurred_at", "policy": "audit_logs_archive_after_years"},
}
