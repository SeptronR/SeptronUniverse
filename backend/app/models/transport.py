"""Transport — section 20 of Database_Schema.sql (Prompts/21 §21.3).

DDL notes the services rely on: ``vehicles UNIQUE (institution_id, registration_no)``, ``transport_routes UNIQUE
(institution_id, code)``, ``transport_stops UNIQUE (route_id, sequence)`` (reorder renumbers through negative
sequences), ``gps_devices.token_hash UNIQUE``; ``vehicles.gps_device_id`` → ``gps_devices`` is added by ``ALTER TABLE``
(circular reference). ``vehicle_gps_logs`` is range-partitioned on ``recorded_at`` (PK ``(id, recorded_at)``, no FKs,
insert-only; monthly partitions ``vehicle_gps_logs_yYYYYmMM`` are created by Beat, the DEFAULT partition catches the
rest). ``transport_allocations.person_id`` is ``students.id`` or ``staff.id`` by ``person_type``.
"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


class Vehicle(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("institution_id", "registration_no"),)

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    registration_no: Mapped[str] = mapped_column(String(20), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(20), nullable=False, default="bus")
    capacity: Mapped[int | None] = mapped_column(SmallInteger)
    make_model: Mapped[str | None] = mapped_column(String(80))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    driver_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    insurance_expiry: Mapped[date | None] = mapped_column(Date)
    fitness_expiry: Mapped[date | None] = mapped_column(Date)
    permit_expiry: Mapped[date | None] = mapped_column(Date)
    puc_expiry: Mapped[date | None] = mapped_column(Date)
    gps_device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gps_devices.id", ondelete="SET NULL", use_alter=True, name="fk_vehicles_gps_device"),
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class TransportRoute(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "transport_routes"
    __table_args__ = (UniqueConstraint("institution_id", "code"),)

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vehicle_id: Mapped[uuid.UUID | None] = _fk("vehicles.id")
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    fee_paise: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class TransportStop(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "transport_stops"
    __table_args__ = (UniqueConstraint("route_id", "sequence"),)

    route_id: Mapped[uuid.UUID] = _fk("transport_routes.id", "CASCADE", nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    pickup_time: Mapped[time | None] = mapped_column(Time)
    drop_time: Mapped[time | None] = mapped_column(Time)
    fee_paise: Mapped[int | None] = mapped_column(Integer)


class TransportAllocation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "transport_allocations"

    person_type: Mapped[str] = mapped_column(String(10), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    route_id: Mapped[uuid.UUID] = _fk("transport_routes.id", nullable=False)
    stop_id: Mapped[uuid.UUID | None] = _fk("transport_stops.id")
    academic_year_id: Mapped[uuid.UUID | None] = _fk("academic_years.id")
    from_on: Mapped[date | None] = mapped_column(Date)
    to_on: Mapped[date | None] = mapped_column(Date)
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class VehicleMaintenance(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "vehicle_maintenance"

    vehicle_id: Mapped[uuid.UUID] = _fk("vehicles.id", "CASCADE", nullable=False)
    maintenance_type: Mapped[str | None] = mapped_column(String(40))
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    odometer: Mapped[int | None] = mapped_column(Integer)
    cost_paise: Mapped[int | None] = mapped_column(Integer)
    vendor: Mapped[str | None] = mapped_column(String(120))
    next_due_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class VehicleFuelLog(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "vehicle_fuel_log"

    vehicle_id: Mapped[uuid.UUID] = _fk("vehicles.id", "CASCADE", nullable=False)
    filled_on: Mapped[date] = mapped_column(Date, nullable=False)
    litres: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    cost_paise: Mapped[int | None] = mapped_column(Integer)
    odometer: Mapped[int | None] = mapped_column(Integer)
    filled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _now()


class GpsDevice(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "gps_devices"
    __table_args__ = (UniqueConstraint("institution_id", "device_id"),)

    device_id: Mapped[str] = mapped_column(String(60), nullable=False)
    vehicle_id: Mapped[uuid.UUID | None] = _fk("vehicles.id")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class TransportTrip(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "transport_trips"

    route_id: Mapped[uuid.UUID] = _fk("transport_routes.id", nullable=False)
    vehicle_id: Mapped[uuid.UUID] = _fk("vehicles.id", nullable=False)
    driver_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    trip_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = _now()


class VehicleGpsLog(Base):
    """Partitioned, insert-only; no FKs (the DDL keeps the partition parent free of references)."""

    __tablename__ = "vehicle_gps_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lat: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    lng: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    speed_kmh: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    heading: Mapped[int | None] = mapped_column(SmallInteger)


class TripStopEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "trip_stop_events"

    trip_id: Mapped[uuid.UUID] = _fk("transport_trips.id", "CASCADE", nullable=False)
    stop_id: Mapped[uuid.UUID] = _fk("transport_stops.id", nullable=False)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TripPassengerEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "trip_passenger_events"

    trip_id: Mapped[uuid.UUID] = _fk("transport_trips.id", "CASCADE", nullable=False)
    person_type: Mapped[str] = mapped_column(String(10), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event: Mapped[str] = mapped_column(String(10), nullable=False)
    stop_id: Mapped[uuid.UUID | None] = _fk("transport_stops.id")
    occurred_at: Mapped[datetime] = _now()
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="app")
