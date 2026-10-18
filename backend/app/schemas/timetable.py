"""Timetable & rooms schemas — Prompts/10 §10.4 (buildings, rooms, slot groups, timetables + entries, conflict
reports, publish, weekly views, substitutions, class sessions, auto-generation, iCal tokens)."""

import uuid
from datetime import date, datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums.timetable import RoomType, SessionStatus, SessionType, SlotType, TimetableScope, WeekPattern

DateT = date  # fields named ``date`` shadow the type inside their class body


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- buildings / rooms ---------------------------------------------------------------------------------------------
class BuildingIn(_Strict):
    college_id: uuid.UUID | None = Field(default=None, description="defaults to the caller's college")
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    address: dict[str, Any] | None = None
    floors: int | None = Field(default=None, ge=0, le=200)
    is_active: bool = True


class BuildingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    college_id: uuid.UUID
    code: str
    name: str
    address: dict[str, Any] | None = None
    floors: int | None = None
    is_active: bool
    rooms_count: int = 0


class RoomIn(_Strict):
    college_id: uuid.UUID | None = None
    building_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    room_type: RoomType = RoomType.CLASSROOM
    floor: int | None = Field(default=None, ge=-5, le=200)
    capacity: int = Field(default=0, ge=0, le=5000)
    exam_capacity: int | None = Field(default=None, ge=0, le=5000)
    features: list[str] = Field(default_factory=list, description="tags the solver matches (projector, ac, lab:cse …)")
    is_bookable: bool = True
    is_active: bool = True
    department_id: uuid.UUID | None = Field(
        default=None, description="department lab — a HOD may only edit labs tagged with its department"
    )

    @model_validator(mode="after")
    def _exam(self) -> "RoomIn":
        if self.exam_capacity is not None and self.exam_capacity > self.capacity:
            raise ValueError("exam_capacity must not exceed capacity")
        return self


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    college_id: uuid.UUID
    building_id: uuid.UUID | None = None
    building_code: str | None = None
    code: str
    name: str
    room_type: str
    floor: int | None = None
    capacity: int
    exam_capacity: int | None = None
    features: list[str] = Field(default_factory=list)
    is_bookable: bool
    is_active: bool
    version: int = 1


class RoomAvailability(BaseModel):
    room: RoomOut
    free: bool
    busy_with: list[str] = Field(default_factory=list, description="course codes / sessions occupying the room")


# ---- slots -----------------------------------------------------------------------------------------------------------
class SlotIn(_Strict):
    name: str = Field(min_length=1, max_length=20)
    start_time: time
    end_time: time
    slot_type: SlotType = SlotType.LECTURE

    @model_validator(mode="after")
    def _order(self) -> "SlotIn":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class SlotGroupReplace(_Strict):
    college_id: uuid.UUID | None = None
    slot_group: str = Field(default="Default", min_length=1, max_length=40)
    slots: list[SlotIn] = Field(min_length=1, max_length=20)


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    college_id: uuid.UUID
    slot_group: str
    name: str
    sequence: int
    start_time: time
    end_time: time
    slot_type: str
    is_active: bool


# ---- timetables / entries --------------------------------------------------------------------------------------------
class TimetableCreate(_Strict):
    term_id: uuid.UUID
    scope_type: TimetableScope
    scope_id: uuid.UUID
    name: str | None = Field(default=None, max_length=120)
    base_version_id: uuid.UUID | None = Field(default=None, description="clone this version's entries")


class EntryCreate(_Strict):
    offering_id: uuid.UUID
    section_id: uuid.UUID | None = None
    day_of_week: int = Field(ge=1, le=7, description="ISO weekday, 1 = Monday")
    time_slot_id: uuid.UUID
    room_id: uuid.UUID | None = None
    staff_id: uuid.UUID | None = None
    session_type: SessionType = SessionType.LECTURE
    week_pattern: WeekPattern = WeekPattern.ALL
    slot_span: int = Field(default=1, ge=1, le=4)


class EntryUpdate(_Strict):
    section_id: uuid.UUID | None = None
    day_of_week: int | None = Field(default=None, ge=1, le=7)
    time_slot_id: uuid.UUID | None = None
    room_id: uuid.UUID | None = None
    staff_id: uuid.UUID | None = None
    session_type: SessionType | None = None
    week_pattern: WeekPattern | None = None
    slot_span: int | None = Field(default=None, ge=1, le=4)


class ConflictItem(BaseModel):
    kind: str  # room | staff | section | capacity | workload
    message: str
    entry_id: uuid.UUID | None = None
    timetable_id: uuid.UUID | None = None
    day_of_week: int | None = None
    slot_name: str | None = None
    course_code: str | None = None


class ConflictReport(BaseModel):
    room: list[ConflictItem] = Field(default_factory=list)
    staff: list[ConflictItem] = Field(default_factory=list)
    section: list[ConflictItem] = Field(default_factory=list)
    capacity: list[ConflictItem] = Field(default_factory=list)
    workload: list[ConflictItem] = Field(default_factory=list)

    @property
    def hard(self) -> bool:
        return bool(self.room or self.staff or self.section)


