"""Help centre — Prompts/01 §01.6 (``help_articles``: platform articles + the tenant's own).

Business rules
1. Everyone in an institution reads the published articles of that institution **plus** platform articles
   (``institution_id IS NULL``); a tenant article with the same ``slug`` overrides the platform one.
2. ``?module=`` narrows to a module key; ``?q=`` is a case-insensitive title/body match (help centre search box).
3. Authoring (create/update/publish) lands with the settings UI in Phase 37; Phase 01 seeds platform articles
   (``scripts/seeders/platform.py``) and reads them.
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal
from app.core.errors import APIError, ErrorCode
from app.models.platform import HelpArticle
from app.repositories.platform_repository import HelpRepository
from app.schemas.platform import HelpArticleResponse, HelpArticleSummary


class HelpService:
    def __init__(self, db: AsyncSession, principal: Principal):
        self.db, self.principal = db, principal
        self.repo = HelpRepository(db, principal.institution_id)

    async def list(self, module: str | None = None, q: str | None = None) -> list[HelpArticleSummary]:
        rows: Sequence[HelpArticle] = await self.repo.list(module=module, q=q)
        return [self._summary(r) for r in rows]

    async def get(self, slug: str) -> HelpArticleResponse:
        row = await self.repo.get_by_slug(slug)
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Help article not found")
        return HelpArticleResponse(
            id=row.id,
            slug=row.slug,
            title=row.title,
            body=row.body,
            module=row.module,
            audience=row.audience,
            is_platform=row.institution_id is None,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _summary(row: HelpArticle) -> HelpArticleSummary:
        return HelpArticleSummary(
            id=row.id,
            slug=row.slug,
            title=row.title,
            module=row.module,
            is_platform=row.institution_id is None,
            updated_at=row.updated_at,
        )
