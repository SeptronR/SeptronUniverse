"""Content items, notices, events and gallery — Prompts/40 §40.6 ``site_service`` rules 4–7.

Business rules
1. Content items: bodies pass the allow-list sanitiser; ``college:{code}`` / ``department:{code}`` sections are the
   sub-sites (college admins / HODs limited to their own prefixes, 403 otherwise); publish / unpublish need
   ``website:publish`` (college admins hold it for their sub-site); slugs unique per (institution, section).
2. Notices: category from ``website.notice_categories``; state = draft → scheduled (``publish_at`` in the future) →
   live → expired (``expires_at`` passed — the public page answers 410 with an archive link); pins and the college
   scope in ``website_meta notice:<id>``; Beat ``website.notices_schedule`` (5 min) emits ``website.notice_published``
   / ``expired`` as windows open / close; ``also_announce`` creates a Phase 24 announcement for students and staff;
   bulk publish / unpublish / expire / delete returns a per-row report.
3. Events: mirrored from Phase 25 ``events`` (scheduled / completed) — title / description / dates / first image and
   the public registration link when the Phase 25 event takes registrations; a cancelled Phase 25 event
   unpublishes its mirror (consumer); manual events too.
4. Gallery: albums and images (ordering, cover); ``bulk-upload`` enqueues ``website.gallery_bulk_upload`` (zip from
   the file service → images only, EXIF stripped by re-encoding with Pillow, thumbnails) with a per-file report.
Every change bumps the page-cache version.
"""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from app.core.errors import APIError, ErrorCode
from app.models.website import GalleryAlbum, GalleryImage, WebsiteContentItem, WebsiteEvent, WebsiteNotice
from app.schemas.website import (
    AlbumIn,
    AlbumOut,
    BulkReport,
    ContentItemIn,
    ContentItemOut,
    ImageIn,
    ImageOut,
    NoticeBulkAction,
    NoticeIn,
    NoticeOut,
    WebsiteEventIn,
    WebsiteEventOut,
)
from app.services.website.common import WebsiteBase, invalidate, sanitise, slugify


