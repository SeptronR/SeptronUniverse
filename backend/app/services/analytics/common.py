"""Shared plumbing of the Phase 35 services (charts, dashboards, read models, KPIs, early-warning analytics) — on the
Phase 27 ``SupportBase`` (people lookups, mentor / advisee ownership, the ``institution_settings`` side store).

This module is the ``analytics_repository`` of Prompts/35 §35.5: :meth:`AnalyticsBase.resolve_scope` turns the caller
and a requested ScopeTab into a :class:`~app.core.charts.ResolvedScope` that never exceeds the caller's
``meta.visibility`` for the chart's **source module** (silently narrowed — ``?scope=all`` from an HOD becomes
``department``), and :func:`app.services.analytics.predicates.scope_sql` maps it onto the dimension columns of the read
models / source tables.

* institution-wide holders of ``<module>:view_all|manage`` → ``all``; ``college_admin`` (college scope) → ``college``;
  HOD / dean (department / faculty scope with ``view_all``) → ``department``;
* everyone else → ``self``: own enrolments (student), consented wards (parent — ``student_guardians.portal_access``),
  mentees / advisees / students of own offerings and the offerings themselves (faculty, class advisor, mentor), own
  staff row, wardens' hostels (and residents);
* IQAC / auditor read aggregates only (drill-down rows withheld unless ``<module>:view_pii``).

Side-store kinds (category ``analytics_meta``): ``layout:<role>`` (institution dashboard layout), ``targets:<college or
all>`` (KPI targets), ``alert:<kpi>:<college or all>`` (open breach), ``kpi_history:<college or all>`` (daily values, 120
days), ``digest:<id>`` (schedules), ``intervention_alert:<enrolment>`` (last reminder).
"""

import uuid
from typing import Any

from sqlalchemy import select, text

from app.core.charts import ResolvedScope
from app.models.mentoring import MentorAssignment
from app.models.offerings import CourseOfferingFaculty
from app.services.student_support.common import (
    SupportBase,
    all_access,
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
    "AnalyticsBase",
    "ROLE_PRIORITY",
    "all_access",
    "forbidden",
    "is_auditor",
    "module_reader",
    "not_found",
    "now_utc",
    "rule",
    "scope_ids",
    "visibility_scopes",
]

META = "analytics_meta"

# highest first — the dashboard of the principal's highest role is shown unless ?role= picks another one they hold
ROLE_PRIORITY: tuple[str, ...] = (
    "super_admin",
    "institution_admin",
    "vice_chancellor",
    "registrar",
    "controller_of_examinations",
    "college_admin",
    "dean",
    "hod",
    "iqac_coordinator",
    "auditor",
    "accountant",
    "hr_officer",
    "admissions_officer",
    "placement_officer",
    "exam_cell",
    "research_cell",
    "alumni_coordinator",
    "hostel_warden",
    "librarian",
    "transport_manager",
    "estate_officer",
    "class_advisor",
    "research_guide",
    "faculty",
    "guest_faculty",
    "research_scholar",
    "student",
    "parent",
    "alumni",
    "recruiter",
    "applicant",
)

_LEVELS = ("self", "department", "college", "all")


