"""Events — Prompts/25 §25.8 (events block) {events.core}; certificates {events.certificates}.

Registration honours ``Idempotency-Key``. ``public_router`` lists public events and takes external registrations
(tenant by institution slug; rate-limited; {events.core} checked inside — ``PUBLIC_ROUTES``).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.idempotency import idempotency_key, store
from app.core.rate_limit import rate_limited
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.events import (
    EventAction,
    EventAttendanceMark,
    EventCertificateRequest,
    EventCreate,
    EventJobAccepted,
    EventPublicOut,
    EventRegister,
    EventRegistrationOut,
    EventReport,
    EventReportIn,
    EventResponse,
    EventUpdate,
)
from app.services.facilities.common import visibility_scopes
from app.services.facilities.event_service import EventService
from app.utils.response import ok

router = APIRouter(tags=["events"])
public_router = APIRouter(tags=["events"])

E = "events"
VIEW = any_permission_required((E, "view"), (E, "view_all"), (E, "organise"), (E, "approve"), (E, "manage"))
ORGANISE = any_permission_required((E, "organise"), (E, "manage"))
CERTIFY = any_permission_required((E, "certify"), (E, "organise"), (E, "manage"))
CORE = [feature_required("events.core")]
CERTS = [feature_required("events.certificates")]


def _vis(principal: Principal, data: Any) -> dict[str, Any]:
    tabs = ["mine" if t == "self" else t for t in visibility_scopes(principal, "events")]
    res = ok(data)
    res["meta"]["visibility"] = {"self": True, "scopes": tabs, "default": tabs[-1] if tabs else "mine"}
    return res


@router.get("/events", summary="Events (scoped)", response_model=Envelope[list[EventResponse]], dependencies=CORE)
async def events_list(
    request: Request,
    status: str | None = None,
    event_type: str | None = None,
    scope: str | None = None,
    q: str | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(
        principal,
        await EventService(db, principal, request).list_events(status=status, event_type=event_type, scope=scope, q=q),
    )


@router.post(
    "/events", status_code=201, summary="Propose an event", response_model=Envelope[EventResponse], dependencies=CORE
)
async def events_create(
    body: EventCreate, request: Request, principal: Principal = Depends(ORGANISE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EventService(db, principal, request).create(body), message="Proposed")


@router.get(
    "/events/me",
    summary="My registrations, tickets and certificates",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=CORE,
)
async def events_me(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EventService(db, principal, request).my_events())


@router.get("/events/{id}", summary="Event", response_model=Envelope[EventResponse], dependencies=CORE)
async def events_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EventService(db, principal, request).get(id))


@router.put("/events/{id}", summary="Edit an event", response_model=Envelope[EventResponse], dependencies=CORE)
async def events_update(
    id: uuid.UUID,
    body: EventUpdate,
    request: Request,
    principal: Principal = Depends(ORGANISE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EventService(db, principal, request).update(id, body))


@router.post(
    "/events/{id}/action",
    summary="Submit / approve / reject / schedule / complete / cancel",
    response_model=Envelope[EventResponse],
    dependencies=CORE,
)
async def events_action(
    id: uuid.UUID,
    body: EventAction,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EventService(db, principal, request).action(id, body))


@router.get("/events/{id}/report", summary="Event report", response_model=Envelope[EventReport], dependencies=CORE)
async def events_report(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EventService(db, principal, request).report(id))


@router.put(
    "/events/{id}/report", summary="Save the event report", response_model=Envelope[EventReport], dependencies=CORE
)
async def events_report_save(
    id: uuid.UUID,
    body: EventReportIn,
    request: Request,
    principal: Principal = Depends(ORGANISE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EventService(db, principal, request).save_report(id, body))


@router.post(
    "/events/{id}/register",
    status_code=201,
    summary="Register (Idempotency-Key)",
    response_model=Envelope[EventRegistrationOut],
    dependencies=CORE,
)
async def events_register(
    id: uuid.UUID,
    body: EventRegister,
    request: Request,
    key: str | None = Depends(idempotency_key),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    res = ok(await EventService(db, principal, request).register(id, body), message="Registered")
    await store(request, res, db, 201)
    return res


@router.get(
    "/events/{id}/registrations",
    summary="Registrations (organiser)",
    response_model=Envelope[list[EventRegistrationOut]],
    dependencies=CORE,
)
async def events_registrations(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EventService(db, principal, request).registrations(id))


@router.post(
    "/events/{id}/attendance",
    summary="Mark attendance (QR or list)",
    response_model=Envelope[list[EventRegistrationOut]],
    dependencies=CORE,
)
async def events_attendance(
    id: uuid.UUID,
    body: EventAttendanceMark,
    request: Request,
    principal: Principal = Depends(ORGANISE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EventService(db, principal, request).attendance(id, body))


@router.post(
    "/events/{id}/certificates",
    status_code=202,
    summary="Issue certificates (job)",
    response_model=Envelope[EventJobAccepted],
    dependencies=CERTS,
)
async def events_certificates(
    id: uuid.UUID,
    body: EventCertificateRequest,
    request: Request,
    principal: Principal = Depends(CERTIFY),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    j = await EventService(db, principal, request).queue_certificates(id, body)
    return JSONResponse(
        status_code=202, content=ok(EventJobAccepted(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


@router.get("/events/{id}/registrations/{rid}/certificate", summary="Certificate PDF", dependencies=CERTS)
async def events_certificate_pdf(
    id: uuid.UUID,
    rid: uuid.UUID,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> Response:
    pdf = await EventService(db, principal, request).certificate_pdf(id, rid)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate-{rid}.pdf"'},
    )


# ---- public (website) ----------------------------------------------------------------------------------------------------
async def _tenant(db: AsyncSession, institution: str) -> uuid.UUID:
    from app.db.session import bind_tenant, set_tenant
    from app.services.inventory.vendor_service import tenant_by_slug

    iid = await tenant_by_slug(institution)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    if not await is_enabled(iid, "events.core"):
        raise APIError(
            403, ErrorCode.FEATURE_DISABLED, "Feature 'events.core' is not enabled", {"feature": "events.core"}
        )
    return iid


@public_router.get("/events/public", summary="Public events (website)", response_model=Envelope[list[EventPublicOut]])
async def events_public(
    request: Request, institution: str = Query(min_length=2, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    iid = await _tenant(db, institution)
    return ok(await EventService(db, None, request, iid).public_list())


@public_router.post(
    "/events/public/{id}/register",
    status_code=201,
    summary="External registration (website form)",
    response_model=Envelope[EventRegistrationOut],
    dependencies=[rate_limited("event_public_register", limit=10, window=600)],
)
async def events_public_register(
    id: uuid.UUID,
    body: EventRegister,
    request: Request,
    institution: str = Query(min_length=2, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    iid = await _tenant(db, institution)
    return ok(await EventService(db, None, request, iid).register_public(id, body), message="Registered")
