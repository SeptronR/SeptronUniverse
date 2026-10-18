"""Development-only routes (registered when ``APP_ENV=development`` — Prompts/01 §01.11 step 7, Prompts/02 §02.11).

``POST /_dev/jobs/sleep?seconds=5`` enqueues the ``jobs.sleep`` job so the tray / WebSocket progress stream can be
exercised before any business module exists. Protected like every route (``jobs:view`` + ``core.background_jobs``).
``&inline=true`` runs the job body inside the API process (no Celery worker needed — e.g. the fakeredis launcher);
the row, progress events and ``job.finished`` event are produced exactly as a worker would.

Phase 02 adds the fixtures its verification script needs before the real modules exist:
``PUT /_dev/users/{id}/validity`` (step 11 — expire a time-boxed account) and ``PUT /_dev/plans/{code}`` (step 14 —
lower a plan's seat limit; Phase 38 ships the real super-admin plan editor). Both are super-admin only and vanish
outside ``APP_ENV=development``.

Phase 03 adds ``POST /_dev/number-sequences/{id}/next`` (step 9 — consume a value the way a business module will;
``settings:manage`` + ``institution.number_sequences_custom``).

Phase 04 adds ``POST /_dev/workflow/start`` (step 8 — start any workflow key for a synthetic entity; ``requester``
overrides ``started_by``) and ``GET /_dev/workflow/markers/{instance_id}`` (the development hook registered below
writes a Redis marker when any workflow is approved/rejected — proof that hooks run), plus
``POST /_dev/workflow/escalate`` (step 10 — runs the Beat body in-process).

Phase 07 adds ``POST /_dev/gates/{gate}-check`` (steps 4 / 6 — runs the registration / hostel / exam … gate the way
Phases 09/14/20 will: ``hold_service.assert_clear`` then the undertakings gate; ``student_id`` defaults to the caller's
own record) and ``POST /_dev/students/{id}/term-results`` (step 9 — writes SGPA / CGPA history on term records and
runs ``recompute_standing`` until Phase 15 publishes results).

Phase 08 adds ``POST /_dev/fees/pay/{ref}`` (steps 3 / 8 — the payment event of an application / admission fee until
Phase 12 invoices exist) and ``POST /_dev/admissions/lapse-allotments`` (step 8 — runs the Beat body in-process).

Phase 10 adds ``POST /_dev/class-sessions/{id}/attendance`` (step 10 — mark a session's attendance ``taken`` /
``finalized`` until Phase 11 exists), ``POST /_dev/timetable/mark-missed`` (the nightly Beat body) and
``POST /_dev/timetable/consume/{event}`` (runs the ``leave.approved`` / ``leave.cancelled`` / ``holiday.changed``
consumer bodies in-process with a given payload, for runs without a Celery worker).

Phase 11 keeps the Phase 10 attendance fixture (older verify scripts; the real flow is ``POST
/class-sessions/{id}/attendance``) and adds ``POST /_dev/attendance/{task}`` (``auto-finalize`` | ``missing-digest`` |
``checkpoints`` [``?checkpoint=50`` forces one] | ``streak-alerts`` — the Beat bodies in-process),
``POST /_dev/condonations/{id}/paid`` (the condonation fee payment until Phase 12 invoices exist) and
``POST /_dev/attendance/consume/{event}`` (``timetable.published`` / ``session.created`` OD consumers).
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import (
    Principal,
    any_permission_required,
    permission_required,
    super_admin_required,
)
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.core.workflow import engine as workflow_engine
from app.db.session import get_db, get_platform_db, redis_client
from app.models.platform import User
from app.models.saas import SubscriptionPlan
from app.schemas.common import Envelope
from app.schemas.institution import NumberSequenceNext
from app.schemas.platform import JobResponse
from app.schemas.students import DevTermResults
from app.schemas.workflow import DevWorkflowStart, WorkflowInstanceResponse
from app.services.job_service import JobService
from app.services.sequence_service import SequenceService
from app.utils.response import ok

router = APIRouter(prefix="/_dev", tags=["dev"])


@router.post(
    "/jobs/sleep", status_code=202, summary="Enqueue a sleep job (dev only)", response_model=Envelope[JobResponse]
)
async def dev_sleep_job(
    request: Request,
    seconds: int = Query(5, ge=1, le=300),
    inline: bool = Query(False, description="run the job body in-process (no worker) — dev only"),
    principal: Principal = Depends(permission_required("jobs", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await JobService(db, principal).enqueue("sleep", {"seconds": seconds}, queue="reports", request=request)
    if inline:
        from app.core import jobs as jobs_core
        from app.tasks import platform as platform_tasks  # registers jobs.sleep in this process

        await db.commit()  # the worker path would see a committed row; keep the same contract
        body = platform_tasks.sleep_job.run.__wrapped__
        request.app.state.inline_jobs = getattr(request.app.state, "inline_jobs", set())
        task = asyncio.create_task(jobs_core._run(body, row.id))  # noqa: SLF001
        request.app.state.inline_jobs.add(task)
        task.add_done_callback(request.app.state.inline_jobs.discard)
    return ok(JobResponse.model_validate(row), message="Job queued")


@router.put(
    "/users/{id}/validity",
    summary="Set a user's valid_from/valid_to (dev fixture)",
    response_model=Envelope[dict[str, Any]],
)
async def set_user_validity(
    id: uuid.UUID,
    valid_from: datetime | None = Body(default=None, embed=True),
    valid_to: datetime | None = Body(default=None, embed=True),
    principal: Principal = Depends(super_admin_required()),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    user = (await db.execute(select(User).where(User.id == id))).scalar_one_or_none()
    if user is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "User not found")
    user.valid_from, user.valid_to = valid_from, valid_to
    await db.flush()
    return ok({"user_id": str(user.id), "valid_from": valid_from, "valid_to": valid_to})


@router.put(
    "/plans/{code}", summary="Set a subscription plan's limits (dev fixture)", response_model=Envelope[dict[str, Any]]
)
async def set_plan_limits(
    code: str,
    student_limit: int | None = Body(default=None, embed=True),
    staff_limit: int | None = Body(default=None, embed=True),
    principal: Principal = Depends(super_admin_required()),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    plan = (await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == code))).scalar_one_or_none()
    if plan is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Plan not found")
    await db.execute(
        update(SubscriptionPlan)
        .where(SubscriptionPlan.id == plan.id)
        .values(student_limit=student_limit, staff_limit=staff_limit)
    )
    return ok({"code": code, "student_limit": student_limit, "staff_limit": staff_limit})


@router.post(
    "/number-sequences/{id}/next",
    summary="Reserve the next value of a sequence (dev fixture)",
    dependencies=[feature_required("institution.number_sequences_custom")],
    response_model=Envelope[NumberSequenceNext],
)
async def next_sequence_value(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SequenceService(db, principal, request).next_by_id(id))


# ---- Phase 04 workflow fixtures --------------------------------------------------------------------------------------
@workflow_engine.on("*", "approved")
async def _dev_marker_approved(db: AsyncSession, instance: Any, actor: Any) -> None:
    await redis_client.set(f"dev:workflow:{instance.id}", "approved", ex=3600)


@workflow_engine.on("*", "rejected")
async def _dev_marker_rejected(db: AsyncSession, instance: Any, actor: Any) -> None:
    await redis_client.set(f"dev:workflow:{instance.id}", "rejected", ex=3600)


@router.post(
    "/workflow/start",
    status_code=201,
    summary="Start a workflow for a synthetic entity (dev fixture)",
    dependencies=[feature_required("workflow.engine")],
    response_model=Envelope[WorkflowInstanceResponse],
)
async def dev_workflow_start(
    body: DevWorkflowStart,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.institution.context import tenant_id
    from app.services.workflow_service import WorkflowService

    inst = tenant_id(principal, request)
    instance = await workflow_engine.start(
        db,
        institution_id=inst,
        key=body.key,
        entity_type="dev_entity",
        entity_id=body.entity_id or uuid.uuid4(),
        started_by=body.requester or principal.id,
        context=body.context,
        title=body.title or f"Dev {body.key}",
    )
    return ok(await WorkflowService(db, principal, request).instance(instance.id))


@router.get(
    "/workflow/markers/{instance_id}",
    summary="Hook marker written by the dev approved/rejected hooks",
    dependencies=[feature_required("workflow.engine")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_workflow_marker(
    instance_id: uuid.UUID, principal: Principal = Depends(permission_required("settings", "manage"))
) -> dict[str, Any]:
    return ok({"instance_id": str(instance_id), "marker": await redis_client.get(f"dev:workflow:{instance_id}")})


@router.post(
    "/workflow/escalate",
    summary="Run the escalation Beat body now (dev fixture)",
    dependencies=[feature_required("workflow.engine")],
    response_model=Envelope[dict[str, int]],
)
async def dev_workflow_escalate(
    principal: Principal = Depends(super_admin_required()), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok({"escalated": await workflow_engine.escalate_due(db)})


# ---- Phase 07 --------------------------------------------------------------------------------------------------------
@router.post(
    "/gates/{gate}-check",
    summary="Run a student gate (holds + undertakings) the way later phases will (dev fixture)",
    dependencies=[feature_required("students.core")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_gate_check(
    gate: str,
    request: Request,
    student_id: uuid.UUID | None = Query(default=None),
    principal: Principal = Depends(
        any_permission_required(("students", "view"), ("students", "view_all"), ("students", "self"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.enums.students import Gate
    from app.services.hold_service import HoldService
    from app.services.student_records_service import StudentRecordsService

    if gate not in {g.value for g in Gate}:
        raise APIError(422, ErrorCode.VALIDATION, f"Unknown gate {gate!r}", {"allowed": [g.value for g in Gate]})
    records = StudentRecordsService(db, principal, request)
    student = await records.students.get_visible(student_id) if student_id else await records._me()  # noqa: SLF001
    enrolment = await records.enrollments.current(student.id)
    if enrolment is not None:
        await HoldService(db, principal, request).assert_clear(enrolment.id, gate)
    await records.assert_undertakings(student, gate)
    return ok({"gate": gate, "student_id": str(student.id), "clear": True}, message="Gate clear")


@router.post(
    "/students/{id}/term-results",
    summary="Write SGPA / CGPA history and recompute the standing (dev fixture until Phase 15)",
    dependencies=[feature_required("students.academic_standing")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_term_results(
    id: uuid.UUID,
    body: DevTermResults,
    request: Request,
    principal: Principal = Depends(permission_required("students", "standing")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.enrollment_service import EnrollmentService

    out = await EnrollmentService(db, principal, request).set_term_results(id, body.terms, body.credits_earned)
    return ok(out.model_dump(mode="json"), message="Standing recomputed")


# ---- Phase 08 admissions fixtures -------------------------------------------------------------------------------------
@router.post(
    "/fees/pay/{ref}",
    summary="Simulate the payment event of an application / admission fee (dev fixture until Phase 12 invoices)",
    dependencies=[feature_required("admissions.cycles")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_fee_paid(
    ref: str,
    request: Request,
    principal: Principal = Depends(permission_required("admissions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.admissions.application_service import ApplicationService

    svc = ApplicationService(db, principal, request)
    applicant, purpose = await svc.find_payment(ref)
    await svc.mark_paid(applicant, purpose)
    return ok({"ref": ref, "purpose": purpose, "applicant_status": applicant.status}, message="Payment recorded")


@router.post(
    "/admissions/lapse-allotments",
    summary="Run the Beat body admissions.lapse_allotments in-process",
    dependencies=[feature_required("admissions.counselling_allotment")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_lapse_allotments(
    request: Request,
    principal: Principal = Depends(permission_required("admissions", "allot")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.admissions.counselling_service import CounsellingService

    return ok({"lapsed": await CounsellingService(db, principal, request).lapse_due()}, message="Lapse run")


# ---- Phase 09 --------------------------------------------------------------------------------------------------------
@router.post(
    "/registration/{task}",
    summary="Run a registration Beat body in-process (lock-windows | waitlist-expire | window-status | reminders)",
    dependencies=[feature_required("registration.core")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_registration_beat(
    task: str,
    request: Request,
    principal: Principal = Depends(permission_required("registration", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.registration.offering_service import WindowService
    from app.services.registration.registration_service import RegistrationService

    methods = {"lock-windows": "lock_due", "waitlist-expire": "expire_waitlists", "reminders": "reminders"}
    if task == "window-status":
        n = await WindowService(db, principal, request).tick()
    elif task in methods:
        n = await getattr(RegistrationService(db, principal, request), methods[task])()
    else:
        raise APIError(422, ErrorCode.VALIDATION, f"Unknown task {task!r}", {"allowed": [*methods, "window-status"]})
    return ok({"task": task, "changed": n}, message="Run")


# ---- Phase 10 --------------------------------------------------------------------------------------------------------
@router.post(
    "/class-sessions/{session_id}/attendance",
    summary="Mark a session's attendance taken / finalized (dev fixture until Phase 11)",
    dependencies=[feature_required("timetable.core")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_session_attendance(
    session_id: uuid.UUID,
    status: str = Query(default="finalized", pattern="^(not_taken|taken|finalized)$"),
    principal: Principal = Depends(any_permission_required(("attendance", "mark"), ("timetable", "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from datetime import UTC

    from app.models.timetable import ClassSession

    row = (
        await db.execute(
            select(ClassSession).where(
                ClassSession.id == session_id, ClassSession.institution_id == principal.institution_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Class session not found")
    now = datetime.now(UTC)
    row.attendance_status = status
    row.attendance_taken_at = now if status != "not_taken" else None
    row.finalized_at, row.finalized_by = (now, principal.id) if status == "finalized" else (None, None)
    if status != "not_taken" and row.status == "scheduled":
        row.status = "conducted"
    await db.flush()
    return ok({"session_id": str(row.id), "attendance_status": status, "status": row.status}, message="Marked")


@router.post(
    "/timetable/mark-missed",
    summary="Run the sessions.mark_missed Beat body in-process",
    dependencies=[feature_required("timetable.core")],
    response_model=Envelope[dict[str, int]],
)
async def dev_mark_missed(
    request: Request,
    principal: Principal = Depends(permission_required("timetable", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.timetable.session_service import SessionService

    return ok({"changed": await SessionService(db, principal, request).mark_missed()}, message="Run")


@router.post(
    "/timetable/consume/{event}",
    summary="Run a Phase 10 outbox consumer body in-process (leave.approved | leave.cancelled | holiday.changed)",
    dependencies=[feature_required("timetable.core")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_timetable_consume(
    event: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
    principal: Principal = Depends(permission_required("timetable", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from datetime import date as _date

    from app.services.timetable.substitution_service import SubstitutionService
    from app.services.timetable.timetable_service import TimetableService

    if event == "leave.approved":
        out: Any = await SubstitutionService(db, principal, request).from_leave(payload)
    elif event == "leave.cancelled":
        out = await SubstitutionService(db, principal, request).leave_cancelled(payload)
    elif event == "holiday.changed":
        out = await TimetableService(db, principal, request).resync_dates(
            [_date.fromisoformat(d) for d in payload.get("dates", [])]
        )
    else:
        raise APIError(422, ErrorCode.VALIDATION, f"Unknown event {event!r}")
    return ok({"event": event, "result": out}, message="Consumed")


# ---- Phase 11 --------------------------------------------------------------------------------------------------------
@router.post(
    "/attendance/{task}",
    summary="Run an attendance Beat body in-process (auto-finalize | missing-digest | checkpoints | streak-alerts)",
    dependencies=[feature_required("attendance.core")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_attendance_beat(
    task: str,
    request: Request,
    checkpoint: int | None = Query(default=None, ge=1, le=100),
    principal: Principal = Depends(any_permission_required(("attendance", "view_all"), ("exams", "eligibility"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.attendance.marking_service import MarkingService
    from app.services.attendance.summary_service import SummaryService

    if task == "auto-finalize":
        n = await MarkingService(db, principal, request).auto_finalize()
    elif task == "missing-digest":
        n = await MarkingService(db, principal, request).missing_digest()
    elif task == "checkpoints":
        n = await SummaryService(db, principal, request).checkpoints(checkpoint)
    elif task == "streak-alerts":
        svc = SummaryService(db, principal, request)
        term = await svc.require_current_term(None)
        n = (await svc.recompute_term(term.id))["rows"]
    else:
        raise APIError(
            422,
            ErrorCode.VALIDATION,
            f"Unknown task {task!r}",
            {"allowed": ["auto-finalize", "missing-digest", "checkpoints", "streak-alerts"]},
        )
    return ok({"task": task, "changed": n}, message="Run")


@router.post(
    "/attendance/consume/{event}",
    summary="Run a Phase 11 consumer body in-process (timetable.published | session.created)",
    dependencies=[feature_required("attendance.on_duty")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_attendance_consume(
    event: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
    principal: Principal = Depends(any_permission_required(("attendance", "view_all"), ("attendance", "condone"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.attendance.od_service import OdService

    svc = OdService(db, principal, request)
    if event == "timetable.published":
        n = await svc.apply_to_sessions()
    elif event == "session.created" and payload.get("session_id"):
        from datetime import date as _date

        n = await svc.apply_to_sessions([uuid.UUID(str(payload["session_id"]))], _date(1970, 1, 1))
    else:
        raise APIError(422, ErrorCode.VALIDATION, f"Unknown event {event!r} (session.created needs session_id)")
    return ok({"event": event, "od_marks": n}, message="Consumed")


@router.post(
    "/condonations/{condonation_id}/paid",
    summary="Simulate the condonation fee payment (until Phase 12 invoices)",
    dependencies=[feature_required("attendance.condonation")],
    response_model=Envelope[dict[str, Any]],
)
async def dev_condonation_paid(
    condonation_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(any_permission_required(("attendance", "condone"), ("fees", "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.attendance.condonation_service import CondonationService

    out = await CondonationService(db, principal, request).mark_paid(condonation_id, "DEV")
    return ok(out.model_dump(mode="json"), message="Paid")
