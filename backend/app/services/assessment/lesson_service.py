"""Lesson plans and course files — Prompts/13 §13.6 ``lesson_plan_service``.

Unit-wise plan items (planned date / hours / CO / resources); ``deliver`` ties an item to a Phase 10
``class_sessions`` row of the same offering (``actual_session_id`` + ``class_sessions.lesson_plan_item_id``) and marks
it ``delivered``; the deviation report compares planned and actual dates. The course file checklist (syllabus,
timetable, lesson plan, question papers, marks, attainment, feedback) derives some items from data (plan ≥ 80 %
delivered, every assessment locked, papers exist) and keeps the rest manual; the HOD audits it.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.assessment import COURSE_FILE_ITEMS
from app.models.assessment import OfferingAssessment
from app.models.content import QuestionPaper
from app.models.lms import CourseFile, LessonPlan
from app.models.timetable import ClassSession
from app.schemas.lms import (
    CourseFileAudit,
    CourseFileChecklist,
    CourseFileUpdate,
    DeliverRequest,
    DeviationRow,
    LessonPlanIn,
    LessonPlanOut,
    LessonPlanReplace,
)
from app.services.assessment.common import AssessmentBase, now_utc


class LessonService(AssessmentBase):
    audit_module = "lms"

    async def plan(self, offering_id: uuid.UUID) -> list[LessonPlanOut]:
        offering = await self.offering(offering_id, "lms")
        rows = (
            (
                await self.db.execute(
                    select(LessonPlan).where(LessonPlan.offering_id == offering.id).order_by(LessonPlan.sequence)
                )
            )
            .scalars()
            .all()
        )
        return [LessonPlanOut.model_validate(r) for r in rows]

    async def replace(self, offering_id: uuid.UUID, body: LessonPlanReplace) -> list[LessonPlanOut]:
        offering = await self.offering(offering_id, "lms")
        await self.require_teacher(offering, "lms")
        existing = (
            (await self.db.execute(select(LessonPlan).where(LessonPlan.offering_id == offering.id))).scalars().all()
        )
        if any(r.status == "delivered" for r in existing):
            # keep delivered items; replace only the planned / deferred ones
            for r in existing:
                if r.status != "delivered":
                    await self.db.delete(r)
        else:
            for r in existing:
                await self.db.delete(r)
        await self.db.flush()
        for i, item in enumerate(body.items):
            data = item.model_dump()
            data["sequence"] = data.get("sequence") or i + 1
            data["planned_hours"] = Decimal(str(data["planned_hours"]))
            self.db.add(LessonPlan(institution_id=self.inst, offering_id=offering.id, status="planned", **data))
        await self.db.flush()
        await self._audit("lesson_plan", "course_offering", offering.id, None, {"items": len(body.items)})
        await self.refresh_course_file(offering.id)
        return await self.plan(offering.id)

    async def _item(self, lid: uuid.UUID) -> LessonPlan:
        r = (
            await self.db.execute(
                select(LessonPlan).where(LessonPlan.id == lid, LessonPlan.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Lesson plan item not found")
        await self.require_teacher(await self.offering(r.offering_id, "lms"), "lms")
        return r

    async def update(self, lid: uuid.UUID, body: LessonPlanIn) -> LessonPlanOut:
        r = await self._item(lid)
        for k, v in body.model_dump().items():
            setattr(r, k, Decimal(str(v)) if k == "planned_hours" else v)
        await self.db.flush()
        return LessonPlanOut.model_validate(r)

    async def deliver(self, lid: uuid.UUID, body: DeliverRequest) -> LessonPlanOut:
        r = await self._item(lid)
        if body.session_id:
            s = (
                await self.db.execute(select(ClassSession).where(ClassSession.id == body.session_id).with_for_update())
            ).scalar_one_or_none()
            if s is None or s.offering_id != r.offering_id:
                raise APIError(422, ErrorCode.VALIDATION, "The session belongs to another offering")
            r.actual_session_id, r.actual_date = s.id, s.session_date
            s.lesson_plan_item_id = r.id
        else:
            r.actual_date = body.actual_date or await self.today()
        r.status = "delivered"
        await self.db.flush()
        await self._emit(
            "lesson.delivered", {"lesson_plan_id": str(r.id), "offering_id": str(r.offering_id)}, "lesson_plan", r.id
        )
        await self.refresh_course_file(r.offering_id)
        return LessonPlanOut.model_validate(r)

    async def deviation(self, offering_id: uuid.UUID) -> list[DeviationRow]:
        today = await self.today()
        out = []
        for r in await self.plan(offering_id):
            late = None
            if r.planned_date:
                ref = r.actual_date or (today if r.status != "delivered" and r.planned_date < today else None)
                late = (ref - r.planned_date).days if ref else None
            out.append(
                DeviationRow(
                    id=r.id,
                    sequence=r.sequence,
                    topic=r.topic,
                    planned_date=r.planned_date,
                    actual_date=r.actual_date,
                    days_late=late,
                    status=r.status,
                )
            )
        return out

    # ---- course file ---------------------------------------------------------------------------------------------------
    async def _file(self, offering_id: uuid.UUID) -> CourseFile:
        f = (
            await self.db.execute(select(CourseFile).where(CourseFile.offering_id == offering_id).with_for_update())
        ).scalar_one_or_none()
        if f is None:
            f = CourseFile(
                institution_id=self.inst,
                offering_id=offering_id,
                checklist=[{"key": k, "label": label, "done": False} for k, label in COURSE_FILE_ITEMS],
                completion_pct=0,
            )
            self.db.add(f)
            await self.db.flush()
        return f

    async def refresh_course_file(self, offering_id: uuid.UUID) -> CourseFile:
        f = await self._file(offering_id)
        total = (
            await self.db.execute(
                select(func.count()).select_from(LessonPlan).where(LessonPlan.offering_id == offering_id)
            )
        ).scalar_one()
        done = (
            await self.db.execute(
                select(func.count())
                .select_from(LessonPlan)
                .where(LessonPlan.offering_id == offering_id, LessonPlan.status == "delivered")
            )
        ).scalar_one()
        assessments = (
            (
                await self.db.execute(
                    select(OfferingAssessment.status).where(OfferingAssessment.offering_id == offering_id)
                )
            )
            .scalars()
            .all()
        )
        from app.models.offerings import CourseOffering

        course_id = (
            await self.db.execute(select(CourseOffering.course_id).where(CourseOffering.id == offering_id))
        ).scalar_one()
        papers = (
            await self.db.execute(
                select(func.count()).select_from(QuestionPaper).where(QuestionPaper.course_id == course_id)
            )
        ).scalar_one()
        auto = {
            "lesson_plan": bool(total) and done / total >= 0.8,
            "marks": bool(assessments) and all(s == "locked" for s in assessments),
            "question_papers": papers > 0,
        }
        items = []
        for it in f.checklist or []:
            it = dict(it)
            if it.get("key") in auto:
                it["done"], it["auto"] = auto[it["key"]], True
            items.append(it)
        f.checklist = items
        f.completion_pct = int(round(100 * sum(1 for i in items if i.get("done")) / max(1, len(items))))
        await self.db.flush()
        return f

    async def course_file(self, offering_id: uuid.UUID) -> CourseFileChecklist:
        await self.offering(offering_id, "lms")
        f = await self.refresh_course_file(offering_id)
        return CourseFileChecklist(
            offering_id=offering_id,
            checklist=f.checklist,
            completion_pct=f.completion_pct,
            audited_by=f.audited_by,
            audited_at=f.audited_at,
            remarks=f.remarks,
        )

    async def update_course_file(self, offering_id: uuid.UUID, body: CourseFileUpdate) -> CourseFileChecklist:
        offering = await self.offering(offering_id, "lms")
        await self.require_teacher(offering, "lms")
        f = await self._file(offering.id)
        given = {str(i.get("key")): i for i in body.checklist}
        f.checklist = [
            {**it, **{k: v for k, v in given.get(it["key"], {}).items() if k in ("done", "url", "note")}}
            if not it.get("auto")
            else it
            for it in f.checklist or []
        ]
        await self.db.flush()
        return await self.course_file(offering.id)

    async def audit_file(self, fid: uuid.UUID, body: CourseFileAudit) -> CourseFileChecklist:
        f = (
            await self.db.execute(
                select(CourseFile).where(CourseFile.id == fid, CourseFile.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if f is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course file not found")
        await self.offering(f.offering_id, "lms")
        f.audited_by, f.audited_at, f.remarks = self.actor_id, now_utc(), body.remarks
        await self.db.flush()
        await self._audit(
            "course_file_audit",
            "course_file",
            f.id,
            None,
            {"remarks": body.remarks, "completion_pct": f.completion_pct},
        )
        return await self.course_file(f.offering_id)
