"""No-dues schemas — Prompts/12 §12.4."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.enums.fees import NoDuesPurpose
from app.schemas.common import ORMModel


class NoDuesCreate(BaseModel):
    purpose: NoDuesPurpose
    enrollment_id: uuid.UUID | None = None


class SignoffRequest(BaseModel):
    department_key: str | None = Field(None, description="defaults to the only department the caller owns")
    status: str = Field(pattern="^(cleared|dues_pending)$")
    dues_paise: int = Field(0, ge=0)
    remarks: str | None = Field(None, max_length=1000)


class NoDuesSignoffOut(ORMModel):
    id: uuid.UUID
    department_key: str
    status: str
    dues_paise: int
    remarks: str | None = None
    signed_by: uuid.UUID | None = None
    signed_at: datetime | None = None
    can_sign: bool = False


class NoDuesResponse(ORMModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    purpose: str
    status: str
    requested_at: datetime
    cleared_at: datetime | None = None
    certificate_number: str | None = None
    signoffs: list[NoDuesSignoffOut] = Field(default_factory=list)
