"""Exam registration — Prompts/14 §14.6 ``exam_registration_service``.

1. ``build_for(session, enrolment)``: regular items = confirmed registration items of the session's term whose
   courses have papers; arrear items = open / registered ``student_arrears`` with papers (``attempt_number =
   attempts + 1``); improvement sessions take the regular courses as ``improvement``; fee per ``fee_rules``; the
   draft is rebuilt while ``draft``.
2. ``submit`` (student, ``Idempotency-Key``): window = ``registration_start .. registration_end`` (+ late fee until
   ``late_fee_until``; after it 409 ``WINDOW_CLOSED``); ``exam`` / ``all`` holds → 409 ``HOLD_BLOCKED``; an invoice
   ``source_type='exam_registration'`` (Phase 12 linkage) → ``fee_pending``; zero fee → ``confirmed``; the
   ``exams.registration_paid`` consumer confirms on ``fees.payment_received``.
3. Admin create / cancel / debar / reinstate (``exams:manage``) and bulk registration (job) of every enrolment with
   confirmed items in the term.
4. ``apply_eligibility``: the latest (or given) ``term_eligibility`` version per (term record, offering) → item
   ``eligibility`` + ``exam_registrations.eligibility_snapshot``; ``recompute`` queues a new Phase 11 version first.
"""
# mypy: disable-error-code="arg-type,var-annotated"

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
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
from app.models.offerings import CourseOffering
from app.models.registration import CourseRegistration, CourseRegistrationItem, StudentArrear
from app.models.students import Student, StudentHold, StudentProgramEnrollment, StudentTermRecord
from app.models.timetable import Room
from app.repositories.exam_scope import registration_predicate, visibility
from app.schemas.exams import (
    EligibilityApplyRequest,
    EligibilityApplySummary,
    ExamRegistrationItemOut,
    ExamRegistrationResponse,
    RegistrationAdminCreate,
)
from app.services.exams.common import ExamBase, now_utc, rule, student_name
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

ENTITY = "exam_registration"


