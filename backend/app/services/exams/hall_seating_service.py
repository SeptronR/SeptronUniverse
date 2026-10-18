"""Hall tickets and seating — Prompts/14 §14.6 ``hall_ticket_service`` + ``seating_service``.

Hall tickets: every ``confirmed`` registration whose live items are all ``eligible`` / ``condoned`` gets a number
(``hall_ticket_no`` sequence, fallback ``HT{yy}{nnnnnn}``), a random QR token (``hall_ticket_qr_token``; the public
``/hall-tickets/verify/{token}`` answers masked identity + papers, ``valid=false`` once the token is revoked by a
cancel / debar) and a PDF (stored; venue filled after seating). Students download only after
``hall_ticket_release_at`` (403 ``NOT_RELEASED``); with ``exams.hall_ticket_requires_no_dues`` open fee dues skip the
student (``NO_DUES_PENDING``).

Seating: candidates = confirmed registrations' items with ``eligible|condoned`` eligibility for papers on the date /
slot, ordered by hall-ticket number; ``mixed_course`` interleaves papers round-robin so neighbours differ,
``by_course`` fills contiguously; capacity = ``rooms.exam_capacity`` (or ``capacity``); fewer seats than candidates
→ 409 ``SEATING_SHORTFALL``; plans locked ``FOR UPDATE`` and rebuilt while ``draft``; publish makes seats visible and
re-renders hall tickets with the venue.
"""

import secrets
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.exams import SEATABLE
from app.models.curriculum import Course
from app.models.exams import (
    ExamPaper,
    ExamRegistration,
    ExamRegistrationItem,
    ExamSeatAllocation,
    ExamSeatingPlan,
    ExamSession,
)
from app.models.fees import FeeInvoice
from app.models.students import Student, StudentProgramEnrollment
from app.models.timetable import Room
from app.schemas.exams import (
    HallTicketGenerateRequest,
    HallTicketVerifyResponse,
    SeatAllocationRow,
    SeatingGenerateRequest,
    SeatingSummary,
    SeatMove,
)
from app.services.exams.common import ExamBase, mask, now_utc, rule, student_name


