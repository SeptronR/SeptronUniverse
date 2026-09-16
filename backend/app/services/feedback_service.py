"""In-app feedback — Prompts/01 §01.6 (``feedback_entries``).

Business rules
1. Any authenticated user may submit feedback (``dashboard:view``); the row records the page, category, rating,
   message and client, tagged with the principal's institution and user id.
2. Visibility: self; ``settings:view_all`` (or super admin) lists the institution's entries (Phase 37 settings UI).
3. Every submission is audited (``settings:feedback``) and emits ``feedback.created`` so Phase 24 can notify the
   support inbox; the request is non-idempotent (``Idempotency-Key`` honoured by the route).
"""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.platform.visibility  # noqa: F401
from app.core import events
from app.core.audit import log_audit
from app.core.authz.dependencies import Principal
from app.models.platform import FeedbackEntry
from app.repositories.platform_repository import FeedbackRepository
from app.schemas.platform import FeedbackCreate
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta


class FeedbackService:
    def __init__(self, db: AsyncSession, principal: Principal):
        self.db, self.principal = db, principal
        self.repo = FeedbackRepository(db, principal)

    async def create(self, body: FeedbackCreate, request: Request | None = None) -> FeedbackEntry:
        """Rules 1 and 3."""
        row = await self.repo.create(
            institution_id=self.principal.institution_id,
            user_id=self.principal.id,
            page=body.page,
            category=body.category,
            rating=body.rating,
            message=body.message,
            screenshot_url=body.screenshot_url,
            client=body.client,
            status="new",
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="settings",
            action="feedback",
            record_type="feedback_entry",
            record_id=row.id,
            new={"page": body.page, "category": body.category, "rating": body.rating, "client": body.client},
            request=request,
        )
        await events.emit(
            self.db,
            institution_id=self.principal.institution_id,
            event_type="feedback.created",
            payload={"id": str(row.id), "category": body.category, "page": body.page, "rating": body.rating},
            aggregate_type="feedback_entry",
            aggregate_id=row.id,
            actor_user_id=self.principal.id,
        )
        return row

    async def list(self, params: PageParams) -> tuple[list[FeedbackEntry], PaginationMeta]:
        """Rule 2."""
        rows, pagination = await self.repo.list_visible(params)
        return list(rows), pagination
