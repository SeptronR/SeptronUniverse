"""Dashboards, returns and metrics — Prompts/34 §34.6 ``dashboard_service`` + ``portfolio_repository``.

* **College dashboard** (own college for college roles; any college for the office): profile, approvals with validity,
  applications, dues, submissions by term, results release (Phase 15 published runs per central session), inspections,
  compliance score.
* **University portfolio** (``affiliation:view_all``): colleges by type, applications by status / type, inspections due,
  deficiencies open, dues, submission compliance %, results gating per session, expiring approvals.
* **Statutory returns** (``colleges_list | intake | results_by_college``) for UGC / state (Phase 36) and the **public
  list** of approved colleges / programmes for the website (Phase 40; no dues / deficiencies).
* **Metrics** for Phase 32: ``metrics.publish`` with ``source='affiliation'`` (``affiliation.colleges_count`` is computed
  by the registry; the published keys are ``affiliation.sanctioned_intake``, ``affiliation.programs_approved``,
  ``affiliation.submission_compliance_pct``, ``affiliation.autonomous_colleges``).
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text

from app.models.academic import Program
from app.models.affiliation import AffiliationApplication, AffiliationProgramApproval, CollegeDataSubmission
from app.models.exams import ExamSession
from app.models.platform import College
from app.schemas.affiliation import (
    AffiliationReturn,
    CollegeDashboard,
    PublicCollege,
    UniversityPortfolio,
)
from app.services.affiliation.common import AffiliationBase, forbidden, not_found, pairs
from app.services.affiliation.gates import session_gating


class DashboardService(AffiliationBase):
    async def _results_release(self, college_id: uuid.UUID | None) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                text(
                    "SELECT es.id, es.name, es.status, max(r.status) FILTER (WHERE r.status = 'published') AS pub, "
                    "max(r.updated_at) AS at FROM exam_sessions es LEFT JOIN result_processing_runs r "
                    "ON r.exam_session_id = es.id WHERE es.institution_id = :i AND es.college_id IS NULL "
                    "AND es.deleted_at IS NULL GROUP BY es.id, es.name, es.status ORDER BY max(es.created_at) DESC LIMIT 6"
                ),
                {"i": self.inst},
            )
        ).all()
        out = []
        for sid, name, status, pub, at in rows:
            item: dict[str, Any] = {
                "session_id": str(sid),
                "session": name,
                "session_status": status,
                "published": bool(pub),
                "at": at.isoformat() if at else None,
            }
            if college_id is not None:
                s = (await self.db.execute(select(ExamSession).where(ExamSession.id == sid))).scalar_one()
                g = (await session_gating(self.db, self.inst, s)).get(college_id)
                item["gating"] = g["status"] if g else "not_applicable"
                item["missing"] = g["missing"] if g else []
            out.append(item)
        return out

    async def college_dashboard(self, college_id: uuid.UUID | None) -> CollegeDashboard:
        if college_id is None:
            mine = self.my_college_ids()
            if not mine:
                raise forbidden("No college is assigned to you")
            college_id = mine[0]
        from app.services.affiliation.application_service import ApplicationService
        from app.services.affiliation.college_registry_service import CollegeRegistryService
        from app.services.affiliation.program_approval_service import ProgramApprovalService

        args = (self.db, self.principal, self.request, self.inst)
        reg = CollegeRegistryService(*args)
        profile = await reg.profile(college_id)
        approvals, _ = await ProgramApprovalService(*args).list_approvals(college_id, None, None, None, 1, 200)
        apps_svc = ApplicationService(*args)
        apps, _ = await apps_svc.list_applications(college_id, None, None, None, None, 1, 20)
        dues = await ProgramApprovalService(*args).dues(college_id)
        subs: dict[str, dict[str, str]] = {}
        for r in (
            await self.db.execute(
                select(CollegeDataSubmission).where(CollegeDataSubmission.college_id == college_id).limit(500)
            )
        ).scalars():
            subs.setdefault(str(r.term_id), {})[r.submission_type] = r.status
        inspections = [i for i in await apps_svc.inspections(None, None) if i.college_id == college_id]
        return CollegeDashboard(
            profile=profile,
            approvals=approvals,
            applications=apps,
            dues=dues[0] if dues else None,
            submissions_by_term=subs,
            results_release=await self._results_release(college_id),
            inspections=inspections,
            compliance_score=profile.compliance.score,
        )

    async def portfolio(self) -> UniversityPortfolio:
        if not (self.system() or self.office_reader()):
            raise forbidden("affiliation:view_all required")
        from app.services.affiliation.program_approval_service import ProgramApprovalService

        by_type = pairs(
            (
                await self.db.execute(
                    select(College.college_type, func.count())
                    .where(College.institution_id == self.inst, College.deleted_at.is_(None), College.is_active)
                    .group_by(College.college_type)
                )
            ).all()
        )
        by_status = pairs(
            (
                await self.db.execute(
                    select(AffiliationApplication.status, func.count())
                    .where(AffiliationApplication.institution_id == self.inst)
                    .group_by(AffiliationApplication.status)
                )
            ).all()
        )
        by_app_type = pairs(
            (
                await self.db.execute(
                    select(AffiliationApplication.application_type, func.count())
                    .where(AffiliationApplication.institution_id == self.inst)
                    .group_by(AffiliationApplication.application_type)
                )
            ).all()
        )
        today = await self.today()
        insp_due = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(AffiliationApplication)
                    .where(
                        AffiliationApplication.institution_id == self.inst,
                        AffiliationApplication.status.in_(("scrutiny", "inspection_scheduled")),
                    )
                )
            ).scalar_one()
        )
        defs_open = 0
        for defs in (
            await self.db.execute(
                select(AffiliationApplication.deficiencies).where(
                    AffiliationApplication.institution_id == self.inst,
                    AffiliationApplication.status.in_(("inspected", "compliance_pending", "inspection_scheduled")),
                )
            )
        ).scalars():
            defs_open += sum(1 for d in defs or [] if d.get("status") != "closed")
        dues = await ProgramApprovalService(self.db, self.principal, self.request, self.inst).dues(None)
        subs = pairs(
            (
                await self.db.execute(
                    select(CollegeDataSubmission.status, func.count())
                    .where(CollegeDataSubmission.institution_id == self.inst)
                    .group_by(CollegeDataSubmission.status)
                )
            ).all()
        )
        total_subs = sum(int(v) for v in subs.values())
        compliance = (
            round(100 * (int(subs.get("accepted", 0)) + int(subs.get("locked", 0))) / total_subs, 1)
            if total_subs
            else None
        )
        gating = []
        for s in (
            await self.db.execute(
                select(ExamSession)
                .where(
                    ExamSession.institution_id == self.inst,
                    ExamSession.college_id.is_(None),
                    ExamSession.deleted_at.is_(None),
                )
                .order_by(ExamSession.created_at.desc())
                .limit(3)
            )
        ).scalars():
            g = await session_gating(self.db, self.inst, s)
            gating.append(
                {
                    "session_id": str(s.id),
                    "session": s.name,
                    "ready": sum(1 for v in g.values() if v["status"] == "ready"),
                    "gated": sum(1 for v in g.values() if v["status"] == "gated"),
                    "not_applicable": sum(1 for v in g.values() if v["status"] == "not_applicable"),
                }
            )
        days = await self.aff_int("expiry_reminder_days")
        expiring = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(AffiliationProgramApproval)
                    .where(
                        AffiliationProgramApproval.institution_id == self.inst,
                        AffiliationProgramApproval.approval_status != "withdrawn",
                        AffiliationProgramApproval.valid_to >= today,
                        AffiliationProgramApproval.valid_to <= today + timedelta(days=days),
                    )
                )
            ).scalar_one()
        )
        cur = await self.current_year_row()
        intake = 0
        if cur is not None:
            intake = int(
                (
                    await self.db.execute(
                        select(func.coalesce(func.sum(AffiliationProgramApproval.sanctioned_intake), 0)).where(
                            AffiliationProgramApproval.institution_id == self.inst,
                            AffiliationProgramApproval.academic_year_id == cur.id,
                            AffiliationProgramApproval.approval_status != "withdrawn",
                        )
                    )
                ).scalar_one()
            )
        return UniversityPortfolio(
            colleges_by_type={str(k): int(v) for k, v in by_type.items()},
            applications_by_status={str(k): int(v) for k, v in by_status.items()},
            applications_by_type={str(k): int(v) for k, v in by_app_type.items()},
            inspections_due=insp_due,
            deficiencies_open=defs_open,
            dues_outstanding_paise=sum(d.outstanding_paise for d in dues),
            dues_by_college=dues[:20],
            submissions_compliance_pct=compliance,
            results_gating=gating,
            expiring_approvals=expiring,
            sanctioned_intake=intake,
        )

    # ---- returns / public -------------------------------------------------------------------------------------------
    async def returns(self, kind: str, year_id: uuid.UUID | None) -> AffiliationReturn:
        p = self.principal
        if not (self.system() or self.office_reader() or (p is not None and p.has("reports", "statutory"))):
            raise forbidden("affiliation:view_all or reports:statutory required")
        y = await self.year(year_id) if year_id else await self.current_year_row()
        rows: list[dict[str, Any]] = []
        colleges = await self.colleges_map()
        if kind == "colleges_list":
            for c in sorted(colleges.values(), key=lambda x: x.code):
                if c.college_type not in ("affiliated", "autonomous", "constituent"):
                    continue
                rows.append(
                    {
                        "code": c.code,
                        "name": c.name,
                        "type": c.college_type,
                        "affiliation_number": c.affiliation_number,
                        "affiliated_since": c.affiliated_since.isoformat() if c.affiliated_since else None,
                        "aishe_code": c.aishe_code,
                        "aicte_pid": c.aicte_pid,
                        "exam_centre": c.is_exam_centre,
                    }
                )
        elif kind == "intake":
            stmt = select(AffiliationProgramApproval).where(AffiliationProgramApproval.institution_id == self.inst)
            if y is not None:
                stmt = stmt.where(AffiliationProgramApproval.academic_year_id == y.id)
            appr = list((await self.db.execute(stmt)).scalars())
            progs = await self.programs_map([a.program_id for a in appr])
            for a in appr:
                col = colleges.get(a.college_id)
                pr = progs.get(a.program_id)
                rows.append(
                    {
                        "college": col.code if col else None,
                        "program": pr.code if pr else None,
                        "program_name": pr.name if pr else None,
                        "level": pr.level if pr else None,
                        "sanctioned_intake": int(a.sanctioned_intake),
                        "lateral_intake": int(a.lateral_intake or 0),
                        "status": a.approval_status,
                        "valid_to": a.valid_to.isoformat() if a.valid_to else None,
                        "order_no": a.order_no,
                    }
                )
        elif kind == "results_by_college":
            res = await self.db.execute(
                text(
                    "SELECT g.college_id, count(DISTINCT t.student_program_enrollment_id) AS appeared, "
                    "count(DISTINCT t.student_program_enrollment_id) FILTER (WHERE t.result_status = 'pass') AS passed "
                    "FROM student_term_results t JOIN result_processing_runs r ON r.id = t.run_id "
                    "JOIN exam_registrations g ON g.exam_session_id = r.exam_session_id "
                    "AND g.student_program_enrollment_id = t.student_program_enrollment_id "
                    "WHERE t.institution_id = :i AND r.status = 'published' GROUP BY g.college_id"
                ),
                {"i": self.inst},
            )
            for cid, appeared, passed in res.all():
                col = colleges.get(cid)
                rows.append(
                    {
                        "college": col.code if col else str(cid),
                        "name": col.name if col else None,
                        "appeared": int(appeared or 0),
                        "passed": int(passed or 0),
                        "pass_pct": round(100 * int(passed or 0) / int(appeared), 1) if appeared else None,
                    }
                )
        else:
            raise not_found("Return")
        return AffiliationReturn(kind=kind, year=y.name if y else None, rows=rows)

    async def public_colleges(self) -> list[PublicCollege]:
        cur = await self.current_year_row()
        colleges = [
            c
            for c in (await self.colleges_map()).values()
            if c.is_active and c.college_type in ("affiliated", "autonomous", "constituent")
        ]
        stmt = select(AffiliationProgramApproval).where(
            AffiliationProgramApproval.institution_id == self.inst,
            AffiliationProgramApproval.approval_status.in_(("provisional", "permanent", "conditional")),
        )
        if cur is not None:
            stmt = stmt.where(AffiliationProgramApproval.academic_year_id == cur.id)
        appr = list((await self.db.execute(stmt)).scalars())
        progs = await self.programs_map([a.program_id for a in appr])
        by: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for a in appr:
            pr: Program | None = progs.get(a.program_id)
            if pr is None:
                continue
            by.setdefault(a.college_id, []).append(
                {"code": pr.code, "name": pr.name, "level": pr.level, "intake": int(a.sanctioned_intake)}
            )
        return [
            PublicCollege(
                code=c.code,
                name=c.name,
                college_type=c.college_type,
                affiliation_number=c.affiliation_number,
                affiliated_since=c.affiliated_since,
                programmes=sorted(by.get(c.id, []), key=lambda x: x["code"]),
            )
            for c in sorted(colleges, key=lambda x: x.code)
            if by.get(c.id) or c.college_type == "constituent"
        ]

    # ---- Phase 32 metrics ---------------------------------------------------------------------------------------------
    async def publish_metrics(self) -> dict[str, Any]:
        cur = await self.current_year_row()
        portfolio = await DashboardService(self.db, None, institution_id=self.inst).portfolio()
        programmes = 0
        if cur is not None:
            programmes = int(
                (
                    await self.db.execute(
                        select(func.count()).where(
                            AffiliationProgramApproval.institution_id == self.inst,
                            AffiliationProgramApproval.academic_year_id == cur.id,
                            AffiliationProgramApproval.approval_status != "withdrawn",
                        )
                    )
                ).scalar_one()
            )
        metrics: dict[str, Any] = {
            "affiliation.sanctioned_intake": portfolio.sanctioned_intake,
            "affiliation.programs_approved": programmes,
            "affiliation.autonomous_colleges": int(portfolio.colleges_by_type.get("autonomous", 0)),
        }
        if portfolio.submissions_compliance_pct is not None:
            metrics["affiliation.submission_compliance_pct"] = portfolio.submissions_compliance_pct
        payload: dict[str, Any] = {"source": "affiliation", "metrics": metrics}
        if cur is not None:
            payload["year"] = cur.start_date.year
        await self._emit("metrics.publish", payload, "affiliation_metrics", None)
        await self._emit("affiliation.portfolio_updated", {"metrics": metrics}, "affiliation_metrics", None)
        return payload
