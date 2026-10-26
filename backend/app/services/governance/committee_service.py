"""Committees — Prompts/33 §33.6 ``committee_service`` ({governance.committees}).

Replaces the Phase 27 stub on the same ``committees`` / ``committee_members`` rows (stub-created rows are read
unchanged; a row without ``quorum_rule`` gets the type default on read). Statutory / custom committees from the
templates of the institution type (``app/enums/governance.py``), members with tenure (``from_on`` / ``to_on``), external
members (no login; ``external {name, org, email, phone}``), student members, chair / secretary, validity
(``valid_to``) and **reconstitution** (the current members' ``to_on`` closes the old tenure, history is kept in
``committee:<id>.history``), quorum rules ``fraction | count``, the committee page (members, meetings, open
resolutions, ATR pendency) and the statutory coverage check (anti-ragging, ICC, grievance mandatory) that Phase 32
uses as 7.1.x evidence. Phase 27 routing keeps calling ``SupportBase.committee_by_type``.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.enums.governance import MANDATORY_COMMITTEES, TYPE_CODES, committee_templates
from app.models.governance import ActionTakenReport, Committee, CommitteeMember, Meeting, Resolution
from app.models.platform import Institution
from app.schemas.governance import (
    CommitteeDetail,
    CommitteeFromTemplate,
    CommitteeIn,
    CommitteeOut,
    CommitteeReconstitute,
    CommitteeTemplateOut,
    CommitteeUpdate,
    CoverageItem,
    MemberIn,
    MemberOut,
    MemberUpdate,
)
from app.services.governance.common import GovernanceBase, committee_code, forbidden, not_found, now_utc, rule

ENTITY = "committee"


def _active(m: CommitteeMember, today: date) -> bool:
    return (m.from_on is None or m.from_on <= today) and (m.to_on is None or m.to_on >= today)


class CommitteeService(GovernanceBase):
    # ---- read ---------------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[Committee]) -> list[CommitteeOut]:
        if not rows:
            return []
        ids = [r.id for r in rows]
        today = await self.today()
        counts = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(CommitteeMember.committee_id, func.count())
                    .where(
                        CommitteeMember.committee_id.in_(ids),
                        or_(CommitteeMember.to_on.is_(None), CommitteeMember.to_on >= today),
                    )
                    .group_by(CommitteeMember.committee_id)
                )
            ).all()
        }
        nxt: dict[uuid.UUID, Any] = {
            r[0]: r[1]
            for r in (
                await self.db.execute(
                    select(Meeting.committee_id, func.min(Meeting.held_on))
                    .where(Meeting.committee_id.in_(ids), Meeting.status == "scheduled", Meeting.held_on >= now_utc())
                    .group_by(Meeting.committee_id)
                )
            ).all()
        }
        open_res = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(Meeting.committee_id, func.count())
                    .join(Resolution, Resolution.meeting_id == Meeting.id)
                    .where(Meeting.committee_id.in_(ids), Resolution.status == "passed")
                    .group_by(Meeting.committee_id)
                )
            ).all()
        }
        pending = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(Meeting.committee_id, func.count())
                    .join(Resolution, Resolution.meeting_id == Meeting.id)
                    .join(ActionTakenReport, ActionTakenReport.resolution_id == Resolution.id)
                    .where(Meeting.committee_id.in_(ids), ActionTakenReport.status == "submitted")
                    .group_by(Meeting.committee_id)
                )
            ).all()
        }
        names = await self.staff_names([x for r in rows for x in (r.chair_staff_id, r.secretary_staff_id)])
        mine = await self._my_roles(ids)
        out: list[CommitteeOut] = []
        for r in rows:
            q = dict(r.quorum_rule or {"type": "fraction", "value": "1/2"})
            out.append(
                CommitteeOut(
                    id=r.id,
                    name=r.name,
                    committee_type=r.committee_type,
                    code=committee_code(r),
                    college_id=r.college_id,
                    department_id=r.department_id,
                    chair_staff_id=r.chair_staff_id,
                    chair_name=names.get(r.chair_staff_id) if r.chair_staff_id else None,
                    secretary_staff_id=r.secretary_staff_id,
                    secretary_name=names.get(r.secretary_staff_id) if r.secretary_staff_id else None,
                    constituted_on=r.constituted_on,
                    valid_to=r.valid_to,
                    valid=bool(r.is_active) and (r.valid_to is None or r.valid_to >= today),
                    quorum_rule={k: v for k, v in q.items() if k != "code"},
                    is_active=r.is_active,
                    members=counts.get(r.id, 0),
                    my_role=mine.get(r.id),
                    next_meeting=nxt.get(r.id),
                    open_resolutions=open_res.get(r.id, 0),
                    pending_atrs=pending.get(r.id, 0),
                )
            )
        return out

    async def _my_roles(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        sid = await self.my_staff_id()
        if self.actor_id is None:
            return {}
        conds = [CommitteeMember.user_id == self.actor_id]
        if sid is not None:
            conds.append(CommitteeMember.staff_id == sid)
        rows = await self.db.execute(
            select(CommitteeMember.committee_id, CommitteeMember.role).where(
                CommitteeMember.committee_id.in_(ids), or_(*conds)
            )
        )
        out: dict[uuid.UUID, str] = {r[0]: r[1] for r in rows.all()}
        if sid is not None:
            for c in (await self.db.execute(select(Committee).where(Committee.id.in_(ids)))).scalars():
                if c.chair_staff_id == sid:
                    out[c.id] = "chair"
                elif c.secretary_staff_id == sid:
                    out[c.id] = "secretary"
        return out

    async def list_committees(
        self, committee_type: str | None = None, college_id: uuid.UUID | None = None, active: bool | None = None
    ) -> list[CommitteeOut]:
        stmt = select(Committee).where(Committee.institution_id == self.inst)
        ids = await self.visible_committee_ids()
        if ids is not None:
            stmt = stmt.where(Committee.id.in_(ids or [uuid.uuid4()]))
        if committee_type:
            stmt = stmt.where(Committee.committee_type == committee_type)
        if college_id:
            stmt = stmt.where(Committee.college_id == college_id)
        if active is not None:
            stmt = stmt.where(Committee.is_active.is_(active))
        rows = (await self.db.execute(stmt.order_by(Committee.committee_type, Committee.name))).scalars().all()
        return await self.outs(list(rows))

    async def mine(self) -> list[CommitteeOut]:
        ids = set(await self.my_committee_ids()) | await self.owned_committee_ids()
        if not ids:
            return []
        rows = (
            await self.db.execute(
                select(Committee).where(Committee.id.in_(ids), Committee.is_active.is_(True)).order_by(Committee.name)
            )
        ).scalars()
        return await self.outs(list(rows))

    async def detail(self, cid: uuid.UUID) -> CommitteeDetail:
        from app.services.governance.meeting_service import MeetingService

        c = await self.committee(cid)
        await self.committee_visible(c)
        base = (await self.outs([c]))[0]
        meetings = await MeetingService(self.db, self.principal, self.request, self.inst).list_meetings(
            committee_id=c.id, limit=50
        )
        return CommitteeDetail(
            **base.model_dump(),
            member_list=await self.members(c.id, include_past=True),
            history=list((await self.meta("committee", c.id)).get("history") or []),
            meetings=meetings,
        )

    async def members(self, cid: uuid.UUID, include_past: bool = False) -> list[MemberOut]:
        c = await self.committee(cid)
        await self.committee_visible(c)
        rows = list(
            (
                await self.db.execute(
                    select(CommitteeMember)
                    .where(CommitteeMember.committee_id == c.id)
                    .order_by(CommitteeMember.role, CommitteeMember.from_on)
                )
            )
            .scalars()
            .all()
        )
        today = await self.today()
        if not include_past:
            rows = [r for r in rows if r.to_on is None or r.to_on >= today]
        staff = await self.staff_names([r.staff_id for r in rows])
        users = await self.user_display([r.user_id for r in rows])
        return [
            MemberOut(
                id=r.id,
                committee_id=r.committee_id,
                member_type=r.member_type,
                staff_id=r.staff_id,
                user_id=r.user_id,
                name=(staff.get(r.staff_id) if r.staff_id else None)
                or (users.get(r.user_id) if r.user_id else None)
                or ((r.external or {}).get("name") if r.external else None),
                organisation=(r.external or {}).get("org") if r.external else None,
                role=r.role,
                from_on=r.from_on,
                to_on=r.to_on,
                active=_active(r, today),
            )
            for r in rows
        ]

    # ---- write --------------------------------------------------------------------------------------------------------
    def _require_admin(self) -> None:
        self.require_writer()
        if not self.has_any("governance", "manage", "committees"):
            raise forbidden("governance:manage required")

    async def create(self, body: CommitteeIn) -> CommitteeOut:
        self._require_admin()
        if not self.admin() and body.college_id and body.college_id not in self.college_ids():
            raise forbidden("Outside your college")
        data = body.model_dump(exclude={"quorum_rule"})
        q = body.quorum_rule.model_dump() if body.quorum_rule else {"type": "fraction", "value": "1/2"}
        q["code"] = TYPE_CODES.get(body.committee_type, "CMT")
        c = Committee(institution_id=self.inst, quorum_rule=q, **data)
        self.db.add(c)
        await self.db.flush()
        await self._audit("create", ENTITY, c.id, None, {"name": c.name, "type": c.committee_type})
        await self._emit(
            "governance.committee_created",
            {"committee_id": str(c.id), "committee_type": c.committee_type, "name": c.name},
            ENTITY,
            c.id,
        )
        return (await self.outs([c]))[0]

    async def templates(self) -> list[CommitteeTemplateOut]:
        inst = (await self.db.execute(select(Institution).where(Institution.id == self.inst))).scalar_one()
        return [
            CommitteeTemplateOut(
                template_key=k, name=n, committee_type=t, code=code, quorum_rule=q, per_department=per_dept
            )
            for k, n, t, code, q, per_dept in committee_templates(getattr(inst, "institution_type", None))
        ]

    async def from_template(self, body: CommitteeFromTemplate) -> CommitteeOut:
        tpl = next((t for t in await self.templates() if t.template_key == body.template_key), None)
        if tpl is None:
            raise not_found(f"Committee template {body.template_key}")
        name = tpl.name
        if tpl.per_department:
            if body.department_id is None:
                raise rule("A Board of Studies needs a department", "DEPARTMENT_REQUIRED", 422)
            codes = await self.department_codes([body.department_id])
            name = f"{tpl.name} — {codes.get(body.department_id, '')}".strip(" —")
        from app.schemas.governance import QuorumRule

        out = await self.create(
            CommitteeIn(
                name=name,
                committee_type=tpl.committee_type,  # type: ignore[arg-type]
                college_id=body.college_id,
                department_id=body.department_id,
                chair_staff_id=body.chair_staff_id,
                secretary_staff_id=body.secretary_staff_id,
                constituted_on=body.constituted_on or await self.today(),
                valid_to=body.valid_to,
                quorum_rule=QuorumRule(**tpl.quorum_rule),
            )
        )
        c = await self.committee(out.id)
        c.quorum_rule = {**(c.quorum_rule or {}), "code": tpl.code, "template_key": tpl.template_key}
        for sid, role in ((body.chair_staff_id, "chair"), (body.secretary_staff_id, "secretary")):
            if sid:
                self.db.add(
                    CommitteeMember(
                        institution_id=self.inst,
                        committee_id=c.id,
                        member_type="staff",
                        staff_id=sid,
                        user_id=await self.staff_user(sid),
                        role=role,
                        from_on=c.constituted_on,
                        to_on=c.valid_to,
                    )
                )
        await self.db.flush()
        return (await self.outs([c]))[0]

    async def update(self, cid: uuid.UUID, body: CommitteeUpdate) -> CommitteeOut:
        c = await self.committee(cid, lock=True)
        await self.require_committee_manager(c)
        old = {"name": c.name, "valid_to": str(c.valid_to), "is_active": c.is_active}
        data = body.model_dump(exclude_unset=True)
        if "quorum_rule" in data and data["quorum_rule"] is not None:
            data["quorum_rule"] = {**data["quorum_rule"], "code": committee_code(c)}
        for k, v in data.items():
            setattr(c, k, v)
        await self.db.flush()
        await self._audit("update", ENTITY, c.id, old, {k: str(v) for k, v in data.items()})
        return (await self.outs([c]))[0]

    async def reconstitute(self, cid: uuid.UUID, body: CommitteeReconstitute) -> CommitteeDetail:
        """New tenure: current members end the day before ``constituted_on`` (history kept), carried-over members get a
        fresh membership row, the new members are added."""
        c = await self.committee(cid, lock=True)
        await self.require_committee_manager(c)
        if c.constituted_on and body.constituted_on <= c.constituted_on:
            raise rule("The new tenure must start after the current one", "INVALID_TENURE", 422)
        end = body.constituted_on - timedelta(days=1)
        current = [
            m
            for m in (
                await self.db.execute(select(CommitteeMember).where(CommitteeMember.committee_id == c.id))
            ).scalars()
            if m.to_on is None or m.to_on >= body.constituted_on
        ]
        carried = {m.id for m in current if m.id in set(body.carry_over_member_ids)}
        for m in current:
            m.to_on = end
            if m.id in carried:
                self.db.add(
                    CommitteeMember(
                        institution_id=self.inst,
                        committee_id=c.id,
                        member_type=m.member_type,
                        staff_id=m.staff_id,
                        user_id=m.user_id,
                        external=m.external,
                        role=m.role,
                        from_on=body.constituted_on,
                        to_on=body.valid_to,
                    )
                )
        meta = await self.meta("committee", c.id)
        hist = list(meta.get("history") or [])
        hist.append(
            {
                "constituted_on": str(c.constituted_on) if c.constituted_on else None,
                "valid_to": str(end),
                "chair_staff_id": str(c.chair_staff_id) if c.chair_staff_id else None,
                "secretary_staff_id": str(c.secretary_staff_id) if c.secretary_staff_id else None,
                "members": len(current),
                "closed_at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
            }
        )
        meta["history"] = hist
        await self.put_meta("committee", c.id, meta)
        c.constituted_on, c.valid_to, c.is_active = body.constituted_on, body.valid_to, True
        if body.chair_staff_id:
            c.chair_staff_id = body.chair_staff_id
        if body.secretary_staff_id:
            c.secretary_staff_id = body.secretary_staff_id
        await self.db.flush()
        for new in body.members:
            await self.add_member(c.id, new.model_copy(update={"from_on": new.from_on or body.constituted_on}))
        await self._audit("reconstitute", ENTITY, c.id, None, {"constituted_on": str(body.constituted_on)})
        await self._emit(
            "governance.committee_reconstituted",
            {"committee_id": str(c.id), "constituted_on": str(body.constituted_on)},
            ENTITY,
            c.id,
        )
        return await self.detail(c.id)

    async def add_member(self, cid: uuid.UUID, body: MemberIn) -> MemberOut:
        c = await self.committee(cid, lock=True)
        await self.require_committee_manager(c)
        if body.member_type == "external":
            if body.external is None:
                raise rule("External members need name / organisation details", "NO_MEMBER", 422)
        elif not (body.staff_id or body.user_id):
            raise rule("A member needs staff_id or user_id", "NO_MEMBER", 422)
        user_id = body.user_id or await self.staff_user(body.staff_id)
        dup = (
            await self.db.execute(
                select(CommitteeMember.id).where(
                    CommitteeMember.committee_id == c.id,
                    or_(CommitteeMember.to_on.is_(None), CommitteeMember.to_on >= (body.from_on or date.today())),
                    (CommitteeMember.staff_id == body.staff_id)
                    if body.staff_id
                    else (CommitteeMember.user_id == user_id)
                    if user_id
                    else CommitteeMember.id.is_(None),
                )
            )
        ).first()
        if dup is not None:
            raise rule("Already a current member", "DUPLICATE_MEMBER")
        m = CommitteeMember(
            institution_id=self.inst,
            committee_id=c.id,
            member_type=body.member_type,
            staff_id=body.staff_id,
            user_id=user_id,
            external=body.external.model_dump() if body.external else None,
            role=body.role,
            from_on=body.from_on or c.constituted_on,
            to_on=body.to_on or c.valid_to,
        )
        self.db.add(m)
        await self.db.flush()
        if body.role == "chair" and body.staff_id:
            c.chair_staff_id = body.staff_id
        if body.role == "secretary" and body.staff_id:
            c.secretary_staff_id = body.staff_id
        await self._emit(
            "governance.member_added",
            {"committee_id": str(c.id), "member_id": str(m.id), "member_type": m.member_type},
            ENTITY,
            c.id,
        )
        return next(x for x in await self.members(c.id, include_past=True) if x.id == m.id)

    async def _member(self, mid: uuid.UUID) -> tuple[CommitteeMember, Committee]:
        m = (
            await self.db.execute(
                select(CommitteeMember).where(CommitteeMember.id == mid, CommitteeMember.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if m is None:
            raise not_found("Committee member")
        return m, await self.committee(m.committee_id, lock=True)

    async def update_member(self, mid: uuid.UUID, body: MemberUpdate) -> MemberOut:
        m, c = await self._member(mid)
        await self.require_committee_manager(c)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(m, k, v)
        await self.db.flush()
        return next(x for x in await self.members(c.id, include_past=True) if x.id == m.id)

    async def remove_member(self, mid: uuid.UUID) -> None:
        """Ends the tenure today (history stays) — rows are never deleted once a meeting recorded attendance."""
        m, c = await self._member(mid)
        await self.require_committee_manager(c)
        m.to_on = await self.today()
        await self.db.flush()
        await self._emit("governance.member_removed", {"committee_id": str(c.id), "member_id": str(m.id)}, ENTITY, c.id)

    # ---- coverage / tenure ----------------------------------------------------------------------------------------------
    async def coverage(self) -> list[CoverageItem]:
        today = await self.today()
        rows = list((await self.db.execute(select(Committee).where(Committee.institution_id == self.inst))).scalars())
        outs = {o.id: o for o in await self.outs(rows)}
        inst = (await self.db.execute(select(Institution).where(Institution.id == self.inst))).scalar_one()
        types = list(
            dict.fromkeys(
                [*MANDATORY_COMMITTEES, *(t[2] for t in committee_templates(getattr(inst, "institution_type", None)))]
            )
        )
        items: list[CoverageItem] = []
        for t in types:
            found = [r for r in rows if r.committee_type == t and r.is_active]
            best = next((r for r in found if r.valid_to is None or r.valid_to >= today), found[0] if found else None)
            items.append(
                CoverageItem(
                    committee_type=t,
                    mandatory=t in MANDATORY_COMMITTEES,
                    present=best is not None,
                    committee_id=best.id if best else None,
                    name=best.name if best else None,
                    valid=bool(best) and (best.valid_to is None or best.valid_to >= today),  # type: ignore[union-attr]
                    valid_to=best.valid_to if best else None,
                    members=outs[best.id].members if best else 0,
                )
            )
        return items

    async def tenure_expiry(self) -> int:
        """Monthly Beat: memberships ending within 30 days → the secretary / administrators are reminded."""
        today = await self.today()
        horizon = today + timedelta(days=30)
        rows = (
            await self.db.execute(
                select(CommitteeMember.committee_id, func.count(), func.min(CommitteeMember.to_on))
                .where(
                    CommitteeMember.institution_id == self.inst,
                    CommitteeMember.to_on >= today,
                    CommitteeMember.to_on <= horizon,
                )
                .group_by(CommitteeMember.committee_id)
            )
        ).all()
        n = 0
        for cid, count, to_on in rows:
            c = await self.committee(cid)
            users = [await self.staff_user(c.secretary_staff_id)] if c.secretary_staff_id else []
            users += await self.role_users("registrar")
            await self._notify(
                "governance.member_tenure",
                users,
                {"committee": c.name, "to_on": str(to_on), "count": int(count)},
            )
            n += 1
        return n
