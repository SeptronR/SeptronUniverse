"""Course registration — Prompts/09 §09.6 ``registration_service.py`` (+ ``waitlist_service`` rules).

1. ``catalog``: the open window matching the enrolment (else 409 ``WINDOW_CLOSED``), limits from the structure term
   (window / override max), curriculum courses with their (targeted) offerings, baskets with the choice-form status,
   open arrears, holds (reported, not raised), pending undertakings and the fee preview.
2. ``add_item`` (offering row locked): open offering, course of the enrolment's regulation (or basket / minor /
   honours / MOOC), audit only with ``registration.audit_courses``, arrear attempt numbers, duplicates, hard
   prerequisites (409 ``PREREQUISITE_NOT_MET``), antirequisites (409 ``ANTIREQUISITE``), credit projection (409
   ``CREDIT_LIMIT``), seats → ``selected`` or ``waitlisted`` (``registration.waitlist``) or 409 ``SEATS_FULL``.
3. ``remove_item``: editable carts (and an approved one while a window is open); ``locked`` → 409 ``RECORD_LOCKED``;
   the released seat is offered to the first waitlisted student.
4. ``submit`` (Idempotency-Key at the route): co-requisites, credit min/max, holds (``assert_clear``), undertakings,
   arrear window rule, the fee order (mock until Phase 12), then ``registration.advisor`` (class advisor of the
   section, fallback HOD) → ``advisor_pending``, or approved directly.
5. Workflow hooks: approved → items confirmed, term record ``registered`` + ``credits_registered``, student
   ``provisional|admitted → active`` (Phase 07 ``apply_status``), arrears ``registered``; rejected / changes requested
   → back to an editable status with the advisor's comment.
6. Lock at the add-drop end (Beat ``registration.lock_windows``): the latest ``add_drop`` window end of the term, else
   ``academic_terms.add_drop_end``; registrar ``withdraw`` afterwards (``W``).
7. Overrides, 8. bulk registration (job), waitlist accept / expiry (Beat ``waitlist.expire``).
"""

import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.workflow import engine as workflow_engine
from app.enums.registration import EDITABLE_REGISTRATION, LIVE_ITEMS, PENDING_REGISTRATION
from app.models.academic import AcademicTerm, BatchSection
from app.models.curriculum import Course, CurriculumCourse, ElectiveBasket, ElectiveBasketCourse
from app.models.hr import Staff
from app.models.offerings import CourseOffering
from app.models.platform import WorkflowInstance, WorkflowStep
from app.models.registration import CourseRegistration, CourseRegistrationItem, OfferingWaitlist, RegistrationWindow
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.schemas.registration import (
    AdvisorDecision,
    BulkRegisterRequest,
    BulkRegisterResult,
    CartItemAdd,
    CatalogArrear,
    CatalogBasket,
    CatalogCourse,
    CatalogOffering,
    CatalogResponse,
    ChoiceFormResponse,
    FeePreview,
    HoldBrief,
    OverrideRequest,
    RegistrationListItem,
    RegistrationResponse,
    RequisiteHint,
    SubmitResponse,
    WaitlistResponse,
)
from app.services.registration.common import REG, RegistrationBase, credits_of, rule, utcnow
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

ADVISOR_KEY = "registration.advisor"
FREE_TYPES = {"minor", "honours", "mooc"}


