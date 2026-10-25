"""Placement statistics — Prompts/28 §28.6 ``stats_service`` ({placement.core}).

``eligible`` = final-year students in scope with a placement profile; ``placed_pct = placed / (eligible − opted_out)``
(NAAC 5.2.1); median / average / highest CTC of placed students (best offer per student) on
``placement.nirf_median_basis`` (``accepted_offers`` | ``all_offers`` | ``joined`` — NIRF GMS); higher-studies %
(NAAC 5.2.2) from opt-outs with reason ``higher_studies``; internships % (NAAC 1.3.4); by programme / company / tier;
PPO count. College-scoped readers see only their colleges. ``publish`` emits ``placement.stats_published`` with the
``placement.placed_pct``, ``nirf.gms``, ``students.higher_studies_pct`` and ``academics.internships_pct`` values for
Phase 32 metrics. ``nirf_sheet`` / ``report`` build xlsx bytes for the export jobs.
"""

import io
import statistics
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from app.models.academic import Program
from app.models.placement import (
    Company,
    DriveApplication,
    Internship,
    PlacementDrive,
    PlacementOffer,
    StudentPlacementProfile,
    TrainingAttendance,
    TrainingProgram,
)
from app.models.students import StudentProgramEnrollment
from app.schemas.placement import PlcStats
from app.services.placement.common import PlacementBase, all_access, forbidden, scope_ids


