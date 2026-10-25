"""Clubs, activity hours & achievements — Prompts/27 §27.6 ``club_service`` ({clubs.core},
{clubs.activity_hours_credits}, {clubs.achievements}).

1. Clubs (type, advisor, budget), members with roles (office bearers), join requests (``role='pending'`` until the
   advisor approves), club events linked to Phase 25 ``events`` (``clubs.event_recorded``; optional hours for the
   members).
2. Activity-hours ledger: entries by the student (with evidence) or officers (bulk); verification — holders of
   ``clubs:verify_hours`` (NSS / NCC / sports officers) verify any entry; a club advisor verifies only ``club`` hours
   logged against a club they advise (anything else → 403). Verified totals against ``clubs.hours_to_credits``
   (``[{course_id, min_hours, activity_types?}]``) mark the contributing rows' ``credits_course_id`` and emit
   ``activity.credit_eligible`` for the Phase 15 non-credit result path ({clubs.activity_hours_credits}).
   Community-service sanctions read the same ledger (``community_service`` hours vs the case target).
3. Achievements: students submit with evidence; officers / advisors verify (``achievement.verified`` → Phase 28
   profile, Phase 32 counts, Phase 26 certificates). Sports participation verified in Phase 25 already writes a
   verified achievement row.
"""

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, true
from sqlalchemy.exc import IntegrityError

from app.models.clubs import ActivityHour, Club, ClubEvent, ClubMember
from app.models.curriculum import Course
from app.models.discipline import DisciplinaryCase
from app.models.events import Event
from app.models.post_result import StudentAchievement
from app.models.students import StudentProgramEnrollment
from app.schemas.clubs import (
    AchCreate,
    AchOut,
    AchVerify,
    ActCreditEligible,
    ActHourBulk,
    ActHourCreate,
    ActHourOut,
    ActLedger,
    ActVerify,
    ActVerifyResult,
    ClubEventIn,
    ClubEventOut,
    ClubIn,
    ClubMemberDecide,
    ClubMemberIn,
    ClubMemberOut,
    ClubMemberRole,
    ClubOut,
)
from app.services.student_support.common import SupportBase, all_access, forbidden, not_found, now_utc, rule

CLUB_ACTIVITY = {"nss": "nss", "ncc": "ncc", "sports": "sports"}