class AnalyticsBase(SupportBase):
    audit_module = "analytics"
    module = "analytics"
    meta_category = META

    _own_cache: dict[str, Any] | None = None

    # ---- roles ------------------------------------------------------------------------------------------------------
    def roles(self) -> list[str]:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return ["institution_admin"]
        return list(getattr(p, "roles", None) or [])

    def primary_role(self, requested: str | None = None) -> str:
        held = self.roles()
        if requested and requested in held:
            return requested
        if requested and not held:
            return requested
        for slug in ROLE_PRIORITY:
            if slug in held:
                return slug
        return held[0] if held else "student"

    def is_student(self) -> bool:
        return "student" in self.roles() and not self.staffish()

    def is_parent(self) -> bool:
        return "parent" in self.roles() and not self.staffish()

    def staffish(self) -> bool:
        return any(r not in ("student", "parent", "alumni", "applicant", "recruiter", "learner") for r in self.roles())

    def aggregates_only(self, module: str) -> bool:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return False
        audit = is_auditor(p) or ("iqac_coordinator" in (getattr(p, "roles", None) or []))
        return audit and not p.has(module, "view_pii")

    # ---- ownership ----------------------------------------------------------------------------------------------------
    async def own(self) -> dict[str, Any]:
        """Own rows of the caller (cached per service instance)."""
        if self._own_cache is not None:
            return self._own_cache
        out: dict[str, Any] = {"enrollments": set(), "offerings": set(), "staff_id": None, "hostels": set()}
        if self.principal is None:
            self._own_cache = out
            return out
        out["enrollments"] |= set(await self.my_enrollment_ids())
        out["enrollments"] |= set(await self.ward_enrollment_ids())
        staff_id = await self.my_staff_id()
        out["staff_id"] = staff_id
        if staff_id is not None:
            mentees = await self.db.execute(
                select(MentorAssignment.student_program_enrollment_id).where(
                    MentorAssignment.mentor_staff_id == staff_id, MentorAssignment.status == "active"
                )
            )
            out["enrollments"] |= {r[0] for r in mentees.all()}
            adv = await self.db.execute(self.advisee_subquery(staff_id))
            out["enrollments"] |= {r[0] for r in adv.all()}
            offs = await self.db.execute(
                select(CourseOfferingFaculty.offering_id).where(CourseOfferingFaculty.staff_id == staff_id)
            )
            out["offerings"] = {r[0] for r in offs.all()}
            if out["offerings"]:
                rows = await self.db.execute(
                    text(
                        "SELECT DISTINCT student_program_enrollment_id FROM attendance_summaries "
                        "WHERE offering_id = ANY(:o)"
                    ),
                    {"o": list(out["offerings"])},
                )
                out["enrollments"] |= {r[0] for r in rows.all()}
            hostels = await self.db.execute(
                text(
                    "SELECT id FROM hostels WHERE institution_id = :i AND warden_staff_id = :s AND deleted_at IS NULL"
                ),
                {"i": self.inst, "s": staff_id},
            )
            out["hostels"] = {r[0] for r in hostels.all()}
            if out["hostels"]:
                res = await self.db.execute(
                    text(
                        "SELECT student_program_enrollment_id FROM hostel_allocations "
                        "WHERE hostel_id = ANY(:h) AND status IN ('allotted', 'checked_in')"
                    ),
                    {"h": list(out["hostels"])},
                )
                out["enrollments"] |= {r[0] for r in res.all()}
        self._own_cache = out
        return out

    async def department_ids(self) -> list[uuid.UUID]:
        p = self.principal
        depts = scope_ids(p, "department")
        faculties = scope_ids(p, "faculty")
        if faculties:
            rows = await self.db.execute(
                text("SELECT id FROM departments WHERE institution_id = :i AND faculty_id = ANY(:f)"),
                {"i": self.inst, "f": faculties},
            )
            depts = list({*depts, *(r[0] for r in rows.all())})
        return depts

    # ---- scope ------------------------------------------------------------------------------------------------------
    def allowed_levels(self, module: str) -> list[str]:
        """``meta.visibility`` of the module mapped onto chart levels (``self`` always first)."""
        tabs = visibility_scopes(self.principal, module)
        levels = ["self"] + [t for t in tabs if t in ("department", "college", "all")]
        if "faculty" in tabs and "department" not in levels:
            levels.insert(1, "department")
        return levels

    async def resolve_scope(self, module: str, requested: str | None = None) -> ResolvedScope:
        allowed = self.allowed_levels(module)
        want = {"mine": "self", "own": "self", "wards": "self", "faculty": "department"}.get(requested or "", requested)
        level = want if want in allowed else allowed[-1]
        s = ResolvedScope(level=level, module=module, allowed=allowed, aggregates_only=self.aggregates_only(module))
        p = self.principal
        if level == "college":
            s.college_ids = scope_ids(p, "college")
        elif level == "department":
            s.department_ids = await self.department_ids()
        elif level == "self":
            own = await self.own()
            s.enrollment_ids = sorted(own["enrollments"], key=str)
            s.offering_ids = sorted(own["offerings"], key=str)
            s.staff_id = own["staff_id"]
            s.hostel_ids = sorted(own["hostels"], key=str)
        return s

    def visibility_meta(self, module: str) -> dict[str, Any]:
        levels = self.allowed_levels(module)
        scopes = [lv for lv in levels if lv != "self"]
        if self.staffish() and scopes:
            scopes = ["own", *scopes]
        return {"self": not self.staffish(), "scopes": scopes, "default": scopes[-1] if scopes else "self"}

    # ---- permissions -------------------------------------------------------------------------------------------------
    def holds_any(self, perms: tuple[str, ...]) -> bool:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return True
        for spec in perms:
            module, _, action = spec.partition(":")
            if p.has(module, action):
                return True
        return False

    async def feature_on(self, key: str | None) -> bool:
        if not key:
            return True
        try:
            return await self.feature(key)
        except KeyError:
            return False

    # ---- settings -----------------------------------------------------------------------------------------------------
    async def a_setting(self, category: str, key: str, default: Any = None) -> Any:
        try:
            v = await self.setting(category, key)
        except Exception:  # noqa: BLE001 - unknown keys fall back to the documented default
            v = None
        return default if v is None else v

    async def platform_setting(self, key: str) -> Any:
        row = (await self.db.execute(text("SELECT value FROM platform_settings WHERE key = :k"), {"k": key})).first()
        return row[0] if row else None

    async def term_label(self, term_id: uuid.UUID | None) -> str:
        if term_id is None:
            return ""
        row = (await self.db.execute(text("SELECT name FROM academic_terms WHERE id = :t"), {"t": term_id})).first()
        return str(row[0]) if row else ""
