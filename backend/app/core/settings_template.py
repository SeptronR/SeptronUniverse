"""Institution settings template, theme tokens and number-sequence patterns — Prompts/03 §03.2 / §03.6.

Single source for revision ``0003_phase03_settings_seed`` (stored in ``platform_settings['settings_template']``,
``['theme_tokens']`` and ``['number_sequence_template']``), for ``SettingsService`` (type validation, defaults,
``is_public``) and for ``seed_institution_defaults(pack)`` (institution rows). Keys are ``category.key``; the value
types are ``str | int | bool | list | json | enum`` (``enum`` carries ``choices``). ``integrations`` keeps provider
**overrides** only — secrets live in ``integration_connections`` (Phase 41), never here.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

VALUE_TYPES = ("str", "int", "bool", "list", "json", "enum")


@dataclass(frozen=True)
class SettingDef:
    category: str
    key: str
    value_type: str
    default: Any = None
    is_public: bool = False
    choices: tuple[str, ...] = ()
    label: str = ""
    min: int | None = None
    max: int | None = None
    feature: str | None = None  # writing the key additionally needs this feature (theme keys → institution.themes)

    @property
    def full_key(self) -> str:
        return f"{self.category}.{self.key}"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["choices"] = list(self.choices)
        return d


THEMES = ("indigo", "ocean", "grove", "sunset", "plum")  # same list as PlatformService.THEMES (Phase 01)
TABLE_STYLES = ("default", "striped", "bordered", "compact", "card", "minimal")

_T = "institution.themes"

SETTINGS_TEMPLATE: tuple[SettingDef, ...] = (
    # general — the branding keys are public (login page, website header) and gated by institution.themes
    SettingDef("general", "institution_display_name", "str", None, True, label="Display name"),
    SettingDef("general", "academic_calendar_locale", "str", "en-IN", True, label="Academic calendar locale"),
    SettingDef("general", "date_format", "enum", "dd/MM/yyyy", True, ("dd/MM/yyyy", "MM/dd/yyyy", "yyyy-MM-dd")),
    SettingDef("general", "first_day_of_week", "int", 1, True, label="First day of week (0=Sun … 6=Sat)", min=0, max=6),
    SettingDef("general", "theme", "enum", "indigo", True, THEMES, "Theme", feature=_T),
    SettingDef("general", "table_style", "enum", "minimal", True, TABLE_STYLES, "Table style", feature=_T),
    SettingDef("general", "logo_dark_url", "str", None, True, label="Logo (dark mode)", feature=_T),
    # security (Phase 02 reads mfa_required_roles / sso_role_map)
    SettingDef(
        "security", "mfa_required_roles", "list", None, label="Roles that must use MFA (empty = platform default)"
    ),
    SettingDef("security", "session_timeout_minutes", "int", 480, min=5, max=10080),
    SettingDef("security", "password_min_length", "int", 10, min=8, max=128),
    SettingDef("security", "ip_allowlist_enforced", "bool", False),
    SettingDef("security", "sso_role_map", "json", None, label="SSO group → role map"),
    # academics
    SettingDef("academics", "attendance_min_pct_default", "int", 75, min=0, max=100),
    SettingDef("academics", "credit_limits_enforced", "bool", True),
    SettingDef("academics", "allow_arrear_with_regular", "bool", True),
    SettingDef("academics", "catalog_public", "bool", False, True),
    # terms (Beat ``terms.auto_status``)
    SettingDef("terms", "auto_advance", "bool", False, label="Advance term status automatically on its dates"),
    # admissions
    SettingDef("admissions", "application_fee_default_paise", "int", 0, min=0),
    SettingDef("admissions", "auto_admit_on_fee", "bool", False),
    SettingDef("admissions", "reservation_policy", "json", None),
    # fees
    SettingDef("fees", "receipt_prefix", "str", "RCP"),
    SettingDef("fees", "late_fee_grace_days", "int", 0, min=0, max=365),
    SettingDef("fees", "gateway_provider", "str", "mock"),
    SettingDef("fees", "upi_vpa", "str", None),
    SettingDef("fees", "gst_enabled", "bool", False),
    # exams
    SettingDef("exams", "valuation_mode_default", "enum", "single", False, ("single", "double")),
    SettingDef("exams", "discrepancy_pct_default", "int", 15, min=0, max=100),
    SettingDef("exams", "hall_ticket_requires_no_dues", "bool", True),
    SettingDef(
        "exams",
        "eligibility_requires_fee_clear",
        "bool",
        False,
        label="Overdue fees make a student ineligible (Phase 11)",
    ),
    SettingDef("exams", "result_public_lookup", "bool", False, True),
    # hostel
    SettingDef("hostel", "guardian_otp_required_for_home_leave", "bool", True),
    SettingDef("hostel", "late_return_grace_minutes", "int", 15, min=0, max=720),
    # communication
    SettingDef("communication", "sms_sender_id", "str", None),
    SettingDef("communication", "dlt_entity_id", "str", None),
    SettingDef("communication", "whatsapp_number", "str", None),
    SettingDef("communication", "quiet_hours", "json", {"start": "21:00", "end": "08:00"}),
    SettingDef("communication", "digest_default", "enum", "daily", False, ("off", "daily", "weekly")),
    # integrations — provider overrides per capability ({"sms": "msg91", …}); secrets never stored here
    SettingDef("integrations", "provider_overrides", "json", {}),
    # privacy
    SettingDef("privacy", "retention_days_logs", "int", 365, min=30, max=3650),
    SettingDef("privacy", "consent_texts_version", "str", "1.0"),
    # hr (Phase 06) — norms default to the pack (seed copies them), week-offs are Python weekdays (6 = Sunday)
    SettingDef("hr", "workload_norms", "json", None, label="Workload norms (hours/week by cadre)"),
    SettingDef("hr", "week_offs", "json", [6], label="Weekly offs (0=Mon … 6=Sun)"),
    SettingDef(
        "hr", "document_expiry_days", "int", 30, label="Remind before a document expires (days)", min=1, max=365
    ),
    SettingDef("hr", "leave_carry_forward_month", "int", 1, label="Leave year starts in month", min=1, max=12),
    # payroll (Phase 06) — statutory thresholds/slabs from the pack; these keys override them per institution
    SettingDef("payroll", "pt_state", "str", None, label="Professional tax state (pack slab key)"),
    SettingDef("payroll", "tds_regime", "enum", "new", False, ("new", "old"), "Default TDS regime"),
    SettingDef("payroll", "pf_wage_ceiling_applies", "bool", True, label="Cap PF wages at the statutory ceiling"),
    SettingDef("payroll", "statutory_overrides", "json", {}, label="Statutory parameter overrides (pf/esi/pt/tds/lwf)"),
    SettingDef("payroll", "reminder_day", "int", 25, label="Payroll reminder day of month", min=1, max=28),
    # attendance (Phase 06) — self check-in geo-fence {lat, lng, radius_m} (a college row overrides it)
    SettingDef("attendance", "geo_fence", "json", None, label="Self check-in geo-fence {lat, lng, radius_m}"),
    SettingDef("attendance", "staff_self_checkin", "bool", True, label="Staff may check in from the app / web"),
    # attendance (Phase 11) — student marking window, QR, alerts, auto-finalize, OD approver, eligibility notices
    SettingDef("attendance", "future_marking_days", "int", 0, label="Days ahead a session may be marked", min=0, max=7),
    SettingDef("attendance", "qr_ttl_seconds", "int", 120, label="Session QR validity (seconds)", min=30, max=900),
    SettingDef(
        "attendance", "qr_late_minutes", "int", 10, label="QR / app check-ins after N minutes are late", min=0, max=120
    ),
    SettingDef(
        "attendance", "auto_finalize_days", "int", 3, label="Finalize taken sessions after N days", min=0, max=60
    ),
    SettingDef(
        "attendance", "absent_alert_consecutive", "int", 3, label="Guardian alert after N consecutive absences", min=1
    ),
    SettingDef("attendance", "checkpoints", "json", [25, 50, 75], label="Warning checkpoints (% of instruction days)"),
    SettingDef("attendance", "notify_guardians", "bool", True, label="Copy absence / threshold alerts to guardians"),
    SettingDef("attendance", "notify_mentor", "bool", True, label="Copy threshold warnings to the mentor / advisor"),
    SettingDef(
        "attendance", "od_approver", "enum", "hod", False, ("hod", "registrar"), "Who approves on-duty requests"
    ),
    SettingDef("attendance", "notify_detained", "bool", True, label="Notify detained students once per version"),
    # students (Phase 07) — gates read ``undertakings_required`` (empty list = the pack default); an adult student
    # (``adult_age``) controls the guardian-portal consent; ID-card QR tokens live until the expected graduation year
    SettingDef(
        "students",
        "undertakings_required",
        "list",
        None,
        label="Undertakings required each academic year (registration / hostel gates; empty = pack default)",
    ),
    SettingDef("students", "adult_age", "int", 18, label="Age from which a student controls guardian consent", min=16),
    SettingDef(
        "students", "document_expiry_days", "int", 30, label="Remind before a student document expires (days)", min=1
    ),
    SettingDef("students", "id_card_validity_years", "int", 5, label="ID-card QR validity (years)", min=1, max=10),
    SettingDef(
        "students",
        "self_service_fields",
        "list",
        ["phone", "email", "current_address", "photo", "emergency_contact"],
        label="Fields a student may edit on the own profile",
    ),
    # admissions (Phase 08) — a cycle's form_config overrides max_preferences / strict_eligibility / refund_policy /
    # admission_fee_paise; applicant accounts expire applicant_validity_days after the cycle closes (and on archive)
    SettingDef("admissions", "max_preferences", "int", 5, label="Programme preferences per application", min=1, max=20),
    SettingDef("admissions", "strict_eligibility", "bool", False, label="Refuse submission for ineligible preferences"),
    SettingDef("admissions", "public_merit_lists", "bool", True, label="Publish merit lists publicly (masked)"),
    SettingDef(
        "admissions", "admission_fee_paise", "int", 2500000, label="Admission fee on seat acceptance (paise)", min=0
    ),
    SettingDef(
        "admissions",
        "refund_policy",
        "json",
        {"processing_fee_paise": 50000, "after_acceptance_pct": 50},
        label="Withdrawal refund {processing_fee_paise, after_acceptance_pct}",
    ),
    SettingDef(
        "admissions", "applicant_validity_days", "int", 365, label="Applicant account validity after close", min=30
    ),
    SettingDef("admissions", "lateral_entry_term", "int", 3, label="Entry term of lateral admits", min=2, max=10),
    # registration (Phase 09) — workload enforcement on faculty allocation, seat defaults, waitlist offer validity,
    # arrear rules and the registration fees that stand in for Phase 12 invoices (mock payment order until then)
    SettingDef(
        "hr", "workload_enforce", "enum", "warn", False, ("block", "warn"), "Faculty allocation above the workload norm"
    ),
    SettingDef("registration", "default_max_seats", "int", 60, label="Default seats per offering", min=1, max=1000),
    SettingDef("registration", "waitlist_offer_hours", "int", 48, label="Waitlist offer validity (hours)", min=1),
    SettingDef("registration", "allow_arrear_with_regular", "bool", False, label="Arrear courses in a regular window"),
    SettingDef(
        "registration", "auto_confirm_allocations", "bool", False, label="Elective allocation confirms the item"
    ),
    SettingDef(
        "registration",
        "prerequisite_bypass",
        "bool",
        False,
        label="Skip prerequisite checks (development only — before Phase 15 results)",
    ),
    SettingDef("registration", "fee_paise", "int", 0, label="Registration fee per submission (paise)", min=0),
    SettingDef(
        "registration", "arrear_fee_per_credit_paise", "int", 50000, label="Arrear fee per credit (paise)", min=0
    ),
    # timetable (Phase 10) — the default slot group the 0010 revision seeds per college, nightly missed-session flagging
    SettingDef(
        "timetable",
        "default_slot_group",
        "json",
        [
            {"name": "P1", "start_time": "09:00", "end_time": "09:50", "slot_type": "lecture"},
            {"name": "P2", "start_time": "09:50", "end_time": "10:40", "slot_type": "lecture"},
            {"name": "BRK", "start_time": "10:40", "end_time": "11:00", "slot_type": "break"},
            {"name": "P3", "start_time": "11:00", "end_time": "11:50", "slot_type": "lecture"},
            {"name": "P4", "start_time": "11:50", "end_time": "12:40", "slot_type": "lecture"},
            {"name": "LUNCH", "start_time": "12:40", "end_time": "13:30", "slot_type": "lunch"},
            {"name": "P5", "start_time": "13:30", "end_time": "14:20", "slot_type": "lecture"},
            {"name": "P6", "start_time": "14:20", "end_time": "15:10", "slot_type": "lecture"},
            {"name": "P7", "start_time": "15:20", "end_time": "16:10", "slot_type": "lecture"},
            {"name": "P8", "start_time": "16:10", "end_time": "17:00", "slot_type": "lecture"},
        ],
        label="Default slot group (P1–P8 with breaks)",
    ),
    SettingDef(
        "timetable", "mark_missed_sessions", "bool", True, label="Flag past sessions without attendance nightly"
    ),
)

CATEGORIES: tuple[str, ...] = tuple(dict.fromkeys(d.category for d in SETTINGS_TEMPLATE))
BY_KEY: dict[tuple[str, str], SettingDef] = {(d.category, d.key): d for d in SETTINGS_TEMPLATE}


def template_json() -> dict[str, dict[str, dict[str, Any]]]:
    """``platform_settings['settings_template']`` — category → key → definition."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for d in SETTINGS_TEMPLATE:
        out.setdefault(d.category, {})[d.key] = {
            k: v for k, v in d.as_dict().items() if k not in {"category", "key"} and v not in (None, [], "")
        } | {"default": d.default}
    return out


