"""Holidays — Prompts/03 §03.6 ``holiday_service`` (feature ``institution.holidays``).

Business rules
1. CRUD: institution-wide holidays (``college_id`` NULL) need an institution-scoped admin, college holidays the college
   in the caller's write scope; ``(college, date, name)`` unique → 409; ``end_date ≥ holiday_date``.
2. ``bulk_import``: CSV ``name,date,end_date,type,applies_to`` (header optional, dates ISO ``YYYY-MM-DD`` or
   ``DD/MM/YYYY``) — every row is validated independently and inserted in its own savepoint, so one bad row never
   blocks the others: ``{succeeded, created, failed:[{index, code, message}]}`` (``index`` = 0-based data row).
3. ``export_ics``: RFC 5545 calendar (``VEVENT`` per holiday, all-day, ``DTEND`` exclusive) of the requested range.
4. ``is_holiday(date, college_id, applies_to)`` — the helper timetable/attendance (Phases 10/11) call.
5. Every change is audited and emits ``holiday.changed``.
"""

import csv
import io
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.models.platform import Holiday
from app.repositories.holiday_repository import HolidayRepository
from app.repositories.institution_repository import InstitutionRepository
from app.schemas.common import BulkFailure
from app.schemas.institution import (
    HolidayBulkImport,
    HolidayBulkResult,
    HolidayCreate,
    HolidayResponse,
    HolidayUpdate,
)
from app.services.institution.context import check_college_writable, structure_visibility, tenant_id
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

CSV_FIELDS = ("name", "date", "end_date", "type", "applies_to")


def _parse_date(raw: str | None) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"invalid date {raw!r} (use YYYY-MM-DD)")


def _snap(h: Holiday) -> dict[str, Any]:
    return {
        "name": h.name,
        "holiday_date": str(h.holiday_date),
        "end_date": str(h.end_date) if h.end_date else None,
        "holiday_type": h.holiday_type,
        "applies_to": h.applies_to,
        "college_id": str(h.college_id) if h.college_id else None,
    }


