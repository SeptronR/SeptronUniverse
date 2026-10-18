"""Scholarship schemas — Prompts/12 §12.4."""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.enums.fees import AmountType, DisbursementMode, ScholarshipProvider
from app.schemas.common import ORMModel


class ScholarshipIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    provider: ScholarshipProvider
    scheme_code: str | None = Field(None, max_length=40)
    amount_paise: int | None = Field(None, ge=0)
    amount_type: AmountType = AmountType.FIXED
    eligibility_rules: dict[str, Any] | None = Field(
        None, description="{categories:[], income_cap_paise, min_cgpa, program_ids:[]}"
    )
    academic_year_id: uuid.UUID | None = None
    applications_open: date | None = None
    applications_close: date | None = None
    description: str | None = None
    is_active: bool = True


class ScholarshipOut(ORMModel):
    id: uuid.UUID
    name: str
    provider: str
    scheme_code: str | None = None
    amount_paise: int | None = None
    amount_type: str
    eligibility_rules: dict[str, Any] | None = None
    academic_year_id: uuid.UUID | None = None
    applications_open: date | None = None
    applications_close: date | None = None
    description: str | None = None
    is_active: bool
    applications: int = 0


class ScholarshipApply(BaseModel):
    enrollment_id: uuid.UUID | None = None
    income_paise: int | None = Field(None, ge=0)
    documents: list[dict[str, Any]] | None = None


class ScholarshipDecision(BaseModel):
    comment: str | None = Field(None, max_length=1000)
    sanctioned_paise: int | None = Field(None, ge=0)


class DisburseRequest(BaseModel):
    mode: DisbursementMode
    reference: str | None = Field(None, max_length=60)
    invoice_id: uuid.UUID | None = None


class ScholarshipApplicationOut(ORMModel):
    id: uuid.UUID
    scholarship_id: uuid.UUID
    scholarship_name: str | None = None
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    income_paise: int | None = None
    documents: list[dict[str, Any]] | None = None
    status: str
    sanctioned_paise: int | None = None
    disbursement_mode: str | None = None
    external_ref: str | None = None
    disbursed_at: datetime | None = None
    workflow_instance_id: uuid.UUID | None = None
    created_at: datetime
    can_act: bool = False
