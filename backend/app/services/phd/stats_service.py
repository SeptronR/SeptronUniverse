"""PhD stats & returns — Prompts/31 §31.6 ``stats_service`` (``phd:view_all`` / IQAC / ``reports:statutory``).

Scholars by status / guide / department, average time to award (registration → date of award), PhDs awarded per
year (NIRF **GPHD** — issued or council-approved Phase 18 ``phd`` awards of the year), guide load utilisation,
fellowship spend (paid disbursements), plagiarism stats and examiner turnaround (invitation → report). Publishes
``phd.stats_published`` with ``nirf.gphd``, ``faculty.phd_guides`` and ``research.phd_awarded`` (Phase 32 owns
``metric_values``); report rows for the xlsx exports (scholars, fellowships, awards, UGC return, examiners).
"""

from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.models.degrees import DegreeAwarded
from app.models.hr import FacultyProfile
from app.models.phd import FellowshipDisbursement, ResearchScholar, ScholarFellowship, ThesisExaminer, ThesisSubmission
from app.models.students import StudentProgramEnrollment
from app.schemas.phd import PhdStats
from app.services.phd.common import PhdBase, forbidden, months_between, staff_name


class StatsService(PhdBase):
    def require_reader(self) -> None:
        p = self.principal
        if self.system():
            return
        if not (
            p.has("phd", "view_all")
            or p.has("phd", "manage")
            or p.has("reports", "statutory")
            or p.has("reports", "export")
        ):
            raise forbidden("phd:view_all or reports:statutory required")

    async def _scholars(self, department_id: Any = None) -> list[ResearchScholar]:
        stmt = select(ResearchScholar).where(
            ResearchScholar.institution_id == self.inst, await self.scholar_predicate()
        )
        if department_id:
            stmt = stmt.join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == ResearchScholar.student_program_enrollment_id
            ).where(StudentProgramEnrollment.department_id == department_id)
        return list((await self.db.execute(stmt)).scalars())

    async def stats(self, department_id: Any = None, year: int | None = None) -> PhdStats:
        self.require_reader()
        rows = await self._scholars(department_id)
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        codes = await self.department_codes(
            [(cards.get(r.student_program_enrollment_id) or {}).get("department_id") for r in rows]
        )
        staff = await self.staff_map([r.guide_staff_id for r in rows])
        by_status = Counter(r.status for r in rows)
        active = [r for r in rows if r.status not in ("awarded", "discontinued")]
        by_guide = Counter(r.guide_staff_id for r in active)

        def dept_code(r: ResearchScholar) -> str:
            dep = (cards.get(r.student_program_enrollment_id) or {}).get("department_id")
            return (codes.get(dep) if dep else None) or "—"

        by_dept = Counter(dept_code(r) for r in rows)
        enr = {r.student_program_enrollment_id: r for r in rows}
        awards = (
            (
                await self.db.execute(
                    select(DegreeAwarded).where(
                        DegreeAwarded.institution_id == self.inst,
                        DegreeAwarded.award_type == "phd",
                        DegreeAwarded.status.in_(("council_approved", "issued", "reissued")),
                        DegreeAwarded.student_program_enrollment_id.in_(list(enr) or [None]),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_year = Counter(str(a.date_of_award.year) for a in awards if a.date_of_award)
        durations = [
            months_between(enr[a.student_program_enrollment_id].registration_date or a.date_of_award, a.date_of_award)
            for a in awards
            if a.date_of_award
            and enr.get(a.student_program_enrollment_id)
            and enr[a.student_program_enrollment_id].registration_date
        ]
        yr = year or (await self.today()).year
        gphd = int(by_year.get(str(yr), 0))
        caps = total_cap = 0
        for sid in by_guide:
            mx, _ = await self.guide_max(sid)
            total_cap += mx
            caps += by_guide[sid]
        spend = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(FellowshipDisbursement.amount_paise), 0))
                    .join(ScholarFellowship, ScholarFellowship.id == FellowshipDisbursement.fellowship_id)
                    .where(
                        FellowshipDisbursement.institution_id == self.inst,
                        FellowshipDisbursement.status == "paid",
                        ScholarFellowship.scholar_id.in_([r.id for r in rows] or [None]),
                    )
                )
            ).scalar_one()
        )
        sims = [
            float(x)
            for (x,) in (
                await self.db.execute(
                    select(ThesisSubmission.similarity_pct).where(
                        ThesisSubmission.institution_id == self.inst,
                        ThesisSubmission.similarity_pct.is_not(None),
                        ThesisSubmission.scholar_id.in_([r.id for r in rows] or [None]),
                    )
                )
            ).all()
        ]
        limit = float((await self.rules()).get("similarity_max_pct") or 10)
        turn = [
            (rr - inv).days
            for inv, rr in (
                await self.db.execute(
                    select(ThesisExaminer.invited_at, ThesisExaminer.report_received_at).where(
                        ThesisExaminer.institution_id == self.inst,
                        ThesisExaminer.invited_at.is_not(None),
                        ThesisExaminer.report_received_at.is_not(None),
                    )
                )
            ).all()
        ]
        return PhdStats(
            by_status=dict(by_status),
            by_guide=[
                {"staff_id": str(k), "name": staff_name(staff.get(k)), "scholars": v} for k, v in by_guide.most_common()
            ],
            by_department=dict(by_dept),
            avg_duration_months=round(sum(durations) / len(durations), 1) if durations else None,
            awarded_by_year=dict(sorted(by_year.items())),
            gphd=gphd,
            guide_utilisation_pct=round(caps * 100 / total_cap, 1) if total_cap else None,
            fellowship_spend_paise=spend,
            plagiarism={
                "checked": len(sims),
                "avg_pct": round(sum(sims) / len(sims), 2) if sims else None,
                "above_limit": sum(1 for x in sims if x > limit),
            },
            examiner_turnaround_days=round(sum(turn) / len(turn), 1) if turn else None,
        )

    async def publish(self, year: int | None = None) -> PhdStats:
        st = await self.stats(year=year)
        guides = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(FacultyProfile)
                    .where(FacultyProfile.institution_id == self.inst, FacultyProfile.is_phd_guide.is_(True))
                )
            ).scalar_one()
        )
        await self._emit(
            "phd.stats_published",
            {
                "year": year or (await self.today()).year,
                "metrics": {"nirf.gphd": st.gphd, "faculty.phd_guides": guides, "research.phd_awarded": st.gphd},
            },
            "institution",
            self.inst,
        )
        return st

    async def report_rows(self, kind: str, year: int | None = None) -> list[dict[str, Any]]:
        self.require_reader()
        from app.services.phd.award_service import AwardService
        from app.services.phd.examiner_service import ExaminerService
        from app.services.phd.fellowship_service import FellowshipService
        from app.services.phd.scholar_service import ScholarService

        args = (self.db, self.principal, self.request, self.inst)
        if kind == "scholars":
            items, _ = await ScholarService(*args).query(limit=100000)
            return [
                {
                    k: v
                    for k, v in i.model_dump(mode="json").items()
                    if k not in ("chips", "relation", "external_co_guide")
                }
                for i in items
            ]
        if kind == "fellowships":
            disb, _ = await FellowshipService(*args).disbursements(limit=100000)
            return [i.model_dump(mode="json") for i in disb if year is None or i.month.year == year]
        if kind == "awards":
            return await AwardService(*args).awards(year)
        if kind == "examiners":
            return [i.model_dump(mode="json") for i in await ExaminerService(*args).tracker()]
        if kind == "ugc_return":
            items, _ = await ScholarService(*args).query(limit=100000)
            cut = date(year or (await self.today()).year, 12, 31)
            return [
                {
                    "registration_number": i.registration_number,
                    "name": i.name,
                    "mode": i.mode,
                    "fellowship": i.fellowship_type,
                    "registration_date": i.registration_date.isoformat() if i.registration_date else None,
                    "status": i.status,
                    "guide": i.guide_name,
                    "research_area": i.research_area,
                }
                for i in items
                if i.registration_date is None or i.registration_date <= cut
            ]
        return []
