"""NBA SAR Criterion 3 export — Prompts/17 §17.6 ``nba_export_service`` (feature ``obe.nba_export``).

``submit`` enqueues ``obe.nba_export`` (202 + job id); ``build`` writes the workbook / document and stores it under
``<institution>/obe-exports/`` (job ``result_url``):

* **3.1** CO statements and the CO-PO / PSO matrix of every contributing course (levels 1–3);
* **3.2** CO attainment per course (latest computed run of the batch's offering: CIA / ESE / direct / indirect /
  final / target / gap);
* **3.3** PO / PSO attainment with the direct / indirect split, target and gap (latest programme-batch run);
* **CQI** — actions of the programme and its offerings (status, owner, due, gap before / after).

XLSX via ``openpyxl``; DOCX via ``app/utils/docx_lite`` (python-docx is not a dependency). The values are the ones the
API returns (same services), so a spot-check of two cells matches ``GET /programs/{id}/attainment``.
"""

import io
import uuid
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.core.files import build_key, storage
from app.models.curriculum import Course
from app.models.obe import CoPoMapping, CourseOutcome
from app.models.platform import BackgroundJob
from app.schemas.obe_attainment import ExportJob, NbaExportRequest
from app.services.obe.co_service import CoAttainmentService
from app.services.obe.common import ObeBase
from app.services.obe.cqi_service import CqiService
from app.services.obe.po_service import PoAttainmentService