class ExamRegistrationService(ExamBase):
    # ---- responses -------------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[ExamRegistration], *, detail: bool = True) -> list[ExamRegistrationResponse]:
        ids = [r.id for r in rows]
        sessions = {
            s.id: s
            for s in (
                await self.db.execute(
                    select(ExamSession).where(ExamSession.id.in_({r.exam_session_id for r in rows} or {uuid.uuid4()}))
                )
            ).scalars()
        }
        people = dict(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.id, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(
                        StudentProgramEnrollment.id.in_(
                            [r.student_program_enrollment_id for r in rows] or [uuid.uuid4()]
                        )
                    )
                )
            ).all()
        )
        invoices = {
            i.id: i
            for i in (
                await self.db.execute(
                    select(FeeInvoice).where(
                        FeeInvoice.id.in_([r.fee_invoice_id for r in rows if r.fee_invoice_id] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        items: dict[uuid.UUID, list[Any]] = defaultdict(list)
        seats: dict[uuid.UUID, dict[str, Any]] = {}
        holds: dict[uuid.UUID, list[str]] = defaultdict(list)
        if detail and ids:
            for it, p, c in (
                await self.db.execute(
                    select(ExamRegistrationItem, ExamPaper, Course)
                    .join(ExamPaper, ExamPaper.id == ExamRegistrationItem.exam_paper_id)
                    .join(Course, Course.id == ExamRegistrationItem.course_id)
                    .where(ExamRegistrationItem.exam_registration_id.in_(ids))
                    .order_by(ExamPaper.exam_date.nulls_last(), Course.code)
                )
            ).all():
                items[it.exam_registration_id].append((it, p, c))
            item_ids = [it.id for lst in items.values() for it, _, _ in lst]
            for a, _plan, room in (
                await self.db.execute(
                    select(ExamSeatAllocation, ExamSeatingPlan, Room)
                    .join(ExamSeatingPlan, ExamSeatingPlan.id == ExamSeatAllocation.seating_plan_id)
                    .join(Room, Room.id == ExamSeatingPlan.room_id)
                    .where(
                        ExamSeatAllocation.exam_registration_item_id.in_(item_ids or [uuid.uuid4()]),
                        ExamSeatingPlan.status == "published",
                    )
                )
            ).all():
                seats[a.exam_registration_item_id] = {"room": room.code, "seat": a.seat_number, "room_name": room.name}
            for h in (
                await self.db.execute(
                    select(StudentHold).where(
                        StudentHold.student_program_enrollment_id.in_([r.student_program_enrollment_id for r in rows]),
                        StudentHold.released_at.is_(None),
                        StudentHold.hold_type.in_(("exam", "all")),
                    )
                )
            ).scalars():
                holds[h.student_program_enrollment_id].append(f"{h.hold_type}: {h.reason}")
        now = now_utc()
        out = []
        for r in rows:
            o = ExamRegistrationResponse.model_validate(r)
            s = sessions.get(r.exam_session_id)
            st = people.get(r.student_program_enrollment_id)
            o.session_name = s.name if s else None
            o.registration_number, o.student_name = (st.registration_number, student_name(st)) if st else (None, None)
            inv = invoices.get(r.fee_invoice_id) if r.fee_invoice_id else None
            o.invoice_status = inv.status if inv else None
            o.hall_ticket_available = bool(
                r.hall_ticket_number
                and (s is None or s.hall_ticket_release_at is None or s.hall_ticket_release_at <= now)
            )
            o.holds = holds.get(r.student_program_enrollment_id, [])
            o.items = []
            for it, p, c in items.get(r.id, []):
                io = ExamRegistrationItemOut.model_validate(it)
                io.course_code, io.course_title, io.paper_type, io.exam_date, io.session_slot = (
                    c.code,
                    c.title,
                    p.paper_type,
                    p.exam_date,
                    p.session_slot,
                )
                io.seat = seats.get(it.id)
                o.items.append(io)
            out.append(o)
        return out

    # ---- 1. build ----------------------------------------------------------------------------------------------------------
    async def _registrable(self, s: ExamSession, enrol: StudentProgramEnrollment) -> list[tuple[ExamPaper, str, int]]:
        papers = (await self.db.execute(select(ExamPaper).where(ExamPaper.exam_session_id == s.id))).scalars().all()
        by_course: dict[uuid.UUID, list[ExamPaper]] = defaultdict(list)
        for p in papers:
            by_course[p.course_id].append(p)
        wanted: list[tuple[ExamPaper, str, int]] = []
        seen: set[uuid.UUID] = set()
        arrears = {
            a.course_id: a
            for a in (
                await self.db.execute(
                    select(StudentArrear).where(
                        StudentArrear.student_program_enrollment_id == enrol.id,
                        StudentArrear.status.in_(("open", "registered")),
                    )
                )
            ).scalars()
        }
        if s.exam_kind not in ("arrear", "supplementary"):
            regular = (
                (
                    await self.db.execute(
                        select(CourseOffering.course_id)
                        .join(CourseRegistrationItem, CourseRegistrationItem.offering_id == CourseOffering.id)
                        .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
                        .where(
                            CourseRegistration.student_program_enrollment_id == enrol.id,
                            CourseRegistration.term_id == s.term_id,
                            CourseRegistrationItem.status == "confirmed",
                        )
                    )
                )
                .scalars()
                .all()
            )
            for cid in regular:
                if cid in arrears:
                    continue
                for p in by_course.get(cid, []):
                    if p.id not in seen:
                        wanted.append((p, "improvement" if s.exam_kind == "improvement" else "regular", 1))
                        seen.add(p.id)
        for cid, a in arrears.items():
            for p in by_course.get(cid, []):
                if p.id not in seen and p.paper_type in ("theory", "online", "practical"):
                    wanted.append((p, "arrear", a.attempts + 1))
                    seen.add(p.id)
        return wanted

    async def build_for(self, s: ExamSession, enrol: StudentProgramEnrollment) -> ExamRegistration:
        reg = (
            await self.db.execute(
                select(ExamRegistration)
                .where(
                    ExamRegistration.exam_session_id == s.id, ExamRegistration.student_program_enrollment_id == enrol.id
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if reg is None:
            reg = ExamRegistration(
                institution_id=self.inst,
                college_id=enrol.college_id,
                exam_session_id=s.id,
                student_program_enrollment_id=enrol.id,
                status="draft",
            )
            self.db.add(reg)
            await self.db.flush()
        if reg.status != "draft":
            return reg
        current = {
            i.exam_paper_id: i
            for i in (
                await self.db.execute(
                    select(ExamRegistrationItem).where(ExamRegistrationItem.exam_registration_id == reg.id)
                )
            ).scalars()
        }
        wanted = await self._registrable(s, enrol)
        keep = set()
        fees = []
        for p, atype, attempt in wanted:
            fee = self.item_fee(s, p.paper_type, atype)
            fees.append(fee)
            keep.add(p.id)
            it = current.get(p.id)
            if it is None:
                self.db.add(
                    ExamRegistrationItem(
                        institution_id=self.inst,
                        exam_registration_id=reg.id,
                        exam_paper_id=p.id,
                        course_id=p.course_id,
                        attempt_type=atype,
                        attempt_number=attempt,
                        fee_paise=fee,
                        eligibility="pending",
                        status="registered",
                    )
                )
            else:
                it.attempt_type, it.attempt_number, it.fee_paise = atype, attempt, fee
        for pid, it in current.items():
            if pid not in keep:
                await self.db.delete(it)
        late = bool(s.registration_end and now_utc() > s.registration_end)
        reg.total_fee_paise, _ = self.total_fee(s, fees, late=late)
        await self.db.flush()
        return reg

    # ---- self ---------------------------------------------------------------------------------------------------------------
    async def my_enrolment(self, ward_id: uuid.UUID | None = None) -> StudentProgramEnrollment:
        from app.repositories.fee_scope import own_enrollment_ids

        q = (
            select(StudentProgramEnrollment)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(
                StudentProgramEnrollment.id.in_(own_enrollment_ids(self.principal, advisees=False)),
                StudentProgramEnrollment.deleted_at.is_(None),
            )
            .order_by(StudentProgramEnrollment.admission_date.desc())
        )
        q = q.where(Student.id == ward_id) if ward_id else q.where(Student.user_id == self.actor_id)
        e = (await self.db.execute(q.limit(1))).scalar_one_or_none()
        if e is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "No enrolment found")
        return e

    async def current_session_for(self, enrol: StudentProgramEnrollment) -> ExamSession:
        from sqlalchemy import or_

        s = (
            await self.db.execute(
                select(ExamSession)
                .where(
                    ExamSession.institution_id == self.inst,
                    ExamSession.deleted_at.is_(None),
                    ExamSession.status.notin_(("draft", "closed")),
                    or_(ExamSession.college_id.is_(None), ExamSession.college_id == enrol.college_id),
                )
                .order_by(ExamSession.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "No open exam session")
        return s

    async def mine(self, session_id: uuid.UUID | None, ward_id: uuid.UUID | None = None) -> ExamRegistrationResponse:
        enrol = await self.my_enrolment(ward_id)
        s = await self.session(session_id) if session_id else await self.current_session_for(enrol)
        reg = (
            await self.build_for(s, enrol)
            if s.status == "registration_open" and not ward_id
            else (
                await self.db.execute(
                    select(ExamRegistration).where(
                        ExamRegistration.exam_session_id == s.id,
                        ExamRegistration.student_program_enrollment_id == enrol.id,
                    )
                )
            ).scalar_one_or_none()
        )
        if reg is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "No exam registration for this session")
        out = (await self.outs([reg]))[0]
        late = bool(s.registration_end and now_utc() > s.registration_end)
        out.late_fee_paise = self.total_fee(s, [i.fee_paise for i in out.items], late=late)[1]
        return out

    async def history(self) -> list[ExamRegistrationResponse]:
        enrol = await self.my_enrolment()
        rows = (
            (
                await self.db.execute(
                    select(ExamRegistration)
                    .where(ExamRegistration.student_program_enrollment_id == enrol.id)
                    .order_by(ExamRegistration.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows))

    def _window(self, s: ExamSession) -> bool:
        now = now_utc()
        if s.status != "registration_open":
            return False
        if s.registration_start and now < s.registration_start:
            return False
        end = s.late_fee_until or s.registration_end
        return not (end and now > end)

    async def submit(
        self, session_id: uuid.UUID | None, item_ids: list[uuid.UUID] | None = None
    ) -> ExamRegistrationResponse:
        enrol = await self.my_enrolment()
        s = await self.session(session_id) if session_id else await self.current_session_for(enrol)
        if not self._window(s):
            raise rule("The registration window is closed", "WINDOW_CLOSED")
        reg = await self.build_for(s, enrol)
        if reg.status != "draft":
            return (await self.outs([reg]))[0]
        return await self._finalise(s, reg, enrol, item_ids)

    async def _finalise(
        self,
        s: ExamSession,
        reg: ExamRegistration,
        enrol: StudentProgramEnrollment,
        item_ids: list[uuid.UUID] | None,
        *,
        skip_holds: bool = False,
    ) -> ExamRegistrationResponse:
        from app.services.hold_service import HoldService

        if not skip_holds:
            await HoldService(self.db, self.principal, self.request, self.inst).assert_clear(enrol.id, "exam")
        items = (
            await self.db.execute(
                select(ExamRegistrationItem, ExamPaper, Course)
                .join(ExamPaper, ExamPaper.id == ExamRegistrationItem.exam_paper_id)
                .join(Course, Course.id == ExamRegistrationItem.course_id)
                .where(ExamRegistrationItem.exam_registration_id == reg.id)
            )
        ).all()
        if item_ids is not None:
            for it, _, _ in items:
                if it.id not in item_ids and it.attempt_type != "regular":
                    it.status = "cancelled"
        live = [(it, p, c) for it, p, c in items if it.status != "cancelled"]
        if not live:
            raise rule("Nothing to register", "NO_ITEMS", 422)
        late = bool(s.registration_end and now_utc() > s.registration_end)
        total, late_fee = self.total_fee(s, [it.fee_paise for it, _, _ in live], late=late)
        reg.total_fee_paise = total
        reg.status = "submitted"
        await self.db.flush()
        if total > 0:
            from app.schemas.fees import InvoiceCreate, InvoiceItemIn
            from app.services.fees.invoice_service import InvoiceService

            inv_svc = InvoiceService(self.db, self.principal, self.request, self.inst)
            head = await inv_svc.head_by_type("exam")
            lines = [
                InvoiceItemIn(
                    description=f"{c.code} {p.paper_type} ({it.attempt_type})"[:200],
                    amount_paise=it.fee_paise,
                    fee_head_id=head.id if head else None,
                )
                for it, p, c in live
            ]
            cap = self.fee_rules(s).get("max_paise")
            if cap and sum(it.fee_paise for it, _, _ in live) > cap:
                lines = [
                    InvoiceItemIn(
                        description=f"Examination fee ({len(live)} papers, capped)",
                        amount_paise=cap,
                        fee_head_id=head.id if head else None,
                    )
                ]
            if late_fee:
                fine = await inv_svc.head_by_type("fine")
                lines.append(
                    InvoiceItemIn(
                        description="Late registration fee",
                        amount_paise=late_fee,
                        fee_head_id=fine.id if fine else None,
                    )
                )
            inv = await inv_svc.create_invoice(
                InvoiceCreate(
                    enrollment_id=enrol.id,
                    source_type="exam_registration",
                    source_id=reg.id,
                    description=f"Exam fee · {s.name}",
                    items=lines,
                    due_date=(s.late_fee_until or s.registration_end or now_utc()).date(),
                    term_id=s.term_id,
                )
            )
            reg.fee_invoice_id = inv.id
            reg.status = "fee_pending" if inv.balance_paise > 0 else "confirmed"
        else:
            reg.status = "confirmed"
        reg.version += 1
        await self.db.flush()
        await self._audit(
            "submit", ENTITY, reg.id, {"status": "draft"}, {"status": reg.status, "total_fee_paise": total}
        )
        await self._emit("exam.registration_submitted", {"exam_registration_id": str(reg.id)}, ENTITY, reg.id)
        if reg.status == "confirmed":
            await self._emit(
                "exam.registration_confirmed",
                {"exam_registration_id": str(reg.id), "student_program_enrollment_id": str(enrol.id)},
                ENTITY,
                reg.id,
            )
        return (await self.outs([reg]))[0]

    async def on_paid(self, reg_id: uuid.UUID) -> bool:
        reg = (
            await self.db.execute(select(ExamRegistration).where(ExamRegistration.id == reg_id).with_for_update())
        ).scalar_one_or_none()
        if reg is None or reg.status != "fee_pending":
            return False
        inv = (
            await self.db.execute(select(FeeInvoice).where(FeeInvoice.id == reg.fee_invoice_id))
        ).scalar_one_or_none()
        if inv is None or inv.balance_paise > 0:
            return False
        reg.status = "confirmed"
        reg.version += 1
        await self.db.flush()
        await self._audit("confirm", ENTITY, reg.id, {"status": "fee_pending"}, {"status": "confirmed"})
        await self._emit(
            "exam.registration_confirmed",
            {
                "exam_registration_id": str(reg.id),
                "student_program_enrollment_id": str(reg.student_program_enrollment_id),
            },
            ENTITY,
            reg.id,
        )
        return True

    # ---- 3. admin ------------------------------------------------------------------------------------------------------------
    async def list_page(
        self,
        sid: uuid.UUID,
        params: PageParams,
        *,
        status: str | None,
        college_id: uuid.UUID | None,
        program_id: uuid.UUID | None,
        search: str | None,
        scope: str | None,
    ) -> tuple[list[ExamRegistrationResponse], PaginationMeta, VisibilityMeta]:
        s = await self.session(sid)
        q = select(ExamRegistration).where(
            ExamRegistration.exam_session_id == s.id, registration_predicate(self.principal, scope)
        )
        if status:
            q = q.where(ExamRegistration.status == status)
        if college_id:
            q = q.where(ExamRegistration.college_id == college_id)
        if program_id or search:
            sub = select(StudentProgramEnrollment.id).join(Student, Student.id == StudentProgramEnrollment.student_id)
            if program_id:
                sub = sub.where(StudentProgramEnrollment.program_id == program_id)
            if search:
                sub = sub.where(
                    Student.registration_number.ilike(f"%{search}%") | Student.first_name.ilike(f"%{search}%")
                )
            q = q.where(ExamRegistration.student_program_enrollment_id.in_(sub))
        total = (await self.db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (
            (
                await self.db.execute(
                    q.order_by(ExamRegistration.created_at).offset(params.offset).limit(params.page_size)
                )
            )
            .scalars()
            .all()
        )
        outs = await self.outs(list(rows))
        fee_only = self.can("fees", "view_all") and not (self.can("exams", "view_all") or self.can("exams", "manage"))
        if fee_only:
            for o in outs:
                o.eligibility_snapshot = None
                for it in o.items:
                    it.eligibility = "—"
        return (
            outs,
            PaginationMeta(
                page=params.page,
                page_size=params.page_size,
                total=total,
                total_pages=max(1, -(-total // params.page_size)),
            ),
            visibility(self.principal),
        )

    async def get(self, rid: uuid.UUID) -> ExamRegistrationResponse:
        reg = (
            await self.db.execute(
                select(ExamRegistration).where(
                    ExamRegistration.id == rid,
                    ExamRegistration.institution_id == self.inst,
                    registration_predicate(self.principal, "all"),
                )
            )
        ).scalar_one_or_none()
        if reg is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Exam registration not found")
        return (await self.outs([reg]))[0]

    async def admin_create(self, body: RegistrationAdminCreate) -> ExamRegistrationResponse:
        papers = (await self.db.execute(select(ExamPaper).where(ExamPaper.id.in_(body.paper_ids)))).scalars().all()
        if len(papers) != len(set(body.paper_ids)) or len({p.exam_session_id for p in papers}) != 1:
            raise APIError(422, ErrorCode.VALIDATION, "Papers must exist and belong to one session")
        s = await self.session(papers[0].exam_session_id, write=True)
        enrol = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(
                    StudentProgramEnrollment.id == body.enrollment_id,
                    StudentProgramEnrollment.institution_id == self.inst,
                )
            )
        ).scalar_one_or_none()
        if enrol is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Enrolment not found")
        reg = (
            await self.db.execute(
                select(ExamRegistration)
                .where(
                    ExamRegistration.exam_session_id == s.id, ExamRegistration.student_program_enrollment_id == enrol.id
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if reg is None:
            reg = ExamRegistration(
                institution_id=self.inst,
                college_id=enrol.college_id,
                exam_session_id=s.id,
                student_program_enrollment_id=enrol.id,
                status="draft",
            )
            self.db.add(reg)
            await self.db.flush()
        have = {
            i.exam_paper_id
            for i in (
                await self.db.execute(
                    select(ExamRegistrationItem).where(ExamRegistrationItem.exam_registration_id == reg.id)
                )
            ).scalars()
        }
        for p in papers:
            if p.id in have:
                continue
            atype = (body.attempt_types or {}).get(str(p.id), "regular")
            self.db.add(
                ExamRegistrationItem(
                    institution_id=self.inst,
                    exam_registration_id=reg.id,
                    exam_paper_id=p.id,
                    course_id=p.course_id,
                    attempt_type=atype,
                    attempt_number=1,
                    fee_paise=self.item_fee(s, p.paper_type, atype),
                    eligibility="pending",
                    status="registered",
                )
            )
        await self.db.flush()
        await self._audit("admin_create", ENTITY, reg.id, None, {"papers": len(papers), "confirm": body.confirm})
        if body.confirm and reg.status == "draft":
            reg.status = "confirmed"
            await self.db.flush()
            await self._emit("exam.registration_confirmed", {"exam_registration_id": str(reg.id)}, ENTITY, reg.id)
        elif reg.status == "draft":
            return await self._finalise(s, reg, enrol, None, skip_holds=True)
        return (await self.outs([reg]))[0]

    async def set_status(self, rid: uuid.UUID, to: str, reason: str) -> ExamRegistrationResponse:
        reg = (
            await self.db.execute(
                select(ExamRegistration)
                .where(ExamRegistration.id == rid, ExamRegistration.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if reg is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Exam registration not found")
        await self.session(reg.exam_session_id, write=True)
        old = reg.status
        if to == "reinstate":
            if old not in ("cancelled", "debarred"):
                raise APIError(409, ErrorCode.CONFLICT, f"Registration is {old}")
            inv = (
                (
                    await self.db.execute(select(FeeInvoice).where(FeeInvoice.id == reg.fee_invoice_id))
                ).scalar_one_or_none()
                if reg.fee_invoice_id
                else None
            )
            to = "confirmed" if inv is None or inv.balance_paise <= 0 else "fee_pending"
        reg.status = to
        if to in ("cancelled", "debarred"):
            reg.hall_ticket_qr_token = None  # revoke: verify answers valid=false
        reg.version += 1
        await self.db.flush()
        await self._audit(f"status_{to}", ENTITY, reg.id, {"status": old}, {"status": to, "reason": reason})
        event = {"cancelled": "exam.registration_cancelled", "debarred": "exam.registration_debarred"}.get(to)
        if event:
            await self._emit(event, {"exam_registration_id": str(reg.id), "reason": reason}, ENTITY, reg.id)
        return (await self.outs([reg]))[0]

    async def bulk_register(self, sid: uuid.UUID, progress: Any = None) -> dict[str, int]:
        s = await self.session(sid, write=True)
        enrols = (
            (
                await self.db.execute(
                    select(StudentProgramEnrollment).where(
                        StudentProgramEnrollment.id.in_(
                            select(CourseRegistration.student_program_enrollment_id)
                            .join(
                                CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id
                            )
                            .where(
                                CourseRegistration.term_id == s.term_id, CourseRegistrationItem.status == "confirmed"
                            )
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        out = {"registrations": 0, "confirmed": 0, "fee_pending": 0, "skipped": 0}
        for n, e in enumerate(enrols):
            if s.college_id and e.college_id != s.college_id:
                continue
            reg = await self.build_for(s, e)
            if reg.status != "draft":
                out["skipped"] += 1
                continue
            try:
                r = await self._finalise(s, reg, e, None, skip_holds=True)
                out["registrations"] += 1
                out[r.status] = out.get(r.status, 0) + 1
            except APIError:
                out["skipped"] += 1
            if progress and n % 25 == 0:
                await progress(int(n * 100 / max(1, len(enrols))), f"{n}/{len(enrols)}")
        return out

    async def lapse_fee_pending(self) -> int:
        now = now_utc()
        rows = (
            (
                await self.db.execute(
                    select(ExamRegistration)
                    .join(ExamSession, ExamSession.id == ExamRegistration.exam_session_id)
                    .where(
                        ExamRegistration.institution_id == self.inst,
                        ExamRegistration.status == "fee_pending",
                        ExamSession.late_fee_until < now,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            r.status = "cancelled"
            await self._audit(
                "lapse",
                ENTITY,
                r.id,
                {"status": "fee_pending"},
                {"status": "cancelled", "reason": "fee unpaid after the late-fee date"},
            )
        await self.db.flush()
        return len(rows)

    # ---- 4. eligibility --------------------------------------------------------------------------------------------------------
    async def apply_eligibility(
        self, sid: uuid.UUID, body: EligibilityApplyRequest, progress: Any = None
    ) -> EligibilityApplySummary:
        from app.models.attendance import TermEligibility

        s = await self.session(sid, write=True)
        if body.recompute:
            from app.core.jobs import enqueue

            if self.principal is not None and getattr(self.principal, "id", None):
                await enqueue(self.db, self.principal, "eligibility.compute", {"term_id": str(s.term_id)})
        version = (
            body.version
            or (
                await self.db.execute(
                    select(func.max(TermEligibility.version))
                    .join(StudentTermRecord, StudentTermRecord.id == TermEligibility.student_term_record_id)
                    .where(StudentTermRecord.term_id == s.term_id)
                )
            ).scalar_one_or_none()
        )
        out = EligibilityApplySummary(version=version)
        regs = (
            (
                await self.db.execute(
                    select(ExamRegistration)
                    .where(ExamRegistration.exam_session_id == s.id, ExamRegistration.status.notin_(("cancelled",)))
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for n, reg in enumerate(regs):
            rows = (
                (
                    await self.db.execute(
                        select(TermEligibility, CourseOffering.course_id)
                        .join(CourseOffering, CourseOffering.id == TermEligibility.offering_id)
                        .join(StudentTermRecord, StudentTermRecord.id == TermEligibility.student_term_record_id)
                        .where(
                            StudentTermRecord.student_program_enrollment_id == reg.student_program_enrollment_id,
                            StudentTermRecord.term_id == s.term_id,
                            TermEligibility.version == version,
                        )
                    )
                ).all()
                if version
                else []
            )
            decided = {cid: te for te, cid in rows}
            snapshot: dict[str, Any] = {"version": version, "items": {}}
            for it in (
                await self.db.execute(
                    select(ExamRegistrationItem).where(ExamRegistrationItem.exam_registration_id == reg.id)
                )
            ).scalars():
                te = decided.get(it.course_id)
                if it.attempt_type == "arrear":
                    it.eligibility = "eligible"
                elif te is None:
                    it.eligibility = "pending" if version else "eligible"
                else:
                    it.eligibility = (
                        te.decision if te.decision in ("eligible", "condoned", "detained", "debarred") else "pending"
                    )
                snapshot["items"][str(it.course_id)] = {
                    "eligibility": it.eligibility,
                    "reasons": te.reason_codes if te else None,
                }
                out.by_decision[it.eligibility] = out.by_decision.get(it.eligibility, 0) + 1
                out.items += 1
            reg.eligibility_snapshot = snapshot
            out.registrations += 1
            if progress and n % 50 == 0:
                await progress(int(n * 100 / max(1, len(regs))), f"{n}/{len(regs)}")
        await self.db.flush()
        await self._audit("eligibility_apply", "exam_session", s.id, None, out.model_dump())
        await self._emit(
            "exams.eligibility_applied", {"exam_session_id": str(s.id), "version": version}, "exam_session", s.id
        )
        return out

    async def eligibility_summary(self, sid: uuid.UUID) -> EligibilityApplySummary:
        s = await self.session(sid)
        rows = (
            await self.db.execute(
                select(ExamRegistrationItem.eligibility, func.count())
                .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
                .where(ExamRegistration.exam_session_id == s.id)
                .group_by(ExamRegistrationItem.eligibility)
            )
        ).all()
        regs = (
            await self.db.execute(
                select(func.count()).select_from(ExamRegistration).where(ExamRegistration.exam_session_id == s.id)
            )
        ).scalar_one()
        return EligibilityApplySummary(
            registrations=int(regs), items=sum(int(n) for _, n in rows), by_decision={k: int(n) for k, n in rows}
        )
