"""Patents, FDP and awards — Prompts/30 §30.6 ``patent_service`` ({research.patents}), ``fdp_service`` ({research.fdp})
and ``award_service``.

* Patents move forward only: filed → published → granted → commercialised (each transition stamps its date when not
  given; a backwards move → 409 ``INVALID_TRANSITION``); co-inventors are tagged like publication authors; renewal
  reminders every ``research.patent_renewal_months`` after the grant (monthly Beat). NAAC 3.4.x counts.
* FDP records per staff (attended / organised / resource person, hours, certificate). Phase 25 events of type
  fdp / workshop / conference create ``attended`` rows for the staff registered (and marked attended) when the event
  completes (``events.completed`` consumer) and an ``organised`` row for the organiser; annual compliance against
  ``research.fdp_hours_target`` feeds Phase 06 PBAS auto-fill (``appraisal_service`` reads ``faculty_developments``).
* Awards with level and evidence; research cell verification (side store); feed NAAC 3.x / 6.x and the profile.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import extract, func, select

from app.enums.research import PATENT_ORDER
from app.models.hr import Staff
from app.models.research import FacultyAward, FacultyDevelopment, Patent
from app.schemas.research import (
    AwardIn,
    AwardOut,
    FdpComplianceRow,
    FdpIn,
    FdpOut,
    FdpUpdate,
    PatentIn,
    PatentOut,
    PatentUpdate,
)
from app.services.research.common import ResearchBase, forbidden, not_found, rule, staff_name

DATE_FIELD = {"published": "published_on", "granted": "granted_on"}


class RecordService(ResearchBase):
    async def _owner(self, staff_id: uuid.UUID | None) -> uuid.UUID:
        if staff_id is not None and self.cell():
            return (await self.staff_row(staff_id)).id
        return (await self.require_my_staff()).id

    async def _can_write(self, staff_id: uuid.UUID | None, tags: list[dict[str, Any]] | None = None) -> None:
        self.require_writer()
        if not self.cell() and not await self.is_mine(staff_id, tags):
            raise forbidden("Only the owner or the research cell changes this record")

    # ---- patents --------------------------------------------------------------------------------------------------------
    async def patent_outs(self, rows: list[Patent]) -> list[PatentOut]:
        staff = await self.staff_map([r.staff_id for r in rows])
        metas = await self.metas("patent", [r.id for r in rows]) if rows else {}
        return [
            PatentOut(
                id=r.id,
                staff_id=r.staff_id,
                staff_name=staff_name(staff.get(r.staff_id)) if r.staff_id else None,
                title=r.title,
                application_no=r.application_no,
                country=r.country,
                filed_on=r.filed_on,
                published_on=r.published_on,
                granted_on=r.granted_on,
                status=r.status,
                co_inventors=list(r.co_inventors or []),
                evidence_url=r.evidence_url,
                history=list(metas.get(str(r.id), {}).get("timeline") or []),
            )
            for r in rows
        ]

    async def patents(
        self, *, status: str | None = None, staff_id: uuid.UUID | None = None, scope: str | None = None
    ) -> list[PatentOut]:
        stmt = select(Patent).where(
            Patent.institution_id == self.inst,
            await self.owned_predicate(Patent.staff_id, scope=scope, json_col=Patent.co_inventors),
        )
        if status:
            stmt = stmt.where(Patent.status == status)
        if staff_id:
            stmt = stmt.where(Patent.staff_id == staff_id)
        return await self.patent_outs(list((await self.db.execute(stmt.order_by(Patent.filed_on.desc()))).scalars()))

    async def patent_row(self, pid: uuid.UUID, *, lock: bool = False) -> Patent:
        stmt = select(Patent).where(
            Patent.id == pid,
            Patent.institution_id == self.inst,
            await self.owned_predicate(Patent.staff_id, json_col=Patent.co_inventors),
        )
        p = (await self.db.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
        if p is None:
            raise not_found("Patent")
        return p

    async def create_patent(self, body: PatentIn) -> PatentOut:
        self.require_writer()
        owner = await self._owner(body.staff_id)
        p = Patent(
            institution_id=self.inst,
            staff_id=owner,
            title=body.title,
            application_no=body.application_no,
            country=body.country,
            filed_on=body.filed_on or await self.today(),
            published_on=body.published_on,
            granted_on=body.granted_on,
            status=body.status.value,
            co_inventors=[c.model_dump(mode="json") for c in body.co_inventors],
            evidence_url=body.evidence_url,
        )
        self.db.add(p)
        await self.db.flush()
        await self.timeline("patent", p.id, p.status)
        await self._audit("create", "patent", p.id, None, {"title": p.title, "status": p.status})
        await self._emit("research.patent_updated", {"patent_id": str(p.id), "status": p.status}, "patent", p.id)
        return (await self.patent_outs([p]))[0]

    async def update_patent(self, pid: uuid.UUID, body: PatentUpdate) -> PatentOut:
        p = await self.patent_row(pid, lock=True)
        await self._can_write(p.staff_id, p.co_inventors)
        data = body.model_dump(exclude_unset=True, mode="json")
        new_status = data.pop("status", None)
        if "co_inventors" in data and data["co_inventors"] is None:
            data.pop("co_inventors")
        for k, v in data.items():
            setattr(p, k, date.fromisoformat(v) if k.endswith("_on") and isinstance(v, str) else v)
        if new_status and new_status != p.status:
            if PATENT_ORDER.index(new_status) < PATENT_ORDER.index(p.status):
                raise rule(f"A patent cannot move from {p.status} back to {new_status}", "INVALID_TRANSITION")
            if new_status in DATE_FIELD and getattr(p, DATE_FIELD[new_status]) is None:
                setattr(p, DATE_FIELD[new_status], await self.today())
            p.status = new_status
            await self.timeline("patent", p.id, new_status)
        await self.db.flush()
        await self._audit("update", "patent", p.id, None, body.model_dump(exclude_unset=True, mode="json"))
        await self._emit("research.patent_updated", {"patent_id": str(p.id), "status": p.status}, "patent", p.id)
        return (await self.patent_outs([p]))[0]

    async def patent_renewals(self) -> int:
        months = await self.int_setting("research", "patent_renewal_months", 12)
        today = await self.today()
        n = 0
        rows = (
            await self.db.execute(
                select(Patent).where(
                    Patent.institution_id == self.inst,
                    Patent.status.in_(("granted", "commercialised")),
                    Patent.granted_on.is_not(None),
                )
            )
        ).scalars()
        for p in rows:
            assert p.granted_on is not None
            elapsed = (today.year - p.granted_on.year) * 12 + today.month - p.granted_on.month
            if elapsed > 0 and elapsed % months == 0 and today.day == min(p.granted_on.day, 28):
                await self._notify(
                    "research.patent_renewal",
                    [await self.staff_user(p.staff_id)],
                    {"title": p.title[:120], "application_no": p.application_no or ""},
                )
                n += 1
        return n

    # ---- FDP --------------------------------------------------------------------------------------------------------------
    async def fdp_outs(self, rows: list[FacultyDevelopment]) -> list[FdpOut]:
        staff = await self.staff_map([r.staff_id for r in rows])
        metas = await self.metas("fdp", [r.id for r in rows]) if rows else {}
        out = []
        for r in rows:
            m = metas.get(str(r.id), {})
            out.append(
                FdpOut(
                    id=r.id,
                    staff_id=r.staff_id,
                    staff_name=staff_name(staff.get(r.staff_id)),
                    event_type=r.event_type,
                    title=r.title,
                    organiser=r.organiser,
                    from_on=r.from_on,
                    to_on=r.to_on,
                    role=r.role,
                    hours=r.hours,
                    certificate_url=r.certificate_url,
                    event_id=uuid.UUID(m["event_id"]) if m.get("event_id") else None,
                    auto_created=bool(m.get("auto")),
                )
            )
        return out

    async def fdps(
        self,
        *,
        staff_id: uuid.UUID | None = None,
        year: int | None = None,
        role: str | None = None,
        scope: str | None = None,
    ) -> list[FdpOut]:
        stmt = select(FacultyDevelopment).where(
            FacultyDevelopment.institution_id == self.inst,
            await self.owned_predicate(FacultyDevelopment.staff_id, scope=scope),
        )
        if staff_id:
            stmt = stmt.where(FacultyDevelopment.staff_id == staff_id)
        if year:
            stmt = stmt.where(extract("year", FacultyDevelopment.from_on) == year)
        if role:
            stmt = stmt.where(FacultyDevelopment.role == role)
        rows = list((await self.db.execute(stmt.order_by(FacultyDevelopment.from_on.desc().nullslast()))).scalars())
        return await self.fdp_outs(rows)

    async def create_fdp(self, body: FdpIn, *, auto: bool = False) -> FdpOut:
        if not auto:
            self.require_writer()
        owner = body.staff_id if auto and body.staff_id else await self._owner(body.staff_id)
        if body.from_on and body.to_on and body.to_on < body.from_on:
            raise rule("to_on precedes from_on", "BAD_DATES", 422)
        r = FacultyDevelopment(
            institution_id=self.inst,
            staff_id=owner,
            event_type=body.event_type.value,
            title=body.title,
            organiser=body.organiser,
            from_on=body.from_on,
            to_on=body.to_on,
            role=body.role.value,
            hours=body.hours,
            certificate_url=body.certificate_url,
        )
        self.db.add(r)
        await self.db.flush()
        if body.event_id or auto:
            await self.put_meta("fdp", r.id, {"event_id": str(body.event_id) if body.event_id else None, "auto": auto})
        await self._emit(
            "research.fdp_recorded",
            {"fdp_id": str(r.id), "staff_id": str(owner), "hours": float(r.hours or 0), "role": r.role},
            "faculty_development",
            r.id,
        )
        await self._notify(
            "research.fdp_recorded",
            [await self.staff_user(owner)],
            {"title": r.title[:120], "hours": str(r.hours or 0), "role": r.role},
        )
        return (await self.fdp_outs([r]))[0]

    async def update_fdp(self, fid: uuid.UUID, body: FdpUpdate) -> FdpOut:
        r = (
            await self.db.execute(
                select(FacultyDevelopment)
                .where(
                    FacultyDevelopment.id == fid,
                    FacultyDevelopment.institution_id == self.inst,
                    await self.owned_predicate(FacultyDevelopment.staff_id),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("FDP record")
        await self._can_write(r.staff_id)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(r, k, v.value if hasattr(v, "value") else v)
        await self.db.flush()
        return (await self.fdp_outs([r]))[0]

    async def on_event_completed(self, event_id: uuid.UUID) -> int:
        """Phase 25 ``event.completed`` (fdp / workshop / conference): attended staff + the organiser."""
        from app.models.events import Event, EventRegistration

        e = (await self.db.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
        if e is None or e.event_type not in ("fdp", "workshop", "conference"):
            return 0
        done = [k for k, m in (await self.metas("fdp")).items() if m.get("event_id") == str(event_id)]
        existing_staff = set()
        if done:
            existing_staff = {
                r[0]
                for r in (
                    await self.db.execute(
                        select(FacultyDevelopment.staff_id).where(
                            FacultyDevelopment.id.in_([uuid.UUID(d) for d in done])
                        )
                    )
                ).all()
            }
        days = max(1, (e.to_on - e.from_on).days + 1)
        hours = Decimal(days * 6)
        etype = e.event_type if e.event_type in ("fdp", "workshop", "conference") else "fdp"
        n = 0
        regs = (
            await self.db.execute(
                select(EventRegistration.person_id).where(
                    EventRegistration.event_id == e.id,
                    EventRegistration.person_type == "staff",
                    EventRegistration.attended.is_(True),
                )
            )
        ).all()
        targets = [(pid, "attended") for (pid,) in regs if pid]
        if e.organiser_staff_id:
            targets.append((e.organiser_staff_id, "organised"))
        for sid, role in targets:
            if sid in existing_staff:
                continue
            await self.create_fdp(
                FdpIn(
                    event_type=etype,
                    title=e.title[:300],
                    organiser=(await self.institution()).name[:200],
                    from_on=e.from_on,
                    to_on=e.to_on,
                    role=role,
                    hours=hours,
                    event_id=e.id,
                    staff_id=sid,
                ),
                auto=True,
            )
            existing_staff.add(sid)
            n += 1
        return n

    async def compliance(self, year: int, department_id: uuid.UUID | None = None) -> list[FdpComplianceRow]:
        target = await self.int_setting("research", "fdp_hours_target", 40)
        stmt = select(Staff).where(Staff.institution_id == self.inst, Staff.deleted_at.is_(None))
        if not self.reader_all():
            sub = self.staff_scope_subquery()
            mine = await self.my_staff_id()
            if sub is None and mine is None:
                return []
            stmt = stmt.where(Staff.id.in_(sub) if sub is not None else Staff.id == mine)
        if department_id:
            stmt = stmt.where(Staff.department_id == department_id)
        staff = list((await self.db.execute(stmt)).scalars())
        hours = {
            sid: (float(h or 0), int(c))
            for sid, h, c in (
                await self.db.execute(
                    select(
                        FacultyDevelopment.staff_id,
                        func.sum(FacultyDevelopment.hours),
                        func.count(FacultyDevelopment.id),
                    )
                    .where(
                        FacultyDevelopment.institution_id == self.inst,
                        extract("year", FacultyDevelopment.from_on) == year,
                    )
                    .group_by(FacultyDevelopment.staff_id)
                )
            ).all()
        }
        rows = [
            FdpComplianceRow(
                staff_id=s.id,
                name=staff_name(s) or "",
                department_id=s.department_id,
                hours=hours.get(s.id, (0.0, 0))[0],
                target=target,
                records=hours.get(s.id, (0.0, 0))[1],
                compliant=hours.get(s.id, (0.0, 0))[0] >= target,
            )
            for s in staff
            if s.staff_category == "teaching" or hours.get(s.id)
        ]
        return sorted(rows, key=lambda r: (r.compliant, r.hours))

    # ---- awards -------------------------------------------------------------------------------------------------------------
    async def award_outs(self, rows: list[FacultyAward]) -> list[AwardOut]:
        staff = await self.staff_map([r.staff_id for r in rows])
        metas = await self.metas("award", [r.id for r in rows]) if rows else {}
        return [
            AwardOut(
                id=r.id,
                staff_id=r.staff_id,
                staff_name=staff_name(staff.get(r.staff_id)),
                title=r.title,
                agency=r.agency,
                year=r.year,
                level=r.level,
                evidence_url=r.evidence_url,
                is_verified=bool(metas.get(str(r.id), {}).get("verified")),
            )
            for r in rows
        ]

    async def awards(self, *, year: int | None = None, scope: str | None = None) -> list[AwardOut]:
        stmt = select(FacultyAward).where(
            FacultyAward.institution_id == self.inst, await self.owned_predicate(FacultyAward.staff_id, scope=scope)
        )
        if year:
            stmt = stmt.where(FacultyAward.year == year)
        return await self.award_outs(list((await self.db.execute(stmt.order_by(FacultyAward.year.desc()))).scalars()))

    async def create_award(self, body: AwardIn) -> AwardOut:
        self.require_writer()
        owner = await self._owner(body.staff_id)
        r = FacultyAward(
            institution_id=self.inst,
            staff_id=owner,
            title=body.title,
            agency=body.agency,
            year=body.year or (await self.today()).year,
            level=body.level.value,
            evidence_url=body.evidence_url,
        )
        self.db.add(r)
        await self.db.flush()
        if self.cell("verify"):
            await self.put_meta("award", r.id, {"verified": True, "by": str(self.actor_id)})
        await self._emit(
            "research.award_recorded", {"award_id": str(r.id), "staff_id": str(owner)}, "faculty_award", r.id
        )
        return (await self.award_outs([r]))[0]

    async def verify_award(self, aid: uuid.UUID, approve: bool) -> AwardOut:
        self.require_cell("verify")
        r = (
            await self.db.execute(
                select(FacultyAward).where(FacultyAward.id == aid, FacultyAward.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Award")
        await self.put_meta("award", r.id, {"verified": approve, "by": str(self.actor_id)})
        return (await self.award_outs([r]))[0]
