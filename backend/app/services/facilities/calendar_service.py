"""Calendar — Prompts/25 §25.6 ``calendar_service`` ({calendar.core}, {calendar.ical}, {calendar.personal_feed}).

1. **Source registry** — ``register_source(key, fn)``; each source maps its own rows into ``CalendarItem`` for a
   window and a scope: academic terms (start / registration / add-drop / last instruction / end), holidays,
   registration windows, published exam papers (date-sheet), events (scheduled / completed), approved room bookings
   (facilities view), my classes, my hostel leaves, my registered events / bookings, and the manual
   ``calendar_events`` rows (audience rules evaluated against the caller). Later phases register more (meetings,
   placement drives) the same way.
2. **Scopes** — ``mine`` (institution + my college + personal sources), ``college`` (one college), ``institution``
   (institution-wide items only). Manual entries are edited by ``calendar:manage`` holders.
3. **iCal** — institution / college ``.ics`` (public), personal feed by revocable token (the Phase 10
   ``calendar_feed_tokens`` row — one live token per user); ``webcal://`` URL.
4. **Reminders** — Beat every 15 min: manual entries / scheduled events starting in the next T-1 h / T-1 day window.
5. **PDF** — year at a glance (job), deadlines for the Home widget, exam-day overlap warnings.
"""

import hashlib
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, or_, select

from app.core.errors import APIError, ErrorCode
from app.enums.facilities import EVENT_TYPE_COLORS
from app.models.academic import AcademicTerm
from app.models.calendar import CalendarEvent, CalendarFeedToken
from app.models.events import Event, EventRegistration
from app.models.exams import ExamPaper, ExamSession
from app.models.facilities import RoomBooking
from app.models.platform import Holiday
from app.models.registration import RegistrationWindow
from app.models.students import StudentProgramEnrollment
from app.models.timetable import ClassSession, Room
from app.schemas.calendar import (
    CalendarDeadline,
    CalendarEventIn,
    CalendarEventOut,
    CalendarFeedTokenOut,
    CalendarItem,
    CalendarOut,
)
from app.services.facilities.common import FacilitiesBase, forbidden, not_found, now_utc, rule, scope_ids

SourceFn = Callable[["CalendarService", datetime, datetime, str], Awaitable[list[CalendarItem]]]
SOURCES: dict[str, SourceFn] = {}
PERSONAL_SOURCES = {"my_classes", "my_events", "my_bookings", "my_hostel_leaves"}


def register_source(key: str) -> Callable[[SourceFn], SourceFn]:
    def deco(fn: SourceFn) -> SourceFn:
        SOURCES[key] = fn
        return fn

    return deco


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _day(d: date, tz: Any, end: bool = False) -> datetime:
    return datetime.combine(d, time(23, 59) if end else time(0, 0), tzinfo=tz).astimezone(UTC)


def _item(
    key: str,
    title: str,
    event_type: str,
    source_type: str,
    starts: datetime,
    ends: datetime | None = None,
    **kw: Any,
) -> CalendarItem:
    return CalendarItem(
        key=key,
        title=title,
        event_type=event_type,
        source_type=source_type,
        starts_at=starts,
        ends_at=ends,
        color=kw.pop("color", None) or EVENT_TYPE_COLORS.get(event_type) or EVENT_TYPE_COLORS["general"],
        **kw,
    )


