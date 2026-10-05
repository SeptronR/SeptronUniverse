"""Faculty workload and course-allocation proposals — Prompts/06 §06.6 ``workload_service.py`` ({hr.workload}).

1. **Workload** per staff member per term: theory / tutorial / lab hours from ``course_offering_faculty
   .hours_per_week`` of the term's offerings (Phase 09 — 0 until offerings exist) + admin hours by cadre (pack) →
   ``total_hours``; compared with the cadre norm (setting ``hr.workload_norms``, pack default professor 14 /
   associate 16 / assistant 18) → ``load_status`` ``under`` (below norm − 2) / ``within`` / ``over`` / ``no_norm``;
   the ``faculty_workloads`` row is upserted and ``workload.computed`` emitted. A member reads their own
   (``faculty:view``); department / faculty / institution views need ``faculty:workload_manage`` or ``view_all``.
2. **Allocation proposal** per department and term: the HOD edits the draft ``[{course_id, staff_id, hours, role}]``
   (staff of the department, courses of the department), **submits** it (workflow ``hr.course_allocation`` → the
   dean of the faculty), the dean **approves** through the workflow (``dean_approved``), and **apply** hands it to
   Phase 09 (``course_allocation.applied``) — refused with 409 while the department has no offerings for the term.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.academic import AcademicTerm
from app.models.curriculum import Course
from app.models.hr import CourseAllocationProposal, FacultyWorkload, Staff
from app.models.platform import Department, WorkflowInstance
from app.repositories.hr_scope import may_view_all
from app.repositories.staff_repository import StaffRecordsRepository
from app.repositories.workload_repository import AllocationRepository, WorkloadRepository
from app.schemas.hr import AllocationProposalIn, AllocationProposalOut, WorkloadResponse
from app.services.hr.common import HrServiceBase

ALLOC_KEY = "hr.course_allocation"
DEFERRED = "Course offerings arrive with Phase 09 — apply the approved proposal once the term's offerings exist"


class WorkloadService(HrServiceBase):
    audit_module = "faculty"

    def __init__(self, db: Any, principal: Any, request: Any = None, institution_id: uuid.UUID | None = None):
        super().__init__(db, principal, request, institution_id)
        self.repo = WorkloadRepository(db)
        self.allocations = AllocationRepository(db)
        self.records = StaffRecordsRepository(db)

    async def _term(self, term_id: uuid.UUID | None, college_id: uuid.UUID | None = None) -> AcademicTerm:
        stmt = select(AcademicTerm).where(AcademicTerm.institution_id == self.inst, AcademicTerm.deleted_at.is_(None))
        stmt = stmt.where(AcademicTerm.id == term_id) if term_id else stmt.where(AcademicTerm.is_current.is_(True))
        if term_id is None:
            # the college's own current term first, else the institution-wide one (college_id NULL)
            stmt = stmt.where(or_(AcademicTerm.college_id == college_id, AcademicTerm.college_id.is_(None)))
            stmt = stmt.order_by(AcademicTerm.college_id.is_(None))
        term = (await self.db.execute(stmt.limit(1))).scalar_one_or_none()
        if term is None:
            raise APIError(
                422 if term_id is None else 404,
                ErrorCode.VALIDATION if term_id is None else ErrorCode.NOT_FOUND,
                "Term not found (pass term_id or set a current term)",
                {"field": "term_id"},
            )
        return term

    async def _norms(self) -> dict[str, float]:
        raw = await self.setting("hr", "workload_norms")
        return raw if isinstance(raw, dict) and raw else dict((await self.pack()).hr.workload_norms)

    def _can_manage(self) -> bool:
        return bool(self.principal.has("faculty", "workload_manage") or may_view_all(self.principal, "workload"))

    # ---- rule 1 -------------------------------------------------------------------------------------------------
    async def for_staff(self, staff_id: uuid.UUID, term_id: uuid.UUID | None) -> WorkloadResponse:
        staff = await self.staff_repo.get_visible(staff_id, module="workload" if self._can_manage() else "hr")
        if staff.user_id != self.principal.id and not self._can_manage():
            raise APIError(404, ErrorCode.NOT_FOUND, "Staff not found")
        term = await self._term(term_id, staff.college_id)
        return (await self.compute([staff], term))[0]

    async def for_department(self, department_id: uuid.UUID, term_id: uuid.UUID | None) -> list[WorkloadResponse]:
        if not self._can_manage():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires faculty:workload_manage")
        stmt = self.staff_repo.filtered(
            scope="all", module="workload", department_id=department_id, staff_category="teaching"
        )
        staff = [
            s for s in (await self.db.execute(stmt.order_by(Staff.employee_id))).scalars().all() if s.status != "exited"
        ]
        if not staff:
            return []
        term = await self._term(term_id, staff[0].college_id)
        return await self.compute(staff, term)

    async def compute(self, staff: list[Staff], term: AcademicTerm) -> list[WorkloadResponse]:
        pack = await self.pack()
        norms = await self._norms()
        hours = await self.repo.teaching_hours([s.id for s in staff], term.id)
        profiles = await self.records.profiles([s.id for s in staff])
        out: list[WorkloadResponse] = []
        offerings_exist = any(hours.values())
        for s in staff:
            cadre = profiles[s.id].cadre if s.id in profiles else None
            h = hours.get(s.id, {"theory": Decimal(0), "tutorial": Decimal(0), "lab": Decimal(0)})
            admin = Decimal(str(pack.hr.admin_hours_by_cadre.get(cadre or "", 0)))
            total = h["theory"] + h["tutorial"] + h["lab"] + admin
            norm = norms.get(cadre or "")
            if norm is None:
                load = "no_norm"
            elif float(total) > float(norm):
                load = "over"
            elif float(total) >= float(norm) - 2:
                load = "within"
            else:
                load = "under"
            row = await self.repo.get(s.id, term.id)
            if row is None:
                row = await self.repo.add(
                    FacultyWorkload(institution_id=self.inst, staff_id=s.id, term_id=term.id, status="draft")
                )
            row.theory_hours, row.tutorial_hours, row.lab_hours = h["theory"], h["tutorial"], h["lab"]
            row.admin_hours, row.total_hours = admin, total
            row.max_allowed_hours = Decimal(str(norm)) if norm is not None else None
            out.append(
                WorkloadResponse(
                    staff_id=s.id,
                    staff_name=s.full_name,
                    employee_id=s.employee_id,
                    cadre=cadre,
                    term_id=term.id,
                    theory_hours=float(h["theory"]),
                    tutorial_hours=float(h["tutorial"]),
                    lab_hours=float(h["lab"]),
                    project_hours=float(row.project_hours or 0),
                    admin_hours=float(admin),
                    research_hours=float(row.research_hours or 0),
                    total_hours=float(total),
                    max_allowed_hours=float(norm) if norm is not None else None,
                    norm_hours=float(norm) if norm is not None else None,
                    load_status=load,
                    status=row.status,
                    note=(
                        None
                        if offerings_exist
                        else "No course offerings for this term yet (Phase 09) — teaching hours are 0"
                    ),
                )
            )
        await self.db.flush()
        await self._emit("workload.computed", {"term_id": str(term.id), "staff": len(staff)}, "academic_term", term.id)
        return out

    # ---- rule 2 -------------------------------------------------------------------------------------------------
    async def _department(self, department_id: uuid.UUID) -> Department:
        from app.services.academics.context import writable_department_ids

        dept = (
            await self.db.execute(
                select(Department).where(Department.id == department_id, Department.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        writable = await writable_department_ids(self.db, self.principal)
        if dept is None or (writable is not None and dept.id not in writable):
            raise APIError(404, ErrorCode.NOT_FOUND, "Department not found")
        return dept

    async def get_proposal(self, department_id: uuid.UUID, term_id: uuid.UUID | None) -> AllocationProposalOut:
        dept = await self._department(department_id)
        term = await self._term(term_id, dept.college_id)
        row = await self.allocations.for_department(dept.id, term.id)
        if row is None:
            return AllocationProposalOut(
                id=uuid.UUID(int=0),
                department_id=dept.id,
                term_id=term.id,
                proposals=[],
                status="draft",
                note="No proposal yet",
            )
        return await self._out(row)

    async def save_proposal(
        self, department_id: uuid.UUID, term_id: uuid.UUID | None, body: AllocationProposalIn
    ) -> AllocationProposalOut:
        dept = await self._department(department_id)
        term = await self._term(term_id, dept.college_id)
        staff_ids = {p.staff_id for p in body.proposals}
        course_ids = {p.course_id for p in body.proposals}
        if staff_ids:
            members = {s.id for s in await self.staff_repo.active(staff_ids=list(staff_ids))}
            foreign = [str(s) for s in staff_ids if s not in members]
            if foreign:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "Unknown or exited staff in the proposal",
                    {"field": "proposals", "staff_ids": foreign},
                )
        if course_ids:
            found = set(
                (
                    await self.db.execute(
                        select(Course.id).where(Course.id.in_(list(course_ids)), Course.deleted_at.is_(None))
                    )
                )
                .scalars()
                .all()
            )
            missing = [str(c) for c in course_ids if c not in found]
            if missing:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "Unknown courses in the proposal",
                    {"field": "proposals", "course_ids": missing},
                )
        row = await self.allocations.for_department(dept.id, term.id, for_update=True)
        items = [p.model_dump(mode="json") for p in body.proposals]
        if row is None:
            row = await self.allocations.add(
                CourseAllocationProposal(
                    institution_id=self.inst, department_id=dept.id, term_id=term.id, proposals=items, status="draft"
                )
            )
        elif row.status != "draft":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The proposal is {row.status}")
        else:
            row.proposals = items
            await self.db.flush()
        await self._audit("allocation_save", "course_allocation_proposal", row.id, None, {"items": len(items)})
        return await self._out(row)

    async def submit(self, proposal_id: uuid.UUID) -> AllocationProposalOut:
        row = await self.allocations.get_one(proposal_id, for_update=True)
        await self._department(row.department_id)
        if row.status != "draft":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The proposal is {row.status}")
        if not row.proposals:
            raise APIError(422, ErrorCode.VALIDATION, "The proposal is empty", {"field": "proposals"})
        instance = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=ALLOC_KEY,
            entity_type="course_allocation_proposal",
            entity_id=row.id,
            started_by=self.principal.id,
            context={"department_id": str(row.department_id), "term_id": str(row.term_id)},
            title="Course allocation proposal",
        )
        row.status, row.submitted_by, row.workflow_instance_id = "submitted", self.principal.id, instance.id
        await self.db.flush()
        await self._audit(
            "allocation_submit", "course_allocation_proposal", row.id, {"status": "draft"}, {"status": "submitted"}
        )
        return await self._out(row)

    async def approve(
        self, proposal_id: uuid.UUID, decision: str = "approve", comment: str | None = None
    ) -> AllocationProposalOut:
        row = await self.allocations.get_one(proposal_id, for_update=True)
        if row.status != "submitted" or row.workflow_instance_id is None:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The proposal is {row.status}")
        await workflow_engine.act(
            self.db, instance_id=row.workflow_instance_id, actor=self.principal, decision=decision, comment=comment
        )
        await self.db.refresh(row)
        return await self._out(row)

    async def apply(self, proposal_id: uuid.UUID) -> AllocationProposalOut:
        row = await self.allocations.get_one(proposal_id, for_update=True)
        await self._department(row.department_id)
        if row.status != "dean_approved":
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"Only a dean-approved proposal can be applied (this one is {row.status})",
            )
        if await self.repo.offerings_count(row.department_id, row.term_id) == 0:
            raise APIError(409, ErrorCode.RULE_VIOLATION, DEFERRED, {"reason": "offerings_missing"})
        row.status = "applied"
        await self.db.flush()
        await self._audit(
            "allocation_apply", "course_allocation_proposal", row.id, {"status": "dean_approved"}, {"status": "applied"}
        )
        await self._emit(
            "course_allocation.applied",
            {"proposal_id": str(row.id), "department_id": str(row.department_id), "term_id": str(row.term_id)},
            "course_allocation_proposal",
            row.id,
        )
        return await self._out(row)

    async def _out(self, row: CourseAllocationProposal) -> AllocationProposalOut:
        o = AllocationProposalOut.model_validate(row)
        if row.status == "dean_approved" and await self.repo.offerings_count(row.department_id, row.term_id) == 0:
            o.note = DEFERRED
        return o


@workflow_engine.on(ALLOC_KEY, "approved")
async def _on_allocation_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await AllocationRepository(db).get_one(instance.entity_id, for_update=True)
    if row.status == "submitted":
        row.status, row.approved_by = "dean_approved", getattr(actor, "id", None)
        await db.flush()


@workflow_engine.on(ALLOC_KEY, "rejected")
async def _on_allocation_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await AllocationRepository(db).get_one(instance.entity_id, for_update=True)
    if row.status == "submitted":
        row.status, row.workflow_instance_id = "draft", None
        await db.flush()


@workflow_engine.summariser("course_allocation_proposal")
async def _summarise_allocation(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = await AllocationRepository(db).get_one(entity_id)
    return f"Course allocation · {len(row.proposals or [])} item(s)", "/admin/hr/workload"
