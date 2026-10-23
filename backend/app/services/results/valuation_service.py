# mypy: disable-error-code="arg-type,var-annotated"
"""Valuation, reconciliation, moderation and decode — Prompts/15 §15.6 ``valuation_service``.

1. ``assign`` (``exams:valuation_assign``): one assignment per (bundle, round) — round 1 always, round 2 only for
   ``valuation_mode='double'`` sessions with ``exams.double_valuation`` on, round 3 only through ``third_assign``. An
   internal evaluator who teaches an offering of the paper's course in the session term is refused (409
   ``RULE_VIOLATION`` / ``EVALUATOR_CONFLICT``) unless ``exams.allow_teacher_evaluation``; the same person never values
   two rounds of one bundle. External evaluators are time-boxed ``external_examiner`` users
   (``external_evaluator.user_id``).
2. Worklist (``exams:evaluate``): every evaluator read goes through ``AnswerScriptForEvaluation`` joined to the caller's
   own assignment (``evaluator_user_id == p.id``) — anything else answers 404. Marks are validated against
   ``max_marks`` and the paper's ``qp_pattern`` (``{"questions": [{"q": "1a", "max": 10}]}`` or ``{"1a": 10}``),
   question-wise marks must add up to the total; submitting the bundle locks every valuation (409 ``RECORD_LOCKED``).
3. ``reconcile`` per paper: single valuation → ``computed = V1``; double → ``|V1 − V2| > discrepancy_pct × max`` →
   ``needs_third`` (script ``discrepancy``) until a third valuation exists, then ``rules.double_valuation.resolution``
   of the course's regulation (``avg_closest_two`` default, ``third_final``, ``best_two_avg``); within tolerance →
   mean of the two. Writes ``script_final_marks(status='resolved', final_marks=computed)``.
4. Moderation (``exams:moderate`` proposes; ``exams:manage`` — the COE — approves): ``scale_up/down {factor}``,
   ``add_flat {marks}``, ``grace {below, up_to}``, ``normalize {target_mean, target_sd}``, ``cap {cap}``; apply
   writes ``moderated_marks`` / ``final_marks`` (clamped to 0..max) and ``affected_count``; revert before decode.
5. ``decode`` (``exams:decode`` + IP allow-list dependency): needs every script of the paper resolved / moderated;
   final marks become ``final``, scripts / bundles ``decoded``; the mapping is never returned.
6. Online papers: quiz totals become synthetic scripts in an ``ONLINE`` bundle, already decoded.
"""

import statistics
import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.models.exams import ExamPaper, ExamRegistration, ExamRegistrationItem, ExamSession
from app.models.hr import Staff
from app.models.offerings import CourseOffering, CourseOfferingFaculty
from app.models.valuation import (
    AnswerScript,
    AnswerScriptBundle,
    AnswerScriptForEvaluation,
    ModerationAction,
    ScriptFinalMarks,
    ScriptValuation,
    ValuationAssignment,
)
from app.schemas.valuation import (
    AssignValuationRequest,
    BulkValuationSubmit,
    DecodeResponse,
    EvaluatorBundleResponse,
    EvaluatorScript,
    ModerationProposal,
    ModerationResponse,
    OnlineImportResponse,
    ReassignRequest,
    ReconcileSummary,
    ScriptValuationResponse,
    ThirdValuationAssign,
    ValuationAssignmentResponse,
    ValuationStatus,
    ValuationSubmit,
)
from app.services.exams.common import ExamBase, now_utc, rule

TWO = Decimal("0.01")


def q2(v: Decimal | float | int) -> Decimal:
    return Decimal(str(v)).quantize(TWO, rounding=ROUND_HALF_UP)


def pattern_max(pattern: dict[str, Any] | None) -> dict[str, Decimal]:
    if not pattern:
        return {}
    if isinstance(pattern.get("questions"), list):
        return {
            str(q.get("q") or q.get("id") or i + 1): Decimal(str(q.get("max") or q.get("max_marks") or 0))
            for i, q in enumerate(pattern["questions"])
            if isinstance(q, dict)
        }
    return {str(k): Decimal(str(v)) for k, v in pattern.items() if isinstance(v, int | float | str) and k != "total"}


def resolve(v1: Decimal, v2: Decimal, v3: Decimal | None, rule_name: str) -> Decimal:
    if v3 is None:
        return q2((v1 + v2) / 2)
    if rule_name == "third_final":
        return q2(v3)
    vals = sorted([v1, v2, v3])
    if rule_name == "best_two_avg":
        return q2((vals[1] + vals[2]) / 2)
    # avg_closest_two: the pair with the smallest gap (ties → the higher pair)
    pairs = [(vals[1] - vals[0], vals[0], vals[1]), (vals[2] - vals[1], vals[1], vals[2])]
    gap, a, b = min(pairs, key=lambda t: (t[0], -t[2]))
    return q2((a + b) / 2)


