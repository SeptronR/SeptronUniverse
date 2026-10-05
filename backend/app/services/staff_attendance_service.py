"""Staff attendance — Prompts/06 §06.6 ``staff_attendance_service.py``.

Rules
1. **Mark** (HR / admin): upsert the (staff, date) row with status / times / remarks (``source = manual``).
2. **Self check-in / check-out** ({attendance.staff}; ``attendance.staff_self_checkin`` setting): with
   ``attendance.geo_app`` on, a ``geo`` point is required and must lie within the geo-fence (``attendance.geo_fence``
   ``{lat, lng, radius_m}``, college row first; haversine distance) → 422 outside; the row is ``present`` with
   ``source = geo`` (``self_checkin`` without geo). A second check-in the same day → 409; check-out needs a check-in.
3. **Device punches** ({attendance.biometric}): the device authenticates with its token (only the SHA-256 is
   stored); punches are grouped per employee code and local date — first ``in`` (or first punch) → check-in, last
   ``out`` (or last punch) → check-out; unknown codes are reported, not failed; ``last_seen_at`` is updated.
4. **Regularisation**: a member asks to correct a past day → workflow ``attendance.regularise`` (HOD) → on approval
   the row is upserted with the requested status/times.
5. **Monthly summary** per staff (present / absent / half day / on leave / on duty / holiday / week-off / LOP /
   unmarked) — payroll reads LOP from it; Beat ``attendance.auto_mark_holidays`` writes ``holiday`` / ``week_off``
   rows for active staff each day.
"""

import calendar
import hashlib
import math
import secrets
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.workflow import engine as workflow_engine
from app.models.hr import Staff, StaffAttendance
from app.models.platform import WorkflowInstance
from app.repositories.hr_scope import hr_visibility, may_view_all
from app.repositories.staff_attendance_repository import AttendanceDeviceRepository, StaffAttendanceRepository
from app.schemas.hr import (
    AttendanceDeviceIn,
    AttendanceDeviceOut,
    AttendanceSummaryRow,
    PunchIngest,
    PunchIngestResult,
    RegulariseRequest,
    SelfCheckinRequest,
    StaffAttendanceMark,
    StaffAttendanceOut,
)
from app.services.hr.common import HrServiceBase
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

REGULARISE_KEY = "attendance.regularise"
EARTH_M = 6_371_000


def haversine_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(h))


def month_range(month: str | None, today: date) -> tuple[date, date]:
    """``YYYY-MM`` → first and last day (default: the current month)."""
    if month:
        try:
            y, m = (int(x) for x in month.split("-", 1))
            first = date(y, m, 1)
        except ValueError as exc:
            raise APIError(422, ErrorCode.VALIDATION, "month must be YYYY-MM", {"field": "month"}) from exc
    else:
        first = today.replace(day=1)
    return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])


