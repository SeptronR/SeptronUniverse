"""Compliance submissions — Prompts/32 §32.6 ``submission_service`` ({accreditation.aishe|nirf|aicte_ugc}).

Per type / period: generate the payload from ``metric_values`` (job) → review (diff vs the previous period's row) →
mark submitted with the ack ref and file. The payload JSON is the source of truth for what was reported: immutable
after ``submitted`` (409); a correction is a new row (``submission:<id>.supersedes``). NIRF payloads carry the Phase 28
placement rows (``nirf_rows``); NSP returns use the Phase 12 scholarship metrics. Officers without the full payload
(accountant) see the finance section only. Weekly due-date reminders to IQAC."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from app.core.metrics import normalise_period
from app.enums.accreditation import SUBMISSION_FRAMEWORK
from app.models.accreditation import ComplianceSubmission, MetricValue
from app.schemas.accreditation import SubmissionDiff, SubmissionIn, SubmissionMarkSubmitted, SubmissionOut
from app.services.accreditation.common import AccreditationBase, forbidden, not_found, now_utc, rule

# (month, day) of the due date in the year after the period starts
DUE: dict[str, tuple[int, int]] = {
    "aishe": (1, 31),
    "nirf_data": (1, 15),
    "aqar": (12, 31),
    "aicte_approval": (3, 31),
    "ugc_annual": (9, 30),
    "nsp_return": (11, 30),
}
FINANCE_PREFIXES = (
    "finance.",
    "library.spend",
    "research.grants_amount",
    "research.consultancy_revenue",
    "nirf.fru",
    "nirf.fppp",
)


class SubmissionService(AccreditationBase):
    def require_reader(self) -> None:
        if not (self.can(self.module, "view") or self.can(self.module, "view_all") or self.can(self.module, "manage")):
            raise forbidden("accreditation:view required")

    def full_payload(self) -> bool:
        return self.reader_all() or self.iqac("submit")

    def finance_only(self) -> bool:
        return not self.full_payload() and "accountant" in self.roles()

    async def _feature(self, submission_type: str) -> None:
        _, key = SUBMISSION_FRAMEWORK[submission_type]
        await self.require_feature(key)

    def _payload_for_viewer(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if payload is None or self.full_payload():
            return payload
        if self.finance_only():
            metrics = {k: v for k, v in (payload.get("metrics") or {}).items() if k.startswith(FINANCE_PREFIXES)}
            return {"section": "finance", "metrics": metrics}
        return None

    async def out(self, s: ComplianceSubmission) -> SubmissionOut:
        m = await self.meta("submission", s.id)
        return SubmissionOut(
            id=s.id,
            framework_id=s.framework_id,
            period_label=s.period_label,
            submission_type=s.submission_type,
            payload=self._payload_for_viewer(s.payload),
            file_url=s.file_url if self.full_payload() else None,
            status=s.status,
            submitted_on=s.submitted_on,
            ack_ref=s.ack_ref,
            supersedes_id=m.get("supersedes"),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )

    async def query(self, submission_type: str | None = None, period: str | None = None) -> list[SubmissionOut]:
        self.require_reader()
        if not (self.full_payload() or self.finance_only() or self.officer_modules()):
            raise forbidden("Submissions are visible to IQAC, principal-level readers and module officers")
        stmt = select(ComplianceSubmission).where(ComplianceSubmission.institution_id == self.inst)
        if submission_type:
            stmt = stmt.where(ComplianceSubmission.submission_type == submission_type)
        if period:
            stmt = stmt.where(ComplianceSubmission.period_label == period)
        rows = (await self.db.execute(stmt.order_by(ComplianceSubmission.created_at.desc()))).scalars().all()
        return [await self.out(s) for s in rows]

    async def row(self, sid: uuid.UUID, *, lock: bool = False) -> ComplianceSubmission:
        stmt = select(ComplianceSubmission).where(
            ComplianceSubmission.id == sid, ComplianceSubmission.institution_id == self.inst
        )
        if lock:
            stmt = stmt.with_for_update()
        s = (await self.db.execute(stmt)).scalar_one_or_none()
        if s is None:
            raise not_found("Submission")
        return s

    async def get(self, sid: uuid.UUID) -> SubmissionOut:
        self.require_reader()
        s = await self.row(sid)
        if not (self.full_payload() or self.finance_only() or self.officer_modules()):
            raise forbidden("accreditation:submit or principal-level read required")
        return await self.out(s)

    async def create(self, body: SubmissionIn) -> SubmissionOut:
        self.require_iqac("submit")
        await self._feature(body.submission_type.value)
        try:
            label = normalise_period(body.period_label).label
        except ValueError as exc:
            raise rule(str(exc), "INVALID_PERIOD", 422) from exc
        prior = (
            await self.db.execute(
                select(ComplianceSubmission)
                .where(
                    ComplianceSubmission.institution_id == self.inst,
                    ComplianceSubmission.submission_type == body.submission_type.value,
                    ComplianceSubmission.period_label == label,
                )
                .order_by(ComplianceSubmission.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if prior is not None and prior.status in ("draft", "generated"):
            raise rule(
                "An open submission exists for this type and period", "DUPLICATE_SUBMISSION", 409, id=str(prior.id)
            )
        fw_id = body.framework_id or (await self.framework(SUBMISSION_FRAMEWORK[body.submission_type.value][0])).id
        s = ComplianceSubmission(
            institution_id=self.inst, framework_id=fw_id, period_label=label, submission_type=body.submission_type.value
        )
        self.db.add(s)
        await self.db.flush()
        if prior is not None:
            await self.put_meta("submission", s.id, {"supersedes": str(prior.id)})
        return await self.out(s)

    async def build_payload(self, s: ComplianceSubmission) -> dict[str, Any]:
        fw_code = SUBMISSION_FRAMEWORK[s.submission_type][0]
        fw = await self.framework(fw_code)
        crits = await self.criteria(fw.id)
        keys = {c.metric_key for c in crits if c.metric_key}
        if s.submission_type == "nsp_return":
            keys = {"scholarships.beneficiaries_pct", "nirf.escs", "students.enrolment_by_category"}
        rows = (
            await self.db.execute(
                select(MetricValue).where(
                    MetricValue.institution_id == self.inst,
                    MetricValue.period_label == s.period_label,
                    MetricValue.metric_key.in_(keys or {"-"}),
                    MetricValue.college_id.is_(None),
                    MetricValue.program_id.is_(None),
                )
            )
        ).scalars()
        metrics = {
            r.metric_key: {
                "value": str(r.value) if r.value is not None else None,
                "numerator": str(r.numerator) if r.numerator is not None else None,
                "denominator": str(r.denominator) if r.denominator is not None else None,
                "breakdown": {k: v for k, v in (r.breakdown or {}).items() if not k.startswith("_")},
                "source": r.source,
                "verified": r.verified_at is not None,
            }
            for r in rows
        }
        sections = {
            c.code: {
                "title": c.title,
                "metric_key": c.metric_key,
                "value": (metrics.get(c.metric_key or "") or {}).get("value"),
            }
            for c in crits
        }
        payload: dict[str, Any] = {
            "type": s.submission_type,
            "framework": fw_code,
            "period_label": s.period_label,
            "generated_at": now_utc().isoformat(),
            "metrics": metrics,
            "sections": sections,
            "missing": sorted(k for k in keys if k not in metrics),
        }
        if s.submission_type == "nirf_data" and await self.feature("placement.core"):
            try:
                from app.services.placement.stats_service import StatsService as PlcStats

                st = await PlcStats(self.db, self.principal, self.request, self.inst).stats(None, None, None)
                payload["placement_rows"] = st.nirf_rows
            except Exception as exc:  # noqa: BLE001 - placement data optional for the payload
                payload["placement_rows_error"] = str(exc)[:200]
        return payload

    async def generate(self, sid: uuid.UUID, job_id: uuid.UUID | None = None) -> SubmissionOut:
        self.require_iqac("submit")
        s = await self.row(sid, lock=True)
        await self._feature(s.submission_type)
        if s.status in ("submitted", "acknowledged"):
            raise rule("Submitted payloads are immutable — create a correction", "IMMUTABLE")
        s.payload = await self.build_payload(s)
        s.status, s.job_id = "generated", job_id
        await self.db.flush()
        await self._emit(
            "accreditation.submission_generated",
            {"submission_id": str(s.id), "type": s.submission_type},
            "compliance_submission",
            s.id,
        )
        return await self.out(s)

    async def diff(self, sid: uuid.UUID, vs: uuid.UUID | None = None) -> SubmissionDiff:
        self.require_reader()
        s = await self.row(sid)
        other: ComplianceSubmission | None
        if vs:
            other = await self.row(vs)
        else:
            other = (
                await self.db.execute(
                    select(ComplianceSubmission)
                    .where(
                        ComplianceSubmission.institution_id == self.inst,
                        ComplianceSubmission.submission_type == s.submission_type,
                        ComplianceSubmission.period_label < s.period_label,
                        ComplianceSubmission.payload.is_not(None),
                    )
                    .order_by(ComplianceSubmission.period_label.desc(), ComplianceSubmission.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        cur = (self._payload_for_viewer(s.payload) or {}).get("metrics") or {}
        prev = (self._payload_for_viewer(other.payload if other else None) or {}).get("metrics") or {}
        rows = []
        for k in sorted(set(cur) | set(prev)):
            a, b = (prev.get(k) or {}).get("value"), (cur.get(k) or {}).get("value")
            delta = None
            try:
                delta = str(round(float(b) - float(a), 4)) if a is not None and b is not None else None
            except ValueError:
                delta = None
            rows.append({"metric": k, "previous": a, "current": b, "delta": delta})
        return SubmissionDiff(
            id=s.id, vs_id=other.id if other else None, vs_period=other.period_label if other else None, rows=rows
        )

    async def mark_submitted(self, sid: uuid.UUID, body: SubmissionMarkSubmitted) -> SubmissionOut:
        self.require_iqac("submit")
        s = await self.row(sid, lock=True)
        if s.status in ("submitted", "acknowledged") and not (body.acknowledged and s.status == "submitted"):
            raise rule("The submission is already submitted — payload immutable", "IMMUTABLE")
        if s.payload is None:
            raise rule("Generate the payload before marking it submitted", "NOT_GENERATED")
        s.submitted_on, s.ack_ref = body.submitted_on, body.ack_ref or s.ack_ref
        s.file_url = body.file_url or s.file_url
        s.status = "acknowledged" if body.acknowledged and (body.ack_ref or s.ack_ref) else "submitted"
        await self.db.flush()
        await self._audit("submission_" + s.status, "compliance_submission", s.id, None, {"ack_ref": s.ack_ref})
        await self._emit(
            f"accreditation.submission_{s.status}",
            {"submission_id": str(s.id), "type": s.submission_type, "ack_ref": s.ack_ref},
            "compliance_submission",
            s.id,
        )
        return await self.out(s)

    async def due_reminders(self) -> int:
        today = await self.today()
        n = 0
        rows = (
            await self.db.execute(
                select(ComplianceSubmission).where(
                    ComplianceSubmission.institution_id == self.inst,
                    ComplianceSubmission.status.in_(("draft", "generated")),
                )
            )
        ).scalars()
        users = await self.iqac_users()
        for s in rows:
            try:
                start = normalise_period(s.period_label).start.year
            except ValueError:
                continue
            mm, dd = DUE.get(s.submission_type, (12, 31))
            due = date(start + 1, mm, dd)
            if 0 <= (due - today).days <= 30:
                await self._notify(
                    "accreditation.submission_due",
                    users,
                    {"type": s.submission_type, "period": s.period_label, "due_on": due.isoformat()},
                )
                n += 1
        return n
