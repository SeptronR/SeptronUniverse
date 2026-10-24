"""Budgets — Prompts/23 §23.6 ``budget_service`` (``accounting.budgets``).

Heads per year × college × department × name (UNIQUE) start ``draft``; ``submit`` (one head or every draft of a year)
runs ``accounting.budget_allocation`` (accountant → vice-chancellor / principal) — an ``accounting:approve`` holder may
also approve directly; ``approved → frozen`` at year close. Revisions and transfers lock both heads ``FOR UPDATE`` and
are audited. Commitments come from ``budget.commit_requested/released`` (Phase 22 indents / POs apply them in place —
their events carry ``applied: true`` and are only acknowledged here); utilisation from approved expenses.
``available = allocated − utilised − committed``; ``accounting.budget_hard_stop`` → 409 ``BUDGET_EXCEEDED`` else a
warning; alerts to the HOD and accountant when utilisation crosses 80 % and 100 %.
"""

import uuid
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.academic import AcademicYear
from app.models.accounting import BudgetHead
from app.models.hr import Staff
from app.models.platform import Department, UserRole, WorkflowInstance
from app.schemas.accounting import (
    BudgetBulkAllocate,
    BudgetHeadIn,
    BudgetHeadOut,
    BudgetHeadUpdate,
    BudgetRevise,
    BudgetTransfer,
)
from app.services.accounting.common import AccountingBase, _ids, dept_ids, now_utc, pairs, rule, unit_predicate
from app.services.students.common import snap

KEYS = ("allocated_paise", "utilised_paise", "committed_paise", "status")
THRESHOLDS = (80, 100)


def budget_predicate(p: Any) -> Any:
    return unit_predicate(p, BudgetHead.department_id, BudgetHead.college_id)


