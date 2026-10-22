"""Shared plumbing of the Phase 12 services — built on the Phase 07 ``StudentServiceBase`` (tenant, audit, outbox,
notifications, institution-local ``today``, settings, terms).

**Invoice arithmetic** (all paise)::

    total   = Σ item.amount for non-fine heads          tax  = Σ item.tax_paise
    fine    = Σ item.amount for ``fine`` heads (late fees, bounce charges)
    balance = total − discount + tax + fine − paid      paid = Σ payments in (success, reconciled)

Status: ``cancelled`` / ``refunded`` are terminal; otherwise ``paid`` when balance ≤ 0, ``overdue`` when the due date
(institution-local) has passed, ``partial`` when something was paid, else ``pending``.
"""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.fees import SETTLED_PAYMENT
from app.models.admissions import Applicant
from app.models.fees import FeeHead, FeeInvoice, FeeInvoiceItem, FeePayment
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.fee_repository import FeeRepository
from app.schemas.fees import FeePaymentOut, InvoiceItemOut, InvoiceResponse
from app.services.students.common import StudentServiceBase, now_utc  # noqa: F401  (re-exported)

SOURCE_LINKS = {
    "condonation": "/admin/attendance/condonations",
    "course_registration": "/admin/registration",
    "registration": "/admin/registration",
    "application_fee": "/admin/admissions/applicants/{payer}",
    "admission_fee": "/admin/admissions/applicants/{payer}",
    "structure": "/admin/fees/structures",
}


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def student_name(s: Student | None) -> str | None:
    if s is None:
        return None
    return " ".join(p for p in (s.first_name, s.last_name) if p)


