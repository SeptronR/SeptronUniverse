"""Invigilation, question papers and conduct — Prompts/14 §14.6 ``invigilation_service`` / ``qp_service`` /
``hall_attendance_service`` / ``online_exam_service``.

Invigilation ``auto_assign``: for every (date, slot, room with a seating plan) fill ``roles_per_room`` from active
teaching staff of the session's college (all colleges for a central session), skipping excluded staff, staff on
approved leave that day, staff with a class session at that slot, staff already on duty in the slot (UNIQUE
guarantee) and staff teaching a paper of that slot; least-loaded first, ``max_duties_per_staff`` respected;
remuneration per role from ``exams.duty_remuneration`` (paise). Swaps: request (own duty) → exam cell approves with an
availability check (409 ``STAFF_BUSY``) → ``swapped`` (the duty moves to the other staff member). Remuneration lines
reach payroll through the Phase 06 hook registry (source ``exam_duty``) when ``exams.remuneration`` is on.

QP: assignments per paper × set (internal setter or external JSON with ``user_id``); upload stores the file
encrypted (AES-GCM via ``encrypt_secret`` over base64) under ``exams/qp/{session}/{paper}/{set}`` and keeps the
encrypted storage key in ``file_key_encrypted``; blueprint generation reuses the Phase 13 paper builder (frozen
paper); scrutiny → approve / reject; select one set (others ``rejected``); print burns a watermark into the PDF, logs
``question_paper_print_log`` and returns a single-use 10-minute download token (Redis; reused → 410); every content
access is audited (``action='qp_access'``).

Conduct: hall attendance per paper (present / absent / late / malpractice; booklet numbers unique per paper → 422;
optional face-match via the ``face_verification`` adapter), item status ``appeared / absent / malpractice``,
malpractice reports create ``malpractice_cases(status='reported')`` (Phase 16 inquiry); online papers link a Phase 13
quiz and grant access only inside the paper window.
"""

import base64
import secrets
import uuid
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.curriculum import Course
from app.models.exams import (
    ExamAttendance,
    ExamPaper,
    ExamRegistration,
    ExamRegistrationItem,
    ExamSeatAllocation,
    ExamSeatingPlan,
    InvigilationDuty,
    MalpracticeCase,
    QuestionPaperAssignment,
    QuestionPaperPrintLog,
)
from app.models.hr import Staff, StaffLeave
from app.models.offerings import CourseOffering, CourseOfferingFaculty
from app.models.students import Student, StudentProgramEnrollment
from app.models.timetable import ClassSession, Room
from app.repositories.assessment_scope import staff_ids
from app.repositories.exam_scope import qp_predicate
from app.schemas.exams import (
    DutyCreate,
    DutyResponse,
    DutyUpdate,
    HallAttendanceMark,
    HallAttendanceRowOut,
    InvigilationAutoAssignRequest,
    MalpracticeOut,
    MalpracticeReportCreate,
    OnlinePaperSetup,
    QpAssignmentCreate,
    QpAssignmentResponse,
    QpPrintRequest,
    QpPrintResponse,
    QpScrutinyRequest,
    RemunerationSummary,
    RosterSummary,
    SwapRequest,
)
from app.services.exams.common import ExamBase, now_utc, rule, student_name

SLOT_TIMES = {"FN": (time(9, 30), time(13, 0)), "AN": (time(13, 30), time(17, 0)), "EVE": (time(17, 0), time(20, 0))}
DEFAULT_RATES = {
    "chief_superintendent": 150000,
    "hall_superintendent": 80000,
    "invigilator": 50000,
    "reliever": 30000,
    "flying_squad": 60000,
    "observer": 60000,
    "qp_setter": 200000,
}


def _office(svc: ExamBase) -> None:
    """Roster / QP administration needs the exam office (``view_all`` or ``manage`` next to the route grant): faculty
    hold ``exams:invigilation`` / ``exams:qp`` only for their own duties and setter assignments."""
    if not (svc.can("exams", "view_all") or svc.can("exams", "manage")):
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "Exam-office permission required")


