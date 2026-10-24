"""OBE attainment enums — Prompts/17 §17.3 (values from the section 17 column comments)."""

from enum import StrEnum
from typing import Any


class ConfigScope(StrEnum):
    REGULATION = "regulation"
    PROGRAM = "program"


class RunScope(StrEnum):
    OFFERING = "offering"
    PROGRAM_BATCH = "program_batch"


class RunStatus(StrEnum):
    QUEUED = "queued"
    COMPUTED = "computed"
    FAILED = "failed"


class CqiStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    VERIFIED = "verified"


class CqiScope(StrEnum):
    OFFERING = "offering"
    COURSE = "course"
    PROGRAM = "program"


class EseStrategy(StrEnum):
    QUESTION_WISE = "question_wise"
    QP_PATTERN = "qp_pattern"
    UNIFORM = "uniform"


# owner moves an action between the working states; done -> verified only through ``verify`` (HOD / OBE coordinator)
CQI_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "planned": ("in_progress", "done"),
    "in_progress": ("planned", "done"),
    "done": ("in_progress",),
    "verified": (),
}

# platform default config (``platform_settings['attainment_defaults']``, migration 0017)
ATTAINMENT_DEFAULTS: dict[str, Any] = {
    "target_student_pct": 60,
    "target_marks_pct": 60,
    "levels": [{"level": 1, "min_pct": 40}, {"level": 2, "min_pct": 50}, {"level": 3, "min_pct": 60}],
    "direct_weight": 80,
    "indirect_weight": 20,
    "cia_weight_in_direct": 30,
    "ese_weight_in_direct": 70,
    "co_target_level": 2.0,
    "po_target_level": 2.0,
    "ese_apportion_strategy": "question_wise",
    "credit_weighted_po": False,
    # survey mean (1-5 scale) -> level: >= 2 -> 1, >= 3 -> 2, >= 4 -> 3
    "survey_thresholds": [{"level": 1, "min_mean": 2.0}, {"level": 2, "min_mean": 3.0}, {"level": 3, "min_mean": 4.0}],
}

CO_SURVEY_TYPES = ("course_exit",)
PO_SURVEY_TYPES = ("program_exit", "alumni", "employer")
