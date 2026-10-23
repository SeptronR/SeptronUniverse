"""Rank lists, medals and result corrections — Prompts/16 §16.6 ``rank_service`` / ``correction_service``.

Rank lists ({results.rank_lists}): term rank (SGPA of the term) or cumulative rank (CGPA of each student's latest
published term) per batch (optionally one programme) over **current published** term results; ties break by CGPA,
then credits earned, then the earlier registration number (``tie_break`` explains each step that decided a pair);
students with active arrears are left out when the regulation's ``rules.class_rules.first_attempt_only`` is set.
Publishing stores an immutable snapshot as an audit row (record type ``rank_list`` — no table; public reads go
through ``GET /public/results/rank-lists/{id}`` with masked names when published ``public`` and setting
``exams.rank_list_public``). Students read their own rank from published lists.

Medals: ``student_achievements(category='academic', position=gold|silver|bronze)`` rows; revoke deletes the row.

Corrections: staff-raised corrections on a published row → workflow ``marks.change`` (entity ``course_result_correction``,
context carries the row, reason and ESE delta; HOD → COE) → approval computes a ``correction`` run (``marks_delta``)
the COE verifies / approves / publishes.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.platform import WorkflowDefinition, WorkflowInstance
from app.models.post_result import StudentAchievement
from app.models.registration import StudentArrear
from app.models.results import StudentCourseResult, StudentTermResult
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.repositories.fee_scope import own_enrollment_ids
from app.schemas.post_result import (
    CorrectionRequestCreate,
    CorrectionResponse,
    MedalAwardCreate,
    MedalResponse,
    RankListEntry,
    RankListPublish,
    RankListResponse,
)
from app.services.exams.common import mask, now_utc, rule
from app.services.post_result.common import PostResultBase

WF_CORRECTION = "marks.change"
CORRECTION_ENTITY = "course_result_correction"
MEDALS = ("gold", "silver", "bronze")


class RankService(PostResultBase):
    audit_module = "results"

    async def compute(
        self, batch_id: uuid.UUID, term_id: uuid.UUID | None, program_id: uuid.UUID | None, top_n: int = 50
    ) -> RankListResponse:
        q = (
            select(Student, StudentProgramEnrollment, StudentTermResult, StudentTermRecord)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
            .join(StudentTermRecord, StudentTermRecord.student_program_enrollment_id == StudentProgramEnrollment.id)
            .join(StudentTermResult, StudentTermResult.student_term_record_id == StudentTermRecord.id)
            .where(
                StudentProgramEnrollment.institution_id == self.inst,
                StudentProgramEnrollment.batch_id == batch_id,
                StudentTermResult.is_current.is_(True),
                StudentTermResult.status == "published",
            )
        )
        if program_id:
            q = q.where(StudentProgramEnrollment.program_id == program_id)
        if term_id:
            q = q.where(StudentTermRecord.term_id == term_id)
        best: dict[uuid.UUID, tuple[Student, StudentProgramEnrollment, StudentTermResult, StudentTermRecord]] = {}
        for st, e, t, rec in (await self.db.execute(q)).all():
            if e.id not in best or rec.term_number > best[e.id][3].term_number:
                best[e.id] = (st, e, t, rec)
        first_attempt: dict[uuid.UUID, bool] = {}
        arrears = set(
            (
                await self.db.execute(
                    select(StudentArrear.student_program_enrollment_id).where(
                        StudentArrear.student_program_enrollment_id.in_(list(best) or [uuid.uuid4()]),
                        StudentArrear.status == "open",
                    )
                )
            ).scalars()
        )
        from app.services.academics.rules import RulesResolver

        resolver = RulesResolver(self.db)
        kept = []
        for v in best.values():
            pr = v[1].program_regulation_id
            if pr not in first_attempt:
                cr = (await resolver.for_program_regulation(pr)).get("class_rules") or {}
                first_attempt[pr] = (
                    bool(cr.get("first_attempt_only"))
                    if isinstance(cr, dict)
                    else any(isinstance(x, dict) and x.get("first_attempt_only") for x in cr)
                )
            if first_attempt[pr] and v[1].id in arrears:
                continue
            kept.append(v)

        def score(v: Any) -> Decimal:
            return (v[2].sgpa if term_id else v[2].cgpa) or Decimal(0)

        def key(v: Any) -> tuple[Any, ...]:
            return (
                -score(v),
                -(v[2].cgpa or Decimal(0)),
                -(v[2].cumulative_credits or v[2].credits_earned or Decimal(0)),
                v[0].registration_number or "",
            )

        ranked = sorted(kept, key=key)
        entries: list[RankListEntry] = []
        prev = None
        for i, v in enumerate(ranked[:top_n], start=1):
            st, e, t, _ = v
            tie = None
            if prev is not None and score(prev) == score(v):
                if (prev[2].cgpa or 0) != (t.cgpa or 0):
                    tie = "CGPA"
                elif (prev[2].cumulative_credits or prev[2].credits_earned) != (
                    t.cumulative_credits or t.credits_earned
                ):
                    tie = "credits earned"
                else:
                    tie = "registration number"
            name = " ".join(x for x in (st.first_name, st.last_name) if x)
            entries.append(
                RankListEntry(
                    rank=i,
                    student_program_enrollment_id=e.id,
                    student_masked=mask(name) or "",
                    registration_number=st.registration_number,
                    sgpa=t.sgpa,
                    cgpa=t.cgpa,
                    credits=t.cumulative_credits or t.credits_earned,
                    tie_break=f"tied on {'SGPA' if term_id else 'CGPA'} — ordered by {tie}" if tie else None,
                )
            )
            prev = v
        return RankListResponse(
            batch_id=batch_id, term_id=term_id, cumulative=term_id is None, program_id=program_id, entries=entries
        )

    async def publish(self, body: RankListPublish) -> RankListResponse:
        out = await self.compute(body.batch_id, body.term_id, body.program_id, body.top_n)
        lid = uuid.uuid4()
        out.published_at, out.key = now_utc(), str(lid)
        await self._audit(
            "rank_list_publish",
            "rank_list",
            lid,
            None,
            {"public": body.public, **out.model_dump(mode="json")},
        )
        await self._emit(
            "rank_list.published", {"rank_list_id": str(lid), "batch_id": str(body.batch_id)}, "rank_list", lid
        )
        return out

    async def _published(self, lid: uuid.UUID | None = None) -> list[tuple[uuid.UUID, dict[str, Any]]]:
        sql = "SELECT record_id, new_values FROM audit_logs WHERE institution_id = CAST(:i AS uuid) AND record_type = 'rank_list' AND action = 'rank_list_publish'"
        params: dict[str, Any] = {"i": str(self.inst)}
        if lid:
            sql += " AND record_id = CAST(:r AS uuid)"
            params["r"] = str(lid)
        rows = (await self.db.execute(text(sql + " ORDER BY occurred_at DESC LIMIT 200"), params)).all()
        return [(r, nv or {}) for r, nv in rows]

    async def published_lists(self) -> list[RankListResponse]:
        out = []
        for lid, nv in await self._published():
            d = {k: v for k, v in nv.items() if k in RankListResponse.model_fields}
            d["key"] = str(lid)
            out.append(RankListResponse.model_validate(d))
        return out

    async def my_ranks(self) -> list[dict[str, Any]]:
        mine = {str(e) for e in (await self.db.execute(own_enrollment_ids(self.principal, advisees=False))).scalars()}
        out = []
        for lid, nv in await self._published():
            for en in nv.get("entries") or []:
                if en.get("student_program_enrollment_id") in mine:
                    out.append(
                        {
                            "rank_list_id": str(lid),
                            "term_id": nv.get("term_id"),
                            "cumulative": nv.get("cumulative"),
                            "rank": en.get("rank"),
                            "sgpa": en.get("sgpa"),
                            "cgpa": en.get("cgpa"),
                            "published_at": nv.get("published_at"),
                        }
                    )
        return out

    # ---- medals ----------------------------------------------------------------------------------------------------------
    async def medal_outs(self, rows: list[StudentAchievement]) -> list[MedalResponse]:
        people: dict[uuid.UUID, Student] = dict(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.id, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(
                        StudentProgramEnrollment.id.in_(
                            {r.student_program_enrollment_id for r in rows} or {uuid.uuid4()}
                        )
                    )
                )
            )
            .tuples()
            .all()
        )
        out = []
        for r in rows:
            o = MedalResponse.model_validate(r, from_attributes=True)
            st = people.get(r.student_program_enrollment_id)
            if st:
                o.student_name = " ".join(x for x in (st.first_name, st.last_name) if x)
                o.registration_number = st.registration_number
            out.append(o)
        return out

    async def medals(self, batch_id: uuid.UUID | None) -> list[MedalResponse]:
        q = select(StudentAchievement).where(
            StudentAchievement.institution_id == self.inst,
            StudentAchievement.category == "academic",
            StudentAchievement.position.in_(MEDALS),
        )
        if batch_id:
            q = q.where(
                StudentAchievement.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.batch_id == batch_id)
                )
            )
        return await self.medal_outs(
            list((await self.db.execute(q.order_by(StudentAchievement.created_at.desc()))).scalars())
        )

    async def award(self, body: MedalAwardCreate) -> MedalResponse:
        from app.models.academic import Batch, Program

        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(
                    StudentProgramEnrollment.id == body.student_program_enrollment_id,
                    StudentProgramEnrollment.institution_id == self.inst,
                    StudentProgramEnrollment.batch_id == body.batch_id,
                )
            )
        ).scalar_one_or_none()
        if e is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Enrolment not found in this batch")
        dup = (
            await self.db.execute(
                select(StudentAchievement.id)
                .join(
                    StudentProgramEnrollment,
                    StudentProgramEnrollment.id == StudentAchievement.student_program_enrollment_id,
                )
                .where(
                    StudentAchievement.category == "academic",
                    StudentAchievement.position == body.medal,
                    StudentProgramEnrollment.batch_id == body.batch_id,
                    StudentProgramEnrollment.program_id == e.program_id,
                )
            )
        ).first()
        if dup:
            raise APIError(
                409, ErrorCode.CONFLICT, f"The {body.medal} medal of this programme and batch is already awarded"
            )
        prog = (await self.db.execute(select(Program.code).where(Program.id == e.program_id))).scalar_one_or_none()
        batch = (await self.db.execute(select(Batch.code).where(Batch.id == e.batch_id))).scalar_one_or_none()
        a = StudentAchievement(
            institution_id=self.inst,
            student_program_enrollment_id=e.id,
            category="academic",
            title=(body.citation or f"{body.medal.title()} medal — {prog or ''} {batch or ''}".strip())[:200],
            level="institution",
            position=body.medal,
            held_on=await self.today(),
            verified_by=self.actor_id,
            verified_at=now_utc(),
        )
        self.db.add(a)
        await self.db.flush()
        await self._audit(
            "medal_award", "student_achievement", a.id, None, {"medal": body.medal, "enrollment_id": str(e.id)}
        )
        await self._emit(
            "medal.awarded", {"achievement_id": str(a.id), "medal": body.medal}, "student_achievement", a.id
        )
        return (await self.medal_outs([a]))[0]

    async def revoke(self, mid: uuid.UUID) -> dict[str, Any]:
        a = (
            await self.db.execute(
                select(StudentAchievement).where(
                    StudentAchievement.id == mid, StudentAchievement.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if a is None or a.category != "academic":
            raise APIError(404, ErrorCode.NOT_FOUND, "Medal not found")
        await self._audit("medal_revoke", "student_achievement", a.id, {"title": a.title, "position": a.position}, None)
        await self.db.delete(a)
        await self.db.flush()
        return {"revoked": str(mid)}


async def public_rank_list(lid: uuid.UUID) -> dict[str, Any]:
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT institution_id, new_values FROM audit_logs WHERE record_type = 'rank_list' "
                    "AND action = 'rank_list_publish' AND record_id = CAST(:r AS uuid) LIMIT 1"
                ),
                {"r": str(lid)},
            )
        ).first()
        if row is None or not (row[1] or {}).get("public"):
            raise APIError(404, ErrorCode.NOT_FOUND, "Rank list not found")
        from app.services.settings_service import SettingsService

        if not await SettingsService(db).value(row[0], "exams", "rank_list_public"):
            raise APIError(404, ErrorCode.NOT_FOUND, "Rank list not found")
    nv = row[1]
    return {
        "term_id": nv.get("term_id"),
        "cumulative": nv.get("cumulative"),
        "published_at": nv.get("published_at"),
        "entries": [
            {
                "rank": e.get("rank"),
                "student_masked": e.get("student_masked"),
                "sgpa": e.get("sgpa"),
                "cgpa": e.get("cgpa"),
            }
            for e in nv.get("entries") or []
        ],
    }


class CorrectionService(PostResultBase):
    audit_module = "results"

    async def _instances(self, entity_id: uuid.UUID | None = None) -> list[WorkflowInstance]:
        q = (
            select(WorkflowInstance)
            .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowInstance.definition_id)
            .where(
                WorkflowInstance.institution_id == self.inst,
                WorkflowInstance.entity_type == CORRECTION_ENTITY,
                WorkflowDefinition.key == WF_CORRECTION,
            )
        )
        if entity_id:
            q = q.where(WorkflowInstance.entity_id == entity_id)
        return list((await self.db.execute(q.order_by(WorkflowInstance.started_at.desc()).limit(500))).scalars())

    @staticmethod
    def out(i: WorkflowInstance) -> CorrectionResponse:
        ctx = i.context or {}
        status = ctx.get("outcome") or {"pending": "pending", "escalated": "pending"}.get(i.status, i.status)
        return CorrectionResponse(
            id=i.entity_id,
            result_id=uuid.UUID(ctx["result_id"]) if ctx.get("result_id") else None,
            status=status,
            reason=ctx.get("reason"),
            ese_delta=Decimal(str(ctx.get("ese_delta", 0))),
            started_at=i.started_at,
            run_id=uuid.UUID(ctx["run_id"]) if ctx.get("run_id") else None,
        )

    async def list_corrections(self, status: str | None) -> list[CorrectionResponse]:
        return [x for x in (self.out(i) for i in await self._instances()) if status is None or x.status == status]

    async def create(self, body: CorrectionRequestCreate) -> CorrectionResponse:
        from app.models.hr import Staff
        from app.models.offerings import CourseOffering, CourseOfferingFaculty

        r = (
            await self.db.execute(
                select(StudentCourseResult).where(
                    StudentCourseResult.id == body.result_id, StudentCourseResult.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Result not found")
        if r.status != "published" or not r.is_current:
            raise rule("Corrections apply to the current published row", "NOT_CURRENT")
        if not (self.can("marks", "correct") or self.can("results", "verify")):
            teaches = (
                await self.db.execute(
                    select(CourseOfferingFaculty.id)
                    .join(CourseOffering, CourseOffering.id == CourseOfferingFaculty.offering_id)
                    .join(Staff, Staff.id == CourseOfferingFaculty.staff_id)
                    .where(
                        CourseOffering.course_id == r.course_id,
                        CourseOffering.term_id == r.term_id,
                        Staff.user_id == self.actor_id,
                    )
                )
            ).first()
            if teaches is None:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only teachers of the course raise corrections")
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == r.student_program_enrollment_id)
            )
        ).scalar_one()
        cid = uuid.uuid4()
        i = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WF_CORRECTION,
            entity_type=CORRECTION_ENTITY,
            entity_id=cid,
            started_by=self.actor_id,
            context={
                "department_id": str(e.department_id),
                "result_id": str(r.id),
                "exam_session_id": str(r.exam_session_id) if r.exam_session_id else None,
                "enrollment_id": str(r.student_program_enrollment_id),
                "course_id": str(r.course_id),
                "reason": body.reason,
                "evidence": body.evidence,
                "ese_delta": str(body.ese_delta),
            },
            title=f"Result correction — {body.reason[:120]}",
        )
        await self._audit(
            "correction_request",
            "student_course_result",
            r.id,
            None,
            {"correction_id": str(cid), "ese_delta": str(body.ese_delta), "reason": body.reason},
        )
        return self.out(i)

    async def decide(self, cid: uuid.UUID, approve: bool, comment: str | None) -> CorrectionResponse:
        inst = next(iter(await self._instances(cid)), None)
        if inst is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Correction not found")
        await workflow_engine.act(
            self.db,
            instance_id=inst.id,
            actor=self.principal,
            decision="approve" if approve else "reject",
            comment=comment,
        )
        await self.db.refresh(inst)
        return self.out(inst)

    async def apply(self, inst: WorkflowInstance) -> None:
        ctx = dict(inst.context or {})
        if not ctx.get("exam_session_id"):
            ctx["outcome"] = "approved"
            inst.context = ctx
            return
        enr, course = uuid.UUID(ctx["enrollment_id"]), uuid.UUID(ctx["course_id"])
        run_id = await self.correction_run(
            uuid.UUID(ctx["exam_session_id"]),
            [(enr, course)],
            marks_delta={f"{enr}:{course}": Decimal(str(ctx.get("ese_delta") or 0))},
        )
        ctx.update({"outcome": "applied" if run_id else "approved", "run_id": str(run_id) if run_id else None})
        inst.context = ctx
        await self.db.flush()
        await self._audit(
            "correction_apply", "student_course_result", uuid.UUID(ctx["result_id"]), None, {"run_id": ctx["run_id"]}
        )


def _actor(instance: WorkflowInstance, actor: Any) -> Any:
    from app.services.fees.payment_service import _Actor

    return _Actor(instance.institution_id, getattr(actor, "id", None))


@workflow_engine.on(WF_CORRECTION, "approved")
async def _correction_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type == CORRECTION_ENTITY:
        await CorrectionService(db, _actor(instance, actor), None, instance.institution_id).apply(instance)


@workflow_engine.on(WF_CORRECTION, "rejected")
async def _correction_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type == CORRECTION_ENTITY:
        instance.context = {**(instance.context or {}), "outcome": "rejected"}
        await db.flush()


@workflow_engine.summariser(CORRECTION_ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    i = (await db.execute(select(WorkflowInstance).where(WorkflowInstance.entity_id == entity_id))).scalar_one_or_none()
    return (
        (f"Result correction — {(i.context or {}).get('reason', '')[:100]}", "/admin/results/corrections")
        if i
        else (None, None)
    )