class RegistrationService(RegistrationBase):
    # ---- lookups ------------------------------------------------------------------------------------------------------
    async def _context(
        self, term_id: uuid.UUID | None
    ) -> tuple[Student, StudentProgramEnrollment, AcademicTerm, StudentTermRecord]:
        student, enrolment = await self.me()
        term = await self.get_term(term_id, enrolment.college_id)
        return student, enrolment, term, await self.term_record(enrolment.id, term.id)

    async def _window(
        self,
        term: AcademicTerm,
        enrolment: StudentProgramEnrollment,
        record: StudentTermRecord,
        *,
        required: bool = True,
    ) -> RegistrationWindow | None:
        open_ = await self.open_windows(term.id, enrolment, record)
        if not open_ and required:
            raise rule("No registration window is open for you in this term", "WINDOW_CLOSED", term_id=str(term.id))
        return open_[0] if open_ else None

    async def _cart(
        self,
        enrolment: StudentProgramEnrollment,
        term: AcademicTerm,
        record: StudentTermRecord,
        window: RegistrationWindow | None,
    ) -> CourseRegistration:
        reg = await self.regs.for_enrollment(enrolment.id, term.id, for_update=True)
        if reg is None:
            reg = await self.regs.add(
                CourseRegistration(
                    institution_id=self.inst,
                    college_id=enrolment.college_id,
                    student_program_enrollment_id=enrolment.id,
                    term_id=term.id,
                    student_term_record_id=record.id,
                    window_id=window.id if window else None,
                    status="draft",
                )
            )
        return reg

    async def _one(self, reg: CourseRegistration) -> RegistrationResponse:
        return (await self.registration_responses([reg]))[0]

    # ---- rule 1: catalog ----------------------------------------------------------------------------------------------
    async def catalog(self, term_id: uuid.UUID | None) -> CatalogResponse:
        student, enrolment, term, record = await self._context(term_id)
        window = await self._window(term, enrolment, record)
        windows = await self.open_windows(term.id, enrolment, record)
        reg = await self.regs.for_enrollment(enrolment.id, term.id)
        overrides = await self.overrides(reg.id) if reg else {}
        limits = await self.limits(enrolment, record, window, overrides)
        st = await self.structure_term(enrolment.program_regulation_id, record.term_number)
        items = (await self.regs.items([reg.id])).get(reg.id, []) if reg else []
        in_cart = {i.course_id: i.status for i in items if i.status in LIVE_ITEMS}
        targeted = await self.offerings.targeted_at(term.id, enrolment.batch_id, record.section_id)
        passed = await self.passed_course_ids(enrolment, record)

        ccs = list(
            (
                await self.db.execute(
                    select(CurriculumCourse).where(
                        CurriculumCourse.program_regulation_id == enrolment.program_regulation_id,
                        CurriculumCourse.term_number == record.term_number,
                    )
                )
            ).scalars()
        )
        basket_rows = list(
            (
                await self.db.execute(
                    select(ElectiveBasket).where(
                        ElectiveBasket.program_regulation_id == enrolment.program_regulation_id,
                        ElectiveBasket.term_number == record.term_number,
                        ElectiveBasket.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        basket_courses = (
            list(
                (
                    await self.db.execute(
                        select(ElectiveBasketCourse).where(
                            ElectiveBasketCourse.basket_id.in_([b.id for b in basket_rows])
                        )
                    )
                ).scalars()
            )
            if basket_rows
            else []
        )
        arrears = await self.arrears.open_for(enrolment.id, ("open", "registered"))
        course_ids = (
            {cc.course_id for cc in ccs} | {bc.course_id for bc in basket_courses} | {a.course_id for a in arrears}
        )
        courses = await self.offerings.rows(Course, list(course_ids))
        offs = await self.offerings.for_courses(term.id, list(course_ids), statuses=("open",))
        fac = await self.offerings.faculty([o.id for o in offs])
        staff = await self.offerings.rows(Staff, [f.staff_id for fs in fac.values() for f in fs])
        rels = await self.relations(list(course_ids))
        rel_codes = await self.offerings.rows(Course, [r.related_course_id for r in rels] + [r.course_id for r in rels])

        def offering_briefs(course_id: uuid.UUID, arrear: bool = False) -> list[CatalogOffering]:
            mine = [o for o in offs if o.course_id == course_id and (arrear or not o.is_arrear_only)]
            tgt = [o for o in mine if o.id in targeted]
            chosen = tgt or [o for o in mine if o.college_id == enrolment.college_id] or mine
            return [
                CatalogOffering(
                    offering_id=o.id,
                    section_code=o.section_code,
                    faculty=[staff[f.staff_id].full_name for f in fac.get(o.id, []) if f.staff_id in staff],
                    max_seats=o.max_seats,
                    enrolled_count=o.enrolled_count,
                    waitlist_count=o.waitlist_count,
                    seats_left=None if o.max_seats is None else max(0, o.max_seats - o.enrolled_count),
                    targeted=o.id in targeted,
                    status=o.status,
                    is_arrear_only=o.is_arrear_only,
                )
                for o in chosen
            ]

        def course_entry(
            course_id: uuid.UUID, mandatory: bool, basket_id: uuid.UUID | None = None
        ) -> CatalogCourse | None:
            c = courses.get(course_id)
            if c is None:
                return None
            hints = []
            for r in rels:
                if r.course_id == c.id and r.relation in ("prerequisite", "corequisite"):
                    other = r.related_course_id
                elif r.relation == "antirequisite" and c.id in (r.course_id, r.related_course_id):
                    other = r.related_course_id if r.course_id == c.id else r.course_id
                else:
                    continue
                met = (
                    other in passed
                    if r.relation == "prerequisite"
                    else (
                        other not in passed and other not in in_cart
                        if r.relation == "antirequisite"
                        else other in in_cart or other in passed
                    )
                )
                hints.append(
                    RequisiteHint(
                        relation=r.relation,
                        course_id=other,
                        course_code=rel_codes[other].code if other in rel_codes else None,
                        met=met,
                        is_hard=r.is_hard,
                    )
                )
            return CatalogCourse(
                course_id=c.id,
                code=c.code,
                title=c.title,
                credits=float(credits_of(c)),
                course_type=c.course_type,
                mandatory=mandatory,
                basket_id=basket_id,
                requisites=hints,
                prerequisites_met=all(h.met for h in hints if h.relation == "prerequisite" and h.is_hard),
                offerings=offering_briefs(c.id),
                in_cart=in_cart.get(c.id),
            )

        curriculum = [
            e
            for cc in sorted(ccs, key=lambda x: x.sequence)
            if cc.elective_basket_id is None and (e := course_entry(cc.course_id, cc.is_mandatory)) is not None
        ]
        forms = {f.elective_basket_id: f for f in await self.forms.for_enrollment(enrolment.id, term.id)}
        baskets = []
        for b in basket_rows:
            f = forms.get(b.id)
            baskets.append(
                CatalogBasket(
                    basket_id=b.id,
                    code=b.code,
                    name=b.name,
                    basket_type=b.basket_type,
                    min_choose=b.min_choose,
                    max_choose=b.max_choose,
                    allocation_mode=b.allocation_mode,
                    courses=[
                        e
                        for bc in basket_courses
                        if bc.basket_id == b.id and (e := course_entry(bc.course_id, False, b.id)) is not None
                    ],
                    choice_form=await self.form_out(f) if f else None,
                )
            )
        arrear_out = []
        for a in arrears:
            c = courses.get(a.course_id)
            if c is None:
                continue
            arrear_out.append(
                CatalogArrear(
                    arrear_id=a.id,
                    course_id=c.id,
                    code=c.code,
                    title=c.title,
                    credits=float(credits_of(c)),
                    attempts=a.attempts,
                    status=a.status,
                    offerings=offering_briefs(c.id, arrear=True),
                    in_cart=in_cart.get(c.id),
                )
            )
        holds = await self.holds.open_holds(enrolment.id, "registration")
        pending: list[str] = []
        try:
            from app.services.student_records_service import StudentRecordsService

            await StudentRecordsService(self.db, self.principal, self.request).assert_undertakings(
                student, "registration"
            )
        except APIError as exc:
            pending = list(exc.details.get("pending", []))
        arrear_credits = sum(
            (
                credits_of(courses.get(i.course_id))
                for i in items
                if i.registration_type == "arrear" and i.status in LIVE_ITEMS
            ),
            Decimal(0),
        )
        return CatalogResponse(
            term={"id": str(term.id), "name": term.name, "status": term.status},
            structure_term={"term_number": record.term_number, "name": st.name if st else None},
            limits=limits,
            window=self.window_out(window, term.name) if window else None,
            windows=[self.window_out(w, term.name) for w in windows],
            curriculum=curriculum,
            baskets=baskets,
            arrears=arrear_out,
            holds=sorted({h.hold_type for h in holds}),
            hold_details=[HoldBrief(id=h.id, hold_type=h.hold_type, reason=h.reason) for h in holds],
            undertakings_pending=pending,
            fee_preview=await self._fee_preview(window, arrear_credits),
            registration_id=reg.id if reg else None,
            registration_status=reg.status if reg else None,
            audit_courses_enabled=await is_enabled(self.inst, "registration.audit_courses"),
        )

    async def _fee_preview(self, window: RegistrationWindow | None, arrear_credits: Decimal) -> FeePreview:
        reg_fee = int(await self.reg_setting("fee_paise", 0))
        arrear = int(Decimal(str(await self.reg_setting("arrear_fee_per_credit_paise", 50000))) * arrear_credits)
        late = window.late_fee_paise if window is not None and window.window_type == "late" else 0
        return FeePreview(
            registration_fee_paise=reg_fee,
            arrear_fee_paise=arrear,
            late_fee_paise=late,
            total_paise=reg_fee + arrear + late,
            note="Tuition is billed by the fee structure (Phase 12); this preview covers registration charges only.",
        )

    async def form_out(self, f: Any) -> ChoiceFormResponse:
        ids = [uuid.UUID(str(c["course_id"])) for c in f.choices or []]
        if f.allocated_course_id:
            ids.append(f.allocated_course_id)
        courses = await self.offerings.rows(Course, ids)
        choices = []
        for c in sorted(f.choices or [], key=lambda x: x.get("priority", 99)):
            cid = uuid.UUID(str(c["course_id"]))
            co = courses.get(cid)
            choices.append(
                {
                    "course_id": str(cid),
                    "code": co.code if co else None,
                    "title": co.title if co else None,
                    "priority": c.get("priority"),
                }
            )
        alloc = courses.get(f.allocated_course_id) if f.allocated_course_id else None
        return ChoiceFormResponse(
            id=f.id,
            enrollment_id=f.student_program_enrollment_id,
            basket_id=f.elective_basket_id,
            term_id=f.term_id,
            choices=choices,
            status=f.status,
            allocated_course_id=f.allocated_course_id,
            allocated_course_code=alloc.code if alloc else None,
            allocation_run_id=f.allocation_run_id,
            submitted_at=f.submitted_at,
        )

    # ---- self: read ---------------------------------------------------------------------------------------------------
    async def mine(self, term_id: uuid.UUID | None) -> RegistrationResponse | None:
        _, enrolment = await self.me()
        term = await self.get_term(term_id, enrolment.college_id)
        reg = await self.regs.for_enrollment(enrolment.id, term.id)
        return await self._one(reg) if reg else None

    async def history_me(self) -> list[RegistrationResponse]:
        student, _ = await self.me()
        return await self.history(student.id, visible=False)

    async def history(self, student_id: uuid.UUID, *, visible: bool = True) -> list[RegistrationResponse]:
        if visible:
            await self.students.get_visible(student_id)
        enrolments = await self.enrollments.for_student(student_id)
        rows = await self.regs.history([e.id for e in enrolments])
        ward = visible and student_id in await self.ward_ids()
        return await self.registration_responses(rows, confirmed_only=ward)

    # ---- rule 2: add ----------------------------------------------------------------------------------------------------
    async def add_item(self, body: CartItemAdd) -> RegistrationResponse:
        student, enrolment = await self.me()
        offering = await self.offerings.get_one(body.offering_id, for_update=True)
        term = await self.get_term(offering.term_id)
        record = await self.term_record(enrolment.id, term.id)
        window = await self._window(term, enrolment, record)
        reg = await self._cart(enrolment, term, record, window)
        await self._assert_editable(reg, term, enrolment, record)
        item = await self._add(
            reg, enrolment, record, offering, body.registration_type.value, body.priority, window=window
        )
        await self._audit(
            "add_item",
            REG,
            reg.id,
            None,
            {"offering_id": str(offering.id), "status": item.status, "type": item.registration_type},
        )
        return await self._one(reg)

    async def _assert_editable(
        self,
        reg: CourseRegistration,
        term: AcademicTerm,
        enrolment: StudentProgramEnrollment,
        record: StudentTermRecord,
    ) -> None:
        if reg.status == "locked":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Registration is locked (add/drop has ended)")
        if reg.status in ("submitted", "advisor_pending"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Registration is awaiting approval")
        if reg.status == "approved":
            if not await is_enabled(self.inst, "registration.add_drop") or not await self.open_windows(
                term.id, enrolment, record
            ):
                raise APIError(
                    409, ErrorCode.RECORD_LOCKED, "Registration is approved — changes need an open add/drop window"
                )

    async def _add(
        self,
        reg: CourseRegistration,
        enrolment: StudentProgramEnrollment,
        record: StudentTermRecord,
        offering: CourseOffering,
        reg_type: str,
        priority: int | None,
        *,
        window: RegistrationWindow | None,
        status_when_seated: str = "selected",
        check_rules: bool = True,
        allow_waitlist: bool = True,
    ) -> CourseRegistrationItem:
        if offering.status != "open":
            raise rule("This offering is not open for registration", "OFFERING_NOT_OPEN", status=offering.status)
        course = (await self.offerings.rows(Course, [offering.course_id]))[offering.course_id]
        pr = await self.program_regulation(enrolment.program_regulation_id)
        items = (await self.regs.items([reg.id])).get(reg.id, [])
        live = [i for i in items if i.status in LIVE_ITEMS]
        if any(i.course_id == course.id for i in live):
            raise APIError(
                409, ErrorCode.CONFLICT, f"{course.code} is already in the cart", {"code": "DUPLICATE_COURSE"}
            )
        arrear = await self.arrears.for_course(enrolment.id, course.id)
        if arrear is not None and arrear.status in ("open", "registered") and reg_type == "regular":
            reg_type = "arrear"
        if reg_type == "arrear" and (arrear is None or arrear.status not in ("open", "registered")):
            raise rule(f"No open arrear in {course.code}", "NO_ARREAR")
        if offering.is_arrear_only and reg_type != "arrear":
            raise rule("This offering is for arrear registration only", "ARREAR_ONLY")
        if reg_type == "audit" and not await is_enabled(self.inst, "registration.audit_courses"):
            raise APIError(
                403, ErrorCode.FEATURE_DISABLED, "Audit courses are disabled", {"feature": "registration.audit_courses"}
            )
        if check_rules:
            in_basket = (
                await self.db.execute(
                    select(ElectiveBasketCourse.id)
                    .join(ElectiveBasket, ElectiveBasket.id == ElectiveBasketCourse.basket_id)
                    .where(
                        ElectiveBasketCourse.course_id == course.id,
                        ElectiveBasket.program_regulation_id == enrolment.program_regulation_id,
                    )
                )
            ).first()
            if (
                pr is not None
                and course.regulation_id != pr.regulation_id
                and in_basket is None
                and reg_type not in FREE_TYPES
            ):
                raise rule(f"{course.code} is not part of your regulation", "COURSE_NOT_IN_REGULATION")
            overrides = await self.overrides(reg.id)
            skip = {str(s) for s in overrides.get("skip_prerequisites", [])}
            bypass = bool(await self.reg_setting("prerequisite_bypass", False))
            rels = await self.relations([course.id])
            passed = await self.passed_course_ids(enrolment, record)
            missing = [
                r.related_course_id
                for r in rels
                if r.course_id == course.id
                and r.relation == "prerequisite"
                and r.is_hard
                and r.related_course_id not in passed
                and str(r.related_course_id) not in skip
            ]
            if missing and not bypass:
                codes = await self.offerings.rows(Course, missing)
                raise rule(
                    f"Prerequisite not met for {course.code}: {', '.join(c.code for c in codes.values())}",
                    "PREREQUISITE_NOT_MET",
                    course=course.code,
                    missing=[c.code for c in codes.values()],
                )
            live_ids = {i.course_id for i in live}
            for r in rels:
                if r.relation != "antirequisite" or course.id not in (r.course_id, r.related_course_id):
                    continue
                other = r.related_course_id if r.course_id == course.id else r.course_id
                if other in passed or other in live_ids:
                    oc = (await self.offerings.rows(Course, [other])).get(other)
                    raise rule(
                        f"{course.code} cannot be taken with {oc.code if oc else other}",
                        "ANTIREQUISITE",
                        course=course.code,
                        conflicts_with=oc.code if oc else str(other),
                    )
            limits = await self.limits(enrolment, record, window, overrides)
            courses = await self.offerings.rows(Course, [i.course_id for i in live])
            projected = sum((credits_of(courses.get(i.course_id)) for i in live if i.is_credit_bearing), Decimal(0)) + (
                credits_of(course) if reg_type != "audit" else Decimal(0)
            )
            if float(projected) > limits.max:
                raise rule(
                    f"Adding {course.code} exceeds the maximum of {limits.max:g} credits",
                    "CREDIT_LIMIT",
                    projected=float(projected),
                    max=limits.max,
                )
        item = await self.regs.item_for_offering(reg.id, offering.id)
        seated = await self.take_seat(offering)
        if not seated:
            if not allow_waitlist or not await is_enabled(self.inst, "registration.waitlist"):
                raise rule(f"{course.code} section {offering.section_code} is full", "SEATS_FULL")
        status = status_when_seated if seated else "waitlisted"
        values = {
            "course_id": course.id,
            "registration_type": reg_type,
            "attempt_number": (arrear.attempts + 1) if reg_type == "arrear" and arrear else 1,
            "priority": priority,
            "status": status,
            "is_credit_bearing": reg_type != "audit" and course.is_credit_bearing,
            "added_at": utcnow(),
            "dropped_at": None,
            "drop_reason": None,
        }
        if item is None:
            item = await self.regs.add_item(
                CourseRegistrationItem(
                    institution_id=self.inst, registration_id=reg.id, offering_id=offering.id, **values
                )
            )
        else:
            for k, v in values.items():
                setattr(item, k, v)
        if not seated:
            wl = await self.waitlists.for_student(offering.id, enrolment.id)
            if wl is None:
                await self.waitlists.add(
                    OfferingWaitlist(
                        institution_id=self.inst,
                        offering_id=offering.id,
                        student_program_enrollment_id=enrolment.id,
                        position=await self.waitlists.next_position(offering.id),
                        status="waiting",
                    )
                )
            else:
                wl.status, wl.position, wl.offered_until = (
                    "waiting",
                    await self.waitlists.next_position(offering.id),
                    None,
                )
            offering.waitlist_count += 1
        await self.db.flush()
        await self.recompute_total(reg)
        return item

    # ---- rule 3: remove ---------------------------------------------------------------------------------------------------
    async def remove_item(self, item_id: uuid.UUID) -> RegistrationResponse:
        _, enrolment = await self.me()
        item = await self.regs.item(item_id, for_update=True)
        reg = await self.regs.by_id(item.registration_id, for_update=True)
        if reg is None or reg.student_program_enrollment_id != enrolment.id:
            raise APIError(404, ErrorCode.NOT_FOUND, "Registration item not found")
        term = await self.get_term(reg.term_id)
        record = await self.term_record(enrolment.id, term.id)
        await self._assert_editable(reg, term, enrolment, record)
        await self._drop(reg, item, "dropped by the student", status="dropped")
        return await self._one(reg)

    async def _drop(self, reg: CourseRegistration, item: CourseRegistrationItem, reason: str, *, status: str) -> None:
        if item.status not in LIVE_ITEMS:
            raise APIError(409, ErrorCode.CONFLICT, f"The item is already {item.status}")
        previous = item.status
        item.status, item.dropped_at, item.drop_reason = status, utcnow(), reason
        await self.db.flush()
        if previous == "waitlisted":
            offering = await self.offerings.get_one(item.offering_id, for_update=True)
            wl = await self.waitlists.for_student(item.offering_id, reg.student_program_enrollment_id)
            if wl is not None and wl.status == "offered":
                wl.status = "cancelled"
                offering.enrolled_count = max(0, offering.enrolled_count - 1)
                await self.db.flush()
                await self.promote_next(offering)
            elif wl is not None:
                wl.status = "cancelled"
                offering.waitlist_count = max(0, offering.waitlist_count - 1)
        else:
            await self.release_seat(item.offering_id)
        await self.recompute_total(reg)
        await self._emit(
            "registration.item_dropped",
            {
                "registration_id": str(reg.id),
                "item_id": str(item.id),
                "offering_id": str(item.offering_id),
                "status": status,
            },
            REG,
            reg.id,
        )

    # ---- rule 4: submit ---------------------------------------------------------------------------------------------------
    async def submit(self, term_id: uuid.UUID | None) -> SubmitResponse:
        student, enrolment, term, record = await self._context(term_id)
        reg = await self.regs.for_enrollment(enrolment.id, term.id, for_update=True)
        if reg is None:
            raise rule("Your cart is empty", "EMPTY_CART")
        if reg.status not in EDITABLE_REGISTRATION:
            raise APIError(409, ErrorCode.CONFLICT, f"The registration is already {reg.status}")
        items = (await self.regs.items([reg.id])).get(reg.id, [])
        live = [i for i in items if i.status in LIVE_ITEMS]
        if not live:
            raise rule("Your cart is empty", "EMPTY_CART")
        windows = await self.open_windows(term.id, enrolment, record)
        if not windows:
            raise rule("No registration window is open for you in this term", "WINDOW_CLOSED")
        has_arrear = any(i.registration_type == "arrear" for i in live)
        arrear_window = next((w for w in windows if w.window_type == "arrear"), None)
        if (
            has_arrear
            and arrear_window is None
            and not bool(await self.reg_setting("allow_arrear_with_regular", False))
        ):
            raise rule("Arrear courses need an open arrear registration window", "ARREAR_WINDOW_REQUIRED")
        window = arrear_window if has_arrear and arrear_window else windows[0]
        overrides = await self.overrides(reg.id)
        # co-requisites
        courses = await self.offerings.rows(Course, [i.course_id for i in live])
        passed = await self.passed_course_ids(enrolment, record)
        live_ids = {i.course_id for i in live}
        pairs = []
        for r in await self.relations(list(live_ids)):
            if (
                r.relation == "corequisite"
                and r.course_id in live_ids
                and r.related_course_id not in live_ids
                and r.related_course_id not in passed
            ):
                other = (await self.offerings.rows(Course, [r.related_course_id])).get(r.related_course_id)
                pairs.append(
                    {"course": courses[r.course_id].code, "requires": other.code if other else str(r.related_course_id)}
                )
        if pairs:
            raise rule(
                "Co-requisites missing: " + ", ".join(f"{p['course']} needs {p['requires']}" for p in pairs),
                "COREQUISITE_MISSING",
                pairs=pairs,
            )
        limits = await self.limits(enrolment, record, window, overrides)
        total = await self.recompute_total(reg)
        if not (limits.min <= float(total) <= limits.max):
            raise rule(
                f"Registered credits {float(total):g} must be between {limits.min:g} and {limits.max:g}",
                "CREDIT_LIMIT",
                total=float(total),
                min=limits.min,
                max=limits.max,
            )
        if not overrides.get("skip_holds"):
            from app.services.hold_service import HoldService

            await HoldService(self.db, self.principal, self.request, self.inst).assert_clear(
                enrolment.id, "registration"
            )
        from app.services.student_records_service import StudentRecordsService

        await StudentRecordsService(self.db, self.principal, self.request).assert_undertakings(student, "registration")
        warnings = []
        if window.requires_fee_clearance:
            warnings.append("Fee clearance is checked from Phase 12 (fee invoices) — not enforced yet")
        arrear_credits = sum(
            (credits_of(courses.get(i.course_id)) for i in live if i.registration_type == "arrear"), Decimal(0)
        )
        preview = await self._fee_preview(window, arrear_credits)
        await self._audit(
            "fee_order",
            REG,
            reg.id,
            None,
            {
                "ref": f"REG-{str(reg.id)[:8].upper()}-{int(utcnow().timestamp())}",
                "amount_paise": preview.total_paise,
                "status": "pending" if preview.total_paise else "not_required",
                "provider": "mock",
                "breakdown": {
                    "registration": preview.registration_fee_paise,
                    "arrear": preview.arrear_fee_paise,
                    "late": preview.late_fee_paise,
                },
            },
        )
        reg.status, reg.submitted_at, reg.window_id = "submitted", utcnow(), window.id
        await self.db.flush()
        await self._audit("submit", REG, reg.id, None, {"credits": float(total), "window": window.name})
        if window.requires_advisor_approval and await is_enabled(self.inst, "registration.advisor_approval"):
            await self._start_workflow(reg, enrolment, record, student)
            reg.status = "advisor_pending"
        else:
            await self.apply_approval(reg, None)
        await self.db.flush()
        await self._emit(
            "registration.submitted",
            {"registration_id": str(reg.id), "status": reg.status, "credits": float(total), "term_id": str(term.id)},
            REG,
            reg.id,
        )
        await self._notify(
            "registration.submitted",
            [student.user_id],
            {"term": term.name, "credits": f"{float(total):g}", "status": reg.status},
        )
        out = SubmitResponse(**(await self._one(reg)).model_dump(), warnings=warnings)
        return out

    async def _advisor_user(self, record: StudentTermRecord, enrolment: StudentProgramEnrollment) -> uuid.UUID | None:
        """Class advisor of the term record's section (staff row holder or ``class_advisor`` @offering), else HOD."""
        if record.section_id:
            section = (await self.offerings.rows(BatchSection, [record.section_id])).get(record.section_id)
            if section and section.class_advisor_staff_id:
                s = (await self.offerings.rows(Staff, [section.class_advisor_staff_id])).get(
                    section.class_advisor_staff_id
                )
                if s and s.user_id:
                    return s.user_id
            users = await workflow_engine._role_holders(  # noqa: SLF001
                self.db, self.inst, "class_advisor", {"offering_id": str(record.section_id)}
            )
            if users:
                return users[0]
        users = await workflow_engine._role_holders(  # noqa: SLF001
            self.db, self.inst, "hod", {"department_id": str(enrolment.department_id)}
        )
        return users[0] if users else None

    async def _start_workflow(
        self, reg: CourseRegistration, enrolment: StudentProgramEnrollment, record: StudentTermRecord, student: Student
    ) -> None:
        context = {
            "department_id": str(enrolment.department_id),
            "college_id": str(enrolment.college_id),
            "offering_id": str(record.section_id) if record.section_id else None,
            "registration_id": str(reg.id),
        }
        approver = await self._advisor_user(record, enrolment)
        instance = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=ADVISOR_KEY,
            entity_type=REG,
            entity_id=reg.id,
            started_by=self.actor_id,
            context=context,
            title=f"Course registration · {student.registration_number}",
        )
        if approver is not None:
            steps = (
                (
                    await self.db.execute(
                        select(WorkflowStep).where(
                            WorkflowStep.instance_id == instance.id, WorkflowStep.status == "pending"
                        )
                    )
                )
                .scalars()
                .all()
            )
            if steps and all(s.approver_user_id != approver for s in steps):
                steps[0].approver_user_id = approver
                for extra in steps[1:]:
                    extra.status = "skipped"
        reg.workflow_instance_id = instance.id
        await self.db.flush()

    # ---- rule 5: advisor decisions & hooks ----------------------------------------------------------------------------------
    async def decide(self, registration_id: uuid.UUID, body: AdvisorDecision) -> RegistrationResponse:
        reg = await self.regs.get_visible(registration_id, for_update=True)
        if reg.status != "advisor_pending" or reg.workflow_instance_id is None:
            raise APIError(409, ErrorCode.CONFLICT, f"The registration is {reg.status}, not awaiting the advisor")
        items = {i.id: i for i in (await self.regs.items([reg.id])).get(reg.id, [])}
        for d in body.item_decisions:
            if d.decision == "drop":
                item = items.get(d.item_id)
                if item is None:
                    raise APIError(422, ErrorCode.VALIDATION, "Unknown item", {"item_id": str(d.item_id)})
                await self._drop(reg, item, f"dropped by the advisor: {body.comment or ''}".strip(), status="dropped")
        decision = body.decision.value
        await self._audit(
            "advisor_decision", REG, reg.id, {"status": reg.status}, {"decision": decision, "comment": body.comment}
        )
        await workflow_engine.act(
            self.db,
            instance_id=reg.workflow_instance_id,
            actor=self.principal,
            decision="approve" if decision == "approve" else "reject",
            comment=body.comment,
        )
        await self.db.refresh(reg)
        if decision == "request_changes" and reg.status == "rejected":
            reg.status = "changes_requested"
            await self.db.flush()
        return await self._one(reg)

    async def apply_approval(self, reg: CourseRegistration, actor_id: uuid.UUID | None) -> None:
        reg.status, reg.approved_by, reg.approved_at = "approved", actor_id, utcnow()
        items = (await self.regs.items([reg.id])).get(reg.id, [])
        for i in items:
            if i.status == "selected":
                i.status = "confirmed"
        total = await self.recompute_total(reg)
        record = (await self.offerings.rows(StudentTermRecord, [reg.student_term_record_id]))[
            reg.student_term_record_id
        ]
        if record.status in ("pending_registration", "in_progress", "registered"):
            record.status = "registered"
        record.credits_registered = total
        enrolment = (await self.offerings.rows(StudentProgramEnrollment, [reg.student_program_enrollment_id]))[
            reg.student_program_enrollment_id
        ]
        for i in items:
            if i.registration_type == "arrear" and i.status == "confirmed":
                a = await self.arrears.for_course(enrolment.id, i.course_id, for_update=True)
                if a is not None and a.status == "open":
                    a.status, a.last_attempt_term_id = "registered", reg.term_id
                    await self._emit("arrear.registered", {"arrear_id": str(a.id)}, "student_arrear", a.id)
        student = (await self.offerings.rows(Student, [enrolment.student_id]))[enrolment.student_id]
        if student.status in ("provisional", "admitted"):
            from app.services.student_service import StudentService

            await StudentService(self.db, self.principal, self.request, self.inst).apply_status(
                student, "active", "first confirmed course registration"
            )
        await self.db.flush()
        term = (await self.offerings.rows(AcademicTerm, [reg.term_id]))[reg.term_id]
        await self._emit(
            "registration.approved",
            {
                "registration_id": str(reg.id),
                "enrollment_id": str(enrolment.id),
                "term_id": str(reg.term_id),
                "offering_ids": [str(i.offering_id) for i in items if i.status == "confirmed"],
            },
            REG,
            reg.id,
        )
        await self._notify("registration.approved", [student.user_id], {"term": term.name})

    async def on_rejected(self, reg: CourseRegistration) -> None:
        reg.status, reg.workflow_instance_id = "rejected", reg.workflow_instance_id
        await self.db.flush()
        student_user = await self.user_of_enrollment(reg.student_program_enrollment_id)
        term = (await self.offerings.rows(AcademicTerm, [reg.term_id]))[reg.term_id]
        comment = await self.advisor_comment(reg.id) or ""
        await self._emit("registration.rejected", {"registration_id": str(reg.id)}, REG, reg.id)
        await self._notify(
            "registration.rejected", [student_user], {"term": term.name, "decision": "returned", "comment": comment}
        )

    # ---- lists ---------------------------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None, **filters: Any
    ) -> tuple[list[RegistrationListItem], PaginationMeta, VisibilityMeta]:
        from app.repositories.registration_scope import registration_visibility

        stmt = self.regs.filtered(scope=scope, **filters)
        if not params.sort:
            stmt = stmt.order_by(
                CourseRegistration.submitted_at.desc().nulls_last(), CourseRegistration.created_at.desc()
            )
        rows, page = await self.regs.paginate(stmt, params)
        return await self.reg_list_items(rows), page, registration_visibility(self.principal)

    async def get(self, registration_id: uuid.UUID) -> RegistrationResponse:
        reg = await self.regs.get_visible(registration_id)
        ward = False
        if not self.can("registration", "view_all"):
            from app.repositories.registration_scope import ward_enrollment_ids

            ward = (
                await self.db.execute(
                    ward_enrollment_ids(self.principal).where(
                        StudentProgramEnrollment.id == reg.student_program_enrollment_id
                    )
                )
            ).first() is not None
        out = (await self.registration_responses([reg], confirmed_only=ward))[0]
        if not ward:
            out.checks = await self._checks(reg)
        return out

    async def _checks(self, reg: CourseRegistration) -> list[dict[str, Any]]:
        enrolment = (await self.offerings.rows(StudentProgramEnrollment, [reg.student_program_enrollment_id]))[
            reg.student_program_enrollment_id
        ]
        record = (await self.offerings.rows(StudentTermRecord, [reg.student_term_record_id]))[
            reg.student_term_record_id
        ]
        window = (
            (await self.offerings.rows(RegistrationWindow, [reg.window_id])).get(reg.window_id)
            if reg.window_id
            else None
        )
        limits = await self.limits(enrolment, record, window, await self.overrides(reg.id))
        holds = await self.holds.open_holds(enrolment.id, "registration")
        return [
            {
                "key": "credits",
                "label": f"Credits {float(reg.total_credits):g} within {limits.min:g}–{limits.max:g}",
                "passed": limits.min <= float(reg.total_credits) <= limits.max,
            },
            {
                "key": "holds",
                "label": "No registration holds",
                "passed": not holds,
                "detail": ", ".join(h.reason for h in holds) or None,
            },
        ]

    # ---- rule 6: lock / withdraw ---------------------------------------------------------------------------------------------
    async def lock_due(self) -> int:
        """Beat ``registration.lock_windows``: approved → locked once the term's add-drop end has passed."""
        today = await self.today()
        terms = (
            (
                await self.db.execute(
                    select(AcademicTerm).where(
                        AcademicTerm.institution_id == self.inst,
                        AcademicTerm.deleted_at.is_(None),
                        AcademicTerm.status.notin_(("closed",)),
                    )
                )
            )
            .scalars()
            .all()
        )
        locked = 0
        for term in terms:
            windows = [w for w in await self.windows.for_term(term.id, None) if w.window_type == "add_drop"]
            if windows:
                end = max(w.ends_at for w in windows)
                passed = end <= utcnow()
            elif term.add_drop_end is not None:
                passed = term.add_drop_end < today
            else:
                continue
            if not passed:
                continue
            for reg in await self.regs.to_lock(term.id):
                reg.status, reg.locked_at = "locked", utcnow()
                locked += 1
                await self._emit("registration.locked", {"registration_id": str(reg.id)}, REG, reg.id)
                await self._notify(
                    "registration.locked",
                    [await self.user_of_enrollment(reg.student_program_enrollment_id)],
                    {"term": term.name},
                )
        await self.db.flush()
        return locked

    async def set_lock(self, registration_id: uuid.UUID, lock: bool, reason: str | None) -> RegistrationResponse:
        reg = await self.regs.get_visible(registration_id, for_update=True)
        want_from, to = ("approved", "locked") if lock else ("locked", "approved")
        if reg.status != want_from:
            raise APIError(409, ErrorCode.CONFLICT, f"The registration is {reg.status}")
        reg.status, reg.locked_at = to, utcnow() if lock else None
        await self.db.flush()
        await self._audit(
            "lock" if lock else "unlock", REG, reg.id, {"status": want_from}, {"status": to, "reason": reason}
        )
        return await self._one(reg)

    async def withdraw_item(self, registration_id: uuid.UUID, item_id: uuid.UUID, reason: str) -> RegistrationResponse:
        reg = await self.regs.get_visible(registration_id, for_update=True)
        item = await self.regs.item(item_id, for_update=True)
        if item.registration_id != reg.id:
            raise APIError(404, ErrorCode.NOT_FOUND, "Registration item not found")
        await self._drop(reg, item, reason, status="withdrawn")
        course = (await self.offerings.rows(Course, [item.course_id])).get(item.course_id)
        await self._audit("withdraw_item", REG, reg.id, None, {"item_id": str(item.id), "reason": reason})
        await self._emit(
            "registration.withdrawn", {"registration_id": str(reg.id), "item_id": str(item.id)}, REG, reg.id
        )
        await self._notify(
            "registration.item_withdrawn",
            [await self.user_of_enrollment(reg.student_program_enrollment_id)],
            {"course": course.code if course else "", "reason": reason},
        )
        return await self._one(reg)

    # ---- rule 7: overrides -----------------------------------------------------------------------------------------------------
    async def override(self, registration_id: uuid.UUID, body: OverrideRequest) -> RegistrationResponse:
        reg = await self.regs.get_visible(registration_id, for_update=True)
        await self._audit(
            "override",
            REG,
            reg.id,
            None,
            {
                "reason": body.reason,
                "max_credits": body.max_credits,
                "skip_prerequisites": [str(c) for c in body.skip_prerequisites],
                "skip_holds": body.skip_holds or None,
            },
        )
        return await self._one(reg)

    # ---- rule 8: bulk registration ---------------------------------------------------------------------------------------------
    async def bulk_register(
        self, body: BulkRegisterRequest, progress: Callable[..., Any] | None = None
    ) -> BulkRegisterResult:
        term = await self.get_term(body.term_id)
        batch = await self.offerings.batches([body.batch_id])
        if body.batch_id not in batch:
            raise APIError(404, ErrorCode.NOT_FOUND, "Batch not found")
        b = batch[body.batch_id]
        result = BulkRegisterResult(batch_id=b.id, term_id=term.id)
        rows = (
            await self.db.execute(
                select(StudentProgramEnrollment, StudentTermRecord)
                .join(StudentTermRecord, StudentTermRecord.student_program_enrollment_id == StudentProgramEnrollment.id)
                .where(
                    StudentProgramEnrollment.batch_id == b.id,
                    StudentProgramEnrollment.deleted_at.is_(None),
                    StudentProgramEnrollment.status == "active",
                    StudentTermRecord.term_id == term.id,
                )
            )
        ).all()
        if body.section_id:
            rows = [(e, r) for e, r in rows if r.section_id == body.section_id]
        result.students = len(rows)
        mandatory = list(
            (
                await self.db.execute(
                    select(CurriculumCourse.course_id).where(
                        CurriculumCourse.program_regulation_id == b.program_regulation_id,
                        CurriculumCourse.term_number == b.current_term_number,
                        CurriculumCourse.elective_basket_id.is_(None),
                        CurriculumCourse.is_mandatory.is_(True),
                    )
                )
            ).scalars()
        )
        offs = await self.offerings.for_courses(term.id, mandatory, statuses=("open",))
        courses = await self.offerings.rows(Course, mandatory)
        for n, (e, rec) in enumerate(rows):
            reg = await self._cart(e, term, rec, None)
            if reg.status in ("approved", "locked", "advisor_pending", "submitted"):
                result.skipped.append({"enrollment_id": str(e.id), "reason": reg.status})
                continue
            wanted = list(mandatory)
            if body.include_electives:
                for f in await self.forms.for_enrollment(e.id, term.id):
                    if f.allocated_course_id:
                        wanted.append(f.allocated_course_id)
            have = {i.course_id for i in (await self.regs.items([reg.id])).get(reg.id, []) if i.status in LIVE_ITEMS}
            targeted = await self.offerings.targeted_at(term.id, e.batch_id, rec.section_id)
            for course_id in wanted:
                if course_id in have:
                    continue
                candidates = [o for o in offs if o.course_id == course_id]
                if not candidates and body.include_electives:
                    candidates = await self.offerings.for_courses(term.id, [course_id], statuses=("open",))
                candidates.sort(key=lambda o: (o.id not in targeted, o.enrolled_count))
                placed = False
                for o in candidates:
                    locked = await self.offerings.get_one(o.id, for_update=True)
                    if locked.max_seats is not None and locked.enrolled_count >= locked.max_seats:
                        continue
                    await self._add(
                        reg,
                        e,
                        rec,
                        locked,
                        "regular",
                        None,
                        window=None,
                        status_when_seated="selected",
                        check_rules=False,
                        allow_waitlist=False,
                    )
                    placed = True
                    result.items_confirmed += 1
                    break
                if not placed:
                    c = courses.get(course_id)
                    result.shortfalls.append({"enrollment_id": str(e.id), "course": c.code if c else str(course_id)})
            student = (await self.offerings.rows(Student, [e.student_id]))[e.student_id]
            was = student.status
            await self.apply_approval(reg, self.actor_id)
            if was in ("provisional", "admitted"):
                result.activated += 1
            result.registrations_approved += 1
            if progress and n % 20 == 0:
                await progress(int(100 * n / max(1, len(rows))), f"{n}/{len(rows)} students")
        await self._audit(
            "bulk_register", "batch", b.id, None, result.model_dump(mode="json", exclude={"skipped", "shortfalls"})
        )
        return result

    async def enqueue_bulk(self, body: BulkRegisterRequest) -> uuid.UUID:
        from app.core.jobs import enqueue

        job = await enqueue(
            self.db, self.principal, "registration.bulk_register", {"body": body.model_dump(mode="json")}
        )
        return job.id

    # ---- waitlists -------------------------------------------------------------------------------------------------------------
    async def my_waitlists(self) -> list[WaitlistResponse]:
        _, enrolment = await self.me()
        rows = await self.waitlists.for_enrollment(enrolment.id)
        offs = await self.offerings.rows(CourseOffering, [w.offering_id for w in rows])
        courses = await self.offerings.rows(Course, [o.course_id for o in offs.values()])
        out = []
        for w in rows:
            o = offs.get(w.offering_id)
            c = courses.get(o.course_id) if o else None
            out.append(
                WaitlistResponse(
                    id=w.id,
                    offering_id=w.offering_id,
                    course_code=c.code if c else None,
                    course_title=c.title if c else None,
                    section_code=o.section_code if o else None,
                    enrollment_id=w.student_program_enrollment_id,
                    position=w.position,
                    status=w.status,
                    offered_until=w.offered_until,
                )
            )
        return out

    async def accept_waitlist(self, waitlist_id: uuid.UUID) -> RegistrationResponse:
        _, enrolment = await self.me()
        wl = await self.waitlists.get(waitlist_id, for_update=True)
        if wl.student_program_enrollment_id != enrolment.id:
            raise APIError(404, ErrorCode.NOT_FOUND, "Waitlist entry not found")
        if wl.status != "offered" or (wl.offered_until and wl.offered_until < utcnow()):
            raise APIError(409, ErrorCode.CONFLICT, f"No open seat offer (status {wl.status})")
        offering = await self.offerings.get_one(wl.offering_id, for_update=True)
        reg = await self.regs.for_enrollment(enrolment.id, offering.term_id, for_update=True)
        item = await self.regs.item_for_offering(reg.id, offering.id) if reg else None
        if reg is None or item is None or item.status != "waitlisted":
            raise APIError(409, ErrorCode.CONFLICT, "The waitlisted item is no longer in your cart")
        item.status = "confirmed" if reg.status in ("approved", "locked") else "selected"
        wl.status = "promoted"
        await self.db.flush()
        await self.recompute_total(reg)
        await self._audit("waitlist_accept", REG, reg.id, None, {"waitlist_id": str(wl.id), "item_status": item.status})
        await self._emit(
            "waitlist.promoted", {"waitlist_id": str(wl.id), "registration_id": str(reg.id)}, "offering_waitlist", wl.id
        )
        return await self._one(reg)

    async def expire_waitlists(self) -> int:
        """Beat ``waitlist.expire``: drop expired offers, free the held seat, offer it to the next in line."""
        n = 0
        for wl in await self.waitlists.expired_offers(utcnow()):
            offering = await self.offerings.get_one(wl.offering_id, for_update=True)
            wl.status = "expired"
            offering.enrolled_count = max(0, offering.enrolled_count - 1)
            reg = await self.regs.for_enrollment(wl.student_program_enrollment_id, offering.term_id, for_update=True)
            if reg is not None:
                item = await self.regs.item_for_offering(reg.id, offering.id)
                if item is not None and item.status == "waitlisted":
                    item.status, item.dropped_at, item.drop_reason = "dropped", utcnow(), "waitlist offer expired"
            await self.db.flush()
            course = (await self.offerings.rows(Course, [offering.course_id])).get(offering.course_id)
            await self._emit("waitlist.expired", {"waitlist_id": str(wl.id)}, "offering_waitlist", wl.id)
            await self._notify(
                "waitlist.expired",
                [await self.user_of_enrollment(wl.student_program_enrollment_id)],
                {"course": course.code if course else ""},
            )
            await self.promote_next(offering)
            n += 1
        return n

    # ---- term close check ------------------------------------------------------------------------------------------------------
    async def pending_count(self, term_id: uuid.UUID) -> int:
        return await self.regs.pending_in_term(term_id, tuple(PENDING_REGISTRATION - {"draft"}))

    async def reminders(self) -> int:
        """Beat ``registration.reminders`` (daily): students of windows open today without a submitted registration."""
        sent = 0
        now = utcnow()
        for w in await self.windows.list_all(status="open"):
            if not (w.starts_at <= now < w.ends_at) or (w.ends_at - now) > timedelta(days=3):
                continue
            term = (await self.offerings.rows(AcademicTerm, [w.term_id])).get(w.term_id)
            pending = (
                (
                    await self.db.execute(
                        select(Student.user_id)
                        .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                        .join(
                            StudentTermRecord,
                            StudentTermRecord.student_program_enrollment_id == StudentProgramEnrollment.id,
                        )
                        .where(
                            StudentTermRecord.term_id == w.term_id,
                            StudentProgramEnrollment.status == "active",
                            StudentProgramEnrollment.id.notin_(
                                select(CourseRegistration.student_program_enrollment_id).where(
                                    CourseRegistration.term_id == w.term_id,
                                    CourseRegistration.status.notin_(("draft", "changes_requested", "rejected")),
                                )
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            ids = [u for u in pending if u]
            if ids:
                await self._notify(
                    "registration.window_open",
                    ids,
                    {"window": w.name, "term": term.name if term else "", "ends_at": w.ends_at.strftime("%d %b %Y")},
                )
                sent += len(ids)
        return sent


# ---- workflow hooks ------------------------------------------------------------------------------------------------------------
class _Actor:
    def __init__(self, institution_id: uuid.UUID, user_id: Any):
        self.institution_id, self.id = institution_id, user_id
        self.impersonator_id, self.is_super_admin = None, False
        self.scopes: list[Any] = [("institution", None)]

    def has(self, module: str, action: str) -> bool:
        return True


@workflow_engine.on(ADVISOR_KEY, "approved")
async def _on_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != REG:
        return
    svc = RegistrationService(
        db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id
    )
    reg = await svc.regs.by_id(instance.entity_id, for_update=True)
    if reg is not None and reg.status == "advisor_pending":
        await svc.apply_approval(reg, getattr(actor, "id", None))


@workflow_engine.on(ADVISOR_KEY, "rejected")
async def _on_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != REG:
        return
    svc = RegistrationService(
        db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id
    )
    reg = await svc.regs.by_id(instance.entity_id, for_update=True)
    if reg is not None and reg.status == "advisor_pending":
        await svc.on_rejected(reg)


@workflow_engine.summariser(REG)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    reg = (await db.execute(select(CourseRegistration).where(CourseRegistration.id == entity_id))).scalar_one_or_none()
    if reg is None:
        return None, None
    return f"Course registration · {float(reg.total_credits):g} credits", f"/admin/registration/{reg.id}"


# ---- term close check -----------------------------------------------------------------------------------------------------------
async def _term_close_check(db: Any, term: Any) -> Any:
    from app.core.academic_hooks import CloseCheckResult

    n = (
        await db.execute(
            select(CourseRegistration.id).where(
                CourseRegistration.term_id == term.id,
                CourseRegistration.status.in_(("submitted", "advisor_pending", "changes_requested")),
            )
        )
    ).all()
    return CloseCheckResult(
        key="registration.pending",
        label="No pending course registrations",
        passed=not n,
        detail=f"{len(n)} registration(s) still pending" if n else None,
    )


def _register_hooks() -> None:
    from app.core.academic_hooks import register_term_close_check

    register_term_close_check("registration.pending", _term_close_check)


_register_hooks()

__all__ = ["RegistrationService"]
