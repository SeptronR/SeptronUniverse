"""Training programmes — Prompts/28 §28.6 ``training_service`` ({placement.training}).

Programmes (aptitude / soft skills / technical / mock interviews) with trainer / vendor, target batches and sessions;
attendance and scores in bulk (by enrolment id or registration number, partial-success report); the readiness score
per student is the average score across programmes (shown on the placement profile); vendor cost kept in the side
store for the accountant (Phase 23 expense optional); daily session reminders.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.models.placement import TrainingAttendance, TrainingProgram
from app.models.students import StudentProgramEnrollment
from app.schemas.placement import (
    PlcBulkReport,
    TrnAttendanceBulk,
    TrnMyRow,
    TrnProgramIn,
    TrnProgramOut,
    TrnProgramUpdate,
    TrnScoresBulk,
)
from app.services.placement.common import PlacementBase, forbidden, not_found


class TrainingService(PlacementBase):
    async def outs(self, rows: list[TrainingProgram]) -> list[TrnProgramOut]:
        stats: dict[uuid.UUID, tuple[int, float | None]] = {}
        if rows:
            for pid, n, avg in (
                await self.db.execute(
                    select(TrainingAttendance.program_id, func.count(), func.avg(TrainingAttendance.score))
                    .where(TrainingAttendance.program_id.in_([r.id for r in rows]))
                    .group_by(TrainingAttendance.program_id)
                )
            ).all():
                stats[pid] = (int(n), round(float(avg), 2) if avg is not None else None)
        costs = (
            await self.metas("training", [str(r.id) for r in rows])
            if self.officer() or self.can("placement", "view")
            else {}
        )
        return [
            TrnProgramOut(
                id=r.id,
                training_type=r.training_type,
                title=r.title,
                trainer=r.trainer,
                from_on=r.from_on,
                to_on=r.to_on,
                batches=list(r.batches or []),
                sessions=list(r.sessions or []),
                participants=stats.get(r.id, (0, None))[0],
                avg_score=stats.get(r.id, (0, None))[1],
                vendor_cost_paise=(costs.get(str(r.id)) or {}).get("vendor_cost_paise"),
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def list_programs(self) -> list[TrnProgramOut]:
        if not (self.officer() or self.reader() or self.can("placement", "view")):
            raise forbidden()
        rows = list(
            (
                await self.db.execute(
                    select(TrainingProgram)
                    .where(TrainingProgram.institution_id == self.inst)
                    .order_by(TrainingProgram.from_on.desc().nullslast())
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def _get(self, pid: uuid.UUID) -> TrainingProgram:
        p = (
            await self.db.execute(
                select(TrainingProgram).where(TrainingProgram.id == pid, TrainingProgram.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if p is None:
            raise not_found("Training programme")
        return p

    async def create(self, body: TrnProgramIn) -> TrnProgramOut:
        self.require_officer("manage")
        p = TrainingProgram(
            institution_id=self.inst,
            training_type=body.training_type,
            title=body.title,
            trainer=body.trainer,
            from_on=body.from_on,
            to_on=body.to_on,
            batches=[str(b) for b in body.batches],
            sessions=[s.model_dump(mode="json") for s in body.sessions],
        )
        self.db.add(p)
        await self.db.flush()
        if body.vendor_cost_paise is not None:
            await self.put_meta("training", p.id, {"vendor_cost_paise": body.vendor_cost_paise})
        await self._audit("create", "training_program", p.id, None, body.model_dump(mode="json"))
        await self._emit("training.scheduled", {"program_id": str(p.id)}, "training_program", p.id)
        return (await self.outs([p]))[0]

    async def update(self, pid: uuid.UUID, body: TrnProgramUpdate) -> TrnProgramOut:
        self.require_officer("manage")
        p = await self._get(pid)
        data = body.model_dump(exclude_unset=True)
        for k, v in data.items():
            if k == "vendor_cost_paise":
                await self.put_meta("training", p.id, {"vendor_cost_paise": v})
            elif k == "batches":
                p.batches = [str(b) for b in v or []]
            elif k == "sessions":
                p.sessions = [s.model_dump(mode="json") for s in body.sessions or []]
            else:
                setattr(p, k, v)
        await self.db.flush()
        await self._audit("update", "training_program", p.id, None, body.model_dump(mode="json", exclude_unset=True))
        return (await self.outs([p]))[0]

    async def _rows(self, p: TrainingProgram, rows: list[Any]) -> tuple[dict[int, uuid.UUID], list[dict[str, Any]]]:
        regs = await self.enrollment_by_reg([r.registration_number for r in rows if r.registration_number])
        found: dict[int, uuid.UUID] = {}
        failed: list[dict[str, Any]] = []
        for i, r in enumerate(rows):
            eid = r.enrollment_id or (regs.get(r.registration_number.strip()) if r.registration_number else None)
            if eid is None:
                failed.append({"row": i, "key": r.registration_number, "error": "NOT_FOUND"})
            else:
                found[i] = eid
        return found, failed

    async def _upsert(self, pid: uuid.UUID, eid: uuid.UUID) -> TrainingAttendance:
        ta = (
            await self.db.execute(
                select(TrainingAttendance).where(
                    TrainingAttendance.program_id == pid, TrainingAttendance.student_program_enrollment_id == eid
                )
            )
        ).scalar_one_or_none()
        if ta is None:
            ta = TrainingAttendance(institution_id=self.inst, program_id=pid, student_program_enrollment_id=eid)
            self.db.add(ta)
        return ta

    async def attendance(self, pid: uuid.UUID, body: TrnAttendanceBulk) -> PlcBulkReport:
        self.require_officer("manage")
        p = await self._get(pid)
        found, failed = await self._rows(p, body.rows)
        total = len(p.sessions or [])
        for i, eid in found.items():
            ta = await self._upsert(p.id, eid)
            n = body.rows[i].sessions_attended
            ta.sessions_attended = min(n, total) if total else n
        await self.db.flush()
        await self._audit("attendance", "training_program", p.id, None, {"rows": len(found)})
        await self._emit(
            "training.attendance_marked", {"program_id": str(p.id), "rows": len(found)}, "training_program", p.id
        )
        return PlcBulkReport(processed=len(body.rows), succeeded=len(found), failed=failed)

    async def scores(self, pid: uuid.UUID, body: TrnScoresBulk) -> PlcBulkReport:
        self.require_officer("manage")
        p = await self._get(pid)
        found, failed = await self._rows(p, body.rows)
        for i, eid in found.items():
            ta = await self._upsert(p.id, eid)
            ta.score = body.rows[i].score
        await self.db.flush()
        await self._audit("scores", "training_program", p.id, None, {"rows": len(found)})
        await self._emit("training.scored", {"program_id": str(p.id), "rows": len(found)}, "training_program", p.id)
        return PlcBulkReport(processed=len(body.rows), succeeded=len(found), failed=failed)

    async def mine(self) -> list[TrnMyRow]:
        ids = await self.my_enrollment_ids() + await self.ward_enrollment_ids()
        enrols = list(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment).where(StudentProgramEnrollment.id.in_(ids or [uuid.uuid4()]))
                )
            ).scalars()
        )
        batches = {str(e.batch_id) for e in enrols}
        att = {
            ta.program_id: ta
            for ta in (
                await self.db.execute(
                    select(TrainingAttendance).where(
                        TrainingAttendance.student_program_enrollment_id.in_(ids or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        out = []
        for p in (
            await self.db.execute(select(TrainingProgram).where(TrainingProgram.institution_id == self.inst))
        ).scalars():
            if p.id not in att and not (batches & set(p.batches or [])):
                continue
            ta = att.get(p.id)
            out.append(
                TrnMyRow(
                    program_id=p.id,
                    title=p.title,
                    training_type=p.training_type,
                    from_on=p.from_on,
                    to_on=p.to_on,
                    sessions=list(p.sessions or []),
                    sessions_attended=ta.sessions_attended if ta else 0,
                    score=float(ta.score) if ta and ta.score is not None else None,
                )
            )
        return out

    async def session_reminders(self) -> int:
        """Daily: sessions in the next 24 h → students of the programme's batches."""
        now = datetime.now(UTC)
        soon = now + timedelta(hours=24)
        n = 0
        for p in (
            await self.db.execute(select(TrainingProgram).where(TrainingProgram.institution_id == self.inst))
        ).scalars():
            for s in p.sessions or []:
                try:
                    at = datetime.fromisoformat(str(s.get("at")))
                except ValueError:
                    continue
                if at.tzinfo is None:
                    at = at.replace(tzinfo=UTC)
                if not (now <= at <= soon) or not p.batches:
                    continue
                enrols = (
                    await self.db.execute(
                        select(StudentProgramEnrollment.id).where(
                            StudentProgramEnrollment.batch_id.in_([uuid.UUID(b) for b in p.batches]),
                            StudentProgramEnrollment.status == "active",
                        )
                    )
                ).all()
                cards = await self.enrollment_cards([r[0] for r in enrols])
                await self._notify(
                    "training.session_reminder",
                    [c.get("user_id") for c in cards.values()],
                    {"title": p.title, "topic": s.get("topic") or "", "at": at.strftime("%d %b %H:%M")},
                )
                n += 1
        return n
