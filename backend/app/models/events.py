"""Events — ``events`` / ``event_registrations`` of section 24 (Prompts/25 §25.3).

Registration settings (``open``, ``capacity``, ``audience``, waitlist), the organiser's report outcomes / spend and
the NAAC tag history have no columns of their own: they live in ``institution_settings`` rows of category
``facilities_meta`` keyed ``event:<id>`` (see ``app/services/facilities/common.py``). ``event_registrations.external``
also carries ``qr_token`` and ``waitlisted`` for every registrant (internal rows too).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated

__all__ = ["Event", "EventRegistration"]


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class Event(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_dates", "institution_id", "from_on"),)
    __mapper_args__ = {"eager_defaults": True}

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    organiser_department_id: Mapped[uuid.UUID | None] = _fk("departments.id")
    organiser_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    from_on: Mapped[date] = mapped_column(Date, nullable=False)
    to_on: Mapped[date] = mapped_column(Date, nullable=False)
    venue_room_id: Mapped[uuid.UUID | None] = _fk("rooms.id")
    venue_text: Mapped[str | None] = mapped_column(String(200))
    budget_paise: Mapped[int | None] = mapped_column(BigInteger)
    sponsor: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    participants_count: Mapped[int | None] = mapped_column(Integer)
    external_participants_count: Mapped[int | None] = mapped_column(Integer)
    report_url: Mapped[str | None] = mapped_column(Text)
    images: Mapped[list[Any] | None] = mapped_column(JSONB)
    naac_criterion: Mapped[str | None] = mapped_column(String(10))
    registration_fee_paise: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventRegistration(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "event_registrations"

    event_id: Mapped[uuid.UUID] = _fk("events.id", "CASCADE", nullable=False)
    person_type: Mapped[str] = mapped_column(String(20), nullable=False)  # student | staff | external
    person_id: Mapped[uuid.UUID | None] = _uuid()
    external: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    attended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    certificate_document_id: Mapped[uuid.UUID | None] = _uuid()
    registered_at: Mapped[datetime] = _now()
