"""Course offerings and registration windows — Prompts/09 §09.6 ``offering_service.py``.

1. CRUD: ``section_code`` unique per (term, course) → 409; the course must be ``active`` and its regulation
   ``active`` (or ``superseded`` — older batches still study under it); ``max_seats`` defaults to ``course.max_seats``
   then the setting ``registration.default_max_seats``; HODs write only their departments' offerings.
2. ``bulk_from_curriculum``: each target batch's programme-regulation structure term = ``batch.current_term_number`` →
   mandatory courses (+ basket courses with ``include_baskets``) → offerings (dedupe existing) with target rows; one
   offering per section code (``A``, ``B`` …); section *k* targets section *k* of each batch (one section → the whole
   batch). Dry run inline; apply inline up to 200 new offerings, else the ``offerings.bulk_from_curriculum`` job.
3. Faculty allocation: staff active and teaching, of the offering's department unless ``allow_cross_department`` by a
   dean / registrar; the Phase 06 workload is recomputed and a member above the cadre norm blocks (409
   ``WORKLOAD_EXCEEDED``) or warns per ``hr.workload_enforce``. ``apply_allocation_proposal`` applies a dean-approved
   Phase 06 proposal to the term's offerings.
4. Status machine ``OFFERING_TRANSITIONS``; ``cancelled`` only with zero confirmed items (live items are dropped).
5. Roster (+ XLSX export job); faculty see the rosters of their own offerings.
"""

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.registration import OFFERING_TRANSITIONS
from app.models.academic import AcademicTerm, Batch, Regulation
from app.models.curriculum import Course, CurriculumCourse, ElectiveBasket
from app.models.hr import CourseAllocationProposal, Staff
from app.models.offerings import CourseOffering, CourseOfferingFaculty, CourseOfferingTarget
from app.models.platform import Department
from app.models.registration import CourseRegistrationItem, OfferingWaitlist, RegistrationWindow
from app.schemas.offerings import (
    BulkFromCurriculumRequest,
    BulkPreview,
    BulkPreviewItem,
    OfferingCreate,
    OfferingFacultyReplace,
    OfferingFacultyResult,
    OfferingResponse,
    OfferingStatusChange,
    OfferingTargetsReplace,
    OfferingUpdate,
    RosterItem,
    TargetIn,
    WindowCreate,
    WindowResponse,
    WindowUpdate,
)
from app.services.academics.context import writable_department_ids
from app.services.registration.common import RegistrationBase, rule, utcnow
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

SECTION_CODES = "ABCDEFGHIJ"
BULK_INLINE_LIMIT = 200