class StaffAttendanceService(HrServiceBase):
    audit_module = "attendance"

    def __init__(self, db: Any, principal: Any, request: Any = None, institution_id: uuid.UUID | None = None):
        super().__init__(db, principal, request, institution_id)
        self.repo = StaffAttendanceRepository(db, principal, self.inst)
        self.devices = AttendanceDeviceRepository(db, principal, self.inst)

    async def _tz(self) -> ZoneInfo:
        try:
            return ZoneInfo((await self.institution()).timezone or "Asia/Kolkata")
        except Exception:  # noqa: BLE001
            return ZoneInfo("Asia/Kolkata")

    # ---- lists --------------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None, month: str | None, **filters: Any
    ) -> tuple[list[StaffAttendanceOut], PaginationMeta, VisibilityMeta]:
        first, last = month_range(month, await self.today())
        stmt = self.repo.filtered(scope=scope, date_from=first, date_to=last, **filters)
        if not params.sort:
            params = params.model_copy(update={"sort": "attendance_date"})
        rows, pagination = await self.repo.paginate(stmt, params)
        return await self._out(list(rows)), pagination, hr_visibility(self.principal, "attendance")

    async def _out(self, rows: list[StaffAttendance]) -> list[StaffAttendanceOut]:
        names = await self.staff_repo.names([r.staff_id for r in rows])
        out = []
        for r in rows:
            o = StaffAttendanceOut.model_validate(r)
            o.staff_name, o.employee_id = names.get(r.staff_id, (None, None))
            out.append(o)
        return out

    # ---- rule 1 -------------------------------------------------------------------------------------------------
    async def mark(self, body: StaffAttendanceMark) -> tuple[StaffAttendanceOut, bool]:
        staff = await self.staff_repo.get_visible(body.staff_id, module="attendance")
        if staff.status == "exited":
            raise APIError(422, ErrorCode.VALIDATION, "The member has exited")
        row = await self.repo.day(staff.id, body.date, for_update=True)
        created = row is None
        old = {"status": row.status} if row else None
        if row is None:
            row = await self.repo.add(
                institution_id=self.inst,
                staff_id=staff.id,
                attendance_date=body.date,
                status=body.status.value,
                check_in_time=body.check_in,
                check_out_time=body.check_out,
                source="manual",
                remarks=body.remarks,
                marked_by=self.principal.id,
            )
        else:
            row.status, row.remarks, row.marked_by, row.source = (
                body.status.value,
                body.remarks,
                self.principal.id,
                "manual",
            )
            if body.check_in:
                row.check_in_time = body.check_in
            if body.check_out:
                row.check_out_time = body.check_out
            await self.db.flush()
        await self._audit(
            "mark",
            "staff_attendance",
            row.id,
            old,
            {"staff_id": str(staff.id), "date": body.date.isoformat(), "status": body.status.value},
        )
        await self._emit(
            "staff_attendance.marked",
            {"staff_id": str(staff.id), "date": body.date.isoformat(), "status": body.status.value},
            "staff_attendance",
            row.id,
        )
        return (await self._out([row]))[0], created

    # ---- rule 2 -------------------------------------------------------------------------------------------------
    async def self_checkin(self, body: SelfCheckinRequest) -> StaffAttendanceOut:
        staff = await self.my_staff()
        assert staff is not None
        if not await self.setting("attendance", "staff_self_checkin", staff.college_id):
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "Self check-in is switched off", {"reason": "self_checkin_disabled"}
            )
        geo_on = await is_enabled(self.inst, "attendance.geo_app")
        geo_payload: dict[str, Any] | None = None
        if geo_on:
            if body.geo is None:
                raise APIError(422, ErrorCode.VALIDATION, "Location is required to check in", {"field": "geo"})
            fence = await self.setting("attendance", "geo_fence", staff.college_id)
            if not isinstance(fence, dict) or not {"lat", "lng"} <= set(fence):
                raise APIError(
                    422, ErrorCode.VALIDATION, "No geo-fence is configured for your campus", {"field": "geo"}
                )
            radius = float(fence.get("radius_m") or 200)
            distance = haversine_m(body.geo.lat, body.geo.lng, float(fence["lat"]), float(fence["lng"]))
            if distance > radius:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"You are {distance:.0f} m from the campus (allowed {radius:.0f} m)",
                    {"field": "geo", "distance_m": round(distance), "radius_m": radius},
                )
            geo_payload = {**body.geo.model_dump(), "distance_m": round(distance)}
        elif body.geo is not None:
            geo_payload = body.geo.model_dump()
        today = await self.today()
        now = datetime.now(UTC)
        row = await self.repo.day(staff.id, today, for_update=True)
        if row is not None and (row.check_in_time is not None or row.status == "on_leave"):
            raise APIError(
                409, ErrorCode.CONFLICT, f"Already {'checked in' if row.check_in_time else 'on leave'} today"
            )
        source = "geo" if geo_on else "self_checkin"
        if row is None:
            row = await self.repo.add(
                institution_id=self.inst,
                staff_id=staff.id,
                attendance_date=today,
                status="present",
                check_in_time=now,
                source=source,
                geo=geo_payload,
                marked_by=self.principal.id,
            )
        else:
            row.status, row.check_in_time, row.source, row.geo = "present", now, source, geo_payload
            await self.db.flush()
        await self._audit(
            "self_checkin", "staff_attendance", row.id, None, {"date": today.isoformat(), "source": source}
        )
        await self._emit(
            "staff_attendance.marked",
            {"staff_id": str(staff.id), "date": today.isoformat(), "status": "present", "source": source},
            "staff_attendance",
            row.id,
        )
        return (await self._out([row]))[0]

    async def self_checkout(self, body: SelfCheckinRequest) -> StaffAttendanceOut:
        staff = await self.my_staff()
        assert staff is not None
        row = await self.repo.day(staff.id, await self.today(), for_update=True)
        if row is None or row.check_in_time is None:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Check in first")
        row.check_out_time = datetime.now(UTC)
        if body.geo is not None:
            row.geo = {**(row.geo or {}), "checkout": body.geo.model_dump()}
        await self.db.flush()
        await self._audit("self_checkout", "staff_attendance", row.id, None, {"date": row.attendance_date.isoformat()})
        return (await self._out([row]))[0]

    # ---- rule 3 -------------------------------------------------------------------------------------------------
    async def list_devices(self) -> list[AttendanceDeviceOut]:
        return [AttendanceDeviceOut.model_validate(d) for d in await self.devices.all()]

    async def create_device(self, body: AttendanceDeviceIn) -> AttendanceDeviceOut:
        token = "dev_" + secrets.token_urlsafe(32)
        row = await self.devices.create(
            institution_id=self.inst,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            **{**body.model_dump(), "device_type": body.device_type.value},
        )
        await self._audit(
            "create", "attendance_device", row.id, None, {"name": row.name, "device_type": row.device_type}
        )
        out = AttendanceDeviceOut.model_validate(row)
        out.token = token
        return out

    async def ingest_punches(self, device_id: uuid.UUID, body: PunchIngest) -> PunchIngestResult:
        device = await self.devices.get_one(device_id)
        if not device.is_active or not secrets.compare_digest(
            device.token_hash, hashlib.sha256(body.device_token.encode()).hexdigest()
        ):
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid device token")
        tz = await self._tz()
        codes = sorted({p.employee_code for p in body.punches})
        staff = await self.staff_repo.by_employee_codes(codes)
        unknown = [c for c in codes if c not in staff]
        grouped: dict[tuple[uuid.UUID, date], list[tuple[datetime, str | None]]] = defaultdict(list)
        for p in body.punches:
            s = staff.get(p.employee_code)
            if s is None:
                continue
            at = p.at if p.at.tzinfo else p.at.replace(tzinfo=tz)
            grouped[(s.id, at.astimezone(tz).date())].append((at.astimezone(UTC), p.direction))
        updated = 0
        for (staff_id, day), punches in grouped.items():
            punches.sort(key=lambda x: x[0])
            ins = [t for t, d in punches if d == "in"] or [punches[0][0]]
            outs = [t for t, d in punches if d == "out"] or ([punches[-1][0]] if len(punches) > 1 else [])
            row = await self.repo.day(staff_id, day, for_update=True)
            if row is None:
                row = await self.repo.add(
                    institution_id=self.inst,
                    staff_id=staff_id,
                    attendance_date=day,
                    status="present",
                    check_in_time=ins[0],
                    check_out_time=outs[-1] if outs else None,
                    source="biometric",
                    device_id=device.id,
                )
            else:
                if row.status in ("absent", "holiday", "week_off") or row.status is None:
                    row.status = "present"
                row.check_in_time = min(filter(None, [row.check_in_time, ins[0]]))
                if outs:
                    row.check_out_time = max(filter(None, [row.check_out_time, outs[-1]]))
                row.source, row.device_id = "biometric", device.id
            updated += 1
        device.last_seen_at = datetime.now(UTC)
        await self.db.flush()
        await self._emit(
            "staff_attendance.punches",
            {"device_id": str(device.id), "punches": len(body.punches), "days": updated},
            "attendance_device",
            device.id,
        )
        return PunchIngestResult(received=len(body.punches), days_updated=updated, unknown_codes=unknown)

    # ---- rule 4 -------------------------------------------------------------------------------------------------
    async def regularise(self, body: RegulariseRequest) -> dict[str, Any]:
        staff = await self.my_staff()
        assert staff is not None
        today = await self.today()
        if body.date > today:
            raise APIError(422, ErrorCode.VALIDATION, "Only past days can be regularised", {"field": "date"})
        instance = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=REGULARISE_KEY,
            entity_type="attendance_regularisation",
            entity_id=uuid.uuid4(),
            started_by=self.principal.id,
            context={
                "staff_id": str(staff.id),
                "department_id": str(staff.department_id) if staff.department_id else None,
                "college_id": str(staff.college_id) if staff.college_id else None,
                "date": body.date.isoformat(),
                "status": body.status.value,
                "check_in": body.check_in.isoformat() if body.check_in else None,
                "check_out": body.check_out.isoformat() if body.check_out else None,
                "reason": body.reason,
            },
            title=f"Attendance regularisation {body.date.isoformat()} — {staff.full_name}",
        )
        await self._audit(
            "regularise_request",
            "staff_attendance",
            instance.id,
            None,
            {"date": body.date.isoformat(), "status": body.status.value},
        )
        return {"workflow_instance_id": str(instance.id), "status": instance.status}

    async def apply_regularisation(self, ctx: dict[str, Any], actor_id: uuid.UUID | None) -> None:
        staff_id, day = uuid.UUID(ctx["staff_id"]), date.fromisoformat(ctx["date"])
        row = await self.repo.day(staff_id, day, for_update=True)
        check_in = datetime.fromisoformat(ctx["check_in"]) if ctx.get("check_in") else None
        check_out = datetime.fromisoformat(ctx["check_out"]) if ctx.get("check_out") else None
        if row is None:
            await self.repo.add(
                institution_id=self.inst,
                staff_id=staff_id,
                attendance_date=day,
                status=ctx["status"],
                check_in_time=check_in,
                check_out_time=check_out,
                source="manual",
                remarks=f"regularised: {ctx.get('reason', '')}"[:500],
                marked_by=actor_id,
            )
        else:
            row.status, row.remarks, row.marked_by = (
                ctx["status"],
                f"regularised: {ctx.get('reason', '')}"[:500],
                actor_id,
            )
            row.check_in_time = check_in or row.check_in_time
            row.check_out_time = check_out or row.check_out_time
        await self.db.flush()

    # ---- rule 5 -------------------------------------------------------------------------------------------------
    async def summary(
        self, month: str | None, scope: str | None, staff_id: uuid.UUID | None = None
    ) -> list[AttendanceSummaryRow]:
        first, last = month_range(month, await self.today())
        stmt = self.staff_repo.filtered(scope=scope, module="attendance")
        if staff_id:
            stmt = stmt.where(Staff.id == staff_id)
        staff_rows = list((await self.db.execute(stmt.order_by(Staff.employee_id))).scalars().all())
        return await self.summarise(staff_rows, first, last)

    async def summarise(self, staff_rows: list[Staff], first: date, last: date) -> list[AttendanceSummaryRow]:
        rows = await self.repo.range_for([s.id for s in staff_rows], first, last)
        by_staff: dict[uuid.UUID, dict[date, StaffAttendance]] = defaultdict(dict)
        for r in rows:
            by_staff[r.staff_id][r.attendance_date] = r
        offs_cache: dict[uuid.UUID | None, dict[date, str]] = {}
        out: list[AttendanceSummaryRow] = []
        days_in_month = (last - first).days + 1
        today = await self.today()
        for s in staff_rows:
            if s.college_id not in offs_cache:
                offs_cache[s.college_id] = await self.off_days(first, last, s.college_id)
            offs = offs_cache[s.college_id]
            counts: defaultdict[str, float] = defaultdict(float)
            unmarked = 0
            d = first
            while d <= last:
                row = by_staff[s.id].get(d)
                if row is not None:
                    counts[row.status] += 1
                elif d in offs:
                    counts[offs[d]] += 1
                elif d <= today and (s.joining_date is None or d >= s.joining_date):
                    unmarked += 1
                d += timedelta(days=1)
            lop = counts["absent"] + counts["half_day"] * 0.5
            out.append(
                AttendanceSummaryRow(
                    staff_id=s.id,
                    staff_name=s.full_name,
                    employee_id=s.employee_id,
                    days_in_month=days_in_month,
                    present=counts["present"] + counts["half_day"] * 0.5,
                    absent=counts["absent"],
                    half_day=int(counts["half_day"]),
                    on_leave=counts["on_leave"],
                    on_duty=counts["on_duty"],
                    holiday=int(counts["holiday"]),
                    week_off=int(counts["week_off"]),
                    lop_days=lop,
                    unmarked=unmarked,
                )
            )
        return out

    async def auto_mark_offs(self, day: date) -> int:
        """Beat ``attendance.auto_mark_holidays``: ``holiday`` / ``week_off`` rows for active staff without a row."""
        n = 0
        offs_cache: dict[uuid.UUID | None, str | None] = {}
        for s in await self.staff_repo.active():
            if s.college_id not in offs_cache:
                offs_cache[s.college_id] = (await self.off_days(day, day, s.college_id)).get(day)
            status = offs_cache[s.college_id]
            if status is None or await self.repo.day(s.id, day) is not None:
                continue
            await self.repo.add(
                institution_id=self.inst,
                staff_id=s.id,
                attendance_date=day,
                status=status,
                source="import",
                remarks="auto",
            )
            n += 1
        return n

    def can_view_all(self) -> bool:
        return may_view_all(self.principal, "attendance")


def local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


@workflow_engine.on(REGULARISE_KEY, "approved")
async def _on_regularised(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    ctx = dict(instance.context or {})
    if not ctx.get("staff_id") or not ctx.get("date"):
        return
    await StaffAttendanceService(db, actor, institution_id=instance.institution_id).apply_regularisation(
        ctx, getattr(actor, "id", None)
    )


@workflow_engine.summariser("attendance_regularisation")
async def _summarise_regularisation(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    return "Attendance regularisation", "/admin/hr/attendance?tab=regularisation"
