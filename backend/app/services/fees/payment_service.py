"""Payments — Prompts/12 §12.6 ``payment_service``.

1. Counter ``collect`` (``Idempotency-Key`` — a replay returns the same receipt): invoices locked ``FOR UPDATE``;
   amount allocated oldest-due first (or the explicit allocation); over-payment without ``allow_advance`` → 422;
   receipt number from ``fee_receipt_no``; day-book upsert; post-payment path.
2. Online: ``initiate`` → ``PaymentGateway.create_order`` → ``initiated`` rows (one per invoice, shared order id);
   webhook (signature mandatory → 401) or client verify → ``success`` → post-payment path; duplicates are no-ops.
   UPI QR: a dynamic intent with a reference; status polled; ``/_dev`` callback settles it.
3. Offline: student declares NEFT / challan / DD with UTR → ``initiated``; bank statement rows auto-match by UTR +
   amount → accountant confirms → ``reconciled``; cheque bounce → ``bounced`` + bank-charge item, invoice reopened.
4. Receipt cancellation → workflow ``fees.receipt_cancel`` (accountant → principal) → ``cancelled``, balance restored.
5. Day-book per counter / collector / date by mode; close & deposit; CSV export.

Post-payment path: recompute → release ``fee_invoice`` holds when settled → day-book → emit ``fees.payment_received``
``{source_type, source_id, receipt_no, invoice_id, amount_paise, payer_type, payer_id}`` (Phase 08 / 09 / 11
consumers) → notification → receipt PDF job.
"""

import csv
import io
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.enums.fees import CASH_MODES, CHEQUE_MODES, OPEN_INVOICE, SETTLED_PAYMENT
from app.integrations.payments import UpiCollect, gateway
from app.models.fees import DayBookEntry, FeeInvoice, FeeInvoiceItem, FeePayment, OfflinePaymentReconciliation
from app.models.platform import User, WorkflowInstance
from app.schemas.fees import (
    BounceRequest,
    CollectRequest,
    DayBookClose,
    DayBookResponse,
    DayBookRow,
    FeePaymentOut,
    OfflineDeclare,
    OnlineInitiateRequest,
    OnlineInitiateResponse,
    OnlineVerifyRequest,
    OrderStatusResponse,
    ReceiptResponse,
    ReconcileRowIn,
    ReconcileRowOut,
    ReconcileSummary,
    ThermalReceipt,
    UpiQrRequest,
    UpiQrResponse,
)
from app.services.fees.common import FeesBase, now_utc, rule, rupees
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta

ENTITY = "fee_payment"
WF_CANCEL = "fees.receipt_cancel"


