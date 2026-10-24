"""Accounting & budget — section 22 of Database_Schema.sql (Prompts/23 §23.3).

``ledger_accounts`` is modelled by Phase 12 (``app/models/fees.py``) and re-exported here. Automatic postings are
``income_records`` / ``expense_records`` rows with ``source_type`` / ``source_id`` (no separate journal table);
``budget_heads UNIQUE (academic_year_id, college_id, department_id, name)``; ``grant_ledgers.budget_heads`` is a JSONB list
``[{name, allocated_paise, utilised_paise}]``; ``bank_reconciliations.items`` holds the statement rows with their match.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.fees import LedgerAccount
from app.models.registration import _fk, _now, _updated

__all__ = [
    "AccountingExport",
    "BankReconciliation",
    "BudgetHead",
    "ExpenseRecord",
    "GrantLedger",
    "IncomeRecord",
    "LedgerAccount",
]


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class IncomeRecord(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "income_records"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    ledger_account_id: Mapped[uuid.UUID] = _fk("ledger_accounts.id", nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[uuid.UUID | None] = _uuid()
    description: Mapped[str | None] = mapped_column(String(255))
    reference_no: Mapped[str | None] = mapped_column(String(80))
    payment_mode: Mapped[str | None] = mapped_column(String(20))
    recorded_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()


class BudgetHead(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "budget_heads"
    __table_args__ = (UniqueConstraint("academic_year_id", "college_id", "department_id", "name"),)

    academic_year_id: Mapped[uuid.UUID] = _fk("academic_years.id", nullable=False)
    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    department_id: Mapped[uuid.UUID | None] = _fk("departments.id")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    ledger_account_id: Mapped[uuid.UUID | None] = _fk("ledger_accounts.id")
    allocated_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    utilised_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    committed_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="approved")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ExpenseRecord(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "expense_records"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    department_id: Mapped[uuid.UUID | None] = _fk("departments.id")
    ledger_account_id: Mapped[uuid.UUID] = _fk("ledger_accounts.id", nullable=False)
    budget_head_id: Mapped[uuid.UUID | None] = _fk("budget_heads.id", "SET NULL")
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    spent_on: Mapped[date] = mapped_column(Date, nullable=False)
    payee: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(255))
    reference_no: Mapped[str | None] = mapped_column(String(80))
    vendor_bill_id: Mapped[uuid.UUID | None] = _fk("vendor_bills.id")
    document_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="recorded")
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    recorded_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class GrantLedger(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "grant_ledgers"

    research_project_id: Mapped[uuid.UUID | None] = _uuid()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    funding_agency: Mapped[str | None] = mapped_column(String(160))
    sanctioned_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    utilised_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    budget_heads: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class BankReconciliation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "bank_reconciliations"

    bank_account: Mapped[str] = mapped_column(String(60), nullable=False)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    statement_balance_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ledger_balance_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    difference_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    reconciled_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()


class AccountingExport(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "accounting_exports"

    target: Mapped[str] = mapped_column(String(20), nullable=False)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    file_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    job_id: Mapped[uuid.UUID | None] = _uuid()
    requested_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
