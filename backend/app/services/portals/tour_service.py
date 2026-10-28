"""Guided tours — Prompts/39 §39.6 ``tour_service`` (``platform.guided_tours``).

Business rules
1. Registry: ``frontend/src/tours/*.ts`` is the source; ``npm run tours:export`` writes
   ``app/core/tours_snapshot.json`` (served here and stored in ``platform_settings['tours']`` by ``0039``).
2. ``definitions(route)``: tours whose route matches (exact, or a ``:param`` pattern) and whose roles intersect the
   caller's (``*`` = everyone); routes listed in ``tours.disabled`` return nothing.
3. State in ``users.preferences['tours']`` = ``{completed: {key: version}, dismissed: [key]}``; a tour auto-starts
   when its version is newer than the completed one and it was not dismissed; ``reset`` clears both (restart).
4. Completion / dismissal emit ``portal.tour_completed|dismissed`` and bump ``tours:stats:{key}`` (Redis hash,
   ``completed`` / ``dismissed``) for the Phase 38 platform dashboard.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core import events
from app.db.session import redis_client
from app.schemas.portals import TourDef, TourStateIn, TourStateOut
from app.services.portals.common import PortalBase

SNAPSHOT = Path(__file__).resolve().parents[2] / "core" / "tours_snapshot.json"


@lru_cache(maxsize=1)
def registry() -> tuple[TourDef, ...]:
    if not SNAPSHOT.exists():
        return ()
    return tuple(TourDef.model_validate(t) for t in json.loads(SNAPSHOT.read_text(encoding="utf-8")))


def _matches(pattern: str, route: str) -> bool:
    rx = "^" + re.sub(r":[A-Za-z_]+", "[^/]+", pattern.rstrip("/") or "/") + "/?$"
    return re.match(rx, route.rstrip("/") or "/") is not None


class TourService(PortalBase):
    def _state(self) -> dict[str, Any]:
        raw = (self.principal.user.preferences or {}).get("tours") or {}
        return {"completed": dict(raw.get("completed") or {}), "dismissed": list(raw.get("dismissed") or [])}

    async def disabled_routes(self) -> list[str]:
        return list(await self.setting("tours", "disabled") or [])

    async def definitions(self, route: str | None) -> list[TourDef]:
        disabled = await self.disabled_routes()
        roles = set(self.principal.roles)
        out = []
        for t in registry():
            if any(_matches(d, t.route) or d == t.route for d in disabled):
                continue
            if route and not _matches(t.route, route):
                continue
            if "*" not in t.roles and not (roles & set(t.roles)) and not self.principal.is_super_admin:
                continue
            out.append(t)
        return out

    async def state(self) -> TourStateOut:
        s = self._state()
        return TourStateOut(
            completed=s["completed"], dismissed=s["dismissed"], disabled_routes=await self.disabled_routes()
        )

    async def update(self, body: TourStateIn) -> TourStateOut:
        s = self._state()
        if body.reset:
            s["completed"].pop(body.key, None)
            s["dismissed"] = [k for k in s["dismissed"] if k != body.key]
        if body.completed:
            s["completed"][body.key] = body.version
            s["dismissed"] = [k for k in s["dismissed"] if k != body.key]
        if body.dismissed and body.key not in s["dismissed"]:
            s["dismissed"].append(body.key)
        prefs = dict(self.principal.user.preferences or {})
        prefs["tours"] = s
        self.principal.user.preferences = prefs
        await self.db.execute(
            text("UPDATE users SET preferences = CAST(:p AS jsonb) WHERE id = :u"),
            {"p": json.dumps(prefs, default=str), "u": self.principal.id},
        )
        if body.completed or body.dismissed:
            kind = "completed" if body.completed else "dismissed"
            await redis_client.hincrby(  # type: ignore[misc]
                f"tours:stats:{body.key}", kind, 1
            )
            await events.emit(
                self.db,
                institution_id=self.inst,
                event_type=f"portal.tour_{kind}",
                payload={"user_id": str(self.principal.id), "key": body.key, "version": body.version},
                aggregate_type="user",
                aggregate_id=self.principal.id,
                actor_user_id=self.principal.id,
            )
        return await self.state()
