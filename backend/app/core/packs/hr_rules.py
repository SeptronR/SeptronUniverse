"""HR pack rules — Prompts/06 §06.2 / §06.6 (docs/Regulatory_Pack_IN.md §2 "HR & payroll").

``HrRules`` is the pack's data for Phase 06: designations by cadre, the leave-type template, the payroll-component
template, statutory parameters (PF/ESI/PT/TDS/LWF), the reservation roster, PhD-guide scholar caps and workload norms
by cadre, CAS promotion paths and the PBAS self-appraisal schema. ``seed_hr_defaults`` (``institution_defaults``)
copies the templates into each institution (idempotent); ``services/hr/statutory.py`` reads the statutory block,
overridable per institution through the ``payroll.*`` settings. Amounts are **paise**.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HrRules:
    designations: tuple[dict[str, Any], ...] = ()
    leave_types: tuple[dict[str, Any], ...] = ()
    payroll_components: tuple[dict[str, Any], ...] = ()
    statutory: dict[str, Any] = field(default_factory=dict)
    # reservation roster: category code → percentage of posts (100-/200-point roster); the unreserved code gets the rest
    roster: dict[str, Any] = field(default_factory=dict)
    max_scholars_by_cadre: dict[str, int] = field(default_factory=dict)
    workload_norms: dict[str, float] = field(default_factory=dict)
    admin_hours_by_cadre: dict[str, float] = field(default_factory=dict)
    cas_paths: dict[str, dict[str, Any]] = field(default_factory=dict)  # cadre → {to, years}
    pbas_schema: dict[str, Any] = field(default_factory=dict)
    week_offs: tuple[int, ...] = (6,)  # Python weekday numbers (6 = Sunday)


_DESIGNATIONS_IN: tuple[dict[str, Any], ...] = (
    {"name": "Professor", "code": "PROF", "cadre": "professor", "category": "teaching", "level": 14},
    {"name": "Associate Professor", "code": "ASSOC", "cadre": "associate", "category": "teaching", "level": 13},
    {"name": "Assistant Professor", "code": "ASST", "cadre": "assistant", "category": "teaching", "level": 10},
    {"name": "Lecturer", "code": "LECT", "cadre": "lecturer", "category": "teaching", "level": 9},
    {"name": "Adjunct Professor", "code": "ADJ", "cadre": "adjunct", "category": "teaching", "level": None},
    {"name": "Visiting Faculty", "code": "VISIT", "cadre": "visiting", "category": "teaching", "level": None},
    {"name": "Guest Faculty", "code": "GUEST", "cadre": "guest", "category": "teaching", "level": None},
    {"name": "Registrar", "code": "REG", "cadre": None, "category": "administrative", "level": 14},
    {"name": "Accounts Officer", "code": "AO", "cadre": None, "category": "administrative", "level": 10},
    {"name": "HR Officer", "code": "HRO", "cadre": None, "category": "administrative", "level": 10},
    {"name": "Section Officer", "code": "SO", "cadre": None, "category": "administrative", "level": 7},
    {"name": "Librarian", "code": "LIB", "cadre": None, "category": "non_teaching", "level": 10},
    {"name": "Lab Technician", "code": "LABT", "cadre": None, "category": "non_teaching", "level": 5},
    {"name": "Office Assistant", "code": "OA", "cadre": None, "category": "non_teaching", "level": 3},
)

# CL 12 · EL 30 accruing 2.5/month · ML 20 · Duty · Study · Sabbatical · Maternity 182 · Paternity 15 · LTC · LWP
_LEAVE_TYPES_IN: tuple[dict[str, Any], ...] = (
    {"code": "CL", "name": "Casual Leave", "annual_quota": 12, "accrual": "yearly", "carry_forward_max": 0},
    {
        "code": "EL",
        "name": "Earned Leave",
        "annual_quota": 30,
        "accrual": "monthly",
        "carry_forward_max": 300,
        "is_encashable": True,
    },
    {
        "code": "ML",
        "name": "Medical Leave",
        "annual_quota": 20,
        "accrual": "yearly",
        "carry_forward_max": 0,
        "requires_document": True,
    },
    {"code": "DL", "name": "Duty Leave", "annual_quota": None, "accrual": "none"},
    {"code": "STL", "name": "Study Leave", "annual_quota": None, "accrual": "none", "requires_document": True},
    {"code": "SAB", "name": "Sabbatical", "annual_quota": None, "accrual": "none", "requires_document": True},
    {
        "code": "MAT",
        "name": "Maternity Leave",
        "annual_quota": 182,
        "accrual": "yearly",
        "requires_document": True,
        "applies_to": {"genders": ["F"]},
    },
    {
        "code": "PAT",
        "name": "Paternity Leave",
        "annual_quota": 15,
        "accrual": "yearly",
        "applies_to": {"genders": ["M"]},
    },
    {"code": "LTC", "name": "Leave Travel Concession", "annual_quota": None, "accrual": "none"},
    {"code": "LWP", "name": "Leave Without Pay", "annual_quota": None, "accrual": "none", "is_paid": False},
)

_COMPONENTS_IN: tuple[dict[str, Any], ...] = (
    {"code": "BASIC", "name": "Basic Pay", "component_type": "earning", "calc_type": "fixed", "sequence": 1},
    {
        "code": "DA",
        "name": "Dearness Allowance",
        "component_type": "earning",
        "calc_type": "pct_of_basic",
        "formula": {"pct": 50},
        "sequence": 2,
    },
    {
        "code": "HRA",
        "name": "House Rent Allowance",
        "component_type": "earning",
        "calc_type": "pct_of_basic",
        "formula": {"pct": 20},
        "sequence": 3,
    },
    {
        "code": "TA",
        "name": "Transport Allowance",
        "component_type": "earning",
        "calc_type": "fixed",
        "formula": {"amount_paise": 360000},
        "sequence": 4,
    },
    {
        "code": "SPECIAL",
        "name": "Special Allowance",
        "component_type": "earning",
        "calc_type": "fixed",
        "formula": {"amount_paise": 0},
        "sequence": 5,
    },
    {
        "code": "PF_EE",
        "name": "Provident Fund (employee)",
        "component_type": "deduction",
        "calc_type": "statutory",
        "statutory_kind": "pf",
        "is_taxable": False,
        "sequence": 20,
    },
    {
        "code": "ESI_EE",
        "name": "ESI (employee)",
        "component_type": "deduction",
        "calc_type": "statutory",
        "statutory_kind": "esi",
        "is_taxable": False,
        "sequence": 21,
    },
    {
        "code": "PT",
        "name": "Professional Tax",
        "component_type": "deduction",
        "calc_type": "statutory",
        "statutory_kind": "pt",
        "is_taxable": False,
        "sequence": 22,
    },
    {
        "code": "TDS",
        "name": "Income Tax (TDS)",
        "component_type": "deduction",
        "calc_type": "statutory",
        "statutory_kind": "tds",
        "is_taxable": False,
        "sequence": 23,
    },
    {
        "code": "LWF_EE",
        "name": "Labour Welfare Fund (employee)",
        "component_type": "deduction",
        "calc_type": "statutory",
        "statutory_kind": "lwf",
        "is_taxable": False,
        "sequence": 24,
    },
    {
        "code": "PF_ER",
        "name": "Provident Fund (employer incl. EPS)",
        "component_type": "employer_contribution",
        "calc_type": "statutory",
        "statutory_kind": "pf",
        "is_taxable": False,
        "sequence": 30,
    },
    {
        "code": "ESI_ER",
        "name": "ESI (employer)",
        "component_type": "employer_contribution",
        "calc_type": "statutory",
        "statutory_kind": "esi",
        "is_taxable": False,
        "sequence": 31,
    },
    {
        "code": "LWF_ER",
        "name": "Labour Welfare Fund (employer)",
        "component_type": "employer_contribution",
        "calc_type": "statutory",
        "statutory_kind": "lwf",
        "is_taxable": False,
        "sequence": 32,
    },
)

_STATUTORY_IN: dict[str, Any] = {
    "pf": {
        "employee_pct": 12.0,
        "employer_pct": 12.0,  # of which EPS 8.33 % (on the capped wage) and EPF the rest
        "eps_pct": 8.33,
        "wage_ceiling_paise": 1_500_000,  # ₹15,000
        "apply_ceiling": True,
        "wage_components": ["BASIC", "DA"],
    },
    "esi": {"employee_pct": 0.75, "employer_pct": 3.25, "threshold_paise": 2_100_000},  # gross ≤ ₹21,000
    "pt": {
        "default_state": "KA",
        # monthly slabs: gross ≥ min_paise → amount_paise (the highest matching slab wins); feb_amount_paise for Feb
        "states": {
            "KA": [{"min_paise": 2_500_000, "amount_paise": 20_000, "feb_amount_paise": 30_000}],
            "MH": [
                {"min_paise": 750_100, "amount_paise": 17_500},
                {"min_paise": 1_000_100, "amount_paise": 20_000, "feb_amount_paise": 30_000},
            ],
            "TN": [{"min_paise": 2_100_100, "amount_paise": 20_800}],
            "TS": [{"min_paise": 1_500_100, "amount_paise": 15_000}, {"min_paise": 2_000_100, "amount_paise": 20_000}],
            "AP": [{"min_paise": 1_500_100, "amount_paise": 15_000}, {"min_paise": 2_000_100, "amount_paise": 20_000}],
        },
    },
    "tds": {
        "default_regime": "new",
        "cess_pct": 4.0,
        "regimes": {
            # FY 2025-26 new regime (s. 115BAC): ₹75,000 standard deduction, rebate u/s 87A up to ₹12 L taxable
            "new": {
                "standard_deduction_paise": 7_500_000,
                "rebate_limit_paise": 120_000_000,
                "slabs": [
                    {"upto_paise": 40_000_000, "pct": 0},
                    {"upto_paise": 80_000_000, "pct": 5},
                    {"upto_paise": 120_000_000, "pct": 10},
                    {"upto_paise": 160_000_000, "pct": 15},
                    {"upto_paise": 200_000_000, "pct": 20},
                    {"upto_paise": 240_000_000, "pct": 25},
                    {"upto_paise": None, "pct": 30},
                ],
            },
            "old": {
                "standard_deduction_paise": 5_000_000,
                "rebate_limit_paise": 50_000_000,
                "slabs": [
                    {"upto_paise": 25_000_000, "pct": 0},
                    {"upto_paise": 50_000_000, "pct": 5},
                    {"upto_paise": 100_000_000, "pct": 20},
                    {"upto_paise": None, "pct": 30},
                ],
            },
        },
    },
    # Karnataka LWF (2024): ₹50 employee / ₹100 employer once a year in December
    "lwf": {"employee_paise": 5_000, "employer_paise": 10_000, "months": [12]},
}

_ROSTER_IN: dict[str, Any] = {
    "unreserved": "GEN",
    "percentages": {"SC": 15.0, "ST": 7.5, "OBC-NCL": 27.0, "EWS": 10.0},
    "rosters": ["100_point", "200_point"],
}

_PBAS_SCHEMA: dict[str, Any] = {
    "teaching": {
        "label": "Teaching, learning & evaluation",
        "max": 100,
        "items": {
            "lectures_engaged_pct": {"label": "Classes engaged (%)", "max": 50, "per_unit": 0.5},
            "student_feedback": {"label": "Student feedback (out of 5)", "max": 20, "per_unit": 4},
            "innovations": {"label": "Teaching innovations / e-content", "max": 30, "per_unit": 10},
        },
    },
    "research": {
        "label": "Research & academic contribution",
        "max": 120,
        "items": {
            "publications": {"label": "Publications", "max": 60, "per_unit": 10, "auto": "publications"},
            "projects": {"label": "Research projects", "max": 30, "per_unit": 15, "auto": "research_projects"},
            "phd_guided": {"label": "PhD scholars guided", "max": 30, "per_unit": 10},
        },
    },
    "extension": {
        "label": "Extension & professional development",
        "max": 50,
        "items": {
            "fdp_attended": {"label": "FDPs / workshops", "max": 20, "per_unit": 5, "auto": "faculty_developments"},
            "outreach": {"label": "Outreach / extension activities", "max": 30, "per_unit": 10},
        },
    },
    "admin": {
        "label": "Administration & governance",
        "max": 30,
        "items": {
            "committees": {"label": "Committees served", "max": 20, "per_unit": 5},
            "admin_roles": {"label": "Administrative roles", "max": 10, "per_unit": 10},
        },
    },
}

IN_HR_RULES = HrRules(
    designations=_DESIGNATIONS_IN,
    leave_types=_LEAVE_TYPES_IN,
    payroll_components=_COMPONENTS_IN,
    statutory=_STATUTORY_IN,
    roster=_ROSTER_IN,
    max_scholars_by_cadre={"professor": 8, "associate": 6, "assistant": 4},
    workload_norms={"professor": 14, "associate": 16, "assistant": 18, "lecturer": 18},
    admin_hours_by_cadre={"professor": 4, "associate": 2, "assistant": 0},
    # UGC Regulations 2018: Assistant (stage 3, Level 12) → Associate after 3 years; Associate → Professor after 3
    cas_paths={"assistant": {"to": "associate", "years": 3}, "associate": {"to": "professor", "years": 3}},
    pbas_schema=_PBAS_SCHEMA,
)

GENERIC_HR_RULES = HrRules(
    designations=_DESIGNATIONS_IN[:7] + _DESIGNATIONS_IN[12:],
    leave_types=tuple(t for t in _LEAVE_TYPES_IN if t["code"] in {"CL", "EL", "ML", "DL", "LWP"}),
    payroll_components=tuple(c for c in _COMPONENTS_IN if c["calc_type"] != "statutory")
    + (
        {
            "code": "TAX",
            "name": "Income tax",
            "component_type": "deduction",
            "calc_type": "pct_of_basic",
            "formula": {"pct": 10},
            "is_taxable": False,
            "sequence": 20,
        },
    ),
    statutory={},
    roster={},
    max_scholars_by_cadre={"professor": 8, "associate": 6, "assistant": 4},
    workload_norms={"professor": 12, "associate": 14, "assistant": 16},
    cas_paths={"assistant": {"to": "associate", "years": 5}, "associate": {"to": "professor", "years": 5}},
    pbas_schema=_PBAS_SCHEMA,
    week_offs=(5, 6),
)
