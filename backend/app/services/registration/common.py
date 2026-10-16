"""Shared plumbing of the Phase 09 offering / registration services — tenant, repositories, audit / outbox /
notifications (Phase 07 base), terms and credit limits, the prerequisite evidence, seat control under row locks with
waitlist promotion, and the response builders that batch-load a page of offerings / registrations.

**Passed courses before Phase 15.** A hard prerequisite needs a passed course. The evidence, in order:

1. a published, current ``student_course_results`` row with ``result_status`` ``pass`` / ``exempted`` (Phase 15);
2. an approved ``credit_transfers`` row whose ``equivalent_course_id`` is the course (Phase 07);
3. until Phase 15 publishes results: a curriculum course of an *earlier* term of the enrolment's programme-regulation
   (or a confirmed item of an earlier term) without an ``open`` / ``registered`` arrear — the arrears register is the
   record of failures (Phase 07 seeds the backlogs, Phase 15 maintains it).

The development flag ``registration.prerequisite_bypass`` (setting, default off) skips the check entirely.

**Registration fee before Phase 12.** ``submit`` records a mock-payment order (registration fee + arrear fee per
credit + the late fee of a ``late`` window) as an audit row ``(record_type='course_registration', action='fee_order')``;
``fee_invoice_id`` stays NULL until Phase 12 ``fee_service.create_registration_invoice``.

**Overrides** (registrar, ``registration.overrides``) are audit rows ``action='override'`` on the registration; the
latest values (``max_credits`` / ``skip_prerequisites`` / ``skip_holds``) are merged and read by the checks.

**Seats.** ``take_seat`` / ``release_seat`` run with the offering row locked ``FOR UPDATE``: ``enrolled_count`` counts
seated items plus seats *held* for a waitlist offer, so concurrent registrations never exceed ``max_seats``. A
released seat goes to the first ``waiting`` row (FCFS): the row becomes ``offered`` with ``offered_until`` (setting
``registration.waitlist_offer_hours``, 48 h) and the student accepts it (→ ``confirmed`` / ``selected``); the Beat
``waitlist.expire`` drops expired offers and offers the seat to the next in line.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicTerm, Batch, BatchSection, Program, ProgramRegulation, ProgramStructureTerm
from app.models.curriculum import Course, CoursePrerequisite, CurriculumCourse
from app.models.hr import Staff
from app.models.offerings import CourseOffering
from app.models.platform import AuditLog, College, Department
from app.models.registration import (
    CourseRegistration,
    CourseRegistrationItem,
    OfferingWaitlist,
    RegistrationWindow,
    StudentArrear,
)
from app.models.students import CreditTransfer, Student, StudentProgramEnrollment, StudentTermRecord
from app.repositories.arrear_repository import ArrearRepository
from app.repositories.choice_form_repository import ChoiceFormRepository
from app.repositories.offering_repository import OfferingRepository
from app.repositories.registration_repository import RegistrationRepository
from app.repositories.waitlist_repository import WaitlistRepository
from app.repositories.window_repository import WindowRepository, window_is_open
from app.schemas.offerings import FacultyOut, OfferingResponse, TargetOut, WindowResponse
from app.schemas.registration import (
    CreditLimits,
    FeeOrder,
    RegistrationItemOut,
    RegistrationListItem,
    RegistrationResponse,
    WaitlistBrief,
)
from app.services.students.common import StudentServiceBase

REG = "course_registration"


def utcnow() -> datetime:
    return datetime.now(UTC)


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    """``409 RULE_VIOLATION`` with ``details.code`` (``CREDIT_LIMIT``, ``PREREQUISITE_NOT_MET`` …)."""
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def credits_of(course: Course | None) -> Decimal:
    return Decimal(str(course.credits)) if course is not None and course.credits is not None else Decimal(0)


class RegistrationBase(StudentServiceBase):
    audit_module = "registration"

    def __init__(
        self, db: AsyncSession, principal: Any, request: Request | None = None, institution_id: uuid.UUID | None = None
    ):
        super().__init__(db, principal, request, institution_id)
        self.offerings = OfferingRepository(db, principal, self.inst)
        self.regs = RegistrationRepository(db, principal, self.inst)
        self.windows = WindowRepository(db, self.inst)
        self.forms = ChoiceFormRepository(db, self.inst)
        self.waitlists = WaitlistRepository(db, self.inst)
        self.arrears = ArrearRepository(db, principal, self.inst)

    # ---- settings / context ----------------------------------------------------------------------------------------
    async def reg_setting(self, key: str, default: Any = None) -> Any:
        value = await self.setting("registration", key)
        return default if value is None else value

    async def get_term(self, term_id: uuid.UUID | None, college_id: uuid.UUID | None = None) -> AcademicTerm:
        if term_id is None:
            return await self.require_current_term(college_id)
        term = (
            await self.db.execute(
                select(AcademicTerm).where(
                    AcademicTerm.id == term_id,
                    AcademicTerm.institution_id == self.inst,
                    AcademicTerm.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if term is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Academic term not found", {"field": "term_id"})
        return term

    async def me(self) -> tuple[Student, StudentProgramEnrollment]:
        student = await self.students.by_user(self.principal.id) if self.actor_id else None
        if student is None:
            raise APIError(
                404, ErrorCode.NOT_FOUND, "Your account is not linked to a student record", {"reason": "no_student"}
            )
        enrolment = await self.enrollments.open_for(student.id)
        if enrolment is None:
            raise rule("You have no open programme enrolment", "NO_ENROLMENT")
        return student, enrolment

    async def term_record(self, enrolment_id: uuid.UUID, term_id: uuid.UUID) -> StudentTermRecord:
        row = (
            await self.db.execute(
                select(StudentTermRecord).where(
                    StudentTermRecord.student_program_enrollment_id == enrolment_id,
                    StudentTermRecord.term_id == term_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise rule(
                "No term record for this term — the student is not promoted into it",
                "NO_TERM_RECORD",
                term_id=str(term_id),
            )
        return row

    async def structure_term(self, pr_id: uuid.UUID, term_number: int) -> ProgramStructureTerm | None:
        return (
            await self.db.execute(
                select(ProgramStructureTerm).where(
                    ProgramStructureTerm.program_regulation_id == pr_id,
                    ProgramStructureTerm.term_number == term_number,
                )
            )
        ).scalar_one_or_none()

    async def limits(
        self,
        enrolment: StudentProgramEnrollment,
        record: StudentTermRecord,
        window: RegistrationWindow | None,
        overrides: dict[str, Any] | None = None,
    ) -> CreditLimits:
        st = await self.structure_term(enrolment.program_regulation_id, record.term_number)
        lo = float(st.min_credits) if st else 0.0
        hi = float(st.max_credits) if st else 40.0
        normal = float(st.normal_credits) if st else hi
        overridden = False
        if window is not None and window.max_credits_override is not None:
            hi = float(window.max_credits_override)
        if overrides and overrides.get("max_credits") is not None:
            hi, overridden = float(overrides["max_credits"]), True
        return CreditLimits(min=lo, max=hi, normal=normal, overridden=overridden)

    async def open_windows(
        self, term_id: uuid.UUID, enrolment: StudentProgramEnrollment, record: StudentTermRecord
    ) -> list[RegistrationWindow]:
        return await self.windows.open_windows(term_id, enrolment, record, utcnow())

    # ---- audit-backed state (overrides, fee order, advisor comment) -------------------------------------------------
    async def _audit_rows(self, registration_id: uuid.UUID, action: str) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.institution_id == self.inst,
                AuditLog.record_type == REG,
                AuditLog.record_id == registration_id,
                AuditLog.action == action,
            )
            .order_by(AuditLog.occurred_at)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def overrides(self, registration_id: uuid.UUID) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for row in await self._audit_rows(registration_id, "override"):
            for k, v in (row.new_values or {}).items():
                if k == "skip_prerequisites":
                    merged[k] = sorted(set(merged.get(k, [])) | set(v or []))
                elif v is not None:
                    merged[k] = v
        return merged

    async def fee_order(self, registration_id: uuid.UUID) -> FeeOrder | None:
        rows = await self._audit_rows(registration_id, "fee_order")
        if not rows:
            return None
        data = dict(rows[-1].new_values or {})
        return FeeOrder.model_validate({**data, "created_at": rows[-1].occurred_at})

    async def advisor_comment(self, registration_id: uuid.UUID) -> str | None:
        rows = await self._audit_rows(registration_id, "advisor_decision")
        return (rows[-1].new_values or {}).get("comment") if rows else None

    # ---- prerequisites ---------------------------------------------------------------------------------------------
    async def passed_course_ids(
        self, enrolment: StudentProgramEnrollment, record: StudentTermRecord | None
    ) -> set[uuid.UUID]:
        """Courses the enrolment has passed (see the module docstring for the evidence order)."""
        passed: set[uuid.UUID] = set()
        rows = (
            await self.db.execute(
                text(
                    "SELECT course_id FROM student_course_results WHERE student_program_enrollment_id = CAST(:e AS uuid) "
                    "AND is_current AND status = 'published' AND result_status IN ('pass','exempted')"
                ),
                {"e": str(enrolment.id)},
            )
        ).all()
        passed |= {uuid.UUID(str(r[0])) for r in rows}
        transfers = (
            await self.db.execute(
                select(CreditTransfer.equivalent_course_id).where(
                    CreditTransfer.student_program_enrollment_id == enrolment.id,
                    CreditTransfer.status == "approved",
                    CreditTransfer.equivalent_course_id.is_not(None),
                )
            )
        ).scalars()
        passed |= {c for c in transfers if c}
        failing = set(
            (
                await self.db.execute(
                    select(StudentArrear.course_id).where(
                        StudentArrear.student_program_enrollment_id == enrolment.id,
                        StudentArrear.status.in_(("open", "registered")),
                    )
                )
            ).scalars()
        )
        if record is not None:
            earlier = (
                await self.db.execute(
                    select(CurriculumCourse.course_id).where(
                        CurriculumCourse.program_regulation_id == enrolment.program_regulation_id,
                        CurriculumCourse.term_number < record.term_number,
                        CurriculumCourse.elective_basket_id.is_(None),
                    )
                )
            ).scalars()
            passed |= {c for c in earlier if c not in failing}
            prior = (
                await self.db.execute(
                    select(CourseRegistrationItem.course_id)
                    .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
                    .join(StudentTermRecord, StudentTermRecord.id == CourseRegistration.student_term_record_id)
                    .where(
                        CourseRegistration.student_program_enrollment_id == enrolment.id,
                        CourseRegistrationItem.status == "confirmed",
                        StudentTermRecord.term_number < record.term_number,
                    )
                )
            ).scalars()
            passed |= {c for c in prior if c not in failing}
        return passed

    async def relations(self, course_ids: Sequence[uuid.UUID]) -> list[CoursePrerequisite]:
        if not course_ids:
            return []
        ids = list(course_ids)
        stmt = select(CoursePrerequisite).where(
            (CoursePrerequisite.course_id.in_(ids)) | (CoursePrerequisite.related_course_id.in_(ids))
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ---- seats & waitlists --------------------------------------------------------------------------------------------
    async def take_seat(self, offering: CourseOffering) -> bool:
        """The offering row must be locked by the caller. True → seated, False → full."""
        if offering.max_seats is not None and offering.enrolled_count >= offering.max_seats:
            return False
        offering.enrolled_count += 1
        return True

    async def release_seat(self, offering_id: uuid.UUID, *, promote: bool = True) -> OfferingWaitlist | None:
        offering = await self.offerings.get_one(offering_id, for_update=True)
        offering.enrolled_count = max(0, offering.enrolled_count - 1)
        await self.db.flush()
        if promote:
            return await self.promote_next(offering)
        return None

    async def promote_next(self, offering: CourseOffering) -> OfferingWaitlist | None:
        """Offer the freed seat to the first waiting student (seat held while the offer is open)."""
        if offering.max_seats is not None and offering.enrolled_count >= offering.max_seats:
            return None
        row = await self.waitlists.next_waiting(offering.id)
        if row is None:
            return None
        hours = int(await self.reg_setting("waitlist_offer_hours", 48))
        row.status, row.offered_until = "offered", utcnow() + timedelta(hours=hours)
        offering.enrolled_count += 1
        offering.waitlist_count = max(0, offering.waitlist_count - 1)
        await self.db.flush()
        course = (await self.offerings.rows(Course, [offering.course_id])).get(offering.course_id)
        payload = {
            "waitlist_id": str(row.id),
            "offering_id": str(offering.id),
            "enrollment_id": str(row.student_program_enrollment_id),
            "offered_until": row.offered_until.isoformat(),
        }
        await self._emit("waitlist.offered", payload, "offering_waitlist", row.id)
        await self._notify(
            "waitlist.offered",
            [await self.user_of_enrollment(row.student_program_enrollment_id)],
            {
                "course": course.code if course else "",
                "offered_until": row.offered_until.strftime("%d %b %Y %H:%M UTC"),
            },
        )
        return row

    async def user_of_enrollment(self, enrollment_id: uuid.UUID) -> uuid.UUID | None:
        row = (
            await self.db.execute(
                select(Student.user_id)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.id == enrollment_id)
            )
        ).first()
        return row[0] if row else None

    async def recompute_total(self, registration: CourseRegistration) -> Decimal:
        items = (await self.regs.items([registration.id])).get(registration.id, [])
        courses = await self.offerings.rows(Course, [i.course_id for i in items])
        total = sum(
            (
                credits_of(courses.get(i.course_id))
                for i in items
                if i.status in ("selected", "confirmed") and i.is_credit_bearing
            ),
            Decimal(0),
        )
        registration.total_credits = total
        await self.db.flush()
        return total

    # ---- response builders ---------------------------------------------------------------------------------------------
    def window_out(self, w: RegistrationWindow, term_name: str | None = None) -> WindowResponse:
        out = WindowResponse.model_validate(w)
        out.term_name = term_name
        out.is_open_now = window_is_open(w, utcnow())
        if w.max_credits_override is not None:
            out.max_credits_override = float(w.max_credits_override)
        return out

    async def offering_responses(
        self, rows: Sequence[CourseOffering], *, workload: bool = False
    ) -> list[OfferingResponse]:
        rows = list(rows)
        ids = [o.id for o in rows]
        courses = await self.offerings.rows(Course, [o.course_id for o in rows])
        terms = await self.offerings.rows(AcademicTerm, [o.term_id for o in rows])
        depts = await self.offerings.rows(Department, [o.department_id for o in rows])
        colleges = await self.offerings.rows(College, [o.college_id for o in rows])
        faculty = await self.offerings.faculty(ids)
        targets = await self.offerings.targets(ids)
        staff = await self.offerings.rows(
            Staff,
            [f.staff_id for fs in faculty.values() for f in fs] + [o.coordinator_staff_id for o in rows],
        )
        batches = await self.offerings.rows(Batch, [t.batch_id for ts in targets.values() for t in ts])
        sections = await self.offerings.rows(BatchSection, [t.section_id for ts in targets.values() for t in ts])
        mine_staff = {s.id for s in staff.values() if s.user_id is not None and s.user_id == self.actor_id}
        loads: dict[tuple[uuid.UUID, uuid.UUID], Any] = {}
        if workload and staff:
            loads = await self._loads(rows, faculty, staff)
        out: list[OfferingResponse] = []
        for o in rows:
            c = courses.get(o.course_id)
            r = OfferingResponse.model_validate(o)
            r.course_code, r.course_title = (c.code, c.title) if c else (None, None)
            r.course_type = c.course_type if c else None
            r.credits = float(credits_of(c))
            r.regulation_id = c.regulation_id if c else None
            r.term_name = terms[o.term_id].name if o.term_id in terms else None
            r.department_code = depts[o.department_id].code if o.department_id in depts else None
            r.college_code = colleges[o.college_id].code if o.college_id in colleges else None
            coord = staff.get(o.coordinator_staff_id) if o.coordinator_staff_id else None
            r.coordinator_name = coord.full_name if coord else None
            r.seats_left = None if o.max_seats is None else max(0, o.max_seats - o.enrolled_count)
            for f in faculty.get(o.id, []):
                s = staff.get(f.staff_id)
                load = loads.get((o.term_id, f.staff_id))
                r.faculty.append(
                    FacultyOut(
                        staff_id=f.staff_id,
                        name=s.full_name if s else None,
                        employee_id=s.employee_id if s else None,
                        department_id=s.department_id if s else None,
                        role=f.role,
                        hours_per_week=f.hours_per_week,
                        total_hours=load.total_hours if load else None,
                        norm_hours=load.norm_hours if load else None,
                        load_status=load.load_status if load else None,
                    )
                )
            r.is_mine = any(f.staff_id in mine_staff for f in faculty.get(o.id, []))
            for t in targets.get(o.id, []):
                b = batches.get(t.batch_id)
                s2 = sections.get(t.section_id) if t.section_id else None
                r.targets.append(
                    TargetOut(
                        id=t.id,
                        batch_id=t.batch_id,
                        batch_code=b.code if b else None,
                        section_id=t.section_id,
                        section_name=s2.name if s2 else None,
                        term_number=t.term_number,
                    )
                )
            out.append(r)
        return out

    async def _loads(
        self, rows: Sequence[CourseOffering], faculty: dict[uuid.UUID, list[Any]], staff: dict[uuid.UUID, Staff]
    ) -> dict[tuple[uuid.UUID, uuid.UUID], Any]:
        """(term, staff) → Phase 06 workload (hours vs the cadre norm) for the faculty badges."""
        from app.services.workload_service import WorkloadService

        svc = WorkloadService(self.db, self.principal, self.request, self.inst)
        out: dict[tuple[uuid.UUID, uuid.UUID], Any] = {}
        by_term: dict[uuid.UUID, set[uuid.UUID]] = {}
        for o in rows:
            for f in faculty.get(o.id, []):
                by_term.setdefault(o.term_id, set()).add(f.staff_id)
        terms = await self.offerings.rows(AcademicTerm, list(by_term))
        for term_id, staff_ids in by_term.items():
            members = [staff[s] for s in staff_ids if s in staff]
            if not members or term_id not in terms:
                continue
            for w in await svc.compute(members, terms[term_id]):
                out[(term_id, w.staff_id)] = w
        return out

    async def registration_responses(
        self, rows: Sequence[CourseRegistration], *, full: bool = True, confirmed_only: bool = False
    ) -> list[RegistrationResponse]:
        rows = list(rows)
        enrolments = await self.offerings.rows(
            StudentProgramEnrollment, [r.student_program_enrollment_id for r in rows]
        )
        students = await self.offerings.rows(Student, [e.student_id for e in enrolments.values()])
        records = await self.offerings.rows(StudentTermRecord, [r.student_term_record_id for r in rows])
        sections = await self.offerings.rows(BatchSection, [t.section_id for t in records.values()])
        batches = await self.offerings.rows(Batch, [e.batch_id for e in enrolments.values()])
        programs = await self.offerings.rows(Program, [e.program_id for e in enrolments.values()])
        depts = await self.offerings.rows(Department, [e.department_id for e in enrolments.values()])
        terms = await self.offerings.rows(AcademicTerm, [r.term_id for r in rows])
        windows = await self.offerings.rows(RegistrationWindow, [r.window_id for r in rows])
        items = await self.regs.items([r.id for r in rows])
        offerings = await self.offerings.rows(CourseOffering, [i.offering_id for its in items.values() for i in its])
        courses = await self.offerings.rows(Course, [i.course_id for its in items.values() for i in its])
        out: list[RegistrationResponse] = []
        for r in rows:
            e = enrolments.get(r.student_program_enrollment_id)
            s = students.get(e.student_id) if e else None
            rec = records.get(r.student_term_record_id)
            sec = sections.get(rec.section_id) if rec and rec.section_id else None
            w = windows.get(r.window_id) if r.window_id else None
            resp = RegistrationResponse(
                id=r.id,
                student_id=s.id if s else None,
                student_name=s.full_name if s else None,
                registration_number=s.registration_number if s else None,
                enrollment_id=r.student_program_enrollment_id,
                program_code=programs[e.program_id].code if e and e.program_id in programs else None,
                batch_code=batches[e.batch_id].code if e and e.batch_id in batches else None,
                section_name=sec.name if sec else None,
                department_code=depts[e.department_id].code if e and e.department_id in depts else None,
                term_id=r.term_id,
                term_name=terms[r.term_id].name if r.term_id in terms else None,
                term_number=rec.term_number if rec else None,
                window_id=r.window_id,
                window_name=w.name if w else None,
                status=r.status,
                total_credits=float(r.total_credits or 0),
                fee_invoice_id=r.fee_invoice_id,
                submitted_at=r.submitted_at,
                approved_by=r.approved_by,
                approved_at=r.approved_at,
                locked_at=r.locked_at,
                workflow_instance_id=r.workflow_instance_id,
                version=r.version,
                updated_at=r.updated_at,
            )
            waits: dict[uuid.UUID, OfferingWaitlist] = {}
            if e is not None and any(i.status == "waitlisted" for i in items.get(r.id, [])):
                waits = {w2.offering_id: w2 for w2 in await self.waitlists.for_enrollment(e.id)}
            for i in items.get(r.id, []):
                if confirmed_only and i.status != "confirmed":
                    continue
                o = offerings.get(i.offering_id)
                c = courses.get(i.course_id)
                wl = waits.get(i.offering_id) if i.status == "waitlisted" else None
                resp.items.append(
                    RegistrationItemOut(
                        id=i.id,
                        offering_id=i.offering_id,
                        course_id=i.course_id,
                        course_code=c.code if c else None,
                        course_title=c.title if c else None,
                        credits=float(credits_of(c)),
                        section_code=o.section_code if o else None,
                        registration_type=i.registration_type,
                        attempt_number=i.attempt_number,
                        priority=i.priority,
                        status=i.status,
                        is_credit_bearing=i.is_credit_bearing,
                        added_at=i.added_at,
                        dropped_at=i.dropped_at,
                        drop_reason=i.drop_reason,
                        prerequisite_override_by=i.prerequisite_override_by,
                        waitlist=(
                            WaitlistBrief(
                                id=wl.id, position=wl.position, status=wl.status, offered_until=wl.offered_until
                            )
                            if wl
                            else None
                        ),
                    )
                )
            if full and e is not None and rec is not None:
                ov = await self.overrides(r.id)
                resp.overrides = ov or None
                resp.limits = await self.limits(e, rec, w, ov)
                resp.fee = await self.fee_order(r.id)
                resp.advisor_comment = await self.advisor_comment(r.id)
            out.append(resp)
        return out

    async def reg_list_items(self, rows: Sequence[CourseRegistration]) -> list[RegistrationListItem]:
        full = await self.registration_responses(rows, full=False)
        counts = await self.regs.counts([r.id for r in rows])
        out = []
        for r in full:
            seated, waiting = counts.get(r.id, (0, 0))
            out.append(
                RegistrationListItem(
                    id=r.id,
                    student_id=r.student_id,
                    student_name=r.student_name,
                    registration_number=r.registration_number,
                    program_code=r.program_code,
                    batch_code=r.batch_code,
                    section_name=r.section_name,
                    department_code=r.department_code,
                    term_id=r.term_id,
                    term_name=r.term_name,
                    status=r.status,
                    total_credits=r.total_credits,
                    items_count=seated,
                    waitlisted_count=waiting,
                    submitted_at=r.submitted_at,
                    approved_at=r.approved_at,
                )
            )
        return out

    # ---- shared lookups --------------------------------------------------------------------------------------------------
    async def program_regulation(self, pr_id: uuid.UUID) -> ProgramRegulation | None:
        return (await self.offerings.rows(ProgramRegulation, [pr_id])).get(pr_id)
