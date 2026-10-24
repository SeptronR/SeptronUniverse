"""Hostel structure — Prompts/20 §20.6 ``structure_service``.

Hostels (type, warden; ``capacity`` = Σ beds, recomputed on every bed change), blocks, rooms generated in bulk from a
``number_pattern`` (``{floor}`` / ``{seq:02}`` / ``{block}``), beds per capacity (labels A, B, C…); rooms in
``maintenance`` / ``blocked`` keep their beds but are skipped by allotment; fee plans per hostel × room type × year;
occupancy map (blocks → rooms → beds with the resident).
"""

import re
import uuid
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.hostel import ACTIVE_ALLOCATION, BED_LABELS, ROOM_CAPACITY
from app.models.hostel import Hostel, HostelAllocation, HostelBed, HostelBlock, HostelFeePlan, HostelRoom
from app.models.hr import Staff
from app.schemas.hostel import (
    BedStatusChange,
    HostelBedOut,
    HostelBlockIn,
    HostelBlockOut,
    HostelFeePlanIn,
    HostelFeePlanOut,
    HostelIn,
    HostelOut,
    HostelRoomIn,
    HostelRoomOut,
    HostelUpdate,
    OccupancyBlock,
    OccupancyResponse,
    RoomBulkCreate,
)
from app.services.hostel.common import HostelBase, hostel_predicate, rule


def render_room_number(pattern: str, floor: int, seq: int, block: str) -> str:
    def sub(m: re.Match[str]) -> str:
        name, width = m.group(1), m.group(2)
        val = {"floor": floor, "seq": seq, "block": block}.get(name, "")
        if width and isinstance(val, int):
            return f"{val:0{int(width)}d}"
        return str(val)

    return re.sub(r"\{(\w+)(?::(\d+))?\}", sub, pattern)[:20]


