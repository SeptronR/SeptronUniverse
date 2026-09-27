"""Phase 03 tasks — Prompts/03 §03.7: outbox consumers, Beat jobs, the admin credential e-mail and the demo-data job.

* consumer ``settings.invalidate_cache`` (``settings.changed``) drops ``settings:{institution}:{category}``;
* Beat ``sequences.reset`` (daily 00:05 UTC) restarts ``yearly`` / ``per_term`` number sequences whose period starts
  today in the institution's timezone;
* Beat ``terms.auto_status`` (daily 00:15 UTC): ``planned → registration`` on ``registration_start`` and
  ``registration → in_progress`` on ``start_date`` for institutions with ``terms.auto_advance = true``;
* ``notifications.send_admin_credentials`` — the onboarding e-mail to the first institution admin (adapter registry);
* job ``institutions.seed_demo`` — optional demo data for a freshly onboarded institution (current year + terms, a
  department per college, national holidays of the pack).

Every Beat task runs on the platform session (cross-tenant) and uses ``run_async`` (one loop per worker process).
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy import select, text

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.outbox import consumer

log = structlog.get_logger()


# ---- consumers -----------------------------------------------------------------------------------------------------
@consumer("settings.invalidate_cache", events=["settings.changed"])
async def invalidate_settings_cache(db: Any, event: dict[str, Any]) -> None:
    from app.services.settings_service import invalidate_settings_cache as drop

    payload = event.get("payload") or {}
    institution_id = event.get("institution_id") or payload.get("institution_id")
    if institution_id:
        await drop(institution_id, list(payload.get("categories") or []) or None)
        log.info("settings_cache_invalidated", institution_id=str(institution_id))


# ---- Beat ----------------------------------------------------------------------------------------------------------
async def _local_today_by_institution(db: Any) -> dict[uuid.UUID, date]:
    from zoneinfo import ZoneInfo

    rows = (await db.execute(text("SELECT id, timezone FROM institutions WHERE deleted_at IS NULL"))).all()
    out: dict[uuid.UUID, date] = {}
    for iid, tz in rows:
        try:
            out[iid] = datetime.now(ZoneInfo(tz or "Asia/Kolkata")).date()
        except Exception:  # noqa: BLE001 - an unknown zone name falls back to UTC
            out[iid] = datetime.now(UTC).date()
    return out


@celery.task(name="beat.sequences.reset", queue="scheduled")
def sequences_reset() -> dict[str, int]:
    return run_async(_sequences_reset())


async def _sequences_reset() -> dict[str, int]:
    from app.db.session import PlatformSessionLocal
    from app.services.sequence_service import reset_due_sequences

    async with PlatformSessionLocal() as db:
        reset = await reset_due_sequences(db, await _local_today_by_institution(db))
        await db.commit()
    log.info("sequences_reset", reset=reset)
    return {"reset": reset}


@celery.task(name="beat.terms.auto_status", queue="scheduled")
def terms_auto_status() -> dict[str, int]:
    return run_async(_terms_auto_status())


async def _terms_auto_status() -> dict[str, int]:
    from app.db.session import PlatformSessionLocal
    from app.repositories.academic_session_repository import AcademicTermRepository
    from app.services.academic_session_service import auto_advance_term

    advanced = 0
    async with PlatformSessionLocal() as db:
        today_by_inst = await _local_today_by_institution(db)
        enabled = {
            iid
            for (iid,) in (
                await db.execute(
                    text(
                        "SELECT institution_id FROM institution_settings WHERE category = 'terms' AND key = 'auto_advance' "
                        "AND college_id IS NULL AND value = 'true'::jsonb"
                    )
                )
            ).all()
        }
        candidates = await AcademicTermRepository(db).due_for_auto_status(
            max(today_by_inst.values(), default=date.today())
        )
        for term in candidates:
            if term.institution_id not in enabled:
                continue
            today = today_by_inst.get(term.institution_id)
            if today is not None and await auto_advance_term(db, term, today):
                advanced += 1
        await db.commit()
    log.info("terms_auto_status", advanced=advanced)
    return {"advanced": advanced}


# ---- notifications -------------------------------------------------------------------------------------------------
@celery.task(name="notifications.send_admin_credentials", queue="emails")
def send_admin_credentials(
    institution_id: str | None = None,
    email: str = "",
    username: str = "",
    temp_password: str = "",
    institution_name: str = "",
    institution_slug: str = "",
) -> dict[str, Any]:
    return run_async(
        _send_admin_credentials(institution_id, email, username, temp_password, institution_name, institution_slug)
    )


async def _send_admin_credentials(
    institution_id: str | None, email: str, username: str, temp_password: str, name: str, slug: str
) -> dict[str, Any]:
    from app.core.config import settings
    from app.db.session import PlatformSessionLocal
    from app.integrations.registry import get_adapter

    body = (
        f"An administrator account was created for {name} on SeptronUniverse.\n\n"
        f"Institution: {slug}\nUsername: {username}\nTemporary password: {temp_password}\n\n"
        "You will be asked to choose a new password (and to enrol multi-factor authentication) at the first sign-in."
    )
    result = await get_adapter("email", settings.EMAIL_PROVIDER).send(
        to=email, body=body, subject=f"Your {name} administrator account"
    )
    if institution_id:
        async with PlatformSessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE message_logs SET status = 'sent', sent_at = NOW(), provider_message_id = :ref "
                    "WHERE institution_id = :i AND event_type = 'institution.admin_credentials' AND recipient = :r "
                    "AND status = 'queued'"
                ),
                {
                    "i": institution_id,
                    "r": email,
                    "ref": (result or {}).get("reference") if isinstance(result, dict) else None,
                },
            )
            await db.commit()
    log.info("admin_credentials_sent", institution_id=institution_id, to=email[:3] + "…")
    return {"status": "sent"}


# ---- jobs ----------------------------------------------------------------------------------------------------------
IN_NATIONAL_HOLIDAYS = (("Republic Day", 1, 26), ("Independence Day", 8, 15), ("Gandhi Jayanti", 10, 2))


@celery.task(name="jobs.institutions.seed_demo", queue="reports")
@job("institutions.seed_demo", queue="reports")
async def seed_demo_job(ctx: JobContext, db: Any, institution_id: str, **_: Any) -> dict[str, Any]:
    """Demo data for a new institution: the current academic year (June–May) with odd/even terms, a department per
    college and the national holidays of the year — enough for the dashboards and selectors to have content."""
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import AcademicTerm, AcademicYear
    from app.models.platform import College, Department, Holiday

    iid = uuid.UUID(institution_id)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    today = datetime.now(UTC).date()
    start_year = today.year if today.month >= 6 else today.year - 1
    name = f"{start_year}-{(start_year + 1) % 100:02d}"
    created: dict[str, int] = {"academic_years": 0, "academic_terms": 0, "departments": 0, "holidays": 0}
    year = (
        await db.execute(
            select(AcademicYear).where(
                AcademicYear.institution_id == iid, AcademicYear.college_id.is_(None), AcademicYear.name == name
            )
        )
    ).scalar_one_or_none()
    if year is None:
        year = AcademicYear(
            institution_id=iid,
            name=name,
            start_date=date(start_year, 6, 1),
            end_date=date(start_year + 1, 5, 31),
            is_current=True,
        )
        db.add(year)
        await db.flush()
        created["academic_years"] += 1
        for seq, (tname, ttype, s, e) in enumerate(
            (
                ("Odd Semester", "odd", date(start_year, 7, 1), date(start_year, 11, 30)),
                ("Even Semester", "even", date(start_year + 1, 1, 2), date(start_year + 1, 5, 15)),
            ),
            start=1,
        ):
            db.add(
                AcademicTerm(
                    institution_id=iid,
                    academic_year_id=year.id,
                    name=tname,
                    term_type=ttype,
                    sequence=seq,
                    start_date=s,
                    end_date=e,
                    registration_start=s.replace(day=1) if s.day > 1 else s,
                    is_current=seq == 1,
                    status="in_progress" if seq == 1 else "planned",
                )
            )
            created["academic_terms"] += 1
    await ctx.progress(db, 40, "academic year")
    colleges = (
        (await db.execute(select(College).where(College.institution_id == iid, College.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    for college in colleges:
        exists = (
            await db.execute(select(Department.id).where(Department.college_id == college.id, Department.code == "GEN"))
        ).first()
        if exists is None:
            db.add(Department(institution_id=iid, college_id=college.id, code="GEN", name="General Studies"))
            created["departments"] += 1
    await ctx.progress(db, 70, "departments")
    for hname, month, day in IN_NATIONAL_HOLIDAYS:
        for yr in (start_year, start_year + 1):
            d = date(yr, month, day)
            if not (year.start_date <= d <= year.end_date):
                continue
            exists = (
                await db.execute(
                    select(Holiday.id).where(
                        Holiday.institution_id == iid, Holiday.holiday_date == d, Holiday.name == hname
                    )
                )
            ).first()
            if exists is None:
                db.add(Holiday(institution_id=iid, name=hname, holiday_date=d, holiday_type="public"))
                created["holidays"] += 1
    await db.flush()
    await ctx.progress(db, 100, "done")
    return created
