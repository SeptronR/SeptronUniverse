"""Communication advanced — Prompts/24 §24.8.

Segments / campaigns {comms.bulk_campaigns} (schedule also {comms.scheduled_sends}), announcement analytics
{comms.announcement_ack}, emergency {comms.emergency_broadcast}, bot {comms.whatsapp_bot}, assistant {comms.ai_assistant},
simulator (non-production), analytics and *my messages*. Campaign actions honour ``Idempotency-Key``. ``public_router``
holds the WhatsApp webhook (verify-token GET + signed POST; tenant from the connection; ``PUBLIC_ROUTES``).
"""

import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.comms_advanced import (
    AckReminderRequest,
    AllClear,
    AnnouncementAnalytics,
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantConfig,
    AssistantMe,
    AssistantOptIn,
    BotFlowsPut,
    BotSessionOut,
    BotTestRequest,
    CampaignAction,
    CampaignCreate,
    CampaignReport,
    CampaignResponse,
    CampaignUpdate,
    CommsJobAccepted,
    ComplianceResult,
    DeliveryAnalyticsOut,
    EmergencyBroadcast,
    EmergencyLog,
    MyMessageOut,
    ProviderHealthOut,
    SavedSegmentIn,
    SavedSegmentOut,
    SegmentPreview,
    SegmentRules,
    SimInbound,
    SimProviderEvent,
    SimulatorInboxOut,
)
from app.services.comms_advanced.analytics_service import CommsAnalyticsService
from app.services.comms_advanced.assistant_service import AssistantService
from app.services.comms_advanced.bot_service import BotService
from app.services.comms_advanced.campaign_service import CampaignService
from app.services.comms_advanced.common import visibility_scopes
from app.services.comms_advanced.segment_service import SegmentService
from app.utils.response import ok

router = APIRouter(tags=["communication-advanced"])
public_router = APIRouter(tags=["communication-advanced"])

C = "communication"
SEND = any_permission_required((C, "bulk"), (C, "send"), (C, "approve"), (C, "view_all"))
BULK = any_permission_required((C, "bulk"))
EMERG = any_permission_required((C, "emergency"), (C, "view_all"))
BOT = any_permission_required((C, "template_manage"), (C, "bulk"), (C, "view_all"))
SELF = any_permission_required((C, "view"), (C, "send"), (C, "bulk"))
ADMIN = any_permission_required((C, "template_manage"), (C, "view_all"))
VIEW_ALL = any_permission_required((C, "view_all"), (C, "bulk"))

CAMPAIGNS = [feature_required("comms.bulk_campaigns")]
ACK = [feature_required("comms.announcement_ack")]
EMERGENCY = [feature_required("comms.emergency_broadcast")]
BOTF = [feature_required("comms.whatsapp_bot")]
ASSIST = [feature_required("comms.ai_assistant")]
CORE = [feature_required("comms.announcements")]


def _vis(principal: Principal, data: Any) -> dict[str, Any]:
    tabs = visibility_scopes(principal)
    res = ok(data)
    res.setdefault("meta", {})["visibility"] = {"self": True, "scopes": tabs, "default": tabs[-1] if tabs else "self"}
    return res


