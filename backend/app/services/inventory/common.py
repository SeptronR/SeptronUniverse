"""Shared plumbing of the Phase 22 services — on the Phase 07 ``StudentServiceBase``.

**Visibility** (Prompts/22 "Visibility rules"):

* **stores / stock** — institution-scoped ``inventory:manage|view_all`` (inventory manager, accountant, auditor) see
  all; college scopes their college's stores; HODs their department stores; store keepers the stores they keep
  (``stores.keeper_staff_id``);
* **indents** — own (``requested_by``), department (HOD — ``indents.department_id``), the stores a keeper keeps
  (approved queue), college / all for readers;
* **assets** — own custody, department, college, all;
* **vendors** — ``suppliers.portal_user_id`` = the caller (quotations, POs, GRNs, bills).

Small mutable facts the section 21 tables have no column for (PO version / acknowledgement, pending custody transfer,
bill hold reason, supplier blacklist reason, audit cycles, depreciation runs) live in ``institution_settings`` rows of
category ``inventory_meta`` keyed ``<kind>:<id>`` — see ``meta`` / ``put_meta``.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.errors import APIError, ErrorCode
from app.models.hr import Staff
from app.models.inventory import Store, Supplier
from app.models.platform import Department, InstitutionSetting
from app.services.students.common import StudentServiceBase

INV = "inventory"
META_CATEGORY = "inventory_meta"


def pairs(rows: Any) -> dict[Any, Any]:
    """``dict`` of two-column rows (typed for mypy)."""
    return {r[0]: r[1] for r in rows}


def now_utc() -> datetime:
    return datetime.now(UTC)


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def _ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def institution_scope(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def is_reader(p: Any, module: str = INV) -> bool:
    return (
        p is None or bool(getattr(p, "is_super_admin", False)) or p.has(module, "view_all") or p.has(module, "manage")
    )


def all_access(p: Any, module: str = INV) -> bool:
    return p is None or bool(getattr(p, "is_super_admin", False)) or (is_reader(p, module) and institution_scope(p))


def my_staff_ids(p: Any) -> Any:
    return select(Staff.id).where(Staff.user_id == getattr(p, "id", None), Staff.deleted_at.is_(None))


def dept_ids(p: Any) -> Any:
    depts, faculties = _ids(p, "department"), _ids(p, "faculty")
    if faculties:
        return select(Department.id).where(
            or_(Department.id.in_(depts or [uuid.uuid4()]), Department.faculty_id.in_(faculties))
        )
    return depts


def kept_store_ids(p: Any) -> Any:
    return select(Store.id).where(Store.keeper_staff_id.in_(my_staff_ids(p)))


def store_predicate(p: Any) -> ColumnElement[bool]:
    if all_access(p):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    parts: list[ColumnElement[bool]] = [Store.id.in_(kept_store_ids(p))]
    if is_reader(p) and _ids(p, "college"):
        parts.append(Store.college_id.in_(_ids(p, "college")))
    if (_ids(p, "department") or _ids(p, "faculty")) and (p.has(INV, "approve_indent") or is_reader(p)):
        parts.append(Store.department_id.in_(dept_ids(p)))
    return or_(*parts)


def unit_predicate(
    p: Any, dept_col: Any, college_col: Any | None, self_col: Any, self_value: Any
) -> ColumnElement[bool]:
    """Department-anchored rows (indents, assets): own, department (HOD / approvers), college, all."""
    if all_access(p):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    parts: list[ColumnElement[bool]] = [
        self_col.in_(self_value) if not isinstance(self_value, uuid.UUID) else self_col == self_value
    ]
    if (_ids(p, "department") or _ids(p, "faculty")) and (
        p.has(INV, "approve_indent") or p.has(INV, "asset_audit") or is_reader(p)
    ):
        parts.append(dept_col.in_(dept_ids(p)))
    if college_col is not None and is_reader(p) and _ids(p, "college"):
        parts.append(college_col.in_(_ids(p, "college")))
    return or_(*parts)


def visibility_scopes(p: Any) -> list[str]:
    if p is None or getattr(p, "is_super_admin", False):
        return ["all"]
    tabs = ["self"]
    if _ids(p, "department") or _ids(p, "faculty"):
        tabs.append("department")
    if _ids(p, "college") and is_reader(p):
        tabs.append("college")
    if all_access(p):
        tabs.append("all")
    return tabs


class InventoryBase(StudentServiceBase):
    audit_module = "inventory"

    def require(self, *perms: str) -> None:
        """``perms`` as ``module:action`` (or bare actions of ``inventory``); ``inventory:manage`` always passes."""
        for spec in perms:
            module, _, action = spec.rpartition(":")
            if self.can(module or INV, action):
                return
        if self.can(INV, "manage"):
            return
        raise APIError(403, ErrorCode.PERMISSION_DENIED, f"{'|'.join(perms)} required")

    async def feature(self, key: str) -> bool:
        from app.core.features import is_enabled

        return await is_enabled(self.inst, key)

    async def my_staff(self) -> Staff | None:
        if self.actor_id is None:
            return None
        return (
            await self.db.execute(
                select(Staff).where(Staff.user_id == self.actor_id, Staff.institution_id == self.inst)
            )
        ).scalar_one_or_none()

    async def my_supplier(self) -> Supplier:
        s = (
            await self.db.execute(
                select(Supplier).where(Supplier.portal_user_id == self.actor_id, Supplier.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None or self.actor_id is None:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "No supplier account for this user")
        if s.status != "active":
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "The supplier account is not verified yet", {"status": s.status}
            )
        return s

    async def store(self, store_id: uuid.UUID, *, own: bool = False) -> Store:
        q = select(Store).where(Store.id == store_id, Store.institution_id == self.inst)
        row = (await self.db.execute(q.where(store_predicate(self.principal)))).scalar_one_or_none()
        if row is None:
            exists = (await self.db.execute(q)).scalar_one_or_none()
            if exists is not None:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "This store is not yours")
            raise APIError(404, ErrorCode.NOT_FOUND, "Store not found")
        if own and not all_access(self.principal) and not self.can(INV, "manage"):
            mine = (await self.db.execute(kept_store_ids(self.principal))).scalars().all()
            if row.id not in mine:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the store keeper may move stock here")
        return row

    async def sequence(self, scope_key: str, prefix: str) -> str:
        from app.services.sequence_service import SequenceService

        try:
            return (
                await SequenceService(self.db, self.principal, self.request, self.inst).next(scope_key, None)
            ).rendered[:30]
        except APIError:
            return f"{prefix}/{(await self.today()).year}/{uuid.uuid4().hex[:6].upper()}"

    async def threshold(self, key: str, default: int) -> int:
        v = await self.setting("inventory", key)
        return int(v) if v is not None else default

    # ---- inventory_meta (see the module docstring) ------------------------------------------------------------------------
    async def meta(self, kind: str, rid: uuid.UUID | str) -> dict[str, Any]:
        row = (
            await self.db.execute(
                select(InstitutionSetting.value).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.college_id.is_(None),
                    InstitutionSetting.category == META_CATEGORY,
                    InstitutionSetting.key == f"{kind}:{rid}",
                )
            )
        ).scalar_one_or_none()
        return dict(row) if isinstance(row, dict) else {}

    async def put_meta(self, kind: str, rid: uuid.UUID | str, value: dict[str, Any]) -> None:
        row = (
            await self.db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.college_id.is_(None),
                    InstitutionSetting.category == META_CATEGORY,
                    InstitutionSetting.key == f"{kind}:{rid}",
                )
            )
        ).scalar_one_or_none()
        if row is None:
            self.db.add(
                InstitutionSetting(
                    institution_id=self.inst,
                    college_id=None,
                    category=META_CATEGORY,
                    key=f"{kind}:{rid}",
                    value=value,
                    value_type="json",
                    updated_by=self.actor_id,
                )
            )
        else:
            row.value = value
            row.updated_by = self.actor_id
        await self.db.flush()

    async def metas(self, kind: str) -> dict[str, dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(InstitutionSetting.key, InstitutionSetting.value).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.category == META_CATEGORY,
                    InstitutionSetting.key.like(f"{kind}:%"),
                )
            )
        ).all()
        return {k.split(":", 1)[1]: (v if isinstance(v, dict) else {}) for k, v in rows}

    async def role_users(self, *roles: str) -> dict[str, Any]:
        return {"roles": list(roles)}

    async def staff_names(self, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        clean = {i for i in ids if i}
        if not clean:
            return {}
        return {s.id: s.full_name for s in (await self.db.execute(select(Staff).where(Staff.id.in_(clean)))).scalars()}
