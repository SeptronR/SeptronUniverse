"""Library — section 18 of Database_Schema.sql (Prompts/19 §19.3): categories, books, copies (accession / barcode /
RFID), e-resources, members, issues, reservations and inter-library loan requests.

DDL notes the services rely on: ``library_copies UNIQUE (institution_id, accession_number)``, ``library_members UNIQUE
(institution_id, member_code)``, ``library_reservations UNIQUE (book_id, member_id, status)`` (one waiting / available
reservation per member and book — terminal rows of the same status are kept unique by the service flipping them to
``cancelled`` / ``expired`` / ``fulfilled`` with timestamps). ``books.total_copies`` / ``available_copies`` change only
through copy transactions (``circulation_service`` / ``catalogue_service``).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class BookCategory(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "book_categories"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = _fk("book_categories.id")
    ddc_code: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()


class Book(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "books"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    category_id: Mapped[uuid.UUID | None] = _fk("book_categories.id")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    authors: Mapped[list[str] | None] = mapped_column(JSONB)
    publisher: Mapped[str | None] = mapped_column(String(160))
    edition: Mapped[str | None] = mapped_column(String(40))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    isbn: Mapped[str | None] = mapped_column(String(20))
    language: Mapped[str | None] = mapped_column(String(30))
    subject: Mapped[str | None] = mapped_column(String(120))
    call_number: Mapped[str | None] = mapped_column(String(40))
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False, default="book")
    pages: Mapped[int | None] = mapped_column(SmallInteger)
    price_paise: Mapped[int | None] = mapped_column(Integer)
    cover_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    total_copies: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    available_copies: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    external_ref: Mapped[str | None] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = _uuid()


class LibraryCopy(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "library_copies"
    __table_args__ = (UniqueConstraint("institution_id", "accession_number"),)

    book_id: Mapped[uuid.UUID] = _fk("books.id", "CASCADE", nullable=False)
    accession_number: Mapped[str] = mapped_column(String(30), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(40))
    rfid_tag: Mapped[str | None] = mapped_column(String(60))
    location: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    acquired_on: Mapped[date | None] = mapped_column(Date)
    price_paise: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class LibraryEresource(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "library_eresources"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(120))
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    access_type: Mapped[str] = mapped_column(String(20), nullable=False, default="ip")
    subscription_from: Mapped[date | None] = mapped_column(Date)
    subscription_to: Mapped[date | None] = mapped_column(Date)
    cost_paise: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class LibraryMember(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "library_members"
    __table_args__ = (UniqueConstraint("institution_id", "member_code"),)

    user_id: Mapped[uuid.UUID] = _fk("users.id", "CASCADE", nullable=False)
    member_type: Mapped[str] = mapped_column(String(20), nullable=False)
    member_code: Mapped[str] = mapped_column(String(30), nullable=False)
    max_books_allowed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    loan_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=14)
    valid_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class BookIssue(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "book_issues"

    copy_id: Mapped[uuid.UUID] = _fk("library_copies.id", nullable=False)
    member_id: Mapped[uuid.UUID] = _fk("library_members.id", nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    returned_on: Mapped[date | None] = mapped_column(Date)
    renewals: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    issued_by: Mapped[uuid.UUID | None] = _uuid()
    returned_to: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="issued")
    fine_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fine_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class LibraryReservation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "library_reservations"
    __table_args__ = (UniqueConstraint("book_id", "member_id", "status"),)

    book_id: Mapped[uuid.UUID] = _fk("books.id", "CASCADE", nullable=False)
    member_id: Mapped[uuid.UUID] = _fk("library_members.id", nullable=False)
    reserved_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="waiting")


class LibraryIllRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "library_ill_requests"

    member_id: Mapped[uuid.UUID] = _fk("library_members.id", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_library: Mapped[str | None] = mapped_column(String(200))
    requested_at: Mapped[datetime] = _now()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    received_on: Mapped[date | None] = mapped_column(Date)
    returned_on: Mapped[date | None] = mapped_column(Date)
    cost_paise: Mapped[int | None] = mapped_column(Integer)
