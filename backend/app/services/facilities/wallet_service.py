"""Canteen & prepaid wallet — Prompts/25 §25.6 ``wallet_service`` ({facilities.canteen_wallet}).

One wallet per person (``UNIQUE (person_type, person_id)``, created on first use). Top-up online through the fees
``PaymentGateway`` (the mock gateway credits at once in development; real gateways credit from ``/wallet/topup/verify``)
or at the counter (``facilities:manage``); parents top up their wards. POS debit by account id or the payer's QR
(``W:<account id>``) under ``SELECT … FOR UPDATE`` with a balance check (409 ``INSUFFICIENT_BALANCE``) and the daily
cap for minors (``wallet.daily_spend_cap_paise``); refunds credit back a debit (never more than it); top-ups above
``wallet.max_balance_paise`` → 422. POS users are ``facilities:manage`` holders or the canteen vendor's portal user.
Statements, daily settlement per canteen / merchant, ledger for ``accounting:view`` holders.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.models.facilities import Canteen, WalletAccount, WalletTransaction
from app.models.inventory import Supplier
from app.models.students import Student
from app.schemas.facilities import (
    CanteenIn,
    CanteenOut,
    WalletCounterTopup,
    WalletDebit,
    WalletOut,
    WalletRefund,
    WalletSettlement,
    WalletStatement,
    WalletTopupRequest,
    WalletTopupResponse,
    WalletTxnOut,
)
from app.services.facilities.common import FacilitiesBase, forbidden, is_auditor, not_found, now_utc, rule


class WalletService(FacilitiesBase):
    audit_module = "facilities"

    # ---- canteens ---------------------------------------------------------------------------------------------------------
    async def canteens(self) -> list[CanteenOut]:
        rows = (
            (await self.db.execute(select(Canteen).where(Canteen.institution_id == self.inst).order_by(Canteen.name)))
            .scalars()
            .all()
        )
        return [CanteenOut.model_validate(r) for r in rows]

    async def save_canteen(self, body: CanteenIn, cid: uuid.UUID | None = None) -> CanteenOut:
        self.require("facilities:manage")
        self.require_writer()
        if cid is None:
            r: Canteen | None = Canteen(institution_id=self.inst, **body.model_dump())
            self.db.add(r)
        else:
            r = (
                await self.db.execute(select(Canteen).where(Canteen.id == cid, Canteen.institution_id == self.inst))
            ).scalar_one_or_none()
            if r is None:
                raise not_found("Canteen")
            for k, v in body.model_dump().items():
                setattr(r, k, v)
        assert r is not None
        await self.db.flush()
        await self._audit("update" if cid else "create", "canteen", r.id, None, {"name": r.name})
        return CanteenOut.model_validate(r)

    async def _pos_canteens(self) -> list[Canteen]:
        if self.can("facilities", "manage"):
            return list((await self.db.execute(select(Canteen).where(Canteen.institution_id == self.inst))).scalars())
        sup = select(Supplier.id).where(Supplier.portal_user_id == self.actor_id)
        return list(
            (
                await self.db.execute(
                    select(Canteen).where(Canteen.institution_id == self.inst, Canteen.vendor_id.in_(sup))
                )
            ).scalars()
        )

    # ---- accounts -------------------------------------------------------------------------------------------------------
    async def account(
        self, ptype: str, pid: uuid.UUID, *, for_update: bool = False, create: bool = True
    ) -> WalletAccount | None:
        stmt = select(WalletAccount).where(
            WalletAccount.person_type == ptype,
            WalletAccount.person_id == pid,
            WalletAccount.institution_id == self.inst,
        )
        if for_update:
            stmt = stmt.with_for_update()
        a = (await self.db.execute(stmt)).scalar_one_or_none()
        if a is None and create:
            a = WalletAccount(
                institution_id=self.inst, person_type=ptype, person_id=pid, balance_paise=0, status="active"
            )
            self.db.add(a)
            await self.db.flush()
            if for_update:
                a = (await self.db.execute(stmt)).scalar_one()
        return a

    async def wallet_out(self, a: WalletAccount | None, ptype: str, pid: uuid.UUID) -> WalletOut:
        name = (await self.person_names([(ptype, pid)])).get(pid)
        recent: list[dict[str, Any]] = []
        if a is not None:
            rows = (
                (
                    await self.db.execute(
                        select(WalletTransaction)
                        .where(WalletTransaction.account_id == a.id)
                        .order_by(WalletTransaction.created_at.desc())
                        .limit(10)
                    )
                )
                .scalars()
                .all()
            )
            recent = [WalletTxnOut.model_validate(t).model_dump(mode="json") for t in rows]
        return WalletOut(
            account_id=a.id if a else None,
            person_type=ptype,
            person_id=pid,
            name=name,
            balance_paise=a.balance_paise if a else 0,
            status=a.status if a else "active",
            pay_qr=f"W:{a.id}" if a else None,
            recent=recent,
        )

    async def me(self) -> WalletOut:
        ptype, pid = await self.me_person()
        a = await self.account(ptype, pid, create=False)
        return await self.wallet_out(a, ptype, pid)

    async def wards(self) -> list[WalletOut]:
        out = []
        for sid in await self.ward_ids():
            a = await self.account("student", sid, create=False)
            out.append(await self.wallet_out(a, "student", sid))
        return out

    async def _credit(
        self, a: WalletAccount, amount: int, kind: str, merchant: str | None, reference: str | None
    ) -> WalletTransaction:
        cap = await self.int_setting("wallet", "max_balance_paise", 500000)
        if kind == "topup" and cap and a.balance_paise + amount > cap:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"The wallet may hold at most ₹{cap / 100:,.0f}",
                {"code": "WALLET_MAX_BALANCE", "max_balance_paise": cap},
            )
        a.balance_paise += amount
        t = WalletTransaction(
            institution_id=self.inst,
            account_id=a.id,
            txn_type=kind,
            amount_paise=amount,
            merchant=merchant,
            reference=reference,
        )
        self.db.add(t)
        await self.db.flush()
        return t

    async def topup(self, body: WalletTopupRequest) -> WalletTopupResponse:
        from app.integrations.payments import MockGateway, gateway

        self.require_writer()
        minimum = await self.int_setting("wallet", "topup_min_paise", 5000)
        if body.amount_paise < minimum:
            raise APIError(422, ErrorCode.VALIDATION, f"Top up at least ₹{minimum / 100:,.0f}", {"code": "TOPUP_MIN"})
        if body.ward_student_id:
            if body.ward_student_id not in await self.ward_ids():
                raise not_found("Student")
            ptype, pid = "student", body.ward_student_id
        else:
            ptype, pid = await self.me_person()
        a = await self.account(ptype, pid, for_update=True)
        assert a is not None
        provider = str(await self.setting("fees", "gateway_provider") or "mock")
        gw = gateway(provider)
        order = await gw.create_order(
            amount_paise=body.amount_paise,
            receipt=f"WAL-{str(a.id)[:8]}",
            notes={"source_type": "wallet_topup", "account_id": str(a.id)},
        )
        if isinstance(gw, MockGateway):
            t = await self._credit(a, body.amount_paise, "topup", "online", str(order.get("order_id")))
            await self._after_topup(a, t, ptype, pid)
            return WalletTopupResponse(order=order, credited=True, balance_paise=a.balance_paise, transaction_id=t.id)
        await self.put_meta(
            "wallet_order", order.get("order_id"), {"account_id": str(a.id), "amount_paise": body.amount_paise}
        )
        return WalletTopupResponse(order=order, credited=False, balance_paise=a.balance_paise)

    async def verify_topup(self, order_id: str, payment_id: str, signature: str) -> WalletTopupResponse:
        from app.integrations.payments import gateway

        m = await self.meta("wallet_order", order_id)
        if not m:
            raise not_found("Order")
        if m.get("credited"):
            raise rule("This order was already credited", "ALREADY_CREDITED")
        provider = str(await self.setting("fees", "gateway_provider") or "mock")
        if not gateway(provider).verify_signature(order_id=order_id, payment_id=payment_id, signature=signature):
            raise APIError(400, ErrorCode.VALIDATION, "Invalid payment signature", {"code": "BAD_SIGNATURE"})
        a = (
            await self.db.execute(
                select(WalletAccount).where(WalletAccount.id == uuid.UUID(m["account_id"])).with_for_update()
            )
        ).scalar_one()
        t = await self._credit(a, int(m["amount_paise"]), "topup", "online", order_id)
        m["credited"] = True
        await self.put_meta("wallet_order", order_id, m)
        await self._after_topup(a, t, a.person_type, a.person_id)
        return WalletTopupResponse(
            order={"order_id": order_id}, credited=True, balance_paise=a.balance_paise, transaction_id=t.id
        )

    async def counter_topup(self, body: WalletCounterTopup) -> WalletOut:
        self.require("facilities:manage")
        self.require_writer()
        a = await self.account(body.person_type, body.person_id, for_update=True)
        assert a is not None
        t = await self._credit(a, body.amount_paise, "topup", "counter", body.reference)
        await self._after_topup(a, t, body.person_type, body.person_id)
        return await self.wallet_out(a, body.person_type, body.person_id)

    async def _after_topup(self, a: WalletAccount, t: WalletTransaction, ptype: str, pid: uuid.UUID) -> None:
        await self._audit("topup", "wallet_account", a.id, None, {"amount_paise": t.amount_paise})
        await self._emit(
            "wallet.topup",
            {"account_id": str(a.id), "amount_paise": t.amount_paise, "source_type": "wallet_topup"},
            "wallet_account",
            a.id,
        )
        uid = await self.person_user_id(ptype, pid)
        await self._notify(
            "wallet.topup",
            [uid],
            {"amount": f"{t.amount_paise / 100:,.2f}", "balance": f"{a.balance_paise / 100:,.2f}"},
            guardians=ptype == "student",
        )

    async def debit(self, body: WalletDebit) -> WalletTxnOut:
        canteens = await self._pos_canteens()
        if not canteens and not self.can("facilities", "manage"):
            raise forbidden("POS access is limited to canteen vendors")
        canteen = next((c for c in canteens if c.id == body.canteen_id), canteens[0] if canteens else None)
        acc_id = body.account_id
        if body.qr:
            raw = body.qr.removeprefix("W:")
            try:
                acc_id = uuid.UUID(raw)
            except ValueError:
                raise APIError(422, ErrorCode.VALIDATION, "Unreadable wallet QR") from None
        if acc_id is None:
            raise APIError(422, ErrorCode.VALIDATION, "account_id or qr is required")
        a = (
            await self.db.execute(
                select(WalletAccount)
                .where(WalletAccount.id == acc_id, WalletAccount.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Wallet")
        if a.status != "active":
            raise rule("The wallet is not active", "WALLET_INACTIVE")
        if a.balance_paise < body.amount_paise:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "Insufficient wallet balance",
                {"code": "INSUFFICIENT_BALANCE", "balance_paise": a.balance_paise},
            )
        cap = await self.setting("wallet", "daily_spend_cap_paise")
        if cap and a.person_type == "student":
            st = await self.db.get(Student, a.person_id)
            if st is not None and not await self.is_adult(st.dob):
                start = datetime.combine(await self.today(), time(0, 0)).astimezone()
                spent = (
                    await self.db.execute(
                        select(func.coalesce(func.sum(WalletTransaction.amount_paise), 0)).where(
                            WalletTransaction.account_id == a.id,
                            WalletTransaction.txn_type == "debit",
                            WalletTransaction.created_at >= start,
                        )
                    )
                ).scalar_one()
                if int(spent) + body.amount_paise > int(cap):
                    raise rule("The daily spend limit is reached", "DAILY_CAP")
        a.balance_paise -= body.amount_paise
        t = WalletTransaction(
            institution_id=self.inst,
            account_id=a.id,
            txn_type="debit",
            amount_paise=body.amount_paise,
            merchant=(body.merchant or (canteen.name if canteen else "POS"))[:120],
            reference=body.reference or (f"canteen:{canteen.id}" if canteen else None),
        )
        self.db.add(t)
        await self.db.flush()
        await self._emit(
            "wallet.debit", {"account_id": str(a.id), "amount_paise": t.amount_paise}, "wallet_account", a.id
        )
        uid = await self.person_user_id(a.person_type, a.person_id)
        await self._notify(
            "wallet.debit",
            [uid],
            {
                "amount": f"{t.amount_paise / 100:,.2f}",
                "merchant": t.merchant or "",
                "balance": f"{a.balance_paise / 100:,.2f}",
            },
        )
        o = WalletTxnOut.model_validate(t)
        o.balance_after_paise = a.balance_paise
        return o

    async def refund(self, body: WalletRefund) -> WalletTxnOut:
        if not (self.can("facilities", "manage") or await self._pos_canteens()):
            raise forbidden("Refunds are made by the canteen or the estate office")
        src = (
            await self.db.execute(
                select(WalletTransaction).where(
                    WalletTransaction.id == body.transaction_id, WalletTransaction.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if src is None or src.txn_type != "debit":
            raise not_found("Debit")
        refunded = (
            await self.db.execute(
                select(func.coalesce(func.sum(WalletTransaction.amount_paise), 0)).where(
                    WalletTransaction.txn_type == "refund", WalletTransaction.reference == f"refund:{src.id}"
                )
            )
        ).scalar_one()
        amount = body.amount_paise or (src.amount_paise - int(refunded))
        if amount <= 0 or int(refunded) + amount > src.amount_paise:
            raise rule("The refund exceeds the debit", "REFUND_EXCEEDS")
        a = (
            await self.db.execute(select(WalletAccount).where(WalletAccount.id == src.account_id).with_for_update())
        ).scalar_one()
        t = await self._credit(a, amount, "refund", src.merchant, f"refund:{src.id}")
        await self._audit("refund", "wallet_account", a.id, None, {"amount_paise": amount, "reason": body.reason})
        await self._emit("wallet.refund", {"account_id": str(a.id), "amount_paise": amount}, "wallet_account", a.id)
        o = WalletTxnOut.model_validate(t)
        o.balance_after_paise = a.balance_paise
        return o

    async def statement(self, account_id: uuid.UUID | None, d0: date | None, d1: date | None) -> WalletStatement:
        if account_id is None:
            ptype, pid = await self.me_person()
            a = await self.account(ptype, pid)
        else:
            a = (
                await self.db.execute(
                    select(WalletAccount).where(
                        WalletAccount.id == account_id, WalletAccount.institution_id == self.inst
                    )
                )
            ).scalar_one_or_none()
            if a is None:
                raise not_found("Wallet")
            own = False
            try:
                ptype, pid = await self.me_person()
                own = (a.person_type, a.person_id) == (ptype, pid)
            except APIError:
                own = False
            ward = a.person_type == "student" and a.person_id in await self.ward_ids()
            if not (
                own
                or ward
                or self.can("facilities", "manage")
                or self.can("accounting", "view")
                or self.can("facilities", "view_all")
            ):
                raise not_found("Wallet")
        assert a is not None
        rows = (
            (
                await self.db.execute(
                    select(WalletTransaction)
                    .where(WalletTransaction.account_id == a.id)
                    .order_by(WalletTransaction.created_at)
                )
            )
            .scalars()
            .all()
        )
        bal, opening = 0, 0
        txns: list[WalletTxnOut] = []
        credits = debits = 0
        for t in rows:
            delta = -t.amount_paise if t.txn_type == "debit" else t.amount_paise
            day = t.created_at.date()
            if d0 and day < d0:
                bal += delta
                opening = bal
                continue
            if d1 and day > d1:
                continue
            bal += delta
            if delta > 0:
                credits += delta
            else:
                debits += -delta
            o = WalletTxnOut.model_validate(t)
            o.balance_after_paise = bal
            txns.append(o)
        return WalletStatement(
            account_id=a.id,
            opening_paise=opening,
            closing_paise=bal,
            credits_paise=credits,
            debits_paise=debits,
            transactions=txns,
        )

    async def settlement(self, canteen_id: uuid.UUID | None, on: date) -> WalletSettlement:
        canteens = await self._pos_canteens()
        if not (
            self.can("facilities", "manage")
            or self.can("accounting", "view")
            or self.can("facilities", "view_all")
            or canteens
        ):
            raise forbidden("Settlement is for the canteen, the estate office and accounts")
        if canteens and not self.can("facilities", "manage") and canteen_id not in {c.id for c in canteens}:
            canteen_id = canteens[0].id
        start = datetime.combine(on, time(0, 0)).astimezone()
        end = start + timedelta(days=1)
        stmt = select(
            WalletTransaction.txn_type, func.count(), func.coalesce(func.sum(WalletTransaction.amount_paise), 0)
        ).where(
            WalletTransaction.institution_id == self.inst,
            WalletTransaction.created_at >= start,
            WalletTransaction.created_at < end,
        )
        merchant = None
        if canteen_id:
            c = (await self.db.execute(select(Canteen).where(Canteen.id == canteen_id))).scalar_one_or_none()
            merchant = c.name if c else None
            stmt = stmt.where(WalletTransaction.merchant == merchant)
        by = {
            k: (int(n), int(s)) for k, n, s in (await self.db.execute(stmt.group_by(WalletTransaction.txn_type))).all()
        }
        d, r = by.get("debit", (0, 0)), by.get("refund", (0, 0))
        return WalletSettlement(
            canteen_id=canteen_id,
            merchant=merchant,
            on=on,
            debits=d[0],
            debit_paise=d[1],
            refunds=r[0],
            refund_paise=r[1],
            net_paise=d[1] - r[1],
        )

    async def ledger(self, limit: int = 500) -> list[WalletTxnOut]:
        if (
            is_auditor(self.principal)
            or self.can("accounting", "view")
            or self.can("facilities", "manage")
            or self.can("facilities", "view_all")
        ):
            rows = (
                (
                    await self.db.execute(
                        select(WalletTransaction)
                        .where(WalletTransaction.institution_id == self.inst)
                        .order_by(WalletTransaction.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [WalletTxnOut.model_validate(t) for t in rows]
        raise forbidden("accounting:view required")

    async def limits_reset(self) -> int:
        return 0  # daily caps are computed from the day's debits; nothing to reset — the Beat stays for parity

    async def txn_rows(self, rows: Sequence[WalletTransaction]) -> list[WalletTxnOut]:
        return [WalletTxnOut.model_validate(t) for t in rows]

    async def touch(self) -> datetime:
        return now_utc()
