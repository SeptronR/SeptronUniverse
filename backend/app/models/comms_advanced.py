"""Communication advanced — ``bulk_campaigns`` of section 23 (Prompts/24 §24.3).

``conversation_sessions`` / ``wa_processed_messages`` / ``message_logs`` are modelled by Phase 04
(``app/models/communication.py``) and re-exported here; ``emergency_alerts`` belongs to Phase 25. Saved segments live in
``institution_settings['comms.segments']`` (no table). The section 23 ``status`` comment lists draft | scheduled |
sending | sent | cancelled; Phase 24 adds pending_approval / approved / paused / failed in the same column.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.communication import ConversationSession, MessageLog, WaProcessedMessage
from app.models.registration import _now, _updated

__all__ = ["BulkCampaign", "ConversationSession", "MessageLog", "WaProcessedMessage"]


class BulkCampaign(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "bulk_campaigns"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    audience_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("notification_templates.id"))
    body_override: Mapped[str | None] = mapped_column(
        Text
    )  # JSON text {sms, whatsapp_template, email{subject, html}, push{title, body}, in_app}
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    is_emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_recipients: Mapped[int | None] = mapped_column(Integer)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
