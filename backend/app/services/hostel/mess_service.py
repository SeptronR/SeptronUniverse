"""Mess — Prompts/20 §20.6 ``mess_service`` (features ``hostel.mess`` / ``hostel.mess_billing``).

* plans per hostel (or shared) with diet and a weekly ``menu``; one active subscription per enrolment — a change closes
  the current one at month end and opens the new plan from the 1st; prepaid billing (``hostel.mess_billing_mode``)
  invoices the month on subscription (``source_type='mess_subscription'``, head MESS);
* attendance per meal by mess-card QR (``ms.<subscription>.<hmac>``), RFID push or manual; duplicates are ignored
  (``UNIQUE``);
* rebates: requests of at least ``hostel.rebate_min_consecutive_days`` days (422 ``REBATE_TOO_SHORT``), optionally tied
  to an approved hostel leave (``hostel.rebate_requires_leave``); requests / decisions are audit rows (``mess_rebate``,
  no table in the DDL); approval writes ``mess_attendance(status='rebate')`` for every meal of the days;
* monthly bill run: ``days_billed = days of the month in the subscription − rebate days − mess-closed holidays``;
  ``amount = monthly_fee × days_billed / days_in_month`` → ``mess_bills`` + postpaid invoice.
"""

import calendar
import hashlib
import hmac
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.models.fees import FeeInvoice
from app.models.hostel import HostelAllocation, HostelLeave, MessAttendance, MessBill, MessPlan, MessSubscription
from app.models.platform import AuditLog, Holiday
from app.schemas.hostel import (
    BillRunSummary,
    MessAttendanceMark,
    MessAttendanceResult,
    MessAttendanceRow,
    MessBillResponse,
    MessPlanIn,
    MessPlanOut,
    MessSubscribe,
    MessSubscriptionOut,
    RebateDecision,
    RebateOut,
    RebateRequest,
)
from app.services.hostel.common import HostelBase, now_utc, resident_predicate, rule, visible_hostel_ids

MEALS = ("breakfast", "lunch", "snacks", "dinner")


