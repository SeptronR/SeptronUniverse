"""Student attendance — Prompts/11 §11.5 (``module="attendance"``, visibility from ``timetable_scope``).

* ``AttendanceRepository`` — rosters (confirmed items of the session's offering, section-filtered through the
  timetable entry's ``section_id``), marks of a session, ``upsert_marks`` with ``ON CONFLICT (session_id,
  student_program_enrollment_id, session_date) DO UPDATE`` (the partitioned table's unique key);
* ``SummaryRepository`` — one aggregate query per offering → ``attendance_summaries`` upsert;
* ``OdRepository`` / ``CondonationRepository`` / ``EligibilityRepository`` — scoped lists (``record_predicate``) and
  ``latest_version``.
"""

import uuid
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import APIError, ErrorCode
from app.models.attendance import (
    AttendanceCondonation,
    AttendanceSummary,
    OnDutyRequest,
    StudentClassAttendance,
    TermEligibility,
)
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.models.timetable import ClassSession, TimetableEntry
from app.repositories.base import BaseRepository
from app.repositories.timetable_scope import record_predicate

COUNTED = or_(ClassSession.status == "conducted", ClassSession.attendance_status.in_(("taken", "finalized")))


class AttendanceRepository(BaseRepository[StudentClassAttendance]):
    model = StudentClassAttendance
    module = "attendance"

    async def section_of(self, session: ClassSession) -> uuid.UUID | None:
        if session.timetable_entry_id is None:
            return None
        sid: uuid.UUID | None = (
            await self.db.execute(
                select(TimetableEntry.section_id).where(TimetableEntry.id == session.timetable_entry_id)
            )
        ).scalar_one_or_none()
        return sid

    def roster_stmt(self, offering_id: uuid.UUID, term_id: uuid.UUID | None, section_id: uuid.UUID | None) -> Any:
        stmt = (
            select(
                StudentProgramEnrollment.id,
                Student.id,
                Student.first_name,
                Student.last_name,
                Student.registration_number,
                StudentTermRecord.roll_number,
                Student.photo_url,
                Student.user_id,
            )
            .select_from(CourseRegistrationItem)
            .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
            .join(
                StudentProgramEnrollment,
                StudentProgramEnrollment.id == CourseRegistration.student_program_enrollment_id,
            )
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .join(StudentTermRecord, StudentTermRecord.id == CourseRegistration.student_term_record_id)
            .where(
                CourseRegistrationItem.offering_id == offering_id,
                CourseRegistrationItem.status == "confirmed",
                StudentProgramEnrollment.deleted_at.is_(None),
                Student.deleted_at.is_(None),
            )
        )
        if term_id is not None:
            stmt = stmt.where(CourseRegistration.term_id == term_id)
        if section_id is not None:
            stmt = stmt.where(StudentTermRecord.section_id == section_id)
        return stmt.order_by(StudentTermRecord.roll_number.nulls_last(), Student.registration_number)

    async def roster(self, session: ClassSession) -> list[Any]:
        section = await self.section_of(session)
        return list((await self.db.execute(self.roster_stmt(session.offering_id, session.term_id, section))).all())

    async def roster_ids(self, offering_id: uuid.UUID, term_id: uuid.UUID | None = None) -> set[uuid.UUID]:
        return {r[0] for r in (await self.db.execute(self.roster_stmt(offering_id, term_id, None))).all()}

    async def marks(self, session: ClassSession) -> dict[uuid.UUID, StudentClassAttendance]:
        rows = (
            await self.db.execute(
                select(StudentClassAttendance).where(
                    StudentClassAttendance.session_id == session.id,
                    StudentClassAttendance.session_date == session.session_date,
                )
            )
        ).scalars()
        return {r.student_program_enrollment_id: r for r in rows}

    async def upsert_marks(self, session: ClassSession, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        values = [
            {
                "id": uuid.uuid4(),
                "institution_id": session.institution_id,
                "session_id": session.id,
                "session_date": session.session_date,
                **r,
            }
            for r in rows
        ]
        stmt = insert(StudentClassAttendance).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["session_id", "student_program_enrollment_id", "session_date"],
            set_={
                "status": stmt.excluded.status,
                "source": stmt.excluded.source,
                "marked_by": stmt.excluded.marked_by,
                "marked_at": func.now(),
                "remarks": stmt.excluded.remarks,
            },
        )
        await self.db.execute(stmt)

    async def history(
        self, enrollment_id: uuid.UUID, offering_ids: Iterable[uuid.UUID] | None = None, limit: int = 200
    ) -> list[Any]:
        stmt = (
            select(ClassSession, StudentClassAttendance.status, StudentClassAttendance.source)
            .join(
                StudentClassAttendance,
                and_(
                    StudentClassAttendance.session_id == ClassSession.id,
                    StudentClassAttendance.session_date == ClassSession.session_date,
                    StudentClassAttendance.student_program_enrollment_id == enrollment_id,
                ),
                isouter=True,
            )
            .where(COUNTED)
        )
        if offering_ids is not None:
            stmt = stmt.where(ClassSession.offering_id.in_(list(offering_ids)))
        stmt = stmt.order_by(ClassSession.session_date.desc(), ClassSession.start_time.desc()).limit(limit)
        return list((await self.db.execute(stmt)).all())


