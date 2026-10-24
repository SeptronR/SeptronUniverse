"""Library schemas — Prompts/19 §19.4."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- catalogue -------------------------------------------------------------------------------------------------------------
class BookCategoryIn(_Strict):
    name: str = Field(min_length=2, max_length=100)
    parent_id: uuid.UUID | None = None
    ddc_code: str | None = Field(None, max_length=20)
    is_active: bool = True


class BookCategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    ddc_code: str | None = None
    is_active: bool
    books: int = 0


LibraryResourceTypeLit = Literal["book", "journal", "thesis", "ebook", "ejournal", "cd", "reference"]


class BookCreate(_Strict):
    title: str = Field(min_length=1, max_length=255)
    authors: list[str] = Field(default_factory=list, max_length=20)
    publisher: str | None = Field(None, max_length=160)
    edition: str | None = Field(None, max_length=40)
    year: int | None = Field(None, ge=1400, le=2100)
    isbn: str | None = Field(None, max_length=20)
    language: str | None = Field(None, max_length=30)
    subject: str | None = Field(None, max_length=120)
    call_number: str | None = Field(None, max_length=40)
    resource_type: LibraryResourceTypeLit = "book"
    category_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    pages: int | None = Field(None, ge=1, le=30000)
    price_paise: int | None = Field(None, ge=0)
    cover_url: str | None = None
    description: str | None = None


class BookUpdate(_Strict):
    title: str | None = Field(None, min_length=1, max_length=255)
    authors: list[str] | None = None
    publisher: str | None = None
    edition: str | None = None
    year: int | None = Field(None, ge=1400, le=2100)
    isbn: str | None = Field(None, max_length=20)
    language: str | None = None
    subject: str | None = None
    call_number: str | None = None
    resource_type: LibraryResourceTypeLit | None = None
    category_id: uuid.UUID | None = None
    pages: int | None = None
    price_paise: int | None = Field(None, ge=0)
    cover_url: str | None = None
    description: str | None = None
    is_active: bool | None = None


class BookResponse(BaseModel):
    id: uuid.UUID
    title: str
    authors: list[str] = []
    publisher: str | None = None
    edition: str | None = None
    year: int | None = None
    isbn: str | None = None
    language: str | None = None
    subject: str | None = None
    call_number: str | None = None
    resource_type: str
    category_id: uuid.UUID | None = None
    category: str | None = None
    college_id: uuid.UUID | None = None
    price_paise: int | None = None
    cover_url: str | None = None
    description: str | None = None
    total_copies: int
    available_copies: int
    copies_by_status: dict[str, int] = {}
    locations: list[str] = []
    is_active: bool
    warnings: list[str] = []
    created_at: datetime


class BookImportRequest(_Strict):
    csv: str = Field(min_length=10, max_length=5_000_000)
    mapping: dict[str, str] | None = None  # field → CSV column
    copies_column: str | None = None


class CatalogueImportReport(BaseModel):
    rows: int
    created: int
    updated: int
    copies: int
    errors: list[dict[str, Any]] = []


class CopyBulkCreate(_Strict):
    count: int = Field(ge=1, le=500)
    location: str | None = Field(None, max_length=80)
    price_paise: int | None = Field(None, ge=0)
    barcode_prefix: str | None = Field(None, max_length=20)
    acquired_on: date | None = None


class CopyResponse(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    title: str | None = None
    accession_number: str
    barcode: str | None = None
    rfid_tag: str | None = None
    location: str | None = None
    status: str
    acquired_on: date | None = None
    price_paise: int | None = None
    current_issue_id: uuid.UUID | None = None


class CopyStatusChange(_Strict):
    status: Literal["available", "damaged", "withdrawn", "reference_only"]
    remarks: str | None = Field(None, max_length=500)
    rfid_tag: str | None = Field(None, max_length=60)


# ---- e-resources -------------------------------------------------------------------------------------------------------------
class EresourceIn(_Strict):
    title: str = Field(min_length=2, max_length=255)
    provider: str | None = Field(None, max_length=120)
    resource_type: Literal["ejournal", "ebook_db", "database", "repository"]
    url: str = Field(min_length=8, max_length=2000)
    access_type: Literal["ip", "remote", "open"] = "ip"
    subscription_from: date | None = None
    subscription_to: date | None = None
    cost_paise: int | None = Field(None, ge=0)
    is_active: bool = True


class EresourceOut(BaseModel):
    id: uuid.UUID
    title: str
    provider: str | None = None
    resource_type: str
    url: str | None = None
    access_type: str
    subscription_from: date | None = None
    subscription_to: date | None = None
    cost_paise: int | None = None
    is_active: bool
    expired: bool = False
    expiring_soon: bool = False
    usage_count: int = 0


# ---- members --------------------------------------------------------------------------------------------------------------------
class LibraryMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str | None = None
    member_code: str
    member_type: str
    max_books_allowed: int
    loan_days: int
    max_renewals: int = 1
    valid_to: date | None = None
    is_active: bool
    active_issues: int = 0
    overdue_issues: int = 0
    outstanding_fine_paise: int = 0
    is_blocked: bool = False
    block_reasons: list[str] = []
    department: str | None = None


class LibraryMemberRulesUpdate(_Strict):
    max_books_allowed: int | None = Field(None, ge=0, le=100)
    loan_days: int | None = Field(None, ge=1, le=365)
    valid_to: date | None = None


class ExternalMemberCreate(_Strict):
    user_id: uuid.UUID
    member_type: Literal["external", "alumni"] = "external"
    valid_to: date | None = None
    deposit_paise: int | None = Field(None, ge=0)


class MemberRulesConfig(_Strict):
    rules: dict[str, dict[str, int]]


# ---- circulation -------------------------------------------------------------------------------------------------------------------
class CirculationIssueRequest(_Strict):
    member_code: str | None = None
    user_id: uuid.UUID | None = None
    id_card_token: str | None = None
    barcode: str | None = None
    accession_number: str | None = None
    rfid_tag: str | None = None
    due_on: date | None = None


class BookIssueResponse(BaseModel):
    id: uuid.UUID
    copy_id: uuid.UUID
    accession_number: str | None = None
    book_id: uuid.UUID | None = None
    title: str | None = None
    member_id: uuid.UUID
    member_code: str | None = None
    member_name: str | None = None
    issued_on: date
    due_on: date
    returned_on: date | None = None
    renewals: int
    status: str
    days_overdue: int = 0
    fine_paise: int = 0
    fine_invoice_id: uuid.UUID | None = None
    fine_status: str | None = None


class BookReturnRequest(_Strict):
    barcode: str | None = None
    accession_number: str | None = None
    rfid_tag: str | None = None
    condition: Literal["good", "damaged"] = "good"
    damage_charge_paise: int | None = Field(None, ge=0)


class BookReturnResponse(BaseModel):
    issue: BookIssueResponse
    fine_paise: int
    invoice_id: uuid.UUID | None = None
    reservation_notified: bool = False
    hold_released: bool = False


class BookRenewRequest(_Strict):
    issue_id: uuid.UUID


class BookLostRequest(_Strict):
    issue_id: uuid.UUID
    replacement_cost_paise: int | None = Field(None, ge=0)


class LibraryReservationCreate(_Strict):
    book_id: uuid.UUID
    member_code: str | None = None  # librarian on behalf


class LibraryReservationResponse(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    title: str | None = None
    member_id: uuid.UUID
    member_code: str | None = None
    member_name: str | None = None
    status: str
    position: int | None = None
    reserved_at: datetime
    expires_at: datetime | None = None


class FineWaiveRequest(_Strict):
    reason: str = Field(min_length=5, max_length=1000)


class LibraryFineRow(BaseModel):
    issue_id: uuid.UUID
    title: str | None = None
    member_code: str | None = None
    member_name: str | None = None
    fine_paise: int
    invoice_id: uuid.UUID | None = None
    invoice_status: str | None = None
    balance_paise: int = 0
    returned_on: date | None = None
    status: str


class LibraryIllRequestIn(_Strict):
    title: str = Field(min_length=2, max_length=255)
    source_library: str | None = Field(None, max_length=200)
    member_code: str | None = None


class LibraryIllDecision(_Strict):
    approve: bool = True
    cost_paise: int | None = Field(None, ge=0)
    source_library: str | None = Field(None, max_length=200)


class LibraryIllResponse(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    member_code: str | None = None
    member_name: str | None = None
    title: str
    source_library: str | None = None
    status: str
    requested_at: datetime
    received_on: date | None = None
    returned_on: date | None = None
    cost_paise: int | None = None


# ---- OPAC ------------------------------------------------------------------------------------------------------------------------
class OpacResult(BaseModel):
    id: uuid.UUID
    title: str
    authors: list[str] = []
    year: int | None = None
    publisher: str | None = None
    isbn: str | None = None
    resource_type: str
    category: str | None = None
    language: str | None = None
    available_copies: int
    total_copies: int
    locations: list[str] = []
    score: float | None = None


class OpacSearchResponse(BaseModel):
    total: int
    items: list[OpacResult]
    facets: dict[str, list[dict[str, Any]]] = {}


# ---- stock verification / sync / reports -------------------------------------------------------------------------------------
class StockVerificationRequest(_Strict):
    location: str | None = None
    scanned_barcodes: list[str] = Field(default_factory=list, max_length=50000)


class StockVerificationReport(BaseModel):
    location: str | None = None
    expected: int
    found: int
    missing: list[dict[str, Any]] = []
    unexpected: list[str] = []


class KohaSyncRequest(_Strict):
    direction: Literal["pull", "push"] = "pull"
    since: date | None = None
    source: Literal["koha", "dspace"] = "koha"


class LibrarySyncSummary(BaseModel):
    source: str
    biblios: int = 0
    items: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0


class LibraryStatsResponse(BaseModel):
    books: int
    copies: int
    available: int
    issued: int
    overdue: int
    lost: int
    members: int
    reservations_waiting: int
    reservations_available: int
    eresources: int
    eresources_expired: int
    outstanding_fine_paise: int
    issued_today: int
    returned_today: int


class LibraryJobAccepted(BaseModel):
    job_id: uuid.UUID
    status: str = "queued"
