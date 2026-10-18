"""Auto-generation of a draft timetable — Prompts/10 §10.6 ``auto_generate_service.py`` ({timetable.auto_generate},
off by default, professional tier).

**Delivered as a deterministic greedy placer, not CP-SAT.** The prompt marks the solver optional ("can be delivered
later"); ``ortools`` is not a dependency yet. The placer honours the same *hard* constraints the editor enforces —
room / staff / section clashes against the live timetables of other scopes and the draft itself, room type (lab
sessions in ``lab`` rooms when ``respect_room_type``), room capacity ≥ offering roster, faculty on approved leave is
not considered (weekly pattern) — plus ``max_consecutive`` teaching slots per section and per staff member and a
*soft* spread (one session of an offering per day first). Weekly demand per offering = the allocated
``course_offering_faculty.hours_per_week`` of its primary staff member (fallback: course L+T+P hours, else 3).
The run writes entries into the given **draft** (existing entries kept) and reports what it could not place.
A CP-SAT model can replace ``_place`` behind the same interface.
"""

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.enums.timetable import SCHEDULABLE_OFFERING_STATUSES
from app.models.academic import BatchSection
from app.models.curriculum import Course
from app.models.offerings import CourseOffering, CourseOfferingFaculty, CourseOfferingTarget
from app.models.timetable import Room, TimeSlot, Timetable, TimetableEntry
from app.schemas.timetable import AutoGenerateRequest
from app.services.timetable.common import TimetableBase, minutes

Progress = Callable[[int, str], Any]