# ---- segments --------------------------------------------------------------------------------------------------------------
@router.get(
    "/comms/segments/fields",
    summary="Segment field catalogue",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=CAMPAIGNS,
)
async def segment_fields(
    request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(SegmentService(db, principal, request).fields())


@router.post(
    "/comms/segments/preview",
    summary="Preview a segment (count, reachability, sample)",
    response_model=Envelope[SegmentPreview],
    dependencies=CAMPAIGNS,
)
async def segment_preview(
    body: SegmentRules, request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SegmentService(db, principal, request).preview(body))


@router.get(
    "/comms/segments", summary="Saved segments", response_model=Envelope[list[SavedSegmentOut]], dependencies=CAMPAIGNS
)
async def segments(
    request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SegmentService(db, principal, request).saved())


@router.post(
    "/comms/segments",
    status_code=201,
    summary="Save a segment",
    response_model=Envelope[SavedSegmentOut],
    dependencies=CAMPAIGNS,
)
async def segment_save(
    body: SavedSegmentIn, request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SegmentService(db, principal, request).save(body))


@router.put(
    "/comms/segments/{id}",
    summary="Edit a saved segment",
    response_model=Envelope[SavedSegmentOut],
    dependencies=CAMPAIGNS,
)
async def segment_update(
    id: uuid.UUID,
    body: SavedSegmentIn,
    request: Request,
    principal: Principal = Depends(SEND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SegmentService(db, principal, request).save(body, id))


@router.delete(
    "/comms/segments/{id}",
    summary="Delete a saved segment",
    response_model=Envelope[dict[str, Any]],
    dependencies=CAMPAIGNS,
)
async def segment_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await SegmentService(db, principal, request).delete(id)
    return ok({"id": str(id)})


# ---- campaigns ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/comms/campaigns",
    summary="Campaigns (ScopeTabs)",
    response_model=Envelope[list[CampaignResponse]],
    dependencies=CAMPAIGNS,
)
async def campaigns(
    request: Request,
    status: str | None = None,
    scope: str | None = Query(None, pattern="^(self|department|college|all)$"),
    principal: Principal = Depends(SEND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(principal, await CampaignService(db, principal, request).list_campaigns(status, scope))


@router.post(
    "/comms/campaigns",
    status_code=201,
    summary="Create a campaign (draft)",
    response_model=Envelope[CampaignResponse],
    dependencies=CAMPAIGNS,
)
async def campaign_create(
    body: CampaignCreate, request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CampaignService(db, principal, request).create(body))


@router.get(
    "/comms/campaigns/{id}",
    summary="Campaign (+ compliance)",
    response_model=Envelope[CampaignResponse],
    dependencies=CAMPAIGNS,
)
async def campaign_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CampaignService(db, principal, request).get(id))


@router.put(
    "/comms/campaigns/{id}",
    summary="Edit a draft campaign",
    response_model=Envelope[CampaignResponse],
    dependencies=CAMPAIGNS,
)
async def campaign_update(
    id: uuid.UUID,
    body: CampaignUpdate,
    request: Request,
    principal: Principal = Depends(SEND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CampaignService(db, principal, request).update(id, body))


@router.post(
    "/comms/campaigns/{id}/compliance-check",
    summary="DLT / WhatsApp / content compliance",
    response_model=Envelope[ComplianceResult],
    dependencies=CAMPAIGNS,
)
async def campaign_compliance(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = CampaignService(db, principal, request)
    return ok(await svc.compliance(await svc.row(id)))


@router.post(
    "/comms/campaigns/{id}/action",
    summary="submit | approve | reject | schedule | send_now | cancel | pause | resume | retry_failed (Idempotency-Key)",
    response_model=Envelope[CampaignResponse],
    dependencies=CAMPAIGNS,
)
async def campaign_action(
    id: uuid.UUID,
    body: CampaignAction,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(SEND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await CampaignService(db, principal, request).action(id, body)
    response = ok(out.model_dump(mode="json"), message=body.action)
    await store(request, response, db)
    return response


@router.get(
    "/comms/campaigns/{id}/report",
    summary="Campaign report",
    response_model=Envelope[CampaignReport],
    dependencies=CAMPAIGNS,
)
async def campaign_report(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CampaignService(db, principal, request).report(id))


@router.get(
    "/comms/campaigns/{id}/recipients",
    summary="Recipients by status (masked)",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=CAMPAIGNS,
)
async def campaign_recipients(
    id: uuid.UUID,
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(SEND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CampaignService(db, principal, request).recipients(id, status))


# ---- announcements -----------------------------------------------------------------------------------------------------------
@router.get(
    "/comms/announcements/{id}/analytics",
    summary="Read / acknowledgement funnel",
    response_model=Envelope[AnnouncementAnalytics],
    dependencies=ACK,
)
async def ann_analytics(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    out = await CampaignService(db, principal, request).analytics(id)
    out.pending = []
    return ok(out)


@router.get(
    "/comms/announcements/{id}/pending",
    summary="Who has not read / acknowledged (scoped)",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=ACK,
)
async def ann_pending(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SEND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok((await CampaignService(db, principal, request).analytics(id)).pending)


@router.post(
    "/comms/announcements/{id}/remind",
    summary="Reminder campaign to the pending audience",
    response_model=Envelope[CampaignResponse],
    dependencies=ACK,
)
async def ann_remind(
    id: uuid.UUID,
    body: AckReminderRequest,
    request: Request,
    principal: Principal = Depends(SEND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CampaignService(db, principal, request).remind(id, list(body.channels)))


# ---- emergency ---------------------------------------------------------------------------------------------------------------
@router.post(
    "/comms/emergency/broadcast",
    status_code=201,
    summary="Emergency broadcast (type BROADCAST to confirm)",
    response_model=Envelope[CampaignResponse],
    dependencies=EMERGENCY,
)
async def emergency_broadcast(
    body: EmergencyBroadcast,
    request: Request,
    principal: Principal = Depends(EMERG),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CampaignService(db, principal, request).emergency(body))


@router.post(
    "/comms/emergency/{id}/all-clear",
    summary="All-clear follow-up",
    response_model=Envelope[CampaignResponse],
    dependencies=EMERGENCY,
)
async def emergency_all_clear(
    id: uuid.UUID,
    body: AllClear,
    request: Request,
    principal: Principal = Depends(EMERG),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CampaignService(db, principal, request).all_clear(id, body.message))


@router.get(
    "/comms/emergency/log",
    summary="Emergency incident log",
    response_model=Envelope[list[EmergencyLog]],
    dependencies=EMERGENCY,
)
async def emergency_log(
    request: Request, principal: Principal = Depends(EMERG), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CampaignService(db, principal, request).emergency_log())


# ---- bot ---------------------------------------------------------------------------------------------------------------------
@router.get("/comms/bot/flows", summary="Bot menu flows", response_model=Envelope[dict[str, Any]], dependencies=BOTF)
async def bot_flows(
    request: Request, principal: Principal = Depends(BOT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BotService(db, principal, request).flows())


@router.put("/comms/bot/flows", summary="Edit bot flows", response_model=Envelope[dict[str, Any]], dependencies=BOTF)
async def bot_flows_put(
    body: BotFlowsPut, request: Request, principal: Principal = Depends(BOT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BotService(db, principal, request).put_flows(body))


@router.post(
    "/comms/bot/flows/{key}/test",
    summary="Test console (runs a message through the bot)",
    response_model=Envelope[dict[str, Any]],
    dependencies=BOTF,
)
async def bot_test(
    key: str,
    body: BotTestRequest,
    request: Request,
    principal: Principal = Depends(BOT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BotService(db, principal, request).test(body.message, body.as_user_id))


@router.get(
    "/comms/bot/me/sessions",
    summary="My bot conversations",
    response_model=Envelope[list[BotSessionOut]],
    dependencies=BOTF,
)
async def bot_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BotService(db, principal, request).my_sessions())


@router.get(
    "/comms/bot/sessions",
    summary="Bot sessions (masked)",
    response_model=Envelope[list[BotSessionOut]],
    dependencies=BOTF,
)
async def bot_sessions(
    request: Request, status: str | None = None, principal: Principal = Depends(BOT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BotService(db, principal, request).sessions(status))


@router.get(
    "/comms/bot/sessions/{id}",
    summary="Bot session (masked)",
    response_model=Envelope[BotSessionOut],
    dependencies=BOTF,
)
async def bot_session(
    id: uuid.UUID, request: Request, principal: Principal = Depends(BOT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BotService(db, principal, request).session(id))


@router.post(
    "/comms/bot/sessions/{id}/handoff-close",
    summary="Close a hand-off",
    response_model=Envelope[BotSessionOut],
    dependencies=BOTF,
)
async def bot_handoff_close(
    id: uuid.UUID, request: Request, principal: Principal = Depends(BOT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BotService(db, principal, request).close_handoff(id))


async def _connection(connection_id: uuid.UUID) -> tuple[uuid.UUID, dict[str, Any], str]:
    from sqlalchemy import text

    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as pdb:
        row = (
            await pdb.execute(
                text(
                    "SELECT institution_id, public_config, provider FROM integration_connections WHERE id = :i AND capability = 'whatsapp'"
                ),
                {"i": connection_id},
            )
        ).first()
    if row is None or row[0] is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown WhatsApp connection")
    return uuid.UUID(str(row[0])), dict(row[1] or {}), str(row[2] or "mock")


@public_router.get("/webhooks/whatsapp/{connection_id}", summary="WhatsApp webhook verification (hub.challenge)")
async def wa_verify(connection_id: uuid.UUID, request: Request) -> PlainTextResponse:
    _, conf, _ = await _connection(connection_id)
    qp = request.query_params
    if (
        qp.get("hub.mode") == "subscribe"
        and conf.get("verify_token")
        and hmac.compare_digest(str(qp.get("hub.verify_token") or ""), str(conf["verify_token"]))
    ):
        return PlainTextResponse(str(qp.get("hub.challenge") or ""))
    raise APIError(403, ErrorCode.PERMISSION_DENIED, "Verification failed")


@public_router.post("/webhooks/whatsapp/{connection_id}", summary="WhatsApp inbound messages (signed)")
async def wa_inbound(connection_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    from app.db.session import bind_tenant, set_tenant

    iid, conf, provider = await _connection(connection_id)
    raw = await request.body()
    if provider != "mock":
        secret = str(conf.get("app_secret") or "")
        sig = request.headers.get("X-Hub-Signature-256")
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not secret or not sig or not hmac.compare_digest(sig, expected):
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Bad signature")
    if not (await is_enabled(iid, "comms.whatsapp") and await is_enabled(iid, "comms.whatsapp_bot")):
        return JSONResponse({"ok": True, "ignored": "bot disabled"})
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    payload = json.loads(raw or b"{}")
    bot = BotService(db, None, request, iid)
    handled = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in (change.get("value") or {}).get("messages", []):
                text_in = (
                    (m.get("text") or {}).get("body")
                    or ((m.get("interactive") or {}).get("button_reply") or {}).get("title")
                    or ((m.get("interactive") or {}).get("list_reply") or {}).get("id")
                    or ""
                )
                if text_in:
                    await bot.handle(str(m.get("from", "")), text_in, str(m.get("id") or uuid.uuid4()))
                    handled += 1
    return JSONResponse({"ok": True, "handled": handled})


# ---- assistant ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/assistant/me",
    summary="Assistant availability and opt-in",
    response_model=Envelope[AssistantMe],
    dependencies=ASSIST,
)
async def assistant_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssistantService(db, principal, request).me())


@router.post(
    "/assistant/opt-in",
    summary="Opt in / out of the assistant",
    response_model=Envelope[AssistantMe],
    dependencies=ASSIST,
)
async def assistant_opt_in(
    body: AssistantOptIn, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssistantService(db, principal, request).opt_in(body.accepted))


@router.post(
    "/assistant/chat",
    summary="Ask the assistant (read-only tools under your permissions)",
    response_model=Envelope[AssistantChatResponse],
    dependencies=ASSIST,
)
async def assistant_chat(
    body: AssistantChatRequest,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    channel = "mobile" if request.headers.get("X-Client") == "mobile" else "web"
    return ok(await AssistantService(db, principal, request).chat(body, channel))


@router.get(
    "/assistant/conversations",
    summary="My assistant conversations",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=ASSIST,
)
async def assistant_conversations(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssistantService(db, principal, request).conversations())


@router.delete(
    "/assistant/conversations/{id}",
    summary="Delete a conversation",
    response_model=Envelope[dict[str, Any]],
    dependencies=ASSIST,
)
async def assistant_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await AssistantService(db, principal, request).delete_conversation(id)
    return ok({"id": str(id)})


@router.get(
    "/assistant/admin/usage",
    summary="Assistant usage by month",
    response_model=Envelope[dict[str, Any]],
    dependencies=ASSIST,
)
async def assistant_usage(
    request: Request, principal: Principal = Depends(ADMIN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssistantService(db, principal, request).usage())


@router.put(
    "/assistant/admin/config",
    summary="Assistant configuration",
    response_model=Envelope[dict[str, Any]],
    dependencies=ASSIST,
)
async def assistant_config(
    body: AssistantConfig, request: Request, principal: Principal = Depends(ADMIN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssistantService(db, principal, request).put_config(body))


# ---- simulator ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/comms/simulator/inbox",
    summary="Simulator inbox (mock provider sends)",
    response_model=Envelope[list[SimulatorInboxOut]],
    dependencies=CORE,
)
async def sim_inbox(
    request: Request,
    channel: str | None = None,
    principal: Principal = Depends(BULK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommsAnalyticsService(db, principal, request).inbox(channel))


@router.delete(
    "/comms/simulator/inbox",
    summary="Clear the simulator inbox",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def sim_clear(
    request: Request, principal: Principal = Depends(BULK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok({"deleted": await CommsAnalyticsService(db, principal, request).clear_inbox()})


@router.post(
    "/comms/simulator/inbound-whatsapp",
    summary="Inject an inbound WhatsApp message",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def sim_inbound(
    body: SimInbound, request: Request, principal: Principal = Depends(BULK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommsAnalyticsService(db, principal, request).inbound(body.phone, body.text, body.wa_message_id))


@router.post(
    "/comms/simulator/provider-event",
    summary="Simulate a provider delivery / read / failure",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def sim_event(
    body: SimProviderEvent, request: Request, principal: Principal = Depends(BULK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommsAnalyticsService(db, principal, request).provider_event(body))


# ---- analytics / me ----------------------------------------------------------------------------------------------------------
@router.get(
    "/comms/analytics/delivery",
    summary="Delivery analytics",
    response_model=Envelope[DeliveryAnalyticsOut],
    dependencies=CORE,
)
async def delivery(
    request: Request,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    channel: str | None = None,
    template_id: uuid.UUID | None = None,
    event_type: str | None = None,
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await CommsAnalyticsService(db, principal, request).delivery(
            date_from, date_to, channel, template_id, event_type
        )
    )


@router.get(
    "/comms/analytics/providers",
    summary="Provider health",
    response_model=Envelope[list[ProviderHealthOut]],
    dependencies=CORE,
)
async def providers(
    request: Request, principal: Principal = Depends(VIEW_ALL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommsAnalyticsService(db, principal, request).providers())


@router.get(
    "/comms/analytics/export",
    status_code=202,
    summary="Delivery analytics CSV (job)",
    response_model=Envelope[CommsJobAccepted],
    dependencies=CORE,
)
async def analytics_export(
    request: Request,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(
        db,
        principal,
        "comms.analytics_export",
        {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
    )
    return JSONResponse(
        status_code=202, content=ok(CommsJobAccepted(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


@router.get(
    "/comms/me/messages",
    summary="My messages (all channels)",
    response_model=Envelope[list[MyMessageOut]],
    dependencies=CORE,
)
async def my_messages(
    request: Request,
    channel: str | None = None,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommsAnalyticsService(db, principal, request).my_messages(channel, date_from, date_to))
