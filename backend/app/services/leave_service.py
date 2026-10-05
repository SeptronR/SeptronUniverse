"""Leaves — Prompts/06 §06.6 ``leave_service.py``.

Rules
1. **Leave types** per institution (copied from the pack by ``seed_hr_defaults``). Balances are kept per (staff, type,
   year) and created lazily: ``yearly`` types are credited the annual quota, ``monthly`` types the months elapsed
   (Beat ``hr.leave_accrual`` adds one month's share on the 1st); ``none`` types without a quota (duty, study,
   sabbatical, LTC, LWP) are unlimited. Carry-forward at the leave-year start caps the previous balance at
   ``carry_forward_max`` (Beat ``hr.leave_carry_forward``). ``balance = opening + accrued − used − encashed``.
2. **Apply** (self): no overlap with a pending/approved leave (409); holidays and week-offs are excluded from
   ``days_count`` (``holidays`` rows that apply to staff + the ``hr.week_offs`` setting); a half day counts 0.5; a
   document is required above 3 days for types with ``requires_document`` (ML) → 422; the balance (minus pending
   requests) must cover paid leave → 422; the request starts workflow ``leave.approval`` (HOD of the member's
   department, then HR — the institution may edit the definition) and stays ``pending``.
3. **Hooks**: ``approved`` → ``approved``, ``used += days``, ``staff_attendance`` rows ``on_leave`` for the working
   days, event ``leave.approved`` (Phase 10 consumes it to request timetable substitutions), notification;
   ``rejected`` → ``rejected`` + notification. **Cancel** by the member while pending (workflow cancelled) or before the
   start of an approved leave (balance restored, attendance rows removed).
4. **Encashment** (``hr.leave_encashment``): request → workflow ``hr.leave_encashment`` → on approval ``encashed +=
   days`` and the payroll remuneration source adds ``(Basic + DA) ÷ 30 × days`` to the next run.
5. **Views**: ``self`` / ``team`` / ``all`` through ``hr_scope`` (``meta.visibility``), calendar feed, own balances.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.core.hr_hooks import RemunerationLine, remuneration_source
from app.core.workflow import engine as workflow_engine
from app.models.hr import LeaveType, Staff, StaffLeave, StaffLeaveBalance
from app.models.platform import WorkflowDefinition, WorkflowInstance, WorkflowStep
from app.repositories.hr_scope import hr_visibility
from app.repositories.leave_balance_repository import LeaveBalanceRepository
from app.repositories.leave_repository import LeaveRepository, LeaveTypeRepository
from app.repositories.payroll_repository import SalaryStructureRepository
from app.repositories.staff_attendance_repository import StaffAttendanceRepository
from app.schemas.leaves import (
    LeaveApply,
    LeaveBalanceResponse,
    LeaveCalendarItem,
    LeaveEncashRequest,
    LeaveEncashResult,
    LeaveResponse,
    LeaveTypeIn,
    LeaveTypeOut,
)
from app.services.hr.common import HrServiceBase, snap
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

WORKFLOW_KEY = "leave.approval"
ENCASH_KEY = "hr.leave_encashment"
ENTITY = "staff_leave"
LEAVE_KEYS = ("staff_id", "leave_type_id", "from_date", "to_date", "days_count", "status", "workflow_instance_id")
DOC_DAYS = Decimal(3)


class LeaveService(HrServiceBase):
    audit_module = "leaves"

    def __init__(self, db: Any, principal: Any, request: Any = None, institution_id: uuid.UUID | None = None):
        super().__init__(db, principal, request, institution_id)
        self.types = LeaveTypeRepository(db, principal, self.inst)
        self.repo = LeaveRepository(db, principal, self.inst)
        self.balances = LeaveBalanceRepository(db)
        self.attendance = StaffAttendanceRepository(db, None, self.inst)

    # ---- rule 1: types + balances -------------------------------------------------------------------------------
    async def list_types(self, include_inactive: bool = False) -> list[LeaveTypeOut]:
        return [LeaveTypeOut.model_validate(t) for t in await self.types.all(include_inactive)]

    async def create_type(self, body: LeaveTypeIn) -> LeaveTypeOut:
        if await self.types.by_code(body.code):
            raise APIError(409, ErrorCode.CONFLICT, f"Leave type {body.code.upper()} exists", {"field": "code"})
        values = body.model_dump()
        values["code"], values["accrual"] = body.code.upper(), body.accrual.value
        row = await self.types.create(institution_id=self.inst, **values)
        await self._audit(
            "create", "leave_type", row.id, None, {"code": row.code, "annual_quota": float(row.annual_quota or 0)}
        )
        return LeaveTypeOut.model_validate(row)

    async def update_type(self, type_id: uuid.UUID, body: LeaveTypeIn) -> LeaveTypeOut:
        row = await self.types.get_one(type_id)
        clash = await self.types.by_code(body.code)
        if clash is not None and clash.id != row.id:
            raise APIError(409, ErrorCode.CONFLICT, f"Leave type {body.code.upper()} exists", {"field": "code"})
        values = body.model_dump()
        values["code"], values["accrual"] = body.code.upper(), body.accrual.value
        old = snap(row, tuple(values))
        await self.types.update(row, **values)
        await self._audit("update", "leave_type", row.id, old, snap(row, tuple(values)))
        return LeaveTypeOut.model_validate(row)

    @staticmethod
    def unlimited(lt: LeaveType) -> bool:
        return lt.annual_quota is None or lt.accrual == "none" and not lt.annual_quota

    async def ensure_balance(
        self, staff: Staff, lt: LeaveType, year: int, *, for_update: bool = False
    ) -> StaffLeaveBalance | None:
        if self.unlimited(lt):
            return None
        row = await self.balances.get(staff.id, lt.id, year, for_update=for_update)
        if row is not None:
            return row
        quota = Decimal(lt.annual_quota or 0)
        today = await self.today()
        if lt.accrual == "monthly":
            months = 12 if year < today.year else (today.month if year == today.year else 0)
            accrued = (quota / 12 * months).quantize(Decimal("0.1"))
        else:
            accrued = quota
        opening = Decimal(0)
        previous = await self.balances.get(staff.id, lt.id, year - 1)
        if previous is not None:
            opening = min(Decimal(previous.balance), Decimal(lt.carry_forward_max or 0))
        row = await self.balances.create(self.inst, staff.id, lt.id, year, opening, accrued)
        if for_update:
            row = await self.balances.get(staff.id, lt.id, year, for_update=True) or row
        return row

    def _applies(self, lt: LeaveType, staff: Staff) -> bool:
        rules = lt.applies_to or {}
        if rules.get("genders") and staff.gender not in rules["genders"]:
            return False
        if rules.get("staff_categories") and staff.staff_category not in rules["staff_categories"]:
            return False
        return not (rules.get("employment_types") and staff.employment_type not in rules["employment_types"])

    async def balance_me(self, year: int | None) -> list[LeaveBalanceResponse]:
        staff = await self.my_staff()
        assert staff is not None
        return await self.balances_for(staff, year or (await self.today()).year)

    async def balances_for(self, staff: Staff, year: int) -> list[LeaveBalanceResponse]:
        pending = await self.repo.pending_days(staff.id, year)
        out: list[LeaveBalanceResponse] = []
        for lt in await self.types.all():
            if not self._applies(lt, staff):
                continue
            row = await self.ensure_balance(staff, lt, year)
            p = pending.get(lt.id, Decimal(0))
            if row is None:
                out.append(
                    LeaveBalanceResponse(
                        leave_type_id=lt.id,
                        code=lt.code,
                        name=lt.name,
                        year=year,
                        annual_quota=lt.annual_quota,
                        opening=Decimal(0),
                        accrued=Decimal(0),
                        used=Decimal(0),
                        encashed=Decimal(0),
                        balance=Decimal(0),
                        pending=p,
                        available=None,
                        is_paid=lt.is_paid,
                        is_encashable=lt.is_encashable,
                    )
                )
                continue
            out.append(
                LeaveBalanceResponse(
                    leave_type_id=lt.id,
                    code=lt.code,
                    name=lt.name,
                    year=year,
                    annual_quota=lt.annual_quota,
                    opening=row.opening,
                    accrued=row.accrued,
                    used=row.used,
                    encashed=row.encashed,
                    balance=row.balance,
                    pending=p,
                    available=Decimal(row.balance) - p,
                    is_paid=lt.is_paid,
                    is_encashable=lt.is_encashable,
                )
            )
        return out

    # ---- rule 2: apply ------------------------------------------------------------------------------------------
    async def working_days(self, staff: Staff, from_date: date, to_date: date) -> list[date]:
        offs = await self.off_days(from_date, to_date, staff.college_id)
        days, d = [], from_date
        while d <= to_date:
            if d not in offs:
                days.append(d)
            d += timedelta(days=1)
        return days

    async def apply(self, body: LeaveApply) -> LeaveResponse:
        staff = await self.my_staff()
        assert staff is not None
        if staff.status == "exited":
            raise APIError(422, ErrorCode.VALIDATION, "Exited staff cannot apply for leave")
        lt = await self.types.get_one(body.leave_type_id)
        if not lt.is_active or not self._applies(lt, staff):
            raise APIError(422, ErrorCode.VALIDATION, f"{lt.name} does not apply to you", {"field": "leave_type_id"})
        if body.from_date.year != body.to_date.year:
            raise APIError(422, ErrorCode.VALIDATION, "Split a leave that crosses the year end", {"field": "to_date"})
        working = await self.working_days(staff, body.from_date, body.to_date)
        if not working:
            raise APIError(
                422, ErrorCode.VALIDATION, "The dates fall entirely on holidays / week-offs", {"field": "from_date"}
            )
        days = Decimal("0.5") if body.half_day else Decimal(len(working))
        clash = await self.repo.overlapping(staff.id, body.from_date, body.to_date)
        if clash is not None:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"Overlaps your {clash.status} leave {clash.from_date.isoformat()} – {clash.to_date.isoformat()}",
                {"leave_id": str(clash.id)},
            )
        if lt.requires_document and days > DOC_DAYS and not body.document_url:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"{lt.name} above {DOC_DAYS} days needs a supporting document",
                {"field": "document_url"},
            )
        if lt.is_paid:
            bal = await self.ensure_balance(staff, lt, body.from_date.year, for_update=True)
            if bal is not None:
                pending = (await self.repo.pending_days(staff.id, body.from_date.year)).get(lt.id, Decimal(0))
                available = Decimal(bal.balance) - pending
                if days > available:
                    raise APIError(
                        422,
                        ErrorCode.VALIDATION,
                        f"Insufficient {lt.code} balance: {available} day(s) available",
                        {"field": "leave_type_id", "available": float(available), "requested": float(days)},
                    )
        leave = await self.repo.create(
            institution_id=self.inst,
            staff_id=staff.id,
            leave_type_id=lt.id,
            from_date=body.from_date,
            to_date=body.to_date,
            days_count=days,
            half_day=body.half_day.value if body.half_day else None,
            reason=body.reason,
            document_url=body.document_url,
            status="pending",
        )
        instance = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WORKFLOW_KEY,
            entity_type=ENTITY,
            entity_id=leave.id,
            started_by=self.principal.id,
            context={
                "department_id": str(staff.department_id) if staff.department_id else None,
                "college_id": str(staff.college_id) if staff.college_id else None,
                "staff_id": str(staff.id),
                "leave_type": lt.code,
                "days": float(days),
            },
            title=f"{lt.code} {float(days):g} day(s) — {staff.full_name} ({body.from_date.isoformat()} → {body.to_date.isoformat()})",
        )
        leave.workflow_instance_id = instance.id
        await self.db.flush()
        await self._audit("apply", "staff_leave", leave.id, None, snap(leave, LEAVE_KEYS))
        await self._emit(
            "leave.applied",
            {"leave_id": str(leave.id), "staff_id": str(staff.id), "days": float(days), "leave_type": lt.code},
            "staff_leave",
            leave.id,
        )
        return (await self._responses([leave]))[0]

    # ---- decisions ----------------------------------------------------------------------------------------------
    async def decide(self, leave_id: uuid.UUID, decision: str, comment: str | None) -> LeaveResponse:
        leave = await self.repo.get_visible(leave_id, for_update=True)
        if leave.status != "pending" or leave.workflow_instance_id is None:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The leave is {leave.status}")
        await workflow_engine.act(
            self.db, instance_id=leave.workflow_instance_id, actor=self.principal, decision=decision, comment=comment
        )
        await self.db.refresh(leave)
        return (await self._responses([leave]))[0]

    async def mark_approved(self, leave: StaffLeave, actor_id: uuid.UUID | None, comment: str | None) -> None:
        staff = await self.staff_repo.by_id(leave.staff_id)
        lt = await self.types.get_one(leave.leave_type_id)
        if staff is None:
            return
        leave.status, leave.reviewed_by, leave.reviewed_at = "approved", actor_id, datetime.now(UTC)
        leave.review_comment = comment
        bal = await self.ensure_balance(staff, lt, leave.from_date.year, for_update=True)
        if bal is not None and lt.is_paid:
            bal.used = Decimal(bal.used) + Decimal(leave.days_count)
            self.balances.recompute(bal)
        for day in await self.working_days(staff, leave.from_date, leave.to_date):
            row = await self.attendance.day(staff.id, day, for_update=True)
            if row is None:
                await self.attendance.add(
                    institution_id=self.inst,
                    staff_id=staff.id,
                    attendance_date=day,
                    status="on_leave",
                    source="manual",
                    remarks=f"{lt.code} leave",
                    marked_by=actor_id,
                )
            elif row.status in ("absent", "on_leave"):
                row.status, row.remarks = "on_leave", f"{lt.code} leave"
        await self.db.flush()
        await self._audit(
            "approve",
            "staff_leave",
            leave.id,
            {"status": "pending"},
            {"status": "approved", "used": float(bal.used) if bal else None},
        )
        await self._emit(
            "leave.approved",
            {
                "leave_id": str(leave.id),
                "staff_id": str(staff.id),
                "user_id": str(staff.user_id) if staff.user_id else None,
                "department_id": str(staff.department_id) if staff.department_id else None,
                "from_date": leave.from_date.isoformat(),
                "to_date": leave.to_date.isoformat(),
                "days": float(leave.days_count),
                "half_day": leave.half_day,
            },
            "staff_leave",
            leave.id,
        )
        await self._notify(
            "leave.approved",
            [staff.user_id],
            {
                "leave_type": lt.name,
                "from_date": leave.from_date.isoformat(),
                "to_date": leave.to_date.isoformat(),
                "days": f"{float(leave.days_count):g}",
            },
        )

    async def mark_rejected(self, leave: StaffLeave, actor_id: uuid.UUID | None, comment: str | None) -> None:
        staff = await self.staff_repo.by_id(leave.staff_id)
        lt = await self.types.get_one(leave.leave_type_id)
        leave.status, leave.reviewed_by, leave.reviewed_at, leave.review_comment = (
            "rejected",
            actor_id,
            datetime.now(UTC),
            comment,
        )
        await self.db.flush()
        await self._audit(
            "reject", "staff_leave", leave.id, {"status": "pending"}, {"status": "rejected", "comment": comment}
        )
        await self._emit(
            "leave.rejected", {"leave_id": str(leave.id), "staff_id": str(leave.staff_id)}, "staff_leave", leave.id
        )
        if staff is not None:
            await self._notify(
                "leave.rejected",
                [staff.user_id],
                {
                    "leave_type": lt.name,
                    "from_date": leave.from_date.isoformat(),
                    "to_date": leave.to_date.isoformat(),
                    "comment": comment or "",
                },
            )

    async def cancel(self, leave_id: uuid.UUID) -> LeaveResponse:
        leave = await self.repo.get_visible(leave_id, for_update=True)
        staff = await self.staff_repo.by_id(leave.staff_id)
        own = staff is not None and staff.user_id == self.principal.id
        if not own and not self.principal.has("leaves", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the applicant (or HR) can cancel a leave")
        today = await self.today()
        old = snap(leave, LEAVE_KEYS)
        if leave.status == "pending":
            if leave.workflow_instance_id is not None and own:
                await workflow_engine.cancel(
                    self.db, instance_id=leave.workflow_instance_id, actor=self.principal, reason="leave cancelled"
                )
            elif leave.workflow_instance_id is not None:
                await self._close_instance(leave.workflow_instance_id)
            leave.status = "cancelled"
        elif leave.status == "approved" and leave.from_date > today:
            lt = await self.types.get_one(leave.leave_type_id)
            assert staff is not None
            bal = await self.ensure_balance(staff, lt, leave.from_date.year, for_update=True)
            if bal is not None and lt.is_paid:
                bal.used = max(Decimal(0), Decimal(bal.used) - Decimal(leave.days_count))
                self.balances.recompute(bal)
            await self.attendance.remove_leave_rows(leave.staff_id, leave.from_date, leave.to_date)
            leave.status = "cancelled"
        else:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "Only pending leaves, or approved leaves before they start, can be cancelled",
            )
        await self.db.flush()
        await self._audit("cancel", "staff_leave", leave.id, old, snap(leave, LEAVE_KEYS))
        await self._emit(
            "leave.cancelled",
            {"leave_id": str(leave.id), "staff_id": str(leave.staff_id), "was": old["status"]},
            "staff_leave",
            leave.id,
        )
        return (await self._responses([leave]))[0]

    async def _close_instance(self, instance_id: uuid.UUID) -> None:
        """HR cancelling someone else's pending leave: close the workflow directly (the engine lets only the
        requester cancel)."""
        inst = (
            await self.db.execute(select(WorkflowInstance).where(WorkflowInstance.id == instance_id).with_for_update())
        ).scalar_one()
        for step in (
            await self.db.execute(
                select(WorkflowStep).where(
                    WorkflowStep.instance_id == instance_id, WorkflowStep.status.in_(("pending", "escalated"))
                )
            )
        ).scalars():
            step.status = "skipped"
        inst.status, inst.closed_at = "cancelled", datetime.now(UTC)

    # ---- rule 4: encashment -------------------------------------------------------------------------------------
    async def encash(self, body: LeaveEncashRequest) -> LeaveEncashResult:
        staff = await self.my_staff()
        assert staff is not None
        lt = await self.types.get_one(body.leave_type_id)
        if not lt.is_encashable:
            raise APIError(422, ErrorCode.VALIDATION, f"{lt.name} is not encashable", {"field": "leave_type_id"})
        year = (await self.today()).year
        bal = await self.ensure_balance(staff, lt, year, for_update=True)
        pending = (await self.repo.pending_days(staff.id, year)).get(lt.id, Decimal(0))
        available = (Decimal(bal.balance) - pending) if bal is not None else Decimal(0)
        if body.days > available:
            raise APIError(422, ErrorCode.VALIDATION, f"Only {available} day(s) can be encashed", {"field": "days"})
        amount = await self.encashment_amount(staff, body.days)
        entity_id = uuid.uuid4()
        instance = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=ENCASH_KEY,
            entity_type="leave_encashment",
            entity_id=entity_id,
            started_by=self.principal.id,
            context={
                "staff_id": str(staff.id),
                "department_id": str(staff.department_id) if staff.department_id else None,
                "college_id": str(staff.college_id) if staff.college_id else None,
                "leave_type_id": str(lt.id),
                "leave_type": lt.code,
                "days": float(body.days),
                "year": year,
                "amount_paise": amount,
                "reason": body.reason,
            },
            title=f"Encash {float(body.days):g} {lt.code} day(s) — {staff.full_name}",
        )
        await self._audit(
            "encash_request", "leave_encashment", instance.id, None, {"days": float(body.days), "amount_paise": amount}
        )
        return LeaveEncashResult(
            workflow_instance_id=instance.id,
            leave_type_code=lt.code,
            days=body.days,
            amount_paise=amount,
            status=instance.status,
        )

    async def encashment_amount(self, staff: Staff, days: Decimal) -> int:
        structure = await SalaryStructureRepository(self.db).effective(staff.id, await self.today())
        if structure is None:
            return 0
        da = structure.components.get("DA", {}) if isinstance(structure.components, dict) else {}
        da_pct = Decimal(str(da.get("pct", 50))) if "amount_paise" not in da else None
        da_amt = (
            Decimal(structure.basic_paise) * da_pct / 100 if da_pct is not None else Decimal(da.get("amount_paise", 0))
        )
        return int(((Decimal(structure.basic_paise) + da_amt) / 30 * days).quantize(Decimal(1)))

    # ---- rule 5: views ------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None, **filters: Any
    ) -> tuple[list[LeaveResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.repo.filtered(scope=scope, **filters)
        if not params.sort:
            params = params.model_copy(update={"sort": "-from_date"})
        rows, pagination = await self.repo.paginate(stmt, params)
        return await self._responses(list(rows)), pagination, hr_visibility(self.principal, "leaves")

    async def get(self, leave_id: uuid.UUID) -> LeaveResponse:
        return (await self._responses([await self.repo.get_visible(leave_id)]))[0]

    async def calendar(
        self, department_id: uuid.UUID | None, date_from: date, date_to: date
    ) -> list[LeaveCalendarItem]:
        stmt = self.repo.filtered(scope="all", department_id=department_id, date_from=date_from, date_to=date_to)
        stmt = stmt.where(StaffLeave.status.in_(("pending", "approved"))).order_by(StaffLeave.from_date)
        rows = list((await self.db.execute(stmt)).scalars().all())
        responses = await self._responses(rows)
        return [
            LeaveCalendarItem(
                id=r.id,
                staff_id=r.staff_id,
                staff_name=r.staff_name or "",
                department_code=r.department_code,
                leave_type_code=r.leave_type_code or "",
                from_date=r.from_date,
                to_date=r.to_date,
                days_count=r.days_count,
                status=r.status,
            )
            for r in responses
        ]

    async def _responses(self, rows: list[StaffLeave]) -> list[LeaveResponse]:
        staff_rows = (
            {s.id: s for s in await self.staff_repo.active(staff_ids=[r.staff_id for r in rows])} if rows else {}
        )
        for r in rows:
            if r.staff_id not in staff_rows:
                s = await self.staff_repo.by_id(r.staff_id)
                if s is not None:
                    staff_rows[s.id] = s
        depts = await self.staff_repo.department_rows([s.department_id for s in staff_rows.values() if s.department_id])
        types = await self.types.by_ids([r.leave_type_id for r in rows])
        instances = await self._instances([r.workflow_instance_id for r in rows if r.workflow_instance_id])
        actionable = await self._actionable([r.workflow_instance_id for r in rows if r.workflow_instance_id])
        out = []
        for r in rows:
            resp = LeaveResponse.model_validate(r)
            s = staff_rows.get(r.staff_id)
            if s is not None:
                resp.staff_name, resp.employee_id = s.full_name, s.employee_id
                resp.department_code = depts[s.department_id].code if s.department_id in depts else None
                resp.is_mine = s.user_id == getattr(self.principal, "id", None)
            lt = types.get(r.leave_type_id)
            if lt is not None:
                resp.leave_type_code, resp.leave_type_name = lt.code, lt.name
            inst = instances.get(r.workflow_instance_id) if r.workflow_instance_id else None
            if inst is not None:
                resp.workflow_status, resp.current_step = inst.status, inst.current_step
            resp.can_act = r.status == "pending" and r.workflow_instance_id in actionable
            out.append(resp)
        return out

    async def _instances(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, WorkflowInstance]:
        if not ids:
            return {}
        rows = (await self.db.execute(select(WorkflowInstance).where(WorkflowInstance.id.in_(ids)))).scalars().all()
        return {r.id: r for r in rows}

    async def _actionable(self, ids: list[uuid.UUID]) -> set[uuid.UUID]:
        if not ids or self.principal is None:
            return set()
        rows = (
            await self.db.execute(
                select(
                    WorkflowStep.instance_id,
                    WorkflowStep.approver_user_id,
                    WorkflowStep.approver_role_slug,
                    WorkflowStep.escalated_to,
                ).where(WorkflowStep.instance_id.in_(ids), WorkflowStep.status.in_(("pending", "escalated")))
            )
        ).all()
        out = set()
        for iid, user_id, role_slug, escalated_to in rows:
            if (
                user_id == self.principal.id
                or escalated_to == self.principal.id
                or (user_id is None and role_slug in self.principal.roles)
            ):
                out.add(iid)
        return out

    # ---- Beat ---------------------------------------------------------------------------------------------------
    async def accrue_month(self, today: date) -> int:
        """Credit one month of every ``monthly`` type to the current-year balances (Beat ``hr.leave_accrual``)."""
        monthly = [t for t in await self.types.all() if t.accrual == "monthly" and t.annual_quota]
        if not monthly:
            return 0
        share = {t.id: (Decimal(t.annual_quota or 0) / 12).quantize(Decimal("0.1")) for t in monthly}
        n = 0
        for row in await self.balances.for_year(today.year, list(share)):
            quota = Decimal(next(t.annual_quota for t in monthly if t.id == row.leave_type_id) or 0)
            if Decimal(row.accrued) + share[row.leave_type_id] <= quota:
                row.accrued = Decimal(row.accrued) + share[row.leave_type_id]
                self.balances.recompute(row)
                n += 1
        await self.db.flush()
        return n

    async def carry_forward(self, new_year: int) -> int:
        """Open the new leave year: ``opening = min(previous balance, carry_forward_max)`` (Beat
        ``hr.leave_carry_forward``). Rows are created only for staff who had a balance the previous year."""
        types = {t.id: t for t in await self.types.all()}
        n = 0
        for prev in await self.balances.for_year(new_year - 1, list(types)):
            lt = types[prev.leave_type_id]
            if await self.balances.get(prev.staff_id, lt.id, new_year) is not None:
                continue
            staff = await self.staff_repo.by_id(prev.staff_id)
            if staff is None or staff.status == "exited":
                continue
            await self.ensure_balance(staff, lt, new_year)
            n += 1
        return n


# ---- workflow hooks + inbox summaries --------------------------------------------------------------------------------
@workflow_engine.on(WORKFLOW_KEY, "approved")
async def _on_leave_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return  # e.g. the Phase 04 verification's dev instances of the same definition
    leave = await LeaveRepository(db).get_any(instance.entity_id, for_update=True)
    if leave is None or leave.status != "pending":
        return
    await LeaveService(db, actor, institution_id=instance.institution_id).mark_approved(
        leave, getattr(actor, "id", None), None
    )


@workflow_engine.on(WORKFLOW_KEY, "rejected")
async def _on_leave_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    leave = await LeaveRepository(db).get_any(instance.entity_id, for_update=True)
    if leave is None or leave.status != "pending":
        return
    comment = (
        await db.execute(
            select(WorkflowStep.comment)
            .where(WorkflowStep.instance_id == instance.id, WorkflowStep.status == "rejected")
            .order_by(WorkflowStep.acted_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    await LeaveService(db, actor, institution_id=instance.institution_id).mark_rejected(
        leave, getattr(actor, "id", None), comment
    )


@workflow_engine.on(ENCASH_KEY, "approved")
async def _on_encashment_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    ctx = dict(instance.context or {})
    try:
        staff_id, type_id, year = uuid.UUID(ctx["staff_id"]), uuid.UUID(ctx["leave_type_id"]), int(ctx["year"])
    except (KeyError, ValueError):
        return
    row = await LeaveBalanceRepository(db).get(staff_id, type_id, year, for_update=True)
    if row is not None:
        row.encashed = Decimal(row.encashed) + Decimal(str(ctx.get("days", 0)))
        LeaveBalanceRepository.recompute(row)
        await db.flush()


@workflow_engine.summariser(ENTITY)
async def _summarise_leave(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(StaffLeave, Staff, LeaveType)
            .join(Staff, Staff.id == StaffLeave.staff_id)
            .join(LeaveType, LeaveType.id == StaffLeave.leave_type_id)
            .where(StaffLeave.id == entity_id)
        )
    ).first()
    if row is None:
        return None, None
    leave, staff, lt = row
    return (
        f"{staff.full_name} · {lt.code} {float(leave.days_count):g} day(s) · {leave.from_date:%d %b} – {leave.to_date:%d %b}",
        f"/admin/hr/leaves?leave={entity_id}",
    )


@remuneration_source("leave_encashment")
async def _encashment_lines(db: Any, staff: Staff, month: int, year: int) -> list[RemunerationLine]:
    rows = (
        (
            await db.execute(
                select(WorkflowInstance)
                .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowInstance.definition_id)
                .where(
                    WorkflowDefinition.key == ENCASH_KEY,
                    WorkflowInstance.status == "approved",
                    WorkflowInstance.context["staff_id"].astext == str(staff.id),
                )
            )
        )
        .scalars()
        .all()
    )
    out = []
    for inst in rows:
        ctx = inst.context or {}
        amount = int(ctx.get("amount_paise") or 0)
        if amount > 0:
            out.append(
                RemunerationLine(
                    label=f"Leave encashment ({ctx.get('leave_type', '')} {float(ctx.get('days', 0)):g} d)",
                    amount_paise=amount,
                    source_type="leave_encashment",
                    source_id=inst.id,
                )
            )
    return out
