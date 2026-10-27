"""Retention, purge, archival, legal holds and erasure — Prompts/37 §37.6 ``retention_service`` (``settings:manage``).

1. **Policies** live in the setting ``privacy.retention`` (``RETENTION_DEFAULTS``); an institution may shorten a
   period but never exceed ``RETENTION_MAXIMUMS`` (422) nor go below ``RETENTION_MINIMUMS`` for the archive ages.
   ``preview(data_class)`` counts the rows a purge / archive would touch and those exempt by legal holds.
2. **Legal holds** (``audit_meta legal_hold:<id>``; ``settings:manage`` or ``legal:manage``) exempt rows by batch,
   enrolments, exam session (its registered students) or date range; the active hold ids are mirrored into
   ``privacy.retention.legal_hold``.
3. **Purge** (job ``retention.purge``; Beat ``retention.purge_daily`` 03:30 for every class) per data class:
   ``login_history`` / ``notifications`` / ``webhook_deliveries`` / ``vehicle_gps_logs`` rows deleted,
   ``message_logs`` content cleared (subject / preview) and delivery metadata deleted one year later,
   ``domain_events`` (dispatched) archived to the file store as JSON lines then deleted, ``visitor_passes`` PII
   anonymised, job / report files removed from the file store (report runs keep their checksum → 410). Users of held
   students and rows inside held date ranges are kept. Each run writes a manifest (``manifest:<id>``) and an audit row
   with counts — a second run purges 0 (idempotent).
4. **Archival** (job ``retention.archive``; Beat ``retention.archive_monthly``) of closed academic years / cold
   periods of ``student_class_attendance``, ``message_logs`` and ``audit_logs`` (only after
   ``audit_logs_archive_after_years`` — audit rows are never deleted before they are archived and their daily digests
   stay verifiable): the tenant's rows of the period are exported to CSV with a sha256 manifest under
   ``{institution}/archive/{class}/{period}/`` and then removed; when a monthly partition holds only this tenant's rows
   it is ``DETACH``-ed and dropped (platform role, advisory lock). **Restore** (super admin, job
   ``retention.restore``) loads the archive into ``<table>_restored`` (same columns, no triggers — the chain hashes are
   kept as archived) for audits.
5. ``erase(user_id)`` (DSR — Phase 43 completes the DPDP flow) anonymises PII in non-record tables (login history
   identifiers / user agents, notifications, message recipients, sessions) and records an ``erase`` manifest; academic
   records are retained per policy.
"""

import contextlib
import csv
import hashlib
import io
import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core.errors import APIError, ErrorCode
from app.core.jobs import enqueue
from app.enums.audit import (
    ARCHIVE_TARGETS,
    PURGE_TARGETS,
    RETENTION_DEFAULTS,
    RETENTION_MAXIMUMS,
    RETENTION_MINIMUMS,
)
from app.schemas.audit import (
    ArchiveManifestOut,
    JobQueuedOut,
    LegalHoldIn,
    LegalHoldOut,
    RetentionPolicyIn,
    RetentionPolicyOut,
    RetentionPreviewOut,
    RetentionRunRequest,
)
from app.schemas.settings import SettingItem
from app.services.audit.common import AuditBase, forbidden, not_found, now_utc, rule
from app.services.settings_service import SettingsService

LOCK_KEY = 37_037


