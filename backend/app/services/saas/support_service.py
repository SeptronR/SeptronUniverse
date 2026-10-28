"""Support desk, help centre authoring and feedback triage — Prompts/38 §38.6 ``support_service``.

Business rules
1. **Tickets** (``support_tickets``; facts without columns in ``messages``: ``{"thread": [...], "meta": {category,
   sla_due_at, breached, csat, related_feedback, reopened}}``). Tenants raise with ``support:create`` (institution
   admin through ``support:manage``) — always for their own institution; platform staff may raise on behalf of a
   tenant. ``ticket_number`` ``SPT/<yyyy>/<nnnn>`` from the platform sequence ``seq:spt:<yyyy>``; SLA due =
   created + ``support.sla_hours[priority]``; auto-assignment round-robin over ``support.oncall``.
   Visibility: a tenant sees its institution's tickets only (404 otherwise — also RLS); internal notes are never
   returned to tenants; platform staff see all (support-agent reads audited, PII masked).
2. **Status machine** ``open → in_progress → waiting (on tenant) → resolved → closed`` (``TICKET_TRANSITIONS``);
   a tenant reply on ``waiting`` returns it to ``in_progress``; tenants may close or reopen (resolved / closed →
   in_progress) within 14 days of resolution (409 after); support agents cannot close ``billing`` tickets (403);
   auto-close 5 days after resolution (Beat ``support.auto_close``); CSAT ``rate`` (1–5) closes a resolved ticket.
3. **SLA scan** (every 15 min): open tickets past ``sla_due_at`` are flagged ``breached`` once, emit
   ``support.ticket_sla_breached`` and escalate to the super admins.
4. **Diagnostics** (platform): versions (API, pack, mobile minimums), feature flags diff vs the plan, failing
   connections, recent failed jobs / consumer errors, subscription state, a Sentry search link.
5. **Help centre**: platform articles (``platform:help``) and institution articles (``settings:manage`` of the
   tenant; same slug overrides the platform article for that tenant only); contextual slugs ``help:<route>``;
   ``audience {roles, portals, public}``; search; JSON export / import of platform articles (``docs/help`` → seed);
   ``help.article_published`` on publish.
6. **Feedback triage** (``platform:support``): board by status / category / rating / tenant (PII masked for support
   agents), triage with a note and an optional response (``feedback.responded`` to the author), convert to a
   ticket (linked both ways). Notes / links in ``platform_settings['feedback:<id>']``.
"""

import uuid
from collections.abc import Awaitable
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, text

from app.enums.saas import TICKET_AUTO_CLOSE_DAYS, TICKET_REOPEN_DAYS, TICKET_TRANSITIONS
from app.models.platform import FeedbackEntry, HelpArticle
from app.models.saas import SupportTicket
from app.schemas.saas import (
    DiagnosticsOut,
    FeedbackAdminOut,
    FeedbackTriage,
    HelpArticleAdminOut,
    HelpArticleIn,
    HelpImport,
    TicketAssign,
    TicketCreate,
    TicketMessage,
    TicketOut,
    TicketRate,
    TicketReply,
    TicketStatusChange,
)
from app.services.saas.common import PlatformBase, conflict, forbidden, not_found, now_utc, rule, unprocessable


