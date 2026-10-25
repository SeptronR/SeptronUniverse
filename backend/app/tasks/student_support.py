"""Mentoring, grievances, discipline, surveys & clubs tasks — Prompts/27 §27.7.

Jobs: ``mentoring.bulk_assign``, ``risk.compute``, ``grievances.register_export``, ``discipline.register_export``,
``surveys.open_close``, ``surveys.analyse``, ``surveys.export``, ``activity.bulk_import``. Beat: follow-up reminders
(daily), minimum-sessions check (monthly), weekly risk recompute, grievance SLA scan (hourly) and auto-close (daily),
survey reminders (daily) and auto-close (hourly), discipline appeal window (daily). Consumers:
``attendance.below_threshold`` (recompute that student's risk), ``hostel.discipline_recorded`` /
``malpractice.registered`` / ``emergency.false_alarm`` / ``placement.policy_violation`` (open a disciplinary case).
"""

import csv
import io
import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer


async def _upload(principal: Any, name: str, text: str) -> str:
    from app.core.files import build_key, get_storage

    key = build_key(principal.institution_id, "student_support", name)
    storage = get_storage()
    await storage.put(key, text.encode("utf-8"), "text/csv")
    return storage.signed_url(key)


def _csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (v if not isinstance(v, dict | list) else str(v)) for k, v in r.items()})
    return buf.getvalue()


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.mentoring.bulk_assign", queue="reports")
@job("mentoring.bulk_assign", queue="reports")
async def mentoring_bulk_assign(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.mentoring import MentBulkAssign
    from app.services.student_support.mentoring_service import MentoringService

    principal = await _principal(db, ctx)
    body = MentBulkAssign.model_validate({k: v for k, v in params.items() if k in MentBulkAssign.model_fields})
    out = await MentoringService(db, principal).bulk_assign(body)
    await ctx.progress(db, 100, f"{out.assigned} assigned, {out.unassigned} unassigned")
    return out.model_dump(mode="json")


@celery.task(name="jobs.risk.compute", queue="reports")
@job("risk.compute", queue="reports")
async def risk_compute(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.mentoring import RiskRunRequest
    from app.services.student_support.risk_service import RiskService

    principal = await _principal(db, ctx)
    body = RiskRunRequest.model_validate({k: v for k, v in params.items() if k in RiskRunRequest.model_fields})
    out = await RiskService(db, principal).compute(body)
    await ctx.progress(db, 100, f"{out.computed} scored, {out.new_high} new high")
    return out.model_dump(mode="json")


@celery.task(name="jobs.grievances.register_export", queue="reports")
@job("grievances.register_export", queue="reports")
async def grievances_register_export(
    ctx: JobContext, db: Any, register: str = "ugc", period: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.student_support.grievance_service import GrievanceService

    principal = await _principal(db, ctx)
    reg = await GrievanceService(db, principal).register(register, period)
    url = await _upload(
        principal, f"grievance-register-{register}.csv", _csv([r.model_dump(mode="json") for r in reg.rows])
    )
    return {"rows": len(reg.rows), "result_url": url}


@celery.task(name="jobs.discipline.register_export", queue="reports")
@job("discipline.register_export", queue="reports")
async def discipline_register_export(
    ctx: JobContext, db: Any, date_from: str | None = None, date_to: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.student_support.discipline_service import DisciplineService

    principal = await _principal(db, ctx)
    rows = await DisciplineService(db, principal).register(
        date.fromisoformat(date_from) if date_from else None, date.fromisoformat(date_to) if date_to else None, None
    )
    url = await _upload(principal, "discipline-register.csv", _csv([r.model_dump(mode="json") for r in rows]))
    return {"rows": len(rows), "result_url": url}


@celery.task(name="jobs.surveys.open_close", queue="scheduled")
@job("surveys.open_close", queue="scheduled")
async def surveys_open_close(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.services.student_support.survey_service import SurveyService

    principal = await _principal(db, ctx)
    return {"changed": await SurveyService(db, principal).auto_close()}


@celery.task(name="jobs.surveys.analyse", queue="reports")
@job("surveys.analyse", queue="reports")
async def surveys_analyse(ctx: JobContext, db: Any, survey_id: str, **_: Any) -> dict[str, Any]:
    from app.services.student_support.survey_service import SurveyService

    principal = await _principal(db, ctx)
    out = await SurveyService(db, principal).transition(uuid.UUID(survey_id), "analyse")
    return {"survey_id": survey_id, "status": out.status, "responses": out.responses}


@celery.task(name="jobs.surveys.export", queue="reports")
@job("surveys.export", queue="reports")
async def surveys_export(ctx: JobContext, db: Any, survey_id: str, **_: Any) -> dict[str, Any]:
    from app.services.student_support.survey_service import SurveyService

    principal = await _principal(db, ctx)
    text = await SurveyService(db, principal).export_rows(uuid.UUID(survey_id))
    url = await _upload(principal, f"survey-{survey_id}.csv", text)
    await ctx.progress(db, 100, "exported")
    return {"result_url": url}


@celery.task(name="jobs.activity.bulk_import", queue="reports")
@job("activity.bulk_import", queue="reports")
async def activity_bulk_import(
    ctx: JobContext, db: Any, rows: list[dict[str, Any]], auto_verify: bool = False, **_: Any
) -> dict[str, Any]:
    from app.schemas.clubs import ActHourBulk
    from app.services.student_support.club_service import ClubService

    principal = await _principal(db, ctx)
    out = await ClubService(db, principal).bulk(ActHourBulk.model_validate({"rows": rows, "auto_verify": auto_verify}))
    return out.model_dump(mode="json")


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, path: str, cls: str, method: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        import importlib

        mod = importlib.import_module(f"app.services.student_support.{path}")
        return int(await getattr(getattr(mod, cls)(db, None, institution_id=iid), method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.mentoring.follow_up_reminders", queue="scheduled")
def follow_up_reminders() -> dict[str, int]:
    return _beat(
        "mentoring_follow_up", "mentoring.core", "mentoring_service", "MentoringService", "follow_up_reminders"
    )


@celery.task(name="beat.mentoring.min_sessions_check", queue="scheduled")
def min_sessions_check() -> dict[str, int]:
    return _beat(
        "mentoring_min_sessions", "mentoring.core", "mentoring_service", "MentoringService", "min_sessions_check"
    )


@celery.task(name="beat.risk.compute_weekly", queue="scheduled")
def risk_weekly() -> dict[str, int]:
    return _beat("risk_compute_weekly", "mentoring.early_warning", "risk_service", "RiskService", "weekly")


@celery.task(name="beat.grievances.sla_scan", queue="scheduled")
def grievance_sla_scan() -> dict[str, int]:
    return _beat("grievances_sla_scan", "grievances.core", "grievance_service", "GrievanceService", "sla_scan")


@celery.task(name="beat.grievances.auto_close", queue="scheduled")
def grievance_auto_close() -> dict[str, int]:
    return _beat("grievances_auto_close", "grievances.core", "grievance_service", "GrievanceService", "auto_close")


@celery.task(name="beat.surveys.reminders", queue="scheduled")
def survey_reminders() -> dict[str, int]:
    return _beat("surveys_reminders", "surveys.core", "survey_service", "SurveyService", "reminders")


@celery.task(name="beat.surveys.auto_close", queue="scheduled")
def survey_auto_close() -> dict[str, int]:
    return _beat("surveys_auto_close", "surveys.core", "survey_service", "SurveyService", "auto_close")


@celery.task(name="beat.discipline.appeal_window", queue="scheduled")
def appeal_window() -> dict[str, int]:
    return _beat(
        "discipline_appeal_window", "discipline.core", "discipline_service", "DisciplineService", "appeal_window"
    )


# ---- consumers ------------------------------------------------------------------------------------------------------------
async def _enabled(event: dict[str, Any], key: str) -> uuid.UUID | None:
    from app.core.features import is_enabled

    inst = event.get("institution_id")
    if not inst:
        return None
    iid = uuid.UUID(str(inst))
    return iid if await is_enabled(iid, key) else None


@consumer("student_support.risk_recompute", events=["attendance.below_threshold"])
async def risk_recompute(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "mentoring.early_warning")
    eid = (event.get("payload") or {}).get("student_program_enrollment_id")
    if iid is None or not eid:
        return
    from app.schemas.mentoring import RiskRunRequest
    from app.services.student_support.risk_service import RiskService

    await RiskService(db, None, institution_id=iid).compute(RiskRunRequest(enrollment_ids=[uuid.UUID(eid)]))


@consumer("student_support.discipline_from_hostel", events=["hostel.discipline_recorded"])
async def discipline_from_hostel(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "discipline.core")
    rid = (event.get("payload") or {}).get("record_id")
    if iid is None or not rid:
        return
    from sqlalchemy import select

    from app.models.hostel import HostelDisciplinaryRecord
    from app.services.student_support.discipline_service import DisciplineService

    rec = (
        await db.execute(select(HostelDisciplinaryRecord).where(HostelDisciplinaryRecord.id == uuid.UUID(rid)))
    ).scalar_one_or_none()
    if rec is None or rec.action in ("warning",):
        return
    await DisciplineService(db, None, institution_id=iid).from_source(
        "student", rec.student_program_enrollment_id, "hostel", rec.description, "hostel", rec.id
    )


@consumer("student_support.discipline_from_malpractice", events=["malpractice.registered"])
async def discipline_from_malpractice(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "discipline.core")
    p = event.get("payload") or {}
    eid = p.get("enrollment_id") or p.get("student_program_enrollment_id")
    if iid is None or not eid or not p.get("refer_discipline"):
        return
    from app.services.student_support.discipline_service import DisciplineService

    await DisciplineService(db, None, institution_id=iid).from_source(
        "student",
        uuid.UUID(eid),
        "exam_malpractice",
        "Referred from examination malpractice",
        "malpractice",
        p.get("case_id"),
    )


@consumer("student_support.discipline_from_false_sos", events=["emergency.false_alarm"])
async def discipline_from_false_sos(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "discipline.core")
    p = event.get("payload") or {}
    uid = p.get("raised_by_user_id")
    if iid is None or not uid or uid == "None":
        return
    from sqlalchemy import select

    from app.models.hr import Staff
    from app.models.students import Student
    from app.services.student_support.discipline_service import DisciplineService

    svc = DisciplineService(db, None, institution_id=iid)
    st = (await db.execute(select(Student).where(Student.user_id == uuid.UUID(uid)))).scalar_one_or_none()
    if st is not None:
        e = await svc.enrollments.current(st.id)
        if e is not None:
            await svc.from_source("student", e.id, "false_sos", "False SOS alarm", "false_sos", p.get("alert_id"))
        return
    sf = (await db.execute(select(Staff).where(Staff.user_id == uuid.UUID(uid)))).scalar_one_or_none()
    if sf is not None:
        await svc.from_source("staff", sf.id, "false_sos", "False SOS alarm", "false_sos", p.get("alert_id"))


@consumer("student_support.discipline_from_placement", events=["placement.policy_violation"])
async def discipline_from_placement(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "discipline.core")
    p = event.get("payload") or {}
    eid = p.get("enrollment_id")
    if iid is None or not eid:
        return
    from app.services.student_support.discipline_service import DisciplineService

    await DisciplineService(db, None, institution_id=iid).from_source(
        "student",
        uuid.UUID(eid),
        "placement_policy",
        str(p.get("reason") or "Placement policy violation"),
        "placement",
        p.get("id"),
    )