class HallTicketService(ExamBase):
    async def _seats(self, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        rows = (
            await self.db.execute(
                select(ExamSeatAllocation.exam_registration_item_id, Room.code, ExamSeatAllocation.seat_number)
                .join(ExamSeatingPlan, ExamSeatingPlan.id == ExamSeatAllocation.seating_plan_id)
                .join(Room, Room.id == ExamSeatingPlan.room_id)
                .where(
                    ExamSeatAllocation.exam_registration_item_id.in_(item_ids or [uuid.uuid4()]),
                    ExamSeatingPlan.status == "published",
                )
            )
        ).all()
        return {i: f"{r} / {s}" for i, r, s in rows}

    async def render(self, reg: ExamRegistration, s: ExamSession) -> bytes:
        from app.utils.pdf import render_pdf

        st = (
            await self.db.execute(
                select(Student)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.id == reg.student_program_enrollment_id)
            )
        ).scalar_one()
        items = (
            await self.db.execute(
                select(ExamRegistrationItem, ExamPaper, Course)
                .join(ExamPaper, ExamPaper.id == ExamRegistrationItem.exam_paper_id)
                .join(Course, Course.id == ExamRegistrationItem.course_id)
                .where(ExamRegistrationItem.exam_registration_id == reg.id, ExamRegistrationItem.status != "cancelled")
                .order_by(ExamPaper.exam_date.nulls_last(), ExamPaper.session_slot)
            )
        ).all()
        seats = await self._seats([it.id for it, _, _ in items])
        inst = await self.institution()
        lines = [
            inst.name,
            f"HALL TICKET / प्रवेश पत्र — {s.name}",
            f"Hall ticket: {reg.hall_ticket_number}",
            f"Name: {student_name(st)}   Reg. no.: {st.registration_number}",
            f"Verify: /hall-tickets/verify/{reg.hall_ticket_qr_token}",
            "",
        ]
        for it, p, c in items:
            when = f"{p.exam_date.isoformat() if p.exam_date else 'TBA'} {p.session_slot or ''} {p.start_time.strftime('%H:%M') if p.start_time else ''}"
            lines.append(f"{when:22s} {c.code:10s} {c.title[:34]:34s} {seats.get(it.id, 'venue: to be announced')}")
        lines += ["", "Carry this hall ticket and a photo ID. Electronic devices are prohibited."]
        html = (
            "<html><body>"
            + (f"<img src='{st.photo_url}' height='90'/>" if st.photo_url else "")
            + "".join(f"<p>{x}</p>" for x in lines)
            + "</body></html>"
        )
        return render_pdf(html, lines, title=f"Hall ticket {reg.hall_ticket_number}")

    async def _number(self, s: ExamSession, college_id: uuid.UUID) -> str:
        from app.services.sequence_service import SequenceService

        try:
            return (
                await SequenceService(self.db, self.principal, self.request, self.inst).next(
                    "hall_ticket_no", college_id, {"term": ""}
                )
            ).rendered[:30]
        except APIError:
            n = (
                await self.db.execute(
                    select(func.count())
                    .select_from(ExamRegistration)
                    .where(ExamRegistration.exam_session_id == s.id, ExamRegistration.hall_ticket_number.is_not(None))
                )
            ).scalar_one()
            return f"HT{now_utc():%y}{int(n) + 1:06d}"

    async def generate(self, sid: uuid.UUID, body: HallTicketGenerateRequest, progress: Any = None) -> dict[str, Any]:
        from app.core.files import build_key, storage

        s = await self.session(sid, write=True)
        q = (
            select(ExamRegistration)
            .where(ExamRegistration.exam_session_id == s.id, ExamRegistration.status == "confirmed")
            .with_for_update()
        )
        if body.college_id:
            q = q.where(ExamRegistration.college_id == body.college_id)
        if body.program_id:
            q = q.where(
                ExamRegistration.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.program_id == body.program_id)
                )
            )
        if body.only_missing:
            q = q.where(ExamRegistration.hall_ticket_number.is_(None))
        regs = (await self.db.execute(q)).scalars().all()
        needs_no_dues = bool(await self.setting("exams", "hall_ticket_requires_no_dues"))
        out: dict[str, Any] = {"issued": 0, "skipped": []}
        for n, reg in enumerate(regs):
            items = (
                (
                    await self.db.execute(
                        select(ExamRegistrationItem).where(
                            ExamRegistrationItem.exam_registration_id == reg.id,
                            ExamRegistrationItem.status != "cancelled",
                        )
                    )
                )
                .scalars()
                .all()
            )
            bad = [i for i in items if i.eligibility not in SEATABLE]
            if not items or len(bad) == len(items):
                out["skipped"].append({"exam_registration_id": str(reg.id), "reason": "NOT_ELIGIBLE"})
                continue
            if needs_no_dues:
                dues = (
                    await self.db.execute(
                        select(func.coalesce(func.sum(FeeInvoice.balance_paise), 0)).where(
                            FeeInvoice.student_program_enrollment_id == reg.student_program_enrollment_id,
                            FeeInvoice.status.in_(("pending", "partial", "overdue")),
                        )
                    )
                ).scalar_one()
                if dues > 0:
                    out["skipped"].append({"exam_registration_id": str(reg.id), "reason": "NO_DUES_PENDING"})
                    continue
            if not reg.hall_ticket_number:
                reg.hall_ticket_number = await self._number(s, reg.college_id)
            reg.hall_ticket_qr_token = reg.hall_ticket_qr_token or secrets.token_urlsafe(24)
            reg.hall_ticket_issued_at = now_utc()
            await self.db.flush()
            pdf = await self.render(reg, s)
            key = build_key(self.inst, "exams/hall-tickets", f"{reg.hall_ticket_number}.pdf")
            await storage.put(key, pdf, "application/pdf")
            reg.hall_ticket_pdf_url = key
            out["issued"] += 1
            if progress and n % 50 == 0:
                await progress(int(n * 100 / max(1, len(regs))), f"{n}/{len(regs)}")
        await self.db.flush()
        await self._audit(
            "hall_tickets", "exam_session", s.id, None, {"issued": out["issued"], "skipped": len(out["skipped"])}
        )
        await self._emit(
            "exams.hall_ticket_ready", {"exam_session_id": str(s.id), "issued": out["issued"]}, "exam_session", s.id
        )
        return out

    async def pdf_for(self, reg: ExamRegistration, *, self_view: bool) -> tuple[bytes, str]:
        s = await self.session(reg.exam_session_id)
        if not reg.hall_ticket_number or reg.status != "confirmed":
            raise rule("No hall ticket issued", "NOT_ISSUED", 404)
        if self_view and s.hall_ticket_release_at and now_utc() < s.hall_ticket_release_at:
            raise APIError(
                403,
                ErrorCode.RULE_VIOLATION,
                "Hall tickets are released at " + s.hall_ticket_release_at.isoformat(),
                {"code": "NOT_RELEASED"},
            )
        return await self.render(reg, s), reg.hall_ticket_number

    async def verify(self, token: str) -> HallTicketVerifyResponse:
        reg = (
            await self.db.execute(select(ExamRegistration).where(ExamRegistration.hall_ticket_qr_token == token))
        ).scalar_one_or_none()
        if reg is None:
            return HallTicketVerifyResponse(valid=False, reason="unknown or revoked")
        s = (await self.db.execute(select(ExamSession).where(ExamSession.id == reg.exam_session_id))).scalar_one()
        st = (
            await self.db.execute(
                select(Student)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.id == reg.student_program_enrollment_id)
            )
        ).scalar_one()
        papers = [
            {"course": c.code, "date": p.exam_date.isoformat() if p.exam_date else None, "slot": p.session_slot}
            for p, c in (
                await self.db.execute(
                    select(ExamPaper, Course)
                    .join(ExamRegistrationItem, ExamRegistrationItem.exam_paper_id == ExamPaper.id)
                    .join(Course, Course.id == ExamPaper.course_id)
                    .where(
                        ExamRegistrationItem.exam_registration_id == reg.id, ExamRegistrationItem.status != "cancelled"
                    )
                )
            ).all()
        ]
        valid = reg.status == "confirmed"
        return HallTicketVerifyResponse(
            valid=valid,
            student_masked=mask(student_name(st)),
            hall_ticket_number=reg.hall_ticket_number,
            session=s.name,
            papers=papers,
            issued_at=reg.hall_ticket_issued_at,
            reason=None if valid else reg.status,
        )


