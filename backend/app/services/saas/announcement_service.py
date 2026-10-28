"""Platform announcements — Prompts/38 §38.6 ``announcement_service``.

Business rules
1. ``platform_announcements`` authored by the super admin (``platform:manage``); ``audience`` carries
   ``{type: all|plan|institution_type|institution_ids|roles, values: [...], channels: [banner, inapp, email],
   kind}`` (channels default ``announcements.default_channels``); a window ``starts_at`` / ``ends_at``.
2. **Active** for a user (``GET /platform/announcements/active``, polled every 5 minutes; also counted in
   ``/auth/me``): live window, ``is_active``, banner channel, audience matched against the user's tenant (plan code /
   tier of the current subscription, institution type, id) or roles, not dismissed (Redis ``ann:{id}:seen:{user}``).
   Platform users see every live announcement.
3. **Delivery** (job ``announcement.deliver`` on publish / when the window opens): ``inapp`` → Phase 24
   notification ``platform.announcement`` to the matched tenants' users (roles audience → those roles; otherwise the
   institution admins — the banner reaches everyone else), ``email`` → the institution admins of the audience;
   counts kept in ``platform_settings['ann:<id>']``. Used for release notes, maintenance notices (read-only windows
   auto-create one) and incident updates (provider outages).
"""

import contextlib
import uuid
from typing import Any

from sqlalchemy import or_, select, text

from app.models.saas import PlatformAnnouncement
from app.schemas.saas import AnnouncementIn, AnnouncementOut
from app.services.saas.common import PlatformBase, not_found, now_utc