class NbaExportService(ObeBase):
    async def submit(self, body: NbaExportRequest) -> ExportJob:
        from app.core.jobs import enqueue

        program = await self.att_program(body.program_id)
        await self.batch_of(program, body.batch_id)
        job = await enqueue(self.db, self.principal, "obe.nba_export", body.model_dump(mode="json"), queue="documents")
        return ExportJob(job_id=job.id, status=job.status, progress=0)

    async def job(self, job_id: uuid.UUID) -> ExportJob:
        j = (
            await self.db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.id == job_id,
                    BackgroundJob.institution_id == self.inst,
                    BackgroundJob.job_type == "obe.nba_export",
                )
            )
        ).scalar_one_or_none()
        if j is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Export not found")
        url = storage.signed_url(j.result_url) if j.result_url else None
        return ExportJob(job_id=j.id, status=j.status, progress=j.progress_pct, file_url=url, result=j.result)

    async def tables(self, program_id: uuid.UUID, batch_id: uuid.UUID) -> dict[str, Any]:
        po_svc = PoAttainmentService(self.db, self.principal, self.request, self.inst)
        co_svc = CoAttainmentService(self.db, self.principal, self.request, self.inst)
        po = await po_svc.get(program_id, batch_id)
        outcome_codes = [o.outcome for o in po.outcomes]
        offering_ids: dict[str, str] = {}
        for o in po.outcomes:
            for c in o.breakdown:
                offering_ids[c["course_id"]] = c["offering_id"]
        t31: list[list[Any]] = []
        t32: list[list[Any]] = []
        for course_id, offering_id in offering_ids.items():
            course = (await self.db.execute(select(Course).where(Course.id == uuid.UUID(course_id)))).scalar_one()
            cos = (
                (
                    await self.db.execute(
                        select(CourseOutcome)
                        .where(CourseOutcome.course_id == course.id)
                        .order_by(CourseOutcome.sequence)
                    )
                )
                .scalars()
                .all()
            )
            maps = (
                await self.db.execute(
                    select(CoPoMapping.course_outcome_id, CoPoMapping.outcome_id, CoPoMapping.level).where(
                        CoPoMapping.course_outcome_id.in_([c.id for c in cos] or [uuid.uuid4()])
                    )
                )
            ).all()
            code_of = {o.outcome_id: o.outcome for o in po.outcomes}
            lvl = {(m[0], code_of.get(m[1])): m[2] for m in maps}
            for co in cos:
                t31.append([course.code, co.code, co.statement, *[lvl.get((co.id, oc)) for oc in outcome_codes]])
            data = await co_svc.get(uuid.UUID(offering_id))
            for r in data.cos:
                t32.append(
                    [
                        course.code,
                        r.co,
                        r.students_assessed,
                        r.cia_level,
                        r.ese_level,
                        r.direct_level,
                        r.indirect_level,
                        r.final_level,
                        r.target,
                        r.gap,
                    ]
                )
        t33 = [
            [o.outcome, o.outcome_type, o.direct, o.indirect, o.final, o.target, o.gap, o.contributing_courses]
            for o in po.outcomes
        ]
        cqi_svc = CqiService(self.db, self.principal, self.request, self.inst)
        actions = await cqi_svc.list(scope_type="program", scope_id=program_id)
        for oid in set(offering_ids.values()):
            actions += await cqi_svc.list(scope_type="offering", scope_id=uuid.UUID(oid))
        cqi = [
            [a.scope_label, a.outcome, a.gap, a.action_text, a.owner_name, a.due_on, a.status, a.gap_after]
            for a in actions
        ]
        return {
            "program": po.program.code,
            "batch": po.batch.code,
            "outcomes": outcome_codes,
            "coverage_pct": po.coverage_pct,
            "3.1": t31,
            "3.2": t32,
            "3.3": t33,
            "CQI": cqi,
        }

    HEADERS = {
        "3.2": ["Course", "CO", "Assessed", "CIA", "ESE", "Direct", "Indirect", "Final", "Target", "Gap"],
        "3.3": ["Outcome", "Type", "Direct", "Indirect", "Final", "Target", "Gap", "Courses"],
        "CQI": ["Scope", "Outcome", "Gap", "Action", "Owner", "Due", "Status", "Gap after"],
    }

    async def build(self, body: NbaExportRequest) -> dict[str, Any]:
        t = await self.tables(body.program_id, body.batch_id)
        headers = {"3.1": ["Course", "CO", "Statement", *t["outcomes"]], **self.HEADERS}
        titles = {
            "3.1": "3.1 Course outcomes and CO-PO/PSO matrix",
            "3.2": "3.2 Attainment of course outcomes",
            "3.3": "3.3 Attainment of programme outcomes and programme specific outcomes",
            "CQI": "Continuous quality improvement actions",
        }
        if body.format == "docx":
            from app.utils.docx_lite import DocxLite

            doc = DocxLite()
            doc.heading(f"NBA SAR — Criterion 3 · {t['program']} · batch {t['batch']}")
            for k in ("3.1", "3.2", "3.3", "CQI"):
                doc.heading(titles[k], 2)
                doc.table(headers[k], t[k])
            data, ext, ctype = (
                doc.to_bytes(),
                "docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        else:
            from openpyxl import Workbook
            from openpyxl.styles import Font

            wb = Workbook()
            wb.remove(wb.active)
            for k in ("3.1", "3.2", "3.3", "CQI"):
                ws = wb.create_sheet(k)
                ws.append([titles[k]])
                ws["A1"].font = Font(bold=True)
                ws.append(headers[k])
                for cell in ws[2]:
                    cell.font = Font(bold=True)
                for row in t[k]:
                    ws.append([v.isoformat() if hasattr(v, "isoformat") else v for v in row])
            buf = io.BytesIO()
            wb.save(buf)
            data, ext, ctype = (
                buf.getvalue(),
                "xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        key = build_key(self.inst, "obe-exports", f"nba-sar-{t['program']}-{t['batch']}-{uuid.uuid4().hex[:8]}.{ext}")
        await storage.put(key, data, ctype)
        await self._audit("nba_export", "attainment_export", body.program_id, None, {"key": key, "format": ext})
        await self._emit(
            "obe.export_generated",
            {"program_id": str(body.program_id), "batch_id": str(body.batch_id), "key": key},
            "program",
            body.program_id,
        )
        return {"result_url": key, "format": ext, "rows": {k: len(t[k]) for k in ("3.1", "3.2", "3.3", "CQI")}}
