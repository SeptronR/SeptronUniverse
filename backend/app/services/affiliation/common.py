"""Shared plumbing of the Phase 34 services (registry, applications, programme approvals, fees, submissions, exam
centres, dashboards) on the Phase 33 ``GovernanceBase`` (people lookups, workflow start / act, ``documents.render``, the
``institution_settings`` side store). This module is the ``affiliation_repository`` of Prompts/34 §34.5: the visibility
predicates live here and the services narrow every query through them.

**Visibility** (Prompts/34 "Visibility rules"):

* **college scope is primary** — ``college_admin`` / ``principal`` / ``college_exam_coordinator`` (role assignments of
  scope ``college``) see the rows of their colleges only (``affiliation:apply`` / ``submit`` / ``view``);
* the **university office** (``affiliation:manage`` / ``view_all`` at institution scope: registrar, VC, COE, IQAC,
  auditor) sees everything; only ``affiliation:manage`` (never the auditor) writes office actions;
* **inspection committee members** (``affiliation:inspect``) own the applications whose ``inspection_committee``
  names their staff id (assigned inspections only);
* **dean / HOD** (faculty / department scope) read applications and programme approvals of the programmes in their
  units (``programs.faculty_id`` / ``department_id``) — read only;
* the accountant reaches dues through ``accounting:view`` / ``fees:view_all``.

Side-store kinds (category ``affiliation_meta``): ``app:<id>`` (number, remarks, scrutiny trail, missing documents,
inspection mode / recommendation / rounds, decision, order document, fee lines, timeline), ``college:<id>`` (documents
vault, last inspection, type history, compliance), ``sub:<id>`` (version, source, payload, validation report, versions,
timeline), ``centre:<id>`` (appointment letter, routed counts), ``approval:<id>`` (change trail),
``reminded:<kind>:<id>`` (one-shot reminder markers).
"""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import and_, false, or_, select, true

from app.enums.affiliation import DEFAULT_AFFILIATION_SETTINGS
from app.models.academic import AcademicTerm, AcademicYear, Program
from app.models.platform import College, Department, Role, UserRole
from app.services.governance.common import (
    GovernanceBase,
    all_access,
    forbidden,
    is_auditor,
    module_reader,
    not_found,
    now_utc,
    rule,
    scope_ids,
)

__all__ = [
    "M",
    "pairs",
    "AffiliationBase",
    "forbidden",
    "is_auditor",
    "not_found",
    "now_utc",
    "rule",
]

META = "affiliation_meta"
M = "affiliation"


def pairs(rows: Any) -> dict[Any, int]:
    """``(key, count)`` rows → ``{key: int(count)}``."""
    return {k: int(v or 0) for k, v in rows}


