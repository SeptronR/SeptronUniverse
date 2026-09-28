"""Announcements — Prompts/04 §04.6 ``announcement_service`` (feature ``comms.announcements``; acknowledgements
``comms.announcement_ack``).

Business rules
1. Drafts are created by holders of ``communication:create``; the audience is a set of rules (roles, colleges,
   departments, programmes, batches, users — OR-combined, empty = whole institution); a ``college_id`` pins the
   announcement to one college (it is added to the college rules).
2. ``publish`` sets ``publish_at`` (now), resolves the audience and notifies it through ``announcement.published``
   (in-app + push by default, optional SMS/e-mail channels) and emits ``announcement.published``; publishing an
   announcement that is already published or expired → 409.
3. Readers see published, unexpired announcements whose audience contains them (pinned first); opening one records
   ``read_at``; ``acknowledge`` records ``acknowledged_at`` when ``requires_ack`` (``comms.announcement_ack``).
4. Stats (creator or ``communication:view_all``): audience size, read, acknowledged.
5. Update is allowed while draft/scheduled; delete is soft. Everything audited.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.notifications.notify import notify_event
from app.models.communication import Announcement
from app.repositories.announcement_repository import AnnouncementRepository
from app.repositories.audience_repository import AudienceRepository
from app.schemas.communication import (
    AckStats,
    AnnouncementCreate,
    AnnouncementPublish,
    AnnouncementResponse,
    AnnouncementUpdate,
)
from app.services.institution.context import tenant_id
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta


def _status(a: Announcement) -> str:
    now = datetime.now(UTC)
    if a.expires_at and a.expires_at <= now:
        return "expired"
    if a.publish_at is None:
        return "draft"
    return "scheduled" if a.publish_at > now else "published"


def _rules(a: Announcement) -> dict[str, Any]:
    rules = dict(a.audience_rules or {})
    if a.college_id:
        rules["college_ids"] = sorted({*map(str, rules.get("college_ids") or []), str(a.college_id)})
    return rules


class AnnouncementService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = tenant_id(principal, request)
        self.repo = AnnouncementRepository(db)
        self.audience = AudienceRepository(db)

    @property
    def manager(self) -> bool:
        return bool(self.principal.has("communication", "view_all") or self.principal.has("communication", "create"))

    def _can_manage(self, a: Announcement) -> bool:
        return bool(self.principal.has("communication", "view_all") or a.created_by == self.principal.id)

    async def _response(self, a: Announcement, with_stats: bool = False) -> AnnouncementResponse:
        r = AnnouncementResponse.model_validate(a)
        r.status = _status(a)
        ack = await self.repo.acks(a.id, self.principal.id)
        if ack is not None:
            r.my_read_at, r.my_acknowledged_at = ack.read_at, ack.acknowledged_at
        if with_stats and self._can_manage(a):
            r.ack_stats = await self.stats(a.id)
        return r

    # ---- reads (rule 3) -------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None, q: str | None, status: str | None
    ) -> tuple[list[AnnouncementResponse], PaginationMeta, VisibilityMeta]:
        manage_view = self.manager and scope in (None, "all", "own")
        if manage_view:
            stmt = self.repo.base(self.inst)
            if scope == "own" or not self.principal.has("communication", "view_all"):
                stmt = stmt.where(
                    or_(Announcement.created_by == self.principal.id, Announcement.publish_at.is_not(None))
                )
        else:
            stmt = self.repo.published(self.inst)
        if q:
            stmt = stmt.where(Announcement.title.ilike(f"%{q}%"))
        stmt = stmt.order_by(
            Announcement.is_pinned.desc(), Announcement.publish_at.desc().nulls_first(), Announcement.created_at.desc()
        )
        rows = list((await self.db.execute(stmt)).scalars())
        visible = []
        for a in rows:
            if (
                manage_view
                and self._can_manage(a)
                or _status(a) == "published"
                and await self.audience.member_of(self.inst, self.principal.id, _rules(a))
            ):
                visible.append(a)
        if status:
            visible = [a for a in visible if _status(a) == status]
        total = len(visible)
        page = visible[params.offset : params.offset + params.page_size]
        acks = await self.repo.my_acks([a.id for a in page], self.principal.id)
        out = []
        for a in page:
            r = AnnouncementResponse.model_validate(a)
            r.status = _status(a)
            if a.id in acks:
                r.my_read_at, r.my_acknowledged_at = acks[a.id].read_at, acks[a.id].acknowledged_at
            out.append(r)
        return (
            out,
            PaginationMeta(
                page=params.page,
                page_size=params.page_size,
                total=total,
                total_pages=max(1, -(-total // params.page_size)),
            ),
            VisibilityMeta(
                self=True, scopes=["own", "all"] if self.manager else [], default="all" if self.manager else "self"
            ),
        )

    async def get(self, announcement_id: uuid.UUID) -> AnnouncementResponse:
        a = await self.repo.get(self.inst, announcement_id)
        if not self._can_manage(a):
            if _status(a) != "published" or not await self.audience.member_of(self.inst, self.principal.id, _rules(a)):
                raise APIError(404, ErrorCode.NOT_FOUND, "Announcement not found")
            await self.repo.upsert_ack(self.inst, a.id, self.principal.id, acknowledge=False)
        return await self._response(a, with_stats=True)

    # ---- rule 1 / 5 -----------------------------------------------------------------------------------------------
    async def create(self, body: AnnouncementCreate) -> AnnouncementResponse:
        a = Announcement(
            institution_id=self.inst,
            college_id=body.college_id,
            title=body.title,
            body=body.body,
            category=body.category,
            audience_rules=body.audience_rules.model_dump(mode="json"),
            attachments=body.attachments,
            expires_at=body.expires_at,
            requires_ack=body.requires_ack,
            is_pinned=body.is_pinned,
            created_by=self.principal.id,
        )
        self.db.add(a)
        await self.db.flush()
        await self._audit("create", a, {"title": a.title, "audience": a.audience_rules})
        return await self._response(a)

    async def update(self, announcement_id: uuid.UUID, body: AnnouncementUpdate) -> AnnouncementResponse:
        a = await self._managed(announcement_id)
        if _status(a) == "published":
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, "Published announcements cannot be edited; expire and re-post"
            )
        values = body.model_dump(exclude_unset=True, mode="json")
        if "audience_rules" in values and body.audience_rules is not None:
            values["audience_rules"] = body.audience_rules.model_dump(mode="json")
        for k, v in values.items():
            setattr(a, k, getattr(body, k) if k in ("publish_at", "expires_at") else v)
        await self.db.flush()
        await self._audit("update", a, {k: str(v) for k, v in values.items()})
        return await self._response(a)

    async def delete(self, announcement_id: uuid.UUID) -> None:
        a = await self._managed(announcement_id)
        a.deleted_at, a.is_active = datetime.now(UTC), False
        await self.db.flush()
        await self._audit("delete", a, {"title": a.title})

    async def _managed(self, announcement_id: uuid.UUID) -> Announcement:
        a = await self.repo.get(self.inst, announcement_id, for_update=True)
        if not self._can_manage(a):
            raise APIError(404, ErrorCode.NOT_FOUND, "Announcement not found")
        return a

    # ---- rule 2 ---------------------------------------------------------------------------------------------------
    async def publish(
        self, announcement_id: uuid.UUID, body: AnnouncementPublish, publish_at: datetime | None = None
    ) -> AnnouncementResponse:
        a = await self._managed(announcement_id)
        if _status(a) in ("published", "expired"):
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"Announcement is already {_status(a)}")
        a.publish_at = publish_at or datetime.now(UTC)
        await self.db.flush()
        rules = _rules(a)
        audience_users = await self.audience.resolve(self.inst, rules) if any(rules.values()) else None
        audience: dict[str, Any] = (
            {"user_ids": [str(u) for u in audience_users]}
            if audience_users is not None
            else {"roles": await self._all_roles()}
        )
        summary = (a.body or "")[:140]
        await notify_event(
            self.db,
            self.inst,
            "announcement.published",
            audience=audience,
            context={
                "title": a.title,
                "summary": summary,
                "announcement_id": str(a.id),
                "requires_ack": a.requires_ack,
            },
            channels=list(body.channels),
            actor_user_id=self.principal.id,
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="announcement.published",
            payload={
                "announcement_id": str(a.id),
                "title": a.title,
                "audience_size": len(audience_users) if audience_users is not None else None,
            },
            aggregate_type="announcement",
            aggregate_id=a.id,
            actor_user_id=self.principal.id,
        )
        await self._audit("publish", a, {"channels": body.channels, "publish_at": a.publish_at.isoformat()})
        return await self._response(a, with_stats=True)

    async def _all_roles(self) -> list[str]:
        from app.models.platform import Role

        rows = (
            await self.db.execute(select(Role.slug).where(Role.institution_id == self.inst, Role.deleted_at.is_(None)))
        ).scalars()
        return sorted(set(rows))

    # ---- rule 3 / 4 -----------------------------------------------------------------------------------------------
    async def acknowledge(self, announcement_id: uuid.UUID, acknowledge: bool = True) -> AnnouncementResponse:
        a = await self.repo.get(self.inst, announcement_id)
        if _status(a) != "published" or not await self.audience.member_of(self.inst, self.principal.id, _rules(a)):
            raise APIError(404, ErrorCode.NOT_FOUND, "Announcement not found")
        if acknowledge and a.requires_ack and not await is_enabled(self.inst, "comms.announcement_ack"):
            raise APIError(
                403,
                ErrorCode.FEATURE_DISABLED,
                "Feature 'comms.announcement_ack' is not enabled",
                {"feature": "comms.announcement_ack"},
            )
        await self.repo.upsert_ack(self.inst, a.id, self.principal.id, acknowledge=acknowledge and a.requires_ack)
        from app.repositories.notification_repository import NotificationRepository

        await NotificationRepository(self.db).mark_read_by_link(self.principal.id, "announcement_id", str(a.id))
        return await self._response(a)

    async def stats(self, announcement_id: uuid.UUID) -> AckStats:
        a = await self.repo.get(self.inst, announcement_id)
        if not self._can_manage(a):
            raise APIError(404, ErrorCode.NOT_FOUND, "Announcement not found")
        rules = _rules(a)
        if any(rules.values()):
            total = len(await self.audience.resolve(self.inst, rules))
        else:
            from app.models.platform import User

            total = int(
                (
                    await self.db.execute(
                        select(func.count())
                        .select_from(User)
                        .where(User.institution_id == self.inst, User.is_active.is_(True), User.deleted_at.is_(None))
                    )
                ).scalar_one()
            )
        read, acked = await self.repo.stats(a.id)
        return AckStats(total=total, read=read, acknowledged=acked)

    async def _audit(self, action: str, a: Announcement, new: dict[str, Any]) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module="communication",
            action=action,
            record_type="announcement",
            record_id=a.id,
            new=new,
            request=self.request,
        )