def _parse(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


class SupportService(PlatformBase):
    audit_module = "support"

    # ---- helpers ----------------------------------------------------------------------------------------------
    def _doc(self, t: SupportTicket) -> dict[str, Any]:
        doc = t.messages if isinstance(t.messages, dict) else {"thread": list(t.messages or []), "meta": {}}
        doc.setdefault("thread", [])
        doc.setdefault("meta", {})
        return dict(doc)

    async def _ticket(self, ticket_id: uuid.UUID, *, lock: bool = False) -> SupportTicket:
        q = select(SupportTicket).where(SupportTicket.id == ticket_id)
        if lock:
            q = q.with_for_update()
        t = (await self.db.execute(q)).scalar_one_or_none()
        if t is None:
            raise not_found("Ticket")
        if not self.is_platform:
            inst = getattr(self.principal, "institution_id", None)
            if t.institution_id is None or t.institution_id != inst or not self._tenant_reads():
                raise not_found("Ticket")
            if (
                not self.can("support", "manage")
                and not self.can("support", "view_all")
                and t.raised_by != self.actor_id
            ):
                raise not_found("Ticket")
        return t

    def _tenant_reads(self) -> bool:
        return self.can("support", "create") or self.can("support", "view") or self.can("support", "manage")

    async def out(self, t: SupportTicket) -> TicketOut:
        doc = self._doc(t)
        meta = doc["meta"]
        thread = [m for m in doc["thread"] if self.is_platform or not m.get("internal")]
        ids = [t.raised_by, t.assigned_to] + [uuid.UUID(m["by"]) for m in thread if m.get("by")]
        users = await self.user_refs([i for i in ids if i])
        insts = await self.institution_refs([t.institution_id])
        resolved = t.resolved_at
        return TicketOut(
            id=t.id,
            ticket_number=t.ticket_number,
            institution=insts.get(t.institution_id) if t.institution_id else None,
            subject=t.subject,
            description=t.description,
            priority=t.priority,
            module=t.module,
            category=meta.get("category"),
            status=t.status,
            raised_by=users.get(t.raised_by) if t.raised_by else None,
            assigned_to=users.get(t.assigned_to) if t.assigned_to else None,
            messages=[
                TicketMessage(
                    id=str(m.get("id")),
                    by=users.get(uuid.UUID(m["by"]), {"id": m["by"]}) if m.get("by") else {"name": "system"},
                    at=_parse(m.get("at")) or t.created_at,
                    text=str(m.get("text") or ""),
                    attachments=list(m.get("attachments") or []),
                    internal=bool(m.get("internal")),
                    side=str(m.get("side") or "tenant"),
                )
                for m in thread
            ],
            sla_due_at=_parse(meta.get("sla_due_at")),
            breached=bool(meta.get("breached")),
            csat=meta.get("csat"),
            related_feedback=list(meta.get("related_feedback") or []),
            created_at=t.created_at,
            updated_at=t.updated_at,
            resolved_at=resolved,
            can_reopen=bool(
                t.status in ("resolved", "closed")
                and resolved
                and now_utc() - resolved <= timedelta(days=TICKET_REOPEN_DAYS)
            ),
        )

    def _message(self, text_: str, attachments: list[str], internal: bool, side: str | None = None) -> dict[str, Any]:
        return {
            "id": uuid.uuid4().hex[:12],
            "by": str(self.actor_id) if self.actor_id else None,
            "at": now_utc().isoformat(),
            "text": text_,
            "attachments": attachments,
            "internal": internal,
            "side": side or ("platform" if self.is_platform else "tenant"),
        }

    # ---- tickets (rule 1) -------------------------------------------------------------------------------------
    async def create(self, body: TicketCreate) -> TicketOut:
        if self.is_platform:
            self.require_platform("platform", "support")
            inst = body.institution_id
            if inst is not None:
                await self.institution(inst)
        else:
            if not (self.can("support", "create") or self.can("support", "manage")):
                raise forbidden("support:create required")
            inst = getattr(self.principal, "institution_id", None)
            if inst is None or (body.institution_id and body.institution_id != inst):
                raise forbidden("Tickets are raised for your own institution")
        categories = await self.setting("support.categories") or []
        if categories and body.category not in categories:
            raise unprocessable(f"Unknown category {body.category!r}", field="category", allowed=categories)
        year = now_utc().year
        number = f"SPT/{year}/{await self.next_sequence(f'spt:{year}')}"
        sla_hours = (await self.setting("support.sla_hours") or {}).get(body.priority, 48)
        assignee = await self._oncall()
        t = SupportTicket(
            institution_id=inst,
            ticket_number=number,
            raised_by=self.actor_id,
            subject=body.subject,
            description=body.description,
            priority=body.priority,
            module=body.module,
            status="open",
            assigned_to=assignee,
            messages={
                "thread": [],
                "meta": {
                    "category": body.category,
                    "sla_due_at": (now_utc() + timedelta(hours=int(sla_hours))).isoformat(),
                    "breached": False,
                    "attachments": body.attachments,
                    "on_behalf": self.is_platform,
                },
            },
        )
        self.db.add(t)
        await self.db.flush()
        await self.audit(
            "ticket_create",
            "support_ticket",
            t.id,
            {"number": number, "priority": body.priority, "category": body.category},
            institution_id=inst,
        )
        await self.emit(
            "support.ticket_created",
            {"ticket_id": str(t.id), "number": number, "priority": body.priority},
            institution_id=inst,
            aggregate_type="support_ticket",
            aggregate_id=t.id,
        )
        ctx = {"number": number, "subject": body.subject, "priority": body.priority}
        await self.notify(
            "support.ticket_created",
            None,
            {"user_ids": [str(assignee)] if assignee else await self.super_admin_ids()},
            ctx,
        )
        if self.is_platform and inst:
            await self.notify_tenant_admins(inst, "support.ticket_created", ctx)
        return await self.out(t)

    async def _oncall(self) -> uuid.UUID | None:
        oncall = [str(x) for x in (await self.setting("support.oncall") or []) if x]
        if not oncall:
            return None
        n = int(await self.next_sequence("spt:rr", width=1))
        try:
            return uuid.UUID(oncall[n % len(oncall)])
        except ValueError:
            return None

    async def list_tickets(
        self,
        scope: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        institution_id: uuid.UUID | None = None,
        q: str | None = None,
    ) -> tuple[list[TicketOut], dict[str, Any]]:
        stmt = select(SupportTicket).order_by(SupportTicket.created_at.desc()).limit(500)
        if self.is_platform:
            if self.is_support:
                self.require_platform("support", "view_all")
            if scope in ("mine", "own"):
                stmt = stmt.where(SupportTicket.assigned_to == self.actor_id)
            if institution_id:
                stmt = stmt.where(SupportTicket.institution_id == institution_id)
            visibility = {"self": False, "scopes": ["own", "all"], "default": "all"}
        else:
            if not self._tenant_reads():
                raise forbidden("support:view required")
            inst = getattr(self.principal, "institution_id", None)
            stmt = stmt.where(SupportTicket.institution_id == inst)
            if scope in ("mine", "own") or not (self.can("support", "manage") or self.can("support", "view_all")):
                stmt = stmt.where(SupportTicket.raised_by == self.actor_id)
                visibility = {"self": True}
            else:
                visibility = {"self": False, "scopes": ["own", "all"], "default": "all"}
        if status:
            stmt = stmt.where(SupportTicket.status == status)
        if priority:
            stmt = stmt.where(SupportTicket.priority == priority)
        if q:
            stmt = stmt.where(SupportTicket.subject.ilike(f"%{q}%") | SupportTicket.ticket_number.ilike(f"%{q}%"))
        rows = list((await self.db.execute(stmt)).scalars())
        if self.is_support:
            for inst_id in {r.institution_id for r in rows if r.institution_id}:
                await self.audit_read(inst_id, "support_tickets")
        return [await self.out(r) for r in rows], visibility

    async def get(self, ticket_id: uuid.UUID) -> TicketOut:
        t = await self._ticket(ticket_id)
        await self.audit_read(t.institution_id, "support_ticket", t.id)
        return await self.out(t)

    async def reply(self, ticket_id: uuid.UUID, body: TicketReply) -> TicketOut:
        t = await self._ticket(ticket_id, lock=True)
        if self.is_platform:
            self.require_platform("platform", "support")
        elif body.internal:
            raise forbidden("Internal notes are for platform staff")
        if t.status == "closed":
            raise rule("The ticket is closed — reopen it first")
        doc = self._doc(t)
        doc["thread"] = [*doc["thread"], self._message(body.text, body.attachments, body.internal)]
        old = t.status
        if (
            not self.is_platform
            and t.status == "waiting"
            or self.is_platform
            and t.status == "open"
            and not body.internal
        ):
            t.status = "in_progress"
        t.messages = doc
        await self.db.flush()
        await self.audit(
            "ticket_reply",
            "support_ticket",
            t.id,
            {"number": t.ticket_number, "internal": body.internal, "status": t.status},
            institution_id=t.institution_id,
        )
        await self.emit(
            "support.ticket_replied",
            {"ticket_id": str(t.id), "internal": body.internal, "side": "platform" if self.is_platform else "tenant"},
            institution_id=t.institution_id,
            aggregate_type="support_ticket",
            aggregate_id=t.id,
        )
        if old != t.status:
            await self.emit(
                "support.ticket_status_changed",
                {"ticket_id": str(t.id), "from": old, "to": t.status},
                institution_id=t.institution_id,
                aggregate_type="support_ticket",
                aggregate_id=t.id,
            )
        ctx = {"number": t.ticket_number, "subject": t.subject, "text": body.text[:300]}
        if not body.internal and self.is_platform and t.raised_by:
            await self.notify(
                "support.ticket_replied", t.institution_id, {"user_ids": [str(t.raised_by)]}, ctx, ["in_app", "email"]
            )
        elif not body.internal and not self.is_platform:
            await self.notify(
                "support.ticket_replied",
                None,
                {"user_ids": [str(t.assigned_to)] if t.assigned_to else await self.super_admin_ids()},
                ctx,
            )
        return await self.out(t)

    async def assign(self, ticket_id: uuid.UUID, body: TicketAssign) -> TicketOut:
        self.require_platform("platform", "support")
        t = await self._ticket(ticket_id, lock=True)
        if self.is_support and body.user_id != self.actor_id:
            raise forbidden("Support agents assign tickets to themselves")
        target = (
            await self.db.execute(
                text(
                    "SELECT u.id FROM users u WHERE u.id = :u AND u.is_active AND u.institution_id IS NULL AND (u.is_super_admin "
                    "OR EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = u.id AND r.slug = 'support_agent'))"
                ),
                {"u": body.user_id},
            )
        ).first()
        if target is None:
            raise unprocessable("Assign to a super admin or support agent", field="user_id")
        old = t.assigned_to
        t.assigned_to = body.user_id
        await self.db.flush()
        await self.audit(
            "ticket_assign",
            "support_ticket",
            t.id,
            {"assigned_to": body.user_id},
            old={"assigned_to": old},
            institution_id=t.institution_id,
        )
        await self.emit(
            "support.ticket_assigned",
            {"ticket_id": str(t.id), "assigned_to": str(body.user_id)},
            institution_id=t.institution_id,
            aggregate_type="support_ticket",
            aggregate_id=t.id,
        )
        if body.user_id != self.actor_id:
            await self.notify(
                "support.ticket_created",
                None,
                {"user_ids": [str(body.user_id)]},
                {"number": t.ticket_number, "subject": t.subject, "priority": t.priority},
            )
        return await self.out(t)

    async def change_status(self, ticket_id: uuid.UUID, body: TicketStatusChange) -> TicketOut:
        t = await self._ticket(ticket_id, lock=True)
        doc = self._doc(t)
        old = t.status
        if body.status == old:
            raise conflict(f"The ticket is already {old}")
        if body.status not in TICKET_TRANSITIONS.get(old, ()):
            raise rule(f"Cannot move a ticket from {old} to {body.status}")
        reopening = old in ("resolved", "closed") and body.status == "in_progress"
        if self.is_platform:
            self.require_platform("platform", "support")
            if self.is_support and body.status == "closed" and doc["meta"].get("category") == "billing":
                raise forbidden("Billing tickets are closed by the super admin")
        else:
            if not (self.can("support", "manage") or t.raised_by == self.actor_id):
                raise forbidden("Only the raiser or the institution admin changes the ticket")
            if body.status not in ("closed", "in_progress") or (body.status == "in_progress" and not reopening):
                raise forbidden("Tenants may close or reopen tickets")
        if reopening:
            resolved = t.resolved_at or t.updated_at
            if now_utc() - resolved > timedelta(days=TICKET_REOPEN_DAYS):
                raise rule(
                    f"Tickets can be reopened within {TICKET_REOPEN_DAYS} days of resolution", code="REOPEN_WINDOW"
                )
            doc["meta"]["reopened"] = int(doc["meta"].get("reopened") or 0) + 1
        t.status = body.status
        if body.status == "resolved":
            t.resolved_at = now_utc()
        if body.resolution:
            doc["thread"] = [*doc["thread"], self._message(f"Resolution: {body.resolution}", [], False)]
        t.messages = doc
        await self.db.flush()
        await self.audit(
            "ticket_status",
            "support_ticket",
            t.id,
            {"from": old, "to": t.status, "resolution": body.resolution},
            institution_id=t.institution_id,
        )
        await self.emit(
            "support.ticket_status_changed",
            {"ticket_id": str(t.id), "from": old, "to": t.status},
            institution_id=t.institution_id,
            aggregate_type="support_ticket",
            aggregate_id=t.id,
        )
        event = {"resolved": "support.ticket_resolved", "closed": "support.ticket_closed"}.get(t.status)
        if event and t.raised_by:
            await self.notify(
                event,
                t.institution_id,
                {"user_ids": [str(t.raised_by)]},
                {"number": t.ticket_number, "subject": t.subject, "resolution": body.resolution or ""},
                ["in_app", "email"],
            )
        return await self.out(t)

    async def rate(self, ticket_id: uuid.UUID, body: TicketRate) -> TicketOut:
        t = await self._ticket(ticket_id, lock=True)
        if self.is_platform:
            raise forbidden("The tenant rates the ticket")
        if t.status not in ("resolved", "closed"):
            raise rule("Rate a ticket once it is resolved")
        doc = self._doc(t)
        doc["meta"]["csat"] = body.rating
        doc["meta"]["csat_comment"] = body.comment
        old = t.status
        t.status = "closed"
        t.messages = doc
        await self.db.flush()
        await self.audit(
            "ticket_rate", "support_ticket", t.id, {"rating": body.rating}, institution_id=t.institution_id
        )
        await self.emit(
            "support.ticket_rated",
            {"ticket_id": str(t.id), "rating": body.rating},
            institution_id=t.institution_id,
            aggregate_type="support_ticket",
            aggregate_id=t.id,
        )
        if old != "closed":
            await self.emit(
                "support.ticket_status_changed",
                {"ticket_id": str(t.id), "from": old, "to": "closed"},
                institution_id=t.institution_id,
                aggregate_type="support_ticket",
                aggregate_id=t.id,
            )
        return await self.out(t)

    # ---- diagnostics (rule 4) -----------------------------------------------------------------------------------
    async def diagnostics(self, ticket_id: uuid.UUID) -> DiagnosticsOut:
        from app.core.config import settings
        from app.services.platform_service import API_VERSION

        self.require_platform("platform", "support")
        t = await self._ticket(ticket_id)
        inst_id = t.institution_id
        await self.audit_read(inst_id, "diagnostics", t.id)
        versions: dict[str, Any] = {"api": API_VERSION, "environment": getattr(settings, "ENVIRONMENT", None)}
        flags_diff: dict[str, Any] = {}
        failing: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        sub = None
        if inst_id:
            inst = await self.institution(inst_id)
            versions.update(
                pack=inst.regulatory_pack, pack_version=inst.pack_version, mobile=await self.pget("mobile.min_versions")
            )
            plan_row = (
                await self.db.execute(
                    text(
                        "SELECT p.code, p.enabled_features, s.status, s.ends_on FROM institution_subscriptions s JOIN subscription_plans p "
                        "ON p.id = s.plan_id WHERE s.institution_id = :i ORDER BY s.starts_on DESC, s.created_at DESC LIMIT 1"
                    ),
                    {"i": inst_id},
                )
            ).first()
            plan_keys = set(plan_row[1] or []) if plan_row else set()
            sub = {"plan": plan_row[0], "status": plan_row[2], "ends_on": plan_row[3]} if plan_row else None
            flags = (
                await self.db.execute(
                    text(
                        "SELECT feature_key, platform_enabled, institution_enabled, source FROM institution_feature_flags WHERE institution_id = :i"
                    ),
                    {"i": inst_id},
                )
            ).all()
            flags_diff = {
                "on_not_in_plan": sorted(k for k, pe, ie, src in flags if pe and k not in plan_keys),
                "plan_but_off": sorted(
                    k for k, pe, ie, src in flags if k in plan_keys and not (pe and (ie is None or ie))
                ),
                "overrides": sorted(k for k, pe, ie, src in flags if src == "override"),
            }
            failing = [
                dict(r)
                for r in (
                    await self.db.execute(
                        text(
                            "SELECT id, capability, provider, status, last_error, last_health_at FROM integration_connections "
                            "WHERE institution_id = :i AND status IN ('failed','degraded')"
                        ),
                        {"i": inst_id},
                    )
                ).mappings()
            ]
            errors = [
                dict(r)
                for r in (
                    await self.db.execute(
                        text(
                            "SELECT job_type AS source, error, finished_at AS at FROM background_jobs WHERE institution_id = :i "
                            "AND status = 'failed' ORDER BY finished_at DESC NULLS LAST LIMIT 10"
                        ),
                        {"i": inst_id},
                    )
                ).mappings()
            ]
        sentry = getattr(settings, "SENTRY_DSN", None)
        return DiagnosticsOut(
            ticket_number=t.ticket_number,
            institution=(await self.institution_refs([inst_id])).get(inst_id) if inst_id else None,
            versions=versions,
            flags_diff=flags_diff,
            failing_connections=failing,
            last_errors=errors,
            subscription=sub,
            sentry_url=f"https://sentry.io/issues/?query=institution_id%3A{inst_id}" if sentry and inst_id else None,
            generated_at=now_utc(),
        )

    # ---- Beat (rules 2–3) ---------------------------------------------------------------------------------------
    async def sla_scan(self) -> int:
        rows = list(
            (
                await self.db.execute(
                    select(SupportTicket)
                    .where(SupportTicket.status.in_(("open", "in_progress", "waiting")))
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        breached = 0
        for t in rows:
            doc = self._doc(t)
            due = _parse(doc["meta"].get("sla_due_at"))
            if due is None or doc["meta"].get("breached") or due > now_utc() or t.status == "waiting":
                continue
            doc["meta"]["breached"] = True
            doc["meta"]["breached_at"] = now_utc().isoformat()
            t.messages = doc
            breached += 1
            await self.emit(
                "support.ticket_sla_breached",
                {"ticket_id": str(t.id), "number": t.ticket_number, "priority": t.priority},
                institution_id=t.institution_id,
                aggregate_type="support_ticket",
                aggregate_id=t.id,
            )
            await self.notify_platform(
                "support.sla_breached", {"number": t.ticket_number, "subject": t.subject, "priority": t.priority}
            )
        await self.db.flush()
        return breached

    async def auto_close(self) -> int:
        cutoff = now_utc() - timedelta(days=TICKET_AUTO_CLOSE_DAYS)
        rows = list(
            (
                await self.db.execute(
                    select(SupportTicket)
                    .where(SupportTicket.status == "resolved", SupportTicket.resolved_at < cutoff)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for t in rows:
            t.status = "closed"
            await self.audit(
                "ticket_auto_close",
                "support_ticket",
                t.id,
                {"number": t.ticket_number},
                institution_id=t.institution_id,
            )
            await self.emit(
                "support.ticket_status_changed",
                {"ticket_id": str(t.id), "from": "resolved", "to": "closed", "auto": True},
                institution_id=t.institution_id,
                aggregate_type="support_ticket",
                aggregate_id=t.id,
            )
        await self.db.flush()
        return len(rows)

    async def open_by_priority(self) -> tuple[dict[str, int], int]:
        rows = (
            await self.db.execute(
                text(
                    "SELECT priority, count(*), count(*) FILTER (WHERE (messages->'meta'->>'breached')::boolean) FROM support_tickets "
                    "WHERE status IN ('open','in_progress','waiting') GROUP BY priority"
                )
            )
        ).all()
        return {p: int(n) for p, n, _ in rows}, sum(int(b or 0) for _, _, b in rows)

    # ---- help centre (rule 5) -----------------------------------------------------------------------------------
    def _help_scope(self) -> uuid.UUID | None:
        """``None`` → platform articles (``platform:help``); else the tenant's own institution (``settings:manage``)."""
        if self.is_platform:
            if not (self.is_super or self.can("platform", "help")):
                raise forbidden("platform:help required")
            return None
        if not self.can("settings", "manage"):
            raise forbidden("settings:manage required")
        inst = getattr(self.principal, "institution_id", None)
        if inst is None:
            raise forbidden("An institution context is required")
        return inst  # type: ignore[no-any-return]

    async def _helpful(self, slugs: list[str]) -> dict[str, dict[str, int]]:
        import contextlib

        from app.db.session import redis_client

        out: dict[str, dict[str, int]] = {}
        with contextlib.suppress(Exception):
            for s in slugs:
                v = await cast(Awaitable[dict[str, str]], redis_client.hgetall(f"help:helpful:{s}"))
                out[s] = {k: int(x) for k, x in (v or {}).items()}
        return out

    def _help_out(self, a: HelpArticle, helpful: dict[str, int] | None = None) -> HelpArticleAdminOut:
        return HelpArticleAdminOut(
            id=a.id,
            slug=a.slug,
            title=a.title,
            body=a.body,
            module=a.module,
            audience=a.audience if isinstance(a.audience, dict) else {"roles": list(a.audience or [])},
            is_published=a.is_published,
            is_platform=a.institution_id is None,
            institution_id=a.institution_id,
            helpful=helpful or {},
            updated_at=a.updated_at,
        )

    async def help_admin_list(self, q: str | None = None, module: str | None = None) -> list[HelpArticleAdminOut]:
        scope = self._help_scope()
        stmt = select(HelpArticle).order_by(HelpArticle.module, HelpArticle.slug)
        stmt = stmt.where(
            HelpArticle.institution_id.is_(None) if scope is None else HelpArticle.institution_id == scope
        )
        if module:
            stmt = stmt.where(HelpArticle.module == module)
        if q:
            stmt = stmt.where(HelpArticle.title.ilike(f"%{q}%") | HelpArticle.slug.ilike(f"%{q}%"))
        rows = list((await self.db.execute(stmt)).scalars())
        helpful = await self._helpful([r.slug for r in rows])
        return [self._help_out(r, helpful.get(r.slug)) for r in rows]

    async def help_create(self, body: HelpArticleIn) -> HelpArticleAdminOut:
        scope = self._help_scope()
        exists = (
            await self.db.execute(
                select(HelpArticle.id).where(
                    HelpArticle.slug == body.slug,
                    HelpArticle.institution_id.is_(None) if scope is None else HelpArticle.institution_id == scope,
                )
            )
        ).first()
        if exists:
            raise conflict(f"Slug {body.slug!r} exists", field="slug")
        a = HelpArticle(
            institution_id=scope,
            slug=body.slug,
            title=body.title,
            body=body.body,
            module=body.module,
            audience=body.audience.model_dump(),
            is_published=body.is_published,
        )
        self.db.add(a)
        await self.db.flush()
        await self.audit(
            "help_create",
            "help_article",
            a.id,
            {"slug": a.slug, "platform": scope is None},
            institution_id=scope,
            module="settings" if scope else None,
        )
        if a.is_published:
            await self.emit(
                "help.article_published",
                {"slug": a.slug, "platform": scope is None},
                institution_id=scope,
                aggregate_type="help_article",
                aggregate_id=a.id,
            )
        return self._help_out(a)

    async def _article(self, article_id: uuid.UUID, scope: uuid.UUID | None) -> HelpArticle:
        a = (await self.db.execute(select(HelpArticle).where(HelpArticle.id == article_id))).scalar_one_or_none()
        if a is None or a.institution_id != scope:
            raise not_found("Help article")
        return a

    async def help_update(self, article_id: uuid.UUID, body: HelpArticleIn) -> HelpArticleAdminOut:
        scope = self._help_scope()
        a = await self._article(article_id, scope)
        was_published = a.is_published
        a.slug, a.title, a.body, a.module = body.slug, body.title, body.body, body.module
        a.audience, a.is_published = body.audience.model_dump(), body.is_published
        await self.db.flush()
        await self.audit(
            "help_update",
            "help_article",
            a.id,
            {"slug": a.slug, "published": a.is_published},
            institution_id=scope,
            module="settings" if scope else None,
        )
        if a.is_published and not was_published:
            await self.emit(
                "help.article_published",
                {"slug": a.slug, "platform": scope is None},
                institution_id=scope,
                aggregate_type="help_article",
                aggregate_id=a.id,
            )
        return self._help_out(a)

    async def help_delete(self, article_id: uuid.UUID) -> None:
        scope = self._help_scope()
        a = await self._article(article_id, scope)
        await self.audit(
            "help_delete",
            "help_article",
            a.id,
            {"slug": a.slug},
            institution_id=scope,
            module="settings" if scope else None,
        )
        await self.db.delete(a)
        await self.db.flush()

    async def help_export(self) -> list[dict[str, Any]]:
        if self._help_scope() is not None:
            raise forbidden("Exports cover platform articles")
        rows = list(
            (
                await self.db.execute(
                    select(HelpArticle).where(HelpArticle.institution_id.is_(None)).order_by(HelpArticle.slug)
                )
            ).scalars()
        )
        return [
            {
                "slug": r.slug,
                "title": r.title,
                "body": r.body,
                "module": r.module,
                "audience": r.audience if isinstance(r.audience, dict) else {},
                "is_published": r.is_published,
            }
            for r in rows
        ]

    async def help_import(self, body: HelpImport) -> dict[str, int]:
        if self._help_scope() is not None:
            raise forbidden("Imports cover platform articles")
        created = updated = 0
        for item in body.articles:
            a = (
                await self.db.execute(
                    select(HelpArticle).where(HelpArticle.institution_id.is_(None), HelpArticle.slug == item.slug)
                )
            ).scalar_one_or_none()
            if a is None:
                self.db.add(
                    HelpArticle(
                        institution_id=None,
                        slug=item.slug,
                        title=item.title,
                        body=item.body,
                        module=item.module,
                        audience=item.audience.model_dump(),
                        is_published=item.is_published,
                    )
                )
                created += 1
            else:
                a.title, a.body, a.module, a.audience, a.is_published = (
                    item.title,
                    item.body,
                    item.module,
                    item.audience.model_dump(),
                    item.is_published,
                )
                updated += 1
        await self.db.flush()
        await self.audit("help_import", "help_article", None, {"created": created, "updated": updated})
        return {"created": created, "updated": updated}

    # ---- feedback triage (rule 6) -------------------------------------------------------------------------------
    async def feedback_list(
        self,
        status: str | None = None,
        category: str | None = None,
        institution_id: uuid.UUID | None = None,
        rating: int | None = None,
    ) -> list[FeedbackAdminOut]:
        self.require_platform("platform", "support")
        q = select(FeedbackEntry).order_by(FeedbackEntry.created_at.desc()).limit(1000)
        if status:
            q = q.where(FeedbackEntry.status == status)
        if category:
            q = q.where(FeedbackEntry.category == category)
        if institution_id:
            q = q.where(FeedbackEntry.institution_id == institution_id)
        if rating:
            q = q.where(FeedbackEntry.rating == rating)
        rows = list((await self.db.execute(q)).scalars())
        users = await self.user_refs([r.user_id for r in rows])
        insts = await self.institution_refs([r.institution_id for r in rows])
        notes = await self.plist("feedback:")
        if self.is_support:
            for i in {r.institution_id for r in rows if r.institution_id}:
                await self.audit_read(i, "feedback")
        return [self._feedback_out(r, users, insts, notes.get(str(r.id)) or {}) for r in rows]

    def _feedback_out(
        self, r: FeedbackEntry, users: dict[uuid.UUID, Any], insts: dict[uuid.UUID, Any], note: dict[str, Any]
    ) -> FeedbackAdminOut:
        return FeedbackAdminOut(
            id=r.id,
            institution=insts.get(r.institution_id) if r.institution_id else None,
            user=users.get(r.user_id) if r.user_id else None,
            page=r.page,
            category=r.category,
            rating=r.rating,
            message=r.message,
            screenshot_url=r.screenshot_url,
            client=r.client,
            status=r.status,
            note=note.get("note"),
            responded=bool(note.get("responded_at")),
            ticket_number=note.get("ticket_number"),
            created_at=r.created_at,
        )

    async def _feedback(self, feedback_id: uuid.UUID) -> FeedbackEntry:
        r = (
            await self.db.execute(select(FeedbackEntry).where(FeedbackEntry.id == feedback_id).with_for_update())
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Feedback")
        return r

    async def triage(self, feedback_id: uuid.UUID, body: FeedbackTriage) -> FeedbackAdminOut:
        self.require_platform("platform", "support")
        r = await self._feedback(feedback_id)
        old = r.status
        r.status = body.status
        note = dict(await self.pget(f"feedback:{r.id}", {}) or {})
        if body.note:
            note["note"] = body.note
        note.setdefault("history", []).append(
            {"at": now_utc().isoformat(), "by": str(self.actor_id), "status": body.status}
        )
        if body.respond_text and r.user_id:
            note["responded_at"] = now_utc().isoformat()
            note["response"] = body.respond_text
            await self.notify(
                "feedback.responded",
                r.institution_id,
                {"user_ids": [str(r.user_id)]},
                {"status": body.status, "response": body.respond_text, "page": r.page or ""},
                ["in_app", "email"],
            )
            await self.emit(
                "feedback.responded",
                {"feedback_id": str(r.id)},
                institution_id=r.institution_id,
                aggregate_type="feedback_entry",
                aggregate_id=r.id,
            )
        await self.pput(f"feedback:{r.id}", note)
        await self.db.flush()
        await self.audit(
            "feedback_triage",
            "feedback_entry",
            r.id,
            {"from": old, "to": body.status, "responded": bool(body.respond_text)},
            institution_id=r.institution_id,
        )
        await self.emit(
            "feedback.triaged",
            {"feedback_id": str(r.id), "status": body.status},
            institution_id=r.institution_id,
            aggregate_type="feedback_entry",
            aggregate_id=r.id,
        )
        return self._feedback_out(
            r, await self.user_refs([r.user_id]), await self.institution_refs([r.institution_id]), note
        )

    async def feedback_to_ticket(self, feedback_id: uuid.UUID) -> TicketOut:
        self.require_platform("platform", "support")
        r = await self._feedback(feedback_id)
        note = dict(await self.pget(f"feedback:{r.id}", {}) or {})
        if note.get("ticket_number"):
            raise conflict("Already converted", ticket_number=note["ticket_number"])
        ticket = await self.create(
            TicketCreate(
                subject=f"Feedback: {(r.message or r.page or 'in-app feedback')[:180]}",
                description=f"{r.message or ''}\n\nPage: {r.page or '—'} · rating {r.rating or '—'} · client {r.client or '—'}",
                priority="low" if (r.rating or 3) >= 3 else "normal",
                category="other",
                institution_id=r.institution_id,
            )
        )
        t = await self._ticket(ticket.id, lock=True)
        doc = self._doc(t)
        doc["meta"]["related_feedback"] = [str(r.id)]
        t.messages = doc
        note["ticket_number"] = ticket.ticket_number
        await self.pput(f"feedback:{r.id}", note)
        if r.status == "new":
            r.status = "triaged"
        await self.db.flush()
        await self.audit(
            "feedback_to_ticket",
            "feedback_entry",
            r.id,
            {"ticket_number": ticket.ticket_number},
            institution_id=r.institution_id,
        )
        return await self.out(t)