class StatsService(PlacementBase):
    def _require(self) -> None:
        if not (self.officer() or self.reader() or self.can("placement", "view_all")):
            raise forbidden("placement:view_all required")

    async def stats(
        self, batch_id: uuid.UUID | None, program_id: uuid.UUID | None, college_id: uuid.UUID | None
    ) -> PlcStats:
        self._require()
        stmt = select(StudentPlacementProfile, StudentProgramEnrollment).join(
            StudentProgramEnrollment,
            StudentProgramEnrollment.id == StudentPlacementProfile.student_program_enrollment_id,
        )
        stmt = stmt.where(StudentPlacementProfile.institution_id == self.inst, self.in_dept())
        if batch_id:
            stmt = stmt.where(StudentProgramEnrollment.batch_id == batch_id)
        if program_id:
            stmt = stmt.where(StudentProgramEnrollment.program_id == program_id)
        p = self.principal
        cols = scope_ids(p, "college") if p is not None and not all_access(p, self.module) else []
        if college_id:
            if cols and college_id not in cols:
                raise forbidden("Another college")
            stmt = stmt.where(StudentProgramEnrollment.college_id == college_id)
        rows = (await self.db.execute(stmt)).all()
        ids = [e.id for _, e in rows]
        basis = str(await self.setting("placement", "nirf_median_basis") or "accepted_offers")
        statuses = {"accepted_offers": ("accepted", "joined"), "joined": ("joined",)}.get(
            basis, ("offered", "accepted", "joined", "not_joined")
        )
        offers = (
            await self.db.execute(
                select(PlacementOffer, DriveApplication.student_program_enrollment_id, Company)
                .join(DriveApplication, DriveApplication.id == PlacementOffer.application_id)
                .join(Company, Company.id == PlacementOffer.company_id)
                .where(DriveApplication.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
            )
        ).all()
        best: dict[uuid.UUID, int] = {}
        by_company: dict[str, dict[str, Any]] = defaultdict(lambda: {"offers": 0, "accepted": 0, "max_ctc_paise": 0})
        by_tier: dict[str, int] = defaultdict(int)
        n_offers = ppo = 0
        for o, eid, c in offers:
            if o.status == "revoked":
                continue
            n_offers += 1
            ppo += 1 if o.is_ppo else 0
            bc = by_company[c.name]
            bc["offers"] += 1
            bc["max_ctc_paise"] = max(bc["max_ctc_paise"], o.ctc_paise)
            if o.status in ("accepted", "joined"):
                bc["accepted"] += 1
                by_tier[c.tier or "unclassified"] += 1
            if o.status in statuses:
                best[eid] = max(best.get(eid, 0), o.ctc_paise)
        interns = {
            r[0]
            for r in (
                await self.db.execute(
                    select(Internship.student_program_enrollment_id).where(
                        Internship.student_program_enrollment_id.in_(ids or [uuid.uuid4()]),
                        Internship.status != "cancelled",
                    )
                )
            ).all()
        }
        programs = {
            r[0]: r[1]
            for r in (
                await self.db.execute(
                    select(Program.id, Program.code).where(
                        Program.id.in_({e.program_id for _, e in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        }
        eligible = len(rows)
        opted = sum(1 for pr, _ in rows if pr.is_opted_out)
        placed = sum(1 for pr, _ in rows if pr.placement_status in ("placed", "multiple"))
        multiple = sum(1 for pr, _ in rows if pr.placement_status == "multiple")
        higher = sum(1 for pr, _ in rows if pr.is_opted_out and pr.opt_out_reason == "higher_studies")
        salaries = sorted(best.values())
        per_prog: dict[uuid.UUID, dict[str, Any]] = defaultdict(
            lambda: {"eligible": 0, "opted_out": 0, "placed": 0, "higher_studies": 0, "salaries": []}
        )
        for pr, e in rows:
            g = per_prog[e.program_id]
            g["eligible"] += 1
            g["opted_out"] += 1 if pr.is_opted_out else 0
            g["placed"] += 1 if pr.placement_status in ("placed", "multiple") else 0
            g["higher_studies"] += 1 if pr.is_opted_out and pr.opt_out_reason == "higher_studies" else 0
            if e.id in best:
                g["salaries"].append(best[e.id])
        by_program = []
        nirf_rows = []
        for pid, g in per_prog.items():
            denom = g["eligible"] - g["opted_out"]
            med = int(statistics.median(g["salaries"])) if g["salaries"] else None
            by_program.append(
                {
                    "program_id": str(pid),
                    "program": programs.get(pid),
                    "eligible": g["eligible"],
                    "opted_out": g["opted_out"],
                    "placed": g["placed"],
                    "placed_pct": round(100 * g["placed"] / denom, 2) if denom > 0 else 0.0,
                    "median_ctc_paise": med,
                }
            )
            nirf_rows.append(
                {
                    "program": programs.get(pid),
                    "graduating_students": g["eligible"],
                    "placed": g["placed"],
                    "median_salary_inr": round(med / 100) if med else None,
                    "higher_studies": g["higher_studies"],
                }
            )
        denom = eligible - opted
        return PlcStats(
            batch_id=batch_id,
            program_id=program_id,
            college_id=college_id,
            eligible=eligible,
            opted_out=opted,
            placed=placed,
            placed_pct=round(100 * placed / denom, 2) if denom > 0 else 0.0,
            multiple=multiple,
            offers=n_offers,
            ppo=ppo,
            median_ctc_paise=int(statistics.median(salaries)) if salaries else None,
            avg_ctc_paise=int(sum(salaries) / len(salaries)) if salaries else None,
            highest_ctc_paise=salaries[-1] if salaries else None,
            higher_studies=higher,
            higher_studies_pct=round(100 * higher / eligible, 2) if eligible else 0.0,
            internships_pct=round(100 * len(interns) / eligible, 2) if eligible else 0.0,
            by_program=sorted(by_program, key=lambda r: str(r["program"])),
            by_company=sorted([{"company": k, **v} for k, v in by_company.items()], key=lambda r: -int(r["accepted"]))[
                :50
            ],
            by_tier=[{"tier": k, "accepted": v} for k, v in sorted(by_tier.items())],
            nirf_rows=nirf_rows,
        )

    async def publish(self, batch_id: uuid.UUID | None = None) -> PlcStats:
        s = await self.stats(batch_id, None, None)
        await self._emit(
            "placement.stats_published",
            {
                "batch_id": str(batch_id) if batch_id else None,
                "metrics": {
                    "placement.placed_pct": s.placed_pct,
                    "nirf.gms": s.median_ctc_paise,
                    "students.higher_studies_pct": s.higher_studies_pct,
                    "academics.internships_pct": s.internships_pct,
                },
            },
            "institution",
            self.inst,
        )
        return s

    async def nirf_sheet(self, batch_id: uuid.UUID | None) -> bytes:
        from openpyxl import Workbook

        s = await self.stats(batch_id, None, None)
        wb = Workbook()
        ws = wb.active
        ws.title = "Placement & higher studies"
        ws.append(
            [
                "Programme",
                "No. of graduating students",
                "No. placed",
                "Median salary (INR)",
                "No. selected for higher studies",
            ]
        )
        for r in s.nirf_rows:
            ws.append(
                [r["program"], r["graduating_students"], r["placed"], r["median_salary_inr"], r["higher_studies"]]
            )
        ws.append([])
        ws.append(
            [
                "Total",
                s.eligible,
                s.placed,
                round(s.median_ctc_paise / 100) if s.median_ctc_paise else None,
                s.higher_studies,
            ]
        )
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    async def report(self, kind: str) -> bytes:
        from openpyxl import Workbook

        self._require()
        wb = Workbook()
        ws = wb.active
        ws.title = kind
        if kind == "drives":
            ws.append(["Company", "Title", "Status", "Drive on", "CTC min (paise)", "Mode"])
            for d, c in (
                await self.db.execute(
                    select(PlacementDrive, Company.name)
                    .join(Company, Company.id == PlacementDrive.company_id)
                    .where(PlacementDrive.institution_id == self.inst)
                )
            ).all():
                ws.append([c, d.title, d.status, d.drive_on, d.ctc_min_paise, d.mode])
        elif kind == "offers":
            ws.append(["Company", "Role", "CTC (paise)", "Status", "PPO", "Offered on", "Joining on"])
            for o, c in (
                await self.db.execute(
                    select(PlacementOffer, Company.name)
                    .join(Company, Company.id == PlacementOffer.company_id)
                    .where(PlacementOffer.institution_id == self.inst)
                )
            ).all():
                ws.append([c, o.role, o.ctc_paise, o.status, o.is_ppo, o.offered_on, o.joining_on])
        elif kind == "internships":
            ws.append(["Company", "Role", "From", "To", "Status", "NOC issued", "Marks"])
            for i in (
                await self.db.execute(select(Internship).where(Internship.institution_id == self.inst))
            ).scalars():
                ws.append(
                    [
                        i.company_name,
                        i.role,
                        i.from_on,
                        i.to_on,
                        i.status,
                        bool(i.noc_document_id),
                        (i.evaluation or {}).get("marks"),
                    ]
                )
        else:
            ws.append(["Programme", "Type", "Trainer", "From", "To", "Participants"])
            for p in (
                await self.db.execute(select(TrainingProgram).where(TrainingProgram.institution_id == self.inst))
            ).scalars():
                n = len(
                    (
                        await self.db.execute(
                            select(TrainingAttendance.id).where(TrainingAttendance.program_id == p.id)
                        )
                    ).all()
                )
                ws.append([p.title, p.training_type, p.trainer, p.from_on, p.to_on, n])
        buf = io.BytesIO()
        wb.save(buf)
        await self._audit("export", "placement_report", None, None, {"kind": kind})
        return buf.getvalue()
