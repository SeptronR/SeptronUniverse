"""Research & faculty development tasks — Prompts/30 §30.7.

Jobs: ``research.import_publications``, ``research.sync_citations``, ``research.api_compute`` (batch),
``research.reports_export``, ``research.evidence_pack`` (NAAC 3.x evidence zip), ``research.mou_activity_report``.
Beat: ``research.publication_sync`` (weekly, opted-in faculty), ``research.project_report_reminders`` (weekly),
``research.mou_expiry_scan`` (daily), ``research.incentive_cap_reset`` (yearly), ``research.patent_renewal_reminders``
(monthly). Consumers: ``event.completed`` (FDP / workshop / conference → FDP records), ``fees.payment_received
(source_type=consultancy)`` (receipt settled → shares), ``accounting.grant_received`` / ``accounting.grant_expensed``
(ledger mirrored on the project), ``inventory.indent_fulfilled`` (project purchase → grant expense),
``phd.thesis_awarded`` (Phase 31 — scholar publications tagging, recorded until Phase 31 models scholars).
"""

import io
import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.services.research import (  # noqa: F401  (workflow hooks register on import in the worker)
    ethics_service,
    incentive_service,
    mou_service,
    project_service,
)
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx_bytes(title: str, rows: list[dict[str, Any]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = title[:30]
    cols = list(rows[0].keys()) if rows else ["(no rows)"]
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c) if not isinstance(r.get(c), dict | list) else str(r.get(c)) for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _upload(principal: Any, name: str, content: bytes, mime: str = XLSX) -> str:
    from app.core.files import build_key, get_storage

    key = build_key(principal.institution_id, "research", name)
    storage = get_storage()
    await storage.put(key, content, mime)
    return storage.signed_url(key)


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.research.import_publications", queue="reports")
@job("research.import_publications", queue="reports")
async def import_publications(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.research import ImportApply
    from app.services.research.publication_service import PublicationService

    principal = await _principal(db, ctx)
    body = ImportApply.model_validate({k: v for k, v in params.items() if k in ImportApply.model_fields})
    out = await PublicationService(db, principal).apply(body)
    await ctx.progress(db, 100, f"{out.created} created, {out.claimed} claimed")
    return out.model_dump()


@celery.task(name="jobs.research.sync_citations", queue="reports")
@job("research.sync_citations", queue="reports")
async def sync_citations(ctx: JobContext, db: Any, staff_id: str | None = None, **_: Any) -> dict[str, Any]:
    from app.services.research.publication_service import PublicationService

    principal = await _principal(db, ctx)
    n = await PublicationService(db, principal).sync_citations(uuid.UUID(staff_id) if staff_id else None)
    return {"updated": n}


@celery.task(name="jobs.research.api_compute", queue="reports")
@job("research.api_compute", queue="reports")
async def api_compute(
    ctx: JobContext,
    db: Any,
    period_from: str,
    period_to: str,
    staff_id: str | None = None,
    department_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    from app.services.research.score_service import ScoreService

    principal = await _principal(db, ctx)
    out = await ScoreService(db, principal).compute(
        uuid.UUID(staff_id) if staff_id else None,
        uuid.UUID(department_id) if department_id else None,
        date.fromisoformat(period_from),
        date.fromisoformat(period_to),
    )
    await ctx.progress(db, 100, f"{len(out)} score(s)")
    return {"computed": len(out)}


@celery.task(name="jobs.research.reports_export", queue="reports")
@job("research.reports_export", queue="reports")
async def reports_export(ctx: JobContext, db: Any, kind: str, year: int | None = None, **_: Any) -> dict[str, Any]:
    from app.services.research.score_service import ScoreService

    principal = await _principal(db, ctx)
    rows = await ScoreService(db, principal).report_rows(kind, year)
    url = await _upload(principal, f"research-{kind}.xlsx", xlsx_bytes(kind, rows))
    await ctx.progress(db, 100, f"{len(rows)} rows")
    return {"result_url": url, "rows": len(rows)}


@celery.task(name="jobs.research.evidence_pack", queue="reports")
@job("research.evidence_pack", queue="reports")
async def evidence_pack(
    ctx: JobContext, db: Any, criterion: str = "3.3", year: int | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.research.score_service import ScoreService

    principal = await _principal(db, ctx)
    content = await ScoreService(db, principal).evidence_pack(criterion, year)
    url = await _upload(principal, f"naac-{criterion}-evidence.zip", content, "application/zip")
    return {"result_url": url}


@celery.task(name="jobs.research.mou_activity_report", queue="reports")
@job("research.mou_activity_report", queue="reports")
async def mou_activity_report(ctx: JobContext, db: Any, year: int, **_: Any) -> dict[str, Any]:
    from app.services.research.mou_service import MouService

    principal = await _principal(db, ctx)
    rows = [r.model_dump(mode="json") for r in await MouService(db, principal).activity_report(int(year))]
    url = await _upload(principal, f"mou-activity-{year}.xlsx", xlsx_bytes("MoU activity", rows))
    return {"result_url": url, "rows": len(rows)}


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, path: str, cls: str, method: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        import importlib

        mod = importlib.import_module(f"app.services.research.{path}")
        return int(await getattr(getattr(mod, cls)(db, None, institution_id=iid), method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.research.publication_sync", queue="scheduled")
def publication_sync() -> dict[str, int]:
    return _beat(
        "research_publication_sync", "research.publications", "publication_service", "PublicationService", "weekly_sync"
    )


@celery.task(name="beat.research.project_report_reminders", queue="scheduled")
def project_report_reminders() -> dict[str, int]:
    return _beat(
        "research_project_report_reminders",
        "research.projects_grants",
        "project_service",
        "ProjectService",
        "report_reminders",
    )


@celery.task(name="beat.research.mou_expiry_scan", queue="scheduled")
def mou_expiry_scan() -> dict[str, int]:
    return _beat("research_mou_expiry_scan", "research.mous_collaborations", "mou_service", "MouService", "expiry_scan")


@celery.task(name="beat.research.incentive_cap_reset", queue="scheduled")
def incentive_cap_reset() -> dict[str, int]:
    return _beat(
        "research_incentive_cap_reset",
        "research.seed_grants_incentives",
        "incentive_service",
        "IncentiveService",
        "cap_reset",
    )


@celery.task(name="beat.research.patent_renewal_reminders", queue="scheduled")
def patent_renewal_reminders() -> dict[str, int]:
    return _beat("research_patent_renewals", "research.patents", "record_service", "RecordService", "patent_renewals")


# ---- consumers ------------------------------------------------------------------------------------------------------------
async def _enabled(event: dict[str, Any], key: str) -> uuid.UUID | None:
    from app.core.features import is_enabled

    inst = event.get("institution_id")
    if not inst:
        return None
    iid = uuid.UUID(str(inst))
    return iid if await is_enabled(iid, key) else None


@consumer("research.fdp_from_event", events=["event.completed"])
async def on_event_completed(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "research.fdp")
    p = event.get("payload") or {}
    if iid is None or not p.get("event_id"):
        return
    from app.services.research.record_service import RecordService

    await RecordService(db, None, institution_id=iid).on_event_completed(uuid.UUID(str(p["event_id"])))


@consumer("research.consultancy_paid", events=["fees.payment_received"])
async def on_payment(db: Any, event: dict[str, Any]) -> None:
    p = event.get("payload") or {}
    if p.get("source_type") != "consultancy":
        return
    iid = await _enabled(event, "research.consultancy")
    if iid is None:
        return
    from app.services.research.consultancy_service import ConsultancyService

    await ConsultancyService(db, None, institution_id=iid).on_payment(p)


@consumer("research.ledger_mirror", events=["accounting.grant_received", "accounting.grant_expensed"])
async def on_grant(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "research.projects_grants")
    p = event.get("payload") or {}
    if iid is None or not p.get("grant_id"):
        return
    from app.services.research.project_service import ProjectService

    await ProjectService(db, None, institution_id=iid).on_grant_event(uuid.UUID(str(p["grant_id"])))


@consumer("research.project_purchase", events=["inventory.indent_fulfilled"])
async def on_indent(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "research.projects_grants")
    p = event.get("payload") or {}
    if iid is None or not p.get("indent_id"):
        return
    from app.services.research.project_service import ProjectService

    await ProjectService(db, None, institution_id=iid).on_indent_fulfilled(
        uuid.UUID(str(p["indent_id"])), int(p["amount_paise"]) if p.get("amount_paise") else None
    )


@consumer("research.thesis_publications", events=["phd.thesis_awarded"])
async def on_thesis(db: Any, event: dict[str, Any]) -> None:
    """Phase 31 scholars: the awarded scholar's publications are marked for the research cell's review."""
    iid = await _enabled(event, "research.publications")
    p = event.get("payload") or {}
    if iid is None or not p.get("scholar_id"):
        return
    from sqlalchemy import select

    from app.models.research import Publication
    from app.services.research.common import ResearchBase

    svc = ResearchBase(db, None, institution_id=iid)
    rows = (
        await db.execute(
            select(Publication.id).where(
                Publication.institution_id == iid, Publication.scholar_id == uuid.UUID(str(p["scholar_id"]))
            )
        )
    ).all()
    for (pid,) in rows:
        m = await svc.meta("pub", pid)
        m["thesis_awarded"] = True
        await svc.put_meta("pub", pid, m)
