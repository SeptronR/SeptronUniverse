"""Programmes, regulations & curriculum tasks — Prompts/05 §05.7.

Jobs: ``jobs.courses.bulk_import`` — CSV rows through ``CourseService.create`` (one savepoint per row), report
``{total, succeeded, failed[{row, code, error, message}]}`` in ``background_jobs.result``; the job runs as the
requesting user (``load_principal``) so department scopes and audit apply exactly as for the API.
Consumers: ``catalog.invalidate`` ← ``program.*``, ``course.*``, ``regulation.*``, ``curriculum.replaced`` (drops the
tenant's public-catalogue cache). ``search.reindex`` already listens to ``course.*`` (Phase 01). Beat: none.
"""

import uuid
from typing import Any

import structlog

from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.outbox import consumer

log = structlog.get_logger()


@celery.task(name="jobs.courses.bulk_import", queue="reports")
@job("courses.bulk_import", queue="reports")
async def courses_bulk_import(ctx: JobContext, db: Any, regulation_id: str, csv: str, **_: Any) -> dict[str, Any]:
    from app.core.errors import APIError
    from app.services.auth_service import load_principal
    from app.services.course_service import CourseService

    if ctx.requested_by is None:
        raise APIError(422, "VALIDATION", "courses.bulk_import needs the requesting user")
    principal = await load_principal(db, ctx.requested_by)

    async def progress(pct: int, message: str) -> None:
        await ctx.progress(db, pct, message)

    report = await CourseService(db, principal).run_bulk_import(uuid.UUID(regulation_id), csv, progress)
    await ctx.progress(db, 100, f"{report['succeeded']} imported, {len(report['failed'])} failed")
    return report


@consumer("catalog.invalidate", events=["program.*", "course.*", "regulation.*", "curriculum.replaced"])
async def catalog_invalidate(db: Any, event: dict[str, Any]) -> None:
    from app.services.catalog_service import invalidate_catalog

    institution_id = event.get("institution_id")
    if institution_id:
        dropped = await invalidate_catalog(institution_id)
        if dropped:
            log.info("catalog_cache_invalidated", institution_id=str(institution_id), keys=dropped)
