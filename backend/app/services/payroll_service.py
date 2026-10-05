"""Payroll — Prompts/06 §06.6 ``payroll_service.py`` (money in paise).

Rules
1. **Components**: ``earning`` / ``deduction`` / ``employer_contribution`` / ``reimbursement``; ``calc_type`` ``fixed``
   (structure amount, else ``formula.amount_paise``), ``pct_of_basic`` (structure ``pct``, else ``formula.pct``),
   ``formula`` (safe expression over component codes, in rupees) or ``statutory`` (``pf`` / ``esi`` / ``pt`` / ``tds``
   / ``lwf`` from ``services/hr/statutory.py`` with the pack rules and the ``payroll.*`` settings).
2. **Salary structures** are effective-dated per staff member; a new structure closes the open one the day before it
   starts; a higher basic is an ``increment`` in the service book. A structure effective in the past produces
   **arrears** in the next run: for every earlier run of the period generated under the previous structure, the
   difference of the monthly gross × paid days ÷ days of that month (one line per month, never paid twice).
3. **Generate** (job ``payroll.generate``) for a month and a scope: per member (row locked ``FOR UPDATE``; a draft is
   recomputed, an approved/paid run is left alone → idempotent) the employment window pro-rates the earnings, LOP
   days (absences + half days + approved unpaid leave) become a *Loss of pay* deduction, statutory items follow the
   earned wages, loan EMIs are deducted, remuneration lines come from the registered sources
   (``core/hr_hooks.py``: leave encashment now; exam duties, guest hours, fellowships later) and TDS is projected on
   the monthly taxable salary. Runs are ``draft``.
4. **Approve** (``payroll:approve``) → ``approved``; **mark paid** (``payroll:mark_paid``) with the payment reference
   → ``paid``, loan balances reduced, payslip PDF job ``payroll.payslips`` + notification; bank advice CSV;
   statutory registers (PF ECR, ESI, PT, TDS 24Q) and Form 16 data.
5. **Loans / advances** ({hr.loans_advances}): a member's request goes through workflow ``hr.loan`` (HR → accounts);
   a payroll manager records an active loan directly; EMIs are deducted until the balance is 0; foreclosure closes it.
"""

import calendar
import csv
import io
import json
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core import jobs
from app.core.authz.masking import mask_value, may_unmask
from app.core.errors import APIError, ErrorCode
from app.core.hr_hooks import REMUNERATION_SOURCES
from app.core.workflow import engine as workflow_engine
from app.models.hr import (
    LoanAdvance,
    PayrollComponent,
    Staff,
    StaffPayroll,
    StaffPayrollItem,
    StaffSalaryStructure,
)
from app.models.platform import WorkflowInstance
from app.repositories.hr_scope import hr_visibility
from app.repositories.leave_repository import LeaveRepository, LeaveTypeRepository
from app.repositories.payroll_repository import (
    LoanRepository,
    PayrollComponentRepository,
    PayrollRepository,
    SalaryStructureRepository,
)
from app.schemas.payroll import (
    Form16Data,
    LoanIn,
    LoanOut,
    PayrollComponentIn,
    PayrollComponentOut,
    PayrollGenerateRequest,
    PayrollItemOut,
    PayrollMarkPaid,
    PayrollResponse,
    RegisterResponse,
    SalaryStructureIn,
    SalaryStructureOut,
)
from app.services.hr import statutory
from app.services.hr.common import HrServiceBase, rupees, snap
from app.utils.pagination import PageParams
from app.utils.pdf import render_pdf
from app.utils.response import PaginationMeta, VisibilityMeta

LOAN_KEY = "hr.loan"
EARNING_TYPES = ("earning", "reimbursement")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
REGISTERS = ("pf", "esi", "pt", "tds")


def month_bounds(month: int, year: int) -> tuple[date, date, int]:
    days = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, days), days