class ValuationService(ExamBase):
    audit_module = "exams"

    # ---- helpers -----------------------------------------------------------------------------------------------------
    async def _staff(self, sid: uuid.UUID) -> Staff:
        st = (
            await self.db.execute(
                select(Staff).where(Staff.id == sid, Staff.institution_id == self.inst, Staff.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if st is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Evaluator (staff) not found")
        return st

    async def _teaches(self, staff_id: uuid.UUID, p: ExamPaper, s: ExamSession) -> bool:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(CourseOfferingFaculty)
                .join(CourseOffering, CourseOffering.id == CourseOfferingFaculty.offering_id)
                .where(
                    CourseOfferingFaculty.staff_id == staff_id,
                    CourseOffering.course_id == p.course_id,
                    CourseOffering.term_id == s.term_id,
                )
            )
        ).scalar_one() > 0

    async def _evaluator(
        self, p: ExamPaper, s: ExamSession, staff_id: uuid.UUID | None, external: Any
    ) -> tuple[uuid.UUID | None, uuid.UUID | None, dict[str, Any] | None, str | None]:
        if staff_id is not None:
            st = await self._staff(staff_id)
            allow = bool(await self.setting("exams", "allow_teacher_evaluation"))
            if not allow and await self._teaches(st.id, p, s):
                raise rule(
                    "The evaluator teaches this course in the session term", "EVALUATOR_CONFLICT", staff_id=str(st.id)
                )
            return st.id, st.user_id, None, " ".join(x for x in (st.first_name, st.last_name) if x)
        ext = external.model_dump(mode="json") if external is not None else None
        uid = uuid.UUID(ext["user_id"]) if ext and ext.get("user_id") else None
        return None, uid, ext, (ext or {}).get("name")

    async def _bundle_in_paper(self, bid: uuid.UUID, p: ExamPaper) -> AnswerScriptBundle:
        b = (
            await self.db.execute(
                select(AnswerScriptBundle)
                .where(AnswerScriptBundle.id == bid, AnswerScriptBundle.exam_paper_id == p.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if b is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Bundle not found on this paper")
        return b

    async def _assignment_out(self, rows: list[ValuationAssignment]) -> list[ValuationAssignmentResponse]:
        if not rows:
            return []
        bids = {a.bundle_id for a in rows}
        numbers = dict(
            (
                await self.db.execute(
                    select(AnswerScriptBundle.id, AnswerScriptBundle.bundle_number).where(
                        AnswerScriptBundle.id.in_(bids)
                    )
                )
            ).all()
        )
        counts = dict(
            (
                await self.db.execute(
                    select(AnswerScript.bundle_id, func.count())
                    .where(AnswerScript.bundle_id.in_(bids))
                    .group_by(AnswerScript.bundle_id)
                )
            ).all()
        )
        valued: dict[tuple[uuid.UUID, int], int] = {
            (bid, rnd): int(n)
            for bid, rnd, n in (
                await self.db.execute(
                    select(AnswerScript.bundle_id, ScriptValuation.valuation_round, func.count())
                    .join(ScriptValuation, ScriptValuation.answer_script_id == AnswerScript.id)
                    .where(AnswerScript.bundle_id.in_(bids))
                    .group_by(AnswerScript.bundle_id, ScriptValuation.valuation_round)
                )
            ).all()
        }
        staff_names = {
            sid: " ".join(x for x in (f, last) if x)
            for sid, f, last in (
                await self.db.execute(
                    select(Staff.id, Staff.first_name, Staff.last_name).where(
                        Staff.id.in_({a.evaluator_staff_id for a in rows if a.evaluator_staff_id})
                    )
                )
            ).all()
        }
        return [
            ValuationAssignmentResponse(
                id=a.id,
                exam_paper_id=a.exam_paper_id,
                bundle_id=a.bundle_id,
                bundle_number=numbers.get(a.bundle_id),
                evaluator_staff_id=a.evaluator_staff_id,
                evaluator_user_id=a.evaluator_user_id,
                evaluator_name=staff_names.get(a.evaluator_staff_id)
                if a.evaluator_staff_id
                else (a.external_evaluator or {}).get("name"),
                evaluator_type=a.evaluator_type,
                valuation_round=a.valuation_round,
                status=a.status,
                assigned_at=a.assigned_at,
                due_at=a.due_at,
                submitted_at=a.submitted_at,
                remuneration_paise=a.remuneration_paise,
                scripts=int(counts.get(a.bundle_id, 0)),
                valued=valued.get((a.bundle_id, a.valuation_round), 0),
            )
            for a in rows
        ]

    # ---- 1. assignment -------------------------------------------------------------------------------------------------
    async def assign(self, pid: uuid.UUID, body: AssignValuationRequest) -> list[ValuationAssignmentResponse]:
        from app.core.features import is_enabled

        p, s = await self.paper(pid)
        if body.round == 3:
            raise rule("Third valuations are assigned through third-assign after reconciliation", "USE_THIRD_ASSIGN")
        if body.round == 2 and (
            s.valuation_mode != "double" or not await is_enabled(self.inst, "exams.double_valuation")
        ):
            raise rule("The session uses single valuation", "SINGLE_VALUATION")
        staff_id, user_id, ext, _name = await self._evaluator(p, s, body.evaluator_staff_id, body.external_evaluator)
        return await self._create_assignments(
            p,
            body.bundle_ids,
            body.round,
            staff_id,
            user_id,
            ext,
            body.evaluator_type,
            body.due_at,
            body.remuneration_paise,
        )

    async def _create_assignments(
        self,
        p: ExamPaper,
        bundle_ids: list[uuid.UUID],
        rnd: int,
        staff_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        ext: dict[str, Any] | None,
        etype: str,
        due_at: Any,
        remuneration: int | None,
    ) -> list[ValuationAssignmentResponse]:
        out: list[ValuationAssignment] = []
        for bid in bundle_ids:
            b = await self._bundle_in_paper(bid, p)
            if b.status == "created":
                raise rule("Code the bundle before assigning it", "BUNDLE_NOT_CODED", bundle_id=str(b.id))
            if b.status in ("decoded", "archived"):
                raise APIError(409, ErrorCode.RECORD_LOCKED, "The bundle is already decoded")
            others = (
                (await self.db.execute(select(ValuationAssignment).where(ValuationAssignment.bundle_id == b.id)))
                .scalars()
                .all()
            )
            if any(o.valuation_round == rnd for o in others):
                raise APIError(409, ErrorCode.CONFLICT, f"Round {rnd} of bundle {b.bundle_number} is already assigned")
            if user_id is not None and any(o.evaluator_user_id == user_id for o in others):
                raise rule("The same evaluator cannot value two rounds of a bundle", "EVALUATOR_CONFLICT")
            a = ValuationAssignment(
                institution_id=self.inst,
                exam_paper_id=p.id,
                bundle_id=b.id,
                evaluator_staff_id=staff_id,
                evaluator_user_id=user_id,
                external_evaluator=ext,
                evaluator_type=etype,
                valuation_round=rnd,
                status="assigned",
                due_at=due_at,
                remuneration_paise=remuneration,
            )
            self.db.add(a)
            if b.status in ("coded", "dispatched", "received", "valuated"):
                b.status = "in_valuation"
            for sc in (await self.db.execute(select(AnswerScript).where(AnswerScript.bundle_id == b.id))).scalars():
                if sc.status in ("coded", "received", "valuated"):
                    sc.status = "in_valuation" if rnd < 3 else "third_valuation"
            out.append(a)
        await self.db.flush()
        await self._audit(
            "valuation_assign", "exam_paper", p.id, None, {"round": rnd, "bundles": len(out), "type": etype}
        )
        await self._emit(
            "valuation.assigned" if rnd < 3 else "valuation.third_required",
            {"paper_id": str(p.id), "round": rnd, "bundles": len(out)},
            "exam_paper",
            p.id,
        )
        if user_id:
            await self._notify(
                "valuation.assigned", [user_id], {"paper": p.paper_code or "", "bundles": len(out), "round": rnd}
            )
        return await self._assignment_out(out)

    async def reassign(self, aid: uuid.UUID, body: ReassignRequest) -> ValuationAssignmentResponse:
        a = (
            await self.db.execute(
                select(ValuationAssignment)
                .where(ValuationAssignment.id == aid, ValuationAssignment.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Assignment not found")
        if a.status in ("submitted", "verified"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The bundle has been submitted")
        p, s = await self.paper(a.exam_paper_id)
        staff_id, user_id, ext, _ = await self._evaluator(p, s, body.evaluator_staff_id, body.external_evaluator)
        # valuations entered by the previous evaluator are discarded
        scripts = select(AnswerScript.id).where(AnswerScript.bundle_id == a.bundle_id)
        for v in (
            await self.db.execute(
                select(ScriptValuation).where(
                    ScriptValuation.answer_script_id.in_(scripts), ScriptValuation.valuation_round == a.valuation_round
                )
            )
        ).scalars():
            await self.db.delete(v)
        old = {"evaluator_staff_id": str(a.evaluator_staff_id) if a.evaluator_staff_id else None}
        a.evaluator_staff_id, a.evaluator_user_id, a.external_evaluator = staff_id, user_id, ext
        a.evaluator_type = "internal" if staff_id else "external"
        a.status = "assigned"
        if body.due_at:
            a.due_at = body.due_at
        await self.db.flush()
        await self._audit(
            "valuation_reassign", "valuation_assignment", a.id, old, {"evaluator_staff_id": str(staff_id)}
        )
        return (await self._assignment_out([a]))[0]

    async def status(self, pid: uuid.UUID) -> ValuationStatus:
        p, s = await self.paper(pid)
        bundles = list(
            (
                await self.db.execute(select(AnswerScriptBundle.id).where(AnswerScriptBundle.exam_paper_id == p.id))
            ).scalars()
        )
        scripts = (
            int(
                (
                    await self.db.execute(
                        select(func.count()).select_from(AnswerScript).where(AnswerScript.bundle_id.in_(bundles))
                    )
                ).scalar_one()
            )
            if bundles
            else 0
        )
        rows = list(
            (
                await self.db.execute(
                    select(ValuationAssignment)
                    .where(ValuationAssignment.exam_paper_id == p.id)
                    .order_by(ValuationAssignment.valuation_round, ValuationAssignment.assigned_at)
                )
            ).scalars()
        )
        fm = (
            dict(
                (
                    await self.db.execute(
                        select(ScriptFinalMarks.status, func.count())
                        .join(AnswerScript, AnswerScript.id == ScriptFinalMarks.answer_script_id)
                        .where(AnswerScript.bundle_id.in_(bundles))
                        .group_by(ScriptFinalMarks.status)
                    )
                ).all()
            )
            if bundles
            else {}
        )
        return ValuationStatus(
            exam_paper_id=p.id,
            valuation_mode=s.valuation_mode,
            bundles=len(bundles),
            scripts=scripts,
            assignments=await self._assignment_out(rows),
            final_marks={k: int(v) for k, v in fm.items()},
        )

    # ---- 2. evaluator worklist -----------------------------------------------------------------------------------------
    async def _my_assignment(self, bid: uuid.UUID, rnd: int | None = None) -> ValuationAssignment:
        q = select(ValuationAssignment).where(
            ValuationAssignment.bundle_id == bid,
            ValuationAssignment.institution_id == self.inst,
            ValuationAssignment.evaluator_user_id == self.actor_id,
        )
        q = q.where(ValuationAssignment.valuation_round == rnd) if rnd is not None else q.where(ValuationAssignment.valuation_round < 90)
        a = (await self.db.execute(q.order_by(ValuationAssignment.valuation_round.desc()))).scalars().first()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Bundle not found")
        return a

    async def my_bundles(self) -> list[EvaluatorBundleResponse]:
        from app.models.curriculum import Course

        rows = (
            await self.db.execute(
                select(ValuationAssignment, AnswerScriptBundle, ExamPaper, Course.title)
                .join(AnswerScriptBundle, AnswerScriptBundle.id == ValuationAssignment.bundle_id)
                .join(ExamPaper, ExamPaper.id == ValuationAssignment.exam_paper_id)
                .join(Course, Course.id == ExamPaper.course_id)
                .where(
                    ValuationAssignment.institution_id == self.inst,
                    ValuationAssignment.evaluator_user_id == self.actor_id,
                    ValuationAssignment.valuation_round < 90,  # rounds 90+ are revaluations (Phase 16)
                )
                .order_by(ValuationAssignment.due_at.nulls_last(), AnswerScriptBundle.bundle_number)
            )
        ).all()
        resp = await self._assignment_out([a for a, *_ in rows])
        by_id = {r.id: r for r in resp}
        return [
            EvaluatorBundleResponse(
                assignment_id=a.id,
                bundle_id=b.id,
                bundle_number=b.bundle_number,
                paper_code=p.paper_code,
                course_title=title,
                max_marks=p.max_marks,
                qp_pattern=p.qp_pattern,
                valuation_round=a.valuation_round,
                status=a.status,
                due_at=a.due_at,
                scripts=by_id[a.id].scripts,
                valued=by_id[a.id].valued,
            )
            for a, b, p, title in rows
        ]

    async def bundle_scripts(self, bid: uuid.UUID) -> list[EvaluatorScript]:
        a = await self._my_assignment(bid)
        rows = (
            await self.db.execute(
                select(AnswerScriptForEvaluation, ScriptValuation)
                .outerjoin(
                    ScriptValuation,
                    (ScriptValuation.answer_script_id == AnswerScriptForEvaluation.id)
                    & (ScriptValuation.valuation_round == a.valuation_round),
                )
                .where(
                    AnswerScriptForEvaluation.bundle_id == bid,
                    AnswerScriptForEvaluation.institution_id == self.inst,
                )
                .order_by(AnswerScriptForEvaluation.dummy_number)
            )
        ).all()
        return [
            EvaluatorScript(
                id=s.id,
                dummy_number=s.dummy_number,
                pages=s.pages,
                scan_available=bool(s.scan_url),
                status=s.status,
                marks=v.marks if v else None,
                question_wise=v.question_wise if v else None,
                is_locked=bool(v and v.is_locked),
            )
            for s, v in rows
        ]

    async def _script_for_me(
        self, script_id: uuid.UUID, rnd: int
    ) -> tuple[AnswerScriptForEvaluation, ValuationAssignment]:
        sc = (
            await self.db.execute(
                select(AnswerScriptForEvaluation).where(
                    AnswerScriptForEvaluation.id == script_id, AnswerScriptForEvaluation.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if sc is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Script not found")
        try:
            a = await self._my_assignment(sc.bundle_id, rnd)
        except APIError:
            raise APIError(404, ErrorCode.NOT_FOUND, "Script not found") from None
        return sc, a

    async def submit_valuation(self, script_id: uuid.UUID, rnd: int, body: ValuationSubmit) -> ScriptValuationResponse:
        if rnd >= 90:
            raise APIError(404, ErrorCode.NOT_FOUND, "Script not found")  # revaluation marks go through Phase 16
        sc, a = await self._script_for_me(script_id, rnd)
        if a.status in ("submitted", "verified"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The bundle has been submitted; valuations are locked")
        p = (await self.db.execute(select(ExamPaper).where(ExamPaper.id == a.exam_paper_id))).scalar_one()
        if body.marks > p.max_marks:
            raise APIError(422, ErrorCode.VALIDATION, f"Marks exceed the paper maximum ({p.max_marks})")
        if body.question_wise:
            maxes = pattern_max(p.qp_pattern)
            bad = {q: str(m) for q, m in body.question_wise.items() if q in maxes and m > maxes[q]}
            unknown = [q for q in body.question_wise if maxes and q not in maxes]
            if bad or unknown:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "Question-wise marks exceed the question maximum",
                    {"over_max": bad, "unknown_questions": unknown},
                )
            if q2(sum(body.question_wise.values(), Decimal(0))) != q2(body.marks):
                raise APIError(422, ErrorCode.VALIDATION, "Question-wise marks do not add up to the total")
        v = (
            await self.db.execute(
                select(ScriptValuation)
                .where(ScriptValuation.answer_script_id == sc.id, ScriptValuation.valuation_round == rnd)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if v is not None and v.is_locked:
            raise APIError(409, ErrorCode.RECORD_LOCKED, "This valuation is locked")
        qw = {k: float(x) for k, x in (body.question_wise or {}).items()} or None
        if v is None:
            v = ScriptValuation(
                institution_id=self.inst,
                answer_script_id=sc.id,
                valuation_round=rnd,
                evaluator_user_id=self.actor_id,
                marks=q2(body.marks),
                question_wise=qw,
                annotations_url=body.annotations_url,
            )
            self.db.add(v)
        else:
            v.marks, v.question_wise, v.annotations_url, v.submitted_at = (
                q2(body.marks),
                qw,
                body.annotations_url,
                now_utc(),
            )
        if a.status == "assigned":
            a.status = "in_progress"
        await self.db.flush()
        return ScriptValuationResponse.model_validate(v, from_attributes=True)

    async def submit_bulk(self, body: BulkValuationSubmit) -> list[ScriptValuationResponse]:
        return [
            await self.submit_valuation(
                r.answer_script_id, body.round, ValuationSubmit(marks=r.marks, question_wise=r.question_wise)
            )
            for r in body.rows
        ]

    async def submit_bundle(self, bid: uuid.UUID) -> ValuationAssignmentResponse:
        a = await self._my_assignment(bid)
        if a.status in ("submitted", "verified"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The bundle has already been submitted")
        scripts = list((await self.db.execute(select(AnswerScript).where(AnswerScript.bundle_id == bid))).scalars())
        vals = {
            v.answer_script_id: v
            for v in (
                await self.db.execute(
                    select(ScriptValuation).where(
                        ScriptValuation.answer_script_id.in_([s.id for s in scripts]),
                        ScriptValuation.valuation_round == a.valuation_round,
                    )
                )
            ).scalars()
        }
        missing = [s.dummy_number for s in scripts if s.id not in vals]
        if missing:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"{len(missing)} script(s) are not valued yet",
                {"dummy_numbers": missing[:50]},
            )
        for v in vals.values():
            v.is_locked = True
        a.status, a.submitted_at = "submitted", now_utc()
        # bundle valuated once every assigned round is submitted
        rounds = (
            (await self.db.execute(select(ValuationAssignment.status).where(ValuationAssignment.bundle_id == bid)))
            .scalars()
            .all()
        )
        if all(r in ("submitted", "verified") for r in rounds):
            b = (await self.db.execute(select(AnswerScriptBundle).where(AnswerScriptBundle.id == bid))).scalar_one()
            b.status = "valuated"
            for s in scripts:
                if s.status in ("in_valuation", "third_valuation", "coded"):
                    s.status = "valuated"
        await self.db.flush()
        await self._emit(
            "valuation.submitted",
            {"bundle_id": str(bid), "round": a.valuation_round, "paper_id": str(a.exam_paper_id)},
            "valuation_assignment",
            a.id,
        )
        return (await self._assignment_out([a]))[0]

    async def scan_url(self, script_id: uuid.UUID) -> dict[str, Any]:
        from app.core.files import storage

        sc = (
            await self.db.execute(
                select(AnswerScriptForEvaluation).where(
                    AnswerScriptForEvaluation.id == script_id, AnswerScriptForEvaluation.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if sc is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Script not found")
        await self._my_assignment(sc.bundle_id)
        if not sc.scan_url:
            raise APIError(404, ErrorCode.NOT_FOUND, "No scan uploaded for this script")
        url = sc.scan_url if sc.scan_url.startswith("http") else storage.signed_url(sc.scan_url, 600)
        return {"url": url, "expires_in": 600, "pages": sc.pages}

    # ---- 3. reconciliation -------------------------------------------------------------------------------------------
    async def _paper_rules(self, p: ExamPaper) -> dict[str, Any]:
        from app.models.curriculum import Course
        from app.services.academics.rules import RulesResolver

        reg = (await self.db.execute(select(Course.regulation_id).where(Course.id == p.course_id))).scalar_one()
        rules, _ = await RulesResolver(self.db).for_regulation(reg)
        return rules

    async def _paper_scripts(self, p: ExamPaper) -> list[AnswerScript]:
        return list(
            (
                await self.db.execute(
                    select(AnswerScript)
                    .join(AnswerScriptBundle, AnswerScriptBundle.id == AnswerScript.bundle_id)
                    .where(AnswerScriptBundle.exam_paper_id == p.id)
                    .with_for_update(of=AnswerScript)
                )
            ).scalars()
        )

    async def reconcile(self, pid: uuid.UUID) -> ReconcileSummary:
        p, s = await self.paper(pid)
        rules = await self._paper_rules(p)
        dv = rules.get("double_valuation") or {}
        rule_name = str(dv.get("resolution") or "avg_closest_two")
        pct = float(s.discrepancy_pct if s.discrepancy_pct is not None else dv.get("discrepancy_pct", 15))
        tol = q2(Decimal(str(pct)) / 100 * p.max_marks)
        double = s.valuation_mode == "double"
        scripts = await self._paper_scripts(p)
        vals: dict[uuid.UUID, dict[int, Decimal]] = defaultdict(dict)
        for sv in (
            await self.db.execute(
                select(ScriptValuation).where(
                    ScriptValuation.answer_script_id.in_([sc.id for sc in scripts]), ScriptValuation.is_locked.is_(True)
                )
            )
        ).scalars():
            vals[sv.answer_script_id][sv.valuation_round] = sv.marks
        finals = {
            f.answer_script_id: f
            for f in (
                await self.db.execute(
                    select(ScriptFinalMarks)
                    .where(ScriptFinalMarks.answer_script_id.in_([sc.id for sc in scripts]))
                    .with_for_update()
                )
            ).scalars()
        }
        resolved = needs = 0
        discs: list[Decimal] = []
        listing: list[dict[str, Any]] = []
        for sc in scripts:
            f = finals.get(sc.id)
            if f is not None and f.status == "final":
                continue  # decoded — never recomputed here
            v = vals.get(sc.id, {})
            if 1 not in v or (double and 2 not in v):
                continue
            if f is None:
                f = ScriptFinalMarks(institution_id=self.inst, answer_script_id=sc.id)
                self.db.add(f)
            f.marks_v1, f.marks_v2, f.marks_v3 = v.get(1), v.get(2), v.get(3)
            if not double:
                f.computed_marks, f.rule_applied, f.discrepancy = q2(v[1]), "single", None
            else:
                d = abs(v[1] - v[2])
                f.discrepancy = q2(d)
                discs.append(d)
                if d > tol and 3 not in v:
                    f.status, f.rule_applied, f.computed_marks, f.final_marks = "needs_third", None, None, None
                    sc.status = "discrepancy"
                    needs += 1
                    listing.append(
                        {
                            "answer_script_id": str(sc.id),
                            "dummy_number": sc.dummy_number,
                            "v1": float(v[1]),
                            "v2": float(v[2]),
                            "discrepancy": float(d),
                        }
                    )
                    continue
                f.computed_marks = resolve(v[1], v[2], v.get(3) if d > tol else None, rule_name)
                f.rule_applied = rule_name if d > tol else "avg_two"
            if f.moderation_action_id is None:
                f.final_marks, f.status = f.computed_marks, "resolved"
            sc.status = "finalized" if f.status == "resolved" else sc.status
            resolved += 1
        await self.db.flush()
        out = ReconcileSummary(
            resolved=resolved,
            needs_third=needs,
            average_discrepancy=float(q2(statistics.fmean(discs))) if discs else None,
            rule=rule_name if double else "single",
            tolerance=float(tol),
            discrepancies=listing,
        )
        await self._audit("valuation_reconcile", "exam_paper", p.id, None, out.model_dump(exclude={"discrepancies"}))
        await self._emit(
            "valuation.reconciled",
            {"paper_id": str(p.id), "resolved": resolved, "needs_third": needs},
            "exam_paper",
            p.id,
        )
        return out

    async def third_assign(self, pid: uuid.UUID, body: ThirdValuationAssign) -> list[ValuationAssignmentResponse]:
        p, s = await self.paper(pid)
        bids = list(
            (
                await self.db.execute(
                    select(AnswerScript.bundle_id)
                    .join(ScriptFinalMarks, ScriptFinalMarks.answer_script_id == AnswerScript.id)
                    .join(AnswerScriptBundle, AnswerScriptBundle.id == AnswerScript.bundle_id)
                    .where(AnswerScriptBundle.exam_paper_id == p.id, ScriptFinalMarks.status == "needs_third")
                    .distinct()
                )
            ).scalars()
        )
        if not bids:
            raise rule("No script needs a third valuation — reconcile first", "NOTHING_TO_ASSIGN", 422)
        already = set(
            (
                await self.db.execute(
                    select(ValuationAssignment.bundle_id).where(
                        ValuationAssignment.bundle_id.in_(bids), ValuationAssignment.valuation_round == 3
                    )
                )
            ).scalars()
        )
        bids = [b for b in bids if b not in already]
        if not bids:
            raise APIError(409, ErrorCode.CONFLICT, "Third valuations are already assigned")
        staff_id, user_id, ext, _ = await self._evaluator(p, s, body.evaluator_staff_id, body.external_evaluator)
        return await self._create_assignments(
            p,
            bids,
            3,
            staff_id,
            user_id,
            ext,
            "internal" if staff_id else "external",
            body.due_at,
            body.remuneration_paise,
        )

    # ---- 4. moderation -------------------------------------------------------------------------------------------------
    async def _action(self, mid: uuid.UUID) -> ModerationAction:
        m = (
            await self.db.execute(
                select(ModerationAction)
                .where(ModerationAction.id == mid, ModerationAction.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if m is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Moderation action not found")
        await self.paper(m.exam_paper_id)
        return m

    @staticmethod
    def _apply_rule(action_type: str, r: dict[str, Any], marks: list[Decimal], mx: Decimal) -> list[Decimal]:
        def clamp(x: Decimal) -> Decimal:
            return q2(min(max(x, Decimal(0)), mx))

        if action_type in ("scale_up", "scale_down"):
            f = Decimal(str(r.get("factor", 1)))
            return [clamp(m * f) for m in marks]
        if action_type == "add_flat":
            k = Decimal(str(r.get("marks", 0)))
            return [clamp(m + k) for m in marks]
        if action_type == "grace":
            below, up = Decimal(str(r.get("below", 0))), Decimal(str(r.get("up_to", 0)))
            return [clamp(below) if below - up <= m < below else m for m in marks]
        if action_type == "cap":
            c = Decimal(str(r.get("cap", mx)))
            return [clamp(min(m, c)) for m in marks]
        if action_type == "normalize" and len(marks) > 1:
            mean, sd = statistics.fmean(float(m) for m in marks), statistics.pstdev(float(m) for m in marks)
            tm, tsd = float(r.get("target_mean", mean)), float(r.get("target_sd", sd or 1))
            return [clamp(Decimal(str(tm + (float(m) - mean) / (sd or 1) * tsd))) for m in marks]
        return list(marks)

    async def _paper_finals(self, p: ExamPaper) -> list[ScriptFinalMarks]:
        return list(
            (
                await self.db.execute(
                    select(ScriptFinalMarks)
                    .join(AnswerScript, AnswerScript.id == ScriptFinalMarks.answer_script_id)
                    .join(AnswerScriptBundle, AnswerScriptBundle.id == AnswerScript.bundle_id)
                    .where(AnswerScriptBundle.exam_paper_id == p.id)
                    .with_for_update(of=ScriptFinalMarks)
                )
            ).scalars()
        )

    async def _moderation_out(self, m: ModerationAction, preview: bool = False) -> ModerationResponse:
        out = ModerationResponse.model_validate(m, from_attributes=True)
        if preview and m.status in ("proposed", "approved"):
            p = (await self.db.execute(select(ExamPaper).where(ExamPaper.id == m.exam_paper_id))).scalar_one()
            base = [f.computed_marks for f in await self._paper_finals(p) if f.computed_marks is not None]
            new = self._apply_rule(m.action_type, m.rule, base, p.max_marks)
            changed = sum(1 for a, b in zip(base, new, strict=True) if a != b)
            out.preview = {
                "scripts": len(base),
                "affected": changed,
                "mean_before": float(q2(statistics.fmean(base))) if base else None,
                "mean_after": float(q2(statistics.fmean(new))) if new else None,
            }
        return out

    async def list_moderation(self, pid: uuid.UUID) -> list[ModerationResponse]:
        p, _ = await self.paper(pid)
        rows = (
            await self.db.execute(
                select(ModerationAction)
                .where(ModerationAction.exam_paper_id == p.id)
                .order_by(ModerationAction.created_at)
            )
        ).scalars()
        return [await self._moderation_out(m, preview=True) for m in rows]

    async def propose(self, pid: uuid.UUID, body: ModerationProposal) -> ModerationResponse:
        p, _ = await self.paper(pid)
        if any(f.status == "final" for f in await self._paper_finals(p)):
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The paper is decoded; moderation is closed")
        m = ModerationAction(
            institution_id=self.inst,
            exam_paper_id=p.id,
            action_type=body.action_type,
            rule=body.rule,
            justification=body.justification,
            proposed_by=self.actor_id or uuid.UUID(int=0),
            status="proposed",
        )
        self.db.add(m)
        await self.db.flush()
        await self._audit(
            "moderation_propose", "moderation_action", m.id, None, {"type": m.action_type, "rule": m.rule}
        )
        await self._emit("moderation.proposed", {"paper_id": str(p.id)}, "moderation_action", m.id)
        return await self._moderation_out(m, preview=True)

    async def approve(self, mid: uuid.UUID) -> ModerationResponse:
        if not self.can("exams", "manage"):
            raise APIError(
                403,
                ErrorCode.PERMISSION_DENIED,
                "Moderation is approved by the controller of examinations (exams:manage)",
            )
        m = await self._action(mid)
        if m.status != "proposed":
            raise rule(f"A {m.status} action cannot be approved", "INVALID_TRANSITION")
        m.status, m.approved_by = "approved", self.actor_id
        await self.db.flush()
        await self._audit(
            "moderation_approve", "moderation_action", m.id, {"status": "proposed"}, {"status": "approved"}
        )
        await self._emit("moderation.approved", {"paper_id": str(m.exam_paper_id)}, "moderation_action", m.id)
        return await self._moderation_out(m, preview=True)

    async def apply(self, mid: uuid.UUID) -> ModerationResponse:
        m = await self._action(mid)
        if m.status != "approved":
            raise rule("Only an approved action can be applied", "INVALID_TRANSITION")
        p = (await self.db.execute(select(ExamPaper).where(ExamPaper.id == m.exam_paper_id))).scalar_one()
        finals = [f for f in await self._paper_finals(p) if f.computed_marks is not None]
        if any(f.status == "final" for f in finals):
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The paper is decoded; moderation is closed")
        if any(f.moderation_action_id is not None for f in finals):
            raise rule("Another moderation action is applied — revert it first", "MODERATION_ACTIVE")
        new = self._apply_rule(m.action_type, m.rule, [f.computed_marks for f in finals], p.max_marks)  # type: ignore[misc]
        n = 0
        script_ids = []
        for f, nm in zip(finals, new, strict=True):
            if nm != f.computed_marks:
                n += 1
            f.moderated_marks, f.final_marks, f.moderation_action_id, f.status = nm, nm, m.id, "moderated"
            script_ids.append(f.answer_script_id)
        for sc in (await self.db.execute(select(AnswerScript).where(AnswerScript.id.in_(script_ids)))).scalars():
            sc.status = "moderated"
        m.status, m.affected_count = "applied", n
        await self.db.flush()
        await self._audit("moderation_apply", "moderation_action", m.id, None, {"affected": n})
        await self._emit("moderation.applied", {"paper_id": str(p.id), "affected": n}, "moderation_action", m.id)
        return await self._moderation_out(m)

    async def revert(self, mid: uuid.UUID) -> ModerationResponse:
        m = await self._action(mid)
        if m.status != "applied":
            raise rule("Only an applied action can be reverted", "INVALID_TRANSITION")
        p = (await self.db.execute(select(ExamPaper).where(ExamPaper.id == m.exam_paper_id))).scalar_one()
        finals = [f for f in await self._paper_finals(p) if f.moderation_action_id == m.id]
        if any(f.status == "final" for f in finals):
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The paper is decoded; moderation can no longer be reverted")
        for f in finals:
            f.moderated_marks, f.final_marks, f.moderation_action_id, f.status = (
                None,
                f.computed_marks,
                None,
                "resolved",
            )
        for sc in (
            await self.db.execute(select(AnswerScript).where(AnswerScript.id.in_([f.answer_script_id for f in finals])))
        ).scalars():
            sc.status = "finalized"
        m.status = "reverted"
        await self.db.flush()
        await self._audit("moderation_revert", "moderation_action", m.id, {"status": "applied"}, {"status": "reverted"})
        return await self._moderation_out(m)

    # ---- 5. decode -----------------------------------------------------------------------------------------------------
    async def decode(self, pid: uuid.UUID) -> DecodeResponse:
        p, _ = await self.paper(pid, for_update=True)
        scripts = await self._paper_scripts(p)
        if not scripts:
            raise rule("The paper has no scripts", "NOTHING_TO_DECODE", 422)
        finals = {f.answer_script_id: f for f in await self._paper_finals(p)}
        pending = [
            sc.dummy_number
            for sc in scripts
            if finals.get(sc.id) is None or finals[sc.id].status not in ("resolved", "moderated", "final")
        ]
        if pending:
            raise rule(
                f"{len(pending)} script(s) are not finalized (valuation / reconciliation pending)",
                "VALUATION_INCOMPLETE",
                dummy_numbers=pending[:50],
            )
        written = 0
        for sc in scripts:
            f = finals[sc.id]
            if f.status != "final":
                f.status = "final"
                written += 1
            sc.status = "decoded"
        for b in (
            await self.db.execute(
                select(AnswerScriptBundle).where(AnswerScriptBundle.exam_paper_id == p.id).with_for_update()
            )
        ).scalars():
            if b.status != "archived":
                b.status = "decoded"
        p.status = "finalized"
        await self.db.flush()
        await self._audit("exams:decode", "exam_paper", p.id, None, {"decoded": len(scripts), "ese_written": written})
        await self._emit("scripts.decoded", {"paper_id": str(p.id), "count": len(scripts)}, "exam_paper", p.id)
        return DecodeResponse(paper=p.id, decoded_count=len(scripts), ese_marks_written=written)

    # ---- 6. online papers ------------------------------------------------------------------------------------------------
    async def import_online(self, pid: uuid.UUID) -> OnlineImportResponse:
        from app.models.lms import QuizAttempt

        p, _ = await self.paper(pid, for_update=True)
        if p.quiz_id is None:
            raise rule("The paper is not an online paper", "NOT_ONLINE", 422)
        items = (
            await self.db.execute(
                select(ExamRegistrationItem, ExamRegistration.student_program_enrollment_id)
                .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
                .where(
                    ExamRegistrationItem.exam_paper_id == p.id,
                    ExamRegistrationItem.id.notin_(select(AnswerScript.exam_registration_item_id)),
                )
            )
        ).all()
        best = dict(
            (
                await self.db.execute(
                    select(QuizAttempt.student_program_enrollment_id, func.max(QuizAttempt.total_score))
                    .where(QuizAttempt.quiz_id == p.quiz_id, QuizAttempt.submitted_at.is_not(None))
                    .group_by(QuizAttempt.student_program_enrollment_id)
                )
            ).all()
        )
        b = AnswerScriptBundle(
            institution_id=self.inst,
            exam_paper_id=p.id,
            bundle_number=f"{(p.paper_code or 'P')[:12]}-ONLINE-{uuid.uuid4().hex[:4]}",
            script_count=0,
            status="decoded",
            coded_by=self.actor_id,
            coded_at=now_utc(),
        )
        self.db.add(b)
        await self.db.flush()
        n = 0
        for item, enr in items:
            score = best.get(enr)
            if score is None:
                continue
            n += 1
            sc = AnswerScript(
                institution_id=self.inst,
                exam_registration_item_id=item.id,
                bundle_id=b.id,
                dummy_number=f"Q{n:05d}",
                status="decoded",
            )
            self.db.add(sc)
            await self.db.flush()
            mk = q2(min(Decimal(score), p.max_marks))
            self.db.add(
                ScriptFinalMarks(
                    institution_id=self.inst,
                    answer_script_id=sc.id,
                    marks_v1=mk,
                    computed_marks=mk,
                    final_marks=mk,
                    rule_applied="online_quiz",
                    status="final",
                )
            )
        b.script_count = n
        await self.db.flush()
        await self._audit("online_import", "exam_paper", p.id, None, {"items": n})
        return OnlineImportResponse(paper=p.id, items=n)

    async def due_reminders(self) -> int:
        """Beat (daily): remind evaluators of bundles due within two days."""
        from datetime import timedelta

        soon = now_utc() + timedelta(days=2)
        rows = (
            await self.db.execute(
                select(ValuationAssignment.evaluator_user_id, func.count())
                .where(
                    ValuationAssignment.institution_id == self.inst,
                    ValuationAssignment.status.in_(("assigned", "accepted", "in_progress")),
                    ValuationAssignment.due_at.is_not(None),
                    ValuationAssignment.due_at <= soon,
                    ValuationAssignment.evaluator_user_id.is_not(None),
                )
                .group_by(ValuationAssignment.evaluator_user_id)
            )
        ).all()
        for uid, n in rows:
            await self._notify("valuation.due_reminder", [uid], {"bundles": int(n)})
        return len(rows)
