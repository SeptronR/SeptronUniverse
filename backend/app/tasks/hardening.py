"""Tasks of Phase 43 — Prompts/43 §43.7 (privacy office, security posture, QA).

Jobs: ``privacy.dsr_export`` (Phase 41 ``export_user`` → file store → signed link 7 days → request ``completed``),
``privacy.dsr_erase`` (refused with outstanding dues; Phase 37 ``retention_service.erase`` + identity fields
anonymised + sessions revoked → manifest id on the timeline), ``qa.suite`` (``scripts/verify/run_all.py``),
``qa.access_matrix`` (``gen_access_matrix.py``). Beat (UTC): ``security.posture_daily`` (22:30 = 04:00 IST),
``security.mfa_enforcement_scan`` (daily 03:10), ``privacy.dsr_due_reminders`` (daily 03:20), ``privacy.minor_recompute``
(daily 18:40 = 00:10 IST — students turning 18 get a re-consent flag), ``privacy.consent_version_reminders`` (Mondays).
"""

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import text

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _principal
from app.tasks.integrations import _platform

log = structlog.get_logger()
BACKEND = Path(__file__).resolve().parents[2]


async def _dsr(db: Any, ctx: JobContext, request_id: str) -> tuple[Any, Any]:
    from app.services.hardening.privacy_office import PrivacyOfficeService

    svc = PrivacyOfficeService(db, await _principal(db, ctx))
    return svc, await svc._get(uuid.UUID(request_id))  # noqa: SLF001 - same package


@celery.task(name="jobs.privacy.dsr_export", queue="reports")
@job("privacy.dsr_export", queue="reports")
async def dsr_export(ctx: JobContext, db: Any, request_id: str, **_: Any) -> dict[str, Any]:
    from app.core.files import storage
    from app.core.notifications.notify import notify_event
    from app.services.integrations.import_service import export_user

    svc, r = await _dsr(db, ctx, request_id)
    data = await export_user(db, ctx.institution_id, r.user_id)  # type: ignore[arg-type]
    key = f"{ctx.institution_id}/privacy/dsr-{r.id}.json"
    await storage.put(key, json.dumps(data, default=str, indent=1).encode(), "application/json")
    r.result_url = storage.signed_url(key, ttl=7 * 86400)
    r.status, r.closed_at = "completed", datetime.now(UTC)
    meta = await svc._dsr_meta(r.id)  # noqa: SLF001
    await svc._note(r.id, meta, "export_ready")  # noqa: SLF001
    await notify_event(
        db,
        ctx.institution_id,
        "privacy.dsr_completed",
        audience={"user_ids": [str(r.user_id)]},
        context={"request_id": str(r.id), "route": "/profile/privacy"},
    )
    return {"request_id": str(r.id), "key": key}