def notice_state(n: WebsiteNotice, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if not n.is_published:
        return "draft"
    if n.expires_at and n.expires_at <= now:
        return "expired"
    if n.publish_at and n.publish_at > now:
        return "scheduled"
    return "live"


class ContentService(WebsiteBase):
    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    async def list(self, section: str | None) -> list[ContentItemOut]:
        self.require("view", "update", "manage")
        q = select(WebsiteContentItem).where(WebsiteContentItem.institution_id == self.inst)
        if section:
            q = q.where(WebsiteContentItem.section == section)
        scopes = await self.section_scopes()
        rows = (await self.db.execute(q.order_by(WebsiteContentItem.section, WebsiteContentItem.sequence))).scalars()
        return [ContentItemOut.model_validate(r) for r in rows if scopes is None or r.section in scopes]

    async def _get(self, item_id: uuid.UUID) -> WebsiteContentItem:
        row = await self.db.get(WebsiteContentItem, item_id)
        if row is None or row.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Content item not found")
        await self.require_section(row.section)
        return row

    async def create(self, body: ContentItemIn) -> ContentItemOut:
        self.require("create", "update", "manage")
        await self.require_section(body.section)
        if body.is_published:
            self.require("publish")
        exists = (
            await self.db.execute(
                select(WebsiteContentItem.id).where(
                    WebsiteContentItem.institution_id == self.inst,
                    WebsiteContentItem.section == body.section,
                    WebsiteContentItem.slug == body.slug,
                )
            )
        ).first()
        if exists:
            raise APIError(409, ErrorCode.CONFLICT, "A page with this slug exists in the section", {"field": "slug"})
        row = WebsiteContentItem(
            institution_id=self.inst,
            section=body.section,
            slug=body.slug,
            title=body.title,
            body=sanitise(body.body),
            media=body.media,
            sequence=body.sequence,
            is_published=body.is_published,
        )
        self.db.add(row)
        await self.db.flush()
        await self.audit("content_create", "website_content_item", row.id, {"section": row.section, "slug": row.slug})
        await invalidate(self.inst)
        return ContentItemOut.model_validate(row)

    async def update(self, item_id: uuid.UUID, body: ContentItemIn) -> ContentItemOut:
        self.require("update", "manage")
        row = await self._get(item_id)
        await self.require_section(body.section)
        if body.is_published != row.is_published:
            self.require("publish")
        row.section, row.slug, row.title = body.section, body.slug, body.title
        row.body, row.media, row.sequence, row.is_published = (
            sanitise(body.body),
            body.media,
            body.sequence,
            body.is_published,
        )
        await self.db.flush()
        await self.audit("content_update", "website_content_item", row.id, {"slug": row.slug})
        await invalidate(self.inst)
        return ContentItemOut.model_validate(row)

    async def set_published(self, item_id: uuid.UUID, published: bool) -> ContentItemOut:
        self.require("publish")
        row = await self._get(item_id)
        row.is_published = published
        await self.db.flush()
        await self.audit("publish" if published else "unpublish", "website_content_item", row.id)
        await self.emit(
            "website.content_published" if published else "website.content_unpublished", {"id": str(row.id)}
        )
        await invalidate(self.inst)
        return ContentItemOut.model_validate(row)

    async def delete(self, item_id: uuid.UUID) -> None:
        self.require("delete", "manage")
        row = await self._get(item_id)
        await self.db.delete(row)
        await self.audit("content_delete", "website_content_item", item_id)
        await invalidate(self.inst)


class NoticeService(WebsiteBase):
    async def _out(self, n: WebsiteNotice) -> NoticeOut:
        meta = await self.meta(f"notice:{n.id}", {}) or {}
        o = NoticeOut.model_validate(n)
        o.pinned, o.state = bool(meta.get("pin")), notice_state(n)
        return o

    async def list(self, category: str | None, state: str | None) -> list[NoticeOut]:
        self.require("view", "update", "manage")
        q = select(WebsiteNotice).where(WebsiteNotice.institution_id == self.inst)
        if category:
            q = q.where(WebsiteNotice.category == category)
        out = [
            await self._out(n)
            for n in (await self.db.execute(q.order_by(WebsiteNotice.created_at.desc()).limit(500))).scalars()
        ]
        return [o for o in out if not state or o.state == state]

    async def _get(self, nid: uuid.UUID) -> WebsiteNotice:
        n = await self.db.get(WebsiteNotice, nid)
        if n is None or n.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Notice not found")
        return n

    async def _validate(self, body: NoticeIn) -> None:
        cats = list(await self.setting("notice_categories") or [])
        if cats and body.category not in cats:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown category {body.category!r}", {"field": "category"})
        if body.publish_at and body.expires_at and body.expires_at <= body.publish_at:
            raise APIError(422, ErrorCode.VALIDATION, "expires_at must be after publish_at", {"field": "expires_at"})
        if body.is_published:
            self.require("publish")

    async def create(self, body: NoticeIn) -> NoticeOut:
        self.require("create", "update", "manage")
        await self._validate(body)
        slug = body.slug or slugify(body.title)
        if (
            await self.db.execute(
                select(WebsiteNotice.id).where(WebsiteNotice.institution_id == self.inst, WebsiteNotice.slug == slug)
            )
        ).first():
            slug = f"{slug[:110]}-{uuid.uuid4().hex[:6]}"
        n = WebsiteNotice(
            institution_id=self.inst,
            title=body.title,
            slug=slug,
            body=sanitise(body.body),
            attachments=body.attachments,
            category=body.category,
            publish_at=body.publish_at,
            expires_at=body.expires_at,
            is_published=body.is_published,
        )
        self.db.add(n)
        await self.db.flush()
        await self.put_meta(
            f"notice:{n.id}", {"pin": body.pin, "college_code": body.college_code, "live_emitted": False}
        )
        await self.audit("notice_create", "website_notice", n.id, {"title": n.title, "category": n.category})
        if body.also_announce and body.is_published:
            await self.announce(n.id)
        await self._maybe_live(n)
        await invalidate(self.inst)
        return await self._out(n)

    async def update(self, nid: uuid.UUID, body: NoticeIn) -> NoticeOut:
        self.require("update", "manage")
        n = await self._get(nid)
        await self._validate(body)
        n.title, n.body, n.attachments, n.category = body.title, sanitise(body.body), body.attachments, body.category
        n.publish_at, n.expires_at, n.is_published = body.publish_at, body.expires_at, body.is_published
        await self.db.flush()
        meta = await self.meta(f"notice:{n.id}", {}) or {}
        await self.put_meta(f"notice:{n.id}", {**meta, "pin": body.pin, "college_code": body.college_code})
        await self.audit("notice_update", "website_notice", n.id, {"title": n.title})
        await self._maybe_live(n)
        await invalidate(self.inst)
        return await self._out(n)

    async def _maybe_live(self, n: WebsiteNotice) -> None:
        meta = await self.meta(f"notice:{n.id}", {}) or {}
        if notice_state(n) == "live" and not meta.get("live_emitted"):
            await self.put_meta(f"notice:{n.id}", {**meta, "live_emitted": True})
            await self.emit("website.notice_published", {"id": str(n.id), "slug": n.slug, "category": n.category}, n.id)

    async def delete(self, nid: uuid.UUID) -> None:
        self.require("delete", "manage")
        n = await self._get(nid)
        await self.db.delete(n)
        await self.put_meta(f"notice:{nid}", None)
        await self.audit("notice_delete", "website_notice", nid)
        await invalidate(self.inst)

    async def bulk(self, body: NoticeBulkAction) -> BulkReport:
        self.require("publish") if body.action != "delete" else self.require("delete", "manage")
        ok, errors = 0, []
        for nid in body.ids:
            try:
                async with self.db.begin_nested():
                    n = await self._get(nid)
                    if body.action == "publish":
                        n.is_published = True
                    elif body.action == "unpublish":
                        n.is_published = False
                    elif body.action == "expire":
                        n.expires_at = datetime.now(UTC)
                        await self.emit("website.notice_expired", {"id": str(n.id)}, n.id)
                    else:
                        await self.db.delete(n)
                    await self.db.flush()
                ok += 1
            except APIError as exc:
                errors.append({"id": str(nid), "code": exc.code, "message": exc.message})
        await self.audit(f"notice_bulk_{body.action}", "website_notice", None, {"ids": len(body.ids), "ok": ok})
        await invalidate(self.inst)
        return BulkReport(succeeded=ok, failed=len(errors), errors=errors)

    async def announce(self, nid: uuid.UUID) -> dict[str, Any]:
        """Phase 24 announcement for students and staff from a notice (``also_announce``)."""
        self.require("publish")
        n = await self._get(nid)
        await self.audit("notice_announce", "website_notice", n.id)
        from app.models.communication import Announcement

        a = Announcement(
            institution_id=self.inst,
            title=n.title[:200],
            body=n.body or n.title,
            category="website",
            audience_rules={"roles": ["student", "faculty", "parent"]},
            publish_at=datetime.now(UTC),
            expires_at=n.expires_at,
            requires_ack=False,
            is_pinned=False,
            is_active=True,
            created_by=getattr(self.principal, "id", None),
        )
        self.db.add(a)
        await self.db.flush()
        from app.core.notifications.notify import notify_event

        await notify_event(
            self.db,
            self.inst,
            "website.notice_published",
            audience={"roles": ["student", "faculty", "parent"]},
            context={
                "title": n.title,
                "category": n.category,
                "route": f"/announcements/{a.id}",
                "announcement_id": str(a.id),
            },
            channels=["in_app", "push"],
        )
        return {"announcement_id": str(a.id)}


class WebsiteEventService(WebsiteBase):
    async def _out(self, e: WebsiteEvent) -> WebsiteEventOut:
        o = WebsiteEventOut.model_validate(e)
        if e.event_id:
            o.registration_url = f"/api/v1/events/public/{e.event_id}/register"
        return o

    async def list(self) -> list[WebsiteEventOut]:
        self.require("view", "update", "manage")
        rows = (
            await self.db.execute(
                select(WebsiteEvent)
                .where(WebsiteEvent.institution_id == self.inst)
                .order_by(WebsiteEvent.starts_at.desc())
            )
        ).scalars()
        return [await self._out(e) for e in rows]

    async def create(self, body: WebsiteEventIn) -> WebsiteEventOut:
        self.require("create", "update", "manage")
        if body.is_published:
            self.require("publish")
        e = WebsiteEvent(
            institution_id=self.inst,
            event_id=body.event_id,
            title=body.title,
            slug=body.slug or f"{slugify(body.title, 100)}-{uuid.uuid4().hex[:4]}",
            description=sanitise(body.description),
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            image_url=body.image_url,
            is_published=body.is_published,
        )
        self.db.add(e)
        await self.db.flush()
        await self.audit("event_create", "website_event", e.id, {"title": e.title})
        await self.audit("change", "website_event", None)
        await invalidate(self.inst)
        return await self._out(e)

    async def update(self, eid: uuid.UUID, body: WebsiteEventIn) -> WebsiteEventOut:
        self.require("update", "manage")
        e = await self.db.get(WebsiteEvent, eid)
        if e is None or e.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Event not found")
        if body.is_published != e.is_published:
            self.require("publish")
        e.title, e.description, e.starts_at, e.ends_at = (
            body.title,
            sanitise(body.description),
            body.starts_at,
            body.ends_at,
        )
        e.image_url, e.is_published = body.image_url, body.is_published
        await self.db.flush()
        await self.audit("change", "website_event", None)
        await invalidate(self.inst)
        return await self._out(e)

    async def delete(self, eid: uuid.UUID) -> None:
        self.require("delete", "manage")
        await self.db.execute(
            delete(WebsiteEvent).where(WebsiteEvent.id == eid, WebsiteEvent.institution_id == self.inst)
        )
        await self.audit("change", "website_event", None)
        await invalidate(self.inst)

    async def mirror(self, event_ids: Sequence[uuid.UUID], publish: bool) -> builtins.list[WebsiteEventOut]:
        self.require("publish") if publish else self.require("create", "manage")
        from datetime import time

        from app.models.events import Event

        out = []
        for eid in event_ids:
            ev = await self.db.get(Event, eid)
            if ev is None or ev.institution_id != self.inst or ev.deleted_at is not None:
                raise APIError(404, ErrorCode.NOT_FOUND, f"Event {eid} not found")
            if ev.status not in ("scheduled", "approved", "completed", "published"):
                raise APIError(
                    409, ErrorCode.RULE_VIOLATION, f"Event {ev.title!r} is {ev.status}", {"event_id": str(eid)}
                )
            existing = (
                await self.db.execute(
                    select(WebsiteEvent).where(WebsiteEvent.institution_id == self.inst, WebsiteEvent.event_id == eid)
                )
            ).scalar_one_or_none()
            images = ev.images if isinstance(ev.images, list) else []
            first = images[0] if images else None
            img = first.get("url") if isinstance(first, dict) else first
            row = existing or WebsiteEvent(
                institution_id=self.inst, event_id=eid, slug=f"{slugify(ev.title, 100)}-{str(eid)[:4]}"
            )
            row.title, row.description = ev.title, sanitise(ev.description)
            row.starts_at = datetime.combine(ev.from_on, time(9, 0), UTC) if ev.from_on else None
            row.ends_at = datetime.combine(ev.to_on or ev.from_on, time(18, 0), UTC) if ev.from_on else None
            row.image_url, row.is_published = img, publish
            if existing is None:
                self.db.add(row)
            await self.db.flush()
            await self.emit("website.event_mirrored", {"event_id": str(eid), "website_event_id": str(row.id)}, row.id)
            out.append(await self._out(row))
        await self.audit("change", "website_event", None)
        await invalidate(self.inst)
        return out


class GalleryService(WebsiteBase):
    async def albums(self, with_images: bool = False) -> list[AlbumOut]:
        rows = list(
            (
                await self.db.execute(
                    select(GalleryAlbum).where(GalleryAlbum.institution_id == self.inst).order_by(GalleryAlbum.sequence)
                )
            ).scalars()
        )
        out = []
        for a in rows:
            o = AlbumOut.model_validate(a)
            imgs = list(
                (
                    await self.db.execute(
                        select(GalleryImage).where(GalleryImage.album_id == a.id).order_by(GalleryImage.sequence)
                    )
                ).scalars()
            )
            o.image_count = len(imgs)
            if with_images:
                o.images = [ImageOut.model_validate(i) for i in imgs]
            out.append(o)
        return out

    async def _album(self, aid: uuid.UUID) -> GalleryAlbum:
        a = await self.db.get(GalleryAlbum, aid)
        if a is None or a.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Album not found")
        return a

    async def create_album(self, body: AlbumIn) -> AlbumOut:
        self.require("create", "manage")
        a = GalleryAlbum(institution_id=self.inst, **body.model_dump())
        self.db.add(a)
        await self.db.flush()
        await self.emit("website.gallery_updated", {"album_id": str(a.id)}, a.id)
        await self.audit("change", "gallery", None)
        await invalidate(self.inst)
        return AlbumOut.model_validate(a)

    async def update_album(self, aid: uuid.UUID, body: AlbumIn) -> AlbumOut:
        self.require("update", "manage")
        a = await self._album(aid)
        for k, v in body.model_dump().items():
            setattr(a, k, v)
        await self.db.flush()
        await self.audit("change", "gallery", None)
        await invalidate(self.inst)
        return AlbumOut.model_validate(a)

    async def delete_album(self, aid: uuid.UUID) -> None:
        self.require("delete", "manage")
        await self.db.delete(await self._album(aid))
        await self.audit("change", "gallery", None)
        await invalidate(self.inst)

    async def add_image(self, aid: uuid.UUID, body: ImageIn) -> ImageOut:
        self.require("create", "manage")
        await self._album(aid)
        i = GalleryImage(institution_id=self.inst, album_id=aid, **body.model_dump())
        self.db.add(i)
        await self.db.flush()
        await self.audit("change", "gallery", None)
        await invalidate(self.inst)
        return ImageOut.model_validate(i)

    async def update_image(self, iid: uuid.UUID, body: ImageIn) -> ImageOut:
        self.require("update", "manage")
        i = await self.db.get(GalleryImage, iid)
        if i is None or i.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Image not found")
        i.image_url, i.caption, i.sequence = body.image_url, body.caption, body.sequence
        await self.db.flush()
        await self.audit("change", "gallery", None)
        await invalidate(self.inst)
        return ImageOut.model_validate(i)

    async def delete_image(self, iid: uuid.UUID) -> None:
        self.require("delete", "manage")
        await self.db.execute(
            delete(GalleryImage).where(GalleryImage.id == iid, GalleryImage.institution_id == self.inst)
        )
        await self.audit("change", "gallery", None)
        await invalidate(self.inst)

    async def bulk_upload(self, aid: uuid.UUID, zip_url: str) -> dict[str, Any]:
        self.require("create", "manage")
        await self._album(aid)
        from app.core.jobs import enqueue

        job = await enqueue(
            self.db,
            self.principal,
            "website.gallery_bulk_upload",
            {"album_id": str(aid), "zip_url": zip_url},
            queue="reports",
        )
        return {"job_id": str(job.id)}
