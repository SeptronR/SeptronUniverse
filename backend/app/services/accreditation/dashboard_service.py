"""IQAC dashboard — Prompts/32 §32.6 ``dashboard_service``: cycle progress, criteria completion, verified metrics %,
pending overrides, evidence coverage per criterion, submissions due, open audits, consistency alerts and the NAAC score
simulation (each criterion's ``max_score`` weighted by the benchmark band of its normalised metric value) with the top
improvement gaps. ``college_admin`` sees their college's cycles / values only; the auditor reads."""

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.metrics import normalise_period
from app.enums.accreditation import BENCHMARK_BANDS
from app.models.accreditation import (
    AuditRegister,
    ComplianceSubmission,
    EvidenceDocument,
    FrameworkCriterion,
    MetricValue,
)
from app.schemas.accreditation import IqacDashboardOut
from app.services.accreditation.common import AccreditationBase, forbidden


def band_score(norm: float) -> float:
    for floor, share in BENCHMARK_BANDS:
        if norm >= floor:
            return share
    return 0.0


def normalise(unit: str | None, value: Decimal) -> float:
    """Metric value → 0..1 for the simulation (pct / 100, ratio FSR inverted around 1:20, levels / 3, else capped)."""
    v = float(value)
    if unit == "pct":
        return max(0.0, min(1.0, v / 100))
    if unit == "level":
        return max(0.0, min(1.0, v / 3))
    if unit == "ratio":
        return max(0.0, min(1.0, 20 / v)) if v > 0 else 0.0
    if unit == "score":
        return max(0.0, min(1.0, v / 10 if v <= 10 else v / 100))
    return 1.0 if v > 0 else 0.0


class DashboardService(AccreditationBase):
    async def dashboard(self, period: str | None = None) -> IqacDashboardOut:
        if not (self.iqac() or self.reader_all() or self.college_ids()):
            raise forbidden("accreditation:manage or view_all required")
        today = await self.today()
        label = (
            normalise_period(period).label
            if period
            else f"{today.year if today.month >= 6 else today.year - 1}-{str((today.year if today.month >= 6 else today.year - 1) + 1)[-2:]}"
        )
        from app.services.accreditation.cycle_service import CycleService

        cycles = await CycleService(self.db, self.principal, self.request, self.inst).query()
        mv = select(MetricValue).where(MetricValue.institution_id == self.inst, MetricValue.period_label == label)
        colleges = self.college_ids()
        if colleges:
            mv = mv.where(MetricValue.college_id.in_(colleges))
        values = list((await self.db.execute(mv)).scalars().all())
        verified = sum(1 for v in values if v.verified_at is not None)
        pending = sum(1 for m in (await self.metas("override")).values() if m.get("pending"))
        ev_counts: dict[str, int] = {}
        for code, n in (
            await self.db.execute(
                select(FrameworkCriterion.code, func.count())
                .join(EvidenceDocument, EvidenceDocument.framework_criterion_id == FrameworkCriterion.id)
                .where(EvidenceDocument.institution_id == self.inst)
                .group_by(FrameworkCriterion.code)
            )
        ).all():
            top = str(code).split(".")[0]
            ev_counts[top] = ev_counts.get(top, 0) + int(n)
        subs = [
            {"id": str(s.id), "type": s.submission_type, "period": s.period_label, "status": s.status}
            for s in (
                await self.db.execute(
                    select(ComplianceSubmission).where(
                        ComplianceSubmission.institution_id == self.inst,
                        ComplianceSubmission.status.in_(("draft", "generated")),
                    )
                )
            ).scalars()
        ]
        audits_open = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(AuditRegister)
                    .where(AuditRegister.institution_id == self.inst, AuditRegister.status != "closed")
                )
            ).scalar_one()
        )
        cons = await self.meta("consistency", label)
        alerts = sum(1 for c in cons.get("checks") or [] if c.get("status") == "fail")
        sim, gaps = await self.simulate(label, values)
        completion: dict[str, float] = {c.name: c.completion_pct for c in cycles}
        return IqacDashboardOut(
            period_label=label,
            cycles=cycles,
            criteria_completion=completion,
            metrics_total=len(values),
            metrics_verified_pct=round(100 * verified / len(values), 1) if values else 0.0,
            overrides_pending=pending,
            evidence_counts=ev_counts,
            submissions_due=subs,
            audits_open=audits_open,
            consistency_alerts=alerts,
            score_simulation=sim,
            top_gaps=gaps,
        )

    async def simulate(self, label: str, values: list[MetricValue]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        try:
            fw = await self.framework("NAAC_2024")
        except Exception:  # noqa: BLE001 - framework rows missing on a bare database
            return {}, []
        defs = await self.definitions_by_key()
        by_key = {
            v.metric_key: v for v in values if v.college_id is None and v.program_id is None and v.value is not None
        }
        crits = [
            c for c in await self.criteria(fw.id) if c.metric_key and c.max_score is not None and c.code.count(".") == 2
        ]
        per: dict[str, dict[str, float]] = {}
        gaps: list[dict[str, Any]] = []
        for c in crits:
            top = c.code.split(".")[0]
            slot = per.setdefault(top, {"max": 0.0, "earned": 0.0})
            mx = float(c.max_score or 0)
            slot["max"] += mx
            v = by_key.get(str(c.metric_key))
            earned = (
                mx * band_score(normalise(defs[c.metric_key].unit if c.metric_key in defs else None, v.value))
                if v and v.value is not None
                else 0.0
            )
            slot["earned"] += earned
            gaps.append(
                {
                    "code": c.code,
                    "title": c.title,
                    "metric_key": c.metric_key,
                    "max_score": mx,
                    "earned": round(earned, 2),
                    "gap": round(mx - earned, 2),
                }
            )
        total_max = sum(s["max"] for s in per.values())
        total = sum(s["earned"] for s in per.values())
        cgpa = round(4 * total / total_max, 2) if total_max else 0.0
        grade = next(
            (
                g
                for floor, g in (
                    (3.51, "A++"),
                    (3.26, "A+"),
                    (3.01, "A"),
                    (2.76, "B++"),
                    (2.51, "B+"),
                    (2.01, "B"),
                    (1.51, "C"),
                )
                if cgpa >= floor
            ),
            "D",
        )
        sim = {
            "by_criterion": {
                k: {"max": round(v["max"], 2), "earned": round(v["earned"], 2)} for k, v in sorted(per.items())
            },
            "quantitative_max": round(total_max, 2),
            "quantitative_earned": round(total, 2),
            "cgpa_estimate": cgpa,
            "grade_estimate": grade,
        }
        return sim, sorted(gaps, key=lambda g: -g["gap"])[:10]