class SeatingService(ExamBase):
    async def _candidates(
        self, s: ExamSession, body: SeatingGenerateRequest
    ) -> list[tuple[ExamRegistrationItem, ExamPaper, str]]:
        rows = (
            await self.db.execute(
                select(ExamRegistrationItem, ExamPaper, ExamRegistration.hall_ticket_number)
                .join(ExamPaper, ExamPaper.id == ExamRegistrationItem.exam_paper_id)
                .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
                .where(
                    ExamPaper.exam_session_id == s.id,
                    ExamPaper.exam_date == body.exam_date,
                    ExamPaper.session_slot == body.session_slot,
                    ExamRegistration.status == "confirmed",
                    ExamRegistrationItem.status == "registered",
                    ExamRegistrationItem.eligibility.in_(tuple(SEATABLE)),
                )
            )
        ).all()
        return sorted([(it, p, ht or "") for it, p, ht in rows], key=lambda x: (x[2], str(x[0].id)))

    async def generate(self, sid: uuid.UUID, body: SeatingGenerateRequest) -> SeatingSummary:
        s = await self.session(sid, write=True)
        rooms = (
            (await self.db.execute(select(Room).where(Room.id.in_(body.room_ids), Room.institution_id == self.inst)))
            .scalars()
            .all()
        )
        order = {rid: i for i, rid in enumerate(body.room_ids)}
        rooms = sorted(rooms, key=lambda r: order.get(r.id, 99))
        cands = await self._candidates(s, body)
        caps = [(r, int(getattr(r, "exam_capacity", None) or r.capacity or 0)) for r in rooms]
        seats = sum(c for _, c in caps)
        out = SeatingSummary(candidates=len(cands), seats=seats, dry_run=body.dry_run)
        if seats < len(cands):
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"{len(cands)} candidates but only {seats} seats",
                {"code": "SEATING_SHORTFALL", "shortfall": len(cands) - seats},
            )
        if body.strategy == "mixed_course":
            by_paper: dict[uuid.UUID, list[Any]] = defaultdict(list)
            for c in cands:
                by_paper[c[1].id].append(c)
            queues = sorted(by_paper.values(), key=len, reverse=True)
            ordered: list[Any] = []
            while any(queues):
                for q in queues:
                    if q:
                        ordered.append(q.pop(0))
            cands = ordered
        if body.dry_run:
            return out
        idx = 0
        for room, cap in caps:
            plan = (
                await self.db.execute(
                    select(ExamSeatingPlan)
                    .where(
                        ExamSeatingPlan.exam_session_id == s.id,
                        ExamSeatingPlan.exam_date == body.exam_date,
                        ExamSeatingPlan.session_slot == body.session_slot,
                        ExamSeatingPlan.room_id == room.id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if plan is not None and plan.status == "published":
                raise APIError(409, ErrorCode.RECORD_LOCKED, f"Room {room.code} is already published for this slot")
            if plan is None:
                plan = ExamSeatingPlan(
                    institution_id=self.inst,
                    exam_session_id=s.id,
                    exam_date=body.exam_date,
                    session_slot=body.session_slot,
                    room_id=room.id,
                    status="draft",
                )
                self.db.add(plan)
                await self.db.flush()
            for old in (
                await self.db.execute(select(ExamSeatAllocation).where(ExamSeatAllocation.seating_plan_id == plan.id))
            ).scalars():
                await self.db.delete(old)
            await self.db.flush()
            chunk = cands[idx : idx + cap]
            idx += len(chunk)
            prev_paper = None
            for k, (it, p, _) in enumerate(chunk):
                row_no, col_no = k // body.seats_per_row + 1, k % body.seats_per_row + 1
                # remove any earlier allocation of the item in another room of the slot
                for a in (
                    await self.db.execute(
                        select(ExamSeatAllocation).where(ExamSeatAllocation.exam_registration_item_id == it.id)
                    )
                ).scalars():
                    await self.db.delete(a)
                self.db.add(
                    ExamSeatAllocation(
                        institution_id=self.inst,
                        seating_plan_id=plan.id,
                        exam_registration_item_id=it.id,
                        seat_number=f"{chr(64 + min(row_no, 26))}{col_no}",
                        row_no=row_no,
                        col_no=col_no,
                    )
                )
                if prev_paper == p.id and col_no > 1:
                    out.adjacency_same_paper += 1
                prev_paper = p.id
            plan.capacity_used = len(chunk)
            plan.layout = {"seats_per_row": body.seats_per_row, "strategy": body.strategy}
            out.rooms.append({"room": room.code, "used": len(chunk), "capacity": cap})
            out.allocated += len(chunk)
            await self.db.flush()
            if idx >= len(cands):
                break
        await self._audit("seating", "exam_session", s.id, None, out.model_dump(mode="json"))
        return out

    async def rows(
        self, sid: uuid.UUID, exam_date: Any, slot: str | None, plan_id: uuid.UUID | None = None
    ) -> list[SeatAllocationRow]:
        s = await self.session(sid)
        q = (
            select(
                ExamSeatAllocation, ExamSeatingPlan, Room, ExamRegistrationItem, ExamRegistration, ExamPaper, Student
            )
            .join(ExamSeatingPlan, ExamSeatingPlan.id == ExamSeatAllocation.seating_plan_id)
            .join(Room, Room.id == ExamSeatingPlan.room_id)
            .join(ExamRegistrationItem, ExamRegistrationItem.id == ExamSeatAllocation.exam_registration_item_id)
            .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
            .join(ExamPaper, ExamPaper.id == ExamRegistrationItem.exam_paper_id)
            .join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == ExamRegistration.student_program_enrollment_id
            )
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(ExamSeatingPlan.exam_session_id == s.id)
        )
        if exam_date:
            q = q.where(ExamSeatingPlan.exam_date == exam_date)
        if slot:
            q = q.where(ExamSeatingPlan.session_slot == slot)
        if plan_id:
            q = q.where(ExamSeatingPlan.id == plan_id)
        return [
            SeatAllocationRow(
                id=a.id,
                seating_plan_id=plan.id,
                room_code=room.code,
                seat_number=a.seat_number,
                row_no=a.row_no,
                col_no=a.col_no,
                exam_registration_item_id=it.id,
                hall_ticket_number=reg.hall_ticket_number,
                registration_number=st.registration_number,
                paper_code=p.paper_code,
                status=plan.status,
            )
            for a, plan, room, it, reg, p, st in (
                await self.db.execute(q.order_by(Room.code, ExamSeatAllocation.row_no, ExamSeatAllocation.col_no))
            ).all()
        ]

    async def move(self, aid: uuid.UUID, body: SeatMove) -> SeatAllocationRow:
        a = (
            await self.db.execute(
                select(ExamSeatAllocation)
                .where(ExamSeatAllocation.id == aid, ExamSeatAllocation.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Seat allocation not found")
        old = {"plan": str(a.seating_plan_id), "seat": a.seat_number}
        target = body.seating_plan_id or a.seating_plan_id
        if (
            await self.db.execute(
                select(ExamSeatAllocation.id).where(
                    ExamSeatAllocation.seating_plan_id == target,
                    ExamSeatAllocation.seat_number == body.seat_number,
                    ExamSeatAllocation.id != a.id,
                )
            )
        ).first():
            raise APIError(409, ErrorCode.CONFLICT, "Seat already taken")
        a.seating_plan_id, a.seat_number = target, body.seat_number
        await self.db.flush()
        await self._audit(
            "seat_move", "exam_seat_allocation", a.id, old, {"plan": str(target), "seat": body.seat_number}
        )
        plan = (await self.db.execute(select(ExamSeatingPlan).where(ExamSeatingPlan.id == target))).scalar_one()
        return next(r for r in await self.rows(plan.exam_session_id, None, None, plan.id) if r.id == a.id)

    async def publish(self, sid: uuid.UUID, exam_date: Any = None, slot: str | None = None) -> int:
        s = await self.session(sid, write=True)
        q = (
            select(ExamSeatingPlan)
            .where(ExamSeatingPlan.exam_session_id == s.id, ExamSeatingPlan.status == "draft")
            .with_for_update()
        )
        if exam_date:
            q = q.where(ExamSeatingPlan.exam_date == exam_date)
        if slot:
            q = q.where(ExamSeatingPlan.session_slot == slot)
        plans = (await self.db.execute(q)).scalars().all()
        for p in plans:
            p.status = "published"
        await self.db.flush()
        regen = await HallTicketService(self.db, self.principal, self.request, self.inst).generate(
            s.id, HallTicketGenerateRequest(only_missing=False)
        )
        await self._emit(
            "exams.seating_published",
            {"exam_session_id": str(s.id), "plans": len(plans), "hall_tickets": regen["issued"]},
            "exam_session",
            s.id,
        )
        return len(plans)

    async def my_seat(self, paper_id: uuid.UUID | None) -> list[dict[str, Any]]:
        from app.repositories.fee_scope import own_enrollment_ids

        q = (
            select(ExamPaper, Course, Room, ExamSeatAllocation)
            .join(ExamRegistrationItem, ExamRegistrationItem.exam_paper_id == ExamPaper.id)
            .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
            .join(Course, Course.id == ExamPaper.course_id)
            .join(ExamSeatAllocation, ExamSeatAllocation.exam_registration_item_id == ExamRegistrationItem.id)
            .join(ExamSeatingPlan, ExamSeatingPlan.id == ExamSeatAllocation.seating_plan_id)
            .join(Room, Room.id == ExamSeatingPlan.room_id)
            .where(
                ExamRegistration.student_program_enrollment_id.in_(own_enrollment_ids(self.principal, advisees=False)),
                ExamSeatingPlan.status == "published",
            )
        )
        if paper_id:
            q = q.where(ExamPaper.id == paper_id)
        return [
            {
                "paper_id": str(p.id),
                "course": c.code,
                "date": p.exam_date.isoformat() if p.exam_date else None,
                "slot": p.session_slot,
                "room": r.code,
                "room_name": r.name,
                "seat": a.seat_number,
            }
            for p, c, r, a in (await self.db.execute(q)).all()
        ]

    async def chart_pdf(self, plan_id: uuid.UUID, *, door: bool = False) -> bytes:
        from app.utils.pdf import render_pdf

        plan = (
            await self.db.execute(
                select(ExamSeatingPlan).where(
                    ExamSeatingPlan.id == plan_id, ExamSeatingPlan.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if plan is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Seating plan not found")
        rows = await self.rows(plan.exam_session_id, None, None, plan.id)
        room = rows[0].room_code if rows else ""
        title = f"{'Door list' if door else 'Seating chart'} — {room} — {plan.exam_date} {plan.session_slot}"
        data = sorted(rows, key=lambda r: r.hall_ticket_number or "") if door else rows
        lines = [title, ""] + [
            f"{r.seat_number:6s} {r.hall_ticket_number or '':14s} {r.registration_number or '':14s} {r.paper_code or ''}"
            for r in data
        ]
        return render_pdf("<html><body>" + "".join(f"<p>{x}</p>" for x in lines) + "</body></html>", lines, title=title)
