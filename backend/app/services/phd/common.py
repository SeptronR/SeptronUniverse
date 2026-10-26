"""Shared plumbing of the Phase 31 services (scholars, coursework, DC, progress, fellowships, requests, thesis, examiners,
viva, award, ETD, stats) — on the Phase 27 ``SupportBase`` (people lookups, enrolment department predicates, the
``institution_settings`` side store, ScopeTabs). This module is the ``phd_repository`` of Prompts/31 §31.5: every
scholar-scoped read goes through :meth:`PhdBase.scholar_predicate` / :meth:`PhdBase.scholar`.

**Visibility** (Prompts/31 "Visibility rules"): *self* through ``research_scholars.student_program_enrollment_id →
students.user_id`` (``phd:self``); **guide ownership** ``guide_staff_id | co_guide_staff_id = principal.staff_id``;
**DC-member ownership** through ``doctoral_committees.members[].staff_id`` (JSON containment); department / faculty
scope through the enrolment department (HOD / dean holding ``phd:view_all`` / ``dc`` at those scopes); college scope
through the enrolment college (``college_admin``); institution-wide for ``phd:view_all`` / ``manage`` at institution
scope (research cell, IQAC, auditor). A scholar outside the caller's reach answers 404. Examiner identities are
projected out for the scholar until the viva is held when ``phd.rules.hide_examiners_from_scholar`` is set. Faculty
hold ``phd:guide`` at *self* scope — writes beyond their own scholars need the research cell (``phd:manage`` at
institution scope). The auditor reads everything and writes nothing.

Side-store kinds (category ``phd_meta``): ``scholar:<id>`` (timeline, relaxation, cancellation-review flag / streak,
ethics approval link, registration letter, warnings sent), ``coursework:<id>`` (plan, exemption, deadline warning),
``dc:<id>`` (Phase 33 committee link), ``dcm:<meeting id>`` (agenda, attendance, kind, approval), ``progress:<id>``
(DC remarks, meeting link), ``fellowship:<id>`` (HRA, contingency claims used, upgrade source), ``disb:<id>`` (kind,
hold reason, arrears, bills, payment request), ``request:<id>`` (NOC, decisions, implications), ``thesis:<id>``
(AI declaration, abstract / keywords, workflow, certificate, flags, award workflow), ``examiner:<id>`` (token, due date,
COI, dispatch link, replacement), ``viva:<id>`` (open defence, re-viva count, attendance), ``etd:<id>`` (embargo,
error), ``token:<hash>`` (examiner token → examiner id).
"""

import hashlib
import secrets
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import false, or_, select, true

from app.enums.phd import DEFAULT_PHD_RULES
from app.models.hr import FacultyProfile, Staff
from app.models.phd import DoctoralCommittee, ResearchScholar
from app.models.students import Student, StudentProgramEnrollment
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
    "PhdBase",
    "add_months",
    "all_access",
    "dept_subquery",
    "forbidden",
    "is_auditor",
    "module_reader",
    "months_between",
    "not_found",
    "now_utc",
    "rule",
    "rupees",
    "scope_ids",
    "staff_name",
]

META = "phd_meta"
M = "phd"


def rupees(paise: int | None) -> str:
    return f"{(paise or 0) / 100:,.2f}"


def staff_name(s: Staff | None) -> str | None:
    return " ".join(x for x in (s.first_name, s.last_name) if x) if s is not None else None


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return date(year, month, 28)


def months_between(a: date, b: date) -> int:
    """Whole months from ``a`` to ``b`` (negative when ``b`` is earlier)."""
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def cadre_key(cadre: str | None) -> str | None:
    c = (cadre or "").lower()
    if "assoc" in c:
        return "associate"
    if "assist" in c:
        return "assistant"
    if "prof" in c:
        return "professor"
    return None


