"""Service desk, AMC and lost & found — Prompts/25 §25.6 ``service_desk_service`` ({facilities.service_desk},
{facilities.amc}, {facilities.lost_found}).

1. **Tickets** — ``ticket_number`` from the ``sr`` sequence; ``sla_due_at = now + sla_hours[category] × priority factor``
   (high halves, urgent quarters; an AMC contract's ``sla[category]`` overrides on vendor assignment); auto-routing
   from ``facilities.routing`` (category → role slug or user id: the queue is notified); status machine
   ``open → assigned → in_progress → resolved → closed`` (auto-close after ``auto_close_days``), reopen by the
   requester within ``reopen_days``, rating on close; SLA breach Beat escalates to the estate officer; cost capture;
   ``hostel_complaints.service_request_id`` mirrors the complaint status, ``asset`` tickets set the asset
   ``under_repair`` and back to ``in_use`` on close. Timeline / cost / AMC link live in ``facilities_meta``.
2. **AMC** — register per supplier / asset category / assets with SLA and value; expiry reminders (60 / 30 days);
   performance per contract (tickets, breaches, MTTR, CSAT).
3. **Lost & found** — report → claim with an identity proof → ``claimed``; disposal after the retention period.

Visibility: self (``requested_by``), assignee, department (HOD — requester's department), college, all; security
officers additionally read ``security`` tickets.
"""

import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.enums.facilities import DEFAULT_ROUTING, OPEN_SERVICE, PRIORITY_FACTOR, SLA_HOURS
from app.models.facilities import AmcContract, LostFoundItem, ServiceRequest
from app.models.inventory import Asset, Supplier
from app.models.timetable import Room
from app.schemas.facilities import (
    FacAmcContractIn,
    FacAmcContractOut,
    FacAmcPerformance,
    FacLostFoundClaim,
    FacLostFoundIn,
    FacLostFoundOut,
    FacServiceAssign,
    FacServiceDashboard,
    FacServiceRate,
    FacServiceRequestCreate,
    FacServiceRequestOut,
    FacServiceUpdate,
)
from app.services.facilities.common import FacilitiesBase, forbidden, not_found, now_utc, rule, scope_ids