class OfferingService(RegistrationBase):
    audit_module = "offerings"

    # ---- helpers ----------------------------------------------------------------------------------------------------
    async def _writable(self, department_id: uuid.UUID) -> None:
        writable = await writable_department_ids(self.db, self.principal)
        if writable is not None and department_id not in writable:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "You may manage offerings of your own department only")

    def visibility(self) -> VisibilityMeta:
        tabs = []
        if any(st == "department" for st, _ in getattr(self.principal, "scopes", [])):
            tabs.append("department")
        if self.can("offerings", "view_all"):
            tabs.append("all")
        return VisibilityMeta(self=True, scopes=tabs, default="all", pii=False)

    # ---- rule 1 -----------------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None = None, **filters: Any
    ) -> tuple[list[OfferingResponse], PaginationMeta, VisibilityMeta]:
        dept_ids = None
        if scope == "department":
            dept_ids = [sid for st, sid in self.principal.scopes if st == "department" and sid]
        stmt = self.offerings.filtered(mine=scope in ("mine", "self", "own"), department_ids=dept_ids, **filters)
        if not params.sort:
            stmt = stmt.order_by(CourseOffering.course_id, CourseOffering.section_code)
        rows, page = await self.offerings.paginate(stmt, params)
        return await self.offering_responses(rows, workload=True), page, self.visibility()

    async def get(self, offering_id: uuid.UUID) -> OfferingResponse:
        return (await self.offering_responses([await self.offerings.get_one(offering_id)], workload=True))[0]

    async def mine(self, term_id: uuid.UUID | None) -> list[OfferingResponse]:
        stmt = self.offerings.filtered(term_id=term_id, mine=True).order_by(CourseOffering.course_id)
        return await self.offering_responses((await self.db.execute(stmt)).scalars().all())

    async def _course(self, course_id: uuid.UUID) -> Course:
        course = (await self.offerings.rows(Course, [course_id])).get(course_id)
        if course is None or course.deleted_at is not None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course not found", {"field": "course_id"})
        reg = (await self.offerings.rows(Regulation, [course.regulation_id])).get(course.regulation_id)
        if course.status != "active" or reg is None or reg.status not in ("active", "superseded"):
            raise rule(
                "Only active courses of an active regulation can be offered",
                "COURSE_NOT_ACTIVE",
                course_status=course.status,
                regulation_status=reg.status if reg else None,
            )
        return course

    async def _targets(self, offering: CourseOffering, items: list[TargetIn]) -> list[CourseOfferingTarget]:
        batches = await self.offerings.rows(Batch, [t.batch_id for t in items])
        out = []
        for t in items:
            b = batches.get(t.batch_id)
            if b is None:
                raise APIError(
                    422, ErrorCode.VALIDATION, "Unknown batch", {"field": "targets", "batch_id": str(t.batch_id)}
                )
            out.append(
                CourseOfferingTarget(
                    institution_id=self.inst,
                    offering_id=offering.id,
                    batch_id=b.id,
                    section_id=t.section_id,
                    term_number=t.term_number or b.current_term_number,
                )
            )
        return out

    async def create(self, body: OfferingCreate) -> OfferingResponse:
        course = await self._course(body.course_id)
        term = await self.get_term(body.term_id)
        dept_id = body.department_id or course.department_id
        await self._writable(dept_id)
        dept = (await self.offerings.rows(Department, [dept_id])).get(dept_id)
        if dept is None:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown department", {"field": "department_id"})
        section = body.section_code.upper()
        if await self.offerings.find(term.id, course.id, section) is not None:
            raise APIError(409, ErrorCode.CONFLICT, f"Section {section} of {course.code} already exists in this term")
        seats = body.max_seats or course.max_seats or int(await self.reg_setting("default_max_seats", 60))
        row = CourseOffering(
            institution_id=self.inst,
            college_id=body.college_id or course.college_id or dept.college_id,
            term_id=term.id,
            course_id=course.id,
            department_id=dept_id,
            section_code=section,
            coordinator_staff_id=body.coordinator_staff_id,
            max_seats=seats,
            delivery_mode=body.delivery_mode.value,
            online_class_link=body.online_class_link,
            assessment_scheme_id=body.assessment_scheme_id or course.assessment_scheme_id,
            is_arrear_only=body.is_arrear_only,
            status="planned",
            created_by=self.actor_id,
        )
        self.db.add(row)
        await self.db.flush()
        for t in await self._targets(row, body.targets):
            self.db.add(t)
        await self.db.flush()
        await self._audit("create", "course_offering", row.id, None, {"course": course.code, "section": section})
        await self._emit(
            "offering.created", {"offering_id": str(row.id), "term_id": str(term.id)}, "course_offering", row.id
        )
        return await self.get(row.id)

    async def update(self, offering_id: uuid.UUID, body: OfferingUpdate) -> OfferingResponse:
        row = await self.offerings.get_one(offering_id, for_update=True)
        await self._writable(row.department_id)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        if "max_seats" in values and values["max_seats"] is not None and values["max_seats"] < row.enrolled_count:
            raise rule("Seats cannot go below the enrolled count", "SEATS_BELOW_ENROLLED", enrolled=row.enrolled_count)
        if values.get("section_code"):
            values["section_code"] = values["section_code"].upper()
            other = await self.offerings.find(row.term_id, row.course_id, values["section_code"])
            if other is not None and other.id != row.id:
                raise APIError(409, ErrorCode.CONFLICT, "Section code already used for this course and term")
        if "delivery_mode" in values and values["delivery_mode"] is not None:
            values["delivery_mode"] = str(values["delivery_mode"])
        old = {k: str(getattr(row, k)) for k in values}
        await self.offerings.update(row, body.version, **values)
        await self._audit("update", "course_offering", row.id, old, {k: str(v) for k, v in values.items()})
        await self._emit("offering.updated", {"offering_id": str(row.id)}, "course_offering", row.id)
        if "max_seats" in values:
            while await self.promote_next(row):
                pass
        return await self.get(row.id)

    # ---- rule 4 -----------------------------------------------------------------------------------------------------
    async def change_status(self, offering_id: uuid.UUID, body: OfferingStatusChange) -> OfferingResponse:
        row = await self.offerings.get_one(offering_id, for_update=True)
        await self._writable(row.department_id)
        to = body.status.value
        if to not in OFFERING_TRANSITIONS.get(row.status, set()):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"An offering in status '{row.status}' cannot move to '{to}'",
                {"from": row.status, "to": to, "allowed": sorted(OFFERING_TRANSITIONS.get(row.status, set()))},
            )
        if to == "cancelled":
            if await self.offerings.confirmed_count(row.id):
                raise rule("The offering has confirmed students — substitute it instead", "OFFERING_HAS_STUDENTS")
            items = (
                await self.db.execute(
                    select(CourseRegistrationItem).where(
                        CourseRegistrationItem.offering_id == row.id,
                        CourseRegistrationItem.status.in_(("selected", "waitlisted")),
                    )
                )
            ).scalars()
            for i in items:
                i.status, i.dropped_at, i.drop_reason = "dropped", utcnow(), "offering cancelled"
            for w in (
                await self.db.execute(select(OfferingWaitlist).where(OfferingWaitlist.offering_id == row.id))
            ).scalars():
                if w.status in ("waiting", "offered"):
                    w.status = "cancelled"
            row.enrolled_count, row.waitlist_count = 0, 0
        old = row.status
        row.status = to
        await self.db.flush()
        await self._audit("status", "course_offering", row.id, {"status": old}, {"status": to, "reason": body.reason})
        await self._emit(
            "offering.status_changed", {"offering_id": str(row.id), "from": old, "to": to}, "course_offering", row.id
        )
        return await self.get(row.id)

    # ---- rule 3 -----------------------------------------------------------------------------------------------------
    async def replace_faculty(self, offering_id: uuid.UUID, body: OfferingFacultyReplace) -> OfferingFacultyResult:
        row = await self.offerings.get_one(offering_id, for_update=True)
        await self._writable(row.department_id)
        staff = await self.offerings.rows(Staff, [i.staff_id for i in body.items])
        unit_wide = await writable_department_ids(self.db, self.principal) is None or any(
            st == "faculty" for st, _ in self.principal.scopes
        )
        for i in body.items:
            s = staff.get(i.staff_id)
            if s is None or s.deleted_at is not None or s.status == "exited":
                raise APIError(422, ErrorCode.VALIDATION, "Unknown or exited staff", {"staff_id": str(i.staff_id)})
            if s.staff_category != "teaching":
                raise APIError(
                    422, ErrorCode.VALIDATION, f"{s.full_name} is not teaching staff", {"staff_id": str(s.id)}
                )
            if s.department_id != row.department_id and not (body.allow_cross_department and unit_wide):
                raise rule(
                    f"{s.full_name} belongs to another department (cross-department allocation needs the dean)",
                    "CROSS_DEPARTMENT",
                    staff_id=str(s.id),
                )
        await self.offerings.replace_faculty(
            row.id,
            [
                CourseOfferingFaculty(
                    institution_id=self.inst,
                    offering_id=row.id,
                    staff_id=i.staff_id,
                    role=i.role.value,
                    hours_per_week=i.hours_per_week,
                )
                for i in body.items
            ],
        )
        coord = next((i.staff_id for i in body.items if i.role.value == "coordinator"), None)
        if coord:
            row.coordinator_staff_id = coord
        warnings = await self._workload_check([staff[i.staff_id] for i in body.items], row.term_id)
        await self._audit(
            "faculty", "course_offering", row.id, None, {"items": [i.model_dump(mode="json") for i in body.items]}
        )
        await self._emit(
            "offering.faculty_changed",
            {
                "offering_id": str(row.id),
                "term_id": str(row.term_id),
                "staff_ids": [str(i.staff_id) for i in body.items],
            },
            "course_offering",
            row.id,
        )
        return OfferingFacultyResult(offering=await self.get(row.id), warnings=warnings)

    async def _workload_check(self, members: list[Staff], term_id: uuid.UUID) -> list[dict[str, Any]]:
        from app.services.workload_service import WorkloadService

        if not members:
            return []
        term = (await self.offerings.rows(AcademicTerm, [term_id]))[term_id]
        loads = await WorkloadService(self.db, self.principal, self.request, self.inst).compute(members, term)
        over = [
            {
                "staff_id": str(w.staff_id),
                "name": w.staff_name,
                "total_hours": w.total_hours,
                "norm_hours": w.norm_hours,
            }
            for w in loads
            if w.load_status == "over"
        ]
        if over and (await self.setting("hr", "workload_enforce") or "warn") == "block":
            raise rule("Allocation exceeds the workload norm", "WORKLOAD_EXCEEDED", staff=over)
        return [{"code": "WORKLOAD_EXCEEDED", **o} for o in over]

    async def replace_targets(self, offering_id: uuid.UUID, body: OfferingTargetsReplace) -> OfferingResponse:
        row = await self.offerings.get_one(offering_id, for_update=True)
        await self._writable(row.department_id)
        await self.offerings.replace_targets(row.id, await self._targets(row, body.items))
        await self._audit("targets", "course_offering", row.id, None, {"targets": len(body.items)})
        return await self.get(row.id)

    async def apply_allocation_proposal(self, proposal: CourseAllocationProposal) -> int:
        """Phase 06 dean-approved proposal → ``course_offering_faculty`` rows of the term's offerings."""
        by_course: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for p in proposal.proposals or []:
            by_course.setdefault(uuid.UUID(str(p["course_id"])), []).append(p)
        applied = 0
        for course_id, items in by_course.items():
            offs = [
                o
                for o in await self.offerings.for_courses(proposal.term_id, [course_id])
                if o.department_id == proposal.department_id and o.status != "cancelled"
            ]
            if not offs:
                continue
            for n, p in enumerate(items):
                targets = offs if len(items) == 1 else [offs[n % len(offs)]]
                for o in targets:
                    role = p.get("role") or "instructor"
                    await self.offerings.upsert_faculty(
                        CourseOfferingFaculty(
                            institution_id=self.inst,
                            offering_id=o.id,
                            staff_id=uuid.UUID(str(p["staff_id"])),
                            role=role,
                            hours_per_week=int(float(p.get("hours") or 0)),
                        )
                    )
                    if role == "coordinator":
                        o.coordinator_staff_id = uuid.UUID(str(p["staff_id"]))
                    applied += 1
                    await self._emit(
                        "offering.faculty_changed",
                        {"offering_id": str(o.id), "source": "allocation"},
                        "course_offering",
                        o.id,
                    )
        await self.db.flush()
        return applied

    # ---- rule 2 -----------------------------------------------------------------------------------------------------
    async def bulk_from_curriculum(
        self, body: BulkFromCurriculumRequest, *, dry_run: bool = True, progress: Callable[..., Any] | None = None
    ) -> BulkPreview:
        term = await self.get_term(body.term_id)
        batches = await self.offerings.rows(Batch, body.batch_ids)
        missing = [str(b) for b in body.batch_ids if b not in batches]
        if missing:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown batches", {"field": "batch_ids", "ids": missing})
        sections = await self.offerings.sections_of(list(batches))
        preview = BulkPreview(term_id=term.id, dry_run=dry_run)
        # course → [(batch, term_number, mandatory, basket)]
        plan: dict[uuid.UUID, list[tuple[Batch, int, bool, uuid.UUID | None]]] = {}
        for b in batches.values():
            stmt = select(CurriculumCourse).where(
                CurriculumCourse.program_regulation_id == b.program_regulation_id,
                CurriculumCourse.term_number == b.current_term_number,
            )
            for cc in (await self.db.execute(stmt)).scalars():
                if cc.elective_basket_id is not None and not body.include_baskets:
                    continue
                plan.setdefault(cc.course_id, []).append(
                    (b, cc.term_number, cc.elective_basket_id is None and cc.is_mandatory, cc.elective_basket_id)
                )
        courses = await self.offerings.rows(Course, list(plan))
        depts = await self.offerings.rows(Department, [c.department_id for c in courses.values()])
        baskets = await self.offerings.rows(
            ElectiveBasket, [bk for rows in plan.values() for _, _, _, bk in rows if bk]
        )
        writable = await writable_department_ids(self.db, self.principal)
        default_seats = body.default_seats or int(await self.reg_setting("default_max_seats", 60))
        created = 0
        for n, (course_id, uses) in enumerate(plan.items()):
            c = courses.get(course_id)
            if c is None or c.status != "active":
                preview.warnings.append(f"{c.code if c else course_id} skipped (course not active)")
                continue
            if writable is not None and c.department_id not in writable:
                preview.warnings.append(f"{c.code} skipped (another department)")
                continue
            for k in range(body.sections_per_course):
                code = SECTION_CODES[k]
                existing = await self.offerings.find(term.id, c.id, code)
                preview.items.append(
                    BulkPreviewItem(
                        course_id=c.id,
                        course_code=c.code,
                        course_title=c.title,
                        department_code=depts[c.department_id].code if c.department_id in depts else None,
                        section_code=code,
                        batch_codes=[b.code for b, _, _, _ in uses],
                        term_number=uses[0][1],
                        mandatory=uses[0][2],
                        basket_code=baskets[uses[0][3]].code if uses[0][3] in baskets else None,
                        exists=existing is not None,
                    )
                )
                if existing is not None:
                    preview.existing += 1
                else:
                    preview.to_create += 1
                if dry_run:
                    continue
                row = existing
                if row is None:
                    row = CourseOffering(
                        institution_id=self.inst,
                        college_id=c.college_id or depts[c.department_id].college_id,
                        term_id=term.id,
                        course_id=c.id,
                        department_id=c.department_id,
                        section_code=code,
                        max_seats=c.max_seats or default_seats,
                        assessment_scheme_id=c.assessment_scheme_id,
                        status="planned",
                        created_by=self.actor_id,
                    )
                    self.db.add(row)
                    await self.db.flush()
                    created += 1
                    await self._emit(
                        "offering.created", {"offering_id": str(row.id), "bulk": True}, "course_offering", row.id
                    )
                for b, tn, _, _ in uses:
                    secs = sections.get(b.id, [])
                    section_id = secs[k].id if body.sections_per_course > 1 and k < len(secs) else None
                    if body.sections_per_course > 1 and k >= len(secs):
                        continue
                    if await self.offerings.add_target(
                        CourseOfferingTarget(
                            institution_id=self.inst,
                            offering_id=row.id,
                            batch_id=b.id,
                            section_id=section_id,
                            term_number=tn,
                        )
                    ):
                        preview.targets_added += 1
            if progress and n % 10 == 0:
                await progress(int(100 * n / max(1, len(plan))), f"{n}/{len(plan)} courses")
        preview.total = len(preview.items)
        if not dry_run:
            await self._audit(
                "bulk_create", "academic_term", term.id, None, {"created": created, "targets": preview.targets_added}
            )
        return preview

    async def enqueue_bulk(self, body: BulkFromCurriculumRequest) -> BulkPreview:
        from app.core.jobs import enqueue

        preview = await self.bulk_from_curriculum(body, dry_run=True)
        if preview.to_create <= BULK_INLINE_LIMIT:
            return await self.bulk_from_curriculum(body, dry_run=False)
        job = await enqueue(
            self.db, self.principal, "offerings.bulk_from_curriculum", {"body": body.model_dump(mode="json")}
        )
        preview.job_id, preview.dry_run = job.id, False
        return preview

    # ---- rule 5 -----------------------------------------------------------------------------------------------------
    async def _roster_access(self, row: CourseOffering) -> None:
        if self.can("offerings", "view_all") or self.can("offerings", "manage") or self.can("registration", "view_all"):
            return
        if self.actor_id and await self.offerings.is_taught_by(row.id, self.actor_id):
            return
        raise APIError(404, ErrorCode.NOT_FOUND, "Course offering not found")

    async def roster(self, offering_id: uuid.UUID, include_waitlist: bool = False) -> list[RosterItem]:
        row = await self.offerings.get_one(offering_id)
        await self._roster_access(row)
        statuses = ("selected", "confirmed", "waitlisted") if include_waitlist else ("selected", "confirmed")
        rows = await self.offerings.roster(row.id, statuses)
        batches = await self.offerings.rows(Batch, [e.batch_id for _, _, _, e, _ in rows])
        from app.models.academic import BatchSection, Program

        programs = await self.offerings.rows(Program, [e.program_id for _, _, _, e, _ in rows])
        sections = await self.offerings.rows(BatchSection, [t.section_id for *_, t in rows])
        return [
            RosterItem(
                item_id=i.id,
                registration_id=r.id,
                student_id=s.id,
                registration_number=s.registration_number,
                name=s.full_name,
                program_code=programs[e.program_id].code if e.program_id in programs else None,
                batch_code=batches[e.batch_id].code if e.batch_id in batches else None,
                section_name=sections[t.section_id].name if t.section_id in sections else None,
                registration_type=i.registration_type,
                attempt_number=i.attempt_number,
                status=i.status,
                added_at=i.added_at,
            )
            for i, r, s, e, t in rows
        ]

    async def roster_xlsx(self, offering_id: uuid.UUID) -> bytes:
        import io

        from openpyxl import Workbook

        rows = await self.roster(offering_id)
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Roster"
        ws.append(["Registration no.", "Name", "Programme", "Batch", "Section", "Type", "Attempt", "Status"])
        for r in rows:
            ws.append(
                [
                    r.registration_number,
                    r.name,
                    r.program_code,
                    r.batch_code,
                    r.section_name,
                    r.registration_type,
                    r.attempt_number,
                    r.status,
                ]
            )
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    async def enqueue_roster_export(self, offering_id: uuid.UUID) -> uuid.UUID:
        from app.core.jobs import enqueue

        await self._roster_access(await self.offerings.get_one(offering_id))
        job = await enqueue(self.db, self.principal, "offerings.roster_export", {"offering_id": str(offering_id)})
        return job.id

    async def recount(self, term_id: uuid.UUID | None = None) -> int:
        """Recompute ``enrolled_count`` / ``waitlist_count`` from the items (held waitlist offers count as seated)."""
        rows = await self.offerings.of_term(term_id) if term_id else []
        counts = await self.offerings.seated_counts([o.id for o in rows])
        held = dict(
            (
                await self.db.execute(
                    select(OfferingWaitlist.offering_id, func.count())
                    .where(OfferingWaitlist.status == "offered")
                    .group_by(OfferingWaitlist.offering_id)
                )
            ).all()
        )
        fixed = 0
        for o in rows:
            seated, waiting = counts.get(o.id, (0, 0))
            seated += int(held.get(o.id, 0))
            waiting = max(0, waiting - int(held.get(o.id, 0)))
            if (o.enrolled_count, o.waitlist_count) != (seated, waiting):
                o.enrolled_count, o.waitlist_count = seated, waiting
                fixed += 1
        await self.db.flush()
        return fixed


