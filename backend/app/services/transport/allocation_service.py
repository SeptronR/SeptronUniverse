"""Allocations — Prompts/21 §21.6 ``allocation_service`` (``transport.core``; ``transport.staff`` for staff,
``transport.fees`` for invoices).

1. One live (active / suspended / pending) allocation per person (409 ``ALREADY_ALLOCATED``); capacity
   ``count(live) < vehicle.capacity`` under ``FOR UPDATE`` on the route (409 ``CAPACITY_FULL`` with
   ``transport.capacity_hard_limit``, else allowed with ``warning=CAPACITY_EXCEEDED``); a student's fee invoice
   (``source_type='transport_allocation'``, stop fee, falling back to the route fee) when ``transport.fees`` is on; staff
   choose a payroll deduction instead (``payroll.deduction_requested``).
2. Bulk allocation with a partial-success report; change of route / stop from an effective date closes the old row and
   opens a new one — with ``transport.prorata_change`` the fee difference for the rest of the year is invoiced.
3. Self-service requests (``transport.self_service_requests``) are ``pending`` rows a manager approves (→ active +
   invoice) or rejects — a simple status, no workflow.
4. Nightly: unpaid invoice past ``transport.fee_grace_days`` → ``suspended`` (boarding scans warn the driver);
   ``fees.payment_received`` → ``active`` again; the year-end job closes allocations whose year / ``to_on`` has passed.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.transport import LIVE_ALLOCATION
from app.models.academic import AcademicYear
from app.models.fees import FeeInvoice
from app.models.hr import Staff
from app.models.platform import Department
from app.models.students import Student, StudentProgramEnrollment
from app.models.transport import TransportAllocation, TransportRoute, TransportStop, TransportTrip, Vehicle
from app.schemas.transport import (
    AllocationBulk,
    AllocationBulkReport,
    AllocationChange,
    AllocationCreate,
    AllocationResponse,
    MyTransportResponse,
    TransportRequestCreate,
    TransportRequestDecision,
    TripBrief,
)
from app.services.students.common import snap
from app.services.transport.common import TransportBase, allocation_predicate, rule

KEYS = ("person_type", "person_id", "route_id", "stop_id", "status", "from_on", "to_on", "fee_invoice_id")
PENDING_OR_LIVE = (*LIVE_ALLOCATION, "pending")


class AllocationService(TransportBase):
    # ---- read -------------------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[TransportAllocation]) -> list[AllocationResponse]:
        stu_ids = [a.person_id for a in rows if a.person_type == "student"]
        stf_ids = [a.person_id for a in rows if a.person_type == "staff"]
        people: dict[uuid.UUID, tuple[str, str | None, str | None]] = {}
        if stu_ids:
            for s, dcode in (
                await self.db.execute(
                    select(Student, Department.code)
                    .outerjoin(
                        StudentProgramEnrollment,
                        (StudentProgramEnrollment.student_id == Student.id)
                        & (StudentProgramEnrollment.status == "active"),
                    )
                    .outerjoin(Department, Department.id == StudentProgramEnrollment.department_id)
                    .where(Student.id.in_(stu_ids))
                )
            ).all():
                people[s.id] = (s.full_name, s.registration_number, dcode)
        if stf_ids:
            for s, dcode in (
                await self.db.execute(
                    select(Staff, Department.code)
                    .outerjoin(Department, Department.id == Staff.department_id)
                    .where(Staff.id.in_(stf_ids))
                )
            ).all():
                people[s.id] = (s.full_name, s.employee_id, dcode)
        routes = {
            r.id: r
            for r in (
                await self.db.execute(
                    select(TransportRoute).where(TransportRoute.id.in_({a.route_id for a in rows} or {uuid.uuid4()}))
                )
            ).scalars()
        }
        stops = {
            s.id: s
            for s in (
                await self.db.execute(
                    select(TransportStop).where(
                        TransportStop.id.in_({a.stop_id for a in rows if a.stop_id} or {uuid.uuid4()})
                    )
                )
            ).scalars()
        }
        invoices = {
            i.id: i
            for i in (
                await self.db.execute(
                    select(FeeInvoice).where(
                        FeeInvoice.id.in_({a.fee_invoice_id for a in rows if a.fee_invoice_id} or {uuid.uuid4()})
                    )
                )
            ).scalars()
        }
        out = []
        for a in rows:
            name, code, dept = people.get(a.person_id, (None, None, None))
            r, s = routes.get(a.route_id), stops.get(a.stop_id) if a.stop_id else None
            inv = invoices.get(a.fee_invoice_id) if a.fee_invoice_id else None
            out.append(
                AllocationResponse(
                    id=a.id,
                    person_type=a.person_type,
                    person_id=a.person_id,
                    person_name=name,
                    person_code=code,
                    department_code=dept,
                    route_id=a.route_id,
                    route_code=r.code if r else None,
                    stop_id=a.stop_id,
                    stop_name=s.name if s else None,
                    academic_year_id=a.academic_year_id,
                    from_on=a.from_on,
                    to_on=a.to_on,
                    fee_paise=self.fee_of(r, s),
                    invoice_id=a.fee_invoice_id,
                    fee_status=(inv.status if inv else None),
                    status=a.status,
                )
            )
        return out

    @staticmethod
    def fee_of(r: TransportRoute | None, s: TransportStop | None) -> int:
        if s is not None and s.fee_paise is not None:
            return int(s.fee_paise)
        return int(r.fee_paise or 0) if r else 0

    async def list_allocations(
        self,
        route_id: uuid.UUID | None = None,
        status: str | None = None,
        person_type: str | None = None,
        department_id: uuid.UUID | None = None,
        scope: str | None = None,
    ) -> list[AllocationResponse]:
        A = TransportAllocation
        q = select(A).where(
            A.institution_id == self.inst, allocation_predicate(self.principal, department_only=scope == "department")
        )
        if route_id:
            q = q.where(A.route_id == route_id)
        if status:
            q = q.where(A.status == status)
        if person_type:
            q = q.where(A.person_type == person_type)
        if department_id:
            q = q.where(
                (
                    (A.person_type == "student")
                    & A.person_id.in_(
                        select(StudentProgramEnrollment.student_id).where(
                            StudentProgramEnrollment.department_id == department_id
                        )
                    )
                )
                | (
                    (A.person_type == "staff")
                    & A.person_id.in_(select(Staff.id).where(Staff.department_id == department_id))
                )
            )
        return await self.outs(list((await self.db.execute(q.order_by(A.created_at.desc()).limit(2000))).scalars()))

    async def get(self, allocation_id: uuid.UUID, *, for_update: bool = False) -> TransportAllocation:
        q = select(TransportAllocation).where(
            TransportAllocation.id == allocation_id,
            TransportAllocation.institution_id == self.inst,
            allocation_predicate(self.principal),
        )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Allocation not found")
        return row

    # ---- allocate --------------------------------------------------------------------------------------------------------
    async def _person(self, person_type: str, person_id: uuid.UUID) -> Student | Staff:
        if person_type == "staff":
            if not await self.feature("transport.staff"):
                raise APIError(
                    403, ErrorCode.FEATURE_DISABLED, "Staff transport is disabled", {"feature": "transport.staff"}
                )
            row: Any = (
                await self.db.execute(select(Staff).where(Staff.id == person_id, Staff.institution_id == self.inst))
            ).scalar_one_or_none()
        else:
            row = (
                await self.db.execute(
                    select(Student).where(
                        Student.id == person_id, Student.institution_id == self.inst, Student.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, f"{person_type.title()} not found")
        return row  # type: ignore[no-any-return]

    async def _route_stop(self, route_id: uuid.UUID, stop_id: uuid.UUID) -> tuple[TransportRoute, TransportStop]:
        r = await self.route(route_id, for_update=True, any_scope=True)
        if not r.is_active:
            raise rule("The route is inactive", "ROUTE_INACTIVE")
        s = (
            await self.db.execute(
                select(TransportStop).where(TransportStop.id == stop_id, TransportStop.route_id == r.id)
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(422, ErrorCode.VALIDATION, "The stop is not on this route")
        return r, s

    async def _capacity(self, r: TransportRoute, *, exclude: uuid.UUID | None = None) -> str | None:
        cap = None
        if r.vehicle_id:
            cap = (
                await self.db.execute(select(Vehicle.capacity).where(Vehicle.id == r.vehicle_id))
            ).scalar_one_or_none()
        if cap is None:
            return None
        q = (
            select(func.count())
            .select_from(TransportAllocation)
            .where(TransportAllocation.route_id == r.id, TransportAllocation.status.in_(LIVE_ALLOCATION))
        )
        if exclude:
            q = q.where(TransportAllocation.id != exclude)
        used = (await self.db.execute(q)).scalar_one()
        if used < cap:
            return None
        hard = await self.setting("transport", "capacity_hard_limit")
        if hard is None or bool(hard):
            raise rule("The route is full", "CAPACITY_FULL", capacity=cap, used=used)
        return "CAPACITY_EXCEEDED"

    async def _live_for(self, person_type: str, person_id: uuid.UUID) -> TransportAllocation | None:
        return (
            (
                await self.db.execute(
                    select(TransportAllocation).where(
                        TransportAllocation.institution_id == self.inst,
                        TransportAllocation.person_type == person_type,
                        TransportAllocation.person_id == person_id,
                        TransportAllocation.status.in_(PENDING_OR_LIVE),
                    )
                )
            )
            .scalars()
            .first()
        )

    async def _year(self, year_id: uuid.UUID | None) -> AcademicYear:
        if year_id:
            y = (await self.db.execute(select(AcademicYear).where(AcademicYear.id == year_id))).scalar_one_or_none()
            if y is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Academic year not found")
            return y
        return await self.academic_year()

    async def _bill(self, a: TransportAllocation, person: Any, amount: int, label: str) -> None:
        if a.person_type != "student" or amount <= 0 or not await self.feature("transport.fees"):
            return
        enrol = await self.current_enrolment(person.id)
        if enrol is None:
            return
        inv = await self.invoice(enrol.id, a.id, amount, label)
        if a.fee_invoice_id is None:
            a.fee_invoice_id = inv

    async def allocate(self, body: AllocationCreate, *, status: str = "active") -> AllocationResponse:
        if status == "active":
            self.require("manage")
        person = await self._person(body.person_type, body.person_id)
        if await self._live_for(body.person_type, body.person_id):
            raise rule("The person already has a transport allocation", "ALREADY_ALLOCATED")
        r, s = await self._route_stop(body.route_id, body.stop_id)
        warning = await self._capacity(r) if status == "active" else None
        year = await self._year(body.academic_year_id)
        a = TransportAllocation(
            institution_id=self.inst,
            person_type=body.person_type,
            person_id=body.person_id,
            route_id=r.id,
            stop_id=s.id,
            academic_year_id=year.id,
            from_on=body.from_on or await self.today(),
            to_on=body.to_on or year.end_date,
            status=status,
        )
        self.db.add(a)
        await self.db.flush()
        if status == "active":
            await self._activated(a, person, r, s, payroll=body.payroll_deduction)
        await self._audit("create", "transport_allocation", a.id, None, snap(a, KEYS))
        out = (await self.outs([a]))[0]
        out.warning = warning
        return out

    async def _activated(
        self, a: TransportAllocation, person: Any, r: TransportRoute, s: TransportStop, *, payroll: bool = False
    ) -> None:
        fee = self.fee_of(r, s)
        await self._bill(a, person, fee, f"Transport fee — {r.code} / {s.name}")
        if a.person_type == "staff" and payroll and fee > 0:
            await self._emit(
                "payroll.deduction_requested",
                {
                    "staff_id": str(a.person_id),
                    "source_type": "transport_allocation",
                    "source_id": str(a.id),
                    "amount_paise": fee,
                    "months": 10,
                    "label": f"Transport {r.code}",
                },
                "transport_allocation",
                a.id,
            )
        users = list((await self.person_users(a.person_type, [a.person_id])).values())
        await self._notify(
            "transport.allocated",
            users,
            {"route": f"{r.code} {r.name}", "stop": s.name, "fee": f"{fee / 100:.2f}"},
            guardians=a.person_type == "student",
        )
        await self._emit(
            "transport.allocated",
            {
                "allocation_id": str(a.id),
                "person_type": a.person_type,
                "person_id": str(a.person_id),
                "route_id": str(r.id),
            },
            "transport_allocation",
            a.id,
        )

    async def bulk(self, body: AllocationBulk) -> AllocationBulkReport:
        self.require("manage")
        rep = AllocationBulkReport()
        for pid in dict.fromkeys(body.person_ids):
            try:
                async with self.db.begin_nested():
                    await self.allocate(
                        AllocationCreate(
                            person_type=body.person_type,
                            person_id=pid,
                            route_id=body.route_id,
                            stop_id=body.stop_id,
                            academic_year_id=body.academic_year_id,
                        )
                    )
                rep.allocated += 1
            except APIError as exc:
                rep.failed.append(
                    {"person_id": str(pid), "code": (exc.details or {}).get("code") or exc.code, "message": exc.message}
                )
        return rep

    async def change(self, allocation_id: uuid.UUID, body: AllocationChange) -> AllocationResponse:
        self.require("manage")
        old = await self.get(allocation_id, for_update=True)
        if old.status not in LIVE_ALLOCATION:
            raise rule("Only a live allocation can be changed", "NOT_LIVE")
        r, s = await self._route_stop(body.new_route_id, body.new_stop_id)
        warning = await self._capacity(r, exclude=old.id) if r.id != old.route_id else None
        old_r = await self.route(old.route_id, any_scope=True)
        old_s = (
            await self.db.execute(select(TransportStop).where(TransportStop.id == old.stop_id))
        ).scalar_one_or_none()
        before = snap(old, KEYS)
        old.status, old.to_on = "closed", body.effective_on - timedelta(days=1)
        new = TransportAllocation(
            institution_id=self.inst,
            person_type=old.person_type,
            person_id=old.person_id,
            route_id=r.id,
            stop_id=s.id,
            academic_year_id=old.academic_year_id,
            from_on=body.effective_on,
            to_on=before["to_on"] and date.fromisoformat(before["to_on"]),
            status="active",
        )
        self.db.add(new)
        await self.db.flush()
        diff = self.fee_of(r, s) - self.fee_of(old_r, old_s)
        prorata = await self.setting("transport", "prorata_change")
        if diff > 0 and (prorata is None or bool(prorata)):
            year = await self._year(old.academic_year_id)
            span = max((year.end_date - year.start_date).days, 1)
            left = max((year.end_date - body.effective_on).days, 0)
            amount = int(diff * left / span)
            person = await self._person(old.person_type, old.person_id)
            if amount > 0 and old.person_type == "student" and await self.feature("transport.fees"):
                enrol = await self.current_enrolment(person.id)
                if enrol:
                    new.fee_invoice_id = await self.invoice(
                        enrol.id, new.id, amount, f"Transport change — {r.code} / {s.name} (pro-rata)"
                    )
        if new.fee_invoice_id is None:
            new.fee_invoice_id = old.fee_invoice_id
        await self._audit("change", "transport_allocation", old.id, before, snap(new, KEYS))
        await self._emit(
            "transport.changed",
            {
                "from_allocation_id": str(old.id),
                "allocation_id": str(new.id),
                "route_id": str(r.id),
                "effective_on": body.effective_on.isoformat(),
            },
            "transport_allocation",
            new.id,
        )
        out = (await self.outs([new]))[0]
        out.warning = warning
        return out

    async def set_status(self, allocation_id: uuid.UUID, status: str, reason: str | None = None) -> AllocationResponse:
        self.require("manage")
        a = await self.get(allocation_id, for_update=True)
        return await self._set(a, status, reason)

    async def _set(self, a: TransportAllocation, status: str, reason: str | None = None) -> AllocationResponse:
        if a.status == "closed":
            raise rule("The allocation is closed", "CLOSED")
        before = snap(a, KEYS)
        a.status = status
        if status == "closed" and (a.to_on is None or a.to_on > await self.today()):
            a.to_on = await self.today()
        await self.db.flush()
        await self._audit(status, "transport_allocation", a.id, before, snap(a, KEYS) | {"reason": reason})
        evt = {"suspended": "transport.suspended", "closed": "transport.closed", "active": "transport.reactivated"}.get(
            status
        )
        if evt:
            await self._emit(evt, {"allocation_id": str(a.id), "reason": reason}, "transport_allocation", a.id)
        if status == "suspended":
            users = list((await self.person_users(a.person_type, [a.person_id])).values())
            await self._notify("transport.suspended", users, {"reason": reason or "fee unpaid"}, guardians=True)
        return (await self.outs([a]))[0]

    # ---- self service ---------------------------------------------------------------------------------------------------
    async def _me(self) -> tuple[str, uuid.UUID]:
        st = await self.my_student()
        if st is not None:
            return "student", st.id
        sf = await self.my_staff()
        if sf is not None:
            return "staff", sf.id
        raise APIError(404, ErrorCode.NOT_FOUND, "No student or staff record for this user")

    async def me(self) -> MyTransportResponse:
        from app.services.transport.route_service import RouteService

        kind, pid = await self._me()
        a = (
            (
                await self.db.execute(
                    select(TransportAllocation)
                    .where(
                        TransportAllocation.institution_id == self.inst,
                        TransportAllocation.person_type == kind,
                        TransportAllocation.person_id == pid,
                        TransportAllocation.status.in_(LIVE_ALLOCATION),
                    )
                    .order_by(TransportAllocation.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        if a is None:
            return MyTransportResponse()
        return await self.passenger_view(a, RouteService)

    async def passenger_view(self, a: TransportAllocation, route_service: Any) -> MyTransportResponse:
        rs = route_service(self.db, None, self.request, self.inst)
        route = (await rs.outs([await rs.route(a.route_id, any_scope=True)]))[0]
        stop = next((s for s in route.stops if s.id == a.stop_id), None)
        today = await self.today()
        trips = (
            (
                await self.db.execute(
                    select(TransportTrip)
                    .where(TransportTrip.route_id == a.route_id, TransportTrip.trip_date == today)
                    .order_by(TransportTrip.direction.desc())
                )
            )
            .scalars()
            .all()
        )
        route.capacity_used = 0  # passengers do not see the fill
        return MyTransportResponse(
            allocation=(await self.outs([a]))[0],
            route=route,
            stop=stop,
            pickup_time=stop.pickup_time if stop else None,
            drop_time=stop.drop_time if stop else None,
            vehicle=route.vehicle_registration,
            driver_name=route.driver_name,
            live_available=any(t.status == "in_progress" for t in trips) and await self.feature("transport.gps_live"),
            today_trips=[
                TripBrief(id=t.id, direction=t.direction, status=t.status, started_at=t.started_at, ended_at=t.ended_at)
                for t in trips
            ],
        )

    async def wards(self) -> list[MyTransportResponse]:
        from app.services.transport.route_service import RouteService

        if self.actor_id is None:
            return []
        ward_ids = list(await self.guardians.ward_ids(self.actor_id))
        rows = (
            (
                await self.db.execute(
                    select(TransportAllocation).where(
                        TransportAllocation.institution_id == self.inst,
                        TransportAllocation.person_type == "student",
                        TransportAllocation.person_id.in_(ward_ids or [uuid.uuid4()]),
                        TransportAllocation.status.in_(LIVE_ALLOCATION),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [await self.passenger_view(a, RouteService) for a in rows]

    async def request_allocation(self, body: TransportRequestCreate) -> AllocationResponse:
        enabled = await self.setting("transport", "self_service_requests")
        if enabled is not None and not bool(enabled):
            raise rule("Self-service transport requests are closed", "REQUESTS_CLOSED", 403)
        kind, pid = await self._me()
        live = await self._live_for(kind, pid)
        if live is not None and live.status == "pending":
            raise rule("You already have a pending request", "REQUEST_PENDING")
        if live is not None:
            # a change request: kept as a pending row next to the live allocation
            r, s = await self._route_stop(body.route_id, body.stop_id)
            a = TransportAllocation(
                institution_id=self.inst,
                person_type=kind,
                person_id=pid,
                route_id=r.id,
                stop_id=s.id,
                academic_year_id=live.academic_year_id,
                status="pending",
            )
            self.db.add(a)
            await self.db.flush()
            await self._audit("request_change", "transport_allocation", a.id, None, snap(a, KEYS))
            return (await self.outs([a]))[0]
        return await self.allocate(
            AllocationCreate(person_type=kind, person_id=pid, route_id=body.route_id, stop_id=body.stop_id),  # type: ignore[arg-type]
            status="pending",
        )

    async def my_requests(self) -> list[AllocationResponse]:
        kind, pid = await self._me()
        rows = (
            (
                await self.db.execute(
                    select(TransportAllocation)
                    .where(
                        TransportAllocation.person_type == kind,
                        TransportAllocation.person_id == pid,
                        TransportAllocation.status.in_(("pending", "rejected", "active", "closed")),
                    )
                    .order_by(TransportAllocation.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows))

    async def requests(self, status: str | None = "pending") -> list[AllocationResponse]:
        self.require("manage")
        return await self.list_allocations(status=status or "pending")

    async def decide(self, allocation_id: uuid.UUID, body: TransportRequestDecision) -> AllocationResponse:
        self.require("manage")
        a = await self.get(allocation_id, for_update=True)
        if a.status != "pending":
            raise rule("The request is already decided", "ALREADY_DECIDED")
        users = list((await self.person_users(a.person_type, [a.person_id])).values())
        if body.decision == "reject":
            a.status = "rejected"
            await self._audit("reject", "transport_allocation", a.id, None, {"remarks": body.remarks})
            await self._notify(
                "transport.request_decided", users, {"decision": "rejected", "remarks": body.remarks or ""}
            )
            return (await self.outs([a]))[0]
        live = (
            (
                await self.db.execute(
                    select(TransportAllocation).where(
                        TransportAllocation.person_type == a.person_type,
                        TransportAllocation.person_id == a.person_id,
                        TransportAllocation.status.in_(LIVE_ALLOCATION),
                        TransportAllocation.id != a.id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if live is not None:  # change request → close the live row, the request becomes the allocation
            a.status = "rejected"
            out = await self.change(
                live.id,
                AllocationChange(new_route_id=a.route_id, new_stop_id=a.stop_id, effective_on=await self.today()),
            )  # type: ignore[arg-type]
            await self._notify(
                "transport.request_decided", users, {"decision": "approved", "remarks": body.remarks or ""}
            )
            return out
        r, s = await self._route_stop(a.route_id, a.stop_id)  # type: ignore[arg-type]
        warning = await self._capacity(r, exclude=a.id)
        year = await self._year(a.academic_year_id)
        a.status, a.from_on, a.to_on = "active", await self.today(), year.end_date
        await self.db.flush()
        await self._activated(a, await self._person(a.person_type, a.person_id), r, s)
        await self._audit("approve", "transport_allocation", a.id, None, snap(a, KEYS))
        await self._notify("transport.request_decided", users, {"decision": "approved", "remarks": body.remarks or ""})
        out = (await self.outs([a]))[0]
        out.warning = warning
        return out

    # ---- jobs / Beat / consumers ------------------------------------------------------------------------------------------------
    async def fee_suspension(self) -> int:
        today = await self.today()
        grace = int(await self.setting("transport", "fee_grace_days") or 15)
        rows = (
            (
                await self.db.execute(
                    select(TransportAllocation)
                    .join(FeeInvoice, FeeInvoice.id == TransportAllocation.fee_invoice_id)
                    .where(
                        TransportAllocation.institution_id == self.inst,
                        TransportAllocation.status == "active",
                        FeeInvoice.balance_paise > 0,
                        FeeInvoice.status.notin_(("paid", "cancelled", "waived")),
                        FeeInvoice.due_date < today - timedelta(days=grace),
                    )
                )
            )
            .scalars()
            .all()
        )
        for a in rows:
            await self._set(a, "suspended", "fee unpaid")
        return len(rows)

    async def payment_received(self, invoice_id: uuid.UUID) -> int:
        inv = (await self.db.execute(select(FeeInvoice).where(FeeInvoice.id == invoice_id))).scalar_one_or_none()
        if inv is None or inv.balance_paise > 0:
            return 0
        rows = (
            (
                await self.db.execute(
                    select(TransportAllocation).where(
                        TransportAllocation.fee_invoice_id == invoice_id, TransportAllocation.status == "suspended"
                    )
                )
            )
            .scalars()
            .all()
        )
        for a in rows:
            await self._set(a, "active", "fee paid")
        return len(rows)

    async def year_end_close(self) -> dict[str, int]:
        today = await self.today()
        rows = (
            (
                await self.db.execute(
                    select(TransportAllocation).where(
                        TransportAllocation.institution_id == self.inst,
                        TransportAllocation.status.in_(PENDING_OR_LIVE),
                        TransportAllocation.to_on < today,
                    )
                )
            )
            .scalars()
            .all()
        )
        summary = {"closed": 0, "students": 0, "staff": 0, "pending_rejected": 0}
        for a in rows:
            if a.status == "pending":
                a.status = "rejected"
                summary["pending_rejected"] += 1
                continue
            a.status = "closed"
            summary["closed"] += 1
            summary["students" if a.person_type == "student" else "staff"] += 1
            await self._emit(
                "transport.closed", {"allocation_id": str(a.id), "reason": "year_end"}, "transport_allocation", a.id
            )
        await self._audit("year_end_close", "transport_allocation", None, None, summary)
        return summary