class RetentionService(AuditBase):
    audit_module = "retention"

    def require_manage(self) -> None:
        self.require("settings:manage")
        self.require_writer()

    def require_read(self) -> None:
        if not (
            self.can("settings", "manage")
            or self.can("settings", "view")
            and (self.views_all() or self.can("audit_logs", "verify_chain"))
        ):
            raise forbidden("settings:manage required")

    # ---- policies ---------------------------------------------------------------------------------------------------
    async def policy(self) -> dict[str, Any]:
        v = await self.a_setting("privacy", "retention", RETENTION_DEFAULTS)
        return {**RETENTION_DEFAULTS, **(v if isinstance(v, dict) else {})}

    async def policies(self) -> RetentionPolicyOut:
        self.require_read()
        return RetentionPolicyOut(
            values=await self.policy(),
            maximums=RETENTION_MAXIMUMS,
            minimums=RETENTION_MINIMUMS,
            defaults=RETENTION_DEFAULTS,
        )

    async def put_policies(self, body: RetentionPolicyIn) -> RetentionPolicyOut:
        self.require_manage()
        errors = []
        for k, v in body.values.items():
            if k not in RETENTION_MAXIMUMS:
                errors.append({"field": k, "reason": "unknown policy key"})
            elif not isinstance(v, int) or isinstance(v, bool) or v < 1:
                errors.append({"field": k, "reason": "must be a positive integer"})
            elif v > RETENTION_MAXIMUMS[k]:
                errors.append({"field": k, "reason": f"above the platform maximum {RETENTION_MAXIMUMS[k]}"})
            elif v < RETENTION_MINIMUMS.get(k, 1):
                errors.append({"field": k, "reason": f"below the minimum {RETENTION_MINIMUMS[k]}"})
        if errors:
            raise APIError(422, ErrorCode.VALIDATION, "Invalid retention policy", {"errors": errors})
        value = {**await self.policy(), **body.values}
        await SettingsService(self.db, self.principal).bulk_update(
            [SettingItem(category="privacy", key="retention", value=value)],
            self.request,
            reason=body.reason or "retention policy",
            strict=True,
        )
        return await self.policies()

    def cutoff(self, policy: dict[str, Any], key: str) -> datetime:
        return now_utc() - timedelta(days=int(policy.get(key) or RETENTION_DEFAULTS[key]))

    # ---- legal holds ------------------------------------------------------------------------------------------------
    def require_holds(self) -> None:
        self.require("settings:manage", "legal:manage")
        self.require_writer()

    async def legal_holds(self, active_only: bool = True) -> list[LegalHoldOut]:
        self.require("settings:manage", "legal:manage", "settings:view")
        today = now_utc().date()
        out = []
        for hid, m in await self.meta_list("legal_hold"):
            until = date.fromisoformat(m["until"]) if m.get("until") else None
            active = not m.get("cleared_at") and (until is None or until >= today)
            if active_only and not active:
                continue
            out.append(
                LegalHoldOut(
                    id=hid,
                    data_class=m["data_class"],
                    scope=m.get("scope") or {},
                    reason=m.get("reason") or "",
                    until=until,
                    set_by=_uuid(m.get("set_by")),
                    set_at=datetime.fromisoformat(m["set_at"]),
                    active=active,
                )
            )
        return out

    async def add_hold(self, body: LegalHoldIn) -> LegalHoldOut:
        self.require_holds()
        if body.data_class not in (*PURGE_TARGETS, *ARCHIVE_TARGETS, "all"):
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown data class {body.data_class}", {"field": "data_class"})
        scope = body.scope.model_dump(mode="json", exclude_none=True)
        if not scope:
            raise APIError(422, ErrorCode.VALIDATION, "A legal hold needs a scope", {"field": "scope"})
        hid = uuid.uuid4().hex[:12]
        doc = {
            "data_class": body.data_class,
            "scope": scope,
            "reason": body.reason,
            "until": body.until.isoformat() if body.until else None,
            "set_by": str(self.actor_id) if self.actor_id else None,
            "set_at": now_utc().isoformat(),
            "created_at": now_utc().isoformat(),
        }
        await self.put_meta("legal_hold", hid, doc)
        await self._mirror_holds()
        await self._audit("legal_hold_set", "legal_hold", None, None, {"id": hid, **doc})
        await self._emit(
            "retention.legal_hold_set", {"id": hid, "data_class": body.data_class}, "institution", self.inst
        )
        await self._notify(
            "retention.legal_hold_set",
            [],
            {"data_class": body.data_class, "scope": json.dumps(scope), "reason": body.reason},
            audience={"roles": ["institution_admin"]},
        )
        return await self._hold_out(hid)

    async def _hold_out(self, hid: str) -> LegalHoldOut:
        for h in await self.legal_holds(active_only=False):
            if h.id == hid:
                return h
        raise not_found("Legal hold")

    async def clear_hold(self, hid: str) -> LegalHoldOut:
        self.require_holds()
        m = await self.meta("legal_hold", hid)
        if not m:
            raise not_found("Legal hold")
        m["cleared_at"], m["cleared_by"] = now_utc().isoformat(), str(self.actor_id) if self.actor_id else None
        await self.put_meta("legal_hold", hid, m)
        await self._mirror_holds()
        await self._audit("legal_hold_cleared", "legal_hold", None, None, {"id": hid})
        await self._emit("retention.legal_hold_cleared", {"id": hid}, "institution", self.inst)
        return await self._hold_out(hid)

    async def _mirror_holds(self) -> None:
        from app.repositories.institution_repository import SettingsRepository
        from app.services.settings_service import invalidate_settings_cache

        active = [h.id for h in await self.legal_holds(active_only=True)]
        value = {**await self.policy(), "legal_hold": active}
        await SettingsRepository(self.db).upsert(
            self.inst,
            "privacy",
            "retention",
            value=value,
            value_type="json",
            is_public=False,
            college_id=None,
            updated_by=self.actor_id,
        )
        await invalidate_settings_cache(self.inst, ["privacy"])

    async def held(self, data_class: str) -> tuple[list[uuid.UUID], list[tuple[date, date]]]:
        """→ (user ids of held students, held date ranges) for a data class."""
        users: set[uuid.UUID] = set()
        ranges: list[tuple[date, date]] = []
        for h in await self.legal_holds(active_only=True):
            if h.data_class not in (data_class, "all"):
                continue
            s = h.scope
            if s.get("batch_id"):
                users |= {
                    u
                    for (u,) in (
                        await self.db.execute(
                            text(
                                "SELECT st.user_id FROM student_program_enrollments e JOIN students st ON st.id = e.student_id "
                                "WHERE e.batch_id = :b AND st.user_id IS NOT NULL"
                            ),
                            {"b": s["batch_id"]},
                        )
                    ).all()
                }
            if s.get("enrollment_ids"):
                users |= {
                    u
                    for (u,) in (
                        await self.db.execute(
                            text(
                                "SELECT st.user_id FROM student_program_enrollments e JOIN students st ON st.id = e.student_id "
                                "WHERE e.id = ANY(:e) AND st.user_id IS NOT NULL"
                            ),
                            {"e": [uuid.UUID(str(x)) for x in s["enrollment_ids"]]},
                        )
                    ).all()
                }
            if s.get("exam_session_id"):
                users |= {
                    u
                    for (u,) in (
                        await self.db.execute(
                            text(
                                "SELECT DISTINCT st.user_id FROM exam_registrations r JOIN student_program_enrollments e ON "
                                "e.id = r.student_program_enrollment_id JOIN students st ON st.id = e.student_id WHERE "
                                "r.exam_session_id = :x AND st.user_id IS NOT NULL"
                            ),
                            {"x": s["exam_session_id"]},
                        )
                    ).all()
                }
            if s.get("date_from") or s.get("date_to"):
                ranges.append(
                    (
                        date.fromisoformat(s.get("date_from") or "1970-01-01"),
                        date.fromisoformat(s.get("date_to") or "2999-12-31"),
                    )
                )
        return sorted(users, key=str), ranges

    @staticmethod
    def _exempt_sql(
        ts: str, user_col: str | None, users: list[uuid.UUID], ranges: list[tuple[date, date]], b: dict[str, Any]
    ) -> str:
        parts = []
        if user_col and users:
            parts.append(f"({user_col} IS NULL OR NOT ({user_col} = ANY(:_held_users)))")
            b["_held_users"] = users
        for i, (lo, hi) in enumerate(ranges):
            parts.append(f"NOT ({ts}::date BETWEEN :_hlo{i} AND :_hhi{i})")
            b[f"_hlo{i}"], b[f"_hhi{i}"] = lo, hi
        return " AND ".join(parts) if parts else "TRUE"

    # ---- preview ----------------------------------------------------------------------------------------------------
    async def preview(self, data_class: str) -> RetentionPreviewOut:
        self.require_read()
        policy = await self.policy()
        if data_class in PURGE_TARGETS and "table" in PURGE_TARGETS[data_class]:
            t = PURGE_TARGETS[data_class]
            cutoff = self.cutoff(policy, t["policy"])
            users, ranges = await self.held(data_class)
            b: dict[str, Any] = {"i": self.inst, "c": cutoff}
            extra = f" AND {t['where']}" if t.get("where") else ""
            base = f"FROM {t['table']} WHERE institution_id = :i AND {t['ts']} < :c{extra}"
            total = int((await self.db.execute(text(f"SELECT COUNT(*) {base}"), b)).scalar_one())
            exempt = self._exempt_sql(t["ts"], t.get("user_col"), users, ranges, b)
            eligible = int((await self.db.execute(text(f"SELECT COUNT(*) {base} AND {exempt}"), b)).scalar_one())
            return RetentionPreviewOut(
                data_class=data_class,
                policy_key=t["policy"],
                keep=int(policy[t["policy"]]),
                cutoff=cutoff,
                eligible=eligible,
                held=total - eligible,
            )
        if data_class in PURGE_TARGETS:
            t = PURGE_TARGETS[data_class]
            cutoff = self.cutoff(policy, t["policy"])
            n = len(await self._file_jobs(t["files"], cutoff))
            return RetentionPreviewOut(
                data_class=data_class,
                policy_key=t["policy"],
                keep=int(policy[t["policy"]]),
                cutoff=cutoff,
                eligible=n,
                held=0,
            )
        if data_class in ARCHIVE_TARGETS:
            a = ARCHIVE_TARGETS[data_class]
            return RetentionPreviewOut(
                data_class=data_class,
                policy_key=a["policy"],
                keep=int(policy[a["policy"]]),
                eligible=0,
                held=0,
                partitions=await self.partitions(a["table"]),
            )
        raise APIError(422, ErrorCode.VALIDATION, f"Unknown data class {data_class}", {"field": "data_class"})

    async def partitions(self, parent: str) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                text(
                    "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                    "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = :t ORDER BY c.relname"
                ),
                {"t": parent},
            )
        ).all()
        return [{"name": n, "bound": b} for n, b in rows]

    # ---- jobs -------------------------------------------------------------------------------------------------------
    async def enqueue_run(self, kind: str, body: RetentionRunRequest) -> JobQueuedOut:
        self.require_manage()
        if kind == "purge" and body.data_class not in PURGE_TARGETS:
            raise APIError(422, ErrorCode.VALIDATION, f"{body.data_class} is not purgeable", {"field": "data_class"})
        if kind == "archive":
            if body.data_class not in ARCHIVE_TARGETS:
                raise APIError(
                    422, ErrorCode.VALIDATION, f"{body.data_class} is not archivable", {"field": "data_class"}
                )
            if not body.period:
                raise APIError(422, ErrorCode.VALIDATION, "period is required", {"field": "period"})
            await self.period_bounds(body.data_class, body.period)  # validates before queuing
        job = await enqueue(
            self.db,
            self.principal,
            f"retention.{kind}",
            body.model_dump(mode="json"),
            task_name=f"jobs.retention.{kind}",
        )
        return JobQueuedOut(job_id=job.id, job_type=f"retention.{kind}")

    async def enqueue_restore(self, manifest_id: str) -> JobQueuedOut:
        if not getattr(self.principal, "is_super_admin", False):
            raise forbidden("Restoring an archive is a super-admin operation")
        m = await self.meta("manifest", manifest_id)
        if not m or m.get("kind") != "archive":
            raise not_found("Archive manifest")
        job = await enqueue(
            self.db,
            self.principal,
            "retention.restore",
            {"manifest_id": manifest_id},
            task_name="jobs.retention.restore",
        )
        return JobQueuedOut(job_id=job.id, job_type="retention.restore")

    async def _manifest(self, kind: str, data_class: str, rows: int, period: str | None = None, **extra: Any) -> str:
        mid = uuid.uuid4().hex[:12]
        await self.put_meta(
            "manifest",
            mid,
            {
                "id": mid,
                "kind": kind,
                "data_class": data_class,
                "period": period,
                "rows": rows,
                "status": extra.pop("status", "done"),
                "created_at": now_utc().isoformat(),
                "created_by": str(self.actor_id) if self.actor_id else None,
                **extra,
            },
        )
        return mid

    async def _file_jobs(self, files: str, cutoff: datetime) -> list[Any]:
        from sqlalchemy import select

        from app.models.platform import BackgroundJob
        from app.models.reports import REPORT_JOB_TYPES

        stmt = select(BackgroundJob).where(
            BackgroundJob.institution_id == self.inst,
            BackgroundJob.created_at < cutoff,
            BackgroundJob.status == "succeeded",
            BackgroundJob.result_url.is_not(None),
        )
        if files == "reports":
            stmt = stmt.where(BackgroundJob.job_type.in_(REPORT_JOB_TYPES))
        elif files == "jobs":
            stmt = stmt.where(BackgroundJob.job_type.notin_(REPORT_JOB_TYPES))
        else:
            return []  # document previews are rendered on demand (no stored preview column on issued_documents)
        return [j for j in (await self.db.execute(stmt)).scalars() if not (j.result or {}).get("purged")]

    async def purge_now(self, data_class: str, dry_run: bool = False) -> dict[str, Any]:
        from app.core.files import build_key, get_storage

        t = PURGE_TARGETS.get(data_class)
        if t is None:
            raise rule(f"{data_class} is not purgeable", "NOT_PURGEABLE", 422)
        policy = await self.policy()
        cutoff = self.cutoff(policy, t["policy"])
        if dry_run:
            return (await self.preview(data_class)).model_dump(mode="json")
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(:k, hashtext(:c))"), {"k": LOCK_KEY, "c": f"{self.inst}:{data_class}"}
        )
        n = 0
        extra: dict[str, Any] = {}
        if "files" in t:
            storage = get_storage()
            for j in await self._file_jobs(t["files"], cutoff):
                r = dict(j.result or {})
                if r.get("storage_key"):
                    with contextlib.suppress(Exception):  # already gone is fine
                        await storage.delete(str(r["storage_key"]))
                r["purged"], r["purged_at"] = True, now_utc().isoformat()
                j.result, j.result_url = r, None
                n += 1
            await self.db.flush()
        else:
            users, ranges = await self.held(data_class)
            b: dict[str, Any] = {"i": self.inst, "c": cutoff}
            exempt = self._exempt_sql(t["ts"], t.get("user_col"), users, ranges, b)
            where = f"institution_id = :i AND {t['ts']} < :c AND {exempt}" + (
                f" AND {t['where']}" if t.get("where") else ""
            )
            table = t["table"]
            if t.get("content_only"):
                res: Any = await self.db.execute(
                    text(
                        f"UPDATE {table} SET subject = NULL, body_preview = NULL WHERE {where} AND (subject IS NOT NULL OR body_preview IS NOT NULL)"
                    ),
                    b,
                )
                n = int(res.rowcount or 0)
                b["c2"] = cutoff - timedelta(days=365)
                res = await self.db.execute(text(f"DELETE FROM {table} WHERE {where.replace(':c ', ':c2 ')}"), b)
                extra["metadata_deleted"] = int(res.rowcount or 0)
            elif t.get("anonymise"):
                res = await self.db.execute(
                    text(
                        f"UPDATE {table} SET visitor = jsonb_build_object('name', 'redacted'), id_proof = NULL, vehicle_no = NULL WHERE {where} AND visitor ->> 'name' IS DISTINCT FROM 'redacted'"
                    ),
                    b,
                )
                n = int(res.rowcount or 0)
            else:
                if data_class == "domain_events":
                    rows = (
                        (
                            await self.db.execute(
                                text(
                                    f"SELECT id, event_type, aggregate_type, aggregate_id, payload, created_at FROM {table} WHERE {where} ORDER BY created_at LIMIT 200000"
                                ),
                                b,
                            )
                        )
                        .mappings()
                        .all()
                    )
                    if rows:
                        body = "\n".join(json.dumps(dict(r), default=str) for r in rows).encode()
                        key = build_key(
                            self.inst, f"archive/domain_events/{now_utc():%Y-%m}", f"{uuid.uuid4().hex[:8]}.jsonl"
                        )
                        await get_storage().put(key, body, "application/x-ndjson")
                        extra.update({"storage_key": key, "sha256": hashlib.sha256(body).hexdigest()})
                res = await self.db.execute(text(f"DELETE FROM {table} WHERE {where}"), b)
                n = int(res.rowcount or 0)
            extra["held_users"] = len(users)
        mid = await self._manifest("purge", data_class, n, cutoff=cutoff.isoformat(), **extra)
        await self._audit(
            "purge",
            "retention",
            None,
            None,
            {"data_class": data_class, "rows": n, "manifest_id": mid, "cutoff": cutoff.isoformat(), **extra},
        )
        await self._emit(
            "retention.purged", {"data_class": data_class, "rows": n, "manifest_id": mid}, "institution", self.inst
        )
        return {"data_class": data_class, "rows": n, "manifest_id": mid}

    async def purge_all(self) -> int:
        total = 0
        for dc in PURGE_TARGETS:
            total += int((await self.purge_now(dc))["rows"])
        return total

    # ---- archive ----------------------------------------------------------------------------------------------------
    async def period_bounds(self, data_class: str, period: str) -> tuple[date, date]:
        policy = await self.policy()
        a = ARCHIVE_TARGETS[data_class]
        row = (
            await self.db.execute(
                text(
                    "SELECT start_date, end_date, is_locked FROM academic_years WHERE institution_id = :i AND name = :n ORDER BY college_id NULLS FIRST LIMIT 1"
                ),
                {"i": self.inst, "n": period},
            )
        ).first()
        if row is not None:
            lo, hi, locked = row[0], row[1] + timedelta(days=1), bool(row[2])
            if data_class == "attendance" and not locked:
                raise rule(f"Academic year {period} is not closed", "YEAR_NOT_CLOSED")
        else:
            try:
                if len(period) == 7 and period[4] == "-" and period[5:].isdigit() and int(period[5:]) <= 12:
                    y, m = int(period[:4]), int(period[5:])
                    lo = date(y, m, 1)
                    hi = date(y + (m == 12), m % 12 + 1, 1)
                else:
                    y = int(period[:4])
                    lo, hi = date(y, 6, 1), date(y + 1, 6, 1)
            except ValueError as exc:
                raise APIError(
                    422, ErrorCode.VALIDATION, "period must be an academic year name or YYYY-MM", {"field": "period"}
                ) from exc
        keep = int(policy[a["policy"]])
        age_limit = now_utc().date() - (
            timedelta(days=keep) if a["policy"].endswith("_days") else timedelta(days=365 * keep)
        )
        if hi > age_limit:
            raise rule(f"{period} is newer than the archive policy ({a['policy']} = {keep})", "TOO_RECENT")
        return lo, hi

    async def archive_now(self, data_class: str, period: str) -> dict[str, Any]:
        from app.core.files import build_key, get_storage

        a = ARCHIVE_TARGETS[data_class]
        lo, hi = await self.period_bounds(data_class, period)
        users, ranges = await self.held(data_class)
        table, ts = a["table"], a["ts"]
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(:k, hashtext(:c))"),
            {"k": LOCK_KEY, "c": f"{self.inst}:archive:{data_class}"},
        )
        b: dict[str, Any] = {"i": self.inst, "lo": lo, "hi": hi}
        exempt = self._exempt_sql(
            ts, "user_id" if data_class in ("message_logs", "audit_logs") else None, users, ranges, b
        )
        where = f"institution_id = :i AND {ts} >= :lo AND {ts} < :hi AND {exempt}"
        res = await self.db.execute(text(f"SELECT * FROM {table} WHERE {where} ORDER BY {ts}"), b)
        cols = list(res.keys())
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        n = 0
        for r in res.all():
            w.writerow(
                [json.dumps(v, default=str) if isinstance(v, dict | list) else ("" if v is None else str(v)) for v in r]
            )
            n += 1
        body = buf.getvalue().encode()
        sha = hashlib.sha256(body).hexdigest()
        key = build_key(self.inst, f"archive/{data_class}/{period}", f"{table}.csv")
        await get_storage().put(key, body, "text/csv")
        deleted = 0
        if n:
            dres: Any = await self.db.execute(text(f"DELETE FROM {table} WHERE {where}"), b)
            deleted = int(dres.rowcount or 0)
        detached = await self._detach_empty(table, lo, hi)
        mid = await self._manifest(
            "archive",
            data_class,
            n,
            period,
            storage_key=key,
            sha256=sha,
            columns=cols,
            table=table,
            deleted=deleted,
            detached=detached,
            held_users=len(users),
        )
        await self._audit(
            "archive",
            "retention",
            None,
            None,
            {"data_class": data_class, "period": period, "rows": n, "sha256": sha, "manifest_id": mid},
        )
        await self._emit(
            "retention.archived",
            {"data_class": data_class, "period": period, "rows": n, "manifest_id": mid},
            "institution",
            self.inst,
        )
        await self._notify(
            "retention.archive_done",
            [self.actor_id] if self.actor_id else [],
            {"data_class": data_class, "period": period, "rows": n, "sha256": sha[:16]},
        )
        return {"data_class": data_class, "period": period, "rows": n, "manifest_id": mid, "sha256": sha}

    async def _detach_empty(self, parent: str, lo: date, hi: date) -> list[str]:
        """Detach + drop monthly partitions inside the period that are empty once the tenant's rows left (platform
        role; a partition still holding another tenant's rows stays)."""
        from app.db.session import PlatformSessionLocal

        out: list[str] = []
        try:
            parts = await self.partitions(parent)
            async with PlatformSessionLocal() as pdb:
                for p in parts:
                    m = re.search(r"FROM \('([0-9-]{10})", str(p["bound"] or ""))
                    if m is None or not lo <= date.fromisoformat(m.group(1)) < hi:
                        continue
                    if (await pdb.execute(text(f'SELECT EXISTS (SELECT 1 FROM "{p["name"]}")'))).scalar_one():
                        continue
                    await pdb.execute(text(f'ALTER TABLE {parent} DETACH PARTITION "{p["name"]}"'))
                    await pdb.execute(text(f'DROP TABLE "{p["name"]}"'))
                    out.append(str(p["name"]))
                await pdb.commit()
        except Exception:  # noqa: BLE001 - partition maintenance is best effort; the rows are archived either way
            return out
        return out

    async def restore_now(self, manifest_id: str) -> dict[str, Any]:
        from app.core.files import get_storage

        m = await self.meta("manifest", manifest_id)
        if not m or m.get("kind") != "archive":
            raise not_found("Archive manifest")
        body = await get_storage().get(str(m["storage_key"]))
        if hashlib.sha256(body).hexdigest() != m.get("sha256"):
            raise rule("The archive file does not match its manifest checksum", "ARCHIVE_CHECKSUM")
        table = str(m["table"])
        side = f"{table}_restored"
        from app.db.session import PlatformSessionLocal

        async with PlatformSessionLocal() as pdb:  # DDL needs the schema owner (platform role)
            await pdb.execute(text(f"CREATE TABLE IF NOT EXISTS {side} (LIKE {table} INCLUDING DEFAULTS)"))
            await pdb.execute(text(f"GRANT SELECT, INSERT ON {side} TO universe_app"))
            await pdb.commit()
        reader = csv.reader(io.StringIO(body.decode()))
        cols = next(reader)
        n = 0
        col_sql = ", ".join(f'"{c}"' for c in cols)
        params = ", ".join(f":c{i}" for i in range(len(cols)))
        for row in reader:
            await self.db.execute(
                text(f"INSERT INTO {side} ({col_sql}) VALUES ({params}) ON CONFLICT DO NOTHING"),
                {f"c{i}": (v if v != "" else None) for i, v in enumerate(row)},
            )
            n += 1
        m.update(
            {"status": "restored", "restored_at": now_utc().isoformat(), "restored_rows": n, "restored_table": side}
        )
        await self.put_meta("manifest", manifest_id, m)
        await self._audit("restore", "retention", None, None, {"manifest_id": manifest_id, "rows": n, "table": side})
        await self._emit("retention.restored", {"manifest_id": manifest_id, "rows": n}, "institution", self.inst)
        return {"manifest_id": manifest_id, "rows": n, "table": side}

    async def archive_due(self) -> int:
        """Beat ``retention.archive_monthly``: archive the oldest due month of each class (one per run)."""
        policy = await self.policy()
        done = 0
        for dc, a in ARCHIVE_TARGETS.items():
            keep = int(policy[a["policy"]])
            age = timedelta(days=keep) if a["policy"].endswith("_days") else timedelta(days=365 * keep)
            month = (now_utc() - age).date().replace(day=1) - timedelta(days=1)
            period = f"{month:%Y-%m}"
            if any(
                x.get("period") == period and x.get("data_class") == dc for _, x in await self.meta_list("manifest")
            ):
                continue
            try:
                await self.archive_now(dc, period)
                done += 1
            except APIError:
                continue
        return done

    # ---- manifests --------------------------------------------------------------------------------------------------
    async def manifests(self, data_class: str | None = None) -> list[ArchiveManifestOut]:
        from app.core.files import get_storage

        self.require_read()
        out = []
        for mid, m in await self.meta_list("manifest"):
            if data_class and m.get("data_class") != data_class:
                continue
            key = m.get("storage_key")
            out.append(
                ArchiveManifestOut(
                    id=mid,
                    kind=m.get("kind") or "purge",
                    data_class=m.get("data_class") or "",
                    period=m.get("period"),
                    rows=int(m.get("rows") or 0),
                    storage_key=key,
                    file_url=get_storage().signed_url(str(key), 3600) if key else None,
                    sha256=m.get("sha256"),
                    status=m.get("status") or "done",
                    created_at=datetime.fromisoformat(m["created_at"]),
                    created_by=_uuid(m.get("created_by")),
                    details={
                        k: v
                        for k, v in m.items()
                        if k
                        in (
                            "cutoff",
                            "deleted",
                            "detached",
                            "held_users",
                            "metadata_deleted",
                            "restored_rows",
                            "restored_table",
                        )
                    },
                )
            )
        return out

    # ---- DSR erasure ------------------------------------------------------------------------------------------------
    async def erase(self, user_id: uuid.UUID) -> dict[str, Any]:
        """Anonymise PII of a user in non-record tables (academic records are retained per policy)."""
        counts: dict[str, int] = {}
        for name, sql in (
            (
                "login_history",
                "UPDATE login_history SET identifier = 'erased', user_agent = NULL, ip = NULL WHERE institution_id = :i AND user_id = :u",
            ),
            ("notifications", "UPDATE notifications SET body = NULL WHERE institution_id = :i AND user_id = :u"),
            (
                "message_logs",
                "UPDATE message_logs SET recipient = 'erased', subject = NULL, body_preview = NULL WHERE institution_id = :i AND user_id = :u",
            ),
            (
                "user_sessions",
                "UPDATE user_sessions SET ip = NULL, user_agent = NULL WHERE institution_id = :i AND user_id = :u",
            ),
        ):
            res: Any = await self.db.execute(text(sql), {"i": self.inst, "u": user_id})
            counts[name] = int(res.rowcount or 0)
        mid = await self._manifest(
            "erase",
            "user",
            sum(counts.values()),
            user_id=str(user_id),
            counts=counts,
            note="Academic records are retained per the retention policy",
        )
        await self._audit("erase", "user", user_id, None, {"counts": counts, "manifest_id": mid})
        return {"user_id": str(user_id), "counts": counts, "manifest_id": mid}


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


__all__ = ["UTC", "RetentionService"]
