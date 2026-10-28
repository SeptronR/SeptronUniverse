"""Tasks of Phase 40 — Prompts/40 §40.7 (public website).

Jobs: ``website.gallery_bulk_upload`` (zip → images only, EXIF stripped by re-encoding, 400 px thumbnails, per-file
report), ``website.enquiry_export`` (xlsx). Beat (UTC): ``website.notices_schedule`` (5 min: windows that opened /
closed → ``website.notice_published|expired`` + cache bump), ``website.domain_verify_retry`` (15 min, 72 h),
``website.cache_sweep`` (hourly: the versioned page keys expire on their own — drops orphaned ``host:`` entries),
``website.sitemap_daily`` (21:30 UTC = 03:00 IST, warms the home page and sitemap per enabled site),
``website.analytics_rollup`` (daily: copies yesterday's counters into ``website_meta analytics:<date>``).
Consumers: ``enquiry.stage_changed`` → website enquiry status; ``events.cancelled`` → mirrored event unpublished;
content / catalogue / disclosure / settings changes of the owning modules → page-cache version bump.
"""

import io
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.outbox import consumer

log = structlog.get_logger()
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")


async def _platform(fn: Any) -> Any:
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        try:
            out = await fn(db)
            await db.commit()
            return out
        except Exception:
            await db.rollback()
            raise


