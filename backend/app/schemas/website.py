"""Website, catalogue, domains and marketing schemas — Prompts/40 §40.4."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import ORMModel


# ---- site config ----------------------------------------------------------------------------------------------------
class SectionIn(BaseModel):
    type: str = Field(max_length=40)
    key: str = Field(max_length=60)
    title: str | None = Field(default=None, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    is_visible: bool = True
    sequence: int = Field(default=1, ge=0, le=1000)


class SiteConfigIn(BaseModel):
    is_enabled: bool = True
    theme: dict[str, Any] = Field(default_factory=dict)
    hero: dict[str, Any] = Field(default_factory=dict)
    sections: list[SectionIn] = Field(default_factory=list, max_length=60)
    seo: dict[str, Any] = Field(default_factory=dict)
    contact: dict[str, Any] = Field(default_factory=dict)
    social: dict[str, Any] = Field(default_factory=dict)
    show_catalog: bool = True
    show_apply: bool = True


class SiteConfigOut(SiteConfigIn):
    has_unpublished_changes: bool = False
    published_at: datetime | None = None
    version: int = 0


class SitePublishRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class SiteVersionOut(BaseModel):
    version: int
    published_at: datetime
    published_by: uuid.UUID | None = None
    notes: str | None = None


class SitePreviewToken(BaseModel):
    token: str
    url: str
    expires_at: datetime


# ---- content --------------------------------------------------------------------------------------------------------
class ContentItemIn(BaseModel):
    section: str = Field(max_length=60, pattern=r"^[a-z0-9_]+(:[A-Za-z0-9_-]+)?$")
    slug: str = Field(max_length=120, pattern=r"^[a-z0-9-]+$")
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=200_000)
    media: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    sequence: int = Field(default=1, ge=0, le=1000)
    is_published: bool = False


class ContentItemOut(ORMModel):
    id: uuid.UUID
    section: str
    slug: str
    title: str | None = None
    body: str | None = None
    media: list[dict[str, Any]] | None = None
    sequence: int
    is_published: bool
    created_at: datetime
    updated_at: datetime


# ---- notices --------------------------------------------------------------------------------------------------------
class NoticeIn(BaseModel):
    title: str = Field(max_length=200)
    slug: str | None = Field(default=None, max_length=120, pattern=r"^[a-z0-9-]+$")
    body: str | None = Field(default=None, max_length=100_000)
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    category: str = Field(default="general", max_length=40)
    publish_at: datetime | None = None
    expires_at: datetime | None = None
    is_published: bool = False
    pin: bool = False
    also_announce: bool = False
    college_code: str | None = Field(default=None, max_length=20)


class NoticeOut(ORMModel):
    id: uuid.UUID
    title: str
    slug: str
    body: str | None = None
    attachments: list[dict[str, Any]] | None = None
    category: str | None = None
    publish_at: datetime | None = None
    expires_at: datetime | None = None
    is_published: bool
    created_at: datetime
    updated_at: datetime
    pinned: bool = False
    state: str = "draft"  # draft | scheduled | live | expired


class NoticeBulkAction(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    action: Literal["publish", "unpublish", "expire", "delete"]


class BulkReport(BaseModel):
    succeeded: int
    failed: int
    errors: list[dict[str, Any]] = Field(default_factory=list)


# ---- events / gallery -----------------------------------------------------------------------------------------------
class WebsiteEventIn(BaseModel):
    event_id: uuid.UUID | None = None
    title: str = Field(max_length=200)
    slug: str | None = Field(default=None, max_length=120, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(default=None, max_length=50_000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    image_url: str | None = Field(default=None, max_length=2000)
    is_published: bool = False


class WebsiteEventOut(ORMModel):
    id: uuid.UUID
    event_id: uuid.UUID | None = None
    title: str
    slug: str
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    image_url: str | None = None
    is_published: bool
    registration_url: str | None = None


class EventMirrorRequest(BaseModel):
    event_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    publish: bool = True


class AlbumIn(BaseModel):
    title: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    cover_url: str | None = Field(default=None, max_length=2000)
    is_published: bool = True
    sequence: int = Field(default=1, ge=0, le=1000)


class ImageIn(BaseModel):
    image_url: str = Field(max_length=2000)
    caption: str | None = Field(default=None, max_length=200)
    sequence: int = Field(default=1, ge=0, le=1000)


class ImageOut(ORMModel):
    id: uuid.UUID
    album_id: uuid.UUID
    image_url: str
    caption: str | None = None
    sequence: int


class AlbumOut(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    cover_url: str | None = None
    is_published: bool
    sequence: int
    images: list[ImageOut] = Field(default_factory=list)
    image_count: int = 0


class ImageBulkUpload(BaseModel):
    zip_url: str = Field(max_length=2000, description="file-service URL of the uploaded zip")


# ---- enquiries ------------------------------------------------------------------------------------------------------
class WebsiteEnquiryOut(ORMModel):
    id: uuid.UUID
    name: str
    email: str | None = None
    phone: str | None = None
    subject: str | None = None
    message: str | None = None
    source_page: str | None = None
    enquiry_id: uuid.UUID | None = None
    status: str
    created_at: datetime
    spam_score: int = 0


class EnquiryStatusChange(BaseModel):
    status: Literal["new", "contacted", "converted", "spam", "closed"]


class PublicEnquiryIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    # validated here (422): the CRM enquiry it becomes uses EmailStr, which otherwise raised a 500 inside the service
    email: EmailStr | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    subject: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=3, max_length=5000)
    program_interest: str | None = Field(default=None, max_length=60)
    captcha_token: str | None = Field(default=None, max_length=4000)
    source_page: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=200, description="honeypot — must stay empty")
    consent: bool = True


class PublicEnquiryOut(BaseModel):
    reference: str


# ---- catalogue ------------------------------------------------------------------------------------------------------
class CatalogueProgrammeSetting(BaseModel):
    program_id: uuid.UUID
    visible: bool = True
    show_fees: bool = False
    highlight: bool = False


class CatalogueSettingsIO(BaseModel):
    programmes: list[CatalogueProgrammeSetting] = Field(default_factory=list, max_length=500)
    courses_hidden: list[str] = Field(default_factory=list, max_length=2000)
    show_electives: bool = True
    show_outcomes: bool = True


class CatalogueProgramme(BaseModel):
    model_config = ConfigDict(extra="allow")
    code: str
    name: str
    level: str | None = None
    department: str | None = None
    college: str | None = None
    intake: int | None = None
    highlight: bool = False
    fees_summary: dict[str, Any] | None = None
    apply_url: str | None = None


class PublicCatalogueOut(BaseModel):
    programmes: list[CatalogueProgramme]
    groups: dict[str, list[str]] = Field(default_factory=dict)


# ---- domains --------------------------------------------------------------------------------------------------------
class DomainIn(BaseModel):
    hostname: str = Field(min_length=4, max_length=255, pattern=r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
    make_primary: bool = False


class DomainOut(ORMModel):
    id: uuid.UUID
    hostname: str
    is_primary: bool
    verification_token: str | None = None
    verified_at: datetime | None = None
    ssl_status: str
    created_at: datetime
    dns_instructions: dict[str, str] = Field(default_factory=dict)
    last_check: dict[str, Any] | None = None


class DomainVerifyResult(BaseModel):
    ok: bool
    hostname: str
    found: list[str] = Field(default_factory=list)
    ssl_status: str
    message: str


class SslStatusIn(BaseModel):
    status: Literal["provisioning", "active", "failed", "disabled"]
    reason: str | None = Field(default=None, max_length=500)


class EdgeDomainOut(BaseModel):
    id: uuid.UUID
    hostname: str
    institution_slug: str
    is_primary: bool
    ssl_status: str


# ---- disclosures / directory / analytics ----------------------------------------------------------------------------
class DisclosureItem(BaseModel):
    key: str = Field(max_length=120)
    title: str | None = Field(default=None, max_length=200)
    source: Literal["metric", "policy", "document", "text"]
    ref: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=10_000)
    is_published: bool = False


class DisclosureSettingsIO(BaseModel):
    items: list[DisclosureItem] = Field(default_factory=list, max_length=200)


class FacultyDirectorySettingsIO(BaseModel):
    fields: list[str] = Field(default_factory=list, max_length=20)
    opt_out: list[uuid.UUID] = Field(default_factory=list, max_length=2000)


class SiteAnalyticsOut(BaseModel):
    pageviews_by_day: dict[str, int]
    top_pages: list[dict[str, Any]]
    visitors_by_day: dict[str, int]
    enquiry_conversions: dict[str, int]


# ---- marketing ------------------------------------------------------------------------------------------------------
class MarketingSiteIO(BaseModel):
    model_config = ConfigDict(extra="allow")
    hero: dict[str, Any] = Field(default_factory=dict)
    features: list[dict[str, Any]] = Field(default_factory=list)
    testimonials: list[dict[str, Any]] = Field(default_factory=list)
    faq: list[dict[str, Any]] = Field(default_factory=list)
    legal: dict[str, str] = Field(default_factory=dict)
    links: dict[str, str] = Field(default_factory=dict)


class MarketingOut(MarketingSiteIO):
    published_at: datetime | None = None
    has_unpublished_changes: bool = False
    pricing: list[dict[str, Any]] = Field(default_factory=list)


# ---- public composite -----------------------------------------------------------------------------------------------
class PublicSiteOut(BaseModel):
    institution: dict[str, Any]
    config: dict[str, Any]
    sections: list[dict[str, Any]]
    canonical: str | None = None
    preview: bool = False


class PublicAdmissionsOut(BaseModel):
    open: list[dict[str, Any]]
    upcoming: list[dict[str, Any]]
    closed: list[dict[str, Any]]


class PublicResultLookupIn(BaseModel):
    registration_number: str = Field(max_length=40)
    dob: date | None = None
    hall_ticket_no: str | None = Field(default=None, max_length=40)
    captcha_token: str | None = Field(default=None, max_length=4000)
