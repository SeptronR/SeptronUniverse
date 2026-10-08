"""``GENERIC`` pack — the jurisdiction-neutral fallback (docs/Regulatory_Pack_IN.md)."""

from app.core.packs.base import AssessmentScheme, Category, GradingScale, IdFormat, Quota, RegulatoryPack
from app.core.packs.hr_rules import GENERIC_HR_RULES
from app.core.packs.registry import register_pack
from app.core.packs.student_rules import GENERIC_STUDENT_RULES


@register_pack("GENERIC")
def build_generic_pack() -> RegulatoryPack:
    return RegulatoryPack(
        code="GENERIC",
        name="Generic (no statutory pack)",
        categories=[Category("GEN", "General", is_reserved=False)],
        quotas=[Quota("OPEN", "Open"), Quota("INTERNATIONAL", "International")],
        id_formats={"national_id": IdFormat("national_id", "National id", r"^.{4,40}$", masked=True)},
        default_grading_scales=[
            GradingScale(
                "LETTER_4",
                "Letter grades (4-point)",
                (
                    {"grade": "A", "min_pct": 85, "points": 4},
                    {"grade": "B", "min_pct": 70, "points": 3},
                    {"grade": "C", "min_pct": 55, "points": 2},
                    {"grade": "D", "min_pct": 40, "points": 1},
                    {"grade": "F", "min_pct": 0, "points": 0},
                ),
            )
        ],
        default_assessment_schemes=[AssessmentScheme("CW50_EX50", "Coursework 50 / Exam 50", 50, 50)],
        default_regulation_rules={"attendance_min_pct": 75, "pass_min_pct_aggregate": 40},
        hr=GENERIC_HR_RULES,
        students=GENERIC_STUDENT_RULES,
    )
