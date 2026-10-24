"""Roll-call, visitors, complaints, discipline and registers — Prompts/20 §20.6 (``roll_call_service`` /
``visitor_service`` / ``complaint_service`` / ``discipline_service``).

* **roll-call** (``hostel.night_roll_call``; warden / ``hostel:roll_call``): one per hostel and night; entries pre-filled
  ``on_leave`` for residents on an approved / out leave covering the night, ``present`` / ``absent`` marked in bulk;
  the Beat after ``hostel.roll_call_time`` + 60 min marks the rest ``absent``; absences notify guardians + warden and
  three absences in 30 days add an automatic discipline ``warning``.
* **visitors** (``hostel.visitors``): in / out register; ID proof numbers masked in lists for everyone but the warden.
* **complaints** (``hostel.complaints``): local status machine (``COMPLAINT_FLOW``); a ``service_request_id`` is kept
  for the Phase 25 service desk; ratings are stored on the audit trail.
* **discipline** (``hostel.discipline``): records with action; ``fine`` raises an invoice (``hostel_disciplinary``);
  ``eviction`` goes through the allocation eviction flow; guardians are notified.
"""

import io
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.hostel import ACTIVE_ALLOCATION, COMPLAINT_FLOW
from app.models.hostel import (
    Hostel,
    HostelAllocation,
    HostelBed,
    HostelComplaint,
    HostelDisciplinaryRecord,
    HostelLeave,
    HostelRollCall,
    HostelRollCallEntry,
    HostelRoom,
    HostelVisitor,
)
from app.schemas.hostel import (
    DisciplineCreate,
    DisciplineOut,
    HostelComplaintCreate,
    HostelComplaintOut,
    HostelComplaintRate,
    HostelComplaintUpdate,
    HostelVisitorIn,
    HostelVisitorOut,
    RollCallCreate,
    RollCallEntriesUpdate,
    RollCallEntryOut,
    RollCallOut,
)
from app.services.hostel.common import HostelBase, now_utc, resident_predicate, rule, visible_hostel_ids


def mask(v: str | None) -> str | None:
    if not v:
        return v
    return "*" * max(len(v) - 4, 0) + v[-4:]


