"""Academic years and terms — Prompts/03 §03.6 ``academic_session_service``.

Business rules
1. Years: ``name`` unique per scope (institution-wide ``college_id`` NULL, or one college) → 409; dates of two years
   of the same scope may not overlap → 422; exactly one ``is_current`` year per (institution, college) — setting a new
   current year clears the previous one in the same transaction (partial unique index ``one_current_year`` is the
   backstop). ``lock`` (``sessions:lock``) freezes the year: its own dates/name and every term of it answer
   ``409 RECORD_LOCKED``; later phases refuse registration/attendance/result edits of a locked year.
2. Terms: the term inherits the year's scope; ``(term_type, sequence)`` unique inside the year → 409; dates within the
   year and ``registration_start ≤ registration_end ≤ add_drop_end ≤ last_instruction_date ≤ end_date`` (each
   optional, ``start_date ≤ end_date`` always) → 422; terms of one year may not overlap → 422.
3. Status machine ``planned → registration → in_progress → exam → result_processing → closed`` — forward only and one
   step at a time (skipping or going back → ``409 RULE_VIOLATION`` naming the allowed next status); ``closed`` also
   needs ``sessions:close`` and every registered ``TermCloseCheck`` (``app/core/academic_hooks.py``) passing (409 with
   the failing checks). Emits ``academic_term.status_changed``.
4. ``rollover``: creates the next year (+ its terms) in the scope, makes it current (and its first term current),
   optionally locks the previous year and — with ``promote_batches`` — runs the registered ``on_rollover`` hooks
   (none before Phases 05/07); emits ``academic_year.rolled_over``.
5. ``set_current_term`` flips the scope's current term (and makes its year current); emits ``academic_term.changed``
   so clients refresh their year/term selectors.
6. College-scoped admins manage only their college's years/terms (403 on create, 404 on others' rows); every change
   is audited.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.academic_hooks import ROLLOVER_HOOKS, TERM_CLOSE_CHECKS
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.enums.institution import TERM_STATUS_ORDER, TermStatus
from app.models.academic import AcademicTerm, AcademicYear
from app.repositories.academic_session_repository import AcademicTermRepository, AcademicYearRepository
from app.repositories.college_repository import CollegeRepository
from app.schemas.academic_sessions import (
    AcademicTermBrief,
    AcademicTermCreate,
    AcademicTermResponse,
    AcademicTermUpdate,
    AcademicYearCreate,
    AcademicYearResponse,
    AcademicYearUpdate,
    RolloverRequest,
    RolloverResponse,
    RolloverTerm,
    TermCloseCheck,
    TermStatusChange,
)
from app.services.institution.context import check_college_writable, tenant_id, writable_college_ids
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

YEAR_KEYS = ("name", "start_date", "end_date", "is_current", "is_locked", "college_id")
TERM_KEYS = (
    "name",
    "term_type",
    "sequence",
    "start_date",
    "end_date",
    "registration_start",
    "registration_end",
    "add_drop_end",
    "last_instruction_date",
    "status",
    "is_current",
)


def _snap(obj: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys:
        v = getattr(obj, k)
        out[k] = str(v) if isinstance(v, uuid.UUID | date) else v
    return out


def next_status(current: str) -> str | None:
    order = [s.value for s in TERM_STATUS_ORDER]
    idx = order.index(current) if current in order else -1
    return order[idx + 1] if 0 <= idx < len(order) - 1 else None


def validate_term_dates(year: AcademicYear, t: Any) -> None:
    """Rule 2 — raises 422 naming the first offending field."""
    if t.start_date > t.end_date:
        raise APIError(422, ErrorCode.VALIDATION, "start_date must be on or before end_date", {"field": "end_date"})
    if t.start_date < year.start_date or t.end_date > year.end_date:
        raise APIError(
            422,
            ErrorCode.VALIDATION,
            f"Term dates must lie within the academic year ({year.start_date} – {year.end_date})",
            {"field": "start_date"},
        )
    chain = [
        ("registration_start", t.registration_start),
        ("registration_end", t.registration_end),
        ("add_drop_end", t.add_drop_end),
        ("last_instruction_date", t.last_instruction_date),
        ("end_date", t.end_date),
    ]
    previous: tuple[str, date] | None = None
    for name, value in chain:
        if value is None:
            continue
        if previous is not None and value < previous[1]:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"{previous[0]} ≤ {name} is required (registration_start ≤ registration_end ≤ add_drop_end ≤ "
                "last_instruction_date ≤ end_date)",
                {"field": name},
            )
        previous = (name, value)


class AcademicSessionService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = tenant_id(principal, request)
        self.years = AcademicYearRepository(db, principal, self.inst)
        self.terms = AcademicTermRepository(db, principal, self.inst)

    # ---- responses ------------------------------------------------------------------------------------------------
    async def _year_responses(self, rows: list[AcademicYear]) -> list[AcademicYearResponse]:
        terms = await self.terms.of_years([y.id for y in rows])
        out = []
        for y in rows:
            r = AcademicYearResponse.model_validate(y)
            r.terms = [AcademicTermBrief.model_validate(t) for t in terms.get(y.id, [])]
            out.append(r)
        return out

    async def _term_response(self, t: AcademicTerm, with_checks: bool = False) -> AcademicTermResponse:
        r = AcademicTermResponse.model_validate(t)
        year = await self.years.get_one(t.academic_year_id)
        r.academic_year_name = year.name
        r.next_status = next_status(t.status)
        if with_checks and r.next_status == TermStatus.CLOSED:
            r.blocking_checks = [c for c in await self.close_checks(t) if not c.passed]
        return r

    def _visibility(self) -> VisibilityMeta:
        from app.services.institution.context import structure_visibility

        return structure_visibility(self.principal)

    # ---- rule 1: years --------------------------------------------------------------------------------------------
    async def list_years(
        self, params: PageParams, college_id: uuid.UUID | None, current_only: bool
    ) -> tuple[list[AcademicYearResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.years.filtered(college_id, current_only=current_only)
        rows, pagination = await self.years.paginate(stmt, params)
        return await self._year_responses(list(rows)), pagination, self._visibility()

    async def get_year(self, year_id: uuid.UUID) -> AcademicYearResponse:
        return (await self._year_responses([await self.years.get_one(year_id)]))[0]

    async def _writable_year(self, year_id: uuid.UUID, *, allow_locked: bool = False) -> AcademicYear:
        y = await self.years.get_one(year_id, for_update=True)
        writable = writable_college_ids(self.principal)
        if writable is not None and (y.college_id is None or y.college_id not in writable):
            raise APIError(404, ErrorCode.NOT_FOUND, "Academic year not found")
        if y.is_locked and not allow_locked:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"Academic year {y.name} is locked", {"year_id": str(y.id)})
        return y

    async def create_year(self, body: AcademicYearCreate) -> AcademicYearResponse:
        check_college_writable(self.principal, body.college_id)
        if body.college_id is not None:
            await CollegeRepository(self.db, self.principal, self.inst).get_readable(body.college_id)
        y = await self._insert_year(body.name, body.start_date, body.end_date, body.college_id)
        if body.is_current:
            await self._make_current_year(y)
        await self._audit("create", "academic_year", y.id, None, _snap(y, YEAR_KEYS))
        await self._emit("academic_year.created", "academic_year", y.id, {"year_id": str(y.id), "name": y.name})
        return (await self._year_responses([y]))[0]

    async def _insert_year(self, name: str, start: date, end: date, college_id: uuid.UUID | None) -> AcademicYear:
        if await self.years.by_name(self.inst, college_id, name):
            raise APIError(409, ErrorCode.CONFLICT, f"Academic year {name!r} already exists", {"field": "name"})
        clash = await self.years.overlapping(self.inst, college_id, start, end)
        if clash is not None:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Dates overlap academic year {clash.name} ({clash.start_date} – {clash.end_date})",
                {"field": "start_date", "overlaps": str(clash.id)},
            )
        return await self.years.create(
            institution_id=self.inst,
            college_id=college_id,
            name=name,
            start_date=start,
            end_date=end,
            created_by=self.principal.id if self.principal else None,
        )

    async def update_year(self, year_id: uuid.UUID, body: AcademicYearUpdate) -> AcademicYearResponse:
        y = await self._writable_year(year_id)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        start = values.get("start_date", y.start_date)
        end = values.get("end_date", y.end_date)
        if end <= start:
            raise APIError(422, ErrorCode.VALIDATION, "end_date must be after start_date", {"field": "end_date"})
        clash = await self.years.overlapping(self.inst, y.college_id, start, end, exclude=y.id)
        if clash is not None:
            raise APIError(
                422, ErrorCode.VALIDATION, f"Dates overlap academic year {clash.name}", {"field": "start_date"}
            )
        for t in (await self.terms.of_years([y.id])).get(y.id, []):
            if t.start_date < start or t.end_date > end:
                raise APIError(
                    422, ErrorCode.VALIDATION, f"Term {t.name} would fall outside the year", {"field": "start_date"}
                )
        if (
            "name" in values
            and values["name"] != y.name
            and await self.years.by_name(self.inst, y.college_id, values["name"])
        ):
            raise APIError(
                409, ErrorCode.CONFLICT, f"Academic year {values['name']!r} already exists", {"field": "name"}
            )
        old = _snap(y, YEAR_KEYS)
        await self.years.update(y, expected_version=body.version, **values)
        await self._audit("update", "academic_year", y.id, old, _snap(y, YEAR_KEYS))
        return (await self._year_responses([y]))[0]

    async def set_current_year(self, year_id: uuid.UUID) -> AcademicYearResponse:
        y = await self._writable_year(year_id, allow_locked=True)
        old = _snap(y, YEAR_KEYS)
        await self._make_current_year(y)
        await self._audit("set_current", "academic_year", y.id, old, _snap(y, YEAR_KEYS))
        await self._emit("academic_year.current_changed", "academic_year", y.id, {"year_id": str(y.id), "name": y.name})
        return (await self._year_responses([y]))[0]

    async def _make_current_year(self, y: AcademicYear) -> None:
        if y.is_current:
            return
        await self.years.clear_current(self.inst, y.college_id)
        y.is_current = True
        await self.db.flush()

    async def lock_year(self, year_id: uuid.UUID, locked: bool) -> AcademicYearResponse:
        y = await self._writable_year(year_id, allow_locked=True)
        old = {"is_locked": y.is_locked}
        y.is_locked = locked
        await self.db.flush()
        await self._audit("lock" if locked else "unlock", "academic_year", y.id, old, {"is_locked": locked})
        return (await self._year_responses([y]))[0]

    # ---- rule 2: terms --------------------------------------------------------------------------------------------
    async def list_terms(
        self,
        params: PageParams,
        academic_year_id: uuid.UUID | None,
        college_id: uuid.UUID | None,
        status: str | None,
        current_only: bool,
    ) -> tuple[list[AcademicTermResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.terms.filtered(
            academic_year_id=academic_year_id, college_id=college_id, status=status, current_only=current_only
        )
        rows, pagination = await self.terms.paginate(stmt, params)
        return [await self._term_response(t) for t in rows], pagination, self._visibility()

    async def get_term(self, term_id: uuid.UUID) -> AcademicTermResponse:
        return await self._term_response(await self.terms.get_one(term_id), with_checks=True)

    async def current_term(self, college_id: uuid.UUID | None) -> AcademicTermResponse | None:
        t = await self.terms.get_current_term(self.inst, college_id)
        return await self._term_response(t) if t is not None else None

    async def create_term(self, body: AcademicTermCreate) -> AcademicTermResponse:
        y = await self._writable_year(body.academic_year_id)
        t = await self._insert_term(y, body)
        await self._audit("create", "academic_term", t.id, None, _snap(t, TERM_KEYS))
        return await self._term_response(t)

    async def _insert_term(self, y: AcademicYear, body: AcademicTermCreate | RolloverTerm) -> AcademicTerm:
        validate_term_dates(y, body)
        if await self.terms.duplicate(y.id, body.term_type, body.sequence):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"The year already has a {body.term_type} term with sequence {body.sequence}",
                {"field": "sequence"},
            )
        clash = await self.terms.overlapping(y.id, body.start_date, body.end_date)
        if clash is not None:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Dates overlap term {clash.name} ({clash.start_date} – {clash.end_date})",
                {"field": "start_date", "overlaps": str(clash.id)},
            )
        values = body.model_dump(exclude={"academic_year_id"})
        return await self.terms.create(
            institution_id=self.inst,
            college_id=y.college_id,
            academic_year_id=y.id,
            status=TermStatus.PLANNED.value,
            created_by=self.principal.id if self.principal else None,
            **values,
        )

    async def _writable_term(self, term_id: uuid.UUID) -> tuple[AcademicTerm, AcademicYear]:
        t = await self.terms.get_one(term_id, for_update=True)
        y = await self._writable_year(t.academic_year_id)
        if t.is_locked:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"Term {t.name} is locked")
        return t, y

    async def update_term(self, term_id: uuid.UUID, body: AcademicTermUpdate) -> AcademicTermResponse:
        t, y = await self._writable_term(term_id)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        probe = type("Probe", (), {**{k: getattr(t, k) for k in TERM_KEYS}, **values})
        validate_term_dates(y, probe)
        clash = await self.terms.overlapping(y.id, probe.start_date, probe.end_date, exclude=t.id)  # type: ignore[attr-defined]
        if clash is not None:
            raise APIError(422, ErrorCode.VALIDATION, f"Dates overlap term {clash.name}", {"field": "start_date"})
        old = _snap(t, TERM_KEYS)
        await self.terms.update(t, expected_version=body.version, **values)
        await self._audit("update", "academic_term", t.id, old, _snap(t, TERM_KEYS))
        return await self._term_response(t)

    # ---- rule 3: status machine -----------------------------------------------------------------------------------
    async def close_checks(self, t: AcademicTerm) -> list[TermCloseCheck]:
        out = []
        for check in TERM_CLOSE_CHECKS.values():
            res = await check(self.db, t)
            out.append(TermCloseCheck(key=res.key, label=res.label, passed=res.passed, detail=res.detail))
        return out

    async def change_status(self, term_id: uuid.UUID, body: TermStatusChange) -> AcademicTermResponse:
        t, _ = await self._writable_term(term_id)
        if body.version is not None and t.version != body.version:
            raise APIError(
                409, ErrorCode.STALE_VERSION, "Record was modified by someone else", {"current_version": t.version}
            )
        allowed = next_status(t.status)
        target = body.status.value
        if target != allowed:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"Term status can only move forward one step: {t.status} → {allowed or '(none — closed)'}",
                {"current": t.status, "requested": target, "allowed_next": allowed},
            )
        if target == TermStatus.CLOSED:
            if not self.principal.has("sessions", "close"):
                raise APIError(
                    403,
                    ErrorCode.PERMISSION_DENIED,
                    "Requires sessions:close",
                    {"module": "sessions", "action": "close"},
                )
            failing = [c for c in await self.close_checks(t) if not c.passed]
            if failing:
                raise APIError(
                    409,
                    ErrorCode.RULE_VIOLATION,
                    "The term cannot be closed yet",
                    {"blocking_checks": [c.model_dump() for c in failing]},
                )
        old = {"status": t.status}
        t.status = target
        await self.db.flush()
        await self._audit("status", "academic_term", t.id, old, {"status": target})
        await self._emit(
            "academic_term.status_changed",
            "academic_term",
            t.id,
            {
                "term_id": str(t.id),
                "from": old["status"],
                "to": target,
                "college_id": str(t.college_id) if t.college_id else None,
            },
        )
        return await self._term_response(t, with_checks=True)

    # ---- rule 4: rollover -----------------------------------------------------------------------------------------
    async def rollover(self, body: RolloverRequest) -> RolloverResponse:
        check_college_writable(self.principal, body.college_id)
        previous = await self.years.current(self.inst, body.college_id)
        if previous is not None and body.start_date <= previous.end_date:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"The new year must start after the current year {previous.name} ends ({previous.end_date})",
                {"field": "start_date"},
            )
        y = await self._insert_year(body.new_year_name, body.start_date, body.end_date, body.college_id)
        created_terms = [await self._insert_term(y, term) for term in sorted(body.terms, key=lambda x: x.start_date)]
        await self._make_current_year(y)
        await self.terms.clear_current(self.inst, body.college_id)
        first = created_terms[0]
        first.is_current = True
        if previous is not None and body.lock_previous:
            previous.is_locked = True
        await self.db.flush()
        promoted: dict[str, int] = {}
        if body.promote_batches:
            for key, hook in ROLLOVER_HOOKS.items():
                promoted[key] = await hook(self.db, self.principal, previous, y)
        await self._audit(
            "rollover",
            "academic_year",
            y.id,
            {"previous_year_id": str(previous.id) if previous else None},
            {**_snap(y, YEAR_KEYS), "terms": [t.name for t in created_terms], "promoted": promoted},
        )
        event_id = await self._emit(
            "academic_year.rolled_over",
            "academic_year",
            y.id,
            {
                "previous_year_id": str(previous.id) if previous else None,
                "year_id": str(y.id),
                "name": y.name,
                "college_id": str(body.college_id) if body.college_id else None,
                "promote_batches": body.promote_batches,
                "current_term_id": str(first.id),
            },
        )
        return RolloverResponse(
            previous_year_id=previous.id if previous else None,
            year=(await self._year_responses([y]))[0],
            current_term_id=first.id,
            promoted=promoted,
            event_id=event_id,
        )

    # ---- rule 5 ---------------------------------------------------------------------------------------------------
    async def set_current_term(self, term_id: uuid.UUID) -> AcademicTermResponse:
        t = await self.terms.get_one(term_id, for_update=True)
        y = await self._writable_year(t.academic_year_id, allow_locked=True)
        await self.terms.clear_current(self.inst, t.college_id)
        t.is_current = True
        await self._make_current_year(y)
        await self.db.flush()
        await self._audit("set_current", "academic_term", t.id, None, {"is_current": True})
        await self._emit(
            "academic_term.changed",
            "academic_term",
            t.id,
            {
                "term_id": str(t.id),
                "year_id": str(y.id),
                "college_id": str(t.college_id) if t.college_id else None,
                "name": t.name,
            },
        )
        return await self._term_response(t)

    # ---- audit / events -------------------------------------------------------------------------------------------
    async def _audit(
        self,
        action: str,
        record_type: str,
        record_id: uuid.UUID,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
    ) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module="sessions",
            action=action,
            record_type=record_type,
            record_id=record_id,
            old=old,
            new=new,
            request=self.request,
        )

    async def _emit(
        self, event_type: str, aggregate: str, aggregate_id: uuid.UUID, payload: dict[str, Any]
    ) -> uuid.UUID:
        return await events.emit(
            self.db,
            institution_id=self.inst,
            event_type=event_type,
            payload=payload,
            aggregate_type=aggregate,
            aggregate_id=aggregate_id,
            actor_user_id=self.principal.id if self.principal else None,
        )


async def auto_advance_term(db: AsyncSession, t: AcademicTerm, today: date) -> str | None:
    """Beat ``terms.auto_status`` (platform session): planned→registration / registration→in_progress."""
    if t.status == TermStatus.PLANNED and t.registration_start and t.registration_start <= today:
        target = TermStatus.REGISTRATION.value
    elif t.status == TermStatus.REGISTRATION and t.start_date <= today:
        target = TermStatus.IN_PROGRESS.value
    else:
        return None
    previous = t.status
    t.status = target
    await db.flush()
    await events.emit(
        db,
        institution_id=t.institution_id,
        event_type="academic_term.status_changed",
        payload={"term_id": str(t.id), "from": previous, "to": target, "auto": True},
        aggregate_type="academic_term",
        aggregate_id=t.id,
    )
    return target
