"""Cross-framework data-consistency checks — Prompts/32 §32.6 ``consistency_service`` (job
``accreditation.consistency_check``; also after every compute).

Checks for a period: the student headcount reported for NAAC / NIRF / AISHE is the same value (one
``students.enrolment_by_category`` row; an override that differs from the live enrolment count fails), faculty counts
vs HR active teaching staff (``faculty.fsr`` denominator), placed ≤ eligible (``placement.placed_pct`` ≤ 100),
PhD awarded vs Phase 18 PhD awards, expenditure totals vs Phase 23 expense records, programme counts vs affiliation
approvals. Results are stored in ``consistency:<period>``; failures alert IQAC (``accreditation.consistency_alert``)
with fix links."""

from decimal import Decimal
from typing import Any

from sqlalchemy import select, text

from app.core.metrics import MetricContext, normalise_period
from app.models.accreditation import MetricValue
from app.schemas.accreditation import ConsistencyCheck, ConsistencyCheckOut
from app.services.accreditation.common import AccreditationBase, forbidden, now_utc


class ConsistencyService(AccreditationBase):
    async def _value(self, key: str, label: str) -> MetricValue | None:
        return (
            await self.db.execute(
                select(MetricValue).where(
                    MetricValue.institution_id == self.inst,
                    MetricValue.metric_key == key,
                    MetricValue.period_label == label,
                    MetricValue.college_id.is_(None),
                    MetricValue.program_id.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def _scalar(self, sql: str, params: dict[str, Any]) -> Any:
        return (await self.db.execute(text(sql), {"inst": self.inst, **params})).scalar()

    async def run(self, period: str, *, notify: bool = False) -> ConsistencyCheckOut:
        p = normalise_period(period)
        label = p.label
        checks: list[ConsistencyCheck] = []
        from app.services.accreditation.metrics.hr import active_students, teachers

        ctx = MetricContext(self.db, self.inst, p)
        # 1. headcount: one enrolment total for NAAC 2.1.1 / NIRF TLR.SS / AISHE C, equal to the live count
        enrol = await self._value("students.enrolment_by_category", label)
        live = await active_students(ctx)
        if enrol is None or enrol.value is None:
            checks.append(ConsistencyCheck(name="student_headcount", status="skip", details={"reason": "not computed"}))
        else:
            ok = int(enrol.value) == live
            checks.append(
                ConsistencyCheck(
                    name="student_headcount",
                    status="pass" if ok else "fail",
                    details={
                        "reported": int(enrol.value),
                        "live": live,
                        "source": enrol.source,
                        "frameworks": ["NAAC_2024", "NIRF", "AISHE"],
                    },
                    fix_link=None if ok else f"/iqac/metrics?key=students.enrolment_by_category&period={label}",
                )
            )
        # 2. faculty count vs HR
        fsr = await self._value("faculty.fsr", label)
        hr = await teachers(ctx)
        if fsr is None or fsr.denominator is None:
            checks.append(ConsistencyCheck(name="faculty_count", status="skip", details={"reason": "not computed"}))
        else:
            ok = int(fsr.denominator) == hr
            checks.append(
                ConsistencyCheck(
                    name="faculty_count",
                    status="pass" if ok else "fail",
                    details={"reported": int(fsr.denominator), "hr_active_teaching": hr},
                    fix_link=None if ok else f"/iqac/metrics?key=faculty.fsr&period={label}",
                )
            )
        # 3. placed ≤ eligible
        pl = await self._value("placement.placed_pct", label)
        if pl is None or pl.value is None:
            checks.append(
                ConsistencyCheck(name="placed_le_eligible", status="skip", details={"reason": "not published"})
            )
        else:
            ok = Decimal(pl.value) <= 100
            checks.append(
                ConsistencyCheck(
                    name="placed_le_eligible",
                    status="pass" if ok else "fail",
                    details={"placed_pct": str(pl.value)},
                    fix_link=None if ok else "/placement/stats",
                )
            )
        # 4. PhD awarded vs Phase 18 awards
        phd = await self._value("research.phd_awarded", label)
        awards = int(
            await self._scalar(
                "SELECT count(*) FROM degrees_awarded WHERE institution_id = :inst AND award_type = 'phd' "
                "AND created_at::date BETWEEN :s AND :e",
                {"s": p.start, "e": p.end},
            )
            or 0
        )
        if phd is None or phd.value is None:
            checks.append(
                ConsistencyCheck(
                    name="phd_awarded", status="skip", details={"reason": "not published", "phase18_awards": awards}
                )
            )
        else:
            ok = awards == 0 or int(phd.value) == awards
            checks.append(
                ConsistencyCheck(
                    name="phd_awarded",
                    status="pass" if ok else "fail",
                    details={"reported": int(phd.value), "phase18_awards": awards},
                    fix_link=None if ok else "/phd/awards",
                )
            )
        # 5. expenditure vs Phase 23 statements
        opex = await self._value("finance.opex", label)
        books = int(
            await self._scalar(
                "SELECT COALESCE(sum(x.amount_paise), 0) FROM expense_records x JOIN ledger_accounts la ON la.id = x.ledger_account_id "
                "WHERE x.institution_id = :inst AND x.status IN ('approved', 'paid') AND x.spent_on BETWEEN :s AND :e "
                "AND lower(la.name) NOT LIKE '%salar%'",
                {"s": p.start, "e": p.end},
            )
            or 0
        )
        if opex is None or opex.value is None:
            checks.append(
                ConsistencyCheck(name="expenditure_totals", status="skip", details={"reason": "not computed"})
            )
        else:
            ok = int(opex.value) == books
            checks.append(
                ConsistencyCheck(
                    name="expenditure_totals",
                    status="pass" if ok else "fail",
                    details={"reported_paise": int(opex.value), "ledger_paise": books, "source": opex.source},
                    fix_link=None if ok else "/accounting/statements",
                )
            )
        # 6. programmes vs affiliation approvals (university tenants)
        progs = int(await self._scalar("SELECT count(*) FROM programs WHERE institution_id = :inst", {}) or 0)
        approved = int(
            await self._scalar(
                "SELECT count(DISTINCT program_id) FROM affiliation_program_approvals WHERE institution_id = :inst", {}
            )
            or 0
        )
        if not approved:
            checks.append(
                ConsistencyCheck(
                    name="programme_approvals",
                    status="skip",
                    details={"programmes": progs, "reason": "no affiliation approvals"},
                )
            )
        else:
            ok = approved <= progs
            checks.append(
                ConsistencyCheck(
                    name="programme_approvals",
                    status="pass" if ok else "fail",
                    details={"programmes": progs, "approved": approved},
                    fix_link=None if ok else "/affiliation/approvals",
                )
            )
        out = ConsistencyCheckOut(period_label=label, checked_at=now_utc().isoformat(), checks=checks)
        await self.put_meta("consistency", label, out.model_dump(mode="json"))
        failed = [c.name for c in checks if c.status == "fail"]
        if failed and notify:
            await self._emit(
                "accreditation.consistency_alert", {"period_label": label, "failed": failed}, "metric_values", None
            )
            await self._notify(
                "accreditation.consistency_alert",
                await self.iqac_users(),
                {"period": label, "checks": ", ".join(failed)},
            )
        return out

    async def latest(self, period: str) -> ConsistencyCheckOut:
        if not (self.iqac() or self.reader_all()):
            raise forbidden("accreditation:manage required")
        label = normalise_period(period).label
        m = await self.meta("consistency", label)
        return ConsistencyCheckOut(**m) if m else ConsistencyCheckOut(period_label=label)
