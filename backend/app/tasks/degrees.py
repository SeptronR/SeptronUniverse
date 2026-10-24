"""Degrees tasks — Prompts/18 §18.7.

Jobs (run as the requesting user): ``degrees.eligibility_run``, ``degrees.issue_batch`` (PDF / eSign),
``degrees.print_batch``, ``credentials.push``, ``abc.push``. Consumers: ``degrees.final_results`` on
``results.published`` (final-term enrolments of the run → eligibility), ``degrees.recheck`` on ``no_dues.cleared`` /
``hold.released`` (one enrolment with a previous check), ``convocation.fee_paid`` on ``fees.payment_received``
(``source_type='convocation_registration'``), ``credentials.revoke_remote`` on ``credentials.revoked``,
``abc.version_created`` on ``results.version_created``. Beat: ``credentials.retry_failed`` (hourly),
``abc.push_pending`` (nightly), ``convocation.reminders`` (daily).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer


@celery.task(name="jobs.degrees.eligibility_run", queue="reports")
@job("degrees.eligibility_run", queue="reports")
async def eligibility_run(ctx: JobContext, db: Any, run_id: str, **params: Any) -> dict[str, Any]:
    from app.schemas.degrees import EligibilityRunRequest
    from app.services.degrees.eligibility_service import EligibilityService

    principal = await _principal(db, ctx)
    body = EligibilityRunRequest(**{k: v for k, v in params.items() if k in EligibilityRunRequest.model_fields})
    out = await EligibilityService(db, principal).run(body, uuid.UUID(run_id))
    await ctx.progress(db, 100, f"{out.eligible} eligible / {out.ineligible} not")
    return out.model_dump(mode="json")


@celery.task(name="jobs.degrees.issue_batch", queue="documents")
@job("degrees.issue_batch", queue="documents")
async def issue_batch(
    ctx: JobContext,
    db: Any,
    award_ids: list[str] | None = None,
    convocation_id: str | None = None,
    esign: bool = False,
    **_: Any,
) -> dict[str, Any]:
    from app.services.degrees.award_service import AwardService

    principal = await _principal(db, ctx)
    out = await AwardService(db, principal).issue_batch(
        [uuid.UUID(a) for a in award_ids] if award_ids else None,
        uuid.UUID(convocation_id) if convocation_id else None,
        esign,
    )
    await ctx.progress(db, 100, f"{out['issued']} issued")
    return out


@celery.task(name="jobs.degrees.print_batch", queue="documents")
@job("degrees.print_batch", queue="documents")
async def print_batch(
    ctx: JobContext, db: Any, award_ids: list[str] | None = None, convocation_id: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.degrees.award_service import AwardService

    principal = await _principal(db, ctx)
    out = await AwardService(db, principal).print_batch(
        [uuid.UUID(a) for a in award_ids] if award_ids else None, uuid.UUID(convocation_id) if convocation_id else None
    )
    await ctx.progress(db, 100, f"{out['count']} certificate(s)")
    return out


@celery.task(name="jobs.credentials.push", queue="reports")
@job("credentials.push", queue="reports")
async def credentials_push(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.degrees import CredentialPushRequest
    from app.services.degrees.credential_service import CredentialService

    principal = await _principal(db, ctx)
    body = CredentialPushRequest(**{k: v for k, v in params.items() if k in CredentialPushRequest.model_fields})
    out = await CredentialService(db, principal).push(body)
    await ctx.progress(db, 100, f"{out.acknowledged} acknowledged")
    return out.model_dump(mode="json")


@celery.task(name="jobs.abc.push", queue="reports")
@job("abc.push", queue="reports")
async def abc_push(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.degrees import AbcPushRequest
    from app.services.degrees.credential_service import CredentialService

    principal = await _principal(db, ctx)
    body = AbcPushRequest(**{k: v for k, v in params.items() if k in AbcPushRequest.model_fields})
    out = await CredentialService(db, principal).abc_push(body)
    await ctx.progress(db, 100, f"{out.batches} batch(es)")
    return out.model_dump(mode="json")


async def _on(iid: uuid.UUID, key: str) -> bool:
    from app.core.features import is_enabled

    return await is_enabled(iid, key)


@consumer("degrees.final_results", events=["results.published"])
async def final_results(db: Any, event: dict[str, Any]) -> None:
    from app.schemas.degrees import EligibilityRunRequest
    from app.services.degrees.eligibility_service import EligibilityService

    iid = uuid.UUID(str(event["institution_id"]))
    p = event.get("payload") or {}
    if not p.get("run_id") or not await _on(iid, "degrees.eligibility"):
        return
    svc = EligibilityService(db, None, institution_id=iid)
    ids = await svc.final_term_batches_of_run(uuid.UUID(str(p["run_id"])))
    if ids:
        await svc.run(EligibilityRunRequest(enrollment_ids=ids))


@consumer("degrees.recheck", events=["no_dues.cleared", "hold.released"])
async def recheck(db: Any, event: dict[str, Any]) -> None:
    from sqlalchemy import select

    from app.models.students import StudentProgramEnrollment
    from app.services.degrees.eligibility_service import EligibilityService

    iid = uuid.UUID(str(event["institution_id"]))
    if not await _on(iid, "degrees.eligibility"):
        return
    p = event.get("payload") or {}
    svc = EligibilityService(db, None, institution_id=iid)
    if p.get("student_program_enrollment_id"):
        await svc.recheck_enrolment(uuid.UUID(str(p["student_program_enrollment_id"])))
    elif p.get("student_id"):
        ids = (
            (
                await db.execute(
                    select(StudentProgramEnrollment.id).where(
                        StudentProgramEnrollment.student_id == uuid.UUID(str(p["student_id"]))
                    )
                )
            )
            .scalars()
            .all()
        )
        for eid in ids:
            await svc.recheck_enrolment(eid)


@consumer("convocation.fee_paid", events=["fees.payment_received"])
async def convocation_fee_paid(db: Any, event: dict[str, Any]) -> None:
    from app.services.degrees.convocation_service import ConvocationService

    p = event.get("payload") or {}
    if (
        p.get("source_type") != "convocation_registration"
        or not p.get("source_id")
        or p.get("invoice_status") not in (None, "paid")
    ):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    await ConvocationService(db, None, institution_id=iid).on_paid(uuid.UUID(str(p["source_id"])))


@consumer("credentials.revoke_remote", events=["credentials.revoked"])
async def revoke_remote(db: Any, event: dict[str, Any]) -> None:
    from app.services.degrees.credential_service import CredentialService

    p = event.get("payload") or {}
    if p.get("credential_id"):
        iid = uuid.UUID(str(event["institution_id"]))
        await CredentialService(db, None, institution_id=iid).on_revoked(uuid.UUID(str(p["credential_id"])))


@consumer("abc.version_created", events=["results.version_created"])
async def abc_version(db: Any, event: dict[str, Any]) -> None:
    from app.services.degrees.credential_service import CredentialService

    iid = uuid.UUID(str(event["institution_id"]))
    p = event.get("payload") or {}
    if p.get("run_id") and await _on(iid, "degrees.abc_push"):
        await CredentialService(db, None, institution_id=iid).on_version_created(uuid.UUID(str(p["run_id"])))


def _beat(fn_name: str, feature: str, label: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.schemas.degrees import AbcPushRequest
        from app.services.degrees.convocation_service import ConvocationService
        from app.services.degrees.credential_service import CredentialService

        if fn_name == "retry":
            return int(await CredentialService(db, None, institution_id=iid).retry_failed())
        if fn_name == "abc":
            out = await CredentialService(db, None, institution_id=iid).abc_push(AbcPushRequest())
            return out.pushed + out.acknowledged
        return int(await ConvocationService(db, None, institution_id=iid).reminders())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.credentials.retry_failed", queue="scheduled")
def credentials_retry_failed() -> dict[str, int]:
    return _beat("retry", "degrees.digilocker_nad", "credentials_retry_failed")


@celery.task(name="beat.abc.push_pending", queue="scheduled")
def abc_push_pending() -> dict[str, int]:
    return _beat("abc", "degrees.abc_push", "abc_push_pending")


@celery.task(name="beat.convocation.reminders", queue="scheduled")
def convocation_reminders() -> dict[str, int]:
    return _beat("reminders", "degrees.convocation", "convocation_reminders")
