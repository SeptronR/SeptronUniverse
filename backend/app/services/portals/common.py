"""Shared helpers of the Phase 39 portal services — Prompts/39 "Visibility rules".

Portals are self / ward / ownership only: every helper resolves the caller's *own* ids (student row, consented
wards, staff row, library member rows, enrolments) and the aggregators filter by them — no scope parameter is ever
honoured (``?scope=all`` is ignored). Settings come from the Phase 03 settings service (template defaults apply).
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal
from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client
from app.enums.portals import PERSONA_PRIORITY, ROLE_PERSONA

WARD_KEY = "portal_ward:{user}"


def personas_of(principal: Any) -> list[str]:
    held = {ROLE_PERSONA[r] for r in getattr(principal, "roles", []) if r in ROLE_PERSONA}
    return [p for p in PERSONA_PRIORITY if p in held]


def persona_of(principal: Any) -> str | None:
    """§39.6 rule 1 — the highest-priority persona the user holds (faculty wins over a parent role)."""
    held = personas_of(principal)
    return held[-1] if held else None


class PortalBase:
    def __init__(self, db: AsyncSession, principal: Principal, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        if principal.institution_id is None:
            raise APIError(422, ErrorCode.VALIDATION, "Portals need an institution account")
        self.inst: uuid.UUID = principal.institution_id
        self._student: Any = None
        self._wards: list[dict[str, Any]] | None = None

    async def setting(self, category: str, key: str) -> Any:
        from app.services.settings_service import SettingsService

        return await SettingsService(self.db).value(self.inst, category, key)

    async def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        return [dict(r) for r in (await self.db.execute(text(sql), {"i": self.inst, **params})).mappings().all()]

    # ---- self ---------------------------------------------------------------------------------------------------
    async def own_student_id(self) -> uuid.UUID | None:
        if self._student is None:
            r = await self.rows(
                "SELECT id FROM students WHERE institution_id = :i AND user_id = :u AND deleted_at IS NULL LIMIT 1",
                u=self.principal.id,
            )
            self._student = r[0]["id"] if r else False
        return self._student or None

    async def own_staff_id(self) -> uuid.UUID | None:
        r = await self.rows(
            "SELECT id FROM staff WHERE institution_id = :i AND user_id = :u LIMIT 1", u=self.principal.id
        )
        return r[0]["id"] if r else None

    # ---- wards (§39.6 rule 4) ------------------------------------------------------------------------------------
    async def wards(self) -> list[dict[str, Any]]:
        if self._wards is None:
            require = await self.setting("portals", "parent_require_consent")
            self._wards = await self.rows(
                "SELECT s.id AS student_id, trim(concat_ws(' ', s.first_name, s.last_name)) AS name, "
                "s.registration_number, s.guardian_portal_consent AS consent, "
                "(SELECT p.name FROM student_program_enrollments e JOIN programs p ON p.id = e.program_id "
                " WHERE e.student_id = s.id ORDER BY e.admission_date DESC NULLS LAST LIMIT 1) AS program "
                "FROM student_guardians g JOIN students s ON s.id = g.student_id "
                "WHERE g.institution_id = :i AND g.user_id = :u AND g.portal_access AND s.deleted_at IS NULL "
                "AND (s.guardian_portal_consent OR NOT :req) ORDER BY s.first_name",
                u=self.principal.id,
                req=require is not False,
            )
        return self._wards

    async def ward_ids(self) -> list[uuid.UUID]:
        return [w["student_id"] for w in await self.wards()]

    async def active_ward(self) -> uuid.UUID | None:
        raw = await redis_client.get(WARD_KEY.format(user=self.principal.id))
        ids = await self.ward_ids()
        if raw:
            try:
                wid = uuid.UUID(raw if isinstance(raw, str) else raw.decode())
            except ValueError:
                wid = None
            if wid in ids:
                return wid
        return ids[0] if ids else None

    async def subject_student_ids(self, student_id: uuid.UUID | None = None) -> list[uuid.UUID]:
        """Students whose records the caller may see in the portal: self + consented wards; ``student_id`` narrows
        to one of them (anything else → 404, never a cross-family read)."""
        ids: list[uuid.UUID] = []
        own = await self.own_student_id()
        if own:
            ids.append(own)
        ids += [w for w in await self.ward_ids() if w not in ids]
        if student_id is not None:
            if student_id not in ids:
                raise APIError(404, ErrorCode.NOT_FOUND, "Student not found")
            return [student_id]
        return ids

    async def enrollment_ids(self, student_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        if not student_ids:
            return []
        r = await self.rows(
            "SELECT id FROM student_program_enrollments WHERE institution_id = :i AND student_id = ANY(:s)",
            s=student_ids,
        )
        return [x["id"] for x in r]
