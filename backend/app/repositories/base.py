"""``BaseRepository`` — Prompts/00_PREREQUISITE_Project_Setup.md §3.13.

All SQL lives in repositories on this base (coding standard 1). ``_base()`` filters soft-deleted rows and the tenant
(belt and braces — RLS is the backstop); ``visible()`` applies the row-level visibility predicate; ``get()`` returns
404 (never 403) for invisible rows; ``update()`` enforces the optimistic ``version``.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar, cast

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.visibility import MODULES, VisibilityResolver
from app.core.errors import APIError, ErrorCode
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

M = TypeVar("M")

SCOPE_TO_COLUMN = {"department": "department_id", "faculty": "faculty_id", "college": "college_id"}


class BaseRepository(Generic[M]):
    model: type[M]
    module: str

    def __init__(self, db: AsyncSession, principal: Any = None, institution_id: Any = None):
        self.db = db
        self.principal = principal
        # explicit tenant (Phase 03): the super admin operating on ``X-Institution-Id`` is pinned to that tenant too
        self.institution_id = institution_id

    @property
    def _m(self) -> Any:
        """The mapped class as ``Any`` for column attribute access (``self._m.institution_id``)."""
        return cast(Any, self.model)

    # ---- query building -----------------------------------------------------------------------------------
    def _base(self, include_deleted: bool = False) -> Select[tuple[M]]:
        q = select(self.model)
        if hasattr(self.model, "deleted_at") and not include_deleted:
            q = q.where(self._m.deleted_at.is_(None))
        if hasattr(self.model, "institution_id"):
            if self.institution_id is not None:
                q = q.where(self._m.institution_id == self.institution_id)
            elif self.principal and not self.principal.is_super_admin:
                # belt and braces (RLS is the backstop)
                q = q.where(self._m.institution_id == self.principal.institution_id)
        return q

    def visible(self, q: Select[tuple[M]], scope: str | None = None) -> Select[tuple[M]]:
        """Apply the row-level visibility predicate; ``scope`` narrows to self/own/department/college/all when requested.

        A requested scope broader than what the principal may see is narrowed silently (docs/Authorization §4).
        """
        if not self.principal or self.principal.is_super_admin:
            return q
        resolver = VisibilityResolver(self.principal)
        pred = resolver.predicate(self.module)
        if pred is not None:
            q = q.where(pred)
        if scope and scope not in {"all", "self", "own"}:
            col = SCOPE_TO_COLUMN.get(scope)
            allowed = resolver.scopes_for(self.module)
            if col and scope in allowed and hasattr(self.model, col):
                ids = [sid for st, sid in self.principal.scopes if st == scope and sid is not None]
                if ids:
                    q = q.where(getattr(self._m, col).in_(ids))
        elif scope in {"self", "own"}:
            mv = MODULES.get(self.module)
            if mv and mv.self_predicate is not None:
                q = q.where(mv.self_predicate(self.principal, mv.model))
        return q

    def visibility_meta(self) -> VisibilityMeta | None:
        if not self.principal or self.module not in MODULES:
            return None
        return VisibilityResolver(self.principal).meta(self.module)

    # ---- reads --------------------------------------------------------------------------------------------
    async def get(self, id: Any, *, for_update: bool = False) -> M:
        q = self.visible(self._base()).where(self._m.id == id)
        if for_update:
            q = q.with_for_update()
        obj = (await self.db.execute(q)).scalar_one_or_none()
        if not obj:
            # 404, never 403 (no existence leak)
            raise APIError(404, ErrorCode.NOT_FOUND, f"{self.model.__name__} not found")
        return obj

    async def list(self, params: PageParams, scope: str | None = None) -> tuple[Sequence[M], PaginationMeta]:
        return await self.paginate(self.visible(self._base(), scope), params)

    async def paginate(self, q: Select[tuple[M]], params: PageParams) -> tuple[Sequence[M], PaginationMeta]:
        total = (await self.db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        if params.sort:
            col = getattr(self._m, params.sort.lstrip("-"), None)
            if col is not None:
                q = q.order_by(col.desc() if params.sort.startswith("-") else col.asc())
        rows = (await self.db.execute(q.offset(params.offset).limit(params.page_size))).scalars().all()
        return rows, PaginationMeta(
            page=params.page,
            page_size=params.page_size,
            total=total,
            total_pages=max(1, -(-total // params.page_size)),
        )

    # ---- writes -------------------------------------------------------------------------------------------
    async def create(self, **values: Any) -> M:
        obj = self.model(**values)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, obj: M, expected_version: int | None = None, **values: Any) -> M:
        current = getattr(obj, "version", None)
        if expected_version is not None and current not in (None, expected_version):
            raise APIError(
                409, ErrorCode.STALE_VERSION, "Record was modified by someone else", {"current_version": current}
            )
        for k, v in values.items():
            setattr(obj, k, v)
        await self.db.flush()
        return obj

    async def soft_delete(self, obj: M, by: Any) -> None:
        row = cast(Any, obj)
        row.is_active = False
        row.deleted_at = datetime.now(UTC)
        row.deleted_by = by
        await self.db.flush()