# ---- theme tokens (platform defaults; an institution picks one with general.theme) ------------------------------------
THEME_TOKENS: dict[str, dict[str, str]] = {
    "indigo": {"primary": "#4f46e5", "primary_foreground": "#ffffff", "accent": "#eef2ff", "sidebar": "#1e1b4b"},
    "ocean": {"primary": "#0369a1", "primary_foreground": "#ffffff", "accent": "#e0f2fe", "sidebar": "#082f49"},
    "grove": {"primary": "#15803d", "primary_foreground": "#ffffff", "accent": "#dcfce7", "sidebar": "#052e16"},
    "sunset": {"primary": "#c2410c", "primary_foreground": "#ffffff", "accent": "#ffedd5", "sidebar": "#431407"},
    "plum": {"primary": "#7e22ce", "primary_foreground": "#ffffff", "accent": "#f3e8ff", "sidebar": "#3b0764"},
}
PLATFORM_THEME_DEFAULT = {"theme": "indigo", "table_style": "minimal"}


# ---- number sequences -------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SequenceTemplate:
    scope_key: str
    pattern: str
    padding: int = 4
    reset_policy: str = "never"
    label: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


NUMBER_SEQUENCE_TEMPLATE: tuple[SequenceTemplate, ...] = (
    SequenceTemplate("application_no", "APP{yy}{seq:6}", 6, "yearly", "Admission application"),
    SequenceTemplate("admission_no", "ADM{yyyy}{seq:5}", 5, "yearly", "Admission number"),
    SequenceTemplate("register_no", "{college_code}{yy}{seq:4}", 4, "yearly", "Student register number"),
    SequenceTemplate("employee_id", "EMP{seq:5}", 5, "never", "Employee id"),
    SequenceTemplate("hall_ticket_no", "HT{yy}{term}{seq:6}", 6, "per_term", "Hall ticket number"),
    SequenceTemplate("fee_receipt_no", "RCP/{yyyy}/{seq:6}", 6, "yearly", "Fee receipt"),
    SequenceTemplate("certificate_no", "CERT/{yyyy}/{seq:5}", 5, "yearly", "Certificate number"),
)


def sequence_template_json() -> list[dict[str, Any]]:
    return [
        {
            "scope_key": s.scope_key,
            "pattern": s.pattern,
            "padding": s.padding,
            "reset_policy": s.reset_policy,
            "label": s.label,
        }
        for s in NUMBER_SEQUENCE_TEMPLATE
    ]
