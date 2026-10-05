"""Payroll components, salary structures, payroll runs, registers, Form 16 and loans — Prompts/06 §06.4
(``payroll.py``). Money is **paise** (integers)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums.hr import CalcType, ComponentType, LoanType, StatutoryKind
from app.schemas.common import ORMModel


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PayrollComponentIn(_Strict):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=2, max_length=80)
    component_type: ComponentType
    calc_type: CalcType = CalcType.FIXED
    formula: dict[str, Any] | None = None  # {amount_paise} | {pct} | {expr}
    statutory_kind: StatutoryKind | None = None
    is_taxable: bool = True
    sequence: int = Field(default=1, ge=1, le=999)
    is_active: bool = True

    @model_validator(mode="after")
    def _calc(self) -> "PayrollComponentIn":
        f = self.formula or {}
        if self.calc_type == CalcType.STATUTORY and self.statutory_kind is None:
            raise ValueError("statutory components need statutory_kind")
        if self.calc_type == CalcType.PCT_OF_BASIC and not isinstance(f.get("pct"), int | float):
            raise ValueError("pct_of_basic needs formula.pct")
        if self.calc_type == CalcType.FORMULA and not isinstance(f.get("expr"), str):
            raise ValueError("formula components need formula.expr")
        return self


class PayrollComponentOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    component_type: str
    calc_type: str
    formula: dict[str, Any] | None = None
    is_statutory: bool
    statutory_kind: str | None = None
    is_taxable: bool
    sequence: int
    is_active: bool


class SalaryStructureIn(_Strict):
    effective_from: date
    pay_level: str | None = Field(default=None, max_length=20)
    basic_paise: int = Field(gt=0, le=2_000_000_000)
    components: dict[str, dict[str, Any]] = Field(default_factory=dict)  # {CODE: {amount_paise} | {pct}}
    ctc_paise: int | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=300, description="service-book note (increment, revision …)")


class SalaryStructureOut(ORMModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None
    pay_level: str | None = None
    basic_paise: int
    components: dict[str, Any]
    ctc_paise: int | None = None
    created_at: datetime
    monthly_gross_paise: int | None = None


class PayrollGenerateRequest(_Strict):
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)
    college_id: uuid.UUID | None = None
    staff_ids: list[uuid.UUID] | None = Field(default=None, max_length=5000)


class PayrollItemOut(ORMModel):
    id: uuid.UUID
    component_id: uuid.UUID | None = None
    label: str
    component_type: str
    amount_paise: int
    source_type: str | None = None
    source_id: uuid.UUID | None = None


class PayrollResponse(ORMModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str | None = None
    employee_id: str | None = None
    department_code: str | None = None
    month: int
    year: int
    working_days: int | None = None
    paid_days: Decimal | None = None
    lop_days: Decimal
    gross_paise: int
    deductions_paise: int
    employer_contrib_paise: int
    net_paise: int
    status: str
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    paid_at: datetime | None = None
    payment_ref: str | None = None
    payslip_url: str | None = None
    items: list[PayrollItemOut] = Field(default_factory=list)


class PayrollMarkPaid(_Strict):
    payment_ref: str = Field(min_length=3, max_length=60)
    paid_on: date | None = None


class PayrollBulkAction(_Strict):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)


class PayrollBulkResult(BaseModel):
    succeeded: list[uuid.UUID]
    failed: list[dict[str, Any]]
    job_id: uuid.UUID | None = None


class RegisterResponse(BaseModel):
    kind: str
    month: int
    year: int
    columns: list[str]
    rows: list[dict[str, Any]]
    totals: dict[str, int]


class Form16Data(BaseModel):
    staff_id: uuid.UUID
    staff_name: str
    employee_id: str
    pan: str | None = None
    financial_year: str
    assessment_year: str
    regime: str
    months: list[dict[str, Any]]
    gross_salary_paise: int
    exempt_allowances_paise: int
    standard_deduction_paise: int
    professional_tax_paise: int
    pf_employee_paise: int
    taxable_income_paise: int
    tax_on_income_paise: int
    tds_deducted_paise: int
    quarters: dict[str, int]


class LoanIn(_Strict):
    staff_id: uuid.UUID | None = None  # omitted → the caller's own request (workflow hr.loan)
    loan_type: LoanType
    principal_paise: int = Field(gt=0, le=1_000_000_000)
    emi_paise: int = Field(gt=0)
    start_month: date
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _emi(self) -> "LoanIn":
        if self.emi_paise > self.principal_paise:
            raise ValueError("emi_paise cannot exceed principal_paise")
        return self


class LoanOut(ORMModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str | None = None
    employee_id: str | None = None
    loan_type: str
    principal_paise: int
    emi_paise: int
    start_month: date
    balance_paise: int
    status: str
    workflow_instance_id: uuid.UUID | None = None
    created_at: datetime
    emis_remaining: int | None = None
