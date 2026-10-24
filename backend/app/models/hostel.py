"""Hostel, mess & staff accommodation — section 19 of Database_Schema.sql (Prompts/20 §20.3).

DDL notes the services rely on: partial unique indexes ``one_active_bed`` / ``one_active_resident`` (one allotted /
checked-in allocation per bed and per enrolment) and ``one_active_quarter`` (one open quarter allocation);
``hostel_roll_calls UNIQUE (hostel_id, on_date)``, ``mess_attendance UNIQUE (subscription, on_date, meal)``,
``mess_bills UNIQUE (subscription, month)``, ``hostel_applications UNIQUE (enrolment, academic_year)``.
``hostels.mess_id`` → ``mess_plans`` is added by ``ALTER TABLE`` in the DDL (circular reference).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class Hostel(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostels"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "name"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    hostel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    warden_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    mess_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mess_plans.id", ondelete="SET NULL", use_alter=True, name="fk_hostels_mess")
    )
    rules_template_id: Mapped[uuid.UUID | None] = _uuid()
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = _uuid()


class HostelBlock(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_blocks"
    __table_args__ = (UniqueConstraint("hostel_id", "name"),)

    hostel_id: Mapped[uuid.UUID] = _fk("hostels.id", "CASCADE", nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    floors: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)


class HostelRoom(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_rooms"
    __table_args__ = (UniqueConstraint("block_id", "room_number"),)

    block_id: Mapped[uuid.UUID] = _fk("hostel_blocks.id", "CASCADE", nullable=False)
    room_number: Mapped[str] = mapped_column(String(20), nullable=False)
    floor: Mapped[int | None] = mapped_column(SmallInteger)
    capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    room_type: Mapped[str] = mapped_column(String(20), nullable=False, default="double")
    has_ac: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    amenities: Mapped[Any | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class HostelBed(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_beds"
    __table_args__ = (UniqueConstraint("room_id", "bed_label"),)

    room_id: Mapped[uuid.UUID] = _fk("hostel_rooms.id", "CASCADE", nullable=False)
    bed_label: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="vacant")


class HostelFeePlan(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_fee_plans"
    __table_args__ = (UniqueConstraint("hostel_id", "room_type", "academic_year_id"),)

    hostel_id: Mapped[uuid.UUID] = _fk("hostels.id", "CASCADE", nullable=False)
    room_type: Mapped[str] = mapped_column(String(20), nullable=False)
    academic_year_id: Mapped[uuid.UUID] = _fk("academic_years.id", nullable=False)
    fee_per_term_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    caution_deposit_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mess_advance_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class HostelApplication(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_applications"
    __table_args__ = (UniqueConstraint("student_program_enrollment_id", "academic_year_id"),)

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    academic_year_id: Mapped[uuid.UUID] = _fk("academic_years.id", nullable=False)
    hostel_preference: Mapped[list[str] | None] = mapped_column(JSONB)
    room_type_pref: Mapped[str | None] = mapped_column(String(20))
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    priority_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="applied")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


ACTIVE_ALLOCATION = text("status IN ('allotted','checked_in')")


class HostelAllocation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_allocations"
    __table_args__ = (
        Index("one_active_bed", "bed_id", unique=True, postgresql_where=ACTIVE_ALLOCATION),
        Index("one_active_resident", "student_program_enrollment_id", unique=True, postgresql_where=ACTIVE_ALLOCATION),
    )

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    bed_id: Mapped[uuid.UUID] = _fk("hostel_beds.id", nullable=False)
    hostel_id: Mapped[uuid.UUID] = _fk("hostels.id", nullable=False)
    academic_year_id: Mapped[uuid.UUID] = _fk("academic_years.id", nullable=False)
    from_on: Mapped[date] = mapped_column(Date, nullable=False)
    to_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="allotted")
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    caution_deposit_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    room_condition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class RoomChangeRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "room_change_requests"

    allocation_id: Mapped[uuid.UUID] = _fk("hostel_allocations.id", "CASCADE", nullable=False)
    requested_bed_id: Mapped[uuid.UUID | None] = _fk("hostel_beds.id")
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    decided_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class HostelRollCall(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_roll_calls"
    __table_args__ = (UniqueConstraint("hostel_id", "on_date"),)

    hostel_id: Mapped[uuid.UUID] = _fk("hostels.id", "CASCADE", nullable=False)
    on_date: Mapped[date] = mapped_column(Date, nullable=False)
    taken_by: Mapped[uuid.UUID | None] = _uuid()
    taken_at: Mapped[datetime] = _now()


class HostelRollCallEntry(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_roll_call_entries"
    __table_args__ = (UniqueConstraint("roll_call_id", "allocation_id"),)

    roll_call_id: Mapped[uuid.UUID] = _fk("hostel_roll_calls.id", "CASCADE", nullable=False)
    allocation_id: Mapped[uuid.UUID] = _fk("hostel_allocations.id", "CASCADE", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class MessPlan(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "mess_plans"

    hostel_id: Mapped[uuid.UUID | None] = _fk("hostels.id", "CASCADE")
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    diet: Mapped[str] = mapped_column(String(20), nullable=False, default="veg")
    monthly_fee_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    menu: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class MessSubscription(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "mess_subscriptions"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    mess_plan_id: Mapped[uuid.UUID] = _fk("mess_plans.id", nullable=False)
    from_on: Mapped[date] = mapped_column(Date, nullable=False)
    to_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class MessAttendance(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "mess_attendance"
    __table_args__ = (UniqueConstraint("mess_subscription_id", "on_date", "meal"),)

    mess_subscription_id: Mapped[uuid.UUID] = _fk("mess_subscriptions.id", "CASCADE", nullable=False)
    on_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="taken")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")


class MessBill(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "mess_bills"
    __table_args__ = (UniqueConstraint("mess_subscription_id", "month"),)

    mess_subscription_id: Mapped[uuid.UUID] = _fk("mess_subscriptions.id", "CASCADE", nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    days_billed: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rebate_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    created_at: Mapped[datetime] = _now()


class HostelVisitor(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_visitors"

    hostel_id: Mapped[uuid.UUID] = _fk("hostels.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", nullable=False)
    visitor_name: Mapped[str] = mapped_column(String(160), nullable=False)
    relation: Mapped[str | None] = mapped_column(String(40))
    phone: Mapped[str | None] = mapped_column(String(20))
    id_proof_type: Mapped[str | None] = mapped_column(String(30))
    id_proof_no: Mapped[str | None] = mapped_column(String(40))
    in_at: Mapped[datetime] = _now()
    out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = _uuid()


class HostelLeave(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_leaves"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    hostel_id: Mapped[uuid.UUID] = _fk("hostels.id", nullable=False)
    leave_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    to_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    destination: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    guardian_consent: Mapped[str] = mapped_column(String(20), nullable=False, default="not_required")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    actual_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_return_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late_minutes: Mapped[int | None] = mapped_column(Integer)
    qr_token: Mapped[str | None] = mapped_column(String(64))
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class HostelComplaint(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_complaints"

    hostel_id: Mapped[uuid.UUID] = _fk("hostels.id", "CASCADE", nullable=False)
    room_id: Mapped[uuid.UUID | None] = _fk("hostel_rooms.id")
    student_program_enrollment_id: Mapped[uuid.UUID | None] = _fk("student_program_enrollments.id")
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    service_request_id: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HostelDisciplinaryRecord(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "hostel_disciplinary_records"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    hostel_id: Mapped[uuid.UUID] = _fk("hostels.id", nullable=False)
    incident_on: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    fine_paise: Mapped[int | None] = mapped_column(Integer)
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    decided_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()


class StaffQuarter(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "staff_quarters"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "unit_code"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", nullable=False)
    unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    quarter_type: Mapped[str | None] = mapped_column(String(20))
    rent_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="vacant")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class StaffQuarterAllocation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "staff_quarter_allocations"
    __table_args__ = (Index("one_active_quarter", "quarter_id", unique=True, postgresql_where=text("to_on IS NULL")),)

    quarter_id: Mapped[uuid.UUID] = _fk("staff_quarters.id", "CASCADE", nullable=False)
    staff_id: Mapped[uuid.UUID] = _fk("staff.id", nullable=False)
    from_on: Mapped[date] = mapped_column(Date, nullable=False)
    to_on: Mapped[date | None] = mapped_column(Date)
    rent_deduction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
