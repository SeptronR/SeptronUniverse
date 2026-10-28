"""Contextual help — Prompts/39 §39.6 ``help_context_service`` (``platform.help_center``).

``context(route)``: the Phase 38 contextual article ``help:<route>`` (institution override → platform, closest parent
route) plus up to 5 related articles of the same module and the tours registered for the route. ``helpful(slug)``
increments ``help:helpful:{slug}`` (``helpful`` / ``not_helpful``) once per user per article (``help:voted:{slug}``
set) — the counters the Phase 38 authoring list already reads.
"""

from typing import Any

from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client
from app.schemas.portals import HelpContextOut, HelpfulOut
from app.services.help_service import HelpService
from app.services.portals.common import PortalBase
from app.services.portals.tour_service import TourService


class HelpContextService(PortalBase):
    async def context(self, route: str) -> HelpContextOut:
        help_svc = HelpService(self.db, self.principal)
        article = await help_svc.contextual(route)
        related: list[dict[str, Any]] = []
        art: dict[str, Any] | None = None
        if article is not None:
            art = {
                "slug": article.slug,
                "title": article.title,
                "body": article.body,
                "module": article.module,
                "is_platform": article.institution_id is None,
                "updated_at": article.updated_at.isoformat() if article.updated_at else None,
            }
            if article.module:
                related = [
                    s.model_dump(mode="json")
                    for s in await help_svc.list(module=article.module)
                    if s.slug != article.slug
                ][:5]
        tours: list[str] = []
        if self.principal.has_feature("platform.guided_tours"):
            tours = [t.key for t in await TourService(self.db, self.principal).definitions(route)]
        return HelpContextOut(route=route, article=art, related=related, tours=tours)

    async def helpful(self, slug: str, helpful: bool) -> HelpfulOut:
        if await HelpService(self.db, self.principal).repo.get_by_slug(slug) is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Help article not found")
        voted = await redis_client.sadd(  # type: ignore[misc]
            f"help:voted:{slug}", str(self.principal.id)
        )
        if voted:
            await redis_client.hincrby(  # type: ignore[misc]
                f"help:helpful:{slug}", "helpful" if helpful else "not_helpful", 1
            )
        v = await redis_client.hgetall(  # type: ignore[misc]
            f"help:helpful:{slug}"
        )
        return HelpfulOut(slug=slug, helpful=int(v.get("helpful", 0)), not_helpful=int(v.get("not_helpful", 0)))
