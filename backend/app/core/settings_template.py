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
