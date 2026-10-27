"""Scheduled reports (``reports.scheduled``) — Prompts/36 §36.6 ``schedule_service``.

* CRUD: a report key or a saved builder report, params, format, cadence (daily / weekly / monthly / termly / cron —
  a 5-field expression validated here) with ``at`` in the institution timezone inside ``reports.schedule_hours_allowed``
  (422 otherwise), recipients by role / user / email, channels email / WhatsApp / in-app.
* Recipients by role are resolved **at run time** and each gets the report **as that recipient** (one ``report.run``
  job per recipient with ``requested_by`` = the recipient — an HOD receives department rows); explicit emails only for
  reports without PII columns (422 ``PII_EMAIL``); private schedules (no ``reports:manage``) may only target the owner.
* ``reports.schedules_tick`` (every 5 min) runs due schedules; deliveries go through Phase 24 notifications with the
  signed link (the run's ``background_jobs.result.delivery``); history is kept on the schedule; three consecutive
  failures pause it and notify the owner. ``termly`` schedules fire on ``academic_term.status_changed``.
"""

import uuid
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.core.jobs import enqueue
from app.core.tenancy import institution_tz
from app.models.platform import BackgroundJob, InstitutionSetting
from app.models.reports import ScheduleDef
from app.schemas.reports import ScheduleHistoryOut, ScheduleIn, ScheduleOut, ScheduleRunNow
from app.services.reports.common import ReportsBase, forbidden, not_found, now_utc

__all__ = ["ScheduleService", "cron_next"]

MAX_FAILURES = 3


def _invalid(msg: str, **details: Any) -> APIError:
    return APIError(422, ErrorCode.VALIDATION, msg, details)


def _field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        if a < lo or b > hi or a > b or step < 1:
            raise ValueError(part)
        out |= set(range(a, b + 1, step))
    return out


def cron_next(expr: str, after: datetime) -> datetime:
    """Next minute matching a 5-field cron expression (minute hour day-of-month month day-of-week; 0 = Sunday)."""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("cron needs 5 fields")
    minutes, hours = _field(parts[0], 0, 59), _field(parts[1], 0, 23)
    doms, months = _field(parts[2], 1, 31), _field(parts[3], 1, 12)
    dows = {d % 7 for d in _field(parts[4], 0, 7)}
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(0, 400):
        d = t.date()
        if d.month in months and d.day in doms and ((d.isoweekday() % 7) in dows):
            for h in sorted(hours):
                if h < t.hour:
                    continue
                for m in sorted(minutes):
                    cand = t.replace(hour=h, minute=m)
                    if cand >= t:
                        return cand
        t = datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=t.tzinfo)
    raise ValueError("cron expression never fires")