class WindowService(RegistrationBase):
    async def list_windows(
        self, term_id: uuid.UUID | None, status: str | None, window_type: str | None = None
    ) -> list[WindowResponse]:
        rows = await self.windows.list_all(term_id, status, window_type=window_type)
        terms = await self.offerings.rows(AcademicTerm, [w.term_id for w in rows])
        return [self.window_out(w, terms[w.term_id].name if w.term_id in terms else None) for w in rows]

    async def get(self, window_id: uuid.UUID) -> WindowResponse:
        w = await self.windows.get(window_id)
        return self.window_out(w)

    async def create(self, body: WindowCreate) -> WindowResponse:
        term = await self.get_term(body.term_id)
        if body.window_type.value == "audit":
            from app.core.features import is_enabled

            if not await is_enabled(self.inst, "registration.audit_courses"):
                raise APIError(403, ErrorCode.FEATURE_DISABLED, "Audit courses are disabled")
        now = utcnow()
        w = await self.windows.add(
            RegistrationWindow(
                institution_id=self.inst,
                college_id=body.college_id,
                term_id=term.id,
                name=body.name,
                window_type=body.window_type.value,
                applies_to=body.applies_to.model_dump(mode="json", exclude_none=True) if body.applies_to else None,
                starts_at=body.starts_at,
                ends_at=body.ends_at,
                late_fee_paise=body.late_fee_paise,
                requires_advisor_approval=body.requires_advisor_approval,
                requires_fee_clearance=body.requires_fee_clearance,
                max_credits_override=body.max_credits_override,
                status="open"
                if body.starts_at <= now < body.ends_at
                else ("closed" if body.ends_at <= now else "scheduled"),
                created_by=self.actor_id,
            )
        )
        await self._audit("create", "registration_window", w.id, None, {"name": w.name, "type": w.window_type})
        return self.window_out(w, term.name)

    async def update(self, window_id: uuid.UUID, body: WindowUpdate) -> WindowResponse:
        w = await self.windows.get(window_id, for_update=True)
        values = body.model_dump(exclude_unset=True)
        if "applies_to" in values:
            values["applies_to"] = (
                body.applies_to.model_dump(mode="json", exclude_none=True) if body.applies_to else None
            )
        for k, v in values.items():
            setattr(w, k, v)
        if w.ends_at <= w.starts_at:
            raise APIError(422, ErrorCode.VALIDATION, "ends_at must be after starts_at", {"field": "ends_at"})
        now = utcnow()
        if w.status != "closed" or "ends_at" in values:
            w.status = "open" if w.starts_at <= now < w.ends_at else ("closed" if w.ends_at <= now else "scheduled")
        await self.db.flush()
        await self._audit("update", "registration_window", w.id, None, {k: str(v) for k, v in values.items()})
        return self.window_out(w)

    async def change_status(self, window_id: uuid.UUID, status: str) -> WindowResponse:
        w = await self.windows.get(window_id, for_update=True)
        old = w.status
        w.status = status
        if status == "open" and w.starts_at > utcnow():
            w.starts_at = utcnow()
        await self.db.flush()
        await self._audit("status", "registration_window", w.id, {"status": old}, {"status": status})
        return self.window_out(w)

    async def tick(self) -> int:
        """Beat ``registration.window_status`` (5 min): scheduled → open → closed by the clock."""
        now, changed = utcnow(), 0
        for w in await self.windows.due_for_status():
            want = "open" if w.starts_at <= now < w.ends_at else ("closed" if w.ends_at <= now else "scheduled")
            if want != w.status:
                w.status = want
                changed += 1
        await self.db.flush()
        return changed
