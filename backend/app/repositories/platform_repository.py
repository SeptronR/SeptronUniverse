"""Platform repositories — Prompts/01 §01.5. All SQL of the platform module lives here (coding standard 1).

* ``JobRepository`` — ``background_jobs`` with the ``jobs`` visibility module (self = requester; ``jobs:view_all`` =
  institution scope; super admin = all);
* ``SearchRepository`` — ``search_documents`` materialized view (``plainto_tsquery``) narrowed to the principal's
  institution / colleges;
* ``HelpRepository`` — platform articles (``institution_id IS NULL``) + the tenant's published articles;
* ``FeedbackRepository`` — ``feedback_entries`` (self; ``settings:view_all`` sees the institution);
* ``ReadOnlyModeRepository`` — ``read_only_modes`` windows;
* ``PlatformConfigRepository`` — read-only lookups for the public/mobile config (institution by slug, plan quota,
  ``platform_settings`` keys) on tables later phases model in full.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import BackgroundJob, College, FeedbackEntry, HelpArticle, Institution, ReadOnlyMode
from app.repositories.base import BaseRepository
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta

SEARCH_ROUTES = {
    "student": "/admin/students/{id}",
    "staff": "/staff/{id}",
    "course": "/courses/{id}",
    "applicant": "/admissions/applicants/{id}",
}
SEARCH_ENTITIES = tuple(SEARCH_ROUTES)


class JobRepository(BaseRepository[BackgroundJob]):
    model = BackgroundJob
    module = "jobs"

    async def list_jobs(
        self, params: PageParams, scope: str | None, status: str | None, job_type: str | None
    ) -> tuple[Sequence[BackgroundJob], PaginationMeta]:
        q = self.visible(self._base(), scope)
        if status:
            q = q.where(BackgroundJob.status == status)
        if job_type:
            q = q.where(BackgroundJob.job_type == job_type)
        if not params.sort:
            q = q.order_by(BackgroundJob.created_at.desc())
        return await self.paginate(q, params)

    async def purge_succeeded(self, older_than: datetime) -> Sequence[BackgroundJob]:
        """Rows to purge: succeeded before ``older_than`` or past their ``expires_at`` (files are deleted by the service)."""
        q = select(BackgroundJob).where(
            or_(
                (BackgroundJob.status == "succeeded") & (BackgroundJob.finished_at < older_than),
                (BackgroundJob.expires_at.is_not(None)) & (BackgroundJob.expires_at < older_than),
            )
        )
        return (await self.db.execute(q)).scalars().all()

    async def request_cancel(self, job: BackgroundJob) -> BackgroundJob:
        values: dict[str, Any] = {"cancel_requested": True}
        if job.status == "queued":  # never started: the wrapper would skip it, so close it now
            values.update(status="cancelled", finished_at=datetime.now(UTC))
        await self.db.execute(update(BackgroundJob).where(BackgroundJob.id == job.id).values(**values))
        await self.db.refresh(job)
        return job


class SearchRepository:
    """Queries the ``search_documents`` materialized view (Database_Schema.sql §35)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(
        self,
        institution_id: uuid.UUID | None,
        q: str,
        entity_types: Sequence[str],
        college_ids: Sequence[uuid.UUID] | None = None,
        limit: int = 20,
        student_ids: Any = None,
    ) -> list[dict[str, Any]]:
        """``student_ids``: optional ``SELECT students.id`` (Phase 07 visibility) — student rows outside it are dropped
        inside the query, so the limit applies to visible rows only."""
        if not entity_types or not q.strip():
            return []
        sql = (
            "SELECT entity_type, entity_id, institution_id, college_id, title, subtitle, "
            "ts_rank(tsv, plainto_tsquery('simple', :q)) AS rank "
            "FROM search_documents WHERE tsv @@ plainto_tsquery('simple', :q) "
            "AND entity_type = ANY(:types)"
        )
        params: dict[str, Any] = {"q": q.strip(), "types": list(entity_types), "limit": limit}
        if institution_id is not None:
            sql += " AND institution_id = :inst"
            params["inst"] = institution_id
        if college_ids is not None:
            # college-scoped principals: rows of their colleges plus institution-wide rows (college_id IS NULL)
            sql += " AND (college_id IS NULL OR college_id = ANY(:colleges))"
            params["colleges"] = list(college_ids)
        if student_ids is not None and "student" in entity_types:
            compiled = student_ids.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
            sql += f" AND (entity_type <> 'student' OR entity_id IN ({compiled}))"  # noqa: S608 - SQLAlchemy-compiled
        sql += " ORDER BY rank DESC, title LIMIT :limit"
        rows = (await self.db.execute(text(sql), params)).mappings().all()
        return [dict(r) for r in rows]

    async def refresh(self) -> None:
        """``REFRESH MATERIALIZED VIEW CONCURRENTLY`` (needs the unique index the DDL creates)."""
        await self.db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY search_documents"))


class HelpRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID | None):
        self.db = db
        self.institution_id = institution_id

    def _scope(self) -> Any:
        if self.institution_id is None:
            return HelpArticle.institution_id.is_(None)
        return or_(HelpArticle.institution_id.is_(None), HelpArticle.institution_id == self.institution_id)

    async def list(self, module: str | None = None, q: str | None = None) -> Sequence[HelpArticle]:
        stmt = select(HelpArticle).where(HelpArticle.is_published.is_(True), self._scope())
        if module:
            stmt = stmt.where(HelpArticle.module == module)
        if q:
            stmt = stmt.where(or_(HelpArticle.title.ilike(f"%{q}%"), HelpArticle.body.ilike(f"%{q}%")))
        # tenant articles override platform ones with the same slug: order tenant first, then title
        stmt = stmt.order_by(HelpArticle.institution_id.is_(None), HelpArticle.module, HelpArticle.title)
        rows = list((await self.db.execute(stmt)).scalars().all())
        seen: set[str] = set()
        out: list[HelpArticle] = []
        for r in rows:
            if r.slug in seen:
                continue
            seen.add(r.slug)
            out.append(r)
        return out

    async def get_by_slug(self, slug: str) -> HelpArticle | None:
        stmt = (
            select(HelpArticle)
            .where(HelpArticle.is_published.is_(True), HelpArticle.slug == slug, self._scope())
            .order_by(HelpArticle.institution_id.is_(None))
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()


class FeedbackRepository(BaseRepository[FeedbackEntry]):
    model = FeedbackEntry
    module = "feedback"

    async def list_visible(self, params: PageParams) -> tuple[Sequence[FeedbackEntry], PaginationMeta]:
        """Self rows; ``settings:view_all`` (or super admin) sees the whole institution (Prompts/01 visibility rules)."""
        q = self._base()
        if self.principal and not self.principal.is_super_admin and not self.principal.has("settings", "view_all"):
            q = q.where(FeedbackEntry.user_id == self.principal.id)
        return await self.paginate(q.order_by(FeedbackEntry.created_at.desc()), params)


class ReadOnlyModeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def active(self, now: datetime) -> Sequence[ReadOnlyMode]:
        stmt = select(ReadOnlyMode).where(
            ReadOnlyMode.is_active.is_(True),
            ReadOnlyMode.starts_at <= now,
            or_(ReadOnlyMode.ends_at.is_(None), ReadOnlyMode.ends_at > now),
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def active_for(self, institution_id: uuid.UUID | None, now: datetime) -> ReadOnlyMode | None:
        stmt = (
            select(ReadOnlyMode)
            .where(
                ReadOnlyMode.is_active.is_(True),
                ReadOnlyMode.starts_at <= now,
                or_(ReadOnlyMode.ends_at.is_(None), ReadOnlyMode.ends_at > now),
                (
                    ReadOnlyMode.institution_id.is_(None)
                    if institution_id is None
                    else ReadOnlyMode.institution_id == institution_id
                ),
            )
            .order_by(ReadOnlyMode.starts_at.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def deactivate(self, institution_id: uuid.UUID | None) -> int:
        stmt = (
            update(ReadOnlyMode)
            .where(
                ReadOnlyMode.is_active.is_(True),
                (
                    ReadOnlyMode.institution_id.is_(None)
                    if institution_id is None
                    else ReadOnlyMode.institution_id == institution_id
                ),
            )
            .values(is_active=False)
        )
        result: Any = await self.db.execute(stmt)
        return int(result.rowcount or 0)

    async def create(
        self, institution_id: uuid.UUID | None, reason: str | None, ends_at: datetime | None, set_by: uuid.UUID | None
    ) -> ReadOnlyMode:
        row = ReadOnlyMode(institution_id=institution_id, reason=reason, ends_at=ends_at, set_by=set_by, is_active=True)
        self.db.add(row)
        await self.db.flush()
        return row

    async def expire(self, now: datetime) -> Sequence[ReadOnlyMode]:
        """Deactivate windows whose ``ends_at`` has passed; returns them so the service can clear the cache."""
        stmt = select(ReadOnlyMode).where(
            ReadOnlyMode.is_active.is_(True), ReadOnlyMode.ends_at.is_not(None), ReadOnlyMode.ends_at <= now
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        for r in rows:
            r.is_active = False
        await self.db.flush()
        return rows


class PlatformConfigRepository:
    """Read-only lookups for the public/mobile config endpoints and quotas (no principal: public routes)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def institution_by_slug(self, slug: str) -> Institution | None:
        stmt = select(Institution).where(
            Institution.slug == slug, Institution.deleted_at.is_(None), Institution.status.in_(["active", "pending"])
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def colleges_of(self, institution_id: uuid.UUID) -> Sequence[College]:
        stmt = (
            select(College)
            .where(College.institution_id == institution_id, College.deleted_at.is_(None), College.is_active.is_(True))
            .order_by(College.is_main.desc(), College.name)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def platform_setting(self, key: str) -> Any | None:
        row = (await self.db.execute(text("SELECT value FROM platform_settings WHERE key = :k"), {"k": key})).first()
        return row[0] if row else None

    async def institution_setting(self, institution_id: uuid.UUID, category: str, key: str) -> Any | None:
        """Institution-wide setting value (``college_id IS NULL``) — Phase 03 models ``institution_settings`` in full."""
        row = (
            await self.db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND college_id IS NULL "
                    "AND category = :c AND key = :k"
                ),
                {"i": institution_id, "c": category, "k": key},
            )
        ).first()
        return row[0] if row else None

    async def plan_storage_gb(self, institution_id: uuid.UUID) -> int | None:
        """Storage quota of the tenant's current plan (``institution_subscriptions`` → ``subscription_plans``)."""
        row = (
            await self.db.execute(
                text(
                    "SELECT p.storage_gb FROM institution_subscriptions s JOIN subscription_plans p ON p.id = s.plan_id "
                    "WHERE s.institution_id = :i AND s.status IN ('trial','active','grace') "
                    "ORDER BY s.starts_on DESC LIMIT 1"
                ),
                {"i": institution_id},
            )
        ).first()
        return int(row[0]) if row and row[0] is not None else None