class AffiliationBase(GovernanceBase):
    audit_module = M
    module = M
    meta_category = META

    # ---- settings -----------------------------------------------------------------------------------------------------
    async def aff_setting(self, key: str) -> Any:
        v = await self.setting("affiliation", key)
        return DEFAULT_AFFILIATION_SETTINGS.get(f"affiliation.{key}") if v is None else v

    async def aff_int(self, key: str) -> int:
        v = await self.aff_setting(key)
        try:
            return int(v)
        except (TypeError, ValueError):
            return int(DEFAULT_AFFILIATION_SETTINGS.get(f"affiliation.{key}") or 0)

    async def soft_feature(self, key: str) -> bool:
        try:
            return await self.feature(key)
        except KeyError:
            return False

    # ---- roles --------------------------------------------------------------------------------------------------------
    def office(self) -> bool:
        """University affiliation office: ``affiliation:manage`` at institution scope (never the auditor)."""
        return self.admin(M)

    def office_reader(self) -> bool:
        return self.reader_all(M)

    def decider(self) -> bool:
        p = self.principal
        return self.system() or (not is_auditor(p) and p.has(M, "decide"))

    def exam_office(self) -> bool:
        """COE: ``exams:configure`` / ``exams:manage`` at institution scope (accept / lock exam submissions, centres)."""
        p = self.principal
        if self.system():
            return True
        return not is_auditor(p) and any(p.has("exams", a) for a in ("configure", "manage")) and all_access(p, "exams")

    def verifier(self) -> bool:
        p = self.principal
        return self.system() or (not is_auditor(p) and (p.has(M, "verify_submission") or self.office()))

    def my_college_ids(self) -> list[uuid.UUID]:
        p = self.principal
        if p is None:
            return []
        if not any(p.has(M, a) for a in ("apply", "submit", "view", "manage", "view_all")):
            return []
        return scope_ids(p, "college")

    def college_writer(self, college_id: uuid.UUID, action: str) -> bool:
        p = self.principal
        if self.system():
            return True
        if is_auditor(p):
            return False
        return college_id in scope_ids(p, "college") and (p.has(M, action) or p.has(M, "manage"))

    async def unit_program_ids(self) -> list[uuid.UUID] | None:
        """Programmes of the caller's faculties / departments (dean / HOD read); ``None`` when not a unit reader."""
        p = self.principal
        if p is None:
            return None
        depts, faculties = scope_ids(p, "department"), scope_ids(p, "faculty")
        if not (depts or faculties) or not module_reader(p, M):
            return None
        cond = []
        if depts:
            cond.append(Program.department_id.in_(depts))
        if faculties:
            cond.append(Program.faculty_id.in_(faculties))
            cond.append(Program.department_id.in_(select(Department.id).where(Department.faculty_id.in_(faculties))))
        return list(
            (await self.db.execute(select(Program.id).where(Program.institution_id == self.inst, or_(*cond))))
            .scalars()
            .all()
        )

    async def unit_college_ids(self) -> list[uuid.UUID]:
        progs = await self.unit_program_ids()
        if not progs:
            return []
        return list(
            (await self.db.execute(select(Program.college_id).where(Program.id.in_(progs)).distinct())).scalars().all()
        )

    async def college_predicate(self, col: Any, *, include_units: bool = True) -> Any:
        """Rows by college: everything for the office readers, own colleges for college roles, unit colleges for
        deans / HODs (read)."""
        if self.system() or self.office_reader():
            return true()
        ids = set(self.my_college_ids())
        if include_units:
            ids |= set(await self.unit_college_ids())
        return col.in_(list(ids)) if ids else false()

    async def visible_college(self, college_id: uuid.UUID) -> College:
        c = await self.college(college_id)
        if self.system() or self.office_reader():
            return c
        if college_id in self.my_college_ids() or college_id in await self.unit_college_ids():
            return c
        raise not_found("College")

    # ---- lookups ------------------------------------------------------------------------------------------------------
    async def college(self, cid: uuid.UUID, *, lock: bool = False) -> College:
        stmt = select(College).where(
            College.id == cid, College.institution_id == self.inst, College.deleted_at.is_(None)
        )
        if lock:
            stmt = stmt.with_for_update()
        c = (await self.db.execute(stmt)).scalar_one_or_none()
        if c is None:
            raise not_found("College")
        return c

    async def colleges_map(self, ids: Sequence[uuid.UUID | None] | None = None) -> dict[uuid.UUID, College]:
        stmt = select(College).where(College.institution_id == self.inst, College.deleted_at.is_(None))
        if ids is not None:
            wanted = list({i for i in ids if i})
            if not wanted:
                return {}
            stmt = stmt.where(College.id.in_(wanted))
        return {c.id: c for c in (await self.db.execute(stmt)).scalars()}

    async def programs_map(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, Program]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        return {p.id: p for p in (await self.db.execute(select(Program).where(Program.id.in_(wanted)))).scalars()}

    async def years_map(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, AcademicYear]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        return {
            y.id: y for y in (await self.db.execute(select(AcademicYear).where(AcademicYear.id.in_(wanted)))).scalars()
        }

    async def year(self, yid: uuid.UUID) -> AcademicYear:
        y = (
            await self.db.execute(
                select(AcademicYear).where(AcademicYear.id == yid, AcademicYear.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if y is None:
            raise not_found("Academic year")
        return y

    async def current_year_row(self) -> AcademicYear | None:
        rows = list(
            (
                await self.db.execute(
                    select(AcademicYear)
                    .where(AcademicYear.institution_id == self.inst)
                    .order_by(AcademicYear.is_current.desc(), AcademicYear.start_date.desc())
                    .limit(1)
                )
            ).scalars()
        )
        return rows[0] if rows else None

    async def year_for_date(self, d: date) -> AcademicYear | None:
        return (
            await self.db.execute(
                select(AcademicYear)
                .where(
                    AcademicYear.institution_id == self.inst,
                    and_(AcademicYear.start_date <= d, AcademicYear.end_date >= d),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    async def term(self, tid: uuid.UUID) -> AcademicTerm:
        t = (
            await self.db.execute(
                select(AcademicTerm).where(AcademicTerm.id == tid, AcademicTerm.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if t is None:
            raise not_found("Academic term")
        return t

    async def college_users(self, college_id: uuid.UUID | None, *slugs: str) -> list[uuid.UUID]:
        """Holders of ``slugs`` assigned at the college's scope (principal / college admin / exam coordinator)."""
        if college_id is None:
            return []
        rows = await self.db.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                Role.slug.in_(slugs or ("college_admin",)),
                UserRole.scope_type == "college",
                UserRole.scope_id == college_id,
            )
        )
        return list({r[0] for r in rows.all()})

    async def office_users(self) -> list[uuid.UUID]:
        return list(dict.fromkeys(await self.role_users("registrar")))

    async def principal_user(self, c: College) -> uuid.UUID | None:
        if c.principal_staff_id:
            u = await self.staff_user(c.principal_staff_id)
            if u:
                return u
        users = await self.college_users(c.id, "college_admin")
        return users[0] if users else None

    async def notify_college(self, c: College, event_type: str, context: dict[str, Any], *slugs: str) -> None:
        users = await self.college_users(c.id, *(slugs or ("college_admin",)))
        pu = await self.principal_user(c)
        await self._notify(event_type, [*users, pu], {"college": c.name, **context})

    def today_iso(self) -> str:
        return now_utc().date().isoformat()
