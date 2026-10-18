"""Exam sessions, papers, date-sheet and centres — Prompts/14 §14.6 ``exam_session_service``.

1. CRUD; ``college_id NULL`` = central session; ``valuation_mode`` / ``discrepancy_pct`` default from the ``exams.*``
   settings; ``fee_rules`` validated (non-negative paise).
2. Status machine (forward only) ``draft → registration_open → registration_closed → scheduled → in_progress →
   valuation → result_processing → results_published → closed``: ``registration_open`` needs papers, ``scheduled``
   a published date-sheet, ``valuation`` every paper ``conducted`` (or later); ``results_published`` locks the session.
   Beat ``exams.session_auto_status`` moves ``scheduled → in_progress`` on ``start_date`` (institution-local).
3. ``papers_bulk``: theory per offered course of the term (practical when the course has practical hours, practical
   only for lab courses, project viva for project / dissertation courses) + arrear-only courses with open
   ``student_arrears``; idempotent on ``UNIQUE (session, course, paper_type)``; codes ``{course}-{T|P|V|D|O}``.
4. Date-sheet: assign date / slot / time; ``check_clashes`` = enrolments with two registrable papers (registered
   items, confirmed regular items of the term, open arrears) on the same date + slot, papers on holidays and
   unscheduled papers; ``publish`` → 409 ``DATE_SHEET_CLASH`` / ``HOLIDAY`` unless ``force`` (COE; exceptions
   audited) → ``calendar_events(event_type='exam')`` + ``exams.date_sheet_published``; PDF / ICS renderers.
"""
# mypy: disable-error-code="arg-type,var-annotated"

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.enums.exams import SESSION_FLOW
from app.models.curriculum import Course
from app.models.exams import CalendarEvent, ExamCentre, ExamPaper, ExamRegistration, ExamRegistrationItem, ExamSession
from app.models.offerings import CourseOffering
from app.models.platform import AuditLog, Holiday
from app.models.registration import CourseRegistration, CourseRegistrationItem, StudentArrear
from app.models.students import Student, StudentProgramEnrollment
from app.schemas.exams import (
    BulkPapersPreview,
    BulkPapersRequest,
    ClashItem,
    ClashReport,
    DateSheetUpdate,
    ExamCentreIn,
    ExamCentreOut,
    ExamPaperCreate,
    ExamPaperResponse,
    ExamPaperUpdate,
    ExamSessionCreate,
    ExamSessionResponse,
    ExamSessionUpdate,
)
from app.services.exams.common import ExamBase, now_utc, rule

ENTITY = "exam_session"
SUFFIX = {"theory": "T", "practical": "P", "project_viva": "V", "dissertation": "D", "online": "O"}


