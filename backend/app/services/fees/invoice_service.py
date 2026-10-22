"""Invoices — Prompts/12 §12.6 ``invoice_service``.

1. ``create_invoice(payer, source_type, source_id, items, due_date, term)`` — the universal linkage API, idempotent on
   ``(source_type, source_id)`` unless ``allow_multiple``; GST per taxable head when ``fees.gst_invoicing``; number from
   the ``fee_invoice_no`` sequence; emits ``fees.invoice_created`` (+ notification).
2. ``from_structure`` — term invoice of an assigned structure (instalments with due dates from ``due_date`` or
   ``term start + due_offset_days``, per-credit arrear fee, approved discounts).
3. Discounts recomputed on assignment (percentage on the heads they apply to, or fixed).
4. Beat bodies: ``late_fees`` (``fine_configurations(applies_to='late_fee')`` after grace), ``due_reminders``
   (D-7 / D-1 / D+7), ``overdue_holds`` (Phase 07 ``HoldService.place_system`` hold type ``fee`` after
   ``fees.hold_on_overdue_days``; released on payment).
5. Cancel only with zero settled payments.
6. ``backfill_stubs`` — the "fee_stub_queue" of earlier phases (Phase 09 / 11 audit ``fee_order`` rows, Phase 08
   ``applicants.documents._payments``) → real invoices with ``source_type/source_id`` and the FK columns set.
"""

import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select, update

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.enums.fees import OPEN_INVOICE
from app.models.academic import AcademicTerm
from app.models.fees import (
    FeeDiscount,
    FeeInvoice,
    FeeInvoiceItem,
    FeeStructure,
    FeeStructureItem,
    FineConfiguration,
    StudentDiscountAssignment,
)
from app.models.students import StudentProgramEnrollment, StudentTermRecord
from app.schemas.fees import DuesResponse, InvoiceCreate, InvoiceItemIn, InvoiceResponse
from app.services.fees.common import FeesBase, now_utc, rule, rupees
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

ENTITY = "fee_invoice"


