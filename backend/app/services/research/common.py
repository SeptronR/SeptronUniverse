"""Shared plumbing of the Phase 30 services (publications, patents / FDP / awards, projects, consultancy, ethics,
incentives, MoUs / collaborations / incubation, API score, profile & stats) — on the Phase 27 ``SupportBase`` (people
lookups, department predicates, committee membership, the ``institution_settings`` side store, ScopeTabs).

**Visibility** (Prompts/30 "Visibility rules" / §30.5): *self* through the staff row of the caller
(``staff_id = principal.staff_id``), an author tag (``publications.authors[].staff_id``) or ``scholar_id``; ownership
for projects (``pi_staff_id`` / ``co_pi[].staff_id``), MoUs (``coordinator_staff_id``) and ethics applications
(committee membership through ``committee_members`` of the bound Phase 33 committee, or ``ethics_committees.members``);
department scope through ``staff.department_id`` (HOD holding ``research:view_all`` / ``verify`` at department
scope); college scope through ``staff.college_id`` (``college_admin``); institution-wide for ``research:view_all`` /
``manage`` at institution scope (research cell, dean / principal-level readers, IQAC, auditor). Faculty hold
``research:manage`` at *self* scope, so writes beyond their own records require the institution scope (the research
cell). The auditor reads everything and writes nothing.

Side-store kinds (category ``research_meta``): ``pub:<id>`` (verification level / history / remarks, import source,
change requests), ``project:<id>`` (reports, staff, expense requests, ethics category, closure checklist, workflow),
``consultancy:<id>`` (receipts, share override, invoices), ``ethics:<id>`` (category, protocol, reviews, conditions,
amendments, renewals, adverse events, workflow), ``incentive:<id>`` (computed eligible amount, decisions, disbursement),
``mou:<id>`` (workflow, versions, alert sent), ``startup:<id>`` (stage history, funding rounds), ``patent:<id>``
(history), ``award:<id>`` (verified), ``fdp:<id>`` (event link), ``api:<staff>:<period>`` (API snapshots, mirrored in
``institution_settings['research.api_snapshots']``), ``import:<token>`` (import previews).
"""

import re
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import String, cast, false, or_, select, true

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
    "ResearchBase",
    "all_access",
    "dept_subquery",
    "forbidden",
    "is_auditor",
    "module_reader",
    "normalise_doi",
    "not_found",
    "now_utc",
    "rule",
    "rupees",
    "scope_ids",
]

META = "research_meta"
R = "research"
_DOI = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.I)


def normalise_doi(doi: str | None) -> str | None:
    """``https://doi.org/10.1000/ABC`` / ``doi:10.1000/abc`` → ``10.1000/abc`` (DOIs are case-insensitive)."""
    if not doi:
        return None
    d = _DOI.sub("", doi.strip()).strip().lower()
    return d or None


def rupees(paise: int | None) -> str:
    return f"{(paise or 0) / 100:,.2f}"


def staff_name(s: Staff | None) -> str | None:
    return " ".join(x for x in (s.first_name, s.last_name) if x) if s is not None else None


