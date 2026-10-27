"""Reports — Prompts/36 §36.8.

* ``/reports/catalogue|run|runs|favourites|registers|models|builder|saved|access-log`` {reports.core};
* ``/reports/schedules*`` {reports.scheduled}; ``/reports/statutory*`` {reports.statutory}.

Every report provider narrows rows to the caller's ``meta.visibility`` for the report's source module (scope params
narrowed silently), masks PII without ``<module>:view_pii``; statutory outputs are aggregates only. The Round 3–4
``/<module>/reports/{key}`` routes stay as aliases enqueuing ``report.run``.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.reports import (
    BuilderDefinition,
    BuilderPreviewOut,
    BuilderRunRequest,
    FavouritesOut,
    FavouriteToggle,
    RegisterOut,
    RegisterRequest,
    ReportAccessLogOut,
    ReportCatalogueOut,
    ReportModelOut,
    ReportRunListOut,
    ReportRunOut,
    ReportRunRequest,
    SavedReportIn,
    SavedReportOut,
    SavedReportShare,
    ScheduleHistoryOut,
    ScheduleIn,
    ScheduleOut,
    ScheduleRunNow,
    StatutoryDiffOut,
    StatutoryGenerateRequest,
    StatutoryListItem,
    StatutoryOut,
    StatutoryReviewAction,
)
from app.services.reports.builder_service import BuilderService
from app.services.reports.report_service import ReportService
from app.services.reports.schedule_service import ScheduleService
from app.services.reports.statutory_service import StatutoryService
from app.utils.response import ok

router = APIRouter(tags=["reports"])

VIEW = any_permission_required(("reports", "view"), ("reports", "run"), ("reports", "manage"))
RUN = any_permission_required(("reports", "run"), ("reports", "manage"))
MANAGE = any_permission_required(("reports", "manage"), ("audit_logs", "view_all"))
SCHEDULE = any_permission_required(("reports", "schedule"), ("reports", "manage"))
STATUTORY = any_permission_required(("reports", "statutory"), ("reports", "manage"), ("reports", "view_all"))

CORE = [feature_required("reports.core")]
SCHED = [feature_required("reports.scheduled")]
STAT = [feature_required("reports.statutory")]


def _queued(out: Any, message: str = "Queued") -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(out.model_dump(mode="json"), message=message))


# ---- catalogue / runs ------------------------------------------------------------------------------------------------------
@router.get(
    "/reports/catalogue",
    summary="Report catalogue for me (+ favourites, last run)",
    response_model=Envelope[list[ReportCatalogueOut]],
    dependencies=CORE,
)
async def catalogue(
    request: Request,
    module: str | None = None,
    category: str | None = None,
    q: str | None = Query(None, max_length=100),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ReportService(db, principal, request).catalogue(module, category, q))


@router.post(
    "/reports/run",
    summary="Run a report (inline preview, else a report.run job)",
    response_model=Envelope[ReportRunOut],
    dependencies=CORE,
)
async def run(
    body: ReportRunRequest, request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> Any:
    out = await ReportService(db, principal, request).run(body)
    if out.job_id:
        return _queued(out, "Report queued")
    res = ok(out)
    res["meta"]["visibility"] = {"scopes": [out.scope] if out.scope else []}
    return res


@router.get(
    "/reports/runs",
    summary="Report runs (ScopeTabs Mine | All)",
    response_model=Envelope[ReportRunListOut],
    dependencies=CORE,
)
async def runs(
    request: Request,
    scope: str = Query("mine", pattern="^(mine|all)$"),
    key: str | None = None,
    status: str | None = None,
    requested_by: uuid.UUID | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ReportService(db, principal, request)
    res = ok(
        await svc.runs(
            mine=scope == "mine",
            key=key,
            status=status,
            requested_by=requested_by,
            date_from=date_from,
            date_to=date_to,
            page=page,
            size=size,
        )
    )
    res["meta"]["visibility"] = {
        "self": False,
        "scopes": ["mine", "all"] if svc.sees_all_runs() else ["mine"],
        "default": "mine",
    }
    return res


@router.get("/reports/runs/{job_id}", summary="One run", response_model=Envelope[ReportRunOut], dependencies=CORE)
async def get_run(
    job_id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ReportService(db, principal, request).get_run(job_id))


@router.post(
    "/reports/runs/{job_id}/cancel", summary="Cancel a run", response_model=Envelope[ReportRunOut], dependencies=CORE
)
async def cancel_run(
    job_id: uuid.UUID, request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ReportService(db, principal, request).cancel(job_id), message="Cancellation requested")


@router.get(
    "/reports/runs/{job_id}/download",
    summary="Download the run's file (signed URL redirect; 410 after retention)",
    response_model=None,
    dependencies=CORE,
)
async def download_run(
    job_id: uuid.UUID,
    request: Request,
    redirect: bool = True,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> Any:
    url = await ReportService(db, principal, request).download(job_id)
    if redirect:
        return RedirectResponse(url, status_code=307)
    return ok({"url": url})


# ---- favourites -----------------------------------------------------------------------------------------------------------
@router.get(
    "/reports/favourites",
    summary="My favourites + recent runs",
    response_model=Envelope[FavouritesOut],
    dependencies=CORE,
)
async def favourites(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ReportService(db, principal, request).favourites())


@router.post(
    "/reports/favourites/toggle",
    summary="Toggle a favourite",
    response_model=Envelope[FavouritesOut],
    dependencies=CORE,
)
async def toggle_favourite(
    body: FavouriteToggle, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ReportService(db, principal, request).toggle_favourite(body.key))


# ---- registers ----------------------------------------------------------------------------------------------------------------
@router.get(
    "/reports/registers", summary="Print-ready registers", response_model=Envelope[list[RegisterOut]], dependencies=CORE
)
async def registers(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ReportService(db, principal, request).registers())


@router.post(
    "/reports/registers/run",
    summary="Generate a register (job)",
    response_model=Envelope[ReportRunOut],
    dependencies=CORE,
)
async def run_register(
    body: RegisterRequest, request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return _queued(await ReportService(db, principal, request).run_register(body), "Register queued")


# ---- builder --------------------------------------------------------------------------------------------------------------------
@router.get(
    "/reports/models", summary="Builder whitelist", response_model=Envelope[list[ReportModelOut]], dependencies=CORE
)
async def models(
    request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BuilderService(db, principal, request).models())


@router.get(
    "/reports/models/{key}", summary="One builder model", response_model=Envelope[ReportModelOut], dependencies=CORE
)
async def model(
    key: str, request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BuilderService(db, principal, request).model_out(key))


@router.post(
    "/reports/builder/preview",
    summary="Ad-hoc preview (≤ 200 rows)",
    response_model=Envelope[BuilderPreviewOut],
    dependencies=CORE,
)
async def builder_preview(
    body: BuilderDefinition, request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BuilderService(db, principal, request).preview(body))


@router.post(
    "/reports/builder/run", summary="Ad-hoc run (job)", response_model=Envelope[ReportRunOut], dependencies=CORE
)
async def builder_run(
    body: BuilderRunRequest, request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return _queued(await BuilderService(db, principal, request).run(body.definition, body.format))


@router.get(
    "/reports/saved",
    summary="Saved reports (own + shared)",
    response_model=Envelope[list[SavedReportOut]],
    dependencies=CORE,
)
async def saved_list(
    request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BuilderService(db, principal, request).saved_list())


@router.post(
    "/reports/saved",
    status_code=201,
    summary="Save a builder report",
    response_model=Envelope[SavedReportOut],
    dependencies=CORE,
)
async def saved_create(
    body: SavedReportIn, request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BuilderService(db, principal, request).create_saved(body), message="Saved")


@router.get(
    "/reports/saved/{sid}", summary="One saved report", response_model=Envelope[SavedReportOut], dependencies=CORE
)
async def saved_get(
    sid: str, request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok((await BuilderService(db, principal, request).saved(sid))[1])


@router.put(
    "/reports/saved/{sid}", summary="Update a saved report", response_model=Envelope[SavedReportOut], dependencies=CORE
)
async def saved_update(
    sid: str,
    body: SavedReportIn,
    request: Request,
    principal: Principal = Depends(RUN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BuilderService(db, principal, request).update_saved(sid, body))


@router.delete(
    "/reports/saved/{sid}", summary="Delete a saved report", response_model=Envelope[dict[str, Any]], dependencies=CORE
)
async def saved_delete(
    sid: str, request: Request, principal: Principal = Depends(RUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await BuilderService(db, principal, request).delete_saved(sid)
    return ok({"id": sid}, message="Deleted")


@router.post(
    "/reports/saved/{sid}/share",
    summary="Share with roles (reports:manage)",
    response_model=Envelope[SavedReportOut],
    dependencies=CORE,
)
async def saved_share(
    sid: str,
    body: SavedReportShare,
    request: Request,
    principal: Principal = Depends(RUN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BuilderService(db, principal, request).share(sid, body.roles))


@router.post(
    "/reports/saved/{sid}/run",
    summary="Run a saved report (job)",
    response_model=Envelope[ReportRunOut],
    dependencies=CORE,
)
async def saved_run(
    sid: str,
    request: Request,
    format: str = Query("xlsx", pattern="^(xlsx|csv|pdf|json)$"),  # noqa: A002 - query name per Prompts/36 §36.8
    principal: Principal = Depends(RUN),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return _queued(await BuilderService(db, principal, request).run_saved(sid, format))


# ---- statutory --------------------------------------------------------------------------------------------------------------------
@router.get(
    "/reports/statutory",
    summary="Statutory reports (status, due dates)",
    response_model=Envelope[list[StatutoryListItem]],
    dependencies=STAT,
)
async def statutory_list(
    request: Request, principal: Principal = Depends(STATUTORY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StatutoryService(db, principal, request).codes())


@router.get(
    "/reports/statutory/{code}",
    summary="One statutory generation",
    response_model=Envelope[StatutoryOut],
    dependencies=STAT,
)
async def statutory_get(
    code: str,
    request: Request,
    period: str = Query(..., min_length=4, max_length=20),
    discipline: str | None = None,
    principal: Principal = Depends(STATUTORY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StatutoryService(db, principal, request).get(code, period, discipline))


@router.post(
    "/reports/statutory/{code}/generate",
    summary="Generate (job)",
    response_model=Envelope[ReportRunOut],
    dependencies=STAT,
)
async def statutory_generate(
    code: str,
    body: StatutoryGenerateRequest,
    request: Request,
    principal: Principal = Depends(STATUTORY),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return _queued(await StatutoryService(db, principal, request).request_generate(code, body), "Generation queued")


@router.get(
    "/reports/statutory/{code}/{period}/diff",
    summary="Diff vs a previous period",
    response_model=Envelope[StatutoryDiffOut],
    dependencies=STAT,
)
async def statutory_diff(
    code: str,
    period: str,
    request: Request,
    vs: str | None = None,
    discipline: str | None = None,
    principal: Principal = Depends(STATUTORY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StatutoryService(db, principal, request).diff(code, period, vs, discipline))


@router.post(
    "/reports/statutory/{code}/{period}/review",
    summary="request_review | sign_off | reopen",
    response_model=Envelope[StatutoryOut],
    dependencies=STAT,
)
async def statutory_review(
    code: str,
    period: str,
    body: StatutoryReviewAction,
    request: Request,
    discipline: str | None = None,
    principal: Principal = Depends(STATUTORY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StatutoryService(db, principal, request).review(code, period, body, discipline))


@router.post(
    "/reports/statutory/{code}/{period}/pack",
    summary="Export pack (zip job)",
    response_model=Envelope[ReportRunOut],
    dependencies=STAT,
)
async def statutory_pack(
    code: str,
    period: str,
    request: Request,
    discipline: str | None = None,
    principal: Principal = Depends(STATUTORY),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return _queued(await StatutoryService(db, principal, request).request_pack(code, period, discipline), "Pack queued")


# ---- schedules ----------------------------------------------------------------------------------------------------------------------
@router.get("/reports/schedules", summary="Schedules", response_model=Envelope[list[ScheduleOut]], dependencies=SCHED)
async def schedules(
    request: Request, principal: Principal = Depends(SCHEDULE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScheduleService(db, principal, request).schedules())


@router.post(
    "/reports/schedules",
    status_code=201,
    summary="Create a schedule",
    response_model=Envelope[ScheduleOut],
    dependencies=SCHED,
)
async def schedule_create(
    body: ScheduleIn, request: Request, principal: Principal = Depends(SCHEDULE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScheduleService(db, principal, request).create(body), message="Scheduled")


@router.get(
    "/reports/schedules/{sid}", summary="One schedule", response_model=Envelope[ScheduleOut], dependencies=SCHED
)
async def schedule_get(
    sid: str, request: Request, principal: Principal = Depends(SCHEDULE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScheduleService(db, principal, request).get(sid))


@router.put(
    "/reports/schedules/{sid}", summary="Update a schedule", response_model=Envelope[ScheduleOut], dependencies=SCHED
)
async def schedule_update(
    sid: str,
    body: ScheduleIn,
    request: Request,
    principal: Principal = Depends(SCHEDULE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ScheduleService(db, principal, request).update(sid, body))


@router.delete(
    "/reports/schedules/{sid}", summary="Delete a schedule", response_model=Envelope[dict[str, Any]], dependencies=SCHED
)
async def schedule_delete(
    sid: str, request: Request, principal: Principal = Depends(SCHEDULE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await ScheduleService(db, principal, request).delete(sid)
    return ok({"id": sid}, message="Deleted")


@router.post(
    "/reports/schedules/{sid}/run-now",
    summary="Run now (one job per recipient)",
    response_model=Envelope[ScheduleRunNow],
    dependencies=SCHED,
)
async def schedule_run_now(
    sid: str, request: Request, principal: Principal = Depends(SCHEDULE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return _queued(await ScheduleService(db, principal, request).run_now(sid))


@router.post(
    "/reports/schedules/{sid}/pause", summary="Pause", response_model=Envelope[ScheduleOut], dependencies=SCHED
)
async def schedule_pause(
    sid: str, request: Request, principal: Principal = Depends(SCHEDULE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScheduleService(db, principal, request).set_active(sid, False))


@router.post(
    "/reports/schedules/{sid}/resume", summary="Resume", response_model=Envelope[ScheduleOut], dependencies=SCHED
)
async def schedule_resume(
    sid: str, request: Request, principal: Principal = Depends(SCHEDULE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScheduleService(db, principal, request).set_active(sid, True))


@router.get(
    "/reports/schedules/{sid}/history",
    summary="Run history",
    response_model=Envelope[list[ScheduleHistoryOut]],
    dependencies=SCHED,
)
async def schedule_history(
    sid: str, request: Request, principal: Principal = Depends(SCHEDULE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScheduleService(db, principal, request).history(sid))


# ---- access log -----------------------------------------------------------------------------------------------------------------------
@router.get(
    "/reports/access-log",
    summary="Who ran / downloaded which report",
    response_model=Envelope[list[ReportAccessLogOut]],
    dependencies=CORE,
)
async def access_log(
    request: Request,
    key: str | None = None,
    user_id: uuid.UUID | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ReportService(db, principal, request).access_log(key, user_id, date_from, date_to))


__all__ = ["router"]
