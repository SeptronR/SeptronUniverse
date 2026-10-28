"""Institution settings template, theme tokens and number-sequence patterns — Prompts/03 §03.2 / §03.6.

Single source for revision ``0003_phase03_settings_seed`` (stored in ``platform_settings['settings_template']``,
``['theme_tokens']`` and ``['number_sequence_template']``), for ``SettingsService`` (type validation, defaults,
``is_public``) and for ``seed_institution_defaults(pack)`` (institution rows). Keys are ``category.key``; the value
types are ``str | int | bool | list | json | enum`` (``enum`` carries ``choices``). ``integrations`` keeps provider
**overrides** only — secrets live in ``integration_connections`` (Phase 41), never here.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from app.enums.accreditation import DEFAULT_DISCLOSURE_ITEMS
from app.enums.affiliation import DEFAULT_CHECKLISTS, DEFAULT_SUBMISSION_WINDOWS, DEFAULT_VALIDATION_RULES
from app.enums.phd import DEFAULT_PHD_RULES
from app.enums.research import DEFAULT_API_SCHEME, DEFAULT_INCENTIVE_SLABS

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
    # Phase 43 hardening (posture checks read these; mfa_grace_until is written by the MFA enforcement action)
    SettingDef("security", "mfa_grace_until", "str", None, label="MFA enforcement grace ends (ISO date-time)"),
    SettingDef("security", "session_max_days", "int", 7, min=1, max=90, label="Maximum session age (days)"),
    SettingDef("security", "concurrent_sessions", "json", {"controller_of_examinations": 3}, label="Concurrent sessions per role"),
    SettingDef("security", "upload_max_mb", "int", 25, min=1, max=200, label="Upload limit (MB)"),
    SettingDef("security", "api_key_unused_days", "int", 90, min=7, max=365, label="Warn on API keys unused for (days)"),
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
    # assessment (Phase 13) — marks deadline after instantiation, auto-lock after the deadline
    SettingDef(
        "assessment", "marks_deadline_days", "int", 14, label="Marks entry deadline (days after instantiation)", min=1
    ),
    SettingDef(
        "assessment", "auto_lock_days", "int", 7, label="Auto-lock verified marks N days after the deadline", min=0
    ),
    # fees (Phase 12) — GSTIN on taxable invoices, reminders, overdue holds, linkage due days, no-dues offices
    SettingDef("fees", "gstin", "str", None, label="GSTIN printed on taxable invoices / receipts"),
    SettingDef("fees", "reminder_days", "json", [7, 1, -7], label="Due reminders: days before (+) / after (-) due"),
    SettingDef(
        "fees", "hold_on_overdue_days", "int", 0, label="Place holds after N days overdue (0 = off)", min=0, max=365
    ),
    SettingDef("fees", "overdue_hold_types", "json", ["registration", "exam"], label="Hold types placed when overdue"),
    SettingDef("fees", "linkage_due_days", "int", 7, label="Due days of linkage invoices (condonation …)", min=0),
    SettingDef("fees", "no_dues_departments", "json", None, label="No-dues offices per purpose (empty = defaults)"),
    # exams
    SettingDef("exams", "valuation_mode_default", "enum", "single", False, ("single", "double")),
    SettingDef("exams", "discrepancy_pct_default", "int", 15, min=0, max=100),
    SettingDef("exams", "hall_ticket_requires_no_dues", "bool", True),
    # exams (Phase 14) — duty remuneration per role (paise); empty = built-in defaults
    SettingDef("exams", "duty_remuneration", "json", None, label="Exam duty remuneration per role (paise)"),
    SettingDef(
        "exams",
        "eligibility_requires_fee_clear",
        "bool",
        False,
        label="Overdue fees make a student ineligible (Phase 11)",
    ),
    SettingDef("exams", "result_public_lookup", "bool", False, True),
    # exams (Phase 15) — coding, evaluator conflicts, script retention, valuation remuneration (paise per script)
    SettingDef("exams", "bundle_size", "int", 30, label="Answer scripts per bundle", min=1, max=500),
    SettingDef(
        "exams", "allow_teacher_evaluation", "bool", False, label="Teachers may value their own course's scripts"
    ),
    SettingDef(
        "exams", "script_retention_months", "int", 6, label="Archive scripts N months after publication", min=1, max=120
    ),
    SettingDef("exams", "valuation_remuneration", "json", None, label="Valuation remuneration per script (paise)"),
    # exams (Phase 16) — malpractice appeals, transcript fees (paise per copy by type), public rank lists
    SettingDef("exams", "malpractice_appeal_days", "int", 30, label="Malpractice appeal window (days)", min=1, max=365),
    SettingDef("exams", "transcript_fees", "json", None, label="Transcript fee per copy by type (paise)"),
    SettingDef("exams", "rank_list_public", "bool", False, label="Publish masked rank lists publicly"),
    # obe (Phase 17) — student self view of CO achievement, auto-run on result publication, strict prerequisites
    SettingDef("obe", "show_students", "bool", False, label="Students see their own CO achievement"),
    SettingDef("obe", "auto_run", "bool", True, label="Compute CO attainment when results are published"),
    SettingDef("obe", "strict_prereq", "bool", False, label="Refuse attainment runs before CIA lock / publication"),
    # degrees (Phase 18) — dues rule, award needs convocation registration
    SettingDef("degrees", "zero_outstanding_ok", "bool", False, label="Zero outstanding fees counts as dues cleared"),
    SettingDef("degrees", "award_requires_registration", "bool", False, label="Awards only for convocation registrants"),
    # library (Phase 19) — member rules, blocks, holds, reservations, lost books, ILL
    SettingDef("library", "member_rules", "json", None, label="Loan rules per member type"),
    SettingDef("library", "block_fine_threshold_paise", "int", 50000, label="Block borrowing above this unpaid fine", min=0),
    SettingDef("library", "block_overdue_days", "int", 30, label="Block borrowing when a book is overdue this long", min=1, max=365),
    SettingDef("library", "hold_after_days", "int", 30, label="Place a library hold after N days overdue", min=1, max=365),
    SettingDef("library", "hold_hours", "int", 48, label="Reservation pickup window (hours)", min=1, max=336),
    SettingDef("library", "weekly_off", "json", ["sunday"], label="Library weekly-off days"),
    SettingDef("library", "allow_reserve_available", "bool", False, label="Allow reserving titles with copies on the shelf"),
    SettingDef("library", "one_copy_per_title", "bool", True, label="One copy of a title per member"),
    SettingDef("library", "lost_replacement_pct", "int", 150, label="Lost book charge (% of price)", min=0, max=1000),
    SettingDef("library", "found_cancels_invoice", "bool", True, label="A found lost book cancels its unpaid charge"),
    SettingDef("library", "ill_students_allowed", "bool", False, label="Students may request inter-library loans"),
    # hostel
    SettingDef("hostel", "guardian_otp_required_for_home_leave", "bool", True),
    SettingDef("hostel", "late_return_grace_minutes", "int", 15, min=0, max=720),
    # hostel (Phase 20) — consent, gate, roll-call, mess, allotment
    SettingDef("hostel", "guardian_otp_required_for", "json", ["home_leave", "medical"], label="Leave types needing guardian OTP"),
    SettingDef("hostel", "minor_requires_otp", "bool", True, label="Minors always need guardian consent"),
    SettingDef("hostel", "late_grace_minutes", "int", 30, label="Late-return grace (minutes)", min=0, max=720),
    SettingDef("hostel", "absconding_after_hours", "int", 12, label="Absconding after N hours overdue", min=1, max=168),
    SettingDef("hostel", "rebate_min_consecutive_days", "int", 5, label="Minimum consecutive days for a mess rebate", min=1, max=60),
    SettingDef("hostel", "rebate_requires_leave", "bool", False, label="Mess rebates need an approved hostel leave"),
    SettingDef("hostel", "roll_call_time", "str", "21:30", label="Night roll-call time (HH:MM)"),
    SettingDef("hostel", "outpass_auto_approve", "bool", False, label="Auto-approve out-passes without pending consent"),
    SettingDef("hostel", "accept_days", "int", 7, label="Days to pay before an allotment lapses", min=1, max=60),
    SettingDef("hostel", "deposit_once", "bool", True, label="Caution deposit collected once"),
    SettingDef("hostel", "fee_before_checkin", "bool", True, label="Hostel fee must be paid before check-in"),
    SettingDef("hostel", "room_type_fallback", "bool", True, label="Allot any room type when the preferred is full"),
    SettingDef("hostel", "mess_billing_mode", "enum", "postpaid", False, ("postpaid", "prepaid")),
    SettingDef("hostel", "eviction_hold_days", "int", 365, label="Hostel hold after eviction (days)", min=0, max=3650),
    SettingDef("hostel", "girls_guardian_visitors_only", "bool", False, label="Girls hostels: guardian visitors only"),
    SettingDef("hostel", "priority_weights", "json", None, label="Allotment priority weights"),
    SettingDef("hostel", "application_window", "json", None, label="Application window per academic year"),
    # transport (Phase 21)
    SettingDef("transport", "trip_schedule", "json", {"pickup": "07:00", "drop": "16:30"}, label="Default trip times"),
    SettingDef("transport", "gps_ping_interval_s", "int", 15, label="GPS ping interval (s)", min=5, max=300),
    SettingDef("transport", "eta_notify_minutes", "int", 5, label="Bus-approaching alert (minutes before)", min=1, max=60),
    SettingDef("transport", "expiry_alert_days", "int", 30, label="Vehicle document alert (days before)", min=1, max=180),
    SettingDef("transport", "capacity_hard_limit", "bool", True, label="Refuse allocations beyond vehicle capacity"),
    SettingDef("transport", "block_expired_vehicles", "bool", True, label="Block vehicles with expired insurance / fitness / permit"),
    SettingDef("transport", "self_service_requests", "bool", True, label="Students / staff may request allocations"),
    SettingDef("transport", "prorata_change", "bool", True, label="Invoice the pro-rata difference on a route change"),
    SettingDef("transport", "fee_grace_days", "int", 15, label="Days after the due date before suspension", min=0, max=120),
    SettingDef("transport", "notify_boarding", "bool", True, label="Notify guardians on boarding / alighting"),
    SettingDef("transport", "working_days", "json", [0, 1, 2, 3, 4, 5], label="Trip days (Mon=0)"),
    # inventory & procurement (Phase 22)
    SettingDef("inventory", "po_approval_threshold_paise", "int", 10000000, label="PO amount needing the workflow (paise)", min=0),
    SettingDef("inventory", "bill_approval_threshold_paise", "int", 10000000, label="Bill amount needing the workflow (paise)", min=0),
    SettingDef("inventory", "three_quotes_above_paise", "int", 2500000, label="Three quotations above (paise)", min=0),
    SettingDef("inventory", "write_off_approval_paise", "int", 500000, label="Write-off value needing an approval ref (paise)", min=0),
    SettingDef("inventory", "depreciation_defaults", "json", {"furniture": {"method": "wdv", "rate": 10}, "it": {"method": "slm", "rate": 33.33}}, label="Depreciation by category"),
    SettingDef("inventory", "salvage_pct", "int", 5, label="Salvage floor (% of cost)", min=0, max=100),
    SettingDef("inventory", "audit_cycle_months", "int", 12, label="Physical audit cycle (months)", min=1, max=60),
    SettingDef("inventory", "bill_variance_pct", "int", 2, label="Three-way match tolerance (%)", min=0, max=100),
    SettingDef("inventory", "tds_threshold_paise", "int", 3000000, label="TDS above (paise)", min=0),
    SettingDef("inventory", "tds_rates", "json", {"company": 2.0, "individual": 1.0, "firm": 1.0, "government": 0.0}, label="TDS % by supplier type"),
    # accounting & budget (Phase 23)
    SettingDef("accounting", "financial_year_start_month", "int", 4, label="Financial year starts (month)", min=1, max=12),
    SettingDef("accounting", "expense_approval_threshold_paise", "int", 5000000, label="Expense amount needing the workflow (paise)", min=0),
    SettingDef("accounting", "document_required_paise", "int", 1000000, label="Attachment required above (paise)", min=0),
    SettingDef("accounting", "budget_hard_stop", "bool", True, label="Refuse expenses beyond the budget"),
    SettingDef("accounting", "gst_number", "str", None, label="GSTIN of the institution"),
    SettingDef("accounting", "tally_company_name", "str", None, label="Tally company name"),
    SettingDef("accounting", "mappings", "json", None, label="Ledger account mappings"),
    # mentoring, early warning, grievances, discipline, surveys, clubs (Phase 27)
    SettingDef("mentoring", "default_ratio", "int", 20, label="Mentees per mentor", min=1, max=200),
    SettingDef("mentoring", "allocation_rule", "str", "round_robin", choices=("section_advisor", "round_robin", "department"), label="Default allocation rule"),
    SettingDef("mentoring", "min_sessions_per_term", "int", 2, label="Minimum mentoring sessions per term", min=0, max=20),
    SettingDef("mentoring", "carry_forward", "bool", True, label="Carry mentors forward to the next term"),
    SettingDef("risk", "weights", "json", {"attendance": 35, "cia": 25, "dues": 10, "standing": 15, "hostel": 5, "engagement": 10}, label="Risk factor weights (sum 100)"),
    SettingDef("risk", "thresholds", "json", {"medium": 40, "high": 65}, label="Risk level thresholds"),
    SettingDef("risk", "show_to_student", "bool", False, label="Students see their own risk level"),
    SettingDef("risk", "cia_pass_pct", "int", 40, label="CIA pass % used by the risk score", min=0, max=100),
    # analytics / early warning (Phase 35) — read-model refresh cadence, KPI targets + alert recipients, digests, the public
    # website counters, intervention types and cohort / intervention alert thresholds
    SettingDef("analytics", "refresh_minutes", "json", {"mv_kpi_daily": 15, "mv_attendance_term": 60, "mv_fees_position": 30, "default": 120}, label="Read-model refresh interval per view (minutes)"),
    SettingDef("analytics", "targets", "json", {"attendance_pct": 75, "fee_collection_pct": 90, "result_pass_pct": 85, "placement_pct": 70, "grievance_sla_pct": 95}, label="KPI targets"),
    SettingDef("analytics", "alert_recipients", "json", {"default": ["institution_admin", "vice_chancellor", "registrar"]}, label="KPI alert recipients per KPI (role slugs / user ids)"),
    SettingDef("analytics", "digest", "json", {"weekly": ["vice_chancellor", "registrar"], "daily": ["hod"]}, label="Dashboard digest roles per cadence"),
    SettingDef("analytics", "public_counter_keys", "list", ["students_active", "programmes", "faculty_count"], label="KPI keys shown on the public website"),
    SettingDef("risk", "intervention_types", "list", ["mentor_meeting", "guardian_call", "counselling", "fee_plan", "remedial_class", "hostel_warden", "other"], label="Intervention types"),
    SettingDef("risk", "alert_threshold_pct", "int", 15, label="Cohort alert: department high-risk share above (%)", min=1, max=100),
    SettingDef("risk", "intervention_due_days", "int", 14, label="High risk without intervention for N days → reminder", min=1, max=90),
    # reports (Phase 36) — inline preview / run row caps, file retention, schedule hours (institution TZ), statutory
    # sign-off roles per code, builder PII masking default
    SettingDef("reports", "max_inline_rows", "int", 2000, label="Inline preview row cap", min=100, max=10000),
    SettingDef("reports", "max_rows", "int", 500000, label="Report row cap", min=1000, max=2000000),
    SettingDef("reports", "retention_days", "int", 30, label="Report file retention (days)", min=1, max=365),
    SettingDef("reports", "schedule_hours_allowed", "json", [5, 22], label="Scheduled report hours [from, to] (institution time)"),
    SettingDef("reports", "statutory_signoff_roles", "json", {"aishe": ["registrar", "principal"], "nirf": ["iqac_coordinator", "principal"], "aicte": ["principal"], "aicte_eoa": ["principal"], "ugc_annual": ["registrar"], "nsp": ["accountant", "registrar"], "nsp_return": ["accountant", "registrar"], "fee_regulatory": ["accountant", "principal"], "rti_annual": ["pio"], "phd_awarded": ["research_cell", "registrar"], "placement_nirf": ["placement_officer", "iqac_coordinator"]}, label="Statutory sign-off roles per report"),
    SettingDef("reports", "builder_pii_default_masked", "bool", True, label="Builder masks PII columns by default"),
    # audit / retention (Phase 37) — integrity checks, signed daily digests, anomaly rules, alert recipients; the
    # retention policy per data class (an institution may shorten, never lengthen beyond RETENTION_MAXIMUMS)
    SettingDef("audit", "chain_verify_daily", "bool", True, label="Verify the audit hash chain daily"),
    SettingDef("audit", "digest_signing_key_id", "str", "platform-default", label="Digest signing key id (platform key)"),
    SettingDef("audit", "anomaly_rules", "json", [{"rule": "pii_unmask_burst", "threshold": 50, "window_minutes": 10}, {"rule": "export_off_hours", "hours": [0, 6]}, {"rule": "login_failures_per_ip", "threshold": 30, "window_minutes": 15}, {"rule": "impersonation_writes", "threshold": 1}], label="Security anomaly rules"),
    SettingDef("audit", "alert_recipients", "list", ["institution_admin", "security_officer"], label="Audit / anomaly alert recipients (role slugs)"),
    SettingDef("audit", "sensitive_change_notify", "list", ["vice_chancellor"], label="Roles notified of sensitive settings changes"),
    SettingDef("privacy", "retention", "json", {"login_history_days": 365, "notifications_days": 180, "message_logs_days": 365, "domain_events_days": 90, "webhook_deliveries_days": 90, "job_files_days": 30, "report_files_days": 30, "document_previews_days": 7, "visitor_pii_days": 90, "gps_logs_days": 180, "audit_logs_archive_after_years": 2, "attendance_archive_after_years": 3, "legal_hold": []}, label="Retention policy per data class"),
    SettingDef("security", "jwt_kid", "str", None, label="JWT signing key id (platform)"),
    # portals, PWA, notification centre, tours & web i18n (Phase 39) — branding falls back to institution_profile
    SettingDef("portals", "branding", "json", {"app_name": None, "short_name": None, "theme_color": "#4f46e5", "background_color": "#f8fafc", "icon_url": None, "splash_url": None}, True, label="Portal / PWA branding"),
    SettingDef("portals", "student_home_widgets", "list", ["timetable_today", "attendance_summary", "dues", "results_latest", "notices", "requests_open"], label="Student portal Home widgets"),
    SettingDef("portals", "parent_require_consent", "bool", True, label="Parents see only wards who consented to the guardian portal"),
    SettingDef("portals", "faculty_show_admin_switch", "bool", True, label="Faculty with admin grants see the Admin-view switch"),
    SettingDef("notifications", "categories", "list", ["academics", "attendance", "exams", "fees", "hostel", "library", "placement", "approvals", "mentoring", "events", "announcements", "security", "system"], label="Notification centre categories"),
    SettingDef("notifications", "digest_default", "str", "none", choices=("none", "daily", "weekly"), label="Default digest for new users"),
    SettingDef("notifications", "quiet_hours_default", "json", {"from": "22:00", "to": "07:00"}, label="Default quiet hours (institution time)"),
    SettingDef("i18n", "web_locales", "list", ["en", "hi"], True, label="Web portal languages"),
    SettingDef("i18n", "overrides", "json", {}, label="Vocabulary overrides per locale {locale: {key: text}}"),
    SettingDef("pwa", "cache_ttl", "json", {"timetable": 86400, "attendance": 21600, "dues": 3600, "results": 86400, "notices": 3600}, True, label="Offline cache TTL per data class (seconds)"),
    SettingDef("tours", "disabled", "list", [], label="Routes whose guided tours are disabled"),
    # public website (Phase 40) — page cache, enquiry rate limit, notice categories, faculty directory allow-list,
    # public result lookup gate, catalogue fee summary, analytics provider, reserved slugs
    SettingDef("website", "cache_ttl_seconds", "int", 300, label="Public page cache (seconds)", min=0, max=86400),
    SettingDef("website", "enquiry_rate_limit", "str", "5/10m", label="Enquiries per IP (count/window)"),
    SettingDef("website", "notice_categories", "list", ["general", "admissions", "examinations", "tenders", "recruitment", "events", "scholarships", "results"], True, label="Notice categories"),
    SettingDef("website", "faculty_directory_fields", "list", ["name", "designation", "department", "qualification", "email_public", "profile_photo", "research_interests"], label="Faculty directory fields (allow-list)"),
    SettingDef("website", "faculty_directory_opt_out", "list", [], label="Staff ids hidden from the faculty directory"),
    SettingDef("website", "results_public_lookup", "bool", False, label="Public result lookup on the website"),
    SettingDef("website", "results_public_show_marks", "bool", False, label="Show marks in the public lookup"),
    SettingDef("website", "catalog_show_fees", "bool", False, label="Show indicative fees in the catalogue"),
    SettingDef("website", "analytics_provider", "str", "none", choices=("none", "plausible", "ga4"), label="External analytics"),
    SettingDef("website", "analytics_site_id", "str", None, label="Plausible domain / GA4 measurement id"),
    SettingDef("website", "reserved_slugs", "list", ["admin", "api", "app", "login", "site", "static", "assets", "www", "status", "docs"], label="Reserved slugs / sub-domains"),
    # integrations hub, webhooks, API keys, migration toolkit (Phase 41)
    SettingDef("integrations", "circuit_breaker", "json", {"failures": 5, "window_s": 60, "open_s": 120}, label="Circuit breaker per connection"),
    SettingDef("integrations", "timeouts_s", "json", {"payments": 15, "sms": 10, "email": 20, "whatsapp": 10, "push": 10, "sso": 10, "lti": 10, "video": 15, "digilocker": 30, "abc": 30, "nsp": 60, "mooc": 20, "lookup": 15, "plagiarism": 60, "repository": 60, "library": 20, "device": 10, "face": 20, "esign": 60, "ekyc": 30, "accounting": 60, "workspace": 30, "llm": 60}, label="Provider timeouts (seconds)"),
    SettingDef("integrations", "retry", "json", {"attempts": 5, "backoff": "exponential", "max_s": 900}, label="Provider retry policy"),
    SettingDef("webhooks", "retry_schedule_s", "list", [60, 300, 1800, 7200, 43200], label="Webhook retry schedule (seconds)"),
    SettingDef("webhooks", "dead_letter_after", "int", 5, label="Dead-letter after N attempts", min=1, max=20),
    SettingDef("api_keys", "max_per_institution", "int", 20, label="Active API keys per institution", min=1, max=200),
    SettingDef("api_keys", "default_rate_limit_per_minute", "int", 600, label="Default API key rate limit (per minute)", min=1, max=100000),
    SettingDef("imports", "chunk_size", "int", 500, label="Import apply chunk size", min=50, max=5000),
    SettingDef("imports", "max_rows", "int", 200000, label="Maximum rows per import", min=100, max=1000000),
    SettingDef("imports", "rollback_window_days", "int", 30, label="Import rollback window (days)", min=1, max=365),
    SettingDef("grievances", "sla_hours", "json", {"harassment": 24, "ragging": 24, "discrimination": 48, "exam": 72, "fee": 72, "academic": 120, "hostel": 72, "infrastructure": 120, "other": 120}, label="Grievance SLA hours by category"),
    SettingDef("grievances", "committee_routing", "json", {"harassment": "icc", "ragging": "anti_ragging", "discrimination": "sc_st_cell|obc_cell", "default": "grievance_cell"}, label="Category to committee routing"),
    SettingDef("grievances", "auto_close_days", "int", 7, label="Auto-close resolved grievances after (days)", min=1, max=60),
    SettingDef("discipline", "sanction_scale", "json", {"minor": ["warning", "community_service"], "moderate": ["fine", "community_service", "hostel_eviction"], "major": ["suspension", "debar_placement"], "gross": ["expulsion"], "max_fine_paise": 2500000, "appeal_window_days": 15}, label="Sanction scale, fine cap and appeal window"),
    SettingDef("discipline", "suspension_attendance", "str", "absent", choices=("absent", "exempt"), label="Attendance during suspension"),
    SettingDef("surveys", "sss_template", "json", None, label="SSS question template (NAAC 21 items; empty = shipped)"),
    SettingDef("surveys", "min_responses", "int", 5, label="Minimum responses before faculty see results", min=1, max=100),
    SettingDef("surveys", "publish_summary", "bool", False, label="Publish survey summaries to students"),
    SettingDef("surveys", "actions", "json", None, label="Action taken on feedback (when OBE is off)"),
    SettingDef("clubs", "hours_to_credits", "json", [], label="Activity hours to credit mapping [{course_id, min_hours, activity_types?}]"),
    # placement, internships & training (Phase 28)
    SettingDef("placement", "eligibility_defaults", "json", {"min_cgpa": 6.0, "max_active_backlogs": 0, "max_history_backlogs": 2, "min_10th_pct": 60, "min_12th_pct": 60, "max_gap_years": 1, "allowed_if_already_placed": False}, label="Default drive eligibility rules"),
    SettingDef("placement", "policy_defaults", "json", {"max_offers": 1, "dream_ctc_threshold_paise": 100000000, "allow_upgrade_if_dream": True, "opt_out_allowed": True}, label="Default placement policy"),
    SettingDef("placement", "consented_fields", "json", ["name", "program", "cgpa", "backlogs", "resume", "skills", "achievements", "email", "phone"], label="Profile fields recruiters may see (with student consent)"),
    SettingDef("placement", "blacklist_rules", "json", {"no_show_after_shortlist": 2, "offer_decline_after_accept": 1}, label="Automatic blacklist rules"),
    SettingDef("placement", "internship_min_weeks", "int", 4, label="Minimum internship weeks for credit mapping", min=1, max=52),
    SettingDef("placement", "nirf_median_basis", "str", "accepted_offers", choices=("accepted_offers", "all_offers", "joined"), label="NIRF median salary basis"),
    SettingDef("placement", "reevaluate_on_results", "bool", False, label="Re-evaluate open drive applications when results are republished"),
    # alumni, endowments & fundraising (Phase 29)
    SettingDef("alumni", "auto_create_on_graduation", "bool", True, label="Create the alumni profile on graduation"),
    SettingDef("alumni", "claim_verification", "str", "email_or_phone_plus_registration_number", choices=("email_or_phone_plus_registration_number", "coordinator_only"), label="Legacy profile claim verification"),
    SettingDef("alumni", "directory_default_fields", "json", ["name", "batch", "program", "city", "company", "designation"], label="Directory fields shown by default (alumni may narrow)"),
    SettingDef("alumni", "directory_open_to_students", "bool", False, label="Students may search the alumni directory"),
    SettingDef("alumni", "jobs_moderation", "bool", True, label="Alumni job posts need coordinator approval"),
    SettingDef("alumni", "jobs_open_to_students", "bool", False, label="Final-year students see the alumni jobs board"),
    SettingDef("alumni", "engagement_weights", "json", {"profile_update": 5, "event_attended": 10, "donation": 20, "mentoring": 15, "job_post": 10, "survey": 5}, label="Engagement score weights"),
    SettingDef("alumni", "job_expiry_days", "int", 60, label="Default alumni job post validity (days)", min=1, max=365),
    SettingDef("fundraising", "80g", "json", {"registration_no": None, "valid_from": None, "valid_to": None, "signatory": None}, label="80G registration (number, validity, signatory)"),
    SettingDef("fundraising", "receipt_sequence", "str", "80g:{fy}", label="80G receipt number sequence key"),
    SettingDef("fundraising", "min_online_paise", "int", 10000, label="Minimum online donation (paise)", min=100),
    SettingDef("fundraising", "pan_threshold_paise", "int", 200000, label="PAN required on 80G receipts above (paise)", min=0),
    SettingDef("fundraising", "pledges", "bool", False, label="Allow pledges with reminders"),
    # research & faculty development (Phase 30)
    SettingDef("research", "api_score_scheme", "json", DEFAULT_API_SCHEME, label="API / CAS score scheme (UGC CAS 2018 category tables)"),
    SettingDef("research", "publication_incentive_slabs", "json", DEFAULT_INCENTIVE_SLABS, label="Publication incentive slabs (rupees per indexing / author position)"),
    SettingDef("research", "seed_grant_max_paise", "int", 50000000, label="Seed grant maximum (paise)", min=0),
    SettingDef("research", "travel_grant_max_paise", "int", 5000000, label="Travel grant maximum (paise)", min=0),
    SettingDef("research", "incentive_annual_cap_paise", "int", 20000000, label="Incentives per faculty per year cap (paise)", min=0),
    SettingDef("research", "incentive_dean_threshold_paise", "int", 2000000, label="Incentives above this go to the dean / principal step (paise)", min=0),
    SettingDef("research", "consultancy_share_pct", "json", {"institution": 30, "faculty": 70}, label="Consultancy revenue share (%)"),
    SettingDef("research", "duplicate_doi_policy", "str", "block", choices=("block", "warn"), label="Duplicate DOI policy"),
    SettingDef("research", "mou_expiry_alert_days", "int", 90, label="MoU expiry alert window (days)", min=1, max=365),
    SettingDef("research", "import_sources", "json", ["crossref", "scopus", "orcid"], label="Bibliographic import sources"),
    SettingDef("research", "fdp_hours_target", "int", 40, label="Annual FDP hours target per faculty", min=0, max=500),
    SettingDef("research", "ethics_required_for_categories", "json", ["clinical", "animal", "biosafety"], label="Project categories that need an ethics approval before start"),
    SettingDef("research", "patent_renewal_months", "int", 12, label="Patent renewal reminder interval (months)", min=1, max=60),
    # PhD & research-scholar management (Phase 31) — UGC PhD Regulations 2022 defaults from the IN pack
    SettingDef("phd", "rules", "json", DEFAULT_PHD_RULES, label="PhD rules (guide load, coursework, durations, plagiarism, examiners, fellowships)"),
    SettingDef("phd", "panel_vc_approval", "bool", False, label="Examiner panels also need the Vice-Chancellor's approval"),
    SettingDef("phd", "thesis_fee_invoice", "bool", False, label="Raise a thesis submission fee invoice"),
    SettingDef("phd", "fellowship_payment_route", "str", "payout", choices=("payout", "payroll"), label="Fellowship payment route (Phase 23 payout / Phase 06 payroll)"),
    # accreditation & compliance / IQAC (Phase 32)
    SettingDef("accreditation", "period_type_default", "str", "academic_year", choices=("academic_year", "calendar_year", "financial_year", "five_year"), label="Default metric period type"),
    SettingDef("accreditation", "compute_schedule", "str", "weekly", choices=("weekly", "manual"), label="Metric compute schedule"),
    SettingDef("accreditation", "override_requires_verification", "bool", True, label="Metric overrides need verification (principal / IQAC)"),
    SettingDef("accreditation", "evidence_max_mb", "int", 25, label="Evidence upload size limit (MB)", min=1, max=500),
    SettingDef("accreditation", "disclosure_items", "json", DEFAULT_DISCLOSURE_ITEMS, label="Mandatory disclosure items (website feed)"),
    SettingDef("accreditation", "custom_criteria", "json", {}, label="Custom criterion sub-items per framework"),
    # governance: committees, meetings, legal, RTI, e-File, policies (Phase 33)
    SettingDef("governance", "minutes_approval", "str", "chair", choices=("chair", "none"), label="Minutes approval (chair via workflow / none)"),
    SettingDef("governance", "notice_days", "int", 7, label="Meeting notice period (days)", min=0, max=60),
    SettingDef("governance", "atr_due_days", "int", 30, label="Default action-taken report due (days)", min=1, max=365),
    SettingDef("governance", "quorum_block", "bool", True, label="Block minutes when the quorum is not met (409 QUORUM_NOT_MET)"),
    SettingDef("rti", "response_days", "int", 30, label="RTI response period (days)", min=1, max=90),
    SettingDef("rti", "fee_paise", "int", 1000, label="RTI application fee (paise)", min=0, max=1000000),
    SettingDef("rti", "appeal_days", "int", 30, label="RTI first appeal window (days)", min=1, max=90),
    SettingDef("efile", "pendency_sla_days", "int", 7, label="e-File pendency SLA with one holder (days)", min=1, max=90),
    SettingDef("legal", "hearing_reminder_days", "json", [7, 1], label="Hearing reminder offsets (days before)"),
    SettingDef("policies", "ack_required_categories", "json", ["conduct", "it", "posh"], label="Policy categories that need acknowledgement"),
    # affiliation management (Phase 34; university tenants)
    SettingDef("affiliation", "document_checklists", "json", DEFAULT_CHECKLISTS, label="Document checklist per application type"),
    SettingDef("affiliation", "inspection_required_years", "int", 3, label="Renewal / extension: inspect when the last inspection is older than (years)", min=0, max=10),
    SettingDef("affiliation", "deficiency_compliance_days", "int", 30, label="Deficiency compliance period (days)", min=1, max=180),
    SettingDef("affiliation", "order_validity_years", "json", {"provisional": 1, "permanent": 5}, label="Order validity per approval status (years)"),
    SettingDef("affiliation", "submission_windows", "json", DEFAULT_SUBMISSION_WINDOWS, label="College data submission due dates (anchor+Nd)"),
    SettingDef("affiliation", "submission_validation_rules", "json", DEFAULT_VALIDATION_RULES, label="Submission validation rules"),
    SettingDef("affiliation", "results_require_accepted", "json", ["cia_marks", "attendance_eligibility", "practical_marks", "exam_registrations"], label="Submission types that gate central result processing"),
    SettingDef("affiliation", "centre_capacity_buffer_pct", "int", 10, label="Exam centre capacity buffer (%)", min=0, max=50),
    SettingDef("affiliation", "expiry_reminder_days", "int", 90, label="Programme approval expiry reminder (days before valid_to)", min=7, max=365),
    SettingDef("affiliation", "appeal_as_extension", "bool", True, label="Review / appeal requests are filed as extension applications"),
    # document templates & certificate requests (Phase 26)
    SettingDef("documents", "signatories", "json", {"registrar": {"name": "Registrar", "designation": "Registrar", "signature_url": None}, "principal": {"name": "Principal", "designation": "Principal", "signature_url": None}, "coe": {"name": "Controller of Examinations", "designation": "Controller of Examinations", "signature_url": None}}, label="Signatories (name, designation, signature image)"),
    SettingDef("documents", "request_rules", "json", {}, label="Certificate request rules per type (overrides of the shipped defaults)"),
    SettingDef("documents", "watermark", "json", {"text": None, "opacity": 0.2}, label="Default document watermark"),
    SettingDef("documents", "verify_shows_pdf", "bool", False, label="Public verification shows the PDF"),
    SettingDef("documents", "allow_parent_requests", "bool", False, label="Guardians may request certificates for wards"),
    SettingDef("documents", "college_overrides", "bool", False, label="Colleges may override templates"),
    SettingDef("documents", "signed_link_ttl_minutes", "int", 15, label="Signed download link validity (minutes)", min=1, max=1440),
    SettingDef("documents", "preview_retention_days", "int", 1, label="Preview retention (days)", min=0, max=30),
    # calendar, events & facilities (Phase 25)
    SettingDef("facilities", "sla_hours", "json", {"electrical": 24, "plumbing": 24, "it": 8, "network": 4, "furniture": 72, "cleaning": 12, "civil": 168, "security": 2, "asset": 48, "other": 48}, label="Service desk SLA hours by category"),
    SettingDef("facilities", "routing", "json", {"it": "it_cell", "network": "it_cell", "security": "security_officer"}, label="Ticket auto-routing (category → role or user id)"),
    SettingDef("facilities", "booking_lead_hours", "int", 24, label="Room booking lead time (hours)", min=0, max=720),
    SettingDef("facilities", "auto_approve_roles", "json", ["hod", "dean"], label="Roles whose bookings are auto-approved"),
    SettingDef("facilities", "visitor_pass_validity_hours", "int", 8, label="Visitor pass validity (hours)", min=1, max=168),
    SettingDef("facilities", "visitor_blacklist", "json", [], label="Blacklisted visitor phones"),
    SettingDef("facilities", "visitor_pii_retention_days", "int", 90, label="Visitor PII retention (days)", min=1),
    SettingDef("facilities", "sos_responders", "json", {"security": ["security_officer"], "medical": ["medical_officer", "security_officer"], "fire": ["security_officer", "estate_officer"], "sos": ["security_officer"]}, label="SOS responders by alert type (roles or user ids)"),
    SettingDef("facilities", "sos_escalate_minutes", "int", 3, label="SOS escalation interval (minutes)", min=1, max=60),
    SettingDef("facilities", "sos_rate_limit", "json", {"count": 3, "minutes": 10}, label="SOS rate limit per user"),
    SettingDef("facilities", "lost_found_retention_days", "int", 90, label="Lost & found retention (days)", min=1),
    SettingDef("facilities", "health_summary_consent", "bool", False, label="HOD / warden see visit summaries with consent"),
    SettingDef("facilities", "auto_close_days", "int", 3, label="Auto-close resolved tickets after (days)", min=1, max=60),
    SettingDef("facilities", "reopen_days", "int", 7, label="Reopen allowed within (days)", min=1, max=60),
    SettingDef("wallet", "max_balance_paise", "int", 500000, label="Wallet maximum balance (paise)", min=0),
    SettingDef("wallet", "topup_min_paise", "int", 5000, label="Wallet minimum top-up (paise)", min=0),
    SettingDef("wallet", "daily_spend_cap_paise", "int", None, label="Daily spend cap for minors (paise)"),
    # communication advanced (Phase 24)
    SettingDef("comms", "throttle_per_minute", "json", {"sms": 600, "whatsapp": 300, "email": 1200, "push": 5000}, label="Throttle per channel per minute"),
    SettingDef("comms", "campaign_approval_threshold_recipients", "int", 2000, label="Campaigns above N recipients need approval", min=1),
    SettingDef("comms", "quiet_hours_default", "json", {"from": "21:00", "to": "07:00"}, label="Default quiet hours"),
    SettingDef("comms", "assistant", "json", {"provider": "mock", "opt_in_required": True, "allowed_roles": [], "allow_pii_to_provider": False, "max_tokens": 800}, label="AI assistant"),
    SettingDef("comms", "bot_flows", "json", None, label="WhatsApp bot flows (override)"),
    SettingDef("comms", "segments", "json", [], label="Saved audience segments"),
    SettingDef("comms", "credits", "json", None, label="Message credits {sms, whatsapp} (absent = unmetered)"),
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
    SequenceTemplate("fee_invoice_no", "INV/{yyyy}/{seq:6}", 6, "yearly", "Fee invoice"),
    SequenceTemplate("certificate_no", "CERT/{yyyy}/{seq:5}", 5, "yearly", "Certificate number"),
    # Phase 18 — degree certificates and their serial numbers
    SequenceTemplate("degree", "DEG/{yyyy}/{seq:6}", 6, "yearly", "Degree certificate number"),
    SequenceTemplate("degree_serial", "SN{yyyy}{seq:7}", 7, "never", "Degree serial number"),
    # Phase 19 — library accession numbers and member codes
    SequenceTemplate("lib:acc", "ACC{seq:6}", 6, "never", "Library accession number"),
    SequenceTemplate("lib:member", "LM{yy}{seq:5}", 5, "yearly", "Library member code"),
    # Phase 21 — trip numbers (no monthly reset policy exists: yearly)
    SequenceTemplate("trip", "TRP{yyyy}{seq:6}", 6, "yearly", "Transport trip number"),
    # Phase 22 — indents, purchase orders, goods receipts, assets, items
    SequenceTemplate("indent", "IND/{yyyy}/{seq:5}", 5, "yearly", "Indent number"),
    SequenceTemplate("po", "PO/{yyyy}/{seq:5}", 5, "yearly", "Purchase order number"),
    SequenceTemplate("grn", "GRN/{yyyy}/{seq:5}", 5, "yearly", "Goods receipt number"),
    SequenceTemplate("asset", "AST{seq:6}", 6, "never", "Asset tag"),
    SequenceTemplate("item", "ITM{seq:5}", 5, "never", "Item code"),
    # Phase 26 — issued document numbers per type and statutory serial registers
    # Phase 27 - grievance tickets and disciplinary cases
    SequenceTemplate("grievance", "GRV/{yyyy}/{seq:5}", 5, "yearly", "Grievance ticket number"),
    SequenceTemplate("disc_case", "DC/{yyyy}/{seq:4}", 4, "yearly", "Disciplinary case number"),
    # Phase 33 - RTI requests, e-files and legal cases (resolutions are numbered per committee code under a row lock)
    SequenceTemplate("rti", "RTI/{yyyy}/{seq:4}", 4, "yearly", "RTI request number"),
    SequenceTemplate("efile", "EF/{yyyy}/{seq:5}", 5, "yearly", "e-File number"),
    SequenceTemplate("legal", "LC/{yyyy}/{seq:4}", 4, "yearly", "Legal case register number"),
    # Phase 34 - affiliation applications and orders
    SequenceTemplate("affil", "AFF/{yyyy}/{seq:4}", 4, "yearly", "Affiliation application number"),
    SequenceTemplate("order", "AO/{yyyy}/{seq:4}", 4, "yearly", "Affiliation order number"),
    SequenceTemplate("doc:id_card", "ID/{yyyy}/{seq:5}", 5, "yearly", "Document number (id_card)"),
    SequenceTemplate("doc:bonafide", "BON/{yyyy}/{seq:5}", 5, "yearly", "Document number (bonafide)"),
    SequenceTemplate("doc:character", "CHR/{yyyy}/{seq:5}", 5, "yearly", "Document number (character)"),
    SequenceTemplate("doc:conduct", "CON/{yyyy}/{seq:5}", 5, "yearly", "Document number (conduct)"),
    SequenceTemplate("doc:noc", "NOC/{yyyy}/{seq:5}", 5, "yearly", "Document number (noc)"),
    SequenceTemplate("doc:tc", "TC/{yyyy}/{seq:5}", 5, "yearly", "Document number (tc)"),
    SequenceTemplate("doc:migration", "MIG/{yyyy}/{seq:5}", 5, "yearly", "Document number (migration)"),
    SequenceTemplate("doc:course_completion", "CC/{yyyy}/{seq:5}", 5, "yearly", "Document number (course_completion)"),
    SequenceTemplate("doc:provisional", "PC/{yyyy}/{seq:5}", 5, "yearly", "Document number (provisional)"),
    SequenceTemplate("doc:degree", "DEG/{yyyy}/{seq:5}", 5, "yearly", "Document number (degree)"),
    SequenceTemplate("doc:grade_card", "GC/{yyyy}/{seq:5}", 5, "yearly", "Document number (grade_card)"),
    SequenceTemplate("doc:transcript", "TR/{yyyy}/{seq:5}", 5, "yearly", "Document number (transcript)"),
    SequenceTemplate("doc:hall_ticket", "HT/{yyyy}/{seq:5}", 5, "yearly", "Document number (hall_ticket)"),
    SequenceTemplate("doc:receipt", "DOC/{yyyy}/{seq:5}", 5, "yearly", "Document number (receipt)"),
    SequenceTemplate("doc:experience", "EXP/{yyyy}/{seq:5}", 5, "yearly", "Document number (experience)"),
    SequenceTemplate("doc:service", "SRV/{yyyy}/{seq:5}", 5, "yearly", "Document number (service)"),
    SequenceTemplate("doc:internship_noc", "INOC/{yyyy}/{seq:5}", 5, "yearly", "Document number (internship_noc)"),
    SequenceTemplate("doc:hostel_allotment", "HAL/{yyyy}/{seq:5}", 5, "yearly", "Document number (hostel_allotment)"),
    SequenceTemplate("doc:event_certificate", "EVC/{yyyy}/{seq:5}", 5, "yearly", "Document number (event_certificate)"),
    SequenceTemplate("doc:undertaking", "DOC/{yyyy}/{seq:5}", 5, "yearly", "Document number (undertaking)"),
    SequenceTemplate("doc:medical_certificate", "DOC/{yyyy}/{seq:5}", 5, "yearly", "Document number (medical_certificate)"),
    SequenceTemplate("doc:fee_structure_letter", "DOC/{yyyy}/{seq:5}", 5, "yearly", "Document number (fee_structure_letter)"),
    SequenceTemplate("doc:offer_letter", "DOC/{yyyy}/{seq:5}", 5, "yearly", "Document number (offer_letter)"),
    SequenceTemplate("doc:custom", "DOC/{yyyy}/{seq:5}", 5, "yearly", "Document number (custom)"),
    SequenceTemplate("doc:donation_receipt_80g", "DR/{yyyy}/{seq:5}", 5, "yearly", "Document number (donation_receipt_80g)"),
    SequenceTemplate("doc:alumni_membership_card", "ALM/{yyyy}/{seq:5}", 5, "yearly", "Document number (alumni_membership_card)"),
    SequenceTemplate("doc:phd_registration_letter", "PHDR/{yyyy}/{seq:5}", 5, "yearly", "Document number (phd_registration_letter)"),
    SequenceTemplate("doc:phd_synopsis_ack", "PHDS/{yyyy}/{seq:5}", 5, "yearly", "Document number (phd_synopsis_ack)"),
    SequenceTemplate("doc:phd_provisional_certificate", "PHDP/{yyyy}/{seq:5}", 5, "yearly", "Document number (phd_provisional_certificate)"),
    SequenceTemplate("doc:examiner_invitation", "PHDX/{yyyy}/{seq:5}", 5, "yearly", "Document number (examiner_invitation)"),
    SequenceTemplate("doc:meeting_notice", "MTN/{yyyy}/{seq:5}", 5, "yearly", "Document number (meeting_notice)"),
    SequenceTemplate("doc:minutes", "MIN/{yyyy}/{seq:5}", 5, "yearly", "Document number (minutes)"),
    SequenceTemplate("doc:resolution_extract", "RES/{yyyy}/{seq:5}", 5, "yearly", "Document number (resolution_extract)"),
    SequenceTemplate("doc:rti_response", "RTIR/{yyyy}/{seq:5}", 5, "yearly", "Document number (rti_response)"),
    SequenceTemplate("doc:office_order", "OO/{yyyy}/{seq:5}", 5, "yearly", "Document number (office_order)"),
    SequenceTemplate("doc:affiliation_order", "AFO/{yyyy}/{seq:5}", 5, "yearly", "Document number (affiliation_order)"),
    SequenceTemplate("doc:inspection_report", "INR/{yyyy}/{seq:5}", 5, "yearly", "Document number (inspection_report)"),
    SequenceTemplate("doc:deficiency_notice", "DFN/{yyyy}/{seq:5}", 5, "yearly", "Document number (deficiency_notice)"),
    SequenceTemplate("doc:centre_appointment", "CAP/{yyyy}/{seq:5}", 5, "yearly", "Document number (centre_appointment)"),
    SequenceTemplate("serial:degree", "DSR{seq:6}", 6, "never", "Serial register (degree)"),
    SequenceTemplate("serial:provisional", "PSR{seq:6}", 6, "never", "Serial register (provisional)"),
    SequenceTemplate("serial:transcript", "TSR{seq:6}", 6, "never", "Serial register (transcript)"),
    SequenceTemplate("serial:tc", "TCS{seq:6}", 6, "never", "Serial register (tc)"),
    SequenceTemplate("serial:migration", "MSR{seq:6}", 6, "never", "Serial register (migration)"),
    SequenceTemplate("serial:bonafide", "BSR{seq:6}", 6, "never", "Serial register (bonafide)"),
    # Phase 25 — service desk tickets and visitor passes
    SequenceTemplate("sr", "SR/{yyyy}/{seq:5}", 5, "yearly", "Service request number"),
    SequenceTemplate("visitor", "VP{yy}{seq:6}", 6, "yearly", "Visitor pass code"),
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
