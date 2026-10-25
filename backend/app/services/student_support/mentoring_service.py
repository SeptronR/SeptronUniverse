"""Mentoring — Prompts/27 §27.6 ``mentoring_service`` ({mentoring.core}, {mentoring.appointment_slots},
{mentoring.counselling}).

1. Assignments per term: bulk by rule (``section_advisor`` → the class advisor mentors the section; ``round_robin``
   across the department's faculty by ``ratio``; ``department`` → the listed mentors in order), optional carry-forward
   from a previous term, reassignment with history (``support_meta assignment:{id}``); one row per enrolment per term
   (UNIQUE → 409); mentor load vs ``mentoring.default_ratio``.
2. Mentee 360° for the mentor / class advisor / department & institution readers (404 otherwise): attendance,
   CIA, dues, holds, standing, hostel, risk, sessions, referrals, achievements.
3. Slots: the mentor publishes (optionally weekly recurring) slots; students and guardians book under ``FOR UPDATE``
   on the slot (capacity → 409); cancel / attended / no-show; attended creates a session record.
4. Sessions: notes, concerns, action items with follow-ups (Beat), ``is_confidential`` (notes only for the author
   mentor and counsellors — everyone else sees that a session occurred), ``share_with_guardian`` (guardian summary).
5. Referrals to counselling: mentor / advisor refers, a counsellor (``facilities:counsel``) accepts and books a
   Phase 25 appointment with the student's consent; non-counsellor readers get counts only.
"""

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, true
from sqlalchemy.exc import IntegrityError

from app.models.academic import BatchSection
from app.models.attendance import AttendanceSummary
from app.models.fees import FeeInvoice
from app.models.hostel import HostelAllocation
from app.models.hr import Staff
from app.models.mentoring import (
    CounsellingReferral,
    MentorAssignment,
    MentoringBooking,
    MentoringSession,
    MentoringSlot,
    RiskFlag,
)
from app.models.offerings import CourseOffering
from app.models.post_result import StudentAchievement
from app.models.students import StudentHold, StudentProgramEnrollment, StudentTermRecord
from app.schemas.mentoring import (
    MentActionItemUpdate,
    MentAssignmentCreate,
    MentAssignmentOut,
    MentAssignSummary,
    MentBookingOut,
    MentBulkAssign,
    MentLoadReport,
    MentLoadRow,
    MentMyMentor,
    MentProfile360,
    MentReassign,
    MentReferralCounts,
    MentReferralCreate,
    MentReferralOut,
    MentReferralUpdate,
    MentSessionCreate,
    MentSessionOut,
    MentSessionUpdate,
    MentSlotBook,
    MentSlotCreate,
    MentSlotOut,
)
from app.services.student_support.common import SupportBase, all_access, forbidden, not_found, now_utc, rule

ACTIVE_BOOKING = ("booked", "attended")


