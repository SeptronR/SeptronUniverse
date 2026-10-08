"""Global search — Prompts/01 §01.6 / docs/Technical_Architecture.md §10.

Business rules
1. ``search(principal, q, entity_types)`` returns the top 20 ``search_documents`` rows for the principal's institution
   (super admins search the current tenant context, or everything when none is selected), each with the client route.
2. Entity types are gated by the permissions of their owning module — ``student`` needs ``students:view``,
   ``staff`` needs ``hr:view`` or ``faculty:view``, ``course`` needs ``courses:view``, ``applicant`` needs
   ``admissions:view``; unknown or unpermitted types are dropped silently (never 403 for a search).
3. Principals whose scopes are college-bound only (no institution scope, no ``view_all``) are narrowed to their
   colleges (institution-wide rows stay visible). Phase 07: ``student`` hits apply the students visibility
   (self / wards / advisees / unit scopes — ``repositories/student_scope.py``) inside the query.
4. The materialized view is refreshed by the outbox consumer ``search.reindex`` (``tasks/platform.py``) — throttled
   to at most one ``REFRESH … CONCURRENTLY`` per minute; Phase 07+ emit ``student.created`` etc.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal
from app.repositories.platform_repository import SEARCH_ENTITIES, SEARCH_ROUTES, SearchRepository
from app.schemas.platform import SearchResult

ENTITY_PERMISSIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "student": (("students", "view"), ("students", "view_all")),
    "staff": (("hr", "view"), ("faculty", "view"), ("hr", "view_all")),
    "course": (("courses", "view"), ("curriculum", "view")),
    "applicant": (("admissions", "view"), ("admissions", "view_all")),
}
MAX_RESULTS = 20


class SearchService:
    def __init__(self, db: AsyncSession, principal: Principal):
        self.db, self.principal = db, principal
        self.repo = SearchRepository(db)

    def allowed_types(self, requested: Sequence[str] | None) -> list[str]:
        """Rule 2."""
        wanted = [t for t in (requested or SEARCH_ENTITIES) if t in SEARCH_ENTITIES]
        return [t for t in wanted if any(self.principal.has(m, a) for m, a in ENTITY_PERMISSIONS[t])]

    def _college_filter(self) -> list[uuid.UUID] | None:
        """Rule 3."""
        if self.principal.is_super_admin:
            return None
        scopes = self.principal.scopes
        if any(st == "institution" for st, _ in scopes):
            return None
        colleges = [sid for st, sid in scopes if st == "college" and sid is not None]
        return colleges if colleges else None

    async def search(self, q: str, entity_types: Sequence[str] | None = None) -> tuple[list[SearchResult], list[str]]:
        """Rule 1."""
        types = self.allowed_types(entity_types)
        q = (q or "").strip()
        if len(q) < 2 or not types:
            return [], types
        student_ids = None
        if "student" in types and not self.principal.is_super_admin:
            from app.repositories.student_scope import visible_student_ids

            student_ids = visible_student_ids(self.principal)
        rows = await self.repo.search(
            self.principal.institution_id,
            q,
            types,
            college_ids=self._college_filter(),
            limit=MAX_RESULTS,
            student_ids=student_ids,
        )
        return [self._to_result(r) for r in rows], types

    @staticmethod
    def _to_result(row: dict[str, Any]) -> SearchResult:
        return SearchResult(
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            title=(row.get("title") or "").strip(),
            subtitle=row.get("subtitle"),
            route=SEARCH_ROUTES[row["entity_type"]].format(id=row["entity_id"]),
            college_id=row.get("college_id"),
        )
