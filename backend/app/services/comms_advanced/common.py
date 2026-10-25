"""Shared plumbing of the Phase 24 services — on the Phase 07 ``StudentServiceBase``.

**Visibility** (Prompts/24 "Visibility rules"): ``communication:bulk|approve`` holders scoped to the institution see and
target everything (``all``); college-scoped holders their college; HODs / faculty (``communication:send`` scoped to a
department, or their staff department) only their department's students, guardians and staff, on in-app / email / push
unless they also hold ``communication:bulk``; everyone reads their own messages and conversations.
Saved segments are the ``comms.segments`` institution setting (JSON list); small facts without columns (campaign
approval, pause, emergency details, assistant opt-in metadata) live in ``institution_settings`` category
``comms_meta``.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.hr import Staff
from app.models.platform import InstitutionSetting
from app.services.students.common import StudentServiceBase

COMM = "communication"
META = "comms_meta"


def now_utc() -> datetime:
    return datetime.now(UTC)


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def _ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def institution_scope(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def officer(p: Any) -> bool:
    return (
        p is None
        or bool(getattr(p, "is_super_admin", False))
        or p.has(COMM, "bulk")
        or p.has(COMM, "approve")
        or p.has(COMM, "manage")
    )


def all_access(p: Any) -> bool:
    return p is None or bool(getattr(p, "is_super_admin", False)) or (officer(p) and institution_scope(p))


def visibility_scopes(p: Any) -> list[str]:
    if p is None or getattr(p, "is_super_admin", False):
        return ["all"]
    tabs = ["self"]
    if _ids(p, "department") or p.has(COMM, "send"):
        tabs.append("department")
    if _ids(p, "college") and officer(p):
        tabs.append("college")
    if all_access(p):
        tabs.append("all")
    return tabs


class CommsBase(StudentServiceBase):
    audit_module = "communication"

    def require(self, *actions: str) -> None:
        if any(self.can(COMM, a) for a in actions) or self.can(COMM, "manage"):
            return
        raise APIError(403, ErrorCode.PERMISSION_DENIED, f"communication:{'|'.join(actions)} required")

    async def feature(self, key: str) -> bool:
        from app.core.features import is_enabled

        return await is_enabled(self.inst, key)

    async def require_feature(self, key: str) -> None:
        if not await self.feature(key):
            raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{key}' is not enabled", {"feature": key})

    async def unit_scope(self) -> dict[str, list[uuid.UUID]]:
        """The units a non-officer may target: department scopes, else the caller's staff department."""
        p = self.principal
        if all_access(p):
            return {}
        out: dict[str, list[uuid.UUID]] = {}
        if officer(p) and _ids(p, "college"):
            out["college"] = _ids(p, "college")
            return out
        depts = _ids(p, "department")
        if not depts and self.actor_id is not None:
            d = (
                await self.db.execute(select(Staff.department_id).where(Staff.user_id == self.actor_id))
            ).scalar_one_or_none()
            depts = [d] if d else []
        out["department"] = depts
        return out

    # ---- settings rows (comms.segments + comms_meta) ---------------------------------------------------------------------
    async def _row(self, category: str, key: str) -> InstitutionSetting | None:
        return (
            await self.db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.college_id.is_(None),
                    InstitutionSetting.category == category,
                    InstitutionSetting.key == key,
                )
            )
        ).scalar_one_or_none()

    async def get_json(self, category: str, key: str, default: Any = None) -> Any:
        row = await self._row(category, key)
        return row.value if row is not None and row.value is not None else default

    async def put_json(self, category: str, key: str, value: Any) -> None:
        row = await self._row(category, key)
        if row is None:
            self.db.add(
                InstitutionSetting(
                    institution_id=self.inst,
                    college_id=None,
                    category=category,
                    key=key,
                    value=value,
                    value_type="json",
                    updated_by=self.actor_id,
                )
            )
        else:
            row.value, row.updated_by = value, self.actor_id
        await self.db.flush()

    async def meta(self, kind: str, rid: Any) -> dict[str, Any]:
        v = await self.get_json(META, f"{kind}:{rid}", {})
        return dict(v) if isinstance(v, dict) else {}

    async def put_meta(self, kind: str, rid: Any, value: dict[str, Any]) -> None:
        await self.put_json(META, f"{kind}:{rid}", value)

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
