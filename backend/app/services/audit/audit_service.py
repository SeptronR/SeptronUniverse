"""Audit explorer — Prompts/37 §37.6 ``audit_service`` steps 1 and 3 ({core.audit_logs}).

1. ``explore(query)``: mandatory date bounds (default 30 days, ≤ 366), filters module / action / user / record / free text
   (record label or summary — the label is matched in SQL on the common label keys of ``new_values``, the rendered
   summary on the page), impersonation filter, ScopeTabs Mine | Department | College | All narrowed to the caller
   (:meth:`AuditBase.scope_predicate`); always partition-pruned on ``occurred_at``. Diffs are masked by the record
   module's ``view_pii``.
2. ``timeline(record_type, record_id)`` merges the record's audit rows, its domain events (``aggregate_id``) and the
   workflow steps of instances on the record, oldest first.
3. ``who_viewed`` lists ``view`` / ``view_pii`` / ``download`` rows of a confidential record (requires ``view_all``
   reach over the record and ``view_pii`` on its module — an HOD asking about a health record gets 403).
4. ``export`` enqueues the registered Phase 36 report ``audit.explorer`` (``report.run``; masked unless ``view_pii``;
   up to 5 years per export) and audits ``audit_logs:export``; the access shows in ``/reports/access-log`` too.
5. ``summary`` — counts per module / action (IQAC and dashboards; no rows).
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.core.jobs import enqueue
from app.enums.audit import CONFIDENTIAL_RECORD_TYPES, RECORD_PII_MODULE, VIEW_ACTIONS
from app.models.audit import AuditLog
from app.models.platform import DomainEvent, WorkflowInstance, WorkflowStep
from app.schemas.audit import (
    AuditDetailOut,
    AuditListOut,
    AuditRowOut,
    AuditSummaryOut,
    AuditUser,
    DiffEntry,
    JobQueuedOut,
    RecordTimelineOut,
    WhoViewedOut,
)
from app.services.audit.common import AuditBase, forbidden, mask_ip24, not_found, now_utc

LABEL_KEYS = ("label", "number", "code", "name", "registration_number", "title", "key", "receipt_number")
SORTS = {"-occurred_at": AuditLog.occurred_at.desc(), "occurred_at": AuditLog.occurred_at.asc()}


class AuditService(AuditBase):
    # ---- explorer ---------------------------------------------------------------------------------------------------
    def require_reader(self) -> None:
        if not (self.can("audit_logs", "view") or self.views_all()):
            raise forbidden("audit_logs:view required")

    def filtered(self, q: dict[str, Any], lo: datetime, hi: datetime) -> Any:
        stmt = select(AuditLog).where(
            AuditLog.institution_id == self.inst, AuditLog.occurred_at >= lo, AuditLog.occurred_at <= hi
        )
        if q.get("module"):
            stmt = stmt.where(AuditLog.module == q["module"])
        if q.get("action"):
            stmt = stmt.where(AuditLog.action == q["action"])
        if q.get("user_id"):
            stmt = stmt.where(AuditLog.user_id == q["user_id"])
        if q.get("record_type"):
            stmt = stmt.where(AuditLog.record_type == q["record_type"])
        if q.get("record_id"):
            stmt = stmt.where(AuditLog.record_id == q["record_id"])
        if q.get("impersonator_only"):
            stmt = stmt.where(AuditLog.impersonator_id.is_not(None))
        if q.get("request_id"):
            stmt = stmt.where(AuditLog.request_id == q["request_id"])
        if q.get("q"):
            like = f"%{str(q['q'])[:100]}%"
            stmt = stmt.where(
                or_(
                    AuditLog.record_type.ilike(like),
                    AuditLog.action.ilike(like),
                    *(AuditLog.new_values[k].astext.ilike(like) for k in LABEL_KEYS),
                )
            )
        return stmt

    async def rows_out(self, rows: list[AuditLog]) -> list[AuditRowOut]:
        names = await self.user_refs([r.user_id for r in rows] + [r.impersonator_id for r in rows])
        return [
            AuditRowOut(
                id=r.id,
                occurred_at=r.occurred_at,
                module=r.module,
                action=r.action,
                record_type=r.record_type,
                record_id=r.record_id,
                record_label=self.record_label(r),
                user=AuditUser(id=r.user_id, name=names.get(r.user_id)) if r.user_id else None,
                impersonator=AuditUser(id=r.impersonator_id, name=names.get(r.impersonator_id))
                if r.impersonator_id
                else None,
                ip_masked=mask_ip24(r.ip),
                request_id=r.request_id,
                summary=self.summary_line(r),
                has_diff=bool(r.old_values or r.new_values),
            )
            for r in rows
        ]

    async def explore(
        self, q: dict[str, Any], scope: str | None, page: int = 1, page_size: int = 50, sort: str = "-occurred_at"
    ) -> tuple[AuditListOut, dict[str, Any]]:
        self.require_reader()
        lo, hi = self.bounds(q.get("from"), q.get("to"))
        pred, level = await self.scope_predicate(scope)
        stmt = self.filtered(q, lo, hi).where(pred)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        page_size = max(1, min(page_size, 200))
        rows = list(
            (
                await self.db.execute(
                    stmt.order_by(SORTS.get(sort, SORTS["-occurred_at"]), AuditLog.id)
                    .offset((max(page, 1) - 1) * page_size)
                    .limit(page_size)
                )
            ).scalars()
        )
        out = AuditListOut(
            items=await self.rows_out(rows), total=total, page=page, page_size=page_size, date_from=lo, date_to=hi
        )
        return out, self.scope_meta(level)

    async def me(self, q: dict[str, Any], page: int = 1, page_size: int = 50) -> AuditListOut:
        out, _ = await self.explore(q, "self", page, page_size)
        return out

    async def row(self, audit_id: uuid.UUID) -> AuditLog:
        r = (
            (
                await self.db.execute(
                    select(AuditLog).where(AuditLog.id == audit_id, AuditLog.institution_id == self.inst)
                )
            )
            .scalars()
            .first()
        )
        if r is None:
            raise not_found("Audit row")
        await self.require_record_visible(r)
        return r

    async def detail(self, audit_id: uuid.UUID) -> AuditDetailOut:
        self.require_reader()
        r = await self.row(audit_id)
        base = (await self.rows_out([r]))[0]
        old, m1 = self.mask_values(r, r.old_values)
        new, m2 = self.mask_values(r, r.new_values)
        masked = sorted({*m1, *m2})
        diff: list[DiffEntry] = []
        o, n = old or {}, new or {}
        for k in sorted({*o, *n}):
            if o.get(k) != n.get(k):
                diff.append(DiffEntry(field=k, old=o.get(k), new=n.get(k), masked=k in masked))
        related: list[AuditRowOut] = []
        if r.request_id:
            pred, _ = await self.scope_predicate(None)
            rel = (
                await self.db.execute(
                    self.filtered(
                        {"request_id": r.request_id},
                        r.occurred_at - timedelta(hours=1),
                        r.occurred_at + timedelta(hours=1),
                    )
                    .where(pred, AuditLog.id != r.id)
                    .order_by(AuditLog.occurred_at)
                    .limit(20)
                )
            ).scalars()
            related = await self.rows_out(list(rel))
        return AuditDetailOut(
            **base.model_dump(),
            old_values=old,
            new_values=new,
            diff=diff,
            masked_fields=masked,
            user_agent=(r.user_agent or "")[:200] or None,
            prev_hash=r.prev_hash,
            hash=r.hash,
            related=related,
        )

    # ---- timeline ---------------------------------------------------------------------------------------------------
    async def record_timeline(
        self, record_type: str, record_id: uuid.UUID, days: int = 3650
    ) -> list[RecordTimelineOut]:
        self.require_reader()
        hi = now_utc()
        lo = hi - timedelta(days=days)
        pred, _ = await self.scope_predicate(None)
        rows = list(
            (
                await self.db.execute(
                    self.filtered({"record_type": record_type, "record_id": record_id}, lo, hi)
                    .where(pred)
                    .order_by(AuditLog.occurred_at)
                    .limit(500)
                )
            ).scalars()
        )
        if not rows and not self.views_all():
            raise not_found("Record")
        events = list(
            (
                await self.db.execute(
                    select(DomainEvent)
                    .where(
                        DomainEvent.institution_id == self.inst,
                        DomainEvent.aggregate_id == record_id,
                        DomainEvent.created_at >= lo,
                    )
                    .order_by(DomainEvent.created_at)
                    .limit(300)
                )
            ).scalars()
        )
        steps = (
            await self.db.execute(
                select(WorkflowStep, WorkflowInstance)
                .join(WorkflowInstance, WorkflowInstance.id == WorkflowStep.instance_id)
                .where(WorkflowInstance.institution_id == self.inst, WorkflowInstance.entity_id == record_id)
                .order_by(WorkflowStep.created_at)
                .limit(200)
            )
        ).all()
        names = await self.user_refs(
            [r.user_id for r in rows] + [e.actor_user_id for e in events] + [s.acted_by for s, _ in steps]
        )

        def who(uid: uuid.UUID | None) -> AuditUser | None:
            return AuditUser(id=uid, name=names.get(uid)) if uid else None

        out = [
            RecordTimelineOut(
                at=r.occurred_at,
                source="audit",
                action=f"{r.module}:{r.action}",
                actor=who(r.user_id),
                summary=self.summary_line(r),
                audit_id=r.id,
            )
            for r in rows
        ]
        out += [
            RecordTimelineOut(
                at=e.created_at,
                source="event",
                action=e.event_type,
                actor=who(e.actor_user_id),
                details={"status": e.status},
            )
            for e in events
        ]
        out += [
            RecordTimelineOut(
                at=s.acted_at or s.created_at,
                source="workflow",
                action=f"step {s.step_order}: {s.status}",
                actor=who(s.acted_by),
                summary=wi.title,
                details={"instance_id": str(wi.id), "role": s.approver_role_slug, "comment": s.comment},
            )
            for s, wi in steps
        ]
        return sorted(out, key=lambda e: e.at)

    # ---- who viewed -------------------------------------------------------------------------------------------------
    async def who_viewed(
        self, record_type: str, record_id: uuid.UUID, date_from: datetime | None, date_to: datetime | None
    ) -> list[WhoViewedOut]:
        self.require_reader()
        if not self.views_all():
            raise forbidden("audit_logs:view_all required")
        module = RECORD_PII_MODULE.get(record_type, record_type)
        if record_type not in CONFIDENTIAL_RECORD_TYPES and not self.is_inst_admin():
            raise forbidden(f"{record_type} is not a confidential record type")
        if not (
            self.can(module, "view_pii")
            or self.is_inst_admin()
            or self.institution_wide()
            and self.can("audit_logs", "verify_chain")
        ):
            raise forbidden(f"{module}:view_pii required to see who viewed this record")
        lo, hi = self.bounds(date_from, date_to)
        pred, _ = await self.scope_predicate(None)
        rows = list(
            (
                await self.db.execute(
                    self.filtered({"record_type": record_type, "record_id": record_id}, lo, hi)
                    .where(pred, AuditLog.action.in_(VIEW_ACTIONS))
                    .order_by(AuditLog.occurred_at.desc())
                    .limit(500)
                )
            ).scalars()
        )
        names = await self.user_refs([r.user_id for r in rows])
        return [
            WhoViewedOut(
                audit_id=r.id,
                user=AuditUser(id=r.user_id, name=names.get(r.user_id)),
                at=r.occurred_at,
                action=r.action,
                fields_unmasked=[str(f) for f in (r.new_values or {}).get("fields") or []],
                ip_masked=mask_ip24(r.ip),
            )
            for r in rows
        ]

    # ---- summary ----------------------------------------------------------------------------------------------------
    async def summary_counts(self, date_from: datetime | None, date_to: datetime | None) -> AuditSummaryOut:
        if not (self.views_all() or self.aggregates_only("audit_logs")):
            raise forbidden("audit_logs:view_all required")
        lo, hi = self.bounds(date_from, date_to)
        base = [AuditLog.institution_id == self.inst, AuditLog.occurred_at >= lo, AuditLog.occurred_at <= hi]
        if not self.sees_decode():
            base.append(AuditLog.action.notin_(("decode", "exams:decode")))
        by_module = (
            await self.db.execute(
                select(AuditLog.module, func.count())
                .where(*base)
                .group_by(AuditLog.module)
                .order_by(func.count().desc())
            )
        ).all()
        by_action = (
            await self.db.execute(
                select(AuditLog.action, func.count())
                .where(*base)
                .group_by(AuditLog.action)
                .order_by(func.count().desc())
                .limit(30)
            )
        ).all()
        imp = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(AuditLog).where(*base, AuditLog.impersonator_id.is_not(None))
                )
            ).scalar_one()
        )
        return AuditSummaryOut(
            date_from=lo,
            date_to=hi,
            total=sum(int(c) for _, c in by_module),
            by_module=[{"module": m, "count": int(c)} for m, c in by_module],
            by_action=[{"action": a, "count": int(c)} for a, c in by_action],
            impersonated=imp,
        )

    # ---- export (job) -----------------------------------------------------------------------------------------------
    async def export(self, query: dict[str, Any], fmt: str) -> JobQueuedOut:
        self.require("audit_logs:export", "audit_logs:manage")
        clean = {
            k: (str(v) if isinstance(v, uuid.UUID | datetime) else v) for k, v in query.items() if v not in (None, "")
        }
        lo, hi = self.bounds(
            self.utc(clean.get("from")), self.utc(clean.get("to")), max_days=5 * 366
        )  # longer than the explorer: exports run as jobs
        clean["from"], clean["to"] = lo.date().isoformat(), hi.date().isoformat()
        job = await enqueue(
            self.db,
            self.principal,
            "report.run",
            {"key": "audit.explorer", "params": clean, "format": fmt, "scope": clean.pop("scope", None)},
            task_name="jobs.report.run",
        )
        await self._audit(
            "export", "audit_logs", job.id, None, {"key": "audit.explorer", "params": clean, "format": fmt}
        )
        await self._emit("audit.exported", {"job_id": str(job.id), "format": fmt}, "background_job", job.id)
        return JobQueuedOut(job_id=job.id, job_type="report.run", report_key="audit.explorer")

    async def export_rows(self, params: dict[str, Any], scope: str | None, limit: int | None) -> list[dict[str, Any]]:
        """Provider of the ``audit.explorer`` report (runs as the requester inside ``report.run``)."""
        to = self.utc(params.get("to"))
        if to is not None and len(str(params.get("to"))) <= 10:
            to = to + timedelta(days=1)  # a date-only bound includes that day
        lo, hi = self.bounds(self.utc(params.get("from")), to, max_days=5 * 366)
        pred, _ = await self.scope_predicate(scope)
        q = {
            k: params.get(k)
            for k in ("module", "action", "user_id", "record_type", "record_id", "q", "impersonator_only")
        }
        stmt = self.filtered(q, lo, hi).where(pred).order_by(AuditLog.occurred_at, AuditLog.id)
        if limit:
            stmt = stmt.limit(limit + 1)
        rows = list((await self.db.execute(stmt)).scalars())
        names = await self.user_refs([r.user_id for r in rows])
        out = []
        for r in rows:
            old, _ = self.mask_values(r, r.old_values)
            new, _ = self.mask_values(r, r.new_values)
            out.append(
                {
                    "occurred_at": r.occurred_at,
                    "module": r.module,
                    "action": r.action,
                    "record_type": r.record_type,
                    "record_id": str(r.record_id) if r.record_id else None,
                    "user": names.get(r.user_id) if r.user_id else None,
                    "impersonated": r.impersonator_id is not None,
                    "summary": self.summary_line(r),
                    "ip": mask_ip24(r.ip),
                    "old_values": old,
                    "new_values": new,
                    "hash": r.hash,
                }
            )
        return out
