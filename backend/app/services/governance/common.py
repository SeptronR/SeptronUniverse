"""Shared plumbing of the Phase 33 services (committees, meetings / resolutions, legal, RTI, audit paras, e-File,
policies, stats) — on the Phase 27 ``SupportBase`` (people lookups, permissions, the ``institution_settings`` side store).
This module is the ``committee_repository`` / ``meeting_repository`` / … of Prompts/33 §33.5: visibility predicates
live here and the services narrow every query through them.

**Visibility** (Prompts/33 "Visibility rules"):

* committees / meetings / resolutions — governance administrators (``governance:manage`` at institution scope: registrar,
  institution admin, principal) and institution-wide readers (``governance:view_all``: IQAC, auditor) see everything;
  ``college_admin`` sees their college's committees; HODs / deans (department / faculty scope with ``view_all``) see
  their departments' BoS; the ``committee_secretary`` role (scope ``committee``) and the chair / secretary named on a
  committee own it; members (``committee_members.staff_id | user_id`` with a current tenure) see their committees.
  Draft minutes are visible to the secretary / chair / administrators only; approved minutes to every member.
* resolutions — additionally the action owner (``action_owner_staff_id``).
* legal — ``legal:manage`` (legal officer) and readers ``legal:view_all`` (registrar / principal / auditor); the case
  owner. Documents only with ``legal:manage``.
* RTI — ``rti:manage`` (PIO) and the assigned PIO; readers (``rti:view_all``) get the applicant masked.
* audit paras — ``governance:audit_paras`` (finance) / ``governance:manage``; the para owner; readers ``view_all``.
* e-File — creator, current holder and past holders; ``efile:manage`` / ``view_all`` at institution scope; college admins
  their college's creators.
* policies — approved policies readable by every authenticated user; drafts by their owner and policy managers
  (``governance:policies`` / ``manage``).

Side-store kinds (category ``governance_meta``): ``committee:<id>`` (tenure history), ``meeting:<id>`` (notice, agenda
freeze, minutes versions / corrigenda, approval trail, workflow id, minutes document), ``resolution:<id>`` (link trail),
``atr:<id>`` (decision remarks), ``legal:<id>`` (hearings, institution role, appeal link, counsel fee), ``rti:<id>``
(mode, fee, consultations, response text, appeal decision), ``para:<id>`` (replies, due date), ``efile:<id>`` (summary,
linked entity, reopen trail, workflow), ``policy:<id>`` (owner, summary, ack flag, supersession, publication,
acknowledgements, workflow), ``suggestions:<committee_type>`` (agenda suggestions fed by module events).
"""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import or_, select

from app.enums.governance import DEFAULT_GOVERNANCE_SETTINGS, TYPE_CODES
from app.models.governance import Committee, CommitteeMember
from app.models.hr import Staff
from app.services.student_support.common import (
    SupportBase,
    all_access,
    dept_subquery,
    forbidden,
    is_auditor,
    module_reader,
    not_found,
    now_utc,
    rule,
    scope_ids,
    visibility_scopes,
)

__all__ = [
    "GovernanceBase",
    "all_access",
    "committee_code",
    "dept_subquery",
    "forbidden",
    "is_auditor",
    "module_reader",
    "not_found",
    "now_utc",
    "rule",
    "scope_ids",
    "visibility_scopes",
]

META = "governance_meta"
M = "governance"


def committee_code(c: Committee) -> str:
    q = c.quorum_rule or {}
    return str(q.get("code") or TYPE_CODES.get(c.committee_type, "CMT"))


