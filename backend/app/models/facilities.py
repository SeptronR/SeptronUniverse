"""Facilities — the remaining section 24 tables plus ``amc_contracts`` (§21) and ``emergency_alerts`` (§23)
(Prompts/25 §25.3).

``person_type`` / ``person_id`` pairs (health, insurance, counselling, wallet) name ``students.id`` for students and
``staff.id`` for staff. DDL facts the services rely on: ``service_requests UNIQUE (institution_id, ticket_number)``,
``wallet_accounts UNIQUE (person_type, person_id)``. Columns the DDL lacks (equipment handover / return condition,
SOS escalation timeline, service-request timeline / cost / AMC link, visitor host notification, counselling referral)
live in ``institution_settings`` rows of category ``facilities_meta`` (``app/services/facilities/common.py``).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Index, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import EncryptedBytes, TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated

__all__ = [
    "AmcContract",
    "Canteen",
    "CounsellingAppointment",
    "EmergencyAlert",
    "EquipmentBooking",
    "HealthVisit",
    "InsurancePolicy",
    "LostFoundItem",
    "RoomBooking",
    "ServiceRequest",
    "SportsEvent",
    "SportsParticipation",
    "SportsTeam",
    "VisitorPass",
    "WalletAccount",
    "WalletTransaction",
]

_EAGER: dict[str, Any] = {"eager_defaults": True}


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class RoomBooking(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "room_bookings"
    __mapper_args__ = _EAGER

    room_id: Mapped[uuid.UUID] = _fk("rooms.id", nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(String(200), nullable=False)
    from_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    to_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_headcount: Mapped[int | None] = mapped_column(SmallInteger)
    event_id: Mapped[uuid.UUID | None] = _fk("events.id")
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class EquipmentBooking(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "equipment_bookings"

    asset_id: Mapped[uuid.UUID] = _fk("assets.id", nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    to_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()


class ServiceRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "service_requests"
    __table_args__ = (
        UniqueConstraint("institution_id", "ticket_number"),
        Index("ix_service_requests_status", "institution_id", "status", "sla_due_at"),
    )
    __mapper_args__ = _EAGER

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    ticket_number: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    location_room_id: Mapped[uuid.UUID | None] = _fk("rooms.id")
    location_text: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[Any] | None] = mapped_column(JSONB)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assigned_to: Mapped[uuid.UUID | None] = _uuid()
    vendor_id: Mapped[uuid.UUID | None] = _fk("suppliers.id")
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolution: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AmcContract(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "amc_contracts"
    __mapper_args__ = _EAGER

    supplier_id: Mapped[uuid.UUID] = _fk("suppliers.id", nullable=False)
    asset_category: Mapped[str | None] = mapped_column(String(60))
    asset_ids: Mapped[list[Any] | None] = mapped_column(JSONB)
    from_on: Mapped[date] = mapped_column(Date, nullable=False)
    to_on: Mapped[date] = mapped_column(Date, nullable=False)
    value_paise: Mapped[int | None] = mapped_column(BigInteger)
    sla: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    document_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class VisitorPass(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "visitor_passes"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    visitor: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    host_user_id: Mapped[uuid.UUID | None] = _uuid()
    purpose: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gate_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gate_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    id_proof: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pass_code: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="issued")
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()


class EmergencyAlert(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "emergency_alerts"

    raised_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="raised")
    responders: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    acknowledged_by: Mapped[uuid.UUID | None] = _uuid()
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class HealthVisit(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "health_visits"

    person_type: Mapped[str] = mapped_column(String(10), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    visited_at: Mapped[datetime] = _now()
    complaint: Mapped[str | None] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    treatment: Mapped[str | None] = mapped_column(Text)
    referred_to: Mapped[str | None] = mapped_column(String(200))
    attended_by: Mapped[uuid.UUID | None] = _uuid()
    is_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()


class InsurancePolicy(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "insurance_policies"

    person_type: Mapped[str] = mapped_column(String(10), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_no: Mapped[str] = mapped_column(String(60), nullable=False)
    coverage_paise: Mapped[int | None] = mapped_column(BigInteger)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    document_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class CounsellingAppointment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "counselling_appointments"
    __mapper_args__ = _EAGER

    counsellor_staff_id: Mapped[uuid.UUID] = _fk("staff.id", nullable=False)
    slot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30)
    person_type: Mapped[str | None] = mapped_column(String(10))
    person_id: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    is_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)  # AES-GCM; plain text in Python
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class SportsTeam(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "sports_teams"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    sport: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="institution")
    coach_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    members: Mapped[list[Any] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()


class SportsEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "sports_events"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sport: Mapped[str | None] = mapped_column(String(60))
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    from_on: Mapped[date] = mapped_column(Date, nullable=False)
    to_on: Mapped[date | None] = mapped_column(Date)
    venue: Mapped[str | None] = mapped_column(String(200))
    organiser: Mapped[str | None] = mapped_column(String(200))
    event_id: Mapped[uuid.UUID | None] = _fk("events.id")
    created_at: Mapped[datetime] = _now()


class SportsParticipation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "sports_participation"

    sports_event_id: Mapped[uuid.UUID] = _fk("sports_events.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", nullable=False)
    team_id: Mapped[uuid.UUID | None] = _fk("sports_teams.id")
    result: Mapped[str | None] = mapped_column(String(60))
    position: Mapped[str | None] = mapped_column(String(20))
    evidence_url: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()


class LostFoundItem(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "lost_found_items"

    description: Mapped[str] = mapped_column(Text, nullable=False)
    found_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(String(200))
    image_url: Mapped[str | None] = mapped_column(Text)
    reported_by: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="reported")
    claimant: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class Canteen(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "canteens"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    vendor_id: Mapped[uuid.UUID | None] = _fk("suppliers.id")
    menu: Mapped[list[Any] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WalletAccount(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "wallet_accounts"
    __table_args__ = (UniqueConstraint("person_type", "person_id"),)
    __mapper_args__ = _EAGER

    person_type: Mapped[str] = mapped_column(String(10), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    balance_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    updated_at: Mapped[datetime] = _updated()


class WalletTransaction(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "wallet_transactions"

    account_id: Mapped[uuid.UUID] = _fk("wallet_accounts.id", "CASCADE", nullable=False)
    txn_type: Mapped[str] = mapped_column(String(10), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(120))
    reference: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _now()