class HostelLifeService(HostelBase):
    # ---- roll call ---------------------------------------------------------------------------------------------------
    async def _residents(self, hostel_id: uuid.UUID) -> list[HostelAllocation]:
        return list(
            (
                await self.db.execute(
                    select(HostelAllocation).where(
                        HostelAllocation.hostel_id == hostel_id, HostelAllocation.status == "checked_in"
                    )
                )
            )
            .scalars()
            .all()
        )

    async def _on_leave(self, enrol_ids: list[uuid.UUID], night: datetime) -> set[uuid.UUID]:
        rows = (
            (
                await self.db.execute(
                    select(HostelLeave.student_program_enrollment_id).where(
                        HostelLeave.student_program_enrollment_id.in_(enrol_ids or [uuid.uuid4()]),
                        HostelLeave.status.in_(("approved", "out", "absconding")),
                        HostelLeave.from_at <= night,
                        HostelLeave.to_at >= night,
                    )
                )
            )
            .scalars()
            .all()
        )
        suspended = (
            (
                await self.db.execute(
                    select(HostelDisciplinaryRecord.student_program_enrollment_id).where(
                        HostelDisciplinaryRecord.student_program_enrollment_id.in_(enrol_ids or [uuid.uuid4()]),
                        HostelDisciplinaryRecord.action == "suspension",
                        HostelDisciplinaryRecord.incident_on >= night.date() - timedelta(days=30),
                    )
                )
            )
            .scalars()
            .all()
        )
        return set(rows) | set(suspended)

    async def roll_call_out(self, rc: HostelRollCall, *, entries: bool = True) -> RollCallOut:
        rows = (
            await self.db.execute(
                select(HostelRollCallEntry, HostelAllocation.student_program_enrollment_id, HostelRoom.room_number)
                .join(HostelAllocation, HostelAllocation.id == HostelRollCallEntry.allocation_id)
                .join(HostelBed, HostelBed.id == HostelAllocation.bed_id)
                .join(HostelRoom, HostelRoom.id == HostelBed.room_id)
                .where(HostelRollCallEntry.roll_call_id == rc.id)
                .order_by(HostelRoom.room_number)
            )
        ).all()
        refs = await self.refs([r[1] for r in rows]) if entries else {}
        counts: dict[str, int] = {}
        for e, _eid, _rn in rows:
            counts[e.status] = counts.get(e.status, 0) + 1
        return RollCallOut(
            id=rc.id,
            hostel_id=rc.hostel_id,
            on_date=rc.on_date,
            taken_at=rc.taken_at,
            counts=counts,
            entries=[
                RollCallEntryOut(
                    allocation_id=e.allocation_id,
                    student=refs.get(eid) or {"enrollment_id": eid},
                    room_number=rn,
                    status=e.status,
                )
                for e, eid, rn in rows
            ]
            if entries
            else [],  # type: ignore[misc]
        )

    async def create_roll_call(self, body: RollCallCreate) -> RollCallOut:
        await self.require_hostel(body.hostel_id, "warden", "roll_call")
        on = body.on_date or await self.today()
        dup = (
            await self.db.execute(
                select(HostelRollCall.id).where(
                    HostelRollCall.hostel_id == body.hostel_id, HostelRollCall.on_date == on
                )
            )
        ).first()
        if dup:
            raise rule("Tonight's roll-call already exists", "ALREADY_TAKEN", roll_call_id=str(dup[0]))
        rc = HostelRollCall(institution_id=self.inst, hostel_id=body.hostel_id, on_date=on, taken_by=self.actor_id)
        self.db.add(rc)
        await self.db.flush()
        await self.db.refresh(rc)
        residents = await self._residents(body.hostel_id)
        rc_time = str(await self.setting("hostel", "roll_call_time") or "21:30")
        hh, mm = (int(x) for x in rc_time.split(":")[:2])
        night = datetime.combine(on, time(hh, mm)).astimezone()
        away = await self._on_leave([a.student_program_enrollment_id for a in residents], night)
        for a in residents:
            if a.student_program_enrollment_id in away:
                self.db.add(
                    HostelRollCallEntry(
                        institution_id=self.inst, roll_call_id=rc.id, allocation_id=a.id, status="on_leave"
                    )
                )
        await self.db.flush()
        await self._emit("hostel.roll_call_taken", {"roll_call_id": str(rc.id)}, "hostel_roll_call", rc.id)
        return await self.roll_call_out(rc)

    async def _rc(self, rc_id: uuid.UUID) -> HostelRollCall:
        rc = (
            await self.db.execute(
                select(HostelRollCall).where(HostelRollCall.id == rc_id, HostelRollCall.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if rc is None or not await self.owns_hostel(rc.hostel_id):
            raise APIError(404, ErrorCode.NOT_FOUND, "Roll-call not found")
        return rc

    async def mark(self, rc_id: uuid.UUID, body: RollCallEntriesUpdate) -> RollCallOut:
        rc = await self._rc(rc_id)
        await self.require_hostel(rc.hostel_id, "warden", "roll_call")
        valid = {a.id for a in await self._residents(rc.hostel_id)}
        existing = {
            e.allocation_id: e
            for e in (
                await self.db.execute(select(HostelRollCallEntry).where(HostelRollCallEntry.roll_call_id == rc.id))
            )
            .scalars()
            .all()
        }
        absent: list[uuid.UUID] = []
        for m in body.entries:
            if m.allocation_id not in valid:
                continue
            e = existing.get(m.allocation_id)
            if e is None:
                self.db.add(
                    HostelRollCallEntry(
                        institution_id=self.inst, roll_call_id=rc.id, allocation_id=m.allocation_id, status=m.status
                    )
                )
            else:
                e.status = m.status
            if m.status == "absent":
                absent.append(m.allocation_id)
        await self.db.flush()
        await self._absent_alerts(rc, absent)
        return await self.roll_call_out(rc)

    async def _absent_alerts(self, rc: HostelRollCall, allocation_ids: list[uuid.UUID]) -> None:
        if not allocation_ids:
            return
        h = (await self.db.execute(select(Hostel).where(Hostel.id == rc.hostel_id))).scalar_one()
        warden = await self.warden_user(h)
        for a in (
            (await self.db.execute(select(HostelAllocation).where(HostelAllocation.id.in_(allocation_ids))))
            .scalars()
            .all()
        ):
            student = await self.ref(a.student_program_enrollment_id)
            await self._emit(
                "hostel.roll_call_absent",
                {"allocation_id": str(a.id), "on_date": rc.on_date.isoformat()},
                "hostel_roll_call",
                rc.id,
            )
            await self._notify(
                "hostel.roll_call_absent",
                [warden, *await self.guardian_users(a.student_program_enrollment_id)],
                {"student": student.name or "", "date": rc.on_date.isoformat()},
            )
            count = (
                await self.db.execute(
                    select(func.count())
                    .select_from(HostelRollCallEntry)
                    .join(HostelRollCall, HostelRollCall.id == HostelRollCallEntry.roll_call_id)
                    .join(HostelAllocation, HostelAllocation.id == HostelRollCallEntry.allocation_id)
                    .where(
                        HostelAllocation.student_program_enrollment_id == a.student_program_enrollment_id,
                        HostelRollCallEntry.status == "absent",
                        HostelRollCall.on_date >= rc.on_date - timedelta(days=30),
                    )
                )
            ).scalar_one()
            if count == 3:
                self.db.add(
                    HostelDisciplinaryRecord(
                        institution_id=self.inst,
                        student_program_enrollment_id=a.student_program_enrollment_id,
                        hostel_id=a.hostel_id,
                        incident_on=rc.on_date,
                        description="Absent at night roll-call three times in 30 days (automatic)",
                        action="warning",
                    )
                )
        await self.db.flush()

    async def autoclose(self) -> int:
        """Beat: fill unmarked residents as absent once roll-call time + 60 min passed (tonight's roll-calls)."""
        today = await self.today()
        rc_time = str(await self.setting("hostel", "roll_call_time") or "21:30")
        hh, mm = (int(x) for x in rc_time.split(":")[:2])
        cutoff = datetime.combine(today, time(hh, mm)).astimezone() + timedelta(minutes=60)
        if now_utc() < cutoff:
            return 0
        n = 0
        for rc in (
            (
                await self.db.execute(
                    select(HostelRollCall).where(
                        HostelRollCall.institution_id == self.inst, HostelRollCall.on_date == today
                    )
                )
            )
            .scalars()
            .all()
        ):
            marked = set(
                (
                    await self.db.execute(
                        select(HostelRollCallEntry.allocation_id).where(HostelRollCallEntry.roll_call_id == rc.id)
                    )
                )
                .scalars()
                .all()
            )
            missing = [a.id for a in await self._residents(rc.hostel_id) if a.id not in marked]
            for aid in missing:
                self.db.add(
                    HostelRollCallEntry(
                        institution_id=self.inst, roll_call_id=rc.id, allocation_id=aid, status="absent"
                    )
                )
            await self.db.flush()
            await self._absent_alerts(rc, missing)
            n += len(missing)
        return n

    async def roll_calls(self, hostel_id: uuid.UUID | None, on: date | None) -> list[RollCallOut]:
        q = select(HostelRollCall).where(
            HostelRollCall.institution_id == self.inst, HostelRollCall.hostel_id.in_(visible_hostel_ids(self.principal))
        )
        if hostel_id:
            q = q.where(HostelRollCall.hostel_id == hostel_id)
        if on:
            q = q.where(HostelRollCall.on_date == on)
        rows = (await self.db.execute(q.order_by(HostelRollCall.on_date.desc()).limit(200))).scalars().all()
        return [await self.roll_call_out(r, entries=bool(on)) for r in rows]

    async def roll_call_report(self, hostel_id: uuid.UUID, start: date, end: date) -> list[dict[str, Any]]:
        await self.hostel(hostel_id)
        rows = (
            await self.db.execute(
                select(HostelRollCall.on_date, HostelRollCallEntry.status, func.count())
                .join(HostelRollCallEntry, HostelRollCallEntry.roll_call_id == HostelRollCall.id)
                .where(HostelRollCall.hostel_id == hostel_id, HostelRollCall.on_date.between(start, end))
                .group_by(HostelRollCall.on_date, HostelRollCallEntry.status)
                .order_by(HostelRollCall.on_date)
            )
        ).all()
        out: dict[date, dict[str, Any]] = {}
        for d, status, n in rows:
            out.setdefault(d, {"date": d.isoformat(), "present": 0, "absent": 0, "on_leave": 0})[status] = int(n)
        return list(out.values())

    # ---- visitors -----------------------------------------------------------------------------------------------------
    async def visitor_outs(self, rows: list[HostelVisitor], *, unmask: bool = False) -> list[HostelVisitorOut]:
        refs = await self.refs([r.student_program_enrollment_id for r in rows])
        return [
            HostelVisitorOut(
                id=r.id,
                hostel_id=r.hostel_id,
                student=refs.get(r.student_program_enrollment_id),
                visitor_name=r.visitor_name,
                relation=r.relation,
                phone=r.phone if unmask else mask(r.phone),
                id_proof_type=r.id_proof_type,
                id_proof_no=r.id_proof_no if unmask else mask(r.id_proof_no),
                in_at=r.in_at,
                out_at=r.out_at,
            )
            for r in rows
        ]

    async def log_visitor(self, body: HostelVisitorIn) -> HostelVisitorOut:
        alloc = (
            await self.db.execute(
                select(HostelAllocation).where(
                    HostelAllocation.student_program_enrollment_id == body.enrollment_id,
                    HostelAllocation.status == "checked_in",
                )
            )
        ).scalar_one_or_none()
        if alloc is None:
            raise rule("The student is not a resident", "NOT_RESIDENT")
        await self.require_hostel(alloc.hostel_id, "gate", "warden")
        h = (await self.db.execute(select(Hostel).where(Hostel.id == alloc.hostel_id))).scalar_one()
        if (
            h.hostel_type == "girls"
            and await self.setting("hostel", "girls_guardian_visitors_only")
            and (body.relation or "").lower() not in ("father", "mother", "guardian", "sibling")
        ):
            raise rule("Only registered guardians may visit this hostel", "GUARDIANS_ONLY")
        v = HostelVisitor(
            institution_id=self.inst,
            hostel_id=alloc.hostel_id,
            approved_by=self.actor_id,
            **body.model_dump(exclude={"enrollment_id"}),
            student_program_enrollment_id=body.enrollment_id,
        )
        self.db.add(v)
        await self.db.flush()
        await self.db.refresh(v)
        await self._emit("hostel.visitor_logged", {"visitor_id": str(v.id)}, "hostel_visitor", v.id)
        await self._notify(
            "hostel.visitor_logged", [await self.student_user(body.enrollment_id)], {"visitor": body.visitor_name}
        )
        return (await self.visitor_outs([v], unmask=True))[0]

    async def visitor_out(self, visitor_id: uuid.UUID) -> HostelVisitorOut:
        v = (
            await self.db.execute(
                select(HostelVisitor)
                .where(HostelVisitor.id == visitor_id, HostelVisitor.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if v is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Visitor not found")
        await self.require_hostel(v.hostel_id, "gate", "warden")
        if v.out_at is None:
            v.out_at = now_utc()
        await self.db.flush()
        return (await self.visitor_outs([v], unmask=True))[0]

    async def visitors(self, hostel_id: uuid.UUID | None, month: date | None) -> list[HostelVisitorOut]:
        q = select(HostelVisitor).where(
            HostelVisitor.institution_id == self.inst,
            resident_predicate(self.principal, HostelVisitor.student_program_enrollment_id, HostelVisitor.hostel_id),
        )
        if hostel_id:
            q = q.where(HostelVisitor.hostel_id == hostel_id)
        if month:
            start = month.replace(day=1)
            nxt = (start + timedelta(days=32)).replace(day=1)
            q = q.where(
                HostelVisitor.in_at >= datetime.combine(start, time()).astimezone(),
                HostelVisitor.in_at < datetime.combine(nxt, time()).astimezone(),
            )
        rows = list((await self.db.execute(q.order_by(HostelVisitor.in_at.desc()).limit(3000))).scalars().all())
        return await self.visitor_outs(rows, unmask=self.can("hostel", "warden") and not self.can("hostel", "view_all"))

    # ---- complaints ---------------------------------------------------------------------------------------------------
    async def complaint_outs(self, rows: list[HostelComplaint]) -> list[HostelComplaintOut]:
        refs = await self.refs([r.student_program_enrollment_id for r in rows if r.student_program_enrollment_id])
        rooms: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(HostelRoom.id, HostelRoom.room_number).where(
                        HostelRoom.id.in_({r.room_id for r in rows if r.room_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )  # type: ignore[arg-type]
        return [
            HostelComplaintOut(
                id=r.id,
                hostel_id=r.hostel_id,
                room_id=r.room_id,
                room_number=rooms.get(r.room_id),
                student=refs.get(r.student_program_enrollment_id) if r.student_program_enrollment_id else None,
                category=r.category,
                description=r.description,
                status=r.status,
                service_request_id=r.service_request_id,
                created_at=r.created_at,
                resolved_at=r.resolved_at,
            )
            for r in rows
        ]

    async def create_complaint(self, body: HostelComplaintCreate) -> HostelComplaintOut:
        e = await self.my_enrolment()
        alloc = (
            await self.db.execute(
                select(HostelAllocation).where(
                    HostelAllocation.student_program_enrollment_id == e.id, HostelAllocation.status == "checked_in"
                )
            )
        ).scalar_one_or_none()
        if alloc is None:
            raise rule("Only residents can raise hostel complaints", "NOT_RESIDENT")
        room_id = (
            body.room_id
            or (await self.db.execute(select(HostelBed.room_id).where(HostelBed.id == alloc.bed_id))).scalar_one()
        )
        c = HostelComplaint(
            institution_id=self.inst,
            hostel_id=alloc.hostel_id,
            room_id=room_id,
            student_program_enrollment_id=e.id,
            category=body.category,
            description=body.description,
            status="open",
        )
        self.db.add(c)
        await self.db.flush()
        await self.db.refresh(c)
        await self._emit(
            "hostel.complaint_created", {"complaint_id": str(c.id), "category": c.category}, "hostel_complaint", c.id
        )
        return (await self.complaint_outs([c]))[0]

    async def complaints(self, hostel_id: uuid.UUID | None, status: str | None) -> list[HostelComplaintOut]:
        q = select(HostelComplaint).where(HostelComplaint.institution_id == self.inst)
        if self.can("hostel", "warden") or self.can("hostel", "view_all"):
            q = q.where(
                HostelComplaint.hostel_id.in_(visible_hostel_ids(self.principal))
                | HostelComplaint.student_program_enrollment_id.in_(await self.mine() or [uuid.uuid4()])
            )
        else:
            q = q.where(HostelComplaint.student_program_enrollment_id.in_(await self.mine() or [uuid.uuid4()]))
        if hostel_id:
            q = q.where(HostelComplaint.hostel_id == hostel_id)
        if status:
            q = q.where(HostelComplaint.status == status)
        rows = list((await self.db.execute(q.order_by(HostelComplaint.created_at.desc()).limit(2000))).scalars().all())
        return await self.complaint_outs(rows)

    async def update_complaint(self, cid: uuid.UUID, body: HostelComplaintUpdate) -> HostelComplaintOut:
        c = (
            await self.db.execute(
                select(HostelComplaint)
                .where(HostelComplaint.id == cid, HostelComplaint.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if c is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Complaint not found")
        await self.require_hostel(c.hostel_id, "warden")
        if body.status not in COMPLAINT_FLOW.get(c.status, ()):
            raise rule(f"Cannot move a {c.status} complaint to {body.status}", "INVALID_TRANSITION")
        old = c.status
        c.status = body.status
        if body.status == "resolved":
            c.resolved_at = now_utc()
        await self.db.flush()
        await self.db.refresh(c)
        await self._audit(
            "complaint_update", "hostel_complaint", c.id, {"status": old}, {"status": c.status, "remarks": body.remarks}
        )
        await self._emit(
            "hostel.complaint_updated", {"complaint_id": str(c.id), "status": c.status}, "hostel_complaint", c.id
        )
        if c.student_program_enrollment_id:
            await self._notify(
                "hostel.complaint_updated",
                [await self.student_user(c.student_program_enrollment_id)],
                {"status": c.status, "category": c.category},
            )
        return (await self.complaint_outs([c]))[0]

    async def rate_complaint(self, cid: uuid.UUID, body: HostelComplaintRate) -> HostelComplaintOut:
        c = (
            await self.db.execute(
                select(HostelComplaint).where(
                    HostelComplaint.id == cid,
                    HostelComplaint.student_program_enrollment_id.in_(await self.mine() or [uuid.uuid4()]),
                )
            )
        ).scalar_one_or_none()
        if c is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Complaint not found")
        if c.status not in ("resolved", "closed"):
            raise rule("Rate a complaint once it is resolved", "NOT_RESOLVED")
        await self._audit("complaint_rate", "hostel_complaint", c.id, None, body.model_dump())
        return (await self.complaint_outs([c]))[0]

    # ---- discipline ---------------------------------------------------------------------------------------------------
    async def discipline_outs(self, rows: list[HostelDisciplinaryRecord]) -> list[DisciplineOut]:
        refs = await self.refs([r.student_program_enrollment_id for r in rows])
        return [
            DisciplineOut(
                id=r.id,
                student=refs.get(r.student_program_enrollment_id) or {"enrollment_id": r.student_program_enrollment_id},  # type: ignore[arg-type]
                hostel_id=r.hostel_id,
                incident_on=r.incident_on,
                description=r.description,
                action=r.action,
                fine_paise=r.fine_paise,
                fee_invoice_id=r.fee_invoice_id,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def record(self, body: DisciplineCreate) -> DisciplineOut:
        alloc = (
            await self.db.execute(
                select(HostelAllocation)
                .where(HostelAllocation.student_program_enrollment_id == body.enrollment_id)
                .order_by(HostelAllocation.status.in_(ACTIVE_ALLOCATION).desc(), HostelAllocation.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if alloc is None:
            raise rule("The student has no hostel allocation", "NOT_RESIDENT")
        await self.require_hostel(alloc.hostel_id, "discipline", "warden")
        if body.action == "fine" and not body.fine_paise:
            raise APIError(422, ErrorCode.VALIDATION, "fine_paise is required for a fine", {"field": "fine_paise"})
        rec = HostelDisciplinaryRecord(
            institution_id=self.inst,
            student_program_enrollment_id=body.enrollment_id,
            hostel_id=alloc.hostel_id,
            incident_on=body.incident_on,
            description=body.description,
            action=body.action,
            fine_paise=body.fine_paise,
            decided_by=self.actor_id,
        )
        self.db.add(rec)
        await self.db.flush()
        if body.action == "fine" and body.fine_paise:
            rec.fee_invoice_id = await self.invoice(
                body.enrollment_id,
                "hostel_disciplinary",
                rec.id,
                [("Hostel disciplinary fine", body.fine_paise, "FINE")],
                "Hostel fine",
            )
        if body.action == "eviction" and alloc.status in ACTIVE_ALLOCATION:
            from app.schemas.hostel import EvictRequest
            from app.services.hostel.allocation_service import AllocationService

            await AllocationService(self.db, self.principal, self.request, self.inst).evict(
                alloc.id, EvictRequest(reason=body.description[:1000], disciplinary_record_id=rec.id)
            )
        await self.db.flush()
        await self.db.refresh(rec)
        await self._emit(
            "hostel.discipline_recorded",
            {"record_id": str(rec.id), "action": rec.action},
            "hostel_disciplinary_record",
            rec.id,
        )
        await self._notify(
            "hostel.discipline_recorded",
            await self.guardian_users(body.enrollment_id) + [await self.student_user(body.enrollment_id)],
            {"action": rec.action, "reason": rec.description[:120]},
        )
        return (await self.discipline_outs([rec]))[0]

    async def discipline(self, *, mine: bool = False, wards: bool = False) -> list[DisciplineOut]:
        q = select(HostelDisciplinaryRecord).where(HostelDisciplinaryRecord.institution_id == self.inst)
        if mine or wards:
            q = q.where(
                HostelDisciplinaryRecord.student_program_enrollment_id.in_(
                    await self.mine(wards=wards) or [uuid.uuid4()]
                )
            )
        else:
            q = q.where(
                resident_predicate(
                    self.principal,
                    HostelDisciplinaryRecord.student_program_enrollment_id,
                    HostelDisciplinaryRecord.hostel_id,
                )
            )
        rows = list(
            (await self.db.execute(q.order_by(HostelDisciplinaryRecord.incident_on.desc()).limit(2000))).scalars().all()
        )
        return await self.discipline_outs(rows)

    # ---- registers ------------------------------------------------------------------------------------------------------
    async def report_xlsx(self, kind: str, hostel_id: uuid.UUID | None = None) -> dict[str, Any]:
        from openpyxl import Workbook

        from app.core.files import build_key, storage

        head: list[str]
        rows: list[list[Any]]
        if kind == "occupancy":
            from app.services.hostel.structure_service import StructureService

            hs = await StructureService(self.db, self.principal, self.request, self.inst).list_hostels()
            head, rows = (
                ["Hostel", "Type", "Capacity", "Occupied", "Allotted", "Vacant"],
                [[h.name, h.hostel_type, h.capacity, h.occupied, h.allotted, h.vacant] for h in hs],
            )
        elif kind == "visitors":
            vs = await self.visitors(hostel_id, None)
            head, rows = (
                ["Visitor", "Relation", "Student", "In", "Out"],
                [[v.visitor_name, v.relation, v.student.name if v.student else None, v.in_at, v.out_at] for v in vs],
            )
        elif kind == "discipline":
            ds = await self.discipline()
            head, rows = (
                ["Date", "Student", "Action", "Fine", "Description"],
                [[d.incident_on, d.student.name, d.action, d.fine_paise, d.description] for d in ds],
            )
        elif kind == "leaves":
            from app.services.hostel.leave_service import LeaveService

            ls = await LeaveService(self.db, self.principal, self.request, self.inst).list_leaves(hostel_id, None, None)
            head, rows = (
                ["Student", "Type", "From", "To", "Consent", "Status", "Late (min)"],
                [
                    [x.student.name, x.leave_type, x.from_at, x.to_at, x.guardian_consent, x.status, x.late_minutes]
                    for x in ls
                ],
            )
        elif kind == "roll_call":
            today = await self.today()
            if hostel_id is None:
                raise APIError(422, ErrorCode.VALIDATION, "hostel_id is required for the roll-call register")
            rr = await self.roll_call_report(hostel_id, today - timedelta(days=30), today)
            head, rows = (
                ["Date", "Present", "Absent", "On leave"],
                [[r["date"], r["present"], r["absent"], r["on_leave"]] for r in rr],
            )
        elif kind in ("fees", "mess"):
            from app.services.hostel.mess_service import MessService

            bills = await MessService(self.db, self.principal, self.request, self.inst).bills(None, hostel_id)
            head, rows = (
                ["Student", "Plan", "Month", "Days", "Rebate", "Amount", "Invoice"],
                [
                    [
                        b.student.name if b.student else None,
                        b.plan,
                        b.month,
                        b.days_billed,
                        b.rebate_days,
                        b.amount_paise,
                        b.invoice_status,
                    ]
                    for b in bills
                ],
            )
        else:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown report")
        wb = Workbook()
        ws = wb.active
        ws.title = kind[:30]
        ws.append(head)
        for r in rows:
            ws.append([v.isoformat() if hasattr(v, "isoformat") else v for v in r])
        buf = io.BytesIO()
        wb.save(buf)
        key = build_key(self.inst, "hostel-reports", f"{kind}-{uuid.uuid4().hex[:8]}.xlsx")
        await storage.put(key, buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        return {"result_url": key, "rows": len(rows), "report": kind}
