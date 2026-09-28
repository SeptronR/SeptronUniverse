"""Courses, prerequisites, programme structure and elective baskets — Prompts/05 §05.4.

``StructureReplaceRequest`` carries the whole per-term structure of a programme-regulation (terms + curriculum
courses + baskets, baskets referenced by ``code`` inside the request) and is replaced transactionally;
``StructureValidationResponse`` lists credit totals per term and every issue (``severity`` ``error`` blocks approval,
``warning`` is informational on a draft).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.enums.academics import (
    CREDIT_BUCKETS,
    AllocationMode,
    BasketType,
    CourseStatus,
    CourseType,
    PrereqRelation,
)
from app.schemas.common import ORMModel

COURSE_CODE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,29}$"


# ---- courses -------------------------------------------------------------------------------------------------------
class SyllabusUnit(BaseModel):
    unit: int = Field(ge=1, le=50)
    title: str = Field(min_length=1, max_length=200)
    topics: list[str] = Field(default_factory=list, max_length=100)
    hours: int | None = Field(default=None, ge=0, le=500)


class CourseCreate(BaseModel):
    regulation_id: uuid.UUID
    department_id: uuid.UUID
    college_id: uuid.UUID | None = None
    code: str = Field(pattern=COURSE_CODE)
    title: str = Field(min_length=2, max_length=200)
    short_title: str | None = Field(default=None, max_length=60)
    course_type: CourseType
    lecture_hours: int = Field(default=0, ge=0, le=40)
    tutorial_hours: int = Field(default=0, ge=0, le=40)
    practical_hours: int = Field(default=0, ge=0, le=40)
    credits: Decimal = Field(default=Decimal("0"), ge=0, le=40)
    assessment_scheme_id: uuid.UUID | None = None  # default: the regulation's scheme for the course type
    cia_max: int | None = Field(default=None, ge=0, le=1000)
    ese_max: int | None = Field(default=None, ge=0, le=1000)
    is_gradable: bool = True
    min_seats: int | None = Field(default=None, ge=0, le=5000)
    max_seats: int | None = Field(default=None, ge=0, le=5000)
    syllabus: list[SyllabusUnit] | None = None
    textbooks: list[Any] | None = None
    references_list: list[Any] | None = None
    is_public_catalog: bool = True

    @model_validator(mode="after")
    def _seats(self) -> "CourseCreate":
        if self.min_seats is not None and self.max_seats is not None and self.min_seats > self.max_seats:
            raise ValueError("min_seats must be ≤ max_seats")
        return self


class CourseUpdate(BaseModel):
    department_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=2, max_length=200)
    short_title: str | None = Field(default=None, max_length=60)
    course_type: CourseType | None = None
    lecture_hours: int | None = Field(default=None, ge=0, le=40)
    tutorial_hours: int | None = Field(default=None, ge=0, le=40)
    practical_hours: int | None = Field(default=None, ge=0, le=40)
    credits: Decimal | None = Field(default=None, ge=0, le=40)
    assessment_scheme_id: uuid.UUID | None = None
    cia_max: int | None = Field(default=None, ge=0, le=1000)
    ese_max: int | None = Field(default=None, ge=0, le=1000)
    is_gradable: bool | None = None
    min_seats: int | None = Field(default=None, ge=0, le=5000)
    max_seats: int | None = Field(default=None, ge=0, le=5000)
    syllabus: list[SyllabusUnit] | None = None
    textbooks: list[Any] | None = None
    references_list: list[Any] | None = None
    is_public_catalog: bool | None = None
    version: int | None = None


class CourseStatusChange(BaseModel):
    status: CourseStatus


class CourseResponse(ORMModel):
    id: uuid.UUID
    regulation_id: uuid.UUID
    department_id: uuid.UUID
    college_id: uuid.UUID | None = None
    code: str
    title: str
    short_title: str | None = None
    course_type: str
    lecture_hours: int
    tutorial_hours: int
    practical_hours: int
    credits: Decimal
    contact_hours_per_week: int | None = None
    assessment_scheme_id: uuid.UUID | None = None
    cia_max: int | None = None
    ese_max: int | None = None
    is_credit_bearing: bool
    is_gradable: bool
    min_seats: int | None = None
    max_seats: int | None = None
    syllabus: list[dict[str, Any]] | None = None
    textbooks: list[Any] | None = None
    references_list: list[Any] | None = None
    is_public_catalog: bool
    status: str
    version: int
    created_at: datetime
    regulation_code: str | None = None
    regulation_status: str | None = None
    department_code: str | None = None
    scheme_code: str | None = None
    ltpc: str | None = None
    can_edit: bool = False
    prerequisites: list["PrerequisiteOut"] = Field(default_factory=list)


class PrerequisiteIn(BaseModel):
    related_course_id: uuid.UUID
    relation: PrereqRelation = PrereqRelation.PREREQUISITE
    min_grade: str | None = Field(default=None, max_length=3)
    is_hard: bool = True


class PrerequisiteSet(BaseModel):
    items: list[PrerequisiteIn] = Field(max_length=30)


class PrerequisiteOut(ORMModel):
    id: uuid.UUID
    related_course_id: uuid.UUID
    relation: str
    min_grade: str | None = None
    is_hard: bool
    related_code: str | None = None
    related_title: str | None = None


class CourseBulkImportRequest(BaseModel):
    regulation_id: uuid.UUID
    csv: str = Field(min_length=10, max_length=2_000_000)  # code,title,type,L,T,P,credits,department_code,scheme_code


# ---- structure -----------------------------------------------------------------------------------------------------
class StructureTermIn(BaseModel):
    term_number: int = Field(ge=1, le=30)
    name: str | None = Field(default=None, max_length=60)  # default "Semester N" / "Year N" / "Trimester N"
    min_credits: Decimal = Field(ge=0, le=100)
    normal_credits: Decimal = Field(ge=0, le=100)
    max_credits: Decimal = Field(ge=0, le=100)
    is_exit_point: bool = False
    exit_award: str | None = Field(default=None, max_length=30)


class StructureTermOut(ORMModel):
    id: uuid.UUID
    term_number: int
    name: str
    min_credits: Decimal
    normal_credits: Decimal
    max_credits: Decimal
    is_exit_point: bool
    exit_award: str | None = None


class CurriculumCourseIn(BaseModel):
    term_number: int = Field(ge=1, le=30)
    course_id: uuid.UUID
    basket_code: str | None = Field(default=None, max_length=30)  # a basket of the same request
    is_mandatory: bool = True
    credit_bucket: Literal[CREDIT_BUCKETS] | None = None  # type: ignore[valid-type]
    sequence: int = Field(default=1, ge=1, le=200)


class CurriculumCourseOut(ORMModel):
    id: uuid.UUID
    term_number: int
    course_id: uuid.UUID
    elective_basket_id: uuid.UUID | None = None
    basket_code: str | None = None
    is_mandatory: bool
    credit_bucket: str | None = None
    sequence: int
    course_code: str | None = None
    course_title: str | None = None
    course_type: str | None = None
    credits: Decimal | None = None
    ltpc: str | None = None


class BasketIn(BaseModel):
    code: str = Field(pattern=COURSE_CODE)
    name: str = Field(min_length=2, max_length=120)
    basket_type: BasketType
    term_number: int | None = Field(default=None, ge=1, le=30)
    min_choose: int = Field(default=1, ge=0, le=20)
    max_choose: int = Field(default=1, ge=1, le=20)
    credits_required: Decimal | None = Field(default=None, ge=0, le=100)
    allocation_mode: AllocationMode = AllocationMode.PRIORITY_CGPA
    course_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _choose(self) -> "BasketIn":
        if self.min_choose > self.max_choose:
            raise ValueError("min_choose must be ≤ max_choose")
        return self


class StructureReplaceRequest(BaseModel):
    terms: list[StructureTermIn] = Field(max_length=30)
    courses: list[CurriculumCourseIn] = Field(default_factory=list, max_length=600)
    baskets: list[BasketIn] | None = None  # None = keep the existing baskets (edited through /elective-baskets)
    version: int | None = None  # programme-regulation version (optimistic lock)


class StructureIssue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str
    term_number: int | None = None
    course_id: uuid.UUID | None = None


class StructureValidationResponse(BaseModel):
    program_regulation_id: uuid.UUID
    credit_totals_by_term: dict[int, Decimal]
    mandatory_credits: Decimal
    basket_credits: Decimal
    total: Decimal
    required: Decimal
    issues: list[StructureIssue]
    valid: bool


class BasketOut(ORMModel):
    id: uuid.UUID
    program_regulation_id: uuid.UUID
    code: str
    name: str
    basket_type: str
    term_number: int | None = None
    min_choose: int
    max_choose: int
    credits_required: Decimal | None = None
    allocation_mode: str
    version: int
    courses: list["BasketCourseOut"] = Field(default_factory=list)


class BasketCourseOut(BaseModel):
    course_id: uuid.UUID
    offering_department_id: uuid.UUID | None = None
    code: str | None = None
    title: str | None = None
    credits: Decimal | None = None


class StructureResponse(BaseModel):
    program_regulation_id: uuid.UUID
    program_id: uuid.UUID
    regulation_id: uuid.UUID
    regulation_status: str
    total_terms: int
    term_pattern: str
    total_credits_required: Decimal
    version: int
    locked: bool
    terms: list[StructureTermOut]
    courses: list[CurriculumCourseOut]
    baskets: list[BasketOut]
    exit_points: list[dict[str, Any]] = Field(default_factory=list)


# ---- baskets (CRUD outside the structure editor) -----------------------------------------------------------------------
class BasketCreate(BaseModel):
    program_regulation_id: uuid.UUID
    code: str = Field(pattern=COURSE_CODE)
    name: str = Field(min_length=2, max_length=120)
    basket_type: BasketType
    term_number: int | None = Field(default=None, ge=1, le=30)
    min_choose: int = Field(default=1, ge=0, le=20)
    max_choose: int = Field(default=1, ge=1, le=20)
    credits_required: Decimal | None = Field(default=None, ge=0, le=100)
    allocation_mode: AllocationMode = AllocationMode.PRIORITY_CGPA
    course_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _choose(self) -> "BasketCreate":
        if self.min_choose > self.max_choose:
            raise ValueError("min_choose must be ≤ max_choose")
        return self


class BasketUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    basket_type: BasketType | None = None
    term_number: int | None = Field(default=None, ge=1, le=30)
    min_choose: int | None = Field(default=None, ge=0, le=20)
    max_choose: int | None = Field(default=None, ge=1, le=20)
    credits_required: Decimal | None = Field(default=None, ge=0, le=100)
    allocation_mode: AllocationMode | None = None
    version: int | None = None


class BasketCourseIn(BaseModel):
    course_id: uuid.UUID
    offering_department_id: uuid.UUID | None = None


class BasketCoursesReplace(BaseModel):
    courses: list[BasketCourseIn] = Field(max_length=100)


# ---- diff ----------------------------------------------------------------------------------------------------------
class CourseChange(BaseModel):
    code: str
    title: str
    fields: dict[str, dict[str, Any]]  # field → {old, new}


class CourseBrief(BaseModel):
    code: str
    title: str
    credits: Decimal
    course_type: str


class RegulationDiffResponse(BaseModel):
    regulation_id: uuid.UUID
    regulation_code: str
    predecessor_id: uuid.UUID | None = None
    predecessor_code: str | None = None
    added: list[CourseBrief] = Field(default_factory=list)
    removed: list[CourseBrief] = Field(default_factory=list)
    changed: list[CourseChange] = Field(default_factory=list)
    rules_changed: dict[str, dict[str, Any]] = Field(default_factory=dict)
    unchanged_count: int = 0


CourseResponse.model_rebuild()
BasketOut.model_rebuild()