class PayrollService(HrServiceBase):
    audit_module = "payroll"

    def __init__(self, db: Any, principal: Any, request: Any = None, institution_id: uuid.UUID | None = None):
        super().__init__(db, principal, request, institution_id)
        self.components = PayrollComponentRepository(db, principal, self.inst)
        self.structures = SalaryStructureRepository(db)
        self.repo = PayrollRepository(db, principal, self.inst)
        self.loans = LoanRepository(db, principal, self.inst)

    # ---- rule 1: components -------------------------------------------------------------------------------------
    async def list_components(self, include_inactive: bool = False) -> list[PayrollComponentOut]:
        return [PayrollComponentOut.model_validate(c) for c in await self.components.all(include_inactive)]

    async def _check_formula(self, body: PayrollComponentIn) -> None:
        if body.calc_type.value == "formula":
            codes = {c.code for c in await self.components.all(include_inactive=True)} | {"BASIC"}
            statutory.validate_formula(str((body.formula or {}).get("expr")), codes)

    async def create_component(self, body: PayrollComponentIn) -> PayrollComponentOut:
        if await self.components.by_code(body.code):
            raise APIError(409, ErrorCode.CONFLICT, f"Component {body.code} exists", {"field": "code"})
        await self._check_formula(body)
        values = self._component_values(body)
        row = await self.components.create(institution_id=self.inst, **values)
        await self._audit("create", "payroll_component", row.id, None, values)
        return PayrollComponentOut.model_validate(row)

    async def update_component(self, component_id: uuid.UUID, body: PayrollComponentIn) -> PayrollComponentOut:
        row = await self.components.get_one(component_id)
        clash = await self.components.by_code(body.code)
        if clash is not None and clash.id != row.id:
            raise APIError(409, ErrorCode.CONFLICT, f"Component {body.code} exists", {"field": "code"})
        await self._check_formula(body)
        values = self._component_values(body)
        old = snap(row, tuple(values))
        await self.components.update(row, **values)
        await self._audit("update", "payroll_component", row.id, old, values)
        return PayrollComponentOut.model_validate(row)

    @staticmethod
    def _component_values(body: PayrollComponentIn) -> dict[str, Any]:
        v = body.model_dump()
        v["component_type"], v["calc_type"] = body.component_type.value, body.calc_type.value
        v["statutory_kind"] = body.statutory_kind.value if body.statutory_kind else None
        v["is_statutory"] = body.calc_type.value == "statutory"
        return v

    async def statutory_config(self) -> dict[str, Any]:
        pack = await self.pack()
        settings = {
            "statutory_overrides": await self.setting("payroll", "statutory_overrides"),
            "pt_state": await self.setting("payroll", "pt_state"),
            "tds_regime": await self.setting("payroll", "tds_regime"),
            "pf_wage_ceiling_applies": await self.setting("payroll", "pf_wage_ceiling_applies"),
        }
        return statutory.merged_config(pack.hr.statutory, settings)

    # ---- rule 2: structures -------------------------------------------------------------------------------------
    def full_earnings(self, structure: StaffSalaryStructure, comps: list[PayrollComponent]) -> dict[str, int]:
        """Full-month amounts of the non-statutory earning / reimbursement components under a structure."""
        per: dict[str, Any] = structure.components if isinstance(structure.components, dict) else {}
        values: dict[str, int] = {"BASIC": int(structure.basic_paise)}
        for c in comps:
            if c.component_type not in EARNING_TYPES or c.calc_type == "statutory" or c.code == "BASIC":
                continue
            override = per.get(c.code) or {}
            f = c.formula or {}
            if c.calc_type == "fixed":
                amount = int(override.get("amount_paise", f.get("amount_paise", 0)) or 0)
            elif c.calc_type == "pct_of_basic":
                pct = float(override.get("pct", f.get("pct", 0)) or 0)
                amount = int(round(structure.basic_paise * pct / 100))
            else:
                amount = statutory.eval_formula(str(f.get("expr", "0")), values)
            values[c.code] = amount
        return values

    async def list_structures(self, staff_id: uuid.UUID) -> list[SalaryStructureOut]:
        staff = await self.staff_repo.get_visible(staff_id, module="payroll")
        comps = list(await self.components.all())
        out = []
        for s in await self.structures.for_staff(staff.id):
            o = SalaryStructureOut.model_validate(s)
            o.monthly_gross_paise = sum(self.full_earnings(s, comps).values())
            out.append(o)
        return out

    async def add_structure(
        self, staff_id: uuid.UUID, body: SalaryStructureIn, *, reason: str | None = None
    ) -> SalaryStructureOut:
        staff = await self.staff_repo.get_visible(staff_id, module="payroll")
        existing = list(await self.structures.for_staff(staff.id))
        latest = existing[0] if existing else None
        if latest is not None and body.effective_from <= latest.effective_from:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"effective_from must be after the current structure ({latest.effective_from.isoformat()})",
                {"field": "effective_from"},
            )
        codes = {c.code for c in await self.components.all()}
        unknown = sorted(set(body.components) - codes)
        if unknown:
            raise APIError(
                422, ErrorCode.VALIDATION, f"Unknown components: {', '.join(unknown)}", {"field": "components"}
            )
        for row in await self.structures.open_ended(staff.id):
            row.effective_to = body.effective_from - timedelta(days=1)
        comps = list(await self.components.all())
        new = StaffSalaryStructure(
            institution_id=self.inst,
            staff_id=staff.id,
            effective_from=body.effective_from,
            pay_level=body.pay_level,
            basic_paise=body.basic_paise,
            components=body.components,
            created_by=getattr(self.principal, "id", None),
        )
        new.ctc_paise = body.ctc_paise or sum(self.full_earnings(new, comps).values()) * 12
        await self.structures.add(new)
        if latest is not None and body.basic_paise > latest.basic_paise:
            from app.services.staff_service import StaffService

            await StaffService(self.db, self.principal, self.request, self.inst).add_service_entry(
                staff,
                "increment",
                body.effective_from,
                {
                    "from_basic_paise": latest.basic_paise,
                    "to_basic_paise": body.basic_paise,
                    "pay_level": body.pay_level,
                    "reason": reason or body.reason,
                },
            )
        await self._audit(
            "salary_structure",
            "staff",
            staff.id,
            {"basic_paise": latest.basic_paise} if latest else None,
            {"basic_paise": body.basic_paise, "effective_from": body.effective_from.isoformat()},
        )
        o = SalaryStructureOut.model_validate(new)
        o.monthly_gross_paise = sum(self.full_earnings(new, comps).values())
        return o

    # ---- rule 3: generation -------------------------------------------------------------------------------------
    async def enqueue_generate(self, body: PayrollGenerateRequest) -> dict[str, Any]:
        params = {
            "month": body.month,
            "year": body.year,
            "college_id": str(body.college_id) if body.college_id else None,
            "staff_ids": [str(s) for s in body.staff_ids or []],
        }
        row = await jobs.enqueue(self.db, self.principal, "payroll.generate", params)
        await self._audit("generate_request", "payroll", None, None, params)
        return {"job_id": str(row.id), "status": row.status}

    async def run_generate(
        self,
        month: int,
        year: int,
        college_id: uuid.UUID | None,
        staff_ids: list[uuid.UUID] | None,
        progress: Callable[[int, str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        comps = list(await self.components.all())
        cfg = await self.statutory_config()
        members = list(await self.staff_repo.active(college_id=college_id, staff_ids=staff_ids))
        report: dict[str, Any] = {
            "month": month,
            "year": year,
            "total": len(members),
            "generated": 0,
            "recomputed": 0,
            "skipped": [],
        }
        for n, s in enumerate(members, start=1):
            try:
                async with self.db.begin_nested():
                    outcome = await self.generate_one(s, month, year, comps, cfg)
            except APIError as exc:
                outcome = exc.message
            if outcome in ("generated", "recomputed"):
                report[outcome] += 1
            else:
                report["skipped"].append({"staff_id": str(s.id), "employee_id": s.employee_id, "reason": outcome})
            if progress and n % 10 == 0:
                await progress(int(n * 100 / max(len(members), 1)), f"{n}/{len(members)} staff")
        await self._audit(
            "generate",
            "payroll",
            None,
            None,
            {k: v for k, v in report.items() if k != "skipped"} | {"skipped": len(report["skipped"])},
        )
        await self._emit(
            "payroll.generated",
            {"month": month, "year": year, "generated": report["generated"], "recomputed": report["recomputed"]},
            "payroll",
            None,
        )
        return report

    async def generate_one(
        self, staff: Staff, month: int, year: int, comps: list[PayrollComponent], cfg: dict[str, Any]
    ) -> str:
        first, last, days_in_month = month_bounds(month, year)
        start = max(first, staff.joining_date or first)
        end = min(last, staff.exit_date or last)
        if start > end:
            return "not employed in the period"
        structure = await self.structures.effective(staff.id, end)
        if structure is None:
            return "no salary structure"
        run = await self.repo.run_for(staff.id, month, year, for_update=True)
        if run is not None and run.status != "draft":
            return f"already {run.status}"
        eligible = (end - start).days + 1
        full = self.full_earnings(structure, comps)
        prorate = eligible / days_in_month
        earn = {code: int(round(v * prorate)) for code, v in full.items()}
        lop = Decimal(str(await self._lop_days(staff, start, end)))
        lop = min(lop, Decimal(eligible))
        paid_days = Decimal(eligible) - lop
        gross_fixed = sum(earn.values())
        lop_amount = int(round(sum(full.values()) / days_in_month * float(lop))) if lop else 0
        lop_amount = min(lop_amount, gross_fixed)
        ratio = float(paid_days) / eligible if eligible else 0
        earned = {code: int(round(v * ratio)) for code, v in earn.items()}
        earned_gross = gross_fixed - lop_amount

        created = run is None
        if run is None:
            run = StaffPayroll(
                institution_id=self.inst,
                staff_id=staff.id,
                month=month,
                year=year,
                gross_paise=0,
                net_paise=0,
                status="draft",
            )
            self.db.add(run)
            await self.db.flush()
        else:
            await self.repo.clear_items(run.id)
        items: list[StaffPayrollItem] = []

        def add(
            label: str,
            ctype: str,
            amount: int,
            comp: PayrollComponent | None = None,
            source_type: str | None = None,
            source_id: uuid.UUID | None = None,
        ) -> None:
            if amount <= 0 and not (comp and comp.code == "BASIC"):
                return
            items.append(
                StaffPayrollItem(
                    institution_id=self.inst,
                    payroll_id=run.id,
                    component_id=comp.id if comp else None,
                    label=label[:80],
                    component_type=ctype,
                    amount_paise=int(amount),
                    source_type=source_type,
                    source_id=source_id,
                )
            )

        by_code = {c.code: c for c in comps}
        for c in comps:
            if c.component_type in EARNING_TYPES and c.calc_type != "statutory":
                add(c.name, c.component_type, earn.get(c.code, 0), c)
        if "BASIC" not in by_code:
            add("Basic Pay", "earning", earn["BASIC"])
        if lop_amount:
            add(f"Loss of pay ({float(lop):g} day(s))", "deduction", lop_amount, source_type="lop")

        pf_wage = sum(earned.get(code, 0) for code in (cfg.get("pf") or {}).get("wage_components", ["BASIC", "DA"]))
        pf_calc = statutory.pf(pf_wage, cfg)
        esi_calc = statutory.esi(earned_gross, cfg)
        lwf_calc = statutory.lwf(month, cfg)
        non_taxable = sum(
            earned.get(c.code, 0) for c in comps if c.component_type in EARNING_TYPES and not c.is_taxable
        )
        tds_calc = statutory.tds_monthly(earned_gross - non_taxable, cfg, pf_calc["employee"])
        for c in comps:
            if c.calc_type == "statutory":
                is_er = c.component_type == "employer_contribution"
                amount = {
                    "pf": pf_calc["employer" if is_er else "employee"],
                    "esi": esi_calc["employer" if is_er else "employee"],
                    "pt": 0 if is_er else statutory.professional_tax(earned_gross, month, cfg),
                    "tds": 0 if is_er else tds_calc["monthly"],
                    "lwf": lwf_calc["employer" if is_er else "employee"],
                }.get(c.statutory_kind or "", 0)
                add(c.name, c.component_type, amount, c, source_type="statutory")
            elif c.component_type == "deduction":
                f = c.formula or {}
                if c.calc_type == "pct_of_basic":
                    amount = int(round(earned.get("BASIC", 0) * float(f.get("pct", 0)) / 100))
                elif c.calc_type == "formula":
                    amount = statutory.eval_formula(str(f.get("expr", "0")), earned)
                else:
                    amount = int(f.get("amount_paise", 0) or 0)
                add(c.name, "deduction", amount, c)

        for loan in await self.loans.active_for(staff.id, first):
            add(
                f"{loan.loan_type.replace('_', ' ').title()} loan EMI",
                "deduction",
                min(loan.emi_paise, loan.balance_paise),
                source_type="loan",
                source_id=loan.id,
            )
        for name, source in REMUNERATION_SOURCES.items():
            for line in await source(self.db, staff, month, year):
                if line.source_id and await self.repo.source_used(line.source_type, line.source_id, run.id):
                    continue
                add(
                    line.label,
                    line.component_type,
                    line.amount_paise,
                    source_type=line.source_type or name,
                    source_id=line.source_id,
                )
        for label, amount, sid in await self._arrears(staff, structure, comps, month, year, run.id):
            add(label, "earning", amount, source_type="arrears", source_id=sid)

        for it in items:
            await self.repo.add_item(it)
        gross = sum(i.amount_paise for i in items if i.component_type in EARNING_TYPES)
        deductions = sum(i.amount_paise for i in items if i.component_type == "deduction")
        employer = sum(i.amount_paise for i in items if i.component_type == "employer_contribution")
        run.working_days, run.paid_days, run.lop_days = eligible, paid_days, lop
        run.gross_paise, run.deductions_paise, run.employer_contrib_paise = gross, deductions, employer
        run.net_paise = gross - deductions
        await self.db.flush()
        return "generated" if created else "recomputed"

    async def _lop_days(self, staff: Staff, start: date, end: date) -> float:
        from app.services.staff_attendance_service import StaffAttendanceService

        summary = (
            await StaffAttendanceService(self.db, None, institution_id=self.inst).summarise([staff], start, end)
        )[0]
        unpaid_types = [
            t.id
            for t in await LeaveTypeRepository(self.db, None, self.inst).all(include_inactive=True)
            if not t.is_paid
        ]
        lwp = 0.0
        if unpaid_types:
            for leave in await LeaveRepository(self.db, None, self.inst).approved_in_range(
                [staff.id], start, end, unpaid_types
            ):
                d = max(leave.from_date, start)
                while d <= min(leave.to_date, end):
                    lwp += 0.5 if leave.half_day else 1
                    d += timedelta(days=1)
        # an approved LWP day shows as ``on_leave`` in attendance (not ``absent``), so the two never double count
        return float(summary.lop_days) + lwp

    async def _arrears(
        self,
        staff: Staff,
        structure: StaffSalaryStructure,
        comps: list[PayrollComponent],
        month: int,
        year: int,
        run_id: uuid.UUID,
    ) -> list[tuple[str, int, uuid.UUID]]:
        history = [
            s
            for s in await self.structures.for_staff(staff.id)
            if s.id != structure.id and s.created_at < structure.created_at
        ]
        if not history:
            return []
        paid = await self.repo.arrears_paid(staff.id, structure.id, run_id)
        new_total = sum(self.full_earnings(structure, comps).values())
        out: list[tuple[str, int, uuid.UUID]] = []
        for prev_run in await self.repo.runs_of_staff(staff.id):
            if (prev_run.year, prev_run.month) >= (year, month) or prev_run.status == "cancelled":
                continue
            p_first, p_last, p_days = month_bounds(prev_run.month, prev_run.year)
            if p_last < structure.effective_from or prev_run.created_at >= structure.created_at:
                continue
            label = f"Arrears {prev_run.month:02d}/{prev_run.year}"
            if label in paid:
                continue
            old = next((s for s in history if s.effective_from <= p_last), None)
            if old is None:
                continue
            diff = new_total - sum(self.full_earnings(old, comps).values())
            covered_from = max(p_first, structure.effective_from)
            share = ((p_last - covered_from).days + 1) / p_days
            paid_share = float(prev_run.paid_days or 0) / float(prev_run.working_days or p_days)
            amount = int(round(diff * share * paid_share))
            if amount > 0:
                out.append((label, amount, structure.id))
        return out

    # ---- rule 4: runs -------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None, **filters: Any
    ) -> tuple[list[PayrollResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.repo.filtered(scope=scope, **filters)
        if not params.sort:
            params = params.model_copy(update={"sort": "-year"})
        rows, pagination = await self.repo.paginate(stmt, params)
        return await self._responses(list(rows), with_items=False), pagination, hr_visibility(self.principal, "payroll")

    async def get(self, payroll_id: uuid.UUID) -> PayrollResponse:
        return (await self._responses([await self.repo.get_visible(payroll_id)], with_items=True))[0]

    async def me(self, year: int | None) -> list[PayrollResponse]:
        staff = await self.my_staff()
        assert staff is not None
        stmt = self.repo.filtered(scope="self", staff_id=staff.id, year=year).where(
            StaffPayroll.status.in_(("approved", "paid"))
        )
        rows = list(
            (await self.db.execute(stmt.order_by(StaffPayroll.year.desc(), StaffPayroll.month.desc()))).scalars().all()
        )
        return await self._responses(rows, with_items=True)

    async def _responses(self, rows: list[StaffPayroll], *, with_items: bool) -> list[PayrollResponse]:
        staff = {s.id: s for s in [await self.staff_repo.by_id(i) for i in {r.staff_id for r in rows}] if s}
        depts = await self.staff_repo.department_rows([s.department_id for s in staff.values() if s.department_id])
        items = await self.repo.items([r.id for r in rows]) if with_items else {}
        out = []
        for r in rows:
            o = PayrollResponse.model_validate(r)
            s = staff.get(r.staff_id)
            if s is not None:
                o.staff_name, o.employee_id = s.full_name, s.employee_id
                o.department_code = depts[s.department_id].code if s.department_id in depts else None
            o.items = [PayrollItemOut.model_validate(i) for i in items.get(r.id, [])]
            o.items.sort(key=_item_order)
            out.append(o)
        return out

    async def approve(self, payroll_id: uuid.UUID) -> PayrollResponse:
        run = await self.repo.get_visible(payroll_id, for_update=True)
        if run.status != "draft":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"Payroll is {run.status}")
        run.status, run.approved_by, run.approved_at = "approved", self.principal.id, datetime.now(UTC)
        await self.db.flush()
        await self._audit(
            "approve", "payroll", run.id, {"status": "draft"}, {"status": "approved", "net_paise": run.net_paise}
        )
        await self._emit(
            "payroll.approved",
            {"payroll_id": str(run.id), "staff_id": str(run.staff_id), "month": run.month, "year": run.year},
            "payroll",
            run.id,
        )
        return await self.get(run.id)

    async def mark_paid(self, payroll_id: uuid.UUID, body: PayrollMarkPaid) -> PayrollResponse:
        run = await self.repo.get_visible(payroll_id, for_update=True)
        if run.status != "approved":
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, f"Only approved payroll can be paid (this one is {run.status})"
            )
        paid_at = datetime.combine(body.paid_on, datetime.min.time(), tzinfo=UTC) if body.paid_on else datetime.now(UTC)
        run.status, run.paid_at, run.payment_ref = "paid", paid_at, body.payment_ref
        for item in (await self.repo.items([run.id])).get(run.id, []):
            if item.source_type == "loan" and item.source_id:
                loan = await self.loans.get_any(item.source_id)
                if loan is not None and loan.status == "active":
                    loan.balance_paise = max(0, loan.balance_paise - item.amount_paise)
                    if loan.balance_paise == 0:
                        loan.status = "closed"
        await self.db.flush()
        job = await jobs.enqueue(
            self.db, self.principal, "payroll.payslips", {"payroll_ids": [str(run.id)]}, queue="documents"
        )
        await self._audit(
            "mark_paid", "payroll", run.id, {"status": "approved"}, {"status": "paid", "payment_ref": body.payment_ref}
        )
        await self._emit(
            "payroll.paid",
            {"payroll_id": str(run.id), "staff_id": str(run.staff_id), "job_id": str(job.id)},
            "payroll",
            run.id,
        )
        resp = await self.get(run.id)
        return resp

    async def payslip_pdf(self, payroll_id: uuid.UUID) -> tuple[bytes, str]:
        run = await self.repo.get_visible(payroll_id)
        staff = await self.staff_repo.by_id(run.staff_id)
        if (
            run.status == "draft"
            and staff is not None
            and staff.user_id == getattr(self.principal, "id", None)
            and not self.principal.has("payroll", "view_all")
        ):
            raise APIError(404, ErrorCode.NOT_FOUND, "Payroll not found")
        resp = (await self._responses([run], with_items=True))[0]
        inst = await self.institution()
        return build_payslip(inst.name, resp), f"payslip-{resp.employee_id}-{run.year}-{run.month:02d}.pdf"

    async def store_payslips(self, payroll_ids: list[uuid.UUID]) -> int:
        """Job ``payroll.payslips``: render, store (signed URL) and notify each member."""
        from app.core.files import build_key, storage

        inst = await self.institution()
        n = 0
        for pid in payroll_ids:
            run = (await self.db.execute(select(StaffPayroll).where(StaffPayroll.id == pid))).scalar_one_or_none()
            if run is None:
                continue
            resp = (await self._responses([run], with_items=True))[0]
            key = build_key(self.inst, "payslips", f"{resp.employee_id}-{run.year}-{run.month:02d}.pdf")
            await storage.put(key, build_payslip(inst.name, resp), "application/pdf")
            run.payslip_url = storage.signed_url(key, 5 * 365 * 24 * 3600)
            staff = await self.staff_repo.by_id(run.staff_id)
            if staff is not None:
                await self._notify(
                    "payroll.payslip_ready",
                    [staff.user_id],
                    {"period": f"{MONTHS[run.month - 1]} {run.year}", "net": rupees(run.net_paise)},
                )
            n += 1
        await self.db.flush()
        return n

    async def bank_advice(self, month: int, year: int) -> bytes:
        rows = await self.repo.period(month, year, ("approved", "paid"))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["employee_id", "name", "account_no", "ifsc", "bank", "net_amount", "status"])
        for r in rows:
            s = await self.staff_repo.by_id(r.staff_id)
            if s is None:
                continue
            bank: dict[str, Any] = {}
            try:
                bank = json.loads(s.bank_details_encrypted) if s.bank_details_encrypted else {}
            except (TypeError, ValueError):
                bank = {}
            w.writerow(
                [
                    s.employee_id,
                    s.full_name,
                    bank.get("account_no", ""),
                    bank.get("ifsc", ""),
                    bank.get("bank", ""),
                    f"{r.net_paise / 100:.2f}",
                    r.status,
                ]
            )
        await self._audit("bank_advice", "payroll", None, None, {"month": month, "year": year, "rows": len(rows)})
        return buf.getvalue().encode()

    # ---- registers / Form 16 ------------------------------------------------------------------------------------
    async def register(self, kind: str, month: int, year: int) -> RegisterResponse:
        if kind not in REGISTERS:
            raise APIError(404, ErrorCode.NOT_FOUND, f"Unknown register {kind}")
        cfg = await self.statutory_config()
        kinds = await self._kinds()
        runs = await self.repo.period(month, year, ("draft", "approved", "paid"))
        items = await self.repo.items([r.id for r in runs])
        unmask = may_unmask(self.principal, "hr")
        rows: list[dict[str, Any]] = []
        totals: dict[str, int] = defaultdict(int)
        ceiling = int((cfg.get("pf") or {}).get("wage_ceiling_paise") or 0)
        for run in runs:
            s = await self.staff_repo.by_id(run.staff_id)
            if s is None:
                continue
            its = items.get(run.id, [])
            gross = run.gross_paise - sum(i.amount_paise for i in its if i.source_type == "lop")

            def amt(kind_name: str, ctype: str, its: list[StaffPayrollItem] = its) -> int:
                return sum(
                    i.amount_paise for i in its if i.component_type == ctype and kinds.get(i.component_id) == kind_name
                )

            if kind == "pf":
                ee, er = amt("pf", "deduction"), amt("pf", "employer_contribution")
                if not ee and not er:
                    continue
                wage = int(round(ee * 100 / 12))
                eps = min(er, int(round(min(wage, ceiling or wage) * 8.33 / 100 / 100)) * 100)
                row = {
                    "uan": s.uan,
                    "name": s.full_name,
                    "gross_wages": gross,
                    "epf_wages": wage,
                    "eps_wages": min(wage, ceiling or wage),
                    "epf_ee": ee,
                    "eps_er": eps,
                    "epf_er": er - eps,
                    "ncp_days": float(run.lop_days),
                }
            elif kind == "esi":
                ee, er = amt("esi", "deduction"), amt("esi", "employer_contribution")
                if not ee and not er:
                    continue
                row = {
                    "esi_number": s.esi_number,
                    "name": s.full_name,
                    "paid_days": float(run.paid_days or 0),
                    "gross_wages": gross,
                    "esi_ee": ee,
                    "esi_er": er,
                }
            elif kind == "pt":
                pt = amt("pt", "deduction")
                row = {"employee_id": s.employee_id, "name": s.full_name, "gross_wages": gross, "pt": pt}
            else:
                pan = s.pan_encrypted if unmask else mask_value(s.pan_encrypted) if s.pan_encrypted else None
                row = {
                    "employee_id": s.employee_id,
                    "pan": pan,
                    "name": s.full_name,
                    "gross_wages": gross,
                    "tds": amt("tds", "deduction"),
                }
            rows.append(row)
            for k, v in row.items():
                if isinstance(v, int) and k not in ("ncp_days",):
                    totals[k] += v
        await self._audit(
            "register", "payroll", None, None, {"kind": kind, "month": month, "year": year, "rows": len(rows)}
        )
        return RegisterResponse(
            kind=kind,
            month=month,
            year=year,
            columns=list(rows[0].keys()) if rows else [],
            rows=rows,
            totals=dict(totals),
        )

    async def form16(self, fy_start: int, staff_id: uuid.UUID | None) -> Form16Data:
        if staff_id is None:
            staff = await self.my_staff()
        else:
            staff = await self.staff_repo.get_visible(staff_id, module="payroll")
        assert staff is not None
        if staff.user_id != getattr(self.principal, "id", None) and not self.principal.has("payroll", "statutory"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires payroll:statutory")
        cfg = await self.statutory_config()
        kinds = await self._kinds()
        periods = [(fy_start, m) for m in range(4, 13)] + [(fy_start + 1, m) for m in range(1, 4)]
        runs = {(r.year, r.month): r for r in await self.repo.year_runs([staff.id], periods)}
        items = await self.repo.items([r.id for r in runs.values()])
        months: list[dict[str, Any]] = []
        gross_total = pt_total = pf_total = tds_total = 0
        quarters = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
        for y, m in periods:
            run = runs.get((y, m))
            if run is None:
                months.append({"period": f"{MONTHS[m - 1]} {y}", "gross": 0, "tds": 0})
                continue
            its = items.get(run.id, [])
            lop = sum(i.amount_paise for i in its if i.source_type == "lop")
            gross = run.gross_paise - lop
            tds = sum(i.amount_paise for i in its if kinds.get(i.component_id) == "tds")
            pt = sum(i.amount_paise for i in its if kinds.get(i.component_id) == "pt")
            pf = sum(
                i.amount_paise for i in its if kinds.get(i.component_id) == "pf" and i.component_type == "deduction"
            )
            gross_total += gross
            tds_total += tds
            pt_total += pt
            pf_total += pf
            q = "Q1" if m in (4, 5, 6) else "Q2" if m in (7, 8, 9) else "Q3" if m in (10, 11, 12) else "Q4"
            quarters[q] += tds
            months.append(
                {"period": f"{MONTHS[m - 1]} {y}", "gross": gross, "tds": tds, "pt": pt, "pf": pf, "status": run.status}
            )
        tds_cfg = cfg.get("tds") or {}
        regime_name = tds_cfg.get("regime") or tds_cfg.get("default_regime") or "new"
        regime = (tds_cfg.get("regimes") or {}).get(regime_name, {})
        std = int(regime.get("standard_deduction_paise") or 0)
        taxable = max(
            0,
            gross_total
            - std
            - (pt_total if regime_name == "old" else 0)
            - (min(pf_total, 15_000_000) if regime_name == "old" else 0),
        )
        unmask = may_unmask(self.principal, "hr") or staff.user_id == getattr(self.principal, "id", None)
        await self._audit("form16", "staff", staff.id, None, {"fy": fy_start})
        return Form16Data(
            staff_id=staff.id,
            staff_name=staff.full_name,
            employee_id=staff.employee_id,
            pan=staff.pan_encrypted if unmask else (mask_value(staff.pan_encrypted) if staff.pan_encrypted else None),
            financial_year=f"{fy_start}-{str(fy_start + 1)[-2:]}",
            assessment_year=f"{fy_start + 1}-{str(fy_start + 2)[-2:]}",
            regime=regime_name,
            months=months,
            gross_salary_paise=gross_total,
            exempt_allowances_paise=0,
            standard_deduction_paise=min(std, gross_total),
            professional_tax_paise=pt_total,
            pf_employee_paise=pf_total,
            taxable_income_paise=taxable,
            tax_on_income_paise=statutory.annual_tax(taxable, cfg),
            tds_deducted_paise=tds_total,
            quarters=quarters,
        )

    async def _kinds(self) -> dict[uuid.UUID | None, str | None]:
        return {c.id: c.statutory_kind for c in await self.components.all(include_inactive=True)}

    # ---- rule 5: loans ------------------------------------------------------------------------------------------
    async def list_loans(
        self, params: PageParams, scope: str | None, status: str | None
    ) -> tuple[list[LoanOut], PaginationMeta, VisibilityMeta]:
        stmt = self.loans.filtered(scope=scope, status=status)
        if not params.sort:
            params = params.model_copy(update={"sort": "-created_at"})
        rows, pagination = await self.loans.paginate(stmt, params)
        return await self._loans_out(list(rows)), pagination, hr_visibility(self.principal, "payroll")

    async def _loans_out(self, rows: list[LoanAdvance]) -> list[LoanOut]:
        names = await self.staff_repo.names([r.staff_id for r in rows])
        out = []
        for r in rows:
            o = LoanOut.model_validate(r)
            o.staff_name, o.employee_id = names.get(r.staff_id, (None, None))
            o.emis_remaining = -(-r.balance_paise // r.emi_paise) if r.emi_paise else None
            out.append(o)
        return out

    async def create_loan(self, body: LoanIn) -> LoanOut:
        manager = self.principal.has("payroll", "manage")
        if body.staff_id is not None and manager:
            staff: Staff | None = await self.staff_repo.get_visible(body.staff_id, module="payroll")
            status = "active"
        else:
            staff = await self.my_staff()
            status = "pending"
        assert staff is not None
        loan = await self.loans.create(
            institution_id=self.inst,
            staff_id=staff.id,
            loan_type=body.loan_type.value,
            principal_paise=body.principal_paise,
            emi_paise=body.emi_paise,
            start_month=body.start_month.replace(day=1),
            balance_paise=body.principal_paise,
            status=status,
        )
        if status == "pending":
            instance = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=LOAN_KEY,
                entity_type="loan_advance",
                entity_id=loan.id,
                started_by=self.principal.id,
                context={
                    "staff_id": str(staff.id),
                    "department_id": str(staff.department_id) if staff.department_id else None,
                    "college_id": str(staff.college_id) if staff.college_id else None,
                    "principal_paise": body.principal_paise,
                },
                title=f"{body.loan_type.value.replace('_', ' ').title()} loan {rupees(body.principal_paise)} — {staff.full_name}",
            )
            loan.workflow_instance_id = instance.id
            await self.db.flush()
        await self._audit(
            "create",
            "loan",
            loan.id,
            None,
            snap(loan, ("staff_id", "loan_type", "principal_paise", "emi_paise", "status")),
        )
        return (await self._loans_out([loan]))[0]

    async def foreclose(self, loan_id: uuid.UUID) -> LoanOut:
        loan = await self.loans.get_visible(loan_id, for_update=True)
        if loan.status != "active":
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"The loan is {loan.status}")
        old = snap(loan, ("status", "balance_paise"))
        loan.status, loan.balance_paise = "closed", 0
        await self.db.flush()
        await self._audit("foreclose", "loan", loan.id, old, {"status": "closed", "balance_paise": 0})
        return (await self._loans_out([loan]))[0]

    # ---- Beat ---------------------------------------------------------------------------------------------------
    async def reminder(self, today: date) -> int:
        pending = 0
        for s in await self.staff_repo.active():
            if await self.repo.run_for(s.id, today.month, today.year) is None:
                pending += 1
        if pending:
            await self._notify(
                "payroll.reminder",
                [],
                {"period": f"{MONTHS[today.month - 1]} {today.year}", "pending": str(pending)},
                audience={"roles": ["accountant", "hr_officer"]},
            )
        return pending


def _item_order(i: PayrollItemOut) -> tuple[int, str]:
    rank = {"earning": 0, "reimbursement": 1, "deduction": 2, "employer_contribution": 3}.get(i.component_type, 4)
    return rank, i.label


def build_payslip(institution: str, p: PayrollResponse) -> bytes:
    period = f"{MONTHS[p.month - 1]} {p.year}"
    earnings = [i for i in p.items if i.component_type in EARNING_TYPES]
    deductions = [i for i in p.items if i.component_type == "deduction"]
    employer = [i for i in p.items if i.component_type == "employer_contribution"]
    lines = [
        f"{institution} — Payslip for {period}",
        f"Employee: {p.staff_name} ({p.employee_id})   Department: {p.department_code or '-'}",
        f"Working days: {p.working_days}   Paid days: {p.paid_days}   LOP days: {p.lop_days}",
        "",
        "EARNINGS",
        *[f"  {i.label:<44} {rupees(i.amount_paise):>16}" for i in earnings],
        f"  {'Gross earnings':<44} {rupees(p.gross_paise):>16}",
        "",
        "DEDUCTIONS",
        *[f"  {i.label:<44} {rupees(i.amount_paise):>16}" for i in deductions],
        f"  {'Total deductions':<44} {rupees(p.deductions_paise):>16}",
        "",
        f"NET PAY {rupees(p.net_paise)}",
        "",
        "Employer contributions (not part of net pay)",
        *[f"  {i.label:<44} {rupees(i.amount_paise):>16}" for i in employer],
        "",
        f"Status: {p.status}{'  Ref: ' + p.payment_ref if p.payment_ref else ''}",
        "This is a system-generated payslip.",
    ]

    def table(title: str, rows: list[PayrollItemOut], total: tuple[str, int] | None) -> str:
        body = "".join(f"<tr><td>{r.label}</td><td class='n'>{rupees(r.amount_paise)}</td></tr>" for r in rows)
        foot = f"<tr class='t'><td>{total[0]}</td><td class='n'>{rupees(total[1])}</td></tr>" if total else ""
        return f"<h3>{title}</h3><table>{body}{foot}</table>"

    html = (
        "<html><head><style>body{font-family:sans-serif;font-size:11px} table{width:100%;border-collapse:collapse}"
        "td{border-bottom:1px solid #ddd;padding:3px} .n{text-align:right} .t td{font-weight:bold}</style></head><body>"
        f"<h2>{institution}</h2><p><b>Payslip — {period}</b></p>"
        f"<p>{p.staff_name} ({p.employee_id}) · {p.department_code or ''} · paid days {p.paid_days} · LOP {p.lop_days}</p>"
        + table("Earnings", earnings, ("Gross", p.gross_paise))
        + table("Deductions", deductions, ("Total deductions", p.deductions_paise))
        + f"<h2>Net pay {rupees(p.net_paise)}</h2>"
        + table("Employer contributions", employer, None)
        + "</body></html>"
    )
    return render_pdf(html, lines, title=f"Payslip {period}")


# ---- workflow hooks ------------------------------------------------------------------------------------------------
@workflow_engine.on(LOAN_KEY, "approved")
async def _on_loan_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    loan = await LoanRepository(db).get_any(instance.entity_id)
    if loan is not None and loan.status == "pending":
        loan.status = "active"
        await db.flush()


@workflow_engine.on(LOAN_KEY, "rejected")
async def _on_loan_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    loan = await LoanRepository(db).get_any(instance.entity_id)
    if loan is not None and loan.status == "pending":
        loan.status = "rejected"
        await db.flush()


@workflow_engine.summariser("loan_advance")
async def _summarise_loan(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    loan = await LoanRepository(db).get_any(entity_id)
    if loan is None:
        return None, None
    return f"{loan.loan_type.replace('_', ' ').title()} loan {rupees(loan.principal_paise)}", "/admin/hr/loans"
