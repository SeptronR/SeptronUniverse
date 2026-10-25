"""Early-warning risk scoring — Prompts/27 §27.6 ``risk_service`` ({mentoring.early_warning}).

``compute(term, scope)`` scores every active enrolment in scope: ``score = Σ weight × factor`` with each factor
normalised to 0..1 and the weights from ``risk.weights`` (sum 100):

* attendance — shortfall of the average ``attendance_summaries.pct`` of the term's offerings below 75 %
  (0 at ≥ 75 %, 1 at ≤ 50 %);
* cia — share of the term's ``cia_consolidations`` whose ``cia_scaled`` is below ``risk.cia_pass_pct`` (40) of the
  best scaled score in the offering (a proxy for the component maximum);
* dues — overdue balance bands (none 0 · < ₹10k 0.4 · < ₹50k 0.7 · more 1);
* standing — ``probation`` 1 · ``warning`` 0.6;
* hostel — disciplinary records (0.5 each) and roll-call absences (0.1 each) in the last 120 days, capped at 1;
* engagement — late / missing share of the term's LMS assignment submissions (when Phase 13 data exists).

``level`` by ``risk.thresholds``; upsert per (enrolment, term); a new ``high`` emits ``risk.flag_raised`` and
notifies the mentor + the department's HOD. Mentors acknowledge with an action; students see only their level when
``risk.show_to_student``.
"""

import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.enums.student_support import DEFAULT_RISK_THRESHOLDS, DEFAULT_RISK_WEIGHTS
from app.models.assessment import CiaConsolidation
from app.models.attendance import AttendanceSummary
from app.models.fees import FeeInvoice
from app.models.hostel import HostelAllocation, HostelDisciplinaryRecord, HostelRollCall, HostelRollCallEntry
from app.models.mentoring import MentorAssignment, RiskFlag
from app.models.offerings import CourseOffering
from app.models.students import StudentProgramEnrollment
from app.schemas.mentoring import RiskAcknowledge, RiskComputeSummary, RiskFlagOut, RiskHeatCell, RiskRunRequest
from app.services.student_support.common import SupportBase, forbidden, not_found, now_utc


def _dues_factor(paise: int) -> float:
    if paise <= 0:
        return 0.0
    if paise < 1_000_000:
        return 0.4
    if paise < 5_000_000:
        return 0.7
    return 1.0