class FeesBase(StudentServiceBase):
    audit_module = "fees"

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.fees = FeeRepository(self.db, self.principal, self.inst)
        self._heads: dict[str, FeeHead] | None = None

    # ---- lookups ----------------------------------------------------------------------------------------------------
    async def heads_by_code(self) -> dict[str, FeeHead]:
        if self._heads is None:
            rows = (await self.db.execute(select(FeeHead).where(FeeHead.institution_id == self.inst))).scalars()
            self._heads = {h.code: h for h in rows}
        return self._heads

    async def head_by_type(self, head_type: str) -> FeeHead | None:
        for h in (await self.heads_by_code()).values():
            if h.head_type == head_type and h.is_active:
                return h
        return None

    async def fine_head_ids(self) -> set[uuid.UUID]:
        return {h.id for h in (await self.heads_by_code()).values() if h.head_type == "fine"}

    async def enrolment(self, enrollment_id: uuid.UUID) -> tuple[StudentProgramEnrollment, Student]:
        row = (
            await self.db.execute(
                select(StudentProgramEnrollment, Student)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .where(
                    StudentProgramEnrollment.id == enrollment_id, StudentProgramEnrollment.institution_id == self.inst
                )
            )
        ).first()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Enrolment not found")
        return row[0], row[1]

    async def my_enrollment(self, enrollment_id: uuid.UUID | None = None) -> tuple[StudentProgramEnrollment, Student]:
        """The caller's own (or consented ward's) active enrolment — 404 for anyone else's."""
        from app.repositories.fee_scope import own_enrollment_ids

        q = (
            select(StudentProgramEnrollment, Student)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(
                StudentProgramEnrollment.deleted_at.is_(None),
                StudentProgramEnrollment.id.in_(own_enrollment_ids(self.principal, advisees=False)),
            )
            .order_by(StudentProgramEnrollment.admission_date.desc())
        )
        if enrollment_id is not None:
            q = q.where(StudentProgramEnrollment.id == enrollment_id)
        else:
            q = q.where(Student.user_id == self.actor_id)
        row = (await self.db.execute(q)).first()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "No enrolment found")
        return row[0], row[1]

    async def sequence(self, scope_key: str, fallback: str, college_id: uuid.UUID | None = None) -> str:
        from app.services.sequence_service import SequenceService

        try:
            return (
                await SequenceService(self.db, self.principal, self.request, self.inst).next(scope_key, college_id)
            ).rendered[:40]
        except APIError:
            n = (await self.db.execute(select(func.count()).select_from(FeeInvoice))).scalar_one()
            return f"{fallback}/{(await self.today()).year}/{uuid.uuid4().hex[:6].upper()}{n}"[:40]

    # ---- arithmetic -------------------------------------------------------------------------------------------------
    async def recompute(self, inv: FeeInvoice, *, today: date | None = None) -> FeeInvoice:
        fines = await self.fine_head_ids()
        items = (
            (await self.db.execute(select(FeeInvoiceItem).where(FeeInvoiceItem.invoice_id == inv.id))).scalars().all()
        )
        inv.total_paise = sum(i.amount_paise for i in items if i.fee_head_id not in fines)
        inv.fine_paise = sum(i.amount_paise for i in items if i.fee_head_id in fines)
        inv.tax_paise = sum(i.tax_paise for i in items)
        paid = (
            await self.db.execute(
                select(func.coalesce(func.sum(FeePayment.amount_paise), 0)).where(
                    FeePayment.invoice_id == inv.id, FeePayment.status.in_(tuple(SETTLED_PAYMENT))
                )
            )
        ).scalar_one()
        inv.paid_paise = int(paid)
        inv.balance_paise = inv.total_paise - inv.discount_paise + inv.tax_paise + inv.fine_paise - inv.paid_paise
        if any(i.due_date for i in items):
            inv.due_date = self._next_due(items, inv.paid_paise) or inv.due_date
        if inv.status not in ("cancelled", "refunded"):
            today = today or await self.today()
            if inv.balance_paise <= 0:
                inv.status = "paid"
            elif inv.due_date and inv.due_date < today:
                inv.status = "overdue"
            elif inv.paid_paise > 0:
                inv.status = "partial"
            else:
                inv.status = "pending"
        await self.db.flush()
        return inv

    @staticmethod
    def _next_due(items: Sequence[FeeInvoiceItem], paid: int) -> date | None:
        """Due date of the first instalment the payments have not covered yet (oldest first)."""
        left = paid
        for it in sorted(items, key=lambda i: (i.due_date or date.max, i.instalment_no or 0)):
            need = it.amount_paise + it.tax_paise
            if left >= need:
                left -= need
                continue
            return it.due_date
        return None

    # ---- responses --------------------------------------------------------------------------------------------------
    async def payer_names(self, invoices: Sequence[FeeInvoice]) -> dict[uuid.UUID, tuple[str | None, str | None]]:
        out: dict[uuid.UUID, tuple[str | None, str | None]] = {}
        enrol_ids = [i.student_program_enrollment_id for i in invoices if i.student_program_enrollment_id]
        if enrol_ids:
            for eid, s in (
                await self.db.execute(
                    select(StudentProgramEnrollment.id, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(StudentProgramEnrollment.id.in_(enrol_ids))
                )
            ).all():
                out[eid] = (student_name(s), s.registration_number)
        app_ids = [i.payer_id for i in invoices if i.payer_type == "applicant"]
        if app_ids:
            for a in (await self.db.execute(select(Applicant).where(Applicant.id.in_(app_ids)))).scalars():
                out[a.id] = (" ".join(p for p in (a.first_name, a.last_name) if p), a.application_number)
        return out

    async def payment_outs(self, rows: Sequence[FeePayment]) -> list[FeePaymentOut]:
        inv_ids = list({r.invoice_id for r in rows})
        invs = (
            {i.id: i for i in (await self.db.execute(select(FeeInvoice).where(FeeInvoice.id.in_(inv_ids)))).scalars()}
            if inv_ids
            else {}
        )
        names = await self.payer_names(list(invs.values()))
        out = []
        for r in rows:
            o = FeePaymentOut.model_validate(r)
            inv = invs.get(r.invoice_id)
            if inv is not None:
                o.invoice_number = inv.invoice_number
                key = inv.student_program_enrollment_id or inv.payer_id
                o.payer_name = names.get(key, (None, None))[0]
            out.append(o)
        return out

    async def invoice_outs(self, rows: Sequence[FeeInvoice], *, detail: bool = False) -> list[InvoiceResponse]:
        names = await self.payer_names(rows)
        ids = [r.id for r in rows]
        items: dict[uuid.UUID, list[FeeInvoiceItem]] = {i: [] for i in ids}
        pays: dict[uuid.UUID, list[FeePayment]] = {i: [] for i in ids}
        if ids:
            for it in (
                await self.db.execute(
                    select(FeeInvoiceItem)
                    .where(FeeInvoiceItem.invoice_id.in_(ids))
                    .order_by(FeeInvoiceItem.instalment_no.nulls_last(), FeeInvoiceItem.description)
                )
            ).scalars():
                items[it.invoice_id].append(it)
            if detail:
                for p in (
                    await self.db.execute(
                        select(FeePayment).where(FeePayment.invoice_id.in_(ids)).order_by(FeePayment.created_at)
                    )
                ).scalars():
                    pays[p.invoice_id].append(p)
        out = []
        for r in rows:
            o = InvoiceResponse.model_validate(r)
            name = names.get(r.student_program_enrollment_id or r.payer_id, (None, None))
            o.payer_name, o.registration_number = name
            link = SOURCE_LINKS.get(r.source_type or "")
            o.source_link = link.replace("{payer}", str(r.payer_id)) if link else None
            o.items = [InvoiceItemOut.model_validate(i) for i in items[r.id]]
            if detail:
                o.payments = await self.payment_outs(pays[r.id])
            out.append(o)
        return out
