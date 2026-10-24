"""Transport enums — Prompts/21 §21.3 (values from the section 20 column comments)."""

from enum import StrEnum


class VehicleType(StrEnum):
    BUS = "bus"
    MINIBUS = "minibus"
    VAN = "van"
    CAR = "car"


class VehicleStatus(StrEnum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"


class PersonType(StrEnum):
    STUDENT = "student"
    STAFF = "staff"


class AllocationStatus(StrEnum):
    PENDING = "pending"  # self-service request awaiting the manager (simple status, no workflow)
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    REJECTED = "rejected"


class TripDirection(StrEnum):
    PICKUP = "pickup"
    DROP = "drop"


class TripStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PassengerEvent(StrEnum):
    BOARD = "board"
    ALIGHT = "alight"


DOCUMENTS = ("insurance", "fitness", "permit", "puc")
BLOCKING_DOCUMENTS = ("insurance", "fitness", "permit")
LIVE_ALLOCATION = ("active", "suspended")
GEOFENCE_M = 100
DEVIATION_M = 500
DEVIATION_PINGS = 3
DELAY_ALERT_MIN = 15
GPS_RETENTION_DAYS = 90
