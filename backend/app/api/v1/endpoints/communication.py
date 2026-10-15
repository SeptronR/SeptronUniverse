"""Communication administration — Prompts/04 §04.8 (router included with ``feature_required("core.notifications_inapp")``;
the registries add their channel key).

Templates: read with ``communication:view_all`` or ``template_manage``, write with ``template_manage``; DLT registry
{comms.sms}; WhatsApp registry {comms.whatsapp}; ``send`` needs ``communication:send``; logs ``view_all``.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.communication import (
    DltTemplateCreate,
    DltTemplateResponse,
    MessageLogResponse,
    SendMessageRequest,
    SendMessageResponse,
    TemplateCreate,
    TemplatePreview,
    TemplatePreviewRequest,
    TemplateResponse,
    TemplateUpdate,
    WhatsappTemplateCreate,
    WhatsappTemplateResponse,
)
from app.services.communication_service import CommunicationService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(prefix="/communication", tags=["communication"])

READ_TEMPLATES = any_permission_required(("communication", "view_all"), ("communication", "template_manage"))
MANAGE = permission_required("communication", "template_manage")


# ---- templates ---------------------------------------------------------------------------------------------------------
@router.get(
    "/templates",
    summary="Notification templates (institution + platform defaults)",
    response_model=Envelope[list[TemplateResponse]],
)
async def list_templates(
    request: Request,
    event_trigger: str | None = Query(default=None, max_length=80),
    include_inactive: bool = False,
    principal: Principal = Depends(READ_TEMPLATES),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).list_templates(event_trigger, include_inactive))


@router.post(
    "/templates",
    status_code=201,
    summary="Create an institution template (new version)",
    response_model=Envelope[TemplateResponse],
)
async def create_template(
    body: TemplateCreate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).create_template(body), message="Template saved")


@router.get("/templates/{id}", summary="Template detail", response_model=Envelope[TemplateResponse])
async def get_template(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ_TEMPLATES), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).get_template(id))


@router.put(
    "/templates/{id}", summary="Edit a template (writes a new version)", response_model=Envelope[TemplateResponse]
)
async def update_template(
    id: uuid.UUID,
    body: TemplateUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).update_template(id, body), message="New version saved")


@router.get(
    "/templates/{id}/versions", summary="Versions of a template", response_model=Envelope[list[TemplateResponse]]
)
async def template_versions(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ_TEMPLATES), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).versions(id))


@router.post(
    "/templates/{id}/preview", summary="Render with a sample context", response_model=Envelope[TemplatePreview]
)
async def preview_template(
    id: uuid.UUID,
    body: TemplatePreviewRequest,
    request: Request,
    principal: Principal = Depends(READ_TEMPLATES),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).preview(id, body))


@router.post(
    "/templates/{id}/activate", summary="Make this version the active one", response_model=Envelope[TemplateResponse]
)
async def activate_template(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).activate_template(id), message="Version activated")


# ---- DLT / WhatsApp registries -----------------------------------------------------------------------------------------
@router.get(
    "/dlt-templates",
    summary="DLT template registry",
    dependencies=[feature_required("comms.sms")],
    response_model=Envelope[list[DltTemplateResponse]],
)
async def list_dlt(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).list_dlt())


@router.post(
    "/dlt-templates",
    status_code=201,
    summary="Register a DLT template",
    dependencies=[feature_required("comms.sms")],
    response_model=Envelope[DltTemplateResponse],
)
async def create_dlt(
    body: DltTemplateCreate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).create_dlt(body), message="DLT template registered")


@router.get(
    "/whatsapp-templates",
    summary="WhatsApp template registry",
    dependencies=[feature_required("comms.whatsapp")],
    response_model=Envelope[list[WhatsappTemplateResponse]],
)
async def list_wa(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).list_wa())


@router.post(
    "/whatsapp-templates",
    status_code=201,
    summary="Submit a WhatsApp template",
    dependencies=[feature_required("comms.whatsapp")],
    response_model=Envelope[WhatsappTemplateResponse],
)
async def create_wa(
    body: WhatsappTemplateCreate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).create_wa(body), message="Template submitted")


@router.post(
    "/whatsapp-templates/{id}/sync-status",
    summary="Refresh the approval status from the provider",
    dependencies=[feature_required("comms.whatsapp")],
    response_model=Envelope[WhatsappTemplateResponse],
)
async def sync_wa(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).sync_wa(id))


# ---- send / logs --------------------------------------------------------------------------------------------------------
@router.post(
    "/send",
    status_code=202,
    summary="Ad-hoc send of an event to an audience",
    response_model=Envelope[SendMessageResponse],
)
async def send(
    body: SendMessageRequest,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("communication", "send")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await CommunicationService(db, principal, request).send(body), message="Queued")
    await store(request, response, db, 202)
    return response


@router.get(
    "/logs",
    summary="Message logs (recipients masked without view_pii)",
    response_model=Envelope[list[MessageLogResponse]],
)
async def logs(
    request: Request,
    params: PageParams = Depends(page_params),
    channel: str | None = Query(default=None, pattern="^(in_app|sms|whatsapp|email|push)$"),
    status: str | None = Query(default=None, max_length=20),
    recipient: str | None = Query(default=None, max_length=200),
    event_type: str | None = Query(default=None, max_length=80),
    since: datetime | None = None,
    principal: Principal = Depends(permission_required("communication", "view_all")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await CommunicationService(db, principal, request).logs(
        params, channel, status, recipient, event_type, since
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get("/logs/{id}", summary="Message log detail", response_model=Envelope[MessageLogResponse])
async def log_detail(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("communication", "view_all")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CommunicationService(db, principal, request).log(id))
