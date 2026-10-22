"""OBE definition schemas — Prompts/13 §13.4."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class OutcomeIn(BaseModel):
    outcome_type: Literal["PEO", "PO", "PSO"]
    code: str = Field(min_length=1, max_length=10)
    statement: str = Field(min_length=3)
    framework: str | None = Field(None, max_length=30)
    sequence: int = 1


class OutcomeOut(ORMModel):
    id: uuid.UUID
    outcome_type: str
    code: str
    statement: str
    framework: str | None = None
    sequence: int
    is_active: bool


class PeoPoCell(BaseModel):
    peo_id: uuid.UUID
    po_id: uuid.UUID
    level: int = Field(ge=1, le=3)


class ProgramOutcomes(BaseModel):
    program_id: uuid.UUID
    outcomes: list[OutcomeOut] = Field(default_factory=list)
    peo_po: list[PeoPoCell] = Field(default_factory=list)


class OutcomesReplace(BaseModel):
    outcomes: list[OutcomeIn]


class PeoPoMatrix(BaseModel):
    cells: list[PeoPoCell]


class TemplateImport(BaseModel):
    template: Literal["nba_engineering", "generic"] | None = None
    psos: list[str] = Field(default_factory=list)


class CoIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    statement: str = Field(min_length=3)
    bloom_level: str | None = None
    sequence: int = 1


class CoOut(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    code: str
    statement: str
    bloom_level: str | None = None
    sequence: int


class CoPoCell(BaseModel):
    co_id: uuid.UUID
    outcome_id: uuid.UUID
    level: int = Field(ge=1, le=3)
    justification: str | None = None


class CoReplace(BaseModel):
    outcomes: list[CoIn]


class CoPoMatrixReplace(BaseModel):
    cells: list[CoPoCell]


class CourseOutcomes(BaseModel):
    course_id: uuid.UUID
    cos: list[CoOut] = Field(default_factory=list)
    program_outcomes: list[OutcomeOut] = Field(default_factory=list)
    matrix: list[CoPoCell] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    editable: bool = False
