"""Applications, allotment and allocations — Prompts/20 §20.6 ``application_service`` / ``allocation_service``.

* **apply** (students; window ``hostel.application_window`` per year when set): one per enrolment and year; blocked by
  open ``hostel`` / ``all`` holds (409 ``HOLD_HOSTEL``) or an eviction in the past two years (409 ``EVICTED``);
  hostel preferences must match the student's gender (422 ``GENDER_RULE``); ``priority_score`` = distance band + category
  bonus + PwD + CGPA × factor (weights ``hostel.priority_weights``).
* **allotment run** (``hostel:allot``; job, ``dry_run``): applications by score DESC, created_at → first preferred hostel
  with a vacant bed (``room_type_pref``, any type when ``hostel.room_type_fallback``) locked ``FOR UPDATE SKIP LOCKED``;
  the rest are waitlisted. Allotment raises the hostel-fee invoice (``source_type='hostel_allocation'``, head HOSTEL)
  and a caution-deposit invoice (head CAUTION) unless a deposit is already held (``hostel.deposit_once``). Unpaid
  allotments lapse after ``hostel.accept_days``; freed beds go to the waitlist in score order.
* **check-in** (warden of the hostel): hostel fee paid unless ``hostel.fee_before_checkin`` is off (409
  ``FEE_PENDING``); room condition / inventory recorded; bed ``allocated``; room ``full`` when every bed is taken.
* **transfer**: old allocation ``transferred``, new ``checked_in`` in one transaction; a room-type change raises the fee
  difference (credit differences are noted on the audit row — refunds stay with the accounts office).
* **room change** (``hostel.room_change``): student request → workflow ``hostel.room_change`` (warden) → applied.
* **vacate**: damages → invoice (``hostel_allocation`` / Damages), allocation ``vacated``, bed freed, waitlist promoted,
  a ``no_dues_requests(purpose='hostel_vacate')``; when cleared and nothing hostel / mess is unpaid a caution-deposit
  refund request (``fee_refunds``) net of dues is raised for the accountant.
* **evict**: warden proposes → workflow ``hostel.eviction`` (warden → registrar) → allocation ``evicted``, bed freed,
  disciplinary ``eviction`` record and a ``hostel`` hold for ``hostel.eviction_hold_days``.
* **no-dues hook**: the hostel sign-off is cleared when the enrolment has no active allocation and no unpaid hostel /
  mess invoices, else ``dues_pending`` with the amount.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.enums.hostel import ACTIVE_ALLOCATION, GENDER_HOSTELS, PRIORITY_WEIGHTS
from app.models.fees import FeeInvoice, FeeRefund, NoDuesRequest, NoDuesSignoff
from app.models.hostel import (
    Hostel,
    HostelAllocation,
    HostelApplication,
    HostelBed,
    HostelBlock,
    HostelDisciplinaryRecord,
    HostelFeePlan,
    HostelRoom,
    MessBill,
    MessSubscription,
    RoomChangeRequest,
)
from app.models.platform import WorkflowInstance
from app.models.students import Student, StudentHold, StudentProgramEnrollment
from app.schemas.hostel import (
    AllotmentRunRequest,
    AllotmentRunSummary,
    CheckInRequest,
    EvictRequest,
    HostelAllocationResponse,
    HostelApplicationCreate,
    HostelApplicationResponse,
    HostelTransferRequest,
    ManualAllotRequest,
    RoomChangeCreate,
    RoomChangeDecision,
    RoomChangeResponse,
    VacateRequest,
    VacateResponse,
)
from app.services.hostel.common import HostelBase, now_utc, resident_predicate, rule, visible_hostel_ids

OPEN = ("pending", "partial", "overdue")


class AllocationService(HostelBase):
    # ---- applications -----------------------------------------------------------------------------------------------
    async def score(self, e: StudentProgramEnrollment, st: Student, distance_km: float | None) -> Decimal:
        weights = {**PRIORITY_WEIGHTS, **(await self.setting("hostel", "priority_weights") or {})}
        pts = 0.0
        for band in sorted(weights.get("distance_bands") or [], key=lambda b: -float(b.get("min_km", 0))):
            if distance_km is not None and distance_km >= float(band.get("min_km", 0)):
                pts += float(band.get("points", 0))
                break
        pts += float((weights.get("category") or {}).get((st.category or "").upper(), 0))
        if st.is_pwd:
            pts += float(weights.get("pwd", 100))
        if e.cgpa is not None:
            pts += float(e.cgpa) * float(weights.get("cgpa_factor", 2))
        return Decimal(str(round(pts, 2)))

    async def app_outs(self, rows: list[HostelApplication]) -> list[HostelApplicationResponse]:
        refs = await self.refs([r.student_program_enrollment_id for r in rows])
        allocs: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(HostelAllocation.student_program_enrollment_id, HostelAllocation.id).where(
                        HostelAllocation.student_program_enrollment_id.in_(
                            [r.student_program_enrollment_id for r in rows] or [uuid.uuid4()]
                        ),
                        HostelAllocation.status.in_(ACTIVE_ALLOCATION),
                    )
                )
            ).all()  # type: ignore[arg-type]
        )
        out = []
        for r in rows:
            pos = None
            if r.status == "waitlisted":
                pos = int(
                    (
                        await self.db.execute(
                            select(func.count())
                            .select_from(HostelApplication)
                            .where(
                                HostelApplication.academic_year_id == r.academic_year_id,
                                HostelApplication.status == "waitlisted",
                                or_(
                                    HostelApplication.priority_score > (r.priority_score or 0),
                                    (HostelApplication.priority_score == (r.priority_score or 0))
                                    & (HostelApplication.created_at <= r.created_at),
                                ),
                            )
                        )
                    ).scalar_one()
                )
            out.append(
                HostelApplicationResponse(
                    id=r.id,
                    student=refs.get(r.student_program_enrollment_id)
                    or {"enrollment_id": r.student_program_enrollment_id},  # type: ignore[arg-type]
                    academic_year_id=r.academic_year_id,
                    hostel_preference=[uuid.UUID(x) for x in (r.hostel_preference or [])],
                    room_type_pref=r.room_type_pref,
                    distance_km=float(r.distance_km) if r.distance_km is not None else None,
                    priority_score=float(r.priority_score) if r.priority_score is not None else None,
                    status=r.status,
                    position=pos,
                    allocation_id=allocs.get(r.student_program_enrollment_id),
                    created_at=r.created_at,
                )
            )
        return out

    async def apply(self, body: HostelApplicationCreate) -> HostelApplicationResponse:
        e = await self.my_enrolment(body.enrollment_id)
        st = (await self.db.execute(select(Student).where(Student.id == e.student_id))).scalar_one()
        year_id = body.academic_year_id or (await self.academic_year()).id
        window = await self.setting("hostel", "application_window")
        today = await self.today()
        if isinstance(window, dict) and window.get(str(year_id)):
            w = window[str(year_id)]
            if (w.get("from") and today < date.fromisoformat(w["from"])) or (
                w.get("to") and today > date.fromisoformat(w["to"])
            ):
                raise rule("The hostel application window is closed", "WINDOW_CLOSED")
        held = (
            await self.db.execute(
                select(func.count())
                .select_from(StudentHold)
                .where(
                    StudentHold.student_program_enrollment_id == e.id,
                    StudentHold.released_at.is_(None),
                    StudentHold.hold_type.in_(("hostel", "all")),
                )
            )
        ).scalar_one()
        if held:
            raise rule("A hostel hold blocks the application", "HOLD_HOSTEL")
        evicted = (
            await self.db.execute(
                select(func.count())
                .select_from(HostelDisciplinaryRecord)
                .where(
                    HostelDisciplinaryRecord.student_program_enrollment_id == e.id,
                    HostelDisciplinaryRecord.action == "eviction",
                    HostelDisciplinaryRecord.incident_on >= today - timedelta(days=730),
                )
            )
        ).scalar_one()
        if evicted:
            raise rule("Evicted residents cannot re-apply within two years", "EVICTED")
        hostels = (
            (
                await self.db.execute(
                    select(Hostel).where(
                        Hostel.id.in_(body.hostel_preference),
                        Hostel.institution_id == self.inst,
                        Hostel.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(hostels) != len(set(body.hostel_preference)):
            raise APIError(422, ErrorCode.VALIDATION, "Unknown hostel in preferences", {"code": "UNKNOWN_HOSTEL"})
        allowed = GENDER_HOSTELS.get((st.gender or "").lower(), ("coed", "pg", "international"))
        bad = [h.name for h in hostels if h.hostel_type not in allowed]
        if bad:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Not allowed for your gender: {', '.join(bad)}",
                {"code": "GENDER_RULE", "hostels": bad},
            )
        dup = (
            await self.db.execute(
                select(HostelApplication.id).where(
                    HostelApplication.student_program_enrollment_id == e.id,
                    HostelApplication.academic_year_id == year_id,
                )
            )
        ).first()
        if dup:
            raise rule("You already applied for this year", "ALREADY_APPLIED", application_id=str(dup[0]))
        app = HostelApplication(
            institution_id=self.inst,
            student_program_enrollment_id=e.id,
            academic_year_id=year_id,
            hostel_preference=[str(h) for h in body.hostel_preference],
            room_type_pref=body.room_type_pref,
            distance_km=body.distance_km,
            priority_score=await self.score(e, st, body.distance_km),
            status="applied",
        )
        self.db.add(app)
        await self.db.flush()
        await self.db.refresh(app)
        await self._emit("hostel.applied", {"application_id": str(app.id)}, "hostel_application", app.id)
        await self._notify("hostel.applied", [st.user_id], {"score": str(app.priority_score)})
        return (await self.app_outs([app]))[0]

    async def my_applications(self) -> list[HostelApplicationResponse]:
        rows = list(
            (
                await self.db.execute(
                    select(HostelApplication).where(
                        HostelApplication.student_program_enrollment_id.in_(await self.mine() or [uuid.uuid4()])
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.app_outs(rows)

    async def cancel_application(self, app_id: uuid.UUID) -> HostelApplicationResponse:
        a = (
            await self.db.execute(
                select(HostelApplication)
                .where(
                    HostelApplication.id == app_id,
                    HostelApplication.student_program_enrollment_id.in_(await self.mine() or [uuid.uuid4()]),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Application not found")
        if a.status not in ("applied", "waitlisted"):
            raise rule(f"The application is {a.status}", "NOT_CANCELLABLE")
        a.status = "cancelled"
        await self.db.flush()
        await self.db.refresh(a)
        return (await self.app_outs([a]))[0]

    async def list_applications(
        self, year_id: uuid.UUID | None, hostel_id: uuid.UUID | None, status: str | None
    ) -> list[HostelApplicationResponse]:
        self.require("allot", "view_all", "warden")
        q = select(HostelApplication).where(HostelApplication.institution_id == self.inst)
        if year_id:
            q = q.where(HostelApplication.academic_year_id == year_id)
        if status:
            q = q.where(HostelApplication.status == status)
        if hostel_id:
            q = q.where(HostelApplication.hostel_preference.contains([str(hostel_id)]))
        rows = list(
            (
                await self.db.execute(
                    q.order_by(
                        HostelApplication.priority_score.desc().nulls_last(), HostelApplication.created_at
                    ).limit(5000)
                )
            )
            .scalars()
            .all()
        )
        return await self.app_outs(rows)

    # ---- allotment ----------------------------------------------------------------------------------------------------
    async def _vacant_bed(self, hostel_id: uuid.UUID, room_type: str | None, *, lock: bool = True) -> HostelBed | None:
        q = (
            select(HostelBed)
            .join(HostelRoom, HostelRoom.id == HostelBed.room_id)
            .join(HostelBlock, HostelBlock.id == HostelRoom.block_id)
            .where(
                HostelBlock.hostel_id == hostel_id,
                HostelBed.status == "vacant",
                HostelRoom.status.in_(("available",)),
                ~HostelBed.id.in_(
                    select(HostelAllocation.bed_id).where(HostelAllocation.status.in_(ACTIVE_ALLOCATION))
                ),
            )
            .order_by(HostelBlock.name, HostelRoom.floor, HostelRoom.room_number, HostelBed.bed_label)
            .limit(1)
        )
        if room_type:
            q = q.where(HostelRoom.room_type == room_type)
        if lock:
            q = q.with_for_update(skip_locked=True, of=HostelBed)
        return (await self.db.execute(q)).scalars().first()

    async def run_allotment(self, body: AllotmentRunRequest) -> AllotmentRunSummary:
        self.require("allot")
        year_id = body.academic_year_id or (await self.academic_year()).id
        apps = list(
            (
                await self.db.execute(
                    select(HostelApplication)
                    .where(
                        HostelApplication.institution_id == self.inst,
                        HostelApplication.academic_year_id == year_id,
                        HostelApplication.status.in_(("applied", "waitlisted")),
                    )
                    .order_by(HostelApplication.priority_score.desc().nulls_last(), HostelApplication.created_at)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        scope_ids: set[str] | None = None
        if body.hostel_ids:
            scope_ids = {str(h) for h in body.hostel_ids}
        elif body.college_id:
            scope_ids = {
                str(h)
                for h in (await self.db.execute(select(Hostel.id).where(Hostel.college_id == body.college_id)))
                .scalars()
                .all()
            }
        fallback = bool(
            await self.setting("hostel", "room_type_fallback")
            if await self.setting("hostel", "room_type_fallback") is not None
            else True
        )
        summary = AllotmentRunSummary(dry_run=body.dry_run)
        taken: set[uuid.UUID] = set()
        names: dict[Any, Any] = dict(
            (await self.db.execute(select(Hostel.id, Hostel.name).where(Hostel.institution_id == self.inst))).all()  # type: ignore[arg-type]
        )  # type: ignore[arg-type]
        for a in apps:
            prefs = [p for p in (a.hostel_preference or []) if scope_ids is None or p in scope_ids]
            if not prefs:
                continue
            summary.considered += 1
            active = (
                await self.db.execute(
                    select(HostelAllocation.id).where(
                        HostelAllocation.student_program_enrollment_id == a.student_program_enrollment_id,
                        HostelAllocation.status.in_(ACTIVE_ALLOCATION),
                    )
                )
            ).first()
            if active:
                continue
            bed = None
            hostel_id = None
            for p in prefs:
                for rt in [a.room_type_pref, None] if fallback and a.room_type_pref else [a.room_type_pref]:
                    candidate = await self._vacant_bed(uuid.UUID(p), rt, lock=not body.dry_run)
                    if body.dry_run:
                        # walk past beds already promised in this dry run
                        while candidate is not None and candidate.id in taken:
                            q = (
                                select(HostelBed)
                                .join(HostelRoom, HostelRoom.id == HostelBed.room_id)
                                .join(HostelBlock, HostelBlock.id == HostelRoom.block_id)
                                .where(
                                    HostelBlock.hostel_id == uuid.UUID(p),
                                    HostelBed.status == "vacant",
                                    HostelRoom.status == "available",
                                    ~HostelBed.id.in_(taken),
                                )
                            )
                            if rt:
                                q = q.where(HostelRoom.room_type == rt)
                            candidate = (await self.db.execute(q.limit(1))).scalars().first()
                    if candidate is not None:
                        bed, hostel_id = candidate, uuid.UUID(p)
                        break
                if bed is not None:
                    break
            if bed is None or hostel_id is None:
                summary.waitlisted += 1
                if not body.dry_run and a.status != "waitlisted":
                    a.status = "waitlisted"
                    await self._emit("hostel.waitlisted", {"application_id": str(a.id)}, "hostel_application", a.id)
                    await self._notify(
                        "hostel.waitlisted",
                        [await self.student_user(a.student_program_enrollment_id)],
                        {"year": str(year_id)},
                    )
                continue
            taken.add(bed.id)
            summary.allotted += 1
            summary.by_hostel[str(names.get(hostel_id, hostel_id))] = (
                summary.by_hostel.get(str(names.get(hostel_id, hostel_id)), 0) + 1
            )
            if not body.dry_run:
                await self._allot(a, bed, hostel_id)
        await self.db.flush()
        if not body.dry_run:
            await self._audit("allotment_run", "hostel_allotment", None, None, summary.model_dump(mode="json"))
        return summary

    async def _allot(self, a: HostelApplication, bed: HostelBed, hostel_id: uuid.UUID) -> HostelAllocation:
        room = (await self.db.execute(select(HostelRoom).where(HostelRoom.id == bed.room_id))).scalar_one()
        today = await self.today()
        alloc = HostelAllocation(
            institution_id=self.inst,
            student_program_enrollment_id=a.student_program_enrollment_id,
            bed_id=bed.id,
            hostel_id=hostel_id,
            academic_year_id=a.academic_year_id,
            from_on=today,
            status="allotted",
        )
        self.db.add(alloc)
        a.status = "allotted"
        await self.db.flush()
        plan = (
            await self.db.execute(
                select(HostelFeePlan).where(
                    HostelFeePlan.hostel_id == hostel_id,
                    HostelFeePlan.room_type == room.room_type,
                    HostelFeePlan.academic_year_id == a.academic_year_id,
                )
            )
        ).scalar_one_or_none()
        if plan is not None:
            if plan.fee_per_term_paise:
                alloc.fee_invoice_id = await self.invoice(
                    a.student_program_enrollment_id,
                    "hostel_allocation",
                    alloc.id,
                    [(f"Hostel fee ({room.room_type})", plan.fee_per_term_paise, "HOSTEL")],
                    "Hostel fee",
                )
            held = False
            if await self.setting("hostel", "deposit_once") in (None, True):
                held = (
                    await self.db.execute(
                        select(HostelAllocation.id).where(
                            HostelAllocation.student_program_enrollment_id == a.student_program_enrollment_id,
                            HostelAllocation.caution_deposit_invoice_id.is_not(None),
                            HostelAllocation.id != alloc.id,
                            HostelAllocation.status.in_(("checked_in", "transferred", "allotted")),
                        )
                    )
                ).first() is not None
            if plan.caution_deposit_paise and not held:
                alloc.caution_deposit_invoice_id = await self.invoice(
                    a.student_program_enrollment_id,
                    "hostel_caution_deposit",
                    alloc.id,
                    [("Hostel caution deposit (refundable)", plan.caution_deposit_paise, "CAUTION")],
                    "Hostel caution deposit",
                )
        await self.db.flush()
        await self._emit(
            "hostel.allotted",
            {"allocation_id": str(alloc.id), "application_id": str(a.id)},
            "hostel_allocation",
            alloc.id,
        )
        await self._notify(
            "hostel.allotted",
            [await self.student_user(a.student_program_enrollment_id)],
            {"room": room.room_number},
            guardians=True,
        )
        return alloc

    async def manual_allot(self, app_id: uuid.UUID, body: ManualAllotRequest) -> HostelAllocationResponse:
        self.require("allot")
        a = (
            await self.db.execute(
                select(HostelApplication)
                .where(HostelApplication.id == app_id, HostelApplication.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Application not found")
        if a.status not in ("applied", "waitlisted"):
            raise rule(f"The application is {a.status}", "NOT_ALLOTTABLE")
        bed, hostel_id = await self._bed_for(body.bed_id)
        active = (
            await self.db.execute(
                select(HostelAllocation.id).where(
                    HostelAllocation.student_program_enrollment_id == a.student_program_enrollment_id,
                    HostelAllocation.status.in_(ACTIVE_ALLOCATION),
                )
            )
        ).first()
        if active:
            raise rule("The student already holds an active allocation", "ALREADY_ALLOTTED")
        alloc = await self._allot(a, bed, hostel_id)
        return (await self.outs([alloc]))[0]

    async def _bed_for(self, bed_id: uuid.UUID) -> tuple[HostelBed, uuid.UUID]:
        row = (
            await self.db.execute(
                select(HostelBed, HostelBlock.hostel_id)
                .join(HostelRoom, HostelRoom.id == HostelBed.room_id)
                .join(HostelBlock, HostelBlock.id == HostelRoom.block_id)
                .where(HostelBed.id == bed_id, HostelBed.institution_id == self.inst)
                .with_for_update(of=HostelBed)
            )
        ).first()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Bed not found")
        bed, hostel_id = row
        busy = (
            await self.db.execute(
                select(HostelAllocation.id).where(
                    HostelAllocation.bed_id == bed.id, HostelAllocation.status.in_(ACTIVE_ALLOCATION)
                )
            )
        ).first()
        if bed.status == "blocked" or busy:
            raise rule("The bed is not vacant", "BED_NOT_VACANT")
        return bed, hostel_id

    async def decline(self, app_id: uuid.UUID) -> HostelApplicationResponse:
        self.require("allot")
        a = (
            await self.db.execute(
                select(HostelApplication)
                .where(HostelApplication.id == app_id, HostelApplication.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Application not found")
        a.status = "declined"
        await self.db.flush()
        await self.db.refresh(a)
        await self._emit("hostel.declined", {"application_id": str(a.id)}, "hostel_application", a.id)
        return (await self.app_outs([a]))[0]

    async def promote_waitlist(self, hostel_id: uuid.UUID | None = None) -> int:
        n = 0
        apps = (
            (
                await self.db.execute(
                    select(HostelApplication)
                    .where(HostelApplication.institution_id == self.inst, HostelApplication.status == "waitlisted")
                    .order_by(HostelApplication.priority_score.desc().nulls_last(), HostelApplication.created_at)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for a in apps:
            for p in a.hostel_preference or []:
                if hostel_id is not None and p != str(hostel_id):
                    continue
                bed = await self._vacant_bed(uuid.UUID(p), a.room_type_pref) or await self._vacant_bed(
                    uuid.UUID(p), None
                )
                if bed is not None:
                    await self._allot(a, bed, uuid.UUID(p))
                    n += 1
                    break
        return n

    async def lapse_unpaid(self) -> int:
        days = int(await self.setting("hostel", "accept_days") or 7)
        cutoff = now_utc() - timedelta(days=days)
        rows = (
            await self.db.execute(
                select(HostelAllocation, FeeInvoice.status)
                .join(FeeInvoice, FeeInvoice.id == HostelAllocation.fee_invoice_id)
                .where(
                    HostelAllocation.institution_id == self.inst,
                    HostelAllocation.status == "allotted",
                    HostelAllocation.created_at < cutoff,
                    FeeInvoice.status.in_(OPEN),
                )
                .with_for_update(of=HostelAllocation)
            )
        ).all()
        freed = set()
        for alloc, _st in rows:
            alloc.status, alloc.to_on = "vacated", await self.today()
            app = (
                await self.db.execute(
                    select(HostelApplication).where(
                        HostelApplication.student_program_enrollment_id == alloc.student_program_enrollment_id,
                        HostelApplication.academic_year_id == alloc.academic_year_id,
                    )
                )
            ).scalar_one_or_none()
            if app is not None:
                app.status = "cancelled"
            from app.services.fees.invoice_service import InvoiceService  # noqa: F401  (invoices stay for the record)

            freed.add(alloc.hostel_id)
            await self._emit("hostel.allotment_lapsed", {"allocation_id": str(alloc.id)}, "hostel_allocation", alloc.id)
        await self.db.flush()
        for h in freed:
            await self.promote_waitlist(h)
        return len(rows)

    # ---- allocations ------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[HostelAllocation]) -> list[HostelAllocationResponse]:
        if not rows:
            return []
        refs = await self.refs([r.student_program_enrollment_id for r in rows])
        beds = {
            b: (rn, bl)
            for b, rn, bl in (
                await self.db.execute(
                    select(HostelBed.id, HostelRoom.room_number, HostelBed.bed_label)
                    .join(HostelRoom, HostelRoom.id == HostelBed.room_id)
                    .where(HostelBed.id.in_({r.bed_id for r in rows}))
                )
            ).all()
        }
        hostels: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(select(Hostel.id, Hostel.name).where(Hostel.id.in_({r.hostel_id for r in rows})))
            ).all()
        )  # type: ignore[arg-type]
        inv_ids = {i for r in rows for i in (r.fee_invoice_id, r.caution_deposit_invoice_id) if i}
        inv: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(FeeInvoice.id, FeeInvoice.status).where(FeeInvoice.id.in_(inv_ids or {uuid.uuid4()}))
                )
            ).all()
        )  # type: ignore[arg-type]
        return [
            HostelAllocationResponse(
                id=r.id,
                student=refs.get(r.student_program_enrollment_id) or {"enrollment_id": r.student_program_enrollment_id},  # type: ignore[arg-type]
                hostel_id=r.hostel_id,
                hostel=hostels.get(r.hostel_id),
                room_number=beds.get(r.bed_id, (None, None))[0],
                bed_label=beds.get(r.bed_id, (None, None))[1],
                bed_id=r.bed_id,
                academic_year_id=r.academic_year_id,
                from_on=r.from_on,
                to_on=r.to_on,
                status=r.status,
                fee_invoice_id=r.fee_invoice_id,
                fee_status=inv.get(r.fee_invoice_id),
                caution_deposit_invoice_id=r.caution_deposit_invoice_id,
                deposit_status=inv.get(r.caution_deposit_invoice_id),
                check_in_at=r.check_in_at,
                check_out_at=r.check_out_at,
                room_condition=r.room_condition,
            )
            for r in rows
        ]

    async def list_allocations(
        self, hostel_id: uuid.UUID | None, status: str | None, department_id: uuid.UUID | None
    ) -> list[HostelAllocationResponse]:
        q = (
            select(HostelAllocation)
            .join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == HostelAllocation.student_program_enrollment_id
            )
            .where(
                HostelAllocation.institution_id == self.inst,
                resident_predicate(
                    self.principal, HostelAllocation.student_program_enrollment_id, HostelAllocation.hostel_id
                ),
            )
        )
        if hostel_id:
            q = q.where(HostelAllocation.hostel_id == hostel_id)
        if status:
            q = q.where(HostelAllocation.status == status)
        if department_id:
            p = self.principal
            depts = [sid for t, sid in getattr(p, "scopes", []) if t == "department"]
            wide = (
                p is None
                or getattr(p, "is_super_admin", False)
                or any(t in ("institution", "college", "faculty") for t, _ in getattr(p, "scopes", []))
            )
            if not wide and department_id not in depts:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "That department is outside your scope")
            q = q.where(StudentProgramEnrollment.department_id == department_id)
        rows = list((await self.db.execute(q.order_by(HostelAllocation.created_at.desc()).limit(5000))).scalars().all())
        return await self.outs(rows)

    async def _alloc(self, alloc_id: uuid.UUID, *, for_update: bool = False) -> HostelAllocation:
        q = select(HostelAllocation).where(
            HostelAllocation.id == alloc_id,
            HostelAllocation.institution_id == self.inst,
            resident_predicate(
                self.principal, HostelAllocation.student_program_enrollment_id, HostelAllocation.hostel_id
            ),
        )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Allocation not found")
        return row

    async def get(self, alloc_id: uuid.UUID) -> HostelAllocationResponse:
        return (await self.outs([await self._alloc(alloc_id)]))[0]

    async def me(self, *, wards: bool = False) -> list[HostelAllocationResponse]:
        ids = await self.mine(wards=wards)
        rows = list(
            (
                await self.db.execute(
                    select(HostelAllocation)
                    .where(HostelAllocation.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                    .order_by(HostelAllocation.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows)

    async def _room_full(self, room_id: uuid.UUID) -> None:
        room = (await self.db.execute(select(HostelRoom).where(HostelRoom.id == room_id))).scalar_one()
        if room.status in ("maintenance", "blocked"):
            return
        free = (
            await self.db.execute(
                select(func.count())
                .select_from(HostelBed)
                .where(HostelBed.room_id == room_id, HostelBed.status == "vacant")
            )
        ).scalar_one()
        room.status = "full" if free == 0 else "available"

    async def check_in(self, alloc_id: uuid.UUID, body: CheckInRequest) -> HostelAllocationResponse:
        a = await self._alloc(alloc_id, for_update=True)
        await self.require_hostel(a.hostel_id, "warden", "allot")
        if a.status != "allotted":
            raise rule(f"The allocation is {a.status}", "NOT_ALLOTTED")
        if a.fee_invoice_id and await self.setting("hostel", "fee_before_checkin") in (None, True):
            status = (
                await self.db.execute(select(FeeInvoice.status).where(FeeInvoice.id == a.fee_invoice_id))
            ).scalar_one_or_none()
            if status in OPEN:
                raise rule("The hostel fee is not paid", "FEE_PENDING")
        bed = (await self.db.execute(select(HostelBed).where(HostelBed.id == a.bed_id).with_for_update())).scalar_one()
        bed.status = "allocated"
        a.status, a.check_in_at = "checked_in", now_utc()
        a.room_condition = {"check_in": body.room_condition, "inventory": body.inventory}
        await self.db.flush()
        await self._room_full(bed.room_id)
        await self.db.flush()
        await self.db.refresh(a)
        await self._audit("check_in", "hostel_allocation", a.id, None, a.room_condition)
        await self._emit("hostel.checked_in", {"allocation_id": str(a.id)}, "hostel_allocation", a.id)
        return (await self.outs([a]))[0]

    async def transfer(
        self, alloc_id: uuid.UUID, body: HostelTransferRequest, *, by_system: bool = False
    ) -> HostelAllocationResponse:
        a = await self._alloc(alloc_id, for_update=True)
        if not by_system:
            await self.require_hostel(a.hostel_id, "warden", "allot")
        if a.status not in ACTIVE_ALLOCATION:
            raise rule(f"The allocation is {a.status}", "NOT_ACTIVE")
        new_bed, new_hostel = await self._bed_for(body.new_bed_id)
        old_bed = (
            await self.db.execute(select(HostelBed).where(HostelBed.id == a.bed_id).with_for_update())
        ).scalar_one()
        old_room = (await self.db.execute(select(HostelRoom).where(HostelRoom.id == old_bed.room_id))).scalar_one()
        new_room = (await self.db.execute(select(HostelRoom).where(HostelRoom.id == new_bed.room_id))).scalar_one()
        a.status, a.to_on = "transferred", await self.today()
        old_bed.status = "vacant"
        await self.db.flush()
        new = HostelAllocation(
            institution_id=self.inst,
            student_program_enrollment_id=a.student_program_enrollment_id,
            bed_id=new_bed.id,
            hostel_id=new_hostel,
            academic_year_id=a.academic_year_id,
            from_on=await self.today(),
            status="checked_in",
            check_in_at=now_utc(),
            caution_deposit_invoice_id=a.caution_deposit_invoice_id,
            fee_invoice_id=a.fee_invoice_id,
            room_condition={"transferred_from": str(a.id), "reason": body.reason},
        )
        self.db.add(new)
        new_bed.status = "allocated"
        await self.db.flush()
        diff_note = None
        if new_room.room_type != old_room.room_type:
            plans = {
                p.room_type: p.fee_per_term_paise
                for p in (
                    await self.db.execute(
                        select(HostelFeePlan).where(
                            HostelFeePlan.hostel_id.in_((a.hostel_id, new_hostel)),
                            HostelFeePlan.academic_year_id == a.academic_year_id,
                        )
                    )
                )
                .scalars()
                .all()
            }
            diff = plans.get(new_room.room_type, 0) - plans.get(old_room.room_type, 0)
            if diff > 0:
                await self.invoice(
                    a.student_program_enrollment_id,
                    "hostel_allocation",
                    new.id,
                    [(f"Room change {old_room.room_type} → {new_room.room_type}", diff, "HOSTEL")],
                    "Hostel fee difference",
                )
            elif diff < 0:
                diff_note = f"credit due {-diff} paise"
        await self._room_full(old_room.id)
        await self._room_full(new_room.id)
        await self.db.flush()
        await self._audit(
            "transfer",
            "hostel_allocation",
            a.id,
            None,
            {"new_allocation": str(new.id), "reason": body.reason, "fee_note": diff_note},
        )
        await self._emit(
            "hostel.transferred",
            {"allocation_id": str(a.id), "new_allocation_id": str(new.id)},
            "hostel_allocation",
            new.id,
        )
        await self.promote_waitlist(a.hostel_id)
        return (await self.outs([new]))[0]

    async def vacate(self, alloc_id: uuid.UUID, body: VacateRequest) -> VacateResponse:
        a = await self._alloc(alloc_id, for_update=True)
        await self.require_hostel(a.hostel_id, "warden", "allot")
        if a.status not in ACTIVE_ALLOCATION:
            raise rule(f"The allocation is {a.status}", "NOT_ACTIVE")
        damages_inv = None
        total = sum(d.amount_paise for d in body.damages)
        if total:
            damages_inv = await self.invoice(
                a.student_program_enrollment_id,
                "hostel_allocation",
                a.id,
                [(f"Damages — {d.item}", d.amount_paise, "HOSTEL") for d in body.damages],
                "Hostel damages",
            )
        bed = (await self.db.execute(select(HostelBed).where(HostelBed.id == a.bed_id).with_for_update())).scalar_one()
        bed.status = "vacant"
        a.status, a.check_out_at, a.to_on = "vacated", now_utc(), body.vacate_on or await self.today()
        a.room_condition = {
            **(a.room_condition or {}),
            "check_out": body.room_condition,
            "damages": [d.model_dump() for d in body.damages],
        }
        await self.db.flush()
        await self._room_full(bed.room_id)
        nd_id = await self._open_no_dues(a.student_program_enrollment_id)
        await self.db.flush()
        await self.db.refresh(a)
        await self._audit(
            "vacate",
            "hostel_allocation",
            a.id,
            None,
            {"damages_paise": total, "no_dues": str(nd_id) if nd_id else None},
        )
        await self._emit("hostel.vacated", {"allocation_id": str(a.id)}, "hostel_allocation", a.id)
        await self.promote_waitlist(a.hostel_id)
        if nd_id:
            await self.sign_no_dues(nd_id)
        return VacateResponse(
            allocation=(await self.outs([a]))[0], no_dues_request_id=nd_id, damages_invoice_id=damages_inv
        )

    async def _open_no_dues(self, enrol_id: uuid.UUID) -> uuid.UUID | None:
        from app.schemas.no_dues import NoDuesCreate
        from app.services.fees.no_dues_service import NoDuesService

        existing = (
            await self.db.execute(
                select(NoDuesRequest.id).where(
                    NoDuesRequest.student_program_enrollment_id == enrol_id,
                    NoDuesRequest.purpose == "hostel_vacate",
                    NoDuesRequest.status != "cleared",
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        try:
            out = await NoDuesService(self.db, None, self.request, self.inst).create(
                NoDuesCreate(purpose="hostel_vacate", enrollment_id=enrol_id), system=True
            )
            return out.id
        except APIError:
            return None

    async def vacate_request(self) -> HostelAllocationResponse:
        rows = await self.me()
        active = next((r for r in rows if r.status in ACTIVE_ALLOCATION), None)
        if active is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "No active hostel allocation")
        h = (await self.db.execute(select(Hostel).where(Hostel.id == active.hostel_id))).scalar_one()
        await self._notify(
            "hostel.vacate_requested",
            [await self.warden_user(h)],
            {"student": active.student.name or "", "room": active.room_number or ""},
        )
        await self._audit("vacate_request", "hostel_allocation", active.id, None, None)
        return active

    async def evict(self, alloc_id: uuid.UUID, body: EvictRequest) -> HostelAllocationResponse:
        """Warden proposes → workflow ``hostel.eviction`` (warden → registrar); ``apply_eviction`` runs on approval."""
        a = await self._alloc(alloc_id, for_update=True)
        await self.require_hostel(a.hostel_id, "warden", "allot")
        if a.status not in ACTIVE_ALLOCATION:
            raise rule(f"The allocation is {a.status}", "NOT_ACTIVE")
        h = (await self.db.execute(select(Hostel).where(Hostel.id == a.hostel_id))).scalar_one()
        if self.can("hostel", "manage") and not await self._is_warden_only():
            await self.apply_eviction(a, body.reason, body.disciplinary_record_id)
        else:
            await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="hostel.eviction",
                entity_type="hostel_allocation",
                entity_id=a.id,
                started_by=self.actor_id,
                context={
                    "warden_user_id": str(await self.warden_user(h) or self.actor_id),
                    "reason": body.reason,
                    "disciplinary_record_id": str(body.disciplinary_record_id) if body.disciplinary_record_id else None,
                    "college_id": str(h.college_id),
                },
                title=f"Eviction · {h.name}",
            )
            await self._audit("eviction_proposed", "hostel_allocation", a.id, None, {"reason": body.reason})
        await self.db.flush()
        return (await self.outs([a]))[0]

    async def _is_warden_only(self) -> bool:
        p = self.principal
        return p is not None and not any(t in ("institution", "college") for t, _ in getattr(p, "scopes", []))

    async def apply_eviction(self, a: HostelAllocation, reason: str, record_id: uuid.UUID | None = None) -> None:
        if a.status not in ACTIVE_ALLOCATION:
            return
        bed = (await self.db.execute(select(HostelBed).where(HostelBed.id == a.bed_id).with_for_update())).scalar_one()
        bed.status = "vacant"
        a.status, a.to_on, a.check_out_at = "evicted", await self.today(), now_utc()
        if record_id is None:
            self.db.add(
                HostelDisciplinaryRecord(
                    institution_id=self.inst,
                    student_program_enrollment_id=a.student_program_enrollment_id,
                    hostel_id=a.hostel_id,
                    incident_on=await self.today(),
                    description=reason,
                    action="eviction",
                    decided_by=self.actor_id,
                )
            )
        hold_days = int(await self.setting("hostel", "eviction_hold_days") or 365)
        self.db.add(
            StudentHold(
                institution_id=self.inst,
                student_program_enrollment_id=a.student_program_enrollment_id,
                hold_type="hostel",
                reason=f"Hostel eviction: {reason}"[:500],
                placed_by=self.actor_id or a.student_program_enrollment_id,
                source_type="hostel_allocation",
                source_id=a.id,
            )
        )
        await self.db.flush()
        await self._room_full(bed.room_id)
        await self._audit("evict", "hostel_allocation", a.id, None, {"reason": reason, "hold_days": hold_days})
        await self._emit("hostel.evicted", {"allocation_id": str(a.id)}, "hostel_allocation", a.id)
        await self._notify(
            "hostel.discipline_recorded",
            await self.guardian_users(a.student_program_enrollment_id)
            + [await self.student_user(a.student_program_enrollment_id)],
            {"action": "eviction", "reason": reason[:120]},
        )
        await self.promote_waitlist(a.hostel_id)

    # ---- room change --------------------------------------------------------------------------------------------------
    async def rc_outs(self, rows: list[RoomChangeRequest]) -> list[RoomChangeResponse]:
        allocs: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(HostelAllocation.id, HostelAllocation.student_program_enrollment_id).where(
                        HostelAllocation.id.in_({r.allocation_id for r in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )  # type: ignore[arg-type]
        refs = await self.refs(list(allocs.values()))
        return [
            RoomChangeResponse(
                id=r.id,
                allocation_id=r.allocation_id,
                student=refs.get(allocs[r.allocation_id]) if r.allocation_id in allocs else None,
                requested_bed_id=r.requested_bed_id,
                reason=r.reason,
                status=r.status,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def request_room_change(self, body: RoomChangeCreate) -> RoomChangeResponse:
        rows = await self.me()
        active = next((r for r in rows if r.status == "checked_in"), None)
        if active is None:
            raise rule("Only checked-in residents can request a room change", "NOT_RESIDENT")
        open_rc = (
            await self.db.execute(
                select(RoomChangeRequest.id).where(
                    RoomChangeRequest.allocation_id == active.id, RoomChangeRequest.status == "requested"
                )
            )
        ).first()
        if open_rc:
            raise rule("A room change request is already open", "ALREADY_REQUESTED")
        rc = RoomChangeRequest(
            institution_id=self.inst,
            allocation_id=active.id,
            requested_bed_id=body.requested_bed_id,
            reason=body.reason,
            status="requested",
        )
        self.db.add(rc)
        await self.db.flush()
        await self.db.refresh(rc)
        h = (await self.db.execute(select(Hostel).where(Hostel.id == active.hostel_id))).scalar_one()
        try:
            async with self.db.begin_nested():
                await workflow_engine.start(
                    self.db,
                    institution_id=self.inst,
                    key="hostel.room_change",
                    entity_type="room_change_request",
                    entity_id=rc.id,
                    started_by=self.actor_id,
                    context={
                        "warden_user_id": str(await self.warden_user(h)) if h.warden_staff_id else None,
                        "college_id": str(h.college_id),
                    },
                    title=f"Room change · {h.name}",
                )
        except APIError:
            pass
        await self._emit("hostel.room_change_requested", {"request_id": str(rc.id)}, "room_change_request", rc.id)
        return (await self.rc_outs([rc]))[0]

    async def room_changes(self, status: str | None) -> list[RoomChangeResponse]:
        q = (
            select(RoomChangeRequest)
            .join(HostelAllocation, HostelAllocation.id == RoomChangeRequest.allocation_id)
            .where(
                RoomChangeRequest.institution_id == self.inst,
                resident_predicate(
                    self.principal, HostelAllocation.student_program_enrollment_id, HostelAllocation.hostel_id
                ),
            )
        )
        if status:
            q = q.where(RoomChangeRequest.status == status)
        rows = list(
            (await self.db.execute(q.order_by(RoomChangeRequest.created_at.desc()).limit(2000))).scalars().all()
        )
        return await self.rc_outs(rows)

    async def decide_room_change(
        self, rc_id: uuid.UUID, body: RoomChangeDecision, *, from_workflow: bool = False
    ) -> RoomChangeResponse:
        rc = (
            await self.db.execute(
                select(RoomChangeRequest)
                .where(RoomChangeRequest.id == rc_id, RoomChangeRequest.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if rc is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Room change request not found")
        a = (
            await self.db.execute(select(HostelAllocation).where(HostelAllocation.id == rc.allocation_id))
        ).scalar_one()
        if not from_workflow:
            await self.require_hostel(a.hostel_id, "warden")
        if rc.status != "requested":
            raise rule(f"The request is {rc.status}", "ALREADY_DECIDED")
        rc.decided_by = self.actor_id
        if not body.approve:
            rc.status = "rejected"
        else:
            bed_id = body.bed_id or rc.requested_bed_id
            if bed_id is None:
                raise APIError(
                    422, ErrorCode.VALIDATION, "Pick a bed to move the resident to", {"code": "BED_REQUIRED"}
                )
            rc.status = "approved"
            await self.db.flush()
            await self.transfer(
                a.id,
                HostelTransferRequest(new_bed_id=bed_id, reason=f"Room change: {rc.reason or ''}"[:500]),
                by_system=True,
            )
            rc.status = "applied"
        await self.db.flush()
        await self.db.refresh(rc)
        await self._advance_workflow(
            "room_change_request", rc.id, "approve" if body.approve else "reject", body.remarks
        )
        await self._emit(
            "hostel.room_change_decided", {"request_id": str(rc.id), "status": rc.status}, "room_change_request", rc.id
        )
        return (await self.rc_outs([rc]))[0]

    async def _advance_workflow(
        self, entity_type: str, entity_id: uuid.UUID, decision: str, comment: str | None
    ) -> None:
        if self.principal is None:
            return
        inst = (
            await self.db.execute(
                select(WorkflowInstance.id).where(
                    WorkflowInstance.entity_type == entity_type,
                    WorkflowInstance.entity_id == entity_id,
                    WorkflowInstance.status.in_(("pending", "escalated")),
                )
            )
        ).scalar_one_or_none()
        if inst is None:
            return
        try:
            async with self.db.begin_nested():
                await workflow_engine.act(
                    self.db, instance_id=inst, actor=self.principal, decision=decision, comment=comment
                )
        except APIError:
            pass

    # ---- payments / no-dues -------------------------------------------------------------------------------------------
    async def hostel_dues(self, enrol_id: uuid.UUID) -> tuple[bool, int]:
        active = (
            await self.db.execute(
                select(HostelAllocation.id).where(
                    HostelAllocation.student_program_enrollment_id == enrol_id,
                    HostelAllocation.status.in_(ACTIVE_ALLOCATION),
                )
            )
        ).first() is not None
        unpaid = (
            await self.db.execute(
                select(func.coalesce(func.sum(FeeInvoice.balance_paise), 0)).where(
                    FeeInvoice.student_program_enrollment_id == enrol_id,
                    FeeInvoice.status.in_(OPEN),
                    FeeInvoice.source_type.in_(
                        ("hostel_allocation", "mess_subscription", "hostel_disciplinary", "hostel_fine")
                    ),
                )
            )
        ).scalar_one()
        return active, int(unpaid)

    async def sign_no_dues(self, request_id: uuid.UUID) -> str | None:
        from app.services.fees.no_dues_service import NoDuesService

        r = (
            await self.db.execute(select(NoDuesRequest).where(NoDuesRequest.id == request_id).with_for_update())
        ).scalar_one_or_none()
        if r is None or r.status == "cleared":
            return None
        signs = list(
            (await self.db.execute(select(NoDuesSignoff).where(NoDuesSignoff.request_id == r.id).with_for_update()))
            .scalars()
            .all()
        )
        s = next((x for x in signs if x.department_key == "hostel"), None)
        if s is None:
            return None
        active, unpaid = await self.hostel_dues(r.student_program_enrollment_id)
        status = "cleared" if not active and not unpaid else "dues_pending"
        if s.status != status or s.dues_paise != (unpaid if status == "dues_pending" else 0):
            s.status, s.dues_paise, s.signed_at = status, unpaid if status == "dues_pending" else 0, now_utc()
            s.remarks = (
                "Auto: no hostel dues"
                if status == "cleared"
                else f"Auto: {'active allocation, ' if active else ''}{unpaid} paise unpaid"
            )
            await self.db.flush()
            st = (
                await self.db.execute(
                    select(Student)
                    .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                    .where(StudentProgramEnrollment.id == r.student_program_enrollment_id)
                )
            ).scalar_one()
            await NoDuesService(self.db, None, self.request, self.inst)._settle(r, signs, st)
        if r.status == "cleared" and r.purpose == "hostel_vacate":
            await self.refund_deposit(r.student_program_enrollment_id)
        return status

    async def refund_deposit(self, enrol_id: uuid.UUID) -> uuid.UUID | None:
        alloc = (
            await self.db.execute(
                select(HostelAllocation)
                .where(
                    HostelAllocation.student_program_enrollment_id == enrol_id,
                    HostelAllocation.caution_deposit_invoice_id.is_not(None),
                )
                .order_by(HostelAllocation.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if alloc is None:
            return None
        inv = (
            await self.db.execute(select(FeeInvoice).where(FeeInvoice.id == alloc.caution_deposit_invoice_id))
        ).scalar_one_or_none()
        if inv is None or not inv.paid_paise:
            return None
        dup = (await self.db.execute(select(FeeRefund.id).where(FeeRefund.invoice_id == inv.id))).first()
        if dup:
            return uuid.UUID(str(dup[0]))
        _active, unpaid = await self.hostel_dues(enrol_id)
        amount = max(int(inv.paid_paise) - unpaid, 0)
        if amount <= 0:
            return None
        st_id = (
            await self.db.execute(
                select(StudentProgramEnrollment.student_id).where(StudentProgramEnrollment.id == enrol_id)
            )
        ).scalar_one()
        ref = FeeRefund(
            institution_id=self.inst,
            invoice_id=inv.id,
            payer_type="student",
            payer_id=st_id,
            amount_paise=amount,
            reason="Hostel caution deposit refund (net of dues)",
            status="requested",
        )
        self.db.add(ref)
        await self.db.flush()
        await self._emit(
            "fees.refund_requested", {"refund_id": str(ref.id), "source": "caution_deposit"}, "fee_refund", ref.id
        )
        return ref.id

    async def reevaluate(self, enrol_id: uuid.UUID) -> None:
        for rid in (
            (
                await self.db.execute(
                    select(NoDuesRequest.id).where(
                        NoDuesRequest.student_program_enrollment_id == enrol_id,
                        NoDuesRequest.status.in_(("requested", "in_progress", "blocked")),
                    )
                )
            )
            .scalars()
            .all()
        ):
            await self.sign_no_dues(rid)

    async def bills_unpaid(self, enrol_id: uuid.UUID) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(MessBill)
                    .join(MessSubscription, MessSubscription.id == MessBill.mess_subscription_id)
                    .join(FeeInvoice, FeeInvoice.id == MessBill.fee_invoice_id)
                    .where(MessSubscription.student_program_enrollment_id == enrol_id, FeeInvoice.status.in_(OPEN))
                )
            ).scalar_one()
        )

    async def visible_allocation_ids(self) -> Any:
        return select(HostelAllocation.id).where(HostelAllocation.hostel_id.in_(visible_hostel_ids(self.principal)))


# ---- workflow hooks --------------------------------------------------------------------------------------------------------
@workflow_engine.on("hostel.room_change", "approved")
async def _room_change_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    rc = (
        await db.execute(select(RoomChangeRequest).where(RoomChangeRequest.id == instance.entity_id))
    ).scalar_one_or_none()
    if rc is None or rc.status != "requested" or rc.requested_bed_id is None:
        return
    await AllocationService(db, actor, institution_id=instance.institution_id).decide_room_change(
        rc.id, RoomChangeDecision(approve=True), from_workflow=True
    )


@workflow_engine.on("hostel.room_change", "rejected")
async def _room_change_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    rc = (
        await db.execute(select(RoomChangeRequest).where(RoomChangeRequest.id == instance.entity_id))
    ).scalar_one_or_none()
    if rc is not None and rc.status == "requested":
        rc.status = "rejected"


@workflow_engine.on("hostel.eviction", "approved")
async def _eviction_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    a = (
        await db.execute(select(HostelAllocation).where(HostelAllocation.id == instance.entity_id).with_for_update())
    ).scalar_one_or_none()
    if a is None:
        return
    ctx = instance.context or {}
    rid = ctx.get("disciplinary_record_id")
    await AllocationService(db, actor, institution_id=instance.institution_id).apply_eviction(
        a, str(ctx.get("reason") or "Eviction"), uuid.UUID(rid) if rid else None
    )
