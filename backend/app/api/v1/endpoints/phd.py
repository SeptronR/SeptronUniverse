"""PhD & research-scholar management — Prompts/31 §31.8: scholars (ScopeTabs Own (guide) | Department | All, guide
load) {phd.core}, scholar portal {phd.scholar_portal}, coursework {phd.coursework}, doctoral committee
{phd.dc_meetings}, progress reports {phd.progress_reports}, fellowships {phd.fellowships}, requests
{phd.extensions_guide_change}, thesis & plagiarism {phd.thesis_plagiarism}, examiners {phd.external_examiners}, viva
{phd.viva}, award {phd.core}, ETD {phd.etd_upload}, stats / reports. The external-examiner token pages and the
plagiarism adapter callback are public (``app/api/v1/public.py``). ``/me`` and fixed-path routes are declared before
the ``/{id}`` routes of the same prefix.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.phd import (
    CancellationDecision,
    ComplianceRow,
    ContingencyClaim,
    CourseworkExemption,
    CourseworkPlan,
    CourseworkStatusOut,
    DcConstitute,
    DcMeetingApprove,
    DcMeetingCreate,
    DcMeetingMinutes,
    DcMeetingOut,
    DcOut,
    DcReview,
    DisbursementHold,
    DisbursementPay,
    DisbursementRun,
    DisbursementRunResult,
    Discontinue,
    EtdEmbargo,
    EtdOut,
    EtdUploadRequest,
    ExaminerInvite,
    ExaminerOut,
    ExaminerPanelPropose,
    ExaminerRemuneration,
    ExaminerReplace,
    ExaminerReportUpload,
    ExaminerResponse,
    ExaminerTokenView,
    FellowshipCreate,
    FellowshipOut,
    FellowshipUpdate,
    GuideAllocate,
    GuideLoadOut,
    GuideNoc,
    GuideReview,
    PanelDecision,
    PhdAwardOut,
    PhdAwardRequest,
    PhdDisbursementOut,
    PhdJobQueued,
    PhdStats,
    PlagiarismResult,
    ProgressPeriod,
    ProgressReportOut,
    ProgressReportSubmit,
    RecommendationsOut,
    RequestDecision,
    Scholar360,
    ScholarCreate,
    ScholarOut,
    ScholarPortalDashboard,
    ScholarRequestCreate,
    ScholarRequestOut,
    ScholarUpdate,
    ThesisOut,
    ThesisReject,
    ThesisSubmit,
    TimelineEntry,
    VivaOut,
    VivaResultIn,
    VivaSchedule,
    VivaUpdate,
)
from app.services.phd.award_service import AwardService
from app.services.phd.common import PhdBase
from app.services.phd.coursework_service import CourseworkService
from app.services.phd.dc_service import DcService
from app.services.phd.etd_service import EtdService
from app.services.phd.examiner_service import ExaminerService
from app.services.phd.fellowship_service import FellowshipService
from app.services.phd.progress_service import ProgressService
from app.services.phd.request_service import RequestService
from app.services.phd.scholar_service import ScholarService
from app.services.phd.stats_service import StatsService
from app.services.phd.thesis_service import ThesisService
from app.services.phd.viva_service import VivaService
from app.utils.response import PaginationMeta, VisibilityMeta, ok

router = APIRouter(tags=["phd"])
public_router = APIRouter(tags=["phd"])

P = "phd"
_READ = ((P, "view"), (P, "view_all"), (P, "manage"), (P, "guide"), (P, "dc"), (P, "self"))
VIEW = any_permission_required(*_READ)
STAFF = any_permission_required((P, "view_all"), (P, "manage"), (P, "guide"), (P, "dc"))
MANAGE = any_permission_required((P, "manage"))
GUIDE_W = any_permission_required((P, "guide"), (P, "dc"), (P, "manage"))
SELF_W = any_permission_required((P, "self"), (P, "guide"), (P, "manage"))
APPROVE = any_permission_required((P, "approve"), (P, "manage"))
FELLOW = any_permission_required(
    (P, "fellowship"), (P, "manage"), (P, "self"), (P, "view_all"), ("accounting", "view_all"), ("accounting", "manage")
)
FELLOW_W = any_permission_required((P, "fellowship"), (P, "manage"), ("accounting", "manage"), ("accounting", "post"))
EXAMINE = any_permission_required((P, "examine"), (P, "manage"), (P, "approve"))
REMUN = any_permission_required((P, "examine"), (P, "manage"), ("accounting", "post"))
ETD = any_permission_required((P, "etd"), (P, "manage"), (P, "self"), (P, "view_all"), (P, "guide"))
ETD_W = any_permission_required((P, "etd"), (P, "manage"))
EMBARGO = any_permission_required((P, "etd"), (P, "manage"), (P, "self"), (P, "guide"))
STATS = any_permission_required((P, "view_all"), (P, "manage"), ("reports", "statutory"), ("reports", "export"))
SELF = any_permission_required((P, "self"))

CORE = [feature_required("phd.core")]
PORTAL = [feature_required("phd.scholar_portal")]
CW = [feature_required("phd.coursework")]
DC = [feature_required("phd.dc_meetings")]
PROG = [feature_required("phd.progress_reports")]
FELL = [feature_required("phd.fellowships")]
REQ = [feature_required("phd.extensions_guide_change")]
THESIS = [feature_required("phd.thesis_plagiarism")]
EXAM = [feature_required("phd.external_examiners")]
VIVA = [feature_required("phd.viva")]
ETD_F = [feature_required("phd.etd_upload")]

SCOPE = Query(None, pattern="^(self|mine|own|department|faculty|college|all)$")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(
        status_code=202, content=ok(PhdJobQueued(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


def _vis(svc: PhdBase) -> VisibilityMeta:
    v = svc.visibility()
    return VisibilityMeta(self=v["self"], scopes=v["scopes"], default=v["default"])


def _page(page: int, per_page: int, total: int) -> PaginationMeta:
    return PaginationMeta(page=page, page_size=per_page, total=total, total_pages=max(1, -(-total // per_page)))


# ---- scholar portal -----------------------------------------------------------------------------------------------------
@router.get("/phd/me", summary="My scholar record (360)", response_model=Envelope[Scholar360], dependencies=PORTAL)
async def me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScholarService(db, principal, request).me())


@router.get(
    "/phd/me/dashboard",
    summary="Scholar dashboard (status, deadlines, duration meter)",
    response_model=Envelope[ScholarPortalDashboard],
    dependencies=PORTAL,
)
async def me_dashboard(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScholarService(db, principal, request).dashboard())


# ---- scholars -----------------------------------------------------------------------------------------------------------
@router.get(
    "/phd/scholars",
    summary="Scholars (ScopeTabs Own | Department | All; scholars use /phd/me)",
    response_model=Envelope[list[ScholarOut]],
    dependencies=CORE,
)
async def scholars(
    request: Request,
    status: str | None = Query(None, max_length=30),
    guide_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    scope: str | None = SCOPE,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ScholarService(db, principal, request)
    items, total = await svc.query(
        status=status,
        guide_id=guide_id,
        department_id=department_id,
        q=q,
        scope=scope,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return ok(items, pagination=_page(page, per_page, total), visibility=_vis(svc))


@router.post(
    "/phd/scholars",
    status_code=201,
    summary="Create a scholar (guide load check → 409 GUIDE_LOAD_EXCEEDED)",
    response_model=Envelope[ScholarOut],
    dependencies=CORE,
)
async def create_scholar(
    body: ScholarCreate, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScholarService(db, principal, request).create(body), message="Created")


@router.get(
    "/phd/guides/load", summary="Guide load by cadre", response_model=Envelope[list[GuideLoadOut]], dependencies=CORE
)
async def guide_load(
    request: Request,
    department_id: uuid.UUID | None = None,
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ScholarService(db, principal, request).guide_loads(department_id))


@router.get("/phd/scholars/{sid}", summary="Scholar 360", response_model=Envelope[Scholar360], dependencies=CORE)
async def scholar(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScholarService(db, principal, request).get(sid))


@router.put("/phd/scholars/{sid}", summary="Update a scholar", response_model=Envelope[ScholarOut], dependencies=CORE)
async def update_scholar(
    sid: uuid.UUID,
    body: ScholarUpdate,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ScholarService(db, principal, request).update(sid, body))


@router.post(
    "/phd/scholars/{sid}/guide",
    summary="Allocate / reallocate the guide (load check under FOR UPDATE)",
    response_model=Envelope[ScholarOut],
    dependencies=CORE,
)
async def allocate_guide(
    sid: uuid.UUID,
    body: GuideAllocate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ScholarService(db, principal, request).allocate_guide(sid, body))


@router.post(
    "/phd/scholars/{sid}/discontinue", summary="Discontinue", response_model=Envelope[ScholarOut], dependencies=CORE
)
async def discontinue(
    sid: uuid.UUID,
    body: Discontinue,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ScholarService(db, principal, request).discontinue(sid, body))


@router.get(
    "/phd/scholars/{sid}/timeline",
    summary="Status timeline",
    response_model=Envelope[list[TimelineEntry]],
    dependencies=CORE,
)
async def timeline(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScholarService(db, principal, request).timeline_of(sid))


# ---- coursework ---------------------------------------------------------------------------------------------------------
@router.get(
    "/phd/scholars/{sid}/coursework",
    summary="Coursework status (credits earned / methodology from results)",
    response_model=Envelope[CourseworkStatusOut],
    dependencies=CW,
)
async def coursework(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CourseworkService(db, principal, request).status(sid))


@router.put(
    "/phd/scholars/{sid}/coursework",
    summary="Plan coursework (research methodology mandatory)",
    response_model=Envelope[CourseworkStatusOut],
    dependencies=CW,
)
async def plan_coursework(
    sid: uuid.UUID,
    body: CourseworkPlan,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CourseworkService(db, principal, request).plan(sid, body))


@router.post(
    "/phd/scholars/{sid}/coursework/exemption",
    status_code=201,
    summary="Request a coursework exemption (phd.request)",
    response_model=Envelope[ScholarRequestOut],
    dependencies=CW,
)
async def coursework_exemption(
    sid: uuid.UUID,
    body: CourseworkExemption,
    request: Request,
    principal: Principal = Depends(SELF_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CourseworkService(db, principal, request).request_exemption(sid, body), message="Requested")


@router.post(
    "/phd/scholars/{sid}/coursework/complete",
    summary="Complete coursework → registered (registration_date, max_duration_end)",
    response_model=Envelope[CourseworkStatusOut],
    dependencies=CW,
)
async def coursework_complete(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(GUIDE_W), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CourseworkService(db, principal, request).complete(sid))


# ---- doctoral committee -------------------------------------------------------------------------------------------------
@router.get(
    "/phd/scholars/{sid}/dc", summary="Doctoral committee", response_model=Envelope[DcOut | None], dependencies=DC
)
async def dc(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DcService(db, principal, request).get(sid))


@router.post(
    "/phd/scholars/{sid}/dc",
    status_code=201,
    summary="Constitute the DC (guide convenor, ≥ 1 external)",
    response_model=Envelope[DcOut],
    dependencies=DC,
)
async def constitute_dc(
    sid: uuid.UUID,
    body: DcConstitute,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DcService(db, principal, request).constitute(sid, body), message="Constituted")


@router.put(
    "/phd/scholars/{sid}/dc/members", summary="Reconstitute DC members", response_model=Envelope[DcOut], dependencies=DC
)
async def dc_members(
    sid: uuid.UUID,
    body: DcConstitute,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DcService(db, principal, request).constitute(sid, body, replace=True))


@router.get(
    "/phd/scholars/{sid}/dc-meetings",
    summary="DC meetings",
    response_model=Envelope[list[DcMeetingOut]],
    dependencies=DC,
)
async def dc_meetings(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DcService(db, principal, request).meetings(sid))


@router.post(
    "/phd/scholars/{sid}/dc-meetings",
    status_code=201,
    summary="Schedule a DC meeting (409 DUPLICATE_MEETING)",
    response_model=Envelope[DcMeetingOut],
    dependencies=DC,
)
async def schedule_meeting(
    sid: uuid.UUID,
    body: DcMeetingCreate,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DcService(db, principal, request).schedule(sid, body), message="Scheduled")


@router.put(
    "/phd/dc-meetings/{mid}/minutes",
    summary="Minutes, attendance and recommendations",
    response_model=Envelope[DcMeetingOut],
    dependencies=DC,
)
async def meeting_minutes(
    mid: uuid.UUID,
    body: DcMeetingMinutes,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DcService(db, principal, request).minutes(mid, body))


@router.post(
    "/phd/dc-meetings/{mid}/approve",
    summary="Convenor approves the minutes",
    response_model=Envelope[DcMeetingOut],
    dependencies=DC,
)
async def meeting_approve(
    mid: uuid.UUID,
    body: DcMeetingApprove,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DcService(db, principal, request).approve(mid, body))


# ---- progress reports ---------------------------------------------------------------------------------------------------
@router.get(
    "/phd/progress-reports/compliance",
    summary="Report compliance (due / submitted / overdue, unsatisfactory streak)",
    response_model=Envelope[list[ComplianceRow]],
    dependencies=PROG,
)
async def compliance(
    request: Request,
    department_id: uuid.UUID | None = None,
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgressService(db, principal, request).compliance(department_id))


@router.get(
    "/phd/scholars/{sid}/progress-reports",
    summary="Progress reports",
    response_model=Envelope[list[ProgressReportOut]],
    dependencies=PROG,
)
async def progress_reports(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProgressService(db, principal, request).reports(sid))


@router.get(
    "/phd/scholars/{sid}/progress-periods",
    summary="Half-yearly periods with due dates",
    response_model=Envelope[list[ProgressPeriod]],
    dependencies=PROG,
)
async def progress_periods(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = ProgressService(db, principal, request)
    return ok(await svc.periods(await svc.scholar(sid)))


@router.post(
    "/phd/scholars/{sid}/progress-reports",
    status_code=201,
    summary="Submit a progress report (scholar)",
    response_model=Envelope[ProgressReportOut],
    dependencies=PROG,
)
async def submit_report(
    sid: uuid.UUID,
    body: ProgressReportSubmit,
    request: Request,
    principal: Principal = Depends(SELF_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgressService(db, principal, request).submit(sid, body), message="Submitted")


@router.post(
    "/phd/progress-reports/{rid}/guide-review",
    summary="Guide review",
    response_model=Envelope[ProgressReportOut],
    dependencies=PROG,
)
async def guide_review(
    rid: uuid.UUID,
    body: GuideReview,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgressService(db, principal, request).guide_review(rid, body))


@router.post(
    "/phd/progress-reports/{rid}/dc-review",
    summary="DC rating (two consecutive unsatisfactory → cancellation review)",
    response_model=Envelope[ProgressReportOut],
    dependencies=PROG,
)
async def dc_review(
    rid: uuid.UUID,
    body: DcReview,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgressService(db, principal, request).dc_review(rid, body))


@router.post(
    "/phd/requests/{rid}/cancellation-decision",
    summary="Cancellation review decision (warning | discontinue)",
    response_model=Envelope[ScholarRequestOut],
    dependencies=PROG,
)
async def cancellation_decision(
    rid: uuid.UUID,
    body: CancellationDecision,
    request: Request,
    principal: Principal = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgressService(db, principal, request).decide_cancellation(rid, body))


# ---- fellowships --------------------------------------------------------------------------------------------------------
@router.get(
    "/phd/fellowships/me",
    summary="My disbursements",
    response_model=Envelope[list[PhdDisbursementOut]],
    dependencies=FELL,
)
async def fellowships_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FellowshipService(db, principal, request).me())


@router.post(
    "/phd/fellowships/run",
    status_code=202,
    summary="Monthly disbursement run (job; ?inline=true runs at once)",
    response_model=Envelope[DisbursementRunResult],
    dependencies=FELL,
)
async def fellowship_run(
    body: DisbursementRun,
    request: Request,
    inline: bool = False,
    principal: Principal = Depends(FELLOW_W),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if inline:
        return ok(await FellowshipService(db, principal, request).run(body.month), message="Run complete")
    return await _job(db, principal, "phd.fellowship_run", {"month": body.month.isoformat()})


@router.get(
    "/phd/scholars/{sid}/fellowship",
    summary="Fellowships of a scholar",
    response_model=Envelope[list[FellowshipOut]],
    dependencies=FELL,
)
async def scholar_fellowships(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(FELLOW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FellowshipService(db, principal, request).for_scholar(sid))


@router.post(
    "/phd/scholars/{sid}/fellowship",
    status_code=201,
    summary="Create a fellowship (defaults from phd.rules)",
    response_model=Envelope[FellowshipOut],
    dependencies=FELL,
)
async def create_fellowship(
    sid: uuid.UUID,
    body: FellowshipCreate,
    request: Request,
    principal: Principal = Depends(FELLOW_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FellowshipService(db, principal, request).create(sid, body), message="Created")


@router.get(
    "/phd/scholars/{sid}/fellowship/statement",
    summary="Agency statement (UGC / CSIR)",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=FELL,
)
async def fellowship_statement(
    sid: uuid.UUID,
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    principal: Principal = Depends(FELLOW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FellowshipService(db, principal, request).statement(sid, year))


@router.put(
    "/phd/fellowships/{fid}", summary="Update a fellowship", response_model=Envelope[FellowshipOut], dependencies=FELL
)
async def update_fellowship(
    fid: uuid.UUID,
    body: FellowshipUpdate,
    request: Request,
    principal: Principal = Depends(FELLOW_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FellowshipService(db, principal, request).update(fid, body))


@router.get(
    "/phd/disbursements",
    summary="Disbursements (month / status)",
    response_model=Envelope[list[PhdDisbursementOut]],
    dependencies=FELL,
)
async def disbursements(
    request: Request,
    month: date | None = None,
    status: str | None = Query(None, pattern="^(pending|approved|paid|held)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(200, ge=1, le=1000),
    principal: Principal = Depends(FELLOW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    items, total = await FellowshipService(db, principal, request).disbursements(
        month=month, status=status, limit=per_page, offset=(page - 1) * per_page
    )
    return ok(items, pagination=_page(page, per_page, total))


@router.post(
    "/phd/disbursements/pay",
    summary="Payment batch (payout / payroll) for approved rows",
    response_model=Envelope[list[PhdDisbursementOut]],
    dependencies=FELL,
)
async def pay_disbursements(
    body: DisbursementPay,
    request: Request,
    principal: Principal = Depends(FELLOW_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FellowshipService(db, principal, request).pay(body))


@router.post(
    "/phd/disbursements/{did}/approve",
    summary="Approve",
    response_model=Envelope[PhdDisbursementOut],
    dependencies=FELL,
)
async def approve_disbursement(
    did: uuid.UUID, request: Request, principal: Principal = Depends(FELLOW_W), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FellowshipService(db, principal, request).approve(did))


@router.post(
    "/phd/disbursements/{did}/hold", summary="Hold", response_model=Envelope[PhdDisbursementOut], dependencies=FELL
)
async def hold_disbursement(
    did: uuid.UUID,
    body: DisbursementHold,
    request: Request,
    principal: Principal = Depends(FELLOW_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FellowshipService(db, principal, request).hold(did, body))


@router.post(
    "/phd/disbursements/{did}/release",
    summary="Release a hold (arrears on the next run)",
    response_model=Envelope[PhdDisbursementOut],
    dependencies=FELL,
)
async def release_disbursement(
    did: uuid.UUID, request: Request, principal: Principal = Depends(FELLOW_W), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FellowshipService(db, principal, request).release(did))


@router.post(
    "/phd/disbursements/{did}/contingency",
    status_code=201,
    summary="Contingency claim with bills",
    response_model=Envelope[PhdDisbursementOut],
    dependencies=FELL,
)
async def contingency(
    did: uuid.UUID,
    body: ContingencyClaim,
    request: Request,
    principal: Principal = Depends(FELLOW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FellowshipService(db, principal, request).contingency(did, body), message="Claimed")


# ---- requests -----------------------------------------------------------------------------------------------------------
@router.get(
    "/phd/requests", summary="Requests queue", response_model=Envelope[list[ScholarRequestOut]], dependencies=REQ
)
async def requests_queue(
    request: Request,
    type: str | None = Query(None, max_length=30),  # noqa: A002 - query name per Prompts/31 §31.8
    status: str | None = Query(None, max_length=20),
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    items, total = await RequestService(db, principal, request).query(
        request_type=type, status=status, limit=per_page, offset=(page - 1) * per_page
    )
    return ok(items, pagination=_page(page, per_page, total))


@router.get(
    "/phd/scholars/{sid}/requests",
    summary="Requests of a scholar",
    response_model=Envelope[list[ScholarRequestOut]],
    dependencies=REQ,
)
async def scholar_requests(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).for_scholar(sid))


@router.post(
    "/phd/scholars/{sid}/requests",
    status_code=201,
    summary="Raise a request (extension / change of guide / mode change / leave / exemption)",
    response_model=Envelope[ScholarRequestOut],
    dependencies=REQ,
)
async def raise_request(
    sid: uuid.UUID,
    body: ScholarRequestCreate,
    request: Request,
    principal: Principal = Depends(SELF_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).create(sid, body), message="Requested")


@router.get("/phd/requests/{rid}", summary="Request", response_model=Envelope[ScholarRequestOut], dependencies=REQ)
async def get_request(
    rid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).get(rid))


@router.post(
    "/phd/requests/{rid}/guide-noc",
    summary="Old guide's NOC (change of guide)",
    response_model=Envelope[ScholarRequestOut],
    dependencies=REQ,
)
async def guide_noc(
    rid: uuid.UUID,
    body: GuideNoc,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).guide_noc(rid, body))


@router.post(
    "/phd/requests/{rid}/decide",
    summary="Research cell desk decision (closes the workflow)",
    response_model=Envelope[ScholarRequestOut],
    dependencies=REQ,
)
async def decide_request(
    rid: uuid.UUID,
    body: RequestDecision,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).decide_desk(rid, body.approve, body.remarks))


# ---- thesis -------------------------------------------------------------------------------------------------------------
@router.get(
    "/phd/thesis",
    summary="Plagiarism / DC approval queue",
    response_model=Envelope[list[ThesisOut]],
    dependencies=THESIS,
)
async def thesis_queue(
    request: Request,
    status: str | None = Query(None, pattern="^(submitted|plagiarism_checked|dc_approved|rejected)$"),
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ThesisService(db, principal, request).queue(status))


@router.get(
    "/phd/scholars/{sid}/thesis",
    summary="Submissions of a scholar",
    response_model=Envelope[list[ThesisOut]],
    dependencies=THESIS,
)
async def scholar_thesis(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ThesisService(db, principal, request).for_scholar(sid))


@router.post(
    "/phd/scholars/{sid}/thesis",
    status_code=201,
    summary="Submit pre-synopsis / synopsis / thesis / revised thesis (AI declaration mandatory)",
    response_model=Envelope[ThesisOut],
    dependencies=THESIS,
)
async def submit_thesis(
    sid: uuid.UUID,
    body: ThesisSubmit,
    request: Request,
    principal: Principal = Depends(SELF_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ThesisService(db, principal, request).submit(sid, body), message="Submitted")


@router.get("/phd/thesis/{tid}", summary="Submission", response_model=Envelope[ThesisOut], dependencies=THESIS)
async def get_thesis(
    tid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ThesisService(db, principal, request).get(tid))


@router.post(
    "/phd/thesis/{tid}/plagiarism/check",
    status_code=202,
    summary="Plagiarism check (job; ?inline=true checks at once)",
    response_model=Envelope[ThesisOut],
    dependencies=THESIS,
)
async def plagiarism_check(
    tid: uuid.UUID,
    request: Request,
    inline: bool = False,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ThesisService(db, principal, request)
    t, s = await svc.row(tid)
    await svc.require_relation(s, "guide", "co_guide")
    if inline:
        return ok(await svc.check(t.id))
    return await _job(db, principal, "phd.plagiarism_check", {"thesis_id": str(t.id)})


@router.post(
    "/phd/thesis/{tid}/dc-approval",
    summary="Start the DC approval workflow (phd.thesis_dc_approval)",
    response_model=Envelope[ThesisOut],
    dependencies=THESIS,
)
async def thesis_dc_approval(
    tid: uuid.UUID, request: Request, principal: Principal = Depends(GUIDE_W), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ThesisService(db, principal, request).start_dc_approval(tid))


@router.post(
    "/phd/thesis/{tid}/reject", summary="Reject a submission", response_model=Envelope[ThesisOut], dependencies=THESIS
)
async def thesis_reject(
    tid: uuid.UUID,
    body: ThesisReject,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ThesisService(db, principal, request).reject(tid, body))


@router.get("/phd/thesis/{tid}/certificate.pdf", summary="Plagiarism check certificate", dependencies=THESIS)
async def thesis_certificate(
    tid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> Response:
    pdf = await ThesisService(db, principal, request).certificate(tid)
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="plagiarism-{tid}.pdf"'}
    )


# ---- examiners ----------------------------------------------------------------------------------------------------------
@router.get(
    "/phd/examiners",
    summary="Invitations / reports tracker",
    response_model=Envelope[list[ExaminerOut]],
    dependencies=EXAM,
)
async def examiner_tracker(
    request: Request,
    status: str | None = Query(None, max_length=20),
    principal: Principal = Depends(EXAMINE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExaminerService(db, principal, request).tracker(status))


@router.get(
    "/phd/thesis/{tid}/examiners",
    summary="Panel (identities hidden from the scholar until the viva)",
    response_model=Envelope[list[ExaminerOut]],
    dependencies=EXAM,
)
async def panel(
    tid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExaminerService(db, principal, request).panel(tid))


@router.post(
    "/phd/thesis/{tid}/examiners",
    status_code=201,
    summary="Propose a panel (≥ 2 external, ≥ 1 outside state; COI → 409)",
    response_model=Envelope[list[ExaminerOut]],
    dependencies=EXAM,
)
async def propose_panel(
    tid: uuid.UUID,
    body: ExaminerPanelPropose,
    request: Request,
    principal: Principal = Depends(GUIDE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExaminerService(db, principal, request).propose(tid, body), message="Proposed")


@router.post(
    "/phd/thesis/{tid}/examiners/decide",
    summary="Panel decision (dean; closes phd.examiner_panel)",
    response_model=Envelope[list[ExaminerOut]],
    dependencies=EXAM,
)
async def decide_panel(
    tid: uuid.UUID,
    body: PanelDecision,
    request: Request,
    principal: Principal = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExaminerService(db, principal, request).decide(tid, body))


@router.get(
    "/phd/thesis/{tid}/recommendations",
    summary="Consolidated recommendations",
    response_model=Envelope[RecommendationsOut],
    dependencies=EXAM,
)
async def recommendations(
    tid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExaminerService(db, principal, request).recommendations(tid))


@router.post(
    "/phd/examiners/{eid}/invite",
    summary="Invite (tokenised link)",
    response_model=Envelope[ExaminerOut],
    dependencies=EXAM,
)
async def invite(
    eid: uuid.UUID,
    body: ExaminerInvite,
    request: Request,
    principal: Principal = Depends(EXAMINE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExaminerService(db, principal, request).invite(eid, body))


@router.post(
    "/phd/examiners/{eid}/dispatch",
    summary="Dispatch the thesis (signed, watermarked link)",
    response_model=Envelope[ExaminerOut],
    dependencies=EXAM,
)
async def dispatch(
    eid: uuid.UUID, request: Request, principal: Principal = Depends(EXAMINE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExaminerService(db, principal, request).dispatch(eid))


@router.post(
    "/phd/examiners/{eid}/report",
    summary="Record an examiner report",
    response_model=Envelope[ExaminerOut],
    dependencies=EXAM,
)
async def examiner_report(
    eid: uuid.UUID,
    body: ExaminerReportUpload,
    request: Request,
    principal: Principal = Depends(EXAMINE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExaminerService(db, principal, request).report(eid, body))


@router.post(
    "/phd/examiners/{eid}/replace",
    summary="Replace a declined examiner",
    response_model=Envelope[ExaminerOut],
    dependencies=EXAM,
)
async def replace_examiner(
    eid: uuid.UUID,
    body: ExaminerReplace,
    request: Request,
    principal: Principal = Depends(EXAMINE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExaminerService(db, principal, request).replace(eid, body))


@router.post(
    "/phd/examiners/{eid}/remuneration",
    summary="Remuneration line",
    response_model=Envelope[ExaminerOut],
    dependencies=EXAM,
)
async def remuneration(
    eid: uuid.UUID,
    body: ExaminerRemuneration,
    request: Request,
    principal: Principal = Depends(REMUN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExaminerService(db, principal, request).remuneration(eid, body))


# ---- viva ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/phd/viva/upcoming",
    summary="Upcoming vivas (open-defence notices)",
    response_model=Envelope[list[VivaOut]],
    dependencies=VIVA,
)
async def viva_upcoming(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await VivaService(db, principal, request).upcoming())


@router.get(
    "/phd/thesis/{tid}/viva", summary="Viva of a thesis", response_model=Envelope[VivaOut | None], dependencies=VIVA
)
async def get_viva(
    tid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await VivaService(db, principal, request).get_for_thesis(tid))


@router.post(
    "/phd/thesis/{tid}/viva",
    status_code=201,
    summary="Schedule the viva (open defence notice)",
    response_model=Envelope[VivaOut],
    dependencies=VIVA,
)
async def schedule_viva(
    tid: uuid.UUID,
    body: VivaSchedule,
    request: Request,
    principal: Principal = Depends(EXAMINE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await VivaService(db, principal, request).schedule(tid, body), message="Scheduled")


@router.put("/phd/viva/{vid}", summary="Reschedule / panel", response_model=Envelope[VivaOut], dependencies=VIVA)
async def update_viva(
    vid: uuid.UUID,
    body: VivaUpdate,
    request: Request,
    principal: Principal = Depends(EXAMINE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await VivaService(db, principal, request).update(vid, body))


@router.post("/phd/viva/{vid}/result", summary="Viva result", response_model=Envelope[VivaOut], dependencies=VIVA)
async def viva_result(
    vid: uuid.UUID,
    body: VivaResultIn,
    request: Request,
    principal: Principal = Depends(EXAMINE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await VivaService(db, principal, request).result(vid, body))


# ---- award / ETD --------------------------------------------------------------------------------------------------------
@router.get(
    "/phd/awards", summary="PhD awards (Phase 18)", response_model=Envelope[list[dict[str, Any]]], dependencies=CORE
)
async def awards(
    request: Request,
    year: int | None = Query(None, ge=1950, le=2100),
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).awards(year))


@router.get(
    "/phd/awards/etd-status",
    summary="Awards with ETD status",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=ETD_F,
)
async def etd_status(
    request: Request, principal: Principal = Depends(ETD_W), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EtdService(db, principal, request).status_board())


@router.get("/phd/thesis/{tid}/award", summary="Award state", response_model=Envelope[PhdAwardOut], dependencies=CORE)
async def get_award(
    tid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).get(tid))


@router.post(
    "/phd/thesis/{tid}/award",
    summary="Request the award (phd.award; resolution required with governance.minutes)",
    response_model=Envelope[PhdAwardOut],
    dependencies=CORE,
)
async def request_award(
    tid: uuid.UUID,
    body: PhdAwardRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).request_award(tid, body), message="Requested")


@router.get("/phd/thesis/{tid}/etd", summary="ETD uploads", response_model=Envelope[list[EtdOut]], dependencies=ETD_F)
async def etd_list(
    tid: uuid.UUID, request: Request, principal: Principal = Depends(ETD), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EtdService(db, principal, request).for_thesis(tid))


@router.post(
    "/phd/thesis/{tid}/etd",
    status_code=202,
    summary="Upload to Shodhganga / institutional repository (job; ?inline=true uploads at once)",
    response_model=Envelope[EtdOut],
    dependencies=ETD_F,
)
async def etd_upload(
    tid: uuid.UUID,
    body: EtdUploadRequest,
    request: Request,
    inline: bool = False,
    principal: Principal = Depends(ETD_W),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = EtdService(db, principal, request)
    row = await svc.request_upload(tid, body)
    if inline:
        return ok(await svc.upload(row.id))
    return await _job(db, principal, "phd.etd_upload", {"etd_id": str(row.id)})


@router.post(
    "/phd/etd/{eid}/retry", summary="Retry a failed upload", response_model=Envelope[EtdOut], dependencies=ETD_F
)
async def etd_retry(
    eid: uuid.UUID, request: Request, principal: Principal = Depends(ETD_W), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EtdService(db, principal, request).retry(eid))


@router.post(
    "/phd/etd/{eid}/embargo",
    summary="Embargo request / decision (approve set)",
    response_model=Envelope[EtdOut],
    dependencies=ETD_F,
)
async def etd_embargo(
    eid: uuid.UUID,
    body: EtdEmbargo,
    request: Request,
    principal: Principal = Depends(EMBARGO),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EtdService(db, principal, request).embargo(eid, body))


# ---- stats / reports ----------------------------------------------------------------------------------------------------
@router.get(
    "/phd/stats",
    summary="PhD stats (GPHD, durations, utilisation)",
    response_model=Envelope[PhdStats],
    dependencies=CORE,
)
async def stats(
    request: Request,
    department_id: uuid.UUID | None = None,
    year: int | None = Query(None, ge=1950, le=2100),
    principal: Principal = Depends(STATS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StatsService(db, principal, request).stats(department_id, year))


@router.get(
    "/phd/reports/{kind}",
    summary="Reports (scholars / fellowships / awards / ugc_return / examiners) — xlsx job; ?inline=true downloads",
    dependencies=CORE,
    response_model=None,
)
async def reports(
    kind: str,
    request: Request,
    year: int | None = Query(None, ge=1950, le=2100),
    format: str = Query("xlsx", pattern="^(xlsx|json)$"),  # noqa: A002 - query name per Prompts/31 §31.8
    inline: bool = False,
    principal: Principal = Depends(STATS),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if kind not in ("scholars", "fellowships", "awards", "ugc_return", "examiners"):
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown report")
    if not inline:
        from app.services.reports.report_service import alias_params  # Phase 36: alias of POST /reports/run

        return await _job(db, principal, "report.run", await alias_params(db, principal, f"phd.{kind}", {"year": year}))
    rows = await StatsService(db, principal, request).report_rows(kind, year)
    if format == "json":
        return ok(rows)
    from app.tasks.research import xlsx_bytes

    return Response(
        xlsx_bytes(kind, rows),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="phd-{kind}.xlsx"'},
    )


# ---- public: external examiner token pages, plagiarism callback ---------------------------------------------------------
async def _token_tenant(db: AsyncSession, institution: str) -> uuid.UUID:
    from app.db.session import bind_tenant, set_tenant
    from app.services.inventory.vendor_service import tenant_by_slug

    iid = await tenant_by_slug(institution)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    if not await is_enabled(iid, "phd.external_examiners"):
        raise APIError(
            403,
            ErrorCode.FEATURE_DISABLED,
            "Feature 'phd.external_examiners' is not enabled",
            {"feature": "phd.external_examiners"},
        )
    return iid


@public_router.get(
    "/phd/examiners/respond/{token}",
    summary="Examiner invitation (token page)",
    response_model=Envelope[ExaminerTokenView],
)
async def examiner_token_view(
    token: str,
    request: Request,
    institution: str = Query(min_length=2, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    iid = await _token_tenant(db, institution)
    return ok(await ExaminerService(db, None, request, iid).token_view(token))


@public_router.post(
    "/phd/examiners/respond/{token}", summary="Accept / decline (token)", response_model=Envelope[ExaminerTokenView]
)
async def examiner_token_respond(
    token: str,
    body: ExaminerResponse,
    request: Request,
    institution: str = Query(min_length=2, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    iid = await _token_tenant(db, institution)
    return ok(await ExaminerService(db, None, request, iid).respond(token, body))


@public_router.post(
    "/phd/examiners/respond/{token}/report",
    summary="Upload the report (token)",
    response_model=Envelope[ExaminerTokenView],
)
async def examiner_token_report(
    token: str,
    body: ExaminerReportUpload,
    request: Request,
    institution: str = Query(min_length=2, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    iid = await _token_tenant(db, institution)
    return ok(await ExaminerService(db, None, request, iid).token_report(token, body))


@public_router.post("/webhooks/plagiarism/{connection_id}", summary="Plagiarism adapter callback (signed)")
async def plagiarism_webhook(
    connection_id: uuid.UUID, body: PlagiarismResult, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    import hashlib
    import hmac

    from sqlalchemy import text

    from app.db.session import PlatformSessionLocal, bind_tenant, set_tenant

    async with PlatformSessionLocal() as pdb:
        row = (
            await pdb.execute(
                text(
                    "SELECT institution_id, public_config, provider FROM integration_connections "
                    "WHERE id = :i AND capability = 'plagiarism'"
                ),
                {"i": connection_id},
            )
        ).first()
    if row is None or row[0] is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown plagiarism connection")
    iid, conf, provider = uuid.UUID(str(row[0])), dict(row[1] or {}), str(row[2] or "mock")
    if provider != "mock":
        secret = str(conf.get("webhook_secret") or "")
        raw = await request.body()
        sig = request.headers.get("X-Signature")
        expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not secret or not sig or not hmac.compare_digest(sig, expected):
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Bad signature")
    if not await is_enabled(iid, "phd.thesis_plagiarism"):
        return JSONResponse({"ok": True, "ignored": "feature disabled"})
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    out = await ThesisService(db, None, request, iid).apply_result(body, system=True)
    return JSONResponse({"ok": True, "status": out.status})
