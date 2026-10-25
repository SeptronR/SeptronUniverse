"""Shared plumbing of the Phase 25 services (calendar, events, facilities) — on the Phase 07 ``StudentServiceBase``.

**Visibility** (Prompts/25 "Visibility rules"): every list is *self* first (``requested_by`` / ``raised_by`` /
``person_id`` / host / organiser), widened by ownership (assignee, coach, counsellor, custodian), then the caller's
departments (HOD — requester / organiser department), colleges (``college_admin``) and institution-wide holders of the
module's ``view_all`` / ``manage``. Health is never widened beyond counts for non-``health:record`` holders, and the
auditor (``ALL(view, view_all)``) is refused there explicitly.

Small facts the section 24 tables have no column for live in ``institution_settings`` rows of category
``facilities_meta`` keyed ``<kind>:<id>`` (event registration settings / report, ticket timeline / cost / AMC link,
equipment handover, SOS timeline, visitor notifications, health certificates).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.errors import APIError, ErrorCode
from app.models.hr import Staff
from app.models.platform import Department, InstitutionSetting, User
from app.models.students import Student, StudentProgramEnrollment
from app.services.students.common import StudentServiceBase

META = "facilities_meta"


def now_utc() -> datetime:
    return datetime.now(UTC)


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def not_found(what: str) -> APIError:
    return APIError(404, ErrorCode.NOT_FOUND, f"{what} not found")


def forbidden(message: str = "Insufficient permissions") -> APIError:
    return APIError(403, ErrorCode.PERMISSION_DENIED, message)


def scope_ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def institution_scope(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def has(p: Any, module: str, *actions: str) -> bool:
    if p is None or getattr(p, "is_super_admin", False):
        return True
    return any(p.has(module, a) for a in actions)


def module_reader(p: Any, module: str) -> bool:
    return has(p, module, "view_all", "manage")


def all_access(p: Any, module: str) -> bool:
    return p is None or bool(getattr(p, "is_super_admin", False)) or (module_reader(p, module) and institution_scope(p))


def is_auditor(p: Any) -> bool:
    return p is not None and "auditor" in (getattr(p, "roles", None) or []) and not getattr(p, "is_super_admin", False)


def dept_subquery(p: Any) -> Any:
    depts, faculties = scope_ids(p, "department"), scope_ids(p, "faculty")
    if faculties:
        return select(Department.id).where(
            or_(Department.id.in_(depts or [uuid.uuid4()]), Department.faculty_id.in_(faculties))
        )
    return depts


def visibility_scopes(p: Any, module: str) -> list[str]:
    if p is None or getattr(p, "is_super_admin", False):
        return ["all"]
    tabs = ["self"]
    if (scope_ids(p, "department") or scope_ids(p, "faculty")) and module_reader(p, module):
        tabs.append("department")
    if scope_ids(p, "college") and module_reader(p, module):
        tabs.append("college")
    if all_access(p, module):
        tabs.append("all")
    return tabs


class FacilitiesBase(StudentServiceBase):
    audit_module = "facilities"
    module = "facilities"

    # ---- permissions --------------------------------------------------------------------------------------------------
    def require(self, *specs: str) -> None:
        for spec in specs:
            module, _, action = spec.rpartition(":")
            if self.can(module or self.module, action):
                return
        raise forbidden(f"{'|'.join(specs)} required")

    def require_writer(self) -> None:
        """The auditor reads across the estate; every mutation is refused (Prompts/25 §25.11 step 13)."""
        if is_auditor(self.principal) and not self.can(self.module, "manage"):
            raise forbidden("The auditor role is read-only")

    async def feature(self, key: str) -> bool:
        from app.core.features import is_enabled

        return await is_enabled(self.inst, key)

    async def require_feature(self, key: str) -> None:
        if not await self.feature(key):
            raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature {key} is not enabled", {"feature": key})

    def all_access(self, module: str | None = None) -> bool:
        return all_access(self.principal, module or self.module)

    def reader(self, module: str | None = None) -> bool:
        return module_reader(self.principal, module or self.module)

    def scopes(self, module: str | None = None) -> list[str]:
        return visibility_scopes(self.principal, module or self.module)

    def unit_predicate(
        self,
        module: str,
        *,
        self_cols: tuple[Any, ...] = (),
        dept_col: Any = None,
        college_col: Any = None,
        scope: str | None = None,
    ) -> ColumnElement[bool]:
        """Self / department / college / all predicate; ``scope`` narrows to one ScopeTab."""
        p = self.principal
        if scope in (None, "all") and all_access(p, module):
            return true()
        if getattr(p, "id", None) is None:
            return false()
        parts: list[ColumnElement[bool]] = []
        if scope in (None, "self", "mine"):
            parts += [c == p.id for c in self_cols]
        units = scope_ids(p, "department") or scope_ids(p, "faculty")
        if scope in (None, "department") and dept_col is not None and module_reader(p, module) and units:
            parts.append(dept_col.in_(dept_subquery(p)))
        if (
            scope in (None, "college")
            and college_col is not None
            and module_reader(p, module)
            and scope_ids(p, "college")
        ):
            parts.append(college_col.in_(scope_ids(p, "college")))
        return or_(*parts) if parts else false()

    # ---- people ---------------------------------------------------------------------------------------------------------
    async def my_staff(self) -> Staff | None:
        if self.actor_id is None:
            return None
        return (await self.db.execute(select(Staff).where(Staff.user_id == self.actor_id))).scalar_one_or_none()

    async def my_staff_id(self) -> uuid.UUID | None:
        s = await self.my_staff()
        return s.id if s else None

    async def my_student(self) -> Student | None:
        if self.actor_id is None:
            return None
        return (await self.db.execute(select(Student).where(Student.user_id == self.actor_id))).scalar_one_or_none()

    async def me_person(self) -> tuple[str, uuid.UUID]:
        """``(person_type, person_id)`` of the caller — student first, then staff (409 for neither)."""
        st = await self.my_student()
        if st is not None:
            return "student", st.id
        sf = await self.my_staff()
        if sf is not None:
            return "staff", sf.id
        raise rule("Your account is not linked to a student or staff record", "NO_PERSON")

    async def person_user_id(self, person_type: str, person_id: uuid.UUID) -> uuid.UUID | None:
        model: Any = Student if person_type == "student" else Staff
        return (await self.db.execute(select(model.user_id).where(model.id == person_id))).scalar_one_or_none()

    async def person_names(self, pairs: list[tuple[str | None, uuid.UUID | None]]) -> dict[uuid.UUID, str]:
        out: dict[uuid.UUID, str] = {}
        sids = [i for t, i in pairs if t == "student" and i]
        fids = [i for t, i in pairs if t == "staff" and i]
        if sids:
            for s in (await self.db.execute(select(Student).where(Student.id.in_(sids)))).scalars():
                out[s.id] = s.full_name
        if fids:
            for f in (await self.db.execute(select(Staff).where(Staff.id.in_(fids)))).scalars():
                out[f.id] = " ".join(x for x in (f.first_name, f.last_name) if x)
        return out

    async def user_names(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        rows = (
            await self.db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(wanted)))
        ).all()
        return {r[0]: r[1] or r[2] for r in rows}

    async def user_departments(self, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID | None]:
        """Department of each user: staff department, else the student's current enrolment department."""
        out: dict[uuid.UUID, uuid.UUID | None] = {}
        if not user_ids:
            return out
        for uid, dep in (
            await self.db.execute(select(Staff.user_id, Staff.department_id).where(Staff.user_id.in_(user_ids)))
        ).all():
            out[uid] = dep
        rest = [u for u in user_ids if u not in out]
        if rest:
            rows = (
                await self.db.execute(
                    select(Student.user_id, StudentProgramEnrollment.department_id)
                    .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                    .where(Student.user_id.in_(rest))
                )
            ).all()
            for uid, dep in rows:
                out.setdefault(uid, dep)
        return out

    def requester_dept_subquery(self) -> Any:
        """User ids whose department is one of the caller's departments (staff or enrolled students)."""
        depts = dept_subquery(self.principal)
        return (
            select(Staff.user_id)
            .where(Staff.department_id.in_(depts))
            .union(
                select(Student.user_id)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.department_id.in_(depts))
            )
        )

    # ---- facilities_meta ------------------------------------------------------------------------------------------------
    async def _meta_row(self, kind: str, rid: Any) -> InstitutionSetting | None:
        return (
            await self.db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.college_id.is_(None),
                    InstitutionSetting.category == META,
                    InstitutionSetting.key == f"{kind}:{rid}",
                )
            )
        ).scalar_one_or_none()

    async def meta(self, kind: str, rid: Any) -> dict[str, Any]:
        row = await self._meta_row(kind, rid)
        return dict(row.value) if row is not None and isinstance(row.value, dict) else {}

    async def put_meta(self, kind: str, rid: Any, value: dict[str, Any]) -> None:
        row = await self._meta_row(kind, rid)
        if row is None:
            self.db.add(
                InstitutionSetting(
                    institution_id=self.inst,
                    college_id=None,
                    category=META,
                    key=f"{kind}:{rid}",
                    value=value,
                    value_type="json",
                    updated_by=self.actor_id,
                )
            )
        else:
            row.value, row.updated_by = value, self.actor_id
        await self.db.flush()

    async def metas(self, kind: str, ids: list[Any] | None = None) -> dict[str, dict[str, Any]]:
        stmt = select(InstitutionSetting.key, InstitutionSetting.value).where(
            InstitutionSetting.institution_id == self.inst, InstitutionSetting.category == META
        )
        if ids is not None:
            if not ids:
                return {}
            stmt = stmt.where(InstitutionSetting.key.in_([f"{kind}:{i}" for i in ids]))
        else:
            stmt = stmt.where(InstitutionSetting.key.like(f"{kind}:%"))
        rows = (await self.db.execute(stmt)).all()
        return {k.split(":", 1)[1]: (v if isinstance(v, dict) else {}) for k, v in rows}

    async def timeline(self, kind: str, rid: Any, action: str, **extra: Any) -> dict[str, Any]:
        m = await self.meta(kind, rid)
        tl = list(m.get("timeline") or [])
        tl.append(
            {
                "at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
                "action": action,
                **extra,
            }
        )
        m["timeline"] = tl
        await self.put_meta(kind, rid, m)
        return m

    async def sequence(self, scope_key: str, prefix: str, college_id: uuid.UUID | None = None) -> str:
        from app.services.sequence_service import SequenceService

        try:
            return (
                await SequenceService(self.db, self.principal, self.request, self.inst).next(scope_key, college_id)
            ).rendered[:30]
        except APIError:
            return f"{prefix}/{(await self.today()).year}/{uuid.uuid4().hex[:6].upper()}"[:30]

    async def close_workflow(self, instance_id: uuid.UUID | None, status: str = "cancelled") -> None:
        """Close a pending workflow decided outside the inbox (desk decision / cancellation by an officer)."""
        if instance_id is None:
            return
        from app.models.platform import WorkflowInstance, WorkflowStep

        wf = (
            await self.db.execute(select(WorkflowInstance).where(WorkflowInstance.id == instance_id).with_for_update())
        ).scalar_one_or_none()
        if wf is None or wf.status not in ("pending", "escalated"):
            return
        for st in (
            await self.db.execute(
                select(WorkflowStep).where(
                    WorkflowStep.instance_id == wf.id, WorkflowStep.status.in_(("pending", "escalated"))
                )
            )
        ).scalars():
            st.status = "skipped"
        wf.status, wf.closed_at = status, now_utc()
        await self.db.flush()

    async def int_setting(self, category: str, key: str, default: int) -> int:
        v = await self.setting(category, key)
        try:
            return int(v) if v is not None else default
        except (TypeError, ValueError):
            return default
