"""Reports schemas — Prompts/36 §36.4."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.enums.reports import REGISTERS

Fmt = Literal["xlsx", "csv", "pdf", "docx", "json"]


# ---- catalogue / runs ---------------------------------------------------------------------------------------------------
class ReportLastRun(BaseModel):
    job_id: uuid.UUID
    status: str
    created_at: datetime | None = None
    rows: int | None = None


class ReportCatalogueOut(BaseModel):
    key: str
    module: str
    category: str
    name: str
    description: str = ""
    formats: list[str]
    params_schema: dict[str, Any] = Field(default_factory=dict)
    layout: str = "portrait"
    register_name: str | None = Field(None, alias="register")
    statutory: dict[str, Any] | None = None
    chart_key: str | None = None
    preview: bool = True
    pii: bool = False
    favourite: bool = False
    last_run: ReportLastRun | None = None

    model_config = {"populate_by_name": True}


class DeliverTo(BaseModel):
    user_ids: list[uuid.UUID] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)


class ReportRunRequest(BaseModel):
    key: str = Field(min_length=3, max_length=120)
    params: dict[str, Any] = Field(default_factory=dict)
    format: Fmt = "xlsx"
    scope: str | None = None
    deliver_to: DeliverTo | None = None
    inline_preview: bool = False


class ReportPreview(BaseModel):
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] = Field(default_factory=dict)
    truncated: bool = False
    masked_fields: list[str] = Field(default_factory=list)


class ReportRunOut(BaseModel):
    job_id: uuid.UUID | None = None
    key: str
    status: str
    format: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    rows: int | None = None
    preview: ReportPreview | None = None
    result_url: str | None = None
    checksum: str | None = None
    requested_by: uuid.UUID | None = None
    requested_by_name: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    purged: bool = False
    scope: str | None = None


class ReportRunListOut(BaseModel):
    items: list[ReportRunOut]
    total: int


class FavouriteToggle(BaseModel):
    key: str = Field(min_length=3, max_length=120)


class FavouritesOut(BaseModel):
    keys: list[str]
    recent: list[dict[str, Any]] = Field(default_factory=list)


# ---- registers ------------------------------------------------------------------------------------------------------------
class RegisterPeriod(BaseModel):
    from_: date | None = Field(None, alias="from")
    to: date | None = None

    model_config = {"populate_by_name": True}


class RegisterRequest(BaseModel):
    register_name: str = Field(alias="register")
    scope: dict[str, Any] = Field(default_factory=dict)
    period: RegisterPeriod | None = None
    format: Literal["pdf", "xlsx", "csv"] = "pdf"

    model_config = {"populate_by_name": True}

    @field_validator("register_name")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in REGISTERS:
            raise ValueError(f"register must be one of {', '.join(REGISTERS)}")
        return v


class RegisterOut(BaseModel):
    register_name: str = Field(alias="register")
    key: str
    name: str
    params_schema: dict[str, Any] = Field(default_factory=dict)
    module: str
    available: bool = True

    model_config = {"populate_by_name": True}


# ---- builder ----------------------------------------------------------------------------------------------------------------
class ReportModelOut(BaseModel):
    key: str
    module: str
    base_entity: str
    label: str
    columns: list[dict[str, Any]]
    joins: list[dict[str, Any]]
    filters: list[str]
    default_sort: str | None = None


class BuilderFilter(BaseModel):
    field: str
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "is_null", "not_null", "between"] = "eq"
    value: Any = None


class BuilderAggregate(BaseModel):
    field: str
    fn: Literal["count", "sum", "avg", "min", "max"] = "count"


class BuilderSort(BaseModel):
    field: str
    dir: Literal["asc", "desc"] = "asc"


class BuilderDefinition(BaseModel):
    model_key: str
    columns: list[str] = Field(default_factory=list)
    joins: list[str] = Field(default_factory=list)
    filters: list[BuilderFilter] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    aggregates: list[BuilderAggregate] = Field(default_factory=list)
    sort: list[BuilderSort] = Field(default_factory=list)
    limit: int | None = Field(None, ge=1, le=500000)
    name: str | None = Field(None, max_length=160)
    share_with_roles: list[str] = Field(default_factory=list)
    scope: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> "BuilderDefinition":
        if not self.columns and not self.aggregates:
            raise ValueError("pick at least one column or aggregate")
        return self


class BuilderRunRequest(BaseModel):
    definition: BuilderDefinition
    format: Literal["xlsx", "csv", "pdf", "json"] = "xlsx"


class BuilderPreviewOut(BaseModel):
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    total: int
    totals: dict[str, Any] = Field(default_factory=dict)
    masked_fields: list[str] = Field(default_factory=list)


class SavedReportIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    definition: BuilderDefinition
    share_with_roles: list[str] = Field(default_factory=list)


class SavedReportShare(BaseModel):
    roles: list[str] = Field(default_factory=list)


class SavedReportOut(BaseModel):
    id: str
    name: str
    definition: dict[str, Any]
    owner: uuid.UUID | None = None
    owner_name: str | None = None
    shared: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    mine: bool = False


# ---- statutory --------------------------------------------------------------------------------------------------------------
class StatutoryListItem(BaseModel):
    code: str
    name: str
    period_type: str
    last_period: str | None = None
    status: str | None = None
    signoff_roles: list[str]
    formats: list[str] = Field(default_factory=list)
    due_on: date | None = None
    submission_type: str | None = None
    disciplines: list[str] = Field(default_factory=list)


class StatutoryGenerateRequest(BaseModel):
    period_label: str = Field(min_length=4, max_length=20)
    college_id: uuid.UUID | None = None
    discipline: str | None = Field(None, max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)


class StatutoryFile(BaseModel):
    format: str
    url: str | None = None
    checksum: str | None = None
    issued_document_id: uuid.UUID | None = None
    revoked: bool = False


class StatutorySignoff(BaseModel):
    role: str
    user: uuid.UUID | None = None
    user_name: str | None = None
    at: datetime | None = None


class StatutoryValidation(BaseModel):
    section: str
    check: str
    status: Literal["pass", "warn", "fail"]
    detail: str | None = None


class StatutoryOut(BaseModel):
    code: str
    name: str
    period_label: str
    discipline: str | None = None
    college_id: uuid.UUID | None = None
    version: int = 1
    status: str
    payload_summary: dict[str, Any] = Field(default_factory=dict)
    sections: dict[str, Any] = Field(default_factory=dict)
    validation: list[StatutoryValidation] = Field(default_factory=list)
    validation_status: str = "pass"
    files: list[StatutoryFile] = Field(default_factory=list)
    compliance_submission_id: uuid.UUID | None = None
    signoffs: list[StatutorySignoff] = Field(default_factory=list)
    signoff_roles: list[str] = Field(default_factory=list)
    job_id: uuid.UUID | None = None
    generated_at: datetime | None = None
    reopened: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)


class StatutoryReviewAction(BaseModel):
    action: Literal["request_review", "sign_off", "reopen"]
    remarks: str | None = Field(None, max_length=2000)
    role: str | None = None


class StatutoryDiffOut(BaseModel):
    code: str
    period_label: str
    vs: str | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)


# ---- schedules --------------------------------------------------------------------------------------------------------------
class ScheduleRecipients(BaseModel):
    roles: list[str] = Field(default_factory=list)
    user_ids: list[uuid.UUID] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)


class ScheduleIn(BaseModel):
    name: str | None = Field(None, max_length=160)
    key: str | None = None
    saved_report_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    format: Literal["xlsx", "csv", "pdf"] = "xlsx"
    cadence: Literal["daily", "weekly", "monthly", "termly", "cron"]
    at: str = Field("07:00", pattern=r"^\d{2}:\d{2}$")
    weekday: int | None = Field(None, ge=0, le=6)
    day_of_month: int | None = Field(None, ge=1, le=28)
    cron: str | None = Field(None, max_length=120)
    recipients: ScheduleRecipients = Field(default_factory=ScheduleRecipients)
    channels: list[Literal["email", "whatsapp", "in_app"]] = Field(default_factory=lambda: ["email", "in_app"])  # type: ignore[arg-type]
    is_active: bool = True

    @model_validator(mode="after")
    def _target(self) -> "ScheduleIn":
        if bool(self.key) == bool(self.saved_report_id):
            raise ValueError("give exactly one of key / saved_report_id")
        return self


class ScheduleOut(BaseModel):
    id: str
    name: str | None = None
    key: str | None = None
    saved_report_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    format: str
    cadence: str
    at: str
    weekday: int | None = None
    day_of_month: int | None = None
    cron: str | None = None
    recipients: dict[str, Any] = Field(default_factory=dict)
    channels: list[str] = Field(default_factory=list)
    is_active: bool = True
    paused_reason: str | None = None
    failures: int = 0
    owner: uuid.UUID | None = None
    owner_name: str | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None


class ScheduleRunNow(BaseModel):
    jobs: list[uuid.UUID]
    recipients: int


class ScheduleHistoryOut(BaseModel):
    run_at: datetime | None = None
    status: str
    result_url: str | None = None
    delivered_to: list[str] = Field(default_factory=list)
    job_id: uuid.UUID | None = None
    error: str | None = None


# ---- access log -----------------------------------------------------------------------------------------------------------
class ReportAccessLogOut(BaseModel):
    id: uuid.UUID
    at: datetime
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    action: str
    key: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    record_id: uuid.UUID | None = None


class ReportJobQueued(BaseModel):
    job_id: uuid.UUID
    status: str = "queued"
    key: str | None = None
