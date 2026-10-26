"""Alumni jobs board — Prompts/29 §29.6 ``jobs_service`` {alumni.jobs_board}.

Posts by **verified** alumni (or the coordinator); with ``alumni.jobs_moderation`` a post waits in the moderation
queue (``pending``) until the coordinator approves / rejects it (reason). Approved, unexpired posts are visible to
alumni and — when ``alumni.jobs_open_to_students`` and the post opts in — to final-year students (read only).
Apply-link clicks are counted; the daily Beat expires posts past ``expires_on``; the placement officer converts a post
into a Phase 28 company lead (existing company by name, or a new one).
"""

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.models.alumni import AlumniJob, AlumniProfile
from app.schemas.alumni import AlmJobClick, AlmJobIn, AlmJobOut, JobModeration
from app.services.alumni.common import AlumniBase, forbidden, not_found, now_utc, rule

ENTITY = "alumni_job"


class JobsService(AlumniBase):
    async def outs(self, rows: list[AlumniJob]) -> list[AlmJobOut]:
        metas = await self.metas("job", [str(j.id) for j in rows])
        posters = [j.posted_by_alumni_id for j in rows if j.posted_by_alumni_id]
        profiles = (
            list((await self.db.execute(select(AlumniProfile).where(AlumniProfile.id.in_(posters)))).scalars())
            if posters
            else []
        )
        cards = await self.cards(profiles)
        out: list[AlmJobOut] = []
        for j in rows:
            m = metas.get(str(j.id), {})
            out.append(
                AlmJobOut(
                    id=j.id,
                    title=j.title,
                    company=j.company,
                    location=j.location,
                    description=j.description,
                    apply_url=j.apply_url,
                    expires_on=j.expires_on,
                    is_active=j.is_active,
                    status=m.get("status") or ("approved" if j.is_active else "expired"),
                    reason=m.get("reason"),
                    clicks=int(m.get("clicks") or 0),
                    open_to_students=bool(m.get("open_to_students")),
                    posted_by_alumni_id=j.posted_by_alumni_id,
                    posted_by=(cards.get(j.posted_by_alumni_id) or {}).get("name") if j.posted_by_alumni_id else None,
                    lead_company_id=uuid.UUID(m["lead_company_id"]) if m.get("lead_company_id") else None,
                    created_at=j.created_at,
                )
            )
        return out

    async def _row(self, jid: uuid.UUID, *, lock: bool = False) -> AlumniJob:
        stmt = select(AlumniJob).where(AlumniJob.id == jid, AlumniJob.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        j = (await self.db.execute(stmt)).scalar_one_or_none()
        if j is None:
            raise not_found("Job post")
        return j

    def manager(self) -> bool:
        return self.coordinator() or self.can("placement", "manage") or self.can("alumni", "view_all")

    async def _viewer(self) -> str:
        """``manager`` | ``alumni`` | ``student`` (students only when the board is opened to them)."""
        if self.manager():
            return "manager"
        if await self.my_profile() is not None:
            return "alumni"
        if (
            self.can("alumni", "self")
            and await self.my_student() is not None
            and await self.setting("alumni", "jobs_open_to_students") is True
        ):
            return "student"
        raise forbidden("The alumni jobs board is not open to students")

    async def list_jobs(self, status: str | None = None, q: str | None = None) -> list[AlmJobOut]:
        viewer = await self._viewer()
        stmt = select(AlumniJob).where(AlumniJob.institution_id == self.inst)
        if q:
            stmt = stmt.where(AlumniJob.title.ilike(f"%{q}%") | AlumniJob.company.ilike(f"%{q}%"))
        rows = list((await self.db.execute(stmt.order_by(AlumniJob.created_at.desc()).limit(500))).scalars())
        outs = await self.outs(rows)
        if viewer == "manager":
            return [o for o in outs if not status or o.status == status]
        today = await self.today()
        visible = [
            o
            for o in outs
            if o.status == "approved" and o.is_active and (o.expires_on is None or o.expires_on >= today)
        ]
        if viewer == "student":
            visible = [o for o in visible if o.open_to_students]
        return visible

    async def get(self, jid: uuid.UUID) -> AlmJobOut:
        j = await self._row(jid)
        o = (await self.outs([j]))[0]
        if not self.manager():
            me = await self.my_profile()
            if o.status != "approved" and (me is None or j.posted_by_alumni_id != me.id):
                raise not_found("Job post")
        return o

    async def mine(self) -> list[AlmJobOut]:
        me = await self.require_my_profile()
        rows = list(
            (
                await self.db.execute(
                    select(AlumniJob)
                    .where(AlumniJob.posted_by_alumni_id == me.id)
                    .order_by(AlumniJob.created_at.desc())
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def create(self, body: AlmJobIn) -> AlmJobOut:
        self.require_writer()
        me = await self.my_profile()
        if me is None and not self.coordinator():
            raise forbidden("Only alumni or the alumni coordinator post jobs")
        if me is not None and not me.is_verified:
            raise rule("Only verified alumni post jobs", "VERIFICATION_REQUIRED", 403)
        moderated = await self.setting("alumni", "jobs_moderation") is not False and not self.coordinator()
        days = await self.int_setting("alumni", "job_expiry_days", 60)
        j = AlumniJob(
            institution_id=self.inst,
            posted_by_alumni_id=me.id if me else None,
            title=body.title,
            company=body.company,
            location=body.location,
            description=body.description,
            apply_url=body.apply_url,
            expires_on=body.expires_on or (await self.today()) + timedelta(days=days),
            is_active=not moderated,
        )
        self.db.add(j)
        await self.db.flush()
        status = "pending" if moderated else "approved"
        await self.put_meta(
            "job",
            j.id,
            {"status": status, "clicks": 0, "open_to_students": body.open_to_students, "poster": str(self.actor_id)},
        )
        await self._audit("create", ENTITY, j.id, None, {"title": j.title, "status": status})
        await self._emit("alumni.job_posted", {"job_id": str(j.id), "status": status}, ENTITY, j.id)
        return (await self.outs([j]))[0]

    async def moderate(self, jid: uuid.UUID, body: JobModeration) -> AlmJobOut:
        self.require_coordinator()
        j = await self._row(jid, lock=True)
        m = await self.meta("job", j.id)
        if m.get("status") not in (None, "pending", "rejected"):
            raise rule("Only pending posts are moderated", "NOT_PENDING")
        m.update(
            {
                "status": "approved" if body.approve else "rejected",
                "reason": body.reason,
                "moderated_by": str(self.actor_id),
                "moderated_at": now_utc().isoformat(),
            }
        )
        j.is_active = body.approve
        await self.put_meta("job", j.id, m)
        poster = None
        if j.posted_by_alumni_id:
            poster = (
                await self.db.execute(select(AlumniProfile.user_id).where(AlumniProfile.id == j.posted_by_alumni_id))
            ).scalar_one_or_none()
        await self._audit("moderate", ENTITY, j.id, None, {"approve": body.approve, "reason": body.reason})
        if body.approve:
            await self._emit("alumni.job_approved", {"job_id": str(j.id)}, ENTITY, j.id)
            await self._notify("alumni.job_approved", [poster], {"title": j.title})
        else:
            await self._emit("alumni.job_rejected", {"job_id": str(j.id), "reason": body.reason}, ENTITY, j.id)
            await self._notify("alumni.job_rejected", [poster], {"title": j.title, "reason": body.reason or ""})
        return (await self.outs([j]))[0]

    async def click(self, jid: uuid.UUID) -> AlmJobClick:
        await self._viewer()
        j = await self._row(jid)
        row = await self._meta_row("job", j.id)
        m = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
        if m.get("status", "approved") != "approved":
            raise not_found("Job post")
        m["clicks"] = int(m.get("clicks") or 0) + 1
        await self.put_meta("job", j.id, m)
        return AlmJobClick(clicks=m["clicks"], apply_url=j.apply_url)

    async def to_lead(self, jid: uuid.UUID) -> AlmJobOut:
        """Placement officer: convert the post into a Phase 28 company lead."""
        if not self.can("placement", "manage"):
            raise forbidden("placement:manage required")
        self.require_writer()
        from app.models.placement import Company

        j = await self._row(jid, lock=True)
        name = (j.company or "").strip()
        if not name:
            raise rule("The post has no company to convert", "NO_COMPANY")
        c = (
            await self.db.execute(
                select(Company).where(Company.institution_id == self.inst, func.lower(Company.name) == name.lower())
            )
        ).scalar_one_or_none()
        if c is None:
            c = Company(
                institution_id=self.inst,
                name=name[:200],
                hq_city=j.location,
                recruiter_user_ids=[],
                notes=f"Lead from alumni job post {j.title}",
            )
            self.db.add(c)
            await self.db.flush()
            await self._emit("placement.company_created", {"company_id": str(c.id), "name": c.name}, "company", c.id)
        m = await self.meta("job", j.id)
        m["lead_company_id"] = str(c.id)
        await self.put_meta("job", j.id, m)
        await self._audit("lead", ENTITY, j.id, None, {"company_id": str(c.id)})
        return (await self.outs([j]))[0]

    async def expire(self) -> int:
        today = await self.today()
        n = 0
        for j in (
            await self.db.execute(
                select(AlumniJob).where(
                    AlumniJob.institution_id == self.inst, AlumniJob.is_active.is_(True), AlumniJob.expires_on < today
                )
            )
        ).scalars():
            j.is_active = False
            m = await self.meta("job", j.id)
            m["status"] = "expired"
            await self.put_meta("job", j.id, m)
            await self._emit("alumni.job_expired", {"job_id": str(j.id)}, ENTITY, j.id)
            n += 1
        return n