class ScheduleService(ReportsBase):
    # ---- helpers ----------------------------------------------------------------------------------------------------------
    async def require_scheduler(self) -> None:
        if not await self.feature_on("reports.scheduled"):
            raise APIError(
                403,
                ErrorCode.FEATURE_DISABLED,
                "Feature reports.scheduled is not enabled",
                {"feature": "reports.scheduled"},
            )
        if not (self.can("reports", "schedule") or self.is_admin()):
            raise forbidden("reports:schedule required")

    async def tz(self) -> Any:
        return institution_tz(await self.institution())

    def can_edit(self, s: ScheduleDef) -> bool:
        return self.is_admin() or s.owner == str(self.actor_id)

    async def _all(self) -> dict[str, ScheduleDef]:
        return {k: ScheduleDef.from_dict({**v, "id": k}) for k, v in (await self.metas("schedule")).items()}

    async def _one(self, sid: str) -> ScheduleDef:
        v = await self.meta("schedule", sid)
        if not v:
            raise not_found("Schedule")
        s = ScheduleDef.from_dict({**v, "id": sid})
        if not (self.can_edit(s) or self.sees_all_runs()):
            raise not_found("Schedule")
        return s

    async def _save(self, s: ScheduleDef) -> None:
        await self.put_meta("schedule", s.id, s.as_dict())

    async def out(self, s: ScheduleDef, names: dict[uuid.UUID, str] | None = None) -> ScheduleOut:
        owner = uuid.UUID(s.owner) if s.owner else None
        return ScheduleOut(
            id=s.id,
            name=s.name,
            key=s.key,
            saved_report_id=s.saved_report_id,
            params=s.params,
            format=s.format,
            cadence=s.cadence,
            at=s.at,
            weekday=s.weekday,
            day_of_month=s.day_of_month,
            cron=s.cron,
            recipients=s.recipients,
            channels=s.channels,
            is_active=s.is_active,
            paused_reason=s.paused_reason,
            failures=s.failures,
            owner=owner,
            owner_name=(names or {}).get(owner) if owner else None,
            last_run_at=self.utc(s.last_run_at),
            next_run_at=self.utc(s.next_run_at),
        )

    async def next_run(self, s: ScheduleDef, after: datetime | None = None) -> str | None:
        if not s.is_active or s.cadence == "termly":
            return None
        tz = await self.tz()
        now = (after or now_utc()).astimezone(tz)
        hh, mm = (int(x) for x in s.at.split(":"))
        if s.cadence == "cron":
            nxt = cron_next(s.cron or "", now)
        else:
            cand = datetime.combine(now.date(), time(hh, mm), tzinfo=tz)
            if s.cadence == "daily":
                if cand <= now:
                    cand += timedelta(days=1)
            elif s.cadence == "weekly":
                wd = 0 if s.weekday is None else s.weekday  # 0 = Monday
                cand += timedelta(days=(wd - cand.weekday()) % 7)
                if cand <= now:
                    cand += timedelta(days=7)
            else:  # monthly
                dom = s.day_of_month or 1
                cand = cand.replace(day=dom)
                if cand <= now:
                    y, m = (cand.year + 1, 1) if cand.month == 12 else (cand.year, cand.month + 1)
                    cand = cand.replace(year=y, month=m)
            nxt = cand
        return nxt.astimezone(UTC).isoformat()

    async def _validate(self, body: ScheduleIn) -> Any:
        """→ the ReportDef / saved definition being scheduled (422 on any guard)."""
        from app.services.reports.builder_service import BuilderService
        from app.services.reports.report_service import ReportService, validate_params

        hours = await self.r_setting("schedule_hours_allowed", [5, 22]) or [5, 22]
        hh, mm = (int(x) for x in body.at.split(":"))
        if not (0 <= mm < 60 and int(hours[0]) <= hh <= int(hours[1]) and not (hh == int(hours[1]) and mm > 0)):
            raise _invalid(f"at must be between {int(hours[0]):02d}:00 and {int(hours[1]):02d}:00", code="HOURS")
        if body.cadence == "cron":
            try:
                cron_next(body.cron or "", now_utc())
            except ValueError as exc:
                raise _invalid(f"Invalid cron expression ({exc})", code="CRON") from exc
            fields = (body.cron or "").split()
            for h in _field(fields[1], 0, 23):
                if not int(hours[0]) <= h <= int(hours[1]):
                    raise _invalid("cron hours must fall inside schedule_hours_allowed", code="HOURS")
        pii = False
        if body.key:
            d = await ReportService(self.db, self.principal, institution_id=self.inst).report_def(body.key)
            validate_params(d.params_schema, body.params)
            pii, target = bool(d.pii_fields), d.name
        else:
            b = BuilderService(self.db, self.principal, institution_id=self.inst)
            v, saved = await b.saved(body.saved_report_id or "")
            from app.core.reports import MODEL_REGISTRY

            m = MODEL_REGISTRY.get((v.get("definition") or {}).get("model_key") or "")
            cols = set((v.get("definition") or {}).get("columns") or [])
            pii = bool(m and any(c.pii for k, c in m.column_map(None).items() if k in cols))
            target = saved.name
        r = body.recipients
        if r.emails and pii:
            raise _invalid("Reports with personal data cannot be sent to external emails", code="PII_EMAIL")
        others = [u for u in r.user_ids if u != self.actor_id]
        delegates = self.can("reports", "view_all") or any(x in self.roles() for x in ("registrar", "hod", "dean"))
        if not self.is_admin() and (others or r.roles or r.emails) and not delegates:
            raise _invalid("Private schedules can only be delivered to yourself", code="PRIVATE_SCHEDULE")
        if not (r.roles or r.user_ids or r.emails):
            r.user_ids = [self.actor_id] if self.actor_id else []
        return target

    # ---- CRUD -------------------------------------------------------------------------------------------------------------
    async def schedules(self) -> list[ScheduleOut]:
        await self.require_scheduler()
        items = [s for s in (await self._all()).values() if self.can_edit(s) or self.sees_all_runs()]
        names = await self.user_display([uuid.UUID(s.owner) for s in items if s.owner])
        return [await self.out(s, names) for s in sorted(items, key=lambda s: s.name or s.key or "")]

    async def get(self, sid: str) -> ScheduleOut:
        await self.require_scheduler()
        return await self.out(await self._one(sid))

    async def create(self, body: ScheduleIn) -> ScheduleOut:
        await self.require_scheduler()
        self.require_writer()
        target = await self._validate(body)
        s = ScheduleDef(
            id=uuid.uuid4().hex[:16],
            key=body.key,
            saved_report_id=body.saved_report_id,
            params=body.params,
            format=body.format,
            cadence=body.cadence,
            at=body.at,
            weekday=body.weekday,
            day_of_month=body.day_of_month,
            cron=body.cron,
            recipients=body.recipients.model_dump(mode="json"),
            channels=list(body.channels),
            is_active=body.is_active,
            owner=str(self.actor_id) if self.actor_id else None,
            name=body.name or target,
        )
        s.next_run_at = await self.next_run(s)
        await self._save(s)
        await self._audit("schedule_created", "report_schedule", None, None, {"key": s.key, "id": s.id})
        await self._emit("reports.schedule_created", {"id": s.id, "key": s.key}, "report_schedule", None)
        return await self.out(s)

    async def update(self, sid: str, body: ScheduleIn) -> ScheduleOut:
        await self.require_scheduler()
        self.require_writer()
        s = await self._one(sid)
        if not self.can_edit(s):
            raise forbidden("Only the owner or a reports manager can edit this schedule")
        await self._validate(body)
        s.key, s.saved_report_id, s.params, s.format = body.key, body.saved_report_id, body.params, body.format
        s.cadence, s.at, s.weekday, s.day_of_month, s.cron = (
            body.cadence,
            body.at,
            body.weekday,
            body.day_of_month,
            body.cron,
        )
        s.recipients, s.channels, s.is_active = (
            body.recipients.model_dump(mode="json"),
            list(body.channels),
            body.is_active,
        )
        s.name = body.name or s.name
        s.next_run_at = await self.next_run(s)
        await self._save(s)
        await self._emit("reports.schedule_updated", {"id": s.id}, "report_schedule", None)
        return await self.out(s)

    async def delete(self, sid: str) -> None:
        await self.require_scheduler()
        self.require_writer()
        s = await self._one(sid)
        if not self.can_edit(s):
            raise forbidden("Only the owner or a reports manager can delete this schedule")
        row = (
            await self.db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.category == self.meta_category,
                    InstitutionSetting.key == f"schedule:{sid}",
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await self.db.delete(row)
            await self.db.flush()

    async def set_active(self, sid: str, active: bool) -> ScheduleOut:
        await self.require_scheduler()
        self.require_writer()
        s = await self._one(sid)
        if not self.can_edit(s):
            raise forbidden("Only the owner or a reports manager can pause / resume this schedule")
        s.is_active = active
        s.paused_reason = None if active else "paused by user"
        if active:
            s.failures = 0
        s.next_run_at = await self.next_run(s)
        await self._save(s)
        await self._emit(
            "reports.schedule_paused" if not active else "reports.schedule_updated",
            {"id": s.id},
            "report_schedule",
            None,
        )
        return await self.out(s)

    async def history(self, sid: str) -> list[ScheduleHistoryOut]:
        await self.require_scheduler()
        s = await self._one(sid)
        out = []
        for h in reversed(s.history[-100:]):
            out.append(
                ScheduleHistoryOut(
                    run_at=self.utc(h.get("run_at")),
                    status=str(h.get("status") or ""),
                    result_url=h.get("result_url"),
                    delivered_to=list(h.get("delivered_to") or []),
                    job_id=uuid.UUID(h["job_id"]) if h.get("job_id") else None,
                    error=h.get("error"),
                )
            )
        return out

    # ---- running -----------------------------------------------------------------------------------------------------------
    async def recipients(self, s: ScheduleDef) -> list[uuid.UUID]:
        users: list[uuid.UUID] = []
        for role in s.recipients.get("roles") or []:
            users += [u for u in await self.role_holders(role) if u not in users]
        users += [uuid.UUID(str(u)) for u in s.recipients.get("user_ids") or [] if uuid.UUID(str(u)) not in users]
        return users

    async def fire(self, s: ScheduleDef) -> list[uuid.UUID]:
        """One job per recipient, run **as** that recipient (their scope); explicit emails ride the owner's job."""
        users = await self.recipients(s)
        owner = uuid.UUID(s.owner) if s.owner else None
        jobs: list[uuid.UUID] = []
        emails = list(s.recipients.get("emails") or [])
        targets = users or ([owner] if owner else [])
        for i, uid in enumerate(targets):
            actor = SimpleNamespace(id=uid, institution_id=self.inst)
            deliver = {"user_ids": [str(uid)], "emails": emails if i == 0 else []}
            params: dict[str, Any] = {
                "params": s.params,
                "format": s.format,
                "schedule_id": s.id,
                "deliver_to": deliver,
                "channels": s.channels,
            }
            if s.key:
                job = await enqueue(self.db, actor, "report.run", {"key": s.key, **params}, task_name="jobs.report.run")
            else:
                job = await enqueue(
                    self.db,
                    actor,
                    "report.schedule_deliver",
                    {"key": f"saved.{s.saved_report_id}", "saved_report_id": s.saved_report_id, **params},
                    task_name="jobs.report.schedule_deliver",
                )
            jobs.append(job.id)
        s.last_run_at = now_utc().isoformat()
        s.history.append(
            {
                "run_at": s.last_run_at,
                "status": "queued",
                "jobs": [str(j) for j in jobs],
                "delivered_to": [str(u) for u in targets] + emails,
            }
        )
        s.history = s.history[-100:]
        s.next_run_at = await self.next_run(s, now_utc())
        await self._save(s)
        return jobs

    async def run_now(self, sid: str) -> ScheduleRunNow:
        await self.require_scheduler()
        s = await self._one(sid)
        if not self.can_edit(s):
            raise forbidden("Only the owner or a reports manager can run this schedule")
        jobs = await self.fire(s)
        return ScheduleRunNow(jobs=jobs, recipients=len(jobs))

    async def tick(self) -> int:
        """Beat body: fire every active schedule whose ``next_run_at`` passed; settle finished runs into history."""
        await self.settle()
        now = now_utc()
        fired = 0
        for s in (await self._all()).values():
            nxt = self.utc(s.next_run_at)
            if not s.is_active or nxt is None or nxt > now:
                continue
            await self.fire(s)
            fired += 1
        return fired

    async def on_term_status(self, term_id: str, status: str) -> int:
        fired = 0
        for s in (await self._all()).values():
            if s.is_active and s.cadence == "termly" and (s.params.get("on_term_status") or "closed") == status:
                await self.fire(s)
                fired += 1
        return fired

    async def settle(self) -> None:
        """Copy job outcomes into the history entries; 3 consecutive failures pause the schedule and notify the owner."""
        for s in (await self._all()).values():
            pending = [h for h in s.history if h.get("status") == "queued" and h.get("jobs")]
            if not pending:
                continue
            changed = False
            for h in pending:
                ids = [uuid.UUID(j) for j in h["jobs"]]
                rows = list((await self.db.execute(select(BackgroundJob).where(BackgroundJob.id.in_(ids)))).scalars())
                if any(j.status not in ("succeeded", "failed", "cancelled") for j in rows):
                    continue
                failed = [j for j in rows if j.status != "succeeded"]
                h["status"] = (
                    "failed" if failed and len(failed) == len(rows) else ("partial" if failed else "delivered")
                )
                h["result_url"] = next((j.result_url for j in rows if j.result_url), None)
                h["error"] = next((j.error for j in failed if j.error), None)
                s.failures = s.failures + 1 if h["status"] == "failed" else 0
                changed = True
                if h["status"] != "failed":
                    await self._emit(
                        "reports.schedule_delivered", {"id": s.id, "jobs": h["jobs"]}, "report_schedule", None
                    )
            if s.failures >= MAX_FAILURES and s.is_active:
                s.is_active, s.paused_reason, s.next_run_at = (
                    False,
                    f"paused after {MAX_FAILURES} consecutive failures",
                    None,
                )
                if s.owner:
                    await self._notify(
                        "reports.failed",
                        [uuid.UUID(s.owner)],
                        {
                            "report": s.name or s.key or "schedule",
                            "key": s.key or "",
                            "error": s.paused_reason,
                            "job_id": "",
                        },
                    )
                await self._emit(
                    "reports.schedule_paused", {"id": s.id, "reason": s.paused_reason}, "report_schedule", None
                )
            if changed:
                await self._save(s)
