"""Payroll remuneration sources — Prompts/06 §06.6 payroll rule 3 ("remuneration lines pulled from sources").

A source is ``async def fn(db, staff, month, year) -> list[RemunerationLine]``; ``PayrollService.generate`` calls every
registered source for every staff member of the run and adds the lines as ``staff_payroll_items`` (``source_type`` /
``source_id`` keep the provenance; a line whose ``(source_type, source_id)`` is already on another payroll is skipped,
so a regenerated draft never pays a line twice). Phase 06 registers leave encashment; exam-duty remuneration
(Phases 14/15), guest-faculty hours from the timetable (Phase 10) and scholar fellowships (Phase 31) register theirs.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RemunerationLine:
    label: str
    amount_paise: int
    source_type: str
    source_id: uuid.UUID | None
    component_type: str = "earning"  # earning | deduction | reimbursement


RemunerationSource = Callable[[Any, Any, int, int], Awaitable[list[RemunerationLine]]]
REMUNERATION_SOURCES: dict[str, RemunerationSource] = {}


def remuneration_source(name: str) -> Callable[[RemunerationSource], RemunerationSource]:
    def deco(fn: RemunerationSource) -> RemunerationSource:
        REMUNERATION_SOURCES[name] = fn
        return fn

    return deco