class InvigilationService(ExamBase):
    async def rates(self) -> dict[str, int]:
        return {**DEFAULT_RATES, **(await self.setting("exams", "duty_remuneration") or {})}

    async def outs(self, rows: list[InvigilationDuty]) -> list[DutyResponse]:
        staff = {
            s.id: s
            for s in (
                await self.db.execute(select(Staff).where(Staff.id.in_([r.staff_id for r in rows] or [uuid.uuid4()])))
            ).scalars()
        }
        rooms = {
            r.id: r.code
            for r in (
                await self.db.execute(
                    select(Room).where(Room.id.in_([r.room_id for r in rows if r.room_id] or [uuid.uuid4()]))
                )
            ).scalars()
        }
        out = []
        for r in rows:
            o = DutyResponse.model_validate(r)
            s = staff.get(r.staff_id)
            o.staff_name = f"{s.first_name} {s.last_name or ''}".strip() if s else None
            o.room_code = rooms.get(r.room_id) if r.room_id else None
            out.append(o)
        return out

    async def _busy(self, staff_id: uuid.UUID, d: Any, slot: str, session_id: uuid.UUID) -> str | None:
        if (
            await self.db.execute(
                select(InvigilationDuty.id).where(
                    InvigilationDuty.exam_session_id == session_id,
                    InvigilationDuty.exam_date == d,
                    InvigilationDuty.session_slot == slot,
                    InvigilationDuty.staff_id == staff_id,
                    InvigilationDuty.status != "swapped",
                )
            )
        ).first():
            return "already on duty"
        if (
            await self.db.execute(
                select(StaffLeave.id).where(
                    StaffLeave.staff_id == staff_id,
                    StaffLeave.status == "approved",
                    StaffLeave.from_date <= d,
                    StaffLeave.to_date >= d,
                )
            )
        ).first():
            return "on leave"
        t0, t1 = SLOT_TIMES.get(slot, SLOT_TIMES["FN"])
        if (
            await self.db.execute(
                select(ClassSession.id).where(
                    ClassSession.staff_id == staff_id,
                    ClassSession.session_date == d,
                    ClassSession.start_time >= t0,
                    ClassSession.start_time < t1,
                    ClassSession.status != "cancelled",
                )
            )
        ).first():
            return "has a class"
        return None

    async def auto_assign(
        self, sid: uuid.UUID, body: InvigilationAutoAssignRequest, progress: Any = None
    ) -> RosterSummary:
        _office(self)
        s = await self.session(sid, write=True)
        plans = (
            (
                await self.db.execute(
                    select(ExamSeatingPlan)
                    .where(
                        ExamSeatingPlan.exam_session_id == s.id,
                        ExamSeatingPlan.exam_date >= body.date_from,
                        ExamSeatingPlan.exam_date <= body.date_to,
                    )
                    .order_by(ExamSeatingPlan.exam_date, ExamSeatingPlan.session_slot)
                )
            )
            .scalars()
            .all()
        )
        q = select(Staff).where(
            Staff.institution_id == self.inst,
            Staff.deleted_at.is_(None),
            Staff.exit_date.is_(None),
            Staff.staff_category == "teaching",
            Staff.id.notin_(body.exclude_staff_ids or [uuid.uuid4()]),
        )
        if s.college_id:
            q = q.where(Staff.college_id == s.college_id)
        pool = list((await self.db.execute(q.order_by(Staff.employee_id))).scalars().all())
        load: dict[uuid.UUID, int] = defaultdict(int)
        for sid_, n in (
            await self.db.execute(
                select(InvigilationDuty.staff_id, func.count())
                .where(InvigilationDuty.exam_session_id == s.id)
                .group_by(InvigilationDuty.staff_id)
            )
        ).all():
            load[sid_] = int(n)
        rates = await self.rates()
        out = RosterSummary(
            slots=len({(p.exam_date, p.session_slot) for p in plans}), rooms=len(plans), dry_run=body.dry_run
        )
        for n, plan in enumerate(plans):
            teaching_here = set(
                (
                    await self.db.execute(
                        select(CourseOfferingFaculty.staff_id)
                        .join(CourseOffering, CourseOffering.id == CourseOfferingFaculty.offering_id)
                        .join(ExamPaper, ExamPaper.course_id == CourseOffering.course_id)
                        .where(
                            ExamPaper.exam_session_id == s.id,
                            ExamPaper.exam_date == plan.exam_date,
                            ExamPaper.session_slot == plan.session_slot,
                            CourseOffering.term_id == s.term_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            have = (
                await self.db.execute(
                    select(InvigilationDuty.role, func.count())
                    .where(
                        InvigilationDuty.exam_session_id == s.id,
                        InvigilationDuty.exam_date == plan.exam_date,
                        InvigilationDuty.session_slot == plan.session_slot,
                        InvigilationDuty.room_id == plan.room_id,
                    )
                    .group_by(InvigilationDuty.role)
                )
            ).all()
            have_by = {r: int(c) for r, c in have}
            for role, want in body.roles_per_room.items():
                need = max(0, want - have_by.get(role, 0))
                for _ in range(need):
                    pick = None
                    for st in sorted(pool, key=lambda x: (load[x.id], x.employee_id)):
                        if load[st.id] >= body.max_duties_per_staff or st.id in teaching_here:
                            continue
                        if await self._busy(st.id, plan.exam_date, plan.session_slot, s.id):
                            continue
                        pick = st
                        break
                    if pick is None:
                        out.unfilled.append(
                            {
                                "date": plan.exam_date.isoformat(),
                                "slot": plan.session_slot,
                                "room_id": str(plan.room_id),
                                "role": role,
                            }
                        )
                        continue
                    load[pick.id] += 1
                    out.duties += 1
                    if not body.dry_run:
                        self.db.add(
                            InvigilationDuty(
                                institution_id=self.inst,
                                exam_session_id=s.id,
                                exam_date=plan.exam_date,
                                session_slot=plan.session_slot,
                                room_id=plan.room_id,
                                staff_id=pick.id,
                                role=role,
                                status="assigned",
                                remuneration_paise=int(rates.get(role, 0)),
                            )
                        )
                        await self.db.flush()
            if progress and n % 10 == 0:
                await progress(int(n * 100 / max(1, len(plans))), f"{n}/{len(plans)}")
        out.per_staff_max = max(load.values()) if load else 0
        if not body.dry_run:
            await self._audit(
                "invigilation_auto", "exam_session", s.id, None, out.model_dump(mode="json", exclude={"unfilled"})
            )
            await self._emit(
                "exams.duty_assigned", {"exam_session_id": str(s.id), "duties": out.duties}, "exam_session", s.id
            )
        return out

    async def roster(self, sid: uuid.UUID, exam_date: Any, room_id: uuid.UUID | None) -> list[DutyResponse]:
        s = await self.session(sid)
        q = select(InvigilationDuty).where(InvigilationDuty.exam_session_id == s.id)
        if exam_date:
            q = q.where(InvigilationDuty.exam_date == exam_date)
        if room_id:
            q = q.where(InvigilationDuty.room_id == room_id)
        return await self.outs(
            list(
                (await self.db.execute(q.order_by(InvigilationDuty.exam_date, InvigilationDuty.session_slot)))
                .scalars()
                .all()
            )
        )

    async def mine(self) -> list[DutyResponse]:
        rows = (
            (
                await self.db.execute(
                    select(InvigilationDuty)
                    .where(
                        InvigilationDuty.institution_id == self.inst,
                        InvigilationDuty.staff_id.in_(staff_ids(self.principal)),
                    )
                    .order_by(InvigilationDuty.exam_date)
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows))

    async def create(self, body: DutyCreate) -> DutyResponse:
        _office(self)
        await self.session(body.exam_session_id, write=True)
        busy = await self._busy(body.staff_id, body.exam_date, body.session_slot, body.exam_session_id)
        if busy:
            raise rule(f"Staff member {busy}", "STAFF_BUSY")
        d = InvigilationDuty(
            institution_id=self.inst,
            status="assigned",
            remuneration_paise=int((await self.rates()).get(body.role, 0)),
            **body.model_dump(),
        )
        self.db.add(d)
        await self.db.flush()
        return (await self.outs([d]))[0]

    async def _duty(self, did: uuid.UUID) -> InvigilationDuty:
        d = (
            await self.db.execute(
                select(InvigilationDuty)
                .where(InvigilationDuty.id == did, InvigilationDuty.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if d is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Duty not found")
        return d

    async def update(self, did: uuid.UUID, body: DutyUpdate) -> DutyResponse:
        _office(self)
        d = await self._duty(did)
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(d, k, v)
        await self.db.flush()
        return (await self.outs([d]))[0]

    async def delete(self, did: uuid.UUID) -> None:
        _office(self)
        await self.db.delete(await self._duty(did))
        await self.db.flush()

    async def swap_request(self, did: uuid.UUID, body: SwapRequest) -> DutyResponse:
        d = await self._duty(did)
        if d.staff_id not in set((await self.db.execute(staff_ids(self.principal))).scalars().all()):
            raise APIError(404, ErrorCode.NOT_FOUND, "Duty not found")
        if d.status not in ("assigned", "accepted"):
            raise APIError(409, ErrorCode.CONFLICT, f"Duty is {d.status}")
        d.status, d.swap_with_staff_id = "swap_requested", body.with_staff_id
        await self.db.flush()
        await self._audit(
            "swap_request",
            "invigilation_duty",
            d.id,
            None,
            {"with": str(body.with_staff_id) if body.with_staff_id else None, "reason": body.reason},
        )
        return (await self.outs([d]))[0]

    async def swap_decide(self, did: uuid.UUID, approve: bool, with_staff_id: uuid.UUID | None = None) -> DutyResponse:
        _office(self)
        d = await self._duty(did)
        if d.status != "swap_requested":
            raise APIError(409, ErrorCode.CONFLICT, f"Duty is {d.status}")
        if not approve:
            d.status, d.swap_with_staff_id = "assigned", None
            await self.db.flush()
            return (await self.outs([d]))[0]
        other = with_staff_id or d.swap_with_staff_id
        if other is None:
            raise APIError(422, ErrorCode.VALIDATION, "with_staff_id is required")
        busy = await self._busy(other, d.exam_date, d.session_slot, d.exam_session_id)
        if busy:
            raise rule(f"Replacement {busy}", "STAFF_BUSY")
        old_staff = d.staff_id
        d.staff_id, d.status, d.swap_with_staff_id = other, "swapped", old_staff
        await self.db.flush()
        await self._audit("swap", "invigilation_duty", d.id, {"staff_id": str(old_staff)}, {"staff_id": str(other)})
        await self._emit("exams.duty_swapped", {"duty_id": str(d.id)}, "invigilation_duty", d.id)
        return (await self.outs([d]))[0]

    async def mark_absent(self, did: uuid.UUID) -> DutyResponse:
        _office(self)
        d = await self._duty(did)
        d.status, d.remuneration_paise = "absent", 0
        await self.db.flush()
        await self._audit("duty_absent", "invigilation_duty", d.id, None, {"status": "absent"})
        return (await self.outs([d]))[0]

    async def letter_pdf(self, did: uuid.UUID) -> bytes:
        from app.utils.pdf import render_pdf

        d = (await self.outs([await self._duty(did)]))[0]
        s = await self.session(d.exam_session_id)
        lines = [
            (await self.institution()).name,
            "INVIGILATION DUTY ORDER",
            f"Session: {s.name}",
            f"To: {d.staff_name}",
            f"Date: {d.exam_date}  Slot: {d.session_slot}  Room: {d.room_code or 'TBA'}",
            f"Role: {d.role}",
            "",
            "Report 30 minutes before the start of the examination.",
        ]
        return render_pdf(
            "<html><body>" + "".join(f"<p>{x}</p>" for x in lines) + "</body></html>", lines, title="Duty order"
        )

    async def remuneration(self, sid: uuid.UUID) -> RemunerationSummary:
        s = await self.session(sid)
        out = RemunerationSummary()
        rows = (
            (
                await self.db.execute(
                    select(InvigilationDuty).where(
                        InvigilationDuty.exam_session_id == s.id, InvigilationDuty.status != "absent"
                    )
                )
            )
            .scalars()
            .all()
        )
        per: dict[uuid.UUID, int] = defaultdict(int)
        for d in rows:
            out.by_role[d.role] = out.by_role.get(d.role, 0) + int(d.remuneration_paise or 0)
            per[d.staff_id] += int(d.remuneration_paise or 0)
        names = {
            x.id: f"{x.first_name} {x.last_name or ''}".strip()
            for x in (await self.db.execute(select(Staff).where(Staff.id.in_(list(per) or [uuid.uuid4()])))).scalars()
        }
        out.by_staff = [
            {"staff_id": str(k), "name": names.get(k), "amount_paise": v}
            for k, v in sorted(per.items(), key=lambda x: -x[1])
        ]
        out.qp = int(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(func.coalesce(func.sum(QuestionPaperAssignment.remuneration_paise), 0))
                    .join(ExamPaper, ExamPaper.id == QuestionPaperAssignment.exam_paper_id)
                    .where(
                        ExamPaper.exam_session_id == s.id,
                        QuestionPaperAssignment.status.in_(
                            ("submitted", "scrutinised", "approved", "selected", "printed")
                        ),
                    )
                )
            ).scalar_one()
        )
        out.total_paise = sum(out.by_role.values()) + out.qp
        return out


class QpService(ExamBase):
    async def outs(self, rows: list[QuestionPaperAssignment]) -> list[QpAssignmentResponse]:
        papers = {
            p.id: (p, c)
            for p, c in (
                await self.db.execute(
                    select(ExamPaper, Course)
                    .join(Course, Course.id == ExamPaper.course_id)
                    .where(ExamPaper.id.in_([r.exam_paper_id for r in rows] or [uuid.uuid4()]))
                )
            ).all()
        }
        staff = {
            s.id: f"{s.first_name} {s.last_name or ''}".strip()
            for s in (
                await self.db.execute(
                    select(Staff).where(
                        Staff.id.in_([r.setter_staff_id for r in rows if r.setter_staff_id] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        out = []
        for r in rows:
            o = QpAssignmentResponse.model_validate(r)
            pc = papers.get(r.exam_paper_id)
            o.paper_code, o.course_code = (pc[0].paper_code, pc[1].code) if pc else (None, None)
            o.setter_name = staff.get(r.setter_staff_id) if r.setter_staff_id else (r.external_setter or {}).get("name")
            o.has_file = bool(r.file_key_encrypted)
            o.due_at = (r.external_setter or {}).get("_due_at")
            out.append(o)
        return out

    async def _assignment(self, aid: uuid.UUID, *, for_update: bool = True) -> QuestionPaperAssignment:
        q = select(QuestionPaperAssignment).where(
            QuestionPaperAssignment.id == aid,
            QuestionPaperAssignment.institution_id == self.inst,
            qp_predicate(self.principal),
        )
        if for_update:
            q = q.with_for_update()
        a = (await self.db.execute(q)).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "QP assignment not found")
        return a

    async def for_paper(self, pid: uuid.UUID) -> list[QpAssignmentResponse]:
        p, _ = await self.paper(pid)
        rows = (
            (
                await self.db.execute(
                    select(QuestionPaperAssignment)
                    .where(QuestionPaperAssignment.exam_paper_id == p.id, qp_predicate(self.principal))
                    .order_by(QuestionPaperAssignment.set_label)
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows))

    async def mine(self) -> list[QpAssignmentResponse]:
        rows = (
            (
                await self.db.execute(
                    select(QuestionPaperAssignment).where(
                        QuestionPaperAssignment.institution_id == self.inst,
                        or_(
                            QuestionPaperAssignment.setter_staff_id.in_(staff_ids(self.principal)),
                            QuestionPaperAssignment.external_setter["user_id"].astext == str(self.actor_id),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows))

    async def create(self, pid: uuid.UUID, body: QpAssignmentCreate) -> QpAssignmentResponse:
        _office(self)
        p, s = await self.paper(pid)
        if s.is_locked:
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The exam session is locked")
        if not body.setter_staff_id and not body.external_setter:
            raise APIError(422, ErrorCode.VALIDATION, "setter_staff_id or external_setter is required")
        if (
            await self.db.execute(
                select(QuestionPaperAssignment.id).where(
                    QuestionPaperAssignment.exam_paper_id == p.id, QuestionPaperAssignment.set_label == body.set_label
                )
            )
        ).first():
            raise APIError(409, ErrorCode.CONFLICT, f"Set {body.set_label} is already assigned")
        ext = dict(body.external_setter or {}) or None
        if ext is not None and body.due_at:
            ext["_due_at"] = body.due_at.isoformat()
        a = QuestionPaperAssignment(
            institution_id=self.inst,
            exam_paper_id=p.id,
            setter_staff_id=body.setter_staff_id,
            external_setter=ext,
            set_label=body.set_label,
            blueprint_id=body.blueprint_id,
            status="invited",
            remuneration_paise=body.remuneration_paise,
        )
        self.db.add(a)
        await self.db.flush()
        await self._audit(
            "qp_assign",
            "question_paper_assignment",
            a.id,
            None,
            {"paper": p.paper_code, "set": body.set_label, "external": bool(ext)},
        )
        return (await self.outs([a]))[0]

    async def update(self, aid: uuid.UUID, body: QpAssignmentCreate) -> QpAssignmentResponse:
        _office(self)
        a = await self._assignment(aid)
        for k, v in body.model_dump(exclude_none=True, exclude={"due_at"}).items():
            setattr(a, k, v)
        await self.db.flush()
        return (await self.outs([a]))[0]

    def _is_setter(self, a: QuestionPaperAssignment, mine: set[uuid.UUID]) -> bool:
        return (a.setter_staff_id in mine) or ((a.external_setter or {}).get("user_id") == str(self.actor_id))

    async def upload(self, aid: uuid.UUID, content: bytes, filename: str) -> QpAssignmentResponse:
        from app.core.files import build_key, storage
        from app.core.security import encrypt_secret

        a = await self._assignment(aid)
        mine = set((await self.db.execute(staff_ids(self.principal))).scalars().all())
        if not self._is_setter(a, mine) and not self.can("exams", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the setter may upload this paper")
        if a.status in ("selected", "printed"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"Set is {a.status}")
        p, s = await self.paper(a.exam_paper_id)
        key = build_key(self.inst, f"exams/qp/{s.id}/{p.id}", f"{a.set_label}-{uuid.uuid4().hex[:8]}.bin")
        await storage.put(key, encrypt_secret(base64.b64encode(content).decode()), "application/octet-stream")
        a.file_key_encrypted = base64.b64encode(encrypt_secret(key)).decode()
        a.status, a.submitted_at = "submitted", now_utc()
        await self.db.flush()
        await self._audit(
            "qp_upload", "question_paper_assignment", a.id, None, {"filename": filename, "bytes": len(content)}
        )
        await self._emit("exams.qp_submitted", {"assignment_id": str(a.id)}, "question_paper_assignment", a.id)
        return (await self.outs([a]))[0]

    async def generate_from_blueprint(self, aid: uuid.UUID) -> QpAssignmentResponse:
        from app.schemas.content import PaperGenerateRequest
        from app.services.assessment.content_service import ContentService

        a = await self._assignment(aid)
        if not a.blueprint_id:
            raise rule("No blueprint on this assignment", "NO_BLUEPRINT", 422)
        content = ContentService(self.db, self.principal, self.request, self.inst)
        paper = await content.generate(
            PaperGenerateRequest(blueprint_id=a.blueprint_id, purpose="ese", title=f"ESE set {a.set_label}")
        )
        await content.freeze(paper.id)
        pdf, _ = await content.print_pdf(paper.id, "both")
        out = await self.upload(a.id, pdf, f"generated-{paper.id}.pdf")
        await self._audit("qp_generate", "question_paper_assignment", a.id, None, {"question_paper_id": str(paper.id)})
        return out

    async def scrutinise(self, aid: uuid.UUID, body: QpScrutinyRequest) -> QpAssignmentResponse:
        _office(self)
        a = await self._assignment(aid)
        if a.status != "submitted":
            raise APIError(409, ErrorCode.CONFLICT, f"Set is {a.status}")
        a.status = "approved" if body.decision == "approve" else "rejected"
        a.scrutiny_by, a.scrutiny_remarks = self.actor_id, body.remarks
        await self.db.flush()
        await self._audit("qp_scrutiny", "question_paper_assignment", a.id, None, body.model_dump())
        return (await self.outs([a]))[0]

    async def select_set(self, aid: uuid.UUID) -> list[QpAssignmentResponse]:
        a = await self._assignment(aid)
        if a.status != "approved":
            raise rule("Only an approved set can be selected", "NOT_APPROVED")
        for other in (
            await self.db.execute(
                select(QuestionPaperAssignment)
                .where(QuestionPaperAssignment.exam_paper_id == a.exam_paper_id, QuestionPaperAssignment.id != a.id)
                .with_for_update()
            )
        ).scalars():
            if other.status not in ("rejected",):
                other.status = "rejected"
        a.status = "selected"
        p = (
            await self.db.execute(select(ExamPaper).where(ExamPaper.id == a.exam_paper_id).with_for_update())
        ).scalar_one()
        if p.status == "planned":
            p.status = "qp_ready"
        await self.db.flush()
        await self._audit("qp_select", "question_paper_assignment", a.id, None, {"set": a.set_label})
        await self._emit("exams.qp_selected", {"exam_paper_id": str(p.id), "set": a.set_label}, "exam_paper", p.id)
        return await self.for_paper(p.id)

    async def _content(self, a: QuestionPaperAssignment) -> bytes:
        from app.core.files import storage
        from app.core.security import decrypt_secret

        if not a.file_key_encrypted:
            raise rule("Nothing uploaded", "NO_FILE", 404)
        key = decrypt_secret(base64.b64decode(a.file_key_encrypted))
        blob = await storage.get(key)
        await self._audit("qp_access", "question_paper_assignment", a.id, None, {"by": str(self.actor_id)})
        return base64.b64decode(decrypt_secret(blob))

    async def print(self, aid: uuid.UUID, body: QpPrintRequest) -> QpPrintResponse:
        from app.db.session import redis_client

        a = await self._assignment(aid)
        if a.status not in ("selected", "printed"):
            raise rule("Select the set before printing", "NOT_SELECTED")
        p, _ = await self.paper(a.exam_paper_id)
        inst = await self.institution()
        who = getattr(self.principal, "username", None) or str(self.actor_id)
        mark = body.watermark_text or f"{inst.name} • {p.paper_code} • {who} • {now_utc():%Y-%m-%d %H:%M}"
        self.db.add(
            QuestionPaperPrintLog(
                institution_id=self.inst,
                exam_paper_id=p.id,
                set_label=a.set_label,
                printed_by=self.actor_id or uuid.UUID(int=0),
                copies=body.copies,
                watermark_text=mark[:120],
                ip=self.request.client.host if self.request and self.request.client else None,
            )
        )
        a.status = "printed"
        await self.db.flush()
        token = secrets.token_urlsafe(24)
        await redis_client.set(f"qp:dl:{token}", f"{self.inst}|{a.id}|{mark[:120]}", ex=600)
        await self._audit(
            "qp_print", "question_paper_assignment", a.id, None, {"copies": body.copies, "watermark": mark[:120]}
        )
        await self._emit("exams.qp_printed", {"exam_paper_id": str(p.id), "copies": body.copies}, "exam_paper", p.id)
        return QpPrintResponse(download_token=token, copies=body.copies)

    async def download(self, token: str) -> bytes:
        from app.db.session import redis_client
        from app.utils.pdf import simple_pdf

        raw = await redis_client.getdel(f"qp:dl:{token}")
        if not raw:
            # 410 is not in the API's allowed status codes — a used / expired token answers 409 TOKEN_USED
            raise APIError(409, ErrorCode.CONFLICT, "The download link was used or has expired", {"code": "TOKEN_USED"})
        _, aid, mark = raw.split("|", 2)
        a = await self._assignment(uuid.UUID(aid), for_update=False)
        content = await self._content(a)
        if content.startswith(b"%PDF"):
            # burn the watermark as the first page of the print bundle (fallback writer cannot overlay pages)
            return simple_pdf([f"WATERMARK: {mark}", "", "Question paper follows."], "Print bundle") + content
        return simple_pdf([f"WATERMARK: {mark}"], "Print bundle") + content


class ConductService(ExamBase):
    async def roster(self, pid: uuid.UUID, room_id: uuid.UUID | None) -> list[HallAttendanceRowOut]:
        p, _ = await self.paper(pid)
        q = (
            select(ExamRegistrationItem, ExamRegistration, Student, ExamAttendance, ExamSeatAllocation, Room)
            .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
            .join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == ExamRegistration.student_program_enrollment_id
            )
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .outerjoin(ExamAttendance, ExamAttendance.exam_registration_item_id == ExamRegistrationItem.id)
            .outerjoin(ExamSeatAllocation, ExamSeatAllocation.exam_registration_item_id == ExamRegistrationItem.id)
            .outerjoin(ExamSeatingPlan, ExamSeatingPlan.id == ExamSeatAllocation.seating_plan_id)
            .outerjoin(Room, Room.id == ExamSeatingPlan.room_id)
            .where(
                ExamRegistrationItem.exam_paper_id == p.id,
                ExamRegistration.status == "confirmed",
                ExamRegistrationItem.status != "cancelled",
            )
        )
        if room_id:
            q = q.where(ExamSeatingPlan.room_id == room_id)
        return [
            HallAttendanceRowOut(
                exam_registration_item_id=it.id,
                hall_ticket_number=reg.hall_ticket_number,
                registration_number=st.registration_number,
                student_name=student_name(st),
                room_code=room.code if room else None,
                seat_number=seat.seat_number if seat else None,
                status=att.status if att else None,
                answer_booklet_number=att.answer_booklet_number if att else None,
                face_match_score=float(att.face_match_score) if att and att.face_match_score is not None else None,
            )
            for it, reg, st, att, seat, room in (
                await self.db.execute(
                    q.order_by(Room.code, ExamSeatAllocation.seat_number, ExamRegistration.hall_ticket_number)
                )
            ).all()
        ]

    async def mark(self, pid: uuid.UUID, body: HallAttendanceMark) -> list[HallAttendanceRowOut]:
        p, s = await self.paper(pid, for_update=True)
        if s.is_locked:
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The exam session is locked")
        valid = {r.exam_registration_item_id for r in await self.roster(p.id, None)}
        booklets = [r.answer_booklet_number for r in body.items if r.answer_booklet_number]
        if len(booklets) != len(set(booklets)):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Duplicate answer booklet numbers in the batch",
                {"code": "DUPLICATE_BOOKLET"},
            )
        if booklets:
            taken = (
                (
                    await self.db.execute(
                        select(ExamAttendance.answer_booklet_number)
                        .join(ExamRegistrationItem, ExamRegistrationItem.id == ExamAttendance.exam_registration_item_id)
                        .where(
                            ExamRegistrationItem.exam_paper_id == p.id,
                            ExamAttendance.answer_booklet_number.in_(booklets),
                            ExamAttendance.exam_registration_item_id.notin_(
                                [r.exam_registration_item_id for r in body.items]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if taken:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "Booklet numbers already used for this paper",
                    {"code": "DUPLICATE_BOOKLET", "booklets": list(taken)},
                )
        face_on = False
        from app.core.features import is_enabled

        face_on = await is_enabled(self.inst, "exams.face_verification")
        for r in body.items:
            if r.exam_registration_item_id not in valid:
                raise APIError(
                    422, ErrorCode.VALIDATION, f"Item {r.exam_registration_item_id} is not on this paper's roster"
                )
            score = r.face_match_score
            if face_on and score is None and r.status == "present":
                from app.integrations.registry import get_adapter

                res = await get_adapter("face_verification", "mock").send(item=str(r.exam_registration_item_id))
                score = 90.0 if res.get("status") == "sent" else None
            att = (
                await self.db.execute(
                    select(ExamAttendance)
                    .where(ExamAttendance.exam_registration_item_id == r.exam_registration_item_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if att is None:
                att = ExamAttendance(
                    institution_id=self.inst, exam_registration_item_id=r.exam_registration_item_id, status=r.status
                )
                self.db.add(att)
            att.status, att.answer_booklet_number, att.marked_by, att.marked_at = (
                r.status,
                r.answer_booklet_number,
                self.actor_id,
                now_utc(),
            )
            if score is not None:
                from decimal import Decimal

                att.face_match_score = Decimal(str(score))
            it = (
                await self.db.execute(
                    select(ExamRegistrationItem)
                    .where(ExamRegistrationItem.id == r.exam_registration_item_id)
                    .with_for_update()
                )
            ).scalar_one()
            it.status = {"present": "appeared", "late": "appeared", "absent": "absent", "malpractice": "malpractice"}[
                r.status
            ]
        if p.status in ("planned", "qp_ready"):
            p.status = "conducted"
        await self.db.flush()
        await self._audit("hall_attendance", "exam_paper", p.id, None, {"rows": len(body.items)})
        await self._emit(
            "exams.hall_attendance_marked", {"exam_paper_id": str(p.id), "rows": len(body.items)}, "exam_paper", p.id
        )
        return await self.roster(p.id, None)

    async def report_malpractice(self, pid: uuid.UUID, body: MalpracticeReportCreate) -> MalpracticeOut:
        p, s = await self.paper(pid)
        it = (
            await self.db.execute(
                select(ExamRegistrationItem)
                .where(
                    ExamRegistrationItem.id == body.exam_registration_item_id,
                    ExamRegistrationItem.exam_paper_id == p.id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if it is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Registration item not on this paper")
        n = (
            await self.db.execute(
                select(func.count()).select_from(MalpracticeCase).where(MalpracticeCase.institution_id == self.inst)
            )
        ).scalar_one()
        case = MalpracticeCase(
            institution_id=self.inst,
            exam_session_id=s.id,
            exam_registration_item_id=it.id,
            case_number=f"MAL/{now_utc():%Y}/{int(n) + 1:05d}",
            reported_by=self.actor_id or uuid.UUID(int=0),
            category=body.category,
            evidence=body.evidence,
            invigilator_report=body.invigilator_report,
            status="reported",
        )
        self.db.add(case)
        it.status = "malpractice"
        att = (
            await self.db.execute(select(ExamAttendance).where(ExamAttendance.exam_registration_item_id == it.id))
        ).scalar_one_or_none()
        if att is None:
            self.db.add(
                ExamAttendance(
                    institution_id=self.inst,
                    exam_registration_item_id=it.id,
                    status="malpractice",
                    marked_by=self.actor_id,
                )
            )
        else:
            att.status = "malpractice"
        await self.db.flush()
        await self._audit(
            "malpractice_report", "malpractice_case", case.id, None, {"category": body.category, "paper": p.paper_code}
        )
        await self._emit(
            "exams.malpractice_reported",
            {"malpractice_case_id": str(case.id), "exam_registration_item_id": str(it.id)},
            "malpractice_case",
            case.id,
        )
        return MalpracticeOut.model_validate(case)

    async def attendance_pdf(self, pid: uuid.UUID) -> bytes:
        from app.utils.pdf import render_pdf

        p, s = await self.paper(pid)
        rows = await self.roster(p.id, None)
        lines = [f"HALL ATTENDANCE — {s.name} — {p.paper_code} {p.exam_date} {p.session_slot}", ""] + [
            f"{r.room_code or '':8s} {r.seat_number or '':6s} {r.hall_ticket_number or '':14s} {(r.student_name or '')[:30]:30s} {r.status or '________'} {r.answer_booklet_number or ''}"
            for r in rows
        ]
        return render_pdf(
            "<html><body>" + "".join(f"<p>{x}</p>" for x in lines) + "</body></html>", lines, title="Hall attendance"
        )

    async def online_setup(self, pid: uuid.UUID, body: OnlinePaperSetup) -> dict[str, Any]:
        from app.models.lms import Quiz

        p, _ = await self.paper(pid, for_update=True)
        q = (
            await self.db.execute(
                select(Quiz).where(Quiz.id == body.quiz_id, Quiz.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if q is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Quiz not found")
        p.quiz_id, p.paper_type = q.id, "online"
        if body.proctoring:
            q.proctoring = body.proctoring
        if p.exam_date and p.start_time:
            from zoneinfo import ZoneInfo

            start = datetime.combine(p.exam_date, p.start_time, ZoneInfo("Asia/Kolkata")).astimezone(UTC)
            q.starts_at, q.ends_at = start, start + timedelta(minutes=p.duration_minutes or q.duration_minutes)
        q.status = "published"
        await self.db.flush()
        await self._audit("online_setup", "exam_paper", p.id, None, {"quiz_id": str(q.id)})
        return {
            "exam_paper_id": str(p.id),
            "quiz_id": str(q.id),
            "starts_at": q.starts_at.isoformat() if q.starts_at else None,
            "ends_at": q.ends_at.isoformat() if q.ends_at else None,
        }

    async def online_access(self, pid: uuid.UUID) -> dict[str, Any]:
        from app.models.lms import Quiz
        from app.repositories.fee_scope import own_enrollment_ids

        p, _ = await self.paper(pid)
        if not p.quiz_id:
            raise rule("Not an online paper", "NOT_ONLINE", 404)
        ok = (
            await self.db.execute(
                select(ExamRegistrationItem.id)
                .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
                .where(
                    ExamRegistrationItem.exam_paper_id == p.id,
                    ExamRegistration.status == "confirmed",
                    ExamRegistrationItem.eligibility.in_(("eligible", "condoned")),
                    ExamRegistration.student_program_enrollment_id.in_(
                        own_enrollment_ids(self.principal, advisees=False)
                    ),
                )
            )
        ).first()
        if not ok:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "You are not registered (or not eligible) for this paper")
        q = (await self.db.execute(select(Quiz).where(Quiz.id == p.quiz_id))).scalar_one()
        now = now_utc()
        if (q.starts_at and now < q.starts_at) or (q.ends_at and now > q.ends_at):
            raise APIError(403, ErrorCode.RULE_VIOLATION, "Outside the paper window", {"code": "WINDOW_CLOSED"})
        return {
            "quiz_id": str(q.id),
            "offering_id": str(q.offering_id),
            "ends_at": q.ends_at.isoformat() if q.ends_at else None,
        }
