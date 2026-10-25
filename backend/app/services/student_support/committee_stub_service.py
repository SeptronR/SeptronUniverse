"""Committees stub — Prompts/27 §27.6 ``committee_stub_service`` ({governance.committees}).

Minimal ``committees`` / ``committee_members`` CRUD (``governance:committees``) so grievance and discipline
committees can be constituted before Phase 33 replaces it (same tables — no data migration).
"""

import uuid

from sqlalchemy import func, select

from app.models.post_result import Committee, CommitteeMember
from app.schemas.clubs import GovCommitteeIn, GovCommitteeMemberIn, GovCommitteeMemberOut, GovCommitteeOut
from app.services.student_support.common import SupportBase, forbidden, not_found, rule


class CommitteeStubService(SupportBase):
    audit_module = "governance"
    module = "governance"

    async def outs(self, rows: list[Committee]) -> list[GovCommitteeOut]:
        counts = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(CommitteeMember.committee_id, func.count())
                    .where(CommitteeMember.committee_id.in_([r.id for r in rows] or [uuid.uuid4()]))
                    .group_by(CommitteeMember.committee_id)
                )
            ).all()
        }
        staff = await self.staff_cards([r.chair_staff_id for r in rows])
        return [
            GovCommitteeOut(
                id=r.id,
                name=r.name,
                committee_type=r.committee_type,
                college_id=r.college_id,
                department_id=r.department_id,
                chair_staff_id=r.chair_staff_id,
                chair_name=staff.get(r.chair_staff_id, {}).get("name") if r.chair_staff_id else None,
                secretary_staff_id=r.secretary_staff_id,
                constituted_on=r.constituted_on,
                valid_to=r.valid_to,
                is_active=r.is_active,
                members=counts.get(r.id, 0),
            )
            for r in rows
        ]

    async def list_committees(self, committee_type: str | None) -> list[GovCommitteeOut]:
        stmt = select(Committee).where(Committee.institution_id == self.inst)
        if committee_type:
            stmt = stmt.where(Committee.committee_type == committee_type)
        rows = (await self.db.execute(stmt.order_by(Committee.committee_type, Committee.name))).scalars().all()
        return await self.outs(list(rows))

    async def create(self, body: GovCommitteeIn) -> GovCommitteeOut:
        self.require_writer()
        if not self.can("governance", "committees"):
            raise forbidden("governance:committees required")
        c = Committee(institution_id=self.inst, **body.model_dump())
        self.db.add(c)
        await self.db.flush()
        await self._audit("create", "committee", c.id, None, {"name": c.name, "type": c.committee_type})
        return (await self.outs([c]))[0]

    async def _committee(self, cid: uuid.UUID) -> Committee:
        c = (
            await self.db.execute(select(Committee).where(Committee.id == cid, Committee.institution_id == self.inst))
        ).scalar_one_or_none()
        if c is None:
            raise not_found("Committee")
        return c

    async def members(self, cid: uuid.UUID) -> list[GovCommitteeMemberOut]:
        c = await self._committee(cid)
        rows = list(
            (await self.db.execute(select(CommitteeMember).where(CommitteeMember.committee_id == c.id))).scalars().all()
        )
        staff = await self.staff_cards([r.staff_id for r in rows])
        users = await self.user_display([r.user_id for r in rows])
        return [
            GovCommitteeMemberOut(
                id=r.id,
                committee_id=r.committee_id,
                member_type=r.member_type,
                staff_id=r.staff_id,
                user_id=r.user_id,
                name=(staff.get(r.staff_id, {}).get("name") if r.staff_id else None)
                or (users.get(r.user_id) if r.user_id else None)
                or ((r.external or {}).get("name") if r.external else None),
                role=r.role,
                from_on=r.from_on,
                to_on=r.to_on,
            )
            for r in rows
        ]

    async def add_member(self, cid: uuid.UUID, body: GovCommitteeMemberIn) -> GovCommitteeMemberOut:
        self.require_writer()
        if not self.can("governance", "committees"):
            raise forbidden("governance:committees required")
        c = await self._committee(cid)
        if not (body.staff_id or body.user_id or body.external):
            raise rule("A member needs staff_id, user_id or external details", "NO_MEMBER")
        user_id = body.user_id or await self.staff_user(body.staff_id)
        m = CommitteeMember(
            institution_id=self.inst,
            committee_id=c.id,
            member_type=body.member_type,
            staff_id=body.staff_id,
            user_id=user_id,
            external=body.external,
            role=body.role,
            from_on=body.from_on,
            to_on=body.to_on,
        )
        self.db.add(m)
        await self.db.flush()
        return next(x for x in await self.members(c.id) if x.id == m.id)