class ResearchBase(SupportBase):
    audit_module = R
    module = R
    meta_category = META

    # ---- roles ------------------------------------------------------------------------------------------------------
    def cell(self, action: str | None = None) -> bool:
        """The research cell: ``research:manage`` (or the named bespoke action) at institution scope."""
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return True
        if is_auditor(p):
            return False
        acts = ("manage",) if action is None else (action, "manage")
        return any(p.has(R, a) for a in acts) and all_access(p, R)

    def require_cell(self, action: str | None = None) -> None:
        self.require_writer()
        if not self.cell(action):
            raise forbidden(f"research:{action or 'manage'} required")

    def reader_all(self) -> bool:
        return all_access(self.principal, R)

    def dept_reader(self) -> bool:
        p = self.principal
        return bool(scope_ids(p, "department") or scope_ids(p, "faculty")) and module_reader(p, R)

    def verifier(self) -> bool:
        p = self.principal
        return p is None or bool(getattr(p, "is_super_admin", False)) or p.has(R, "verify")

    def money_reader(self) -> bool:
        """Accountants reach project / consultancy money and incentive disbursement through ``accounting:*``."""
        p = self.principal
        return (
            p is None
            or bool(getattr(p, "is_super_admin", False))
            or any(p.has("accounting", a) for a in ("view_all", "manage", "post"))
        )

    def visibility(self, *, self_tab: bool = True, own_tab: bool = False) -> dict[str, Any]:
        tabs = [t for t in visibility_scopes(self.principal, R) if t != "self"]
        return {"self": self_tab, "scopes": tabs, "default": tabs[-1] if tabs else ("own" if own_tab else "self")}

    # ---- people -----------------------------------------------------------------------------------------------------
    async def require_my_staff(self) -> Staff:
        s = await self.my_staff()
        if s is None:
            raise rule("Your account is not linked to a staff record", "NO_STAFF", 403)
        return s

    async def staff_row(self, sid: uuid.UUID) -> Staff:
        s = (
            await self.db.execute(select(Staff).where(Staff.id == sid, Staff.institution_id == self.inst))
        ).scalar_one_or_none()
        if s is None:
            raise not_found("Staff")
        return s

    async def staff_map(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, Staff]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        return {s.id: s for s in (await self.db.execute(select(Staff).where(Staff.id.in_(wanted)))).scalars()}

    def staff_scope_subquery(self, scope: str | None = None) -> Any:
        """Staff ids the caller reads beyond self: department (HOD), college (``college_admin``)."""
        p = self.principal
        parts: list[Any] = []
        if scope in (None, "department") and self.dept_reader():
            parts.append(Staff.department_id.in_(dept_subquery(p)))
        if scope in (None, "college") and scope_ids(p, "college") and module_reader(p, R):
            parts.append(Staff.college_id.in_(scope_ids(p, "college")))
        if not parts:
            return None
        return select(Staff.id).where(Staff.institution_id == self.inst, or_(*parts))

    async def owned_predicate(
        self,
        staff_col: Any,
        *,
        scope: str | None = None,
        json_col: Any = None,
        json_key: str = "staff_id",
        extra_self: Sequence[Any] = (),
    ) -> Any:
        """Self / department / college / all over a staff id column (+ a JSON list of ``{staff_id}`` tags)."""
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return true()
        if scope in (None, "all") and self.reader_all():
            return true()
        parts: list[Any] = []
        if scope in (None, "self", "mine", "own"):
            mine = await self.my_staff_id()
            if mine is not None:
                parts.append(staff_col == mine)
                if json_col is not None:
                    parts.append(json_col.contains([{json_key: str(mine)}]))
            parts += list(extra_self)
        sub = self.staff_scope_subquery(scope)
        if sub is not None:
            parts.append(staff_col.in_(sub))
        return or_(*parts) if parts else false()

    async def is_mine(self, staff_id: uuid.UUID | None, tags: list[dict[str, Any]] | None = None) -> bool:
        mine = await self.my_staff_id()
        if mine is None:
            return False
        if staff_id == mine:
            return True
        return any(str(t.get("staff_id")) == str(mine) for t in (tags or []) if isinstance(t, dict))

    async def in_my_units(self, staff_id: uuid.UUID | None) -> bool:
        if staff_id is None:
            return False
        sub = self.staff_scope_subquery()
        if sub is None:
            return False
        return (await self.db.execute(sub.where(Staff.id == staff_id))).first() is not None

    async def can_read_staff(self, staff_id: uuid.UUID | None, tags: list[dict[str, Any]] | None = None) -> bool:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False) or self.reader_all():
            return True
        return await self.is_mine(staff_id, tags) or await self.in_my_units(staff_id)

    async def resolve_staff_param(self, staff_id: str | uuid.UUID | None) -> uuid.UUID | None:
        """``staff_id=self`` / ``me`` → the caller's staff id."""
        if staff_id in (None, ""):
            return None
        if str(staff_id) in ("self", "me"):
            return (await self.require_my_staff()).id
        try:
            return uuid.UUID(str(staff_id))
        except ValueError as exc:
            raise rule("staff_id must be a UUID or 'self'", "BAD_STAFF", 422) from exc

    # ---- settings -----------------------------------------------------------------------------------------------------
    async def json_setting(self, key: str, default: Any) -> Any:
        v = await self.setting(R, key)
        return v if v is not None else default

    def text_like(self, col: Any, q: str) -> Any:
        return cast(col, String).ilike(f"%{q.strip()}%")
