"""Alumni events — Prompts/29 §29.6 ``event_service`` {alumni.core}.

An alumni event is a Phase 25 ``events(event_type='alumni')`` row wrapped by ``alumni_events`` (type, held-on, venue,
``registrations_count``). The coordinator's event is scheduled on creation (no proposal workflow — Prompts/29
"Workflows: none") with public registration open, the fee on the Phase 25 registration settings (registration and
payment go through ``/events/{id}/register`` → invoice ``source_type=event_registration``). Invitations target a
segment of alumni (graduation years, programmes, chapter, city) as a Phase 24 draft campaign plus in-app / email
notifications. ``registrations_count`` is re-synced on registration / attendance events and on ``events.completed``
(NAAC 5.4.1 evidence counts attended alumni).
"""

import uuid
from typing import Any

from sqlalchemy import func, select

from app.models.alumni import AlumniEvent, AlumniProfile
from app.models.events import Event, EventRegistration
from app.schemas.alumni import AlmEventIn, AlmEventInvite, AlmEventOut, AlmInviteReport
from app.services.alumni.common import AlumniBase, forbidden, not_found

ENTITY = "alumni_event"


class AlumniEventService(AlumniBase):
    async def outs(self, rows: list[AlumniEvent]) -> list[AlmEventOut]:
        eids = [r.event_id for r in rows if r.event_id]
        events = (
            {e.id: e for e in (await self.db.execute(select(Event).where(Event.id.in_(eids)))).scalars()}
            if eids
            else {}
        )
        attended: dict[uuid.UUID, int] = {}
        if eids:
            attended = {
                k: int(v)
                for k, v in (
                    await self.db.execute(
                        select(EventRegistration.event_id, func.count())
                        .where(EventRegistration.event_id.in_(eids), EventRegistration.attended.is_(True))
                        .group_by(EventRegistration.event_id)
                    )
                ).all()
            }
        mine: dict[uuid.UUID, uuid.UUID] = {}
        me = await self.my_profile()
        if me is not None and eids:
            regs = await self.db.execute(
                select(EventRegistration.event_id, EventRegistration.id).where(
                    EventRegistration.event_id.in_(eids), EventRegistration.person_id == me.student_id
                )
            )
            mine = dict(regs.tuples().all())
        metas = await self.metas("alumni_event", [str(r.id) for r in rows])
        out: list[AlmEventOut] = []
        for r in rows:
            e = events.get(r.event_id) if r.event_id else None
            m = metas.get(str(r.id), {})
            out.append(
                AlmEventOut(
                    id=r.id,
                    title=r.title,
                    event_type=r.event_type,
                    held_on=r.held_on,
                    venue=r.venue,
                    event_id=r.event_id,
                    event_status=e.status if e else None,
                    registration_fee_paise=int(e.registration_fee_paise or 0) if e else 0,
                    registrations_count=r.registrations_count,
                    attended_count=attended.get(r.event_id, 0) if r.event_id else 0,
                    webinar_url=m.get("webinar_url"),
                    invited=int(m.get("invited") or 0),
                    photos=list((e.images if e else None) or m.get("photos") or []),
                    my_registration_id=mine.get(r.event_id) if r.event_id else None,
                    created_at=r.created_at,
                )
            )
        return out

    async def row(self, aid: uuid.UUID) -> AlumniEvent:
        r = (
            await self.db.execute(
                select(AlumniEvent).where(AlumniEvent.id == aid, AlumniEvent.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Alumni event")
        return r

    async def list_events(self, upcoming: bool | None = None) -> list[AlmEventOut]:
        stmt = select(AlumniEvent).where(AlumniEvent.institution_id == self.inst)
        if upcoming is True:
            stmt = stmt.where(AlumniEvent.held_on >= await self.today())
        elif upcoming is False:
            stmt = stmt.where(AlumniEvent.held_on < await self.today())
        return await self.outs(list((await self.db.execute(stmt.order_by(AlumniEvent.held_on.desc()))).scalars()))

    async def get(self, aid: uuid.UUID) -> AlmEventOut:
        return (await self.outs([await self.row(aid)]))[0]

    async def create(self, body: AlmEventIn) -> AlmEventOut:
        self.require_coordinator()
        from app.schemas.events import EventCreate, EventRegistrationSettings
        from app.services.facilities.event_service import EventService

        es = EventService(self.db, self.principal, self.request, self.inst)
        created = await es.create(
            EventCreate(
                event_type="alumni",
                title=body.title,
                description=body.description,
                college_id=body.college_id,
                from_on=body.held_on,
                to_on=body.to_on or body.held_on,
                venue_text=body.venue or ("Online" if body.webinar_url else None),
                registration=EventRegistrationSettings(
                    open=True, fee_paise=body.registration_fee_paise, capacity=body.capacity, audience="public"
                ),
                naac_criterion="5.4.1",
            )
        )
        e = (await self.db.execute(select(Event).where(Event.id == created.id))).scalar_one()
        e.status = "scheduled"
        r = AlumniEvent(
            institution_id=self.inst,
            title=body.title,
            held_on=body.held_on,
            venue=body.venue,
            event_type=body.event_type,
            event_id=e.id,
        )
        self.db.add(r)
        await self.db.flush()
        await self.put_meta("alumni_event", r.id, {"webinar_url": body.webinar_url})
        await self._audit("create", ENTITY, r.id, None, {"title": r.title, "event_id": str(e.id)})
        await self._emit("alumni.event_created", {"alumni_event_id": str(r.id), "event_id": str(e.id)}, ENTITY, r.id)
        return await self.get(r.id)

    async def invite(self, aid: uuid.UUID, body: AlmEventInvite) -> AlmInviteReport:
        self.require_coordinator()
        r = await self.row(aid)
        stmt = select(AlumniProfile.id, AlumniProfile.user_id).where(
            AlumniProfile.institution_id == self.inst, AlumniProfile.user_id.is_not(None)
        )
        if body.graduation_years:
            stmt = stmt.where(AlumniProfile.graduation_year.in_(body.graduation_years))
        if body.program_ids:
            stmt = stmt.where(AlumniProfile.program_id.in_(body.program_ids))
        if body.city:
            stmt = stmt.where(func.lower(AlumniProfile.city) == body.city.strip().lower())
        if body.verified_only:
            stmt = stmt.where(AlumniProfile.is_verified.is_(True))
        rows: list[tuple[Any, Any]] = list((await self.db.execute(stmt)).tuples().all())
        if body.chapter:
            metas = await self.metas("profile", [str(a) for a, _ in rows])
            rows = [(a, u) for a, u in rows if (metas.get(str(a)) or {}).get("chapter") == body.chapter]
        users = [u for _, u in rows]
        campaign_id = await self._campaign(r, users, body)
        await self._notify(
            "alumni.event_invite",
            users,
            {"title": r.title, "held_on": r.held_on.isoformat() if r.held_on else "", "venue": r.venue or "Online"},
        )
        m = await self.meta("alumni_event", r.id)
        m["invited"] = int(m.get("invited") or 0) + len(users)
        m.setdefault("invites", []).append({"segment": body.model_dump(mode="json"), "count": len(users)})
        await self.put_meta("alumni_event", r.id, m)
        await self._audit("invite", ENTITY, r.id, None, {"count": len(users)})
        return AlmInviteReport(invited=len(users), campaign_id=campaign_id)

    async def _campaign(self, r: AlumniEvent, users: list[Any], body: AlmEventInvite) -> uuid.UUID | None:
        """A Phase 24 draft campaign on the alumni segment (sent from the campaigns console)."""
        from app.models.comms_advanced import BulkCampaign

        if not users:
            return None
        c = BulkCampaign(
            institution_id=self.inst,
            name=f"Invite: {r.title}"[:160],
            channels=["email", "in_app"],
            audience_rules={"user_ids": [str(u) for u in users], "segment": "alumni", **body.model_dump(mode="json")},
            status="draft",
            created_by=self.actor_id,
        )
        self.db.add(c)
        await self.db.flush()
        return c.id

    async def mine(self) -> list[AlmEventOut]:
        me = await self.my_profile()
        if me is None:
            raise forbidden("No alumni profile for the caller")
        rows = list(
            (
                await self.db.execute(
                    select(AlumniEvent)
                    .join(EventRegistration, EventRegistration.event_id == AlumniEvent.event_id)
                    .where(AlumniEvent.institution_id == self.inst, EventRegistration.person_id == me.student_id)
                    .order_by(AlumniEvent.held_on.desc())
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def sync_counts(self, event_id: uuid.UUID) -> int:
        r = (
            await self.db.execute(select(AlumniEvent).where(AlumniEvent.event_id == event_id).with_for_update())
        ).scalar_one_or_none()
        if r is None:
            return 0
        r.registrations_count = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(EventRegistration).where(EventRegistration.event_id == event_id)
                )
            ).scalar_one()
        )
        await self.db.flush()
        return r.registrations_count
