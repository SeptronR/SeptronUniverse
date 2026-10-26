"""MoUs, collaborations and incubation — Prompts/30 §30.6 ``mou_service`` ({research.mous_collaborations}) and
``incubation_service`` ({research.incubation}).

* MoUs are drafted by the research cell (``research:mous``) or a coordinator, submitted into ``research.mou``
  (research cell → legal officer when ``governance.legal`` is on → principal); approval makes them ``approved`` and
  ``sign`` (dates + signed copy) makes them ``active``. Expiry chips from ``research.mou_expiry_alert_days``; the daily
  Beat marks lapsed MoUs ``expired`` and alerts the coordinator / research cell once per MoU per window
  (``research.mou_expiring``). Renewal creates a new version (a new ``mous`` row pointing at the previous one, which
  becomes ``renewed``). Faculty read the register without documents unless they coordinate the MoU.
* Collaborations under MoUs (joint research, exchange, joint degree, internships — an industry MoU's internships link
  the Phase 28 company); the activity report counts collaborations per MoU per year (NAAC 3.7.x "functional" MoUs).
* Start-ups register (founders tagged student / alumni / faculty), forward-only stage progression with funding,
  mentors; NAAC 3.x / NIRF innovation counts.
"""

import contextlib
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import extract, func, or_, select

from app.core.errors import APIError
from app.core.workflow import engine as workflow_engine
from app.enums.research import STARTUP_ORDER
from app.models.platform import WorkflowInstance
from app.models.research import Collaboration, IncubationStartup, Mou
from app.schemas.research import (
    CollaborationIn,
    CollaborationOut,
    MouActivityRow,
    MouIn,
    MouOut,
    MouSign,
    MouUpdate,
    StartupIn,
    StartupOut,
    StartupStageIn,
    StartupUpdate,
)
from app.services.research.common import ResearchBase, forbidden, not_found, rule, staff_name

WF_KEY = "research.mou"