class AnnouncementService(PlatformBase):
    def out(self, a: PlatformAnnouncement, delivered: dict[str, Any] | None = None) -> AnnouncementOut:
        aud = dict(a.audience or {})
        now = now_utc()
        live = a.is_active and (a.starts_at is None or a.starts_at <= now) and (a.ends_at is None or a.ends_at > now)
        return AnnouncementOut(
            id=a.id,
            title=a.title,
            body=a.body,
            audience={"type": aud.get("type", "all"), "values": list(aud.get("values") or [])},
            channels=list(aud.get("channels") or ["banner"]),
            kind=str(aud.get("kind") or "info"),
            starts_at=a.starts_at,
            ends_at=a.ends_at,
            is_active=a.is_active,
            live=live,
            delivered=delivered or {},
            created_at=a.created_at,
        )

    async def list_all(self) -> list[AnnouncementOut]:
        self.require_platform("platform", "view")
        rows = list(
            (
                await self.db.execute(
                    select(PlatformAnnouncement).order_by(PlatformAnnouncement.created_at.desc()).limit(500)
                )
            ).scalars()
        )
        delivered = await self.plist("ann:")
        return [self.out(a, delivered.get(str(a.id))) for a in rows]

    async def create(self, body: AnnouncementIn, *, system: bool = False) -> AnnouncementOut:
        if not system:
            self.require_super("Publishing platform announcements")
        a = PlatformAnnouncement(
            title=body.title,
            body=body.body,
            audience={**body.audience.model_dump(), "channels": list(body.channels), "kind": body.kind},
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            is_active=body.is_active,
            created_by=self.actor_id,
        )
        self.db.add(a)
        await self.db.flush()
        await self.audit(
            "announcement_create", "platform_announcement", a.id, {"title": a.title, "audience": a.audience}
        )
        await self.emit(
            "platform.announcement_published",
            {"announcement_id": str(a.id), "audience": a.audience},
            aggregate_type="platform_announcement",
            aggregate_id=a.id,
        )
        await self._queue_delivery(a)
        return self.out(a)

    async def update(self, announcement_id: uuid.UUID, body: AnnouncementIn) -> AnnouncementOut:
        self.require_super("Editing platform announcements")
        a = await self._get(announcement_id)
        a.title, a.body = body.title, body.body
        a.audience = {**body.audience.model_dump(), "channels": list(body.channels), "kind": body.kind}
        a.starts_at, a.ends_at, a.is_active = body.starts_at, body.ends_at, body.is_active
        await self.db.flush()
        await self.audit(
            "announcement_update", "platform_announcement", a.id, {"title": a.title, "is_active": a.is_active}
        )
        return self.out(a, await self.pget(f"ann:{a.id}", {}))

    async def delete(self, announcement_id: uuid.UUID) -> None:
        self.require_super("Deleting platform announcements")
        a = await self._get(announcement_id)
        await self.audit("announcement_delete", "platform_announcement", a.id, {"title": a.title})
        await self.db.delete(a)
        await self.pdelete(f"ann:{a.id}")
        await self.db.flush()

    async def _get(self, announcement_id: uuid.UUID) -> PlatformAnnouncement:
        a = (
            await self.db.execute(
                select(PlatformAnnouncement).where(PlatformAnnouncement.id == announcement_id).with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Announcement")
        return a

    async def _queue_delivery(self, a: PlatformAnnouncement) -> None:
        channels = set((a.audience or {}).get("channels") or [])
        if not channels & {"inapp", "email"} or not a.is_active:
            return
        from app.core.jobs import enqueue

        await enqueue(
            self.db, self.principal, "announcement.deliver", {"announcement_id": str(a.id)}, queue="notifications"
        )

    # ---- audience (rule 2) ------------------------------------------------------------------------------------------
    async def tenant_facts(self, institution_id: uuid.UUID) -> dict[str, Any]:
        row = (
            await self.db.execute(
                text(
                    "SELECT i.institution_type, p.code, p.tier FROM institutions i LEFT JOIN LATERAL (SELECT plan_id FROM "
                    "institution_subscriptions s WHERE s.institution_id = i.id ORDER BY s.starts_on DESC, s.created_at DESC LIMIT 1) s ON TRUE "
                    "LEFT JOIN subscription_plans p ON p.id = s.plan_id WHERE i.id = :i"
                ),
                {"i": institution_id},
            )
        ).first()
        return {"type": row[0] if row else None, "plan": row[1] if row else None, "tier": row[2] if row else None}

    @staticmethod
    def matches(aud: dict[str, Any], institution_id: uuid.UUID | None, facts: dict[str, Any], roles: list[str]) -> bool:
        kind = aud.get("type") or "all"
        values = [str(v) for v in aud.get("values") or []]
        if kind == "all":
            return True
        if kind == "plan":
            return facts.get("plan") in values or facts.get("tier") in values
        if kind == "institution_type":
            return facts.get("type") in values
        if kind == "institution_ids":
            return institution_id is not None and str(institution_id) in values
        if kind == "roles":
            return bool(set(values) & set(roles))
        return False

    async def active(self) -> list[AnnouncementOut]:
        from app.db.session import redis_client

        now = now_utc()
        rows = list(
            (
                await self.db.execute(
                    select(PlatformAnnouncement)
                    .where(
                        PlatformAnnouncement.is_active.is_(True),
                        or_(PlatformAnnouncement.starts_at.is_(None), PlatformAnnouncement.starts_at <= now),
                        or_(PlatformAnnouncement.ends_at.is_(None), PlatformAnnouncement.ends_at > now),
                    )
                    .order_by(PlatformAnnouncement.created_at.desc())
                )
            ).scalars()
        )
        p = self.principal
        inst = getattr(p, "institution_id", None)
        facts = await self.tenant_facts(inst) if inst else {}
        roles = list(getattr(p, "roles", None) or [])
        out = []
        for a in rows:
            aud = dict(a.audience or {})
            if "banner" not in (aud.get("channels") or ["banner"]):
                continue
            if not self.is_platform and not self.matches(aud, inst, facts, roles):
                continue
            seen = False
            with contextlib.suppress(Exception):
                seen = bool(await redis_client.exists(f"ann:{a.id}:seen:{self.actor_id}"))
            if not seen:
                out.append(self.out(a))
        return out

    async def dismiss(self, announcement_id: uuid.UUID) -> None:
        from app.db.session import redis_client

        a = (
            await self.db.execute(select(PlatformAnnouncement).where(PlatformAnnouncement.id == announcement_id))
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Announcement")
        ttl = int((a.ends_at - now_utc()).total_seconds()) + 86400 if a.ends_at else 180 * 86400
        with contextlib.suppress(Exception):
            await redis_client.set(f"ann:{a.id}:seen:{self.actor_id}", "1", ex=max(ttl, 3600))
        await self.audit(
            "announcement_dismiss",
            "platform_announcement",
            a.id,
            {"user": str(self.actor_id)},
            institution_id=getattr(self.principal, "institution_id", None),
        )

    # ---- delivery (rule 3) ------------------------------------------------------------------------------------------
    async def deliver(self, announcement_id: uuid.UUID) -> dict[str, Any]:
        a = (
            await self.db.execute(select(PlatformAnnouncement).where(PlatformAnnouncement.id == announcement_id))
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Announcement")
        aud = dict(a.audience or {})
        channels = set(aud.get("channels") or [])
        tenants = [
            r[0]
            for r in (
                await self.db.execute(
                    text("SELECT id FROM institutions WHERE deleted_at IS NULL AND status = 'active'")
                )
            ).all()
        ]
        reached = 0
        for iid in tenants:
            facts = await self.tenant_facts(iid)
            if aud.get("type") == "roles":
                audience_roles = list(aud.get("values") or [])
            elif self.matches(aud, iid, facts, []):
                audience_roles = ["institution_admin"]
            else:
                continue
            ctx = {"title": a.title, "body": a.body[:1000], "kind": aud.get("kind") or "info"}
            if "inapp" in channels:
                await self.notify("platform.announcement", iid, {"roles": audience_roles}, ctx, ["in_app"])
            if "email" in channels:
                await self.notify("platform.announcement", iid, {"roles": ["institution_admin"]}, ctx, ["email"])
            reached += 1
        doc = {"tenants": reached, "channels": sorted(channels), "at": now_utc().isoformat()}
        await self.pput(f"ann:{a.id}", doc)
        return doc
