"""``RulesResolver`` — Prompts/05 §05.6 ``regulation_service`` rule 5, exposed for later phases.

``rules_effective(program_regulation)`` = ``regulation.rules ⊕ program_regulation.rules_override`` validated through
``RegulationRules`` (so every key is present with its default). Attendance (Phase 11), exams (14), results (15),
standing/promotion (07) and degrees (18) read their thresholds here — never from ``regulations.rules`` directly::

    rules = await RulesResolver(db).for_program_regulation(pr_id)
    rules["attendance_min_pct"]
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.academic import ProgramRegulation, Regulation
from app.schemas.academics import RegulationRules, merge_rules


def effective(rules: dict[str, Any] | None, override: dict[str, Any] | None) -> dict[str, Any]:
    return RegulationRules.model_validate(merge_rules(rules or {}, override)).model_dump(mode="json")


class RulesResolver:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def for_program_regulation(self, program_regulation_id: uuid.UUID) -> dict[str, Any]:
        row = (
            await self.db.execute(
                select(Regulation.rules, ProgramRegulation.rules_override)
                .join(ProgramRegulation, ProgramRegulation.regulation_id == Regulation.id)
                .where(ProgramRegulation.id == program_regulation_id)
            )
        ).first()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Programme-regulation not found")
        return effective(row[0], row[1])

    async def for_regulation(
        self, regulation_id: uuid.UUID, program_id: uuid.UUID | None = None
    ) -> tuple[dict[str, Any], ProgramRegulation | None]:
        reg = (await self.db.execute(select(Regulation).where(Regulation.id == regulation_id))).scalar_one_or_none()
        if reg is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Regulation not found")
        binding = None
        if program_id is not None:
            binding = (
                await self.db.execute(
                    select(ProgramRegulation).where(
                        ProgramRegulation.regulation_id == regulation_id,
                        ProgramRegulation.program_id == program_id,
                        ProgramRegulation.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if binding is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "The programme is not bound to this regulation")
        return effective(reg.rules, binding.rules_override if binding else None), binding


async def rules_effective(db: AsyncSession, program_regulation_id: uuid.UUID) -> dict[str, Any]:
    return await RulesResolver(db).for_program_regulation(program_regulation_id)
