"""Leave types, requests, balances and encashment — Prompts/06 §06.4 (``leaves.py``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums.hr import HalfDay, LeaveAccrual
from app.schemas.common import ORMModel


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeaveTypeIn(_Strict):
    code: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z0-9_]+$")
    name: str = Field(min_length=2, max_length=80)
    annual_quota: Decimal | None = Field(default=None, ge=0, le=400)
    accrual: LeaveAccrual = LeaveAccrual.YEARLY
    carry_forward_max: Decimal | None = Field(default=None, ge=0, le=1000)
    is_paid: bool = True
    is_encashable: bool = False
    requires_document: bool = False
    applies_to: dict[str, Any] | None = None
    is_active: bool = True


class LeaveTypeOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    annual_quota: Decimal | None = None
    accrual: str
    carry_forward_max: Decimal | None = None
    is_paid: bool
    is_encashable: bool
    requires_document: bool
    applies_to: dict[str, Any] | None = None
    is_active: bool


class LeaveApply(_Strict):
    leave_type_id: uuid.UUID
    from_date: date
    to_date: date
    half_day: HalfDay | None = None
    reason: str = Field(min_length=3, max_length=2000)
    document_url: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _range(self) -> "LeaveApply":
        if self.to_date < self.from_date:
            raise ValueError("to_date must not be before from_date")
        if self.half_day and self.from_date != self.to_date:
            raise ValueError("a half day covers a single date")
        return self


class LeaveDecision(_Strict):
    comment: str | None = Field(default=None, max_length=1000)


class LeaveResponse(ORMModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str | None = None
    employee_id: str | None = None
    department_code: str | None = None
    leave_type_id: uuid.UUID
    leave_type_code: str | None = None
    leave_type_name: str | None = None
    from_date: date
    to_date: date
    days_count: Decimal
    half_day: str | None = None
    reason: str | None = None
    document_url: str | None = None
    status: str
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    workflow_instance_id: uuid.UUID | None = None
    workflow_status: str | None = None
    current_step: int | None = None
    created_at: datetime
    is_mine: bool = False
    can_act: bool = False


class LeaveBalanceResponse(BaseModel):
    leave_type_id: uuid.UUID
    code: str
    name: str
    year: int
    annual_quota: Decimal | None = None
    opening: Decimal
    accrued: Decimal
    used: Decimal
    encashed: Decimal
    balance: Decimal
    pending: Decimal
    available: Decimal | None = None  # balance − pending (None = unlimited)
    is_paid: bool
    is_encashable: bool


class LeaveEncashRequest(_Strict):
    leave_type_id: uuid.UUID
    days: Decimal = Field(gt=0, le=300)
    reason: str | None = Field(default=None, max_length=500)


class LeaveEncashResult(BaseModel):
    workflow_instance_id: uuid.UUID
    leave_type_code: str
    days: Decimal
    amount_paise: int
    status: str


class LeaveCalendarItem(BaseModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str
    department_code: str | None = None
    leave_type_code: str
    from_date: date
    to_date: date
    days_count: Decimal
    status: str
