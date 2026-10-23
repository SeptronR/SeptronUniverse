"""Revaluation family — Prompts/16 §16.6 ``reval_service``.

1. ``eligibility``: published, current rows of the session (``pass|fail``, theory papers) within the window
   (``rules.reval.window_days``, default 15, from the session's latest publication); allowed types by feature
   (``results.photocopy`` → retotaling / photocopy, ``results.revaluation`` → revaluation, ``results.challenge_valuation``
   → challenge after a decided revaluation of the item); fees from ``rules.reval`` (revaluation ``fee_paise``,
   retotaling / photocopy ``photocopy_fee_paise``, challenge ``challenge_fee_paise``).
2. ``create`` (own / ward; Idempotency-Key at the route): one request per (item, type) — 409 otherwise; a linkage invoice
   ``source_type='reval_request'`` (head EXAM) puts it in ``submitted``; a zero fee or the payment (consumer
   ``reval.fee_paid`` ← ``fees.payment_received``) moves it to ``fee_paid``; photocopies are produced at once
   (watermarked with the registration number) → ``evaluated``.
3. Revaluation: ``assign`` to an evaluator who never valued the script and does not teach the course
   (``EVALUATOR_CONFLICT``) — a valuation assignment on the script's bundle in round 90+ whose
   ``external_evaluator.reval_request_id`` links it to the request (Phase 15 worklists skip rounds ≥ 90); the evaluator
   enters marks through ``/reval-requests/{id}/valuation`` (dummy number only) → ``evaluated``. Challenge: a panel of two
   evaluators, the mean of both. Retotaling: the exam cell enters the corrected total (min-delta ignored).
4. ``decide``: ``delta = revised − original``; ``|delta| ≥ rules.reval.min_delta_to_apply`` → ``marks_changed`` else
   ``no_change``; ``refund_due`` when changed and ``refund_if_changed`` → a Phase 12 refund request is raised.
5. ``apply(session)``: changed requests write ``script_final_marks.final_marks`` and become a ``revaluation`` run
   (job) for the affected rows — the COE verifies / approves / publishes it (new versions, arrears cleared on a pass).
"""

import contextlib
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.models.exams import ExamPaper, ExamRegistration, ExamRegistrationItem
from app.models.fees import FeeInvoice
from app.models.hr import Staff
from app.models.post_result import RevalRequest
from app.models.results import ResultPublication, StudentCourseResult
from app.models.valuation import (
    AnswerScript,
    AnswerScriptForEvaluation,
    ScriptFinalMarks,
    ScriptValuation,
    ValuationAssignment,
)
from app.repositories.fee_scope import own_enrollment_ids
from app.schemas.post_result import (
    ChallengePanelRequest,
    RetotalRequest,
    RevalApplyResponse,
    RevalAssignRequest,
    RevalCreate,
    RevalDecision,
    RevalEligibilityResponse,
    RevalEligibleItem,
    RevalMarks,
    RevalResponse,
    RevalScript,
)
from app.services.exams.common import now_utc, rule
from app.services.post_result.common import PostResultBase
from app.services.results.compute import d2

FEE_KEY = {
    "revaluation": "fee_paise",
    "retotaling": "photocopy_fee_paise",
    "photocopy": "photocopy_fee_paise",
    "challenge": "challenge_fee_paise",
}
REVAL_ROUND = 90