@celery.task(name="jobs.privacy.dsr_erase", queue="reports")
@job("privacy.dsr_erase", queue="reports")
async def dsr_erase(ctx: JobContext, db: Any, request_id: str, **_: Any) -> dict[str, Any]:
    from app.core import events
    from app.core.notifications.notify import notify_event
    from app.services.audit.retention_service import RetentionService

    svc, r = await _dsr(db, ctx, request_id)
    meta = await svc._dsr_meta(r.id)  # noqa: SLF001
    dues = (
        (
            await db.execute(
                text(
                    "SELECT coalesce(sum(i.balance_paise), 0) FROM fee_invoices i JOIN students s ON s.id = i.student_id "
                    "WHERE s.user_id = :u AND i.balance_paise > 0 AND i.status <> 'cancelled'"
                ),
                {"u": r.user_id},
            )
        ).scalar_one_or_none()
        if await _has_column(db, "fee_invoices", "balance_paise")
        else 0
    )
    hold = await svc.meta(f"legal_hold:user:{r.user_id}", "audit_meta")
    if dues or hold:
        reason = "Outstanding fee dues" if dues else "A legal hold applies"
        r.status, r.closed_at = "rejected", datetime.now(UTC)
        await svc._note(r.id, meta, "rejected", reason=reason)  # noqa: SLF001
        await notify_event(
            db,
            ctx.institution_id,
            "privacy.dsr_rejected",
            audience={"user_ids": [str(r.user_id)]},
            context={"request_id": str(r.id), "reason": reason},
        )
        return {"rejected": reason}
    out = await RetentionService(db, svc.principal).erase(r.user_id)
    anon = f"erased-{str(r.user_id)[:8]}"
    await db.execute(
        text(
            "UPDATE users SET display_name = :a, email = NULL, phone = NULL, avatar_url = NULL, is_active = FALSE WHERE id = :u"
        ),
        {"a": anon, "u": r.user_id},
    )
    await db.execute(text("UPDATE students SET phone = NULL, email = NULL WHERE user_id = :u"), {"u": r.user_id})
    await db.execute(
        text(
            "UPDATE student_guardians SET phone = NULL, email = NULL WHERE student_id IN (SELECT id FROM students WHERE user_id = :u)"
        ),
        {"u": r.user_id},
    )
    await db.execute(
        text(
            "UPDATE user_sessions SET revoked_at = NOW(), revoked_reason = 'erasure' WHERE user_id = :u AND revoked_at IS NULL"
        ),
        {"u": r.user_id},
    )
    await db.execute(text("UPDATE device_tokens SET is_active = FALSE WHERE user_id = :u"), {"u": r.user_id})
    meta["manifest_id"] = out.get("manifest_id")
    r.status, r.closed_at = "completed", datetime.now(UTC)
    await svc._note(r.id, meta, "erased", manifest_id=out.get("manifest_id"), counts=out.get("counts"))  # noqa: SLF001
    await events.emit(
        db,
        institution_id=ctx.institution_id,
        event_type="privacy.erasure_done",
        payload={"request_id": str(r.id), "manifest_id": out.get("manifest_id")},
        aggregate_type="data_subject_request",
        aggregate_id=r.id,
        actor_user_id=ctx.requested_by,
    )
    return {"request_id": str(r.id), **out}


async def _has_column(db: Any, table: str, column: str) -> bool:
    return bool(
        (
            await db.execute(
                text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
                {"t": table, "c": column},
            )
        ).first()
    )


@celery.task(name="jobs.qa.suite", queue="reports")
@job("qa.suite", queue="reports")
async def qa_suite(ctx: JobContext, db: Any, suite: str, env: str = "dev", **_: Any) -> dict[str, Any]:
    from app.core.config import settings

    if settings.is_production:
        return {"refused": "production"}
    await ctx.progress(db, 5, f"running {suite}")
    p = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "verify" / "run_all.py"), "--suite", suite],  # noqa: S603
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=7200,
        check=False,
    )
    line = next((ln for ln in p.stdout.splitlines() if "→" in ln), "")
    report_dir = line.split("→")[-1].strip() if line else None
    summary = {}
    if report_dir and (BACKEND / report_dir / "summary.json").exists():
        summary = json.loads((BACKEND / report_dir / "summary.json").read_text(encoding="utf-8"))
    from app.core import events

    await events.emit(
        db,
        institution_id=ctx.institution_id,
        event_type="qa.suite_finished",
        payload={"suite": suite, "ok": p.returncode == 0, "failed": summary.get("failed")},
        aggregate_type="qa",
        aggregate_id=None,
        actor_user_id=ctx.requested_by,
    )
    return {
        "suite": suite,
        "env": env,
        "ok": p.returncode == 0,
        "report_dir": report_dir,
        **summary,
        "tail": p.stdout[-2000:],
    }


@celery.task(name="jobs.qa.access_matrix", queue="reports")
@job("qa.access_matrix", queue="reports")
async def qa_access_matrix(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    p = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "gen_access_matrix.py")],
        cwd=BACKEND,  # noqa: S603
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    return {"ok": p.returncode == 0, "out": p.stdout[-1000:]}


# ---- Beat -----------------------------------------------------------------------------------------------------------
@celery.task(name="beat.security.posture_daily", queue="scheduled")
def posture_daily() -> dict[str, int]:
    async def fn(db: Any) -> dict[str, int]:
        from app.db.session import bind_tenant, set_tenant
        from app.services.hardening.posture import PostureService

        n = 0
        for (iid,) in (
            await db.execute(text("SELECT id FROM institutions WHERE deleted_at IS NULL AND status = 'active'"))
        ).all():
            principal = _System(iid)
            bind_tenant(db, iid)
            await set_tenant(db, iid)
            try:
                await PostureService(db, principal).check()
                n += 1
            except Exception as e:  # noqa: BLE001 - one tenant never blocks the others
                log.warning("posture.check_failed", institution=str(iid), error=str(e))
        return {"checked": n}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