def mess_token(sub_id: uuid.UUID) -> str:
    sig = hmac.new(settings.SECRET_KEY.encode(), f"ms:{sub_id}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"ms.{sub_id.hex}.{sig}"


def parse_mess_token(token: str) -> uuid.UUID | None:
    try:
        prefix, sid, _sig = token.strip().split(".")
        sub_id = uuid.UUID(sid)
    except ValueError:
        return None
    return sub_id if prefix == "ms" and hmac.compare_digest(mess_token(sub_id), token.strip()) else None


class MessService(HostelBase):
    def manager(self) -> bool:
        return self.can("hostel", "mess_manage") or self.can("hostel", "warden") or self.can("hostel", "manage")

    # ---- plans ------------------------------------------------------------------------------------------------------
    async def plans(self, hostel_id: uuid.UUID | None = None) -> list[MessPlanOut]:
        q = select(MessPlan).where(MessPlan.institution_id == self.inst)
        if hostel_id:
            q = q.where((MessPlan.hostel_id == hostel_id) | MessPlan.hostel_id.is_(None))
        rows = (await self.db.execute(q.order_by(MessPlan.name))).scalars().all()
        counts: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(MessSubscription.mess_plan_id, func.count())
                    .where(MessSubscription.status == "active")
                    .group_by(MessSubscription.mess_plan_id)
                )
            ).all()
        )  # type: ignore[arg-type]
        return [
            MessPlanOut(
                id=p.id,
                hostel_id=p.hostel_id,
                name=p.name,
                diet=p.diet,
                monthly_fee_paise=p.monthly_fee_paise,
                menu=p.menu,
                is_active=p.is_active,
                subscribers=int(counts.get(p.id, 0)),
            )
            for p in rows
        ]

    async def save_plan(self, body: MessPlanIn, plan_id: uuid.UUID | None = None) -> MessPlanOut:
        self.require("mess_manage", "warden")
        if body.hostel_id and not await self.owns_hostel(body.hostel_id):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "This hostel is not yours")
        p: MessPlan | None
        if plan_id is None:
            p = MessPlan(institution_id=self.inst, **body.model_dump())
            self.db.add(p)
        else:
            p = (
                await self.db.execute(
                    select(MessPlan).where(MessPlan.id == plan_id, MessPlan.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if p is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Mess plan not found")
            for k, v in body.model_dump().items():
                setattr(p, k, v)
        await self.db.flush()
        await self._audit("mess_plan_save", "mess_plan", p.id, None, body.model_dump(mode="json"))
        return next(x for x in await self.plans() if x.id == p.id)

    # ---- subscriptions --------------------------------------------------------------------------------------------------
    async def sub_outs(self, rows: list[MessSubscription], *, with_qr: bool = False) -> list[MessSubscriptionOut]:
        refs = await self.refs([r.student_program_enrollment_id for r in rows])
        names: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(MessPlan.id, MessPlan.name).where(
                        MessPlan.id.in_({r.mess_plan_id for r in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )  # type: ignore[arg-type]
        return [
            MessSubscriptionOut(
                id=r.id,
                student=refs.get(r.student_program_enrollment_id) or {"enrollment_id": r.student_program_enrollment_id},  # type: ignore[arg-type]
                mess_plan_id=r.mess_plan_id,
                plan=names.get(r.mess_plan_id),
                from_on=r.from_on,
                to_on=r.to_on,
                status=r.status,
                fee_invoice_id=r.fee_invoice_id,
                qr_token=mess_token(r.id) if with_qr and r.status == "active" else None,
            )
            for r in rows
        ]

    async def subscribe(self, body: MessSubscribe) -> MessSubscriptionOut:
        e = await self.my_enrolment(body.enrollment_id)
        plan = (
            await self.db.execute(
                select(MessPlan).where(
                    MessPlan.id == body.mess_plan_id, MessPlan.institution_id == self.inst, MessPlan.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        if plan is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Mess plan not found")
        current = (
            await self.db.execute(
                select(MessSubscription)
                .where(MessSubscription.student_program_enrollment_id == e.id, MessSubscription.status == "active")
                .with_for_update()
            )
        ).scalar_one_or_none()
        today = await self.today()
        start = body.from_on or today
        if current is not None:
            if current.mess_plan_id == plan.id:
                raise rule("Already subscribed to this plan", "ALREADY_SUBSCRIBED")
            # change effective next month
            month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
            current.to_on, current.status = month_end, "closed"
            start = month_end + timedelta(days=1)
        sub = MessSubscription(
            institution_id=self.inst,
            student_program_enrollment_id=e.id,
            mess_plan_id=plan.id,
            from_on=start,
            status="active",
        )
        self.db.add(sub)
        await self.db.flush()
        if await self.setting("hostel", "mess_billing_mode") == "prepaid" and plan.monthly_fee_paise:
            sub.fee_invoice_id = await self.invoice(
                e.id,
                "mess_subscription",
                sub.id,
                [(f"Mess — {plan.name} ({start:%b %Y})", plan.monthly_fee_paise, "MESS")],
                "Mess fee",
            )
        await self.db.flush()
        await self.db.refresh(sub)
        await self._emit(
            "mess.subscribed", {"subscription_id": str(sub.id), "plan_id": str(plan.id)}, "mess_subscription", sub.id
        )
        return (await self.sub_outs([sub], with_qr=True))[0]

    async def close(self, sub_id: uuid.UUID) -> MessSubscriptionOut:
        sub = await self._sub(sub_id, for_update=True)
        if sub.student_program_enrollment_id not in await self.mine() and not self.manager():
            raise APIError(404, ErrorCode.NOT_FOUND, "Subscription not found")
        sub.status, sub.to_on = "closed", await self.today()
        await self.db.flush()
        await self.db.refresh(sub)
        return (await self.sub_outs([sub]))[0]

    async def change(self, sub_id: uuid.UUID, plan_id: uuid.UUID) -> MessSubscriptionOut:
        sub = await self._sub(sub_id)
        return await self.subscribe(
            MessSubscribe(
                mess_plan_id=plan_id, enrollment_id=sub.student_program_enrollment_id if self.manager() else None
            )
        )

    async def _sub(self, sub_id: uuid.UUID, *, for_update: bool = False) -> MessSubscription:
        q = select(MessSubscription).where(MessSubscription.id == sub_id, MessSubscription.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        sub = (await self.db.execute(q)).scalar_one_or_none()
        if sub is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Subscription not found")
        return sub

    async def subscriptions(self, hostel_id: uuid.UUID | None, *, mine: bool = False) -> list[MessSubscriptionOut]:
        q = select(MessSubscription).where(MessSubscription.institution_id == self.inst)
        if mine or not self.manager():
            q = q.where(
                MessSubscription.student_program_enrollment_id.in_(await self.mine(wards=not mine) or [uuid.uuid4()])
            )
        else:
            q = q.where(
                MessSubscription.student_program_enrollment_id.in_(
                    select(HostelAllocation.student_program_enrollment_id).where(
                        HostelAllocation.hostel_id.in_(visible_hostel_ids(self.principal)),
                        HostelAllocation.status.in_(("allotted", "checked_in")),
                    )
                )
                | MessSubscription.mess_plan_id.in_(select(MessPlan.id).where(MessPlan.hostel_id.is_(None)))
            )
        if hostel_id:
            q = q.where(
                MessSubscription.mess_plan_id.in_(
                    select(MessPlan.id).where((MessPlan.hostel_id == hostel_id) | MessPlan.hostel_id.is_(None))
                )
            )
        rows = list((await self.db.execute(q.order_by(MessSubscription.created_at.desc()).limit(5000))).scalars().all())
        return await self.sub_outs(rows, with_qr=mine)

    # ---- attendance --------------------------------------------------------------------------------------------------
    async def mark(self, items: list[MessAttendanceMark]) -> MessAttendanceResult:
        if not self.manager():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "hostel:mess_manage required")
        from sqlalchemy.dialects.postgresql import insert

        out = MessAttendanceResult(recorded=0, duplicates=0)
        today = await self.today()
        for i, m in enumerate(items):
            sid = m.subscription_id or (parse_mess_token(m.qr) if m.qr else None)
            if sid is None:
                out.errors.append({"index": i, "error": "unknown card"})
                continue
            sub = (
                await self.db.execute(
                    select(MessSubscription).where(
                        MessSubscription.id == sid, MessSubscription.institution_id == self.inst
                    )
                )
            ).scalar_one_or_none()
            if sub is None or sub.status != "active":
                out.errors.append({"index": i, "error": "no active subscription"})
                continue
            stmt = (
                insert(MessAttendance)
                .values(
                    id=uuid.uuid4(),
                    institution_id=self.inst,
                    mess_subscription_id=sid,
                    on_date=m.on_date or today,
                    meal=m.meal,
                    status="taken",
                    source=m.source if not m.qr else "qr",
                )
                .on_conflict_do_nothing(index_elements=["mess_subscription_id", "on_date", "meal"])
            )
            res = await self.db.execute(stmt)
            if getattr(res, "rowcount", 0):
                out.recorded += 1
            else:
                out.duplicates += 1
        await self.db.flush()
        return out

    async def attendance(self, sub_id: uuid.UUID | None, on: date | None) -> list[MessAttendanceRow]:
        q = (
            select(MessAttendance)
            .join(MessSubscription, MessSubscription.id == MessAttendance.mess_subscription_id)
            .where(MessAttendance.institution_id == self.inst)
        )
        if not self.manager():
            q = q.where(
                MessSubscription.student_program_enrollment_id.in_(await self.mine(wards=True) or [uuid.uuid4()])
            )
        if sub_id:
            q = q.where(MessAttendance.mess_subscription_id == sub_id)
        if on:
            q = q.where(MessAttendance.on_date == on)
        rows = (await self.db.execute(q.order_by(MessAttendance.on_date.desc()).limit(3000))).scalars().all()
        return [MessAttendanceRow(on_date=r.on_date, meal=r.meal, status=r.status, source=r.source) for r in rows]

    # ---- rebates (audit-backed) ------------------------------------------------------------------------------------------
    async def _rebate_rows(self) -> list[tuple[uuid.UUID, dict[str, Any], dict[str, Any] | None]]:
        reqs = (
            await self.db.execute(
                select(AuditLog.record_id, AuditLog.new_values)
                .where(
                    AuditLog.institution_id == self.inst,
                    AuditLog.record_type == "mess_rebate",
                    AuditLog.action == "rebate_request",
                )
                .order_by(AuditLog.occurred_at.desc())
                .limit(3000)
            )
        ).all()
        decisions = {
            r[0]: r[1]
            for r in (
                await self.db.execute(
                    select(AuditLog.record_id, AuditLog.new_values).where(
                        AuditLog.institution_id == self.inst,
                        AuditLog.record_type == "mess_rebate",
                        AuditLog.action == "rebate_decide",
                    )
                )
            ).all()
        }
        return [(rid, nv or {}, decisions.get(rid)) for rid, nv in reqs if rid]

    async def _rebate_out(self, rid: uuid.UUID, req: dict[str, Any], dec: dict[str, Any] | None) -> RebateOut:
        sub_id = uuid.UUID(req["subscription_id"])
        enrol = (
            await self.db.execute(
                select(MessSubscription.student_program_enrollment_id).where(MessSubscription.id == sub_id)
            )
        ).scalar_one_or_none()
        f, t = date.fromisoformat(req["from_on"]), date.fromisoformat(req["to_on"])
        return RebateOut(
            id=rid,
            subscription_id=sub_id,
            student=await self.ref(enrol) if enrol else None,
            from_on=f,
            to_on=t,
            days=(t - f).days + 1,
            reason=req.get("reason"),
            status=(dec or {}).get("status", "requested"),
            leave_id=uuid.UUID(req["leave_id"]) if req.get("leave_id") else None,
        )

    async def request_rebate(self, body: RebateRequest) -> RebateOut:
        e = await self.my_enrolment()
        sub = (
            await self.db.execute(
                select(MessSubscription).where(
                    MessSubscription.student_program_enrollment_id == e.id, MessSubscription.status == "active"
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            raise rule("No active mess subscription", "NO_SUBSCRIPTION")
        days = (body.to_on - body.from_on).days + 1
        minimum = int(await self.setting("hostel", "rebate_min_consecutive_days") or 5)
        if days < minimum:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"A rebate needs at least {minimum} consecutive days",
                {"code": "REBATE_TOO_SHORT", "min_days": minimum},
            )
        leave = (
            await self.db.execute(
                select(HostelLeave.id).where(
                    HostelLeave.student_program_enrollment_id == e.id,
                    HostelLeave.status.in_(("approved", "out", "returned", "late_return")),
                    func.date(HostelLeave.from_at) <= body.from_on,
                    func.date(HostelLeave.to_at) >= body.to_on,
                )
            )
        ).scalar_one_or_none()
        if await self.setting("hostel", "rebate_requires_leave") and leave is None:
            raise rule("A rebate needs an approved hostel leave covering the days", "LEAVE_REQUIRED")
        rid = uuid.uuid4()
        req = {
            "subscription_id": str(sub.id),
            "from_on": body.from_on.isoformat(),
            "to_on": body.to_on.isoformat(),
            "reason": body.reason,
            "leave_id": str(leave) if leave else None,
        }
        await self._audit("rebate_request", "mess_rebate", rid, None, req)
        await self._emit("mess.rebate_requested", {"rebate_id": str(rid)}, "mess_rebate", rid)
        return await self._rebate_out(rid, req, None)

    async def rebates(self, status: str | None, *, mine: bool = False) -> list[RebateOut]:
        own = set(await self.mine(wards=True))
        out = []
        for rid, req, dec in await self._rebate_rows():
            r = await self._rebate_out(rid, req, dec)
            if (mine or not self.manager()) and (r.student is None or r.student.enrollment_id not in own):
                continue
            if status and r.status != status:
                continue
            out.append(r)
        return out

    async def decide_rebate(self, rid: uuid.UUID, body: RebateDecision) -> RebateOut:
        if not self.manager():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "hostel:mess_manage required")
        found = next(((r, req, dec) for r, req, dec in await self._rebate_rows() if r == rid), None)
        if found is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Rebate request not found")
        _r, req, dec = found
        if dec is not None:
            raise rule("The rebate is already decided", "ALREADY_DECIDED")
        status = "approved" if body.approve else "rejected"
        if body.approve:
            from sqlalchemy.dialects.postgresql import insert

            sub_id = uuid.UUID(req["subscription_id"])
            d = date.fromisoformat(req["from_on"])
            end = date.fromisoformat(req["to_on"])
            while d <= end:
                for meal in MEALS:
                    stmt = insert(MessAttendance).values(
                        id=uuid.uuid4(),
                        institution_id=self.inst,
                        mess_subscription_id=sub_id,
                        on_date=d,
                        meal=meal,
                        status="rebate",
                        source="manual",
                    )
                    await self.db.execute(
                        stmt.on_conflict_do_update(
                            index_elements=["mess_subscription_id", "on_date", "meal"], set_={"status": "rebate"}
                        )
                    )
                d += timedelta(days=1)
        await self._audit("rebate_decide", "mess_rebate", rid, None, {"status": status, "remarks": body.remarks})
        await self._emit("mess.rebate_decided", {"rebate_id": str(rid), "status": status}, "mess_rebate", rid)
        return await self._rebate_out(rid, req, {"status": status})

    # ---- bills --------------------------------------------------------------------------------------------------------------
    async def bill_run(self, month: date, hostel_id: uuid.UUID | None = None) -> BillRunSummary:
        if not self.manager():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "hostel:mess_manage required")
        start = month.replace(day=1)
        days_in = calendar.monthrange(start.year, start.month)[1]
        end = start.replace(day=days_in)
        q = (
            select(MessSubscription, MessPlan)
            .join(MessPlan, MessPlan.id == MessSubscription.mess_plan_id)
            .where(
                MessSubscription.institution_id == self.inst,
                MessSubscription.from_on <= end,
                (MessSubscription.to_on.is_(None)) | (MessSubscription.to_on >= start),
            )
        )
        if hostel_id:
            q = q.where((MessPlan.hostel_id == hostel_id) | MessPlan.hostel_id.is_(None))
        closures = 0
        for a, b in (
            await self.db.execute(
                select(Holiday.holiday_date, Holiday.end_date).where(
                    Holiday.institution_id == self.inst,
                    Holiday.deleted_at.is_(None),
                    Holiday.holiday_type == "mess_closed",
                    Holiday.holiday_date <= end,
                )
            )
        ).all():
            d = max(a, start)
            while d <= min(b or a, end):
                closures += 1
                d += timedelta(days=1)
        summary = BillRunSummary(month=start)
        for sub, plan in (await self.db.execute(q)).all():
            if (
                await self.db.execute(
                    select(MessBill.id).where(MessBill.mess_subscription_id == sub.id, MessBill.month == start)
                )
            ).first():
                summary.skipped += 1
                continue
            s = max(sub.from_on, start)
            e = min(sub.to_on or end, end)
            span = (e - s).days + 1
            rebate_days = (
                await self.db.execute(
                    select(func.count(func.distinct(MessAttendance.on_date))).where(
                        MessAttendance.mess_subscription_id == sub.id,
                        MessAttendance.status == "rebate",
                        MessAttendance.on_date.between(s, e),
                    )
                )
            ).scalar_one()
            billed = max(span - int(rebate_days) - closures, 0)
            amount = round(plan.monthly_fee_paise * billed / days_in)
            bill = MessBill(
                institution_id=self.inst,
                mess_subscription_id=sub.id,
                month=start,
                days_billed=billed,
                rebate_days=int(rebate_days),
                amount_paise=amount,
            )
            self.db.add(bill)
            await self.db.flush()
            if amount > 0 and await self.setting("hostel", "mess_billing_mode") != "prepaid":
                bill.fee_invoice_id = await self.invoice(
                    sub.student_program_enrollment_id,
                    "mess_subscription",
                    bill.id,
                    [(f"Mess {plan.name} {start:%b %Y} ({billed} days)", amount, "MESS")],
                    f"Mess bill {start:%b %Y}",
                )
            summary.bills += 1
            summary.amount_paise += amount
            await self._notify(
                "mess.bill_generated",
                [await self.student_user(sub.student_program_enrollment_id)],
                {"month": f"{start:%b %Y}", "amount": f"₹{amount / 100:,.2f}"},
                guardians=True,
            )
        await self.db.flush()
        await self._emit(
            "mess.bill_generated", {"month": start.isoformat(), "bills": summary.bills}, "mess_bill_run", None
        )
        return summary

    async def bill_outs(self, rows: list[MessBill]) -> list[MessBillResponse]:
        subs = {
            s.id: s
            for s in (
                await self.db.execute(
                    select(MessSubscription).where(
                        MessSubscription.id.in_({r.mess_subscription_id for r in rows} or {uuid.uuid4()})
                    )
                )
            )
            .scalars()
            .all()
        }
        refs = await self.refs([s.student_program_enrollment_id for s in subs.values()])
        plans: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(MessPlan.id, MessPlan.name).where(
                        MessPlan.id.in_({s.mess_plan_id for s in subs.values()} or {uuid.uuid4()})
                    )
                )
            ).all()
        )  # type: ignore[arg-type]
        inv: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(FeeInvoice.id, FeeInvoice.status).where(
                        FeeInvoice.id.in_({r.fee_invoice_id for r in rows if r.fee_invoice_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )  # type: ignore[arg-type]
        return [
            MessBillResponse(
                id=r.id,
                subscription_id=r.mess_subscription_id,
                student=refs.get(subs[r.mess_subscription_id].student_program_enrollment_id)
                if r.mess_subscription_id in subs
                else None,
                plan=plans.get(subs[r.mess_subscription_id].mess_plan_id) if r.mess_subscription_id in subs else None,
                month=r.month,
                days_billed=r.days_billed,
                rebate_days=r.rebate_days,
                amount_paise=r.amount_paise,
                fee_invoice_id=r.fee_invoice_id,
                invoice_status=inv.get(r.fee_invoice_id),
            )
            for r in rows
        ]

    async def bills(
        self, month: date | None, hostel_id: uuid.UUID | None, *, mine: bool = False
    ) -> list[MessBillResponse]:
        q = (
            select(MessBill)
            .join(MessSubscription, MessSubscription.id == MessBill.mess_subscription_id)
            .where(MessBill.institution_id == self.inst)
        )
        if mine or not self.manager():
            q = q.where(
                MessSubscription.student_program_enrollment_id.in_(await self.mine(wards=True) or [uuid.uuid4()])
            )
        else:
            q = q.where(
                resident_predicate(self.principal, MessSubscription.student_program_enrollment_id, None)
                | MessSubscription.student_program_enrollment_id.in_(
                    select(HostelAllocation.student_program_enrollment_id).where(
                        HostelAllocation.hostel_id.in_(visible_hostel_ids(self.principal))
                    )
                )
            )
        if month:
            q = q.where(MessBill.month == month.replace(day=1))
        if hostel_id:
            q = q.where(
                MessSubscription.mess_plan_id.in_(
                    select(MessPlan.id).where((MessPlan.hostel_id == hostel_id) | MessPlan.hostel_id.is_(None))
                )
            )
        rows = list((await self.db.execute(q.order_by(MessBill.month.desc()).limit(5000))).scalars().all())
        return await self.bill_outs(rows)

    async def bill_pdf(self, bill_id: uuid.UUID) -> bytes:
        from app.utils.pdf import simple_pdf

        rows = [b for b in await self.bills(None, None) if b.id == bill_id] or [
            b for b in await self.bills(None, None, mine=True) if b.id == bill_id
        ]
        if not rows:
            raise APIError(404, ErrorCode.NOT_FOUND, "Bill not found")
        b = rows[0]
        lines = [
            f"Mess bill — {b.month:%B %Y}",
            "",
            f"Student: {b.student.name if b.student else ''} ({b.student.registration_number if b.student else ''})",
            f"Plan: {b.plan}",
            f"Days billed: {b.days_billed} (rebate days {b.rebate_days})",
            f"Amount: ₹{b.amount_paise / 100:,.2f}",
            f"Invoice: {b.invoice_status or '—'}",
            f"Generated {now_utc():%d %b %Y}",
        ]
        return simple_pdf(lines, title="Mess bill")
