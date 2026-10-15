"""Communication administration — Prompts/04 §04.6 (templates, DLT / WhatsApp registries, ad-hoc sends, logs,
provider webhooks).

Business rules
1. Templates: the list shows the institution's templates next to the platform defaults (read-only, ``is_platform``);
   creating an override of an event starts at ``version = max + 1`` and — with ``activate`` — deactivates the other
   versions of the same (event, language), so ``resolve`` returns it. Editing never mutates a version: ``PUT`` writes
   a new version (running dispatches keep the text they rendered). Bodies must compile (sandboxed Jinja2 → 422).
   ``activate`` switches the resolver to any stored version. Needs ``communication:template_manage``.
2. ``preview`` renders subject/body with a sample context and lists the missing variables.
3. DLT registry (``comms.sms``): ``template_id`` unique per institution (409); WhatsApp registry (``comms.whatsapp``):
   new templates are ``pending``; ``sync-status`` asks the provider (mock: approves) and stores ``meta_template_id``.
4. ``send``: ``notify_event`` with the audience (roles / college / department / programme / batch / users / direct
   contacts) — 202 with the outbox event id; delivery is asynchronous.
5. Logs (``communication:view_all``): filters channel/status/recipient/event; recipients masked without
   ``communication:view_pii``.
6. Webhooks (public, signature ``X-Signature = hex(HMAC-SHA256(SECRET_KEY + provider, body))``): the log found by
   provider message id (or our id) moves to delivered / bounced / read / failed; bad signature → 401.
"""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.authz.masking import mask_all
from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.notifications.catalogue import category_of
from app.core.notifications.notify import notify_event
from app.core.notifications.templating import missing_variables, render, validate
from app.models.communication import DltTemplate, NotificationTemplate, WhatsappTemplate
from app.repositories.message_log_repository import MessageLogRepository
from app.repositories.template_repository import TemplateRepository
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
    WebhookCallback,
    WhatsappTemplateCreate,
    WhatsappTemplateResponse,
)
from app.services.institution.context import tenant_id
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta


def template_response(t: NotificationTemplate) -> TemplateResponse:
    r = TemplateResponse.model_validate(t)
    r.is_platform = t.institution_id is None
    r.category = category_of(t.event_trigger)
    return r


def webhook_signature(provider: str, body: bytes) -> str:
    return hmac.new((settings.SECRET_KEY + provider).encode(), body, hashlib.sha256).hexdigest()


