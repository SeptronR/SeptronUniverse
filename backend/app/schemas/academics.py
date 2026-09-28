"""Programmes, regulations, grading, assessment schemes, batches and the public catalogue — Prompts/05 §05.4.

``RegulationRules`` types ``regulations.rules`` with every key of docs/Academic_Core_Design.md §1a and its default;
unknown keys are refused (a typo must not silently fall back to a default at result time). ``rules_override`` on a
programme-regulation is a *partial* rules object: it is validated by merging it over the regulation's rules and
re-validating the result (``merge_rules``). Course-level schemas are in ``app/schemas/curriculum.py``.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.enums.academics import (
    BatchStatus,
    ComponentCategory,
    CourseType,
    EntryType,
    ExamAuthority,
    ProgramLevel,
    ProgramMode,
    ProgramRegulationStatus,
    ProgramStatus,
    ScaleType,
    TermPattern,
)
from app.schemas.common import ORMModel

CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,29}$"


# ---- regulation rules (docs/Academic_Core_Design.md §1a) --------------------------------------------------------------
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClassRule(_Strict):
    name: str = Field(min_length=1, max_length=40)
    min_cgpa: float = Field(ge=0, le=10)
    first_attempt_only: bool = False


class GraceRules(_Strict):
    max_per_course: float = Field(default=5, ge=0, le=100)
    max_courses_per_term: int = Field(default=2, ge=0, le=20)
    max_total_per_term: float = Field(default=8, ge=0, le=200)
    scope: Literal["total", "ese"] = "total"


class DoubleValuation(_Strict):
    enabled: bool = True
    discrepancy_pct: float = Field(default=15, ge=0, le=100)
    resolution: Literal["avg_closest_two", "third_final", "best_two_avg"] = "avg_closest_two"


class RevalRules(_Strict):
    min_delta_to_apply: float = Field(default=5, ge=0, le=100)
    fee_paise: int = Field(default=0, ge=0)
    photocopy_fee_paise: int = Field(default=0, ge=0)
    challenge_fee_paise: int = Field(default=0, ge=0)
    refund_if_changed: bool = True


class ExitPoint(_Strict):
    after_term: int = Field(ge=1, le=20)
    award: str = Field(min_length=2, max_length=30)
    min_credits: float = Field(ge=0, le=400)


class StandingRule(_Strict):
    status: Literal["warning", "probation", "dismissal"]
    when: dict[str, float]

    @field_validator("when")
    @classmethod
    def _keys(cls, v: dict[str, float]) -> dict[str, float]:
        allowed = {"sgpa_below", "cgpa_below", "consecutive_terms", "backlogs_above"}
        unknown = set(v) - allowed
        if unknown:
            raise ValueError(f"unknown standing condition(s): {sorted(unknown)}")
        return v


DEFAULT_CLASS_RULES = [
    {"name": "Distinction", "min_cgpa": 8.5, "first_attempt_only": True},
    {"name": "First", "min_cgpa": 6.5},
    {"name": "Second", "min_cgpa": 5.0},
]
DEFAULT_EXIT_POINTS = [
    {"after_term": 2, "award": "certificate", "min_credits": 40},
    {"after_term": 4, "award": "diploma", "min_credits": 80},
    {"after_term": 6, "award": "degree", "min_credits": 120},
    {"after_term": 8, "award": "honours", "min_credits": 160},
]
DEFAULT_STANDING_RULES = [
    {"status": "warning", "when": {"sgpa_below": 5.0}},
    {"status": "probation", "when": {"cgpa_below": 5.0, "consecutive_terms": 1}},
    {"status": "dismissal", "when": {"cgpa_below": 4.0, "consecutive_terms": 2}},
]
DEFAULT_MOOC_GRADE_MAP = {
    "90-100": "O",
    "80-89": "A+",
    "70-79": "A",
    "60-69": "B+",
    "55-59": "B",
    "50-54": "C",
    "40-49": "P",
    "0-39": "F",
}


class RegulationRules(_Strict):
    """Every rules key with its default (help text is served to the Rules tab by ``rules_help()``)."""

    attendance_min_pct: float = Field(default=75, ge=0, le=100, description="eligibility threshold")
    condonation_floor_pct: float = Field(default=65, ge=0, le=100, description="below this no condonation")
    condonation_fee_paise: int = Field(default=0, ge=0, description="fee for condonation (paise)")
    attendance_mode: Literal["course_wise", "aggregate"] = Field(default="course_wise", description="how % is computed")
    ese_pass_min_pct: float = Field(default=45, ge=0, le=100, description="minimum % in the end-semester exam")
    total_pass_min_pct: float = Field(default=50, ge=0, le=100, description="minimum % of CIA + ESE")
    cia_pass_min_pct: float | None = Field(default=None, ge=0, le=100, description="minimum % in CIA (none = no rule)")
    include_failed_credits_in_sgpa: bool = Field(default=True, description="failed credits count in the denominator")
    cgpa_attempt_policy: Literal["latest", "best"] = Field(default="latest", description="which attempt counts")
    percentage_formula: str = Field(
        default="cgpa*10", pattern=r"^[0-9cgpa+\-*/(). ]{1,40}$", description="CGPA → percentage expression"
    )
    class_rules: list[ClassRule] = Field(
        default_factory=lambda: [ClassRule(**r) for r in DEFAULT_CLASS_RULES], description="first satisfied wins"
    )
    grace: GraceRules = Field(default_factory=GraceRules, description="grace-mark caps")
    double_valuation: DoubleValuation = Field(default_factory=DoubleValuation, description="second valuation rule")
    reval: RevalRules = Field(default_factory=RevalRules, description="post-result revaluation rules")
    exit_points: list[ExitPoint] = Field(
        default_factory=lambda: [ExitPoint(**e) for e in DEFAULT_EXIT_POINTS], description="NEP multiple exits"
    )
    minor_credits: float = Field(default=18, ge=0, le=100, description="credits for a minor")
    honours_credits: float = Field(default=18, ge=0, le=100, description="additional credits for honours")
    mooc_max_credits: float = Field(default=12, ge=0, le=100, description="cap on MOOC credits")
    max_backlogs_for_promotion: int = Field(default=4, ge=0, le=50, description="detention rule")
    min_cgpa_for_degree: float = Field(default=5.0, ge=0, le=10, description="degree eligibility")
    standing_rules: list[StandingRule] = Field(
        default_factory=lambda: [StandingRule(**r) for r in DEFAULT_STANDING_RULES], description="academic standing"
    )
    mooc_grade_map: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_MOOC_GRADE_MAP), description="MOOC score band → letter grade"
    )
    print_grace_note: bool = Field(default=True, description="footnote on the grade card")

    @model_validator(mode="after")
    def _consistent(self) -> "RegulationRules":
        if self.condonation_floor_pct > self.attendance_min_pct:
            raise ValueError("condonation_floor_pct must not exceed attendance_min_pct")
        terms = [e.after_term for e in self.exit_points]
        if len(terms) != len(set(terms)):
            raise ValueError("exit_points: one award per term")
        return self


# pack rule keys (app/core/packs) → RegulationRules keys
PACK_RULE_KEYS = {
    "attendance_min_pct": "attendance_min_pct",
    "condonation_min_pct": "condonation_floor_pct",
    "pass_min_pct_external": "ese_pass_min_pct",
    "pass_min_pct_aggregate": "total_pass_min_pct",
}


def pack_rules(pack_rules_dict: dict[str, Any]) -> dict[str, Any]:
    """Pack defaults translated to rules keys (``ug_exit_points`` → ``exit_points``); pack keys without a rules
    counterpart (``credit_hours_per_credit``, the percentage ``mooc_credit_cap_pct``) are dropped."""
    out: dict[str, Any] = {}
    for src, dst in PACK_RULE_KEYS.items():
        if src in pack_rules_dict:
            out[dst] = pack_rules_dict[src]
    exits = pack_rules_dict.get("ug_exit_points")
    if isinstance(exits, dict):
        out["exit_points"] = [
            {"after_term": 2 * (i + 1), "award": award, "min_credits": credits}
            for i, (award, credits) in enumerate(exits.items())
        ]
    return out


def merge_rules(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    """``rules ⊕ rules_override``: top-level keys replace, nested objects (grace, reval, …) merge one level deep."""
    merged = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict) and key != "mooc_grade_map":
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def rules_help() -> list[dict[str, Any]]:
    """Rules-form metadata: key, default, description (the web Rules tab renders it)."""
    defaults = RegulationRules().model_dump(mode="json")
    return [
        {"key": name, "default": defaults[name], "description": field.description or ""}
        for name, field in RegulationRules.model_fields.items()
    ]


# ---- programmes ----------------------------------------------------------------------------------------------------
class ProgramCreate(BaseModel):
    college_id: uuid.UUID
    faculty_id: uuid.UUID | None = None
    department_id: uuid.UUID
    code: str = Field(pattern=CODE_PATTERN)
    name: str = Field(min_length=2, max_length=200)
    degree_name: str = Field(min_length=1, max_length=80)
    specialization: str | None = Field(default=None, max_length=120)
    level: ProgramLevel
    mode: ProgramMode = ProgramMode.REGULAR
    term_pattern: TermPattern = TermPattern.SEMESTER
    duration_years: Decimal = Field(gt=0, le=10)
    total_terms: int = Field(ge=1, le=30)
    max_duration_years: Decimal | None = Field(default=None, gt=0, le=20)
    sanctioned_intake: int | None = Field(default=None, ge=0, le=10000)
    lateral_intake: int | None = Field(default=None, ge=0, le=10000)
    approving_body: str | None = Field(default=None, max_length=40)
    exam_authority: ExamAuthority | None = None  # default from the institution type (affiliated → university)
    is_nep_multidisciplinary: bool = False
    is_open_enrolment: bool = False
    status: ProgramStatus = ProgramStatus.ACTIVE

    @model_validator(mode="after")
    def _durations(self) -> "ProgramCreate":
        if self.max_duration_years is not None and self.max_duration_years < self.duration_years:
            raise ValueError("max_duration_years must be ≥ duration_years")
        return self


class ProgramUpdate(BaseModel):
    faculty_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=2, max_length=200)
    degree_name: str | None = Field(default=None, min_length=1, max_length=80)
    specialization: str | None = Field(default=None, max_length=120)
    mode: ProgramMode | None = None
    term_pattern: TermPattern | None = None
    duration_years: Decimal | None = Field(default=None, gt=0, le=10)
    total_terms: int | None = Field(default=None, ge=1, le=30)
    max_duration_years: Decimal | None = Field(default=None, gt=0, le=20)
    sanctioned_intake: int | None = Field(default=None, ge=0, le=10000)
    lateral_intake: int | None = Field(default=None, ge=0, le=10000)
    approving_body: str | None = Field(default=None, max_length=40)
    exam_authority: ExamAuthority | None = None
    is_nep_multidisciplinary: bool | None = None
    is_open_enrolment: bool | None = None
    status: Literal["draft", "active"] | None = None  # closing goes through POST /programs/{id}/close
    version: int | None = None


class ProgramResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID
    faculty_id: uuid.UUID | None = None
    department_id: uuid.UUID
    code: str
    name: str
    degree_name: str
    specialization: str | None = None
    level: str
    mode: str
    term_pattern: str
    duration_years: Decimal
    total_terms: int
    max_duration_years: Decimal | None = None
    sanctioned_intake: int | None = None
    lateral_intake: int | None = None
    approving_body: str | None = None
    exam_authority: str
    is_nep_multidisciplinary: bool
    is_open_enrolment: bool
    status: str
    version: int
    college_code: str | None = None
    department_code: str | None = None
    can_edit: bool = False


# ---- regulations ---------------------------------------------------------------------------------------------------
class RegulationCreate(BaseModel):
    college_id: uuid.UUID | None = None  # NULL = institution-wide regulation
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,19}$")
    name: str = Field(min_length=2, max_length=120)
    effective_from_admission_year: int = Field(ge=1950, le=2100)
    grading_scale_id: uuid.UUID | None = None
    rules: dict[str, Any] | None = (
        None  # partial: missing keys take the pack defaults, then the RegulationRules defaults
    )


class RegulationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    effective_from_admission_year: int | None = Field(default=None, ge=1950, le=2100)
    grading_scale_id: uuid.UUID | None = None
    rules: dict[str, Any] | None = None  # full or partial; merged over the stored rules and re-validated
    version: int | None = None


class RegulationCloneRequest(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,19}$")
    name: str = Field(min_length=2, max_length=120)
    effective_from_admission_year: int = Field(ge=1950, le=2100)


class RegulationApproveRequest(BaseModel):
    resolution_id: uuid.UUID | None = None


class RegulationResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    code: str
    name: str
    effective_from_admission_year: int
    grading_scale_id: uuid.UUID | None = None
    rules: dict[str, Any]
    status: str
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    approval_resolution_id: uuid.UUID | None = None
    locked_at: datetime | None = None
    superseded_by_id: uuid.UUID | None = None
    version: int
    created_at: datetime
    course_count: int = 0
    program_count: int = 0
    predecessor_id: uuid.UUID | None = None
    workflow_instance_id: uuid.UUID | None = None
    rules_locked: bool = False
    structure_locked: bool = False


class RegulationApproveResponse(BaseModel):
    regulation: RegulationResponse
    workflow_instance_id: uuid.UUID | None = None
    pending_workflow: bool = False


class RulesHelpItem(BaseModel):
    key: str
    default: Any = None
    description: str = ""


class RulesEffectiveResponse(BaseModel):
    regulation_id: uuid.UUID
    program_id: uuid.UUID | None = None
    program_regulation_id: uuid.UUID | None = None
    rules: dict[str, Any]
    overridden_keys: list[str] = Field(default_factory=list)


# ---- programme-regulation bindings ---------------------------------------------------------------------------------
class ProgramRegulationCreate(BaseModel):
    program_id: uuid.UUID
    regulation_id: uuid.UUID
    total_credits_required: Decimal = Field(gt=0, le=1000)
    rules_override: dict[str, Any] | None = None
    status: ProgramRegulationStatus = ProgramRegulationStatus.DRAFT


class ProgramRegulationUpdate(BaseModel):
    total_credits_required: Decimal | None = Field(default=None, gt=0, le=1000)
    rules_override: dict[str, Any] | None = None
    status: ProgramRegulationStatus | None = None
    version: int | None = None


class ProgramRegulationResponse(ORMModel):
    id: uuid.UUID
    program_id: uuid.UUID
    regulation_id: uuid.UUID
    rules_override: dict[str, Any] | None = None
    total_credits_required: Decimal
    status: str
    version: int
    program_code: str | None = None
    program_name: str | None = None
    regulation_code: str | None = None
    regulation_status: str | None = None
    total_terms: int | None = None


# ---- grading scales ------------------------------------------------------------------------------------------------
class GradeRange(BaseModel):
    grade: str = Field(min_length=1, max_length=3)
    min_pct: float = Field(ge=0, le=100)
    max_pct: float | None = Field(default=None, ge=0, le=100)  # omitted = up to the next grade's min
    points: float = Field(ge=0, le=10, validation_alias=AliasChoices("points", "grade_point"))
    is_fail: bool | None = None  # default: points == 0
    description: str | None = Field(default=None, max_length=60)


class SpecialGrade(BaseModel):
    grade: str = Field(min_length=1, max_length=3)  # AB | W | I | RA …
    meaning: str = Field(min_length=1, max_length=60)
    counts_as_attempt: bool = True
    points: float | None = None


class GradingScaleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    regulation_id: uuid.UUID | None = None
    scale_type: ScaleType = ScaleType.ABSOLUTE
    ranges: list[GradeRange] = Field(min_length=2, max_length=20)
    relative_config: dict[str, Any] | None = None
    special_grades: list[SpecialGrade] | None = None
    max_grade_point: Decimal = Field(default=Decimal("10"), gt=0, le=10)
    is_default: bool = False


class GradingScaleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    scale_type: ScaleType | None = None
    ranges: list[GradeRange] | None = Field(default=None, min_length=2, max_length=20)
    relative_config: dict[str, Any] | None = None
    special_grades: list[SpecialGrade] | None = None
    max_grade_point: Decimal | None = Field(default=None, gt=0, le=10)
    is_default: bool | None = None
    version: int | None = None


class GradingScaleResponse(ORMModel):
    id: uuid.UUID
    regulation_id: uuid.UUID | None = None
    name: str
    scale_type: str
    ranges: list[dict[str, Any]]
    relative_config: dict[str, Any] | None = None
    special_grades: list[dict[str, Any]] | None = None
    max_grade_point: Decimal
    is_default: bool
    version: int


# ---- assessment schemes --------------------------------------------------------------------------------------------
class BestOf(BaseModel):
    take: int = Field(ge=1, le=10)
    of: int = Field(ge=1, le=10)
    group: str | None = Field(default=None, max_length=20)


class AssessmentComponentIn(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,19}$")
    name: str = Field(min_length=1, max_length=80)
    category: ComponentCategory
    max_marks: int = Field(ge=1, le=1000)
    scaled_to: Decimal | None = Field(default=None, ge=0, le=1000)
    weight_pct: Decimal | None = Field(default=None, ge=0, le=100)
    best_of: BestOf | None = None
    sequence: int = Field(default=1, ge=1, le=100)
    is_mandatory: bool = True
    co_mappable: bool = True


class AssessmentComponentOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    category: str
    max_marks: int
    scaled_to: Decimal | None = None
    weight_pct: Decimal | None = None
    best_of: dict[str, Any] | None = None
    sequence: int
    is_mandatory: bool
    co_mappable: bool


class PassRules(BaseModel):
    ese_min_pct: float | None = Field(default=None, ge=0, le=100)
    total_min_pct: float | None = Field(default=None, ge=0, le=100)
    cia_min_pct: float | None = Field(default=None, ge=0, le=100)


class AssessmentSchemeCreate(BaseModel):
    regulation_id: uuid.UUID
    code: str = Field(pattern=CODE_PATTERN)
    name: str = Field(min_length=2, max_length=120)
    applies_to_course_types: list[CourseType] = Field(default_factory=list)
    cia_weight: int = Field(default=40, ge=0, le=100)
    ese_weight: int = Field(default=60, ge=0, le=100)
    cia_max: int = Field(default=40, ge=0, le=1000)
    ese_max: int = Field(default=60, ge=0, le=1000)
    pass_rules: PassRules = Field(default_factory=PassRules)
    is_default: bool = False
    components: list[AssessmentComponentIn] = Field(default_factory=list)


class AssessmentSchemeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    applies_to_course_types: list[CourseType] | None = None
    cia_weight: int | None = Field(default=None, ge=0, le=100)
    ese_weight: int | None = Field(default=None, ge=0, le=100)
    cia_max: int | None = Field(default=None, ge=0, le=1000)
    ese_max: int | None = Field(default=None, ge=0, le=1000)
    pass_rules: PassRules | None = None
    is_default: bool | None = None
    version: int | None = None


class AssessmentComponentsReplace(BaseModel):
    components: list[AssessmentComponentIn] = Field(max_length=40)


class AssessmentSchemeResponse(ORMModel):
    id: uuid.UUID
    regulation_id: uuid.UUID
    code: str
    name: str
    applies_to_course_types: list[str]
    cia_weight: int
    ese_weight: int
    cia_max: int
    ese_max: int
    pass_rules: dict[str, Any]
    is_default: bool
    version: int
    components: list[AssessmentComponentOut] = Field(default_factory=list)
    regulation_code: str | None = None


# ---- batches -------------------------------------------------------------------------------------------------------
class BatchSectionIn(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,9}$")
    capacity: int | None = Field(default=None, ge=1, le=1000)


class BatchSectionOut(ORMModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    name: str
    capacity: int | None = None
    class_advisor_staff_id: uuid.UUID | None = None
    class_advisor_user_id: uuid.UUID | None = None
    class_advisor_name: str | None = None
    is_active: bool


class BatchCreate(BaseModel):
    college_id: uuid.UUID | None = None  # default: the programme's college
    program_id: uuid.UUID
    program_regulation_id: uuid.UUID
    admission_year: int = Field(ge=1950, le=2100)
    entry_type: EntryType = EntryType.REGULAR
    code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")  # default {year}-{prog}
    name: str | None = Field(default=None, max_length=120)
    expected_graduation_year: int | None = Field(default=None, ge=1950, le=2110)
    sections: list[BatchSectionIn] | None = None  # default: section_count sections A…N
    section_count: int = Field(default=1, ge=1, le=26)
    section_capacity: int | None = Field(default=None, ge=1, le=1000)


class BatchUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    expected_graduation_year: int | None = Field(default=None, ge=1950, le=2110)
    status: BatchStatus | None = None
    version: int | None = None


class BatchSectionsReplace(BaseModel):
    sections: list[BatchSectionIn] = Field(min_length=1, max_length=26)


class AdvisorAssign(BaseModel):
    """``staff_id`` may be a ``staff`` row (Phase 06) or — until staff records exist — the staff **user** id."""

    staff_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one(self) -> "AdvisorAssign":
        if not (self.staff_id or self.user_id):
            raise ValueError("staff_id or user_id is required")
        return self


class BatchResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID
    program_id: uuid.UUID
    program_regulation_id: uuid.UUID
    admission_year: int
    entry_type: str
    code: str
    name: str | None = None
    expected_graduation_year: int | None = None
    current_term_number: int
    status: str
    version: int
    sections: list[BatchSectionOut] = Field(default_factory=list)
    program_code: str | None = None
    regulation_code: str | None = None


# ---- public catalogue (no internal ids beyond codes) -----------------------------------------------------------------
class PublicCatalogCourse(BaseModel):
    code: str
    title: str
    course_type: str
    credits: Decimal
    lecture_hours: int
    tutorial_hours: int
    practical_hours: int
    term_number: int | None = None
    regulation: str
    department: str | None = None
    syllabus: list[dict[str, Any]] | None = None
    textbooks: list[Any] | None = None


class PublicCatalogProgram(BaseModel):
    code: str
    name: str
    degree_name: str
    specialization: str | None = None
    level: str
    mode: str
    duration_years: Decimal
    total_terms: int
    sanctioned_intake: int | None = None
    college: str
    college_name: str | None = None
    department: str | None = None
    regulation: str | None = None
    total_credits: Decimal | None = None
    courses: list[PublicCatalogCourse] = Field(default_factory=list)


class PublicCatalogResponse(BaseModel):
    institution: str
    programs: list[PublicCatalogProgram]
    generated_at: datetime
