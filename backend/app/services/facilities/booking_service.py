"""Room & equipment booking — Prompts/25 §25.6 ``booking_service`` ({facilities.room_booking},
{facilities.equipment_booking}).

1. **Availability / conflicts** — a room is blocked by approved bookings, the published timetable of every term that
   covers the date (``timetable_entries`` day / slot → wall-clock time, every week pattern counts), ``class_sessions``
   (rescheduled / extra classes), exam seating plans (FN / AN / EVE slots) and an inactive / non-bookable room.
2. **Requests** — ``facilities.booking_lead_hours`` ahead (422 otherwise); holders of ``facilities:approve_booking`` and
   the ``facilities.auto_approve_roles`` (HOD / dean) are auto-approved when the slot is free, everyone else goes
   through the ``facilities.room_booking`` workflow (estate officer). ``rooms`` has no owning-department column in the
   canonical DDL, so the "room owner HOD first" step of the prompt is not modelled. Approval re-checks conflicts under
   ``SELECT … FOR UPDATE`` on the room → 409 ``ROOM_CONFLICT``. Recurring weekly bookings are created per instance with
   their own conflicts; approved bookings mirror into ``calendar_events`` (``source_type='room_booking'``).
3. **Equipment** — ``assets.is_bookable`` items; overlapping live bookings conflict; the ``facilities.equipment_booking``
   workflow runs custodian → estate officer when the asset has a custodian with a login (otherwise an approver decides
   directly); handover / return record the condition (``facilities_meta``); overdue returns are reminded daily.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.academic import AcademicTerm
from app.models.exams import ExamSeatingPlan
from app.models.facilities import EquipmentBooking, RoomBooking
from app.models.inventory import Asset
from app.models.platform import WorkflowInstance
from app.models.timetable import ClassSession, Room, TimeSlot, Timetable, TimetableEntry
from app.schemas.facilities import (
    FacAvailabilityOut,
    FacAvailabilitySlot,
    FacBookingDecision,
    FacConflict,
    FacEquipmentBookingCreate,
    FacEquipmentBookingOut,
    FacHandover,
    FacRecurringBooking,
    FacRecurringResult,
    FacRoomBookingCreate,
    FacRoomBookingOut,
)
from app.services.facilities.common import FacilitiesBase, forbidden, not_found, now_utc, rule, scope_ids

EXAM_SLOTS = {"FN": (time(9, 30), time(13, 0)), "AN": (time(13, 30), time(17, 0)), "EVE": (time(17, 0), time(20, 0))}
RB_KEYS = ("room_id", "from_at", "to_at", "purpose", "status")


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


class BookingService(FacilitiesBase):
    audit_module = "facilities"

    async def tz(self) -> Any:
        from app.core.tenancy import institution_tz

        return institution_tz(await self.institution())

    # ---- conflict engine ----------------------------------------------------------------------------------------------
    async def room(self, room_id: uuid.UUID, *, for_update: bool = False) -> Room:
        stmt = select(Room).where(Room.id == room_id, Room.institution_id == self.inst, Room.deleted_at.is_(None))
        if for_update:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Room")
        return r

    async def conflicts(
        self,
        room: Room,
        f: datetime,
        t: datetime,
        *,
        exclude_booking: uuid.UUID | None = None,
        exclude_event: uuid.UUID | None = None,
    ) -> list[FacConflict]:
        tz = await self.tz()
        out: list[FacConflict] = []
        if not room.is_active or not room.is_bookable:
            out.append(FacConflict(kind="room_status", title=f"{room.code} is not bookable"))
        stmt = select(RoomBooking).where(
            RoomBooking.room_id == room.id,
            RoomBooking.status == "approved",
            RoomBooking.from_at < t,
            RoomBooking.to_at > f,
        )
        if exclude_booking:
            stmt = stmt.where(RoomBooking.id != exclude_booking)
        if exclude_event:
            stmt = stmt.where(or_(RoomBooking.event_id.is_(None), RoomBooking.event_id != exclude_event))
        for b in (await self.db.execute(stmt)).scalars():
            out.append(FacConflict(kind="booking", source_id=b.id, title=b.purpose, from_at=b.from_at, to_at=b.to_at))
        d0, d1 = f.astimezone(tz).date(), t.astimezone(tz).date()
        # published timetables of the terms covering the window
        rows = (
            await self.db.execute(
                select(TimetableEntry, TimeSlot, AcademicTerm.start_date, AcademicTerm.end_date)
                .join(Timetable, Timetable.id == TimetableEntry.timetable_id)
                .join(TimeSlot, TimeSlot.id == TimetableEntry.time_slot_id)
                .join(AcademicTerm, AcademicTerm.id == TimetableEntry.term_id)
                .where(
                    TimetableEntry.room_id == room.id,
                    TimetableEntry.is_active.is_(True),
                    Timetable.status == "published",
                    AcademicTerm.start_date <= d1,
                    AcademicTerm.end_date >= d0,
                )
            )
        ).all()
        day = d0
        while day <= d1 and rows:
            for e, slot, ts, te in rows:
                if not (ts <= day <= te) or e.day_of_week != day.isoweekday():
                    continue
                s0 = datetime.combine(day, slot.start_time, tzinfo=tz).astimezone(UTC)
                s1 = datetime.combine(day, slot.end_time, tzinfo=tz).astimezone(UTC)
                if _overlap(f, t, s0, s1):
                    out.append(
                        FacConflict(
                            kind="timetable", source_id=e.id, title=f"Timetable slot {slot.name}", from_at=s0, to_at=s1
                        )
                    )
            day += timedelta(days=1)
        sessions = (
            await self.db.execute(
                select(ClassSession).where(
                    ClassSession.room_id == room.id,
                    ClassSession.session_date >= d0,
                    ClassSession.session_date <= d1,
                    ClassSession.status.in_(("scheduled", "conducted")),
                    ClassSession.timetable_entry_id.is_(None),
                )
            )
        ).scalars()
        for s in sessions:
            s0 = datetime.combine(s.session_date, s.start_time, tzinfo=tz).astimezone(UTC)
            s1 = datetime.combine(s.session_date, s.end_time, tzinfo=tz).astimezone(UTC)
            if _overlap(f, t, s0, s1):
                out.append(
                    FacConflict(
                        kind="class_session", source_id=s.id, title=s.topic or "Extra class", from_at=s0, to_at=s1
                    )
                )
        for plan in (
            await self.db.execute(
                select(ExamSeatingPlan).where(
                    ExamSeatingPlan.room_id == room.id,
                    ExamSeatingPlan.exam_date >= d0,
                    ExamSeatingPlan.exam_date <= d1,
                    ExamSeatingPlan.status != "cancelled",
                )
            )
        ).scalars():
            t_a, t_b = EXAM_SLOTS.get(plan.session_slot, EXAM_SLOTS["FN"])
            s0 = datetime.combine(plan.exam_date, t_a, tzinfo=tz).astimezone(UTC)
            s1 = datetime.combine(plan.exam_date, t_b, tzinfo=tz).astimezone(UTC)
            if _overlap(f, t, s0, s1):
                out.append(
                    FacConflict(
                        kind="exam", source_id=plan.id, title=f"Exam seating {plan.session_slot}", from_at=s0, to_at=s1
                    )
                )
        return out

    async def availability(
        self,
        f: datetime,
        t: datetime,
        *,
        room_id: uuid.UUID | None = None,
        building_id: uuid.UUID | None = None,
        capacity_min: int | None = None,
        features: Sequence[str] = (),
    ) -> FacAvailabilityOut:
        if t <= f:
            raise APIError(422, ErrorCode.VALIDATION, "to_at must be after from_at")
        stmt = select(Room).where(Room.institution_id == self.inst, Room.deleted_at.is_(None), Room.is_active.is_(True))
        if room_id:
            stmt = stmt.where(Room.id == room_id)
        if building_id:
            stmt = stmt.where(Room.building_id == building_id)
        if capacity_min:
            stmt = stmt.where(Room.capacity >= capacity_min)
        rooms = (await self.db.execute(stmt.order_by(Room.code).limit(200))).scalars().all()
        out = []
        for r in rooms:
            feats = r.features if isinstance(r.features, list) else list((r.features or {}).keys())
            if features and not set(features) <= {str(x) for x in feats}:
                continue
            c = await self.conflicts(r, f, t)
            out.append(
                FacAvailabilitySlot(
                    room_id=r.id,
                    room_code=r.code,
                    room_name=r.name,
                    capacity=r.capacity,
                    building_id=r.building_id,
                    available=not c,
                    conflicts=c,
                )
            )
        return FacAvailabilityOut(from_at=f, to_at=t, rooms=out)

    # ---- room bookings --------------------------------------------------------------------------------------------------
    def _visible(self) -> Any:
        return self.unit_predicate("facilities", self_cols=(RoomBooking.requested_by,), college_col=Room.college_id) | (
            RoomBooking.requested_by.in_(self.requester_dept_subquery())
            if (scope_ids(self.principal, "department") or scope_ids(self.principal, "faculty")) and self.reader()
            else RoomBooking.id.is_(None)
        )

    async def booking_outs(
        self, rows: Sequence[RoomBooking], conflicts: dict[uuid.UUID, list[FacConflict]] | None = None
    ) -> list[FacRoomBookingOut]:
        rooms = {
            r.id: r
            for r in (
                await self.db.execute(select(Room).where(Room.id.in_([b.room_id for b in rows] or [uuid.uuid4()])))
            ).scalars()
        }
        names = await self.user_names([b.requested_by for b in rows])
        out = []
        for b in rows:
            o = FacRoomBookingOut.model_validate(b)
            rm = rooms.get(b.room_id)
            o.room_code, o.room_name = (rm.code, rm.name) if rm else (None, None)
            o.requester_name = names.get(b.requested_by)
            o.conflicts = (conflicts or {}).get(b.id, [])
            out.append(o)
        return out

    async def list_bookings(
        self,
        *,
        status: str | None = None,
        room_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        mine: bool = False,
    ) -> list[FacRoomBookingOut]:
        stmt = (
            select(RoomBooking)
            .join(Room, Room.id == RoomBooking.room_id)
            .where(RoomBooking.institution_id == self.inst)
        )
        stmt = stmt.where(RoomBooking.requested_by == self.actor_id) if mine else stmt.where(self._visible())
        if status:
            stmt = stmt.where(RoomBooking.status == status)
        if room_id:
            stmt = stmt.where(RoomBooking.room_id == room_id)
        if date_from:
            stmt = stmt.where(RoomBooking.to_at >= date_from)
        if date_to:
            stmt = stmt.where(RoomBooking.from_at <= date_to)
        rows = (await self.db.execute(stmt.order_by(RoomBooking.from_at.desc()).limit(500))).scalars().all()
        return await self.booking_outs(rows)

    async def booking_row(self, bid: uuid.UUID, *, for_update: bool = False) -> RoomBooking:
        stmt = (
            select(RoomBooking)
            .join(Room, Room.id == RoomBooking.room_id)
            .where(RoomBooking.id == bid, RoomBooking.institution_id == self.inst, self._visible())
        )
        if for_update:
            stmt = stmt.with_for_update(of=RoomBooking)
        b = (await self.db.execute(stmt)).scalar_one_or_none()
        if b is None:
            raise not_found("Booking")
        return b

    async def get_booking(self, bid: uuid.UUID) -> FacRoomBookingOut:
        b = await self.booking_row(bid)
        c = (
            await self.conflicts(await self.room(b.room_id), b.from_at, b.to_at, exclude_booking=b.id)
            if b.status == "requested"
            else []
        )
        return (await self.booking_outs([b], {b.id: c}))[0]

    async def _auto_approve(self) -> bool:
        if self.can("facilities", "approve_booking"):
            return True
        roles = await self.setting("facilities", "auto_approve_roles")
        mine = set(getattr(self.principal, "roles", None) or [])
        return bool(isinstance(roles, list) and mine & set(roles))

    async def request_room(
        self, body: FacRoomBookingCreate, *, check_lead: bool = True, auto: bool | None = None, emit: bool = True
    ) -> FacRoomBookingOut:
        self.require("facilities:book", "facilities:approve_booking", "facilities:manage")
        self.require_writer()
        room = await self.room(body.room_id, for_update=True)
        if check_lead:
            lead = await self.int_setting("facilities", "booking_lead_hours", 24)
            if body.from_at < now_utc() + timedelta(hours=lead) and not self.can("facilities", "approve_booking"):
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"Book at least {lead} hours ahead",
                    {"code": "LEAD_TIME", "lead_hours": lead},
                )
        if body.expected_headcount and room.capacity and body.expected_headcount > room.capacity:
            raise APIError(422, ErrorCode.VALIDATION, f"{room.code} seats {room.capacity}", {"code": "OVER_CAPACITY"})
        conflicts = await self.conflicts(room, body.from_at, body.to_at, exclude_event=body.event_id)
        b = RoomBooking(
            institution_id=self.inst,
            room_id=room.id,
            requested_by=self.actor_id,
            purpose=body.purpose,
            from_at=body.from_at,
            to_at=body.to_at,
            expected_headcount=body.expected_headcount,
            event_id=body.event_id,
            status="requested",
        )
        self.db.add(b)
        await self.db.flush()
        auto_ok = (await self._auto_approve()) if auto is None else auto
        approved = False
        if auto_ok and not conflicts:
            b.status = "approved"
            approved = True
            await self._mirror(b, room)
        elif not auto_ok:
            inst = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="facilities.room_booking",
                entity_type="room_booking",
                entity_id=b.id,
                started_by=self.actor_id,
                context={"college_id": str(room.college_id), "room_id": str(room.id)},
                title=f"Room {room.code} · {body.purpose}"[:200],
            )
            b.workflow_instance_id = inst.id
        await self.db.flush()
        await self._audit("create", "room_booking", b.id, None, {"room": room.code, "status": b.status})
        if emit:
            await self._emit(
                "booking.approved" if approved else ("booking.conflict" if conflicts else "booking.requested"),
                {"booking_id": str(b.id), "room_id": str(room.id)},
                "room_booking",
                b.id,
            )
        out = (await self.booking_outs([b], {b.id: conflicts}))[0]
        out.auto_approved = approved
        return out

    async def _mirror(self, b: RoomBooking, room: Room) -> None:
        from app.services.facilities.calendar_service import CalendarService

        await CalendarService(self.db, self.principal, self.request, self.inst).mirror(
            "room_booking",
            b.id,
            title=f"{room.code}: {b.purpose}",
            starts=b.from_at,
            ends=b.to_at,
            event_type="general",
            college_id=room.college_id,
            location=room.code,
            audience={"roles": ["estate_officer", "registrar"]},
        )

    async def decide(
        self, bid: uuid.UUID, body: FacBookingDecision, *, via_workflow: bool = False
    ) -> FacRoomBookingOut:
        if not via_workflow:
            self.require("facilities:approve_booking", "facilities:manage")
            self.require_writer()
        b = await self.booking_row(bid, for_update=True) if not via_workflow else await self._row_any(bid)
        if b.status != "requested":
            raise rule("Only a requested booking can be decided", "NOT_REQUESTED", current=b.status)
        if not via_workflow:
            await self.close_workflow(b.workflow_instance_id, "approved" if body.action == "approve" else "rejected")
        room = await self.room(b.room_id, for_update=True)
        if body.action == "approve":
            c = await self.conflicts(room, b.from_at, b.to_at, exclude_booking=b.id, exclude_event=b.event_id)
            if c:
                raise APIError(
                    409,
                    ErrorCode.CONFLICT,
                    f"{room.code} is no longer free for this slot",
                    {"code": "ROOM_CONFLICT", "conflicts": [x.model_dump(mode="json") for x in c]},
                )
            b.status = "approved"
            await self._mirror(b, room)
        else:
            b.status = "rejected"
        await self.db.flush()
        await self._audit(body.action, "room_booking", b.id, None, {"status": b.status, "remarks": body.remarks})
        await self._emit(f"booking.{b.status}", {"booking_id": str(b.id)}, "room_booking", b.id)
        await self._notify(
            "booking.decided",
            [b.requested_by],
            {"room": room.code, "from_at": b.from_at.isoformat(), "status": b.status, "remarks": body.remarks or ""},
        )
        return (await self.booking_outs([b]))[0]

    async def _row_any(self, bid: uuid.UUID) -> RoomBooking:
        b = (
            await self.db.execute(select(RoomBooking).where(RoomBooking.id == bid).with_for_update())
        ).scalar_one_or_none()
        if b is None:
            raise not_found("Booking")
        return b

    async def cancel(self, bid: uuid.UUID) -> FacRoomBookingOut:
        b = await self.booking_row(bid, for_update=True)
        if b.requested_by != self.actor_id and not self.can("facilities", "manage"):
            raise forbidden("Only the requester cancels a booking")
        if b.status not in ("requested", "approved"):
            raise rule("This booking cannot be cancelled", "NOT_CANCELLABLE", current=b.status)
        b.status = "cancelled"
        await self.close_workflow(b.workflow_instance_id)
        from app.services.facilities.calendar_service import CalendarService

        await CalendarService(self.db, self.principal, self.request, self.inst).unmirror("room_booking", b.id)
        await self.db.flush()
        await self._audit("cancel", "room_booking", b.id, None, {"status": "cancelled"})
        await self._emit("booking.cancelled", {"booking_id": str(b.id)}, "room_booking", b.id)
        return (await self.booking_outs([b]))[0]

    async def recurring(self, body: FacRecurringBooking) -> FacRecurringResult:
        created: list[FacRoomBookingOut] = []
        conflicts: list[dict[str, Any]] = []
        for w in range(body.weeks):
            delta = timedelta(weeks=w)
            req = FacRoomBookingCreate(
                room_id=body.room_id,
                from_at=body.from_at + delta,
                to_at=body.to_at + delta,
                purpose=body.purpose,
                expected_headcount=body.expected_headcount,
            )
            room = await self.room(body.room_id)
            c = await self.conflicts(room, req.from_at, req.to_at)
            if c:
                conflicts.append(
                    {
                        "week": w + 1,
                        "from_at": req.from_at.isoformat(),
                        "conflicts": [x.model_dump(mode="json") for x in c],
                    }
                )
                continue
            created.append(await self.request_room(req, check_lead=w == 0))
        return FacRecurringResult(created=created, conflicts=conflicts)

    async def for_event(
        self, event_id: uuid.UUID, room_id: uuid.UUID, d0: date, d1: date, title: str
    ) -> FacRoomBookingOut:
        """Venue booking of a scheduled event: approved when free, else 409 ``ROOM_CONFLICT`` (the event stays approved)."""
        tz = await self.tz()
        f = datetime.combine(d0, time(9, 0), tzinfo=tz).astimezone(UTC)
        t = datetime.combine(d1, time(18, 0), tzinfo=tz).astimezone(UTC)
        room = await self.room(room_id, for_update=True)
        existing = (
            await self.db.execute(
                select(RoomBooking).where(
                    RoomBooking.event_id == event_id, RoomBooking.status.in_(("requested", "approved"))
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return (await self.booking_outs([existing]))[0]
        c = await self.conflicts(room, f, t, exclude_event=event_id)
        if c:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"{room.code} is not free for the event dates",
                {"code": "ROOM_CONFLICT", "conflicts": [x.model_dump(mode="json") for x in c]},
            )
        return await self.request_room(
            FacRoomBookingCreate(
                room_id=room_id, from_at=f, to_at=t, purpose=f"Event: {title}"[:200], event_id=event_id
            ),
            check_lead=False,
            auto=True,
        )

    async def release_event(self, event_id: uuid.UUID) -> None:
        for b in (
            await self.db.execute(
                select(RoomBooking).where(
                    RoomBooking.event_id == event_id, RoomBooking.status.in_(("requested", "approved"))
                )
            )
        ).scalars():
            b.status = "cancelled"
            from app.services.facilities.calendar_service import CalendarService

            await CalendarService(self.db, self.principal, self.request, self.inst).unmirror("room_booking", b.id)
        await self.db.flush()

    async def usage(self, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(
                    Room.code,
                    Room.name,
                    func.count(RoomBooking.id),
                    func.coalesce(func.sum(func.extract("epoch", RoomBooking.to_at - RoomBooking.from_at)), 0),
                )
                .join(RoomBooking, RoomBooking.room_id == Room.id)
                .where(
                    RoomBooking.institution_id == self.inst,
                    RoomBooking.status == "approved",
                    RoomBooking.from_at >= date_from,
                    RoomBooking.from_at <= date_to,
                )
                .group_by(Room.code, Room.name)
                .order_by(Room.code)
            )
        ).all()
        return [{"room": c, "name": n, "bookings": int(k), "hours": round(float(s) / 3600, 1)} for c, n, k, s in rows]

    # ---- equipment ---------------------------------------------------------------------------------------------------------
    def _eq_visible(self) -> Any:
        return self.unit_predicate(
            "facilities",
            self_cols=(EquipmentBooking.requested_by, EquipmentBooking.approved_by),
            college_col=Asset.college_id,
        )

    async def eq_outs(self, rows: Sequence[EquipmentBooking]) -> list[FacEquipmentBookingOut]:
        assets = {
            a.id: a
            for a in (
                await self.db.execute(select(Asset).where(Asset.id.in_([b.asset_id for b in rows] or [uuid.uuid4()])))
            ).scalars()
        }
        names = await self.user_names([b.requested_by for b in rows])
        metas = await self.metas("equipment", [b.id for b in rows])
        now = now_utc()
        out = []
        for b in rows:
            o = FacEquipmentBookingOut.model_validate(b)
            a = assets.get(b.asset_id)
            o.asset_tag, o.asset_name = (a.asset_tag, a.name) if a else (None, None)
            o.requester_name = names.get(b.requested_by)
            m = metas.get(str(b.id), {})
            o.handover, o.returned = m.get("handover"), m.get("returned")
            o.overdue = b.status == "handed_over" and b.to_at < now
            out.append(o)
        return out

    async def eq_list(self, *, mine: bool = False, status: str | None = None) -> list[FacEquipmentBookingOut]:
        stmt = (
            select(EquipmentBooking)
            .join(Asset, Asset.id == EquipmentBooking.asset_id)
            .where(EquipmentBooking.institution_id == self.inst)
        )
        stmt = (
            stmt.where(EquipmentBooking.requested_by == self.actor_id)
            if mine
            else stmt.where(self._eq_visible() | self._custodian_pred())
        )
        if status:
            stmt = stmt.where(EquipmentBooking.status == status)
        rows = (await self.db.execute(stmt.order_by(EquipmentBooking.from_at.desc()).limit(500))).scalars().all()
        return await self.eq_outs(rows)

    def _custodian_pred(self) -> Any:
        from app.models.hr import Staff

        return Asset.custodian_staff_id.in_(select(Staff.id).where(Staff.user_id == self.actor_id))

    async def eq_row(self, bid: uuid.UUID) -> EquipmentBooking:
        b = (
            await self.db.execute(
                select(EquipmentBooking)
                .join(Asset, Asset.id == EquipmentBooking.asset_id)
                .where(
                    EquipmentBooking.id == bid,
                    EquipmentBooking.institution_id == self.inst,
                    self._eq_visible() | self._custodian_pred(),
                )
                .with_for_update(of=EquipmentBooking)
            )
        ).scalar_one_or_none()
        if b is None:
            raise not_found("Equipment booking")
        return b

    async def eq_request(self, body: FacEquipmentBookingCreate) -> FacEquipmentBookingOut:
        from app.models.hr import Staff

        self.require("facilities:book", "facilities:manage")
        self.require_writer()
        a = (
            await self.db.execute(
                select(Asset).where(Asset.id == body.asset_id, Asset.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if a is None or a.deleted_at is not None:
            raise not_found("Asset")
        if not a.is_bookable or a.status in ("under_repair", "condemned", "disposed"):
            raise rule(f"{a.asset_tag} cannot be booked", "NOT_BOOKABLE", current=a.status)
        clash = (
            await self.db.execute(
                select(func.count())
                .select_from(EquipmentBooking)
                .where(
                    EquipmentBooking.asset_id == a.id,
                    EquipmentBooking.status.in_(("requested", "approved", "handed_over")),
                    EquipmentBooking.from_at < body.to_at,
                    EquipmentBooking.to_at > body.from_at,
                )
            )
        ).scalar_one()
        if (
            clash
            and (
                await self.db.execute(
                    select(func.count())
                    .select_from(EquipmentBooking)
                    .where(
                        EquipmentBooking.asset_id == a.id,
                        EquipmentBooking.status.in_(("approved", "handed_over")),
                        EquipmentBooking.from_at < body.to_at,
                        EquipmentBooking.to_at > body.from_at,
                    )
                )
            ).scalar_one()
        ):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"{a.asset_tag} is already booked for this period",
                {"code": "EQUIPMENT_CONFLICT"},
            )
        b = EquipmentBooking(
            institution_id=self.inst,
            asset_id=a.id,
            requested_by=self.actor_id,
            from_at=body.from_at,
            to_at=body.to_at,
            purpose=body.purpose,
            status="requested",
        )
        self.db.add(b)
        await self.db.flush()
        custodian_user = None
        if a.custodian_staff_id:
            custodian_user = (
                await self.db.execute(select(Staff.user_id).where(Staff.id == a.custodian_staff_id))
            ).scalar_one_or_none()
        if custodian_user:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="facilities.equipment_booking",
                entity_type="equipment_booking",
                entity_id=b.id,
                started_by=self.actor_id,
                context={
                    "custodian_user_id": str(custodian_user),
                    "college_id": str(a.college_id) if a.college_id else None,
                },
                title=f"{a.asset_tag} · {a.name}"[:200],
            )
            await self.put_meta("equipment", b.id, {"workflow_instance_id": str(wf.id)})
        await self._audit("create", "equipment_booking", b.id, None, {"asset": a.asset_tag})
        await self._emit(
            "equipment.booked", {"booking_id": str(b.id), "asset_id": str(a.id)}, "equipment_booking", b.id
        )
        return (await self.eq_outs([b]))[0]

    async def eq_decide(
        self, bid: uuid.UUID, body: FacBookingDecision, *, via_workflow: bool = False
    ) -> FacEquipmentBookingOut:
        if not via_workflow:
            self.require("facilities:approve_booking", "facilities:manage")
            self.require_writer()
            b = await self.eq_row(bid)
        else:
            b = (
                await self.db.execute(select(EquipmentBooking).where(EquipmentBooking.id == bid).with_for_update())
            ).scalar_one()
        if b.status != "requested":
            raise rule("Only a requested booking can be decided", "NOT_REQUESTED")
        b.status = "approved" if body.action == "approve" else "rejected"
        b.approved_by = self.actor_id
        if not via_workflow:
            wid = (await self.meta("equipment", b.id)).get("workflow_instance_id")
            await self.close_workflow(uuid.UUID(wid) if wid else None, b.status)
        await self.db.flush()
        await self._audit(body.action, "equipment_booking", b.id, None, {"status": b.status})
        await self._notify(
            "booking.decided",
            [b.requested_by],
            {"room": "equipment", "from_at": b.from_at.isoformat(), "status": b.status, "remarks": body.remarks or ""},
        )
        return (await self.eq_outs([b]))[0]

    async def eq_handover(self, bid: uuid.UUID, body: FacHandover, *, returning: bool) -> FacEquipmentBookingOut:
        self.require("facilities:approve_booking", "facilities:manage", "facilities:book")
        b = await self.eq_row(bid)
        if not (self.can("facilities", "approve_booking") or self.can("facilities", "manage")):
            raise forbidden("The custodian or the estate officer records handover / return")
        m = await self.meta("equipment", b.id)
        stamp = {
            "at": now_utc().isoformat(),
            "by": str(self.actor_id),
            "condition": body.condition,
            "remarks": body.remarks,
        }
        if returning:
            if b.status != "handed_over":
                raise rule("The equipment was not handed over", "NOT_HANDED_OVER")
            b.status, m["returned"] = "returned", stamp
            if body.condition in ("damaged", "missing_parts"):
                a = (await self.db.execute(select(Asset).where(Asset.id == b.asset_id))).scalar_one()
                a.status = "under_repair"
            await self._emit(
                "equipment.returned", {"booking_id": str(b.id), "condition": body.condition}, "equipment_booking", b.id
            )
        else:
            if b.status != "approved":
                raise rule("Only an approved booking is handed over", "NOT_APPROVED")
            b.status, m["handover"] = "handed_over", stamp
        await self.put_meta("equipment", b.id, m)
        await self.db.flush()
        await self._audit("return" if returning else "handover", "equipment_booking", b.id, None, stamp)
        return (await self.eq_outs([b]))[0]

    async def overdue_scan(self) -> int:
        rows = (
            (
                await self.db.execute(
                    select(EquipmentBooking).where(
                        EquipmentBooking.institution_id == self.inst,
                        EquipmentBooking.status == "handed_over",
                        EquipmentBooking.to_at < now_utc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        for b in rows:
            await self._emit("equipment.overdue", {"booking_id": str(b.id)}, "equipment_booking", b.id)
            await self._notify(
                "booking.decided",
                [b.requested_by],
                {
                    "room": "equipment",
                    "from_at": b.to_at.isoformat(),
                    "status": "overdue — please return it",
                    "remarks": "",
                },
            )
        return len(rows)


@workflow_engine.on("facilities.room_booking", "approved")
async def _booking_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await BookingService(db, actor, institution_id=instance.institution_id).decide(
        instance.entity_id, FacBookingDecision(action="approve"), via_workflow=True
    )


@workflow_engine.on("facilities.room_booking", "rejected")
async def _booking_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await BookingService(db, actor, institution_id=instance.institution_id).decide(
        instance.entity_id, FacBookingDecision(action="reject"), via_workflow=True
    )


@workflow_engine.on("facilities.equipment_booking", "approved")
async def _eq_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await BookingService(db, actor, institution_id=instance.institution_id).eq_decide(
        instance.entity_id, FacBookingDecision(action="approve"), via_workflow=True
    )


@workflow_engine.on("facilities.equipment_booking", "rejected")
async def _eq_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await BookingService(db, actor, institution_id=instance.institution_id).eq_decide(
        instance.entity_id, FacBookingDecision(action="reject"), via_workflow=True
    )
