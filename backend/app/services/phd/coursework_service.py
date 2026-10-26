"""PhD coursework — Prompts/31 §31.6 ``coursework_service`` ({phd.coursework}).

The guide / research cell plans the courses (research methodology mandatory + electives; a course counts as
methodology when its code / title matches ``phd.rules.methodology_course_codes``). The plan is kept in the side store
and announced as ``phd.coursework_planned {enrollment_id, course_ids}`` for the Phase 09 registration in the PhD
programme term (``registration_type='regular'``); results arrive through Phase 15. ``credits_earned`` and
``methodology_done`` are computed from current, published, passed ``student_course_results`` of the planned courses.
Completion (credits ≥ ``coursework_min_credits`` with methodology) moves the scholar to ``registered`` with the
``registration_date``. Exemptions (M.Phil / prior coursework) go through ``phd.request`` (``coursework_exemption``);
the approved hook calls :meth:`exempt`. The monthly deadline scan warns scholars past ``coursework_deadline_months``.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.models.curriculum import Course
from app.models.phd import ResearchScholar
from app.models.results import StudentCourseResult
from app.schemas.phd import (
    CourseworkCourse,
    CourseworkExemption,
    CourseworkPlan,
    CourseworkStatusOut,
    CourseworkSummary,
    ScholarRequestCreate,
    ScholarRequestOut,
)
from app.services.phd.common import PhdBase, add_months, forbidden, rule

ENTITY = "research_scholar"
_PASS = ("pass", "passed", "P", "exempted")


class CourseworkService(PhdBase):
    async def _methodology(self, c: Course) -> bool:
        keys = [str(k).upper() for k in (await self.rules()).get("methodology_course_codes") or []]
        hay = f"{c.code} {c.title}".upper()
        return any(k in hay for k in keys)

    async def _compute(self, s: ResearchScholar) -> tuple[list[CourseworkCourse], float, bool]:
        m = await self.meta("coursework", s.id)
        ids = [uuid.UUID(i) for i in m.get("course_ids") or []]
        if not ids:
            return [], 0.0, False
        courses = {c.id: c for c in (await self.db.execute(select(Course).where(Course.id.in_(ids)))).scalars()}
        results = {
            r.course_id: r
            for r in (
                await self.db.execute(
                    select(StudentCourseResult).where(
                        StudentCourseResult.student_program_enrollment_id == s.student_program_enrollment_id,
                        StudentCourseResult.course_id.in_(ids),
                        StudentCourseResult.is_current.is_(True),
                        StudentCourseResult.status == "published",
                    )
                )
            ).scalars()
        }
        out: list[CourseworkCourse] = []
        earned = Decimal(0)
        methodology = False
        for cid in ids:
            c = courses.get(cid)
            if c is None:
                continue
            r = results.get(cid)
            passed = r is not None and r.result_status in _PASS
            is_m = await self._methodology(c)
            if passed:
                earned += r.credits if r is not None else Decimal(0)
                methodology = methodology or is_m
            out.append(
                CourseworkCourse(
                    course_id=c.id,
                    code=c.code,
                    title=c.title,
                    credits=float(c.credits),
                    is_methodology=is_m,
                    result=r.result_status if r is not None else None,
                )
            )
        return out, float(earned), methodology

    async def _deadline(self, s: ResearchScholar) -> date:
        months = await self.rule_int("coursework_deadline_months")
        start = (await self.enrollment(s.student_program_enrollment_id)).admission_date
        return add_months(start, months)

    async def summary(self, s: ResearchScholar) -> CourseworkSummary:
        _, earned, meth = await self._compute(s)
        return CourseworkSummary(
            status=s.coursework_status,
            credits_required=await self.rule_int("coursework_min_credits"),
            credits_earned=earned,
            methodology_done=meth or s.coursework_status == "exempted",
            deadline=await self._deadline(s),
        )

    async def status(self, sid: uuid.UUID) -> CourseworkStatusOut:
        s = await self.scholar(sid)
        courses, earned, meth = await self._compute(s)
        m = await self.meta("coursework", s.id)
        return CourseworkStatusOut(
            scholar_id=s.id,
            status=s.coursework_status,
            credits_required=await self.rule_int("coursework_min_credits"),
            credits_earned=earned,
            methodology_done=meth or s.coursework_status == "exempted",
            deadline=await self._deadline(s),
            courses=courses,
            exemption=m.get("exemption"),
        )

    async def plan(self, sid: uuid.UUID, body: CourseworkPlan) -> CourseworkStatusOut:
        s = await self.scholar(sid, lock=True)
        await self.require_relation(s, "guide", "co_guide")
        if s.coursework_status in ("completed", "exempted"):
            raise rule("Coursework is already closed", "COURSEWORK_CLOSED")
        courses = list((await self.db.execute(select(Course).where(Course.id.in_(body.course_ids)))).scalars())
        if len(courses) != len(set(body.course_ids)):
            raise rule("Unknown course in the plan", "UNKNOWN_COURSE", 422)
        if not any([await self._methodology(c) for c in courses]):
            raise rule("The plan must include research methodology", "METHODOLOGY_REQUIRED", 422)
        need = await self.rule_int("coursework_min_credits")
        planned = float(sum((c.credits for c in courses), Decimal(0)))
        if planned < need:
            raise rule(
                f"The plan carries {planned} of {need} credits", "CREDITS_SHORT", 422, planned=planned, need=need
            )
        m = await self.meta("coursework", s.id)
        m["course_ids"] = [str(c.id) for c in courses]
        m["planned_on"] = (await self.today()).isoformat()
        await self.put_meta("coursework", s.id, m)
        s.coursework_status = "in_progress"
        if s.status == "admitted":
            from app.services.phd.scholar_service import ScholarService

            await ScholarService(self.db, self.principal, self.request, self.inst).set_status(s, "coursework")
        await self.db.flush()
        await self._emit(
            "phd.coursework_planned",
            {
                "scholar_id": str(s.id),
                "enrollment_id": str(s.student_program_enrollment_id),
                "course_ids": m["course_ids"],
                "registration_type": "regular",
            },
            ENTITY,
            s.id,
        )
        return await self.status(s.id)

    async def request_exemption(self, sid: uuid.UUID, body: CourseworkExemption) -> ScholarRequestOut:
        from app.schemas.phd import RequestDetails
        from app.services.phd.request_service import RequestService

        return await RequestService(self.db, self.principal, self.request, self.inst).create(
            sid,
            ScholarRequestCreate(
                request_type="coursework_exemption",
                details=RequestDetails(reason=body.reason),
                attachments=[body.evidence_url] if body.evidence_url else [],
            ),
        )

    async def exempt(self, s: ResearchScholar, reason: str, evidence: list[str] | None = None) -> None:
        s.coursework_status = "exempted"
        s.coursework_exemption_reason = reason
        m = await self.meta("coursework", s.id)
        m["exemption"] = {"reason": reason, "evidence": evidence or [], "on": (await self.today()).isoformat()}
        await self.put_meta("coursework", s.id, m)
        await self._emit("phd.coursework_exempted", {"scholar_id": str(s.id)}, ENTITY, s.id)
        await self._register(s)

    async def complete(self, sid: uuid.UUID) -> CourseworkStatusOut:
        s = await self.scholar(sid, lock=True)
        if not (self.cell() or await self.is_guide_of(s)):
            raise forbidden("The guide or the research cell completes coursework")
        self.require_writer()
        if s.coursework_status == "completed":
            raise rule("Coursework is already completed", "COURSEWORK_CLOSED")
        if s.coursework_status != "exempted":
            _, earned, meth = await self._compute(s)
            need = await self.rule_int("coursework_min_credits")
            if earned < need or not meth:
                raise rule(
                    f"{earned} of {need} credits earned{'' if meth else ', research methodology pending'}",
                    "COURSEWORK_INCOMPLETE",
                    409,
                    credits_earned=earned,
                    methodology_done=meth,
                )
            s.coursework_status = "completed"
            await self._emit("phd.coursework_completed", {"scholar_id": str(s.id), "credits": earned}, ENTITY, s.id)
        await self._register(s)
        return await self.status(s.id)

    async def _register(self, s: ResearchScholar) -> None:
        from app.services.phd.scholar_service import ScholarService

        svc = ScholarService(self.db, self.principal, self.request, self.inst)
        if s.registration_date is None:
            await svc.register(s)
            await svc.letter(s)
        await self.db.flush()

    # ---- consumers / Beat ---------------------------------------------------------------------------------------------
    async def on_results_published(self, enrollment_ids: list[uuid.UUID]) -> int:
        """Coursework credits refresh: auto-complete when the plan is met (Phase 15 results published)."""
        n = 0
        for s in (
            await self.db.execute(
                select(ResearchScholar).where(
                    ResearchScholar.institution_id == self.inst,
                    ResearchScholar.student_program_enrollment_id.in_(enrollment_ids),
                    ResearchScholar.coursework_status == "in_progress",
                )
            )
        ).scalars():
            _, earned, meth = await self._compute(s)
            if earned >= await self.rule_int("coursework_min_credits") and meth:
                s.coursework_status = "completed"
                await self._emit("phd.coursework_completed", {"scholar_id": str(s.id), "credits": earned}, ENTITY, s.id)
                await self._register(s)
                n += 1
        return n

    async def deadline_scan(self) -> int:
        today = await self.today()
        n = 0
        for s in (
            await self.db.execute(
                select(ResearchScholar).where(
                    ResearchScholar.institution_id == self.inst,
                    ResearchScholar.coursework_status.in_(("pending", "in_progress")),
                    ResearchScholar.status.in_(("admitted", "coursework")),
                )
            )
        ).scalars():
            due = await self._deadline(s)
            if due > today:
                continue
            m = await self.meta("coursework", s.id)
            if m.get("deadline_warned") == due.isoformat():
                continue
            m["deadline_warned"] = due.isoformat()
            await self.put_meta("coursework", s.id, m)
            await self._notify(
                "phd.duration_warning",
                [await self.scholar_user(s), *await self.guide_users(s)],
                {"scholar": await self.scholar_name(s), "max_end": f"coursework deadline {due}", "months": 0},
            )
            n += 1
        return n

    async def plan_ids(self, s: ResearchScholar) -> list[str]:
        m: dict[str, Any] = await self.meta("coursework", s.id)
        return list(m.get("course_ids") or [])
