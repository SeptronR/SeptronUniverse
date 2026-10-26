"""Half-yearly progress reports — Prompts/31 §31.6 ``progress_service`` ({phd.progress_reports}).

Periods (``YYYY-H1`` / ``YYYY-H2``, every ``phd.rules.progress_report_months``) run from the registration date; each
is due at the end of its half-year. The scholar submits (report + summary) → the guide reviews → the DC rates at the
next meeting (``satisfactory | unsatisfactory``). Two consecutive ``unsatisfactory`` ratings (``unsatisfactory_limit``)
raise the **cancellation review** flag: a ``scholar_requests`` row of type ``cancellation_review`` on the
``phd.request`` workflow (guide → research cell → dean); the research cell's decision is ``warning`` (kept, streak
reset) or ``discontinue``. Reminders go out weekly before the due date; the compliance dashboard counts due /
submitted / overdue per scholar.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.models.phd import ResearchScholar, ScholarProgressReport, ScholarRequest
from app.schemas.phd import (
    CancellationDecision,
    ComplianceRow,
    DcReview,
    Discontinue,
    GuideReview,
    ProgressPeriod,
    ProgressReportOut,
    ProgressReportSubmit,
    ScholarRequestOut,
)
from app.services.phd.common import PhdBase, forbidden, not_found, now_utc, rule, staff_name

ENTITY = "scholar_progress_report"


def period_of(d: date) -> str:
    return f"{d.year}-H{1 if d.month <= 6 else 2}"


def period_end(label: str) -> date:
    y, h = int(label[:4]), label[-1]
    return date(y, 6, 30) if h == "1" else date(y, 12, 31)


def next_period(label: str) -> str:
    y, h = int(label[:4]), label[-1]
    return f"{y}-H2" if h == "1" else f"{y + 1}-H1"


class ProgressService(PhdBase):
    async def outs(self, rows: list[ScholarProgressReport]) -> list[ProgressReportOut]:
        metas = await self.metas("progress", [r.id for r in rows])
        return [
            ProgressReportOut(
                id=r.id,
                scholar_id=r.scholar_id,
                period_label=r.period_label,
                report_url=r.report_url,
                summary=r.summary,
                guide_remarks=r.guide_remarks,
                dc_rating=r.dc_rating,
                dc_remarks=(metas.get(str(r.id)) or {}).get("dc_remarks"),
                status=r.status,
                submitted_at=r.submitted_at,
                reviewed_at=r.reviewed_at,
            )
            for r in rows
        ]

    async def _labels(self, s: ResearchScholar, upto: date) -> list[str]:
        if s.registration_date is None:
            return []
        label = period_of(s.registration_date)
        out: list[str] = []
        while period_end(label) <= upto + timedelta(days=183) and len(out) < 40:
            out.append(label)
            label = next_period(label)
        return out

    async def periods(self, s: ResearchScholar) -> list[ProgressPeriod]:
        today = await self.today()
        grace = await self.rule_int("progress_grace_days")
        have = {
            r.period_label: r
            for r in (
                await self.db.execute(select(ScholarProgressReport).where(ScholarProgressReport.scholar_id == s.id))
            ).scalars()
        }
        out: list[ProgressPeriod] = []
        for label in await self._labels(s, today):
            due = period_end(label)
            r = have.get(label)
            status = r.status if r else ("overdue" if today > due + timedelta(days=grace) else "due")
            out.append(ProgressPeriod(period_label=label, due_on=due, report_id=r.id if r else None, status=status))
        return out

    async def reports(self, sid: uuid.UUID) -> list[ProgressReportOut]:
        s = await self.scholar(sid)
        rows = list(
            (
                await self.db.execute(
                    select(ScholarProgressReport)
                    .where(ScholarProgressReport.scholar_id == s.id)
                    .order_by(ScholarProgressReport.period_label)
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def submit(self, sid: uuid.UUID, body: ProgressReportSubmit) -> ProgressReportOut:
        s = await self.scholar(sid, lock=True)
        self.require_writer()
        if not (await self.is_self(s) or self.cell()):
            raise forbidden("The scholar submits the progress report")
        if s.registration_date is None:
            raise rule("Progress reports start after registration", "NOT_REGISTERED")
        if body.period_label not in await self._labels(s, await self.today()):
            raise rule(f"{body.period_label} is not a reporting period of this scholar", "BAD_PERIOD", 422)
        existing = (
            await self.db.execute(
                select(ScholarProgressReport).where(
                    ScholarProgressReport.scholar_id == s.id, ScholarProgressReport.period_label == body.period_label
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status != "submitted":
                raise rule("The report is already reviewed", "ALREADY_REVIEWED")
            existing.report_url, existing.summary = body.report_url, body.summary
            r = existing
        else:
            r = ScholarProgressReport(
                institution_id=self.inst,
                scholar_id=s.id,
                period_label=body.period_label,
                report_url=body.report_url,
                summary=body.summary,
            )
            self.db.add(r)
        await self.db.flush()
        await self._emit(
            "phd.progress_report_submitted",
            {"scholar_id": str(s.id), "report_id": str(r.id), "period": r.period_label},
            ENTITY,
            r.id,
        )
        return (await self.outs([r]))[0]

    async def _report(self, rid: uuid.UUID) -> tuple[ScholarProgressReport, ResearchScholar]:
        r = (
            await self.db.execute(
                select(ScholarProgressReport)
                .where(ScholarProgressReport.id == rid, ScholarProgressReport.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Progress report")
        return r, await self.scholar(r.scholar_id)

    async def guide_review(self, rid: uuid.UUID, body: GuideReview) -> ProgressReportOut:
        r, s = await self._report(rid)
        await self.require_relation(s, "guide", "co_guide")
        if r.status != "submitted":
            raise rule("The report is past the guide review", "ALREADY_REVIEWED")
        r.guide_remarks, r.status = body.remarks, "guide_reviewed"
        await self.db.flush()
        await self._emit(
            "phd.progress_report_reviewed", {"scholar_id": str(s.id), "report_id": str(r.id)}, ENTITY, r.id
        )
        await self._notify(
            "phd.progress_report_reviewed",
            [await self.scholar_user(s)],
            {"period": r.period_label, "stage": "guide", "rating": ""},
        )
        return (await self.outs([r]))[0]

    async def dc_review(self, rid: uuid.UUID, body: DcReview) -> ProgressReportOut:
        r, s = await self._report(rid)
        await self.require_relation(s, "convenor", "dc", "guide")
        if r.status == "submitted":
            raise rule("The guide reviews the report first", "GUIDE_REVIEW_PENDING")
        if r.status == "dc_reviewed":
            raise rule("The report is already rated", "ALREADY_REVIEWED")
        r.dc_rating, r.status, r.reviewed_at = body.rating.value, "dc_reviewed", now_utc()
        m = await self.meta("progress", r.id)
        m.update({"dc_remarks": body.remarks, "meeting_id": str(body.meeting_id) if body.meeting_id else None})
        await self.put_meta("progress", r.id, m)
        await self.db.flush()
        await self._emit(
            "phd.progress_report_rated",
            {"scholar_id": str(s.id), "report_id": str(r.id), "rating": r.dc_rating, "period": r.period_label},
            ENTITY,
            r.id,
        )
        await self._notify(
            "phd.progress_report_reviewed",
            [await self.scholar_user(s)],
            {"period": r.period_label, "stage": "DC", "rating": r.dc_rating},
        )
        streak = await self.unsatisfactory_streak(s)
        if streak >= await self.rule_int("unsatisfactory_limit"):
            await self.flag_cancellation(s, reason="unsatisfactory_progress", streak=streak)
        return (await self.outs([r]))[0]

    async def unsatisfactory_streak(self, s: ResearchScholar) -> int:
        sm = await self.meta("scholar", s.id)
        reset = sm.get("streak_reset_after")
        rows = (
            await self.db.execute(
                select(ScholarProgressReport.period_label, ScholarProgressReport.dc_rating)
                .where(ScholarProgressReport.scholar_id == s.id, ScholarProgressReport.status == "dc_reviewed")
                .order_by(ScholarProgressReport.period_label.desc())
            )
        ).all()
        n = 0
        for label, rating in rows:
            if reset and label <= reset:
                break
            if rating != "unsatisfactory":
                break
            n += 1
        return n

    async def flag_cancellation(self, s: ResearchScholar, *, reason: str, streak: int = 0) -> None:
        sm = await self.meta("scholar", s.id)
        if sm.get("cancellation_review"):
            return
        sm["cancellation_review"] = {"reason": reason, "streak": streak, "on": (await self.today()).isoformat()}
        await self.put_meta("scholar", s.id, sm)
        await self.scholar_timeline(s, "cancellation_review", reason=reason, streak=streak)
        from app.services.phd.request_service import RequestService

        req = await RequestService(self.db, None, self.request, self.inst).open_system(
            s, "cancellation_review", {"reason": reason, "streak": streak}
        )
        await self._emit(
            "phd.cancellation_review",
            {"scholar_id": str(s.id), "reason": reason, "streak": streak, "request_id": str(req.id)},
            "research_scholar",
            s.id,
        )
        await self._notify(
            "phd.cancellation_review",
            await self.guide_users(s),
            {"scholar": await self.scholar_name(s), "count": streak},
        )

    async def decide_cancellation(self, request_id: uuid.UUID, body: CancellationDecision) -> ScholarRequestOut:
        """The research cell's (or dean's) decision on a cancellation review: ``warning`` keeps the scholar."""
        from app.services.phd.request_service import RequestService
        from app.services.phd.scholar_service import ScholarService

        self.require_writer()
        if not (self.cell() or self.approver()):
            raise forbidden("The research cell or dean decides cancellation reviews")
        rsvc = RequestService(self.db, self.principal, self.request, self.inst)
        req = await rsvc.row(request_id, lock=True)
        if req.request_type != "cancellation_review":
            raise rule("Not a cancellation review", "WRONG_REQUEST_TYPE", 422)
        s = await self.scholar_raw(req.scholar_id, lock=True)
        sm = await self.meta("scholar", s.id)
        sm.pop("cancellation_review", None)
        latest = (
            await self.db.execute(
                select(ScholarProgressReport.period_label)
                .where(ScholarProgressReport.scholar_id == s.id)
                .order_by(ScholarProgressReport.period_label.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest:
            sm["streak_reset_after"] = latest
        await self.put_meta("scholar", s.id, sm)
        await rsvc.finish(req, approve=body.decision == "discontinue", remarks=body.remarks, decision=body.decision)
        if body.decision == "discontinue":
            await ScholarService(self.db, self.principal, self.request, self.inst).discontinue(
                s.id, Discontinue(reason="unsatisfactory_progress", remarks=body.remarks), system=True
            )
        else:
            await self.scholar_timeline(s, "warning", remarks=body.remarks)
        return (await rsvc.outs([req]))[0]

    # ---- compliance / Beat --------------------------------------------------------------------------------------------
    async def compliance(self, department_id: uuid.UUID | None = None) -> list[ComplianceRow]:
        from app.models.students import StudentProgramEnrollment

        stmt = select(ResearchScholar).where(
            ResearchScholar.institution_id == self.inst,
            ResearchScholar.registration_date.is_not(None),
            ResearchScholar.status.not_in(("awarded", "discontinued")),
            await self.scholar_predicate(),
        )
        if department_id:
            stmt = stmt.join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == ResearchScholar.student_program_enrollment_id
            ).where(StudentProgramEnrollment.department_id == department_id)
        rows = list((await self.db.execute(stmt)).scalars())
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        staff = await self.staff_map([r.guide_staff_id for r in rows])
        today = await self.today()
        out: list[ComplianceRow] = []
        for s in rows:
            ps = [p for p in await self.periods(s) if p.due_on <= today]
            c = cards.get(s.student_program_enrollment_id) or {}
            out.append(
                ComplianceRow(
                    scholar_id=s.id,
                    name=c.get("name"),
                    guide_name=staff_name(staff.get(s.guide_staff_id)),
                    department_id=c.get("department_id"),
                    due=len(ps),
                    submitted=sum(1 for p in ps if p.report_id),
                    overdue=[p.period_label for p in ps if p.status == "overdue"],
                    unsatisfactory_streak=await self.unsatisfactory_streak(s),
                )
            )
        return out

    async def overdue(self, s: ResearchScholar) -> bool:
        return any(p.status == "overdue" for p in await self.periods(s))

    async def due_reminders(self) -> int:
        """Weekly: a reminder for each scholar whose current period ends within 30 days without a report."""
        today = await self.today()
        n = 0
        for s in (
            await self.db.execute(
                select(ResearchScholar).where(
                    ResearchScholar.institution_id == self.inst,
                    ResearchScholar.registration_date.is_not(None),
                    ResearchScholar.status.in_(("registered", "synopsis_submitted")),
                )
            )
        ).scalars():
            for p in await self.periods(s):
                if p.status == "due" and 0 <= (p.due_on - today).days <= 30:
                    m = await self.meta("progress_reminder", s.id)
                    if m.get(p.period_label):
                        continue
                    m[p.period_label] = today.isoformat()
                    await self.put_meta("progress_reminder", s.id, m)
                    await self._notify(
                        "phd.progress_report_due",
                        [await self.scholar_user(s)],
                        {"period": p.period_label, "due_on": str(p.due_on)},
                    )
                    n += 1
        return n

    async def generate_periods(self) -> int:
        """Job ``phd.progress_periods_generate``: counts the periods now due (rows are created on submission)."""
        today = await self.today()
        n = 0
        for s in (
            await self.db.execute(
                select(ResearchScholar).where(
                    ResearchScholar.institution_id == self.inst, ResearchScholar.registration_date.is_not(None)
                )
            )
        ).scalars():
            n += sum(1 for p in await self.periods(s) if p.due_on <= today)
        return n

    async def open_cancellation_request(self, s: ResearchScholar) -> ScholarRequest | None:
        return (
            await self.db.execute(
                select(ScholarRequest).where(
                    ScholarRequest.scholar_id == s.id,
                    ScholarRequest.request_type == "cancellation_review",
                    ScholarRequest.status.in_(("requested", "in_review")),
                )
            )
        ).scalar_one_or_none()
