"""Fees, scholarships & no-dues — section 13 of Database_Schema.sql (+ ``ledger_accounts`` of §22) (Prompts/12 §12.3).

Column names mirror the DDL exactly (``check_schema_drift.py --phase 12``). DDL notes the services rely on:

* money is **paise** (integers) everywhere; ``fee_invoices.balance_paise`` = total − discount + tax + fine − paid;
* ``fee_invoices`` carries the universal linkage ``payer_type/payer_id`` + ``source_type/source_id`` (indexed);
  ``UNIQUE (institution_id, invoice_number)`` / ``fee_payments UNIQUE (institution_id, receipt_number)``;
* ``fee_structure_items UNIQUE (structure_id, fee_head_id, instalment_no)``;
* ``student_fee_assignments UNIQUE (student_program_enrollment_id, structure_id)``;
* ``scholarship_applications UNIQUE (scholarship_id, student_program_enrollment_id)``;
* ``no_dues_signoffs UNIQUE (request_id, department_key)``;
* ``day_book_entries UNIQUE (institution_id, college_id, entry_date, counter, collected_by)`` (NULLs never collide —
  the service looks the row up first).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class LedgerAccount(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (UniqueConstraint("institution_id", "code"),)

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = _fk("ledger_accounts.id")
    external_ref: Mapped[str | None] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()


class FeeHead(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fee_heads"
    __table_args__ = (UniqueConstraint("institution_id", "code"),)

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    head_type: Mapped[str] = mapped_column(String(30), nullable=False, default="tuition")
    is_refundable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    ledger_account_id: Mapped[uuid.UUID | None] = _fk("ledger_accounts.id", "SET NULL")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class FeeStructure(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fee_structures"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id", "CASCADE")
    academic_year_id: Mapped[uuid.UUID | None] = _fk("academic_years.id")
    program_id: Mapped[uuid.UUID | None] = _fk("programs.id")
    program_regulation_id: Mapped[uuid.UUID | None] = _fk("program_regulations.id")
    batch_id: Mapped[uuid.UUID | None] = _fk("batches.id")
    term_number: Mapped[int | None] = mapped_column(SmallInteger)
    category: Mapped[str | None] = mapped_column(String(20))
    quota: Mapped[str | None] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    total_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    per_credit_paise: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = _uuid()


class FeeStructureItem(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fee_structure_items"
    __table_args__ = (UniqueConstraint("structure_id", "fee_head_id", "instalment_no"),)

    structure_id: Mapped[uuid.UUID] = _fk("fee_structures.id", "CASCADE", nullable=False)
    fee_head_id: Mapped[uuid.UUID] = _fk("fee_heads.id", nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    instalment_no: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_offset_days: Mapped[int | None] = mapped_column(SmallInteger)
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class FeeDiscount(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fee_discounts"
    __table_args__ = (UniqueConstraint("institution_id", "code"),)

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    applies_to_heads: Mapped[list[str] | None] = mapped_column(JSONB)
    eligibility_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_per_year: Mapped[int | None] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class StudentFeeAssignment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "student_fee_assignments"
    __table_args__ = (UniqueConstraint("student_program_enrollment_id", "structure_id"),)

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    structure_id: Mapped[uuid.UUID] = _fk("fee_structures.id", nullable=False)
    term_id: Mapped[uuid.UUID | None] = _fk("academic_terms.id")
    assigned_by: Mapped[uuid.UUID | None] = _uuid()
    assigned_at: Mapped[datetime] = _now()


class StudentDiscountAssignment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "student_discount_assignments"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    discount_id: Mapped[uuid.UUID] = _fk("fee_discounts.id", nullable=False)
    academic_year_id: Mapped[uuid.UUID | None] = _fk("academic_years.id")
    reason: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="approved")
    created_at: Mapped[datetime] = _now()


class FineConfiguration(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fine_configurations"

    applies_to: Mapped[str] = mapped_column(String(30), nullable=False)
    calc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_paise: Mapped[int | None] = mapped_column(Integer)
    grace_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_paise: Mapped[int | None] = mapped_column(Integer)
    slabs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class FeeInvoice(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fee_invoices"
    __table_args__ = (
        UniqueConstraint("institution_id", "invoice_number"),
        Index("ix_fee_invoices_payer", "payer_type", "payer_id", "status"),
        Index("ix_fee_invoices_source", "source_type", "source_id"),
        Index("ix_fee_invoices_due", "institution_id", "status", "due_date"),
    )

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id", "CASCADE")
    payer_type: Mapped[str] = mapped_column(String(20), nullable=False, default="student")
    payer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID | None] = _fk("student_program_enrollments.id")
    invoice_number: Mapped[str] = mapped_column(String(40), nullable=False)
    academic_year_id: Mapped[uuid.UUID | None] = _fk("academic_years.id")
    term_id: Mapped[uuid.UUID | None] = _fk("academic_terms.id")
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[uuid.UUID | None] = _uuid()
    description: Mapped[str | None] = mapped_column(String(255))
    total_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fine_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balance_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    gst_number: Mapped[str | None] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_reason: Mapped[str | None] = mapped_column(Text)


class FeeInvoiceItem(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fee_invoice_items"

    invoice_id: Mapped[uuid.UUID] = _fk("fee_invoices.id", "CASCADE", nullable=False)
    fee_head_id: Mapped[uuid.UUID | None] = _fk("fee_heads.id")
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    instalment_no: Mapped[int | None] = mapped_column(SmallInteger)
    due_date: Mapped[date | None] = mapped_column(Date)


class FeePayment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fee_payments"
    __table_args__ = (
        UniqueConstraint("institution_id", "receipt_number"),
        Index("ix_fee_payments_invoice", "invoice_id"),
        Index("ix_fee_payments_date", "institution_id", "payment_date"),
    )

    invoice_id: Mapped[uuid.UUID] = _fk("fee_invoices.id", nullable=False)
    receipt_number: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    gateway: Mapped[str | None] = mapped_column(String(30))
    gateway_order_id: Mapped[str | None] = mapped_column(String(80))
    gateway_payment_id: Mapped[str | None] = mapped_column(String(80))
    gateway_signature: Mapped[str | None] = mapped_column(String(255))
    reference_no: Mapped[str | None] = mapped_column(String(80))
    utr: Mapped[str | None] = mapped_column(String(40))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    collected_by: Mapped[uuid.UUID | None] = _uuid()
    counter: Mapped[str | None] = mapped_column(String(40))
    receipt_url: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = _uuid()
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancel_workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    idempotency_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class OfflinePaymentReconciliation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "offline_payment_reconciliations"

    statement_file_url: Mapped[str | None] = mapped_column(Text)
    bank_account: Mapped[str | None] = mapped_column(String(60))
    statement_date: Mapped[date | None] = mapped_column(Date)
    utr: Mapped[str | None] = mapped_column(String(40))
    amount_paise: Mapped[int | None] = mapped_column(Integer)
    payer_hint: Mapped[str | None] = mapped_column(String(200))
    matched_payment_id: Mapped[uuid.UUID | None] = _fk("fee_payments.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unmatched")
    matched_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class FeeRefund(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fee_refunds"

    invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    payment_id: Mapped[uuid.UUID | None] = _fk("fee_payments.id")
    payer_type: Mapped[str] = mapped_column(String(20), nullable=False)
    payer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    refund_mode: Mapped[str | None] = mapped_column(String(20))
    reference_no: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class DayBookEntry(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "day_book_entries"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "entry_date", "counter", "collected_by"),)

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    counter: Mapped[str | None] = mapped_column(String(40))
    collected_by: Mapped[uuid.UUID | None] = _uuid()
    cash_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    digital_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cheque_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deposited_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)


class Scholarship(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "scholarships"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    scheme_code: Mapped[str | None] = mapped_column(String(40))
    amount_paise: Mapped[int | None] = mapped_column(Integer)
    amount_type: Mapped[str] = mapped_column(String(20), nullable=False, default="fixed")
    eligibility_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    academic_year_id: Mapped[uuid.UUID | None] = _fk("academic_years.id")
    applications_open: Mapped[date | None] = mapped_column(Date)
    applications_close: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ScholarshipApplication(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "scholarship_applications"
    __table_args__ = (UniqueConstraint("scholarship_id", "student_program_enrollment_id"),)

    scholarship_id: Mapped[uuid.UUID] = _fk("scholarships.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    income_paise: Mapped[int | None] = mapped_column(BigInteger)
    documents: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="applied")
    sanctioned_paise: Mapped[int | None] = mapped_column(Integer)
    disbursement_mode: Mapped[str | None] = mapped_column(String(20))
    external_ref: Mapped[str | None] = mapped_column(String(60))
    fee_discount_id: Mapped[uuid.UUID | None] = _fk("fee_discounts.id")
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class NoDuesRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "no_dues_requests"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    requested_at: Mapped[datetime] = _now()
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certificate_document_id: Mapped[uuid.UUID | None] = _uuid()


class NoDuesSignoff(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "no_dues_signoffs"
    __table_args__ = (UniqueConstraint("request_id", "department_key"),)

    request_id: Mapped[uuid.UUID] = _fk("no_dues_requests.id", "CASCADE", nullable=False)
    department_key: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    dues_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remarks: Mapped[str | None] = mapped_column(Text)
    signed_by: Mapped[uuid.UUID | None] = _uuid()
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
