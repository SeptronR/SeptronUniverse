"""Help centre — Prompts/01 §01.6 (``help_articles``: platform articles + the tenant's own).

Business rules
1. Everyone in an institution reads the published articles of that institution **plus** platform articles
   (``institution_id IS NULL``); a tenant article with the same ``slug`` overrides the platform one.
2. ``?module=`` narrows to a module key; ``?q=`` is a case-insensitive title/body match (help centre search box).
3. Authoring lands with Phase 38 (``services/saas/support_service.py``: platform articles by ``platform:help``,
   institution articles by the tenant's ``settings:manage``); Phase 01 seeds platform articles.
4. Phase 38: ``?route=/admin/fees/collect`` returns the contextual article ``help:<route>`` (tenant override first,
   then the platform one; a route without its own article falls back to the closest parent route) ahead of the
   module's articles; articles whose ``audience.roles`` / ``audience.portals`` are set are shown only to matching
   users (institution admins see everything).
"""

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

    async def list(
        self, module: str | None = None, q: str | None = None, route: str | None = None
    ) -> list[HelpArticleSummary]:
        rows: list[HelpArticle] = [r for r in await self.repo.list(module=module, q=q) if self._audience_ok(r)]
        if route:
            contextual = await self.contextual(route)
            if contextual is not None:
                rows = [contextual, *[r for r in rows if r.slug != contextual.slug]]
        return [self._summary(r) for r in rows]

    async def contextual(self, route: str) -> HelpArticle | None:
        path = "/" + route.strip("/")
        while path:
            row = await self.repo.get_by_slug(f"help:{path}")
            if row is not None and self._audience_ok(row):
                return row
            if path == "/":
                break
            path = path.rsplit("/", 1)[0] or "/"
        return None

    def _audience_ok(self, row: HelpArticle) -> bool:
        aud = row.audience if isinstance(row.audience, dict) else {}
        roles = set(aud.get("roles") or [])
        if not roles or self.principal.is_super_admin or "institution_admin" in self.principal.roles:
            return True
        return bool(roles & set(self.principal.roles))

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
            audience=row.audience if isinstance(row.audience, list) else list((row.audience or {}).get("roles") or []),
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