class EntryOut(BaseModel):
    id: uuid.UUID
    timetable_id: uuid.UUID
    term_id: uuid.UUID
    offering_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    section_id: uuid.UUID | None = None
    section_name: str | None = None
    day_of_week: int
    time_slot_id: uuid.UUID
    slot_name: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    room_id: uuid.UUID | None = None
    room_code: str | None = None
    staff_id: uuid.UUID | None = None
    staff_name: str | None = None
    session_type: str
    week_pattern: str
    slot_span: int
    is_active: bool


class EntryResult(BaseModel):
    entry: EntryOut
    warnings: ConflictReport


class TimetableResponse(BaseModel):
    id: uuid.UUID
    college_id: uuid.UUID
    term_id: uuid.UUID
    term_name: str | None = None
    scope_type: str
    scope_id: uuid.UUID
    scope_label: str | None = None
    name: str | None = None
    version: int
    status: str
    effective_from: date | None = None
    published_at: datetime | None = None
    entries_count: int = 0
    entries: list[EntryOut] = Field(default_factory=list)
    can_edit: bool = False


class PublishRequest(_Strict):
    effective_from: date | None = Field(default=None, description="defaults to today (institution-local)")
    regenerate_sessions: bool = True


class PublishSummary(BaseModel):
    timetable: TimetableResponse
    sessions_created: int = 0
    sessions_removed: int = 0
    sessions_preserved: int = 0
    archived_version_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None


# ---- weekly views ---------------------------------------------------------------------------------------------------
class ViewSlot(BaseModel):
    slot_id: uuid.UUID
    name: str
    start_time: time
    end_time: time
    slot_type: str
    entries: list[EntryOut] = Field(default_factory=list)


class ViewDay(BaseModel):
    day_of_week: int
    label: str
    date: DateT | None = None
    slots: list[ViewSlot] = Field(default_factory=list)


class WeeklyView(BaseModel):
    scope: str
    scope_id: uuid.UUID | None = None
    label: str | None = None
    week_start: date | None = None
    iso_week: int | None = None
    days: list[ViewDay] = Field(default_factory=list)
    sessions: list["ClassSessionResponse"] = Field(default_factory=list)


# ---- substitutions ---------------------------------------------------------------------------------------------------
class SubstitutionCreate(_Strict):
    entry_id: uuid.UUID
    on_date: date
    substitute_staff_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)


class SubstitutionDecision(_Strict):
    substitute_staff_id: uuid.UUID | None = None
    comment: str | None = Field(default=None, max_length=1000)


class SubstitutionResponse(BaseModel):
    id: uuid.UUID
    timetable_entry_id: uuid.UUID
    on_date: date
    course_code: str | None = None
    slot_name: str | None = None
    section_name: str | None = None
    staff_id: uuid.UUID | None = None
    staff_name: str | None = None
    substitute_staff_id: uuid.UUID | None = None
    substitute_name: str | None = None
    reason: str | None = None
    source: str
    status: str
    leave_id: uuid.UUID | None = None
    approved_by: uuid.UUID | None = None
    created_at: datetime | None = None


class SubstituteCandidate(BaseModel):
    staff_id: uuid.UUID
    name: str
    department_id: uuid.UUID | None = None
    free: bool
    on_leave: bool = False
    teaches_offering: bool = False


# ---- sessions --------------------------------------------------------------------------------------------------------
class ClassSessionResponse(BaseModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    timetable_entry_id: uuid.UUID | None = None
    session_date: date
    time_slot_id: uuid.UUID | None = None
    slot_name: str | None = None
    start_time: time
    end_time: time
    staff_id: uuid.UUID | None = None
    staff_name: str | None = None
    room_id: uuid.UUID | None = None
    room_code: str | None = None
    section_name: str | None = None
    session_type: str
    topic: str | None = None
    online_link: str | None = None
    status: str
    attendance_status: str
    substituted: bool = False


class ExtraSessionCreate(_Strict):
    offering_id: uuid.UUID
    date: DateT
    start: time
    end: time
    room_id: uuid.UUID | None = None
    staff_id: uuid.UUID | None = None
    session_type: SessionType = SessionType.LECTURE
    topic: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _order(self) -> "ExtraSessionCreate":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class SessionUpdate(_Strict):
    status: SessionStatus | None = None
    topic: str | None = Field(default=None, max_length=255)
    room_id: uuid.UUID | None = None
    online_link: str | None = Field(default=None, max_length=1000)


class SessionCancel(_Strict):
    reason: str | None = Field(default=None, max_length=500)


class SessionReschedule(_Strict):
    date: DateT
    start: time
    end: time
    room_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _order(self) -> "SessionReschedule":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


# ---- auto-generate / iCal ---------------------------------------------------------------------------------------------
class AutoGenerateRequest(_Strict):
    slot_group: str = "Default"
    days: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5], description="ISO weekdays to fill")
    max_consecutive: int = Field(default=3, ge=1, le=8)
    spread: bool = Field(default=True, description="prefer one session of an offering per day")
    respect_room_type: bool = True


class ICalToken(BaseModel):
    token: str | None = Field(default=None, description="shown once — store it")
    url: str | None = None
    created_at: datetime | None = None
    revoked: bool = False


class SectionFeed(BaseModel):
    section_id: uuid.UUID
    url: str


WeeklyView.model_rebuild()
