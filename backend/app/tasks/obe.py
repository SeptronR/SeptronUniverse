"""OBE attainment tasks — Prompts/17 §17.7.

Jobs (run as the requesting user): ``obe.co_run`` / ``obe.po_run`` (compute a queued run), ``obe.nba_export``
(Criterion 3 workbook / document → ``result_url``), ``obe.batch_recompute`` (every offering of a term, then the PO
runs of the batches they target). Consumers: ``obe.auto_run`` on ``results.published`` (setting ``obe.auto_run``; CO
runs for every offering of the published result run), ``obe.marks_refresh`` on ``marks.locked`` (recompute an offering
that already has a computed run, at most once per 10 minutes), ``obe.survey_recompute`` on ``surveys.closed``
(Phase 27 — offerings / programmes the survey's responses target). Beat: ``cqi.due_reminders`` (weekly) and
``obe.coverage_digest`` (monthly, OBE coordinators).
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer


@celery.task(name="jobs.obe.co_run", queue="reports")
@job("obe.co_run", queue="reports")
async def co_run(ctx: JobContext, db: Any, run_id: str, **_: Any) -> dict[str, Any]:
    from app.services.obe.co_service import CoAttainmentService

    principal = await _principal(db, ctx)
    run = await CoAttainmentService(db, principal).compute(uuid.UUID(run_id))
    await ctx.progress(db, 100, f"CO run {run.status}")
    return {"run_id": run_id, "status": run.status, "warnings": (run.config_snapshot or {}).get("_warnings") or []}


@celery.task(name="jobs.obe.po_run", queue="reports")
@job("obe.po_run", queue="reports")
async def po_run(ctx: JobContext, db: Any, run_id: str, **_: Any) -> dict[str, Any]:
    from app.services.obe.po_service import PoAttainmentService

    principal = await _principal(db, ctx)
    run = await PoAttainmentService(db, principal).compute(uuid.UUID(run_id))
    await ctx.progress(db, 100, f"PO run {run.status}")
    return {"run_id": run_id, "status": run.status, "warnings": (run.config_snapshot or {}).get("_warnings") or []}


@celery.task(name="jobs.obe.nba_export", queue="documents")
@job("obe.nba_export", queue="documents")
async def nba_export(ctx: JobContext, db: Any, program_id: str, batch_id: str, format: str = "xlsx", **_: Any) -> dict:
    from app.schemas.obe_attainment import NbaExportRequest
    from app.services.obe.nba_service import NbaExportService

    principal = await _principal(db, ctx)
    out = await NbaExportService(db, principal).build(
        NbaExportRequest(program_id=uuid.UUID(program_id), batch_id=uuid.UUID(batch_id), format=format)  # type: ignore[arg-type]
    )
    await ctx.progress(db, 100, "NBA SAR export ready")
    return out


@celery.task(name="jobs.obe.batch_recompute", queue="reports")
@job("obe.batch_recompute", queue="reports")
async def batch_recompute(
    ctx: JobContext, db: Any, term_id: str, include_indirect: bool = True, **_: Any
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.academic import Batch
    from app.models.offerings import CourseOfferingTarget
    from app.schemas.obe_attainment import PoRunRequest
    from app.services.obe.co_service import CoAttainmentService
    from app.services.obe.po_service import PoAttainmentService

    principal = await _principal(db, ctx)
    co = CoAttainmentService(db, principal)
    offerings = await co.offerings_of_term(uuid.UUID(term_id))
    stats = await co.run_many(offerings, include_indirect)
    await ctx.progress(db, 70, f"{stats['computed']} CO run(s)")
    pairs = (
        await db.execute(
            select(Batch.program_id, Batch.id)
            .join(CourseOfferingTarget, CourseOfferingTarget.batch_id == Batch.id)
            .where(CourseOfferingTarget.offering_id.in_(offerings or [uuid.uuid4()]))
            .distinct()
        )
    ).all()
    po = PoAttainmentService(db, None, institution_id=co.inst)
    for program_id, batch_id in pairs:
        await po.request_run(program_id, batch_id, PoRunRequest(include_indirect=include_indirect), inline=True)
    await ctx.progress(db, 100, f"{len(pairs)} PO run(s)")
    return {**stats, "po_runs": len(pairs)}


async def _attainment_on(iid: uuid.UUID) -> bool:
    from app.core.features import is_enabled

    return await is_enabled(iid, "obe.attainment")


@consumer("obe.auto_run", events=["results.published"])
async def auto_run(db: Any, event: dict[str, Any]) -> None:
    from app.services.obe.co_service import CoAttainmentService

    iid = uuid.UUID(str(event["institution_id"]))
    if not await _attainment_on(iid):
        return
    svc = CoAttainmentService(db, None, institution_id=iid)
    if not await svc.setting("obe", "auto_run"):
        return
    p = event.get("payload") or {}
    if not p.get("run_id"):
        return
    await svc.run_many(await svc.offerings_of_result_run(uuid.UUID(str(p["run_id"]))))


@consumer("obe.marks_refresh", events=["marks.locked"])
async def marks_refresh(db: Any, event: dict[str, Any]) -> None:
    from app.schemas.obe_attainment import CoRunRequest
    from app.services.obe.co_service import CoAttainmentService

    iid = uuid.UUID(str(event["institution_id"]))
    p = event.get("payload") or {}
    if not p.get("offering_id") or not await _attainment_on(iid):
        return
    svc = CoAttainmentService(db, None, institution_id=iid)
    oid = uuid.UUID(str(p["offering_id"]))
    last = await svc.latest_run(oid, computed=False)
    if last is None or last.run_at > datetime.now(UTC) - timedelta(minutes=10):
        return  # never computed (nothing to refresh) or debounced
    await svc.request_run(oid, CoRunRequest(), inline=True)


@consumer("obe.survey_recompute", events=["surveys.closed"])
async def survey_recompute(db: Any, event: dict[str, Any]) -> None:
    from sqlalchemy import select

    from app.models.academic import Batch
    from app.models.obe_attainment import FeedbackResponse, FeedbackSurvey
    from app.schemas.obe_attainment import PoRunRequest
    from app.services.obe.co_service import CoAttainmentService
    from app.services.obe.po_service import PO_SURVEYS, PoAttainmentService

    iid = uuid.UUID(str(event["institution_id"]))
    p = event.get("payload") or {}
    sid = p.get("survey_id") or event.get("aggregate_id")
    if not sid or not await _attainment_on(iid):
        return
    s = (await db.execute(select(FeedbackSurvey).where(FeedbackSurvey.id == uuid.UUID(str(sid))))).scalar_one_or_none()
    if s is None:
        return
    targets = [
        t
        for t in (
            await db.execute(select(FeedbackResponse.target_id).where(FeedbackResponse.survey_id == s.id).distinct())
        )
        .scalars()
        .all()
        if t
    ]
    if s.survey_type == "course_exit":
        await CoAttainmentService(db, None, institution_id=iid).run_many(targets)
    elif s.survey_type in PO_SURVEYS:
        po = PoAttainmentService(db, None, institution_id=iid)
        for program_id, batch_id in (
            await db.execute(select(Batch.program_id, Batch.id).where(Batch.program_id.in_(targets or [uuid.uuid4()])))
        ).all():
            if await po.latest_run(program_id, batch_id) is not None:
                await po.request_run(program_id, batch_id, PoRunRequest(), inline=True)


def _beat(fn_name: str, label: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        if fn_name == "cqi":
            from app.services.obe.cqi_service import CqiService

            return int(await CqiService(db, None, institution_id=iid).due_reminders())
        return int(await _coverage_digest(db, iid))

    return run_async(_for_institutions("obe.cqi" if fn_name == "cqi" else "obe.attainment", one, label))


async def _coverage_digest(db: Any, iid: uuid.UUID) -> int:
    from sqlalchemy import func, select

    from app.models.obe_attainment import AttainmentRun, CqiAction
    from app.services.obe.common import ObeBase

    since = datetime.now(UTC) - timedelta(days=31)
    runs = (
        await db.execute(
            select(AttainmentRun.scope_type, func.count())
            .where(
                AttainmentRun.institution_id == iid, AttainmentRun.run_at >= since, AttainmentRun.status == "computed"
            )
            .group_by(AttainmentRun.scope_type)
        )
    ).all()
    open_actions = (
        await db.execute(
            select(func.count())
            .select_from(CqiAction)
            .where(CqiAction.institution_id == iid, CqiAction.status != "verified")
        )
    ).scalar_one()
    counts = dict(runs)
    svc = ObeBase(db, None, institution_id=iid)
    await svc._notify(
        "obe.coverage_digest",
        [],
        {
            "co_runs": str(counts.get("offering", 0)),
            "po_runs": str(counts.get("program_batch", 0)),
            "open_actions": str(open_actions),
        },
        audience={"roles": ["obe_coordinator"]},
    )
    return 1


@celery.task(name="beat.cqi.due_reminders", queue="scheduled")
def cqi_due_reminders() -> dict[str, int]:
    return _beat("cqi", "cqi_due_reminders")


@celery.task(name="beat.obe.coverage_digest", queue="scheduled")
def coverage_digest() -> dict[str, int]:
    return _beat("digest", "obe_coverage_digest")
