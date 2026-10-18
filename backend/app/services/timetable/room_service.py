"""Buildings, rooms and slot groups — Prompts/10 §10.6 ``room_service.py``.

1. Buildings / rooms CRUD: ``code`` unique per college (409 ``CONFLICT``); ``exam_capacity ≤ capacity`` (422 —
   schema validator, re-checked on partial updates); ``features`` are free tags the auto-generator matches. Writers:
   ``timetable:update`` / ``manage`` (registrar, estate officer, college admin). A HOD edits only **department labs**
   — rooms of type ``lab`` tagged ``dept:<department id>`` with one of its departments. A room still used by a
   published entry cannot be deleted (409).
2. Slot groups: ``PUT /time-slots`` replaces a college's group in order; slots must not overlap (422) and are
   numbered by position. Slots referenced by entries are kept (deactivated) when dropped from the group.
3. Availability: ``rooms × (date, slot)`` — free when no live entry occupies the room at that weekday / slot (week
   pattern of the date's ISO week) and no live session overlaps the slot's time window.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.timetable import Building, Room, TimeSlot, TimetableEntry
from app.schemas.timetable import BuildingIn, BuildingOut, RoomAvailability, RoomIn, RoomOut, SlotGroupReplace, SlotOut
from app.services.academics.context import writable_department_ids
from app.services.students.common import snap
from app.services.timetable.common import TT, TimetableBase, minutes
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta

ROOM_KEYS = ("code", "name", "room_type", "capacity", "exam_capacity", "building_id", "is_bookable", "is_active")


def _features(room: Room) -> list[str]:
    f = room.features
    if isinstance(f, list):
        return [str(x) for x in f]
    if isinstance(f, dict):
        return [str(k) for k, v in f.items() if v]
    return []


class RoomService(TimetableBase):
    # ---- write scope -------------------------------------------------------------------------------------------
    def _full_writer(self) -> bool:
        return bool(
            getattr(self.principal, "is_super_admin", False)
            or self.can(TT, "manage")
            or any(st in ("institution", "college") for st, _ in getattr(self.principal, "scopes", []))
        )

    async def _assert_room_write(self, room_type: str, features: list[str]) -> None:
        if self._full_writer():
            return
        writable = await writable_department_ids(self.db, self.principal)
        tags = {f.split(":", 1)[1] for f in features if f.startswith("dept:")}
        if room_type == "lab" and writable and any(str(d) in tags for d in writable):
            return
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "You may edit the labs of your own department only")

    def _assert_full(self) -> None:
        if not self._full_writer():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Buildings and slot groups are managed centrally")

    # ---- buildings ---------------------------------------------------------------------------------------------
    async def list_buildings(self, college_id: uuid.UUID | None) -> list[BuildingOut]:
        rows = await self.buildings.listed(college_id)
        counts = await self.buildings.room_counts([b.id for b in rows])
        out = []
        for b in rows:
            item = BuildingOut.model_validate(b)
            item.rooms_count = counts.get(b.id, 0)
            out.append(item)
        return out

    async def create_building(self, body: BuildingIn) -> BuildingOut:
        self._assert_full()
        college_id = await self.default_college(body.college_id)
        if await self.buildings.by_code(college_id, body.code):
            raise APIError(409, ErrorCode.CONFLICT, "Building code already exists in this college", {"field": "code"})
        b = Building(institution_id=self.inst, college_id=college_id, **body.model_dump(exclude={"college_id"}))
        self.db.add(b)
        await self.db.flush()
        await self._audit("create", "building", b.id, None, {"code": b.code, "name": b.name})
        return BuildingOut.model_validate(b)

    async def update_building(self, building_id: uuid.UUID, body: BuildingIn) -> BuildingOut:
        self._assert_full()
        b = await self.buildings.get_one(building_id)
        other = await self.buildings.by_code(b.college_id, body.code)
        if other is not None and other.id != b.id:
            raise APIError(409, ErrorCode.CONFLICT, "Building code already exists in this college", {"field": "code"})
        old = {"code": b.code, "name": b.name}
        for k, v in body.model_dump(exclude={"college_id"}).items():
            setattr(b, k, v)
        await self.db.flush()
        await self._audit("update", "building", b.id, old, {"code": b.code, "name": b.name})
        out = BuildingOut.model_validate(b)
        out.rooms_count = (await self.buildings.room_counts([b.id])).get(b.id, 0)
        return out

    async def delete_building(self, building_id: uuid.UUID) -> None:
        self._assert_full()
        b = await self.buildings.get_one(building_id)
        await self.db.delete(b)  # rooms keep existing (building_id → NULL)
        await self.db.flush()
        await self._audit("delete", "building", building_id, {"code": b.code}, None)

    # ---- rooms ---------------------------------------------------------------------------------------------------
    async def room_outs(self, rows: list[Room]) -> list[RoomOut]:
        buildings = await self._rows(Building, [r.building_id for r in rows])
        out = []
        for r in rows:
            item = RoomOut(
                id=r.id,
                college_id=r.college_id,
                building_id=r.building_id,
                building_code=buildings[r.building_id].code if r.building_id in buildings else None,
                code=r.code,
                name=r.name,
                room_type=r.room_type,
                floor=r.floor,
                capacity=r.capacity,
                exam_capacity=r.exam_capacity,
                features=_features(r),
                is_bookable=r.is_bookable,
                is_active=r.is_active,
                version=r.version or 1,
            )
            out.append(item)
        return out

    async def list_rooms(self, params: PageParams, **filters: Any) -> tuple[list[RoomOut], PaginationMeta]:
        stmt = self.rooms.filtered(**filters)
        if not params.sort:
            stmt = stmt.order_by(Room.code)
        rows, page = await self.rooms.paginate(stmt, params)
        return await self.room_outs(list(rows)), page

    async def get_room(self, room_id: uuid.UUID) -> RoomOut:
        return (await self.room_outs([await self.rooms.get_one(room_id)]))[0]

    def _tags(self, body: RoomIn) -> list[str]:
        tags = [t.strip() for t in body.features if t and t.strip() and not t.startswith("dept:")]
        tags += [t for t in body.features if t.startswith("dept:")]
        if body.department_id:
            tags.append(f"dept:{body.department_id}")
        return list(dict.fromkeys(tags))

    async def create_room(self, body: RoomIn) -> RoomOut:
        features = self._tags(body)
        await self._assert_room_write(body.room_type.value, features)
        college_id = await self.default_college(body.college_id)
        if await self.rooms.by_code(college_id, body.code):
            raise APIError(409, ErrorCode.CONFLICT, "Room code already exists in this college", {"field": "code"})
        if body.building_id:
            b = await self.buildings.get_one(body.building_id)
            if b.college_id != college_id:
                raise APIError(422, ErrorCode.VALIDATION, "Building is in another college", {"field": "building_id"})
        r = Room(
            institution_id=self.inst,
            college_id=college_id,
            **body.model_dump(exclude={"college_id", "features", "department_id"}),
            features=features,
        )
        self.db.add(r)
        await self.db.flush()
        await self._audit("create", "room", r.id, None, snap(r, ROOM_KEYS))
        return (await self.room_outs([r]))[0]

    async def update_room(self, room_id: uuid.UUID, body: RoomIn, expected_version: int | None = None) -> RoomOut:
        r = await self.rooms.get_one(room_id, for_update=True)
        await self._assert_room_write(r.room_type, _features(r))
        features = self._tags(body)
        await self._assert_room_write(body.room_type.value, features)
        if expected_version is not None and r.version != expected_version:
            raise APIError(
                409, ErrorCode.STALE_VERSION, "Room was modified by someone else", {"current_version": r.version}
            )
        other = await self.rooms.by_code(r.college_id, body.code)
        if other is not None and other.id != r.id:
            raise APIError(409, ErrorCode.CONFLICT, "Room code already exists in this college", {"field": "code"})
        old = snap(r, ROOM_KEYS)
        for k, v in body.model_dump(exclude={"college_id", "features", "department_id"}).items():
            setattr(r, k, v)
        r.features = features
        await self.db.flush()
        await self._audit("update", "room", r.id, old, snap(r, ROOM_KEYS))
        return (await self.room_outs([r]))[0]

    async def delete_room(self, room_id: uuid.UUID) -> None:
        r = await self.rooms.get_one(room_id, for_update=True)
        await self._assert_room_write(r.room_type, _features(r))
        if await self.rooms.entries_using(r.id):
            raise APIError(409, ErrorCode.CONFLICT, "The room is used by a published timetable", {"reason": "in_use"})
        await self.rooms.soft_delete(r, self.actor_id)
        await self._audit("delete", "room", r.id, snap(r, ROOM_KEYS), None)

    async def availability(
        self,
        on: date,
        slot_id: uuid.UUID,
        room_type: str | None,
        college_id: uuid.UUID | None,
        min_capacity: int | None,
    ) -> list[RoomAvailability]:
        slot = await self.slots.get_one(slot_id)
        rooms = list(
            (
                await self.db.execute(
                    self.rooms.filtered(
                        college_id=college_id or slot.college_id,
                        room_type=room_type,
                        min_capacity=min_capacity,
                        active_only=True,
                    ).order_by(Room.code)
                )
            )
            .scalars()
            .all()
        )
        pattern = "odd" if on.isocalendar().week % 2 == 1 else "even"
        term = await self.current_term(slot.college_id)
        busy = await self.rooms.busy_on(term.id if term else None, on.isoweekday(), [slot.id], ("all", pattern))
        sessions = await self.rooms.busy_sessions(on, slot.start_time, slot.end_time)
        entry_ids = [e for ids in busy.values() for e in ids]
        entries = await self._rows(TimetableEntry, entry_ids)
        oc = await self.offering_courses(
            [e.offering_id for e in entries.values()] + [s.offering_id for v in sessions.values() for s in v]
        )
        outs = await self.room_outs(rooms)
        result = []
        for r, out in zip(rooms, outs, strict=True):
            labels = []
            for eid in busy.get(r.id, []):
                e = entries.get(eid)
                c = oc.get(e.offering_id, (None, None))[1] if e else None
                labels.append(c.code if c else "timetable")
            for s in sessions.get(r.id, []):
                c = oc.get(s.offering_id, (None, None))[1]
                labels.append(f"{c.code if c else 'session'} {s.start_time:%H:%M}")
            result.append(RoomAvailability(room=out, free=not labels, busy_with=list(dict.fromkeys(labels))))
        return result

    # ---- slots ---------------------------------------------------------------------------------------------------
    async def list_slots(self, college_id: uuid.UUID | None, slot_group: str | None) -> list[SlotOut]:
        return [SlotOut.model_validate(s) for s in await self.slots.group(college_id, slot_group)]

    async def replace_group(self, body: SlotGroupReplace) -> list[SlotOut]:
        self._assert_full()
        college_id = await self.default_college(body.college_id)
        ordered = sorted(body.slots, key=lambda s: s.start_time)
        for a, b in zip(ordered, ordered[1:], strict=False):
            if minutes(b.start_time) < minutes(a.end_time):
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"Slots {a.name} and {b.name} overlap",
                    {"field": "slots", "overlap": [a.name, b.name]},
                )
        names = [s.name for s in ordered]
        if len(set(names)) != len(names):
            raise APIError(422, ErrorCode.VALIDATION, "Slot names must be unique", {"field": "slots"})
        existing = {
            s.name: s
            for s in (
                await self.db.execute(
                    select(TimeSlot)
                    .where(
                        TimeSlot.institution_id == self.inst,
                        TimeSlot.college_id == college_id,
                        TimeSlot.slot_group == body.slot_group,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        }
        used: set[uuid.UUID] = set()
        if existing:
            used = set(
                (
                    await self.db.execute(
                        select(TimetableEntry.time_slot_id)
                        .where(TimetableEntry.time_slot_id.in_([s.id for s in existing.values()]))
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
        for i, s in enumerate(ordered, start=1):
            row = existing.pop(s.name, None)
            if row is None:
                row = TimeSlot(institution_id=self.inst, college_id=college_id, slot_group=body.slot_group, name=s.name)
                self.db.add(row)
            row.sequence, row.start_time, row.end_time = i, s.start_time, s.end_time
            row.slot_type, row.is_active = s.slot_type.value, True
        for leftover in existing.values():
            if leftover.id in used:
                leftover.is_active = False
            else:
                await self.db.delete(leftover)
        await self.db.flush()
        await self._audit(
            "replace",
            "time_slot_group",
            None,
            None,
            {"college_id": str(college_id), "slot_group": body.slot_group, "slots": names},
        )
        return await self.list_slots(college_id, body.slot_group)
