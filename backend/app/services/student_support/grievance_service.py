"""Grievances — Prompts/27 §27.6 ``grievance_service`` ({grievances.core}, {grievances.anonymous},
{grievances.committees}).

1. Create — authenticated (own / on behalf of a ward) or anonymous (public form with captcha, or the ``is_anonymous``
   toggle): anonymous rows keep ``raised_by_user_id`` NULL and only a hash of the tracking secret (shown once);
   ``ticket_number`` from ``number_sequences('grievance')``; category → committee by ``grievances.committee_routing``
   (``{grievances.committees}``), SLA from ``grievances.sla_hours``.
2. Triage (``grievances:triage`` or the routed committee's secretary / chair): assignee, priority, committee change
   (audited), status ``acknowledged`` / ``under_review``; updates with internal notes hidden from the complainant;
   resolve → ``resolved``; close / rate (closes) / reopen once (second → 409); auto-close 7 days after resolution;
   escalation through workflow ``grievance.escalation`` on SLA breach (Beat) or manually.
3. Confidential categories (harassment / ragging / discrimination) are visible only to the routed committee, the
   assignee, grievance officers (``grievances:triage``) and escalation approvers (``grievances:escalate``) — never
   through department / college scope; every read of one is audited. Statutory registers are anonymised.
4. Complainant view: timeline without internal notes, SLA, rating; anonymous tracking by ticket + secret.
"""

import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, false, func, not_, or_, select, true

from app.core.errors import APIError
from app.core.workflow import engine as workflow_engine
from app.enums.student_support import (
    COMMITTEE_TYPE_OF,
    CONFIDENTIAL_CATEGORIES,
    DEFAULT_COMMITTEE_ROUTING,
    DEFAULT_SLA_HOURS,
)
from app.models.grievances import Grievance, GrievanceUpdate
from app.models.platform import WorkflowInstance
from app.models.students import StudentProgramEnrollment
from app.schemas.grievances import (
    GrvAnonymousCreate,
    GrvCreate,
    GrvCreated,
    GrvEscalate,
    GrvOut,
    GrvRate,
    GrvRegister,
    GrvRegisterRow,
    GrvReopen,
    GrvResolve,
    GrvTimelineItem,
    GrvTrack,
    GrvTriage,
    GrvUpdateIn,
)
from app.services.student_support.common import (
    SupportBase,
    all_access,
    dept_subquery,
    forbidden,
    is_auditor,
    module_reader,
    not_found,
    now_utc,
    rule,
    scope_ids,
    sha,
)

OPEN = ("open", "acknowledged", "under_review", "reopened", "escalated")