class StructureService(HostelBase):
    async def _counts(self, hostel_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
        out: dict[uuid.UUID, dict[str, int]] = {
            h: {"beds": 0, "occupied": 0, "allotted": 0, "blocks": 0} for h in hostel_ids
        }
        if not hostel_ids:
            return out
        for hid, n in (
            await self.db.execute(
                select(HostelBlock.hostel_id, func.count(HostelBed.id))
                .join(HostelRoom, HostelRoom.block_id == HostelBlock.id)
                .join(HostelBed, HostelBed.room_id == HostelRoom.id)
                .where(HostelBlock.hostel_id.in_(hostel_ids))
                .group_by(HostelBlock.hostel_id)
            )
        ).all():
            out[hid]["beds"] = int(n)
        for hid, status, n in (
            await self.db.execute(
                select(HostelAllocation.hostel_id, HostelAllocation.status, func.count())
                .where(HostelAllocation.hostel_id.in_(hostel_ids), HostelAllocation.status.in_(ACTIVE_ALLOCATION))
                .group_by(HostelAllocation.hostel_id, HostelAllocation.status)
            )
        ).all():
            out[hid]["occupied" if status == "checked_in" else "allotted"] += int(n)
        for hid, n in (
            await self.db.execute(
                select(HostelBlock.hostel_id, func.count())
                .where(HostelBlock.hostel_id.in_(hostel_ids))
                .group_by(HostelBlock.hostel_id)
            )
        ).all():
            out[hid]["blocks"] = int(n)
        return out

    async def outs(self, rows: list[Hostel]) -> list[HostelOut]:
        counts = await self._counts([h.id for h in rows])
        wardens: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(Staff.id, Staff.first_name).where(
                        Staff.id.in_({h.warden_staff_id for h in rows if h.warden_staff_id} or {uuid.uuid4()})
                    )
                )
            ).all()  # type: ignore[arg-type]
        )
        return [
            HostelOut(
                id=h.id,
                college_id=h.college_id,
                name=h.name,
                hostel_type=h.hostel_type,
                warden_staff_id=h.warden_staff_id,
                warden_name=wardens.get(h.warden_staff_id),
                capacity=h.capacity,
                occupied=counts[h.id]["occupied"],
                allotted=counts[h.id]["allotted"],
                vacant=max(counts[h.id]["beds"] - counts[h.id]["occupied"] - counts[h.id]["allotted"], 0),
                blocks=counts[h.id]["blocks"],
                mess_id=h.mess_id,
                is_active=h.is_active,
            )
            for h in rows
        ]

    async def list_hostels(self, college_id: uuid.UUID | None = None) -> list[HostelOut]:
        q = select(Hostel).where(
            Hostel.institution_id == self.inst, Hostel.deleted_at.is_(None), hostel_predicate(self.principal)
        )
        if college_id:
            q = q.where(Hostel.college_id == college_id)
        return await self.outs(list((await self.db.execute(q.order_by(Hostel.name))).scalars().all()))

    async def get(self, hostel_id: uuid.UUID) -> HostelOut:
        return (await self.outs([await self.hostel(hostel_id)]))[0]

    async def create(self, body: HostelIn) -> HostelOut:
        self.require("manage")
        h = Hostel(institution_id=self.inst, capacity=0, **body.model_dump())
        self.db.add(h)
        await self.db.flush()
        await self.db.refresh(h)
        await self._audit("hostel_create", "hostel", h.id, None, body.model_dump(mode="json"))
        return (await self.outs([h]))[0]

    async def update(self, hostel_id: uuid.UUID, body: HostelUpdate) -> HostelOut:
        self.require("manage")
        h = await self.hostel(hostel_id, for_update=True)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(h, k, v)
        h.version += 1
        await self.db.flush()
        await self.db.refresh(h)
        await self._audit("hostel_update", "hostel", h.id, None, body.model_dump(mode="json", exclude_unset=True))
        return (await self.outs([h]))[0]

    async def delete(self, hostel_id: uuid.UUID) -> None:
        self.require("manage")
        h = await self.hostel(hostel_id, for_update=True)
        active = (
            await self.db.execute(
                select(func.count())
                .select_from(HostelAllocation)
                .where(HostelAllocation.hostel_id == h.id, HostelAllocation.status.in_(ACTIVE_ALLOCATION))
            )
        ).scalar_one()
        if active:
            raise rule("Residents are allotted to this hostel", "HOSTEL_OCCUPIED")
        from app.services.hostel.common import now_utc

        h.deleted_at, h.deleted_by, h.is_active = now_utc(), self.actor_id, False
        await self.db.flush()

    async def recompute_capacity(self, hostel_id: uuid.UUID) -> None:
        n = (
            await self.db.execute(
                select(func.count(HostelBed.id))
                .join(HostelRoom, HostelRoom.id == HostelBed.room_id)
                .join(HostelBlock, HostelBlock.id == HostelRoom.block_id)
                .where(HostelBlock.hostel_id == hostel_id)
            )
        ).scalar_one()
        h = (await self.db.execute(select(Hostel).where(Hostel.id == hostel_id))).scalar_one()
        h.capacity = min(int(n), 32767)
        await self.db.flush()

    # ---- blocks / rooms / beds --------------------------------------------------------------------------------------
    async def blocks(self, hostel_id: uuid.UUID) -> list[HostelBlockOut]:
        await self.hostel(hostel_id)
        rows = (
            await self.db.execute(
                select(HostelBlock, func.count(HostelRoom.id))
                .outerjoin(HostelRoom, HostelRoom.block_id == HostelBlock.id)
                .where(HostelBlock.hostel_id == hostel_id)
                .group_by(HostelBlock.id)
                .order_by(HostelBlock.name)
            )
        ).all()
        return [
            HostelBlockOut(id=b.id, hostel_id=b.hostel_id, name=b.name, floors=b.floors, rooms=int(n)) for b, n in rows
        ]

    async def create_block(self, hostel_id: uuid.UUID, body: HostelBlockIn) -> HostelBlockOut:
        self.require("manage")
        await self.hostel(hostel_id)
        b = HostelBlock(institution_id=self.inst, hostel_id=hostel_id, **body.model_dump())
        self.db.add(b)
        await self.db.flush()
        return HostelBlockOut(id=b.id, hostel_id=hostel_id, name=b.name, floors=b.floors)

    async def bulk_rooms(self, hostel_id: uuid.UUID, body: RoomBulkCreate) -> dict[str, int]:
        self.require("manage")
        await self.hostel(hostel_id)
        block = (
            await self.db.execute(
                select(HostelBlock).where(HostelBlock.id == body.block_id, HostelBlock.hostel_id == hostel_id)
            )
        ).scalar_one_or_none()
        if block is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Block not found in this hostel")
        if body.floor_to < body.floor_from:
            raise APIError(422, ErrorCode.VALIDATION, "floor_to precedes floor_from")
        capacity = body.capacity or ROOM_CAPACITY.get(body.room_type, 2)
        rooms = beds = skipped = 0
        existing = set(
            (await self.db.execute(select(HostelRoom.room_number).where(HostelRoom.block_id == block.id)))
            .scalars()
            .all()
        )
        for floor in range(body.floor_from, body.floor_to + 1):
            for seq in range(1, body.rooms_per_floor + 1):
                number = render_room_number(body.number_pattern, floor, seq, block.name)
                if number in existing:
                    skipped += 1
                    continue
                r = HostelRoom(
                    institution_id=self.inst,
                    block_id=block.id,
                    room_number=number,
                    floor=floor,
                    capacity=capacity,
                    room_type=body.room_type,
                    has_ac=body.has_ac,
                )
                self.db.add(r)
                await self.db.flush()
                for i in range(capacity):
                    self.db.add(
                        HostelBed(
                            institution_id=self.inst,
                            room_id=r.id,
                            bed_label=BED_LABELS[i] if i < len(BED_LABELS) else str(i + 1),
                        )
                    )
                rooms += 1
                beds += capacity
                existing.add(number)
        block.floors = max(block.floors, body.floor_to + 1 if body.floor_from == 0 else body.floor_to)
        await self.db.flush()
        await self.recompute_capacity(hostel_id)
        await self._audit(
            "rooms_bulk", "hostel", hostel_id, None, {"rooms": rooms, "beds": beds, "pattern": body.number_pattern}
        )
        return {"rooms": rooms, "beds": beds, "skipped": skipped}

    async def _room(self, room_id: uuid.UUID) -> tuple[HostelRoom, uuid.UUID]:
        row = (
            await self.db.execute(
                select(HostelRoom, HostelBlock.hostel_id)
                .join(HostelBlock, HostelBlock.id == HostelRoom.block_id)
                .where(HostelRoom.id == room_id, HostelRoom.institution_id == self.inst)
            )
        ).first()
        if row is None or not await self.owns_hostel(row[1]):
            raise APIError(404, ErrorCode.NOT_FOUND, "Room not found")
        return row[0], row[1]

    async def room_out(self, r: HostelRoom) -> HostelRoomOut:
        beds = (
            (await self.db.execute(select(HostelBed).where(HostelBed.room_id == r.id).order_by(HostelBed.bed_label)))
            .scalars()
            .all()
        )
        allocs = {
            a.bed_id: a
            for a in (
                await self.db.execute(
                    select(HostelAllocation).where(
                        HostelAllocation.bed_id.in_([b.id for b in beds] or [uuid.uuid4()]),
                        HostelAllocation.status.in_(ACTIVE_ALLOCATION),
                    )
                )
            )
            .scalars()
            .all()
        }
        refs = await self.refs([a.student_program_enrollment_id for a in allocs.values()])
        return HostelRoomOut(
            id=r.id,
            block_id=r.block_id,
            room_number=r.room_number,
            floor=r.floor,
            capacity=r.capacity,
            room_type=r.room_type,
            has_ac=r.has_ac,
            status=r.status,
            beds=[
                HostelBedOut(
                    id=b.id,
                    bed_label=b.bed_label,
                    status=b.status,
                    allocation_id=allocs[b.id].id if b.id in allocs else None,
                    resident=refs[allocs[b.id].student_program_enrollment_id].name
                    if b.id in allocs and allocs[b.id].student_program_enrollment_id in refs
                    else None,
                    registration_number=refs[allocs[b.id].student_program_enrollment_id].registration_number
                    if b.id in allocs and allocs[b.id].student_program_enrollment_id in refs
                    else None,
                )
                for b in beds
            ],
        )

    async def get_room(self, room_id: uuid.UUID) -> HostelRoomOut:
        r, _ = await self._room(room_id)
        return await self.room_out(r)

    async def update_room(self, room_id: uuid.UUID, body: HostelRoomIn) -> HostelRoomOut:
        self.require("manage", "warden")
        r, hid = await self._room(room_id)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(r, k, v)
        await self.db.flush()
        await self._audit("room_update", "hostel_room", r.id, None, body.model_dump(mode="json", exclude_unset=True))
        return await self.room_out(r)

    async def bed_status(self, bed_id: uuid.UUID, body: BedStatusChange) -> HostelBedOut:
        self.require("manage", "warden")
        bed = (
            await self.db.execute(
                select(HostelBed).where(HostelBed.id == bed_id, HostelBed.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if bed is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Bed not found")
        await self._room(bed.room_id)
        if bed.status == "allocated":
            raise rule("The bed is allocated — transfer or vacate the resident first", "BED_ALLOCATED")
        bed.status = body.status
        await self.db.flush()
        return HostelBedOut(id=bed.id, bed_label=bed.bed_label, status=bed.status)

    async def occupancy(self, hostel_id: uuid.UUID) -> OccupancyResponse:
        h = await self.hostel(hostel_id)
        blocks = (
            (await self.db.execute(select(HostelBlock).where(HostelBlock.hostel_id == h.id).order_by(HostelBlock.name)))
            .scalars()
            .all()
        )
        out_blocks = []
        totals = {"rooms": 0, "beds": 0, "vacant": 0, "allotted": 0, "occupied": 0, "blocked": 0}
        for b in blocks:
            rooms = (
                (
                    await self.db.execute(
                        select(HostelRoom)
                        .where(HostelRoom.block_id == b.id)
                        .order_by(HostelRoom.floor, HostelRoom.room_number)
                    )
                )
                .scalars()
                .all()
            )
            outs = [await self.room_out(r) for r in rooms]
            for ro in outs:
                totals["rooms"] += 1
                for bed in ro.beds:
                    totals["beds"] += 1
                    if bed.status == "blocked":
                        totals["blocked"] += 1
                    elif bed.allocation_id:
                        totals["allotted"] += 1
                        if bed.status == "allocated":
                            totals["occupied"] += 1
                    else:
                        totals["vacant"] += 1
            out_blocks.append(OccupancyBlock(id=b.id, name=b.name, rooms=outs))
        return OccupancyResponse(hostel=(await self.outs([h]))[0], blocks=out_blocks, totals=totals)

    # ---- fee plans --------------------------------------------------------------------------------------------------
    async def fee_plans(
        self, hostel_id: uuid.UUID | None, academic_year_id: uuid.UUID | None
    ) -> list[HostelFeePlanOut]:
        q = select(HostelFeePlan).where(HostelFeePlan.institution_id == self.inst)
        if hostel_id:
            q = q.where(HostelFeePlan.hostel_id == hostel_id)
        if academic_year_id:
            q = q.where(HostelFeePlan.academic_year_id == academic_year_id)
        rows = (await self.db.execute(q)).scalars().all()
        return [
            HostelFeePlanOut(
                id=r.id,
                hostel_id=r.hostel_id,
                room_type=r.room_type,
                academic_year_id=r.academic_year_id,
                fee_per_term_paise=r.fee_per_term_paise,
                caution_deposit_paise=r.caution_deposit_paise,
                mess_advance_paise=r.mess_advance_paise,
            )
            for r in rows
        ]

    async def save_fee_plan(self, body: HostelFeePlanIn, plan_id: uuid.UUID | None = None) -> HostelFeePlanOut:
        self.require("manage")
        await self.hostel(body.hostel_id)
        row: HostelFeePlan | None
        if plan_id is None:
            row = (
                await self.db.execute(
                    select(HostelFeePlan).where(
                        HostelFeePlan.hostel_id == body.hostel_id,
                        HostelFeePlan.room_type == body.room_type,
                        HostelFeePlan.academic_year_id == body.academic_year_id,
                    )
                )
            ).scalar_one_or_none()
        else:
            row = (
                await self.db.execute(
                    select(HostelFeePlan).where(HostelFeePlan.id == plan_id, HostelFeePlan.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if row is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Fee plan not found")
        if row is None:
            row = HostelFeePlan(institution_id=self.inst, **body.model_dump())
            self.db.add(row)
        else:
            for k, v in body.model_dump().items():
                setattr(row, k, v)
        await self.db.flush()
        await self._audit("fee_plan_save", "hostel_fee_plan", row.id, None, body.model_dump(mode="json"))
        return (
            (await self.fee_plans(body.hostel_id, body.academic_year_id))[0]
            if plan_id is None
            else HostelFeePlanOut(id=row.id, **body.model_dump())
        )

    async def rules_text(self, hostel: Hostel) -> list[str]:
        late = await self.setting("hostel", "late_grace_minutes")
        return [
            f"{hostel.name} — hostel rules",
            "",
            f"1. Night roll-call at {await self.setting('hostel', 'roll_call_time') or '21:30'}; residents must be present.",
            f"2. Out-pass / leave through the app; return within {late or 30} minutes of the approved time.",
            "3. Visitors only in the visitors' area during visiting hours; register at the gate.",
            "4. Damage to hostel property is charged to the resident(s).",
            "5. Ragging, alcohol and substances are prohibited — disciplinary action applies.",
        ]