class SummaryRepository(BaseRepository[AttendanceSummary]):
    model = AttendanceSummary
    module = "attendance"

    async def aggregate(
        self, offering_id: uuid.UUID, enrollment_ids: Sequence[uuid.UUID] | None = None
    ) -> dict[uuid.UUID, dict[str, int]]:
        """Per enrolment counts over the offering's counted sessions (conducted / attendance taken)."""
        sca = StudentClassAttendance
        stmt = (
            select(
                sca.student_program_enrollment_id,
                func.count().label("marked"),
                *[
                    func.sum(case((sca.status == s, 1), else_=0)).label(s)
                    for s in ("present", "absent", "late", "on_duty", "leave", "medical", "exempt")
                ],
            )
            .join(ClassSession, and_(ClassSession.id == sca.session_id, ClassSession.session_date == sca.session_date))
            .where(ClassSession.offering_id == offering_id, COUNTED)
            .group_by(sca.student_program_enrollment_id)
        )
        if enrollment_ids is not None:
            stmt = stmt.where(sca.student_program_enrollment_id.in_(list(enrollment_ids)))
        out: dict[uuid.UUID, dict[str, int]] = {}
        for row in (await self.db.execute(stmt)).mappings():
            out[row["student_program_enrollment_id"]] = {
                k: int(v or 0) for k, v in row.items() if k != "student_program_enrollment_id"
            }
        return out

    async def counted_sessions(self, offering_id: uuid.UUID) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(ClassSession)
                    .where(ClassSession.offering_id == offering_id, COUNTED)
                )
            ).scalar_one()
        )

    async def upsert(self, institution_id: uuid.UUID, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        stmt = insert(AttendanceSummary).values(
            [{"id": uuid.uuid4(), "institution_id": institution_id, **r} for r in rows]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["offering_id", "student_program_enrollment_id"],
            set_={
                c: getattr(stmt.excluded, c)
                for c in ("total_sessions", "present", "absent", "on_duty", "late", "exempt", "pct", "eligibility")
            }
            | {"computed_at": func.now()},
        )
        await self.db.execute(stmt)

    def scoped(self, scope: str | None = None) -> Select[tuple[AttendanceSummary]]:
        return self._base().where(
            record_predicate(
                self.principal, AttendanceSummary.offering_id, AttendanceSummary.student_program_enrollment_id, scope
            )
        )

    async def of(self, offering_id: uuid.UUID, enrollment_id: uuid.UUID) -> AttendanceSummary | None:
        return (
            await self.db.execute(
                self._base().where(
                    AttendanceSummary.offering_id == offering_id,
                    AttendanceSummary.student_program_enrollment_id == enrollment_id,
                )
            )
        ).scalar_one_or_none()


class OdRepository(BaseRepository[OnDutyRequest]):
    model = OnDutyRequest
    module = "attendance"

    def scoped(self, scope: str | None = None) -> Select[tuple[OnDutyRequest]]:
        return self._base().where(
            record_predicate(self.principal, None, OnDutyRequest.student_program_enrollment_id, scope)
        )

    async def get_one(self, od_id: uuid.UUID, *, for_update: bool = False) -> OnDutyRequest:
        stmt = self.scoped("all").where(OnDutyRequest.id == od_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "On-duty request not found")
        return row

    async def approved_covering(self, enrollment_ids: Sequence[uuid.UUID], on: date) -> set[uuid.UUID]:
        if not enrollment_ids:
            return set()
        rows = await self.db.execute(
            select(OnDutyRequest.student_program_enrollment_id).where(
                OnDutyRequest.student_program_enrollment_id.in_(list(enrollment_ids)),
                OnDutyRequest.status == "approved",
                OnDutyRequest.from_date <= on,
                OnDutyRequest.to_date >= on,
            )
        )
        return set(rows.scalars())


class CondonationRepository(BaseRepository[AttendanceCondonation]):
    model = AttendanceCondonation
    module = "attendance"

    def scoped(self, scope: str | None = None) -> Select[tuple[AttendanceCondonation]]:
        return self._base().where(
            record_predicate(
                self.principal,
                None,
                AttendanceCondonation.student_program_enrollment_id,
                scope,
            )
        )

    async def get_one(self, cid: uuid.UUID, *, for_update: bool = False) -> AttendanceCondonation:
        stmt = self.scoped("all").where(AttendanceCondonation.id == cid)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Condonation request not found")
        return row


class EligibilityRepository(BaseRepository[TermEligibility]):
    model = TermEligibility
    module = "attendance"

    def scoped(self, scope: str | None = None) -> Select[tuple[TermEligibility]]:
        enrol = (
            select(StudentTermRecord.student_program_enrollment_id)
            .where(StudentTermRecord.id == TermEligibility.student_term_record_id)
            .scalar_subquery()
        )
        return self._base().where(record_predicate(self.principal, TermEligibility.offering_id, enrol, scope))

    async def term_version(self, term_id: uuid.UUID) -> int:
        """Highest version written for any record of the term (0 when never computed)."""
        v = (
            await self.db.execute(
                select(func.max(TermEligibility.version))
                .join(StudentTermRecord, StudentTermRecord.id == TermEligibility.student_term_record_id)
                .where(StudentTermRecord.term_id == term_id, TermEligibility.institution_id == self.institution_id)
            )
        ).scalar_one_or_none()
        return int(v or 0)

    async def latest_version(self, term_record_id: uuid.UUID, offering_id: uuid.UUID) -> TermEligibility | None:
        return (
            await self.db.execute(
                self._base()
                .where(
                    TermEligibility.student_term_record_id == term_record_id,
                    TermEligibility.offering_id == offering_id,
                )
                .order_by(TermEligibility.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


__all__ = [
    "COUNTED",
    "AttendanceRepository",
    "CondonationRepository",
    "EligibilityRepository",
    "OdRepository",
    "SummaryRepository",
]
