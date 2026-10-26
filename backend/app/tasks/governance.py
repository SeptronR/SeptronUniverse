"""Governance tasks — Prompts/33 §33.7.

Jobs: ``governance.notice_send``, ``governance.minutes_pdf``, ``governance.resolution_extract``, ``rti.annual_return``,
``efile.notings_pdf``, ``governance.registers_export`` (xlsx: committees, resolutions, legal, RTI, paras, files).
Beat: ``governance.meeting_reminders`` (daily), ``governance.atr_due_reminders`` (weekly), ``legal.hearing_reminders``
(daily), ``rti.due_reminders`` (daily), ``audit_para.due_reminders`` (weekly), ``efile.pendency_scan`` (daily),
``policy.ack_reminders`` (weekly), ``governance.member_tenure_expiry`` (monthly).
Consumers: ``regulation.submitted_for_approval`` / ``results.approval_requested`` / ``results.verified`` /
``degrees.council_approval_requested`` / ``degrees.recommended`` (council agenda inbox), ``accreditation.consistency_alert``
(IQAC agenda), ``accounting.budget_submitted`` (finance agenda), ``research.mou_submitted`` / ``research.mou_created``
(legal review file when e-File is on, else a legal agenda note), ``grievance.committee_routed`` (committee agenda).
Workflow hooks for ``governance.minutes_approval`` / ``governance.policy_approval`` register on import of the services.
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.services.governance import meeting_service, policy_service  # noqa: F401  (workflow hooks register on import)
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer
from app.tasks.research import XLSX, xlsx_bytes


async def _upload(principal: Any, name: str, content: bytes, mime: str) -> str:
    from app.core.files import build_key, get_storage

    key = build_key(principal.institution_id, "governance", name)
    storage = get_storage()
    await storage.put(key, content, mime)
    return storage.signed_url(key)


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.governance.notice_send", queue="reports")
@job("governance.notice_send", queue="reports")
async def notice_send(
    ctx: JobContext, db: Any, meeting_id: str, channels: list[str] | None = None, **_: Any
) -> dict[str, Any]:
    from app.schemas.governance import NoticeSend
    from app.services.governance.meeting_service import MeetingService

    principal = await _principal(db, ctx)
    out = await MeetingService(db, principal).send_notice(
        uuid.UUID(meeting_id),
        NoticeSend(channels=channels or ["in_app", "email"]),  # type: ignore[arg-type]
    )
    return {"meeting_id": meeting_id, "short_notice": out.short_notice}


@celery.task(name="jobs.governance.minutes_pdf", queue="reports")
@job("governance.minutes_pdf", queue="reports")
async def minutes_pdf(ctx: JobContext, db: Any, meeting_id: str, **_: Any) -> dict[str, Any]:
    from app.services.governance.meeting_service import MeetingService
    from app.utils.pdf import simple_pdf

    principal = await _principal(db, ctx)
    name, lines = await MeetingService(db, principal).minutes_lines(uuid.UUID(meeting_id))
    url = await _upload(principal, f"{name}.pdf", simple_pdf(lines, title="Minutes"), "application/pdf")
    return {"result_url": url}


@celery.task(name="jobs.governance.resolution_extract", queue="reports")
@job("governance.resolution_extract", queue="reports")
async def resolution_extract(ctx: JobContext, db: Any, resolution_id: str, **_: Any) -> dict[str, Any]:
    from app.services.governance.resolution_service import ResolutionService

    principal = await _principal(db, ctx)
    out = await ResolutionService(db, principal).extract(uuid.UUID(resolution_id))
    return {
        "result_url": out.url,
        "issued_document_id": str(out.issued_document_id) if out.issued_document_id else None,
    }


@celery.task(name="jobs.rti.annual_return", queue="reports")
@job("rti.annual_return", queue="reports")
async def rti_annual_return(ctx: JobContext, db: Any, period: str, **_: Any) -> dict[str, Any]:
    from app.services.governance.rti_service import RtiService

    principal = await _principal(db, ctx)
    out = await RtiService(db, principal).annual_return(period)
    url = await _upload(principal, f"rti-return-{period}.xlsx", xlsx_bytes(f"RTI {period}", [out.model_dump()]), XLSX)
    return {"result_url": url, **out.model_dump()}


@celery.task(name="jobs.efile.notings_pdf", queue="reports")
@job("efile.notings_pdf", queue="reports")
async def notings_pdf(ctx: JobContext, db: Any, efile_id: str, **_: Any) -> dict[str, Any]:
    from app.services.governance.efile_service import EfileService
    from app.utils.pdf import simple_pdf

    principal = await _principal(db, ctx)
    name, lines = await EfileService(db, principal).notings_lines(uuid.UUID(efile_id))
    url = await _upload(principal, f"{name}.pdf", simple_pdf(lines, title="Notings sheet"), "application/pdf")
    return {"result_url": url}


@celery.task(name="jobs.governance.registers_export", queue="reports")
@job("governance.registers_export", queue="reports")
async def registers_export(ctx: JobContext, db: Any, register: str = "resolutions", **_: Any) -> dict[str, Any]:
    from app.services.governance.committee_service import CommitteeService
    from app.services.governance.resolution_service import ResolutionService

    principal = await _principal(db, ctx)
    rows: list[dict[str, Any]]
    if register == "committees":
        rows = [c.model_dump(mode="json") for c in await CommitteeService(db, principal).list_committees()]
    else:
        items, _total = await ResolutionService(db, principal).list_resolutions(limit=5000)
        rows = [{k: v for k, v in r.model_dump(mode="json").items() if k not in ("atr", "text")} for r in items]
    url = await _upload(principal, f"{register}-register.xlsx", xlsx_bytes(register, rows), XLSX)
    return {"result_url": url, "rows": len(rows)}


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, path: str, cls: str, method: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        import importlib

        mod = importlib.import_module(f"app.services.governance.{path}")
        return int(await getattr(getattr(mod, cls)(db, None, institution_id=iid), method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.governance.meeting_reminders", queue="scheduled")
def meeting_reminders() -> dict[str, int]:
    return _beat("governance_meeting_reminders", "governance.minutes", "meeting_service", "MeetingService", "reminders")


@celery.task(name="beat.governance.atr_due_reminders", queue="scheduled")
def atr_due_reminders() -> dict[str, int]:
    return _beat(
        "governance_atr_due", "governance.minutes", "resolution_service", "ResolutionService", "atr_due_reminders"
    )


@celery.task(name="beat.legal.hearing_reminders", queue="scheduled")
def hearing_reminders() -> dict[str, int]:
    return _beat("legal_hearing_reminders", "governance.legal", "legal_service", "LegalService", "hearing_reminders")


@celery.task(name="beat.rti.due_reminders", queue="scheduled")
def rti_due_reminders() -> dict[str, int]:
    return _beat("rti_due_reminders", "governance.rti", "rti_service", "RtiService", "due_reminders")


@celery.task(name="beat.audit_para.due_reminders", queue="scheduled")
def para_due_reminders() -> dict[str, int]:
    return _beat("audit_para_due", "governance.audit_paras", "audit_para_service", "AuditParaService", "due_reminders")


@celery.task(name="beat.efile.pendency_scan", queue="scheduled")
def pendency_scan() -> dict[str, int]:
    return _beat("efile_pendency_scan", "governance.efile", "efile_service", "EfileService", "pendency_scan")


@celery.task(name="beat.policy.ack_reminders", queue="scheduled")
def ack_reminders() -> dict[str, int]:
    return _beat("policy_ack_reminders", "governance.policies", "policy_service", "PolicyService", "ack_reminders")


@celery.task(name="beat.governance.member_tenure_expiry", queue="scheduled")
def member_tenure_expiry() -> dict[str, int]:
    return _beat(
        "governance_member_tenure", "governance.committees", "committee_service", "CommitteeService", "tenure_expiry"
    )


# ---- consumers ------------------------------------------------------------------------------------------------------------
def _iid(event: dict[str, Any]) -> uuid.UUID | None:
    inst = event.get("institution_id")
    return uuid.UUID(str(inst)) if inst else None


# event → (committee types whose agenda inbox receives it, source, item text, entity_type, payload id key)
AGENDA_EVENTS: dict[str, tuple[tuple[str, ...], str, str, str | None, str | None]] = {
    "regulation.submitted_for_approval": (
        ("bos", "academic_council"),
        "regulation",
        "Approval of a regulation",
        "regulation",
        "regulation_id",
    ),
    "results.approval_requested": (
        ("academic_council", "executive_council"),
        "result_run",
        "Approval of results",
        "result_run",
        "run_id",
    ),
    "results.verified": (
        ("academic_council", "executive_council"),
        "result_run",
        "Approval of verified results",
        "result_run",
        "run_id",
    ),
    "degrees.council_approval_requested": (
        ("academic_council", "executive_council"),
        "degrees",
        "Award of degrees",
        None,
        "batch_id",
    ),
    "accreditation.consistency_alert": (("iqac",), "consistency_alert", "Data consistency alerts", None, None),
    "accounting.budget_submitted": (("finance",), "budget", "Budget proposal", None, "budget_id"),
    "grievance.committee_routed": (
        ("grievance", "icc", "anti_ragging"),
        "grievance",
        "Grievance routed to the committee",
        None,
        "grievance_id",
    ),
}


@consumer("governance.agenda_suggestions", events=list(AGENDA_EVENTS))
async def on_agenda_source(db: Any, event: dict[str, Any]) -> None:
    iid = _iid(event)
    et = str(event.get("event_type"))
    if iid is None or et not in AGENDA_EVENTS:
        return
    from app.core.features import is_enabled
    from app.services.governance.meeting_service import MeetingService

    if not await is_enabled(iid, "governance.minutes"):
        return
    types, source, item, entity_type, key = AGENDA_EVENTS[et]
    p = event.get("payload") or {}
    ref = p.get(key) if key else None
    ref = ref or event.get("aggregate_id")
    detail = p.get("period_label") or p.get("title") or p.get("name")
    entry: dict[str, Any] = {"source": source, "item": f"{item}{f' — {detail}' if detail else ''}"[:500], "detail": et}
    if entity_type and ref:
        entry["linked_entity"] = {"entity_type": entity_type, "entity_id": str(ref)}
    svc = MeetingService(db, None, institution_id=iid)
    for t in types:
        await svc.add_suggestion(t, entry)


@consumer("governance.mou_legal_review", events=["research.mou_submitted", "research.mou_created"])
async def on_mou(db: Any, event: dict[str, Any]) -> None:
    """MoUs reach the legal officer: an e-file (``governance.efile`` on) forwarded to the legal officer, else a note."""
    iid = _iid(event)
    if iid is None:
        return
    from app.core.features import is_enabled

    if not await is_enabled(iid, "governance.legal"):
        return
    p = event.get("payload") or {}
    mou_id = p.get("mou_id") or event.get("aggregate_id")
    from app.services.governance.efile_service import EfileService
    from app.services.governance.meeting_service import MeetingService

    if await is_enabled(iid, "governance.efile"):
        from sqlalchemy import select

        from app.models.governance import Efile

        es = EfileService(db, None, institution_id=iid)
        legal = await es.role_users("legal_officer")
        creator = event.get("actor_user_id") or (legal[0] if legal else None)
        if not creator or not legal:
            return
        exists_ = (
            await db.execute(select(Efile.id).where(Efile.institution_id == iid, Efile.subject.like(f"%{mou_id}%")))
        ).first()
        if exists_:
            return
        f = Efile(
            institution_id=iid,
            file_no=await es.sequence("efile", "EF"),
            subject=f"Legal review of MoU with {p.get('partner') or ''} [{mou_id}]"[:300],
            category="legal_review",
            created_by=uuid.UUID(str(creator)),
            current_holder_user_id=legal[0],
            priority="normal",
            status="in_movement",
        )
        db.add(f)
        await db.flush()
        from app.models.governance import EfileMovement

        db.add(
            EfileMovement(
                institution_id=iid,
                efile_id=f.id,
                from_user_id=uuid.UUID(str(creator)),
                to_user_id=legal[0],
                noting="MoU submitted for legal review (auto-opened from research.mou_submitted).",
                action="forward",
            )
        )
        await es.put_meta("efile", f.id, {"linked_entity": {"entity_type": "mou", "entity_id": str(mou_id)}})
        await db.flush()
        return
    await MeetingService(db, None, institution_id=iid).add_suggestion(
        "research_board",
        {
            "source": "mou",
            "item": f"MoU legal review — {p.get('partner') or mou_id}",
            "detail": "research.mou_submitted",
        },
    )
