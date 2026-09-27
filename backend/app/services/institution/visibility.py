"""Visibility registrations of Phase 03 (Prompts/03 "Visibility rules"; docs/Authorization_and_Visibility.md).

Institution structure is **institution-wide readable**: every member holds ``institutions:view`` and the read routes
accept it, so these modules register no ownership links — the resolver's institution predicate (plus RLS) is the whole
read rule and the repositories do not apply ``visible()`` to reads. Writes are narrowed by the college scope
(``context.writable_college_ids``): ``college_admin`` @college edits only its own college, its faculties,
departments, years/terms and holidays; out-of-scope rows answer 404 on the write lookup.
"""

from app.core.authz.visibility import ModuleVisibility, register_module
from app.models.academic import AcademicYear
from app.models.platform import College, Department, Faculty, Holiday

register_module(
    ModuleVisibility(module="colleges", model=College, scope_columns={"institution": "institution_id", "college": "id"})
)
register_module(
    ModuleVisibility(
        module="faculties",
        model=Faculty,
        scope_columns={"institution": "institution_id", "college": "college_id", "faculty": "id"},
    )
)
register_module(
    ModuleVisibility(
        module="departments",
        model=Department,
        scope_columns={
            "institution": "institution_id",
            "college": "college_id",
            "faculty": "faculty_id",
            "department": "id",
        },
    )
)
register_module(
    ModuleVisibility(
        module="sessions", model=AcademicYear, scope_columns={"institution": "institution_id", "college": "college_id"}
    )
)
register_module(
    ModuleVisibility(
        module="holidays", model=Holiday, scope_columns={"institution": "institution_id", "college": "college_id"}
    )
)