def strip_exif(data: bytes) -> tuple[bytes, bytes]:
    """Re-encode without metadata (GPS / camera) → (image, 400 px thumbnail)."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as src:
        im = src.convert("RGB")
        clean = io.BytesIO()
        im.save(clean, "JPEG", quality=85, optimize=True)
        im.thumbnail((400, 400))
        thumb = io.BytesIO()
        im.save(thumb, "JPEG", quality=80)
    return clean.getvalue(), thumb.getvalue()


@celery.task(name="jobs.website.gallery_bulk_upload", queue="reports")
@job("website.gallery_bulk_upload", queue="reports")
async def gallery_bulk_upload(ctx: JobContext, db: Any, album_id: str, zip_url: str, **_: Any) -> dict[str, Any]:
    from app.core.files import storage
    from app.models.website import GalleryImage

    key = zip_url.split("?")[0].split("/files/")[-1]
    raw = await storage.get(key)
    ok, failed, errors = 0, 0, []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for n, info in enumerate(zf.infolist()[:500]):
            if info.is_dir():
                continue
            name = info.filename.rsplit("/", 1)[-1]
            try:
                if not name.lower().endswith(IMAGE_EXT) or info.file_size > 15 * 1024 * 1024:
                    raise ValueError("not an image")
                clean, thumb = strip_exif(zf.read(info))
                k = f"{ctx.institution_id}/website/gallery/{album_id}/{uuid.uuid4().hex}.jpg"
                await storage.put(k, clean, "image/jpeg")
                await storage.put(k.replace(".jpg", "-thumb.jpg"), thumb, "image/jpeg")
                db.add(
                    GalleryImage(
                        institution_id=ctx.institution_id,
                        album_id=uuid.UUID(album_id),
                        image_url=f"/files/{k}",
                        caption=name[:200],
                        sequence=n + 1,
                    )
                )
                ok += 1
            except Exception as exc:  # noqa: BLE001 - per-file report
                failed += 1
                errors.append({"file": name, "error": str(exc)[:120]})
    await db.flush()
    from app.services.website.common import invalidate

    await invalidate(ctx.institution_id)
    return {"succeeded": ok, "failed": failed, "errors": errors[:50]}


@celery.task(name="jobs.website.enquiry_export", queue="reports")
@job("website.enquiry_export", queue="reports")
async def enquiry_export(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.core.files import storage
    from app.services.reports.render_service import xlsx_sheets

    rows = (
        (
            await db.execute(
                text(
                    "SELECT name, email, phone, subject, message, source_page, status, created_at FROM website_enquiries WHERE institution_id = :i ORDER BY created_at DESC"
                ),
                {"i": ctx.institution_id},
            )
        )
        .mappings()
        .all()
    )
    data = xlsx_sheets(
        {"Enquiries": [{k: (str(v) if v is not None else "") for k, v in dict(r).items()} for r in rows]}
    )
    key = f"{ctx.institution_id}/website/exports/enquiries-{date.today().isoformat()}-{uuid.uuid4().hex[:6]}.xlsx"
    await storage.put(key, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return {"rows": len(rows), "result_url": storage.signed_url(key)}


# ---- Beat -----------------------------------------------------------------------------------------------------------------
@celery.task(name="beat.website.notices_schedule", queue="scheduled")
def notices_schedule() -> dict[str, int]:
    async def fn(db: Any) -> dict[str, int]:
        from app.core import events
        from app.services.website.common import invalidate

        since = datetime.now(UTC) - timedelta(minutes=6)
        opened = (
            await db.execute(
                text(
                    "SELECT id, institution_id, slug, category FROM website_notices WHERE is_published AND publish_at > :s AND publish_at <= NOW()"
                ),
                {"s": since},
            )
        ).all()
        closed = (
            await db.execute(
                text(
                    "SELECT id, institution_id FROM website_notices WHERE is_published AND expires_at > :s AND expires_at <= NOW()"
                ),
                {"s": since},
            )
        ).all()
        insts = set()
        for nid, iid, slug, cat in opened:
            await events.emit(
                db,
                institution_id=iid,
                event_type="website.notice_published",
                payload={"id": str(nid), "slug": slug, "category": cat},
                aggregate_type="website_notice",
                aggregate_id=nid,
            )
            insts.add(iid)
        for nid, iid in closed:
            await events.emit(
                db,
                institution_id=iid,
                event_type="website.notice_expired",
                payload={"id": str(nid)},
                aggregate_type="website_notice",
                aggregate_id=nid,
            )
            insts.add(iid)
        for iid in insts:
            await invalidate(iid)
        return {"published": len(opened), "expired": len(closed)}

    out: dict[str, int] = run_async(_platform(fn))
    log.info("beat_website_notices_schedule", **out)
    return out


@celery.task(name="beat.website.domain_verify_retry", queue="scheduled")
def domain_verify_retry() -> dict[str, int]:
    from app.services.website.domain_service import retry_unverified

    return {"verified": run_async(_platform(retry_unverified))}


@celery.task(name="beat.website.cache_sweep", queue="scheduled")
def cache_sweep() -> dict[str, int]:
    async def fn(db: Any) -> dict[str, int]:
        from app.db.session import redis_client

        dropped = 0
        async for k in redis_client.scan_iter(match="host:*", count=500):
            host = str(k).split(":", 1)[1]
            alive = (
                await db.execute(
                    text("SELECT 1 FROM institution_domains WHERE hostname = :h AND verified_at IS NOT NULL"),
                    {"h": host},
                )
            ).first()
            if not alive:
                await redis_client.delete(k)
                dropped += 1
        return {"dropped": dropped}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@celery.task(name="beat.website.sitemap_daily", queue="scheduled")
def sitemap_daily() -> dict[str, int]:
    async def fn(db: Any) -> dict[str, int]:
        from app.db.session import bind_tenant, set_tenant
        from app.services.website.site_service import SiteService

        n = 0
        for (iid,) in (
            await db.execute(
                text(
                    "SELECT c.institution_id FROM institution_website_config c JOIN institutions i ON i.id = c.institution_id WHERE c.is_enabled AND i.deleted_at IS NULL"
                )
            )
        ).all():
            try:
                bind_tenant(db, iid)
                await set_tenant(db, iid)
                await SiteService(db, None, None, iid).ssr("", False, "")
                n += 1
            except Exception as exc:  # noqa: BLE001 - one site never stops the warm-up
                log.warning("site_warm_failed", institution_id=str(iid), error=str(exc)[:200])
        return {"warmed": n}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@celery.task(name="beat.website.analytics_rollup", queue="scheduled")
def analytics_rollup() -> dict[str, int]:
    async def fn(db: Any) -> dict[str, int]:
        import json

        from app.db.session import redis_client

        day = (date.today() - timedelta(days=1)).isoformat()
        n = 0
        for (iid,) in (await db.execute(text("SELECT institution_id FROM institution_website_config"))).all():
            pv = await redis_client.hgetall(f"site:pv:{iid}:{day}")  # type: ignore[misc]
            uv = await redis_client.pfcount(f"site:uv:{iid}:{day}")
            if not pv:
                continue
            await db.execute(
                text(
                    "INSERT INTO institution_settings (id, institution_id, college_id, category, key, value, value_type, is_public, created_at, updated_at) "
                    "VALUES (:id, :i, NULL, 'website_meta', :k, CAST(:v AS jsonb), 'json', FALSE, NOW(), NOW()) "
                    "ON CONFLICT (institution_id, college_id, category, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
                ),
                {
                    "id": uuid.uuid4(),
                    "i": iid,
                    "k": f"analytics:{day}",
                    "v": json.dumps({"pageviews": sum(int(v) for v in pv.values()), "visitors": int(uv)}),
                },
            )
            n += 1
        return {"sites": n}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


# ---- consumers ------------------------------------------------------------------------------------------------------------
@consumer("website.enquiry_sync", events=["enquiry.stage_changed"])
async def enquiry_sync(db: Any, event: dict[str, Any]) -> None:
    from app.services.website.enquiry_service import sync_stage

    p = event.get("payload") or {}
    if event.get("institution_id") and p.get("enquiry_id") and p.get("stage"):
        await sync_stage(db, uuid.UUID(str(event["institution_id"])), str(p["enquiry_id"]), str(p["stage"]))


@consumer("website.event_sync", events=["events.cancelled", "event.cancelled"])
async def event_sync(db: Any, event: dict[str, Any]) -> None:
    p = event.get("payload") or {}
    eid = p.get("event_id") or p.get("id")
    if eid and event.get("institution_id"):
        await db.execute(
            text("UPDATE website_events SET is_published = FALSE WHERE institution_id = :i AND event_id = :e"),
            {"i": event["institution_id"], "e": eid},
        )
        from app.services.website.common import invalidate

        await invalidate(event["institution_id"])


@consumer(
    "website.cache_invalidate",
    events=[
        "institution.updated",
        "settings.changed",
        "program.*",
        "regulation.*",
        "curriculum.*",
        "admission_cycle.*",
        "policy.*",
        "affiliation.*",
        "accreditation.disclosures_refreshed",
        "analytics.kpi_refreshed",
        "feature_flag.changed",
    ],
)
async def cache_invalidate(db: Any, event: dict[str, Any]) -> None:
    if event.get("institution_id"):
        from app.services.website.common import invalidate

        await invalidate(event["institution_id"])
