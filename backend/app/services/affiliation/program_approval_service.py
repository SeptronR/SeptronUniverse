"""Programme approvals and fee schedules — Prompts/34 §34.6 ``program_approval_service`` {affiliation.core} and the
fee schedule / dues half of ``application_service`` {affiliation.fees}.

``affiliation_program_approvals`` is the authoritative intake per college / programme / year: Phase 08 seat matrices
(``gates.check_intake``), Phase 09 registrations (``gates.check_registration``), Phase 32 metrics
(``affiliation.colleges_count`` / published intake keys) and the Phase 40 public list read it. Manual updates
(withdrawal, conditions, intake) carry a reason and are audited; the row is locked ``FOR UPDATE`` while the intake
changes. Carry-forward at year rollover creates next-year ``provisional`` rows for ``permanent`` approvals still valid.
Dues: per college the Phase 12 invoices with ``payer_type='college'`` plus the exam-processing estimate (accepted
``exam_registrations`` submission counts × the per-student schedule).
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.models.affiliation import AffiliationFeeSchedule, AffiliationProgramApproval, CollegeDataSubmission
from app.models.platform import College
from app.schemas.affiliation import (
    CarryForwardOut,
    DuesRow,
    FeeScheduleIn,
    FeeScheduleOut,
    FeeScheduleUpdate,
    ProgramApprovalCheck,
    ProgramApprovalOut,
    ProgramApprovalUpdate,
)
from app.services.affiliation.common import AffiliationBase, forbidden, not_found, rule
from app.services.affiliation.gates import approval_for

ENTITY = "affiliation_program_approval"


class ProgramApprovalService(AffiliationBase):
    async def _admitted(self, rows: list[AffiliationProgramApproval]) -> dict[uuid.UUID, int]:
        """Students admitted (active enrolments of the year's batch start) per approval row."""
        if not rows:
            return {}
        from app.models.students import StudentProgramEnrollment

        years = await self.years_map([r.academic_year_id for r in rows])
        out: dict[uuid.UUID, int] = {}
        for r in rows:
            y = years.get(r.academic_year_id)
            if y is None:
                continue
            n = (
                await self.db.execute(
                    select(func.count())
                    .select_from(StudentProgramEnrollment)
                    .where(
                        StudentProgramEnrollment.institution_id == self.inst,
                        StudentProgramEnrollment.college_id == r.college_id,
                        StudentProgramEnrollment.program_id == r.program_id,
                        StudentProgramEnrollment.created_at >= y.start_date,
                        StudentProgramEnrollment.created_at <= y.end_date + timedelta(days=1),
                    )
                )
            ).scalar_one()
            out[r.id] = int(n)
        return out

    async def outs(self, rows: list[AffiliationProgramApproval], *, admitted: bool = True) -> list[ProgramApprovalOut]:
        colleges = await self.colleges_map([r.college_id for r in rows])
        progs = await self.programs_map([r.program_id for r in rows])
        years = await self.years_map([r.academic_year_id for r in rows])
        counts = await self._admitted(rows) if admitted else {}
        today = await self.today()
        days = await self.aff_int("expiry_reminder_days")
        out = []
        for r in rows:
            if r.approval_status == "withdrawn":
                validity = "withdrawn"
            elif r.valid_to and r.valid_to < today:
                validity = "expired"
            elif r.valid_to and r.valid_to <= today + timedelta(days=days):
                validity = "expiring"
            else:
                validity = "valid"
            c, p, y = colleges.get(r.college_id), progs.get(r.program_id), years.get(r.academic_year_id)
            out.append(
                ProgramApprovalOut(
                    id=r.id,
                    college_id=r.college_id,
                    college_code=c.code if c else None,
                    program_id=r.program_id,
                    program_code=p.code if p else None,
                    program_name=p.name if p else None,
                    academic_year_id=r.academic_year_id,
                    academic_year=y.name if y else None,
                    sanctioned_intake=int(r.sanctioned_intake),
                    lateral_intake=int(r.lateral_intake or 0),
                    approval_status=r.approval_status,
                    order_no=r.order_no,
                    valid_from=r.valid_from,
                    valid_to=r.valid_to,
                    conditions=r.conditions,
                    validity=validity,  # type: ignore[arg-type]
                    admitted=counts.get(r.id, 0),
                )
            )
        return out

    async def _predicate(self) -> Any:
        if self.system() or self.office_reader():
            return None
        from sqlalchemy import false, or_

        conds = []
        mine = self.my_college_ids()
        if mine:
            conds.append(AffiliationProgramApproval.college_id.in_(mine))
        units = await self.unit_program_ids()
        if units:
            conds.append(AffiliationProgramApproval.program_id.in_(units))
        return or_(*conds) if conds else false()

    async def list_approvals(
        self,
        college_id: uuid.UUID | None,
        year_id: uuid.UUID | None,
        program_id: uuid.UUID | None,
        status: str | None,
        page: int = 1,
        per_page: int = 100,
    ) -> tuple[list[ProgramApprovalOut], int]:
        stmt = select(AffiliationProgramApproval).where(AffiliationProgramApproval.institution_id == self.inst)
        pred = await self._predicate()
        if pred is not None:
            stmt = stmt.where(pred)
        if college_id:
            stmt = stmt.where(AffiliationProgramApproval.college_id == college_id)
        if year_id:
            stmt = stmt.where(AffiliationProgramApproval.academic_year_id == year_id)
        if program_id:
            stmt = stmt.where(AffiliationProgramApproval.program_id == program_id)
        if status:
            stmt = stmt.where(AffiliationProgramApproval.approval_status == status)
        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = list(
            (
                await self.db.execute(
                    stmt.order_by(AffiliationProgramApproval.college_id, AffiliationProgramApproval.program_id)
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                )
            ).scalars()
        )
        return await self.outs(rows), int(total)

    async def _row(self, aid: uuid.UUID, *, lock: bool = False) -> AffiliationProgramApproval:
        stmt = select(AffiliationProgramApproval).where(
            AffiliationProgramApproval.id == aid, AffiliationProgramApproval.institution_id == self.inst
        )
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Programme approval")
        pred = await self._predicate()
        if pred is not None:
            ok_ = (
                await self.db.execute(
                    select(AffiliationProgramApproval.id).where(AffiliationProgramApproval.id == r.id, pred)
                )
            ).first()
            if not ok_:
                raise not_found("Programme approval")
        return r

    async def get(self, aid: uuid.UUID) -> ProgramApprovalOut:
        return (await self.outs([await self._row(aid)]))[0]

    async def update(self, aid: uuid.UUID, body: ProgramApprovalUpdate) -> ProgramApprovalOut:
        self.require_writer()
        if not (self.office() or self.decider()):
            raise forbidden("affiliation:manage or affiliation:decide required")
        r = await self._row(aid, lock=True)
        old = {
            "approval_status": r.approval_status,
            "sanctioned_intake": int(r.sanctioned_intake),
            "lateral_intake": int(r.lateral_intake or 0),
            "valid_to": r.valid_to.isoformat() if r.valid_to else None,
        }
        if body.approval_status is not None:
            r.approval_status = str(body.approval_status)
        if body.sanctioned_intake is not None:
            r.sanctioned_intake = body.sanctioned_intake
        if body.lateral_intake is not None:
            r.lateral_intake = body.lateral_intake
        if body.valid_to is not None:
            if r.valid_from and body.valid_to < r.valid_from:
                raise APIError(422, ErrorCode.VALIDATION, "valid_to precedes valid_from", {"field": "valid_to"})
            r.valid_to = body.valid_to
        cond = dict(r.conditions or {})
        if body.conditions is not None:
            cond["items"] = body.conditions
        trail = list(cond.get("changes") or [])
        trail.append({"reason": body.reason, "by": str(self.actor_id) if self.actor_id else None, "old": old})
        cond["changes"] = trail[-20:]
        r.conditions = cond
        await self.db.flush()
        await self._audit("approval_update", ENTITY, r.id, old, body.model_dump(mode="json", exclude_unset=True))
        event = "affiliation.program_withdrawn" if r.approval_status == "withdrawn" else "affiliation.program_updated"
        await self._emit(event, {"approval_id": str(r.id), "college_id": str(r.college_id)}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def check(
        self, college_id: uuid.UUID, program_id: uuid.UUID, year_id: uuid.UUID | None
    ) -> ProgramApprovalCheck:
        c = await self.visible_college(college_id)
        a = await approval_for(self.db, self.inst, college_id, program_id, year_id)
        prog = (await self.programs_map([program_id])).get(program_id)
        closed = bool(
            (prog is not None and prog.status == "closed")
            or (a is not None and a.approval_status == "withdrawn" and (a.conditions or {}).get("closure"))
        )
        if c.college_type not in ("affiliated", "autonomous"):
            return ProgramApprovalCheck(
                college_id=college_id,
                program_id=program_id,
                academic_year_id=year_id,
                approved=not closed,
                closed=closed,
                reason=f"{c.college_type} college — not gated",
            )
        approved = a is not None and a.approval_status != "withdrawn"
        return ProgramApprovalCheck(
            college_id=college_id,
            program_id=program_id,
            academic_year_id=year_id,
            approved=approved,
            closed=closed,
            approval_status=a.approval_status if a else None,
            sanctioned_intake=int(a.sanctioned_intake) if a else None,
            lateral_intake=int(a.lateral_intake or 0) if a else None,
            total_intake=int(a.sanctioned_intake) + int(a.lateral_intake or 0) if a else None,
            valid_to=a.valid_to if a else None,
            reason=None if approved else ("closed" if closed else "no approval for the year"),
        )

    async def carry_forward(self, year_id: uuid.UUID) -> CarryForwardOut:
        """Next-year ``provisional`` rows for ``permanent`` approvals still valid on the year's start (idempotent)."""
        y = await self.year(year_id)
        prev = (
            await self.db.execute(
                select(AffiliationProgramApproval).where(
                    AffiliationProgramApproval.institution_id == self.inst,
                    AffiliationProgramApproval.approval_status == "permanent",
                    AffiliationProgramApproval.academic_year_id != y.id,
                )
            )
        ).scalars()
        created = skipped = 0
        seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for r in prev:
            key = (r.college_id, r.program_id)
            if key in seen or (r.valid_to is not None and r.valid_to < y.start_date):
                skipped += 1
                continue
            seen.add(key)
            exists = (
                await self.db.execute(
                    select(AffiliationProgramApproval.id).where(
                        AffiliationProgramApproval.college_id == r.college_id,
                        AffiliationProgramApproval.program_id == r.program_id,
                        AffiliationProgramApproval.academic_year_id == y.id,
                    )
                )
            ).first()
            if exists:
                skipped += 1
                continue
            self.db.add(
                AffiliationProgramApproval(
                    institution_id=self.inst,
                    college_id=r.college_id,
                    program_id=r.program_id,
                    academic_year_id=y.id,
                    sanctioned_intake=r.sanctioned_intake,
                    lateral_intake=r.lateral_intake,
                    approval_status="provisional",
                    order_no=r.order_no,
                    valid_from=y.start_date,
                    valid_to=r.valid_to or y.end_date,
                    conditions={"carried_from": str(r.id)},
                )
            )
            created += 1
        await self.db.flush()
        await self._audit("carry_forward", ENTITY, None, None, {"year": y.name, "created": created})
        return CarryForwardOut(academic_year_id=y.id, created=created, skipped=skipped)

    async def expiry_scan(self) -> int:
        today = await self.today()
        days = await self.aff_int("expiry_reminder_days")
        rows = list(
            (
                await self.db.execute(
                    select(AffiliationProgramApproval).where(
                        AffiliationProgramApproval.institution_id == self.inst,
                        AffiliationProgramApproval.approval_status != "withdrawn",
                        AffiliationProgramApproval.valid_to.is_not(None),
                        AffiliationProgramApproval.valid_to >= today,
                        AffiliationProgramApproval.valid_to <= today + timedelta(days=days),
                    )
                )
            ).scalars()
        )
        n = 0
        colleges = await self.colleges_map([r.college_id for r in rows])
        progs = await self.programs_map([r.program_id for r in rows])
        for r in rows:
            key = f"expiry:{r.id}"
            if (await self.meta("reminded", key)).get("sent"):
                continue
            c = colleges.get(r.college_id)
            if c is None:
                continue
            p = progs.get(r.program_id)
            ctx = {"program": p.code if p else "", "valid_to": r.valid_to.isoformat() if r.valid_to else ""}
            await self.notify_college(c, "affiliation.program_approval_expiring", ctx)
            await self._notify(
                "affiliation.program_approval_expiring", await self.office_users(), {"college": c.name, **ctx}
            )
            await self._emit("affiliation.expiring", {"approval_id": str(r.id), **ctx}, ENTITY, r.id)
            await self.put_meta("reminded", key, {"sent": True, "at": today.isoformat()})
            n += 1
        return n

    # ---- fee schedules ------------------------------------------------------------------------------------------------
    async def schedule_outs(self, rows: list[AffiliationFeeSchedule]) -> list[FeeScheduleOut]:
        years = await self.years_map([r.academic_year_id for r in rows])
        return [
            FeeScheduleOut(
                id=r.id,
                academic_year_id=r.academic_year_id,
                academic_year=years[r.academic_year_id].name if r.academic_year_id in years else None,
                fee_type=r.fee_type,
                amount_paise=int(r.amount_paise),
                per_unit=r.per_unit,
            )
            for r in rows
        ]

    async def schedules(self, year_id: uuid.UUID | None) -> list[FeeScheduleOut]:
        stmt = select(AffiliationFeeSchedule).where(AffiliationFeeSchedule.institution_id == self.inst)
        if year_id:
            stmt = stmt.where(AffiliationFeeSchedule.academic_year_id == year_id)
        rows = list((await self.db.execute(stmt.order_by(AffiliationFeeSchedule.fee_type))).scalars())
        return await self.schedule_outs(rows)

    async def create_schedule(self, body: FeeScheduleIn) -> FeeScheduleOut:
        self.require_writer()
        if not self.office():
            raise forbidden("affiliation:manage required")
        await self.year(body.academic_year_id)
        dup = (
            await self.db.execute(
                select(AffiliationFeeSchedule.id).where(
                    AffiliationFeeSchedule.academic_year_id == body.academic_year_id,
                    AffiliationFeeSchedule.fee_type == str(body.fee_type),
                )
            )
        ).first()
        if dup:
            raise rule("A schedule for this fee type and year exists", "DUPLICATE_SCHEDULE")
        r = AffiliationFeeSchedule(
            institution_id=self.inst,
            academic_year_id=body.academic_year_id,
            fee_type=str(body.fee_type),
            amount_paise=body.amount_paise,
            per_unit=str(body.per_unit),
        )
        self.db.add(r)
        await self.db.flush()
        await self._audit("fee_schedule_create", "affiliation_fee_schedule", r.id, None, body.model_dump(mode="json"))
        return (await self.schedule_outs([r]))[0]

    async def update_schedule(self, sid: uuid.UUID, body: FeeScheduleUpdate) -> FeeScheduleOut:
        self.require_writer()
        if not self.office():
            raise forbidden("affiliation:manage required")
        r = (
            await self.db.execute(
                select(AffiliationFeeSchedule)
                .where(AffiliationFeeSchedule.id == sid, AffiliationFeeSchedule.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Fee schedule")
        old = {"amount_paise": int(r.amount_paise), "per_unit": r.per_unit}
        if body.amount_paise is not None:
            r.amount_paise = body.amount_paise
        if body.per_unit is not None:
            r.per_unit = str(body.per_unit)
        await self.db.flush()
        await self._audit(
            "fee_schedule_update", "affiliation_fee_schedule", r.id, old, body.model_dump(exclude_unset=True)
        )
        return (await self.schedule_outs([r]))[0]

    # ---- dues ---------------------------------------------------------------------------------------------------------
    async def dues(self, college_id: uuid.UUID | None) -> list[DuesRow]:
        from app.models.fees import FeeInvoice

        p = self.principal
        reader = (
            self.system()
            or self.office_reader()
            or (p is not None and (p.has("accounting", "view") or p.has("fees", "view_all")))
        )
        stmt = select(FeeInvoice).where(FeeInvoice.institution_id == self.inst, FeeInvoice.payer_type == "college")
        if not reader:
            mine = self.my_college_ids()
            if not mine:
                return []
            stmt = stmt.where(FeeInvoice.payer_id.in_(mine))
        if college_id:
            stmt = stmt.where(FeeInvoice.payer_id == college_id)
        today = await self.today()
        by_college: dict[uuid.UUID, DuesRow] = {}
        for inv in (await self.db.execute(stmt.where(FeeInvoice.status != "cancelled"))).scalars():
            row = by_college.setdefault(inv.payer_id, DuesRow(college_id=inv.payer_id))
            row.invoices += 1
            row.billed_paise += int(inv.total_paise or 0)
            row.paid_paise += int(inv.paid_paise or 0)
            bal = int(inv.balance_paise or 0)
            row.outstanding_paise += bal
            if inv.due_date and inv.due_date < today:
                row.overdue_paise += bal
            key = (inv.source_type or "other").replace("affiliation_", "")
            row.by_type[key] = row.by_type.get(key, 0) + bal
        # exam processing per student: accepted / locked exam_registrations submissions × the per-student schedule
        cur = await self.current_year_row()
        rate = 0
        if cur is not None:
            sched = (
                await self.db.execute(
                    select(AffiliationFeeSchedule.amount_paise).where(
                        AffiliationFeeSchedule.academic_year_id == cur.id,
                        AffiliationFeeSchedule.fee_type == "exam_processing_per_student",
                    )
                )
            ).scalar_one_or_none()
            rate = int(sched or 0)
        if rate:
            sub_stmt = (
                select(CollegeDataSubmission.college_id, func.coalesce(func.sum(CollegeDataSubmission.record_count), 0))
                .where(
                    CollegeDataSubmission.institution_id == self.inst,
                    CollegeDataSubmission.submission_type == "exam_registrations",
                    CollegeDataSubmission.status.in_(("accepted", "locked")),
                )
                .group_by(CollegeDataSubmission.college_id)
            )
            if not reader:
                sub_stmt = sub_stmt.where(CollegeDataSubmission.college_id.in_(self.my_college_ids()))
            if college_id:
                sub_stmt = sub_stmt.where(CollegeDataSubmission.college_id == college_id)
            for cid, n in (await self.db.execute(sub_stmt)).all():
                row = by_college.setdefault(cid, DuesRow(college_id=cid))
                row.exam_processing_estimate_paise = int(n) * rate
        colleges = await self.colleges_map(list(by_college))
        for cid, row in by_college.items():
            c: College | None = colleges.get(cid)
            row.college_code, row.college_name = (c.code, c.name) if c else (None, None)
        return sorted(by_college.values(), key=lambda r: -r.outstanding_paise)

    async def dues_reminders(self) -> int:
        n = 0
        for row in await self.dues(None):
            if row.overdue_paise <= 0:
                continue
            c = await self.college(row.college_id)
            await self.notify_college(
                c, "affiliation.fee_due", {"number": "dues", "amount": f"{row.overdue_paise / 100:.2f}"}
            )
            n += 1
        return n


def validity_for(valid_to: date | None, today: date, days: int) -> str:
    if valid_to is None:
        return "valid"
    if valid_to < today:
        return "expired"
    return "expiring" if valid_to <= today + timedelta(days=days) else "valid"
