"""Accreditation & compliance (IQAC) tasks — Prompts/32 §32.7.

Jobs: ``accreditation.compute``, ``accreditation.drilldown_export`` (xlsx), ``accreditation.evidence_pack`` (zip),
``accreditation.cycle_export`` (SSR / AQAR / SAR docx, pdf through Phase 26, NIRF / AISHE / AICTE / UGC xlsx),
``accreditation.submission_generate``, ``accreditation.consistency_check``, ``accreditation.disclosures_refresh``.
Beat: ``accreditation.compute_weekly``, ``accreditation.submission_due_reminders`` (weekly),
``accreditation.response_due_reminders`` (daily), ``accreditation.audit_finding_reminders`` (weekly),
``accreditation.evidence_retention`` (monthly). Consumers: ``research.stats_published`` / ``phd.stats_published`` /
``placement.stats_published`` / ``alumni.stats_published`` / ``metrics.publish`` (precomputed values →
``metric_values``), evidence suggestions from ``accreditation.evidence_suggested`` (Phase 25 event completion with a
``naac_criterion``), ``event.completed``, ``research.publication_verified``, ``research.mou_signed``,
``phd.thesis_awarded``, ``placement.stats_published``, ``governance.minutes_approved``, ``accounting.period_closed``,
``survey.analysed`` (SSS → recompute ``surveys.sss_score``).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.services.accreditation import cycle_service  # noqa: F401  (workflow hooks register on import in the worker)
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer
from app.tasks.research import XLSX, _upload, xlsx_bytes


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.accreditation.compute", queue="reports")
@job("accreditation.compute", queue="reports")
async def compute(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.accreditation import MetricComputeRequest
    from app.services.accreditation.disclosure_service import DisclosureService
    from app.services.accreditation.metric_service import MetricService

    principal = await _principal(db, ctx)
    body = MetricComputeRequest.model_validate(
        {k: v for k, v in params.items() if k in MetricComputeRequest.model_fields}
    )
    out = await MetricService(db, principal).compute(body, job_id=ctx.job_id)
    await DisclosureService(db, principal).refresh()
    await ctx.progress(db, 100, f"{out.computed} computed, {len(out.failed)} failed")
    return out.model_dump(mode="json")


@celery.task(name="jobs.accreditation.drilldown_export", queue="reports")
@job("accreditation.drilldown_export", queue="reports")
async def drilldown_export(
    ctx: JobContext,
    db: Any,
    key: str,
    period: str,
    college_id: str | None = None,
    program_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    from app.services.accreditation.metric_service import MetricService

    principal = await _principal(db, ctx)
    rows = await MetricService(db, principal).drilldown_rows_all(
        key, period, uuid.UUID(college_id) if college_id else None, uuid.UUID(program_id) if program_id else None
    )
    url = await _upload(principal, f"drilldown-{key}-{period}.xlsx", xlsx_bytes(key, rows), XLSX)
    return {"result_url": url, "rows": len(rows)}


@celery.task(name="jobs.accreditation.evidence_pack", queue="reports")
@job("accreditation.evidence_pack", queue="reports")
async def evidence_pack(
    ctx: JobContext, db: Any, criterion: str, period: str | None = None, framework: str = "NAAC_2024", **_: Any
) -> dict[str, Any]:
    from app.services.accreditation.evidence_service import EvidenceService

    principal = await _principal(db, ctx)
    content = await EvidenceService(db, principal).build_pack(criterion, period, framework)
    url = await _upload(principal, f"{framework}-{criterion}-evidence-pack.zip", content, "application/zip")
    return {"result_url": url}


@celery.task(name="jobs.accreditation.cycle_export", queue="reports")
@job("accreditation.cycle_export", queue="reports")
async def cycle_export(
    ctx: JobContext, db: Any, cycle_id: str, format: str, period_label: str | None = None, **_: Any
) -> dict[str, Any]:  # noqa: A002
    from app.services.accreditation.cycle_service import CycleService
    from app.services.accreditation.export_service import ExportService

    principal = await _principal(db, ctx)
    svc = ExportService(db, principal)
    cid = uuid.UUID(cycle_id)
    content, name, mime, rows = await svc.cycle_export(cid, format, period_label)
    c = await CycleService(db, principal).cycle(cid)
    doc = await svc.register_document(c, format, f"{name} — {rows} row(s)")
    url = (
        doc.pdf_url
        if format == "pdf" and doc is not None
        else (await _upload(principal, name, content, mime) if content else None)
    )
    entry = await svc.record_export(cid, format, url, rows, doc.issued_document_id if doc is not None else None)
    await ctx.progress(db, 100, f"{format} ready")
    return {"result_url": url, **entry}


@celery.task(name="jobs.accreditation.submission_generate", queue="reports")
@job("accreditation.submission_generate", queue="reports")
async def submission_generate(ctx: JobContext, db: Any, submission_id: str, **_: Any) -> dict[str, Any]:
    from app.services.accreditation.export_service import xlsx_sheets
    from app.services.accreditation.submission_service import SubmissionService

    principal = await _principal(db, ctx)
    svc = SubmissionService(db, principal)
    out = await svc.generate(uuid.UUID(submission_id), job_id=ctx.job_id)
    metrics = (out.payload or {}).get("metrics") or {}
    content = xlsx_sheets(
        {"metrics": [{"metric": k, **{x: y for x, y in v.items() if x != "breakdown"}} for k, v in metrics.items()]}
    )
    url = await _upload(principal, f"{out.submission_type}-{out.period_label}.xlsx", content, XLSX)
    row = await svc.row(out.id)
    row.file_url = url
    return {"result_url": url, "metrics": len(metrics)}


@celery.task(name="jobs.accreditation.consistency_check", queue="reports")
@job("accreditation.consistency_check", queue="reports")
async def consistency_check(ctx: JobContext, db: Any, period: str, **_: Any) -> dict[str, Any]:
    from app.services.accreditation.consistency_service import ConsistencyService

    principal = await _principal(db, ctx)
    out = await ConsistencyService(db, principal).run(period, notify=True)
    return out.model_dump(mode="json")


@celery.task(name="jobs.accreditation.disclosures_refresh", queue="reports")
@job("accreditation.disclosures_refresh", queue="reports")
async def disclosures_refresh(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.services.accreditation.disclosure_service import DisclosureService

    principal = await _principal(db, ctx)
    out = await DisclosureService(db, principal).refresh()
    return {"items": len(out.items)}


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, path: str, cls: str, method: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        import importlib

        mod = importlib.import_module(f"app.services.accreditation.{path}")
        return int(await getattr(getattr(mod, cls)(db, None, institution_id=iid), method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.accreditation.compute_weekly", queue="scheduled")
def compute_weekly() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.schemas.accreditation import MetricComputeRequest
        from app.services.accreditation.disclosure_service import DisclosureService
        from app.services.accreditation.metric_service import MetricService, label_for_year

        svc = MetricService(db, None, institution_id=iid)
        if (await svc.acc_setting("compute_schedule")) not in ("weekly", None):
            return 0
        label = label_for_year(today.year if today.month >= 6 else today.year - 1)
        out = await svc.compute(MetricComputeRequest(period_label=label))
        await DisclosureService(db, None, institution_id=iid).refresh()
        return out.computed

    return run_async(_for_institutions("accreditation.aishe", one, "accreditation_compute_weekly"))


@celery.task(name="beat.accreditation.submission_due_reminders", queue="scheduled")
def submission_due_reminders() -> dict[str, int]:
    return _beat(
        "accreditation_submission_due",
        "accreditation.aishe",
        "submission_service",
        "SubmissionService",
        "due_reminders",
    )


@celery.task(name="beat.accreditation.response_due_reminders", queue="scheduled")
def response_due_reminders() -> dict[str, int]:
    return _beat(
        "accreditation_response_due", "accreditation.iqac_cycles", "cycle_service", "CycleService", "due_reminders"
    )


@celery.task(name="beat.accreditation.audit_finding_reminders", queue="scheduled")
def audit_finding_reminders() -> dict[str, int]:
    return _beat(
        "accreditation_audit_findings",
        "accreditation.audit_registers",
        "audit_service",
        "AuditService",
        "finding_reminders",
    )


@celery.task(name="beat.accreditation.evidence_retention", queue="scheduled")
def evidence_retention() -> dict[str, int]:
    return _beat(
        "accreditation_evidence_retention",
        "accreditation.evidence_repo",
        "evidence_service",
        "EvidenceService",
        "retention_sweep",
    )


# ---- consumers ------------------------------------------------------------------------------------------------------------
def _iid(event: dict[str, Any]) -> uuid.UUID | None:
    inst = event.get("institution_id")
    return uuid.UUID(str(inst)) if inst else None


@consumer(
    "accreditation.metrics_published",
    events=[
        "research.stats_published",
        "phd.stats_published",
        "placement.stats_published",
        "alumni.stats_published",
        "metrics.publish",
    ],
)
async def on_stats_published(db: Any, event: dict[str, Any]) -> None:
    """Modules push precomputed values (Phases 28–31, library) → institution-level ``metric_values``."""
    iid = _iid(event)
    if iid is None:
        return
    from app.services.accreditation.metric_service import MetricService

    await MetricService(db, None, institution_id=iid).consume_published(
        str(event.get("event_type")), event.get("payload") or {}
    )


@consumer(
    "accreditation.evidence_suggestions",
    events=[
        "accreditation.evidence_suggested",
        "research.publication_verified",
        "research.mou_signed",
        "phd.thesis_awarded",
        "placement.stats_published",
        "governance.minutes_approved",
        "accounting.period_closed",
    ],
)
async def on_evidence_source(db: Any, event: dict[str, Any]) -> None:
    iid = _iid(event)
    if iid is None:
        return
    from app.services.accreditation.evidence_service import EvidenceService

    p = event.get("payload") or {}
    et = str(event.get("event_type"))
    svc = EvidenceService(db, None, institution_id=iid)
    agg = event.get("aggregate_id")
    if et == "accreditation.evidence_suggested":
        if not p.get("source_type"):
            return  # our own inbox notifications
        await svc.suggest(
            "events" if p["source_type"] == "event" else str(p["source_type"]),
            str(p["source_type"]),
            p.get("source_id"),
            f"Event report: {p.get('title') or ''}",
            p.get("criterion"),
            file_url=f"/events/{p.get('source_id')}",
        )
        return
    mapping: dict[str, tuple[str, str, str, str | None]] = {
        "research.publication_verified": ("research", "publication", "Verified publication", "3.3.1"),
        "research.mou_signed": ("research", "mou", "MoU signed", "3.5.1"),
        "phd.thesis_awarded": ("phd", "research_scholar", "PhD awarded", "3.6.3"),
        "placement.stats_published": ("placement", "placement_stats", "Placement statistics published", "5.2.1"),
        "governance.minutes_approved": ("governance", "meeting", "Approved minutes", "6.5.1"),
        "accounting.period_closed": ("accounting", "statements", "Audited statements / period closed", "6.4.1"),
    }
    module, entity, title, criterion = mapping[et]
    ref = (
        p.get("publication_id")
        or p.get("mou_id")
        or p.get("scholar_id")
        or p.get("meeting_id")
        or agg
        or p.get("batch_id")
    )
    await svc.suggest(module, entity, ref, title, criterion)


@consumer("accreditation.sss_recompute", events=["survey.analysed"])
async def on_survey_analysed(db: Any, event: dict[str, Any]) -> None:
    p = event.get("payload") or {}
    iid = _iid(event)
    if iid is None or p.get("survey_type") not in (None, "sss"):
        return
    from app.core.metrics import REGISTRY, MetricContext, normalise_period
    from app.services.accreditation.metric_service import MetricService, label_for_year

    svc = MetricService(db, None, institution_id=iid)
    today = await svc.today()
    period = normalise_period(label_for_year(today.year if today.month >= 6 else today.year - 1))
    res = await REGISTRY["surveys.sss_score"].fn(MetricContext(db, iid, period))
    await svc.upsert_auto("surveys.sss_score", period.label, res)
