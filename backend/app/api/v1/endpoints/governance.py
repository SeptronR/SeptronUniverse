"""Governance — Prompts/33 §33.8: committees {governance.committees}, meetings / minutes / resolutions / ATRs
{governance.minutes}, legal cases {governance.legal}, RTI {governance.rti}, audit paras {governance.audit_paras}, e-File
{governance.efile}, policies {governance.policies} (+ the public website list by institution slug) and stats. Rows are
narrowed by the services (member / secretary / chair / owner / holder / PIO / legal ownership, committee / department /
college / all). Fixed-path routes are declared before ``/{id}`` routes. Replaces the Phase 27 committees stub.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.governance import (
    AgendaSuggestion,
    AgendaUpdate,
    AtrDecision,
    AtrSubmit,
    AttendanceMark,
    AuditParaIn,
    AuditParaOut,
    AuditParaUpdate,
    CommitteeDetail,
    CommitteeFromTemplate,
    CommitteeIn,
    CommitteeOut,
    CommitteeReconstitute,
    CommitteeTemplateOut,
    CommitteeUpdate,
    Corrigendum,
    CoverageItem,
    DocumentRef,
    EfileClose,
    EfileCreate,
    EfileMove,
    EfileOut,
    EfileReopen,
    GovernanceJobQueued,
    GovernanceMe,
    GovernanceStats,
    HearingUpdate,
    LegalCaseIn,
    LegalCaseOut,
    LegalCaseUpdate,
    LegalOutcome,
    MeetingCancel,
    MeetingCreate,
    MeetingOut,
    MeetingUpdate,
    MemberIn,
    MemberOut,
    MemberUpdate,
    MinutesApprove,
    MinutesDraft,
    NoticeSend,
    ParaDashboard,
    ParaReply,
    ParaStatusUpdate,
    PendencyRow,
    PolicyAckOut,
    PolicyApprove,
    PolicyIn,
    PolicyOut,
    PolicyUpdate,
    QuorumOut,
    ResolutionLink,
    ResolutionOut,
    ResolutionStatusChange,
    RtiAppeal,
    RtiAppealDecision,
    RtiAssign,
    RtiClose,
    RtiConsult,
    RtiIn,
    RtiOut,
    RtiRespond,
    RtiReturnOut,
    RtiUpdate,
)
from app.services.governance.audit_para_service import AuditParaService
from app.services.governance.committee_service import CommitteeService
from app.services.governance.efile_service import EfileService
from app.services.governance.legal_service import LegalService
from app.services.governance.meeting_service import MeetingService
from app.services.governance.policy_service import PolicyService
from app.services.governance.resolution_service import ResolutionService
from app.services.governance.rti_service import RtiService
from app.services.governance.stats_service import StatsService
from app.utils.pdf import simple_pdf
from app.utils.response import PaginationMeta, VisibilityMeta, ok

router = APIRouter(tags=["governance"])
public_router = APIRouter(tags=["governance"])

G = "governance"
COMM_VIEW = any_permission_required(
    (G, "view"), (G, "view_all"), (G, "committees"), (G, "minutes"), (G, "resolutions"), (G, "manage")
)
COMM_WRITE = any_permission_required((G, "committees"), (G, "manage"))
MIN_VIEW = any_permission_required(
    (G, "view"), (G, "view_all"), (G, "minutes"), (G, "resolutions"), (G, "approve"), (G, "manage")
)
MIN_WRITE = any_permission_required((G, "minutes"), (G, "manage"))
RES_WRITE = any_permission_required((G, "resolutions"), (G, "minutes"), (G, "manage"))
LEGAL_VIEW = any_permission_required(("legal", "view"), ("legal", "view_all"), ("legal", "manage"))
LEGAL_WRITE = any_permission_required(("legal", "manage"))
RTI_VIEW = any_permission_required(("rti", "view"), ("rti", "view_all"), ("rti", "approve"), ("rti", "manage"))
RTI_WRITE = any_permission_required(("rti", "manage"), ("rti", "update"))
RTI_APPEAL = any_permission_required(("rti", "approve"), ("rti", "manage"), ("rti", "view"))
PARA_VIEW = any_permission_required((G, "view"), (G, "view_all"), (G, "audit_paras"), (G, "manage"))
PARA_WRITE = any_permission_required((G, "audit_paras"), (G, "manage"))
EF_VIEW = any_permission_required(("efile", "view"), ("efile", "create"), ("efile", "view_all"), ("efile", "manage"))
EF_CREATE = any_permission_required(("efile", "create"), ("efile", "manage"))
EF_MANAGE = any_permission_required(("efile", "manage"))
POL_VIEW = any_permission_required((G, "view"), (G, "view_all"), (G, "policies"), (G, "manage"))
POL_WRITE = any_permission_required((G, "policies"), (G, "manage"), (G, "view"))
POL_APPROVE = any_permission_required((G, "approve"), (G, "policies"), (G, "manage"))
STATS = any_permission_required((G, "view_all"), (G, "manage"))

COMMITTEES = [feature_required("governance.committees")]
MINUTES = [feature_required("governance.minutes")]
LEGAL = [feature_required("governance.legal")]
RTI = [feature_required("governance.rti")]
PARAS = [feature_required("governance.audit_paras")]
EFILE = [feature_required("governance.efile")]
POLICIES = [feature_required("governance.policies")]

SCOPE = Query(None, pattern="^(mine|committee|all)$")


def _page(page: int, per_page: int, total: int) -> PaginationMeta:
    return PaginationMeta(page=page, page_size=per_page, total=total, total_pages=max(1, -(-total // per_page)))


def _vis(svc: Any) -> VisibilityMeta:
    scopes = ["mine", "committee"] + (["all"] if svc.reader_all() else [])
    return VisibilityMeta(self=True, scopes=scopes, default="all" if svc.reader_all() else "mine")


def _pdf(name: str, lines: list[str], title: str) -> Response:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_") or "document"
    return Response(
        simple_pdf(lines, title=title),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={safe}.pdf"},
    )


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(
        status_code=202, content=ok(GovernanceJobQueued(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


# ======================================================================================================================
# committees
# ======================================================================================================================
@router.get(
    "/governance/committees/me",
    summary="My committees (member / chair / secretary)",
    response_model=Envelope[list[CommitteeOut]],
    dependencies=COMMITTEES,
)
async def my_committees(
    request: Request, principal: Principal = Depends(COMM_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).mine())


@router.get(
    "/governance/committees/coverage",
    summary="Statutory committee coverage (anti-ragging, ICC, grievance mandatory) with validity",
    response_model=Envelope[list[CoverageItem]],
    dependencies=COMMITTEES,
)
async def coverage(
    request: Request, principal: Principal = Depends(COMM_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).coverage())


@router.get(
    "/governance/committees/templates",
    summary="Statutory committee templates for the institution type",
    response_model=Envelope[list[CommitteeTemplateOut]],
    dependencies=COMMITTEES,
)
async def committee_templates(
    request: Request, principal: Principal = Depends(COMM_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).templates())


@router.post(
    "/governance/committees/from-template",
    status_code=201,
    summary="Constitute a committee from a statutory template",
    response_model=Envelope[CommitteeOut],
    dependencies=COMMITTEES,
)
async def committee_from_template(
    body: CommitteeFromTemplate,
    request: Request,
    principal: Principal = Depends(COMM_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).from_template(body), message="Created")


@router.get(
    "/governance/committees",
    summary="Committees (member / secretary / department / college / all)",
    response_model=Envelope[list[CommitteeOut]],
    dependencies=COMMITTEES,
)
async def committees(
    request: Request,
    committee_type: str | None = Query(None, max_length=30),
    college_id: uuid.UUID | None = None,
    active: bool | None = None,
    principal: Principal = Depends(COMM_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).list_committees(committee_type, college_id, active))


@router.post(
    "/governance/committees",
    status_code=201,
    summary="Create a committee",
    response_model=Envelope[CommitteeOut],
    dependencies=COMMITTEES,
)
async def create_committee(
    body: CommitteeIn, request: Request, principal: Principal = Depends(COMM_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).create(body), message="Created")


@router.get(
    "/governance/committees/{id}",
    summary="Committee page (members with tenure, meetings, open resolutions, ATR pendency, history)",
    response_model=Envelope[CommitteeDetail],
    dependencies=COMMITTEES,
)
async def committee(
    id: uuid.UUID, request: Request, principal: Principal = Depends(COMM_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).detail(id))


@router.put(
    "/governance/committees/{id}",
    summary="Update a committee (secretary / chair / administrator)",
    response_model=Envelope[CommitteeOut],
    dependencies=COMMITTEES,
)
async def update_committee(
    id: uuid.UUID,
    body: CommitteeUpdate,
    request: Request,
    principal: Principal = Depends(COMM_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).update(id, body))


@router.post(
    "/governance/committees/{id}/reconstitute",
    summary="Reconstitute: new tenure, old members closed, history kept",
    response_model=Envelope[CommitteeDetail],
    dependencies=COMMITTEES,
)
async def reconstitute(
    id: uuid.UUID,
    body: CommitteeReconstitute,
    request: Request,
    principal: Principal = Depends(COMM_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).reconstitute(id, body))


@router.get(
    "/governance/committees/{id}/members",
    summary="Committee members",
    response_model=Envelope[list[MemberOut]],
    dependencies=COMMITTEES,
)
async def committee_members(
    id: uuid.UUID,
    request: Request,
    include_past: bool = False,
    principal: Principal = Depends(COMM_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).members(id, include_past))


@router.post(
    "/governance/committees/{id}/members",
    status_code=201,
    summary="Add a member (staff / external / student)",
    response_model=Envelope[MemberOut],
    dependencies=COMMITTEES,
)
async def add_member(
    id: uuid.UUID,
    body: MemberIn,
    request: Request,
    principal: Principal = Depends(COMM_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).add_member(id, body), message="Added")


@router.put(
    "/governance/committee-members/{id}",
    summary="Update a membership (role / tenure)",
    response_model=Envelope[MemberOut],
    dependencies=COMMITTEES,
)
async def update_member(
    id: uuid.UUID,
    body: MemberUpdate,
    request: Request,
    principal: Principal = Depends(COMM_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommitteeService(db, principal, request).update_member(id, body))


@router.delete(
    "/governance/committee-members/{id}",
    summary="End a membership today (history kept)",
    response_model=Envelope[None],
    dependencies=COMMITTEES,
)
async def remove_member(
    id: uuid.UUID, request: Request, principal: Principal = Depends(COMM_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await CommitteeService(db, principal, request).remove_member(id)
    return ok(None, message="Removed")


@router.get(
    "/governance/me",
    summary="Staff / student governance overview (committees, meetings, resolutions, e-file inbox, policy acks)",
    response_model=Envelope[GovernanceMe],
    dependencies=COMMITTEES,
)
async def governance_me(
    request: Request, principal: Principal = Depends(COMM_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    inst = getattr(request.state, "institution_id", None)

    async def on(key: str) -> bool:
        return bool(inst) and await is_enabled(inst, key)

    meetings: list[MeetingOut] = []
    res: list[ResolutionOut] = []
    if await on("governance.minutes"):
        meetings = await MeetingService(db, principal, request).my_meetings()
        res, _ = await ResolutionService(db, principal, request).list_resolutions(scope="mine", limit=50)
    efile = await EfileService(db, principal, request).inbox_count() if await on("governance.efile") else 0
    acks = await PolicyService(db, principal, request).pending_ack() if await on("governance.policies") else []
    paras = (
        len(await AuditParaService(db, principal, request).list_paras(mine=True))
        if await on("governance.audit_paras")
        else 0
    )
    return ok(
        GovernanceMe(
            committees=await CommitteeService(db, principal, request).mine(),
            meetings=meetings,
            resolutions=res,
            efile_inbox=efile,
            pending_acks=acks,
            audit_paras=paras,
        )
    )


# ======================================================================================================================
# meetings / minutes
# ======================================================================================================================
@router.get(
    "/governance/meetings/me",
    summary="Meetings of my committees",
    response_model=Envelope[list[MeetingOut]],
    dependencies=MINUTES,
)
async def my_meetings(
    request: Request, principal: Principal = Depends(MIN_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).my_meetings())


@router.get(
    "/governance/meetings",
    summary="Meetings (ScopeTabs Mine | Committee | All)",
    response_model=Envelope[list[MeetingOut]],
    dependencies=MINUTES,
)
async def meetings(
    request: Request,
    committee_id: uuid.UUID | None = None,
    status: str | None = Query(None, max_length=20),
    year: int | None = Query(None, ge=2000, le=2100),
    scope: str | None = SCOPE,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(MIN_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = MeetingService(db, principal, request)
    rows = await svc.list_meetings(
        committee_id=committee_id, status=status, scope=scope, year=year, limit=per_page, offset=(page - 1) * per_page
    )
    return ok(rows, visibility=_vis(svc))


@router.post(
    "/governance/meetings",
    status_code=201,
    summary="Schedule a meeting (number auto per committee / year; ATR item added)",
    response_model=Envelope[MeetingOut],
    dependencies=MINUTES,
)
async def create_meeting(
    body: MeetingCreate, request: Request, principal: Principal = Depends(MIN_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).create(body), message="Scheduled")


@router.get(
    "/governance/meetings/{id}",
    summary="Meeting (agenda, notice, attendance / quorum, minutes, resolutions, approval)",
    response_model=Envelope[MeetingOut],
    dependencies=MINUTES,
)
async def meeting(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MIN_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).get(id))


@router.put(
    "/governance/meetings/{id}",
    summary="Reschedule / change venue",
    response_model=Envelope[MeetingOut],
    dependencies=MINUTES,
)
async def update_meeting(
    id: uuid.UUID,
    body: MeetingUpdate,
    request: Request,
    principal: Principal = Depends(MIN_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).update(id, body))


@router.put(
    "/governance/meetings/{id}/agenda",
    summary="Replace the agenda (until frozen)",
    response_model=Envelope[MeetingOut],
    dependencies=MINUTES,
)
async def set_agenda(
    id: uuid.UUID,
    body: AgendaUpdate,
    request: Request,
    principal: Principal = Depends(MIN_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).set_agenda(id, body))


@router.get(
    "/governance/meetings/{id}/agenda/suggestions",
    summary="Agenda suggestions (ATRs, regulations, result runs, degrees, BoS items, policies, audit paras, IQAC gaps)",
    response_model=Envelope[list[AgendaSuggestion]],
    dependencies=MINUTES,
)
async def agenda_suggestions(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MIN_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).suggestions(id))


@router.post(
    "/governance/meetings/{id}/notice",
    summary="Send the meeting notice (short notice flagged; calendar entry)",
    response_model=Envelope[MeetingOut],
    dependencies=MINUTES,
)
async def send_notice(
    id: uuid.UUID,
    body: NoticeSend,
    request: Request,
    principal: Principal = Depends(MIN_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).send_notice(id, body), message="Notice sent")


@router.post(
    "/governance/meetings/{id}/attendance",
    summary="Mark attendance (secretary roll or member self check-in) → quorum",
    response_model=Envelope[QuorumOut],
    dependencies=MINUTES,
)
async def attendance(
    id: uuid.UUID,
    body: AttendanceMark,
    request: Request,
    principal: Principal = Depends(MIN_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).attendance(id, body))


@router.post(
    "/governance/meetings/{id}/minutes",
    summary="Draft minutes with per-item resolutions (409 QUORUM_NOT_MET when blocked)",
    response_model=Envelope[MeetingOut],
    dependencies=MINUTES,
)
async def draft_minutes(
    id: uuid.UUID,
    body: MinutesDraft,
    request: Request,
    principal: Principal = Depends(MIN_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).draft_minutes(id, body))


@router.post(
    "/governance/meetings/{id}/minutes/submit",
    summary="Submit the minutes (governance.minutes_approval: secretary → chair)",
    response_model=Envelope[MeetingOut],
    dependencies=MINUTES,
)
async def submit_minutes(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MIN_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).submit_minutes(id))


@router.post(
    "/governance/meetings/{id}/minutes/approve",
    summary="Approve / return the minutes (chair) — numbers resolutions, renders the minutes",
    response_model=Envelope[MeetingOut],
    dependencies=MINUTES,
)
async def approve_minutes(
    id: uuid.UUID,
    body: MinutesApprove,
    request: Request,
    principal: Principal = Depends(MIN_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).approve_minutes(id, body))


@router.post(
    "/governance/meetings/{id}/corrigendum",
    summary="Corrigendum to approved minutes (new version with approval record)",
    response_model=Envelope[MeetingOut],
    dependencies=MINUTES,
)
async def corrigendum(
    id: uuid.UUID,
    body: Corrigendum,
    request: Request,
    principal: Principal = Depends(MIN_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).corrigendum(id, body))


@router.post(
    "/governance/meetings/{id}/cancel",
    summary="Cancel / adjourn a meeting",
    response_model=Envelope[MeetingOut],
    dependencies=MINUTES,
)
async def cancel_meeting(
    id: uuid.UUID,
    body: MeetingCancel,
    request: Request,
    principal: Principal = Depends(MIN_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MeetingService(db, principal, request).cancel(id, body))


@router.get(
    "/governance/meetings/{id}/minutes.pdf",
    summary="Minutes PDF (approved; drafts to the secretary / chair)",
    response_class=Response,
    dependencies=MINUTES,
)
async def minutes_pdf(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MIN_VIEW), db: AsyncSession = Depends(get_db)
) -> Response:
    name, lines = await MeetingService(db, principal, request).minutes_lines(id)
    return _pdf(name, lines, "Minutes")


# ---- resolutions / ATR ------------------------------------------------------------------------------------------------
@router.get(
    "/governance/resolutions/lookup",
    summary="Resolutions linked to an entity (regulation / result_run / degree_award / policy / …)",
    response_model=Envelope[list[ResolutionOut]],
    dependencies=MINUTES,
)
async def resolution_lookup(
    request: Request,
    entity_type: str = Query(min_length=2, max_length=40),
    entity_id: uuid.UUID = Query(...),
    principal: Principal = Depends(MIN_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResolutionService(db, principal, request).lookup(entity_type, entity_id))


@router.get(
    "/governance/resolutions",
    summary="Resolution register (ScopeTabs Mine | Committee | All)",
    response_model=Envelope[list[ResolutionOut]],
    dependencies=MINUTES,
)
async def resolutions(
    request: Request,
    committee_id: uuid.UUID | None = None,
    status: str | None = Query(None, max_length=20),
    owner_id: uuid.UUID | None = None,
    year: int | None = Query(None, ge=2000, le=2100),
    scope: str | None = SCOPE,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(MIN_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ResolutionService(db, principal, request)
    rows, total = await svc.list_resolutions(
        committee_id=committee_id,
        status=status,
        owner_id=owner_id,
        year=year,
        scope=scope,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return ok(rows, pagination=_page(page, per_page, total), visibility=_vis(svc))


@router.get(
    "/governance/resolutions/{id}",
    summary="Resolution with its ATR",
    response_model=Envelope[ResolutionOut],
    dependencies=MINUTES,
)
async def resolution(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MIN_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ResolutionService(db, principal, request).get(id))


@router.post(
    "/governance/resolutions/{id}/link",
    summary="Link a resolution to an entity (writes the entity's approval_resolution_id)",
    response_model=Envelope[ResolutionOut],
    dependencies=MINUTES,
)
async def link_resolution(
    id: uuid.UUID,
    body: ResolutionLink,
    request: Request,
    principal: Principal = Depends(RES_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResolutionService(db, principal, request).link(id, body))


@router.post(
    "/governance/resolutions/{id}/status",
    summary="Change a resolution's status",
    response_model=Envelope[ResolutionOut],
    dependencies=MINUTES,
)
async def resolution_status(
    id: uuid.UUID,
    body: ResolutionStatusChange,
    request: Request,
    principal: Principal = Depends(RES_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResolutionService(db, principal, request).set_status(id, body))


@router.get(
    "/governance/resolutions/{id}/extract.pdf",
    summary="Certified extract (Phase 26 resolution_extract)",
    response_model=Envelope[DocumentRef],
    dependencies=MINUTES,
)
async def resolution_extract(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MIN_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ResolutionService(db, principal, request).extract(id))


@router.post(
    "/governance/resolutions/{id}/atr",
    status_code=201,
    summary="Submit the action-taken report (action owner)",
    response_model=Envelope[ResolutionOut],
    dependencies=MINUTES,
)
async def submit_atr(
    id: uuid.UUID,
    body: AtrSubmit,
    request: Request,
    principal: Principal = Depends(MIN_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResolutionService(db, principal, request).submit_atr(id, body), message="Submitted")


@router.post(
    "/governance/atr/{id}/decide",
    summary="Accept (→ implemented) / return an ATR (secretary)",
    response_model=Envelope[ResolutionOut],
    dependencies=MINUTES,
)
async def decide_atr(
    id: uuid.UUID,
    body: AtrDecision,
    request: Request,
    principal: Principal = Depends(RES_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResolutionService(db, principal, request).decide_atr(id, body))


# ======================================================================================================================
# legal
# ======================================================================================================================
@router.get(
    "/legal/calendar", summary="Hearing calendar", response_model=Envelope[list[dict[str, Any]]], dependencies=LEGAL
)
async def legal_calendar(
    request: Request,
    days: int = Query(60, ge=1, le=365),
    principal: Principal = Depends(LEGAL_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LegalService(db, principal, request).calendar(days))


@router.get(
    "/legal/cases", summary="Legal case register", response_model=Envelope[list[LegalCaseOut]], dependencies=LEGAL
)
async def legal_cases(
    request: Request,
    status: str | None = Query(None, max_length=20),
    q: str | None = Query(None, max_length=60),
    principal: Principal = Depends(LEGAL_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LegalService(db, principal, request).list_cases(status, q))


@router.post(
    "/legal/cases",
    status_code=201,
    summary="Register a case (appeals link the parent case)",
    response_model=Envelope[LegalCaseOut],
    dependencies=LEGAL,
)
async def create_case(
    body: LegalCaseIn, request: Request, principal: Principal = Depends(LEGAL_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LegalService(db, principal, request).create(body), message="Created")


@router.get("/legal/cases/{id}", summary="Case", response_model=Envelope[LegalCaseOut], dependencies=LEGAL)
async def legal_case(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LEGAL_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LegalService(db, principal, request).get(id))


@router.put("/legal/cases/{id}", summary="Update a case", response_model=Envelope[LegalCaseOut], dependencies=LEGAL)
async def update_case(
    id: uuid.UUID,
    body: LegalCaseUpdate,
    request: Request,
    principal: Principal = Depends(LEGAL_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LegalService(db, principal, request).update(id, body))


@router.post(
    "/legal/cases/{id}/hearings",
    summary="Record a hearing and the next date",
    response_model=Envelope[LegalCaseOut],
    dependencies=LEGAL,
)
async def case_hearing(
    id: uuid.UUID,
    body: HearingUpdate,
    request: Request,
    principal: Principal = Depends(LEGAL_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LegalService(db, principal, request).hearing(id, body))


@router.post(
    "/legal/cases/{id}/outcome",
    summary="Outcome / judgement",
    response_model=Envelope[LegalCaseOut],
    dependencies=LEGAL,
)
async def case_outcome(
    id: uuid.UUID,
    body: LegalOutcome,
    request: Request,
    principal: Principal = Depends(LEGAL_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LegalService(db, principal, request).outcome(id, body))


@router.get(
    "/legal/cases/{id}/documents",
    summary="Case documents (legal:manage only)",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=LEGAL,
)
async def case_documents(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LEGAL_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LegalService(db, principal, request).documents(id))


# ======================================================================================================================
# RTI
# ======================================================================================================================
@router.get(
    "/rti/returns",
    summary="Quarterly / annual RTI return (job; ?inline=true returns the figures)",
    response_model=Envelope[RtiReturnOut],
    dependencies=RTI,
)
async def rti_returns(
    request: Request,
    period: str = Query(pattern=r"^\d{4}(-Q[1-4])?$"),
    inline: bool = False,
    principal: Principal = Depends(RTI_VIEW),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = RtiService(db, principal, request)
    if not svc.can_read():
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "rti:view_all required")
    if not inline:
        return await _job(db, principal, "rti.annual_return", {"period": period})
    return ok(await svc.annual_return(period))


@router.get(
    "/rti/requests", summary="RTI requests (PIO queue)", response_model=Envelope[list[RtiOut]], dependencies=RTI
)
async def rti_requests(
    request: Request,
    status: str | None = Query(None, max_length=20),
    overdue: bool | None = None,
    principal: Principal = Depends(RTI_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RtiService(db, principal, request).list_requests(status, overdue))


@router.post(
    "/rti/requests",
    status_code=201,
    summary="Record an RTI request (due date, fee / BPL waiver)",
    response_model=Envelope[RtiOut],
    dependencies=RTI,
)
async def create_rti(
    body: RtiIn, request: Request, principal: Principal = Depends(RTI_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RtiService(db, principal, request).create(body), message="Recorded")


@router.get("/rti/requests/{id}", summary="RTI request", response_model=Envelope[RtiOut], dependencies=RTI)
async def rti_request(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RTI_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RtiService(db, principal, request).get(id))


@router.put("/rti/requests/{id}", summary="Correct an RTI request", response_model=Envelope[RtiOut], dependencies=RTI)
async def update_rti(
    id: uuid.UUID,
    body: RtiUpdate,
    request: Request,
    principal: Principal = Depends(RTI_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RtiService(db, principal, request).update(id, body))


@router.post("/rti/requests/{id}/assign", summary="Assign the PIO", response_model=Envelope[RtiOut], dependencies=RTI)
async def assign_rti(
    id: uuid.UUID,
    body: RtiAssign,
    request: Request,
    principal: Principal = Depends(RTI_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RtiService(db, principal, request).assign(id, body))


@router.post(
    "/rti/requests/{id}/consult",
    summary="Consult a department through e-File",
    response_model=Envelope[RtiOut],
    dependencies=RTI,
)
async def consult_rti(
    id: uuid.UUID,
    body: RtiConsult,
    request: Request,
    principal: Principal = Depends(RTI_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RtiService(db, principal, request).consult(id, body))


@router.post(
    "/rti/requests/{id}/respond",
    summary="Reply (Phase 26 rti_response; additional fee for copies)",
    response_model=Envelope[RtiOut],
    dependencies=RTI,
)
async def respond_rti(
    id: uuid.UUID,
    body: RtiRespond,
    request: Request,
    principal: Principal = Depends(RTI_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RtiService(db, principal, request).respond(id, body))


@router.post(
    "/rti/requests/{id}/appeal", summary="Record a first appeal", response_model=Envelope[RtiOut], dependencies=RTI
)
async def appeal_rti(
    id: uuid.UUID,
    body: RtiAppeal,
    request: Request,
    principal: Principal = Depends(RTI_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RtiService(db, principal, request).appeal(id, body))


@router.post(
    "/rti/requests/{id}/appeal/decide",
    summary="Decide the first appeal (appellate authority)",
    response_model=Envelope[RtiOut],
    dependencies=RTI,
)
async def decide_rti_appeal(
    id: uuid.UUID,
    body: RtiAppealDecision,
    request: Request,
    principal: Principal = Depends(RTI_APPEAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RtiService(db, principal, request).decide_appeal(id, body))


@router.post(
    "/rti/requests/{id}/close", summary="Close a replied request", response_model=Envelope[RtiOut], dependencies=RTI
)
async def close_rti(
    id: uuid.UUID,
    body: RtiClose,
    request: Request,
    principal: Principal = Depends(RTI_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RtiService(db, principal, request).close(id, body))


# ======================================================================================================================
# audit paras
# ======================================================================================================================
@router.get("/audit-paras/me", summary="Paras I own", response_model=Envelope[list[AuditParaOut]], dependencies=PARAS)
async def my_paras(
    request: Request, principal: Principal = Depends(PARA_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuditParaService(db, principal, request).list_paras(mine=True))


@router.get(
    "/audit-paras/dashboard",
    summary="Ageing / status / register dashboard",
    response_model=Envelope[ParaDashboard],
    dependencies=PARAS,
)
async def para_dashboard(
    request: Request, principal: Principal = Depends(PARA_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuditParaService(db, principal, request).dashboard())


@router.get(
    "/audit-paras",
    summary="Audit paras (financial statutory / AG registers)",
    response_model=Envelope[list[AuditParaOut]],
    dependencies=PARAS,
)
async def audit_paras(
    request: Request,
    audit_register_id: uuid.UUID | None = None,
    status: str | None = Query(None, max_length=20),
    principal: Principal = Depends(PARA_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AuditParaService(db, principal, request).list_paras(audit_register_id, status))


@router.post(
    "/audit-paras", status_code=201, summary="Record a para", response_model=Envelope[AuditParaOut], dependencies=PARAS
)
async def create_para(
    body: AuditParaIn, request: Request, principal: Principal = Depends(PARA_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuditParaService(db, principal, request).create(body), message="Created")


@router.get("/audit-paras/{id}", summary="Para", response_model=Envelope[AuditParaOut], dependencies=PARAS)
async def audit_para(
    id: uuid.UUID, request: Request, principal: Principal = Depends(PARA_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuditParaService(db, principal, request).get(id))


@router.put("/audit-paras/{id}", summary="Update a para", response_model=Envelope[AuditParaOut], dependencies=PARAS)
async def update_para(
    id: uuid.UUID,
    body: AuditParaUpdate,
    request: Request,
    principal: Principal = Depends(PARA_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AuditParaService(db, principal, request).update(id, body))


@router.post(
    "/audit-paras/{id}/reply",
    summary="Reply (owner / finance)",
    response_model=Envelope[AuditParaOut],
    dependencies=PARAS,
)
async def reply_para(
    id: uuid.UUID,
    body: ParaReply,
    request: Request,
    principal: Principal = Depends(PARA_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AuditParaService(db, principal, request).reply(id, body))


@router.post(
    "/audit-paras/{id}/status",
    summary="Settle / drop / reopen a para",
    response_model=Envelope[AuditParaOut],
    dependencies=PARAS,
)
async def para_status(
    id: uuid.UUID,
    body: ParaStatusUpdate,
    request: Request,
    principal: Principal = Depends(PARA_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AuditParaService(db, principal, request).set_status(id, body))


# ======================================================================================================================
# e-File
# ======================================================================================================================
def _box(name: str) -> Any:
    async def handler(
        request: Request,
        q: str | None = Query(None, max_length=100),
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=1, le=200),
        principal: Principal = Depends(EF_VIEW),
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        rows, total = await EfileService(db, principal, request).list_files(
            name, q, None, per_page, (page - 1) * per_page
        )
        return ok(rows, pagination=_page(page, per_page, total))

    return handler


router.get("/efiles/inbox", summary="Files with me", response_model=Envelope[list[EfileOut]], dependencies=EFILE)(
    _box("inbox")
)
router.get(
    "/efiles/outbox",
    summary="Files I moved (held by others)",
    response_model=Envelope[list[EfileOut]],
    dependencies=EFILE,
)(_box("outbox"))
router.get("/efiles/mine", summary="Files I created", response_model=Envelope[list[EfileOut]], dependencies=EFILE)(
    _box("mine")
)


@router.get(
    "/efiles/pendency",
    summary="Pendency by holder (SLA breaches first)",
    response_model=Envelope[list[PendencyRow]],
    dependencies=EFILE,
)
async def efile_pendency(
    request: Request,
    department_id: uuid.UUID | None = None,
    principal: Principal = Depends(EF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EfileService(db, principal, request).pendency(department_id))


@router.get(
    "/efiles", summary="Files visible to me (search)", response_model=Envelope[list[EfileOut]], dependencies=EFILE
)
async def efiles(
    request: Request,
    q: str | None = Query(None, max_length=100),
    status: str | None = Query(None, max_length=20),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(EF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, total = await EfileService(db, principal, request).list_files(
        None, q, status, per_page, (page - 1) * per_page
    )
    return ok(rows, pagination=_page(page, per_page, total))


@router.post(
    "/efiles",
    status_code=201,
    summary="Open a file with the initial noting",
    response_model=Envelope[EfileOut],
    dependencies=EFILE,
)
async def create_efile(
    body: EfileCreate, request: Request, principal: Principal = Depends(EF_CREATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EfileService(db, principal, request).create(body), message="Created")


@router.get(
    "/efiles/{id}",
    summary="File with the append-only notings sheet",
    response_model=Envelope[EfileOut],
    dependencies=EFILE,
)
async def efile(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EF_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EfileService(db, principal, request).get(id))


@router.post(
    "/efiles/{id}/move",
    summary="Forward (user / role) / return / approve / reject with a noting",
    response_model=Envelope[EfileOut],
    dependencies=EFILE,
)
async def move_efile(
    id: uuid.UUID,
    body: EfileMove,
    request: Request,
    principal: Principal = Depends(EF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EfileService(db, principal, request).move(id, body))


@router.post("/efiles/{id}/close", summary="Close with summary", response_model=Envelope[EfileOut], dependencies=EFILE)
async def close_efile(
    id: uuid.UUID,
    body: EfileClose,
    request: Request,
    principal: Principal = Depends(EF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EfileService(db, principal, request).close(id, body))


@router.post("/efiles/{id}/reopen", summary="Reopen (admin)", response_model=Envelope[EfileOut], dependencies=EFILE)
async def reopen_efile(
    id: uuid.UUID,
    body: EfileReopen,
    request: Request,
    principal: Principal = Depends(EF_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EfileService(db, principal, request).reopen(id, body))


@router.get("/efiles/{id}/notings.pdf", summary="Notings sheet PDF", response_class=Response, dependencies=EFILE)
async def notings_pdf(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EF_VIEW), db: AsyncSession = Depends(get_db)
) -> Response:
    name, lines = await EfileService(db, principal, request).notings_lines(id)
    return _pdf(name, lines, "Notings sheet")


# ======================================================================================================================
# policies
# ======================================================================================================================
@router.get(
    "/policies/me/pending-ack",
    summary="Published policies awaiting my acknowledgement",
    response_model=Envelope[list[PolicyOut]],
    dependencies=POLICIES,
)
async def pending_acks(
    request: Request, principal: Principal = Depends(POL_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).pending_ack())


@router.get("/policies", summary="Policy repository", response_model=Envelope[list[PolicyOut]], dependencies=POLICIES)
async def policies(
    request: Request,
    category: str | None = Query(None, max_length=60),
    status: str | None = Query(None, max_length=20),
    q: str | None = Query(None, max_length=100),
    principal: Principal = Depends(POL_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).list_policies(category, status, q))


@router.post(
    "/policies",
    status_code=201,
    summary="Draft a policy (version)",
    response_model=Envelope[PolicyOut],
    dependencies=POLICIES,
)
async def create_policy(
    body: PolicyIn, request: Request, principal: Principal = Depends(POL_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).create(body), message="Created")


@router.get("/policies/{id}", summary="Policy", response_model=Envelope[PolicyOut], dependencies=POLICIES)
async def policy(
    id: uuid.UUID, request: Request, principal: Principal = Depends(POL_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).get(id))


@router.put("/policies/{id}", summary="Edit a draft", response_model=Envelope[PolicyOut], dependencies=POLICIES)
async def update_policy(
    id: uuid.UUID,
    body: PolicyUpdate,
    request: Request,
    principal: Principal = Depends(POL_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).update(id, body))


@router.post(
    "/policies/{id}/submit",
    summary="Submit for approval (owner → registrar → principal)",
    response_model=Envelope[PolicyOut],
    dependencies=POLICIES,
)
async def submit_policy(
    id: uuid.UUID, request: Request, principal: Principal = Depends(POL_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).submit(id))


@router.post(
    "/policies/{id}/approve",
    summary="Approve / return (final approval cites a council resolution with governance.minutes)",
    response_model=Envelope[PolicyOut],
    dependencies=POLICIES,
)
async def approve_policy(
    id: uuid.UUID,
    body: PolicyApprove,
    request: Request,
    principal: Principal = Depends(POL_APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).approve(id, body))


@router.post(
    "/policies/{id}/publish",
    summary="Publish (announcement with acknowledgement where required)",
    response_model=Envelope[PolicyOut],
    dependencies=POLICIES,
)
async def publish_policy(
    id: uuid.UUID, request: Request, principal: Principal = Depends(POL_APPROVE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).publish(id))


@router.post(
    "/policies/{id}/supersede", summary="Mark superseded", response_model=Envelope[PolicyOut], dependencies=POLICIES
)
async def supersede_policy(
    id: uuid.UUID,
    request: Request,
    by_policy_id: uuid.UUID | None = None,
    principal: Principal = Depends(POL_APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).supersede(id, by_policy_id))


@router.post(
    "/policies/{id}/acknowledge",
    summary="Acknowledge a policy",
    response_model=Envelope[PolicyOut],
    dependencies=POLICIES,
)
async def acknowledge_policy(
    id: uuid.UUID, request: Request, principal: Principal = Depends(POL_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).acknowledge(id))


@router.get(
    "/policies/{id}/acknowledgements",
    summary="Acknowledgements",
    response_model=Envelope[list[PolicyAckOut]],
    dependencies=POLICIES,
)
async def policy_acks(
    id: uuid.UUID, request: Request, principal: Principal = Depends(POL_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).acknowledgements(id))


@public_router.get(
    "/policies/public",
    summary="Published policies flagged for the website (tenant by institution slug)",
    response_model=Envelope[list[PolicyOut]],
)
async def public_policies(
    request: Request, institution: str = Query(min_length=2, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.db.session import bind_tenant, set_tenant
    from app.services.inventory.vendor_service import tenant_by_slug

    iid = await tenant_by_slug(institution)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    if not await is_enabled(iid, "governance.policies"):
        raise APIError(
            403,
            ErrorCode.FEATURE_DISABLED,
            "Feature 'governance.policies' is not enabled",
            {"feature": "governance.policies"},
        )
    return ok(await PolicyService(db, None, request, iid).public())


# ======================================================================================================================
# stats
# ======================================================================================================================
@router.get(
    "/governance/stats",
    summary="Governance statistics (meetings, quorum, resolutions, ATR, legal, RTI, paras, e-file, policy acks)",
    response_model=Envelope[GovernanceStats],
    dependencies=COMMITTEES,
)
async def governance_stats(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    principal: Principal = Depends(STATS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StatsService(db, principal, request).stats(year))
