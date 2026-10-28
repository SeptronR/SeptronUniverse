"""Integrations hub, platform APIs, data migration and exports — Prompts/41 §41.8.

``router`` (``/integrations/*`` {core.settings}; API keys / webhooks add {integrations.api_keys_webhooks}),
``imports_router`` (``/imports/*`` {data.migration_toolkit}), ``exports_router`` (``/exports/*``
{data.export_portability}) and ``inbound_router`` (``POST /webhooks/in/{provider}/{connection_id}`` — public,
provider-signature verified, in ``PUBLIC_ROUTES``).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, authenticated
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.integrations import (
    ApiKeyCreate,
    ApiKeyCreatedOut,
    ApiKeyOut,
    CapabilityStatusOut,
    ConnectionIn,
    ConnectionOut,
    ConnectionTestOut,
    ConnectionTestRequest,
    DeadLetterAction,
    DeadLetterOut,
    DeliveryOut,
    DeliveryRetryRequest,
    EventCatalogueItem,
    ExportOut,
    ExportRequest,
    ImportApplyRequest,
    ImportCreate,
    ImportMappingIn,
    ImportOut,
    ImportRollbackRequest,
    ImportRowOut,
    ImportTemplateOut,
    InboundEventOut,
    WebhookCreatedOut,
    WebhookIn,
    WebhookOut,
    WebhookTestRequest,
    WorkbookOut,
)
from app.services.integrations import webhook_service as wh
from app.services.integrations.api_key_service import ApiKeyService
from app.services.integrations.connection_service import ConnectionService
from app.services.integrations.import_service import ImportService
from app.utils.response import ok

router = APIRouter(prefix="/integrations", tags=["integrations"])
imports_router = APIRouter(prefix="/imports", tags=["imports"])
exports_router = APIRouter(prefix="/exports", tags=["exports"])
inbound_router = APIRouter(tags=["integrations-inbound"])

VIEW = any_permission_required(("integrations", "view"), ("integrations", "manage"), ("integrations", "connect"))
MANAGE = any_permission_required(("integrations", "manage"), ("integrations", "connect"))
KEYS = any_permission_required(("integrations", "api_keys"), ("integrations", "manage"), ("integrations", "view"))
HOOKS = any_permission_required(("integrations", "webhooks"), ("integrations", "manage"), ("integrations", "view"))
APIW = [feature_required("integrations.api_keys_webhooks")]
IMPORT = any_permission_required(
    ("integrations", "import"),
    ("students", "bulk_import"),
    ("hr", "manage"),
    ("library", "manage"),
    ("fees", "manage"),
    ("research", "manage"),
    ("integrations", "view"),
)

CHANGELOG = [
    {
        "version": "v1.41",
        "date": "2026-10-28",
        "changes": [
            "API keys (X-API-Key) with scopes",
            "Outbound webhooks with HMAC signatures",
            "/imports migration toolkit",
            "/exports user data export",
        ],
    },
    {"version": "v1.40", "date": "2026-10-28", "changes": ["Public website, catalogue, marketing endpoints"]},
    {"version": "v1.39", "date": "2026-10-28", "changes": ["Portal shell, notification centre, push, tours"]},
]


# ---- connections ----------------------------------------------------------------------------------------------------
@router.get(
    "/providers",
    summary="Provider catalogue (capabilities × providers, config schemas)",
    response_model=Envelope[list[dict[str, Any]]],
)
async def providers(principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(ConnectionService(db, principal).providers())


@router.get(
    "/capabilities",
    summary="Capability / feature matrix of this institution",
    response_model=Envelope[list[CapabilityStatusOut]],
)
async def capabilities(principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await ConnectionService(db, principal).capabilities())


@router.get("/health-summary", summary="Connection status counts", response_model=Envelope[dict[str, int]])
async def health_summary(principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = await ConnectionService(db, principal).list(None)
    out: dict[str, int] = {}
    for c in rows:
        out[c.status] = out.get(c.status, 0) + 1
    return ok(out)


@router.get("/connections", summary="Connections (secrets redacted)", response_model=Envelope[list[ConnectionOut]])
async def connections(
    capability: str | None = Query(None, max_length=40),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConnectionService(db, principal).list(capability))


@router.post("/connections", status_code=201, summary="Create a connection", response_model=Envelope[ConnectionOut])
async def connection_create(
    body: ConnectionIn, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConnectionService(db, principal, request).create(body), message="Connection saved")


@router.get("/connections/{id}", summary="Connection with health history", response_model=Envelope[ConnectionOut])
async def connection_get(
    id: uuid.UUID, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConnectionService(db, principal).get(id))


@router.put(
    "/connections/{id}", summary="Update a connection ('***' keeps a secret)", response_model=Envelope[ConnectionOut]
)
async def connection_update(
    id: uuid.UUID,
    body: ConnectionIn,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConnectionService(db, principal, request).update(id, body), message="Connection saved")


@router.delete("/connections/{id}", status_code=204, summary="Delete a connection")
async def connection_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> Response:
    await ConnectionService(db, principal, request).delete(id)
    return Response(status_code=204)


@router.post("/connections/{id}/test", summary="Test a connection", response_model=Envelope[ConnectionTestOut])
async def connection_test(
    id: uuid.UUID,
    body: ConnectionTestRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConnectionService(db, principal, request).test(id, body))


@router.post("/connections/{id}/enable", summary="Enable", response_model=Envelope[ConnectionOut])
async def connection_enable(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConnectionService(db, principal, request).set_enabled(id, True))


@router.post("/connections/{id}/disable", summary="Disable", response_model=Envelope[ConnectionOut])
async def connection_disable(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConnectionService(db, principal, request).set_enabled(id, False))


@router.post(
    "/connections/{id}/set-default",
    summary="Default connection for its capability",
    response_model=Envelope[ConnectionOut],
)
async def connection_default(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConnectionService(db, principal, request).set_default(id))


@router.get("/connections/{id}/health", summary="Health history", response_model=Envelope[list[dict[str, Any]]])
async def connection_health(
    id: uuid.UUID, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConnectionService(db, principal).health(id))


@router.get("/inbound", summary="Inbound webhook log", response_model=Envelope[list[InboundEventOut]])
async def inbound(
    provider: str | None = Query(None, max_length=40),
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await wh.inbound_list(principal.institution_id, provider))


@router.post("/inbound/{id}/replay", summary="Replay an inbound event", response_model=Envelope[dict[str, Any]])
async def inbound_replay(
    id: str, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.core.audit import log_audit
    from app.services.integrations.inbound_service import handle

    e = await wh.inbound_entry(principal.institution_id, id[:40])
    if not e or not e.get("connection_id"):
        raise APIError(404, ErrorCode.NOT_FOUND, "Inbound event not found")
    out = await handle(
        db, request, e["provider"], uuid.UUID(e["connection_id"]), str(e.get("body") or "").encode(), replay=True
    )
    await log_audit(
        db,
        principal=principal,
        module="integrations",
        action="inbound_replay",
        record_type="inbound_event",
        record_id=None,
        new={"id": id},
        request=request,
    )
    return ok(out)


@router.get("/api-changelog", summary="Platform API changelog", response_model=Envelope[list[dict[str, Any]]])
async def api_changelog(principal: Principal = Depends(authenticated())) -> dict[str, Any]:
    return ok(CHANGELOG)


# ---- api keys -------------------------------------------------------------------------------------------------------
@router.get(
    "/api-keys", summary="API keys (prefixes only)", dependencies=APIW, response_model=Envelope[list[ApiKeyOut]]
)
async def api_keys(principal: Principal = Depends(KEYS), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await ApiKeyService(db, principal).list())


@router.post(
    "/api-keys",
    status_code=201,
    summary="Create an API key (secret shown once)",
    dependencies=APIW,
    response_model=Envelope[ApiKeyCreatedOut],
)
async def api_key_create(
    body: ApiKeyCreate, request: Request, principal: Principal = Depends(KEYS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(
        await ApiKeyService(db, principal, request).create(body), message="Copy the secret now — it is not shown again"
    )


@router.post(
    "/api-keys/{id}/rotate",
    summary="Rotate (old key valid 24 h)",
    dependencies=APIW,
    response_model=Envelope[ApiKeyCreatedOut],
)
async def api_key_rotate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(KEYS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ApiKeyService(db, principal, request).rotate(id))


@router.delete("/api-keys/{id}", status_code=204, summary="Revoke an API key", dependencies=APIW)
async def api_key_revoke(
    id: uuid.UUID, request: Request, principal: Principal = Depends(KEYS), db: AsyncSession = Depends(get_db)
) -> Response:
    await ApiKeyService(db, principal, request).revoke(id)
    return Response(status_code=204)


@router.get(
    "/api-keys/{id}/usage", summary="Daily usage (14 days)", dependencies=APIW, response_model=Envelope[dict[str, int]]
)
async def api_key_usage(
    id: uuid.UUID, principal: Principal = Depends(KEYS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ApiKeyService(db, principal).usage(id))


# ---- webhooks -------------------------------------------------------------------------------------------------------
@router.get(
    "/webhooks/events",
    summary="Webhook event catalogue",
    dependencies=APIW,
    response_model=Envelope[list[EventCatalogueItem]],
)
async def webhook_events(principal: Principal = Depends(HOOKS)) -> dict[str, Any]:
    return ok(wh.catalogue())


@router.get("/webhooks", summary="Webhook subscriptions", dependencies=APIW, response_model=Envelope[list[WebhookOut]])
async def webhooks(principal: Principal = Depends(HOOKS), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await wh.WebhookService(db, principal).list())


@router.post(
    "/webhooks",
    status_code=201,
    summary="Create a webhook (secret shown once)",
    dependencies=APIW,
    response_model=Envelope[WebhookCreatedOut],
)
async def webhook_create(
    body: WebhookIn, request: Request, principal: Principal = Depends(HOOKS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await wh.WebhookService(db, principal, request).create(body))


@router.get("/webhooks/{id}", summary="Webhook", dependencies=APIW, response_model=Envelope[WebhookOut])
async def webhook_get(
    id: uuid.UUID, principal: Principal = Depends(HOOKS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = wh.WebhookService(db, principal)
    return ok(await svc._out(await svc._get(id)))


@router.put("/webhooks/{id}", summary="Update a webhook", dependencies=APIW, response_model=Envelope[WebhookOut])
async def webhook_update(
    id: uuid.UUID,
    body: WebhookIn,
    request: Request,
    principal: Principal = Depends(HOOKS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await wh.WebhookService(db, principal, request).update(id, body))


@router.delete("/webhooks/{id}", status_code=204, summary="Delete a webhook", dependencies=APIW)
async def webhook_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(HOOKS), db: AsyncSession = Depends(get_db)
) -> Response:
    await wh.WebhookService(db, principal, request).delete(id)
    return Response(status_code=204)


@router.post(
    "/webhooks/{id}/rotate-secret",
    summary="Rotate the signing secret",
    dependencies=APIW,
    response_model=Envelope[WebhookCreatedOut],
)
async def webhook_rotate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(HOOKS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await wh.WebhookService(db, principal, request).rotate_secret(id))


@router.post(
    "/webhooks/{id}/test", summary="Send a test delivery", dependencies=APIW, response_model=Envelope[DeliveryOut]
)
async def webhook_test(
    id: uuid.UUID,
    body: WebhookTestRequest,
    request: Request,
    principal: Principal = Depends(HOOKS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await wh.WebhookService(db, principal, request).test(id, body.event_type))


@router.get("/deliveries", summary="Webhook deliveries", dependencies=APIW, response_model=Envelope[list[DeliveryOut]])
async def deliveries(
    webhook_id: uuid.UUID | None = None,
    status: str | None = Query(None, pattern="^(pending|delivered|failed|dead)$"),
    event_type: str | None = Query(None, max_length=80),
    principal: Principal = Depends(HOOKS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await wh.WebhookService(db, principal).deliveries(webhook_id, status, event_type))


@router.get(
    "/deliveries/{id}", summary="Delivery with payload", dependencies=APIW, response_model=Envelope[DeliveryOut]
)
async def delivery(
    id: uuid.UUID, principal: Principal = Depends(HOOKS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await wh.WebhookService(db, principal).delivery(id))


@router.post(
    "/deliveries/retry",
    summary="Retry deliveries / replay all dead",
    dependencies=APIW,
    response_model=Envelope[dict[str, int]],
)
async def deliveries_retry(
    body: DeliveryRetryRequest,
    request: Request,
    principal: Principal = Depends(HOOKS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        {"queued": await wh.WebhookService(db, principal, request).retry(body.ids, body.all_dead, body.webhook_id)}
    )


# ---- dead letters ---------------------------------------------------------------------------------------------------
@router.get(
    "/dead-letters",
    summary="Dead letters (outbox / webhooks / notifications)",
    response_model=Envelope[list[DeadLetterOut]],
)
async def dead_letters(
    kind: str | None = Query(None, pattern="^(outbox|webhook|notification)$"),
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await wh.DeadLetterService(db, principal).list(kind))


@router.post("/dead-letters/replay", summary="Replay dead letters", response_model=Envelope[dict[str, int]])
async def dead_replay(
    body: DeadLetterAction, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok({"replayed": await wh.DeadLetterService(db, principal, request).replay(body.kind, body.ids)})


@router.post(
    "/dead-letters/discard", summary="Discard dead letters (reason audited)", response_model=Envelope[dict[str, int]]
)
async def dead_discard(
    body: DeadLetterAction, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(
        {"discarded": await wh.DeadLetterService(db, principal, request).discard(body.kind, body.ids, body.reason)}
    )


# ---- inbound (public) -----------------------------------------------------------------------------------------------
@inbound_router.post(
    "/webhooks/in/{provider}/{connection_id}",
    summary="Inbound provider webhook (signature-verified, idempotent)",
    response_model=Envelope[dict[str, Any]],
)
async def inbound_webhook(
    provider: str, connection_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.services.integrations.inbound_service import MAX_BODY, handle

    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise APIError(413, ErrorCode.VALIDATION, "Payload too large")
    return ok(await handle(db, request, provider[:40], connection_id, await request.body()))


# ---- imports --------------------------------------------------------------------------------------------------------
@imports_router.get(
    "/templates", summary="Import templates I may use", response_model=Envelope[list[ImportTemplateOut]]
)
async def import_templates(
    principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(ImportService(db, principal).templates())


@imports_router.get("/templates/{entity}/sample.xlsx", summary="Sample file", response_model=None)
async def import_sample(
    entity: str, principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> Response:
    return Response(
        ImportService(db, principal).sample_xlsx(entity),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{entity}-sample.xlsx"'},
    )


@imports_router.get("/profiles", summary="Saved mapping profiles", response_model=Envelope[dict[str, Any]])
async def import_profiles(principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await ImportService(db, principal).profiles())


@imports_router.post("/profiles", summary="Save a mapping profile", response_model=Envelope[dict[str, Any]])
async def import_profile_save(
    body: dict[str, Any], principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(
        await ImportService(db, principal).save_profile(
            str(body.get("name"))[:80], str(body.get("entity")), dict(body.get("mapping") or {})
        )
    )


@imports_router.delete("/profiles/{name}", status_code=204, summary="Delete a mapping profile")
async def import_profile_delete(
    name: str, principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> Response:
    await ImportService(db, principal).delete_profile(name[:80])
    return Response(status_code=204)


@imports_router.get("/workbook", summary="Migration workbook", response_model=Envelope[WorkbookOut])
async def workbook(principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await ImportService(db, principal).workbook())


@imports_router.post("/workbook/start", summary="Start the cut-over workbook", response_model=Envelope[WorkbookOut])
async def workbook_start(principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await ImportService(db, principal).workbook_start())


@imports_router.post(
    "/workbook/steps/{order}/attach",
    summary="Attach an import to a step (or mark it done)",
    response_model=Envelope[WorkbookOut],
)
async def workbook_attach(
    order: int, body: dict[str, Any], principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    iid = body.get("import_id")
    return ok(
        await ImportService(db, principal).workbook_attach(
            order, uuid.UUID(str(iid)) if iid else None, bool(body.get("done"))
        )
    )


@imports_router.get("", summary="Imports (Mine | All)", response_model=Envelope[list[ImportOut]])
async def imports(
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    principal: Principal = Depends(IMPORT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ImportService(db, principal).list(scope == "mine"))


@imports_router.post(
    "", status_code=201, summary="Upload an import (parsed + auto-mapped)", response_model=Envelope[ImportOut]
)
async def import_create(
    body: ImportCreate, request: Request, principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ImportService(db, principal, request).create(body), message="Uploaded")


@imports_router.get("/{id}", summary="Import", response_model=Envelope[ImportOut])
async def import_get(
    id: uuid.UUID, principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ImportService(db, principal).get(id))


@imports_router.put("/{id}/mapping", summary="Change the column mapping", response_model=Envelope[ImportOut])
async def import_mapping(
    id: uuid.UUID, body: ImportMappingIn, principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ImportService(db, principal).set_mapping(id, body.mapping, body.profile_name))


@imports_router.post("/{id}/validate", summary="Validate (job)", response_model=Envelope[ImportOut])
async def import_validate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ImportService(db, principal, request).enqueue(id, "validate"), message="Validation queued")


@imports_router.get("/{id}/rows", summary="Rows with errors", response_model=Envelope[list[ImportRowOut]])
async def import_rows(
    id: uuid.UUID,
    status: str | None = Query(None, pattern="^(pending|valid|invalid|applied|skipped|rolled_back)$"),
    error_code: str | None = Query(None, max_length=40),
    page: int = Query(1, ge=1, le=10_000),
    principal: Principal = Depends(IMPORT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ImportService(db, principal).rows(id, status, error_code, page))


@imports_router.get("/{id}/errors.xlsx", summary="Error file", response_model=None)
async def import_errors(
    id: uuid.UUID, principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> Response:
    return Response(
        await ImportService(db, principal).error_file(id),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="errors.xlsx"'},
    )


@imports_router.post(
    "/{id}/apply", summary="Apply (job; confirm the valid row count)", response_model=Envelope[ImportOut]
)
async def import_apply(
    id: uuid.UUID,
    body: ImportApplyRequest,
    request: Request,
    principal: Principal = Depends(IMPORT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ImportService(db, principal, request)
    await svc.check_apply(id, body.confirm_valid_rows)
    return ok(await svc.enqueue(id, "apply", {"on_conflict": body.on_conflict}), message="Apply queued")


@imports_router.post("/{id}/rollback", summary="Roll back (job)", response_model=Envelope[ImportOut])
async def import_rollback(
    id: uuid.UUID,
    body: ImportRollbackRequest,
    request: Request,
    principal: Principal = Depends(IMPORT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await ImportService(db, principal, request).enqueue(id, "rollback", {"reason": body.reason}),
        message="Rollback queued",
    )


@imports_router.delete("/{id}", status_code=204, summary="Delete an unapplied import")
async def import_delete(
    id: uuid.UUID, principal: Principal = Depends(IMPORT), db: AsyncSession = Depends(get_db)
) -> Response:
    await ImportService(db, principal).delete(id)
    return Response(status_code=204)


# ---- exports --------------------------------------------------------------------------------------------------------
@exports_router.post(
    "/users/{who}",
    summary="User data export (me, or any user for privacy officers)",
    response_model=Envelope[ExportOut],
)
async def export_user(
    who: str,
    body: ExportRequest,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.core.audit import log_audit
    from app.core.jobs import enqueue

    uid = principal.id if who == "me" else uuid.UUID(who)
    if uid != principal.id and not principal.has("settings", "manage"):
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only privacy officers may export another user's data")
    job = await enqueue(db, principal, "exports.user", {"user_id": str(uid), "include": body.include}, queue="reports")
    await log_audit(
        db,
        principal=principal,
        module="integrations",
        action="export_user",
        record_type="user",
        record_id=uid,
        request=request,
    )
    return ok(ExportOut(job_id=job.id, status=job.status))


@exports_router.post(
    "/tenant",
    status_code=202,
    summary="Tenant export (alias of the Phase 38 /billing/export job)",
    response_model=Envelope[dict[str, Any]],
)
async def export_tenant(
    body: dict[str, Any],
    request: Request,
    principal: Principal = Depends(any_permission_required(("settings", "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.schemas.saas import TenantExportRequest
    from app.services.saas.institution_admin_service import InstitutionAdminService

    out = await InstitutionAdminService(db, principal, request).request_export(
        principal.institution_id, TenantExportRequest.model_validate(body or {}), tenant=True
    )
    return ok(out.model_dump(mode="json") if hasattr(out, "model_dump") else out, message="Export queued")


@exports_router.get("/{job_id}", summary="Export job status", response_model=Envelope[ExportOut])
async def export_status(
    job_id: uuid.UUID, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.models.platform import BackgroundJob

    j = await db.get(BackgroundJob, job_id)
    if j is None or (j.requested_by != principal.id and not principal.has("settings", "manage")):
        raise APIError(404, ErrorCode.NOT_FOUND, "Export not found")
    return ok(ExportOut(job_id=j.id, status=j.status, url=j.result_url))
