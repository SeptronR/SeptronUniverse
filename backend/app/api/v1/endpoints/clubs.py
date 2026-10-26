"""Clubs, activity hours, achievements and student-support stats — Prompts/27 §27.8: clubs / members / events
{clubs.core}, activity hours {clubs.core} with credit mapping {clubs.activity_hours_credits}, achievements
{clubs.achievements} and ``/student-support/stats`` {mentoring.core}. The Phase 27 ``/governance/committees`` stub is
replaced by Phase 33 (``app/api/v1/endpoints/governance.py``).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.clubs import (
    AchCreate,
    AchOut,
    AchVerify,
    ActCreditEligible,
    ActHourBulk,
    ActHourCreate,
    ActHourOut,
    ActLedger,
    ActVerify,
    ActVerifyResult,
    ClubEventIn,
    ClubEventOut,
    ClubIn,
    ClubMemberDecide,
    ClubMemberIn,
    ClubMemberOut,
    ClubMemberRole,
    ClubOut,
    SupportStats,
)
from app.schemas.common import Envelope
from app.services.student_support.club_service import ClubService
from app.services.student_support.stats_service import StatsService
from app.utils.response import ok

router = APIRouter(tags=["clubs"])

C = "clubs"
VIEW = any_permission_required((C, "view"), (C, "view_all"), (C, "manage"), (C, "verify_hours"))
MANAGE = any_permission_required((C, "manage"), (C, "view"))  # advisors (clubs:view) are checked per club
HOURS_SELF = any_permission_required((C, "view"), (C, "verify_hours"), (C, "manage"))
VERIFY = any_permission_required((C, "verify_hours"), (C, "manage"), (C, "view"))
STATS = any_permission_required(
    ("mentoring", "view_all"), ("mentoring", "manage"), ("accreditation", "view"), ("surveys", "manage")
)

CORE = [feature_required("clubs.core")]
CREDITS = [feature_required("clubs.activity_hours_credits")]
ACH = [feature_required("clubs.achievements")]
SUPPORT = [feature_required("mentoring.core")]


# ---- clubs ----------------------------------------------------------------------------------------------------------------
@router.get(
    "/clubs",
    summary="Clubs (?mine=true: my clubs / advised clubs)",
    response_model=Envelope[list[ClubOut]],
    dependencies=CORE,
)
async def clubs(
    request: Request,
    club_type: str | None = None,
    mine: bool = False,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).list_clubs(club_type, mine))


@router.post("/clubs", status_code=201, summary="Create a club", response_model=Envelope[ClubOut], dependencies=CORE)
async def create_club(
    body: ClubIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).create_club(body), message="Created")


@router.get("/clubs/{id}", summary="Club", response_model=Envelope[ClubOut], dependencies=CORE)
async def get_club(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).get_club(id))


@router.put(
    "/clubs/{id}", summary="Update a club (advisor / clubs:manage)", response_model=Envelope[ClubOut], dependencies=CORE
)
async def update_club(
    id: uuid.UUID,
    body: ClubIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).update_club(id, body))


@router.get(
    "/clubs/{id}/members",
    summary="Members & office bearers",
    response_model=Envelope[list[ClubMemberOut]],
    dependencies=CORE,
)
async def members(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).members(id))


@router.post(
    "/clubs/{id}/members",
    status_code=201,
    summary="Add a member (advisor)",
    response_model=Envelope[ClubMemberOut],
    dependencies=CORE,
)
async def add_member(
    id: uuid.UUID,
    body: ClubMemberIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).add_member(id, body), message="Added")


@router.post(
    "/clubs/{id}/join",
    status_code=201,
    summary="Request to join (student)",
    response_model=Envelope[ClubMemberOut],
    dependencies=CORE,
)
async def join(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).join(id), message="Requested")


@router.post(
    "/clubs/{id}/members/{member_id}/decide",
    summary="Approve / decline a join request",
    response_model=Envelope[ClubMemberOut | None],
    dependencies=CORE,
)
async def decide_member(
    id: uuid.UUID,
    member_id: uuid.UUID,
    body: ClubMemberDecide,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).decide_member(id, member_id, body))


@router.post(
    "/clubs/{id}/members/{member_id}/role",
    summary="Set an office-bearer role",
    response_model=Envelope[ClubMemberOut],
    dependencies=CORE,
)
async def set_role(
    id: uuid.UUID,
    member_id: uuid.UUID,
    body: ClubMemberRole,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).set_role(id, member_id, body))


@router.get("/clubs/{id}/events", summary="Club events", response_model=Envelope[list[ClubEventOut]], dependencies=CORE)
async def events(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).events(id))


@router.post(
    "/clubs/{id}/events",
    status_code=201,
    summary="Record a club event (optionally linked to a Phase 25 event)",
    response_model=Envelope[ClubEventOut],
    dependencies=CORE,
)
async def add_event(
    id: uuid.UUID,
    body: ClubEventIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).add_event(id, body), message="Recorded")


# ---- activity hours -------------------------------------------------------------------------------------------------------
@router.get(
    "/activity-hours",
    summary="Hours queue (officers: all; advisors: their clubs)",
    response_model=Envelope[list[ActHourOut]],
    dependencies=CORE,
)
async def hours(
    request: Request,
    status: str | None = None,
    activity_type: str | None = None,
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).list_hours(status, activity_type))


@router.post(
    "/activity-hours",
    status_code=201,
    summary="Log hours (with evidence)",
    response_model=Envelope[ActHourOut],
    dependencies=CORE,
)
async def log_hours(
    body: ActHourCreate,
    request: Request,
    principal: Principal = Depends(HOURS_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).log_hours(body), message="Logged")


@router.post(
    "/activity-hours/evidence",
    status_code=201,
    summary="Upload evidence (photo / PDF) for hours or achievements — returns the stored key",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def evidence(
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(HOURS_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.file_service import FileService

    saved = await FileService(db).save(
        file,
        "activity_evidence",
        allowed_types=("application/pdf", "image/jpeg", "image/png", "image/webp"),
        max_mb=10,
        institution_id=principal.institution_id,
    )
    return ok({"evidence_url": saved.key})


@router.get("/activity-hours/me", summary="My hours", response_model=Envelope[list[ActHourOut]], dependencies=CORE)
async def my_hours(
    request: Request, principal: Principal = Depends(HOURS_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).my_hours())


@router.post(
    "/activity-hours/bulk",
    summary="Bulk import (officers)",
    response_model=Envelope[ActVerifyResult],
    dependencies=CORE,
)
async def bulk(
    body: ActHourBulk, request: Request, principal: Principal = Depends(VERIFY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).bulk(body))


@router.post(
    "/activity-hours/verify",
    summary="Verify / reject hours",
    response_model=Envelope[ActVerifyResult],
    dependencies=CORE,
)
async def verify(
    body: ActVerify, request: Request, principal: Principal = Depends(VERIFY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).verify(body))


@router.get("/activity-hours/ledger", summary="Hours ledger", response_model=Envelope[ActLedger], dependencies=CORE)
async def ledger(
    request: Request,
    enrollment_id: uuid.UUID | None = None,
    principal: Principal = Depends(HOURS_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).ledger(enrollment_id))


@router.get(
    "/activity-hours/credit-eligible",
    summary="Students eligible for hours → credit mapping",
    response_model=Envelope[list[ActCreditEligible]],
    dependencies=CREDITS,
)
async def credit_eligible(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).credit_eligible(term_id))


# ---- achievements ---------------------------------------------------------------------------------------------------------
@router.get(
    "/achievements",
    summary="Achievements (ScopeTabs: department / all)",
    response_model=Envelope[list[AchOut]],
    dependencies=ACH,
)
async def achievements(
    request: Request,
    category: str | None = None,
    level: str | None = None,
    verified: bool | None = None,
    department_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ClubService(db, principal, request)
    res = ok(await svc.list_achievements(category, level, verified, department_id, scope))
    res["meta"]["visibility"] = svc.visibility(self_tab=False, own_tab=True)
    return res


@router.post(
    "/achievements", status_code=201, summary="Submit an achievement", response_model=Envelope[AchOut], dependencies=ACH
)
async def submit(
    body: AchCreate, request: Request, principal: Principal = Depends(HOURS_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).submit_achievement(body), message="Submitted")


@router.get("/achievements/me", summary="My achievements", response_model=Envelope[list[AchOut]], dependencies=ACH)
async def my_achievements(
    request: Request, principal: Principal = Depends(HOURS_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).my_achievements())


@router.post(
    "/achievements/{id}/verify", summary="Verify an achievement", response_model=Envelope[AchOut], dependencies=ACH
)
async def verify_achievement(
    id: uuid.UUID,
    body: AchVerify,
    request: Request,
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ClubService(db, principal, request).verify_achievement(id, body), message="Verified")


# ---- stats ----------------------------------------------------------------------------------------------------------------
@router.get(
    "/student-support/stats",
    summary="Student-support statistics (IQAC / readers)",
    response_model=Envelope[SupportStats],
    dependencies=SUPPORT,
)
async def stats(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(STATS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StatsService(db, principal, request).stats(term_id))