class BudgetService(AccountingBase):
    async def outs(self, rows: list[BudgetHead]) -> list[BudgetHeadOut]:
        depts = pairs(
            (
                await self.db.execute(
                    select(Department.id, Department.code).where(
                        Department.id.in_({r.department_id for r in rows if r.department_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        out = []
        for r in rows:
            avail = int(r.allocated_paise) - int(r.utilised_paise) - int(r.committed_paise)
            out.append(
                BudgetHeadOut(
                    id=r.id,
                    academic_year_id=r.academic_year_id,
                    college_id=r.college_id,
                    department_id=r.department_id,
                    department_code=depts.get(r.department_id) if r.department_id else None,
                    name=r.name,
                    ledger_account_id=r.ledger_account_id,
                    allocated_paise=int(r.allocated_paise),
                    utilised_paise=int(r.utilised_paise),
                    committed_paise=int(r.committed_paise),
                    available_paise=avail,
                    pct=round(100 * (int(r.utilised_paise) + int(r.committed_paise)) / int(r.allocated_paise), 1)
                    if r.allocated_paise
                    else 0.0,
                    status=r.status,
                )
            )
        return out

    async def year_now(self) -> AcademicYear:
        y = (
            await self.db.execute(
                select(AcademicYear)
                .where(AcademicYear.institution_id == self.inst)
                .order_by(AcademicYear.is_current.desc(), AcademicYear.start_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if y is None:
            raise rule("No academic year configured", "NO_ACADEMIC_YEAR")
        return y

    async def heads(
        self,
        year_id: uuid.UUID | None = None,
        college_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[BudgetHeadOut]:
        q = select(BudgetHead).where(BudgetHead.institution_id == self.inst, budget_predicate(self.principal))
        q = q.where(BudgetHead.academic_year_id == (year_id or (await self.year_now()).id))
        if college_id:
            q = q.where(BudgetHead.college_id == college_id)
        if department_id:
            q = q.where(BudgetHead.department_id == department_id)
        if status:
            q = q.where(BudgetHead.status == status)
        return await self.outs(list((await self.db.execute(q.order_by(BudgetHead.name))).scalars()))

    async def mine(self) -> list[BudgetHeadOut]:
        depts: Any = (
            dept_ids(self.principal)
            if (_ids(self.principal, "department") or _ids(self.principal, "faculty"))
            else None
        )
        if depts is None:
            sid = await self.my_staff_id()
            d = (
                (await self.db.execute(select(Staff.department_id).where(Staff.id == sid))).scalar_one_or_none()
                if sid
                else None
            )
            if d is None:
                return []
            depts = [d]
        year = await self.year_now()
        rows = (
            await self.db.execute(
                select(BudgetHead)
                .where(
                    BudgetHead.institution_id == self.inst,
                    BudgetHead.academic_year_id == year.id,
                    BudgetHead.department_id.in_(depts),
                )
                .order_by(BudgetHead.name)
            )
        ).scalars()
        return await self.outs(list(rows))

    async def row(self, head_id: uuid.UUID, *, for_update: bool = False, any_scope: bool = False) -> BudgetHead:
        q = select(BudgetHead).where(BudgetHead.id == head_id, BudgetHead.institution_id == self.inst)
        if not any_scope:
            q = q.where(budget_predicate(self.principal))
        if for_update:
            q = q.with_for_update()
        r = (await self.db.execute(q)).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Budget head not found")
        return r

    async def get(self, head_id: uuid.UUID) -> BudgetHeadOut:
        return (await self.outs([await self.row(head_id)]))[0]

    async def create(self, body: BudgetHeadIn) -> BudgetHeadOut:
        self.require("manage")
        exists = (
            await self.db.execute(
                select(BudgetHead.id).where(
                    BudgetHead.academic_year_id == body.academic_year_id,
                    BudgetHead.college_id.is_(body.college_id)
                    if body.college_id is None
                    else BudgetHead.college_id == body.college_id,
                    BudgetHead.department_id.is_(body.department_id)
                    if body.department_id is None
                    else BudgetHead.department_id == body.department_id,
                    BudgetHead.name == body.name,
                )
            )
        ).first()
        if exists:
            raise rule("A head with this name exists for the year and unit", "DUPLICATE_HEAD")
        if body.college_id is None and body.department_id:
            body = body.model_copy(
                update={
                    "college_id": (
                        await self.db.execute(select(Department.college_id).where(Department.id == body.department_id))
                    ).scalar_one_or_none()
                }
            )
        r = BudgetHead(institution_id=self.inst, **body.model_dump(), status="draft")
        self.db.add(r)
        await self.db.flush()
        await self._audit("create", "budget_head", r.id, None, snap(r, KEYS) | {"name": r.name})
        return (await self.outs([r]))[0]

    async def bulk(self, body: BudgetBulkAllocate) -> dict[str, Any]:
        self.require("manage")
        rep: dict[str, Any] = {"created": 0, "failed": []}
        for n, row in enumerate(body.rows):
            try:
                async with self.db.begin_nested():
                    await self.create(row.model_copy(update={"academic_year_id": body.academic_year_id}))
                rep["created"] += 1
            except APIError as exc:
                rep["failed"].append({"row": n, "message": exc.message})
        return rep

    async def update(self, head_id: uuid.UUID, body: BudgetHeadUpdate) -> BudgetHeadOut:
        self.require("manage")
        r = await self.row(head_id, for_update=True)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(r, k, v)
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def submit(self, head_id: uuid.UUID | None, year_id: uuid.UUID | None = None) -> list[BudgetHeadOut]:
        self.require("manage")
        if head_id:
            rows = [await self.row(head_id, for_update=True)]
        else:
            yid = year_id or (await self.year_now()).id
            rows = list(
                (
                    await self.db.execute(
                        select(BudgetHead)
                        .where(
                            BudgetHead.institution_id == self.inst,
                            BudgetHead.academic_year_id == yid,
                            BudgetHead.status == "draft",
                        )
                        .with_for_update()
                    )
                ).scalars()
            )
        rows = [r for r in rows if r.status == "draft"]
        if not rows:
            raise rule("No draft heads to submit", "NOTHING_TO_SUBMIT")
        batch = uuid.uuid4()
        total = sum(int(r.allocated_paise) for r in rows)
        await self.put_meta("budget_batch", batch, {"head_ids": [str(r.id) for r in rows], "at": now_utc().isoformat()})
        await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key="accounting.budget_allocation",
            entity_type="budget_batch",
            entity_id=batch,
            started_by=self.actor_id,
            context={"amount_paise": total, "heads": len(rows)},
            title=f"Budget allocation · {len(rows)} head(s) · ₹{total / 100:,.0f}",
        )
        for r in rows:
            r.status = "submitted"
        await self.db.flush()
        return await self.outs(rows)

    async def approve(self, head_ids: list[uuid.UUID], *, via_workflow: bool = False) -> list[BudgetHeadOut]:
        if not via_workflow:
            self.require("approve")
        rows = list(
            (
                await self.db.execute(
                    select(BudgetHead)
                    .where(BudgetHead.id.in_(head_ids), BudgetHead.institution_id == self.inst)
                    .with_for_update()
                )
            ).scalars()
        )
        for r in rows:
            if r.status in ("draft", "submitted"):
                r.status = "approved"
                await self._emit(
                    "accounting.budget_allocated",
                    {"budget_head_id": str(r.id), "allocated_paise": int(r.allocated_paise)},
                    "budget_head",
                    r.id,
                )
        await self.db.flush()
        await self._audit("approve", "budget_head", None, None, {"heads": [str(r.id) for r in rows]})
        return await self.outs(rows)

    async def revise(self, head_id: uuid.UUID, body: BudgetRevise) -> BudgetHeadOut:
        self.require("manage")
        r = await self.row(head_id, for_update=True)
        if r.status in ("frozen", "closed"):
            raise rule("The head is frozen", "BUDGET_FROZEN")
        if body.allocated_paise < int(r.utilised_paise) + int(r.committed_paise):
            raise rule("The new allocation is below what is already used or committed", "BELOW_USAGE")
        old = snap(r, KEYS)
        r.allocated_paise = body.allocated_paise
        await self.db.flush()
        await self._audit("revise", "budget_head", r.id, old, snap(r, KEYS) | {"reason": body.reason})
        await self._emit(
            "accounting.budget_revised",
            {"budget_head_id": str(r.id), "allocated_paise": body.allocated_paise},
            "budget_head",
            r.id,
        )
        return (await self.outs([r]))[0]

    async def transfer(self, body: BudgetTransfer) -> list[BudgetHeadOut]:
        self.require("manage")
        if body.from_head_id == body.to_head_id:
            raise APIError(422, ErrorCode.VALIDATION, "Pick two different heads")
        a, b = sorted([body.from_head_id, body.to_head_id], key=str)  # lock order avoids deadlocks
        ra, rb = await self.row(a, for_update=True), await self.row(b, for_update=True)
        src, dst = (ra, rb) if ra.id == body.from_head_id else (rb, ra)
        for h in (src, dst):
            if h.status in ("frozen", "closed"):
                raise rule("A frozen head cannot take part in a transfer", "BUDGET_FROZEN")
        available = int(src.allocated_paise) - int(src.utilised_paise) - int(src.committed_paise)
        if body.amount_paise > available:
            raise rule("Not enough available in the source head", "BUDGET_EXCEEDED", available=available)
        src.allocated_paise = int(src.allocated_paise) - body.amount_paise
        dst.allocated_paise = int(dst.allocated_paise) + body.amount_paise
        await self.db.flush()
        await self._audit(
            "transfer",
            "budget_head",
            src.id,
            None,
            {"to": str(dst.id), "amount_paise": body.amount_paise, "reason": body.reason},
        )
        await self._emit(
            "accounting.budget_transferred",
            {"from": str(src.id), "to": str(dst.id), "amount_paise": body.amount_paise},
            "budget_head",
            src.id,
        )
        return await self.outs([src, dst])

    async def freeze(self, head_id: uuid.UUID) -> BudgetHeadOut:
        self.require("manage")
        r = await self.row(head_id, for_update=True)
        r.status = "frozen"
        await self._audit("freeze", "budget_head", r.id, None, None)
        return (await self.outs([r]))[0]

    # ---- controls -------------------------------------------------------------------------------------------------------
    async def room(self, head_id: uuid.UUID, amount: int, *, exclude: int = 0) -> tuple[BudgetHead, str | None]:
        h = await self.row(head_id, for_update=True, any_scope=True)
        if h.status in ("frozen", "closed"):
            raise rule("The budget head is frozen", "BUDGET_FROZEN")
        if h.status != "approved":
            raise rule("The budget head is not approved yet", "BUDGET_NOT_APPROVED")
        available = int(h.allocated_paise) - int(h.utilised_paise) - int(h.committed_paise) + exclude
        if amount <= available:
            return h, None
        hard = await self.setting("accounting", "budget_hard_stop")
        if hard is None or bool(hard):
            await self._emit(
                "accounting.budget_exceeded",
                {"budget_head_id": str(h.id), "requested_paise": amount, "available_paise": available},
                "budget_head",
                h.id,
            )
            raise rule(
                "The budget head does not have enough room", "BUDGET_EXCEEDED", available=available, requested=amount
            )
        return h, "BUDGET_EXCEEDED"

    async def utilise(self, head_id: uuid.UUID, amount: int) -> None:
        h = await self.row(head_id, for_update=True, any_scope=True)
        before = self._pct(h)
        h.utilised_paise = int(h.utilised_paise) + amount
        await self.db.flush()
        await self._threshold(h, before)

    async def commit(self, head_id: uuid.UUID, amount: int, *, release: bool = False) -> None:
        h = await self.row(head_id, for_update=True, any_scope=True)
        before = self._pct(h)
        h.committed_paise = max(0, int(h.committed_paise) + (-amount if release else amount))
        await self.db.flush()
        if not release:
            await self._threshold(h, before)

    @staticmethod
    def _pct(h: BudgetHead) -> float:
        return (
            100 * (int(h.utilised_paise) + int(h.committed_paise)) / int(h.allocated_paise)
            if h.allocated_paise
            else 0.0
        )

    async def _threshold(self, h: BudgetHead, before: float) -> None:
        now = self._pct(h)
        for t in THRESHOLDS:
            if before < t <= now:
                users = await self.hod_users(h.department_id)
                await self._notify(
                    "accounting.budget_threshold",
                    users,
                    {"head": h.name, "pct": t},
                    audience={"user_ids": [str(u) for u in users], "roles": ["accountant"]},
                )
                await self._emit(
                    "accounting.budget_threshold", {"budget_head_id": str(h.id), "pct": t}, "budget_head", h.id
                )

    async def hod_users(self, department_id: uuid.UUID | None) -> list[uuid.UUID]:
        if department_id is None:
            return []
        from app.models.platform import Role

        return list(
            (
                await self.db.execute(
                    select(UserRole.user_id)
                    .join(Role, Role.id == UserRole.role_id)
                    .where(Role.slug == "hod", UserRole.scope_type == "department", UserRole.scope_id == department_id)
                )
            ).scalars()
        )

    async def threshold_scan(self) -> int:
        y = await self.year_now()
        n = 0
        for h in (
            await self.db.execute(
                select(BudgetHead).where(
                    BudgetHead.institution_id == self.inst,
                    BudgetHead.academic_year_id == y.id,
                    BudgetHead.status == "approved",
                )
            )
        ).scalars():
            pct = self._pct(h)
            if pct >= 80:  # noqa: PLR2004
                key = f"{h.id}:{100 if pct >= 100 else 80}"  # noqa: PLR2004
                if (await self.meta("budget_alert", key)).get("sent"):
                    continue
                await self._threshold(h, 0 if pct < 100 else 80)  # noqa: PLR2004
                await self.put_meta("budget_alert", key, {"sent": now_utc().isoformat()})
                n += 1
        return n

    async def utilisation(
        self,
        year_id: uuid.UUID | None = None,
        college_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        heads = await self.heads(year_id, college_id, department_id)
        agg: dict[str, dict[str, int]] = {}
        for h in heads:
            a = agg.setdefault(
                h.department_code or "institution", {"allocated_paise": 0, "utilised_paise": 0, "committed_paise": 0}
            )
            a["allocated_paise"] += h.allocated_paise
            a["utilised_paise"] += h.utilised_paise
            a["committed_paise"] += h.committed_paise
        return [
            {
                "department": k,
                **v,
                "pct": round(100 * v["utilised_paise"] / v["allocated_paise"], 1) if v["allocated_paise"] else 0.0,
            }
            for k, v in sorted(agg.items())
        ]

    async def year_close(self, year_id: uuid.UUID, carry_forward: str = "none") -> dict[str, Any]:
        self.require("manage")
        rows = list(
            (
                await self.db.execute(
                    select(BudgetHead)
                    .where(BudgetHead.institution_id == self.inst, BudgetHead.academic_year_id == year_id)
                    .with_for_update()
                )
            ).scalars()
        )
        nxt = (
            await self.db.execute(
                select(AcademicYear)
                .where(
                    AcademicYear.institution_id == self.inst,
                    AcademicYear.start_date
                    > select(AcademicYear.start_date).where(AcademicYear.id == year_id).scalar_subquery(),
                )
                .order_by(AcademicYear.start_date)
                .limit(1)
            )
        ).scalar_one_or_none()
        carried = 0
        for r in rows:
            r.status = "frozen"
            unspent = int(r.allocated_paise) - int(r.utilised_paise) - int(r.committed_paise)
            if carry_forward == "unspent" and nxt is not None and unspent > 0:
                existing = (
                    await self.db.execute(
                        select(BudgetHead).where(
                            BudgetHead.academic_year_id == nxt.id,
                            BudgetHead.department_id.is_(r.department_id)
                            if r.department_id is None
                            else BudgetHead.department_id == r.department_id,
                            BudgetHead.name == r.name,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    self.db.add(
                        BudgetHead(
                            institution_id=self.inst,
                            academic_year_id=nxt.id,
                            college_id=r.college_id,
                            department_id=r.department_id,
                            name=r.name,
                            ledger_account_id=r.ledger_account_id,
                            allocated_paise=unspent,
                            status="draft",
                        )
                    )
                else:
                    existing.allocated_paise = int(existing.allocated_paise) + unspent
                carried += unspent
        await self.db.flush()
        out = {"frozen": len(rows), "carried_forward_paise": carried, "next_year": str(nxt.id) if nxt else None}
        await self._audit("year_close", "budget_head", None, None, out)
        await self._emit("accounting.period_closed", {"academic_year_id": str(year_id), **out}, "budget_head", None)
        return out


@workflow_engine.on("accounting.budget_allocation", "approved")
async def _budget_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    svc = BudgetService(db, actor, institution_id=instance.institution_id)
    ids = [uuid.UUID(x) for x in (await svc.meta("budget_batch", instance.entity_id)).get("head_ids", [])]
    if ids:
        await svc.approve(ids, via_workflow=True)


@workflow_engine.on("accounting.budget_allocation", "rejected")
async def _budget_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    svc = BudgetService(db, actor, institution_id=instance.institution_id)
    ids = [uuid.UUID(x) for x in (await svc.meta("budget_batch", instance.entity_id)).get("head_ids", [])]
    for r in (await db.execute(select(BudgetHead).where(BudgetHead.id.in_(ids or [uuid.uuid4()])))).scalars():
        if r.status == "submitted":
            r.status = "draft"