def pct_of(amount: int, pct: Decimal | float) -> int:
    return int((Decimal(amount) * Decimal(str(pct)) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class InvoiceService(FeesBase):
    # ---- 1. universal linkage ---------------------------------------------------------------------------------------
    async def create_invoice(self, body: InvoiceCreate, *, notify: bool = True) -> FeeInvoice:
        if body.source_type and body.source_id and not body.allow_multiple:
            existing = await self.fees.by_source(body.source_type, body.source_id)
            if existing is not None:
                return existing
        if not body.items:
            raise APIError(422, ErrorCode.VALIDATION, "An invoice needs at least one item", {"field": "items"})
        enrol = None
        payer_id = body.payer_id
        college_id = None
        if body.enrollment_id:
            enrol, _ = await self.enrolment(body.enrollment_id)
            payer_id = payer_id or enrol.student_id
            college_id = enrol.college_id
        if payer_id is None:
            raise APIError(422, ErrorCode.VALIDATION, "payer_id or enrollment_id is required")
        heads = await self.heads_by_code()
        gst_on = await is_enabled(self.inst, "fees.gst_invoicing")
        gstin = await self.setting("fees", "gstin") if gst_on else None
        term = None
        if body.term_id:
            term = (
                await self.db.execute(select(AcademicTerm).where(AcademicTerm.id == body.term_id))
            ).scalar_one_or_none()
        inv = FeeInvoice(
            institution_id=self.inst,
            college_id=college_id,
            payer_type=body.payer_type,
            payer_id=payer_id,
            student_program_enrollment_id=enrol.id if enrol else None,
            invoice_number=(await self.sequence("fee_invoice_no", "INV", college_id)).upper(),
            academic_year_id=term.academic_year_id if term else None,
            term_id=term.id if term else None,
            source_type=body.source_type,
            source_id=body.source_id,
            description=(body.description or (body.items[0].description if body.items else None) or "")[:255],
            due_date=body.due_date,
            status="pending",
            gst_number=str(gstin)[:20] if gstin else None,
            created_by=self.actor_id,
        )
        self.db.add(inv)
        await self.db.flush()
        any_tax = False
        for it in body.items:
            head = heads.get(it.head_code) if it.head_code else None
            head_id = it.fee_head_id or (head.id if head else None)
            if head is None and head_id is not None:
                head = next((h for h in heads.values() if h.id == head_id), None)
            tax = 0
            if gst_on and head is not None and head.is_taxable and head.gst_rate:
                tax = pct_of(it.amount_paise, head.gst_rate)
                any_tax = True
            self.db.add(
                FeeInvoiceItem(
                    institution_id=self.inst,
                    invoice_id=inv.id,
                    fee_head_id=head_id,
                    description=it.description[:200],
                    amount_paise=it.amount_paise,
                    tax_paise=tax,
                    instalment_no=it.instalment_no,
                    due_date=it.due_date or body.due_date,
                )
            )
        if not any_tax:
            inv.gst_number = None
        await self.db.flush()
        if enrol is not None:
            inv.discount_paise = await self.discount_for(inv, enrol.id)
        await self.recompute(inv)
        await self._audit(
            "create",
            ENTITY,
            inv.id,
            None,
            {
                "invoice_number": inv.invoice_number,
                "source_type": inv.source_type,
                "source_id": str(inv.source_id) if inv.source_id else None,
                "total_paise": inv.total_paise,
            },
        )
        await self._emit(
            "fees.invoice_created",
            {
                "invoice_id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "source_type": inv.source_type,
                "source_id": str(inv.source_id) if inv.source_id else None,
                "payer_type": inv.payer_type,
                "payer_id": str(inv.payer_id),
                "balance_paise": inv.balance_paise,
            },
            ENTITY,
            inv.id,
        )
        await self._link_back(inv)
        if notify:
            await self._notify(
                "fees.invoice_created",
                await self.payer_user_ids(inv),
                {
                    "invoice_no": inv.invoice_number,
                    "amount": rupees(inv.balance_paise),
                    "due_date": inv.due_date.isoformat() if inv.due_date else "—",
                },
                guardians=inv.payer_type == "student",
            )
        return inv

    async def _link_back(self, inv: FeeInvoice) -> None:
        """Set the FK columns earlier phases left NULL (registration / condonation / applicant / seat allotment)."""
        if not inv.source_id:
            return
        from app.models.admissions import Applicant, SeatAllotment
        from app.models.attendance import AttendanceCondonation
        from app.models.registration import CourseRegistration

        st, sid = inv.source_type, inv.source_id
        if st in ("course_registration", "registration"):
            await self.db.execute(
                update(CourseRegistration).where(CourseRegistration.id == sid).values(fee_invoice_id=inv.id)
            )
        elif st == "condonation":
            await self.db.execute(
                update(AttendanceCondonation).where(AttendanceCondonation.id == sid).values(fee_invoice_id=inv.id)
            )
        elif st == "application_fee":
            await self.db.execute(
                update(Applicant).where(Applicant.id == sid).values(application_fee_invoice_id=inv.id)
            )
        elif st == "admission_fee":
            await self.db.execute(
                update(SeatAllotment)
                .where(SeatAllotment.applicant_id == sid, SeatAllotment.fee_invoice_id.is_(None))
                .values(fee_invoice_id=inv.id)
            )

    async def payer_user_ids(self, inv: FeeInvoice) -> list[uuid.UUID | None]:
        from app.models.admissions import Applicant
        from app.models.students import Student

        if inv.payer_type == "student":
            uid = (
                await self.db.execute(select(Student.user_id).where(Student.id == inv.payer_id))
            ).scalar_one_or_none()
            return [uid]
        if inv.payer_type == "applicant":
            uid = (
                await self.db.execute(select(Applicant.user_id).where(Applicant.id == inv.payer_id))
            ).scalar_one_or_none()
            return [uid]
        return []

    async def link(
        self,
        source_type: str,
        source_id: uuid.UUID,
        amount_paise: int,
        enrollment_id: uuid.UUID | None,
        description: str | None = None,
        head_type: str | None = None,
    ) -> FeeInvoice:
        """Shorthand for one-item linkage invoices (condonation, registration, dev fixture)."""
        head = await self.head_by_type(head_type or source_type) or await self.head_by_type("other")
        return await self.create_invoice(
            InvoiceCreate(
                enrollment_id=enrollment_id,
                source_type=source_type,
                source_id=source_id,
                description=description or source_type.replace("_", " ").title(),
                items=[
                    InvoiceItemIn(
                        description=description or source_type.replace("_", " ").title(),
                        amount_paise=amount_paise,
                        fee_head_id=head.id if head else None,
                    )
                ],
                due_date=(await self.today())
                + timedelta(days=int(await self.setting("fees", "linkage_due_days") or 7)),
            )
        )

    # ---- 2. from a structure ---------------------------------------------------------------------------------------
    async def term_number_of(self, enrol: StudentProgramEnrollment, term: AcademicTerm | None) -> int | None:
        q = select(StudentTermRecord.term_number).where(StudentTermRecord.student_program_enrollment_id == enrol.id)
        if term is not None:
            n = (await self.db.execute(q.where(StudentTermRecord.term_id == term.id))).scalar_one_or_none()
            if n:
                return int(n)
        n = (
            await self.db.execute(
                select(func.max(StudentTermRecord.term_number)).where(
                    StudentTermRecord.student_program_enrollment_id == enrol.id
                )
            )
        ).scalar_one_or_none()
        return int(n) if n else enrol.entry_term_number

    async def from_structure(
        self, s: FeeStructure, enrol: StudentProgramEnrollment, term: AcademicTerm | None, *, arrear_credits: float = 0
    ) -> FeeInvoice:
        items = (
            (
                await self.db.execute(
                    select(FeeStructureItem)
                    .where(FeeStructureItem.structure_id == s.id)
                    .order_by(FeeStructureItem.instalment_no)
                )
            )
            .scalars()
            .all()
        )
        heads = {h.id: h for h in (await self.heads_by_code()).values()}
        base = term.start_date if term else await self.today()
        lines = []
        for it in items:
            if it.is_optional:
                continue
            due = it.due_date or (base + timedelta(days=int(it.due_offset_days or 0)))
            head = heads.get(it.fee_head_id)
            label = f"{head.name if head else 'Fee'}" + (
                f" · instalment {it.instalment_no}"
                if it.instalment_no > 1 or len({i.instalment_no for i in items}) > 1
                else ""
            )
            lines.append(
                InvoiceItemIn(
                    description=label,
                    amount_paise=it.amount_paise,
                    fee_head_id=it.fee_head_id,
                    instalment_no=it.instalment_no,
                    due_date=due,
                )
            )
        if arrear_credits and s.per_credit_paise:
            tuition = await self.head_by_type("tuition")
            lines.append(
                InvoiceItemIn(
                    description=f"Arrear fee · {arrear_credits:g} credits",
                    amount_paise=int(arrear_credits * s.per_credit_paise),
                    fee_head_id=tuition.id if tuition else None,
                    due_date=base,
                )
            )
        if not lines:
            raise rule("The structure has no mandatory items", "EMPTY_STRUCTURE", 422)
        return await self.create_invoice(
            InvoiceCreate(
                enrollment_id=enrol.id,
                source_type="structure",
                source_id=s.id,
                description=f"{s.name}" + (f" · {term.name}" if term else ""),
                items=lines,
                due_date=min(i.due_date for i in lines if i.due_date),
                term_id=term.id if term else None,
                allow_multiple=True,
            )
        )

    async def structure_invoice_exists(self, s: FeeStructure, enrol_id: uuid.UUID, term_id: uuid.UUID | None) -> bool:
        q = select(FeeInvoice.id).where(
            FeeInvoice.institution_id == self.inst,
            FeeInvoice.source_type == "structure",
            FeeInvoice.source_id == s.id,
            FeeInvoice.student_program_enrollment_id == enrol_id,
            FeeInvoice.status != "cancelled",
        )
        if term_id:
            q = q.where(FeeInvoice.term_id == term_id)
        return (await self.db.execute(q.limit(1))).first() is not None

    # ---- 3. discounts -----------------------------------------------------------------------------------------------
    async def discount_for(self, inv: FeeInvoice, enrol_id: uuid.UUID) -> int:
        rows = (
            (
                await self.db.execute(
                    select(FeeDiscount)
                    .join(StudentDiscountAssignment, StudentDiscountAssignment.discount_id == FeeDiscount.id)
                    .where(
                        StudentDiscountAssignment.student_program_enrollment_id == enrol_id,
                        StudentDiscountAssignment.status == "approved",
                        FeeDiscount.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return 0
        items = (
            (await self.db.execute(select(FeeInvoiceItem).where(FeeInvoiceItem.invoice_id == inv.id))).scalars().all()
        )
        heads = {h.id: h for h in (await self.heads_by_code()).values()}
        total = 0
        for d in rows:
            wanted = set(d.applies_to_heads or [])
            base = sum(
                i.amount_paise
                for i in items
                if i.fee_head_id in heads
                and heads[i.fee_head_id].head_type != "fine"
                and (not wanted or heads[i.fee_head_id].code in wanted or heads[i.fee_head_id].head_type in wanted)
            )
            total += pct_of(base, d.value) if d.discount_type == "percentage" else min(base, int(d.value * 100))
        return total

    async def reapply_discounts(self, enrol_id: uuid.UUID) -> int:
        n = 0
        for inv in (
            await self.db.execute(
                select(FeeInvoice)
                .where(FeeInvoice.student_program_enrollment_id == enrol_id, FeeInvoice.status.in_(tuple(OPEN_INVOICE)))
                .with_for_update()
            )
        ).scalars():
            new = await self.discount_for(inv, enrol_id)
            if new != inv.discount_paise:
                inv.discount_paise = new
                await self.recompute(inv)
                n += 1
        return n

    # ---- reads ------------------------------------------------------------------------------------------------------
    async def list_page(
        self,
        params: PageParams,
        scope: str | None,
        *,
        payer_type: str | None = None,
        status: str | None = None,
        overdue: bool | None = None,
        batch_id: uuid.UUID | None = None,
        q: str | None = None,
        source_type: str | None = None,
    ) -> tuple[list[InvoiceResponse], PaginationMeta, VisibilityMeta]:
        from app.repositories.fee_scope import visibility

        stmt = self.fees.scoped(scope)
        if payer_type:
            stmt = stmt.where(FeeInvoice.payer_type == payer_type)
        if status:
            stmt = stmt.where(FeeInvoice.status == status)
        if source_type:
            stmt = stmt.where(FeeInvoice.source_type == source_type)
        if overdue:
            stmt = stmt.where(FeeInvoice.status.in_(tuple(OPEN_INVOICE)), FeeInvoice.due_date < await self.today())
        if batch_id:
            stmt = stmt.where(
                FeeInvoice.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.batch_id == batch_id)
                )
            )
        if q:
            from sqlalchemy import or_

            from app.models.students import Student

            stmt = stmt.where(
                or_(
                    FeeInvoice.invoice_number.ilike(f"%{q}%"),
                    FeeInvoice.student_program_enrollment_id.in_(
                        select(StudentProgramEnrollment.id)
                        .join(Student, Student.id == StudentProgramEnrollment.student_id)
                        .where(or_(Student.registration_number.ilike(f"%{q}%"), Student.first_name.ilike(f"%{q}%")))
                    ),
                )
            )
        params.sort = params.sort or "-created_at"
        rows, page = await self.fees.paginate(stmt, params)
        return await self.invoice_outs(rows), page, visibility(self.principal)

    async def get(self, invoice_id: uuid.UUID) -> InvoiceResponse:
        return (await self.invoice_outs([await self.fees.get_visible(invoice_id)], detail=True))[0]

    async def dues_for(self, enrol_id: uuid.UUID) -> DuesResponse:
        enrol, student = await self.enrolment(enrol_id)
        rows = (
            (
                await self.db.execute(
                    select(FeeInvoice)
                    .where(
                        FeeInvoice.student_program_enrollment_id == enrol_id, FeeInvoice.status.notin_(("cancelled",))
                    )
                    .order_by(FeeInvoice.due_date.nulls_last(), FeeInvoice.created_at)
                )
            )
            .scalars()
            .all()
        )
        today = await self.today()
        outs = await self.invoice_outs(rows, detail=True)
        open_rows = [r for r in rows if r.status in OPEN_INVOICE]
        dues = [r.due_date for r in open_rows if r.due_date]
        from app.services.fees.common import student_name

        return DuesResponse(
            invoices=outs,
            total_due=sum(max(0, r.balance_paise) for r in open_rows),
            overdue=sum(max(0, r.balance_paise) for r in open_rows if r.due_date and r.due_date < today),
            next_due=min(dues) if dues else None,
            student_name=student_name(student),
            enrollment_id=enrol.id,
        )

    async def my_dues(self, enrollment_id: uuid.UUID | None = None) -> DuesResponse:
        enrol, _ = await self.my_enrollment(enrollment_id)
        return await self.dues_for(enrol.id)

    async def ward_dues(self, student_id: uuid.UUID) -> DuesResponse:
        from app.repositories.fee_scope import ward_enrollment_ids

        eid = (
            await self.db.execute(
                select(StudentProgramEnrollment.id)
                .where(
                    StudentProgramEnrollment.student_id == student_id,
                    StudentProgramEnrollment.id.in_(ward_enrollment_ids(self.principal)),
                    StudentProgramEnrollment.deleted_at.is_(None),
                )
                .order_by(StudentProgramEnrollment.admission_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if eid is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Ward not found")
        return await self.dues_for(eid)

    async def my_invoices(self) -> list[InvoiceResponse]:
        rows = (
            (await self.db.execute(self.fees.scoped("self").order_by(FeeInvoice.created_at.desc()).limit(200)))
            .scalars()
            .all()
        )
        return await self.invoice_outs(rows, detail=True)

    # ---- 5. cancel --------------------------------------------------------------------------------------------------
    async def cancel(self, invoice_id: uuid.UUID, reason: str) -> InvoiceResponse:
        inv = await self.fees.get_visible(invoice_id, for_update=True)
        await self.recompute(inv)
        if inv.status in ("cancelled", "refunded"):
            raise APIError(409, ErrorCode.CONFLICT, f"The invoice is already {inv.status}")
        if inv.paid_paise > 0:
            raise rule(
                "An invoice with payments cannot be cancelled — cancel the receipts or refund first", "HAS_PAYMENTS"
            )
        inv.status, inv.cancelled_at, inv.cancelled_reason = "cancelled", now_utc(), reason
        await self.db.flush()
        await self._audit("cancel", ENTITY, inv.id, {"status": "pending"}, {"status": "cancelled", "reason": reason})
        await self._emit(
            "fees.invoice_cancelled",
            {
                "invoice_id": str(inv.id),
                "source_type": inv.source_type,
                "source_id": str(inv.source_id) if inv.source_id else None,
            },
            ENTITY,
            inv.id,
        )
        return await self.get(inv.id)

    # ---- 4. Beat bodies ---------------------------------------------------------------------------------------------
    async def late_fees(self) -> int:
        cfg = (
            await self.db.execute(
                select(FineConfiguration)
                .where(
                    FineConfiguration.institution_id == self.inst,
                    FineConfiguration.applies_to == "late_fee",
                    FineConfiguration.is_active.is_(True),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if cfg is None:
            return 0
        fine_head = await self.head_by_type("fine")
        today = await self.today()
        n = 0
        rows = (
            (
                await self.db.execute(
                    select(FeeInvoice)
                    .where(
                        FeeInvoice.institution_id == self.inst,
                        FeeInvoice.status.in_(tuple(OPEN_INVOICE)),
                        FeeInvoice.due_date.is_not(None),
                        FeeInvoice.due_date < today - timedelta(days=cfg.grace_days),
                        FeeInvoice.source_type == "structure",
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for inv in rows:
            assert inv.due_date is not None
            days = (today - inv.due_date).days - cfg.grace_days
            if cfg.calc_type == "per_day":
                want = days * int(cfg.amount_paise or 0)
            elif cfg.calc_type == "slab":
                want = 0
                for slab in cfg.slabs or []:
                    if days >= int(slab.get("from_day", 0)):
                        want = int(slab.get("amount_paise", 0))
            else:
                want = int(cfg.amount_paise or 0)
            if cfg.max_paise:
                want = min(want, cfg.max_paise)
            existing = (
                await self.db.execute(
                    select(FeeInvoiceItem).where(
                        FeeInvoiceItem.invoice_id == inv.id, FeeInvoiceItem.description.like("Late fee%")
                    )
                )
            ).scalar_one_or_none()
            current = existing.amount_paise if existing else 0
            if want <= current:
                continue
            if existing:
                existing.amount_paise = want
            else:
                self.db.add(
                    FeeInvoiceItem(
                        institution_id=self.inst,
                        invoice_id=inv.id,
                        fee_head_id=fine_head.id if fine_head else None,
                        description="Late fee",
                        amount_paise=want,
                        due_date=today,
                    )
                )
            await self.db.flush()
            await self.recompute(inv, today=today)
            await self._audit("late_fee", ENTITY, inv.id, {"fine_paise": current}, {"fine_paise": want, "days": days})
            await self._emit("fees.late_fee_applied", {"invoice_id": str(inv.id), "fine_paise": want}, ENTITY, inv.id)
            n += 1
        # status sweep (pending → overdue) for invoices without a late-fee rule
        for inv in (
            await self.db.execute(
                select(FeeInvoice).where(
                    FeeInvoice.institution_id == self.inst,
                    FeeInvoice.status.in_(("pending", "partial")),
                    FeeInvoice.due_date < today,
                )
            )
        ).scalars():
            await self.recompute(inv, today=today)
        return n

    async def due_reminders(self) -> int:
        today = await self.today()
        offsets = await self.setting("fees", "reminder_days") or [7, 1, -7]
        n = 0
        for off in offsets:
            target = today + timedelta(days=int(off))
            for inv in (
                await self.db.execute(
                    select(FeeInvoice).where(
                        FeeInvoice.institution_id == self.inst,
                        FeeInvoice.status.in_(tuple(OPEN_INVOICE)),
                        FeeInvoice.due_date == target,
                    )
                )
            ).scalars():
                await self._notify(
                    "fees.due_reminder",
                    await self.payer_user_ids(inv),
                    {"amount": rupees(inv.balance_paise), "due_date": target.isoformat()},
                    guardians=True,
                )
                await self._emit("fees.due_reminder", {"invoice_id": str(inv.id), "offset": int(off)}, ENTITY, inv.id)
                n += 1
        return n

    async def overdue_holds(self) -> int:
        from app.services.hold_service import HoldService

        days = int(await self.setting("fees", "hold_on_overdue_days") or 0)
        if days <= 0:
            return 0
        today = await self.today()
        hs = HoldService(self.db, self.principal, self.request, self.inst)
        n = 0
        rows = (
            await self.db.execute(
                select(FeeInvoice, StudentProgramEnrollment)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.id == FeeInvoice.student_program_enrollment_id)
                .where(
                    FeeInvoice.institution_id == self.inst,
                    FeeInvoice.status.in_(tuple(OPEN_INVOICE)),
                    FeeInvoice.due_date <= today - timedelta(days=days),
                )
            )
        ).all()
        # Phase 07 has no ``fee`` hold type and its gates match hold_type == gate: the overdue hold is placed per gate
        # it must block (setting ``fees.overdue_hold_types``, default registration + exam), source ``fee_invoice``
        types = await self.setting("fees", "overdue_hold_types") or ["registration", "exam"]
        for inv, enrol in rows:
            for ht in types:
                await hs.place_system(
                    enrol,
                    str(ht),
                    f"Fee overdue: {inv.invoice_number} ({rupees(inv.balance_paise)})",
                    "fee_invoice",
                    inv.id,
                )
                n += 1
        return n

    async def release_holds(self, inv: FeeInvoice) -> int:
        """Release the ``fee`` hold of a settled invoice (system release, audited)."""
        from app.models.students import StudentHold
        from app.services.hold_service import SYSTEM_USER

        n = 0
        for h in (
            await self.db.execute(
                select(StudentHold)
                .where(
                    StudentHold.source_type == "fee_invoice",
                    StudentHold.source_id == inv.id,
                    StudentHold.released_at.is_(None),
                )
                .with_for_update()
            )
        ).scalars():
            h.released_at = now_utc()
            h.released_by = self.actor_id or SYSTEM_USER
            n += 1
            await self._audit(
                "release_hold",
                "student_hold",
                h.id,
                None,
                {"reason": f"invoice {inv.invoice_number} paid"},
                module="students",
            )
        await self.db.flush()
        return n

    # ---- 6. stub back-fill ------------------------------------------------------------------------------------------
    async def backfill_stubs(self) -> dict[str, int]:
        from app.models.admissions import Applicant
        from app.models.platform import AuditLog

        out = {"registration": 0, "condonation": 0, "applicant": 0, "skipped": 0}
        rows = (
            await self.db.execute(
                select(AuditLog.record_type, AuditLog.record_id, AuditLog.new_values).where(
                    AuditLog.institution_id == self.inst,
                    AuditLog.action == "fee_order",
                    AuditLog.record_type.in_(("course_registration", "attendance_condonation")),
                )
            )
        ).all()
        for record_type, record_id, values in rows:
            amount = int((values or {}).get("amount_paise") or (values or {}).get("total_paise") or 0)
            if amount <= 0 or record_id is None:
                out["skipped"] += 1
                continue
            if record_type == "course_registration":
                from app.models.registration import CourseRegistration

                reg = (
                    await self.db.execute(select(CourseRegistration).where(CourseRegistration.id == record_id))
                ).scalar_one_or_none()
                if reg is None:
                    continue
                inv = await self.link(
                    "course_registration",
                    reg.id,
                    amount,
                    reg.student_program_enrollment_id,
                    "Registration fee",
                    "tuition",
                )
                out["registration"] += 1
            else:
                from app.models.attendance import AttendanceCondonation

                c = (
                    await self.db.execute(select(AttendanceCondonation).where(AttendanceCondonation.id == record_id))
                ).scalar_one_or_none()
                if c is None:
                    continue
                inv = await self.link(
                    "condonation", c.id, amount, c.student_program_enrollment_id, "Condonation fee", "condonation"
                )
                out["condonation"] += 1
            if (values or {}).get("status") == "paid" or await self._stub_paid(record_type, record_id):
                await self._settle_stub(inv)
        for a in (await self.db.execute(select(Applicant).where(Applicant.institution_id == self.inst))).scalars():
            for purpose, pay in ((a.documents or {}).get("_payments") or {}).items():
                amount = int(pay.get("amount_paise") or 0)
                if amount <= 0:
                    continue
                head = await self.head_by_type("admission")
                inv = await self.create_invoice(
                    InvoiceCreate(
                        payer_type="applicant",
                        payer_id=a.id,
                        source_type=f"{purpose}_fee",
                        source_id=a.id,
                        description=f"{purpose.title()} fee · {a.application_number}",
                        items=[
                            InvoiceItemIn(
                                description=f"{purpose.title()} fee",
                                amount_paise=amount,
                                fee_head_id=head.id if head else None,
                            )
                        ],
                        due_date=await self.today(),
                    ),
                    notify=False,
                )
                if pay.get("status") == "paid":
                    await self._settle_stub(inv)
                out["applicant"] += 1
        return out

    async def _stub_paid(self, record_type: str, record_id: uuid.UUID) -> bool:
        from app.models.platform import AuditLog

        return (
            await self.db.execute(
                select(AuditLog.id)
                .where(
                    AuditLog.record_type == record_type, AuditLog.record_id == record_id, AuditLog.action == "fee_paid"
                )
                .limit(1)
            )
        ).first() is not None

    async def _settle_stub(self, inv: FeeInvoice) -> None:
        """A stub the earlier phase already marked paid → an ``adjustment`` receipt, no events (already consumed)."""
        from app.services.fees.payment_service import PaymentService

        await self.recompute(inv)
        if inv.balance_paise > 0:
            await PaymentService(self.db, self.principal, self.request, self.inst).record(
                inv, inv.balance_paise, "adjustment", emit=False, reference="stub back-fill"
            )


async def open_invoices_for(db: Any, enrol_ids: Sequence[uuid.UUID]) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(FeeInvoice)
                .where(
                    FeeInvoice.student_program_enrollment_id.in_(list(enrol_ids)),
                    FeeInvoice.status.in_(tuple(OPEN_INVOICE)),
                )
            )
        ).scalar_one()
    )


async def overdue_balance(db: Any, enrol_id: uuid.UUID, today: date) -> int:
    """Open balance past its due date — Phase 09 windows with ``requires_fee_clearance``."""
    return int(
        (
            await db.execute(
                select(func.coalesce(func.sum(FeeInvoice.balance_paise), 0)).where(
                    FeeInvoice.student_program_enrollment_id == enrol_id,
                    FeeInvoice.status.in_(tuple(OPEN_INVOICE)),
                    FeeInvoice.due_date < today,
                )
            )
        ).scalar_one()
    )
