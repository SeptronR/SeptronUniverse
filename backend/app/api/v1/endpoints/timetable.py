"""Timetable & rooms — Prompts/10 §10.8 (router included with ``feature_required("timetable.core")``; sub-features
per route: {timetable.rooms}, {timetable.substitutions}, {timetable.auto_generate}, {timetable.ical}).

Auto-generation and exports answer ``202`` + ``job_id``; ``dry_run`` previews answer inline. ``public_router`` holds
the token-authenticated iCal feeds (``PUBLIC_ROUTES``). Fixed paths (``/timetables/view``, ``/timetables/me``,
``/timetables/ical/…``) are declared before ``/timetables/{id}``.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.db.session import get_db
from app.enums.timetable import RoomType, TimetableScope, TimetableStatus
from app.schemas.common import Envelope
from app.schemas.timetable import (
    AutoGenerateRequest,
    BuildingIn,
    BuildingOut,
    ClassSessionResponse,
    ConflictReport,
    EntryCreate,
    EntryResult,
    EntryUpdate,
    ExtraSessionCreate,
    ICalToken,
    PublishRequest,
    PublishSummary,
    RoomAvailability,
    RoomIn,
    RoomOut,
    SectionFeed,
    SessionCancel,
    SessionReschedule,
    SessionUpdate,
    SlotGroupReplace,
    SlotOut,
    SubstituteCandidate,
    SubstitutionCreate,
    SubstitutionDecision,
    SubstitutionResponse,
    TimetableCreate,
    TimetableResponse,
    WeeklyView,
)
from app.services.timetable.auto_generate_service import AutoGenerateService
from app.services.timetable.room_service import RoomService
from app.services.timetable.session_service import SessionService
from app.services.timetable.substitution_service import SubstitutionService
from app.services.timetable.timetable_service import TimetableService, ical_for_section, ical_for_token
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["timetable"])
public_router = APIRouter(tags=["public"])

TT_VIEW = any_permission_required(("timetable", "view"), ("timetable", "view_all"))
TT_WRITE = any_permission_required(("timetable", "update"), ("timetable", "manage"))
TT_CREATE = any_permission_required(("timetable", "create"), ("timetable", "manage"))
TT_PUBLISH = any_permission_required(("timetable", "publish"), ("timetable", "manage"))
TT_GENERATE = any_permission_required(("timetable", "generate"), ("timetable", "manage"))
TT_EXPORT = any_permission_required(("timetable", "export"), ("timetable", "create"), ("timetable", "manage"))
SUB_VIEW = any_permission_required(
    ("timetable", "substitute"), ("timetable", "approve"), ("timetable", "view_all"), ("timetable", "manage")
)
SUB_REQUEST = any_permission_required(("timetable", "substitute"), ("timetable", "manage"))
SUB_DECIDE = any_permission_required(("timetable", "approve"), ("timetable", "manage"))
SESS_VIEW = any_permission_required(
    ("attendance", "view"), ("attendance", "view_all"), ("attendance", "self"), ("attendance", "mark")
)
SESS_WRITE = any_permission_required(("attendance", "mark"), ("timetable", "manage"), ("timetable", "update"))
ROOMS = [feature_required("timetable.rooms")]
SUBS = [feature_required("timetable.substitutions")]
ICAL = [feature_required("timetable.ical")]
AUTO = [feature_required("timetable.auto_generate")]


def _queued(data: Any, message: str) -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(data, message=message))


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _version(if_match: str | None) -> int | None:
    if not if_match:
        return None
    try:
        return int(if_match.strip('W/"'))
    except ValueError:
        return None


# ---- buildings ------------------------------------------------------------------------------------------------------
@router.get("/buildings", summary="Buildings", dependencies=ROOMS, response_model=Envelope[list[BuildingOut]])
async def list_buildings(
    request: Request,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(TT_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RoomService(db, principal, request).list_buildings(college_id))


@router.post(
    "/buildings", status_code=201, summary="Create a building", dependencies=ROOMS, response_model=Envelope[BuildingOut]
)
async def create_building(
    body: BuildingIn, request: Request, principal: Principal = Depends(TT_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RoomService(db, principal, request).create_building(body), message="Building created")


@router.put("/buildings/{id}", summary="Update a building", dependencies=ROOMS, response_model=Envelope[BuildingOut])
async def update_building(
    id: uuid.UUID,
    body: BuildingIn,
    request: Request,
    principal: Principal = Depends(TT_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RoomService(db, principal, request).update_building(id, body), message="Building updated")


@router.delete("/buildings/{id}", summary="Delete a building", dependencies=ROOMS, response_model=Envelope[None])
async def delete_building(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TT_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await RoomService(db, principal, request).delete_building(id)
    return ok(None, message="Building deleted")


# ---- rooms ------------------------------------------------------------------------------------------------------------
@router.get("/rooms", summary="Rooms", dependencies=ROOMS, response_model=Envelope[list[RoomOut]])
async def list_rooms(
    request: Request,
    college_id: uuid.UUID | None = None,
    building_id: uuid.UUID | None = None,
    room_type: RoomType | None = None,
    min_capacity: int | None = Query(default=None, ge=0),
    bookable: bool | None = None,
    q: str | None = Query(default=None, max_length=60),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(TT_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page = await RoomService(db, principal, request).list_rooms(
        params,
        college_id=college_id,
        building_id=building_id,
        room_type=room_type.value if room_type else None,
        min_capacity=min_capacity,
        bookable=bookable,
        q=q,
    )
    return ok(rows, pagination=page)


@router.get(
    "/rooms/availability",
    summary="Free / busy rooms at a date × slot",
    dependencies=ROOMS,
    response_model=Envelope[list[RoomAvailability]],
)
async def room_availability(
    request: Request,
    date: date,
    slot_id: uuid.UUID,
    type: RoomType | None = None,
    college_id: uuid.UUID | None = None,
    min_capacity: int | None = Query(default=None, ge=0),
    principal: Principal = Depends(TT_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RoomService(db, principal, request).availability(
            date, slot_id, type.value if type else None, college_id, min_capacity
        )
    )


@router.post("/rooms", status_code=201, summary="Create a room", dependencies=ROOMS, response_model=Envelope[RoomOut])
async def create_room(
    body: RoomIn, request: Request, principal: Principal = Depends(TT_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RoomService(db, principal, request).create_room(body), message="Room created")


@router.get("/rooms/{id}", summary="Room", dependencies=ROOMS, response_model=Envelope[RoomOut])
async def get_room(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RoomService(db, principal, request).get_room(id))


@router.put(
    "/rooms/{id}", summary="Update a room (If-Match: version)", dependencies=ROOMS, response_model=Envelope[RoomOut]
)
async def update_room(
    id: uuid.UUID,
    body: RoomIn,
    request: Request,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(TT_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RoomService(db, principal, request).update_room(id, body, _version(if_match)), message="Room updated"
    )


@router.delete("/rooms/{id}", summary="Delete a room", dependencies=ROOMS, response_model=Envelope[None])
async def delete_room(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TT_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await RoomService(db, principal, request).delete_room(id)
    return ok(None, message="Room deleted")


# ---- slots ------------------------------------------------------------------------------------------------------------
@router.get("/time-slots", summary="Time slots of a slot group", response_model=Envelope[list[SlotOut]])
async def list_slots(
    request: Request,
    slot_group: str | None = Query(default=None, max_length=40),
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(TT_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RoomService(db, principal, request).list_slots(college_id, slot_group))


@router.put(
    "/time-slots", summary="Replace a slot group (ordered, non-overlapping)", response_model=Envelope[list[SlotOut]]
)
async def replace_slots(
    body: SlotGroupReplace,
    request: Request,
    principal: Principal = Depends(TT_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RoomService(db, principal, request).replace_group(body), message="Slot group saved")


# ---- timetables: fixed paths first ------------------------------------------------------------------------------------
@router.get("/timetables/view", summary="Weekly view of a scope", response_model=Envelope[WeeklyView])
async def weekly_view(
    request: Request,
    scope: str = Query(pattern="^(section|batch|department|faculty|room)$"),
    id: uuid.UUID = Query(),
    week: date | None = None,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(TT_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).weekly(scope, id, week, term_id=term_id))


@router.get(
    "/timetables/me", summary="My week (faculty / student; parents pass ward_id)", response_model=Envelope[WeeklyView]
)
async def my_timetable(
    request: Request,
    week: date | None = None,
    ward_id: uuid.UUID | None = None,
    principal: Principal = Depends(TT_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).my_week(week, ward_id))


@router.post(
    "/timetables/ical/token",
    summary="Create my iCal feed token (revokes the previous one)",
    dependencies=ICAL,
    response_model=Envelope[ICalToken],
)
async def ical_token(
    request: Request, principal: Principal = Depends(TT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).create_token(_base_url(request)), message="Feed created")


@router.delete(
    "/timetables/ical/token", summary="Revoke my iCal feed", dependencies=ICAL, response_model=Envelope[ICalToken]
)
async def ical_revoke(
    request: Request, principal: Principal = Depends(TT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).revoke_token(), message="Feed revoked")


@router.post(
    "/timetables/sections/{id}/ical-link",
    summary="Signed iCal link of a section",
    dependencies=ICAL,
    response_model=Envelope[SectionFeed],
)
async def section_ical_link(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).section_feed(id, _base_url(request)))


# ---- timetables --------------------------------------------------------------------------------------------------------
@router.get("/timetables", summary="Timetables (versions per scope)", response_model=Envelope[list[TimetableResponse]])
async def list_timetables(
    request: Request,
    term_id: uuid.UUID | None = None,
    college_id: uuid.UUID | None = None,
    scope_type: TimetableScope | None = None,
    scope_id: uuid.UUID | None = None,
    status: TimetableStatus | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(TT_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page = await TimetableService(db, principal, request).list_page(
        params,
        term_id=term_id,
        college_id=college_id,
        scope_type=scope_type.value if scope_type else None,
        scope_id=scope_id,
        status=status.value if status else None,
    )
    return ok(rows, pagination=page)


@router.post(
    "/timetables",
    status_code=201,
    summary="Create a draft (optionally from a version)",
    response_model=Envelope[TimetableResponse],
)
async def create_timetable(
    body: TimetableCreate,
    request: Request,
    principal: Principal = Depends(TT_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).create(body), message="Draft created")


@router.get("/timetables/{id}", summary="Timetable with entries", response_model=Envelope[TimetableResponse])
async def get_timetable(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).get(id))


@router.post(
    "/timetables/{id}/clone",
    status_code=201,
    summary="Clone into a new draft version",
    response_model=Envelope[TimetableResponse],
)
async def clone_timetable(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TT_CREATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).clone(id), message="New draft version")


@router.delete("/timetables/{id}", summary="Delete a draft", response_model=Envelope[None])
async def delete_timetable(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TT_CREATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await TimetableService(db, principal, request).delete(id)
    return ok(None, message="Draft deleted")


@router.post(
    "/timetables/{id}/entries",
    status_code=201,
    summary="Add an entry (conflict pre-check)",
    response_model=Envelope[EntryResult],
)
async def add_entry(
    id: uuid.UUID,
    body: EntryCreate,
    request: Request,
    principal: Principal = Depends(TT_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).add_entry(id, body), message="Entry added")


@router.put("/timetables/{id}/entries/{eid}", summary="Update an entry", response_model=Envelope[EntryResult])
async def update_entry(
    id: uuid.UUID,
    eid: uuid.UUID,
    body: EntryUpdate,
    request: Request,
    principal: Principal = Depends(TT_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).update_entry(id, eid, body), message="Entry updated")


@router.delete("/timetables/{id}/entries/{eid}", summary="Delete an entry", response_model=Envelope[None])
async def delete_entry(
    id: uuid.UUID,
    eid: uuid.UUID,
    request: Request,
    principal: Principal = Depends(TT_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await TimetableService(db, principal, request).delete_entry(id, eid)
    return ok(None, message="Entry deleted")


@router.post(
    "/timetables/{id}/check-conflicts",
    summary="Conflict report for a candidate entry (or the whole draft without a body)",
    response_model=Envelope[ConflictReport],
)
async def check_conflicts(
    id: uuid.UUID,
    request: Request,
    body: EntryCreate | None = Body(default=None),
    principal: Principal = Depends(TT_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).check_conflicts(id, body))


@router.post(
    "/timetables/{id}/publish", summary="Publish (+ generate sessions)", response_model=Envelope[PublishSummary]
)
async def publish(
    id: uuid.UUID,
    request: Request,
    body: PublishRequest = Body(default_factory=PublishRequest),
    principal: Principal = Depends(TT_PUBLISH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await TimetableService(db, principal, request).publish(id, body)
    return ok(out, message="Timetable published")


@router.post(
    "/timetables/{id}/archive", summary="Archive the published version", response_model=Envelope[TimetableResponse]
)
async def archive(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TT_PUBLISH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TimetableService(db, principal, request).archive(id), message="Timetable archived")


@router.post(
    "/timetables/{id}/auto-generate",
    summary="Auto-generate entries into a draft (dry_run → preview; else job)",
    dependencies=AUTO,
    response_model=Envelope[dict[str, Any]],
)
async def auto_generate(
    id: uuid.UUID,
    request: Request,
    body: AutoGenerateRequest = Body(default_factory=AutoGenerateRequest),
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(TT_GENERATE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if dry_run:
        return ok(await AutoGenerateService(db, principal, request).run(id, body, dry_run=True))
    from app.core.jobs import enqueue

    await TimetableService(db, principal, request).tts.get_one(id)
    job = await enqueue(db, principal, "timetable.auto_generate", {"timetable_id": str(id), "body": body.model_dump()})
    return _queued({"job_id": str(job.id)}, "Auto-generation queued")


@router.get(
    "/timetables/{id}/export", summary="Export the entries as CSV (job)", response_model=Envelope[dict[str, Any]]
)
async def export_timetable(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TT_EXPORT), db: AsyncSession = Depends(get_db)
) -> Any:
    from app.core.jobs import enqueue

    await TimetableService(db, principal, request).tts.get_one(id)
    job = await enqueue(db, principal, "timetable.export", {"timetable_id": str(id)})
    return _queued({"job_id": str(job.id)}, "Export queued")


# ---- substitutions -------------------------------------------------------------------------------------------------------
@router.get(
    "/substitutions",
    summary="Substitution queue",
    dependencies=SUBS,
    response_model=Envelope[list[SubstitutionResponse]],
)
async def list_substitutions(
    request: Request,
    status: str | None = Query(default=None, pattern="^(requested|approved|rejected|withdrawn)$"),
    source: str | None = Query(default=None, pattern="^(manual|leave_auto)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    scope: str | None = Query(default=None, pattern="^(mine|self|own|department|all)$"),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(SUB_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await SubstitutionService(db, principal, request).list_page(
        params, scope, status=status, source=source, date_from=date_from, date_to=date_to
    )
    return ok(rows, pagination=page, visibility=vis)


@router.post(
    "/substitutions",
    status_code=201,
    summary="Request a substitution",
    dependencies=SUBS,
    response_model=Envelope[SubstitutionResponse],
)
async def create_substitution(
    body: SubstitutionCreate,
    request: Request,
    principal: Principal = Depends(SUB_REQUEST),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SubstitutionService(db, principal, request).create(body), message="Substitution requested")


@router.get(
    "/substitutions/{id}/candidates",
    summary="Substitute candidates with availability",
    dependencies=SUBS,
    response_model=Envelope[list[SubstituteCandidate]],
)
async def substitution_candidates(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SUB_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SubstitutionService(db, principal, request).candidates(id))


@router.post(
    "/substitutions/{id}/approve",
    summary="Approve (swap the session staff)",
    dependencies=SUBS,
    response_model=Envelope[SubstitutionResponse],
)
async def approve_substitution(
    id: uuid.UUID,
    request: Request,
    body: SubstitutionDecision = Body(default_factory=SubstitutionDecision),
    principal: Principal = Depends(SUB_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SubstitutionService(db, principal, request).approve(id, body), message="Substitution approved")


@router.post(
    "/substitutions/{id}/reject", summary="Reject", dependencies=SUBS, response_model=Envelope[SubstitutionResponse]
)
async def reject_substitution(
    id: uuid.UUID,
    request: Request,
    body: SubstitutionDecision = Body(default_factory=SubstitutionDecision),
    principal: Principal = Depends(SUB_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SubstitutionService(db, principal, request).reject(id, body), message="Substitution rejected")


@router.post(
    "/substitutions/{id}/withdraw", summary="Withdraw", dependencies=SUBS, response_model=Envelope[SubstitutionResponse]
)
async def withdraw_substitution(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SUB_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SubstitutionService(db, principal, request).withdraw(id), message="Substitution withdrawn")


# ---- class sessions -----------------------------------------------------------------------------------------------------
@router.get("/class-sessions", summary="Class sessions", response_model=Envelope[list[ClassSessionResponse]])
async def list_sessions(
    request: Request,
    offering_id: uuid.UUID | None = None,
    date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    staff_id: uuid.UUID | None = None,
    section_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(scheduled|conducted|cancelled|rescheduled)$"),
    scope: str | None = Query(default=None, pattern="^(self|own|mine|department|faculty|college|all)$"),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(SESS_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await SessionService(db, principal, request).list_page(
        params,
        scope,
        section_id=section_id,
        offering_id=offering_id,
        on=date,
        date_from=date_from,
        date_to=date_to,
        staff_id=staff_id,
        room_id=room_id,
        status=status,
    )
    return ok(rows, pagination=page, visibility=vis)


@router.get("/class-sessions/today", summary="My sessions today", response_model=Envelope[list[ClassSessionResponse]])
async def sessions_today(
    request: Request, principal: Principal = Depends(SESS_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SessionService(db, principal, request).today_sessions())


@router.post(
    "/class-sessions/extra",
    status_code=201,
    summary="Extra / remedial session",
    response_model=Envelope[ClassSessionResponse],
)
async def extra_session(
    body: ExtraSessionCreate,
    request: Request,
    principal: Principal = Depends(SESS_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SessionService(db, principal, request).extra(body), message="Session created")


@router.get("/class-sessions/{id}", summary="Class session", response_model=Envelope[ClassSessionResponse])
async def get_session(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SESS_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SessionService(db, principal, request).get(id))


@router.put(
    "/class-sessions/{id}", summary="Update topic / room / link / status", response_model=Envelope[ClassSessionResponse]
)
async def update_session(
    id: uuid.UUID,
    body: SessionUpdate,
    request: Request,
    principal: Principal = Depends(SESS_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SessionService(db, principal, request).update(id, body), message="Session updated")


@router.post(
    "/class-sessions/{id}/cancel", summary="Cancel (attendance not taken)", response_model=Envelope[ClassSessionResponse]
)
async def cancel_session(
    id: uuid.UUID,
    request: Request,
    body: SessionCancel = Body(default_factory=SessionCancel),
    principal: Principal = Depends(SESS_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SessionService(db, principal, request).cancel(id, body), message="Session cancelled")


@router.post(
    "/class-sessions/{id}/reschedule",
    summary="Reschedule (attendance not taken)",
    response_model=Envelope[ClassSessionResponse],
)
async def reschedule_session(
    id: uuid.UUID,
    body: SessionReschedule,
    request: Request,
    principal: Principal = Depends(SESS_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SessionService(db, principal, request).reschedule(id, body), message="Session rescheduled")


# ---- public iCal feeds (token-authenticated; PUBLIC_ROUTES) --------------------------------------------------------------
ICS = "text/calendar; charset=utf-8"


@public_router.get("/timetables/ical/{token}.ics", summary="Personal iCal feed (public with token)")
async def ical_feed(token: str) -> Response:
    body = await ical_for_token(token)
    if body is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown or revoked feed")
    return Response(content=body, media_type=ICS)


@public_router.get("/timetables/sections/{id}.ics", summary="Section iCal feed (public with signed token)")
async def section_feed(id: uuid.UUID, token: str = Query(min_length=10)) -> Response:
    body = await ical_for_section(id, token)
    if body is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown or expired feed")
    return Response(content=body, media_type=ICS)