class GrievanceService(SupportBase):
    audit_module = "grievances"
    module = "grievances"

    # ---- permission helpers ---------------------------------------------------------------------------------------------
    def officer(self) -> bool:
        return self.can("grievances", "triage")

    def confidential_reader(self) -> bool:
        return self.can("grievances", "triage") or self.can("grievances", "escalate")

    async def _visible(self, scope: str | None = None) -> Any:
        """Row predicate: self / committee / assignee / department / college / all with the confidentiality rule."""
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return true()
        me = self.actor_id
        committees = await self.my_committee_ids()
        own_parts: list[Any] = []
        if scope in (None, "self", "mine"):
            own_parts.append(Grievance.raised_by_user_id == me)
            wards = await self.ward_enrollment_ids()
            if wards:
                own_parts.append(
                    and_(Grievance.student_program_enrollment_id.in_(wards), Grievance.is_anonymous.is_(False))
                )
        if scope in (None, "own", "committee"):
            if committees:
                own_parts.append(Grievance.committee_id.in_(committees))
            own_parts.append(Grievance.assigned_to == me)
        conf = Grievance.category.in_(tuple(CONFIDENTIAL_CATEGORIES))
        wide: list[Any] = []
        if scope in (None, "all") and all_access(p, self.module):
            wide.append(true() if self.confidential_reader() else not_(conf))
        units = scope_ids(p, "department") or scope_ids(p, "faculty")
        if scope in (None, "department") and units and module_reader(p, self.module):
            wide.append(
                and_(
                    not_(conf),
                    Grievance.student_program_enrollment_id.in_(
                        select(StudentProgramEnrollment.id).where(
                            StudentProgramEnrollment.department_id.in_(dept_subquery(p))
                        )
                    ),
                )
            )
        if scope in (None, "college") and scope_ids(p, "college") and module_reader(p, self.module):
            wide.append(and_(not_(conf), Grievance.college_id.in_(scope_ids(p, "college"))))
        parts = own_parts + wide
        return or_(*parts) if parts else false()

    async def _get(self, gid: uuid.UUID, *, lock: bool = False) -> Grievance:
        stmt = select(Grievance).where(
            Grievance.id == gid, Grievance.institution_id == self.inst, await self._visible()
        )
        if lock:
            stmt = stmt.with_for_update()
        g = (await self.db.execute(stmt)).scalar_one_or_none()
        if g is None:
            raise not_found("Grievance")
        return g

    async def _is_complainant(self, g: Grievance) -> bool:
        if self.actor_id is None:
            return False
        if g.raised_by_user_id == self.actor_id:
            return True
        if g.is_anonymous or g.student_program_enrollment_id is None:
            return False
        return g.student_program_enrollment_id in await self.ward_enrollment_ids()

    async def _is_handler(self, g: Grievance) -> bool:
        if self.principal is None or getattr(self.principal, "is_super_admin", False):
            return True
        if self.officer() or self.can("grievances", "resolve") and all_access(self.principal, self.module):
            return True
        if g.assigned_to is not None and g.assigned_to == self.actor_id:
            return True
        return g.committee_id is not None and g.committee_id in await self.my_committee_ids()

    # ---- routing --------------------------------------------------------------------------------------------------------
    async def _route(self, category: str) -> str | None:
        if not await self.feature("grievances.committees"):
            return None
        routing = await self.setting("grievances", "committee_routing")
        routing = routing if isinstance(routing, dict) else DEFAULT_COMMITTEE_ROUTING
        code = str(routing.get(category) or routing.get("default") or "grievance_cell")
        return code.split("|")[0]

    async def _sla(self, category: str) -> datetime:
        hours = await self.setting("grievances", "sla_hours")
        hours = hours if isinstance(hours, dict) else DEFAULT_SLA_HOURS
        return now_utc() + timedelta(hours=int(hours.get(category) or hours.get("other") or 120))

    async def _new(
        self,
        *,
        category: str,
        description: str,
        attachments: list[dict[str, Any]],
        anonymous: bool,
        enrollment_id: uuid.UUID | None,
        priority: str,
        contact: str | None,
    ) -> GrvCreated:
        committee = await self._route(category)
        committee_row = (
            await self.committee_by_type(COMMITTEE_TYPE_OF.get(committee, "grievance")) if committee else None
        )
        college_id = None
        if enrollment_id:
            college_id = (await self.enrollment(enrollment_id)).college_id
        secret = secrets.token_urlsafe(18) if anonymous else None
        payload: dict[str, Any] = {"files": attachments}
        if secret:
            payload["tracking"] = {"secret_hash": sha(secret)}
        if contact:
            payload["contact"] = contact
        if category in ("harassment", "ragging") and priority in ("low", "normal"):
            priority = "high"
        g = Grievance(
            institution_id=self.inst,
            college_id=college_id,
            ticket_number=(await self.sequence("grievance", "GRV")).upper(),
            raised_by_user_id=None if anonymous else self.actor_id,
            student_program_enrollment_id=None if anonymous else enrollment_id,
            category=category,
            is_anonymous=anonymous,
            description=description,
            attachments=payload,
            priority=priority,
            committee=committee,
            committee_id=committee_row.id if committee_row else None,
            sla_due_at=await self._sla(category),
            status="open",
        )
        self.db.add(g)
        await self.db.flush()
        await self._emit(
            "grievance.created",
            {"grievance_id": str(g.id), "category": category, "committee": committee, "anonymous": anonymous},
            "grievance",
            g.id,
        )
        handlers = await self.committee_user_ids(g.committee_id) + await self.role_users("grievance_officer")
        await self._notify(
            "grievance.updated",
            handlers,
            {"ticket_no": g.ticket_number, "status": "open (new)"},
        )
        await self._audit(
            "create", "grievance", g.id, None, {"category": category, "committee": committee, "anonymous": anonymous}
        )
        return GrvCreated(
            id=g.id,
            ticket_number=g.ticket_number,
            status=g.status,
            committee=g.committee,
            sla_due_at=g.sla_due_at,
            tracking_secret=secret,
        )

    async def create(self, body: GrvCreate) -> GrvCreated:
        self.require_writer()
        if body.is_anonymous:
            await self.require_feature("grievances.anonymous")
        enrol_id = body.on_behalf_enrollment_id
        if enrol_id is not None:
            mine = await self.my_enrollment_ids()
            if enrol_id not in mine and enrol_id not in await self.ward_enrollment_ids():
                raise forbidden("You raise grievances for yourself or your ward")
        else:
            e = await self.my_enrollment()
            enrol_id = e.id if e else None
        return await self._new(
            category=body.category,
            description=body.description,
            attachments=[a.model_dump() for a in body.attachments],
            anonymous=body.is_anonymous,
            enrollment_id=enrol_id,
            priority=body.priority,
            contact=body.contact_email,
        )

    async def create_anonymous(self, body: GrvAnonymousCreate) -> GrvCreated:
        return await self._new(
            category=body.category,
            description=body.description,
            attachments=[a.model_dump() for a in body.attachments],
            anonymous=True,
            enrollment_id=None,
            priority="normal",
            contact=body.contact_email,
        )

    # ---- output ---------------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[Grievance], *, detail: bool = False) -> list[GrvOut]:
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        users = await self.user_display([r.raised_by_user_id for r in rows] + [r.assigned_to for r in rows])
        auditor = is_auditor(self.principal)
        now = now_utc()
        out = []
        for r in rows:
            card = cards.get(r.student_program_enrollment_id, {}) if r.student_program_enrollment_id else {}
            hide = r.is_anonymous or auditor
            files = (r.attachments or {}).get("files") if isinstance(r.attachments, dict) else (r.attachments or [])
            o = GrvOut(
                id=r.id,
                ticket_number=r.ticket_number,
                category=r.category,
                description=r.description if detail else (r.description or "")[:200],
                is_anonymous=r.is_anonymous,
                raised_by_user_id=None if hide else r.raised_by_user_id,
                raised_by_name=None if hide else users.get(r.raised_by_user_id) if r.raised_by_user_id else None,
                student_program_enrollment_id=None if hide else r.student_program_enrollment_id,
                student_name=None if hide else card.get("name"),
                department_id=card.get("department_id"),
                priority=r.priority,
                committee=r.committee,
                committee_id=r.committee_id,
                assigned_to=r.assigned_to,
                assignee_name=users.get(r.assigned_to) if r.assigned_to else None,
                sla_due_at=r.sla_due_at,
                sla_breached=bool(r.sla_due_at and r.status in OPEN and r.sla_due_at < now),
                status=r.status,
                resolution=r.resolution,
                resolved_at=r.resolved_at,
                satisfaction_rating=r.satisfaction_rating,
                confidential=r.category in CONFIDENTIAL_CATEGORIES,
                attachments=list(files or []),
                workflow_instance_id=r.workflow_instance_id,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            out.append(o)
        return out

    async def _timeline(self, g: Grievance, *, internal: bool) -> list[GrvTimelineItem]:
        stmt = select(GrievanceUpdate).where(GrievanceUpdate.grievance_id == g.id)
        if not internal:
            stmt = stmt.where(GrievanceUpdate.is_internal.is_(False))
        rows = (await self.db.execute(stmt.order_by(GrievanceUpdate.at))).scalars().all()
        names = await self.user_display([r.by_user_id for r in rows]) if internal else {}
        return [
            GrvTimelineItem(
                at=r.at,
                by=(names.get(r.by_user_id) if r.by_user_id else "system") if internal else None,
                note=r.note,
                is_internal=r.is_internal,
                attachments=list(r.attachments or []),
            )
            for r in rows
        ]

    async def detail(self, g: Grievance) -> GrvOut:
        o = (await self.outs([g], detail=True))[0]
        handler = await self._is_handler(g)
        complainant = await self._is_complainant(g)
        o.timeline = await self._timeline(g, internal=handler and not complainant)
        reopens = int(((g.attachments or {}) if isinstance(g.attachments, dict) else {}).get("reopens") or 0)
        o.can_reopen = complainant and g.status in ("resolved", "closed") and reopens < 1
        o.can_rate = complainant and g.status in ("resolved", "closed") and g.satisfaction_rating is None
        if g.category in CONFIDENTIAL_CATEGORIES:
            await self._audit("read", "grievance", g.id, None, {"confidential": True})
        return o

    # ---- reads ----------------------------------------------------------------------------------------------------------
    async def list_all(
        self,
        status: str | None,
        category: str | None,
        committee: str | None,
        department_id: uuid.UUID | None,
        scope: str | None = None,
        limit: int = 500,
    ) -> list[GrvOut]:
        stmt = select(Grievance).where(Grievance.institution_id == self.inst, await self._visible(scope))
        if status:
            stmt = stmt.where(Grievance.status == status)
        if category:
            stmt = stmt.where(Grievance.category == category)
        if committee:
            stmt = stmt.where(Grievance.committee == committee)
        if department_id:
            stmt = stmt.where(
                Grievance.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.department_id == department_id)
                )
            )
        rows = (await self.db.execute(stmt.order_by(Grievance.created_at.desc()).limit(limit))).scalars().all()
        return await self.outs(list(rows))

    async def get(self, gid: uuid.UUID) -> GrvOut:
        return await self.detail(await self._get(gid))

    async def mine(self) -> list[GrvOut]:
        if self.actor_id is None:
            return []
        rows = (
            (
                await self.db.execute(
                    select(Grievance)
                    .where(Grievance.institution_id == self.inst, Grievance.raised_by_user_id == self.actor_id)
                    .order_by(Grievance.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows))

    async def wards(self) -> list[GrvOut]:
        ids = await self.ward_enrollment_ids()
        if not ids:
            return []
        rows = (
            (
                await self.db.execute(
                    select(Grievance)
                    .where(Grievance.student_program_enrollment_id.in_(ids), Grievance.is_anonymous.is_(False))
                    .order_by(Grievance.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows))

    async def track(self, ticket: str, secret: str) -> GrvTrack:
        g = (
            await self.db.execute(
                select(Grievance).where(
                    Grievance.institution_id == self.inst, Grievance.ticket_number == ticket.upper()
                )
            )
        ).scalar_one_or_none()
        stored = (
            ((g.attachments or {}).get("tracking") or {}).get("secret_hash")
            if g and isinstance(g.attachments, dict)
            else None
        )
        if g is None or not stored or not secrets.compare_digest(stored, sha(secret)):
            raise not_found("Ticket")
        return GrvTrack(
            ticket_number=g.ticket_number,
            category=g.category,
            status=g.status,
            committee=g.committee,
            sla_due_at=g.sla_due_at,
            created_at=g.created_at,
            resolution=g.resolution,
            timeline=await self._timeline(g, internal=False),
        )

    # ---- actions --------------------------------------------------------------------------------------------------------
    async def _log(
        self, g: Grievance, note: str, *, internal: bool = False, attachments: list[Any] | None = None
    ) -> None:
        self.db.add(
            GrievanceUpdate(
                institution_id=self.inst,
                grievance_id=g.id,
                by_user_id=self.actor_id,
                note=note,
                is_internal=internal,
                attachments=attachments or None,
            )
        )
        await self.db.flush()

    async def _tell_complainant(self, g: Grievance, event: str) -> None:
        users: list[uuid.UUID | None] = [g.raised_by_user_id]
        await self._emit(event, {"grievance_id": str(g.id), "status": g.status}, "grievance", g.id)
        if users[0] is None:
            return
        await self._notify(event, users, {"ticket_no": g.ticket_number, "status": g.status.replace("_", " ")})

    async def add_update(self, gid: uuid.UUID, body: GrvUpdateIn) -> GrvOut:
        self.require_writer()
        g = await self._get(gid, lock=True)
        handler, complainant = await self._is_handler(g), await self._is_complainant(g)
        if not (handler or complainant):
            raise forbidden("Only the complainant or a handler posts updates")
        internal = body.is_internal and handler and not complainant
        if g.status == "closed" and not handler:
            raise rule("The grievance is closed — reopen it first", "CLOSED")
        await self._log(g, body.note, internal=internal, attachments=[a.model_dump() for a in body.attachments])
        if not internal:
            if complainant:
                await self._notify(
                    "grievance.updated",
                    [g.assigned_to, *await self.committee_user_ids(g.committee_id)],
                    {"ticket_no": g.ticket_number, "status": "updated by the complainant"},
                )
            else:
                await self._tell_complainant(g, "grievance.updated")
        return await self.detail(g)

    async def triage(self, gid: uuid.UUID, body: GrvTriage) -> GrvOut:
        self.require_writer()
        g = await self._get(gid, lock=True)
        if not (self.officer() or (g.committee_id and g.committee_id in await self.my_committee_ids())):
            raise forbidden("grievances:triage or the routed committee required")
        old = {
            "committee": g.committee,
            "assigned_to": str(g.assigned_to) if g.assigned_to else None,
            "priority": g.priority,
        }
        notes = []
        if body.committee and body.committee != g.committee:
            if not (self.can("grievances", "committee") or self.officer()):
                raise forbidden("grievances:committee required to re-route")
            c = await self.committee_by_type(COMMITTEE_TYPE_OF.get(body.committee, "grievance"))
            g.committee, g.committee_id = body.committee, c.id if c else None
            notes.append(f"Routed to {body.committee}")
        if body.assigned_to:
            g.assigned_to = body.assigned_to
            notes.append("Assigned")
        if body.priority:
            g.priority = body.priority
        if body.sla_due_at:
            g.sla_due_at = body.sla_due_at
        acknowledged = False
        if body.status:
            acknowledged = g.status in ("open", "reopened") and body.status == "acknowledged"
            g.status = body.status
        elif g.status in ("open", "reopened"):
            g.status, acknowledged = "acknowledged", True
        await self.db.flush()
        await self._audit("triage", "grievance", g.id, old, {"committee": g.committee, "priority": g.priority})
        await self._log(g, "; ".join(notes + ([body.note] if body.note else [])) or "Triaged", internal=True)
        if acknowledged:
            await self._log(g, "Your grievance was acknowledged")
            await self._tell_complainant(g, "grievance.acknowledged")
        if body.assigned_to:
            await self._notify(
                "grievance.updated", [body.assigned_to], {"ticket_no": g.ticket_number, "status": "assigned to you"}
            )
        return await self.detail(g)

    async def resolve(self, gid: uuid.UUID, body: GrvResolve) -> GrvOut:
        self.require_writer()
        g = await self._get(gid, lock=True)
        if not await self._is_handler(g):
            raise forbidden("grievances:resolve required")
        if g.status not in OPEN:
            raise rule(f"A {g.status} grievance cannot be resolved", "BAD_STATUS")
        g.status, g.resolution, g.resolved_at = "resolved", body.resolution, now_utc()
        await self.close_workflow(g.workflow_instance_id, "approved")
        await self.db.flush()
        await self._log(g, f"Resolved: {body.resolution}")
        await self._tell_complainant(g, "grievance.resolved")
        return await self.detail(g)

    async def close(self, gid: uuid.UUID) -> GrvOut:
        self.require_writer()
        g = await self._get(gid, lock=True)
        if not (await self._is_handler(g) or await self._is_complainant(g)):
            raise forbidden("Only a handler or the complainant closes the grievance")
        if g.status not in ("resolved",) and not await self._is_handler(g):
            raise rule("Only a resolved grievance is closed", "BAD_STATUS")
        g.status = "closed"
        await self.db.flush()
        await self._log(g, "Closed")
        await self._tell_complainant(g, "grievance.closed")
        return await self.detail(g)

    async def rate(self, gid: uuid.UUID, body: GrvRate) -> GrvOut:
        g = await self._get(gid, lock=True)
        if not await self._is_complainant(g):
            raise not_found("Grievance")
        if g.status not in ("resolved", "closed"):
            raise rule("Rate after the grievance is resolved", "BAD_STATUS")
        g.satisfaction_rating, g.status = body.rating, "closed"
        await self.db.flush()
        await self._log(g, f"Rated {body.rating}/5" + (f": {body.comment}" if body.comment else ""))
        await self._emit("grievance.rated", {"grievance_id": str(g.id), "rating": body.rating}, "grievance", g.id)
        return await self.detail(g)

    async def reopen(self, gid: uuid.UUID, body: GrvReopen) -> GrvOut:
        g = await self._get(gid, lock=True)
        if not await self._is_complainant(g):
            raise not_found("Grievance")
        if g.status not in ("resolved", "closed"):
            raise rule("Only a resolved or closed grievance is reopened", "BAD_STATUS")
        meta = dict(g.attachments) if isinstance(g.attachments, dict) else {"files": list(g.attachments or [])}
        if int(meta.get("reopens") or 0) >= 1:
            raise rule("A grievance is reopened only once", "REOPEN_LIMIT")
        meta["reopens"] = int(meta.get("reopens") or 0) + 1
        g.attachments = meta
        g.status, g.satisfaction_rating = "reopened", None
        g.sla_due_at = await self._sla(g.category)
        await self.db.flush()
        await self._log(g, f"Reopened: {body.reason}")
        await self._emit("grievance.reopened", {"grievance_id": str(g.id)}, "grievance", g.id)
        await self._notify(
            "grievance.updated",
            [g.assigned_to, *await self.committee_user_ids(g.committee_id)],
            {"ticket_no": g.ticket_number, "status": "reopened"},
        )
        return await self.detail(g)

    async def escalate(self, gid: uuid.UUID, body: GrvEscalate, *, system: bool = False) -> GrvOut:
        g = await self._get(gid, lock=True) if not system else await self._get_system(gid)
        if not system and not (await self._is_handler(g) or self.can("grievances", "escalate")):
            raise forbidden("grievances:escalate required")
        if g.status not in OPEN or g.status == "escalated":
            raise rule(f"A {g.status} grievance cannot be escalated", "BAD_STATUS")
        try:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="grievance.escalation",
                entity_type="grievance",
                entity_id=g.id,
                started_by=self.actor_id,
                context={"college_id": str(g.college_id) if g.college_id else None, "category": g.category},
                title=f"Grievance {g.ticket_number} escalated"[:200],
            )
            g.workflow_instance_id = wf.id
        except APIError:
            pass
        g.status = "escalated"
        await self.db.flush()
        await self._log(g, f"Escalated: {body.reason}", internal=True)
        await self._tell_complainant(g, "grievance.escalated")
        return await self.detail(g) if not system else (await self.outs([g]))[0]

    async def _get_system(self, gid: uuid.UUID) -> Grievance:
        g = (await self.db.execute(select(Grievance).where(Grievance.id == gid).with_for_update())).scalar_one_or_none()
        if g is None:
            raise not_found("Grievance")
        return g

    # ---- Beat -----------------------------------------------------------------------------------------------------------
    async def sla_scan(self) -> int:
        rows = (
            await self.db.execute(
                select(Grievance.id).where(
                    Grievance.institution_id == self.inst,
                    Grievance.status.in_(("open", "acknowledged", "under_review", "reopened")),
                    Grievance.sla_due_at < now_utc(),
                    Grievance.workflow_instance_id.is_(None),
                )
            )
        ).all()
        n = 0
        for (gid,) in rows:
            try:
                await self.escalate(gid, GrvEscalate(reason="SLA breached"), system=True)
                n += 1
            except APIError:
                continue
        return n

    async def auto_close(self) -> int:
        rows = (
            (
                await self.db.execute(
                    select(Grievance).where(
                        Grievance.institution_id == self.inst,
                        Grievance.status == "resolved",
                        Grievance.resolved_at
                        < now_utc() - timedelta(days=await self.int_setting("grievances", "auto_close_days", 7)),
                    )
                )
            )
            .scalars()
            .all()
        )
        for g in rows:
            g.status = "closed"
            await self._log(g, "Auto-closed after the resolution window")
            await self._emit("grievance.closed", {"grievance_id": str(g.id), "auto": True}, "grievance", g.id)
        await self.db.flush()
        return len(rows)

    # ---- registers / stats ----------------------------------------------------------------------------------------------
    async def register(self, kind: str, period: str | None) -> GrvRegister:
        if not (self.reader() or self.can("reports", "statutory")):
            raise forbidden("grievances:view_all or reports:statutory required")
        stmt = select(Grievance).where(Grievance.institution_id == self.inst)
        if kind == "icc":
            stmt = stmt.where(Grievance.committee == "icc")
        elif kind == "anti_ragging":
            stmt = stmt.where(or_(Grievance.committee == "anti_ragging", Grievance.category == "ragging"))
        elif kind != "ugc":
            raise not_found("Register")
        if period and len(period) >= 4 and period[:4].isdigit():
            y = int(period[:4])
            stmt = stmt.where(func.extract("year", Grievance.created_at) == y)
        rows = (await self.db.execute(stmt.order_by(Grievance.created_at))).scalars().all()
        out = []
        totals = {"received": 0, "resolved": 0, "pending": 0, "within_sla": 0}
        for g in rows:
            done = g.resolved_at
            within = bool(done and g.sla_due_at and done <= g.sla_due_at) if done else None
            totals["received"] += 1
            totals["resolved" if g.status in ("resolved", "closed") else "pending"] += 1
            totals["within_sla"] += 1 if within else 0
            out.append(
                GrvRegisterRow(
                    ticket_number=g.ticket_number,
                    category=g.category,
                    committee=g.committee,
                    complainant="Anonymous" if g.is_anonymous or kind == "icc" else "Student/Staff (withheld)",
                    received_on=g.created_at,
                    status=g.status,
                    resolved_on=done,
                    days_taken=round((done - g.created_at).total_seconds() / 86400, 1)
                    if done and g.created_at
                    else None,
                    within_sla=within,
                    action_taken=(g.resolution or "")[:300] or None,
                )
            )
        await self._emit("grievances.register_exported", {"register": kind, "rows": len(out)}, "grievance", None)
        return GrvRegister(kind=kind, period=period, rows=out, totals=totals)

    async def stats(self) -> dict[str, Any]:
        by_status = {
            s: int(n)
            for s, n in (
                await self.db.execute(
                    select(Grievance.status, func.count())
                    .where(Grievance.institution_id == self.inst)
                    .group_by(Grievance.status)
                )
            ).all()
        }
        by_category = {
            c: int(n)
            for c, n in (
                await self.db.execute(
                    select(Grievance.category, func.count())
                    .where(Grievance.institution_id == self.inst)
                    .group_by(Grievance.category)
                )
            ).all()
        }
        resolved = (
            await self.db.execute(
                select(Grievance.resolved_at, Grievance.sla_due_at, Grievance.satisfaction_rating).where(
                    Grievance.institution_id == self.inst, Grievance.resolved_at.is_not(None)
                )
            )
        ).all()
        within = sum(1 for r, due, _ in resolved if due and r <= due)
        ratings = [int(x) for _, _, x in resolved if x]
        return {
            "total": sum(by_status.values()),
            "by_status": by_status,
            "by_category": by_category,
            "sla_pct": round(100.0 * within / len(resolved), 1) if resolved else None,
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "anonymous": int(
                (
                    await self.db.execute(
                        select(func.count())
                        .select_from(Grievance)
                        .where(Grievance.institution_id == self.inst, Grievance.is_anonymous.is_(True))
                    )
                ).scalar_one()
                or 0
            ),
        }


@workflow_engine.summariser("grievance")
async def _summary(db: Any, gid: uuid.UUID) -> tuple[str | None, str | None]:
    g = (await db.execute(select(Grievance).where(Grievance.id == gid))).scalar_one_or_none()
    if g is None:
        return None, None
    return f"Grievance {g.ticket_number} · {g.category}", f"/admin/grievances/{g.id}"


@workflow_engine.on("grievance.escalation", "approved")
async def _escalation_done(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    g = (
        await db.execute(select(Grievance).where(Grievance.id == instance.entity_id).with_for_update())
    ).scalar_one_or_none()
    if g is not None and g.status == "escalated":
        g.status = "under_review"
        db.add(
            GrievanceUpdate(
                institution_id=g.institution_id,
                grievance_id=g.id,
                by_user_id=getattr(actor, "id", None),
                note="Escalation reviewed — action directed",
                is_internal=False,
            )
        )
        await db.flush()


@workflow_engine.on("grievance.escalation", "rejected")
async def _escalation_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await _escalation_done(db, instance, actor)
