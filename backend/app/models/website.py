"""Website models — Database_Schema.sql §32 (the eight website tables; Prompts/40 §40.3).

Facts without columns live in ``institution_settings`` category ``website_meta`` (config draft / published copies and
versions, notice pins / announce flags / college scope, gallery EXIF state, enquiry spam score / CRM stage, domain
DNS check log and SSL reason, catalogue settings) — see ``app/services/website/common.py``.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InstitutionWebsiteConfig(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "institution_website_config"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    theme: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    hero: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sections: Mapped[Any | None] = mapped_column(JSONB)
    seo: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    contact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    social: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    show_catalog: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = _now()


class InstitutionDomain(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "institution_domains"

    hostname: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_token: Mapped[str | None] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ssl_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = _now()


class GalleryAlbum(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "gallery_albums"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()


class GalleryImage(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "gallery_images"

    album_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gallery_albums.id", ondelete="CASCADE"), nullable=False
    )
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[str | None] = mapped_column(String(200))
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()


class WebsiteNotice(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "website_notices"
    __table_args__ = (UniqueConstraint("institution_id", "slug"),)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    category: Mapped[str | None] = mapped_column(String(40))
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WebsiteEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "website_events"
    __table_args__ = (UniqueConstraint("institution_id", "slug"),)

    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image_url: Mapped[str | None] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()


class WebsiteContentItem(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "website_content_items"
    __table_args__ = (UniqueConstraint("institution_id", "section", "slug"),)

    section: Mapped[str] = mapped_column(String(60), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    media: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WebsiteEnquiry(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "website_enquiries"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    subject: Mapped[str | None] = mapped_column(String(200))
    message: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[str | None] = mapped_column(String(200))
    enquiry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("enquiries.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    created_at: Mapped[datetime] = _now()
