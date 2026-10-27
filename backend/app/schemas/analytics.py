"""Dashboards, analytics & early warning schemas — Prompts/35 §35.4."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ScopeName = Literal["self", "mine", "own", "department", "faculty", "college", "all"]


# ---- charts -----------------------------------------------------------------------------------------------------------
class ChartTableOut(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class ChartOut(BaseModel):
    """``ChartData{series[], dims{}, table{columns[], rows[]}, generated_at, stale}`` + drill-down."""

    key: str
    kind: str
    title: str
    series: list[dict[str, Any]]
    dims: dict[str, Any] = Field(default_factory=dict)
    table: ChartTableOut
    generated_at: datetime
    stale: bool = False
    scope: str = "all"
    drilldown: dict[str, Any] | None = None
    total: float | None = None


class ChartCatalogueItem(BaseModel):
    key: str
    module: str
    kind: str
    title: str
    dims: list[str]
    params_schema: dict[str, Any] = Field(default_factory=dict)
    drilldown_route: str | None = None
    feature: str | None = None
    source_view: str | None = None
    description: str = ""


class ChartQuery(BaseModel):
    key: str
    scope: ScopeName | None = None
    dims: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    format: Literal["json", "table", "csv"] = "json"


class ChartExportIn(BaseModel):
    scope: ScopeName | None = None
    dims: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    format: Literal["csv", "xlsx"] = "xlsx"


class DrilldownOut(BaseModel):
    key: str
    total: int
    rows: list[dict[str, Any]]
    masked: bool = True
    aggregates_only: bool = False
    page: int = 1


class InsightsOut(BaseModel):
    module: str
    filters: dict[str, Any] = Field(default_factory=dict)
    charts: list[ChartOut]


# ---- dashboards -------------------------------------------------------------------------------------------------------
class LayoutWidget(BaseModel):
    key: str = Field(max_length=120)
    size: Literal["sm", "md", "lg", "xl"] | None = None
    position: int | None = None
    hidden: bool = False
    kind: str | None = None


class DashboardLayoutIn(BaseModel):
    columns: int | None = Field(default=None, ge=1, le=6)
    widgets: list[LayoutWidget]


class DashboardLayoutOut(BaseModel):
    role: str
    columns: int
    widgets: list[LayoutWidget]
    customised: bool = False


class DashboardPinsIn(BaseModel):
    pinned_keys: list[str] = Field(default_factory=list, max_length=50)
    hidden_keys: list[str] = Field(default_factory=list, max_length=50)


class DashboardPinsOut(BaseModel):
    pinned_keys: list[str]
    hidden_keys: list[str]


class DashboardWidgetOut(BaseModel):
    key: str
    kind: Literal["chart", "stat", "list", "action"]
    size: str = "md"
    title: str | None = None
    permission_ok: bool = True
    chart_kind: str | None = None
    data: dict[str, Any] | None = None
    stat: dict[str, Any] | None = None
    items: list[dict[str, Any]] | None = None
    route: str | None = None
    icon: str | None = None
    drilldown: dict[str, Any] | None = None
    stale: bool = False
    generated_at: datetime | None = None
    unavailable: bool = False
    reason: str | None = None


class DashboardOut(BaseModel):
    role: str
    roles: list[str] = Field(default_factory=list)
    layout: dict[str, Any]
    widgets: list[DashboardWidgetOut]
    targets: dict[str, Any] = Field(default_factory=dict)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    visibility: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] | None = None


# ---- KPIs ---------------------------------------------------------------------------------------------------------------
class KpiTargetsIn(BaseModel):
    targets: dict[str, float] = Field(default_factory=dict)
    alert_recipients: dict[str, list[str]] | None = None
    college_id: uuid.UUID | None = None


class KpiTargetsOut(BaseModel):
    targets: dict[str, Any]
    alert_recipients: dict[str, Any] = Field(default_factory=dict)
    college_id: uuid.UUID | None = None
    history: dict[str, list[list[Any]]] = Field(default_factory=dict)


class KpiAlertOut(BaseModel):
    key: str | None
    value: float | None = None
    target: float | None = None
    direction: str | None = None
    since: str | None = None
    scope: str | None = None
    open: bool = True
    recovered_at: str | None = None


class PublicCountersOut(BaseModel):
    counters: dict[str, Any]
    as_of: date | None = None


# ---- read models / digests ------------------------------------------------------------------------------------------------
class RefreshRequest(BaseModel):
    views: list[str] = Field(default_factory=list)


class RefreshStatusOut(BaseModel):
    view: str
    description: str = ""
    refreshed_at: datetime | None = None
    duration_ms: int | None = None
    rows: int | None = None
    stale: bool = True
    dirty: int = 0
    interval_minutes: int = 120


class DigestScheduleIn(BaseModel):
    cadence: Literal["daily", "weekly"]
    roles: list[str] = Field(default_factory=list)
    user_ids: list[uuid.UUID] = Field(default_factory=list)
    channels: list[Literal["in_app", "email", "whatsapp"]] = Field(default_factory=lambda: ["in_app", "email"])  # type: ignore[arg-type]
    hour: int = Field(default=7, ge=0, le=23)


class DigestScheduleOut(BaseModel):
    id: str
    cadence: str
    roles: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    hour: int = 7
    last_sent_at: str | None = None
    created_at: str | None = None


class JobQueued(BaseModel):
    job_id: uuid.UUID
    detail: dict[str, Any] = Field(default_factory=dict)


# ---- early warning ------------------------------------------------------------------------------------------------------------
class RiskCohortCell(BaseModel):
    group: str
    group_id: str | None = None
    low: int = 0
    medium: int = 0
    high: int = 0
    total: int = 0
    acknowledged_pct: float = 0.0


class RiskCohortOut(BaseModel):
    term_id: uuid.UUID
    group_by: str
    scope: str
    cells: list[RiskCohortCell]
    factor_means: dict[str, float | None]
    trend: list[dict[str, Any]] = Field(default_factory=list)
    aggregates_only: bool = False


class RiskTrendOut(BaseModel):
    periods: list[str]
    counts_by_level: dict[str, list[int]]
    points: list[dict[str, Any]] = Field(default_factory=list)


class RiskStudentOut(BaseModel):
    enrollment_id: uuid.UUID | None = None
    student_name: str | None = None
    registration_number: str | None = None
    department_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    score: float
    level: str
    factors: dict[str, Any] = Field(default_factory=dict)
    mentor: str | None = None
    mentor_staff_id: uuid.UUID | None = None
    last_intervention: dict[str, Any] | None = None
    acknowledged: bool = False


class InterventionIn(BaseModel):
    intervention_type: str = Field(min_length=2, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)
    follow_up_on: date | None = None


class InterventionOut(BaseModel):
    id: uuid.UUID
    enrollment_id: uuid.UUID
    intervention_type: str | None = None
    notes: str | None = None
    held_on: date
    follow_up_on: date | None = None
    logged_by: str | None = None
    risk_level_at_log: str | None = None


class RiskEffectivenessOut(BaseModel):
    term_id: uuid.UUID
    by_type: dict[str, dict[str, int]]


class RiskExportIn(BaseModel):
    term_id: uuid.UUID | None = None
    kind: Literal["cohort", "students", "iqac"] = "cohort"
    scope: ScopeName | None = None