class ClubService(SupportBase):
    audit_module = "clubs"
    module = "clubs"

    # ---- helpers --------------------------------------------------------------------------------------------------------
    def officer(self) -> bool:
        return self.can("clubs", "verify_hours")

    def admin(self) -> bool:
        return self.can("clubs", "manage") and not self._auditor()

    def _auditor(self) -> bool:
        from app.services.student_support.common import is_auditor

        return is_auditor(self.principal)

    async def advised_club_ids(self) -> list[uuid.UUID]:
        staff_id = await self.my_staff_id()
        if staff_id is None:
            return []
        return [r[0] for r in (await self.db.execute(select(Club.id).where(Club.faculty_advisor_id == staff_id))).all()]

    async def _club(self, cid: uuid.UUID, *, lock: bool = False) -> Club:
        stmt = select(Club).where(Club.id == cid, Club.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        c = (await self.db.execute(stmt)).scalar_one_or_none()
        if c is None:
            raise not_found("Club")
        return c

    async def _require_club_admin(self, c: Club) -> None:
        self.require_writer()
        if self.admin():
            return
        if c.id in await self.advised_club_ids():
            return
        raise forbidden("The club advisor or clubs:manage required")

    async def club_outs(self, rows: list[Club]) -> list[ClubOut]:
        ids = [r.id for r in rows] or [uuid.uuid4()]
        members: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: {"members": 0, "pending": 0})
        for cid, role, n in (
            await self.db.execute(
                select(ClubMember.club_id, ClubMember.role, func.count())
                .where(ClubMember.club_id.in_(ids))
                .group_by(ClubMember.club_id, ClubMember.role)
            )
        ).all():
            members[cid]["pending" if role == "pending" else "members"] += int(n)
        events = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(ClubEvent.club_id, func.count())
                    .where(ClubEvent.club_id.in_(ids))
                    .group_by(ClubEvent.club_id)
                )
            ).all()
        }
        mine: dict[uuid.UUID, str] = {}
        my_ids = await self.my_enrollment_ids()
        if my_ids:
            mine = dict(
                (
                    await self.db.execute(
                        select(ClubMember.club_id, ClubMember.role).where(
                            ClubMember.club_id.in_(ids), ClubMember.student_program_enrollment_id.in_(my_ids)
                        )
                    )
                )
                .tuples()
                .all()
            )
        advised = set(await self.advised_club_ids())
        staff = await self.staff_cards([r.faculty_advisor_id for r in rows])
        return [
            ClubOut(
                id=r.id,
                name=r.name,
                club_type=r.club_type,
                college_id=r.college_id,
                faculty_advisor_id=r.faculty_advisor_id,
                advisor_name=staff.get(r.faculty_advisor_id, {}).get("name") if r.faculty_advisor_id else None,
                description=r.description,
                budget_paise=r.budget_paise,
                is_active=r.is_active,
                members=members[r.id]["members"],
                pending=members[r.id]["pending"],
                events=events.get(r.id, 0),
                my_role=mine.get(r.id),
                is_advisor=r.id in advised,
            )
            for r in rows
        ]

    # ---- clubs ----------------------------------------------------------------------------------------------------------
    async def list_clubs(self, club_type: str | None, mine: bool = False) -> list[ClubOut]:
        stmt = select(Club).where(Club.institution_id == self.inst)
        if club_type:
            stmt = stmt.where(Club.club_type == club_type)
        if mine:
            my_ids = await self.my_enrollment_ids()
            advised = await self.advised_club_ids()
            stmt = stmt.where(
                or_(
                    Club.id.in_(advised or [uuid.uuid4()]),
                    Club.id.in_(
                        select(ClubMember.club_id).where(
                            ClubMember.student_program_enrollment_id.in_(my_ids or [uuid.uuid4()])
                        )
                    ),
                )
            )
        rows = (await self.db.execute(stmt.order_by(Club.name))).scalars().all()
        return await self.club_outs(list(rows))

    async def get_club(self, cid: uuid.UUID) -> ClubOut:
        return (await self.club_outs([await self._club(cid)]))[0]

    async def create_club(self, body: ClubIn) -> ClubOut:
        self.require_writer()
        if not self.admin():
            raise forbidden("clubs:manage required")
        c = Club(institution_id=self.inst, **body.model_dump())
        self.db.add(c)
        try:
            await self.db.flush()
        except IntegrityError:
            raise rule("A club with this name exists", "DUPLICATE_NAME") from None
        await self._audit("create", "club", c.id, None, {"name": c.name, "type": c.club_type})
        return (await self.club_outs([c]))[0]

    async def update_club(self, cid: uuid.UUID, body: ClubIn) -> ClubOut:
        c = await self._club(cid, lock=True)
        await self._require_club_admin(c)
        data = body.model_dump()
        if not self.admin():
            data.pop("faculty_advisor_id", None)
            data.pop("budget_paise", None)
        for k, v in data.items():
            setattr(c, k, v)
        await self.db.flush()
        return (await self.club_outs([c]))[0]

    # ---- members --------------------------------------------------------------------------------------------------------
    async def member_outs(self, rows: list[ClubMember]) -> list[ClubMemberOut]:
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        return [
            ClubMemberOut(
                id=r.id,
                club_id=r.club_id,
                student_program_enrollment_id=r.student_program_enrollment_id,
                student_name=cards.get(r.student_program_enrollment_id, {}).get("name"),
                registration_number=cards.get(r.student_program_enrollment_id, {}).get("registration_number"),
                role=r.role,
                from_on=r.from_on,
                to_on=r.to_on,
            )
            for r in rows
        ]

    async def members(self, cid: uuid.UUID) -> list[ClubMemberOut]:
        c = await self._club(cid)
        stmt = select(ClubMember).where(ClubMember.club_id == c.id)
        if not (self.admin() or self.reader() or c.id in await self.advised_club_ids()):
            stmt = stmt.where(ClubMember.role != "pending")
        rows = (await self.db.execute(stmt.order_by(ClubMember.role, ClubMember.from_on))).scalars().all()
        return await self.member_outs(list(rows))

    async def add_member(self, cid: uuid.UUID, body: ClubMemberIn) -> ClubMemberOut:
        c = await self._club(cid)
        await self._require_club_admin(c)
        await self.enrollment(body.enrollment_id)
        m = ClubMember(
            institution_id=self.inst,
            club_id=c.id,
            student_program_enrollment_id=body.enrollment_id,
            role=body.role,
            from_on=body.from_on or await self.today(),
        )
        self.db.add(m)
        try:
            await self.db.flush()
        except IntegrityError:
            raise rule("The student is already a member", "ALREADY_MEMBER") from None
        await self._joined(c, m)
        return (await self.member_outs([m]))[0]

    async def join(self, cid: uuid.UUID) -> ClubMemberOut:
        self.require_writer()
        c = await self._club(cid)
        if not c.is_active:
            raise rule("The club is not active", "CLUB_INACTIVE")
        e = await self.my_enrollment()
        if e is None:
            raise rule("Your account is not linked to an enrolment", "NO_ENROLMENT")
        m = ClubMember(institution_id=self.inst, club_id=c.id, student_program_enrollment_id=e.id, role="pending")
        self.db.add(m)
        try:
            await self.db.flush()
        except IntegrityError:
            raise rule("You already joined or requested this club", "ALREADY_MEMBER") from None
        await self._notify(
            "clubs.membership",
            [await self.staff_user(c.faculty_advisor_id)],
            {"club": c.name, "status": "join request received"},
        )
        return (await self.member_outs([m]))[0]

    async def _member(self, c: Club, mid: uuid.UUID) -> ClubMember:
        m = (
            await self.db.execute(
                select(ClubMember).where(ClubMember.id == mid, ClubMember.club_id == c.id).with_for_update()
            )
        ).scalar_one_or_none()
        if m is None:
            raise not_found("Member")
        return m

    async def _joined(self, c: Club, m: ClubMember) -> None:
        await self._emit("clubs.member_joined", {"club_id": str(c.id), "member_id": str(m.id)}, "club_member", m.id)
        card = (await self.enrollment_cards([m.student_program_enrollment_id])).get(m.student_program_enrollment_id, {})
        await self._notify(
            "clubs.membership", [card.get("user_id")], {"club": c.name, "status": "you are now a member"}
        )

    async def decide_member(self, cid: uuid.UUID, mid: uuid.UUID, body: ClubMemberDecide) -> ClubMemberOut | None:
        c = await self._club(cid)
        await self._require_club_admin(c)
        m = await self._member(c, mid)
        if m.role != "pending":
            raise rule("Only a pending request is decided", "NOT_PENDING")
        if not body.approve:
            card = (await self.enrollment_cards([m.student_program_enrollment_id])).get(
                m.student_program_enrollment_id, {}
            )
            await self.db.delete(m)
            await self.db.flush()
            await self._notify(
                "clubs.membership", [card.get("user_id")], {"club": c.name, "status": "request declined"}
            )
            return None
        m.role, m.from_on = "member", await self.today()
        await self.db.flush()
        await self._joined(c, m)
        return (await self.member_outs([m]))[0]

    async def set_role(self, cid: uuid.UUID, mid: uuid.UUID, body: ClubMemberRole) -> ClubMemberOut:
        c = await self._club(cid)
        await self._require_club_admin(c)
        m = await self._member(c, mid)
        if m.role == "pending":
            raise rule("Approve the request first", "PENDING")
        m.role = body.role
        if body.from_on:
            m.from_on = body.from_on
        m.to_on = body.to_on
        await self.db.flush()
        return (await self.member_outs([m]))[0]

    # ---- events ---------------------------------------------------------------------------------------------------------
    async def event_outs(self, rows: list[ClubEvent]) -> list[ClubEventOut]:
        titles = {
            e.id: e.title
            for e in (
                await self.db.execute(
                    select(Event).where(Event.id.in_([r.event_id for r in rows if r.event_id] or [uuid.uuid4()]))
                )
            ).scalars()
        }
        return [
            ClubEventOut(
                id=r.id,
                club_id=r.club_id,
                title=r.title,
                held_on=r.held_on,
                venue=r.venue,
                participants_count=r.participants_count,
                budget_paise=r.budget_paise,
                report_url=r.report_url,
                images=list(r.images or []),
                event_id=r.event_id,
                event_title=titles.get(r.event_id) if r.event_id else None,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def events(self, cid: uuid.UUID) -> list[ClubEventOut]:
        c = await self._club(cid)
        rows = (
            (
                await self.db.execute(
                    select(ClubEvent).where(ClubEvent.club_id == c.id).order_by(ClubEvent.held_on.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.event_outs(list(rows))

    async def add_event(self, cid: uuid.UUID, body: ClubEventIn) -> ClubEventOut:
        c = await self._club(cid)
        await self._require_club_admin(c)
        ev = None
        if body.event_id:
            ev = (
                await self.db.execute(select(Event).where(Event.id == body.event_id, Event.institution_id == self.inst))
            ).scalar_one_or_none()
            if ev is None:
                raise not_found("Event")
        row = ClubEvent(
            institution_id=self.inst,
            club_id=c.id,
            title=body.title,
            held_on=body.held_on or (ev.from_on if ev else None),
            venue=body.venue or (ev.venue_text if ev else None),
            participants_count=body.participants_count
            if body.participants_count is not None
            else (ev.participants_count if ev else None),
            budget_paise=body.budget_paise,
            report_url=body.report_url or (ev.report_url if ev else None),
            images=body.images or (list(ev.images or []) if ev else None),
            event_id=body.event_id,
        )
        self.db.add(row)
        await self.db.flush()
        await self._emit(
            "clubs.event_recorded",
            {
                "club_id": str(c.id),
                "club_event_id": str(row.id),
                "event_id": str(body.event_id) if body.event_id else None,
            },
            "club_event",
            row.id,
        )
        if body.log_hours and row.held_on:
            act = CLUB_ACTIVITY.get(c.club_type, "club")
            for (eid,) in (
                await self.db.execute(
                    select(ClubMember.student_program_enrollment_id).where(
                        ClubMember.club_id == c.id, ClubMember.role != "pending"
                    )
                )
            ).all():
                h = ActivityHour(
                    institution_id=self.inst,
                    student_program_enrollment_id=eid,
                    activity_type=act,
                    hours=Decimal(str(body.log_hours)),
                    on_date=row.held_on,
                    description=f"{c.name}: {body.title}"[:200],
                )
                self.db.add(h)
                await self.db.flush()
                await self.put_meta("hours", h.id, {"club_id": str(c.id), "club_event_id": str(row.id)})
        return (await self.event_outs([row]))[0]

    # ---- activity hours -------------------------------------------------------------------------------------------------
    async def hour_outs(self, rows: list[ActivityHour]) -> list[ActHourOut]:
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        return [
            ActHourOut(
                id=r.id,
                student_program_enrollment_id=r.student_program_enrollment_id,
                student_name=cards.get(r.student_program_enrollment_id, {}).get("name"),
                activity_type=r.activity_type,
                hours=float(r.hours),
                on_date=r.on_date,
                description=r.description,
                evidence_url=r.evidence_url,
                status="pending" if r.verified_at is None else ("rejected" if float(r.hours) == 0 else "verified"),
                verified_by=r.verified_by,
                verified_at=r.verified_at,
                credits_course_id=r.credits_course_id,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def log_hours(self, body: ActHourCreate) -> ActHourOut:
        self.require_writer()
        if body.enrollment_id is not None:
            if not (self.officer() or self.admin() or (body.club_id and body.club_id in await self.advised_club_ids())):
                raise forbidden("Officers log hours for students")
            eid = body.enrollment_id
            await self.enrollment(eid)
        else:
            e = await self.my_enrollment()
            if e is None:
                raise rule("Your account is not linked to an enrolment", "NO_ENROLMENT")
            eid = e.id
        if body.club_id:
            c = await self._club(body.club_id)
            member = (
                await self.db.execute(
                    select(func.count())
                    .select_from(ClubMember)
                    .where(
                        ClubMember.club_id == c.id,
                        ClubMember.student_program_enrollment_id == eid,
                        ClubMember.role != "pending",
                    )
                )
            ).scalar_one()
            if not member:
                raise rule("Hours against a club need membership", "NOT_MEMBER")
        h = ActivityHour(
            institution_id=self.inst,
            student_program_enrollment_id=eid,
            activity_type=body.activity_type,
            hours=Decimal(str(body.hours)),
            on_date=body.on_date,
            description=body.description,
            evidence_url=body.evidence_url,
        )
        self.db.add(h)
        await self.db.flush()
        if body.club_id:
            await self.put_meta("hours", h.id, {"club_id": str(body.club_id)})
        await self._emit(
            "activity.hours_logged", {"activity_hour_id": str(h.id), "type": h.activity_type}, "activity_hour", h.id
        )
        return (await self.hour_outs([h]))[0]

    async def bulk(self, body: ActHourBulk) -> ActVerifyResult:
        self.require_writer()
        if not (self.officer() or self.admin()):
            raise forbidden("clubs:verify_hours required")
        ok = skipped = 0
        valid = {
            r[0]
            for r in (
                await self.db.execute(
                    select(StudentProgramEnrollment.id).where(
                        StudentProgramEnrollment.id.in_(
                            [r.enrollment_id for r in body.rows if r.enrollment_id] or [uuid.uuid4()]
                        )
                    )
                )
            ).all()
        }
        for r in body.rows:
            if r.enrollment_id not in valid:
                skipped += 1
                continue
            self.db.add(
                ActivityHour(
                    institution_id=self.inst,
                    student_program_enrollment_id=r.enrollment_id,
                    activity_type=r.activity_type,
                    hours=Decimal(str(r.hours)),
                    on_date=r.on_date,
                    description=r.description,
                    evidence_url=r.evidence_url,
                    verified_by=self.actor_id if body.auto_verify else None,
                    verified_at=now_utc() if body.auto_verify else None,
                )
            )
            ok += 1
        await self.db.flush()
        eligible = await self._credit_check(list(valid)) if body.auto_verify else 0
        await self._audit("bulk", "activity_hour", None, None, {"rows": ok, "skipped": skipped})
        return ActVerifyResult(
            verified=ok if body.auto_verify else 0, rejected=0, skipped=skipped, credit_eligible=eligible
        )

    async def verify(self, body: ActVerify) -> ActVerifyResult:
        self.require_writer()
        rows = (
            (
                await self.db.execute(
                    select(ActivityHour)
                    .where(ActivityHour.id.in_(body.ids), ActivityHour.institution_id == self.inst)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        officer = self.officer() or self.admin()
        advised = set(await self.advised_club_ids()) if not officer else set()
        metas = await self.metas("hours", [r.id for r in rows]) if not officer else {}
        if not officer:
            for r in rows:
                club = metas.get(str(r.id), {}).get("club_id")
                if r.activity_type not in ("club",) or not club or uuid.UUID(club) not in advised:
                    raise forbidden(
                        "Club advisors verify only club hours of their own clubs (clubs:verify_hours for others)"
                    )
        v = rej = skipped = 0
        touched: set[uuid.UUID] = set()
        for r in rows:
            if r.verified_at is not None:
                skipped += 1
                continue
            r.verified_by, r.verified_at = self.actor_id, now_utc()
            if body.approve:
                v += 1
                touched.add(r.student_program_enrollment_id)
                await self._emit("activity.hours_verified", {"activity_hour_id": str(r.id)}, "activity_hour", r.id)
            else:
                rej += 1
                r.hours = Decimal("0")
                r.description = f"[rejected] {body.remarks or ''} {r.description or ''}".strip()[:200]
        await self.db.flush()
        for eid in touched:
            card = (await self.enrollment_cards([eid])).get(eid, {})
            await self._notify("clubs.verified_hours", [card.get("user_id")], {"status": "verified"})
        eligible = await self._credit_check(list(touched))
        return ActVerifyResult(verified=v, rejected=rej, skipped=skipped, credit_eligible=eligible)

    async def _mapping(self) -> list[dict[str, Any]]:
        m = await self.setting("clubs", "hours_to_credits")
        return [x for x in (m if isinstance(m, list) else []) if isinstance(x, dict) and x.get("course_id")]

    async def _credit_check(self, eids: list[uuid.UUID]) -> int:
        if not eids or not await self.feature("clubs.activity_hours_credits"):
            return 0
        n = 0
        for mp in await self._mapping():
            course_id = uuid.UUID(str(mp["course_id"]))
            types = mp.get("activity_types")
            need = float(mp.get("min_hours") or 0)
            for eid in eids:
                stmt = select(ActivityHour).where(
                    ActivityHour.student_program_enrollment_id == eid,
                    ActivityHour.verified_at.is_not(None),
                    ActivityHour.hours > 0,
                )
                if types:
                    stmt = stmt.where(ActivityHour.activity_type.in_(types))
                rows = (await self.db.execute(stmt)).scalars().all()
                if any(r.credits_course_id == course_id for r in rows):
                    continue
                total = sum(float(r.hours) for r in rows if r.credits_course_id is None)
                if need and total >= need:
                    for r in rows:
                        if r.credits_course_id is None:
                            r.credits_course_id = course_id
                    await self.db.flush()
                    await self._emit(
                        "activity.credit_eligible",
                        {
                            "enrollment_id": str(eid),
                            "course_id": str(course_id),
                            "verified_hours": total,
                            "result_status": "pass",
                            "counts_toward_cgpa": False,
                        },
                        "student_program_enrollment",
                        eid,
                    )
                    n += 1
        return n

    async def my_hours(self) -> list[ActHourOut]:
        ids = await self.my_enrollment_ids() or await self.ward_enrollment_ids()
        rows = (
            (
                await self.db.execute(
                    select(ActivityHour)
                    .where(ActivityHour.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                    .order_by(ActivityHour.on_date.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.hour_outs(list(rows))

    async def list_hours(self, status: str | None, activity_type: str | None) -> list[ActHourOut]:
        stmt = select(ActivityHour).where(ActivityHour.institution_id == self.inst)
        if not (self.officer() or all_access(self.principal, self.module) or self.admin()):
            advised = await self.advised_club_ids()
            if not advised:
                raise forbidden("clubs:verify_hours required")
            keys = [k for k, v in (await self.metas("hours")).items() if v.get("club_id") in {str(a) for a in advised}]
            stmt = stmt.where(ActivityHour.id.in_([uuid.UUID(k) for k in keys] or [uuid.uuid4()]))
        if status == "pending":
            stmt = stmt.where(ActivityHour.verified_at.is_(None))
        elif status == "verified":
            stmt = stmt.where(ActivityHour.verified_at.is_not(None), ActivityHour.hours > 0)
        if activity_type:
            stmt = stmt.where(ActivityHour.activity_type == activity_type)
        rows = (await self.db.execute(stmt.order_by(ActivityHour.created_at.desc()).limit(1000))).scalars().all()
        return await self.hour_outs(list(rows))

    async def ledger(self, eid: uuid.UUID | None) -> ActLedger:
        if eid is None:
            e = await self.my_enrollment()
            if e is None:
                raise rule("Pass enrollment_id", "NO_ENROLMENT")
            eid = e.id
        elif eid not in await self.my_enrollment_ids() and eid not in await self.ward_enrollment_ids():
            if not (self.officer() or self.reader() or self.admin()):
                raise not_found("Ledger")
        rows = list(
            (
                await self.db.execute(
                    select(ActivityHour)
                    .where(ActivityHour.student_program_enrollment_id == eid)
                    .order_by(ActivityHour.on_date.desc())
                )
            )
            .scalars()
            .all()
        )
        by_type: dict[str, float] = defaultdict(float)
        verified = pending = 0.0
        for r in rows:
            h = float(r.hours)
            by_type[r.activity_type] += h
            if r.verified_at is None:
                pending += h
            else:
                verified += h
        credits: list[dict[str, Any]] = []
        for mp in await self._mapping():
            types = mp.get("activity_types")
            got = sum(
                float(r.hours) for r in rows if r.verified_at is not None and (not types or r.activity_type in types)
            )
            credits.append(
                {
                    "course_id": str(mp["course_id"]),
                    "min_hours": float(mp.get("min_hours") or 0),
                    "verified_hours": got,
                    "eligible": got >= float(mp.get("min_hours") or 0),
                    "mapped": any(str(r.credits_course_id) == str(mp["course_id"]) for r in rows),
                }
            )
        cs_target = 0.0
        for c in (
            await self.db.execute(
                select(DisciplinaryCase).where(
                    DisciplinaryCase.subject_type == "student", DisciplinaryCase.subject_id == eid
                )
            )
        ).scalars():
            for s in c.sanctions or []:
                if s.get("type") == "community_service":
                    cs_target += float(s.get("hours") or 20)
        if cs_target:
            credits.append(
                {
                    "kind": "community_service_sanction",
                    "target_hours": cs_target,
                    "verified_hours": by_type.get("community_service", 0.0),
                }
            )
        return ActLedger(
            enrollment_id=eid,
            by_type=dict(by_type),
            total=sum(by_type.values()),
            verified=verified,
            pending=pending,
            credits_eligible=credits,
            entries=await self.hour_outs(rows[:200]),
        )

    async def credit_eligible(self, term_id: uuid.UUID | None) -> list[ActCreditEligible]:
        await self.require_feature("clubs.activity_hours_credits")
        if not (self.officer() or self.reader() or self.admin()):
            raise forbidden("clubs:verify_hours required")
        out: list[ActCreditEligible] = []
        for mp in await self._mapping():
            course_id = uuid.UUID(str(mp["course_id"]))
            need = float(mp.get("min_hours") or 0)
            types = mp.get("activity_types")
            stmt = (
                select(
                    ActivityHour.student_program_enrollment_id,
                    func.sum(ActivityHour.hours),
                    func.count(ActivityHour.credits_course_id),
                )
                .where(
                    ActivityHour.institution_id == self.inst,
                    ActivityHour.verified_at.is_not(None),
                    ActivityHour.hours > 0,
                )
                .group_by(ActivityHour.student_program_enrollment_id)
            )
            if types:
                stmt = stmt.where(ActivityHour.activity_type.in_(types))
            rows = [
                (e, float(h or 0), int(m)) for e, h, m in (await self.db.execute(stmt)).all() if float(h or 0) >= need
            ]
            cards = await self.enrollment_cards([e for e, _, _ in rows])
            code = (await self.db.execute(select(Course.code).where(Course.id == course_id))).scalar_one_or_none()
            out += [
                ActCreditEligible(
                    enrollment_id=e,
                    student_name=cards.get(e, {}).get("name"),
                    course_id=course_id,
                    course_code=code,
                    verified_hours=h,
                    min_hours=need,
                    mapped=m > 0,
                )
                for e, h, m in rows
            ]
        return out

    # ---- achievements ---------------------------------------------------------------------------------------------------
    async def ach_outs(self, rows: list[StudentAchievement]) -> list[AchOut]:
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        return [
            AchOut(
                id=r.id,
                student_program_enrollment_id=r.student_program_enrollment_id,
                student_name=cards.get(r.student_program_enrollment_id, {}).get("name"),
                department_id=cards.get(r.student_program_enrollment_id, {}).get("department_id"),
                category=r.category,
                title=r.title,
                level=r.level,
                position=r.position,
                held_on=r.held_on,
                evidence_url=r.evidence_url,
                verified=r.verified_at is not None,
                verified_at=r.verified_at,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def submit_achievement(self, body: AchCreate) -> AchOut:
        self.require_writer()
        if body.enrollment_id is not None and not (self.officer() or self.admin()):
            raise forbidden("Officers record achievements for students")
        eid = body.enrollment_id
        if eid is None:
            e = await self.my_enrollment()
            if e is None:
                raise rule("Your account is not linked to an enrolment", "NO_ENROLMENT")
            eid = e.id
        a = StudentAchievement(
            institution_id=self.inst,
            student_program_enrollment_id=eid,
            category=body.category,
            title=body.title,
            level=body.level,
            position=body.position,
            held_on=body.held_on,
            evidence_url=body.evidence_url,
        )
        self.db.add(a)
        await self.db.flush()
        await self._emit("achievement.submitted", {"achievement_id": str(a.id)}, "student_achievement", a.id)
        return (await self.ach_outs([a]))[0]

    async def verify_achievement(self, aid: uuid.UUID, body: AchVerify) -> AchOut:
        self.require_writer()
        a = (
            await self.db.execute(
                select(StudentAchievement)
                .where(StudentAchievement.id == aid, StudentAchievement.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Achievement")
        if not (self.officer() or self.admin()):
            advised = await self.advised_club_ids()
            member = (
                await self.db.execute(
                    select(func.count())
                    .select_from(ClubMember)
                    .where(
                        ClubMember.club_id.in_(advised or [uuid.uuid4()]),
                        ClubMember.student_program_enrollment_id == a.student_program_enrollment_id,
                    )
                )
            ).scalar_one()
            if not member:
                raise forbidden("clubs:verify_hours or the student's club advisor required")
        if a.verified_at is not None:
            raise rule("Already verified", "ALREADY_VERIFIED")
        if not body.approve:
            await self.db.delete(a)
            await self.db.flush()
            raise rule("Achievement rejected and removed", "REJECTED", status=200)
        a.verified_by, a.verified_at = self.actor_id, now_utc()
        await self.db.flush()
        await self._emit(
            "achievement.verified",
            {
                "achievement_id": str(a.id),
                "enrollment_id": str(a.student_program_enrollment_id),
                "category": a.category,
                "level": a.level,
            },
            "student_achievement",
            a.id,
        )
        card = (await self.enrollment_cards([a.student_program_enrollment_id])).get(a.student_program_enrollment_id, {})
        await self._notify("clubs.achievement_verified", [card.get("user_id")], {"title": a.title})
        return (await self.ach_outs([a]))[0]

    async def my_achievements(self) -> list[AchOut]:
        ids = await self.my_enrollment_ids() or await self.ward_enrollment_ids()
        rows = (
            (
                await self.db.execute(
                    select(StudentAchievement)
                    .where(StudentAchievement.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                    .order_by(StudentAchievement.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.ach_outs(list(rows))

    async def list_achievements(
        self,
        category: str | None,
        level: str | None,
        verified: bool | None,
        department_id: uuid.UUID | None,
        scope: str | None = None,
    ) -> list[AchOut]:
        stmt = select(StudentAchievement).where(StudentAchievement.institution_id == self.inst)
        if not (scope in (None, "all") and (all_access(self.principal, self.module) or self.officer())):
            parts = self.enrolment_dept_predicate(StudentAchievement.student_program_enrollment_id, scope)
            advised = await self.advised_club_ids()
            if advised:
                parts.append(
                    StudentAchievement.student_program_enrollment_id.in_(
                        select(ClubMember.student_program_enrollment_id).where(ClubMember.club_id.in_(advised))
                    )
                )
            stmt = stmt.where(or_(*parts) if parts else true().is_(False))
        if category:
            stmt = stmt.where(StudentAchievement.category == category)
        if level:
            stmt = stmt.where(StudentAchievement.level == level)
        if verified is not None:
            stmt = stmt.where(
                StudentAchievement.verified_at.is_not(None) if verified else StudentAchievement.verified_at.is_(None)
            )
        if department_id:
            stmt = stmt.where(
                StudentAchievement.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.department_id == department_id)
                )
            )
        rows = (await self.db.execute(stmt.order_by(StudentAchievement.created_at.desc()).limit(1000))).scalars().all()
        return await self.ach_outs(list(rows))

    async def stats(self) -> dict[str, Any]:
        clubs = int(
            (
                await self.db.execute(select(func.count()).select_from(Club).where(Club.institution_id == self.inst))
            ).scalar_one()
            or 0
        )
        members = int(
            (
                await self.db.execute(
                    select(func.count(func.distinct(ClubMember.student_program_enrollment_id))).where(
                        ClubMember.institution_id == self.inst, ClubMember.role != "pending"
                    )
                )
            ).scalar_one()
            or 0
        )
        hours = (
            await self.db.execute(
                select(func.coalesce(func.sum(ActivityHour.hours), 0), func.count()).where(
                    ActivityHour.institution_id == self.inst, ActivityHour.verified_at.is_not(None)
                )
            )
        ).one()
        ach = {
            ("verified" if v else "pending"): int(n)
            for v, n in (
                await self.db.execute(
                    select(StudentAchievement.verified_at.is_not(None), func.count())
                    .where(StudentAchievement.institution_id == self.inst)
                    .group_by(StudentAchievement.verified_at.is_not(None))
                )
            ).all()
        }
        return {
            "clubs": clubs,
            "participants": members,
            "verified_hours": float(hours[0] or 0),
            "verified_entries": int(hours[1] or 0),
            "achievements": ach,
        }
