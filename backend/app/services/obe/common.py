"""Shared plumbing of the Phase 17 services — on the Phase 13 ``AssessmentBase`` (offering roster, teacher check,
tenant / audit / outbox / notifications / settings).

* ``att_offering(id)`` — an offering whose attainment the caller may read (``attainment_scope.offering_predicate``;
  404 otherwise, never 403); ``require_compute(offering)`` — its faculty / coordinator or a unit holder of
  ``obe:compute|manage``;
* ``att_program(id)`` / ``batch_of(program, id)`` — programme-anchored reads;
* ``level_for(pct, bands)`` — 0 below band 1, else the highest band whose ``min_pct`` is reached;
  ``survey_level(mean, thresholds)`` likewise for survey means; ``d2`` rounds levels to 2 places (``NUMERIC(3,2)``).
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.academic import Batch, Program
from app.models.curriculum import Course
from app.models.hr import Staff
from app.models.offerings import CourseOffering
from app.repositories.attainment_scope import offering_predicate, program_predicate
from app.schemas.obe_attainment import BatchRef, OfferingRef, ProgramRef, RunSummary
from app.services.assessment.common import AssessmentBase


def d2(v: Any) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def f2(v: Any) -> float | None:
    return None if v is None else float(d2(v))  # type: ignore[arg-type]


def level_for(pct: float, bands: list[dict[str, Any]]) -> int:
    level = 0
    for b in sorted(bands, key=lambda x: float(x["min_pct"])):
        if pct >= float(b["min_pct"]):
            level = int(b["level"])
    return level


def survey_level(mean: float, thresholds: list[dict[str, Any]]) -> int:
    level = 0
    for t in sorted(thresholds, key=lambda x: float(x["min_mean"])):
        if mean >= float(t["min_mean"]):
            level = int(t["level"])
    return level


def run_summary(run: Any) -> RunSummary | None:
    if run is None:
        return None
    snap = run.config_snapshot or {}
    return RunSummary(
        id=run.id,
        status=run.status,
        run_at=run.run_at,
        run_by=run.run_by,
        warnings=list(snap.get("_warnings") or []),
        config_snapshot={k: v for k, v in snap.items() if not k.startswith("_")},
    )


class ObeBase(AssessmentBase):
    audit_module = "obe"

    async def att_offering(self, offering_id: uuid.UUID) -> CourseOffering:
        row = (
            await self.db.execute(
                select(CourseOffering).where(
                    CourseOffering.id == offering_id,
                    CourseOffering.institution_id == self.inst,
                    CourseOffering.deleted_at.is_(None),
                    offering_predicate(self.principal),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course offering not found")
        return row

    async def is_coordinator(self, offering: CourseOffering) -> bool:
        if offering.coordinator_staff_id is None or self.principal is None:
            return False
        return offering.coordinator_staff_id in await self.my_staff_ids()

    async def my_staff_ids(self) -> set[uuid.UUID]:
        if self.principal is None or getattr(self.principal, "id", None) is None:
            return set()
        return set(
            (
                await self.db.execute(
                    select(Staff.id).where(Staff.user_id == self.principal.id, Staff.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )

    async def require_compute(self, offering: CourseOffering) -> None:
        if self.can("obe", "manage") or self.can("obe", "configure"):
            return
        if self.can("obe", "compute") and (await self.is_teacher(offering.id) or await self.is_coordinator(offering)):
            return
        # unit holders (HOD / dean) passed ``att_offering`` through their unit — compute is theirs too
        units = ("department", "faculty", "college", "institution")
        if self.can("obe", "compute") and any(t in units for t, _ in getattr(self.principal, "scopes", None) or []):
            return
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the offering's faculty or the OBE office may compute")

    async def att_program(self, program_id: uuid.UUID) -> Program:
        row = (
            await self.db.execute(
                select(Program).where(
                    Program.id == program_id, Program.institution_id == self.inst, program_predicate(self.principal)
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Programme not found")
        return row

    async def batch_of(self, program: Program, batch_id: uuid.UUID) -> Batch:
        row = (
            await self.db.execute(select(Batch).where(Batch.id == batch_id, Batch.program_id == program.id))
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Batch not found for this programme")
        return row

    async def offering_ref(self, o: CourseOffering) -> OfferingRef:
        c = (await self.db.execute(select(Course).where(Course.id == o.course_id))).scalar_one_or_none()
        return OfferingRef(
            id=o.id,
            course_id=o.course_id,
            course_code=c.code if c else None,
            course_title=c.title if c else None,
            section_code=o.section_code,
            term_id=o.term_id,
        )

    @staticmethod
    def program_ref(p: Program) -> ProgramRef:
        return ProgramRef(id=p.id, code=p.code, name=p.name)

    @staticmethod
    def batch_ref(b: Batch) -> BatchRef:
        return BatchRef(id=b.id, code=b.code, admission_year=b.admission_year)
