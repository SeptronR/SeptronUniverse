"""Timetables, entries, conflicts, publication and weekly views — Prompts/10 §10.6 ``timetable_service.py``.

1. **Drafts per scope** (section / batch / department of a term): version = last + 1 under a ``FOR UPDATE`` lock of
   the scope's versions; ``base_version_id`` (or ``POST /clone``) copies that version's entries. Writers: HOD for its
   departments' scopes, ``college_admin`` for its college, registrar / ``timetable:manage`` everywhere.
2. **Entries reference offerings** (Phase 09): only ``open | closed | in_progress`` offerings of the same term (409
   ``OFFERING_NOT_SCHEDULABLE``); the staff member must hold a ``course_offering_faculty`` row of the offering (any
   role — TAs included; 422); a section must be targeted by the offering (``course_offering_targets`` — the section
   itself or its whole batch; 422); a section-scope timetable defaults the entry's section to the scope.
3. **Conflicts** — an explicit pre-check before every write: entries of this draft plus the live (published) entries
   of every other scope that share the weekday and overlap in time (``slot_span`` expanded from the slot group, so
   different slot groups compare by clock time) with a clashing week pattern (``all`` × anything, ``odd`` × ``odd``)
   for the same room, staff member or section → ``ConflictReport``; a hard clash answers 409 ``CONFLICT`` with the
   report in ``details``. The rows checked are locked ``FOR UPDATE``. Warnings: ``capacity`` (room smaller than the
   offering roster / section size) and ``workload`` (scheduled weekly hours of the staff member on the offering above
   its ``course_offering_faculty.hours_per_week`` — 409 ``WORKLOAD_EXCEEDED`` when ``hr.workload_enforce=block``).
   The partial unique indexes ``uq_tt_*`` are the last line of defence at publish.
4. **Publish** (``effective_from`` default today, institution-local): no hard conflicts; the previous published
   version → ``archived`` and its entries switched off, this version's entries switched on (the unique indexes now
   guard them); **sessions**: for each entry × each date in ``[effective_from, term end]`` on its weekday, skipping
   holidays (college / institution, ``applies_to`` all | students) and honouring ``week_pattern`` (odd / even ISO
   weeks) and ``slot_span`` (start of the first slot → end of the last); ``conducted`` / attendance-taken sessions are
   preserved, future ``scheduled`` sessions of the replaced version are removed. Above ``GENERATE_INLINE_LIMIT``
   sessions the generation runs as the ``timetable.generate_sessions`` job. Emits ``timetable.published``.
5. **Views**: ``weekly(scope, id, week)`` for section / batch / department / faculty / room and ``me`` (faculty by
   staff row; student by the latest term-record section + confirmed offerings; parent per ward).
6. **iCal**: per-user token (hash in ``calendar_feed_tokens``; one live token per user, a new one revokes the old);
   ``/timetables/ical/{token}.ics`` lists the next 30 days of the user's sessions; section feeds use a signed link.
"""

import hashlib
import secrets
import uuid
from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.errors import APIError, ErrorCode
from app.enums.timetable import DAY_NAMES, SCHEDULABLE_OFFERING_STATUSES
from app.models.academic import AcademicTerm, Batch, BatchSection
from app.models.hr import Staff
from app.models.offerings import CourseOffering, CourseOfferingFaculty, CourseOfferingTarget
from app.models.platform import Department, Holiday
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.models.timetable import CalendarFeedToken, ClassSession, TimeSlot, Timetable, TimetableEntry
from app.repositories.timetable_repository import clashing_patterns
from app.repositories.timetable_scope import (
    confirmed_offering_ids,
    entry_predicate,
    is_staff,
    session_predicate,
)
from app.schemas.timetable import (
    ConflictItem,
    ConflictReport,
    EntryCreate,
    EntryResult,
    EntryUpdate,
    ICalToken,
    PublishRequest,
    PublishSummary,
    SectionFeed,
    TimetableCreate,
    TimetableResponse,
    ViewDay,
    ViewSlot,
    WeeklyView,
)
from app.services.students.common import snap
from app.services.timetable.common import TT, TimetableBase, matches_week, minutes, now_utc, rule, week_start
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta

GENERATE_INLINE_LIMIT = 3000
ENTRY_KEYS = (
    "offering_id",
    "section_id",
    "day_of_week",
    "time_slot_id",
    "room_id",
    "staff_id",
    "session_type",
    "week_pattern",
    "slot_span",
)
Progress = Callable[[int, str], Any]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class _Cand:
    """An entry being checked (new or updated) with its resolved clock window."""

    offering_id: uuid.UUID
    section_id: uuid.UUID | None
    day_of_week: int
    time_slot_id: uuid.UUID
    room_id: uuid.UUID | None
    staff_id: uuid.UUID | None
    week_pattern: str

    def __init__(self, data: dict[str, Any], start: time, end: time, slot_name: str):
        self.offering_id, self.section_id = data["offering_id"], data.get("section_id")
        self.day_of_week, self.time_slot_id = int(data["day_of_week"]), data["time_slot_id"]
        self.room_id, self.staff_id = data.get("room_id"), data.get("staff_id")
        self.week_pattern = str(data.get("week_pattern") or "all")
        self.start, self.end, self.slot_name = start, end, slot_name