class PhdBase(SupportBase):
    audit_module = M
    module = M
    meta_category = META

    # ---- rules --------------------------------------------------------------------------------------------------------
    async def rules(self) -> dict[str, Any]:
        """``institution_settings['phd.rules']`` over the shipped defaults (the IN pack values)."""
        configured = await self.setting(M, "rules")
        out = dict(DEFAULT_PHD_RULES)
        if isinstance(configured, dict):
            out.update(configured)
        return out

    async def rule_int(self, key: str) -> int:
        return int((await self.rules()).get(key) or DEFAULT_PHD_RULES.get(key) or 0)

    # ---- roles --------------------------------------------------------------------------------------------------------
    def system(self) -> bool:
        p = self.principal
        return p is None or bool(getattr(p, "is_super_admin", False))

    def cell(self, action: str | None = None) -> bool:
        """The research cell: ``phd:manage`` (or the named bespoke action) at institution scope."""
        p = self.principal
        if self.system():
            return True
        if is_auditor(p):
            return False
        acts = ("manage",) if action is None else (action, "manage")
        return any(p.has(M, a) for a in acts) and all_access(p, M)

    def require_cell(self, action: str | None = None) -> None:
        self.require_writer()
        if not self.cell(action):
            raise forbidden(f"phd:{action or 'manage'} required")

    def approver(self) -> bool:
        """HOD / dean / research cell at their scope (request and panel steps)."""
        p = self.principal
        return self.system() or (not is_auditor(p) and (p.has(M, "approve") or p.has(M, "manage")))

    def unit_reader(self) -> bool:
        p = self.principal
        if p is None:
            return False
        return bool(scope_ids(p, "department") or scope_ids(p, "faculty") or scope_ids(p, "college")) and (
            module_reader(p, M) or p.has(M, "dc")
        )

    def visibility(self, *, self_tab: bool = False, own_tab: bool = True) -> dict[str, Any]:
        tabs = [t for t in visibility_scopes(self.principal, M) if t not in ("self", "own")]
        p = self.principal
        lead = ["own"] if own_tab and p is not None and (p.has(M, "guide") or p.has(M, "dc")) else []
        scopes = lead + tabs
        return {"self": self_tab, "scopes": scopes, "default": scopes[-1] if scopes else ("own" if own_tab else "self")}

    # ---- people -------------------------------------------------------------------------------------------------------
    async def my_scholar(self) -> ResearchScholar | None:
        st = await self.my_student()
        if st is None:
            return None
        return (
            await self.db.execute(
                select(ResearchScholar)
                .join(
                    StudentProgramEnrollment,
                    StudentProgramEnrollment.id == ResearchScholar.student_program_enrollment_id,
                )
                .where(StudentProgramEnrollment.student_id == st.id, ResearchScholar.institution_id == self.inst)
                .order_by(ResearchScholar.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def require_my_scholar(self) -> ResearchScholar:
        s = await self.my_scholar()
        if s is None:
            raise rule("Your account is not linked to a research scholar record", "NO_SCHOLAR", 403)
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

    async def scholar_user(self, s: ResearchScholar) -> uuid.UUID | None:
        return (
            await self.db.execute(
                select(Student.user_id)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.id == s.student_program_enrollment_id)
            )
        ).scalar_one_or_none()

    async def scholar_name(self, s: ResearchScholar) -> str:
        cards = await self.enrollment_cards([s.student_program_enrollment_id])
        return str((cards.get(s.student_program_enrollment_id) or {}).get("name") or "Research scholar")

    async def guide_users(self, s: ResearchScholar) -> list[uuid.UUID]:
        out = [await self.staff_user(s.guide_staff_id)]
        if s.co_guide_staff_id:
            out.append(await self.staff_user(s.co_guide_staff_id))
        return [u for u in out if u]

    # ---- visibility (phd_repository) ----------------------------------------------------------------------------------
    async def scholar_predicate(self, scope: str | None = None) -> Any:
        """Self / own (guide, co-guide, DC member) / department / faculty / college / all."""
        p = self.principal
        if self.system():
            return true()
        if scope in (None, "all") and all_access(p, M):
            return true()
        parts: list[Any] = []
        if scope in (None, "self", "mine"):
            mine = await self.my_scholar()
            if mine is not None:
                parts.append(ResearchScholar.id == mine.id)
        if scope in (None, "own", "mine"):
            sid = await self.my_staff_id()
            if sid is not None:
                parts += [
                    ResearchScholar.guide_staff_id == sid,
                    ResearchScholar.co_guide_staff_id == sid,
                    ResearchScholar.id.in_(
                        select(DoctoralCommittee.scholar_id).where(
                            DoctoralCommittee.institution_id == self.inst,
                            DoctoralCommittee.members.contains([{"staff_id": str(sid)}]),
                        )
                    ),
                ]
        if scope in (None, "department", "faculty", "college") and self.unit_reader():
            parts += self.enrolment_dept_predicate(
                ResearchScholar.student_program_enrollment_id, None if scope == "faculty" else scope
            )
        return or_(*parts) if parts else false()

    def enrolment_dept_predicate(self, col: Any, scope: str | None = None) -> list[Any]:
        """Department / faculty / college widening for holders of ``phd:view_all`` or ``phd:dc`` at those scopes."""
        p = self.principal
        parts: list[Any] = []
        if p is None or not (module_reader(p, M) or p.has(M, "dc")):
            return parts
        if scope in (None, "department") and (scope_ids(p, "department") or scope_ids(p, "faculty")):
            parts.append(
                col.in_(
                    select(StudentProgramEnrollment.id).where(
                        StudentProgramEnrollment.department_id.in_(dept_subquery(p))
                    )
                )
            )
        if scope in (None, "college") and scope_ids(p, "college"):
            parts.append(
                col.in_(
                    select(StudentProgramEnrollment.id).where(
                        StudentProgramEnrollment.college_id.in_(scope_ids(p, "college"))
                    )
                )
            )
        return parts

    async def scholar(self, sid: uuid.UUID, *, lock: bool = False) -> ResearchScholar:
        stmt = select(ResearchScholar).where(
            ResearchScholar.id == sid,
            ResearchScholar.institution_id == self.inst,
            await self.scholar_predicate(),
        )
        if lock:
            stmt = stmt.with_for_update(of=ResearchScholar)
        s = (await self.db.execute(stmt)).scalar_one_or_none()
        if s is None:
            raise not_found("Research scholar")
        return s

    async def scholar_raw(self, sid: uuid.UUID, *, lock: bool = False) -> ResearchScholar:
        stmt = select(ResearchScholar).where(ResearchScholar.id == sid, ResearchScholar.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        s = (await self.db.execute(stmt)).scalar_one_or_none()
        if s is None:
            raise not_found("Research scholar")
        return s

    async def dc_members(self, scholar_id: uuid.UUID) -> list[dict[str, Any]]:
        dc = (
            await self.db.execute(select(DoctoralCommittee).where(DoctoralCommittee.scholar_id == scholar_id))
        ).scalar_one_or_none()
        return list(dc.members or []) if dc is not None else []

    async def relation(self, s: ResearchScholar) -> list[str]:
        """How the caller relates to the scholar: self | guide | co_guide | dc | convenor | unit | all."""
        out: list[str] = []
        if self.system() or all_access(self.principal, M):
            out.append("all")
        mine = await self.my_scholar()
        if mine is not None and mine.id == s.id:
            out.append("self")
        sid = await self.my_staff_id()
        if sid is not None:
            if s.guide_staff_id == sid:
                out.append("guide")
            if s.co_guide_staff_id == sid:
                out.append("co_guide")
            for m in await self.dc_members(s.id):
                if str(m.get("staff_id")) == str(sid):
                    out.append("convenor" if m.get("role") == "convenor" else "dc")
        if "all" not in out and self.unit_reader():
            preds = self.enrolment_dept_predicate(ResearchScholar.student_program_enrollment_id)
            if preds:
                hit = (
                    await self.db.execute(select(ResearchScholar.id).where(ResearchScholar.id == s.id, or_(*preds)))
                ).first()
                if hit is not None:
                    out.append("unit")
        return out

    async def require_relation(self, s: ResearchScholar, *allowed: str, write: bool = True) -> list[str]:
        if write:
            self.require_writer()
        rel = await self.relation(s)
        if self.cell() or any(r in rel for r in allowed):
            return rel
        raise forbidden(f"Only the {' / '.join(allowed) or 'research cell'} or the research cell may do this")

    async def is_guide_of(self, s: ResearchScholar) -> bool:
        sid = await self.my_staff_id()
        return sid is not None and sid in (s.guide_staff_id, s.co_guide_staff_id)

    async def is_self(self, s: ResearchScholar) -> bool:
        mine = await self.my_scholar()
        return mine is not None and mine.id == s.id

    # ---- guide load ---------------------------------------------------------------------------------------------------
    async def guide_max(self, staff_id: uuid.UUID, *, lock: bool = False) -> tuple[int, str | None]:
        """``faculty_profiles.max_scholars`` when set, else the cadre rule of ``phd.rules.guide_load_by_cadre``."""
        stmt = select(FacultyProfile).where(FacultyProfile.staff_id == staff_id)
        if lock:
            stmt = stmt.with_for_update()
        fp = (await self.db.execute(stmt)).scalar_one_or_none()
        staff = (await self.db.execute(select(Staff).where(Staff.id == staff_id))).scalar_one_or_none()
        cadre = (fp.cadre if fp is not None else None) or (getattr(staff, "cadre", None) if staff else None)
        if fp is not None and fp.max_scholars:
            return int(fp.max_scholars), cadre
        table = (await self.rules()).get("guide_load_by_cadre") or {}
        key = cadre_key(cadre)
        return int(table.get(key) or min(table.values(), default=4)), cadre

    async def guide_current(self, staff_id: uuid.UUID, *, exclude: uuid.UUID | None = None) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).where(
            ResearchScholar.institution_id == self.inst,
            ResearchScholar.guide_staff_id == staff_id,
            ResearchScholar.status.not_in(("awarded", "discontinued")),
        )
        if exclude is not None:
            stmt = stmt.where(ResearchScholar.id != exclude)
        return int((await self.db.execute(stmt)).scalar_one())

    async def check_guide_load(self, staff_id: uuid.UUID, *, exclude: uuid.UUID | None = None) -> None:
        """``FOR UPDATE`` on the guide's ``faculty_profiles`` row, then ``current < max`` (409 GUIDE_LOAD_EXCEEDED)."""
        mx, cadre = await self.guide_max(staff_id, lock=True)
        cur = await self.guide_current(staff_id, exclude=exclude)
        if cur >= mx:
            raise rule(
                f"The guide already supervises {cur} of {mx} scholars",
                "GUIDE_LOAD_EXCEEDED",
                409,
                staff_id=str(staff_id),
                current=cur,
                max=mx,
                cadre=cadre,
            )

    # ---- documents ----------------------------------------------------------------------------------------------------
    async def render_doc(
        self,
        template_type: str,
        entity_type: str,
        entity_id: uuid.UUID,
        variables: dict[str, Any] | None = None,
        *,
        allow_multiple: bool = False,
    ) -> uuid.UUID | None:
        """Phase 26 ``documents.render`` — skipped (``None``) while ``documents.templates`` is off."""
        if not await self.feature("documents.templates"):
            return None
        from app.core.errors import APIError
        from app.services.documents.render_service import render

        try:
            res = await render(
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
        return res.issued_document_id

    async def scholar_timeline(self, s: ResearchScholar, action: str, **extra: Any) -> None:
        await self.timeline("scholar", s.id, action, **extra)
