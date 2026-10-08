"""Holds — Prompts/07 §07.6 ``hold_service.py``.

* ``place(student, hold_type, reason, source)`` — ``students:holds`` places any type; the library (``library:manage``)
  and hostel offices (``hostel:manage``) only ``library`` / ``hostel`` holds (Prompts/07 visibility table). The hold sits
  on the student's open enrolment (or the one named). Fees (Phase 12: overdue → ``registration`` / ``exam`` holds per
  setting), library (Phase 19), hostel (Phase 20), discipline (Phase 27) and standing (``dismissal`` → ``all``) place
  holds through ``place_system`` with their ``source_type`` / ``source_id``.
* ``release(hold, reason)`` — the same type rule (a librarian cannot release an ``all`` hold → 403); the reason is
  kept in the audit row (the DDL has no column) and shown with the released hold.
* ``assert_clear(enrollment, gate)`` raises ``409 HOLD_BLOCKED {hold_type, reason}`` when an open hold of the gate's
  type or ``all`` exists — registration (Phase 09: ``registration|all``), exam registration / hall tickets (``exam``),
  transcripts (``transcript``), degrees (``graduation``), hostel allotment (``hostel``), library issue (``library``).
* The student and the consented guardians are notified on place / release (``hold.placed`` / ``hold.released``).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.models.students import StudentHold, StudentProgramEnrollment
from app.repositories.student_scope import student_visibility
from app.schemas.students import HoldCreate, HoldReleaseRequest, HoldResponse
from app.services.students.common import HOLD_LABELS, StudentServiceBase
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

SYSTEM_USER = uuid.UUID(int=0)  # ``placed_by`` is NOT NULL — holds placed by a job carry the nil id ("system")


class HoldService(StudentServiceBase):
    # ---- reads ------------------------------------------------------------------------------------------------------
    async def for_student(self, student_id: uuid.UUID, include_released: bool = True) -> list[HoldResponse]:
        student = await self.students.get_visible(student_id)
        enrolments = await self.enrollments.for_student(student.id)
        rows = await self.holds.for_enrollments([e.id for e in enrolments], open_only=not include_released)
        return await self.hold_responses(rows)

    async def queue(
        self, params: PageParams, *, status: str | None, hold_type: str | None, q: str | None, scope: str | None
    ) -> tuple[list[HoldResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.holds.queue(status=status, hold_type=hold_type, q=q, scope=scope)
        rows, total = await self.holds.paginate_queue(stmt, params.offset, params.page_size)
        pagination = PaginationMeta(
            page=params.page, page_size=params.page_size, total=total, total_pages=max(1, -(-total // params.page_size))
        )
        return await self.hold_responses(rows), pagination, student_visibility(self.principal)

    # ---- place / release ----------------------------------------------------------------------------------------------
    async def place(self, student_id: uuid.UUID, body: HoldCreate) -> HoldResponse:
        student = await self.students.get_visible(student_id)
        kind = body.hold_type.value
        if not self.may_manage_hold_type(kind):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, f"You may not place {kind} holds", {"hold_type": kind})
        if body.enrollment_id is not None:
            enrolment = await self.enrollments.get_visible(body.enrollment_id)
            if enrolment.student_id != student.id:
                raise APIError(
                    422, ErrorCode.VALIDATION, "The enrolment belongs to another student", {"field": "enrollment_id"}
                )
        else:
            current = await self.enrollments.current(student.id)
            if current is None:
                raise APIError(409, ErrorCode.RULE_VIOLATION, "The student has no enrolment to hold")
            enrolment = current
        hold = await self._place(enrolment, kind, body.reason, body.source_type or "manual", body.source_id)
        return (await self.hold_responses([hold]))[0]

    async def place_system(
        self,
        enrolment: StudentProgramEnrollment,
        hold_type: str,
        reason: str,
        source_type: str,
        source_id: uuid.UUID | None,
    ) -> StudentHold:
        """Holds placed by other modules / jobs (no permission check; idempotent per open source)."""
        for h in await self.holds.open_holds(enrolment.id):
            if h.hold_type == hold_type and h.source_type == source_type and h.source_id == source_id:
                return h
        return await self._place(enrolment, hold_type, reason, source_type, source_id)

    async def _place(
        self,
        enrolment: StudentProgramEnrollment,
        hold_type: str,
        reason: str,
        source_type: str | None,
        source_id: uuid.UUID | None,
    ) -> StudentHold:
        hold = await self.holds.add(
            StudentHold(
                institution_id=self.inst,
                student_program_enrollment_id=enrolment.id,
                hold_type=hold_type,
                reason=reason.strip(),
                placed_by=self.actor_id or SYSTEM_USER,
                source_type=source_type,
                source_id=source_id,
            )
        )
        student = await self.students.by_id(enrolment.student_id)
        await self._audit(
            "place",
            "student_hold",
            hold.id,
            None,
            {
                "student_id": str(enrolment.student_id),
                "hold_type": hold_type,
                "reason": reason,
                "source_type": source_type,
                "source_id": str(source_id) if source_id else None,
            },
        )
        await self._emit(
            "hold.placed",
            {
                "hold_id": str(hold.id),
                "student_id": str(enrolment.student_id),
                "enrollment_id": str(enrolment.id),
                "hold_type": hold_type,
                "source_type": source_type,
            },
            "student",
            enrolment.student_id,
        )
        if student is not None:
            await self._notify(
                "hold.placed",
                [student.user_id],
                {
                    "hold_label": HOLD_LABELS.get(hold_type, hold_type),
                    "student_name": student.full_name,
                    "reason": reason,
                    "contact": (
                        "the registrar's office"
                        if hold_type in ("all", "registration", "exam")
                        else f"the {hold_type} office"
                    ),
                },
                guardians=True,
            )
        return hold

    async def release(self, hold_id: uuid.UUID, body: HoldReleaseRequest) -> HoldResponse:
        hold = await self.holds.get(hold_id, for_update=True)
        if hold is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Hold not found")
        if hold.released_at is not None:
            raise APIError(409, ErrorCode.CONFLICT, "The hold was already released")
        if not self.may_manage_hold_type(hold.hold_type):
            raise APIError(
                403,
                ErrorCode.PERMISSION_DENIED,
                f"You may not release {hold.hold_type} holds",
                {"hold_type": hold.hold_type},
            )
        hold.released_by, hold.released_at = self.actor_id or SYSTEM_USER, datetime.now(UTC)
        await self.db.flush()
        enrolment = await self.enrollments.by_id(hold.student_program_enrollment_id)
        student = await self.students.by_id(enrolment.student_id) if enrolment else None
        await self._audit(
            "release",
            "student_hold",
            hold.id,
            {"released_at": None},
            {"released_at": hold.released_at.isoformat(), "release_reason": body.reason, "hold_type": hold.hold_type},
        )
        await self._emit(
            "hold.released",
            {"hold_id": str(hold.id), "student_id": str(student.id) if student else None, "hold_type": hold.hold_type},
            "student",
            student.id if student else None,
        )
        if student is not None:
            await self._notify(
                "hold.released",
                [student.user_id],
                {
                    "hold_label": HOLD_LABELS.get(hold.hold_type, hold.hold_type),
                    "student_name": student.full_name,
                    "reason": body.reason,
                },
                guardians=True,
            )
        return (await self.hold_responses([hold]))[0]

    # ---- gate ---------------------------------------------------------------------------------------------------------
    async def assert_clear(self, enrollment_id: uuid.UUID, gate: str) -> None:
        if not await is_enabled(self.inst, "students.holds"):
            return
        blocking = await self.holds.open_holds(enrollment_id, gate)
        if blocking:
            first = blocking[0]
            raise APIError(
                409,
                ErrorCode.HOLD_BLOCKED,
                f"{HOLD_LABELS.get(first.hold_type, first.hold_type)} hold: {first.reason}",
                {
                    "hold_type": first.hold_type,
                    "reason": first.reason,
                    "gate": gate,
                    "holds": [{"id": str(h.id), "hold_type": h.hold_type, "reason": h.reason} for h in blocking],
                },
            )


async def assert_clear(db: Any, principal: Any, enrollment_id: uuid.UUID, gate: str, institution_id: uuid.UUID) -> None:
    """Module-level helper for later phases (registration, exams, transcripts, degrees, hostel, library)."""
    await HoldService(db, principal, None, institution_id).assert_clear(enrollment_id, gate)