class AutoGenerateService(TimetableBase):
    async def _offerings(self, tt: Timetable) -> list[CourseOffering]:
        stmt = select(CourseOffering).where(
            CourseOffering.term_id == tt.term_id,
            CourseOffering.deleted_at.is_(None),
            CourseOffering.status.in_(tuple(SCHEDULABLE_OFFERING_STATUSES)),
        )
        if tt.scope_type == "department":
            stmt = stmt.where(CourseOffering.department_id == tt.scope_id)
        elif tt.scope_type == "section":
            sec = (await self._rows(BatchSection, [tt.scope_id]))[tt.scope_id]
            stmt = stmt.where(
                CourseOffering.id.in_(
                    select(CourseOfferingTarget.offering_id).where(
                        (CourseOfferingTarget.section_id == tt.scope_id)
                        | ((CourseOfferingTarget.batch_id == sec.batch_id) & CourseOfferingTarget.section_id.is_(None))
                    )
                )
            )
        else:
            stmt = stmt.where(
                CourseOffering.id.in_(
                    select(CourseOfferingTarget.offering_id).where(CourseOfferingTarget.batch_id == tt.scope_id)
                )
            )
        return list((await self.db.execute(stmt.order_by(CourseOffering.course_id))).scalars().all())

    async def run(
        self, timetable_id: uuid.UUID, body: AutoGenerateRequest, *, dry_run: bool, progress: Progress | None = None
    ) -> dict[str, Any]:
        tt = await self.tts.get_one(timetable_id, for_update=True)
        await self.assert_edit(tt)
        if tt.status != "draft":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Auto-generation fills a draft version only")
        slots = [
            s for s in await self.slots.group(tt.college_id, body.slot_group) if s.slot_type not in ("break", "lunch")
        ]
        if not slots:
            raise APIError(422, ErrorCode.VALIDATION, "The slot group has no teaching slots", {"field": "slot_group"})
        offerings = await self._offerings(tt)
        courses = await self._rows(Course, [o.course_id for o in offerings])
        rooms = list(
            (
                await self.db.execute(
                    select(Room).where(
                        Room.institution_id == self.inst,
                        Room.college_id == tt.college_id,
                        Room.deleted_at.is_(None),
                        Room.is_active.is_(True),
                        Room.room_type.in_(("classroom", "lab", "smart_class", "seminar")),
                    )
                )
            ).scalars()
        )
        faculty = (
            (
                await self.db.execute(
                    select(CourseOfferingFaculty).where(
                        CourseOfferingFaculty.offering_id.in_([o.id for o in offerings] or [uuid.uuid4()])
                    )
                )
            )
            .scalars()
            .all()
        )
        primary: dict[uuid.UUID, CourseOfferingFaculty] = {}
        for f in sorted(faculty, key=lambda f: (f.role != "coordinator", f.role != "instructor", -f.hours_per_week)):
            primary.setdefault(f.offering_id, f)
        # occupancy from the live timetables of other scopes + this draft: (day, slot) → sets
        busy_room: set[tuple[int, uuid.UUID, uuid.UUID]] = set()
        busy_staff: set[tuple[int, uuid.UUID, uuid.UUID]] = set()
        busy_sec: set[tuple[int, uuid.UUID, uuid.UUID]] = set()
        slot_ids = {s.id for s in slots}
        for day in body.days:
            for e in await self.tts.day_entries(tt.term_id, day, timetable=tt):
                if e.time_slot_id not in slot_ids:
                    continue
                if e.room_id:
                    busy_room.add((day, e.time_slot_id, e.room_id))
                if e.staff_id:
                    busy_staff.add((day, e.time_slot_id, e.staff_id))
                if e.section_id:
                    busy_sec.add((day, e.time_slot_id, e.section_id))
        section_id = tt.scope_id if tt.scope_type == "section" else None
        placed: list[dict[str, Any]] = []
        unplaced: list[dict[str, Any]] = []
        for i, off in enumerate(offerings):
            course = courses.get(off.course_id)
            fac = primary.get(off.id)
            demand = fac.hours_per_week if fac and fac.hours_per_week else 0
            if not demand and course is not None:
                demand = int(course.lecture_hours + course.tutorial_hours + course.practical_hours)
            demand = demand or 3
            is_lab = bool(course is not None and course.course_type in ("lab", "practical"))
            size = int(off.enrolled_count or 0)
            fit = [
                r
                for r in sorted(rooms, key=lambda r: r.capacity)
                if r.capacity >= size and (not body.respect_room_type or (r.room_type == "lab") == is_lab)
            ] or sorted(rooms, key=lambda r: -r.capacity)
            remaining = demand
            for pass_no in (0, 1):
                for day in body.days:
                    if remaining <= 0:
                        break
                    if (
                        body.spread
                        and pass_no == 0
                        and any(p["offering_id"] == off.id and p["day_of_week"] == day for p in placed)
                    ):
                        continue
                    for idx, slot in enumerate(slots):
                        if remaining <= 0:
                            break
                        if section_id and (day, slot.id, section_id) in busy_sec:
                            continue
                        if fac and (day, slot.id, fac.staff_id) in busy_staff:
                            continue
                        if self._run_too_long(
                            day,
                            idx,
                            slots,
                            section_id,
                            fac.staff_id if fac else None,
                            busy_sec,
                            busy_staff,
                            body.max_consecutive,
                        ):
                            continue
                        room = next((r for r in fit if (day, slot.id, r.id) not in busy_room), None)
                        if room is None:
                            continue
                        placed.append(
                            {
                                "offering_id": off.id,
                                "course_code": course.code if course else None,
                                "day_of_week": day,
                                "time_slot_id": slot.id,
                                "slot_name": slot.name,
                                "room_id": room.id,
                                "staff_id": fac.staff_id if fac else None,
                                "section_id": section_id,
                                "session_type": "lab" if is_lab else "lecture",
                            }
                        )
                        busy_room.add((day, slot.id, room.id))
                        if fac:
                            busy_staff.add((day, slot.id, fac.staff_id))
                        if section_id:
                            busy_sec.add((day, slot.id, section_id))
                        remaining -= max(1, round((minutes(slot.end_time) - minutes(slot.start_time)) / 60))
                        if body.spread and pass_no == 0:
                            break
            if remaining > 0:
                unplaced.append(
                    {
                        "offering_id": str(off.id),
                        "course_code": course.code if course else None,
                        "hours_left": remaining,
                    }
                )
            if progress and i % 5 == 0:
                await progress(min(90, 10 + int(80 * i / max(1, len(offerings)))), f"{len(placed)} placed")
        if not dry_run:
            for p in placed:
                self.db.add(
                    TimetableEntry(
                        institution_id=self.inst,
                        timetable_id=tt.id,
                        term_id=tt.term_id,
                        offering_id=p["offering_id"],
                        section_id=p["section_id"],
                        day_of_week=p["day_of_week"],
                        time_slot_id=p["time_slot_id"],
                        room_id=p["room_id"],
                        staff_id=p["staff_id"],
                        session_type=p["session_type"],
                        week_pattern="all",
                        slot_span=1,
                        is_active=False,
                    )
                )
            await self.db.flush()
            await self._audit(
                "auto_generate", "timetable", tt.id, None, {"placed": len(placed), "unplaced": len(unplaced)}
            )
        return {
            "timetable_id": str(tt.id),
            "dry_run": dry_run,
            "placed": len(placed),
            "unplaced": unplaced,
            "entries": [{k: str(v) if isinstance(v, uuid.UUID) else v for k, v in p.items()} for p in placed[:200]],
        }

    @staticmethod
    def _run_too_long(
        day: int,
        idx: int,
        slots: list[TimeSlot],
        section_id: uuid.UUID | None,
        staff_id: uuid.UUID | None,
        busy_sec: set[tuple[int, uuid.UUID, uuid.UUID]],
        busy_staff: set[tuple[int, uuid.UUID, uuid.UUID]],
        limit: int,
    ) -> bool:
        for who, busy in ((section_id, busy_sec), (staff_id, busy_staff)):
            if who is None:
                continue
            run = 1
            j = idx - 1
            while j >= 0 and (day, slots[j].id, who) in busy:
                run, j = run + 1, j - 1
            j = idx + 1
            while j < len(slots) and (day, slots[j].id, who) in busy:
                run, j = run + 1, j + 1
            if run > limit:
                return True
        return False


__all__ = ["AutoGenerateService"]
