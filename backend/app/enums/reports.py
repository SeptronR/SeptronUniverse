"""Report enums and the statutory pack — Prompts/36 §36.3, §36.6 ``statutory_service`` step 1.

``STATUTORY_DEFS`` is the regulatory pack's statutory-report list (docs/Regulatory_Pack_IN.md §2.6) expressed for the
renderers: period type, sections (each a provider in ``services/reports/statutory_sections.py``), the Phase 32
``compliance_submissions.submission_type`` the generated files are linked to (``None`` → the generation is kept in the
reports side store only), the source feature that must be on for a section's data and the due date (month, day) after
the period ends used by the weekly due calendar.
"""

from enum import StrEnum
from typing import Any


class ReportFormat(StrEnum):
    xlsx = "xlsx"
    csv = "csv"
    pdf = "pdf"
    docx = "docx"
    json = "json"


class ScheduleCadence(StrEnum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    termly = "termly"
    cron = "cron"


class StatutoryCode(StrEnum):
    aishe = "aishe"
    nirf = "nirf"
    aicte_eoa = "aicte_eoa"
    ugc_annual = "ugc_annual"
    nsp_return = "nsp_return"
    fee_regulatory = "fee_regulatory"
    minority_cell = "minority_cell"
    sc_st_cell = "sc_st_cell"
    anti_ragging = "anti_ragging"
    rti_annual = "rti_annual"
    phd_awarded = "phd_awarded"
    placement_nirf = "placement_nirf"
    affiliated_colleges = "affiliated_colleges"
    gst = "gst"


class StatutoryStatus(StrEnum):
    generated = "generated"
    in_review = "in_review"
    signed_off = "signed_off"
    submitted = "submitted"


REGISTERS: tuple[str, ...] = (
    "admission",
    "attendance",
    "fee",
    "results",
    "script_custody",
    "degree",
    "certificates",
    "leave",
    "stock",
    "assets",
    "library_issues",
    "hostel_occupancy",
    "visitor",
    "grievance",
)

# code → definition. ``sections``: provider keys; ``signoff`` defaults (overridden by reports.statutory_signoff_roles)
STATUTORY_DEFS: dict[str, dict[str, Any]] = {
    "aishe": {
        "name": "AISHE Data Capture Format",
        "period_type": "academic_year",
        "sections": ["institution", "programmes", "students", "staff", "infrastructure", "finance"],
        "submission_type": "aishe",
        "due": (1, 31),
        "signoff": ["registrar", "principal"],
        "formats": ["xlsx", "csv", "pdf"],
    },
    "nirf": {
        "name": "NIRF data capture (per discipline)",
        "period_type": "academic_year",
        "sections": ["institution", "nirf_metrics", "students", "staff", "placement", "phd", "research", "finance"],
        "submission_type": "nirf_data",
        "due": (12, 15),
        "signoff": ["iqac_coordinator", "principal"],
        "formats": ["xlsx", "csv", "pdf"],
        "disciplines": ["overall", "university", "college", "engineering", "management", "pharmacy", "law", "research"],
    },
    "aicte_eoa": {
        "name": "AICTE Extension of Approval data",
        "period_type": "academic_year",
        "sections": ["institution", "programmes", "staff", "infrastructure", "finance"],
        "submission_type": "aicte_approval",
        "due": (3, 31),
        "signoff": ["principal"],
        "formats": ["xlsx", "pdf"],
    },
    "ugc_annual": {
        "name": "UGC annual report",
        "period_type": "academic_year",
        "sections": ["institution", "programmes", "students", "staff", "research", "phd", "governance", "finance"],
        "submission_type": "ugc_annual",
        "due": (9, 30),
        "signoff": ["registrar"],
        "formats": ["docx", "pdf", "xlsx"],
    },
    "nsp_return": {
        "name": "NSP scholarship return",
        "period_type": "academic_year",
        "sections": ["scholarships"],
        "submission_type": "nsp_return",
        "due": (11, 30),
        "signoff": ["accountant", "registrar"],
        "formats": ["xlsx", "csv", "pdf"],
    },
    "fee_regulatory": {
        "name": "State fee-regulatory return",
        "period_type": "academic_year",
        "sections": ["fee_structure", "fee_collection"],
        "submission_type": None,
        "due": (6, 30),
        "signoff": ["accountant", "principal"],
        "formats": ["xlsx", "pdf"],
    },
    "minority_cell": {
        "name": "Minority cell return",
        "period_type": "academic_year",
        "sections": ["minority_students", "scholarships"],
        "submission_type": None,
        "due": (10, 31),
        "signoff": ["registrar"],
        "formats": ["xlsx", "pdf"],
    },
    "sc_st_cell": {
        "name": "SC/ST cell return",
        "period_type": "academic_year",
        "sections": ["category_students", "category_staff", "grievances_sc_st"],
        "submission_type": None,
        "due": (10, 31),
        "signoff": ["registrar"],
        "formats": ["xlsx", "pdf"],
    },
    "anti_ragging": {
        "name": "Anti-ragging compliance",
        "period_type": "academic_year",
        "sections": ["anti_ragging"],
        "submission_type": None,
        "due": (9, 15),
        "signoff": ["registrar", "principal"],
        "formats": ["pdf", "xlsx"],
    },
    "rti_annual": {
        "name": "RTI annual return",
        "period_type": "financial_year",
        "sections": ["rti"],
        "submission_type": None,
        "due": (5, 31),
        "signoff": ["pio"],
        "formats": ["xlsx", "pdf"],
    },
    "phd_awarded": {
        "name": "UGC PhD-awarded return",
        "period_type": "calendar_year",
        "sections": ["phd"],
        "submission_type": None,
        "due": (1, 31),
        "signoff": ["research_cell", "registrar"],
        "formats": ["xlsx", "pdf"],
    },
    "placement_nirf": {
        "name": "Placement statistics (NIRF format)",
        "period_type": "academic_year",
        "sections": ["placement"],
        "submission_type": None,
        "due": (12, 15),
        "signoff": ["placement_officer", "iqac_coordinator"],
        "formats": ["xlsx", "csv", "pdf"],
    },
    "affiliated_colleges": {
        "name": "Affiliated colleges list",
        "period_type": "academic_year",
        "sections": ["affiliated_colleges"],
        "submission_type": None,
        "due": (8, 31),
        "signoff": ["registrar"],
        "formats": ["xlsx", "csv", "pdf"],
    },
    "gst": {
        "name": "GST reports (GSTR-1 outward supplies)",
        "period_type": "financial_year",
        "sections": ["gst"],
        "submission_type": None,
        "due": (4, 30),
        "signoff": ["accountant"],
        "formats": ["xlsx", "csv"],
    },
}

# sign-off role slugs that are titles rather than role templates
ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "principal": ("vice_chancellor", "institution_admin", "college_admin"),
    "pio": ("pio",),
}
