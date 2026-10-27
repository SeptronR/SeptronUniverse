"""Dashboards, analytics & early warning — Prompts/35 §35.8.

* ``/dashboard*`` {core.dashboard} — role dashboard, single widget (live re-fetch), my pins, institution layouts
  (``settings:manage``);
* ``/analytics/*`` {analytics.core} — chart catalogue / data (+ table / CSV) / drill-down / export job, Insights tab per
  module, KPI targets / alerts, read models (status, manual refresh job), digests; public website counters;
* ``/risk/cohort|students|…`` {analytics.early_warning} — cohort heat map, trend, student lists under the Phase 27
  visibility, interventions (stored as Phase 27 mentoring sessions), effectiveness, cohort export job.

Visibility (self / wards / own / department / faculty / college / all; aggregates-only for IQAC / auditor) is applied by
the services per chart module; ``meta.visibility`` drives the ScopeTabs.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.db.session import get_db
from app.schemas.analytics import (
    ChartCatalogueItem,
    ChartExportIn,
    ChartOut,
    DashboardLayoutIn,
    DashboardLayoutOut,
    DashboardOut,
    DashboardPinsIn,
    DashboardPinsOut,
    DashboardWidgetOut,
    DigestScheduleIn,
    DigestScheduleOut,
    DrilldownOut,
    InsightsOut,
    InterventionIn,
    InterventionOut,
    JobQueued,
    KpiAlertOut,
    KpiTargetsIn,
    KpiTargetsOut,
    PublicCountersOut,
    RefreshRequest,
    RefreshStatusOut,
    RiskCohortOut,
    RiskEffectivenessOut,
    RiskExportIn,
    RiskStudentOut,
    RiskTrendOut,
)
from app.schemas.common import Envelope
from app.services.analytics.chart_service import ChartService
from app.services.analytics.dashboard_service import DashboardService
from app.services.analytics.digest_service import DigestService
from app.services.analytics.kpi_service import KPI_TARGET_COLUMNS, KpiService
from app.services.analytics.readmodel_service import ReadModelService
from app.services.analytics.risk_analytics_service import RiskAnalyticsService
from app.utils.response import ok

router = APIRouter(tags=["analytics"])
public_router = APIRouter(tags=["analytics"])

DASH = any_permission_required(("dashboard", "view"))
SETTINGS = any_permission_required(("settings", "manage"))
VIEW = any_permission_required(("analytics", "view"), ("analytics", "manage"))
EXPORT = any_permission_required(("analytics", "export"), ("analytics", "manage"))
MANAGE = any_permission_required(("analytics", "manage"))
TARGETS_VIEW = any_permission_required(("analytics", "view"), ("settings", "manage"))
RISK = any_permission_required(
    ("mentoring", "view_all"), ("mentoring", "manage"), ("mentoring", "view"), ("accreditation", "view")
)
RISK_WRITE = any_permission_required(("mentoring", "manage"))
RISK_EXPORT = any_permission_required(("mentoring", "view_all"), ("accreditation", "view"))

CORE_DASH = [feature_required("core.dashboard")]
CORE = [feature_required("analytics.core")]
EW = [feature_required("analytics.early_warning")]


def _dims(
    college_id: uuid.UUID | None,
    department_id: uuid.UUID | None,
    program_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    term_id: uuid.UUID | None,
    period: str | None,
) -> dict[str, Any]:
    return {
        k: str(v) if isinstance(v, uuid.UUID) else v
        for k, v in {
            "college_id": college_id,
            "department_id": department_id,
            "program_id": program_id,
            "batch_id": batch_id,
            "term_id": term_id,
            "period": period,
        }.items()
        if v
    }


def _params(request: Request, prefix: str = "params[") -> dict[str, Any]:
    """``params[metric_key]=…`` / ``dims[period]=…`` query style (Prompts/35 §35.11 step 4)."""
    out: dict[str, Any] = {}
    for k, v in request.query_params.multi_items():
        if k.startswith(prefix) and k.endswith("]"):
            out[k[len(prefix) : -1]] = v
    return out


def _vis(data: Any, visibility: dict[str, Any]) -> dict[str, Any]:
    res = ok(data)
    res["meta"]["visibility"] = visibility
    return res


# ---- dashboard -----------------------------------------------------------------------------------------------------------
@router.get(
    "/dashboard",
    summary="Role dashboard (widgets rendered, meta.visibility)",
    response_model=Envelope[DashboardOut],
    dependencies=CORE_DASH,
)
async def dashboard(
    request: Request,
    role: str | None = None,
    scope: str | None = None,
    college_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(DASH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await DashboardService(db, principal, request).for_role(
        role, scope, _dims(college_id, department_id, None, None, term_id, None)
    )
    return _vis(out, out["visibility"])


@router.get(
    "/dashboard/widgets/{key}",
    summary="Single widget (re-fetch / live refresh)",
    response_model=Envelope[DashboardWidgetOut],
    dependencies=CORE_DASH,
)
async def dashboard_widget(
    key: str,
    request: Request,
    role: str | None = None,
    scope: str | None = None,
    college_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(DASH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await DashboardService(db, principal, request).for_role(
        role, scope, _dims(college_id, department_id, None, None, term_id, None), only=key
    )
    if not out["widgets"]:
        raise APIError(404, ErrorCode.NOT_FOUND, "Widget not found on this dashboard")
    return ok(out["widgets"][0])


@router.put(
    "/dashboard/pins",
    summary="My pinned / hidden widgets",
    response_model=Envelope[DashboardPinsOut],
    dependencies=CORE_DASH,
)
async def dashboard_pins(
    body: DashboardPinsIn, request: Request, principal: Principal = Depends(DASH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DashboardService(db, principal, request).put_pins(body.pinned_keys, body.hidden_keys))


@router.get(
    "/dashboard/layouts/{role}",
    summary="Institution layout for a role",
    response_model=Envelope[DashboardLayoutOut],
    dependencies=CORE_DASH,
)
async def get_layout(
    role: str, request: Request, principal: Principal = Depends(SETTINGS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DashboardService(db, principal, request).get_layout(role))


@router.put(
    "/dashboard/layouts/{role}",
    summary="Edit the institution layout of a role",
    response_model=Envelope[DashboardLayoutOut],
    dependencies=CORE_DASH,
)
async def put_layout(
    role: str,
    body: DashboardLayoutIn,
    request: Request,
    principal: Principal = Depends(SETTINGS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    widgets = [w.model_dump(exclude_none=True) for w in body.widgets]
    return ok(await DashboardService(db, principal, request).put_layout(role, widgets, body.columns))


@router.post(
    "/dashboard/layouts/{role}/reset",
    summary="Reset a role layout to the defaults",
    response_model=Envelope[DashboardLayoutOut],
    dependencies=CORE_DASH,
)
async def reset_layout(
    role: str, request: Request, principal: Principal = Depends(SETTINGS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DashboardService(db, principal, request).reset_layout(role))


# ---- charts ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/analytics/charts",
    summary="Chart catalogue for me",
    response_model=Envelope[list[ChartCatalogueItem]],
    dependencies=CORE,
)
async def chart_catalogue(
    request: Request,
    module: str | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ChartService(db, principal, request).catalogue(module))


@router.get(
    "/analytics/charts/{key}",
    summary="Chart data + table + drill-down (format=json|table|csv)",
    response_model=Envelope[ChartOut],
    dependencies=CORE,
)
async def chart_data(
    key: str,
    request: Request,
    scope: str | None = None,
    format: str = Query("json", pattern="^(json|table|csv)$"),
    college_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    term_id: uuid.UUID | None = None,
    period: str | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ChartService(db, principal, request)
    dims = {**_dims(college_id, department_id, program_id, batch_id, term_id, period), **_params(request, "dims[")}
    data = await svc.render(key, scope=scope, dims=dims, params=_params(request))
    etag = svc.etag(data)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    if format == "csv":
        return PlainTextResponse(await svc.table_csv(data), media_type="text/csv", headers={"ETag": etag})
    res = _vis(data.__dict__, svc.visibility_meta(svc_module(key)))
    if format == "table":
        res["data"]["series"] = []
    return JSONResponse(content=_json(res), headers={"ETag": etag})


def svc_module(key: str) -> str:
    from app.core.charts import CHART_REGISTRY

    spec = CHART_REGISTRY.get(key)
    return spec.module if spec else "analytics"


def _json(obj: Any) -> Any:
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(obj)


@router.get(
    "/analytics/charts/{key}/drilldown",
    summary="Rows behind a chart point (target module list, masked)",
    response_model=Envelope[DrilldownOut],
    dependencies=CORE,
)
async def chart_drilldown(
    key: str,
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    point = _params(request, "point[")
    for k in ("college_id", "department_id", "program_id", "batch_id", "term_id", "scope"):
        if request.query_params.get(k):
            point[k] = request.query_params[k]
    return ok(await ChartService(db, principal, request).drilldown(key, point, page, size))


@router.post(
    "/analytics/charts/{key}/export",
    status_code=202,
    summary="Export chart rows (job analytics.chart_export)",
    dependencies=CORE,
)
async def chart_export(
    key: str,
    body: ChartExportIn,
    request: Request,
    principal: Principal = Depends(EXPORT),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.jobs import enqueue

    await ChartService(db, principal, request).spec(key)
    j = await enqueue(
        db, principal, "analytics.chart_export", {"key": key, **body.model_dump(mode="json")}, queue="reports"
    )
    return JSONResponse(status_code=202, content=ok({"job_id": str(j.id), "key": key}, message="Queued"))


@router.get(
    "/analytics/insights/{module}",
    summary="Insights tab charts for a list page (current filters)",
    response_model=Envelope[InsightsOut],
    dependencies=CORE,
)
async def insights(
    module: str, request: Request, principal: Principal = Depends(DASH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    filters = _params(request, "filter[")
    for k in ("college_id", "department_id", "program_id", "batch_id", "term_id", "period"):
        if request.query_params.get(k):
            filters[k] = request.query_params[k]
    svc = ChartService(db, principal, request)
    out = await svc.insights(module, filters)
    out["charts"] = [c.__dict__ for c in out["charts"]]
    return _vis(out, svc.visibility_meta(module))


# ---- KPI targets / alerts / public counters -------------------------------------------------------------------------------
@router.get(
    "/analytics/targets",
    summary="KPI targets, alert recipients and history",
    response_model=Envelope[KpiTargetsOut],
    dependencies=CORE,
)
async def get_targets(
    request: Request,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(TARGETS_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = KpiService(db, principal, request)
    history = {k: await svc.history(col, college_id, 60) for k, (col, _) in KPI_TARGET_COLUMNS.items()}
    return ok(
        {
            "targets": await svc.targets(college_id),
            "alert_recipients": await svc.recipients(),
            "college_id": college_id,
            "history": history,
        }
    )


@router.put(
    "/analytics/targets",
    summary="Set KPI targets / alert recipients",
    response_model=Envelope[KpiTargetsOut],
    dependencies=CORE,
)
async def put_targets(
    body: KpiTargetsIn, request: Request, principal: Principal = Depends(SETTINGS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(
        await KpiService(db, principal, request).put_targets(body.targets, body.alert_recipients, body.college_id)
    )


@router.post(
    "/analytics/targets/evaluate",
    status_code=202,
    summary="Evaluate KPI targets now (job analytics.kpi_evaluate)",
    dependencies=CORE,
)
async def evaluate_targets(
    request: Request, principal: Principal = Depends(SETTINGS), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, "analytics.kpi_evaluate", {}, queue="reports")
    return JSONResponse(status_code=202, content=ok({"job_id": str(j.id)}, message="Queued"))


@router.get(
    "/analytics/alerts", summary="KPI threshold alerts", response_model=Envelope[list[KpiAlertOut]], dependencies=CORE
)
async def kpi_alerts(
    request: Request,
    active: bool | None = None,
    principal: Principal = Depends(TARGETS_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await KpiService(db, principal, request).alerts(active))


@public_router.get(
    "/analytics/public-counters",
    summary="Website counters (tenant by institution slug)",
    response_model=Envelope[PublicCountersOut],
)
async def public_counters(
    request: Request, institution: str = Query(min_length=2, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.db.session import bind_tenant, set_tenant
    from app.services.inventory.vendor_service import tenant_by_slug

    iid = await tenant_by_slug(institution)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    if not await is_enabled(iid, "analytics.core"):
        raise APIError(
            403, ErrorCode.FEATURE_DISABLED, "Feature 'analytics.core' is not enabled", {"feature": "analytics.core"}
        )
    return ok(await KpiService(db, None, request, iid).public_counters())


# ---- read models -------------------------------------------------------------------------------------------------------------
@router.get(
    "/analytics/readmodels",
    summary="Read models: refreshed_at, stale, dirty",
    response_model=Envelope[list[RefreshStatusOut]],
    dependencies=CORE,
)
async def readmodels(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ReadModelService(db, principal, request).status())


@router.post(
    "/analytics/readmodels/refresh",
    status_code=202,
    summary="Refresh read models (job analytics.refresh_all)",
    dependencies=CORE,
)
async def refresh_readmodels(
    body: RefreshRequest, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    out = await ReadModelService(db, principal, request).request_refresh(body.views or None)
    return JSONResponse(status_code=202, content=ok(out, message="Queued"))


# ---- digests ---------------------------------------------------------------------------------------------------------------------
@router.get(
    "/analytics/digests",
    summary="Digest schedules",
    response_model=Envelope[list[DigestScheduleOut]],
    dependencies=CORE,
)
async def digests(
    request: Request, principal: Principal = Depends(SETTINGS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DigestService(db, principal, request).schedules())


@router.post(
    "/analytics/digests",
    status_code=201,
    summary="Create a digest schedule",
    response_model=Envelope[DigestScheduleOut],
    dependencies=CORE,
)
async def create_digest(
    body: DigestScheduleIn,
    request: Request,
    principal: Principal = Depends(SETTINGS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DigestService(db, principal, request).create(body.model_dump(mode="json")))


@router.delete(
    "/analytics/digests/{id}",
    summary="Delete a digest schedule",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def delete_digest(
    id: str, request: Request, principal: Principal = Depends(SETTINGS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await DigestService(db, principal, request).delete(id)
    return ok({"id": id, "deleted": True})


@router.post(
    "/analytics/digests/{id}/send-now",
    status_code=202,
    summary="Send a digest now (job analytics.digest)",
    dependencies=CORE,
)
async def send_digest(
    id: str, request: Request, principal: Principal = Depends(SETTINGS), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    await DigestService(db, principal, request).get(id)
    j = await enqueue(db, principal, "analytics.digest", {"digest_id": id}, queue="reports")
    return JSONResponse(status_code=202, content=ok({"job_id": str(j.id), "digest_id": id}, message="Queued"))


# ---- early warning -------------------------------------------------------------------------------------------------------------
@router.get(
    "/risk/cohort",
    summary="Risk cohort heat map (ScopeTabs Mine | Department | All)",
    response_model=Envelope[RiskCohortOut],
    dependencies=EW,
)
async def risk_cohort(
    request: Request,
    term_id: uuid.UUID | None = None,
    group_by: str = Query("department", pattern="^(department|program|batch|hostel|category)$"),
    level: str | None = Query(None, pattern="^(low|medium|high)$"),
    scope: str | None = None,
    principal: Principal = Depends(RISK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = RiskAnalyticsService(db, principal, request)
    return _vis(await svc.cohort(term_id, group_by, level, scope), svc.visibility_meta("mentoring"))


@router.get(
    "/risk/cohort/trend", summary="Risk levels across terms", response_model=Envelope[RiskTrendOut], dependencies=EW
)
async def risk_trend(
    request: Request, scope: str | None = None, principal: Principal = Depends(RISK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = RiskAnalyticsService(db, principal, request)
    return _vis(await svc.trend(scope), svc.visibility_meta("mentoring"))


@router.get(
    "/risk/students",
    summary="Flagged students (Phase 27 visibility; filters)",
    response_model=Envelope[list[RiskStudentOut]],
    dependencies=EW,
)
async def risk_students(
    request: Request,
    term_id: uuid.UUID | None = None,
    level: str | None = Query(None, pattern="^(low|medium|high)$"),
    department_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    factor: str | None = Query(None, pattern="^(attendance|cia|dues|standing|hostel|engagement)$"),
    unacknowledged: bool | None = None,
    no_intervention_days: int | None = Query(None, ge=1, le=365),
    scope: str | None = None,
    principal: Principal = Depends(RISK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = RiskAnalyticsService(db, principal, request)
    rows = await svc.student_list(
        term_id=term_id,
        level=level,
        department_id=department_id,
        program_id=program_id,
        batch_id=batch_id,
        factor=factor,
        unacknowledged=unacknowledged,
        no_intervention_days=no_intervention_days,
        scope=scope,
    )
    return _vis(rows, svc.visibility_meta("mentoring"))


@router.post(
    "/risk/students/{enrollment_id}/interventions",
    status_code=201,
    summary="Log an intervention (stored as a mentoring session)",
    response_model=Envelope[InterventionOut],
    dependencies=EW,
)
async def log_intervention(
    enrollment_id: uuid.UUID,
    body: InterventionIn,
    request: Request,
    principal: Principal = Depends(RISK_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RiskAnalyticsService(db, principal, request).log_intervention(
            enrollment_id, body.intervention_type, body.notes, body.follow_up_on
        )
    )


@router.get(
    "/risk/students/{enrollment_id}/interventions",
    summary="Interventions of a student",
    response_model=Envelope[list[InterventionOut]],
    dependencies=EW,
)
async def list_interventions(
    enrollment_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(RISK_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RiskAnalyticsService(db, principal, request).interventions(enrollment_id))


@router.get(
    "/risk/effectiveness",
    summary="Intervention effectiveness (level change within the term)",
    response_model=Envelope[RiskEffectivenessOut],
    dependencies=EW,
)
async def risk_effectiveness(
    request: Request,
    term_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(RISK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RiskAnalyticsService(db, principal, request).effectiveness(term_id, scope))


@router.post(
    "/risk/cohort/export",
    status_code=202,
    summary="Cohort / student list / IQAC export (job risk.cohort_export)",
    response_model=Envelope[JobQueued],
    dependencies=EW,
)
async def risk_export(
    body: RiskExportIn,
    request: Request,
    principal: Principal = Depends(RISK_EXPORT),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, "risk.cohort_export", body.model_dump(mode="json"), queue="reports")
    return JSONResponse(
        status_code=202, content=ok({"job_id": str(j.id), "detail": {"kind": body.kind}}, message="Queued")
    )
