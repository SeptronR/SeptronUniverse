"""Portals, PWA, notification centre, tours, contextual help and locale packs — Prompts/39 §39.8.

``router`` (authenticated, self only): ``/portal/*`` {persona feature, checked in the service}, ``/users/me``,
``/notifications/counts|mark-read|snooze|{id}|preferences|test`` {core.notifications_inapp; preferences
{comms.preferences}}, ``/announcements/me`` {comms.announcements}, ``/push/*`` {portals.pwa_push, comms.push},
``/tours/*`` {platform.guided_tours}, ``/help/context|helpful`` {platform.help_center}, ``/pwa/installed``.
``public_router`` (``PUBLIC_ROUTES``): manifest, PWA config, VAPID key, icons, locale packs (tenant from
``?institution=<slug>`` or the X-Institution header). ``well_known_router`` is mounted at the site root by
``main.py`` (``/.well-known/assetlinks.json``, ``/.well-known/apple-app-site-association``).
"""

import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, authenticated
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.db.session import get_db, get_platform_db
from app.schemas.common import Envelope
from app.schemas.communication import AnnouncementResponse
from app.schemas.portals import (
    ApprovalItem,
    HelpContextOut,
    HelpfulIn,
    HelpfulOut,
    InstallPing,
    LocalePackOut,
    MarkReadIn,
    MarkReadOut,
    MeUpdateIn,
    MeUpdateOut,
    MyCalendarOut,
    MyPaymentsOut,
    MyRequestsOut,
    NotificationCounts,
    NotificationDetail,
    NotificationTestIn,
    PortalConfigOut,
    PreferencesIn,
    PreferencesOut,
    PushSubscribeIn,
    PushSubscribeOut,
    PushTestOut,
    PushTestRequest,
    PushUnsubscribeIn,
    PwaConfigOut,
    SnoozeIn,
    TimelineItem,
    TourDef,
    TourStateIn,
    TourStateOut,
    UnifiedDocumentItem,
    VapidKeyOut,
    WardOut,
    WardSwitchIn,
)
from app.services.portals import pwa_service
from app.services.portals.aggregators import PortalAggregator
from app.services.portals.help_context_service import HelpContextService
from app.services.portals.i18n_service import locale_pack
from app.services.portals.notification_center_service import NotificationCenterService
from app.services.portals.portal_service import PortalService
from app.services.portals.tour_service import TourService
from app.utils.response import ok

router = APIRouter(tags=["portals"])
public_router = APIRouter(tags=["portals-public"])
well_known_router = APIRouter(tags=["portals-public"])
# included before the Phase 04 announcements router so ``/announcements/me`` is not captured by ``/announcements/{id}``
early_router = APIRouter(tags=["portals"])

AUTH = authenticated()
PREFS = [feature_required("comms.preferences")]
PUSH = [feature_required("portals.pwa_push"), feature_required("comms.push")]
TOURS = [feature_required("platform.guided_tours")]
HELP = [feature_required("platform.help_center")]


# ---- shell ----------------------------------------------------------------------------------------------------------
@router.get(
    "/portal/config",
    summary="Persona shell config (tabs / more / branding / language)",
    response_model=Envelope[PortalConfigOut],
)
async def portal_config(
    request: Request, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PortalService(db, principal, request).config())


@router.get(
    "/portal/wards",
    summary="Parent: consented wards",
    dependencies=[feature_required("portals.parent")],
    response_model=Envelope[list[WardOut]],
)
async def portal_wards(principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await PortalService(db, principal).ward_list())


@router.post(
    "/portal/wards/switch",
    summary="Parent: switch the active ward",
    dependencies=[feature_required("portals.parent")],
    response_model=Envelope[list[WardOut]],
)
async def portal_ward_switch(
    body: WardSwitchIn, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PortalService(db, principal).switch_ward(body.student_id), message="Ward switched")


@router.put("/users/me", summary="My language / timezone / theme", response_model=Envelope[MeUpdateOut])
async def update_me(
    body: MeUpdateIn, request: Request, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PortalService(db, principal, request).update_me(body), message="Saved")