class HolidayService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = tenant_id(principal, request)
        self.repo = HolidayRepository(db, principal, self.inst)

    async def list_page(
        self,
        params: PageParams,
        college_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        holiday_type: str | None,
        applies_to: str | None,
    ) -> tuple[list[HolidayResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.repo.filtered(
            college_id=college_id,
            date_from=date_from,
            date_to=date_to,
            holiday_type=holiday_type,
            applies_to=applies_to,
        )
        if not params.sort:
            params = params.model_copy(update={"sort": "holiday_date"})
        rows, pagination = await self.repo.paginate(stmt, params)
        return [HolidayResponse.model_validate(h) for h in rows], pagination, structure_visibility(self.principal)

    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    async def create(self, body: HolidayCreate, *, audit: bool = True) -> Holiday:
        check_college_writable(self.principal, body.college_id)
        if await self.repo.duplicate(self.inst, body.college_id, body.holiday_date, body.name):
            raise APIError(
                409, ErrorCode.CONFLICT, f"{body.name} on {body.holiday_date} already exists", {"field": "holiday_date"}
            )
        h = await self.repo.create(
            institution_id=self.inst,
            college_id=body.college_id,
            name=body.name,
            holiday_date=body.holiday_date,
            end_date=body.end_date,
            holiday_type=body.holiday_type.value,
            applies_to=body.applies_to.value,
            created_by=self.principal.id,
        )
        if audit:
            await self._audit("create", h, None, _snap(h))
            await self._emit([h], "created")
        return h

    async def update(self, holiday_id: uuid.UUID, body: HolidayUpdate) -> HolidayResponse:
        h = await self.repo.get_one(holiday_id)
        check_college_writable(self.principal, h.college_id)
        values = {k: (v.value if hasattr(v, "value") else v) for k, v in body.model_dump(exclude_unset=True).items()}
        start = values.get("holiday_date", h.holiday_date)
        end = values.get("end_date", h.end_date)
        if end is not None and end < start:
            raise APIError(
                422, ErrorCode.VALIDATION, "end_date must be on or after holiday_date", {"field": "end_date"}
            )
        old = _snap(h)
        await self.repo.update(h, **values)
        await self._audit("update", h, old, _snap(h))
        await self._emit([h], "updated")
        return HolidayResponse.model_validate(h)

    async def delete(self, holiday_id: uuid.UUID) -> None:
        h = await self.repo.get_one(holiday_id)
        check_college_writable(self.principal, h.college_id)
        old = _snap(h)
        await self.repo.soft_delete(h, self.principal.id)
        await self._audit("delete", h, old, None)
        await self._emit([h], "deleted")

    # ---- rule 2 ---------------------------------------------------------------------------------------------------
    async def bulk_import(self, body: HolidayBulkImport) -> HolidayBulkResult:
        check_college_writable(self.principal, body.college_id)
        rows = body.rows if body.rows is not None else self._csv_rows(body.csv or "")
        created: list[Holiday] = []
        failed: list[BulkFailure] = []
        for idx, raw in enumerate(rows):
            try:
                item = HolidayCreate(
                    name=str(raw.get("name") or "").strip(),
                    holiday_date=_parse_date(raw.get("date") or raw.get("holiday_date")),  # type: ignore[arg-type]
                    end_date=_parse_date(raw.get("end_date")),
                    holiday_type=(raw.get("type") or raw.get("holiday_type") or "public").strip(),
                    applies_to=(raw.get("applies_to") or "all").strip(),
                    college_id=body.college_id,
                )
            except (ValueError, ValidationError, TypeError) as exc:
                failed.append(BulkFailure(index=idx, code=ErrorCode.VALIDATION, message=_first_error(exc)))
                continue
            try:
                async with self.db.begin_nested():
                    created.append(await self.create(item, audit=False))
            except APIError as exc:
                failed.append(BulkFailure(index=idx, code=exc.code, message=exc.message))
        if created:
            await log_audit(
                self.db,
                principal=self.principal,
                module="institutions",
                action="bulk_import",
                record_type="holiday",
                record_id=None,
                new={"created": len(created), "failed": len(failed), "ids": [str(h.id) for h in created]},
                request=self.request,
            )
            await self._emit(created, "imported")
        return HolidayBulkResult(
            succeeded=len(created), created=[HolidayResponse.model_validate(h) for h in created], failed=failed
        )

    @staticmethod
    def _csv_rows(text: str) -> list[dict[str, Any]]:
        lines = [ln for ln in text.strip().splitlines() if ln.strip()]
        if not lines:
            raise APIError(422, ErrorCode.VALIDATION, "Empty CSV", {"field": "csv"})
        first = [c.strip().lower() for c in next(csv.reader([lines[0]]))]
        has_header = first[:2] == ["name", "date"] or "name" in first and "date" in first
        reader = csv.reader(io.StringIO("\n".join(lines[1:] if has_header else lines)))
        header = first if has_header else list(CSV_FIELDS)
        return [dict(zip(header, [c.strip() for c in row], strict=False)) for row in reader]

    # ---- rule 3 ---------------------------------------------------------------------------------------------------
    async def export_ics(self, college_id: uuid.UUID | None, date_from: date | None, date_to: date | None) -> bytes:
        from icalendar import Calendar, Event

        institution = await InstitutionRepository(self.db).get(self.inst)
        rows = (
            (
                await self.db.execute(
                    self.repo.filtered(college_id=college_id, date_from=date_from, date_to=date_to).order_by(
                        Holiday.holiday_date
                    )
                )
            )
            .scalars()
            .all()
        )
        cal = Calendar()
        cal.add("prodid", "-//SeptronUniverse//Holidays//EN")
        cal.add("version", "2.0")
        cal.add("x-wr-calname", f"{institution.name if institution else 'Institution'} holidays")
        if institution is not None:
            cal.add("x-wr-timezone", institution.timezone)
        for h in rows:
            ev = Event()
            ev.add("uid", f"{h.id}@septronuniverse")
            ev.add("summary", h.name)
            ev.add("dtstart", h.holiday_date)
            ev.add("dtend", (h.end_date or h.holiday_date) + timedelta(days=1))
            ev.add("categories", [h.holiday_type])
            ev.add("description", f"{h.holiday_type} holiday · applies to {h.applies_to}")
            ev.add("dtstamp", h.created_at)
            cal.add_component(ev)
        return bytes(cal.to_ical())

    # ---- rule 4 ---------------------------------------------------------------------------------------------------
    async def is_holiday(self, day: date, college_id: uuid.UUID | None = None, applies_to: str | None = None) -> bool:
        return bool(await self.repo.covering(self.inst, day, college_id, applies_to))

    # ---- rule 5 ---------------------------------------------------------------------------------------------------
    async def _audit(self, action: str, h: Holiday, old: dict[str, Any] | None, new: dict[str, Any] | None) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module="institutions",
            action=action,
            record_type="holiday",
            record_id=h.id,
            old=old,
            new=new,
            request=self.request,
        )

    async def _emit(self, rows: list[Holiday], change: str) -> None:
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="holiday.changed",
            payload={
                "change": change,
                "holiday_ids": [str(h.id) for h in rows],
                "dates": sorted({str(h.holiday_date) for h in rows}),
            },
            aggregate_type="holiday",
            aggregate_id=rows[0].id if len(rows) == 1 else None,
            actor_user_id=self.principal.id,
        )


def _first_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        err = exc.errors()[0]
        loc = ".".join(str(p) for p in err.get("loc", ()))
        return f"{loc}: {err.get('msg')}" if loc else str(err.get("msg"))
    return str(exc)