class MentoringService(SupportBase):
    audit_module = "mentoring"
    module = "mentoring"

    # ---- helpers ----------------------------------------------------------------------------------------------------
    def is_counsellor(self) -> bool:
        p = self.principal
        return p is not None and (getattr(p, "is_super_admin", False) or p.has("facilities", "counsel"))

    async def _owned_enrolment_predicate(self, col: Any, scope: str | None = None) -> Any:
        """Mentees + advisees (own) widened by department / college / all for readers."""
        if scope in (None, "all") and self.all_access():
            return true()
        parts: list[Any] = []
        staff_id = await self.my_staff_id()
        if staff_id is not None and scope in (None, "own", "mine"):
            parts.append(
                col.in_(
                    select(MentorAssignment.student_program_enrollment_id).where(
                        MentorAssignment.mentor_staff_id == staff_id
                    )
                )
            )
            parts.append(col.in_(self.advisee_subquery(staff_id)))
        parts += self.enrolment_dept_predicate(col, scope)
        return or_(*parts) if parts else None

    async def _can_see_enrolment(self, eid: uuid.UUID) -> str | None:
        """Access label for the 360° view (``mentor`` / ``advisor`` / ``department`` / ``all``) or None."""
        if self.all_access():
            return "all"
        staff_id = await self.my_staff_id()
        if staff_id is not None:
            mentor = (
                await self.db.execute(
                    select(func.count())
                    .select_from(MentorAssignment)
                    .where(
                        MentorAssignment.mentor_staff_id == staff_id,
                        MentorAssignment.student_program_enrollment_id == eid,
                    )
                )
            ).scalar_one()
            if mentor:
                return "mentor"
            adv = (
                await self.db.execute(
                    select(func.count())
                    .select_from(StudentTermRecord)
                    .join(BatchSection, BatchSection.id == StudentTermRecord.section_id)
                    .where(
                        StudentTermRecord.student_program_enrollment_id == eid,
                        BatchSection.class_advisor_staff_id == staff_id,
                    )
                )
            ).scalar_one()
            if adv:
                return "advisor"
        parts = self.enrolment_dept_predicate(StudentProgramEnrollment.id)
        if parts:
            hit = (
                await self.db.execute(
                    select(func.count())
                    .select_from(StudentProgramEnrollment)
                    .where(StudentProgramEnrollment.id == eid, or_(*parts))
                )
            ).scalar_one()
            if hit:
                return "department"
        return None

    async def _assignment(self, aid: uuid.UUID, *, lock: bool = False) -> MentorAssignment:
        stmt = select(MentorAssignment).where(MentorAssignment.id == aid, MentorAssignment.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        a = (await self.db.execute(stmt)).scalar_one_or_none()
        if a is None:
            raise not_found("Assignment")
        return a

    async def assignment_outs(self, rows: list[MentorAssignment]) -> list[MentAssignmentOut]:
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        staff = await self.staff_cards([r.mentor_staff_id for r in rows])
        risks = {
            (f.student_program_enrollment_id, f.term_id): f.level
            for f in (
                await self.db.execute(
                    select(RiskFlag).where(
                        RiskFlag.student_program_enrollment_id.in_(
                            [r.student_program_enrollment_id for r in rows] or [uuid.uuid4()]
                        )
                    )
                )
            ).scalars()
        }
        counts = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(MentoringSession.mentor_assignment_id, func.count())
                    .where(MentoringSession.mentor_assignment_id.in_([r.id for r in rows] or [uuid.uuid4()]))
                    .group_by(MentoringSession.mentor_assignment_id)
                )
            ).all()
        }
        metas = await self.metas("assignment", [r.id for r in rows])
        out = []
        for r in rows:
            c = cards.get(r.student_program_enrollment_id, {})
            out.append(
                MentAssignmentOut(
                    id=r.id,
                    mentor_staff_id=r.mentor_staff_id,
                    mentor_name=staff.get(r.mentor_staff_id, {}).get("name"),
                    student_program_enrollment_id=r.student_program_enrollment_id,
                    student_id=c.get("student_id"),
                    student_name=c.get("name"),
                    registration_number=c.get("registration_number"),
                    department_id=c.get("department_id"),
                    term_id=r.term_id,
                    from_on=r.from_on,
                    to_on=r.to_on,
                    status=r.status,
                    risk_level=risks.get((r.student_program_enrollment_id, r.term_id)),
                    sessions=counts.get(r.id, 0),
                    history=list(metas.get(str(r.id), {}).get("history") or []),
                )
            )
        return out

    # ---- 1. assignments ---------------------------------------------------------------------------------------------
    async def list_assignments(
        self,
        term_id: uuid.UUID | None,
        department_id: uuid.UUID | None = None,
        mentor_id: uuid.UUID | None = None,
        scope: str | None = None,
        limit: int = 500,
    ) -> list[MentAssignmentOut]:
        pred = await self._owned_enrolment_predicate(MentorAssignment.student_program_enrollment_id, scope)
        staff_id = await self.my_staff_id()
        if staff_id is not None and scope in (None, "own", "mine"):
            own = MentorAssignment.mentor_staff_id == staff_id
            pred = own if pred is None else or_(pred, own)
        if pred is None:
            return []
        stmt = select(MentorAssignment).where(MentorAssignment.institution_id == self.inst, pred)
        if term_id:
            stmt = stmt.where(MentorAssignment.term_id == term_id)
        if mentor_id:
            stmt = stmt.where(MentorAssignment.mentor_staff_id == mentor_id)
        if department_id:
            stmt = stmt.where(
                MentorAssignment.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.department_id == department_id)
                )
            )
        rows = (await self.db.execute(stmt.order_by(MentorAssignment.created_at.desc()).limit(limit))).scalars().all()
        return await self.assignment_outs(list(rows))

    async def _require_assign_rights(self) -> None:
        self.require_writer()
        if not (self.all_access() or self.enrolment_dept_predicate(StudentProgramEnrollment.id)):
            raise forbidden("Assigning mentors needs department or institution scope (mentoring:manage)")

    async def create_assignments(self, body: MentAssignmentCreate) -> list[MentAssignmentOut]:
        await self._require_assign_rights()
        term = await self.term_or_current(body.term_id)
        mentor = (await self.db.execute(select(Staff).where(Staff.id == body.mentor_staff_id))).scalar_one_or_none()
        if mentor is None:
            raise not_found("Mentor")
        rows: list[MentorAssignment] = []
        for eid in body.enrollment_ids:
            await self.enrollment(eid)
            dup = (
                await self.db.execute(
                    select(MentorAssignment).where(
                        MentorAssignment.student_program_enrollment_id == eid, MentorAssignment.term_id == term.id
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise rule(
                    "The student already has a mentor this term — reassign instead",
                    "ALREADY_ASSIGNED",
                    enrollment_id=str(eid),
                    assignment_id=str(dup.id),
                )
            a = MentorAssignment(
                institution_id=self.inst,
                mentor_staff_id=mentor.id,
                student_program_enrollment_id=eid,
                term_id=term.id,
                from_on=await self.today(),
                status="active",
            )
            self.db.add(a)
            rows.append(a)
        try:
            await self.db.flush()
        except IntegrityError:
            raise rule("The student already has a mentor this term", "ALREADY_ASSIGNED") from None
        await self._after_assigned(rows)
        return await self.assignment_outs(rows)

    async def _after_assigned(self, rows: list[MentorAssignment]) -> None:
        if not rows:
            return
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        staff = await self.staff_cards([r.mentor_staff_id for r in rows])
        by_mentor: dict[uuid.UUID, int] = defaultdict(int)
        for r in rows:
            by_mentor[r.mentor_staff_id] += 1
            await self._emit(
                "mentoring.assigned",
                {"assignment_id": str(r.id), "mentor_staff_id": str(r.mentor_staff_id), "term_id": str(r.term_id)},
                "mentor_assignment",
                r.id,
            )
            c = cards.get(r.student_program_enrollment_id, {})
            await self._notify(
                "mentoring.assigned",
                [c.get("user_id")],
                {"mentor": staff.get(r.mentor_staff_id, {}).get("name") or "your mentor"},
                guardians=True,
            )
        for mid, n in by_mentor.items():
            await self._notify(
                "mentoring.assigned",
                [staff.get(mid, {}).get("user_id")],
                {"mentor": f"{n} mentee(s) assigned to you"},
            )
        await self._audit("assign", "mentor_assignment", None, None, {"count": len(rows)})

    async def _scope_enrolments(self, body: MentBulkAssign) -> list[StudentProgramEnrollment]:
        stmt = select(StudentProgramEnrollment).where(
            StudentProgramEnrollment.institution_id == self.inst, StudentProgramEnrollment.status == "active"
        )
        sc = body.scope
        if sc.department_id:
            stmt = stmt.where(StudentProgramEnrollment.department_id == sc.department_id)
        if sc.batch_id:
            stmt = stmt.where(StudentProgramEnrollment.batch_id == sc.batch_id)
        if sc.section_id:
            stmt = stmt.where(
                StudentProgramEnrollment.id.in_(
                    select(StudentTermRecord.student_program_enrollment_id).where(
                        StudentTermRecord.section_id == sc.section_id
                    )
                )
            )
        if not self.all_access():
            parts = self.enrolment_dept_predicate(StudentProgramEnrollment.id)
            if not parts:
                return []
            stmt = stmt.where(or_(*parts))
        return list((await self.db.execute(stmt.order_by(StudentProgramEnrollment.id))).scalars().all())

    async def bulk_assign(self, body: MentBulkAssign) -> MentAssignSummary:
        """``mentoring.bulk_assign`` — rule-based allocation; ``preview`` computes without writing."""
        await self._require_assign_rights()
        term = await self.term_or_current(body.term_id)
        ratio = body.ratio or await self.int_setting("mentoring", "default_ratio", 20)
        enrols = await self._scope_enrolments(body)
        existing = {
            r[0]
            for r in (
                await self.db.execute(
                    select(MentorAssignment.student_program_enrollment_id).where(MentorAssignment.term_id == term.id)
                )
            ).all()
        }
        todo = [e for e in enrols if e.id not in existing]
        plan: dict[uuid.UUID, uuid.UUID] = {}
        carry: dict[uuid.UUID, uuid.UUID] = {}
        if body.carry_forward_from_term_id:
            carry = {
                a.student_program_enrollment_id: a.mentor_staff_id
                for a in (
                    await self.db.execute(
                        select(MentorAssignment).where(MentorAssignment.term_id == body.carry_forward_from_term_id)
                    )
                ).scalars()
            }
        for e in todo:
            if e.id in carry:
                plan[e.id] = carry[e.id]
        rest = [e for e in todo if e.id not in plan]
        if body.rule == "section_advisor":
            recs = {
                r.student_program_enrollment_id: r.section_id
                for r in (
                    await self.db.execute(
                        select(StudentTermRecord).where(
                            StudentTermRecord.student_program_enrollment_id.in_([e.id for e in rest] or [uuid.uuid4()]),
                            StudentTermRecord.term_id == term.id,
                        )
                    )
                ).scalars()
            }
            advisors = {
                s.id: s.class_advisor_staff_id
                for s in (
                    await self.db.execute(
                        select(BatchSection).where(
                            BatchSection.id.in_([v for v in recs.values() if v] or [uuid.uuid4()])
                        )
                    )
                ).scalars()
            }
            for e in rest:
                adv = advisors.get(recs.get(e.id))  # type: ignore[arg-type]
                if adv:
                    plan[e.id] = adv
        else:
            by_dept: dict[uuid.UUID, list[StudentProgramEnrollment]] = defaultdict(list)
            for e in rest:
                by_dept[e.department_id].append(e)
            load = {
                k: int(v)
                for k, v in (
                    await self.db.execute(
                        select(MentorAssignment.mentor_staff_id, func.count())
                        .where(MentorAssignment.term_id == term.id)
                        .group_by(MentorAssignment.mentor_staff_id)
                    )
                ).all()
            }
            for dept, items in by_dept.items():
                if body.mentor_staff_ids:
                    mentors = list(body.mentor_staff_ids)
                else:
                    mentors = [
                        r[0]
                        for r in (
                            await self.db.execute(
                                select(Staff.id)
                                .where(
                                    Staff.institution_id == self.inst,
                                    Staff.department_id == dept,
                                    Staff.staff_category == "teaching",
                                    Staff.status == "active",
                                )
                                .order_by(Staff.employee_id)
                            )
                        ).all()
                    ]
                if not mentors:
                    continue
                i = 0
                for e in items:
                    if body.rule == "department":
                        # fill each listed mentor up to the ratio, in order
                        while i < len(mentors) and load.get(mentors[i], 0) >= ratio:
                            i += 1
                        if i >= len(mentors):
                            break
                        m = mentors[i]
                    else:
                        cands = [m for m in mentors if load.get(m, 0) < ratio] or mentors
                        m = min(cands, key=lambda x: load.get(x, 0))
                    plan[e.id] = m
                    load[m] = load.get(m, 0) + 1
        per_mentor: dict[str, int] = defaultdict(int)
        for m in plan.values():
            per_mentor[str(m)] += 1
        summary = MentAssignSummary(
            term_id=term.id,
            rule=body.rule,
            students=len(enrols),
            assigned=len(plan),
            skipped_existing=len(enrols) - len(todo),
            mentors=len(set(plan.values())),
            unassigned=len(todo) - len(plan),
            preview=body.preview,
            per_mentor=dict(per_mentor),
        )
        if body.preview:
            return summary
        today = await self.today()
        rows = []
        for eid, mid in plan.items():
            a = MentorAssignment(
                institution_id=self.inst,
                mentor_staff_id=mid,
                student_program_enrollment_id=eid,
                term_id=term.id,
                from_on=today,
                status="active",
            )
            self.db.add(a)
            rows.append(a)
        await self.db.flush()
        await self._after_assigned(rows)
        return summary

    async def reassign(self, aid: uuid.UUID, body: MentReassign) -> MentAssignmentOut:
        await self._require_assign_rights()
        a = await self._assignment(aid, lock=True)
        if a.mentor_staff_id == body.mentor_staff_id:
            raise rule("The student already has this mentor", "SAME_MENTOR")
        if (
            await self.db.execute(select(Staff.id).where(Staff.id == body.mentor_staff_id))
        ).scalar_one_or_none() is None:
            raise not_found("Mentor")
        m = await self.meta("assignment", a.id)
        hist = list(m.get("history") or [])
        hist.append(
            {
                "from_mentor": str(a.mentor_staff_id),
                "to_mentor": str(body.mentor_staff_id),
                "reason": body.reason,
                "at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
            }
        )
        m["history"] = hist
        await self.put_meta("assignment", a.id, m)
        old = a.mentor_staff_id
        a.mentor_staff_id, a.from_on = body.mentor_staff_id, await self.today()
        await self.db.flush()
        await self._audit(
            "reassign",
            "mentor_assignment",
            a.id,
            {"mentor_staff_id": str(old)},
            {"mentor_staff_id": str(a.mentor_staff_id)},
        )
        await self._emit(
            "mentoring.reassigned",
            {"assignment_id": str(a.id), "from": str(old), "to": str(a.mentor_staff_id)},
            "mentor_assignment",
            a.id,
        )
        return (await self.assignment_outs([a]))[0]

    async def load(self, term_id: uuid.UUID | None) -> MentLoadReport:
        term = await self.term_or_current(term_id)
        ratio = await self.int_setting("mentoring", "default_ratio", 20)
        min_sessions = await self.int_setting("mentoring", "min_sessions_per_term", 2)
        pred = await self._owned_enrolment_predicate(MentorAssignment.student_program_enrollment_id)
        if pred is None:
            raise forbidden("mentoring:view_all required")
        rows = (
            (
                await self.db.execute(
                    select(MentorAssignment).where(
                        MentorAssignment.institution_id == self.inst, MentorAssignment.term_id == term.id, pred
                    )
                )
            )
            .scalars()
            .all()
        )
        sess = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(MentoringSession.mentor_assignment_id, func.count())
                    .where(MentoringSession.mentor_assignment_id.in_([r.id for r in rows] or [uuid.uuid4()]))
                    .group_by(MentoringSession.mentor_assignment_id)
                )
            ).all()
        }
        staff = await self.staff_cards([r.mentor_staff_id for r in rows])
        agg: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: {"mentees": 0, "sessions": 0, "compliant": 0})
        for r in rows:
            g = agg[r.mentor_staff_id]
            g["mentees"] += 1
            n = sess.get(r.id, 0)
            g["sessions"] += n
            g["compliant"] += 1 if n >= min_sessions else 0
        out = [
            MentLoadRow(
                mentor_staff_id=mid,
                mentor_name=staff.get(mid, {}).get("name"),
                department_id=staff.get(mid, {}).get("department_id"),
                mentees=g["mentees"],
                sessions=g["sessions"],
                compliant_mentees=g["compliant"],
                over_ratio=g["mentees"] > ratio,
            )
            for mid, g in agg.items()
        ]
        out.sort(key=lambda x: -x.mentees)
        active_q = (
            select(func.count())
            .select_from(StudentProgramEnrollment)
            .where(StudentProgramEnrollment.institution_id == self.inst, StudentProgramEnrollment.status == "active")
        )
        if not self.all_access():
            parts = self.enrolment_dept_predicate(StudentProgramEnrollment.id)
            if parts:
                active_q = active_q.where(or_(*parts))
        active = int((await self.db.execute(active_q)).scalar_one() or 0)
        compliant = sum(g["compliant"] for g in agg.values())
        return MentLoadReport(
            term_id=term.id,
            default_ratio=ratio,
            min_sessions=min_sessions,
            rows=out,
            coverage_pct=round(100.0 * len(rows) / active, 1) if active else 0.0,
            compliance_pct=round(100.0 * compliant / len(rows), 1) if rows else 0.0,
        )

    async def my_mentor(self) -> MentMyMentor:
        e = await self.my_enrollment()
        if e is None:
            raise rule("Your account is not linked to an enrolment", "NO_ENROLMENT")
        return await self._mentor_card(e.id)

    async def ward_mentors(self) -> list[MentMyMentor]:
        return [await self._mentor_card(eid) for eid in await self.ward_enrollment_ids()]

    async def _mentor_card(self, eid: uuid.UUID) -> MentMyMentor:
        a = (
            await self.db.execute(
                select(MentorAssignment)
                .where(MentorAssignment.student_program_enrollment_id == eid, MentorAssignment.status == "active")
                .order_by(MentorAssignment.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if a is None:
            return MentMyMentor()
        s = (await self.staff_cards([a.mentor_staff_id])).get(a.mentor_staff_id, {})
        slots = await self.available_slots(a.mentor_staff_id)
        items: list[dict[str, Any]] = []
        for ses in (
            await self.db.execute(
                select(MentoringSession).where(
                    MentoringSession.mentor_assignment_id == a.id, MentoringSession.is_confidential.is_(False)
                )
            )
        ).scalars():
            for idx, it in enumerate(ses.action_items or []):
                if not it.get("done"):
                    items.append({**it, "session_id": str(ses.id), "index": idx})
        return MentMyMentor(
            assignment_id=a.id,
            term_id=a.term_id,
            mentor_staff_id=a.mentor_staff_id,
            mentor_name=s.get("name"),
            mentor_email=s.get("email"),
            mentor_phone=s.get("phone"),
            next_slots=slots[:10],
            open_action_items=items,
        )

    async def mentees(self, term_id: uuid.UUID | None) -> list[MentAssignmentOut]:
        staff_id = await self.my_staff_id()
        if staff_id is None:
            raise forbidden("Mentees are listed for staff")
        stmt = select(MentorAssignment).where(
            MentorAssignment.institution_id == self.inst,
            or_(
                MentorAssignment.mentor_staff_id == staff_id,
                MentorAssignment.student_program_enrollment_id.in_(self.advisee_subquery(staff_id)),
            ),
        )
        term = await self.term_or_current(term_id) if term_id else await self.current_term(None)
        if term is not None:
            stmt = stmt.where(MentorAssignment.term_id == term.id)
        rows = (await self.db.execute(stmt.order_by(MentorAssignment.created_at))).scalars().all()
        return await self.assignment_outs(list(rows))

    # ---- 2. 360° ----------------------------------------------------------------------------------------------------
    async def profile360(self, eid: uuid.UUID) -> MentProfile360:
        access = await self._can_see_enrolment(eid)
        if access is None:
            raise not_found("Mentee")
        e = await self.enrollment(eid)
        card = (await self.enrollment_cards([eid])).get(eid, {})
        term = await self.current_term(e.college_id)
        att_rows = (
            await self.db.execute(
                select(AttendanceSummary, CourseOffering)
                .join(CourseOffering, CourseOffering.id == AttendanceSummary.offering_id)
                .where(
                    AttendanceSummary.student_program_enrollment_id == eid,
                    *([CourseOffering.term_id == term.id] if term else []),
                )
            )
        ).all()
        attendance = [
            {
                "offering_id": str(o.id),
                "section": o.section_code,
                "pct": float(a.pct or 0),
                "eligibility": a.eligibility,
            }
            for a, o in att_rows
        ]
        att_pct = round(sum(x["pct"] for x in attendance) / len(attendance), 1) if attendance else None
        from app.models.assessment import CiaConsolidation

        cia_rows = (
            (
                await self.db.execute(
                    select(CiaConsolidation).where(CiaConsolidation.student_program_enrollment_id == eid)
                )
            )
            .scalars()
            .all()
        )
        cia = {
            "offerings": len(cia_rows),
            "avg_scaled": round(sum(float(c.cia_scaled or 0) for c in cia_rows) / len(cia_rows), 1)
            if cia_rows
            else None,
            "items": [
                {"offering_id": str(c.offering_id), "cia_scaled": float(c.cia_scaled or 0), "status": c.status}
                for c in cia_rows[:20]
            ],
        }
        today = await self.today()
        inv = (
            (
                await self.db.execute(
                    select(FeeInvoice).where(
                        FeeInvoice.student_program_enrollment_id == eid,
                        FeeInvoice.status.in_(("pending", "partial", "overdue")),
                    )
                )
            )
            .scalars()
            .all()
        )
        dues = {
            "outstanding_paise": sum(i.balance_paise or 0 for i in inv),
            "overdue_paise": sum(i.balance_paise or 0 for i in inv if i.due_date and i.due_date < today),
            "invoices": len(inv),
        }
        holds = [
            {"id": str(h.id), "hold_type": h.hold_type, "reason": h.reason, "placed_at": h.placed_at.isoformat()}
            for h in (
                await self.db.execute(
                    select(StudentHold).where(
                        StudentHold.student_program_enrollment_id == eid, StudentHold.released_at.is_(None)
                    )
                )
            ).scalars()
        ]
        alloc = (
            await self.db.execute(
                select(HostelAllocation)
                .where(HostelAllocation.student_program_enrollment_id == eid, HostelAllocation.status == "active")
                .limit(1)
            )
        ).scalar_one_or_none()
        hostel = (
            {"hostel_id": str(alloc.hostel_id), "bed_id": str(alloc.bed_id), "from_on": alloc.from_on.isoformat()}
            if alloc
            else None
        )
        flag = (
            await self.db.execute(
                select(RiskFlag)
                .where(RiskFlag.student_program_enrollment_id == eid)
                .order_by(RiskFlag.computed_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        risk = (
            {
                "level": flag.level,
                "score": float(flag.score),
                "factors": flag.factors,
                "acknowledged": bool(flag.acknowledged_at),
            }
            if flag
            else None
        )
        sess_rows = (
            (
                await self.db.execute(
                    select(MentoringSession)
                    .join(MentorAssignment, MentorAssignment.id == MentoringSession.mentor_assignment_id)
                    .where(MentorAssignment.student_program_enrollment_id == eid)
                    .order_by(MentoringSession.held_on.desc())
                )
            )
            .scalars()
            .all()
        )
        sessions = await self.session_outs(list(sess_rows))
        refs = (
            (
                await self.db.execute(
                    select(CounsellingReferral).where(CounsellingReferral.student_program_enrollment_id == eid)
                )
            )
            .scalars()
            .all()
        )
        achievements = [
            {"id": str(a.id), "title": a.title, "category": a.category, "verified": a.verified_at is not None}
            for a in (
                await self.db.execute(
                    select(StudentAchievement).where(StudentAchievement.student_program_enrollment_id == eid)
                )
            ).scalars()
        ]
        return MentProfile360(
            enrollment_id=eid,
            student={k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in card.items() if k != "user_id"},
            attendance_pct=att_pct,
            attendance=attendance,
            cia_summary=cia,
            dues=dues,
            holds=holds,
            standing=e.academic_standing,
            hostel=hostel,
            risk=risk,
            sessions=sessions,
            referrals=await self.referral_outs(list(refs), detail=self.is_counsellor()),
            achievements=achievements,
            access=access,
        )

    # ---- 3. slots ---------------------------------------------------------------------------------------------------
    async def slot_outs(self, rows: list[MentoringSlot], *, with_bookings: bool = False) -> list[MentSlotOut]:
        staff = await self.staff_cards([r.mentor_staff_id for r in rows])
        books = (
            (
                await self.db.execute(
                    select(MentoringBooking).where(MentoringBooking.slot_id.in_([r.id for r in rows] or [uuid.uuid4()]))
                )
            )
            .scalars()
            .all()
        )
        by_slot: dict[uuid.UUID, list[MentoringBooking]] = defaultdict(list)
        for b in books:
            by_slot[b.slot_id].append(b)
        out = []
        for r in rows:
            active = [b for b in by_slot.get(r.id, []) if b.status in ACTIVE_BOOKING]
            o = MentSlotOut(
                id=r.id,
                mentor_staff_id=r.mentor_staff_id,
                mentor_name=staff.get(r.mentor_staff_id, {}).get("name"),
                starts_at=r.starts_at,
                ends_at=r.ends_at,
                capacity=r.capacity,
                booked=len(active),
                location=r.location,
            )
            if with_bookings:
                o.bookings = await self.booking_outs(by_slot.get(r.id, []), {r.id: r})
            out.append(o)
        return out

    async def booking_outs(
        self, rows: list[MentoringBooking], slots: dict[uuid.UUID, MentoringSlot] | None = None
    ) -> list[MentBookingOut]:
        if slots is None:
            slots = {
                s.id: s
                for s in (
                    await self.db.execute(
                        select(MentoringSlot).where(MentoringSlot.id.in_([r.slot_id for r in rows] or [uuid.uuid4()]))
                    )
                ).scalars()
            }
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        users = await self.user_display([r.guardian_user_id for r in rows])
        return [
            MentBookingOut(
                id=r.id,
                slot_id=r.slot_id,
                starts_at=slots[r.slot_id].starts_at if r.slot_id in slots else None,
                student_program_enrollment_id=r.student_program_enrollment_id,
                student_name=cards.get(r.student_program_enrollment_id, {}).get("name")
                if r.student_program_enrollment_id
                else None,
                guardian_user_id=r.guardian_user_id,
                guardian_name=users.get(r.guardian_user_id) if r.guardian_user_id else None,
                status=r.status,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def publish_slots(self, body: MentSlotCreate) -> list[MentSlotOut]:
        self.require_writer()
        staff_id = await self.my_staff_id()
        if staff_id is None:
            raise forbidden("Mentors publish their own slots")
        rows = []
        for w in range(body.repeat_weeks + 1):
            start, end = body.starts_at + timedelta(weeks=w), body.ends_at + timedelta(weeks=w)
            clash = (
                await self.db.execute(
                    select(func.count())
                    .select_from(MentoringSlot)
                    .where(
                        MentoringSlot.mentor_staff_id == staff_id,
                        MentoringSlot.starts_at < end,
                        MentoringSlot.ends_at > start,
                    )
                )
            ).scalar_one()
            if clash:
                continue
            s = MentoringSlot(
                institution_id=self.inst,
                mentor_staff_id=staff_id,
                starts_at=start,
                ends_at=end,
                capacity=body.capacity,
                location=body.location,
            )
            self.db.add(s)
            rows.append(s)
        await self.db.flush()
        await self._audit("publish", "mentoring_slot", None, None, {"count": len(rows)})
        return await self.slot_outs(rows)

    async def my_slots(self) -> list[MentSlotOut]:
        staff_id = await self.my_staff_id()
        if staff_id is None:
            raise forbidden("Slots are published by mentors")
        rows = (
            (
                await self.db.execute(
                    select(MentoringSlot)
                    .where(
                        MentoringSlot.mentor_staff_id == staff_id,
                        MentoringSlot.starts_at >= now_utc() - timedelta(days=14),
                    )
                    .order_by(MentoringSlot.starts_at)
                )
            )
            .scalars()
            .all()
        )
        return await self.slot_outs(list(rows), with_bookings=True)

    async def delete_slot(self, sid: uuid.UUID) -> None:
        s = await self._slot(sid)
        if s.mentor_staff_id != await self.my_staff_id() and not self.all_access():
            raise not_found("Slot")
        booked = (
            await self.db.execute(
                select(func.count())
                .select_from(MentoringBooking)
                .where(MentoringBooking.slot_id == s.id, MentoringBooking.status == "booked")
            )
        ).scalar_one()
        if booked:
            raise rule("The slot has bookings — cancel them first", "SLOT_BOOKED")
        await self.db.delete(s)
        await self.db.flush()

    async def available_slots(self, mentor_id: uuid.UUID | None) -> list[MentSlotOut]:
        if mentor_id is None:
            card = await self.my_mentor() if await self.my_student() else MentMyMentor()
            mentor_id = card.mentor_staff_id
            if mentor_id is None:
                return []
        rows = (
            (
                await self.db.execute(
                    select(MentoringSlot)
                    .where(
                        MentoringSlot.institution_id == self.inst,
                        MentoringSlot.mentor_staff_id == mentor_id,
                        MentoringSlot.starts_at >= now_utc(),
                    )
                    .order_by(MentoringSlot.starts_at)
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        outs = await self.slot_outs(list(rows))
        return [o for o in outs if o.booked < o.capacity]

    async def _slot(self, sid: uuid.UUID, *, lock: bool = False) -> MentoringSlot:
        stmt = select(MentoringSlot).where(MentoringSlot.id == sid, MentoringSlot.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        s = (await self.db.execute(stmt)).scalar_one_or_none()
        if s is None:
            raise not_found("Slot")
        return s

    async def book(self, sid: uuid.UUID, body: MentSlotBook) -> MentBookingOut:
        self.require_writer()
        slot = await self._slot(sid, lock=True)
        if slot.starts_at < now_utc():
            raise rule("The slot has already started", "SLOT_PAST")
        enrol_id: uuid.UUID | None = None
        guardian: uuid.UUID | None = None
        mine = await self.my_enrollment()
        if mine is not None and (body.enrollment_id in (None, mine.id)):
            enrol_id = mine.id
        else:
            wards = await self.ward_enrollment_ids()
            target = body.enrollment_id or (wards[0] if len(wards) == 1 else None)
            if target is None or target not in wards:
                raise forbidden("Book for yourself or for your ward")
            enrol_id, guardian = target, self.actor_id
        taken = (
            (
                await self.db.execute(
                    select(MentoringBooking).where(
                        MentoringBooking.slot_id == slot.id, MentoringBooking.status.in_(ACTIVE_BOOKING)
                    )
                )
            )
            .scalars()
            .all()
        )
        if any(b.student_program_enrollment_id == enrol_id and b.guardian_user_id == guardian for b in taken):
            raise rule("You already booked this slot", "ALREADY_BOOKED")
        if len(taken) >= slot.capacity:
            raise rule("The slot is full", "SLOT_FULL")
        b = MentoringBooking(
            institution_id=self.inst,
            slot_id=slot.id,
            student_program_enrollment_id=enrol_id,
            guardian_user_id=guardian,
            status="booked",
        )
        self.db.add(b)
        await self.db.flush()
        if body.note:
            await self.put_meta("booking", b.id, {"note": body.note})
        await self._emit(
            "mentoring.slot_booked", {"booking_id": str(b.id), "slot_id": str(slot.id)}, "mentoring_booking", b.id
        )
        await self._notify(
            "mentoring.meeting_scheduled",
            [await self.staff_user(slot.mentor_staff_id), self.actor_id],
            {"date": slot.starts_at.date().isoformat(), "time": slot.starts_at.strftime("%H:%M")},
        )
        return (await self.booking_outs([b], {slot.id: slot}))[0]

    async def booking_action(self, bid: uuid.UUID, action: str) -> MentBookingOut:
        b = (
            await self.db.execute(
                select(MentoringBooking)
                .where(MentoringBooking.id == bid, MentoringBooking.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if b is None:
            raise not_found("Booking")
        slot = await self._slot(b.slot_id)
        is_mentor = slot.mentor_staff_id == await self.my_staff_id()
        mine = await self.my_enrollment()
        is_booker = (b.guardian_user_id is not None and b.guardian_user_id == self.actor_id) or (
            b.guardian_user_id is None and mine is not None and b.student_program_enrollment_id == mine.id
        )
        if not (is_mentor or is_booker):
            raise not_found("Booking")
        if b.status != "booked":
            raise rule("Only a booked appointment is updated", "NOT_BOOKED")
        if action == "cancel":
            b.status = "cancelled"
            await self._emit("mentoring.slot_cancelled", {"booking_id": str(b.id)}, "mentoring_booking", b.id)
        else:
            if not is_mentor:
                raise forbidden("The mentor marks attendance")
            b.status = "attended" if action == "attended" else "no_show"
            if action == "no-show":
                await self._emit("mentoring.no_show", {"booking_id": str(b.id)}, "mentoring_booking", b.id)
            elif b.student_program_enrollment_id:
                a = (
                    await self.db.execute(
                        select(MentorAssignment)
                        .where(
                            MentorAssignment.student_program_enrollment_id == b.student_program_enrollment_id,
                            MentorAssignment.mentor_staff_id == slot.mentor_staff_id,
                        )
                        .order_by(MentorAssignment.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if a is not None:
                    self.db.add(
                        MentoringSession(
                            institution_id=self.inst,
                            mentor_assignment_id=a.id,
                            held_on=slot.starts_at.date(),
                            mode="in_person",
                            notes=None,
                            concerns={
                                "items": [],
                                "booking_id": str(b.id),
                                "with_guardian": b.guardian_user_id is not None,
                            },
                            action_items=[],
                        )
                    )
        await self.db.flush()
        return (await self.booking_outs([b], {slot.id: slot}))[0]

    # ---- 4. sessions ------------------------------------------------------------------------------------------------
    async def session_outs(self, rows: list[MentoringSession], *, viewer: str | None = None) -> list[MentSessionOut]:
        """``viewer``: None (staff — notes only for the author mentor / counsellors), ``student`` or ``guardian``."""
        assigns = {
            a.id: a
            for a in (
                await self.db.execute(
                    select(MentorAssignment).where(
                        MentorAssignment.id.in_([r.mentor_assignment_id for r in rows] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        cards = await self.enrollment_cards([a.student_program_enrollment_id for a in assigns.values()])
        staff = await self.staff_cards([a.mentor_staff_id for a in assigns.values()])
        me = await self.my_staff_id()
        counsellor = self.is_counsellor()
        out = []
        for r in rows:
            a = assigns.get(r.mentor_assignment_id)
            meta = r.concerns or {}
            share = bool(meta.get("share_with_guardian"))
            o = MentSessionOut(
                id=r.id,
                assignment_id=r.mentor_assignment_id,
                student_program_enrollment_id=a.student_program_enrollment_id if a else None,
                student_name=cards.get(a.student_program_enrollment_id, {}).get("name") if a else None,
                mentor_name=staff.get(a.mentor_staff_id, {}).get("name") if a else None,
                held_on=r.held_on,
                mode=r.mode,
                is_confidential=r.is_confidential,
                follow_up_on=r.follow_up_on,
                share_with_guardian=share,
            )
            author = a is not None and me is not None and a.mentor_staff_id == me
            full = author or counsellor
            if viewer == "guardian":
                o.guardian_summary = meta.get("guardian_summary") if share and not r.is_confidential else None
                o.redacted = True
            elif viewer == "student":
                if r.is_confidential:
                    o.redacted = True
                else:
                    o.notes, o.action_items = r.notes, list(r.action_items or [])
                    o.concerns = list(meta.get("items") or [])
            elif full or not r.is_confidential:
                if full or not self._auditor_only():
                    o.notes = r.notes
                o.concerns = list(meta.get("items") or [])
                o.action_items = list(r.action_items or [])
                o.guardian_summary = meta.get("guardian_summary")
            else:
                o.redacted = True
            out.append(o)
        return out

    def _auditor_only(self) -> bool:
        from app.services.student_support.common import is_auditor

        return is_auditor(self.principal)

    async def _own_assignment(self, aid: uuid.UUID) -> MentorAssignment:
        a = await self._assignment(aid)
        if a.mentor_staff_id != await self.my_staff_id() and not self.all_access():
            raise not_found("Assignment")
        return a

    async def log_session(self, body: MentSessionCreate) -> MentSessionOut:
        self.require_writer()
        a = await self._own_assignment(body.assignment_id)
        s = MentoringSession(
            institution_id=self.inst,
            mentor_assignment_id=a.id,
            held_on=body.held_on,
            mode=body.mode,
            notes=body.notes,
            concerns={
                "items": list(body.concerns),
                "share_with_guardian": body.share_with_guardian,
                "guardian_summary": body.guardian_summary,
                "booking_id": str(body.booking_id) if body.booking_id else None,
            },
            action_items=[i.model_dump(mode="json") for i in body.action_items],
            follow_up_on=body.follow_up_on,
            is_confidential=body.is_confidential,
        )
        self.db.add(s)
        await self.db.flush()
        await self._emit(
            "mentoring.session_logged",
            {"session_id": str(s.id), "assignment_id": str(a.id), "confidential": s.is_confidential},
            "mentoring_session",
            s.id,
        )
        await self._audit("log", "mentoring_session", s.id, None, {"confidential": s.is_confidential})
        if body.share_with_guardian and not body.is_confidential:
            await self._notify(
                "mentoring.meeting_scheduled",
                await self.guardian_users(a.student_program_enrollment_id),
                {"date": body.held_on.isoformat(), "time": "—"},
            )
        return (await self.session_outs([s]))[0]

    async def _session(self, sid: uuid.UUID) -> tuple[MentoringSession, MentorAssignment]:
        s = (
            await self.db.execute(
                select(MentoringSession).where(MentoringSession.id == sid, MentoringSession.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None:
            raise not_found("Session")
        a = await self._assignment(s.mentor_assignment_id)
        return s, a

    async def update_session(self, sid: uuid.UUID, body: MentSessionUpdate) -> MentSessionOut:
        self.require_writer()
        s, a = await self._session(sid)
        if a.mentor_staff_id != await self.my_staff_id():
            raise not_found("Session")
        data = body.model_dump(exclude_unset=True)
        meta = dict(s.concerns or {})
        for k in ("held_on", "mode", "notes", "follow_up_on", "is_confidential"):
            if k in data:
                setattr(s, k, data[k])
        if "concerns" in data:
            meta["items"] = data["concerns"]
        if "share_with_guardian" in data:
            meta["share_with_guardian"] = data["share_with_guardian"]
        if "guardian_summary" in data:
            meta["guardian_summary"] = data["guardian_summary"]
        s.concerns = meta
        if body.action_items is not None:
            s.action_items = [i.model_dump(mode="json") for i in body.action_items]
        await self.db.flush()
        return (await self.session_outs([s]))[0]

    async def update_action_item(self, sid: uuid.UUID, idx: int, body: MentActionItemUpdate) -> MentSessionOut:
        s, a = await self._session(sid)
        mine = await self.my_enrollment()
        is_mentor = a.mentor_staff_id == await self.my_staff_id()
        is_student = mine is not None and mine.id == a.student_program_enrollment_id and not s.is_confidential
        if not (is_mentor or is_student):
            raise not_found("Session")
        items = list(s.action_items or [])
        if idx < 0 or idx >= len(items):
            raise not_found("Action item")
        items[idx] = {**items[idx], "done": body.done, "done_at": now_utc().isoformat() if body.done else None}
        s.action_items = items
        await self.db.flush()
        return (await self.session_outs([s], viewer=None if is_mentor else "student"))[0]

    async def list_sessions(self, assignment_id: uuid.UUID | None, scope: str | None = None) -> list[MentSessionOut]:
        pred = await self._owned_enrolment_predicate(MentorAssignment.student_program_enrollment_id, scope)
        if pred is None:
            raise forbidden("mentoring:manage required")
        stmt = (
            select(MentoringSession)
            .join(MentorAssignment, MentorAssignment.id == MentoringSession.mentor_assignment_id)
            .where(MentoringSession.institution_id == self.inst, pred)
        )
        if assignment_id:
            stmt = stmt.where(MentoringSession.mentor_assignment_id == assignment_id)
        rows = (await self.db.execute(stmt.order_by(MentoringSession.held_on.desc()).limit(500))).scalars().all()
        return await self.session_outs(list(rows))

    async def my_sessions(self) -> list[MentSessionOut]:
        ids = await self.my_enrollment_ids()
        viewer = "student"
        if not ids:
            ids = await self.ward_enrollment_ids()
            viewer = "guardian"
        if not ids:
            return []
        rows = (
            (
                await self.db.execute(
                    select(MentoringSession)
                    .join(MentorAssignment, MentorAssignment.id == MentoringSession.mentor_assignment_id)
                    .where(MentorAssignment.student_program_enrollment_id.in_(ids))
                    .order_by(MentoringSession.held_on.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.session_outs(list(rows), viewer=viewer)

    async def follow_up_reminders(self) -> int:
        """Beat ``mentoring.follow_up_reminders`` — follow-ups and action items due today."""
        today = await self.today()
        rows = (
            await self.db.execute(
                select(MentoringSession, MentorAssignment)
                .join(MentorAssignment, MentorAssignment.id == MentoringSession.mentor_assignment_id)
                .where(MentoringSession.institution_id == self.inst)
                .where(
                    or_(
                        MentoringSession.follow_up_on == today,
                        MentoringSession.action_items.is_not(None),
                    )
                )
            )
        ).all()
        n = 0
        for s, a in rows:
            due = s.follow_up_on == today or any(
                (not it.get("done")) and it.get("due_on") == today.isoformat() for it in (s.action_items or [])
            )
            if not due:
                continue
            n += 1
            card = (await self.enrollment_cards([a.student_program_enrollment_id])).get(
                a.student_program_enrollment_id, {}
            )
            await self._emit("mentoring.follow_up_due", {"session_id": str(s.id)}, "mentoring_session", s.id)
            await self._notify(
                "mentoring.follow_up_due",
                [await self.staff_user(a.mentor_staff_id)] + ([card.get("user_id")] if not s.is_confidential else []),
                {"student": card.get("name") or "", "date": today.isoformat()},
            )
        return n

    async def min_sessions_check(self) -> int:
        """Beat ``mentoring.min_sessions_check`` (monthly) — mentors below the minimum sessions per mentee."""
        term = await self.current_term(None)
        if term is None:
            return 0
        min_sessions = await self.int_setting("mentoring", "min_sessions_per_term", 2)
        rows = (
            await self.db.execute(
                select(MentorAssignment.mentor_staff_id, MentorAssignment.id, func.count(MentoringSession.id))
                .outerjoin(MentoringSession, MentoringSession.mentor_assignment_id == MentorAssignment.id)
                .where(MentorAssignment.term_id == term.id, MentorAssignment.status == "active")
                .group_by(MentorAssignment.mentor_staff_id, MentorAssignment.id)
            )
        ).all()
        behind: dict[uuid.UUID, int] = defaultdict(int)
        for mid, _aid, n in rows:
            if int(n) < min_sessions:
                behind[mid] += 1
        for mid, count in behind.items():
            await self._notify(
                "mentoring.follow_up_due",
                [await self.staff_user(mid)],
                {
                    "student": f"{count} mentee(s) below {min_sessions} sessions",
                    "date": (await self.today()).isoformat(),
                },
            )
        return len(behind)

    # ---- 5. referrals -----------------------------------------------------------------------------------------------
    async def referral_outs(self, rows: list[CounsellingReferral], *, detail: bool) -> list[MentReferralOut]:
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        staff = await self.staff_cards([r.counsellor_staff_id for r in rows])
        metas = await self.metas("referral", [r.id for r in rows]) if detail else {}
        out = []
        for r in rows:
            o = MentReferralOut(id=r.id, status=r.status, created_at=r.created_at)
            mine = self.actor_id is not None and r.referred_by == self.actor_id
            if detail or mine:
                o.student_program_enrollment_id = r.student_program_enrollment_id
                o.student_name = cards.get(r.student_program_enrollment_id, {}).get("name")
                o.counsellor_staff_id = r.counsellor_staff_id
                o.counsellor_name = staff.get(r.counsellor_staff_id, {}).get("name") if r.counsellor_staff_id else None
                o.referred_by = r.referred_by
            if detail:
                o.reason = r.reason
                appt = metas.get(str(r.id), {}).get("appointment_id")
                o.appointment_id = uuid.UUID(appt) if appt else None
            out.append(o)
        return out

    async def refer(self, body: MentReferralCreate) -> MentReferralOut:
        self.require_writer()
        access = await self._can_see_enrolment(body.enrollment_id)
        if access is None:
            raise not_found("Student")
        r = CounsellingReferral(
            institution_id=self.inst,
            student_program_enrollment_id=body.enrollment_id,
            referred_by=self.actor_id or uuid.UUID(int=0),
            counsellor_staff_id=body.counsellor_staff_id,
            reason=body.reason,
            status="referred",
            is_confidential=True,
        )
        self.db.add(r)
        await self.db.flush()
        await self._emit("mentoring.referral_created", {"referral_id": str(r.id)}, "counselling_referral", r.id)
        if body.counsellor_staff_id:
            await self._notify(
                "mentoring.follow_up_due",
                [await self.staff_user(body.counsellor_staff_id)],
                {"student": "a new counselling referral", "date": (await self.today()).isoformat()},
            )
        return (await self.referral_outs([r], detail=False))[0]

    async def list_referrals(
        self, status: str | None, mine: bool = False
    ) -> list[MentReferralOut] | MentReferralCounts:
        base = select(CounsellingReferral).where(CounsellingReferral.institution_id == self.inst)
        if status:
            base = base.where(CounsellingReferral.status == status)
        if self.is_counsellor() and not mine:
            me = await self.my_staff_id()
            rows = (
                (
                    await self.db.execute(
                        base.where(
                            or_(
                                CounsellingReferral.counsellor_staff_id == me,
                                CounsellingReferral.counsellor_staff_id.is_(None),
                            )
                        ).order_by(CounsellingReferral.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            return await self.referral_outs(list(rows), detail=True)
        tabs = self.visibility(self_tab=False, own_tab=False)["scopes"]
        if tabs and not mine:
            counts_q = select(CounsellingReferral.status, func.count()).where(
                CounsellingReferral.institution_id == self.inst
            )
            if not all_access(self.principal, self.module):
                parts = self.enrolment_dept_predicate(CounsellingReferral.student_program_enrollment_id)
                if parts:
                    counts_q = counts_q.where(or_(*parts))
            by = {s: int(n) for s, n in (await self.db.execute(counts_q.group_by(CounsellingReferral.status))).all()}
            return MentReferralCounts(by_status=by, total=sum(by.values()))
        rows = (
            (
                await self.db.execute(
                    base.where(CounsellingReferral.referred_by == self.actor_id).order_by(
                        CounsellingReferral.created_at.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.referral_outs(list(rows), detail=False)

    async def update_referral(self, rid: uuid.UUID, body: MentReferralUpdate) -> MentReferralOut:
        if not self.is_counsellor():
            raise forbidden("Counsellors update referrals (facilities:counsel)")
        r = (
            await self.db.execute(
                select(CounsellingReferral)
                .where(CounsellingReferral.id == rid, CounsellingReferral.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Referral")
        me = await self.my_staff_id()
        if r.counsellor_staff_id not in (None, me) and not self.all_access("facilities"):
            raise not_found("Referral")
        r.counsellor_staff_id = body.counsellor_staff_id or r.counsellor_staff_id or me
        meta = await self.meta("referral", r.id)
        if body.appointment_slot_id:
            if not body.student_consent:
                raise rule("Booking an appointment needs the student's consent", "CONSENT_REQUIRED")
            from app.services.facilities.counselling_service import CounsellingService

            card = (await self.enrollment_cards([r.student_program_enrollment_id])).get(
                r.student_program_enrollment_id, {}
            )
            appt = await CounsellingService(self.db, self.principal, self.request, self.inst).book_for(
                body.appointment_slot_id, "student", card["student_id"]
            )
            meta["appointment_id"] = str(appt.id)
            r.status = "scheduled"
        if body.status:
            r.status = body.status
        if body.note:
            meta.setdefault("notes", []).append({"at": now_utc().isoformat(), "note": body.note})
        await self.put_meta("referral", r.id, meta)
        await self.db.flush()
        await self._emit(
            "mentoring.referral_updated", {"referral_id": str(r.id), "status": r.status}, "counselling_referral", r.id
        )
        return (await self.referral_outs([r], detail=True))[0]

    # ---- misc -------------------------------------------------------------------------------------------------------
    async def coverage(self, term_id: uuid.UUID) -> dict[str, Any]:
        active = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(StudentProgramEnrollment)
                    .where(
                        StudentProgramEnrollment.institution_id == self.inst,
                        StudentProgramEnrollment.status == "active",
                    )
                )
            ).scalar_one()
            or 0
        )
        assigned = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(MentorAssignment).where(MentorAssignment.term_id == term_id)
                )
            ).scalar_one()
            or 0
        )
        mentors = int(
            (
                await self.db.execute(
                    select(func.count(func.distinct(MentorAssignment.mentor_staff_id))).where(
                        MentorAssignment.term_id == term_id
                    )
                )
            ).scalar_one()
            or 0
        )
        sessions = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(MentoringSession)
                    .join(MentorAssignment, MentorAssignment.id == MentoringSession.mentor_assignment_id)
                    .where(MentorAssignment.term_id == term_id)
                )
            ).scalar_one()
            or 0
        )
        return {
            "active_students": active,
            "assigned": assigned,
            "mentors": mentors,
            "sessions": sessions,
            "coverage_pct": round(100.0 * assigned / active, 1) if active else 0.0,
            "mentor_mentee_ratio": f"1:{round(assigned / mentors) if mentors else 0}",
        }


def _d(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date | datetime):
        return v.isoformat()
    return v