class ExamSessionService(ExamBase):
    # ---- 1. sessions ----------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[ExamSession]) -> list[ExamSessionResponse]:
        ids = [r.id for r in rows]
        papers = dict(
            (
                await self.db.execute(
                    select(ExamPaper.exam_session_id, func.count())
                    .where(ExamPaper.exam_session_id.in_(ids or [uuid.uuid4()]))
                    .group_by(ExamPaper.exam_session_id)
                )
            ).all()
        )  # type: ignore[arg-type]
        regs: dict[tuple[Any, str], int] = {
            (sid, st): int(n)
            for sid, st, n in (
                await self.db.execute(
                    select(ExamRegistration.exam_session_id, ExamRegistration.status, func.count())
                    .where(ExamRegistration.exam_session_id.in_(ids or [uuid.uuid4()]))
                    .group_by(ExamRegistration.exam_session_id, ExamRegistration.status)
                )
            ).all()
        }
        out = []
        for r in rows:
            o = ExamSessionResponse.model_validate(r)
            o.counts = {"papers": int(papers.get(r.id, 0)), **{st: n for (sid, st), n in regs.items() if sid == r.id}}
            out.append(o)
        return out

    async def list_sessions(self, term_id: uuid.UUID | None, status: str | None) -> list[ExamSessionResponse]:
        q = select(ExamSession).where(ExamSession.institution_id == self.inst, ExamSession.deleted_at.is_(None))
        if term_id:
            q = q.where(ExamSession.term_id == term_id)
        if status:
            q = q.where(ExamSession.status == status)
        colleges = self._college_ids()
        institution = (
            self.principal is None
            or getattr(self.principal, "is_super_admin", False)
            or any(st == "institution" for st, _ in getattr(self.principal, "scopes", []))
        )
        if not institution and colleges:
            q = q.where(or_(ExamSession.college_id.is_(None), ExamSession.college_id.in_(colleges)))
        if not (self.can("exams", "view") or self.can("exams", "view_all") or self.can("exams", "configure")):
            # learners: sessions of their colleges (central ones included) that left draft
            college_ids = (
                (
                    await self.db.execute(
                        select(StudentProgramEnrollment.college_id)
                        .join(Student, Student.id == StudentProgramEnrollment.student_id)
                        .where(Student.user_id == self.actor_id)
                    )
                )
                .scalars()
                .all()
            )
            q = q.where(
                ExamSession.status != "draft",
                or_(ExamSession.college_id.is_(None), ExamSession.college_id.in_(list(college_ids) or [uuid.uuid4()])),
            )
        return await self.outs(list((await self.db.execute(q.order_by(ExamSession.created_at.desc()))).scalars().all()))

    async def get(self, sid: uuid.UUID) -> ExamSessionResponse:
        return (await self.outs([await self.session(sid)]))[0]

    def _validate_fee_rules(self, rules: dict[str, Any] | None) -> None:
        for k, v in (rules or {}).items():
            if isinstance(v, int | float) and v < 0:
                raise APIError(422, ErrorCode.VALIDATION, f"fee_rules.{k} must be ≥ 0", {"field": f"fee_rules.{k}"})

    async def create(self, body: ExamSessionCreate) -> ExamSessionResponse:
        self._validate_fee_rules(body.fee_rules)
        data = body.model_dump()
        data["valuation_mode"] = body.valuation_mode or str(
            await self.setting("exams", "valuation_mode_default") or "single"
        )
        data["discrepancy_pct"] = Decimal(
            str(
                body.discrepancy_pct
                if body.discrepancy_pct is not None
                else (await self.setting("exams", "discrepancy_pct_default") or 15)
            )
        )
        s = ExamSession(institution_id=self.inst, created_by=self.actor_id, status="draft", **data)
        self.db.add(s)
        await self.db.flush()
        await self._audit("create", ENTITY, s.id, None, {"name": s.name, "kind": s.exam_kind})
        await self._emit("exams.session_created", {"exam_session_id": str(s.id)}, ENTITY, s.id)
        return await self.get(s.id)

    async def update(self, sid: uuid.UUID, body: ExamSessionUpdate) -> ExamSessionResponse:
        s = await self.session(sid, for_update=True, write=True)
        if body.version is not None and body.version != s.version:
            raise APIError(
                409, ErrorCode.STALE_VERSION, "Record was modified by someone else", {"current_version": s.version}
            )
        self._validate_fee_rules(body.fee_rules)
        for k, v in body.model_dump(exclude_none=True, exclude={"version"}).items():
            setattr(s, k, Decimal(str(v)) if k == "discrepancy_pct" else v)
        s.version += 1
        await self.db.flush()
        await self._audit("update", ENTITY, s.id, None, body.model_dump(mode="json", exclude_none=True))
        return await self.get(s.id)

    async def change_status(self, sid: uuid.UUID, to: str, *, system: bool = False) -> ExamSessionResponse:
        s = await self.session(sid, for_update=True, write=True)
        if to not in SESSION_FLOW:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown status {to}")
        if SESSION_FLOW.index(to) <= SESSION_FLOW.index(s.status):
            raise rule(f"Status moves forward only ({s.status} → {to})", "BACKWARD_TRANSITION")
        if (
            to == "registration_open"
            and not (
                await self.db.execute(select(ExamPaper.id).where(ExamPaper.exam_session_id == s.id).limit(1))
            ).first()
        ):
            raise rule("Create the papers first", "NO_PAPERS")
        if SESSION_FLOW.index(to) >= SESSION_FLOW.index("scheduled") and not await self._date_sheet_published(s.id):
            raise rule("Publish the date-sheet first", "DATE_SHEET_NOT_PUBLISHED")
        if to == "valuation":
            pending = (
                await self.db.execute(
                    select(func.count())
                    .select_from(ExamPaper)
                    .where(ExamPaper.exam_session_id == s.id, ExamPaper.status.in_(("planned", "qp_ready")))
                )
            ).scalar_one()
            if pending:
                raise rule(f"{pending} paper(s) not conducted yet", "PAPERS_PENDING")
        old = s.status
        s.status = to
        if to == "results_published":
            s.is_locked = True
        s.version += 1
        await self.db.flush()
        await self._audit("status", ENTITY, s.id, {"status": old}, {"status": to, "system": system})
        await self._emit("exams.status_changed", {"exam_session_id": str(s.id), "from": old, "to": to}, ENTITY, s.id)
        return await self.get(s.id)

    async def lock(self, sid: uuid.UUID) -> ExamSessionResponse:
        s = await self.session(sid, for_update=True)
        s.is_locked = True
        await self.db.flush()
        await self._audit("lock", ENTITY, s.id, None, {"is_locked": True})
        return await self.get(s.id)

    async def auto_status(self) -> int:
        today = await self.today()
        rows = (
            (
                await self.db.execute(
                    select(ExamSession.id).where(
                        ExamSession.institution_id == self.inst,
                        ExamSession.status == "scheduled",
                        ExamSession.start_date <= today,
                    )
                )
            )
            .scalars()
            .all()
        )
        for sid in rows:
            await self.change_status(sid, "in_progress", system=True)
        return len(rows)

    # ---- papers ---------------------------------------------------------------------------------------------------------
    async def paper_outs(self, rows: list[ExamPaper]) -> list[ExamPaperResponse]:
        courses = {
            c.id: c
            for c in (
                await self.db.execute(
                    select(Course).where(Course.id.in_([r.course_id for r in rows] or [uuid.uuid4()]))
                )
            ).scalars()
        }
        regs = dict(
            (
                await self.db.execute(
                    select(ExamRegistrationItem.exam_paper_id, func.count())
                    .where(
                        ExamRegistrationItem.exam_paper_id.in_([r.id for r in rows] or [uuid.uuid4()]),
                        ExamRegistrationItem.status != "cancelled",
                    )
                    .group_by(ExamRegistrationItem.exam_paper_id)
                )
            ).all()
        )  # type: ignore[arg-type]
        out = []
        for r in rows:
            o = ExamPaperResponse.model_validate(r)
            c = courses.get(r.course_id)
            o.course_code, o.course_title = (c.code, c.title) if c else (None, None)
            o.registered = int(regs.get(r.id, 0))
            out.append(o)
        return out

    async def papers(self, sid: uuid.UUID) -> list[ExamPaperResponse]:
        s = await self.session(sid)
        rows = (
            (
                await self.db.execute(
                    select(ExamPaper)
                    .where(ExamPaper.exam_session_id == s.id)
                    .order_by(ExamPaper.exam_date.nulls_last(), ExamPaper.session_slot, ExamPaper.paper_code)
                )
            )
            .scalars()
            .all()
        )
        return await self.paper_outs(list(rows))

    async def create_paper(self, sid: uuid.UUID, body: ExamPaperCreate) -> ExamPaperResponse:
        s = await self.session(sid, write=True)
        if (
            await self.db.execute(
                select(ExamPaper.id).where(
                    ExamPaper.exam_session_id == s.id,
                    ExamPaper.course_id == body.course_id,
                    ExamPaper.paper_type == body.paper_type,
                )
            )
        ).first():
            raise APIError(409, ErrorCode.CONFLICT, "The session already has this paper")
        course = (await self.db.execute(select(Course).where(Course.id == body.course_id))).scalar_one_or_none()
        if course is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course not found")
        data = body.model_dump()
        data["max_marks"] = Decimal(str(body.max_marks))
        data["paper_code"] = body.paper_code or f"{course.code}-{SUFFIX[body.paper_type]}"
        p = ExamPaper(institution_id=self.inst, exam_session_id=s.id, status="planned", **data)
        self.db.add(p)
        await self.db.flush()
        await self._audit("create_paper", ENTITY, s.id, None, {"paper_code": p.paper_code})
        return (await self.paper_outs([p]))[0]

    async def update_paper(self, pid: uuid.UUID, body: ExamPaperUpdate) -> ExamPaperResponse:
        p, s = await self.paper(pid, for_update=True)
        if s.is_locked:
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The exam session is locked")
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(p, k, Decimal(str(v)) if k == "max_marks" else v)
        await self.db.flush()
        if body.status == "conducted":
            await self._emit("exams.paper_conducted", {"exam_paper_id": str(p.id)}, "exam_paper", p.id)
        return (await self.paper_outs([p]))[0]

    async def delete_paper(self, pid: uuid.UUID) -> None:
        p, s = await self.paper(pid, for_update=True)
        if (
            s.is_locked
            or (
                await self.db.execute(
                    select(ExamRegistrationItem.id).where(ExamRegistrationItem.exam_paper_id == p.id).limit(1)
                )
            ).first()
        ):
            raise APIError(409, ErrorCode.CONFLICT, "Papers with registrations cannot be deleted")
        await self.db.delete(p)
        await self.db.flush()

    async def papers_bulk(self, sid: uuid.UUID, body: BulkPapersRequest) -> BulkPapersPreview:
        s = await self.session(sid, write=True)
        existing = {
            (r.course_id, r.paper_type)
            for r in (await self.db.execute(select(ExamPaper).where(ExamPaper.exam_session_id == s.id))).scalars()
        }
        out = BulkPapersPreview(dry_run=body.dry_run)
        wanted: list[tuple[Course, str]] = []
        if body.from_offerings:
            q = (
                select(Course)
                .join(CourseOffering, CourseOffering.course_id == Course.id)
                .where(
                    CourseOffering.term_id == s.term_id,
                    CourseOffering.deleted_at.is_(None),
                    CourseOffering.status.notin_(("cancelled",)),
                )
                .distinct()
            )
            if s.college_id:
                q = q.where(CourseOffering.college_id == s.college_id)
            for c in (await self.db.execute(q)).scalars():
                ctype = (c.course_type or "").lower()
                if "project" in ctype or "dissertation" in ctype or "internship" in ctype:
                    wanted.append((c, "project_viva"))
                    out.project_viva += 1
                elif "lab" in ctype or "practical" in ctype:
                    wanted.append((c, "practical"))
                    out.practical += 1
                else:
                    wanted.append((c, "theory"))
                    out.theory += 1
                    if (c.practical_hours or 0) > 0:
                        wanted.append((c, "practical"))
                        out.practical += 1
        if body.include_arrears:
            have = {c.id for c, _ in wanted}
            q = (
                select(Course)
                .join(StudentArrear, StudentArrear.course_id == Course.id)
                .where(StudentArrear.institution_id == self.inst, StudentArrear.status.in_(("open", "registered")))
                .distinct()
            )
            for c in (await self.db.execute(q)).scalars():
                if c.id not in have:
                    wanted.append((c, "theory"))
                    out.arrear_only += 1
        for c, ptype in wanted:
            if (c.id, ptype) in existing:
                out.existing += 1
                continue
            if body.dry_run:
                continue
            mx = Decimal(str(c.ese_max or 100))
            self.db.add(
                ExamPaper(
                    institution_id=self.inst,
                    exam_session_id=s.id,
                    course_id=c.id,
                    paper_type=ptype,
                    paper_code=f"{c.code}-{SUFFIX[ptype]}"[:30],
                    max_marks=mx,
                    duration_minutes=180 if ptype == "theory" else 120,
                    status="planned",
                )
            )
            existing.add((c.id, ptype))
            out.created += 1
        await self.db.flush()
        if not body.dry_run:
            await self._audit("papers_bulk", ENTITY, s.id, None, out.model_dump())
        return out

    # ---- date-sheet -----------------------------------------------------------------------------------------------------
    async def update_date_sheet(self, sid: uuid.UUID, body: DateSheetUpdate) -> list[ExamPaperResponse]:
        s = await self.session(sid, write=True)
        for e in body.entries:
            p = (
                await self.db.execute(
                    select(ExamPaper)
                    .where(ExamPaper.id == e.paper_id, ExamPaper.exam_session_id == s.id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if p is None:
                raise APIError(404, ErrorCode.NOT_FOUND, f"Paper {e.paper_id} is not in this session")
            p.exam_date, p.session_slot = e.exam_date, e.session_slot
            if e.start_time:
                p.start_time = e.start_time
            elif p.start_time is None:
                from datetime import time as _t

                p.start_time = {"FN": _t(10, 0), "AN": _t(14, 0), "EVE": _t(17, 0)}[e.session_slot]
            if e.duration_minutes:
                p.duration_minutes = e.duration_minutes
        await self.db.flush()
        await self._audit("date_sheet", ENTITY, s.id, None, {"entries": len(body.entries)})
        return await self.papers(s.id)

    async def candidate_papers(self, s: ExamSession) -> dict[uuid.UUID, set[uuid.UUID]]:
        """enrolment → paper ids it is (or would be) registered for in this session."""
        papers = (
            await self.db.execute(
                select(ExamPaper.id, ExamPaper.course_id, ExamPaper.paper_type).where(ExamPaper.exam_session_id == s.id)
            )
        ).all()
        by_course: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for pid, cid, _ in papers:
            by_course[cid].append(pid)
        out: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for eid, pid in (
            await self.db.execute(
                select(ExamRegistration.student_program_enrollment_id, ExamRegistrationItem.exam_paper_id)
                .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
                .where(ExamRegistration.exam_session_id == s.id, ExamRegistrationItem.status != "cancelled")
            )
        ).all():
            out[eid].add(pid)
        regular = (
            select(CourseRegistration.student_program_enrollment_id, CourseOffering.course_id)
            .join(CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id)
            .join(CourseOffering, CourseOffering.id == CourseRegistrationItem.offering_id)
            .where(CourseRegistration.term_id == s.term_id, CourseRegistrationItem.status == "confirmed")
        )
        for eid, cid in (await self.db.execute(regular)).all():
            out[eid].update(by_course.get(cid, []))
        for eid, cid in (
            await self.db.execute(
                select(StudentArrear.student_program_enrollment_id, StudentArrear.course_id).where(
                    StudentArrear.institution_id == self.inst, StudentArrear.status.in_(("open", "registered"))
                )
            )
        ).all():
            out[eid].update(p for p in by_course.get(cid, []))
        return out

    async def check_clashes(self, sid: uuid.UUID) -> ClashReport:
        s = await self.session(sid)
        papers = {
            p.id: p
            for p in (await self.db.execute(select(ExamPaper).where(ExamPaper.exam_session_id == s.id))).scalars()
        }
        report = ClashReport(
            unscheduled=[p.paper_code or str(p.id) for p in papers.values() if not p.exam_date or not p.session_slot]
        )
        regnos = {}
        for eid, pids in (await self.candidate_papers(s)).items():
            slots: dict[tuple[Any, str], list[str]] = defaultdict(list)
            for pid in pids:
                p = papers.get(pid)
                if p and p.exam_date and p.session_slot:
                    slots[(p.exam_date, p.session_slot)].append(p.paper_code or str(p.id))
            for (d, slot), codes in slots.items():
                if len(codes) > 1:
                    if not regnos:
                        regnos = dict(
                            (
                                await self.db.execute(
                                    select(StudentProgramEnrollment.id, Student.registration_number)
                                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                                    .where(StudentProgramEnrollment.institution_id == self.inst)
                                )
                            ).all()
                        )
                    report.items.append(
                        ClashItem(
                            student_program_enrollment_id=eid,
                            registration_number=regnos.get(eid),
                            exam_date=d,
                            session_slot=slot,
                            papers=sorted(codes),
                        )
                    )
        dates = {p.exam_date for p in papers.values() if p.exam_date}
        if dates:
            hol = (
                (
                    await self.db.execute(
                        select(Holiday).where(
                            Holiday.institution_id == self.inst,
                            Holiday.applies_to.in_(("all", "students")),
                            or_(Holiday.college_id.is_(None), Holiday.college_id == s.college_id)
                            if s.college_id
                            else True,
                            Holiday.holiday_date <= max(dates),
                            func.coalesce(Holiday.end_date, Holiday.holiday_date) >= min(dates),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for h in hol:
                end = h.end_date or h.holiday_date
                for p in papers.values():
                    if p.exam_date and h.holiday_date <= p.exam_date <= end:
                        report.holidays.append(
                            {"paper": p.paper_code, "date": p.exam_date.isoformat(), "holiday": h.name}
                        )
        return report

    async def _date_sheet_published(self, sid: uuid.UUID) -> bool:
        return (
            await self.db.execute(
                select(AuditLog.id)
                .where(
                    AuditLog.record_type == ENTITY, AuditLog.record_id == sid, AuditLog.action == "publish_date_sheet"
                )
                .limit(1)
            )
        ).first() is not None

    async def publish_date_sheet(self, sid: uuid.UUID, *, force: bool = False) -> ClashReport:
        s = await self.session(sid, for_update=True, write=True)
        report = await self.check_clashes(s.id)
        if report.unscheduled:
            raise rule(
                f"{len(report.unscheduled)} paper(s) have no date / slot", "UNSCHEDULED", papers=report.unscheduled[:50]
            )
        if (report.items or report.holidays) and not force:
            code = "DATE_SHEET_CLASH" if report.items else "HOLIDAY"
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"{len(report.items)} clash(es), {len(report.holidays)} holiday conflict(s)",
                {"code": code, "report": report.model_dump(mode="json")},
            )
        if force and not self.can("exams", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the COE may force-publish a date-sheet with clashes")
        # calendar events (replace the session's earlier ones)
        for old in (
            await self.db.execute(
                select(CalendarEvent).where(
                    CalendarEvent.source_type == "exam_paper",
                    CalendarEvent.source_id.in_(select(ExamPaper.id).where(ExamPaper.exam_session_id == s.id)),
                )
            )
        ).scalars():
            old.deleted_at = now_utc()
        inst = await self.institution()
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(inst.timezone or "Asia/Kolkata") if hasattr(inst, "timezone") else ZoneInfo("Asia/Kolkata")
        papers = (
            await self.db.execute(
                select(ExamPaper, Course)
                .join(Course, Course.id == ExamPaper.course_id)
                .where(ExamPaper.exam_session_id == s.id)
            )
        ).all()
        for p, c in papers:
            assert p.exam_date is not None
            from datetime import time as _t

            start = datetime.combine(p.exam_date, p.start_time or _t(10, 0), tz)
            self.db.add(
                CalendarEvent(
                    institution_id=self.inst,
                    college_id=s.college_id,
                    title=f"Exam: {c.code} {c.title}"[:200],
                    description=f"{s.name} · {p.paper_type} · {p.session_slot}",
                    event_type="exam",
                    starts_at=start,
                    ends_at=start + timedelta(minutes=p.duration_minutes or 180),
                    audience_rules={"course_id": str(c.id), "exam_session_id": str(s.id)},
                    source_type="exam_paper",
                    source_id=p.id,
                    created_by=self.actor_id,
                )
            )
        await self.db.flush()
        await self._audit(
            "publish_date_sheet",
            ENTITY,
            s.id,
            None,
            {
                "force": force,
                "clashes": len(report.items),
                "holidays": len(report.holidays),
                "exceptions": [i.model_dump(mode="json") for i in report.items[:100]] if force else [],
            },
        )
        await self._emit(
            "exams.date_sheet_published", {"exam_session_id": str(s.id), "papers": len(papers)}, ENTITY, s.id
        )
        await self._notify(
            "exams.date_sheet_published", [], {"session": s.name}, audience={"roles": ["student"], "user_ids": []}
        )
        return report

    async def date_sheet_rows(self, sid: uuid.UUID) -> tuple[ExamSession, list[tuple[ExamPaper, Course]]]:
        s = await self.session(sid)
        rows = (
            await self.db.execute(
                select(ExamPaper, Course)
                .join(Course, Course.id == ExamPaper.course_id)
                .where(ExamPaper.exam_session_id == s.id)
                .order_by(ExamPaper.exam_date.nulls_last(), ExamPaper.session_slot, Course.code)
            )
        ).all()
        return s, [(p, c) for p, c in rows]

    async def date_sheet_pdf(self, sid: uuid.UUID) -> bytes:
        from app.utils.pdf import render_pdf

        s, rows = await self.date_sheet_rows(sid)
        inst = await self.institution()
        lines = [inst.name, f"DATE-SHEET — {s.name}", ""]
        lines += [
            f"{p.exam_date.isoformat() if p.exam_date else 'TBA':12s} {p.session_slot or '--':4s} {(p.start_time.strftime('%H:%M') if p.start_time else ''):6s} {c.code:12s} {c.title[:40]} ({p.paper_type})"
            for p, c in rows
        ]
        html = "<html><body>" + "".join(f"<p>{x}</p>" for x in lines) + "</body></html>"
        return render_pdf(html, lines, title=f"Date-sheet {s.name}")

    async def date_sheet_ics(self, sid: uuid.UUID) -> str:
        s, rows = await self.date_sheet_rows(sid)
        from datetime import UTC
        from datetime import time as _t
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Kolkata")
        out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SeptronUniverse//Exams//EN"]
        for p, c in rows:
            if not p.exam_date:
                continue
            start = datetime.combine(p.exam_date, p.start_time or _t(10, 0), tz).astimezone(UTC)
            end = start + timedelta(minutes=p.duration_minutes or 180)
            out += [
                "BEGIN:VEVENT",
                f"UID:{p.id}@septronuniverse",
                f"DTSTAMP:{now_utc().strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
                f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
                f"SUMMARY:{c.code} {c.title[:60]} ({p.paper_type})",
                f"DESCRIPTION:{s.name}",
                "END:VEVENT",
            ]
        out.append("END:VCALENDAR")
        return "\r\n".join(out) + "\r\n"

    # ---- centres ---------------------------------------------------------------------------------------------------------
    async def centres(self, sid: uuid.UUID) -> list[ExamCentreOut]:
        s = await self.session(sid)
        return [
            ExamCentreOut.model_validate(c)
            for c in (
                await self.db.execute(
                    select(ExamCentre).where(ExamCentre.exam_session_id == s.id).order_by(ExamCentre.centre_code)
                )
            ).scalars()
        ]

    async def save_centre(
        self, sid: uuid.UUID | None, body: ExamCentreIn, cid: uuid.UUID | None = None
    ) -> ExamCentreOut:
        data = {**body.model_dump(), "assigned_colleges": [str(x) for x in body.assigned_colleges]}
        if cid:
            c = (
                await self.db.execute(
                    select(ExamCentre)
                    .where(ExamCentre.id == cid, ExamCentre.institution_id == self.inst)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if c is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Centre not found")
            await self.session(c.exam_session_id, write=True)
            for k, v in data.items():
                setattr(c, k, v)
        else:
            s = await self.session(sid, write=True)  # type: ignore[arg-type]
            if s.college_id is not None:
                raise rule("Centres belong to central (university) sessions", "NOT_CENTRAL", 422)
            c = ExamCentre(institution_id=self.inst, exam_session_id=s.id, **data)
            self.db.add(c)
        await self.db.flush()
        return ExamCentreOut.model_validate(c)
