"""Student-support statistics — Prompts/27 §27.6 ``stats_service``: mentoring coverage and session compliance, risk
distribution, grievance SLA / categories, discipline counts, survey completion, club participation and achievements
(Phases 32 / 35 read the same numbers). College admins see their colleges only (the enrolment-scoped parts)."""

import uuid

from app.schemas.clubs import SupportStats
from app.services.student_support.club_service import ClubService
from app.services.student_support.common import SupportBase, forbidden
from app.services.student_support.discipline_service import DisciplineService
from app.services.student_support.grievance_service import GrievanceService
from app.services.student_support.mentoring_service import MentoringService
from app.services.student_support.risk_service import RiskService
from app.services.student_support.survey_service import SurveyService


class StatsService(SupportBase):
    audit_module = "mentoring"
    module = "mentoring"

    async def stats(self, term_id: uuid.UUID | None) -> SupportStats:
        if not (self.reader() or self.can("accreditation", "view") or self.can("surveys", "manage")):
            raise forbidden("mentoring:view_all or IQAC required")
        args = (self.db, self.principal, self.request, self.inst)
        term = await self.term_or_current(term_id) if term_id else await self.current_term(None)
        mentoring: dict[str, object] = {}
        risk: dict[str, int] = {}
        if term is not None:
            load = await MentoringService(*args).load(term.id)
            mentoring = {
                **(await MentoringService(*args).coverage(term.id)),
                "compliance_pct": load.compliance_pct,
                "min_sessions": load.min_sessions,
                "mentors_over_ratio": sum(1 for r in load.rows if r.over_ratio),
            }
            risk = await RiskService(*args).distribution(term.id)
        return SupportStats(
            term_id=term.id if term else None,
            mentoring=mentoring,
            risk=risk,
            grievances=await GrievanceService(*args).stats(),
            discipline=await DisciplineService(*args).counts(),
            surveys=await SurveyService(*args).stats(),
            clubs=await ClubService(*args).stats(),
            achievements=(await ClubService(*args).stats()).get("achievements", {}),  # type: ignore[arg-type]
        )
