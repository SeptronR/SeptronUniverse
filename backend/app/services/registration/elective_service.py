"""Elective choice forms and allocation runs — Prompts/09 §09.6 ``elective_service.py`` (+ ``arrear_service.py``).

Choice forms: one per enrolment × basket × term, submitted / replaced while a registration window is open and the form
is not yet allocated; priorities unique, courses ⊂ basket. ``allocate(basket, term, mode, dry_run)``: candidates =
forms ``submitted`` / ``unallocated``; ``priority_cgpa`` sorts by CGPA desc (latest term record / enrolment; registration
number breaks ties — before Phase 15 most CGPAs come from the Phase 07 history), ``fcfs`` by ``submitted_at``,
``lottery`` by a seeded shuffle; each student's choices are walked in priority order to the first offering with a
free seat → ``allocated_course_id`` + a cart item (``selected``, or ``confirmed`` with
``registration.auto_confirm_allocations``); nobody left out silently — unplaced forms become ``manual``. Dry runs
simulate the seats; the real run (job) locks the offerings ``FOR UPDATE`` and records an ``elective_allocation_runs``
row with the summary.

Arrears: open / registered / cleared / waived; registration moves ``open → registered``; the registrar waives with a
reason; Phase 15 publication calls ``record_result`` (fail → open with attempts + 1, pass → cleared).
"""

import random
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicTerm, Batch, Program
from app.models.curriculum import Course, ElectiveBasket, ElectiveBasketCourse
from app.models.registration import ElectiveAllocationRun, ElectiveChoiceForm, StudentArrear
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.schemas.registration import (
    AllocationResultRow,
    AllocationSummary,
    ArrearResponse,
    ChoiceFormResponse,
    ChoiceFormSubmit,
    ManualAllocation,
    WaiveRequest,
)
from app.services.registration.common import credits_of, rule, utcnow
from app.services.registration.registration_service import RegistrationService
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta


