"""India regulatory pack (``IN``) — docs/Regulatory_Pack_IN.md §2.

Reference data and validators the core relies on from Phase 00; later phases extend the pack with grading/assessment
defaults (Phase 05), NBA POs (Phase 13), frameworks/metrics (Phase 32), templates (Phase 26), statutory reports
(Phase 36) as their prompts specify.
"""

import re

from app.core.packs.base import (
    AssessmentScheme,
    Category,
    CommsRules,
    Framework,
    GradingScale,
    IdFormat,
    PhdRules,
    PrivacyRules,
    Quota,
    RegulatoryPack,
    TaxRules,
)
from app.core.packs.hr_rules import IN_HR_RULES
from app.core.packs.registry import register_pack

IN_LOCALES = ["en", "hi", "bn", "mr", "te", "ta", "gu", "kn", "or", "ml", "as"]


def _verhoeff_valid(number: str) -> bool:
    """Aadhaar check digit (Verhoeff)."""
    d = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
        [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
        [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
        [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
        [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
        [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
    ]
    p = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
        [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
        [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
        [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
        [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
    ]
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = d[c][p[i % 8][int(ch)]]
    return c == 0


def validate_aadhaar(value: str) -> bool:
    v = re.sub(r"\s", "", value or "")
    return bool(re.fullmatch(r"[2-9]\d{11}", v)) and _verhoeff_valid(v)


def validate_pan(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", (value or "").upper()))


def validate_apaar(value: str) -> bool:
    """APAAR / ABC id: 12 digits with a Luhn-style check digit."""
    v = re.sub(r"\s", "", value or "")
    if not re.fullmatch(r"\d{12}", v):
        return False
    total = 0
    for i, ch in enumerate(reversed(v)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2
            n = n - 9 if n > 9 else n
        total += n
    return total % 10 == 0


def validate_gstin(value: str) -> bool:
    return bool(re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", (value or "").upper()))


def validate_aishe(value: str) -> bool:
    return bool(re.fullmatch(r"[CUS]-\d{4,6}", (value or "").upper()))


@register_pack("IN")
def build_in_pack() -> RegulatoryPack:
    return RegulatoryPack(
        code="IN",
        name="India (UGC / AICTE / NEP 2020)",
        categories=[
            Category("GEN", "General", is_reserved=False),
            Category("EWS", "Economically Weaker Section"),
            Category("OBC-NCL", "OBC (Non-Creamy Layer)"),
            Category("OBC-CL", "OBC (Creamy Layer)", is_reserved=False),
            Category("SC", "Scheduled Caste"),
            Category("ST", "Scheduled Tribe"),
        ],
        quotas=[
            Quota("STATE", "State quota"),
            Quota("ALL_INDIA", "All-India quota"),
            Quota("MANAGEMENT", "Management quota"),
            Quota("NRI", "NRI / PIO / foreign"),
            Quota("LATERAL", "Lateral entry"),
            Quota("SPORTS", "Sports", kind="horizontal"),
            Quota("PWD", "Persons with disability", kind="horizontal"),
            Quota("WOMEN", "Women", kind="horizontal"),
            Quota("DEFENCE", "Defence / ex-servicemen wards", kind="horizontal"),
            Quota("EWS_SUPER", "EWS supernumerary", kind="supernumerary"),
        ],
        id_formats={
            "apaar": IdFormat("apaar", "APAAR id", r"^\d{12}$", 12),
            "abc": IdFormat("abc", "ABC id", r"^\d{12}$", 12),
            "aadhaar": IdFormat("aadhaar", "Aadhaar", r"^[2-9]\d{11}$", 12, masked=True),
            "pan": IdFormat("pan", "PAN", r"^[A-Z]{5}\d{4}[A-Z]$", 10, masked=True),
            "aishe": IdFormat("aishe", "AISHE code", r"^[CUS]-\d{4,6}$"),
            "gstin": IdFormat("gstin", "GSTIN", r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", 15),
        },
        default_grading_scales=[
            GradingScale(
                "UGC_10",
                "UGC 10-point absolute",
                (
                    {"grade": "O", "min_pct": 90, "points": 10},
                    {"grade": "A+", "min_pct": 80, "points": 9},
                    {"grade": "A", "min_pct": 70, "points": 8},
                    {"grade": "B+", "min_pct": 60, "points": 7},
                    {"grade": "B", "min_pct": 55, "points": 6},
                    {"grade": "C", "min_pct": 50, "points": 5},
                    {"grade": "P", "min_pct": 40, "points": 4},
                    {"grade": "F", "min_pct": 0, "points": 0},
                ),
            )
        ],
        default_assessment_schemes=[AssessmentScheme("CIA40_SEE60", "CIA 40 / SEE 60", 40, 60)],
        default_regulation_rules={
            "attendance_min_pct": 75,
            "condonation_min_pct": 65,
            "pass_min_pct_external": 40,
            "pass_min_pct_aggregate": 50,
            "credit_hours_per_credit": {"lecture": 15, "practical": 30},
            "mooc_credit_cap_pct": 40,
            "ug_exit_points": {"certificate": 40, "diploma": 80, "degree": 120, "honours": 160},
        },
        accreditation_frameworks=[
            Framework("NAAC_2024", "NAAC Revised Assessment & Accreditation Framework", "2024"),
            Framework("NBA_UG_ENGG", "NBA Tier-I/II UG Engineering (GAPC v4)", "4.0"),
            Framework("NIRF", "National Institutional Ranking Framework", "2026"),
            Framework("AISHE", "All India Survey on Higher Education", "2026"),
            Framework("AICTE_APPROVAL", "AICTE Approval Process", "2026"),
            Framework("UGC_12B", "UGC 2(f)/12(B) Recognition", "2026"),
        ],
        comms_compliance=CommsRules(
            sms_requires_dlt=True, whatsapp_template_policy="meta_approved", quiet_hours=(21, 8)
        ),
        privacy=PrivacyRules(
            law="DPDP_2023",
            consent_purposes=("academic", "communication", "marketing", "health", "photo", "third_party"),
            retention_years=7,
        ),
        tax=TaxRules(tax_name="GST", default_rate_pct=18.0, taxable_fee_heads=("hostel", "transport", "mess", "misc")),
        phd_rules=PhdRules(
            min_coursework_credits=12, max_scholars_per_guide=8, min_duration_years=3, max_duration_years=6
        ),
        validators={
            "aadhaar": validate_aadhaar,
            "pan": validate_pan,
            "apaar": validate_apaar,
            "abc": validate_apaar,
            "gstin": validate_gstin,
            "aishe": validate_aishe,
        },
        locales=IN_LOCALES,
        hr=IN_HR_RULES,
    )
