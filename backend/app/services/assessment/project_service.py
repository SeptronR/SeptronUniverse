"""Student projects / dissertations — Prompts/13 §13.6 ``project_service``.

Projects belong to an offering (``project`` / ``internship_project`` / ``dissertation`` course types); 1–4 members
who must be on the offering's roster (422 otherwise; the first is the leader), guide / co-guide (staff; an external
guide is JSON). Reviews (panel, rubric, marks) linked to a ``project_review`` component write the same marks for every
member through the single write path. Visibility: members (self / wards), guides, panel members and units with
``projects:view_all`` (``assessment_scope.project_predicate``).
"""

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.assessment import OfferingAssessment
from app.models.hr import Staff
from app.models.projects import ProjectMember, ProjectReview, StudentProject
from app.repositories.assessment_scope import project_predicate, staff_ids
from app.schemas.projects import MemberIn, ProjectIn, ProjectOut, ReviewIn, ReviewOut
from app.services.assessment.common import AssessmentBase, q2


class ProjectService(AssessmentBase):
    audit_module = "projects"

    async def outs(self, rows: list[StudentProject]) -> list[ProjectOut]:
        ids = [r.id for r in rows]
        members = (
            (await self.db.execute(select(ProjectMember).where(ProjectMember.project_id.in_(ids or [uuid.uuid4()]))))
            .scalars()
            .all()
        )
        names = {}
        if members:
            from app.models.students import Student, StudentProgramEnrollment

            names = {
                e: (s.registration_number, f"{s.first_name} {s.last_name or ''}".strip())
                for e, s in (
                    await self.db.execute(
                        select(StudentProgramEnrollment.id, Student)
                        .join(Student, Student.id == StudentProgramEnrollment.student_id)
                        .where(StudentProgramEnrollment.id.in_([m.student_program_enrollment_id for m in members]))
                    )
                ).all()
            }
        reviews = (
            (
                await self.db.execute(
                    select(ProjectReview)
                    .where(ProjectReview.project_id.in_(ids or [uuid.uuid4()]))
                    .order_by(ProjectReview.review_no)
                )
            )
            .scalars()
            .all()
        )
        guides = {
            s.id: f"{s.first_name} {s.last_name or ''}".strip()
            for s in (
                await self.db.execute(
                    select(Staff).where(
                        Staff.id.in_([r.guide_staff_id for r in rows if r.guide_staff_id] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        out = []
        for r in rows:
            o = ProjectOut.model_validate(r)
            o.guide_name = guides.get(r.guide_staff_id) if r.guide_staff_id else None
            o.members = [
                {
                    "student_program_enrollment_id": str(m.student_program_enrollment_id),
                    "role": m.role,
                    "registration_number": names.get(m.student_program_enrollment_id, (None, None))[0],
                    "name": names.get(m.student_program_enrollment_id, (None, None))[1],
                }
                for m in members
                if m.project_id == r.id
            ]
            o.reviews = [ReviewOut.model_validate(v) for v in reviews if v.project_id == r.id]
            out.append(o)
        return out

    async def _project(self, pid: uuid.UUID, *, for_update: bool = False) -> StudentProject:
        q = select(StudentProject).where(
            StudentProject.id == pid,
            StudentProject.institution_id == self.inst,
            project_predicate(self.principal, "all"),
        )
        if for_update:
            q = q.with_for_update()
        p = (await self.db.execute(q)).scalar_one_or_none()
        if p is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Project not found")
        return p

    async def _can_manage(self, p: StudentProject) -> None:
        mine = (
            set((await self.db.execute(staff_ids(self.principal))).scalars().all())
            if self.principal is not None
            else set()
        )
        if (
            p.guide_staff_id in mine
            or p.co_guide_staff_id in mine
            or await self.is_teacher(p.offering_id)
            or self.can("projects", "manage")
        ):
            return
        raise APIError(
            403, ErrorCode.PERMISSION_DENIED, "Only the guide or the offering's faculty may change the project"
        )

    async def list_for(self, offering_id: uuid.UUID) -> list[ProjectOut]:
        offering = await self.offering(offering_id, "projects")
        q = select(StudentProject).where(StudentProject.offering_id == offering.id)
        if not (await self.is_teacher(offering.id) or self.can("projects", "view_all")):
            q = q.where(project_predicate(self.principal, "self"))
        return await self.outs(list((await self.db.execute(q.order_by(StudentProject.created_at))).scalars().all()))

    async def _set_members(self, p: StudentProject, members: list[uuid.UUID]) -> None:
        if not 1 <= len(members) <= 4:
            raise APIError(422, ErrorCode.VALIDATION, "A project has 1–4 members")
        offering = await self.offering(p.offering_id, "projects")
        roster = await self.roster_ids(offering)
        foreign = [str(m) for m in members if m not in roster]
        if foreign:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Members must be registered for this offering",
                {"code": "NOT_ON_ROSTER", "members": foreign},
            )
        for old in (await self.db.execute(select(ProjectMember).where(ProjectMember.project_id == p.id))).scalars():
            await self.db.delete(old)
        await self.db.flush()
        for i, m in enumerate(members):
            self.db.add(
                ProjectMember(
                    institution_id=self.inst,
                    project_id=p.id,
                    student_program_enrollment_id=m,
                    role="leader" if i == 0 else "member",
                )
            )
        await self.db.flush()

    async def create(self, offering_id: uuid.UUID, body: ProjectIn) -> ProjectOut:
        offering = await self.offering(offering_id, "projects")
        if not (await self.is_teacher(offering.id) or self.can("projects", "manage") or self.can("projects", "guide")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only faculty create projects")
        data = body.model_dump(exclude={"members", "status"})
        p = StudentProject(institution_id=self.inst, offering_id=offering.id, status=body.status or "proposed", **data)
        self.db.add(p)
        await self.db.flush()
        if body.members:
            await self._set_members(p, body.members)
        await self._audit(
            "create", "student_project", p.id, None, {"title": p.title, "members": len(body.members or [])}
        )
        await self._emit(
            "project.created", {"project_id": str(p.id), "offering_id": str(offering.id)}, "student_project", p.id
        )
        return (await self.outs([p]))[0]

    async def update(self, pid: uuid.UUID, body: ProjectIn) -> ProjectOut:
        p = await self._project(pid, for_update=True)
        await self._can_manage(p)
        for k, v in body.model_dump(exclude={"members"}, exclude_none=True).items():
            setattr(p, k, v)
        if body.members is not None:
            await self._set_members(p, body.members)
        await self.db.flush()
        return (await self.outs([p]))[0]

    async def members(self, pid: uuid.UUID, body: MemberIn) -> ProjectOut:
        p = await self._project(pid, for_update=True)
        await self._can_manage(p)
        await self._set_members(p, body.members)
        return (await self.outs([p]))[0]

    async def review(self, pid: uuid.UUID, body: ReviewIn) -> ProjectOut:
        p = await self._project(pid, for_update=True)
        await self._can_manage(p) if not self.can("projects", "review") else None
        marks = (
            Decimal(str(sum(body.rubric_scores.values())))
            if body.rubric_scores
            else (Decimal(str(body.marks)) if body.marks is not None else None)
        )
        r = (
            await self.db.execute(
                select(ProjectReview)
                .where(ProjectReview.project_id == p.id, ProjectReview.review_no == body.review_no)
                .with_for_update()
            )
        ).scalar_one_or_none()
        data = {**body.model_dump(), "marks": q2(marks) if marks is not None else None}
        if r is None:
            r = ProjectReview(institution_id=self.inst, project_id=p.id, recorded_by=self.actor_id, **data)
            self.db.add(r)
        else:
            for k, v in data.items():
                setattr(r, k, v)
        await self.db.flush()
        if body.offering_assessment_id and marks is not None:
            a = (
                await self.db.execute(
                    select(OfferingAssessment)
                    .where(OfferingAssessment.id == body.offering_assessment_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if a is None or a.offering_id != p.offering_id:
                raise APIError(422, ErrorCode.VALIDATION, "The assessment belongs to another offering")
            if marks > Decimal(str(a.max_marks)):
                raise APIError(422, ErrorCode.VALIDATION, f"Review marks above {a.max_marks}")
            for m in (await self.db.execute(select(ProjectMember).where(ProjectMember.project_id == p.id))).scalars():
                await self.write_internal_mark(a, m.student_program_enrollment_id, marks, source="project_review")
        await self._audit(
            "review",
            "student_project",
            p.id,
            None,
            {"review_no": body.review_no, "marks": float(marks) if marks is not None else None},
        )
        await self._emit(
            "project.reviewed", {"project_id": str(p.id), "review_no": body.review_no}, "student_project", p.id
        )
        return (await self.outs([p]))[0]

    async def mine(self) -> list[ProjectOut]:
        rows = (
            (
                await self.db.execute(
                    select(StudentProject)
                    .where(StudentProject.institution_id == self.inst, project_predicate(self.principal, "self"))
                    .order_by(StudentProject.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows))
