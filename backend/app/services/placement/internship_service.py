"""Internships — Prompts/28 §28.6 ``internship_service`` ({placement.internships}).

Records (company from the master or free text) created by the student or an officer; credit mapping
(``credits_course_id``) needs a duration ≥ ``placement.internship_min_weeks`` (409 ``MIN_WEEKS``); the **NOC letter**
renders through Phase 26 ``documents.render('internship_noc', 'internship', id)`` into ``noc_document_id`` (inline, or
the ``internship.noc_batch`` job for many); evaluation (rubric → marks) by the faculty of an offering of the mapped
course in the student's college (ownership — ``internships.mentor`` is free text) or a department reader; with a
mapped course the marks are written to that offering's first assessment as the Phase 13 internal mark (the single
write path — Phase 15 consolidates it). A PPO from an internship becomes an ``is_ppo`` offer on a per-company PPO drive
so it counts toward the policy. ``academics.internships_pct`` is reported by the stats service.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select

from app.core.errors import APIError
from app.models.assessment import InternalMark, OfferingAssessment
from app.models.offerings import CourseOffering, CourseOfferingFaculty
from app.models.placement import Company, DriveApplication, Internship, PlacementDrive
from app.models.students import StudentProgramEnrollment
from app.schemas.placement import (
    InternshipEvaluation,
    InternshipIn,
    InternshipNocRequest,
    InternshipOut,
    InternshipUpdate,
    PlcOfferCreate,
    PlcOfferOut,
)
from app.services.documents.render_service import RenderService, register_resolver
from app.services.placement.common import PlacementBase, forbidden, not_found, now_utc, rule


def _weeks(i: Internship) -> int | None:
    if i.to_on is None:
        return None
    return max(0, (i.to_on - i.from_on).days) // 7


class InternshipService(PlacementBase):
    async def outs(self, rows: list[Internship]) -> list[InternshipOut]:
        cards = await self.enrollment_cards([i.student_program_enrollment_id for i in rows])
        depts = await self.department_codes([c.get("department_id") for c in cards.values()])
        companies = await self.companies_map([i.company_id for i in rows])
        out = []
        for i in rows:
            card = cards.get(i.student_program_enrollment_id, {})
            c = companies.get(i.company_id) if i.company_id else None
            out.append(
                InternshipOut(
                    id=i.id,
                    student_program_enrollment_id=i.student_program_enrollment_id,
                    student_name=card.get("name"),
                    registration_number=card.get("registration_number"),
                    department_code=depts.get(card["department_id"]) if card.get("department_id") else None,
                    company_id=i.company_id,
                    company_name=c.name if c else i.company_name,
                    role=i.role,
                    from_on=i.from_on,
                    to_on=i.to_on,
                    weeks=_weeks(i),
                    stipend_paise=i.stipend_paise,
                    mentor=i.mentor,
                    evaluation=i.evaluation,
                    certificate_url=i.certificate_url,
                    noc_document_id=i.noc_document_id,
                    credits_course_id=i.credits_course_id,
                    status=i.status,
                    created_at=i.created_at,
                )
            )
        return out

    async def _mentor_course_ids(self) -> list[uuid.UUID]:
        staff_id = await self.my_staff_id()
        if staff_id is None:
            return []
        rows = await self.db.execute(
            select(CourseOffering.course_id)
            .join(CourseOfferingFaculty, CourseOfferingFaculty.offering_id == CourseOffering.id)
            .where(CourseOfferingFaculty.staff_id == staff_id)
        )
        return list({r[0] for r in rows.all()})

    async def _visible(self, scope: str | None = None) -> Any:
        pred = await self.enrolment_predicate(Internship.student_program_enrollment_id, scope)
        if scope in (None, "own") and self.can("placement", "evaluate"):
            courses = await self._mentor_course_ids()
            if courses:
                pred = or_(pred, Internship.credits_course_id.in_(courses))
        return pred

    async def _get(self, iid: uuid.UUID, *, lock: bool = False) -> Internship:
        stmt = select(Internship).where(
            Internship.id == iid, Internship.institution_id == self.inst, await self._visible()
        )
        if lock:
            stmt = stmt.with_for_update()
        i = (await self.db.execute(stmt)).scalar_one_or_none()
        if i is None:
            raise not_found("Internship")
        return i

    async def _check_credit(self, i: Internship) -> None:
        if i.credits_course_id is None:
            return
        min_weeks = await self.int_setting("placement", "internship_min_weeks", 4)
        w = _weeks(i)
        if w is None or w < min_weeks:
            raise rule(f"Credit mapping needs at least {min_weeks} weeks", "MIN_WEEKS", min_weeks=min_weeks, weeks=w)

    async def list_internships(
        self, department_id: uuid.UUID | None, status: str | None, scope: str | None
    ) -> list[InternshipOut]:
        stmt = select(Internship).where(Internship.institution_id == self.inst, await self._visible(scope))
        if status:
            stmt = stmt.where(Internship.status == status)
        if department_id:
            stmt = stmt.where(
                Internship.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.department_id == department_id)
                )
            )
        rows = list((await self.db.execute(stmt.order_by(Internship.from_on.desc()).limit(3000))).scalars())
        return await self.outs(rows)

    async def mine(self) -> list[InternshipOut]:
        ids = await self.my_enrollment_ids() + await self.ward_enrollment_ids()
        rows = list(
            (
                await self.db.execute(
                    select(Internship)
                    .where(Internship.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                    .order_by(Internship.from_on.desc())
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def get(self, iid: uuid.UUID) -> InternshipOut:
        return (await self.outs([await self._get(iid)]))[0]

    async def create(self, body: InternshipIn) -> InternshipOut:
        self.require_writer()
        if body.enrollment_id is not None and self.officer():
            e = await self.enrollment(body.enrollment_id)
        else:
            e = await self.require_my_enrollment()
        if body.company_id is None and not body.company_name:
            raise rule("Company or company name required", "COMPANY_REQUIRED", status=422)
        name = body.company_name
        if body.company_id:
            c = (await self.db.execute(select(Company).where(Company.id == body.company_id))).scalar_one_or_none()
            if c is None:
                raise not_found("Company")
            name = c.name
        if body.to_on and body.to_on < body.from_on:
            raise rule("End date before start date", "DATES", status=422)
        i = Internship(
            institution_id=self.inst,
            student_program_enrollment_id=e.id,
            company_id=body.company_id,
            company_name=name,
            role=body.role,
            from_on=body.from_on,
            to_on=body.to_on,
            stipend_paise=body.stipend_paise,
            mentor=body.mentor,
            credits_course_id=body.credits_course_id,
            certificate_url=body.certificate_url,
            status=body.status,
        )
        await self._check_credit(i)
        self.db.add(i)
        await self.db.flush()
        await self._audit("create", "internship", i.id, None, body.model_dump(mode="json"))
        await self._emit(
            "internship.created", {"internship_id": str(i.id), "enrollment_id": str(e.id)}, "internship", i.id
        )
        return (await self.outs([i]))[0]

    async def update(self, iid: uuid.UUID, body: InternshipUpdate) -> InternshipOut:
        self.require_writer()
        i = await self._get(iid, lock=True)
        if not self.officer() and i.student_program_enrollment_id not in await self.my_enrollment_ids():
            raise forbidden()
        if (i.evaluation or {}).get("evaluated_at") and not self.officer():
            raise rule("Evaluated internships are locked", "EVALUATED")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(i, k, v)
        await self._check_credit(i)
        await self.db.flush()
        await self._audit("update", "internship", i.id, None, body.model_dump(mode="json", exclude_unset=True))
        if i.status == "completed":
            await self._emit("internship.completed", {"internship_id": str(i.id)}, "internship", i.id)
        return (await self.outs([i]))[0]

    async def noc(self, iid: uuid.UUID, body: InternshipNocRequest) -> InternshipOut:
        i = await self._get(iid, lock=True)
        if not self.officer() and i.student_program_enrollment_id not in await self.my_enrollment_ids():
            raise forbidden()
        ev = dict(i.evaluation or {})
        ev["noc"] = {**body.model_dump(), "requested_at": now_utc().isoformat(), "requested_by": str(self.actor_id)}
        i.evaluation = ev
        await self._emit("internship.noc_requested", {"internship_id": str(i.id)}, "internship", i.id)
        await self.issue_noc(i)
        return (await self.outs([i]))[0]

    async def issue_noc(self, i: Internship) -> uuid.UUID | None:
        try:
            res = await RenderService(self.db, self.principal, self.request, self.inst).render(
                "internship_noc", "internship", i.id, allow_multiple=True
            )
        except APIError as exc:
            ev = dict(i.evaluation or {})
            ev.setdefault("noc", {})["error"] = getattr(exc, "message", str(exc))
            i.evaluation = ev
            await self.db.flush()
            return None
        i.noc_document_id = res.issued_document_id
        await self.db.flush()
        card = (await self.enrollment_cards([i.student_program_enrollment_id])).get(i.student_program_enrollment_id, {})
        await self._notify("internship.noc_ready", [card.get("user_id")], {"company": i.company_name or ""})
        return res.issued_document_id

    async def noc_batch(self, ids: list[uuid.UUID]) -> int:
        n = 0
        for iid in ids:
            i = (await self.db.execute(select(Internship).where(Internship.id == iid))).scalar_one_or_none()
            if i is not None and i.noc_document_id is None and await self.issue_noc(i):
                n += 1
        return n

    async def evaluate(self, iid: uuid.UUID, body: InternshipEvaluation) -> InternshipOut:
        self.require_writer()
        i = await self._get(iid, lock=True)
        mentor = i.credits_course_id is not None and i.credits_course_id in await self._mentor_course_ids()
        if not (self.officer() or mentor or (self.can("placement", "evaluate") and self.reader())):
            raise forbidden("Only the internship course faculty or the department evaluates")
        if body.marks > body.max_marks:
            raise rule("Marks exceed the maximum", "MARKS", status=422)
        await self._check_credit(i)
        ev = dict(i.evaluation or {})
        ev.update(
            rubric_scores=body.rubric_scores,
            marks=float(body.marks),
            max_marks=float(body.max_marks),
            remarks=body.remarks,
            evaluated_by=str(self.actor_id),
            evaluated_at=now_utc().isoformat(),
        )
        if body.certificate_url:
            i.certificate_url = body.certificate_url
        if i.credits_course_id is not None:
            ev["internal_mark"] = await self._write_mark(i, body.marks, body.max_marks)
        i.evaluation = ev
        if i.status in ("ongoing", "planned"):
            i.status = "completed"
        await self.db.flush()
        await self._audit("evaluate", "internship", i.id, None, {"marks": float(body.marks)})
        await self._emit(
            "internship.evaluated",
            {"internship_id": str(i.id), "marks": float(body.marks), "course_id": str(i.credits_course_id or "")},
            "internship",
            i.id,
        )
        return (await self.outs([i]))[0]

    async def _write_mark(self, i: Internship, marks: Decimal, max_marks: Decimal) -> dict[str, Any]:
        e = await self.enrollment(i.student_program_enrollment_id)
        term = await self.current_term(e.college_id)
        stmt = select(CourseOffering).where(
            CourseOffering.institution_id == self.inst,
            CourseOffering.course_id == i.credits_course_id,
            CourseOffering.college_id == e.college_id,
        )
        if term is not None:
            stmt = stmt.order_by((CourseOffering.term_id == term.id).desc())
        off = (await self.db.execute(stmt.limit(1))).scalar_one_or_none()
        if off is None:
            return {"status": "no_offering"}
        oa = (
            await self.db.execute(
                select(OfferingAssessment)
                .where(OfferingAssessment.offering_id == off.id)
                .order_by(OfferingAssessment.name)
                .limit(1)
            )
        ).scalar_one_or_none()
        if oa is None:
            return {"status": "no_assessment", "offering_id": str(off.id)}
        scaled = (Decimal(marks) * Decimal(oa.max_marks) / Decimal(max_marks)).quantize(Decimal("0.01"))
        im = (
            await self.db.execute(
                select(InternalMark).where(
                    InternalMark.offering_assessment_id == oa.id, InternalMark.student_program_enrollment_id == e.id
                )
            )
        ).scalar_one_or_none()
        if im is None:
            im = InternalMark(
                institution_id=self.inst, offering_assessment_id=oa.id, student_program_enrollment_id=e.id, version=1
            )
            self.db.add(im)
        else:
            im.version = (im.version or 1) + 1
        im.marks, im.entered_by, im.entered_at = scaled, self.actor_id, now_utc()
        await self.db.flush()
        return {"status": "written", "offering_assessment_id": str(oa.id), "marks": float(scaled)}

    async def ppo(self, iid: uuid.UUID, body: PlcOfferCreate) -> PlcOfferOut:
        """Pre-placement offer from an internship → ``is_ppo`` offer on the company's PPO drive."""
        from app.services.placement.offer_service import OfferService

        self.require_officer("offer_manage")
        i = await self._get(iid, lock=True)
        if i.company_id is None:
            raise rule("PPO needs a company from the master", "COMPANY_REQUIRED")
        e = await self.enrollment(i.student_program_enrollment_id)
        d = (
            await self.db.execute(
                select(PlacementDrive).where(
                    PlacementDrive.institution_id == self.inst,
                    PlacementDrive.company_id == i.company_id,
                    PlacementDrive.job_type == "intern_ppo",
                    PlacementDrive.college_id == e.college_id,
                )
            )
        ).scalar_one_or_none()
        if d is None:
            c = (await self.db.execute(select(Company).where(Company.id == i.company_id))).scalar_one()
            d = PlacementDrive(
                institution_id=self.inst,
                company_id=c.id,
                college_id=e.college_id,
                title=f"PPO — {c.name}",
                job_type="intern_ppo",
                mode="off_campus",
                status="completed",
                eligibility_rules={},
                created_by=self.actor_id,
            )
            self.db.add(d)
            await self.db.flush()
        a = (
            await self.db.execute(
                select(DriveApplication).where(
                    DriveApplication.drive_id == d.id, DriveApplication.student_program_enrollment_id == e.id
                )
            )
        ).scalar_one_or_none()
        if a is None:
            a = DriveApplication(
                institution_id=self.inst,
                drive_id=d.id,
                student_program_enrollment_id=e.id,
                eligibility_snapshot={"ppo_from_internship": str(i.id)},
                status="selected",
            )
            self.db.add(a)
            await self.db.flush()
        return await OfferService(self.db, self.principal, self.request, self.inst).create(
            body.model_copy(update={"application_id": a.id, "is_ppo": True})
        )


@register_resolver("internship")
async def _internship_ctx(svc: RenderService, iid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    i = (await svc.db.execute(select(Internship).where(Internship.id == iid))).scalar_one()
    ctx, ptype, pid = await svc.enrolment_ctx(i.student_program_enrollment_id)
    noc = (i.evaluation or {}).get("noc") or {}
    ctx["internship"] = {
        "company": i.company_name,
        "role": i.role,
        "from_on": i.from_on.strftime("%d-%m-%Y"),
        "to_on": i.to_on.strftime("%d-%m-%Y") if i.to_on else "",
        "addressed_to": noc.get("addressed_to") or "",
        "purpose": noc.get("purpose") or "",
    }
    return ctx, ptype, pid
