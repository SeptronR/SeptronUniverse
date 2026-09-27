"""Academic session schemas — Prompts/03 §03.4 (years, terms, status changes, rollover; Database_Schema.sql §7)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.enums.institution import TermStatus, TermType
from app.schemas.common import ORMModel


class AcademicYearCreate(BaseModel):
    name: str = Field(min_length=4, max_length=20, pattern=r"^[0-9A-Za-z/ -]+$")
    start_date: date
    end_date: date
    college_id: uuid.UUID | None = Field(default=None, description="NULL = institution-wide year")
    is_current: bool = False

    @model_validator(mode="after")
    def _range(self) -> "AcademicYearCreate":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class AcademicYearUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=4, max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    version: int | None = None


class AcademicTermBrief(ORMModel):
    id: uuid.UUID
    name: str
    term_type: str
    sequence: int
    start_date: date
    end_date: date
    status: str
    is_current: bool


class AcademicYearResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    name: str
    start_date: date
    end_date: date
    is_current: bool
    is_locked: bool
    version: int
    created_at: datetime
    terms: list[AcademicTermBrief] = Field(default_factory=list)


class AcademicTermCreate(BaseModel):
    academic_year_id: uuid.UUID
    name: str = Field(min_length=2, max_length=60)
    term_type: TermType
    sequence: int = Field(ge=1, le=12)
    start_date: date
    end_date: date
    registration_start: date | None = None
    registration_end: date | None = None
    add_drop_end: date | None = None
    last_instruction_date: date | None = None


class AcademicTermUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    start_date: date | None = None
    end_date: date | None = None
    registration_start: date | None = None
    registration_end: date | None = None
    add_drop_end: date | None = None
    last_instruction_date: date | None = None
    version: int | None = None


class TermCloseCheck(BaseModel):
    key: str
    label: str
    passed: bool
    detail: str | None = None


class AcademicTermResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID
    academic_year_name: str | None = None
    name: str
    term_type: str
    sequence: int
    start_date: date
    end_date: date
    registration_start: date | None = None
    registration_end: date | None = None
    add_drop_end: date | None = None
    last_instruction_date: date | None = None
    is_current: bool
    is_locked: bool
    status: str
    version: int
    next_status: str | None = None
    blocking_checks: list[TermCloseCheck] = Field(default_factory=list)


class TermStatusChange(BaseModel):
    status: TermStatus
    version: int | None = None


class RolloverTerm(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    term_type: TermType
    sequence: int = Field(ge=1, le=12)
    start_date: date
    end_date: date
    registration_start: date | None = None
    registration_end: date | None = None
    add_drop_end: date | None = None
    last_instruction_date: date | None = None


class RolloverRequest(BaseModel):
    new_year_name: str = Field(min_length=4, max_length=20)
    start_date: date
    end_date: date
    terms: list[RolloverTerm] = Field(min_length=1, max_length=6)
    promote_batches: bool = False
    college_id: uuid.UUID | None = Field(default=None, description="scope of the years (NULL = institution-wide)")
    lock_previous: bool = False

    @model_validator(mode="after")
    def _range(self) -> "RolloverRequest":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class RolloverResponse(BaseModel):
    previous_year_id: uuid.UUID | None = None
    year: AcademicYearResponse
    current_term_id: uuid.UUID | None = None
    promoted: dict[str, int] = Field(default_factory=dict)
    event_id: uuid.UUID
