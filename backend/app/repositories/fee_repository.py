"""Fees repositories — Prompts/12 §12.5 (one module, like Phase 11's ``attendance_repository``).

* ``FeeRepository`` (``module="fees"``) — invoices with ``fee_scope.invoice_predicate`` (self / wards / advisees /
  units / all), ``FOR UPDATE`` on invoices and payments during collection, payments by date / mode / counter;
* ``StructureRepository`` — ``applicable(enrolment, student, term_number, on_date)``: the most specific effective
  structure (batch > regulation > programme, then category / quota, then college / institution);
* ``ScholarshipRepository`` (``module="scholarships"``) / ``NoDuesRepository`` (``module="no_dues"``) — scoped
  lists over the enrolment;
* ``LedgerRepository`` — the minimal chart (Phase 23 extends it).
"""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, and_, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.fees import (
    FeeInvoice,
    FeePayment,
    FeeStructure,
    LedgerAccount,
    NoDuesRequest,
    ScholarshipApplication,
)
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.base import BaseRepository
from app.repositories.fee_scope import enrollment_column_predicate, invoice_predicate


class FeeRepository(BaseRepository[FeeInvoice]):
    model = FeeInvoice
    module = "fees"

    def scoped(self, scope: str | None = None) -> Select[tuple[FeeInvoice]]:
        q = self._base()
        if self.principal is not None:
            q = q.where(invoice_predicate(self.principal, scope))
        return q

    async def get_visible(self, invoice_id: uuid.UUID, *, for_update: bool = False) -> FeeInvoice:
        q = self.scoped("all").where(FeeInvoice.id == invoice_id)
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Invoice not found")
        return row

    async def get_any(self, invoice_id: uuid.UUID, *, for_update: bool = False) -> FeeInvoice:
        """Unscoped (tenant only) — system paths: consumers, webhooks, Beat."""
        q = select(FeeInvoice).where(FeeInvoice.id == invoice_id, FeeInvoice.institution_id == self.institution_id)
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Invoice not found")
        return row

    async def lock_many(self, ids: Sequence[uuid.UUID]) -> list[FeeInvoice]:
        rows = (
            (
                await self.db.execute(
                    select(FeeInvoice)
                    .where(FeeInvoice.id.in_(list(ids)), FeeInvoice.institution_id == self.institution_id)
                    .order_by(FeeInvoice.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def by_source(self, source_type: str, source_id: uuid.UUID) -> FeeInvoice | None:
        row: FeeInvoice | None = (
            await self.db.execute(
                select(FeeInvoice)
                .where(
                    FeeInvoice.institution_id == self.institution_id,
                    FeeInvoice.source_type == source_type,
                    FeeInvoice.source_id == source_id,
                    FeeInvoice.status != "cancelled",
                )
                .order_by(FeeInvoice.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        return row

    async def payment(self, payment_id: uuid.UUID, *, for_update: bool = False) -> FeePayment:
        q = select(FeePayment).where(FeePayment.id == payment_id, FeePayment.institution_id == self.institution_id)
        if self.principal is not None and not getattr(self.principal, "is_super_admin", False):
            q = q.where(
                FeePayment.invoice_id.in_(select(FeeInvoice.id).where(invoice_predicate(self.principal, "all")))
            )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Payment not found")
        return row

    def payments_stmt(
        self,
        *,
        on: date | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        mode: str | None = None,
        counter: str | None = None,
        status: str | None = None,
        scope: str | None = "all",
    ) -> Select[tuple[FeePayment]]:
        q = select(FeePayment).where(FeePayment.institution_id == self.institution_id)
        if self.principal is not None and not getattr(self.principal, "is_super_admin", False):
            q = q.where(
                FeePayment.invoice_id.in_(select(FeeInvoice.id).where(invoice_predicate(self.principal, scope)))
            )
        if on:
            q = q.where(FeePayment.payment_date == on)
        if date_from:
            q = q.where(FeePayment.payment_date >= date_from)
        if date_to:
            q = q.where(FeePayment.payment_date <= date_to)
        if mode:
            q = q.where(FeePayment.payment_mode == mode)
        if counter:
            q = q.where(FeePayment.counter == counter)
        if status:
            q = q.where(FeePayment.status == status)
        return q.order_by(FeePayment.created_at.desc())


class StructureRepository(BaseRepository[FeeStructure]):
    model = FeeStructure
    module = "fees"

    def visible(self, q: Select[tuple[FeeStructure]], scope: str | None = None) -> Select[tuple[FeeStructure]]:
        return q  # structures are institution masters (route permission gates them)

    async def candidates(self, on_date: date) -> list[FeeStructure]:
        rows = (
            (
                await self.db.execute(
                    self._base().where(
                        FeeStructure.status == "active",
                        FeeStructure.is_active.is_(True),
                        FeeStructure.effective_from <= on_date,
                        or_(FeeStructure.effective_to.is_(None), FeeStructure.effective_to >= on_date),
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    def score(
        s: FeeStructure, e: StudentProgramEnrollment, st: Student, term_number: int | None
    ) -> tuple[int, list[str]] | None:
        """``None`` when a set dimension does not match; else a specificity score (higher wins) + matched names."""
        dims: list[tuple[Any, Any, int, str]] = [
            (s.batch_id, e.batch_id, 400, "batch"),
            (s.program_regulation_id, e.program_regulation_id, 200, "regulation"),
            (s.program_id, e.program_id, 100, "programme"),
            (s.category, st.category, 40, "category"),
            (s.quota, st.admission_quota, 20, "quota"),
            (s.college_id, e.college_id, 10, "college"),
            (s.term_number, term_number, 5, "term"),
        ]
        total, matched = 0, []
        for want, have, weight, name in dims:
            if want is None:
                continue
            if isinstance(want, str) and isinstance(have, str):
                if want.lower() != have.lower():
                    return None
            elif want != have:
                return None
            total += weight
            matched.append(name)
        return total, matched

    async def applicable(
        self, e: StudentProgramEnrollment, st: Student, term_number: int | None, on_date: date
    ) -> tuple[FeeStructure | None, list[str], int]:
        best: tuple[int, FeeStructure, list[str]] | None = None
        cands = await self.candidates(on_date)
        for s in cands:
            sc = self.score(s, e, st, term_number)
            if sc is None:
                continue
            if best is None or sc[0] > best[0] or (sc[0] == best[0] and s.effective_from > best[1].effective_from):
                best = (sc[0], s, sc[1])
        return (best[1], best[2], len(cands)) if best else (None, [], len(cands))

    async def overlapping(self, s: FeeStructure | Any, exclude: uuid.UUID | None = None) -> FeeStructure | None:
        """Another active structure with the identical dimension set whose dates overlap (409)."""
        cols = ("college_id", "program_id", "program_regulation_id", "batch_id", "term_number", "category", "quota")
        conds = [
            (getattr(FeeStructure, c).is_(None) if getattr(s, c) is None else getattr(FeeStructure, c) == getattr(s, c))
            for c in cols
        ]
        end = s.effective_to or date(9999, 12, 31)
        q = self._base().where(
            *conds,
            FeeStructure.status == "active",
            FeeStructure.effective_from <= end,
            or_(FeeStructure.effective_to.is_(None), FeeStructure.effective_to >= s.effective_from),
        )
        if exclude:
            q = q.where(FeeStructure.id != exclude)
        row: FeeStructure | None = (await self.db.execute(q.limit(1))).scalar_one_or_none()
        return row


class ScholarshipRepository(BaseRepository[ScholarshipApplication]):
    model = ScholarshipApplication
    module = "scholarships"

    def scoped(self, scope: str | None = None) -> Select[tuple[ScholarshipApplication]]:
        q = self._base()
        if self.principal is not None and not getattr(self.principal, "is_super_admin", False):
            q = q.where(
                enrollment_column_predicate(
                    self.principal, ScholarshipApplication.student_program_enrollment_id, scope, "scholarships"
                )
            )
        return q

    async def get_visible(self, app_id: uuid.UUID, *, for_update: bool = False) -> ScholarshipApplication:
        q = self.scoped("all").where(ScholarshipApplication.id == app_id)
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Scholarship application not found")
        return row


class NoDuesRepository(BaseRepository[NoDuesRequest]):
    model = NoDuesRequest
    module = "no_dues"

    def scoped(self, scope: str | None = None) -> Select[tuple[NoDuesRequest]]:
        q = self._base()
        if self.principal is not None and not getattr(self.principal, "is_super_admin", False):
            q = q.where(
                enrollment_column_predicate(
                    self.principal, NoDuesRequest.student_program_enrollment_id, scope, "no_dues"
                )
            )
        return q

    async def get_visible(self, rid: uuid.UUID, *, for_update: bool = False) -> NoDuesRequest:
        q = self.scoped("all").where(NoDuesRequest.id == rid)
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "No-dues request not found")
        return row


class LedgerRepository(BaseRepository[LedgerAccount]):
    model = LedgerAccount
    module = "fees"

    async def chart(self) -> list[LedgerAccount]:
        return list((await self.db.execute(self._base().order_by(LedgerAccount.code))).scalars().all())


__all__ = [
    "FeeRepository",
    "LedgerRepository",
    "NoDuesRepository",
    "ScholarshipRepository",
    "StructureRepository",
    "and_",
]