class RevalService(PostResultBase):
    audit_module = "exams"

    async def _rules(self, program_regulation_id: uuid.UUID) -> dict[str, Any]:
        from app.services.academics.rules import RulesResolver

        return await RulesResolver(self.db).for_program_regulation(program_regulation_id)

    async def _published_at(self, session_id: uuid.UUID) -> Any:
        return (
            await self.db.execute(
                select(func.max(ResultPublication.published_at)).where(ResultPublication.exam_session_id == session_id)
            )
        ).scalar_one_or_none()

    async def _allowed(self, item_id: uuid.UUID) -> list[str]:
        from app.core.features import is_enabled

        out = []
        if await is_enabled(self.inst, "results.photocopy"):
            out += ["retotaling", "photocopy"]
        if await is_enabled(self.inst, "results.revaluation"):
            out.append("revaluation")
        if await is_enabled(self.inst, "results.challenge_valuation"):
            prior = (
                await self.db.execute(
                    select(RevalRequest.id).where(
                        RevalRequest.exam_registration_item_id == item_id,
                        RevalRequest.request_type == "revaluation",
                        RevalRequest.status.in_(("marks_changed", "no_change", "closed")),
                    )
                )
            ).first()
            if prior:
                out.append("challenge")
        return out

    async def req(self, rid: uuid.UUID, *, for_update: bool = False) -> RevalRequest:
        q = select(RevalRequest).where(RevalRequest.id == rid, RevalRequest.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        r = (await self.db.execute(q)).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Request not found")
        await self.item_context(r.exam_registration_item_id)  # visibility
        return r

    async def outs(self, rows: list[RevalRequest]) -> list[RevalResponse]:
        if not rows:
            return []
        invs = {
            i.id: i
            for i in (
                await self.db.execute(
                    select(FeeInvoice).where(
                        FeeInvoice.id.in_({r.fee_invoice_id for r in rows if r.fee_invoice_id} or {uuid.uuid4()})
                    )
                )
            ).scalars()
        }
        out = []
        for r in rows:
            ctx = await self.item_context(r.exam_registration_item_id)
            o = RevalResponse.model_validate(r, from_attributes=True)
            inv = invs.get(r.fee_invoice_id) if r.fee_invoice_id else None
            o.fee_paise = int(inv.total_paise) if inv is not None else 0
            o.invoice_status = inv.status if inv is not None else None
            o.photocopy_ready = bool(r.photocopy_url)
            o.course_code = ctx.course.code
            o.student_name, o.registration_number = ctx.student_name, ctx.student.registration_number
            out.append(o)
        return out

    # ---- 1. eligibility ------------------------------------------------------------------------------------------------
    async def eligibility(self, session_id: uuid.UUID) -> RevalEligibilityResponse:
        s = await self.session(session_id)
        published = await self._published_at(s.id)
        enrs = list(
            (
                await self.db.execute(
                    select(ExamRegistration.student_program_enrollment_id).where(
                        ExamRegistration.exam_session_id == s.id,
                        ExamRegistration.student_program_enrollment_id.in_(
                            own_enrollment_ids(self.principal, advisees=False)
                        ),
                    )
                )
            ).scalars()
        )
        items: list[RevalEligibleItem] = []
        if not enrs or published is None:
            return RevalEligibilityResponse(session_id=s.id, items=[])
        from app.models.curriculum import Course
        from app.models.students import StudentProgramEnrollment

        rows = (
            await self.db.execute(
                select(
                    StudentCourseResult, ExamPaper.paper_type, Course, StudentProgramEnrollment.program_regulation_id
                )
                .join(ExamRegistrationItem, ExamRegistrationItem.id == StudentCourseResult.exam_registration_item_id)
                .join(ExamPaper, ExamPaper.id == ExamRegistrationItem.exam_paper_id)
                .join(Course, Course.id == StudentCourseResult.course_id)
                .join(
                    StudentProgramEnrollment,
                    StudentProgramEnrollment.id == StudentCourseResult.student_program_enrollment_id,
                )
                .where(
                    StudentCourseResult.exam_session_id == s.id,
                    StudentCourseResult.student_program_enrollment_id.in_(enrs),
                    StudentCourseResult.status == "published",
                    StudentCourseResult.is_current.is_(True),
                    StudentCourseResult.result_status.in_(("pass", "fail")),
                )
            )
        ).all()
        now = now_utc()
        existing: dict[uuid.UUID, dict[str, str]] = {}
        for r in (
            await self.db.execute(
                select(RevalRequest).where(
                    RevalRequest.exam_registration_item_id.in_(
                        [x.exam_registration_item_id for x, *_ in rows] or [uuid.uuid4()]
                    )
                )
            )
        ).scalars():
            existing.setdefault(r.exam_registration_item_id, {})[r.request_type] = r.status
        for row, paper_type, course, pr in rows:
            if paper_type != "theory" or row.exam_registration_item_id is None:
                continue
            rv = (await self._rules(pr)).get("reval") or {}
            ends = published + timedelta(days=int(rv.get("window_days", 15)))
            if now > ends:
                continue
            allowed = await self._allowed(row.exam_registration_item_id)
            items.append(
                RevalEligibleItem(
                    exam_registration_item_id=row.exam_registration_item_id,
                    result_id=row.id,
                    course_code=course.code,
                    course_title=course.title,
                    letter_grade=row.letter_grade,
                    result_status=row.result_status,
                    allowed_types=allowed,
                    fees={t: int(rv.get(FEE_KEY[t], 0) or 0) for t in allowed},
                    window_ends_at=ends,
                    existing=existing.get(row.exam_registration_item_id, {}),
                )
            )
        return RevalEligibilityResponse(session_id=s.id, items=items)

    # ---- 2. create / pay ---------------------------------------------------------------------------------------------
    async def create(self, body: RevalCreate) -> RevalResponse:
        from app.services.fees.invoice_service import InvoiceService

        ctx = await self.item_context(body.exam_registration_item_id)
        if not await self.mine(ctx.enrolment.id):
            raise APIError(404, ErrorCode.NOT_FOUND, "Exam registration item not found")
        elig = await self.eligibility(ctx.session.id)
        item = next((i for i in elig.items if i.exam_registration_item_id == ctx.item.id), None)
        if item is None:
            raise rule("This result is not open for revaluation (window, status or paper type)", "NOT_ELIGIBLE")
        if body.request_type not in item.allowed_types:
            raise rule(f"{body.request_type} is not available for this item", "TYPE_NOT_ALLOWED")
        if body.request_type in item.existing:
            raise APIError(409, ErrorCode.CONFLICT, f"A {body.request_type} request already exists for this paper")
        script = (
            await self.db.execute(select(AnswerScript).where(AnswerScript.exam_registration_item_id == ctx.item.id))
        ).scalar_one_or_none()
        original = None
        if script is not None:
            original = (
                await self.db.execute(
                    select(ScriptFinalMarks.final_marks).where(ScriptFinalMarks.answer_script_id == script.id)
                )
            ).scalar_one_or_none()
        r = RevalRequest(
            institution_id=self.inst,
            exam_session_id=ctx.session.id,
            exam_registration_item_id=ctx.item.id,
            answer_script_id=script.id if script else None,
            request_type=body.request_type,
            status="submitted",
            original_marks=original,
        )
        self.db.add(r)
        await self.db.flush()
        fee = item.fees.get(body.request_type, 0)
        if fee > 0:
            inv = await InvoiceService(self.db, None, self.request, self.inst).link(
                "reval_request",
                r.id,
                fee,
                ctx.enrolment.id,
                f"{body.request_type.title()} — {ctx.course.code}",
                head_type="exam",
            )
            r.fee_invoice_id = inv.id
        else:
            await self._paid(r)
        await self.db.flush()
        await self._audit("reval_request", "reval_request", r.id, None, {"type": r.request_type, "fee": fee})
        await self._emit("reval.requested", {"request_id": str(r.id), "type": r.request_type}, "reval_request", r.id)
        return (await self.outs([r]))[0]

    async def _paid(self, r: RevalRequest) -> None:
        r.status = "fee_paid"
        if r.request_type == "photocopy":
            await self._photocopy(r)

    async def on_paid(self, rid: uuid.UUID) -> None:
        r = (
            await self.db.execute(select(RevalRequest).where(RevalRequest.id == rid).with_for_update())
        ).scalar_one_or_none()
        if r is None or r.status != "submitted":
            return
        await self._paid(r)
        await self.db.flush()
        await self._emit("reval.fee_paid", {"request_id": str(r.id)}, "reval_request", r.id)

    async def _photocopy(self, r: RevalRequest) -> None:
        from app.core.files import build_key, storage
        from app.utils.pdf import simple_pdf

        ctx = await self.item_context(r.exam_registration_item_id)
        lines = [
            "PHOTOCOPY OF ANSWER SCRIPT — FOR THE CANDIDATE ONLY",
            f"Watermark: {ctx.student.registration_number} · {ctx.course.code} · {ctx.session.name}",
            f"Issued {now_utc():%Y-%m-%d %H:%M} UTC",
        ]
        if r.answer_script_id:
            sc = (await self.db.execute(select(AnswerScript).where(AnswerScript.id == r.answer_script_id))).scalar_one()
            lines.append(
                f"Script pages: {sc.pages or '—'} · scan {'attached' if sc.scan_url else 'pending (exam cell scan)'}"
            )
        pdf = simple_pdf(lines, title="Answer script photocopy")
        key = build_key(self.inst, "reval/photocopies", f"{r.id}.pdf")
        await storage.put(key, pdf, "application/pdf")
        r.photocopy_url, r.status = key, "evaluated"
        await self._emit("photocopy.ready", {"request_id": str(r.id)}, "reval_request", r.id)

    async def render_photocopy(self, r: RevalRequest) -> None:
        """``reval.photocopy_scan`` job: re-render once the exam cell attached the scan."""
        await self._photocopy(r)
        await self.db.flush()

    async def photocopy(self, rid: uuid.UUID) -> bytes:
        from app.core.files import storage

        r = await self.req(rid)
        if not self.is_staff():
            ctx = await self.item_context(r.exam_registration_item_id)
            if not await self.mine(ctx.enrolment.id):
                raise APIError(404, ErrorCode.NOT_FOUND, "Request not found")
        if r.request_type != "photocopy" or not r.photocopy_url:
            raise APIError(404, ErrorCode.NOT_FOUND, "The photocopy is not ready")
        data = await storage.get(r.photocopy_url)
        if not data:
            raise APIError(404, ErrorCode.NOT_FOUND, "The photocopy is not ready")
        return data

    async def my_requests(self) -> list[RevalResponse]:
        rows = list(
            (
                await self.db.execute(
                    select(RevalRequest)
                    .join(ExamRegistrationItem, ExamRegistrationItem.id == RevalRequest.exam_registration_item_id)
                    .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
                    .where(
                        RevalRequest.institution_id == self.inst,
                        ExamRegistration.student_program_enrollment_id.in_(
                            own_enrollment_ids(self.principal, advisees=False)
                        ),
                    )
                    .order_by(RevalRequest.created_at.desc())
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def get(self, rid: uuid.UUID) -> RevalResponse:
        return (await self.outs([await self.req(rid)]))[0]

    async def session_requests(self, sid: uuid.UUID, rtype: str | None, status: str | None) -> list[RevalResponse]:
        s = await self.session(sid)
        q = select(RevalRequest).where(RevalRequest.exam_session_id == s.id)
        if rtype:
            q = q.where(RevalRequest.request_type == rtype)
        if status:
            q = q.where(RevalRequest.status == status)
        return await self.outs(list((await self.db.execute(q.order_by(RevalRequest.created_at))).scalars()))

    # ---- 3. assignment / valuation ---------------------------------------------------------------------------------------
    async def _excluded_users(self, r: RevalRequest, ctx: Any) -> set[uuid.UUID]:
        from app.models.offerings import CourseOffering, CourseOfferingFaculty

        users = set(
            (
                await self.db.execute(
                    select(ScriptValuation.evaluator_user_id).where(
                        ScriptValuation.answer_script_id == r.answer_script_id
                    )
                )
            ).scalars()
        )
        teachers = (
            await self.db.execute(
                select(Staff.user_id)
                .join(CourseOfferingFaculty, CourseOfferingFaculty.staff_id == Staff.id)
                .join(CourseOffering, CourseOffering.id == CourseOfferingFaculty.offering_id)
                .where(CourseOffering.course_id == ctx.course.id, CourseOffering.term_id == ctx.session.term_id)
            )
        ).scalars()
        return users | {u for u in teachers if u}

    async def _new_assignment(
        self, r: RevalRequest, ctx: Any, staff_id: uuid.UUID | None, external: dict[str, Any] | None, due_at: Any
    ) -> ValuationAssignment:
        if r.answer_script_id is None:
            raise rule("The item has no answer script", "NO_SCRIPT", 422)
        sc = (await self.db.execute(select(AnswerScript).where(AnswerScript.id == r.answer_script_id))).scalar_one()
        user_id = None
        if staff_id is not None:
            st = (
                await self.db.execute(select(Staff).where(Staff.id == staff_id, Staff.institution_id == self.inst))
            ).scalar_one_or_none()
            if st is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Evaluator (staff) not found")
            user_id = st.user_id
        elif external and external.get("user_id"):
            user_id = uuid.UUID(str(external["user_id"]))
        if user_id is not None and user_id in await self._excluded_users(r, ctx):
            raise rule("The evaluator valued this script or teaches the course", "EVALUATOR_CONFLICT")
        used = (
            await self.db.execute(
                select(func.max(ValuationAssignment.valuation_round)).where(
                    ValuationAssignment.bundle_id == sc.bundle_id, ValuationAssignment.valuation_round >= REVAL_ROUND
                )
            )
        ).scalar_one_or_none()
        a = ValuationAssignment(
            institution_id=self.inst,
            exam_paper_id=ctx.paper.id,
            bundle_id=sc.bundle_id,
            evaluator_staff_id=staff_id,
            evaluator_user_id=user_id,
            external_evaluator={**(external or {}), "reval_request_id": str(r.id), "purpose": r.request_type},
            evaluator_type="internal" if staff_id else "external",
            valuation_round=int(used or REVAL_ROUND - 1) + 1,
            status="assigned",
            due_at=due_at,
        )
        self.db.add(a)
        await self.db.flush()
        return a

    async def assign(self, rid: uuid.UUID, body: RevalAssignRequest) -> RevalResponse:
        r = await self.req(rid, for_update=True)
        if r.request_type != "revaluation":
            raise rule("Only revaluation requests are assigned (challenge uses the panel)", "WRONG_TYPE")
        if r.status != "fee_paid":
            raise rule(f"A {r.status} request cannot be assigned", "INVALID_TRANSITION")
        ctx = await self.item_context(r.exam_registration_item_id)
        a = await self._new_assignment(r, ctx, body.evaluator_staff_id, body.external_evaluator, body.due_at)
        r.evaluator_assignment_id, r.status = a.id, "assigned"
        await self.db.flush()
        await self._emit("reval.assigned", {"request_id": str(r.id)}, "reval_request", r.id)
        if a.evaluator_user_id:
            await self._notify(
                "valuation.assigned",
                [a.evaluator_user_id],
                {"paper": ctx.paper.paper_code or "", "bundles": 1, "round": "reval"},
            )
        return (await self.outs([r]))[0]

    async def challenge_panel(self, sid: uuid.UUID, body: ChallengePanelRequest) -> list[RevalResponse]:
        s = await self.session(sid)
        out = []
        for rid in body.request_ids:
            r = await self.req(rid, for_update=True)
            if r.exam_session_id != s.id or r.request_type != "challenge" or r.status != "fee_paid":
                raise rule(
                    "Only paid challenge requests of this session form a panel",
                    "INVALID_TRANSITION",
                    request_id=str(rid),
                )
            ctx = await self.item_context(r.exam_registration_item_id)
            first = None
            for staff_id in body.evaluator_staff_ids:
                a = await self._new_assignment(r, ctx, staff_id, None, body.due_at)
                first = first or a
            r.evaluator_assignment_id, r.status = first.id if first else None, "assigned"
            out.append(r)
        await self.db.flush()
        return await self.outs(out)

    async def my_scripts(self) -> list[RevalScript]:
        rows = (
            await self.db.execute(
                select(ValuationAssignment, ExamPaper.max_marks)
                .join(ExamPaper, ExamPaper.id == ValuationAssignment.exam_paper_id)
                .where(
                    ValuationAssignment.institution_id == self.inst,
                    ValuationAssignment.evaluator_user_id == self.actor_id,
                    ValuationAssignment.valuation_round >= REVAL_ROUND,
                )
            )
        ).all()
        out = []
        for a, mx in rows:
            rid = (a.external_evaluator or {}).get("reval_request_id")
            if not rid:
                continue
            r = (
                await self.db.execute(select(RevalRequest).where(RevalRequest.id == uuid.UUID(rid)))
            ).scalar_one_or_none()
            if r is None or r.answer_script_id is None:
                continue
            sc = (
                await self.db.execute(
                    select(AnswerScriptForEvaluation).where(AnswerScriptForEvaluation.id == r.answer_script_id)
                )
            ).scalar_one()
            v = (
                await self.db.execute(
                    select(ScriptValuation.marks).where(
                        ScriptValuation.answer_script_id == sc.id, ScriptValuation.valuation_round == a.valuation_round
                    )
                )
            ).scalar_one_or_none()
            out.append(
                RevalScript(
                    reval_request_id=r.id,
                    answer_script_id=sc.id,
                    dummy_number=sc.dummy_number,
                    pages=sc.pages,
                    scan_available=bool(sc.scan_url),
                    max_marks=mx,
                    request_type=r.request_type,
                    status=a.status,
                    due_at=a.due_at,
                    marks=v,
                )
            )
        return out

    async def submit_valuation(self, rid: uuid.UUID, body: RevalMarks) -> RevalScript:
        r = (
            await self.db.execute(
                select(RevalRequest)
                .where(RevalRequest.id == rid, RevalRequest.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None or r.answer_script_id is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Request not found")
        mine = None
        for a in (
            await self.db.execute(
                select(ValuationAssignment).where(
                    ValuationAssignment.evaluator_user_id == self.actor_id,
                    ValuationAssignment.valuation_round >= REVAL_ROUND,
                )
            )
        ).scalars():
            if (a.external_evaluator or {}).get("reval_request_id") == str(r.id):
                mine = a
        if mine is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Request not found")
        if mine.status in ("submitted", "verified"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, "This valuation is submitted")
        mx = (await self.db.execute(select(ExamPaper.max_marks).where(ExamPaper.id == mine.exam_paper_id))).scalar_one()
        if body.marks > mx:
            raise APIError(422, ErrorCode.VALIDATION, f"Marks exceed the paper maximum ({mx})")
        self.db.add(
            ScriptValuation(
                institution_id=self.inst,
                answer_script_id=r.answer_script_id,
                valuation_round=mine.valuation_round,
                evaluator_user_id=self.actor_id,
                marks=d2(body.marks),
                question_wise={k: float(v) for k, v in (body.question_wise or {}).items()} or None,
                is_locked=True,
            )
        )
        mine.status, mine.submitted_at = "submitted", now_utc()
        await self.db.flush()
        # all panel valuations in → evaluated (challenge: mean of both)
        panel = [
            a
            for a in (
                await self.db.execute(
                    select(ValuationAssignment).where(
                        ValuationAssignment.bundle_id == mine.bundle_id,
                        ValuationAssignment.valuation_round >= REVAL_ROUND,
                    )
                )
            ).scalars()
            if (a.external_evaluator or {}).get("reval_request_id") == str(r.id)
        ]
        if all(a.status == "submitted" for a in panel):
            marks = list(
                (
                    await self.db.execute(
                        select(ScriptValuation.marks).where(
                            ScriptValuation.answer_script_id == r.answer_script_id,
                            ScriptValuation.valuation_round.in_([a.valuation_round for a in panel]),
                        )
                    )
                ).scalars()
            )
            r.revised_marks = d2(sum(marks, Decimal(0)) / len(marks))
            r.delta = d2(r.revised_marks - (r.original_marks or Decimal(0)))
            r.status = "evaluated"
            await self._emit("reval.evaluated", {"request_id": str(r.id)}, "reval_request", r.id)
        await self.db.flush()
        return next(x for x in await self.my_scripts() if x.reval_request_id == r.id)

    # ---- 4. decisions ----------------------------------------------------------------------------------------------------
    async def _min_delta(self, r: RevalRequest) -> tuple[Decimal, bool]:
        ctx = await self.item_context(r.exam_registration_item_id)
        rv = (await self._rules(ctx.enrolment.program_regulation_id)).get("reval") or {}
        return Decimal(str(rv.get("min_delta_to_apply", 5))), bool(rv.get("refund_if_changed", True))

    async def _close_decision(
        self, r: RevalRequest, changed: bool, refund_if_changed: bool, remarks: str | None
    ) -> None:
        from app.schemas.fees import RefundCreate
        from app.services.fees.refund_service import RefundService

        r.status = "marks_changed" if changed else "no_change"
        r.decided_by, r.decided_at = self.actor_id, now_utc()
        inv = None
        if r.fee_invoice_id:
            inv = (
                await self.db.execute(select(FeeInvoice).where(FeeInvoice.id == r.fee_invoice_id))
            ).scalar_one_or_none()
        r.refund_due = bool(changed and refund_if_changed and inv is not None and inv.paid_paise > 0)
        await self.db.flush()
        if r.refund_due and inv is not None:
            with contextlib.suppress(APIError):  # the refund can be raised manually from the fee desk
                await RefundService(self.db, self.principal, self.request, self.inst).submit(
                    RefundCreate(
                        invoice_id=inv.id,
                        amount_paise=int(inv.paid_paise),
                        reason=f"Revaluation changed the marks ({r.request_type})",
                    )
                )
        await self._audit(
            "reval_decide",
            "reval_request",
            r.id,
            None,
            {"status": r.status, "delta": float(r.delta or 0), "refund_due": r.refund_due, "remarks": remarks},
        )
        await self._emit("reval.decided", {"request_id": str(r.id), "status": r.status}, "reval_request", r.id)
        ctx = await self.item_context(r.exam_registration_item_id)
        if ctx.student.user_id:
            await self._notify(
                "results.reval_decided",
                [ctx.student.user_id],
                {"course": ctx.course.code, "type": r.request_type, "outcome": r.status.replace("_", " ")},
                guardians=True,
            )

    async def retotal(self, rid: uuid.UUID, body: RetotalRequest) -> RevalResponse:
        r = await self.req(rid, for_update=True)
        if r.request_type != "retotaling" or r.status not in ("fee_paid", "evaluated"):
            raise rule("Only a paid retotaling request can be retotalled", "INVALID_TRANSITION")
        r.revised_marks = d2(body.revised_marks)
        r.delta = d2(r.revised_marks - (r.original_marks or Decimal(0)))
        _, refund = await self._min_delta(r)
        await self._close_decision(r, r.delta != 0, refund, body.remarks)  # retotaling ignores the min-delta rule
        return (await self.outs([r]))[0]

    async def decide(self, rid: uuid.UUID, body: RevalDecision) -> RevalResponse:
        r = await self.req(rid, for_update=True)
        if body.decision == "rejected":
            return await self.reject(rid, body.remarks or "Rejected")
        if r.status not in ("evaluated", "fee_paid") or r.request_type == "photocopy":
            raise rule(f"A {r.status} {r.request_type} request cannot be decided", "INVALID_TRANSITION")
        if body.revised_marks is not None:
            r.revised_marks = d2(body.revised_marks)
        if r.revised_marks is None:
            raise rule("No revised marks yet — the revaluation is pending", "NOT_EVALUATED", 422)
        r.delta = d2(r.revised_marks - (r.original_marks or Decimal(0)))
        min_delta, refund = await self._min_delta(r)
        changed = r.delta != 0 if r.request_type == "retotaling" else abs(r.delta) >= min_delta
        if body.decision == "no_change":
            changed = False
        elif body.decision == "marks_changed":
            changed = r.delta != 0
        await self._close_decision(r, changed, refund, body.remarks)
        return (await self.outs([r]))[0]

    async def reject(self, rid: uuid.UUID, remarks: str) -> RevalResponse:
        r = await self.req(rid, for_update=True)
        if r.status in ("marks_changed", "no_change", "closed", "rejected"):
            raise rule(f"A {r.status} request cannot be rejected", "INVALID_TRANSITION")
        r.status, r.decided_by, r.decided_at = "rejected", self.actor_id, now_utc()
        await self.db.flush()
        await self._audit("reval_reject", "reval_request", r.id, None, {"remarks": remarks})
        await self._emit("reval.decided", {"request_id": str(r.id), "status": "rejected"}, "reval_request", r.id)
        return (await self.outs([r]))[0]

    # ---- 5. apply ----------------------------------------------------------------------------------------------------------
    async def apply(self, sid: uuid.UUID) -> RevalApplyResponse:
        from app.core.jobs import enqueue
        from app.schemas.results import RunCreateRequest, RunScope
        from app.services.results.result_service import ResultRunService

        s = await self.session(sid)
        reqs = list(
            (
                await self.db.execute(
                    select(RevalRequest)
                    .where(
                        RevalRequest.exam_session_id == s.id,
                        RevalRequest.status == "marks_changed",
                        RevalRequest.request_type.in_(("retotaling", "revaluation", "challenge")),
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        if not reqs:
            return RevalApplyResponse(requests=0)
        pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for r in reqs:
            ctx = await self.item_context(r.exam_registration_item_id)
            if r.answer_script_id and r.revised_marks is not None:
                fm = (
                    await self.db.execute(
                        select(ScriptFinalMarks)
                        .where(ScriptFinalMarks.answer_script_id == r.answer_script_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if fm is not None:
                    fm.final_marks, fm.rule_applied = r.revised_marks, f"reval:{r.request_type}"
            pairs.add((ctx.enrolment.id, ctx.course.id))
            r.status = "closed"
        await self.db.flush()
        svc = ResultRunService(self.db, self.principal, self.request, self.inst)
        run = await svc.create_run(
            RunCreateRequest(
                exam_session_id=s.id,
                run_type="revaluation",
                scope=RunScope(enrollment_ids=sorted({e for e, _ in pairs}), course_ids=sorted({c for _, c in pairs})),
            )
        )
        j = await enqueue(self.db, self.principal, "results.compute_run", {"run_id": str(run.id)})
        run.job_id = j.id
        await self.db.flush()
        await self._emit(
            "reval.applied",
            {"session_id": str(s.id), "run_id": str(run.id), "requests": len(reqs)},
            "exam_session",
            s.id,
        )
        return RevalApplyResponse(requests=len(reqs), run_id=run.id, job_id=j.id)

    async def window_close(self) -> int:
        """Beat (daily): unpaid requests older than 15 days close."""
        n = 0
        for r in (
            await self.db.execute(
                select(RevalRequest).where(
                    RevalRequest.institution_id == self.inst,
                    RevalRequest.status == "submitted",
                    RevalRequest.created_at < now_utc() - timedelta(days=15),
                )
            )
        ).scalars():
            r.status = "closed"
            n += 1
        await self.db.flush()
        return n

    async def due_reminders(self) -> int:
        """Beat (daily): remind revaluation evaluators of assignments due within two days."""
        n = 0
        for a in (
            await self.db.execute(
                select(ValuationAssignment).where(
                    ValuationAssignment.institution_id == self.inst,
                    ValuationAssignment.valuation_round >= REVAL_ROUND,
                    ValuationAssignment.status == "assigned",
                    ValuationAssignment.due_at.is_not(None),
                    ValuationAssignment.due_at <= now_utc() + timedelta(days=2),
                )
            )
        ).scalars():
            if a.evaluator_user_id:
                await self._notify("valuation.due_reminder", [a.evaluator_user_id], {"bundles": 1})
                n += 1
        return n
