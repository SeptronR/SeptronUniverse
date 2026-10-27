"""Read-model service — Prompts/35 §35.5 ``refresh_repository`` / §35.6 ``readmodel_service``.

* Refresh: ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` under ``pg_try_advisory_lock`` per view, run on the owning platform
  role (``PlatformSessionLocal`` — matviews are owned by the migrating role and carry no RLS). Bookkeeping in Redis
  ``mv:{view}:refreshed_at`` / ``mv:{view}:duration_ms`` / ``mv:{view}:rows``. ``mv_kpi_daily`` is refreshed after the
  views it reads. After each ``mv_kpi_daily`` refresh the ``dashboard:{institution}`` channel gets ``kpi.refreshed``.
* Scheduler (Beat ``analytics.refresh_scheduler``, every 5 min): refresh a view when its interval
  (``analytics.refresh_minutes``) elapsed **and** a source event marked it dirty since (``mv_dirty:{institution}:{view}``).
* Invalidation (outbox consumers): mark the views fed by the event's module dirty and bump
  ``chartver:{institution}:{module}`` so cached chart payloads are never served again.
* Health: ``stale`` = refreshed longer ago than twice the interval (or never).
"""

import contextlib
import time
import uuid
import zlib
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text

from app.services.analytics.common import AnalyticsBase, rule
from app.services.analytics.read_models import BY_NAME, READ_MODELS, SOURCE_VIEWS, VIEW_NAMES

__all__ = ["DEFAULT_REFRESH", "EVENT_MODULES", "ReadModelService", "refresh_views"]

log = structlog.get_logger()

DEFAULT_REFRESH: dict[str, int] = {"mv_kpi_daily": 15, "mv_attendance_term": 60, "mv_fees_position": 30, "default": 120}

# event prefix → source module (read_models.SOURCE_VIEWS) and the chart modules whose cache it drops
EVENT_MODULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "student": ("students", ("students", "mentoring")),
    "registration": ("registration", ("registration", "offerings")),
    "attendance": ("attendance", ("attendance",)),
    "marks": ("assessment", ("marks", "lms")),
    "fees": ("fees", ("fees", "scholarships", "no_dues")),
    "exams": ("exams", ("exams",)),
    "results": ("results", ("results",)),
    "hr": ("hr", ("hr", "recruitment")),
    "leave": ("leaves", ("leaves", "hr")),
    "admissions": ("admissions", ("admissions",)),
    "hostel": ("hostel", ("hostel",)),
    "library": ("library", ("library",)),
    "placement": ("placement", ("placement",)),
    "service_request": ("facilities", ("facilities",)),
    "grievance": ("grievances", ("grievances",)),
    "risk": ("mentoring", ("mentoring",)),
    "metrics": ("accreditation", ("accreditation",)),
    "affiliation": ("affiliation", ("affiliation",)),
    "research": ("research", ("research", "phd")),
    "phd": ("phd", ("phd",)),
}


def _lock_key(view: str) -> int:
    return zlib.crc32(f"mv:{view}".encode()) & 0x7FFFFFFF


async def _redis() -> Any:
    from app.db.session import redis_client

    return redis_client


async def refresh_views(views: list[str] | None = None, *, concurrently: bool = True) -> list[dict[str, Any]]:
    """Refresh the views (dependency order: ``mv_kpi_daily`` last) on the platform role; returns per-view status."""
    from app.db.session import PlatformSessionLocal

    wanted = [m.name for m in READ_MODELS if views is None or m.name in views]
    r = await _redis()
    out: list[dict[str, Any]] = []
    async with PlatformSessionLocal() as pdb:
        for name in wanted:
            started = time.monotonic()
            got = (await pdb.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _lock_key(name)})).scalar_one()
            if not got:
                out.append({"view": name, "skipped": "locked"})
                continue
            try:
                try:
                    await pdb.execute(
                        text(f"REFRESH MATERIALIZED VIEW {'CONCURRENTLY ' if concurrently else ''}{name}")
                    )
                    await pdb.commit()
                except Exception as exc:  # noqa: BLE001 - first population / missing unique index → plain refresh
                    await pdb.rollback()
                    log.warning("mv_refresh_concurrent_failed", view=name, error=str(exc)[:200])
                    await pdb.execute(text(f"REFRESH MATERIALIZED VIEW {name}"))
                    await pdb.commit()
                rows = int((await pdb.execute(text(f"SELECT COUNT(*) FROM {name}"))).scalar_one())
                ms = int((time.monotonic() - started) * 1000)
                now = datetime.now(UTC).isoformat()
                try:
                    await r.set(f"mv:{name}:refreshed_at", now)
                    await r.set(f"mv:{name}:duration_ms", str(ms))
                    await r.set(f"mv:{name}:rows", str(rows))
                except Exception:  # noqa: BLE001
                    pass
                out.append({"view": name, "refreshed_at": now, "duration_ms": ms, "rows": rows})
            finally:
                await pdb.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _lock_key(name)})
                await pdb.commit()
    if any(o.get("view") == "mv_kpi_daily" and "rows" in o for o in out):
        await _announce_kpi_refresh()
    return out


async def _announce_kpi_refresh() -> None:
    from app.core.ws import publish
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as pdb:
        ids = [r[0] for r in (await pdb.execute(text("SELECT id FROM institutions WHERE deleted_at IS NULL"))).all()]
    for iid in ids:
        try:
            await publish(f"dashboard:{iid}", {"type": "kpi.refreshed", "at": datetime.now(UTC).isoformat()})
        except Exception:  # noqa: BLE001 - live refresh is optional (polling fallback)
            return


