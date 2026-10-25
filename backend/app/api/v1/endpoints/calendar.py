"""Calendar — Prompts/25 §25.8 (calendar block).

Merged calendar / manual entries / PDF {calendar.core}; personal feed token {calendar.personal_feed}. ``public_router``
serves the institution / college ``.ics`` ({calendar.ical} checked inside) and the personal feed by token
(``PUBLIC_ROUTES``).
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.calendar import (
    CalendarDeadline,
    CalendarEventIn,
    CalendarEventOut,
    CalendarFeedTokenOut,
    CalendarJobAccepted,
    CalendarOut,
)
from app.schemas.common import Envelope
from app.services.facilities.calendar_service import CalendarService, personal_ics, public_ics
from app.utils.response import ok

router = APIRouter(tags=["calendar"])
public_router = APIRouter(tags=["calendar"])

C = "calendar"
VIEW = any_permission_required((C, "view"), (C, "view_all"), (C, "manage"))
MANAGE = any_permission_required((C, "manage"))
CORE = [feature_required("calendar.core")]
FEED = [feature_required("calendar.personal_feed")]
ICS = "text/calendar; charset=utf-8"


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get(
    "/calendar",
    summary="Merged calendar (sources + manual entries)",
    response_model=Envelope[CalendarOut],
    dependencies=CORE,
)
async def calendar_view(
    request: Request,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    types: list[str] | None = Query(None),
    college_id: uuid.UUID | None = None,
    scope: str = "mine",
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CalendarService(db, principal, request).view(date_from, date_to, types, college_id, scope))


@router.get(
    "/calendar/deadlines",
    summary="Upcoming deadlines (Home widget)",
    response_model=Envelope[list[CalendarDeadline]],
    dependencies=CORE,
)
async def calendar_deadlines(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CalendarService(db, principal, request).deadlines())


@router.get(
    "/calendar/events",
    summary="Manual calendar entries",
    response_model=Envelope[list[CalendarEventOut]],
    dependencies=CORE,
)
async def calendar_events(
    request: Request,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CalendarService(db, principal, request).list_manual(date_from, date_to))


@router.post(
    "/calendar/events",
    status_code=201,
    summary="Create a calendar entry",
    response_model=Envelope[CalendarEventOut],
    dependencies=CORE,
)
async def calendar_event_create(
    body: CalendarEventIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CalendarService(db, principal, request).create(body), message="Created")


@router.put(
    "/calendar/events/{id}",
    summary="Edit a calendar entry",
    response_model=Envelope[CalendarEventOut],
    dependencies=CORE,
)
async def calendar_event_update(
    id: uuid.UUID,
    body: CalendarEventIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CalendarService(db, principal, request).update(id, body))


@router.delete(
    "/calendar/events/{id}",
    summary="Delete a calendar entry",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def calendar_event_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await CalendarService(db, principal, request).delete(id)
    return ok({"deleted": True})


@router.get(
    "/calendar/pdf",
    status_code=202,
    summary="Academic calendar PDF (job)",
    response_model=Envelope[CalendarJobAccepted],
    dependencies=CORE,
)
async def calendar_pdf(
    request: Request,
    academic_year_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(
        db, principal, "calendar.pdf", {"academic_year_id": str(academic_year_id) if academic_year_id else None}
    )
    return JSONResponse(
        status_code=202, content=ok(CalendarJobAccepted(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


@router.post(
    "/calendar/feed-token",
    summary="Create my personal iCal feed",
    response_model=Envelope[CalendarFeedTokenOut],
    dependencies=FEED,
)
async def feed_token(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CalendarService(db, principal, request).create_token(_base_url(request)), message="Feed created")


@router.delete(
    "/calendar/feed-token",
    summary="Revoke my personal iCal feed",
    response_model=Envelope[CalendarFeedTokenOut],
    dependencies=FEED,
)
async def feed_token_revoke(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CalendarService(db, principal, request).revoke_token())


# ---- public ----------------------------------------------------------------------------------------------------------------
@public_router.get("/calendar/feed/{token}.ics", summary="Personal iCal feed (public with token)")
async def personal_feed(token: str) -> Response:
    body = await personal_ics(token)
    if body is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown or revoked feed")
    return Response(content=body, media_type=ICS)


@public_router.get("/calendar/ical/institution.ics", summary="Institution iCal feed (public)")
async def institution_feed(institution: str = Query(min_length=2, max_length=60)) -> Response:
    body = await public_ics(institution_slug=institution)
    if body is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "No public calendar")
    return Response(content=body, media_type=ICS)


@public_router.get("/calendar/ical/college/{college_id}.ics", summary="College iCal feed (public)")
async def college_feed(college_id: uuid.UUID) -> Response:
    body = await public_ics(college_id=college_id)
    if body is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "No public calendar")
    return Response(content=body, media_type=ICS)