class TimetableService(TimetableBase):
    # ---- reads -----------------------------------------------------------------------------------------------------
    async def responses(self, rows: Sequence[Timetable], *, with_entries: bool = False) -> list[TimetableResponse]:
        rows = list(rows)
        counts = await self.tts.entry_counts([t.id for t in rows])
        terms = await self._rows(AcademicTerm, [t.term_id for t in rows])
        labels = await self._scope_labels(rows)
        out = []
        for t in rows:
            item = TimetableResponse(
                id=t.id,
                college_id=t.college_id,
                term_id=t.term_id,
                term_name=terms[t.term_id].name if t.term_id in terms else None,
                scope_type=t.scope_type,
                scope_id=t.scope_id,
                scope_label=labels.get(t.scope_id),
                name=t.name,
                version=t.version,
                status=t.status,
                effective_from=t.effective_from,
                published_at=t.published_at,
                entries_count=counts.get(t.id, 0),
                can_edit=t.status == "draft" and await self.can_edit(t),
            )
            if with_entries:
                entries = await self.tts.entries([t.id])
                item.entries = await self.entry_outs(entries)
            out.append(item)
        return out

    async def _scope_labels(self, rows: Sequence[Timetable]) -> dict[uuid.UUID, str]:
        sections = await self._rows(BatchSection, [t.scope_id for t in rows if t.scope_type == "section"])
        batches = await self._rows(
            Batch, [t.scope_id for t in rows if t.scope_type == "batch"] + [s.batch_id for s in sections.values()]
        )
        depts = await self._rows(Department, [t.scope_id for t in rows if t.scope_type == "department"])
        out: dict[uuid.UUID, str] = {}
        for sid, s in sections.items():
            b = batches.get(s.batch_id)
            out[sid] = f"{b.code if b else '?'} / {s.name}"
        for bid, b in batches.items():
            out.setdefault(bid, b.code)
        for did, d in depts.items():
            out[did] = d.code
        return out

    async def list_page(self, params: PageParams, **filters: Any) -> tuple[list[TimetableResponse], PaginationMeta]:
        stmt = self.tts.filtered(**filters)
        if not params.sort:
            stmt = stmt.order_by(Timetable.scope_type, Timetable.scope_id, Timetable.version.desc())
        rows, page = await self.tts.paginate(stmt, params)
        return await self.responses(rows), page

    async def get(self, timetable_id: uuid.UUID) -> TimetableResponse:
        return (await self.responses([await self.tts.get_one(timetable_id)], with_entries=True))[0]

    # ---- rule 1: drafts -----------------------------------------------------------------------------------------
    async def _scope_college(self, scope_type: str, scope_id: uuid.UUID) -> uuid.UUID:
        if scope_type == "department":
            d = (await self._rows(Department, [scope_id])).get(scope_id)
            if d is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Department not found", {"field": "scope_id"})
            college: uuid.UUID = d.college_id
            return college
        batch_id = scope_id
        if scope_type == "section":
            sec = (await self._rows(BatchSection, [scope_id])).get(scope_id)
            if sec is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Section not found", {"field": "scope_id"})
            batch_id = sec.batch_id
        b = (await self._rows(Batch, [batch_id])).get(batch_id)
        if b is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Batch not found", {"field": "scope_id"})
        college_id: uuid.UUID = b.college_id
        return college_id

    async def create(self, body: TimetableCreate) -> TimetableResponse:
        term = await self.get_term(body.term_id)
        college_id = await self._scope_college(body.scope_type.value, body.scope_id)
        probe = Timetable(
            institution_id=self.inst,
            college_id=college_id,
            term_id=term.id,
            scope_type=body.scope_type.value,
            scope_id=body.scope_id,
        )
        await self.assert_edit(probe)
        versions = await self.tts.lock_scope(term.id, body.scope_type.value, body.scope_id)
        base: Timetable | None = None
        if body.base_version_id:
            base = next((v for v in versions if v.id == body.base_version_id), None)
            if base is None:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "base_version_id is not a version of this scope",
                    {"field": "base_version_id"},
                )
        tt = Timetable(
            institution_id=self.inst,
            college_id=college_id,
            term_id=term.id,
            scope_type=body.scope_type.value,
            scope_id=body.scope_id,
            name=body.name or (base.name if base else None),
            version=(max((v.version for v in versions), default=0) + 1),
            status="draft",
            created_by=self.actor_id,
        )
        self.db.add(tt)
        await self.db.flush()
        if base is not None:
            for e in await self.tts.entries([base.id]):
                self.db.add(
                    TimetableEntry(
                        institution_id=self.inst,
                        timetable_id=tt.id,
                        term_id=e.term_id,
                        is_active=False,
                        **{k: getattr(e, k) for k in ENTRY_KEYS},
                    )
                )
            await self.db.flush()
        await self._audit(
            "create",
            "timetable",
            tt.id,
            None,
            {"scope_type": tt.scope_type, "scope_id": str(tt.scope_id), "version": tt.version},
        )
        return await self.get(tt.id)

    async def clone(self, timetable_id: uuid.UUID) -> TimetableResponse:
        src = await self.tts.get_one(timetable_id)
        return await self.create(
            TimetableCreate(
                term_id=src.term_id,
                scope_type=src.scope_type,  # type: ignore[arg-type]
                scope_id=src.scope_id,
                name=src.name,
                base_version_id=src.id,
            )
        )

    async def _draft(self, timetable_id: uuid.UUID) -> Timetable:
        tt = await self.tts.get_one(timetable_id, for_update=True)
        await self.assert_edit(tt)
        if tt.status != "draft":
            raise APIError(
                409,
                ErrorCode.RECORD_LOCKED,
                f"A {tt.status} timetable cannot be edited — clone it into a new draft version",
                {"status": tt.status},
            )
        return tt

    async def delete(self, timetable_id: uuid.UUID) -> None:
        tt = await self._draft(timetable_id)
        await self.db.delete(tt)
        await self.db.flush()
        await self._audit("delete", "timetable", timetable_id, {"version": tt.version}, None)

    # ---- rule 2/3: entry validation and conflicts ------------------------------------------------------------------
    async def _group_windows(self, slots: Sequence[TimeSlot]) -> dict[tuple[uuid.UUID, int], tuple[time, time]]:
        """(slot id, span) → clock window, resolved from each slot's group."""
        out: dict[tuple[uuid.UUID, int], tuple[time, time]] = {}
        groups: dict[tuple[uuid.UUID, str], list[TimeSlot]] = {}
        for s in slots:
            key = (s.college_id, s.slot_group)
            if key not in groups:
                groups[key] = await self.slots.group(s.college_id, s.slot_group, active_only=False)
        for (_, _), group in groups.items():
            for i, s in enumerate(group):
                for span in range(1, 5):
                    part = group[i : i + span]
                    out[(s.id, span)] = (part[0].start_time, part[-1].end_time)
        return out

    async def _validate(self, tt: Timetable, data: dict[str, Any]) -> _Cand:
        off = (await self._rows(CourseOffering, [data["offering_id"]])).get(data["offering_id"])
        if off is None or off.deleted_at is not None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course offering not found", {"field": "offering_id"})
        if off.term_id != tt.term_id:
            raise APIError(422, ErrorCode.VALIDATION, "The offering belongs to another term", {"field": "offering_id"})
        if off.status not in SCHEDULABLE_OFFERING_STATUSES:
            raise rule(
                "Only open, closed or in-progress offerings can be scheduled",
                "OFFERING_NOT_SCHEDULABLE",
                offering_status=off.status,
            )
        if tt.scope_type == "section" and data.get("section_id") is None:
            data["section_id"] = tt.scope_id
        if tt.scope_type == "department" and off.department_id != tt.scope_id:
            raise APIError(
                422, ErrorCode.VALIDATION, "The offering belongs to another department", {"field": "offering_id"}
            )
        if data.get("section_id"):
            sec = (await self._rows(BatchSection, [data["section_id"]])).get(data["section_id"])
            if sec is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Section not found", {"field": "section_id"})
            targeted = (
                await self.db.execute(
                    select(func.count()).where(
                        CourseOfferingTarget.offering_id == off.id,
                        (CourseOfferingTarget.section_id == sec.id)
                        | ((CourseOfferingTarget.batch_id == sec.batch_id) & CourseOfferingTarget.section_id.is_(None)),
                    )
                )
            ).scalar_one()
            if not targeted:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "The offering does not target this section",
                    {"field": "section_id", "reason": "section_not_targeted"},
                )
        if data.get("staff_id"):
            allocated = (
                await self.db.execute(
                    select(func.count()).where(
                        CourseOfferingFaculty.offering_id == off.id, CourseOfferingFaculty.staff_id == data["staff_id"]
                    )
                )
            ).scalar_one()
            if not allocated:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "The staff member is not allocated to this offering (course_offering_faculty)",
                    {"field": "staff_id", "reason": "staff_not_allocated"},
                )
        if data.get("room_id"):
            room = await self.rooms.get_one(data["room_id"])
            if not room.is_active:
                raise APIError(422, ErrorCode.VALIDATION, "The room is inactive", {"field": "room_id"})
        slot = await self.slots.get_one(data["time_slot_id"])
        if slot.slot_type in ("break", "lunch"):
            raise APIError(422, ErrorCode.VALIDATION, "Breaks cannot be scheduled", {"field": "time_slot_id"})
        span = await self.slots.span(slot, int(data.get("slot_span") or 1))
        return _Cand(data, span[0].start_time, span[-1].end_time, slot.name)

    async def _check(
        self, tt: Timetable, cand: _Cand, *, exclude: uuid.UUID | None = None, lock: bool = False
    ) -> ConflictReport:
        report = ConflictReport()
        others = await self.tts.day_entries(tt.term_id, cand.day_of_week, timetable=tt)
        others = [o for o in others if o.id != exclude and o.week_pattern in clashing_patterns(cand.week_pattern)]
        slots = await self.slots.rows([o.time_slot_id for o in others])
        windows = await self._group_windows(list(slots.values()))
        hits = []
        for o in others:
            w = windows.get((o.time_slot_id, o.slot_span))
            if w is None:
                continue
            if minutes(w[0]) < minutes(cand.end) and minutes(w[1]) > minutes(cand.start):
                hits.append(o)
        if lock and hits:
            await self.db.execute(
                select(TimetableEntry.id).where(TimetableEntry.id.in_([h.id for h in hits])).with_for_update()
            )
        oc = await self.offering_courses([h.offering_id for h in hits])
        for o in hits:
            code = oc.get(o.offering_id, (None, None))[1]
            slot = slots.get(o.time_slot_id)

            def item(kind: str, msg: str, o: TimetableEntry = o, code: Any = code, slot: Any = slot) -> ConflictItem:
                return ConflictItem(
                    kind=kind,
                    message=msg,
                    entry_id=o.id,
                    timetable_id=o.timetable_id,
                    day_of_week=o.day_of_week,
                    slot_name=slot.name if slot else None,
                    course_code=code.code if code else None,
                )

            label = f"{DAY_NAMES.get(o.day_of_week)} {slot.name if slot else ''}".strip()
            if cand.room_id and o.room_id == cand.room_id:
                report.room.append(item("room", f"Room already booked {label}"))
            if cand.staff_id and o.staff_id == cand.staff_id:
                report.staff.append(item("staff", f"Faculty already teaching {label}"))
            if cand.section_id and o.section_id == cand.section_id:
                report.section.append(item("section", f"Section already has a class {label}"))
        await self._soft_checks(tt, cand, report, exclude)
        return report

    async def _soft_checks(self, tt: Timetable, cand: _Cand, report: ConflictReport, exclude: uuid.UUID | None) -> None:
        off = (await self._rows(CourseOffering, [cand.offering_id]))[cand.offering_id]
        if cand.room_id:
            room = await self.rooms.get_one(cand.room_id)
            size = int(off.enrolled_count or 0)
            if cand.section_id:
                sec = (await self._rows(BatchSection, [cand.section_id])).get(cand.section_id)
                size = max(size, int(sec.capacity or 0) if sec else 0) if not off.enrolled_count else size
            if size and room.capacity < size:
                report.capacity.append(
                    ConflictItem(
                        kind="capacity",
                        message=f"Room {room.code} seats {room.capacity} but the class has {size}",
                    )
                )
        if cand.staff_id:
            allotted = (
                await self.db.execute(
                    select(func.coalesce(func.sum(CourseOfferingFaculty.hours_per_week), 0)).where(
                        CourseOfferingFaculty.offering_id == off.id,
                        CourseOfferingFaculty.staff_id == cand.staff_id,
                    )
                )
            ).scalar_one()
            if allotted:
                scheduled = await self._scheduled_hours(tt, off.id, cand.staff_id, exclude)
                hours = scheduled + self._hours(cand.start, cand.end, cand.week_pattern)
                if hours > float(allotted) + 1e-6:
                    report.workload.append(
                        ConflictItem(
                            kind="workload",
                            message=(
                                f"{hours:g} h/week scheduled on this offering exceeds the allotted {int(allotted)} h"
                            ),
                        )
                    )

    @staticmethod
    def _hours(start: time, end: time, pattern: str) -> float:
        h = (minutes(end) - minutes(start)) / 60
        return round(h / 2 if pattern in ("odd", "even") else h, 2)

    async def _scheduled_hours(
        self, tt: Timetable, offering_id: uuid.UUID, staff_id: uuid.UUID, exclude: uuid.UUID | None
    ) -> float:
        rows = [
            e
            for e in await self.tts.entries([tt.id])
            if e.offering_id == offering_id and e.staff_id == staff_id and e.id != exclude
        ]
        same_scope = select(Timetable.id).where(
            Timetable.term_id == tt.term_id, Timetable.scope_type == tt.scope_type, Timetable.scope_id == tt.scope_id
        )
        live = (
            await self.db.execute(
                select(TimetableEntry).where(
                    TimetableEntry.is_active.is_(True),
                    TimetableEntry.offering_id == offering_id,
                    TimetableEntry.staff_id == staff_id,
                    TimetableEntry.timetable_id.notin_(same_scope),
                )
            )
        ).scalars()
        rows += list(live)
        slots = await self.slots.rows([e.time_slot_id for e in rows])
        windows = await self._group_windows(list(slots.values()))
        total = 0.0
        for e in rows:
            w = windows.get((e.time_slot_id, e.slot_span))
            if w:
                total += self._hours(w[0], w[1], e.week_pattern)
        return total

    async def _raise_or_warn(self, report: ConflictReport) -> None:
        if report.hard:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "The entry clashes with another class",
                {"conflicts": report.model_dump(mode="json")},
            )
        if report.workload and (await self.setting("hr", "workload_enforce")) == "block":
            raise rule(
                report.workload[0].message,
                "WORKLOAD_EXCEEDED",
                conflicts=report.model_dump(mode="json"),
            )

    async def check_conflicts(self, timetable_id: uuid.UUID, body: EntryCreate | None) -> ConflictReport:
        tt = await self.tts.get_one(timetable_id)
        if body is not None:
            cand = await self._validate(tt, body.model_dump(mode="python"))
            return await self._check(tt, cand)
        report = ConflictReport()
        for e in await self.tts.entries([tt.id]):
            cand = await self._validate(tt, {k: getattr(e, k) for k in ENTRY_KEYS})
            one = await self._check(tt, cand, exclude=e.id)
            for kind in ("room", "staff", "section", "capacity", "workload"):
                getattr(report, kind).extend(getattr(one, kind))
        return report

    async def add_entry(self, timetable_id: uuid.UUID, body: EntryCreate) -> EntryResult:
        tt = await self._draft(timetable_id)
        data = body.model_dump(mode="python")
        cand = await self._validate(tt, data)
        report = await self._check(tt, cand, lock=True)
        await self._raise_or_warn(report)
        e = TimetableEntry(
            institution_id=self.inst,
            timetable_id=tt.id,
            term_id=tt.term_id,
            is_active=False,
            **{k: data.get(k) for k in ENTRY_KEYS},
        )
        e.session_type, e.week_pattern = str(e.session_type), str(e.week_pattern)
        self.db.add(e)
        await self.db.flush()
        await self._entry_changed(tt, e, "added", None)
        return EntryResult(entry=(await self.entry_outs([e]))[0], warnings=report)

    async def update_entry(self, timetable_id: uuid.UUID, entry_id: uuid.UUID, body: EntryUpdate) -> EntryResult:
        tt = await self._draft(timetable_id)
        e = await self.tts.entry(entry_id, for_update=True)
        if e.timetable_id != tt.id:
            raise APIError(404, ErrorCode.NOT_FOUND, "Timetable entry not found")
        old = snap(e, ENTRY_KEYS)
        data = {k: getattr(e, k) for k in ENTRY_KEYS}
        data.update(dict(body.model_dump(mode="python", exclude_unset=True).items()))
        cand = await self._validate(tt, data)
        report = await self._check(tt, cand, exclude=e.id, lock=True)
        await self._raise_or_warn(report)
        for k in ENTRY_KEYS:
            setattr(e, k, str(data[k]) if k in ("session_type", "week_pattern") else data.get(k))
        await self.db.flush()
        await self._entry_changed(tt, e, "updated", old)
        return EntryResult(entry=(await self.entry_outs([e]))[0], warnings=report)

    async def delete_entry(self, timetable_id: uuid.UUID, entry_id: uuid.UUID) -> None:
        tt = await self._draft(timetable_id)
        e = await self.tts.entry(entry_id, for_update=True)
        if e.timetable_id != tt.id:
            raise APIError(404, ErrorCode.NOT_FOUND, "Timetable entry not found")
        old = snap(e, ENTRY_KEYS)
        await self.db.delete(e)
        await self.db.flush()
        await self._entry_changed(tt, e, "deleted", old)

    async def _entry_changed(self, tt: Timetable, e: TimetableEntry, change: str, old: dict[str, Any] | None) -> None:
        await self._audit(
            change if change != "added" else "create",
            "timetable_entry",
            e.id,
            old,
            snap(e, ENTRY_KEYS) if change != "deleted" else None,
        )
        await self._emit(
            "timetable.entry_changed",
            {"timetable_id": str(tt.id), "entry_id": str(e.id), "change": change},
            "timetable",
            tt.id,
        )

    # ---- rule 4: publish & session generation ---------------------------------------------------------------------
    async def publish(self, timetable_id: uuid.UUID, body: PublishRequest) -> PublishSummary:
        tt = await self._draft(timetable_id)
        if not await self.can_publish(tt):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "You may publish timetables of your own department only")
        versions = await self.tts.lock_scope(tt.term_id, tt.scope_type, tt.scope_id)
        entries = await self.tts.entries([tt.id])
        if not entries:
            raise rule("A timetable without entries cannot be published", "EMPTY_TIMETABLE")
        report = await self.check_conflicts(tt.id, None)
        if report.hard:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "Resolve the conflicts before publishing",
                {"conflicts": report.model_dump(mode="json")},
            )
        effective = body.effective_from or await self.today()
        term = await self.get_term(tt.term_id)
        if effective > term.end_date:
            raise APIError(
                422, ErrorCode.VALIDATION, "effective_from is after the term end", {"field": "effective_from"}
            )
        previous = next((v for v in versions if v.status == "published"), None)
        old_entry_ids: list[uuid.UUID] = []
        if previous is not None:
            previous.status = "archived"
            for e in await self.tts.entries([previous.id]):
                e.is_active = False
                old_entry_ids.append(e.id)
            await self.db.flush()
        for e in entries:
            e.is_active = True
        try:
            async with self.db.begin_nested():
                await self.db.flush()
        except IntegrityError as exc:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "Another published timetable now uses one of these slots",
                {"index": str(exc.orig)[:200]},
            ) from exc
        tt.status, tt.effective_from = "published", effective
        tt.published_by, tt.published_at = self.actor_id, now_utc()
        await self.db.flush()
        summary = PublishSummary(
            timetable=(await self.responses([tt]))[0], archived_version_id=previous.id if previous else None
        )
        if body.regenerate_sessions:
            estimate = len(entries) * max(1, ((term.end_date - effective).days + 7) // 7)
            if estimate > GENERATE_INLINE_LIMIT:
                from app.core.jobs import enqueue

                job = await enqueue(
                    self.db,
                    self.principal,
                    "timetable.generate_sessions",
                    {
                        "timetable_id": str(tt.id),
                        "effective_from": effective.isoformat(),
                        "old_entry_ids": [str(i) for i in old_entry_ids],
                    },
                )
                summary.job_id = job.id
            else:
                created, removed, kept = await self.generate_sessions(tt, effective, old_entry_ids)
                summary.sessions_created, summary.sessions_removed, summary.sessions_preserved = created, removed, kept
        await self._audit(
            "publish",
            "timetable",
            tt.id,
            {"status": "draft"},
            {"status": "published", "effective_from": effective.isoformat(), "sessions": summary.sessions_created},
        )
        await self._emit(
            "timetable.published",
            {
                "timetable_id": str(tt.id),
                "term_id": str(tt.term_id),
                "scope_type": tt.scope_type,
                "scope_id": str(tt.scope_id),
                "version": tt.version,
                "effective_from": effective.isoformat(),
                "sessions_created": summary.sessions_created,
                "archived_version_id": str(previous.id) if previous else None,
            },
            "timetable",
            tt.id,
        )
        await self._notify_published(tt, entries, summary.timetable.scope_label)
        summary.timetable = (await self.responses([tt]))[0]
        return summary

    async def can_publish(self, tt: Timetable) -> bool:
        return (self.can(TT, "publish") or self.can(TT, "manage")) and await self.can_edit(tt)

    async def _notify_published(self, tt: Timetable, entries: Sequence[TimetableEntry], label: str | None) -> None:
        staff_users = await self.staff_user_ids([e.staff_id for e in entries])
        students = (
            await self.db.execute(
                select(Student.user_id)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .join(
                    CourseRegistration, CourseRegistration.student_program_enrollment_id == StudentProgramEnrollment.id
                )
                .join(CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id)
                .where(
                    CourseRegistrationItem.status == "confirmed",
                    CourseRegistrationItem.offering_id.in_({e.offering_id for e in entries}),
                    Student.user_id.is_not(None),
                )
                .distinct()
            )
        ).scalars()
        users = list(dict.fromkeys([*staff_users, *students]))
        await self._notify(
            "timetable.published",
            users,
            {"scope": label or tt.scope_type, "version": str(tt.version), "effective_from": str(tt.effective_from)},
        )

    async def holiday_dates(self, college_id: uuid.UUID, start: date, end: date) -> set[date]:
        rows = (
            await self.db.execute(
                select(Holiday).where(
                    Holiday.institution_id == self.inst,
                    Holiday.deleted_at.is_(None),
                    Holiday.is_active.is_(True),
                    Holiday.applies_to.in_(("all", "students")),
                    (Holiday.college_id.is_(None)) | (Holiday.college_id == college_id),
                    Holiday.holiday_date <= end,
                    func.coalesce(Holiday.end_date, Holiday.holiday_date) >= start,
                )
            )
        ).scalars()
        out: set[date] = set()
        for h in rows:
            d, last = h.holiday_date, h.end_date or h.holiday_date
            while d <= last:
                out.add(d)
                d += timedelta(days=1)
        return out

    async def generate_sessions(
        self,
        tt: Timetable,
        effective: date,
        old_entry_ids: Sequence[uuid.UUID] = (),
        progress: Progress | None = None,
    ) -> tuple[int, int, int]:
        """Replace future ``scheduled`` sessions of the replaced version and create this version's sessions.
        Returns ``(created, removed, preserved)``."""
        term = await self.get_term(tt.term_id)
        removed = kept = 0
        old = await self.sessions.for_entries(list(old_entry_ids), date_from=effective, for_update=True)
        drop = [s.id for s in old if s.status == "scheduled" and s.attendance_status == "not_taken"]
        kept = len(old) - len(drop)
        removed = await self.sessions.delete_ids(drop)
        entries = await self.tts.entries([tt.id])
        created = await self.create_sessions(entries, effective, term.end_date, tt.college_id, progress=progress)
        return created, removed, kept

    async def create_sessions(
        self,
        entries: Sequence[TimetableEntry],
        start: date,
        end: date,
        college_id: uuid.UUID,
        *,
        only_dates: set[date] | None = None,
        progress: Progress | None = None,
    ) -> int:
        holidays = await self.holiday_dates(college_id, start, end)
        slots = await self.slots.rows([e.time_slot_id for e in entries])
        windows = await self._group_windows(list(slots.values()))
        offs = await self._rows(CourseOffering, [e.offering_id for e in entries])
        approved = await self._approved_substitutes([e.id for e in entries], start, end)
        rows: list[dict[str, Any]] = []
        for i, e in enumerate(entries):
            w = windows.get((e.time_slot_id, e.slot_span))
            off = offs.get(e.offering_id)
            if w is None or off is None:
                continue
            d = start + timedelta(days=(e.day_of_week - start.isoweekday()) % 7)
            while d <= end:
                if d not in holidays and matches_week(e.week_pattern, d) and (only_dates is None or d in only_dates):
                    rows.append(
                        {
                            "id": uuid.uuid4(),
                            "institution_id": self.inst,
                            "college_id": off.college_id,
                            "term_id": e.term_id,
                            "offering_id": e.offering_id,
                            "timetable_entry_id": e.id,
                            "session_date": d,
                            "time_slot_id": e.time_slot_id,
                            "start_time": w[0],
                            "end_time": w[1],
                            "staff_id": approved.get((e.id, d), e.staff_id),
                            "session_type": e.session_type,
                            "room_id": e.room_id,
                            "online_link": off.online_class_link,
                        }
                    )
                d += timedelta(days=7)
            if progress and i % 20 == 0:
                await progress(min(90, 10 + int(80 * i / max(1, len(entries)))), f"{len(rows)} sessions prepared")
        created = 0
        for chunk in range(0, len(rows), 500):
            stmt = (
                pg_insert(ClassSession)
                .values(rows[chunk : chunk + 500])
                .on_conflict_do_nothing(index_elements=["offering_id", "session_date", "start_time"])
                .returning(ClassSession.id)
            )
            created += len((await self.db.execute(stmt)).all())
        return created

    async def _approved_substitutes(
        self, entry_ids: Sequence[uuid.UUID], start: date, end: date
    ) -> dict[tuple[uuid.UUID, date], uuid.UUID]:
        from app.models.timetable import TimetableSubstitution

        if not entry_ids:
            return {}
        rows = await self.db.execute(
            select(TimetableSubstitution).where(
                TimetableSubstitution.timetable_entry_id.in_(list(entry_ids)),
                TimetableSubstitution.status == "approved",
                TimetableSubstitution.on_date >= start,
                TimetableSubstitution.on_date <= end,
                TimetableSubstitution.substitute_staff_id.is_not(None),
            )
        )
        return {
            (s.timetable_entry_id, s.on_date): s.substitute_staff_id
            for s in rows.scalars()
            if s.substitute_staff_id is not None
        }

    async def archive(self, timetable_id: uuid.UUID) -> TimetableResponse:
        tt = await self.tts.get_one(timetable_id, for_update=True)
        if not await self.can_publish(tt):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "You may archive timetables of your own department only")
        if tt.status != "published":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Only a published timetable can be archived")
        entries = await self.tts.entries([tt.id])
        for e in entries:
            e.is_active = False
        tomorrow = await self.today() + timedelta(days=1)
        future = await self.sessions.for_entries([e.id for e in entries], date_from=tomorrow, for_update=True)
        await self.sessions.delete_ids(
            [s.id for s in future if s.status == "scheduled" and s.attendance_status == "not_taken"]
        )
        tt.status = "archived"
        await self.db.flush()
        await self._audit("archive", "timetable", tt.id, {"status": "published"}, {"status": "archived"})
        return (await self.responses([tt]))[0]

    async def resync_dates(self, dates: Sequence[date]) -> dict[str, int]:
        """``holiday.changed`` → ``sessions.regenerate_future``: drop not-taken scheduled sessions on dates that are
        now holidays and recreate sessions of live entries on dates that no longer are (future dates only)."""
        today = await self.today()
        wanted = sorted({d for d in dates if d >= today})
        removed = created = 0
        if not wanted:
            return {"removed": 0, "created": 0}
        from app.models.platform import College

        colleges = (
            (
                await self.db.execute(
                    select(College.id).where(College.institution_id == self.inst, College.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        for college_id in colleges:
            hol = await self.holiday_dates(college_id, wanted[0], wanted[-1])
            on_holiday = [d for d in wanted if d in hol]
            free = {d for d in wanted if d not in hol}
            if on_holiday:
                stale = [
                    s
                    for s in await self.sessions.on_dates(on_holiday)
                    if s.college_id == college_id and s.attendance_status == "not_taken"
                ]
                removed += await self.sessions.delete_ids([s.id for s in stale])
            if free:
                live = (
                    (
                        await self.db.execute(
                            select(TimetableEntry)
                            .join(Timetable, Timetable.id == TimetableEntry.timetable_id)
                            .where(
                                TimetableEntry.is_active.is_(True),
                                Timetable.status == "published",
                                Timetable.college_id == college_id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                by_tt: dict[uuid.UUID, list[TimetableEntry]] = {}
                for e in live:
                    by_tt.setdefault(e.timetable_id, []).append(e)
                tts = await self._rows(Timetable, list(by_tt))
                for tid, entries in by_tt.items():
                    t = tts[tid]
                    start = max(min(free), t.effective_from or min(free))
                    term = await self.get_term(t.term_id)
                    created += await self.create_sessions(
                        entries, start, min(max(free), term.end_date), college_id, only_dates=free
                    )
        return {"removed": removed, "created": created}

    # ---- rule 5: views ------------------------------------------------------------------------------------------------
    async def _live_entries(self, scope: str, scope_id: uuid.UUID, term_id: uuid.UUID | None) -> list[TimetableEntry]:
        stmt = select(TimetableEntry).where(
            TimetableEntry.is_active.is_(True), TimetableEntry.institution_id == self.inst
        )
        if term_id:
            stmt = stmt.where(TimetableEntry.term_id == term_id)
        published_of = select(Timetable.id).where(Timetable.status == "published", Timetable.scope_id == scope_id)
        if scope == "section":
            stmt = stmt.where((TimetableEntry.section_id == scope_id) | TimetableEntry.timetable_id.in_(published_of))
        elif scope == "batch":
            secs = select(BatchSection.id).where(BatchSection.batch_id == scope_id)
            stmt = stmt.where(TimetableEntry.section_id.in_(secs) | TimetableEntry.timetable_id.in_(published_of))
        elif scope == "department":
            stmt = stmt.where(
                TimetableEntry.offering_id.in_(
                    select(CourseOffering.id).where(CourseOffering.department_id == scope_id)
                )
            )
        elif scope == "faculty":
            stmt = stmt.where(TimetableEntry.staff_id == scope_id)
        elif scope == "room":
            stmt = stmt.where(TimetableEntry.room_id == scope_id)
        else:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown view scope", {"field": "scope"})
        if self.principal is not None:
            if scope in ("faculty", "room", "department") and not is_staff(self.principal):
                raise APIError(
                    403, ErrorCode.PERMISSION_DENIED, "Only staff can open faculty, room or department views"
                )
            stmt = stmt.where(entry_predicate(self.principal))
        return list((await self.db.execute(stmt)).scalars().all())

    async def _label(self, scope: str, scope_id: uuid.UUID) -> str | None:
        if scope == "faculty":
            s = (await self._rows(Staff, [scope_id])).get(scope_id)
            return s.full_name if s else None
        if scope == "room":
            r = (await self.rooms.rows([scope_id])).get(scope_id)
            return f"{r.code} — {r.name}" if r else None
        probe = Timetable(scope_type=scope, scope_id=scope_id)
        return (await self._scope_labels([probe])).get(scope_id)

    async def weekly(
        self,
        scope: str,
        scope_id: uuid.UUID,
        week: date | None,
        *,
        term_id: uuid.UUID | None = None,
        entries: list[TimetableEntry] | None = None,
        session_filter: Any = None,
    ) -> WeeklyView:
        day0 = week_start(week or await self.today())
        if entries is None:
            entries = await self._live_entries(scope, scope_id, term_id)
        entries = [e for e in entries if matches_week(e.week_pattern, day0)]
        outs = {o.id: o for o in await self.entry_outs(entries)}
        slots_used = await self.slots.rows([e.time_slot_id for e in entries])
        group: list[TimeSlot] = []
        if slots_used:
            first = next(iter(slots_used.values()))
            group = await self.slots.group(first.college_id, first.slot_group)
        group_ids = {s.id for s in group}
        extra = [s for s in slots_used.values() if s.id not in group_ids]
        all_slots = sorted([*group, *extra], key=lambda s: (s.start_time, s.sequence))
        last_day = 7 if any(e.day_of_week == 7 for e in entries) else 6
        days = []
        for dow in range(1, last_day + 1):
            vslots = []
            for s in all_slots:
                vslots.append(
                    ViewSlot(
                        slot_id=s.id,
                        name=s.name,
                        start_time=s.start_time,
                        end_time=s.end_time,
                        slot_type=s.slot_type,
                        entries=[
                            outs[e.id]
                            for e in entries
                            if e.day_of_week == dow and e.time_slot_id == s.id and e.id in outs
                        ],
                    )
                )
            days.append(
                ViewDay(day_of_week=dow, label=DAY_NAMES[dow], date=day0 + timedelta(days=dow - 1), slots=vslots)
            )
        view = WeeklyView(
            scope=scope,
            scope_id=scope_id,
            label=await self._label(scope, scope_id) if scope != "me" else None,
            week_start=day0,
            iso_week=day0.isocalendar().week,
            days=days,
        )
        stmt = select(ClassSession).where(
            ClassSession.institution_id == self.inst,
            ClassSession.session_date >= day0,
            ClassSession.session_date <= day0 + timedelta(days=6),
        )
        if session_filter is not None:
            stmt = stmt.where(session_filter)
        elif scope == "faculty":
            stmt = stmt.where(ClassSession.staff_id == scope_id)
        elif scope == "room":
            stmt = stmt.where(ClassSession.room_id == scope_id)
        else:
            stmt = stmt.where(ClassSession.timetable_entry_id.in_([e.id for e in entries] or [uuid.uuid4()]))
        if self.principal is not None:
            stmt = stmt.where(session_predicate(self.principal, "all"))
        sessions = (await self.db.execute(stmt.order_by(ClassSession.session_date, ClassSession.start_time))).scalars()
        view.sessions = await self.session_outs(list(sessions))
        return view

    async def my_week(self, week: date | None, ward_id: uuid.UUID | None = None) -> WeeklyView:
        staff = await self.my_staff()
        if staff is not None and ward_id is None:
            view = await self.weekly("faculty", staff.id, week)
            view.scope, view.label = "me", staff.full_name
            return view
        enrolment, student = await self._learner(ward_id)
        term = await self.current_term(enrolment.college_id)
        section_id = None
        if term is not None:
            rec = (
                await self.db.execute(
                    select(StudentTermRecord).where(
                        StudentTermRecord.student_program_enrollment_id == enrolment.id,
                        StudentTermRecord.term_id == term.id,
                    )
                )
            ).scalar_one_or_none()
            section_id = rec.section_id if rec else None
        if section_id is None:
            section_id = (
                await self.db.execute(
                    select(StudentTermRecord.section_id)
                    .where(StudentTermRecord.student_program_enrollment_id == enrolment.id)
                    .order_by(StudentTermRecord.term_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        confirmed = (
            select(CourseRegistrationItem.offering_id)
            .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
            .where(
                CourseRegistrationItem.status == "confirmed",
                CourseRegistration.student_program_enrollment_id == enrolment.id,
            )
        )
        conds: list[Any] = [
            TimetableEntry.offering_id.in_(confirmed)
            & ((TimetableEntry.section_id.is_(None)) | (TimetableEntry.section_id == section_id))
        ]
        if section_id is not None:
            conds.append(TimetableEntry.section_id == section_id)
            conds.append(
                TimetableEntry.timetable_id.in_(
                    select(Timetable.id).where(Timetable.status == "published", Timetable.scope_id == section_id)
                )
            )
        stmt = select(TimetableEntry).where(
            TimetableEntry.is_active.is_(True), TimetableEntry.institution_id == self.inst
        )
        if term is not None:
            stmt = stmt.where(TimetableEntry.term_id == term.id)
        from sqlalchemy import or_

        entries = list((await self.db.execute(stmt.where(or_(*conds)))).scalars().all())
        view = await self.weekly(
            "me",
            student.id,
            week,
            entries=entries,
            session_filter=ClassSession.timetable_entry_id.in_([e.id for e in entries] or [uuid.uuid4()])
            | ClassSession.offering_id.in_(confirmed),
        )
        view.label = student.full_name
        return view

    async def _learner(self, ward_id: uuid.UUID | None) -> tuple[StudentProgramEnrollment, Student]:
        if ward_id is None:
            student, enrolment = await self.me()
            return enrolment, student
        wards = await self.ward_ids()
        if ward_id not in wards:
            raise APIError(404, ErrorCode.NOT_FOUND, "Student not found")
        student = (await self._rows(Student, [ward_id]))[ward_id]
        open_enrolment = await self.enrollments.open_for(ward_id)
        if open_enrolment is None:
            raise rule("The student has no open programme enrolment", "NO_ENROLMENT")
        return open_enrolment, student

    # ---- rule 6: iCal ------------------------------------------------------------------------------------------------
    async def create_token(self, base_url: str) -> ICalToken:
        if self.actor_id is None:
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Sign in first")
        now = now_utc()
        for row in (
            await self.db.execute(
                select(CalendarFeedToken).where(
                    CalendarFeedToken.user_id == self.actor_id, CalendarFeedToken.revoked_at.is_(None)
                )
            )
        ).scalars():
            row.revoked_at = now
        token = secrets.token_urlsafe(32)
        row = CalendarFeedToken(institution_id=self.inst, user_id=self.actor_id, token_hash=_token_hash(token))
        self.db.add(row)
        await self.db.flush()
        await self._audit("create", "calendar_feed_token", row.id, None, {"user_id": str(self.actor_id)})
        return ICalToken(token=token, url=f"{base_url}/api/v1/timetables/ical/{token}.ics", created_at=row.created_at)

    async def revoke_token(self) -> ICalToken:
        now = now_utc()
        n = 0
        for row in (
            await self.db.execute(
                select(CalendarFeedToken).where(
                    CalendarFeedToken.user_id == self.actor_id, CalendarFeedToken.revoked_at.is_(None)
                )
            )
        ).scalars():
            row.revoked_at, n = now, n + 1
        await self.db.flush()
        if n:
            await self._audit("revoke", "calendar_feed_token", None, None, {"user_id": str(self.actor_id)})
        return ICalToken(revoked=True)

    async def section_feed(self, section_id: uuid.UUID, base_url: str) -> SectionFeed:
        from app.core.security import sign_payload

        sec = (await self._rows(BatchSection, [section_id])).get(section_id)
        if sec is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Section not found")
        token = sign_payload({"t": "tt_section", "s": str(section_id), "i": str(self.inst)}, 400 * 86400)
        return SectionFeed(
            section_id=section_id, url=f"{base_url}/api/v1/timetables/sections/{section_id}.ics?token={token}"
        )

    async def ical_sessions(self, *, section_id: uuid.UUID | None = None, days: int = 30) -> list[ClassSession]:
        today = await self.today()
        stmt = select(ClassSession).where(
            ClassSession.institution_id == self.inst,
            ClassSession.session_date >= today,
            ClassSession.session_date <= today + timedelta(days=days),
            ClassSession.status.in_(("scheduled", "conducted")),
        )
        if section_id is not None:
            stmt = stmt.where(
                ClassSession.timetable_entry_id.in_(
                    select(TimetableEntry.id).where(TimetableEntry.section_id == section_id)
                )
            )
        elif self.principal is not None:
            stmt = stmt.where(session_predicate(self.principal, "self"))
        return list(
            (await self.db.execute(stmt.order_by(ClassSession.session_date, ClassSession.start_time))).scalars()
        )

    async def render_ics(self, sessions: Sequence[ClassSession], name: str) -> str:
        from app.core.tenancy import institution_tz

        tz = institution_tz(await self.institution())
        outs = await self.session_outs(sessions)

        def stamp(d: date, t: time) -> str:
            from datetime import UTC

            return datetime.combine(d, t, tzinfo=tz).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

        now = now_utc().strftime("%Y%m%dT%H%M%SZ")
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//SeptronUniverse//Timetable//EN",
            f"X-WR-CALNAME:{esc(name)}",
        ]
        for s in outs:
            lines += [
                "BEGIN:VEVENT",
                f"UID:{s.id}@septron-universe",
                f"DTSTAMP:{now}",
                f"DTSTART:{stamp(s.session_date, s.start_time)}",
                f"DTEND:{stamp(s.session_date, s.end_time)}",
                f"SUMMARY:{esc(' '.join(x for x in (s.course_code, s.course_title) if x) or 'Class')}",
            ]
            if s.room_code:
                lines.append(f"LOCATION:{esc(s.room_code)}")
            desc = " · ".join(x for x in (s.session_type, s.staff_name, s.topic) if x)
            if desc:
                lines.append(f"DESCRIPTION:{esc(desc)}")
            if s.status == "cancelled":
                lines.append("STATUS:CANCELLED")
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines) + "\r\n"


async def ical_for_token(token: str) -> str | None:
    """Public ``GET /timetables/ical/{token}.ics`` — resolves the token on the platform session, then renders inside
    the tenant session as that user (their own sessions only)."""
    from app.db.session import PlatformSessionLocal, tenant_session
    from app.services.auth_service import load_principal

    async with PlatformSessionLocal() as pdb:
        row = (
            await pdb.execute(
                select(CalendarFeedToken).where(
                    CalendarFeedToken.token_hash == _token_hash(token), CalendarFeedToken.revoked_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        iid, uid = row.institution_id, row.user_id
    from app.core.features import is_enabled

    if not await is_enabled(iid, "timetable.ical"):
        return None
    db = await tenant_session(iid)
    try:
        principal = await load_principal(db, uid)
        svc = TimetableService(db, principal, institution_id=iid)
        return await svc.render_ics(await svc.ical_sessions(), "My timetable")
    finally:
        await db.close()


async def ical_for_section(section_id: uuid.UUID, token: str) -> str | None:
    from app.core.security import verify_signed
    from app.db.session import tenant_session

    try:
        claims = verify_signed(token)
    except APIError:
        return None
    if claims.get("t") != "tt_section" or claims.get("s") != str(section_id):
        return None
    iid = uuid.UUID(str(claims["i"]))
    from app.core.features import is_enabled

    if not await is_enabled(iid, "timetable.ical"):
        return None
    db = await tenant_session(iid)
    try:
        svc = TimetableService(db, None, institution_id=iid)
        return await svc.render_ics(await svc.ical_sessions(section_id=section_id), "Section timetable")
    finally:
        await db.close()


__all__ = ["TimetableService", "confirmed_offering_ids", "ical_for_section", "ical_for_token"]