class ReadModelService(AnalyticsBase):
    async def intervals(self) -> dict[str, int]:
        v = await self.a_setting("analytics", "refresh_minutes", DEFAULT_REFRESH)
        return {**DEFAULT_REFRESH, **(v if isinstance(v, dict) else {})}

    async def interval(self, view: str) -> int:
        iv = await self.intervals()
        return int(iv.get(view) or iv.get("default") or 120)

    async def refreshed_at(self, view: str) -> datetime | None:
        try:
            raw = await (await _redis()).get(f"mv:{view}:refreshed_at")
        except Exception:  # noqa: BLE001
            return None
        return datetime.fromisoformat(raw) if raw else None

    async def view_stale(self, view: str) -> bool:
        at = await self.refreshed_at(view)
        if at is None:
            return True
        return (datetime.now(UTC) - at).total_seconds() > 2 * 60 * await self.interval(view)

    async def status(self) -> list[dict[str, Any]]:
        r = await _redis()
        out = []
        for name in VIEW_NAMES:
            at = await self.refreshed_at(name)
            try:
                ms = await r.get(f"mv:{name}:duration_ms")
                rows = await r.get(f"mv:{name}:rows")
                dirty = await r.get(f"mv_dirty:{self.inst}:{name}")
            except Exception:  # noqa: BLE001
                ms = rows = dirty = None
            out.append(
                {
                    "view": name,
                    "description": BY_NAME[name].description,
                    "refreshed_at": at,
                    "duration_ms": int(ms) if ms else None,
                    "rows": int(rows) if rows else None,
                    "stale": await self.view_stale(name),
                    "dirty": int(dirty or 0),
                    "interval_minutes": await self.interval(name),
                }
            )
        return out

    async def request_refresh(self, views: list[str] | None) -> dict[str, Any]:
        from app.core.jobs import enqueue

        bad = [v for v in (views or []) if v not in VIEW_NAMES]
        if bad:
            raise rule("Unknown read model", "UNKNOWN_VIEW", 422, views=bad)
        job = await enqueue(self.db, self.principal, "analytics.refresh_all", {"views": views or []}, queue="reports")
        return {"job_id": str(job.id), "views": views or list(VIEW_NAMES)}

    # ---- dirty tracking / invalidation --------------------------------------------------------------------------------
    async def mark_dirty(self, event_type: str) -> list[str]:
        prefix = event_type.split(".", 1)[0]
        source, chart_modules = EVENT_MODULES.get(prefix, (prefix, (prefix,)))
        views = list(SOURCE_VIEWS.get(source, ())) + ["mv_kpi_daily"]
        r = await _redis()
        try:
            for v in views:
                await r.incr(f"mv_dirty:{self.inst}:{v}")
            for m in chart_modules:
                await r.incr(f"chartver:{self.inst}:{m}")
        except Exception:  # noqa: BLE001
            return []
        return views

    async def invalidate_all_charts(self) -> None:
        from app.core.charts import CHART_REGISTRY

        r = await _redis()
        try:
            for m in {c.module for c in CHART_REGISTRY.values()}:
                await r.incr(f"chartver:{self.inst}:{m}")
        except Exception:  # noqa: BLE001
            return


async def scheduler_tick() -> dict[str, Any]:
    """Beat ``analytics.refresh_scheduler``: views whose interval elapsed and that are dirty for any tenant."""
    from app.db.session import PlatformSessionLocal

    r = await _redis()
    async with PlatformSessionLocal() as pdb:
        tenants = [
            row[0]
            for row in (
                await pdb.execute(text("SELECT id FROM institutions WHERE status = 'active' AND deleted_at IS NULL"))
            ).all()
        ]
        settings_rows = (
            await pdb.execute(
                text(
                    "SELECT institution_id, value FROM institution_settings WHERE category = 'analytics' "
                    "AND key = 'refresh_minutes' AND college_id IS NULL"
                )
            )
        ).all()
    per_inst = {iid: {**DEFAULT_REFRESH, **(v if isinstance(v, dict) else {})} for iid, v in settings_rows}
    due: list[str] = []
    dirty_keys: dict[str, list[str]] = {}
    now = datetime.now(UTC)
    for view in VIEW_NAMES:
        try:
            raw = await r.get(f"mv:{view}:refreshed_at")
        except Exception:  # noqa: BLE001
            raw = None
        age_min = (now - datetime.fromisoformat(raw)).total_seconds() / 60 if raw else 10**9
        for iid in tenants:
            iv = per_inst.get(iid, DEFAULT_REFRESH)
            interval = int(iv.get(view) or iv.get("default") or 120)
            key = f"mv_dirty:{iid}:{view}"
            try:
                dirty = int(await r.get(key) or 0)
            except Exception:  # noqa: BLE001
                dirty = 0
            if (dirty or raw is None) and age_min >= interval:
                if view not in due:
                    due.append(view)
                dirty_keys.setdefault(view, []).append(key)
    if not due:
        return {"refreshed": []}
    if "mv_kpi_daily" not in due and any(v != "mv_kpi_daily" for v in due):
        due.append("mv_kpi_daily")
    out = await refresh_views(sorted(set(due), key=VIEW_NAMES.index))
    for keys in dirty_keys.values():
        for k in keys:
            with contextlib.suppress(Exception):
                await r.delete(k)
    return {"refreshed": [o["view"] for o in out if "rows" in o]}


def tenant_ids_for(event: dict[str, Any]) -> uuid.UUID | None:
    inst = event.get("institution_id")
    return uuid.UUID(str(inst)) if inst else None
