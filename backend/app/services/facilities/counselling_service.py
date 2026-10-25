"""Counselling appointments — Prompts/25 §25.6 ``counselling_service`` ({facilities.counselling_appointments}).

Counsellors (``facilities:counsel`` holders with a staff row) publish slots; students / staff book one (one active
booking per person — 409), reschedule (book with ``reschedule_from``) or cancel; the counsellor completes / marks
no-show (hourly Beat marks booked slots that ended an hour ago). Notes are AES-GCM encrypted (``notes_encrypted``) and
returned **only** to the slot's counsellor; everyone else — including the person and administrators — sees
``has_notes`` at most. Administrators / IQAC get anonymised utilisation counts. Phase 27 counselling referrals
pre-book a slot with the student's consent (``book_for``).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.core.errors import APIError
from app.models.facilities import CounsellingAppointment
from app.models.hr import Staff
from app.schemas.facilities import (
    CounsellingAppointmentOut,
    CounsellingBook,
    CounsellingSlotCreate,
    CounsellingUtilisation,
)
from app.services.facilities.common import FacilitiesBase, forbidden, is_auditor, not_found, now_utc, rule

ACTIVE = ("booked",)


class CounsellingService(FacilitiesBase):
    audit_module = "facilities"

    async def _me_counsellor(self) -> uuid.UUID | None:
        if not self.can("facilities", "counsel"):
            return None
        return await self.my_staff_id()

    async def outs(
        self, rows: Sequence[CounsellingAppointment], *, me: uuid.UUID | None = None, reveal_person: bool = True
    ) -> list[CounsellingAppointmentOut]:
        staff = {
            s.id: " ".join(x for x in (s.first_name, s.last_name) if x)
            for s in (
                await self.db.execute(
                    select(Staff).where(Staff.id.in_([r.counsellor_staff_id for r in rows] or [uuid.uuid4()]))
                )
            ).scalars()
        }
        people = await self.person_names([(r.person_type, r.person_id) for r in rows]) if reveal_person else {}
        out = []
        for r in rows:
            o = CounsellingAppointmentOut(
                id=r.id,
                counsellor_staff_id=r.counsellor_staff_id,
                counsellor_name=staff.get(r.counsellor_staff_id),
                slot_at=r.slot_at,
                duration_minutes=r.duration_minutes,
                person_type=r.person_type if reveal_person or me == r.counsellor_staff_id else None,
                person_id=r.person_id if reveal_person or me == r.counsellor_staff_id else None,
                person_name=people.get(r.person_id) if r.person_id else None,
                status=r.status,
                is_confidential=r.is_confidential,
                has_notes=r.notes_encrypted is not None,
            )
            if me is not None and me == r.counsellor_staff_id:
                o.notes = r.notes_encrypted
            out.append(o)
        return out

    async def publish(self, body: CounsellingSlotCreate) -> list[CounsellingAppointmentOut]:
        me = await self._me_counsellor()
        target = body.counsellor_staff_id or me
        if target is None:
            raise forbidden("facilities:counsel required")
        if target != me and not self.can("facilities", "manage"):
            raise forbidden("Counsellors publish their own slots")
        rows = []
        for s in body.slots:
            clash = (
                await self.db.execute(
                    select(func.count())
                    .select_from(CounsellingAppointment)
                    .where(
                        CounsellingAppointment.counsellor_staff_id == target,
                        CounsellingAppointment.slot_at == s.at,
                        CounsellingAppointment.status != "cancelled",
                    )
                )
            ).scalar_one()
            if clash:
                continue
            r = CounsellingAppointment(
                institution_id=self.inst,
                counsellor_staff_id=target,
                slot_at=s.at,
                duration_minutes=s.duration,
                status="available",
            )
            self.db.add(r)
            rows.append(r)
        await self.db.flush()
        await self._audit("publish", "counselling_slot", None, None, {"count": len(rows)})
        return await self.outs(rows, me=me)

    async def my_slots(self) -> list[CounsellingAppointmentOut]:
        me = await self._me_counsellor()
        if me is None:
            raise forbidden("facilities:counsel required")
        rows = (
            (
                await self.db.execute(
                    select(CounsellingAppointment)
                    .where(
                        CounsellingAppointment.counsellor_staff_id == me,
                        CounsellingAppointment.slot_at >= now_utc() - timedelta(days=30),
                    )
                    .order_by(CounsellingAppointment.slot_at)
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows, me=me)

    async def available(
        self, counsellor_id: uuid.UUID | None, f: datetime | None, t: datetime | None
    ) -> list[CounsellingAppointmentOut]:
        stmt = select(CounsellingAppointment).where(
            CounsellingAppointment.institution_id == self.inst,
            CounsellingAppointment.status == "available",
            CounsellingAppointment.slot_at >= (f or now_utc()),
        )
        if t:
            stmt = stmt.where(CounsellingAppointment.slot_at <= t)
        if counsellor_id:
            stmt = stmt.where(CounsellingAppointment.counsellor_staff_id == counsellor_id)
        rows = (await self.db.execute(stmt.order_by(CounsellingAppointment.slot_at).limit(300))).scalars().all()
        return await self.outs(rows, reveal_person=False)

    async def _slot(self, sid: uuid.UUID) -> CounsellingAppointment:
        r = (
            await self.db.execute(
                select(CounsellingAppointment)
                .where(CounsellingAppointment.id == sid, CounsellingAppointment.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Slot")
        return r

    async def book(self, sid: uuid.UUID, body: CounsellingBook) -> CounsellingAppointmentOut:
        self.require_writer()
        ptype, pid = await self.me_person()
        return await self.book_for(sid, ptype, pid, reschedule_from=body.reschedule_from)

    async def book_for(
        self, sid: uuid.UUID, ptype: str, pid: uuid.UUID, *, reschedule_from: uuid.UUID | None = None
    ) -> CounsellingAppointmentOut:
        slot = await self._slot(sid)
        if slot.status != "available" or slot.slot_at < now_utc():
            raise rule("The slot is not available", "SLOT_TAKEN")
        active = (
            (
                await self.db.execute(
                    select(CounsellingAppointment).where(
                        CounsellingAppointment.person_type == ptype,
                        CounsellingAppointment.person_id == pid,
                        CounsellingAppointment.status.in_(ACTIVE),
                        CounsellingAppointment.slot_at >= now_utc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        old = next((a for a in active if a.id == reschedule_from), None) if reschedule_from else None
        if active and old is None:
            raise rule("You already have an upcoming appointment — reschedule or cancel it first", "ALREADY_BOOKED")
        if old is not None:
            old.status, old.person_type, old.person_id = "available", None, None
        slot.status, slot.person_type, slot.person_id = "booked", ptype, pid
        await self.db.flush()
        await self._emit("counselling.slot_booked", {"slot_id": str(slot.id)}, "counselling_appointment", slot.id)
        return (await self.outs([slot]))[0]

    async def cancel(self, aid: uuid.UUID) -> CounsellingAppointmentOut:
        slot = await self._slot(aid)
        me = await self._me_counsellor()
        mine = False
        try:
            ptype, pid = await self.me_person()
            mine = (slot.person_type, slot.person_id) == (ptype, pid)
        except APIError:
            mine = False
        if not mine and me != slot.counsellor_staff_id:
            raise not_found("Appointment")
        if slot.status != "booked":
            raise rule("Only a booked appointment is cancelled", "NOT_BOOKED")
        if mine:
            slot.status, slot.person_type, slot.person_id = "available", None, None
        else:
            slot.status = "cancelled"
        await self.db.flush()
        await self._emit("counselling.cancelled", {"slot_id": str(slot.id)}, "counselling_appointment", slot.id)
        return (await self.outs([slot], me=me))[0]

    async def counsellor_action(self, aid: uuid.UUID, status: str) -> CounsellingAppointmentOut:
        me = await self._me_counsellor()
        slot = await self._slot(aid)
        if me is None or me != slot.counsellor_staff_id:
            raise not_found("Appointment")
        if slot.status != "booked":
            raise rule("Only a booked appointment is updated", "NOT_BOOKED")
        slot.status = status
        await self.db.flush()
        if status == "no_show":
            await self._emit("counselling.no_show", {"slot_id": str(slot.id)}, "counselling_appointment", slot.id)
        return (await self.outs([slot], me=me))[0]

    async def notes(self, aid: uuid.UUID, text: str) -> CounsellingAppointmentOut:
        me = await self._me_counsellor()
        slot = await self._slot(aid)
        if me is None or me != slot.counsellor_staff_id:
            raise not_found("Appointment")
        slot.notes_encrypted = text
        await self.db.flush()
        await self._audit("notes", "counselling_appointment", slot.id, None, {"length": len(text)})
        return (await self.outs([slot], me=me))[0]

    async def get(self, aid: uuid.UUID) -> CounsellingAppointmentOut:
        r = (
            await self.db.execute(
                select(CounsellingAppointment).where(
                    CounsellingAppointment.id == aid, CounsellingAppointment.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Appointment")
        me = await self._me_counsellor()
        if me == r.counsellor_staff_id:
            return (await self.outs([r], me=me))[0]
        try:
            ptype, pid = await self.me_person()
        except APIError:
            raise forbidden("Counselling appointments are confidential") from None
        if (r.person_type, r.person_id) != (ptype, pid):
            raise forbidden("Counselling appointments are confidential")
        return (await self.outs([r]))[0]

    async def mine(self) -> list[CounsellingAppointmentOut]:
        ptype, pid = await self.me_person()
        rows = (
            (
                await self.db.execute(
                    select(CounsellingAppointment)
                    .where(CounsellingAppointment.person_type == ptype, CounsellingAppointment.person_id == pid)
                    .order_by(CounsellingAppointment.slot_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows)

    async def utilisation(self) -> CounsellingUtilisation:
        if is_auditor(self.principal) or not (
            self.can("facilities", "manage") or self.can("facilities", "view_all") or self.can("health", "view_all")
        ):
            raise forbidden("Counselling counts are restricted")
        by = {
            s: int(n)
            for s, n in (
                await self.db.execute(
                    select(CounsellingAppointment.status, func.count())
                    .where(CounsellingAppointment.institution_id == self.inst)
                    .group_by(CounsellingAppointment.status)
                )
            ).all()
        }
        counsellors = (
            await self.db.execute(
                select(func.count(func.distinct(CounsellingAppointment.counsellor_staff_id))).where(
                    CounsellingAppointment.institution_id == self.inst
                )
            )
        ).scalar_one()
        return CounsellingUtilisation(
            slots=sum(by.values()),
            booked=by.get("booked", 0),
            completed=by.get("completed", 0),
            no_show=by.get("no_show", 0),
            cancelled=by.get("cancelled", 0),
            counsellors=int(counsellors),
        )

    async def no_show_mark(self) -> int:
        rows = (
            (
                await self.db.execute(
                    select(CounsellingAppointment).where(
                        CounsellingAppointment.institution_id == self.inst,
                        CounsellingAppointment.status == "booked",
                        CounsellingAppointment.slot_at < now_utc() - timedelta(hours=1),
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            if r.slot_at + timedelta(minutes=r.duration_minutes) < now_utc() - timedelta(hours=1):
                r.status = "no_show"
                await self._emit("counselling.no_show", {"slot_id": str(r.id)}, "counselling_appointment", r.id)
        await self.db.flush()
        return len(rows)