class _System:
    """System principal for Beat bodies (``security:manage`` within one tenant)."""

    is_super_admin = True
    roles = ["institution_admin"]
    scopes: list[Any] = []

    def __init__(self, institution_id: Any):
        self.institution_id = institution_id
        self.id = None

    def has(self, module: str, action: str) -> bool:
        return True


@celery.task(name="beat.security.mfa_enforcement_scan", queue="scheduled")
def mfa_enforcement_scan() -> dict[str, int]:
    async def fn(db: Any) -> dict[str, int]:
        from app.core.notifications.notify import notify_event
        from app.services.hardening.posture import PostureService

        rows = (
            await db.execute(
                text(
                    "SELECT institution_id, value FROM institution_settings WHERE category = 'security' AND key = 'mfa_grace_until'"
                )
            )
        ).all()
        reminded = 0
        for iid, until in rows:
            if not until or datetime.fromisoformat(str(until).strip('"')) < datetime.now(UTC):
                continue
            missing = await PostureService(db, _System(iid)).mfa_missing()
            if missing:
                await notify_event(
                    db,
                    iid,
                    "security.mfa_enforcement_reminder",
                    audience={"user_ids": [m["user_id"] for m in missing]},
                    context={"grace_until": str(until)},
                )
                reminded += len(missing)
        return {"reminded": reminded}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@celery.task(name="beat.privacy.dsr_due_reminders", queue="scheduled")
def dsr_due_reminders() -> dict[str, int]:
    async def fn(db: Any) -> dict[str, int]:
        from app.core.notifications.notify import notify_event

        rows = (
            await db.execute(
                text(
                    "SELECT id, institution_id, request_type, due_at FROM data_subject_requests WHERE status NOT IN ('completed', 'rejected') "
                    "AND due_at BETWEEN NOW() AND NOW() + INTERVAL '5 days'"
                )
            )
        ).all()
        for rid, iid, typ, due in rows:
            await notify_event(
                db,
                iid,
                "privacy.dsr_due_soon",
                audience={"roles": ["privacy_officer"]},
                context={"request_id": str(rid), "request_type": typ, "due_at": due.isoformat()},
            )
        return {"reminded": len(rows)}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@celery.task(name="beat.privacy.minor_recompute", queue="scheduled")
def minor_recompute() -> dict[str, int]:
    """Students who turned 18 today must re-consent themselves (their guardian's decisions no longer apply)."""

    async def fn(db: Any) -> dict[str, int]:
        res = await db.execute(
            text(
                "UPDATE users SET preferences = jsonb_set(coalesce(preferences, '{}'::jsonb), '{privacy}', "
                "coalesce(preferences -> 'privacy', '{}'::jsonb) || '{\"notice_version\": null, \"reconsent_adult\": true}'::jsonb) "
                "WHERE id IN (SELECT user_id FROM students WHERE user_id IS NOT NULL AND deleted_at IS NULL "
                "AND dob = (CURRENT_DATE - INTERVAL '18 years')::date)"
            )
        )
        return {"flagged": int(res.rowcount or 0)}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@celery.task(name="beat.privacy.consent_version_reminders", queue="scheduled")
def consent_version_reminders() -> dict[str, int]:
    async def fn(db: Any) -> dict[str, int]:
        from app.core.notifications.notify import notify_event

        rows = (
            await db.execute(
                text(
                    "SELECT institution_id, value ->> 'version' FROM institution_settings WHERE category = 'privacy' AND key = 'notice:dpdp_notice' "
                    "AND updated_at > NOW() - INTERVAL '30 days'"
                )
            )
        ).all()
        for iid, version in rows:
            await notify_event(
                db,
                iid,
                "privacy.consent_version_changed",
                audience={"roles": ["student", "parent", "faculty"]},
                context={
                    "version": version,
                    "reminder": True,
                    "since": (datetime.now(UTC) - timedelta(days=7)).date().isoformat(),
                },
            )
        return {"institutions": len(rows)}

    return run_async(_platform(fn))  # type: ignore[no-any-return]