class ServiceDeskService(FacilitiesBase):
    audit_module = "facilities"

    # ---- visibility ---------------------------------------------------------------------------------------------------
    def _visible(self) -> Any:
        p = self.principal
        parts = [
            self.unit_predicate(
                "facilities",
                self_cols=(ServiceRequest.requested_by, ServiceRequest.assigned_to),
                college_col=ServiceRequest.college_id,
            )
        ]
        if (scope_ids(p, "department") or scope_ids(p, "faculty")) and self.reader():
            parts.append(ServiceRequest.requested_by.in_(self.requester_dept_subquery()))
        if p is not None and "security_officer" in (getattr(p, "roles", None) or []):
            parts.append(ServiceRequest.category == "security")
        return or_(*parts)

    async def _scoped(self, scope: str | None) -> Any:
        if scope in ("mine", "self"):
            return ServiceRequest.requested_by == self.actor_id
        if scope == "assigned":
            return ServiceRequest.assigned_to == self.actor_id
        if scope == "department":
            return ServiceRequest.requested_by.in_(self.requester_dept_subquery())
        if scope == "college":
            return ServiceRequest.college_id.in_(scope_ids(self.principal, "college") or [uuid.uuid4()])
        return self._visible()

    async def outs(self, rows: Sequence[ServiceRequest]) -> list[FacServiceRequestOut]:
        names = await self.user_names([*(r.requested_by for r in rows), *(r.assigned_to for r in rows)])
        rooms = {
            r.id: r.code
            for r in (
                await self.db.execute(
                    select(Room).where(
                        Room.id.in_([x.location_room_id for x in rows if x.location_room_id] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        vendors = {
            v.id: v.name
            for v in (
                await self.db.execute(
                    select(Supplier).where(
                        Supplier.id.in_([x.vendor_id for x in rows if x.vendor_id] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        metas = await self.metas("sr", [r.id for r in rows])
        now = now_utc()
        out = []
        for r in rows:
            o = FacServiceRequestOut.model_validate(r)
            o.requester_name = names.get(r.requested_by)
            o.assignee_name = names.get(r.assigned_to) if r.assigned_to else None
            o.room_code = rooms.get(r.location_room_id) if r.location_room_id else None
            o.vendor_name = vendors.get(r.vendor_id) if r.vendor_id else None
            m = metas.get(str(r.id), {})
            o.timeline = m.get("timeline") or []
            o.cost_paise = m.get("cost_paise")
            o.amc_contract_id = uuid.UUID(m["amc_contract_id"]) if m.get("amc_contract_id") else None
            end = r.resolved_at or now
            o.sla_breached = bool(r.sla_due_at and end > r.sla_due_at) or bool(m.get("breached"))
            o.is_mine = r.requested_by == self.actor_id
            out.append(o)
        return out

    async def row(self, rid: uuid.UUID, *, for_update: bool = False) -> ServiceRequest:
        stmt = select(ServiceRequest).where(
            ServiceRequest.id == rid, ServiceRequest.institution_id == self.inst, self._visible()
        )
        if for_update:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Service request")
        return r

    async def list_requests(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        scope: str | None = None,
        breached: bool | None = None,
        q: str | None = None,
        limit: int = 300,
    ) -> list[FacServiceRequestOut]:
        stmt = select(ServiceRequest).where(ServiceRequest.institution_id == self.inst, await self._scoped(scope))
        if status:
            stmt = stmt.where(ServiceRequest.status == status)
        if category:
            stmt = stmt.where(ServiceRequest.category == category)
        if breached:
            stmt = stmt.where(ServiceRequest.status.in_(OPEN_SERVICE), ServiceRequest.sla_due_at < now_utc())
        if q:
            stmt = stmt.where(
                or_(ServiceRequest.ticket_number.ilike(f"%{q}%"), ServiceRequest.description.ilike(f"%{q}%"))
            )
        rows = (await self.db.execute(stmt.order_by(ServiceRequest.created_at.desc()).limit(limit))).scalars().all()
        return await self.outs(rows)

    async def get(self, rid: uuid.UUID) -> FacServiceRequestOut:
        return (await self.outs([await self.row(rid)]))[0]

    # ---- lifecycle ------------------------------------------------------------------------------------------------------
    async def sla_hours(self, category: str, priority: str, override: dict[str, Any] | None = None) -> float:
        table = await self.setting("facilities", "sla_hours")
        hours = dict(SLA_HOURS)
        if isinstance(table, dict):
            hours.update({k: int(v) for k, v in table.items() if isinstance(v, int | float)})
        base = float((override or {}).get(category) or hours.get(category) or hours["other"])
        return base * PRIORITY_FACTOR.get(priority, 1.0)

    async def create(self, body: FacServiceRequestCreate) -> FacServiceRequestOut:
        self.require("facilities:view", "facilities:book", "facilities:manage")
        self.require_writer()
        if self.actor_id is None:
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Sign in first")
        college = body.college_id
        if body.location_room_id:
            room = (
                await self.db.execute(
                    select(Room).where(Room.id == body.location_room_id, Room.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if room is None:
                raise not_found("Room")
            college = college or room.college_id
        if college is None:
            st, sf = await self.my_student(), await self.my_staff()
            college = st.college_id if st else (sf.college_id if sf else None)
        now = now_utc()
        r = ServiceRequest(
            institution_id=self.inst,
            college_id=college,
            ticket_number=await self.sequence("sr", "SR", None),
            category=body.category,
            location_room_id=body.location_room_id,
            location_text=body.location_text,
            description=body.description,
            attachments=body.attachments or None,
            priority=body.priority,
            requested_by=self.actor_id,
            sla_due_at=now + timedelta(hours=await self.sla_hours(body.category, body.priority)),
            status="open",
        )
        self.db.add(r)
        await self.db.flush()
        meta: dict[str, Any] = {"timeline": [{"at": now.isoformat(), "by": str(self.actor_id), "action": "created"}]}
        if body.asset_id:
            meta["asset_id"] = str(body.asset_id)
            a = (
                await self.db.execute(select(Asset).where(Asset.id == body.asset_id, Asset.institution_id == self.inst))
            ).scalar_one_or_none()
            if a is not None:
                a.status = "under_repair"
        if body.hostel_complaint_id:
            from app.models.hostel import HostelComplaint

            hc = (
                await self.db.execute(select(HostelComplaint).where(HostelComplaint.id == body.hostel_complaint_id))
            ).scalar_one_or_none()
            if hc is not None:
                hc.service_request_id = r.id
                meta["hostel_complaint_id"] = str(hc.id)
        await self.put_meta("sr", r.id, meta)
        await self._route(r)
        await self._audit("create", "service_request", r.id, None, {"ticket": r.ticket_number, "category": r.category})
        await self._emit(
            "service_request.created",
            {"service_request_id": str(r.id), "category": r.category},
            "service_request",
            r.id,
        )
        return await self.get(r.id)

    async def _route(self, r: ServiceRequest) -> None:
        routing = await self.setting("facilities", "routing")
        table = {**DEFAULT_ROUTING, **(routing if isinstance(routing, dict) else {})}
        target = table.get(r.category)
        ctx = {
            "ticket": r.ticket_number,
            "category": r.category,
            "due": r.sla_due_at.isoformat() if r.sla_due_at else "",
        }
        if target:
            try:
                uid = uuid.UUID(str(target))
            except ValueError:
                uid = None
            if uid:
                r.assigned_to, r.status = uid, "assigned"
                await self.timeline("sr", r.id, "auto_assigned", to=str(uid))
                await self._notify("service_request.assigned", [uid], ctx)
                return
            await self.timeline("sr", r.id, "routed", queue=str(target))
            await self._notify("service_request.assigned", [], ctx, audience={"roles": [str(target)]})
            return
        await self._notify("service_request.assigned", [], ctx, audience={"roles": ["estate_officer"]})

    async def assign(self, rid: uuid.UUID, body: FacServiceAssign) -> FacServiceRequestOut:
        self.require("facilities:service_assign", "facilities:manage")
        self.require_writer()
        r = await self.row(rid, for_update=True)
        if r.status in ("resolved", "closed"):
            raise rule("A resolved ticket cannot be reassigned", "TICKET_CLOSED")
        override = None
        if body.amc_contract_id:
            amc = (
                await self.db.execute(
                    select(AmcContract).where(
                        AmcContract.id == body.amc_contract_id, AmcContract.institution_id == self.inst
                    )
                )
            ).scalar_one_or_none()
            if amc is None:
                raise not_found("AMC contract")
            if amc.status != "active" or amc.to_on < await self.today():
                raise rule("The AMC contract is not active", "AMC_INACTIVE")
            override = amc.sla or None
            r.vendor_id = amc.supplier_id
        if body.vendor_id:
            r.vendor_id = body.vendor_id
        r.assigned_to = body.assigned_to or r.assigned_to
        r.status = "assigned"
        if override:
            r.sla_due_at = r.created_at + timedelta(hours=await self.sla_hours(r.category, r.priority, override))
        m = await self.timeline(
            "sr",
            r.id,
            "assigned",
            to=str(r.assigned_to) if r.assigned_to else None,
            vendor=str(r.vendor_id) if r.vendor_id else None,
            remarks=body.remarks,
        )
        if body.amc_contract_id:
            m["amc_contract_id"] = str(body.amc_contract_id)
            await self.put_meta("sr", r.id, m)
        await self.db.flush()
        await self._audit(
            "assign", "service_request", r.id, None, {"assigned_to": str(r.assigned_to), "vendor_id": str(r.vendor_id)}
        )
        await self._emit("service_request.assigned", {"service_request_id": str(r.id)}, "service_request", r.id)
        if r.assigned_to:
            await self._notify(
                "service_request.assigned",
                [r.assigned_to],
                {
                    "ticket": r.ticket_number,
                    "category": r.category,
                    "due": r.sla_due_at.isoformat() if r.sla_due_at else "",
                },
            )
        return await self.get(r.id)

    async def update(self, rid: uuid.UUID, body: FacServiceUpdate) -> FacServiceRequestOut:
        self.require_writer()
        r = await self.row(rid, for_update=True)
        if r.assigned_to != self.actor_id and not (
            self.can("facilities", "service_assign") or self.can("facilities", "manage")
        ):
            raise forbidden("Only the assignee updates the ticket")
        if r.status in ("closed",):
            raise rule("The ticket is closed", "TICKET_CLOSED")
        m = await self.meta("sr", r.id)
        if body.cost_paise is not None:
            m["cost_paise"] = body.cost_paise
            await self.put_meta("sr", r.id, m)
        if body.status == "resolved":
            return await self.resolve(rid, body)
        r.status = "in_progress"
        await self.timeline("sr", r.id, "in_progress", remarks=body.remarks)
        await self.db.flush()
        await self._emit(
            "service_request.updated", {"service_request_id": str(r.id), "status": r.status}, "service_request", r.id
        )
        return await self.get(r.id)

    async def resolve(self, rid: uuid.UUID, body: FacServiceUpdate) -> FacServiceRequestOut:
        self.require_writer()
        r = await self.row(rid, for_update=True)
        if r.assigned_to != self.actor_id and not (
            self.can("facilities", "service_assign") or self.can("facilities", "manage")
        ):
            raise forbidden("Only the assignee resolves the ticket")
        if r.status not in OPEN_SERVICE:
            raise rule("Only an open ticket is resolved", "NOT_OPEN", current=r.status)
        r.status, r.resolution, r.resolved_at = "resolved", body.resolution or r.resolution, now_utc()
        m = await self.timeline("sr", r.id, "resolved", resolution=body.resolution)
        if body.cost_paise is not None:
            m["cost_paise"] = body.cost_paise
            await self.put_meta("sr", r.id, m)
        await self._mirror_hostel(m, "resolved")
        await self.db.flush()
        await self._audit("resolve", "service_request", r.id, None, {"resolution": r.resolution})
        await self._emit(
            "service_request.resolved",
            {"service_request_id": str(r.id), "cost_paise": m.get("cost_paise")},
            "service_request",
            r.id,
        )
        await self._notify(
            "service_request.resolved", [r.requested_by], {"ticket": r.ticket_number, "resolution": r.resolution or ""}
        )
        return await self.get(r.id)

    async def close(
        self, rid: uuid.UUID, *, rating: FacServiceRate | None = None, auto: bool = False
    ) -> FacServiceRequestOut:
        r = (
            await self.row(rid, for_update=True)
            if not auto
            else (
                await self.db.execute(select(ServiceRequest).where(ServiceRequest.id == rid).with_for_update())
            ).scalar_one()
        )
        if not auto:
            self.require_writer()
            if r.requested_by != self.actor_id and not self.can("facilities", "manage"):
                raise forbidden("The requester closes the ticket")
        if r.status != "resolved":
            raise rule("Only a resolved ticket is closed", "NOT_RESOLVED", current=r.status)
        r.status, r.closed_at = "closed", now_utc()
        if rating is not None:
            r.rating = rating.rating
        m = await self.timeline(
            "sr",
            r.id,
            "auto_closed" if auto else "closed",
            rating=rating.rating if rating else None,
            comment=rating.comment if rating else None,
        )
        if m.get("asset_id"):
            a = (await self.db.execute(select(Asset).where(Asset.id == uuid.UUID(m["asset_id"])))).scalar_one_or_none()
            if a is not None and a.status == "under_repair":
                a.status = "in_use"
        await self._mirror_hostel(m, "closed")
        await self.db.flush()
        await self._emit(
            "service_request.closed", {"service_request_id": str(r.id), "rating": r.rating}, "service_request", r.id
        )
        return (await self.outs([r]))[0]

    async def rate(self, rid: uuid.UUID, body: FacServiceRate) -> FacServiceRequestOut:
        r = await self.row(rid)
        if r.requested_by != self.actor_id:
            raise forbidden("Only the requester rates the service")
        if r.status == "closed":
            r.rating = body.rating
            await self.timeline("sr", r.id, "rated", rating=body.rating, comment=body.comment)
            await self.db.flush()
            return await self.get(r.id)
        return await self.close(rid, rating=body)

    async def reopen(self, rid: uuid.UUID, remarks: str | None) -> FacServiceRequestOut:
        self.require_writer()
        r = await self.row(rid, for_update=True)
        if r.requested_by != self.actor_id and not self.can("facilities", "manage"):
            raise forbidden("Only the requester reopens the ticket")
        if r.status not in ("resolved", "closed"):
            raise rule("Only a resolved / closed ticket is reopened", "NOT_RESOLVED")
        days = await self.int_setting("facilities", "reopen_days", 7)
        if r.resolved_at and now_utc() - r.resolved_at > timedelta(days=days):
            raise rule(f"Tickets can be reopened within {days} days of resolution", "REOPEN_WINDOW")
        r.status, r.closed_at = "reopened", None
        r.sla_due_at = now_utc() + timedelta(hours=await self.sla_hours(r.category, r.priority))
        m = await self.timeline("sr", r.id, "reopened", remarks=remarks)
        await self._mirror_hostel(m, "in_progress")
        await self.db.flush()
        await self._emit("service_request.reopened", {"service_request_id": str(r.id)}, "service_request", r.id)
        return await self.get(r.id)

    async def _mirror_hostel(self, m: dict[str, Any], status: str) -> None:
        if not m.get("hostel_complaint_id"):
            return
        from app.models.hostel import HostelComplaint

        hc = (
            await self.db.execute(
                select(HostelComplaint).where(HostelComplaint.id == uuid.UUID(m["hostel_complaint_id"]))
            )
        ).scalar_one_or_none()
        if hc is not None:
            hc.status = status
            if status in ("resolved", "closed"):
                hc.resolved_at = now_utc()

    # ---- dashboard / Beat --------------------------------------------------------------------------------------------------
    async def dashboard(self) -> FacServiceDashboard:
        base = select(ServiceRequest).where(ServiceRequest.institution_id == self.inst, self._visible()).subquery()
        by_status = {
            s: int(n)
            for s, n in (await self.db.execute(select(base.c.status, func.count()).group_by(base.c.status))).all()
        }
        open_rows = select(base).where(base.c.status.in_(OPEN_SERVICE)).subquery()
        by_cat = {
            c: int(n)
            for c, n in (
                await self.db.execute(select(open_rows.c.category, func.count()).group_by(open_rows.c.category))
            ).all()
        }
        now = now_utc()
        breached = (
            await self.db.execute(select(func.count()).select_from(open_rows).where(open_rows.c.sla_due_at < now))
        ).scalar_one()
        due = (
            await self.db.execute(
                select(func.count())
                .select_from(open_rows)
                .where(open_rows.c.sla_due_at >= now, open_rows.c.sla_due_at < now + timedelta(hours=24))
            )
        ).scalar_one()
        mttr = (
            await self.db.execute(
                select(func.avg(func.extract("epoch", base.c.resolved_at - base.c.created_at))).where(
                    base.c.resolved_at.is_not(None)
                )
            )
        ).scalar_one()
        csat, rated = (
            await self.db.execute(
                select(func.avg(base.c.rating), func.count(base.c.rating)).where(base.c.rating.is_not(None))
            )
        ).one()
        ages: dict[str, int] = {"<1d": 0, "1-3d": 0, "3-7d": 0, ">7d": 0}
        for (created,) in (await self.db.execute(select(open_rows.c.created_at))).all():
            d = (now - created).days
            ages["<1d" if d < 1 else "1-3d" if d < 3 else "3-7d" if d < 7 else ">7d"] += 1
        return FacServiceDashboard(
            open=sum(by_cat.values()),
            by_status=by_status,
            by_category=by_cat,
            breached=int(breached),
            due_24h=int(due),
            mttr_hours=round(float(mttr) / 3600, 1) if mttr else None,
            csat=round(float(csat), 2) if csat else None,
            rated=int(rated or 0),
            backlog_by_age=ages,
        )

    async def sla_scan(self) -> int:
        rows = (
            (
                await self.db.execute(
                    select(ServiceRequest).where(
                        ServiceRequest.institution_id == self.inst,
                        ServiceRequest.status.in_(OPEN_SERVICE),
                        ServiceRequest.sla_due_at < now_utc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        n = 0
        metas = await self.metas("sr", [r.id for r in rows])
        for r in rows:
            m = metas.get(str(r.id), {})
            if m.get("breached"):
                continue
            m["breached"] = now_utc().isoformat()
            await self.put_meta("sr", r.id, m)
            await self._emit("service_request.sla_breached", {"service_request_id": str(r.id)}, "service_request", r.id)
            await self._notify(
                "service_request.sla_breach",
                [r.assigned_to],
                {
                    "ticket": r.ticket_number,
                    "category": r.category,
                    "due": r.sla_due_at.isoformat() if r.sla_due_at else "",
                },
                audience={"user_ids": [str(r.assigned_to)] if r.assigned_to else [], "roles": ["estate_officer"]},
            )
            n += 1
        return n

    async def auto_close(self) -> int:
        days = await self.int_setting("facilities", "auto_close_days", 3)
        ids = (
            (
                await self.db.execute(
                    select(ServiceRequest.id).where(
                        ServiceRequest.institution_id == self.inst,
                        ServiceRequest.status == "resolved",
                        ServiceRequest.resolved_at < now_utc() - timedelta(days=days),
                    )
                )
            )
            .scalars()
            .all()
        )
        for rid in ids:
            await self.close(rid, auto=True)
        return len(ids)

    # ---- AMC --------------------------------------------------------------------------------------------------------------
    async def amc_outs(self, rows: Sequence[AmcContract]) -> list[FacAmcContractOut]:
        sup = {
            s.id: s.name
            for s in (
                await self.db.execute(
                    select(Supplier).where(Supplier.id.in_([r.supplier_id for r in rows] or [uuid.uuid4()]))
                )
            ).scalars()
        }
        today = await self.today()
        out = []
        for r in rows:
            o = FacAmcContractOut.model_validate(r)
            o.supplier_name = sup.get(r.supplier_id)
            o.days_left = (r.to_on - today).days
            out.append(o)
        return out

    async def amc_list(self) -> list[FacAmcContractOut]:
        self.require("facilities:manage", "facilities:view_all")
        rows = (
            (
                await self.db.execute(
                    select(AmcContract).where(AmcContract.institution_id == self.inst).order_by(AmcContract.to_on)
                )
            )
            .scalars()
            .all()
        )
        return await self.amc_outs(rows)

    async def amc_save(self, body: FacAmcContractIn, cid: uuid.UUID | None = None) -> FacAmcContractOut:
        self.require("facilities:manage")
        if body.to_on < body.from_on:
            raise APIError(422, ErrorCode.VALIDATION, "to_on must not be before from_on")
        data = body.model_dump(mode="json")
        data["from_on"], data["to_on"] = body.from_on, body.to_on
        data["supplier_id"] = body.supplier_id
        if cid is None:
            row: AmcContract | None = AmcContract(institution_id=self.inst, **data)
            self.db.add(row)
        else:
            row = (
                await self.db.execute(
                    select(AmcContract).where(AmcContract.id == cid, AmcContract.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if row is None:
                raise not_found("AMC contract")
            for k, v in data.items():
                setattr(row, k, v)
        assert row is not None
        await self.db.flush()
        await self._audit(
            "update" if cid else "create", "amc_contract", row.id, None, {"supplier_id": str(row.supplier_id)}
        )
        return (await self.amc_outs([row]))[0]

    async def amc_performance(self, cid: uuid.UUID) -> FacAmcPerformance:
        self.require("facilities:manage", "facilities:view_all")
        tagged = [uuid.UUID(k) for k, m in (await self.metas("sr")).items() if m.get("amc_contract_id") == str(cid)]
        rows = (
            (await self.db.execute(select(ServiceRequest).where(ServiceRequest.id.in_(tagged or [uuid.uuid4()]))))
            .scalars()
            .all()
        )
        resolved = [r for r in rows if r.resolved_at]
        breached = [r for r in rows if r.sla_due_at and (r.resolved_at or now_utc()) > r.sla_due_at]
        rated = [r.rating for r in rows if r.rating]
        mttr = (
            sum((r.resolved_at - r.created_at).total_seconds() for r in resolved if r.resolved_at)
            / len(resolved)
            / 3600
            if resolved
            else None
        )
        return FacAmcPerformance(
            contract_id=cid,
            tickets=len(rows),
            resolved=len(resolved),
            breached=len(breached),
            mttr_hours=round(mttr, 1) if mttr is not None else None,
            csat=round(sum(rated) / len(rated), 2) if rated else None,
        )

    async def amc_expiry_scan(self) -> int:
        today = await self.today()
        n = 0
        for row in (
            await self.db.execute(
                select(AmcContract).where(AmcContract.institution_id == self.inst, AmcContract.status == "active")
            )
        ).scalars():
            left = (row.to_on - today).days
            if left < 0:
                row.status = "expired"
            elif left in (60, 30) or left <= 7:
                await self._emit(
                    "amc.expiring", {"contract_id": str(row.id), "days_left": left}, "amc_contract", row.id
                )
                n += 1
        await self.db.flush()
        return n

    # ---- lost & found -------------------------------------------------------------------------------------------------------
    async def lf_list(self, status: str | None = None) -> list[FacLostFoundOut]:
        stmt = select(LostFoundItem).where(LostFoundItem.institution_id == self.inst)
        if status:
            stmt = stmt.where(LostFoundItem.status == status)
        rows = (await self.db.execute(stmt.order_by(LostFoundItem.created_at.desc()).limit(500))).scalars().all()
        manage = self.can("facilities", "manage") or self.can("facilities", "view_all")
        out = []
        for r in rows:
            o = FacLostFoundOut.model_validate(r)
            if not manage and r.claimant and r.reported_by != self.actor_id:
                o.claimant = {"claimed": True}
            out.append(o)
        return out

    async def lf_report(self, body: FacLostFoundIn) -> FacLostFoundOut:
        self.require_writer()
        row = LostFoundItem(
            institution_id=self.inst,
            description=body.description,
            found_at=body.found_at or now_utc(),
            location=body.location,
            image_url=body.image_url,
            reported_by=self.actor_id,
            status="reported",
        )
        self.db.add(row)
        await self.db.flush()
        await self._emit("lost_found.reported", {"item_id": str(row.id)}, "lost_found_item", row.id)
        return FacLostFoundOut.model_validate(row)

    async def lf_claim(self, iid: uuid.UUID, body: FacLostFoundClaim) -> FacLostFoundOut:
        self.require("facilities:manage")
        row = (
            await self.db.execute(
                select(LostFoundItem)
                .where(LostFoundItem.id == iid, LostFoundItem.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise not_found("Item")
        if row.status != "reported":
            raise rule("The item was already claimed or disposed", "NOT_AVAILABLE")
        row.status = "claimed"
        row.claimant = {**body.model_dump(mode="json"), "verified_by": str(self.actor_id), "at": now_utc().isoformat()}
        await self.db.flush()
        await self._audit("claim", "lost_found_item", row.id, None, {"claimant": body.name})
        await self._emit("lost_found.claimed", {"item_id": str(row.id)}, "lost_found_item", row.id)
        return FacLostFoundOut.model_validate(row)

    async def lf_dispose(self, iid: uuid.UUID) -> FacLostFoundOut:
        self.require("facilities:manage")
        row = (
            await self.db.execute(
                select(LostFoundItem)
                .where(LostFoundItem.id == iid, LostFoundItem.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise not_found("Item")
        if row.status != "reported":
            raise rule("Only an unclaimed item is disposed", "NOT_AVAILABLE")
        days = await self.int_setting("facilities", "lost_found_retention_days", 90)
        if row.created_at > now_utc() - timedelta(days=days):
            raise rule(f"Items are kept {days} days before disposal", "RETENTION_ACTIVE", retention_days=days)
        row.status = "disposed"
        await self.db.flush()
        await self._audit("dispose", "lost_found_item", row.id, None, {"status": "disposed"})
        return FacLostFoundOut.model_validate(row)

    async def export_rows(self, d0: date | None = None) -> list[dict[str, Any]]:
        return [o.model_dump(mode="json") for o in await self.list_requests(limit=5000)]
