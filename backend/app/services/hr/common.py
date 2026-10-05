"""Shared plumbing of the Phase 06 services: tenant, audit, outbox events, notifications, the caller's staff row,
the institution's local date, the pack and settings, and the day calendar (holidays + week-offs)."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.core.notifications.notify import notify_event
from app.core.packs import get_pack
from app.core.packs.base import RegulatoryPack
from app.core.tenancy import today_for
from app.models.hr import Staff
from app.models.platform import Institution
from app.repositories.holiday_repository import HolidayRepository
from app.repositories.staff_repository import StaffRepository
from app.services.institution.context import tenant_id


def snap(obj: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys:
        v = getattr(obj, k, None)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, Decimal):
            v = float(v)
        elif isinstance(v, date | datetime):
            v = v.isoformat()
        out[k] = v
    return out


def rupees(paise: int | None) -> str:
    """₹1,23,456.78 (Indian grouping) for notifications and payslips."""
    if paise is None:
        return "—"
    neg = paise < 0
    whole, frac = divmod(abs(int(paise)), 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"{'-' if neg else ''}₹{s}.{frac:02d}"


class SystemActor:
    """Audit actor for institution-level work without a signed-in user (Beat jobs, public careers, device punches)."""

    def __init__(self, institution_id: uuid.UUID):
        self.institution_id = institution_id
        self.id = None
        self.impersonator_id = None


class HrServiceBase:
    audit_module = "hr"

    def __init__(
        self, db: AsyncSession, principal: Any, request: Request | None = None, institution_id: uuid.UUID | None = None
    ):
        # ``institution_id`` without a principal: Beat jobs / outbox consumers acting for the institution itself
        self.db, self.principal, self.request = db, principal, request
        self.inst = institution_id or tenant_id(principal, request)
        self.staff_repo = StaffRepository(db, principal, self.inst)
        self._institution: Institution | None = None
        self._pack: RegulatoryPack | None = None

    # ---- context ----------------------------------------------------------------------------------------------------
    async def institution(self) -> Institution:
        if self._institution is None:
            self._institution = (
                await self.db.execute(select(Institution).where(Institution.id == self.inst))
            ).scalar_one()
        return self._institution

    async def pack(self) -> RegulatoryPack:
        if self._pack is None:
            self._pack = get_pack((await self.institution()).regulatory_pack)
        return self._pack

    async def today(self) -> date:
        return today_for(await self.institution())

    async def setting(self, category: str, key: str, college_id: uuid.UUID | None = None) -> Any:
        from app.services.settings_service import SettingsService

        return await SettingsService(self.db).value(self.inst, category, key, college_id)

    async def my_staff(self, required: bool = True) -> Staff | None:
        row = await self.staff_repo.by_user(self.principal.id)
        if row is None and required:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Your account is not linked to a staff record",
                {"reason": "no_staff_record"},
            )
        return row

    # ---- calendar -----------------------------------------------------------------------------------------------
    async def week_offs(self) -> set[int]:
        raw = await self.setting("hr", "week_offs")
        if isinstance(raw, list) and all(isinstance(x, int) for x in raw):
            return set(raw)
        return set((await self.pack()).hr.week_offs)

    async def off_days(self, date_from: date, date_to: date, college_id: uuid.UUID | None) -> dict[date, str]:
        """date → 'holiday' | 'week_off' for the staff calendar of a college (institution-wide rows included)."""
        offs = await self.week_offs()
        out: dict[date, str] = {}
        day = date_from
        while day <= date_to:
            if day.weekday() in offs:
                out[day] = "week_off"
            day += timedelta(days=1)
        holidays = HolidayRepository(self.db, self.principal, self.inst)
        day = date_from
        while day <= date_to:
            if day not in out and await holidays.covering(self.inst, day, college_id, "staff"):
                out[day] = "holiday"
            day += timedelta(days=1)
        return out

    # ---- side effects -----------------------------------------------------------------------------------------------
    async def _audit(
        self,
        action: str,
        record_type: str,
        record_id: uuid.UUID | None,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
        module: str | None = None,
    ) -> None:
        await log_audit(
            self.db,
            principal=self.principal or SystemActor(self.inst),
            module=module or self.audit_module,
            action=action,
            record_type=record_type,
            record_id=record_id,
            old=old,
            new=new,
            request=self.request,
        )

    async def _emit(
        self, event_type: str, payload: dict[str, Any], aggregate_type: str, aggregate_id: uuid.UUID | None
    ) -> None:
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type=event_type,
            payload=payload,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor_user_id=getattr(self.principal, "id", None),
        )

    async def _notify(
        self, event_type: str, user_ids: list[uuid.UUID | None], context: dict[str, Any], **kw: Any
    ) -> None:
        ids = [str(u) for u in user_ids if u]
        if not ids and not kw.get("audience"):
            return
        audience = kw.pop("audience", None) or {"user_ids": ids}
        await notify_event(
            self.db,
            self.inst,
            event_type,
            audience=audience,
            context=context,
            actor_user_id=getattr(self.principal, "id", None),
            **kw,
        )
