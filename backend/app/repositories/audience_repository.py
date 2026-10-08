"""Audience resolution — Prompts/04 §04.5 (announcement rules and ``notify_event`` audiences → user ids).

Rules combine with OR across keys (a user matching any rule is in the audience); every rule is evaluated inside the
institution. Membership sources, until each owning module exists (the tables are all in the canonical DDL):

* ``roles`` — ``user_roles`` → ``roles.slug`` (valid assignments);
* ``college_ids`` / ``department_ids`` — role assignments scoped to the unit (a department assignment also counts for
  its college), ``staff.college_id/department_id`` (Phase 06) and ``students.college_id`` /
  ``student_program_enrollments.department_id`` (Phase 07);
* ``program_ids`` / ``batch_ids`` — ``student_program_enrollments`` (Phases 05/07);
* ``include_guardians`` — ``student_guardians.user_id`` of the matched students when ``students.guardian_portal_consent``.

Phase 07: student membership counts only non-deleted students in a seated status (an exited / transferred student is
no longer in a college's or batch's audience) and open enrolments (active / break / detained) for department,
programme and batch rules.
"""

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SEATED = "('provisional','admitted','active','on_break','detained')"
OPEN = "('active','break','detained')"


def _ids(values: Iterable[Any] | None) -> list[str]:
    out = []
    for v in values or []:
        try:
            out.append(str(uuid.UUID(str(v))))
        except (TypeError, ValueError):
            continue
    return out


class AudienceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _users(self, sql: str, params: dict[str, Any]) -> set[uuid.UUID]:
        rows = (await self.db.execute(text(sql), params)).all()
        return {uuid.UUID(str(r[0])) for r in rows if r[0]}

    async def resolve(self, institution_id: uuid.UUID, rules: dict[str, Any]) -> set[uuid.UUID]:
        i = str(institution_id)
        users: set[uuid.UUID] = set()
        user_ids = _ids(rules.get("user_ids"))
        if user_ids:
            users |= await self._users(
                "SELECT id FROM users WHERE institution_id = :i AND id = ANY(CAST(:u AS uuid[])) AND is_active "
                "AND deleted_at IS NULL",
                {"i": i, "u": user_ids},
            )
        roles = [str(r) for r in rules.get("roles") or []]
        if roles:
            users |= await self._users(
                "SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id JOIN users u ON u.id = ur.user_id "
                "WHERE r.institution_id = :i AND r.slug = ANY(:r) AND u.is_active AND u.deleted_at IS NULL "
                "AND (ur.valid_to IS NULL OR ur.valid_to >= NOW())",
                {"i": i, "r": roles},
            )
        colleges = _ids(rules.get("college_ids") or ([rules["college_id"]] if rules.get("college_id") else []))
        if colleges:
            users |= await self._users(
                "SELECT ur.user_id FROM user_roles ur WHERE ur.institution_id = :i AND ("
                " (ur.scope_type = 'college' AND ur.scope_id = ANY(CAST(:c AS uuid[])))"
                " OR (ur.scope_type = 'department' AND ur.scope_id IN (SELECT id FROM departments WHERE college_id = ANY(CAST(:c AS uuid[]))))"
                " OR (ur.scope_type = 'faculty' AND ur.scope_id IN (SELECT id FROM faculties WHERE college_id = ANY(CAST(:c AS uuid[])))))"
                " UNION SELECT user_id FROM staff WHERE institution_id = :i AND college_id = ANY(CAST(:c AS uuid[])) AND deleted_at IS NULL"
                " UNION SELECT user_id FROM students WHERE institution_id = :i AND college_id = ANY(CAST(:c AS uuid[])) AND deleted_at IS NULL"
                f" AND status IN {SEATED}",
                {"i": i, "c": colleges},
            )
        depts = _ids(rules.get("department_ids") or ([rules["department_id"]] if rules.get("department_id") else []))
        if depts:
            users |= await self._users(
                "SELECT user_id FROM user_roles WHERE institution_id = :i AND scope_type = 'department' "
                "AND scope_id = ANY(CAST(:d AS uuid[]))"
                " UNION SELECT user_id FROM staff WHERE institution_id = :i AND department_id = ANY(CAST(:d AS uuid[])) AND deleted_at IS NULL"
                " UNION SELECT s.user_id FROM student_program_enrollments e JOIN students s ON s.id = e.student_id "
                "WHERE e.institution_id = :i AND e.department_id = ANY(CAST(:d AS uuid[])) AND e.deleted_at IS NULL "
                f"AND s.deleted_at IS NULL AND e.status IN {OPEN}",
                {"i": i, "d": depts},
            )
        for key, column in (("program_ids", "program_id"), ("batch_ids", "batch_id")):
            single = key[:-1]
            ids = _ids(rules.get(key) or ([rules[single]] if rules.get(single) else []))
            if ids:
                users |= await self._users(
                    f"SELECT s.user_id FROM student_program_enrollments e JOIN students s ON s.id = e.student_id "  # noqa: S608 - column is a literal
                    f"WHERE e.institution_id = :i AND e.{column} = ANY(CAST(:x AS uuid[])) AND e.deleted_at IS NULL "
                    f"AND s.deleted_at IS NULL AND e.status IN {OPEN}",
                    {"i": i, "x": ids},
                )
        if rules.get("include_guardians") and users:
            users |= await self.guardians_of(institution_id, sorted(users, key=str))
        return users

    async def guardians_of(self, institution_id: uuid.UUID, student_user_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
        return await self._users(
            "SELECT g.user_id FROM student_guardians g JOIN students s ON s.id = g.student_id "
            "WHERE s.institution_id = :i AND s.user_id = ANY(CAST(:u AS uuid[])) AND s.guardian_portal_consent "
            "AND g.portal_access AND g.user_id IS NOT NULL",
            {"i": str(institution_id), "u": [str(u) for u in student_user_ids]},
        )

    async def contacts(self, user_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        """user → {email, phone, locale, display_name, institution_id} for the delivery step."""
        if not user_ids:
            return {}
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, email, phone, locale, display_name, username, institution_id FROM users "
                        "WHERE id = ANY(CAST(:u AS uuid[]))"
                    ),
                    {"u": [str(u) for u in user_ids]},
                )
            )
            .mappings()
            .all()
        )
        return {uuid.UUID(str(r["id"])): dict(r) for r in rows}

    async def member_of(self, institution_id: uuid.UUID, user_id: uuid.UUID, rules: dict[str, Any]) -> bool:
        """Does ``user_id`` belong to the audience (announcement visibility)? Empty rules = the whole institution."""
        if not any(
            rules.get(k) for k in ("roles", "college_ids", "department_ids", "program_ids", "batch_ids", "user_ids")
        ):
            return True
        return user_id in await self.resolve(institution_id, rules)
