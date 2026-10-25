"""Event schemas — Prompts/25 §25.4 (OpenAPI names prefixed ``Event`` / ``Campus`` to stay unique)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


EventTypeLit = Literal[
    "conference",
    "seminar",
    "workshop",
    "fdp",
    "guest_lecture",
    "cultural",
    "sports",
    "outreach",
    "exhibition",
    "alumni",
    "convocation",
    "other",
]


class EventRegistrationSettings(_Strict):
    open: bool = False
    fee_paise: int = Field(0, ge=0)
    capacity: int | None = Field(None, ge=1)
    audience: Literal["institution", "college", "department", "public"] = "institution"
    waitlist: bool = True
    closes_on: date | None = None


class EventCreate(_Strict):
    event_type: EventTypeLit
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(None, max_length=8000)
    college_id: uuid.UUID | None = None
    organiser_department_id: uuid.UUID | None = None
    from_on: date
    to_on: date
    venue_room_id: uuid.UUID | None = None
    venue_text: str | None = Field(None, max_length=200)
    budget_paise: int = Field(0, ge=0)
    budget_head_id: uuid.UUID | None = None
    sponsor: dict[str, Any] | None = None
    registration: EventRegistrationSettings = EventRegistrationSettings()
    naac_criterion: str | None = Field(None, max_length=10)
    club_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _dates(self) -> "EventCreate":
        if self.to_on < self.from_on:
            raise ValueError("to_on must not be before from_on")
        return self


class EventUpdate(_Strict):
    title: str | None = Field(None, min_length=3, max_length=200)
    description: str | None = Field(None, max_length=8000)
    from_on: date | None = None
    to_on: date | None = None
    venue_room_id: uuid.UUID | None = None
    venue_text: str | None = Field(None, max_length=200)
    budget_paise: int | None = Field(None, ge=0)
    budget_head_id: uuid.UUID | None = None
    sponsor: dict[str, Any] | None = None
    registration: EventRegistrationSettings | None = None
    naac_criterion: str | None = Field(None, max_length=10)


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    college_id: uuid.UUID | None = None
    event_type: str
    title: str
    description: str | None = None
    organiser_department_id: uuid.UUID | None = None
    organiser_staff_id: uuid.UUID | None = None
    from_on: date
    to_on: date
    venue_room_id: uuid.UUID | None = None
    venue_text: str | None = None
    venue_label: str | None = None
    budget_paise: int | None = None
    sponsor: dict[str, Any] | None = None
    participants_count: int | None = None
    external_participants_count: int | None = None
    report_url: str | None = None
    images: list[Any] | None = None
    naac_criterion: str | None = None
    registration_fee_paise: int | None = None
    status: str
    workflow_instance_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    registration: dict[str, Any] = {}
    workflow: dict[str, Any] = {}
    counts: dict[str, int] = {}
    budget: dict[str, Any] = {}
    venue_booking_id: uuid.UUID | None = None
    is_organiser: bool = False
    my_registration: dict[str, Any] | None = None


class EventAction(_Strict):
    action: Literal["submit", "approve", "reject", "schedule", "complete", "cancel"]
    remarks: str | None = Field(None, max_length=500)


class EventExternalPerson(_Strict):
    name: str = Field(min_length=2, max_length=200)
    email: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=20)
    organisation: str | None = Field(None, max_length=200)


class EventRegister(_Strict):
    person_type: Literal["student", "staff", "external"] = "student"
    external: EventExternalPerson | None = None


class EventRegistrationOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    person_type: str
    person_id: uuid.UUID | None = None
    name: str | None = None
    external: dict[str, Any] | None = None
    fee_invoice_id: uuid.UUID | None = None
    fee_status: str | None = None
    attended: bool
    waitlisted: bool = False
    qr_token: str | None = None
    certificate_document_id: uuid.UUID | None = None
    certificate_url: str | None = None
    registered_at: datetime


class EventAttendanceMark(_Strict):
    registration_ids: list[uuid.UUID] = []
    qr: str | None = Field(None, max_length=120)
    attended: bool = True


class EventCertificateRequest(_Strict):
    template_id: uuid.UUID | None = None
    only_attended: bool = True


class EventReportIn(_Strict):
    participants: int | None = Field(None, ge=0)
    external: int | None = Field(None, ge=0)
    images: list[str] = []
    report_url: str | None = None
    outcomes: str | None = Field(None, max_length=8000)
    naac_criterion: str | None = Field(None, max_length=10)


class EventReport(BaseModel):
    event_id: uuid.UUID
    participants: int
    external: int
    registered: int
    attended: int
    certificates: int
    budget_paise: int
    spend_paise: int
    images: list[Any] = []
    report_url: str | None = None
    outcomes: str | None = None
    naac_criterion: str | None = None


class EventPublicOut(BaseModel):
    id: uuid.UUID
    title: str
    event_type: str
    from_on: date
    to_on: date
    venue: str | None = None
    registration_open: bool
    fee_paise: int = 0


class EventJobAccepted(BaseModel):
    job_id: uuid.UUID