class CalendarService(FacilitiesBase):
    audit_module = "calendar"
    module = "calendar"

    async def tz(self) -> Any:
        from app.core.tenancy import institution_tz

        return institution_tz(await self.institution())

    async def my_college_ids(self) -> list[uuid.UUID]:
        ids = set(scope_ids(self.principal, "college"))
        st = await self.my_student()
        if st is not None:
            ids.add(st.college_id)
        sf = await self.my_staff()
        if sf is not None and sf.college_id:
            ids.add(sf.college_id)
        return list(ids)

    # ---- audience ---------------------------------------------------------------------------------------------------------
    async def _me_context(self) -> dict[str, Any]:
        if getattr(self, "_ctx", None) is not None:
            return self._ctx  # type: ignore[no-any-return,has-type]
        p = self.principal
        roles = set(getattr(p, "roles", None) or [])
        ctx: dict[str, Any] = {"roles": roles, "person_types": set(), "departments": set(), "programs": set()}
        st = await self.my_student()
        if st is not None:
            ctx["person_types"].add("student")
            for dep, prog in (
                await self.db.execute(
                    select(StudentProgramEnrollment.department_id, StudentProgramEnrollment.program_id).where(
                        StudentProgramEnrollment.student_id == st.id
                    )
                )
            ).all():
                ctx["departments"].add(dep)
                ctx["programs"].add(prog)
        sf = await self.my_staff()
        if sf is not None:
            ctx["person_types"].add("staff")
            if sf.department_id:
                ctx["departments"].add(sf.department_id)
        if "parent" in roles:
            ctx["person_types"].add("guardian")
        self._ctx = ctx
        return ctx

    async def audience_match(self, rules: dict[str, Any] | None) -> bool:
        if not rules:
            return True
        if self.principal is None:  # public feeds carry only unrestricted entries
            return not any(rules.get(k) for k in ("person_types", "roles", "department_ids", "program_ids"))
        if getattr(self.principal, "is_super_admin", False):
            return True
        if self.can("calendar", "manage"):
            return True
        ctx = await self._me_context()
        pts, roles = rules.get("person_types") or [], rules.get("roles") or []
        depts = {str(d) for d in rules.get("department_ids") or []}
        progs = {str(d) for d in rules.get("program_ids") or []}
        if pts and not (set(pts) & ctx["person_types"]):
            return False
        if roles and not (set(roles) & ctx["roles"]):
            return False
        if depts and not (depts & {str(d) for d in ctx["departments"]}):
            return False
        return not (progs and not (progs & {str(p) for p in ctx["programs"]}))

    # ---- merged view ------------------------------------------------------------------------------------------------------
    async def view(
        self,
        date_from: datetime | None,
        date_to: datetime | None,
        types: list[str] | None = None,
        college_id: uuid.UUID | None = None,
        scope: str = "mine",
    ) -> CalendarOut:
        if scope not in ("mine", "college", "institution"):
            raise APIError(422, ErrorCode.VALIDATION, "scope must be mine | college | institution")
        tz = await self.tz()
        today = await self.today()
        f = date_from or _day(today.replace(day=1), tz)
        t = date_to or (f + timedelta(days=42))
        if (t - f).days > 400:
            raise APIError(422, ErrorCode.VALIDATION, "The window may span at most 400 days")
        self._college = college_id
        items: list[CalendarItem] = []
        used: list[str] = []
        for key, fn in SOURCES.items():
            if scope != "mine" and key in PERSONAL_SOURCES:
                continue
            got = await fn(self, f, t, scope)
            if got:
                used.append(key)
            items += got
        if types:
            items = [i for i in items if i.event_type in types or i.source_type in types]
        items.sort(key=lambda i: (i.starts_at, i.title))
        return CalendarOut(
            from_at=f, to_at=t, scope=scope, items=items, sources=sorted(SOURCES), conflicts=self._exam_overlaps(items)
        )

    def _college_filter(self, col: Any, scope: str, mine: list[uuid.UUID]) -> Any:
        college = getattr(self, "_college", None)
        if scope == "institution":
            return col.is_(None)
        if scope == "college" and college:
            return or_(col.is_(None), col == college)
        return or_(col.is_(None), col.in_(mine or [uuid.uuid4()]))

    @staticmethod
    def _exam_overlaps(items: list[CalendarItem]) -> list[dict[str, Any]]:
        exam_days = {i.starts_at.date() for i in items if i.event_type == "exam"}
        return [
            {"key": i.key, "title": i.title, "date": i.starts_at.date().isoformat(), "reason": "overlaps an exam day"}
            for i in items
            if i.source_type == "event" and i.starts_at.date() in exam_days
        ]

    # ---- manual entries -----------------------------------------------------------------------------------------------------
    async def list_manual(self, date_from: datetime | None, date_to: datetime | None) -> list[CalendarEventOut]:
        stmt = select(CalendarEvent).where(
            CalendarEvent.institution_id == self.inst,
            CalendarEvent.deleted_at.is_(None),
            CalendarEvent.source_type.is_(None),
        )
        if date_from:
            stmt = stmt.where(CalendarEvent.starts_at >= date_from)
        if date_to:
            stmt = stmt.where(CalendarEvent.starts_at <= date_to)
        rows = (await self.db.execute(stmt.order_by(CalendarEvent.starts_at).limit(1000))).scalars().all()
        return [CalendarEventOut.model_validate(r) for r in rows if await self.audience_match(r.audience_rules)]

    async def _manual(self, eid: uuid.UUID) -> CalendarEvent:
        row = (
            await self.db.execute(
                select(CalendarEvent).where(
                    CalendarEvent.id == eid,
                    CalendarEvent.institution_id == self.inst,
                    CalendarEvent.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise not_found("Calendar entry")
        return row

    def _check_college(self, college_id: uuid.UUID | None) -> None:
        if self.all_access() or getattr(self.principal, "is_super_admin", False):
            return
        if college_id is None or college_id not in scope_ids(self.principal, "college"):
            raise forbidden("You manage the calendar of your college only")

    async def create(self, body: CalendarEventIn) -> CalendarEventOut:
        self.require("calendar:manage")
        self._check_college(body.college_id)
        if body.ends_at and body.ends_at < body.starts_at:
            raise APIError(422, ErrorCode.VALIDATION, "ends_at must not be before starts_at")
        row = CalendarEvent(
            institution_id=self.inst,
            college_id=body.college_id,
            title=body.title,
            description=body.description,
            event_type=body.event_type,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            all_day=body.all_day,
            location=body.location,
            audience_rules=body.audience_rules.model_dump(mode="json") if body.audience_rules else None,
            color=body.color,
            created_by=self.actor_id,
        )
        self.db.add(row)
        await self.db.flush()
        await self._audit("create", "calendar_event", row.id, None, {"title": row.title})
        await self._emit("calendar.event_created", {"calendar_event_id": str(row.id)}, "calendar_event", row.id)
        return CalendarEventOut.model_validate(row)

    async def update(self, eid: uuid.UUID, body: CalendarEventIn) -> CalendarEventOut:
        self.require("calendar:manage")
        row = await self._manual(eid)
        if row.source_type:
            raise rule("Entries mirrored from another module are edited at their source", "SOURCE_OWNED")
        self._check_college(row.college_id)
        self._check_college(body.college_id)
        data = body.model_dump()
        data["audience_rules"] = body.audience_rules.model_dump(mode="json") if body.audience_rules else None
        for k, v in data.items():
            setattr(row, k, v)
        await self.db.flush()
        await self.db.refresh(row)
        await self._audit("update", "calendar_event", row.id, None, {"title": row.title})
        await self._emit("calendar.event_updated", {"calendar_event_id": str(row.id)}, "calendar_event", row.id)
        return CalendarEventOut.model_validate(row)

    async def delete(self, eid: uuid.UUID) -> None:
        self.require("calendar:manage")
        row = await self._manual(eid)
        self._check_college(row.college_id)
        row.deleted_at = now_utc()
        await self.db.flush()
        await self._audit("delete", "calendar_event", row.id, {"title": row.title}, None)

    # ---- mirror rows (bookings / events write their own calendar entries) ------------------------------------------------
    async def mirror(
        self,
        source_type: str,
        source_id: uuid.UUID,
        *,
        title: str,
        starts: datetime,
        ends: datetime | None,
        event_type: str = "general",
        college_id: uuid.UUID | None = None,
        location: str | None = None,
        audience: dict[str, Any] | None = None,
    ) -> None:
        row = (
            await self.db.execute(
                select(CalendarEvent).where(
                    CalendarEvent.institution_id == self.inst,
                    CalendarEvent.source_type == source_type,
                    CalendarEvent.source_id == source_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = CalendarEvent(
                institution_id=self.inst, source_type=source_type, source_id=source_id, created_by=self.actor_id
            )
            self.db.add(row)
        row.title, row.starts_at, row.ends_at, row.event_type = title[:200], starts, ends, event_type
        row.college_id, row.location, row.audience_rules, row.deleted_at = college_id, location, audience, None
        await self.db.flush()

    async def unmirror(self, source_type: str, source_id: uuid.UUID) -> None:
        for row in (
            await self.db.execute(
                select(CalendarEvent).where(
                    CalendarEvent.institution_id == self.inst,
                    CalendarEvent.source_type == source_type,
                    CalendarEvent.source_id == source_id,
                    CalendarEvent.deleted_at.is_(None),
                )
            )
        ).scalars():
            row.deleted_at = now_utc()
        await self.db.flush()

    # ---- feeds ----------------------------------------------------------------------------------------------------------
    async def create_token(self, base_url: str) -> CalendarFeedTokenOut:
        if self.actor_id is None:
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Sign in first")
        await self.require_feature("calendar.personal_feed")
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
        row = CalendarFeedToken(institution_id=self.inst, user_id=self.actor_id, token_hash=token_hash(token))
        self.db.add(row)
        await self.db.flush()
        await self._audit("create", "calendar_feed_token", row.id, None, {"user_id": str(self.actor_id)})
        await self._emit("calendar.feed_token_created", {"user_id": str(self.actor_id)}, "calendar_feed_token", row.id)
        url = f"{base_url}/api/v1/calendar/feed/{token}.ics"
        webcal = "webcal://" + url.split("://", 1)[-1]
        return CalendarFeedTokenOut(url=url, webcal_url=webcal, created_at=row.created_at)

    async def revoke_token(self) -> CalendarFeedTokenOut:
        n = 0
        for row in (
            await self.db.execute(
                select(CalendarFeedToken).where(
                    CalendarFeedToken.user_id == self.actor_id, CalendarFeedToken.revoked_at.is_(None)
                )
            )
        ).scalars():
            row.revoked_at, n = now_utc(), n + 1
        await self.db.flush()
        if n:
            await self._audit("revoke", "calendar_feed_token", None, None, {"user_id": str(self.actor_id)})
            await self._emit(
                "calendar.feed_token_revoked", {"user_id": str(self.actor_id)}, "calendar_feed_token", None
            )
        return CalendarFeedTokenOut(revoked=True)

    async def feed_window(self) -> tuple[datetime, datetime]:
        tz = await self.tz()
        today = await self.today()
        return _day(today - timedelta(days=14), tz), _day(today + timedelta(days=180), tz, end=True)

    async def render_ics(self, items: list[CalendarItem], name: str) -> str:
        def stamp(d: datetime) -> str:
            return d.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

        now = stamp(now_utc())
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//SeptronUniverse//Calendar//EN",
            f"X-WR-CALNAME:{esc(name)}",
        ]
        for i in items:
            lines += ["BEGIN:VEVENT", f"UID:{i.key}@septron-universe", f"DTSTAMP:{now}"]
            if i.all_day:
                lines.append(f"DTSTART;VALUE=DATE:{i.starts_at.strftime('%Y%m%d')}")
                end = (i.ends_at or i.starts_at) + timedelta(days=1)
                lines.append(f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}")
            else:
                lines.append(f"DTSTART:{stamp(i.starts_at)}")
                lines.append(f"DTEND:{stamp(i.ends_at or (i.starts_at + timedelta(hours=1)))}")
            lines.append(f"SUMMARY:{esc(i.title)}")
            lines.append(f"CATEGORIES:{esc(i.event_type)}")
            if i.location:
                lines.append(f"LOCATION:{esc(i.location)}")
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines) + "\r\n"

    async def public_items(self, college_id: uuid.UUID | None) -> list[CalendarItem]:
        f, t = await self.feed_window()
        out = await self.view(f, t, None, college_id, "college" if college_id else "institution")
        return [i for i in out.items if i.source_type not in ("room_booking",)]

    # ---- deadlines / PDF -----------------------------------------------------------------------------------------------
    async def deadlines(self) -> list[CalendarDeadline]:
        tz = await self.tz()
        today = await self.today()
        out = await self.view(_day(today, tz), _day(today + timedelta(days=60), tz, end=True), None, None, "mine")
        rows = [
            CalendarDeadline(
                title=i.title,
                due_at=i.starts_at,
                source_type=i.source_type,
                days_left=(i.starts_at.astimezone(tz).date() - today).days,
            )
            for i in out.items
            if i.event_type in ("deadline", "registration", "exam")
        ]
        return rows[:20]

    async def year_pdf(self, academic_year_id: uuid.UUID | None) -> dict[str, Any]:
        from app.core.files import build_key, get_storage
        from app.models.academic import AcademicYear
        from app.utils.pdf import simple_pdf

        tz = await self.tz()
        year = None
        if academic_year_id:
            year = (
                await self.db.execute(select(AcademicYear).where(AcademicYear.id == academic_year_id))
            ).scalar_one_or_none()
        if year is None:
            year = await self.current_year(None)
        if year is None:
            raise rule("No academic year to print", "NO_YEAR")
        out = await self.view(_day(year.start_date, tz), _day(year.end_date, tz, end=True), None, None, "institution")
        lines = [f"Academic calendar {year.name}", ""]
        month = ""
        for i in out.items:
            m = i.starts_at.astimezone(tz).strftime("%B %Y")
            if m != month:
                lines += ["", m.upper()]
                month = m
            lines.append(f"  {i.starts_at.astimezone(tz).strftime('%d %a')}  {i.title} ({i.event_type})")
        pdf = simple_pdf(lines, title=f"Academic calendar {year.name}")
        key = build_key(self.inst, "calendar", f"academic-calendar-{year.name}.pdf".replace("/", "-"))
        storage = get_storage()
        await storage.put(key, pdf, "application/pdf")
        return {"result_url": storage.signed_url(key), "entries": len(out.items)}

    # ---- reminders (Beat) ----------------------------------------------------------------------------------------------
    async def reminders(self) -> int:
        now = now_utc()
        sent = 0
        for lead, label in ((timedelta(hours=1), "in 1 hour"), (timedelta(days=1), "tomorrow")):
            lo, hi = now + lead, now + lead + timedelta(minutes=15)
            rows = (
                (
                    await self.db.execute(
                        select(CalendarEvent).where(
                            CalendarEvent.institution_id == self.inst,
                            CalendarEvent.deleted_at.is_(None),
                            CalendarEvent.source_type.is_(None),
                            CalendarEvent.starts_at >= lo,
                            CalendarEvent.starts_at < hi,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for r in rows:
                rules = r.audience_rules or {}
                audience: dict[str, Any] = {"roles": rules.get("roles") or []}
                if not audience["roles"]:
                    pts = rules.get("person_types") or ["student", "staff"]
                    audience = {
                        "roles": (["student"] if "student" in pts else []) + (["faculty"] if "staff" in pts else [])
                    }
                await self._notify("calendar.reminder", [], {"title": r.title, "starts": label}, audience=audience)
                sent += 1
        return sent


# ---- sources ----------------------------------------------------------------------------------------------------------------
@register_source("manual")
async def _src_manual(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    mine = await svc.my_college_ids()
    rows = (
        (
            await svc.db.execute(
                select(CalendarEvent).where(
                    CalendarEvent.institution_id == svc.inst,
                    CalendarEvent.deleted_at.is_(None),
                    or_(CalendarEvent.source_type.is_(None), CalendarEvent.source_type.in_(("exam_paper", "manual"))),
                    CalendarEvent.starts_at <= t,
                    or_(CalendarEvent.ends_at.is_(None), CalendarEvent.ends_at >= f, CalendarEvent.starts_at >= f),
                    svc._college_filter(CalendarEvent.college_id, scope, mine),
                )
            )
        )
        .scalars()
        .all()
    )
    manage = svc.can("calendar", "manage")
    out = []
    for r in rows:
        if not await svc.audience_match(r.audience_rules):
            continue
        out.append(
            _item(
                f"cal-{r.id}",
                r.title,
                r.event_type,
                r.source_type or "manual",
                r.starts_at,
                r.ends_at,
                source_id=r.id,
                all_day=r.all_day,
                location=r.location,
                color=r.color,
                college_id=r.college_id,
                editable=manage and r.source_type is None,
            )
        )
    return out


@register_source("academic_terms")
async def _src_terms(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    tz = await svc.tz()
    mine = await svc.my_college_ids()
    rows = (
        (
            await svc.db.execute(
                select(AcademicTerm).where(
                    AcademicTerm.institution_id == svc.inst,
                    AcademicTerm.start_date <= t.date(),
                    AcademicTerm.end_date >= f.date() - timedelta(days=60),
                    svc._college_filter(AcademicTerm.college_id, scope, mine),
                )
            )
        )
        .scalars()
        .all()
    )
    out: list[CalendarItem] = []
    for term in rows:
        marks = [
            ("start", term.start_date, f"{term.name} begins", "academic"),
            ("reg_start", term.registration_start, f"{term.name}: registration opens", "registration"),
            ("reg_end", term.registration_end, f"{term.name}: registration closes", "deadline"),
            ("add_drop", term.add_drop_end, f"{term.name}: last day of add / drop", "deadline"),
            ("last_instr", term.last_instruction_date, f"{term.name}: last instruction day", "academic"),
            ("end", term.end_date, f"{term.name} ends", "academic"),
        ]
        for code, d, title, et in marks:
            if d is None:
                continue
            at = _day(d, tz)
            if f <= at <= t:
                out.append(
                    _item(
                        f"term-{term.id}-{code}",
                        title,
                        et,
                        "academic_term",
                        at,
                        source_id=term.id,
                        all_day=True,
                        college_id=term.college_id,
                    )
                )
    return out


@register_source("holidays")
async def _src_holidays(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    tz = await svc.tz()
    mine = await svc.my_college_ids()
    ctx = await svc._me_context()
    rows = (
        (
            await svc.db.execute(
                select(Holiday).where(
                    Holiday.institution_id == svc.inst,
                    Holiday.holiday_date <= t.date(),
                    or_(Holiday.holiday_date >= f.date(), Holiday.end_date >= f.date()),
                    svc._college_filter(Holiday.college_id, scope, mine),
                )
            )
        )
        .scalars()
        .all()
    )
    out = []
    for h in rows:
        if (
            scope == "mine"
            and h.applies_to == "students"
            and "student" not in ctx["person_types"]
            and "guardian" not in ctx["person_types"]
        ):
            continue
        if scope == "mine" and h.applies_to == "staff" and "staff" not in ctx["person_types"]:
            continue
        out.append(
            _item(
                f"hol-{h.id}",
                h.name,
                "holiday",
                "holiday",
                _day(h.holiday_date, tz),
                _day(h.end_date or h.holiday_date, tz, end=True),
                source_id=h.id,
                all_day=True,
                college_id=h.college_id,
            )
        )
    return out


@register_source("registration_windows")
async def _src_windows(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    mine = await svc.my_college_ids()
    rows = (
        (
            await svc.db.execute(
                select(RegistrationWindow).where(
                    RegistrationWindow.institution_id == svc.inst,
                    RegistrationWindow.starts_at <= t,
                    RegistrationWindow.ends_at >= f,
                    RegistrationWindow.status != "cancelled",
                    svc._college_filter(RegistrationWindow.college_id, scope, mine),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        _item(
            f"rw-{w.id}",
            w.name,
            "registration",
            "registration_window",
            w.starts_at,
            w.ends_at,
            source_id=w.id,
            college_id=w.college_id,
            link="/student/registration",
        )
        for w in rows
    ]


@register_source("exam_papers")
async def _src_exams(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    tz = await svc.tz()
    mine = await svc.my_college_ids()
    rows = (
        await svc.db.execute(
            select(ExamPaper, ExamSession.name, ExamSession.college_id)
            .join(ExamSession, ExamSession.id == ExamPaper.exam_session_id)
            .where(
                ExamSession.institution_id == svc.inst,
                ExamSession.deleted_at.is_(None),
                ExamSession.status.notin_(("draft", "cancelled")),
                ExamPaper.exam_date.is_not(None),
                ExamPaper.exam_date >= f.date(),
                ExamPaper.exam_date <= t.date(),
                svc._college_filter(ExamSession.college_id, scope, mine),
            )
            .limit(2000)
        )
    ).all()
    out = []
    for paper, session_name, college_id in rows:
        assert paper.exam_date is not None
        start = (
            datetime.combine(paper.exam_date, paper.start_time, tzinfo=tz).astimezone(UTC)
            if paper.start_time
            else _day(paper.exam_date, tz)
        )
        end = start + timedelta(minutes=paper.duration_minutes or 180) if paper.start_time else None
        out.append(
            _item(
                f"exam-{paper.id}",
                f"{session_name}: {paper.paper_code or 'paper'}",
                "exam",
                "exam_paper",
                start,
                end,
                source_id=paper.id,
                all_day=paper.start_time is None,
                college_id=college_id,
            )
        )
    return out


@register_source("events")
async def _src_events(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    tz = await svc.tz()
    mine = await svc.my_college_ids()
    rows = (
        await svc.db.execute(
            select(Event, Room.code)
            .outerjoin(Room, Room.id == Event.venue_room_id)
            .where(
                Event.institution_id == svc.inst,
                Event.deleted_at.is_(None),
                Event.status.in_(("scheduled", "completed")),
                Event.from_on <= t.date(),
                Event.to_on >= f.date(),
                svc._college_filter(Event.college_id, scope, mine),
            )
        )
    ).all()
    return [
        _item(
            f"event-{e.id}",
            e.title,
            "event",
            "event",
            _day(e.from_on, tz),
            _day(e.to_on, tz, end=True),
            source_id=e.id,
            all_day=True,
            location=room or e.venue_text,
            college_id=e.college_id,
            link=f"/events/{e.id}",
        )
        for e, room in rows
    ]


@register_source("room_bookings")
async def _src_bookings(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    if scope == "mine" or not (svc.can("facilities", "view_all") or svc.can("facilities", "manage")):
        return []
    rows = (
        await svc.db.execute(
            select(RoomBooking, Room.code, Room.college_id)
            .join(Room, Room.id == RoomBooking.room_id)
            .where(
                RoomBooking.institution_id == svc.inst,
                RoomBooking.status == "approved",
                RoomBooking.from_at <= t,
                RoomBooking.to_at >= f,
            )
            .limit(1000)
        )
    ).all()
    return [
        _item(
            f"bk-{b.id}",
            f"{code}: {b.purpose}",
            "booking",
            "room_booking",
            b.from_at,
            b.to_at,
            source_id=b.id,
            location=code,
            college_id=college,
        )
        for b, code, college in rows
    ]


@register_source("my_classes")
async def _src_classes(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    if svc.principal is None or (t - f).days > 120:
        return []
    from app.repositories.timetable_scope import own_sessions_predicate

    tz = await svc.tz()
    rows = (
        await svc.db.execute(
            select(ClassSession, Room.code)
            .outerjoin(Room, Room.id == ClassSession.room_id)
            .where(
                ClassSession.institution_id == svc.inst,
                ClassSession.session_date >= f.date(),
                ClassSession.session_date <= t.date(),
                ClassSession.status.in_(("scheduled", "conducted")),
                own_sessions_predicate(svc.principal),
            )
            .limit(1500)
        )
    ).all()
    return [
        _item(
            f"cls-{s.id}",
            s.topic or s.session_type.title(),
            "class",
            "class_session",
            datetime.combine(s.session_date, s.start_time, tzinfo=tz).astimezone(UTC),
            datetime.combine(s.session_date, s.end_time, tzinfo=tz).astimezone(UTC),
            source_id=s.id,
            location=room,
            college_id=s.college_id,
        )
        for s, room in rows
    ]


@register_source("my_events")
async def _src_my_events(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    if svc.principal is None:
        return []
    try:
        ptype, pid = await svc.me_person()
    except APIError:
        return []
    tz = await svc.tz()
    rows = (
        (
            await svc.db.execute(
                select(Event)
                .join(EventRegistration, EventRegistration.event_id == Event.id)
                .where(
                    EventRegistration.person_type == ptype,
                    EventRegistration.person_id == pid,
                    Event.status.in_(("approved", "scheduled")),
                    Event.from_on <= t.date(),
                    Event.to_on >= f.date(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        _item(
            f"myev-{e.id}",
            f"Registered: {e.title}",
            "event",
            "event_registration",
            _day(e.from_on, tz),
            _day(e.to_on, tz, end=True),
            source_id=e.id,
            all_day=True,
        )
        for e in rows
    ]


@register_source("my_bookings")
async def _src_my_bookings(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    if svc.actor_id is None:
        return []
    rows = (
        await svc.db.execute(
            select(RoomBooking, Room.code)
            .join(Room, Room.id == RoomBooking.room_id)
            .where(
                RoomBooking.requested_by == svc.actor_id,
                RoomBooking.status.in_(("requested", "approved")),
                RoomBooking.from_at <= t,
                RoomBooking.to_at >= f,
            )
        )
    ).all()
    return [
        _item(
            f"mybk-{b.id}",
            f"{code}: {b.purpose} ({b.status})",
            "booking",
            "my_booking",
            b.from_at,
            b.to_at,
            source_id=b.id,
            location=code,
        )
        for b, code in rows
    ]


@register_source("my_hostel_leaves")
async def _src_leaves(svc: CalendarService, f: datetime, t: datetime, scope: str) -> list[CalendarItem]:
    st = await svc.my_student()
    if st is None:
        return []
    from app.models.hostel import HostelLeave

    rows = (
        (
            await svc.db.execute(
                select(HostelLeave).where(
                    HostelLeave.student_program_enrollment_id.in_(
                        select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.student_id == st.id)
                    ),
                    and_(HostelLeave.from_at <= t, HostelLeave.to_at >= f),
                    HostelLeave.status.notin_(("rejected", "cancelled")),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        _item(
            f"leave-{lv.id}",
            f"Hostel leave ({lv.status})",
            "general",
            "hostel_leave",
            lv.from_at,
            lv.to_at,
            source_id=lv.id,
        )
        for lv in rows
    ]


# ---- public feeds (resolved on the platform session, rendered inside the tenant session) --------------------------------
async def personal_ics(token: str) -> str | None:
    """``GET /calendar/feed/{token}.ics`` — the token's user, their personal (``mine``) calendar."""
    from app.core.features import is_enabled
    from app.db.session import PlatformSessionLocal, tenant_session
    from app.services.auth_service import load_principal

    async with PlatformSessionLocal() as pdb:
        row = (
            await pdb.execute(
                select(CalendarFeedToken).where(
                    CalendarFeedToken.token_hash == token_hash(token), CalendarFeedToken.revoked_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        iid, uid = row.institution_id, row.user_id
    if not await is_enabled(iid, "calendar.personal_feed"):
        return None
    db = await tenant_session(iid)
    try:
        principal = await load_principal(db, uid)
        svc = CalendarService(db, principal, institution_id=iid)
        f, t = await svc.feed_window()
        out = await svc.view(f, t, None, None, "mine")
        return await svc.render_ics(out.items, "My calendar")
    finally:
        await db.close()


async def public_ics(institution_slug: str | None = None, college_id: uuid.UUID | None = None) -> str | None:
    """Institution / college ``.ics`` (public when {calendar.ical} is on)."""
    from app.core.features import is_enabled
    from app.db.session import PlatformSessionLocal, tenant_session
    from app.models.platform import College, Institution

    async with PlatformSessionLocal() as pdb:
        if college_id is not None:
            iid = (
                await pdb.execute(select(College.institution_id).where(College.id == college_id))
            ).scalar_one_or_none()
        else:
            iid = (
                await pdb.execute(
                    select(Institution.id).where(Institution.slug == institution_slug, Institution.deleted_at.is_(None))
                )
            ).scalar_one_or_none()
    if iid is None or not await is_enabled(iid, "calendar.ical"):
        return None
    db = await tenant_session(iid)
    try:
        svc = CalendarService(db, None, institution_id=iid)
        items = await svc.public_items(college_id)
        name = (await svc.institution()).name
        return await svc.render_ics(items, f"{name} calendar")
    finally:
        await db.close()