# ---- unified pages (self / wards / ownership; ?scope is ignored) ----------------------------------------------------------
@router.get("/portal/me/requests", summary="My requests across modules", response_model=Envelope[MyRequestsOut])
async def my_requests(
    status: str | None = Query(None, pattern="^(draft|pending|in_progress|approved|rejected|completed|cancelled)$"),
    module: str | None = Query(None, max_length=40),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(AUTH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PortalAggregator(db, principal).my_requests(status, module, date_from, date_to))


@router.get("/portal/me/documents", summary="My issued documents", response_model=Envelope[list[UnifiedDocumentItem]])
async def my_documents(principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await PortalAggregator(db, principal).my_documents())


@router.get("/portal/me/payments", summary="My invoices, payments and refunds", response_model=Envelope[MyPaymentsOut])
async def my_payments(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    status: str | None = Query(None, max_length=20),
    principal: Principal = Depends(AUTH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PortalAggregator(db, principal).my_payments(date_from, date_to, status))


@router.get(
    "/portal/me/approvals",
    summary="Approval steps assigned to me",
    dependencies=[feature_required("workflow.engine")],
    response_model=Envelope[list[ApprovalItem]],
)
async def my_approvals(principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await PortalAggregator(db, principal).my_approvals())


@router.get("/portal/me/calendar", summary="My personal calendar", response_model=Envelope[MyCalendarOut])
async def my_calendar(
    request: Request,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(AUTH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PortalAggregator(db, principal, request).my_calendar(date_from, date_to))


@router.get("/portal/me/timeline", summary="My activity (last 90 days)", response_model=Envelope[list[TimelineItem]])
async def my_timeline(
    date_from: date | None = Query(None, alias="from"),
    principal: Principal = Depends(AUTH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PortalAggregator(db, principal).my_timeline(date_from))


# ---- notification centre --------------------------------------------------------------------------------------------
@router.get("/notifications/counts", summary="Unread by category", response_model=Envelope[NotificationCounts])
async def notification_counts(
    request: Request, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NotificationCenterService(db, principal, request).counts())


@router.post(
    "/notifications/mark-read", summary="Mark read (ids, or all / per category)", response_model=Envelope[MarkReadOut]
)
async def notification_mark_read(
    body: MarkReadIn, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NotificationCenterService(db, principal).mark_read(body))


@router.post(
    "/notifications/snooze",
    summary="Mute a category's push / e-mail for N hours",
    response_model=Envelope[NotificationCounts],
)
async def notification_snooze(
    body: SnoozeIn, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NotificationCenterService(db, principal).snooze(body), message="Snoozed")


@router.get(
    "/notifications/preferences",
    summary="Category × channel matrix, quiet hours, digest",
    dependencies=PREFS,
    response_model=Envelope[PreferencesOut],
)
async def notification_preferences(
    principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NotificationCenterService(db, principal).preferences())


@router.put(
    "/notifications/preferences",
    summary="Update the matrix (policy-locked cells → 422)",
    dependencies=PREFS,
    response_model=Envelope[PreferencesOut],
)
async def notification_preferences_update(
    body: PreferencesIn, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NotificationCenterService(db, principal).update_preferences(body), message="Preferences saved")


@router.post(
    "/notifications/test",
    summary="Send myself a test notification",
    dependencies=PREFS,
    response_model=Envelope[dict[str, Any]],
)
async def notification_test(
    body: NotificationTestIn, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NotificationCenterService(db, principal).test(body.category, list(body.channels)), message="Sent")


@router.get(
    "/notifications/{id}",
    summary="Open a notification (marks it read, returns the route)",
    response_model=Envelope[NotificationDetail],
)
async def notification_open(
    id: uuid.UUID, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NotificationCenterService(db, principal).open(id))


@early_router.get(
    "/announcements/me",
    summary="Announcements addressed to me (pending_ack: still to acknowledge)",
    dependencies=[feature_required("comms.announcements")],
    response_model=Envelope[list[AnnouncementResponse]],
)
async def my_announcements(
    request: Request,
    pending_ack: bool = False,
    principal: Principal = Depends(AUTH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.announcement_service import AnnouncementService

    return ok(await AnnouncementService(db, principal, request).mine(pending_ack))


# ---- push -----------------------------------------------------------------------------------------------------------
@router.post(
    "/push/subscribe",
    status_code=201,
    summary="Register this browser for web push",
    dependencies=PUSH,
    response_model=Envelope[PushSubscribeOut],
)
async def push_subscribe(
    body: PushSubscribeIn, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await pwa_service.PushService(db, principal).subscribe(body), message="Push enabled")


@router.delete("/push/subscribe", summary="Unregister this browser", dependencies=PUSH, response_model=Envelope[None])
async def push_unsubscribe(
    body: PushUnsubscribeIn, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await pwa_service.PushService(db, principal).unsubscribe(body.endpoint)
    return ok(None, message="Push disabled")


@router.post(
    "/push/test", summary="Send a test push to my browsers", dependencies=PUSH, response_model=Envelope[PushTestOut]
)
async def push_test(
    body: PushTestRequest, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await pwa_service.PushService(db, principal).test(body), message="Test push queued")


@router.post("/pwa/installed", summary="Install analytics ping", response_model=Envelope[None])
async def pwa_installed(
    body: InstallPing, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.core import events

    await events.emit(
        db,
        institution_id=principal.institution_id,
        event_type="pwa.installed",
        payload={"user_id": str(principal.id), "platform": body.platform, "outcome": body.outcome},
        aggregate_type="user",
        aggregate_id=principal.id,
        actor_user_id=principal.id,
    )
    return ok(None)


# ---- tours / help -----------------------------------------------------------------------------------------------------
@router.get(
    "/tours/definitions",
    summary="Tours for a route (role-filtered)",
    dependencies=TOURS,
    response_model=Envelope[list[TourDef]],
)
async def tour_definitions(
    route: str | None = Query(None, max_length=200),
    principal: Principal = Depends(AUTH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TourService(db, principal).definitions(route))


@router.get("/tours/state", summary="My tour progress", dependencies=TOURS, response_model=Envelope[TourStateOut])
async def tour_state(principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await TourService(db, principal).state())


@router.put(
    "/tours/state",
    summary="Complete / dismiss / reset a tour",
    dependencies=TOURS,
    response_model=Envelope[TourStateOut],
)
async def tour_state_update(
    body: TourStateIn, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TourService(db, principal).update(body))


@router.get(
    "/help/context",
    summary="Contextual article for a route",
    dependencies=HELP,
    response_model=Envelope[HelpContextOut],
)
async def help_context(
    route: str = Query(max_length=200), principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HelpContextService(db, principal).context(route))


@router.post(
    "/help/helpful/{slug}", summary="Was this helpful?", dependencies=HELP, response_model=Envelope[HelpfulOut]
)
async def help_helpful(
    slug: str, body: HelpfulIn | None = None, principal: Principal = Depends(AUTH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HelpContextService(db, principal).helpful(slug[:200], body.helpful if body else True))


# ---- public -----------------------------------------------------------------------------------------------------------
async def _tenant(request: Request, db: AsyncSession, institution: str | None) -> uuid.UUID | None:
    return await pwa_service.resolve_institution(db, institution, getattr(request.state, "institution_id", None))


@public_router.get("/public/manifest.json", summary="Web App Manifest per institution", response_model=None)
async def public_manifest(
    request: Request,
    institution: str | None = Query(None, max_length=60),
    db: AsyncSession = Depends(get_platform_db),
) -> JSONResponse:
    inst = await _tenant(request, db, institution)
    return JSONResponse(
        await pwa_service.manifest(db, inst),
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@public_router.get(
    "/public/pwa-config", summary="Service-worker strategy config", response_model=Envelope[PwaConfigOut]
)
async def public_pwa_config(
    request: Request,
    institution: str | None = Query(None, max_length=60),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    inst = await _tenant(request, db, institution)
    push = inst is not None and await is_enabled(inst, "portals.pwa_push")
    return ok(await pwa_service.pwa_config(db, inst, push))


@public_router.get("/public/push/vapid-key", summary="VAPID public key", response_model=Envelope[VapidKeyOut])
async def public_vapid_key(db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    key, configured = await pwa_service.vapid_public_key(db)
    return ok(VapidKeyOut(public_key=key, configured=configured))


@public_router.get(
    "/public/pwa-icons/{institution_id}/{size}.png", summary="PWA icon (institution logo)", response_model=None
)
async def public_pwa_icon(
    institution_id: uuid.UUID, size: int, db: AsyncSession = Depends(get_platform_db)
) -> RedirectResponse:
    if size not in (192, 512):
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown icon size")
    row = (await db.execute(text("SELECT logo_url FROM institutions WHERE id = :i"), {"i": institution_id})).first()
    return RedirectResponse((row[0] if row and row[0] else None) or "/icons/icon.svg", status_code=307)


@public_router.get(
    "/public/locales/{lng}.json", summary="Locale pack + institution overrides", response_model=Envelope[LocalePackOut]
)
async def public_locale(
    lng: str,
    request: Request,
    institution: str | None = Query(None, max_length=60),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    inst = await _tenant(request, db, institution)
    if inst is not None and not await is_enabled(inst, "i18n.web"):
        raise APIError(403, ErrorCode.FEATURE_DISABLED, "Feature 'i18n.web' is not enabled", {"feature": "i18n.web"})
    if not lng.isalpha() or len(lng) > 5:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown language")
    return ok(await locale_pack(db, inst, lng.lower()))


@well_known_router.get("/.well-known/assetlinks.json", summary="Android App Links", response_model=None)
async def assetlinks(db: AsyncSession = Depends(get_platform_db)) -> JSONResponse:
    links, _ = await pwa_service.association_files(db)
    return JSONResponse(links)


@well_known_router.get("/.well-known/apple-app-site-association", summary="iOS universal links", response_model=None)
async def apple_app_site_association(db: AsyncSession = Depends(get_platform_db)) -> JSONResponse:
    _, aasa = await pwa_service.association_files(db)
    return JSONResponse(aasa)
