"""Malpractice lifecycle — Prompts/16 §16.6 ``malpractice_service`` ({results.malpractice}).

Cases come from the Phase 14 hall report (``reported``) or are registered here (item → ``malpractice``); while a case
is pending (reported / under inquiry / hearing / appealed) the item's result computes as ``withheld``
(``MALPRACTICE_PENDING``). Inquiry assigns a committee (``committees``; members read the case) and a hearing; the
notice goes to the student and guardians; the student files a statement from the portal.

Decision (``exams:manage`` — the COE — or the chair of the assigned committee): ``none`` / ``warning`` release the
item, ``cancel_paper`` → item ``MP`` (arrear opened at publication), ``cancel_session`` → every item of the
registration ``MP``, ``debar_terms`` → ``debar_until_term_id`` = the N-th term after the session's term, an ``exam``
hold (source ``malpractice_case``) and later sessions' registrations up to that term ``debarred``, ``expel`` →
enrolment ``expelled`` + an ``all`` hold. When the session has published results a correction run is computed for the
affected rows (the COE publishes it). Appeal (student, within ``exams.malpractice_appeal_days``, default 30) →
``appealed`` → committee / COE ``uphold`` or ``modify`` (previous effects undone, the new punishment applied) →
``appeal_decided`` → ``closed``. Timeline = the case's audit rows.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select, text

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicTerm
from app.models.exams import ExamRegistration, ExamRegistrationItem, ExamSession, MalpracticeCase
from app.models.hr import Staff
from app.models.post_result import Committee, CommitteeMember
from app.models.results import ResultProcessingRun
from app.models.students import StudentHold
from app.repositories.fee_scope import own_enrollment_ids
from app.schemas.post_result import (
    AppealCreate,
    AppealDecision,
    InquiryUpdate,
    MalpracticeCaseCreate,
    MalpracticeCaseResponse,
    MalpracticeDecision,
    StudentStatementSubmit,
)
from app.services.exams.common import now_utc, rule
from app.services.post_result.common import ItemContext, PostResultBase


def committee_ids_of(p: Any) -> Any:
    return select(CommitteeMember.committee_id).where(
        or_(
            CommitteeMember.user_id == p.id,
            CommitteeMember.staff_id.in_(select(Staff.id).where(Staff.user_id == p.id)),
        )
    )


class MalpracticeService(PostResultBase):
    audit_module = "exams"

    def _office(self) -> bool:
        return any(self.can(m, a) for m, a in (("exams", "manage"), ("exams", "view_all"), ("results", "view_all")))

    def _predicate(self) -> Any:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False) or self._office():
            return MalpracticeCase.institution_id == self.inst
        own_items = (
            select(ExamRegistrationItem.id)
            .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
            .where(ExamRegistration.student_program_enrollment_id.in_(own_enrollment_ids(p, advisees=False)))
        )
        return or_(
            MalpracticeCase.exam_registration_item_id.in_(own_items),
            MalpracticeCase.committee_id.in_(committee_ids_of(p)),
            MalpracticeCase.reported_by == p.id,
        )

    async def case(self, cid: uuid.UUID, *, for_update: bool = False) -> MalpracticeCase:
        q = select(MalpracticeCase).where(MalpracticeCase.id == cid, MalpracticeCase.institution_id == self.inst, self._predicate())
        if for_update:
            q = q.with_for_update()
        c = (await self.db.execute(q)).scalar_one_or_none()
        if c is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Case not found")
        return c

    async def _ctx(self, c: MalpracticeCase) -> ItemContext:
        return await self.item_context(c.exam_registration_item_id)

    async def out(self, c: MalpracticeCase, run_id: uuid.UUID | None = None, *, timeline: bool = False) -> MalpracticeCaseResponse:
        o = MalpracticeCaseResponse.model_validate(c, from_attributes=True)
        try:
            ctx = await self._ctx(c)
            o.student_name, o.registration_number, o.course_code = ctx.student_name, ctx.student.registration_number, ctx.course.code
        except APIError:
            pass
        if timeline:
            rows = (
                await self.db.execute(
                    text(
                        "SELECT action, occurred_at, new_values FROM audit_logs WHERE record_type = 'malpractice_case' "
                        "AND record_id = CAST(:r AS uuid) ORDER BY occurred_at"
                    ),
                    {"r": str(c.id)},
                )
            ).all()
            o.timeline = [{"action": a, "at": at.isoformat(), "detail": nv} for a, at, nv in rows]
        o.run_id = run_id
        return o

    async def list_cases(self, session_id: uuid.UUID | None, status: str | None) -> list[MalpracticeCaseResponse]:
        q = select(MalpracticeCase).where(MalpracticeCase.institution_id == self.inst, self._predicate())
        if session_id:
            q = q.where(MalpracticeCase.exam_session_id == session_id)
        if status:
            q = q.where(MalpracticeCase.status == status)
        return [await self.out(c) for c in (await self.db.execute(q.order_by(MalpracticeCase.reported_at.desc()))).scalars()]

    async def my_cases(self) -> list[MalpracticeCaseResponse]:
        own_items = (
            select(ExamRegistrationItem.id)
            .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
            .where(ExamRegistration.student_program_enrollment_id.in_(own_enrollment_ids(self.principal, advisees=False)))
        )
        rows = (
            await self.db.execute(
                select(MalpracticeCase).where(MalpracticeCase.exam_registration_item_id.in_(own_items)).order_by(MalpracticeCase.reported_at.desc())
            )
        ).scalars()
        return [await self.out(c, timeline=True) for c in rows]

    async def get(self, cid: uuid.UUID) -> MalpracticeCaseResponse:
        return await self.out(await self.case(cid), timeline=True)

    async def create(self, body: MalpracticeCaseCreate) -> MalpracticeCaseResponse:
        ctx = await self.item_context(body.exam_registration_item_id, for_update=True)
        n = (
            await self.db.execute(select(func.count()).select_from(MalpracticeCase).where(MalpracticeCase.institution_id == self.inst))
        ).scalar_one()
        c = MalpracticeCase(
            institution_id=self.inst,
            exam_session_id=ctx.session.id,
            exam_registration_item_id=ctx.item.id,
            case_number=f"MAL/{now_utc():%Y}/{int(n) + 1:05d}",
            reported_by=self.actor_id or uuid.UUID(int=0),
            category=body.category,
            evidence=body.evidence,
            invigilator_report=body.invigilator_report,
            status="reported",
        )
        self.db.add(c)
        ctx.item.status = "malpractice"
        await self.db.flush()
        await self._audit("malpractice_register", "malpractice_case", c.id, None, {"case": c.case_number, "category": c.category})
        await self._emit("malpractice.registered", {"case_id": str(c.id)}, "malpractice_case", c.id)
        return await self.out(c)

    async def inquiry(self, cid: uuid.UUID, body: InquiryUpdate) -> MalpracticeCaseResponse:
        c = await self.case(cid, for_update=True)
        if c.status not in ("reported", "under_inquiry", "hearing_scheduled"):
            raise rule(f"A {c.status} case is past the inquiry", "INVALID_TRANSITION")
        if body.committee_id:
            com = (
                await self.db.execute(select(Committee).where(Committee.id == body.committee_id, Committee.institution_id == self.inst))
            ).scalar_one_or_none()
            if com is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Committee not found")
            c.committee_id = com.id
        if body.hearing_at:
            c.hearing_at = body.hearing_at
        c.status = "hearing_scheduled" if c.hearing_at else "under_inquiry"
        if body.invalidate_paper:
            ctx = await self._ctx(c)
            ctx.item.status = "malpractice"
        await self.db.flush()
        await self._audit("malpractice_inquiry", "malpractice_case", c.id, None, {"committee_id": str(c.committee_id) if c.committee_id else None, "hearing_at": c.hearing_at.isoformat() if c.hearing_at else None})
        if body.hearing_at:
            await self._emit("malpractice.hearing_scheduled", {"case_id": str(c.id)}, "malpractice_case", c.id)
        return await self.out(c)

    async def hearing(self, cid: uuid.UUID, body: InquiryUpdate) -> MalpracticeCaseResponse:
        if body.hearing_at is None:
            raise APIError(422, ErrorCode.VALIDATION, "hearing_at is required")
        out = await self.inquiry(cid, body)
        await self.notice(cid)
        return out

    async def notice(self, cid: uuid.UUID) -> MalpracticeCaseResponse:
        from app.core.files import build_key, storage
        from app.utils.pdf import simple_pdf

        c = await self.case(cid, for_update=True)
        ctx = await self._ctx(c)
        lines = [
            f"Malpractice notice — case {c.case_number}",
            f"To: {ctx.student_name} ({ctx.student.registration_number})",
            f"Paper: {ctx.course.code} · {ctx.session.name}",
            f"Category: {c.category}",
            f"Hearing: {c.hearing_at:%Y-%m-%d %H:%M} UTC" if c.hearing_at else "Hearing: to be scheduled",
            "You may submit a written statement through the student portal before the hearing.",
        ]
        key = build_key(self.inst, "malpractice/notices", f"{c.case_number.replace('/', '-')}.pdf")
        await storage.put(key, simple_pdf(lines, title="Malpractice notice"), "application/pdf")
        c.evidence = [*(c.evidence or []), {"type": "notice", "key": key, "at": now_utc().isoformat()}]
        if c.status == "reported":
            c.status = "under_inquiry"
        await self.db.flush()
        if ctx.student.user_id:
            await self._notify(
                "results.malpractice_notice",
                [ctx.student.user_id],
                {"case": c.case_number, "course": ctx.course.code, "hearing": c.hearing_at.strftime("%Y-%m-%d %H:%M") if c.hearing_at else "to be scheduled"},
                guardians=True,
            )
        await self._audit("malpractice_notice", "malpractice_case", c.id, None, {"key": key})
        await self._emit("malpractice.notice_sent", {"case_id": str(c.id)}, "malpractice_case", c.id)
        return await self.out(c)

    async def statement(self, cid: uuid.UUID, body: StudentStatementSubmit) -> MalpracticeCaseResponse:
        c = await self.case(cid, for_update=True)
        ctx = await self._ctx(c)
        if not await self.mine(ctx.enrolment.id):
            raise APIError(404, ErrorCode.NOT_FOUND, "Case not found")
        if c.status not in ("reported", "under_inquiry", "hearing_scheduled"):
            raise rule("Statements are accepted until the decision", "INVALID_TRANSITION")
        c.student_statement = body.text
        if body.attachments:
            c.evidence = [*(c.evidence or []), *({"type": "statement_attachment", "key": a} for a in body.attachments)]
        await self.db.flush()
        await self._audit("malpractice_statement", "malpractice_case", c.id, None, {"length": len(body.text)})
        return await self.out(c)

    # ---- decision ----------------------------------------------------------------------------------------------------
    async def _may_decide(self, c: MalpracticeCase) -> None:
        if self.can("exams", "manage"):
            return
        if c.committee_id and self.principal is not None:
            chair = (
                await self.db.execute(
                    select(Committee.id).where(
                        Committee.id == c.committee_id,
                        or_(
                            Committee.chair_staff_id.in_(select(Staff.id).where(Staff.user_id == self.principal.id)),
                            Committee.id.in_(
                                select(CommitteeMember.committee_id).where(
                                    CommitteeMember.committee_id == c.committee_id,
                                    CommitteeMember.role.in_(("chair", "chairperson")),
                                    or_(
                                        CommitteeMember.user_id == self.principal.id,
                                        CommitteeMember.staff_id.in_(select(Staff.id).where(Staff.user_id == self.principal.id)),
                                    ),
                                )
                            ),
                        ),
                    )
                )
            ).first()
            if chair:
                return
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "Decided by the controller of examinations or the committee chair")

    async def _debar_term(self, session: ExamSession, terms: int) -> uuid.UUID | None:
        base = (await self.db.execute(select(AcademicTerm).where(AcademicTerm.id == session.term_id))).scalar_one()
        later = list(
            (
                await self.db.execute(
                    select(AcademicTerm.id)
                    .where(
                        AcademicTerm.institution_id == self.inst,
                        AcademicTerm.college_id.is_(base.college_id) if base.college_id is None else AcademicTerm.college_id == base.college_id,
                        AcademicTerm.start_date > base.start_date,
                        AcademicTerm.deleted_at.is_(None),
                    )
                    .order_by(AcademicTerm.start_date)
                    .limit(terms)
                )
            ).scalars()
        )
        return later[-1] if later else base.id

    async def _undo(self, c: MalpracticeCase, ctx: ItemContext) -> None:
        for h in (
            await self.db.execute(
                select(StudentHold).where(
                    StudentHold.source_type == "malpractice_case", StudentHold.source_id == c.id, StudentHold.released_at.is_(None)
                )
            )
        ).scalars():
            h.released_at, h.released_by = now_utc(), self.actor_id or uuid.UUID(int=0)
        if c.punishment == "debar_terms":
            for reg in (
                await self.db.execute(
                    select(ExamRegistration)
                    .join(ExamSession, ExamSession.id == ExamRegistration.exam_session_id)
                    .where(
                        ExamRegistration.student_program_enrollment_id == ctx.enrolment.id,
                        ExamRegistration.status == "debarred",
                        ExamSession.id != c.exam_session_id,
                    )
                )
            ).scalars():
                reg.status = "confirmed" if reg.total_fee_paise == 0 or reg.fee_invoice_id else "draft"
        if c.punishment == "expel" and ctx.enrolment.status == "expelled":
            ctx.enrolment.status = "active"
        if c.punishment in ("cancel_session",):
            for it in (
                await self.db.execute(select(ExamRegistrationItem).where(ExamRegistrationItem.exam_registration_id == ctx.registration.id))
            ).scalars():
                if it.status == "malpractice" and it.id != c.exam_registration_item_id:
                    it.status = "appeared"
        c.debar_until_term_id = None

    async def _apply(self, c: MalpracticeCase, ctx: ItemContext, punishment: str, debar_terms: int | None) -> list[uuid.UUID]:
        from app.services.hold_service import HoldService

        affected = [ctx.course.id]
        holds = HoldService(self.db, self.principal, self.request, self.inst)
        if punishment in ("none", "warning"):
            ctx.item.status = "appeared"
        elif punishment == "cancel_paper":
            ctx.item.status = "malpractice"
        elif punishment == "cancel_session":
            for it in (
                await self.db.execute(select(ExamRegistrationItem).where(ExamRegistrationItem.exam_registration_id == ctx.registration.id))
            ).scalars():
                if it.status != "cancelled":
                    it.status = "malpractice"
                    affected.append(it.course_id)
        elif punishment == "debar_terms":
            ctx.item.status = "malpractice"
            c.debar_until_term_id = await self._debar_term(ctx.session, debar_terms or 1)
            await holds.place_system(ctx.enrolment, "exam", f"Debarred — malpractice case {c.case_number}", "malpractice_case", c.id)
            until = (await self.db.execute(select(AcademicTerm.start_date).where(AcademicTerm.id == c.debar_until_term_id))).scalar_one()
            for reg in (
                await self.db.execute(
                    select(ExamRegistration)
                    .join(ExamSession, ExamSession.id == ExamRegistration.exam_session_id)
                    .join(AcademicTerm, AcademicTerm.id == ExamSession.term_id)
                    .where(
                        ExamRegistration.student_program_enrollment_id == ctx.enrolment.id,
                        ExamSession.id != ctx.session.id,
                        AcademicTerm.start_date <= until,
                        ExamRegistration.status.notin_(("cancelled", "debarred")),
                    )
                )
            ).scalars():
                reg.status = "debarred"
        elif punishment == "expel":
            ctx.item.status = "malpractice"
            ctx.enrolment.status = "expelled"
            await holds.place_system(ctx.enrolment, "all", f"Expelled — malpractice case {c.case_number}", "malpractice_case", c.id)
        c.punishment = punishment
        return affected

    async def _rerun(self, c: MalpracticeCase, ctx: ItemContext, courses: list[uuid.UUID]) -> uuid.UUID | None:
        published = (
            await self.db.execute(
                select(ResultProcessingRun.id).where(
                    ResultProcessingRun.exam_session_id == c.exam_session_id, ResultProcessingRun.status == "published"
                )
            )
        ).first()
        if not published:
            return None
        try:
            return await self.correction_run(c.exam_session_id, [(ctx.enrolment.id, cid) for cid in set(courses)])
        except APIError:
            return None

    async def decide(self, cid: uuid.UUID, body: MalpracticeDecision) -> MalpracticeCaseResponse:
        c = await self.case(cid, for_update=True)
        await self._may_decide(c)
        if c.status not in ("reported", "under_inquiry", "hearing_scheduled"):
            raise rule(f"A {c.status} case cannot be decided", "INVALID_TRANSITION")
        if body.punishment == "debar_terms" and not body.debar_terms:
            raise APIError(422, ErrorCode.VALIDATION, "debar_terms is required for a debarment")
        ctx = await self._ctx(c)
        affected = await self._apply(c, ctx, body.punishment, body.debar_terms)
        c.decision_text, c.decided_by, c.decided_at, c.status = body.decision_text, self.actor_id, now_utc(), "decided"
        await self.db.flush()
        run_id = await self._rerun(c, ctx, affected)
        await self._audit("malpractice_decide", "malpractice_case", c.id, None, {"punishment": c.punishment, "debar_terms": body.debar_terms, "run_id": str(run_id) if run_id else None})
        await self._emit("malpractice.decided", {"case_id": str(c.id), "punishment": c.punishment}, "malpractice_case", c.id)
        if ctx.student.user_id:
            await self._notify(
                "results.malpractice_notice",
                [ctx.student.user_id],
                {"case": c.case_number, "course": ctx.course.code, "hearing": f"decided: {c.punishment}"},
                guardians=True,
            )
        return await self.out(c, run_id, timeline=True)

    async def appeal(self, cid: uuid.UUID, body: AppealCreate) -> MalpracticeCaseResponse:
        from app.core.workflow import engine as workflow_engine

        c = await self.case(cid, for_update=True)
        ctx = await self._ctx(c)
        if not await self.mine(ctx.enrolment.id):
            raise APIError(404, ErrorCode.NOT_FOUND, "Case not found")
        if c.status != "decided" or c.decided_at is None:
            raise rule("Only a decided case can be appealed", "INVALID_TRANSITION")
        days = int(await self.setting("exams", "malpractice_appeal_days") or 30)
        if now_utc() > c.decided_at + timedelta(days=days):
            raise rule(f"The appeal window ({days} days) has closed", "APPEAL_WINDOW_CLOSED")
        c.evidence = [*(c.evidence or []), {"type": "appeal", "grounds": body.grounds, "attachments": body.attachments, "at": now_utc().isoformat()}]
        c.status = "appealed"
        await self.db.flush()
        try:
            await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="malpractice.appeal",
                entity_type="malpractice_case",
                entity_id=c.id,
                started_by=self.actor_id,
                context={"case": c.case_number, "punishment": c.punishment},
                title=f"Malpractice appeal — {c.case_number}",
            )
        except APIError:
            pass  # the appeal is decided from the case page either way
        await self._audit("malpractice_appeal", "malpractice_case", c.id, None, {"grounds": body.grounds[:200]})
        await self._emit("malpractice.appealed", {"case_id": str(c.id)}, "malpractice_case", c.id)
        return await self.out(c, timeline=True)

    async def appeal_decide(self, cid: uuid.UUID, body: AppealDecision) -> MalpracticeCaseResponse:
        c = await self.case(cid, for_update=True)
        await self._may_decide(c)
        if c.status != "appealed":
            raise rule("Only an appealed case can be decided on appeal", "INVALID_TRANSITION")
        ctx = await self._ctx(c)
        run_id = None
        if body.outcome == "modify":
            if body.punishment is None:
                raise APIError(422, ErrorCode.VALIDATION, "The modified punishment is required")
            await self._undo(c, ctx)
            affected = await self._apply(c, ctx, body.punishment, body.debar_terms)
            await self.db.flush()
            run_id = await self._rerun(c, ctx, affected)
        c.status = "appeal_decided"
        c.evidence = [*(c.evidence or []), {"type": "appeal_decision", "outcome": body.outcome, "text": body.decision_text, "at": now_utc().isoformat()}]
        await self.db.flush()
        await self._audit("malpractice_appeal_decide", "malpractice_case", c.id, None, {"outcome": body.outcome, "punishment": c.punishment})
        await self._emit("malpractice.appeal_decided", {"case_id": str(c.id), "outcome": body.outcome}, "malpractice_case", c.id)
        return await self.out(c, run_id, timeline=True)

    async def close(self, cid: uuid.UUID) -> MalpracticeCaseResponse:
        c = await self.case(cid, for_update=True)
        if c.status not in ("decided", "appeal_decided"):
            raise rule("Only decided cases close", "INVALID_TRANSITION")
        c.status = "closed"
        await self.db.flush()
        await self._audit("malpractice_close", "malpractice_case", c.id, None, {})
        await self._emit("malpractice.closed", {"case_id": str(c.id)}, "malpractice_case", c.id)
        return await self.out(c)

    async def hearing_reminders(self) -> int:
        """Beat (daily): remind committee members and the student of hearings in the next 24 hours."""
        soon = now_utc() + timedelta(days=1)
        n = 0
        for c in (
            await self.db.execute(
                select(MalpracticeCase).where(
                    MalpracticeCase.institution_id == self.inst,
                    MalpracticeCase.status == "hearing_scheduled",
                    MalpracticeCase.hearing_at.is_not(None),
                    MalpracticeCase.hearing_at <= soon,
                    MalpracticeCase.hearing_at > now_utc(),
                )
            )
        ).scalars():
            ctx = await self._ctx(c)
            if ctx.student.user_id:
                await self._notify(
                    "results.malpractice_notice",
                    [ctx.student.user_id],
                    {"case": c.case_number, "course": ctx.course.code, "hearing": c.hearing_at.strftime("%Y-%m-%d %H:%M") if c.hearing_at else ""},
                )
                n += 1
        return n

