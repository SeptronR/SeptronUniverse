"""Shared plumbing of the Phase 32 services (frameworks, metrics, evidence, cycles, submissions, audits, consistency,
disclosures, dashboard) — on the Phase 27 ``SupportBase`` (people lookups, permissions, the ``institution_settings``
side store). This module is the ``accreditation_repository`` of Prompts/32 §32.5.

**Visibility** (Prompts/32 "Visibility rules"): IQAC (``accreditation:manage`` at institution scope) and the
institution-wide readers (principal / dean ``view_all``, auditor / peer team read-only) see everything; ``college_admin``
narrows metric values / cycles to ``college_id``; HODs (department scope) see metric values whose ``program_id``
belongs to their departments (and department recomputes in drill-down), evidence uploaded by their department's staff
and responses owned by their department's staff; faculty see the responses they own and the evidence they uploaded;
module officers (registrar / CoE / accountant / placement) read their own module's metrics. The auditor writes nothing.

Side-store kinds (category ``accreditation_meta``): ``override:<value id>`` (pending proposal, stale auto value,
verification trail), ``evidence:<id>`` (version history, size, source suggestion), ``suggestion:<id>`` (inbox rows),
``response:<id>`` (versions, due date, review trail, best practice / distinctiveness structure), ``cycle:<id>``
(status history, exports), ``submission:<id>`` (supersedes / corrections, generated file), ``consistency:<period>``,
``disclosures:feed``, ``custom_criteria`` is the setting ``accreditation.custom_criteria``.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from app.enums.accreditation import DEFAULT_ACCREDITATION_SETTINGS, FRAMEWORK_FEATURES
from app.models.academic import Program
from app.models.accreditation import AccreditationFramework, FrameworkCriterion, MetricDefinition
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
    "AccreditationBase",
    "all_access",
    "dept_subquery",
    "forbidden",
    "is_auditor",
    "module_reader",
    "not_found",
    "now_utc",
    "rule",
    "scope_ids",
    "staff_name",
    "visibility_scopes",
    "word_count",
]

META = "accreditation_meta"
M = "accreditation"

# module officers read the metrics of their own module (``source_module``)
OFFICER_MODULES: dict[str, tuple[str, ...]] = {
    "registrar": ("students", "admissions", "academics", "affiliation"),
    "controller_of_examinations": ("results",),
    "accountant": ("accounting", "fees"),
    "placement_officer": ("placement",),
    "librarian": ("library",),
    "obe_coordinator": ("obe", "results"),
    "research_cell": ("research", "phd"),
}


def staff_name(s: Staff | None) -> str | None:
    return " ".join(x for x in (s.first_name, s.last_name) if x) if s is not None else None


def word_count(text: str | None) -> int:
    import re

    if not text:
        return 0
    plain = re.sub(r"<[^>]+>", " ", text)
    return len([w for w in plain.split() if w.strip()])


class AccreditationBase(SupportBase):
    audit_module = M
    module = M
    meta_category = META

    # ---- settings -----------------------------------------------------------------------------------------------------
    async def acc_setting(self, key: str) -> Any:
        v = await self.setting(M, key)
        return DEFAULT_ACCREDITATION_SETTINGS.get(key) if v is None else v

    # ---- roles --------------------------------------------------------------------------------------------------------
    def system(self) -> bool:
        p = self.principal
        return p is None or bool(getattr(p, "is_super_admin", False))

    def iqac(self, action: str | None = None) -> bool:
        """IQAC: ``accreditation:manage`` (or the named bespoke action) at institution scope (or college for
        ``college_admin``)."""
        p = self.principal
        if self.system():
            return True
        if is_auditor(p):
            return False
        acts = ("manage",) if action is None else (action, "manage")
        return any(p.has(M, a) for a in acts) and (all_access(p, M) or bool(scope_ids(p, "college")))

    def require_iqac(self, action: str | None = None) -> None:
        self.require_writer()
        if not self.iqac(action):
            raise forbidden(f"accreditation:{action or 'manage'} required")

    def reader_all(self) -> bool:
        return self.system() or all_access(self.principal, M)

    def verifier(self) -> bool:
        """Principal / dean (``accreditation:approve``) or IQAC verify overrides and lock values."""
        p = self.principal
        return self.system() or (not is_auditor(p) and (p.has(M, "approve") or self.iqac()))

    def roles(self) -> list[str]:
        return list(getattr(self.principal, "roles", None) or [])

    def officer_modules(self) -> set[str]:
        out: set[str] = set()
        for r in self.roles():
            out.update(OFFICER_MODULES.get(r, ()))
        return out

    def dept_ids(self) -> list[uuid.UUID] | None:
        """Departments of a department-scoped reader (None = not department scoped)."""
        p = self.principal
        if self.reader_all() or p is None:
            return None
        depts = scope_ids(p, "department")
        return depts or None

    def college_ids(self) -> list[uuid.UUID] | None:
        p = self.principal
        if self.reader_all() or p is None:
            return None
        return scope_ids(p, "college") or None

    async def resolved_dept_ids(self) -> list[uuid.UUID] | None:
        """Departments of a department / faculty-scoped reader, resolved to ids (faculty scope → its departments)."""
        p = self.principal
        if self.reader_all() or p is None:
            return None
        if not (scope_ids(p, "department") or scope_ids(p, "faculty")):
            return None
        sub = dept_subquery(p)
        if isinstance(sub, list):
            return list(sub)
        return list((await self.db.execute(sub)).scalars().all())

    async def dept_program_ids(self, depts: Sequence[uuid.UUID]) -> list[uuid.UUID]:
        if not depts:
            return []
        return list(
            (
                await self.db.execute(
                    select(Program.id).where(Program.institution_id == self.inst, Program.department_id.in_(depts))
                )
            )
            .scalars()
            .all()
        )

    async def dept_staff_ids(self, depts: Sequence[uuid.UUID]) -> list[uuid.UUID]:
        if not depts:
            return []
        return list(
            (
                await self.db.execute(
                    select(Staff.id).where(Staff.institution_id == self.inst, Staff.department_id.in_(depts))
                )
            )
            .scalars()
            .all()
        )

    async def dept_user_ids(self, depts: Sequence[uuid.UUID]) -> list[uuid.UUID]:
        if not depts:
            return []
        return [
            u
            for u in (
                await self.db.execute(
                    select(Staff.user_id).where(Staff.institution_id == self.inst, Staff.department_id.in_(depts))
                )
            )
            .scalars()
            .all()
            if u
        ]

    def visibility(self, *, self_tab: bool = False, own_tab: bool = True) -> dict[str, Any]:
        tabs = [t for t in visibility_scopes(self.principal, M) if t not in ("self",)]
        if self.dept_ids() and "department" not in tabs:
            tabs.insert(0, "department")
        lead = ["own"] if own_tab and not self.reader_all() and not tabs else []
        scopes = lead + tabs
        return {"self": self_tab, "scopes": scopes, "default": scopes[-1] if scopes else "own"}

    # ---- frameworks ---------------------------------------------------------------------------------------------------
    async def framework(self, code_or_id: str | uuid.UUID) -> AccreditationFramework:
        stmt = select(AccreditationFramework)
        if isinstance(code_or_id, uuid.UUID):
            stmt = stmt.where(AccreditationFramework.id == code_or_id)
        else:
            stmt = stmt.where(AccreditationFramework.code == str(code_or_id).upper())
        fw = (await self.db.execute(stmt)).scalar_one_or_none()
        if fw is None:
            raise not_found("Framework")
        return fw

    async def framework_enabled(self, fw: AccreditationFramework) -> bool:
        key = FRAMEWORK_FEATURES.get(fw.code)
        return bool(fw.is_active) and (key is None or await self.feature(key))

    async def require_framework(self, fw: AccreditationFramework) -> None:
        key = FRAMEWORK_FEATURES.get(fw.code)
        if key:
            await self.require_feature(key)

    async def criteria(self, framework_id: uuid.UUID) -> list[FrameworkCriterion]:
        return list(
            (
                await self.db.execute(
                    select(FrameworkCriterion)
                    .where(FrameworkCriterion.framework_id == framework_id)
                    .order_by(FrameworkCriterion.sequence, FrameworkCriterion.code)
                )
            )
            .scalars()
            .all()
        )

    async def criterion_by_code(self, framework_id: uuid.UUID, code: str) -> FrameworkCriterion:
        c = (
            await self.db.execute(
                select(FrameworkCriterion).where(
                    FrameworkCriterion.framework_id == framework_id, FrameworkCriterion.code == code
                )
            )
        ).scalar_one_or_none()
        if c is None:
            raise not_found(f"Criterion {code}")
        return c

    async def definitions_by_key(self) -> dict[str, MetricDefinition]:
        return {d.key: d for d in (await self.db.execute(select(MetricDefinition))).scalars()}

    async def definition(self, key: str) -> MetricDefinition:
        d = (await self.db.execute(select(MetricDefinition).where(MetricDefinition.key == key))).scalar_one_or_none()
        if d is None:
            raise not_found(f"Metric {key}")
        return d

    # ---- people ---------------------------------------------------------------------------------------------------------
    async def staff_names(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        return {
            s.id: staff_name(s) or ""
            for s in (await self.db.execute(select(Staff).where(Staff.id.in_(wanted)))).scalars()
        }

    async def iqac_users(self) -> list[uuid.UUID]:
        return await self.role_users("iqac_coordinator")