class CommunicationService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = tenant_id(principal, request)
        self.templates = TemplateRepository(db)

    async def _audit(
        self,
        action: str,
        record_type: str,
        record_id: uuid.UUID | None,
        new: dict[str, Any],
        old: dict[str, Any] | None = None,
    ) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module="communication",
            action=action,
            record_type=record_type,
            record_id=record_id,
            old=old,
            new=new,
            request=self.request,
        )

    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    async def list_templates(self, event_trigger: str | None, include_inactive: bool) -> list[TemplateResponse]:
        return [template_response(t) for t in await self.templates.list(self.inst, event_trigger, include_inactive)]

    async def get_template(self, template_id: uuid.UUID) -> TemplateResponse:
        return template_response(await self._template(template_id))

    async def _template(self, template_id: uuid.UUID) -> NotificationTemplate:
        t = await self.templates.get(template_id, self.inst)
        if t is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Template not found")
        return t

    @staticmethod
    def _check_syntax(*parts: str | None) -> None:
        for p in parts:
            if p and (err := validate(p)):
                raise APIError(422, ErrorCode.VALIDATION, f"Template syntax error ({err})", {"field": "body_template"})

    async def create_template(self, body: TemplateCreate) -> TemplateResponse:
        self._check_syntax(body.subject_template, body.body_template)
        if body.dlt_template_id and await self.templates.dlt_by_template_id(self.inst, body.dlt_template_id) is None:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown DLT template id", {"field": "dlt_template_id"})
        version = await self.templates.next_version(self.inst, body.event_trigger, body.language)
        t = NotificationTemplate(
            institution_id=self.inst,
            event_trigger=body.event_trigger,
            name=body.name,
            channels=list(body.channels),
            subject_template=body.subject_template,
            body_template=body.body_template,
            variables=body.variables,
            language=body.language,
            version=version,
            is_active=body.activate,
            dlt_template_id=body.dlt_template_id,
            whatsapp_template_name=body.whatsapp_template_name,
        )
        self.db.add(t)
        await self.db.flush()
        if body.activate:
            await self.templates.deactivate_others(t)
        await self._audit(
            "create",
            "notification_template",
            t.id,
            {"event": t.event_trigger, "language": t.language, "version": version},
        )
        return template_response(t)

    async def update_template(self, template_id: uuid.UUID, body: TemplateUpdate) -> TemplateResponse:
        base = await self._template(template_id)
        values = body.model_dump(exclude_unset=True, exclude={"activate"})
        merged = {
            "name": base.name,
            "channels": base.channels,
            "subject_template": base.subject_template,
            "body_template": base.body_template,
            "variables": base.variables or [],
            "dlt_template_id": base.dlt_template_id,
            "whatsapp_template_name": base.whatsapp_template_name,
            **values,
        }
        return await self.create_template(
            TemplateCreate(event_trigger=base.event_trigger, language=base.language, activate=body.activate, **merged)
        )

    async def activate_template(self, template_id: uuid.UUID) -> TemplateResponse:
        t = await self._template(template_id)
        if t.institution_id is None:
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, "Platform templates are read-only; create an override instead"
            )
        t.is_active = True
        await self.templates.deactivate_others(t)
        await self.db.flush()
        await self._audit("activate", "notification_template", t.id, {"version": t.version})
        return template_response(t)

    async def versions(self, template_id: uuid.UUID) -> list[TemplateResponse]:
        t = await self._template(template_id)
        if t.institution_id is None:
            return [template_response(t)]
        return [template_response(v) for v in await self.templates.versions(self.inst, t.event_trigger, t.language)]

    # ---- rule 2 ---------------------------------------------------------------------------------------------------
    async def preview(self, template_id: uuid.UUID, body: TemplatePreviewRequest) -> TemplatePreview:
        t = await self._template(template_id)
        context = body.context
        draft = body.model_fields_set & {"subject_template", "body_template", "variables"}
        subject = body.subject_template if "subject_template" in draft else t.subject_template
        text = body.body_template if "body_template" in draft and body.body_template is not None else t.body_template
        variables = body.variables if "variables" in draft else t.variables
        if draft:
            self._check_syntax(subject, text)
        missing = missing_variables(variables, context, subject, text)
        ctx = {**{m: f"{{{{{m}}}}}" for m in missing}, **context}
        try:
            return TemplatePreview(
                subject=render(subject, ctx) or None,
                body=render(text, ctx),
                missing_variables=missing,
            )
        except Exception as exc:  # noqa: BLE001 - sandbox errors are the template author's to fix
            raise APIError(422, ErrorCode.VALIDATION, f"Render failed: {exc}") from None

    # ---- rule 3 ---------------------------------------------------------------------------------------------------
    async def list_dlt(self) -> list[DltTemplateResponse]:
        return [DltTemplateResponse.model_validate(d) for d in await self.templates.dlt_list(self.inst)]

    async def create_dlt(self, body: DltTemplateCreate) -> DltTemplateResponse:
        if await self.templates.dlt_by_template_id(self.inst, body.template_id):
            raise APIError(409, ErrorCode.CONFLICT, "DLT template id already registered", {"field": "template_id"})
        row = DltTemplate(institution_id=self.inst, **body.model_dump())
        self.db.add(row)
        await self.db.flush()
        await self._audit("create", "dlt_template", row.id, body.model_dump())
        return DltTemplateResponse.model_validate(row)

    async def list_wa(self) -> list[WhatsappTemplateResponse]:
        return [WhatsappTemplateResponse.model_validate(w) for w in await self.templates.wa_list(self.inst)]

    async def create_wa(self, body: WhatsappTemplateCreate) -> WhatsappTemplateResponse:
        if await self.templates.wa_by_name(self.inst, body.name, body.language):
            raise APIError(409, ErrorCode.CONFLICT, "WhatsApp template already exists", {"field": "name"})
        row = WhatsappTemplate(institution_id=self.inst, status="pending", **body.model_dump())
        self.db.add(row)
        await self.db.flush()
        await self._audit("create", "whatsapp_template", row.id, {"name": body.name, "language": body.language})
        return WhatsappTemplateResponse.model_validate(row)

    async def sync_wa(self, template_id: uuid.UUID) -> WhatsappTemplateResponse:
        from app.integrations.registry import get_adapter
        from app.services.notifications.delivery import provider_for

        row = await self.templates.wa_get(self.inst, template_id)
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "WhatsApp template not found")
        provider = await provider_for(self.db, self.inst, "whatsapp")
        adapter = get_adapter("whatsapp", provider)
        result = await adapter.template_status(name=row.name, language=row.language)
        old = {"status": row.status}
        if getattr(adapter, "provider", provider) == "mock":
            row.status, row.meta_template_id = "approved", row.meta_template_id or f"mock-{row.name}"
        elif isinstance(result, dict):
            row.status = str(result.get("status") or row.status)
            row.meta_template_id = result.get("id") or row.meta_template_id
        await self.db.flush()
        await self._audit("sync_status", "whatsapp_template", row.id, {"status": row.status}, old)
        return WhatsappTemplateResponse.model_validate(row)

    # ---- rule 4 ---------------------------------------------------------------------------------------------------
    async def send(self, body: SendMessageRequest) -> SendMessageResponse:
        event_type = body.event_type
        if body.template_id is not None:
            event_type = (await self._template(body.template_id)).event_trigger
        audience = body.audience.model_dump(mode="json")
        event_id = await notify_event(
            self.db,
            self.inst,
            str(event_type),
            audience=audience,
            context=body.context,
            channels=list(body.channels) if body.channels else None,
            template_id=body.template_id,
            actor_user_id=self.principal.id,
        )
        await self._audit(
            "send",
            "notification",
            event_id,
            {"event_type": event_type, "audience": audience, "channels": body.channels},
        )
        return SendMessageResponse(event_id=event_id, event_type=str(event_type))

    # ---- rule 5 ---------------------------------------------------------------------------------------------------
    async def logs(
        self,
        params: PageParams,
        channel: str | None,
        status: str | None,
        recipient: str | None,
        event_type: str | None,
        since: datetime | None,
    ) -> tuple[list[MessageLogResponse], PaginationMeta, VisibilityMeta]:
        rows, pagination = await MessageLogRepository(self.db).search(
            self.inst, params, channel, status, recipient, event_type, since
        )
        items = mask_all([MessageLogResponse.model_validate(r) for r in rows], self.principal, "communication")
        return (
            items,
            pagination,
            VisibilityMeta(
                self=False, scopes=["all"], default="all", pii=self.principal.has("communication", "view_pii")
            ),
        )

    async def log(self, log_id: uuid.UUID) -> MessageLogResponse:
        row = await MessageLogRepository(self.db).get(log_id, self.inst)
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Message log not found")
        masked: MessageLogResponse = mask_all(
            [MessageLogResponse.model_validate(row)], self.principal, "communication"
        )[0]
        return masked


# ---- rule 6 (public) --------------------------------------------------------------------------------------------------
async def apply_webhook(
    db: AsyncSession, provider: str, channel: str, raw: bytes, signature: str | None, body: WebhookCallback
) -> dict[str, Any]:
    expected = webhook_signature(provider, raw)
    if not signature or not hmac.compare_digest(signature, expected):
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid webhook signature")
    row = await MessageLogRepository(db).by_provider_ref(body.message_id)
    if row is None or row.channel != channel:
        raise APIError(404, ErrorCode.NOT_FOUND, "Message not found")
    now = datetime.now(UTC)
    row.status = body.status
    if body.status == "delivered":
        row.delivered_at = now
    if body.error:
        row.error = body.error
    if body.cost_paise is not None:
        row.cost_paise = body.cost_paise
    await db.flush()
    return {"message_log_id": str(row.id), "status": row.status}