class ElectiveService(RegistrationService):
    async def _basket(self, basket_id: uuid.UUID) -> tuple[ElectiveBasket, set[uuid.UUID]]:
        basket = (await self.offerings.rows(ElectiveBasket, [basket_id])).get(basket_id)
        if basket is None or basket.deleted_at is not None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Elective basket not found")
        courses = set(
            (
                await self.db.execute(
                    select(ElectiveBasketCourse.course_id).where(ElectiveBasketCourse.basket_id == basket.id)
                )
            ).scalars()
        )
        return basket, courses

    # ---- choice forms (self) ------------------------------------------------------------------------------------------
    async def my_form(self, basket_id: uuid.UUID, term_id: uuid.UUID | None) -> ChoiceFormResponse | None:
        _, enrolment = await self.me()
        term = await self.get_term(term_id, enrolment.college_id)
        f = await self.forms.get_for(enrolment.id, basket_id, term.id)
        return await self.form_out(f) if f else None

    async def submit_form(self, basket_id: uuid.UUID, body: ChoiceFormSubmit, *, replace: bool) -> ChoiceFormResponse:
        _, enrolment = await self.me()
        basket, courses = await self._basket(basket_id)
        if basket.program_regulation_id != enrolment.program_regulation_id:
            raise APIError(404, ErrorCode.NOT_FOUND, "Elective basket not found")
        term = await self.get_term(body.term_id, enrolment.college_id)
        record = await self.term_record(enrolment.id, term.id)
        if not await self.open_windows(term.id, enrolment, record):
            raise rule("No registration window is open for you in this term", "WINDOW_CLOSED")
        foreign = [str(c.course_id) for c in body.choices if c.course_id not in courses]
        if foreign:
            raise APIError(
                422, ErrorCode.VALIDATION, "Courses outside the basket", {"field": "choices", "course_ids": foreign}
            )
        f = await self.forms.get_for(enrolment.id, basket.id, term.id, for_update=True)
        choices = [{"course_id": str(c.course_id), "priority": c.priority} for c in body.choices]
        if f is None:
            f = await self.forms.add(
                ElectiveChoiceForm(
                    institution_id=self.inst,
                    student_program_enrollment_id=enrolment.id,
                    elective_basket_id=basket.id,
                    term_id=term.id,
                    choices=choices,
                    status="submitted",
                )
            )
        else:
            if not replace:
                raise APIError(409, ErrorCode.CONFLICT, "A choice form exists — replace it with PUT")
            if f.status not in ("submitted", "unallocated"):
                raise APIError(409, ErrorCode.RECORD_LOCKED, f"The form is already {f.status}")
            f.choices = choices
            await self.db.flush()
        await self._audit("choice_form", "elective_choice_form", f.id, None, {"choices": choices})
        return await self.form_out(f)

    # ---- allocation ---------------------------------------------------------------------------------------------------
    async def allocate(
        self,
        basket_id: uuid.UUID,
        term_id: uuid.UUID,
        mode: str | None,
        *,
        dry_run: bool = True,
        seed: int | None = None,
        job_id: uuid.UUID | None = None,
        progress: Callable[..., Any] | None = None,
    ) -> AllocationSummary:
        basket, basket_courses = await self._basket(basket_id)
        term = await self.get_term(term_id)
        mode = mode or basket.allocation_mode or "priority_cgpa"
        forms = await self.forms.for_basket(basket.id, term.id, ("submitted", "unallocated"), lock=not dry_run)
        enrolments = await self.offerings.rows(
            StudentProgramEnrollment, [f.student_program_enrollment_id for f in forms]
        )
        students = await self.offerings.rows(Student, [e.student_id for e in enrolments.values()])
        cgpa: dict[uuid.UUID, float] = {}
        for e in enrolments.values():
            latest = (await self.terms.latest_for([e.id])).get(e.id)
            value = (latest.cgpa if latest and latest.cgpa is not None else None) or e.cgpa
            cgpa[e.id] = float(value) if value is not None else -1.0

        def regno(f: ElectiveChoiceForm) -> str:
            e = enrolments.get(f.student_program_enrollment_id)
            s = students.get(e.student_id) if e else None
            return s.registration_number if s else ""

        if mode == "fcfs":
            forms.sort(key=lambda f: (f.submitted_at, regno(f)))
        elif mode == "lottery":
            rnd = random.Random(seed if seed is not None else int(utcnow().timestamp()))
            forms.sort(key=regno)
            rnd.shuffle(forms)
        else:
            forms.sort(key=lambda f: (-cgpa.get(f.student_program_enrollment_id, -1.0), regno(f)))
        offs = await self.offerings.for_courses(term.id, list(basket_courses), statuses=("open",))
        courses = await self.offerings.rows(Course, list(basket_courses))
        seats = {o.id: (o.max_seats - o.enrolled_count) if o.max_seats is not None else 10**6 for o in offs}
        run: ElectiveAllocationRun | None = None
        if not dry_run:
            run = await self.forms.add(
                ElectiveAllocationRun(
                    institution_id=self.inst,
                    elective_basket_id=basket.id,
                    term_id=term.id,
                    mode=mode,
                    params={"seed": seed},
                    run_by=self.actor_id,
                    job_id=job_id,
                )
            )
        auto_confirm = bool(await self.reg_setting("auto_confirm_allocations", False))
        summary = AllocationSummary(
            run_id=run.id if run else None,
            job_id=job_id,
            basket_id=basket.id,
            basket_code=basket.code,
            term_id=term.id,
            mode=mode,
            dry_run=dry_run,
            candidates=len(forms),
        )
        per_course: dict[uuid.UUID, int] = {}
        for rank, f in enumerate(forms, start=1):
            e = enrolments.get(f.student_program_enrollment_id)
            s = students.get(e.student_id) if e else None
            placed: tuple[Any, int] | None = None
            for n, choice in enumerate(sorted(f.choices or [], key=lambda c: c.get("priority", 99)), start=1):
                cid = uuid.UUID(str(choice["course_id"]))
                for o in sorted((o for o in offs if o.course_id == cid), key=lambda o: -seats[o.id]):
                    if seats[o.id] > 0:
                        placed = (o, n)
                        break
                if placed:
                    break
            row = AllocationResultRow(
                form_id=f.id,
                enrollment_id=f.student_program_enrollment_id,
                student_name=s.full_name if s else None,
                registration_number=s.registration_number if s else None,
                rank=rank,
                sort_key=f"{cgpa.get(f.student_program_enrollment_id, -1):.2f}"
                if mode == "priority_cgpa"
                else (f.submitted_at.isoformat() if mode == "fcfs" else None),
                status="manual",
            )
            if placed:
                o, n = placed
                seats[o.id] -= 1
                per_course[o.course_id] = per_course.get(o.course_id, 0) + 1
                row.allocated_course_id, row.allocated_course_code, row.choice_number = (
                    o.course_id,
                    courses[o.course_id].code,
                    n,
                )
                row.status = "allocated"
                summary.allocated += 1
            else:
                summary.unallocated += 1
            summary.results.append(row)
            if not dry_run and e is not None:
                f.allocation_run_id = run.id if run else None
                if placed:
                    o, _ = placed
                    f.status, f.allocated_course_id = "allocated", o.course_id
                    record = (
                        await self.db.execute(
                            select(StudentTermRecord).where(
                                StudentTermRecord.student_program_enrollment_id == e.id,
                                StudentTermRecord.term_id == term.id,
                            )
                        )
                    ).scalar_one_or_none()
                    if record is not None:
                        reg = await self._cart(e, term, record, None)
                        if reg.status in ("draft", "changes_requested", "rejected", "approved"):
                            locked = await self.offerings.get_one(o.id, for_update=True)
                            try:
                                await self._add(
                                    reg,
                                    e,
                                    record,
                                    locked,
                                    "regular",
                                    None,
                                    window=None,
                                    status_when_seated="confirmed" if auto_confirm else "selected",
                                    check_rules=False,
                                    allow_waitlist=False,
                                )
                            except APIError:
                                f.status, f.allocated_course_id = "manual", None
                                row.status = "manual"
                else:
                    f.status = "manual"
                await self._notify(
                    "elective.allocated",
                    [s.user_id if s else None],
                    {
                        "basket": basket.name,
                        "result": f"allocated {row.allocated_course_code}"
                        if placed
                        else "no seat was free in your choices — the registrar will assign you manually",
                    },
                )
            if progress and rank % 20 == 0:
                await progress(int(100 * rank / max(1, len(forms))), f"{rank}/{len(forms)}")
        summary.per_course = [
            {
                "course_id": str(cid),
                "code": courses[cid].code,
                "allocated": per_course.get(cid, 0),
                "seats": sum((o.max_seats or 0) for o in offs if o.course_id == cid),
            }
            for cid in basket_courses
            if cid in courses
        ]
        if run is not None:
            run.summary = summary.model_dump(mode="json", exclude={"results"})
            summary.run_at = run.run_at
            await self.db.flush()
            await self._emit(
                "elective.allocated",
                {"run_id": str(run.id), "basket_id": str(basket.id), "allocated": summary.allocated},
                "elective_allocation_run",
                run.id,
            )
            await self._audit("allocate", "elective_allocation_run", run.id, None, run.summary)
        return summary

    async def enqueue_allocate(
        self, basket_id: uuid.UUID, term_id: uuid.UUID, mode: str | None, seed: int | None
    ) -> uuid.UUID:
        from app.core.jobs import enqueue

        await self._basket(basket_id)
        job = await enqueue(
            self.db,
            self.principal,
            "elective.allocate",
            {"basket_id": str(basket_id), "term_id": str(term_id), "mode": mode, "seed": seed},
        )
        return job.id

    async def get_run(self, run_id: uuid.UUID) -> dict[str, Any]:
        run = await self.forms.run(run_id)
        forms = await self.forms.for_basket(run.elective_basket_id, run.term_id)
        return {
            "id": str(run.id),
            "basket_id": str(run.elective_basket_id),
            "term_id": str(run.term_id),
            "mode": run.mode,
            "run_at": run.run_at.isoformat(),
            "summary": run.summary,
            "forms": [(await self.form_out(f)).model_dump(mode="json") for f in forms if f.allocation_run_id == run.id],
        }

    async def basket_forms(self, basket_id: uuid.UUID, term_id: uuid.UUID) -> list[ChoiceFormResponse]:
        await self._basket(basket_id)
        out = []
        for f in await self.forms.for_basket(basket_id, term_id):
            r = await self.form_out(f)
            e = (await self.offerings.rows(StudentProgramEnrollment, [f.student_program_enrollment_id])).get(
                f.student_program_enrollment_id
            )
            s = (await self.offerings.rows(Student, [e.student_id])).get(e.student_id) if e else None
            r.student_name, r.registration_number = (s.full_name, s.registration_number) if s else (None, None)
            out.append(r)
        return out

    async def manual_assign(self, basket_id: uuid.UUID, body: ManualAllocation) -> ChoiceFormResponse:
        basket, courses = await self._basket(basket_id)
        if body.course_id not in courses:
            raise APIError(422, ErrorCode.VALIDATION, "Course outside the basket", {"field": "course_id"})
        f = await self.forms.get(body.form_id, for_update=True)
        e = (await self.offerings.rows(StudentProgramEnrollment, [f.student_program_enrollment_id]))[
            f.student_program_enrollment_id
        ]
        term = await self.get_term(f.term_id)
        record = await self.term_record(e.id, term.id)
        reg = await self._cart(e, term, record, None)
        offs = await self.offerings.for_courses(term.id, [body.course_id], statuses=("open",))
        for o in sorted(offs, key=lambda o: o.enrolled_count):
            locked = await self.offerings.get_one(o.id, for_update=True)
            if locked.max_seats is None or locked.enrolled_count < locked.max_seats:
                await self._add(
                    reg, e, record, locked, "regular", None, window=None, check_rules=False, allow_waitlist=False
                )
                f.status, f.allocated_course_id = "allocated", body.course_id
                await self.db.flush()
                await self._audit(
                    "manual_allocate", "elective_choice_form", f.id, None, {"course_id": str(body.course_id)}
                )
                return await self.form_out(f)
        raise rule("No offering of the course has a free seat", "SEATS_FULL")


