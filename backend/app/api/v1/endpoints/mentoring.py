"""Mentoring & early warning — Prompts/27 §27.8: assignments / load / mentees / 360° {mentoring.core}, slots and
bookings {mentoring.appointment_slots}, sessions {mentoring.core}, referrals {mentoring.counselling}, risk flags
{mentoring.early_warning}. Ownership (mentor / class advisor), department / college / institution scope and
confidentiality are enforced by the services.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.mentoring import (
    MentActionItemUpdate,
    MentAssignmentCreate,
    MentAssignmentOut,
    MentAssignSummary,
    MentBookingOut,
    MentBulkAssign,
    MentLoadReport,
    MentMyMentor,
    MentProfile360,
    MentReassign,
    MentReferralCounts,
    MentReferralCreate,
    MentReferralOut,
    MentReferralUpdate,
    MentSessionCreate,
    MentSessionOut,
    MentSessionUpdate,
    MentSlotBook,
    MentSlotCreate,
    MentSlotOut,
    RiskAcknowledge,
    RiskFlagOut,
    RiskHeatCell,
    RiskRunRequest,
)
from app.services.student_support.mentoring_service import MentoringService
from app.services.student_support.risk_service import RiskService
from app.utils.response import ok

router = APIRouter(tags=["mentoring"])

M = "mentoring"
SELF = any_permission_required((M, "self"), (M, "wards"), (M, "manage"), (M, "view_all"), (M, "view"))
STAFF = any_permission_required((M, "manage"), (M, "view_all"))
WRITE = any_permission_required((M, "manage"))
REFER = any_permission_required((M, "refer"), (M, "manage"), ("facilities", "counsel"))
RISK = any_permission_required((M, "manage"), (M, "view_all"))
RISK_SELF = any_permission_required((M, "self"), (M, "manage"), (M, "view_all"))

CORE = [feature_required("mentoring.core")]
SLOTS = [feature_required("mentoring.appointment_slots")]
COUNSEL = [feature_required("mentoring.counselling")]
EARLY = [feature_required("mentoring.early_warning")]


def _vis(data: Any, svc: MentoringService | RiskService, *, self_tab: bool = False) -> dict[str, Any]:
    res = ok(data)
    res["meta"]["visibility"] = svc.visibility(self_tab=self_tab, own_tab=True)
    return res


# ---- assignments --------------------------------------------------------------------------------------------------------
@router.get(
    "/mentoring/assignments",
    summary="Mentor assignments (ScopeTabs)",
    response_model=Envelope[list[MentAssignmentOut]],
    dependencies=CORE,
)
async def assignments(
    request: Request,
    term_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    mentor_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = MentoringService(db, principal, request)
    return _vis(await svc.list_assignments(term_id, department_id, mentor_id, scope), svc)


@router.post(
    "/mentoring/assignments",
    status_code=201,
    summary="Assign a mentor (409 when already assigned this term)",
    response_model=Envelope[list[MentAssignmentOut]],
    dependencies=CORE,
)
async def assign(
    body: MentAssignmentCreate,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).create_assignments(body), message="Assigned")


@router.post(
    "/mentoring/assignments/bulk",
    summary="Bulk assign by rule (preview inline; otherwise job mentoring.bulk_assign)",
    response_model=Envelope[MentAssignSummary],
    dependencies=CORE,
)
async def assign_bulk(
    body: MentBulkAssign, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> Any:
    svc = MentoringService(db, principal, request)
    if body.preview:
        return ok(await svc.bulk_assign(body))
    from app.core.jobs import enqueue

    await svc.bulk_assign(body.model_copy(update={"preview": True}))  # permission / scope check up front
    j = await enqueue(db, principal, "mentoring.bulk_assign", body.model_dump(mode="json"), queue="reports")
    return JSONResponse(status_code=202, content=ok({"job_id": str(j.id)}, message="Queued"))


@router.put(
    "/mentoring/assignments/{id}/reassign",
    summary="Reassign with reason (history kept)",
    response_model=Envelope[MentAssignmentOut],
    dependencies=CORE,
)
async def reassign(
    id: uuid.UUID,
    body: MentReassign,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).reassign(id, body), message="Reassigned")


@router.get(
    "/mentoring/load", summary="Mentor load & compliance", response_model=Envelope[MentLoadReport], dependencies=CORE
)
async def load(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).load(term_id))


@router.get("/mentoring/me", summary="My mentor (student)", response_model=Envelope[MentMyMentor], dependencies=CORE)
async def my_mentor(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).my_mentor())


@router.get(
    "/mentoring/wards",
    summary="Mentors of my wards (parent)",
    response_model=Envelope[list[MentMyMentor]],
    dependencies=CORE,
)
async def ward_mentors(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).ward_mentors())


@router.get(
    "/mentoring/mentees",
    summary="My mentees / advisees",
    response_model=Envelope[list[MentAssignmentOut]],
    dependencies=CORE,
)
async def mentees(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).mentees(term_id))


@router.get(
    "/mentoring/mentees/{enrollment_id}/360",
    summary="Mentee 360° (mentor / advisor / department)",
    response_model=Envelope[MentProfile360],
    dependencies=CORE,
)
async def mentee_360(
    enrollment_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).profile360(enrollment_id))


# ---- slots ----------------------------------------------------------------------------------------------------------------
@router.get(
    "/mentoring/slots",
    summary="My published slots (mentor)",
    response_model=Envelope[list[MentSlotOut]],
    dependencies=SLOTS,
)
async def my_slots(
    request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).my_slots())


@router.post(
    "/mentoring/slots",
    status_code=201,
    summary="Publish slots (optionally weekly recurring)",
    response_model=Envelope[list[MentSlotOut]],
    dependencies=SLOTS,
)
async def publish_slots(
    body: MentSlotCreate, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).publish_slots(body), message="Published")


@router.delete("/mentoring/slots/{id}", summary="Delete a slot", response_model=Envelope[dict], dependencies=SLOTS)
async def delete_slot(
    id: uuid.UUID, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await MentoringService(db, principal, request).delete_slot(id)
    return ok({"id": str(id)}, message="Deleted")


@router.get(
    "/mentoring/slots/available",
    summary="Available slots (default: my mentor)",
    response_model=Envelope[list[MentSlotOut]],
    dependencies=SLOTS,
)
async def available_slots(
    request: Request,
    mentor_id: uuid.UUID | None = None,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).available_slots(mentor_id))


@router.post(
    "/mentoring/slots/{id}/book",
    status_code=201,
    summary="Book a slot (student or guardian; capacity → 409)",
    response_model=Envelope[MentBookingOut],
    dependencies=SLOTS,
)
async def book_slot(
    id: uuid.UUID,
    body: MentSlotBook,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).book(id, body), message="Booked")


@router.post(
    "/mentoring/bookings/{id}/{action}",
    summary="Booking action: cancel | attended | no-show",
    response_model=Envelope[MentBookingOut],
    dependencies=SLOTS,
)
async def booking_action(
    id: uuid.UUID,
    action: str,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if action not in ("cancel", "attended", "no-show"):
        from app.services.student_support.common import not_found

        raise not_found("Action")
    return ok(await MentoringService(db, principal, request).booking_action(id, action))


# ---- sessions -------------------------------------------------------------------------------------------------------------
@router.get(
    "/mentoring/sessions",
    summary="Sessions of my mentees (confidential notes for the author only)",
    response_model=Envelope[list[MentSessionOut]],
    dependencies=CORE,
)
async def sessions(
    request: Request,
    assignment_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = MentoringService(db, principal, request)
    return _vis(await svc.list_sessions(assignment_id, scope), svc)


@router.post(
    "/mentoring/sessions",
    status_code=201,
    summary="Log a session",
    response_model=Envelope[MentSessionOut],
    dependencies=CORE,
)
async def log_session(
    body: MentSessionCreate, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).log_session(body), message="Logged")


@router.get(
    "/mentoring/sessions/me",
    summary="My sessions (student: non-confidential parts; guardian: shared summaries)",
    response_model=Envelope[list[MentSessionOut]],
    dependencies=CORE,
)
async def my_sessions(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).my_sessions())


@router.put(
    "/mentoring/sessions/{id}", summary="Update a session", response_model=Envelope[MentSessionOut], dependencies=CORE
)
async def update_session(
    id: uuid.UUID,
    body: MentSessionUpdate,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).update_session(id, body))


@router.put(
    "/mentoring/sessions/{id}/action-items/{idx}",
    summary="Tick an action item (mentor or the student)",
    response_model=Envelope[MentSessionOut],
    dependencies=CORE,
)
async def update_action_item(
    id: uuid.UUID,
    idx: int,
    body: MentActionItemUpdate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).update_action_item(id, idx, body))


# ---- referrals ------------------------------------------------------------------------------------------------------------
@router.post(
    "/mentoring/referrals",
    status_code=201,
    summary="Refer to counselling",
    response_model=Envelope[MentReferralOut],
    dependencies=COUNSEL,
)
async def refer(
    body: MentReferralCreate,
    request: Request,
    principal: Principal = Depends(REFER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).refer(body), message="Referred")


@router.get(
    "/mentoring/referrals",
    summary="Referrals (counsellor: detail; referrer: own status; readers: counts only)",
    response_model=Envelope[list[MentReferralOut] | MentReferralCounts],
    dependencies=COUNSEL,
)
async def referrals(
    request: Request,
    status: str | None = None,
    mine: bool = False,
    principal: Principal = Depends(REFER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).list_referrals(status, mine))


@router.put(
    "/mentoring/referrals/{id}",
    summary="Counsellor update (accept / book appointment with consent / close)",
    response_model=Envelope[MentReferralOut],
    dependencies=COUNSEL,
)
async def update_referral(
    id: uuid.UUID,
    body: MentReferralUpdate,
    request: Request,
    principal: Principal = Depends(REFER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MentoringService(db, principal, request).update_referral(id, body))


# ---- risk -----------------------------------------------------------------------------------------------------------------
@router.post("/risk/compute", status_code=202, summary="Compute risk flags (job risk.compute)", dependencies=EARLY)
async def risk_compute(
    body: RiskRunRequest, request: Request, principal: Principal = Depends(RISK), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    svc = RiskService(db, principal, request)
    term = await svc.term_or_current(body.term_id)
    payload = body.model_copy(update={"term_id": term.id}).model_dump(mode="json")
    j = await enqueue(db, principal, "risk.compute", payload, queue="reports")
    return JSONResponse(status_code=202, content=ok({"job_id": str(j.id), "term_id": str(term.id)}, message="Queued"))


@router.get(
    "/risk/flags",
    summary="Risk flags (ScopeTabs: own mentees / department / all)",
    response_model=Envelope[list[RiskFlagOut]],
    dependencies=EARLY,
)
async def risk_flags(
    request: Request,
    term_id: uuid.UUID | None = None,
    level: str | None = None,
    department_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(RISK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = RiskService(db, principal, request)
    return _vis(await svc.flags(term_id, level, department_id, scope), svc)


@router.get(
    "/risk/heatmap", summary="Risk by department", response_model=Envelope[list[RiskHeatCell]], dependencies=EARLY
)
async def risk_heatmap(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(RISK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RiskService(db, principal, request).heatmap(term_id))


@router.get(
    "/risk/flags/me",
    summary="My risk level (when risk.show_to_student)",
    response_model=Envelope[list[RiskFlagOut]],
    dependencies=EARLY,
)
async def risk_me(
    request: Request, principal: Principal = Depends(RISK_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RiskService(db, principal, request).my_flag())


@router.post(
    "/risk/flags/{id}/acknowledge",
    summary="Acknowledge with action (mentor / HOD)",
    response_model=Envelope[RiskFlagOut],
    dependencies=EARLY,
)
async def risk_ack(
    id: uuid.UUID,
    body: RiskAcknowledge,
    request: Request,
    principal: Principal = Depends(RISK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RiskService(db, principal, request).acknowledge(id, body), message="Acknowledged")