class PaymentService(FeesBase):
    # ---- core ---------------------------------------------------------------------------------------------------------
    async def record(
        self,
        inv: FeeInvoice,
        amount: int,
        mode: str,
        *,
        status: str = "success",
        reference: str | None = None,
        utr: str | None = None,
        bank: str | None = None,
        counter: str | None = None,
        gateway_name: str | None = None,
        order_id: str | None = None,
        idem: str | None = None,
        emit: bool = True,
        paid_on: date | None = None,
    ) -> FeePayment:
        receipt = (
            (await self.sequence("fee_receipt_no", "RCP", inv.college_id)).upper()
            if status == "success"
            else f"PEND-{uuid.uuid4().hex[:12].upper()}"
        )
        p = FeePayment(
            institution_id=self.inst,
            invoice_id=inv.id,
            receipt_number=receipt,
            amount_paise=amount,
            payment_date=paid_on or await self.today(),
            payment_mode=mode,
            gateway=gateway_name,
            gateway_order_id=order_id,
            reference_no=reference,
            utr=utr,
            bank_name=bank,
            status=status,
            collected_by=self.actor_id,
            counter=counter,
            idempotency_key=idem,
        )
        self.db.add(p)
        await self.db.flush()
        if status == "success":
            await self.after_settle(inv, p, emit=emit)
        else:
            await self.recompute(inv)
        return p

    async def after_settle(self, inv: FeeInvoice, p: FeePayment, *, emit: bool = True) -> None:
        from app.services.fees.invoice_service import InvoiceService

        await self.recompute(inv)
        if inv.balance_paise <= 0:
            await InvoiceService(self.db, self.principal, self.request, self.inst).release_holds(inv)
        await self.day_book_add(p)
        await self._audit(
            "collect",
            ENTITY,
            p.id,
            None,
            {
                "invoice_id": str(inv.id),
                "receipt_number": p.receipt_number,
                "amount_paise": p.amount_paise,
                "mode": p.payment_mode,
            },
        )
        if not emit:
            return
        payload = {
            "source_type": inv.source_type,
            "source_id": str(inv.source_id) if inv.source_id else None,
            "receipt_no": p.receipt_number,
            "invoice_id": str(inv.id),
            "payment_id": str(p.id),
            "amount_paise": p.amount_paise,
            "invoice_status": inv.status,
            "balance_paise": inv.balance_paise,
            "payer_type": inv.payer_type,
            "payer_id": str(inv.payer_id),
            "student_program_enrollment_id": str(inv.student_program_enrollment_id)
            if inv.student_program_enrollment_id
            else None,
        }
        await self._emit("fees.payment_received", payload, ENTITY, p.id)
        from app.services.fees.invoice_service import InvoiceService as _I

        await self._notify(
            "fees.payment_received",
            await _I(self.db, self.principal, self.request, self.inst).payer_user_ids(inv),
            {"amount": rupees(p.amount_paise), "receipt_no": p.receipt_number},
            guardians=inv.payer_type == "student",
        )
        await self.queue_receipt(p)

    async def queue_receipt(self, p: FeePayment) -> None:
        if self.principal is None or getattr(self.principal, "id", None) is None:
            return
        try:
            from app.core.jobs import enqueue

            await enqueue(self.db, self.principal, "fees.receipt_pdf", {"payment_id": str(p.id)})
        except Exception:  # noqa: BLE001 - the receipt can always be rendered on demand
            pass

    async def day_book_add(self, p: FeePayment, sign: int = 1) -> None:
        inv_college = (
            await self.db.execute(select(FeeInvoice.college_id).where(FeeInvoice.id == p.invoice_id))
        ).scalar_one_or_none()
        q = (
            select(DayBookEntry)
            .where(
                DayBookEntry.institution_id == self.inst,
                DayBookEntry.entry_date == p.payment_date,
                DayBookEntry.college_id.is_(None) if inv_college is None else DayBookEntry.college_id == inv_college,
                DayBookEntry.counter.is_(None) if p.counter is None else DayBookEntry.counter == p.counter,
                DayBookEntry.collected_by.is_(None)
                if p.collected_by is None
                else DayBookEntry.collected_by == p.collected_by,
            )
            .with_for_update()
        )
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            row = DayBookEntry(
                institution_id=self.inst,
                college_id=inv_college,
                entry_date=p.payment_date,
                counter=p.counter,
                collected_by=p.collected_by,
                cash_paise=0,
                digital_paise=0,
                cheque_paise=0,
                deposited_paise=0,
                status="open",
            )
            self.db.add(row)
        amt = sign * p.amount_paise
        if p.payment_mode in CASH_MODES:
            row.cash_paise += amt
        elif p.payment_mode in CHEQUE_MODES:
            row.cheque_paise += amt
        elif p.payment_mode not in ("adjustment", "scholarship_credit"):
            row.digital_paise += amt
        await self.db.flush()

    # ---- 1. counter collect -------------------------------------------------------------------------------------------
    async def collect(self, body: CollectRequest, idem: str | None) -> ReceiptResponse:
        if idem:
            prior = (
                (
                    await self.db.execute(
                        select(FeePayment).where(
                            FeePayment.institution_id == self.inst, FeePayment.idempotency_key == idem
                        )
                    )
                )
                .scalars()
                .all()
            )
            if prior:
                return await self.receipt_response(prior)
        ids = [a.invoice_id for a in body.allocation] if body.allocation else [body.invoice_id]  # type: ignore[list-item]
        for i in ids:
            await self.fees.get_visible(i)  # 404 for invisible invoices
        invs = await self.fees.lock_many([i for i in ids if i])
        for inv in invs:
            await self.recompute(inv)
            if inv.status in ("cancelled", "refunded"):
                raise rule(f"Invoice {inv.invoice_number} is {inv.status}", "INVOICE_CLOSED")
        by_id = {i.id: i for i in invs}
        if body.allocation:
            plan = [(by_id[a.invoice_id], a.amount_paise) for a in body.allocation]
            if sum(a for _, a in plan) != body.amount_paise:
                raise APIError(
                    422, ErrorCode.VALIDATION, "The allocation does not add up to amount_paise", {"field": "allocation"}
                )
        else:
            plan = [(invs[0], body.amount_paise)]
        for inv, amt in plan:
            if amt > max(inv.balance_paise, 0) and not body.allow_advance:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"{rupees(amt)} exceeds the balance {rupees(inv.balance_paise)} of {inv.invoice_number}",
                    {"code": "OVERPAYMENT", "balance_paise": inv.balance_paise},
                )
        mode = str(body.mode)
        reference = body.reference or (f"{body.cheque.no} / {body.cheque.date.isoformat()}" if body.cheque else None)
        bank = body.bank or (body.cheque.bank if body.cheque else None)
        payments = []
        for inv, amt in plan:
            payments.append(
                await self.record(
                    inv,
                    amt,
                    mode,
                    reference=reference,
                    utr=body.utr,
                    bank=bank,
                    counter=body.counter or "main",
                    idem=idem,
                )
            )
        return await self.receipt_response(payments)

    async def receipt_response(self, payments: Sequence[FeePayment]) -> ReceiptResponse:
        invs = (
            (await self.db.execute(select(FeeInvoice).where(FeeInvoice.id.in_([p.invoice_id for p in payments]))))
            .scalars()
            .all()
        )
        return ReceiptResponse(
            receipt_numbers=[p.receipt_number for p in payments],
            payments=await self.payment_outs(payments),
            invoices=await self.invoice_outs(invs),
            amount_paise=sum(p.amount_paise for p in payments),
        )

    async def list_payments(self, params: PageParams, **filters: Any) -> tuple[list[FeePaymentOut], PaginationMeta]:
        stmt = self.fees.payments_stmt(**filters)
        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await self.db.execute(stmt.offset(params.offset).limit(params.page_size))).scalars().all()
        return await self.payment_outs(rows), PaginationMeta(
            page=params.page, page_size=params.page_size, total=total, total_pages=max(1, -(-total // params.page_size))
        )

    async def get_payment(self, pid: uuid.UUID) -> FeePaymentOut:
        return (await self.payment_outs([await self.fees.payment(pid)]))[0]

    async def my_receipts(self) -> list[FeePaymentOut]:
        stmt = self.fees.payments_stmt(scope="self").where(
            FeePayment.status.in_(tuple(SETTLED_PAYMENT) + ("cancelled", "bounced"))
        )
        return await self.payment_outs((await self.db.execute(stmt.limit(200))).scalars().all())

    # ---- receipts ------------------------------------------------------------------------------------------------------
    async def receipt_lines(self, pid: uuid.UUID) -> tuple[FeePayment, list[str], str]:
        p = await self.fees.payment(pid)
        inv = await self.fees.get_any(p.invoice_id)
        inst = await self.institution()
        name = (await self.payer_names([inv])).get(inv.student_program_enrollment_id or inv.payer_id, (None, None))
        items = (
            (await self.db.execute(select(FeeInvoiceItem).where(FeeInvoiceItem.invoice_id == inv.id))).scalars().all()
        )
        lines = [
            inst.name,
            f"FEE RECEIPT  {p.receipt_number}",
            f"Date: {p.payment_date.isoformat()}   Mode: {p.payment_mode.upper()}   Status: {p.status}",
            f"Received from: {name[0] or '-'} ({name[1] or '-'})",
            f"Invoice: {inv.invoice_number}  {inv.description or ''}",
            "-" * 60,
        ]
        for it in items:
            tax = f" + GST {rupees(it.tax_paise)}" if it.tax_paise else ""
            lines.append(f"{it.description[:40]:40s} {rupees(it.amount_paise):>14s}{tax}")
        lines += [
            "-" * 60,
            f"Amount received: {rupees(p.amount_paise)}",
            f"Invoice balance: {rupees(inv.balance_paise)}",
        ]
        if p.reference_no or p.utr:
            lines.append(f"Reference: {p.reference_no or ''} {p.utr or ''}")
        if inv.gst_number:
            lines.append(f"GSTIN: {inv.gst_number}")
        if p.status == "cancelled":
            lines.append(f"CANCELLED: {p.cancel_reason or ''}")
        html = (
            "<html><body style='font-family:sans-serif'>"
            + "".join(f"<p>{line}</p>" for line in lines)
            + "</body></html>"
        )
        return p, lines, html

    async def receipt_pdf(self, pid: uuid.UUID) -> tuple[bytes, str]:
        from app.utils.pdf import render_pdf

        p, lines, html = await self.receipt_lines(pid)
        return render_pdf(html, lines, title=f"Receipt {p.receipt_number}"), p.receipt_number

    async def thermal(self, pid: uuid.UUID) -> ThermalReceipt:
        p, lines, _ = await self.receipt_lines(pid)
        cmds: list[dict[str, Any]] = [
            {"cmd": "init"},
            {"cmd": "align", "value": "center"},
            {"cmd": "bold", "value": True},
            {"cmd": "text", "value": lines[0][:32]},
            {"cmd": "bold", "value": False},
            {"cmd": "align", "value": "left"},
        ]
        cmds += [{"cmd": "text", "value": line[:32]} for line in lines[1:]]
        cmds += [{"cmd": "feed", "value": 3}, {"cmd": "cut"}]
        return ThermalReceipt(
            receipt_number=p.receipt_number, commands=cmds, text="\n".join(line[:32] for line in lines)
        )

    # ---- 2. online ------------------------------------------------------------------------------------------------------
    async def _gateway(self, name: str | None = None) -> tuple[str, Any]:
        provider = name or str(await self.setting("fees", "gateway_provider") or "mock")
        return provider, gateway(provider)

    async def initiate(self, body: OnlineInitiateRequest) -> OnlineInitiateResponse:
        invs = []
        for i in body.invoice_ids:
            invs.append(await self.fees.get_visible(i, for_update=True))
        for inv in invs:
            await self.recompute(inv)
            if inv.status not in OPEN_INVOICE or inv.balance_paise <= 0:
                raise rule(f"Invoice {inv.invoice_number} has nothing due", "NOTHING_DUE")
        total = sum(i.balance_paise for i in invs)
        amount = body.amount_paise or total
        if amount > total:
            raise APIError(422, ErrorCode.VALIDATION, "Amount exceeds the dues", {"code": "OVERPAYMENT"})
        provider, gw = await self._gateway(body.gateway)
        order = await gw.create_order(
            amount_paise=amount, receipt=invs[0].invoice_number, notes={"invoices": [str(i.id) for i in invs]}
        )
        left, ids = amount, []
        for inv in invs:
            share = min(left, inv.balance_paise)
            if share <= 0:
                break
            left -= share
            p = await self.record(
                inv, share, "gateway", status="initiated", gateway_name=provider, order_id=order["order_id"]
            )
            ids.append(p.id)
        await self._audit(
            "online_initiate",
            ENTITY,
            ids[0] if ids else None,
            None,
            {"order_id": order["order_id"], "amount_paise": amount, "gateway": provider},
        )
        return OnlineInitiateResponse(
            order_id=order["order_id"],
            gateway=provider,
            key=order.get("key"),
            amount=amount,
            checkout=order.get("checkout") or {},
            payment_ids=ids,
        )

    async def _order_rows(self, order_id: str) -> list[FeePayment]:
        return list(
            (
                await self.db.execute(
                    select(FeePayment)
                    .where(FeePayment.institution_id == self.inst, FeePayment.gateway_order_id == order_id)
                    .order_by(FeePayment.created_at)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )

    async def settle_order(
        self, order_id: str, payment_id: str | None, signature: str | None, *, mode: str = "gateway"
    ) -> OrderStatusResponse:
        rows = await self._order_rows(order_id)
        if not rows:
            raise APIError(404, ErrorCode.NOT_FOUND, "Order not found")
        receipts = []
        for p in rows:
            if p.status != "initiated":
                receipts.append(p.receipt_number)
                continue  # duplicate webhook / verify → idempotent
            inv = await self.fees.get_any(p.invoice_id, for_update=True)
            p.status = "success"
            p.receipt_number = (await self.sequence("fee_receipt_no", "RCP", inv.college_id)).upper()
            p.gateway_payment_id, p.gateway_signature, p.payment_mode = payment_id, signature, mode
            p.payment_date = await self.today()
            await self.db.flush()
            await self.after_settle(inv, p)
            receipts.append(p.receipt_number)
        return OrderStatusResponse(
            order_id=order_id,
            status="success",
            amount_paise=sum(p.amount_paise for p in rows),
            receipt_numbers=receipts,
        )

    async def fail_order(self, order_id: str, reason: str = "failed") -> int:
        n = 0
        for p in await self._order_rows(order_id):
            if p.status == "initiated":
                p.status = "failed"
                n += 1
                await self._emit(
                    "fees.payment_failed",
                    {"order_id": order_id, "invoice_id": str(p.invoice_id), "reason": reason},
                    ENTITY,
                    p.id,
                )
        await self.db.flush()
        return n

    async def verify(self, body: OnlineVerifyRequest) -> OrderStatusResponse:
        rows = await self._order_rows(body.order_id)
        if not rows:
            raise APIError(404, ErrorCode.NOT_FOUND, "Order not found")
        for p in rows:
            await self.fees.get_visible(p.invoice_id)
        _, gw = await self._gateway(rows[0].gateway)
        if not gw.verify_signature(order_id=body.order_id, payment_id=body.payment_id, signature=body.signature):
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid payment signature")
        return await self.settle_order(body.order_id, body.payment_id, body.signature)

    async def webhook(
        self, provider: str, raw: bytes, signature: str | None, payload: dict[str, Any]
    ) -> dict[str, Any]:
        gw = gateway(provider)
        if not signature or not gw.verify_webhook(body=raw, signature=signature):
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid webhook signature")
        entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or payload
        order_id = entity.get("order_id")
        if not order_id:
            raise APIError(422, ErrorCode.VALIDATION, "order_id missing")
        event = str(payload.get("event") or entity.get("status") or "payment.captured")
        if "fail" in event:
            return {"order_id": order_id, "failed": await self.fail_order(order_id, event)}
        out = await self.settle_order(order_id, entity.get("id"), signature)
        return out.model_dump(mode="json")

    async def order_status(self, order_id: str) -> OrderStatusResponse:
        rows = (
            (
                await self.db.execute(
                    select(FeePayment).where(
                        FeePayment.institution_id == self.inst, FeePayment.gateway_order_id == order_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            raise APIError(404, ErrorCode.NOT_FOUND, "Order not found")
        for p in rows:
            await self.fees.get_visible(p.invoice_id)
        statuses = {p.status for p in rows}
        status = (
            "success"
            if statuses <= {"success", "reconciled"}
            else ("failed" if statuses == {"failed"} else "initiated")
        )
        return OrderStatusResponse(
            order_id=order_id,
            status=status,
            amount_paise=sum(p.amount_paise for p in rows),
            receipt_numbers=[p.receipt_number for p in rows if p.status == "success"],
        )

    async def poll_initiated(self) -> int:
        """Beat ``fees.gateway_status_poll``: orders older than 30 min still ``initiated`` → provider status."""
        from datetime import timedelta

        cutoff = now_utc() - timedelta(minutes=30)
        rows = (
            await self.db.execute(
                select(FeePayment.gateway_order_id, FeePayment.gateway)
                .where(
                    FeePayment.institution_id == self.inst,
                    FeePayment.status == "initiated",
                    FeePayment.gateway_order_id.is_not(None),
                    FeePayment.created_at < cutoff,
                )
                .distinct()
            )
        ).all()
        n = 0
        for order_id, provider in rows:
            try:
                st = await gateway(provider or "mock").fetch_status(order_id)
            except Exception:  # noqa: BLE001 - provider outage: retry next poll
                continue
            if st == "paid":
                await self.settle_order(order_id, None, None)
                n += 1
            elif now_utc() - cutoff > timedelta(hours=24) or st == "failed":
                n += await self.fail_order(order_id, "timeout")
        return n

    # UPI QR
    async def upi_qr(self, body: UpiQrRequest) -> UpiQrResponse:
        inv = await self.fees.get_visible(body.invoice_id, for_update=True)
        await self.recompute(inv)
        if inv.balance_paise <= 0:
            raise rule("Nothing is due on this invoice", "NOTHING_DUE")
        amount = min(body.amount_paise or inv.balance_paise, inv.balance_paise)
        ref = f"UPI{uuid.uuid4().hex[:12].upper()}"
        await self.record(inv, amount, "upi", status="initiated", gateway_name="upi_qr", order_id=ref)
        inst = await self.institution()
        qr = UpiCollect(await self.setting("fees", "upi_vpa"), inst.name).generate_qr(amount, ref)
        return UpiQrResponse(**qr, status="pending")

    async def upi_status(self, ref: str) -> OrderStatusResponse:
        return await self.order_status(ref)

    # ---- 3. offline -----------------------------------------------------------------------------------------------------
    async def declare(self, body: OfflineDeclare) -> FeePaymentOut:
        inv = await self.fees.get_visible(body.invoice_id, for_update=True)
        await self.recompute(inv)
        if body.amount_paise > max(inv.balance_paise, 0):
            raise APIError(422, ErrorCode.VALIDATION, "Amount exceeds the balance", {"code": "OVERPAYMENT"})
        dup = (
            await self.db.execute(
                select(FeePayment.id).where(
                    FeePayment.institution_id == self.inst,
                    FeePayment.utr == body.utr,
                    FeePayment.status.in_(("initiated", "success", "reconciled")),
                )
            )
        ).first()
        if dup:
            raise APIError(409, ErrorCode.CONFLICT, "This UTR was already declared")
        p = await self.record(
            inv,
            body.amount_paise,
            str(body.mode),
            status="initiated",
            utr=body.utr,
            bank=body.bank,
            paid_on=body.paid_on,
        )
        await self._audit("offline_declare", ENTITY, p.id, None, {"utr": body.utr, "amount_paise": body.amount_paise})
        return (await self.payment_outs([p]))[0]

    async def reconcile_rows(
        self, rows: Sequence[ReconcileRowIn], file_url: str | None, *, dry_run: bool = False
    ) -> ReconcileSummary:
        out = ReconcileSummary(rows=len(rows), dry_run=dry_run)
        for r in rows:
            match = await self._propose(r.utr, r.amount_paise)
            if match is not None:
                out.auto_matched += 1
            else:
                out.unmatched += 1
            if dry_run:
                continue
            exists = (
                (
                    await self.db.execute(
                        select(OfflinePaymentReconciliation.id).where(
                            OfflinePaymentReconciliation.institution_id == self.inst,
                            OfflinePaymentReconciliation.utr == r.utr,
                            OfflinePaymentReconciliation.amount_paise == r.amount_paise,
                        )
                    )
                ).first()
                if r.utr
                else None
            )
            if exists:
                continue
            self.db.add(
                OfflinePaymentReconciliation(
                    institution_id=self.inst,
                    statement_file_url=file_url,
                    bank_account=r.bank_account,
                    statement_date=r.statement_date,
                    utr=r.utr,
                    amount_paise=r.amount_paise,
                    payer_hint=(r.payer_hint or "")[:200] or None,
                    status="unmatched",
                )
            )
        await self.db.flush()
        if not dry_run:
            await self._audit(
                "reconcile_upload",
                "offline_reconciliation",
                None,
                None,
                {"rows": out.rows, "auto_matched": out.auto_matched},
            )
        return out

    @staticmethod
    def parse_statement(text: str) -> list[ReconcileRowIn]:
        rows = []
        for rec in csv.DictReader(io.StringIO(text)):
            low = {k.strip().lower(): (v or "").strip() for k, v in rec.items() if k}
            amt = low.get("amount_paise") or ""
            if not amt and low.get("amount"):
                amt = str(int(round(float(low["amount"].replace(",", "")) * 100)))
            if not amt:
                continue
            d = low.get("date") or low.get("statement_date")
            rows.append(
                ReconcileRowIn(
                    utr=low.get("utr") or low.get("reference") or None,
                    amount_paise=int(amt),
                    statement_date=date.fromisoformat(d) if d else None,
                    payer_hint=low.get("narration") or low.get("payer") or None,
                    bank_account=low.get("account") or None,
                )
            )
        return rows

    async def _propose(self, utr: str | None, amount: int | None) -> FeePayment | None:
        if not utr:
            return None
        row: FeePayment | None = (
            await self.db.execute(
                select(FeePayment)
                .where(
                    FeePayment.institution_id == self.inst,
                    FeePayment.utr == utr,
                    FeePayment.status == "initiated",
                    FeePayment.amount_paise == amount,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row

    async def reconcile_list(self, status: str | None) -> list[ReconcileRowOut]:
        q = select(OfflinePaymentReconciliation).where(OfflinePaymentReconciliation.institution_id == self.inst)
        if status:
            q = q.where(OfflinePaymentReconciliation.status == status)
        out = []
        for r in (
            await self.db.execute(q.order_by(OfflinePaymentReconciliation.created_at.desc()).limit(500))
        ).scalars():
            o = ReconcileRowOut.model_validate(r)
            if r.status == "unmatched":
                prop = await self._propose(r.utr, r.amount_paise)
                if prop is not None:
                    o.proposed_payment_id, o.proposed_receipt = prop.id, prop.receipt_number
            out.append(o)
        return out

    async def reconcile_match(
        self, rid: uuid.UUID, payment_id: uuid.UUID | None, invoice_id: uuid.UUID | None
    ) -> ReconcileRowOut:
        row = (
            await self.db.execute(
                select(OfflinePaymentReconciliation)
                .where(OfflinePaymentReconciliation.id == rid, OfflinePaymentReconciliation.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Statement row not found")
        if row.status != "unmatched":
            raise APIError(409, ErrorCode.CONFLICT, f"Row already {row.status}")
        if payment_id:
            p = await self.fees.payment(payment_id, for_update=True)
            if p.status != "initiated":
                raise APIError(409, ErrorCode.CONFLICT, f"Payment is {p.status}")
            inv = await self.fees.get_any(p.invoice_id, for_update=True)
            p.status = "reconciled"
            p.receipt_number = (await self.sequence("fee_receipt_no", "RCP", inv.college_id)).upper()
            p.payment_date = row.statement_date or p.payment_date
            p.collected_by = self.actor_id
            await self.db.flush()
            await self.after_settle(inv, p)
        elif invoice_id:
            inv = await self.fees.get_visible(invoice_id, for_update=True)
            p = await self.record(
                inv, int(row.amount_paise or 0), "neft", status="initiated", utr=row.utr, paid_on=row.statement_date
            )
            p.status = "reconciled"
            p.receipt_number = (await self.sequence("fee_receipt_no", "RCP", inv.college_id)).upper()
            await self.db.flush()
            await self.after_settle(inv, p)
        else:
            raise APIError(422, ErrorCode.VALIDATION, "payment_id or invoice_id is required")
        row.status, row.matched_payment_id, row.matched_by = "matched", p.id, self.actor_id
        await self.db.flush()
        await self._emit("fees.payment_reconciled", {"payment_id": str(p.id), "utr": row.utr}, ENTITY, p.id)
        return ReconcileRowOut.model_validate(row)

    async def reconcile_ignore(self, rid: uuid.UUID) -> ReconcileRowOut:
        row = (
            await self.db.execute(
                select(OfflinePaymentReconciliation)
                .where(OfflinePaymentReconciliation.id == rid, OfflinePaymentReconciliation.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Statement row not found")
        row.status, row.matched_by = "ignored", self.actor_id
        await self.db.flush()
        return ReconcileRowOut.model_validate(row)

    async def bounce(self, pid: uuid.UUID, body: BounceRequest) -> FeePaymentOut:
        p = await self.fees.payment(pid, for_update=True)
        if p.payment_mode not in ("cheque", "dd") or p.status not in SETTLED_PAYMENT:
            raise rule("Only a settled cheque / DD payment can bounce", "NOT_BOUNCEABLE")
        inv = await self.fees.get_any(p.invoice_id, for_update=True)
        p.status, p.cancel_reason, p.cancelled_at, p.cancelled_by = "bounced", body.reason, now_utc(), self.actor_id
        await self.db.flush()
        if body.bank_charges_paise:
            head = await self.head_by_type("fine")
            self.db.add(
                FeeInvoiceItem(
                    institution_id=self.inst,
                    invoice_id=inv.id,
                    fee_head_id=head.id if head else None,
                    description=f"Cheque bounce charges · {p.receipt_number}",
                    amount_paise=body.bank_charges_paise,
                    due_date=await self.today(),
                )
            )
            await self.db.flush()
        if inv.status == "paid":
            inv.status = "partial"
        await self.recompute(inv)
        await self.day_book_add(p, -1)
        await self._audit(
            "bounce",
            ENTITY,
            p.id,
            {"status": "success"},
            {"status": "bounced", "reason": body.reason, "bank_charges_paise": body.bank_charges_paise},
        )
        await self._emit(
            "fees.payment_bounced",
            {
                "payment_id": str(p.id),
                "invoice_id": str(inv.id),
                "source_type": inv.source_type,
                "source_id": str(inv.source_id) if inv.source_id else None,
            },
            ENTITY,
            p.id,
        )
        from app.services.fees.invoice_service import InvoiceService

        await self._notify(
            "fees.payment_bounced",
            await InvoiceService(self.db, self.principal, self.request, self.inst).payer_user_ids(inv),
            {"receipt_no": p.receipt_number, "amount": rupees(p.amount_paise), "reason": body.reason},
            guardians=True,
        )
        return (await self.payment_outs([p]))[0]

    # ---- 4. receipt cancellation --------------------------------------------------------------------------------------
    async def cancel_request(self, pid: uuid.UUID, reason: str) -> FeePaymentOut:
        p = await self.fees.payment(pid, for_update=True)
        if p.status not in SETTLED_PAYMENT:
            raise rule(f"A {p.status} receipt cannot be cancelled", "NOT_CANCELLABLE")
        if p.cancel_workflow_instance_id is not None:
            inst = (
                await self.db.execute(
                    select(WorkflowInstance).where(WorkflowInstance.id == p.cancel_workflow_instance_id)
                )
            ).scalar_one_or_none()
            if inst is not None and inst.status in ("pending", "escalated"):
                raise APIError(409, ErrorCode.CONFLICT, "A cancellation request is already pending")
        p.cancel_reason = reason
        try:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF_CANCEL,
                entity_type=ENTITY,
                entity_id=p.id,
                started_by=self.actor_id,
                context={},
                title=f"Cancel receipt {p.receipt_number} ({rupees(p.amount_paise)})",
            )
            p.cancel_workflow_instance_id = wf.id
        except APIError:
            await self.apply_cancel(p)  # workflow removed: cancel directly (audited)
        await self.db.flush()
        await self._audit("cancel_request", ENTITY, p.id, None, {"reason": reason})
        return (await self.payment_outs([p]))[0]

    async def apply_cancel(self, p: FeePayment) -> None:
        if p.status not in SETTLED_PAYMENT:
            return
        inv = await self.fees.get_any(p.invoice_id, for_update=True)
        p.status, p.cancelled_at, p.cancelled_by = "cancelled", now_utc(), self.actor_id
        await self.db.flush()
        if inv.status == "paid":
            inv.status = "partial"
        await self.recompute(inv)
        await self.day_book_add(p, -1)
        await self._audit(
            "cancel_receipt",
            ENTITY,
            p.id,
            {"status": "success"},
            {"status": "cancelled", "reason": p.cancel_reason, "balance_paise": inv.balance_paise},
        )
        await self._emit(
            "fees.receipt_cancelled",
            {
                "payment_id": str(p.id),
                "invoice_id": str(inv.id),
                "receipt_no": p.receipt_number,
                "source_type": inv.source_type,
                "source_id": str(inv.source_id) if inv.source_id else None,
            },
            ENTITY,
            p.id,
        )

    async def cancel_queue(self) -> list[FeePaymentOut]:
        rows = (
            (
                await self.db.execute(
                    select(FeePayment)
                    .join(WorkflowInstance, WorkflowInstance.id == FeePayment.cancel_workflow_instance_id)
                    .where(
                        FeePayment.institution_id == self.inst, WorkflowInstance.status.in_(("pending", "escalated"))
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.payment_outs(rows)

    async def decide_cancel(self, pid: uuid.UUID, approve: bool, comment: str | None) -> FeePaymentOut:
        p = await self.fees.payment(pid, for_update=True)
        if p.cancel_workflow_instance_id is None:
            raise APIError(409, ErrorCode.CONFLICT, "No cancellation request")
        await workflow_engine.act(
            self.db,
            instance_id=p.cancel_workflow_instance_id,
            actor=self.principal,
            decision="approve" if approve else "reject",
            comment=comment,
        )
        return (await self.payment_outs([p]))[0]

    # ---- 5. day-book --------------------------------------------------------------------------------------------------
    async def day_book(self, on: date, counter: str | None = None) -> DayBookResponse:
        q = select(DayBookEntry).where(DayBookEntry.institution_id == self.inst, DayBookEntry.entry_date == on)
        if counter:
            q = q.where(DayBookEntry.counter == counter)
        entries = (await self.db.execute(q)).scalars().all()
        users = (
            {
                u.id: u
                for u in (
                    await self.db.execute(
                        select(User).where(User.id.in_([e.collected_by for e in entries if e.collected_by]))
                    )
                ).scalars()
            }
            if entries
            else {}
        )
        by_mode = {
            m: int(s)
            for m, s in (
                await self.db.execute(
                    select(FeePayment.payment_mode, func.sum(FeePayment.amount_paise))
                    .where(
                        FeePayment.institution_id == self.inst,
                        FeePayment.payment_date == on,
                        FeePayment.status.in_(tuple(SETTLED_PAYMENT)),
                        *([FeePayment.counter == counter] if counter else []),
                    )
                    .group_by(FeePayment.payment_mode)
                )
            ).all()
        }
        counts = {
            (c, u): int(n)
            for c, u, n in (
                await self.db.execute(
                    select(FeePayment.counter, FeePayment.collected_by, func.count())
                    .where(
                        FeePayment.institution_id == self.inst,
                        FeePayment.payment_date == on,
                        FeePayment.status.in_(tuple(SETTLED_PAYMENT)),
                    )
                    .group_by(FeePayment.counter, FeePayment.collected_by)
                )
            ).all()
        }
        rows = [
            DayBookRow(
                id=e.id,
                entry_date=e.entry_date,
                counter=e.counter,
                collected_by=e.collected_by,
                collector_name=(users[e.collected_by].display_name or users[e.collected_by].username)
                if e.collected_by in users
                else None,
                cash_paise=e.cash_paise,
                digital_paise=e.digital_paise,
                cheque_paise=e.cheque_paise,
                deposited_paise=e.deposited_paise,
                status=e.status,
                receipts=counts.get((e.counter, e.collected_by), 0),
            )
            for e in entries
        ]
        return DayBookResponse(date=on, rows=rows, by_mode=by_mode, total_paise=sum(by_mode.values()))

    async def close_day(self, body: DayBookClose) -> DayBookResponse:
        q = (
            select(DayBookEntry)
            .where(
                DayBookEntry.institution_id == self.inst,
                DayBookEntry.entry_date == body.date,
                DayBookEntry.status == "open",
            )
            .with_for_update()
        )
        if body.counter:
            q = q.where(DayBookEntry.counter == body.counter)
        if not getattr(self.principal, "is_super_admin", False) and not self.can("fees", "view_all"):
            q = q.where(DayBookEntry.collected_by == self.actor_id)
        rows = (await self.db.execute(q)).scalars().all()
        if not rows:
            raise APIError(409, ErrorCode.CONFLICT, "Nothing open to close for that day")
        for e in rows:
            e.status, e.closed_at, e.remarks = (
                ("deposited" if body.deposited_paise is not None else "closed"),
                now_utc(),
                body.remarks,
            )
            e.deposited_paise = (
                e.cash_paise + e.cheque_paise
                if body.deposited_paise is None
                else body.deposited_paise
                if len(rows) == 1
                else e.cash_paise + e.cheque_paise
            )
        await self.db.flush()
        await self._audit(
            "day_book_close", "day_book", rows[0].id, None, {"date": body.date.isoformat(), "rows": len(rows)}
        )
        return await self.day_book(body.date, body.counter)

    async def day_book_csv(self, date_from: date, date_to: date) -> bytes:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "receipt", "invoice", "mode", "amount", "status", "counter", "reference", "utr"])
        stmt = self.fees.payments_stmt(date_from=date_from, date_to=date_to)
        for p in await self.payment_outs((await self.db.execute(stmt)).scalars().all()):
            w.writerow(
                [
                    p.payment_date,
                    p.receipt_number,
                    p.invoice_number,
                    p.payment_mode,
                    f"{p.amount_paise / 100:.2f}",
                    p.status,
                    p.counter or "",
                    p.reference_no or "",
                    p.utr or "",
                ]
            )
        return buf.getvalue().encode("utf-8-sig")

    async def day_book_close_reminder(self) -> int:
        today = await self.today()
        open_rows = (
            (
                await self.db.execute(
                    select(DayBookEntry.collected_by).where(
                        DayBookEntry.institution_id == self.inst,
                        DayBookEntry.entry_date == today,
                        DayBookEntry.status == "open",
                    )
                )
            )
            .scalars()
            .all()
        )
        ids = [u for u in open_rows if u]
        if ids:
            await self._notify("fees.day_book_open", ids, {"date": today.isoformat()})
        return len(ids)


# ---- workflow hooks ------------------------------------------------------------------------------------------------------
class _Actor:
    def __init__(self, iid: uuid.UUID, uid: uuid.UUID | None):
        self.institution_id, self.id, self.is_super_admin, self.impersonator_id = iid, uid, False, None
        self.scopes = [("institution", None)]
        self.roles: list[str] = []

    def has(self, module: str, action: str) -> bool:
        return True


@workflow_engine.on(WF_CANCEL, "approved")
async def _cancel_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    svc = PaymentService(db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id)
    p = (
        await db.execute(select(FeePayment).where(FeePayment.id == instance.entity_id).with_for_update())
    ).scalar_one_or_none()
    if p is not None:
        await svc.apply_cancel(p)


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    p = (await db.execute(select(FeePayment).where(FeePayment.id == entity_id))).scalar_one_or_none()
    if p is None:
        return None, None
    return (
        f"Cancel receipt {p.receipt_number} · {rupees(p.amount_paise)} — {p.cancel_reason or ''}",
        "/admin/fees/payments",
    )


__all__ = ["PaymentService", "_Actor"]
