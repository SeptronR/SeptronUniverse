"""Shared plumbing of the Phase 23 services — on the Phase 07 ``StudentServiceBase``.

**Visibility** (Prompts/23 "Visibility rules"): chart / ledger / statements need ``accounting:view_all|manage``
(institution scope = all, college scope = rows of that college); expenses add own (``recorded_by``) and the caller's
departments (HOD — ``accounting:view|post`` scoped to a department); budgets add the caller's departments; grants add
PI ownership (``pi_staff_id`` kept with the ledger's metadata, or the Phase 30 ``research_projects.pi_staff_id``).

Small facts the section 22 tables have no column for (period lock date, grant PI / heads history, export markers,
expense GST input, posting idempotency keys of reversals) live in ``institution_settings`` rows of category
``accounting_meta`` keyed ``<kind>:<id>``; account mappings are the ``accounting.mappings`` setting.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.errors import APIError, ErrorCode
from app.enums.accounting import DEFAULT_MAPPINGS
from app.models.fees import LedgerAccount
from app.models.hr import Staff
from app.models.platform import Department, InstitutionSetting
from app.services.students.common import StudentServiceBase

ACC = "accounting"
META = "accounting_meta"


def pairs(rows: Any) -> dict[Any, Any]:
    return {r[0]: r[1] for r in rows}


def now_utc() -> datetime:
    return datetime.now(UTC)


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def _ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def institution_scope(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def reader(p: Any) -> bool:
    return p is None or bool(getattr(p, "is_super_admin", False)) or p.has(ACC, "view_all") or p.has(ACC, "manage")


def all_access(p: Any) -> bool:
    return p is None or bool(getattr(p, "is_super_admin", False)) or (reader(p) and institution_scope(p))


def dept_ids(p: Any) -> Any:
    depts, faculties = _ids(p, "department"), _ids(p, "faculty")
    if faculties:
        return select(Department.id).where(
            or_(Department.id.in_(depts or [uuid.uuid4()]), Department.faculty_id.in_(faculties))
        )
    return depts


def unit_predicate(p: Any, dept_col: Any, college_col: Any, self_col: Any | None = None) -> ColumnElement[bool]:
    if all_access(p):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    parts: list[ColumnElement[bool]] = []
    if self_col is not None:
        parts.append(self_col == p.id)
    if (
        dept_col is not None
        and (_ids(p, "department") or _ids(p, "faculty"))
        and (p.has(ACC, "view") or p.has(ACC, "post") or reader(p))
    ):
        parts.append(dept_col.in_(dept_ids(p)))
    if college_col is not None and reader(p) and _ids(p, "college"):
        parts.append(college_col.in_(_ids(p, "college")))
    return or_(*parts) if parts else false()


def visibility_scopes(p: Any) -> list[str]:
    if p is None or getattr(p, "is_super_admin", False):
        return ["all"]
    tabs = ["self"]
    if _ids(p, "department") or _ids(p, "faculty"):
        tabs.append("department")
    if _ids(p, "college") and reader(p):
        tabs.append("college")
    if all_access(p):
        tabs.append("all")
    return tabs


class AccountingBase(StudentServiceBase):
    audit_module = "accounting"

    def require(self, *perms: str) -> None:
        for spec in perms:
            module, _, action = spec.rpartition(":")
            if self.can(module or ACC, action):
                return
        if self.can(ACC, "manage"):
            return
        raise APIError(403, ErrorCode.PERMISSION_DENIED, f"{'|'.join(perms)} required")

    async def feature(self, key: str) -> bool:
        from app.core.features import is_enabled

        return await is_enabled(self.inst, key)

    async def my_staff_id(self) -> uuid.UUID | None:
        if self.actor_id is None:
            return None
        return (await self.db.execute(select(Staff.id).where(Staff.user_id == self.actor_id))).scalar_one_or_none()

    # ---- accounts & mappings ----------------------------------------------------------------------------------------------
    async def mappings(self) -> dict[str, Any]:
        m = await self.setting("accounting", "mappings")
        return {**DEFAULT_MAPPINGS, **(m if isinstance(m, dict) else {})}

    async def account(self, code_or_key: str) -> LedgerAccount:
        """Account by mapping key (``bank``, ``tds_payable``…) or by code; 409 when the chart lacks it."""
        maps = await self.mappings()
        code = maps.get(code_or_key, code_or_key)
        acct = (
            await self.db.execute(
                select(LedgerAccount).where(LedgerAccount.institution_id == self.inst, LedgerAccount.code == str(code))
            )
        ).scalar_one_or_none()
        if acct is None:
            raise rule(
                f"Ledger account {code} is missing — import the chart of accounts", "ACCOUNT_MISSING", account=str(code)
            )
        return acct

    async def account_by_id(self, account_id: uuid.UUID) -> LedgerAccount:
        a = (
            await self.db.execute(
                select(LedgerAccount).where(LedgerAccount.id == account_id, LedgerAccount.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Ledger account not found")
        if not a.is_active:
            raise rule("The ledger account is inactive", "ACCOUNT_INACTIVE")
        return a

    # ---- period lock --------------------------------------------------------------------------------------------------------
    async def closed_upto(self) -> date | None:
        v = (await self.meta("period", "lock")).get("upto")
        return date.fromisoformat(v) if v else None

    async def check_open(self, on: date) -> None:
        upto = await self.closed_upto()
        if upto and on <= upto:
            raise rule(f"The books are closed up to {upto.isoformat()}", "PERIOD_CLOSED", closed_upto=upto.isoformat())

    # ---- accounting_meta --------------------------------------------------------------------------------------------------
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

    async def metas(self, kind: str) -> dict[str, dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(InstitutionSetting.key, InstitutionSetting.value).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.category == META,
                    InstitutionSetting.key.like(f"{kind}:%"),
                )
            )
        ).all()
        return {k.split(":", 1)[1]: (v if isinstance(v, dict) else {}) for k, v in rows}