class MouService(ResearchBase):
    def manager(self) -> bool:
        return self.cell("mous")

    async def row(self, mid: uuid.UUID, *, lock: bool = False) -> Mou:
        stmt = select(Mou).where(Mou.id == mid, Mou.institution_id == self.inst)
        m = (await self.db.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
        if m is None:
            raise not_found("MoU")
        return m

    async def outs(self, rows: list[Mou]) -> list[MouOut]:
        staff = await self.staff_map([r.coordinator_staff_id for r in rows])
        metas = await self.metas("mou", [r.id for r in rows]) if rows else {}
        ids = [r.id for r in rows]
        counts: dict[Any, Any] = (
            dict(
                (
                    await self.db.execute(
                        select(Collaboration.mou_id, func.count())
                        .where(Collaboration.mou_id.in_(ids))
                        .group_by(Collaboration.mou_id)
                    )
                )
                .tuples()
                .all()
            )
            if ids
            else {}
        )
        today = await self.today()
        window = await self.int_setting("research", "mou_expiry_alert_days", 90)
        mine = await self.my_staff_id()
        full = self.manager() or self.reader_all()
        out = []
        for r in rows:
            m = metas.get(str(r.id), {})
            days = (r.valid_to - today).days if r.valid_to else None
            expiry = "none" if days is None else "expired" if days < 0 else "expiring" if days <= window else "active"
            see_docs = full or (mine is not None and r.coordinator_staff_id == mine)
            out.append(
                MouOut(
                    id=r.id,
                    partner=r.partner,
                    partner_type=r.partner_type,
                    country=r.country,
                    mou_type=r.mou_type,
                    signed_on=r.signed_on,
                    valid_to=r.valid_to,
                    activities=list(r.activities or []) if see_docs else [],
                    document_url=r.document_url if see_docs else None,
                    coordinator_staff_id=r.coordinator_staff_id,
                    coordinator_name=staff_name(staff.get(r.coordinator_staff_id)) if r.coordinator_staff_id else None,
                    status=r.status,
                    collaborations=int(counts.get(r.id, 0)),
                    expiry=expiry,
                    days_to_expiry=days,
                    version=int(m.get("version") or 1),
                    previous_id=uuid.UUID(m["previous_id"]) if m.get("previous_id") else None,
                    workflow_instance_id=uuid.UUID(m["workflow_instance_id"])
                    if m.get("workflow_instance_id")
                    else None,
                    company_id=uuid.UUID(m["company_id"]) if m.get("company_id") else None,
                )
            )
        return out

    async def query(
        self, *, status: str | None = None, mou_type: str | None = None, expiring: bool = False, q: str | None = None
    ) -> list[MouOut]:
        stmt = select(Mou).where(Mou.institution_id == self.inst)
        if status:
            stmt = stmt.where(Mou.status == status)
        if mou_type:
            stmt = stmt.where(Mou.mou_type == mou_type)
        if q:
            stmt = stmt.where(Mou.partner.ilike(f"%{q}%"))
        if expiring:
            window = await self.int_setting("research", "mou_expiry_alert_days", 90)
            today = await self.today()
            stmt = stmt.where(Mou.valid_to.is_not(None), Mou.valid_to <= today + timedelta(days=window))
        rows = list((await self.db.execute(stmt.order_by(Mou.valid_to.asc().nullslast()))).scalars())
        return await self.outs(rows)

    async def get(self, mid: uuid.UUID) -> MouOut:
        return (await self.outs([await self.row(mid)]))[0]

    async def _can_edit(self, r: Mou) -> None:
        self.require_writer()
        if not self.manager() and not (r.coordinator_staff_id and r.coordinator_staff_id == await self.my_staff_id()):
            raise forbidden("research:mous or the MoU coordinator required")

    async def create(self, body: MouIn, *, previous: Mou | None = None) -> MouOut:
        self.require_writer()
        if not self.manager():
            raise forbidden("research:mous required")
        if body.signed_on and body.valid_to and body.valid_to < body.signed_on:
            raise rule("valid_to precedes signed_on", "BAD_DATES", 422)
        r = Mou(
            institution_id=self.inst,
            partner=body.partner,
            partner_type=body.partner_type.value,
            country=body.country,
            mou_type=body.mou_type.value,
            signed_on=None,
            valid_to=body.valid_to,
            activities=body.activities,
            document_url=body.document_url,
            coordinator_staff_id=body.coordinator_staff_id,
            status="draft",
        )
        self.db.add(r)
        await self.db.flush()
        meta: dict[str, Any] = {"version": 1, "company_id": str(body.company_id) if body.company_id else None}
        if previous is not None:
            pm = await self.meta("mou", previous.id)
            meta.update(version=int(pm.get("version") or 1) + 1, previous_id=str(previous.id))
        await self.put_meta("mou", r.id, meta)
        await self._audit("create", "mou", r.id, None, body.model_dump(mode="json"))
        await self._emit("research.mou_created", {"mou_id": str(r.id), "partner": r.partner}, "mou", r.id)
        return (await self.outs([r]))[0]

    async def update(self, mid: uuid.UUID, body: MouUpdate) -> MouOut:
        r = await self.row(mid, lock=True)
        await self._can_edit(r)
        data = body.model_dump(exclude_unset=True)
        if not self.manager():
            data = {k: v for k, v in data.items() if k == "activities"}  # coordinators record activities
        for k, v in data.items():
            setattr(r, k, v)
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def submit(self, mid: uuid.UUID) -> MouOut:
        r = await self.row(mid, lock=True)
        await self._can_edit(r)
        if r.status not in ("draft", "rejected"):
            raise rule("Only a draft MoU is submitted", "NOT_DRAFT")
        legal = await self.feature("governance.legal")
        wf = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WF_KEY,
            entity_type="mou",
            entity_id=r.id,
            started_by=self.actor_id,
            context={"legal_review": legal, "partner": r.partner, "mou_type": r.mou_type},
            title=f"MoU · {r.partner[:100]}",
        )
        r.status = "submitted"
        m = await self.meta("mou", r.id)
        m["workflow_instance_id"] = str(wf.id)
        await self.put_meta("mou", r.id, m)
        if self.principal is not None and self.manager():
            with contextlib.suppress(APIError):  # the research cell submitting is step 1
                await workflow_engine.act(
                    self.db, instance_id=wf.id, actor=self.principal, decision="approve", comment="Submitted"
                )
        await self.db.flush()
        await self.db.refresh(r)
        return (await self.outs([r]))[0]

    async def on_decided(self, mid: uuid.UUID, approved: bool) -> None:
        r = (await self.db.execute(select(Mou).where(Mou.id == mid).with_for_update())).scalar_one_or_none()
        if r is None or r.status != "submitted":
            return
        r.status = "approved" if approved else "rejected"
        await self.db.flush()

    async def sign(self, mid: uuid.UUID, body: MouSign) -> MouOut:
        r = await self.row(mid, lock=True)
        self.require_writer()
        if not self.manager():
            raise forbidden("research:mous required")
        if r.status != "approved":
            raise rule("The MoU must be approved before signing", "NOT_APPROVED")
        if body.valid_to < body.signed_on:
            raise rule("valid_to precedes signed_on", "BAD_DATES", 422)
        r.signed_on, r.valid_to, r.status = body.signed_on, body.valid_to, "active"
        if body.document_url:
            r.document_url = body.document_url
        m = await self.meta("mou", r.id)
        if m.get("previous_id"):
            prev = (
                await self.db.execute(select(Mou).where(Mou.id == uuid.UUID(m["previous_id"])).with_for_update())
            ).scalar_one_or_none()
            if prev is not None:
                prev.status = "renewed"
                await self._emit("research.mou_renewed", {"mou_id": str(prev.id), "new_id": str(r.id)}, "mou", prev.id)
        await self.db.flush()
        await self._emit("research.mou_signed", {"mou_id": str(r.id), "valid_to": str(r.valid_to)}, "mou", r.id)
        return (await self.outs([r]))[0]

    async def renew(self, mid: uuid.UUID) -> MouOut:
        r = await self.row(mid)
        if r.status not in ("active", "expired"):
            raise rule("Only an active / expired MoU is renewed", "NOT_RENEWABLE")
        m = await self.meta("mou", r.id)
        return await self.create(
            MouIn(
                partner=r.partner,
                partner_type=r.partner_type,
                country=r.country,
                mou_type=r.mou_type,
                activities=list(r.activities or []),
                coordinator_staff_id=r.coordinator_staff_id,
                company_id=uuid.UUID(m["company_id"]) if m.get("company_id") else None,
            ),
            previous=r,
        )

    async def expiry_scan(self) -> int:
        today = await self.today()
        window = await self.int_setting("research", "mou_expiry_alert_days", 90)
        n = 0
        rows = list(
            (
                await self.db.execute(
                    select(Mou)
                    .where(Mou.institution_id == self.inst, Mou.status == "active", Mou.valid_to.is_not(None))
                    .with_for_update()
                )
            ).scalars()
        )
        cell_users = await self.role_users("research_cell")
        for r in rows:
            assert r.valid_to is not None
            if r.valid_to < today:
                r.status = "expired"
                continue
            if r.valid_to <= today + timedelta(days=window):
                m = await self.meta("mou", r.id)
                if m.get("alerted_for") == r.valid_to.isoformat():
                    continue
                users: list[uuid.UUID | None] = list(cell_users)
                if r.coordinator_staff_id:
                    users.append(await self.staff_user(r.coordinator_staff_id))
                await self._notify(
                    "research.mou_expiring", users, {"partner": r.partner, "valid_to": r.valid_to.isoformat()}
                )
                await self._emit(
                    "research.mou_expiring", {"mou_id": str(r.id), "valid_to": r.valid_to.isoformat()}, "mou", r.id
                )
                m["alerted_for"] = r.valid_to.isoformat()
                await self.put_meta("mou", r.id, m)
                n += 1
        await self.db.flush()
        return n

    # ---- collaborations -------------------------------------------------------------------------------------------------
    async def collab_outs(self, rows: list[Collaboration]) -> list[CollaborationOut]:
        mids = [r.mou_id for r in rows if r.mou_id]
        partners: dict[Any, Any] = (
            dict((await self.db.execute(select(Mou.id, Mou.partner).where(Mou.id.in_(mids)))).tuples().all())
            if mids
            else {}
        )
        return [
            CollaborationOut(
                id=r.id,
                mou_id=r.mou_id,
                partner=partners.get(r.mou_id) if r.mou_id else None,
                title=r.title,
                collaboration_type=r.collaboration_type,
                participants=list(r.participants or []),
                from_on=r.from_on,
                to_on=r.to_on,
                outcomes=list(r.outcomes or []),
            )
            for r in rows
        ]

    async def collaborations(
        self, *, mou_id: uuid.UUID | None = None, ctype: str | None = None, year: int | None = None
    ) -> list[CollaborationOut]:
        stmt = select(Collaboration).where(Collaboration.institution_id == self.inst)
        if mou_id:
            stmt = stmt.where(Collaboration.mou_id == mou_id)
        if ctype:
            stmt = stmt.where(Collaboration.collaboration_type == ctype)
        if year:
            stmt = stmt.where(extract("year", Collaboration.from_on) == year)
        return await self.collab_outs(
            list((await self.db.execute(stmt.order_by(Collaboration.from_on.desc().nullslast()))).scalars())
        )

    async def add_collaboration(self, mid: uuid.UUID | None, body: CollaborationIn) -> CollaborationOut:
        self.require_writer()
        mou = None
        if mid or body.mou_id:
            mou = await self.row(mid or body.mou_id)  # type: ignore[arg-type]
            await self._can_edit(mou)
            if mou.status not in ("active", "approved"):
                raise rule("Collaborations are recorded under an active MoU", "MOU_NOT_ACTIVE")
        elif not self.manager():
            raise forbidden("research:mous required")
        r = Collaboration(
            institution_id=self.inst,
            mou_id=mou.id if mou else None,
            title=body.title,
            collaboration_type=body.collaboration_type.value,
            participants=body.participants,
            from_on=body.from_on or await self.today(),
            to_on=body.to_on,
            outcomes=body.outcomes,
        )
        self.db.add(r)
        await self.db.flush()
        if mou is not None and body.collaboration_type.value == "internship":
            await self._company_link(mou)
        await self._emit(
            "research.collaboration_recorded",
            {"collaboration_id": str(r.id), "mou_id": str(mou.id) if mou else None, "type": r.collaboration_type},
            "collaboration",
            r.id,
        )
        return (await self.collab_outs([r]))[0]

    async def _company_link(self, mou: Mou) -> None:
        """Internships under an industry MoU reuse / create the Phase 28 company."""
        m = await self.meta("mou", mou.id)
        if m.get("company_id") or mou.partner_type != "industry":
            return
        from app.models.placement import Company

        c = (
            await self.db.execute(
                select(Company).where(
                    Company.institution_id == self.inst, func.lower(Company.name) == mou.partner.lower()
                )
            )
        ).scalar_one_or_none()
        if c is None:
            c = Company(institution_id=self.inst, name=mou.partner[:200])
            self.db.add(c)
            await self.db.flush()
        m["company_id"] = str(c.id)
        await self.put_meta("mou", mou.id, m)

    async def activity_report(self, year: int) -> list[MouActivityRow]:
        rows = list((await self.db.execute(select(Mou).where(Mou.institution_id == self.inst))).scalars())
        counts: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(Collaboration.mou_id, func.count())
                    .where(Collaboration.institution_id == self.inst, extract("year", Collaboration.from_on) == year)
                    .group_by(Collaboration.mou_id)
                )
            )
            .tuples()
            .all()
        )
        return [
            MouActivityRow(
                mou_id=r.id,
                partner=r.partner,
                mou_type=r.mou_type,
                status=r.status,
                collaborations=int(counts.get(r.id, 0)),
                functional=int(counts.get(r.id, 0)) > 0,
            )
            for r in rows
            if r.signed_on is None or r.signed_on.year <= year
        ]

    # ---- start-ups ---------------------------------------------------------------------------------------------------------
    def incubation(self) -> bool:
        return self.cell("incubation")

    async def startup_outs(self, rows: list[IncubationStartup]) -> list[StartupOut]:
        staff = await self.staff_map([r.mentor_staff_id for r in rows])
        metas = await self.metas("startup", [r.id for r in rows]) if rows else {}
        return [
            StartupOut(
                id=r.id,
                name=r.name,
                founders=list(r.founders or []),
                sector=r.sector,
                stage=r.stage,
                funding_paise=r.funding_paise,
                mentor_staff_id=r.mentor_staff_id,
                mentor_name=staff_name(staff.get(r.mentor_staff_id)) if r.mentor_staff_id else None,
                registered_on=r.registered_on,
                status=r.status,
                history=list(metas.get(str(r.id), {}).get("timeline") or []),
            )
            for r in rows
        ]

    async def startups(self, *, stage: str | None = None, q: str | None = None) -> list[StartupOut]:
        stmt = select(IncubationStartup).where(IncubationStartup.institution_id == self.inst)
        if stage:
            stmt = stmt.where(IncubationStartup.stage == stage)
        if q:
            stmt = stmt.where(or_(IncubationStartup.name.ilike(f"%{q}%"), IncubationStartup.sector.ilike(f"%{q}%")))
        return await self.startup_outs(
            list((await self.db.execute(stmt.order_by(IncubationStartup.created_at.desc()))).scalars())
        )

    async def startup_row(self, sid: uuid.UUID, *, lock: bool = False) -> IncubationStartup:
        stmt = select(IncubationStartup).where(
            IncubationStartup.id == sid, IncubationStartup.institution_id == self.inst
        )
        r = (await self.db.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Start-up")
        return r

    async def create_startup(self, body: StartupIn) -> StartupOut:
        self.require_writer()
        if not self.incubation():
            raise forbidden("research:incubation required")
        r = IncubationStartup(
            institution_id=self.inst,
            name=body.name,
            founders=body.founders,
            sector=body.sector,
            stage=body.stage.value,
            funding_paise=body.funding_paise,
            mentor_staff_id=body.mentor_staff_id,
            registered_on=body.registered_on or await self.today(),
            status="active",
        )
        self.db.add(r)
        await self.db.flush()
        await self.timeline("startup", r.id, r.stage)
        await self._emit("research.startup_updated", {"startup_id": str(r.id), "stage": r.stage}, "startup", r.id)
        return (await self.startup_outs([r]))[0]

    async def update_startup(self, sid: uuid.UUID, body: StartupUpdate) -> StartupOut:
        self.require_writer()
        if not self.incubation():
            raise forbidden("research:incubation required")
        r = await self.startup_row(sid, lock=True)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(r, k, v)
        await self.db.flush()
        return (await self.startup_outs([r]))[0]

    async def stage(self, sid: uuid.UUID, body: StartupStageIn) -> StartupOut:
        self.require_writer()
        if not self.incubation():
            raise forbidden("research:incubation required")
        r = await self.startup_row(sid, lock=True)
        if STARTUP_ORDER.index(body.stage.value) <= STARTUP_ORDER.index(r.stage):
            raise rule(f"A start-up moves forward from {r.stage}", "INVALID_TRANSITION")
        r.stage = body.stage.value
        if body.funding_paise:
            r.funding_paise = int(r.funding_paise or 0) + body.funding_paise
        if r.stage == "graduated":
            r.status = "graduated"
        await self.timeline("startup", r.id, r.stage, funding_paise=body.funding_paise, note=body.note)
        await self.db.flush()
        await self._emit("research.startup_updated", {"startup_id": str(r.id), "stage": r.stage}, "startup", r.id)
        return (await self.startup_outs([r]))[0]


@workflow_engine.on(WF_KEY, "approved")
async def _mou_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await MouService(db, actor, institution_id=instance.institution_id).on_decided(instance.entity_id, True)


@workflow_engine.on(WF_KEY, "rejected")
async def _mou_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await MouService(db, actor, institution_id=instance.institution_id).on_decided(instance.entity_id, False)