class RiskService(SupportBase):
    audit_module = "mentoring"
    module = "mentoring"

    async def _weights(self) -> tuple[dict[str, float], dict[str, float]]:
        w = await self.setting("risk", "weights")
        t = await self.setting("risk", "thresholds")
        weights = {k: float(v) for k, v in (w if isinstance(w, dict) else DEFAULT_RISK_WEIGHTS).items()}
        thresholds = {k: float(v) for k, v in (t if isinstance(t, dict) else DEFAULT_RISK_THRESHOLDS).items()}
        return weights, thresholds

    async def compute(self, body: RiskRunRequest) -> RiskComputeSummary:
        term = await self.term_or_current(body.term_id)
        weights, thresholds = await self._weights()
        stmt = select(StudentProgramEnrollment).where(
            StudentProgramEnrollment.institution_id == self.inst, StudentProgramEnrollment.status == "active"
        )
        if body.department_id:
            stmt = stmt.where(StudentProgramEnrollment.department_id == body.department_id)
        if body.enrollment_ids:
            stmt = stmt.where(StudentProgramEnrollment.id.in_(body.enrollment_ids))
        if self.principal is not None and not self.all_access():
            parts = self.enrolment_dept_predicate(StudentProgramEnrollment.id)
            if not parts:
                raise forbidden("Risk computation needs department or institution scope")
            stmt = stmt.where(or_(*parts))
        enrols = list((await self.db.execute(stmt)).scalars().all())
        ids = [e.id for e in enrols] or [uuid.uuid4()]
        offerings = select(CourseOffering.id).where(CourseOffering.term_id == term.id)

        att: dict[uuid.UUID, list[float]] = defaultdict(list)
        for eid, pct in (
            await self.db.execute(
                select(AttendanceSummary.student_program_enrollment_id, AttendanceSummary.pct).where(
                    AttendanceSummary.student_program_enrollment_id.in_(ids),
                    AttendanceSummary.offering_id.in_(offerings),
                )
            )
        ).all():
            att[eid].append(float(pct or 0))

        cia_rows = (
            await self.db.execute(
                select(
                    CiaConsolidation.offering_id,
                    CiaConsolidation.student_program_enrollment_id,
                    CiaConsolidation.cia_scaled,
                ).where(CiaConsolidation.offering_id.in_(offerings))
            )
        ).all()
        best: dict[uuid.UUID, float] = defaultdict(float)
        for oid, _eid, sc in cia_rows:
            best[oid] = max(best[oid], float(sc or 0))
        pass_pct = float(await self.int_setting("risk", "cia_pass_pct", 40))
        cia: dict[uuid.UUID, list[bool]] = defaultdict(list)
        for oid, eid, sc in cia_rows:
            if best[oid] > 0:
                cia[eid].append(float(sc or 0) < best[oid] * pass_pct / 100)

        today = await self.today()
        dues: dict[uuid.UUID, int] = defaultdict(int)
        for eid, bal in (
            await self.db.execute(
                select(FeeInvoice.student_program_enrollment_id, FeeInvoice.balance_paise).where(
                    FeeInvoice.student_program_enrollment_id.in_(ids),
                    FeeInvoice.status.in_(("pending", "partial", "overdue")),
                    FeeInvoice.due_date < today,
                )
            )
        ).all():
            if eid:
                dues[eid] += int(bal or 0)

        since = today - timedelta(days=120)
        hostel: dict[uuid.UUID, float] = defaultdict(float)
        for (eid,) in (
            await self.db.execute(
                select(HostelDisciplinaryRecord.student_program_enrollment_id).where(
                    HostelDisciplinaryRecord.student_program_enrollment_id.in_(ids),
                    HostelDisciplinaryRecord.incident_on >= since,
                )
            )
        ).all():
            hostel[eid] += 0.5
        for (eid,) in (
            await self.db.execute(
                select(HostelAllocation.student_program_enrollment_id)
                .join(HostelRollCallEntry, HostelRollCallEntry.allocation_id == HostelAllocation.id)
                .join(HostelRollCall, HostelRollCall.id == HostelRollCallEntry.roll_call_id)
                .where(
                    HostelAllocation.student_program_enrollment_id.in_(ids),
                    HostelRollCallEntry.status.in_(("absent", "late")),
                    HostelRollCall.on_date >= since,
                )
            )
        ).all():
            hostel[eid] += 0.1

        engagement: dict[uuid.UUID, float] = {}
        try:
            from app.models.lms import AssignmentSubmission

            subs: dict[uuid.UUID, list[bool]] = defaultdict(list)
            for eid, late in (
                await self.db.execute(
                    select(AssignmentSubmission.student_program_enrollment_id, AssignmentSubmission.is_late).where(
                        AssignmentSubmission.student_program_enrollment_id.in_(ids),
                        AssignmentSubmission.submitted_at >= now_utc() - timedelta(days=120),
                    )
                )
            ).all():
                subs[eid].append(bool(late))
            engagement = {k: sum(v) / len(v) for k, v in subs.items() if v}
        except Exception:  # noqa: BLE001 - LMS data is optional (Phase 13)
            engagement = {}

        existing = {
            f.student_program_enrollment_id: f
            for f in (
                await self.db.execute(
                    select(RiskFlag).where(RiskFlag.term_id == term.id, RiskFlag.student_program_enrollment_id.in_(ids))
                )
            ).scalars()
        }
        by_level: dict[str, int] = defaultdict(int)
        new_high: list[tuple[StudentProgramEnrollment, RiskFlag]] = []
        for e in enrols:
            a = att.get(e.id)
            avg = sum(a) / len(a) if a else None
            f_att = 0.0 if avg is None or avg >= 75 else min(1.0, (75 - avg) / 25)
            c = cia.get(e.id)
            f_cia = (sum(c) / len(c)) if c else 0.0
            f_dues = _dues_factor(dues.get(e.id, 0))
            f_standing = {"probation": 1.0, "warning": 0.6}.get(e.academic_standing or "", 0.0)
            f_hostel = min(1.0, hostel.get(e.id, 0.0))
            f_eng = engagement.get(e.id, 0.0)
            factors_n = {
                "attendance": f_att,
                "cia": f_cia,
                "dues": f_dues,
                "standing": f_standing,
                "hostel": f_hostel,
                "engagement": f_eng,
            }
            score = round(sum(weights.get(k, 0.0) * v for k, v in factors_n.items()), 2)
            level = (
                "high"
                if score >= thresholds.get("high", 65)
                else "medium"
                if score >= thresholds.get("medium", 40)
                else "low"
            )
            factors: dict[str, Any] = {
                k: {"value": round(v, 3), "weight": weights.get(k, 0.0), "points": round(weights.get(k, 0.0) * v, 2)}
                for k, v in factors_n.items()
            }
            factors["attendance"]["avg_pct"] = round(avg, 1) if avg is not None else None
            factors["dues"]["overdue_paise"] = dues.get(e.id, 0)
            factors["standing"]["standing"] = e.academic_standing
            by_level[level] += 1
            f = existing.get(e.id)
            if f is None:
                f = RiskFlag(
                    institution_id=self.inst,
                    student_program_enrollment_id=e.id,
                    term_id=term.id,
                    score=Decimal(str(score)),
                    factors=factors,
                    level=level,
                )
                self.db.add(f)
                was = None
            else:
                was = f.level
                f.score, f.factors, f.level, f.computed_at = Decimal(str(score)), factors, level, now_utc()
                if level != was:
                    f.acknowledged_at, f.acknowledged_by = None, None
            if level == "high" and was != "high":
                new_high.append((e, f))
        await self.db.flush()
        for e, f in new_high:
            mentor = (
                await self.db.execute(
                    select(MentorAssignment.mentor_staff_id).where(
                        MentorAssignment.student_program_enrollment_id == e.id, MentorAssignment.term_id == term.id
                    )
                )
            ).scalar_one_or_none()
            card = (await self.enrollment_cards([e.id])).get(e.id, {})
            await self._emit(
                "risk.flag_raised",
                {"risk_flag_id": str(f.id), "enrollment_id": str(e.id), "score": float(f.score)},
                "risk_flag",
                f.id,
            )
            users = [await self.staff_user(mentor)] + await self.role_users("hod", e.department_id)
            await self._notify(
                "risk.flag_raised",
                users,
                {"student": card.get("name") or "", "score": float(f.score), "level": f.level},
            )
        await self._emit(
            "risk.computed",
            {"term_id": str(term.id), "computed": len(enrols), "high": by_level.get("high", 0)},
            "academic_term",
            term.id,
        )
        return RiskComputeSummary(
            term_id=term.id, computed=len(enrols), by_level=dict(by_level), new_high=len(new_high)
        )

    async def outs(self, rows: list[RiskFlag], *, level_only: bool = False) -> list[RiskFlagOut]:
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        metas = await self.metas("risk", [r.id for r in rows])
        out = []
        for r in rows:
            c = cards.get(r.student_program_enrollment_id, {})
            o = RiskFlagOut(
                id=r.id,
                student_program_enrollment_id=r.student_program_enrollment_id,
                term_id=r.term_id,
                level=r.level,
                computed_at=r.computed_at,
                acknowledged=r.acknowledged_at is not None,
            )
            if not level_only:
                o.student_name = c.get("name")
                o.registration_number = c.get("registration_number")
                o.department_id = c.get("department_id")
                o.score = float(r.score)
                o.factors = r.factors or {}
                o.acknowledged_at = r.acknowledged_at
                o.action = metas.get(str(r.id), {}).get("action")
            out.append(o)
        return out

    async def flags(
        self, term_id: uuid.UUID | None, level: str | None, department_id: uuid.UUID | None, scope: str | None = None
    ) -> list[RiskFlagOut]:
        term = await self.term_or_current(term_id)
        from app.services.student_support.mentoring_service import MentoringService

        pred = await MentoringService(self.db, self.principal, self.request, self.inst)._owned_enrolment_predicate(
            RiskFlag.student_program_enrollment_id, scope
        )
        if pred is None:
            raise forbidden("mentoring:manage required")
        stmt = select(RiskFlag).where(RiskFlag.institution_id == self.inst, RiskFlag.term_id == term.id, pred)
        if level:
            stmt = stmt.where(RiskFlag.level == level)
        if department_id:
            stmt = stmt.where(
                RiskFlag.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.department_id == department_id)
                )
            )
        rows = (await self.db.execute(stmt.order_by(RiskFlag.score.desc()).limit(1000))).scalars().all()
        return await self.outs(list(rows))

    async def my_flag(self) -> list[RiskFlagOut]:
        show = await self.setting("risk", "show_to_student")
        if not show:
            raise forbidden("Risk levels are not shown to students")
        ids = await self.my_enrollment_ids()
        rows = (
            (
                await self.db.execute(
                    select(RiskFlag)
                    .where(RiskFlag.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                    .order_by(RiskFlag.computed_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows), level_only=True)

    async def acknowledge(self, fid: uuid.UUID, body: RiskAcknowledge) -> RiskFlagOut:
        self.require_writer()
        f = (
            await self.db.execute(
                select(RiskFlag).where(RiskFlag.id == fid, RiskFlag.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if f is None:
            raise not_found("Risk flag")
        from app.services.student_support.mentoring_service import MentoringService

        if (
            await MentoringService(self.db, self.principal, self.request, self.inst)._can_see_enrolment(
                f.student_program_enrollment_id
            )
            is None
        ):
            raise not_found("Risk flag")
        f.acknowledged_by, f.acknowledged_at = self.actor_id, now_utc()
        await self.put_meta("risk", f.id, {"action": body.action, "by": str(self.actor_id)})
        await self.db.flush()
        await self._emit("risk.flag_acknowledged", {"risk_flag_id": str(f.id)}, "risk_flag", f.id)
        return (await self.outs([f]))[0]

    async def heatmap(self, term_id: uuid.UUID | None) -> list[RiskHeatCell]:
        term = await self.term_or_current(term_id)
        stmt = (
            select(StudentProgramEnrollment.department_id, RiskFlag.level, func.count())
            .join(StudentProgramEnrollment, StudentProgramEnrollment.id == RiskFlag.student_program_enrollment_id)
            .where(RiskFlag.institution_id == self.inst, RiskFlag.term_id == term.id)
        )
        if not self.all_access():
            parts = self.enrolment_dept_predicate(RiskFlag.student_program_enrollment_id)
            if not parts:
                raise forbidden("mentoring:view_all required")
            stmt = stmt.where(or_(*parts))
        rows = (await self.db.execute(stmt.group_by(StudentProgramEnrollment.department_id, RiskFlag.level))).all()
        codes = await self.department_codes([r[0] for r in rows])
        cells: dict[Any, RiskHeatCell] = {}
        for dep, level, n in rows:
            c = cells.setdefault(dep, RiskHeatCell(department_id=dep, department_code=codes.get(dep)))
            setattr(c, level, int(n))
        return list(cells.values())

    async def distribution(self, term_id: uuid.UUID) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(RiskFlag.level, func.count())
                .where(RiskFlag.institution_id == self.inst, RiskFlag.term_id == term_id)
                .group_by(RiskFlag.level)
            )
        ).all()
        return {lv: int(n) for lv, n in rows}

    async def weekly(self) -> int:
        """Beat ``risk.compute_weekly`` — recompute the current term for the whole institution."""
        term = await self.current_term(None)
        if term is None:
            return 0
        return (await self.compute(RiskRunRequest(term_id=term.id))).computed