class ArrearService(RegistrationService):
    async def _out(self, rows: list[StudentArrear]) -> list[ArrearResponse]:
        enrolments = await self.offerings.rows(
            StudentProgramEnrollment, [a.student_program_enrollment_id for a in rows]
        )
        students = await self.offerings.rows(Student, [e.student_id for e in enrolments.values()])
        courses = await self.offerings.rows(Course, [a.course_id for a in rows])
        programs = await self.offerings.rows(Program, [e.program_id for e in enrolments.values()])
        batches = await self.offerings.rows(Batch, [e.batch_id for e in enrolments.values()])
        out = []
        for a in rows:
            e = enrolments.get(a.student_program_enrollment_id)
            s = students.get(e.student_id) if e else None
            c = courses.get(a.course_id)
            out.append(
                ArrearResponse(
                    id=a.id,
                    enrollment_id=a.student_program_enrollment_id,
                    student_id=s.id if s else None,
                    student_name=s.full_name if s else None,
                    registration_number=s.registration_number if s else None,
                    program_code=programs[e.program_id].code if e and e.program_id in programs else None,
                    batch_code=batches[e.batch_id].code if e and e.batch_id in batches else None,
                    course_id=a.course_id,
                    course_code=c.code if c else None,
                    course_title=c.title if c else None,
                    credits=float(credits_of(c)),
                    attempts=a.attempts,
                    status=a.status,
                    first_failed_term_id=a.first_failed_term_id,
                    last_attempt_term_id=a.last_attempt_term_id,
                    updated_at=a.updated_at,
                )
            )
        return out

    async def list_page(  # type: ignore[override]
        self, params: PageParams, scope: str | None, **filters: Any
    ) -> tuple[list[ArrearResponse], PaginationMeta, VisibilityMeta]:
        from app.repositories.registration_scope import registration_visibility

        stmt = self.arrears.filtered(scope=scope, **filters).order_by(StudentArrear.updated_at.desc())
        total_rows = (await self.db.execute(stmt.offset(params.offset).limit(params.page_size))).scalars().all()
        from sqlalchemy import func

        total = (await self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
        page = PaginationMeta(
            page=params.page, page_size=params.page_size, total=total, total_pages=max(1, -(-total // params.page_size))
        )
        return await self._out(list(total_rows)), page, registration_visibility(self.principal)

    async def for_student(self, student_id: uuid.UUID) -> list[ArrearResponse]:
        await self.students.get_visible(student_id)
        ids = [e.id for e in await self.enrollments.for_student(student_id)]
        rows = []
        for i in ids:
            rows += list((await self.db.execute(self.arrears.filtered(enrollment_id=i, visible=False))).scalars())
        return await self._out(rows)

    async def mine_list(self) -> list[ArrearResponse]:
        _, enrolment = await self.me()
        return await self._out(
            list((await self.db.execute(self.arrears.filtered(enrollment_id=enrolment.id, visible=False))).scalars())
        )

    async def waive(self, arrear_id: uuid.UUID, body: WaiveRequest) -> ArrearResponse:
        a = await self.arrears.get(arrear_id, for_update=True)
        if a.status not in ("open", "registered"):
            raise APIError(409, ErrorCode.CONFLICT, f"The arrear is {a.status}")
        old = a.status
        a.status = "waived"
        await self.db.flush()
        course = (await self.offerings.rows(Course, [a.course_id])).get(a.course_id)
        await self._audit("waive", "student_arrear", a.id, {"status": old}, {"status": "waived", "reason": body.reason})
        await self._emit("arrear.waived", {"arrear_id": str(a.id), "reason": body.reason}, "student_arrear", a.id)
        await self._notify(
            "arrear.waived",
            [await self.user_of_enrollment(a.student_program_enrollment_id)],
            {"course": course.code if course else "", "reason": body.reason},
        )
        return (await self._out([a]))[0]

    async def record_result(
        self,
        enrollment_id: uuid.UUID,
        course_id: uuid.UUID,
        term: AcademicTerm,
        passed: bool,
        result_id: uuid.UUID | None = None,
    ) -> StudentArrear | None:
        """Phase 15 publication hook: fail → open (attempts + 1), pass → cleared."""
        a = await self.arrears.for_course(enrollment_id, course_id, for_update=True)
        if passed:
            if a is not None and a.status in ("open", "registered"):
                a.status, a.cleared_result_id, a.last_attempt_term_id = "cleared", result_id, term.id
        elif a is None:
            a = await self.arrears.add(
                StudentArrear(
                    institution_id=self.inst,
                    student_program_enrollment_id=enrollment_id,
                    course_id=course_id,
                    first_failed_term_id=term.id,
                    last_attempt_term_id=term.id,
                    attempts=1,
                    status="open",
                )
            )
        else:
            a.status, a.attempts, a.last_attempt_term_id = "open", a.attempts + 1, term.id
        await self.db.flush()
        return a
