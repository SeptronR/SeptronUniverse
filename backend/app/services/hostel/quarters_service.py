"""Staff quarters — Prompts/20 §20.6 ``quarters_service`` (feature ``hostel.staff_quarters``).

Quarters master (unit code, type, rent) and allocations (one open allocation per quarter — ``one_active_quarter``,
409 ``QUARTER_OCCUPIED``). ``rent_deduction`` allocations emit ``payroll.deduction_requested``; the Phase 06 payroll run
reads them through the remuneration hook ``staff_quarter`` (``app/tasks/hostel.py``), which adds a ``deduction`` line
for every month the allocation covers; vacating closes the allocation (``to_on``) and the deduction stops.
Estate / hostel managers (``hostel:manage``) administer quarters; staff read their own allocation.
"""

import uuid
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.hostel import StaffQuarter, StaffQuarterAllocation
from app.models.hr import Staff
from app.schemas.hostel import QuarterAllocate, QuarterIn, QuarterOut, QuarterVacate
from app.services.hostel.common import HostelBase, rule


class QuartersService(HostelBase):
    async def outs(self, rows: list[StaffQuarter]) -> list[QuarterOut]:
        allocs = {
            a.quarter_id: a
            for a in (
                await self.db.execute(
                    select(StaffQuarterAllocation).where(
                        StaffQuarterAllocation.quarter_id.in_([q.id for q in rows] or [uuid.uuid4()]),
                        StaffQuarterAllocation.to_on.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        }
        names: dict[Any, Any] = {
            s.id: " ".join(x for x in (s.first_name, s.last_name) if x)
            for s in (
                await self.db.execute(
                    select(Staff).where(Staff.id.in_({a.staff_id for a in allocs.values()} or {uuid.uuid4()}))
                )
            )
            .scalars()
            .all()
        }
        return [
            QuarterOut(
                id=q.id,
                college_id=q.college_id,
                unit_code=q.unit_code,
                quarter_type=q.quarter_type,
                rent_paise=q.rent_paise,
                status=q.status,
                allocation_id=allocs[q.id].id if q.id in allocs else None,
                occupant=names.get(allocs[q.id].staff_id) if q.id in allocs else None,
                occupant_staff_id=allocs[q.id].staff_id if q.id in allocs else None,
                from_on=allocs[q.id].from_on if q.id in allocs else None,
                rent_deduction=allocs[q.id].rent_deduction if q.id in allocs else None,
            )
            for q in rows
        ]

    async def list_quarters(self, college_id: uuid.UUID | None = None) -> list[QuarterOut]:
        self.require("manage", "view_all")
        q = select(StaffQuarter).where(StaffQuarter.institution_id == self.inst)
        colleges = [sid for t, sid in getattr(self.principal, "scopes", []) if t == "college"]
        institution = (
            self.principal is None
            or getattr(self.principal, "is_super_admin", False)
            or any(t == "institution" for t, _ in getattr(self.principal, "scopes", []))
        )
        if not institution and colleges:
            q = q.where(StaffQuarter.college_id.in_(colleges))
        if college_id:
            q = q.where(StaffQuarter.college_id == college_id)
        return await self.outs(list((await self.db.execute(q.order_by(StaffQuarter.unit_code))).scalars().all()))

    async def save(self, body: QuarterIn, qid: uuid.UUID | None = None) -> QuarterOut:
        self.require("manage")
        q: StaffQuarter | None
        if qid is None:
            q = StaffQuarter(institution_id=self.inst, **body.model_dump(exclude_none=True))
            self.db.add(q)
        else:
            q = (
                await self.db.execute(
                    select(StaffQuarter).where(StaffQuarter.id == qid, StaffQuarter.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if q is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Quarter not found")
            for k, v in body.model_dump(exclude_none=True).items():
                setattr(q, k, v)
        await self.db.flush()
        await self.db.refresh(q)
        await self._audit("quarter_save", "staff_quarter", q.id, None, body.model_dump(mode="json"))
        return (await self.outs([q]))[0]

    async def allocate(self, qid: uuid.UUID, body: QuarterAllocate) -> QuarterOut:
        self.require("manage")
        q = (
            await self.db.execute(
                select(StaffQuarter)
                .where(StaffQuarter.id == qid, StaffQuarter.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if q is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Quarter not found")
        open_alloc = (
            await self.db.execute(
                select(StaffQuarterAllocation.id).where(
                    StaffQuarterAllocation.quarter_id == q.id, StaffQuarterAllocation.to_on.is_(None)
                )
            )
        ).first()
        if open_alloc or q.status == "allocated":
            raise rule("The quarter is occupied", "QUARTER_OCCUPIED")
        if q.status == "maintenance":
            raise rule("The quarter is under maintenance", "QUARTER_MAINTENANCE")
        staff = (
            await self.db.execute(
                select(Staff).where(
                    Staff.id == body.staff_id, Staff.institution_id == self.inst, Staff.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if staff is None:
            raise APIError(422, ErrorCode.VALIDATION, "Staff not found", {"field": "staff_id"})
        a = StaffQuarterAllocation(
            institution_id=self.inst,
            quarter_id=q.id,
            staff_id=staff.id,
            from_on=body.from_on or await self.today(),
            rent_deduction=body.rent_deduction,
        )
        self.db.add(a)
        q.status = "allocated"
        await self.db.flush()
        await self._audit(
            "quarter_allocate",
            "staff_quarter",
            q.id,
            None,
            {"staff_id": str(staff.id), "rent_deduction": body.rent_deduction},
        )
        await self._emit(
            "hostel.quarter_allocated", {"allocation_id": str(a.id), "staff_id": str(staff.id)}, "staff_quarter", q.id
        )
        if body.rent_deduction and q.rent_paise:
            await self._emit(
                "payroll.deduction_requested",
                {
                    "staff_id": str(staff.id),
                    "source_type": "staff_quarter",
                    "source_id": str(a.id),
                    "amount_paise": q.rent_paise,
                    "from_on": a.from_on.isoformat(),
                },
                "staff_quarter_allocation",
                a.id,
            )
        return (await self.outs([q]))[0]

    async def vacate(self, alloc_id: uuid.UUID, body: QuarterVacate) -> QuarterOut:
        self.require("manage")
        a = (
            await self.db.execute(
                select(StaffQuarterAllocation)
                .where(StaffQuarterAllocation.id == alloc_id, StaffQuarterAllocation.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Allocation not found")
        if a.to_on is not None:
            raise rule("Already vacated", "ALREADY_VACATED")
        a.to_on = body.to_on or await self.today()
        q = (
            await self.db.execute(select(StaffQuarter).where(StaffQuarter.id == a.quarter_id).with_for_update())
        ).scalar_one()
        q.status = "vacant"
        await self.db.flush()
        await self._audit("quarter_vacate", "staff_quarter", q.id, None, {"to_on": a.to_on.isoformat()})
        await self._emit("hostel.quarter_vacated", {"allocation_id": str(a.id)}, "staff_quarter", q.id)
        return (await self.outs([q]))[0]

    async def me(self) -> list[QuarterOut]:
        staff_ids = select(Staff.id).where(Staff.user_id == getattr(self.principal, "id", None))
        ids = (
            (
                await self.db.execute(
                    select(StaffQuarterAllocation.quarter_id).where(
                        StaffQuarterAllocation.staff_id.in_(staff_ids), StaffQuarterAllocation.to_on.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        rows = list(
            (await self.db.execute(select(StaffQuarter).where(StaffQuarter.id.in_(list(ids) or [uuid.uuid4()]))))
            .scalars()
            .all()
        )
        return await self.outs(rows)