def quorum_required(rule_: dict[str, Any] | None, total: int) -> int:
    """``{type: fraction, value: "1/2"}`` → ceil(total × fraction) (at least 1); ``{type: count, value: "5"}``."""
    r = rule_ or {"type": "fraction", "value": "1/2"}
    try:
        if r.get("type") == "count":
            return max(1, int(r.get("value") or 1))
        num, _, den = str(r.get("value") or "1/2").partition("/")
        n, d = int(num), int(den or 1)
        return max(1, -(-total * n // d))
    except (TypeError, ValueError, ZeroDivisionError):
        return max(1, -(-total // 2))


class GovernanceBase(SupportBase):
    audit_module = M
    module = M
    meta_category = META

    # ---- settings -----------------------------------------------------------------------------------------------------
    async def gov_setting(self, dotted: str) -> Any:
        category, _, key = dotted.partition(".")
        v = await self.setting(category, key)
        return DEFAULT_GOVERNANCE_SETTINGS.get(dotted) if v is None else v

    async def gov_int(self, dotted: str) -> int:
        v = await self.gov_setting(dotted)
        try:
            return int(v)
        except (TypeError, ValueError):
            return int(DEFAULT_GOVERNANCE_SETTINGS.get(dotted) or 0)

    # ---- roles --------------------------------------------------------------------------------------------------------
    def system(self) -> bool:
        p = self.principal
        return p is None or bool(getattr(p, "is_super_admin", False))

    def has_any(self, module: str, *actions: str) -> bool:
        p = self.principal
        return self.system() or any(p.has(module, a) for a in actions)

    def admin(self, module: str = M) -> bool:
        """``<module>:manage`` at institution scope (registrar / institution admin / principal) — never the auditor."""
        p = self.principal
        if self.system():
            return True
        return not is_auditor(p) and p.has(module, "manage") and all_access(p, module)

    def reader_all(self, module: str = M) -> bool:
        return self.system() or all_access(self.principal, module)

    def college_ids(self) -> list[uuid.UUID]:
        p = self.principal
        return [] if p is None else scope_ids(p, "college")

    def secretary_scope(self) -> list[uuid.UUID]:
        """Committees a ``committee_secretary`` role assignment is scoped to (scope type ``committee``)."""
        p = self.principal
        return [] if p is None else scope_ids(p, "committee")

    async def dept_ids(self) -> list[uuid.UUID]:
        p = self.principal
        if p is None or not (scope_ids(p, "department") or scope_ids(p, "faculty")):
            return []
        if not module_reader(p, M):
            return []
        sub = dept_subquery(p)
        if isinstance(sub, list):
            return list(sub)
        return list((await self.db.execute(sub)).scalars().all())

    # ---- committee visibility -----------------------------------------------------------------------------------------
    async def owned_committee_ids(self) -> set[uuid.UUID]:
        """Committees the caller administers as secretary / chair (named or by ``committee`` scope)."""
        out = set(self.secretary_scope())
        sid = await self.my_staff_id()
        if sid is not None:
            rows = await self.db.execute(
                select(Committee.id).where(
                    Committee.institution_id == self.inst,
                    or_(Committee.chair_staff_id == sid, Committee.secretary_staff_id == sid),
                )
            )
            out |= {r[0] for r in rows.all()}
            rows = await self.db.execute(
                select(CommitteeMember.committee_id).where(
                    CommitteeMember.institution_id == self.inst,
                    CommitteeMember.staff_id == sid,
                    CommitteeMember.role.in_(("chair", "secretary", "convenor")),
                    or_(CommitteeMember.to_on.is_(None), CommitteeMember.to_on >= date.today()),
                )
            )
            out |= {r[0] for r in rows.all()}
        return out

    async def chair_committee_ids(self) -> set[uuid.UUID]:
        sid = await self.my_staff_id()
        if sid is None:
            return set()
        rows = await self.db.execute(
            select(Committee.id).where(Committee.institution_id == self.inst, Committee.chair_staff_id == sid)
        )
        out = {r[0] for r in rows.all()}
        rows = await self.db.execute(
            select(CommitteeMember.committee_id).where(
                CommitteeMember.institution_id == self.inst,
                CommitteeMember.staff_id == sid,
                CommitteeMember.role == "chair",
                or_(CommitteeMember.to_on.is_(None), CommitteeMember.to_on >= date.today()),
            )
        )
        return out | {r[0] for r in rows.all()}

    async def visible_committee_ids(self) -> list[uuid.UUID] | None:
        """``None`` = every committee of the institution; otherwise the ids the caller may read."""
        if self.reader_all():
            return None
        ids: set[uuid.UUID] = set(await self.my_committee_ids()) | await self.owned_committee_ids()
        if self.college_ids() and module_reader(self.principal, M):
            rows = await self.db.execute(
                select(Committee.id).where(
                    Committee.institution_id == self.inst, Committee.college_id.in_(self.college_ids())
                )
            )
            ids |= {r[0] for r in rows.all()}
        depts = await self.dept_ids()
        if depts:
            rows = await self.db.execute(
                select(Committee.id).where(Committee.institution_id == self.inst, Committee.department_id.in_(depts))
            )
            ids |= {r[0] for r in rows.all()}
        return list(ids)

    async def can_manage_committee(self, c: Committee) -> bool:
        if self.admin():
            return True
        if is_auditor(self.principal):
            return False
        if c.college_id and c.college_id in self.college_ids() and self.has_any(M, "manage"):
            return True
        return c.id in await self.owned_committee_ids()

    async def require_committee_manager(self, c: Committee) -> None:
        self.require_writer()
        if not await self.can_manage_committee(c):
            raise forbidden("Only the committee secretary / chair or a governance administrator may do this")

    async def committee(self, cid: uuid.UUID, *, lock: bool = False) -> Committee:
        stmt = select(Committee).where(Committee.id == cid, Committee.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        c = (await self.db.execute(stmt)).scalar_one_or_none()
        if c is None:
            raise not_found("Committee")
        return c

    async def committee_visible(self, c: Committee) -> None:
        ids = await self.visible_committee_ids()
        if ids is not None and c.id not in ids:
            raise not_found("Committee")

    # ---- people ---------------------------------------------------------------------------------------------------------
    async def staff_names(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        return {
            s.id: " ".join(x for x in (s.first_name, s.last_name) if x)
            for s in (await self.db.execute(select(Staff).where(Staff.id.in_(wanted)))).scalars()
        }

    async def user_of_role(self, slug: str, college_id: uuid.UUID | None = None) -> uuid.UUID | None:
        users = await self.role_users(slug)
        return users[0] if users else None

    async def reporting_head_user(self, user_id: uuid.UUID | None) -> uuid.UUID | None:
        """The holder's reporting head (Phase 06 ``staff.reports_to_staff_id``), else their HOD."""
        if user_id is None:
            return None
        s = (await self.db.execute(select(Staff).where(Staff.user_id == user_id))).scalar_one_or_none()
        if s is None:
            return None
        head = getattr(s, "reports_to_staff_id", None)
        if head:
            return await self.staff_user(head)
        if s.department_id:
            hods = await self.role_users("hod", s.department_id)
            return hods[0] if hods else None
        return None

    # ---- Phase 26 documents ---------------------------------------------------------------------------------------------
    async def render_doc(
        self,
        template_type: str,
        entity_type: str,
        entity_id: uuid.UUID,
        variables: dict[str, Any] | None = None,
        *,
        allow_multiple: bool = False,
    ) -> Any:
        """``documents.render`` → ``DocRenderResult`` (``None`` while ``documents.templates`` is off or rendering fails)."""
        if not await self.feature("documents.templates"):
            return None
        from app.core.errors import APIError
        from app.services.documents.render_service import render

        try:
            return await render(
                self.db,
                self.principal,
                template_type,
                entity_type,
                entity_id,
                institution_id=self.inst,
                variables_override=variables,
                allow_multiple=allow_multiple,
            )
        except APIError:
            return None

    async def start_workflow(
        self, key: str, entity_type: str, entity_id: uuid.UUID, title: str, context: dict[str, Any]
    ) -> uuid.UUID | None:
        """Start ``key`` when its definition is seeded for the tenant; ``None`` otherwise (direct decisions apply)."""
        from app.core.errors import APIError
        from app.core.workflow import engine as workflow_engine

        try:
            async with self.db.begin_nested():
                wf = await workflow_engine.start(
                    self.db,
                    institution_id=self.inst,
                    key=key,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    started_by=self.actor_id,
                    context=context,
                    title=title[:200],
                )
        except (APIError, LookupError, ValueError):
            return None
        return wf.id

    async def acted_on_workflow(self, instance_id: str | None, approve: bool, comment: str | None) -> bool:
        """Act on the caller's pending step of ``instance_id`` (the ``approved`` / ``rejected`` hooks finish the record);
        False when there is no open instance (direct decisions apply)."""
        if not instance_id:
            return False
        from app.core.workflow import engine as workflow_engine
        from app.models.platform import WorkflowInstance

        wf = (
            await self.db.execute(select(WorkflowInstance).where(WorkflowInstance.id == uuid.UUID(str(instance_id))))
        ).scalar_one_or_none()
        if wf is None or wf.status not in ("pending", "escalated"):
            return False
        await workflow_engine.act(
            self.db,
            instance_id=wf.id,
            actor=self.principal,
            decision="approve" if approve else "reject",
            comment=comment,
        )
        return True
