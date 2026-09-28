"""Communication — section 23 of Database_Schema.sql (Prompts/04 §04.3). Workflow and device models live in
``models/platform.py`` (sections 3 and 6). ``message_logs`` is range-partitioned by ``created_at`` (monthly children
created by ``partitions.ensure_next_month``; the default partition catches the rest) — its PK is ``(id, created_at)``.
``bulk_campaigns`` and ``emergency_alerts`` (same section) are Phase 24 / Phase 25 tables.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


def _inst(nullable: bool = True) -> Mapped[Any]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=nullable, index=True
    )


class NotificationTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_templates"
    __table_args__ = (UniqueConstraint("institution_id", "event_trigger", "language", "version"),)

    institution_id: Mapped[uuid.UUID | None] = _inst()  # NULL = platform default (read-only for tenants)
    event_trigger: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=lambda: ["in_app"])
    subject_template: Mapped[str | None] = mapped_column(Text)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str] | None] = mapped_column(JSONB)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dlt_template_id: Mapped[str | None] = mapped_column(String(40))
    whatsapp_template_name: Mapped[str | None] = mapped_column(String(120))


class DltTemplate(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "dlt_templates"
    __table_args__ = (UniqueConstraint("institution_id", "template_id"),)

    institution_id: Mapped[uuid.UUID] = _inst(False)
    sender_id: Mapped[str] = mapped_column(String(10), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(30))
    template_id: Mapped[str] = mapped_column(String(40), nullable=False)
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="transactional")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="approved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WhatsappTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_templates"
    __table_args__ = (UniqueConstraint("institution_id", "name", "language"),)

    institution_id: Mapped[uuid.UUID] = _inst(False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    components: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending | approved | rejected
    meta_template_id: Mapped[str | None] = mapped_column(String(60))


class NotificationPreference(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "category"),)

    institution_id: Mapped[uuid.UUID | None] = _inst()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    quiet_hours: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    digest: Mapped[str] = mapped_column(String(20), nullable=False, default="none")  # none | daily | weekly
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Notification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notifications"

    institution_id: Mapped[uuid.UUID | None] = _inst()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(40))
    event_type: Mapped[str | None] = mapped_column(String(80))
    link: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MessageLog(Base):
    __tablename__ = "message_logs"
    __table_args__ = (PrimaryKeyConstraint("id", "created_at"), {"postgresql_partition_by": "RANGE (created_at)"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    recipient: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # sms | whatsapp | email | push | in_app
    event_type: Mapped[str | None] = mapped_column(String(80))
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    subject: Mapped[str | None] = mapped_column(String(255))
    body_preview: Mapped[str | None] = mapped_column(String(255))
    provider: Mapped[str | None] = mapped_column(String(30))
    provider_message_id: Mapped[str | None] = mapped_column(String(120))
    # queued | deferred | sent | delivered | failed | bounced | read | suppressed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    cost_paise: Mapped[int | None] = mapped_column(Integer)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Announcement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "announcements"

    institution_id: Mapped[uuid.UUID] = _inst(False)
    college_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("colleges.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(30))
    audience_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requires_ack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnnouncementAcknowledgement(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "announcement_acknowledgements"
    __table_args__ = (UniqueConstraint("announcement_id", "user_id"),)

    institution_id: Mapped[uuid.UUID] = _inst(False)
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conversation_sessions"

    institution_id: Mapped[uuid.UUID | None] = _inst()
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # web | whatsapp
    external_id: Mapped[str | None] = mapped_column(String(120))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    flow_key: Mapped[str | None] = mapped_column(String(60))
    state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    messages: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WaProcessedMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "wa_processed_messages"

    institution_id: Mapped[uuid.UUID | None] = _inst()
    wa_message_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
