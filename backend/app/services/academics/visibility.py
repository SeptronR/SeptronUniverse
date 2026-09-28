"""Visibility registrations of Phase 05 (Prompts/05 §05.5 "Visibility registrations for the five modules").

``programs``, ``regulations``, ``courses``, ``curriculum`` and ``batches`` are **institution-wide readable** by staff
(``*:view`` in the staff self-service grants), so no self predicates / ownership links are registered and reads do
not apply ``visible()``; the scope columns drive ``meta.visibility`` tabs and the write narrowing in
``academics.context``. Students and parents read the curriculum of their own programme-regulation through their
enrolment — Phase 07 registers that link. ``grading`` (scales + schemes) is configuration read by the same staff.
"""

from app.core.authz.visibility import ModuleVisibility, register_module
from app.models.academic import Batch, GradingScale, Program, ProgramRegulation, Regulation
from app.models.curriculum import Course

register_module(
    ModuleVisibility(
        module="programs",
        model=Program,
        scope_columns={
            "institution": "institution_id",
            "college": "college_id",
            "faculty": "faculty_id",
            "department": "department_id",
        },
    )
)
register_module(
    ModuleVisibility(
        module="regulations", model=Regulation, scope_columns={"institution": "institution_id", "college": "college_id"}
    )
)
register_module(
    ModuleVisibility(
        module="courses",
        model=Course,
        scope_columns={"institution": "institution_id", "college": "college_id", "department": "department_id"},
    )
)
register_module(
    ModuleVisibility(module="curriculum", model=ProgramRegulation, scope_columns={"institution": "institution_id"})
)
register_module(
    ModuleVisibility(
        module="batches", model=Batch, scope_columns={"institution": "institution_id", "college": "college_id"}
    )
)
register_module(ModuleVisibility(module="grading", model=GradingScale, scope_columns={"institution": "institution_id"}))
