"""Sports — Prompts/25 §25.6 ``sports_service`` ({facilities.sports}).

Teams (sport, level, coach, members = enrolment ids), sports events (institution … international; optionally linked
to an ``events`` row for budget / venue — ``create_event`` makes one in ``proposed``), participation with result /
position / evidence; verification (``sports:manage``) posts a verified ``student_achievements`` row (category
``sports``) and emits ``sports.participation_verified`` for activity hours / NAAC 5.3.1 / NIRF counts. Visibility:
participants see their own rows, coaches their teams, ``sports:view_all`` / ``manage`` everything.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, or_, select

from app.models.events import Event
from app.models.facilities import SportsEvent, SportsParticipation, SportsTeam
from app.models.hr import Staff
from app.models.post_result import StudentAchievement
from app.models.students import Student, StudentProgramEnrollment
from app.schemas.facilities import (
    SportsEventIn,
    SportsEventOut,
    SportsParticipationIn,
    SportsParticipationOut,
    SportsTeamIn,
    SportsTeamOut,
)
from app.services.facilities.common import FacilitiesBase, forbidden, not_found, now_utc, rule


class SportsService(FacilitiesBase):
    audit_module = "sports"
    module = "sports"

    def manager(self) -> bool:
        return self.can("sports", "manage")

    def reader_all(self) -> bool:
        return self.manager() or self.can("sports", "view_all")

    # ---- teams --------------------------------------------------------------------------------------------------------
    async def team_outs(self, rows: Sequence[SportsTeam]) -> list[SportsTeamOut]:
        coaches = {
            s.id: " ".join(x for x in (s.first_name, s.last_name) if x)
            for s in (
                await self.db.execute(
                    select(Staff).where(
                        Staff.id.in_([t.coach_staff_id for t in rows if t.coach_staff_id] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        out = []
        for t in rows:
            o = SportsTeamOut.model_validate(t)
            o.coach_name = coaches.get(t.coach_staff_id) if t.coach_staff_id else None
            out.append(o)
        return out

    async def teams(self) -> list[SportsTeamOut]:
        stmt = select(SportsTeam).where(SportsTeam.institution_id == self.inst)
        if not self.reader_all():
            sid = await self.my_staff_id()
            stmt = stmt.where(SportsTeam.coach_staff_id == (sid or uuid.uuid4()))
        rows = (await self.db.execute(stmt.order_by(SportsTeam.sport, SportsTeam.name))).scalars().all()
        return await self.team_outs(rows)

    async def save_team(self, body: SportsTeamIn, tid: uuid.UUID | None = None) -> SportsTeamOut:
        if not self.manager():
            sid = await self.my_staff_id()
            if tid is None or sid is None:
                raise forbidden("sports:manage required")
        data = body.model_dump()
        data["members"] = [str(m) for m in body.members]
        if tid is None:
            t: SportsTeam | None = SportsTeam(institution_id=self.inst, **data)
            self.db.add(t)
        else:
            t = (
                await self.db.execute(
                    select(SportsTeam).where(SportsTeam.id == tid, SportsTeam.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if t is None:
                raise not_found("Team")
            if not self.manager() and t.coach_staff_id != await self.my_staff_id():
                raise forbidden("Coaches edit their own teams")
            if not self.manager():
                data = {"members": data["members"], "name": data["name"]}
            for k, v in data.items():
                setattr(t, k, v)
        assert t is not None
        await self.db.flush()
        await self._audit("update" if tid else "create", "sports_team", t.id, None, {"sport": t.sport})
        if tid is None:
            for eid in body.members:
                uid = (
                    await self.db.execute(
                        select(Student.user_id)
                        .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                        .where(StudentProgramEnrollment.id == eid)
                    )
                ).scalar_one_or_none()
                await self._notify("sports.selected", [uid], {"event": t.name or t.sport, "sport": t.sport})
        return (await self.team_outs([t]))[0]

    # ---- events ---------------------------------------------------------------------------------------------------------
    async def events(self) -> list[SportsEventOut]:
        rows = (
            (
                await self.db.execute(
                    select(SportsEvent)
                    .where(SportsEvent.institution_id == self.inst)
                    .order_by(SportsEvent.from_on.desc())
                    .limit(300)
                )
            )
            .scalars()
            .all()
        )
        counts = {
            e: int(n)
            for e, n in (
                await self.db.execute(
                    select(SportsParticipation.sports_event_id, func.count())
                    .where(SportsParticipation.sports_event_id.in_([r.id for r in rows] or [uuid.uuid4()]))
                    .group_by(SportsParticipation.sports_event_id)
                )
            ).all()
        }
        out = []
        for r in rows:
            o = SportsEventOut.model_validate(r)
            o.participants = counts.get(r.id, 0)
            out.append(o)
        return out

    async def create_event(self, body: SportsEventIn) -> SportsEventOut:
        if not self.manager():
            raise forbidden("sports:manage required")
        event_id = body.event_id
        if body.create_event and event_id is None:
            staff = await self.my_staff()
            ev = Event(
                institution_id=self.inst,
                college_id=staff.college_id if staff else None,
                event_type="sports",
                title=body.title,
                organiser_department_id=staff.department_id if staff else None,
                organiser_staff_id=staff.id if staff else None,
                from_on=body.from_on,
                to_on=body.to_on or body.from_on,
                venue_text=body.venue,
                naac_criterion="5.3",
                status="proposed",
                created_by=self.actor_id,
            )
            self.db.add(ev)
            await self.db.flush()
            event_id = ev.id
        r = SportsEvent(
            institution_id=self.inst,
            title=body.title,
            sport=body.sport,
            level=body.level,
            from_on=body.from_on,
            to_on=body.to_on,
            venue=body.venue,
            organiser=body.organiser,
            event_id=event_id,
        )
        self.db.add(r)
        await self.db.flush()
        await self._audit("create", "sports_event", r.id, None, {"title": r.title, "level": r.level})
        return SportsEventOut.model_validate(r)

    # ---- participation -----------------------------------------------------------------------------------------------
    async def part_outs(self, rows: Sequence[SportsParticipation]) -> list[SportsParticipationOut]:
        titles = {
            e.id: e.title
            for e in (
                await self.db.execute(
                    select(SportsEvent).where(SportsEvent.id.in_([r.sports_event_id for r in rows] or [uuid.uuid4()]))
                )
            ).scalars()
        }
        names: dict[uuid.UUID, str] = {}
        for eid, st in (
            await self.db.execute(
                select(StudentProgramEnrollment.id, Student)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .where(
                    StudentProgramEnrollment.id.in_([r.student_program_enrollment_id for r in rows] or [uuid.uuid4()])
                )
            )
        ).all():
            names[eid] = st.full_name
        out = []
        for r in rows:
            o = SportsParticipationOut.model_validate(r)
            o.event_title = titles.get(r.sports_event_id)
            o.student_name = names.get(r.student_program_enrollment_id)
            out.append(o)
        return out

    async def add_participation(self, body: SportsParticipationIn) -> list[SportsParticipationOut]:
        sid = await self.my_staff_id()
        team = None
        if body.team_id:
            team = (
                await self.db.execute(
                    select(SportsTeam).where(SportsTeam.id == body.team_id, SportsTeam.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if team is None:
                raise not_found("Team")
        if not self.manager() and not (team and sid and team.coach_staff_id == sid):
            raise forbidden("sports:manage or the team's coach required")
        ev = (
            await self.db.execute(
                select(SportsEvent).where(SportsEvent.id == body.event_id, SportsEvent.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if ev is None:
            raise not_found("Sports event")
        rows = []
        for eid in body.enrollment_ids:
            dup = (
                await self.db.execute(
                    select(SportsParticipation).where(
                        SportsParticipation.sports_event_id == ev.id,
                        SportsParticipation.student_program_enrollment_id == eid,
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                dup.result, dup.position = body.result or dup.result, body.position or dup.position
                dup.evidence_url = body.evidence_url or dup.evidence_url
                rows.append(dup)
                continue
            r = SportsParticipation(
                institution_id=self.inst,
                sports_event_id=ev.id,
                student_program_enrollment_id=eid,
                team_id=body.team_id,
                result=body.result,
                position=body.position,
                evidence_url=body.evidence_url,
            )
            self.db.add(r)
            rows.append(r)
        await self.db.flush()
        await self._audit("participation", "sports_event", ev.id, None, {"count": len(rows)})
        return await self.part_outs(rows)

    async def verify(self, pid: uuid.UUID) -> SportsParticipationOut:
        if not self.manager():
            raise forbidden("sports:manage required")
        r = (
            await self.db.execute(
                select(SportsParticipation)
                .where(SportsParticipation.id == pid, SportsParticipation.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Participation")
        if r.verified_by:
            raise rule("Already verified", "ALREADY_VERIFIED")
        if not r.evidence_url:
            raise rule("Upload the evidence before verifying", "EVIDENCE_REQUIRED")
        ev = (await self.db.execute(select(SportsEvent).where(SportsEvent.id == r.sports_event_id))).scalar_one()
        r.verified_by = self.actor_id
        self.db.add(
            StudentAchievement(
                institution_id=self.inst,
                student_program_enrollment_id=r.student_program_enrollment_id,
                category="sports",
                title=f"{ev.title}{' — ' + r.position if r.position else ''}"[:200],
                level=ev.level[:20],
                position=r.position,
                held_on=ev.from_on,
                evidence_url=r.evidence_url,
                verified_by=self.actor_id,
                verified_at=now_utc(),
            )
        )
        await self.db.flush()
        await self._audit("verify", "sports_participation", r.id, None, {"event": ev.title})
        await self._emit(
            "sports.participation_verified",
            {
                "participation_id": str(r.id),
                "enrollment_id": str(r.student_program_enrollment_id),
                "level": ev.level,
                "position": r.position,
            },
            "sports_participation",
            r.id,
        )
        return (await self.part_outs([r]))[0]

    async def participation(self, event_id: uuid.UUID | None = None) -> list[SportsParticipationOut]:
        stmt = select(SportsParticipation).where(SportsParticipation.institution_id == self.inst)
        if event_id:
            stmt = stmt.where(SportsParticipation.sports_event_id == event_id)
        if not self.reader_all():
            sid = await self.my_staff_id()
            stmt = stmt.where(
                SportsParticipation.team_id.in_(
                    select(SportsTeam.id).where(SportsTeam.coach_staff_id == (sid or uuid.uuid4()))
                )
            )
        rows = (await self.db.execute(stmt.order_by(SportsParticipation.created_at.desc()).limit(500))).scalars().all()
        return await self.part_outs(rows)

    async def mine(self) -> dict[str, Any]:
        st = await self.my_student()
        sid = await self.my_staff_id()
        out: dict[str, Any] = {"participation": [], "teams": []}
        if st is not None:
            enrol_ids = list(
                (
                    await self.db.execute(
                        select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.student_id == st.id)
                    )
                ).scalars()
            )
            rows = (
                (
                    await self.db.execute(
                        select(SportsParticipation).where(
                            SportsParticipation.student_program_enrollment_id.in_(enrol_ids or [uuid.uuid4()])
                        )
                    )
                )
                .scalars()
                .all()
            )
            out["participation"] = [o.model_dump(mode="json") for o in await self.part_outs(rows)]
            teams = (
                (
                    await self.db.execute(
                        select(SportsTeam).where(
                            SportsTeam.institution_id == self.inst,
                            (
                                or_(*[SportsTeam.members.contains([str(e)]) for e in enrol_ids])
                                if enrol_ids
                                else SportsTeam.id.is_(None)
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            out["teams"] = [o.model_dump(mode="json") for o in await self.team_outs(teams)]
        if sid is not None:
            coached = (
                (await self.db.execute(select(SportsTeam).where(SportsTeam.coach_staff_id == sid))).scalars().all()
            )
            out["coached_teams"] = [o.model_dump(mode="json") for o in await self.team_outs(coached)]
        return out
